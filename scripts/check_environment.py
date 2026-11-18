#!/usr/bin/env python3
"""Read-only readiness check. Does not install software, replace binaries, or render."""
import argparse, json, os, platform, re, shutil, subprocess, sys
from pathlib import Path

def official_directories():
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin")]
    if system == "Windows":
        program = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        return [program / "ffmpeg" / "bin", home / "scoop" / "shims"]
    return [Path("/usr/bin"), Path("/usr/local/bin"), home / ".local" / "bin"]

def candidate_paths(name):
    paths = []
    env = os.environ.get(name.upper())
    if env:
        paths.append(Path(env))
    found = shutil.which(name)
    if found:
        paths.append(Path(found))
    paths.extend(directory / name for directory in official_directories())
    unique = []
    seen = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique

def probe_executable(path):
    """Read-only. Classifies one file. Does not install, sign, or change quarantine."""
    path = Path(path)
    record = {"path": str(path), "assert_system_block": False}
    if not path.exists():
        record["status"] = "not_found"
        return record
    if not os.access(path, os.X_OK):
        record["status"] = "not_executable"
        return record
    try:
        run = subprocess.run([str(path), "-version"], capture_output=True, text=True, timeout=10)
    except PermissionError as exc:
        record["status"] = "permission"
        record["detail"] = str(exc)[:200]
        return record
    except OSError as exc:
        record["status"] = "crashed"
        record["detail"] = str(exc)[:200]
        return record
    if run.returncode != 0:
        record["status"] = "crashed"
        record["detail"] = ((run.stderr or run.stdout or "")[:300])
        lowered = record["detail"].lower()
        record["assert_system_block"] = "quarantine" in lowered
        return record
    version = (run.stdout or "").splitlines()
    line = version[0] if version else ""
    if "version" not in line.lower():
        record["status"] = "crashed"
        record["detail"] = line[:200]
        return record
    record["status"] = "ok"
    record["version"] = line
    return record

def locate_tool(name):
    checked = [probe_executable(path) for path in candidate_paths(name)]
    ok = next((item for item in checked if item["status"] == "ok"), None)
    if ok:
        return {"name": name, "status": "ok", "path": ok["path"], "version": ok.get("version", ""), "checked": checked, "assert_system_block": False}
    worst = next((item for item in checked if item["status"] != "not_found"), None)
    status = worst["status"] if worst else "not_found"
    return {
        "name": name,
        "status": status,
        "path": worst["path"] if worst else "",
        "detail": (worst or {}).get("detail", ""),
        "checked": checked,
        "assert_system_block": bool((worst or {}).get("assert_system_block")),
    }

def binary(name):
    found = locate_tool(name)
    if found["status"] == "ok":
        return found["path"]
    raise ValueError(tool_status_text(found) + " 不要覆盖系统里已有的程序。")

def tool_status_text(found):
    status = found.get("status")
    if status == "not_found":
        return "还没在命令路径或常见安装位置找到能运行的 " + found.get("name", "程序")
    if status == "not_executable":
        return "找到了 " + found.get("name", "程序") + "，但当前不能执行"
    if status == "permission":
        return "找到了 " + found.get("name", "程序") + "，但当前环境没有运行权限"
    if status == "crashed":
        if found.get("assert_system_block"):
            return found.get("name", "程序") + " 启动失败，记录里提到了隔离限制"
        return found.get("name", "程序") + " 实际运行没有成功。没有隔离或拦截记录时，不能说是系统拦住了它"
    return found.get("name", "程序") + " 还不能用"

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
        "template_version": "0.2.3",
        "rendered": False,
        "errors": errors,
        "support": "只记录这次实际启动的 FFmpeg。不下载二进制，也不改系统工具。",
    }
    if sys.version_info < (3, 9):
        errors.append("需要 Python 3.9 或更新版本")
    probes = {}
    for name in ("ffmpeg", "ffprobe"):
        found = locate_tool(name)
        probes[name] = found
        if found["status"] == "ok":
            result[name] = found["path"]
            if name == "ffmpeg":
                result["ffmpeg_version"] = found.get("version", "")
        else:
            errors.append(tool_status_text(found))
    result["probes"] = probes
    other_app = Path("/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static/ffmpeg")
    result["other_app_bundle_present"] = other_app.exists()
    result["other_app_bundle_used"] = False
    if "ffmpeg" in result:
        version = result.get("ffmpeg_version", "")
        match = re.search(r"version\s+n?(\d+)\.", version)
        major = int(match.group(1)) if match else None
        result["ffmpeg_major"] = major
        result["filter_file_option"] = "-/filter_complex" if major is not None and major >= 7 else "-filter_complex_script"
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
        install = ""
        if probes.get("ffmpeg", {}).get("status") == "not_found":
            install = "如果你愿意，我可以在你同意后按 FFmpeg 官网的方式协助安装。我不会自己装。"
        result["user_message"] = "这里暂时不能导出：" + "；".join(errors) + "。" + install + "可以先发要放进唱片里的照片。"
        result["assert_system_block"] = any(item.get("assert_system_block") for item in probes.values())
    else:
        result["user_message"] = "运行环境已就绪。"
        result["assert_system_block"] = False
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
