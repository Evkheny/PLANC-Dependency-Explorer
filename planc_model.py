"""PLANC model scanner (read only). Builds the functional dependency model of the PLANC controller from three sources:
  1. the PLANC repo 'Controller' folder (Subareas/**/<Comp>/<Comp>.slx + <Comp>.xml, Shared/*.xml)
  2. the Controller Description PDF of the same release (sections from the PDF bookmarks, text for parameter lookup)
  3. the CoPaD parameter-value export of the same release (parVal<version>.csv, ';'-separated): parameter definition,
     STC1 mapping, type selection, value per type value, min/max and owner. Other columns are ignored.
Output: a JSON-serialisable dict (meta, components, signals, parameters, typeselections, edges, cd, outside_model_params).
Nothing in the repo is modified.
Usage: python planc_model.py <Controller folder> --cd <ControllerDescription.pdf> --csv <parVal.csv> [--out model.json]"""
import argparse, collections, csv, datetime, glob, json, os, re, zipfile
import xml.etree.ElementTree as ET

TOK = re.compile(r'[A-Za-z][A-Za-z0-9_]{2,}')
CSV_COLS = ('parameterDefinitionName', 'parameterMappingName', 'typeName', 'typeValue', 'value', 'minValue', 'maxValue',
            'matriceValue', 'owner')
# helpers that are part of a test harness (not an emulation of a legacy STC1 function)
HARNESS = {'AccumulatorPressureHelper', 'HydPitchValvesController', 'PitchHardwareModel', 'Grid_Helper', 'Converter_Helper',
           'SpeedSource_Helper', 'PitchTrajectory_Helper', 'PowerTrajectory_Helper', 'NacelleAccelerationSensor_Helper',
           'GridFormingAndIslandMode_Helper', 'PitchControlStates_Helper'}


def _say(progress, msg):
    if progress:
        progress(msg)


# ---------------------------------------------------------------------------------------------------------- Simulink repo
def _attrs(path, tag):
    out = {}
    if not os.path.exists(path):
        return out
    for e in ET.parse(path).getroot().iter(tag):
        d = dict(e.attrib)
        maps = [m.get('name') for m in e.iter('Mapping') if m.get('interface') == 'STC1' and m.get('name')]
        if maps:
            d['stc1'] = maps[0].split('::')[0]
        if tag == 'MultiParameter':
            d['layers'] = [l.get('name') for l in e.iter('Layer')]
        if tag == 'TypeSelection':
            d['values'] = [v.get('name') for v in e.iter('TypeValue')]
        if 'name' in d:
            out[d['name']] = d
    return out


def scan_shared(ctrl):
    sh = os.path.join(ctrl, 'Shared')
    return (_attrs(os.path.join(sh, 'Parameters.xml'), 'Parameter'), _attrs(os.path.join(sh, 'MultiParameters.xml'), 'MultiParameter'),
            _attrs(os.path.join(sh, 'Signals.xml'), 'Signal'), _attrs(os.path.join(sh, 'TypeSelections.xml'), 'TypeSelection'))


def find_components(ctrl):
    """A component is Subareas/.../<Name>/<Name>.slx with a sibling <Name>.xml whose root is <SubComponent>."""
    comps = []
    base = os.path.join(ctrl, 'Subareas')
    for slx in glob.glob(os.path.join(base, '**', '*.slx'), recursive=True):
        d, fn = os.path.split(slx)
        name = fn[:-4]
        if os.path.basename(d) != name or (os.sep + 'Test' + os.sep) in slx:
            continue
        xml = os.path.join(d, name + '.xml')
        if not os.path.exists(xml):
            continue
        r = ET.parse(xml).getroot()
        if r.tag != 'SubComponent':
            continue
        info = r.find('Info')
        rel = os.path.relpath(slx, base).split(os.sep)
        desc = (info.findtext('Description') or '').strip() if info is not None else ''
        comps.append(dict(name=name, short=info.get('shortName', '') if info is not None else '', subarea=rel[0],
                          group=rel[1] if len(rel) > 3 else '', helper='Helper' in rel, path=os.path.relpath(slx, ctrl),
                          description='' if desc == '...' else desc))
    return comps


def scan_slx(path):
    """Root Inport/Outport names (= TDI signal names) and every identifier used inside the model (systems + stateflow)."""
    z = zipfile.ZipFile(path)
    ins, outs, txt = [], [], []
    for n in z.namelist():
        if not n.endswith('.xml'):
            continue
        data = z.read(n)
        if n == 'simulink/systems/system_root.xml':
            for b in ET.fromstring(data).iter('Block'):
                if b.get('BlockType') == 'Inport':
                    ins.append(b.get('Name'))
                elif b.get('BlockType') == 'Outport':
                    outs.append(b.get('Name'))
        if n.startswith('simulink/systems/') or n.startswith('simulink/stateflow/'):
            txt.append(data.decode('utf8', 'replace'))
    return ins, outs, set(TOK.findall(' '.join(txt)))


def scan_libraries(ctrl, comp_paths):
    """Every other .slx under Subareas (libraries, helpers' libraries) -> {stem: identifier set}."""
    libs = {}
    for slx in glob.glob(os.path.join(ctrl, 'Subareas', '**', '*.slx'), recursive=True):
        rel = os.path.relpath(slx, ctrl)
        if rel in comp_paths or (os.sep + 'Test' + os.sep) in slx:
            continue
        try:
            libs[os.path.basename(slx)[:-4]] = scan_slx(slx)[2]
        except zipfile.BadZipFile:
            pass
    return libs


def expand_with_libraries(toks, libs, own_dir_libs):
    """Add identifiers of the libraries referenced by name (transitively) and of the libraries in the component folder."""
    seen, todo = set(), [l for l in libs if l in toks] + own_dir_libs
    out = set(toks)
    while todo:
        l = todo.pop()
        if l in seen or l not in libs:
            continue
        seen.add(l)
        out |= libs[l]
        todo += [k for k in libs if k in libs[l] and k not in seen]
    return out, sorted(seen)


def match_params(toks, pnames):
    """Exact names plus library templates with an 'X' placeholder segment (e.g. ACS_LoadEstX_Coef2 -> ACS_LoadEst1_Coef2)."""
    hit = toks & pnames
    for t in toks:
        if 'X' in t and '_' in t and t not in pnames:
            parts = t.split('_')
            if any(p.endswith('X') and len(p) > 1 for p in parts):
                rx = re.compile('^' + '_'.join(re.escape(p[:-1]) + r'\d+' if p.endswith('X') and len(p) > 1 else re.escape(p)
                                               for p in parts) + '$')
                hit |= {p for p in pnames if rx.match(p)}
    return hit


# ---------------------------------------------------------------------------------------------------------- CoPaD export
def load_copad(path):
    """CoPaD parameter-value export (csv, ';'). Returns {parameter: {mapping, type, owner, min, max, values {typeValue: v}}};
    an untyped parameter keeps its single value under ''. Matrix values are shown by their CoPaD hash (first 8 chars)."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding='utf-8-sig', errors='replace', newline='') as f:
        rd = csv.DictReader(f, delimiter=';')
        miss = [c for c in ('parameterDefinitionName', 'typeName', 'typeValue', 'value') if c not in (rd.fieldnames or [])]
        if miss:
            raise ValueError('Not a CoPaD parameter-value export: missing column(s) ' + ', '.join(miss))
        for r in rd:
            p = (r.get('parameterDefinitionName') or '').strip()
            if not p:
                continue
            e = out.setdefault(p, dict(mapping=r.get('parameterMappingName') or '', type=r.get('typeName') or '',
                                       owner=r.get('owner') or '', min=r.get('minValue') or '', max=r.get('maxValue') or '', values={}))
            v = (r.get('value') or '').strip()
            if not v and (r.get('matriceValue') or '').strip():
                v = 'matrix#' + r['matriceValue'].strip()[:8]
            e['values'][(r.get('typeValue') or '').strip()] = v
    return out


# ---------------------------------------------------------------------------------------------------------- Controller Description
def load_cd(path, progress=None):
    """Controller Description PDF. Sections = level-2 bookmarks ('9.4 Blade Load Limiter'); for each: title, chapter,
    first page, introduction text, |Type| selections mentioned and the identifiers used (for parameter lookup)."""
    if not path or not os.path.exists(path):
        return {}
    import pymupdf
    doc = pymupdf.open(path)
    _say(progress, f'Reading the Controller Description ({doc.page_count} pages)...')
    pages = [p.get_text() for p in doc]
    toc = doc.get_toc()
    chap, secs, starts = '', {}, []
    for lvl, title, page in toc:
        m = re.match(r'^(\d{1,2}(?:\.\d{1,2})?)\s+(.+)$', title.strip())
        if not m:
            continue
        if lvl == 1:
            chap = m.group(2)
        elif lvl == 2 and m.group(1) not in secs:
            secs[m.group(1)] = dict(num=m.group(1), title=m.group(2).strip(), chapter=chap, page=page)
            starts.append((page, m.group(1)))
    starts.sort()
    for i, (page, num) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(pages)
        text = '\n'.join(pages[page - 1:max(end, page)])
        flat = re.sub(r'\s+', ' ', text)
        n = re.escape(num)
        m = re.search(n + r'\.1 ?Introduction (.*?)(?:' + n + r'\.2 |$)', flat)
        intro = m.group(1) if m else ''
        intro = re.sub(r'(SG[ \S]{0,40}Controller Description[^.]*?\d{4}-\d{2}-\d{2}, Confidential)', ' ', intro)
        secs[num].update(intro=intro.strip()[:2000], types=sorted(set(re.findall(r'\|\s*([A-Za-z][A-Za-z0-9]{3,11})\s*\|', flat))),
                         tokens=set(TOK.findall(text)))
    return secs


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def words(s):
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s or '')
    return {w for w in re.findall(r'[a-z0-9]+', s.lower()) if w not in ('and', 'the', 'of', 'helper', 'for')}


def cd_section_for(name, short, cds):
    """Section whose title matches the component name: exact (normalised), else the best word overlap (>= 0.6)."""
    n = norm(name.replace('_Helper', ''))
    for k, v in cds.items():
        if norm(v['title']) == n or (short and norm(v['title']) == norm(short)):
            return k
    w = words(name.replace('_Helper', ''))
    best, score = None, 0.0
    for k, v in cds.items():
        t = words(v['title'])
        j = len(w & t) / max(1, len(w | t))
        if j > score:
            best, score = k, j
    return best if score >= 0.6 else None


# ---------------------------------------------------------------------------------------------------------- signal use
_AUX = re.compile(r'(notch|track|npfrq|frq|frequenc|3p|6p|9p|1p|gainsch|scheduling|scaling|activation|'
                  r'leadfactor|selector|status|compareto|azimuthshift|deadband)', re.I)
_EVENT = re.compile(r'(event|alarm|warning|reason)', re.I)


def classify_use(uses):
    """Heuristic role of a signal in its consumer, from the first blocks that use it: 'event data' (only alarm / event
    logging), 'scheduling / auxiliary' (gain scheduling, nP frequency of filters, activation, status) or 'main'."""
    if not uses:
        return 'not traced'
    last = [u.split('/')[-1].replace(' ', '').replace('-', '') for u in uses]     # innermost subsystem + block only
    if all(_EVENT.search(u) for u in last):
        return 'event data'
    if all(_AUX.search(u) or _EVENT.search(u) for u in last):
        return 'scheduling / auxiliary'
    return 'main'


def trace_signal_use(ctrl, comps, edges, progress=None):
    """For every link, where each signal is first used inside the consumer (subsystem path: first functional block):
    edge['use'] = {signal: [..]}, edge['role'] = {signal: classify_use(..)}. Read only."""
    from slx_trace import Slx
    by_dst = collections.defaultdict(list)
    for e in edges:
        by_dst[e['dst']].append(e)
    for i, (dst, es) in enumerate(sorted(by_dst.items())):
        if i % 20 == 0:
            _say(progress, f'Tracing signal use {i}/{len(by_dst)}...')
        try:
            s = Slx(os.path.join(ctrl, comps[dst]['path']))
        except Exception:
            s = None
        for e in es:
            e['use'], e['role'] = {}, {}
            for sig in e['signals']:
                uses = []
                try:
                    fu = s.first_users(sig) if s else []
                except Exception:
                    fu = []
                for p, n, port, t in fu:
                    if t == 'DataTypeConversion' or n.startswith(('Data Type Conversion', 'Convert to Simulink')):
                        continue
                    p2 = '/'.join(p.split('/')[2:]) or p
                    uses.append(f"{p2}: {n.strip()}".replace('\n', ' '))
                e['use'][sig] = uses[:4]
                e['role'][sig] = classify_use(uses[:4])


# ---------------------------------------------------------------------------------------------------------- build
def build(ctrl, cd=None, copad=None, progress=None):
    _say(progress, 'Reading Shared/*.xml...')
    par, mpar, sig, typ = scan_shared(ctrl)
    pv = load_copad(copad)
    cds = load_cd(cd, progress)
    multi_of = {m: m for m in mpar}
    multi_of.update({f'{m}_{l}': m for m in mpar for l in mpar[m]['layers'] if l != m})
    pnames = set(par) | set(multi_of)
    comps = find_components(ctrl)
    names = {c['name'] for c in comps}
    for c in comps:   # function | harness (test helper of a real component) | stc1 (helper emulating a legacy STC1 function)
        base = c['name'][:-7] if c['name'].endswith('_Helper') else None
        c['kind'] = 'function' if not c['helper'] else ('harness' if base in names or c['name'] in HARNESS else 'stc1')
    _say(progress, f'Scanning {len(comps)} Simulink components and their libraries...')
    libs = scan_libraries(ctrl, {c['path'] for c in comps})
    prod, cons = collections.defaultdict(list), collections.defaultdict(list)
    for i, c in enumerate(comps):
        if i % 20 == 0:
            _say(progress, f'Scanning components {i}/{len(comps)}...')
        ins, outs, toks = scan_slx(os.path.join(ctrl, c['path']))
        d = os.path.dirname(os.path.join(ctrl, c['path']))
        own = [os.path.basename(f)[:-4] for f in glob.glob(os.path.join(d, '*.slx')) if os.path.basename(f)[:-4] != c['name']]
        toks, c['libraries'] = expand_with_libraries(toks, libs, own)
        c['inputs'], c['outputs'] = sorted(set(ins)), sorted(set(outs))
        c['parameters'] = sorted(match_params(toks, pnames))
        c['typeselections'] = sorted({t[2:] for t in toks if t.startswith('T_') and t[2:] in typ})
        for s in c['inputs']:
            cons[s].append(c['name'])
        for s in c['outputs']:
            prod[s].append(c['name'])

    def pkey(p):
        return p if p in pv else multi_of.get(p) if multi_of.get(p) in pv else None
    for c in comps:
        td, own = collections.Counter(), collections.Counter()
        for p in c['parameters']:
            e = pv.get(pkey(p))
            if e:
                if e['type']:
                    td[e['type']] += 1
                own[e['owner'] or '?'] += 1
        c['type_param_count'] = dict(td)
        c['owners'] = dict(own)
        c['cd_section'] = cd_section_for(c['name'], c['short'], cds) if cds else None
    kind = {c['name']: c['kind'] for c in comps}
    E = collections.defaultdict(list)
    for s in set(prod) | set(cons):
        real = [a for a in prod.get(s, []) if kind[a] != 'harness'] or prod.get(s, [])   # a harness only counts if nothing else produces it
        for a in real:
            for b in cons.get(s, []):
                if a != b and kind[b] != 'harness':
                    E[(a, b)].append(s)
    edges = [dict(src=a, dst=b, signals=sorted(v)) for (a, b), v in sorted(E.items())]
    _say(progress, 'Tracing where each signal is used inside its consumers...')
    trace_signal_use(ctrl, {c['name']: c for c in comps}, edges, progress)
    sigs = {s: dict(sig.get(s, {}), producers=sorted(prod.get(s, [])), consumers=sorted(cons.get(s, [])))
            for s in sorted(set(prod) | set(cons))}
    used = sorted(set().union(*[set(c['parameters']) for c in comps])) if comps else []
    params = {}
    for p in used:
        d = dict(par.get(p) or mpar.get(multi_of.get(p), {}) or {})
        if p in multi_of:
            d['multi'] = multi_of[p]
        e = pv.get(pkey(p), {})
        d.update(type=e.get('type', ''), owner=e.get('owner', ''), mapping=e.get('mapping', '') or d.get('stc1', ''),
                 min=e.get('min', ''), max=e.get('max', ''), values=e.get('values', {}), in_copad=bool(e),
                 users=sorted(c['name'] for c in comps if p in c['parameters']))
        params[p] = d
    # type-dependent parameters of the export that the Simulink model does not use (legacy STC1 functions): CD section
    _say(progress, 'Locating type-dependent parameters outside the model in the Controller Description...')
    used_keys = {pkey(p) for p in used}
    outside = {}
    for p, e in pv.items():
        if not e['type'] or p in used_keys or p in mpar:
            continue
        hits = [k for k, v in cds.items() if p in v['tokens']]
        outside[p] = dict(e, cd_sections=hits)
    tvals = collections.defaultdict(set)
    for e in pv.values():
        if e['type']:
            tvals[e['type']] |= set(e['values'])
    cd_out = {k: {kk: vv for kk, vv in v.items() if kk != 'tokens'} for k, v in cds.items()}
    meta = dict(controller=os.path.abspath(ctrl), cd=os.path.abspath(cd) if cd else None, copad=os.path.abspath(copad) if copad else None,
                built=datetime.datetime.now().isoformat(timespec='seconds'), n_copad=len(pv),
                type_values={t: sorted(v) for t, v in tvals.items()})
    return dict(meta=meta, components={c['name']: c for c in comps}, signals=sigs, parameters=params, typeselections=typ,
                edges=edges, outside_model_params=outside, cd=cd_out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('controller', help='PLANC repo "Controller" folder')
    ap.add_argument('--cd', help='Controller Description .pdf of the same release')
    ap.add_argument('--csv', help='CoPaD parameter-value export (parVal<version>.csv) of the same release')
    ap.add_argument('--out', default='planc_model.json')
    a = ap.parse_args()
    m = build(a.controller, a.cd, a.csv, progress=print)
    json.dump(m, open(a.out, 'w', encoding='utf8'), default=str)
    c = m['components']
    print(f"components {len(c)}, signals {len(m['signals'])}, edges {len(m['edges'])}, parameters used {len(m['parameters'])} "
          f"({sum(1 for v in m['parameters'].values() if v['in_copad'])} found in CoPaD), CD sections {len(m['cd'])}, "
          f"components with CD section {sum(1 for v in c.values() if v['cd_section'])}, "
          f"type-dependent params outside the model {len(m['outside_model_params'])}")
