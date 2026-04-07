#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIP39 BTC BLOOM SCANNER — CPU ONLY
✅ Stable, simple, no GPU dependencies
✅ IMMEDIATE STOP SUPPORT
✅ API ACTIVE FLAG FIX
"""
import sys
import os
import time
import json
import sqlite3
import hashlib
import hmac
import logging
import ctypes
import threading
import queue
import random
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# ==================== IMPORTS ====================
try:
    from bit import PrivateKey
    from bit.format import bytes_to_wif
    from mnemonic import Mnemonic
except ImportError as e:
    print(f"\n❌ Missing: {e}\n💡 py -3.12 -m pip install bit mnemonic requests tqdm flask flask-socketio\n"); sys.exit(1)

mnemo = Mnemonic("english")

# ==================== CONFIG FROM ENV ====================
TELEGRAM_ENABLED = os.environ.get('TG_ENABLED', '0') == '1'
TELEGRAM_TOKEN = os.environ.get('TG_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TG_CHAT_ID', '')

# ==================== ADMIN ====================
def ensure_admin():
    if sys.platform != 'win32': return
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            script = os.path.abspath(sys.argv[0])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}"', os.path.dirname(script), 1)
            sys.exit(0)
    except: pass

# ==================== PATHS & LOGS ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
RESULTS_DIR = os.path.join(BASE_DIR, "results")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
BLOOM_PATH = os.path.join(BASE_DIR, "addresses.bloom")
os.makedirs(RESULTS_DIR, exist_ok=True); os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOGS_DIR, "scanner.log"), encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger()

if not os.path.exists(BLOOM_PATH):
    log.error("❌ addresses.bloom not found"); sys.exit(1)

# ==================== TELEGRAM ====================
def send_telegram(msg):
    if not TELEGRAM_ENABLED or not TELEGRAM_TOKEN: return False
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                     json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        return True
    except: return False

# ==================== BLOOM FILTER ====================
class BloomFilter:
    def __init__(self, path):
        with open(path, 'rb') as f: self.data = bytearray(f.read())
        self.bits = len(self.data) * 8
        log.info(f"✅ Loaded: {self.bits:,} bits")
    def check(self, h160):
        for i in range(3):
            h = hashlib.sha256(h160 + i.to_bytes(4, 'big')).digest()
            h += hashlib.sha256(h).digest()
            pos = int.from_bytes(h[:8], 'little') % self.bits
            if not (self.data[pos//8] & (1 << (pos%8))): return False
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

# ==================== SCANNER ENGINE ====================
class Scanner:
    def __init__(self, method, use_api, threads):
        self.sid = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.db = DB(self.sid)
        self.bloom = BloomFilter(BLOOM_PATH)
        self.use_api = use_api
        self.threads = threads
        self.counter = 0
        self.hits = 0
        self.lock = threading.Lock()
        self.api_queue = queue.Queue()
        self.stop_api = threading.Event()
        self.api_checked = 0
        self.api_with_balance = 0
        self.api_empty = 0
        self.api_errors = 0
        self.total_target = 0
        self.socketio = None
        self.state = None
    
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
        """LOUD API WORKER"""
        print("\n" + "="*60 + "\n🌐 API WORKER STARTED\n" + "="*60 + "\n")
        sys.stdout.flush()
        
        while not self.stop_api.is_set() or not self.api_queue.empty():
            try:
                q_size = self.api_queue.qsize()
                if q_size > 0: print(f"📦 QUEUE: {q_size} waiting"); sys.stdout.flush()
                try: addr = self.api_queue.get(timeout=2)
                except queue.Empty: continue
                print(f"🔍 Checking: {addr}"); sys.stdout.flush()
                bal = self.check_api(addr)
                self.db.update_api(addr, bal)
                with self.lock:
                    self.api_checked += 1
                    if self.state: self.state['api_checked'] = self.api_checked
                    if bal > 0:
                        self.api_with_balance += 1
                        print(f"💰 FOUND: {addr} | {bal/1e8:.8f} BTC"); sys.stdout.flush()
                        if self.socketio:
                            self.socketio.emit('new_balance', {
                                'address': addr, 'btc': f"{bal/1e8:.8f}",
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                        msg = f"💰 <b>BALANCE FOUND!</b>\n📍 {addr}\n💵 {bal/1e8:.8f} BTC"
                        send_telegram(msg)
                    else:
                        print(f"✅ Empty: {addr}"); sys.stdout.flush()
                self.api_queue.task_done()
                if not self.api_queue.empty():
                    delay = random.uniform(20, 50)
                    print(f"⏳ Wait {delay:.0f}s"); sys.stdout.flush()
                    time.sleep(delay)
            except Exception as e:
                print(f"❌ API Error: {e}"); sys.stdout.flush()
        
        print("🛑 API worker stopped.")
        
        # 🔥 TURN OFF API ACTIVE FLAG
        if self.state:
            self.state['api_active'] = False
        if self.socketio:
            self.socketio.emit('api_complete', {'api_checked': self.api_checked})
    
    def worker(self, count, pbar=None, state=None, pause_event=None):
        for i in range(count):
            # Проверка остановки каждые 100 итераций
            if i % 100 == 0:
                try:
                    if pause_event and pause_event.is_set():
                        while pause_event.is_set(): 
                            time.sleep(0.1)
                except:
                    pass
            
            w = self.generate()
            
            with self.lock:
                self.counter += 1
                if state: state['total_generated'] = self.counter
            
            if self.bloom.check(bytes.fromhex(w['hash160'])):
                with self.lock:
                    self.hits += 1
                    if state: state['total_hits'] = self.hits
                self.db.save(w)
                if self.use_api: self.api_queue.put(w['address'])
                if self.socketio:
                    try: self.socketio.emit('new_hit', {'address': w['address'], 'time': datetime.now().strftime('%H:%M:%S')})
                    except: pass
            
            if pbar: pbar.update(1)
    
    def run(self, total):
        self.total_target = total
        log.info(f"🚀 Target: {total:,} | Threads: {self.threads}")
        if self.use_api: threading.Thread(target=self.api_worker, daemon=True).start()
        per_thread = total // self.threads; remainder = total % self.threads
        with tqdm(total=total, desc="Scanning", unit="addr", dynamic_ncols=True) as pbar:
            with ThreadPoolExecutor(max_workers=self.threads) as ex:
                futures = [ex.submit(self.worker, per_thread + (1 if i < remainder else 0), pbar) for i in range(self.threads)]
                for f in futures: f.result()
        log.info(f"✅ Done: {self.counter:,} gen, {self.hits:,} hits")
    
    def run_with_gui(self, socketio, total, threads, method, use_api, stop_event, pause_event, state):
        # 🔥 НЕ ВЫЗЫВАЕМ __init__ ЗДЕСЬ!
        self.socketio = socketio
        self.state = state
        self.total_target = total
        self.use_api = use_api
        self.threads = threads
        
        log.info(f"🚀 GUI Mode: {total:,} | Threads: {threads} | API: {'ON' if use_api else 'OFF'}")
        
        if use_api:
            threading.Thread(target=self.api_worker, daemon=True).start()
        
        per_thread = total // threads
        remainder = total % threads
        start_time = time.time()
        
        with tqdm(total=total, desc="Scanning", unit="addr", dynamic_ncols=True) as pbar:
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futures = [ex.submit(self.worker, per_thread + (1 if i < remainder else 0), pbar, state, pause_event) for i in range(threads)]
                try:
                    for f in futures:
                        if stop_event.is_set():
                            print("🛑 Stop detected, cancelling...")
                            for remaining_f in futures:
                                if not remaining_f.done():
                                    remaining_f.cancel()
                            break
                        try:
                            f.result(timeout=0.5)
                        except:
                            pass
                except Exception as e:
                    print(f"❌ Error: {e}")
                    stop_event.set()
        
        elapsed = time.time() - start_time
        if stop_event.is_set():
            log.info(f"⏹️ Stopped at {self.counter:,}")
            return
        
        log.info(f"✅ Completed: {self.counter:,} in {elapsed:.1f}s")
        socketio.emit('scan_complete', {
            'generated': self.counter, 'hits': self.hits,
            'time_sec': elapsed, 'avg_speed': self.counter/elapsed if elapsed > 0 else 0
        })

# ==================== MAIN ====================
if __name__ == "__main__":
    ensure_admin()
    print("\n1) pubkey_hash160  2) address_sha256")
    method = {"1":"pubkey_hash160","2":"address_sha256"}.get(input("Method [1]: ") or "1", "pubkey_hash160")
    total = int(input("Count [50000000]: ") or "50000000")
    api = input("API? (y/n) [y]: ").lower() != 'n'
    threads = min(8, os.cpu_count() or 4)
    start = time.time()
    Scanner(method, api, threads).run(total)
    log.info(f"⏱️ Time: {(time.time()-start)/60:.1f} min")
    input("\nPress Enter...")