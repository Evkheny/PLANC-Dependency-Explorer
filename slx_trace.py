"""Trace how an input TDI (root Inport) is used inside a PLANC component .slx (read only).
Follows lines and branches, subsystem input / output ports, Goto/From tags and library blocks downstream. Prints the
subsystems the signal enters, the library blocks and functional blocks it passes, and the root outports it reaches,
so one can see whether a signal drives the main algorithm or only an auxiliary path.
Usage: python slx_trace.py <component name | .slx path> <Inport name>"""
import glob, os, re, sys, zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict, deque

CTRL = r'C:\GitLab_Repos\planc\Controller'
SKIP = {'Inport', 'Outport', 'Goto', 'From', 'BusCreator', 'Mux', 'Demux', 'SignalConversion', 'Terminator', 'Ground'}


def P(e, name):
    x = e.find(f"P[@Name='{name}']")
    return x.text if x is not None else None


def _dsts(e):
    out = [P(e, 'Dst')] if P(e, 'Dst') else []
    for br in e.findall('Branch'):
        out += _dsts(br)
    return out


class Slx:
    def __init__(self, path):
        z = zipfile.ZipFile(path)
        self.blocks, self.out, self.child, self.par = {}, defaultdict(list), {}, {}
        self.froms = defaultdict(list)
        for n in z.namelist():
            m = re.match(r'simulink/systems/(system_\w+)\.xml$', n)
            if not m:
                continue
            sysname, root = m.group(1), ET.fromstring(z.read(n))
            for b in root.findall('Block'):
                sid = b.get('SID')
                self.blocks[sid] = dict(sys=sysname, type=b.get('BlockType'), name=b.get('Name'),
                                        port=P(b, 'Port') or '1', tag=P(b, 'GotoTag'), src=P(b, 'SourceBlock'))
                s = b.find('System')
                if s is not None and s.get('Ref'):
                    self.child[sid] = s.get('Ref'); self.par[s.get('Ref')] = sid
                if b.get('BlockType') == 'From':
                    self.froms[P(b, 'GotoTag')].append(sid)
            for ln in root.findall('Line'):
                src = P(ln, 'Src')
                if src:
                    sid, port = src.split('#')
                    for d in _dsts(ln):
                        dsid, dport = d.split('#')
                        self.out[(sid, re.sub(r'\D', '', port) or '1')].append((dsid, re.sub(r'\D', '', dport) or '1'))

    def path(self, sysname):
        names = []
        while sysname in self.par:
            sid = self.par[sysname]
            names.append(self.blocks[sid]['name'])
            sysname = self.blocks[sid]['sys']
        return '/'.join(reversed(names)) or '(root)'

    def outs(self, sid):
        return [d for (s, p), ds in self.out.items() if s == sid for d in ds]

    def first_users(self, inport, stop=('Reference', 'S-Function', 'Stateflow', 'MATLABFcn', 'Lookup_n-D', 'DiscreteFilter',
                                       'DiscreteTransferFcn', 'ModelReference')):
        """First functional blocks reached (library / S-function / lookup / filter / chart), with the input port used.
        Simple math blocks are passed through and listed on the way."""
        start = [s for s, b in self.blocks.items() if b['sys'] == 'system_root' and b['type'] == 'Inport' and b['name'] == inport]
        q, seen, res = deque((s, None) for s in start), set(start), []
        while q:
            sid, inp = q.popleft()
            b = self.blocks[sid]
            if b['type'] in stop:
                res.append((self.path(b['sys']), b['name'], inp, b['src'] or b['type'])); continue
            if b['type'] == 'Outport':
                if b['sys'] == 'system_root':
                    res.append(('(root)', 'OUTPUT ' + b['name'], inp, '')); continue
                for d, dp in self.out.get((self.par[b['sys']], b['port']), []):
                    self._push2(d, dp, q, seen)
                continue
            if b['type'] == 'Goto':
                for f in self.froms.get(b['tag'], []):
                    if f not in seen:
                        seen.add(f); q.append((f, None))
                continue
            if b['type'] not in SKIP:
                res.append((self.path(b['sys']), b['name'], inp, b['type']))
            for d, dp in self.outs(sid):
                self._push2(d, dp, q, seen)
        return res

    def _push2(self, d, dp, q, seen):
        db = self.blocks.get(d)
        if db is None:
            return
        if db['type'] == 'SubSystem' and d in self.child:
            for s, x in self.blocks.items():
                if x['sys'] == self.child[d] and x['type'] == 'Inport' and x['port'] == dp and s not in seen:
                    seen.add(s); q.append((s, None))
        elif d not in seen or db['type'] in ('Reference', 'S-Function'):
            seen.add(d); q.append((d, dp))

    def trace(self, inport):
        start = [s for s, b in self.blocks.items() if b['sys'] == 'system_root' and b['type'] == 'Inport' and b['name'] == inport]
        q, seen, hits = deque(start), set(start), []

        def push(x):
            if x not in seen:
                seen.add(x); q.append(x)
        while q:
            sid = q.popleft()
            b = self.blocks[sid]
            if b['type'] == 'Outport':
                if b['sys'] == 'system_root':
                    hits.append(('OUTPUT', '(root)', b['name']))
                else:
                    psid = self.par[b['sys']]
                    for d, dp in self.out.get((psid, b['port']), []):
                        self._enter(d, dp, push, hits)
                continue
            if b['type'] == 'Goto':
                for f in self.froms.get(b['tag'], []):
                    push(f)
                continue
            if b['type'] not in SKIP:
                hits.append((b['type'] if b['type'] != 'Reference' else 'LIB', self.path(b['sys']),
                             b['name'] + (f"  <- {b['src']}" if b['src'] else '')))
            for d, dp in self.outs(sid):
                self._enter(d, dp, push, hits)
        return hits

    def _enter(self, d, dp, push, hits):
        db = self.blocks.get(d)
        if db is None:
            return
        if db['type'] == 'SubSystem' and d in self.child:
            hits.append(('ENTERS', self.path(self.child[d]), ''))
            for s, x in self.blocks.items():
                if x['sys'] == self.child[d] and x['type'] == 'Inport' and x['port'] == dp:
                    push(s)
        else:
            push(d)


def find_slx(name):
    if name.lower().endswith('.slx'):
        return name
    c = [f for f in glob.glob(os.path.join(CTRL, 'Subareas', '**', name + '.slx'), recursive=True)
         if os.sep + 'Test' + os.sep not in f]
    return c[0] if c else None


def summary(comp, inport):
    s = Slx(find_slx(comp))
    hits = s.trace(inport)
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h); out.append(h)
    return out


if __name__ == '__main__' and '--first' in sys.argv:
    s = Slx(find_slx(sys.argv[1]))
    for p, n, port, t in s.first_users(sys.argv[2]):
        print(f'{p} :: {n}  [in {port}] {t}')
    sys.exit(0)
if __name__ == '__main__':
    for kind, p, n in summary(sys.argv[1], sys.argv[2]):
        if kind in ('ENTERS', 'OUTPUT', 'LIB', 'SubSystem', 'MATLABFcn', 'Stateflow', 'S-Function', 'Lookup_n-D',
                    'DiscreteFilter', 'DiscreteTransferFcn', 'Switch', 'MinMax', 'Product', 'Sum', 'RelationalOperator'):
            print(f'{kind:9} {p} :: {n}')
