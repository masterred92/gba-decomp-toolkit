#!/usr/bin/env python3
"""mutate.py [--config accel.json] TU FUNC [start.c] [--budget SECONDS] [--keep]

Greedy matcher: starting from FUNC's current C in TU (or start.c), repeatedly
applies the playbook mutations below, compiles each candidate (funcutil.compare) and
keeps the one that lowers the instruction-diff count, until MATCH, no gain, or
the time budget. Leaves the best candidate in the TU only if it MATCHes (or
with --keep). Best candidate always saved to <work_dir>/mut_FUNC.c, log to
<work_dir>/timing.log.

Playbook, all semantics-preserving:
  P1  operand order of commutative ops (+ * & | ^ == !=)
  P2  declaration order of locals
  P3  order of adjacent independent statements
  P4  signedness of locals/params (int<->unsigned, s16<->u16, ...)
  P5  loop bound form: i < N / i <= N-1 / i != N
  P6  re-read instead of local: inline a single-assignment local
  P7  local instead of re-read: hoist a repeated memory read into a local
  P8  'v = E + 1' <-> 'v = E; v++'
  P9  for <-> while loop shape
  P10 index vs pointer arithmetic: p[i] <-> *(p + i)
"""
import copy, os, re, sys, time, json
sys.path.insert(0, os.path.dirname(__file__))
from funcutil import TU, CFG, work, log_timing
from pycparser import c_parser, c_ast, c_generator

TYPEDEFS = list(CFG['typedefs'])   # typedef names pycparser must know about
COMM = {'+', '*', '&', '|', '^', '==', '!='}
SIGN = {('int',): ('unsigned', 'int'), ('unsigned', 'int'): ('int',), ('short',): ('unsigned', 'short'),
        ('unsigned', 'short'): ('short',), ('char',): ('unsigned', 'char'), ('unsigned', 'char'): ('signed', 'char'),
        ('signed', 'char'): ('unsigned', 'char'), ('unsigned',): ('int',),
        ('s32',): ('u32',), ('u32',): ('s32',), ('s16',): ('u16',), ('u16',): ('s16',), ('s8',): ('u8',), ('u8',): ('s8',)}
gen = c_generator.CGenerator()

TYPEOF = {}
def _typeof_sub(body):
    out, i = [], 0
    while True:
        j = body.find('__typeof__(', i)
        if j < 0: out.append(body[i:]); break
        out.append(body[i:j]); k = j + len('__typeof__('); d = 1
        while d:
            d += {'(': 1, ')': -1}.get(body[k], 0); k += 1
        expr = body[j:k]
        name = next((n for n, e in TYPEOF.items() if e == expr), None) or 'TYPEOF_%d' % len(TYPEOF)
        TYPEOF[name] = expr; out.append(name); i = k
    return ''.join(out)

def untypeof(s):
    for n, e in sorted(TYPEOF.items(), key=lambda x: -len(x[0])):
        s = re.sub(r'\b%s\b' % n, e, s)
    return s

def parse(body):
    body = _typeof_sub(body)
    pre = ''.join('typedef int %s;\n' % t for t in TYPEOF).join('typedef int %s;\n' % t for t in TYPEDEFS)
    extra = set(re.findall(r'\b([A-Z]\w*)\s*\*', body)) - set(TYPEDEFS)
    pre += ''.join('typedef int %s;\n' % t for t in extra if not re.search(r'struct\s+' + t, body))
    b = re.sub(r'/\*.*?\*/|//[^\n]*', '', body, flags=re.S)
    b = re.sub(r'__asm__\("[^"]*"\)|\basm\("[^"]*"\)', '', b)
    ast = c_parser.CParser().parse(pre + b)
    return ast, len(TYPEOF) + len(TYPEDEFS) + len([t for t in extra if not re.search(r'struct\s+' + t, body)])

def emit(ast, nskip):
    return '\n'.join(gen.visit(e) + (';' if not isinstance(e, c_ast.FuncDef) else '') for e in ast.ext[nskip:])

def nodes(n, acc=None):
    acc = [] if acc is None else acc
    acc.append(n)
    for _, c in n.children(): nodes(c, acc)
    return acc

def idents(n):
    return {x.name for x in nodes(n) if isinstance(x, c_ast.ID)}

def has(n, *types):
    return any(isinstance(x, types) for x in nodes(n))

def memread(n):
    return any(isinstance(x, (c_ast.StructRef, c_ast.ArrayRef)) or (isinstance(x, c_ast.UnaryOp) and x.op == '*') for x in nodes(n))

def writes(n):
    """(written plain idents, writes memory?, has call)"""
    w, mem = set(), False
    for x in nodes(n):
        t = None
        if isinstance(x, c_ast.Assignment): t = x.lvalue
        elif isinstance(x, c_ast.UnaryOp) and x.op in ('++', '--', 'p++', 'p--'): t = x.expr
        if t is not None:
            if isinstance(t, c_ast.ID): w.add(t.name)
            else: mem = True
        if isinstance(x, c_ast.Decl) and x.init is not None: w.add(x.name)
    return w, mem, has(n, c_ast.FuncCall)

def memkeys(n):
    """(write keys, read keys, opaque) for struct-field memory accesses; opaque = deref/array writes."""
    w, r, opaque = set(), set(), False
    for x in nodes(n):
        t = None
        if isinstance(x, c_ast.Assignment): t = x.lvalue
        elif isinstance(x, c_ast.UnaryOp) and x.op in ('++', '--', 'p++', 'p--'): t = x.expr
        if t is not None and not isinstance(t, c_ast.ID):
            if isinstance(t, c_ast.StructRef): w.add(gen.visit(t))
            else: opaque = True
        if isinstance(x, c_ast.StructRef): r.add(gen.visit(x))
        elif isinstance(x, (c_ast.ArrayRef,)) or (isinstance(x, c_ast.UnaryOp) and x.op == '*'): r.add('*')
    return w, r, opaque

def independent(a, b):
    wa, ma, ca = writes(a); wb, mb, cb = writes(b)
    if not (ca or cb) and (ma or mb):
        # field-level check (assumes distinct struct members don't alias)
        kwa, kra, oa = memkeys(a); kwb, krb, ob = memkeys(b)
        if not (oa or ob) and not (kwa & (krb | kwb)) and not (kwb & (kra | kwa)) and '*' not in (kra | krb):
            if not (wa & (idents(b) | wb)) and not (wb & (idents(a) | wa)):
                return True

    wa, ma, ca = writes(a); wb, mb, cb = writes(b)
    ra, rb = idents(a), idents(b)
    if ca and cb: return False
    if (ca or cb) and ((ma or mb) or (ca and memread(b)) or (cb and memread(a))): return False
    if ca and (wb & idents(a) or wb) and not wb.isdisjoint(ra | wa): return False
    if wa & (rb | wb) or wb & (ra | wa): return False
    if (ma and (mb or memread(b))) or (mb and memread(a)): return False
    return True

def same(a, b): return gen.visit(a) == gen.visit(b)

def candidates(ast):
    """yield (tag, mutator) where mutator(ast_copy) mutates in place; sites are DFS indices."""
    all_ = nodes(ast)
    for k, n in enumerate(all_):
        if isinstance(n, c_ast.BinaryOp) and n.op in COMM and not same(n.left, n.right):
            yield 'P1 swap %s' % n.op, (lambda k: lambda t: _swap(nodes(t)[k]))(k)
        if isinstance(n, c_ast.Compound) and n.block_items:
            items = n.block_items
            for i in range(len(items) - 1):
                a, b = items[i], items[i + 1]
                if isinstance(a, c_ast.Decl) and isinstance(b, c_ast.Decl) and not (a.init is not None and has(a.init, c_ast.FuncCall) and b.init is not None and has(b.init, c_ast.FuncCall)) and a.name not in (idents(b.init) if b.init is not None else set()):
                    yield 'P2 decl order', (lambda k, i: lambda t: _swapitems(nodes(t)[k], i))(k, i)
                elif not isinstance(a, (c_ast.Decl, c_ast.If, c_ast.For, c_ast.While, c_ast.DoWhile, c_ast.Return, c_ast.Break, c_ast.Continue, c_ast.Label, c_ast.Switch, c_ast.Goto)) \
                        and not isinstance(b, (c_ast.Decl, c_ast.If, c_ast.For, c_ast.While, c_ast.DoWhile, c_ast.Return, c_ast.Break, c_ast.Continue, c_ast.Label, c_ast.Switch, c_ast.Goto)) \
                        and independent(a, b):
                    yield 'P3 stmt order', (lambda k, i: lambda t: _swapitems(nodes(t)[k], i))(k, i)
            # P6 inline single-assignment local
            for i, d in enumerate(items):
                if isinstance(d, c_ast.Decl) and isinstance(d.type, c_ast.TypeDecl):
                    yield 'P6 re-read %s' % d.name, (lambda k, i: lambda t: _inline(nodes(t)[k], i))(k, i)
            # P7 hoist repeated memory read
            reads = {}
            for x in nodes(n):
                if isinstance(x, (c_ast.StructRef, c_ast.ArrayRef)) or (isinstance(x, c_ast.UnaryOp) and x.op == '*'):
                    reads.setdefault(gen.visit(x), 0); reads[gen.visit(x)] += 1
            for e, c in reads.items():
                if c >= 2:
                    yield 'P7 local for %s' % e[:30], (lambda k, e: lambda t: _hoist(nodes(t)[k], e))(k, e)
        if isinstance(n, c_ast.Decl) and isinstance(n.type, c_ast.TypeDecl) and isinstance(n.type.type, c_ast.IdentifierType):
            if tuple(n.type.type.names) in SIGN:
                yield 'P4 sign %s' % n.name, (lambda k: lambda t: _sign(nodes(t)[k]))(k)
        if isinstance(n, c_ast.For) and isinstance(n.cond, c_ast.BinaryOp) and isinstance(n.cond.right, c_ast.Constant):
            for form in ('<', '<=', '!='):
                if form != n.cond.op:
                    yield 'P5 bound %s' % form, (lambda k, form: lambda t: _bound(nodes(t)[k], form))(k, form)
        if isinstance(n, c_ast.For) and n.init is not None and n.next is not None:
            yield 'P9 for->while', (lambda k: lambda t: _forwhile(t, nodes(t)[k]))(k)
        if isinstance(n, c_ast.Compound) and n.block_items:
            for i, s in enumerate(n.block_items):
                if isinstance(s, c_ast.Assignment) and s.op == '=' and isinstance(s.lvalue, c_ast.ID) and \
                        isinstance(s.rvalue, c_ast.BinaryOp) and s.rvalue.op == '+' and isinstance(s.rvalue.right, c_ast.Constant) and s.rvalue.right.value == '1' \
                        and s.lvalue.name not in idents(s.rvalue.left):
                    yield 'P8 split +1', (lambda k, i: lambda t: _split1(nodes(t)[k], i))(k, i)
        if isinstance(n, c_ast.Compound) and n.block_items:
            lead = 0
            while lead < len(n.block_items) and isinstance(n.block_items[lead], c_ast.Decl): lead += 1
            for i in range(lead, len(n.block_items)):
                st = n.block_items[i]
                roots = {c_ast.Return: 'expr', c_ast.Assignment: 'rvalue', c_ast.If: 'cond'}
                r = next((getattr(st, f) for T_, f in roots.items() if isinstance(st, T_)), None)
                if r is None or has(r, c_ast.FuncCall, c_ast.Assignment): continue
                if any(isinstance(x, c_ast.UnaryOp) and x.op in ('++', '--', 'p++', 'p--') for x in nodes(r)): continue
                for j, x in enumerate(nodes(r)):
                    if x is r and isinstance(st, c_ast.Assignment) and st.op == '=': continue
                    if isinstance(x, c_ast.BinaryOp) and x.op not in ('&&', '||') or isinstance(x, (c_ast.StructRef, c_ast.ArrayRef)) or (isinstance(x, c_ast.UnaryOp) and x.op == '*'):
                        yield 'P11 name subexpr %s' % gen.visit(x)[:24], (lambda k, i, j: lambda t: _extract(nodes(t)[k], i, j))(k, i, j)
        if isinstance(n, c_ast.ArrayRef):
            yield 'P10 index->ptr', (lambda k: lambda t: _a2p(t, nodes(t)[k]))(k)

def _swap(n): n.left, n.right = n.right, n.left
def _swapitems(c, i): c.block_items[i], c.block_items[i + 1] = c.block_items[i + 1], c.block_items[i]
def _sign(d):
    d.type.type.names = list(SIGN[tuple(d.type.type.names)])
def _bound(f, form):
    v = f.cond.right.value; base = int(v, 0)
    cur = f.cond.op
    lim = base + 1 if cur == '<=' else base
    f.cond.op = form
    f.cond.right = c_ast.Constant('int', str(lim - 1 if form == '<=' else lim))

class Bail(Exception): pass

def replace_in(root, pred, make):
    for n in nodes(root):
        for name, c in n.children():
            if pred(c):
                new = make()
                m = re.match(r'(\w+)\[(\d+)\]', name)
                if m: getattr(n, m.group(1))[int(m.group(2))] = new
                else: setattr(n, name, new)

def _inline(comp, i):
    d = comp.block_items[i]; name = d.name; rest = comp.block_items[i + 1:]
    if d.init is not None:
        rhs, start = d.init, 0
    else:
        asg = [j for j, s in enumerate(rest) if isinstance(s, c_ast.Assignment) and s.op == '=' and isinstance(s.lvalue, c_ast.ID) and s.lvalue.name == name]
        if len(asg) != 1: raise Bail
        rhs, start = rest[asg[0]].rvalue, asg[0] + 1
    if has(rhs, c_ast.FuncCall, c_ast.Assignment): raise Bail
    after = rest[start:]
    for s in after:
        w, mem, call = writes(s)
        if name in w or (w & idents(rhs)) or (memread(rhs) and (mem or call)): raise Bail
    if d.init is None:
        del rest[asg[0]]
    comp.block_items[i + 1:] = rest
    del comp.block_items[i]
    for s in comp.block_items[i:]:
        replace_in(s, lambda c: isinstance(c, c_ast.ID) and c.name == name, lambda: c_ast.Cast(c_ast.Typename(None, [], None, copy.deepcopy(d.type)), copy.deepcopy(rhs)) if False else copy.deepcopy(rhs))

HN = [0]
def _hoist(comp, e):
    items = comp.block_items
    first = next(j for j, s in enumerate(items) if any(gen.visit(x) == e for x in nodes(s)))
    target = next(x for x in nodes(items[first]) if gen.visit(x) == e)
    # no stores to memory / calls / writes to its idents between first and last use
    ids = idents(target)
    uses = [j for j, s in enumerate(items) if any(gen.visit(x) == e for x in nodes(s))]
    for s in items[first:uses[-1] + 1]:
        w, mem, call = writes(s)
        if mem or call or (w & ids): raise Bail
    HN[0] += 1; v = 't%d' % HN[0]
    decl = c_parser.CParser().parse('void f(void){ __typeof__(0) %s; }' % v).ext[0].body.block_items[0]
    decl.type.type.names = [_typeof_sub('__typeof__(%s)' % e)]
    decl.init = copy.deepcopy(target)
    for s in items[first:]:
        replace_in(s, lambda c: gen.visit(c) == e, lambda: c_ast.ID(v))
    # declarations must stay at block top (C89): put after the last leading Decl if first use is later
    lead = 0
    while lead < len(items) and isinstance(items[lead], c_ast.Decl): lead += 1
    if first < lead: raise Bail
    items.insert(first, c_ast.Assignment('=', c_ast.ID(v), copy.deepcopy(target)))
    decl.init = None
    items.insert(lead, decl)

def _extract(comp, i, j):
    st = comp.block_items[i]
    r = st.expr if isinstance(st, c_ast.Return) else st.rvalue if isinstance(st, c_ast.Assignment) else st.cond
    x = nodes(r)[j]
    HN[0] += 1; v = 'v%d' % HN[0]
    e = gen.visit(x)
    decl = c_parser.CParser().parse('void f(void){ int %s; }' % v).ext[0].body.block_items[0]
    decl.type.type.names = [_typeof_sub('__typeof__(%s)' % e)]
    replace_in(st, lambda c: c is x, lambda: c_ast.ID(v))
    if x is r:
        if isinstance(st, c_ast.Return): st.expr = c_ast.ID(v)
        else: st.cond = c_ast.ID(v)
    lead = 0
    while lead < len(comp.block_items) and isinstance(comp.block_items[lead], c_ast.Decl): lead += 1
    comp.block_items.insert(i, c_ast.Assignment('=', c_ast.ID(v), x))
    comp.block_items.insert(lead, decl)

def _split1(comp, i):
    s = comp.block_items[i]
    comp.block_items[i] = c_ast.Assignment('=', s.lvalue, s.rvalue.left)
    comp.block_items.insert(i + 1, c_ast.UnaryOp('p++', c_ast.ID(s.lvalue.name)))

def _forwhile(root, f):
    if not isinstance(f.init, (c_ast.Assignment, c_ast.ExprList)): raise Bail
    if has(f.stmt, c_ast.Continue): raise Bail
    body = f.stmt if isinstance(f.stmt, c_ast.Compound) else c_ast.Compound([f.stmt])
    body = c_ast.Compound((body.block_items or []) + [f.next])
    w = c_ast.While(f.cond or c_ast.Constant('int', '1'), body)
    for n in nodes(root):
        if isinstance(n, c_ast.Compound) and n.block_items and f in n.block_items:
            j = n.block_items.index(f)
            n.block_items[j:j + 1] = [f.init, w]
            return
    raise Bail

def _a2p(root, a):
    new = c_ast.UnaryOp('*', c_ast.BinaryOp('+', a.name, a.subscript))
    replace_in(root, lambda c: c is a, lambda: new)

def run(tu, fn, start=None, budget=600, keep=False, verbose=True):
    t0 = time.time()
    T = TU(tu, fn)
    body = open(start).read() if start else T.orig[T.a:T.b]
    pre = ''
    m = re.match(r'((?:\s*(?:/\*.*?\*/|extern[^;]*;|struct\s+\w+\s*\{.*?\};)\s*)*)', body, re.S)
    try:
        cur_s, out = T.score(body); best_body = body
        if verbose: print('start', cur_s, flush=True)
        seen = {body}; evals = [1]
        def expand(src, limit=10**6):
            ast, nskip = parse(src)
            fd_idx = max(i for i, e in enumerate(ast.ext) if isinstance(e, c_ast.FuncDef))
            head_txt = src[:src.find(ast.ext[fd_idx].decl.name + '(')]
            src = untypeof(src)
            head_txt = head_txt[:head_txt.rfind('\n') + 1] if '\n' in head_txt else ''
            res = []
            for tag, mut in candidates(ast.ext[fd_idx]):
                if len(res) >= limit or time.time() - t0 > budget: break
                t = copy.deepcopy(ast.ext[fd_idx])
                try: mut(t)
                except (Bail, StopIteration, ValueError, AttributeError, IndexError, KeyError): continue
                cand = head_txt + untypeof(gen.visit(t))
                if cand in seen: continue
                seen.add(cand)
                sc, _ = T.score(cand); evals[0] += 1
                res.append((sc, tag, cand))
                if sc == 0: break
            res.sort(key=lambda r: r[0])
            if os.environ.get('MUTDBG'): [print('   ', r[0], r[1]) for r in res[:8]]
            return res
        while cur_s and time.time() - t0 < budget:
            try:
                res = expand(best_body)
            except Exception as ex:
                print('parse error:', str(ex)[:200]); break
            if not res: break
            if res[0][0] < cur_s:
                cur_s, tag, best_body = res[0]
                if verbose: print('%4.0fs %-34s -> %d' % (time.time() - t0, tag[:34], cur_s), flush=True)
                continue
            # plateau: two-step beam over the best ties / near-ties
            beam = [r for r in res if r[0] <= cur_s + 2][:6]
            found = None
            for s1, tag1, c1 in beam:
                if time.time() - t0 > budget: break
                try: r2 = expand(c1, limit=60)
                except Exception: continue
                if r2 and r2[0][0] < cur_s and (found is None or r2[0][0] < found[0]):
                    found = (r2[0][0], tag1 + ' + ' + r2[0][1], r2[0][2])
                    if found[0] == 0: break
            if not found: break
            cur_s, tag, best_body = found
            if verbose: print('%4.0fs %-34s -> %d' % (time.time() - t0, tag[:34], cur_s), flush=True)
        evals = evals[0]
        open(work('mut_%s.c' % fn), 'w').write(best_body)
        if cur_s == 0 or keep: T.write(best_body)
        else: T.restore()
        dt = time.time() - t0
        log_timing({'fn': fn, 'tool': 'mutate', 'result': cur_s, 'secs': round(dt), 'evals': evals})
        print('RESULT %s %s (%d evals, %.0fs) -> %s' % (fn, 'MATCH' if cur_s == 0 else 'DIFF %d' % cur_s, evals, dt, work('mut_%s.c' % fn)))
        return cur_s
    except BaseException:
        T.restore(); raise

if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    budget = 600
    if '--budget' in sys.argv: budget = int(sys.argv[sys.argv.index('--budget') + 1]); a.remove(str(budget))
    run(a[0], a[1], a[2] if len(a) > 2 else None, budget, '--keep' in sys.argv)
