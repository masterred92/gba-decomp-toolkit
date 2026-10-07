"""Generate a matching-decomp project from a user-supplied ROM.

Layout produced:
  config.json         segments + discovered functions (edit me)
  asm/funcs/*.s       one file per function: raw .2byte/.4byte + objdump comments
  asm/data/*.s        .incbin of data ranges from baserom.gba (never copied)
  src/                put matched C here; Makefile swaps it in for the .s
  ld_script.ld, Makefile
The output assembles byte-identically by construction; you then replace
functions one by one with C (or symbolic asm) and keep `make compare` green.
"""
import json, os, subprocess, tempfile
from . import header, discover

BASE = 0x08000000

def _objdump(chunk: bytes, mode: str, vma: int) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(chunk); p = f.name
    try:
        args = ["arm-none-eabi-objdump", "-D", "-b", "binary", "-marm",
                f"--adjust-vma={vma:#x}"] + (["-Mforce-thumb"] if mode == "thumb" else [])
        out = subprocess.run(args + [p], capture_output=True, text=True).stdout
    finally:
        os.unlink(p)
    res = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().endswith(":"):
            try: res[int(parts[0].strip()[:-1], 16)] = " ".join(parts[2:]).strip()
            except ValueError: pass
    return res

MODES = ("match", "asm-only", "notes-only")

def generate(rom_path: str, out: str, code_end: int | None = None, compiler: str = "agbcc",
             mode: str = "match") -> dict:
    """mode: match = full matching project; asm-only = byte-identical split, no C matching
    (compiler unavailable, e.g. ARM ADS); notes-only = function table + notes, no build, no ROM copy."""
    assert mode in MODES, mode
    rom = open(rom_path, "rb").read()
    h = header.parse(rom)
    os.makedirs(out, exist_ok=True)
    code_end = code_end or len(rom)
    funcs = discover.discover_detailed(rom, 0xC0, code_end)
    starts = sorted(funcs)
    segs = [{"name": "header", "start": 0, "end": 0xC0, "kind": "data"}]
    cur = 0xC0
    for i, s in enumerate(starts):
        if s < cur: continue
        if s > cur:
            segs.append({"name": f"data_{BASE+cur:08X}", "start": cur, "end": s, "kind": "data"})
        e = next((x for x in starts[i+1:] if x > s), code_end)
        segs.append({"name": f"sub_{BASE+s:08X}", "start": s, "end": e, "kind": "code",
                     "mode": funcs[s]["mode"], "found_by": funcs[s]["why"]})
        cur = e
    if cur < len(rom):
        segs.append({"name": f"data_{BASE+cur:08X}", "start": cur, "end": len(rom), "kind": "data"})
    cfg = {"header": h, "compiler": compiler, "mode": mode, "segments": segs}
    if mode == "notes-only":
        cfg["rom"] = os.path.abspath(rom_path)   # read in place, never copied
        json.dump(cfg, open(f"{out}/config.json", "w"), indent=1)
        _notes(out, cfg)
        return cfg
    for d in ("asm/funcs", "asm/data", "src"):
        os.makedirs(f"{out}/{d}", exist_ok=True)
    order = []
    for sg in segs:
        n, a, b = sg["name"], sg["start"], sg["end"]
        if sg["kind"] == "data":
            body = f'\t.incbin "baserom.gba", {a:#x}, {b-a:#x}\n'
            path = f"asm/data/{n}.s"
        else:
            m = sg["mode"]; step = 2 if m == "thumb" else 4
            dis = _objdump(rom[a:b], m, BASE + a)
            lines = [f"\t.{m}\n\t.global {n}\n{n}:\n"]
            i = a
            while i < b:
                st = step if i + step <= b else 1
                v = int.from_bytes(rom[i:i+st], "little")
                d = {1: ".byte", 2: ".2byte", 4: ".4byte"}[st]
                lines.append(f"\t{d} {v:#0{st*2+2}x}  @ {BASE+i:08X}: {dis.get(BASE+i, '')}\n")
                i += st
            body = "".join(lines)
            path = f"asm/funcs/{n}.s"
        with open(f"{out}/{path}", "w") as f:
            f.write(f"@ {n}  rom {a:#x}-{b:#x}\n" + body)
        order.append(path)
    json.dump(cfg, open(f"{out}/config.json", "w"), indent=1)
    with open(f"{out}/rom.s", "w") as f:
        f.write("\t.syntax unified\n\t.section .text\n" + "".join(f'\t.include "{p}"\n' for p in order))
    with open(f"{out}/ld_script.ld", "w") as f:
        f.write("SECTIONS {\n  . = 0x08000000;\n  .text : { *(.text) }\n}\n")
    with open(f"{out}/Makefile", "w") as f:
        from .match import load_profile
        cc, cflags, _ = load_profile(compiler)
        mk = MAKEFILE.replace("@SHA1@", h["sha1"]).replace("@COMPILER@", compiler)
        if mode == "match":
            mk = mk.replace("@CC@", cc).replace("@CFLAGS@", cflags)
        else:
            mk = mk.replace("CC1 ?= @CC@\nCFLAGS ?= @CFLAGS@\n", NO_MATCH)
        f.write(mk)
    with open(f"{out}/rom.sha1", "w") as f:
        f.write(f"{h['sha1']}  build/rom.gba\n")
    if mode != "match":
        _notes(out, cfg)
    return cfg

NO_MATCH = """# MATCHING DISABLED (asm-only mode): this game's original compiler isn't available, so C
# can't be checked byte-for-byte. The asm still rebuilds the exact ROM; label it, rename
# functions and write up what they do in notes/. See docs/compilers.md in gba-decomp-toolkit.
CC1 :=
CFLAGS :=
"""

def _notes(out, cfg):
    """notes/functions.md: one row per discovered function, ready to fill in."""
    os.makedirs(f"{out}/notes", exist_ok=True)
    h = cfg["header"]
    rows = [f"| `{BASE + s['start']:08X}` | {s['end'] - s['start']} | {s['mode']} | {s.get('found_by', '')} | `{s['name']}` |  |"
            for s in cfg["segments"] if s["kind"] == "code"]
    txt = f"""# Function notes: {h.get('title', '')} ({h.get('game_code', '')})

Mode **{cfg['mode']}**, compiler profile **{cfg['compiler']}**. Matching is off, so the goal is
understanding: what each function does, what it reads and writes, who calls it.
Sizes are up to the next discovered start, so they can include padding or data.

| Address | Size | Mode | Found by | Name | What it does |
|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n"
    p = f"{out}/notes/functions.md"
    if not os.path.exists(p):          # never overwrite your write-ups
        open(p, "w").write(txt)

MAKEFILE = r"""# Generated by gba-decomp-toolkit. Requires baserom.gba (your own dump) here.
PREFIX ?= arm-none-eabi-
AS := $(PREFIX)as
LD := $(PREFIX)ld
OBJCOPY := $(PREFIX)objcopy
# Compiler for matched C. pret/agbcc for most GBA titles; some games used other
# GCC versions (e.g. Golden Sun: patched gcc-2.96). Selected profile: @COMPILER@
# (see compilers/profiles.json in gba-decomp-toolkit). Override: make CC1=... CFLAGS=...
CC1 ?= @CC@
CFLAGS ?= @CFLAGS@

all: compare
build/rom.elf: rom.s $(wildcard asm/*/*.s) ld_script.ld
	@mkdir -p build
	$(AS) -mcpu=arm7tdmi -o build/rom.o rom.s
	$(LD) -T ld_script.ld -o $@ build/rom.o
build/rom.gba: build/rom.elf
	$(OBJCOPY) -O binary $< $@
compare: build/rom.gba
	sha1sum -c rom.sha1
clean:
	rm -rf build
.PHONY: all compare clean
"""
