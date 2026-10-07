"""AI-assisted match loop (stub).

Loop: guess C -> compile with the game's compiler -> diff vs original bytes -> refine.
  * m2c does NOT support ARM/Thumb, so the starting guess comes from Ghidra headless
    (scripts/ghidra_guess.sh) or a hand-written attempt.
  * `propose` is the hook where an LLM is called with: target asm, Ghidra C,
    previous attempt and the diff. Left unimplemented on purpose (bring your own model).
"""
import json, os, re, subprocess, sys, tempfile

PROFILES = os.path.join(os.path.dirname(__file__), "..", "compilers", "profiles.json")

def _expand(v):
    """Expand ${VAR} and ${VAR:-default}."""
    return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", lambda m: os.environ.get(m.group(1), m.group(2) or ""), v)

def load_profile(name, project=None):
    """Return (cc, cflags, kind) for a named profile; relative cc paths resolve against project."""
    profs = json.load(open(PROFILES))
    if name not in profs or name.startswith("_"):
        raise SystemExit(f"unknown compiler profile {name!r}; choose from: " + ", ".join(k for k in profs if not k.startswith("_")))
    p = profs[name]
    cc = _expand(p["cc"])
    if project and os.sep in cc and not os.path.isabs(cc):
        cc = os.path.join(project, cc)
    cflags = _expand(p["cflags"])
    if project:
        cflags = re.sub(r"-B(?!/)(\S+)", lambda m: "-B" + os.path.join(project, m.group(1)), cflags)
    return cc, cflags, p["kind"]

def target_bytes(project, func):
    cfg = json.load(open(os.path.join(project, "config.json")))
    sg = next(s for s in cfg["segments"] if s["name"] == func)
    rom = open(os.path.join(project, "baserom.gba"), "rb").read()
    return rom[sg["start"]:sg["end"]], sg

def compile_c(c_path, cc1, cflags, prefix="arm-none-eabi-", kind=None):
    """Compile C -> .text bytes. agbcc emits asm (cc1-style); gcc also accepted."""
    d = tempfile.mkdtemp()
    s, o, b = (os.path.join(d, x) for x in ("f.s", "f.o", "f.bin"))
    if kind is None:
        kind = "cc1" if "agbcc" in os.path.basename(cc1) else "driver"
    if kind == "cc1":
        pre = subprocess.run(["cpp", "-P", c_path], capture_output=True, text=True, check=True).stdout
        subprocess.run([cc1, *cflags.split(), "-o", s], input=pre, text=True, check=True)
        subprocess.run([prefix + "as", "-mcpu=arm7tdmi", "-o", o, s], check=True)
    elif os.path.basename(cc1) == "xgcc":  # gcc-2.96 driver: emit asm, assemble with modern as
        subprocess.run([cc1, *cflags.split(), "-S", "-o", s, c_path], check=True)
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
    ap.add_argument("--profile", help="compiler profile from compilers/profiles.json (default: project config 'compiler', else arm-none-eabi-gcc)")
    ap.add_argument("--cc", help="explicit compiler path (overrides profile)")
    ap.add_argument("--cflags", help="explicit flags (overrides profile)")
    a = ap.parse_args(argv)
    cfg = json.load(open(os.path.join(a.project, "config.json")))
    name = a.profile or cfg.get("compiler", "arm-none-eabi-gcc")
    cc, cflags, kind = load_profile(name, a.project)
    if a.cc: cc, kind = a.cc, None
    if a.cflags: cflags = a.cflags
    if os.sep in cc and not os.path.exists(cc):
        raise SystemExit(f"compiler not found: {cc} (profile {name}); see docs/compilers.md")
    t, _ = target_bytes(a.project, a.func)
    c = compile_c(a.c_file, cc, cflags, kind=kind)
    d = score(t, c)
    print(f"{a.func}: target {len(t)}B, candidate {len(c)}B, differing bytes {d} -> {'MATCH' if d == 0 else 'MISMATCH'}")
    return 0 if d == 0 else 1
