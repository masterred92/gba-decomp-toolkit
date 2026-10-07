#!/usr/bin/env bash
# End-to-end test on our own MIT homebrew ROM only.
set -euo pipefail
cd "$(dirname "$0")"; R=$(pwd)/..
make -s -C homebrew clean demo.gba demo_b.gba
cd "$R" && rm -rf tests/out tests/out_b
python3 -m gbadt info tests/homebrew/demo.gba --expect-sha1 "$(sha1sum tests/homebrew/demo.gba | cut -d' ' -f1)" >/dev/null
python3 -m gbadt init tests/homebrew/demo.gba tests/out --compiler arm-none-eabi-gcc
make -s -C tests/out compare
# discovery: every real function in the demo (incl. the push-less leaf rgb15) starts a segment,
# and main (whose PUSH comes after 3 scheduled instructions) is not split in two
python3 - <<'PY'
import json, subprocess
nm = subprocess.run(["arm-none-eabi-nm", "tests/homebrew/demo.elf"], capture_output=True, text=True).stdout
want = {int(a, 16) - 0x08000000: n for a, t, n in (l.split() for l in nm.splitlines()) if t in "Tt" and n != "_start"}
segs = {s["start"]: s for s in json.load(open("tests/out/config.json"))["segments"] if s["kind"] == "code"}
assert set(segs) == set(want), f"discovered {sorted(map(hex, segs))}, expected {sorted(map(hex, want))}"
print("discovery: OK", ", ".join(f"{want[o]}<-{segs[o]['found_by']}" for o in sorted(want)))
PY
# match loop: compile checksum() alone with the demo's compiler, compare vs discovered function
ADDR=$(arm-none-eabi-nm tests/homebrew/demo.elf | awk '/ T checksum$/{print toupper($1)}')
printf 'typedef unsigned int u32;\nu32 checksum(const unsigned char *p, u32 n) { u32 s = 0; while (n--) s = (s << 1 | s >> 31) ^ *p++; return s; }\n' > /tmp/fn.c
python3 -m gbadt match tests/out "sub_$ADDR" /tmp/fn.c --cflags "-mthumb -mthumb-interwork -mcpu=arm7tdmi -O2"
printf 'typedef unsigned int u32;\nu32 checksum(const unsigned char *p, u32 n) { u32 s = 0; while (n--) s = (s << 1) ^ *p++; return s; }\n' > /tmp/fn_bad.c
! python3 -m gbadt match tests/out "sub_$ADDR" /tmp/fn_bad.c --cflags "-mthumb -mthumb-interwork -mcpu=arm7tdmi -O2"
# import-symbols: use the demo's own nm output as a stand-in "sibling" symbol file
arm-none-eabi-nm tests/homebrew/demo.elf > /tmp/demo.syms
echo "main = 0x0FFFFFF0;" >> /tmp/demo.syms   # bogus address -> must be reported, not applied
python3 -m gbadt import-symbols tests/out /tmp/demo.syms | tee /tmp/imp.txt
grep -q -- "-> checksum" /tmp/imp.txt
test -f tests/out/asm/funcs/checksum.s
make -s -C tests/out clean compare   # renaming must keep the build byte-identical
python3 -m gbadt match tests/out checksum /tmp/fn.c --cflags "-mthumb -mthumb-interwork -mcpu=arm7tdmi -O2"
# signatures: same program, different layout (demo_b has 2 extra functions). Name demo_b's
# functions from the named tests/out project by masked-byte fingerprints alone.
python3 -m gbadt init tests/homebrew/demo_b.gba tests/out_b --compiler arm-none-eabi-gcc >/dev/null
python3 -m gbadt signatures build tests/out -o /tmp/demo_a.sigs
python3 -m gbadt signatures match /tmp/demo_a.sigs tests/out_b -o /tmp/demo_b.syms
python3 -m gbadt import-symbols tests/out_b /tmp/demo_b.syms
python3 - <<'PY'
import json, subprocess
nm = subprocess.run(["arm-none-eabi-nm", "tests/homebrew/demo_b.elf"], capture_output=True, text=True).stdout
addr = {n: int(a, 16) - 0x08000000 for a, t, n in (l.split() for l in nm.splitlines())}
segs = {s["name"]: s for s in json.load(open("tests/out_b/config.json"))["segments"] if s["kind"] == "code"}
for n in ["reset", "rgb15", "checksum", "fill_gradient", "main"]:
    assert n in segs and segs[n]["start"] == addr[n], f"{n} not found at its demo_b address"
for n in ["spacer_a", "spacer_b"]:
    assert n not in segs, f"{n} exists only in demo_b, must not be named"
a, b = (open(f, "rb").read() for f in ("tests/homebrew/demo.gba", "tests/homebrew/demo_b.gba"))
ma = [s for s in json.load(open("tests/out/config.json"))["segments"] if s["name"] == "main"][0]
assert a[ma["start"]:ma["end"]] != b[segs["main"]["start"]:segs["main"]["end"]], "main should differ in raw bytes"
print("signatures: OK (5/5 named across layouts; main's raw bytes differ, signatures equal)")
PY
make -s -C tests/out_b clean compare
# compiler profiles: list, select at init, bad name rejected, missing compiler reported
python3 -m gbadt compilers | grep -q gcc-2.96-patched
rm -rf /tmp/gbadt_prof && python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_prof --compiler gcc-2.96-patched >/dev/null
grep -q '"compiler": "gcc-2.96-patched"' /tmp/gbadt_prof/config.json
grep -q 'fcall-used-r4' /tmp/gbadt_prof/Makefile
if python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_bad --compiler nope 2>/dev/null; then echo "bad profile accepted"; exit 1; fi
(env -u GCC296_DIR python3 -m gbadt match /tmp/gbadt_prof checksum /tmp/fn.c 2>&1 || true) | grep -q "compiler not found"
# ads12 (no-matching profile): asm-only by default, still byte-identical; match refuses;
# notes-only makes a function table without copying the ROM; --mode match is rejected
rm -rf /tmp/gbadt_ads /tmp/gbadt_adsn /tmp/gbadt_adsx
python3 -m gbadt compilers | grep -q "ads12.*no matching"
python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_ads --compiler ads12 >/dev/null
grep -q '"mode": "asm-only"' /tmp/gbadt_ads/config.json && grep -q "MATCHING DISABLED" /tmp/gbadt_ads/Makefile
make -s -C /tmp/gbadt_ads compare >/dev/null
(python3 -m gbadt match /tmp/gbadt_ads sub_08000108 /tmp/fn.c 2>&1 || true) | grep -q "matching is disabled"
python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_adsn --compiler ads12 --mode notes-only >/dev/null
test ! -e /tmp/gbadt_adsn/baserom.gba && test ! -d /tmp/gbadt_adsn/asm
test "$(grep -c '^| `08' /tmp/gbadt_adsn/notes/functions.md)" = 5
python3 -m gbadt import-symbols /tmp/gbadt_adsn /tmp/demo.syms >/dev/null && grep -q '`rgb15`' /tmp/gbadt_adsn/notes/functions.md
if python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_adsx --compiler ads12 --mode match 2>/dev/null; then echo "ads12 match accepted"; exit 1; fi
echo "profiles: OK"
python3 tests/check_gcc296.py   # skips if camelot gcc-2.96 is not installed
echo ALL TESTS PASSED
