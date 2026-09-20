/* Shared display helpers. Kept deliberately small and dependency-free -
   all the real sailing maths happens in scripts/sailing.py at build time, so
   this file only formats what the pipeline already decided. */

const ORYC = (() => {
  'use strict';

  const COMPASS = ['N','NNE','NE','ENE','E','ESE','SE','SSE',
                   'S','SSW','SW','WSW','W','WNW','NW','NNW'];

  const VERDICT = {
    'go':        { glyph: '●', label: 'Go',      cls: 'chip-go' },
    'caution':   { glyph: '▲', label: 'Caution', cls: 'chip-caution' },
    'no-go':     { glyph: '■', label: 'No-go',   cls: 'chip-nogo' },
    'unknown':   { glyph: '—', label: 'No data', cls: 'chip-unknown' },
    'sheltered': { glyph: '●', label: 'Sheltered', cls: 'chip-sheltered' },
    'workable':  { glyph: '◐', label: 'Workable',  cls: 'chip-workable' },
    'exposed':   { glyph: '▲', label: 'Exposed',   cls: 'chip-exposed' },
    'untenable': { glyph: '■', label: 'Untenable', cls: 'chip-untenable' },
  };

  const MODEL_COLOR = {
    ecmwf_ifs025: '#23408f',
    ecmwf_aifs025_single: '#d2232a',
    italia_meteo_arpae_icon_2i: '#1f7a52',
  };

  /** Escape anything that reaches innerHTML. */
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

  /** Status chip. Always carries a glyph AND a word, never colour alone. */
  function chip(verdict) {
    const v = VERDICT[verdict] || VERDICT.unknown;
    return `<span class="chip ${v.cls}"><span class="glyph" aria-hidden="true">${v.glyph}</span>${v.label}</span>`;
  }

  /** An arrow pointing the way the wind is blowing TO (meteorological dir is
   *  where it comes FROM, so the glyph is rotated 180° from the reading). */
  function windArrow(fromDeg, size) {
    if (fromDeg === null || fromDeg === undefined) return '';
    const rot = (fromDeg + 180) % 360;
    return `<span class="arrow" style="transform:rotate(${rot}deg);font-size:${size || 1}em" aria-hidden="true">↑</span>`;
  }

  function num(v, digits) {
    if (v === null || v === undefined) return '–';
    return Number(v).toFixed(digits === undefined ? 0 : digits);
  }

  /** Deep link into the Windy app, centred on a coordinate with one overlay.
   *  Windy's URL scheme is undocumented; this is the long-standing
   *  `?overlay,lat,lon,zoom` form. A link is all this is - no key, no embed. */
  function windyUrl(lat, lon, overlay, zoom) {
    const o = overlay || 'wind';
    const z = zoom || 9;
    return `https://www.windy.com/?${o},${lat.toFixed(3)},${lon.toFixed(3)},${z}`;
  }

  function windyLink(lat, lon, overlay, label) {
    if (lat === undefined || lat === null) return '';
    return `<a class="windy" href="${windyUrl(lat, lon, overlay)}" target="_blank" rel="noopener">${esc(label || 'Windy')} ↗</a>`;
  }

  /** '2026-10-04T08:00' -> 'Sun 4 Oct' */
  function dayLabel(iso) {
    const d = new Date(iso.length <= 10 ? iso + 'T12:00' : iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString('en-GB',
      { weekday: 'short', day: 'numeric', month: 'short' });
  }

  function hourLabel(iso) {
    return iso.slice(11, 16);
  }

  function dayHourLabel(iso) {
    return `${dayLabel(iso)} ${hourLabel(iso)}`;
  }

  /** Relative age, e.g. '4 h ago'. */
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

  /** Colour for a shelter verdict - used by the map markers. */
  function shelterColor(verdict) {
    return { sheltered: '#1f7a52', workable: '#a96908',
             exposed: '#b4560c', untenable: '#d2232a' }[verdict] || '#6b7490';
  }

  function verdictClass(v) {
    return { 'go': '', 'caution': 'amber', 'no-go': 'red' }[v] || '';
  }

  return { esc, compass, chip, windArrow, num, windyUrl, windyLink,
           dayLabel, hourLabel, dayHourLabel, ago, shelterColor, verdictClass,
           MODEL_COLOR, VERDICT };
})();
