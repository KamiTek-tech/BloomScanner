#!/usr/bin/env python3
"""
Создание Strict Bloom Filter (STABLE)
Исправлен IndexError, оптимизирован для больших файлов.
"""
import gzip
import hashlib
import math
import os
import sys
import time

ARCHIVE_NAME = "all_Bitcoin_addresses_ever_used_sorted.txt.gz"
OUTPUT_NAME = "addresses_strict.bloom"
ERROR_RATE = 0.00001
ESTIMATED_ADDRESSES = 250_000_000

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, ARCHIVE_NAME)
OUTPUT_FILE = os.path.join(SCRIPT_DIR, OUTPUT_NAME)

def decode_base58(addr_str):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    n = 0
    try:
        for char in addr_str: n = n * 58 + alphabet.index(char)
        full_bytes = n.to_bytes(25, 'big')
        return full_bytes[1:21]
    except: return None

def main():
    print("="*60 + "\n🔨 STRICT BLOOM FILTER GENERATOR (STABLE)\n" + "="*60)
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл '{ARCHIVE_NAME}' не найден!"); input("Enter..."); sys.exit(1)
    print("✅ Архив найден.")
    print("🧮 Расчет памяти...")
    m = int(-(ESTIMATED_ADDRESSES * math.log(ERROR_RATE)) / (math.log(2) ** 2))
    byte_count = (m + 7) // 8  # Фикс: округление вверх
    print(f"   • Размер: {byte_count/1024/1024:.2f} MB")
    try: bit_array = bytearray(byte_count)
    except MemoryError: print("❌ Не хватило RAM"); input("Enter..."); sys.exit(1)
    print("\n🚀 Обработка...")
    count = 0; skipped = 0; start_time = time.time()
    try:
        with gzip.open(INPUT_FILE, 'rt', encoding='utf-8') as f:
            for line in f:
                addr = line.strip()
                if not addr: continue
                if addr.startswith('bc1'): skipped += 1; continue
                h160 = decode_base58(addr)
                if not h160: skipped += 1; continue
                for i in range(3):
                    h = hashlib.sha256(h160 + i.to_bytes(4, 'big')).digest()
                    h = hashlib.sha256(h).digest()
                    pos = int.from_bytes(h[:8], 'little') % m
                    bit_array[pos // 8] |= (1 << (pos % 8))
                count += 1
                if count % 100000 == 0:
                    elapsed = time.time() - start_time
                    speed = count / elapsed if elapsed > 0 else 0
                    print(f"   ⏳ {count:,} addr | {speed:.0f} addr/s")
    except KeyboardInterrupt: print("\n⚠️ Остановка.")
    except Exception as e: print(f"\n❌ Ошибка: {e}"); input("Enter..."); sys.exit(1)
    print("\n💾 Сохранение...")
    with open(OUTPUT_FILE, 'wb') as f: f.write(bit_array)
    print(f"✅ Сохранено: {OUTPUT_FILE}")
    total_time = (time.time() - start_time) / 3600
    print(f"\n🎉 ГОТОВО! Время: {total_time:.2f} ч. | Адресов: {count:,}")
    input("Enter для выхода...")

if __name__ == "__main__":
    main()