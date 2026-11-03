r"""ULS / FLS post-processing input readers (Post\00_Input\ULS_*.inp / FLS_*.inp), copied unchanged from SimStatsPlotter
(extremes.py / loadcalc.py) without their numpy parts, so dlcsetup can run inside the PLANC Dependency Explorer."""
from __future__ import annotations

import glob
import math
import os
import re
from dataclasses import dataclass, field

@dataclass
class FlsCase:
    name: str
    ids: list[str]              # DLC folder (search string) per input line
    life: float                 # L [years]
    A: float                    # Weibull scale (0 = no Weibull weighting)
    k: float
    ituci: int                  # 1 = time below the lowest wind speed is included
    forced: float = 0.0         # events / year, Weibull distributed
    events: dict = field(default_factory=dict)   # cutin / rated / ... -> events / year

AVERAGING = ("max", "mean", "meanhalf", "meanrun", "mean3std", "mean3", "mean6")
_EVENT_FIELDS = ("cutin", "rated", "startuplim", "hwrtactivate", "cutout", "hwrtcutout", "allfiles")

@dataclass
class UlsRule:
    """One ``Case`` line: a DLC folder, its partial safety factor, averaging and grouping."""
    name: str                   # folder id as written (trailing backslash = exact folder)
    psf: float
    averaging: str
    grouping: str

    @property
    def short(self) -> str:
        return self.name.rstrip("\\/")


@dataclass
class UlsSetup:
    path: str
    source_dir: str = ""
    turbine: str = ""
    uls_name: str = ""
    rules: list[UlsRule] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def read_uls_inp(path: str) -> UlsSetup:
    """``ulsautosetup`` input file: ``key : value`` lines between ``<START>`` and ``<END>``;
    ``%`` starts a comment; ``Case : <id> <psf> <averaging> <grouping>``."""
    with open(path, encoding="latin1") as fh:
        text = fh.read()
    setup = UlsSetup(path=path)
    active = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith("<START>"):
            active = True
            continue
        if line.upper().startswith("<END>"):
            break
        if not active or not line or line.startswith("%") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.split("%", 1)[0].strip()
        if key == "case":
            parts = value.split()
            if len(parts) < 4:
                setup.warnings.append(f"Case line with fewer than 4 values ignored: {value}")
                continue
            try:
                setup.rules.append(UlsRule(parts[0], float(parts[1]), parts[2].lower(), parts[3]))
            except ValueError:
                setup.warnings.append(f"Case line with a wrong safety factor ignored: {value}")
        elif key == "source_directory":
            setup.source_dir = value
        elif key == "turbine":
            setup.turbine = value.strip("'\"")
        elif key == "uls_name":
            setup.uls_name = value
    for r in setup.rules:
        if r.averaging not in AVERAGING:
            setup.warnings.append(f"{r.short}: averaging '{r.averaging}' is not implemented")
    return setup


def find_uls_setups(sim_dir: str) -> list[str]:
    """ULS input files of a simulation: ``<sim>\\Post\\00_Input\\ULS*.inp``."""
    return sorted(glob.glob(os.path.join(sim_dir, "Post", "00_Input", "ULS*.inp")))


@dataclass
class FlsSetup:
    path: str
    turbine: str
    cut_in: float
    rated: float
    cut_out: float
    availability: float = 100.0
    startup_limit: float | None = None
    hwrt_activate: float | None = None
    hwrt_cut_out: float | None = None
    source_dir: str = ""
    cases: list[FlsCase] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def event_speed(self, key: str) -> float | None:
        return {"cutin": self.cut_in, "rated": self.rated, "startuplim": self.startup_limit,
                "hwrtactivate": self.hwrt_activate, "cutout": self.cut_out,
                "hwrtcutout": self.hwrt_cut_out}.get(key)


def _num(text):
    try:
        return float(str(text).strip().strip("'\""))
    except ValueError:
        return None


def read_fls_inp(path: str) -> FlsSetup:
    """``flssetup`` input file: header keys, the ``fields`` line and one ``Case`` line per DLC
    folder (lines with the same Name form one case, e.g. DLC24a + DLC24b)."""
    with open(path, encoding="latin1") as fh:
        lines = fh.read().splitlines()
    # the processed block runs from the LINE starting with <START> to the one starting with
    # <END> (the header comments mention both markers too)
    start = next((i for i, s in enumerate(lines) if s.lstrip().startswith("<START>")), -1)
    end = next((i for i, s in enumerate(lines) if i > start and s.lstrip().startswith("<END>")), len(lines))
    keys, case_lines = {}, []
    for raw in lines[start + 1:end]:
        line = raw.split("%", 1)[0].rstrip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key.lower().startswith("case") and key.lower() != "case_label" and key.lower() != "case_directory":
            case_lines.append(value)
        else:
            keys[key.split("[")[0].strip().lower()] = value
    fields = [f.lower() for f in keys.get("fields", "").split()]
    if not fields or fields[:2] != ["name", "id"]:
        raise ValueError(f"{path}: no 'fields : Name Id ...' line")
    setup = FlsSetup(path=path, turbine=keys.get("turbine", "").strip("'\" "),
                     cut_in=_num(keys.get("cut_in")), rated=_num(keys.get("rated")),
                     cut_out=_num(keys.get("cut_out")),
                     availability=_num(keys.get("availability")) or 100.0,
                     startup_limit=_num(keys.get("startup_limit")),
                     hwrt_activate=_num(keys.get("hwrt_activate")),
                     hwrt_cut_out=_num(keys.get("hwrt_cut_out")),
                     source_dir=keys.get("source_directory", "").strip("'\" "))
    by_name: dict[str, FlsCase] = {}
    for value in case_lines:
        tok = value.split()
        required = len([f for f in fields if f != "selectionmethod"])   # trailing text field, often blank
        if len(tok) < required:
            setup.warnings.append(f"Case line with fewer values than fields ignored: {value}")
            continue
        row = dict(zip(fields, tok))
        name, ident = row["name"], row["id"].rstrip("\\/")
        if name in by_name:
            by_name[name].ids.append(ident)
            continue
        f = {k: _num(v) or 0.0 for k, v in row.items() if k not in ("name", "id", "selectionmethod")}
        by_name[name] = FlsCase(name=name, ids=[ident], life=f.get("l", 0.0), A=f.get("a", 0.0),
                                k=f.get("k", 0.0), ituci=int(f.get("ituci", 0)), forced=f.get("forced", 0.0),
                                events={e: f.get(e, 0.0) for e in _EVENT_FIELDS if f.get(e, 0.0)})
    setup.cases = list(by_name.values())
    for key in ("wind_wave_joint_distrib", "wind_distrib_method", "waveexchangepath", "special"):
        if keys.get(key, "").strip():
            setup.warnings.append(f"'{key}' is set ({keys[key].strip()}): wind-wave / PCC / special weighting "
                                  "is not reproduced - compare with the official weights (.lst).")
    return setup


def find_fls_setups(sim_dir: str) -> list[str]:
    """FLS input files of a simulation: ``<sim>\\Post\\00_Input\\FLS*.inp``."""
    return sorted(glob.glob(os.path.join(sim_dir, "Post", "00_Input", "FLS*.inp")))

