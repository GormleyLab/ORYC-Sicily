/* Renders the page against the real published data with a minimal DOM stub.
 *
 * The point is not to test the browser - it is to catch the most likely class
 * of bug in a two-language project: a field the Python pipeline renamed or
 * stopped emitting that the JavaScript still reads. That failure is silent in
 * a browser (undefined prints as "undefined") and invisible in a syntax check.
 *
 * Run: node scripts/test_render.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(ROOT, p), 'utf8');

let failures = 0;
const fail = (msg) => { failures++; console.error(`  FAIL  ${msg}`); };
const ok = (msg) => console.log(`  ok    ${msg}`);

// --- DOM stub -------------------------------------------------------------

function makeEl(id) {
  return {
    id, innerHTML: '', textContent: '', hidden: false, dataset: {},
    value: 0, min: 0, max: 0, style: {}, ctx: {},
    classList: { add() {}, remove() {}, toggle: () => false },
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {},
    querySelectorAll: () => [],
    closest: () => null,
    parentElement: { hidden: false },
  };
}

const calls = { mapInit: 0, charts: 0, layers: 0, markers: 0, polylines: 0, tiles: 0 };

function makeLeafletStub() {
  const chain = () => {
    const o = {
      addTo: () => o, bindPopup: () => o, setView: () => o,
      on: () => o, clearLayers: () => o, addLayer: () => o, remove: () => o,
    };
    return o;
  };
  return {
    map: () => { calls.mapInit++; return Object.assign(chain(), {
      fitBounds: () => {}, invalidateSize: () => {}, getBounds: () => ({}),
      scales: {},
    }); },
    tileLayer: () => { calls.tiles++; return chain(); },
    polyline: () => { calls.polylines++; return chain(); },
    circleMarker: () => { calls.markers++; return chain(); },
    marker: () => { calls.markers++; return chain(); },
    layerGroup: () => { calls.layers++; return chain(); },
    divIcon: () => ({}),
  };
}

function makeChartStub() {
  function Chart() { calls.charts++; this.destroy = () => {}; }
  Chart.defaults = { font: {}, color: '' };
  return Chart;
}

const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeEl(id));
    return elements.get(id);
  },
  querySelectorAll: () => [],
  body: {},
  documentElement: { getAttribute: () => null, setAttribute() {}, removeAttribute() {} },
  addEventListener() {},
};

const weather = JSON.parse(read('data/weather.json'));
const itinerary = JSON.parse(read('data/itinerary.json'));
const waypoints = JSON.parse(read('data/waypoints.json'));

const FILES = {
  'data/weather.json': weather,
  'data/itinerary.json': itinerary,
  'data/waypoints.json': waypoints,
};

const sandbox = {
  console,
  document,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  // charts.js reads theme tokens through getPropertyValue; a stub without it
  // threw inside init and the charts silently never drew.
  getComputedStyle: () => ({ fontFamily: 'sans-serif', getPropertyValue: () => '#000' }),
  fetch: (p) => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve(FILES[p]),
  }),
  setTimeout: (fn) => fn(),
  requestAnimationFrame: (fn) => fn(),
  Date,
  Math,
  JSON,
  Number,
  String,
  Object,
  Array,
  Promise,
  isNaN,
  // Recording stubs rather than `undefined`. With the libraries absent both
  // modules no-opped, so the test could not have caught the map and charts
  // never being initialised at all.
  L: makeLeafletStub(),
  Chart: makeChartStub(),
};
// In a browser `window === globalThis`, and UMD libraries assign themselves
// onto it. Stubbing `window` as a bare {} meant `window.L` / `window.Chart`
// were undefined and both modules returned early.
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
vm.createContext(sandbox);

// --- load ------------------------------------------------------------------

console.log('\nLoading frontend modules…');
for (const f of ['assets/sailing.js', 'assets/map.js', 'assets/charts.js']) {
  try {
    vm.runInContext(read(f), sandbox, { filename: f });
    ok(`loaded ${f}`);
  } catch (e) {
    fail(`${f} threw on load: ${e.message}`);
  }
}
try {
  vm.runInContext(read('assets/app.js'), sandbox, { filename: 'assets/app.js' });
  ok('loaded assets/app.js');
} catch (e) {
  fail(`app.js threw on load: ${e.message}`);
}

// --- render ----------------------------------------------------------------

setImmediate(() => {
  console.log('\nChecking rendered output…');

  const html = (id) => document.getElementById(id).innerHTML;

  // Before roughly a week out, the real trip dates sit beyond every model's
  // horizon and NO leg has a forecast. That is a legitimate state the page has
  // to handle, so the expectations adapt: with forecasts we demand the
  // departure table, without them we demand the beyond-horizon messaging.
  const hasForecast = weather.legs.some(l => l.status === 'forecast');
  const hasBerths = weather.berths.some(b => b.status === 'forecast');
  console.log(hasForecast
    ? '  (forecast data present — checking the passage planner)'
    : '  (all legs beyond the forecast horizon — checking the pre-trip state)');

  const sections = {
    'status-line': ['Updated', 'models'],
    'model-grid': ['IFS', 'ICON-2i', 'MFWAM'],
    'now-body': ['kt'],
    'legs-body': ['Course', 'Distance',
                  hasForecast ? 'recommended departure' : 'beyond the forecast horizon'],
    'berths-body': hasBerths ? ['open ', 'swell'] : ['Beyond the forecast horizon'],
    'itinerary-body': ['Portorosa', 'Lipari', 'Stromboli', 'Salina', 'Filicudi'],
    'notes-body': ['Dining', 'Moorings'],
    'briefing-body': [],
  };

  for (const [id, needles] of Object.entries(sections)) {
    const out = html(id);
    if (!out || out.length < 20) {
      fail(`#${id} rendered empty (${out.length} chars)`);
      continue;
    }
    const missing = needles.filter(n => !out.includes(n));
    if (missing.length) fail(`#${id} missing: ${missing.join(', ')}`);
    else ok(`#${id} rendered (${out.length} chars)`);
  }

  // The silent-failure hunt: undefined/NaN leaking into user-visible text.
  console.log('\nScanning for undefined values leaking into the page…');
  for (const id of Object.keys(sections)) {
    const out = html(id);
    for (const bad of ['undefined', 'NaN', '[object Object]', 'null kt', 'null m']) {
      if (out.includes(bad)) {
        const at = out.indexOf(bad);
        fail(`#${id} contains "${bad}" — …${out.slice(Math.max(0, at - 70), at + 30)}…`);
      }
    }
  }
  if (!failures) ok('no undefined/NaN found in any section');

  // Every leg and berth in the data must actually appear on the page.
  console.log('\nChecking data coverage…');
  const legsHtml = html('legs-body');
  const missingLegs = weather.legs.filter(l => !legsHtml.includes(l.label.split(' → ')[0]));
  if (missingLegs.length) fail(`${missingLegs.length} legs absent from the page`);
  else ok(`all ${weather.legs.length} legs rendered`);

  const berthsHtml = html('berths-body');
  const shownBerths = weather.berths.filter(b => b.options.length > 1 || b.status === 'forecast');
  const missingBerths = shownBerths.filter(b => !berthsHtml.includes(b.port));
  if (missingBerths.length) fail(`${missingBerths.length} berths absent from the page`);
  else ok(`all ${shownBerths.length} berths rendered`);

  const itinHtml = html('itinerary-body');
  // Compare against the escaped form - the page correctly escapes apostrophes
  // and ampersands, so a raw-substring match gives false negatives.
  const escFn = vm.runInContext('ORYC.esc', sandbox);
  const missingDays = itinerary.days.filter(
    d => !itinHtml.includes(escFn(d.headline.slice(0, 30))));
  if (missingDays.length) {
    missingDays.forEach(d => fail(`day ${d.day} (${d.port}) absent — headline: "${d.headline.slice(0, 40)}"`));
  }
  else ok(`all ${itinerary.days.length} itinerary days rendered`);

  // Windy deep links must be well-formed.
  const windyLinks = (legsHtml + berthsHtml).match(/https:\/\/www\.windy\.com\/\?[^"]+/g) || [];
  const badWindy = windyLinks.filter(u => !/^https:\/\/www\.windy\.com\/\?\w+,-?\d+\.\d+,-?\d+\.\d+,\d+$/.test(u));
  if (!windyLinks.length) fail('no Windy deep links rendered');
  else if (badWindy.length) fail(`malformed Windy links: ${badWindy.slice(0, 2).join(' ')}`);
  else ok(`${windyLinks.length} Windy deep links well-formed (e.g. ${windyLinks[0]})`);

  // The map and charts must actually have been initialised. `const ORYCMap`
  // at the top level of a classic script is a global lexical binding, not a
  // property of `window`, so a `window.ORYCMap` guard silently skips both.
  console.log('\nChecking map and chart initialisation…');
  if (!calls.mapInit) fail('ORYCMap.init never ran — the map would not render');
  else ok(`map initialised (${calls.tiles} tile layer, ${calls.polylines} legs, ${calls.markers} markers)`);
  if (!calls.charts) fail('ORYCCharts.init never ran — no charts would render');
  else ok(`${calls.charts} charts constructed`);

  // Escaping must be real, not decorative.
  const evil = escFn('<img src=x onerror=alert(1)>');
  if (evil.includes('<img')) fail('ORYC.esc does not escape HTML');
  else ok('ORYC.esc escapes HTML');

  console.log(failures
    ? `\n${failures} failure(s)\n`
    : '\nAll render checks passed.\n');
  process.exit(failures ? 1 : 0);
});
