<p align="center">
  <img src="assets/icon.svg" width="112" height="112" alt="Lekkersappie Red Wine Glass Icon" />
</p>

<h1 align="center">🍷 Lekkersappie</h1>

<p align="center">
  <strong>Home Assistant Wine Inventory, Gemini Flash-Lite Label Scanner &amp; Vivino Cellar Manager</strong>
</p>

---

**Lekkersappie** (`wine_inventory`) is a native Home Assistant custom integration and bundled Lovelace frontend card (`custom:wine-inventory-card`) that keeps track of your local wine inventory. It stores your cellar in a local SQLite database (`<config>/wine_inventory/wine_inventory.db`), scans wine bottle photos using **Gemini Flash-Lite** models, automatically enriches bottles with **Vivino community ratings**, and tracks every addition with date/time added, where it was bought, storage slot, drinking window (*When to Drink*), and a chronological free-form notes & tasting overview.

Built following the [**`homeassistant-ai/skills`**](https://github.com/homeassistant-ai/skills) (`home-assistant-best-practices`) standards.

---

## ✨ Key Features

- **🍷 Local SQLite Cellar Database (`wine_inventory.db`)**:
  - Relational schema with master `wines`, child `inventory_additions` batches (recording `added_at` date/time, `purchase_location`, `purchase_price`, `storage_location`, `drink_window_note`, and batch `notes`), and `consumption_history` (tasting notes & audit log).
  - Automatic Write-Ahead Log (`WAL`) checkpointing hooked into Home Assistant Core Backups (`backup.py`).
- **📸 Visual Bottle Label Scanning with Interactive Crop & Rotate (Gemini Flash-Lite)**:
  - Snap a photo directly from your smartphone camera or upload a photo from your desktop.
  - **Interactive Crop & Rotate Modal**: Rotate photos 90° in either direction and adjust the cropping box to frame only the wine label, removing backgrounds, tilted bottle angles, and glare for optimal vision recognition.
  - **Prominent Error Visibility**: Any scan failures (unreadable labels, invalid API keys, quota limits) are surfaced in a high-visibility error card with actionable troubleshooting tips and one-click "Adjust Crop & Retry".
  - Extracts Winery, Wine Name, Vintage (`YYYY` or `NV`), Wine Style (`red`, `white`, `rose`, `sparkling`, `dessert`, `fortified`), Varietal, Region, Country, Alcohol %, recommended Drinking Window (`drink_from_year`–`drink_until_year`), Food Pairings, and a concise label summary.
  - Automatically detects if the scanned bottle already exists in your cellar so you can increment your stock in one click without creating duplicate wine entries.
- **⭐ Automatic Vivino Ranking Lookup**:
  - Looks up the bottle on Vivino and populates the community star rating (`★ 4.3`), rating count, estimated price, and direct Vivino URL.
  - Includes a **3-candidate selector dropdown** in the scan dialog if a label is ambiguous, plus an automatic Gemini rating estimation fallback if Vivino rate-limits requests (`HTTP 403/429`).
- **➕ / ➖ 1-Tap Inventory Adjustments & Notes Overview**:
  - Clicking **`+`** on any wine opens a Quick-Add Batch dialog pre-filled with the current timestamp and your last used store & storage location—hit **Save** in 1 tap or add purchase context and notes.
  - Clicking **`-`** opens an **Open / Drink Bottle** dialog where you select which fridge/rack batch you pulled the bottle from, give it a `1–5` personal rating, and record tasting notes. Wines that reach `0` bottles stay preserved in the **Tasted Archive** tab so you always remember what you enjoyed.
- **🏠 100% Home Assistant-Native Visuals**:
  - Automatically registers `/wine_inventory/wine-inventory-card.js?v=1.0.0`.
  - Ships with a complete Home Assistant **`sections` dashboard** (`dashboards/wine-cellar-dashboard.yaml`) featuring native `heading`, `tile`, and `distribution` cards alongside `custom:wine-inventory-card`.

---

## 📖 User Manual

### 1. Installing Lekkersappie via HACS

1. Open your Home Assistant UI and click **HACS** in the left sidebar.
2. Click the **three dots (`⋮`)** in the top-right corner of HACS and select **Custom repositories**.
3. Fill in the dialog:
   - **Repository**: `https://github.com/Maartenwiese/lekkersappie-cellar`
   - **Type / Category**: Select **Integration**
4. Click **Add**, then close the dialog.
5. Search for **Lekkersappie** in HACS, open it, and click **Download** in the bottom-right corner. Confirm the download.
6. **Restart Home Assistant** (**Settings → System → Restart** in the top-right corner) so Home Assistant loads the custom integration.

---

### 2. Enabling & Configuring the Lekkersappie Integration

Once Home Assistant has restarted:

1. Go to **Settings → Devices & Services**.
2. Click the **+ Add Integration** button in the bottom-right corner.
3. Search for **Lekkersappie** (or **Wine Inventory**) and click it.
4. Fill in the configuration dialog:
   - **Cellar Name**: Defaults to `Lekkersappie` (determines the name of your device and summary sensors, e.g., `sensor.lekkersappie_total_bottles`).
   - **Google Gemini API Key**: Paste your Gemini API key (from [Google AI Studio](https://aistudio.google.com/apikey)) to enable photo label scanning.
   - **Gemini Flash-Lite Model ID**: Defaults to `gemini-3.8-flash-lite` (you can adjust this at any time in the integration's **Configure** options).
   - **Currency Code**: e.g., `EUR` or `USD`.
   - **Vivino Country Code**: e.g., `NL`, `US`, `FR`, `DE`, `IT`.
   - **Estimate rating via Gemini if Vivino rate-limits**: Keep enabled (`true`) so ratings are still estimated if Vivino blocks automated requests.
   - **Low Stock Alert Threshold**: Number of remaining bottles (default `2`) that triggers a `stock_low` event when you consume a bottle.
   - **Optional Cellar/Fridge Temperature & Humidity Sensors**: Enter an existing Home Assistant entity ID (e.g., `sensor.wine_fridge_temperature` and `sensor.wine_fridge_humidity`) to display live cellar conditions inside the Lekkersappie header bar.
5. Click **Submit**.
   - Lekkersappie automatically initializes `<config>/wine_inventory/wine_inventory.db`, creates 10 summary sensors + 1 activity event entity, and registers the **Lekkersappie Wine Cellar Card** (`custom:wine-inventory-card`) in Lovelace.

---

### 3. Creating Your Lekkersappie Dashboard

You can either create a dedicated **Lekkersappie** dashboard using our pre-built Home Assistant `sections` dashboard or drop the card onto an existing dashboard.

#### Option A: Create a Dedicated Full Wine Cellar Dashboard (Recommended)
1. Go to **Settings → Dashboards** and click **+ Add Dashboard** in the bottom-right corner.
2. Choose **New dashboard from scratch**:
   - **Title**: `Lekkersappie`
   - **Icon**: `mdi:glass-wine`
   - **URL path**: `lekkersappie-cellar` (must contain a hyphen)
   - Click **Create**.
3. Open your new **Lekkersappie** dashboard from the left sidebar.
4. Click the **Edit Dashboard (pencil icon)** in the top-right corner, then click the **three dots (`⋮`)** in the top-right corner and select **Raw configuration editor**.
5. Replace the contents with the YAML from [`dashboards/wine-cellar-dashboard.yaml`](dashboards/wine-cellar-dashboard.yaml) and click **Save**:
   - **Left column (`Cellar Overview`)**: Native `tile` cards for *Total Stock*, *Unique Wines*, *Ready to Drink*, *Drink Soon*, and *Cellar Valuation*, plus a native Home Assistant `distribution` bar chart showing your *Red / White / Rosé / Sparkling / Dessert* split.
   - **Right column (`Lekkersappie — Wine Inventory & Gemini Scanner`)**: The full interactive `custom:wine-inventory-card`.

#### Option B: Add the Lekkersappie Card to an Existing View
1. Open any dashboard view and click the **Edit (pencil)** icon.
2. Click **+ Add Card** and search for **Lekkersappie Wine Cellar Card** (or choose **Manual** and enter):
   ```yaml
   type: custom:wine-inventory-card
   title: Lekkersappie
   ```
3. Click **Save**. *(Tip: If the card doesn't appear right away on mobile or desktop, do a hard browser refresh `Ctrl+Shift+R` / `Cmd+Shift+R` or go to **Settings → Companion App → Debugging → Reset frontend cache**).*

---

### 4. How to Add Your First Bottle to the Inventory

Open your **Lekkersappie** dashboard card. You have two ways to add a bottle:

#### Method A: Scan a Bottle Photo (Gemini Flash-Lite + Vivino)
1. Click the primary **Scan Bottle** button (`📷`) in the top-right of the Lekkersappie card.
2. In the **Scan Wine Bottle** dialog, click **Take Photo / Upload Label**.
   - On a phone or tablet, this directly activates your device camera so you can take a photo of the bottle.
   - On a desktop, select any bottle photo from your computer.
3. The interactive **Crop & Rotate Bottle Label** modal opens immediately:
   - Click **Rotate Left (90°)** or **Rotate Right (90°)** if the bottle was photographed sideways or upside down until the label is upright.
   - Drag the crop rectangle and corner handles to tightly frame the front wine label, cutting out tables, backgrounds, reflections, or bottle necks.
   - Click **Confirm & Scan Label**.
4. Wait a couple of seconds while **Gemini Flash-Lite** extracts the label details and queries **Vivino**:
   - **Winery, Wine Name, Vintage, Wine Type, Varietal, Region, and Country** are automatically extracted and populated.
   - **Vivino Rating & URL** are populated from the best Vivino match. If multiple matches were found on Vivino, you can switch between the top 3 matches using the **Vivino Match Candidates** dropdown.
   - **Duplicate Check**: If that exact wine & vintage is already in your cellar database, a green notification banner appears (*"Already in your cellar! Saving will increment the bottle count and log this new addition batch."*).
   - **Error Visibility**: If any issue occurs (e.g., blurry image, invalid API key, or quota limit), an alert card clearly explains the root cause with troubleshooting tips and an **Adjust Crop & Retry** button so you can re-crop without re-uploading.
4. Complete the **Addition Metadata, Drinking Window & Notes** section:
   - **Quantity Added**: Number of bottles you are adding (defaults to `1`).
   - **Date / Time Added**: Automatically pre-filled with the exact current date & time (editable if backdating).
   - **Where Was It Bought?**: Enter the store, winery, website, or gift source (e.g., `Gall & Gall`, `Winery Direct`). Previously entered stores appear as autocomplete suggestions.
   - **Purchase Price & Storage Slot**: Enter the optional price per bottle and where you placed it (e.g., `Kitchen Wine Fridge - Shelf 2` or `Cellar Rack A3`).
   - **When to Drink (From Year – Until Year & Guidance)**: Review or adjust the Gemini-suggested drinking window years (e.g., `2025` – `2032`) and optional serving/occasion note (e.g., `Decant 1 hour, drink with grilled lamb`).
   - **Free-Form Notes Overview**: Overall notes about the wine (aromas, food pairings, summary).
   - **Batch / Addition Note**: Specific notes about this purchase batch.
5. Click **Save Wine to Cellar**. Your bottle immediately appears in the inventory grid with its photo thumbnail, Vivino star rating badge, drinking window readiness badge (*Ready to Drink*, *Hold / Aging*, *Drink Soon*), store, storage slot, and notes preview!

#### Method B: Add a Bottle Manually (Without a Photo)
1. Click the **+ Add Wine** button in the top-right of the Lekkersappie card.
2. Fill in the Winery, Wine Name, Vintage, Quantity, Where Bought, When to Drink, and Free-Form Notes Overview, then click **Save Wine to Cellar**.
3. You can click the **Refresh (`↻`)** button in the card header at any time to automatically fetch the Vivino rating for manually added wines!

---

### 5. Day-to-Day Cellar Operations

- **Increasing Bottle Count (`+` Button)**:
  - Tap the **`+`** button on any wine card when you buy more bottles of a wine you already own.
  - A compact **Add Bottle(s)** dialog opens, pre-filled with `+1`, the current date/time, and your last used store and storage location. Click **Save Addition** in one tap, or enter a new store/location and note for the new batch.
- **Opening / Consuming a Bottle (`-` Button)**:
  - Tap the **`-`** button when you open a bottle.
  - Select which storage batch/slot you pulled the bottle from (defaults to your oldest batch), optionally give it your **Personal Rating (`1.0–5.0` stars)**, and write **Tasting Notes**.
  - If a wine's stock reaches `0` bottles, it is never deleted—click the **Tasted Archive** filter chip at the top of the card to browse every past wine you've finished along with your ratings and tasting notes.
- **Viewing & Editing the Notes Overview & History (`Batches & Notes` Button)**:
  - Click **Batches & Notes** on any wine card to edit its master **Free-Form Notes Overview** and **Drink Window**, inspect remaining bottles across different storage slots, and read the full chronological timeline of additions and tastings.
- **Exporting Your Inventory to CSV or JSON**:
  - Click the export badge in the dashboard header (or run the `wine_inventory.export_inventory` action in **Developer Tools → Actions**) to save a complete CSV or JSON export under `/config/www/wine_inventory/exports/` (downloadable at `/local/wine_inventory/exports/wine_inventory_export.csv`).
