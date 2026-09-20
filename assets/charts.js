/* Wind and sea timeseries. Every model is its own line rather than averaged
   into one, because where the lines diverge is exactly what a skipper needs
   to see. Colours are read from the live CSS variables so the charts follow
   the day / dark / night-vision theme. */

const ORYCCharts = (() => {
  'use strict';

  const { esc, dayLabel, hourLabel, compass, MODEL_COLOR, nowIndex } = ORYC;

  /** weather.json stores sea state in metres; the page shows whichever unit
   *  the header toggle is on. Converted here, where the series enters the
   *  chart, so the axis, the tooltip and the threshold lines all move
   *  together. Rounded because the tooltip prints the plotted value as-is.
   *  Called at draw time, never cached - `refresh()` redraws on a switch. */
  const conv = m => {
    const v = ORYC.toDisplay(m);
    return v == null ? null : Math.round(v * 10) / 10;
  };

  let weather = null, windChart = null, seaChart = null, current = null;

  const MODEL_LABEL = {
    ecmwf_ifs025: 'ECMWF IFS',
    ecmwf_aifs025_single: 'ECMWF AIFS',
    italia_meteo_arpae_icon_2i: 'ICON-2i',
  };

  const cssVar = n => getComputedStyle(document.documentElement)
    .getPropertyValue(n).trim();

  /** In night mode every hue collapses to red, so lines are separated by dash
   *  pattern instead of colour - the chart still reads without any hue. */
  function isNight() {
    return document.documentElement.getAttribute('data-theme') === 'night';
  }

  function modelColor(mid, i) {
    if (isNight()) return cssVar('--ink');
    return MODEL_COLOR[mid] || cssVar('--ink-soft');
  }

  function modelDash(i) {
    return isNight() ? [[], [6, 3], [2, 3]][i % 3] : [];
  }

  function init(w) {
    if (!window.Chart) return;
    weather = w;

    const series = w.series || {};
    const ids = Object.keys(series);
    if (!ids.length) { document.getElementById('charts').hidden = true; return; }

    Chart.defaults.font.family = cssVar('--sans') ||
      getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 11;

    const tabs = document.getElementById('chart-tabs');
    tabs.innerHTML = ids.map(id =>
      `<button type="button" data-loc="${esc(id)}" aria-pressed="false">` +
      `${esc(series[id].name)}</button>`).join('');

    tabs.addEventListener('click', e => {
      const btn = e.target.closest('button[data-loc]');
      if (btn) select(btn.dataset.loc);
    });

    select(defaultLocation(ids));
    watchSize();
    nudge();
  }

  function defaultLocation(ids) {
    const today = (weather.generated_at || '').slice(0, 10);
    const berth = (weather.berths || []).find(b => b.date >= today);
    if (berth && berth.recommended && ids.includes(berth.recommended)) return berth.recommended;
    return ids[0];
  }

  function select(id) {
    current = id;
    document.querySelectorAll('#chart-tabs button').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.loc === id)));
    drawWind(id);
    drawSea(id);
    drawBarbs(id);
    nudge();
  }

  /** Redraw in the current theme's colours. */
  function refresh() { if (current) select(current); }

  /* Chart.js sizes a canvas from its container at construction time. If the
     container has no width yet - fonts still loading, the section not laid
     out, the page inside an iframe that has not been given a width - the
     canvas is created 0px wide and never recovers on its own, so the chart
     is silently invisible with no error logged.

     Watch the container and resize whenever it gains width. Cheap, and it
     removes a whole class of "the charts are blank" failures. */
  let observer = null;
  function watchSize() {
    if (observer || typeof ResizeObserver === 'undefined') return;
    const box = document.getElementById('wind-chart');
    if (!box || !box.parentElement) return;
    observer = new ResizeObserver(() => {
      [windChart, seaChart].forEach(ch => {
        if (!ch) return;
        const el = ch.canvas;
        if (el && el.parentElement && el.parentElement.clientWidth > 0
            && el.width !== el.parentElement.clientWidth) {
          ch.resize();
        }
      });
    });
    observer.observe(box.parentElement.parentElement || box.parentElement);
  }

  /** Belt and braces for the zero-width case: nudge after layout settles and
      again once web fonts have swapped in. */
  function nudge() {
    const go = () => {
      try { [windChart, seaChart].forEach(ch => ch && ch.resize()); } catch (e) {}
    };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(go);
    setTimeout(go, 250);
    setTimeout(go, 1200);
    try {
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(go);
    } catch (e) {}
  }

  function labels(times) {
    return times.map(t => {
      const h = hourLabel(t);
      return h === '00:00' ? dayLabel(t) : h;
    });
  }

  function baseOptions(titleText, unit) {
    const ink = cssVar('--ink'), soft = cssVar('--ink-soft'), hair = cssVar('--hair-soft');
    Chart.defaults.color = cssVar('--ink-mid');
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end',
                  labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 10,
                            color: cssVar('--ink-mid') } },
        title: { display: true, text: titleText, align: 'start',
                 font: { size: 12, weight: '600' }, color: ink, padding: { bottom: 8 } },
        tooltip: {
          backgroundColor: cssVar('--surface'), borderColor: cssVar('--hair'), borderWidth: 1,
          titleColor: ink, bodyColor: cssVar('--ink-mid'),
          padding: 9, cornerRadius: 6, displayColors: true,
          titleFont: { size: 11 }, bodyFont: { size: 11 },
          callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y == null ? '–' : c.parsed.y} ${unit}` },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: hair },
             ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, color: soft } },
        y: { beginAtZero: true, grid: { color: hair }, border: { display: false },
             ticks: { color: soft },
             title: { display: true, text: unit, color: soft } },
      },
      elements: { point: { radius: 0, hitRadius: 14 }, line: { borderWidth: 2, tension: .3 } },
    };
  }

  /** A vertical marker at the current hour, so "now" is findable at a glance. */
  function nowMarker(times) {
    const i = nowIndex(times);
    if (i < 0) return null;
    return {
      id: 'nowline',
      afterDraw(chart) {
        const x = chart.scales.x.getPixelForValue(i);
        if (!isFinite(x)) return;
        const { top, bottom } = chart.chartArea;
        const c = chart.ctx;
        c.save();
        c.strokeStyle = cssVar('--accent');
        c.lineWidth = 1.5;
        c.setLineDash([3, 3]);
        c.beginPath(); c.moveTo(x, top); c.lineTo(x, bottom); c.stroke();
        c.restore();
      },
    };
  }

  function drawWind(id) {
    const p = weather.series[id];
    const datasets = [];

    Object.entries(p.models).forEach(([mid, s], i) => {
      datasets.push({
        label: MODEL_LABEL[mid] || mid,
        data: s.wind_speed_10m,
        borderColor: modelColor(mid, i),
        borderDash: modelDash(i),
        backgroundColor: 'transparent',
        spanGaps: false,
      });
    });

    const gustSrc = p.models.italia_meteo_arpae_icon_2i || p.models.ecmwf_ifs025;
    if (gustSrc) {
      datasets.push({
        label: 'Gusts',
        data: gustSrc.wind_gusts_10m,
        borderColor: cssVar('--caution'),
        borderDash: [4, 4],
        backgroundColor: 'transparent',
        spanGaps: false,
      });
    }

    const threshold = (y, color) => ({
      label: `${y} kt`, data: p.time.map(() => y),
      borderColor: color, borderWidth: 1, borderDash: [2, 5], pointRadius: 0, fill: false,
    });
    datasets.push(threshold(18, cssVar('--caution-line')));
    datasets.push(threshold(25, cssVar('--nogo-line')));

    if (windChart) windChart.destroy();
    const marker = nowMarker(p.time);
    windChart = new Chart(document.getElementById('wind-chart'), {
      type: 'line',
      data: { labels: labels(p.time), datasets },
      options: baseOptions(`Wind at ${p.name}`, 'kt'),
      plugins: marker ? [marker] : [],
    });
  }

  function drawSea(id) {
    const p = weather.series[id];
    const box = document.getElementById('sea-chart').parentElement;
    if (!p.sea || !p.sea.series) { box.hidden = true; return; }
    box.hidden = false;

    const s = p.sea.series;
    const night = isNight();
    const unit = ORYC.units();
    const datasets = [
      { label: 'Total wave', data: (s.wave_height || []).map(conv),
        borderColor: night ? cssVar('--ink') : cssVar('--navy'),
        backgroundColor: 'transparent', fill: false },
      { label: 'Swell', data: (s.swell_wave_height || []).map(conv),
        borderColor: night ? cssVar('--ink-mid') : cssVar('--go'),
        backgroundColor: 'transparent', borderDash: [5, 3] },
      { label: `${conv(1.25)} ${unit}`, data: p.time.map(() => conv(1.25)),
        borderColor: cssVar('--caution-line'), borderWidth: 1, borderDash: [2, 5], pointRadius: 0 },
      { label: `${conv(2.0)} ${unit}`, data: p.time.map(() => conv(2.0)),
        borderColor: cssVar('--nogo-line'), borderWidth: 1, borderDash: [2, 5], pointRadius: 0 },
    ];

    const opts = baseOptions(`Sea state near ${p.name} — Météo-France MFWAM`, unit);
    opts.plugins.tooltip.callbacks.afterBody = items => {
      const i = items[0].dataIndex;
      const out = [];
      const dir = s.swell_wave_direction && s.swell_wave_direction[i];
      const per = s.swell_wave_period && s.swell_wave_period[i];
      if (dir != null) out.push(`Swell from ${compass(dir)} (${dir}°)`);
      if (per != null) out.push(`Period ${per} s`);
      return out;
    };

    if (seaChart) seaChart.destroy();
    const marker = nowMarker(p.time);
    seaChart = new Chart(document.getElementById('sea-chart'), {
      type: 'line', data: { labels: labels(p.time), datasets }, options: opts,
      plugins: marker ? [marker] : [],
    });
  }

  /** Direction arrows under the wind chart - direction drives the whole
   *  shelter question and is hard to read off a line chart. */
  function drawBarbs(id) {
    const p = weather.series[id];
    const src = p.models.italia_meteo_arpae_icon_2i || p.models.ecmwf_ifs025
             || Object.values(p.models)[0];
    if (!src) return;

    const step = Math.max(1, Math.round(p.time.length / 18));
    const out = [];
    for (let i = 0; i < p.time.length; i += step) {
      const d = src.wind_direction_10m[i];
      out.push(d == null
        ? '<span>·</span>'
        : `<span title="${esc(dayLabel(p.time[i]))} ${esc(hourLabel(p.time[i]))} — from ${compass(d)}">` +
          ORYC.windArrow(d, 11) + `</span>`);
    }
    document.getElementById('wind-barbs').innerHTML = out.join('');
  }

  return { init, refresh };
})();
