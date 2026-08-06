const state = {
  data: null,
  records: [],
  filtered: [],
  page: 1,
  perPage: 12,
  colourColumns: null
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const clean = (value, fallback = 'Unknown') => {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
};

const countBy = (items, keyFn) => {
  const map = new Map();
  items.forEach(item => {
    const key = keyFn(item);
    map.set(key, (map.get(key) || 0) + 1);
  });
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
};

const centuryStart = (label) => {
  if (!label || /^unknown$/i.test(label)) return 999999;
  const match = String(label).match(/(\d+)/);
  return match ? Number(match[1]) : 999999;
};

const normaliseHex = (value) => {
  const raw = clean(value, '').trim().replace(/^#/, '');
  if (/^[0-9a-f]{3}$/i.test(raw)) {
    return `#${raw.split('').map(char => char + char).join('').toLowerCase()}`;
  }
  if (/^[0-9a-f]{6}$/i.test(raw)) return `#${raw.toLowerCase()}`;
  return '#000000';
};

const colourFromHex = (record) => {
  const hex = normaliseHex(record?.dominant_colour?.hex);
  const number = Number.parseInt(hex.slice(1), 16);
  const r = (number >> 16) & 255;
  const g = (number >> 8) & 255;
  const b = number & 255;
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const delta = max - min;
  const lightness = (max + min) / 2;
  let hue = 0;

  if (delta !== 0) {
    if (max === rn) hue = 60 * (((gn - bn) / delta) % 6);
    else if (max === gn) hue = 60 * (((bn - rn) / delta) + 2);
    else hue = 60 * (((rn - gn) / delta) + 4);
  }
  if (hue < 0) hue += 360;

  const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * lightness - 1));
  return { hex, r, g, b, hue, saturation, lightness };
};


const colourSortKey = (record) => {
  const colour = colourFromHex(record);
  return {
    ...colour,
    neutral: colour.saturation < 0.14 ? 0 : 1
  };
};

const getColourColumns = () => {
  if (window.innerWidth >= 1500) return 36;
  if (window.innerWidth >= 1100) return 30;
  if (window.innerWidth >= 760) return 24;
  return 16;
};

const srgbToLinear = (channel) => {
  const value = channel / 255;
  return value <= 0.04045
    ? value / 12.92
    : Math.pow((value + 0.055) / 1.055, 2.4);
};

const rgbToLab = ({ r, g, b }) => {
  const red = srgbToLinear(r);
  const green = srgbToLinear(g);
  const blue = srgbToLinear(b);

  // sRGB → XYZ, using the D65 reference white.
  const x = (red * 0.4124564 + green * 0.3575761 + blue * 0.1804375) / 0.95047;
  const y = (red * 0.2126729 + green * 0.7151522 + blue * 0.0721750) / 1.00000;
  const z = (red * 0.0193339 + green * 0.1191920 + blue * 0.9503041) / 1.08883;

  const transform = (value) => value > 216 / 24389
    ? Math.cbrt(value)
    : ((24389 / 27) * value + 16) / 116;

  const fx = transform(x);
  const fy = transform(y);
  const fz = transform(z);

  return {
    l: 116 * fy - 16,
    a: 500 * (fx - fy),
    labB: 200 * (fy - fz)
  };
};

const degreesToRadians = (degrees) => degrees * Math.PI / 180;
const radiansToDegrees = (radians) => radians * 180 / Math.PI;

// CIEDE2000 compares colours in CIELAB space according to perceptual distance.
// A smaller result means that two colours look more similar to the human eye.
const deltaE2000 = (first, second) => {
  const l1 = first.l;
  const a1 = first.a;
  const b1 = first.labB;
  const l2 = second.l;
  const a2 = second.a;
  const b2 = second.labB;

  const c1 = Math.sqrt(a1 * a1 + b1 * b1);
  const c2 = Math.sqrt(a2 * a2 + b2 * b2);
  const meanC = (c1 + c2) / 2;
  const meanC7 = Math.pow(meanC, 7);
  const g = 0.5 * (1 - Math.sqrt(meanC7 / (meanC7 + Math.pow(25, 7))));

  const a1Prime = (1 + g) * a1;
  const a2Prime = (1 + g) * a2;
  const c1Prime = Math.sqrt(a1Prime * a1Prime + b1 * b1);
  const c2Prime = Math.sqrt(a2Prime * a2Prime + b2 * b2);

  const hue = (labB, aPrime) => {
    if (aPrime === 0 && labB === 0) return 0;
    const value = radiansToDegrees(Math.atan2(labB, aPrime));
    return value >= 0 ? value : value + 360;
  };

  const h1Prime = hue(b1, a1Prime);
  const h2Prime = hue(b2, a2Prime);

  const deltaLPrime = l2 - l1;
  const deltaCPrime = c2Prime - c1Prime;

  let deltaHuePrime = 0;
  if (c1Prime * c2Prime !== 0) {
    const hueDifference = h2Prime - h1Prime;
    if (Math.abs(hueDifference) <= 180) deltaHuePrime = hueDifference;
    else if (hueDifference > 180) deltaHuePrime = hueDifference - 360;
    else deltaHuePrime = hueDifference + 360;
  }

  const deltaHPrime = 2
    * Math.sqrt(c1Prime * c2Prime)
    * Math.sin(degreesToRadians(deltaHuePrime / 2));

  const meanLPrime = (l1 + l2) / 2;
  const meanCPrime = (c1Prime + c2Prime) / 2;

  let meanHPrime = h1Prime + h2Prime;
  if (c1Prime * c2Prime === 0) {
    meanHPrime = h1Prime + h2Prime;
  } else if (Math.abs(h1Prime - h2Prime) <= 180) {
    meanHPrime = (h1Prime + h2Prime) / 2;
  } else if (h1Prime + h2Prime < 360) {
    meanHPrime = (h1Prime + h2Prime + 360) / 2;
  } else {
    meanHPrime = (h1Prime + h2Prime - 360) / 2;
  }

  const t = 1
    - 0.17 * Math.cos(degreesToRadians(meanHPrime - 30))
    + 0.24 * Math.cos(degreesToRadians(2 * meanHPrime))
    + 0.32 * Math.cos(degreesToRadians(3 * meanHPrime + 6))
    - 0.20 * Math.cos(degreesToRadians(4 * meanHPrime - 63));

  const deltaTheta = 30 * Math.exp(-Math.pow((meanHPrime - 275) / 25, 2));
  const meanCPrime7 = Math.pow(meanCPrime, 7);
  const rC = 2 * Math.sqrt(meanCPrime7 / (meanCPrime7 + Math.pow(25, 7)));
  const sL = 1 + (0.015 * Math.pow(meanLPrime - 50, 2))
    / Math.sqrt(20 + Math.pow(meanLPrime - 50, 2));
  const sC = 1 + 0.045 * meanCPrime;
  const sH = 1 + 0.015 * meanCPrime * t;
  const rT = -Math.sin(degreesToRadians(2 * deltaTheta)) * rC;

  const lightnessTerm = deltaLPrime / sL;
  const chromaTerm = deltaCPrime / sC;
  const hueTerm = deltaHPrime / sH;

  return Math.sqrt(
    lightnessTerm * lightnessTerm
    + chromaTerm * chromaTerm
    + hueTerm * hueTerm
    + rT * chromaTerm * hueTerm
  );
};

const buildPerceptualColourPath = (items) => {
  const nodes = items.map(record => {
    const colour = colourFromHex(record);
    return {
      record,
      colour,
      lab: rgbToLab(colour)
    };
  });

  if (nodes.length < 2) return nodes;

  // Cache every perceptual distance once so arranging the wall remains quick.
  const distances = Array.from(
    { length: nodes.length },
    () => new Float32Array(nodes.length)
  );

  for (let first = 0; first < nodes.length; first += 1) {
    for (let second = first + 1; second < nodes.length; second += 1) {
      const distance = deltaE2000(nodes[first].lab, nodes[second].lab);
      distances[first][second] = distance;
      distances[second][first] = distance;
    }
  }

  // Begin with the darkest colour, then repeatedly choose the perceptually
  // nearest unplaced colour. This creates a continuous colour sequence rather
  // than breaking colours apart at binary RGB boundaries.
  let startIndex = 0;
  for (let index = 1; index < nodes.length; index += 1) {
    if (nodes[index].lab.l < nodes[startIndex].lab.l) startIndex = index;
  }

  const visited = new Uint8Array(nodes.length);
  const path = [startIndex];
  visited[startIndex] = 1;

  while (path.length < nodes.length) {
    const current = path[path.length - 1];
    let nearest = -1;
    let nearestDistance = Number.POSITIVE_INFINITY;

    for (let candidate = 0; candidate < nodes.length; candidate += 1) {
      if (visited[candidate]) continue;
      const distance = distances[current][candidate];
      if (distance < nearestDistance) {
        nearest = candidate;
        nearestDistance = distance;
      }
    }

    visited[nearest] = 1;
    path.push(nearest);
  }

  // A few bounded 2-opt passes remove obvious detours without slowing the page.
  const optimisationWindow = 42;
  for (let pass = 0; pass < 5; pass += 1) {
    let improved = false;

    for (let first = 1; first < path.length - 2; first += 1) {
      const limit = Math.min(path.length - 2, first + optimisationWindow);
      for (let second = first + 1; second <= limit; second += 1) {
        const previous = path[first - 1];
        const current = path[first];
        const later = path[second];
        const next = path[second + 1];

        const existingDistance = distances[previous][current] + distances[later][next];
        const proposedDistance = distances[previous][later] + distances[current][next];

        if (proposedDistance + 0.01 < existingDistance) {
          const reversed = path.slice(first, second + 1).reverse();
          path.splice(first, reversed.length, ...reversed);
          improved = true;
        }
      }
    }

    if (!improved) break;
  }

  return path.map(index => nodes[index]);
};

const arrangeColourRows = (items, columns) => {
  const ordered = buildPerceptualColourPath(items);
  const rows = [];

  for (let index = 0; index < ordered.length; index += columns) {
    const row = ordered
      .slice(index, index + columns)
      .map(item => item.record);

    // Alternate the row direction so the colour path continues directly into
    // the next row instead of jumping from the far right back to the far left.
    if (rows.length % 2 === 1) row.reverse();
    rows.push(row);
  }

  return rows;
};
async function init() {
  const response = await fetch('data.json');
  state.data = await response.json();
  state.records = state.data.records;
  state.filtered = [...state.records];

  renderHero();
  renderMetrics();
  renderCharts();
  renderCenturyOptions();
  renderPlaceOptions();
  renderColourWall();
  applyArchiveFilters();
  bindEvents();
}

function renderHero() {
  const candidates = state.records.filter(record => record.image_url);
  const imageCount = Math.min(24, candidates.length);
  const step = Math.max(1, Math.floor(candidates.length / imageCount));
  const images = Array.from({ length: imageCount }, (_, index) => candidates[index * step]).filter(Boolean);
  const artworkLinks = images.map(record => `
    <a class="strip-img" href="${record.landing_page}" target="_blank" rel="noreferrer" title="${clean(record.title)}">
      <img src="${record.image_url}" alt="${clean(record.title)}" loading="lazy">
    </a>
  `).join('');

  $('#heroStrip').innerHTML = `
    <div class="hero-strip-track">
      <div class="hero-strip-set">${artworkLinks}</div>
      <div class="hero-strip-set" aria-hidden="true">${artworkLinks}</div>
    </div>
  `;
}

function renderMetrics() {
  const s = state.data.summary;
  const metrics = [
    ['Total records', s.total_records],
    ['Records with image', s.records_with_image],
    ['Dominant colours', s.records_with_dominant_colour],
    ['Unique places', s.unique_places]
  ];
  $('#metricGrid').innerHTML = metrics.map(([label, value]) => `
    <article class="metric">
      <strong>${value}</strong>
      <span>${label}</span>
    </article>
  `).join('');
}

function renderCharts() {
  const years = state.records.map(r => r.year).filter(Boolean);
  $('#yearRange').textContent = `${Math.min(...years)}–${Math.max(...years)}`;
  const centuryCounts = countBy(state.records, r => clean(r.century)).sort((a, b) => centuryStart(a[0]) - centuryStart(b[0]));
  renderLineChart('#centuryChart', centuryCounts);
  const placeCounts = countBy(state.records, r => clean(r.place)).slice(0, 10);
  renderBars('#placeChart', placeCounts);
}

function renderLineChart(selector, entries) {
  const width = 760;
  const height = 390;
  const pad = { top: 34, right: 28, bottom: 76, left: 44 };
  const max = Math.max(...entries.map(d => d[1]));
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const x = (i) => pad.left + (entries.length === 1 ? innerW / 2 : (i / (entries.length - 1)) * innerW);
  const y = (value) => pad.top + innerH - (value / max) * innerH;

  const points = entries.map(([label, count], i) => [x(i), y(count), label, count]);
  const path = points.map((p, i) => `${i ? 'L' : 'M'} ${p[0]} ${p[1]}`).join(' ');
  const area = `${path} L ${points.at(-1)[0]} ${pad.top + innerH} L ${points[0][0]} ${pad.top + innerH} Z`;

  $(selector).innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Records by century line chart">
      <line class="axis-line" x1="${pad.left}" y1="${pad.top + innerH}" x2="${width - pad.right}" y2="${pad.top + innerH}" />
      <path class="area-path" d="${area}" />
      <path class="line-path" d="${path}" />
      ${points.map(([px, py, label, count]) => `
        <circle class="line-dot" cx="${px}" cy="${py}" r="6" />
        <text class="line-value" x="${px}" y="${py - 14}" text-anchor="middle">${count}</text>
        <text class="axis-label" x="${px}" y="${height - 34}" text-anchor="middle" transform="rotate(-34 ${px} ${height - 34})">${label}</text>
      `).join('')}
    </svg>
  `;
}

function renderBars(selector, entries) {
  const max = Math.max(...entries.map(d => d[1]));
  const minAlpha = 0.28;
  $(selector).innerHTML = entries.map(([label, count]) => {
    const ratio = count / max;
    const alpha = (minAlpha + ratio * (1 - minAlpha)).toFixed(2);
    return `
      <div class="bar-row">
        <span class="bar-label" title="${label}">${label}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${ratio * 100}%; --bar-alpha:${alpha}"></span></span>
        <span class="bar-value">${count}</span>
      </div>
    `;
  }).join('');
}

function renderCenturyOptions() {
  const centuries = [...new Set(state.records.map(r => clean(r.century)))].sort((a, b) => centuryStart(a) - centuryStart(b));
  $('#centurySelect').innerHTML += centuries.map(c => `<option value="${c}">${c}</option>`).join('');
}


function renderPlaceOptions() {
  const places = [...new Set(state.records.map(record => clean(record.place)).filter(Boolean))]
    .sort((a, b) => {
      const aUnknown = /^unknown(?: place)?$/i.test(a);
      const bUnknown = /^unknown(?: place)?$/i.test(b);
      if (aUnknown !== bUnknown) return aUnknown ? 1 : -1;
      return a.localeCompare(b, undefined, { sensitivity: 'base' });
    });

  $('#placeSelect').innerHTML = '<option value="all">All places</option>'
    + places.map(place => `<option value="${place}">${place}</option>`).join('');
}

function renderColourWall() {
  const records = state.records.filter(record => record.dominant_colour?.hex);
  const columns = getColourColumns();
  const rows = arrangeColourRows(records, columns);
  state.colourColumns = columns;

  $('#colourWall').innerHTML = rows.map(row => `
    <div class="colour-row" style="--colour-columns:${columns}">
      ${row.map(record => {
        const hex = normaliseHex(record.dominant_colour.hex);
        return `
          <a class="colour-tile" href="${record.landing_page}" target="_blank" rel="noreferrer"
             data-id="${clean(record.object_id)}"
             data-title="${clean(record.title)}"
             data-creator="${clean(record.creator)}"
             data-date="${clean(record.date)}"
             data-place="${clean(record.place)}"
             data-type="${clean(record.object_type)}"
             data-hex="${hex}"
             data-image="${record.image_url || record.thumbnail_url || ''}"
             style="background:${hex}" aria-label="${clean(record.title)}"></a>
        `;
      }).join('')}
    </div>
  `).join('');

  const tooltip = $('#colourTooltip');
  $$('.colour-tile').forEach(tile => {
    tile.addEventListener('mouseenter', event => {
      showColourTooltip(tile);
      moveColourTooltip(event);
    });
    tile.addEventListener('mousemove', moveColourTooltip);
    tile.addEventListener('mouseleave', () => {
      tooltip.classList.remove('visible');
      tooltip.setAttribute('aria-hidden', 'true');
    });
  });
}

function showColourTooltip(tile) {
  const tooltip = $('#colourTooltip');
  const img = tile.dataset.image
    ? `<img src="${tile.dataset.image}" alt="${tile.dataset.title}" loading="lazy">`
    : `<div class="tooltip-placeholder">No image available</div>`;
  tooltip.innerHTML = `
    <div class="tooltip-inner">
      ${img}
      <div class="tooltip-content">
        <p class="tooltip-eyebrow">${tile.dataset.type}</p>
        <h3 class="tooltip-title">${tile.dataset.title}</h3>
        <dl class="tooltip-details">
          <dt>Creator</dt><dd>${tile.dataset.creator}</dd>
          <dt>Date</dt><dd>${tile.dataset.date}</dd>
          <dt>Place</dt><dd>${tile.dataset.place}</dd>
          <dt>Object ID</dt><dd>${tile.dataset.id}</dd>
        </dl>
        <div class="tooltip-colour">
          <span class="tooltip-hex">${tile.dataset.hex}</span>
          <span class="tooltip-swatch" style="background:${tile.dataset.hex}"></span>
        </div>
      </div>
    </div>
  `;
  tooltip.classList.add('visible');
  tooltip.setAttribute('aria-hidden', 'false');
}

function moveColourTooltip(event) {
  const tooltip = $('#colourTooltip');
  const offsetX = 46;
  const offsetY = 26;
  const edgeGap = 14;
  const rect = tooltip.getBoundingClientRect();
  const width = rect.width || 340;
  const height = rect.height || 470;
  let left = event.clientX + offsetX;
  let top = event.clientY + offsetY;

  // Keep the card to the right of the cursor whenever there is room.
  // It only flips to the left near the viewport edge.
  if (left + width > window.innerWidth - edgeGap) {
    left = event.clientX - width - offsetX;
  }
  if (top + height > window.innerHeight - edgeGap) {
    top = event.clientY - height - offsetY;
  }

  tooltip.style.left = `${Math.max(edgeGap, left)}px`;
  tooltip.style.top = `${Math.max(edgeGap, top)}px`;
}

function applyArchiveFilters() {
  const q = $('#searchInput')?.value?.trim().toLowerCase() || '';
  const century = $('#centurySelect')?.value || 'all';
  const place = $('#placeSelect')?.value || 'all';
  const sort = $('#sortSelect')?.value || 'year-asc';

  state.filtered = state.records.filter(record => {
    const haystack = [record.title, record.creator, record.place, record.object_type, record.date].map(v => clean(v, '')).join(' ').toLowerCase();
    const matchesSearch = !q || haystack.includes(q);
    const matchesCentury = century === 'all' || clean(record.century) === century;
    const matchesPlace = place === 'all' || clean(record.place) === place;
    return matchesSearch && matchesCentury && matchesPlace;
  });

  state.filtered.sort((a, b) => {
    if (sort === 'year-asc') return (a.year || 9999) - (b.year || 9999);
    if (sort === 'year-desc') return (b.year || -9999) - (a.year || -9999);
    if (sort === 'title-asc') return clean(a.title).localeCompare(clean(b.title));
    if (sort === 'colour') {
      const ca = colourSortKey(a);
      const cb = colourSortKey(b);
      return ca.neutral - cb.neutral
        || ca.hue - cb.hue
        || ca.lightness - cb.lightness
        || ca.hex.localeCompare(cb.hex);
    }
    return 0;
  });

  const maxPage = Math.max(1, Math.ceil(state.filtered.length / state.perPage));
  state.page = Math.min(state.page, maxPage);
  renderCards();
}

function renderCards() {
  const start = (state.page - 1) * state.perPage;
  const pageItems = state.filtered.slice(start, start + state.perPage);
  $('#archiveMeta').textContent = `${state.filtered.length} records matched · showing ${pageItems.length} objects`;
  $('#cardGrid').innerHTML = pageItems.map(record => `
    <article class="art-card">
      <div class="image-wrap">
        ${record.image_url ? `<img src="${record.image_url}" alt="${clean(record.title)}" loading="lazy">` : `<div class="placeholder">No image</div>`}
      </div>
      <div class="art-body">
        <h3>${clean(record.title)}</h3>
        <p>${clean(record.creator)}<br>${clean(record.date)} · ${clean(record.place)}</p>
      </div>
      <a class="art-link" href="${record.landing_page}" target="_blank" rel="noreferrer">
        Open object <span>↗</span>
      </a>
    </article>
  `).join('');

  const maxPage = Math.max(1, Math.ceil(state.filtered.length / state.perPage));
  $('#pageInfo').textContent = `Page ${state.page} / ${maxPage}`;
  $('#prevPage').disabled = state.page === 1;
  $('#nextPage').disabled = state.page === maxPage;
}

function bindEvents() {
  $('#themeToggle').addEventListener('click', () => document.body.classList.toggle('dark'));
  $('#searchInput').addEventListener('input', () => { state.page = 1; applyArchiveFilters(); });
  $('#centurySelect').addEventListener('change', () => { state.page = 1; applyArchiveFilters(); });
  $('#placeSelect').addEventListener('change', () => { state.page = 1; applyArchiveFilters(); });
  $('#sortSelect').addEventListener('change', () => { state.page = 1; applyArchiveFilters(); });
  $('#prevPage').addEventListener('click', () => { state.page--; renderCards(); });
  $('#nextPage').addEventListener('click', () => { state.page++; renderCards(); });


  let resizeTimer;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (getColourColumns() !== state.colourColumns) renderColourWall();
    }, 140);
  });
}

init().catch(error => {
  console.error(error);
  document.body.innerHTML = `<main style="padding:40px;font-family:system-ui"><h1>Data loading failed</h1><p>Please run this page through a local server, for example: <code>python -m http.server</code>.</p></main>`;
});
