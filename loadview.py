"""Load case view: which control strategies (tunable functionalities) affect a load case or a load, and which would
make most sense to tune to reduce it.

Two angles:
- a load case (DLC of the project simulation, or a DLC code of the knowledge base): the DLC in the centre and an arrow
  from every functionality whose tuning affects it (relevance High / Medium / Lower from its tuning sheet), labelled
  with the loads it acts on in that case (extreme if the DLC enters ULS, fatigue if it enters FLS);
- a load ('all load cases' + a load group / type): the functionalities that act on that load and in which DLCs.
Data: tuning_kb.json ('dlcs' rows of each task, 'effects', 'components', 'keywords', 'dlc_switch') and, when loaded,
the DLC set-up of the project simulation (ULS / FLS use, functions disabled in the case)."""
import re
import textwrap
import tkinter as tk
from tkinter import ttk

import dlcsetup
import overview

LEVEL_W = {'High': 3, 'Medium': 2, 'Lower': 1}
LEVEL_COL = {'High': '#B03A2E', 'Medium': '#E67E22', 'Lower': '#95A5A6', None: '#7D3C98'}
KIND_TXT = {'E': 'extreme', 'F': 'fatigue', 'EF': 'extreme + fatigue'}
SHORT = {'TWR_FA': 'Tower FA', 'TWR_SS': 'Tower SS', 'BLD_FLAP': 'Blade flap', 'BLD_EDGE': 'Blade edge',
         'PITCH': 'Pitch bearing', 'DRV': 'Drivetrain', 'HUB': 'Hub / bearings', 'CLR': 'Clearance', 'SPD': 'Overspeed',
         'AEP': 'AEP'}
INK, MUTED, ACCENT = '#1C2A30', '#5B6B73', '#0B5563'


# ------------------------------------------------------------------------------------------------ logic (no Tk)
def components():
    return overview.kb().get('components', {})


def code_match(task_code, dlc_code):
    """'1.2a' == '1.2a'; '3.x' matches any 3.*; '2.1' matches 2.1g / 2.1c; '9.4' matches 9.4w."""
    if task_code == dlc_code:
        return True
    if task_code.endswith('.x'):
        return dlc_code.startswith(task_code[:-1])
    return not task_code[-1].isalpha() and re.fullmatch(re.escape(task_code) + r'[a-z]+', dlc_code) is not None


def default_kind(code):
    """IEC 61400-1 use of a DLC when no simulation tells it: fatigue for normal production, idling and parked
    fatigue cases, extreme otherwise."""
    if code.startswith('1.2'):
        return 'F'
    if code.startswith('1.7'):
        return 'EF'
    if re.match(r'(3\.1|4\.1|6\.4|7\.2)', code):
        return 'F'
    return 'E'


def dlc_kind(code, setup=None):
    """'E' (ULS), 'F' (FLS) or 'EF' from the simulation set-up; IEC default when unknown."""
    if setup is not None and (setup.uls or setup.fls):
        return ('E' if setup.uls else '') + ('F' if setup.fls else '')
    return default_kind(code)


def disabled_tasks(setup):
    """OVTASK keys of the functions switched off in the DLC set-up."""
    if setup is None:
        return set()
    sw = overview.kb().get('dlc_switch', {})
    return {sw[f.label] for f in setup.section('Control functions') + setup.section('Safety system')
            if f.label in sw and 'disabled' in f.text.lower()}


def named_components(text):
    t = text.lower()
    return {c for c, words in overview.kb().get('keywords', {}).items() if any(w in t for w in words)}


def is_monitor(name):
    """Monitors / detectors only set alarm or stop limits: they protect, they do not reduce the load in operation."""
    n = name.lower()
    return any(w in n for w in ('monitor', 'detector', 'safety system', 'validator'))


def task_effects(key):
    return [(e['comp'], e['kind'], e['why']) for e in overview.kb().get('effects', {}).get(key, [])]


def affecting(code, setup=None, comp=None, kind=None):
    """Functionalities whose tuning affects the load case `code` (e.g. '1.4'), best level first.
    Each item: dict(task, level, reasons, effects [(comp, kind, why)], named, disabled, score)."""
    k_dlc = dlc_kind(code, setup)
    off = disabled_tasks(setup)
    out = []
    for t in overview.all_tasks():
        rows = [(lv, rs) for lv, codes, rs in overview.dlc_items(t) if any(code_match(c, code) for c in codes)]
        if not rows:
            continue
        level = max((lv for lv, _ in rows), key=lambda x: LEVEL_W[x])
        reasons = [rs for _, rs in rows]
        kinds = set(k_dlc) & set(kind or 'EF')
        eff = [e for e in task_effects(t['key']) if set(e[1]) & kinds]
        named = named_components(' '.join(reasons))
        if comp:
            eff = [e for e in eff if e[0] == comp]
            if not eff:
                continue
        if not eff and kind:
            continue
        score = LEVEL_W[level] + (0.5 if named & {e[0] for e in eff} else 0) + \
            (0.5 if any(not e[2].lower().startswith('through') for e in eff) else 0)
        score -= 0.7 if is_monitor(t['name']) else 0
        out.append(dict(task=t, level=level, reasons=reasons, effects=eff, named=named,
                        disabled=t['key'] in off, score=score))
    out.sort(key=lambda d: (d['disabled'], -d['score'], d['task']['name']))
    return out


def affecting_load(comp, kind=None):
    """Second angle: functionalities that act on a load group (all load cases). Level = best level among the task's
    DLC rows whose (default) DLC use matches the kind."""
    out = []
    for t in overview.all_tasks():
        eff = [e for e in task_effects(t['key']) if (not comp or e[0] == comp) and (not kind or set(e[1]) & set(kind))]
        if not eff:
            continue
        kinds = set(kind or ''.join(e[1] for e in eff))
        rows = [(lv, c, rs) for lv, codes, rs in overview.dlc_items(t) for c in codes if set(default_kind(c)) & kinds]
        level = max((lv for lv, _, _ in rows), key=lambda x: LEVEL_W[x]) if rows else None
        codes = list(dict.fromkeys(c for lv, c, _ in sorted(rows, key=lambda r: -LEVEL_W[r[0]])))
        named = [rs for _, _, rs in rows if comp in named_components(rs)] if comp else []
        n_high = sum(1 for lv, _, _ in rows if lv == 'High')
        score = (LEVEL_W[level] if level else 0.5) + (0.5 if any(not e[2].lower().startswith('through') for e in eff) else 0)             + (0.5 if named else 0) + min(n_high, 5) * 0.1 - (0.7 if is_monitor(t['name']) else 0)
        out.append(dict(task=t, level=level, reasons=[f'{lv}: DLC {c}' for lv, c, _ in rows][:12], effects=eff,
                        named=set(), disabled=False, score=score, codes=codes))
    out.sort(key=lambda d: (-d['score'], d['task']['name']))
    return out


def kb_codes():
    """All DLC codes used in the knowledge base (when no simulation is loaded)."""
    codes = {c for t in overview.all_tasks() for _, cs, _ in overview.dlc_items(t) for c in cs}

    def key(c):
        a, b = c.split('.', 1)
        m = re.match(r'(\d+|x)(.*)', b)
        return (int(a) if a.isdigit() else 99, int(m.group(1)) if m and m.group(1).isdigit() else 99, m.group(2) if m else b)
    return sorted(codes, key=key)


# ------------------------------------------------------------------------------------------------ window
class LoadCaseWindow:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app)
        self.win.title('Load case view - which control strategies affect a load case / a load')
        self.win.geometry('1600x900')
        self.comp = tk.StringVar(value='All loads')
        self.kind = tk.StringVar(value='Extreme + fatigue')
        self.min_level = tk.StringVar(value='Lower')
        self.q = tk.StringVar()
        self.tip = None
        self.items = []
        self.build()
        self.fill_list()

    # ---- layout
    def build(self):
        pane = ttk.PanedWindow(self.win, orient='horizontal')
        pane.pack(fill='both', expand=True)
        self.pane = pane
        self.win.after(250, self.place_sashes)
        left = ttk.Frame(pane, padding=4)
        mid = ttk.Frame(pane)
        right = ttk.Frame(pane, padding=4)
        pane.add(left, weight=1)
        pane.add(mid, weight=4)
        pane.add(right, weight=2)
        f = ttk.LabelFrame(left, text=' Load ', padding=4)
        f.pack(fill='x')
        comps = components()
        self.comp_keys = [''] + list(comps)
        ttk.Label(f, text='Load group').grid(row=0, column=0, sticky='w')
        cb = ttk.Combobox(f, textvariable=self.comp, state='readonly', width=30,
                          values=['All loads'] + [comps[k] for k in comps])
        cb.grid(row=0, column=1, sticky='we', padx=3)
        ttk.Label(f, text='Load type').grid(row=1, column=0, sticky='w')
        cb2 = ttk.Combobox(f, textvariable=self.kind, state='readonly', width=30,
                           values=['Extreme + fatigue', 'Extreme (ULS)', 'Fatigue (FLS)'])
        cb2.grid(row=1, column=1, sticky='we', padx=3)
        ttk.Label(f, text='Relevance at least').grid(row=2, column=0, sticky='w')
        cb3 = ttk.Combobox(f, textvariable=self.min_level, state='readonly', width=30, values=['Lower', 'Medium', 'High'])
        cb3.grid(row=2, column=1, sticky='we', padx=3)
        for c in (cb, cb2, cb3):
            c.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        f.columnconfigure(1, weight=1)
        g = ttk.LabelFrame(left, text=' Load case ', padding=4)
        g.pack(fill='both', expand=True, pady=(6, 0))
        ttk.Entry(g, textvariable=self.q).pack(fill='x')
        self.q.trace_add('write', lambda *_: self.fill_list())
        self.lst = ttk.Treeview(g, columns=('use',), show='tree headings', selectmode='browse')
        self.lst.heading('#0', text='Load case')
        self.lst.heading('use', text='Use')
        self.lst.column('#0', width=260)
        self.lst.column('use', width=50, anchor='center')
        y = ttk.Scrollbar(g, orient='vertical', command=self.lst.yview)
        self.lst.configure(yscrollcommand=y.set)
        self.lst.pack(side='left', fill='both', expand=True)
        y.pack(side='right', fill='y')
        self.lst.bind('<<TreeviewSelect>>', lambda e: self.refresh())
        self.src = ttk.Label(left, foreground=MUTED, wraplength=330, justify='left')
        self.src.pack(fill='x', pady=4)
        # centre: diagram
        self.cv = tk.Canvas(mid, bg='white', highlightthickness=0)
        vs = ttk.Scrollbar(mid, orient='vertical', command=self.cv.yview)
        self.cv.configure(yscrollcommand=vs.set)
        self.cv.pack(side='left', fill='both', expand=True)
        vs.pack(side='right', fill='y')
        self.cv.bind('<Configure>', lambda e: self.draw())
        self.cv.bind('<MouseWheel>', lambda e: self.cv.yview_scroll(int(-e.delta / 120), 'units'))
        # right: ranking
        ttk.Label(right, text='What to tune first', font=('Segoe UI', 11, 'bold'), foreground=ACCENT).pack(anchor='w')
        self.rank_lbl = ttk.Label(right, foreground=MUTED, wraplength=520, justify='left')
        self.rank_lbl.pack(anchor='w')
        self.rank = ttk.Treeview(right, columns=('n', 'level', 'loads'), show='tree headings', selectmode='browse')
        self.rank.heading('#0', text='Functionality')
        self.rank.heading('n', text='#')
        self.rank.heading('level', text='Relevance')
        self.rank.heading('loads', text='Loads it acts on here')
        self.rank.column('#0', width=230)
        self.rank.column('n', width=30, anchor='center')
        self.rank.column('level', width=70, anchor='center')
        self.rank.column('loads', width=220)
        self.rank.tag_configure('off', foreground='#AAB7B8')
        self.rank.pack(fill='both', expand=True, pady=(4, 4))
        self.rank.bind('<<TreeviewSelect>>', lambda e: self.show_why())
        self.rank.bind('<Double-1>', lambda e: self.open_sel())
        self.why = tk.Text(right, height=14, wrap='word', font=('Segoe UI', 9), relief='flat', background='#F7F9FA')
        self.why.pack(fill='x')
        ttk.Button(right, text='Open its tuning overview', command=self.open_sel).pack(anchor='e', pady=4)

    def place_sashes(self):
        w = self.pane.winfo_width()
        if w <= 900:                                     # not mapped yet
            self.win.after(200, self.place_sashes)
            return
        self.pane.sashpos(1, w - 520)
        self.pane.sashpos(0, 330)
        self.win.after(50, self.draw)

    # ---- data
    def sims(self):
        s = self.app.project_sims()
        return s[0] if s else None

    def fill_list(self):
        t = self.lst
        t.delete(*t.get_children())
        q = self.q.get().strip().lower()
        t.insert('', 'end', iid='ALL', text='(all load cases) - by load', values=('',))
        sim = self.sims()
        if sim:
            self.src.configure(text=f'Load cases of the project simulation {sim.label}. Use: E = in ULS (extreme), '
                                    f'F = in FLS (fatigue). Functions disabled in a case are shown dashed.')
            groups = {}
            for name, d in sim.dlcs.items():
                if d.tool:
                    continue
                if q and q not in name.lower() and q not in d.pretty.lower():
                    continue
                sit = d.situation
                if sit not in groups:
                    groups[sit] = t.insert('', 'end', text=dlcsetup.SITUATIONS.get(sit, sit), open=True)
                use = ('E' if d.uls else '') + ('F' if d.fls else '')
                t.insert(groups[sit], 'end', iid='S:' + name, text=f'{d.pretty}  {name}', values=(use or '-',))
        else:
            self.src.configure(text='No project simulation loaded: DLC codes of the knowledge base, with the IEC default '
                                    'use (E / F). Add the simulation in Sources to see the real set-up.')
            for c in kb_codes():
                if q and q not in c:
                    continue
                t.insert('', 'end', iid='K:' + c, text=f'DLC {c}', values=(default_kind(c),))

    def selection(self):
        s = self.lst.selection()
        if not s or s[0] in ('',):
            return None, None, None
        i = s[0]
        if i == 'ALL':
            return 'ALL', None, None
        if i.startswith('S:'):
            sim = self.sims()
            d = sim.dlcs[i[2:]]
            return overview.pretty_to_key(d.pretty), d, i[2:]
        if i.startswith('K:'):
            return i[2:], None, None
        return None, None, None

    def filters(self):
        comps = components()
        comp = next((k for k, v in comps.items() if v == self.comp.get()), None)
        kind = {'Extreme (ULS)': 'E', 'Fatigue (FLS)': 'F'}.get(self.kind.get())
        return comp, kind

    def refresh(self):
        code, setup, folder = self.selection()
        comp, kind = self.filters()
        lvl = LEVEL_W[self.min_level.get()]
        self.code, self.setup, self.folder = code, setup, folder
        if code is None:
            self.items = []
        elif code == 'ALL':
            self.items = affecting_load(comp, kind) if comp else []
        else:
            self.items = affecting(code, setup, comp, kind)
        self.items = [d for d in self.items if d['level'] is None or LEVEL_W[d['level']] >= lvl]
        self.fill_rank()
        self.draw()

    # ---- ranking
    def fill_rank(self):
        r = self.rank
        r.delete(*r.get_children())
        comp, kind = self.filters()
        if self.code == 'ALL':
            self.rank_lbl.configure(text=('Functionalities that act on ' + (components().get(comp, 'the load') if comp else
                                                                           '... pick a load group') +
                                          (f' ({KIND_TXT[kind]})' if kind else '') + ', ranked by relevance in their DLCs.'))
        elif self.code:
            self.rank_lbl.configure(text='Ranked by relevance in this load case (High / Medium / Lower of the tuning sheet), '
                                         'whether the load is named in the reason, and direct vs indirect action. Disabled '
                                         'functions cannot act in this case.')
        n = 0
        for i, d in enumerate(self.items):
            loads = ', '.join(dict.fromkeys(f"{SHORT.get(c, c)} {k}" for c, k, _ in d['effects']))
            if not d['disabled']:
                n += 1
            r.insert('', 'end', iid=str(i), text=d['task']['name'], values=('' if d['disabled'] else n,
                                                                            d['level'] or '-',
                                                                            ('DISABLED in this case. ' if d['disabled']
                                                                             else '') + loads),
                     tags=('off',) if d['disabled'] else ())

    def explain(self, d):
        t = d['task']
        lines = [f"{t['key']}  {t['name']}" + (f"   ({t['comp']})" if t.get('comp') else ''),
                 f"Relevance: {d['level'] or '-'}" + ('   DISABLED in this load case (DLC set-up)' if d['disabled'] else '')]
        if d['reasons']:
            lines += ['', 'Why this load case (tuning sheet):'] + ['- ' + overview.strip(x) for x in d['reasons']]
        if d['effects']:
            lines += ['', 'Loads and mechanism:'] + [f"- {components().get(c, c)} ({KIND_TXT[k]}): {w}"
                                                     for c, k, w in d['effects']]
        return '\n'.join(lines)

    def show_why(self):
        s = self.rank.selection()
        if not s:
            return
        d = self.items[int(s[0])]
        self.why.configure(state='normal')
        self.why.delete('1.0', 'end')
        self.why.insert('end', self.explain(d))
        self.why.configure(state='disabled')

    def open_sel(self, d=None):
        if d is None:
            s = self.rank.selection()
            if not s:
                return
            d = self.items[int(s[0])]
        t = d['task']
        comp = t.get('comp')
        if comp and comp in self.app.M['components']:
            self.app.navigate(comp)
            self.app.nb.select(0)
            self.app.fill_overview(self.app.ov_main, comp, t['key'])
            self.app.lift()
        else:
            w = tk.Toplevel(self.win)
            w.title(f"Tuning overview - {t['key']}")
            w.geometry('980x860')
            ov = self.app.ov_frame(w)
            self.app.fill_overview(ov, comp or next(iter(self.app.M['components'])), t['key'])

    # ---- diagram
    def hover(self, item, text):
        def enter(e):
            self.unhover()
            self.tip = tk.Toplevel(self.win)
            self.tip.wm_overrideredirect(True)
            self.tip.geometry(f'+{e.x_root + 12}+{e.y_root + 12}')
            tk.Label(self.tip, text=text, justify='left', bg='#FFFDE7', relief='solid', bd=1, font=('Segoe UI', 9),
                     wraplength=620).pack()
        self.cv.tag_bind(item, '<Enter>', enter)
        self.cv.tag_bind(item, '<Leave>', lambda e: self.unhover())

    def unhover(self):
        if self.tip:
            self.tip.destroy()
            self.tip = None

    def centre_text(self):
        comp, kind = self.filters()
        if self.code == 'ALL':
            return (components().get(comp, 'Pick a load group') if comp else 'Pick a load group (left)',
                    'all load cases' + (f' - {KIND_TXT[kind]}' if kind else ''), '')
        if self.setup is not None:
            d = self.setup
            use = ' + '.join(x for x, ok in (('extreme (ULS)', d.uls), ('fatigue (FLS)', d.fls)) if ok) or 'not in ULS / FLS'
            off = sorted({f.label for f in d.section('Control functions') + d.section('Safety system')
                          if 'disabled' in f.text.lower()})
            return (f'{d.pretty}   {self.folder}', f'{use}\n' + textwrap.shorten(d.description, 260),
                    ('Disabled: ' + ', '.join(off)) if off else '')
        return (f'DLC {self.code}', f'{KIND_TXT[default_kind(self.code)]} (IEC default use)', '')

    def draw(self):
        cv = self.cv
        cv.delete('all')
        if not getattr(self, 'code', None):
            cv.create_text(20, 20, anchor='nw', fill=MUTED, font=('Segoe UI', 11), text=(
                'Pick a load case on the left to see every control strategy whose tuning affects it.\n\n'
                'Or pick "(all load cases) - by load" and a load group (e.g. Tower fore-aft, Extreme) to see which '
                'strategies act on that load.\n\nArrow colour / width = relevance (High / Medium / Lower), box label = loads '
                'it acts on in that case, dashed = disabled in the case. Hover for the reason; click to open the overview.'),
                width=max(cv.winfo_width() - 40, 300))
            return
        W = max(cv.winfo_width(), 300)
        items = self.items
        lefts, rights = items[0::2], items[1::2]
        rowh, top = 56, 50
        nrows = max(len(lefts), len(rights), 1)
        H = top + nrows * rowh + 70
        cv.configure(scrollregion=(0, 0, W, max(H, cv.winfo_height())))
        cw = min(300, int(W * 0.3))
        bw = max(150, min(270, int((W - cw - 120) / 2)))
        xc, cy = W / 2, top + nrows * rowh / 2
        title, sub, off = self.centre_text()
        yy, its = 0, []
        for txt, font, colr in ((title, ('Segoe UI', 10, 'bold'), INK), (sub, ('Segoe UI', 8), INK),
                                (off, ('Segoe UI', 8, 'italic'), '#B03A2E')):
            if txt:
                it = cv.create_text(xc, yy, text=txt, font=font, fill=colr, width=cw - 14, anchor='n', justify='center')
                its.append(it)
                yy = cv.bbox(it)[3] + 6
        ch = max(120, yy + 8)
        for it in its:
            cv.move(it, 0, cy - ch / 2 + 8)
        rect = cv.create_rectangle(xc - cw / 2, cy - ch / 2, xc + cw / 2, cy + ch / 2, fill='#D6EAF8', outline=ACCENT,
                                   width=3)
        cv.tag_lower(rect)
        cv.create_text(20, 22, anchor='w', fill=MUTED, font=('Segoe UI', 9, 'bold'),
                       text=f'{len(items)} control strategies affect this ' + ('load' if self.code == 'ALL' else 'load case'))
        if not items:
            cv.create_text(xc, cy + ch / 2 + 30, fill=MUTED, font=('Segoe UI', 10, 'italic'),
                           text='No functionality with these filters.' if self.code != 'ALL' or self.filters()[0]
                           else 'Pick a load group on the left.')
        for side, lst in ((0, lefts), (1, rights)):
            off_rows = (nrows - len(lst)) * rowh / 2
            for i, d in enumerate(lst):
                y = top + i * rowh + rowh / 2 + off_rows
                x = 20 if side == 0 else W - 20 - bw
                col = LEVEL_COL[d['level']] if not d['disabled'] else '#BDC3C7'
                dash = (4, 3) if d['disabled'] else None
                r = cv.create_rectangle(x, y - 24, x + bw, y + 24, fill='#FBFCFC' if not d['disabled'] else '#F2F3F4',
                                        outline=col, width=2, dash=dash)
                nmax = max(12, int((bw - 12) / 7.6))
                t1 = cv.create_text(x + 6, y - 12, anchor='w', text=textwrap.shorten(d['task']['name'], nmax, placeholder='…'),
                                    font=('Segoe UI', 9, 'bold'), fill=INK if not d['disabled'] else '#95A5A6')
                loads = ', '.join(dict.fromkeys(f"{SHORT.get(c, c)} {k}" for c, k, _ in d['effects']))
                txt2 = (d['level'] or '-') + ' | ' + ('disabled in this case' if d['disabled'] else
                                                      loads or '(no load effect of this type)')
                t2 = cv.create_text(x + 6, y + 9, anchor='w', text=textwrap.shorten(txt2, int(nmax * 1.9), placeholder='…'),
                                    font=('Segoe UI', 8), fill=col, width=bw - 10)
                x0 = x + bw if side == 0 else x
                ex = xc - cw / 2 if side == 0 else xc + cw / 2
                ey = cy - ch / 2 + 14 + (ch - 28) * (i + 0.5) / max(len(lst), 1)
                w = {'High': 3.5, 'Medium': 2.2, 'Lower': 1.2}.get(d['level'], 1.5)
                a = cv.create_line(x0, y, ex, ey, arrow='last', fill=col, width=w, smooth=True, dash=dash)
                tip = self.explain(d)
                for it in (r, t1, t2, a):
                    self.hover(it, tip)
                for it in (r, t1, t2):
                    cv.tag_bind(it, '<Button-1>', lambda e, d=d: self.open_sel(d))
        cv.create_text(W / 2, H - 20, fill=MUTED, font=('Segoe UI', 8), width=W - 30, justify='center', text=(
            'Arrow colour and width = relevance of the load case for the tuning of the functionality (red High, orange '
            'Medium, grey Lower). E = extreme, F = fatigue. Dashed = disabled in this load case. Hover for the reason, '
            'click a box for its tuning overview. Relevance and load effects are engineering judgement: review with Loads.'))
