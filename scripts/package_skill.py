#!/usr/bin/env python3
"""Build a skill zip whose root contains SKILL.md, with no extra wrapper folder."""
import sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP_FILES = ("SKILL.md", "README.md", "LICENSE")
PACK_DIRS = ("assets", "examples", "references", "scripts")


def iter_skill_files(root=ROOT):
    files = []
    for name in TOP_FILES:
        path = root / name
        if not path.is_file():
            raise SystemExit(f"缺少 {name}，不能打包")
        files.append(path)
    for dirname in PACK_DIRS:
        base = root / dirname
        if not base.is_dir():
            raise SystemExit(f"缺少 {dirname}，不能打包")
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if "/__pycache__/" in f"/{relative}/" or relative.endswith(".pyc"):
                continue
            if relative.startswith("examples/output/"):
                continue
            if path.name.endswith(".partial.mp4"):
                continue
            files.append(path)
    return files


def build_zip(dest, root=ROOT):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    files = iter_skill_files(root)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    return dest


def main():
    if len(sys.argv) != 2:
        raise SystemExit("用法：python3 scripts/package_skill.py 输出.zip")
    dest = build_zip(sys.argv[1])
    with zipfile.ZipFile(dest) as archive:
        names = archive.namelist()
    if "SKILL.md" not in names or names[0] != "SKILL.md":
        raise SystemExit("压缩包根目录没有直接放 SKILL.md")
    print(dest)


if __name__ == "__main__":
    main()
