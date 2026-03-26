"""
build.py — generate docs/index.html (static GitHub Pages build).

Reads data/catalogue.json and templates/index.html, then writes
docs/index.html with the catalogue embedded as a JS constant and
all Flask API calls replaced with in-memory equivalents.

Usage:
    python build.py
"""

import json
import os
import re

ROOT     = os.path.dirname(__file__)
CATALOGUE_PATH = os.path.join(ROOT, "data", "catalogue.json")
TEMPLATE_PATH  = os.path.join(ROOT, "templates", "index.html")
OUT_DIR        = os.path.join(ROOT, "docs")
OUT_PATH       = os.path.join(OUT_DIR, "index.html")


def load_catalogue():
    with open(CATALOGUE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["flavours"]


def read_template():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Static JS that replaces all fetch('/api/...') calls
# ---------------------------------------------------------------------------
STATIC_JS = r"""
// ── Embedded catalogue ────────────────────────────────────────────────────────
// CATALOGUE_PLACEHOLDER

// Pre-compute brands index
const _brandsIndex = (function() {
  const map = {};
  CATALOGUE.forEach(function(f) {
    if (!f.marca) return;
    if (!map[f.marca]) map[f.marca] = [];
    map[f.marca].push(f);
  });
  return map;
})();

const BRANDS = (function() {
  return Object.keys(_brandsIndex).sort(function(a, b) {
    return a.toLowerCase().localeCompare(b.toLowerCase());
  }).map(function(name) {
    const flavours = _brandsIndex[name];
    const prices = flavours.reduce(function(acc, f) {
      f.formatos.forEach(function(fmt) { acc.push(fmt.price); });
      return acc;
    }, []);
    const sizesSet = {};
    flavours.forEach(function(f) {
      f.formatos.forEach(function(fmt) { sizesSet[fmt.grams] = true; });
    });
    const sizes = Object.keys(sizesSet).map(Number).sort(function(a, b) { return a - b; });
    return {
      name:          name,
      brand_img:     flavours[0] ? flavours[0].brand_img || '' : '',
      flavour_count: flavours.length,
      sizes:         sizes,
      price_min:     prices.length ? Math.min.apply(null, prices) : null,
      price_max:     prices.length ? Math.max.apply(null, prices) : null,
    };
  });
})();

// ── State ─────────────────────────────────────────────────────────────────────
const cart = [];

// ── Init ──────────────────────────────────────────────────────────────────────
(function init() {
  const el = document.getElementById('catalogue-meta');
  el.textContent = CATALOGUE.length.toLocaleString() + ' flavours';
})();

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.panel').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('panel-' + name).classList.add('active');
  btn.classList.add('active');
  if (name === 'brands') { loadBrandsGrid(); }
}

// ── Fuzzy search (in-memory) ──────────────────────────────────────────────────
function norm(text) {
  if (!text) return '';
  return (text + '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function bigrams(s) {
  var r = [];
  for (var i = 0; i < s.length - 1; i++) r.push(s.slice(i, i + 2));
  return r;
}

function bigramSim(a, b) {
  if (!a || !b) return 0;
  var ba = bigrams(a), bb = bigrams(b);
  if (!ba.length || !bb.length) return 0;
  var used = new Array(bb.length).fill(false);
  var matches = 0;
  for (var i = 0; i < ba.length; i++) {
    for (var j = 0; j < bb.length; j++) {
      if (!used[j] && bb[j] === ba[i]) { matches++; used[j] = true; break; }
    }
  }
  return (2 * matches) / (ba.length + bb.length);
}

function tokenOverlap(a, b) {
  var ta = a.split(/\s+/).filter(function(w) { return w.length > 1; });
  var tb = b.split(/\s+/).filter(function(w) { return w.length > 1; });
  if (!ta.length || !tb.length) return 0;
  var tbSet = {};
  tb.forEach(function(w) { tbSet[w] = true; });
  var inter = ta.filter(function(w) { return tbSet[w]; }).length;
  return inter / Math.min(ta.length, tb.length);
}

function scoreMatch(query, f) {
  var q     = norm(query);
  var name  = norm(f.nombre);
  var brand = norm(f.marca);
  var desc  = norm(f.descripcion || '');
  var full  = name + ' ' + brand + ' ' + desc;

  // Strip brand prefix from query
  var qStripped = q;
  if (brand && q.indexOf(brand) === 0) {
    qStripped = q.slice(brand.length).trim();
  } else if (brand) {
    brand.split(/\s+/).forEach(function(w) {
      if (w.length > 2) qStripped = qStripped.replace(w, '').trim();
    });
  }

  var s1 = tokenOverlap(q, full) * 100;
  var s2 = bigramSim(q, name) * 100;
  var s3 = qStripped !== q ? bigramSim(qStripped, name) * 100 : s2;

  var s = Math.max(s1, s2, s3);

  // Exact substring bonus
  if (full.indexOf(q) !== -1) s = Math.min(100, s + 25);

  // All significant words present bonus
  var words = q.split(/\s+/).filter(function(w) { return w.length > 2; });
  if (words.length && words.every(function(w) { return full.indexOf(w) !== -1; })) {
    s = Math.min(100, s + 15);
  }

  return s;
}

function fuzzySearch(query, limit) {
  limit = limit || 30;
  var q = norm(query);
  var scored = CATALOGUE.map(function(f) { return [scoreMatch(q, f), f]; });
  scored.sort(function(a, b) { return b[0] - a[0]; });
  return scored.slice(0, limit)
    .filter(function(pair) { return pair[0] >= 45; })
    .map(function(pair) { return pair[1]; });
}

function bestMatch(query) {
  var q = norm(query);
  var scored = CATALOGUE.map(function(f) { return [scoreMatch(q, f), f]; });
  scored.sort(function(a, b) { return b[0] - a[0]; });
  if (scored.length && scored[0][0] >= 55) return scored[0][1];
  return null;
}

// ── Search ────────────────────────────────────────────────────────────────────
var searchTimer = null;

document.getElementById('search-input').addEventListener('input', function(e) {
  clearTimeout(searchTimer);
  var q = e.target.value.trim();
  if (!q) {
    document.getElementById('results').textContent = '';
    document.getElementById('results-count').textContent = '';
    return;
  }
  searchTimer = setTimeout(function() { doSearch(q); }, 260);
});

function doSearch(q) {
  var el      = document.getElementById('results');
  var countEl = document.getElementById('results-count');
  el.textContent = '';
  countEl.textContent = '';
  el.appendChild(makeSpinner('Searching\u2026'));

  // Defer so the spinner renders before the (synchronous) search runs
  setTimeout(function() {
    var data = fuzzySearch(q, 30);
    el.textContent = '';

    if (!data.length) {
      countEl.textContent = 'No results';
      var msg = document.createElement('p');
      msg.style.cssText = 'color:var(--text-dim);font-style:italic;font-size:.85rem;padding:8px 2px';
      msg.textContent = 'No flavours matched "' + q + '".';
      el.appendChild(msg);
      return;
    }

    countEl.textContent = data.length + ' result' + (data.length !== 1 ? 's' : '');
    data.forEach(function(f) { el.appendChild(buildCard(f)); });
  }, 0);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeSpinner(text) {
  var wrap = document.createElement('div');
  wrap.className = 'spinner';
  var ring = document.createElement('div');
  ring.className = 'spin-ring';
  wrap.appendChild(ring);
  wrap.appendChild(document.createTextNode(text || ''));
  return wrap;
}

function makeEl(tag, className, text) {
  var el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

// ── Card ──────────────────────────────────────────────────────────────────────
function brandInitials(name) {
  if (!name) return '?';
  var words = name.trim().split(/\s+/);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function buildBrandAvatar(f) {
  var wrap = document.createElement('div');
  wrap.className = 'brand-avatar';
  wrap.appendChild(makeEl('span', 'brand-avatar-initials', brandInitials(f.marca)));
  return wrap;
}

function buildCard(f) {
  var card = document.createElement('div');
  card.className = 'flavour-card';
  card.appendChild(buildBrandAvatar(f));

  var body = document.createElement('div');
  body.className = 'flavour-body';

  var meta = document.createElement('div');
  meta.className = 'flavour-meta';
  meta.appendChild(makeEl('span', 'flavour-brand', f.marca));
  body.appendChild(meta);
  body.appendChild(makeEl('div', 'flavour-name', f.nombre));

  if (f.descripcion) body.appendChild(makeEl('div', 'flavour-desc', f.descripcion));

  body.appendChild(buildSizeRow(f));
  card.appendChild(body);
  return card;
}

function buildSizeRow(f) {
  var row = document.createElement('div');
  row.className = 'size-row';

  if (!f.formatos || !f.formatos.length) {
    row.appendChild(makeEl('span', 'no-price', 'No price info'));
    return row;
  }

  // Quantity stepper
  var qtyWrap = makeEl('div', 'size-qty');
  var decBtn  = makeEl('button', 'size-qty-btn', '\u2212');
  var qtyNum  = document.createElement('input');
  qtyNum.type = 'number'; qtyNum.min = '1'; qtyNum.value = '1';
  qtyNum.className = 'size-qty-num';
  qtyNum.addEventListener('click', function(e) { e.stopPropagation(); });
  qtyNum.addEventListener('change', function() {
    if (!qtyNum.value || parseInt(qtyNum.value) < 1) qtyNum.value = '1';
  });
  var incBtn  = makeEl('button', 'size-qty-btn', '+');
  decBtn.addEventListener('click', function() {
    var v = parseInt(qtyNum.value) || 1;
    if (v > 1) qtyNum.value = v - 1;
  });
  incBtn.addEventListener('click', function() {
    qtyNum.value = (parseInt(qtyNum.value) || 1) + 1;
  });
  qtyWrap.appendChild(decBtn);
  qtyWrap.appendChild(qtyNum);
  qtyWrap.appendChild(incBtn);

  f.formatos.forEach(function(fmt, i) {
    var pill = makeEl('button', 'size-pill' + (i === 0 ? ' selected' : ''),
      fmt.grams + 'g \u2014 ' + fmt.price.toFixed(2) + '\u20AC');
    pill.dataset.grams = fmt.grams;
    pill.dataset.price = fmt.price;
    pill.addEventListener('click', function() {
      selectSize(pill);
      addToCartFromRow(row, f, pill);
    });
    row.appendChild(pill);
  });

  row.appendChild(qtyWrap);
  return row;
}

function selectSize(pill) {
  pill.closest('.size-row').querySelectorAll('.size-pill')
      .forEach(function(p) { p.classList.remove('selected'); });
  pill.classList.add('selected');
}

function addToCartFromRow(row, f, pill) {
  var selected = row.querySelector('.size-pill.selected');
  if (!selected) return;

  var grams = parseInt(selected.dataset.grams);
  var price = parseFloat(selected.dataset.price);
  var qtyEl = row.querySelector('.size-qty-num');
  var qty   = qtyEl ? Math.max(1, parseInt(qtyEl.value) || 1) : 1;
  var existing = cart.find(function(i) { return i.id === f.id && i.selectedGrams === grams; });

  if (existing) {
    existing.qty += qty;
    renderCart();
    flashBtn(pill, '+' + qty, true);
    return;
  }

  cart.push({ id: f.id, nombre: f.nombre, marca: f.marca,
              formatos: f.formatos, selectedGrams: grams, selectedPrice: price, qty: qty });
  renderCart();
  flashBtn(pill, '\u2713', true);
}

function flashBtn(btn, msg, success) {
  var orig = btn.textContent;
  btn.textContent = msg;
  if (success) btn.classList.add('flash');
  btn.disabled = true;
  setTimeout(function() {
    btn.textContent = orig;
    btn.classList.remove('flash');
    btn.disabled = false;
  }, 1300);
}

// ── Cart ──────────────────────────────────────────────────────────────────────
function renderCart() {
  var el    = document.getElementById('cart-items');
  var badge = document.getElementById('cart-count');
  el.textContent = '';

  var totalQty = cart.reduce(function(s, i) { return s + i.qty; }, 0);
  badge.textContent = totalQty;
  badge.classList.remove('pop');
  void badge.offsetWidth;
  badge.classList.add('pop');

  if (!cart.length) {
    var empty = document.createElement('div');
    empty.className = 'cart-empty';
    var icon = makeEl('div', 'cart-empty-icon', '\u25C6');
    var txt  = makeEl('div', 'cart-empty-text', '');
    txt.textContent = 'Your cart is empty.\nSearch or import flavours to add them.';
    txt.style.whiteSpace = 'pre-line';
    empty.appendChild(icon);
    empty.appendChild(txt);
    el.appendChild(empty);
    document.getElementById('cart-total').textContent = '0.00 \u20AC';
    document.getElementById('cart-total-items').textContent = '';
    return;
  }

  var total = 0;
  cart.forEach(function(item, idx) {
    total += item.selectedPrice * item.qty;
    el.appendChild(buildCartItem(item, idx));
  });

  document.getElementById('cart-total').textContent = total.toFixed(2) + ' \u20AC';
  var units = cart.reduce(function(s, i) { return s + i.qty; }, 0);
  var lines = cart.length;
  document.getElementById('cart-total-items').textContent =
    units + ' unit' + (units !== 1 ? 's' : '') +
    ' \u00b7 ' + lines + ' flavour' + (lines !== 1 ? 's' : '');
}

function buildCartItem(item, idx) {
  var div = document.createElement('div');
  div.className = 'cart-item';

  var header = document.createElement('div');
  header.className = 'ci-header';

  var info = document.createElement('div');
  info.className = 'ci-info';
  info.appendChild(makeEl('div', 'ci-brand', item.marca));
  info.appendChild(makeEl('div', 'ci-name', item.nombre));

  var removeBtn = makeEl('button', 'ci-remove', '\u00d7');
  removeBtn.title = 'Remove';
  removeBtn.addEventListener('click', function() { removeFromCart(idx); });

  header.appendChild(info);
  header.appendChild(removeBtn);
  div.appendChild(header);

  var controls = document.createElement('div');
  controls.className = 'ci-controls';

  var sel = document.createElement('select');
  sel.className = 'ci-size';
  item.formatos.forEach(function(fmt) {
    var opt = document.createElement('option');
    opt.value = fmt.grams;
    opt.dataset.price = fmt.price;
    opt.textContent = fmt.grams + 'g \u2014 ' + fmt.price.toFixed(2) + '\u20AC';
    if (fmt.grams === item.selectedGrams) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.addEventListener('change', function() {
    var opt = sel.options[sel.selectedIndex];
    cart[idx].selectedGrams = parseInt(sel.value);
    cart[idx].selectedPrice = parseFloat(opt.dataset.price);
    renderCart();
  });

  var qtyWrap = document.createElement('div');
  qtyWrap.className = 'ci-qty';

  var decBtn = makeEl('button', 'ci-qty-btn', '\u2212');
  decBtn.addEventListener('click', function() {
    if (cart[idx].qty > 1) { cart[idx].qty--; renderCart(); }
    else removeFromCart(idx);
  });

  var qtyNum = document.createElement('input');
  qtyNum.type = 'number'; qtyNum.min = '1'; qtyNum.value = item.qty;
  qtyNum.className = 'ci-qty-num';
  qtyNum.addEventListener('change', function() {
    var v = parseInt(qtyNum.value);
    if (!v || v < 1) { removeFromCart(idx); return; }
    cart[idx].qty = v;
    renderCart();
  });

  var incBtn = makeEl('button', 'ci-qty-btn', '+');
  incBtn.addEventListener('click', function() { cart[idx].qty++; renderCart(); });

  qtyWrap.appendChild(decBtn);
  qtyWrap.appendChild(qtyNum);
  qtyWrap.appendChild(incBtn);

  var linePrice = makeEl('span', 'ci-price',
    (item.selectedPrice * item.qty).toFixed(2) + '\u20AC');

  controls.appendChild(sel);
  controls.appendChild(qtyWrap);
  controls.appendChild(linePrice);
  div.appendChild(controls);
  return div;
}

function removeFromCart(idx) {
  cart.splice(idx, 1);
  renderCart();
}

function clearCart() {
  if (!cart.length) return;
  if (!confirm('Clear all ' + cart.length + ' item(s) from cart?')) return;
  cart.length = 0;
  renderCart();
}

// ── Import ────────────────────────────────────────────────────────────────────
var _importMatches = [];

function runImport() {
  var raw = document.getElementById('import-area').value.trim();
  if (!raw) return;

  var btn      = document.getElementById('import-btn');
  var addBtn   = document.getElementById('import-add-btn');
  var resultEl = document.getElementById('import-result');
  var lines    = raw.split('\n').filter(function(l) { return l.trim(); });

  btn.disabled = true;
  addBtn.style.display = 'none';
  _importMatches = [];
  resultEl.textContent = '';
  resultEl.appendChild(makeSpinner('Finding matches\u2026'));

  // Defer so spinner renders
  setTimeout(function() {
    var data = [];
    lines.forEach(function(line) {
      line.split(',').forEach(function(part) {
        part = part.trim();
        if (!part) return;
        data.push({ query: part, match: bestMatch(part) });
      });
    });

    _importMatches = data
      .filter(function(r) { return r.match; })
      .map(function(r) { return r.match; });

    resultEl.textContent = '';
    if (data.length) {
      resultEl.appendChild(makeEl('div', 'section-label',
        data.length + ' quer' + (data.length !== 1 ? 'ies' : 'y') + ' processed'));
    }
    data.forEach(function(row) { resultEl.appendChild(buildImportRow(row)); });

    if (_importMatches.length) addBtn.style.display = '';
    btn.disabled = false;
  }, 0);
}

function addAllMatches() {
  _importMatches.forEach(function(f) {
    if (!f.formatos || !f.formatos.length) return;
    var fmt = f.formatos[0];
    var existing = cart.find(function(c) { return c.id === f.id && c.selectedGrams === fmt.grams; });
    if (existing) { existing.qty += 1; }
    else {
      cart.push({ id: f.id, nombre: f.nombre, marca: f.marca, formatos: f.formatos,
        selectedGrams: fmt.grams, selectedPrice: fmt.price, qty: 1 });
    }
  });
  renderCart();
}

function buildImportRow(row) {
  var div = document.createElement('div');
  div.className = 'import-row';

  var qLine = document.createElement('div');
  qLine.className = 'import-query';
  qLine.appendChild(document.createTextNode('query\u00a0'));
  qLine.appendChild(makeEl('span', 'import-query-tag', row.query));
  div.appendChild(qLine);

  if (!row.match) {
    div.appendChild(makeEl('div', 'import-no-match', 'No match found'));
    return div;
  }

  var f = row.match;
  var matchHeader = document.createElement('div');
  matchHeader.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:8px';
  matchHeader.appendChild(buildBrandAvatar(f));
  var matchInfo = document.createElement('div');
  matchInfo.style.minWidth = '0';
  matchInfo.appendChild(makeEl('div', 'flavour-brand', f.marca));
  matchInfo.appendChild(makeEl('div', 'flavour-name', f.nombre));
  if (f.descripcion) matchInfo.appendChild(makeEl('div', 'flavour-desc', f.descripcion));
  matchHeader.appendChild(matchInfo);
  div.appendChild(matchHeader);

  var sizeRow = buildSizeRow(f);
  sizeRow.style.marginTop = '8px';
  div.appendChild(sizeRow);
  return div;
}

// ── Brands ────────────────────────────────────────────────────────────────────
var _brandsData = null;
var _activeSizeFilter = null;

function fillAvatarEl(el, name) {
  el.textContent = '';
  el.appendChild(makeEl('span', 'brand-avatar-initials', brandInitials(name)));
}

function buildAvatarForBrand(name, size) {
  var wrap = document.createElement('div');
  wrap.className = size === 'large' ? 'brand-detail-avatar' : 'brand-tile-avatar';
  fillAvatarEl(wrap, name);
  return wrap;
}

function loadBrandsGrid() {
  if (_brandsData) { renderBrandsGrid(_brandsData); return; }
  _brandsData = BRANDS;
  renderBrandsGrid(_brandsData);
}

function renderBrandsGrid(brands) {
  var grid    = document.getElementById('brand-grid');
  var countEl = document.getElementById('brands-count');
  grid.textContent = '';
  countEl.textContent = brands.length + ' brand' + (brands.length !== 1 ? 's' : '');

  brands.forEach(function(b) {
    var tile = document.createElement('div');
    tile.className = 'brand-tile';
    tile.dataset.name = b.name.toLowerCase();

    tile.appendChild(buildAvatarForBrand(b.name, 'small'));
    tile.appendChild(makeEl('div', 'brand-tile-name', b.name));

    var meta = document.createElement('div');
    meta.className = 'brand-tile-meta';
    meta.textContent = b.flavour_count + ' flavour' + (b.flavour_count !== 1 ? 's' : '');
    tile.appendChild(meta);

    if (b.price_min !== null) {
      var price = document.createElement('div');
      price.className = 'brand-tile-price';
      price.textContent = b.price_min === b.price_max
        ? b.price_min.toFixed(2) + '\u20AC'
        : b.price_min.toFixed(2) + ' \u2013 ' + b.price_max.toFixed(2) + '\u20AC';
      tile.appendChild(price);
    }

    tile.addEventListener('click', function() { openBrand(b.name); });
    grid.appendChild(tile);
  });
}

document.getElementById('brands-filter').addEventListener('input', function(e) {
  var q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('.brand-tile').forEach(function(tile) {
    tile.style.display = (!q || tile.dataset.name.indexOf(q) !== -1) ? '' : 'none';
  });
  var visible = document.querySelectorAll('.brand-tile:not([style*="none"])').length;
  document.getElementById('brands-count').textContent =
    visible + ' brand' + (visible !== 1 ? 's' : '');
});

function openBrand(brandName) {
  document.getElementById('brands-grid-view').style.display = 'none';
  var detail = document.getElementById('brands-detail-view');
  detail.classList.add('active');

  document.getElementById('brand-detail-name').textContent = brandName;
  document.getElementById('brand-detail-stats').textContent = '';
  document.getElementById('size-filter-row').textContent = '';
  document.getElementById('brand-flavour-list').textContent = '';

  var avatarWrap = document.getElementById('brand-detail-avatar');
  avatarWrap.textContent = '';
  fillAvatarEl(avatarWrap, brandName);

  var flavours = (_brandsIndex[brandName] || []).slice().sort(function(a, b) {
    return a.nombre.toLowerCase().localeCompare(b.nombre.toLowerCase());
  });

  var statsEl   = document.getElementById('brand-detail-stats');
  var allPrices = flavours.reduce(function(acc, f) {
    f.formatos.forEach(function(fmt) { acc.push(fmt.price); }); return acc;
  }, []);
  var sizesSet = {};
  flavours.forEach(function(f) {
    f.formatos.forEach(function(fmt) { sizesSet[fmt.grams] = true; });
  });
  var allSizes = Object.keys(sizesSet).map(Number).sort(function(a,b){return a-b;});

  function makeStat(label, value) {
    var s = document.createElement('span');
    var strong = document.createElement('strong');
    strong.textContent = value;
    s.appendChild(document.createTextNode(label + '\u00a0'));
    s.appendChild(strong);
    return s;
  }

  statsEl.appendChild(makeStat('', flavours.length + ' flavours'));
  if (allPrices.length) {
    statsEl.appendChild(makeStat('from\u00a0', Math.min.apply(null, allPrices).toFixed(2) + '\u20AC'));
    statsEl.appendChild(makeStat('to\u00a0', Math.max.apply(null, allPrices).toFixed(2) + '\u20AC'));
  }
  if (allSizes.length) {
    statsEl.appendChild(makeStat('sizes\u00a0', allSizes.join('g, ') + 'g'));
  }

  _activeSizeFilter = null;
  var filterRow = document.getElementById('size-filter-row');
  filterRow.appendChild(makeEl('span', 'size-filter-label', 'Filter by size'));

  var allChip = makeEl('button', 'size-chip active', 'All');
  allChip.addEventListener('click', function() {
    _activeSizeFilter = null;
    filterRow.querySelectorAll('.size-chip').forEach(function(c) { c.classList.remove('active'); });
    allChip.classList.add('active');
    applyBrandSizeFilter(null);
  });
  filterRow.appendChild(allChip);

  allSizes.forEach(function(g) {
    var chip = makeEl('button', 'size-chip', g + 'g');
    chip.addEventListener('click', function() {
      _activeSizeFilter = g;
      filterRow.querySelectorAll('.size-chip').forEach(function(c) { c.classList.remove('active'); });
      chip.classList.add('active');
      applyBrandSizeFilter(g);
    });
    filterRow.appendChild(chip);
  });

  var listEl = document.getElementById('brand-flavour-list');
  flavours.forEach(function(f) { listEl.appendChild(buildBrandFlavourRow(f)); });
}

function applyBrandSizeFilter(grams) {
  document.querySelectorAll('.bf-row').forEach(function(row) {
    if (!grams) { row.classList.remove('hidden'); return; }
    var sizes = row.dataset.sizes ? row.dataset.sizes.split(',').map(Number) : [];
    row.classList.toggle('hidden', sizes.indexOf(grams) === -1);
  });
}

function buildBrandFlavourRow(f) {
  var row = document.createElement('div');
  row.className = 'bf-row';
  row.dataset.sizes = f.formatos.map(function(fmt) { return fmt.grams; }).join(',');

  var info = document.createElement('div');
  info.className = 'bf-info';
  info.appendChild(makeEl('div', 'bf-name', f.nombre));
  if (f.descripcion) info.appendChild(makeEl('div', 'bf-desc', f.descripcion));
  row.appendChild(info);

  var pricesWrap = document.createElement('div');
  pricesWrap.className = 'bf-prices';

  if (f.formatos && f.formatos.length) {
    f.formatos.forEach(function(fmt) {
      pricesWrap.appendChild(makeEl('span', 'bf-price-tag',
        fmt.grams + 'g\u00a0' + fmt.price.toFixed(2) + '\u20AC'));
    });
  } else {
    pricesWrap.appendChild(makeEl('span', 'bf-no-price', 'no price'));
  }
  row.appendChild(pricesWrap);

  if (f.formatos && f.formatos.length) {
    row.style.cursor = 'pointer';
    row.addEventListener('click', function() {
      var fmt = f.formatos[0];
      var existing = cart.find(function(i) { return i.id === f.id && i.selectedGrams === fmt.grams; });
      if (existing) { existing.qty++; }
      else {
        cart.push({ id: f.id, nombre: f.nombre, marca: f.marca, formatos: f.formatos,
                    selectedGrams: fmt.grams, selectedPrice: fmt.price, qty: 1 });
      }
      renderCart();
      row.classList.add('flash');
      setTimeout(function() { row.classList.remove('flash'); }, 600);
    });
  }

  return row;
}

function showBrandGrid() {
  document.getElementById('brands-detail-view').classList.remove('active');
  document.getElementById('brands-grid-view').style.display = '';
}
"""


def main():
    flavours = load_catalogue()
    template = read_template()

    # Extract everything up to (and including) <script>
    script_idx = template.index('<script>')
    html_part = template[:script_idx + len('<script>')]

    # Strip the brand_img field — it's a Firebase URL, not sensitive but
    # useless in static context; keep the rest of each flavour object
    for f in flavours:
        f.pop('brand_img', None)
        f.pop('img', None)

    catalogue_json = json.dumps(flavours, ensure_ascii=False, separators=(',', ':'))
    catalogue_line = 'const CATALOGUE = ' + catalogue_json + ';'

    static_js = STATIC_JS.replace('// CATALOGUE_PLACEHOLDER', catalogue_line)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as out:
        out.write(html_part)
        out.write(static_js)
        out.write('\n</script>\n</body>\n</html>\n')

    size_kb = os.path.getsize(OUT_PATH) // 1024
    print(f'Built docs/index.html  ({size_kb} KB, {len(flavours)} flavours)')


if __name__ == '__main__':
    main()
