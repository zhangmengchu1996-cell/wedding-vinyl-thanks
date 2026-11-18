#!/usr/bin/env python3
"""1080p memory proof for one unpacked skill directory.

Uses four generated stills and a long fictional Chinese list. Records peak
RSS from the renderer's own memory.json. Not a Codex or WorkBuddy session.
"""
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
NAMES = [f"测试亲友{i:02d}" for i in range(1, 41)] + ["测试亲友01"]


def run(cmd, env=None):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    if result.returncode:
        raise SystemExit(result.stderr[-2500:] or result.stdout[-2500:])
    return result.stdout


def ffmpeg(*args):
    ff = os.environ.get("FFMPEG", "ffmpeg")
    run([ff, "-y", "-hide_banner", "-loglevel", "error", *args])


def ffprobe(path):
    probe = os.environ.get("FFPROBE", "ffprobe")
    return json.loads(run([probe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def main():
    if len(sys.argv) != 4:
        raise SystemExit("用法：prove_memory.py 解压目录 输出目录 标签")
    unpack, out_root, label = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    out_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["WEDDING_VINYL_RSS_LIMIT_MIB"] = os.environ.get("WEDDING_VINYL_RSS_LIMIT_MIB", "4096")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        photos = []
        for index, color in enumerate(("0x884433", "0x335588", "0x558833", "0x883355")):
            path = work / f"p{index}.jpg"
            ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=1200x1200", "-frames:v", "1", str(path))
            photos.append(path)
        music = work / "INTERNAL-ACCEPTANCE-TEST-TONE-NOT-CLIENT-BGM.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(music))
        report = {"label": label, "ffmpeg": run([env.get("FFMPEG", "ffmpeg"), "-version"]).splitlines()[0], "cases": []}
        for silent in (False, True):
            name = label + ("-silent" if silent else "-music")
            config = {
                "font": FONT,
                "photos": [{"path": str(path), "focus_x": 0.5, "focus_y": 0.45} for path in photos],
                "lines": [
                    {"text": "谢 幕 答 谢", "heading": True},
                    {"text": "2026.06.18"},
                    {"text": "新郎 陈一  &  新娘 林二"},
                    {"text": "感谢你们到场"},
                    {"names": NAMES},
                    {"text": "感谢一路相伴"},
                ],
            }
            if silent:
                config["audio"] = None
                config["silent"] = True
                utterance = "照片、姓名、婚期、分组名单和感谢文字都齐了，不要音乐"
            else:
                config["audio"] = str(music)
                utterance = "这是我的照片、姓名、婚期、分组名单和感谢文字，音乐用测试音"
            case = work / name
            case.mkdir()
            cfg_path = case / "config.json"
            state_path = case / "state.json"
            manifest_path = case / "manifest.json"
            out = case / "out"
            cfg_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            state_path.write_text(json.dumps({
                "intent": "personal", "utterance": utterance, "names": True, "date": True,
                "lists": True, "thanks": True, "audio": not silent, "confirmed": True,
            }, ensure_ascii=False), encoding="utf-8")
            py = sys.executable
            run([py, "-X", "utf8", str(unpack / "scripts" / "gate.py"), "manifest",
                 "--state", str(state_path), "--config", str(cfg_path),
                 "--out", str(out), "--manifest", str(manifest_path), "--width", "1920"], env)
            run([py, "-X", "utf8", str(unpack / "scripts" / "render.py"), str(cfg_path),
                 "--manifest", str(manifest_path), "--out", str(out), "--width", "1920"], env)
            video = out / "video.mp4"
            if not video.is_file():
                raise SystemExit(name + " 没有完整的 video.mp4")
            if (out / "video.partial.mp4").exists():
                raise SystemExit(name + " 仍留着半成品")
            meta = ffprobe(video)
            video_stream = next(item for item in meta["streams"] if item["codec_type"] == "video")
            kinds = [item["codec_type"] for item in meta["streams"]]
            duration = float(meta["format"]["duration"])
            snapshot = json.loads((out / "config.snapshot.json").read_text(encoding="utf-8"))
            memory = json.loads((out / "memory.json").read_text(encoding="utf-8"))
            command = json.loads((out / "command.json").read_text(encoding="utf-8"))
            if video_stream["width"] != 1920 or video_stream["height"] != 1080:
                raise SystemExit(name + " 不是 1920x1080")
            if abs(duration - snapshot["duration"]) >= 0.2:
                raise SystemExit(name + " 时长不符")
            if snapshot.get("hold_seconds") != 6 or snapshot["duration"] - snapshot["scroll_ends_at"] < 6:
                raise SystemExit(name + " 结尾停留不足 6 秒")
            if silent and "audio" in kinds:
                raise SystemExit(name + " 静音成片仍有音轨")
            if not silent and "audio" not in kinds:
                raise SystemExit(name + " 缺少音轨")
            if memory["peak_rss_kib"] > 3584 * 1024:
                raise SystemExit(name + f" 内存峰值过高：{memory['peak_rss_kib']}")
            if "-stream_loop" in command:
                idx = command.index("-stream_loop")
                if command[idx:idx + 4] != ["-stream_loop", "-1", "-t", str(snapshot["duration"])]:
                    # duration may be formatted as 20.0 vs 20
                    if command[idx + 1] != "-1" or command[idx + 2] != "-t":
                        raise SystemExit(name + " 星光输入没有时长上限")
            frames = out_root / name
            frames.mkdir(parents=True, exist_ok=True)
            shutil_video = frames / "video.mp4"
            shutil_video.write_bytes(video.read_bytes())
            for frame_name, second in (("start", 1), ("middle", duration / 2), ("end", max(0, duration - 0.3))):
                ffmpeg("-i", str(video), "-ss", f"{second:.3f}", "-frames:v", "1", str(frames / f"{frame_name}.jpg"))
            star_a, star_b = frames / "star-a.png", frames / "star-b.png"
            for dest, second in ((star_a, 1.0), (star_b, 1.7)):
                ffmpeg("-i", str(video), "-ss", f"{second:.3f}", "-frames:v", "1", "-vf", "crop=480:480:0:0", str(dest))
            if star_a.read_bytes() == star_b.read_bytes():
                raise SystemExit(name + " 0.7 秒内星光区域没有变化")
            report["cases"].append({
                "name": name,
                "duration": duration,
                "silent": silent,
                "streams": kinds,
                "width": 1920,
                "height": 1080,
                "hold_seconds": snapshot["hold_seconds"],
                "scroll_ends_at": snapshot["scroll_ends_at"],
                "peak_rss_mib": round(memory["peak_rss_kib"] / 1024, 1),
                "returncode": memory["returncode"],
                "video_sha256": hashlib.sha256(shutil_video.read_bytes()).hexdigest(),
                "stars_sha256": hashlib.sha256((out / "stars.mov").read_bytes()).hexdigest(),
            })
    dest = out_root / f"{label}-memory.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main()
