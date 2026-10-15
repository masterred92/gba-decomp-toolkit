"""Shared helpers for the accel tools: config loading, locating a function's asm and
C file, splicing C into a translation unit, and scoring it against the original object.

Config: JSON file given with --config, $ACCEL_CONFIG, or ./accel.json (see
accel.example.json). Every path in it is relative to "repo" unless absolute.
"""
import json, os, re, shlex, subprocess, sys

DEFAULTS = {
    "repo": ".",                     # decomp project root
    "asm_dir": "asm",                # per-function .s files
    "src_dir": "src",                # C translation units
    "func_start": "thumb_func_start",# directive that names a function in its .s file
    "skip_src_globs": ["*/non_matching/*"],
    # build one object: {obj} {tu} {cc} {cflags} are substituted
    "build_cmd": "make -j1 {obj}",
    "cc": "",                        # e.g. tools/gcc296/cc1 or tools/agbcc/bin/agbcc
    "cflags": "",                    # e.g. -O2 -mthumb-interwork -fcall-used-r4
    "obj_path": "build/obj/{stem}.o",# object built from {stem}=src/x/y
    "ref_obj_path": "",              # original object for the same TU, e.g. /path/ref/{stem}.o
    "objdump": "arm-none-eabi-objdump",
    "env_script": "",                # optional shell file sourced before builds
    "build_timeout": 300,
    "m2c": "m2c.py",                 # path to m2c.py
    "m2c_args": ["-t", "gba", "--valid-syntax", "--globals=used"],
    "permuter": "",                  # decomp-permuter checkout
    "typedefs": ["s8", "u8", "s16", "u16", "s32", "u32", "s64", "u64", "vu8", "vu16", "vu32", "bool8", "bool16", "bool32"],
    "work_dir": ".accel",            # scratch output, timing.log, clusters.json
}

def _find_config(argv):
    if '--config' in argv:
        i = argv.index('--config'); p = argv[i + 1]; del argv[i:i + 2]; return p
    return os.environ.get('ACCEL_CONFIG') or ('accel.json' if os.path.exists('accel.json') else None)

CONFIG_PATH = _find_config(sys.argv)
CFG = dict(DEFAULTS)
if CONFIG_PATH:
    CFG.update(json.load(open(CONFIG_PATH)))
    if not os.path.isabs(CFG['repo']):
        CFG['repo'] = os.path.join(os.path.dirname(os.path.abspath(CONFIG_PATH)), CFG['repo'])
REPO = os.path.abspath(CFG['repo'])

def path(key):
    p = os.path.expanduser(CFG[key])
    return p if os.path.isabs(p) else os.path.join(REPO, p)

WORK = path('work_dir'); os.makedirs(WORK, exist_ok=True)
def work(name): return os.path.join(WORK, name)

def find_asm(fn):
    out = subprocess.run(['rg', '-l', r'%s %s\b' % (CFG['func_start'], fn), path('asm_dir')], capture_output=True, text=True).stdout.split()
    return out[0] if out else None

def find_tu(fn):
    cmd = ['rg', '-l', '--glob', '*.c'] + sum((['--glob', '!' + g] for g in CFG['skip_src_globs']), [])
    out = subprocess.run(cmd + [r'(/%s\.s"|\b%s\s*\([^;]*\)\s*\{?\s*$)' % (fn, fn), path('src_dir')], capture_output=True, text=True).stdout.split()
    return os.path.relpath(out[0], REPO) if out else None

def span(src, fn):
    """(start, end) of fn's definition or INCLUDE_ASM line in src."""
    m = re.search(r'^[^\n;#]*\b' + fn + r'\([^)]*\)\s*\{', src, re.M)
    if m:
        i = src.index('{', m.start()); d = 0
        while True:
            if src[i] == '{': d += 1
            elif src[i] == '}':
                d -= 1
                if d == 0: break
            i += 1
        return m.start(), i + 1
    m = re.search(r'^INCLUDE_ASM[^\n]*/' + fn + r'\.s"[^\n]*$', src, re.M)
    return (m.start(), m.end()) if m else None

def tell(fn):
    """Return-type tell from a Thumb epilogue: pop {r1} => non-void, pop {r0} => void."""
    a = open(find_asm(fn)).read()
    if re.search(r'pop\s*\{r1\}', a): return 'int'
    if re.search(r'pop\s*\{r0\}', a): return 'void'
    return None

def _sh(cmd):
    pre = 'source %s >/dev/null 2>&1; ' % shlex.quote(os.path.expanduser(CFG['env_script'])) if CFG['env_script'] else ''
    return subprocess.run(['bash', '-c', pre + cmd], cwd=REPO, capture_output=True, text=True, timeout=CFG['build_timeout'] + 30)

def _disasm(obj, fn):
    out = subprocess.run([CFG['objdump'], '-dr', '--no-show-raw-insn', obj], capture_output=True, text=True).stdout
    lines, on = [], False
    for l in out.splitlines():
        if re.match(r'^[0-9a-f]+ <%s>:$' % re.escape(fn), l): on = True; continue
        if on and re.match(r'^[0-9a-f]+ <.*>:$', l): break
        if on and l.strip():
            l = re.sub(r'^\s*[0-9a-f]+:\s*', '', l); l = re.sub(r'[0-9a-f]+ <[^>]*>', 'ADDR', l)
            lines.append(re.sub(r'\s+@.*', '', l))
    return lines

def compare(tu, fns):
    """Build tu's object and diff each function against the reference object.
    Returns ({fn: diff_count or None on build error}, text)."""
    stem = os.path.splitext(tu)[0]
    sub = dict(stem=stem, rel=os.path.relpath(stem, CFG['src_dir']))
    obj = CFG['obj_path'].format(**sub); ref = os.path.expanduser(CFG['ref_obj_path'].format(**sub))
    if not os.path.isabs(ref): ref = os.path.join(REPO, ref)
    cmd = CFG['build_cmd'].format(obj=obj, tu=tu, cc=CFG['cc'], cflags=CFG['cflags'])
    r = _sh('timeout %d %s' % (CFG['build_timeout'], cmd))
    if r.returncode:
        err = [l for l in (r.stdout + r.stderr).splitlines() if re.search(r'error|:\d+:', l)][:20]
        return {f: None for f in fns}, '\n'.join(err)
    import difflib
    res, txt = {}, []
    for f in fns:
        d = [l for l in difflib.unified_diff(_disasm(ref, f), _disasm(os.path.join(REPO, obj), f), lineterm='', n=0) if l[:1] in '+-' and l[:3] not in ('+++', '---')]
        res[f] = len(d)
        txt.append('%s %s' % (f, 'MATCH' if not d else 'DIFF (%d)' % len(d))); txt += d[:40]
    return res, '\n'.join(txt)

class TU:
    def __init__(self, tu, fn):
        self.tu, self.fn, self.path = tu, fn, os.path.join(REPO, tu)
        self.orig = open(self.path).read()
        self.a, self.b = span(self.orig, fn)
    def write(self, body):
        open(self.path, 'w').write(self.orig[:self.a] + body.strip() + self.orig[self.b:])
    def restore(self):
        open(self.path, 'w').write(self.orig)
    def score(self, body):
        """diff-line count (0 = match), or 9999 on compile error."""
        self.write(body)
        res, out = compare(self.tu, [self.fn])
        return (9999 if res[self.fn] is None else res[self.fn]), out

def log_timing(rec):
    open(work('timing.log'), 'a').write(json.dumps(rec) + '\n')

if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['get']: print(path(a[1]) if a[1] in ('repo', 'permuter', 'work_dir', 'asm_dir', 'src_dir') else CFG[a[1]])
    elif a[:1] == ['compare']: print(compare(a[1], a[2:])[1])
    else: print('usage: funcutil.py [--config F] get KEY | compare TU FUNC...')
