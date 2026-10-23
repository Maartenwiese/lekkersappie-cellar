# Wine Inventory & Cellar Scanner (`wine_inventory`) for Home Assistant

A native Home Assistant custom integration and Lovelace UI card for tracking your local wine cellar, scanning bottle labels with **Gemini Flash-Lite**, automatically enriching wines with **Vivino community ratings**, tracking purchase batches (`added_at`, `where_bought`, `storage_location`, `when_to_drink`), and maintaining a rich free-form notes & tasting overview.

Designed and built using the [**`homeassistant-ai/skills`**](https://github.com/homeassistant-ai/skills) (`home-assistant-best-practices`) engineering standards.

## Key Features

1. **Local SQLite Cellar Database (`wine_inventory.db`)**:
   - Relational schema with `wines` (master catalog), `inventory_additions` (purchase batches with `added_at` timestamp, `purchase_location`, `purchase_price`, `storage_location`, `drink_window_note`, and batch `notes`), and `consumption_history` (audit & tasting notes log).
   - Automatic Write-Ahead Log (`WAL`) checkpointing integrated with Home Assistant Core Backups (`backup.py`).
2. **Gemini Flash-Lite Bottle Label Scanning**:
   - Snap a photo from the Home Assistant mobile/web UI (`capture="environment"`) or capture a frame from any `camera.*` / `image.*` entity.
   - Extracts winery, wine name, vintage, wine type (`red`, `white`, `rose`, `sparkling`, `dessert`, `fortified`), grape varietal, region, country, alcohol %, suggested drinking window (`drink_from_year`–`drink_until_year`), food pairings, and label summary.
   - Detects existing wines in your cellar to prevent duplicate records and saves a local cover image under `/local/wine_inventory/covers/`.
3. **Vivino Rating & Candidate Lookup**:
   - Queries Vivino for the scanned wine and presents the top rating (`★ 4.3`), rating count, estimated retail price, and direct Vivino URL, plus a 3-candidate selector in the scan modal if a label is ambiguous.
   - Includes an automatic Gemini rating estimation fallback if Vivino rate-limits requests (`HTTP 403/429`).
4. **1-Tap `+1` / `-1` Inventory Adjustments & Notes Overview**:
   - Clicking **`+`** opens a pre-filled Quick-Add Batch dialog with the current date/time and last used store/storage location—save in 1 tap or add purchase notes.
   - Clicking **`-`** opens a Consume & Tasting Note dialog where you pick which storage slot you pulled the bottle from, rate the wine (`1–5` stars), and log tasting notes. Wines reaching `0` bottles remain accessible in the **Tasted Archive** tab.
5. **100% Home Assistant-Native Visuals**:
   - Auto-registers `/wine_inventory/wine-inventory-card.js?v=1.0.0`.
   - Includes a modern Home Assistant `sections` dashboard (`dashboards/wine-cellar-dashboard.yaml`) using `heading`, `tile`, `distribution`, and `custom:wine-inventory-card`.
