"""UI smoke test with screenshots (uses the model saved in %APPDATA%\PLANC_Dependency_Explorer, so run a build first).
Usage: python tests/ui_smoke.py <out folder>   (needs pillow). Writes ui1.png (compare A/B, only A!=B, PitchTrajectoryTables),
ui2.png (values-per-type popup) and ui3.png (STC1-emulated function with outside-model parameters)."""
import ctypes, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ctypes.windll.shcore.SetProcessDpiAwareness(1)
import planc_explorer as pe  # noqa: E402
from PIL import ImageGrab  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else '.'
app = pe.Explorer()
app.state('zoomed')


def grab(w, name):
    w.update()
    x, y = w.winfo_rootx(), w.winfo_rooty()
    ImageGrab.grab((x, y, x + w.winfo_width(), y + w.winfo_height()), all_screens=True).save(os.path.join(out, name))


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
    app.nb.select(0)
    app.after(1500, s4)


def s4():
    grab(app, 'ui3.png')
    app.destroy()


app.after(2500, s1)
app.mainloop()
