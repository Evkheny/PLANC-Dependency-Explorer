"""(Copied from SimStatsPlotter dlcsetup.py; keep in sync.) Load cases (DLCs) of a BHawC simulation, read from their exchange sheets.

Every DLC of a simulation is a folder ``<sim>\\Btc\\<DLC>`` holding its exchange sheet
``<DLC>.xlsx`` (made by Load Basis Setup): one row per simulation, one column per change to the
template ``<sim>\\Btc\\_Template\\<sim>.btc`` - rows 2-4 give the BHawC command, its keyword and the
parameter position (or ``exclude`` / ``disable`` / ``insertafter ...``), row 6 on the values.

This module finds the DLCs, reads the sheets and the template, and turns the changes into what
the DLC simulates (wind, set-up, events, control and safety functions, model changes), adds how it
enters ULS / FLS from the run's own ``Post\\00_Input\\ULS_*.inp`` / ``FLS_*.inp``, and compares the
DLCs of several simulations. Nothing is taken from a static table: it is all read from the run.
No Tk here (the window is ``dlcview``).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

import dlc_inputs as extremes   # ULS / FLS input readers (no numpy)
import dlc_inputs as loadcalc

_CACHE_VER = 1

# ===================================================================== names
SITUATIONS = OrderedDict([
    ("1", "1.x Power production"),
    ("2", "2.x Power production with fault"),
    ("3", "3.x Start-up"),
    ("4", "4.x Normal shut-down"),
    ("5", "5.x Emergency shut-down"),
    ("6", "6.x Parked (standing still or idling)"),
    ("7", "7.x Parked with fault"),
    ("8", "8.x Transport, assembly, maintenance and repair"),
    ("9", "9.x Other (internal) load cases"),
    ("11", "11.x Earthquake"),
    ("I", "I.x Tropical cyclone"),
    ("prep", "Preparation runs (timings)"),
    ("other", "Other"),
])

# IEC 61400-1 wind condition models (the second part of the DLC folder name)
WIND_MODELS = {
    "NTM": "Normal turbulence model",
    "ETM": "Extreme turbulence model",
    "NWP": "Normal wind profile (no turbulence)",
    "EOG": "Extreme operating gust",
    "EDC": "Extreme direction change",
    "ECD": "Extreme coherent gust with direction change",
    "EWS": "Extreme wind shear",
    "EWM": "Extreme wind speed model",
    "EWM50": "Extreme wind speed model, 50-year recurrence",
    "EWM1": "Extreme wind speed model, 1-year recurrence",
    "EWMN": "Extreme wind speed model, N-year recurrence",
    "EWM500": "Extreme wind speed model, 500-year recurrence",
    "ECG": "Extreme coherent gust",
    "RWM": "Reduced wind speed model",
}

SECTIONS = ("Wind conditions", "Simulation set-up", "Events and faults", "Control functions",
            "Safety system", "Model changes", "Other BHawC changes")

_CONTROL_SWITCHES = {
    "DISABLEACS": "ACS (adaptive control strategy)",
    "DISABLEOVERSPEEDMONITOR": "Controller overspeed monitor",
    "DISABLEPITCHMOTION": "Pitch motion",
    "DISABLEPOWERBOOST": "Power Boost (PB)",
    "DISABLETRACKINGERROR": "Pitch tracking-error monitor",
}
_EVENT_PARAMS = {
    "INITIATEPITCHRUNAWAY": "Pitch runaway",
    "INITIATESENSORFAILURE": "Sensor failure",
    "INITIATESTUCKBLADEDURINGSTOP": "Blade stuck during the stop",
    "BLADESTUCK": "Blade stuck",
}


def dlc_code(name: str) -> str:
    """'DLC12a_NTM_RepTurbEQP_SS' -> 'DLC12a'."""
    return name.split("_")[0]


def situation(name: str) -> str:
    """Key of SITUATIONS for a DLC folder name."""
    m = re.match(r"DLC(I?)(\d+)", name, re.I)
    if not m:
        return "prep" if name.lower().startswith("prep") else "other"
    if m.group(1):
        return "I"
    digits = m.group(2)
    if digits.startswith("11") and len(digits) >= 3:
        return "11"
    return digits[0] if digits[0] in SITUATIONS else "other"


def pretty_code(name: str) -> str:
    """'DLC12a_...' -> 'DLC 1.2a', 'DLC111_...' -> 'DLC 11.1', 'DLCI22p_...' -> 'DLC I.22p'."""
    m = re.match(r"DLC(I?)(\d+)([A-Za-z]*)", name)
    if not m:
        return dlc_code(name)
    i, d, s = m.groups()
    if i:
        return f"DLC I.{d}{s}"
    if d.startswith("11") and len(d) >= 3:
        return f"DLC 11.{d[2:]}{s}"
    return f"DLC {d[0]}.{d[1:]}{s}" if len(d) > 1 else f"DLC {d}{s}"


def wind_model(name: str) -> tuple[str, str]:
    """(token, description) of the wind model in a DLC folder name ('' when there is none)."""
    for tok in name.split("_")[1:]:
        t = tok.upper()
        if t in WIND_MODELS:
            return tok, WIND_MODELS[t]
        m = re.match(r"(EWM|NTM|ETM|ECD|EOG|EDC|EWS|NWP|ECG)\d*", t)
        if m:
            return tok, WIND_MODELS.get(t, WIND_MODELS.get(m.group(1), ""))
    return "", ""


def base_key(name: str) -> str:
    """Name without the design-class suffix ('_SS', '_2A', ...): to match a DLC across simulations."""
    return re.sub(r"_(SS|S|[0-9][A-C])$", "", name, flags=re.I)


# ===================================================================== values
def clean(v) -> str:
    """A cell value as text: quotes removed, numbers without float noise."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return f"{v:.10g}"
    s = str(v).strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1].strip()
    return s


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def summarize(values, unit: str = "") -> str:
    """Several values of one parameter as short text: '3 - 25 step 1 (23)', '-5.6, 0, 5.6', 'x'."""
    vals = [v for v in values if v != ""] if values else []
    if not vals:
        return "(empty)" if values else ""
    uniq = list(dict.fromkeys(vals))
    u = f" {unit}" if unit else ""
    nums = [_num(v) for v in uniq]
    if all(n is not None for n in nums):
        nums = sorted(set(nums))
        if len(nums) == 1:
            return f"{nums[0]:g}{u}"
        if len(nums) <= 4:
            return ", ".join(f"{n:g}" for n in nums) + u
        steps = {round(b - a, 6) for a, b in zip(nums, nums[1:])}
        if len(steps) == 1:
            return f"{nums[0]:g} - {nums[-1]:g}{u}, step {steps.pop():g} ({len(nums)})"
        return f"{nums[0]:g} - {nums[-1]:g}{u} ({len(nums)} values)"
    if len(uniq) == 1:
        return uniq[0]
    if len(uniq) <= 4:
        return "; ".join(uniq)
    return f"{len(uniq)} different values ({uniq[0]} ... {uniq[-1]})"


# ===================================================================== exchange sheet
@dataclass
class Column:
    """One change of the exchange sheet: BHawC command, keyword (parts split at '|'), position."""
    command: str
    keyword: str
    pos: str
    values: list = field(default_factory=list)      # one per simulation (text)

    @property
    def parts(self) -> list[str]:
        return [p.strip() for p in self.keyword.split("|") if p.strip()]

    @property
    def mode(self) -> str:
        p = self.pos.strip().lower()
        if p.startswith("insert"):
            return "insert"
        if p in ("exclude", "disable"):
            return p
        return "set"

    @property
    def key(self) -> str:
        return norm(f"{self.command}|{self.keyword}|{self.pos}")

    @property
    def label(self) -> str:
        p = self.pos if self.mode == "set" else self.mode
        return f"{self.command} {' '.join(self.parts)} [{p}]"


def norm(s: str) -> str:
    """Comparable form of a BHawC key: upper case, '_' = ' ', single spaces, ' | ' between parts."""
    s = str(s).upper().replace("_", " ")
    return "|".join(" ".join(p.split()) for p in s.split("|"))


@dataclass
class Sheet:
    path: str
    name: str
    sims: list[str] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)

    def column(self, *key) -> Column | None:
        """The column whose normalised 'command|keyword...|pos' equals *key* parts joined by '|'."""
        k = norm("|".join(str(x) for x in key))
        return next((c for c in self.columns if c.key == k), None)


def read_sheet(path: str) -> Sheet:
    """Exchange sheet of one DLC: sheet 'Exchange' (else the first), header rows 2-4, values from row 6."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Exchange"] if "Exchange" in wb.sheetnames else wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    if len(rows) < 6:
        raise ValueError(f"{os.path.basename(path)}: not an exchange sheet (fewer than 6 rows)")
    width = max(len(r) for r in rows)
    rows = [r + [None] * (width - len(r)) for r in rows]
    cmd, kw, pos = rows[1], rows[2], rows[3]
    data = [r for r in rows[5:] if r[1] not in (None, "")]
    sh = Sheet(path=path, name=os.path.splitext(os.path.basename(path))[0])
    for j in range(1, width):
        if cmd[j] in (None, "") and kw[j] in (None, ""):
            continue
        c, k, p = clean(cmd[j]), clean(kw[j]), clean(pos[j])
        vals = [clean(r[j]) for r in data]
        if norm(c) == "CASE":
            sh.sims = vals
            continue
        if norm(c) == "DIRECTORY":
            continue
        sh.columns.append(Column(c, k, p, vals))
    if not sh.sims:
        sh.sims = [f"sim {i + 1}" for i in range(len(data))]
    return sh


def _sheet_to_json(sh: Sheet) -> dict:
    return {"name": sh.name, "sims": sh.sims,
            "columns": [[c.command, c.keyword, c.pos, c.values] for c in sh.columns]}


def _sheet_from_json(path: str, d: dict) -> Sheet:
    return Sheet(path=path, name=d["name"], sims=d["sims"], columns=[Column(*c) for c in d["columns"]])


def cached_sheet(path: str, cache_dir: str | None = None) -> Sheet:
    """read_sheet, kept on disk (JSON per sheet, valid while size + mtime are unchanged)."""
    st = os.stat(path)
    sig = {"v": _CACHE_VER, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    cf = None
    if cache_dir:
        cf = os.path.join(cache_dir, hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode()).hexdigest() + ".json")
        try:
            with open(cf, encoding="utf-8") as fh:
                ent = json.load(fh)
            if all(ent.get(k) == v for k, v in sig.items()):
                return _sheet_from_json(path, ent["sheet"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    sh = read_sheet(path)
    if cf:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            tmp = f"{cf}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({**sig, "path": path, "sheet": _sheet_to_json(sh)}, fh)
            os.replace(tmp, cf)
        except OSError:
            pass
    return sh


# ===================================================================== template .btc
@dataclass
class TemplateLine:
    tokens: list[str]
    comment: str


class Template:
    """The template .btc of a simulation: the default of every BHawC line an exchange sheet changes."""

    def __init__(self, path: str = "", lines: list[TemplateLine] | None = None):
        self.path = path
        self.lines = lines or []

    @classmethod
    def read(cls, path: str) -> Template:
        with open(path, encoding="latin1") as fh:
            text = fh.read()
        out = []
        for raw in text.splitlines():
            s = raw.strip()
            if not s or s.startswith(";"):
                continue
            body, _, comment = _split_comment(s)
            toks = _tokens(body)
            if len(toks) >= 2:
                out.append(TemplateLine(toks, comment.strip()))
        return cls(path, out)

    def find(self, command: str, parts: list[str]) -> tuple[list[str], str] | None:
        """(values after the keyword, comment) of the line 'command keyword...' (first match)."""
        want = norm(" ".join([command] + parts)).replace("|", " ").split()
        for ln in self.lines:
            words = []
            for i, t in enumerate(ln.tokens):
                words += norm(t).split()
                if words == want:
                    return [_unquote(x) for x in ln.tokens[i + 1:]], ln.comment
                if len(words) >= len(want):
                    break
        return None

    def value(self, col: Column) -> tuple[str, str] | None:
        """(default value, comment) the column changes, from the template ('' when not found)."""
        hit = self.find(col.command, col.parts)
        if hit is None:
            return None
        vals, comment = hit
        if col.mode == "set":
            try:
                return vals[int(float(col.pos)) - 1], comment
            except (ValueError, IndexError):
                return None
        return " ".join(vals), comment

    def keyed(self) -> dict[str, str]:
        """{normalised keyword line: its values} - to compare the templates of two simulations."""
        out = {}
        for ln in self.lines:
            if norm(ln.tokens[0]) in ("CASE", "PATH", "DIRECTORY"):
                continue                 # names / folders of the run itself
            k, vals = _line_key(ln.tokens)
            out.setdefault(k, " ".join(vals))
        return out


def _split_comment(s: str):
    q = False
    for i, ch in enumerate(s):
        if ch == '"':
            q = not q
        elif ch == ";" and not q:
            return s[:i], ";", s[i + 1:]
    return s, "", ""


def _tokens(s: str) -> list[str]:
    return re.findall(r'"[^"]*"|\S+', s)


def _unquote(t: str) -> str:
    return t[1:-1] if len(t) >= 2 and t[0] == t[-1] == '"' else t


def _line_key(tokens: list[str]) -> tuple[str, list[str]]:
    """'COMPONENT PARAMETER EXC_OVRSPD Output StopCommand=20' -> ('COMPONENT PARAMETER EXC OVRSPD OUTPUT', [...]).
    The keyword is every leading token that is a name (no digit start, no quotes / path / '=')."""
    n = 1
    cmd = norm(tokens[0])
    limit = 4 if cmd in ("COMPONENT",) else 3
    while n < len(tokens) and n < limit:
        t = tokens[n]
        if t.startswith('"') or re.match(r"^[-+.\d]", t) or "\\" in t or "=" in t:
            break
        n += 1
    return norm(" ".join(tokens[:n])), [_unquote(t) for t in tokens[n:]]


def find_template(sim_dir: str) -> str | None:
    tdir = os.path.join(sim_dir, "Btc", "_Template")
    exact = os.path.join(tdir, os.path.basename(os.path.normpath(sim_dir)) + ".btc")
    if os.path.exists(exact):
        return exact
    cands = sorted(glob.glob(os.path.join(tdir, "*.btc")), key=lambda p: (len(p), p))
    return cands[0] if cands else None


# ===================================================================== discovery
@dataclass
class DlcEntry:
    name: str
    folder: str
    sheet: str | None          # path of the exchange sheet, None when the folder has none
    results: bool | None       # results under <sim>\\Res\\<name> (None = unknown)


def is_dlc_folder(name: str) -> bool:
    n = name.lower()
    return (n.startswith("dlc") or n.startswith("prep")) and "." not in name


def find_dlcs(sim_dir: str) -> list[DlcEntry]:
    """DLC folders of ``<sim>\\Btc`` (one listing), their exchange sheets and whether results exist."""
    btc = os.path.join(sim_dir, "Btc")
    names = sorted(n for n in os.listdir(btc) if is_dlc_folder(n))
    try:
        res = set(os.listdir(os.path.join(sim_dir, "Res")))
    except OSError:
        res = None
    # the sheet path is checked when it is read (in parallel: one stat on a network drive is slow)
    return [DlcEntry(n, os.path.join(btc, n), os.path.join(btc, n, n + ".xlsx"), None if res is None else n in res)
            for n in names]


# ===================================================================== ULS / FLS of the run
@dataclass
class UlsUse:
    inp: str
    psf: float
    averaging: str
    grouping: str


@dataclass
class FlsUse:
    inp: str
    case: str
    life: float
    forced: float
    events: dict


def _matches(rule_name: str, dlc: str) -> bool:
    exact = rule_name.endswith(("\\", "/"))
    r = rule_name.rstrip("\\/")
    return dlc.lower() == r.lower() if exact else dlc.lower().startswith(r.lower())


def read_post_inputs(sim_dir: str) -> tuple[dict, dict]:
    """({ULS inp name: UlsSetup}, {FLS inp name: FlsSetup}) of ``<sim>\\Post\\00_Input``; unreadable ones skipped."""
    uls, fls = {}, {}
    for p in extremes.find_uls_setups(sim_dir):
        try:
            uls[os.path.basename(p)] = extremes.read_uls_inp(p)
        except (OSError, ValueError):
            pass
    for p in loadcalc.find_fls_setups(sim_dir):
        try:
            fls[os.path.basename(p)] = loadcalc.read_fls_inp(p)
        except (OSError, ValueError):
            pass
    return uls, fls


def main_input(names) -> str:
    """The run's main input among several (the shortest name: ULS_All_RNA.inp before ULS_All_RNA_RES.inp)."""
    names = sorted(names, key=lambda n: (len(n), n))
    return names[0] if names else ""


def uls_uses(name: str, uls: dict) -> list[UlsUse]:
    out = []
    for inp, setup in uls.items():
        for r in setup.rules:
            if _matches(r.name, name):
                out.append(UlsUse(inp, r.psf, r.averaging, r.grouping))
                break
    return out


def fls_uses(name: str, fls: dict) -> list[FlsUse]:
    out = []
    for inp, setup in fls.items():
        for c in setup.cases:
            ids = [i.rstrip("\\/").lower() for i in c.ids if i.strip()]
            if any(i == name.lower() or name.lower().startswith(i) for i in ids):
                out.append(FlsUse(inp, c.name, c.life, c.forced, dict(c.events)))
                break
    return out


# ===================================================================== interpretation
@dataclass
class Fact:
    section: str
    label: str
    text: str
    key: str = ""              # what is compared across simulations (defaults to section|label)


@dataclass
class DlcSetup:
    name: str
    sim_dir: str = ""
    sheet_path: str | None = None
    results: bool | None = None
    nsims: int = 0
    facts: list[Fact] = field(default_factory=list)
    uls: list[UlsUse] = field(default_factory=list)
    fls: list[FlsUse] = field(default_factory=list)
    sheet: Sheet | None = None
    error: str = ""
    tool: str = ""                         # post-processing case: its tool ('extrapolation'), no sheet
    tool_input: str | None = None          # path of its tool input (.inp)
    source: str = ""                       # the DLC whose simulations it uses

    # ---- identity
    @property
    def code(self) -> str:
        return dlc_code(self.name)

    @property
    def pretty(self) -> str:
        return pretty_code(self.name)

    @property
    def situation(self) -> str:
        return situation(self.name)

    @property
    def wind(self) -> str:
        return wind_model(self.name)[0]

    # ---- facts
    def fact(self, label: str) -> str:
        f = next((f for f in self.facts if f.label == label), None)
        return f.text if f else ""

    def section(self, name: str) -> list[Fact]:
        return [f for f in self.facts if f.section == name]

    def comparable(self) -> dict[str, str]:
        return {f.key or f"{f.section}|{f.label}": f.text for f in self.facts}

    @property
    def description(self) -> str:
        """What the DLC simulates, in one paragraph built from what its sheet changes."""
        if self.tool == "extrapolation":
            src = self.source or "?"
            return (f"Statistical extrapolation of the extreme loads (DLC 1.1, post-processing - not simulated "
                    f"itself) from the simulations of {src}: {self.fact('Fitted distribution')} fit of the "
                    f"{self.fact('Extremes extracted').split(' (')[0]}, exceedance probability "
                    f"{self.fact('Exceedance probability')}, {self.fact('Wind distribution')}.")
        tok, wind_txt = wind_model(self.name)
        bits = [SITUATIONS.get(self.situation, "").split(" ", 1)[-1]]
        if wind_txt:
            ws = self.fact("Wind speed")
            bits.append(f"{wind_txt} ({tok})" + (f", wind speed {ws}" if ws else ""))
        ev = [f.text if f.label.startswith("Timer") else f"{f.label}: {f.text}" for f in self.section("Events and faults")
              if not f.text.endswith("no action")]
        if ev:
            bits.append("Events: " + "; ".join(ev))
        off = [f.label for f in self.section("Control functions") + self.section("Safety system")
               if f.text.lower().startswith(("disabled", "inactive", "output disconnected"))
               and not f.text.endswith("(template)")]
        if off:
            bits.append("Not active: " + ", ".join(off))
        if self.sheet is None and not self.tool:
            bits.append("No exchange sheet in the DLC folder.")
        return ". ".join(b for b in bits if b) + "."

    def psf(self) -> str:
        return self.fact("Partial safety factor (TOTF Psf)")


def _per_value_counts(values) -> str:
    c = Counter(values)
    counts = set(c.values())
    if len(counts) == 1:
        return f"{counts.pop()}"
    return f"{min(counts)} - {max(counts)}"


def interpret(sheet: Sheet | None, template: Template | None = None, name: str = "") -> list[Fact]:
    """The facts of one DLC (wind, set-up, events, control, safety, model) from its exchange sheet,
    with the template's default where a known parameter is not changed."""
    if sheet is None:
        return []
    facts: list[Fact] = []
    used: set[int] = set()
    cols = sheet.columns

    def col(*key):
        c = sheet.column(*key)
        if c is not None:
            used.add(id(c))
        return c

    def default(*key):
        """Template value of a 'set' parameter the sheet does not change."""
        if template is None:
            return None
        cmd, *rest = key
        pos = rest[-1]
        hit = template.find(cmd, [r for r in rest[:-1]])
        if hit is None:
            return None
        try:
            return hit[0][int(pos) - 1]
        except (ValueError, IndexError):
            return None

    def add(section, label, text, key=""):
        if text != "":
            facts.append(Fact(section, label, text, key))

    def param(label, unit, *key, section="Wind conditions", tmpl=True):
        c = col(*key)
        if c is not None:
            add(section, label, summarize(c.values, unit))
        elif tmpl:
            d = default(*key)
            if d is not None:
                add(section, label, f"{summarize([d], unit)} (template)")

    W = "Wind conditions"
    S = "Simulation set-up"
    # ---- wind
    tok, wtxt = wind_model(name or sheet.name)
    if wtxt:
        add(W, "Wind model", f"{tok} - {wtxt}")
    ws = col("ENVIRONMENT", "WIND FIELD SHEAR", "2")
    if ws is not None:
        add(W, "Wind speed", summarize(ws.values, "m/s"))
    else:
        d = default("ENVIRONMENT", "WIND FIELD SHEAR", "2")
        if d is not None:
            add(W, "Wind speed", f"{summarize([d], 'm/s')} (template)")
    turb = col("ENVIRONMENT", "APPLY TURBULENCE", "1")
    if turb is not None and all(v in ("0", "0.0") for v in turb.values):
        add(W, "Turbulence", "none (laminar inflow)")
    ti = col("ENVIRONMENT", "WIND FIELD SHEAR", "6")
    if ti is not None and not (turb is not None and all(v in ("0", "0.0") for v in turb.values)):
        nti = len(set(ti.values))
        nws = len(set(ws.values)) if ws is not None else 1
        kind = " - a distribution per wind speed (RepTurb)" if nti > nws * 1.5 else ""
        add(W, "Turbulence intensity", summarize(ti.values) + kind)
    param("Wind shear exponent", "", "ENVIRONMENT", "WIND FIELD SHEAR", "7")
    param("Inflow angle (terrain slope)", "deg", "ENVIRONMENT", "WIND FIELD SHEAR", "5")
    param("Air density", "kg/m3", "ENVIRONMENT", "WIND FIELD SHEAR", "1")
    param("Shear profile type", "", "ENVIRONMENT", "WIND FIELD SHEAR", "8", tmpl=False)
    param("Reference height", "m", "ENVIRONMENT", "WIND FIELD SHEAR", "3", tmpl=False)
    param("Mann grid (parameter 2)", "", "ENVIRONMENT", "TURBULENCE MANN GRID", "2", tmpl=False)
    gx = col("ENVIRONMENT", "WIND GUST", "exclude")
    gust = [c for c in cols if norm(c.command) == "ENVIRONMENT" and norm(c.keyword) == "WIND GUST" and c.mode == "set"]
    for c in gust:
        used.add(id(c))
    if gust:
        gtype = next((c for c in gust if c.pos == "1"), None)
        desc = ", ".join(f"p{c.pos} = {summarize(c.values)}" for c in sorted(gust, key=lambda c: c.pos))
        add(W, "Gust (WIND_GUST)", ("type " + summarize(gtype.values) + ": " if gtype else "") + desc)
    elif gx is not None:
        add(W, "Gust", "none (WIND_GUST removed)")
    for c in cols:
        if norm(c.command) == "FILENAME" and "GUST" in norm(c.keyword):
            used.add(id(c))
            add(W, "Gust file", summarize([os.path.basename(v.replace("\\", "/")) for v in c.values]))

    # ---- simulation set-up
    add(S, "Simulations", str(len(sheet.sims)))
    if ws is not None:
        add(S, "Simulations per wind speed", _per_value_counts(ws.values))
    yaw = col("ENVIRONMENT", "WIND FIELD SHEAR", "4")
    if yaw is not None:
        add(S, "Yaw misalignment", summarize(yaw.values, "deg"))
    seed = col("ENVIRONMENT", "TURBULENCE MANN TENSOR", "4")
    if seed is not None:
        add(S, "Turbulence seeds", f"{len(set(seed.values))} different")
    dur = col("SIMULATE", "DYN RESPONSE", "1")
    if dur is not None:
        add(S, "Simulation duration", summarize(dur.values, "s"))
    else:
        d = default("SIMULATE", "DYN RESPONSE", "1")
        if d is not None:
            add(S, "Simulation duration", f"{summarize([d], 's')} (template)")
    param("Time step", "s", "SIMULATE", "DYN RESPONSE", "2", section=S, tmpl=False)
    az = col("INITIAL CONDITIONS", "ROTOR ROTATION", "1")
    if az is not None:
        add(S, "Azimuth (initial)", summarize(az.values, "deg"))
    param("Initial rotor speed", "rpm", "INITIAL CONDITIONS", "ROTOR ROTATION", "2", section=S, tmpl=False)
    param("Initial pitch", "deg", "INITIAL CONDITIONS", "PITCH BEARINGS", "1", section=S, tmpl=False)
    for c in cols:
        if norm(c.command) in ("SIMULATION CONDIT",) and id(c) not in used:
            used.add(id(c))
            tv = template.value(c) if template else None
            add(S, f"Initialisation (SIMULATION_CONDIT DYN_RESPONSE p{c.pos})",
                summarize(c.values) + (f"  (template {tv[0]})" if tv else ""))
    psf = col("COMPONENT", "PARAMETER", "TOTF Psf", "3")
    if psf is not None:
        add(S, "Partial safety factor (TOTF Psf)", summarize(psf.values))

    # ---- timers (events at a time / signal threshold)
    E = "Events and faults"
    for n in range(1, 6):
        inp = col("COMPONENT", "PARAMETER", f"TIMER{n} Input", "3")
        thr = col("COMPONENT", "PARAMETER", f"TIMER{n} Threshold", "3")
        out = col("COMPONENT", "PARAMETER", f"TIMER{n} Output", "3")
        if not (inp or thr or out):
            continue
        i_txt = summarize(inp.values) if inp else "NormalFullTime [s]"
        t_txt = summarize(thr.values) if thr else "0"
        o_txt = summarize(out.values) if out else ""
        if not o_txt or o_txt == "(empty)":
            add(E, f"Timer {n}", f"{i_txt} = {t_txt}: no action")
        else:
            add(E, f"Timer {n}", f"when {i_txt} = {t_txt}: {o_txt}")

    # ---- component parameters
    C, SF, M, O = "Control functions", "Safety system", "Model changes", "Other BHawC changes"
    added: dict[str, list[Column]] = {}
    for c in cols:
        if id(c) in used:
            continue
        ncmd = norm(c.command)
        if ncmd != "COMPONENT":
            continue
        parts = c.parts
        rest = " ".join(parts[1:]).split()
        comp = rest[0] if rest else ""
        pname = " ".join(rest[1:]) if len(rest) > 1 else ""
        ucomp, upar = comp.upper(), norm(pname).replace(" ", "")
        used.add(id(c))
        if ucomp == "TOTF":
            if c.mode == "disable":
                add(O, "Load transformation (TOTF)", "disabled" if _truthy(c.values) else "enabled")
            continue
        if ucomp == "CONTROLLER" and upar in _CONTROL_SWITCHES:
            add(C, _CONTROL_SWITCHES[upar], "disabled", key=f"{C}|{_CONTROL_SWITCHES[upar]}")
            continue
        if ucomp in ("CONTROLLER", "PITCH") and upar in _EVENT_PARAMS:
            add(E, _EVENT_PARAMS[upar], summarize(c.values) + f"  ({pname})")
            continue
        if ucomp == "CONTROLLER" and upar == "SCALEACSTHRESHOLDS":
            add(C, "ACS (adaptive control strategy)", f"active, thresholds x {summarize(c.values)}",
                key=f"{C}|ACS (adaptive control strategy)")
            continue
        if ucomp == "CONTROLLER" and upar == "SCALEBLLTHRESHOLD":
            add(C, "BLL thresholds", f"x {summarize(c.values)}")
            continue
        if ucomp == "CONTROLLER" and upar == "ENABLEOVERSPEED":
            add(E, "Controller overspeed (EnableOverspeed)", summarize(c.values))
            continue
        if ucomp == "CONTROLLER":
            add(C, f"Controller parameter {pname}", summarize(c.values))
            continue
        if ucomp == "EXC_OVRSPD":
            if upar == "OUTPUT":
                v = summarize(c.values)
                add(SF, "Safety overspeed system (EXC_OVRSPD)",
                    "output disconnected (inactive)" if v in ("(empty)", "") else f"active, output {v}")
            elif upar.startswith("ACTIHS") or upar.startswith("ACTPRPS"):
                v = summarize(c.values)
                add(SF, f"Safety monitor {pname}", {"1": "active", "0": "inactive"}.get(v, v))
            else:
                add(SF, f"Safety parameter {pname}", summarize(c.values))
            continue
        if ucomp in ("CCU_OVRSPD", "CCU_OVRSPD_STOP"):
            if c.mode == "disable":
                add(SF, f"Converter overspeed trip ({comp})", "disabled" if _truthy(c.values) else "enabled",
                    key=f"{SF}|{comp}")
            continue
        if ucomp == "PITSHUTDOWN":
            v = summarize(c.values)
            add(SF, f"Pitch shutdown ({pname})", "output disconnected (inactive)" if v in ("(empty)", "") else v)
            continue
        added.setdefault(comp, []).append(c)
    for comp, cs in added.items():
        define = next((c for c in cs if norm(c.parts[0]) == "DEFINE"), None)
        params = [c for c in cs if c is not define]
        what = os.path.splitext(os.path.basename((summarize(define.values) if define else "").replace("\\", "/")))[0]
        txt = "; ".join(f"{' '.join(c.parts[1:]).split(' ', 1)[-1]} = {summarize(c.values)}" for c in params)
        head = f"added ({what})" if define is not None and define.mode == "insert" else (
            "disabled" if define is not None and define.mode == "disable" and _truthy(define.values) else "")
        add(M if comp.upper() not in ("GENCONV",) else C, f"Component {comp}", ", ".join(x for x in (head, txt) if x))

    # ---- model changes
    for c in cols:
        if id(c) in used:
            continue
        ncmd, nkw = norm(c.command), norm(c.keyword)
        tv = template.value(c) if template else None
        tdef = f"  (template {tv[0]})" if tv and tv[0] != "" else ""
        if ncmd == "MODEL" and nkw == "PITCH MOUNTING ERROR":
            add(M, f"Pitch mounting error, blade {c.pos}", summarize(c.values, "deg") + tdef)
        elif ncmd == "CONCENTRATED MASS":
            add(M, f"Concentrated mass {' '.join(c.parts)} (p{c.pos})", summarize(c.values) + tdef)
        elif ncmd == "MODEL" and "MECHANICAL BRAKE" in nkw:
            if c.mode == "disable":
                add(M, "Mechanical brake actuator", "disabled" if _truthy(c.values) else "enabled",
                    key=f"{M}|Mechanical brake actuator")
            else:
                add(M, f"Mechanical brake actuator (p{c.pos})", summarize(c.values) + tdef)
        elif ncmd == "MODEL" and "BOUNDARY CONDITION" in nkw:
            vals = [v for v in c.values if v.strip()]
            add(M, f"Boundary condition {' '.join(c.parts[1:])}",
                ("clamped (" + summarize(vals) + ")") if vals else "(empty)")
        elif ncmd == "AERODYN" and c.mode == "exclude":
            add(M, f"Aerodynamics: {' '.join(c.parts)}", "removed (not applied)")
        elif ncmd == "AERODYN":
            add(M, f"Aerodynamics: {' '.join(c.parts)} (p{c.pos})", summarize(c.values) + tdef)
        elif ncmd == "FILENAME":
            add(M, f"File: {' '.join(c.parts)}",
                summarize([os.path.basename(v.replace("\\", "/")) for v in c.values]))
        elif ncmd in ("TYPES", "DAMPING", "NODE", "ELEMENT", "INTEGRATION", "DEFAULTS", "MODEL"):
            add(M, c.label, summarize(c.values) + tdef)
        elif ncmd == "ENVIRONMENT" and c.mode == "exclude":
            add(W, f"{' '.join(c.parts)}", "removed (not applied)")
        else:
            add(O, c.label, summarize(c.values) + tdef)
        used.add(id(c))
    return facts


def template_functions(facts: list[Fact], template: Template | None) -> list[Fact]:
    """The control and safety functions the sheet does not change, with their state in the template -
    so every DLC lists all of them (active / disabled), not only the changed ones."""
    if template is None:
        return []
    have = {f.key or f"{f.section}|{f.label}" for f in facts}
    out = []

    def add(section, label, text):
        k = f"{section}|{label}"
        if k not in have:
            out.append(Fact(section, label, f"{text} (template)", k))
            have.add(k)

    C, SF = "Control functions", "Safety system"
    for flag, label in _CONTROL_SWITCHES.items():
        hit = next((ln for ln in template.lines if norm(" ".join(ln.tokens[:4])).replace(" ", "")
                    == f"COMPONENTPARAMETERCONTROLLER{flag}"), None)
        add(C, label, "disabled" if hit is not None else "active")
    for ln in template.lines:
        t = ln.tokens
        if len(t) >= 5 and norm(t[0]) == "COMPONENT" and norm(t[1]) == "PARAMETER" and norm(t[2]) == "EXC OVRSPD":
            name = t[3]
            if norm(name) == "OUTPUT":
                v = _unquote(t[4])
                add(SF, "Safety overspeed system (EXC_OVRSPD)",
                    "output disconnected (inactive)" if not v else f"active, output {v}")
            elif name.upper().startswith(("ACTIHS", "ACTPRPS")):
                add(SF, f"Safety monitor {name}", {"1": "active", "0": "inactive"}.get(_unquote(t[4]), _unquote(t[4])))
        if len(t) >= 3 and norm(t[0]) == "COMPONENT" and norm(t[1]) == "DEFINE" and t[2].upper() in (
                "CCU_OVRSPD", "CCU_OVRSPD_STOP"):
            add(SF, f"Converter overspeed trip ({t[2]})", "enabled")
    return out


def read_tool_input(path: str) -> tuple[str, dict[str, str]]:
    """(tool, {key: value}) of a MATLAB tool input (``key : value`` lines between <START> and <END>,
    ``%`` comments), e.g. the ``extrapolation`` input of a DLC 1.1 folder."""
    with open(path, encoding="latin1") as fh:
        text = fh.read()
    tool, keys, active = "", {}, False
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith("<START>"):
            active = True
            continue
        if line.upper().startswith("<END>"):
            break
        if not line or line.startswith("%") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.split("%", 1)[0].strip()
        if not active:
            if k.lower() == "inputfile":
                tool = v
            continue
        keys[k] = v
    return tool, keys


_EXTRAP_ROLES = {"wbl3": "3-parameter Weibull", "wbl": "Weibull", "gev": "generalised extreme value",
                 "gumbel": "Gumbel", "BM": "block maxima", "POT": "peaks over threshold"}


def interpret_extrapolation(keys: dict[str, str]) -> list[Fact]:
    """Facts of a DLC 1.1 extrapolation from its tool input (SourceDir, Weibull, fit settings)."""
    W, S, O = "Wind conditions", "Simulation set-up", "Other BHawC changes"
    facts = []

    def add(section, label, text):
        if text not in ("", None):
            facts.append(Fact(section, label, text))
    src = os.path.basename(keys.get("SourceDir", "").rstrip("\\/"))
    add(S, "Source load case (simulations used)", src)
    if keys.get("WeibullA"):
        add(W, "Wind distribution", f"Weibull A = {keys['WeibullA']} m/s, k = {keys.get('Weibullk') or '2 (default)'}")
    elif keys.get("AverageWind"):
        add(W, "Wind distribution", f"Rayleigh, mean wind {keys['AverageWind']} m/s")
    dist = keys.get("DistType", "")
    add(S, "Fitted distribution", f"{dist} ({_EXTRAP_ROLES.get(dist, dist)})" if dist else "")
    ext = keys.get("ExtractType", "")
    sec = keys.get("BMsections", "")
    add(S, "Extremes extracted", (f"{_EXTRAP_ROLES.get(ext, ext)} ({ext}"
                                  + (f", {sec} sections per simulation" if sec and ext == "BM" else "") + ")") if ext else "")
    p = keys.get("ExcProb", "")
    if p:
        try:
            yrs = 1.0 / (float(p) * 6 * 24 * 365.25)
            add(S, "Exceedance probability", f"{p} per 10 min (return period ~{yrs:.0f} years)")
        except ValueError:
            add(S, "Exceedance probability", p)
    add(S, "Fit method", " / ".join(x for x in (keys.get("LSorMLE", ""), keys.get("OptiType", "")) if x))
    add(S, "Quantile", keys.get("Quantile", ""))
    add(S, "Minimum points / time (Nmin, Tmin)",
        " / ".join(x for x in (keys.get("Nmin", ""), keys.get("Tmin", "")) if x))
    add(S, "Cut-in / cut-out", " / ".join(x for x in (keys.get("CutIn", ""), keys.get("CutOut", "")) if x))
    add(S, "Results folder", os.path.basename(keys.get("ResultDir", "").rstrip("\\/")))
    known = {"SourceDir", "WeibullA", "Weibullk", "AverageWind", "DistType", "ExtractType", "BMsections", "ExcProb",
             "LSorMLE", "OptiType", "Quantile", "Nmin", "Tmin", "CutIn", "CutOut", "ResultDir"}
    for k, v in keys.items():
        if k not in known and v:
            add(O, f"extrapolation input: {k}", v)
    return facts


def find_tool_input(folder: str, name: str) -> str | None:
    """The tool input of a DLC folder without exchange sheet: <name>.inp, else the only .inp in it."""
    exact = os.path.join(folder, name + ".inp")
    if os.path.exists(exact):
        return exact
    try:
        inps = [n for n in os.listdir(folder) if n.lower().endswith(".inp")]
    except OSError:
        return None
    return os.path.join(folder, inps[0]) if len(inps) == 1 else None


def _truthy(values) -> bool:
    return any(str(v).strip().lower() in ("true", "1", "yes") for v in values)


def build(entry: DlcEntry, sheet: Sheet | None, template: Template | None, uls: dict, fls: dict,
          sim_dir: str = "", error: str = "") -> DlcSetup:
    s = DlcSetup(name=entry.name, sim_dir=sim_dir, sheet_path=entry.sheet, results=entry.results, sheet=sheet,
                 error=error)
    s.nsims = len(sheet.sims) if sheet else 0
    facts = interpret(sheet, template, entry.name)
    if sheet is not None:
        facts += template_functions(facts, template)
    order = {n: i for i, n in enumerate(SECTIONS)}
    s.facts = sorted(facts, key=lambda f: order.get(f.section, len(order)))   # stable: sheet order kept
    s.uls = uls_uses(entry.name, uls)
    s.fls = fls_uses(entry.name, fls)
    return s


@dataclass
class SimDlcs:
    """All DLCs of one simulation."""
    label: str
    sim_dir: str
    dlcs: "OrderedDict[str, DlcSetup]" = field(default_factory=OrderedDict)
    template: Template | None = None
    uls: dict = field(default_factory=dict)
    fls: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def load_sim(label: str, sim_dir: str, cache_dir: str | None = None, workers: int = 8, progress=None) -> SimDlcs:
    """Every DLC of a simulation with its exchange sheet read (in parallel; cached on disk)."""
    from concurrent.futures import ThreadPoolExecutor
    out = SimDlcs(label, sim_dir)
    done = [0]
    lock = threading.Lock()
    entries: list[DlcEntry] = []

    def template():
        tp = find_template(sim_dir)
        if not tp:
            out.warnings.append("No template .btc in Btc\\_Template: parameters not changed by a sheet are not shown.")
            return None
        try:
            return Template.read(tp)
        except OSError as e:
            out.warnings.append(f"Template {tp}: {e}")
            return None

    def sheet_of(e: DlcEntry):
        sheet, err = None, ""
        try:
            sheet = cached_sheet(e.sheet, cache_dir)
        except FileNotFoundError:
            e.sheet = None                   # a folder without exchange sheet (e.g. DLC11 extrapolation)
            inp = find_tool_input(e.folder, e.name)
            if inp:
                try:
                    tool, keys = read_tool_input(inp)
                    err = ("tool", inp, tool, keys)
                except OSError as ex:
                    err = f"{type(ex).__name__}: {ex}"
        except Exception as ex:              # noqa: BLE001 - reported per DLC
            err = f"{type(ex).__name__}: {ex}"
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], len(entries), e.name)
        return sheet, err

    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool:
        f_tpl = pool.submit(template)
        f_post = pool.submit(read_post_inputs, sim_dir)
        entries = find_dlcs(sim_dir)
        sheets = list(pool.map(sheet_of, entries))
        out.template = f_tpl.result()
        out.uls, out.fls = f_post.result()
    for e, (sheet, err) in zip(entries, sheets):
        tool = err if isinstance(err, tuple) else None
        d = build(e, sheet, out.template, out.uls, out.fls, sim_dir, "" if tool else err)
        if tool:
            _kind, d.tool_input, d.tool, keys = tool
            d.facts = interpret_extrapolation(keys) if d.tool.lower() == "extrapolation" else [
                Fact("Other BHawC changes", f"{d.tool} input: {k}", v) for k, v in keys.items() if v]
            d.source = d.fact("Source load case (simulations used)")
        out.dlcs[e.name] = d
    for d in out.dlcs.values():               # the wind and simulations of the source case
        src = out.dlcs.get(d.source) if d.source else None
        if src is not None:
            d.nsims = src.nsims
            for label in ("Wind model", "Wind speed", "Turbulence intensity", "Wind shear exponent"):
                t = src.fact(label)
                if t:
                    d.facts.append(Fact("Wind conditions", label, f"{t} (from {src.name})"))
            for label in ("Simulations", "Simulations per wind speed", "Yaw misalignment", "Simulation duration"):
                t = src.fact(label)
                if t:
                    d.facts.append(Fact("Simulation set-up", label, f"{t} (from {src.name})"))
            order = {n: i for i, n in enumerate(SECTIONS)}
            d.facts.sort(key=lambda f: order.get(f.section, len(order)))
    return out


# ===================================================================== comparison
@dataclass
class Compared:
    key: str                               # base name (design-class suffix removed)
    names: dict                            # label -> DLC folder name (missing = not in that simulation)
    status: str                            # same / changed / new / removed / only (single sim)
    changes: list[str] = field(default_factory=list)


def compare(sims: list[SimDlcs]) -> list[Compared]:
    """DLCs of several simulations against the FIRST one: new (not in the first), removed (in the first,
    not in another), changed (same DLC, other set-up: the list says what) or same."""
    if not sims:
        return []

    def same(a, b):
        return a == b or base_key(a) == base_key(b)

    order: list[str] = []                    # one name per DLC, in the order of the simulations
    for s in sims:
        for n in s.dlcs:
            if not any(same(n, o) for o in order):
                order.append(n)
    ref = sims[0]
    out = []
    for n in order:
        names = {}
        for s in sims:
            hit = n if n in s.dlcs else next((x for x in s.dlcs if same(x, n)), None)
            if hit:
                names[s.label] = hit
        if len(sims) == 1:
            out.append(Compared(n, names, "only"))
            continue
        if ref.label not in names:
            out.append(Compared(n, names, "new", [f"not in {ref.label}"]))
            continue
        missing = [s.label for s in sims if s.label not in names]
        a = ref.dlcs[names[ref.label]]
        changes = []
        for s in sims[1:]:
            if s.label not in names:
                continue
            b = s.dlcs[names[s.label]]
            for line in diff_setups(a, b):
                changes.append(f"{s.label}: {line}" if len(sims) > 2 else line)
        if missing:
            status = "removed"
            changes = [f"not in {', '.join(missing)}"] + changes
        else:
            status = "changed" if changes else "same"
        out.append(Compared(n, names, status, changes))
    return out


def diff_setups(a: DlcSetup, b: DlcSetup) -> list[str]:
    """What differs between two set-ups of a DLC, one line per item ('label: a -> b')."""
    da, db = a.comparable(), b.comparable()
    lines = []
    if a.name != b.name:
        lines.append(f"folder: {a.name} -> {b.name}")
    for k in list(da) + [k for k in db if k not in da]:
        va, vb = da.get(k, ""), db.get(k, "")
        if (va == "" or va.endswith("(template)")) and (vb == "" or vb.endswith("(template)")):
            continue                     # set by the templates only: shown in the template comparison
        va_c, vb_c = va.replace(" (template)", ""), vb.replace(" (template)", "")
        if va_c != vb_c:
            label = k.split("|", 1)[-1]
            lines.append(f"{label}: {va or '(not set)'} -> {vb or '(not set)'}")
    ua = {(u.inp, u.psf, u.averaging, u.grouping) for u in a.uls}
    ub = {(u.inp, u.psf, u.averaging, u.grouping) for u in b.uls}
    if bool(a.uls) != bool(b.uls):
        lines.append(f"ULS: {'yes' if a.uls else 'no'} -> {'yes' if b.uls else 'no'}")
    elif ua != ub and a.uls and b.uls:
        x, y = a.uls[0], b.uls[0]
        if (x.psf, x.averaging, x.grouping) != (y.psf, y.averaging, y.grouping):
            lines.append(f"ULS: PSF {x.psf:g} {x.averaging} {x.grouping} -> PSF {y.psf:g} {y.averaging} {y.grouping}")
    if bool(a.fls) != bool(b.fls):
        lines.append(f"FLS: {'yes' if a.fls else 'no'} -> {'yes' if b.fls else 'no'}")
    elif a.fls and b.fls:
        x, y = a.fls[0], b.fls[0]
        if (x.life, x.forced, x.events) != (y.life, y.forced, y.events):
            lines.append(f"FLS: {fls_text(x)} -> {fls_text(y)}")
    return lines


def compare_templates(a: Template | None, b: Template | None) -> list[tuple[str, str, str]]:
    """(BHawC line, value in a, value in b) of the template lines that differ between two simulations."""
    if a is None or b is None:
        return []
    ka, kb = a.keyed(), b.keyed()
    out = []
    for k in list(ka) + [k for k in kb if k not in ka]:
        if str(ka.get(k)).lower() != str(kb.get(k)).lower():           # paths: r:\ = R:\ 
            out.append((k, ka.get(k, "(not in template)"), kb.get(k, "(not in template)")))
    return out


# ===================================================================== short texts for tables
def uls_text(u: UlsUse | None) -> str:
    return "" if u is None else f"PSF {u.psf:g}, {u.averaging}, {u.grouping}"


def fls_text(f: FlsUse | None) -> str:
    if f is None:
        return ""
    bits = [f"{f.life:g} y"]
    if f.forced:
        bits.append(f"{f.forced:g} /y")
    if f.events:
        bits.append(", ".join(f"{k} {v:g}/y" for k, v in f.events.items()))
    return "; ".join(bits)


def pick(uses: list, inp: str):
    """The use of *inp* (the chosen input file), else the first one."""
    return next((u for u in uses if u.inp == inp), uses[0] if uses else None)


def state(s: DlcSetup, label: str) -> str:
    """Short state of a control / safety function for the overview: 'off', 'x1.2', 'on' or ''."""
    t = s.fact(label)
    if not t:
        return ""
    lt = t.lower()
    if lt.startswith(("disabled", "inactive", "output disconnected")):
        return "off"
    m = re.search(r"x\s*([-\d.]+)", t)
    if "thresholds" in lt and m:
        return f"x{m.group(1)}"
    return "on"
