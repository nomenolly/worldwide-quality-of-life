/* Worldwide Quality of Life Map, WQL-003 global reference preview.
 * Plain script, no build step. Reads the files pipeline/global_build.py writes to data/.
 *
 * Four controls: locality, indicator, observation date, evidence.
 * The heatmap is the compression; the locality inspector is its decompression:
 * click anywhere on Earth and it lists every ingested observation for that place,
 * then every reference indicator it does not know, and why.
 */
(function () {
  "use strict";

  const SEQ = ["#fde725", "#a0da39", "#4ac16d", "#1fa187", "#277f8e", "#365c8d", "#46327e", "#440154"]; // viridis, light = low
  const DIV = ["#8c510a", "#bf812d", "#dfc27d", "#f0ead6", "#c7eae5", "#80cdc1", "#35978f", "#01665e"]; // BrBG
  const DIM_LABEL = { recency: "Recency", directness: "Directness", spatial_fidelity: "Spatial fidelity",
    coverage: "Coverage", validation: "Validation", interval: "Interval" };
  const STATUS_WORD = { ingested: "on the map", next: "next to ingest", blocked: "blocked", prospective: "prospective (licence)" };
  const ORDER = "ABCD";

  // Evidence ("basis") view: what each absence or note code means for the map.
  const BASIS = {
    known: { label: "Value", color: "#3b7dd8" },
    caveat: { label: "Value with a caveat (see inspector)", color: "#9cc3f0" },
    zero_land: { label: "Modelled zero, on land", color: "#c8c1a6" },
    zero_water: { label: "Modelled zero, on water", color: "#d5e4ea" },
    none: { label: "No estimate here (source makes none)", pattern: "light" },
    extent: { label: "Outside the source's extent", pattern: "dense" },
  };
  const CODE_BASIS = { "": "known", ghsl_partial_water: "caveat", map_unweighted: "caveat", map_on_water: "caveat",
    land_over_100: "caveat", ghsl_zero_land: "zero_land", ghsl_zero_water: "zero_water", wp_nodata: "none",
    map_nodata: "none", d_missing: "none", d_small: "none", wp_extent: "extent", map_extent: "extent", ghsl_extent: "extent" };

  let META, LAYERS, map, drawLayer, marker, renderer;
  const state = { layer: null, evidence: "value", sel: null };
  const cache = new Map();

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (v) => {
    if (v === undefined || v === null || v === "") return "";
    const a = Math.abs(v);
    if (a >= 1000) return Math.round(v).toLocaleString("en");
    if (a >= 100) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1).replace(/\.0$/, "");
    if (a >= 1 || a === 0) return (+v.toFixed(2)).toString();
    return (+v.toPrecision(2)).toString();
  };
  const weakest = (g) => Object.values(g).reduce((w, x) => (ORDER.indexOf(x) > ORDER.indexOf(w) ? x : w), "A");
  const layerById = (id) => LAYERS.find((l) => l.id === id);

  // ------------------------------------------------------------ data files
  function getJSON(path) {
    if (!cache.has(path)) {
      cache.set(path, fetch(path).then((r) => {
        if (r.status === 404) return null; // no file: no source touches any cell under this parent
        if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
        return r.json();
      }).then((d) => {
        if (d && d.cells) { d.index = new Map(d.cells.map((c, i) => [c, i])); }
        return d;
      }));
    }
    return cache.get(path);
  }
  function displayRes(z) { return z < 3 ? 2 : z < 5 ? 3 : z < 7 ? 4 : META.build.inspect_res; }
  function shardPath(res, cell) {
    if (res === META.build.inspect_res) return `data/r${res}/${h3.cellToParent(cell, META.build.shard_res)}.json`;
    const d = META.counts.display[String(res)];
    if (d.file) return `data/${d.file}`;
    return `data/${d.folder}/${h3.cellToParent(cell, d.shard_res)}.json`;
  }
  function shardResFor(res) {
    if (res === META.build.inspect_res) return META.build.shard_res;
    const d = META.counts.display[String(res)];
    return d.file ? -1 : d.shard_res;
  }

  // Viewport as polygons in -180..180 (split at the antimeridian).
  function viewPolys() {
    const b = map.getBounds();
    const s = Math.max(-85, b.getSouth()), n = Math.min(85, b.getNorth());
    let w = b.getWest(), e = b.getEast();
    if (e - w >= 360) return [[[s, -180], [s, 0], [s, 180], [n, 180], [n, 0], [n, -180]]];
    const k = Math.floor((w + 180) / 360);
    w -= 360 * k; e -= 360 * k;
    const box = (a, c) => [[s, a], [s, c], [n, c], [n, a]];
    return e > 180 ? [box(w, 180), box(-180, e - 360)] : [box(w, e)];
  }
  function visibleShards(res) {
    const sr = shardResFor(res);
    if (sr < 0) return [shardPath(res, null)];
    const set = new Set();
    for (const poly of viewPolys()) {
      for (const c of h3.polygonToCells(poly, Math.min(sr + 2, 15))) set.add(h3.cellToParent(c, sr));
      // edge samples catch shards whose centres lie outside the view
      const [s, w] = poly[0], [n, e] = poly[2];
      for (let i = 0; i <= 16; i++) {
        const f = i / 16;
        for (const [la, ln] of [[s, w + f * (e - w)], [n, w + f * (e - w)], [s + f * (n - s), w], [s + f * (n - s), e]]) {
          set.add(h3.latLngToCell(la, ln, sr));
        }
      }
    }
    return [...set].map((p) => `data/r${res}/${p}.json`);
  }

  // ------------------------------------------------------------ styling
  const patterns = {};
  function makePattern(kind) {
    const c = document.createElement("canvas");
    c.width = c.height = 8;
    const x = c.getContext("2d");
    x.fillStyle = css("--absent-bg");
    x.fillRect(0, 0, 8, 8);
    x.strokeStyle = css("--absent-line");
    x.lineWidth = kind === "dense" ? 2.2 : 1.2;
    x.beginPath();
    x.moveTo(0, 8); x.lineTo(8, 0);
    x.moveTo(-2, 2); x.lineTo(2, -2);
    x.moveTo(6, 10); x.lineTo(10, 6);
    x.stroke();
    return x.createPattern(c, "repeat");
  }
  function scaleFor(L) {
    const s = L.scale;
    const pal = s.type === "diverging" ? DIV : SEQ;
    const breaks = s.breaks;
    const colors = pal.slice(pal.length - breaks.length - 1);
    return { breaks, colors, color(v) { let i = 0; while (i < breaks.length && v >= breaks[i]) i++; return colors[i]; } };
  }
  function fillFor(L, v, code) {
    if (state.evidence === "basis") {
      const b = BASIS[CODE_BASIS[code ?? (v === null ? "d_missing" : "")] || (v === null ? "none" : "known")];
      return b.pattern ? patterns[b.pattern] : b.color;
    }
    if (v === null || v === undefined) return patterns[CODE_BASIS[code] === "extent" ? "dense" : "light"];
    if (v === 0 && L.id.startsWith("pop.") && L.id !== "pop.disagreement") return css("--zero");
    return scaleFor(L).color(v);
  }

  // ------------------------------------------------------------ legend
  function periodText(L) {
    const p = L.reference_period;
    const a = p[0].slice(0, 4), b = p[1].slice(0, 4);
    return a === b ? a : `${a}–${b}`;
  }
  function legendHTML(L, res) {
    const parts = [`<span><strong>${esc(L.label)}</strong> (${esc(L.unit)})</span>`];
    if (state.evidence === "basis") {
      for (const k in BASIS) {
        const b = BASIS[k];
        const sw = b.pattern ? `<i class="sw absent"${b.pattern === "dense" ? ' style="filter:contrast(1.6)"' : ""}></i>` : `<i class="sw" style="background:${b.color}"></i>`;
        parts.push(`<span>${sw}${esc(b.label)}</span>`);
      }
    } else {
      const s = scaleFor(L);
      const lab = (i) => i === 0 ? `&lt; ${fmt(s.breaks[0])}` : i === s.breaks.length ? `≥ ${fmt(s.breaks[i - 1])}` : `${fmt(s.breaks[i - 1])} to ${fmt(s.breaks[i])}`;
      if (L.id.startsWith("pop.") && L.id !== "pop.disagreement") parts.push(`<span><i class="sw" style="background:var(--zero)"></i>0 (modelled)</span>`);
      s.colors.forEach((c, i) => parts.push(`<span><i class="sw" style="background:${c}"></i>${lab(i)}</span>`));
      parts.push(`<span><i class="sw absent"></i>no value (inspector says why)</span>`);
      parts.push(`<span>${L.scale.type === "diverging" ? "Brown: WorldPop lower than GHSL. Teal: WorldPop higher." : "Fixed classes for the whole globe, for display only."} No colour means better or worse.</span>`);
    }
    parts.push(`<span><i class="sw untouched"></i>not drawn: no source has land, residents or a value here</span>`);
    parts.push(`<span><strong>When:</strong> ${esc(periodText(L))}; other indicators describe other years.${L.upstream_epochs ? " " + esc(L.upstream_epochs) : ""}</span>`);
    parts.push(`<span><strong>Measured on:</strong> ${esc(L.native_grain.split(";")[0])}. Drawn on H3 resolution-${res} cells, an index for display, not a precision claim.</span>`);
    return parts.join("");
  }

  // ------------------------------------------------------------ drawing
  let drawToken = 0;
  async function draw() {
    const token = ++drawToken;
    const res = displayRes(map.getZoom());
    const L = layerById(state.layer);
    $("#legend").innerHTML = legendHTML(L, res);
    const avg = { 2: "86,800", 3: "12,400", 4: "1,770", 5: "253" }[res] || "";
    $("#zoomnote").textContent = `Drawing H3 resolution ${res} (about ${avg} km² average per cell)` +
      (res < META.build.inspect_res ? `. Zoom in for resolution ${META.build.inspect_res}; the inspector always reports resolution ${META.build.inspect_res}.` : ".");
    const files = await Promise.all(visibleShards(res).map((p) => getJSON(p).catch(() => null)));
    if (token !== drawToken) return;
    const b = map.getBounds().pad(0.15);
    const k = Math.round(map.getCenter().lng / 360) * 360;
    const group = L_layerGroup();
    for (const d of files) {
      if (!d) continue;
      const vals = d.v[state.layer], why = d.why ? d.why[state.layer] : null;
      for (let i = 0; i < d.cells.length; i++) {
        const c = d.cells[i];
        const [la, ln] = h3.cellToLatLng(c);
        if (la < b.getSouth() - 3 || la > b.getNorth() + 3) continue;
        const lnk = ln + k;
        if (b.getEast() - b.getWest() < 300 && (lnk < b.getWest() - 6 || lnk > b.getEast() + 6)) continue;
        const ring = h3.cellToBoundary(c);
        const span = Math.max(...ring.map((p) => p[1])) - Math.min(...ring.map((p) => p[1]));
        const pts = ring.map(([a, o]) => [a, (span > 180 && o < 0 ? o + 360 : o) + k]);
        group.addLayer(window.L.polygon(pts, { renderer, interactive: false, weight: res >= 5 ? 0.3 : 0.15,
          color: "rgba(80,80,80,.45)", fillOpacity: 0.78, fillColor: fillFor(L, vals[i], why ? why[i] : undefined) }));
      }
    }
    if (drawLayer) map.removeLayer(drawLayer);
    drawLayer = group.addTo(map);
  }
  const L_layerGroup = () => window.L.layerGroup();

  // ------------------------------------------------------------ inspector
  function sourceBlock(sid) {
    const s = META.sources[sid];
    if (!s) return "";
    return `<dl class="kv">
      <dt>Source</dt><dd><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a></dd>
      <dt>Publisher</dt><dd>${esc(s.publisher)}</dd>
      <dt>Licence</dt><dd>${esc(s.licence)} <span class="meta">(checked ${esc(s.licence_checked)})</span></dd>
      <dt>Cite</dt><dd>${esc(s.citation)}</dd>
      <dt>Source notes</dt><dd>${esc(s.grade_notes)}</dd></dl>`;
  }
  function refFor(L) { return META.references.find((r) => r.id === L.reference); }

  function knownCard(L, v, code, x) {
    const ref = refFor(L);
    const active = L.id === state.layer ? " active" : "";
    let h = `<div class="obs${active}" data-layer="${esc(L.id)}"><h3>${esc(L.label)}</h3>`;
    if (ref) h += `<div class="lim">Reveals <strong>${esc(ref.reveals.toLowerCase())}</strong>. ${esc(ref.limitation)}.</div>`;
    const gd = L.grade_detail, w = weakest(gd);
    h += `<div class="val">${fmt(v)} <span class="meta">${esc(L.unit)}</span></div>`;
    h += `<span class="badge">${esc(L.status)}</span><span class="badge">applies to ${esc(periodText(L))}</span>`;
    h += `<span class="badge grade" title="Weakest of the six evidence dimensions. A flag, not a score.">weakest evidence: ${w}</span>`;
    h += `<dl class="kv">`;
    if (code && META.notes[code]) h += `<dt>Note</dt><dd>${esc(META.notes[code])}</dd>`;
    if (x) {
      if (L.id === "pop.ghsl") h += `<dt>People</dt><dd>${fmt(x.g_c)} modelled in this cell</dd><dt>Behind this value</dt><dd>${x.g_n.toLocaleString("en")} GHSL pixels with modelled residents (pixels modelling no one are not counted)</dd>`;
      if (L.id === "pop.worldpop") h += `<dt>People</dt><dd>${fmt(x.w_c)} modelled in this cell</dd><dt>Behind this value</dt><dd>${x.w_n.toLocaleString("en")} WorldPop pixels with a value</dd>`;
      if (L.id === "pop.disagreement") h += `<dt>The two estimates</dt><dd>WorldPop ${fmt(x.w_c)}, GHSL ${fmt(x.g_c)} people; difference ${x.w_c - x.g_c > 0 ? "+" : ""}${fmt(x.w_c - x.g_c)} (WorldPop minus GHSL)</dd>`;
      if (L.id === "acc.motor") h += `<dt>Within-cell spread</dt><dd>${fmt(x.m_min)} to ${fmt(x.m_max)} min (spread across pixels, not uncertainty)</dd><dt>Behind this value</dt><dd>${x.m_n.toLocaleString("en")} MAP pixels</dd>`;
      if (L.id === "geo.land") h += `<dt>Behind this value</dt><dd>${x.land_n.toLocaleString("en")} GHS-LAND pixels holding land</dd>`;
    }
    h += `<dt>Measured on</dt><dd>${esc(L.native_grain)}</dd>`;
    h += `<dt>Kind of number</dt><dd>${esc(L.statistic)}</dd>`;
    if (L.depends_on) h += `<dt>Not independent of</dt><dd>${esc(L.depends_on)}</dd>`;
    h += `<dt>Reference period</dt><dd>${esc(L.reference_period[0])} to ${esc(L.reference_period[1])}</dd></dl>`;
    h += `<details><summary>Evidence grade by dimension</summary><table class="grades">` +
      Object.keys(DIM_LABEL).map((d) => `<tr><td>${DIM_LABEL[d]}</td><td class="${gd[d] === w ? "weak" : ""}">${gd[d]}</td></tr>`).join("") +
      `</table><p class="meta">Source-level grades. Per-cell lowering (for example for old censuses) is not yet applied in the global build.</p></details>`;
    h += `<details><summary>How this value was made</summary><ol>${L.lineage.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>`;
    h += `<details><summary>Caveat and source</summary><p>${esc(L.caveat)}</p>${L.source_id ? sourceBlock(L.source_id) : (L.sources || []).map(sourceBlock).join("")}</details>`;
    return h + `</div>`;
  }
  function absentCard(L, code) {
    const ref = refFor(L);
    let h = `<div class="obs notknown" data-layer="${esc(L.id)}"><h3>${esc(L.label)}</h3>`;
    if (ref) h += `<div class="lim">Would reveal <strong>${esc(ref.reveals.toLowerCase())}</strong>. ${esc(ref.limitation)}.</div>`;
    h += `<div class="val absent">No value here</div><div class="flag">${esc(META.reasons[code] || "No value.")}</div>`;
    h += `<details><summary>Caveat and source</summary><p>${esc(L.caveat)}</p>${L.source_id ? sourceBlock(L.source_id) : ""}</details>`;
    return h + `</div>`;
  }
  function refCard(R) {
    return `<div class="obs notknown"><h3>${esc(R.label)}</h3>
      <div class="lim">Would reveal <strong>${esc(R.reveals.toLowerCase())}</strong>. ${esc(R.limitation)}.</div>
      <span class="status">${esc(STATUS_WORD[R.status] || R.status)}</span>
      <p>${esc(R.reason)}</p>
      <dl class="kv"><dt>Candidate source</dt><dd>${esc(R.candidate)}</dd><dt>Needs</dt><dd>${esc(R.needs)}</dd></dl></div>`;
  }

  // Values for a res-5 cell, or the stated meaning of a cell no source touches.
  async function lookup(cell) {
    const d = await getJSON(shardPath(META.build.inspect_res, cell));
    const i = d ? d.index.get(cell) : undefined;
    if (i !== undefined) {
      const out = { touched: true, v: {}, why: {}, x: {} };
      for (const k in d.v) out.v[k] = d.v[k][i];
      for (const k in d.why) out.why[k] = d.why[k][i];
      for (const k in d.x) out.x[k] = d.x[k][i];
      return out;
    }
    const [lat] = h3.cellToLatLng(cell);
    const inside = (n) => lat >= META.extent[n][0] && lat <= META.extent[n][1];
    return { touched: false, x: null,
      v: { "pop.ghsl": inside("ghsl") ? 0 : null, "pop.worldpop": null, "pop.disagreement": null, "acc.motor": null, "geo.land": 0 },
      why: { "pop.ghsl": inside("ghsl") ? "ghsl_zero_water" : "ghsl_extent", "pop.worldpop": inside("worldpop") ? "wp_nodata" : "wp_extent",
        "pop.disagreement": "d_missing", "acc.motor": inside("map") ? "map_nodata" : "map_extent", "geo.land": "" } };
  }

  async function inspect(lat, lng, cellArg) {
    const res = META.build.inspect_res;
    const cell = cellArg || h3.latLngToCell(lat, lng, res);
    if (cellArg) [lat, lng] = h3.cellToLatLng(cell);
    state.sel = { lat, lng, cell };
    writeHash();
    if (marker) map.removeLayer(marker);
    const ring = h3.cellToBoundary(cell);
    const span = Math.max(...ring.map((p) => p[1])) - Math.min(...ring.map((p) => p[1]));
    marker = window.L.polygon(ring.map(([a, o]) => [a, span > 180 && o < 0 ? o + 360 : o]),
      { interactive: false, color: "#e8590c", weight: 3, fill: false }).addTo(map);
    $("#locality").value = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    $("#cell").innerHTML = `<p class="meta">Looking up ${esc(cell)}…</p>`;
    $("#cell").hidden = false; $("#intro").hidden = true;
    let rec;
    try { rec = await lookup(cell); } catch (e) { $("#cell").innerHTML = `<p class="err">Could not read the data for this cell: ${esc(e.message)}</p>`; return; }
    if (!state.sel || state.sel.cell !== cell) return;
    const [clat, clng] = h3.cellToLatLng(cell);
    let h = `<h2 class="loc-h">${lat.toFixed(3)}°, ${lng.toFixed(3)}°</h2>
      <div class="meta">H3 resolution-${res} cell <code>${esc(cell)}</code> · centre ${clat.toFixed(3)}°, ${clng.toFixed(3)}° · ${fmt(h3.cellArea(cell, "km2"))} km²
      · build ${esc(META.build.version)} · <a href="#" id="closecell">overview</a></div>
      <p class="meta">The cell is an index for joining sources, not a measurement area. Each value says what grid it was measured on and how many of its pixels fell in this cell.</p>`;
    if (!rec.touched) h += `<div class="flag">${esc(META.untouched)}</div>`;
    const known = [], absent = [];
    const order = LAYERS.slice().sort((a, b) => (a.id === state.layer ? -1 : b.id === state.layer ? 1 : 0));
    for (const L of order) {
      const v = rec.v[L.id];
      if (v === null || v === undefined) absent.push(absentCard(L, rec.why[L.id]));
      else known.push(knownCard(L, v, rec.why[L.id], rec.x));
    }
    const notIngested = META.references.filter((r) => r.status !== "ingested");
    h += `<div class="section-h">What is known here (${known.length})</div>` + known.join("");
    h += `<div class="section-h">What is not known here (${absent.length + notIngested.length})</div>`;
    if (absent.length) h += `<p class="meta">Ingested indicators with no value at this place:</p>` + absent.join("");
    h += `<p class="meta">Reference indicators not yet on the map anywhere, and why:</p>` + notIngested.map(refCard).join("");
    $("#cell").innerHTML = h;
    $("#closecell").onclick = (e) => { e.preventDefault(); clearSel(); };
    $("#cell").querySelectorAll(".obs[data-layer] h3").forEach((el) => {
      el.style.cursor = "pointer"; el.title = "Show this indicator on the map";
      el.onclick = () => setLayer(el.parentElement.dataset.layer);
    });
  }
  function clearSel() {
    state.sel = null;
    if (marker) { map.removeLayer(marker); marker = null; }
    $("#cell").hidden = true; $("#intro").hidden = false;
    writeHash();
  }

  // ------------------------------------------------------------ intro / about
  function introHTML() {
    const t = META.totals, c = META.counts;
    const rows = META.references.map((r) => `<tr><td>${esc(r.label)}</td><td><span class="status">${esc(STATUS_WORD[r.status] || r.status)}</span></td></tr>`).join("");
    return `<h2>Select any place on Earth</h2>
      <p>Click the map, or type a latitude and longitude (or an H3 cell id) into <em>Locality</em>. The inspector lists what this build knows about that place, where each value comes from and how far it can be read, and then what it does not know.</p>
      <p class="meta">Build ${esc(META.build.version)} · ${c.inspect.cells_touched.toLocaleString("en")} H3 resolution-${META.build.inspect_res} cells hold land, modelled residents or a value · GHSL total ${(t.ghsl_people / 1e9).toFixed(2)} billion people, WorldPop ${(t.worldpop_people / 1e9).toFixed(2)} billion (2020 models, not counts).</p>
      <div id="aboutbox">
      <div class="section-h">The twelve reference indicators</div>
      <table class="grades">${rows}</table>
      <p class="meta">Two of twelve are on the map, each from one openly licensed source, with a second population model shown beside the first as a check that is not independent. The rest are registered with the reason they are missing; click any place to read them.</p>
      <div class="section-h">What this preview is not</div>
      <ul class="meta">
        <li>Not a score, ranking or composite. One indicator is coloured at a time.</li>
        <li>Not a measurement at the hexagon's size. Sources are 1 km grids; hexagons are an index for joining and drawing.</li>
        <li>Not one moment. Population is 2020, land surface 2018, travel time 2019 to 2020.</li>
        <li>Not a statement about any boundary. This build uses no country outlines at all.</li>
        <li>Not published. This is a working build on a branch; publication is Nolen's decision.</li>
      </ul></div>`;
  }

  // ------------------------------------------------------------ controls and state
  function setLayer(id) {
    state.layer = id;
    $("#layer").value = id;
    const L = layerById(id);
    const ep = $("#epoch");
    ep.innerHTML = `<option>${esc(periodText(L))}</option>`;
    $("#epochnote").textContent = "The only epoch ingested so far.";
    $("#epochnote").title = L.upstream_epochs || "";
    writeHash();
    draw();
    if (state.sel) inspect(state.sel.lat, state.sel.lng, state.sel.cell);
  }
  function writeHash() {
    const h = new URLSearchParams();
    h.set("layer", state.layer);
    if (state.evidence !== "value") h.set("evidence", state.evidence);
    if (state.sel) h.set("cell", state.sel.cell);
    if (map) { const c = map.getCenter(); h.set("view", `${c.lat.toFixed(2)},${c.lng.toFixed(2)},${map.getZoom()}`); }
    history.replaceState(null, "", "#" + h.toString());
  }
  function parseLocality(s) {
    s = s.trim();
    if (/^[0-9a-f]{15}$/i.test(s) && h3.isValidCell(s.toLowerCase())) {
      const c = s.toLowerCase();
      const r = h3.getResolution(c);
      const cell = r === META.build.inspect_res ? c : r > META.build.inspect_res ? h3.cellToParent(c, META.build.inspect_res) : h3.cellToCenterChild(c, META.build.inspect_res);
      return { cell };
    }
    const m = s.match(/^\s*(-?\d+(?:\.\d+)?)\s*°?\s*([NS])?\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*°?\s*([EW])?\s*$/i);
    if (!m) return null;
    let lat = +m[1], lng = +m[3];
    if (m[2] && m[2].toUpperCase() === "S") lat = -Math.abs(lat);
    if (m[4] && m[4].toUpperCase() === "W") lng = -Math.abs(lng);
    if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
    return { lat, lng };
  }

  async function boot() {
    META = await getJSON("data/meta.json");
    LAYERS = META.layers;
    for (const k of ["light", "dense"]) patterns[k] = makePattern(k);
    $("#intro").innerHTML = introHTML();
    $("#aboutlink").onclick = (e) => { e.preventDefault(); clearSel(); $("#aboutbox").scrollIntoView({ behavior: "smooth" }); };

    const sel = $("#layer");
    const ingested = LAYERS.map((L) => `<option value="${esc(L.id)}">${esc(L.label)}</option>`).join("");
    const missing = META.references.filter((r) => r.status !== "ingested")
      .map((r) => `<option disabled>${esc(r.label)}: ${esc(STATUS_WORD[r.status] || r.status)}</option>`).join("");
    sel.innerHTML = `<optgroup label="On the map">${ingested}</optgroup><optgroup label="Registered, not yet on the map">${missing}</optgroup>`;
    sel.onchange = () => setLayer(sel.value);
    $("#evidence").onchange = (e) => { state.evidence = e.target.value; writeHash(); draw(); };
    $("#locform").onsubmit = (e) => {
      e.preventDefault();
      const p = parseLocality($("#locality").value);
      if (!p) { $("#lochelp").textContent = "Type latitude, longitude (for example -1.29, 36.82) or a 15-character H3 cell id."; return; }
      $("#lochelp").textContent = "or click the map";
      if (p.cell) { const [la, ln] = h3.cellToLatLng(p.cell); map.setView([la, ln], Math.max(map.getZoom(), 7)); inspect(la, ln, p.cell); }
      else { map.setView([p.lat, p.lng], Math.max(map.getZoom(), 7)); inspect(p.lat, p.lng); }
    };

    const h = new URLSearchParams(location.hash.slice(1));
    const view = (h.get("view") || "").split(",").map(Number);
    renderer = window.L.canvas({ padding: 0.2 });
    map = window.L.map("map", { worldCopyJump: true, minZoom: 1, maxZoom: 11, zoomSnap: 1, renderer });
    if (view.length === 3 && view.every(Number.isFinite)) map.setView([view[0], view[1]], view[2]); else map.setView([15, 10], 2);
    window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 11,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    map.attributionControl.addAttribution("Data: GHSL (JRC), WorldPop, Malaria Atlas Project; licences in the inspector.");
    map.on("click", (e) => inspect(e.latlng.lat, ((e.latlng.lng + 540) % 360) - 180));
    map.on("moveend", () => { writeHash(); draw(); });

    state.evidence = h.get("evidence") === "basis" ? "basis" : "value";
    $("#evidence").value = state.evidence;
    const first = LAYERS.find((L) => L.id === h.get("layer")) || LAYERS.find((L) => L.primary) || LAYERS[0];
    setLayer(first.id);
    const c = h.get("cell");
    if (c && h3.isValidCell(c)) { const [la, ln] = h3.cellToLatLng(c); inspect(la, ln, c); }
  }

  boot().catch((e) => { document.querySelector("#intro").innerHTML = `<p class="err">Could not start: ${esc(e.message)}</p>`; console.error(e); });
})();
