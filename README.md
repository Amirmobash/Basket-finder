# Basket Finder Radar — BLE Presence Detection & Distance Dashboard

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Bleak](https://img.shields.io/badge/BLE-Bleak-green)](https://github.com/hbldh/bleak)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Basket Finder Radar is a Python BLE presence detection dashboard that passively scans Bluetooth Low Energy advertisements and estimates beacon distance from RSSI.**

The application is designed for a **single-gateway, single-room scenario** called **Room A / Zimmer A**. It detects whether a configured BLE beacon is inside a defined distance range, records arrival and departure events, tracks stay duration, and displays real-time signal data in a desktop dashboard.

No Bluetooth pairing or GATT connection is required.

---

## Features

- Passive **BLE advertisement scanning** using [`bleak`](https://github.com/hbldh/bleak)
- No pairing or GATT connection required
- RSSI-based **BLE distance estimation**
- Configurable Room A distance range
- Presence state:
  - `Anwesend` — present
  - `Abwesend` — absent
- Arrival and departure event detection
- Per-stay duration tracking
- Daily cumulative presence duration
- Hysteresis and debouncing to reduce rapid state changes
- Live distance chart with a rolling 3-minute window
- Room A range visualization
- Mini path indicator
- CSV event logging
- German-language desktop UI
- Orange industrial-style interface

---

## Use Cases

Basket Finder Radar can be used as a prototype for:

- BLE presence detection
- Bluetooth beacon monitoring
- Basket, cart, container, or equipment presence tracking
- Indoor BLE proximity experiments
- Room-level beacon monitoring
- RSSI-based distance estimation
- BLE asset tracking prototypes
- Warehouse or industrial monitoring experiments
- Python Bluetooth Low Energy development
- BLE event logging and analytics

The current implementation is designed around **one gateway and one monitored room**.

---

## How It Works

Basket Finder Radar listens for BLE advertisement packets broadcast by nearby devices.

The application matches configured beacon names, reads their RSSI signal strength, estimates distance, and determines whether the beacon lies within the configured Room A distance range.

The default range is:

```python
ROOM_A_METER_RANGE = (1.0, 5.0)
```

A beacon whose estimated distance is between `1.0 m` and `5.0 m` is treated as being inside Room A.

The basic processing flow is:

```text
BLE Advertisement
      ↓
Device Name Matching
      ↓
RSSI Measurement
      ↓
Distance Estimation
      ↓
Smoothing / Debouncing
      ↓
Room A Range Check
      ↓
Presence State
      ↓
UI + CSV Event Log
```

> Distance is estimated from RSSI. BLE RSSI is affected by walls, people, antenna orientation, interference, reflections, and the surrounding environment, so the reported meter value should be treated as an estimate rather than a precise physical measurement.

---

## Requirements

### Software

- Python 3.10+
- Bluetooth support
- Python `venv`
- `pip`

### Python Dependencies

The project uses:

```text
bleak>=0.22
matplotlib>=3.8
```

`tkinter` is normally included with standard Python installers on Windows and macOS.

On some Linux distributions, install it separately, for example:

```bash
sudo apt install python3-tk
```

Linux BLE support may also require BlueZ.

### Hardware

- Computer with Bluetooth Low Energy support
- BLE beacon or compatible BLE advertiser

The optional example in this repository can advertise the device name:

```text
ITAG
```

---

## Quick Start

### Windows PowerShell

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -U pip; pip install -r requirements.txt; python presence_by_name.py
```

### macOS / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt && python3 presence_by_name.py
```

---

## Installation

Clone the repository:

```bash
git clone <YOUR-REPOSITORY-URL>
cd <YOUR-REPOSITORY-DIRECTORY>
```

### Windows

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run the application:

```powershell
python presence_by_name.py
```

### macOS / Linux

Create a virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run:

```bash
python presence_by_name.py
```

---

## Configuration

Open:

```text
presence_by_name.py
```

and adjust the configuration values near the top of the file.

Example:

```python
SCAN_WINDOW_SEC = 5.0

# Inside Room A when estimated distance lies between these values.
ROOM_A_METER_RANGE = (1.0, 5.0)

CSV_LOG_PATH = "ble_events.csv"

NAME_TARGETS = {
    "ITAG": "Basket-1"
}
```

### `SCAN_WINDOW_SEC`

Controls the BLE scanning window:

```python
SCAN_WINDOW_SEC = 5.0
```

### `ROOM_A_METER_RANGE`

Defines the estimated distance range considered inside Room A:

```python
ROOM_A_METER_RANGE = (1.0, 5.0)
```

With the default configuration:

```text
1.0 m ≤ estimated distance ≤ 5.0 m
```

is considered present in Room A.

### `CSV_LOG_PATH`

Defines the event log file:

```python
CSV_LOG_PATH = "ble_events.csv"
```

### `NAME_TARGETS`

Maps BLE device-name matches to display names:

```python
NAME_TARGETS = {
    "ITAG": "Basket-1"
}
```

Matching is performed by device name substring and is case-insensitive.

---

## Dashboard

The interface displays information including:

- Presence status
- RSSI in dBm
- Estimated distance in meters
- Room A distance range
- Live distance chart
- Room range shading
- Mini path indicator
- Arrival and departure event history

The UI uses German presence labels:

```text
Anwesend
Abwesend
```

---

## BLE Distance Estimation

Bluetooth RSSI indicates received signal strength.

Basket Finder Radar uses RSSI as the input for estimating the approximate distance between the BLE beacon and scanner.

BLE distance estimation is inherently approximate.

Factors that can change RSSI include:

- Walls
- Shelving
- People
- Metal objects
- Beacon orientation
- Scanner orientation
- Multipath reflections
- Radio interference
- Beacon transmit power
- Bluetooth adapter characteristics

For reliable room-presence detection, tune the configured distance thresholds in the actual deployment environment.

---

## Presence Detection

The application combines estimated distance with hysteresis and debouncing.

This helps reduce repeated state changes when the RSSI value fluctuates near the Room A boundary.

Example:

```text
Beacon detected
      ↓
Distance estimated
      ↓
Distance inside configured range?
      ↓
Debounce / hysteresis logic
      ↓
Anwesend or Abwesend
```

Arrival and departure events are then recorded.

---

## CSV Event Logging

Events are written by default to:

```text
ble_events.csv
```

### Arrival Event

Arrival rows include values such as:

```text
timestamp
BEREICHS_BETRETEN
device
room
distance
```

### Departure Event

Departure rows include values such as:

```text
timestamp
BEREICHS_VERLASSEN
device
room
duration
total_today
last_distance
```

This makes the output suitable for later analysis in spreadsheet software, Python, or another data-processing tool.

---

## BLE Beacon Advertiser

An optional beacon advertiser example is available at:

```text
tools/beacon_advertiser_itag.ino
```

It broadcasts the BLE device name:

```text
ITAG
```

Example:

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

void loop() {
  delay(1000);
}
```

The Python application can then match the advertised `ITAG` name using:

```python
NAME_TARGETS = {
    "ITAG": "Basket-1"
}
```

---

## Project Structure

```text
.
├── presence_by_name.py
├── requirements.txt
├── scripts/
│   ├── setup_venv_windows.ps1
│   ├── setup_venv_unix.sh
│   ├── run_windows.ps1
│   └── run_unix.sh
├── tools/
│   ├── beacon_advertiser_itag.ino
│   └── win_ble_fix.ps1
├── .gitignore
└── README.md
```

### `presence_by_name.py`

Main application containing:

- BLE scanning
- Presence logic
- Distance estimation
- Desktop UI
- Event logging

### `scripts/`

Helper scripts for creating virtual environments and running the application.

### `tools/`

Optional BLE advertiser and Windows Bluetooth helper files.

---

## Helper Scripts

### Windows Environment Setup

```powershell
.\scripts\setup_venv_windows.ps1
```

Equivalent script:

```powershell
param(
  [string]$Python="python"
)

$ErrorActionPreference = "Stop"

& $Python -m venv .venv
& .\.venv\Scripts\Activate.ps1
& python -m pip install --upgrade pip
& pip install -r requirements.txt

Write-Host "✅ Virtual env ready. Run: .\.venv\Scripts\Activate.ps1 ; python presence_by_name.py"
```

### macOS / Linux Environment Setup

```bash
./scripts/setup_venv_unix.sh
```

Script:

```bash
#!/usr/bin/env bash
set -euo pipefail

PY=${1:-python3}

$PY -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt

echo "✅ Virtual env ready. Run: source .venv/bin/activate && python presence_by_name.py"
```

### Windows Run Script

```powershell
.\scripts\run_windows.ps1
```

```powershell
.\.venv\Scripts\Activate.ps1
python presence_by_name.py
```

### macOS / Linux Run Script

```bash
./scripts/run_unix.sh
```

```bash
#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
python presence_by_name.py
```

---

## Windows Bluetooth Helper

The repository includes an optional helper:

```text
tools/win_ble_fix.ps1
```

It reminds users to check Bluetooth and USB power-saving settings:

```powershell
Write-Host "Remember to disable 'Allow the computer to turn off this device to save power' for Bluetooth/USB in Device Manager."
```

Administrator permissions may be required to modify related system settings.

---

## FAQ

### What is BLE presence detection?

BLE presence detection determines whether a Bluetooth Low Energy device or beacon is near a scanner by observing its advertisement packets and signal strength.

Basket Finder Radar uses BLE advertisements, RSSI, and configurable distance thresholds to determine whether a device is considered inside Room A.

### Does the BLE device need to be paired?

No.

Basket Finder Radar passively scans BLE advertisements and does not require Bluetooth pairing or a GATT connection.

### How does Basket Finder Radar estimate BLE distance?

The application estimates distance from the received BLE signal strength, or RSSI.

Because radio signals are affected by the physical environment, the resulting distance is approximate.

### Can BLE RSSI accurately measure distance in meters?

Not precisely.

RSSI can provide a useful proximity estimate, but it is not equivalent to a dedicated ranging technology. Environmental calibration is recommended.

### Can I use another beacon name instead of ITAG?

Yes.

Change:

```python
NAME_TARGETS = {
    "ITAG": "Basket-1"
}
```

to match the BLE name you want to monitor.

### Can I change the Room A detection distance?

Yes.

Change:

```python
ROOM_A_METER_RANGE = (1.0, 5.0)
```

to the desired estimated distance range.

### Does the application connect to the beacon?

No.

The application scans BLE advertisements without making a GATT connection.

### Does it save arrival and departure history?

Yes.

Arrival and departure events are written to:

```text
ble_events.csv
```

including timestamps and relevant presence information.

### Does it work on Windows?

Yes, provided the computer has a compatible Bluetooth adapter.

The project also includes Windows PowerShell helper scripts.

### Does it work on Linux or macOS?

The code is intended to support Windows, Linux, and macOS through `bleak`, subject to OS Bluetooth support and required system dependencies.

---

## Limitations

Basket Finder Radar uses RSSI-based distance estimation.

It should therefore not be interpreted as a precision indoor positioning system.

The project currently targets a:

```text
single gateway
+
single room
```

configuration.

The meter-based boundaries should be calibrated for the actual environment in which the system is used.

---

## Requirements File

Example `requirements.txt`:

```txt
bleak>=0.22
matplotlib>=3.8
```

`winsound` is part of the Python standard library on Windows and does not require installation through `pip`.

---

## .gitignore

Recommended entries:

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.env
.cache/

# Virtual environment
.venv/

# OS
.DS_Store
Thumbs.db

# Logs / Data
ble_events.csv
```

---

## Contributing

Pull requests are welcome.

When contributing:

- Preserve the German UI terminology where appropriate.
- Keep the orange interface design consistent.
- Avoid breaking BLE advertisement scanning.
- Preserve CSV event semantics.
- Document configuration changes.
- Test BLE presence behavior before submitting changes.

---

## Author

**Amir Mobasheraghdam**

Related publication:

[Mein Computer lernt von mir](https://buchshop.bod.de/mein-computer-lernt-von-mir-amir-mobasheraghdam-9783695791002)

---

## License

This project is intended to use the MIT License.

If an MIT `LICENSE` file is included in the repository, the project can be described as:

> Licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Related Resources

- [Bleak — Python Bluetooth Low Energy client](https://github.com/hbldh/bleak)
- [Python](https://www.python.org/)
- [Matplotlib](https://matplotlib.org/)

Basket Finder Radar is useful for developers researching **BLE presence detection**, **Bluetooth beacon tracking**, **RSSI distance estimation**, and **Python BLE monitoring dashboards**.
