"""Local SQLite database engine for Wine Inventory."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .const import (
    DRINK_STATUS_DRINK_SOON,
    DRINK_STATUS_HOLD,
    DRINK_STATUS_PAST_PEAK,
    DRINK_STATUS_READY,
    DRINK_STATUS_UNKNOWN,
    WINE_TYPE_RED,
    WINE_TYPES,
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_drink_status(
    drink_from_year: int | None,
    drink_until_year: int | None,
    reference_year: int | None = None,
) -> str:
    """Compute drinking readiness status from structured drink window years."""
    current_year = reference_year or datetime.now(timezone.utc).year
    if drink_from_year is None and drink_until_year is None:
        return DRINK_STATUS_UNKNOWN

    if drink_from_year is not None and current_year < drink_from_year:
        return DRINK_STATUS_HOLD

    if drink_until_year is not None:
        if current_year > drink_until_year:
            return DRINK_STATUS_PAST_PEAK
        if (drink_until_year - current_year) <= 1:
            return DRINK_STATUS_DRINK_SOON

    return DRINK_STATUS_READY


class WineDatabase:
    """SQLite database manager for the Home Assistant Wine Inventory."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the database manager with a file path."""
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        """Create a SQLite connection configured with Row factory and WAL mode."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def initialize(self) -> None:
        """Create schema tables and indexes if they do not exist."""
        with closing(self._connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    winery TEXT NOT NULL,
                    name TEXT NOT NULL,
                    vintage INTEGER NULL,
                    wine_type TEXT NOT NULL DEFAULT 'red',
                    varietal TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL DEFAULT '',
                    alcohol_pct REAL NULL,
                    bottle_size_ml INTEGER NOT NULL DEFAULT 750,
                    vivino_rating REAL NULL,
                    vivino_ratings_count INTEGER NULL,
                    vivino_url TEXT NOT NULL DEFAULT '',
                    vivino_price_estimate REAL NULL,
                    rating_source TEXT NOT NULL DEFAULT '',
                    drink_from_year INTEGER NULL,
                    drink_until_year INTEGER NULL,
                    drink_window_note TEXT NOT NULL DEFAULT '',
                    food_pairings TEXT NOT NULL DEFAULT '[]',
                    general_notes TEXT NOT NULL DEFAULT '',
                    personal_rating REAL NULL,
                    image_url TEXT NOT NULL DEFAULT '',
                    quantity INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_wines_lookup
                    ON wines (LOWER(winery), LOWER(name), IFNULL(vintage, 0));

                CREATE INDEX IF NOT EXISTS idx_wines_type_qty
                    ON wines (wine_type, quantity);

                CREATE TABLE IF NOT EXISTS inventory_additions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wine_id INTEGER NOT NULL REFERENCES wines(id) ON DELETE CASCADE,
                    quantity_added INTEGER NOT NULL,
                    quantity_remaining INTEGER NOT NULL,
                    added_at TEXT NOT NULL,
                    purchase_location TEXT NOT NULL DEFAULT '',
                    purchase_price REAL NULL,
                    storage_location TEXT NOT NULL DEFAULT '',
                    drink_window_note TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_additions_wine_id
                    ON inventory_additions (wine_id, added_at DESC);

                CREATE TABLE IF NOT EXISTS consumption_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wine_id INTEGER NOT NULL REFERENCES wines(id) ON DELETE CASCADE,
                    batch_id INTEGER NULL REFERENCES inventory_additions(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    purchase_location TEXT NOT NULL DEFAULT '',
                    storage_location TEXT NOT NULL DEFAULT '',
                    tasting_notes TEXT NOT NULL DEFAULT '',
                    personal_rating REAL NULL
                );

                CREATE INDEX IF NOT EXISTS idx_history_wine_id
                    ON consumption_history (wine_id, timestamp DESC);
                """
            )

    def checkpoint_wal(self) -> None:
        """Flush the SQLite Write-Ahead Log before a Home Assistant backup."""
        if not self.db_path.exists():
            return
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def _serialize_wine_row(
        self,
        row: sqlite3.Row,
        batches: list[dict[str, Any]] | None = None,
        timeline: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Convert a sqlite3.Row from wines into an enriched dict."""
        data = dict(row)
        try:
            pairings = json.loads(data.get("food_pairings") or "[]")
            if not isinstance(pairings, list):
                pairings = [str(pairings)]
        except (ValueError, TypeError):
            raw = data.get("food_pairings") or ""
            pairings = [p.strip() for p in str(raw).split(",") if p.strip()]

        data["food_pairings"] = pairings
        data["drink_status"] = compute_drink_status(
            data.get("drink_from_year"),
            data.get("drink_until_year"),
        )
        if batches is not None:
            data["batches"] = batches
            data["last_purchase_location"] = next(
                (b["purchase_location"] for b in batches if b.get("purchase_location")),
                "",
            )
            data["last_storage_location"] = next(
                (b["storage_location"] for b in batches if b.get("storage_location")),
                "",
            )
            data["last_purchase_price"] = next(
                (
                    b["purchase_price"]
                    for b in batches
                    if b.get("purchase_price") is not None
                ),
                None,
            )
            active_locations = sorted(
                {
                    b["storage_location"]
                    for b in batches
                    if b.get("storage_location") and b.get("quantity_remaining", 0) > 0
                }
            )
            data["active_storage_locations"] = active_locations
            data["latest_added_at"] = batches[0]["added_at"] if batches else data["created_at"]
        if timeline is not None:
            data["timeline"] = timeline
        return data

    def find_matching_wine(
        self,
        winery: str,
        name: str,
        vintage: int | None,
    ) -> dict[str, Any] | None:
        """Find an existing wine by normalized (winery, name, vintage)."""
        norm_winery = (winery or "").strip().lower()
        norm_name = (name or "").strip().lower()
        norm_vintage = int(vintage) if vintage else 0
        if not norm_winery and not norm_name:
            return None

        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM wines
                WHERE LOWER(TRIM(winery)) = ?
                  AND LOWER(TRIM(name)) = ?
                  AND IFNULL(vintage, 0) = ?
                LIMIT 1
                """,
                (norm_winery, norm_name, norm_vintage),
            ).fetchone()
            if row is None:
                return None
            return self.get_wine_detail(row["id"], _conn=conn)

    def get_wine_detail(
        self,
        wine_id: int,
        _conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a single wine with its batches and chronological notes timeline."""
        if _conn is not None:
            return self._get_wine_detail_with_conn(_conn, wine_id)
        with closing(self._connect()) as conn:
            return self._get_wine_detail_with_conn(conn, wine_id)

    def _get_wine_detail_with_conn(
        self,
        conn: sqlite3.Connection,
        wine_id: int,
    ) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM wines WHERE id = ?", (wine_id,)).fetchone()
        if row is None:
            return None
        batch_rows = conn.execute(
            """
            SELECT * FROM inventory_additions
            WHERE wine_id = ?
            ORDER BY added_at DESC, id DESC
            """,
            (wine_id,),
        ).fetchall()
        history_rows = conn.execute(
            """
            SELECT * FROM consumption_history
            WHERE wine_id = ?
            ORDER BY timestamp DESC, id DESC
            """,
            (wine_id,),
        ).fetchall()
        batches = [dict(b) for b in batch_rows]
        timeline = [dict(h) for h in history_rows]
        return self._serialize_wine_row(row, batches=batches, timeline=timeline)

    def add_or_increment_wine(
        self,
        *,
        winery: str,
        name: str,
        vintage: int | None = None,
        wine_type: str = WINE_TYPE_RED,
        varietal: str = "",
        region: str = "",
        country: str = "",
        alcohol_pct: float | None = None,
        bottle_size_ml: int = 750,
        vivino_rating: float | None = None,
        vivino_ratings_count: int | None = None,
        vivino_url: str = "",
        vivino_price_estimate: float | None = None,
        rating_source: str = "",
        drink_from_year: int | None = None,
        drink_until_year: int | None = None,
        drink_window_note: str = "",
        food_pairings: list[str] | str | None = None,
        general_notes: str = "",
        personal_rating: float | None = None,
        image_url: str = "",
        quantity: int = 1,
        added_at: str | None = None,
        purchase_location: str = "",
        purchase_price: float | None = None,
        storage_location: str = "",
        batch_notes: str = "",
        wine_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a new wine or add a purchase batch to an existing wine."""
        qty = max(1, int(quantity))
        timestamp = (added_at or "").strip() or utc_now_iso()
        normalized_type = (
            wine_type.lower().strip()
            if wine_type and wine_type.lower().strip() in WINE_TYPES
            else WINE_TYPE_RED
        )
        normalized_vintage = int(vintage) if vintage and int(vintage) > 0 else None

        if isinstance(food_pairings, list):
            pairings_json = json.dumps([str(p).strip() for p in food_pairings if str(p).strip()])
        elif isinstance(food_pairings, str) and food_pairings.strip():
            pairings_json = json.dumps(
                [p.strip() for p in food_pairings.split(",") if p.strip()]
            )
        else:
            pairings_json = "[]"

        with closing(self._connect()) as conn, conn:
            existing_row = None
            if wine_id is not None:
                existing_row = conn.execute(
                    "SELECT * FROM wines WHERE id = ?", (int(wine_id),)
                ).fetchone()
            if existing_row is None:
                existing_row = conn.execute(
                    """
                    SELECT * FROM wines
                    WHERE LOWER(TRIM(winery)) = ?
                      AND LOWER(TRIM(name)) = ?
                      AND IFNULL(vintage, 0) = ?
                    LIMIT 1
                    """,
                    (
                        winery.strip().lower(),
                        name.strip().lower(),
                        normalized_vintage or 0,
                    ),
                ).fetchone()

            if existing_row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO wines (
                        winery, name, vintage, wine_type, varietal, region, country,
                        alcohol_pct, bottle_size_ml, vivino_rating, vivino_ratings_count,
                        vivino_url, vivino_price_estimate, rating_source,
                        drink_from_year, drink_until_year, drink_window_note,
                        food_pairings, general_notes, personal_rating, image_url,
                        quantity, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        winery.strip(),
                        name.strip(),
                        normalized_vintage,
                        normalized_type,
                        varietal.strip(),
                        region.strip(),
                        country.strip(),
                        alcohol_pct,
                        int(bottle_size_ml or 750),
                        vivino_rating,
                        vivino_ratings_count,
                        vivino_url.strip(),
                        vivino_price_estimate,
                        rating_source.strip(),
                        drink_from_year,
                        drink_until_year,
                        drink_window_note.strip(),
                        pairings_json,
                        general_notes.strip(),
                        personal_rating,
                        image_url.strip(),
                        qty,
                        timestamp,
                        timestamp,
                    ),
                )
                target_wine_id = int(cursor.lastrowid)
            else:
                target_wine_id = int(existing_row["id"])
                new_qty = int(existing_row["quantity"]) + qty
                updated_general_notes = (
                    general_notes.strip()
                    if general_notes.strip()
                    else existing_row["general_notes"]
                )
                conn.execute(
                    """
                    UPDATE wines
                    SET quantity = ?,
                        vivino_rating = COALESCE(?, vivino_rating),
                        vivino_ratings_count = COALESCE(?, vivino_ratings_count),
                        vivino_url = CASE WHEN ? != '' THEN ? ELSE vivino_url END,
                        vivino_price_estimate = COALESCE(?, vivino_price_estimate),
                        rating_source = CASE WHEN ? != '' THEN ? ELSE rating_source END,
                        drink_from_year = COALESCE(?, drink_from_year),
                        drink_until_year = COALESCE(?, drink_until_year),
                        drink_window_note = CASE WHEN ? != '' THEN ? ELSE drink_window_note END,
                        general_notes = ?,
                        personal_rating = COALESCE(?, personal_rating),
                        image_url = CASE WHEN ? != '' THEN ? ELSE image_url END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        new_qty,
                        vivino_rating,
                        vivino_ratings_count,
                        vivino_url.strip(),
                        vivino_url.strip(),
                        vivino_price_estimate,
                        rating_source.strip(),
                        rating_source.strip(),
                        drink_from_year,
                        drink_until_year,
                        drink_window_note.strip(),
                        drink_window_note.strip(),
                        updated_general_notes,
                        personal_rating,
                        image_url.strip(),
                        image_url.strip(),
                        timestamp,
                        target_wine_id,
                    ),
                )

            batch_cursor = conn.execute(
                """
                INSERT INTO inventory_additions (
                    wine_id, quantity_added, quantity_remaining, added_at,
                    purchase_location, purchase_price, storage_location,
                    drink_window_note, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_wine_id,
                    qty,
                    qty,
                    timestamp,
                    purchase_location.strip(),
                    purchase_price,
                    storage_location.strip(),
                    drink_window_note.strip(),
                    batch_notes.strip(),
                ),
            )
            batch_id = int(batch_cursor.lastrowid)

            conn.execute(
                """
                INSERT INTO consumption_history (
                    wine_id, batch_id, event_type, delta, timestamp,
                    purchase_location, storage_location, tasting_notes, personal_rating
                ) VALUES (?, ?, 'added', ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_wine_id,
                    batch_id,
                    qty,
                    timestamp,
                    purchase_location.strip(),
                    storage_location.strip(),
                    batch_notes.strip(),
                    personal_rating,
                ),
            )

            detail = self._get_wine_detail_with_conn(conn, target_wine_id)
            assert detail is not None
            return detail

    def adjust_quantity(
        self,
        *,
        wine_id: int,
        delta: int,
        batch_id: int | None = None,
        added_at: str | None = None,
        purchase_location: str = "",
        purchase_price: float | None = None,
        storage_location: str = "",
        drink_window_note: str = "",
        notes: str = "",
        personal_rating: float | None = None,
    ) -> dict[str, Any]:
        """Adjust bottle quantity (+N adds a batch; -N consumes from batch or FIFO)."""
        if delta == 0:
            detail = self.get_wine_detail(wine_id)
            if detail is None:
                raise ValueError(f"Wine ID {wine_id} not found")
            return detail

        if delta > 0:
            existing = self.get_wine_detail(wine_id)
            if existing is None:
                raise ValueError(f"Wine ID {wine_id} not found")
            return self.add_or_increment_wine(
                wine_id=wine_id,
                winery=existing["winery"],
                name=existing["name"],
                vintage=existing["vintage"],
                wine_type=existing["wine_type"],
                quantity=delta,
                added_at=added_at,
                purchase_location=purchase_location or existing.get("last_purchase_location", ""),
                purchase_price=purchase_price,
                storage_location=storage_location or existing.get("last_storage_location", ""),
                drink_window_note=drink_window_note,
                batch_notes=notes,
                personal_rating=personal_rating,
            )

        # Consuming (-N) bottles
        timestamp = (added_at or "").strip() or utc_now_iso()
        to_consume = abs(int(delta))

        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT * FROM wines WHERE id = ?", (wine_id,)).fetchone()
            if row is None:
                raise ValueError(f"Wine ID {wine_id} not found")

            current_qty = int(row["quantity"])
            actual_consumed = min(current_qty, to_consume) if current_qty > 0 else 0
            new_qty = max(0, current_qty - to_consume)

            used_location = storage_location.strip()
            used_store = purchase_location.strip()
            resolved_batch_id = batch_id

            if batch_id is not None:
                b_row = conn.execute(
                    "SELECT * FROM inventory_additions WHERE id = ? AND wine_id = ?",
                    (batch_id, wine_id),
                ).fetchone()
                if b_row is not None:
                    rem = max(0, int(b_row["quantity_remaining"]) - to_consume)
                    conn.execute(
                        "UPDATE inventory_additions SET quantity_remaining = ? WHERE id = ?",
                        (rem, batch_id),
                    )
                    used_location = used_location or b_row["storage_location"]
                    used_store = used_store or b_row["purchase_location"]
            else:
                # FIFO across batches with remaining quantity
                remaining_to_deduct = actual_consumed
                fifo_batches = conn.execute(
                    """
                    SELECT * FROM inventory_additions
                    WHERE wine_id = ? AND quantity_remaining > 0
                    ORDER BY added_at ASC, id ASC
                    """,
                    (wine_id,),
                ).fetchall()
                for b_row in fifo_batches:
                    if remaining_to_deduct <= 0:
                        break
                    avail = int(b_row["quantity_remaining"])
                    take = min(avail, remaining_to_deduct)
                    conn.execute(
                        "UPDATE inventory_additions SET quantity_remaining = ? WHERE id = ?",
                        (avail - take, b_row["id"]),
                    )
                    if resolved_batch_id is None:
                        resolved_batch_id = int(b_row["id"])
                    if not used_location and b_row["storage_location"]:
                        used_location = b_row["storage_location"]
                    if not used_store and b_row["purchase_location"]:
                        used_store = b_row["purchase_location"]
                    remaining_to_deduct -= take

            conn.execute(
                """
                UPDATE wines
                SET quantity = ?,
                    personal_rating = COALESCE(?, personal_rating),
                    updated_at = ?
                WHERE id = ?
                """,
                (new_qty, personal_rating, timestamp, wine_id),
            )

            conn.execute(
                """
                INSERT INTO consumption_history (
                    wine_id, batch_id, event_type, delta, timestamp,
                    purchase_location, storage_location, tasting_notes, personal_rating
                ) VALUES (?, ?, 'consumed', ?, ?, ?, ?, ?, ?)
                """,
                (
                    wine_id,
                    resolved_batch_id,
                    -actual_consumed if actual_consumed > 0 else delta,
                    timestamp,
                    used_store,
                    used_location,
                    notes.strip(),
                    personal_rating,
                ),
            )

            detail = self._get_wine_detail_with_conn(conn, wine_id)
            assert detail is not None
            return detail

    def update_wine(
        self,
        wine_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update editable metadata on a wine record."""
        allowed_fields = {
            "winery",
            "name",
            "vintage",
            "wine_type",
            "varietal",
            "region",
            "country",
            "alcohol_pct",
            "bottle_size_ml",
            "vivino_rating",
            "vivino_ratings_count",
            "vivino_url",
            "vivino_price_estimate",
            "rating_source",
            "drink_from_year",
            "drink_until_year",
            "drink_window_note",
            "food_pairings",
            "general_notes",
            "personal_rating",
            "image_url",
        }
        set_clauses: list[str] = []
        values: list[Any] = []

        for key, val in updates.items():
            if key not in allowed_fields:
                continue
            if key == "food_pairings":
                if isinstance(val, list):
                    val = json.dumps([str(x).strip() for x in val if str(x).strip()])
                elif isinstance(val, str):
                    val = json.dumps([x.strip() for x in val.split(",") if x.strip()])
            set_clauses.append(f"{key} = ?")
            values.append(val)

        if not set_clauses:
            detail = self.get_wine_detail(wine_id)
            if detail is None:
                raise ValueError(f"Wine ID {wine_id} not found")
            return detail

        set_clauses.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(wine_id)

        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                f"UPDATE wines SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Wine ID {wine_id} not found")
            detail = self._get_wine_detail_with_conn(conn, wine_id)
            assert detail is not None
            return detail

    def delete_wine(self, wine_id: int) -> bool:
        """Delete a wine record and its cascading batches and history."""
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("DELETE FROM wines WHERE id = ?", (wine_id,))
            return cursor.rowcount > 0

    def list_wines(
        self,
        *,
        include_out_of_stock: bool = True,
        wine_type: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all wines with batches and timeline metadata."""
        clauses: list[str] = []
        params: list[Any] = []

        if not include_out_of_stock:
            clauses.append("quantity > 0")
        if wine_type and wine_type.lower() in WINE_TYPES:
            clauses.append("LOWER(wine_type) = ?")
            params.append(wine_type.lower())
        if search and search.strip():
            q = f"%{search.strip().lower()}%"
            clauses.append(
                "("
                "LOWER(winery) LIKE ? OR "
                "LOWER(name) LIKE ? OR "
                "LOWER(varietal) LIKE ? OR "
                "LOWER(region) LIKE ? OR "
                "LOWER(country) LIKE ? OR "
                "LOWER(general_notes) LIKE ?"
                ")"
            )
            params.extend([q, q, q, q, q, q])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM wines {where_sql} ORDER BY updated_at DESC, id DESC",
                params,
            ).fetchall()
            if not rows:
                return []

            wine_ids = [int(r["id"]) for r in rows]
            placeholders = ",".join("?" for _ in wine_ids)
            batch_rows = conn.execute(
                f"""
                SELECT * FROM inventory_additions
                WHERE wine_id IN ({placeholders})
                ORDER BY added_at DESC, id DESC
                """,
                wine_ids,
            ).fetchall()
            history_rows = conn.execute(
                f"""
                SELECT * FROM consumption_history
                WHERE wine_id IN ({placeholders})
                ORDER BY timestamp DESC, id DESC
                """,
                wine_ids,
            ).fetchall()

            batches_by_wine: dict[int, list[dict[str, Any]]] = {wid: [] for wid in wine_ids}
            for b in batch_rows:
                batches_by_wine[int(b["wine_id"])].append(dict(b))

            history_by_wine: dict[int, list[dict[str, Any]]] = {wid: [] for wid in wine_ids}
            for h in history_rows:
                history_by_wine[int(h["wine_id"])].append(dict(h))

            return [
                self._serialize_wine_row(
                    r,
                    batches=batches_by_wine[int(r["id"])],
                    timeline=history_by_wine[int(r["id"])],
                )
                for r in rows
            ]

    def get_statistics(self) -> dict[str, Any]:
        """Compute aggregate cellar metrics for Home Assistant sensors and UI."""
        wines = self.list_wines(include_out_of_stock=True)
        in_stock = [w for w in wines if int(w["quantity"]) > 0]
        archived = [w for w in wines if int(w["quantity"]) == 0]

        total_bottles = sum(int(w["quantity"]) for w in in_stock)
        unique_wines_in_stock = len(in_stock)

        by_type: dict[str, int] = {t: 0 for t in WINE_TYPES}
        ready_to_drink_bottles = 0
        drink_soon_bottles = 0
        hold_bottles = 0
        past_peak_bottles = 0
        estimated_value = 0.0

        for w in in_stock:
            qty = int(w["quantity"])
            wtype = (w.get("wine_type") or WINE_TYPE_RED).lower()
            if wtype in by_type:
                by_type[wtype] += qty
            else:
                by_type[WINE_TYPE_RED] += qty

            status = w.get("drink_status")
            if status in (DRINK_STATUS_READY, DRINK_STATUS_DRINK_SOON):
                ready_to_drink_bottles += qty
            if status == DRINK_STATUS_DRINK_SOON:
                drink_soon_bottles += qty
            elif status == DRINK_STATUS_HOLD:
                hold_bottles += qty
            elif status == DRINK_STATUS_PAST_PEAK:
                past_peak_bottles += qty

            unit_price = w.get("last_purchase_price")
            if unit_price is None:
                unit_price = w.get("vivino_price_estimate")
            if unit_price is not None:
                estimated_value += float(unit_price) * qty

        purchase_locations = sorted(
            {
                b["purchase_location"]
                for w in wines
                for b in w.get("batches", [])
                if b.get("purchase_location")
            }
        )
        storage_locations = sorted(
            {
                b["storage_location"]
                for w in wines
                for b in w.get("batches", [])
                if b.get("storage_location")
            }
        )

        return {
            "total_bottles": total_bottles,
            "unique_wines": unique_wines_in_stock,
            "archived_wines": len(archived),
            "ready_to_drink_bottles": ready_to_drink_bottles,
            "drink_soon_bottles": drink_soon_bottles,
            "hold_bottles": hold_bottles,
            "past_peak_bottles": past_peak_bottles,
            "estimated_value": round(estimated_value, 2),
            "by_type": by_type,
            "known_purchase_locations": purchase_locations,
            "known_storage_locations": storage_locations,
        }
