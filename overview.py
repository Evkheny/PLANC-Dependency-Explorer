"""Tuning overview of a functionality (Jira OVTASK 'Overview' table, gates omitted), built from:
  - the tuning knowledge base shipped with the tool (tuning_kb.json: scope, KPIs, DLC relevance and reasons, risks),
  - the current model (signal links with WHERE each signal is used inside the consumer),
  - CoPaD (type-dependent parameters, values A / B of the compare selection),
  - the DLCs of the selected simulation path(s) (dlcsetup): which relevant DLCs exist in the project and their set-up.
No other input. Text marked [P] in the knowledge base is proposed and must be reviewed."""
import json, os, re, sys

HERE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
_KB = None


def kb():
    global _KB
    if _KB is None:
        try:
            _KB = json.load(open(os.path.join(HERE, 'tuning_kb.json'), encoding='utf8'))
        except OSError:
            _KB = {'tasks': []}
    return _KB


def tasks_for(comp):
    return [t for t in kb()['tasks'] if t.get('comp') == comp]


def all_tasks():
    return kb()['tasks']


# ------------------------------------------------------------------------------------------------ tuning couplings
def couplings(comp):
    """Tuning couplings of a Simulink component (all its tasks), grouped by peer.
    Returns (incoming, outgoing): [(peer comp or task key, label, peer comp or None, [(from key, to key, reason)])].
    A -> B = changing the tunable parameters of A requires re-tuning or re-checking B (physical reason given)."""
    T = {t['key']: t for t in all_tasks()}
    mine = {t['key'] for t in tasks_for(comp)}
    inc, out = {}, {}
    for e in kb().get('couplings', []):
        a, b = e['from'], e['to']
        for side, me, peer in ((out, a, b), (inc, b, a)):
            if me in mine and peer not in mine:
                pt = T.get(peer, {})
                pid = pt.get('comp') or peer
                label = pt.get('comp') or (pt.get('name', peer) + (f' ({peer})' if peer in T else ''))
                side.setdefault(pid, [pid, label, pt.get('comp'), []])[3].append((a, b, e['reason']))
    return [tuple(v) for v in inc.values()], [tuple(v) for v in out.values()]


# ------------------------------------------------------------------------------------------------ DLC relevance
_CODE = re.compile(r'(\d{1,2})\.(\d+|x)([a-z]{0,3})(?:/([a-z]))?')


def _codes(chunk):
    """DLC codes in a text chunk ('DLC 1.2a', 'DLC 2.4a/b', 'DLC 1.2 / 1.2a / 1.2c, 1.3', 'DLC 3.x')."""
    if 'DLC' not in chunk:
        return []
    out = []
    tail = chunk[chunk.index('DLC'):]
    for m in _CODE.finditer(tail):
        major, minor, suf, alt = m.groups()
        out.append(f'{major}.{minor}{suf}')
        if alt:
            out.append(f'{major}.{minor}{alt}')
    return list(dict.fromkeys(out))


def _split_top(text):
    """Split at ';' outside parentheses."""
    out, depth, cur = [], 0, ''
    for ch in text:
        depth += ch == '('
        depth -= ch == ')'
        if ch == ';' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    return [c.strip() for c in out + [cur] if c.strip()]


def dlc_items(task):
    """[(level, [codes], reason)] parsed from the knowledge-base 'Relevant DLCs' paragraphs."""
    items = []
    for para in task.get('dlcs', []):
        m = re.match(r'\*\*(High|Medium|Lower):\*\*\s*(.*)', para)
        if not m:
            continue
        level, body = m.groups()
        for chunk in _split_top(body):
            c = _codes(chunk)
            if c or chunk.strip():
                items.append((level, c, chunk.strip().rstrip('.')))
    return items


def pretty_to_key(pretty):
    """'DLC 1.2a' -> '1.2a'; 'DLC I.22p' -> 'I.22p'."""
    return pretty.replace('DLC', '').strip()


def match_dlcs(codes, sim):
    """Folder names of the simulation whose DLC code matches one of the codes ('3.x' = any 3.*)."""
    if sim is None:
        return []
    keys = {name: pretty_to_key(d.pretty) for name, d in sim.dlcs.items() if not d.tool}   # no post-processing cases
    out = []
    for c in codes:
        if c.endswith('.x'):
            hit = [n for n, k in keys.items() if k.startswith(c[:-1])]
        else:
            hit = [n for n, k in keys.items() if k == c]
            if not hit and not c[-1].isalpha():                 # '1.7' -> 1.7p / 1.7q when there is no plain 1.7
                hit = [n for n, k in keys.items() if re.fullmatch(re.escape(c) + r'[a-z]+', k)]
        out += [n for n in hit if n not in out]
    return out


def dlc_rows(task, sims):
    """Rows for the overview: (level, codes, reason, {sim label: [(folder, description)]}). The first simulation is the
    project simulation; codes not found there are flagged."""
    rows = []
    for level, codes, reason in dlc_items(task):
        found = {}
        for s in sims:
            names = match_dlcs(codes, s)
            found[s.label] = [(n, s.dlcs[n].description) for n in names]
        rows.append((level, codes, reason, found))
    return rows


# ------------------------------------------------------------------------------------------------ model links
def links(M, comp):
    """(incoming, outgoing): lists of (peer, signal, role, uses) from the model, main uses first."""
    order = {'main': 0, 'scheduling / auxiliary': 1, 'event data': 2, 'not traced': 3}
    inc, out = [], []
    for e in M['edges']:
        if e['dst'] == comp:
            for s in e['signals']:
                inc.append((e['src'], s, e.get('role', {}).get(s, ''), e.get('use', {}).get(s, [])))
        if e['src'] == comp:
            for s in e['signals']:
                out.append((e['dst'], s, e.get('role', {}).get(s, ''), e.get('use', {}).get(s, [])))
    key = lambda x: (order.get(x[2], 9), x[0], x[1])
    return sorted(inc, key=key), sorted(out, key=key)


def type_params(M, comp, ty, a, b):
    """(typed count for type ty, [(param, value A, value B)] that differ)."""
    if comp not in M['components']:
        return 0, []
    P = M['parameters']
    pars = [p for p in M['components'][comp]['parameters'] if P.get(p, {}).get('type') == ty]
    diff = [(p, P[p]['values'].get(a, ''), P[p]['values'].get(b, '')) for p in pars
            if a and b and P[p]['values'].get(a) != P[p]['values'].get(b)]
    return len(pars), diff


# ------------------------------------------------------------------------------------------------ text export
def strip(t):
    return t.replace('**', '').replace('[P] ', '(proposed) ').replace('[P]', '(proposed)')


def jira_markup(task, M=None, sims=(), ty='WTGType', a='', b=''):
    """Jira wiki table of the overview (gates omitted), ready to paste in an OVTASK."""
    def cell(paras):
        return ' \\\\ '.join(('* ' + strip(p[2:])) if p.startswith('- ') else strip(p) for p in paras).replace('|', '/')
    rows = [('Name', [task['name']]), ('Main Scope', task['scope']), ('Tuning KPI', task['kpi'])]
    dl = task['dlcs']
    if sims:
        extra = []
        for level, codes, reason, found in dlc_rows(task, sims):
            if not codes:
                continue
            f = found.get(sims[0].label, [])
            extra.append(f"- {level}: {reason} -> {sims[0].label}: " + (', '.join(n for n, _ in f) if f else 'not simulated'))
        dl = dl + ['Project load cases (' + sims[0].label + '):'] + extra
    rows.append(('Relevant DLCs', dl))
    rows += [('Highly affected functionalities', task['affects']), ('Highly affected by', task['affected_by']),
             ('Risk of not tuning', task['risk'])]
    if M is not None and task.get('comp') in M['components']:
        n, diff = type_params(M, task['comp'], ty, a, b)
        txt = [f'{n} parameters depend on {ty}' + (f'; {len(diff)} differ between {a} and {b}: ' +
                                                   ', '.join(f'{p} {x}->{y}' for p, x, y in diff[:12]) if diff else '')]
        rows.append(('Type-dependent parameters', txt))
    return '\n'.join(f'||{k}|{cell(v)}|' for k, v in rows)
