"""(Copied from SimStatsPlotter dlcview.py; keep in sync.)
Load cases window (Tools -> Load cases (DLCs)...): the DLCs a simulation runs, read from the exchange
sheet of each DLC, and - with several simulations - what changed between them. Logic in ``dlcsetup``.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import dlcsetup
import screen_fit
import dlc_viewutil as viewutil   # help_layout / tree only (no numpy)

STATUS_TAGS = {"new": "#d5f5e3", "removed": "#fadbd8", "changed": "#fdebd0", "same": "#ffffff", "only": "#ffffff"}
STATUS_TEXT = {"new": "new", "removed": "removed", "changed": "changed", "same": "same", "only": ""}

HELP_OVERVIEW = """HOW TO READ THE LOAD CASES

Where it comes from: every folder <simulation>\\Btc\\DLC... is a load case; its exchange sheet <DLC>.xlsx (made by Load Basis Setup) has one row per simulation and one column per change to the template <simulation>\\Btc\\_Template\\<simulation>.btc. Nothing is taken from a fixed table: what you see is what the run simulates. Whether a case enters ULS / FLS (and with which safety factor, averaging, lifetime) comes from the run's own Post\\00_Input\\ULS_*.inp and FLS_*.inp (pick which one on the left).

One simulation: one row per load case, grouped by design situation (1.x production, 2.x production with fault, ... 8.x maintenance):
- Wind: the wind model of the case (NTM, ETM, ECD, EOG, EWM50...). Wind speed: the range simulated. Sims: number of simulations; per WS: simulations per wind speed (seeds x yaw errors x azimuths ...).
- PSF: partial safety factor written to the load transformation (TOTF Psf) of the sheet. ULS / FLS: how the chosen ULS / FLS input uses the case (PSF, averaging, grouping / lifetime years, events per year); empty = not used.
- ACS, OS mon. (controller overspeed monitor), Safety OS (the safety overspeed system EXC_OVRSPD): on / off / x factor (scaled thresholds) - from the sheet, else from the template.
- Event: the fault or action of the case (timers, pitch runaway, sensor failure, ...).
- Results: whether Res\\<DLC> exists.

Several simulations (compare machines or revisions): the FIRST simulation of the list is the reference.
- new (green): the case is not in the reference.
- removed (red): the case is in the reference but not in (one of) the others.
- changed (orange): same case, other set-up - the Changes column says what (e.g. 'Simulations: 276 -> 552', 'Azimuth (initial): 90 -> 30, 90 deg', 'Mechanical brake actuator: enabled (template) -> disabled').
- same: identical set-up.
A case renamed only in its design-class suffix (_SS / _2A) is matched as the same case.
'Only differences' hides the identical ones. Double-click a row = its card (Load case tab).

Template differences tab: the lines of the template .btc that differ between the simulations (controller parameter file, aerodynamics, masses...): they change EVERY load case."""

HELP_CARD = """HOW TO READ THE LOAD CASE CARD

The card of one load case, laid out like the DLC Forum design basis (Description, Wind conditions, Simulation set-up, ULS, FLS) plus what the exchange sheet changes in the model:
- Description: built from the sheet - design situation, wind model and speeds, events, the functions that are switched off.
- Wind conditions: wind model, speeds, turbulence intensity (one per wind speed, or a distribution per wind speed for RepTurb), shear exponent, inflow angle, air density, gusts.
- Simulation set-up: number of simulations, per wind speed, yaw misalignment, seeds, duration, azimuths, initial pitch / rotor speed, safety factor.
- Events and faults: timers ('when NormalFullTime [s] = 10: StopCommand=50' = a stop with code 50 at 10 s), pitch runaway, stuck blade, sensor failure, grid drop...
- Control functions / Safety system: every function with its state; '(template)' = not changed by the sheet, the template's state.
- Model changes: masses, pitch errors, brake, aerodynamic files, clamped blades, added components...
- ULS / FLS: one row per input file of Post\\00_Input that uses the case.
With several simulations there is one column per simulation and the rows that differ are highlighted.

Simulations tab: the rows of the exchange sheet (only the columns that vary). BHawC changes tab: every column of the sheet with its template default."""


class DlcWindow:
    def __init__(self, parent, sims: dict[str, str], cache_dir: str | None = None):
        """*sims*: {label: simulation folder} (the paths loaded in the main window)."""
        self.parent = parent
        self.sims = dict(sims)
        self.cache_dir = cache_dir
        self.loaded: dict[str, dlcsetup.SimDlcs] = {}
        self.shown: list[str] = []                 # labels shown, the first = reference
        self.rows: list[dlcsetup.Compared] = []
        self._busy = False
        self.win = tk.Toplevel(parent)
        self.win.title("Load cases (DLCs)")
        self.uls_inp = tk.StringVar()
        self.fls_inp = tk.StringVar()
        self.only_diff = tk.BooleanVar(value=False)
        self.search = tk.StringVar()
        self.card_sim = tk.StringVar()
        self._build()
        screen_fit.fit_to_screen(self.win, "dlcs", 1560, 900, parent=parent)
        self._fill_sims()

    # ================================================================ UI
    def _build(self):
        pane = ttk.PanedWindow(screen_fit.scroll_body(self.win), orient="horizontal")
        pane.pack(fill="both", expand=True)
        leftwrap, left = screen_fit.scroll_column(pane)
        right = ttk.Frame(pane)
        pane.add(leftwrap, weight=0)
        pane.add(right, weight=1)

        sf = ttk.LabelFrame(left, text="1. Simulations")
        sf.pack(fill="x")
        ttk.Label(sf, text="Pick one to see its load cases, or several to compare them\n"
                  "(the first one picked is the reference).", foreground="#555").pack(anchor="w", padx=4)
        box = ttk.Frame(sf)
        box.pack(fill="x", padx=4, pady=2)
        self.sim_lb = tk.Listbox(box, selectmode="multiple", height=8, width=44, exportselection=False)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.sim_lb.yview)
        self.sim_lb.configure(yscrollcommand=sb.set)
        self.sim_lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.sim_lb.bind("<<ListboxSelect>>", self._on_pick)
        self._picked: list[str] = []
        ttk.Button(sf, text="Add simulation folder...", command=self._add_sim).pack(anchor="w", padx=4)
        ttk.Button(sf, text="▶ Read load cases", command=self._load).pack(fill="x", padx=4, pady=(6, 4))

        vf = ttk.LabelFrame(left, text="2. Show")
        vf.pack(fill="x", pady=(6, 0))
        g = ttk.Frame(vf)
        g.pack(fill="x", padx=4, pady=2)
        ttk.Label(g, text="ULS input:").grid(row=0, column=0, sticky="w")
        self.uls_cb = ttk.Combobox(g, textvariable=self.uls_inp, state="readonly", width=30)
        self.uls_cb.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(g, text="FLS input:").grid(row=1, column=0, sticky="w")
        self.fls_cb = ttk.Combobox(g, textvariable=self.fls_inp, state="readonly", width=30)
        self.fls_cb.grid(row=1, column=1, sticky="ew", padx=4)
        for cb in (self.uls_cb, self.fls_cb):
            cb.bind("<<ComboboxSelected>>", lambda *_: self._refresh())
        ttk.Label(g, text="Search:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ent = ttk.Entry(g, textvariable=self.search, width=30)
        ent.grid(row=2, column=1, sticky="ew", padx=4, pady=(4, 0))
        self.search.trace_add("write", lambda *_: self._refresh())
        g.columnconfigure(1, weight=1)
        self.diff_cb = ttk.Checkbutton(vf, text="Only differences (comparison)", variable=self.only_diff,
                                       command=self._refresh)
        self.diff_cb.pack(anchor="w", padx=4)
        ttk.Button(vf, text="Export to Excel...", command=self._export).pack(fill="x", padx=4, pady=(6, 4))
        self.status = ttk.Label(left, text="Pick simulation(s) and press 'Read load cases'.", wraplength=330,
                                justify="left", foreground="#333")
        self.status.pack(anchor="w", pady=(8, 0))

        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        # ---- overview
        frm = ttk.Frame(self.nb)
        self.nb.add(frm, text="Overview")
        top = ttk.Frame(frm)
        top.pack(fill="x")
        self.ov_title = ttk.Label(top, text="", font=("Segoe UI", 10, "bold"))
        self.ov_title.pack(side="left", padx=4, pady=2)
        body = viewutil.help_layout(frm, top, HELP_OVERVIEW)
        self.ov = self._tree(body)
        self.ov.bind("<Double-1>", lambda e: self._open_card())
        self.ov.bind("<Return>", lambda e: self._open_card())
        # ---- card
        frm = ttk.Frame(self.nb)
        self.nb.add(frm, text="Load case")
        top = ttk.Frame(frm)
        top.pack(fill="x")
        self.card_title = ttk.Label(top, text="Double-click a load case in the Overview.", font=("Segoe UI", 10, "bold"))
        self.card_title.pack(side="left", padx=4, pady=2)
        body = viewutil.help_layout(frm, top, HELP_CARD)
        vp = ttk.PanedWindow(body, orient="vertical")
        vp.pack(fill="both", expand=True)
        upper = ttk.Frame(vp)
        lower = ttk.Frame(vp)
        vp.add(upper, weight=3)
        vp.add(lower, weight=2)
        self.desc = tk.Text(upper, height=4, wrap="word", relief="flat", background="#f6f8fa",
                            font=("Segoe UI", 9), padx=6, pady=4)
        self.desc.pack(fill="x", padx=2, pady=(0, 4))
        self.card = self._tree(upper)
        sub = ttk.Frame(lower)
        sub.pack(fill="x")
        ttk.Label(sub, text="Exchange sheet of:").pack(side="left", padx=4)
        self.card_sim_cb = ttk.Combobox(sub, textvariable=self.card_sim, state="readonly", width=40)
        self.card_sim_cb.pack(side="left", padx=4, pady=2)
        self.card_sim_cb.bind("<<ComboboxSelected>>", lambda *_: self._fill_sheet())
        self.sheet_path = ttk.Label(sub, text="", foreground="#555")
        self.sheet_path.pack(side="left", padx=6)
        snb = ttk.Notebook(lower)
        snb.pack(fill="both", expand=True)
        f1 = ttk.Frame(snb)
        f2 = ttk.Frame(snb)
        snb.add(f1, text="Simulations")
        snb.add(f2, text="BHawC changes")
        self.sims_tv = viewutil.tree(f1)
        self.raw_tv = viewutil.tree(f2, columns=("change", "mode", "template", "values"))
        for c, w, t in (("change", 360, "BHawC command / keyword [position]"), ("mode", 70, "how"),
                        ("template", 200, "template default"), ("values", 420, "values in the sheet")):
            self.raw_tv.heading(c, text=t, anchor="w")
            self.raw_tv.column(c, width=w, anchor="w", stretch=c == "values")
        # ---- template differences
        frm = ttk.Frame(self.nb)
        self.nb.add(frm, text="Template differences")
        self.tpl_title = ttk.Label(frm, text="Compare two or more simulations to see their template differences.")
        self.tpl_title.pack(anchor="w", padx=4, pady=2)
        self.tpl = viewutil.tree(frm)

    def _tree(self, parent):
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        t = ttk.Treeview(box, show="tree headings")
        vsb = ttk.Scrollbar(box, orient="vertical", command=t.yview)
        hsb = ttk.Scrollbar(box, orient="horizontal", command=t.xview)
        t.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        t.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        for st, col in STATUS_TAGS.items():
            t.tag_configure(st, background=col)
        t.tag_configure("group", font=("Segoe UI", 9, "bold"), background="#eef2f7")
        t.tag_configure("nosheet", foreground="#888")
        t.tag_configure("diff", background="#fdebd0")
        return t

    # ================================================================ simulations
    def _fill_sims(self):
        self.sim_lb.delete(0, "end")
        for lb in self.sims:
            self.sim_lb.insert("end", lb)
        if len(self.sims) == 1:
            self.sim_lb.selection_set(0)
            self._picked = list(self.sims)

    def _on_pick(self, _e=None):
        sel = [self.sim_lb.get(i) for i in self.sim_lb.curselection()]
        self._picked = [x for x in self._picked if x in sel] + [x for x in sel if x not in self._picked]
        n = len(self._picked)
        self.status.config(text=("Reference: " + self._picked[0] + (f" + {n - 1} to compare" if n > 1 else "")
                                 + ". Press 'Read load cases'.") if n else "Pick simulation(s).")

    def _add_sim(self):
        d = filedialog.askdirectory(parent=self.win, title="Simulation folder (the one holding Btc/, Res/ and Post/)")
        if d:
            lb = os.path.basename(d.rstrip("\\/")) or d
            self.sims[lb] = d
            self._fill_sims()
            idx = list(self.sims).index(lb)
            self.sim_lb.selection_set(idx)
            self._on_pick()

    # ================================================================ loading
    def _load(self):
        if self._busy:
            return
        labels = list(self._picked)
        if not labels:
            messagebox.showinfo("Load cases", "Pick at least one simulation.", parent=self.win)
            return
        bad = [lb for lb in labels if not os.path.isdir(os.path.join(self.sims[lb], "Btc"))]
        if bad:
            messagebox.showwarning("Load cases", "No Btc folder in:\n" + "\n".join(self.sims[b] for b in bad),
                                   parent=self.win)
            labels = [lb for lb in labels if lb not in bad]
            if not labels:
                return
        self._busy = True
        todo = [lb for lb in labels if lb not in self.loaded]
        state = {"msg": "", "done": False, "err": []}

        def work():
            for lb in todo:
                def prog(i, n, name, lb=lb):
                    state["msg"] = f"{lb}: exchange sheet {i}/{n} ({name})"
                try:
                    self.loaded[lb] = dlcsetup.load_sim(lb, self.sims[lb], self.cache_dir, progress=prog)
                except Exception as e:           # noqa: BLE001 - shown to the user
                    state["err"].append(f"{lb}: {e}")
            state["done"] = True

        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                if not self.win.winfo_exists():
                    return
            except tk.TclError:
                return
            if not state["done"]:
                self.status.config(text="Reading ... " + state["msg"])
                self.win.after(150, poll)
                return
            self._busy = False
            if state["err"]:
                messagebox.showerror("Load cases", "\n".join(state["err"]), parent=self.win)
            self.shown = [lb for lb in labels if lb in self.loaded]
            self._after_load()
        poll()

    def _after_load(self):
        if not self.shown:
            return
        sims = [self.loaded[lb] for lb in self.shown]
        uls = sorted({n for s in sims for n in s.uls}, key=lambda n: (len(n), n))
        fls = sorted({n for s in sims for n in s.fls}, key=lambda n: (len(n), n))
        self.uls_cb.config(values=uls)
        self.fls_cb.config(values=fls)
        if self.uls_inp.get() not in uls:
            self.uls_inp.set(dlcsetup.main_input(uls))
        if self.fls_inp.get() not in fls:
            self.fls_inp.set(dlcsetup.main_input(fls))
        self.rows = dlcsetup.compare(sims)
        self.card_sim_cb.config(values=self.shown)
        warn = [f"{s.label}: {w}" for s in sims for w in s.warnings]
        n = len(self.rows)
        if len(sims) == 1:
            s = sims[0]
            post = sum(1 for d in s.dlcs.values() if d.tool)
            nosheet = sum(1 for d in s.dlcs.values() if d.sheet is None and not d.tool)
            txt = (f"{s.label}: {n} load cases" + (f", {post} post-processing (extrapolation)" if post else "")
                   + (f" ({nosheet} without exchange sheet)" if nosheet else ""))
        else:
            c = {k: sum(1 for r in self.rows if r.status == k) for k in ("same", "changed", "new", "removed")}
            txt = (f"Reference {sims[0].label} vs {', '.join(s.label for s in sims[1:])}: {c['same']} same, "
                   f"{c['changed']} changed, {c['new']} new, {c['removed']} removed")
        self.ov_title.config(text=txt)
        self.status.config(text=txt + ("\n" + "\n".join(warn) if warn else ""))
        self._refresh()
        self._fill_templates()

    # ================================================================ overview
    def _refresh(self):
        if not self.shown:
            return
        sims = [self.loaded[lb] for lb in self.shown]
        t = self.ov
        t.delete(*t.get_children())
        multi = len(sims) > 1
        if multi:
            cols = ["status"] + [f"s{i}" for i in range(len(sims))] + ["changes"]
            heads = ["status"] + [s.label for s in sims] + ["what changed (vs the first)"]
            widths = [70] + [260] * len(sims) + [700]
        else:
            cols = ["folder", "wind", "ws", "sims", "perws", "yaw", "dur", "psf", "uls", "fls", "acs", "osm", "sos",
                    "event", "res"]
            heads = ["folder", "wind", "wind speed [m/s]", "sims", "per WS", "yaw [deg]", "duration [s]", "PSF",
                     "ULS", "FLS", "ACS", "OS mon.", "Safety OS", "event", "results"]
            widths = [270, 60, 150, 50, 50, 110, 80, 45, 170, 120, 60, 60, 70, 300, 55]
        t.configure(columns=cols)
        t.heading("#0", text="load case", anchor="w")
        t.column("#0", width=280, stretch=False)
        for c, h, w in zip(cols, heads, widths):
            t.heading(c, text=h, anchor="w")
            t.column(c, width=w, anchor="w", stretch=c in ("changes", "event"))
        q = self.search.get().strip().lower()
        groups: dict[str, str] = {}
        counts: dict[str, int] = {}
        for r in self.rows:
            if multi and self.only_diff.get() and r.status == "same":
                continue
            first = next(iter(r.names.values()))
            if q and not any(q in n.lower() for n in r.names.values()) and q not in dlcsetup.pretty_code(first).lower():
                continue
            sit = dlcsetup.situation(first)
            if sit not in groups:
                groups[sit] = ""
            counts[sit] = counts.get(sit, 0) + 1
        for sit in dlcsetup.SITUATIONS:
            if sit in groups:
                groups[sit] = t.insert("", "end", text=dlcsetup.SITUATIONS[sit] + f"  ({counts[sit]})", open=True,
                                       tags=("group",))
        for idx, r in enumerate(self.rows):
            first = next(iter(r.names.values()))
            sit = dlcsetup.situation(first)
            if sit not in groups or not groups[sit]:
                continue
            if multi and self.only_diff.get() and r.status == "same":
                continue
            if q and not any(q in n.lower() for n in r.names.values()) and q not in dlcsetup.pretty_code(first).lower():
                continue
            if multi:
                vals = [STATUS_TEXT[r.status]]
                for s in sims:
                    n = r.names.get(s.label)
                    d = s.dlcs.get(n) if n else None
                    vals.append("-" if d is None else (n if n != first else "") + f"  [{d.nsims} sims]")
                vals.append(" | ".join(r.changes[:6]) + (f"  (+{len(r.changes) - 6})" if len(r.changes) > 6 else ""))
                tags = (r.status,)
            else:
                d = sims[0].dlcs[first]
                ev = [f.text for f in d.section("Events and faults") if not f.text.endswith("no action")]
                def fact(label, unit=""):         # an extrapolation shows its source case's values
                    t = d.fact(label).split(" (from ")[0]
                    return t.replace(unit, "") if unit else t
                vals = [first, d.wind or fact("Wind model").split(" ")[0], fact("Wind speed", " m/s"), d.nsims or "",
                        fact("Simulations per wind speed"), fact("Yaw misalignment", " deg"),
                        fact("Simulation duration", " s"), d.psf(),
                        dlcsetup.uls_text(dlcsetup.pick([u for u in d.uls if u.inp == self.uls_inp.get()], "")),
                        dlcsetup.fls_text(dlcsetup.pick([f for f in d.fls if f.inp == self.fls_inp.get()], "")),
                        dlcsetup.state(d, "ACS (adaptive control strategy)"),
                        dlcsetup.state(d, "Controller overspeed monitor"),
                        dlcsetup.state(d, "Safety overspeed system (EXC_OVRSPD)"),
                        "; ".join(ev), {True: "yes", False: "no", None: "?"}[d.results]]
                if d.tool:
                    ev = [f"{d.tool} of {d.source}" if d.source else d.tool]
                    vals[-2] = "; ".join(ev)
                tags = ("nosheet",) if d.sheet is None and not d.tool else ()
            t.insert(groups[sit], "end", iid=f"r{idx}", text=dlcsetup.pretty_code(first), values=vals, tags=tags)

    # ================================================================ card
    def _selected_row(self) -> dlcsetup.Compared | None:
        sel = self.ov.selection()
        if not sel or not sel[0].startswith("r"):
            return None
        return self.rows[int(sel[0][1:])]

    def _open_card(self):
        r = self._selected_row()
        if r is None:
            return
        self._card_row = r
        sims = [self.loaded[lb] for lb in self.shown]
        setups = [(s.label, s.dlcs.get(r.names.get(s.label, ""))) for s in sims]
        first = next(iter(r.names.values()))
        self.card_title.config(text=f"{dlcsetup.pretty_code(first)}   {' / '.join(dict.fromkeys(r.names.values()))}"
                               + (f"   ({STATUS_TEXT[r.status]})" if len(sims) > 1 else ""))
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        for lb, d in setups:
            if d is not None:
                self.desc.insert("end", (f"{lb}: " if len(setups) > 1 else "") + d.description + "\n")
            else:
                self.desc.insert("end", f"{lb}: not in this simulation.\n")
        self.desc.configure(state="disabled")
        t = self.card
        t.delete(*t.get_children())
        cols = [f"s{i}" for i in range(len(setups))]
        t.configure(columns=cols)
        t.heading("#0", text="item", anchor="w")
        t.column("#0", width=330, stretch=False)
        for c, (lb, _d) in zip(cols, setups):
            t.heading(c, text=lb if len(setups) > 1 else "value", anchor="w")
            t.column(c, width=420 if len(setups) > 1 else 900, anchor="w", stretch=True)
        rows: dict[str, dict[str, list]] = {}
        for i, (_lb, d) in enumerate(setups):
            if d is None:
                continue
            for f in d.facts:
                rows.setdefault(f.section, {}).setdefault(f.label, [""] * len(setups))[i] = f.text
            uls = rows.setdefault("ULS", {})
            for u in d.uls:
                uls.setdefault(u.inp, [""] * len(setups))[i] = dlcsetup.uls_text(u)
            fls = rows.setdefault("FLS", {})
            for f in d.fls:
                fls.setdefault(f.inp, [""] * len(setups))[i] = f"{f.case}: " + dlcsetup.fls_text(f)
            rows.setdefault("Files", {}).setdefault("Exchange sheet", [""] * len(setups))[i] = d.sheet_path or "(none)"
            if d.tool_input:
                rows["Files"].setdefault(f"{d.tool} input", [""] * len(setups))[i] = d.tool_input
            if d.error:
                rows["Files"].setdefault("Read error", [""] * len(setups))[i] = d.error
        for sec in list(dlcsetup.SECTIONS) + ["ULS", "FLS", "Files"]:
            items = rows.get(sec)
            if sec in ("ULS", "FLS") and not items:
                items = {"(not used by any input)": ["-"] * len(setups)}
            if not items:
                continue
            p = t.insert("", "end", text=sec, open=True, tags=("group",))
            for label, vals in items.items():
                clean = {v.replace(" (template)", "") for v in vals}
                only_tpl = all(v == "" or v.endswith("(template)") for v in vals)   # see Template differences
                tag = ("diff",) if len(setups) > 1 and len(clean) > 1 and sec != "Files" and not only_tpl else ()
                t.insert(p, "end", text=label, values=vals, tags=tag)
        avail = [lb for lb, d in setups if d is not None]
        self.card_sim_cb.config(values=avail)
        if self.card_sim.get() not in avail and avail:
            self.card_sim.set(avail[0])
        self._fill_sheet()
        self.nb.select(1)

    def _fill_sheet(self):
        r = getattr(self, "_card_row", None)
        lb = self.card_sim.get()
        if r is None or lb not in self.loaded or lb not in r.names:
            return
        sim = self.loaded[lb]
        d = sim.dlcs[r.names[lb]]
        self.sheet_path.config(text=d.sheet_path or (f"(no exchange sheet - {d.tool} input {d.tool_input})"
                                                     if d.tool else "(no exchange sheet)"))
        tv = self.sims_tv
        tv.delete(*tv.get_children())
        sh = d.sheet
        if sh is None:
            tv.configure(columns=("x",))
            return
        varying = [c for c in sh.columns if len(set(c.values)) > 1]
        cols = ["sim"] + [f"c{i}" for i in range(len(varying))]
        tv.configure(columns=cols)
        tv.heading("sim", text="simulation", anchor="w")
        tv.column("sim", width=330, stretch=False)
        for c, col in zip(cols[1:], varying):
            tv.heading(c, text=f"{' '.join(col.parts)} [{col.pos if col.mode == 'set' else col.mode}]", anchor="w")
            tv.column(c, width=150, anchor="w", stretch=False)
        for i, name in enumerate(sh.sims):
            tv.insert("", "end", values=[name] + [col.values[i] if i < len(col.values) else "" for col in varying])
        rt = self.raw_tv
        rt.delete(*rt.get_children())
        for col in sh.columns:
            tv_def = sim.template.value(col) if sim.template else None
            rt.insert("", "end", values=(f"{col.command} {' | '.join(col.parts)} [{col.pos}]", col.mode,
                                         tv_def[0] if tv_def else "", dlcsetup.summarize(col.values)))

    # ================================================================ templates
    def _fill_templates(self):
        t = self.tpl
        t.delete(*t.get_children())
        sims = [self.loaded[lb] for lb in self.shown]
        if len(sims) < 2:
            t.configure(columns=("x",))
            self.tpl_title.config(text="Compare two or more simulations to see their template differences.")
            return
        cols = ["line"] + [f"s{i}" for i in range(len(sims))]
        t.configure(columns=cols)
        t.heading("line", text="template line (BHawC)", anchor="w")
        t.column("line", width=380, stretch=False)
        for c, s in zip(cols[1:], sims):
            t.heading(c, text=s.label, anchor="w")
            t.column(c, width=420, anchor="w")
        keyed = [s.template.keyed() if s.template else {} for s in sims]
        keys = []
        for k in keyed:
            keys += [x for x in k if x not in keys]
        n = 0
        for k in keys:
            vals = [kk.get(k, "(not in template)") for kk in keyed]
            if len({v.lower() for v in vals}) > 1:
                t.insert("", "end", values=[k] + vals)
                n += 1
        self.tpl_title.config(text=f"{n} template lines differ (they apply to every load case). "
                              + " / ".join(f"{s.label}: {os.path.basename(s.template.path) if s.template else 'no template'}"
                                           for s in sims))

    # ================================================================ export
    def _export(self):
        if not self.shown:
            messagebox.showinfo("Export", "Read the load cases first.", parent=self.win)
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".xlsx",
                                         filetypes=[("Excel", "*.xlsx")], initialfile="load_cases.xlsx")
        if not p:
            return
        try:
            export_xlsx(p, [self.loaded[lb] for lb in self.shown], self.rows, self.uls_inp.get(), self.fls_inp.get())
        except Exception as e:                   # noqa: BLE001 - shown to the user
            messagebox.showerror("Export", str(e), parent=self.win)
            return
        self.status.config(text=f"Exported to {p}")


def export_xlsx(path: str, sims: list, rows: list, uls_inp: str = "", fls_inp: str = ""):
    """Overview (+ comparison), every card (long format) and the template differences to one workbook."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Overview"
    bold = Font(bold=True)
    fills = {k: PatternFill("solid", fgColor=v.lstrip("#")) for k, v in STATUS_TAGS.items()}
    head = ["design situation", "load case"] + (["status"] if len(sims) > 1 else []) + \
        [f"{s.label} folder" for s in sims] + [f"{s.label} sims" for s in sims] + \
        ["wind", "wind speed", "per WS", "yaw", "duration", "PSF", "ULS", "FLS", "ACS", "OS monitor", "safety OS",
         "events"] + (["what changed (vs the first)"] if len(sims) > 1 else [])
    ws.append(head)
    for c in ws[1]:
        c.font = bold
    for r in rows:
        first_sim = next(s for s in sims if s.label in r.names)
        d = first_sim.dlcs[r.names[first_sim.label]]
        line = [dlcsetup.SITUATIONS.get(d.situation, ""), d.pretty] + ([r.status] if len(sims) > 1 else [])
        line += [r.names.get(s.label, "") for s in sims]
        line += [s.dlcs[r.names[s.label]].nsims if s.label in r.names else "" for s in sims]
        line += [d.wind, d.fact("Wind speed"), d.fact("Simulations per wind speed"), d.fact("Yaw misalignment"),
                 d.fact("Simulation duration"), d.psf(),
                 dlcsetup.uls_text(dlcsetup.pick([u for u in d.uls if u.inp == uls_inp], "")),
                 dlcsetup.fls_text(dlcsetup.pick([f for f in d.fls if f.inp == fls_inp], "")),
                 dlcsetup.state(d, "ACS (adaptive control strategy)"), dlcsetup.state(d, "Controller overspeed monitor"),
                 dlcsetup.state(d, "Safety overspeed system (EXC_OVRSPD)"),
                 "; ".join(f.text for f in d.section("Events and faults") if not f.text.endswith("no action"))]
        if len(sims) > 1:
            line.append("\n".join(r.changes))
        ws.append(line)
        if len(sims) > 1 and r.status in fills:
            for c in ws[ws.max_row]:
                c.fill = fills[r.status]
    ws.freeze_panes = "C2"
    wd = wb.create_sheet("Load cases")
    wd.append(["load case", "section", "item"] + [s.label for s in sims])
    for c in wd[1]:
        c.font = bold
    for r in rows:
        setups = [s.dlcs.get(r.names.get(s.label, "")) for s in sims]
        items: dict[tuple, list] = {}
        for i, d in enumerate(setups):
            if d is None:
                continue
            items.setdefault(("Description", ""), [""] * len(sims))[i] = d.description
            for f in d.facts:
                items.setdefault((f.section, f.label), [""] * len(sims))[i] = f.text
            for u in d.uls:
                items.setdefault(("ULS", u.inp), [""] * len(sims))[i] = dlcsetup.uls_text(u)
            for f in d.fls:
                items.setdefault(("FLS", f.inp), [""] * len(sims))[i] = f"{f.case}: {dlcsetup.fls_text(f)}"
        name = next(iter(r.names.values()))
        for (sec, label), vals in items.items():
            wd.append([name, sec, label] + vals)
    if len(sims) > 1:
        wt = wb.create_sheet("Template differences")
        wt.append(["template line"] + [s.label for s in sims])
        keyed = [s.template.keyed() if s.template else {} for s in sims]
        keys = []
        for k in keyed:
            keys += [x for x in k if x not in keys]
        for k in keys:
            vals = [kk.get(k, "(not in template)") for kk in keyed]
            if len({v.lower() for v in vals}) > 1:
                wt.append([k] + vals)
    wb.save(path)
