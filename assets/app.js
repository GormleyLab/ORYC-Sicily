/* ORYC Aeolian Flotilla - page renderer.
   Renders the three JSON files the pipeline publishes. The browser makes no
   API calls: weather.json is pre-computed by the cron. */

(function () {
  'use strict';

  const { esc, chip, windArrow, num, height, units, windyLink, dayLabel, hourLabel,
          ago, verdictClass, compass, shelterColor, nowIndex } = ORYC;

  const $ = id => document.getElementById(id);
  const state = { weather: null, itinerary: null, waypoints: null };

  // --- theme ---------------------------------------------------------------
  // Day / dark / night-vision. Night is red-on-black to protect dark
  // adaptation - the fleet sails to Stromboli after dark.

  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem('oryc-theme'); } catch (e) {}
    mark(saved);

    document.querySelectorAll('[data-theme-set]').forEach(btn => {
      btn.addEventListener('click', () => {
        const want = btn.dataset.themeSet;
        let current = document.documentElement.getAttribute('data-theme');
        const next = current === want ? null : want;   // pressing again returns to system
        if (next) document.documentElement.setAttribute('data-theme', next);
        else document.documentElement.removeAttribute('data-theme');
        try {
          if (next) localStorage.setItem('oryc-theme', next);
          else localStorage.removeItem('oryc-theme');
        } catch (e) {}
        mark(next);
        if (typeof ORYCCharts !== 'undefined') ORYCCharts.refresh();
      });
    });
  }

  function mark(active) {
    document.querySelectorAll('[data-theme-set]').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.themeSet === active)));
  }

  // --- units ---------------------------------------------------------------
  // Feet or metres, numbers only. The stored data is metric and every figure
  // on the page is converted at render time, so switching is just a re-render
  // - there is no second copy of the data to keep in step.

  function initUnits() {
    markUnits();
    document.querySelectorAll('[data-unit-set]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.unitSet === ORYC.units()) return;
        ORYC.setUnits(btn.dataset.unitSet);
        markUnits();
        renderAll();
        if (typeof ORYCCharts !== 'undefined') ORYCCharts.refresh();
      });
    });
  }

  function markUnits() {
    document.querySelectorAll('[data-unit-set]').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.unitSet === ORYC.units())));
  }

  /** Re-run every weather section. The render functions all read from `state`
   *  and rewrite their own innerHTML, re-attaching their own listeners, so
   *  this is safe to call repeatedly - but an open "Hour-by-hour" panel is
   *  rebuilt collapsed, so its state is carried across by hand. */
  function renderAll() {
    if (!state.weather) return;

    const open = [];
    document.querySelectorAll('.hours').forEach(el => {
      if (!el.hidden) open.push(el.id);
    });

    renderStatus();
    renderPill();
    renderNow();
    renderBriefing();
    renderLegs();
    renderRehearsal();
    renderStability();
    renderBerths();

    open.forEach(id => {
      const box = $(id);
      if (box) box.hidden = false;
      document.querySelectorAll(`[data-hours="${id}"]`).forEach(btn => {
        btn.setAttribute('aria-expanded', 'true');
        btn.textContent = 'Hide hour-by-hour';
      });
    });
  }

  // --- boot ----------------------------------------------------------------

  initTheme();

  Promise.all([
    fetchJson('data/weather.json'),
    fetchJson('data/itinerary.json'),
    fetchJson('data/waypoints.json'),
  ]).then(([weather, itinerary, waypoints]) => {
    Object.assign(state, { weather, itinerary, waypoints });

    renderItinerary();
    renderNotes();

    if (!weather) {
      $('status-line').innerHTML =
        '<b>Forecast not published yet.</b> The itinerary below is complete; ' +
        'weather appears once the updater has run.';
      ['now', 'briefing', 'passages', 'berths', 'map', 'charts']
        .forEach(id => { const el = $(id); if (el) el.hidden = true; });
      return;
    }

    renderAll();
    initUnits();

    // These modules declare `const ORYCMap` / `const ORYCCharts` at the top
    // level of a classic script, which creates a global lexical binding - NOT
    // a property of `window`. Guarding on `window.ORYCMap` silently skipped
    // both, so the map and the charts never rendered at all.
    // The map and charts are presentation. If either fails, the briefing,
    // passage calls, berth rankings and every number above must still stand -
    // the same rule the AI briefing follows.
    try {
      if (typeof ORYCMap !== 'undefined') ORYCMap.init(weather, waypoints);
    } catch (e) {
      console.error('map failed to initialise', e);
      hideSection('map', 'The route map could not be drawn.');
    }
    try {
      if (typeof ORYCCharts !== 'undefined') ORYCCharts.init(weather);
    } catch (e) {
      console.error('charts failed to initialise', e);
      hideSection('charts', 'The wind and sea charts could not be drawn.');
    }
  }).catch(err => {
    console.error(err);
    $('status-line').innerHTML = '<b>Could not load site data.</b> ' + esc(err.message);
  });

  /** Replace a failed visual section with an honest note rather than leaving
   *  an empty box that reads as a broken page. */
  function hideSection(id, message) {
    const el = $(id);
    if (!el) return;
    const head = el.querySelector('.sec-head');
    el.innerHTML = (head ? head.outerHTML : '') +
      `<div class="card card-pad"><p class="small muted" style="margin:0">` +
      `${esc(message)} Every figure elsewhere on this page is unaffected.</p></div>`;
  }

  function fetchJson(path) {
    return fetch(path, { cache: 'no-cache' })
      .then(r => {
        if (!r.ok) {
          if (path.endsWith('weather.json')) return null;
          throw new Error(`${path}: HTTP ${r.status}`);
        }
        return r.json();
      })
      .catch(e => { if (path.endsWith('weather.json')) return null; throw e; });
  }

  // --- status --------------------------------------------------------------

  function renderStatus() {
    const w = state.weather;
    const live = w.stale ? 'warn' : '';
    const okCount = (w.models || []).filter(m => m.ok).length;

    $('status-line').innerHTML =
      `<i class="live-dot ${live}" aria-hidden="true"></i>` +
      `<span>Updated <b>${esc(ago(w.generated_at_utc || w.generated_at))}</b></span>` +
      `<span>·</span><span><b>${okCount}</b> of ${(w.models || []).length} models</span>` +
      (w.horizon_end ? `<span>·</span><span>reaches <b>${esc(dayLabel(w.horizon_end))}</b></span>` : '') +
      // Only the numbers follow the ft/m toggle. The briefing and the
      // pilot-book notes are prose written at build time and stay in feet, so
      // say so here rather than let a skipper trip over it mid-sentence.
      (ORYC.unitNote() ? `<span>·</span><span class="unit-note">${esc(ORYC.unitNote())}</span>` : '') +
      `<button class="disclose" id="model-toggle" aria-expanded="false">model runs</button>`;

    $('model-grid').innerHTML = (w.models || []).map(m => {
      let cls = 'model-row';
      if (!m.ok) cls += ' is-dead';
      else if (m.age_hours > (m.update_interval_hours || 12) * 2) cls += ' is-stale';
      return `<div class="${cls}" title="${esc(m.note || '')}">` +
        `<span class="mid">${esc(m.short)}</span>` +
        `<span class="muted">${esc(m.label)} · ${esc(m.resolution)}` +
        `${m.provides_gusts === false ? ' · no gust field' : ''}</span>` +
        `<span class="det">${m.ok ? esc(m.init_label) + ' · ' + num(m.age_hours, 1) + ' h' : 'unavailable'}</span>` +
      `</div>`;
    }).join('');

    const toggle = $('model-toggle'), panel = $('model-detail');
    toggle.addEventListener('click', () => {
      const open = panel.hidden;
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
    });

    // Notices, most urgent first.
    const n = [];
    if (w.simulated) {
      n.push(['danger', '◉', 'Preview mode — not the real trip dates',
        `Itinerary dates are shifted ${w.simulated_shift_days} days into the current ` +
        `forecast window to demonstrate the planner. Do not plan against this page.`]);
    }
    if (w.stale) {
      n.push(['warn', '▲', 'Forecast is stale',
        `The last update failed, so these figures are from an earlier run. ${esc(w.stale_reason || '')}`]);
    }
    $('notices').innerHTML = n.map(([k, ico, title, body]) =>
      `<div class="notice notice-${k}"><span class="ico" aria-hidden="true">${ico}</span>` +
      `<span><b>${esc(title)}</b>${body}</span></div>`).join('');
  }

  function renderPill() {
    const w = state.weather, el = $('pill-day');
    if (w.phase === 'underway' && w.trip_day) {
      $('pill-n').textContent = w.trip_day; $('pill-l').textContent = 'of 8';
    } else if (w.phase === 'pre-trip') {
      $('pill-n').textContent = w.days_to_departure;
      $('pill-l').textContent = w.days_to_departure === 1 ? 'day out' : 'days out';
    } else {
      $('pill-n').textContent = '⚓'; $('pill-l').textContent = 'done';
    }
    el.hidden = false;
  }

  // --- conditions now ------------------------------------------------------
  // Always has data, so the page carries real information even while every
  // trip date is still beyond the forecast horizon.

  function renderNow() {
    const series = state.weather.series || {};
    const moorings = (state.waypoints || {}).moorings || {};
    const ids = Object.keys(series).filter(id => moorings[id]);
    if (!ids.length) return;

    const first = series[ids[0]];
    const i = nowIndex(first.time);
    if (i < 0) return;

    $('now-time').textContent = `${dayLabel(first.time[i])} ${hourLabel(first.time[i])} local`;

    // One card per island - a dozen near-identical cards for the same island
    // would be noise. Values are the consensus across every model that has
    // data, not one model's reading: at 2 km ICON-2i sometimes resolves a
    // local acceleration the coarser models miss, and showing that alone as
    // a bare headline figure would mislead.
    const seen = new Set();
    const cards = [];

    ids.forEach(id => {
      const group = moorings[id].group || moorings[id].island;
      if (seen.has(group)) return;

      const p = series[id];
      const speeds = [], dirs = [];
      Object.values(p.models).forEach(m => {
        if (m.wind_speed_10m[i] != null) speeds.push(m.wind_speed_10m[i]);
        if (m.wind_direction_10m[i] != null) dirs.push(m.wind_direction_10m[i]);
      });
      if (!speeds.length) return;
      seen.add(group);

      const mean = speeds.reduce((a, b) => a + b, 0) / speeds.length;
      const lo = Math.min(...speeds), hi = Math.max(...speeds);
      const spread = hi - lo;
      const dir = ORYC.circularMean(dirs);
      const wave = p.sea && p.sea.series ? p.sea.series.wave_height[i] : null;

      // A wide spread is information, not noise - say so rather than hiding it.
      const disagree = spread > 8 && speeds.length > 1
        ? `<div class="spread">models ${num(lo)}–${num(hi)} kt</div>` : '';

      cards.push(
        `<div class="now-card">` +
          `<div class="pl">${esc(group)}</div>` +
          `<div class="ws">${num(mean)}<small>kt</small></div>` +
          `<div class="wd">${windArrow(dir, 12)} ${esc(compass(dir))}</div>` +
          disagree +
          (wave != null ? `<div class="sea">sea ${height(wave)} ${units()}</div>` : '') +
        `</div>`);
    });

    if (!cards.length) return;
    $('now-body').innerHTML = cards.join('');
    $('now').hidden = false;
  }

  // --- briefing ------------------------------------------------------------

  function renderBriefing() {
    const b = state.weather.briefing;
    const body = $('briefing-body');

    if (!b) {
      const w = state.weather;
      const msg = w.phase === 'pre-trip'
        ? `The written briefing begins once the trip dates come inside the forecast ` +
          `horizon. Until then the numbers above and below are live and current.`
        : `No written briefing in this run. Every passage call, berth ranking and chart ` +
          `below is computed directly from the model data and is unaffected.`;
      body.innerHTML = `<div class="card card-pad"><p class="muted small" style="margin:0">${msg}</p></div>`;
      return;
    }

    const sec = (t, x) => x ? `<h4>${esc(t)}</h4><p>${esc(x)}</p>` : '';
    const notes = (b.passage_notes || []).length
      ? `<h4>Passage notes</h4><ul>` + b.passage_notes.map(n =>
          `<li><strong>${esc(n.leg)}</strong> — ${esc(n.note)}</li>`).join('') + `</ul>` : '';
    const cautions = (b.cautions || []).length
      ? `<h4>Watch for</h4><ul>` + b.cautions.map(c => `<li>${esc(c)}</li>`).join('') + `</ul>` : '';

    body.innerHTML =
      `<div class="card card-pad briefing">` +
        `<div class="headline">${esc(b.headline)}</div>` +
        sec('Synopsis', b.synopsis) +
        sec('Overnight at the berth', b.overnight_anchorage) +
        sec('Tomorrow morning', b.tomorrow_morning) +
        notes + cautions +
        `<div class="by">` +
          (b.confidence ? `<span>Confidence <strong>${esc(b.confidence)}</strong>` +
            (b.confidence_note ? ` — ${esc(b.confidence_note)}` : '') + `</span>` : '') +
          `<span>${esc(b.model || 'Claude')}, from the data on this page</span>` +
        `</div>` +
      `</div>`;
  }

  // --- passages ------------------------------------------------------------

  function renderLegs() {
    $('legs-body').innerHTML = (state.weather.legs || []).map(legCard).join('');

    document.querySelectorAll('[data-hours]').forEach(btn => {
      btn.addEventListener('click', () => {
        const box = $(btn.dataset.hours);
        const open = box.hidden;
        box.hidden = !open;
        btn.setAttribute('aria-expanded', String(open));
        btn.textContent = open ? 'Hide hour-by-hour' : 'Hour-by-hour';
      });
    });
  }

  function legCard(leg) {
    const head =
      `<div class="leg-head">` +
        `<h3>${esc(leg.label.replace(' (optional)', '').replace(' (optional return)', ''))}</h3>` +
        `<span class="when">${esc(dayLabel(leg.date))}</span>` +
        (leg.status === 'forecast' ? chip(leg.verdict) : '') +
      `</div>`;

    const facts =
      `<div class="facts">` +
        `<div><div class="k">Course</div><div class="v">${windArrow(leg.bearing + 180, 12)}` +
          `${num(leg.bearing)}°<span class="muted" style="font-weight:400">${esc(leg.bearing_label)}</span></div></div>` +
        `<div><div class="k">Distance</div><div class="v">${num(leg.stated_nm)}<span class="muted" style="font-weight:400">nm</span></div></div>` +
        `<div><div class="k">Passage</div><div class="v">${esc(leg.duration_label)}</div></div>` +
      `</div>`;

    if (leg.status !== 'forecast') {
      const days = leg.available_in_days;
      return `<div class="card leg${leg.optional ? ' is-optional' : ''}">${head}${facts}` +
        `<div class="await">` +
          `<div class="ring" aria-hidden="true">${days != null ? esc(String(days)) + 'd' : '–'}</div>` +
          `<div class="txt">${esc(leg.message || 'Beyond the forecast horizon.')}` +
          `<div class="muted" style="margin-top:3px">${esc(leg.note || '')}</div></div>` +
        `</div>` +
        `<div class="card-foot">${windyLink(leg.midpoint.lat, leg.midpoint.lon, 'wind', 'Wind on this leg')}</div>` +
      `</div>`;
    }

    const best = leg.windows.find(w => w.depart === leg.recommended_window) || leg.windows[0];
    const cls = verdictClass(leg.verdict);

    const callout = best ? `<div class="callout ${cls}">` +
      `<div class="callout-top">` +
        `<span class="callout-time">${esc(best.depart)}</span>` +
        `<span class="callout-lab">recommended departure<br>arrive ${esc(best.arrive)}` +
        `${best.arrive_next_day ? ' next day' : ''}</span>` +
      `</div>` +
      `<div class="keynums">` +
        `<div><div class="k">Wind</div><div class="v">${num(best.max_wind_kt)}<small>kt</small></div></div>` +
        `<div><div class="k">Gust</div><div class="v">${num(best.max_gust_kt)}<small>kt</small></div></div>` +
        `<div><div class="k">Sea</div><div class="v">${height(best.max_wave_m)}<small>${units()}</small></div></div>` +
        `<div><div class="k">From</div><div class="v">${windArrow(best.wind_dir, 13)}${esc(best.wind_dir_label)}</div></div>` +
        `<div><div class="k">TWA</div><div class="v">${best.twa == null ? '–' : num(best.twa) + '°'}</div></div>` +
        `<div><div class="k">Force</div><div class="v">${num(best.beaufort.force)}</div></div>` +
        `<div class="pos"><div class="k">Point of sail</div><div class="v">${esc(best.point_of_sail)} · ${esc(best.reefing)}</div></div>` +
      `</div>` +
      `<div class="why">${esc(best.reasons.join('; '))}` +
      (leg.deteriorates_after ? ` Deteriorates for departures after <strong>${esc(leg.deteriorates_after)}</strong>.` : '') +
      `</div></div>` : '';

    const boxId = `h-${leg.id.replace(/[^a-z0-9]/gi, '')}`;

    // Stacked rows on phones; the same data as a table from 720px up. No
    // horizontal scrolling of the primary content on a handheld.
    const rows = leg.windows.map(w => {
      const b2 = w.depart === leg.recommended_window;
      return `<div class="hour-row${b2 ? ' is-best' : ''}">` +
        `<span class="t">${esc(w.depart)}</span>` +
        `<span class="d">` +
          `<span class="nw">${num(w.max_wind_kt)}–${num(w.max_gust_kt)} kt</span>` +
          `<span class="nw">${windArrow(w.wind_dir, 11)} ${esc(w.wind_dir_label)}</span>` +
          `<span class="nw">${height(w.max_wave_m)} ${units()}</span>` +
          `<span class="nw">${esc(w.point_of_sail)}</span>` +
        `</span>` +
        `${chip(w.verdict)}</div>`;
    }).join('');

    const tableRows = leg.windows.map(w => {
      const b2 = w.depart === leg.recommended_window;
      return `<tr${b2 ? ' class="is-best"' : ''}>` +
        `<td class="num">${esc(w.depart)}</td>` +
        `<td class="num muted">${esc(w.arrive)}${w.arrive_next_day ? '+1' : ''}</td>` +
        `<td class="num">${num(w.max_wind_kt)}</td>` +
        `<td class="num">${num(w.max_gust_kt)}</td>` +
        `<td>${windArrow(w.wind_dir, 12)} ${esc(w.wind_dir_label)}</td>` +
        `<td class="num">${height(w.max_wave_m)}</td>` +
        `<td class="num">${w.twa == null ? '–' : num(w.twa) + '°'}</td>` +
        `<td class="pos">${esc(w.point_of_sail)}</td>` +
        `<td>${chip(w.verdict)}</td></tr>`;
    }).join('');

    const hours =
      `<div class="hours" id="${boxId}" hidden>` +
        `<div class="only-phone">${rows}</div>` +
        `<table class="hours-table only-wide"><thead><tr>` +
          `<th>Depart</th><th>Arrive</th><th>Wind</th><th>Gust</th><th>From</th>` +
          `<th>Sea ${units()}</th><th>TWA</th><th>Point of sail</th><th>Call</th>` +
        `</tr></thead><tbody>${tableRows}</tbody></table>` +
      `</div>`;

    return `<div class="card leg${leg.optional ? ' is-optional' : ''}">` +
      head + facts + callout + hours +
      `<div class="card-foot">` +
        `<button class="disclose" data-hours="${boxId}" aria-expanded="false">Hour-by-hour</button>` +
        windyLink(leg.midpoint.lat, leg.midpoint.lon, 'wind', 'Windy') +
        (leg.arrive_by ? `<span>Arrive by <strong>${esc(leg.arrive_by)}</strong></span>` : '') +
        (leg.distance_warning ? `<span style="color:var(--caution)">▲ ${esc(leg.distance_warning)}</span>` : '') +
      `</div></div>`;
  }

  // --- daily rehearsal ------------------------------------------------------
  // Proves the analysis runs, every day, on real numbers - long before the
  // trip dates come inside any model's horizon.

  function renderRehearsal() {
    const r = state.weather.rehearsal;
    if (!r || !r.available) return;

    const legs = (r.legs || []).map(l => {
      const w = (l.windows || [])[0] || {};
      return `<div class="reh-leg">` +
        `<span class="lab">${esc(l.label.replace(' (optional)', '').replace(' (optional return)', ''))}</span>` +
        `${chip(l.verdict)}` +
        `<span class="det">` +
          `<span>sailed ${esc(dayLabel(l.date))}</span>` +
          `<span>depart ${esc(l.recommended_window || '-')}</span>` +
          `<span>${num(w.max_wind_kt)}–${num(w.max_gust_kt)} kt ${esc(w.wind_dir_label || '')}</span>` +
          `<span>${esc(w.point_of_sail || '')}</span>` +
          (l.deteriorates_after ? `<span>worse after ${esc(l.deteriorates_after)}</span>` : '') +
        `</span></div>`;
    }).join('');

    const berths = (r.berths || []).map(b => {
      const best = (b.options || []).slice().sort((x, y) => (y.score || 0) - (x.score || 0))[0];
      if (!best) return '';
      return `<div class="reh-leg">` +
        `<span class="lab">${esc(b.port)}</span>${chip(best.verdict)}` +
        `<span class="det"><span>night of ${esc(dayLabel(b.date))}</span>` +
        `<span>picks ${esc(best.name)}</span>` +
        `<span>${esc(best.reason)}</span></span></div>`;
    }).join('');

    $('rehearsal-body').innerHTML =
      (legs ? `<div class="card"><div class="leg-head"><h3>Passages</h3></div>${legs}</div>` : '') +
      (berths ? `<div class="card"><div class="leg-head"><h3>Berths</h3></div>${berths}</div>` : '');
    $('rehearsal').hidden = false;
  }

  // --- forecast stability ---------------------------------------------------

  function renderStability() {
    const v = state.weather.verification;
    const body = $('stability-body');
    if (!v) return;

    if (!v.available) {
      body.innerHTML = `<div class="card card-pad"><p class="small muted" style="margin:0">` +
        `${esc(v.reason || 'Not enough archived runs yet.')}</p></div>`;
      $('stability').hidden = false;
      return;
    }

    const max = Math.max(...v.by_lead_time.map(b => b.mean_wind_shift_kt), 1);
    const rows = v.by_lead_time.map(b =>
      `<tr><td>${esc(b.lead)}</td>` +
      `<td>${num(b.mean_wind_shift_kt, 1)} kt` +
      `<i class="stab-bar" style="width:${Math.round(b.mean_wind_shift_kt / max * 70)}px"></i></td>` +
      `<td>${num(b.max_wind_shift_kt, 1)} kt</td>` +
      `<td>${b.mean_dir_shift_deg == null ? '–' : num(b.mean_dir_shift_deg) + '°'}</td>` +
      `<td class="muted">${num(b.samples)}</td></tr>`).join('');

    body.innerHTML =
      `<div class="card">` +
        `<div class="card-pad" style="padding-bottom:4px">` +
          `<p class="small" style="margin:0 0 4px">How far a forecast for a given hour ` +
          `typically moved between model cycles, by how far ahead it was made. ` +
          `Smaller means the guidance is settling down.</p>` +
          `<p class="tiny muted" style="margin:0">` +
          `<strong>This is stability, not accuracy.</strong> The reference is the newest ` +
          `model run for the same hour, not an observation — a forecast can be perfectly ` +
          `stable and still wrong. Built from ${num(v.snapshots_compared)} archived runs ` +
          `since ${esc(v.oldest_run || '')}` +
          (v.runs_skipped_same_cycle ? `; ${num(v.runs_skipped_same_cycle)} run(s) skipped for ` +
            `sharing a model cycle with the current one` : '') + `.</p></div>` +
        `<div style="overflow-x:auto"><table class="stab"><thead><tr>` +
          `<th>Made this far ahead</th><th>Mean wind shift</th><th>Largest</th>` +
          `<th>Mean dir shift</th><th>Samples</th>` +
        `</tr></thead><tbody>${rows}</tbody></table></div>` +
      `</div>`;
    $('stability').hidden = false;
  }

  // --- berths --------------------------------------------------------------

  function renderBerths() {
    const list = (state.weather.berths || [])
      .filter(b => b.options.length > 1 || b.status === 'forecast');
    $('berths-body').innerHTML = list.map(berthCard).join('');
  }

  function berthCard(b) {
    const head =
      `<div class="leg-head">` +
        `<h3>${esc(b.port)}</h3>` +
        `<span class="when">${esc(dayLabel(b.date))} night</span>` +
      `</div>`;

    if (b.status !== 'forecast') {
      const list = b.options.map(o =>
        `<div class="opt"><div class="opt-top"><span class="opt-name">${esc(o.name)}` +
        (o.verified ? '' : `<span class="badge-unver" title="Exposure sector computed from coastline geometry, not read off a chart">unverified</span>`) +
        `</span></div><div class="why">${esc(o.shelter_note)}</div></div>`).join('');
      return `<div class="card">${head}<div class="card-pad">` +
        `<p class="small muted" style="margin:0 0 9px">Beyond the forecast horizon — ` +
        `options and their exposure shown for planning.</p>${list}</div></div>`;
    }

    const sorted = b.options.slice().sort((x, y) => (y.score || 0) - (x.score || 0));
    const lead = b.choice_matters
      ? `<p class="small" style="margin:0 0 9px"><strong>The choice matters tonight.</strong> ` +
        `${esc(sorted[0].name)} is meaningfully better sheltered.</p>`
      : `<p class="small muted" style="margin:0 0 9px">All options look comfortable — pick on convenience.</p>`;

    const list = sorted.map((o, i) => {
      const pct = o.score == null ? 0 : Math.round(o.score * 100);
      // A berth may be open to more than one arc, so exposed_sector is either
      // a single [from, to] or a list of them.
      const arcs = !o.exposed_sector ? []
        : (Array.isArray(o.exposed_sector[0]) ? o.exposed_sector : [o.exposed_sector]);
      const sector = arcs.length
        ? 'open ' + arcs.map(a => `${num(a[0])}–${num(a[1])}°`).join(', ')
        : 'enclosed';
      return `<div class="opt${i === 0 && b.choice_matters ? ' is-best' : ''}">` +
        `<div class="opt-top"><span class="opt-name">${esc(o.name)}` +
        (o.verified ? '' : `<span class="badge-unver" title="Exposure sector computed from coastline geometry, not read off a chart">unverified</span>`) +
        `</span>${chip(o.verdict)}</div>` +
        `<div class="why">${esc(o.reason)}</div>` +
        `<div class="nums">` +
          `<span>${windArrow(o.wind_dir, 11)} ${num(o.wind_kt)} kt ${esc(o.wind_dir_label || '')}</span>` +
          `<span>gust ${num(o.gust_kt)}</span>` +
          `<span>swell ${height(o.swell_m)} ${units()}</span>` +
          `<span>${esc(sector)}</span>` +
        `</div>` +
        (o.no_anchoring ? `<div class="warn">▲ Do not anchor — rocky. Buoys only.</div>` : '') +
        `<div class="meter"><i style="width:${pct}%;background:${shelterColor(o.verdict)}"></i></div>` +
      `</div>`;
    }).join('');

    return `<div class="card">${head}<div class="card-pad">${lead}${list}` +
      `<div style="margin-top:10px">${windyLink(sorted[0].lat, sorted[0].lon, 'waves', 'Swell here')}</div>` +
      `</div></div>`;
  }

  // --- itinerary -----------------------------------------------------------

  function renderItinerary() {
    $('itinerary-body').innerHTML = state.itinerary.days.map(dayCard).join('');
    document.querySelectorAll('[data-more]').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = $(btn.dataset.more);
        const clipped = p.classList.toggle('clipped');
        btn.textContent = clipped ? 'Read more' : 'Read less';
      });
    });
  }

  function dayCard(d, i) {
    const pid = `prose-${i}`;
    const long = (d.prose || '').length > 230;

    const tags = []
      .concat((d.flags || []).map(f => `<span class="tag flag">${esc(f)}</span>`))
      .concat(d.dining ? [`<span class="tag dinner">${esc(d.dining.label)}</span>`] : [])
      .concat((d.things_to_do || []).slice(0, 5).map(t => `<span class="tag">${esc(t)}</span>`))
      .join('');

    const links = (d.links || []).map(l =>
      `<a class="windy" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join(' ');

    const sail = d.sailing
      ? `<div class="sail-line">${num(d.sailing.distance_nm)} nm · ${esc(d.sailing.hours_at_6kt)} at 6 kt` +
        (d.sailing.optional ? ' · optional' : '') + `</div>` : '';

    return `<div class="card day${d.optional ? ' is-optional' : ''}">` +
      `<div class="day-head">` +
        `<span class="daynum" aria-hidden="true">${d.day}</span>` +
        `<h3>${esc(d.port)}</h3>` +
        `<span class="when">${esc(dayLabel(d.date))}</span>` +
      `</div>` +
      `<div class="card-pad">` +
        `<p class="lede">${esc(d.headline)}</p>` +
        `<p class="prose${long ? ' clipped' : ''}" id="${pid}">${esc(d.prose)}</p>` +
        (long ? `<button class="more" data-more="${pid}">Read more</button>` : '') +
        sail +
        (d.mooring_info ? `<div class="mooring-note"><strong>Mooring.</strong> ${esc(d.mooring_info)}</div>` : '') +
        (tags ? `<div class="tags">${tags}</div>` : '') +
        (links ? `<div class="tags">${links}</div>` : '') +
      `</div></div>`;
  }

  function renderNotes() {
    const n = state.itinerary.trip.notes || {};
    $('notes-body').innerHTML =
      `<h4 style="font-size:.64rem;letter-spacing:.11em;text-transform:uppercase;` +
      `color:var(--ink-soft);margin:0 0 4px">Dining</h4>` +
      `<p class="small" style="margin:0 0 13px">${esc(n.dining || '')}</p>` +
      `<h4 style="font-size:.64rem;letter-spacing:.11em;text-transform:uppercase;` +
      `color:var(--ink-soft);margin:0 0 4px">Moorings</h4>` +
      `<p class="small" style="margin:0">${esc(n.moorings || '')}</p>`;
  }

})();
