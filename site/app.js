/* Worldwide Quality of Life Map, WQL-002 proof of concept.
 * Plain script, no build step. Reads the files the pipeline writes to data/.
 * One layer is coloured at a time; nothing is combined or ranked.
 */
(function () {
  "use strict";

  const SEQ = ["#fde725", "#a0da39", "#4ac16d", "#1fa187", "#277f8e", "#365c8d", "#46327e", "#440154"]; // viridis, light = low
  const DIV = ["#8c510a", "#bf812d", "#dfc27d", "#f0ead6", "#c7eae5", "#80cdc1", "#35978f", "#01665e"];   // BrBG
  const STATUS_TEXT = {
    measured: "measured", modelled: "modelled", derived: "derived by this project",
    "lower bound": "lower bound", absent: "absent", imputed: "imputed", disaggregated: "disaggregated",
  };
  const DIM_LABEL = { recency: "Recency", directness: "Directness", spatial_fidelity: "Spatial fidelity",
    coverage: "Coverage", validation: "Validation", interval: "Interval" };
  const ORDER = "ABCD";

  let META, OBS, REGION, SRC, cellLayer, outlineLayer, disputeLayer, baseLayer, map;
  let current = null, selected = null, scale = null;

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v) => {
    if (v === undefined || v === null || v === "") return "";
    const a = Math.abs(v);
    if (a >= 1000) return Math.round(v).toLocaleString("en");
    if (a >= 100) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1).replace(/\.0$/, "");
    return (+v.toFixed(2)).toString();
  };
  const weakest = (g) => Object.values(g).reduce((w, x) => (ORDER.indexOf(x) > ORDER.indexOf(w) ? x : w), "A");

  function readHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    return { layer: h.get("layer"), cell: h.get("cell") };
  }
  function writeHash() {
    const h = new URLSearchParams();
    if (current) h.set("layer", current);
    if (selected) h.set("cell", selected);
    history.replaceState(null, "", "#" + h.toString());
  }

  // ------------------------------------------------------------ scales
  function quantileBreaks(values, n) {
    const v = values.slice().sort((a, b) => a - b);
    const out = [];
    for (let i = 1; i < n; i++) out.push(v[Math.floor((i / n) * (v.length - 1))]);
    return [...new Set(out.map((x) => +fmt(x).replace(/,/g, "")))];
  }
  function buildScale(m) {
    const vals = [];
    for (const id in OBS) {
      const o = OBS[id].o[m.id];
      if (o.st !== "absent" && o.v !== undefined) vals.push(o.v);
    }
    let breaks, palette = SEQ, zeroClass = false;
    if (m.scale.type === "diverging") {
      breaks = [-100, -50, -20, 0, 20, 50, 100];
      palette = DIV;
    } else if (m.scale.type === "linear" && m.scale.domain) {
      const [a, b] = m.scale.domain, step = (b - a) / SEQ.length;
      breaks = SEQ.slice(1).map((_, i) => +(a + step * (i + 1)).toFixed(0));
    } else {
      const pos = vals.filter((x) => x > 0);
      zeroClass = vals.some((x) => x === 0);
      breaks = quantileBreaks(pos, SEQ.length);
    }
    const colors = palette.slice(palette.length - breaks.length - 1);
    return {
      breaks, colors, zeroClass,
      color(v) {
        if (zeroClass && v === 0) return getComputedStyle(document.documentElement).getPropertyValue("--zero").trim();
        let i = 0;
        while (i < breaks.length && v >= breaks[i]) i++;
        return colors[i];
      },
    };
  }

  function legendHTML(m, s) {
    const parts = [`<span><strong>${esc(m.label)}</strong> (${esc(m.unit)})</span>`];
    const lab = (i) => i === 0 ? (s.zeroClass ? `&gt;0–${fmt(s.breaks[0])}` : `&lt; ${fmt(s.breaks[0])}`) : i === s.breaks.length ? `≥ ${fmt(s.breaks[i - 1])}` : (s.breaks[i - 1] < 0 ? `${fmt(s.breaks[i - 1])} to ${fmt(s.breaks[i])}` : `${fmt(s.breaks[i - 1])}–${fmt(s.breaks[i])}`);
    if (s.zeroClass) parts.push(`<span><i class="sw" style="background:var(--zero)"></i>${m.id === "sec.conflict" ? "0 recorded" : "0"}</span>`);
    s.colors.forEach((c, i) => parts.push(`<span><i class="sw" style="background:${c}"></i>${lab(i)}</span>`));
    parts.push(`<span><i class="sw absent"></i>absent</span>`);
    const note = m.scale.type === "log" ? "Classes are quantiles of the values in this window, so colours are relative to this region, not to any standard." :
      m.scale.type === "diverging" ? "Brown: WorldPop lower than GHSL. Teal: WorldPop higher." : "";
    if (note) parts.push(`<span>${note}</span>`);
    return parts.join("");
  }

  // ------------------------------------------------------------ map
  function styleFor(feature) {
    const o = OBS[feature.id].o[current];
    const base = { weight: 0.25, color: "rgba(80,80,80,.5)",
      fillOpacity: $("#basemap").checked ? 0.72 : 0.92 };
    if (o.st === "absent") return { ...base, className: "cell-absent", fillColor: null, fill: true };
    return { ...base, className: "", fillColor: scale.color(o.v) };
  }
  function restyle() {
    cellLayer.eachLayer((l) => {
      const st = styleFor(l.feature);
      l.setStyle(st);
      const el = l.getElement();
      if (el) {
        el.classList.toggle("cell-absent", st.className === "cell-absent");
        if (st.className === "cell-absent") el.removeAttribute("fill");
      }
    });
  }
  function setLayer(id) {
    current = id;
    const m = META.indicators.find((x) => x.id === id);
    scale = buildScale(m);
    $("#legend").innerHTML = legendHTML(m, scale);
    restyle();
    if (selected) renderCell(selected);
    writeHash();
  }

  // ------------------------------------------------------------ inspector
  function sourceBlock(sid) {
    const s = SRC[sid];
    if (!s) return "";
    return `<dl class="kv">
      <dt>Source</dt><dd><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a></dd>
      <dt>Publisher</dt><dd>${esc(s.publisher)}</dd>
      <dt>Licence</dt><dd>${esc(s.licence)}</dd>
      <dt>Cite</dt><dd>${esc(s.citation)}</dd></dl>`;
  }

  function obsCard(cid, m) {
    const o = OBS[cid].o[m.id];
    const active = m.id === current ? " active" : "";
    let h = `<div class="obs${active}" data-ind="${esc(m.id)}"><h3>${esc(m.label)}</h3>`;
    if (o.st === "absent") {
      h += `<div class="val absent">No value</div><div class="flag">${esc(o.why)}</div>`;
    } else {
      const gd = { ...m.grade_detail, ...(o.g || {}) };
      const w = weakest(gd);
      let interval = "";
      if (o.lo !== undefined && o.hi !== undefined && (o.lo !== o.v || o.hi !== o.v)) interval = ` <span class="meta">(${fmt(o.lo)}–${fmt(o.hi)}${m.interval_meaning ? ", " + esc(m.interval_meaning) : ""})</span>`;
      else if (o.st === "lower bound") interval = ` <span class="meta">(at least)</span>`;
      h += `<div class="val">${o.st === "lower bound" ? "≥ " : ""}${fmt(o.v)} <span class="meta">${esc(m.unit)}</span>${interval}</div>`;
      h += `<span class="badge">${esc(STATUS_TEXT[o.st] || o.st)}</span>`;
      h += `<span class="badge grade" title="Weakest of the six evidence dimensions. A flag, not a score.">weakest evidence: ${w}</span>`;
      h += `<dl class="kv"><dt>Native grain</dt><dd>${esc(m.native_grain)}</dd>`;
      if (o.n !== undefined) {
        const unit = m.id === "sec.conflict" ? (o.n === 1 ? "event" : "events") : (o.n === 1 ? "source pixel" : "source pixels");
        h += `<dt>Behind this value</dt><dd>${o.n.toLocaleString("en")} ${unit} in this cell</dd>`;
      }
      if (m.period) h += `<dt>Reference period</dt><dd>${esc(m.period[0])} to ${esc(m.period[1])}</dd>`;
      h += extras(m, o);
      h += `</dl>`;
      h += `<details><summary>Evidence grade by dimension</summary><table class="grades">` +
        Object.keys(DIM_LABEL).map((d) => `<tr><td>${DIM_LABEL[d]}</td><td class="${gd[d] === w ? "weak" : ""}">${gd[d]}${o.g && o.g[d] ? " (lowered for this cell)" : ""}</td></tr>`).join("") +
        `</table></details>`;
    }
    h += `<details><summary>How this value was made</summary><ol>${m.lineage.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>`;
    h += `<details><summary>Caveat and source</summary><p>${esc(m.caveat)}</p>${sourceBlock(m.source_id)}` +
      (m.sources ? m.sources.filter((s) => s !== m.source_id).map(sourceBlock).join("") : "") + `</details>`;
    return h + `</div>`;
  }

  function extras(m, o) {
    const x = o.x || {};
    let h = "";
    if (m.id === "urb.share") h += `<dt>Split</dt><dd>urban centre ${fmt(x.urban_centre)}%, urban cluster ${fmt(x.urban_cluster)}%, rural ${fmt(x.rural)}%</dd>`;
    if (m.id.startsWith("acc.")) h += `<dt>Within-cell spread</dt><dd>${fmt(x.min)} to ${fmt(x.max)} min (spread, not uncertainty); ${esc(x.weighting)}</dd>`;
    if (m.id === "pop.disagreement") h += `<dt>The two estimates</dt><dd>WorldPop ${fmt(x.worldpop)}, GHSL ${fmt(x.ghsl)} people</dd>`;
    if (m.id === "sec.conflict" && x.events_within_25km) h += `<dt>Location precision</dt><dd>${x.events_within_25km} of ${o.n} events are located only within 25 km of the coded point, so they may belong to a neighbouring cell</dd>`;
    if (m.id === "kno.census_age" && x.countries) {
      h += `<dt>Census</dt><dd>${Object.entries(x.countries).map(([k, c]) => `${esc(k)}: ${c.lower_bound ? "no census since at least " + c.year + " (unconfirmed)" : "last census " + c.year}`).join("; ")}</dd>`;
    }
    if (x.note) h += `<dt>Note</dt><dd>${esc(x.note)}</dd>`;
    return h;
  }

  function renderCell(cid) {
    const c = OBS[cid];
    const f = c.f;
    let h = `<h2>Cell ${esc(cid)}</h2><div class="meta">Centre ${c.c[0]}°, ${c.c[1]}° · ${c.a} km² · H3 resolution ${REGION.h3_resolution} · <a href="#" id="closecell">back to overview</a></div>`;
    if (f.countries.length) h += `<div class="meta">Country outlines covering this cell: ${f.shares.map(([k, s]) => `${esc(k)} ${Math.round(s * 100)}%`).join(", ")}</div>`;
    if (f.no_country) h += `<div class="flag">No country outline covers this cell. In the simplified geoBoundaries outlines that usually means open water, but some populated islands and shorelines also fall outside them.</div>`;
    if (f.boundary_disagreement) h += `<div class="flag">Boundary sources disagree here: two independently sourced country outlines overlap inside this cell. This is a disagreement between boundary files, not necessarily a political dispute.</div>`;
    if (f.known_dispute) h += `<div class="flag">Contested territory: ${esc(f.known_dispute)}. See the limits page; the list of disputes is not authoritative.</div>`;
    const ms = META.indicators.slice().sort((a, b) => (a.id === current ? -1 : b.id === current ? 1 : 0));
    h += ms.map((m) => obsCard(cid, m)).join("");
    $("#cell").innerHTML = h;
    $("#cell").hidden = false;
    $("#intro").hidden = true;
    $("#closecell").onclick = (e) => { e.preventDefault(); selectCell(null); };
    $("#cell").querySelectorAll(".obs h3").forEach((el) => {
      el.style.cursor = "pointer";
      el.title = "Show this layer on the map";
      el.onclick = () => { $("#layer").value = el.parentElement.dataset.ind; setLayer(el.parentElement.dataset.ind); };
    });
  }

  let highlight = null;
  function selectCell(cid) {
    selected = cid;
    if (highlight) { map.removeLayer(highlight); highlight = null; }
    if (cid) cellLayer.eachLayer((l) => {
      if (l.feature.id === cid) highlight = L.geoJSON(l.feature, { interactive: false,
        style: { color: "#e8590c", weight: 4, fill: false } }).addTo(map);
    });
    if (cid) renderCell(cid); else { $("#cell").hidden = true; $("#intro").hidden = false; }
    restyle();
    writeHash();
  }

  // ------------------------------------------------------------ boot
  async function boot() {
    const get = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p + " " + r.status); return r.json(); });
    const [meta, obs, cells, bounds, region] = await Promise.all([
      get("data/indicators.json"), get("data/observations.json"), get("data/cells.geojson"),
      get("data/boundaries.geojson"), get("data/region.json")]);
    META = meta; OBS = obs; REGION = region; SRC = meta.sources;

    const r = region.region;
    map = L.map("map", { preferCanvas: false, zoomSnap: 0.25 }).fitBounds([[r.south, r.west], [r.north, r.east]]);
    baseLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' });
    baseLayer.addTo(map);
    map.attributionControl.addAttribution("Data: GHSL (JRC), WorldPop, MAP, UCDP, UNSD, geoBoundaries. See each cell for licences.");

    cellLayer = L.geoJSON(cells, {
      style: () => ({ weight: 0.25 }),
      onEachFeature: (f, l) => l.on("click", () => selectCell(f.id)),
    }).addTo(map);
    outlineLayer = L.geoJSON(bounds, { interactive: false,
      style: { color: getComputedStyle(document.documentElement).getPropertyValue("--outline").trim(), weight: 1.5, dashArray: "4 3", fill: false } }).addTo(map);
    disputeLayer = L.layerGroup(region.boundary.known_disputes.map((d) =>
      L.circleMarker([d.lat, d.lng], { radius: 7, color: "#000", weight: 2, fillColor: "#fff", fillOpacity: 1 })
        .bindTooltip(`${d.name}: ${d.claimants.join(" / ")}. ${d.note}`))).addTo(map);

    const sel = $("#layer");
    META.indicators.forEach((m) => {
      const o = document.createElement("option");
      o.value = m.id; o.textContent = m.label; sel.appendChild(o);
    });
    sel.onchange = () => setLayer(sel.value);
    $("#basemap").onchange = (e) => { e.target.checked ? baseLayer.addTo(map) : map.removeLayer(baseLayer); restyle(); };
    $("#outlines").onchange = (e) => { if (e.target.checked) { outlineLayer.addTo(map); disputeLayer.addTo(map); } else { map.removeLayer(outlineLayer); map.removeLayer(disputeLayer); } };

    const ac = region.absent_counts;
    $("#summary").innerHTML = `This window holds <strong>${region.n_cells.toLocaleString("en")}</strong> cells and about ` +
      `<strong>${(region.population_totals.ghsl / 1e6).toFixed(1)} million</strong> people by GHSL's 2020 model ` +
      `(${(region.population_totals.worldpop / 1e6).toFixed(1)} million by WorldPop's). ` +
      `${region.conflict.events_in_window - region.conflict.events_placed} of ${region.conflict.events_in_window} recorded conflict events in ${region.conflict.period.join("–")} ` +
      `are located too coarsely to place in a cell and are counted separately. ` +
      `Cells with no value: ${META.indicators.filter((m) => ac[m.id]).map((m) => `${esc(m.label)} ${ac[m.id].toLocaleString("en")}`).join("; ")}.`;

    const h = readHash();
    const first = META.indicators.find((m) => m.id === h.layer) ? h.layer : "pop.ghsl";
    sel.value = first;
    setLayer(first);
    if (h.cell && OBS[h.cell]) selectCell(h.cell);
    setTimeout(() => { map.invalidateSize(); map.fitBounds([[r.south, r.west], [r.north, r.east]]); }, 0);
  }

  boot().catch((e) => {
    document.getElementById("intro").innerHTML = `<h2>The map failed to load</h2><p>${esc(e.message)}</p><p>If you opened this file directly from disk, serve the folder instead, for example <code>python3 -m http.server -d site</code>.</p>`;
  });
})();
