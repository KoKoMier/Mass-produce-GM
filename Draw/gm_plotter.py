from __future__ import annotations

import csv
import queue
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import serial
from serial.tools import list_ports

import matplotlib
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


BAUD_RATE = 115200
DEFAULT_WINDOW_SECONDS = 120
MAX_POINTS = 3600
J305_USVH_PER_CPM = 0.00812037
J305_USVH_PER_CPS = 60.0 * J305_USVH_PER_CPM


@dataclass(frozen=True)
class Measurement:
    timestamp_ms: int
    ck1_cps: float
    ck2_cps: float
    ck3_cps: float
    adc1_mv: int
    adc2_mv: int
    adc3_mv: int

    @property
    def average_cps(self) -> float:
        return (self.ck1_cps + self.ck2_cps + self.ck3_cps) / 3.0

    @property
    def average_dose_usvh(self) -> float:
        return self.average_cps * J305_USVH_PER_CPS


def parse_measurement(line: str) -> Measurement | None:
    fields = line.strip().split(",")
    if len(fields) != 8 or fields[0] != "DATA":
        return None
    try:
        values = Measurement(
            timestamp_ms=int(fields[1]),
            ck1_cps=float(fields[2]),
            ck2_cps=float(fields[3]),
            ck3_cps=float(fields[4]),
            adc1_mv=int(fields[5]),
            adc2_mv=int(fields[6]),
            adc3_mv=int(fields[7]),
        )
    except ValueError:
        return None
    if values.timestamp_ms < 0 or min(values.adc1_mv, values.adc2_mv, values.adc3_mv) < 0:
        return None
    return values


def export_csv_to_excel(csv_path: Path) -> Path:
    """Convert one measurement CSV file to an Excel workbook with a CPS chart."""
    excel_path = csv_path.with_suffix(".xlsx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "GM measurements"

    headers = (
        "timestamp_ms", "ck1_cps", "ck2_cps", "ck3_cps", "average_cps",
        "average_dose_usvh", "adc1_mv", "adc2_mv", "adc3_mv",
    )
    sheet.append(headers)

    with csv_path.open("r", newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            ck1 = float(row["ck1_cps"])
            ck2 = float(row["ck2_cps"])
            ck3 = float(row["ck3_cps"])
            average_cps = (ck1 + ck2 + ck3) / 3.0
            sheet.append(
                (
                    int(row["timestamp_ms"]), ck1, ck2, ck3, average_cps,
                    average_cps * J305_USVH_PER_CPS,
                    int(row["adc1_mv"]), int(row["adc2_mv"]), int(row["adc3_mv"]),
                )
            )

    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    widths = (16, 12, 12, 12, 14, 22, 14, 14, 14)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2, min_col=2, max_col=6):
        for cell in row:
            cell.number_format = "0.0000"

    if sheet.max_row > 1:
        chart = LineChart()
        chart.title = "CK channels and average CPS"
        chart.y_axis.title = "CPS"
        chart.x_axis.title = "Timestamp (ms)"
        chart.height = 10
        chart.width = 22
        chart.add_data(
            Reference(sheet, min_col=2, max_col=5, min_row=1, max_row=sheet.max_row),
            titles_from_data=True,
        )
        chart.set_categories(
            Reference(sheet, min_col=1, min_row=2, max_row=sheet.max_row)
        )
        sheet.add_chart(chart, "K2")

    workbook.save(excel_path)
    return excel_path


class SerialReader(threading.Thread):
    def __init__(self, port: str, events: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.port = port
        self.events = events
        self.stop_event = stop_event

    def run(self) -> None:
        try:
            with serial.Serial(self.port, BAUD_RATE, timeout=0.2) as device:
                device.reset_input_buffer()
                self.events.put(("connected", self.port))
                while not self.stop_event.is_set():
                    raw = device.readline()
                    if not raw:
                        continue
                    line = raw.decode("ascii", errors="ignore")
                    measurement = parse_measurement(line)
                    if measurement is not None:
                        self.events.put(("measurement", measurement))
        except serial.SerialException as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("disconnected", self.port))


class PlotterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("GM 管实时监测")
        self.root.geometry("1100x760")
        self.root.minsize(820, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.reader: SerialReader | None = None
        self.connected = False
        self.recording = True
        self.csv_file = None
        self.csv_writer = None
        self.csv_path: Path | None = None

        self.timestamps_ms: deque[int] = deque(maxlen=MAX_POINTS)
        self.ck_values = [deque(maxlen=MAX_POINTS) for _ in range(3)]
        self.average_cps_values: deque[float] = deque(maxlen=MAX_POINTS)
        self.adc_values = [deque(maxlen=MAX_POINTS) for _ in range(3)]

        self.port_var = tk.StringVar()
        self.window_var = tk.StringVar(value=str(DEFAULT_WINDOW_SECONDS))
        self.status_var = tk.StringVar(value="未连接")
        self.sample_var = tk.StringVar(value="样本 0")
        self.value_vars = [tk.StringVar(value="--") for _ in range(9)]

        self._build_ui()
        self.refresh_ports()
        self.root.after(50, self._process_events)
        self.root.after(200, self._redraw)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        controls = ttk.Frame(outer)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="串口").grid(row=0, column=0, padx=(0, 6))
        self.port_box = ttk.Combobox(controls, textvariable=self.port_var, state="readonly", width=18)
        self.port_box.grid(row=0, column=1, sticky="w")
        ttk.Button(controls, text="刷新", command=self.refresh_ports).grid(row=0, column=2, padx=6)
        self.connect_button = ttk.Button(controls, text="连接", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=3, padx=(0, 16))

        ttk.Label(controls, text="显示窗口(s)").grid(row=0, column=4, padx=(0, 6))
        ttk.Entry(controls, textvariable=self.window_var, width=8).grid(row=0, column=5)
        ttk.Button(controls, text="清空", command=self.clear_data).grid(row=0, column=6, padx=6)
        ttk.Button(controls, text="选择记录目录", command=self.choose_log_directory).grid(row=0, column=7)

        values = ttk.Frame(outer)
        values.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        labels = (
            "时间(ms)", "CK1(CPS)", "CK2(CPS)", "CK3(CPS)", "平均(CPS)",
            "剂量率(μSv/h)", "ADC1(V)", "ADC2(V)", "ADC3(V)",
        )
        for index, (label, variable) in enumerate(zip(labels, self.value_vars)):
            values.columnconfigure(index, weight=1)
            cell = ttk.Frame(values, padding=(6, 2))
            cell.grid(row=0, column=index, sticky="ew")
            ttk.Label(cell, text=label).pack(anchor="center")
            ttk.Label(cell, textvariable=variable, font=("Segoe UI", 12, "bold")).pack(anchor="center")

        self.figure = Figure(figsize=(10, 6), dpi=100, constrained_layout=True)
        self.cps_ax = self.figure.add_subplot(211)
        self.voltage_ax = self.figure.add_subplot(212, sharex=self.cps_ax)
        self.cps_ax.set_ylabel("脉冲率 (CPS)")
        self.voltage_ax.set_ylabel("校准电压 (V)")
        self.voltage_ax.set_xlabel("设备运行时间 (s)")
        self.cps_ax.grid(True, alpha=0.25)
        self.voltage_ax.grid(True, alpha=0.25)

        colors = ("#0072B2", "#D55E00", "#009E73")
        self.cps_lines = [
            self.cps_ax.plot([], [], label=f"CK{i + 1}", color=colors[i], linewidth=1.5)[0]
            for i in range(3)
        ]
        self.average_cps_line = self.cps_ax.plot(
            [], [], label="平均", color="#202020", linewidth=2.4, linestyle="--"
        )[0]
        self.voltage_lines = [
            self.voltage_ax.plot([], [], label=f"ADC{i + 1}", color=colors[i], linewidth=1.5)[0]
            for i in range(3)
        ]
        self.cps_ax.legend(loc="upper left", ncol=4)
        self.voltage_ax.legend(loc="upper left", ncol=3)

        chart = ttk.Frame(outer)
        chart.grid(row=2, column=0, sticky="nsew")
        chart.rowconfigure(0, weight=1)
        chart.columnconfigure(0, weight=1)
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar = NavigationToolbar2Tk(self.canvas, chart, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        status = ttk.Frame(outer)
        status.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.sample_var).grid(row=0, column=1, sticky="e")

    def refresh_ports(self) -> None:
        ports = [port.device for port in list_ports.comports()]
        current = self.port_var.get()
        self.port_box["values"] = ports
        if current in ports:
            self.port_var.set(current)
        elif ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("")

    def toggle_connection(self) -> None:
        if self.reader and self.reader.is_alive():
            self.disconnect()
            return
        port = self.port_var.get()
        if not port:
            messagebox.showerror("串口错误", "没有选择串口")
            return
        self.stop_event.clear()
        self.reader = SerialReader(port, self.events, self.stop_event)
        self.reader.start()
        self.connect_button.configure(text="断开", state="disabled")
        self.status_var.set(f"正在连接 {port}...")

    def disconnect(self) -> None:
        self.stop_event.set()
        self.status_var.set("正在断开...")

    def choose_log_directory(self) -> None:
        selected = filedialog.askdirectory(title="选择 CSV 记录目录")
        if selected:
            self._close_log()
            self._open_log(Path(selected))

    def _open_log(self, directory: Path | None = None) -> None:
        directory = directory or (Path(__file__).resolve().parent / "logs")
        directory.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("gm_%Y%m%d_%H%M%S.csv")
        self.csv_path = directory / filename
        self.csv_file = self.csv_path.open("w", newline="", encoding="utf-8-sig")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(
            ("timestamp_ms", "ck1_cps", "ck2_cps", "ck3_cps", "average_cps",
             "average_dose_usvh", "adc1_mv", "adc2_mv", "adc3_mv")
        )
        self.csv_file.flush()

    def _close_log(self) -> None:
        if self.csv_file:
            self.csv_file.close()
            if self.csv_path and self.csv_path.stat().st_size > 0:
                try:
                    excel_path = export_csv_to_excel(self.csv_path)
                    self.status_var.set(f"Excel 已保存：{excel_path.name}")
                except (OSError, KeyError, ValueError) as exc:
                    self.status_var.set(f"Excel 导出失败：{exc}")
        self.csv_file = None
        self.csv_writer = None
        self.csv_path = None

    def _record(self, item: Measurement) -> None:
        if self.csv_writer is None:
            self._open_log()
        self.csv_writer.writerow(
            (item.timestamp_ms, item.ck1_cps, item.ck2_cps, item.ck3_cps,
             item.average_cps, item.average_dose_usvh,
             item.adc1_mv, item.adc2_mv, item.adc3_mv)
        )
        self.csv_file.flush()

    def _append(self, item: Measurement) -> None:
        self.timestamps_ms.append(item.timestamp_ms)
        for series, value in zip(self.ck_values, (item.ck1_cps, item.ck2_cps, item.ck3_cps)):
            series.append(value)
        self.average_cps_values.append(item.average_cps)
        for series, value in zip(self.adc_values, (item.adc1_mv, item.adc2_mv, item.adc3_mv)):
            series.append(value / 1000.0)
        self._record(item)

        latest = (
            str(item.timestamp_ms), f"{item.ck1_cps:.2f}", f"{item.ck2_cps:.2f}",
            f"{item.ck3_cps:.2f}", f"{item.average_cps:.2f}",
            f"{item.average_dose_usvh:.3f}", f"{item.adc1_mv / 1000:.3f}",
            f"{item.adc2_mv / 1000:.3f}", f"{item.adc3_mv / 1000:.3f}"
        )
        for variable, value in zip(self.value_vars, latest):
            variable.set(value)
        self.sample_var.set(f"样本 {len(self.timestamps_ms)}")

    def _process_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "measurement":
                    self._append(value)
                elif kind == "connected":
                    self.connected = True
                    self.connect_button.configure(text="断开", state="normal")
                    self.status_var.set(f"已连接 {value}，{BAUD_RATE} 8N1")
                elif kind == "error":
                    messagebox.showerror("串口错误", str(value))
                    self.status_var.set(f"串口错误：{value}")
                elif kind == "disconnected":
                    self.connected = False
                    self.connect_button.configure(text="连接", state="normal")
                    if not self.status_var.get().startswith("串口错误"):
                        self.status_var.set("未连接")
        except queue.Empty:
            pass
        self.root.after(50, self._process_events)

    def _redraw(self) -> None:
        if self.timestamps_ms:
            x_values = [value / 1000.0 for value in self.timestamps_ms]
            for line, values in zip(self.cps_lines, self.ck_values):
                line.set_data(x_values, values)
            self.average_cps_line.set_data(x_values, self.average_cps_values)
            for line, values in zip(self.voltage_lines, self.adc_values):
                line.set_data(x_values, values)

            try:
                window = max(1.0, float(self.window_var.get()))
            except ValueError:
                window = DEFAULT_WINDOW_SECONDS
            right = x_values[-1]
            left = max(x_values[0], right - window)
            if right <= left:
                right = left + 1.0
            self.cps_ax.set_xlim(left, right)
            self.voltage_ax.set_xlim(left, right)
            for axis in (self.cps_ax, self.voltage_ax):
                axis.relim()
                axis.autoscale_view(scalex=False, scaley=True)
            self.canvas.draw_idle()
        self.root.after(200, self._redraw)

    def clear_data(self) -> None:
        self.timestamps_ms.clear()
        self.average_cps_values.clear()
        for values in self.ck_values + self.adc_values:
            values.clear()
        for variable in self.value_vars:
            variable.set("--")
        self.sample_var.set("样本 0")
        for line in self.cps_lines + self.voltage_lines + [self.average_cps_line]:
            line.set_data([], [])
        self.canvas.draw_idle()

    def close(self) -> None:
        self.stop_event.set()
        self._close_log()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    PlotterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
