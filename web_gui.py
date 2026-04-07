#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC Bloom Scanner — Web GUI Backend
✅ Simple & Stable (CPU only)
✅ API Active Flag Fix
"""
import sys
import os
import time
import threading
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'btc_scanner_secret_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==================== GLOBAL STATE ====================
scanner_state = {
    'running': False, 'paused': False,
    'total_generated': 0, 'total_hits': 0,
    'api_checked': 0, 'speed': 0.0,
    'start_time': None,
    'api_active': False  # 🔥 NEW FLAG
}

scanner_thread = None
stats_thread = None
stop_event = threading.Event()
pause_event = threading.Event()

# ==================== ROUTES ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    return jsonify(scanner_state)

# ==================== SOCKET EVENTS ====================
@socketio.on('connect')
def on_connect():
    print("🔗 Client connected")
    socketio.emit('initial_state', scanner_state)
    socketio.emit('log_message', {'msg': '🔗 Client connected'})

@socketio.on('disconnect')
def on_disconnect():
    print("🔌 Client disconnected")

@socketio.on('start_scanning')
def on_start(config):
    global scanner_thread, stats_thread
    if scanner_state['running']:
        socketio.emit('error', {'message': 'Already running'}); return
    
    stop_event.clear(); pause_event.clear()
    scanner_state.update({
        'running': True, 'paused': False,
        'total_generated': 0, 'total_hits': 0,
        'api_checked': 0, 'start_time': time.time(),
        'api_active': config.get('api', True)  # 🔥 SET API ACTIVE
    })
    socketio.emit('state_changed', scanner_state)
    
    # Telegram config
    tg = config.get('telegram', {})
    os.environ['TG_ENABLED'] = '1' if tg.get('enabled') else '0'
    os.environ['TG_TOKEN'] = tg.get('token', '')
    os.environ['TG_CHAT_ID'] = tg.get('chat_id', '')
    
    socketio.emit('log_message', {'msg': f"🚀 Starting: {config.get('total',0):,} addresses | API: ON"})
    
    scanner_thread = threading.Thread(target=_run_scanner, args=(config,), daemon=True)
    scanner_thread.start()
    stats_thread = threading.Thread(target=_stats_loop, daemon=True)
    stats_thread.start()

@socketio.on('pause_scanning')
def on_pause():
    scanner_state['paused'] = not scanner_state['paused']
    if scanner_state['paused']: pause_event.set()
    else: pause_event.clear()
    socketio.emit('state_changed', scanner_state)
    socketio.emit('log_message', {'msg': f"⏸️ {'Paused' if scanner_state['paused'] else 'Resumed'}"})

@socketio.on('stop_scanning')
def on_stop():
    print("🛑 Stop requested")
    stop_event.set(); pause_event.clear()
    scanner_state['running'] = False; scanner_state['paused'] = False
    socketio.emit('state_changed', scanner_state)
    socketio.emit('log_message', {'msg': '🛑 Stopped by user'})
    time.sleep(0.5)
    if scanner_thread and scanner_thread.is_alive():
        scanner_thread.join(timeout=2)

# ==================== BACKEND LOGIC ====================
def _run_scanner(config):
    try:
        from scanner import Scanner
        use_api = config.get('api', True)
        threads = config.get('threads', 4)
        total = config.get('total', 10000)
        method = config.get('method', 'pubkey_hash160')
        
        # 🔥 SET API ACTIVE FLAG
        scanner_state['api_active'] = use_api
        
        print(f"\n{'='*60}\n🔍 SCANNER CONFIG:\n  • Method: {method}\n  • Threads: {threads}\n  • Total: {total:,}\n  • API: {'ON' if use_api else 'OFF'}\n{'='*60}\n")
        
        scanner = Scanner(method=method, use_api=use_api, threads=threads)
        scanner.socketio = socketio
        scanner.run_with_gui(socketio=socketio, total=total, threads=threads, method=method, use_api=use_api, stop_event=stop_event, pause_event=pause_event, state=scanner_state)
        
    except Exception as e:
        import traceback; print(traceback.format_exc())
        socketio.emit('error', {'message': str(e)})
        socketio.emit('log_message', {'msg': f'❌ Error: {e}'})
    finally:
        scanner_state['running'] = False
        # 🔥 Don't turn off api_active here - it will turn off when API worker finishes
        socketio.emit('state_changed', scanner_state)
        print("✅ Scanner thread finished")

def _stats_loop():
    """Update statistics every second"""
    last_count, last_time = 0, time.time()
    
    # 🔥 CONTINUE WHILE GENERATION OR API CHECKING
    while scanner_state['running'] or scanner_state['paused'] or scanner_state.get('api_active', False):
        time.sleep(1)
        
        if scanner_state['paused']:
            continue
        
        now = time.time()
        dt = now - last_time
        dc = scanner_state['total_generated'] - last_count
        if dt > 0: scanner_state['speed'] = dc / dt
        
        last_count, last_time = scanner_state['total_generated'], now
        
        socketio.emit('stats_update', {
            'generated': scanner_state['total_generated'],
            'hits': scanner_state['total_hits'],
            'speed': scanner_state['speed'],
            'api_checked': scanner_state['api_checked'],
            'running': scanner_state['running'],
            'paused': scanner_state['paused'],
            'api_active': scanner_state.get('api_active', False)
        })

if __name__ == '__main__':
    print("\n🔐 BTC Bloom Scanner GUI\n🌐 http://localhost:5000\n")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)