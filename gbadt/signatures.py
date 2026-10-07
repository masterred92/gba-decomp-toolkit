"""Function signatures: find the same function in two ROMs even when it moved.

Tutor's note: if two games (or two builds of one game) contain the same function, its bytes
are *almost* the same. What changes is anything that encodes an address:
  * BL calls store the distance to the callee, which changes when code moves;
  * literal-pool words hold absolute addresses of ROM data, RAM variables or other functions;
  * a branch that leaves the function (tail call) stores a distance too.
So we "mask" exactly those bytes (replace them with zeros), keep everything else (the
instructions, registers, constants, hardware addresses like 0x04000000), and hash the result.
Equal hash = very likely the same function. Short functions are skipped because many unrelated
tiny functions (e.g. `bx lr`) hash the same.

Workflow:
  signatures build  named_project -o lib.sigs          # project with real names
  signatures match  lib.sigs  target_project -o hits.syms
  import-symbols    target_project hits.syms           # applies the names
"""
import hashlib, json, os, struct
from .discover import PTR_TOPS, _sext

BASE = 0x08000000
MAGIC = "# gbadt signatures v1"


def _pools(code: bytes, start: int, mode: str) -> set:
    """Offsets (relative to the function) of literal-pool words read via LDR [PC]."""
    pools, pc, n = set(), 0, len(code)
    while pc + (2 if mode == "thumb" else 4) <= n:
        if pc in pools:
            pc += 4; continue
        if mode == "thumb":
            hw = struct.unpack_from("<H", code, pc)[0]
            nxt = struct.unpack_from("<H", code, pc + 2)[0] if pc + 4 <= n else 0
            if hw & 0xF800 == 0x4800:
                pools.add(((start + pc + 4) & ~3) - start + (hw & 0xFF) * 4)
            pc += 4 if hw & 0xF800 == 0xF000 and nxt & 0xF800 == 0xF800 else 2
        else:
            w = struct.unpack_from("<I", code, pc)[0]
            if w & 0x0F7F0000 == 0x051F0000:
                off = w & 0xFFF
                pools.add(pc + 8 + (off if w & (1 << 23) else -off))
            pc += 4
    return pools


def _trim(code: bytes, start: int, mode: str, pools: set) -> bytes:
    """Drop alignment padding at the end; it depends on layout, not on the function.
    Zero bytes that belong to a literal-pool word are data, not padding, so they stay."""
    n = len(code)
    in_pool = lambda i: any(p <= i < p + 4 for p in pools)
    while n >= 2 and code[n - 2:n] == b"\0\0" and not in_pool(n - 2):
        n -= 2
    if mode == "thumb" and n >= 2 and code[n - 2:n] == b"\xc0\x46" and (start + n - 2) % 4 == 2 \
            and not in_pool(n - 2):
        n -= 2
    return code[:n]


def masked(code: bytes, start: int, mode: str):
    """Return (masked_bytes, mask) where mask[i] is True for bytes that were blanked."""
    code = bytearray(_trim(code, start, mode, _pools(code, start, mode)))
    n, m = len(code), [False] * len(code)
    pools, pc = set(), 0

    def blank(i, k):            # zero k bytes and mark them as masked (shown as ..)
        for j in range(i, min(i + k, n)):
            code[j] = 0; m[j] = True

    def inside(rel):
        return 0 <= rel < n

    while pc < n:
        if pc in pools:
            if pc + 4 <= n:
                w = struct.unpack_from("<I", code, pc)[0]
                if w >> 24 in PTR_TOPS:
                    blank(pc, 4)
            pc += 4; continue
        if mode == "thumb":
            if pc + 2 > n: break
            hw = struct.unpack_from("<H", code, pc)[0]
            nxt = struct.unpack_from("<H", code, pc + 2)[0] if pc + 4 <= n else 0
            if hw & 0xF800 == 0x4800:                                   # LDR [PC]
                pools.add(((start + pc + 4) & ~3) - start + (hw & 0xFF) * 4)
            elif hw & 0xF800 == 0xF000 and nxt & 0xF800 == 0xF800:      # BL: mask offsets
                blank(pc, 4)
                code[pc + 1], code[pc + 3] = 0xF0, 0xF8              # keep "this is a BL"
                pc += 4; continue
            elif hw & 0xF800 == 0xE000:                                 # B leaving the function
                if not inside(pc + 4 + _sext(hw & 0x7FF, 11) * 2):
                    blank(pc, 2); code[pc + 1] = 0xE0
            pc += 2
        else:
            if pc + 4 > n: break
            w = struct.unpack_from("<I", code, pc)[0]
            if w & 0x0F7F0000 == 0x051F0000:                            # LDR [PC, #imm]
                off = w & 0xFFF
                pools.add(pc + 8 + (off if w & (1 << 23) else -off))
            elif (w >> 25) & 7 == 5:                                    # B / BL
                if w & (1 << 24) or not inside(pc + 8 + _sext(w & 0xFFFFFF, 24) * 4):
                    blank(pc, 3)                                    # keep cond/opcode byte
            pc += 4
    return bytes(code), m


def signature(code: bytes, start: int, mode: str):
    mb, _ = masked(code, start, mode)
    return hashlib.sha1(mode.encode() + b":" + mb).hexdigest()[:16], len(mb)


def build(project: str):
    """[(sig, size, addr, mode, name)] for every code segment of a gbadt project."""
    cfg = json.load(open(os.path.join(project, "config.json")))
    rom = open(os.path.join(project, "baserom.gba"), "rb").read()
    out = []
    for sg in cfg["segments"]:
        if sg["kind"] != "code": continue
        sig, size = signature(rom[sg["start"]:sg["end"]], sg["start"], sg["mode"])
        out.append((sig, size, BASE + sg["start"], sg["mode"], sg["name"]))
    return out


def dump(entries, source="") -> str:
    lines = [f"{MAGIC}  source={source}", "# sig              size  addr        mode   name"]
    lines += [f"{s}  {z:5d}  0x{a:08X}  {m:5}  {n}" for s, z, a, m, n in entries]
    return "\n".join(lines) + "\n"


def load(path: str):
    """Read a .sigs file, or compute signatures if `path` is a project directory."""
    if os.path.isdir(path):
        return build(path)
    out = []
    for line in open(path):
        if not line.strip() or line.startswith("#"): continue
        s, z, a, m, n = line.split()
        out.append((s, int(z), int(a, 16), m, n))
    return out


def match(lib, target, min_size=8, include_unnamed=False):
    """Pair functions whose signature is unique on both sides. Returns (hits, stats)."""
    def index(entries):
        d = {}
        for e in entries: d.setdefault(e[0], []).append(e)
        return d
    li, ti = index(lib), index(target)
    hits, st = [], {"matched": 0, "ambiguous": 0, "too_small": 0, "no_match": 0, "unnamed": 0}
    for sig, ents in li.items():
        s, z, a, m, name = ents[0]
        if not include_unnamed and name.startswith("sub_"):
            st["unnamed"] += len(ents); continue
        if z < min_size:
            st["too_small"] += len(ents); continue
        if sig not in ti:
            st["no_match"] += len(ents); continue
        if len(ents) > 1 or len(ti[sig]) > 1:
            st["ambiguous"] += len(ents); continue
        t = ti[sig][0]
        hits.append((t[2], name, sig, z, a)); st["matched"] += 1
    return sorted(hits), st


def show(project: str, func: str) -> str:
    """Hex dump of a function with masked bytes shown as '..' (for learning)."""
    cfg = json.load(open(os.path.join(project, "config.json")))
    sg = next(s for s in cfg["segments"] if s["name"] == func)
    rom = open(os.path.join(project, "baserom.gba"), "rb").read()
    raw = rom[sg["start"]:sg["end"]]
    mb, m = masked(raw, sg["start"], sg["mode"])
    rows = []
    for i in range(0, len(mb), 16):
        h = " ".join(".." if m[j] else f"{raw[j]:02x}" for j in range(i, min(i + 16, len(mb))))
        rows.append(f"  {BASE + sg['start'] + i:08X}: {h}")
    sig, size = signature(raw, sg["start"], sg["mode"])
    return f"{func} ({sg['mode']}, {size} bytes after trimming padding, {sum(m)} masked) sig {sig}\n" + "\n".join(rows)
