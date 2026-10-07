"""Import function names from a sibling decomp (or any symbol list).

Why: games built on a shared engine (e.g. two titles from one studio) often
contain near-identical functions. A finished sibling project already named
them. Importing its names into our scaffold turns `sub_08001234` into
`UpdateEntity`, which tells you what a function does before you read it.

Accepted formats (auto-detected per line, '#' and '@' lines and trailing '  # ...' ignored):
  nm:            08000194 T checksum
  linker script: checksum = 0x08000194;
  plain:         0x08000194 checksum
Addresses are GBA bus addresses (0x08xxxxxx) or ROM offsets.
Only names whose address equals a discovered function start are applied;
everything else is reported so you can review it (addresses shift between
games, so sibling symbols usually need --offset or a signature match).
"""
import json, os, re

BASE = 0x08000000
_NM = re.compile(r"^([0-9A-Fa-f]{8})\s+[TtWw]\s+(\w+)$")
_LD = re.compile(r"^(\w+)\s*=\s*(0x[0-9A-Fa-f]+)\s*;")
_PL = re.compile(r"^(0x[0-9A-Fa-f]+|[0-9A-Fa-f]{8})\s+(\w+)$")

def parse(text: str) -> dict:
    syms = {}
    for line in text.splitlines():
        line = line.split("  #")[0].strip()   # allow trailing "  # comment"
        if not line or line[0] in "#@": continue
        if m := _NM.match(line): a, n = int(m[1], 16), m[2]
        elif m := _LD.match(line): n, a = m[1], int(m[2], 16)
        elif m := _PL.match(line): a, n = int(m[1], 16), m[2]
        else: continue
        a &= ~1  # thumb bit
        if a < BASE: a += BASE
        syms[a] = n
    return syms

def apply(project: str, text: str, offset: int = 0) -> dict:
    cfg_p = os.path.join(project, "config.json")
    cfg = json.load(open(cfg_p))
    syms = {a + offset: n for a, n in parse(text).items()}
    used, renamed = set(), []
    rom_s = open(os.path.join(project, "rom.s")).read()
    for sg in cfg["segments"]:
        if sg["kind"] != "code": continue
        addr = BASE + sg["start"]
        new = syms.get(addr)
        if not new or new == sg["name"]: continue
        old = sg["name"]
        src, dst = f"asm/funcs/{old}.s", f"asm/funcs/{new}.s"
        body = open(os.path.join(project, src)).read()
        body = re.sub(rf"\b{old}\b", new, body)
        open(os.path.join(project, dst), "w").write(body)
        os.unlink(os.path.join(project, src))
        rom_s = rom_s.replace(f'"{src}"', f'"{dst}"')
        sg["name"], sg["orig_name"] = new, old
        used.add(addr); renamed.append((old, new))
    open(os.path.join(project, "rom.s"), "w").write(rom_s)
    json.dump(cfg, open(cfg_p, "w"), indent=1)
    unmatched = sorted((a, n) for a, n in syms.items() if a not in used)
    return {"renamed": renamed, "unmatched": unmatched}
