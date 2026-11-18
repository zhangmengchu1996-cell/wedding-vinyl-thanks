#!/usr/bin/env python3
"""Fresh-unzip acceptance for the two v0.2.2 packages.

Runs real FFmpeg exports. It does not talk to Codex or WorkBuddy.
"""
import hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
ARTIFACTS = Path("/opt/cursor/artifacts")
STARS = "d1c484e47f2008ab2a7d547453c4f4b9329047a800dc6b4e851fe57fa117e4b5"


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise SystemExit(result.stderr[-4000:] or result.stdout[-4000:])
    return result.stdout


def ffmpeg(*args):
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args])


def ffprobe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def write_json(path, payload):
    path = Path(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def psnr(first, second):
    result = subprocess.run(
        ["ffmpeg", "-i", str(first), "-i", str(second), "-lavfi", "psnr", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    marker = "average:"
    text = result.stderr
    start = text.rfind(marker)
    if start < 0:
        raise SystemExit(text[-500:])
    return float(text[start + len(marker):].split()[0])


def frame_at(video, second, dest, box=None, accurate=False):
    # Accurate seeks decode up to the requested time. Fast seeks are for preview stills.
    if accurate:
        args = ["-i", str(video), "-ss", f"{second:.3f}", "-frames:v", "1"]
    else:
        args = ["-ss", f"{second:.3f}", "-i", str(video), "-frames:v", "1"]
    if box:
        args += ["-vf", f"crop={box}"]
    ffmpeg(*args, str(dest))


def render_case(unpack, work, label, silent):
    photo = work / "photo.jpg"
    music = work / "march.m4a"
    if not photo.exists():
        ffmpeg("-f", "lavfi", "-i", "color=c=0x884433:s=640x640", "-frames:v", "1", str(photo))
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=494:duration=3", "-c:a", "aac", str(music))
    lines = {
        "font": FONT,
        "photos": [{"path": str(photo), "focus_x": 0.5, "focus_y": 0.45}],
        "lines": [
            {"text": "谢 幕 答 谢", "heading": True},
            {"text": "2026.06.18"},
            {"text": "新郎 陈一  &  新娘 林二"},
            {"text": "感谢你们到场"},
            {"names": [f"测试亲友{i:02d}" for i in range(1, 41)] + ["测试亲友01"]},
            {"text": "感谢一路相伴"},
        ],
    }
    if silent:
        lines["audio"] = None
        lines["silent"] = True
        utterance = "照片、姓名、婚期、分组名单和感谢文字都齐了，不要音乐"
        state = {
            "intent": "personal", "utterance": utterance, "names": True, "date": True,
            "lists": True, "thanks": True, "confirmed": True,
        }
    else:
        lines["audio"] = str(music)
        utterance = "这是我的照片、姓名、婚期、分组名单和感谢文字，音乐用 march.m4a"
        state = {
            "intent": "personal", "utterance": utterance, "names": True, "date": True,
            "lists": True, "thanks": True, "audio": True, "confirmed": True,
        }
    config = work / f"{label}.json"
    manifest = work / f"{label}-manifest.json"
    out = work / label
    write_json(config, lines)
    write_json(work / f"{label}-state.json", state)
    run([sys.executable, "-X", "utf8", str(unpack / "scripts" / "gate.py"), "manifest",
         "--state", str(work / f"{label}-state.json"), "--config", str(config),
         "--out", str(out), "--manifest", str(manifest), "--width", "1920"])
    run([sys.executable, "-X", "utf8", str(unpack / "scripts" / "render.py"), str(config),
         "--manifest", str(manifest), "--out", str(out), "--width", "1920"])
    video = out / "video.mp4"
    meta = ffprobe(video)
    video_stream = next(item for item in meta["streams"] if item["codec_type"] == "video")
    kinds = [item["codec_type"] for item in meta["streams"]]
    duration = float(meta["format"]["duration"])
    snapshot = json.loads((out / "config.snapshot.json").read_text(encoding="utf-8"))
    if video_stream["width"] != 1920 or video_stream["height"] != 1080:
        raise SystemExit(f"{label} 尺寸不是 1920x1080")
    if abs(duration - snapshot["duration"]) >= 0.2:
        raise SystemExit(f"{label} 时长不符")
    if snapshot["hold_seconds"] != 6:
        raise SystemExit(f"{label} 结尾停留不是 6 秒")
    if silent and "audio" in kinds:
        raise SystemExit(f"{label} 明确静音却有音轨")
    if not silent and "audio" not in kinds:
        raise SystemExit(f"{label} 缺少音轨")
    frames = ARTIFACTS / "v022"
    frames.mkdir(parents=True, exist_ok=True)
    for name, second in (("start", 1), ("middle", duration / 2), ("end", max(0, duration - 0.3))):
        dest = frames / f"{label}-{name}.jpg"
        frame_at(video, second, dest)
    star_a = frames / f"{label}-star-a.png"
    star_b = frames / f"{label}-star-b.png"
    frame_at(video, 1.0, star_a, "480:480:0:0", accurate=True)
    frame_at(video, 1.7, star_b, "480:480:0:0", accurate=True)
    if star_a.read_bytes() == star_b.read_bytes():
        raise SystemExit(f"{label} 左侧星光区域在 0.7 秒内没有变化")
    hold_a = frames / f"{label}-hold-a.png"
    hold_b = frames / f"{label}-hold-b.png"
    frame_at(video, duration - 1.0, hold_a, "700:700:1120:140", accurate=True)
    frame_at(video, duration - 3.0, hold_b, "700:700:1120:140", accurate=True)
    hold_score = psnr(hold_a, hold_b)
    if hold_score < 40:
        raise SystemExit(f"{label} 结尾停留不稳定，文字区域 PSNR {hold_score}")
    moving = frames / f"{label}-moving.png"
    frame_at(video, 10, moving, "700:700:1120:140", accurate=True)
    if snapshot["duration"] > 24 and psnr(moving, hold_b) > 40:
        raise SystemExit(f"{label} 滚动和结尾停留看起来没有区别")
    command = json.loads((out / "command.json").read_text(encoding="utf-8"))
    if "-filter_complex_script" not in command:
        raise SystemExit(f"{label} 在 FFmpeg 6.1 上没有使用原来的滤镜文件参数")
    if "-/filter_complex" in command:
        raise SystemExit(f"{label} 在 FFmpeg 6.1 上误用了 9.0 的参数")
    return {
        "video": str(video),
        "duration": duration,
        "silent": silent,
        "width": video_stream["width"],
        "height": video_stream["height"],
        "streams": kinds,
        "hold_seconds": snapshot["hold_seconds"],
        "scroll_ends_at": snapshot["scroll_ends_at"],
        "stars_sha256": hashlib.sha256((out / "stars.mov").read_bytes()).hexdigest(),
    }


def packaged_negative(unpack, work):
    vague = subprocess.run(
        [sys.executable, "-X", "utf8", str(unpack / "scripts" / "gate.py"), "decide",
         "--state", str(write_json(work / "vague.json", {"utterance": "给我跑一下", "confirmed": True}))],
        capture_output=True, text=True,
    )
    if vague.returncode:
        raise SystemExit(vague.stderr)
    decision = json.loads(vague.stdout)
    if decision["render"] or decision["action"] != "ask_photos":
        raise SystemExit("安装包里的「给我跑一下」仍然会导出")
    checked = subprocess.run(
        [sys.executable, "-X", "utf8", str(unpack / "scripts" / "check_environment.py"), "--details"],
        capture_output=True, text=True,
    )
    if checked.returncode:
        raise SystemExit(checked.stderr)
    payload = json.loads(checked.stdout)
    if payload["rendered"] or "video" in payload:
        raise SystemExit("依赖检查导出了视频")
    return {"vague_action": decision["action"], "ffmpeg_version": payload["ffmpeg_version"], "ffmpeg_9_executed": payload["ffmpeg_9_executed"]}


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    codex_zip = ARTIFACTS / "wedding-vinyl-thanks-codex-v0.2.2.zip"
    workbuddy_zip = ARTIFACTS / "wedding-vinyl-thanks-workbuddy-v0.2.2.zip"
    sys.path.insert(0, str(ROOT / "scripts"))
    from package_skill import build
    build(codex_zip, ROOT / "SKILL.md", ["README.md"])
    build(workbuddy_zip, ROOT / "packaging" / "workbuddy" / "SKILL.md")
    report = {"ffmpeg": run(["ffmpeg", "-version"]).splitlines()[0], "packages": {}}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, archive in (("codex", codex_zip), ("workbuddy", workbuddy_zip)):
            unpack = root / name
            unpack.mkdir()
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(unpack)
                names = zipped.namelist()
            if names[0] != "SKILL.md" or not (unpack / "SKILL.md").is_file():
                raise SystemExit(name + " 解压后根目录不是 SKILL.md")
            stars = hashlib.sha256((unpack / "assets" / "stars.mov").read_bytes()).hexdigest()
            if stars != STARS:
                raise SystemExit(name + " 星光素材变了")
            work = root / (name + "-work")
            work.mkdir()
            negative = packaged_negative(unpack, work)
            music = render_case(unpack, work, name + "-music", silent=False)
            silence = render_case(unpack, work, name + "-silence", silent=True)
            report["packages"][name] = {"negative": negative, "music": music, "silence": silence, "zip_entries": len(names)}
    log = ARTIFACTS / "v022-acceptance-log.txt"
    log.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(log)
    print(codex_zip)
    print(workbuddy_zip)


if __name__ == "__main__":
    main()
