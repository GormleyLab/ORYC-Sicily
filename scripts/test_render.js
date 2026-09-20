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

/* A clickable stub button. The unit toggle is the one control whose whole
   job is to re-render, so the test drives the real listener rather than
   reaching past it into the module. */
function makeButton(dataset) {
  const listeners = [];
  const attrs = {};
  return {
    dataset, textContent: '',
    addEventListener(ev, fn) { if (ev === 'click') listeners.push(fn); },
    setAttribute(k, v) { attrs[k] = v; },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    click() { listeners.forEach(fn => fn()); },
    classList: { add() {}, remove() {}, toggle: () => false },
  };
}
const unitButtons = [makeButton({ unitSet: 'ft' }), makeButton({ unitSet: 'm' })];

const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeEl(id));
    return elements.get(id);
  },
  querySelectorAll: (sel) => (sel === '[data-unit-set]' ? unitButtons : []),
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
    // Pre-trip these two carry the whole value of the page, so they must not
    // silently render empty.
    'rehearsal-body': (weather.rehearsal || {}).available ? ['Passages'] : [],
    // With no archive yet this section shows why, not a table - so the needle
    // only applies when there is something to show.
    'stability-body': (weather.verification || {}).available
      ? ['stability, not accuracy'] : ['archive'],
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
    for (const bad of ['undefined', 'NaN', '[object Object]', 'null kt', 'null ft']) {
      if (out.includes(bad)) {
        const at = out.indexOf(bad);
        fail(`#${id} contains "${bad}" — …${out.slice(Math.max(0, at - 70), at + 30)}…`);
      }
    }
  }
  if (!failures) ok('no undefined/NaN found in any section');

  // Sea state is stored in metres and shown in feet. The conversion lives at
  // the render boundary, so a regression there is silent in a browser: the
  // page still shows a plausible number, just a third of the real sea. Check
  // the arithmetic against the data rather than only looking for the word.
  console.log('\nChecking sea state is shown in feet…');
  const M_TO_FT = 3.28084;

  // Pre-trip every real leg is beyond the horizon and the only heights on the
  // page are the berths' swell, so check whichever section actually has data.
  const samples = [];
  for (const l of weather.legs) {
    for (const w of l.windows || []) {
      if (w.max_wave_m != null) {
        samples.push({ id: 'legs-body', m: w.max_wave_m,
                       where: `${l.id} departing ${w.depart}` });
        break;
      }
    }
  }
  for (const b of weather.berths || []) {
    for (const o of b.options || []) {
      if (o.swell_m != null && o.swell_m > 0) {
        samples.push({ id: 'berths-body', m: o.swell_m,
                       where: `${o.name} on ${b.date}` });
        break;
      }
    }
  }

  // The "right now" cards print a sea height every day of the year, trip or
  // not. Whatever figure they show must be one of the model's metre values
  // multiplied out, not the metre value itself.
  const nowOut = html('now-body');
  const shown = [...nowOut.matchAll(/sea ([0-9.]+) ft/g)].map(m => m[1]);
  if (!shown.length) {
    ok('no sea height on the right-now cards in this run');
  } else {
    // Only the values at the hour the cards actually render. Compared against
    // the whole week's series this check is vacuous: somewhere in seven days
    // there is a metre figure that collides with a feet figure, and a card
    // left in metres passes. `ORYC` is a lexical const, not a property of the
    // sandbox, so it has to be evaluated inside the context to be reached.
    const api = vm.runInContext('ORYC', sandbox);
    const inFeet = new Set(), inMetres = new Set();
    for (const pt of Object.values(weather.series || {})) {
      const ser = (pt.sea || {}).series || {};
      const i = api.nowIndex(pt.time || []);
      const v = i < 0 ? null : (ser.wave_height || [])[i];
      if (v == null) continue;
      inFeet.add((v * M_TO_FT).toFixed(1));
      inMetres.add(v.toFixed(1));
    }
    const wrong = shown.filter(v => !inFeet.has(v));
    if (!inFeet.size) {
      fail('#now-body shows a sea height but no point has wave data at this hour');
    } else if (!wrong.length) {
      ok(`right-now cards: ${shown.length} sea heights, all converted (${shown.join(', ')} ft)`);
    } else if (wrong.some(v => inMetres.has(v))) {
      fail(`#now-body prints "sea ${wrong[0]} ft" but that is the metre figure ` +
           `unconverted — the label says feet and the number does not`);
    } else {
      fail(`#now-body sea height ${wrong[0]} ft is not this hour's wave height ` +
           `at any point (expected one of ${[...inFeet].join(', ')})`);
    }
  }

  if (!samples.length) {
    ok('no leg or berth height in this run — nothing further to convert');
  } else {
    for (const sample of samples.slice(0, 4)) {
      const out = html(sample.id);
      const ft = (sample.m * M_TO_FT).toFixed(1);
      if (out.includes(ft)) {
        ok(`${sample.id}: ${sample.m} m renders as ${ft} ft (${sample.where})`);
      } else if (out.includes(sample.m.toFixed(1))) {
        fail(`#${sample.id} still shows ${sample.m.toFixed(1)} for a ${sample.m} m ` +
             `height at ${sample.where} — expected ${ft} ft`);
      } else {
        fail(`#${sample.id} shows neither ${ft} ft nor the metre figure for ` +
             `${sample.where} — did the height stop rendering?`);
      }
    }
    if (html('legs-body').includes('<th>') && !/Sea ft/.test(html('legs-body'))) {
      fail('#legs-body hour table header does not say "Sea ft"');
    }
  }
  // --- the ft / m toggle ---------------------------------------------------
  // Switching units is a full re-render driven from `state`, so the risk is
  // not the arithmetic - it is a section that never re-runs, or one that does
  // and comes back subtly different. Drive the real button and check both.
  console.log('\nChecking the ft / m toggle…');
  {
    const api = vm.runInContext('ORYC', sandbox);
    const beforeCharts = calls.charts;
    const feetHtml = {};
    for (const id of ['now-body', 'legs-body', 'berths-body']) feetHtml[id] = html(id);

    unitButtons[1].click();                       // switch to metres

    if (api.units() !== 'm') {
      fail(`clicking "m" left the unit at ${api.units()}`);
    } else {
      ok('toggle switched the unit to metres');
    }

    const metreShown = [...html('now-body').matchAll(/sea ([0-9.]+) m/g)].map(m => m[1]);
    const expected = new Set();
    for (const pt of Object.values(weather.series || {})) {
      const ser = (pt.sea || {}).series || {};
      const i = api.nowIndex(pt.time || []);
      const v = i < 0 ? null : (ser.wave_height || [])[i];
      if (v != null) expected.add(v.toFixed(1));
    }
    if (!metreShown.length) {
      fail('#now-body prints no "sea N m" after switching to metres — did it re-render?');
    } else if (metreShown.some(v => !expected.has(v))) {
      fail(`#now-body metre figure ${metreShown.find(v => !expected.has(v))} is not ` +
           `this hour's wave height (expected one of ${[...expected].join(', ')})`);
    } else {
      ok(`right-now cards in metres: ${metreShown.join(', ')} m`);
    }

    if (/Sea ft|<small>ft<\/small>/.test(html('legs-body'))) {
      fail('#legs-body still labels a column "ft" after the switch to metres');
    }
    if (html('now-body').includes(' ft')) {
      fail('#now-body still shows a ft figure after the switch to metres');
    }
    if (!html('status-line').includes('written notes quote feet')) {
      fail('#status-line does not warn that the prose stays in feet while the ' +
           'numbers are in metres');
    } else {
      ok('status strip flags that the written notes stay in feet');
    }
    if (calls.charts <= beforeCharts) {
      fail('the sea chart was not redrawn on a unit change — its axis is stale');
    } else {
      ok(`charts redrawn on the switch (${calls.charts - beforeCharts} rebuilt)`);
    }
    if (unitButtons[1].getAttribute('aria-pressed') !== 'true' ||
        unitButtons[0].getAttribute('aria-pressed') !== 'false') {
      fail('aria-pressed does not follow the active unit');
    }

    unitButtons[0].click();                       // and back to feet

    if (api.units() !== 'ft') {
      fail(`clicking "ft" left the unit at ${api.units()}`);
    }
    // Round-tripping must be exact. If a section renders differently the
    // second time, some piece of it is reading state it should not.
    if (html('status-line').includes('written notes quote feet')) {
      fail('#status-line still shows the metres caveat after switching back to feet');
    }
    const drifted = Object.keys(feetHtml).filter(id => html(id) !== feetHtml[id]);
    if (drifted.length) {
      fail(`switching to metres and back changed ${drifted.join(', ')} — ` +
           `the re-render is not idempotent`);
    } else {
      ok('ft → m → ft round-trips to byte-identical output');
    }
  }

  // Metres must not survive anywhere a height is printed.
  for (const id of ['now-body', 'legs-body', 'berths-body']) {
    const out = html(id);
    const stray = out.match(/(?:sea|swell)\s[^<]*?\d\s?m\b/i);
    if (stray) fail(`#${id} still prints a height in metres — "${stray[0]}"`);
  }

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
  // Pre-trip these two sections carry the whole value of the page.
  console.log('\nChecking the pre-trip value sections…');
  const reh = weather.rehearsal || {};
  if (reh.available) {
    const n = (reh.legs || []).length, m = (reh.berths || []).length;
    if (!n && !m) fail('rehearsal flagged available but carries no legs or berths');
    else ok(`rehearsal: ${n} legs, ${m} berths`);
    if (n && !html('rehearsal-body').includes(escFn(reh.legs[0].label.split(' (')[0])))
      fail('first rehearsal leg missing from the page');
  } else { ok('rehearsal not available this run (reported, not blank)'); }

  const ver = weather.verification || {};
  if (ver.available) {
    ok(`stability: ${ver.points_compared} points, ${ver.by_lead_time.length} lead buckets`);
    if (!html('stability-body').includes('stability, not accuracy'))
      fail('stability table missing the stability-not-accuracy caveat');
  } else { ok('stability not available yet (reason shown, not a blank table)'); }


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
