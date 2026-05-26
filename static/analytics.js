// Analytics Dashboard Logic

window.loadAnalytics = async function() {
    try {
        const res = await fetch('/api/analytics');
        const data = await res.json();
        
        if (data.error) {
            console.error("Analytics Error:", data.error);
            return;
        }
        
        // Update Stats
        const formatPl = (val) => val > 0 ? `+₹${val}` : (val < 0 ? `-₹${Math.abs(val)}` : `₹0`);
        const setStat = (id, val, isPl=false) => {
            const el = document.getElementById(id);
            if(el) {
                el.textContent = isPl ? formatPl(val) : val;
                if(isPl) {
                    el.className = 'stat-card-value ' + (val > 0 ? 'green' : (val < 0 ? 'red' : ''));
                }
            }
        };
        
        setStat('statRealPL', data.realized_pl, true);
        const realTotal = data.real_wins + data.real_losses;
        const realWinRate = realTotal > 0 ? Math.round((data.real_wins / realTotal) * 100) + '%' : '-';
        setStat('statRealWinRate', realWinRate);
        
        setStat('statPaperPL', data.paper_pl, true);
        const paperTotal = data.paper_wins + data.paper_losses;
        const paperWinRate = paperTotal > 0 ? Math.round((data.paper_wins / paperTotal) * 100) + '%' : '-';
        setStat('statPaperWinRate', paperWinRate);
        
        // Render Chart
        renderChart(data.daily_pl);
        
    } catch(err) {
        console.error("Failed to load analytics:", err);
    }
};

let plChartInstance = null;

function renderChart(dailyPl) {
    const ctx = document.getElementById('plChart');
    if(!ctx) return;
    
    // Destroy previous instance if exists
    if(plChartInstance) {
        plChartInstance.destroy();
    }
    
    // Sort dates
    const dates = Object.keys(dailyPl).sort();
    
    const realData = dates.map(d => dailyPl[d].real);
    const paperData = dates.map(d => dailyPl[d].paper);
    
    // Create cumulative data if preferred, but daily is usually better for bars
    
    plChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'Realized P&L',
                    data: realData,
                    backgroundColor: 'rgba(16, 185, 129, 0.6)', // Green
                    borderColor: 'rgba(16, 185, 129, 1)',
                    borderWidth: 1
                },
                {
                    label: 'Paper P&L',
                    data: paperData,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)', // Blue
                    borderColor: 'rgba(59, 130, 246, 1)',
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#ffffff'
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                x: {
                    stacked: true,
                    ticks: { color: '#a1a1aa' },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                },
                y: {
                    stacked: true,
                    ticks: { color: '#a1a1aa' },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                }
            }
        }
    });
}
