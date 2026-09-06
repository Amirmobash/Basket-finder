#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BLE presence/range monitor with Tkinter UI.

This application scans for configured BLE advertising names, estimates distance
from RSSI, applies smoothing + hysteresis + debounce, logs enter/leave events to
CSV, and displays a short history chart.

Important:
    RSSI-based distance is only an approximation. It is strongly affected by
    antenna orientation, walls, people, reflections, interference, and device
    transmit power. Do not use this software as the sole basis for safety-
    critical, access-control, or life-safety decisions.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import logging
import math
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Optional

from bleak import BleakScanner
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import scrolledtext


LOGGER = logging.getLogger("ble_presence")

DEFAULT_SCAN_WINDOW_SEC: Final[float] = 5.0
DEFAULT_SCAN_INTERVAL_SEC: Final[float] = 5.0
DEFAULT_STALE_TIMEOUT_SEC: Final[float] = 20.0

ROOM_A_METER_RANGE: Final[tuple[float, float]] = (1.0, 5.0)
HYSTERESIS_MARGIN_M: Final[float] = 0.5
DEBOUNCE_COUNT: Final[int] = 2
SMOOTHING_FACTOR: Final[float] = 0.3

TX_POWER_1M_DBM: Final[int] = -59
PATH_LOSS_EXPONENT: Final[float] = 2.5

DEFAULT_CSV_LOG_PATH: Final[str] = "ble_events.csv"
DEFAULT_CHART_WINDOW_SEC: Final[int] = 180
DEFAULT_HISTORY_POINTS: Final[int] = 600

# Substring match against BLE advertised local name.
NAME_TARGETS: Final[dict[str, str]] = {
    "ITAG": "Basket-1",
}


@dataclass(frozen=True)
class AppConfig:
    scan_window_sec: float = DEFAULT_SCAN_WINDOW_SEC
    scan_interval_sec: float = DEFAULT_SCAN_INTERVAL_SEC
    stale_timeout_sec: float = DEFAULT_STALE_TIMEOUT_SEC
    room_range_m: tuple[float, float] = ROOM_A_METER_RANGE
    hysteresis_margin_m: float = HYSTERESIS_MARGIN_M
    debounce_count: int = DEBOUNCE_COUNT
    smoothing_factor: float = SMOOTHING_FACTOR
    tx_power_1m_dbm: int = TX_POWER_1M_DBM
    path_loss_exponent: float = PATH_LOSS_EXPONENT
    csv_log_path: Path = Path(DEFAULT_CSV_LOG_PATH)
    chart_window_sec: int = DEFAULT_CHART_WINDOW_SEC
    history_points: int = DEFAULT_HISTORY_POINTS

    def validate(self) -> None:
        low, high = self.room_range_m

        if self.scan_window_sec <= 0:
            raise ValueError("scan_window_sec must be > 0")
        if self.scan_interval_sec < 0:
            raise ValueError("scan_interval_sec must be >= 0")
        if self.stale_timeout_sec <= 0:
            raise ValueError("stale_timeout_sec must be > 0")
        if not (0 <= low < high):
            raise ValueError("room_range_m must satisfy 0 <= low < high")
        if self.hysteresis_margin_m < 0:
            raise ValueError("hysteresis_margin_m must be >= 0")
        if self.debounce_count < 1:
            raise ValueError("debounce_count must be >= 1")
        if not 0 < self.smoothing_factor <= 1:
            raise ValueError("smoothing_factor must be in (0, 1]")
        if self.path_loss_exponent <= 0:
            raise ValueError("path_loss_exponent must be > 0")
        if self.chart_window_sec <= 0:
            raise ValueError("chart_window_sec must be > 0")
        if self.history_points < 10:
            raise ValueError("history_points must be >= 10")


@dataclass(frozen=True)
class ScanResult:
    timestamp: float
    address: str
    friendly_name: str
    advertised_name: str
    rssi: int


@dataclass
class DeviceState:
    address: str
    friendly_name: str
    advertised_name: str
    last_seen: float = 0.0
    raw_rssi: int = -100
    smoothed_distance_m: Optional[float] = None
    presence_inside: bool = False
    debounce_target: Optional[bool] = None
    debounce_counter: int = 0
    last_state_change: float = 0.0
    entry_started_at: Optional[float] = None
    total_inside_today_s: float = 0.0
    total_date: Optional[dt.date] = None
    history_times: deque[float] = field(default_factory=deque)
    history_distances: deque[float] = field(default_factory=deque)

    def reset_daily_total_if_needed(self, today: dt.date) -> None:
        if self.total_date != today:
            self.total_date = today
            self.total_inside_today_s = 0.0


def distance_from_rssi(
    rssi: int,
    *,
    tx_power_1m_dbm: int,
    path_loss_exponent: float,
) -> float:
    """
    Estimate distance from RSSI using a log-distance path-loss model.

    This is an approximation, not a physical ranging measurement.
    """
    if rssi == 0:
        return math.inf

    exponent = (tx_power_1m_dbm - rssi) / (10.0 * path_loss_exponent)
    return 10.0 ** exponent


def exponential_smooth(
    new_value: float,
    old_value: Optional[float],
    *,
    alpha: float,
) -> float:
    if old_value is None or not math.isfinite(old_value):
        return new_value
    return alpha * new_value + (1.0 - alpha) * old_value


def target_state_for_distance(
    distance_m: float,
    *,
    currently_inside: bool,
    room_range_m: tuple[float, float],
    hysteresis_margin_m: float,
) -> bool:
    """
    Apply band hysteresis.

    Enter only when inside the nominal [low, high] band.
    Once inside, remain inside until leaving the expanded
    [low-margin, high+margin] band.
    """
    low, high = room_range_m

    if currently_inside:
        return (low - hysteresis_margin_m) <= distance_m <= (
            high + hysteresis_margin_m
        )

    return low <= distance_m <= high


class BLEScannerThread(threading.Thread):
    def __init__(
        self,
        result_queue: "queue.Queue[ScanResult]",
        config: AppConfig,
    ) -> None:
        super().__init__(name="ble-scanner", daemon=True)
        self._result_queue = result_queue
        self._config = config
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            asyncio.run(self._scan_loop())
        except Exception:
            LOGGER.exception("BLE scanner thread terminated unexpectedly")

    async def _scan_loop(self) -> None:
        while not self._stop_event.is_set():
            cycle_started = time.monotonic()

            try:
                discovered = await BleakScanner.discover(
                    timeout=self._config.scan_window_sec,
                    return_adv=True,
                )
                now = time.time()

                for address, pair in discovered.items():
                    _, adv_data = pair
                    local_name = (adv_data.local_name or "").strip()
                    if not local_name:
                        continue

                    friendly = self._match_target(local_name)
                    if friendly is None:
                        continue

                    rssi = int(adv_data.rssi)
                    result = ScanResult(
                        timestamp=now,
                        address=address,
                        friendly_name=friendly,
                        advertised_name=local_name,
                        rssi=rssi,
                    )
                    self._put_latest(result)

            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("BLE scan failed")

            elapsed = time.monotonic() - cycle_started
            sleep_for = max(0.0, self._config.scan_interval_sec - elapsed)
            if sleep_for > 0:
                await asyncio.to_thread(self._stop_event.wait, sleep_for)

    @staticmethod
    def _match_target(local_name: str) -> Optional[str]:
        lower_name = local_name.casefold()
        for target, friendly in NAME_TARGETS.items():
            if target.casefold() in lower_name:
                return friendly
        return None

    def _put_latest(self, result: ScanResult) -> None:
        try:
            self._result_queue.put_nowait(result)
        except queue.Full:
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self._result_queue.put_nowait(result)
            except queue.Full:
                LOGGER.warning("Dropping BLE result because UI queue is full")


class PresenceApp(tk.Tk):
    PROCESS_INTERVAL_MS: Final[int] = 250
    UI_INTERVAL_MS: Final[int] = 1000

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config_data = config
        self.config_data.validate()

        self.title("Basket Finder Radar – Zimmer A")
        self.geometry("1200x700")
        self.minsize(900, 600)

        self._closing = False
        self._after_ids: set[str] = set()

        self.devices: dict[str, DeviceState] = {}
        self.selected_address: Optional[str] = None

        self.result_queue: "queue.Queue[ScanResult]" = queue.Queue(maxsize=500)
        self.scanner = BLEScannerThread(self.result_queue, self.config_data)

        self.csv_file = None
        self.csv_writer = None

        self._init_csv()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.scanner.start()

        self._schedule(self.PROCESS_INTERVAL_MS, self._process_queue)
        self._schedule(self.UI_INTERVAL_MS, self._update_ui)

    def _schedule(self, delay_ms: int, callback) -> None:
        if self._closing:
            return

        after_id: Optional[str] = None

        def wrapped() -> None:
            if after_id is not None:
                self._after_ids.discard(after_id)
            if not self._closing:
                callback()

        after_id = self.after(delay_ms, wrapped)
        self._after_ids.add(after_id)

    def _init_csv(self) -> None:
        path = self.config_data.csv_log_path
        path.parent.mkdir(parents=True, exist_ok=True)

        file_exists = path.is_file() and path.stat().st_size > 0
        self.csv_file = path.open("a", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)

        if not file_exists:
            self.csv_writer.writerow(
                [
                    "timestamp",
                    "event",
                    "device",
                    "room",
                    "distance_m",
                    "duration_s",
                    "total_today_s",
                ]
            )
            self.csv_file.flush()

    def _build_ui(self) -> None:
        bg = "#2b2b2b"
        fg = "#ff8c00"
        list_bg = "#3c3c3c"
        list_fg = "#ffa500"

        self.configure(bg=bg)

        top_frame = tk.Frame(self, bg=bg)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.status_label = tk.Label(
            top_frame,
            text="Status: Unbekannt",
            font=("Helvetica", 16, "bold"),
            fg=fg,
            bg=bg,
        )
        self.status_label.pack(side=tk.LEFT, padx=10)

        self.device_label = tk.Label(
            top_frame,
            text="Gerät: —",
            font=("Helvetica", 14),
            fg=fg,
            bg=bg,
        )
        self.device_label.pack(side=tk.LEFT, padx=20)

        self.rssi_label = tk.Label(
            top_frame,
            text="RSSI: —",
            font=("Helvetica", 14),
            fg=fg,
            bg=bg,
        )
        self.rssi_label.pack(side=tk.LEFT, padx=20)

        self.distance_label = tk.Label(
            top_frame,
            text="Distanz: — m",
            font=("Helvetica", 14),
            fg=fg,
            bg=bg,
        )
        self.distance_label.pack(side=tk.LEFT, padx=20)

        mid_frame = tk.Frame(self, bg=bg)
        mid_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.fig, self.ax = plt.subplots(figsize=(8, 3), dpi=100)
        self.fig.patch.set_facecolor(bg)
        self.ax.set_facecolor("#3c3c3c")
        self.ax.tick_params(colors=fg)
        for spine in self.ax.spines.values():
            spine.set_color(fg)
        self.ax.xaxis.label.set_color(fg)
        self.ax.yaxis.label.set_color(fg)
        self.ax.set_xlabel("Zeit relativ zu jetzt (s)")
        self.ax.set_ylabel("Geschätzte Distanz (m)")

        low, high = self.config_data.room_range_m
        self.ax.axhspan(low, high, alpha=0.3, label="Zimmer A")
        (self.line,) = self.ax.plot([], [], linewidth=2)
        self.ax.legend(loc="upper right")

        self.canvas = FigureCanvasTkAgg(self.fig, master=mid_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.path_label = tk.Label(
            mid_frame,
            text="Pfad: [keine Bewegung]",
            font=("Helvetica", 10),
            fg=fg,
            bg=bg,
        )
        self.path_label.pack(side=tk.BOTTOM, pady=2)

        bottom_frame = tk.Frame(self, bg=bg)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=5)

        log_label = tk.Label(
            bottom_frame,
            text="Ereignisprotokoll",
            font=("Helvetica", 12, "bold"),
            fg=fg,
            bg=bg,
        )
        log_label.pack(anchor=tk.W)

        self.log_text = scrolledtext.ScrolledText(
            bottom_frame,
            height=10,
            bg=list_bg,
            fg=list_fg,
            font=("Courier", 10),
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _process_queue(self) -> None:
        processed = 0
        while processed < 500:
            try:
                result = self.result_queue.get_nowait()
            except queue.Empty:
                break

            self._update_device(result)
            processed += 1

        self._mark_stale_devices(time.time())
        self._schedule(self.PROCESS_INTERVAL_MS, self._process_queue)

    def _get_or_create_device(self, result: ScanResult) -> DeviceState:
        dev = self.devices.get(result.address)
        if dev is None:
            dev = DeviceState(
                address=result.address,
                friendly_name=result.friendly_name,
                advertised_name=result.advertised_name,
                history_times=deque(maxlen=self.config_data.history_points),
                history_distances=deque(maxlen=self.config_data.history_points),
            )
            self.devices[result.address] = dev
        return dev

    def _update_device(self, result: ScanResult) -> None:
        dev = self._get_or_create_device(result)

        raw_distance = distance_from_rssi(
            result.rssi,
            tx_power_1m_dbm=self.config_data.tx_power_1m_dbm,
            path_loss_exponent=self.config_data.path_loss_exponent,
        )
        if not math.isfinite(raw_distance):
            LOGGER.warning(
                "Ignoring invalid distance for %s (%s): RSSI=%s",
                dev.friendly_name,
                dev.address,
                result.rssi,
            )
            return

        smoothed = exponential_smooth(
            raw_distance,
            dev.smoothed_distance_m,
            alpha=self.config_data.smoothing_factor,
        )

        dev.smoothed_distance_m = smoothed
        dev.raw_rssi = result.rssi
        dev.last_seen = result.timestamp
        dev.advertised_name = result.advertised_name
        dev.history_times.append(result.timestamp)
        dev.history_distances.append(smoothed)

        desired_state = target_state_for_distance(
            smoothed,
            currently_inside=dev.presence_inside,
            room_range_m=self.config_data.room_range_m,
            hysteresis_margin_m=self.config_data.hysteresis_margin_m,
        )

        self._apply_debounce(dev, desired_state, result.timestamp, smoothed)
        self._select_most_recent_device()
        if self.selected_address == dev.address:
            self._refresh_labels(dev)

    def _apply_debounce(
        self,
        dev: DeviceState,
        desired_state: bool,
        timestamp: float,
        distance_m: float,
    ) -> None:
        if desired_state == dev.presence_inside:
            dev.debounce_target = None
            dev.debounce_counter = 0
            return

        if dev.debounce_target != desired_state:
            dev.debounce_target = desired_state
            dev.debounce_counter = 1
        else:
            dev.debounce_counter += 1

        if dev.debounce_counter < self.config_data.debounce_count:
            return

        old_state = dev.presence_inside
        dev.presence_inside = desired_state
        dev.last_state_change = timestamp
        dev.debounce_target = None
        dev.debounce_counter = 0

        self._on_presence_change(
            dev,
            old_state,
            desired_state,
            distance_m,
            timestamp,
            stale=False,
        )

    def _mark_stale_devices(self, now: float) -> None:
        changed = False

        for dev in self.devices.values():
            if dev.last_seen <= 0:
                continue
            if now - dev.last_seen <= self.config_data.stale_timeout_sec:
                continue

            if dev.presence_inside:
                old_state = dev.presence_inside
                dev.presence_inside = False
                dev.debounce_target = None
                dev.debounce_counter = 0
                dev.last_state_change = now

                self._on_presence_change(
                    dev,
                    old_state,
                    False,
                    dev.smoothed_distance_m or math.nan,
                    now,
                    stale=True,
                )
                changed = True

        if changed:
            self._select_most_recent_device()

        if self.selected_address:
            selected = self.devices.get(self.selected_address)
            if selected:
                self._refresh_labels(selected)

    def _on_presence_change(
        self,
        dev: DeviceState,
        old_state: bool,
        new_state: bool,
        distance_m: float,
        timestamp: float,
        *,
        stale: bool,
    ) -> None:
        del old_state

        now_dt = dt.datetime.fromtimestamp(timestamp)
        dev.reset_daily_total_if_needed(now_dt.date())

        event_type = "BEREICHS_BETRETEN" if new_state else "BEREICHS_VERLASSEN"
        if stale and not new_state:
            event_type = "SIGNAL_VERLOREN"

        duration_s = 0.0
        if new_state:
            dev.entry_started_at = timestamp
        elif dev.entry_started_at is not None:
            duration_s = max(0.0, timestamp - dev.entry_started_at)
            dev.total_inside_today_s += duration_s
            dev.entry_started_at = None

        timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        if math.isfinite(distance_m):
            dist_text = f"{distance_m:.2f} m"
            csv_dist = f"{distance_m:.2f}"
        else:
            dist_text = "unbekannt"
            csv_dist = ""

        log_line = (
            f"[{timestamp_str}] {dev.friendly_name} "
            f"({dev.advertised_name}, {dev.address}): "
            f"{event_type} (Distanz: {dist_text})\n"
        )
        self._append_log(log_line)
        self._beep(new_state)

        if self.csv_writer is not None and self.csv_file is not None:
            self.csv_writer.writerow(
                [
                    timestamp_str,
                    event_type,
                    dev.friendly_name,
                    "Zimmer A",
                    csv_dist,
                    f"{duration_s:.1f}" if duration_s > 0 else "",
                    f"{dev.total_inside_today_s:.1f}",
                ]
            )
            self.csv_file.flush()

    def _beep(self, entering: bool) -> None:
        if sys.platform == "win32":
            try:
                import winsound

                winsound.Beep(1000 if entering else 500, 300)
                return
            except Exception:
                LOGGER.exception("Windows beep failed")

        try:
            self.bell()
        except tk.TclError:
            LOGGER.debug("Tk bell unavailable", exc_info=True)

    def _select_most_recent_device(self) -> None:
        if not self.devices:
            self.selected_address = None
            return

        selected = max(self.devices.values(), key=lambda dev: dev.last_seen)
        self.selected_address = selected.address

    def _refresh_labels(self, dev: DeviceState) -> None:
        age = time.time() - dev.last_seen if dev.last_seen > 0 else math.inf

        if age > self.config_data.stale_timeout_sec:
            status_text = "Signal verloren"
        else:
            status_text = "Anwesend" if dev.presence_inside else "Abwesend"

        self.status_label.config(text=f"Status: {status_text}")
        self.device_label.config(text=f"Gerät: {dev.friendly_name}")
        self.rssi_label.config(text=f"RSSI: {dev.raw_rssi} dBm")

        if dev.smoothed_distance_m is None:
            self.distance_label.config(text="Distanz: — m")
        else:
            self.distance_label.config(
                text=f"Distanz: {dev.smoothed_distance_m:.2f} m (Schätzung)"
            )

    def _update_ui(self) -> None:
        self._select_most_recent_device()

        if self.selected_address is not None:
            dev = self.devices.get(self.selected_address)
            if dev is not None:
                self._refresh_labels(dev)
                self._update_chart(dev)

        self._schedule(self.UI_INTERVAL_MS, self._update_ui)

    def _update_chart(self, dev: DeviceState) -> None:
        times = list(dev.history_times)
        distances = list(dev.history_distances)

        if not times or not distances:
            self.line.set_data([], [])
            self.path_label.config(text="Pfad: [keine Bewegung]")
            self.canvas.draw_idle()
            return

        now = time.time()
        cutoff = now - self.config_data.chart_window_sec

        filtered = [
            (timestamp - now, distance)
            for timestamp, distance in zip(times, distances)
            if timestamp >= cutoff
        ]

        if not filtered:
            self.line.set_data([], [])
            self.path_label.config(text="Pfad: [keine aktuellen Daten]")
            self.canvas.draw_idle()
            return

        rel_times, filtered_distances = zip(*filtered)
        self.line.set_data(rel_times, filtered_distances)
        self.ax.set_xlim(-self.config_data.chart_window_sec, 0)
        self.ax.set_ylim(0, max(10.0, max(filtered_distances) * 1.1))

        if len(filtered_distances) >= 3:
            first = filtered_distances[-3]
            last = filtered_distances[-1]
            delta = last - first

            if abs(delta) < 0.05:
                trend = "➡️"
            elif delta > 0:
                trend = "↗️"
            else:
                trend = "↘️"

            self.path_label.config(
                text=f"Pfad: {trend} {last:.2f} m (Schätzung)"
            )
        else:
            self.path_label.config(
                text=(
                    f"Pfad: {filtered_distances[-1]:.2f} m "
                    "(zu wenig Daten für Trend)"
                )
            )

        self.canvas.draw_idle()

    def _on_close(self) -> None:
        if self._closing:
            return

        self._closing = True

        for after_id in list(self._after_ids):
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        self._after_ids.clear()

        self.scanner.stop()
        self.scanner.join(timeout=self.config_data.scan_window_sec + 1.0)
        if self.scanner.is_alive():
            LOGGER.warning("BLE scanner did not stop before timeout")

        if self.csv_file is not None:
            try:
                self.csv_file.flush()
                self.csv_file.close()
            except OSError:
                LOGGER.exception("Failed to close CSV log")

        try:
            plt.close(self.fig)
        except Exception:
            LOGGER.debug("Matplotlib figure close failed", exc_info=True)

        self.destroy()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "BLE RSSI-based presence/range monitor. "
            "Distance values are estimates."
        )
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(DEFAULT_CSV_LOG_PATH),
        help=f"CSV event log path (default: {DEFAULT_CSV_LOG_PATH})",
    )
    parser.add_argument(
        "--scan-window",
        type=float,
        default=DEFAULT_SCAN_WINDOW_SEC,
        help="BLE scan duration in seconds",
    )
    parser.add_argument(
        "--scan-interval",
        type=float,
        default=DEFAULT_SCAN_INTERVAL_SEC,
        help="Target time between the start of scan cycles in seconds",
    )
    parser.add_argument(
        "--stale-timeout",
        type=float,
        default=DEFAULT_STALE_TIMEOUT_SEC,
        help=(
            "Mark an inside device as lost after this many seconds "
            "without an advertisement"
        ),
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format=(
            "%(asctime)s %(levelname)s "
            "%(threadName)s %(name)s: %(message)s"
        ),
    )

    config = AppConfig(
        scan_window_sec=args.scan_window,
        scan_interval_sec=args.scan_interval,
        stale_timeout_sec=args.stale_timeout,
        csv_log_path=args.csv,
    )

    try:
        config.validate()
    except ValueError as exc:
        LOGGER.error("Invalid configuration: %s", exc)
        return 2

    try:
        app = PresenceApp(config)
        app.mainloop()
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
        return 130
    except (tk.TclError, OSError):
        LOGGER.exception("Application failed to start or run")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
