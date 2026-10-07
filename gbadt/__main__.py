import argparse, json, sys
from . import header, scaffold, match, symbols

def main():
    ap = argparse.ArgumentParser(prog="gbadt", description="GBA matching-decomp scaffold generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="parse header + SHA1"); p.add_argument("rom")
    p.add_argument("--expect-sha1")
    p = sub.add_parser("init", help="create project from ROM"); p.add_argument("rom"); p.add_argument("out")
    p.add_argument("--code-end", type=lambda x: int(x, 0))
    p.add_argument("--compiler", default="agbcc", help="compiler profile (compilers/profiles.json), e.g. gcc-2.96-patched")
    p = sub.add_parser("import-symbols", help="rename functions from a sibling symbol list")
    p.add_argument("project"); p.add_argument("symfile")
    p.add_argument("--offset", type=lambda x: int(x, 0), default=0, help="add to every symbol address")
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
        cfg = scaffold.generate(a.rom, a.out, a.code_end, compiler=a.compiler)
        shutil.copyfile(a.rom, os.path.join(a.out, "baserom.gba"))
        n = sum(1 for s in cfg["segments"] if s["kind"] == "code")
        print(f"project at {a.out}: {n} functions, {len(cfg['segments'])} segments. Run: make -C {a.out}")
    elif a.cmd == "import-symbols":
        r = symbols.apply(a.project, open(a.symfile).read(), a.offset)
        for o, n in r["renamed"]: print(f"renamed {o} -> {n}")
        print(f"{len(r['renamed'])} renamed, {len(r['unmatched'])} symbols had no matching function start")
    elif a.cmd == "compilers":
        profs = json.load(open(match.PROFILES))
        for k, v in profs.items():
            if not k.startswith("_"): print(f"{k:20} {v['cc']}\n{'':20} from: {v['source']}")
    elif a.cmd == "match":
        sys.exit(match.main(rest))
main()
