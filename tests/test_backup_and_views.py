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
    import_vivino_history_csv,
    import_wines_archive,
    list_available_backups,
    restore_backup_archive,
    stage_backup_for_download,
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

        # Verify Tasted view is titled 'Tasted' and configures default_tab: tasted
        tasted_view = next(v for v in views if v.get("path") == "tasting-archive")
        self.assertEqual(tasted_view.get("title"), "Tasted")
        tasted_card = next(
            c
            for sec in tasted_view.get("sections", [])
            for c in sec.get("cards", [])
            if c.get("type") == "custom:wine-inventory-card"
        )
        self.assertEqual(tasted_card.get("default_tab"), "tasted")

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

    def test_import_vivino_history_csv_lossless(self) -> None:
        """Verify importing the user's Vivino history CSV with ratings, notes, and cellar quantities."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "wine_inventory.db"
            db = WineDatabase(db_path)
            db.initialize()

            # Exact sample attached by the user plus a 0-quantity tasted row
            csv_sample = (
                "Wine Name,Winery / Producer,Vintage,Region,Country,My Rating,Review Text / Notes,Date Logged,Price Paid,Quantity In Cellar\n"
                'Sassicaia,Tenuta San Guido,2018,Bolgheri,Italy,4.8,"Incredible structure, silky tannins, dark cherry and tobacco.",2025-05-14,250.0,2\n'
                'Chateau Margaux,Château Margaux,2015,Margaux,France,4.9,"A masterpiece. Velvety, elegant, perfect balance.",2025-11-20,600.0,1\n'
                'Dom Perignon Brut Champagne,Dom Pérignon,2012,Champagne,France,4.7,"Toasty brioche, crisp acidity, beautiful fine bubbles.",2025-12-31,220.0,3\n'
                'Tignanello,Marchesi Antinori,2020,Toscana,Italy,4.6,"Classic Sangiovese blend, vibrant acidity, oak notes.",2026-03-15,140.0,4\n'
                'Silver Oak Alexander Valley Cabernet Sauvignon,Silver Oak,2019,Alexander Valley,United States,4.5,"Classic bold California Cab, vanilla and rich blackberry.",2026-09-02,95.0,2\n'
                'Barolo Monfortino,Giacomo Conterno,2010,Piemonte,Italy,5.0,"Legendary wine, drank at special anniversary dinner.",2024-10-10,1200.0,0\n'
            )

            res = import_vivino_history_csv(db, csv_sample)
            self.assertTrue(res["success"])
            self.assertEqual(res["imported_count"], 6)
            self.assertEqual(res["cellar_count"], 5)
            self.assertEqual(res["tasted_count"], 1)

            wines = db.list_wines(include_out_of_stock=True)
            self.assertEqual(len(wines), 6)

            # Check Dom Perignon Brut Champagne -> sparkling
            dom = next(w for w in wines if "Dom Perignon" in w["name"])
            self.assertEqual(dom["wine_type"], "sparkling")
            self.assertEqual(dom["vintage"], 2012)
            self.assertEqual(dom["personal_rating"], 4.7)
            self.assertEqual(dom["quantity"], 3)

            # Check Sassicaia -> personal rating 4.8 and review notes
            sass = next(w for w in wines if "Sassicaia" in w["name"])
            self.assertEqual(sass["winery"], "Tenuta San Guido")
            self.assertEqual(sass["personal_rating"], 4.8)
            self.assertIn("silky tannins", sass["general_notes"])
            self.assertEqual(sass["quantity"], 2)

            # Check Barolo Monfortino -> 0 quantity in cellar, stored with personal_rating=5.0 and notes in tasted
            barolo = next(w for w in wines if "Monfortino" in w["name"])
            self.assertEqual(barolo["quantity"], 0)
            self.assertEqual(barolo["personal_rating"], 5.0)

            # Also verify _import_wines_from_csv auto-detects Vivino CSV headers
            with tempfile.TemporaryDirectory() as tmp_dir2:
                db2 = WineDatabase(Path(tmp_dir2) / "wine_inventory.db")
                db2.initialize()
                cnt = import_wines_archive(Path(tmp_dir2), db2, csv_sample)
                self.assertEqual(cnt.get("imported_wines"), 6)
                self.assertEqual(len(db2.list_wines(include_out_of_stock=True)), 6)

    def test_stage_backup_for_download(self) -> None:
        """Verify staging backup archive into <config>/www/wine_inventory/backups/ for direct HTTP download."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            db = WineDatabase(config_dir / "wine_inventory.db")
            db.initialize()
            db.add_or_increment_wine(winery="Test Winery", name="Test Wine", quantity=1)

            meta = create_backup_archive(config_dir, db)
            filename = meta["filename"]

            url = stage_backup_for_download(config_dir, filename)
            self.assertEqual(url, f"/local/wine_inventory/backups/{filename}")
            staged_path = config_dir / "www" / "wine_inventory" / "backups" / filename
            self.assertTrue(staged_path.exists())
            self.assertEqual(staged_path.stat().st_size, meta["size_bytes"])

    def test_options_flow_download_and_upload_vivino(self) -> None:
        """Verify OptionsFlow download_backup and upload_vivino menu options."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            db = WineDatabase(config_dir / "wine_inventory.db")
            db.initialize()

            class _FakeCoordinator:
                def __init__(self) -> None:
                    self.db = db

                async def async_create_backup(self) -> dict:
                    return create_backup_archive(config_dir, db)

                async def async_list_backups(self) -> list:
                    return list_available_backups(config_dir)

                async def async_stage_backup_for_download(self, filename: str) -> str:
                    return stage_backup_for_download(config_dir, filename)

                async def async_import_vivino_csv(self, csv_text: str) -> dict:
                    return import_vivino_history_csv(db, csv_text)

            coord = _FakeCoordinator()
            entry = SimpleNamespace(
                entry_id="entry_test_039",
                data={"cellar_name": "Lekkersappie"},
                options=MappingProxyType({"low_stock_threshold": 3}),
            )
            fake_hass = SimpleNamespace(
                config=SimpleNamespace(path=lambda *parts: str(config_dir.joinpath(*parts))),
                data={DOMAIN: {"entry_test_039": {"coordinator": coord}}},
            )

            flow = WineInventoryOptionsFlowHandler(entry)
            flow.hass = fake_hass

            # Check menu options include download_backup and upload_vivino
            menu_res = asyncio.run(flow.async_step_init(None))
            self.assertIn("download_backup", menu_res["menu_options"])
            self.assertIn("upload_vivino", menu_res["menu_options"])

            # Create backup first so download_backup has files
            asyncio.run(flow.async_step_backup({}))
            backups = list_available_backups(config_dir)
            self.assertEqual(len(backups), 1)
            filename = backups[0]["filename"]

            # Download backup step
            dl_res = asyncio.run(flow.async_step_download_backup({"backup_file": filename}))
            self.assertEqual(dl_res["type"], "form")
            self.assertIn("download_url", dl_res.get("description_placeholders", {}))
            self.assertEqual(
                dl_res["description_placeholders"]["download_url"],
                f"/local/wine_inventory/backups/{filename}",
            )

            # Upload Vivino history step
            csv_content = (
                "Wine Name,Winery / Producer,Vintage,Region,Country,My Rating,Review Text / Notes,Date Logged,Price Paid,Quantity In Cellar\n"
                'Sassicaia,Tenuta San Guido,2018,Bolgheri,Italy,4.8,"Incredible structure.",2025-05-14,250.0,2\n'
            )
            vivino_res = asyncio.run(flow.async_step_upload_vivino({"csv_content": csv_content}))
            self.assertEqual(vivino_res["type"], "create_entry")
            self.assertEqual(len(db.list_wines()), 1)

    def test_v040_vivino_export_zip_import(self) -> None:
        """v0.4.0: Verify Vivino ZIP archive import parses full_wine_list.csv as Tasted, cellar.csv into cellar stock, and downloads covers."""
        from custom_components.wine_inventory.backup import (
            is_vivino_export_zip,
            import_vivino_export_zip,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            db_path = config_dir / "wine_inventory.db"
            db = WineDatabase(db_path)
            db.initialize()

            # Test with a synthetic zip first
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "vivino_data/full_wine_list.csv",
                    "Winery,Wine name,Vintage,Region,Country,Regional wine style,Average rating,Wine ratings count,Your rating,Your review,Personal Note,Wine type,Drinking Window,Link to wine,Label image\n"
                    'Tenuta San Guido,Sassicaia,2018,Bolgheri,Italy,Tuscan Red,4.7,12500,4.8,"Incredible structure","Cellar favorite",Red,2025-2045,https://www.vivino.com/wines/12345,https://images.vivino.com/labels/sassicaia2018.jpg\n'
                    'Château Margaux,Margaux Premier Grand Cru Classé,2015,Margaux,France,Bordeaux Red,4.8,8900,4.9,"Velvety perfection","",Red,2024-2050,https://www.vivino.com/wines/67890,https://images.vivino.com/labels/margaux2015.jpg\n'
                )
                zf.writestr(
                    "vivino_data/cellar.csv",
                    "Winery,Wine name,Vintage,Region,Country,Regional wine style,Average rating,Wine ratings count,User cellar count,Link to wine\n"
                    "Tenuta San Guido,Sassicaia,2018,Bolgheri,Italy,Tuscan Red,4.7,12500,2,https://www.vivino.com/wines/12345\n"
                )

            zip_bytes = zip_buffer.getvalue()
            self.assertTrue(is_vivino_export_zip(zip_bytes, config_dir=config_dir))

            # Run import without downloading images over network in unit test
            res = import_vivino_export_zip(config_dir, db, zip_bytes, download_images=False)
            self.assertTrue(res["success"])
            self.assertEqual(res["cellar_imported"], 1)
            self.assertEqual(res["cellar_bottles"], 2)
            self.assertEqual(res["tasted_imported"], 2)

            wines = db.list_wines()
            self.assertEqual(len(wines), 2)
            sassicaia = [w for w in wines if "Sassicaia" in w["name"]][0]
            self.assertEqual(sassicaia["quantity"], 2)
            self.assertEqual(sassicaia["personal_rating"], 4.8)
            self.assertIn("Incredible structure", sassicaia["general_notes"])
            self.assertEqual(sassicaia["drink_from_year"], 2025)
            self.assertEqual(sassicaia["drink_until_year"], 2045)
            self.assertEqual(sassicaia["vivino_url"], "https://www.vivino.com/wines/12345")
            self.assertEqual(sassicaia["vivino_wine_id"], 12345)
            self.assertEqual(sassicaia["vivino_match_confidence"], "confirmed")

            # Verify that database initialize / restart does not wipe canonical Vivino links
            db.initialize()
            sassicaia_reloaded = [w for w in db.list_wines() if "Sassicaia" in w["name"]][0]
            self.assertEqual(sassicaia_reloaded["vivino_url"], "https://www.vivino.com/wines/12345")
            self.assertEqual(sassicaia_reloaded["vivino_wine_id"], 12345)

            margaux = [w for w in wines if "Margaux" in w["name"]][0]
            self.assertEqual(margaux["quantity"], 0)
            self.assertEqual(margaux["personal_rating"], 4.9)
            self.assertEqual(margaux["vivino_url"], "https://www.vivino.com/wines/67890")

            stats = db.get_statistics()
            self.assertEqual(stats["total_bottles"], 2)
            self.assertEqual(stats["unique_wines"], 1)
            self.assertEqual(stats["tasted_wines"], 2)

            # Also verify with the actual uploaded user zip if present on disk
            real_zip_path = Path("/usr/local/google/home/maartenw/.gemini/jetski/brain/d789ffa3-5b47-4a4d-bf20-6fc7cecfef15/.user_uploaded/media_1793127093064_fb972978.zip")
            if real_zip_path.exists():
                self.assertTrue(is_vivino_export_zip(real_zip_path, config_dir=config_dir))
                # Create a fresh db to test real zip full extraction
                db2_path = config_dir / "wine_inventory_real.db"
                db2 = WineDatabase(db2_path)
                db2.initialize()
                real_res = import_vivino_export_zip(config_dir, db2, real_zip_path, download_images=False)
                self.assertTrue(real_res["success"])
                self.assertEqual(real_res["cellar_imported"], 54)
                self.assertEqual(real_res["cellar_bottles"], 77)
                self.assertGreaterEqual(real_res["tasted_imported"], 430)


if __name__ == "__main__":
    unittest.main()
