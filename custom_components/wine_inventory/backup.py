"""Home Assistant Core Backup integration and ZIP backup/restore/import for Wine Inventory."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
import zipfile

from .const import (
    BACKUPS_SUBDIR,
    COVERS_SUBDIR,
    DB_FILENAME,
    DOMAIN,
    STORAGE_DIR_NAME,
    VERSION,
)
from .database import WineDatabase

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def list_available_backups(config_dir: Path) -> list[dict[str, Any]]:
    """List available .zip backup archives in <config>/www/wine_inventory/backups/."""
    backups_dir = config_dir / BACKUPS_SUBDIR
    if not backups_dir.exists():
        return []

    backups = []
    for f in backups_dir.glob("*.zip"):
        if f.is_file():
            stat = f.stat()
            backups.append(
                {
                    "filename": f.name,
                    "file_path": str(f),
                    "download_url": f"/local/wine_inventory/backups/{f.name}",
                    "size_bytes": stat.st_size,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


def create_backup_archive(config_dir: Path, db: WineDatabase) -> dict[str, Any]:
    """Create a complete .zip backup containing SQLite db, metadata.json, and cover images."""
    db.checkpoint_wal()
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

    metadata = {
        "format_version": "1.0",
        "integration": "wine_inventory",
        "version": VERSION,
        "integration_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cellar_name": str(getattr(db, "cellar_name", "Lekkersappie")),
        "wines_count": len(full_wines),
        "total_bottles": sum(int(w.get("quantity") or 0) for w in full_wines),
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

    return {
        "file_path": str(target_zip),
        "filename": filename,
        "download_url": f"/local/wine_inventory/backups/{filename}",
        "size_bytes": target_zip.stat().st_size,
        "size_kb": round(target_zip.stat().st_size / 1024, 1),
        "wines_count": len(full_wines),
        "images_count": images_count,
        "created_at": metadata["created_at"],
    }


def restore_backup_archive(
    config_dir: Path,
    db: WineDatabase,
    zip_source: Path | bytes | str,
) -> dict[str, Any]:
    """Restore SQLite database and cover images from a .zip backup archive."""
    db_dir = config_dir / STORAGE_DIR_NAME
    db_dir.mkdir(parents=True, exist_ok=True)
    target_db_path = getattr(db, "db_path", None) or (db_dir / DB_FILENAME)
    covers_dir = config_dir / COVERS_SUBDIR
    covers_dir.mkdir(parents=True, exist_ok=True)
    alt_covers_dir = config_dir / "covers"
    alt_covers_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(zip_source, bytes):
        zip_obj = zipfile.ZipFile(io.BytesIO(zip_source))
    else:
        zip_obj = zipfile.ZipFile(Path(zip_source))

    restored_db = False
    restored_images = 0
    wines_count = 0

    with zip_obj:
        namelist = zip_obj.namelist()

        # Restore cover image files
        for name in namelist:
            if name.startswith("covers/") and len(name) > len("covers/") and not name.endswith("/"):
                data = zip_obj.read(name)
                dest = covers_dir / Path(name).name
                dest.write_bytes(data)
                alt_dest = alt_covers_dir / Path(name).name
                alt_dest.write_bytes(data)
                restored_images += 1

        # Check for DB_FILENAME
        db_arcname = None
        for name in namelist:
            if Path(name).name == DB_FILENAME:
                db_arcname = name
                break

        if db_arcname:
            # Delete stale -wal and -shm files if present
            wal_file = target_db_path.with_name(f"{DB_FILENAME}-wal")
            shm_file = target_db_path.with_name(f"{DB_FILENAME}-shm")
            if wal_file.exists():
                wal_file.unlink()
            if shm_file.exists():
                shm_file.unlink()

            target_db_path.write_bytes(zip_obj.read(db_arcname))
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


def _import_wines_from_csv(db: WineDatabase, csv_text: str) -> int:
    """Parse CSV text with wine headers and import into SQLite."""
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
        payload.endswith(".zip") or payload.endswith(".json") or payload.endswith(".csv")
    ):
        path = Path(payload)
        if path.exists():
            if path.suffix.lower() == ".zip":
                return restore_backup_archive(config_dir, db, path)
            if path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                return import_wines_archive(config_dir, db, data, "json")
            if path.suffix.lower() == ".csv":
                text = path.read_text(encoding="utf-8")
                count = _import_wines_from_csv(db, text)
                return {"success": True, "imported_wines": count}

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
            return {"success": True, "imported_wines": count}
    else:
        raise ValueError("Unsupported import payload format.")

    count = _import_wines_list(db, wines_list)
    return {
        "success": True,
        "imported_wines": count,
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
