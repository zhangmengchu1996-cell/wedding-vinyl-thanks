#!/usr/bin/env python3
"""Build the Codex and WorkBuddy zips. Each archive root is SKILL.md."""
import sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = [
    "LICENSE",
    "references/workflow.md",
    "references/config.md",
    "references/effects.md",
    "scripts/render.py",
    "scripts/layout.py",
    "scripts/gate.py",
    "scripts/check_environment.py",
    "assets/record.png",
    "assets/stars.mov",
    "assets/wave.png",
]


def build(dest, skill, extra=()):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    files = [Path(skill)] + [ROOT / item for item in SHARED] + [ROOT / item for item in extra]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise SystemExit("缺少文件：" + "、".join(missing))
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(skill, "SKILL.md")
        for path in files[1:]:
            archive.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(dest) as archive:
        names = archive.namelist()
    if names[0] != "SKILL.md":
        raise SystemExit("压缩包根目录没有直接放 SKILL.md")
    if any(name.startswith(("examples/", "scripts/test_", "scripts/accept_")) for name in names):
        raise SystemExit("安装包混入了开发者示例或测试脚本")
    return dest


def main():
    if len(sys.argv) != 3:
        raise SystemExit("用法：python3 scripts/package_skill.py Codex输出.zip WorkBuddy输出.zip")
    codex = build(sys.argv[1], ROOT / "SKILL.md", ["README.md"])
    workbuddy = build(sys.argv[2], ROOT / "packaging" / "workbuddy" / "SKILL.md")
    print(codex)
    print(workbuddy)


if __name__ == "__main__":
    main()
