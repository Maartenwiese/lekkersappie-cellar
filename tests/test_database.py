"""Unit tests for the WineDatabase SQLite engine."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from custom_components.wine_inventory.const import (
    DRINK_STATUS_DRINK_SOON,
    DRINK_STATUS_HOLD,
    DRINK_STATUS_PAST_PEAK,
    DRINK_STATUS_READY,
    DRINK_STATUS_UNKNOWN,
)
from custom_components.wine_inventory.database import WineDatabase, compute_drink_status


class TestWineDatabase(unittest.TestCase):
    """Test cases for SQLite database schema, batch additions, FIFO consumption, and notes."""

    def test_compute_drink_status(self) -> None:
        """Verify drinking window readiness transitions across years."""
        self.assertEqual(
            compute_drink_status(None, None, reference_year=2026),
            DRINK_STATUS_UNKNOWN,
        )
        self.assertEqual(
            compute_drink_status(2028, 2035, reference_year=2026),
            DRINK_STATUS_HOLD,
        )
        self.assertEqual(
            compute_drink_status(2024, 2030, reference_year=2026),
            DRINK_STATUS_READY,
        )
        self.assertEqual(
            compute_drink_status(2020, 2027, reference_year=2026),
            DRINK_STATUS_DRINK_SOON,
        )
        self.assertEqual(
            compute_drink_status(2018, 2024, reference_year=2026),
            DRINK_STATUS_PAST_PEAK,
        )

    def test_add_duplicate_batches_and_consume_fifo(self) -> None:
        """Verify master wine creation, duplicate batch increment, and FIFO/batch consumption."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = WineDatabase(Path(tmpdir) / "wine_inventory.db")
            db.initialize()

            # 1. Add initial 2 bottles bought at Store A
            wine1 = db.add_or_increment_wine(
                winery="Château Margaux",
                name="Pavillon Rouge",
                vintage=2018,
                wine_type="red",
                varietal="Cabernet Sauvignon, Merlot",
                region="Margaux",
                country="France",
                vivino_rating=4.3,
                vivino_ratings_count=3200,
                vivino_url="https://www.vivino.com/wines/12345",
                drink_from_year=2024,
                drink_until_year=2035,
                drink_window_note="Decant 2 hours",
                food_pairings=["Beef", "Lamb"],
                general_notes="Rich cedar and cassis bouquet.",
                quantity=2,
                added_at="2026-10-20T18:00:00+00:00",
                purchase_location="Gall & Gall Amsterdam",
                purchase_price=165.0,
                storage_location="Basement Cellar - Rack A1",
                batch_notes="Bought for anniversary",
            )

            self.assertEqual(wine1["id"], 1)
            self.assertEqual(wine1["quantity"], 2)
            self.assertEqual(wine1["last_purchase_location"], "Gall & Gall Amsterdam")
            self.assertEqual(wine1["last_storage_location"], "Basement Cellar - Rack A1")
            self.assertEqual(len(wine1["batches"]), 1)
            self.assertEqual(len(wine1["timeline"]), 1)

            # 2. Check duplicate match lookup on scan
            matched = db.find_matching_wine("château margaux", "Pavillon Rouge", 2018)
            self.assertIsNotNone(matched)
            assert matched is not None
            self.assertEqual(matched["id"], wine1["id"])

            # 3. Add 1 more bottle of the same wine bought at Store B (stored in Kitchen Fridge)
            wine2 = db.add_or_increment_wine(
                winery="Château Margaux",
                name="Pavillon Rouge",
                vintage=2018,
                wine_type="red",
                quantity=1,
                added_at="2026-10-23T12:00:00+00:00",
                purchase_location="Bordeaux Winery Direct",
                purchase_price=155.0,
                storage_location="Kitchen Wine Fridge - Shelf 2",
                batch_notes="Picked up on vacation",
            )

            self.assertEqual(wine2["id"], wine1["id"])
            self.assertEqual(wine2["quantity"], 3)
            self.assertEqual(len(wine2["batches"]), 2)
            self.assertEqual(
                set(wine2["active_storage_locations"]),
                {"Basement Cellar - Rack A1", "Kitchen Wine Fridge - Shelf 2"},
            )

            # 4. Consume 1 bottle (-1) with personal rating and tasting note
            after_consume = db.adjust_quantity(
                wine_id=wine1["id"],
                delta=-1,
                notes="Opened with ribeye steak; velvet tannins.",
                personal_rating=4.5,
            )
            self.assertEqual(after_consume["quantity"], 2)
            self.assertEqual(after_consume["personal_rating"], 4.5)
            self.assertEqual(len(after_consume["timeline"]), 3)
            self.assertEqual(after_consume["timeline"][0]["event_type"], "consumed")
            self.assertEqual(after_consume["timeline"][0]["delta"], -1)
            self.assertIn("ribeye", after_consume["timeline"][0]["tasting_notes"])

            # 5. Consume remaining 2 bottles so stock hits 0 -> moves to Tasted Archive
            after_empty = db.adjust_quantity(
                wine_id=wine1["id"],
                delta=-2,
                notes="Finished last 2 bottles at dinner party.",
            )
            self.assertEqual(after_empty["quantity"], 0)

            stats = db.get_statistics()
            self.assertEqual(stats["total_bottles"], 0)
            self.assertEqual(stats["unique_wines"], 0)
            self.assertEqual(stats["archived_wines"], 1)
            self.assertIn("Gall & Gall Amsterdam", stats["known_purchase_locations"])
            self.assertIn("Kitchen Wine Fridge - Shelf 2", stats["known_storage_locations"])

    def test_update_wine_and_checkpoint(self) -> None:
        """Verify updating wine notes overview, drinking window, and WAL checkpointing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = WineDatabase(Path(tmpdir) / "wine_inventory.db")
            db.initialize()

            wine = db.add_or_increment_wine(
                winery="Cloudy Bay",
                name="Sauvignon Blanc",
                vintage=2025,
                wine_type="white",
                quantity=4,
                drink_from_year=2025,
                drink_until_year=2027,
                purchase_price=28.50,
            )

            updated = db.update_wine(
                wine["id"],
                {
                    "general_notes": "Crisp passionfruit and lime zest.",
                    "drink_window_note": "Serve chilled at 8°C",
                    "vivino_rating": 4.2,
                },
            )
            self.assertEqual(updated["general_notes"], "Crisp passionfruit and lime zest.")
            self.assertEqual(updated["drink_window_note"], "Serve chilled at 8°C")
            self.assertEqual(updated["vivino_rating"], 4.2)

            stats = db.get_statistics()
            self.assertEqual(stats["total_bottles"], 4)
            self.assertEqual(stats["by_type"]["white"], 4)
            self.assertEqual(stats["estimated_value"], 114.0)

            db.checkpoint_wal()

    def test_storage_location_and_research_notes(self) -> None:
        """Verify storage location updates on wine and batches, and research notes persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = WineDatabase(Path(tmpdir) / "wine_inventory.db")
            db.initialize()

            wine = db.add_or_increment_wine(
                winery="Tenuta San Guido",
                name="Sassicaia",
                vintage=2018,
                wine_type="red",
                varietal="Cabernet Sauvignon, Cabernet Franc",
                region="Bolgheri",
                country="Italy",
                quantity=3,
                storage_location="Wine Fridge Rack 2",
            )
            self.assertEqual(wine["storage_location"], "Wine Fridge Rack 2")
            self.assertEqual(wine["country"], "Italy")
            self.assertEqual(wine["varietal"], "Cabernet Sauvignon, Cabernet Franc")

            research_payload = json.dumps({
                "producer_history": "Pioneering Bolgheri estate founded by Mario Incisa della Rocchetta.",
                "wine_and_terroir": "Gravelly soils similar to Graves in Bordeaux.",
                "summary": "Legendary Super Tuscan icon.",
            })
            updated = db.update_wine(
                wine["id"],
                {
                    "storage_location": "Underground Cellar Bin 4",
                    "research_notes": research_payload,
                },
            )
            self.assertEqual(updated["storage_location"], "Underground Cellar Bin 4")
            self.assertIn("Pioneering Bolgheri estate", updated["research_notes"])

            detail = db.get_wine_detail(wine["id"])
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["storage_location"], "Underground Cellar Bin 4")
            self.assertEqual(detail["batches"][0]["storage_location"], "Underground Cellar Bin 4")

            # 3. Test editable purchase location and purchase price
            updated_purchase = db.update_wine(
                wine["id"],
                {
                    "purchase_location": "Boutique Wine Merchant",
                    "purchase_price": 285.50,
                },
            )
            self.assertEqual(updated_purchase["purchase_location"], "Boutique Wine Merchant")
            self.assertEqual(updated_purchase["purchase_price"], 285.50)

            detail_after_price = db.get_wine_detail(wine["id"])
            assert detail_after_price is not None
            self.assertEqual(detail_after_price["purchase_location"], "Boutique Wine Merchant")
            self.assertEqual(detail_after_price["purchase_price"], 285.50)
            self.assertEqual(detail_after_price["batches"][0]["purchase_location"], "Boutique Wine Merchant")
            self.assertEqual(detail_after_price["batches"][0]["purchase_price"], 285.50)

            # 4. Test Unlink Vivino
            db.update_wine(
                wine["id"],
                {
                    "vivino_rating": 4.6,
                    "vivino_ratings_count": 1250,
                    "vivino_url": "https://www.vivino.com/wines/sassicaia-2018",
                    "vivino_price_estimate": 290.0,
                    "rating_source": "vivino",
                },
            )
            detail_with_vivino = db.get_wine_detail(wine["id"])
            assert detail_with_vivino is not None
            self.assertEqual(detail_with_vivino["vivino_rating"], 4.6)
            self.assertEqual(detail_with_vivino["vivino_url"], "https://www.vivino.com/wines/sassicaia-2018")

            unlinked = db.unlink_vivino(wine["id"])
            self.assertIsNone(unlinked["vivino_rating"])
            self.assertIsNone(unlinked["vivino_ratings_count"])
            self.assertEqual(unlinked["vivino_url"], "")
            self.assertIsNone(unlinked["vivino_price_estimate"])
            self.assertEqual(unlinked["rating_source"], "")

            detail_unlinked = db.get_wine_detail(wine["id"])
            assert detail_unlinked is not None
            self.assertIsNone(detail_unlinked["vivino_rating"])
            self.assertEqual(detail_unlinked["vivino_url"], "")

    def test_vivino_grounding_migration_clears_untrusted_links(self) -> None:
        """Gemini-estimated ratings and legacy /wines/<id> links are cleared on startup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = WineDatabase(Path(tmpdir) / "wine_inventory.db")
            db.initialize()
            est = db.add_or_increment_wine(
                winery="Estate A", name="Cuvee A", vivino_rating=4.1, rating_source="gemini_estimate"
            )
            legacy = db.add_or_increment_wine(
                winery="Antinori", name="Tignanello", vintage=2019, vivino_rating=4.6,
                vivino_url="https://www.vivino.com/wines/1652?year=2019", rating_source="vivino",
            )
            good = db.add_or_increment_wine(
                winery="Penfolds", name="Grange", vintage=2018, vivino_rating=4.7,
                vivino_url="https://www.vivino.com/w/1136930?year=2018", rating_source="vivino",
                vivino_wine_id=1136930, vivino_match_confidence="high",
            )
            db.initialize()  # simulate restart after upgrade

            e = db.get_wine_detail(est["id"]); l = db.get_wine_detail(legacy["id"]); g = db.get_wine_detail(good["id"])
            assert e and l and g
            self.assertIsNone(e["vivino_rating"])
            self.assertEqual(e["rating_source"], "")
            self.assertEqual(l["vivino_url"], "")
            self.assertIsNone(l["vivino_rating"])
            self.assertEqual(g["vivino_url"], "https://www.vivino.com/w/1136930?year=2018")
            self.assertEqual(g["vivino_rating"], 4.7)
            self.assertEqual(g["vivino_wine_id"], 1136930)
            self.assertEqual(g["vivino_match_confidence"], "high")

    def test_empty_string_numeric_fields_and_legacy_db_self_healing(self) -> None:
        """v0.3.5 regression: empty strings '' in numeric fields never raise ValueError in float()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = WineDatabase(Path(tmpdir) / "wine_inventory.db")
            db.initialize()

            # 1. Saving a wine with empty strings "" in numeric fields (like an unlinked scan form)
            wine = db.add_or_increment_wine(
                winery="Bodegas Muga",
                name="Reserva",
                vintage="",  # type: ignore[arg-type]
                vivino_rating="",  # type: ignore[arg-type]
                vivino_price_estimate="",  # type: ignore[arg-type]
                purchase_price="",  # type: ignore[arg-type]
                personal_rating="",  # type: ignore[arg-type]
                alcohol_pct="",  # type: ignore[arg-type]
                drink_from_year="",  # type: ignore[arg-type]
                drink_until_year="",  # type: ignore[arg-type]
                quantity=2,
            )
            self.assertIsNone(wine["vintage"])
            self.assertIsNone(wine["vivino_rating"])
            self.assertIsNone(wine["vivino_price_estimate"])
            self.assertIsNone(wine["purchase_price"])
            stats = db.get_statistics()
            self.assertEqual(stats["total_bottles"], 2)
            self.assertEqual(stats["estimated_value"], 0.0)

            # 2. Updating a wine with empty strings "" in numeric fields
            updated = db.update_wine(
                wine["id"],
                {
                    "vintage": "",
                    "purchase_price": "",
                    "vivino_rating": "",
                    "vivino_price_estimate": "",
                    "drink_from_year": "",
                    "drink_until_year": "",
                    "personal_rating": "",
                },
            )
            self.assertIsNone(updated["purchase_price"])
            self.assertIsNone(updated["vivino_price_estimate"])
            self.assertEqual(db.get_statistics()["estimated_value"], 0.0)

            # 3. Simulate a pre-v0.3.5 database row that already has '' stored in REAL/INTEGER columns
            with db._connect() as conn, conn:
                conn.execute(
                    """
                    UPDATE wines
                    SET vivino_price_estimate = '',
                        vivino_rating = '',
                        purchase_price = '',
                        drink_from_year = '',
                        drink_until_year = ''
                    WHERE id = ?
                    """,
                    (wine["id"],),
                )
            # Even before re-running initialize(), list_wines() and get_statistics() must not fail
            stats_before_init = db.get_statistics()
            self.assertEqual(stats_before_init["total_bottles"], 2)
            self.assertEqual(stats_before_init["estimated_value"], 0.0)

            # Running initialize() heals the raw SQLite columns back to NULL
            db.initialize()
            with db._connect() as conn:
                raw_row = conn.execute(
                    "SELECT vivino_price_estimate, vivino_rating, purchase_price, drink_from_year FROM wines WHERE id = ?",
                    (wine["id"],),
                ).fetchone()
                self.assertIsNone(raw_row["vivino_price_estimate"])
                self.assertIsNone(raw_row["vivino_rating"])
                self.assertIsNone(raw_row["purchase_price"])
                self.assertIsNone(raw_row["drink_from_year"])


if __name__ == "__main__":
    unittest.main()
