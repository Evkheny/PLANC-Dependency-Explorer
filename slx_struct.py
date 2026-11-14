"""Structure of a PLANC component .slx (read only): the subsystem tree, the blocks and lines of each system, and the
parameter names used inside each system. Used to scope the parameters of a tuning task to the subsystems it tunes
(e.g. the Feed-Forward of the Speed-Pitch Controller) and to draw the block diagram that shows where that part sits.
Read lazily from the PLANC 'Controller' folder when a function is shown (a component reads in well under a second)."""
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

_SKIP_DRAW = {'Terminator', 'Ground'}


def _p(e, name):
    x = e.find(f"P[@Name='{name}']")
    return x.text if x is not None else None


def _dsts(e):
    out = [_p(e, 'Dst')] if _p(e, 'Dst') else []
    for br in e.findall('Branch'):
        out += _dsts(br)
    return out


def _port(s):
    """'4858#in:3' -> ('4858', 3); 'enable' / 'trigger' ports -> 0."""
    sid, p = s.split('#', 1)
    m = re.search(r'(\d+)$', p)
    return sid, int(m.group(1)) if m else 0


class Component:
    def __init__(self, slx_path):
        z = zipfile.ZipFile(slx_path)
        self.sys = {}                         # sysname -> dict(blocks{sid: dict}, lines[(s, sp, d, dp, name)], tokens)
        self.child = {}                       # SubSystem block sid -> child sysname
        self.parent = {}                      # child sysname -> (parent sysname, block sid)
        for n in z.namelist():
            m = re.match(r'simulink/systems/(system_\w+)\.xml$', n)
            if not m:
                continue
            name, raw = m.group(1), z.read(n)
            root = ET.fromstring(raw)
            blocks = {}
            for b in root.findall('Block'):
                sid = b.get('SID')
                blocks[sid] = dict(type=b.get('BlockType'), name=b.get('Name'), port=int(_p(b, 'Port') or 1),
                                   tag=_p(b, 'GotoTag'))
                s = b.find('System')
                if s is not None and s.get('Ref'):
                    self.child[sid] = s.get('Ref')
                    self.parent[s.get('Ref')] = (name, sid)
            lines = []
            for ln in root.findall('Line'):
                src = _p(ln, 'Src')
                if not src:
                    continue
                for d in _dsts(ln):
                    (s, sp), (dd, dp) = _port(src), _port(d)
                    lines.append((s, sp, dd, dp, _p(ln, 'Name')))
            self.sys[name] = dict(blocks=blocks, lines=lines,
                                  tokens=set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', raw.decode('utf8', 'ignore'))))
        self.root = 'system_root' if 'system_root' in self.sys else next(iter(self.sys), None)
        self.by_path = {self.path(s): s for s in self.sys}

    # ---- tree
    def path(self, sysname):
        names = []
        while sysname in self.parent:
            par, sid = self.parent[sysname]
            names.append(self.sys[par]['blocks'][sid]['name'])
            sysname = par
        return '/'.join(reversed(names))

    def descendants(self, sysname):
        out, todo = [], [sysname]
        while todo:
            s = todo.pop()
            out.append(s)
            todo += [self.child[b] for b in self.sys[s]['blocks'] if b in self.child]
        return out

    def find(self, rel):
        """System by path; a path that does not start at the root may match the end of a full path."""
        if rel in self.by_path:
            return self.by_path[rel]
        hits = [s for p, s in self.by_path.items() if p.endswith('/' + rel) or p == rel]
        return hits[0] if len(hits) == 1 else None

    def params_in(self, systems, params):
        """Parameter names (from `params`) used inside the given systems and everything below them."""
        toks = set()
        for s in systems:
            for d in self.descendants(s):
                toks |= self.sys[d]['tokens']
        return toks & set(params)

    def common_parent(self, systems):
        """Deepest system that contains all the given systems (their parent when there is one system)."""
        chains = []
        for s in systems:
            ch = []
            while s in self.parent:
                s = self.parent[s][0]
                ch.append(s)
            chains.append(list(reversed(ch)) or [self.root])
        common = self.root
        for level in zip(*chains):
            if all(x == level[0] for x in level):
                common = level[0]
            else:
                break
        return common

    def main_system(self):
        """The first system with more than one subsystem (skips wrapper subsystems at the top)."""
        s = self.root
        while True:
            subs = [b for b in self.sys[s]['blocks'] if b in self.child]
            if len(subs) == 1:
                s = self.child[subs[0]]
            else:
                return s

    # ---- diagram of one system
    def port_name(self, sid_sys, sid, port, kind):
        """Name of the inner Inport / Outport number `port` of SubSystem block `sid`."""
        ch = self.child.get(sid)
        if not ch:
            return ''
        for b in self.sys[ch]['blocks'].values():
            if b['type'] == kind and b['port'] == port:
                return b['name']
        return ''

    def diagram(self, sysname):
        """Nodes and edges of one system for drawing.
        nodes: {sid: dict(type, name, kind 'in' | 'out' | 'sub' | 'blk')}; edges: [(src sid, dst sid, label)]."""
        S = self.sys[sysname]
        nodes = {}
        for sid, b in S['blocks'].items():
            if b['type'] in _SKIP_DRAW:
                continue
            kind = ('in' if b['type'] in ('Inport', 'InportShadow') else 'out' if b['type'] == 'Outport'
                    else 'sub' if sid in self.child else 'blk')
            nodes[sid] = dict(type=b['type'], name=b['name'], kind=kind)
        edges = []
        for s, sp, d, dp, nm in S['lines']:
            if s not in nodes or d not in nodes:
                continue
            label = nm or (self.port_name(sysname, d, dp, 'Inport') if d in self.child else '') or \
                (self.port_name(sysname, s, sp, 'Outport') if s in self.child else '')
            edges.append((s, d, label))
        gotos = defaultdict(list)                      # Goto -> From at the same level (same tag)
        for sid, b in S['blocks'].items():
            if b['type'] == 'Goto':
                gotos[b['tag']].append(sid)
        for sid, b in S['blocks'].items():
            if b['type'] == 'From':
                for g in gotos.get(b['tag'], []):
                    edges.append((g, sid, b['tag'] or ''))
        return nodes, edges


def _tokens(comp, systems):
    t = set()
    for x in systems:
        t |= comp.sys[x]['tokens']
    return t


def _subtree(comp, task):
    """Systems of a task: its subsystems and everything below them, minus its 'exclude' subtrees."""
    own = [x for x in (comp.find(p) for p in task.get('subsystems', [])) if x]
    keep = {d for x in own for d in comp.descendants(x)}
    for e in (comp.find(p) for p in task.get('exclude', [])):
        if e:
            keep -= set(comp.descendants(e))
    return own, keep


def scope(comp, task, tasks_of_comp, params):
    """(highlighted systems, parameter names) of a task inside its component, from the knowledge-base fields
    'subsystems' (paths), 'exclude' (paths), 'param_re' (regex) and 'rest' (= everything its sibling tasks do not
    cover). Returns (None, params) when the task has no scope (it covers the whole component)."""
    params = set(params)
    if task.get('rest'):
        sib = [t for t in tasks_of_comp if t is not task]
        taken, owns, minus = set(), [], set()
        for t in sib:
            own, keep = _subtree(comp, t)
            owns += own
            if t.get('param_re'):            # sibling shares the systems: remove only its parameters
                minus |= {p for p in _tokens(comp, keep) & params if re.match(t['param_re'], p)}
            else:
                taken |= keep
        rest = [x for x in comp.sys if x not in taken]
        pars = (_tokens(comp, rest) & params) - minus
        top = comp.common_parent(owns) if owns else comp.main_system()
        hl = [comp.child[b] for b in comp.sys[top]['blocks'] if b in comp.child and comp.child[b] not in taken]
        return hl, pars
    own, keep = _subtree(comp, task)
    if not own:
        return None, params
    pars = _tokens(comp, keep) & params
    if task.get('param_re'):
        pars = {p for p in pars if re.match(task['param_re'], p)}
    return own, pars
