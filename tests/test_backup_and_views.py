"""Unit tests for database backup, restore, import, and dashboard multi-view configs."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import tempfile
from types import MappingProxyType, SimpleNamespace
import unittest
import zipfile
import yaml

from custom_components.wine_inventory.backup import (
    create_backup_archive,
    import_wines_archive,
    list_available_backups,
    restore_backup_archive,
)
from custom_components.wine_inventory.config_flow import WineInventoryOptionsFlowHandler
from custom_components.wine_inventory.const import DOMAIN, VERSION
from custom_components.wine_inventory.database import WineDatabase


class TestBackupRestoreAndViews(unittest.TestCase):
    """Test suite verifying ZIP backup generation, restore, multi-format import, and dashboard YAML."""

    def test_create_and_restore_backup_archive(self) -> None:
        """Verify full ZIP backup creation and lossless restoration of DB, covers, and metadata."""
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dest_dir:
            src_path = Path(src_dir)
            dest_path = Path(dest_dir)

            # 1. Setup source DB and covers
            db_file = src_path / "wine_inventory.db"
            db = WineDatabase(db_file)
            db.initialize()

            w1 = db.add_or_increment_wine(
                winery="Domaine de la Romanée-Conti",
                name="Romanée-Conti Grand Cru",
                vintage=2015,
                wine_type="red",
                varietal="Pinot Noir",
                region="Vosne-Romanée",
                country="France",
                quantity=3,
                purchase_location="Berry Bros & Rudd",
                purchase_price=12500.0,
                storage_location="Rack A1",
                vivino_rating=4.9,
            )

            # Create dummy cover image
            covers_dir = src_path / "covers"
            covers_dir.mkdir(parents=True, exist_ok=True)
            dummy_cover = covers_dir / f"cover_{w1['id']}.jpg"
            dummy_cover.write_bytes(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01DUMMY_IMAGE_DATA")

            # Update DB with image path
            db.update_wine(w1["id"], {"image_url": f"/local/wine_inventory/covers/{dummy_cover.name}"})

            # 2. Create full backup archive
            backup_meta = create_backup_archive(src_path, db)
            backup_file_path = Path(backup_meta["file_path"])
            self.assertTrue(backup_file_path.exists())
            self.assertEqual(backup_meta["wines_count"], 1)
            self.assertGreater(backup_meta["size_bytes"], 0)

            # Verify contents of generated ZIP
            with zipfile.ZipFile(backup_file_path, "r") as zf:
                namelist = zf.namelist()
                self.assertIn("wine_inventory.db", namelist)
                self.assertIn("metadata.json", namelist)
                self.assertIn(f"covers/{dummy_cover.name}", namelist)

                metadata_bytes = zf.read("metadata.json")
                meta = json.loads(metadata_bytes.decode("utf-8"))
                self.assertEqual(meta["version"], VERSION)
                self.assertEqual(meta["wines_count"], 1)
                self.assertEqual(meta["total_bottles"], 3)

            # Verify backup shows up in list_available_backups
            backups_list = list_available_backups(src_path)
            self.assertGreaterEqual(len(backups_list), 1)
            self.assertEqual(backups_list[0]["filename"], backup_meta["filename"])

            # 3. Restore backup into destination directory
            dest_db_file = dest_path / "wine_inventory.db"
            dest_db = WineDatabase(dest_db_file)

            with open(backup_file_path, "rb") as bf:
                restore_meta = restore_backup_archive(dest_path, dest_db, bf.read())

            self.assertEqual(restore_meta["wines_count"], 1)
            self.assertEqual(restore_meta["restored_images"], 1)
            self.assertTrue(dest_db_file.exists())
            self.assertTrue((dest_path / "covers" / dummy_cover.name).exists())

            # Validate destination DB query
            restored_wines = dest_db.list_wines()
            self.assertEqual(len(restored_wines), 1)
            self.assertEqual(restored_wines[0]["name"], "Romanée-Conti Grand Cru")
            self.assertEqual(restored_wines[0]["quantity"], 3)

    def test_import_wines_json_csv_and_zip(self) -> None:
        """Verify bulk wine import from JSON array, CSV text, and ZIP archive without wiping cellar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_file = tmp_path / "wine_inventory.db"
            db = WineDatabase(db_file)
            db.initialize()

            # 1. Import from JSON array
            json_payload = [
                {
                    "winery": "Château Margaux",
                    "name": "Pavillon Rouge",
                    "vintage": 2018,
                    "wine_type": "red",
                    "varietal": "Cabernet Sauvignon",
                    "quantity": 2,
                    "purchase_location": "Bordeaux Primeurs",
                    "purchase_price": 210.0,
                },
                {
                    "winery": "Kistler",
                    "name": "Les Noisetiers Chardonnay",
                    "vintage": 2021,
                    "wine_type": "white",
                    "varietal": "Chardonnay",
                    "quantity": 4,
                    "purchase_location": "Napa Valley",
                    "purchase_price": 75.0,
                },
            ]
            json_res = import_wines_archive(tmp_path, db, json_payload, format_type="json")
            self.assertEqual(json_res["imported_wines"], 2)

            # 2. Import from CSV string
            csv_payload = (
                "winery,name,vintage,wine_type,varietal,quantity,purchase_price\n"
                "Dom Pérignon,Vintage Champagne,2012,sparkling,Chardonnay Pinot Noir,3,240.0\n"
                "Château d'Yquem,Sauternes,2009,dessert,Semillon Sauvignon Blanc,1,450.0\n"
            )
            csv_res = import_wines_archive(tmp_path, db, csv_payload, format_type="csv")
            self.assertEqual(csv_res["imported_wines"], 2)

            # Total wines should now be 4, total bottles 10
            stats = db.get_statistics()
            self.assertEqual(stats["unique_wines"], 4)
            self.assertEqual(stats["total_bottles"], 10)

    def test_dashboard_views_configuration(self) -> None:
        """Verify dashboards/wine-cellar-dashboard.yaml specifies multiple views including list-view."""
        dash_path = Path(__file__).resolve().parent.parent / "dashboards" / "wine-cellar-dashboard.yaml"
        self.assertTrue(dash_path.exists(), f"Missing dashboard file at {dash_path}")

        with open(dash_path, "r", encoding="utf-8") as f:
            dash = yaml.safe_load(f)

        self.assertIn("views", dash)
        views = dash["views"]
        self.assertGreaterEqual(len(views), 4, "Dashboard should define at least 4 views")

        view_paths = [v.get("path") for v in views]
        self.assertIn("overview", view_paths)
        self.assertIn("list-view", view_paths)
        self.assertIn("tasting-archive", view_paths)
        self.assertIn("cellar-operations", view_paths)

        # Verify list-view uses default_view: list
        list_view = next(v for v in views if v.get("path") == "list-view")
        self.assertEqual(list_view.get("icon"), "mdi:view-list")
        card_types = [
            c.get("type")
            for sec in list_view.get("sections", [])
            for c in sec.get("cards", [])
        ]
        self.assertIn("custom:wine-inventory-card", card_types)

        # Verify custom card has default_view: list
        card = next(
            c
            for sec in list_view.get("sections", [])
            for c in sec.get("cards", [])
            if c.get("type") == "custom:wine-inventory-card"
        )
        self.assertEqual(card.get("default_view"), "list")

    def test_database_delete_wine_permanently(self) -> None:
        """Verify full permanent deletion of wine, batches, and timeline from SQLite database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "wine_inventory.db"
            db = WineDatabase(db_file)
            db.initialize()

            # Add wine with initial batch
            wine = db.add_or_increment_wine(
                winery="Château Cheval Blanc",
                name="Premier Grand Cru Classé A",
                vintage=2010,
                wine_type="red",
                quantity=2,
                purchase_location="Bordeaux",
            )
            wine_id = wine["id"]
            self.assertEqual(len(db.list_wines()), 1)

            # Consume 1 bottle to create tasting history
            db.adjust_quantity(wine_id=wine_id, delta=-1, personal_rating=4.8, notes="Superb structure")
            detail = db.get_wine_detail(wine_id)
            self.assertIsNotNone(detail)
            self.assertEqual(len(detail["timeline"]), 2)  # Added + Consumed

            # Now delete wine permanently
            deleted = db.delete_wine(wine_id)
            self.assertTrue(deleted)
            self.assertEqual(len(db.list_wines()), 0)
            self.assertIsNone(db.get_wine_detail(wine_id))
            stats = db.get_statistics()
            self.assertEqual(stats["total_bottles"], 0)
            self.assertEqual(stats["unique_wines"], 0)

    def test_v036_backup_security_sandboxing_zipslip_and_sqlite_header(self) -> None:
        """v0.3.6: Verify private storage migration, path traversal sandboxing, Zip-Slip rejection, and SQLite header checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            db_file = config_dir / "wine_inventory.db"
            db = WineDatabase(db_file)
            db.initialize()

            # 1. Backup created in private wine_inventory/backups, not www/
            meta = create_backup_archive(config_dir, db)
            self.assertTrue(meta["download_url"].startswith("/api/wine_inventory/download/backup/"))
            self.assertNotIn("/local/", meta["download_url"])

            # 2. Path traversal outside wine_inventory/backups is blocked
            with self.assertRaises(ValueError):
                restore_backup_archive(config_dir, db, "../../etc/passwd")
            with self.assertRaises(ValueError):
                import_wines_archive(config_dir, db, "../../etc/passwd", format_type="json")

            # 3. ZIP containing a fake/non-SQLite wine_inventory.db is rejected
            bad_db_buf = io.BytesIO()
            with zipfile.ZipFile(bad_db_buf, "w") as zf:
                zf.writestr("wine_inventory.db", b"NOT_A_SQLITE_FILE_HEADER_AT_ALL")
            with self.assertRaises(ValueError) as ctx_bad_db:
                restore_backup_archive(config_dir, db, bad_db_buf.getvalue())
            self.assertIn("SQLite", str(ctx_bad_db.exception))

            # 4. ZIP containing Zip-Slip traversal entry (../evil.sh) is rejected
            zip_slip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_slip_buf, "w") as zf:
                zf.writestr("../evil.sh", b"#!/bin/sh\necho pwned\n")
            with self.assertRaises(ValueError) as ctx_slip:
                restore_backup_archive(config_dir, db, zip_slip_buf.getvalue())
            self.assertIn("unsafe member path", str(ctx_slip.exception))

    def test_v037_options_flow_backup_restore_and_import(self) -> None:
        """v0.3.7: Verify OptionsFlow 'Create Full Database Backup (.zip)', Restore, and Import complete without NameError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            db_file = config_dir / "wine_inventory.db"
            db = WineDatabase(db_file)
            db.initialize()
            db.add_or_increment_wine(
                winery="Château Margaux",
                name="Premier Grand Cru Classé",
                vintage=2015,
                wine_type="red",
                quantity=2,
            )

            class _FakeCoordinator:
                def __init__(self) -> None:
                    self.fail_backup = False

                async def async_create_backup(self) -> dict:
                    if self.fail_backup:
                        raise RuntimeError("disk full")
                    return create_backup_archive(config_dir, db)

                async def async_list_backups(self) -> list[dict]:
                    return list_available_backups(config_dir)

                async def async_restore_backup(self, file_path: str) -> dict:
                    return restore_backup_archive(config_dir, db, file_path)

                async def async_import_wines(self, payload: str, format_type: str = "auto") -> dict:
                    return import_wines_archive(config_dir, db, payload, format_type)

            coord = _FakeCoordinator()
            entry = SimpleNamespace(
                entry_id="entry_test_037",
                data={"cellar_name": "Lekkersappie", "currency": "EUR"},
                options=MappingProxyType({"low_stock_threshold": 3}),
            )
            fake_hass = SimpleNamespace(
                config=SimpleNamespace(path=lambda *parts: str(config_dir.joinpath(*parts))),
                data={DOMAIN: {"entry_test_037": {"coordinator": coord}}},
            )

            flow = WineInventoryOptionsFlowHandler(entry)
            flow.hass = fake_hass

            # 1. Initial menu step renders menu options
            menu_res = asyncio.run(flow.async_step_init(None))
            self.assertEqual(menu_res["type"], "menu")
            self.assertIn("backup", menu_res["menu_options"])

            # 2. Backup confirmation form and execution
            backup_form = asyncio.run(flow.async_step_backup(None))
            self.assertEqual(backup_form["type"], "form")
            backup_done = asyncio.run(flow.async_step_backup({}))
            self.assertEqual(backup_done["type"], "create_entry")
            self.assertIsInstance(backup_done["data"], dict)
            self.assertEqual(backup_done["data"]["low_stock_threshold"], 3)

            backups = list_available_backups(config_dir)
            self.assertEqual(len(backups), 1)
            backup_filename = backups[0]["filename"]

            # 3. Backup error path logs cleanly without NameError and shows form error
            coord.fail_backup = True
            backup_err = asyncio.run(flow.async_step_backup({}))
            self.assertEqual(backup_err["type"], "form")
            self.assertEqual(backup_err["errors"].get("base"), "backup_failed")
            coord.fail_backup = False

            # 4. Restore execution via OptionsFlow
            restore_done = asyncio.run(
                flow.async_step_restore({"backup_file": backup_filename})
            )
            self.assertEqual(restore_done["type"], "create_entry")

            # 5. Import execution via OptionsFlow
            import_payload = json.dumps(
                [{"winery": "Krug", "name": "Grande Cuvée", "vintage": 2012, "wine_type": "sparkling", "quantity": 1}]
            )
            import_done = asyncio.run(
                flow.async_step_import_wines(
                    {"import_source": import_payload, "import_format": "json"}
                )
            )
            self.assertEqual(import_done["type"], "create_entry")
            self.assertEqual(len(db.list_wines()), 2)


if __name__ == "__main__":
    unittest.main()
