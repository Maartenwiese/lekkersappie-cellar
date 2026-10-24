/**
 * Wine Inventory & Cellar Scanner Lovelace Card (`custom:wine-inventory-card`)
 * Built using native Home Assistant Web Components (<ha-card>, <ha-icon>) and HA CSS variables.
 */

const WINE_TYPE_LABELS = {
  red: "Red",
  white: "White",
  rose: "Rosé",
  sparkling: "Sparkling",
  dessert: "Dessert",
  fortified: "Fortified",
};

const DRINK_STATUS_META = {
  ready: { label: "Ready to Drink", color: "var(--success-color, #2e7d32)" },
  drink_soon: { label: "Drink Soon", color: "var(--warning-color, #ef6c00)" },
  hold: { label: "Hold / Aging", color: "var(--info-color, #0288d1)" },
  past_peak: { label: "Past Peak", color: "var(--error-color, #c62828)" },
  unknown: { label: "No Window Set", color: "var(--secondary-text-color, #757575)" },
};

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function nowLocalIsoMinutes() {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 16);
}

function formatDisplayDate(isoStr) {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return String(isoStr).slice(0, 16);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

class WineInventoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._wines = [];
    this._statistics = {};
    this._cellarName = "Lekkersappie";
    this._currency = "EUR";
    this._tempEntity = "";
    this._humidityEntity = "";
    this._loading = false;
    this._error = "";

    // Filter & sort UI state
    this._filterTab = "all";
    this._searchQuery = "";
    this._sortBy = "recent";
    this._viewMode = "list";
    this._userToggledView = false;

    // Active modal state: null | "scan" | "crop_rotate" | "quick_add" | "consume" | "detail" | "backup" | "image_preview"
    this._activeModal = null;
    this._modalWine = null;
    this._cropState = null;
    this._previewImageWine = null;
    this._previousModal = null;
    this._backupState = {
      busy: false,
      error: "",
      success: "",
      backups: [],
    };
    this._scanState = {
      busy: false,
      error: "",
      imageData: "",
      vivinoCandidates: [],
      vivinoStatus: "",
      existingWine: null,
      form: this._emptyForm(),
    };
  }

  _emptyForm() {
    return {
      wine_id: null,
      winery: "",
      name: "",
      vintage: "",
      wine_type: "red",
      varietal: "",
      region: "",
      country: "",
      alcohol_pct: "",
      bottle_size_ml: 750,
      vivino_rating: "",
      vivino_ratings_count: null,
      vivino_url: "",
      vivino_price_estimate: "",
      rating_source: "",
      drink_from_year: "",
      drink_until_year: "",
      drink_window_note: "",
      food_pairings: "",
      general_notes: "",
      batch_notes: "",
      quantity: 1,
      added_at: nowLocalIsoMinutes(),
      purchase_location: "",
      purchase_price: "",
      storage_location: "",
    };
  }

  setConfig(config) {
    this._config = config || {};
    if (this._config.title) {
      this._cellarName = this._config.title;
    }
    if (!this._userToggledView) {
      this._viewMode = this._config.default_view === "grid" ? "grid" : "list";
    }
    this._render();
  }

  set hass(hass) {
    const firstBind = !this._hass;
    this._hass = hass;
    if (firstBind) {
      this._fetchInventory();
    } else {
      this._updateEnvironmentBadges();
    }
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return {
      columns: "full",
      min_columns: 6,
      rows: "auto",
    };
  }

  async _fetchInventory() {
    if (!this._hass) return;
    this._loading = true;
    this._error = "";
    try {
      const res = await this._hass.callWS({
        type: "wine_inventory/list",
        include_out_of_stock: true,
      });
      this._wines = res.wines || [];
      this._statistics = res.statistics || {};
      this._cellarName = this._config.title || res.cellar_name || "Lekkersappie";
      this._currency = res.currency || "EUR";
      this._tempEntity = res.temperature_entity || "";
      this._humidityEntity = res.humidity_entity || "";
    } catch (err) {
      this._error = err?.message || "Failed to load Wine Inventory from Home Assistant.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  _updateEnvironmentBadges() {
    if (!this.shadowRoot || !this._hass) return;
    const tempEl = this.shadowRoot.querySelector("#env-temp-val");
    if (tempEl && this._tempEntity && this._hass.states[this._tempEntity]) {
      const st = this._hass.states[this._tempEntity];
      tempEl.textContent = `${st.state} ${st.attributes.unit_of_measurement || "°C"}`;
    }
    const humEl = this.shadowRoot.querySelector("#env-hum-val");
    if (humEl && this._humidityEntity && this._hass.states[this._humidityEntity]) {
      const st = this._hass.states[this._humidityEntity];
      humEl.textContent = `${st.state} ${st.attributes.unit_of_measurement || "%"}`;
    }
  }

  _getFilteredAndSortedWines() {
    const q = (this._searchQuery || "").trim().toLowerCase();
    let list = this._wines.filter((w) => {
      const qty = Number(w.quantity || 0);
      if (this._filterTab === "archived") {
        if (qty !== 0) return false;
      } else {
        if (qty <= 0) return false;
        if (this._filterTab === "ready" && w.drink_status !== "ready" && w.drink_status !== "drink_soon") {
          return false;
        }
        if (this._filterTab === "drink_soon" && w.drink_status !== "drink_soon") {
          return false;
        }
        if (["red", "white", "rose", "sparkling"].includes(this._filterTab) && w.wine_type !== this._filterTab) {
          return false;
        }
        if (this._filterTab === "dessert" && !["dessert", "fortified"].includes(w.wine_type)) {
          return false;
        }
      }

      if (!q) return true;
      const haystack = [
        w.winery,
        w.name,
        w.vintage,
        w.varietal,
        w.region,
        w.country,
        w.general_notes,
        w.drink_window_note,
        w.last_purchase_location,
        w.last_storage_location,
        ...(w.food_pairings || []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });

    list.sort((a, b) => {
      if (this._sortBy === "rating") {
        return Number(b.vivino_rating || 0) - Number(a.vivino_rating || 0);
      }
      if (this._sortBy === "drink_window") {
        const ay = Number(a.drink_until_year || 9999);
        const by = Number(b.drink_until_year || 9999);
        return ay - by;
      }
      if (this._sortBy === "vintage") {
        const av = Number(a.vintage || 9999);
        const bv = Number(b.vintage || 9999);
        return av - bv;
      }
      if (this._sortBy === "quantity") {
        return Number(b.quantity || 0) - Number(a.quantity || 0);
      }
      // default: recent
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });

    return list;
  }

  _openScanModal(manualOnly = false) {
    this._activeModal = "scan";
    this._scanState = {
      busy: false,
      error: "",
      manualOnly,
      imageData: "",
      vivinoCandidates: [],
      vivinoStatus: "",
      existingWine: null,
      form: this._emptyForm(),
    };
    this._render();
  }

  _openQuickAddModal(wine) {
    this._activeModal = "quick_add";
    this._modalWine = wine;
    this._quickAddForm = {
      wine_id: wine.id,
      quantity: 1,
      added_at: nowLocalIsoMinutes(),
      purchase_location: wine.last_purchase_location || "",
      purchase_price: wine.last_purchase_price ?? "",
      storage_location: wine.last_storage_location || "",
      drink_window_note: wine.drink_window_note || "",
      notes: "",
    };
    this._render();
  }

  _openConsumeModal(wine) {
    this._activeModal = "consume";
    this._modalWine = wine;
    const activeBatches = (wine.batches || []).filter((b) => Number(b.quantity_remaining) > 0);
    this._consumeForm = {
      wine_id: wine.id,
      delta: -1,
      batch_id: activeBatches.length > 0 ? activeBatches[activeBatches.length - 1].id : null,
      personal_rating: wine.personal_rating ?? "",
      notes: "",
    };
    this._render();
  }

  _openDetailModal(wine) {
    this._activeModal = "detail";
    this._modalWine = wine;
    this._detailForm = {
      wine_id: wine.id,
      general_notes: wine.general_notes || "",
      drink_from_year: wine.drink_from_year ?? "",
      drink_until_year: wine.drink_until_year ?? "",
      drink_window_note: wine.drink_window_note || "",
      vivino_rating: wine.vivino_rating ?? "",
      vivino_url: wine.vivino_url || "",
      personal_rating: wine.personal_rating ?? "",
    };
    this._render();
  }

  _closeModal() {
    this._activeModal = null;
    this._modalWine = null;
    this._render();
  }

  async _handleFileSelected(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";
    this._scanState.busy = true;
    this._scanState.error = "";
    this._render();

    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        this._cropState = {
          image: img,
          originalDataUrl: String(reader.result || ""),
          rotation: 0,
          crop: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 },
          dragging: false,
          dragHandle: null,
          dragStart: { px: 0, py: 0 },
          initialCrop: null,
        };
        this._scanState.busy = false;
        this._activeModal = "crop_rotate";
        this._render();
      };
      img.onerror = () => {
        this._scanState.busy = false;
        this._scanState.error = "Failed to decode the selected image file. Please choose a valid JPG/PNG/WebP photo.";
        this._render();
      };
      img.src = String(reader.result || "");
    };
    reader.onerror = () => {
      this._scanState.busy = false;
      this._scanState.error = "Failed to read image file from your device.";
      this._render();
    };
    reader.readAsDataURL(file);
  }

  _rotateCrop(delta) {
    if (!this._cropState) return;
    this._cropState.rotation = (this._cropState.rotation + delta + 360) % 360;
    this._cropState.crop = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
    this._render();
  }

  _resetCrop() {
    if (!this._cropState) return;
    this._cropState.crop = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
    this._drawCropCanvas();
  }

  _cancelCrop() {
    this._activeModal = "scan";
    this._render();
  }

  _confirmCropAndScan() {
    if (!this._cropState || !this._cropState.image) return;
    const { image, rotation, crop } = this._cropState;
    const origW = image.naturalWidth || image.width;
    const origH = image.naturalHeight || image.height;
    const isSideways = rotation === 90 || rotation === 270;
    const rotW = isSideways ? origH : origW;
    const rotH = isSideways ? origW : origH;

    const fullCanvas = document.createElement("canvas");
    fullCanvas.width = rotW;
    fullCanvas.height = rotH;
    const fctx = fullCanvas.getContext("2d");
    if (!fctx) return;
    fctx.translate(rotW / 2, rotH / 2);
    fctx.rotate((rotation * Math.PI) / 180);
    fctx.drawImage(image, -origW / 2, -origH / 2);

    const pixelX = Math.max(0, Math.round(crop.x * rotW));
    const pixelY = Math.max(0, Math.round(crop.y * rotH));
    const pixelW = Math.min(rotW - pixelX, Math.max(32, Math.round(crop.width * rotW)));
    const pixelH = Math.min(rotH - pixelY, Math.max(32, Math.round(crop.height * rotH)));

    const cropCanvas = document.createElement("canvas");
    cropCanvas.width = pixelW;
    cropCanvas.height = pixelH;
    const cctx = cropCanvas.getContext("2d");
    if (!cctx) return;
    cctx.drawImage(fullCanvas, pixelX, pixelY, pixelW, pixelH, 0, 0, pixelW, pixelH);

    const croppedDataUrl = cropCanvas.toDataURL("image/jpeg", 0.92);
    this._scanState.imageData = croppedDataUrl;
    this._activeModal = "scan";
    this._render();
    this._runBottleScan({ image_data: croppedDataUrl });
  }

  _setupCropCanvas() {
    const canvas = this.shadowRoot.querySelector("#crop-canvas");
    const wrapper = this.shadowRoot.querySelector("#canvas-wrapper");
    if (!canvas || !wrapper || !this._cropState || !this._cropState.image) return;

    const { image, rotation } = this._cropState;
    const origW = image.naturalWidth || image.width;
    const origH = image.naturalHeight || image.height;
    const isSideways = rotation === 90 || rotation === 270;
    const effW = isSideways ? origH : origW;
    const effH = isSideways ? origW : origH;

    const wrapperRect = wrapper.getBoundingClientRect();
    const maxW = Math.max(260, Math.min(520, wrapperRect.width || 480));
    const maxH = 400;
    const scale = Math.min(maxW / effW, maxH / effH);
    const dispW = Math.max(180, Math.round(effW * scale));
    const dispH = Math.max(180, Math.round(effH * scale));

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(dispW * dpr);
    canvas.height = Math.round(dispH * dpr);
    canvas.style.width = `${dispW}px`;
    canvas.style.height = `${dispH}px`;

    this._cropState.dispW = dispW;
    this._cropState.dispH = dispH;
    this._cropState.dpr = dpr;

    this._drawCropCanvas();

    const getCanvasPos = (e) => {
      const rect = canvas.getBoundingClientRect();
      const clientX = e.clientX ?? (e.touches && e.touches[0]?.clientX) ?? 0;
      const clientY = e.clientY ?? (e.touches && e.touches[0]?.clientY) ?? 0;
      return {
        px: (clientX - rect.left) * (dispW / rect.width),
        py: (clientY - rect.top) * (dispH / rect.height),
      };
    };

    const getHitHandle = (pos) => {
      const c = this._cropState.crop;
      const bx = c.x * dispW;
      const by = c.y * dispH;
      const bw = c.width * dispW;
      const bh = c.height * dispH;
      const r = 24;

      if (Math.hypot(pos.px - bx, pos.py - by) <= r) return "nw";
      if (Math.hypot(pos.px - (bx + bw), pos.py - by) <= r) return "ne";
      if (Math.hypot(pos.px - (bx + bw), pos.py - (by + bh)) <= r) return "se";
      if (Math.hypot(pos.px - bx, pos.py - (by + bh)) <= r) return "sw";
      if (pos.px >= bx && pos.px <= bx + bw && pos.py >= by && pos.py <= by + bh) return "move";
      return null;
    };

    canvas.onpointerdown = (e) => {
      e.preventDefault();
      const pos = getCanvasPos(e);
      const handle = getHitHandle(pos);
      if (!handle) return;
      this._cropState.dragging = true;
      this._cropState.dragHandle = handle;
      this._cropState.dragStart = pos;
      this._cropState.initialCrop = { ...this._cropState.crop };
      try {
        canvas.setPointerCapture(e.pointerId);
      } catch (_) {}
    };

    canvas.onpointermove = (e) => {
      if (!this._cropState.dragging) {
        const pos = getCanvasPos(e);
        const handle = getHitHandle(pos);
        if (handle === "nw" || handle === "se") canvas.style.cursor = "nwse-resize";
        else if (handle === "ne" || handle === "sw") canvas.style.cursor = "nesw-resize";
        else if (handle === "move") canvas.style.cursor = "move";
        else canvas.style.cursor = "default";
        return;
      }

      e.preventDefault();
      const pos = getCanvasPos(e);
      const dx = (pos.px - this._cropState.dragStart.px) / dispW;
      const dy = (pos.py - this._cropState.dragStart.py) / dispH;
      const init = this._cropState.initialCrop;
      const minSize = 0.08;

      if (this._cropState.dragHandle === "move") {
        const nx = Math.max(0, Math.min(1 - init.width, init.x + dx));
        const ny = Math.max(0, Math.min(1 - init.height, init.y + dy));
        this._cropState.crop.x = nx;
        this._cropState.crop.y = ny;
      } else if (this._cropState.dragHandle === "nw") {
        const right = init.x + init.width;
        const bottom = init.y + init.height;
        const nx = Math.max(0, Math.min(right - minSize, init.x + dx));
        const ny = Math.max(0, Math.min(bottom - minSize, init.y + dy));
        this._cropState.crop.x = nx;
        this._cropState.crop.y = ny;
        this._cropState.crop.width = right - nx;
        this._cropState.crop.height = bottom - ny;
      } else if (this._cropState.dragHandle === "ne") {
        const left = init.x;
        const bottom = init.y + init.height;
        const nw = Math.max(minSize, Math.min(1 - left, init.width + dx));
        const ny = Math.max(0, Math.min(bottom - minSize, init.y + dy));
        this._cropState.crop.y = ny;
        this._cropState.crop.width = nw;
        this._cropState.crop.height = bottom - ny;
      } else if (this._cropState.dragHandle === "se") {
        const left = init.x;
        const top = init.y;
        this._cropState.crop.width = Math.max(minSize, Math.min(1 - left, init.width + dx));
        this._cropState.crop.height = Math.max(minSize, Math.min(1 - top, init.height + dy));
      } else if (this._cropState.dragHandle === "sw") {
        const top = init.y;
        const right = init.x + init.width;
        const nx = Math.max(0, Math.min(right - minSize, init.x + dx));
        this._cropState.crop.x = nx;
        this._cropState.crop.width = right - nx;
        this._cropState.crop.height = Math.max(minSize, Math.min(1 - top, init.height + dy));
      }
      this._drawCropCanvas();
    };

    const stopDrag = (e) => {
      if (this._cropState && this._cropState.dragging) {
        this._cropState.dragging = false;
        this._cropState.dragHandle = null;
        try {
          canvas.releasePointerCapture(e.pointerId);
        } catch (_) {}
      }
    };
    canvas.onpointerup = stopDrag;
    canvas.onpointercancel = stopDrag;
  }

  _drawCropCanvas() {
    const canvas = this.shadowRoot.querySelector("#crop-canvas");
    if (!canvas || !this._cropState || !this._cropState.image) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { image, rotation, crop, dispW, dispH, dpr } = this._cropState;
    if (!dispW || !dispH) return;

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, dispW, dispH);

    ctx.save();
    ctx.translate(dispW / 2, dispH / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    const origW = image.naturalWidth || image.width;
    const origH = image.naturalHeight || image.height;
    const isSideways = rotation === 90 || rotation === 270;
    const targetW = isSideways ? dispH : dispW;
    const targetH = isSideways ? dispW : dispH;
    ctx.drawImage(image, -targetW / 2, -targetH / 2, targetW, targetH);
    ctx.restore();

    const bx = Math.round(crop.x * dispW);
    const by = Math.round(crop.y * dispH);
    const bw = Math.round(crop.width * dispW);
    const bh = Math.round(crop.height * dispH);

    ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
    ctx.fillRect(0, 0, dispW, by);
    ctx.fillRect(0, by + bh, dispW, dispH - (by + bh));
    ctx.fillRect(0, by, bx, bh);
    ctx.fillRect(bx + bw, by, dispW - (bx + bw), bh);

    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.strokeRect(bx, by, bw, bh);

    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "#1a73e8";
    ctx.strokeRect(bx, by, bw, bh);
    ctx.setLineDash([]);

    const handleR = 7;
    const corners = [
      [bx, by],
      [bx + bw, by],
      [bx + bw, by + bh],
      [bx, by + bh],
    ];
    corners.forEach(([cx, cy]) => {
      ctx.beginPath();
      ctx.arc(cx, cy, handleR, 0, Math.PI * 2);
      ctx.fillStyle = "#1a73e8";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.stroke();
    });

    ctx.restore();
  }

  async _runBottleScan(payload) {
    if (!this._hass) return;
    this._scanState.busy = true;
    this._scanState.error = "";
    this._render();

    try {
      const res = await this._hass.callWS({
        type: "wine_inventory/scan_bottle",
        ...payload,
      });
      const ext = res.extracted || {};
      const existing = res.existing_wine || null;
      this._scanState.vivinoCandidates = res.vivino_candidates || [];
      this._scanState.vivinoStatus = res.vivino_status || "";
      this._scanState.selectedVivinoIndex = this._scanState.vivinoCandidates.length > 0 ? 0 : -1;
      this._scanState.existingWine = existing;

      this._scanState.form = {
        wine_id: existing ? existing.id : null,
        winery: ext.winery || "",
        name: ext.name || "",
        vintage: ext.vintage ?? "",
        wine_type: ext.wine_type || "red",
        varietal: ext.varietal || "",
        region: ext.region || "",
        country: ext.country || "",
        alcohol_pct: ext.alcohol_pct ?? "",
        bottle_size_ml: ext.bottle_size_ml || 750,
        vivino_rating: ext.vivino_rating ?? "",
        vivino_ratings_count: ext.vivino_ratings_count ?? null,
        vivino_url: ext.vivino_url || "",
        vivino_price_estimate: ext.vivino_price_estimate ?? "",
        rating_source: ext.rating_source || "",
        drink_from_year: ext.drink_from_year ?? (existing?.drink_from_year ?? ""),
        drink_until_year: ext.drink_until_year ?? (existing?.drink_until_year ?? ""),
        drink_window_note: ext.drink_window_note || existing?.drink_window_note || "",
        food_pairings: Array.isArray(ext.food_pairings)
          ? ext.food_pairings.join(", ")
          : ext.food_pairings || "",
        general_notes: existing?.general_notes || ext.general_notes || "",
        batch_notes: "",
        image_url: ext.image_url || "",
        quantity: 1,
        added_at: nowLocalIsoMinutes(),
        purchase_location: existing?.last_purchase_location || "",
        purchase_price: existing?.last_purchase_price ?? (ext.vivino_price_estimate ?? ""),
        storage_location: existing?.last_storage_location || "",
      };
    } catch (err) {
      const errMsg = err?.message || (typeof err === "string" ? err : "Bottle scan failed. You can still fill details manually.");
      this._scanState.error = errMsg;
      this.dispatchEvent(
        new CustomEvent("hass-notification", {
          detail: { message: `Lekkersappie: ${errMsg}` },
          bubbles: true,
          composed: true,
        })
      );
    } finally {
      this._scanState.busy = false;
      this._render();
    }
  }

  _applyVivinoCandidate(index) {
    this._scanState.selectedVivinoIndex = index;
    const f = this._scanState.form;
    if (index === -1) {
      f.vivino_rating = "";
      f.vivino_ratings_count = null;
      f.vivino_url = "";
      f.vivino_price_estimate = "";
      f.rating_source = "";
      this._render();
      return;
    }
    const cand = this._scanState.vivinoCandidates[index];
    if (!cand) return;
    f.vivino_rating = cand.vivino_rating ?? "";
    f.vivino_ratings_count = cand.vivino_ratings_count ?? null;
    f.vivino_url = cand.vivino_url || "";
    f.vivino_price_estimate = cand.vivino_price_estimate ?? "";
    f.rating_source = cand.rating_source || "vivino";
    if (cand.region && !f.region) f.region = cand.region;
    if (cand.country && !f.country) f.country = cand.country;
    this._render();
  }

  async _submitScanOrAddForm(event) {
    event.preventDefault();
    if (!this._hass) return;
    const f = this._scanState.form;
    const toIntOrNull = (v) => (v !== "" && v !== null && v !== undefined ? parseInt(v, 10) : null);
    const toFloatOrNull = (v) => (v !== "" && v !== null && v !== undefined ? parseFloat(v) : null);

    this._scanState.busy = true;
    this._render();
    try {
      await this._hass.callWS({
        type: "wine_inventory/add_wine",
        wine_id: f.wine_id,
        winery: f.winery,
        name: f.name,
        vintage: toIntOrNull(f.vintage),
        wine_type: f.wine_type,
        varietal: f.varietal,
        region: f.region,
        country: f.country,
        alcohol_pct: toFloatOrNull(f.alcohol_pct),
        bottle_size_ml: toIntOrNull(f.bottle_size_ml) || 750,
        vivino_rating: toFloatOrNull(f.vivino_rating),
        vivino_ratings_count: toIntOrNull(f.vivino_ratings_count),
        vivino_url: f.vivino_url,
        vivino_price_estimate: toFloatOrNull(f.vivino_price_estimate),
        rating_source: f.rating_source || "user",
        drink_from_year: toIntOrNull(f.drink_from_year),
        drink_until_year: toIntOrNull(f.drink_until_year),
        drink_window_note: f.drink_window_note,
        food_pairings: f.food_pairings,
        general_notes: f.general_notes,
        image_url: f.image_url || "",
        quantity: Math.max(1, toIntOrNull(f.quantity) || 1),
        added_at: f.added_at ? new Date(f.added_at).toISOString() : null,
        purchase_location: f.purchase_location,
        purchase_price: toFloatOrNull(f.purchase_price),
        storage_location: f.storage_location,
        batch_notes: f.batch_notes,
      });
      this._closeModal();
      await this._fetchInventory();
    } catch (err) {
      this._scanState.error = err?.message || "Failed to save wine.";
      this._scanState.busy = false;
      this._render();
    }
  }

  async _submitQuickAdd(event) {
    event.preventDefault();
    if (!this._hass || !this._quickAddForm) return;
    const qf = this._quickAddForm;
    await this._hass.callWS({
      type: "wine_inventory/adjust_quantity",
      wine_id: qf.wine_id,
      delta: Math.max(1, parseInt(qf.quantity, 10) || 1),
      added_at: qf.added_at ? new Date(qf.added_at).toISOString() : null,
      purchase_location: qf.purchase_location,
      purchase_price: qf.purchase_price !== "" ? parseFloat(qf.purchase_price) : null,
      storage_location: qf.storage_location,
      drink_window_note: qf.drink_window_note,
      notes: qf.notes,
    });
    this._closeModal();
    await this._fetchInventory();
  }

  async _submitConsume(event) {
    event.preventDefault();
    if (!this._hass || !this._consumeForm) return;
    const cf = this._consumeForm;
    await this._hass.callWS({
      type: "wine_inventory/adjust_quantity",
      wine_id: cf.wine_id,
      delta: -Math.abs(parseInt(cf.delta, 10) || 1),
      batch_id: cf.batch_id ? parseInt(cf.batch_id, 10) : null,
      personal_rating: cf.personal_rating !== "" ? parseFloat(cf.personal_rating) : null,
      notes: cf.notes,
    });
    this._closeModal();
    await this._fetchInventory();
  }

  async _submitDetailUpdate(event) {
    event.preventDefault();
    if (!this._hass || !this._detailForm) return;
    const df = this._detailForm;
    const toIntOrNull = (v) => (v !== "" && v !== null && v !== undefined ? parseInt(v, 10) : null);
    const toFloatOrNull = (v) => (v !== "" && v !== null && v !== undefined ? parseFloat(v) : null);

    await this._hass.callWS({
      type: "wine_inventory/update_wine",
      wine_id: df.wine_id,
      updates: {
        general_notes: df.general_notes,
        drink_from_year: toIntOrNull(df.drink_from_year),
        drink_until_year: toIntOrNull(df.drink_until_year),
        drink_window_note: df.drink_window_note,
        vivino_rating: toFloatOrNull(df.vivino_rating),
        vivino_url: df.vivino_url,
        personal_rating: toFloatOrNull(df.personal_rating),
      },
    });
    this._closeModal();
    await this._fetchInventory();
  }

  async _refreshAllVivino() {
    if (!this._hass) return;
    this._loading = true;
    this._render();
    try {
      await this._hass.callWS({ type: "wine_inventory/refresh_vivino" });
      await this._fetchInventory();
    } catch (err) {
      this._error = err?.message || "Vivino refresh failed.";
      this._loading = false;
      this._render();
    }
  }

  _renderWineCard(wine) {
    const statusMeta = DRINK_STATUS_META[wine.drink_status] || DRINK_STATUS_META.unknown;
    const typeLabel = WINE_TYPE_LABELS[wine.wine_type] || "Wine";
    const vintageLabel = wine.vintage ? String(wine.vintage) : "NV";
    const ratingVal = wine.vivino_rating ? Number(wine.vivino_rating).toFixed(1) : null;
    const ratingCount = wine.vivino_ratings_count
      ? `(${Number(wine.vivino_ratings_count).toLocaleString()})`
      : wine.rating_source === "gemini_estimate"
      ? "(est.)"
      : "";
    const drinkYears =
      wine.drink_from_year || wine.drink_until_year
        ? `${wine.drink_from_year || "Now"}–${wine.drink_until_year || "…"}`
        : statusMeta.label;

    return `
      <div class="wine-item" data-wine-id="${wine.id}">
        <div class="wine-item-top">
          <div class="wine-thumb-wrap">
            ${
              wine.image_url
                ? `<img class="wine-thumb preview-image-clickable" src="${escapeHtml(wine.image_url)}" alt="${escapeHtml(wine.name)}" data-action="preview-image" data-id="${wine.id}" title="Click to enlarge image" style="cursor: pointer;" />`
                : `<div class="wine-thumb-placeholder type-${escapeHtml(wine.wine_type)}">
                    <ha-icon icon="mdi:glass-wine"></ha-icon>
                  </div>`
            }
          </div>
          <div class="wine-info">
            <div class="wine-badges-row">
              <span class="type-pill type-${escapeHtml(wine.wine_type)}">${escapeHtml(typeLabel)}</span>
              <span class="vintage-pill">${escapeHtml(vintageLabel)}</span>
              <span class="drink-pill" style="border-color:${statusMeta.color}; color:${statusMeta.color};">
                ${escapeHtml(statusMeta.label)} (${escapeHtml(drinkYears)})
              </span>
            </div>
            <div class="wine-winery">${escapeHtml(wine.winery)}</div>
            <div class="wine-title">${escapeHtml(wine.name)}</div>
            <div class="wine-sub">
              ${escapeHtml([wine.varietal, wine.region, wine.country].filter(Boolean).join(" • ") || "—")}
            </div>
            <div class="wine-ratings-row">
              ${
                ratingVal
                  ? wine.vivino_url
                    ? `<a class="vivino-badge" href="${escapeHtml(wine.vivino_url)}" target="_blank" rel="noopener noreferrer" title="Open on Vivino (opens in new tab)">
                        ★ ${escapeHtml(ratingVal)} <span class="vivino-sub">Vivino ${escapeHtml(ratingCount)}</span>
                        <ha-icon icon="mdi:open-in-new" style="--mdc-icon-size: 12px; margin-left: 2px;"></ha-icon>
                      </a>`
                    : `<span class="vivino-badge">★ ${escapeHtml(ratingVal)} <span class="vivino-sub">Vivino ${escapeHtml(ratingCount)}</span></span>`
                  : `<span class="vivino-badge muted">No Vivino rating</span>`
              }
              ${
                wine.personal_rating
                  ? `<span class="personal-badge">My Rating: ★ ${Number(wine.personal_rating).toFixed(1)}</span>`
                  : ""
              }
            </div>
          </div>
        </div>

        <div class="wine-meta-grid">
          <div>
            <ha-icon icon="mdi:storefront-outline"></ha-icon>
            <span><strong>Bought:</strong> ${escapeHtml(wine.last_purchase_location || "—")}</span>
          </div>
          <div>
            <ha-icon icon="mdi:fridge-outline"></ha-icon>
            <span><strong>Location:</strong> ${escapeHtml((wine.active_storage_locations || []).join(", ") || wine.last_storage_location || "—")}</span>
          </div>
          <div>
            <ha-icon icon="mdi:calendar-clock"></ha-icon>
            <span><strong>Added:</strong> ${escapeHtml(formatDisplayDate(wine.latest_added_at))}</span>
          </div>
          ${
            wine.drink_window_note
              ? `<div>
                  <ha-icon icon="mdi:glass-wine"></ha-icon>
                  <span><strong>Drink Note:</strong> ${escapeHtml(wine.drink_window_note)}</span>
                </div>`
              : ""
          }
        </div>

        ${
          wine.general_notes
            ? `<div class="wine-notes-preview">
                <strong>Notes Overview:</strong> ${escapeHtml(wine.general_notes)}
              </div>`
            : ""
        }

        <div class="wine-actions-bar">
          <div class="stepper-group">
            <button class="ha-btn icon-btn minus-btn" data-action="consume" data-id="${wine.id}" title="Open / Consume Bottle (-1)">
              <ha-icon icon="mdi:minus"></ha-icon>
            </button>
            <span class="qty-badge">${Number(wine.quantity || 0)} ${Number(wine.quantity) === 1 ? "bottle" : "bottles"}</span>
            <button class="ha-btn icon-btn plus-btn" data-action="quick-add" data-id="${wine.id}" title="Add Bottle(s) (+1 with timestamp & notes)">
              <ha-icon icon="mdi:plus"></ha-icon>
            </button>
          </div>
          <button class="ha-btn secondary-btn" data-action="detail" data-id="${wine.id}">
            <ha-icon icon="mdi:notebook-edit-outline"></ha-icon>
            <span>Batches &amp; Notes (${(wine.timeline || []).length})</span>
          </button>
        </div>
      </div>
    `;
  }

  _renderWineListView(wines) {
    return `
      <div class="wine-list-table-container">
        <table class="wine-list-table">
          <thead>
            <tr>
              <th style="width: 44px;">Label</th>
              <th>Wine &amp; Winery</th>
              <th>Vintage</th>
              <th>Type</th>
              <th>Drink Window</th>
              <th>Rating</th>
              <th style="text-align: center;">Stock</th>
              <th style="text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${wines
              .map((wine) => {
                const statusMeta = DRINK_STATUS_META[wine.drink_status] || DRINK_STATUS_META.unknown;
                const typeLabel = WINE_TYPE_LABELS[wine.wine_type] || "Wine";
                const vintageLabel = wine.vintage ? String(wine.vintage) : "NV";
                const ratingVal = wine.vivino_rating ? Number(wine.vivino_rating).toFixed(1) : null;
                const drinkYears =
                  wine.drink_from_year || wine.drink_until_year
                    ? `${wine.drink_from_year || "Now"}–${wine.drink_until_year || "…"}`
                    : statusMeta.label;
                const subMeta = [wine.varietal, wine.region, wine.country].filter(Boolean).join(" • ") || "—";

                return `
                  <tr data-wine-id="${wine.id}">
                    <td>
                      ${
                        wine.image_url
                          ? `<img class="wine-list-thumb preview-image-clickable" src="${escapeHtml(wine.image_url)}" alt="${escapeHtml(wine.name)}" data-action="preview-image" data-id="${wine.id}" title="Click to enlarge image" style="cursor: pointer;" />`
                          : `<div class="wine-list-thumb-placeholder type-${escapeHtml(wine.wine_type)}">
                              <ha-icon icon="mdi:glass-wine" style="--mdc-icon-size: 20px;"></ha-icon>
                            </div>`
                      }
                    </td>
                    <td>
                      <div class="wine-list-title-wrap">
                        <strong title="${escapeHtml(wine.name)}">${escapeHtml(wine.name)}</strong>
                        <span style="font-weight: 500;">${escapeHtml(wine.winery)}</span>
                        <span>${escapeHtml(subMeta)}</span>
                      </div>
                    </td>
                    <td>
                      <span class="vintage-pill">${escapeHtml(vintageLabel)}</span>
                    </td>
                    <td>
                      <span class="type-pill type-${escapeHtml(wine.wine_type)}">${escapeHtml(typeLabel)}</span>
                    </td>
                    <td>
                      <span class="drink-pill" style="border-color:${statusMeta.color}; color:${statusMeta.color}; font-size: 11px;">
                        ${escapeHtml(drinkYears)}
                      </span>
                    </td>
                    <td>
                      ${
                        ratingVal
                          ? wine.vivino_url
                            ? `<a class="vivino-badge" href="${escapeHtml(wine.vivino_url)}" target="_blank" rel="noopener noreferrer" title="Open on Vivino (opens in new tab)" style="font-size: 11px; padding: 2px 6px; text-decoration: none;">
                                ★ ${escapeHtml(ratingVal)}
                                <ha-icon icon="mdi:open-in-new" style="--mdc-icon-size: 11px; margin-left: 2px;"></ha-icon>
                              </a>`
                            : `<span class="vivino-badge" style="font-size: 11px; padding: 2px 6px;">★ ${escapeHtml(ratingVal)}</span>`
                          : `<span style="font-size: 11px; color: var(--secondary-text-color);">—</span>`
                      }
                    </td>
                    <td style="text-align: center;">
                      <div class="stepper-group" style="justify-content: center;">
                        <button class="ha-btn icon-btn minus-btn" data-action="consume" data-id="${wine.id}" title="Open / Consume Bottle (-1)" style="padding: 2px 6px; min-width: 26px; min-height: 26px;">
                          <ha-icon icon="mdi:minus" style="--mdc-icon-size: 14px;"></ha-icon>
                        </button>
                        <strong class="qty-badge" style="min-width: 32px; font-size: 13px;">${Number(wine.quantity || 0)}</strong>
                        <button class="ha-btn icon-btn plus-btn" data-action="quick-add" data-id="${wine.id}" title="Add Bottle (+1)" style="padding: 2px 6px; min-width: 26px; min-height: 26px;">
                          <ha-icon icon="mdi:plus" style="--mdc-icon-size: 14px;"></ha-icon>
                        </button>
                      </div>
                    </td>
                    <td style="text-align: right;">
                      <div class="wine-list-actions" style="justify-content: flex-end;">
                        <button class="ha-btn secondary-btn" data-action="detail" data-id="${wine.id}" style="padding: 4px 10px; font-size: 12px;">
                          <ha-icon icon="mdi:notebook-edit-outline" style="--mdc-icon-size: 16px;"></ha-icon>
                          <span>Details</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                `;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  async _loadBackups() {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({ type: "wine_inventory/list_backups" });
      this._backupState.backups = res.backups || [];
      this._render();
    } catch (err) {
      console.warn("Failed to list backups:", err);
    }
  }

  async _handleCreateBackup() {
    if (!this._hass) return;
    this._backupState.busy = true;
    this._backupState.error = "";
    this._backupState.success = "";
    this._render();
    try {
      const res = await this._hass.callWS({ type: "wine_inventory/create_backup" });
      this._backupState.busy = false;
      this._backupState.success = `Backup created successfully (${res.wine_count} wines, ${(res.size_bytes / 1024).toFixed(1)} KB): ${res.backup_filename}`;
      const a = document.createElement("a");
      if (res.archive_base64) {
        a.href = `data:application/zip;base64,${res.archive_base64}`;
      } else if (res.download_url) {
        a.href = res.download_url;
      }
      a.download = res.backup_filename || "wine_inventory_backup.zip";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      await this._loadBackups();
    } catch (err) {
      this._backupState.busy = false;
      this._backupState.error = err?.message || "Failed to create backup.";
      this._render();
    }
  }

  async _handleRestoreFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";
    if (
      !confirm(
        `Are you sure you want to restore from "${file.name}"? This will overwrite your current cellar database and restore images.`
      )
    ) {
      return;
    }
    this._backupState.busy = true;
    this._backupState.error = "";
    this._backupState.success = "";
    this._render();

    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const dataUrl = String(reader.result || "");
        const base64 = dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
        const res = await this._hass.callWS({
          type: "wine_inventory/restore_backup",
          archive_base64: base64,
        });
        this._backupState.busy = false;
        this._backupState.success = `Database restored successfully (${res.wines_restored} wines, ${res.images_restored} images)!`;
        await this._fetchInventory();
        await this._loadBackups();
      } catch (err) {
        this._backupState.busy = false;
        this._backupState.error = err?.message || "Failed to restore backup.";
        this._render();
      }
    };
    reader.onerror = () => {
      this._backupState.busy = false;
      this._backupState.error = "Failed to read selected backup file.";
      this._render();
    };
    reader.readAsDataURL(file);
  }

  async _handleImportFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";
    this._backupState.busy = true;
    this._backupState.error = "";
    this._backupState.success = "";
    this._render();

    const fileNameLower = file.name.toLowerCase();
    const isZip = fileNameLower.endsWith(".zip");
    const isCsv = fileNameLower.endsWith(".csv");
    const formatType = isZip ? "zip" : isCsv ? "csv" : "json";

    const reader = new FileReader();
    if (isZip) {
      reader.onload = async () => {
        try {
          const dataUrl = String(reader.result || "");
          const base64 = dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
          const res = await this._hass.callWS({
            type: "wine_inventory/import_wines",
            payload: base64,
            format_type: "zip",
          });
          this._backupState.busy = false;
          this._backupState.success = `Imported ${res.imported_wines} wines (${res.bottles_added} bottles added)!`;
          await this._fetchInventory();
        } catch (err) {
          this._backupState.busy = false;
          this._backupState.error = err?.message || "Import failed.";
          this._render();
        }
      };
      reader.readAsDataURL(file);
    } else {
      reader.onload = async () => {
        try {
          const text = String(reader.result || "");
          const payload = formatType === "json" ? JSON.parse(text) : text;
          const res = await this._hass.callWS({
            type: "wine_inventory/import_wines",
            payload: payload,
            format_type: formatType,
          });
          this._backupState.busy = false;
          this._backupState.success = `Imported ${res.imported_wines} wines (${res.bottles_added} bottles added)!`;
          await this._fetchInventory();
        } catch (err) {
          this._backupState.busy = false;
          this._backupState.error = err?.message || "Import failed.";
          this._render();
        }
      };
      reader.readAsText(file);
    }
  }

  async _handleRestoreServerBackup(filename) {
    if (!this._hass || !filename) return;
    if (
      !confirm(
        `Are you sure you want to restore from "${filename}"? This will overwrite your current cellar database and restore images.`
      )
    ) {
      return;
    }
    this._backupState.busy = true;
    this._backupState.error = "";
    this._backupState.success = "";
    this._render();
    try {
      const res = await this._hass.callWS({
        type: "wine_inventory/restore_backup",
        backup_filename: filename,
      });
      this._backupState.busy = false;
      this._backupState.success = `Database restored successfully (${res.wines_restored} wines, ${res.images_restored} images)!`;
      await this._fetchInventory();
      await this._loadBackups();
    } catch (err) {
      this._backupState.busy = false;
      this._backupState.error = err?.message || "Failed to restore backup.";
      this._render();
    }
  }

  _renderBackupModal() {
    const bs = this._backupState;
    return `
      <div class="modal-backdrop" id="backup-modal-backdrop">
        <div class="modal-surface" style="max-width: 620px;">
          <div class="modal-header">
            <h2>
              <ha-icon icon="mdi:database-cog" style="color: var(--primary-color, #03a9f4);"></ha-icon>
              <span>Cellar Database Backup, Restore &amp; Import</span>
            </h2>
            <button class="ha-btn icon-btn" id="close-backup-btn" title="Close">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>

          <div class="modal-body">
            ${
              bs.error
                ? `<div class="card-alert-banner" role="alert" style="margin-bottom: 14px;">
                    <div class="card-alert-content">
                      <ha-icon icon="mdi:alert-circle" style="color: var(--error-color, #c62828);"></ha-icon>
                      <span>${escapeHtml(bs.error)}</span>
                    </div>
                    <button class="ha-btn icon-btn" id="dismiss-backup-error-btn">
                      <ha-icon icon="mdi:close"></ha-icon>
                    </button>
                  </div>`
                : ""
            }

            ${
              bs.success
                ? `<div class="scan-status-banner" style="background: rgba(46, 125, 50, 0.15); color: #2e7d32; padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <ha-icon icon="mdi:check-circle" style="color: #2e7d32;"></ha-icon>
                      <span>${escapeHtml(bs.success)}</span>
                    </div>
                    <button class="ha-btn icon-btn" id="dismiss-backup-success-btn">
                      <ha-icon icon="mdi:close"></ha-icon>
                    </button>
                  </div>`
                : ""
            }

            <div class="backup-action-card" style="border: 1px solid var(--divider-color, #e0e0e0); border-radius: 10px; padding: 14px; margin-bottom: 12px; background: var(--secondary-background-color, rgba(127,127,127,0.04));">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
                <div style="max-width: 360px;">
                  <strong style="font-size: 14px; display: flex; align-items: center; gap: 6px;">
                    <ha-icon icon="mdi:folder-zip-outline" style="color: var(--primary-color);"></ha-icon>
                    Full Cellar Backup (.zip)
                  </strong>
                  <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
                    Creates a complete archive containing <code>wine_inventory.db</code>, all bottle photos (<code>covers/</code>), and metadata.
                  </div>
                </div>
                <button class="ha-btn primary-btn" id="btn-create-backup" ${bs.busy ? "disabled" : ""}>
                  <ha-icon icon="mdi:download"></ha-icon>
                  <span>${bs.busy ? "Creating…" : "Download Backup (.zip)"}</span>
                </button>
              </div>
            </div>

            <div class="backup-action-card" style="border: 1px solid var(--divider-color, #e0e0e0); border-radius: 10px; padding: 14px; margin-bottom: 12px; background: var(--secondary-background-color, rgba(127,127,127,0.04));">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
                <div style="max-width: 360px;">
                  <strong style="font-size: 14px; display: flex; align-items: center; gap: 6px;">
                    <ha-icon icon="mdi:database-refresh" style="color: var(--warning-color, #ef6c00);"></ha-icon>
                    Restore Database from Backup (.zip)
                  </strong>
                  <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
                    Restores your database and cover images. <em>Warning: Replaces active cellar data.</em>
                  </div>
                </div>
                <div>
                  <input type="file" id="restore-file-input" accept=".zip" style="display: none;" />
                  <button class="ha-btn secondary-btn" id="btn-select-restore" ${bs.busy ? "disabled" : ""}>
                    <ha-icon icon="mdi:upload"></ha-icon>
                    <span>Restore .zip Backup</span>
                  </button>
                </div>
              </div>
            </div>

            <div class="backup-action-card" style="border: 1px solid var(--divider-color, #e0e0e0); border-radius: 10px; padding: 14px; margin-bottom: 16px; background: var(--secondary-background-color, rgba(127,127,127,0.04));">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
                <div style="max-width: 360px;">
                  <strong style="font-size: 14px; display: flex; align-items: center; gap: 6px;">
                    <ha-icon icon="mdi:file-import-outline" style="color: #2e7d32;"></ha-icon>
                    Import Wines (JSON / CSV / ZIP)
                  </strong>
                  <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
                    Batch imports bottles from JSON, CSV, or another wine backup file without wiping existing wines.
                  </div>
                </div>
                <div>
                  <input type="file" id="import-file-input" accept=".json,.csv,.zip" style="display: none;" />
                  <button class="ha-btn secondary-btn" id="btn-select-import" ${bs.busy ? "disabled" : ""}>
                    <ha-icon icon="mdi:file-upload-outline"></ha-icon>
                    <span>Import File</span>
                  </button>
                </div>
              </div>
            </div>

            ${
              (bs.backups || []).length > 0
                ? `
                <div class="section-divider" style="margin-bottom: 10px;">Available On-Disk Backups (${bs.backups.length})</div>
                <div style="display: flex; flex-direction: column; gap: 8px; max-height: 180px; overflow-y: auto;">
                  ${bs.backups
                    .map(
                      (b) => `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px; font-size: 12px;">
                      <div>
                        <strong>${escapeHtml(b.filename)}</strong>
                        <div style="color: var(--secondary-text-color); font-size: 11px;">
                          ${(b.size_bytes / 1024).toFixed(1)} KB • ${escapeHtml(formatDisplayDate(b.created_at))}
                        </div>
                      </div>
                      <div style="display: flex; gap: 6px;">
                        ${
                          b.download_url
                            ? `<a class="ha-btn secondary-btn" href="${escapeHtml(b.download_url)}" download="${escapeHtml(b.filename)}" style="padding: 4px 8px; font-size: 11px; text-decoration: none;">Download</a>`
                            : ""
                        }
                        <button class="ha-btn secondary-btn" data-restore-server-filename="${escapeHtml(b.filename)}" style="padding: 4px 8px; font-size: 11px;">Restore</button>
                      </div>
                    </div>
                  `
                    )
                    .join("")}
                </div>
              `
                : ""
            }
          </div>
        </div>
      </div>
    `;
  }

  _renderCropRotateModal() {
    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal-surface crop-modal-surface">
          <div class="modal-header">
            <h2>
              <ha-icon icon="mdi:crop-rotate"></ha-icon>
              <span>Crop &amp; Rotate Bottle Label</span>
            </h2>
            <button class="ha-btn icon-btn" id="close-crop-btn" title="Cancel">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>

          <div class="modal-body crop-modal-body">
            <div class="crop-instructions">
              <ha-icon icon="mdi:information-outline"></ha-icon>
              <span>Rotate so the wine label is upright, then drag the box &amp; corner handles to frame only the label for optimal recognition.</span>
            </div>

            <div class="canvas-wrapper" id="canvas-wrapper">
              <canvas id="crop-canvas"></canvas>
            </div>

            <div class="crop-controls-row">
              <button type="button" class="ha-btn secondary-btn" id="btn-rotate-left">
                <ha-icon icon="mdi:rotate-left"></ha-icon>
                <span>Rotate Left (90°)</span>
              </button>
              <button type="button" class="ha-btn secondary-btn" id="btn-rotate-right">
                <ha-icon icon="mdi:rotate-right"></ha-icon>
                <span>Rotate Right (90°)</span>
              </button>
              <button type="button" class="ha-btn secondary-btn" id="btn-reset-crop">
                <ha-icon icon="mdi:refresh"></ha-icon>
                <span>Reset Frame</span>
              </button>
            </div>
          </div>

          <div class="modal-actions full-width crop-footer">
            <button type="button" class="ha-btn secondary-btn" id="btn-cancel-crop">Cancel</button>
            <button type="button" class="ha-btn primary-btn" id="btn-confirm-crop">
              <ha-icon icon="mdi:check"></ha-icon>
              <span>Confirm &amp; Scan Label</span>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _renderScanModal() {
    const s = this._scanState;
    const f = s.form;
    const knownStores = this._statistics.known_purchase_locations || [];
    const knownLocations = this._statistics.known_storage_locations || [];

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal-surface">
          <div class="modal-header">
            <h2>
              <ha-icon icon="${s.manualOnly ? "mdi:plus-circle-outline" : "mdi:camera-iris"}"></ha-icon>
              ${s.manualOnly ? "Add Wine to Inventory" : "Scan Wine Bottle with Gemini Flash-Lite"}
            </h2>
            <button class="ha-btn icon-btn" id="close-modal-btn"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>

          <div class="modal-body">
            ${
              !s.manualOnly
                ? `<div class="scan-capture-box">
                    <div class="scan-buttons-row">
                      <label class="ha-btn primary-btn file-label">
                        <ha-icon icon="mdi:camera"></ha-icon>
                        <span>Take Photo / Upload Label</span>
                        <input type="file" id="bottle-file-input" accept="image/*" capture="environment" hidden />
                      </label>
                      ${
                        this._cropState?.image
                          ? `<button type="button" class="ha-btn secondary-btn" id="reopen-crop-btn">
                              <ha-icon icon="mdi:crop-rotate"></ha-icon>
                              <span>Adjust Crop &amp; Rotate</span>
                            </button>`
                          : ""
                      }
                    </div>
                    ${
                      s.busy
                        ? `<div class="scan-status-banner">
                            <ha-icon icon="mdi:loading"></ha-icon>
                            <span>Analyzing bottle label with Gemini Flash-Lite &amp; looking up Vivino rating…</span>
                          </div>`
                        : ""
                    }
                    ${
                      s.error
                        ? `<div class="scan-error-card" role="alert">
                            <div class="scan-error-header">
                              <div class="scan-error-title-wrap">
                                <ha-icon icon="mdi:alert-circle" style="color: var(--error-color, #c62828);"></ha-icon>
                                <strong style="color: var(--error-color, #c62828);">Scan Recognition Error</strong>
                              </div>
                              <button type="button" class="ha-btn icon-btn" id="dismiss-scan-error-btn" title="Dismiss Error">
                                <ha-icon icon="mdi:close"></ha-icon>
                              </button>
                            </div>
                            <div class="scan-error-body">
                              <p class="scan-error-message">${escapeHtml(s.error)}</p>
                              <div class="scan-error-hint">
                                <strong>Troubleshooting tips:</strong>
                                <ul>
                                  <li>Check that your Google Gemini API key is valid in Lekkersappie integration options.</li>
                                  <li>Click <em>Adjust Crop &amp; Rotate</em> to orient the label upright and frame only the printed front label.</li>
                                  <li>Or type the winery, wine name, and vintage manually into the fields below.</li>
                                </ul>
                              </div>
                            </div>
                            <div class="scan-error-actions">
                              ${
                                this._cropState?.image
                                  ? `<button type="button" class="ha-btn primary-btn" id="retry-crop-btn">
                                      <ha-icon icon="mdi:crop-rotate"></ha-icon>
                                      <span>Adjust Crop &amp; Retry</span>
                                    </button>`
                                  : ""
                              }
                              <button type="button" class="ha-btn secondary-btn" id="clear-scan-error-btn">Dismiss</button>
                            </div>
                          </div>`
                        : ""
                    }
                    ${
                      s.existingWine
                        ? `<div class="scan-existing-banner">
                            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
                            <div>
                              <strong>Already in your cellar!</strong> Currently <strong>${s.existingWine.quantity}</strong> bottle(s) in stock
                              (Last bought at: <em>${escapeHtml(s.existingWine.last_purchase_location || "—")}</em>,
                              Location: <em>${escapeHtml(s.existingWine.last_storage_location || "—")}</em>).
                              Saving will increment the bottle count and log this new addition batch.
                            </div>
                          </div>`
                        : ""
                    }
                    ${
                      s.vivinoCandidates && s.vivinoCandidates.length > 0
                        ? `<div class="form-field full-width">
                            <label>Vivino Match Selection (select candidate or disconnect)</label>
                            <select id="vivino-candidate-select" class="ha-input">
                              <option value="-1" ${s.selectedVivinoIndex === -1 ? "selected" : ""}>
                                🚫 Do not link to Vivino (Leave unlinked)
                              </option>
                              ${s.vivinoCandidates
                                .map(
                                  (c, idx) =>
                                    `<option value="${idx}" ${s.selectedVivinoIndex === idx ? "selected" : ""}>
                                      ★ ${c.vivino_rating ?? "?"} – ${escapeHtml(c.winery)}: ${escapeHtml(c.name)} (${c.vintage || "NV"}) [${c.vivino_ratings_count ? c.vivino_ratings_count.toLocaleString() : 0} ratings]
                                    </option>`
                                )
                                .join("")}
                            </select>
                          </div>`
                        : s.form.vivino_rating || s.form.vivino_url
                        ? `<div class="form-field full-width">
                            <label>Vivino Match</label>
                            <div style="display:flex; justify-content:space-between; align-items:center; padding: 6px 12px; background:var(--secondary-background-color, rgba(127,127,127,0.08)); border-radius:8px;">
                              <span style="font-size: 13px;">★ ${escapeHtml(s.form.vivino_rating)} (${escapeHtml(s.form.rating_source || "Vivino")})</span>
                              <button type="button" class="ha-btn secondary-btn" id="btn-disconnect-vivino" style="padding: 4px 8px; font-size: 12px;">
                                <ha-icon icon="mdi:link-variant-off"></ha-icon>
                                <span>Do Not Link</span>
                              </button>
                            </div>
                          </div>`
                        : ""
                    }
                  </div>`
                : ""
            }

            <form id="scan-add-form" class="form-grid">
              <div class="form-field">
                <label>Winery / Producer *</label>
                <input class="ha-input" name="winery" required value="${escapeHtml(f.winery)}" placeholder="e.g. Château Margaux" />
              </div>
              <div class="form-field">
                <label>Wine Name / Cuvée *</label>
                <input class="ha-input" name="name" required value="${escapeHtml(f.name)}" placeholder="e.g. Pavillon Rouge" />
              </div>
              <div class="form-field">
                <label>Vintage Year (blank = NV)</label>
                <input class="ha-input" type="number" name="vintage" min="1900" max="2100" value="${escapeHtml(f.vintage)}" />
              </div>
              <div class="form-field">
                <label>Wine Type</label>
                <select class="ha-input" name="wine_type">
                  ${Object.entries(WINE_TYPE_LABELS)
                    .map(
                      ([k, lbl]) =>
                        `<option value="${k}" ${f.wine_type === k ? "selected" : ""}>${lbl}</option>`
                    )
                    .join("")}
                </select>
              </div>
              <div class="form-field">
                <label>Varietal / Grapes</label>
                <input class="ha-input" name="varietal" value="${escapeHtml(f.varietal)}" placeholder="e.g. Cabernet Sauvignon, Merlot" />
              </div>
              <div class="form-field">
                <label>Region &amp; Country</label>
                <div class="split-2">
                  <input class="ha-input" name="region" value="${escapeHtml(f.region)}" placeholder="Region" />
                  <input class="ha-input" name="country" value="${escapeHtml(f.country)}" placeholder="Country" />
                </div>
              </div>
              <div class="form-field">
                <label>Vivino Rating (1.0–5.0)</label>
                <input class="ha-input" type="number" step="0.1" min="1" max="5" name="vivino_rating" value="${escapeHtml(f.vivino_rating)}" />
              </div>
              <div class="form-field">
                <label>Vivino URL</label>
                <input class="ha-input" name="vivino_url" value="${escapeHtml(f.vivino_url)}" placeholder="https://www.vivino.com/..." />
              </div>

              <div class="section-divider full-width">Addition Metadata, Drinking Window &amp; Notes</div>

              <div class="form-field">
                <label>Quantity Added *</label>
                <input class="ha-input" type="number" name="quantity" min="1" max="120" required value="${escapeHtml(f.quantity)}" />
              </div>
              <div class="form-field">
                <label>Date / Time Added *</label>
                <input class="ha-input" type="datetime-local" name="added_at" required value="${escapeHtml(f.added_at)}" />
              </div>
              <div class="form-field">
                <label>Where Was It Bought?</label>
                <input class="ha-input" name="purchase_location" list="known-stores-list" value="${escapeHtml(f.purchase_location)}" placeholder="Store, winery, website, or gift" />
                <datalist id="known-stores-list">
                  ${knownStores.map((st) => `<option value="${escapeHtml(st)}"></option>`).join("")}
                </datalist>
              </div>
              <div class="form-field">
                <label>Purchase Price (${escapeHtml(this._currency)}) &amp; Storage Slot</label>
                <div class="split-2">
                  <input class="ha-input" type="number" step="0.01" name="purchase_price" value="${escapeHtml(f.purchase_price)}" placeholder="Price" />
                  <input class="ha-input" name="storage_location" list="known-locations-list" value="${escapeHtml(f.storage_location)}" placeholder="Fridge / Rack / Row" />
                </div>
                <datalist id="known-locations-list">
                  ${knownLocations.map((loc) => `<option value="${escapeHtml(loc)}"></option>`).join("")}
                </datalist>
              </div>

              <div class="form-field">
                <label>When to Drink (From Year – Until Year)</label>
                <div class="split-2">
                  <input class="ha-input" type="number" name="drink_from_year" min="1950" max="2100" value="${escapeHtml(f.drink_from_year)}" placeholder="From (e.g. 2025)" />
                  <input class="ha-input" type="number" name="drink_until_year" min="1950" max="2100" value="${escapeHtml(f.drink_until_year)}" placeholder="Until (e.g. 2032)" />
                </div>
              </div>
              <div class="form-field">
                <label>When to Drink Guidance / Occasion</label>
                <input class="ha-input" name="drink_window_note" value="${escapeHtml(f.drink_window_note)}" placeholder="e.g. Decant 2h, drink with steak" />
              </div>

              <div class="form-field full-width">
                <label>Free-Form Notes Overview (Master Wine Overview)</label>
                <textarea class="ha-textarea" name="general_notes" rows="2" placeholder="Overall wine summary, aromas, pairings, or cellar notes...">${escapeHtml(f.general_notes)}</textarea>
              </div>
              <div class="form-field full-width">
                <label>Batch / Addition Note (Specific to this bottle purchase)</label>
                <textarea class="ha-textarea" name="batch_notes" rows="2" placeholder="Optional note for this specific purchase batch...">${escapeHtml(f.batch_notes)}</textarea>
              </div>

              <div class="modal-actions full-width">
                <button type="button" class="ha-btn secondary-btn" id="cancel-modal-btn">Cancel</button>
                <button type="submit" class="ha-btn primary-btn" ${s.busy ? "disabled" : ""}>
                  <ha-icon icon="mdi:check"></ha-icon>
                  <span>${s.existingWine ? "Add Bottle Batch (+)" : "Save Wine to Cellar"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    `;
  }

  _renderQuickAddModal() {
    const w = this._modalWine;
    const qf = this._quickAddForm;
    if (!w || !qf) return "";
    const knownStores = this._statistics.known_purchase_locations || [];
    const knownLocations = this._statistics.known_storage_locations || [];

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal-surface compact">
          <div class="modal-header">
            <h2><ha-icon icon="mdi:plus-circle"></ha-icon> Add Bottle(s): ${escapeHtml(w.winery)} – ${escapeHtml(w.name)}</h2>
            <button class="ha-btn icon-btn" id="close-modal-btn"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>
          <div class="modal-body">
            <form id="quick-add-form" class="form-grid">
              <div class="form-field">
                <label>Bottles to Add (+)</label>
                <input class="ha-input" type="number" name="quantity" min="1" max="120" required value="${escapeHtml(qf.quantity)}" />
              </div>
              <div class="form-field">
                <label>Date / Time Added</label>
                <input class="ha-input" type="datetime-local" name="added_at" required value="${escapeHtml(qf.added_at)}" />
              </div>
              <div class="form-field">
                <label>Where Was It Bought?</label>
                <input class="ha-input" name="purchase_location" list="qa-stores" value="${escapeHtml(qf.purchase_location)}" placeholder="Store or winery" />
                <datalist id="qa-stores">
                  ${knownStores.map((st) => `<option value="${escapeHtml(st)}"></option>`).join("")}
                </datalist>
              </div>
              <div class="form-field">
                <label>Storage Location &amp; Price</label>
                <div class="split-2">
                  <input class="ha-input" name="storage_location" list="qa-locations" value="${escapeHtml(qf.storage_location)}" placeholder="Fridge / Rack" />
                  <input class="ha-input" type="number" step="0.01" name="purchase_price" value="${escapeHtml(qf.purchase_price)}" placeholder="Price" />
                </div>
                <datalist id="qa-locations">
                  ${knownLocations.map((loc) => `<option value="${escapeHtml(loc)}"></option>`).join("")}
                </datalist>
              </div>
              <div class="form-field full-width">
                <label>When to Drink Guidance</label>
                <input class="ha-input" name="drink_window_note" value="${escapeHtml(qf.drink_window_note)}" placeholder="e.g. Ready autumn 2026" />
              </div>
              <div class="form-field full-width">
                <label>Addition Note (Optional)</label>
                <textarea class="ha-textarea" name="notes" rows="2" placeholder="Where/why you bought it, occasion, etc.">${escapeHtml(qf.notes)}</textarea>
              </div>
              <div class="modal-actions full-width">
                <button type="button" class="ha-btn secondary-btn" id="cancel-modal-btn">Cancel</button>
                <button type="submit" class="ha-btn primary-btn">
                  <ha-icon icon="mdi:plus"></ha-icon>
                  <span>Save Addition</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    `;
  }

  _renderConsumeModal() {
    const w = this._modalWine;
    const cf = this._consumeForm;
    if (!w || !cf) return "";
    const activeBatches = (w.batches || []).filter((b) => Number(b.quantity_remaining) > 0);

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal-surface compact">
          <div class="modal-header">
            <h2><ha-icon icon="mdi:glass-wine"></ha-icon> Open / Drink Bottle: ${escapeHtml(w.winery)} – ${escapeHtml(w.name)}</h2>
            <button class="ha-btn icon-btn" id="close-modal-btn"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>
          <div class="modal-body">
            <form id="consume-form" class="form-grid">
              <div class="form-field">
                <label>Bottles Opened</label>
                <input class="ha-input" type="number" name="delta" min="1" max="${Math.max(1, w.quantity)}" required value="1" />
              </div>
              <div class="form-field">
                <label>Your Personal Rating (1.0–5.0)</label>
                <input class="ha-input" type="number" step="0.5" min="1" max="5" name="personal_rating" value="${escapeHtml(cf.personal_rating)}" placeholder="e.g. 4.5" />
              </div>
              ${
                activeBatches.length > 0
                  ? `<div class="form-field full-width">
                      <label>Pull from Batch / Storage Location</label>
                      <select class="ha-input" name="batch_id">
                        ${activeBatches
                          .map(
                            (b) =>
                              `<option value="${b.id}" ${cf.batch_id === b.id ? "selected" : ""}>
                                ${escapeHtml(b.storage_location || "Unspecified Slot")} • Bought at ${escapeHtml(
                                b.purchase_location || "—"
                              )} (${formatDisplayDate(b.added_at)}) — ${b.quantity_remaining} left
                              </option>`
                          )
                          .join("")}
                      </select>
                    </div>`
                  : ""
              }
              <div class="form-field full-width">
                <label>Tasting Notes (Optional)</label>
                <textarea class="ha-textarea" name="notes" rows="3" placeholder="How did it taste? What did you pair it with? Would you buy again?">${escapeHtml(cf.notes)}</textarea>
              </div>
              <div class="modal-actions full-width">
                <button type="button" class="ha-btn secondary-btn" id="cancel-modal-btn">Cancel</button>
                <button type="submit" class="ha-btn primary-btn">
                  <ha-icon icon="mdi:check"></ha-icon>
                  <span>Confirm &amp; Log Tasting</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    `;
  }

  _renderDetailModal() {
    const w = this._modalWine;
    const df = this._detailForm;
    if (!w || !df) return "";

    const statusMeta = DRINK_STATUS_META[w.drink_status] || DRINK_STATUS_META.unknown;
    const typeLabel = WINE_TYPE_LABELS[w.wine_type] || "Wine";
    const drinkYears =
      w.drink_from_year || w.drink_until_year
        ? `${w.drink_from_year || "Now"}–${w.drink_until_year || "…"}`
        : statusMeta.label;

    return `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal-surface">
          <div class="modal-header">
            <h2><ha-icon icon="mdi:notebook-edit-outline"></ha-icon> ${escapeHtml(w.winery)} – ${escapeHtml(w.name)} (${w.vintage || "NV"})</h2>
            <button class="ha-btn icon-btn" id="close-modal-btn"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>
          <div class="modal-body">
            <div class="detail-overview-header" style="display: flex; gap: 14px; margin-bottom: 16px; padding: 12px; border-radius: 10px; background: var(--secondary-background-color, rgba(127,127,127,0.06)); align-items: center;">
              <div class="detail-thumb-wrap" style="position: relative; cursor: pointer;" title="Click to enlarge image">
                ${
                  w.image_url
                    ? `<img class="detail-wine-thumb preview-image-clickable" src="${escapeHtml(w.image_url)}" alt="${escapeHtml(w.name)}" data-action="preview-image" data-id="${w.id}" style="width: 72px; height: 96px; border-radius: 8px; object-fit: cover; box-shadow: 0 2px 6px rgba(0,0,0,0.15);" />
                       <div class="thumb-zoom-overlay" style="position: absolute; bottom: 4px; right: 4px; background: rgba(0,0,0,0.65); color: #fff; border-radius: 4px; padding: 2px 4px; font-size: 10px; display: flex; align-items: center; pointer-events: none;">
                         <ha-icon icon="mdi:magnify-plus-outline" style="--mdc-icon-size: 14px;"></ha-icon>
                       </div>`
                    : `<div class="wine-thumb-placeholder type-${escapeHtml(w.wine_type)}" style="width: 72px; height: 96px; border-radius: 8px;">
                         <ha-icon icon="mdi:glass-wine"></ha-icon>
                       </div>`
                }
              </div>
              <div style="flex: 1; min-width: 0;">
                <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 4px;">
                  <span class="type-pill type-${escapeHtml(w.wine_type)}">${escapeHtml(typeLabel)}</span>
                  <span class="vintage-pill">${escapeHtml(w.vintage ? String(w.vintage) : "NV")}</span>
                  <span class="drink-pill" style="border-color:${statusMeta.color}; color:${statusMeta.color}; font-size: 11px;">
                    ${escapeHtml(statusMeta.label)} (${escapeHtml(drinkYears)})
                  </span>
                </div>
                <div style="font-size: 13px; font-weight: 500; color: var(--secondary-text-color);">${escapeHtml(w.winery)}</div>
                <div style="font-size: 16px; font-weight: 600; margin: 2px 0 4px;">${escapeHtml(w.name)}</div>
                <div style="font-size: 12px; color: var(--secondary-text-color);">
                  ${escapeHtml([w.varietal, w.region, w.country].filter(Boolean).join(" • ") || "—")}
                </div>
                <div style="display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap;">
                  ${
                    w.vivino_url
                      ? `<a class="vivino-badge" href="${escapeHtml(w.vivino_url)}" target="_blank" rel="noopener noreferrer" title="Open on Vivino (opens in new tab)" style="text-decoration: none;">
                           ★ ${escapeHtml(w.vivino_rating ? Number(w.vivino_rating).toFixed(1) : "Vivino")}
                           <ha-icon icon="mdi:open-in-new" style="--mdc-icon-size: 13px; margin-left: 2px;"></ha-icon>
                         </a>`
                      : w.vivino_rating
                      ? `<span class="vivino-badge">★ ${escapeHtml(Number(w.vivino_rating).toFixed(1))}</span>`
                      : `<span class="vivino-badge muted">No Vivino rating</span>`
                  }
                  <span style="font-size: 12px; font-weight: 600; color: var(--primary-color);">
                    In Stock: ${Number(w.quantity || 0)} ${Number(w.quantity) === 1 ? "bottle" : "bottles"}
                  </span>
                </div>
              </div>
            </div>

            <form id="detail-form" class="form-grid">
              <div class="form-field full-width">
                <label>Free-Form Notes Overview</label>
                <textarea class="ha-textarea" name="general_notes" rows="3" placeholder="Master overview notes for this wine...">${escapeHtml(df.general_notes)}</textarea>
              </div>
              <div class="form-field">
                <label>Drink Window (From – Until Year)</label>
                <div class="split-2">
                  <input class="ha-input" type="number" name="drink_from_year" value="${escapeHtml(df.drink_from_year)}" placeholder="From Year" />
                  <input class="ha-input" type="number" name="drink_until_year" value="${escapeHtml(df.drink_until_year)}" placeholder="Until Year" />
                </div>
              </div>
              <div class="form-field">
                <label>When to Drink Guidance</label>
                <input class="ha-input" name="drink_window_note" value="${escapeHtml(df.drink_window_note)}" />
              </div>
              <div class="form-field">
                <label>Vivino Rating &amp; Personal Rating</label>
                <div class="split-2">
                  <input class="ha-input" type="number" step="0.1" name="vivino_rating" value="${escapeHtml(df.vivino_rating)}" placeholder="Vivino ★" />
                  <input class="ha-input" type="number" step="0.5" name="personal_rating" value="${escapeHtml(df.personal_rating)}" placeholder="My ★" />
                </div>
              </div>
              <div class="form-field">
                <label style="display: flex; justify-content: space-between; align-items: center;">
                  <span>Vivino URL</span>
                  ${
                    df.vivino_url
                      ? `<a href="${escapeHtml(df.vivino_url)}" target="_blank" rel="noopener noreferrer" style="font-size: 11px; color: var(--primary-color); display: inline-flex; align-items: center; gap: 2px; text-decoration: none;">
                           <span>Open in Vivino</span>
                           <ha-icon icon="mdi:open-in-new" style="--mdc-icon-size: 13px;"></ha-icon>
                         </a>`
                      : ""
                  }
                </label>
                <input class="ha-input" name="vivino_url" value="${escapeHtml(df.vivino_url)}" />
              </div>
              <div class="modal-actions full-width" style="display: flex; justify-content: space-between; align-items: center;">
                <button type="button" class="ha-btn danger-btn" id="btn-delete-wine" data-id="${w.id}" style="background: rgba(198, 40, 40, 0.12); color: var(--error-color, #c62828); border-color: rgba(198, 40, 40, 0.35);">
                  <ha-icon icon="mdi:trash-can-outline"></ha-icon>
                  <span>Delete Wine</span>
                </button>
                <button type="submit" class="ha-btn primary-btn">
                  <ha-icon icon="mdi:content-save-outline"></ha-icon>
                  <span>Save Overview Changes</span>
                </button>
              </div>
            </form>

            <div class="section-divider">Purchase Batches &amp; Storage Locations</div>
            <div class="timeline-list">
              ${
                (w.batches || []).length === 0
                  ? `<div class="empty-sub">No purchase batches recorded yet.</div>`
                  : (w.batches || [])
                      .map(
                        (b) => `
                        <div class="timeline-item">
                          <div class="timeline-title">
                            <strong>+${b.quantity_added} bottle(s)</strong> (${b.quantity_remaining} left in stock)
                            • <span>${escapeHtml(formatDisplayDate(b.added_at))}</span>
                          </div>
                          <div class="timeline-meta">
                            Bought at: <strong>${escapeHtml(b.purchase_location || "—")}</strong>
                            • Stored in: <strong>${escapeHtml(b.storage_location || "—")}</strong>
                            ${b.purchase_price !== null ? `• Price: ${escapeHtml(b.purchase_price)} ${escapeHtml(this._currency)}` : ""}
                          </div>
                          ${b.notes ? `<div class="timeline-note">${escapeHtml(b.notes)}</div>` : ""}
                        </div>
                      `
                      )
                      .join("")
              }
            </div>

            <div class="section-divider">Chronological Addition &amp; Tasting Notes Timeline</div>
            <div class="timeline-list">
              ${
                (w.timeline || []).length === 0
                  ? `<div class="empty-sub">No history entries yet.</div>`
                  : (w.timeline || [])
                      .map(
                        (h) => `
                        <div class="timeline-item">
                          <div class="timeline-title">
                            <span class="event-tag ${h.delta > 0 ? "added" : "consumed"}">
                              ${h.delta > 0 ? `Added +${h.delta}` : `Opened ${h.delta}`}
                            </span>
                            <span>${escapeHtml(formatDisplayDate(h.timestamp))}</span>
                            ${h.personal_rating ? `<span class="personal-badge">★ ${h.personal_rating}</span>` : ""}
                          </div>
                          ${
                            h.tasting_notes
                              ? `<div class="timeline-note">${escapeHtml(h.tasting_notes)}</div>`
                              : ""
                          }
                        </div>
                      `
                      )
                      .join("")
              }
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _openImagePreview(wine) {
    if (!wine || !wine.image_url) return;
    this._previewImageWine = wine;
    this._previousModal = this._activeModal;
    this._activeModal = "image_preview";
    this._render();
  }

  _closeImagePreview() {
    this._activeModal = this._previousModal || null;
    this._previewImageWine = null;
    this._previousModal = null;
    this._render();
  }

  _renderImagePreviewModal() {
    const wine = this._previewImageWine;
    if (!wine || !wine.image_url) return "";
    return `
      <div class="modal-backdrop" id="image-preview-backdrop" style="background: rgba(0, 0, 0, 0.85); z-index: 1100;">
        <div class="modal-surface" style="max-width: 540px; width: 92%; background: var(--card-background-color, #fff); border-radius: 14px; overflow: hidden; box-shadow: 0 16px 40px rgba(0,0,0,0.5);">
          <div class="modal-header" style="padding: 14px 18px; border-bottom: 1px solid var(--divider-color, #e0e0e0);">
            <div>
              <h2 style="font-size: 16px; margin: 0; display: flex; align-items: center; gap: 8px;">
                <ha-icon icon="mdi:image-outline" style="color: var(--primary-color);"></ha-icon>
                <span>${escapeHtml(wine.name)}</span>
              </h2>
              <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 2px;">
                ${escapeHtml(wine.winery)} (${wine.vintage || "NV"})
              </div>
            </div>
            <button class="ha-btn icon-btn" id="close-image-preview-btn" title="Close">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          <div style="padding: 12px; background: rgba(0,0,0,0.04); display: flex; justify-content: center; align-items: center; max-height: 75vh; overflow: hidden;">
            <img src="${escapeHtml(wine.image_url)}" alt="${escapeHtml(wine.name)}" style="max-height: 70vh; max-width: 100%; object-fit: contain; border-radius: 8px; display: block; box-shadow: 0 4px 12px rgba(0,0,0,0.25);" />
          </div>
        </div>
      </div>
    `;
  }

  _bindEvents() {
    const root = this.shadowRoot;
    if (!root) return;

    root.querySelector("#btn-scan-bottle")?.addEventListener("click", () => this._openScanModal(false));
    root.querySelector("#btn-add-manual")?.addEventListener("click", () => this._openScanModal(true));
    root.querySelector("#btn-refresh-vivino")?.addEventListener("click", () => this._refreshAllVivino());
    root.querySelector("#btn-toggle-grid")?.addEventListener("click", () => {
      this._viewMode = "grid";
      this._userToggledView = true;
      this._render();
    });
    root.querySelector("#btn-toggle-list")?.addEventListener("click", () => {
      this._viewMode = "list";
      this._userToggledView = true;
      this._render();
    });
    root.querySelector("#btn-open-backup")?.addEventListener("click", () => {
      this._activeModal = "backup";
      this._loadBackups();
      this._render();
    });

    const searchInput = root.querySelector("#wine-search-input");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this._searchQuery = e.target.value;
        this._render();
        const el = this.shadowRoot.querySelector("#wine-search-input");
        if (el) {
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
        }
      });
    }

    root.querySelector("#wine-sort-select")?.addEventListener("change", (e) => {
      this._sortBy = e.target.value;
      this._render();
    });

    root.querySelectorAll(".filter-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        this._filterTab = chip.dataset.tab;
        this._render();
      });
    });

    root.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const wineId = Number(btn.dataset.id);
        const wine = this._wines.find((w) => Number(w.id) === wineId);
        if (!wine) return;
        const action = btn.dataset.action;
        if (action === "quick-add") this._openQuickAddModal(wine);
        else if (action === "consume") this._openConsumeModal(wine);
        else if (action === "detail") this._openDetailModal(wine);
      });
    });

    // Modal handlers
    root.querySelector("#close-modal-btn")?.addEventListener("click", () => this._closeModal());
    root.querySelector("#cancel-modal-btn")?.addEventListener("click", () => this._closeModal());

    // Image preview modal handlers
    root.querySelector("#close-image-preview-btn")?.addEventListener("click", () => this._closeImagePreview());
    root.querySelector("#image-preview-backdrop")?.addEventListener("click", (e) => {
      if (e.target.id === "image-preview-backdrop") {
        this._closeImagePreview();
      }
    });

    root.querySelectorAll('[data-action="preview-image"]').forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const wineId = Number(el.dataset.id);
        const wine = this._wines.find((w) => Number(w.id) === wineId) || this._modalWine;
        if (wine && wine.image_url) {
          this._openImagePreview(wine);
        }
      });
    });

    // Delete wine button handler
    root.querySelector("#btn-delete-wine")?.addEventListener("click", async () => {
      const wine = this._modalWine;
      if (!wine || !this._hass) return;
      const label = `${wine.winery ? wine.winery + " – " : ""}${wine.name} (${wine.vintage || "NV"})`;
      const confirmed = window.confirm(
        `⚠️ WARNING: Are you sure you want to permanently delete "${label}" from your cellar database?\n\nThis will completely remove the wine, all its purchase batches, and all tasting history. This action CANNOT be undone!`
      );
      if (!confirmed) return;

      try {
        await this._hass.callWS({
          type: "wine_inventory/delete_wine",
          wine_id: Number(wine.id),
        });
        this._closeModal();
        await this._fetchInventory();
      } catch (err) {
        alert(`Failed to delete wine: ${err?.message || err}`);
      }
    });

    // Crop / Rotate modal handlers
    root.querySelector("#close-crop-btn")?.addEventListener("click", () => this._cancelCrop());
    root.querySelector("#btn-cancel-crop")?.addEventListener("click", () => this._cancelCrop());
    root.querySelector("#btn-confirm-crop")?.addEventListener("click", () => this._confirmCropAndScan());
    root.querySelector("#btn-rotate-left")?.addEventListener("click", () => this._rotateCrop(-90));
    root.querySelector("#btn-rotate-right")?.addEventListener("click", () => this._rotateCrop(90));
    root.querySelector("#btn-reset-crop")?.addEventListener("click", () => this._resetCrop());
    root.querySelector("#reopen-crop-btn")?.addEventListener("click", () => {
      this._activeModal = "crop_rotate";
      this._render();
    });
    root.querySelector("#retry-crop-btn")?.addEventListener("click", () => {
      this._activeModal = "crop_rotate";
      this._render();
    });
    root.querySelector("#dismiss-scan-error-btn")?.addEventListener("click", () => {
      this._scanState.error = "";
      this._render();
    });
    root.querySelector("#clear-scan-error-btn")?.addEventListener("click", () => {
      this._scanState.error = "";
      this._render();
    });
    root.querySelector("#dismiss-card-error-btn")?.addEventListener("click", () => {
      this._error = "";
      this._render();
    });

    // Backup & Restore modal handlers
    root.querySelector("#close-backup-btn")?.addEventListener("click", () => this._closeModal());
    root.querySelector("#dismiss-backup-error-btn")?.addEventListener("click", () => {
      this._backupState.error = "";
      this._render();
    });
    root.querySelector("#dismiss-backup-success-btn")?.addEventListener("click", () => {
      this._backupState.success = "";
      this._render();
    });
    root.querySelector("#btn-create-backup")?.addEventListener("click", () => this._handleCreateBackup());
    root.querySelector("#btn-select-restore")?.addEventListener("click", () => {
      root.querySelector("#restore-file-input")?.click();
    });
    root.querySelector("#restore-file-input")?.addEventListener("change", (e) => this._handleRestoreFile(e));
    root.querySelector("#btn-select-import")?.addEventListener("click", () => {
      root.querySelector("#import-file-input")?.click();
    });
    root.querySelector("#import-file-input")?.addEventListener("change", (e) => this._handleImportFile(e));
    root.querySelectorAll("[data-restore-server-filename]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._handleRestoreServerBackup(btn.dataset.restoreServerFilename);
      });
    });

    root.querySelector("#bottle-file-input")?.addEventListener("change", (e) => this._handleFileSelected(e));
    root.querySelector("#vivino-candidate-select")?.addEventListener("change", (e) => {
      this._applyVivinoCandidate(Number(e.target.value));
    });
    root.querySelector("#btn-disconnect-vivino")?.addEventListener("click", () => {
      this._applyVivinoCandidate(-1);
    });

    if (this._activeModal === "crop_rotate") {
      this._setupCropCanvas();
    }

    const scanForm = root.querySelector("#scan-add-form");
    if (scanForm) {
      scanForm.querySelectorAll("input, select, textarea").forEach((inp) => {
        inp.addEventListener("change", (e) => {
          if (e.target.name) {
            this._scanState.form[e.target.name] = e.target.value;
          }
        });
      });
      scanForm.addEventListener("submit", (e) => this._submitScanOrAddForm(e));
    }

    const qaForm = root.querySelector("#quick-add-form");
    if (qaForm) {
      qaForm.querySelectorAll("input, select, textarea").forEach((inp) => {
        inp.addEventListener("change", (e) => {
          if (e.target.name) {
            this._quickAddForm[e.target.name] = e.target.value;
          }
        });
      });
      qaForm.addEventListener("submit", (e) => this._submitQuickAdd(e));
    }

    const consumeForm = root.querySelector("#consume-form");
    if (consumeForm) {
      consumeForm.querySelectorAll("input, select, textarea").forEach((inp) => {
        inp.addEventListener("change", (e) => {
          if (e.target.name) {
            this._consumeForm[e.target.name] = e.target.value;
          }
        });
      });
      consumeForm.addEventListener("submit", (e) => this._submitConsume(e));
    }

    const detailForm = root.querySelector("#detail-form");
    if (detailForm) {
      detailForm.querySelectorAll("input, select, textarea").forEach((inp) => {
        inp.addEventListener("change", (e) => {
          if (e.target.name) {
            this._detailForm[e.target.name] = e.target.value;
          }
        });
      });
      detailForm.addEventListener("submit", (e) => this._submitDetailUpdate(e));
    }
  }

  _render() {
    if (!this.shadowRoot) return;
    const stats = this._statistics || {};
    const wines = this._getFilteredAndSortedWines();

    const tabs = [
      { id: "all", label: `In Stock (${stats.total_bottles || 0})` },
      { id: "ready", label: `Ready to Drink (${stats.ready_to_drink_bottles || 0})` },
      { id: "drink_soon", label: `Drink Soon (${stats.drink_soon_bottles || 0})` },
      { id: "red", label: `Red (${stats.by_type?.red || 0})` },
      { id: "white", label: `White (${stats.by_type?.white || 0})` },
      { id: "rose", label: `Rosé (${stats.by_type?.rose || 0})` },
      { id: "sparkling", label: `Sparkling (${stats.by_type?.sparkling || 0})` },
      { id: "archived", label: `Tasted Archive (${stats.archived_wines || 0})` },
    ];

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          color: var(--primary-text-color);
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
        }
        ha-card {
          padding: 20px;
          border-radius: var(--ha-card-border-radius, 12px);
          background: var(--ha-card-background, var(--card-background-color, #fff));
        }
        .header-bar {
          display: flex;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
        }
        .title-block h1 {
          margin: 0;
          font-size: 20px;
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .env-pills {
          display: flex;
          gap: 8px;
          margin-top: 4px;
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .env-pill {
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
          padding: 2px 8px;
          border-radius: 999px;
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }
        .header-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .ha-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          padding: 8px 14px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
          transition: opacity 0.15s ease;
        }
        .ha-btn:hover {
          opacity: 0.9;
        }
        .primary-btn {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          border-color: transparent;
        }
        .secondary-btn {
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.1));
        }
        .icon-btn {
          padding: 6px;
          min-width: 34px;
          min-height: 34px;
        }
        .controls-bar {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-bottom: 12px;
        }
        .ha-input, .ha-textarea {
          width: 100%;
          box-sizing: border-box;
          padding: 8px 12px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
          font-size: 13px;
        }
        .search-wrap {
          flex: 1 1 240px;
        }
        .filter-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-bottom: 16px;
        }
        .filter-chip {
          padding: 5px 12px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          border: 1px solid var(--divider-color, #ddd);
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
          color: var(--primary-text-color);
        }
        .filter-chip.active {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          border-color: transparent;
        }
        .wine-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 14px;
        }
        .wine-item {
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 12px;
          padding: 14px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          gap: 10px;
          background: var(--card-background-color, #fff);
        }
        .wine-item-top {
          display: flex;
          gap: 12px;
        }
        .wine-thumb, .wine-thumb-placeholder {
          width: 68px;
          height: 92px;
          border-radius: 8px;
          object-fit: cover;
          flex-shrink: 0;
        }
        .wine-thumb-placeholder {
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(123, 31, 58, 0.14);
          color: #880e4f;
        }
        .wine-info {
          flex: 1;
          min-width: 0;
        }
        .wine-badges-row {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          margin-bottom: 4px;
        }
        .type-pill, .vintage-pill, .drink-pill {
          font-size: 10px;
          font-weight: 600;
          padding: 2px 7px;
          border-radius: 999px;
          text-transform: uppercase;
        }
        .type-red { background: rgba(183, 28, 28, 0.15); color: #c62828; }
        .type-white { background: rgba(245, 127, 23, 0.15); color: #ef6c00; }
        .type-rose { background: rgba(233, 30, 99, 0.15); color: #ad1457; }
        .type-sparkling { background: rgba(2, 136, 209, 0.15); color: #0277bd; }
        .vintage-pill {
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.15));
        }
        .drink-pill {
          border: 1px solid currentColor;
        }
        .wine-winery {
          font-size: 12px;
          color: var(--secondary-text-color);
          font-weight: 500;
        }
        .wine-title {
          font-size: 15px;
          font-weight: 600;
          margin: 1px 0 3px;
        }
        .wine-sub {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-bottom: 6px;
        }
        .wine-ratings-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
        }
        .vivino-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(166, 26, 46, 0.12);
          color: #a61a2e;
          padding: 2px 8px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 600;
          text-decoration: none;
        }
        .vivino-badge.muted {
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
          font-weight: 400;
        }
        .vivino-sub {
          font-weight: 400;
          font-size: 11px;
        }
        .personal-badge {
          font-size: 11px;
          font-weight: 600;
          color: var(--primary-color);
        }
        .wine-meta-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 4px 10px;
          font-size: 12px;
          color: var(--secondary-text-color);
          padding-top: 8px;
          border-top: 1px dashed var(--divider-color, #e0e0e0);
        }
        .wine-meta-grid > div {
          display: flex;
          align-items: center;
          gap: 4px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .wine-meta-grid ha-icon {
          --mdc-icon-size: 15px;
          flex-shrink: 0;
        }
        .wine-notes-preview {
          font-size: 12px;
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.07));
          padding: 6px 10px;
          border-radius: 6px;
          color: var(--primary-text-color);
        }
        .wine-actions-bar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
        }
        .stepper-group {
          display: inline-flex;
          align-items: center;
          gap: 8px;
        }
        .qty-badge {
          font-size: 13px;
          font-weight: 600;
          min-width: 68px;
          text-align: center;
        }
        .empty-state {
          text-align: center;
          padding: 32px 16px;
          color: var(--secondary-text-color);
        }
        /* Modal Styles */
        .modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.55);
          z-index: 999;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 16px;
        }
        .modal-surface {
          background: var(--ha-card-background, var(--card-background-color, #fff));
          color: var(--primary-text-color);
          border-radius: 14px;
          max-width: 680px;
          width: 100%;
          max-height: 90vh;
          overflow-y: auto;
          box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
        }
        .modal-surface.compact {
          max-width: 480px;
        }
        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 16px 20px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .modal-header h2 {
          margin: 0;
          font-size: 17px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .modal-body {
          padding: 18px 20px;
        }
        .scan-capture-box {
          margin-bottom: 16px;
          padding: 12px;
          border-radius: 10px;
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
        }
        .scan-buttons-row {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
        }
        .crop-modal-surface {
          max-width: 640px;
          width: 95%;
        }
        .crop-modal-body {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 14px;
        }
        .crop-instructions {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          color: var(--secondary-text-color);
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
          padding: 8px 12px;
          border-radius: 8px;
          width: 100%;
          box-sizing: border-box;
        }
        .canvas-wrapper {
          display: flex;
          align-items: center;
          justify-content: center;
          background: #111;
          border-radius: 8px;
          overflow: hidden;
          padding: 10px;
          width: 100%;
          box-sizing: border-box;
          min-height: 240px;
        }
        #crop-canvas {
          touch-action: none;
          user-select: none;
          max-width: 100%;
          display: block;
          border-radius: 4px;
        }
        .crop-controls-row {
          display: flex;
          flex-wrap: wrap;
          justify-content: center;
          gap: 8px;
          width: 100%;
        }
        .crop-footer {
          margin-top: 8px;
        }
        .scan-status-banner, .scan-existing-banner, .scan-error-banner {
          margin-top: 10px;
          padding: 10px 12px;
          border-radius: 8px;
          font-size: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .scan-error-card {
          margin-top: 12px;
          padding: 14px;
          border-radius: 10px;
          border: 1px solid var(--error-color, #c62828);
          background: rgba(198, 40, 40, 0.08);
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .scan-error-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        .scan-error-title-wrap {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .scan-error-message {
          margin: 0;
          font-size: 13px;
          color: var(--primary-text-color);
          font-weight: 500;
          line-height: 1.4;
        }
        .scan-error-hint {
          margin-top: 6px;
          font-size: 12px;
          color: var(--secondary-text-color);
          line-height: 1.4;
        }
        .scan-error-hint ul {
          margin: 4px 0 0 16px;
          padding: 0;
        }
        .scan-error-hint li {
          margin-bottom: 2px;
        }
        .scan-error-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 4px;
        }
        .card-alert-banner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 14px;
          border-radius: 8px;
          margin-bottom: 14px;
          font-size: 13px;
          gap: 10px;
          background: rgba(198, 40, 40, 0.12);
          border: 1px solid var(--error-color, #c62828);
          color: var(--primary-text-color);
        }
        .card-alert-content {
          display: flex;
          align-items: center;
          gap: 8px;
          flex: 1;
        }
        .scan-status-banner {
          background: rgba(2, 136, 209, 0.15);
          color: var(--primary-text-color);
        }
        .scan-existing-banner {
          background: rgba(46, 125, 50, 0.15);
          color: var(--primary-text-color);
        }
        .scan-error-banner {
          background: rgba(198, 40, 40, 0.15);
          color: #c62828;
        }
        .form-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .form-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .form-field.full-width, .section-divider.full-width, .modal-actions.full-width {
          grid-column: 1 / -1;
        }
        .form-field label {
          font-size: 12px;
          font-weight: 500;
          color: var(--secondary-text-color);
        }
        .split-2 {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }
        .section-divider {
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--primary-color);
          padding-top: 8px;
          margin-top: 4px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
        }
        .modal-actions {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          padding-top: 10px;
        }
        .timeline-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin: 10px 0 16px;
        }
        .timeline-item {
          padding: 10px 12px;
          border-radius: 8px;
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
          font-size: 12px;
        }
        .timeline-title {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
        }
        .event-tag {
          padding: 2px 6px;
          border-radius: 4px;
          font-weight: 600;
          font-size: 11px;
        }
        .event-tag.added { background: rgba(46, 125, 50, 0.15); color: #2e7d32; }
        .event-tag.consumed { background: rgba(239, 108, 0, 0.15); color: #ef6c00; }
        .timeline-note {
          margin-top: 4px;
          color: var(--primary-text-color);
          white-space: pre-wrap;
        }
        @media (max-width: 600px) {
          .form-grid {
            grid-template-columns: 1fr;
          }
        }
        .active-view {
          background: var(--primary-color, #03a9f4) !important;
          color: var(--text-primary-color, #fff) !important;
          border-color: transparent !important;
        }
        .wine-list-table-container {
          overflow-x: auto;
          margin-top: 6px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 10px;
          background: var(--card-background-color, #fff);
        }
        .wine-list-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
          text-align: left;
        }
        .wine-list-table th {
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
          padding: 10px 12px;
          font-weight: 600;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--secondary-text-color);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          white-space: nowrap;
        }
        .wine-list-table td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--divider-color, #f0f0f0);
          vertical-align: middle;
        }
        .wine-list-table tr:last-child td {
          border-bottom: none;
        }
        .wine-list-table tr:hover {
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.04));
        }
        .wine-list-thumb {
          width: 36px;
          height: 48px;
          border-radius: 4px;
          object-fit: cover;
          display: block;
        }
        .wine-list-thumb-placeholder {
          width: 36px;
          height: 48px;
          border-radius: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .wine-list-title-wrap {
          display: flex;
          flex-direction: column;
          gap: 2px;
          max-width: 260px;
        }
        .wine-list-title-wrap strong {
          font-size: 13px;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .wine-list-title-wrap span {
          font-size: 11px;
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .wine-list-actions {
          display: flex;
          align-items: center;
          gap: 6px;
          white-space: nowrap;
        }
      </style>

      <ha-card>
        <div class="header-bar">
          <div class="title-block">
            <h1>
              <ha-icon icon="mdi:glass-wine" style="color: #a61a2e;"></ha-icon>
              <span>${escapeHtml(this._cellarName)}</span>
            </h1>
            <div class="env-pills">
              <span><strong>${stats.total_bottles || 0}</strong> bottles (${stats.unique_wines || 0} unique)</span>
              ${
                this._tempEntity
                  ? `<span class="env-pill"><ha-icon icon="mdi:thermometer"></ha-icon><span id="env-temp-val">—</span></span>`
                  : ""
              }
              ${
                this._humidityEntity
                  ? `<span class="env-pill"><ha-icon icon="mdi:water-percent"></ha-icon><span id="env-hum-val">—</span></span>`
                  : ""
              }
            </div>
          </div>

          <div class="header-actions">
            <button class="ha-btn ${this._viewMode === "grid" ? "active-view" : "secondary-btn"} icon-btn" id="btn-toggle-grid" title="Grid View">
              <ha-icon icon="mdi:view-grid"></ha-icon>
            </button>
            <button class="ha-btn ${this._viewMode === "list" ? "active-view" : "secondary-btn"} icon-btn" id="btn-toggle-list" title="Line-Item List View">
              <ha-icon icon="mdi:view-list"></ha-icon>
            </button>
            <button class="ha-btn secondary-btn" id="btn-open-backup" title="Backup, Restore &amp; Import Database">
              <ha-icon icon="mdi:database-arrow-down"></ha-icon>
              <span>Backup / Import</span>
            </button>
            <button class="ha-btn primary-btn" id="btn-scan-bottle">
              <ha-icon icon="mdi:camera-iris"></ha-icon>
              <span>Scan Bottle</span>
            </button>
            <button class="ha-btn secondary-btn" id="btn-add-manual">
              <ha-icon icon="mdi:plus"></ha-icon>
              <span>Add Wine</span>
            </button>
            <button class="ha-btn icon-btn" id="btn-refresh-vivino" title="Refresh Vivino Ratings">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
        </div>

        <div class="controls-bar">
          <div class="search-wrap">
            <input
              id="wine-search-input"
              class="ha-input"
              type="search"
              placeholder="Search winery, wine, varietal, where bought, location, or notes…"
              value="${escapeHtml(this._searchQuery)}"
            />
          </div>
          <div>
            <select id="wine-sort-select" class="ha-input">
              <option value="recent" ${this._sortBy === "recent" ? "selected" : ""}>Sort: Recently Added / Updated</option>
              <option value="rating" ${this._sortBy === "rating" ? "selected" : ""}>Sort: Vivino Rating (High → Low)</option>
              <option value="drink_window" ${this._sortBy === "drink_window" ? "selected" : ""}>Sort: Drink Window (Urgent First)</option>
              <option value="vintage" ${this._sortBy === "vintage" ? "selected" : ""}>Sort: Vintage (Oldest First)</option>
              <option value="quantity" ${this._sortBy === "quantity" ? "selected" : ""}>Sort: Bottle Count</option>
            </select>
          </div>
        </div>

        <div class="filter-chips">
          ${tabs
            .map(
              (t) => `
              <button class="filter-chip ${this._filterTab === t.id ? "active" : ""}" data-tab="${t.id}">
                ${escapeHtml(t.label)}
              </button>
            `
            )
            .join("")}
        </div>

        ${
          this._error
            ? `<div class="card-alert-banner" role="alert">
                <div class="card-alert-content">
                  <ha-icon icon="mdi:alert-circle" style="color: var(--error-color, #c62828);"></ha-icon>
                  <span>${escapeHtml(this._error)}</span>
                </div>
                <button class="ha-btn icon-btn" id="dismiss-card-error-btn" title="Dismiss">
                  <ha-icon icon="mdi:close"></ha-icon>
                </button>
              </div>`
            : ""
        }

        ${
          wines.length === 0
            ? `<div class="empty-state">
                <ha-icon icon="mdi:glass-wine" style="--mdc-icon-size: 40px; color: #a61a2e;"></ha-icon>
                <p>No wines match the current filter. Click <strong>Scan Bottle</strong> to scan a wine label with Gemini Flash-Lite!</p>
              </div>`
            : this._viewMode === "list"
            ? this._renderWineListView(wines)
            : `<div class="wine-grid">
                ${wines.map((w) => this._renderWineCard(w)).join("")}
              </div>`
        }
      </ha-card>

      ${this._activeModal === "scan" ? this._renderScanModal() : ""}
      ${this._activeModal === "crop_rotate" ? this._renderCropRotateModal() : ""}
      ${this._activeModal === "quick_add" ? this._renderQuickAddModal() : ""}
      ${this._activeModal === "consume" ? this._renderConsumeModal() : ""}
      ${this._activeModal === "detail" ? this._renderDetailModal() : ""}
      ${this._activeModal === "backup" ? this._renderBackupModal() : ""}
      ${this._activeModal === "image_preview" ? this._renderImagePreviewModal() : ""}
    `;

    this._updateEnvironmentBadges();
    this._bindEvents();
  }
}

if (!customElements.get("wine-inventory-card")) {
  customElements.define("wine-inventory-card", WineInventoryCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "wine-inventory-card")) {
  window.customCards.push({
    type: "wine-inventory-card",
    name: "Lekkersappie Wine Cellar Card",
    description: "Lekkersappie: Scan wine labels with Gemini Flash-Lite, enrich with Vivino ratings, and manage cellar stock & notes.",
    preview: true,
  });
}
