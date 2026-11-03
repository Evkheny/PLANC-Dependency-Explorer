r"""UI smoke test with screenshots (uses the model saved in %APPDATA%\PLANC_Dependency_Explorer, so run a build first).
Usage: python tests/ui_smoke.py <out folder>   (needs pillow). Writes ui1.png (compare A/B, only A!=B, PitchTrajectoryTables),
ui2.png (values-per-type popup), ui3.png (STC1-emulated function with outside-model parameters), ui4.png (Tuning overview
tab of RotorSpeedFilter with the DLCs of the project simulation, if one is configured), ui5.png (overview window opened from
the centre box) and ui6.png (Load cases window)."""
import ctypes, ctypes.wintypes, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import planc_explorer as pe  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else '.'
app = pe.Explorer()
app.state('zoomed')


def grab(w, name):
    """Window capture with PrintWindow (works while other windows cover it)."""
    from PIL import Image
    w.update()
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    hwnd = int(w.wm_frame(), 16)
    r = ctypes.wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    wd, ht = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, wd, ht)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, 2)
    buf = ctypes.create_string_buffer(wd * ht * 4)
    bi = (ctypes.c_uint32 * 10)(40, wd, (-ht) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
    g.GetDIBits(mdc, bmp, 0, ht, buf, ctypes.byref(bi), 0)
    Image.frombuffer('RGBA', (wd, ht), buf, 'raw', 'BGRA', 0, 1).convert('RGB').save(os.path.join(out, name))
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(hwnd, hdc)


def s1():
    app.only_diff.set(True)
    app.fill_tree()
    app.navigate('PitchTrajectoryTables')
    app.after(1500, s2)


def s2():
    grab(app, 'ui1.png')
    app.t_par.focus(app.t_par.get_children()[0])
    app.on_par_dbl(None)
    app.after(1500, s3)


def s3():
    w = [c for c in app.winfo_children() if str(c).startswith('.!toplevel')][-1]
    grab(w, 'ui2.png')
    w.destroy()
    app.only_diff.set(False)
    app.fill_tree()
    app.navigate('OperationWithIce_Helper')
    app.nb.select(1)
    app.after(1500, s4)


def s4():
    grab(app, 'ui3.png')
    app.navigate('RotorSpeedFilter')
    app.nb.select(0)
    wait_sim(s5)


def wait_sim(then, n=0):
    if app.sims and not app.project_sims() and n < 120:       # project simulation still being read
        app.after(1000, lambda: wait_sim(then, n + 1))
    else:
        app.refresh_overview()
        app.after(800, then)


def s5():
    grab(app, 'ui4.png')
    app.overview_window('SpeedPitchController')
    app.after(1500, s6)


def s6():
    w = [c for c in app.winfo_children() if str(c).startswith('.!toplevel')][-1]
    grab(w, 'ui5.png')
    w.destroy()
    app.open_dlcs()
    app.after(3000, s7)


def s7():
    dw = [c for c in app.winfo_children() if str(c).startswith('.!toplevel')][-1]
    grab(dw, 'ui6.png')
    app.destroy()


app.after(2500, s1)
app.mainloop()
