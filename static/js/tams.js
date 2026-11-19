/* TAMS shared JS: notification polling + Leaflet helpers. No build step. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ polling
  function initPolling() {
    const body = document.body;
    const url = body.dataset.pollUrl;
    if (!url) return;
    const interval = parseInt(body.dataset.pollMs || "30000", 10);
    let lastSeen = parseInt(body.dataset.unread || "0", 10);
    const badge = document.getElementById("notif-badge");
    const banner = document.getElementById("notif-banner");
    const bannerCount = document.getElementById("notif-banner-count");

    function render(count) {
      if (badge) { badge.textContent = count; badge.classList.toggle("d-none", count === 0); }
      if (banner) { banner.classList.toggle("d-none", count === 0); }
      if (bannerCount) { bannerCount.textContent = count; }
      document.querySelectorAll(".js-unread").forEach(function (el) { el.textContent = count; el.classList.toggle("d-none", count === 0); });
      document.title = document.title.replace(/^\(\d+\)\s*/, "");
      if (count > 0) document.title = "(" + count + ") " + document.title;
    }

    function toast(item) {
      const c = document.getElementById("notif-toast-container");
      if (!c || !window.bootstrap) return;
      const el = document.createElement("div");
      el.className = "toast align-items-center text-bg-dark border-0";
      el.setAttribute("role", "status");
      const inner = document.createElement("div");
      inner.className = "d-flex";
      const b = document.createElement("div");
      b.className = "toast-body";
      b.textContent = item.message;
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "btn-close btn-close-white me-2 m-auto";
      btn.setAttribute("data-bs-dismiss", "toast");
      inner.append(b, btn); el.append(inner); c.append(el);
      new bootstrap.Toast(el, { delay: 8000 }).show();
    }

    async function poll() {
      if (document.hidden) return;
      try {
        const res = await fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" });
        if (!res.ok) return;
        const data = await res.json();
        if (data.unread > lastSeen && data.latest && data.latest.length) {
          data.latest.slice(0, data.unread - lastSeen).reverse().forEach(toast);
        }
        lastSeen = data.unread;
        render(data.unread);
      } catch (e) { /* offline: try again next tick */ }
    }
    render(lastSeen);
    setInterval(poll, interval);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  }

  // ------------------------------------------------------------------ map
  const STATUS_COLORS = {
    reported: "#f59e0b", verified: "#ef4444", assigned: "#3b82f6", resolved: "#10b981", stale: "#94a3b8",
  };
  const SEVERITY_COLORS = { low: "#06b6d4", medium: "#f97316", high: "#ef4444", closed: "#0f172a" };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function baseMap(el, center, zoom) {
    const map = L.map(el).setView(center || [0, 0], zoom || 13);
    const ds = document.body.dataset;
    L.tileLayer(ds.tileUrl || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: ds.tileAttribution || "&copy; OpenStreetMap contributors",
      // OSM tile policy: requests must carry a Referer identifying the site.
      referrerPolicy: "strict-origin-when-cross-origin",
    }).addTo(map);
    return map;
  }

  function drawZones(map, zones, opts) {
    const layer = L.layerGroup();
    zones.forEach(function (z) {
      L.circle([z.center_lat, z.center_lng], {
        radius: z.radius_m, color: "#6366f1", weight: 1.5, opacity: .6, dashArray: "5 5", fillColor: "#6366f1", fillOpacity: opts && opts.fill ? 0.07 : 0,
      }).bindTooltip(escapeHtml(z.name)).addTo(layer);
    });
    return layer.addTo(map);
  }

  function drawIncidents(map, incidents) {
    const layer = L.layerGroup();
    incidents.forEach(function (i) {
      const stale = i.status === "stale";
      L.circleMarker([i.lat, i.lng], {
        radius: stale ? 7 : 9, color: "#fff", weight: 2,
        fillColor: STATUS_COLORS[i.status] || "#666", fillOpacity: stale ? 0.45 : 0.95,
        dashArray: stale ? "2 3" : null,
      }).bindPopup(
        "<strong>" + escapeHtml(i.type_label) + "</strong> · " + escapeHtml(i.status_label) +
        (stale ? " <em>(not re-confirmed)</em>" : "") +
        "<br><small>" + escapeHtml(i.zone) + "</small><br>" + escapeHtml(i.description) +
        '<br><a href="' + i.url + '">Open incident #' + i.id + "</a>"
      ).addTo(layer);
    });
    return layer.addTo(map);
  }

  function drawBlockages(map, blockages) {
    const layer = L.layerGroup();
    blockages.forEach(function (b) {
      const needs = b.status === "needs_reconfirmation";
      L.circle([b.lat, b.lng], {
        radius: b.radius_m, color: SEVERITY_COLORS[b.severity] || "#dc3545", weight: 2,
        fillOpacity: needs ? 0.12 : 0.28, dashArray: needs ? "8 6" : null,
      }).bindPopup(
        "<strong>Blockage:</strong> " + escapeHtml(b.severity_label) + "<br>" + escapeHtml(b.zone) +
        " · " + escapeHtml(b.status_label) + "<br>" + escapeHtml(b.reason) +
        '<br><a href="' + b.url + '">Open blockage #' + b.id + "</a>"
      ).addTo(layer);
    });
    return layer.addTo(map);
  }

  function drawRoutes(map, routes) {
    const layer = L.layerGroup();
    (routes || []).forEach(function (r) {
      L.polyline(r.points, { color: "#8b5cf6", weight: 5, opacity: 0.85, lineCap: "round" }).bindTooltip(escapeHtml(r.name)).addTo(layer);
    });
    return layer.addTo(map);
  }

  /** Full operational map from /api/map-data/. */
  async function loadOpsMap(el, opts) {
    opts = opts || {};
    // Fetch data first so the map opens directly on the city (no wasted tile requests at 0,0).
    const res = await fetch(el.dataset.src + (opts.resolved ? "?resolved=1" : ""), { credentials: "same-origin" });
    const data = await res.json();
    const first = data.zones[0];
    const map = baseMap(el, opts.center || (first ? [first.center_lat, first.center_lng] : [0, 0]), opts.zoom);
    const zones = drawZones(map, data.zones, { fill: false });
    const blk = drawBlockages(map, data.blockages);
    const inc = drawIncidents(map, data.incidents);
    const routes = drawRoutes(map, data.routes);
    L.control.layers(null, { "Zones": zones, "Blockages": blk, "Incidents": inc, "My routes": routes }, { collapsed: false }).addTo(map);
    const pts = data.incidents.map(function (i) { return [i.lat, i.lng]; })
      .concat(data.zones.map(function (z) { return [z.center_lat, z.center_lng]; }));
    if (!opts.center && pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.15));
    return map;
  }

  window.TAMS = { baseMap, drawZones, drawIncidents, drawBlockages, drawRoutes, loadOpsMap, STATUS_COLORS, SEVERITY_COLORS };

  document.addEventListener("DOMContentLoaded", function () {
    initPolling();
    document.querySelectorAll("[data-ops-map]").forEach(function (el) {
      loadOpsMap(el, { zoom: 13 });
    });
  });
})();
