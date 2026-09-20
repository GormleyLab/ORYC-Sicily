/* Wind and sea timeseries. Every model is drawn as its own line rather than
   averaged into one, because where the lines diverge is exactly the thing a
   skipper needs to see. */

const ORYCCharts = (() => {
  'use strict';

  const { esc, dayLabel, hourLabel, compass, MODEL_COLOR } = ORYC;

  let weather = null, windChart = null, seaChart = null, current = null;

  const MODEL_LABEL = {
    ecmwf_ifs025: 'ECMWF IFS',
    ecmwf_aifs025_single: 'ECMWF AIFS',
    italia_meteo_arpae_icon_2i: 'ICON-2i',
  };

  function init(w) {
    if (!window.Chart) return;
    weather = w;

    const series = w.series || {};
    const ids = Object.keys(series);
    if (!ids.length) { document.getElementById('charts').hidden = true; return; }

    Chart.defaults.font.family =
      getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 11;
    Chart.defaults.color = '#4a5875';

    const tabs = document.getElementById('chart-tabs');
    tabs.innerHTML = ids.map(id =>
      `<button type="button" data-loc="${esc(id)}" aria-pressed="false">` +
      `${esc(series[id].name)}</button>`).join('');

    tabs.addEventListener('click', e => {
      const btn = e.target.closest('button[data-loc]');
      if (btn) select(btn.dataset.loc);
    });

    // Open on the island the fleet is at today, falling back to the first.
    select(defaultLocation(ids));
  }

  function defaultLocation(ids) {
    const today = (weather.generated_at || '').slice(0, 10);
    const berth = (weather.berths || []).find(b => b.date >= today);
    if (berth && berth.recommended && ids.includes(berth.recommended)) {
      return berth.recommended;
    }
    return ids[0];
  }

  function select(id) {
    current = id;
    document.querySelectorAll('#chart-tabs button').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.loc === id)));
    drawWind(id);
    drawSea(id);
    drawBarbs(id);
  }

  function labels(times) {
    return times.map(t => {
      const h = hourLabel(t);
      return h === '00:00' ? dayLabel(t) : h;
    });
  }

  const baseOptions = (titleText, unit) => ({
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'top', align: 'end',
                labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 12 } },
      title: { display: true, text: titleText, align: 'start',
               font: { size: 12, weight: '600' }, color: '#14213f',
               padding: { bottom: 10 } },
      tooltip: {
        backgroundColor: '#14213f', padding: 10, cornerRadius: 6,
        titleFont: { size: 11 }, bodyFont: { size: 11 },
        callbacks: {
          label: c => `${c.dataset.label}: ${c.parsed.y === null ? '–' : c.parsed.y} ${unit}`,
        },
      },
    },
    scales: {
      x: { grid: { display: false },
           ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
      y: { beginAtZero: true, grid: { color: '#ebe7de' },
           title: { display: true, text: unit } },
    },
    elements: { point: { radius: 0, hitRadius: 12 }, line: { borderWidth: 2, tension: 0.3 } },
  });

  function drawWind(id) {
    const p = weather.series[id];
    const datasets = [];

    Object.entries(p.models).forEach(([mid, s]) => {
      datasets.push({
        label: MODEL_LABEL[mid] || mid,
        data: s.wind_speed_10m,
        borderColor: MODEL_COLOR[mid] || '#6b7490',
        backgroundColor: 'transparent',
        spanGaps: false,
      });
    });

    // Gusts from the highest-resolution model that publishes them, drawn as a
    // dashed envelope rather than a competing line.
    const gustSrc = p.models.italia_meteo_arpae_icon_2i || p.models.ecmwf_ifs025;
    if (gustSrc) {
      datasets.push({
        label: 'Gusts',
        data: gustSrc.wind_gusts_10m,
        borderColor: '#a96908',
        borderDash: [4, 4],
        backgroundColor: 'rgba(169,105,8,.06)',
        fill: true,
        spanGaps: false,
      });
    }

    // Reference lines at the thresholds the verdicts use.
    const threshold = (y, color) => ({
      label: `${y} kt`,
      data: p.time.map(() => y),
      borderColor: color, borderWidth: 1, borderDash: [2, 4],
      pointRadius: 0, fill: false,
    });
    datasets.push(threshold(18, 'rgba(169,105,8,.5)'));
    datasets.push(threshold(25, 'rgba(210,35,42,.5)'));

    if (windChart) windChart.destroy();
    windChart = new Chart(document.getElementById('wind-chart'), {
      type: 'line',
      data: { labels: labels(p.time), datasets },
      options: baseOptions(`Wind at ${p.name}`, 'kt'),
    });
  }

  function drawSea(id) {
    const p = weather.series[id];
    const box = document.getElementById('sea-chart').parentElement;
    if (!p.sea || !p.sea.series) { box.hidden = true; return; }
    box.hidden = false;

    const s = p.sea.series;
    const datasets = [
      { label: 'Total wave', data: s.wave_height,
        borderColor: '#23408f', backgroundColor: 'rgba(35,64,143,.08)', fill: true },
      { label: 'Swell', data: s.swell_wave_height,
        borderColor: '#1f7a52', backgroundColor: 'transparent', borderDash: [5, 3] },
      { label: '1.25 m', data: p.time.map(() => 1.25),
        borderColor: 'rgba(169,105,8,.5)', borderWidth: 1, borderDash: [2, 4], pointRadius: 0 },
      { label: '2.0 m', data: p.time.map(() => 2.0),
        borderColor: 'rgba(210,35,42,.5)', borderWidth: 1, borderDash: [2, 4], pointRadius: 0 },
    ];

    if (seaChart) seaChart.destroy();
    const opts = baseOptions(
      `Sea state near ${p.name} — Météo-France MFWAM`, 'm');
    opts.plugins.tooltip.callbacks.afterBody = items => {
      const i = items[0].dataIndex;
      const dir = s.swell_wave_direction ? s.swell_wave_direction[i] : null;
      const per = s.swell_wave_period ? s.swell_wave_period[i] : null;
      const out = [];
      if (dir !== null && dir !== undefined) out.push(`Swell from ${compass(dir)} (${dir}°)`);
      if (per !== null && per !== undefined) out.push(`Period ${per} s`);
      return out;
    };
    seaChart = new Chart(document.getElementById('sea-chart'), {
      type: 'line', data: { labels: labels(p.time), datasets }, options: opts,
    });
  }

  /** A thin row of direction arrows under the wind chart - direction is hard
   *  to read off a line chart and it drives the whole shelter question. */
  function drawBarbs(id) {
    const p = weather.series[id];
    const src = p.models.italia_meteo_arpae_icon_2i || p.models.ecmwf_ifs025
             || Object.values(p.models)[0];
    if (!src) return;

    const step = Math.max(1, Math.round(p.time.length / 24));
    const out = [];
    for (let i = 0; i < p.time.length; i += step) {
      const d = src.wind_direction_10m[i];
      out.push(d === null || d === undefined
        ? '<span>·</span>'
        : `<span title="${esc(dayLabel(p.time[i]))} ${esc(hourLabel(p.time[i]))} — from ${compass(d)}">` +
          `<span style="display:inline-block;transform:rotate(${(d + 180) % 360}deg)">↑</span></span>`);
    }
    document.getElementById('wind-barbs').innerHTML = out.join('');
  }

  return { init };
})();
