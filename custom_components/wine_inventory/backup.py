"""Home Assistant Core Backup integration and ZIP backup/restore/import for Wine Inventory."""

from __future__ import annotations

from contextlib import closing
import csv
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import TYPE_CHECKING, Any
import zipfile

from .const import (
    BACKUPS_SUBDIR,
    COVERS_SUBDIR,
    DB_FILENAME,
    DOMAIN,
    EXPORTS_SUBDIR,
    LEGACY_BACKUPS_SUBDIR,
    LEGACY_EXPORTS_SUBDIR,
    MAX_BACKUP_ARCHIVE_BYTES,
    MAX_IMAGE_UPLOAD_BYTES,
    STORAGE_DIR_NAME,
    VERSION,
)
from .database import WineDatabase

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SQLITE_MAGIC_HEADER = b"SQLite format 3\x00"
ALLOWED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def is_valid_image_bytes(data: bytes) -> bool:
    """Return True if raw bytes begin with a recognized JPEG, PNG, or WebP magic signature."""
    if not data or len(data) < 12 or len(data) > MAX_IMAGE_UPLOAD_BYTES:
        return False
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return True
    return False


def _validate_sqlite_bytes(db_bytes: bytes, work_dir: Path) -> None:
    """Verify that db_bytes is a valid, uncorrupted SQLite 3 database before overwriting."""
    if not db_bytes or len(db_bytes) < 100 or not db_bytes.startswith(SQLITE_MAGIC_HEADER):
        raise ValueError(
            "Security error: backup database file does not have a valid SQLite 3 header."
        )
    if len(db_bytes) > MAX_BACKUP_ARCHIVE_BYTES:
        raise ValueError(
            "Security error: backup database exceeds maximum allowed size (50 MB)."
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=work_dir, suffix=".sqlite_verify", delete=True) as tmp:
        tmp.write(db_bytes)
        tmp.flush()
        with closing(sqlite3.connect(tmp.name)) as conn:
            verdict = conn.execute("PRAGMA quick_check;").fetchone()
            if not verdict or str(verdict[0]).lower() != "ok":
                raise ValueError(
                    "Security error: SQLite database failed integrity check."
                )


def _migrate_legacy_public_files(config_dir: Path) -> None:
    """Move any legacy backups/exports out of <config>/www/ into private storage."""
    migrations = (
        (config_dir / LEGACY_BACKUPS_SUBDIR, config_dir / BACKUPS_SUBDIR, ("*.zip",)),
        (
            config_dir / LEGACY_EXPORTS_SUBDIR,
            config_dir / EXPORTS_SUBDIR,
            ("*.csv", "*.json"),
        ),
    )
    for legacy_dir, private_dir, patterns in migrations:
        try:
            if not legacy_dir.exists() or not legacy_dir.is_dir():
                continue
            for pat in patterns:
                for item in legacy_dir.glob(pat):
                    if not item.is_file() or item.is_symlink():
                        continue
                    private_dir.mkdir(parents=True, exist_ok=True)
                    dest = private_dir / item.name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))
                    else:
                        item.unlink()
        except OSError as err:
            _LOGGER.debug("Could not migrate legacy files from %s: %s", legacy_dir, err)


def resolve_safe_storage_path(
    config_dir: Path,
    user_path: str | Path,
    *,
    allowed_subdirs: tuple[str, ...] = (BACKUPS_SUBDIR, EXPORTS_SUBDIR, STORAGE_DIR_NAME),
) -> Path:
    """Resolve a user-supplied filename or path strictly within private wine_inventory dirs."""
    raw = str(user_path or "").strip()
    if not raw or "\x00" in raw:
        raise ValueError("Invalid or empty file path.")

    candidate_input = Path(raw)
    if ".." in candidate_input.parts:
        raise ValueError(
            "Security error: path traversal ('..') is not allowed."
        )

    allowed_roots = [(config_dir / sub).resolve() for sub in allowed_subdirs]

    # Bare filename (e.g. "lekkersappie_backup_20261026_120000.zip")
    if candidate_input.name == raw:
        for root in allowed_roots:
            cand = root / raw
            if cand.exists() and cand.is_file() and not cand.is_symlink():
                resolved = cand.resolve()
                if any(resolved.is_relative_to(r) for r in allowed_roots):
                    return resolved
        # Return path inside primary allowed root so caller can report file-not-found or check exists()
        return allowed_roots[0] / raw

    # Explicit relative or absolute path: must resolve inside one of allowed_roots
    if not candidate_input.is_absolute():
        candidate_input = config_dir / candidate_input
    if candidate_input.is_symlink():
        raise ValueError("Security error: symbolic links are not allowed.")
    resolved = candidate_input.resolve()
    if not any(resolved.is_relative_to(r) for r in allowed_roots):
        raise ValueError(
            "Security error: path is outside the allowed wine_inventory storage directory."
        )
    return resolved


def list_available_backups(config_dir: Path) -> list[dict[str, Any]]:
    """List available .zip backup archives in <config>/wine_inventory/backups/."""
    _migrate_legacy_public_files(config_dir)
    backups_dir = config_dir / BACKUPS_SUBDIR
    if not backups_dir.exists():
        return []

    backups = []
    for f in backups_dir.glob("*.zip"):
        if f.is_file() and not f.is_symlink():
            stat = f.stat()
            backups.append(
                {
                    "filename": f.name,
                    "file_path": str(f),
                    "download_url": f"/api/wine_inventory/download/backup/{f.name}",
                    "size_bytes": stat.st_size,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


def create_backup_archive(config_dir: Path, db: WineDatabase) -> dict[str, Any]:
    """Create a complete .zip backup containing SQLite db, metadata.json, and cover images."""
    _migrate_legacy_public_files(config_dir)
    try:
        db.checkpoint_wal()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("SQLite WAL checkpoint warning before backup: %s", err)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"lekkersappie_backup_{timestamp_str}.zip"

    backups_dir = config_dir / BACKUPS_SUBDIR
    backups_dir.mkdir(parents=True, exist_ok=True)
    target_zip = backups_dir / filename

    db_path = getattr(db, "db_path", None) or (config_dir / STORAGE_DIR_NAME / DB_FILENAME)
    covers_dir = config_dir / COVERS_SUBDIR
    alt_covers_dir = config_dir / "covers"

    # Build comprehensive metadata.json
    wines = db.list_wines(include_out_of_stock=True)
    full_wines = []
    for w in wines:
        detail = db.get_wine_detail(int(w["id"]))
        if detail:
            full_wines.append(detail)
        else:
            full_wines.append(w)

    def _safe_qty(val: Any) -> int:
        try:
            return int(float(val or 0))
        except (ValueError, TypeError):
            return 0

    metadata = {
        "format_version": "1.0",
        "integration": "wine_inventory",
        "version": VERSION,
        "integration_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cellar_name": str(getattr(db, "cellar_name", "Lekkersappie")),
        "wines_count": len(full_wines),
        "total_bottles": sum(_safe_qty(w.get("quantity")) for w in full_wines),
        "statistics": db.get_statistics(),
        "wines": full_wines,
    }

    images_count = 0
    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        if Path(db_path).exists():
            zf.write(db_path, arcname=DB_FILENAME)

        zf.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False))

        active_covers = covers_dir if covers_dir.exists() else alt_covers_dir
        if active_covers.exists():
            for img_file in active_covers.glob("*"):
                if img_file.is_file() and not img_file.name.startswith("."):
                    zf.write(img_file, arcname=f"covers/{img_file.name}")
                    images_count += 1

    size_bytes = target_zip.stat().st_size
    return {
        "file_path": str(target_zip),
        "filename": filename,
        "backup_filename": filename,
        "download_url": f"/api/wine_inventory/download/backup/{filename}",
        "size_bytes": size_bytes,
        "size_kb": round(size_bytes / 1024, 1),
        "wines_count": len(full_wines),
        "wine_count": len(full_wines),
        "images_count": images_count,
        "created_at": metadata["created_at"],
    }


def restore_backup_archive(
    config_dir: Path,
    db: WineDatabase,
    zip_source: Path | bytes | str,
) -> dict[str, Any]:
    """Restore SQLite database and cover images from a validated .zip backup archive."""
    _migrate_legacy_public_files(config_dir)
    db_dir = config_dir / STORAGE_DIR_NAME
    db_dir.mkdir(parents=True, exist_ok=True)
    target_db_path = getattr(db, "db_path", None) or (db_dir / DB_FILENAME)
    covers_dir = config_dir / COVERS_SUBDIR
    covers_dir.mkdir(parents=True, exist_ok=True)
    alt_covers_dir = config_dir / "covers"
    alt_covers_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(zip_source, bytes):
        if len(zip_source) > MAX_BACKUP_ARCHIVE_BYTES:
            raise ValueError(
                "Security error: backup archive exceeds maximum allowed size (50 MB)."
            )
        zip_obj = zipfile.ZipFile(io.BytesIO(zip_source))
    else:
        safe_path = resolve_safe_storage_path(config_dir, zip_source)
        if not safe_path.exists() or not safe_path.is_file():
            raise FileNotFoundError(f"Backup archive not found: {safe_path.name}")
        if safe_path.stat().st_size > MAX_BACKUP_ARCHIVE_BYTES:
            raise ValueError(
                "Security error: backup archive exceeds maximum allowed size (50 MB)."
            )
        zip_obj = zipfile.ZipFile(safe_path)

    restored_db = False
    restored_images = 0
    wines_count = 0

    with zip_obj:
        # Zip-Slip and Zip-Bomb pre-flight inspection
        total_uncompressed = 0
        for info in zip_obj.infolist():
            member_path = Path(info.filename)
            if (
                ".." in member_path.parts
                or info.filename.startswith("/")
                or info.filename.startswith("\\")
            ):
                raise ValueError(
                    f"Security error: unsafe member path in ZIP archive: {info.filename}"
                )
            if info.file_size < 0 or info.file_size > MAX_BACKUP_ARCHIVE_BYTES:
                raise ValueError(
                    "Security error: archive member exceeds maximum allowed uncompressed size."
                )
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_BACKUP_ARCHIVE_BYTES:
                raise ValueError(
                    "Security error: total uncompressed archive size exceeds 50 MB limit."
                )

        namelist = zip_obj.namelist()

        # Restore cover image files (validated by extension and image magic header)
        for name in namelist:
            if name.startswith("covers/") and len(name) > len("covers/") and not name.endswith("/"):
                clean_img_name = Path(name).name
                ext = Path(clean_img_name).suffix.lower()
                if clean_img_name != name[len("covers/"):] or ext not in ALLOWED_COVER_EXTENSIONS:
                    raise ValueError(
                        f"Security error: disallowed cover image filename in archive: {name}"
                    )
                data = zip_obj.read(name)
                if not is_valid_image_bytes(data):
                    raise ValueError(
                        f"Security error: cover file '{clean_img_name}' failed image magic header verification."
                    )
                dest = covers_dir / clean_img_name
                dest.write_bytes(data)
                alt_dest = alt_covers_dir / clean_img_name
                alt_dest.write_bytes(data)
                restored_images += 1

        # Check for DB_FILENAME
        db_arcname = None
        for name in namelist:
            if Path(name).name == DB_FILENAME:
                db_arcname = name
                break

        if db_arcname:
            db_bytes = zip_obj.read(db_arcname)
            _validate_sqlite_bytes(db_bytes, db_dir)

            # Delete stale -wal and -shm files if present
            wal_file = target_db_path.with_name(f"{DB_FILENAME}-wal")
            shm_file = target_db_path.with_name(f"{DB_FILENAME}-shm")
            if wal_file.exists():
                wal_file.unlink()
            if shm_file.exists():
                shm_file.unlink()

            target_db_path.write_bytes(db_bytes)
            db.initialize()
            restored_db = True
            wines_count = len(db.list_wines(include_out_of_stock=True))
        elif "metadata.json" in namelist:
            meta = json.loads(zip_obj.read("metadata.json").decode("utf-8"))
            wines_data = meta.get("wines") or []
            wines_count = _import_wines_list(db, wines_data)
            restored_db = True

    return {
        "success": True,
        "restored_db": restored_db,
        "restored_images": restored_images,
        "wines_count": wines_count,
    }


def _import_wines_list(db: WineDatabase, wines: list[dict[str, Any]]) -> int:
    """Import a list of structured wine records and their batches into SQLite."""
    imported = 0
    for w in wines:
        if not isinstance(w, dict):
            continue
        winery = str(w.get("winery") or "Unknown Winery").strip()
        name = str(w.get("name") or "Unnamed Wine").strip()
        vintage = w.get("vintage")
        if vintage is not None:
            try:
                vintage = int(vintage)
            except (ValueError, TypeError):
                vintage = None

        wine_type = str(w.get("wine_type") or "red").strip()
        varietal = str(w.get("varietal") or "").strip()
        region = str(w.get("region") or "").strip()
        country = str(w.get("country") or "").strip()
        alcohol_pct = w.get("alcohol_pct")
        bottle_size_ml = int(w.get("bottle_size_ml") or 750)
        drink_from_year = w.get("drink_from_year")
        drink_until_year = w.get("drink_until_year")
        drink_window_note = str(w.get("drink_window_note") or "").strip()
        general_notes = str(w.get("general_notes") or "").strip()
        personal_rating = w.get("personal_rating")
        image_url = str(w.get("image_url") or "").strip()

        batches = w.get("batches") or []
        if batches:
            for b in batches:
                qty = int(b.get("quantity_remaining") or b.get("quantity_added") or 1)
                db.add_or_increment_wine(
                    winery=winery,
                    name=name,
                    vintage=vintage,
                    wine_type=wine_type,
                    varietal=varietal,
                    region=region,
                    country=country,
                    alcohol_pct=alcohol_pct,
                    bottle_size_ml=bottle_size_ml,
                    drink_from_year=drink_from_year,
                    drink_until_year=drink_until_year,
                    drink_window_note=drink_window_note,
                    general_notes=general_notes,
                    personal_rating=personal_rating,
                    image_url=image_url,
                    quantity=qty,
                    added_at=b.get("added_at"),
                    purchase_location=str(b.get("purchase_location") or ""),
                    purchase_price=b.get("purchase_price"),
                    storage_location=str(b.get("storage_location") or ""),
                    notes=str(b.get("notes") or ""),
                )
        else:
            qty = int(w.get("quantity") or 0)
            db.add_or_increment_wine(
                winery=winery,
                name=name,
                vintage=vintage,
                wine_type=wine_type,
                varietal=varietal,
                region=region,
                country=country,
                alcohol_pct=alcohol_pct,
                bottle_size_ml=bottle_size_ml,
                drink_from_year=drink_from_year,
                drink_until_year=drink_until_year,
                drink_window_note=drink_window_note,
                general_notes=general_notes,
                personal_rating=personal_rating,
                image_url=image_url,
                quantity=max(1, qty),
                purchase_location=str(w.get("last_purchase_location") or ""),
                purchase_price=w.get("last_purchase_price"),
                storage_location=str(w.get("last_storage_location") or ""),
            )
            # If original had 0 quantity, adjust down
            if qty == 0:
                created = db.find_matching_wine(winery, name, vintage)
                if created:
                    db.adjust_wine_quantity(created["id"], delta=-1)
        imported += 1
    return imported


def infer_wine_type_from_text(text: str) -> str:
    """Infer wine type ('red', 'white', 'rose', 'sparkling', 'dessert', 'fortified') from text."""
    lower = text.lower()
    if any(
        k in lower
        for k in (
            "champagne",
            "prosecco",
            "cava",
            "brut",
            "sparkling",
            "cremant",
            "crémant",
            "spumante",
            "sekt",
            "franciacorta",
        )
    ):
        return "sparkling"
    if any(k in lower for k in ("rosé", "rose", "rosato")):
        return "rose"
    if any(
        k in lower
        for k in (
            "chardonnay",
            "sauvignon blanc",
            "riesling",
            "pinot grigio",
            "pinot gris",
            "chenin",
            "viognier",
            "chablis",
            "sancerre",
            "white",
            "albarino",
            "albariño",
            "verdejo",
            "soave",
            "gavi",
            "muscadet",
            "vermentino",
            "grüner veltliner",
        )
    ):
        return "white"
    if any(k in lower for k in ("port", "sherry", "madeira", "fortified", "tawny", "marsala")):
        return "fortified"
    if any(k in lower for k in ("sauternes", "tokaji", "ice wine", "eiswein", "dessert", "late harvest")):
        return "dessert"
    return "red"


def infer_varietal_from_text(text: str) -> str:
    """Infer grape varietal from wine name, cuvée, and region."""
    lower = text.lower()
    varietals = [
        ("cabernet sauvignon", "Cabernet Sauvignon"),
        ("pinot noir", "Pinot Noir"),
        ("chardonnay", "Chardonnay"),
        ("sauvignon blanc", "Sauvignon Blanc"),
        ("syrah", "Syrah"),
        ("shiraz", "Shiraz"),
        ("merlot", "Merlot"),
        ("sangiovese", "Sangiovese"),
        ("nebbiolo", "Nebbiolo"),
        ("tempranillo", "Tempranillo"),
        ("garnacha", "Garnacha"),
        ("grenache", "Grenache"),
        ("malbec", "Malbec"),
        ("zinfandel", "Zinfandel"),
        ("riesling", "Riesling"),
        ("chenin blanc", "Chenin Blanc"),
        ("viognier", "Viognier"),
        ("pinot grigio", "Pinot Grigio"),
        ("pinot gris", "Pinot Gris"),
        ("cabernet franc", "Cabernet Franc"),
        ("primitivo", "Primitivo"),
        ("carmenere", "Carménère"),
        ("corvina", "Corvina"),
        ("gamay", "Gamay"),
    ]
    for key, name in varietals:
        if key in lower:
            return name
    if any(k in lower for k in ("bolgheri", "sassicaia", "bordeaux", "margaux", "pauillac", "saint-julien")):
        return "Bordeaux Blend / Cabernet Sauvignon"
    if any(k in lower for k in ("tignanello", "chianti", "brunello")):
        return "Sangiovese"
    if any(k in lower for k in ("champagne", "champenois")):
        return "Chardonnay / Pinot Noir"
    return ""


def import_vivino_history_csv(db: WineDatabase, csv_text: str) -> dict[str, Any]:
    """Parse Vivino history CSV export and populate wine cellar & tasted database.

    Recognizes standard Vivino exports and custom column variations:
      - Wine Name, Winery / Producer, Vintage, Region, Country
      - My Rating, Review Text / Notes, Date Logged, Price Paid, Quantity In Cellar
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    imported_count = 0
    tasted_count = 0
    cellar_count = 0

    for row in reader:
        # Resolve fields flexibly with case-insensitive / trimmed lookup
        norm_row = {str(k).strip().lower(): v for k, v in row.items() if k is not None}

        def _val(*keys: str) -> str:
            for k in keys:
                k_lower = k.lower()
                if k_lower in norm_row and norm_row[k_lower] is not None:
                    res = str(norm_row[k_lower]).strip()
                    if res:
                        return res
            return ""

        name = _val("wine name", "wine", "name", "cuvée", "cuvee")
        winery = _val("winery / producer", "winery", "producer", "winery name")
        if not name and not winery:
            continue
        if not winery:
            winery = "Unknown Winery"
        if not name:
            name = "Unnamed Wine"

        raw_vintage = _val("vintage", "year")
        vintage: int | None = None
        if raw_vintage:
            try:
                vintage = int(float(raw_vintage))
            except (ValueError, TypeError):
                vintage = None

        region = _val("region")
        country = _val("country")

        raw_rating = _val("my rating", "personal rating", "user rating", "rating", "your rating")
        personal_rating: float | None = None
        if raw_rating:
            try:
                personal_rating = round(float(raw_rating), 1)
            except (ValueError, TypeError):
                personal_rating = None

        notes = _val("review text / notes", "review text", "review", "notes", "personal note", "note")
        added_at = _val("date logged", "scan date", "activity date", "date added", "added at", "date") or None

        raw_price = _val("price paid", "price", "purchase price", "bottle price", "wine price")
        purchase_price: float | None = None
        if raw_price:
            try:
                purchase_price = float(raw_price)
            except (ValueError, TypeError):
                purchase_price = None

        raw_qty = _val("quantity in cellar", "quantity", "bottle count", "bottles in cellar", "stock")
        qty = 0
        if raw_qty:
            try:
                qty = max(0, int(float(raw_qty)))
            except (ValueError, TypeError):
                qty = 0

        # Infer wine type and grape varietal from available text
        text_corpus = f"{name} {winery} {region} {country}"
        wine_type = _val("wine type", "type", "style") or infer_wine_type_from_text(text_corpus)
        varietal = _val("varietal", "grape", "grape variety") or infer_varietal_from_text(text_corpus)

        is_as_tasted = qty <= 0
        db.add_or_increment_wine(
            winery=winery,
            name=name,
            vintage=vintage,
            wine_type=wine_type,
            varietal=varietal,
            region=region,
            country=country,
            drink_window_note="",
            general_notes=notes,
            batch_notes=notes,
            personal_rating=personal_rating,
            quantity=qty if qty > 0 else 0,
            added_at=added_at,
            purchase_price=purchase_price,
            as_tasted=is_as_tasted,
        )
        imported_count += 1
        if is_as_tasted:
            tasted_count += 1
        else:
            cellar_count += 1

    return {
        "success": True,
        "imported_count": imported_count,
        "cellar_count": cellar_count,
        "tasted_count": tasted_count,
    }


def stage_backup_for_download(config_dir: Path, filename: str) -> str:
    """Stage a backup .zip file into <config>/www/wine_inventory/backups/ for direct HTTP download.

    Returns the public Home Assistant URL path '/local/wine_inventory/backups/<filename>'.
    """
    safe_path = resolve_safe_storage_path(config_dir, filename)
    if not safe_path.exists() or not safe_path.is_file():
        raise FileNotFoundError(f"Backup archive {filename} not found.")

    www_backups_dir = config_dir / "www" / "wine_inventory" / "backups"
    www_backups_dir.mkdir(parents=True, exist_ok=True)
    target_file = www_backups_dir / safe_path.name
    shutil.copy2(safe_path, target_file)
    return f"/local/wine_inventory/backups/{safe_path.name}"


def _import_wines_from_csv(db: WineDatabase, csv_text: str) -> int:
    """Parse CSV text with wine headers and import into SQLite."""
    # Check if this CSV contains Vivino export columns
    first_line = csv_text.splitlines()[0].lower() if csv_text.strip() else ""
    if any(k in first_line for k in ("wine name", "winery / producer", "my rating", "quantity in cellar", "date logged", "review text")):
        res = import_vivino_history_csv(db, csv_text)
        return int(res.get("imported_count") or 0)

    reader = csv.DictReader(io.StringIO(csv_text))
    wines_list = []
    for row in reader:
        wines_list.append(row)
    return _import_wines_list(db, wines_list)


def import_wines_archive(
    config_dir: Path,
    db: WineDatabase,
    payload: list[dict[str, Any]] | dict[str, Any] | bytes | str,
    format_type: str = "auto",
) -> dict[str, Any]:
    """Import wines from JSON list, CSV text, or ZIP backup archive."""
    if isinstance(payload, bytes) and payload.startswith(b"PK"):
        return restore_backup_archive(config_dir, db, payload)

    if isinstance(payload, str) and (
        payload.endswith(".zip")
        or payload.endswith(".json")
        or payload.endswith(".csv")
        or ("\n" not in payload.strip() and not payload.strip().startswith(("[", "{")))
    ):
        safe_path = resolve_safe_storage_path(config_dir, payload)
        if not safe_path.exists() or not safe_path.is_file():
            raise FileNotFoundError(f"Import file not found: {safe_path.name}")
        if safe_path.stat().st_size > MAX_BACKUP_ARCHIVE_BYTES:
            raise ValueError(
                "Security error: import file exceeds maximum allowed size (50 MB)."
            )
        if safe_path.suffix.lower() == ".zip":
            return restore_backup_archive(config_dir, db, safe_path)
        if safe_path.suffix.lower() == ".json":
            data = json.loads(safe_path.read_text(encoding="utf-8"))
            return import_wines_archive(config_dir, db, data, "json")
        if safe_path.suffix.lower() == ".csv":
            text = safe_path.read_text(encoding="utf-8")
            count = _import_wines_from_csv(db, text)
            return {"success": True, "imported_wines": count, "imported_count": count}

    if isinstance(payload, dict):
        wines_list = payload.get("wines") or [payload]
    elif isinstance(payload, list):
        wines_list = payload
    elif isinstance(payload, str):
        trimmed = payload.strip()
        if trimmed.startswith("[") or trimmed.startswith("{"):
            data = json.loads(trimmed)
            wines_list = data.get("wines") if isinstance(data, dict) else data
        else:
            count = _import_wines_from_csv(db, trimmed)
            return {"success": True, "imported_wines": count, "imported_count": count}
    else:
        raise ValueError("Unsupported import payload format.")

    count = _import_wines_list(db, wines_list)
    return {
        "success": True,
        "imported_wines": count,
        "imported_count": count,
    }


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Flush SQLite WAL checkpoint before Home Assistant creates a backup archive."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if isinstance(entry_data, dict) and "coordinator" in entry_data:
            coordinator = entry_data["coordinator"]
            await coordinator.async_checkpoint_database()
    _LOGGER.debug("Completed SQLite WAL checkpoint for Wine Inventory pre-backup")


async def async_post_backup(hass: HomeAssistant) -> None:
    """Perform any post-backup actions after Home Assistant snapshot completes."""
    _LOGGER.debug("Completed Wine Inventory post-backup hook")
