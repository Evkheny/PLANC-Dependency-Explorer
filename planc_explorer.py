"""PLANC Dependency Explorer: visual navigation of the PLANC controller functions, their TDI signals (producer -> consumer),
parameters, type selections, owners and parameter values per type. Built only from three sources of the same release:
  - the PLANC repo 'Controller' folder (Simulink model; only read)
  - the Controller Description PDF
  - the CoPaD parameter-value export (parVal<version>.csv)
Optional: simulation folder(s) (only read): their load cases (DLCs) feed the tuning overview of each function and can be
viewed and compared in the Load cases window.
Run: python planc_explorer.py   (or the packaged PLANC_Dependency_Explorer.exe)"""
import json, os, sys, threading, traceback, collections, textwrap
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
sys.path.insert(0, HERE)
import planc_model  # noqa: E402
import overview  # noqa: E402
import dlcsetup  # noqa: E402
import dlcview  # noqa: E402

__version__ = '1.2.0'
APP = 'PLANC Dependency Explorer'
DATA = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'PLANC_Dependency_Explorer')
CFG = os.path.join(DATA, 'config.json')
CACHE = os.path.join(DATA, 'planc_model.json')
DLC_CACHE = os.path.join(DATA, 'dlccache')
PATHS = [('controller', 'PLANC "Controller" folder', 'dir'), ('cd', 'Controller Description (.pdf)', 'pdf'),
         ('copad', 'CoPaD parameter export (.csv)', 'csv')]
SUBAREA_COL = {'BladeActuation': '#7FB3D5', 'BladeMeasurementAndEstimation': '#76D7C4', 'FaultDetectionAndAccommodation': '#F1948A',
               'GridSupport': '#F8C471', 'LoadReductionHandles': '#BB8FCE', 'OperationalScheduling': '#F0B27A',
               'OperationalStatesAndTransitions': '#D7BDE2', 'OperationalTrajectories': '#A9DFBF', 'PowerSystemActuation': '#F9E79F',
               'RotorMeasurementAndEstimation': '#85C1E9', 'SpeedControl': '#82E0AA', 'TowerMeasurementAndEstimation': '#AED6F1',
               'WeatherMeasurementAndEstimation': '#A3E4D7', 'YawActuation': '#FAD7A0'}
INK, MUTED, BG, ACCENT, DIFF = '#1C2A30', '#5B6B73', '#F7F9FA', '#0B5563', '#FDEBD0'


class Explorer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP} {__version__}')
        self.geometry('1500x900')
        self.minsize(1100, 700)
        self.configure(bg=BG)
        st = ttk.Style(self)
        st.theme_use('clam')
        st.configure('Treeview', rowheight=22, font=('Segoe UI', 9))
        st.configure('Treeview.Heading', font=('Segoe UI', 9, 'bold'))
        st.configure('TNotebook.Tab', padding=(10, 4))
        st.configure('Accent.TButton', foreground='white', background=ACCENT)
        os.makedirs(DATA, exist_ok=True)
        self.cfg = self.load_cfg()
        self.M = None
        self.hist, self.hpos = [], -1
        self.sel = None
        self.sims = [p for p in self.cfg.get('sims', []) if p]     # simulation folders; the first = project simulation
        self.loaded = {}                                            # label -> dlcsetup.SimDlcs (shared with the DLC window)
        self.sim_msg = ''
        self.sim_err = {}
        self.build_ui()
        self.after(500, self.load_project_sim)
        if os.path.exists(CACHE):
            try:
                self.load_model(CACHE)
            except Exception:
                self.status('The saved model could not be read: press "Build model".')
        else:
            self.status('No model yet: select the three sources and press "Build model".')

    # ------------------------------------------------------------------ config
    def load_cfg(self):
        d = {}
        if os.path.exists(CFG):
            try:
                d.update(json.load(open(CFG, encoding='utf8')))
            except Exception:
                pass
        return d

    def save_cfg(self):
        d = {k: v.get() for k, v in self.pvars.items()}
        d.update(type=self.ty.get(), A=self.va.get(), B=self.vb.get(), sims=self.sims)
        try:
            json.dump(d, open(CFG, 'w', encoding='utf8'), indent=1)
        except OSError:
            pass

    # ------------------------------------------------------------------ layout
    def build_ui(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(fill='x')
        self.src_btn = ttk.Button(bar, text='Sources ▾', command=self.toggle_sources)
        self.src_btn.pack(side='left')
        ttk.Button(bar, text='Build model', style='Accent.TButton', command=self.rebuild).pack(side='left', padx=4)
        ttk.Button(bar, text='Load cases (DLCs)', command=self.open_dlcs).pack(side='left', padx=4)
        ttk.Button(bar, text='Help', command=self.help).pack(side='left', padx=4)
        # compare bar: type selection + two type values
        cmp_ = ttk.Frame(bar)
        cmp_.pack(side='right')
        ttk.Label(cmp_, text='Compare values of').pack(side='left')
        self.ty = tk.StringVar(value=self.cfg.get('type', 'WTGType'))
        self.va, self.vb = tk.StringVar(value=self.cfg.get('A', '')), tk.StringVar(value=self.cfg.get('B', ''))
        self.cb_ty = ttk.Combobox(cmp_, textvariable=self.ty, width=11, state='readonly')
        self.cb_ty.pack(side='left', padx=3)
        ttk.Label(cmp_, text='A').pack(side='left')
        self.cb_a = ttk.Combobox(cmp_, textvariable=self.va, width=28, state='readonly')
        self.cb_a.pack(side='left', padx=3)
        ttk.Label(cmp_, text='B').pack(side='left')
        self.cb_b = ttk.Combobox(cmp_, textvariable=self.vb, width=28, state='readonly')
        self.cb_b.pack(side='left', padx=3)
        self.cb_ty.bind('<<ComboboxSelected>>', lambda e: self.on_type())
        for cb in (self.cb_a, self.cb_b):
            cb.bind('<<ComboboxSelected>>', lambda e: self.on_compare())

        top = ttk.Frame(self, padding=(8, 0, 8, 6))
        self.top = top
        self.src_open = True
        top.pack(fill='x')
        self.pvars = {}
        files = ttk.LabelFrame(top, text=' Sources - all three of the same PLANC release (remembered) ', padding=6)
        files.pack(side='left', fill='x', expand=True)
        for i, (k, lab, kind) in enumerate(PATHS):
            ttk.Label(files, text=lab).grid(row=i, column=0, sticky='e', padx=(6, 3), pady=1)
            v = tk.StringVar(value=self.cfg.get(k, ''))
            self.pvars[k] = v
            ttk.Entry(files, textvariable=v, width=110).grid(row=i, column=1, sticky='we', pady=1)
            ttk.Button(files, text='...', width=3, command=lambda k=k, kind=kind: self.browse(k, kind)).grid(row=i, column=2, padx=2)
        ttk.Label(files, foreground=MUTED, text='CoPaD: export the parameter values (csv) of the PLANC version to analyse from the '
                  'CoPaD parameter database.').grid(row=3, column=1, sticky='w')
        files.columnconfigure(1, weight=1)
        sf = ttk.LabelFrame(top, text=' Simulations (optional, only read) ', padding=6)
        sf.pack(side='left', fill='both', padx=(6, 0))
        self.sim_lb = tk.Listbox(sf, height=4, width=46, exportselection=False)
        self.sim_lb.grid(row=0, column=0, rowspan=3, sticky='nsew')
        ttk.Button(sf, text='Add...', width=9, command=self.add_sim).grid(row=0, column=1, padx=3)
        ttk.Button(sf, text='Remove', width=9, command=self.del_sim).grid(row=1, column=1, padx=3)
        ttk.Button(sf, text='To top', width=9, command=self.top_sim).grid(row=2, column=1, padx=3)
        ttk.Label(sf, foreground=MUTED, wraplength=420, justify='left',
                  text='The FIRST one is the project simulation: its DLCs fill "Relevant DLCs" of the tuning overview. '
                  'The others can be compared in "Load cases (DLCs)".').grid(row=3, column=0, columnspan=2, sticky='w')
        self.fill_sims()

        main = ttk.PanedWindow(self, orient='horizontal')
        self.main = main
        main.pack(fill='both', expand=True, padx=8, pady=(0, 4))
        self.after(300, self.place_sashes)
        # left: search + tree
        left = ttk.Frame(main)
        main.add(left, weight=1)
        sf = ttk.Frame(left)
        sf.pack(fill='x')
        ttk.Label(sf, text='Search function / signal / parameter / STC1 Par:').pack(anchor='w')
        self.q = tk.StringVar()
        ttk.Entry(sf, textvariable=self.q).pack(fill='x')
        self.q.trace_add('write', lambda *_: self.fill_tree())
        opt = ttk.Frame(left)
        opt.pack(fill='x', pady=3)
        self.show_h = tk.BooleanVar(value=False)
        self.only_typed = tk.BooleanVar(value=False)
        self.only_diff = tk.BooleanVar(value=False)
        self.only_tuned = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text='test helpers', variable=self.show_h, command=self.fill_tree).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(opt, text='only type-dependent', variable=self.only_typed, command=self.fill_tree).grid(row=0, column=1, sticky='w')
        ttk.Checkbutton(opt, text='only where A ≠ B', variable=self.only_diff, command=self.fill_tree).grid(row=1, column=1, sticky='w')
        ttk.Checkbutton(opt, text='with tuning overview', variable=self.only_tuned, command=self.fill_tree).grid(row=1, column=0, sticky='w')
        self.tree = ttk.Treeview(left, columns=('tune', 'typed', 'diff'), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='Function (Simulink component)')
        self.tree.heading('tune', text='Tun.')
        self.tree.heading('typed', text='Typed')
        self.tree.heading('diff', text='A≠B')
        self.tree.column('#0', width=240)
        self.tree.column('tune', width=36, anchor='center')
        self.tree.column('typed', width=48, anchor='center')
        self.tree.column('diff', width=44, anchor='center')
        ysb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        ysb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.on_tree)
        # centre: graph
        mid = ttk.Frame(main)
        main.add(mid, weight=4)
        nav = ttk.Frame(mid)
        nav.pack(fill='x')
        ttk.Button(nav, text='< Back', command=lambda: self.go_hist(-1)).pack(side='left')
        ttk.Button(nav, text='Forward >', command=lambda: self.go_hist(1)).pack(side='left', padx=4)
        self.title_lbl = ttk.Label(nav, text='', font=('Segoe UI', 12, 'bold'), foreground=ACCENT)
        self.title_lbl.pack(side='left', padx=10)
        nav2 = ttk.Frame(mid)
        nav2.pack(fill='x', pady=(2, 0))
        ttk.Label(nav2, text='Graph:').pack(side='left')
        self.gmode = tk.StringVar(value='signals')
        for v, lab in (('signals', 'signal links'), ('tuning', 'tuning couplings')):
            ttk.Radiobutton(nav2, text=lab, value=v, variable=self.gmode,
                            command=lambda: self.show(self.sel, False)).pack(side='left', padx=4)
        self.ext = tk.BooleanVar(value=False)
        ttk.Checkbutton(nav2, text='show platform (STC1) inputs / unused outputs', variable=self.ext,
                        command=lambda: self.show(self.sel, False)).pack(side='right')
        cf = ttk.Frame(mid)
        cf.pack(fill='both', expand=True)
        self.cv = tk.Canvas(cf, bg='white', highlightthickness=0)
        vs = ttk.Scrollbar(cf, orient='vertical', command=self.cv.yview)
        self.cv.configure(yscrollcommand=vs.set)
        self.cv.pack(side='left', fill='both', expand=True)
        vs.pack(side='right', fill='y')
        self.cv.bind('<Configure>', lambda e: self.show(self.sel, False))
        self.cv.bind_all('<MouseWheel>', lambda e: self.cv.yview_scroll(int(-e.delta / 120), 'units')
                         if str(e.widget).startswith(str(self.cv)) else None)
        self.tip = None
        # right: details
        right = ttk.Notebook(main)
        main.add(right, weight=3)
        self.nb = right
        f = ttk.Frame(right)
        right.add(f, text='Tuning overview')
        self.ov_main = self.ov_frame(f)
        self.t_par = self.table(right, 'Parameters', ('par', 'stc1', 'type', 'owner', 'a', 'b', 'min', 'max', 'unit', 'desc'),
                                ('Parameter', 'STC1', 'Type sel.', 'Owner', 'Value A', 'Value B', 'Min', 'Max', 'Unit', 'Description'),
                                (200, 75, 75, 105, 80, 80, 55, 55, 45, 300))
        self.t_sig = self.table(right, 'Signals', ('dir', 'signal', 'peer', 'unit', 'desc'),
                                ('In/Out', 'Signal (TDI)', 'Producer / consumers', 'Unit', 'Description'), (55, 190, 220, 50, 320))
        self.t_typ = self.table(right, 'Type selections', ('type', 'n', 'how'), ('Type selection', 'Parameters / use', 'How'),
                                (110, 150, 420))
        f = ttk.Frame(right)
        right.add(f, text='Description')
        self.txt = tk.Text(f, wrap='word', font=('Segoe UI', 10), padx=10, pady=8, relief='flat')
        self.txt.pack(fill='both', expand=True)
        self.t_sig.bind('<Double-1>', self.on_sig_dbl)
        self.t_par.bind('<Double-1>', self.on_par_dbl)
        self.sb = ttk.Label(self, text='', anchor='w', padding=(8, 2))
        self.sb.pack(fill='x')

    def toggle_sources(self):
        self.src_open = not self.src_open
        if not self.src_open:
            self.top.pack_forget()
            self.src_btn.configure(text='Sources ▸')
        else:
            self.top.pack(fill='x', before=self.main)
            self.src_btn.configure(text='Sources ▾')

    def place_sashes(self):
        w = self.main.winfo_width()
        if w > 900:
            self.main.sashpos(0, int(w * 0.2))
            self.main.sashpos(1, int(w * 0.64))
        self.show(self.sel, False)

    def table(self, nb, title, cols, heads, widths):
        f = ttk.Frame(nb)
        nb.add(f, text=title)
        t = ttk.Treeview(f, columns=cols, show='headings')
        for c, h, w in zip(cols, heads, widths):
            t.heading(c, text=h, command=lambda c=c, t=t: self.sort(t, c))
            t.column(c, width=w, stretch=c in ('desc', 'how'))
        y = ttk.Scrollbar(f, orient='vertical', command=t.yview)
        x = ttk.Scrollbar(f, orient='horizontal', command=t.xview)
        t.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        t.grid(row=0, column=0, sticky='nsew')
        y.grid(row=0, column=1, sticky='ns')
        x.grid(row=1, column=0, sticky='ew')
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        t.tag_configure('typed', foreground='#B03A2E')
        t.tag_configure('diff', background=DIFF)
        t.tag_configure('in', foreground='#1A5276')
        t.tag_configure('out', foreground='#196F3D')
        t.tag_configure('outside', foreground='#7D3C98')
        return t

    def sort(self, t, c):
        rows = [(t.set(i, c), i) for i in t.get_children('')]
        rev = getattr(t, '_rev', False)
        rows.sort(reverse=rev)
        for n, (_, i) in enumerate(rows):
            t.move(i, '', n)
        t._rev = not rev

    def status(self, s):
        self.sb.configure(text=s)
        self.update_idletasks()

    # ------------------------------------------------------------------ data
    def browse(self, k, kind):
        cur = self.pvars[k].get()
        start = cur if os.path.isdir(cur) else os.path.dirname(cur) if cur else os.path.expanduser('~')
        if kind == 'dir':
            p = filedialog.askdirectory(initialdir=start, title='PLANC repo "Controller" folder (contains Subareas and Shared)')
        else:
            ft = {'pdf': [('Controller Description', '*.pdf')], 'csv': [('CoPaD export', '*.csv')]}[kind]
            p = filedialog.askopenfilename(initialdir=start, filetypes=ft + [('All', '*.*')])
        if p:
            self.pvars[k].set(os.path.normpath(p))
            self.save_cfg()

    def rebuild(self):
        self.save_cfg()
        v = {k: (x.get().strip() or None) for k, x in self.pvars.items()}
        if not v['controller'] or not os.path.isdir(os.path.join(v['controller'], 'Subareas')):
            messagebox.showerror('PLANC folder', 'Select the "Controller" folder of the PLANC repo (it contains Subareas and Shared).')
            return
        miss = [lab for k, lab, _ in PATHS[1:] if not v[k] or not os.path.isfile(v[k])]
        if miss and not messagebox.askyesno(APP, 'Not found: ' + ', '.join(miss) + '.\n\nBuild the model without it '
                                            '(no parameter values / no Controller Description)?'):
            return

        def prog(msg):
            self.after(0, lambda: self.status(msg))

        def work():
            try:
                m = planc_model.build(v['controller'], v['cd'] if v['cd'] and os.path.isfile(v['cd']) else None,
                                      v['copad'] if v['copad'] and os.path.isfile(v['copad']) else None, progress=prog)
                json.dump(m, open(CACHE, 'w', encoding='utf8'), default=str)
                self.after(0, lambda: self.load_model(CACHE))
            except Exception:
                err = traceback.format_exc()
                self.after(0, lambda: (self.status('Build failed.'), messagebox.showerror('Build failed', err[-2000:])))
        self.status('Building the model (read only)...')
        threading.Thread(target=work, daemon=True).start()

    def load_model(self, path):
        self.M = json.load(open(path, encoding='utf8'))
        C = self.M['components']
        self.edges_in, self.edges_out = collections.defaultdict(list), collections.defaultdict(list)
        for e in self.M['edges']:
            self.edges_out[e['src']].append(e)
            self.edges_in[e['dst']].append(e)
        self.outside_by_sec = collections.defaultdict(list)
        for p, v in self.M.get('outside_model_params', {}).items():
            for s in v.get('cd_sections', []):
                self.outside_by_sec[s].append(p)
        tv = self.M['meta'].get('type_values', {})
        self.cb_ty['values'] = sorted(tv, key=lambda t: (t != 'WTGType', t))
        if self.ty.get() not in tv:
            self.ty.set('WTGType' if 'WTGType' in tv else (sorted(tv)[0] if tv else ''))
        self.on_type(keep=True)
        m = self.M['meta']
        self.status(f"Model {m['built']}: {len(C)} functions, {len(self.M['signals'])} signals, {len(self.M['edges'])} links, "
                    f"{len(self.M['parameters'])} parameters ({m.get('n_copad', 0)} in CoPaD) | {m['controller']}")
        if self.src_open:
            self.toggle_sources()
        start = self.sel if self.sel in C else ('SpeedPitchController' if 'SpeedPitchController' in C else next(iter(C)))
        self.navigate(start)

    def on_type(self, keep=False):
        vals = self.M['meta'].get('type_values', {}).get(self.ty.get(), []) if self.M else []
        for cb, var in ((self.cb_a, self.va), (self.cb_b, self.vb)):
            cb['values'] = [''] + vals
            if not keep or var.get() not in vals:
                var.set('')
        self.on_compare()

    def on_compare(self):
        self.save_cfg()
        self.fill_tree()
        if self.sel:
            self.details(self.sel)

    # ------------------------------------------------------------------ type values
    def pval(self, v, which):
        """Value of parameter dict v for type value A/B (only if it depends on the compared type selection)."""
        tv = self.va.get() if which == 'A' else self.vb.get()
        if not v.get('values'):
            return ''
        if not v.get('type'):
            return v['values'].get('', '')
        if v['type'] != self.ty.get() or not tv:
            return f"({len(set(v['values'].values()))} values)" if which == 'A' else ''
        return v['values'].get(tv, '-')

    def differs(self, v):
        a, b = self.va.get(), self.vb.get()
        return bool(a and b and v.get('type') == self.ty.get() and v.get('values', {}).get(a) != v.get('values', {}).get(b))

    def comp_stats(self, c):
        P = self.M['parameters']
        typed = sum(1 for p in c['parameters'] if P.get(p, {}).get('type') == self.ty.get())
        out = [self.M['outside_model_params'][p] for p in self.outside_by_sec.get(c.get('cd_section'), [])] if c['kind'] == 'stc1' else []
        typed += sum(1 for v in out if v.get('type') == self.ty.get())
        diff = sum(1 for p in c['parameters'] if self.differs(P.get(p, {}))) + sum(1 for v in out if self.differs(v))
        return typed, diff

    # ------------------------------------------------------------------ tree
    def fill_tree(self):
        if not self.M:
            return
        t = self.tree
        t.delete(*t.get_children())
        q = self.q.get().strip().lower()
        C, S, P = self.M['components'], self.M['signals'], self.M['parameters']
        hit_sig = {n for s, v in S.items() if q in s.lower() for n in v['producers'] + v['consumers']} if len(q) > 2 else set()
        hit_par = {n for p, v in P.items() if q in p.lower() or q == str(v.get('mapping', '')).lower() for n in v['users']} \
            if len(q) > 2 else set()
        groups = collections.defaultdict(list)
        for n, c in C.items():
            if c['kind'] == 'harness' and not self.show_h.get():
                continue
            typed, diff = self.comp_stats(c)
            if self.only_typed.get() and not typed:
                continue
            if self.only_diff.get() and not diff:
                continue
            if self.only_tuned.get() and not overview.tasks_for(n):
                continue
            txt = (n + ' ' + c['short']).lower()
            if q and q not in txt and n not in hit_sig and n not in hit_par:
                continue
            groups[c['subarea']].append((n, typed, diff))
        for sa in sorted(groups):
            gid = t.insert('', 'end', text=sa, open=bool(q) or self.only_diff.get() or len(groups) < 4, tags=(sa,))
            t.tag_configure(sa, background=SUBAREA_COL.get(sa, '#EEE'))
            for n, typed, diff in sorted(groups[sa]):
                c = C[n]
                lab = n + ('  [STC1 emul.]' if c['kind'] == 'stc1' else '  [helper]' if c['kind'] == 'harness' else '')
                t.insert(gid, 'end', iid=n, text=lab, values=('●' if overview.tasks_for(n) else '', typed or '', diff or ''))

    def on_tree(self, _):
        s = self.tree.selection()
        if s and s[0] in self.M['components']:
            self.navigate(s[0])

    # ------------------------------------------------------------------ navigation + drawing
    def navigate(self, n):
        if self.hpos < len(self.hist) - 1:
            self.hist = self.hist[:self.hpos + 1]
        self.hist.append(n)
        self.hpos = len(self.hist) - 1
        self.show(n)

    def go_hist(self, d):
        if 0 <= self.hpos + d < len(self.hist):
            self.hpos += d
            self.show(self.hist[self.hpos])

    def show(self, n, details=True):
        if not self.M or not n:
            return
        self.sel = n
        c = self.M['components'][n]
        if self.tree.exists(n):
            self.tree.see(n)
        sec = c.get('cd_section')
        self.title_lbl.configure(text=f"{n}  ({c['short']})" + (f"   CD {sec}" if sec else ''))
        if self.gmode.get() == 'tuning':
            self.draw_tuning(n)
        else:
            self.draw(n)
        if details:
            self.details(n)

    def draw(self, n):
        cv = self.cv
        cv.delete('all')
        C = self.M['components']
        W = max(cv.winfo_width(), 700)
        ins = sorted(self.edges_in[n], key=lambda e: (C[e['src']]['subarea'], e['src']))
        outs = sorted(self.edges_out[n], key=lambda e: (C[e['dst']]['subarea'], e['dst']))
        sig = self.M['signals']
        c = C[n]
        ext_in = [s for s in c['inputs'] if not sig.get(s, {}).get('producers')] if self.ext.get() else []
        ext_out = [s for s in c['outputs'] if not [x for x in sig.get(s, {}).get('consumers', []) if x != n]] if self.ext.get() else []
        rowh, top = 46, 60
        nrows = max(len(ins) + (1 if ext_in else 0), len(outs) + (1 if ext_out else 0), 1)
        H = top + nrows * rowh + 40
        cv.configure(scrollregion=(0, 0, W, max(H, cv.winfo_height())))
        bw = min(240, int(W * 0.22))
        xl, xr, xc = 20, W - 20 - bw, W / 2
        cy = top + (nrows * rowh) / 2
        cw, ch = min(280, int(W * 0.24)), 132
        gap = (W - 40 - 2 * bw - cw) / 2 - 16          # free width for the signal labels between the boxes
        maxc = max(6, int(gap / 6.5))
        self.box(xc - cw / 2, cy - ch / 2, cw, ch, n, c, centre=True)
        cv.create_text(xl, 25, text=f'INPUTS FROM  ({len(ins)} functions, {len(c["inputs"])} signals)', fill=MUTED,
                       font=('Segoe UI', 9, 'bold'), anchor='w')
        cv.create_text(xr + bw, 25, text=f'OUTPUTS TO  ({len(outs)} functions, {len(c["outputs"])} signals)', fill=MUTED,
                       font=('Segoe UI', 9, 'bold'), anchor='e')

        def lab(sigs):
            s = sigs[0] + (f' +{len(sigs) - 1}' if len(sigs) > 1 else '')
            return s if len(s) <= maxc else s[:maxc - 1] + '…'
        for i, e in enumerate(ins):
            y = top + i * rowh + rowh / 2 + (nrows - len(ins) - (1 if ext_in else 0)) * rowh / 2
            self.box(xl, y - 17, bw, 34, e['src'], C[e['src']])
            a = cv.create_line(xl + bw, y, xc - cw / 2, cy - ch / 2 + 12 + (ch - 24) * (i + 0.5) / max(len(ins), 1),
                               arrow='last', fill='#1A5276', width=1.4, smooth=True)
            t = cv.create_text(xl + bw + 8, y - 8, text=lab(e['signals']), anchor='w', fill='#1A5276', font=('Consolas', 8))
            for it in (a, t):
                self.hover(it, '\n'.join(e['signals']))
        if ext_in:
            y = top + len(ins) * rowh + rowh / 2 + (nrows - len(ins) - 1) * rowh / 2
            r = cv.create_rectangle(xl, y - 17, xl + bw, y + 17, fill='#ECEFF1', outline='#B0BEC5', dash=(3, 2))
            cv.create_text(xl + bw / 2, y, text=f'STC1 / platform: {len(ext_in)} signals', fill=MUTED, font=('Segoe UI', 9, 'italic'))
            self.hover(r, '\n'.join(ext_in))
        for i, e in enumerate(outs):
            y = top + i * rowh + rowh / 2 + (nrows - len(outs) - (1 if ext_out else 0)) * rowh / 2
            self.box(xr, y - 17, bw, 34, e['dst'], C[e['dst']])
            a = cv.create_line(xc + cw / 2, cy - ch / 2 + 12 + (ch - 24) * (i + 0.5) / max(len(outs), 1), xr, y,
                               arrow='last', fill='#196F3D', width=1.4, smooth=True)
            t = cv.create_text(xr - 8, y - 8, text=lab(e['signals']), anchor='e', fill='#196F3D', font=('Consolas', 8))
            for it in (a, t):
                self.hover(it, '\n'.join(e['signals']))
        if ext_out:
            y = top + len(outs) * rowh + rowh / 2 + (nrows - len(outs) - 1) * rowh / 2
            r = cv.create_rectangle(xr, y - 17, xr + bw, y + 17, fill='#ECEFF1', outline='#B0BEC5', dash=(3, 2))
            cv.create_text(xr + bw / 2, y, text=f'STC1 / logging: {len(ext_out)} signals', fill=MUTED, font=('Segoe UI', 9, 'italic'))
            self.hover(r, '\n'.join(ext_out))
        vis = max(cv.winfo_height(), 300)
        cv.yview_moveto(max(0.0, (cy - vis / 2) / max(H, vis)))
        cv.create_text(W / 2, H - 14, text='Click a box to navigate (centre box: tuning overview) - hover an arrow for all its signals - colours = subarea - '
                       'orange border = parameters differ between A and B', fill=MUTED, font=('Segoe UI', 8))

    def draw_tuning(self, n):
        """Tuning couplings (complement of the signal graph): left = functions whose tuning highly affects this one,
        right = functions whose tuning must be repeated or re-checked when this one changes. Hover = physical reason."""
        cv = self.cv
        cv.delete('all')
        C = self.M['components']
        W = max(cv.winfo_width(), 700)
        ins, outs = overview.couplings(n)
        T = {t['key']: t['name'] for t in overview.all_tasks()}
        rowh, top = 46, 60
        nrows = max(len(ins), len(outs), 1)
        H = top + nrows * rowh + 40
        cv.configure(scrollregion=(0, 0, W, max(H, cv.winfo_height())))
        bw = min(240, int(W * 0.22))
        xl, xr, xc = 20, W - 20 - bw, W / 2
        cy = top + (nrows * rowh) / 2
        cw, ch = min(280, int(W * 0.24)), 132
        self.box(xc - cw / 2, cy - ch / 2, cw, ch, n, C[n], centre=True)
        cv.create_text(xl, 25, text=f'TUNING HIGHLY AFFECTED BY  ({len(ins)})', fill=MUTED, font=('Segoe UI', 9, 'bold'),
                       anchor='w')
        cv.create_text(xr + bw, 25, text=f'TUNING HIGHLY AFFECTS  ({len(outs)})', fill=MUTED, font=('Segoe UI', 9, 'bold'),
                       anchor='e')

        def tip(items):
            return '\n\n'.join(f'{T.get(a, a)} -> {T.get(b, b)}:\n' + textwrap.fill(r, 90) for a, b, r in items)

        def peer_box(x, y, pid, label, comp):
            if comp in C:
                self.box(x, y - 17, bw, 34, comp, C[comp])
            else:                                       # task without a Simulink function (or outside the model)
                cv.create_rectangle(x, y - 17, x + bw, y + 17, fill='#ECEFF1', outline='#90A4AE')
                cv.create_text(x + 8, y, text=label, anchor='w', font=('Segoe UI', 9, 'bold'), fill=INK, width=bw - 12)
        if not ins and not outs:
            cv.create_text(W / 2, cy + ch / 2 + 30, text='No strong tuning coupling recorded for this function.', fill=MUTED,
                           font=('Segoe UI', 10, 'italic'))
        for i, (pid, label, comp, items) in enumerate(ins):
            y = top + i * rowh + rowh / 2 + (nrows - len(ins)) * rowh / 2
            peer_box(xl, y, pid, label, comp)
            a = cv.create_line(xl + bw, y, xc - cw / 2, cy - ch / 2 + 12 + (ch - 24) * (i + 0.5) / max(len(ins), 1),
                               arrow='last', fill='#7D3C98', width=2, smooth=True)
            self.hover(a, tip(items))
        for i, (pid, label, comp, items) in enumerate(outs):
            y = top + i * rowh + rowh / 2 + (nrows - len(outs)) * rowh / 2
            peer_box(xr, y, pid, label, comp)
            a = cv.create_line(xc + cw / 2, cy - ch / 2 + 12 + (ch - 24) * (i + 0.5) / max(len(outs), 1), xr, y,
                               arrow='last', fill='#B9770E', width=2, smooth=True)
            self.hover(a, tip(items))
        vis = max(cv.winfo_height(), 300)
        cv.yview_moveto(max(0.0, (cy - vis / 2) / max(H, vis)))
        cv.create_text(W / 2, H - 14, text='Tuning couplings (not signals): A -> B = changing the tunable parameters of A '
                       'requires re-tuning or re-checking B. Hover an arrow for the physical reason; click a box to navigate.',
                       fill=MUTED, font=('Segoe UI', 8), width=W - 20, justify='center')

    def box(self, x, y, w, h, name, c, centre=False):
        cv = self.cv
        col = SUBAREA_COL.get(c['subarea'], '#DDD')
        dash = (4, 2) if c['kind'] == 'stc1' else None
        typed, diff = self.comp_stats(c)
        outline = ACCENT if centre else ('#E67E22' if diff else '#7F8C8D')
        r = cv.create_rectangle(x, y, x + w, y + h, fill=col, outline=outline, width=3 if centre or diff else 1, dash=dash)
        if centre:
            fs = 11 if len(name) * 9 < w - 10 else 9 if len(name) * 7.5 < w - 10 else 8
            cv.create_text(x + w / 2, y + 20, text=name, font=('Segoe UI', fs, 'bold'), fill=INK, width=w - 10)
            cv.create_text(x + w / 2, y + 44, text=c['subarea'], font=('Segoe UI', 8), fill=INK, width=w - 10)
            txt = f"{len(c['parameters'])} parameters, {typed} depend on {self.ty.get()}" + (f', {diff} differ A/B' if diff else '')
            cv.create_text(x + w / 2, y + h - 42, text=txt, font=('Segoe UI', 8, 'italic'), fill='#B03A2E' if typed else MUTED,
                           width=w - 10)
            tasks = overview.tasks_for(name)
            t = cv.create_text(x + w / 2, y + h - 14, text='click: tuning overview' + (
                f' ({tasks[0]["key"]})' if len(tasks) == 1 else f' ({len(tasks)} tasks)' if tasks else ''), font=('Segoe UI', 8, 'underline'),
                fill=ACCENT, width=w - 10)
            for it in (r, t):
                cv.tag_bind(it, '<Button-1>', lambda e, n=name: self.overview_window(n))
                cv.tag_bind(it, '<Enter>', lambda e: self.cv.configure(cursor='hand2'))
                cv.tag_bind(it, '<Leave>', lambda e: self.cv.configure(cursor=''))
            return
        t = cv.create_text(x + 8, y + h / 2, text=name + (f'  [{diff} ≠]' if diff else ''), anchor='w',
                           font=('Segoe UI', 9, 'bold'), fill=INK, width=w - 12)
        for it in (r, t):
            cv.tag_bind(it, '<Button-1>', lambda e, n=name: self.navigate(n))
            cv.tag_bind(it, '<Enter>', lambda e: self.cv.configure(cursor='hand2'))
            cv.tag_bind(it, '<Leave>', lambda e: self.cv.configure(cursor=''))

    def hover(self, item, text):
        def enter(e):
            self.unhover()
            self.tip = tk.Toplevel(self)
            self.tip.wm_overrideredirect(True)
            self.tip.geometry(f'+{e.x_root + 12}+{e.y_root + 12}')
            tk.Label(self.tip, text=text, justify='left', bg='#FFFDE7', relief='solid', bd=1, font=('Consolas', 9)).pack()
        self.cv.tag_bind(item, '<Enter>', enter)
        self.cv.tag_bind(item, '<Leave>', lambda e: self.unhover())

    def unhover(self):
        if self.tip:
            self.tip.destroy()
            self.tip = None

    # ------------------------------------------------------------------ detail tabs
    def details(self, n):
        M = self.M
        C, S, P = M['components'], M['signals'], M['parameters']
        c = C[n]
        sec = c.get('cd_section')
        # parameters
        t = self.t_par
        t.delete(*t.get_children())
        rows = sorted(c['parameters'], key=lambda p: (not self.differs(P.get(p, {})), P.get(p, {}).get('type') != self.ty.get(),
                                                      not P.get(p, {}).get('type'), p))
        for p in rows:
            v = P.get(p, {})
            tags = (('typed',) if v.get('type') else ()) + (('diff',) if self.differs(v) else ())
            t.insert('', 'end', iid='p:' + p, values=(p, v.get('mapping', ''), v.get('type', ''), v.get('owner', ''),
                                                      self.pval(v, 'A'), self.pval(v, 'B'), v.get('min', ''), v.get('max', ''),
                                                      v.get('unit', ''), (v.get('description', '') or '') +
                                                      ('' if v.get('in_copad') else '  [not in the CoPaD export]')), tags=tags)
        if c['kind'] == 'stc1' or not c['parameters']:
            for p in sorted(self.outside_by_sec.get(sec, [])):
                v = M['outside_model_params'][p]
                tags = ('outside',) + (('diff',) if self.differs(v) else ())
                t.insert('', 'end', iid='o:' + p, values=(p + '  (STC1)', v.get('mapping', ''), v.get('type', ''), v.get('owner', ''),
                                                          self.pval(v, 'A'), self.pval(v, 'B'), v.get('min', ''), v.get('max', ''), '',
                                                          f'Not in the Simulink model; documented in CD {sec}'), tags=tags)
        # signals
        t = self.t_sig
        t.delete(*t.get_children())
        for s in c['inputs']:
            v = S.get(s, {})
            peer = ', '.join(v.get('producers', [])) or 'STC1 / platform'
            t.insert('', 'end', values=('IN', s, peer, v.get('unit', ''), v.get('description', '')), tags=('in',))
        for s in c['outputs']:
            v = S.get(s, {})
            peer = ', '.join(x for x in v.get('consumers', []) if C.get(x, {}).get('kind') != 'harness') or '(STC1 / logging)'
            t.insert('', 'end', values=('OUT', s, peer, v.get('unit', ''), v.get('description', '')), tags=('out',))
        # type selections
        t = self.t_typ
        t.delete(*t.get_children())
        for ty, k in sorted(c['type_param_count'].items(), key=lambda x: -x[1]):
            t.insert('', 'end', values=(ty, f'{k} parameters', 'parameter values change with this type selection (CoPaD)'),
                     tags=('typed',))
        for ty in c['typeselections']:
            d = M['typeselections'].get(ty, {})
            t.insert('', 'end', values=(ty, 'used in the logic (T_' + ty + ')', (d.get('description', '') + '  values: ' +
                                                                                  ', '.join(d.get('values', [])))))
        if sec and sec in M.get('cd', {}):
            for ty in M['cd'][sec]['types']:
                t.insert('', 'end', values=(ty, 'mentioned in the CD', f"Controller Description {sec}: |{ty}|"))
        self.fill_overview(self.ov_main, n)
        # description
        own = ', '.join(f'{o}: {k}' for o, k in sorted(c['owners'].items(), key=lambda x: -x[1]))
        tx = self.txt
        tx.configure(state='normal')
        tx.delete('1.0', 'end')
        tx.insert('end', f"{n}  ({c['short']})\n", 'h')
        tx.insert('end', f"Subarea: {c['subarea']}   Kind: {c['kind']}   Model: {c['path']}\n")
        if c.get('libraries'):
            tx.insert('end', 'Libraries: ' + ', '.join(c['libraries']) + '\n')
        tx.insert('end', f"Signals: {len(c['inputs'])} in, {len(c['outputs'])} out.  Parameters: {len(c['parameters'])} "
                         f"({sum(c['type_param_count'].values())} type-dependent).  Owners (CoPaD): {own or '-'}\n\n")
        if c.get('description'):
            tx.insert('end', c['description'] + '\n\n')
        if sec and sec in M.get('cd', {}):
            d = M['cd'][sec]
            tx.insert('end', f"Controller Description {sec} {d['title']}  (chapter {d.get('chapter', '')}, page {d.get('page', '')})\n", 'h2')
            tx.insert('end', (d.get('intro') or '(no introduction found)') + '\n')
        else:
            tx.insert('end', 'No Controller Description section with this name.\n')
        tx.tag_configure('h', font=('Segoe UI', 13, 'bold'), foreground=ACCENT)
        tx.tag_configure('h2', font=('Segoe UI', 11, 'bold'), foreground=ACCENT)
        tx.configure(state='disabled')

    def on_sig_dbl(self, _):
        i = self.t_sig.focus()
        if not i:
            return
        d, s, peer = self.t_sig.item(i, 'values')[:3]
        cands = [p.strip() for p in peer.split(',') if p.strip() in self.M['components']]
        if len(cands) == 1:
            self.navigate(cands[0])
        elif cands:
            m = tk.Menu(self, tearoff=0)
            for p in cands:
                m.add_command(label=p, command=lambda p=p: self.navigate(p))
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def on_par_dbl(self, _):
        """All values of the parameter per type value (CoPaD), A and B highlighted; other functions using it."""
        i = self.t_par.focus()
        if not i:
            return
        p = i[2:]
        v = (self.M['parameters'] if i.startswith('p:') else self.M['outside_model_params']).get(p, {})
        w = tk.Toplevel(self)
        w.title(f'{p}  -  values per {v.get("type") or "(no type selection)"}')
        w.geometry('620x560')
        hdr = (f"{p}   STC1 {v.get('mapping', '')}   owner {v.get('owner', '')}   min {v.get('min', '')}   max {v.get('max', '')}\n"
               f"Used by: {', '.join(v.get('users', [])) or ', '.join('CD ' + s for s in v.get('cd_sections', [])) or '-'}")
        ttk.Label(w, text=hdr, padding=8, wraplength=600).pack(fill='x')
        t = ttk.Treeview(w, columns=('tv', 'val'), show='headings')
        t.heading('tv', text=v.get('type') or 'Type value')
        t.heading('val', text='Value')
        t.column('tv', width=320)
        t.column('val', width=240)
        t.tag_configure('ab', background=DIFF)
        y = ttk.Scrollbar(w, orient='vertical', command=t.yview)
        t.configure(yscrollcommand=y.set)
        t.pack(side='left', fill='both', expand=True)
        y.pack(side='right', fill='y')
        for tv, val in sorted(v.get('values', {}).items()):
            mark = ('A' if tv == self.va.get() else '') + ('B' if tv == self.vb.get() else '')
            t.insert('', 'end', values=(tv + (f'   [{mark}]' if mark else ''), val), tags=('ab',) if mark else ())

    # ------------------------------------------------------------------ simulations (load cases)
    def sim_label(self, path):
        base = os.path.basename(path.rstrip('\\/')) or path
        same = [q for q in self.sims if (os.path.basename(q.rstrip('\\/')) or q) == base]
        return base if len(same) < 2 or same[0] == path else f'{base} ({same.index(path) + 1})'

    def fill_sims(self):
        self.sim_lb.delete(0, 'end')
        for i, q in enumerate(self.sims):
            lb = self.sim_label(q)
            st = '' if lb in self.loaded else '  (error)' if lb in self.sim_err else '  (not read yet)'
            self.sim_lb.insert('end', ('PROJECT  ' if i == 0 else '         ') + lb + st)

    def add_sim(self, path=None):
        path = path or filedialog.askdirectory(title='Simulation folder (the one holding Btc/, Res/ and Post/)')
        if not path:
            return
        path = os.path.normpath(path)
        if not os.path.isdir(os.path.join(path, 'Btc')):
            messagebox.showwarning(APP, 'No Btc folder in:\n' + path)
            return
        if path not in self.sims:
            self.sims.append(path)
        self.save_cfg()
        self.fill_sims()
        if len(self.sims) == 1:
            self.load_project_sim()

    def del_sim(self):
        s = self.sim_lb.curselection()
        if s:
            q = self.sims.pop(s[0])
            self.loaded.pop(self.sim_label(q), None)
            self.save_cfg()
            self.fill_sims()
            self.refresh_overview()

    def top_sim(self):
        s = self.sim_lb.curselection()
        if s and s[0] > 0:
            self.sims.insert(0, self.sims.pop(s[0]))
            self.save_cfg()
            self.fill_sims()
            self.load_project_sim()

    def project_sims(self):
        """Loaded simulations in the order of the list (the project simulation first)."""
        return [self.loaded[lb] for lb in map(self.sim_label, self.sims) if lb in self.loaded]

    def load_project_sim(self):
        """Read the load cases of the project simulation in the background (cached in %APPDATA%)."""
        if not self.sims:
            return
        path = self.sims[0]
        lb = self.sim_label(path)
        if lb in self.loaded or getattr(self, '_sim_busy', False):
            self.refresh_overview()
            return
        self._sim_busy = True
        self.sim_msg = f'Reading the load cases of {lb}...'
        self.refresh_overview()

        def work():
            try:
                self.loaded[lb] = dlcsetup.load_sim(lb, path, DLC_CACHE)
                self.sim_err.pop(lb, None)
                msg = ''
            except Exception as e:                    # noqa: BLE001 - shown to the user
                self.sim_err[lb] = str(e)
                msg = f'Load cases of {lb} could not be read: {e}'
            self.after(0, lambda: self.sims_done(msg))
        threading.Thread(target=work, daemon=True).start()

    def sims_done(self, msg=''):
        self._sim_busy = False
        self.sim_msg = msg
        self.fill_sims()
        self.refresh_overview()

    def open_dlcs(self):
        sims = {self.sim_label(q): q for q in self.sims}
        DlcWindow(self, sims, DLC_CACHE)

    # ------------------------------------------------------------------ tuning overview
    def ov_frame(self, parent):
        """Overview panel (tab or window): task selector, buttons and the rendered overview."""
        ov = type('Ov', (), {})()
        bar = ttk.Frame(parent, padding=(4, 4))
        bar.pack(fill='x')
        ttk.Label(bar, text='Tuning task').pack(side='left')
        ov.task = tk.StringVar()
        ov.cb = ttk.Combobox(bar, textvariable=ov.task, state='readonly', width=46)
        ov.cb.pack(side='left', padx=4)
        ov.cb.bind('<<ComboboxSelected>>', lambda e: self.render_overview(ov))
        ttk.Button(bar, text='Copy for Jira', command=lambda: self.copy_jira(ov)).pack(side='right')
        ttk.Button(bar, text='DLCs...', command=self.open_dlcs).pack(side='right', padx=4)
        f = ttk.Frame(parent)
        f.pack(fill='both', expand=True)
        ov.tx = tk.Text(f, wrap='word', font=('Segoe UI', 10), padx=10, pady=8, relief='flat', cursor='arrow')
        y = ttk.Scrollbar(f, orient='vertical', command=ov.tx.yview)
        ov.tx.configure(yscrollcommand=y.set)
        ov.tx.pack(side='left', fill='both', expand=True)
        y.pack(side='right', fill='y')
        tx = ov.tx
        tx.tag_configure('h', font=('Segoe UI', 13, 'bold'), foreground=ACCENT)
        tx.tag_configure('sub', foreground=MUTED)
        tx.tag_configure('row', font=('Segoe UI', 10, 'bold'), foreground='white', background=ACCENT, spacing1=10, spacing3=3,
                         lmargin1=0)
        tx.tag_configure('b', font=('Segoe UI', 10, 'bold'))
        tx.tag_configure('p', foreground='#B9770E', font=('Segoe UI', 10, 'italic'))
        tx.tag_configure('src', font=('Segoe UI', 9, 'bold'), foreground=MUTED, spacing1=6)
        tx.tag_configure('bul', lmargin1=14, lmargin2=26)
        tx.tag_configure('ind', lmargin1=26, lmargin2=26)
        tx.tag_configure('mono', font=('Consolas', 9))
        tx.tag_configure('miss', foreground='#B03A2E', font=('Segoe UI', 10, 'italic'))
        tx.tag_configure('lvl', font=('Segoe UI', 10, 'bold'), foreground='#1A5276')
        tx.tag_configure('link', foreground=ACCENT, underline=True)
        tx.tag_configure('note', foreground=MUTED, font=('Segoe UI', 9, 'italic'))
        tx.tag_bind('link', '<Enter>', lambda e: tx.configure(cursor='hand2'))
        tx.tag_bind('link', '<Leave>', lambda e: tx.configure(cursor='arrow'))
        ov.comp, ov.keys = None, []
        self.__dict__.setdefault('ovs', []).append(ov)
        return ov

    def fill_overview(self, ov, comp, key=None):
        ov.comp = comp
        own = overview.tasks_for(comp)
        free = [t for t in overview.all_tasks() if not t.get('comp')]
        ov.keys = [t['key'] for t in own] + ([None] if free else []) + [t['key'] for t in free]
        ov.cb['values'] = [f"{t['key']}  {t['name']}" for t in own] + (
            ['--- tasks not tied to one function ---'] if free else []) + [f"{t['key']}  {t['name']}" for t in free]
        cur = key or (own[0]['key'] if own else None)
        ov.task.set(next((v for k, v in zip(ov.keys, ov.cb['values']) if k and k == cur), ''))
        self.render_overview(ov)

    def refresh_overview(self):
        for ov in [o for o in getattr(self, 'ovs', []) if o.tx.winfo_exists()]:
            if ov.comp and self.M:
                self.render_overview(ov)

    def ov_task(self, ov):
        i = list(ov.cb['values']).index(ov.task.get()) if ov.task.get() in ov.cb['values'] else -1
        k = ov.keys[i] if i >= 0 else None
        return next((t for t in overview.all_tasks() if t['key'] == k), None)

    def md(self, tx, text, base=()):
        """Insert knowledge-base text: '- ' bullets, **bold**, [P] = proposed."""
        bullet = text.startswith('- ')
        if bullet:
            text = text[2:]
            tx.insert('end', '•  ', base + ('bul',))
        tags = base + (('bul',) if bullet else ())
        for i, part in enumerate(text.replace('[P]', '\x00').split('**')):
            for j, bit in enumerate(part.split('\x00')):
                if j:
                    tx.insert('end', '(proposed)', tags + ('p',))
                tx.insert('end', bit, tags + (('b',) if i % 2 else ()))
        tx.insert('end', '\n', tags)

    def render_overview(self, ov):
        if not self.M or not ov.comp:
            return
        M, comp, tx = self.M, ov.comp, ov.tx
        C = M['components']
        task = self.ov_task(ov)
        tx.configure(state='normal')
        tx.delete('1.0', 'end')
        c = C.get(comp, {})
        tcomp = task.get('comp') if task else comp
        if task:
            tx.insert('end', f"{task['key']}  {task['name']}\n", 'h')
            tx.insert('end', (f"Function {tcomp}" if tcomp else 'Not tied to one Simulink function') +
                      (f"   CD {task['cd']}" if task.get('cd') else '') + f"   {task.get('subarea', '')}\n", 'sub')
        else:
            tx.insert('end', f'{comp}\n', 'h')
            tx.insert('end', 'No tuning task in the knowledge base for this function: only the model information is shown. '
                             'Pick another task above.\n', 'sub')
        sims = self.project_sims()

        def row(title):
            tx.insert('end', f'  {title}  \n', 'row')

        def paras(lst):
            for x in lst:
                self.md(tx, x)
        if task:
            row('Name')
            tx.insert('end', task['name'] + '\n')
            row('Main Scope')
            paras(task['scope'])
            row('Tuning KPI')
            paras(task['kpi'])
            row('Relevant DLCs')
            paras(task['dlcs'])
            self.render_dlcs(tx, task, sims)
            row('Highly affected functionalities')
            paras(task['affects'])
            row('Highly affected by')
            paras(task['affected_by'])
            tx.insert('end', 'Tuning couplings with the physical reason (not signal links). The signal links are in the graph; '
                             '"Graph: tuning couplings" draws these couplings.\n', 'note')
        if task:
            row('Risk of not tuning')
            paras(task['risk'])
        if tcomp in C:
            row('Type-dependent parameters (CoPaD)')
            ty, a, b = self.ty.get(), self.va.get(), self.vb.get()
            n, diff = overview.type_params(M, tcomp, ty, a, b)
            tx.insert('end', f'{n} of {len(C[tcomp]["parameters"])} parameters depend on {ty}.')
            if a and b:
                tx.insert('end', f' {len(diff)} differ between A = {a} and B = {b}' + (':\n' if diff else '.\n'))
                for p_, x, y in diff[:40]:
                    tx.insert('end', f'{p_}:  {x}  →  {y}\n', ('ind', 'mono'))
                if len(diff) > 40:
                    tx.insert('end', f'... {len(diff) - 40} more (Parameters tab)\n', ('ind', 'note'))
            else:
                tx.insert('end', '  Pick A and B (top right) to list the values that change.\n', 'note')
        tx.insert('end', '\n(proposed) = proposed content, to be reviewed. Tuning gates are not shown. Knowledge base: '
                         f"{overview.kb().get('version', '')}.\n", 'note')
        tx.configure(state='disabled')

    def render_dlcs(self, tx, task, sims):
        tx.insert('end', 'Load cases of the project', 'src')
        if not sims:
            tx.insert('end', '\n')
            tx.insert('end', (self.sim_msg or 'Add the project simulation folder in Sources (Simulations) to see which of '
                              'these load cases the project runs and how they are set up.') + '\n', 'note')
            return
        tx.insert('end', f" ({sims[0].label}" + (', compared with ' + ', '.join(s.label for s in sims[1:]) if sims[1:] else '')
                  + ')\n', 'src')
        for level, codes, reason, found in overview.dlc_rows(task, sims):
            if not codes:
                continue
            tx.insert('end', f'{level}  ', ('lvl', 'bul'))
            tx.insert('end', 'DLC ' + ', '.join(codes) + '\n', ('b', 'bul'))
            for i, s in enumerate(sims):
                names = found.get(s.label, [])
                pre = '' if len(sims) == 1 else f'{s.label}: '
                if not names:
                    tx.insert('end', pre + 'not simulated\n', ('ind', 'miss'))
                    continue
                miss = [k for k in codes if not overview.match_dlcs([k], s)]
                if miss:
                    tx.insert('end', pre + 'not simulated: DLC ' + ', '.join(miss) + '\n', ('ind', 'miss'))
                tx.insert('end', pre, ('ind', 'note'))
                for j, (nm, desc) in enumerate(names):
                    tag = f'dlc{id(s)}_{nm}'
                    tx.insert('end', nm, ('ind', 'mono', 'link', tag))
                    tx.tag_bind(tag, '<Button-1>', lambda e, s=s, nm=nm: self.dlc_card(s, nm))
                    tx.tag_bind(tag, '<Enter>', lambda e, d=desc: self.status(d), add='+')
                    if j < len(names) - 1:
                        tx.insert('end', ',  ', 'ind')
                tx.insert('end', '\n', 'ind')
        tx.insert('end', 'Click a load case for its set-up; "DLCs..." to see all of them and compare simulations.\n', 'note')

    def dlc_card(self, sim, name):
        d = sim.dlcs[name]
        w = tk.Toplevel(self)
        w.title(f'{d.pretty}  {name}  ({sim.label})')
        w.geometry('760x640')
        tx = tk.Text(w, wrap='word', font=('Segoe UI', 10), padx=10, pady=8, relief='flat')
        y = ttk.Scrollbar(w, orient='vertical', command=tx.yview)
        tx.configure(yscrollcommand=y.set)
        tx.pack(side='left', fill='both', expand=True)
        y.pack(side='right', fill='y')
        tx.tag_configure('h', font=('Segoe UI', 12, 'bold'), foreground=ACCENT)
        tx.tag_configure('s', font=('Segoe UI', 10, 'bold'), foreground='white', background=ACCENT, spacing1=8)
        tx.tag_configure('l', font=('Segoe UI', 10, 'bold'))
        tx.insert('end', f'{d.pretty}   {name}\n', 'h')
        tx.insert('end', d.description + '\n')
        for sec in dlcsetup.SECTIONS:
            facts = d.section(sec)
            if facts:
                tx.insert('end', f'  {sec}  \n', 's')
                for f in facts:
                    tx.insert('end', f.label + ': ', 'l')
                    tx.insert('end', f.text + '\n')
        if d.uls or d.fls:
            tx.insert('end', '  ULS / FLS  \n', 's')
            for u in d.uls:
                tx.insert('end', u.inp + ': ', 'l')
                tx.insert('end', dlcsetup.uls_text(u) + '\n')
            for f in d.fls:
                tx.insert('end', f.inp + ': ', 'l')
                tx.insert('end', f'{f.case}: ' + dlcsetup.fls_text(f) + '\n')
        tx.configure(state='disabled')

    def render_links(self, tx, links):
        C = self.M['components']
        by = collections.OrderedDict()
        for peer, sig, role, uses in links:
            if C.get(peer, {}).get('kind') == 'harness':
                continue
            by.setdefault(peer, []).append((sig, role, uses))
        if not by:
            tx.insert('end', '(none)\n', ('ind', 'note'))
        for peer, sigs in by.items():
            tag = 'nav_' + peer
            tx.insert('end', '•  ', 'bul')
            tx.insert('end', peer, ('bul', 'b', 'link', tag))
            tx.tag_bind(tag, '<Button-1>', lambda e, p=peer: self.navigate(p))
            roles = collections.OrderedDict()
            for sig, role, uses in sigs:
                roles.setdefault(role or 'not traced', []).append((sig, uses))
            for role, items in roles.items():
                tx.insert('end', f'   {role}: ', ('bul', 'note'))
                for j, (sig, uses) in enumerate(items):
                    t2 = f'use_{peer}_{sig}'
                    tx.insert('end', sig, ('bul', 'mono', t2))
                    if uses:
                        tx.tag_bind(t2, '<Enter>', lambda e, u=uses, s=sig: self.status(f'{s} used in: ' + ' | '.join(u)))
                    if j < len(items) - 1:
                        tx.insert('end', ', ', 'bul')
            tx.insert('end', '\n', 'bul')

    def copy_jira(self, ov):
        task = self.ov_task(ov)
        if not task:
            messagebox.showinfo(APP, 'Pick a tuning task first.')
            return
        txt = overview.jira_markup(task, self.M, self.project_sims(), self.ty.get(), self.va.get(), self.vb.get())
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.status(f"{task['key']}: overview table copied (Jira wiki markup, gates omitted).")

    def overview_window(self, comp):
        w = tk.Toplevel(self)
        w.title(f'Tuning overview - {comp}')
        w.geometry('980x860')
        ov = self.ov_frame(w)
        self.fill_overview(ov, comp)

    def help(self):
        messagebox.showinfo(f'{APP} {__version__}', (
            'Sources (all three of the same PLANC release):\n'
            ' - PLANC repo "Controller" folder (only read, never modified)\n'
            ' - Controller Description PDF\n'
            ' - CoPaD parameter-value export (.csv) of that PLANC version, exported from the CoPaD parameter database\n\n'
            '1. Select the sources and press "Build model" (about half a minute). The model is remembered.\n'
            '2. Pick a function on the left (search also finds signals, parameters and STC1 Par numbers).\n'
            '3. The graph shows who produces its inputs (left, blue arrows) and who consumes its outputs (right, green). '
            'Click a box to navigate, Back/Forward to return, hover an arrow to see all the TDI signals.\n'
            '4. Compare (top right): choose a type selection (e.g. WTGType) and two type values A and B. Parameters that differ are '
            'highlighted; "only where A ≠ B" lists the functions affected; orange borders mark them in the graph.\n'
            '5. Tabs: Parameters (red = type-dependent, purple = STC1 parameter outside the model; double-click = all values per type), '
            'Signals (double-click to jump), Type selections, Description (model + Controller Description).\n'
            'Dashed boxes = functions still implemented in legacy STC1 (emulated by a helper in the model).\n\n'
            'Tuning overview (tab, or click the centre box): the Jira overview table of the tuning task of the function (scope, KPIs, '
            'relevant DLCs, affected functions, risk; tuning gates omitted) from the built-in knowledge base, completed with '
            'the model links (and how each signal is used inside the consumer), the type-dependent parameters A/B and the '
            'load cases of the project simulation. "Copy for Jira" copies it as a Jira table.\n'
            'Simulations (Sources, optional): the first folder is the project simulation; "Load cases (DLCs)" shows the set-up '
            'of each DLC and compares simulations (same window as SimStatsPlotter).'))


class DlcWindow(dlcview.DlcWindow):
    """The SimStatsPlotter load-case window, sharing the loaded simulations with the explorer."""
    def __init__(self, app, sims, cache_dir):
        self.app = app
        super().__init__(app, sims, cache_dir)
        self.loaded = app.loaded
        if self._picked and all(lb in self.loaded for lb in self._picked):    # already read: show it at once
            self._load()

    def _add_sim(self):
        super()._add_sim()
        for q in self.sims.values():
            if os.path.normpath(q) not in self.app.sims:
                self.app.sims.append(os.path.normpath(q))
        self.app.save_cfg()
        self.app.fill_sims()

    def _after_load(self):
        super()._after_load()
        self.app.fill_sims()
        self.app.refresh_overview()


def headless_build():
    """--build: rebuild the model from the saved sources without opening the window; result in build.log next to the model."""
    os.makedirs(DATA, exist_ok=True)
    log = open(os.path.join(DATA, 'build.log'), 'w', encoding='utf8')
    try:
        cfg = json.load(open(CFG, encoding='utf8'))
        m = planc_model.build(cfg['controller'], cfg.get('cd') or None, cfg.get('copad') or None,
                              progress=lambda s: print(s, file=log, flush=True))
        json.dump(m, open(CACHE, 'w', encoding='utf8'), default=str)
        print(f"OK {len(m['components'])} components, {len(m['signals'])} signals, {len(m['edges'])} links, "
              f"{len(m['parameters'])} parameters, {len(m['cd'])} CD sections, {m['meta']['n_copad']} CoPaD parameters", file=log)
    except Exception:
        print('FAILED\n' + traceback.format_exc(), file=log)
    log.close()


if __name__ == '__main__':
    if '--build' in sys.argv:
        headless_build()
        sys.exit(0)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Explorer().mainloop()
