/**
 * Lekkersappie Standalone Mobile Web App (PWA) — /lekkersappie/app.js (v0.3.0)
 * Runs parallel to the native Home Assistant UI and supports full Home Screen installation.
 */

const WINE_TYPES = {
  red: "Red",
  white: "White",
  rose: "Rosé",
  sparkling: "Sparkling",
  dessert: "Dessert",
  fortified: "Fortified",
};

const DRINK_META = {
  ready: { label: "Ready to Drink", color: "#2e7d32" },
  drink_soon: { label: "Drink Soon", color: "#ef6c00" },
  hold: { label: "Hold / Aging", color: "#0277bd" },
  past_peak: { label: "Past Peak", color: "#c62828" },
  unknown: { label: "No Window Set", color: "#6c5e63" },
};

const FONT_SCALES = [
  { id: "S", value: 0.9 },
  { id: "M", value: 1.0 },
  { id: "L", value: 1.15 },
  { id: "XL", value: 1.3 },
];

function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function nowIsoMinutes() {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 16);
}

function fmtDate(isoStr) {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return String(isoStr).slice(0, 16);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

class LekkersappieMobileApp {
  constructor(rootEl) {
    this.root = rootEl;
    this.state = {
      cellarName: "Lekkersappie",
      currency: "EUR",
      tempDisplay: null,
      humidityDisplay: null,
      areas: ["Wine Cellar", "Wine Fridge", "Kitchen Rack"],
      statistics: {},
      wines: [],
      loading: true,
      error: "",
      isOnline: navigator.onLine,

      // Navigation: "cellar" | "areas" | "add" | "settings"
      activeNav: "cellar",
      filterTab: "all",
      areaFilter: "",
      searchQuery: "",
      sortBy: "recent",

      // Display preferences
      fontScale: this._loadFontScale(),
      theme: localStorage.getItem("lekkersappie_theme") || "auto",

      // PWA install state
      deferredPrompt: null,
      isInstalled:
        window.matchMedia("(display-mode: standalone)").matches ||
        window.navigator.standalone === true,
      isIOS: /iphone|ipad|ipod/i.test(window.navigator.userAgent || ""),
      installBannerDismissed: false,

      // Active sheet: null | "detail" | "scan" | "crop" | "preview" | "install_guide"
      activeSheet: null,
      detailWine: null,
      detailForm: null,
      previewWine: null,
      previousSheet: null,
      researchingWineId: null,
      researchError: "",
      linkingVivinoId: null,
      vivinoLinkError: "",

      // Scan & Add form
      scanBusy: false,
      scanError: "",
      scanImageData: "",
      scanCandidates: [],
      scanConfidence: "none",
      scanSuggestedIndex: -1,
      selectedCandidateIdx: -1,
      existingWine: null,
      scanForm: this._emptyForm(),
      cropState: null,

      toastMessage: "",
    };

    this._searchDebounce = null;
    this._toastTimer = null;

    this._applyThemeAndScale();
    this._setupPWAEvents();
    this._parseUrlParams();
    this.render();
    this.fetchState();
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
      vivino_rating: "",
      vivino_ratings_count: null,
      vivino_url: "",
      vivino_price_estimate: "",
      vivino_wine_id: null,
      vivino_match_confidence: "",
      rating_source: "",
      drink_from_year: "",
      drink_until_year: "",
      drink_window_note: "",
      general_notes: "",
      batch_notes: "",
      quantity: 1,
      added_at: nowIsoMinutes(),
      purchase_location: "",
      purchase_price: "",
      storage_location: "",
    };
  }

  _loadFontScale() {
    const val = parseFloat(localStorage.getItem("lekkersappie_font_scale") || "");
    return val >= 0.8 && val <= 1.5 ? val : 1.0;
  }

  _fontScaleLabel() {
    let best = FONT_SCALES[1];
    FONT_SCALES.forEach((s) => {
      if (Math.abs(s.value - this.state.fontScale) < Math.abs(best.value - this.state.fontScale)) {
        best = s;
      }
    });
    return best.id;
  }

  setFontScale(value) {
    this.state.fontScale = value;
    try {
      localStorage.setItem("lekkersappie_font_scale", String(value));
    } catch (_) {}
    this._applyThemeAndScale();
    this.render();
  }

  cycleFontScale() {
    const curLabel = this._fontScaleLabel();
    const idx = FONT_SCALES.findIndex((s) => s.id === curLabel);
    const next = FONT_SCALES[(idx + 1) % FONT_SCALES.length];
    this.setFontScale(next.value);
    this.showToast(`Text size set to ${next.id} (${Math.round(next.value * 100)}%)`);
  }

  setTheme(theme) {
    this.state.theme = theme;
    try {
      localStorage.setItem("lekkersappie_theme", theme);
    } catch (_) {}
    this._applyThemeAndScale();
    this.render();
  }

  _applyThemeAndScale() {
    document.documentElement.style.setProperty("--ls-app-scale", String(this.state.fontScale));
    const prefersDark =
      window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark =
      this.state.theme === "dark" || (this.state.theme === "auto" && prefersDark);
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  }

  _setupPWAEvents() {
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", () => {
        navigator.serviceWorker
          .register("/lekkersappie/sw.js", { scope: "/lekkersappie/" })
          .catch((err) => console.warn("SW registration skipped:", err));
      });
    }

    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      this.state.deferredPrompt = e;
      this.render();
    });

    window.addEventListener("appinstalled", () => {
      this.state.isInstalled = true;
      this.state.deferredPrompt = null;
      this.state.activeSheet = null;
      this.showToast("Lekkersappie installed as an app!");
      this.render();
    });

    window.addEventListener("online", () => {
      this.state.isOnline = true;
      this.fetchState();
    });
    window.addEventListener("offline", () => {
      this.state.isOnline = false;
      this.render();
    });
  }

  _parseUrlParams() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("action") === "scan") {
      this.state.activeSheet = "scan";
    }
    if (params.get("filter")) {
      this.state.filterTab = params.get("filter");
    }
  }

  showToast(msg) {
    this.state.toastMessage = msg;
    this.render();
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this.state.toastMessage = "";
      this.render();
    }, 2600);
  }

  async apiGet(action, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const url = `/api/wine_inventory/pwa/${action}${qs ? `?${qs}` : ""}`;
    const res = await fetch(url, { credentials: "same-origin" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  async apiPost(action, body = {}) {
    const res = await fetch(`/api/wine_inventory/pwa/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  async fetchState() {
    this.state.loading = true;
    try {
      const data = await this.apiGet("state", { include_out_of_stock: "true" });
      this.state.cellarName = data.cellar_name || "Lekkersappie";
      this.state.currency = data.currency || "EUR";
      this.state.tempDisplay = data.temperature_display || null;
      this.state.humidityDisplay = data.humidity_display || null;
      this.state.areas = data.areas || ["Wine Cellar", "Wine Fridge", "Kitchen Rack"];
      this.state.statistics = data.statistics || {};
      this.state.wines = data.wines || [];
      this.state.error = "";
    } catch (err) {
      this.state.error = err?.message || "Could not connect to Home Assistant Wine Inventory API.";
    } finally {
      this.state.loading = false;
      this.render();
    }
  }

  getFilteredWines() {
    const q = (this.state.searchQuery || "").trim().toLowerCase();
    const areaFilter = (this.state.areaFilter || "").trim().toLowerCase();

    const filtered = this.state.wines.filter((w) => {
      const qty = Number(w.quantity || 0);
      if (this.state.filterTab === "archived") {
        if (qty !== 0) return false;
      } else {
        if (qty <= 0) return false;
        if (
          this.state.filterTab === "ready" &&
          w.drink_status !== "ready" &&
          w.drink_status !== "drink_soon"
        ) {
          return false;
        }
        if (this.state.filterTab === "drink_soon" && w.drink_status !== "drink_soon") {
          return false;
        }
        if (
          ["red", "white", "rose", "sparkling"].includes(this.state.filterTab) &&
          w.wine_type !== this.state.filterTab
        ) {
          return false;
        }
      }

      if (areaFilter) {
        const wineAreas = [
          w.storage_location,
          w.last_storage_location,
          ...(w.active_storage_locations || []),
        ]
          .filter(Boolean)
          .map((x) => String(x).toLowerCase());
        if (!wineAreas.includes(areaFilter)) return false;
      }

      if (!q) return true;
      const hay = [
        w.winery,
        w.name,
        w.vintage,
        w.varietal,
        w.region,
        w.country,
        w.general_notes,
        w.last_purchase_location,
        w.last_storage_location,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });

    filtered.sort((a, b) => {
      if (this.state.sortBy === "rating") {
        return Number(b.vivino_rating || 0) - Number(a.vivino_rating || 0);
      }
      if (this.state.sortBy === "drink_window") {
        return Number(a.drink_until_year || 9999) - Number(b.drink_until_year || 9999);
      }
      if (this.state.sortBy === "vintage") {
        return Number(a.vintage || 9999) - Number(b.vintage || 9999);
      }
      if (this.state.sortBy === "quantity") {
        return Number(b.quantity || 0) - Number(a.quantity || 0);
      }
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });

    return filtered;
  }

  async openDetail(wineId) {
    const summaryWine = this.state.wines.find((w) => Number(w.id) === Number(wineId));
    if (!summaryWine) return;
    let fullWine = summaryWine;
    try {
      const res = await this.apiGet("detail", { wine_id: wineId });
      if (res.wine) fullWine = res.wine;
    } catch (_) {}

    this.state.detailWine = fullWine;
    this.state.detailForm = {
      winery: fullWine.winery || "",
      name: fullWine.name || "",
      varietal: fullWine.varietal || "",
      vintage: fullWine.vintage ?? "",
      country: fullWine.country || "",
      region: fullWine.region || "",
      storage_location:
        fullWine.storage_location ||
        fullWine.last_storage_location ||
        (fullWine.active_storage_locations || [])[0] ||
        "",
      purchase_location: fullWine.purchase_location || fullWine.last_purchase_location || "",
      purchase_price:
        fullWine.purchase_price !== null && fullWine.purchase_price !== undefined
          ? fullWine.purchase_price
          : fullWine.last_purchase_price ?? "",
      general_notes: fullWine.general_notes || "",
      drink_from_year: fullWine.drink_from_year ?? "",
      drink_until_year: fullWine.drink_until_year ?? "",
      drink_window_note: fullWine.drink_window_note || "",
      vivino_rating: fullWine.vivino_rating ?? "",
      vivino_url: fullWine.vivino_url || "",
      personal_rating: fullWine.personal_rating ?? "",
    };
    this.state.researchError = "";
    this.state.vivinoLinkError = "";
    this.state.activeSheet = "detail";
    this.render();
  }

  async adjustBottleStock(wine, delta) {
    const cur = Number(wine.quantity || 0);
    if (delta < 0 && cur <= 0) return;
    if (delta < 0 && cur === 1) {
      const ok = window.confirm(
        `⚠️ WARNING: Reducing the bottle count to 0 will mark "${wine.winery ? wine.winery + " – " : ""}${wine.name}" as consumed / out of stock.\n\nConfirm reducing quantity to 0?`
      );
      if (!ok) return;
    }
    try {
      const res = await this.apiPost("adjust", { wine_id: Number(wine.id), delta });
      if (res.wine && this.state.detailWine && Number(this.state.detailWine.id) === Number(wine.id)) {
        this.state.detailWine = res.wine;
      }
      await this.fetchState();
      this.showToast(delta > 0 ? "Added +1 bottle" : "Opened 1 bottle (-1)");
    } catch (err) {
      alert(`Failed to update stock: ${err?.message || err}`);
    }
  }

  async handleInstallClick() {
    if (this.state.deferredPrompt) {
      await this.state.deferredPrompt.prompt();
      const choice = await this.state.deferredPrompt.userChoice;
      if (choice?.outcome === "accepted") {
        this.state.isInstalled = true;
        this.state.deferredPrompt = null;
      }
      this.render();
      return;
    }
    this.state.activeSheet = "install_guide";
    this.render();
  }

  /* ================= Focus-safe search update ================= */
  refreshBottleListOnly() {
    const listContainer = this.root.querySelector("#mobile-bottle-list");
    if (!listContainer) {
      this.render();
      return;
    }
    listContainer.innerHTML = this._renderBottleListItems(this.getFilteredWines());
    this._bindBottleCardEvents(listContainer);
    const clearBtn = this.root.querySelector("#btn-mobile-clear-search");
    if (clearBtn) clearBtn.style.visibility = this.state.searchQuery ? "visible" : "hidden";
  }

  /* ================= Render Views ================= */

  _renderBottleListItems(wines) {
    if (this.state.loading && wines.length === 0) {
      return `<div class="panel-card" style="text-align:center; padding:28px;">Loading your wine cellar…</div>`;
    }
    if (wines.length === 0) {
      return `
        <div class="panel-card" style="text-align:center; padding:28px 16px;">
          <div style="font-size:32px; margin-bottom:6px;">🍷</div>
          <strong>No matching bottles found</strong>
          <p style="font-size:13px; color:var(--text-muted); margin:6px 0 14px;">
            ${this.state.searchQuery ? `Nothing matched “${esc(this.state.searchQuery)}”.` : "Tap Scan in the bottom bar to snap a wine label."}
          </p>
          <button class="btn btn-primary" data-open-scan="1">📷 Scan Bottle Label</button>
        </div>
      `;
    }

    return wines
      .map((w) => {
        const typeLabel = WINE_TYPES[w.wine_type] || "Wine";
        const drinkMeta = DRINK_META[w.drink_status] || DRINK_META.unknown;
        const area =
          (w.active_storage_locations || [])[0] || w.storage_location || w.last_storage_location || "";
        const rating = w.vivino_rating ? Number(w.vivino_rating).toFixed(1) : null;

        return `
          <div class="bottle-card" data-wine-id="${w.id}">
            <div class="bottle-thumb-wrap" data-preview-id="${w.id}" title="Tap to view label photo">
              ${
                w.image_url
                  ? `<img src="${esc(w.image_url)}" alt="${esc(w.name)}" />`
                  : `<span style="font-size:24px;">🍷</span>`
              }
            </div>
            <div class="bottle-card-main" data-detail-id="${w.id}">
              <div class="bottle-meta-top">
                <span class="pill pill-${esc(w.wine_type)}">${esc(typeLabel)}</span>
                <span class="pill pill-vintage">${esc(w.vintage || "NV")}</span>
                ${area ? `<span class="pill pill-area">📍 ${esc(area)}</span>` : ""}
              </div>
              <div class="bottle-winery">${esc(w.winery)}</div>
              <div class="bottle-name">${esc(w.name)}</div>
              <div class="bottle-subline">
                ${
                  rating
                    ? w.vivino_url
                      ? `<a class="vivino-tag" href="${esc(w.vivino_url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();">★ ${esc(rating)} ↗</a>`
                      : `<span class="vivino-tag">★ ${esc(rating)}</span>`
                    : ""
                }
                <span style="color:${drinkMeta.color}; font-weight:600; font-size:11.5px;">● ${esc(drinkMeta.label)}</span>
                ${w.country || w.varietal ? `<span class="sub-origin">• ${esc([w.varietal, w.country].filter(Boolean).join(" · "))}</span>` : ""}
              </div>
            </div>
            <div class="bottle-stepper">
              <div class="stepper-capsule">
                <button class="step-btn" data-step-minus="${w.id}" aria-label="Consume 1 bottle">−</button>
                <span class="step-qty">${Number(w.quantity || 0)}</span>
                <button class="step-btn" data-step-plus="${w.id}" aria-label="Add 1 bottle">+</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  _renderCellarView() {
    const stats = this.state.statistics || {};
    const wines = this.getFilteredWines();
    const tabs = [
      { id: "all", label: `In Stock (${stats.total_bottles || 0})` },
      { id: "ready", label: `Ready (${stats.ready_to_drink_bottles || 0})` },
      { id: "drink_soon", label: `Soon (${stats.drink_soon_bottles || 0})` },
      { id: "red", label: `Red (${stats.by_type?.red || 0})` },
      { id: "white", label: `White (${stats.by_type?.white || 0})` },
      { id: "rose", label: `Rosé (${stats.by_type?.rose || 0})` },
      { id: "sparkling", label: `Sparkling (${stats.by_type?.sparkling || 0})` },
      { id: "archived", label: `Archive (${stats.archived_wines || 0})` },
    ];

    return `
      ${
        !this.state.isInstalled && !this.state.installBannerDismissed
          ? `<div class="install-banner">
              <div class="install-banner-text">
                <strong>📲 Install Lekkersappie as an App</strong>
                <span>Launch full-screen from your phone’s Home Screen</span>
              </div>
              <div style="display:flex; gap:6px; align-items:center;">
                <button class="btn btn-primary" id="btn-banner-install" style="padding:7px 12px; min-height:36px; font-size:12.5px;">Install</button>
                <button class="btn btn-icon" id="btn-banner-dismiss" style="min-width:34px; min-height:34px; padding:4px;" aria-label="Dismiss">✕</button>
              </div>
            </div>`
          : ""
      }

      <div class="search-filter-dock">
        <div class="search-row">
          <div class="search-box">
            <span class="search-box-icon">🔍</span>
            <input
              id="mobile-search-input"
              class="search-input"
              type="text"
              inputmode="search"
              enterkeyhint="search"
              autocomplete="off"
              autocorrect="off"
              autocapitalize="off"
              spellcheck="false"
              placeholder="Search wine, grape, region, area…"
              value="${esc(this.state.searchQuery)}"
            />
            <button
              type="button"
              id="btn-mobile-clear-search"
              class="search-clear-btn"
              style="visibility: ${this.state.searchQuery ? "visible" : "hidden"};"
              aria-label="Clear search"
            >✕</button>
          </div>
          <select id="mobile-sort-select" class="sort-select" aria-label="Sort wines">
            <option value="recent" ${this.state.sortBy === "recent" ? "selected" : ""}>Recent</option>
            <option value="rating" ${this.state.sortBy === "rating" ? "selected" : ""}>★ Rating</option>
            <option value="drink_window" ${this.state.sortBy === "drink_window" ? "selected" : ""}>Drink Soon</option>
            <option value="vintage" ${this.state.sortBy === "vintage" ? "selected" : ""}>Vintage</option>
            <option value="quantity" ${this.state.sortBy === "quantity" ? "selected" : ""}>Stock</option>
          </select>
        </div>

        ${
          this.state.areaFilter
            ? `<div style="margin-bottom:8px; display:flex; align-items:center; justify-content:space-between; padding:6px 12px; border-radius:10px; background:var(--brand-soft); color:var(--brand); font-size:12.5px; font-weight:700;">
                <span>📍 Filtered by Area: ${esc(this.state.areaFilter)}</span>
                <button class="btn" id="btn-clear-area-filter" style="min-height:28px; padding:2px 8px; font-size:11.5px;">Show All</button>
              </div>`
            : ""
        }

        <div class="filter-pills-scroll">
          ${tabs
            .map(
              (t) => `
              <button class="filter-pill ${this.state.filterTab === t.id ? "active" : ""}" data-tab="${t.id}">
                ${esc(t.label)}
              </button>
            `
            )
            .join("")}
        </div>
      </div>

      <div id="mobile-bottle-list" class="bottle-list">
        ${this._renderBottleListItems(wines)}
      </div>
    `;
  }

  _renderAreasAndStatsView() {
    const stats = this.state.statistics || {};
    const inStock = this.state.wines.filter((w) => Number(w.quantity || 0) > 0);
    const areaCounts = {};
    inStock.forEach((w) => {
      const loc =
        (w.active_storage_locations || [])[0] ||
        w.storage_location ||
        w.last_storage_location ||
        "Unassigned Area";
      areaCounts[loc] = (areaCounts[loc] || 0) + Number(w.quantity || 0);
    });
    const areaEntries = Object.entries(areaCounts).sort((a, b) => b[1] - a[1]);

    return `
      <div class="section-wrap">
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-value">${stats.total_bottles || 0}</div>
            <div class="kpi-label">Bottles in Cellar</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value" style="color:var(--success);">${stats.ready_to_drink_bottles || 0}</div>
            <div class="kpi-label">Ready to Drink</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value">${stats.unique_wines || 0}</div>
            <div class="kpi-label">Unique Labels</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-value">${stats.estimated_cellar_value ? `${Math.round(stats.estimated_cellar_value)} ${esc(this.state.currency)}` : "—"}</div>
            <div class="kpi-label">Estimated Cellar Value</div>
          </div>
        </div>

        <div class="panel-card">
          <h3>
            <span>📍 Storage Areas</span>
            <small style="font-size:11.5px; color:var(--text-muted); font-weight:500;">Tap area to view bottles</small>
          </h3>
          ${
            areaEntries.length === 0
              ? `<div style="font-size:13px; color:var(--text-muted);">No bottles assigned to storage areas yet.</div>`
              : `<div class="area-grid">
                  ${areaEntries
                    .map(
                      ([loc, count]) => `
                      <button class="area-tile" data-jump-area="${esc(loc === "Unassigned Area" ? "" : loc)}">
                        <strong>${esc(loc)}</strong>
                        <span>${count} ${count === 1 ? "bottle" : "bottles"} →</span>
                      </button>
                    `
                    )
                    .join("")}
                </div>`
          }
        </div>

        <div class="panel-card">
          <h3>🍷 Cellar Breakdown by Style</h3>
          <div class="form-stack">
            ${Object.entries(WINE_TYPES)
              .map(([k, label]) => {
                const count = stats.by_type?.[k] || 0;
                const pct = stats.total_bottles ? Math.round((count / stats.total_bottles) * 100) : 0;
                return `
                  <div>
                    <div style="display:flex; justify-content:space-between; font-size:13px; font-weight:600; margin-bottom:4px;">
                      <span>${esc(label)}</span>
                      <span>${count} (${pct}%)</span>
                    </div>
                    <div class="taste-bar">
                      <div class="taste-bar-fill" style="width:${pct}%; background:var(--brand);"></div>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </div>
        </div>
      </div>
    `;
  }

  _renderManualAddView() {
    const f = this.state.scanForm;
    return `
      <div class="section-wrap">
        <div class="panel-card">
          <h3>➕ Add Wine to Cellar</h3>
          <form id="mobile-manual-add-form" class="form-stack">
            <div class="form-row-2">
              <div class="field">
                <label>Winery / Producer *</label>
                <input class="input" name="winery" required value="${esc(f.winery)}" placeholder="e.g. Château Margaux" />
              </div>
              <div class="field">
                <label>Wine / Cuvée Name *</label>
                <input class="input" name="name" required value="${esc(f.name)}" placeholder="e.g. Pavillon Rouge" />
              </div>
            </div>
            <div class="form-row-2">
              <div class="field">
                <label>Harvest Year / Vintage</label>
                <input class="input" type="number" name="vintage" value="${esc(f.vintage)}" placeholder="e.g. 2019 (blank = NV)" />
              </div>
              <div class="field">
                <label>Wine Style</label>
                <select class="select" name="wine_type">
                  ${Object.entries(WINE_TYPES)
                    .map(([k, lbl]) => `<option value="${k}" ${f.wine_type === k ? "selected" : ""}>${lbl}</option>`)
                    .join("")}
                </select>
              </div>
            </div>
            <div class="form-row-2">
              <div class="field">
                <label>Grape Variety</label>
                <input class="input" name="varietal" value="${esc(f.varietal)}" placeholder="e.g. Pinot Noir, Syrah" />
              </div>
              <div class="field">
                <label>Country &amp; Region</label>
                <div class="form-row-2">
                  <input class="input" name="country" value="${esc(f.country)}" placeholder="Country" />
                  <input class="input" name="region" value="${esc(f.region)}" placeholder="Region" />
                </div>
              </div>
            </div>
            <div class="form-row-2">
              <div class="field">
                <label>Storage Area / Location</label>
                <input class="input" name="storage_location" list="mobile-areas-dl" value="${esc(f.storage_location)}" placeholder="e.g. Wine Fridge" />
                <datalist id="mobile-areas-dl">
                  ${this.state.areas.map((a) => `<option value="${esc(a)}"></option>`).join("")}
                </datalist>
              </div>
              <div class="field">
                <label>Bottles Added &amp; Price (${esc(this.state.currency)})</label>
                <div class="form-row-2">
                  <input class="input" type="number" name="quantity" min="1" required value="${esc(f.quantity || 1)}" />
                  <input class="input" type="number" step="0.01" name="purchase_price" value="${esc(f.purchase_price)}" placeholder="Price" />
                </div>
              </div>
            </div>
            <div class="form-row-2">
              <div class="field">
                <label>Bought At (Store / Winery)</label>
                <input class="input" name="purchase_location" value="${esc(f.purchase_location)}" placeholder="e.g. Gall & Gall, Domain" />
              </div>
              <div class="field">
                <label>Drink Window (From – Until)</label>
                <div class="form-row-2">
                  <input class="input" type="number" name="drink_from_year" value="${esc(f.drink_from_year)}" placeholder="From" />
                  <input class="input" type="number" name="drink_until_year" value="${esc(f.drink_until_year)}" placeholder="Until" />
                </div>
              </div>
            </div>
            <div class="field">
              <label>Notes</label>
              <textarea class="textarea" name="general_notes" placeholder="Aromas, food pairing ideas, gift note…">${esc(f.general_notes)}</textarea>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%; min-height:48px;">Save Wine to Cellar</button>
          </form>
        </div>
      </div>
    `;
  }

  _renderSettingsView() {
    const scaleLabel = this._fontScaleLabel();
    return `
      <div class="section-wrap">
        <div class="panel-card">
          <h3>📲 Install Lekkersappie App</h3>
          <p style="font-size:13px; color:var(--text-muted); margin:0 0 12px; line-height:1.45;">
            ${
              this.state.isInstalled
                ? "✅ You are running Lekkersappie as an installed standalone mobile app."
                : "Install this mobile page to your phone’s Home Screen so it launches full-screen like a native app alongside Home Assistant."
            }
          </p>
          ${
            this.state.isInstalled
              ? `<div class="pill pill-area" style="display:inline-block; padding:6px 12px; font-size:12.5px;">✓ Installed Standalone Mode Active</div>`
              : `<button class="btn btn-primary" id="btn-settings-install" style="width:100%; min-height:46px;">
                  📲 Install App to Home Screen
                </button>`
          }
        </div>

        <div class="panel-card">
          <h3>Aa Text Size (Applies to All Views &amp; Wine Details)</h3>
          <div class="segmented-row">
            ${FONT_SCALES.map(
              (s) => `
              <button class="seg-btn ${scaleLabel === s.id ? "active" : ""}" data-set-scale="${s.value}">
                ${s.id} <small style="font-weight:500; font-size:11px;">${Math.round(s.value * 100)}%</small>
              </button>
            `
            ).join("")}
          </div>
        </div>

        <div class="panel-card">
          <h3>🎨 Appearance</h3>
          <div class="segmented-row" style="grid-template-columns: repeat(3, 1fr);">
            <button class="seg-btn ${this.state.theme === "auto" ? "active" : ""}" data-set-theme="auto">Auto</button>
            <button class="seg-btn ${this.state.theme === "light" ? "active" : ""}" data-set-theme="light">Light</button>
            <button class="seg-btn ${this.state.theme === "dark" ? "active" : ""}" data-set-theme="dark">Dark</button>
          </div>
        </div>

        <div class="panel-card">
          <h3>⚙️ Cellar Actions</h3>
          <div class="form-stack">
            <button class="btn" id="btn-settings-refresh-vivino" style="width:100%;">
              🔄 Refresh Verified Vivino Ratings
            </button>
            <a class="btn" href="/" style="width:100%;">
              🏠 Return to Home Assistant UI
            </a>
          </div>
        </div>
      </div>
    `;
  }

  /* ================= Slide-Up Sheets ================= */

  _renderDetailSheet() {
    const w = this.state.detailWine;
    const df = this.state.detailForm;
    if (!w || !df) return "";

    const typeLabel = WINE_TYPES[w.wine_type] || "Wine";
    const drinkMeta = DRINK_META[w.drink_status] || DRINK_META.unknown;
    let research = null;
    if (w.research_notes) {
      try {
        research = typeof w.research_notes === "string" ? JSON.parse(w.research_notes) : w.research_notes;
      } catch (_) {
        research = { summary: String(w.research_notes) };
      }
    }

    return `
      <div class="sheet-backdrop" id="sheet-backdrop">
        <div class="sheet-surface">
          <div class="sheet-handle"></div>
          <div class="scaled-zone">
            <div class="sheet-header">
              <h2>${esc(w.winery)} – ${esc(w.name)} (${esc(w.vintage || "NV")})</h2>
              <div style="display:flex; gap:6px; align-items:center;">
                <button class="btn btn-icon font-pill-btn" id="btn-sheet-font-scale" title="Adjust text size">
                  Aa <small>${this._fontScaleLabel()}</small>
                </button>
                <button class="btn btn-icon" id="btn-close-sheet" aria-label="Close">✕</button>
              </div>
            </div>

            <div class="sheet-body">
              <div class="detail-hero">
                ${
                  w.image_url
                    ? `<img class="detail-hero-img" src="${esc(w.image_url)}" alt="${esc(w.name)}" id="btn-detail-zoom-img" title="Tap to enlarge photo" />`
                    : `<div class="detail-hero-img" style="background:var(--brand-soft); display:flex; align-items:center; justify-content:center; font-size:30px;">🍷</div>`
                }
                <div class="detail-hero-info">
                  <div class="bottle-meta-top" style="margin-bottom:6px;">
                    <span class="pill pill-${esc(w.wine_type)}">${esc(typeLabel)}</span>
                    <span class="pill pill-vintage">📅 ${esc(w.vintage || "NV")}</span>
                    ${w.varietal ? `<span class="pill pill-vintage">🍇 ${esc(w.varietal)}</span>` : ""}
                    <span class="pill" style="border:1px solid ${drinkMeta.color}; color:${drinkMeta.color};">${esc(drinkMeta.label)}</span>
                  </div>
                  <div style="font-size:13px; color:var(--text-muted); font-weight:600;">${esc(w.winery)}</div>
                  <div style="font-size:18px; font-weight:800; line-height:1.25; margin:2px 0 6px;">${esc(w.name)}</div>
                  <div style="font-size:12.5px; color:var(--text-muted); margin-bottom:8px;">
                    🌍 ${esc([w.region, w.country].filter(Boolean).join(" • ") || "Origin not specified")}
                    ${df.storage_location ? ` • <strong style="color:var(--brand);">📍 ${esc(df.storage_location)}</strong>` : ""}
                    ${df.purchase_location ? ` • 🛒 ${esc(df.purchase_location)}` : ""}
                    ${df.purchase_price !== "" && df.purchase_price !== null ? ` • 💰 ${esc(df.purchase_price)} ${esc(this.state.currency)}` : ""}
                  </div>

                  <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px;">
                    ${
                      w.vivino_url
                        ? `<a class="vivino-tag" href="${esc(w.vivino_url)}" target="_blank" rel="noopener noreferrer" style="padding:4px 10px; font-size:12.5px;">
                            ★ ${esc(w.vivino_rating ? Number(w.vivino_rating).toFixed(1) : "Vivino")} ↗
                          </a>`
                        : `<span class="pill pill-vintage">No Vivino link</span>`
                    }
                    ${
                      w.vivino_url || w.vivino_rating
                        ? `<button type="button" class="btn btn-danger" id="btn-mobile-unlink-vivino" style="min-height:32px; padding:4px 9px; font-size:11.5px;">
                            Remove Vivino Link
                          </button>`
                        : ""
                    }
                  </div>

                  <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                    <input class="input" id="mobile-vivino-url-input" type="url" placeholder="Paste exact Vivino URL (…/w/1234)" style="flex:1; min-width:160px; min-height:36px; padding:5px 9px; font-size:13px;" />
                    <button type="button" class="btn" id="btn-mobile-link-vivino" style="min-height:36px; padding:5px 10px; font-size:12px;">
                      ${this.state.linkingVivinoId === w.id ? "Linking…" : "Link Vivino"}
                    </button>
                  </div>
                  ${this.state.vivinoLinkError ? `<div style="color:var(--danger); font-size:12px; margin-top:4px;">${esc(this.state.vivinoLinkError)}</div>` : ""}

                  <div style="display:flex; align-items:center; gap:10px; margin-top:12px; flex-wrap:wrap;">
                    <span style="font-size:13px; font-weight:700;">In Cellar:</span>
                    <div class="stepper-capsule">
                      <button type="button" class="step-btn" id="btn-detail-minus">−</button>
                      <span class="step-qty" style="padding:0 10px;">${Number(w.quantity || 0)}</span>
                      <button type="button" class="step-btn" id="btn-detail-plus">+</button>
                    </div>
                    <button type="button" class="btn btn-soft" id="btn-detail-research" style="margin-left:auto; min-height:40px;" ${this.state.researchingWineId === w.id ? "disabled" : ""}>
                      ✨ ${this.state.researchingWineId === w.id ? "Researching…" : "Research Wine (AI)"}
                    </button>
                  </div>
                </div>
              </div>

              ${
                this.state.researchError
                  ? `<div style="padding:10px 12px; border-radius:10px; background:rgba(198,40,40,0.1); color:var(--danger); font-size:12.5px; margin-bottom:12px;">
                      <strong>Research Error:</strong> ${esc(this.state.researchError)}
                    </div>`
                  : ""
              }

              ${
                research
                  ? `<div class="panel-card" style="margin-bottom:14px; background:var(--surface-alt);">
                      <h3>
                        <span>✨ Sommelier &amp; Producer AI Research</span>
                        <button type="button" class="btn btn-icon" id="btn-detail-reresearch" style="min-height:32px; min-width:32px; padding:4px;" title="Refresh AI Research">🔄</button>
                      </h3>
                      ${research.summary ? `<p style="font-size:13.5px; font-style:italic; margin:0 0 10px; line-height:1.45;">${esc(research.summary)}</p>` : ""}
                      ${
                        research.taste_profile
                          ? `<div class="taste-card">
                              <div style="font-size:11.5px; font-weight:800; text-transform:uppercase; color:var(--brand); margin-bottom:10px;">
                                Structural Taste Profile
                              </div>
                              <div class="taste-row">
                                <div class="taste-labels">
                                  <span>Soft / Round</span>
                                  <span style="color:var(--brand);">${esc(research.taste_profile.soft_vs_acidic_label || "Balanced")} (${Math.round(Number(research.taste_profile.soft_vs_acidic || 50))}%)</span>
                                  <span>Acidic / Crisp</span>
                                </div>
                                <div class="taste-bar">
                                  <div class="taste-bar-fill" style="width:${Math.max(4, Math.min(100, Number(research.taste_profile.soft_vs_acidic || 50)))}%; background:linear-gradient(90deg, #c084fc, #a61a2e);"></div>
                                  <div class="taste-bar-dot" style="left:${Math.max(2, Math.min(98, Number(research.taste_profile.soft_vs_acidic || 50)))}%;"></div>
                                </div>
                              </div>
                              <div class="taste-row">
                                <div class="taste-labels">
                                  <span>Light-Bodied</span>
                                  <span style="color:var(--brand);">${esc(research.taste_profile.light_vs_bold_label || "Medium")} (${Math.round(Number(research.taste_profile.light_vs_bold || 50))}%)</span>
                                  <span>Bold / Full</span>
                                </div>
                                <div class="taste-bar">
                                  <div class="taste-bar-fill" style="width:${Math.max(4, Math.min(100, Number(research.taste_profile.light_vs_bold || 50)))}%; background:linear-gradient(90deg, #fcd34d, #831843);"></div>
                                  <div class="taste-bar-dot" style="left:${Math.max(2, Math.min(98, Number(research.taste_profile.light_vs_bold || 50)))}%;"></div>
                                </div>
                              </div>
                              <div class="taste-row">
                                <div class="taste-labels">
                                  <span>Bone Dry</span>
                                  <span style="color:var(--brand);">${esc(research.taste_profile.dry_vs_sweet_label || "Dry")} (${Math.round(Number(research.taste_profile.dry_vs_sweet || 10))}%)</span>
                                  <span>Sweet / Luscious</span>
                                </div>
                                <div class="taste-bar">
                                  <div class="taste-bar-fill" style="width:${Math.max(4, Math.min(100, Number(research.taste_profile.dry_vs_sweet || 10)))}%; background:linear-gradient(90deg, #93c5fd, #f59e0b);"></div>
                                  <div class="taste-bar-dot" style="left:${Math.max(2, Math.min(98, Number(research.taste_profile.dry_vs_sweet || 10)))}%;"></div>
                                </div>
                              </div>
                            </div>`
                          : ""
                      }
                      <div class="form-stack" style="font-size:12.5px; line-height:1.5;">
                        ${research.producer_history ? `<div><strong style="color:var(--brand);">🏰 Producer Heritage:</strong> ${esc(research.producer_history)}</div>` : ""}
                        ${research.wine_and_terroir ? `<div><strong style="color:var(--brand);">🍇 Terroir &amp; Vineyards:</strong> ${esc(research.wine_and_terroir)}</div>` : ""}
                        ${research.tasting_profile ? `<div><strong style="color:var(--brand);">🍷 Tasting Profile:</strong> ${esc(research.tasting_profile)}</div>` : ""}
                        ${research.serving_and_pairing ? `<div><strong style="color:var(--brand);">🍽️ Pairings:</strong> ${esc(research.serving_and_pairing)}</div>` : ""}
                      </div>
                    </div>`
                  : ""
              }

              <form id="mobile-detail-form" class="form-stack">
                <div class="form-row-2">
                  <div class="field">
                    <label>Winery / Producer</label>
                    <input class="input" name="winery" value="${esc(df.winery)}" />
                  </div>
                  <div class="field">
                    <label>Wine / Cuvée Name</label>
                    <input class="input" name="name" value="${esc(df.name)}" />
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Grape Variety</label>
                    <input class="input" name="varietal" value="${esc(df.varietal)}" />
                  </div>
                  <div class="field">
                    <label>Harvest Year</label>
                    <input class="input" type="number" name="vintage" value="${esc(df.vintage)}" />
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Country of Origin</label>
                    <input class="input" name="country" value="${esc(df.country)}" />
                  </div>
                  <div class="field">
                    <label>Region / Appellation</label>
                    <input class="input" name="region" value="${esc(df.region)}" />
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Storage Area / Location</label>
                    <input class="input" name="storage_location" list="detail-areas-dl" value="${esc(df.storage_location)}" />
                    <datalist id="detail-areas-dl">
                      ${this.state.areas.map((a) => `<option value="${esc(a)}"></option>`).join("")}
                    </datalist>
                  </div>
                  <div class="field">
                    <label>Bought At &amp; Price (${esc(this.state.currency)})</label>
                    <div class="form-row-2">
                      <input class="input" name="purchase_location" value="${esc(df.purchase_location)}" placeholder="Store" />
                      <input class="input" type="number" step="0.01" name="purchase_price" value="${esc(df.purchase_price)}" placeholder="Price" />
                    </div>
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Drink Window (From – Until)</label>
                    <div class="form-row-2">
                      <input class="input" type="number" name="drink_from_year" value="${esc(df.drink_from_year)}" placeholder="From" />
                      <input class="input" type="number" name="drink_until_year" value="${esc(df.drink_until_year)}" placeholder="Until" />
                    </div>
                  </div>
                  <div class="field">
                    <label>My Personal Rating (1–5 ★)</label>
                    <input class="input" type="number" step="0.5" min="1" max="5" name="personal_rating" value="${esc(df.personal_rating)}" />
                  </div>
                </div>
                <div class="field">
                  <label>Master Wine Notes</label>
                  <textarea class="textarea" name="general_notes">${esc(df.general_notes)}</textarea>
                </div>

                <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:4px;">
                  <button type="button" class="btn btn-danger" id="btn-mobile-delete-wine" style="flex:1;">
                    🗑️ Delete Wine
                  </button>
                  <button type="submit" class="btn btn-primary" style="flex:2;">
                    💾 Save Overview Changes
                  </button>
                </div>
              </form>

              <div style="margin-top:18px; padding-top:14px; border-top:1px solid var(--border);">
                <strong style="font-size:12.5px; text-transform:uppercase; color:var(--brand);">Purchase Batches &amp; History</strong>
                <div style="display:flex; flex-direction:column; gap:8px; margin-top:8px;">
                  ${
                    (w.batches || []).length === 0
                      ? `<div style="font-size:12.5px; color:var(--text-muted);">No batch records yet.</div>`
                      : (w.batches || [])
                          .map(
                            (b) => `
                            <div style="padding:9px 11px; border-radius:10px; background:var(--surface-alt); font-size:12.5px;">
                              <strong>+${b.quantity_added} bottle(s)</strong> (${b.quantity_remaining} left) • ${esc(fmtDate(b.added_at))}<br/>
                              Bought at: <strong>${esc(b.purchase_location || "—")}</strong> • Area: <strong>${esc(b.storage_location || "—")}</strong>
                            </div>
                          `
                          )
                          .join("")
                  }
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderScanSheet() {
    const f = this.state.scanForm;
    return `
      <div class="sheet-backdrop" id="sheet-backdrop">
        <div class="sheet-surface">
          <div class="sheet-handle"></div>
          <div class="scaled-zone">
            <div class="sheet-header">
              <h2>📷 Scan Wine Label with Gemini AI</h2>
              <div style="display:flex; gap:6px; align-items:center;">
                <button class="btn btn-icon font-pill-btn" id="btn-sheet-font-scale">
                  Aa <small>${this._fontScaleLabel()}</small>
                </button>
                <button class="btn btn-icon" id="btn-close-sheet">✕</button>
              </div>
            </div>
            <div class="sheet-body">
              <div style="padding:14px; border-radius:14px; background:var(--surface-alt); border:1px solid var(--border); margin-bottom:14px;">
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <label class="btn btn-primary" style="flex:1; cursor:pointer;">
                    📷 Snap Photo / Upload Label
                    <input type="file" id="mobile-scan-file" accept="image/*" capture="environment" hidden />
                  </label>
                  ${
                    this.state.cropState?.image
                      ? `<button type="button" class="btn" id="btn-reopen-crop">✂️ Crop &amp; Rotate</button>`
                      : ""
                  }
                </div>
                ${
                  this.state.scanBusy
                    ? `<div style="margin-top:10px; font-size:13px; font-weight:600; color:var(--brand);">
                        ⏳ Analyzing bottle label with Gemini Flash-Lite &amp; verifying Vivino…
                      </div>`
                    : ""
                }
                ${
                  this.state.scanError
                    ? `<div style="margin-top:10px; padding:10px; border-radius:10px; background:rgba(198,40,40,0.1); color:var(--danger); font-size:12.5px;">
                        <strong>Scan Error:</strong> ${esc(this.state.scanError)}
                      </div>`
                    : ""
                }
                ${
                  this.state.scanCandidates.length > 0
                    ? `<div class="field" style="margin-top:10px;">
                        <label>
                          ${
                            this.state.scanConfidence === "high"
                              ? "✓ Verified Vivino Match"
                              : "⚠️ Possible Vivino Matches (Confirm or Leave Unlinked)"
                          }
                        </label>
                        <select id="mobile-vivino-candidate" class="select">
                          <option value="-1" ${this.state.selectedCandidateIdx === -1 ? "selected" : ""}>
                            🚫 Do not link to Vivino
                          </option>
                          ${this.state.scanCandidates
                            .map(
                              (c, idx) => `
                              <option value="${idx}" ${this.state.selectedCandidateIdx === idx ? "selected" : ""}>
                                ${c.prefilter_exact ? "✓ " : ""}${esc(c.winery)}: ${esc(c.name)} (${esc(c.vintage || "NV")}) – ★ ${esc(c.vivino_rating ?? "?")}
                              </option>
                            `
                            )
                            .join("")}
                        </select>
                      </div>`
                    : ""
                }
              </div>

              <form id="mobile-scan-save-form" class="form-stack">
                <div class="form-row-2">
                  <div class="field">
                    <label>Winery / Producer *</label>
                    <input class="input" name="winery" required value="${esc(f.winery)}" />
                  </div>
                  <div class="field">
                    <label>Wine / Cuvée Name *</label>
                    <input class="input" name="name" required value="${esc(f.name)}" />
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Vintage Year</label>
                    <input class="input" type="number" name="vintage" value="${esc(f.vintage)}" />
                  </div>
                  <div class="field">
                    <label>Wine Style</label>
                    <select class="select" name="wine_type">
                      ${Object.entries(WINE_TYPES)
                        .map(([k, lbl]) => `<option value="${k}" ${f.wine_type === k ? "selected" : ""}>${lbl}</option>`)
                        .join("")}
                    </select>
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Grape Variety</label>
                    <input class="input" name="varietal" value="${esc(f.varietal)}" />
                  </div>
                  <div class="field">
                    <label>Country &amp; Region</label>
                    <div class="form-row-2">
                      <input class="input" name="country" value="${esc(f.country)}" placeholder="Country" />
                      <input class="input" name="region" value="${esc(f.region)}" placeholder="Region" />
                    </div>
                  </div>
                </div>
                <div class="form-row-2">
                  <div class="field">
                    <label>Storage Area</label>
                    <input class="input" name="storage_location" list="scan-areas-dl" value="${esc(f.storage_location)}" placeholder="Wine Fridge / Cellar" />
                    <datalist id="scan-areas-dl">
                      ${this.state.areas.map((a) => `<option value="${esc(a)}"></option>`).join("")}
                    </datalist>
                  </div>
                  <div class="field">
                    <label>Quantity &amp; Price (${esc(this.state.currency)})</label>
                    <div class="form-row-2">
                      <input class="input" type="number" name="quantity" min="1" required value="${esc(f.quantity || 1)}" />
                      <input class="input" type="number" step="0.01" name="purchase_price" value="${esc(f.purchase_price)}" placeholder="Price" />
                    </div>
                  </div>
                </div>
                <div class="field">
                  <label>Bought At (Store / Winery)</label>
                  <input class="input" name="purchase_location" value="${esc(f.purchase_location)}" />
                </div>
                <button type="submit" class="btn btn-primary" style="width:100%; min-height:48px;" ${this.state.scanBusy ? "disabled" : ""}>
                  ✓ Save Scanned Wine to Cellar
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderCropSheet() {
    return `
      <div class="sheet-backdrop" id="sheet-backdrop">
        <div class="sheet-surface">
          <div class="sheet-handle"></div>
          <div class="sheet-header">
            <h2>✂️ Crop &amp; Rotate Bottle Label</h2>
            <button class="btn btn-icon" id="btn-cancel-crop">✕</button>
          </div>
          <div class="sheet-body">
            <div class="crop-stage">
              <canvas id="mobile-crop-canvas"></canvas>
            </div>
            <div style="display:flex; gap:8px; justify-content:center; margin-bottom:12px; flex-wrap:wrap;">
              <button type="button" class="btn" id="btn-crop-left">↺ Rotate Left</button>
              <button type="button" class="btn" id="btn-crop-right">↻ Rotate Right</button>
              <button type="button" class="btn" id="btn-crop-reset">Reset Frame</button>
            </div>
            <button type="button" class="btn btn-primary" id="btn-crop-confirm" style="width:100%; min-height:48px;">
              ✓ Confirm &amp; Scan Label
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _renderPreviewSheet() {
    const w = this.state.previewWine;
    if (!w || !w.image_url) return "";
    return `
      <div class="sheet-backdrop" id="sheet-backdrop" style="align-items:center; padding:16px;">
        <div class="panel-card" style="max-width:480px; width:100%; padding:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <div>
              <strong style="font-size:15px;">${esc(w.name)}</strong>
              <div style="font-size:12px; color:var(--text-muted);">${esc(w.winery)} (${esc(w.vintage || "NV")})</div>
            </div>
            <button class="btn btn-icon" id="btn-close-preview">✕</button>
          </div>
          <div style="display:flex; justify-content:center; background:#111; border-radius:12px; padding:8px;">
            <img src="${esc(w.image_url)}" alt="${esc(w.name)}" style="max-height:70dvh; max-width:100%; object-fit:contain; border-radius:8px;" />
          </div>
        </div>
      </div>
    `;
  }

  _renderInstallGuideSheet() {
    return `
      <div class="sheet-backdrop" id="sheet-backdrop">
        <div class="sheet-surface">
          <div class="sheet-handle"></div>
          <div class="scaled-zone">
            <div class="sheet-header">
              <h2>📲 Install Lekkersappie as an App</h2>
              <button class="btn btn-icon" id="btn-close-sheet">✕</button>
            </div>
            <div class="sheet-body">
              <div style="display:flex; align-items:center; gap:12px; margin-bottom:14px;">
                <img src="/lekkersappie/icon-192.png" alt="Lekkersappie" class="brand-icon" style="width:52px; height:52px;" />
                <div>
                  <strong style="font-size:16px; display:block;">Lekkersappie Wine Cellar</strong>
                  <span style="font-size:12.5px; color:var(--text-muted);">Standalone Mobile App • Parallel to Home Assistant</span>
                </div>
              </div>
              ${
                this.state.deferredPrompt
                  ? `<button class="btn btn-primary" id="btn-guide-native-install" style="width:100%; min-height:48px; margin-bottom:14px;">
                      📲 Tap Here to Install App Now
                    </button>`
                  : ""
              }
              <div class="panel-card" style="background:var(--surface-alt); margin-bottom:12px;">
                <h3 style="margin-bottom:8px;">🍏 iPhone / iPad (Safari)</h3>
                <ol style="margin:0; padding-left:18px; font-size:13.5px; line-height:1.6;">
                  <li>Tap the <strong>Share</strong> button (square with arrow pointing up) in Safari’s toolbar.</li>
                  <li>Scroll down and tap <strong>Add to Home Screen</strong>.</li>
                  <li>Tap <strong>Add</strong> in the top-right corner to launch Lekkersappie full-screen.</li>
                </ol>
              </div>
              <div class="panel-card" style="background:var(--surface-alt);">
                <h3 style="margin-bottom:8px;">🤖 Android (Chrome / Edge)</h3>
                <ol style="margin:0; padding-left:18px; font-size:13.5px; line-height:1.6;">
                  <li>Tap the browser menu <strong>⋮</strong> in the top-right corner.</li>
                  <li>Tap <strong>Install app</strong> or <strong>Add to Home screen</strong>.</li>
                </ol>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  /* ================= Main Render ================= */

  render() {
    if (!this.root) return;
    const stats = this.state.statistics || {};
    const scaleLabel = this._fontScaleLabel();

    let activeViewHtml = "";
    if (this.state.activeNav === "areas") activeViewHtml = this._renderAreasAndStatsView();
    else if (this.state.activeNav === "add") activeViewHtml = this._renderManualAddView();
    else if (this.state.activeNav === "settings") activeViewHtml = this._renderSettingsView();
    else activeViewHtml = this._renderCellarView();

    this.root.innerHTML = `
      ${
        !this.state.isOnline
          ? `<div class="offline-banner">⚡ Offline Mode — Showing cached cellar inventory</div>`
          : ""
      }
      <div class="app-shell">
        <header class="top-app-bar">
          <div class="brand-cluster">
            <img src="/lekkersappie/icon-192.png" alt="Lekkersappie" class="brand-icon" />
            <div class="brand-titles">
              <h1>${esc(this.state.cellarName)}</h1>
              <div class="brand-sub">
                <span><strong>${stats.total_bottles || 0}</strong> bottles (${stats.unique_wines || 0} wines)</span>
                ${this.state.tempDisplay ? `<span class="climate-chip">🌡️ ${esc(this.state.tempDisplay)}</span>` : ""}
                ${this.state.humidityDisplay ? `<span class="climate-chip">💧 ${esc(this.state.humidityDisplay)}</span>` : ""}
              </div>
            </div>
          </div>

          <div class="top-actions">
            <button class="btn btn-icon font-pill-btn" id="btn-top-font-scale" title="Adjust text size (S / M / L / XL)" aria-label="Text size ${scaleLabel}">
              Aa <small>${scaleLabel}</small>
            </button>
            ${
              !this.state.isInstalled
                ? `<button class="btn btn-soft" id="btn-top-install" title="Install as Mobile App">
                    📲 <span>Install</span>
                  </button>`
                : ""
            }
          </div>
        </header>

        <main class="scaled-zone">
          ${
            this.state.error
              ? `<div style="margin:12px; padding:12px; border-radius:12px; background:rgba(198,40,40,0.12); color:var(--danger); font-size:13px;">
                  ${esc(this.state.error)}
                </div>`
              : ""
          }
          ${activeViewHtml}
        </main>
      </div>

      <nav class="bottom-nav" aria-label="Mobile Navigation">
        <div class="bottom-nav-inner">
          <button class="nav-tab ${this.state.activeNav === "cellar" ? "active" : ""}" data-nav="cellar">
            <span>🍷</span>
            <span>Cellar</span>
          </button>
          <button class="nav-tab ${this.state.activeNav === "areas" ? "active" : ""}" data-nav="areas">
            <span>📍</span>
            <span>Areas</span>
          </button>
          <button class="nav-fab-scan" id="btn-nav-scan" aria-label="Scan Bottle">
            <span style="font-size:20px;">📷</span>
            <span>SCAN</span>
          </button>
          <button class="nav-tab ${this.state.activeNav === "add" ? "active" : ""}" data-nav="add">
            <span>➕</span>
            <span>Add</span>
          </button>
          <button class="nav-tab ${this.state.activeNav === "settings" ? "active" : ""}" data-nav="settings">
            <span>Aa</span>
            <span>App</span>
          </button>
        </div>
      </nav>

      ${this.state.activeSheet === "detail" ? this._renderDetailSheet() : ""}
      ${this.state.activeSheet === "scan" ? this._renderScanSheet() : ""}
      ${this.state.activeSheet === "crop" ? this._renderCropSheet() : ""}
      ${this.state.activeSheet === "preview" ? this._renderPreviewSheet() : ""}
      ${this.state.activeSheet === "install_guide" ? this._renderInstallGuideSheet() : ""}
      ${this.state.toastMessage ? `<div class="toast">${esc(this.state.toastMessage)}</div>` : ""}
    `;

    this._bindEvents();
  }

  _bindBottleCardEvents(scope) {
    scope.querySelectorAll("[data-detail-id]").forEach((el) => {
      el.addEventListener("click", () => this.openDetail(Number(el.dataset.detailId)));
    });
    scope.querySelectorAll("[data-preview-id]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const wine = this.state.wines.find((w) => Number(w.id) === Number(el.dataset.previewId));
        if (wine && wine.image_url) {
          this.state.previewWine = wine;
          this.state.previousSheet = this.state.activeSheet;
          this.state.activeSheet = "preview";
          this.render();
        } else if (wine) {
          this.openDetail(wine.id);
        }
      });
    });
    scope.querySelectorAll("[data-step-plus]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const wine = this.state.wines.find((w) => Number(w.id) === Number(btn.dataset.stepPlus));
        if (wine) this.adjustBottleStock(wine, 1);
      });
    });
    scope.querySelectorAll("[data-step-minus]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const wine = this.state.wines.find((w) => Number(w.id) === Number(btn.dataset.stepMinus));
        if (wine) this.adjustBottleStock(wine, -1);
      });
    });
    scope.querySelectorAll("[data-open-scan]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.state.scanForm = this._emptyForm();
        this.state.activeSheet = "scan";
        this.render();
      });
    });
  }

  _bindEvents() {
    const r = this.root;
    r.querySelector("#btn-top-font-scale")?.addEventListener("click", () => this.cycleFontScale());
    r.querySelector("#btn-sheet-font-scale")?.addEventListener("click", () => this.cycleFontScale());
    r.querySelector("#btn-top-install")?.addEventListener("click", () => this.handleInstallClick());
    r.querySelector("#btn-banner-install")?.addEventListener("click", () => this.handleInstallClick());
    r.querySelector("#btn-settings-install")?.addEventListener("click", () => this.handleInstallClick());
    r.querySelector("#btn-guide-native-install")?.addEventListener("click", () => this.handleInstallClick());
    r.querySelector("#btn-banner-dismiss")?.addEventListener("click", () => {
      this.state.installBannerDismissed = true;
      this.render();
    });

    // Bottom navigation
    r.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.state.activeNav = btn.dataset.nav;
        this.render();
      });
    });
    r.querySelector("#btn-nav-scan")?.addEventListener("click", () => {
      this.state.scanForm = this._emptyForm();
      this.state.scanError = "";
      this.state.activeSheet = "scan";
      this.render();
    });

    // Search & filter in Cellar view
    const searchInput = r.querySelector("#mobile-search-input");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this.state.searchQuery = e.target.value;
        clearTimeout(this._searchDebounce);
        this._searchDebounce = setTimeout(() => this.refreshBottleListOnly(), 120);
      });
      searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") searchInput.blur();
      });
    }
    r.querySelector("#btn-mobile-clear-search")?.addEventListener("click", () => {
      this.state.searchQuery = "";
      const inp = r.querySelector("#mobile-search-input");
      if (inp) {
        inp.value = "";
        inp.focus();
      }
      this.refreshBottleListOnly();
    });
    r.querySelector("#mobile-sort-select")?.addEventListener("change", (e) => {
      this.state.sortBy = e.target.value;
      this.render();
    });
    r.querySelectorAll(".filter-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        this.state.filterTab = pill.dataset.tab;
        this.render();
      });
    });
    r.querySelector("#btn-clear-area-filter")?.addEventListener("click", () => {
      this.state.areaFilter = "";
      this.render();
    });

    this._bindBottleCardEvents(r);

    // Areas view jump
    r.querySelectorAll("[data-jump-area]").forEach((tile) => {
      tile.addEventListener("click", () => {
        this.state.areaFilter = tile.dataset.jumpArea || "";
        this.state.activeNav = "cellar";
        this.render();
      });
    });

    // Settings view controls
    r.querySelectorAll("[data-set-scale]").forEach((b) => {
      b.addEventListener("click", () => this.setFontScale(parseFloat(b.dataset.setScale)));
    });
    r.querySelectorAll("[data-set-theme]").forEach((b) => {
      b.addEventListener("click", () => this.setTheme(b.dataset.setTheme));
    });
    r.querySelector("#btn-settings-refresh-vivino")?.addEventListener("click", async () => {
      try {
        this.showToast("Refreshing Vivino ratings…");
        await this.apiPost("refresh_vivino", {});
        await this.fetchState();
        this.showToast("Vivino ratings refreshed!");
      } catch (err) {
        alert(`Vivino refresh failed: ${err?.message || err}`);
      }
    });

    // Manual add form
    const manualForm = r.querySelector("#mobile-manual-add-form");
    if (manualForm) {
      manualForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(manualForm);
        const payload = Object.fromEntries(fd.entries());
        payload.quantity = Number(payload.quantity || 1);
        if (payload.vintage) payload.vintage = Number(payload.vintage);
        else delete payload.vintage;
        if (payload.purchase_price) payload.purchase_price = Number(payload.purchase_price);
        else delete payload.purchase_price;
        if (payload.drink_from_year) payload.drink_from_year = Number(payload.drink_from_year);
        else delete payload.drink_from_year;
        if (payload.drink_until_year) payload.drink_until_year = Number(payload.drink_until_year);
        else delete payload.drink_until_year;
        try {
          await this.apiPost("add", payload);
          this.state.scanForm = this._emptyForm();
          this.state.activeNav = "cellar";
          await this.fetchState();
          this.showToast("Wine added to cellar!");
        } catch (err) {
          alert(`Failed to add wine: ${err?.message || err}`);
        }
      });
    }

    // Sheet close handlers
    r.querySelector("#btn-close-sheet")?.addEventListener("click", () => {
      this.state.activeSheet = null;
      this.render();
    });
    r.querySelector("#btn-close-preview")?.addEventListener("click", () => {
      this.state.activeSheet = this.state.previousSheet || null;
      this.state.previewWine = null;
      this.render();
    });
    r.querySelector("#sheet-backdrop")?.addEventListener("click", (e) => {
      if (e.target.id === "sheet-backdrop") {
        this.state.activeSheet = null;
        this.render();
      }
    });

    // Detail sheet handlers
    r.querySelector("#btn-detail-zoom-img")?.addEventListener("click", () => {
      this.state.previewWine = this.state.detailWine;
      this.state.previousSheet = "detail";
      this.state.activeSheet = "preview";
      this.render();
    });
    r.querySelector("#btn-detail-plus")?.addEventListener("click", () => {
      if (this.state.detailWine) this.adjustBottleStock(this.state.detailWine, 1);
    });
    r.querySelector("#btn-detail-minus")?.addEventListener("click", () => {
      if (this.state.detailWine) this.adjustBottleStock(this.state.detailWine, -1);
    });
    r.querySelector("#btn-detail-research")?.addEventListener("click", () => this._runResearch());
    r.querySelector("#btn-detail-reresearch")?.addEventListener("click", () => this._runResearch());
    r.querySelector("#btn-mobile-unlink-vivino")?.addEventListener("click", async () => {
      const w = this.state.detailWine;
      if (!w) return;
      if (!window.confirm(`Remove Vivino link and rating from "${w.name}"?`)) return;
      try {
        const res = await this.apiPost("unlink_vivino", { wine_id: w.id });
        this.state.detailWine = res.wine;
        await this.fetchState();
        this.showToast("Vivino link removed");
      } catch (err) {
        alert(`Failed to unlink Vivino: ${err?.message || err}`);
      }
    });
    r.querySelector("#btn-mobile-link-vivino")?.addEventListener("click", async () => {
      const w = this.state.detailWine;
      const inp = r.querySelector("#mobile-vivino-url-input");
      const url = (inp?.value || "").trim();
      if (!w || !url) return;
      this.state.linkingVivinoId = w.id;
      this.state.vivinoLinkError = "";
      this.render();
      try {
        const res = await this.apiPost("link_vivino", { wine_id: w.id, url });
        this.state.linkingVivinoId = null;
        if (res.wine) this.state.detailWine = res.wine;
        await this.fetchState();
        this.showToast("Vivino link updated!");
      } catch (err) {
        this.state.linkingVivinoId = null;
        this.state.vivinoLinkError = err?.message || "Could not link Vivino URL";
        this.render();
      }
    });
    r.querySelector("#btn-mobile-delete-wine")?.addEventListener("click", async () => {
      const w = this.state.detailWine;
      if (!w) return;
      const ok = window.confirm(
        `⚠️ WARNING: Permanently delete "${w.winery} – ${w.name}" from your cellar database?\n\nThis action CANNOT be undone.`
      );
      if (!ok) return;
      try {
        await this.apiPost("delete", { wine_id: w.id });
        this.state.activeSheet = null;
        this.state.detailWine = null;
        await this.fetchState();
        this.showToast("Wine deleted");
      } catch (err) {
        alert(`Delete failed: ${err?.message || err}`);
      }
    });

    const detailForm = r.querySelector("#mobile-detail-form");
    if (detailForm) {
      detailForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const w = this.state.detailWine;
        if (!w) return;
        const fd = new FormData(detailForm);
        const updates = Object.fromEntries(fd.entries());
        updates.vintage = updates.vintage ? Number(updates.vintage) : null;
        updates.purchase_price = updates.purchase_price !== "" ? Number(updates.purchase_price) : null;
        updates.drink_from_year = updates.drink_from_year ? Number(updates.drink_from_year) : null;
        updates.drink_until_year = updates.drink_until_year ? Number(updates.drink_until_year) : null;
        updates.personal_rating = updates.personal_rating ? Number(updates.personal_rating) : null;
        try {
          const res = await this.apiPost("update", { wine_id: w.id, updates });
          if (res.wine) this.state.detailWine = res.wine;
          await this.fetchState();
          this.showToast("Wine details saved!");
        } catch (err) {
          alert(`Save failed: ${err?.message || err}`);
        }
      });
    }

    // Scanner & Crop handlers
    r.querySelector("#mobile-scan-file")?.addEventListener("change", (e) => this._onScanFilePicked(e));
    r.querySelector("#btn-reopen-crop")?.addEventListener("click", () => {
      this.state.activeSheet = "crop";
      this.render();
    });
    r.querySelector("#mobile-vivino-candidate")?.addEventListener("change", (e) => {
      this._selectScanCandidate(Number(e.target.value));
    });
    const scanSaveForm = r.querySelector("#mobile-scan-save-form");
    if (scanSaveForm) {
      scanSaveForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(scanSaveForm);
        const payload = { ...this.state.scanForm, ...Object.fromEntries(fd.entries()) };
        payload.quantity = Number(payload.quantity || 1);
        payload.vintage = payload.vintage ? Number(payload.vintage) : null;
        payload.purchase_price = payload.purchase_price ? Number(payload.purchase_price) : null;
        try {
          await this.apiPost("add", payload);
          this.state.activeSheet = null;
          await this.fetchState();
          this.showToast("Scanned bottle saved!");
        } catch (err) {
          alert(`Save failed: ${err?.message || err}`);
        }
      });
    }

    if (this.state.activeSheet === "crop") {
      this._initCropCanvas();
      r.querySelector("#btn-cancel-crop")?.addEventListener("click", () => {
        this.state.activeSheet = "scan";
        this.render();
      });
      r.querySelector("#btn-crop-left")?.addEventListener("click", () => this._rotateCrop(-90));
      r.querySelector("#btn-crop-right")?.addEventListener("click", () => this._rotateCrop(90));
      r.querySelector("#btn-crop-reset")?.addEventListener("click", () => {
        if (this.state.cropState) {
          this.state.cropState.crop = { x: 0.08, y: 0.08, w: 0.84, h: 0.84 };
          this._drawCropCanvas();
        }
      });
      r.querySelector("#btn-crop-confirm")?.addEventListener("click", () => this._confirmCropAndRunScan());
    }
  }

  async _runResearch() {
    const w = this.state.detailWine;
    if (!w) return;
    this.state.researchingWineId = w.id;
    this.state.researchError = "";
    this.render();
    try {
      const res = await this.apiPost("research", { wine_id: w.id });
      this.state.researchingWineId = null;
      if (res.wine) this.state.detailWine = res.wine;
      await this.fetchState();
      this.showToast("AI wine research complete!");
    } catch (err) {
      this.state.researchingWineId = null;
      this.state.researchError = err?.message || "Research failed.";
      this.render();
    }
  }

  _onScanFilePicked(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        this.state.cropState = {
          image: img,
          rotation: 0,
          crop: { x: 0.08, y: 0.08, w: 0.84, h: 0.84 },
        };
        this.state.activeSheet = "crop";
        this.render();
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  }

  _rotateCrop(deg) {
    if (!this.state.cropState) return;
    this.state.cropState.rotation = (this.state.cropState.rotation + deg + 360) % 360;
    this._drawCropCanvas();
  }

  _initCropCanvas() {
    this._drawCropCanvas();
  }

  _drawCropCanvas() {
    const canvas = this.root.querySelector("#mobile-crop-canvas");
    const cs = this.state.cropState;
    if (!canvas || !cs?.image) return;
    const ctx = canvas.getContext("2d");
    const rot = cs.rotation % 360;
    const swapped = rot === 90 || rot === 270;
    const srcW = swapped ? cs.image.height : cs.image.width;
    const srcH = swapped ? cs.image.width : cs.image.height;
    const maxDim = 320;
    const scale = Math.min(maxDim / srcW, maxDim / srcH, 1);
    canvas.width = Math.round(srcW * scale);
    canvas.height = Math.round(srcH * scale);

    ctx.save();
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate((rot * Math.PI) / 180);
    const drawW = swapped ? canvas.height : canvas.width;
    const drawH = swapped ? canvas.width : canvas.height;
    ctx.drawImage(cs.image, -drawW / 2, -drawH / 2, drawW, drawH);
    ctx.restore();

    const cx = cs.crop.x * canvas.width;
    const cy = cs.crop.y * canvas.height;
    const cw = cs.crop.w * canvas.width;
    const ch = cs.crop.h * canvas.height;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2.5;
    ctx.strokeRect(cx, cy, cw, ch);
  }

  async _confirmCropAndRunScan() {
    const cs = this.state.cropState;
    if (!cs?.image) return;
    const rot = cs.rotation % 360;
    const swapped = rot === 90 || rot === 270;
    const srcW = swapped ? cs.image.height : cs.image.width;
    const srcH = swapped ? cs.image.width : cs.image.height;

    const rotCanvas = document.createElement("canvas");
    rotCanvas.width = srcW;
    rotCanvas.height = srcH;
    const rctx = rotCanvas.getContext("2d");
    rctx.translate(srcW / 2, srcH / 2);
    rctx.rotate((rot * Math.PI) / 180);
    rctx.drawImage(cs.image, -cs.image.width / 2, -cs.image.height / 2);

    const outCanvas = document.createElement("canvas");
    const cw = Math.max(1, Math.round(cs.crop.w * srcW));
    const ch = Math.max(1, Math.round(cs.crop.h * srcH));
    const maxOut = 1280;
    const scale = Math.min(maxOut / cw, maxOut / ch, 1);
    outCanvas.width = Math.round(cw * scale);
    outCanvas.height = Math.round(ch * scale);
    outCanvas
      .getContext("2d")
      .drawImage(
        rotCanvas,
        Math.round(cs.crop.x * srcW),
        Math.round(cs.crop.y * srcH),
        cw,
        ch,
        0,
        0,
        outCanvas.width,
        outCanvas.height
      );

    const dataUrl = outCanvas.toDataURL("image/jpeg", 0.88);
    this.state.scanImageData = dataUrl;
    this.state.activeSheet = "scan";
    this.state.scanBusy = true;
    this.state.scanError = "";
    this.render();

    try {
      const res = await this.apiPost("scan", { image_data: dataUrl });
      const rec = res.recognized || {};
      this.state.scanCandidates = res.vivino_candidates || [];
      this.state.scanConfidence = res.vivino_match_confidence || "none";
      this.state.scanSuggestedIndex = res.vivino_suggested_index ?? -1;
      this.state.selectedCandidateIdx = this.state.scanConfidence === "high" ? 0 : -1;
      this.state.scanForm = {
        ...this._emptyForm(),
        winery: rec.winery || "",
        name: rec.name || "",
        vintage: rec.vintage ?? "",
        wine_type: rec.wine_type || "red",
        varietal: rec.varietal || "",
        region: rec.region || "",
        country: rec.country || "",
        vivino_rating: rec.vivino_rating ?? "",
        vivino_ratings_count: rec.vivino_ratings_count ?? null,
        vivino_url: rec.vivino_url || "",
        vivino_wine_id: rec.vivino_wine_id ?? null,
        vivino_match_confidence: rec.vivino_match_confidence || "",
        drink_from_year: rec.drink_from_year ?? "",
        drink_until_year: rec.drink_until_year ?? "",
        drink_window_note: rec.drink_window_note || "",
        general_notes: rec.general_notes || "",
        image_url: rec.image_url || "",
      };
    } catch (err) {
      this.state.scanError = err?.message || "Bottle recognition failed.";
    } finally {
      this.state.scanBusy = false;
      this.render();
    }
  }

  _selectScanCandidate(idx) {
    this.state.selectedCandidateIdx = idx;
    if (idx < 0 || !this.state.scanCandidates[idx]) {
      this.state.scanForm.vivino_rating = "";
      this.state.scanForm.vivino_url = "";
      this.state.scanForm.vivino_wine_id = null;
      this.state.scanForm.vivino_match_confidence = "";
    } else {
      const c = this.state.scanCandidates[idx];
      this.state.scanForm.vivino_rating = c.vivino_rating ?? "";
      this.state.scanForm.vivino_url = c.vivino_url || "";
      this.state.scanForm.vivino_wine_id = c.vivino_wine_id ?? null;
      this.state.scanForm.vivino_match_confidence = "confirmed";
    }
    this.render();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("lekkersappie-mobile-root");
  if (root) {
    window.lekkersappieApp = new LekkersappieMobileApp(root);
  }
});
