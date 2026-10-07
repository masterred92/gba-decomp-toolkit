"""Heuristic Thumb/ARM function discovery.

Tutor's note: a ROM has no labels, so we look for clues that say "a function starts here".
Some clues are strong, some are weak:

  strong  * the ROM entry branch target (ARM)
          * Thumb BL targets: someone *calls* this address
          * Thumb pointers (addr|1) sitting in literal pools: someone takes its address
  weak    * prologues: Thumb PUSH {.., LR} (0xB5xx), ARM STMFD SP!, {.., LR}
  derived * "after-end": once we know where a function ENDS (its last return plus the
            literal pool it reads), the next real instruction is usually a new function.

To find ends we *sweep*: decode instructions from a start, remember the furthest forward
branch target and every literal-pool word that LDR [PC] reads, and stop at a return
(bx / pop {pc} / mov pc / unconditional b) once nothing jumps past it and no pool we read lies
further ahead. Then skip the pool and zero/nop padding.

Two things this fixes compared with "every PUSH is a function":
  * small leaf functions with no PUSH at all (e.g. `bx lr` helpers) are found after-end;
  * compilers sometimes schedule a few instructions *before* the PUSH. A PUSH that sits
    inside a function we already swept is ignored instead of splitting it in two.

Still a heuristic: data inside the code region can look like code, and compilers that share
literal pools between functions (ARM ADS) or use jump tables in unusual ways can confuse it.
Real projects refine with Ghidra/luvdis and by hand.
"""
import struct
BASE = 0x08000000
PTR_TOPS = (0x02, 0x03, 0x08, 0x09)   # EWRAM, IWRAM, ROM: addresses that move between builds


def _sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def sweep(rom: bytes, start: int, mode: str, limit_end: int, stops=()):
    """Decode one function from `start`. Returns (end, pools, ok).

    end   = offset just past the function's code, its literal pool and padding
    pools = set of offsets of 4-byte literal-pool words the function reads
    ok    = True if we reached a proper return before running off the end / into `stops`
    """
    pools, far, pc = set(), start, start
    step = 2 if mode == "thumb" else 4
    while pc + step <= limit_end:
        if pc != start and pc in stops:
            return pc, pools, False
        if pc in pools:
            pc += 4; continue
        term = False
        if mode == "thumb":
            hw = struct.unpack_from("<H", rom, pc)[0]
            nxt = struct.unpack_from("<H", rom, pc + 2)[0] if pc + 4 <= limit_end else 0
            if hw & 0xF800 == 0x4800:                       # LDR Rd, [PC, #imm8*4]
                pools.add(((pc + 4) & ~3) + (hw & 0xFF) * 4)
            elif hw & 0xF000 == 0xD000 and (hw >> 8) & 0xF < 0xE:   # B<cond>
                far = max(far, pc + 4 + _sext(hw & 0xFF, 8) * 2)
            elif hw & 0xF800 == 0xE000:                     # B (unconditional)
                tgt = pc + 4 + _sext(hw & 0x7FF, 11) * 2
                far = max(far, tgt)
                term = True
            elif hw & 0xF800 == 0xF000 and nxt & 0xF800 == 0xF800:  # BL pair: a call
                pc += 4; continue
            elif hw & 0xFF87 == 0x4700:                     # BX Rm
                term = True
            elif hw & 0xFF00 == 0xBD00:                     # POP {.., PC}
                term = True
            elif hw & 0xFF87 == 0x4687:                     # MOV PC, Rm (jump table / return)
                term = True
                # agbcc-style switch: a word-aligned table of 0x08xxxxxx case addresses follows
                t = (pc + 2 + 3) & ~3
                while t + 4 <= limit_end:
                    w = struct.unpack_from("<I", rom, t)[0]
                    if w >> 24 not in (0x08, 0x09) or w & 1 or not (pc < w - BASE < pc + 0x10000):
                        break
                    pools.add(t); far = max(far, w - BASE); t += 4
        else:
            w = struct.unpack_from("<I", rom, pc)[0]
            cond = w >> 28
            if w & 0x0F7F0000 == 0x051F0000:                # LDR Rd, [PC, #+/-imm12]
                off = w & 0xFFF
                pools.add(pc + 8 + (off if w & (1 << 23) else -off))
                if (w >> 12) & 0xF == 15 and cond == 0xE:
                    term = True                             # LDR PC, [...]
            elif (w >> 25) & 7 == 5:                        # B / BL
                if not w & (1 << 24):
                    tgt = pc + 8 + _sext(w & 0xFFFFFF, 24) * 4
                    far = max(far, tgt)
                    term = cond == 0xE
            elif w & 0x0FFFFFF0 == 0x012FFF10 and cond == 0xE:   # BX Rm
                term = True
            elif w & 0x0FFF8000 == 0x08BD8000 and cond == 0xE:   # LDMFD SP!, {.., PC}
                term = True
            elif w & 0x0FFFFFF0 == 0x01A0F000 and cond == 0xE:   # MOV PC, Rm
                term = True
        pc += step
        if term and pc > far:
            # A literal pool this function reads that lies further ahead means the function
            # isn't over yet (e.g. switch cases reached only through a jump table), unless
            # everything up to that pool is padding.
            ahead = [p for p in pools if p >= pc]
            if ahead and any(struct.unpack_from("<H", rom, o)[0] not in (0, 0x46C0)
                             for o in range(pc, min(min(ahead), limit_end - 1), 2)):
                continue
            end = pc
            while True:                                     # skip pool words + padding
                if end in pools and end + 4 <= limit_end:
                    end += 4
                elif end + 2 <= limit_end and struct.unpack_from("<H", rom, end)[0] == 0 \
                        and end not in stops:
                    end += 2
                elif mode == "thumb" and end % 4 == 2 and end + 2 <= limit_end \
                        and struct.unpack_from("<H", rom, end)[0] == 0x46C0:
                    end += 2                                # nop used as alignment
                else:
                    break
            return end, pools, True
    return min(pc, limit_end), pools, False


def _guess_mode(rom, off, end):
    """ARM words almost always have condition 0xE (always) in their top nibble."""
    if off % 4:
        return "thumb"
    words = [struct.unpack_from("<I", rom, o)[0] for o in range(off, min(off + 16, end - 3), 4)]
    return "arm" if words and sum(w >> 28 == 0xE for w in words) >= max(1, len(words) - 1) else "thumb"


def _signals(rom, code_start, code_end):
    strong, weak = {}, {}
    entry = struct.unpack_from("<I", rom, 0)[0]
    if entry >> 24 == 0xEA:
        strong[8 + ((entry & 0xFFFFFF) << 2)] = ("arm", "entry")
    for off in range(code_start, code_end - 4, 2):
        hw, hw2 = struct.unpack_from("<HH", rom, off)
        if hw & 0xFF00 == 0xB500:
            weak.setdefault(off, ("thumb", "push"))
        if hw & 0xF800 == 0xF000 and hw2 & 0xF800 == 0xF800:
            tgt = off + 4 + (_sext(hw & 0x7FF, 11) << 12) + ((hw2 & 0x7FF) << 1)
            if code_start <= tgt < code_end:
                strong.setdefault(tgt, ("thumb", "bl"))
    for off in range(code_start & ~3, code_end - 4, 4):
        w = struct.unpack_from("<I", rom, off)[0]
        if w & 0xFFFF4000 == 0xE92D4000:
            weak.setdefault(off, ("arm", "stmfd"))
        if w & 1 and BASE + code_start <= w - 1 < BASE + code_end:
            strong.setdefault(w - 1 - BASE, ("thumb", "pointer"))
    return strong, weak


def discover_detailed(rom: bytes, code_start: int, code_end: int) -> dict:
    """offset -> {"mode", "why", "end"}; `end` is the swept end (None if the sweep gave up)."""
    strong, weak = _signals(rom, code_start, code_end)
    found = {}
    covered = []                      # (start, end) of cleanly swept functions
    stops = set(strong)
    queue = [(0, o, m, why) for o, (m, why) in strong.items()]
    queue += [(2, o, m, why) for o, (m, why) in weak.items() if o not in strong]

    def inside(o):
        return any(a < o < b for a, b in covered)

    while queue:
        queue.sort()
        prio, off, mode, why = queue.pop(0)
        if off in found or not (code_start <= off < code_end):
            continue
        if prio > 0 and inside(off):  # weak/derived start inside a known function: drop it
            continue
        end, _, ok = sweep(rom, off, mode, code_end, stops)
        if prio == 1 and not ok:      # after-end guess that never returns: probably data
            continue
        found[off] = {"mode": mode, "why": why, "end": end if ok else None}
        if ok:
            covered.append((off, end))
            if end < code_end and end not in found:
                queue.append((1, end, _guess_mode(rom, end, code_end), "after-end"))
    return dict(sorted(found.items()))


def discover(rom: bytes, code_start: int, code_end: int) -> dict:
    """offset -> mode ("thumb"/"arm")."""
    return {o: d["mode"] for o, d in discover_detailed(rom, code_start, code_end).items()}
