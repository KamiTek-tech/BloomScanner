#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC Bloom Scanner Pro — Web GUI Backend
✅ Cascade Bloom, Recovery, API Active Flag, Telegram Sync
✅ GUI Continues Updating After Generation
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

scanner_state = {
    'running': False, 'paused': False,
    'total_generated': 0, 'total_hits': 0,
    'api_checked': 0, 'speed': 0.0,
    'start_time': None, 'api_active': False
}

scanner_thread = None
stats_thread = None
stop_event = threading.Event()
pause_event = threading.Event()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    return jsonify(scanner_state)

@socketio.on('connect')
def on_connect():
    socketio.emit('initial_state', scanner_state)

@socketio.on('start_scanning')
def on_start(config):
    global scanner_thread, stats_thread
    if scanner_state['running']: return
    stop_event.clear(); pause_event.clear()
    scanner_state.update({
        'running': True, 'paused': False,
        'total_generated': 0, 'total_hits': 0,
        'api_checked': 0, 'start_time': time.time(),
        'api_active': config.get('api', True)  # 🔥 Включаем флаг API
    })
    tg = config.get('telegram', {})
    os.environ['TG_ENABLED'] = '1' if tg.get('enabled') else '0'
    os.environ['TG_TOKEN'] = tg.get('token', '')
    os.environ['TG_CHAT_ID'] = tg.get('chat_id', '')
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

@socketio.on('stop_scanning')
def on_stop():
    stop_event.set(); pause_event.clear()
    scanner_state['running'] = False
    scanner_state['api_active'] = False  # 🔥 Выключаем флаг API при остановке
    socketio.emit('state_changed', scanner_state)
    time.sleep(0.5)
    if scanner_thread and scanner_thread.is_alive(): scanner_thread.join(timeout=2)

def _run_scanner(config):
    try:
        from scanner import Scanner
        use_api = config.get('api', True)
        threads = config.get('threads', 4)
        total = config.get('total', 10000)
        method = config.get('method', 'pubkey_hash160')
        scanner = Scanner(method=method, use_api=use_api, threads=threads)
        scanner.socketio = socketio
        scanner.run_with_gui(socketio=socketio, total=total, threads=threads, method=method, use_api=use_api, stop_event=stop_event, pause_event=pause_event, state=scanner_state)
    except Exception as e:
        print(f"Scanner Error: {e}")
    finally:
        scanner_state['running'] = False
        # 🔥 НЕ выключаем api_active здесь! Он выключится когда API-воркер закончит
        socketio.emit('state_changed', scanner_state)

def _stats_loop():
    """Update statistics every second - continues while API is active"""
    last_count, last_time = 0, time.time()
    
    # 🔥 Продолжаем работу пока идет генерация ИЛИ API проверка
    while scanner_state['running'] or scanner_state['paused'] or scanner_state.get('api_active', False):
        time.sleep(1)
        if scanner_state['paused']: continue
        
        now = time.time()
        dt = now - last_time
        dc = scanner_state['total_generated'] - last_count
        if dt > 0: scanner_state['speed'] = dc / dt
        
        last_count, last_time = scanner_state['total_generated'], now
        
        # 🔥 Отправляем обновление в GUI
        socketio.emit('stats_update', {
            'generated': scanner_state['total_generated'],
            'hits': scanner_state['total_hits'],
            'speed': scanner_state['speed'],
            'api_checked': scanner_state['api_checked'],
            'running': scanner_state['running'],
            'paused': scanner_state['paused'],
            'api_active': scanner_state.get('api_active', False)
        })
        
        # 🔥 Если генерация завершена и API-очередь пуста - выключаем флаг
        if not scanner_state['running'] and scanner_state.get('api_active', False):
            # Проверяем, пустая ли очередь API (через scanner)
            # Это делается в scanner.py, здесь просто ждем сигнала
            pass

# ==================== RECOVERY ====================
@socketio.on('start_recovery')
def on_start_recovery(config):
    try:
        from mnemonic_recovery import load_bloom_filter, recover_missing, recover_shuffled, recover_typo
        bloom_data, bloom_bits = load_bloom_filter()
        tg = config.get('telegram', {})
        os.environ['TG_ENABLED'] = '1' if tg.get('enabled') else '0'
        os.environ['TG_TOKEN'] = tg.get('token', '')
        os.environ['TG_CHAT_ID'] = tg.get('chat_id', '')
        stop_flag = threading.Event()
        def emit_progress(current, total):
            percent = (current / total * 100) if total > 0 else 0
            socketio.emit('recovery_progress', {'current': current, 'total': total, 'percent': round(percent, 2)})
        def emit_hit(phrase, address, balance):
            socketio.emit('recovery_found', {'phrase': phrase, 'address': address, 'balance': balance, 'time': time.strftime('%H:%M:%S')})
        socketio.emit('log_message', {'msg': f"🔍 Recovery started: {config.get('mode')}"})
        mode = config.get('mode')
        if mode == 'missing':
            words = config.get('words', '').split()
            missing_idx = config.get('missing_indices', [])
            partial = [w if w != '?' else None for w in words]
            recover_missing(partial, missing_idx, bloom_data, bloom_bits, emit_progress, emit_hit, stop_flag)
        elif mode == 'shuffled':
            words = config.get('words', '').split()
            recover_shuffled(words, bloom_data, bloom_bits, emit_progress, emit_hit, stop_flag)
        elif mode == 'typo':
            words = config.get('words', '').split()
            recover_typo(words, bloom_data, bloom_bits, emit_progress, emit_hit, stop_flag)
        socketio.emit('log_message', {'msg': "✅ Recovery completed"})
        socketio.emit('recovery_complete', {})
    except Exception as e:
        socketio.emit('log_message', {'msg': f"❌ Recovery Error: {e}"})
        socketio.emit('recovery_complete', {})

if __name__ == '__main__':
    print("🔐 BTC Bloom Scanner Pro\n🌐 http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)