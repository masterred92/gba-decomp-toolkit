#!/usr/bin/env bash
# End-to-end test on our own MIT homebrew ROM only.
set -euo pipefail
cd "$(dirname "$0")"; R=$(pwd)/..
make -s -C homebrew clean demo.gba
cd "$R" && rm -rf tests/out
python3 -m gbadt info tests/homebrew/demo.gba --expect-sha1 "$(sha1sum tests/homebrew/demo.gba | cut -d' ' -f1)" >/dev/null
python3 -m gbadt init tests/homebrew/demo.gba tests/out
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
echo ALL TESTS PASSED
