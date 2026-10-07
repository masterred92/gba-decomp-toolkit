"""Heuristic Thumb/ARM function discovery.

Signals (combined, deduplicated):
  * ROM entry branch target (ARM)
  * Thumb BL targets (two-halfword F000/F800 pairs) landing inside the code region
  * Thumb prologues: PUSH {..., LR}  (0xB5xx)
  * ARM prologues:  STMFD SP!, {..., LR}  (0xE92D4xxx)
  * Literal-pool pointers 0x08xxxxxx|1 (Thumb function pointers)
This is a starting point; real projects refine with Ghidra/luvdis and by hand.
"""
import struct
BASE = 0x08000000

def discover(rom: bytes, code_start: int, code_end: int) -> dict:
    found = {}  # rom_offset -> mode
    entry = struct.unpack_from("<I", rom, 0)[0]
    if entry >> 24 == 0xEA:
        found[8 + ((entry & 0xFFFFFF) << 2)] = "arm"
    for off in range(code_start, code_end - 4, 2):
        hw, hw2 = struct.unpack_from("<HH", rom, off)
        if hw & 0xFF00 == 0xB500:
            found.setdefault(off, "thumb")
        if hw & 0xF800 == 0xF000 and hw2 & 0xF800 == 0xF800:
            hi = hw & 0x7FF
            if hi & 0x400: hi -= 0x800
            tgt = off + 4 + (hi << 12) + ((hw2 & 0x7FF) << 1)
            if code_start <= tgt < code_end:
                found.setdefault(tgt, "thumb")
    for off in range(code_start & ~3, code_end - 4, 4):
        w = struct.unpack_from("<I", rom, off)[0]
        if w & 0xFFFF4000 == 0xE92D4000:
            found.setdefault(off, "arm")
        if w & 1 and BASE + code_start <= w - 1 < BASE + code_end:
            found.setdefault(w - 1 - BASE, "thumb")
    return dict(sorted(found.items()))
