#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIP39 BTC BLOOM SCANNER PRO
✅ Cascade Bloom Filter (Fast + Strict)
✅ API Worker with Safe Delay
✅ Auto-Export to found_wallets.txt
✅ Telegram Notifications
✅ Immediate Stop Support
✅ GUI Continues Updating After Generation
"""
import sys
import os
import time
import hashlib
import hmac
import logging
import ctypes
import threading
import queue
import random
import requests
import sqlite3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

try:
    from bit import PrivateKey
    from bit.format import bytes_to_wif
    from mnemonic import Mnemonic
except ImportError as e:
    print(f"\n❌ Missing: {e}\n💡 py -3.12 -m pip install bit mnemonic requests tqdm flask flask-socketio\n"); sys.exit(1)

mnemo = Mnemonic("english")

# ==================== CONFIG ====================
TELEGRAM_ENABLED = os.environ.get('TG_ENABLED', '0') == '1'
TELEGRAM_TOKEN = os.environ.get('TG_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TG_CHAT_ID', '')

# ==================== PATHS ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
RESULTS_DIR = os.path.join(BASE_DIR, "results")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
BLOOM_FAST_PATH = os.path.join(BASE_DIR, "addresses.bloom")
BLOOM_STRICT_PATH = os.path.join(BASE_DIR, "addresses_strict.bloom")
FOUND_FILE = os.path.join(RESULTS_DIR, "found_wallets.txt")
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOGS_DIR, "scanner.log"), encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger()

# ==================== HELPERS ====================
def save_hit_to_file(address, mnemonic, wif, h160, balance=0, mode="Scanner"):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {mode} | Addr: {address} | Bal: {balance} | H160: {h160}\n"
        if mnemonic: line += f"   Mnemonic: {mnemonic}\n   WIF: {wif}\n"
        line += "-" * 80 + "\n"
        with open(FOUND_FILE, 'a', encoding='utf-8') as f: f.write(line)
    except Exception as e: print(f"❌ Save error: {e}")

def send_telegram(msg):
    if not TELEGRAM_ENABLED or not TELEGRAM_TOKEN: return False
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except: return False

# ==================== CASCADE BLOOM ====================
class BloomFilter:
    def __init__(self, fast_path, strict_path=None):
        print(f"📂 Loading Fast Filter: {fast_path}")
        with open(fast_path, 'rb') as f: self.data_fast = bytearray(f.read())
        self.bits_fast = len(self.data_fast) * 8
        print(f"✅ Fast Filter: {self.bits_fast:,} bits")
        
        self.data_strict = None
        self.bits_strict = None
        if strict_path and os.path.exists(strict_path):
            print(f"📂 Loading Strict Filter: {strict_path}")
            with open(strict_path, 'rb') as f: self.data_strict = bytearray(f.read())
            self.bits_strict = len(self.data_strict) * 8
            print(f"✅ Strict Filter: {self.bits_strict:,} bits")
        else:
            print("ℹ️ Strict Filter not found. Using Fast only.")
    
    def check(self, h160):
        if not self._check_data(h160, self.data_fast, self.bits_fast): return False
        if self.data_strict: return self._check_data(h160, self.data_strict, self.bits_strict)
        return True

    def _check_data(self, h160, data, bits):
        for i in range(3):
            h = hashlib.sha256(h160 + i.to_bytes(4, 'big')).digest()
            h = hashlib.sha256(h).digest()
            pos = int.from_bytes(h[:8], 'little') % bits
            if not (data[pos//8] & (1 << (pos%8))): return False
        return True

# ==================== DATABASE ====================
class DB:
    def __init__(self, sid):
        self.path = os.path.join(RESULTS_DIR, f"scan_{sid}.db")
        self.lock = threading.Lock()
        with sqlite3.connect(self.path) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute('''CREATE TABLE IF NOT EXISTS hits (
                id INTEGER PRIMARY KEY, address TEXT UNIQUE, mnemonic TEXT, wif TEXT, 
                hash160 TEXT, hit_time TEXT, api_checked INT DEFAULT 0, balance_sat INT DEFAULT 0)''')
    def save(self, w):
        with self.lock:
            with sqlite3.connect(self.path) as c:
                c.execute('INSERT OR IGNORE INTO hits VALUES (NULL,?,?,?,?,?,0,0)',
                         (w['address'], w['mnemonic'], w['wif'], w['hash160'], w['time']))
    def update_api(self, addr, bal):
        with self.lock:
            with sqlite3.connect(self.path) as c:
                c.execute('UPDATE hits SET api_checked=1, balance_sat=? WHERE address=?', (bal, addr))

# ==================== SCANNER ====================
class Scanner:
    def __init__(self, method, use_api, threads):
        self.sid = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.db = DB(self.sid)
        self.bloom = BloomFilter(BLOOM_FAST_PATH, strict_path=BLOOM_STRICT_PATH)
        self.use_api = use_api
        self.threads = threads
        self.counter = 0; self.hits = 0; self.lock = threading.Lock()
        self.api_queue = queue.Queue(); self.stop_api = threading.Event()
        self.api_checked = 0; self.api_with_balance = 0
        self.api_thread = None  # 🔥 Сохраняем ссылку на поток API
        self.socketio = None; self.state = None
    
    def generate(self):
        mnem = mnemo.generate(strength=128)
        seed = mnemo.to_seed(mnem)
        priv_bytes = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()[:32]
        k = PrivateKey.from_bytes(priv_bytes)
        try: wif_str = k.wif
        except AttributeError: wif_str = bytes_to_wif(priv_bytes, compressed=True)
        h160 = hashlib.new('ripemd160', hashlib.sha256(k.public_key).digest()).hexdigest()
        return {'mnemonic': mnem, 'address': k.address, 'hash160': h160, 'wif': wif_str, 'time': time.time()}
    
    def check_api(self, addr):
        try:
            r = requests.get(f"https://blockstream.info/api/address/{addr}", timeout=10)
            if r.ok:
                d = r.json()['chain_stats']
                return d['funded_txo_sum'] - d['spent_txo_sum']
        except: pass
        return 0
    
    def api_worker(self):
        print("\n" + "="*60 + "\n🌐 API WORKER STARTED\n" + "="*60 + "\n")
        sys.stdout.flush()
        while not self.stop_api.is_set() or not self.api_queue.empty():
            try:
                if self.api_queue.qsize() > 0: print(f"📦 QUEUE: {self.api_queue.qsize()}"); sys.stdout.flush()
                try: addr = self.api_queue.get(timeout=2)
                except queue.Empty: continue
                print(f"🔍 Checking: {addr}"); sys.stdout.flush()
                bal = self.check_api(addr)
                self.db.update_api(addr, bal)
                with self.lock:
                    self.api_checked += 1
                    if self.state: 
                        self.state['api_checked'] = self.api_checked
                        # 🔥 Отправляем обновление в GUI
                        if self.socketio:
                            self.socketio.emit('stats_update', {
                                'generated': self.state.get('total_generated', 0),
                                'hits': self.state.get('total_hits', 0),
                                'speed': self.state.get('speed', 0),
                                'api_checked': self.api_checked,
                                'running': self.state.get('running', False),
                                'paused': self.state.get('paused', False)
                            })
                    if bal > 0:
                        self.api_with_balance += 1
                        msg = f"💰 FOUND: {addr} | {bal/1e8:.8f} BTC"
                        print(msg); sys.stdout.flush()
                        if self.socketio:
                            self.socketio.emit('new_balance', {'address': addr, 'btc': f"{bal/1e8:.8f}", 'time': datetime.now().strftime('%H:%M:%S')})
                        send_telegram(f"💰 <b>BALANCE FOUND!</b>\n📍 {addr}\n💵 {bal/1e8:.8f} BTC")
                    else: print(f"✅ Empty: {addr}"); sys.stdout.flush()
                self.api_queue.task_done()
                if not self.api_queue.empty(): time.sleep(random.uniform(20, 50))
            except Exception as e: print(f"❌ API Error: {e}"); sys.stdout.flush()
        print("🛑 API worker stopped.")
    
    def worker(self, count, pbar=None, state=None, pause_event=None):
        for i in range(count):
            if i % 100 == 0:
                try:
                    if pause_event and pause_event.is_set():
                        while pause_event.is_set(): time.sleep(0.1)
                except: pass
            w = self.generate()
            with self.lock:
                self.counter += 1
                if state: state['total_generated'] = self.counter
            if self.bloom.check(bytes.fromhex(w['hash160'])):
                with self.lock:
                    self.hits += 1
                    if state: state['total_hits'] = self.hits
                self.db.save(w)
                save_hit_to_file(w['address'], w['mnemonic'], w['wif'], w['hash160'], mode="Scanner")
                if self.use_api: self.api_queue.put(w['address'])
                if self.socketio:
                    try: self.socketio.emit('new_hit', {'address': w['address'], 'time': datetime.now().strftime('%H:%M:%S')})
                    except: pass
            if pbar: pbar.update(1)
    
    def run_with_gui(self, socketio, total, threads, method, use_api, stop_event, pause_event, state):
        self.socketio = socketio; self.state = state; self.total_target = total
        log.info(f"🚀 GUI Mode: {total:,} | Threads: {threads}")
        
        # 🔥 Запускаем API-воркер и сохраняем поток
        if use_api:
            self.api_thread = threading.Thread(target=self.api_worker, daemon=True)
            self.api_thread.start()
        
        per_thread = total // threads; remainder = total % threads; start_time = time.time()
        
        # 🔥 Генерация адресов
        with tqdm(total=total, desc="Scanning", unit="addr", dynamic_ncols=True) as pbar:
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futures = [ex.submit(self.worker, per_thread + (1 if i < remainder else 0), pbar, state, pause_event) for i in range(threads)]
                try:
                    for f in futures:
                        if stop_event.is_set(): break
                        try: f.result(timeout=0.5)
                        except: pass
                except Exception: stop_event.set()
        
        elapsed = time.time() - start_time
        
        # 🔥 Ждем завершения API-воркера после генерации
        if use_api and self.api_thread:
            print("\n⏳ Waiting for API worker to finish...")
            self.stop_api.set()  # Сигнализируем API-воркеру остановиться
            self.api_thread.join(timeout=30)  # Ждем до 30 секунд
            print("✅ API worker finished.")
        
        if stop_event.is_set(): 
            log.info(f"⏹️ Stopped at {self.counter:,}")
            return
        
        socketio.emit('scan_complete', {'generated': self.counter, 'hits': self.hits})

# ==================== MAIN ====================
if __name__ == "__main__":
    print("1) pubkey_hash160  2) address_sha256")
    method = {"1":"pubkey_hash160","2":"address_sha256"}.get(input("Method [1]: ") or "1", "pubkey_hash160")
    total = int(input("Count [50000000]: ") or "50000000")
    api = input("API? (y/n) [y]: ").lower() != 'n'
    threads = min(8, os.cpu_count() or 4)
    Scanner(method, api, threads).run_with_gui(None, total, threads, method, api, threading.Event(), threading.Event(), None)
    input("Done.")