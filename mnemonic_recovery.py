#!/usr/bin/env python3
"""
BIP39 Mnemonic Recovery Engine (Safe API + Export)
✅ Missing / Shuffled / Typo
✅ Cascade Bloom + Safe API Delay (2-5s)
✅ Telegram + File Export
"""
import os
import sys
import time
import hashlib
import hmac
import itertools
import math
import difflib
import random
import requests
from datetime import datetime
from mnemonic import Mnemonic
from bit import PrivateKey
from concurrent.futures import ThreadPoolExecutor, as_completed

TELEGRAM_ENABLED = os.environ.get('TG_ENABLED', '0') == '1'
TELEGRAM_TOKEN = os.environ.get('TG_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TG_CHAT_ID', '')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)
FOUND_FILE = os.path.join(RESULTS_DIR, "found_wallets.txt")
sys.path.insert(0, BASE_DIR)
mnemo = Mnemonic("english")
WORDLIST = mnemo.wordlist
WORD_SET = set(WORDLIST)

def save_recovery_hit(address, phrase, balance=0):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(FOUND_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] RECOVERY | Addr: {address} | Bal: {balance} | Phrase: {phrase}\n" + "-"*80 + "\n")
    except: pass

def load_bloom_filter():
    path = os.path.join(BASE_DIR, "addresses_strict.bloom")
    if not os.path.exists(path): path = os.path.join(BASE_DIR, "addresses.bloom")
    if not os.path.exists(path): raise FileNotFoundError("Bloom filter not found!")
    with open(path, 'rb') as f: data = bytearray(f.read())
    return data, len(data) * 8

def check_bloom(h160, bloom_data, bloom_bits):
    for i in range(3):
        h = hashlib.sha256(h160 + i.to_bytes(4, 'big')).digest()
        h = hashlib.sha256(h).digest()
        pos = int.from_bytes(h[:8], 'little') % bloom_bits
        if not (bloom_data[pos//8] & (1 << (pos%8))): return False
    return True

def verify_address_balance(addr):
    try:
        r = requests.get(f"https://blockstream.info/api/address/{addr}", timeout=10)
        if r.ok:
            d = r.json()['chain_stats']
            return (d['funded_txo_sum'] - d['spent_txo_sum']) / 1e8
    except: pass
    return 0.0

def derive_address(phrase):
    try:
        seed = mnemo.to_seed(phrase, passphrase="")
        k = PrivateKey.from_seed(seed, path="m/44'/0'/0'/0")
        return k.address, k.public_key
    except: return None, None

def send_telegram(phrase, addr, bal):
    if not TELEGRAM_ENABLED: return
    msg = f"🔓 <b>RECOVERY FOUND!</b>\n\nPhrase: <code>{phrase}</code>\nAddr: {addr}\nBal: {bal} BTC"
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})
    except: pass

def recover_missing(words, missing_indices, bloom_data, bloom_bits, emit_progress, emit_hit, stop_flag):
    total = 2048 ** len(missing_indices)
    checked = 0; last_report = time.time()
    for combo in itertools.product(WORDLIST, repeat=len(missing_indices)):
        if stop_flag.is_set(): break
        temp = words[:]
        for idx, word in zip(missing_indices, combo): temp[idx] = word
        phrase = ' '.join(temp)
        if not mnemo.check(phrase): checked += 1; continue
        addr, pub_key = derive_address(phrase)
        if not addr: checked += 1; continue
        h160 = hashlib.new('ripemd160', hashlib.sha256(pub_key).digest()).digest()
        if check_bloom(h160, bloom_data, bloom_bits):
            time.sleep(random.uniform(2, 5))
            bal = verify_address_balance(addr)
            if bal > 0:
                emit_hit(phrase, addr, bal); send_telegram(phrase, addr, bal); save_recovery_hit(addr, phrase, bal)
            else: save_recovery_hit(addr, phrase, 0)
        checked += 1
        if time.time() - last_report > 0.5: emit_progress(checked, total); last_report = time.time()
    emit_progress(checked, total)

def recover_shuffled(words, bloom_data, bloom_bits, emit_progress, emit_hit, stop_flag):
    total = math.factorial(len(words))
    checked = 0; last_report = time.time()
    def worker(perm):
        nonlocal checked
        phrase = ' '.join(perm)
        if not mnemo.check(phrase): checked += 1; return
        addr, pub_key = derive_address(phrase)
        if not addr: checked += 1; return
        h160 = hashlib.new('ripemd160', hashlib.sha256(pub_key).digest()).digest()
        if check_bloom(h160, bloom_data, bloom_bits):
            time.sleep(random.uniform(2, 5))
            bal = verify_address_balance(addr)
            if bal > 0: emit_hit(phrase, addr, bal); send_telegram(phrase, addr, bal); save_recovery_hit(addr, phrase, bal)
        checked += 1
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = []
        for perm in itertools.permutations(words):
            if stop_flag.is_set(): break
            futures.append(ex.submit(worker, perm))
            if time.time() - last_report > 0.5: emit_progress(checked, total); last_report = time.time()
        for f in as_completed(futures): pass
    emit_progress(checked, total)

def recover_typo(words, bloom_data, bloom_bits, emit_progress, emit_hit, stop_flag):
    cands_list = []
    for w in words:
        if w in WORD_SET: cands_list.append([w])
        else:
            c = [x for x in WORDLIST if x.startswith(w[:3].lower())] or difflib.get_close_matches(w, WORDLIST, n=2, cutoff=0.7)
            cands_list.append(c if c else [w])
    total = math.prod(len(c) for c in cands_list)
    if total > 50000: raise ValueError("Too many combinations for Typo mode.")
    checked = 0; last_report = time.time()
    for combo in itertools.product(*cands_list):
        if stop_flag.is_set(): break
        phrase = ' '.join(combo)
        if not mnemo.check(phrase): checked += 1; continue
        addr, pub_key = derive_address(phrase)
        if not addr: checked += 1; continue
        h160 = hashlib.new('ripemd160', hashlib.sha256(pub_key).digest()).digest()
        if check_bloom(h160, bloom_data, bloom_bits):
            time.sleep(random.uniform(2, 5))
            bal = verify_address_balance(addr)
            if bal > 0: emit_hit(phrase, addr, bal); send_telegram(phrase, addr, bal); save_recovery_hit(addr, phrase, bal)
        checked += 1
        if time.time() - last_report > 0.5: emit_progress(checked, total); last_report = time.time()
    emit_progress(checked, total)