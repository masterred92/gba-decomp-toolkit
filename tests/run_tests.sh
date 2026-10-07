#!/usr/bin/env bash
# End-to-end test on our own MIT homebrew ROM only.
set -euo pipefail
cd "$(dirname "$0")"; R=$(pwd)/..
make -s -C homebrew clean demo.gba
cd "$R" && rm -rf tests/out
python3 -m gbadt info tests/homebrew/demo.gba --expect-sha1 "$(sha1sum tests/homebrew/demo.gba | cut -d' ' -f1)" >/dev/null
python3 -m gbadt init tests/homebrew/demo.gba tests/out --compiler arm-none-eabi-gcc
make -s -C tests/out compare
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
# compiler profiles: list, select at init, bad name rejected, missing compiler reported
python3 -m gbadt compilers | grep -q gcc-2.96-patched
rm -rf /tmp/gbadt_prof && python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_prof --compiler gcc-2.96-patched >/dev/null
grep -q '"compiler": "gcc-2.96-patched"' /tmp/gbadt_prof/config.json
grep -q 'fcall-used-r4' /tmp/gbadt_prof/Makefile
if python3 -m gbadt init tests/homebrew/demo.gba /tmp/gbadt_bad --compiler nope 2>/dev/null; then echo "bad profile accepted"; exit 1; fi
(env -u GCC296_DIR python3 -m gbadt match /tmp/gbadt_prof checksum /tmp/fn.c 2>&1 || true) | grep -q "compiler not found"
echo "profiles: OK"
python3 tests/check_gcc296.py   # skips if camelot gcc-2.96 is not installed
echo ALL TESTS PASSED
