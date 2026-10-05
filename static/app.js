/* WanderPin UI */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ------------------------------------------------------------------ api --
async function api(path, method = 'GET', body) {
  const r = await fetch(path, {method, headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || msg); } catch {}
    const e = new Error(msg); e.status = r.status; throw e;
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.text();
}
const post = (p, b) => api(p, 'POST', b || {});

function toast(msg, kind = 'ok', ms) {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.innerHTML = icon(kind === 'ok' ? 'check' : kind === 'warn' ? 'info' : 'info') + `<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(t);
  setTimeout(() => { t.style.transition = '.3s'; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, ms || (kind === 'bad' ? 6500 : 2800));
}
const fail = e => toast(e.message || String(e), 'bad');

// -------------------------------------------------------------- formats --
let S = {};            // settings
let PRESETS = [];
let STATE = {};
const isMph = () => S.units === 'mph';
const toUnit = kmh => isMph() ? kmh / 1.609344 : kmh;
const fromUnit = v => isMph() ? v * 1.609344 : v;
const unitLabel = () => isMph() ? 'mph' : 'km/h';
function fmtSpeed(kmh) { const v = toUnit(kmh); return v < 10 ? v.toFixed(1).replace(/\.0$/, '') : Math.round(v).toString(); }
function fmtDist(m) {
  if (isMph()) { const mi = m / 1609.344; return mi < 0.1 ? `${Math.round(m * 3.28084)} ft` : `${mi < 10 ? mi.toFixed(2) : mi.toFixed(1)} mi`; }
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km`;
}
function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${s % 60 ? (s % 60) + 's' : ''}`.trim();
}
const fmtLL = (lat, lon) => `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
function timeAgo(t) {
  const s = Date.now() / 1000 - t;
  if (s < 60) return 'just now'; if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`; return new Date(t * 1000).toLocaleDateString();
}
function distM(a, b) {
  const R = 6371000, r = Math.PI / 180, dLa = (b[0] - a[0]) * r, dLo = (b[1] - a[1]) * r;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
const pathLen = p => p.reduce((s, x, i) => i ? s + distM(p[i - 1], x) : 0, 0);
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

// ------------------------------------------------------------------ map --
let map, baseLayer, LAYERS = {}, MAPCFG = {};
const mk = {me: null, target: null, stops: [], line: null, done: null};
const HAS_WEBGL = (() => { try { const c = document.createElement('canvas'); return !!(window.WebGL2RenderingContext && c.getContext('webgl2')) || !!c.getContext('webgl'); } catch { return false; } })();
const ROUTING_CREDIT = 'Routing <a href="https://routing.openstreetmap.de/about.html" target="_blank" rel="noopener">FOSSGIS OSRM</a> · <a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener">Fix the map</a>';

function initMap(center) {
  map = L.map('map', {zoomControl: false, keyboard: false, worldCopyJump: true, attributionControl: true})
    .setView(center || [40.7128, -74.006], center ? 15 : 12);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>');
  map.attributionControl.addAttribution(ROUTING_CREDIT);
  L.control.zoom({position: 'bottomright'}).addTo(map);
  applyLayer();
  map.on('click', e => onMapClick(e.latlng));
  map.on('contextmenu', e => openCtx(e));
  map.on('movestart', closeCtx);
  map.on('dragstart', () => { if (follow) setFollow(false, true); });
}
function layerId() {
  let id = S.map_layer || 'auto';
  if (id === 'auto') id = S.theme === 'light' ? (MAPCFG.auto_light || 'streets') : (MAPCFG.auto_dark || 'dark');
  if (!LAYERS[id]) id = Object.keys(LAYERS)[0];
  if (LAYERS[id].type === 'vector' && (!HAS_WEBGL || !L.maplibreGL)) id = Object.keys(LAYERS).find(k => LAYERS[k].type !== 'vector') || id;
  return id;
}
function applyLayer() {
  const l = LAYERS[layerId()];
  if (baseLayer) { map.removeLayer(baseLayer); baseLayer = null; }
  if (l.type === 'vector') {
    baseLayer = L.maplibreGL({style: l.style, attributionControl: false, interactive: false});
    baseLayer.getAttribution = () => '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
  } else {
    baseLayer = L.tileLayer(l.url, {maxZoom: l.max_zoom || 19, maxNativeZoom: l.max_zoom || 19, attribution: l.attribution || '', subdomains: l.subdomains || 'abc'});
  }
  baseLayer.addTo(map);
  map.getContainer().style.background = l.preview || '';
  if (l.type === 'vector') {
    // If the vector map server can't be reached, fall back to classic OpenStreetMap tiles.
    const gl = baseLayer.getMaplibreMap?.(), me = baseLayer;
    let loaded = false;
    gl?.once('load', () => { loaded = true; });
    gl?.on('error', e => {
      if (loaded || baseLayer !== me || !LAYERS.osm) return;
      if (/Failed to fetch|AJAXError|NetworkError/i.test(String(e?.error?.message || e?.error || ''))) {
        loaded = true;
        map.removeLayer(baseLayer);
        baseLayer = L.tileLayer(LAYERS.osm.url, {maxZoom: 19, attribution: LAYERS.osm.attribution}).addTo(map);
        toast('Vector maps unavailable. Using classic OpenStreetMap.', 'warn');
      }
    });
  }
}
function renderLayerMenu() {
  const opts = [['auto', 'Auto (match theme)', 'var(--grad)']].concat(Object.entries(LAYERS)
    .filter(([, v]) => v.type !== 'vector' || HAS_WEBGL).map(([k, v]) => [k, v.name, v.preview || 'var(--line-2)']));
  $('#layerMenu').innerHTML = opts.map(([k, n, bg]) => `<button data-l="${k}" class="${(S.map_layer || 'auto') === k ? 'on' : ''}"><span class="sw" style="background:${bg}"></span>${esc(n)}</button>`).join('');
  $$('#layerMenu button').forEach(b => b.onclick = () => { saveSetting({map_layer: b.dataset.l}); applyLayer(); renderLayerMenu(); $('#layerMenu').classList.remove('show'); });
}

const meIcon = L.divIcon({className: 'glide', html: '<div class="me"><div class="halo"></div><div class="core"></div></div>', iconSize: [26, 26], iconAnchor: [13, 13]});
const tgtIcon = L.divIcon({className: '', iconSize: [34, 42], iconAnchor: [17, 40],
  html: `<svg class="tgt" viewBox="0 0 34 42"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs><path d="M17 41S3 27 3 16a14 14 0 0 1 28 0c0 11-14 25-14 25z" fill="url(#g)" stroke="#fff" stroke-width="2.5"/><circle cx="17" cy="16" r="5" fill="#fff"/></svg>`});

function setMe(pos) {
  if (!pos) { if (mk.me) { mk.me.remove(); mk.me = null; } return; }
  if (!mk.me) mk.me = L.marker(pos, {icon: meIcon, zIndexOffset: 1000, interactive: false}).addTo(map);
  else mk.me.setLatLng(pos);
}

// ------------------------------------------------------------- targeting --
let target = null;   // {lat, lon, name, detail}
async function setTarget(lat, lon, name, detail, fly = true) {
  target = {lat, lon, name, detail};
  if (!mk.target) mk.target = L.marker([lat, lon], {icon: tgtIcon, draggable: true, zIndexOffset: 900}).addTo(map)
    .on('dragend', e => { const p = e.target.getLatLng(); setTarget(p.lat, p.lng, null, null, false); });
  else mk.target.setLatLng([lat, lon]);
  if (fly) map.flyTo([lat, lon], Math.max(map.getZoom(), 15), {duration: .8});
  showTab('move');
  renderTarget();
  if (!name) {
    const tk = target;
    try { const r = await api(`/api/reverse?lat=${lat}&lon=${lon}`); if (target === tk && r.name) { const [a, ...b] = r.name.split(','); target.name = a.trim(); target.detail = b.join(',').trim(); renderTarget(); } } catch {}
  }
}
function clearTarget() { target = null; if (mk.target) { mk.target.remove(); mk.target = null; } renderTarget(); }
function renderTarget() {
  $('#targetEmpty').hidden = !!target; $('#targetInfo').hidden = !target;
  if (!target) return;
  $('#tName').textContent = target.name || 'Dropped pin';
  $('#tSub').textContent = target.detail || fmtLL(target.lat, target.lon);
  const meta = [`<span class="pill">${icon('pin')}${fmtLL(target.lat, target.lon)}</span>`];
  const cur = STATE.current;
  if (cur) {
    const d = distM(cur, [target.lat, target.lon]);
    meta.push(`<span class="pill">${icon('route')}${fmtDist(d)} away</span>`);
    const kmh = targetKmh();
    if (d > 20) meta.push(`<span class="pill">${icon('clock')}~${fmtDur(d / (kmh / 3.6))} at ${fmtSpeed(kmh)} ${unitLabel()}</span>`);
    const cd = cooldownFor(d / 1000);
    if (S.cooldown_warnings && cd) meta.push(`<span class="pill warn" title="Suggested wait after this jump">${icon('clock')}${cd} min cooldown</span>`);
  }
  $('#tMeta').innerHTML = meta.join('');
}
const CD = [[1, .5], [2, 1], [4, 2], [10, 8], [12, 9], [15, 11], [20, 13], [25, 15], [30, 18], [65, 22], [81, 25], [100, 35], [250, 45], [500, 65], [750, 80], [1000, 100], [1500, 120]];
function cooldownFor(km) { if (km < .5) return 0; for (const [d, m] of CD) if (km <= d) return m; return 120; }

async function teleport(lat, lon, name) {
  if (!requireConnected()) return;
  try {
    const cd = STATE.motion?.cooldown;
    if (S.cooldown_warnings && cd && STATE.current && distM(STATE.current, [lat, lon]) > 1000 &&
        !confirm(`Your cooldown still has ${fmtDur(cd.left_s)} left. Games that check travel speed may flag this jump. Teleport anyway?`)) return;
    STATE = {...STATE, ...(await post('/api/teleport', {lat, lon, name}))};
    render(); toast(`Teleported${name ? ' to ' + name : ''}`);
    if (target && Math.abs(target.lat - lat) < 1e-7 && Math.abs(target.lon - lon) < 1e-7) clearTarget();
    loadHistory();
  } catch (e) { fail(e); }
}
async function travel(lat, lon) {
  if (!requireConnected()) return;
  if (!STATE.current) return toast('Teleport somewhere first — Travel moves you from your current spot.', 'warn');
  try {
    const r = await post('/api/travel', {lat, lon, roads: S.follow_roads});
    STATE = {...STATE, ...r};
    drawActivePath(r.plan.path);
    if (r.plan.fallback) toast('No road route found — traveling in a straight line.', 'warn');
    toast(`Traveling ${fmtDist(r.plan.distance)} at ${fmtSpeed(targetKmh())} ${unitLabel()}`);
    render();
  } catch (e) { fail(e); }
}
function requireConnected() {
  if (STATE.state === 'connected') return true;
  toast('Connect your iPhone first.', 'warn'); openConnect(); return false;
}

// ---------------------------------------------------------- context menu --
function openCtx(e) {
  const {lat, lng} = e.latlng, c = $('#ctx');
  c.innerHTML = `<div class="ch">${fmtLL(lat, lng)}</div>
    <button data-a="tp">${icon('zap')}Teleport here</button>
    <button data-a="tr">${icon('navigation')}Travel here</button>
    <button data-a="stop">${icon('route')}Add as route stop</button>
    <button data-a="save">${icon('star')}Save this place</button>
    <button data-a="copy">${icon('copy')}Copy coordinates</button>`;
  c.hidden = false;
  const x = Math.min(e.originalEvent.clientX, innerWidth - 230), y = Math.min(e.originalEvent.clientY, innerHeight - 250);
  c.style.left = x + 'px'; c.style.top = y + 'px';
  c.querySelectorAll('button').forEach(b => b.onclick = () => {
    closeCtx();
    ({tp: () => teleport(lat, lng), tr: () => travel(lat, lng), stop: () => { showTab('route'); addStop([lat, lng]); },
      save: () => savePlaceDialog({lat, lon: lng}), copy: () => { navigator.clipboard?.writeText(fmtLL(lat, lng)); toast('Coordinates copied'); }})[b.dataset.a]();
  });
}
function closeCtx() { $('#ctx').hidden = true; }
document.addEventListener('click', e => { if (!e.target.closest('#ctx')) closeCtx(); if (!e.target.closest('#layerMenu,#bLayers')) $('#layerMenu').classList.remove('show'); if (!e.target.closest('#searchBox')) $('#results').classList.remove('show'); });

function onMapClick(ll) {
  closeCtx();
  if (currentTab === 'route') return addStop([ll.lat, ll.lng]);
  setTarget(ll.lat, ll.lng, null, null, false);
}

// ---------------------------------------------------------------- search --
let results = [], resSel = -1;
const searchNow = debounce(runSearch, 350);
$('#q').addEventListener('input', () => { const v = $('#q').value.trim(); if (!v) return $('#results').classList.remove('show'); searchNow(v); });
$('#q').addEventListener('focus', () => { if (results.length && $('#q').value.trim()) $('#results').classList.add('show'); });
$('#q').addEventListener('keydown', e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); resSel = Math.max(0, Math.min(results.length - 1, resSel + (e.key === 'ArrowDown' ? 1 : -1))); paintResults(); }
  else if (e.key === 'Enter') { e.preventDefault(); if (results.length) pickResult(results[Math.max(0, resSel)]); else runSearch($('#q').value.trim()); }
  else if (e.key === 'Escape') { $('#results').classList.remove('show'); $('#q').blur(); }
});
function parseCoords(s) {
  const m = s.match(/^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/);
  if (!m) return null; const lat = +m[1], lon = +m[2];
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
}
async function runSearch(q) {
  if (!q) return;
  const local = [];
  const c = parseCoords(q);
  if (c) local.push({name: 'Go to coordinates', detail: fmtLL(c[0], c[1]), lat: c[0], lon: c[1], kind: 'crosshair'});
  const ql = q.toLowerCase();
  (window._places || []).filter(p => p.name.toLowerCase().includes(ql)).slice(0, 3)
    .forEach(p => local.push({name: p.name, detail: 'Saved place', lat: p.lat, lon: p.lon, kind: 'star'}));
  results = local; resSel = results.length ? 0 : -1; paintResults(true);
  if (c) return;
  try {
    const cur = STATE.current || (map && [map.getCenter().lat, map.getCenter().lng]);
    const r = await api(`/api/geocode?q=${encodeURIComponent(q)}${cur ? `&lat=${cur[0]}&lon=${cur[1]}` : ''}`);
    if ($('#q').value.trim() !== q) return;
    results = local.concat(r.map(x => ({...x, kind: 'pin'}))); resSel = results.length ? 0 : -1; paintResults();
  } catch (e) { paintResults(false, e.message); }
}
function paintResults(loading, err) {
  const box = $('#results');
  box.innerHTML = results.map((r, i) => `<div class="res ${i === resSel ? 'sel' : ''}" data-i="${i}"><div class="ri">${icon(r.kind || 'pin')}</div><div><b>${esc(r.name)}</b><small>${esc(r.detail || '')}</small></div></div>`).join('')
    + (loading ? `<div class="res-empty"><span class="spin"></span>&nbsp; Searching…</div>` : '')
    + (!loading && !results.length ? `<div class="res-empty">${esc(err || 'No results')}</div>` : '');
  box.classList.add('show');
  box.querySelectorAll('.res').forEach(el => el.onclick = () => pickResult(results[+el.dataset.i]));
}
function pickResult(r) {
  $('#results').classList.remove('show'); $('#q').blur();
  if (currentTab === 'route') { addStop([r.lat, r.lon], r.name); map.flyTo([r.lat, r.lon], Math.max(map.getZoom(), 14)); return; }
  setTarget(r.lat, r.lon, r.name, r.detail);
}

// ------------------------------------------------------------------ tabs --
let currentTab = 'move';
function showTab(t) {
  currentTab = t;
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  $$('.tab').forEach(s => s.classList.toggle('on', s.id === 'tab-' + t));
  map?.getContainer().style.setProperty('cursor', t === 'route' ? 'crosshair' : '');
  if (t === 'places') loadPlaces(); if (t === 'history') loadHistory(); if (t === 'schedule') loadSchedules(); if (t === 'route') loadRoutes();
  if (innerWidth <= 820 && $('#panel').classList.contains('collapsed')) setSheet('');
}
$$('#tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));

// ---------------------------------------------------------------- routes --
let stops = [];         // [{p:[lat,lon], name}]
let plan = null;        // {path, distance, roads}
function addStop(p, name) { stops.push({p, name}); redrawStops(); replan(); }
function redrawStops() {
  mk.stops.forEach(m => m.remove());
  mk.stops = stops.map((s, i) => L.marker(s.p, {draggable: true, zIndexOffset: 800,
    icon: L.divIcon({className: '', html: `<div class="stop-m ${i ? '' : 'first'}">${i + 1}</div>`, iconSize: [24, 24], iconAnchor: [12, 12]})})
    .addTo(map).on('dragend', e => { const ll = e.target.getLatLng(); stops[i].p = [ll.lat, ll.lng]; stops[i].name = null; renderStops(); replan(); }));
  renderStops();
}
function renderStops() {
  $('#stops').innerHTML = stops.length ? stops.map((s, i) => `<li><span class="n">${i + 1}</span><span class="t">${esc(s.name || fmtLL(s.p[0], s.p[1]))}</span><button data-i="${i}" title="Remove">${icon('x')}</button></li>`).join('')
    : `<div class="empty" style="padding:14px">${icon('route')}No stops yet</div>`;
  $$('#stops button').forEach(b => b.onclick = () => { stops.splice(+b.dataset.i, 1); redrawStops(); replan(); });
}
const replan = debounce(async () => {
  if (mk.line && STATE.motion?.mode !== 'route') { mk.line.remove(); mk.line = null; }
  plan = null; renderRouteStats();
  if (stops.length < 2) return;
  $('#routeStats').innerHTML = `<span class="pill"><span class="spin"></span>Finding route…</span>`;
  const road = S.follow_roads ? (presetById(S.preset)?.road || null) : null;
  try {
    plan = await post('/api/route/plan', {points: stops.map(s => s.p), road});
    drawPlan(plan.path);
    if (plan.fallback) toast('No road route found between those stops — using straight lines.', 'warn');
  } catch (e) { fail(e); }
  renderRouteStats();
}, 250);
function drawPlan(path) {
  if (mk.line) mk.line.remove();
  mk.line = L.polyline(path, {color: '#8b7bff', weight: 5, opacity: .85, dashArray: STATE.motion?.mode === 'route' ? null : '1 9', lineCap: 'round'}).addTo(map);
}
function drawActivePath(path) { plan = {path, distance: pathLen(path)}; drawPlan(path); mk.line.setStyle({dashArray: null}); }
function renderRouteStats() {
  if (!plan) { $('#routeStats').innerHTML = stops.length === 1 ? '<span class="pill">Add another stop</span>' : ''; return; }
  const kmh = targetKmh();
  $('#routeStats').innerHTML = `<span class="pill">${icon('route')}${fmtDist(plan.distance)}</span><span class="pill">${icon('clock')}${fmtDur(plan.distance / (kmh / 3.6))} at ${fmtSpeed(kmh)} ${unitLabel()}</span>${plan.roads ? `<span class="pill">${icon('check')}Roads</span>` : ''}`;
}
async function startRoute(path) {
  if (!requireConnected()) return;
  path = path || plan?.path;
  if (!path || path.length < 2) return toast('Add at least two stops first.', 'warn');
  try { STATE = {...STATE, ...(await post('/api/route/start', {path, loop_mode: S.loop_mode}))}; drawActivePath(path); toast('Route started'); render(); }
  catch (e) { fail(e); }
}
$('#bStart').onclick = () => startRoute();
$('#bClearRoute').onclick = () => { stops = []; plan = null; redrawStops(); if (mk.line) { mk.line.remove(); mk.line = null; } renderRouteStats(); };
$('#bRouteFromHere').onclick = () => { if (!STATE.current) return toast('No simulated location yet.', 'warn'); stops.unshift({p: [...STATE.current], name: 'Current location'}); redrawStops(); replan(); };
$('#optRoads').onchange = e => { saveSetting({follow_roads: e.target.checked}); replan(); };
$$('#loopSeg button').forEach(b => b.onclick = () => { saveSetting({loop_mode: b.dataset.v}); paintLoop(); });
function paintLoop() { $$('#loopSeg button').forEach(b => b.classList.toggle('on', b.dataset.v === (S.loop_mode || 'once'))); }
$('#bSaveRoute').onclick = () => {
  if (!plan) return toast('Build a route first.', 'warn');
  promptModal('Save route', 'Route name', `Route ${new Date().toLocaleDateString()}`, async name => {
    await post('/api/routes', {name, path: plan.path, stops: stops.map(s => s.p), distance: plan.distance, preset: S.preset, loop_mode: S.loop_mode});
    toast('Route saved'); loadRoutes();
  });
};
$('#bExportGpx').onclick = () => { if (!plan) return toast('Build a route first.', 'warn'); exportGpx('Route', plan.path); };
async function exportGpx(name, path) {
  try {
    const xml = await post('/api/gpx/export', {name, path});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([xml], {type: 'application/gpx+xml'}));
    a.download = (name.replace(/[^\w\- ]+/g, '').trim() || 'route') + '.gpx'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { fail(e); }
}
$('#bImportGpx').onclick = () => $('#gpxFile').click();
$('#gpxFile').onchange = async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  try {
    const r = await post('/api/gpx/import', {text: await f.text()});
    const name = r.name || f.name.replace(/\.gpx$/i, '');
    await post('/api/routes', {name, path: r.path, stops: [r.path[0], r.path[r.path.length - 1]], distance: pathLen(r.path), imported: true});
    showSavedRoute({path: r.path}); toast(`Imported “${name}”`); loadRoutes();
  } catch (e2) { fail(e2); }
};
function showSavedRoute(r) {
  stops = [{p: r.path[0], name: 'Start'}, {p: r.path[r.path.length - 1], name: 'Finish'}];
  redrawStops(); plan = {path: r.path, distance: pathLen(r.path), roads: false}; drawPlan(r.path); renderRouteStats();
  map.fitBounds(L.latLngBounds(r.path), {padding: [80, 80]});
}
async function loadRoutes() {
  const list = await api('/api/routes');
  $('#routeList').innerHTML = list.length ? list.slice().reverse().map(r => `
    <div class="item" data-id="${r.id}"><div class="emo">${icon(r.imported ? 'upload' : 'route')}</div>
      <div class="body"><b>${esc(r.name)}</b><small>${fmtDist(r.distance || pathLen(r.path))}${r.preset ? ' · ' + esc(presetById(r.preset)?.name || '') : ''}</small></div>
      <div class="acts"><button data-a="play" title="Play">${icon('play')}</button><button data-a="gpx" title="Export GPX">${icon('download')}</button><button data-a="del" title="Delete">${icon('trash')}</button></div></div>`).join('')
    : `<div class="empty">${icon('route')}Saved routes show up here</div>`;
  $$('#routeList .item').forEach(el => {
    const r = list.find(x => x.id === el.dataset.id);
    el.onclick = e => { const a = e.target.closest('button')?.dataset.a;
      if (a === 'play') { e.stopPropagation(); if (r.preset) setPreset(r.preset); if (r.loop_mode) { saveSetting({loop_mode: r.loop_mode}); paintLoop(); } showSavedRoute(r); startRoute(r.path); }
      else if (a === 'gpx') { e.stopPropagation(); exportGpx(r.name, r.path); }
      else if (a === 'del') { e.stopPropagation(); if (confirm(`Delete “${r.name}”?`)) api('/api/routes/' + r.id, 'DELETE').then(loadRoutes); }
      else showSavedRoute(r); };
  });
  window._routes = list;
}

// ---------------------------------------------------------------- places --
const EMOJIS = ['📍', '🏠', '🏢', '🏫', '☕', '🍔', '🛍️', '🏋️', '🌳', '🏖️', '✈️', '🎮', '❤️', '⭐', '🎯', '🗽'];
async function loadPlaces() {
  const list = await api('/api/places'); window._places = list;
  const f = $('#placeFilter').value.trim().toLowerCase();
  const shown = list.filter(p => !f || p.name.toLowerCase().includes(f)).reverse();
  $('#placeList').innerHTML = shown.length ? shown.map(p => `
    <div class="item" data-id="${p.id}"><div class="emo">${esc(p.emoji || '📍')}</div>
      <div class="body"><b>${esc(p.name)}</b><small>${esc(p.detail || fmtLL(p.lat, p.lon))}</small></div>
      <div class="acts"><button data-a="tp" title="Teleport">${icon('zap')}</button><button data-a="edit" title="Rename">${icon('edit')}</button><button data-a="del" title="Delete">${icon('trash')}</button></div></div>`).join('')
    : `<div class="empty">${icon('star')}${list.length ? 'No matches' : 'Save places with the ★ button or right-click the map'}</div>`;
  $$('#placeList .item').forEach(el => {
    const p = list.find(x => x.id === el.dataset.id);
    el.onclick = e => { const a = e.target.closest('button')?.dataset.a;
      if (a === 'tp') { e.stopPropagation(); teleport(p.lat, p.lon, p.name); }
      else if (a === 'edit') { e.stopPropagation(); savePlaceDialog(p, true); }
      else if (a === 'del') { e.stopPropagation(); if (confirm(`Delete “${p.name}”?`)) api('/api/places/' + p.id, 'DELETE').then(loadPlaces); }
      else setTarget(p.lat, p.lon, p.name, p.detail); };
  });
}
$('#placeFilter').oninput = debounce(loadPlaces, 150);
function savePlaceDialog(p, editing) {
  let emoji = p.emoji || '📍';
  openModal(`<h2>${editing ? 'Edit place' : 'Save place'}</h2><p>${fmtLL(p.lat, p.lon)}</p>
    <label class="fl">Name</label><input id="mpName" value="${esc(p.name || '')}" placeholder="e.g. Home, Gym, Mom's">
    <label class="fl">Icon</label><div class="emojis" style="display:flex;flex-wrap:wrap;gap:6px">${EMOJIS.map(e => `<button class="btn icon emo-b" data-e="${e}" style="font-size:18px">${e}</button>`).join('')}</div>
    <div class="btn-row"><button class="btn grow" data-close>Cancel</button><button class="btn pri grow" id="mpSave">${icon('check')}Save</button></div>`);
  const paint = () => $$('.emo-b').forEach(b => b.style.borderColor = b.dataset.e === emoji ? 'var(--accent)' : '');
  $$('.emo-b').forEach(b => b.onclick = () => { emoji = b.dataset.e; paint(); }); paint();
  $('#mpName').focus();
  const save = async () => {
    const name = $('#mpName').value.trim() || p.name || fmtLL(p.lat, p.lon);
    try {
      if (editing) await api('/api/places/' + p.id, 'PUT', {name, emoji});
      else await post('/api/places', {name, emoji, lat: p.lat, lon: p.lon, detail: p.detail || ''});
      closeModal(); toast(editing ? 'Saved' : `Saved “${name}”`); loadPlaces();
    } catch (e) { fail(e); }
  };
  $('#mpSave').onclick = save; $('#mpName').onkeydown = e => { if (e.key === 'Enter') save(); };
}

// --------------------------------------------------------------- history --
async function loadHistory() {
  const list = await api('/api/history');
  $('#histList').innerHTML = list.length ? list.map(h => `
    <div class="item" data-id="${h.id}"><div class="emo">${icon('history')}</div>
      <div class="body"><b>${esc(h.name.split(',')[0])}</b><small>${timeAgo(h.t)} · ${esc(h.name.split(',').slice(1).join(',').trim() || fmtLL(h.lat, h.lon))}</small></div>
      <div class="acts"><button data-a="tp" title="Teleport">${icon('zap')}</button><button data-a="save" title="Save">${icon('star')}</button></div></div>`).join('')
    : `<div class="empty">${icon('history')}Places you teleport to show up here</div>`;
  $$('#histList .item').forEach(el => {
    const h = list.find(x => x.id === el.dataset.id);
    el.onclick = e => { const a = e.target.closest('button')?.dataset.a;
      if (a === 'tp') { e.stopPropagation(); teleport(h.lat, h.lon, h.name.split(',')[0]); }
      else if (a === 'save') { e.stopPropagation(); savePlaceDialog({lat: h.lat, lon: h.lon, name: h.name.split(',')[0], detail: h.name}); }
      else setTarget(h.lat, h.lon, h.name.split(',')[0], h.name.split(',').slice(1).join(',')); };
  });
}
$('#bClearHist').onclick = () => { if (confirm('Clear all history?')) api('/api/history', 'DELETE').then(loadHistory); };

// -------------------------------------------------------------- schedule --
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
async function loadSchedules() {
  const [list, places, routes] = await Promise.all([api('/api/schedules'), api('/api/places'), api('/api/routes')]);
  window._places = places; window._routes = routes;
  const desc = s => s.action === 'teleport' ? `Go to ${s.place_name || fmtLL(s.lat, s.lon)}` : s.action === 'route' ? `Play “${routes.find(r => r.id === s.route_id)?.name || 'route'}”` : 'Back to real GPS';
  const days = d => (d?.length === 7 || !d) ? 'Every day' : d.length === 5 && !d.includes(5) && !d.includes(6) ? 'Weekdays' : d.map(i => DAYS[i]).join(' ');
  $('#schedList').innerHTML = list.length ? list.map(s => `
    <div class="item" data-id="${s.id}"><div class="emo" style="font-weight:700;font-size:13px">${esc(s.time)}</div>
      <div class="body"><b>${esc(s.name || desc(s))}</b><small>${days(s.days)} · ${esc(desc(s))}</small></div>
      <input type="checkbox" class="switch" data-a="tog" ${s.enabled !== false ? 'checked' : ''} title="On/off">
      <div class="acts"><button data-a="del" title="Delete">${icon('trash')}</button></div></div>`).join('')
    : `<div class="empty">${icon('calendar')}No schedules yet</div>`;
  $$('#schedList .item').forEach(el => {
    const s = list.find(x => x.id === el.dataset.id);
    el.querySelector('[data-a=tog]').onclick = e => { e.stopPropagation(); api('/api/schedules/' + s.id, 'PUT', {enabled: e.target.checked}); };
    el.querySelector('[data-a=del]').onclick = e => { e.stopPropagation(); if (confirm('Delete this schedule?')) api('/api/schedules/' + s.id, 'DELETE').then(loadSchedules); };
    el.onclick = e => { if (!e.target.closest('input,button')) scheduleDialog(s); };
  });
}
$('#bNewSched').onclick = () => scheduleDialog();
function scheduleDialog(s) {
  const places = window._places || [], routes = window._routes || [];
  s = s || {time: '09:00', days: [0, 1, 2, 3, 4, 5, 6], action: places.length ? 'teleport' : 'reset', enabled: true};
  let days = [...(s.days || [0, 1, 2, 3, 4, 5, 6])];
  openModal(`<h2>${s.id ? 'Edit' : 'New'} schedule</h2><p>Runs while ${esc(APP.name)} is open and your iPhone is connected.</p>
    <label class="fl">Name (optional)</label><input id="sdName" value="${esc(s.name || '')}" placeholder="e.g. Morning commute">
    <div style="display:flex;gap:10px"><div style="flex:1"><label class="fl">Time</label><input type="time" id="sdTime" value="${esc(s.time)}"></div>
    <div style="flex:1"><label class="fl">Speed</label><select id="sdPreset"><option value="">Keep current</option>${PRESETS.map(p => `<option value="${p.id}" ${s.preset === p.id ? 'selected' : ''}>${p.name}</option>`).join('')}</select></div></div>
    <label class="fl">Days</label><div class="days" id="sdDays">${DAYS.map((d, i) => `<button data-d="${i}">${d[0]}${d[1]}</button>`).join('')}</div>
    <label class="fl">Action</label><select id="sdAction">
      <option value="teleport" ${s.action === 'teleport' ? 'selected' : ''} ${places.length ? '' : 'disabled'}>Go to a saved place${places.length ? '' : ' (save a place first)'}</option>
      <option value="route" ${s.action === 'route' ? 'selected' : ''} ${routes.length ? '' : 'disabled'}>Play a saved route${routes.length ? '' : ' (save a route first)'}</option>
      <option value="reset" ${s.action === 'reset' ? 'selected' : ''}>Go back to real GPS</option></select>
    <div id="sdPlaceW"><label class="fl">Place</label><select id="sdPlace">${places.map(p => `<option value="${p.id}" ${s.place_id === p.id ? 'selected' : ''}>${esc((p.emoji || '') + ' ' + p.name)}</option>`).join('')}</select></div>
    <div id="sdRouteW"><label class="fl">Route</label><select id="sdRoute">${routes.map(r => `<option value="${r.id}" ${s.route_id === r.id ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></div>
    <div class="btn-row"><button class="btn grow" data-close>Cancel</button><button class="btn pri grow" id="sdSave">${icon('check')}Save</button></div>`);
  const paint = () => {
    $$('#sdDays button').forEach(b => b.classList.toggle('on', days.includes(+b.dataset.d)));
    const a = $('#sdAction').value; $('#sdPlaceW').hidden = a !== 'teleport'; $('#sdRouteW').hidden = a !== 'route';
  };
  $$('#sdDays button').forEach(b => b.onclick = () => { const d = +b.dataset.d; days = days.includes(d) ? days.filter(x => x !== d) : [...days, d].sort(); paint(); });
  $('#sdAction').onchange = paint; paint();
  $('#sdSave').onclick = async () => {
    if (!days.length) return toast('Pick at least one day.', 'warn');
    const action = $('#sdAction').value;
    const d = {name: $('#sdName').value.trim(), time: $('#sdTime').value || '09:00', days, action, preset: $('#sdPreset').value || null, enabled: s.enabled !== false};
    if (action === 'teleport') { const p = places.find(x => x.id === $('#sdPlace').value); if (!p) return; Object.assign(d, {place_id: p.id, place_name: p.name, lat: p.lat, lon: p.lon}); }
    if (action === 'route') { d.route_id = $('#sdRoute').value; if (!d.route_id) return; }
    try { s.id ? await api('/api/schedules/' + s.id, 'PUT', d) : await post('/api/schedules', d); closeModal(); toast('Schedule saved'); loadSchedules(); }
    catch (e) { fail(e); }
  };
}

// ------------------------------------------------------------ speed dock --
const presetById = id => PRESETS.find(p => p.id === id);
const targetKmh = () => S.custom_kmh || presetById(S.preset)?.kmh || 5;
const SL_MIN = 1, SL_MAX = 1000;
const posToKmh = p => SL_MIN * Math.pow(SL_MAX / SL_MIN, p / 1000);
const kmhToPos = k => 1000 * Math.log(Math.max(SL_MIN, Math.min(SL_MAX, k)) / SL_MIN) / Math.log(SL_MAX / SL_MIN);
function renderPresets() {
  $('#presets').innerHTML = PRESETS.map(p => `<button class="preset ${p.id === S.preset && !S.custom_kmh ? 'on' : p.id === S.preset ? 'on' : ''}" data-p="${p.id}" title="${p.name} — ${fmtSpeed(p.kmh)} ${unitLabel()}${p.profile === 'traffic' ? ' with stop-and-go' : p.profile === 'city' ? ' with stops at lights' : ''}">${icon(p.icon)}<b>${p.name}</b><small>${fmtSpeed(p.kmh)}</small></button>`).join('');
  $$('#presets .preset').forEach(b => b.onclick = () => setPreset(b.dataset.p));
}
async function setPreset(id) {
  S.preset = id; S.custom_kmh = null; renderPresets(); renderSpeed(); renderRouteStats(); renderTarget();
  try { await post('/api/speed', {preset: id}); } catch (e) { fail(e); }
  if (stops.length > 1 && S.follow_roads) replan();
}
const pushSpeed = debounce(k => post('/api/speed', {kmh: k}).catch(fail), 150);
function setCustom(kmh) {
  kmh = Math.max(0.5, Math.min(1200, kmh));
  const p = presetById(S.preset);
  S.custom_kmh = p && Math.abs(p.kmh - kmh) < 0.05 ? null : kmh;
  renderSpeed(); renderRouteStats(); renderTarget(); pushSpeed(S.custom_kmh || p.kmh);
}
function renderSpeed() {
  const k = targetKmh(), pos = kmhToPos(k), sl = $('#spSlider');
  if (document.activeElement !== sl) sl.value = pos;
  sl.style.setProperty('--fill', (pos / 10) + '%');
  if (document.activeElement !== $('#spTarget')) $('#spTarget').value = fmtSpeed(k);
  $('#spTargetUnit').textContent = $('#spUnit').textContent = unitLabel();
  $('#spReset').hidden = !S.custom_kmh;
  const p = presetById(S.preset);
  $('#spLabel').textContent = (p?.name || '') + (S.custom_kmh ? ' · custom speed' : '');
}
$('#spSlider').oninput = e => { const k = posToKmh(+e.target.value); e.target.style.setProperty('--fill', (e.target.value / 10) + '%'); $('#spTarget').value = fmtSpeed(k); setCustom(k); };
$('#spTarget').onchange = e => { const v = parseFloat(e.target.value); if (v > 0) setCustom(fromUnit(v)); else renderSpeed(); };
$('#spTarget').onkeydown = e => { if (e.key === 'Enter') e.target.blur(); };
$('#spMinus').onclick = () => setCustom(targetKmh() / 1.1);
$('#spPlus').onclick = () => setCustom(targetKmh() * 1.1);
$('#spReset').onclick = () => setPreset(S.preset);
$('#tWobble').onclick = () => { saveSetting({wobble: !S.wobble}); paintToggles(); toast(S.wobble ? 'Natural GPS wobble on' : 'Wobble off — perfectly straight lines'); };
let follow = false;
function setFollow(on, quiet) { follow = on; paintToggles(); if (on && STATE.current) map.panTo(STATE.current); if (!quiet) toast(on ? 'Map follows you' : 'Follow off'); }
$('#tFollow').onclick = () => setFollow(!follow);
function paintToggles() { $('#tWobble').classList.toggle('on', !!S.wobble); $('#tFollow').classList.toggle('on', follow); }

$('#bPlay').onclick = playPause;
$('#bStop').onclick = stopMotion;
async function playPause() {
  const m = STATE.motion || {};
  try {
    if (m.mode === 'route') { STATE = {...STATE, ...(await post(m.paused ? '/api/route/resume' : '/api/route/pause'))}; render(); return; }
    if (plan && stops.length > 1) return startRoute();
    if (target) return travel(target.lat, target.lon);
    toast('Pick a spot to travel to, or build a route first.', 'warn');
  } catch (e) { fail(e); }
}
async function stopMotion() {
  try { STATE = {...STATE, ...(await post('/api/route/stop'))}; render(); if (mk.line && !stops.length) { mk.line.remove(); mk.line = null; } } catch (e) { fail(e); }
}

// -------------------------------------------------------------- joystick --
const keys = new Set();
const KEYV = {w: [0, 1], arrowup: [0, 1], s: [0, -1], arrowdown: [0, -1], a: [-1, 0], arrowleft: [-1, 0], d: [1, 0], arrowright: [1, 0]};
let padVec = [0, 0], joySent = false;
function joyVec() {
  let x = padVec[0], y = padVec[1];
  keys.forEach(k => { x += KEYV[k][0]; y += KEYV[k][1]; });
  const m = Math.hypot(x, y); return m > 1 ? [x / m, y / m] : [x, y];
}
setInterval(() => {
  const [x, y] = joyVec(), active = Math.hypot(x, y) > 0.05;
  if (resettingGps || (!active && !joySent)) return;
  if (active && STATE.state !== 'connected') return;
  if (active && !STATE.current) { keys.clear(); padVec = [0, 0]; return toast('Teleport somewhere first, then walk with the joystick.', 'warn'); }
  joySent = active;
  post('/api/joystick', {x, y}).catch(() => {});
}, 200);
const typing = e => /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) && e.target.type !== 'checkbox' && e.target.type !== 'range';
document.addEventListener('keydown', e => {
  if (typing(e)) return;
  const k = e.key.toLowerCase();
  if (KEYV[k] && !e.ctrlKey && !e.metaKey && !e.altKey) { if (!keys.size && !follow && STATE.current) setFollow(true, true); keys.add(k); e.preventDefault(); return; }
  if (k === ' ') { e.preventDefault(); playPause(); }
  else if (k === 'escape') { if (!$('#modalBg').hidden) closeModal(); else stopMotion(); }
  else if (k === '/') { e.preventDefault(); $('#q').focus(); }
});
document.addEventListener('keyup', e => keys.delete(e.key.toLowerCase()));
window.addEventListener('blur', () => keys.clear());
$('#bJoy').onclick = () => { const on = $('#joypad').hidden; $('#joypad').hidden = !on; $('#bJoy').classList.toggle('pri', on); if (on) toast('Drag the stick, or use W A S D / arrow keys'); };
(() => {
  const pad = $('#joypad'), stick = $('#stick'); let id = null;
  const move = e => {
    const r = pad.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, R = r.width / 2 - 28;
    let dx = e.clientX - cx, dy = e.clientY - cy; const m = Math.hypot(dx, dy); if (m > R) { dx *= R / m; dy *= R / m; }
    stick.style.transform = `translate(${dx}px,${dy}px)`; padVec = [dx / R, -dy / R];
  };
  pad.addEventListener('pointerdown', e => { id = e.pointerId; pad.setPointerCapture(id); move(e); });
  pad.addEventListener('pointermove', e => { if (e.pointerId === id) move(e); });
  const end = () => { id = null; stick.style.transform = ''; padVec = [0, 0]; };
  pad.addEventListener('pointerup', end); pad.addEventListener('pointercancel', end);
})();

// ---------------------------------------------------------- state render --
let lastPos = null;
async function poll() {
  try { STATE = await api('/api/state'); render(); } catch {}
  setTimeout(poll, 600);
}
function render() {
  const st = STATE.state || 'disconnected', pill = $('#statusPill');
  pill.className = 'status glass ' + st;
  const dv = STATE.device;
  $('.stext', pill).innerHTML = st === 'connected' ? `${esc(dv?.name || 'iPhone')} <span class="muted" style="font-weight:500">· iOS ${esc(dv?.ios || '')}</span>`
    : st === 'connecting' ? `<span class="spin"></span>&nbsp;${esc(STATE.step || 'Connecting…')}`
    : st === 'reconnecting' ? 'Reconnecting…' : 'Connect iPhone';
  $('.s-ico', pill).outerHTML = icon(dv?.wifi ? 'wifi' : 'usb', 's-ico');

  if (st === 'connected' && !S.onboarded && S.terms_accepted) { saveSetting({onboarded: true}); if ($('#modalBody .steps-dots')) { closeModal(); } }
  const cur = STATE.current;
  setMe(cur);
  $('#curLoc').textContent = STATE.gps_reset === 'failed' ? 'GPS reset failed — the phone may still use a simulated location'
    : STATE.gps_reset === 'pending' ? 'Clearing simulated location…'
    : cur ? fmtLL(cur[0], cur[1])
    : STATE.gps_reset === 'sent' ? 'Simulation ended — check your location on the phone'
    : 'No simulated coordinates (check real GPS on the phone)';
  if (cur && follow && (!lastPos || distM(lastPos, cur) > 0.5)) map.panTo(cur, {animate: true, duration: .6});
  lastPos = cur;

  const m = STATE.motion || {};
  $('#spNow').textContent = m.mode === 'idle' || !m.mode ? '0' : fmtSpeed(m.speed_kmh || 0);
  $('#bPlay').innerHTML = icon(m.mode === 'route' && !m.paused ? 'pause' : 'play');
  const pr = $('#progress');
  if (m.mode === 'route' && m.route) {
    pr.hidden = false;
    const pct = m.route.length ? (100 * m.route.done / m.route.length) : 0;
    $('#progBar').style.width = pct.toFixed(1) + '%';
    $('#progLeft').textContent = `${m.paused ? 'Paused · ' : ''}${fmtDist(m.route.done)} of ${fmtDist(m.route.length)}`;
    $('#progRight').textContent = `${fmtDur(m.route.eta_s)} left · ${fmtDur(m.route.elapsed_s)} elapsed`;
  } else if (m.mode === 'joystick') {
    pr.hidden = false; $('#progBar').style.width = '0'; $('#progLeft').textContent = 'Joystick'; $('#progRight').textContent = '';
  } else pr.hidden = true;
  if (m.finished && m.finished !== render._fin) { if (render._fin !== undefined) toast('Arrived 🎉'); render._fin = m.finished; }

  const cd = m.cooldown;
  $('#cooldownChip').hidden = !(cd && S.cooldown_warnings);
  if (cd) $('#cooldownTxt').textContent = `Cooldown ${fmtDur(cd.left_s)} · jumped ${fmtDist(cd.km * 1000)}`;

  const up = STATE.update;
  $('#updateChip').hidden = !up; if (up) $('#updateTxt').textContent = `Update ${up.version} available`;
  renderTarget.throttle = (renderTarget.throttle || 0) + 1; if (target && renderTarget.throttle % 5 === 0) renderTarget();
}

// ------------------------------------------------------------- settings --
async function saveSetting(patch) { Object.assign(S, patch); try { S = await post('/api/settings', patch); } catch (e) { fail(e); } }
function applyTheme() {
  document.documentElement.dataset.theme = S.theme;
  $('#bTheme').innerHTML = icon(S.theme === 'light' ? 'sun' : 'moon');
  $('meta[name=theme-color]').content = S.theme === 'light' ? '#eef1f6' : '#0b0d12';
}
$('#bTheme').onclick = () => { saveSetting({theme: S.theme === 'light' ? 'dark' : 'light'}); applyTheme(); if (map && (S.map_layer || 'auto') === 'auto') applyLayer(); };
$('#bLayers').onclick = e => { e.stopPropagation(); $('#layerMenu').classList.toggle('show'); };
$('#bSettings').onclick = () => openSettings();
$('#bPhone').onclick = () => openPhone();
$('#statusPill').onclick = () => openConnect();
$('#bCenter').onclick = () => { if (STATE.current) map.flyTo(STATE.current, Math.max(map.getZoom(), 16), {duration: .7}); else toast('No simulated location yet.', 'warn'); };
let resettingGps = false;
async function restoreGps() {
  if (resettingGps) return false;
  resettingGps = true;
  const button = $('#bReset'), previous = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spin"></span>Restoring…';
  keys.clear(); padVec = [0, 0]; joySent = false;
  $('#stick').style.transform = '';
  try {
    STATE = await post('/api/reset');
    render();
    toast('Reset command sent and simulation session closed. Check your location in the phone map. Reconnect before simulating again.', 'ok', 9000);
    return true;
  } catch (e) {
    STATE = await api('/api/state').catch(() => STATE);
    render(); fail(e); return false;
  } finally {
    resettingGps = false; button.disabled = false; button.innerHTML = previous;
  }
}
$('#bReset').onclick = restoreGps;
$('#bTeleport').onclick = () => target && teleport(target.lat, target.lon, target.name);
$('#bTravel').onclick = () => target && travel(target.lat, target.lon);
$('#bSaveTarget').onclick = () => target && savePlaceDialog({lat: target.lat, lon: target.lon, name: target.name, detail: target.detail});
$('#bCoords').onclick = () => { const c = parseCoords($('#coords').value); if (!c) return toast('Use the format: 40.68925, -74.04450', 'bad'); setTarget(c[0], c[1], null, null); };
$('#coords').onkeydown = e => { if (e.key === 'Enter') $('#bCoords').click(); };
$('#updateChip').onclick = () => STATE.update?.url && openExternal(STATE.update.url);
$('#bSupport').onclick = () => openSupport();

// ---------------------------------------------------------------- modals --
function openModal(html) {
  $('#modalBody').innerHTML = html; $('#modalBg').hidden = false;
  $$('[data-close]', $('#modalBody')).forEach(b => b.onclick = closeModal);
  const f = $('#modalBody input:not([type=checkbox])'); if (f && !f.readOnly) setTimeout(() => f.focus(), 50);
}
function closeModal() { $('#modalBg').hidden = true; $('#modalBody').innerHTML = ''; }
$('#modalClose').onclick = closeModal;
$('#modalBg').onclick = e => { if (e.target.id === 'modalBg' && !$('#modalBg').dataset.lock) closeModal(); };
function promptModal(title, label, value, onOk) {
  openModal(`<h2>${esc(title)}</h2><label class="fl">${esc(label)}</label><input id="pmV" value="${esc(value)}">
    <div class="btn-row"><button class="btn grow" data-close>Cancel</button><button class="btn pri grow" id="pmOk">${icon('check')}Save</button></div>`);
  const ok = async () => { try { await onOk($('#pmV').value.trim() || value); closeModal(); } catch (e) { fail(e); } };
  $('#pmOk').onclick = ok; $('#pmV').onkeydown = e => { if (e.key === 'Enter') ok(); };
  $('#pmV').select();
}

function openConnect() {
  const st = STATE.state;
  if (st === 'connected') {
    const d = STATE.device || {};
    openModal(`<div class="wiz-ico">${icon('phone')}</div><h2>${esc(d.name || 'iPhone')}</h2>
      <p>iOS ${esc(d.ios)} · ${esc(d.model || '')} · connected over ${d.wifi ? 'Wi-Fi' : 'USB'}</p>
      <div class="set-group"><label class="switch-row"><span>Reconnect automatically<small>If the cable wiggles or the phone locks</small></span><input type="checkbox" class="switch" id="cAuto" ${S.auto_reconnect ? 'checked' : ''}></label></div>
      <div class="btn-row"><button class="btn grow" id="cRe">${icon('refresh')}Reconnect</button><button class="btn grow danger-soft" id="cDis">Disconnect</button></div>`);
    $('#cAuto').onchange = e => saveSetting({auto_reconnect: e.target.checked});
    $('#cRe').onclick = () => { closeModal(); doConnect(); };
    $('#cDis').onclick = async () => { if (await restoreGps()) closeModal(); };
    return;
  }
  wizard(S.terms_accepted ? 1 : 0);
}
async function doConnect() {
  try { STATE = {...STATE, ...(await post('/api/connect'))}; render(); toast(`Connected to ${STATE.device?.name || 'iPhone'}`); return true; }
  catch (e) { fail(e); return e; }
}

// ---------------------------------------------------------- setup wizard --
const TERMS = () => `<b>${esc(APP.name)} — Terms of use (summary)</b><br><br>
1. You must be 18 or older, or have permission from a parent or guardian.<br>
2. Only use ${esc(APP.name)} with devices you own or are allowed to manage.<br>
3. Don't use it to mislead people in ways that could harm them, to get around the law, or to commit fraud. You're responsible for how you use it.<br>
4. Some apps and games forbid location changing in their own terms and may suspend accounts. Use at your own risk.<br>
5. ${esc(APP.name)} uses Apple's built-in Developer Mode feature. It doesn't jailbreak or permanently modify your phone. Turning the app off or pressing “Real GPS” restores your real location.<br>
6. The software is provided “as is”, without warranty of any kind.<br><br>See the full EULA included with the app.`;
function wizard(step) {
  const steps = [
    () => `<div class="wiz-ico">${icon('pin')}</div><h2>Welcome to ${esc(APP.name)}</h2><p>Set your iPhone's location anywhere in the world — teleport, walk, drive or follow a route. Setup takes about 2 minutes.</p>
      <div class="terms">${TERMS()}</div>
      <label class="agree"><input type="checkbox" id="wzAgree" ${S.terms_accepted ? 'checked' : ''}>I agree to the terms of use</label>`,
    () => `<div class="wiz-ico">${icon('download')}</div><h2>Install Apple's driver</h2><p>Windows needs Apple's phone driver to talk to your iPhone. Install <b>one</b> of these (free):</p>
      <ul class="checks"><li>${icon('check')}<span><b>Apple Devices</b> from the Microsoft Store (recommended)</span></li><li>${icon('check')}<span>or <b>iTunes</b> from the Microsoft Store / apple.com</span></li></ul>
      <p class="tiny">On a Mac, nothing extra is needed.</p>`,
    () => `<div class="wiz-ico">${icon('usb')}</div><h2>Plug in &amp; trust</h2>
      <ul class="checks"><li>${icon('check')}<span>Connect your iPhone with a <b>data</b> cable (not charge-only)</span></li><li>${icon('check')}<span>Unlock it and tap <b>Trust This Computer</b>, then enter your passcode</span></li><li>${icon('check')}<span>iOS 17.4 or newer is required</span></li></ul>`,
    () => `<div class="wiz-ico">${icon('settings')}</div><h2>Turn on Developer Mode</h2>
      <p>On the iPhone go to <b>Settings › Privacy &amp; Security › Developer Mode</b>, switch it on and let the phone restart. After it restarts, tap <b>Turn On</b>.</p>
      <p class="tiny">Don't see “Developer Mode”? With the phone plugged in, press the button below to make it appear.</p>
      <button class="btn full" id="wzReveal">${icon('zap')}Show Developer Mode option</button>`,
    () => `<div class="wiz-ico">${icon('phone')}</div><h2>Connect</h2><p>Keep the iPhone unlocked for the first connection. The first time, ${esc(APP.name)} downloads Apple's developer tools (~20 MB).</p>
      <button class="btn pri full" id="wzConnect" style="height:48px">${icon('usb')}Connect my iPhone</button><div class="err" id="wzErr"></div>`,
  ];
  const n = steps.length;
  openModal(`<div class="steps-dots">${steps.map((_, i) => `<span class="${i <= step ? 'on' : ''}"></span>`).join('')}</div>${steps[step]()}
    <div class="btn-row">${step ? '<button class="btn" id="wzBack">Back</button>' : ''}<span style="flex:1"></span>${step < n - 1 ? `<button class="btn pri" id="wzNext">Next</button>` : ''}</div>`);
  $('#wzBack') && ($('#wzBack').onclick = () => wizard(step - 1));
  $('#wzNext') && ($('#wzNext').onclick = () => {
    if (step === 0) { if (!$('#wzAgree').checked) return toast('Please accept the terms to continue.', 'warn'); saveSetting({terms_accepted: true}); if (STATE.state === 'connected') { saveSetting({onboarded: true}); return closeModal(); } }
    wizard(step + 1);
  });
  $('#wzReveal') && ($('#wzReveal').onclick = async () => { try { await post('/api/reveal-devmode'); toast('Now check Settings › Privacy & Security on the iPhone'); } catch (e) { fail(e); } });
  $('#wzConnect') && ($('#wzConnect').onclick = async () => {
    const b = $('#wzConnect'); b.disabled = true; b.innerHTML = '<span class="spin"></span> Connecting…';
    const r = await doConnect();
    if (r === true) { saveSetting({onboarded: true}); closeModal(); }
    else { b.disabled = false; b.innerHTML = icon('refresh') + 'Try again'; $('#wzErr').textContent = r.message; }
  });
}

// ------------------------------------------------------------ settings --
function openSettings(focus) {
  const st = STATE.stats || {};
  const sw = (k, label, sub) => `<label class="switch-row"><span>${label}${sub ? `<small>${sub}</small>` : ''}</span><input type="checkbox" class="switch" data-k="${k}" ${S[k] ? 'checked' : ''}></label>`;
  openModal(`<h2>Settings</h2>
    <h3>Appearance</h3>
    <div class="set-group" style="padding:12px 14px">
      <div class="switch-row" style="padding-top:0"><span>Theme</span><div class="seg" style="width:180px" data-seg="theme"><button data-v="dark">Dark</button><button data-v="light">Light</button></div></div>
      <div class="switch-row" style="border-top:1px solid var(--line)"><span>Speed units</span><div class="seg" style="width:180px" data-seg="units"><button data-v="mph">mph</button><button data-v="kmh">km/h</button></div></div>
    </div>
    <h3>Movement</h3>
    <div class="set-group">
      ${sw('wobble', 'Natural GPS wobble', 'Adds tiny, realistic drift while moving')}
      ${sw('idle_drift', 'Drift while parked', 'Real phones never sit perfectly still')}
      ${sw('follow_roads', 'Follow roads by default', 'Routes and Travel use real streets and paths')}
      ${sw('cooldown_warnings', 'Travel cooldown warnings', 'Suggested wait after long jumps (for location-based games)')}
    </div>
    <h3>Connection</h3>
    <div class="set-group">
      ${sw('auto_connect', 'Connect on startup')}
      ${sw('auto_reconnect', 'Reconnect automatically')}
      ${sw('reset_on_exit', 'Restore real GPS when closing', 'Recommended')}
      ${sw('open_in_browser', 'Open in web browser instead of app window', 'Takes effect next launch')}
    </div>
    <div class="btn-row"><button class="btn grow" id="stGuide">${icon('info')}Setup guide</button><button class="btn grow" id="stPhone">${icon('phone')}Phone control</button></div>
    <h3>Your stats</h3>
    <div class="stats"><div class="stat"><b>${fmtDist(st.distance_m || 0)}</b><small>simulated travel</small></div><div class="stat"><b>${st.teleports || 0}</b><small>teleports</small></div><div class="stat"><b>${(window._places || []).length}</b><small>saved places</small></div></div>
    <h3>About</h3>
    <p class="tiny" style="margin:0">${esc(APP.name)} ${esc(APP.version)} — free &amp; open source (GPL-3.0).${APP.github_repo ? ` <a class="link ext" href="https://github.com/${esc(APP.github_repo)}">GitHub</a>` : ''}${APP.donate_url ? ` · <a class="link ext" href="${esc(APP.donate_url)}">Buy me a coffee ☕</a>` : ''}<br>
    Maps: OpenFreeMap, OpenMapTiles, © OpenStreetMap contributors, Esri imagery. Search: Photon by komoot. Routing: FOSSGIS OSRM.
    Built on pymobiledevice3, Leaflet and MapLibre.</p>`);
  $$('#modalBody .switch[data-k]').forEach(i => i.onchange = () => { saveSetting({[i.dataset.k]: i.checked}); if (i.dataset.k === 'wobble') paintToggles(); if (i.dataset.k === 'follow_roads') { $('#optRoads').checked = i.checked; replan(); } });
  $$('#modalBody [data-seg]').forEach(seg => {
    const k = seg.dataset.seg, paint = () => seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === S[k]));
    seg.querySelectorAll('button').forEach(b => b.onclick = () => { saveSetting({[k]: b.dataset.v}); paint(); if (k === 'theme') { applyTheme(); if ((S.map_layer || 'auto') === 'auto') applyLayer(); } if (k === 'units') { renderPresets(); renderSpeed(); renderRouteStats(); renderTarget(); } });
    paint();
  });
  $('#stGuide').onclick = () => wizard(0);
  $('#stPhone').onclick = () => openPhone();
}

async function openPhone() {
  const lan = await api('/api/lan');
  const wasOn = lan.enabled;
  openModal(`<div class="wiz-ico">${icon('phone')}</div><h2>Control from your phone</h2>
    <p>Move your location from any phone or tablet on the same Wi-Fi — handy when you're away from the PC.</p>
    <div class="set-group"><label class="switch-row"><span>Allow phone control<small>Protected by a private access key</small></span><input type="checkbox" class="switch" id="lanOn" ${lan.enabled ? 'checked' : ''}></label></div>
    <div id="lanBody"></div>`);
  const paint = async on => {
    const l = await api('/api/lan');
    if (!on) { $('#lanBody').innerHTML = ''; return; }
    if (!wasOn) { $('#lanBody').innerHTML = `<p style="margin-top:16px">${icon('info')} Restart ${esc(APP.name)} to turn this on. Windows may ask to allow network access — choose <b>Private networks</b>.</p>`; return; }
    let qr = '';
    try { const q = qrcode(0, 'M'); q.addData(l.url); q.make(); qr = q.createSvgTag(5, 0); } catch {}
    $('#lanBody').innerHTML = `<p style="margin-top:16px;text-align:center">Scan with your phone's camera:</p><div class="qr">${qr}</div>
      <div class="copybox"><span>${esc(l.url || 'No network found')}</span><button class="btn icon" id="lanCopy">${icon('copy')}</button></div>
      <div class="btn-row"><button class="btn grow" id="lanRegen">${icon('refresh')}New access key</button></div>
      <p class="tiny">Anyone with this link on your Wi-Fi can control your location. Make a new key to revoke old links.</p>`;
    $('#lanCopy').onclick = () => { navigator.clipboard?.writeText(l.url); toast('Link copied'); };
    $('#lanRegen').onclick = async () => { await post('/api/lan/regenerate'); paint(true); toast('New key made — old links no longer work'); };
  };
  $('#lanOn').onchange = e => { saveSetting({lan_enabled: e.target.checked}); paint(e.target.checked); };
  paint(lan.enabled);
}

// --------------------------------------------------------------- support --
function openExternal(url) { post('/api/open', {url}).catch(() => window.open(url, '_blank', 'noopener')); }
document.addEventListener('click', e => { const a = e.target.closest('a[href^="https://"]'); if (a) { e.preventDefault(); openExternal(a.href); } });
function openSupport(nudge) {
  const st = STATE.stats || {};
  openModal(`<div class="support">
    <div class="coffee">☕</div>
    <h2>${nudge ? `Enjoying ${esc(APP.name)}?` : `Support ${esc(APP.name)}`}</h2>
    <p>${esc(APP.name)} is free and open source, with no ads and no subscriptions. If it's useful to you, a small donation keeps it updated for new iOS versions.</p>
    ${st.distance_m > 1000 ? `<div class="stats" style="grid-template-columns:1fr 1fr;margin-bottom:16px"><div class="stat"><b>${fmtDist(st.distance_m)}</b><small>you've traveled</small></div><div class="stat"><b>${st.teleports || 0}</b><small>teleports</small></div></div>` : ''}
    ${APP.donate_url ? `<button class="btn coffee-btn full" id="spCoffee">☕&nbsp; Buy me a coffee</button>` : ''}
    ${APP.github_repo ? `<div class="btn-row"><button class="btn grow" id="spStar">${icon('star')}Star on GitHub</button><button class="btn grow" id="spIssue">${icon('flag')}Report a bug</button></div>` : ''}
    ${nudge ? `<button class="link" data-close style="margin:16px auto 0;display:block">Maybe later</button>` : ''}
  </div>`);
  $('#spCoffee') && ($('#spCoffee').onclick = () => { openExternal(APP.donate_url); saveSetting({donated_click: true}); closeModal(); toast('Thank you so much! 💜'); });
  $('#spStar') && ($('#spStar').onclick = () => openExternal(`https://github.com/${APP.github_repo}`));
  $('#spIssue') && ($('#spIssue').onclick = () => openExternal(`https://github.com/${APP.github_repo}/issues/new`));
}
// A single, gentle reminder after the app has been genuinely useful (never repeats).
function maybeNudge() {
  const st = STATE.stats || {};
  if (!APP.donate_url || S.support_nudged || !$('#modalBg').hidden) return;
  if ((st.teleports || 0) >= 20 || (st.distance_m || 0) >= 25000) { saveSetting({support_nudged: true}); openSupport(true); }
}

// --------------------------------------------------------- mobile sheet --
function setSheet(mode) {
  const p = $('#panel'); p.classList.remove('collapsed', 'expanded'); document.body.classList.remove('panel-collapsed', 'panel-expanded');
  if (mode) { p.classList.add(mode); document.body.classList.add('panel-' + mode); }
}
$('#grab').onclick = () => { const p = $('#panel'); setSheet(p.classList.contains('collapsed') ? '' : p.classList.contains('expanded') ? 'collapsed' : 'expanded'); };

// ------------------------------------------------------------------ boot --
let APP = {name: 'WanderPin', version: ''};
(async function boot() {
  hydrateIcons();
  let b;
  for (let i = 0; i < 40; i++) { try { b = await api('/api/boot'); break; } catch { await new Promise(r => setTimeout(r, 250)); } }
  if (!b) return toast('Could not start. Please restart the app.', 'bad', 60000);
  APP = b.app; S = b.settings; PRESETS = b.presets; MAPCFG = b.map; LAYERS = b.map.layers;
  document.title = APP.name; $('#brandName').textContent = APP.name; $$('.app-name').forEach(e => e.textContent = APP.name);
  applyTheme();
  initMap(b.last);
  renderLayerMenu(); renderPresets(); renderSpeed(); paintToggles(); paintLoop(); renderStops();
  $('#optRoads').checked = !!S.follow_roads;
  if (innerWidth <= 820) setSheet('collapsed');
  api('/api/places').then(l => window._places = l);
  api('/api/routes').then(l => window._routes = l);
  STATE = await api('/api/state').catch(() => ({})); render();
  $('#bSupport').hidden = !(APP.donate_url || APP.github_repo);
  if (!S.terms_accepted || !S.onboarded) wizard(S.terms_accepted ? 1 : 0);
  poll();
  setInterval(maybeNudge, 60000);
})();
