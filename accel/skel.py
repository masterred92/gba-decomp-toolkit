#!/usr/bin/env python3
"""skel.py [--config accel.json] FUNC [-o out.c] : m2c-based C skeleton for FUNC, rewritten into decomp-ready C.
- M2C_FIELD(p, T*, off) -> *(T *)((u8 *)p + off)
- signed power-of-two division idiom (if (x<0) x += 2^k-1; ... x >> k) -> x / 2^k
- return type from the pop {r0}/{r1} tell
- externs for called functions / globals ('?' -> int)
"""
import re, subprocess, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from funcutil import find_asm, tell, CFG, work

M2C = os.path.expanduser(CFG['m2c'])

def m2c(fn):
    a = find_asm(fn)
    lines = ['.text', 'glabel ' + fn]
    skip = r'\s*\.(include|section|incrom)|.*(%s|func_end)' % CFG['func_start']
    for l in open(a):
        if re.match(skip, l): continue
        lines.append(l.rstrip('\n'))
    open(work('skel_in.s'), 'w').write('\n'.join(lines) + '\n')
    r = subprocess.run(['python3', M2C] + CFG['m2c_args'] + [work('skel_in.s')],
                       capture_output=True, text=True, timeout=60)
    return r.stdout + (('\n/* m2c stderr: ' + r.stderr.strip()[:300] + ' */') if r.returncode else '')

def field(m):
    return '*(%s)((u8 *)%s + %s)' % (m.group(2).strip(), m.group(1).strip(), m.group(3).strip())

def clean(fn, c):
    for _ in range(5):
        c = re.sub(r'M2C_FIELD\(((?:[^,()]|\([^()]*\))+),\s*([^,]+?),\s*(0x[0-9A-Fa-f]+|\d+)\)', field, c)
    # signed division idiom:  if (v < 0) { v += K; }  ... (v >> k)
    for m in list(re.finditer(r'\n(\s*)if \((\w+) < 0\) \{\n\s*\2 \+= (\d+);\n\s*\}', c)):
        v, k = m.group(2), int(m.group(3))
        if (k + 1) & k == 0:
            sh = (k + 1).bit_length() - 1
            c2 = c.replace(m.group(0), '')
            c2 = re.sub(r'\(%s >> %d\)' % (v, sh), '(%s / %d)' % (v, k + 1), c2)
            if c2 != c.replace(m.group(0), ''): c = c2
    c = re.sub(r'^\? ', 'int ', c, flags=re.M)
    c = re.sub(r'\bM2C_UNK\b', 'int', c)
    c = re.sub(r'\bM2C_ERROR\(([^)]*)\)', r'/* M2C_ERROR \1 */ 0', c)
    t = tell(fn)
    if t:
        hdr = '/* return-type tell: %s (pop {%s}) */\n' % (t, 'r1' if t == 'int' else 'r0')
        if t == 'void':
            c = re.sub(r'^[\w\s\*]+?\b%s\(' % fn, 'void %s(' % fn, c, count=1, flags=re.M)
        elif re.search(r'^void\s+%s\(' % fn, c, re.M):
            c = re.sub(r'^void\s+%s\(' % fn, 'int %s(' % fn, c, count=1, flags=re.M)
        c = hdr + c
    return c

if __name__ == '__main__':
    fn = sys.argv[1]
    out = clean(fn, m2c(fn))
    if '-o' in sys.argv: open(sys.argv[sys.argv.index('-o') + 1], 'w').write(out)
    print(out)
