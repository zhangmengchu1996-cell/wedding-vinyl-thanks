#!/usr/bin/env python3
"""Read-only readiness check. Does not install software, replace binaries, or render."""
import argparse, json, os, platform, re, shutil, subprocess, sys
from pathlib import Path

def binary(name):
    found = os.environ.get(name.upper()) or shutil.which(name)
    if found:
        return found
    bundled = Path("/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static") / name
    if bundled.exists():
        return str(bundled)
    raise ValueError("找不到 " + name + "；请安装或设置 " + name.upper() + "。不要覆盖系统里已有的程序。")

def font_candidates(explicit):
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    stock = [
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        windows / "Fonts/simsun.ttc",
        windows / "Fonts/msyh.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    ]
    if explicit:
        return [Path(explicit).expanduser()]
    return stock

def check(font=None):
    errors = []
    result = {
        "system": platform.system(),
        "python": sys.version.split()[0],
        "template_version": "0.2.2",
        "rendered": False,
        "errors": errors,
        "support": "只记录这次实际启动的 FFmpeg。不下载二进制，也不改系统工具。",
    }
    if sys.version_info < (3, 9):
        errors.append("需要 Python 3.9 或更新版本")
    for name in ("ffmpeg", "ffprobe"):
        try:
            program = binary(name)
            run = subprocess.run([program, "-version"], capture_output=True, text=True, timeout=10)
            if run.returncode:
                raise ValueError("程序不能正常启动")
            result[name] = program
            if name == "ffmpeg":
                result["ffmpeg_version"] = (run.stdout or "").splitlines()[0]
        except Exception as exc:
            errors.append(name + ": " + str(exc))
    if "ffmpeg" in result:
        version = result.get("ffmpeg_version", "")
        match = re.search(r"version\s+n?(\d+)\.", version)
        major = int(match.group(1)) if match else None
        result["ffmpeg_major"] = major
        result["filter_file_option"] = "-/filter_complex" if major is not None and major >= 9 else "-filter_complex_script"
        result["ffmpeg_9_executed"] = False
        if major is not None and major >= 9:
            result["ffmpeg_9_note"] = "当前启动的是 FFmpeg 9 或更新版本。复杂滤镜改从文件读取的新写法加载，画面参数不变。"
        else:
            result["ffmpeg_9_note"] = (
                "FFmpeg 9.0 移除了 -filter_complex_script（官方提交 07407ff，位于 n8.1 与 n9.0 之间）。"
                "本环境这次启动的不是 9.0；没有从未知来源下载 9.0，所以不能把 9.0 说成已经跑通。"
            )
        for arg, required in (
            ("-filters", ["drawtext", "geq", "rotate", "overlay", "scale", "crop", "afade", "format", "colorchannelmixer"]),
            ("-encoders", ["libx264", "aac", "png"]),
            ("-decoders", ["qtrle"]),
        ):
            try:
                run = subprocess.run([result["ffmpeg"], arg], capture_output=True, text=True, timeout=10)
                if run.returncode:
                    raise ValueError("无法查询功能")
                for item in required:
                    if not re.search(r"\b" + item + r"\b", run.stdout):
                        errors.append("视频工具缺少 " + item)
            except Exception as exc:
                errors.append(str(exc))
    found = next((str(path.resolve()) for path in font_candidates(font) if path.is_file()), None)
    result["font"] = found
    if not found:
        errors.append("未找到中文字体。请指定本机已安装的字体路径，不要改用示例视频。")
    assets = Path(__file__).resolve().parent.parent / "assets"
    for name in ("record.png", "wave.png", "stars.mov"):
        if not (assets / name).is_file():
            errors.append("缺少效果素材 " + name + "。请换完整技能包，不要用别的图形顶替。")
    result["ready"] = not errors
    result["changed_system"] = False
    result["removed_quarantine"] = False
    result["signed_binaries"] = False
    result["technical"] = {
        "ffmpeg": result.get("ffmpeg"),
        "ffprobe": result.get("ffprobe"),
        "ffmpeg_version": result.get("ffmpeg_version"),
        "ffmpeg_major": result.get("ffmpeg_major"),
        "font": found,
        "ffmpeg_9_note": result.get("ffmpeg_9_note"),
    }
    if errors:
        result["user_message"] = "这台电脑还不能做视频：" + "；".join(errors)
    else:
        result["user_message"] = "运行环境已就绪。"
    result["note"] = "平时只把 user_message 告诉用户。路径和版本留在 technical 里，出错或用户追问再说明。不要为此签名、去隔离或安装软件。"
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="只检查依赖，不导出视频。")
    parser.add_argument("--font")
    parser.add_argument("--details", action="store_true", help="打印技术字段。平时不要把这些内容发给用户。")
    args = parser.parse_args()
    result = check(args.font)
    if result["ready"] and not args.details:
        print(result["user_message"])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ready"] else 1)
