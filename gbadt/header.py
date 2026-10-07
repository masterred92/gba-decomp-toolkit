"""GBA cartridge header parsing and ROM identity checks."""
import hashlib, struct

# CRC of the 156-byte boot logo; we store a hash so we never ship the logo bytes.
LOGO_SHA1 = None  # filled lazily from verified homebrew (logo is required by BIOS)

def complement(rom: bytes) -> int:
    return (-(sum(rom[0xA0:0xBD]) + 0x19)) & 0xFF

def parse(rom: bytes) -> dict:
    if len(rom) < 0xC0:
        raise ValueError("file too small to be a GBA ROM")
    entry = struct.unpack_from("<I", rom, 0)[0]
    h = {
        "title": rom[0xA0:0xAC].rstrip(b"\0").decode("ascii", "replace"),
        "game_code": rom[0xAC:0xB0].decode("ascii", "replace"),
        "maker": rom[0xB0:0xB2].decode("ascii", "replace"),
        "fixed_96h": rom[0xB2],
        "version": rom[0xBC],
        "complement": rom[0xBD],
        "complement_ok": rom[0xBD] == complement(rom),
        "entry_is_branch": (entry >> 24) == 0xEA,
        "entry_target": 0x08000000 + 8 + ((entry & 0xFFFFFF) << 2) if (entry >> 24) == 0xEA else None,
        "size": len(rom),
        "sha1": hashlib.sha1(rom).hexdigest(),
    }
    h["looks_valid"] = h["fixed_96h"] == 0x96 and h["complement_ok"] and h["entry_is_branch"]
    return h

def fix_header(rom: bytearray) -> bytearray:
    """gbafix-equivalent: set fixed byte and complement check (for homebrew builds)."""
    rom[0xB2] = 0x96
    rom[0xBD] = complement(rom)
    return rom
