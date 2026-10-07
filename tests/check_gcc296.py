"""Optional check: does the camelot gcc-2.96 install behave like Golden Sun's compiler?
Skips (exit 0) if the compiler isn't installed. Uses the toolkit's own profile + compile path."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gbadt import match

os.environ.setdefault("GCC296_DIR", os.path.expanduser("~/tools/gcc296"))
cc, cflags, kind = match.load_profile("gcc-2.96-patched")
if not os.path.exists(cc):
    print(f"gcc296: SKIP (no compiler at {cc}; run scripts/install_camelot_gcc.sh)"); sys.exit(0)
src = os.path.join(os.path.dirname(__file__), "fixtures", "camelot_toy.c")
a = match.compile_c(src, cc, cflags, kind=kind)
b = match.compile_c(src, cc, cflags, kind=kind)
assert a == b, "output differs between two runs (not deterministic)"
with tempfile.NamedTemporaryFile(suffix=".bin") as f:
    f.write(a); f.flush()
    dis = subprocess.run(["arm-none-eabi-objdump", "-D", "-b", "binary", "-marm", "-Mforce-thumb", f.name],
                         capture_output=True, text=True, check=True).stdout
assert "push\t{r5, r6, lr}" in dis, "keep() should save r5,r6 (r4 is scratch under -fcall-used-r4)\n" + dis
assert "mul" not in dis, "scale() should use shift+add, not MUL\n" + dis
print(f"gcc296: OK ({len(a)} bytes; r4 scratch, shift-add multiply, deterministic)")
