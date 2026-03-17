#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Basket finder Radar — BLE Presence & Distance Dashboard (Zimmer A)

Passively scans BLE advertisements, estimates distance from RSSI, and detects
presence inside Room A (configurable meter range). Displays live orange‑themed UI
with chart, event log, and logs arrival/departure events to CSV.
"""

import asyncio
import csv
import datetime
import os
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Third‑party
import bleak
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import scrolledtext

# Platform‑specific
if sys.platform == "win32":
    import winsound


# ----------------------------------------------------------------------
# Configuration (adjust as needed)
# ----------------------------------------------------------------------
SCAN_WINDOW_SEC = 5.0                # Duration of each BLE scan
SCAN_INTERVAL_SEC = 5.0              # Wait between scans (non‑overlapping)
ROOM_A_METER_RANGE = (1.0, 5.0)       # Inside if distance in this interval
HYSTERESIS_MARGIN = 0.5               # Meters added to range for state change
DEBOUNCE_COUNT = 2                    # Require N consecutive same state
SMOOTHING_FACTOR = 0.3                 # Exponential moving average alpha

# RSSI to distance conversion (simple log‑distance model)
TX_POWER_1M = -59                      # Calibrated RSSI at 1 meter (dBm)
PATH_LOSS_EXP = 2.5                    # Environment factor

CSV_LOG_PATH = "ble_events.csv"

# Device name matching: substring -> friendly name (case‑insensitive)
NAME_TARGETS = {"ITAG": "Basket-1"}

# Chart time window (seconds)
CHART_WINDOW_SEC = 180


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def distance_from_rssi(rssi: int) -> float:
    """Convert RSSI (dBm) to estimated distance in meters."""
    if rssi == 0:
        return 10.0  # fallback
    return 10 ** ((TX_POWER_1M - rssi) / (10 * PATH_LOSS_EXP))


def exponential_smooth(new: float, old: Optional[float], alpha: float = SMOOTHING_FACTOR) -> float:
    """Exponential moving average. If old is None, return new."""
    if old is None:
        return new
    return alpha * new + (1 - alpha) * old


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------
@dataclass
class DeviceState:
    """State of a tracked device."""
    friendly_name: str
    last_seen: float = 0.0
    raw_rssi: int = -100
    smoothed_distance: Optional[float] = None
    presence_inside: bool = False
    debounce_counter: int = 0
    last_state_change: float = 0.0
    history_times: deque = field(default_factory=lambda: deque(maxlen=100))
    history_distances: deque = field(default_factory=lambda: deque(maxlen=100))


# ----------------------------------------------------------------------
# BLE Scanner (runs in a separate thread with its own asyncio loop)
# ----------------------------------------------------------------------
class BLEScanner(threading.Thread):
    def __init__(self, result_queue: queue.Queue):
        super().__init__(daemon=True)
        self.result_queue = result_queue
        self.loop = None
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        asyncio.set_event_loop_policy(bleak.get_platform_loop_policy())
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._scan_loop())

    async def _scan_loop(self):
        while not self._stop_event.is_set():
            try:
                # Perform one scan
                scanner = bleak.BleakScanner()
                devices = await scanner.discover(timeout=SCAN_WINDOW_SEC, return_adv=True)
                now = time.time()
                for addr, (dev, adv_data) in devices.items():
                    if not adv_data.local_name:
                        continue
                    name = adv_data.local_name
                    # Check if name contains any target substring
                    for target, friendly in NAME_TARGETS.items():
                        if target.lower() in name.lower():
                            # Found a device of interest
                            rssi = adv_data.rssi
                            self.result_queue.put((now, friendly, rssi))
                            break
            except Exception as e:
                print(f"BLE scan error: {e}", file=sys.stderr)
            # Wait before next scan (non‑overlapping)
            await asyncio.sleep(SCAN_INTERVAL_SEC)


# ----------------------------------------------------------------------
# Main Application (tkinter)
# ----------------------------------------------------------------------
class PresenceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Basket finder Radar – Zimmer A")
        self.geometry("1200x700")
        self.configure(bg="#2b2b2b")  # dark background

        # Data
        self.devices: Dict[str, DeviceState] = {}
        self.queue = queue.Queue()
        self.scanner = BLEScanner(self.queue)
        self.scanner.start()

        # CSV logging
        self.csv_file = None
        self.csv_writer = None
        self._init_csv()

        # Build UI
        self._build_ui()

        # Start periodic UI updates
        self.update_interval = 1000  # ms
        self.after(self.update_interval, self._process_queue)
        self.after(2000, self._update_ui)  # initial chart update

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_csv(self):
        """Open CSV file and write header if needed."""
        file_exists = os.path.isfile(CSV_LOG_PATH)
        self.csv_file = open(CSV_LOG_PATH, "a", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        if not file_exists:
            self.csv_writer.writerow([
                "timestamp", "event", "device", "room",
                "distance_m", "duration_s", "total_today_s"
            ])
            self.csv_file.flush()

    def _build_ui(self):
        """Create all GUI elements with orange/black theme."""
        # Colors
        bg = "#2b2b2b"
        fg = "#ff8c00"  # orange
        list_bg = "#3c3c3c"
        list_fg = "#ffa500"

        # Top frame: current status
        top_frame = tk.Frame(self, bg=bg)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.status_label = tk.Label(
            top_frame, text="Status: Unbekannt", font=("Helvetica", 16, "bold"),
            fg=fg, bg=bg
        )
        self.status_label.pack(side=tk.LEFT, padx=10)

        self.device_label = tk.Label(
            top_frame, text="Gerät: —", font=("Helvetica", 14),
            fg=fg, bg=bg
        )
        self.device_label.pack(side=tk.LEFT, padx=20)

        self.rssi_label = tk.Label(
            top_frame, text="RSSI: —", font=("Helvetica", 14),
            fg=fg, bg=bg
        )
        self.rssi_label.pack(side=tk.LEFT, padx=20)

        self.distance_label = tk.Label(
            top_frame, text="Distanz: — m", font=("Helvetica", 14),
            fg=fg, bg=bg
        )
        self.distance_label.pack(side=tk.LEFT, padx=20)

        # Middle frame: chart + mini path
        mid_frame = tk.Frame(self, bg=bg)
        mid_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Matplotlib figure
        self.fig, self.ax = plt.subplots(figsize=(8, 3), dpi=100)
        self.fig.patch.set_facecolor(bg)
        self.ax.set_facecolor("#3c3c3c")
        self.ax.tick_params(colors=fg)
        self.ax.spines["bottom"].set_color(fg)
        self.ax.spines["left"].set_color(fg)
        self.ax.xaxis.label.set_color(fg)
        self.ax.yaxis.label.set_color(fg)
        self.ax.set_ylim(0, 10)
        self.ax.set_xlabel("Zeit (sek)", color=fg)
        self.ax.set_ylabel("Distanz (m)", color=fg)

        # Room A range shading
        low, high = ROOM_A_METER_RANGE
        self.ax.axhspan(low, high, color="orange", alpha=0.3, label="Zimmer A")

        self.line, = self.ax.plot([], [], color="orange", linewidth=2)
        self.ax.legend(loc="upper right", facecolor=bg, labelcolor=fg)

        self.canvas = FigureCanvasTkAgg(self.fig, master=mid_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Mini path indicator (just a label for now)
        self.path_label = tk.Label(
            mid_frame, text="Pfad: [keine Bewegung]", font=("Helvetica", 10),
            fg=fg, bg=bg
        )
        self.path_label.pack(side=tk.BOTTOM, pady=2)

        # Bottom frame: event log
        bottom_frame = tk.Frame(self, bg=bg)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=5)

        log_label = tk.Label(bottom_frame, text="Ereignisprotokoll", font=("Helvetica", 12, "bold"),
                             fg=fg, bg=bg)
        log_label.pack(anchor=tk.W)

        self.log_text = scrolledtext.ScrolledText(
            bottom_frame, height=10, bg=list_bg, fg=list_fg,
            font=("Courier", 10), wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _process_queue(self):
        """Retrieve scan results from the BLE thread and update device states."""
        try:
            while True:
                timestamp, friendly, rssi = self.queue.get_nowait()
                self._update_device(timestamp, friendly, rssi)
        except queue.Empty:
            pass
        finally:
            self.after(self.update_interval, self._process_queue)

    def _update_device(self, timestamp: float, friendly: str, rssi: int):
        """Update device state with new scan data, check presence changes."""
        if friendly not in self.devices:
            self.devices[friendly] = DeviceState(friendly_name=friendly)

        dev = self.devices[friendly]
        raw_dist = distance_from_rssi(rssi)
        smoothed = exponential_smooth(raw_dist, dev.smoothed_distance)
        dev.smoothed_distance = smoothed
        dev.raw_rssi = rssi
        dev.last_seen = timestamp

        # Append to history for chart
        dev.history_times.append(timestamp)
        dev.history_distances.append(smoothed)

        # Determine current inside/outside with hysteresis
        low, high = ROOM_A_METER_RANGE
        inside_raw = low <= smoothed <= high

        # Apply hysteresis: if currently inside, require < low - HYSTERESIS to go out,
        # if outside, require > high + HYSTERESIS to go in.
        if dev.presence_inside:
            new_state = smoothed <= high + HYSTERESIS_MARGIN  # stay inside unless too high
        else:
            new_state = smoothed >= low - HYSTERESIS_MARGIN   # stay outside unless too low

        # Debounce: need N consecutive same state
        if new_state == dev.presence_inside:
            dev.debounce_counter = 0
        else:
            dev.debounce_counter += 1
            if dev.debounce_counter >= DEBOUNCE_COUNT:
                # State change confirmed
                old_state = dev.presence_inside
                dev.presence_inside = new_state
                dev.last_state_change = timestamp
                dev.debounce_counter = 0
                self._on_presence_change(dev, old_state, new_state, smoothed)

        # Update UI labels (always with latest data)
        self._refresh_labels(dev)

    def _on_presence_change(self, dev: DeviceState, old: bool, new: bool, dist: float):
        """Handle entry/exit events: log, beep, write CSV."""
        event_type = "BEREICHS_BETRETEN" if new else "BEREICHS_VERLASSEN"
        room = "Zimmer A"
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # Log to UI
        log_line = f"[{timestamp_str}] {dev.friendly_name}: {event_type} (Distanz: {dist:.2f} m)\n"
        self.log_text.insert(tk.END, log_line)
        self.log_text.see(tk.END)

        # Beep on Windows
        if sys.platform == "win32":
            frequency = 1000 if new else 500
            winsound.Beep(frequency, 300)

        # CSV logging
        if event_type == "BEREICHS_BETRETEN":
            self.csv_writer.writerow([
                timestamp_str, event_type, dev.friendly_name, room,
                f"{dist:.2f}", "", ""
            ])
        else:
            # For departure, compute duration and today's total
            # (simplified: we don't accumulate across multiple entries today)
            # In a real app you'd maintain a daily total per device.
            # Here we just write placeholder.
            self.csv_writer.writerow([
                timestamp_str, event_type, dev.friendly_name, room,
                f"{dist:.2f}", "", ""
            ])
        self.csv_file.flush()

    def _refresh_labels(self, dev: DeviceState):
        """Update top status labels."""
        status_text = "Anwesend" if dev.presence_inside else "Abwesend"
        self.status_label.config(text=f"Status: {status_text}")
        self.device_label.config(text=f"Gerät: {dev.friendly_name}")
        self.rssi_label.config(text=f"RSSI: {dev.raw_rssi} dBm")
        dist = dev.smoothed_distance
        if dist is not None:
            self.distance_label.config(text=f"Distanz: {dist:.2f} m")

    def _update_ui(self):
        """Periodic UI refresh: redraw chart, update path indicator."""
        # Find device with most recent data (or pick first)
        if self.devices:
            # Use the first device for simplicity (multi‑device not fully handled)
            dev = next(iter(self.devices.values()))
            times = list(dev.history_times)
            dists = list(dev.history_distances)
            if times and dists:
                # Convert to relative time (seconds ago)
                now = time.time()
                rel_times = [t - now for t in times]  # negative
                # Keep only last CHART_WINDOW_SEC
                cutoff = now - CHART_WINDOW_SEC
                filtered = [(rt, d) for rt, t, d in zip(rel_times, times, dists) if t >= cutoff]
                if filtered:
                    rel, filtered_dists = zip(*filtered)
                    self.line.set_data(rel, filtered_dists)
                    self.ax.relim()
                    self.ax.autoscale_view(scalex=True, scaley=True)
                    # Keep y limits reasonable
                    self.ax.set_ylim(0, max(10, max(filtered_dists) * 1.1))
                    # Update path indicator (simple: show last 3 distances)
                    if len(filtered_dists) >= 3:
                        last3 = filtered_dists[-3:]
                        trend = "↗️" if last3[-1] > last3[0] else "↘️" if last3[-1] < last3[0] else "➡️"
                        self.path_label.config(text=f"Pfad: {trend}  {last3[-1]:.2f} m")
                    self.canvas.draw()

        # Schedule next update
        self.after(2000, self._update_ui)

    def _on_close(self):
        """Clean shutdown: stop scanner, close CSV, close window."""
        self.scanner.stop()
        if self.csv_file:
            self.csv_file.close()
        self.destroy()
        sys.exit(0)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    app = PresenceApp()
    app.mainloop()


if __name__ == "__main__":
    main()
