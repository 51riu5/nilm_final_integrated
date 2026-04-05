"""
Simulate ESP32 + PZEM sensor sending live readings to the backend.

Cycles through realistic scenarios so you can watch the dashboard update
in real time. Sends one reading per second, just like the real hardware.

Usage:  python simulate_esp32.py
"""

import json
import math
import random
import time
import urllib.request

API = "http://localhost:8000/api/v1/readings"

def send(power_w, voltage=230.0, freq=50.0, pf=0.95):
    noise_v = random.uniform(-1.5, 1.5)
    noise_f = random.uniform(-0.02, 0.02)
    noise_p = random.uniform(-0.5, 0.5)
    pw = max(power_w + noise_p, 0)
    v = voltage + noise_v
    body = {
        "device_id": "esp32_1",
        "meter_id": "pzem_1",
        "site_id": "home_1",
        "voltage_v": round(v, 2),
        "current_a": round(pw / v, 4),
        "power_w": round(pw, 2),
        "energy_kwh": round(pw / 1000 / 3600, 6),
        "frequency_hz": round(freq + noise_f, 2),
        "power_factor": round(pf + random.uniform(-0.02, 0.02), 3),
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        print(f"  [!] Send failed: {e}")

SCENARIOS = [
    ("No load (standby)",          0.3,   15),
    ("Mobile charger plugged in",  12.0,  20),
    ("Mobile charging (steady)",   10.5,  15),
    ("Laptop charger plugged in",  65.0,  25),
    ("Both charging (steady)",     62.0,  20),
    ("Mobile unplugged",           50.0,  20),
    ("Laptop heavy load",          78.0,  15),
    ("Laptop idle charging",       42.0,  20),
    ("Everything unplugged",       0.2,   15),
    ("Mobile charger only",        15.0,  20),
    ("Mobile done, trickle",       5.0,   15),
    ("All off",                    0.1,   10),
]

print("=" * 55)
print("  ESP32 Simulator — sending to", API)
print("  Open the dashboard at http://localhost:5173")
print("  Press Ctrl+C to stop")
print("=" * 55)

cycle = 0
try:
    while True:
        cycle += 1
        print(f"\n--- Cycle {cycle} ---")
        for label, base_power, duration in SCENARIOS:
            print(f"\n  [{label}] ~{base_power} W for {duration}s")
            for i in range(duration):
                send(base_power)
                time.sleep(1)
        print("\n  (Looping...)")
except KeyboardInterrupt:
    print("\n\nStopped.")
