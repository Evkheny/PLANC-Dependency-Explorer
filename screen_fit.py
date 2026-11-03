"""Window sizes that follow the monitor the window is on (Tkinter port of SimLauncher's ``ui/screen_fit``).

Each window asks for a comfortable size, but never more than ~92 % of the free area of its monitor (task bar
excluded; Windows display scaling included, since Tk and the monitor API both see the same logical pixels),
and opens centred on the monitor of its parent (or of the mouse, or the primary one). When it is dragged to
another monitor it is shrunk / moved to fit that one. Every window can be resized by hand down to ~420 x 320:
the content lives in a :class:`ScrollArea`, so nothing is cut, it scrolls. The size chosen is remembered for
the session and, for the windows given a :class:`Settings`, across sessions (``%LOCALAPPDATA%``).

Call :func:`fit_to_screen` in the window's constructor instead of ``geometry("WxH")``.
"""
from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

FRACTION = 0.92          # share of the monitor's free area a window may take when it opens
FRAME_W, FRAME_H = 16, 40   # borders and title bar (logical px) until the real frame is known
MIN_SIZE = (420, 320)    # every window can be shrunk to this
_session: dict[str, dict] = {}


# ===================================================================== monitors
@dataclass(frozen=True)
class Monitor:
    x: int                  # whole monitor
    y: int
    width: int
    height: int
    wx: int                 # free (work) area: the monitor without the task bar
    wy: int
    wwidth: int
    wheight: int
    primary: bool = False
    dpi: int = 96

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height


# Tests (and odd platforms) set this to a list of Monitor to simulate other screens.
MONITORS_OVERRIDE: list[Monitor] | None = None


def monitors(widget=None) -> list[Monitor]:
    """The monitors with their free areas: from Windows (EnumDisplayMonitors / GetMonitorInfo, in the same
    logical pixels Tk uses), else the whole Tk screen as one monitor."""
    if MONITORS_OVERRIDE:
        return list(MONITORS_OVERRIDE)
    if sys.platform == "win32":
        try:
            return _windows_monitors()
        except (OSError, AttributeError):
            pass
    if widget is not None:
        w, h = widget.winfo_screenwidth(), widget.winfo_screenheight()
        return [Monitor(0, 0, w, h, 0, 0, w, h, True)]
    return [Monitor(0, 0, 1280, 720, 0, 0, 1280, 680, True)]


def _windows_monitors() -> list[Monitor]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    out: list[Monitor] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                              wintypes.LPARAM)

    def cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r, w = mi.rcMonitor, mi.rcWork
            dpi = 96
            try:
                dx, dy = wintypes.UINT(), wintypes.UINT()
                ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy))
                dpi = int(dx.value) or 96
            except (OSError, AttributeError):
                pass
            out.append(Monitor(r.left, r.top, r.right - r.left, r.bottom - r.top, w.left, w.top,
                               w.right - w.left, w.bottom - w.top, bool(mi.dwFlags & 1), dpi))
        return 1

    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    if not out:
        raise OSError("no monitor found")
    return out


def monitor_at(px: int, py: int, mons: list[Monitor] | None = None) -> Monitor:
    """The monitor holding the point, else the nearest one."""
    mons = mons or monitors()
    hit = next((m for m in mons if m.contains(px, py)), None)
    if hit:
        return hit

    def dist(m):
        cx = min(max(px, m.x), m.x + m.width - 1)
        cy = min(max(py, m.y), m.y + m.height - 1)
        return (cx - px) ** 2 + (cy - py) ** 2
    return min(mons, key=dist)


def _centre(win) -> tuple[int, int] | None:
    try:
        if win is not None and win.winfo_exists() and win.winfo_ismapped():
            top = win.winfo_toplevel()
            return top.winfo_rootx() + top.winfo_width() // 2, top.winfo_rooty() + top.winfo_height() // 2
    except tk.TclError:
        pass
    return None


def monitor_for(window, parent=None) -> Monitor:
    """The monitor of the window if it is shown, else of its parent, else of the mouse, else the primary."""
    mons = monitors(window)
    for w in (window, parent):
        c = _centre(w)
        if c:
            return monitor_at(*c, mons)
    try:
        return monitor_at(*window.winfo_pointerxy(), mons)
    except tk.TclError:
        return next((m for m in mons if m.primary), mons[0])


# ===================================================================== sizes
def fitted(width: int, height: int, mon: Monitor, fraction: float = FRACTION,
           frame: tuple[int, int] = (FRAME_W, FRAME_H)) -> tuple[int, int]:
    """``width`` x ``height`` (client size) reduced so that the window WITH its frame takes at most
    ``fraction`` of the monitor's free area."""
    return (max(1, min(width, int(mon.wwidth * fraction) - frame[0])),
            max(1, min(height, int(mon.wheight * fraction) - frame[1])))


def _frame(window) -> tuple[int, int]:
    """Extra width / height of the window frame (borders + title bar), measured once the window is shown."""
    try:
        if window.winfo_ismapped():
            fx = window.winfo_rootx() - window.winfo_x()
            fy = window.winfo_rooty() - window.winfo_y()
            if 0 <= fx < 60 and 0 <= fy < 120:
                return 2 * fx, fy + fx
    except tk.TclError:
        pass
    return FRAME_W, FRAME_H


def clamp(window, mon: Monitor | None = None) -> None:
    """Keep the window inside the free area of its monitor (after a restore, or a move to another monitor)."""
    try:
        if str(window.state()) == "zoomed":
            return
        window.update_idletasks()
        mon = mon or monitor_for(window)
        fw, fh = _frame(window)
        w, h = window.winfo_width(), window.winfo_height()
        if w <= 1 or h <= 1:                               # not laid out yet: use the requested geometry
            w, h = (int(v) for v in window.geometry().split("+")[0].split("x"))
        x, y = window.winfo_x(), window.winfo_y()
        nw, nh = min(w, mon.wwidth - fw), min(h, mon.wheight - fh)
        nx = min(max(x, mon.wx), mon.wx + mon.wwidth - (nw + fw))
        ny = min(max(y, mon.wy), mon.wy + mon.wheight - (nh + fh))
        if (nw, nh, nx, ny) != (w, h, x, y):
            window.geometry(f"{nw}x{nh}+{nx}+{ny}")
    except tk.TclError:
        pass


# ===================================================================== settings (QSettings-like)
class Settings:
    """A small JSON store for window geometries kept between sessions."""

    def __init__(self, path: str | None = None):
        if path is None:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            path = os.path.join(base, "SimStatsPlotter", "settings.json")
        self.path = path
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def set_value(self, key, value):
        self.data[key] = value
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1)
        except OSError:
            pass


# ===================================================================== fitting
class _Fitter:
    def __init__(self, window, key, width, height, settings, parent, content):
        self.window, self.key, self.settings, self.parent = window, key, settings, parent
        self.size, self.content = (width, height), content
        self._mon = None
        self._pending = False
        window.bind("<Configure>", self._on_configure, add="+")
        window.bind("<Destroy>", self._on_destroy, add="+")

    def _saved(self):
        if self.settings is not None:
            v = self.settings.value(f"window/{self.key}")
            if isinstance(v, dict) and v.get("geometry"):
                return v
        return _session.get(self.key)

    def natural_size(self):
        w, h = self.size
        if (w is None or h is None) and self.content is not None:
            self.window.update_idletasks()
            rw = self.content.winfo_reqwidth() + 24       # room for the scrollbars
            rh = self.window.winfo_reqheight() + self.content.winfo_reqheight() + 24
            w, h = w or rw, h or rh
        return w or 640, h or 480

    def place(self):
        mon = monitor_for(self.window, self.parent)
        saved = self._saved()
        if saved:
            try:
                self.window.geometry(saved["geometry"])
                if saved.get("zoomed"):
                    self.window.state("zoomed")
            except tk.TclError:
                saved = None
        if not saved:
            w, h = fitted(*self.natural_size(), mon)
            x = mon.wx + (mon.wwidth - (w + FRAME_W)) // 2
            y = mon.wy + (mon.wheight - (h + FRAME_H)) // 2
            self.window.geometry(f"{w}x{h}+{x}+{y}")
        self._mon = mon
        # once the window is on screen, check it against its real monitor and frame
        self.window.after(200, self._settle)

    def _settle(self):
        clamp(self.window)
        self._mon = monitor_for(self.window)

    def _on_configure(self, event):
        if event.widget is not self.window or self._pending:
            return
        self._pending = True
        self.window.after(300, self._check)

    def _check(self):
        self._pending = False
        try:
            if not self.window.winfo_exists():
                return
        except tk.TclError:
            return
        self.remember(persist=False)
        mon = monitor_for(self.window)
        if self._mon is not None and mon != self._mon:      # dragged to another monitor
            clamp(self.window, mon)
        self._mon = mon

    def remember(self, persist=True):
        try:
            zoomed = str(self.window.state()) == "zoomed"
            geo = self.window.geometry() if not zoomed else _session.get(self.key, {}).get("geometry")
        except tk.TclError:
            return
        if not geo or geo.startswith("1x1"):
            return
        value = {"geometry": geo, "zoomed": zoomed}
        _session[self.key] = value
        if persist and self.settings is not None:
            self.settings.set_value(f"window/{self.key}", value)

    def _on_destroy(self, event):
        """Keep the last size seen while the window was alive: at <Destroy> its menu bar is already gone,
        so the window would read 20 px taller and grow at every session."""
        if event.widget is self.window and self.settings is not None and self.key in _session:
            self.settings.set_value(f"window/{self.key}", _session[self.key])


def fit_to_screen(window, key: str, width: int | None = None, height: int | None = None,
                  settings: Settings | None = None, parent=None, content=None,
                  min_size: tuple[int, int] = MIN_SIZE) -> None:
    """Size and place ``window`` (a Tk / Toplevel) for the monitor it opens on (see the module text).

    *width* / *height*: the size asked for (``None`` = the natural size of *content*, e.g. a ScrollArea's
    body). *settings*: keep the size between sessions (main window). *parent*: the window it opens from."""
    window.resizable(True, True)
    window.minsize(*min_size)
    window._screen_fitter = _Fitter(window, key, width, height, settings, parent, content)
    window._screen_fitter.place()


# ===================================================================== scroll area
class ScrollArea(ttk.Frame):
    """The Tk counterpart of a ``QScrollArea(widgetResizable=True)``: put the content in ``.body``. The body
    fills the visible area, but never gets smaller than it asks to be; scroll bars appear only when the
    window is smaller than the content, so the window can be shrunk without cutting anything."""

    _SELF_SCROLLING = ("Listbox", "Text", "Treeview", "TCombobox", "Spinbox")

    def __init__(self, parent, fit_width: bool = False, **kw):
        """*fit_width*: a side column - it asks for the width of its content and scrolls vertically only
        (until the window is too narrow for it)."""
        super().__init__(parent, **kw)
        self.fit_width = fit_width
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, width=1, height=1)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body = ttk.Frame(self.canvas)
        self._item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self._last = None
        self.canvas.bind("<Configure>", lambda e: self._layout())
        self.body.bind("<Configure>", lambda e: self._layout())
        # the wheel is caught on the toplevel (every widget's events pass by it) - never with bind_all,
        # which other panels of the tool bind / unbind for their own scrolling
        top = self.winfo_toplevel()
        if not getattr(top, "_scrollarea_wheel", False):
            top.bind("<MouseWheel>", _toplevel_wheel, add="+")
            top._scrollarea_wheel = True
        self._sized = False
        if fit_width:
            self.after_idle(self._fit)
            self.bind("<Map>", lambda e: setattr(self, "_sized", False) if e.widget is self else None, add="+")
        self._job = self.after(400, self._watch)
        self.bind("<Destroy>", self._stop, add="+")

    def _stop(self, event):
        if event.widget is self and self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _fit(self):
        """Side column: ask for the content's width, so the column is not squeezed. In a PanedWindow the
        pane keeps the width it got when first shown (the content is not built yet then), so the sash is
        put at the content's width once each time the column is shown - later the user's drag wins."""
        try:
            rw = self.body.winfo_reqwidth()
            if int(float(self.canvas.cget("width"))) != rw:
                self.canvas.configure(width=rw)
            pw = self.master
            if (not self._sized and rw > 1 and isinstance(pw, ttk.PanedWindow) and self.winfo_ismapped()
                    and pw.winfo_width() > rw):
                panes = [str(p) for p in pw.panes()]
                i = panes.index(str(self))
                want = rw + self.vsb.winfo_reqwidth()
                if i < len(panes) - 1:
                    pw.sashpos(i, want)
                    pw.update_idletasks()
                # done once the column really got its width (retried by _watch until then)
                self._sized = self.winfo_width() >= want - 2 or i == len(panes) - 1
        except (tk.TclError, ValueError):
            pass

    def _layout(self):
        if self.fit_width:
            self._fit()
        try:
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            rw, rh = self.body.winfo_reqwidth(), self.body.winfo_reqheight()
        except tk.TclError:
            return
        if cw <= 1 or ch <= 1:
            return
        need_v, need_h = rh > ch + 1, rw > cw + 1
        state = (cw, ch, rw, rh, need_v, need_h)
        if state == self._last:
            return
        self._last = state
        w, h = max(cw, rw), max(ch, rh)
        self.canvas.itemconfigure(self._item, width=w, height=h)
        self.canvas.configure(scrollregion=(0, 0, w, h))
        for bar, need, pos in ((self.vsb, need_v, dict(row=0, column=1, sticky="ns")),
                               (self.hsb, need_h, dict(row=1, column=0, sticky="ew"))):
            if need and not bar.winfo_ismapped():
                bar.grid(**pos)
            elif not need and bar.winfo_ismapped():
                bar.grid_remove()

    def _watch(self):
        """The body's requested size changes without any event (widgets added / re-laid out): re-check it."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._layout()
        self._job = self.after(400, self._watch)



def _toplevel_wheel(event):
    """Mouse wheel over a ScrollArea that has a vertical scroll bar: scroll it. Widgets that scroll by
    themselves (lists, text, tables) keep the wheel."""
    w = event.widget
    try:
        if isinstance(w, str) or w.winfo_class() in ScrollArea._SELF_SCROLLING:
            return
    except tk.TclError:
        return
    while w is not None:
        if isinstance(w, tk.Canvas) and not isinstance(w.master, ScrollArea):
            try:
                if w.cget("yscrollcommand"):               # a scrolling canvas of its own (panels, plot stacks)
                    return
            except tk.TclError:
                pass
        if isinstance(w, ScrollArea):
            if w.vsb.winfo_ismapped():
                w.canvas.yview_scroll(int(-(event.delta / 120)), "units")
                return
        w = getattr(w, "master", None)


def scroll_body(window, **pack):
    """A ScrollArea filling *window* (or the rest of it); returns the frame to build the content in."""
    area = ScrollArea(window)
    area.pack(fill="both", expand=True, **pack)
    return area.body


def scroll_column(parent, padding=6):
    """A side column (control panel) that scrolls vertically when the window is low: returns the outer
    widget (to pack / add to a PanedWindow) and the frame to build the controls in."""
    area = ScrollArea(parent, fit_width=True)
    inner = ttk.Frame(area.body, padding=padding)
    inner.pack(fill="both", expand=True)
    return area, inner


def flexible(canvas_widget, width=320, height=240):
    """A matplotlib canvas asks for the size of its figure (e.g. 1100 x 700 px), which would make its
    window that big; ask for a small size instead - it still fills the space it gets."""
    canvas_widget.configure(width=width, height=height)
