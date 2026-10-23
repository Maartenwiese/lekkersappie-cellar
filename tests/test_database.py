"""Unit tests for the WineDatabase SQLite engine."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
