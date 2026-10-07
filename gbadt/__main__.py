import argparse, json, sys
from . import header, scaffold, match

def main():
    ap = argparse.ArgumentParser(prog="gbadt", description="GBA matching-decomp scaffold generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="parse header + SHA1"); p.add_argument("rom")
    p.add_argument("--expect-sha1")
    p = sub.add_parser("init", help="create project from ROM"); p.add_argument("rom"); p.add_argument("out")
    p.add_argument("--code-end", type=lambda x: int(x, 0))
    sub.add_parser("match", help="compile C and compare against a function", add_help=False)
    a, rest = ap.parse_known_args()
    if a.cmd == "info":
        h = header.parse(open(a.rom, "rb").read()); print(json.dumps(h, indent=1))
        if a.expect_sha1 and h["sha1"] != a.expect_sha1.lower():
            sys.exit("SHA1 mismatch: wrong ROM revision or bad dump")
    elif a.cmd == "init":
        import os, shutil
        cfg = scaffold.generate(a.rom, a.out, a.code_end)
        shutil.copyfile(a.rom, os.path.join(a.out, "baserom.gba"))
        n = sum(1 for s in cfg["segments"] if s["kind"] == "code")
        print(f"project at {a.out}: {n} functions, {len(cfg['segments'])} segments. Run: make -C {a.out}")
    elif a.cmd == "match":
        sys.exit(match.main(rest))
main()
