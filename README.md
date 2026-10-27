<p align="center">
  <img src="brand/icon.png" width="112" height="112" alt="Lekkersappie Red Wine Glass Icon" />
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
  - Searches Vivino using only text that is verifiably **printed on the label**, keeps only records whose producer **and** cuvée match exactly, and lets Gemini pick from those real records (or reject them all) by comparing them with your photo.
  - **Verified** matches (one exact record that the AI check confirms) are linked automatically. Ambiguous results are shown for you to confirm, with **🚫 Do not link** selected by default.
  - Ratings are never estimated: if Vivino has no verified record (or blocks the request), the wine stays unlinked. You can always paste an exact Vivino link in the Details view or remove a link.
- **➕ / ➖ 1-Tap Inventory Adjustments & Notes Overview**:
  - Clicking **`+`** on any wine opens a Quick-Add Batch dialog pre-filled with the current timestamp and your last used store & storage location—hit **Save** in 1 tap or add purchase context and notes.
  - Clicking **`-`** opens an **Open / Drink Bottle** dialog where you select which fridge/rack batch you pulled the bottle from, give it a `1–5` personal rating, and record tasting notes. Wines that reach `0` bottles stay preserved in the **Tasted Archive** tab so you always remember what you enjoyed.
- **🏠 100% Home Assistant-Native Visuals & Addable Lovelace Cards**:
  - Automatically registers `/wine_inventory/wine-inventory-card.js`.
  - Ships with two cards in the Home Assistant UI Card Picker (with visual GUI editors):
    1. **Lekkersappie Wine Cellar Card** (`custom:wine-inventory-card`) — full cellar manager, label scanner, and tasting archive.
    2. **Lekkersappie Cellar Quick Card** (`custom:wine-cellar-summary-card`) — compact summary widget you can drop onto any existing Home Assistant dashboard page (showing total bottles, ready-now count, style bar, recent bottles, and 1-tap Scan / Mobile App buttons).
  - Ships with a complete Home Assistant **`sections` dashboard** (`dashboards/wine-cellar-dashboard.yaml`) featuring native `heading`, `tile`, and `distribution` cards alongside `custom:wine-inventory-card` and `custom:wine-cellar-summary-card`.
- **📱 Standalone Installable Mobile Web App (`/lekkersappie`)**:
  - Runs a modern, mobile-first Progressive Web App (PWA) at **`http://<your-home-assistant>:8123/lekkersappie`** in parallel to the native Home Assistant UI.
  - **Inherits Home Assistant Authentication**: Automatically reuses your Home Assistant login session (`hassTokens` / synced token with automatic OAuth2 refresh and native `/auth/authorize` login fallback) and enforces `requires_auth = True` on all mobile API endpoints.
  - **Rich Mobile List View & Large (`L`) Default Text**: Defaults to Large (`L`, `115%`) font sizing and displays grape variety (`🍇`), bought/added date (`🗓️`), store (`🛒`), price (`💰`), vintage (`📅`), storage area (`📍`), origin (`🌍`), Vivino badge (`★`), and drinking window status on each line item.
  - **Camera & Photo Library Support**: Scanning a bottle offers both **📷 Take Photo (Camera)** and **🖼️ Choose from Library** with interactive crop & rotate.
  - **Touch-first design**: 48 px+ tap targets, a finger-friendly **Crop & Rotate** (drag the frame, drag corners/edges to resize, ±90° rotation plus a −20°…+20° straighten slider), swipe-down to close sheets, pull-to-refresh, bottom-sheet confirmations, and numeric keypads for years, quantities and prices.
  - **📊 Stats tab**: bottles, value, average price, average Vivino rating, drinking-window breakdown, highest-rated and drink-first wines, vintage spread, top countries, grapes and stores, recent activity, and storage areas.
  - **⚙️ Config tab**: text size, appearance, app installation, and Vivino refresh.
  - Installable directly to your iPhone/iPad or Android Home Screen (`display: standalone`) with a thumb-friendly bottom navigation bar, floating `SCAN` button, smooth-scrolling slide-up Wine Details sheet, `Aa` text scaling (`S` / `M` / `L` / `XL`) across all views and modals, and Service Worker caching.

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

#### Option B: Add a Lekkersappie Card to Any Existing Home Assistant Page
Both Lekkersappie cards appear directly in the Home Assistant **+ Add Card** picker with a visual GUI editor:

1. Open any dashboard view and click the **Edit (pencil)** icon, then click **+ Add Card**.
2. Search for **Lekkersappie** and choose either:
   - **Lekkersappie Cellar Quick Card** (`custom:wine-cellar-summary-card`) — a compact card ideal for your main home/kitchen overview page:
     ```yaml
     type: custom:wine-cellar-summary-card
     title: Lekkersappie Cellar
     show_recent: true
     show_style_bar: true
     dashboard_path: /lekkersappie-cellar/overview
     ```
   - **Lekkersappie Wine Cellar Card** (`custom:wine-inventory-card`) — the full interactive cellar inventory and scanner:
     ```yaml
     type: custom:wine-inventory-card
     title: Lekkersappie
     default_view: list
     font_scale: 1
     ```
3. Click **Save**. *(Tip: If the card doesn't appear right away on mobile or desktop, do a hard browser refresh `Ctrl+Shift+R` / `Cmd+Shift+R` or go to **Settings → Companion App → Debugging → Reset frontend cache**).*

#### Option C: Launch & Install the Standalone Mobile Web App (`/lekkersappie`)
Lekkersappie serves a parallel, mobile-first web app designed for one-handed phone use in your cellar or kitchen:

1. Open **`http://<your-home-assistant>:8123/lekkersappie`** in Chrome (Android) or Safari (iOS), or tap the **📱 Mobile App** button in the header of any Lekkersappie card.
2. Tap **📲 Install** in the top bar (or the install banner):
   - **Android (Chrome / Edge)**: Prompts the native **Install app** dialog and adds **Lekkersappie** to your app drawer.
   - **iPhone / iPad (Safari)**: Tap Safari’s **Share** button → **Add to Home Screen** to launch Lekkersappie full-screen (`standalone`) with its own white wine-glass app icon.
3. Adjust text size (`S` / `M` / `L` / `XL`) and appearance in the **⚙️ Config** tab. The app opens with a short Lekkersappie splash screen (once per session), uses a full-height layout without a header, and every sheet has a **‹ Back** button. The phone's back button or back gesture also returns to the previous page.

---

### 4. How to Add Your First Bottle to the Inventory

Open your **Lekkersappie** dashboard card. You have two ways to add a bottle:

#### Method A: Scan a Bottle Photo (Gemini Flash-Lite + Vivino)
1. Click the primary **Scan Bottle** button (`📷`) in the top-right of the Lekkersappie card (or the floating **SCAN** button in the mobile app).
2. In the **Scan Wine Bottle** dialog, choose either **📷 Take Photo (Camera)** to snap a live photo with your phone's camera or **🖼️ Choose from Library** to pick an existing photo from your phone's photo library / computer.
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
- **Switching Between Grid & Line-Item List Views**:
  - In the Lekkersappie card header, toggle between **Grid View** (`mdi:view-grid`) and **Line-Item List View** (`mdi:view-list`).
  - In **Line-Item List View**, each wine is rendered as a clean, compact line item displaying its label thumbnail, winery, vintage, wine type, drinking window, Vivino rating, inline bottle stepper (`-` and `+`), and details button.
  - You can also set `default_view: list` or `default_view: grid` directly in the card's Lovelace YAML configuration or use the dedicated **Wine List** view in `dashboards/wine-cellar-dashboard.yaml`.
- **Database Backup, Restore & Import (.zip / JSON / CSV)**:
  - **Download Full Backup (.zip)**: Exports a self-contained archive containing `wine_inventory.db`, all bottle cover photos (`covers/`), and structured JSON metadata. You can create a backup from the **Backup / Import** button in the card header, from the integration options (**Settings → Devices & Services → Lekkersappie → Configure → Create Full Backup**), or via the `wine_inventory.create_backup` action.
  - **Restore Database (.zip)**: Restore a previous `.zip` backup archive either by uploading it directly through the card modal or through the integration configure options (**Settings → Devices & Services → Lekkersappie → Configure → Restore Database from Backup**).
  - **Import Wines (JSON / CSV / ZIP)**: Import wines in bulk from external CSV spreadsheets, JSON export arrays, or other cellar archives without overwriting existing wines. Available in the card modal and the integration configure options.
- **Exporting Your Inventory to CSV or JSON**:
  - Click the export badge in the dashboard header (or run the `wine_inventory.export_inventory` action in **Developer Tools → Actions**) to save a complete CSV or JSON export under `/config/www/wine_inventory/exports/` (downloadable at `/local/wine_inventory/exports/wine_inventory_export.csv`).
