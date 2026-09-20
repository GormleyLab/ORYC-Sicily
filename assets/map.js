/* Leaflet route map: legs, mooring markers coloured by shelter verdict, and
   wind arrows that scrub through the forecast with the slider. */

const ORYCMap = (() => {
  'use strict';

  const { esc, num, compass, windyUrl, dayLabel, hourLabel, shelterColor } = ORYC;

  let map, windLayer, times = [], weather = null, waypoints = null;

  function init(w, wp) {
    if (!window.L) return;
    weather = w; waypoints = wp;

    map = L.map('map-canvas', { scrollWheelZoom: false })
      .setView([38.52, 14.95], 9);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 17,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    drawLegs();
    drawMoorings();
    drawPOIs();

    windLayer = L.layerGroup().addTo(map);
    setupSlider();

    // The map is inside a section that may still be laying out on first paint.
    setTimeout(() => map.invalidateSize(), 200);
  }

  function drawLegs() {
    const bounds = [];
    (weather.legs || []).forEach(leg => {
      const pts = [[leg.from_lat, leg.from_lon],
                   [leg.midpoint.lat, leg.midpoint.lon],
                   [leg.to_lat, leg.to_lon]];
      bounds.push(...pts);

      const color = leg.status === 'forecast'
        ? ({ 'go': '#1f7a52', 'caution': '#a96908', 'no-go': '#d2232a' }[leg.verdict] || '#23408f')
        : '#23408f';

      L.polyline(pts, {
        color, weight: leg.optional ? 2.5 : 3.5,
        opacity: 0.85, dashArray: leg.optional ? '7,7' : null,
      }).addTo(map).bindPopup(legPopup(leg));
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [34, 34] });
  }

  function legPopup(leg) {
    const v = leg.status === 'forecast'
      ? `<div style="margin-top:5px">${ORYC.chip(leg.verdict)}` +
        (leg.recommended_window ? ` depart ${esc(leg.recommended_window)}` : '') + `</div>`
      : `<div style="margin-top:5px;color:#666">Beyond the forecast horizon</div>`;
    return `<strong>${esc(leg.label)}</strong><br>` +
      `${esc(dayLabel(leg.date))} · ${num(leg.stated_nm)} nm · ` +
      `${num(leg.bearing)}°T ${esc(leg.bearing_label)}${v}` +
      `<div style="margin-top:6px"><a href="${windyUrl(leg.midpoint.lat, leg.midpoint.lon, 'wind')}" ` +
      `target="_blank" rel="noopener">Open in Windy ↗</a></div>`;
  }

  function latestVerdict(mooringId) {
    // The nearest-in-time berth entry that actually has a verdict for this spot.
    for (const b of (weather.berths || [])) {
      if (b.status !== 'forecast') continue;
      const o = (b.options || []).find(x => x.id === mooringId);
      if (o) return o;
    }
    return null;
  }

  function drawMoorings() {
    const moorings = (waypoints && waypoints.moorings) || {};
    Object.entries(moorings).forEach(([id, m]) => {
      const o = latestVerdict(id);
      const color = o ? shelterColor(o.verdict) : '#23408f';

      L.circleMarker([m.lat, m.lon], {
        radius: 7, weight: 2, color: '#fff', fillColor: color, fillOpacity: 0.95,
      }).addTo(map).bindPopup(
        `<strong>${esc(m.name)}</strong><br><span style="color:#666">${esc(m.island)}</span>` +
        (o ? `<div style="margin-top:5px">${ORYC.chip(o.verdict)}</div>` +
             `<div style="margin-top:4px;font-size:.85em">${esc(o.reason)}</div>` : '') +
        `<div style="margin-top:5px;font-size:.85em;color:#666">${esc(m.shelter_note)}</div>` +
        (m.no_anchoring ? `<div style="margin-top:5px;color:#d2232a;font-weight:600;font-size:.85em">Do not anchor — rocky</div>` : '') +
        (m.verified ? '' : `<div style="margin-top:5px;font-size:.8em;color:#a96908">Position not yet chart-verified</div>`) +
        `<div style="margin-top:6px"><a href="${windyUrl(m.lat, m.lon, 'waves', 11)}" ` +
        `target="_blank" rel="noopener">Open in Windy ↗</a></div>`
      );
    });
  }

  function drawPOIs() {
    const pois = (waypoints && waypoints.points_of_interest) || {};
    Object.values(pois).forEach(p => {
      L.circleMarker([p.lat, p.lon], {
        radius: 5, weight: 1.5, color: '#d2232a', fillColor: '#fff', fillOpacity: 1,
      }).addTo(map).bindPopup(
        `<strong>${esc(p.name)}</strong><br><span style="color:#666;font-size:.9em">${esc(p.note)}</span>`);
    });
  }

  // --- wind arrows ---------------------------------------------------------

  function setupSlider() {
    const series = weather.series || {};
    const first = Object.values(series)[0];
    if (!first || !first.time || !first.time.length) return;

    times = first.time;
    const slider = document.getElementById('map-slider');
    slider.min = 0;
    slider.max = times.length - 1;

    // Start at the current hour if it is in range, otherwise at the beginning.
    const nowIso = new Date().toISOString().slice(0, 13);
    let start = times.findIndex(t => t.slice(0, 13) >= nowIso);
    slider.value = start > 0 ? start : 0;

    slider.addEventListener('input', () => drawWind(+slider.value));
    drawWind(+slider.value);
  }

  function drawWind(index) {
    if (!windLayer) return;
    windLayer.clearLayers();

    const iso = times[index];
    document.getElementById('map-time').textContent =
      `${dayLabel(iso)} ${hourLabel(iso)}`;

    const series = weather.series || {};
    Object.entries(series).forEach(([id, point]) => {
      const i = point.time.indexOf(iso);
      if (i < 0) return;

      // Prefer the highest-resolution model that has a value at this hour.
      let speed = null, dir = null;
      for (const mid of ['italia_meteo_arpae_icon_2i', 'ecmwf_ifs025', 'ecmwf_aifs025_single']) {
        const m = point.models[mid];
        if (m && m.wind_speed_10m[i] !== null && m.wind_direction_10m[i] !== null) {
          speed = m.wind_speed_10m[i]; dir = m.wind_direction_10m[i]; break;
        }
      }
      if (speed === null) return;

      const size = 15 + Math.min(speed, 30) * 0.65;
      const rot = (dir + 180) % 360;   // arrow flies downwind
      const icon = L.divIcon({
        className: '',
        html: `<div class="wind-arrow" style="transform:rotate(${rot}deg);` +
              `font-size:${size}px;line-height:1;text-align:center">↑</div>` +
              `<div style="font:600 10px/1 ui-monospace,monospace;text-align:center;` +
              `color:#14213f;text-shadow:0 0 3px #fff,0 0 3px #fff">${Math.round(speed)}</div>`,
        iconSize: [size + 12, size + 16],
        iconAnchor: [(size + 12) / 2, (size + 16) / 2],
      });

      L.marker([point.lat, point.lon], { icon, interactive: false })
        .addTo(windLayer);
    });
  }

  return { init };
})();
