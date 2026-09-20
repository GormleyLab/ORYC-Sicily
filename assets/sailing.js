/* Shared display helpers. All the real sailing maths happens in
   scripts/sailing.py at build time; this only formats what it decided. */

const ORYC = (() => {
  'use strict';

  const COMPASS = ['N','NNE','NE','ENE','E','ESE','SE','SSE',
                   'S','SSW','SW','WSW','W','WNW','NW','NNW'];

  const VERDICT = {
    'go':        { g: '●', label: 'Go',        cls: 'chip-go' },
    'caution':   { g: '▲', label: 'Caution',   cls: 'chip-caution' },
    'no-go':     { g: '■', label: 'No-go',     cls: 'chip-nogo' },
    'unknown':   { g: '·', label: 'No data',   cls: 'chip-unknown' },
    'sheltered': { g: '●', label: 'Sheltered', cls: 'chip-sheltered' },
    'workable':  { g: '◐', label: 'Workable',  cls: 'chip-workable' },
    'exposed':   { g: '▲', label: 'Exposed',   cls: 'chip-exposed' },
    'untenable': { g: '■', label: 'Untenable', cls: 'chip-untenable' },
  };

  const MODEL_COLOR = {
    ecmwf_ifs025: '#23408f',
    ecmwf_aifs025_single: '#d2232a',
    italia_meteo_arpae_icon_2i: '#0f7a4f',
  };

  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, c => (
      { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]
    ));
  }

  function compass(deg) {
    if (deg === null || deg === undefined) return '–';
    return COMPASS[Math.round((deg % 360) / 22.5) % 16];
  }

  /** Status chip - always a glyph AND a word, never colour alone. */
  function chip(verdict) {
    const v = VERDICT[verdict] || VERDICT.unknown;
    return `<span class="chip ${v.cls}"><span class="g" aria-hidden="true">${v.g}</span>${v.label}</span>`;
  }

  /** Wind arrow as inline SVG. A rotated text glyph sat off its baseline and
   *  read as a stray tick mark at small sizes; this aligns predictably and
   *  inherits currentColor in every theme. The arrow flies downwind, since
   *  meteorological direction is where the wind comes FROM. */
  function windArrow(fromDeg, px) {
    if (fromDeg === null || fromDeg === undefined) return '';
    const s = px || 13;
    const rot = (fromDeg + 180) % 360;
    return `<span class="warr" style="width:${s}px;height:${s}px" aria-hidden="true">` +
      `<svg viewBox="0 0 24 24" width="${s}" height="${s}" style="transform:rotate(${rot}deg)">` +
      `<path d="M12 3 L12 21 M12 3 L7 9 M12 3 L17 9" fill="none" stroke="currentColor" ` +
      `stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
  }

  function num(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return '–';
    return Number(v).toFixed(digits === undefined ? 0 : digits);
  }

  /** Deep link into Windy, centred on a coordinate with one overlay. The
   *  `?overlay,lat,lon,zoom` form is Windy's long-standing scheme. No key,
   *  no embed - just a link out to the app the fleet already uses. */
  function windyUrl(lat, lon, overlay, zoom) {
    return `https://www.windy.com/?${overlay || 'wind'},${lat.toFixed(3)},${lon.toFixed(3)},${zoom || 9}`;
  }

  function windyLink(lat, lon, overlay, label) {
    if (lat === undefined || lat === null) return '';
    return `<a class="windy" href="${windyUrl(lat, lon, overlay)}" target="_blank" ` +
           `rel="noopener">${esc(label || 'Windy')} ↗</a>`;
  }

  function dayLabel(iso) {
    const d = new Date(iso.length <= 10 ? iso + 'T12:00' : iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  function hourLabel(iso) { return iso.slice(11, 16); }

  function ago(isoUtc) {
    const then = new Date(isoUtc);
    if (isNaN(then)) return '';
    const mins = Math.round((Date.now() - then.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const hrs = mins / 60;
    if (hrs < 24) return `${hrs.toFixed(hrs < 10 ? 1 : 0)} h ago`;
    return `${Math.round(hrs / 24)} d ago`;
  }

  function shelterColor(v) {
    return { sheltered: 'var(--go)', workable: 'var(--caution)',
             exposed: 'var(--caution)', untenable: 'var(--nogo)' }[v] || 'var(--none)';
  }

  function verdictClass(v) {
    return { 'go': 'go', 'caution': 'caution', 'no-go': 'nogo' }[v] || '';
  }

  /** Vector mean of compass directions - a plain average is wrong near 360. */
  function circularMean(dirs) {
    const d = dirs.filter(v => v != null);
    if (!d.length) return null;
    let x = 0, y = 0;
    d.forEach(v => { x += Math.cos(v * Math.PI / 180); y += Math.sin(v * Math.PI / 180); });
    if (Math.abs(x) < 1e-9 && Math.abs(y) < 1e-9) return null;
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  /** Index of the hour nearest to now within an array of local ISO stamps. */
  function nowIndex(times) {
    if (!times || !times.length) return -1;
    const now = new Date();
    // Times are local Italian time without an offset; compare on the wall
    // clock in Europe/Rome so this is right wherever the reader is.
    const rome = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/Rome' }));
    const stamp = `${rome.getFullYear()}-${String(rome.getMonth() + 1).padStart(2, '0')}-` +
                  `${String(rome.getDate()).padStart(2, '0')}T${String(rome.getHours()).padStart(2, '0')}:00`;
    const exact = times.indexOf(stamp);
    if (exact >= 0) return exact;
    for (let i = 0; i < times.length; i++) if (times[i] >= stamp) return i;
    return -1;
  }

  return { esc, compass, chip, windArrow, num, windyUrl, windyLink,
           dayLabel, hourLabel, ago, shelterColor, verdictClass, nowIndex, circularMean,
           MODEL_COLOR, VERDICT };
})();
