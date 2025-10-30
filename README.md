# Basket-finder

├─ README.md
├─ requirements.txt
├─ presence_by_name.py
├─ tools/
│ 
│  └─ win_ble_fix.ps1
├─ scripts/
│  └─ run_unix.sh
└─ .gitignore
```


---

## README.md (copy-paste)

````markdown
# Basket finder Radar — BLE Presence & Distance Dashboard (Zimmer A)

Basket finder Radar is a Python desktop app that **passively scans BLE advertisements** (no pairing) and presents a live, industrial **orange-themed** UI for **presence detection** in *Room A* based on **distance (meters)** estimated from RSSI.

- **Single gateway / single room (Zimmer A)** scenario.
- **Inside** when the estimated distance lies **within a configurable meter range** (default: `1.0–5.0 m`).
- **Arrival/Departure** events are logged with timestamps, **per-stay duration**, and **daily cumulative presence**.
- Smooth chart with a 3-minute window and a mini path indicator.
- CSV logging enabled (`ble_events.csv`).

## Features

- **Passive BLE scanning** via `bleak` (no GATT connection / no pairing).
- **Distance-based presence**: configurable **Room A range** (meters) highlighted in the chart.
- **Hysteresis & debouncing** to reduce chattering.

----Amir Mobasheraghdam

## Requirements

- **Python 3.10+** (recommended)
- OS:
  - Windows 10/11 (Bluetooth adapter, `winsound` available)
  - Linux/macOS (Bluetooth adapter; `tkinter` and BlueZ on Linux; sound beeps may be skipped)
- Hardware:

----Amir Mobasheraghdam

## Quick Start (one-line)

> Windows PowerShell:
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -U pip; pip install -r requirements.txt; python presence_by_name.py
````

> macOS / Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt && python3 presence_by_name.py
```

---Amir Mobasheraghdam

## Standard Setup

1. **Create & activate venv**

**Windows (PowerShell):**

```powershell
python -m venv .venv


**macOS / Linux (bash):**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. **Install Python dependencies**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. **Run**

```bash
python presence_by_name.py
```

---

## Configuration

Open `presence_by_name.py` and adjust at the top:

```python
SCAN_WINDOW_SEC = 5.0

# Room A meter range: inside when distance is between these bounds
ROOM_A_METER_RANGE = (1.0, 5.0)     # e.g., 1–5 m considered “inside Room A”

CSV_LOG_PATH = "ble_events.csv"

NAME_TARGETS = {"ITAG": "Basket-1"} # match by substring (case-insensitive)
```

**What you’ll see in the UI:**

* **Status**: Anwesend/Abwesend
* **RSSI** (dBm), **Distance** (m), **Room A range** badge
* **Live chart** with Room-A range shading and your signal’s distance curve
* **Mini path indicator**
* **Event log** (arrival/departure)

> Note: Distance is an *estimate* derived from RSSI and smoothed to reduce jitter.

---

## Bacon Advertiser (optional)

Flash this to an beacon to broadcast a BLE name **"ITAG"** continuously.

See `tools/beacon_advertiser_itag.ino`. Summary:

```cpp
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEAdvertising.h>

void setup() {
  BLEDevice::init("ITAG");     // the Python app looks for this name
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->setScanResponse(false);
  adv->start();
}

void loop() { delay(1000); }
```

---

## CSV Output

By default logs to `ble_events.csv`:

* Arrival rows: timestamp, `BEREICHS_BETRETEN`, device, room, distance
* Departure rows: timestamp, `BEREICHS_VERLASSEN`, device, room, duration, total_today, last_distance

---



## Project Structure

```
presence_by_name.py        # main app (UI + BLE scan + logic)
requirements.txt           # Python dependencies
tools/beacon_advertiser_itag.ino

```

---

## License

MIT (or your choice)

---

## Contributing

Pull requests welcome:

* Keep **German UI text** and **orange theme** consistent.
* Don’t break the BLE scanning logic or CSV semantics.

````

---

## requirements.txt

```txt
bleak>=0.22
matplotlib>=3.8
# tkinter is part of the standard Python installers for Windows/macOS;
# on some Linux distros, install system package: e.g., python3-tk
````

> `winsound` is part of the Python standard library on Windows; no pip needed.

---

## scripts/setup_venv_windows.ps1

```powershell
param(
  [string]$Python="python"
)
$ErrorActionPreference = "Stop"

& $Python -m venv .venv
& .\.venv\Scripts\Activate.ps1
& python -m pip install --upgrade pip
& pip install -r requirements.txt

Write-Host "✅ Virtual env ready. Run:  .\.venv\Scripts\Activate.ps1 ; python presence_by_name.py"
```

## scripts/setup_venv_unix.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

PY=${1:-python3}

$PY -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo "✅ Virtual env ready. Run:  source .venv/bin/activate && python presence_by_name.py"
```

## scripts/run_windows.ps1

```powershell
.\.venv\Scripts\Activate.ps1
python presence_by_name.py
```

## scripts/run_unix.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
python presence_by_name.py
```

---

## tools/beacon_advertiser_itag.ino

```cpp
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEAdvertising.h>

void setup() {
  BLEDevice::init("ITAG");
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->setScanResponse(false);
  adv->setMinPreferred(0x06);
  adv->start();
}

void loop() { delay(1000); }
```

---

## tools/win_ble_fix.ps1 (optional helper)

```powershell
# Disable power saving on Bluetooth + USB hubs (optional, admin may be required)
Write-Host "Remember to disable 'Allow the computer to turn off this device to save power' for Bluetooth/USB in Device Manager."
```

---

## .gitignore

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.env
.cache/

# OS
.DS_Store
Thumbs.db

# Logs / Data
ble_events.csv
```

---

### One-liner to publish to GitHub

```bash
git init
git add .
git commit -m "Initial: Basket finder Radar (BLE presence, Room A, orange UI)"


If you want, I can also generate a short **MIT LICENSE** file and a **GitHub Actions workflow** later (e.g., to run flake8/black).
