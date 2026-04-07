const socket = io();
let chart, speedData = [], speedLabels = [];

function initChart() {
    const ctx = document.getElementById('chart').getContext('2d');
    chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: speedLabels,
            datasets: [{
                label: 'Addr/sec',
                data: speedData,
                borderColor: '#2ea043',
                backgroundColor: 'rgba(46,160,67,0.1)',
                tension: 0.3,
                fill: true,
                pointRadius: 0,
                pointHitRadius: 10,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: '#21262d' },
                    ticks: { color: '#8b949e' }
                },
                x: {
                    grid: { color: '#21262d' },
                    ticks: { color: '#8b949e', maxTicksLimit: 8, maxRotation: 45, minRotation: 45 }
                }
            }
        }
    });
}

function updateUI(state) {
    document.getElementById('s-gen').textContent = (state.total_generated || 0).toLocaleString();
    document.getElementById('s-hits').textContent = (state.total_hits || 0).toLocaleString();
    document.getElementById('s-speed').textContent = (state.speed || 0).toFixed(1);
    document.getElementById('s-api').textContent = (state.api_checked || 0).toLocaleString();
    
    if (state.running) {
        if (state.paused) setButtons('paused');
        else setButtons('running');
    } else {
        setButtons('stopped');
    }
}

function startScan() {
    const config = {
        method: document.getElementById('cfg-method').value,
        threads: parseInt(document.getElementById('cfg-threads').value),
        total: parseInt(document.getElementById('cfg-total').value),
        api: true,
        telegram: {
            enabled: document.getElementById('tg-enabled').checked,
            token: document.getElementById('tg-token').value.trim(),
            chat_id: document.getElementById('tg-chat').value.trim()
        }
    };
    socket.emit('start_scanning', config);
    setButtons('running');
}

function pauseScan() { socket.emit('pause_scanning'); }
function stopScan() { socket.emit('stop_scanning'); setButtons('stopped'); }

function setButtons(state) {
    const startBtn = document.getElementById('btn-start');
    const pauseBtn = document.getElementById('btn-pause');
    const stopBtn = document.getElementById('btn-stop');
    
    if (state === 'running') {
        startBtn.disabled = true; startBtn.classList.add('disabled');
        pauseBtn.disabled = false; pauseBtn.classList.remove('disabled');
        stopBtn.disabled = false; stopBtn.classList.remove('disabled');
        pauseBtn.innerHTML = '<i class="bi bi-pause-fill"></i>';
    } else if (state === 'paused') {
        startBtn.disabled = true; startBtn.classList.add('disabled');
        pauseBtn.disabled = false; pauseBtn.classList.remove('disabled');
        stopBtn.disabled = false; stopBtn.classList.remove('disabled');
        pauseBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
    } else {
        startBtn.disabled = false; startBtn.classList.remove('disabled');
        pauseBtn.disabled = true; pauseBtn.classList.add('disabled');
        stopBtn.disabled = true; stopBtn.classList.add('disabled');
        pauseBtn.innerHTML = '<i class="bi bi-pause-fill"></i>';
    }
}

socket.on('connect', () => {
    document.getElementById('conn-status').innerHTML = '<span class="badge bg-success">Connected</span>';
});
socket.on('disconnect', () => {
    document.getElementById('conn-status').innerHTML = '<span class="badge bg-danger">Disconnected</span>';
});

socket.on('initial_state', (state) => {
    console.log("🔄 Syncing UI:", state);
    updateUI(state);
});

socket.on('stats_update', d => {
    document.getElementById('s-gen').textContent = d.generated.toLocaleString();
    document.getElementById('s-hits').textContent = d.hits.toLocaleString();
    document.getElementById('s-speed').textContent = d.speed.toFixed(1);
    document.getElementById('s-api').textContent = (d.api_checked||0).toLocaleString();
    
    if (speedLabels.length > 30) { speedLabels.shift(); speedData.shift(); }
    speedLabels.push(new Date().toLocaleTimeString());
    speedData.push(d.speed);
    
    if (chart) { chart.update('none'); }
});

socket.on('new_hit', h => {
    const c = document.getElementById('hits-list');
    if (c.querySelector('.text-muted')) c.innerHTML = '';
    const div = document.createElement('div'); div.className = 'hit';
    div.innerHTML = `<div class="d-flex justify-content-between"><code class="text-truncate" style="max-width:250px">${h.address}</code><small class="text-muted">${h.time}</small></div>`;
    c.insertBefore(div, c.firstChild);
    while (c.children.length > 15) c.removeChild(c.lastChild);
});

socket.on('new_balance', h => {
    const c = document.getElementById('balance-list');
    if (c.querySelector('.text-muted')) c.innerHTML = '';
    const count = parseInt(document.getElementById('balance-count').textContent) + 1;
    document.getElementById('balance-count').textContent = count;
    const div = document.createElement('div'); div.className = 'hit found';
    div.innerHTML = `<div class="d-flex justify-content-between align-items-center">
        <div><code>${h.address}</code><br><small class="text-muted">${h.btc} BTC</small></div>
        <span class="badge bg-danger">${h.btc} BTC</span>
    </div>`;
    c.insertBefore(div, c.firstChild);
});

socket.on('log_message', m => {
    const c = document.getElementById('console');
    const line = document.createElement('div'); line.textContent = `[${new Date().toLocaleTimeString()}] ${m.msg}`;
    c.appendChild(line); c.scrollTop = c.scrollHeight;
    if (c.children.length > 100) c.removeChild(c.firstChild);
});

socket.on('scan_complete', d => {
    setButtons('stopped');
    socket.emit('log_message', { msg: `✅ Done: ${d.generated.toLocaleString()} gen, ${d.hits} hits` });
});

socket.on('error', e => { alert('❌ ' + e.message); setButtons('stopped'); });
socket.on('state_changed', s => { updateUI(s); });

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChart);
} else {
    initChart();
}