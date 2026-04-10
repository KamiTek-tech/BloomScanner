// ==================== GLOBAL VARIABLES ====================
const socket = io();
let chart, speedData = [], speedLabels = [];

// ==================== CHART INITIALIZATION ====================
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

// ==================== UI HELPERS ====================
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

// ==================== SCANNER CONTROLS ====================
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

// ==================== SOCKET LISTENERS ====================
socket.on('connect', () => {
    document.getElementById('conn-status-text').textContent = 'Connected';
    // 🔥 Убираем класс disconnected → переход к зелёному
    document.querySelector('.gradient-badge-container').classList.remove('status-disconnected');
});

socket.on('disconnect', () => {
    document.getElementById('conn-status-text').textContent = 'Disconnected';
    // 🔥 Добавляем класс disconnected → переход к красному
    document.querySelector('.gradient-badge-container').classList.add('status-disconnected');
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
    
    if (chart) chart.update('none');
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
    div.innerHTML = `<div class="d-flex justify-content-between align-items-center"><div><code>${h.address}</code><br><small class="text-muted">${h.btc} BTC</small></div><span class="badge bg-danger">${h.btc} BTC</span></div>`;
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

// ==================== RECOVERY LOGIC ====================
function startRecovery(mode) {
    const resultsDiv = document.getElementById('rec-results');
    resultsDiv.innerHTML = '<div class="text-warning">🔄 Scanning...</div>';
    document.getElementById('rec-status').textContent = '🔄 Working...';
    document.getElementById('rec-progress').style.width = '0%';
    
    let config = { 
        mode,
        telegram: { 
            enabled: document.getElementById('tg-enabled').checked, 
            token: document.getElementById('tg-token').value.trim(), 
            chat_id: document.getElementById('tg-chat').value.trim() 
        }
    };
    
    if (mode === 'missing') {
        const input = document.getElementById('rec-missing-phrase').value.trim().split(/\s+/);
        config.words = input.join(' ');
        config.missing_indices = input.map((w, i) => w === '?' ? i : -1).filter(i => i !== -1);
        if (config.missing_indices.length === 0 || config.missing_indices.length > 2) { 
            alert('Error: Mark 1 or 2 words with ?'); return; 
        }
    } else if (mode === 'shuffled') {
        config.words = document.getElementById('rec-shuffled-phrase').value.trim();
        if (config.words.split(/\s+/).length > 9) { 
            alert('Error: Max 9 words for shuffled mode!'); return; 
        }
    } else if (mode === 'typo') {
        config.words = document.getElementById('rec-typo-phrase').value.trim();
    }
    
    socket.emit('start_recovery', config);
}

socket.on('recovery_progress', d => {
    document.getElementById('rec-status').textContent = `🔄 ${d.percent.toFixed(2)}%`;
    document.getElementById('rec-count').textContent = `${d.current.toLocaleString()} / ${d.total.toLocaleString()}`;
    document.getElementById('rec-progress').style.width = `${d.percent}%`;
});

socket.on('recovery_found', h => {
    const div = document.createElement('div');
    const balClass = h.balance > 0 ? 'alert-danger' : 'alert-success';
    const balIcon = h.balance > 0 ? '💰' : '🟢';
    div.className = `alert ${balClass} py-2 mb-2 fade show`;
    div.innerHTML = `<strong>${balIcon} FOUND!</strong><br><code>${h.phrase}</code><br><small>Addr: ${h.address} | Bal: ${h.balance} BTC</small>`;
    document.getElementById('rec-results').prepend(div);
});

socket.on('recovery_complete', () => {
    document.getElementById('rec-status').textContent = '✅ Done';
    document.getElementById('rec-progress').style.width = '100%';
    document.getElementById('rec-progress').classList.remove('progress-bar-animated');
});

// ==================== INIT ====================
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChart);
} else {
    initChart();
}