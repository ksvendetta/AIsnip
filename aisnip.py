from __future__ import annotations

import io
import json
import math
import queue
import copy
import sys
import threading
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pyautogui
from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk
from pynput import keyboard, mouse
import pystray

try:
    import win32clipboard
    import win32con
    import win32gui
    import win32api
except ImportError:  # pragma: no cover - app is Windows-focused, but import stays friendly.
    win32clipboard = None
    win32con = None
    win32gui = None
    win32api = None

import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog, ttk


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CONFIG_PATH = APP_DIR / "aisnip.json"
MOUSE_IMAGE_PATH = BUNDLE_DIR / "assets" / "mouse_top_view_clean.png"
STARTUP_APP_NAME = "AIsnip"
STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
COLORS = {
    "bg": "#f5f7fb",
    "panel": "#ffffff",
    "panel_border": "#d8dee9",
    "text": "#172033",
    "muted": "#5f6b7a",
    "primary": "#2563eb",
    "primary_hover": "#1d4ed8",
    "accent": "#0891b2",
    "editor_bg": "#111827",
    "toolbar": "#f8fafc",
}


DEFAULT_CONFIG = {
    "hotkey": "shift+mouse:right",
    "window_hotkey": "shift+mouse:left",
    "fullscreen_hotkey": "shift+mouse:middle",
    "color": "#ff2d2d",
    "stroke_width": 4,
    "font_size": 24,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def startup_command() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    return f'"{exe}" "{APP_DIR / "aisnip.py"}"'


def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH) as key:
            value, _value_type = winreg.QueryValueEx(key, STARTUP_APP_NAME)
            return value == startup_command()
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, STARTUP_APP_NAME)
            except FileNotFoundError:
                pass


def apply_app_style(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.option_add("*Font", ("Segoe UI", 10))
    root.option_add("*Foreground", COLORS["text"])
    style.configure(".", font=("Segoe UI", 10), background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("App.TFrame", background=COLORS["bg"])
    style.configure("Panel.TFrame", background=COLORS["panel"], relief="solid", borderwidth=1)
    style.configure("Toolbar.TFrame", background=COLORS["toolbar"])
    style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI Semibold", 17))
    style.configure("Subtitle.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 9))
    style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"], font=("Segoe UI", 9))
    style.configure("Key.TLabel", background="#eef4ff", foreground="#163b7a", font=("Segoe UI Semibold", 10), padding=(10, 4))
    style.configure("Primary.TButton", background=COLORS["primary"], foreground="#ffffff", borderwidth=0, padding=(12, 7))
    style.map("Primary.TButton", background=[("active", COLORS["primary_hover"]), ("pressed", COLORS["primary_hover"])], foreground=[("active", "#ffffff")])
    style.configure("Tool.TButton", padding=(10, 6))
    style.configure("Icon.TButton", padding=(8, 5))
    style.configure("Danger.TButton", padding=(10, 6), foreground="#991b1b")
    style.configure("App.TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Panel.TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("Tool.TRadiobutton", background=COLORS["toolbar"], foreground=COLORS["text"], padding=(7, 5))


def apply_rounded_window(window: tk.Misc, radius: int = 18) -> None:
    if win32gui is None:
        return

    def round_now(_event: Optional[tk.Event] = None) -> None:
        try:
            window.update_idletasks()
            width = window.winfo_width()
            height = window.winfo_height()
            if width <= 1 or height <= 1:
                return
            region = win32gui.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
            win32gui.SetWindowRgn(window.winfo_id(), region, True)
        except Exception:
            pass

    window.after(80, round_now)
    window.bind("<Configure>", round_now, add="+")


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Optional[Callable[[], None]] = None,
        width: int = 118,
        height: int = 34,
        radius: int = 10,
        fill: str = "#ffffff",
        hover: str = "#eef4ff",
        active: str = "#dbeafe",
        foreground: str = COLORS["text"],
        outline: str = COLORS["panel_border"],
        bg: Optional[str] = None,
        selected_fill: str = "#dbeafe",
        selected_outline: str = COLORS["primary"],
    ):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=bg or COLORS["bg"])
        self.command = command
        self.button_text = text
        self.radius = radius
        self.fill = fill
        self.hover = hover
        self.active = active
        self.foreground = foreground
        self.outline = outline
        self.selected_fill = selected_fill
        self.selected_outline = selected_outline
        self.selected = False
        self.state_fill = fill
        self.bind("<Enter>", lambda _event: self.paint(self.hover if not self.selected else self.selected_fill))
        self.bind("<Leave>", lambda _event: self.paint())
        self.bind("<ButtonPress-1>", lambda _event: self.paint(self.active))
        self.bind("<ButtonRelease-1>", self.release)
        self.paint()

    def release(self, _event: tk.Event) -> None:
        self.paint(self.hover if not self.selected else self.selected_fill)
        if self.command:
            self.command()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.paint()

    def paint(self, fill: Optional[str] = None) -> None:
        self.delete("all")
        width = int(self["width"])
        height = int(self["height"])
        use_fill = fill or (self.selected_fill if self.selected else self.fill)
        use_outline = self.selected_outline if self.selected else self.outline
        self.round_rect(1, 1, width - 1, height - 1, self.radius, fill=use_fill, outline=use_outline)
        text_color = COLORS["primary"] if self.selected and self.foreground == COLORS["text"] else self.foreground
        self.create_text(width // 2, height // 2, text=self.button_text, fill=text_color, font=("Segoe UI Semibold", 9))

    def round_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs: object) -> None:
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)


def normalize_hotkey(value: str) -> str:
    parts = [part.strip().lower().replace("control", "ctrl") for part in value.split("+") if part.strip()]
    return "+".join(parts) or DEFAULT_CONFIG["hotkey"]


def pynput_hotkey(value: str) -> str:
    names = {
        "ctrl": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "cmd": "<cmd>",
        "win": "<cmd>",
        "enter": "<enter>",
        "space": "<space>",
        "tab": "<tab>",
        "esc": "<esc>",
        "escape": "<esc>",
    }
    converted = []
    for part in normalize_hotkey(value).split("+"):
        if part in names:
            converted.append(names[part])
        elif part.startswith("f") and part[1:].isdigit():
            converted.append(f"<{part}>")
        else:
            converted.append(part)
    return "+".join(converted)


def single_key_name(value: str) -> Optional[str]:
    parts = normalize_hotkey(value).split("+")
    return parts[0] if len(parts) == 1 else None


def key_to_name(key: keyboard.Key | keyboard.KeyCode) -> str:
    if isinstance(key, keyboard.KeyCode):
        return (key.char or "").lower()
    name = key.name or str(key)
    name = name.replace("Key.", "").lower()
    if name in {"print_screen", "print"}:
        return "print_screen"
    return {"cmd": "win", "ctrl_l": "ctrl", "ctrl_r": "ctrl", "shift_l": "shift", "shift_r": "shift", "alt_l": "alt", "alt_r": "alt"}.get(name, name)


def mouse_button_to_name(button: mouse.Button) -> str:
    return f"mouse:{button.name.lower()}"


def windows_modifier_keys() -> set[str]:
    if win32api is None:
        return set()
    keys = set()
    virtual_keys = {
        "shift": (0x10, 0xA0, 0xA1),
        "ctrl": (0x11, 0xA2, 0xA3),
        "alt": (0x12, 0xA4, 0xA5),
        "win": (0x5B, 0x5C),
    }
    for name, codes in virtual_keys.items():
        if any(win32api.GetAsyncKeyState(code) & 0x8000 for code in codes):
            keys.add(name)
    return keys


def display_shortcut(value: str) -> str:
    parts = []
    for part in normalize_hotkey(value).split("+"):
        if part.startswith("mouse:"):
            parts.append(f"Mouse {part.split(':', 1)[1].upper()}")
        else:
            parts.append(part)
    return "+".join(parts)


def hotkey_parts(value: str) -> set[str]:
    return set(normalize_hotkey(value).replace("cmd", "win").split("+"))


COMMON_SHORTCUT_CONFLICTS = {
    "ctrl+c": "Copy",
    "ctrl+v": "Paste",
    "ctrl+x": "Cut",
    "ctrl+z": "Undo",
    "ctrl+a": "Select all",
    "ctrl+s": "Save",
    "ctrl+p": "Print",
    "ctrl+shift+esc": "Task Manager",
    "alt+tab": "switch windows",
    "alt+f4": "close the active window",
    "win+d": "show desktop",
    "win+e": "open File Explorer",
    "win+l": "lock Windows",
    "win+r": "Run dialog",
    "win+tab": "Task View",
    "win+shift+s": "Windows Snipping Tool",
    "print_screen": "Windows screenshot",
}


def shortcut_conflict(value: str) -> Optional[str]:
    normalized = normalize_hotkey(value).replace("cmd", "win")
    return COMMON_SHORTCUT_CONFLICTS.get(normalized)


def copy_image_to_clipboard(image: Image.Image) -> None:
    if win32clipboard is None:
        raise RuntimeError("Image clipboard support requires pywin32 on Windows.")
    output = io.BytesIO()
    image.convert("RGB").save(output, "BMP")
    data = output.getvalue()[14:]
    output.close()
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()


def capture_screen() -> Image.Image:
    return ImageGrab.grab(all_screens=True)


def active_monitor_offset() -> tuple[int, int]:
    image = capture_screen()
    return image.getbbox()[:2] if image.getbbox() else (0, 0)


def window_under_cursor() -> Optional[tuple[int, tuple[int, int, int, int]]]:
    if win32gui is None:
        return None
    x, y = pyautogui.position()
    hwnd = win32gui.WindowFromPoint((x, y))
    hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
    if not hwnd or not win32gui.IsWindowVisible(hwnd):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if right - left < 20 or bottom - top < 20:
        return None
    return hwnd, (left, top, right, bottom)


def window_rect_under_cursor() -> Optional[tuple[int, int, int, int]]:
    window = window_under_cursor()
    return window[1] if window else None


def bring_window_to_front(hwnd: int) -> None:
    if win32gui is None or win32con is None:
        return
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    else:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        if win32api is not None:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            win32gui.SetForegroundWindow(hwnd)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32gui.BringWindowToTop(hwnd)


def capture_rect(rect: tuple[int, int, int, int]) -> Image.Image:
    return ImageGrab.grab(bbox=rect, all_screens=True)


@dataclass
class AnnotationItem:
    tool: str
    start: tuple[int, int]
    end: tuple[int, int]
    color: str
    width: int
    font_size: int
    text: str = ""
    points: list[tuple[int, int]] = field(default_factory=list)


class RegionSelector(tk.Toplevel):
    def __init__(self, root: tk.Tk, on_done: Callable[[Optional[Image.Image]], None]):
        super().__init__(root)
        self.on_done = on_done
        self.image = capture_screen()
        self.photo = ImageTk.PhotoImage(self.image)
        self.start: Optional[tuple[int, int]] = None
        self.rect_id: Optional[int] = None
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.35)
        self.geometry(f"{self.image.width}x{self.image.height}+0+0")
        self.canvas = tk.Canvas(self, cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.finish)
        self.bind("<Escape>", lambda _event: self.cancel())

    def begin(self, event: tk.Event) -> None:
        self.start = (event.x, event.y)
        self.rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00e5ff", width=3)

    def drag(self, event: tk.Event) -> None:
        if self.start and self.rect_id:
            self.canvas.coords(self.rect_id, self.start[0], self.start[1], event.x, event.y)

    def finish(self, event: tk.Event) -> None:
        if not self.start:
            self.cancel()
            return
        x1, y1 = self.start
        x2, y2 = event.x, event.y
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        self.destroy()
        if right - left < 5 or bottom - top < 5:
            self.on_done(None)
            return
        self.on_done(self.image.crop((left, top, right, bottom)))

    def cancel(self) -> None:
        self.destroy()
        self.on_done(None)


class WindowHighlighter(tk.Toplevel):
    def __init__(self, root: tk.Tk, on_done: Callable[[Optional[Image.Image]], None]):
        super().__init__(root)
        self.on_done = on_done
        self.current_rect: Optional[tuple[int, int, int, int]] = None
        self.current_hwnd: Optional[int] = None
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", "magenta")
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        self.canvas = tk.Canvas(self, bg="magenta", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.rect_id = self.canvas.create_rectangle(0, 0, 0, 0, outline="#00e5ff", width=5)
        self.after(30, self.track)

    def track(self) -> None:
        window = window_under_cursor()
        self.current_hwnd = window[0] if window else None
        rect = window[1] if window else None
        self.current_rect = rect
        if rect:
            left, top, right, bottom = rect
            self.canvas.coords(self.rect_id, left, top, right, bottom)
        else:
            self.canvas.coords(self.rect_id, 0, 0, 0, 0)
        self.after(30, self.track)

    def finish(self) -> None:
        rect = self.current_rect
        hwnd = self.current_hwnd
        self.withdraw()
        self.update_idletasks()
        if hwnd:
            bring_window_to_front(hwnd)
        time.sleep(0.25)
        if hwnd and win32gui is not None and win32gui.IsWindow(hwnd):
            rect = win32gui.GetWindowRect(hwnd)
        image = capture_rect(rect) if rect else None
        self.destroy()
        self.on_done(image)


class ShortcutPicker(tk.Toplevel):
    def __init__(self, root: tk.Tk, current: str, on_done: Callable[[str], None], on_cancel: Callable[[], None]):
        super().__init__(root)
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.modifiers: dict[str, tk.BooleanVar] = {
            "ctrl": tk.BooleanVar(value="ctrl" in hotkey_parts(current)),
            "alt": tk.BooleanVar(value="alt" in hotkey_parts(current)),
            "shift": tk.BooleanVar(value="shift" in hotkey_parts(current)),
            "win": tk.BooleanVar(value="win" in hotkey_parts(current)),
        }
        self.modifier_buttons: dict[str, list[RoundedButton]] = {}
        self.key_buttons: dict[str, RoundedButton] = {}
        self.mouse_buttons: dict[str, RoundedButton] = {}
        self.mouse_canvas: Optional[tk.Canvas] = None
        self.mouse_photo: Optional[ImageTk.PhotoImage] = None
        self.mouse_regions: dict[str, list[tuple[int, int]]] = {}
        existing = [part for part in normalize_hotkey(current).split("+") if part not in self.modifiers]
        self.main_key = tk.StringVar(value=existing[-1] if existing and existing[-1].startswith("mouse:") else (existing[-1].upper() if existing else "S"))
        self.title("Choose Shortcut")
        self.geometry("780x660")
        self.resizable(False, False)
        apply_app_style(self)
        apply_rounded_window(self, 20)
        self.transient(root)
        self.grab_set()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(3, weight=1)
        outer.columnconfigure(0, weight=1)
        ttk.Label(outer, text="Choose a keyboard key or mouse button. Modifier keys stay highlighted when active.").pack(anchor="w")

        self.preview = tk.StringVar()
        ttk.Label(outer, textvariable=self.preview, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(12, 10))
        self.warning = tk.StringVar()
        ttk.Label(outer, textvariable=self.warning, foreground="#b45309", wraplength=720).pack(anchor="w", pady=(0, 8))

        keyboard_frame = ttk.Frame(outer)
        keyboard_frame.pack(fill="both", expand=True)
        rows = [
            [(f"F{i}", f"f{i}", 46, "key") for i in range(1, 13)],
            [(key, key, 46, "key") for key in list("1234567890")],
            [(key, key, 46, "key") for key in list("QWERTYUIOP")],
            [("Shift", "shift", 82, "modifier"), *[(key, key, 46, "key") for key in list("ASDFGHJKL")], ("Shift", "shift", 82, "modifier")],
            [("Ctrl", "ctrl", 70, "modifier"), ("Win", "win", 62, "modifier"), ("Alt", "alt", 62, "modifier"), *[(key, key, 46, "key") for key in list("ZXCVBNM")], ("Alt", "alt", 62, "modifier"), ("Win", "win", 62, "modifier"), ("Ctrl", "ctrl", 70, "modifier")],
        ]
        for row in rows:
            row_frame = ttk.Frame(keyboard_frame)
            row_frame.pack(anchor="center", pady=2)
            for label, value, width, kind in row:
                if kind == "modifier":
                    button = RoundedButton(row_frame, text=label, width=width, height=30, radius=8, command=lambda item=value: self.toggle_modifier(item), bg=COLORS["bg"])
                    self.modifier_buttons.setdefault(value, []).append(button)
                else:
                    button = RoundedButton(row_frame, text=label, width=width, height=30, radius=8, command=lambda item=value: self.pick_key(item), bg=COLORS["bg"])
                    self.key_buttons[value.lower()] = button
                button.pack(side="left", padx=2)

        mouse_frame = ttk.Frame(keyboard_frame)
        mouse_frame.pack(anchor="center", pady=(8, 2))
        self.draw_mouse_picker(mouse_frame)

        buttons = ttk.Frame(outer)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        RoundedButton(buttons, text="Cancel", command=self.cancel, width=92, bg=COLORS["bg"]).pack(side="right", padx=4)
        RoundedButton(buttons, text="Save", command=self.finish, width=92, fill=COLORS["primary"], hover=COLORS["primary_hover"], active=COLORS["primary_hover"], foreground="#ffffff", outline=COLORS["primary"], bg=COLORS["bg"]).pack(side="right")
        self.update_preview()

    def toggle_modifier(self, name: str) -> None:
        self.modifiers[name].set(not self.modifiers[name].get())
        self.update_preview()

    def pick_key(self, key: str) -> None:
        self.main_key.set(key)
        self.update_preview()

    def shortcut_value(self) -> str:
        parts = [name for name, var in self.modifiers.items() if var.get()]
        parts.append(self.main_key.get().lower())
        return normalize_hotkey("+".join(parts))

    def update_preview(self) -> None:
        value = self.shortcut_value()
        self.preview.set(f"Selected: {display_shortcut(value)}")
        conflict = shortcut_conflict(value)
        self.warning.set(f"Possible Windows shortcut conflict: {conflict}." if conflict else "")
        selected_key = self.main_key.get().lower()
        for name, buttons in self.modifier_buttons.items():
            for button in buttons:
                button.set_selected(self.modifiers[name].get())
        for key, button in self.key_buttons.items():
            button.set_selected(key == selected_key)
        self.update_mouse_picker()

    def draw_mouse_picker(self, parent: tk.Misc) -> None:
        self.mouse_canvas = tk.Canvas(parent, width=270, height=320, bg=COLORS["bg"], highlightthickness=0)
        self.mouse_canvas.pack(side="left", padx=(0, 14))
        self.mouse_canvas.create_text(135, 12, text="Use mouse button", fill=COLORS["muted"], font=("Segoe UI Semibold", 9))
        if MOUSE_IMAGE_PATH.exists():
            mouse_image = Image.open(MOUSE_IMAGE_PATH)
            self.mouse_photo = ImageTk.PhotoImage(mouse_image)
            self.mouse_canvas.create_image(135, 170, image=self.mouse_photo)
        else:
            self.mouse_canvas.create_text(135, 170, text="Mouse image missing", fill="#b91c1c", font=("Segoe UI", 10))

        # Hit zones over the imported mouse image. They are intentionally generous
        # so the diagram is easy to click.
        self.mouse_regions = {
            "mouse:middle": [(110, 42), (160, 42), (160, 140), (110, 140)],
            "mouse:left": [(75, 42), (128, 28), (128, 96), (78, 104), (68, 76)],
            "mouse:right": [(142, 28), (195, 42), (202, 76), (192, 104), (142, 96)],
            "mouse:x1": [(55, 95), (79, 100), (82, 148), (58, 145)],
            "mouse:x2": [(61, 149), (89, 160), (98, 227), (70, 218)],
        }
        self.mouse_canvas.bind("<Button-1>", self.handle_mouse_canvas_click)
        self.mouse_canvas.bind("<Motion>", self.handle_mouse_canvas_motion)
        self.mouse_canvas.bind("<Leave>", lambda _event: self.mouse_canvas.configure(cursor="") if self.mouse_canvas else None)
        button_panel = ttk.Frame(parent)
        button_panel.pack(side="left", padx=(4, 0))
        for label, value in [
            ("Left", "mouse:left"),
            ("Middle / Wheel", "mouse:middle"),
            ("Right", "mouse:right"),
            ("Side X1", "mouse:x1"),
            ("Side X2", "mouse:x2"),
        ]:
            button = RoundedButton(button_panel, text=label, width=122, height=28, radius=8, command=lambda item=value: self.pick_key(item), bg=COLORS["bg"])
            button.pack(anchor="w", pady=2)
            self.mouse_buttons[value] = button

    def update_mouse_picker(self) -> None:
        if not self.mouse_canvas:
            return
        selected_key = self.main_key.get().lower()
        self.mouse_canvas.delete("mouse-highlight")
        for value, button in self.mouse_buttons.items():
            button.set_selected(value == selected_key)
        for value, item_id in self.mouse_regions.items():
            if value == selected_key:
                flat = [coord for point in item_id for coord in point]
                self.mouse_canvas.create_polygon(
                    flat,
                    fill="#bfdbfe",
                    stipple="gray25",
                    outline=COLORS["primary"],
                    width=3,
                    tags=("mouse-highlight",),
                )
                self.mouse_canvas.tag_lower("mouse-highlight")
                if self.mouse_photo:
                    self.mouse_canvas.tag_raise("mouse-highlight")

    def handle_mouse_canvas_click(self, event: tk.Event) -> None:
        hit = self.mouse_region_at(event.x, event.y)
        if hit:
            self.pick_key(hit)

    def handle_mouse_canvas_motion(self, event: tk.Event) -> None:
        if self.mouse_canvas:
            self.mouse_canvas.configure(cursor="hand2" if self.mouse_region_at(event.x, event.y) else "")

    def mouse_region_at(self, x: int, y: int) -> Optional[str]:
        for value, polygon in self.mouse_regions.items():
            if self.point_in_polygon(x, y, polygon):
                return value
        return None

    @staticmethod
    def point_in_polygon(x: int, y: int, polygon: list[tuple[int, int]]) -> bool:
        inside = False
        j = len(polygon) - 1
        for i, point in enumerate(polygon):
            xi, yi = point
            xj, yj = polygon[j]
            if (yi > y) != (yj > y):
                x_intersect = (xj - xi) * (y - yi) / ((yj - yi) or 1) + xi
                if x < x_intersect:
                    inside = not inside
            j = i
        return inside

    def finish(self) -> None:
        self.on_done(self.shortcut_value())
        self.destroy()

    def cancel(self) -> None:
        self.on_cancel()
        self.destroy()


class AnnotationEditor(tk.Toplevel):
    def __init__(self, root: tk.Tk, image: Image.Image, config: dict):
        super().__init__(root)
        self.app_root = root
        self.config_data = config
        self.base = image.convert("RGBA")
        self.items: list[AnnotationItem] = []
        self.history: list[list[AnnotationItem]] = []
        self.current_item: Optional[AnnotationItem] = None
        self.hover_index: Optional[int] = None
        self.selected_index: Optional[int] = None
        self.drag_mode: Optional[str] = None
        self.drag_start: Optional[tuple[int, int]] = None
        self.drag_original: Optional[tuple[tuple[int, int], tuple[int, int], list[tuple[int, int]]]] = None
        self.tool = tk.StringVar(value="bubble")
        self.color = tk.StringVar(value=config.get("color", "#ff2d2d"))
        self.stroke_width = tk.IntVar(value=int(config.get("stroke_width", 4)))
        self.font_size = tk.IntVar(value=int(config.get("font_size", 24)))
        apply_app_style(self)
        self.title("AIsnip Editor")
        self.configure(bg=COLORS["editor_bg"])
        self.geometry(f"{min(self.base.width + 80, 1400)}x{min(self.base.height + 130, 900)}")
        apply_rounded_window(self, 18)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build_ui()
        self._render()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(12, 9), style="Toolbar.TFrame")
        toolbar.pack(side="top", fill="x")
        ttk.Label(toolbar, text="Tools", background=COLORS["toolbar"], foreground=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(side="left", padx=(0, 8))
        for label, value in [
            ("Arrow", "arrow"),
            ("Bubble", "bubble"),
            ("Box", "rect"),
            ("Oval", "ellipse"),
            ("Line", "line"),
        ]:
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.tool, style="Tool.TRadiobutton").pack(side="left", padx=1)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=10)
        RoundedButton(toolbar, text="Color", command=self.pick_color, width=82, height=32, radius=9, bg=COLORS["toolbar"]).pack(side="left", padx=2)
        RoundedButton(toolbar, text="-", command=lambda: self.resize_items(-1), width=36, height=32, radius=9, bg=COLORS["toolbar"]).pack(side="left", padx=(8, 2))
        RoundedButton(toolbar, text="+", command=lambda: self.resize_items(1), width=36, height=32, radius=9, bg=COLORS["toolbar"]).pack(side="left", padx=2)
        RoundedButton(toolbar, text="Undo", command=self.undo, width=76, height=32, radius=9, bg=COLORS["toolbar"]).pack(side="left", padx=(12, 2))
        RoundedButton(toolbar, text="Done", command=self.done, width=88, height=32, radius=9, fill=COLORS["primary"], hover=COLORS["primary_hover"], active=COLORS["primary_hover"], foreground="#ffffff", outline=COLORS["primary"], bg=COLORS["toolbar"]).pack(side="right", padx=2)

        frame = ttk.Frame(self, padding=10, style="App.TFrame")
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, bg=COLORS["editor_bg"], highlightthickness=1, highlightbackground="#273244")
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas.bind("<ButtonPress-1>", self.begin_item)
        self.canvas.bind("<B1-Motion>", self.drag_item)
        self.canvas.bind("<ButtonRelease-1>", self.finish_item)
        self.canvas.bind("<Motion>", self.hover_item)
        self.canvas.bind("<Leave>", self.clear_hover)
        self.canvas.bind("<Double-Button-1>", self.edit_selected_text)
        self.bind("<Delete>", self.delete_selected_item)
        self.bind("<BackSpace>", self.delete_selected_item)
        self.bind("<Control-z>", self.undo_event)
        self.bind("<Control-Z>", self.undo_event)
        self.canvas.focus_set()

    def pick_color(self) -> None:
        value = colorchooser.askcolor(color=self.color.get(), parent=self)[1]
        if value:
            self.push_history()
            self.color.set(value)
            for item in self.items:
                item.color = value
            self.config_data["color"] = value
            save_config(self.config_data)
            self._render()

    def resize_items(self, delta: int) -> None:
        self.push_history()
        self.stroke_width.set(max(1, self.stroke_width.get() + delta))
        self.font_size.set(max(10, self.font_size.get() + delta * 2))
        for item in self.items:
            item.width = max(1, item.width + delta)
            item.font_size = max(10, item.font_size + delta * 2)
        self.config_data["stroke_width"] = self.stroke_width.get()
        self.config_data["font_size"] = self.font_size.get()
        save_config(self.config_data)
        self._render()

    def begin_item(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        point = (int(x), int(y))
        handle = self.handle_at(point)
        if handle:
            self.selected_index, self.drag_mode = handle
            self.begin_existing_drag(point)
            self._render()
            return
        hit = self.item_at(point)
        if hit is not None:
            self.selected_index = hit
            self.drag_mode = "move"
            self.begin_existing_drag(point)
            self._render()
            return
        self.selected_index = None
        if self.tool.get() == "bubble":
            text = simpledialog.askstring("Notation Bubble", "Text:", parent=self)
            if not text:
                return
            self.push_history()
            self.items.append(self.create_bubble(point, text))
            self.selected_index = len(self.items) - 1
            self._render()
            return
        self.current_item = AnnotationItem(
            self.tool.get(),
            point,
            point,
            self.color.get(),
            self.stroke_width.get(),
            self.font_size.get(),
        )

    def drag_item(self, event: tk.Event) -> None:
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        point = (int(x), int(y))
        if self.drag_mode and self.selected_index is not None:
            self.drag_existing_item(point)
            self._render()
            return
        if not self.current_item:
            return
        self.current_item.end = point
        self._render(preview=self.current_item)

    def finish_item(self, event: tk.Event) -> None:
        if self.drag_mode:
            self.push_history()
            self.drag_mode = None
            self.drag_start = None
            self.drag_original = None
            self._render()
            return
        if not self.current_item:
            return
        self.push_history()
        self.items.append(self.current_item)
        self.selected_index = len(self.items) - 1
        self.current_item = None
        self._render()

    def create_bubble(self, anchor: tuple[int, int], text: str) -> AnnotationItem:
        font = self.annotation_font(self.font_size.get())
        lines = text.splitlines() or [text]
        probe = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(probe)
        line_boxes = [draw.textbbox((0, 0), line or " ", font=font) for line in lines]
        text_width = max(box[2] - box[0] for box in line_boxes)
        line_height = max(font.size + 4 if hasattr(font, "size") else 18, max(box[3] - box[1] for box in line_boxes) + 6)
        padding_x = 18
        padding_y = 14
        bubble_width = max(110, text_width + padding_x * 2)
        bubble_height = max(54, line_height * len(lines) + padding_y * 2)
        ax, ay = anchor
        left = ax + 34
        top = ay - bubble_height - 28
        if left + bubble_width > self.base.width:
            left = max(8, ax - bubble_width - 34)
        if top < 8:
            top = min(self.base.height - bubble_height - 8, ay + 28)
        right = left + bubble_width
        bottom = top + bubble_height
        return AnnotationItem("bubble", (int(left), int(top)), (int(right), int(bottom)), self.color.get(), self.stroke_width.get(), self.font_size.get(), text, [anchor])

    def undo(self) -> None:
        if not self.history:
            return
        self.items = self.history.pop()
        self.selected_index = min(self.selected_index, len(self.items) - 1) if self.selected_index is not None and self.items else None
        self.hover_index = None
        self.current_item = None
        self.drag_mode = None
        self._render()

    def undo_event(self, _event: tk.Event) -> str:
        self.undo()
        return "break"

    def push_history(self) -> None:
        self.history.append(copy.deepcopy(self.items))
        if len(self.history) > 50:
            self.history.pop(0)

    def delete_selected_item(self, _event: Optional[tk.Event] = None) -> str:
        index = self.selected_index if self.selected_index is not None else self.hover_index
        if index is None or index < 0 or index >= len(self.items):
            return "break"
        self.push_history()
        self.items.pop(index)
        self.selected_index = None
        self.hover_index = None
        self._render()
        return "break"

    def _render(self, preview: Optional[AnnotationItem] = None) -> None:
        image = self.flatten(preview)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.draw_selection_overlays()
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))

    def draw_selection_overlays(self) -> None:
        overlay_index = self.selected_index if self.selected_index is not None else self.hover_index
        if overlay_index is None or overlay_index < 0 or overlay_index >= len(self.items):
            return
        item = self.items[overlay_index]
        x1, y1, x2, y2 = self.item_bounds(item)
        outline = "#00e5ff" if overlay_index == self.selected_index else "#ffd400"
        self.canvas.create_rectangle(x1 - 3, y1 - 3, x2 + 3, y2 + 3, outline="#111827", width=4)
        self.canvas.create_rectangle(x1 - 3, y1 - 3, x2 + 3, y2 + 3, outline=outline, width=2, dash=(5, 3))
        if overlay_index == self.selected_index:
            for name, point in self.handles_for_item(item).items():
                x, y = point
                fill = "#ffffff" if name != "move-anchor" else "#67e8f9"
                self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill=fill, outline="#111827", width=2, tags=("handle", name))

    def flatten(self, preview: Optional[AnnotationItem] = None) -> Image.Image:
        image = self.base.copy()
        draw = ImageDraw.Draw(image)
        for item in [*self.items, *([preview] if preview else [])]:
            self.draw_item(draw, item)
        return image.convert("RGB")

    def hover_item(self, event: tk.Event) -> None:
        point = (int(self.canvas.canvasx(event.x)), int(self.canvas.canvasy(event.y)))
        handle = self.handle_at(point)
        if handle:
            _index, mode = handle
            cursor = "fleur" if mode == "move-anchor" else "sizing"
            self.canvas.configure(cursor=cursor)
        elif self.item_at(point) is not None:
            self.canvas.configure(cursor="fleur")
        else:
            self.canvas.configure(cursor="crosshair")
        if self.drag_mode:
            return
        new_hover = self.item_at(point)
        if new_hover != self.hover_index:
            self.hover_index = new_hover
            self._render()

    def clear_hover(self, _event: tk.Event) -> None:
        if self.hover_index is not None:
            self.hover_index = None
            self.canvas.configure(cursor="crosshair")
            self._render()

    def begin_existing_drag(self, point: tuple[int, int]) -> None:
        item = self.items[self.selected_index]  # type: ignore[index]
        self.drag_start = point
        self.drag_original = (item.start, item.end, list(item.points))

    def drag_existing_item(self, point: tuple[int, int]) -> None:
        if self.selected_index is None or not self.drag_start or not self.drag_original or not self.drag_mode:
            return
        item = self.items[self.selected_index]
        start, end, points = self.drag_original
        dx = point[0] - self.drag_start[0]
        dy = point[1] - self.drag_start[1]
        if self.drag_mode == "move":
            item.start = (start[0] + dx, start[1] + dy)
            item.end = (end[0] + dx, end[1] + dy)
            if item.tool != "bubble":
                item.points = [(px + dx, py + dy) for px, py in points]
        elif self.drag_mode == "resize-start":
            item.start = point
        elif self.drag_mode == "resize-end":
            item.end = point
        elif self.drag_mode == "resize-nw":
            item.start = point
        elif self.drag_mode == "resize-ne":
            item.start = (start[0], point[1])
            item.end = (point[0], end[1])
        elif self.drag_mode == "resize-sw":
            item.start = (point[0], start[1])
            item.end = (end[0], point[1])
        elif self.drag_mode == "resize-se":
            item.end = point
        elif self.drag_mode == "move-anchor" and item.tool == "bubble":
            item.points = [point]

    def item_at(self, point: tuple[int, int]) -> Optional[int]:
        for index in range(len(self.items) - 1, -1, -1):
            if self.hit_item(self.items[index], point):
                return index
        return None

    def handle_at(self, point: tuple[int, int]) -> Optional[tuple[int, str]]:
        if self.selected_index is None or self.selected_index >= len(self.items):
            return None
        for name, handle in self.handles_for_item(self.items[self.selected_index]).items():
            if abs(point[0] - handle[0]) <= 8 and abs(point[1] - handle[1]) <= 8:
                return self.selected_index, name
        return None

    def handles_for_item(self, item: AnnotationItem) -> dict[str, tuple[int, int]]:
        if item.tool in {"line", "arrow"}:
            return {"resize-start": item.start, "resize-end": item.end}
        x1, y1, x2, y2 = self.item_bounds(item)
        handles = {
            "resize-nw": (x1, y1),
            "resize-ne": (x2, y1),
            "resize-sw": (x1, y2),
            "resize-se": (x2, y2),
        }
        if item.tool == "bubble" and item.points:
            handles["move-anchor"] = item.points[0]
        return handles

    def hit_item(self, item: AnnotationItem, point: tuple[int, int]) -> bool:
        x, y = point
        x1, y1, x2, y2 = self.item_bounds(item)
        if item.tool in {"line", "arrow"}:
            return self.distance_to_segment(point, item.start, item.end) <= max(8, item.width + 4)
        if item.tool == "ellipse":
            width = max(1, x2 - x1)
            height = max(1, y2 - y1)
            cx = x1 + width / 2
            cy = y1 + height / 2
            value = ((x - cx) / (width / 2)) ** 2 + ((y - cy) / (height / 2)) ** 2
            return value <= 1.08
        if item.tool == "bubble" and item.points and self.distance_to_segment(point, item.points[0], ((x1 + x2) // 2, y1 if item.points[0][1] < y1 else y2)) <= 10:
            return True
        return x1 <= x <= x2 and y1 <= y <= y2

    @staticmethod
    def item_bounds(item: AnnotationItem) -> tuple[int, int, int, int]:
        x1, y1 = item.start
        x2, y2 = item.end
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if item.tool in {"line", "arrow"}:
            pad = max(10, item.width * 3)
            return left - pad, top - pad, right + pad, bottom + pad
        return left, top, right, bottom

    @staticmethod
    def distance_to_segment(point: tuple[int, int], start: tuple[int, int], end: tuple[int, int]) -> float:
        px, py = point
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        nearest = (x1 + t * dx, y1 + t * dy)
        return math.hypot(px - nearest[0], py - nearest[1])

    def edit_selected_text(self, event: tk.Event) -> None:
        point = (int(self.canvas.canvasx(event.x)), int(self.canvas.canvasy(event.y)))
        index = self.item_at(point)
        if index is None or self.items[index].tool != "bubble":
            return
        self.selected_index = index
        text = simpledialog.askstring("Notation Bubble", "Text:", initialvalue=self.items[index].text, parent=self)
        if text is not None:
            old_anchor = self.items[index].points[0] if self.items[index].points else point
            self.items[index] = self.create_bubble(old_anchor, text)
            self.selected_index = index
            self._render()

    def draw_item(self, draw: ImageDraw.ImageDraw, item: AnnotationItem) -> None:
        x1, y1 = item.start
        x2, y2 = item.end
        width = item.width
        if item.tool == "arrow":
            draw.line((x1, y1, x2, y2), fill=item.color, width=width)
            self.draw_arrow_head(draw, x1, y1, x2, y2, item.color, width)
        elif item.tool == "line":
            draw.line((x1, y1, x2, y2), fill=item.color, width=width)
        elif item.tool == "rect":
            draw.rectangle((x1, y1, x2, y2), outline=item.color, width=width)
        elif item.tool == "ellipse":
            draw.ellipse((x1, y1, x2, y2), outline=item.color, width=width)
        elif item.tool == "bubble":
            shadow = (x1 + 4, y1 + 5, x2 + 4, y2 + 5)
            draw.rounded_rectangle(shadow, radius=14, fill=(0, 0, 0, 55))
            anchor = item.points[0] if item.points else item.start
            tail_x = min(max(anchor[0], min(x1, x2) + 18), max(x1, x2) - 18)
            tail_y = y2 if anchor[1] > (y1 + y2) / 2 else y1
            tail = [(tail_x - 12, tail_y), (tail_x + 12, tail_y), anchor]
            draw.polygon(tail, fill=(255, 255, 255, 230), outline=item.color)
            draw.line((tail[0], anchor, tail[1]), fill=item.color, width=width)
            draw.rounded_rectangle((x1, y1, x2, y2), radius=14, outline=item.color, width=width, fill=(255, 255, 255, 230))
            if item.text:
                font = self.annotation_font(item.font_size)
                y = min(y1, y2) + 14
                for line in item.text.splitlines():
                    draw.text((min(x1, x2) + 18, y), line, fill="#111111", font=font)
                    bbox = draw.textbbox((0, 0), line or " ", font=font)
                    y += max(item.font_size + 4, bbox[3] - bbox[1] + 6)

    @staticmethod
    def annotation_font(size: int) -> ImageFont.ImageFont:
        for name in ("arial.ttf", "segoeui.ttf"):
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)

    @staticmethod
    def draw_arrow_head(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int, color: str, width: int) -> None:
        angle = math.atan2(y2 - y1, x2 - x1)
        length = max(14, width * 5)
        spread = math.pi / 7
        points = [(x2, y2)]
        for offset in (spread, -spread):
            points.append((int(x2 - length * math.cos(angle - offset)), int(y2 - length * math.sin(angle - offset))))
        draw.polygon(points, fill=color)

    def done(self) -> None:
        image = self.flatten()
        copy_image_to_clipboard(image)
        self.destroy()


class AIsnipApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config_data = load_config()
        self.hotkey_listener: Optional[keyboard.Listener] = None
        self.mouse_listener: Optional[mouse.Listener] = None
        self.highlight: Optional[WindowHighlighter] = None
        self.window_hold_active = False
        self.pressed_keys: set[str] = set()
        self.snip_triggered = False
        self.fullscreen_triggered = False
        self.shortcut_picker_open = False
        self.mouse_shortcut_active = False
        self.hidden_to_tray = False
        self.actions: queue.Queue[Callable[[], None]] = queue.Queue()
        self.tray_icon: Optional[pystray.Icon] = None
        apply_app_style(self)
        self.title("AIsnip")
        self.configure(bg=COLORS["bg"])
        self.geometry("650x500")
        self.resizable(False, False)
        apply_rounded_window(self, 22)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self._build_ui()
        self.create_tray_icon()
        self.register_hotkey()
        self.after(50, self.drain_actions)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=20, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="AIsnip", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, text="Capture, mark up, copy, and send screenshots without breaking flow.", style="Subtitle.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 16)
        )

        shortcuts = ttk.Frame(outer, padding=14, style="Panel.TFrame")
        shortcuts.grid(row=2, column=0, columnspan=3, sticky="ew")
        shortcuts.columnconfigure(1, weight=1)
        ttk.Label(shortcuts, text="Snip Region Shortcut", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.hotkey_value = self.config_data["hotkey"]
        self.hotkey_var = tk.StringVar(value=display_shortcut(self.hotkey_value))
        ttk.Label(shortcuts, textvariable=self.hotkey_var, style="Key.TLabel").grid(row=0, column=1, sticky="w", padx=12)
        RoundedButton(shortcuts, text="Choose Keys", command=self.open_shortcut_picker, width=120, bg=COLORS["panel"]).grid(row=0, column=2, sticky="e")
        ttk.Label(shortcuts, text="Press once, then drag over a screen region.", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 10))

        ttk.Label(shortcuts, text="Select Window Shortcut", style="Panel.TLabel").grid(row=2, column=0, sticky="w")
        self.window_hotkey_value = self.config_data["window_hotkey"]
        self.window_hotkey_var = tk.StringVar(value=display_shortcut(self.window_hotkey_value))
        ttk.Label(shortcuts, textvariable=self.window_hotkey_var, style="Key.TLabel").grid(row=2, column=1, sticky="w", padx=12)
        RoundedButton(shortcuts, text="Choose Hold Key", command=self.open_window_shortcut_picker, width=134, bg=COLORS["panel"]).grid(row=2, column=2, sticky="e")
        ttk.Label(shortcuts, text="Hold, hover a window, then release to capture it.", style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 10))

        ttk.Label(shortcuts, text="Full Screen Snapshot Shortcut", style="Panel.TLabel").grid(row=4, column=0, sticky="w")
        self.fullscreen_hotkey_value = self.config_data["fullscreen_hotkey"]
        self.fullscreen_hotkey_var = tk.StringVar(value=display_shortcut(self.fullscreen_hotkey_value))
        ttk.Label(shortcuts, textvariable=self.fullscreen_hotkey_var, style="Key.TLabel").grid(row=4, column=1, sticky="w", padx=12)
        RoundedButton(shortcuts, text="Choose Keys", command=self.open_fullscreen_shortcut_picker, width=120, bg=COLORS["panel"]).grid(row=4, column=2, sticky="e")
        ttk.Label(shortcuts, text="Press once to capture the whole desktop.", style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))

        options = ttk.Frame(outer, padding=(14, 12), style="Panel.TFrame")
        options.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        ttk.Checkbutton(options, text="Run AIsnip when Windows starts", variable=self.startup_var, command=self.save_settings, style="Panel.TCheckbutton").grid(
            row=0, column=0, sticky="w"
        )

        actions = ttk.Frame(outer, style="App.TFrame")
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        actions.columnconfigure((0, 1, 2), weight=1)
        RoundedButton(actions, text="Snip Region", command=self.start_region, width=190, fill=COLORS["primary"], hover=COLORS["primary_hover"], active=COLORS["primary_hover"], foreground="#ffffff", outline=COLORS["primary"]).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        RoundedButton(actions, text="Pick Window", command=self.start_window_pick, width=190).grid(row=0, column=1, sticky="ew", padx=4)
        RoundedButton(actions, text="Full Screen", command=self.capture_fullscreen, width=190).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        footer = ttk.Frame(outer, style="App.TFrame")
        footer.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        footer.columnconfigure(1, weight=1)
        RoundedButton(footer, text="Minimize to Tray", command=self.hide_to_tray, width=136).grid(row=0, column=0, sticky="w")
        RoundedButton(footer, text="Quit", command=self.quit_app, width=86, fill="#fff1f2", hover="#ffe4e6", active="#fecdd3", foreground="#991b1b", outline="#fecdd3").grid(row=0, column=2, sticky="e")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(outer, textvariable=self.status, style="Subtitle.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 0))
        outer.columnconfigure(1, weight=1)

    def open_shortcut_picker(self) -> None:
        self.shortcut_picker_open = True

        def selected(value: str) -> None:
            self.hotkey_value = value
            self.hotkey_var.set(display_shortcut(value))
            self.shortcut_picker_open = False
            self.save_settings()

        picker = ShortcutPicker(self, self.hotkey_value, selected, lambda: setattr(self, "shortcut_picker_open", False))
        picker.protocol("WM_DELETE_WINDOW", picker.cancel)

    def open_window_shortcut_picker(self) -> None:
        self.shortcut_picker_open = True

        def selected(value: str) -> None:
            self.window_hotkey_value = value
            self.window_hotkey_var.set(display_shortcut(value))
            self.shortcut_picker_open = False
            self.save_settings()

        picker = ShortcutPicker(self, self.window_hotkey_value, selected, lambda: setattr(self, "shortcut_picker_open", False))
        picker.title("Choose Hold Window Key")
        picker.protocol("WM_DELETE_WINDOW", picker.cancel)

    def open_fullscreen_shortcut_picker(self) -> None:
        self.shortcut_picker_open = True

        def selected(value: str) -> None:
            self.fullscreen_hotkey_value = value
            self.fullscreen_hotkey_var.set(display_shortcut(value))
            self.shortcut_picker_open = False
            self.save_settings()

        picker = ShortcutPicker(self, self.fullscreen_hotkey_value, selected, lambda: setattr(self, "shortcut_picker_open", False))
        picker.title("Choose Full Screen Shortcut")
        picker.protocol("WM_DELETE_WINDOW", picker.cancel)

    def post_action(self, action: Callable[[], None]) -> None:
        self.actions.put(action)

    def drain_actions(self) -> None:
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                break
            action()
        self.after(50, self.drain_actions)

    def save_settings(self) -> None:
        self.config_data["hotkey"] = normalize_hotkey(self.hotkey_value)
        self.config_data["window_hotkey"] = normalize_hotkey(self.window_hotkey_value)
        self.config_data["fullscreen_hotkey"] = normalize_hotkey(self.fullscreen_hotkey_value)
        conflicts = []
        for label, value in [
            ("Snip Region", self.config_data["hotkey"]),
            ("Select Window", self.config_data["window_hotkey"]),
            ("Full Screen", self.config_data["fullscreen_hotkey"]),
        ]:
            conflict = shortcut_conflict(value)
            if conflict:
                conflicts.append(f"{label} uses {display_shortcut(value)}, which may conflict with {conflict}")
        save_config(self.config_data)
        try:
            set_startup_enabled(self.startup_var.get())
        except OSError as exc:
            self.startup_var.set(is_startup_enabled())
            self.status.set(f"Could not update startup option: {exc}")
            return
        self.register_hotkey()
        if conflicts:
            messagebox.showwarning("Possible Shortcut Conflict", "\n".join(conflicts), parent=self)
            self.status.set("Shortcut saved with a possible Windows shortcut conflict.")
        else:
            self.status.set(
                f"Shortcuts saved: snip {display_shortcut(self.config_data['hotkey'])}, "
                f"window {display_shortcut(self.config_data['window_hotkey'])}, full screen {display_shortcut(self.config_data['fullscreen_hotkey'])}"
            )

    def register_hotkey(self) -> None:
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        self.pressed_keys.clear()
        self.snip_triggered = False
        self.fullscreen_triggered = False
        self.mouse_shortcut_active = False
        self.window_hold_active = False
        try:
            self.hotkey_listener = keyboard.Listener(on_press=self.on_key_press, on_release=self.on_key_release)
            self.hotkey_listener.start()
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
            self.mouse_listener.start()
        except Exception as exc:
            self.status.set(f"Could not register shortcut: {exc}")

    def on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if self.shortcut_picker_open:
            return
        key_name = key_to_name(key)
        if not key_name:
            return
        self.pressed_keys.add(key_name)
        self.evaluate_shortcuts()

    def on_mouse_click(self, _x: int, _y: int, button: mouse.Button, pressed: bool) -> None:
        if self.shortcut_picker_open or self.is_shortcut_blocked_foreground():
            return
        button_name = mouse_button_to_name(button)
        self.refresh_live_modifiers()
        if pressed:
            self.pressed_keys.add(button_name)
            self.mouse_shortcut_active = True
            self.evaluate_shortcuts()
        else:
            self.release_shortcut_name(button_name)
            self.mouse_shortcut_active = False

    def refresh_live_modifiers(self) -> None:
        self.pressed_keys.difference_update({"shift", "ctrl", "alt", "win"})
        self.pressed_keys.update(windows_modifier_keys())

    def evaluate_shortcuts(self) -> None:
        window_target = hotkey_parts(self.config_data["window_hotkey"])
        if window_target.issubset(self.pressed_keys) and not self.window_hold_active:
            self.window_hold_active = True
            self.post_action(lambda: self.status.set(f"Heard shortcut: {display_shortcut(self.config_data['window_hotkey'])}"))
            self.post_action(self.begin_hold_highlight)
            return
        fullscreen_target = hotkey_parts(self.config_data["fullscreen_hotkey"])
        if fullscreen_target.issubset(self.pressed_keys):
            if not self.fullscreen_triggered:
                self.fullscreen_triggered = True
                self.post_action(lambda: self.status.set(f"Heard shortcut: {display_shortcut(self.config_data['fullscreen_hotkey'])}"))
                self.post_action(self.capture_fullscreen)
            return
        target = hotkey_parts(self.config_data["hotkey"])
        if not target.issubset(self.pressed_keys):
            return
        if not self.snip_triggered:
            self.snip_triggered = True
            self.post_action(lambda: self.status.set(f"Heard shortcut: {display_shortcut(self.config_data['hotkey'])}"))
            self.post_action(self.start_region)

    def on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = key_to_name(key)
        self.release_shortcut_name(key_name)

    def release_shortcut_name(self, key_name: str) -> None:
        self.pressed_keys.discard(key_name)
        target = hotkey_parts(self.config_data["hotkey"])
        if not target.issubset(self.pressed_keys):
            self.snip_triggered = False
        fullscreen_target = hotkey_parts(self.config_data["fullscreen_hotkey"])
        if not fullscreen_target.issubset(self.pressed_keys):
            self.fullscreen_triggered = False
        window_target = hotkey_parts(self.config_data["window_hotkey"])
        if self.window_hold_active and not window_target.issubset(self.pressed_keys):
            self.window_hold_active = False
            self.post_action(self.finish_hold_highlight)

    def is_shortcut_blocked_foreground(self) -> bool:
        if win32gui is None:
            return False
        try:
            foreground = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(foreground)
            return self.is_aisnip_window_title(title)
        except Exception:
            return False

    @staticmethod
    def is_aisnip_window_title(title: str) -> bool:
        return (
            "AIsnip" in title
            or "Choose Shortcut" in title
            or "Choose Hold Window Key" in title
            or "Choose Full Screen Shortcut" in title
        )

    def begin_hold_highlight(self) -> None:
        if not self.highlight:
            self.highlight = WindowHighlighter(self, self.open_editor)

    def finish_hold_highlight(self) -> None:
        if self.highlight:
            highlighter = self.highlight
            self.highlight = None
            highlighter.finish()

    def start_region(self) -> None:
        if self.mouse_shortcut_active:
            pyautogui.press("esc")
        self.withdraw()
        self.after(180, lambda: RegionSelector(self, self.open_editor))

    def start_window_pick(self) -> None:
        self.withdraw()
        self.after(150, self._start_window_pick_visible)

    def _start_window_pick_visible(self) -> None:
        self.highlight = WindowHighlighter(self, self.open_editor)
        self.highlight.bind("<ButtonRelease-1>", lambda _event: self.finish_hold_highlight())
        self.highlight.bind("<Escape>", lambda _event: self.cancel_highlight())

    def cancel_highlight(self) -> None:
        if self.highlight:
            self.highlight.destroy()
            self.highlight = None
        self.deiconify()

    def capture_fullscreen(self) -> None:
        if self.mouse_shortcut_active:
            pyautogui.press("esc")
        self.withdraw()
        self.after(180, lambda: self.open_editor(capture_screen()))

    def open_editor(self, image: Optional[Image.Image]) -> None:
        if not self.hidden_to_tray:
            self.deiconify()
        if image is None:
            self.status.set("Capture canceled")
            return
        self.status.set("Editing capture")
        AnnotationEditor(self, image, self.config_data)

    def create_tray_icon(self) -> None:
        image = Image.new("RGBA", (64, 64), "#1f2937")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((10, 10, 54, 54), radius=8, fill="#00e5ff")
        draw.rectangle((22, 22, 42, 42), outline="#111827", width=4)
        menu = pystray.Menu(
            pystray.MenuItem("Show AIsnip", lambda _icon, _item: self.post_action(self.show_from_tray)),
            pystray.MenuItem("Snip Region", lambda _icon, _item: self.post_action(self.start_region)),
            pystray.MenuItem("Pick Window", lambda _icon, _item: self.post_action(self.start_window_pick)),
            pystray.MenuItem("Full Screen", lambda _icon, _item: self.post_action(self.capture_fullscreen)),
            pystray.MenuItem("Quit", lambda _icon, _item: self.post_action(self.quit_app)),
        )
        self.tray_icon = pystray.Icon("AIsnip", image, "AIsnip", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_to_tray(self) -> None:
        self.hidden_to_tray = True
        self.withdraw()
        self.status.set("Running in the tray")

    def show_from_tray(self) -> None:
        self.hidden_to_tray = False
        self.deiconify()
        self.lift()
        self.focus_force()
        self.status.set("Ready")

    def quit_app(self) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy()

    def destroy(self) -> None:
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        super().destroy()


def main() -> int:
    if sys.platform != "win32":
        messagebox.showwarning("AIsnip", "AIsnip is designed for Windows screen capture and clipboard behavior.")
    app = AIsnipApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
