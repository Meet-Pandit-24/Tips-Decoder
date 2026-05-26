/* ── State ────────────────────────────────────────────────── */
const state = {
  optionType:  'BOTH',
  expiryScope: 'nearest',
};

/* ── Init ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  checkConnection();
  loadLotSizes();
  setupSegmentedControls();
  setupPrevClosePreview();
  setupRangeSlider();
  setupTabs();
  setupOCR();
});

/* ── Tabs ───────────────────────────────────────────────────── */
function setupTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.main').forEach(m => m.style.display = 'none');
      document.getElementById(tab.dataset.target).style.display = 'grid'; // or block based on css
      
      if(tab.dataset.target === 'dashboardView' && window.loadDashboard) {
          window.loadDashboard();
      } else if(tab.dataset.target === 'analyticsView' && window.loadAnalytics) {
          window.loadAnalytics();
      }
    });
  });
}

/* ── OCR (Screenshot Paste) ─────────────────────────────────── */
function setupOCR() {
  const pasteZone = document.getElementById('pasteZone');
  const fileInput = document.getElementById('imageUpload');
  
  // Mobile upload via tap
  pasteZone.addEventListener('click', () => {
    fileInput.click();
  });
  
  // Handle file selection
  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processImageOCR(e.target.files[0]);
    }
  });

  // Listen for paste anywhere on document
  document.addEventListener('paste', async (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    for (let index in items) {
      const item = items[index];
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const blob = item.getAsFile();
        processImageOCR(blob);
      }
    }
  });
}

async function processImageOCR(imageBlob) {
    const pasteZone = document.getElementById('pasteZone');
    pasteZone.classList.add('loading');
    pasteZone.innerHTML = '<div class="spinner" style="margin: 0 auto; width: 30px; height: 30px; border-width: 2px;"></div><p style="margin-top:10px">Extracting text...</p>';
    
    try {
        const result = await Tesseract.recognize(imageBlob, 'eng');
        const text = result.data.text;
        
        console.log("OCR Result:", text);
        
        // Very basic Regex to find a number followed by space and negative/positive number
        // e.g. "5.39 -1.03"
        const matches = text.match(/(\d+\.\d+)\s+([+-]\d+\.\d+)/);
        
        if(matches && matches.length >= 3) {
            const price = parseFloat(matches[1]);
            const change = parseFloat(matches[2]);
            
            document.getElementById('currentPrice').value = price;
            document.getElementById('absChange').value = change;
            document.getElementById('pctChange').value = '';
            
            // Trigger preview update
            document.getElementById('currentPrice').dispatchEvent(new Event('input'));
            document.getElementById('absChange').dispatchEvent(new Event('input'));
            
            pasteZone.innerHTML = '<div class="paste-icon">✅</div><p>Extracted: <strong>₹' + price + '</strong> (Change: <strong>' + change + '</strong>)</p>';
        } else {
            pasteZone.innerHTML = '<div class="paste-icon">⚠️</div><p>Could not parse numbers automatically.</p><p class="paste-sub">Please enter manually below.</p>';
        }
    } catch (err) {
        pasteZone.innerHTML = '<div class="paste-icon">❌</div><p>OCR Failed.</p>';
    }
    
    setTimeout(() => {
        pasteZone.classList.remove('loading');
        setTimeout(() => {
            pasteZone.innerHTML = '<div class="paste-icon">🖼️</div><p><strong>Tap/Click here to Upload or Paste (Ctrl+V)</strong></p><p class="paste-sub">Price and Change will auto-fill via OCR</p><input type="file" id="imageUpload" accept="image/*" style="display: none;" />';
            // Re-bind the change event since we just overwrote the input element
            document.getElementById('imageUpload').addEventListener('change', (e) => {
                if (e.target.files && e.target.files.length > 0) {
                    processImageOCR(e.target.files[0]);
                }
            });
        }, 5000); // Reset after 5s
    }, 500);
}

/* ── Connection Status ──────────────────────────────────────── */
async function checkConnection() {
  const badge = document.getElementById('connectionBadge');
  const label = document.getElementById('connLabel');

  try {
    const res  = await fetch('/api/status');
    const data = await res.json();

    if (data.status === 'connected') {
      badge.className = 'connection-badge connected';
      label.textContent = data.client || 'Connected';
    } else {
      badge.className = 'connection-badge error';
      label.textContent = 'Not Connected';
    }
  } catch {
    badge.className = 'connection-badge error';
    label.textContent = 'Server Offline';
  }
}

/* ── Lot Sizes Autocomplete ─────────────────────────────────── */
async function loadLotSizes() {
  try {
    const res  = await fetch('/api/lot-sizes');
    const data = await res.json();
    const dl   = document.getElementById('lotSizeOptions');
    (data.lot_sizes || []).forEach(sz => {
      const opt = document.createElement('option');
      opt.value = sz;
      dl.appendChild(opt);
    });
  } catch { /* non-critical */ }
}

/* ── Segmented Controls ─────────────────────────────────────── */
function setupSegmentedControls() {
  // Option type
  document.getElementById('optionTypeCtrl').querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#optionTypeCtrl .seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.optionType = btn.dataset.value;
    });
  });

  // Expiry scope
  document.getElementById('expiryCtrl').querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#expiryCtrl .seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.expiryScope = btn.dataset.value;
    });
  });
}

/* ── Live Previous Close Preview ────────────────────────────── */
function setupPrevClosePreview() {
  const currentPriceEl = document.getElementById('currentPrice');
  const absChangeEl    = document.getElementById('absChange');
  const pctChangeEl    = document.getElementById('pctChange');
  const preview        = document.getElementById('prevClosePreview');
  const valueEl        = document.getElementById('prevCloseValue');

  function updatePreview() {
    const cp  = parseFloat(currentPriceEl.value);
    const abs = parseFloat(absChangeEl.value);
    const pct = parseFloat(pctChangeEl.value);

    if (isNaN(cp) || cp <= 0) { preview.style.display = 'none'; return; }

    let prevClose = null;
    if (!isNaN(abs)) {
      prevClose = cp - abs;
    } else if (!isNaN(pct)) {
      prevClose = cp / (1 + pct / 100);
    }

    if (prevClose !== null && prevClose > 0) {
      preview.style.display = 'flex';
      valueEl.textContent   = `₹${prevClose.toFixed(2)}`;
    } else {
      preview.style.display = 'none';
    }
  }

  [currentPriceEl, absChangeEl, pctChangeEl].forEach(el =>
    el.addEventListener('input', updatePreview)
  );

  // Mutual exclusion hint: highlight whichever was last typed
  absChangeEl.addEventListener('input', () => { if (absChangeEl.value) pctChangeEl.style.opacity = '0.5'; else pctChangeEl.style.opacity = '1'; });
  pctChangeEl.addEventListener('input', () => { if (pctChangeEl.value) absChangeEl.style.opacity = '0.5'; else absChangeEl.style.opacity = '1'; });
}

/* ── Range Slider ────────────────────────────────────────────── */
function setupRangeSlider() {
  const slider  = document.getElementById('tolerance');
  const hint    = document.getElementById('toleranceHint');

  function update() {
    hint.textContent = slider.value + '%';
    const pct = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
    slider.style.background = `linear-gradient(to right, var(--accent) 0%, var(--accent) ${pct}%, var(--border) ${pct}%)`;
  }

  slider.addEventListener('input', update);
  update();
}

/* ── Fill Example (from screenshot) ─────────────────────────── */
function fillExample() {
  document.getElementById('currentPrice').value = '5.39';
  document.getElementById('absChange').value    = '-1.03';
  document.getElementById('pctChange').value    = '';
  document.getElementById('lotSize').value      = '';

  // Trigger preview update
  document.getElementById('currentPrice').dispatchEvent(new Event('input'));
  document.getElementById('absChange').dispatchEvent(new Event('input'));

  // Flash the fields
  ['currentPrice', 'absChange'].forEach(id => {
    const el = document.getElementById(id);
    el.style.borderColor = 'var(--accent)';
    setTimeout(() => el.style.borderColor = '', 800);
  });
}

/* ── Decode ──────────────────────────────────────────────────── */
async function runDecode() {
  // Gather inputs
  const currentPrice = parseFloat(document.getElementById('currentPrice').value);
  const absChange    = document.getElementById('absChange').value !== ''
    ? parseFloat(document.getElementById('absChange').value) : null;
  const pctChange    = document.getElementById('pctChange').value !== ''
    ? parseFloat(document.getElementById('pctChange').value) : null;
  const lotSize      = parseInt(document.getElementById('lotSize').value);
  const tolerance    = parseInt(document.getElementById('tolerance').value);

  // Validate
  if (isNaN(currentPrice) || currentPrice <= 0) {
    flashError('currentPrice', 'Enter a valid current price');
    return;
  }
  if (absChange === null && pctChange === null) {
    flashError('absChange', 'Enter change amount or %');
    return;
  }
  if (isNaN(lotSize)) {
     lotSize = 0; // Means Index Option
  }

  // Show loading
  setUIState('loading');
  document.getElementById('loadingSub').textContent = `Scanning NFO options with lot size ${lotSize}…`;
  setDecodeBtn(true);

  const startTime = Date.now();

  try {
    const payload = {
      current_price: currentPrice,
      lot_size:      lotSize,
      option_type:   state.optionType,
      expiry_scope:  state.expiryScope,
      tolerance_pct: tolerance,
    };
    if (absChange !== null) payload.abs_change = absChange;
    if (pctChange !== null) payload.pct_change = pctChange;

    const res  = await fetch('/api/decode', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    const data = await res.json();
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

    if (!res.ok || data.error) {
      showError(data.error || 'Decode failed');
      return;
    }

    renderResults(data, elapsed, currentPrice);
    setUIState('results');

  } catch (err) {
    showError(`Network error: ${err.message}`);
  } finally {
    setDecodeBtn(false);
  }
}

/* ── Render Results ──────────────────────────────────────────── */
function renderResults(data, elapsed, currentPrice) {
  // Summary bar
  document.getElementById('resultsSummary').innerHTML = `
    <div class="summary-item">
      <span class="summary-label">Calc. Prev Close</span>
      <span class="summary-value gold">₹${data.calc_prev_close}</span>
    </div>
    <div class="summary-item">
      <span class="summary-label">Tokens Scanned</span>
      <span class="summary-value">${data.tokens_searched?.toLocaleString() ?? '—'}</span>
    </div>
    <div class="summary-item">
      <span class="summary-label">Matches Found</span>
      <span class="summary-value ${data.total_matches > 0 ? 'green' : ''}">${data.total_matches}</span>
    </div>
    <div class="summary-item">
      <span class="summary-label">Time Taken</span>
      <span class="summary-value">${elapsed}s</span>
    </div>
    <div class="summary-item">
      <span class="summary-label">Lot Size</span>
      <span class="summary-value">${data.lot_size}</span>
    </div>
  `;

  // Matches list
  const list = document.getElementById('matchesList');

  if (!data.matches || data.matches.length === 0) {
    list.innerHTML = `
      <div class="no-results">
        <h3>No matches found</h3>
        <p>Try increasing the tolerance slider or changing the expiry scope.<br/>
        Make sure lot size is correct (e.g. Nifty=75, BankNifty=15).</p>
      </div>`;
    return;
  }

  list.innerHTML = data.matches.map((m, i) => buildMatchCard(m, i, currentPrice)).join('');
}

function buildMatchCard(m, idx, currentPrice) {
  const q     = m.match_quality;
  const qLow  = q.toLowerCase();

  // Match bar width: 100% = exact, 0% = worst (> tolerance)
  const barWidth = Math.max(0, 100 - m.match_pct * 5);

  const typeBadge   = m.opt_type === 'CE'
    ? '<span class="badge badge-ce">CE</span>'
    : '<span class="badge badge-pe">PE</span>';
  const qualBadge   = `<span class="badge badge-${qLow}">${q}</span>`;
  const instrBadge  = m.instrumenttype === 'OPTIDX'
    ? '<span class="badge badge-idx">INDEX</span>'
    : '<span class="badge badge-stk">STOCK</span>';

  const ltpClass   = m.ltp > m.opt_prev_close ? 'green' : (m.ltp < m.opt_prev_close ? 'red' : 'dim');

  return `
    <div class="match-card quality-${q}" style="animation-delay:${idx * 0.06}s">
      <div class="card-header">
        <div class="card-symbol">
          <span class="card-underlying">${m.underlying}</span>
          <span class="card-symbol-full">${m.symbol}</span>
        </div>
        <div class="card-badges">
          ${instrBadge}
          ${typeBadge}
          ${qualBadge}
        </div>
      </div>

      <div class="match-bar-wrap">
        <div class="match-bar-bg">
          <div class="match-bar-fill quality-${q}" style="width:${barWidth}%"></div>
        </div>
        <span class="match-pct-label">${m.match_pct}% off</span>
      </div>

      <div class="card-stats">
        <div class="stat-item">
          <span class="stat-label">Strike Price</span>
          <span class="stat-value gold">₹${formatNum(m.strike)}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Expiry</span>
          <span class="stat-value">${m.expiry}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Option Prev Close</span>
          <span class="stat-value">₹${m.opt_prev_close}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Your Calc Close</span>
          <span class="stat-value gold">₹${m.calc_prev_close}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Current LTP</span>
          <span class="stat-value ${ltpClass}">₹${m.ltp}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Today Open</span>
          <span class="stat-value dim">₹${m.open}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">High / Low</span>
          <span class="stat-value dim">₹${m.high} / ₹${m.low}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Lot Size</span>
          <span class="stat-value dim">${m.lot_size}</span>
        </div>
      </div>
      
      <!-- Tracker Form -->
      <div class="save-form">
          <div class="save-row">
              <input type="number" id="tg_${idx}" class="save-input" placeholder="Target (e.g. ${Math.round(m.ltp * 1.5)})">
              <input type="number" id="sl_${idx}" class="save-input" placeholder="Stop Loss (e.g. ${Math.round(m.ltp * 0.7)})">
              <select id="mode_${idx}" class="save-input" style="flex:0.5; display:none;">
                  <option value="OBSERVER">Paper Trade</option>
                  <option value="TRADED">Real Trade</option>
              </select>
          </div>
          <div class="save-row">
              <input type="text" id="notes_${idx}" class="save-input" placeholder="Notes (optional)...">
              <button class="save-btn" onclick='saveTip(${JSON.stringify(m).replace(/'/g, "&#39;")}, ${currentPrice}, ${idx}, "OBSERVER")'>Paper Trade (Save)</button>
              <button class="primary-btn" style="padding: 10px 16px; font-size: 13px;" onclick='openOrderModal(${JSON.stringify(m).replace(/'/g, "&#39;")}, ${currentPrice})'>⚡ Execute Trade</button>
          </div>
      </div>
      
    </div>
  `;
}

/* ── Save Tip ────────────────────────────────────────────────── */
async function saveTip(match, entryPrice, idx, forceMode=null) {
    const tg = document.getElementById(`tg_${idx}`)?.value;
    const sl = document.getElementById(`sl_${idx}`)?.value;
    const mode = forceMode || (document.getElementById(`mode_${idx}`)?.value || 'OBSERVER');
    const notes = document.getElementById(`notes_${idx}`)?.value;
    const btn = event.target;
    
    btn.disabled = true;
    btn.textContent = 'Saving...';
    
    try {
        const payload = {
            symbol: match.symbol,
            token: match.token,
            underlying: match.underlying,
            strike: match.strike,
            expiry: match.expiry,
            opt_type: match.opt_type,
            lot_size: match.lot_size,
            instrument_type: match.instrumenttype,
            entry_price: entryPrice,
            entry_ltp: match.ltp,
            target_price: tg ? parseFloat(tg) : null,
            stop_loss: sl ? parseFloat(sl) : null,
            mode: mode,
            notes: notes
        };
        
        const res = await fetch('/api/tips', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        if(res.ok) {
            btn.textContent = 'Saved!';
            btn.style.background = 'var(--text-3)';
        } else {
            btn.textContent = 'Error';
            btn.disabled = false;
        }
    } catch(err) {
        btn.textContent = 'Error';
        btn.disabled = false;
    }
}

/* ── UI Helpers ──────────────────────────────────────────────── */
function setUIState(state) {
  document.getElementById('idleState').style.display    = state === 'idle'    ? 'flex' : 'none';
  document.getElementById('loadingState').style.display = state === 'loading' ? 'flex' : 'none';
  document.getElementById('resultsContent').style.display = state === 'results' ? 'block' : 'none';
  document.getElementById('errorState').style.display   = state === 'error'   ? 'flex' : 'none';
}

function showError(msg) {
  setUIState('error');
  document.getElementById('errorText').textContent = msg;
}

function setDecodeBtn(loading) {
  const btn  = document.getElementById('decodeBtn');
  const icon = document.getElementById('decodeBtnIcon');
  const text = document.getElementById('decodeBtnText');
  btn.disabled    = loading;
  icon.textContent = loading ? '⏳' : '⚡';
  text.textContent = loading ? 'Scanning…' : 'Decode Now';
}

function flashError(fieldId, msg) {
  const el = document.getElementById(fieldId);
  el.style.borderColor = 'var(--red)';
  el.style.boxShadow   = '0 0 0 3px rgba(239,68,68,0.2)';
  el.focus();
  setTimeout(() => {
    el.style.borderColor = '';
    el.style.boxShadow   = '';
  }, 1500);
}

function formatNum(n) {
  return n % 1 === 0 ? n.toLocaleString('en-IN') : n.toLocaleString('en-IN', { minimumFractionDigits: 2 });
}

function clearFields() {
  // Clear inputs
  document.getElementById('currentPrice').value = '';
  document.getElementById('absChange').value = '';
  document.getElementById('pctChange').value = '';
  document.getElementById('lotSize').value = '';
  
  // Trigger preview update
  document.getElementById('currentPrice').dispatchEvent(new Event('input'));
  document.getElementById('absChange').dispatchEvent(new Event('input'));
  
  // Reset paste zone
  const pasteZone = document.getElementById('pasteZone');
  pasteZone.innerHTML = '<div class="paste-icon">🖼️</div><p><strong>Tap/Click here to Upload or Paste (Ctrl+V)</strong></p><p class="paste-sub">Price and Change will auto-fill via OCR</p><input type="file" id="imageUpload" accept="image/*" style="display: none;" />';
  document.getElementById('imageUpload').addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
          processImageOCR(e.target.files[0]);
      }
  });
  
  // Clear results
  setUIState('idle');
}

/* ── Order Modal Logic ───────────────────────────────────────── */
window.openOrderModal = function(match, entryPrice) {
    document.getElementById('orderModal').classList.add('show');
    document.getElementById('orderSymbol').textContent = `${match.underlying} ${match.expiry} ${match.strike} ${match.opt_type}`;
    
    // Fill hidden fields
    document.getElementById('orderToken').value = match.token;
    document.getElementById('orderExchange').value = 'NFO'; // Assuming NFO for options
    document.getElementById('orderUnderlying').value = match.underlying;
    document.getElementById('orderStrike').value = match.strike;
    document.getElementById('orderExpiry').value = match.expiry;
    document.getElementById('orderOptType').value = match.opt_type;
    document.getElementById('orderInstrumentType').value = match.instrumenttype;
    document.getElementById('orderEntryPrice').value = entryPrice;
    document.getElementById('orderEntryLtp').value = match.ltp;
    
    // Fill Lot Size
    document.getElementById('orderLotSize').value = match.lot_size;
    document.getElementById('orderQtyHint').textContent = `Qty: ${match.lot_size}`;
    document.getElementById('orderLots').value = 1;
    
    // Reset inputs
    document.getElementById('orderType').value = 'MARKET';
    document.getElementById('orderProduct').value = 'CARRYFORWARD';
    document.getElementById('orderPrice').value = match.ltp;
    document.getElementById('orderTarget').value = '';
    document.getElementById('orderSL').value = '';
    document.getElementById('orderError').style.display = 'none';
    
    toggleOrderPrice();
    
    // Add event listener to update qty hint dynamically
    document.getElementById('orderLots').addEventListener('input', function() {
        const lots = parseInt(this.value) || 0;
        const ls = parseInt(document.getElementById('orderLotSize').value) || 0;
        document.getElementById('orderQtyHint').textContent = `Qty: ${lots * ls}`;
    });
};

window.closeOrderModal = function() {
    document.getElementById('orderModal').classList.remove('show');
};

window.toggleOrderPrice = function() {
    const type = document.getElementById('orderType').value;
    document.getElementById('orderPriceGroup').style.display = type === 'LIMIT' ? 'block' : 'none';
};

window.submitOrder = async function() {
    const btn = document.getElementById('submitOrderBtn');
    const err = document.getElementById('orderError');
    err.style.display = 'none';
    
    btn.disabled = true;
    btn.textContent = 'Submitting...';
    
    try {
        const payload = {
            symbol: document.getElementById('orderSymbol').textContent.trim(),
            token: document.getElementById('orderToken').value,
            transaction_type: 'BUY',
            exchange: document.getElementById('orderExchange').value,
            order_type: document.getElementById('orderType').value,
            product_type: document.getElementById('orderProduct').value,
            lots: parseInt(document.getElementById('orderLots').value),
            lot_size: parseInt(document.getElementById('orderLotSize').value),
            price: document.getElementById('orderPrice').value
        };
        
        // 1. Place the order
        const orderRes = await fetch('/api/order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        const orderData = await orderRes.json();
        if(!orderRes.ok || orderData.error) {
            throw new Error(orderData.error || 'Failed to place order');
        }
        
        // 2. Save to Tracker automatically!
        const tg = document.getElementById('orderTarget').value;
        const sl = document.getElementById('orderSL').value;
        
        const tipPayload = {
            symbol: payload.symbol,
            underlying: document.getElementById('orderUnderlying').value,
            strike: document.getElementById('orderStrike').value,
            expiry: document.getElementById('orderExpiry').value,
            opt_type: document.getElementById('orderOptType').value,
            lot_size: payload.lot_size,
            instrument_type: document.getElementById('orderInstrumentType').value,
            entry_price: document.getElementById('orderEntryPrice').value,
            entry_ltp: document.getElementById('orderEntryLtp').value,
            target_price: tg ? parseFloat(tg) : null,
            stop_loss: sl ? parseFloat(sl) : null,
            mode: 'TRADED', // It's a real trade!
            notes: `Auto-Executed. Order ID: ${orderData.order_id}`
        };
        
        await fetch('/api/tips', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(tipPayload)
        });
        
        btn.textContent = 'Order Placed! ✅';
        btn.style.background = 'var(--green)';
        
        setTimeout(() => {
            closeOrderModal();
            btn.disabled = false;
            btn.textContent = 'Submit BUY Order';
            btn.style.background = 'var(--accent)';
        }, 2000);
        
    } catch(e) {
        err.textContent = e.message;
        err.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Submit BUY Order';
    }
};

/* ── Enter key shortcut ──────────────────────────────────────── */
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
      if(document.getElementById('orderModal').classList.contains('show')) {
          submitOrder();
      } else {
          runDecode();
      }
  }
});
