"""AI-assisted match loop (stub).

Loop: guess C -> compile with the game's compiler -> diff vs original bytes -> refine.
  * m2c does NOT support ARM/Thumb, so the starting guess comes from Ghidra headless
    (scripts/ghidra_guess.sh) or a hand-written attempt.
  * `propose` is the hook where an LLM is called with: target asm, Ghidra C,
    previous attempt and the diff. Left unimplemented on purpose (bring your own model).
"""
import json, os, subprocess, sys, tempfile

def target_bytes(project, func):
    cfg = json.load(open(os.path.join(project, "config.json")))
    sg = next(s for s in cfg["segments"] if s["name"] == func)
    rom = open(os.path.join(project, "baserom.gba"), "rb").read()
    return rom[sg["start"]:sg["end"]], sg

def compile_c(c_path, cc1, cflags, prefix="arm-none-eabi-"):
    """Compile C -> .text bytes. agbcc emits asm (cc1-style); gcc also accepted."""
    d = tempfile.mkdtemp()
    s, o, b = (os.path.join(d, x) for x in ("f.s", "f.o", "f.bin"))
    if os.path.basename(cc1).startswith("agbcc"):
        pre = subprocess.run(["cpp", "-P", c_path], capture_output=True, text=True, check=True).stdout
        subprocess.run([cc1, *cflags.split(), "-o", s], input=pre, text=True, check=True)
        subprocess.run([prefix + "as", "-mcpu=arm7tdmi", "-o", o, s], check=True)
    else:
        subprocess.run([cc1, *cflags.split(), "-c", "-o", o, c_path], check=True)
    subprocess.run([prefix + "objcopy", "-O", "binary", "-j", ".text", o, b], check=True)
    return open(b, "rb").read()

def score(target, cand):
    n = max(len(target), len(cand))
    diff = sum(1 for i in range(n) if i >= len(target) or i >= len(cand) or target[i] != cand[i])
    return diff  # 0 == match

def propose(asm_text, ghidra_c, last_c, diff_text):
    raise NotImplementedError("plug an LLM call in here; return new C source text")

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("func"); ap.add_argument("c_file")
    ap.add_argument("--cc", default="arm-none-eabi-gcc")
    ap.add_argument("--cflags", default="-mthumb -mcpu=arm7tdmi -O2")
    a = ap.parse_args(argv)
    t, _ = target_bytes(a.project, a.func)
    c = compile_c(a.c_file, a.cc, a.cflags)
    d = score(t, c)
    print(f"{a.func}: target {len(t)}B, candidate {len(c)}B, differing bytes {d} -> {'MATCH' if d == 0 else 'MISMATCH'}")
    return 0 if d == 0 else 1
