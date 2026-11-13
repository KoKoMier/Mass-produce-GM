from __future__ import annotations

import os
import queue
import struct
import threading
import zlib
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import serial
from serial.tools import list_ports

from protocol import BootloaderClient, ProtocolError, UpgradeCancelled


APP_START = 0x08004000
APP_END = 0x08010000
SRAM_START = 0x20000000
SRAM_END = 0x20005000
MAX_FIRMWARE_SIZE = 48 * 1024
CHUNK_SIZE = 256


def validate_firmware(data: bytes) -> tuple[int, int]:
    if len(data) < 8:
        raise ValueError("固件长度不足 8 字节")
    if len(data) > MAX_FIRMWARE_SIZE:
        raise ValueError(f"固件超过 48 KB：{len(data)} 字节")

    stack_pointer, reset_handler = struct.unpack_from("<II", data)
    reset_address = reset_handler & ~1
    if not (SRAM_START <= stack_pointer <= SRAM_END):
        raise ValueError(f"初始栈地址无效：0x{stack_pointer:08X}")
    if (reset_handler & 1) == 0 or not (APP_START <= reset_address < APP_END):
        raise ValueError(
            f"复位入口 0x{reset_handler:08X} 不在 Application 分区，"
            "请确认固件链接地址为 0x08004000"
        )
    return stack_pointer, reset_handler


class FlasherWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("GM 管固件升级")
        self.root.geometry("720x520")
        self.root.minsize(640, 460)

        base_dir = Path(__file__).resolve().parent
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.file_var = tk.StringVar(value=str(base_dir / "firmware.bin"))
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self.refresh_ports()
        self.root.after(50, self._process_events)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="串口").grid(row=0, column=0, sticky="w", pady=5)
        self.port_box = ttk.Combobox(frame, textvariable=self.port_var, state="readonly")
        self.port_box.grid(row=0, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(frame, text="刷新", command=self.refresh_ports).grid(row=0, column=2, pady=5)

        ttk.Label(frame, text="波特率").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Combobox(
            frame,
            textvariable=self.baud_var,
            values=("9600", "19200", "57600", "115200"),
            state="readonly",
            width=14,
        ).grid(row=1, column=1, sticky="w", padx=8, pady=5)

        ttk.Label(frame, text="固件").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.file_var).grid(row=2, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(frame, text="选择", command=self.choose_file).grid(row=2, column=2, pady=5)

        action = ttk.Frame(frame)
        action.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        action.columnconfigure(0, weight=1)
        self.start_button = ttk.Button(action, text="开始升级", command=self.start_upgrade)
        self.start_button.grid(row=0, column=0, sticky="e", padx=4)
        self.cancel_button = ttk.Button(action, text="取消", command=self.cancel_upgrade, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=4)

        progress = ttk.Progressbar(frame, variable=self.progress_var, maximum=100.0)
        progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 6))

        self.log = scrolledtext.ScrolledText(frame, height=14, state="disabled", wrap=tk.WORD)
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew")

        ttk.Label(frame, textvariable=self.status_var, anchor="w").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(7, 0)
        )

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

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 Application 固件",
            initialdir=str(Path(self.file_var.get()).parent),
            filetypes=(("Binary firmware", "*.bin"), ("All files", "*.*")),
        )
        if path:
            self.file_var.set(path)

    def _emit(self, kind: str, value: object) -> None:
        self.events.put((kind, value))

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(tk.END, text + os.linesep)
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def start_upgrade(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        port = self.port_var.get().strip()
        path = Path(self.file_var.get()).expanduser()
        if not port:
            messagebox.showerror("串口错误", "没有选择可用串口")
            return
        try:
            baud = int(self.baud_var.get())
            data = path.read_bytes()
            stack_pointer, reset_handler = validate_firmware(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("固件错误", str(exc))
            return

        crc32 = zlib.crc32(data) & 0xFFFFFFFF
        self.cancel_event.clear()
        self.progress_var.set(0.0)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._append_log(f"文件：{path}")
        self._append_log(f"大小：{len(data)} 字节，CRC32：0x{crc32:08X}")
        self._append_log(f"MSP：0x{stack_pointer:08X}，入口：0x{reset_handler:08X}")
        self.worker = threading.Thread(
            target=self._upgrade_worker,
            args=(port, baud, data, crc32),
            daemon=True,
        )
        self.worker.start()

    def cancel_upgrade(self) -> None:
        self.cancel_event.set()
        self.status_var.set("正在取消...")

    def _upgrade_worker(self, port: str, baud: int, data: bytes, crc32: int) -> None:
        try:
            with serial.Serial(port, baud, timeout=0.05, write_timeout=2.0) as device:
                client = BootloaderClient(device, self.cancel_event.is_set)
                self._emit("status", "等待 Bootloader，请复位设备")
                client.wait_for_bootloader(len(data), crc32)
                self._emit("log", "Bootloader 已连接")

                self._emit("status", "正在擦除 W25Q64 固件区")
                client.erase()
                self._emit("log", "外部 Flash 擦除完成")

                self._emit("status", "正在发送固件")
                for offset in range(0, len(data), CHUNK_SIZE):
                    chunk = data[offset : offset + CHUNK_SIZE]
                    next_offset = client.write_chunk(offset, chunk)
                    self._emit("progress", next_offset * 100.0 / len(data))
                self._emit("log", "固件数据发送完成")

                self._emit("status", "正在执行整包 CRC32 校验")
                client.finish(crc32)
                self._emit("log", "设备端 CRC32 校验通过")

                self._emit("status", "正在激活固件")
                client.activate()
                self._emit("progress", 100.0)
                self._emit("done", "升级完成，设备正在安装并重启")
        except UpgradeCancelled:
            self._emit("cancelled", "升级已取消")
        except (OSError, serial.SerialException, ProtocolError) as exc:
            self._emit("error", str(exc))
        except Exception as exc:
            self._emit("error", f"未预期错误：{exc}")

    def _process_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(value))
                elif kind == "status":
                    self.status_var.set(str(value))
                elif kind == "progress":
                    self.progress_var.set(float(value))
                elif kind == "done":
                    self._finish_ui(str(value))
                    messagebox.showinfo("升级完成", str(value))
                elif kind == "cancelled":
                    self._finish_ui(str(value))
                elif kind == "error":
                    self._finish_ui("升级失败")
                    self._append_log(f"错误：{value}")
                    messagebox.showerror("升级失败", str(value))
        except queue.Empty:
            pass
        self.root.after(50, self._process_events)

    def _finish_ui(self, status: str) -> None:
        self.status_var.set(status)
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    FlasherWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
