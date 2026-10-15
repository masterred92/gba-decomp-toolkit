#!/usr/bin/env python3
"""auto.py [--config accel.json] [--budget S] FUNC [FUNC ...]
End-to-end first pass per function: m2c skeleton (skel.py) -> compile fixes ->
score -> greedy playbook (mutate.py). Prints a one-line verdict per function and
appends timing to <work_dir>/timing.log. MATCHes are left applied in the TU; everything
else is restored, with the best attempt in <work_dir>/mut_FUNC.c (or skel_FUNC.c).
"""
import os, re, sys, time, json
sys.path.insert(0, os.path.dirname(__file__))
from funcutil import TU, find_tu, work, log_timing
import skel, mutate

def fixups(tu_src, body, fn):
    out = []
    for line in body.splitlines():
        m = re.match(r'^\w[\w\s\*]*?\b(\w+)\(.*\);\s*/\* extern \*/', line) or re.match(r'^(?:extern\s+)?\w[\w\s\*]*?\b(\w+)(?:\[\])?;\s*/\* extern \*/', line)
        if m and re.search(r'\b%s\b' % m.group(1), tu_src):
            continue          # already declared in the TU
        out.append(line)
    b = '\n'.join(out)
    b = re.sub(r'\bvoid \*(\w+)', r'u8 *\1', b)            # byte-addressable pointers
    b = re.sub(r'/\* extern \*/', '', b)
    for k, v in (('s32', 'int'), ('u32', 'unsigned int'), ('s16', 'short'), ('u16', 'unsigned short'), ('s8', 'signed char'), ('u8', 'unsigned char')):
        b = re.sub(r'\b%s\b' % k, v, b)
    return b

def one(fn, budget):
    t0 = time.time()
    tu = find_tu(fn)
    if not tu: print(fn, 'no TU'); return
    T = TU(tu, fn)
    body = fixups(T.orig, skel.clean(fn, skel.m2c(fn)), fn)
    open(work('skel_%s.c' % fn), 'w').write(body)
    s, out = T.score(body)
    T.restore()
    verdict = 'skeleton %s' % ('compile-error' if s == 9999 else s)
    if s == 0:
        T.write(body); res = 0
    elif s < 9999:
        res = mutate.run(tu, fn, work('skel_%s.c' % fn), budget, verbose=False)
    else:
        res = s
        err = [l for l in out.splitlines() if re.search(r':\d+:', l) and 'warning' not in l][:3]
        verdict += ' ' + ' / '.join(e.strip()[-90:] for e in err)
    dt = time.time() - t0
    log_timing({'fn': fn, 'tool': 'auto', 'result': res, 'secs': round(dt)})
    print('%-24s %-34s %s  %s (%.0fs)' % (fn, tu, verdict, 'MATCH' if res == 0 else 'best %s' % res, dt), flush=True)

if __name__ == '__main__':
    a = sys.argv[1:]; budget = 90
    if '--budget' in a: i = a.index('--budget'); budget = int(a[i + 1]); del a[i:i + 2]
    for fn in a: one(fn, budget)
