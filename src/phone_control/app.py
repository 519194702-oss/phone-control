"""Tkinter desktop application for Android screen mirroring and control."""

from __future__ import annotations

import base64
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from .adb import AdbClient, AdbError, AndroidDevice

REFRESH_SECONDS = 0.45
MAX_DISPLAY_WIDTH = 900
MAX_DISPLAY_HEIGHT = 900
DRAG_AS_SWIPE_THRESHOLD = 12

KEY_EVENTS = {
    "Escape": "BACK",
    "BackSpace": "DEL",
    "Return": "ENTER",
    "Home": "HOME",
    "Tab": "TAB",
    "Up": "DPAD_UP",
    "Down": "DPAD_DOWN",
    "Left": "DPAD_LEFT",
    "Right": "DPAD_RIGHT",
    "F5": "APP_SWITCH",
}


@dataclass(frozen=True)
class DisplayTransform:
    """Maps displayed canvas coordinates back to Android screen coordinates."""

    screen_width: int
    screen_height: int
    scale_divisor: int = 1

    @property
    def display_width(self) -> int:
        return max(1, self.screen_width // self.scale_divisor)

    @property
    def display_height(self) -> int:
        return max(1, self.screen_height // self.scale_divisor)

    @classmethod
    def fit(cls, screen_width: int, screen_height: int, max_width: int, max_height: int) -> "DisplayTransform":
        divisor = 1
        while screen_width // divisor > max_width or screen_height // divisor > max_height:
            divisor += 1
        return cls(screen_width=screen_width, screen_height=screen_height, scale_divisor=divisor)

    def to_device(self, canvas_x: float, canvas_y: float) -> tuple[int, int]:
        x = round(canvas_x * self.scale_divisor)
        y = round(canvas_y * self.scale_divisor)
        return min(max(x, 0), self.screen_width - 1), min(max(y, 0), self.screen_height - 1)


class PhoneControlApp(tk.Tk):
    """Desktop UI that mirrors an Android screen and forwards input events."""

    def __init__(self, adb: AdbClient | None = None) -> None:
        super().__init__()
        self.title("Phone Control - Android ADB Mirror")
        self.minsize(720, 520)

        self.adb = adb or AdbClient()
        self.device_adb: AdbClient | None = None
        self.devices: list[AndroidDevice] = []
        self.transform: DisplayTransform | None = None
        self.current_image: tk.PhotoImage | None = None
        self.stop_event = threading.Event()
        self.frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=2)
        self.status_var = tk.StringVar(value="请连接 Android 手机并启用 USB 调试。")
        self.device_var = tk.StringVar()
        self.drag_start: tuple[int, int, float] | None = None
        self.mirror_thread: threading.Thread | None = None

        self._build_ui()
        self.refresh_devices()
        self.after(80, self._consume_frames)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(root)
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="设备：").pack(side=tk.LEFT)
        self.device_combo = ttk.Combobox(toolbar, textvariable=self.device_var, state="readonly", width=55)
        self.device_combo.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(toolbar, text="刷新设备", command=self.refresh_devices).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="开始投屏", command=self.start_mirroring).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="停止", command=self.stop_mirroring).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="返回", command=lambda: self._send_key("BACK")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="主页", command=lambda: self._send_key("HOME")).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="多任务", command=lambda: self._send_key("APP_SWITCH")).pack(side=tk.LEFT, padx=2)

        self.canvas = tk.Canvas(root, bg="#161b22", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=10)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Key>", self._on_key)
        self.canvas.bind("<FocusIn>", lambda _event: self.status_var.set("已聚焦投屏窗口，可用鼠标点击/拖动或键盘输入。"))

        ttk.Label(root, textvariable=self.status_var, anchor="w").pack(fill=tk.X)

        help_text = (
            "提示：点击=手机点击，拖动=手机滑动；Esc=返回，Enter=确认，Backspace=删除，"
            "方向键=DPAD，F5=多任务。"
        )
        ttk.Label(root, text=help_text, anchor="w", foreground="#555").pack(fill=tk.X, pady=(4, 0))

    def refresh_devices(self) -> None:
        try:
            self.devices = self.adb.devices()
        except AdbError as exc:
            self.devices = []
            self.status_var.set(str(exc))
            messagebox.showerror("ADB 错误", str(exc))
            return

        values = [self._format_device(device) for device in self.devices]
        self.device_combo["values"] = values
        if values:
            self.device_combo.current(0)
            self.status_var.set("请选择设备并点击“开始投屏”。")
        else:
            self.device_var.set("")
            self.status_var.set("未发现设备：请安装 adb、连接手机，并在手机上允许 USB 调试。")

    def start_mirroring(self) -> None:
        if not self.devices:
            self.refresh_devices()
        selected_index = self.device_combo.current()
        if selected_index < 0 or selected_index >= len(self.devices):
            messagebox.showwarning("未选择设备", "请先选择一个 Android 设备。")
            return

        device = self.devices[selected_index]
        if not device.is_ready:
            messagebox.showwarning("设备不可用", f"设备状态为 {device.state}，请在手机上允许 USB 调试。")
            return

        self.stop_mirroring()
        self.device_adb = self.adb.with_serial(device.serial)
        try:
            width, height = self.device_adb.screen_size()
        except AdbError as exc:
            self.status_var.set(str(exc))
            messagebox.showerror("读取屏幕失败", str(exc))
            return

        self.transform = DisplayTransform.fit(width, height, MAX_DISPLAY_WIDTH, MAX_DISPLAY_HEIGHT)
        self.canvas.config(width=self.transform.display_width, height=self.transform.display_height)
        self.canvas.focus_set()
        self.stop_event.clear()
        self.mirror_thread = threading.Thread(target=self._mirror_loop, name="adb-screen-mirror", daemon=True)
        self.mirror_thread.start()
        self.status_var.set(f"正在投屏 {device.serial}，手机分辨率 {width}x{height}。")

    def stop_mirroring(self) -> None:
        self.stop_event.set()
        self.mirror_thread = None
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

    def close(self) -> None:
        self.stop_mirroring()
        self.destroy()

    def _mirror_loop(self) -> None:
        while not self.stop_event.is_set() and self.device_adb is not None:
            started_at = time.monotonic()
            try:
                frame = self.device_adb.screen_png()
                if self.frame_queue.full():
                    self.frame_queue.get_nowait()
                self.frame_queue.put_nowait(frame)
            except (AdbError, queue.Empty) as exc:
                self.after(0, lambda message=str(exc): self.status_var.set(message))
                time.sleep(1.0)
            elapsed = time.monotonic() - started_at
            time.sleep(max(0.05, REFRESH_SECONDS - elapsed))

    def _consume_frames(self) -> None:
        try:
            frame = self.frame_queue.get_nowait()
        except queue.Empty:
            self.after(80, self._consume_frames)
            return

        try:
            image = tk.PhotoImage(data=base64.b64encode(frame))
            if self.transform and self.transform.scale_divisor > 1:
                image = image.subsample(self.transform.scale_divisor, self.transform.scale_divisor)
            self.current_image = image
            self.canvas.delete("screen")
            self.canvas.create_image(0, 0, anchor=tk.NW, image=image, tags="screen")
            if self.transform:
                self.canvas.config(scrollregion=(0, 0, self.transform.display_width, self.transform.display_height))
        except tk.TclError as exc:
            self.status_var.set(f"无法显示截图：{exc}")

        self.after(80, self._consume_frames)

    def _on_mouse_down(self, event: tk.Event) -> None:
        if not self.transform:
            return
        x, y = self.transform.to_device(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.drag_start = (x, y, time.monotonic())

    def _on_mouse_up(self, event: tk.Event) -> None:
        if not self.transform or not self.device_adb or not self.drag_start:
            return
        end_x, end_y = self.transform.to_device(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        start_x, start_y, started_at = self.drag_start
        self.drag_start = None
        distance = abs(end_x - start_x) + abs(end_y - start_y)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        try:
            if distance < DRAG_AS_SWIPE_THRESHOLD:
                self.device_adb.tap(end_x, end_y)
                self.status_var.set(f"点击：{end_x}, {end_y}")
            else:
                self.device_adb.swipe(start_x, start_y, end_x, end_y, duration_ms)
                self.status_var.set(f"滑动：{start_x},{start_y} -> {end_x},{end_y}")
        except AdbError as exc:
            self.status_var.set(str(exc))

    def _on_key(self, event: tk.Event) -> str:
        if event.keysym in KEY_EVENTS:
            self._send_key(KEY_EVENTS[event.keysym])
            return "break"
        if event.char and event.char.isprintable():
            self._send_text(event.char)
            return "break"
        return "break"

    def _send_key(self, key_code: int | str) -> None:
        if not self.device_adb:
            return
        try:
            self.device_adb.keyevent(key_code)
            self.status_var.set(f"按键：{key_code}")
        except AdbError as exc:
            self.status_var.set(str(exc))

    def _send_text(self, text: str) -> None:
        if not self.device_adb:
            return
        try:
            self.device_adb.text(text)
            self.status_var.set("已发送文本。")
        except AdbError as exc:
            self.status_var.set(str(exc))

    @staticmethod
    def _format_device(device: AndroidDevice) -> str:
        suffix = f" ({device.description})" if device.description else ""
        return f"{device.serial} [{device.state}]{suffix}"


def main() -> None:
    app = PhoneControlApp()
    app.mainloop()
