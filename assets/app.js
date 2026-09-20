/* ORYC Aeolian Flotilla - page renderer.
   Fetches the three JSON files the pipeline publishes and renders everything.
   No API calls from the browser: weather.json is pre-computed by the cron. */

(function () {
  'use strict';

  const { esc, chip, windArrow, num, windyLink, dayLabel, hourLabel,
          ago, verdictClass, compass } = ORYC;

  const $ = id => document.getElementById(id);

  const state = { weather: null, itinerary: null, waypoints: null };

  // --- boot ----------------------------------------------------------------

  Promise.all([
    fetchJson('data/weather.json'),
    fetchJson('data/itinerary.json'),
    fetchJson('data/waypoints.json'),
  ]).then(([weather, itinerary, waypoints]) => {
    state.weather = weather;
    state.itinerary = itinerary;
    state.waypoints = waypoints;

    renderItinerary();   // static content first - always renders
    renderNotes();

    if (!weather) {
      $('updated').innerHTML =
        '<strong>Forecast data has not been published yet.</strong> ' +
        'The itinerary below is complete; weather appears once the updater has run.';
      ['briefing', 'passages', 'berths', 'map', 'charts'].forEach(id => {
        const el = $(id); if (el) el.hidden = true;
      });
      return;
    }

    renderFreshness();
    renderCountdown();
    renderBriefing();
    renderLegs();
    renderBerths();

    if (window.ORYCMap) ORYCMap.init(weather, waypoints);
    if (window.ORYCCharts) ORYCCharts.init(weather);
  }).catch(err => {
    console.error(err);
    $('updated').innerHTML =
      '<strong>Could not load the site data.</strong> ' + esc(err.message);
  });

  function fetchJson(path) {
    return fetch(path, { cache: 'no-cache' }).then(r => {
      if (!r.ok) {
        if (path.endsWith('weather.json')) return null;  // not published yet
        throw new Error(`${path}: HTTP ${r.status}`);
      }
      return r.json();
    }).catch(e => {
      if (path.endsWith('weather.json')) return null;
      throw e;
    });
  }

  // --- freshness -----------------------------------------------------------

  function renderFreshness() {
    const w = state.weather;

    $('updated').innerHTML =
      `Forecast updated <b>${esc(ago(w.generated_at_utc || w.generated_at))}</b> ` +
      `<span class="muted">(${esc(dayLabel(w.generated_at))} ${esc(hourLabel(w.generated_at))} local)</span>` +
      (w.horizon_end ? ` · reaches <b>${esc(dayLabel(w.horizon_end))}</b>` : '');

    $('model-badges').innerHTML = (w.models || []).map(m => {
      let cls = 'badge';
      if (!m.ok) cls += ' dead';
      else if (m.age_hours > (m.update_interval_hours || 12) * 2) cls += ' stale-model';
      const init = m.ok ? `${esc(m.init_label)} · ${num(m.age_hours, 1)} h old`
                        : 'unavailable';
      const gusts = m.provides_gusts === false ? ' · no gusts' : '';
      return `<span class="${cls}" title="${esc(m.note || '')}">` +
             `<b>${esc(m.short)}</b> ${esc(m.resolution)} · ${init}${gusts}</span>`;
    }).join('');

    const alerts = [];
    if (w.simulated) {
      alerts.push(['danger', 'Preview mode — these are not the real trip dates',
        `Itinerary dates have been shifted by ${w.simulated_shift_days} days into the ` +
        `current forecast window so the passage planner can be demonstrated. ` +
        `Do not plan against this page while this banner is showing.`]);
    }
    if (w.stale) {
      alerts.push(['warn', 'This forecast is stale',
        `The last update attempt failed, so the figures below are from an earlier ` +
        `run. ${esc(w.stale_reason || '')}`]);
    }
    if (w.briefing_error && !w.briefing) {
      alerts.push(['warn', 'The written briefing is unavailable',
        'All the numbers, passage calls and berth rankings below are unaffected — ' +
        'only the prose summary is missing.']);
    }
    const unverified = Object.values((state.waypoints || {}).moorings || {})
      .filter(m => !m.verified).length;
    if (unverified) {
      alerts.push(['warn', `${unverified} mooring positions are not yet verified`,
        'Coordinates and exposure sectors were derived from the itinerary text and ' +
        'have not been checked against a chart. Shelter rankings depend on them, so ' +
        'treat them as indicative until they are confirmed.']);
    }

    $('alerts').innerHTML = alerts.map(([kind, title, body]) =>
      `<div class="alert alert-${kind}"><strong>${esc(title)}</strong>${body}</div>`
    ).join('');
  }

  function renderCountdown() {
    const w = state.weather, el = $('countdown');
    if (w.phase === 'underway' && w.trip_day) {
      $('countdown-n').textContent = w.trip_day;
      $('countdown-l').textContent = `of 8 days`;
    } else if (w.phase === 'pre-trip') {
      $('countdown-n').textContent = w.days_to_departure;
      $('countdown-l').textContent = w.days_to_departure === 1 ? 'day out' : 'days out';
    } else {
      $('countdown-n').textContent = '⚓';
      $('countdown-l').textContent = 'complete';
    }
    el.hidden = false;
  }

  // --- briefing ------------------------------------------------------------

  function renderBriefing() {
    const b = state.weather.briefing;
    const body = $('briefing-body');

    if (!b) {
      body.innerHTML =
        `<div class="card"><p class="muted small" style="margin:0">` +
        `No written briefing in this run. The passage calls, berth rankings and ` +
        `charts below are computed directly from the model data and are unaffected.` +
        `</p></div>`;
      return;
    }

    const section = (title, text) => text
      ? `<h4>${esc(title)}</h4><p>${esc(text)}</p>` : '';

    const notes = (b.passage_notes || []).length
      ? `<h4>Passage notes</h4><ul class="cautions">` +
        b.passage_notes.map(n =>
          `<li><strong>${esc(n.leg)}</strong> — ${esc(n.note)}</li>`).join('') +
        `</ul>`
      : '';

    const cautions = (b.cautions || []).length
      ? `<h4>Watch for</h4><ul class="cautions">` +
        b.cautions.map(c => `<li>${esc(c)}</li>`).join('') + `</ul>`
      : '';

    const conf = b.confidence
      ? `<span>Confidence: <strong>${esc(b.confidence)}</strong>` +
        (b.confidence_note ? ` — ${esc(b.confidence_note)}` : '') + `</span>`
      : '';

    body.innerHTML =
      `<div class="card briefing">` +
        `<div class="headline">${esc(b.headline)}</div>` +
        section('Synopsis', b.synopsis) +
        section('Overnight at the berth', b.overnight_anchorage) +
        section('Tomorrow morning', b.tomorrow_morning) +
        notes + cautions +
        `<div class="by">${conf}<span>Written by ${esc(b.model || 'Claude')} ` +
        `from the model data on this page</span></div>` +
      `</div>`;
  }

  // --- passage planner -----------------------------------------------------

  function renderLegs() {
    const legs = state.weather.legs || [];
    $('legs-body').innerHTML = legs.map(legCard).join('');

    // Progressive disclosure: only the recommended row is shown until asked.
    document.querySelectorAll('[data-expand]').forEach(btn => {
      btn.addEventListener('click', () => {
        const tbl = document.getElementById(btn.dataset.expand);
        const open = tbl.dataset.open === '1';
        tbl.dataset.open = open ? '0' : '1';
        tbl.querySelectorAll('tr[data-extra]').forEach(tr => { tr.hidden = open; });
        btn.textContent = open ? 'Show all departure windows'
                               : 'Show only the recommended window';
      });
    });
  }

  function legCard(leg) {
    const optional = leg.optional ? ' is-optional' : '';
    const head =
      `<div class="leg-head">` +
        `<h3>${esc(leg.label)}</h3>` +
        `<span class="when">${esc(dayLabel(leg.date))}</span>` +
        (leg.status === 'forecast' ? chip(leg.verdict) : '') +
      `</div>`;

    const meta =
      `<div class="leg-meta">` +
        `<span>Bearing <b>${num(leg.bearing)}°T</b> ${esc(leg.bearing_label)} ${windArrow(leg.bearing + 180)}</span>` +
        `<span>Distance <b>${num(leg.stated_nm)} nm</b></span>` +
        `<span>Passage <b>${esc(leg.duration_label)}</b> at 6 kt</span>` +
        (leg.arrive_by ? `<span>Arrive by <b>${esc(leg.arrive_by)}</b></span>` : '') +
        windyLink(leg.midpoint.lat, leg.midpoint.lon, 'wind', 'Wind on this leg') +
      `</div>`;

    if (leg.status !== 'forecast') {
      return `<div class="card leg${optional}">${head}${meta}` +
             `<div class="beyond">${esc(leg.message || 'Beyond the forecast horizon.')}</div></div>`;
    }

    const rank = { 'go': 0, 'caution': 1, 'no-go': 2, 'unknown': 3 };
    const best = leg.windows.find(w => w.depart === leg.recommended_window);

    let rec = '';
    if (best) {
      rec = `<div class="rec ${verdictClass(leg.verdict)}">` +
        `Recommended departure <b>${esc(best.depart)}</b>, arriving about <b>${esc(best.arrive)}</b>` +
        (leg.deteriorates_after
          ? ` — conditions deteriorate for departures after <b>${esc(leg.deteriorates_after)}</b>.`
          : '.') +
        `<div class="small muted" style="margin-top:4px">${esc(best.reasons.join('; '))}</div>` +
      `</div>`;
    }

    const tableId = `w-${leg.id.replace(/[^a-z0-9]/gi, '')}`;
    const rows = leg.windows.map(w => {
      const isBest = w.depart === leg.recommended_window;
      return `<tr${isBest ? ' class="best"' : ''}${isBest ? '' : ' data-extra hidden'}>` +
        `<td class="num">${esc(w.depart)}</td>` +
        `<td class="num muted">${esc(w.arrive)}${w.arrive_next_day ? '+1' : ''}</td>` +
        `<td class="num">${num(w.max_wind_kt)}</td>` +
        `<td class="num">${num(w.max_gust_kt)}</td>` +
        `<td>${windArrow(w.wind_dir)} ${esc(w.wind_dir_label)}</td>` +
        `<td class="num">${w.max_wave_m === null ? '–' : num(w.max_wave_m, 1)}</td>` +
        `<td class="num">${w.twa === null ? '–' : num(w.twa) + '°'}</td>` +
        `<td class="pos">${esc(w.point_of_sail)}</td>` +
        `<td class="num muted">F${num(w.beaufort.force)}</td>` +
        `<td>${chip(w.verdict)}</td>` +
      `</tr>`;
    }).join('');

    const table =
      `<div class="table-scroll"><table class="windows" id="${tableId}" data-open="0">` +
        `<thead><tr>` +
          `<th>Depart</th><th>Arrive</th><th>Wind kt</th><th>Gust kt</th><th>From</th>` +
          `<th>Wave m</th><th>TWA</th><th>Point of sail</th><th>Bft</th><th>Call</th>` +
        `</tr></thead><tbody>${rows}</tbody>` +
      `</table></div>` +
      `<div style="padding:8px 18px 14px">` +
        `<button class="more" data-expand="${tableId}">Show all departure windows</button>` +
        (leg.distance_warning
          ? `<div class="small" style="color:var(--caution);margin-top:6px">⚠ ${esc(leg.distance_warning)}</div>`
          : '') +
        (leg.note ? `<div class="small muted" style="margin-top:6px">${esc(leg.note)}</div>` : '') +
      `</div>`;

    return `<div class="card leg${optional}">${head}${meta}${rec}${table}</div>`;
  }

  // --- berths --------------------------------------------------------------

  function renderBerths() {
    const berths = (state.weather.berths || []).filter(b => b.options.length > 1
      || b.status === 'forecast');
    $('berths-body').innerHTML = berths.map(berthCard).join('');
  }

  function berthCard(b) {
    const head =
      `<div class="berth-head">` +
        `<h3>${esc(b.port)}</h3>` +
        `<span class="when">${esc(dayLabel(b.date))} night</span>` +
        (b.optional ? `<span class="tag">optional</span>` : '') +
      `</div>`;

    if (b.status !== 'forecast') {
      const list = b.options.map(o =>
        `<div class="option"><div class="option-head">` +
          `<span class="option-name">${esc(o.name)}` +
          (o.verified ? '' : ' <span class="unverified" title="Position and exposure sector not yet checked against a chart">unverified</span>') +
          `</span></div>` +
          `<div class="why">${esc(o.shelter_note)}</div>` +
        `</div>`).join('');
      return `<div class="card berth">${head}` +
        `<p class="small muted" style="margin:0 0 10px">Beyond the forecast horizon — ` +
        `the options and their exposure are shown for planning.</p>${list}</div>`;
    }

    const sorted = b.options.slice().sort((x, y) => (y.score || 0) - (x.score || 0));
    const lead = b.choice_matters
      ? `<p class="small" style="margin:0 0 10px"><strong>The choice matters tonight.</strong> ` +
        `${esc(sorted[0].name)} is meaningfully better sheltered than the alternatives.</p>`
      : `<p class="small muted" style="margin:0 0 10px">All options look comfortable tonight — ` +
        `pick on convenience.</p>`;

    const list = sorted.map((o, i) => {
      const pct = o.score === null ? 0 : Math.round(o.score * 100);
      const color = ORYC.shelterColor(o.verdict);
      const sector = o.exposed_sector
        ? `exposed ${num(o.exposed_sector[0])}–${num(o.exposed_sector[1])}°`
        : 'enclosed';
      return `<div class="option${i === 0 && b.choice_matters ? ' best' : ''}">` +
        `<div class="option-head">` +
          `<span class="option-name">${esc(o.name)}` +
          (o.verified ? '' : ' <span class="unverified" title="Position and exposure sector not yet checked against a chart">unverified</span>') +
          `</span>${chip(o.verdict)}` +
        `</div>` +
        `<div class="why">${esc(o.reason)}</div>` +
        `<div class="nums">` +
          `wind ${num(o.wind_kt)} kt ${windArrow(o.wind_dir)} ${esc(o.wind_dir_label || '')} · ` +
          `gust ${num(o.gust_kt)} kt · swell ${num(o.swell_m, 1)} m ${esc(o.swell_dir_label || '')} · ${esc(sector)}` +
        `</div>` +
        (o.no_anchoring ? `<div class="warn">⚠ Do not anchor here — rocky bottom. Buoys only.</div>` : '') +
        `<div class="meter"><i style="width:${pct}%;background:${color}"></i></div>` +
        `<div style="margin-top:7px">${windyLink(o.lat, o.lon, 'waves', 'Swell here')}</div>` +
      `</div>`;
    }).join('');

    return `<div class="card berth">${head}${lead}${list}</div>`;
  }

  // --- itinerary -----------------------------------------------------------

  function renderItinerary() {
    const it = state.itinerary;
    $('itinerary-body').innerHTML = it.days.map(dayCard).join('');

    document.querySelectorAll('[data-more]').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = document.getElementById(btn.dataset.more);
        const clipped = p.classList.toggle('clipped');
        btn.textContent = clipped ? 'Read more' : 'Read less';
      });
    });
  }

  function dayCard(d, i) {
    const pid = `prose-${i}`;
    const long = (d.prose || '').length > 260;

    const tags = []
      .concat((d.flags || []).map(f => `<span class="tag flag">${esc(f)}</span>`))
      .concat(d.dining ? [`<span class="tag dinner">${esc(d.dining.label)}</span>`] : [])
      .concat((d.things_to_do || []).slice(0, 6).map(t => `<span class="tag">${esc(t)}</span>`))
      .join('');

    const links = (d.links || []).map(l =>
      `<a class="windy" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`
    ).join(' ');

    const sailing = d.sailing
      ? `<div class="small muted" style="margin-top:8px">` +
        `⛵ ${num(d.sailing.distance_nm)} nm · ${esc(d.sailing.hours_at_6kt)} at 6 kt` +
        (d.sailing.optional ? ' · optional' : '') + `</div>`
      : '';

    return `<div class="card day${d.optional ? ' is-optional' : ''}">` +
      `<div class="day-num"><span class="n">${d.day}</span>` +
      `<span class="d">${esc(d.weekday.slice(0, 3))} ${esc(dayLabel(d.date))}</span></div>` +
      `<div>` +
        `<h3>${esc(d.port)}${d.optional ? ' <span class="tag">optional</span>' : ''}</h3>` +
        `<p class="headline">${esc(d.headline)}</p>` +
        `<p class="prose${long ? ' clipped' : ''}" id="${pid}">${esc(d.prose)}</p>` +
        (long ? `<button class="more" data-more="${pid}">Read more</button>` : '') +
        sailing +
        (d.mooring_info ? `<div class="mooring-note"><strong>Mooring.</strong> ${esc(d.mooring_info)}</div>` : '') +
        (tags ? `<div class="tags">${tags}</div>` : '') +
        (links ? `<div class="tags">${links}</div>` : '') +
      `</div>` +
    `</div>`;
  }

  function renderNotes() {
    const n = state.itinerary.trip.notes || {};
    $('notes-body').innerHTML =
      `<h4 style="font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;` +
      `color:var(--oryc-navy);margin:0 0 5px">Dining</h4>` +
      `<p class="small" style="margin:0 0 14px">${esc(n.dining || '')}</p>` +
      `<h4 style="font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;` +
      `color:var(--oryc-navy);margin:0 0 5px">Moorings</h4>` +
      `<p class="small" style="margin:0">${esc(n.moorings || '')}</p>`;
  }

})();
