// Tips Tracker Dashboard Logic

window.loadDashboard = async function() {
    await fetchTips();
    // No automatic polling. Live prices synced manually via button.
};

let tipsData = [];
let liveInterval = null;

async function fetchTips() {
    try {
        const res = await fetch('/api/tips');
        const data = await res.json();
        
        const statRes = await fetch('/api/stats');
        const statData = await statRes.json();
        
        if(data.tips) {
            tipsData = data.tips;
            renderTrackerTable();
            updateAnalytics(statData.total_api_calls || 0);
        }
    } catch(err) {
        console.error("Failed to fetch tips:", err);
    }
}

function renderTrackerTable() {
    const tbody = document.getElementById('trackerTableBody');
    tbody.innerHTML = '';
    
    tipsData.forEach(tip => {
        const tr = document.createElement('tr');
        
        const date = new Date(tip.timestamp).toLocaleString('en-IN', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        let actions = '';
        if(tip.status === 'OPEN') {
            actions = `
                <button class="save-btn" style="padding: 4px 8px; font-size: 10px;" onclick="closeTip(${tip.id}, 'TARGET_HIT')">TG</button>
                <button class="save-btn" style="padding: 4px 8px; font-size: 10px; background: var(--red);" onclick="closeTip(${tip.id}, 'SL_HIT')">SL</button>
                <button class="save-btn" style="padding: 4px 8px; font-size: 10px; background: var(--text-3);" onclick="closeTip(${tip.id}, 'MANUAL_EXIT')">Exit</button>
                <button class="save-btn" style="padding: 4px 8px; font-size: 10px; background: transparent; border: 1px solid var(--red); color: var(--red);" onclick="deleteTip(${tip.id})" title="Delete">🗑️</button>
            `;
        } else {
            actions = `
                <button class="save-btn" style="padding: 4px 8px; font-size: 10px; background: transparent; border: 1px solid var(--red); color: var(--red);" onclick="deleteTip(${tip.id})" title="Delete">🗑️</button>
            `;
        }
        
        // Expected values
        const expProfStr = tip.expected_profit ? `<br><small class="gold">+₹${tip.expected_profit}</small>` : '';
        const expLossStr = tip.expected_loss ? `<br><small class="red">-₹${tip.expected_loss}</small>` : '';
        
        tr.innerHTML = `
            <td>${date}</td>
            <td><strong>${tip.underlying}</strong><br><small>${tip.strike} ${tip.opt_type}</small></td>
            <td>₹${tip.entry_price}</td>
            <td id="live_ltp_${tip.id}" class="live-ltp">₹${tip.entry_ltp}</td>
            <td>${tip.target_price ? '₹'+tip.target_price : '-'} ${expProfStr}</td>
            <td>${tip.stop_loss ? '₹'+tip.stop_loss : '-'} ${expLossStr}</td>
            <td><span class="status-badge status-${tip.status}">${tip.status}</span></td>
            <td>${tip.mode}</td>
            <td>${actions}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateAnalytics(totalApiCalls) {
    const total = tipsData.length;
    
    const closed = tipsData.filter(t => t.status !== 'OPEN');
    const wins = closed.filter(t => t.status === 'TARGET_HIT');
    
    let winRate = 0;
    if(closed.length > 0) {
        winRate = Math.round((wins.length / closed.length) * 100);
    }
    
    // Expected Profit of OPEN trades
    const open = tipsData.filter(t => t.status === 'OPEN');
    let totalExpProfit = 0;
    open.forEach(t => {
        if(t.expected_profit) totalExpProfit += t.expected_profit;
    });
    
    document.getElementById('dashTotalTips').textContent = total;
    document.getElementById('dashWinRate').textContent = closed.length > 0 ? `${winRate}%` : '-';
    document.getElementById('dashExpProfit').textContent = totalExpProfit > 0 ? `₹${totalExpProfit}` : '-';
    
    if(totalApiCalls !== undefined && document.getElementById('dashApiCalls')) {
        document.getElementById('dashApiCalls').textContent = totalApiCalls.toLocaleString();
    }
}

window.syncLivePrices = async function() {
    const btn = document.getElementById('syncPricesBtn');
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '🔄 Syncing...';
    }
    
    try {
        const hasOpen = tipsData.some(t => t.status === 'OPEN');
        if(!hasOpen) {
            if(btn) { btn.innerHTML = '🔄 Sync Live LTP'; btn.disabled = false; }
            return;
        }
        
        const res = await fetch('/api/tips/live');
        const data = await res.json();
        
        if(data.prices) {
            for(const [tipId, price] of Object.entries(data.prices)) {
                const el = document.getElementById(`live_ltp_${tipId}`);
                if(el) {
                    el.textContent = `₹${price}`;
                    el.style.color = 'var(--accent)';
                    setTimeout(() => el.style.color = '', 500);
                }
            }
        }
    } catch(err) {
        console.error("Live price update failed:", err);
    } finally {
        if(btn) {
            btn.innerHTML = '🔄 Sync Live LTP';
            btn.disabled = false;
        }
    }
};

window.closeTip = async function(id, newStatus) {
    try {
        const res = await fetch(`/api/tips/${id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ status: newStatus })
        });
        if(res.ok) {
            await fetchTips();
        }
    } catch(err) {
        alert("Failed to update tip status");
    }
};

window.deleteTip = async function(id) {
    if(!confirm("Are you sure you want to delete this tip?")) return;
    try {
        const res = await fetch(`/api/tips/${id}`, {
            method: 'DELETE'
        });
        if(res.ok) {
            await fetchTips();
        }
    } catch(err) {
        alert("Failed to delete tip");
    }
};
