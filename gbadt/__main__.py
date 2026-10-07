import argparse, json, sys
from . import header, scaffold, match, symbols, signatures

def main():
    ap = argparse.ArgumentParser(prog="gbadt", description="GBA matching-decomp scaffold generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="parse header + SHA1"); p.add_argument("rom")
    p.add_argument("--expect-sha1")
    p = sub.add_parser("init", help="create project from ROM"); p.add_argument("rom"); p.add_argument("out")
    p.add_argument("--code-end", type=lambda x: int(x, 0))
    p.add_argument("--compiler", default="agbcc", help="compiler profile (compilers/profiles.json), e.g. gcc-2.96-patched")
    p.add_argument("--mode", choices=scaffold.MODES, help="match (default for matching profiles), asm-only or notes-only (no-matching profiles like ads12 default to their own default_mode)")
    p = sub.add_parser("import-symbols", help="rename functions from a sibling symbol list")
    p.add_argument("project"); p.add_argument("symfile")
    p.add_argument("--offset", type=lambda x: int(x, 0), default=0, help="add to every symbol address")
    p = sub.add_parser("signatures", help="fingerprint functions (addresses masked) to find them in another ROM")
    ss = p.add_subparsers(dest="sigcmd", required=True)
    q = ss.add_parser("build", help="write signatures for every function in a project")
    q.add_argument("project"); q.add_argument("-o", "--out")
    q = ss.add_parser("match", help="pair a named signature set with a target; prints import-symbols input")
    q.add_argument("lib", help=".sigs file or named project"); q.add_argument("target", help="project or .sigs")
    q.add_argument("-o", "--out"); q.add_argument("--min-size", type=int, default=8, help="skip functions shorter than this (bytes)")
    q.add_argument("--include-unnamed", action="store_true", help="also transfer sub_XXXXXXXX names")
    q = ss.add_parser("show", help="hex dump of one function with masked bytes as ..")
    q.add_argument("project"); q.add_argument("func")
    sub.add_parser("compilers", help="list compiler profiles")
    sub.add_parser("match", help="compile C and compare against a function", add_help=False)
    a, rest = ap.parse_known_args()
    if a.cmd == "info":
        h = header.parse(open(a.rom, "rb").read()); print(json.dumps(h, indent=1))
        if a.expect_sha1 and h["sha1"] != a.expect_sha1.lower():
            sys.exit("SHA1 mismatch: wrong ROM revision or bad dump")
    elif a.cmd == "init":
        import os, shutil
        match.load_profile(a.compiler)  # validate name early
        meta = match.profile_meta(a.compiler)
        mode = a.mode or ("match" if meta.get("matching", True) else meta.get("default_mode", "asm-only"))
        if mode == "match" and not meta.get("matching", True):
            sys.exit(f"profile {a.compiler} can't do matching: {meta.get('source', '')}. Use --mode asm-only or notes-only.")
        cfg = scaffold.generate(a.rom, a.out, a.code_end, compiler=a.compiler, mode=mode)
        n = sum(1 for s in cfg["segments"] if s["kind"] == "code")
        if mode == "notes-only":
            print(f"notes-only project at {a.out}: {n} functions listed in {a.out}/notes/functions.md (ROM read in place, not copied)")
        else:
            shutil.copyfile(a.rom, os.path.join(a.out, "baserom.gba"))
            extra = " Matching is off; document functions in notes/functions.md." if mode == "asm-only" else ""
            print(f"project at {a.out}: {n} functions, {len(cfg['segments'])} segments. Run: make -C {a.out}.{extra}")
    elif a.cmd == "import-symbols":
        r = symbols.apply(a.project, open(a.symfile).read(), a.offset)
        for o, n in r["renamed"]: print(f"renamed {o} -> {n}")
        print(f"{len(r['renamed'])} renamed, {len(r['unmatched'])} symbols had no matching function start")
    elif a.cmd == "signatures":
        if a.sigcmd == "build":
            txt = signatures.dump(signatures.build(a.project), a.project)
            open(a.out, "w").write(txt) if a.out else sys.stdout.write(txt)
            if a.out: print(f"wrote {txt.count(chr(10)) - 2} signatures to {a.out}")
        elif a.sigcmd == "match":
            hits, st = signatures.match(signatures.load(a.lib), signatures.load(a.target), a.min_size, a.include_unnamed)
            txt = "# gbadt signatures match: feed to `gbadt import-symbols <project> <this file>`\n"
            txt += "".join(f"0x{t:08X} {n}  # sig {s}, {z}B, was 0x{la:08X}\n" for t, n, s, z, la in hits)
            open(a.out, "w").write(txt) if a.out else sys.stdout.write(txt)
            print(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in st.items()), file=sys.stderr)
        else:
            print(signatures.show(a.project, a.func))
    elif a.cmd == "compilers":
        profs = json.load(open(match.PROFILES))
        for k, v in profs.items():
            if k.startswith("_"): continue
            cc = v["cc"] or f"(no matching: {v.get('default_mode', 'asm-only')} / notes-only)"
            print(f"{k:20} {cc}\n{'':20} from: {v['source']}")
    elif a.cmd == "match":
        sys.exit(match.main(rest))
main()
