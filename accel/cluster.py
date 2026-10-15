#!/usr/bin/env python3
"""cluster.py [--config accel.json] [--max-insns N] [--top K] : group functions by asm shape so one match unlocks several.

Normalizes each function's asm to an opcode/operand-shape sequence (registers, immediates,
labels and symbols abstracted), then clusters with exact-shape buckets plus a
difflib similarity pass (>= 0.85). Reports families with an already-matched member
first (that member's C is a ready template), then all-unmatched families.
Writes <work_dir>/clusters.json.
"""
import difflib, glob, json, os, re, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from funcutil import REPO, CFG, path, work
maxn = int(sys.argv[sys.argv.index('--max-insns') + 1]) if '--max-insns' in sys.argv else 80

def norm(path):
    seq, rodata = [], False
    for l in open(path):
        l = l.split('@')[0].strip()
        if not l: continue
        if l.startswith('.section') or l.startswith('.incrom'): rodata = True
        if l.startswith('.') or l.endswith(':'): continue
        op, _, args = l.partition('\t') if '\t' in l else l.partition(' ')
        args = re.sub(r'\br([0-9]|1[0-2])\b|\b(sp|lr|pc|r8|r9|r10)\b', 'R', args)
        if op == 'ldr' and re.search(r'=-?(0x[0-9a-fA-F]+|\d+)\s*$', args):
            seq.append('const'); continue
        args = re.sub(r'#?-?(0x[0-9a-fA-F]+|\d+)\b', '#', args)
        args = re.sub(r'=\S+', '=S', args)
        args = re.sub(r'\.L\w+', 'L', args)
        args = re.sub(r'\b(?!R\b)[A-Za-z_]\w*\b', 'S', args)
        seq.append(op + ' ' + args.replace(' ', ''))
    out = []
    for x in seq:   # mov R,# ; lsl R,# materialization == literal-pool constant
        if x == 'lsl R,#' and out and out[-1] == 'mov R,#':
            out[-1] = 'const'; continue
        if x == 'lsl R,R,#' and out and out[-1] == 'mov R,#':
            out[-1] = 'const'; continue
        out.append(x)
    return out, rodata

inc = set()
for c in glob.glob(path('src_dir') + '/**/*.c', recursive=True):
    for m in re.finditer(r'INCLUDE_ASM(?:_SECTION)?\("([^"]+)"', open(c).read()):
        inc.add(os.path.join(REPO, m.group(1)))
funcs = {}
for a in glob.glob(path('asm_dir') + '/**/*.s', recursive=True):
    m = re.search(CFG['func_start'] + r' (\w+)', open(a).read())
    if not m: continue
    seq, ro = norm(a)
    if 3 <= len(seq) <= maxn:
        funcs[m.group(1)] = {'asm': os.path.relpath(a, REPO), 'n': len(seq), 'matched': a not in inc, 'rodata': ro, 'seq': seq}

names = sorted(funcs, key=lambda f: funcs[f]['n'])
parent = {f: f for f in names}
def find(x):
    while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
    return x
buckets = {}
for f in names: buckets.setdefault(tuple(funcs[f]['seq']), []).append(f)
for b in buckets.values():
    for f in b[1:]: parent[find(f)] = find(b[0])
reps = [b[0] for b in buckets.values()]
reps.sort(key=lambda f: funcs[f]['n'])
for i, f in enumerate(reps):
    sf = funcs[f]['seq']
    for g in reps[i + 1:]:
        sg = funcs[g]['seq']
        if len(sg) > len(sf) * 1.2 + 2: break
        sm = difflib.SequenceMatcher(None, sf, sg, autojunk=False)
        if sm.real_quick_ratio() >= 0.85 and sm.quick_ratio() >= 0.85 and sm.ratio() >= 0.85:
            parent[find(g)] = find(f)
fam = {}
for f in names: fam.setdefault(find(f), []).append(f)
fams = [sorted(v, key=lambda f: (not funcs[f]['matched'], f)) for v in fam.values() if len(v) > 1 and any(not funcs[f]['matched'] for f in v)]
fams.sort(key=lambda v: (not any(funcs[f]['matched'] for f in v), -sum(not funcs[f]['matched'] for f in v), funcs[v[0]]['n']))
out = [{'members': [{'fn': f, 'asm': funcs[f]['asm'], 'n': funcs[f]['n'], 'matched': funcs[f]['matched'], 'rodata': funcs[f]['rodata']} for f in v]} for v in fams]
json.dump(out, open(work('clusters.json'), 'w'), indent=1)
for v in out[:int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 40]:
    print(' | '.join(('*' if m['matched'] else '') + m['fn'] + '(%d)' % m['n'] for m in v['members']))
print('%d families, %d unmatched functions in families' % (len(out), sum(sum(not m['matched'] for m in v['members']) for v in out)))
