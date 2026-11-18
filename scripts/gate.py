#!/usr/bin/env python3
"""File-backed intake gate.

The assistant must follow the decision this module prints. Tests lock it.
A model can still lie in the utterance field: that is not a security boundary.
What the script itself checks is the part that does not depend on trust:
the phrase blocks, whether files exist, whether audio really has a stream,
whether the manifest hashes still match, and whether the output directory is new.
"""
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
EXAMPLES = ROOT / "examples"
GATE_VERSION = "0.2.2"

VAGUE_EXACT = {
    "给我跑一下", "跑一下", "试一下", "做一个", "做一下", "试试看",
    "帮我跑一下", "帮我试一下", "测试一下", "跑个测试", "跑一下看看",
}
INSTALL_EXACT = {"安装好了", "已安装", "技能已安装", "装好了", "我装好了"}
SILENCE_MARKERS = ("不要音乐", "先静音", "跳过音乐", "不用音乐", "明确不要音乐", "明确静音")
ORIGINAL_REFERENCE = "五月天《如果我们不曾相遇》"
COPY_FIELDS = ("names", "date", "lists", "thanks")
COPY_LABELS = {
    "names": "新郎新娘姓名",
    "date": "婚期",
    "lists": "分组名单",
    "thanks": "感谢文字",
}

class GateError(RuntimeError):
    pass

def normalize(text):
    return re.sub(r"[\s，。！？、,.!~～\"'“”]", "", text or "")

def is_vague_request(text):
    return normalize(text) in {normalize(item) for item in VAGUE_EXACT}

def is_install_request(text):
    return normalize(text) in {normalize(item) for item in INSTALL_EXACT}

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False

def packaged_asset_hashes():
    found = {}
    if ASSETS.is_dir():
        for name in ("record.png", "wave.png", "stars.mov"):
            path = ASSETS / name
            if path.is_file():
                found[sha256_file(path)] = name
    return found

def example_hashes():
    found = {}
    photo_dir = EXAMPLES / "photos"
    if photo_dir.is_dir():
        for path in photo_dir.iterdir():
            if path.is_file():
                found[sha256_file(path)] = "examples/photos/" + path.name
    music = EXAMPLES / "music.m4a"
    if music.is_file():
        found[sha256_file(music)] = "examples/music.m4a"
    return found

def probe_json(path):
    probe = _binary("ffprobe")
    result = subprocess.run(
        [probe, "-v", "error", "-show_streams", "-of", "json", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = detail[-1][:300] if detail else "无法读取"
        raise GateError(f"文件无法读取：{path}。已停止。{tail}")
    return json.loads(result.stdout or "{}")

def has_stream(path, kind):
    meta = probe_json(path)
    return any(item.get("codec_type") == kind for item in meta.get("streams") or [])

def _binary(name):
    import os, shutil
    found = os.environ.get(name.upper()) or shutil.which(name)
    if found:
        return found
    bundled = Path("/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static") / name
    if bundled.exists():
        return str(bundled)
    raise GateError(f"找不到 {name}。已停止，没有安装或替换系统里的程序。")

def ffmpeg_major(ff=None):
    ff = ff or _binary("ffmpeg")
    result = subprocess.run([ff, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise GateError("FFmpeg 无法启动。已停止，没有安装替代版本，也没有导出视频。")
    line = (result.stdout or "").splitlines()[0] if result.stdout else ""
    match = re.search(r"version\s+n?(\d+)\.", line)
    if not match:
        raise GateError("无法识别 FFmpeg 版本：" + line)
    return int(match.group(1)), line

def filter_file_option(major, mode):
    """How to load a filter graph file without changing the graph text.

    FFmpeg 6.1 accepts -filter_complex_script and -filter_script:v.
    -/filter_complex is rejected there. FFmpeg 9.0 removes -filter_complex_script
    (commit 07407ff, between n8.1 and n9.0); the deprecation text says it is
    equivalent to -/filter_complex. This environment has not executed 9.0.
    """
    if mode == "complex":
        return "-/filter_complex" if major >= 9 else "-filter_complex_script"
    if mode == "video":
        return "-/filter:v" if major >= 9 else "-filter_script:v"
    raise GateError("未知滤镜参数类型")

def silence_allowed(text):
    if is_vague_request(text):
        return False
    return any(marker in (text or "") for marker in SILENCE_MARKERS)

def placeholders_allowed(state):
    text = state.get("utterance") or ""
    if is_vague_request(text):
        return False
    return "占位" in text and "同意" in text and state.get("placeholders_accepted") is True

def synthetic_allowed(state):
    text = state.get("utterance") or ""
    if is_vague_request(text):
        return False
    return "合成测试音" in text and "同意" in text and state.get("synthetic_tone_accepted") is True

def mentions_original(text, choice=""):
    if choice in ("original", "原片同款"):
        return True
    raw = text or ""
    if "原片同款" in raw or "如果我们不曾相遇" in raw:
        return True
    compact = normalize(raw)
    return compact in {"用原片", "原片", "原片音乐", "原片的音乐", "用原片的音乐", "用原片的bgm", "用原片的BGM"}

def mentions_other_song(text):
    raw = text or ""
    return any(item in raw for item in ("别的歌", "不是这首", "另一首", "换一首"))

def mentions_own_song(text, choice=""):
    if choice in ("own", "自己选歌"):
        return True
    return "自己选歌" in (text or "")

def canonical_summary(photo_count, kind, audio_label, placeholders, width, source_note=""):
    parts = [f"照片 {photo_count} 张", "姓名、婚期、分组名单和感谢文字已收到"]
    if placeholders:
        parts.append("这是占位照片和化名，不是你的婚礼")
    if kind == "silent":
        parts.append("你已明确不要音乐，将导出静音")
    elif kind == "synthetic-test-tone":
        parts.append("音乐是合成测试音，不是你的歌曲")
    else:
        if not audio_label:
            raise GateError("确认前必须有真实音乐文件名。不能只写原片同款。")
        parts.append("音乐文件：" + audio_label)
        if source_note:
            parts.append(source_note)
    parts.append(f"确认后才导出 {width}×{width * 9 // 16}")
    return "；".join(parts) + "。"

def decide(state):
    if not isinstance(state, dict):
        raise GateError("state 必须是对象")
    text = state.get("utterance") or ""
    intent = state.get("intent") or ""
    photos = bool(state.get("photos"))
    copy = {key: bool(state.get(key)) for key in COPY_FIELDS}
    audio = bool(state.get("audio"))
    audio_label = (state.get("audio_label") or "").strip()
    confirmed = bool(state.get("confirmed")) and not is_vague_request(text)
    provided = photos or any(copy.values()) or audio
    vague = is_vague_request(text) or intent == "vague"
    limits = {
        "agent_flags_are_not_a_security_boundary": True,
        "vague_phrase_is_not_consent": True,
    }

    if (intent == "install" or is_install_request(text)) and not vague and not provided:
        if state.get("already_installed"):
            message = "请发你要放进视频的照片。"
        else:
            message = "技能已经装好。请发你要放进视频的照片。"
        return _result(
            "acknowledge_install",
            message,
            limits=limits,
            assistant_note="只做只读依赖检查。不要重报版本，不要念路径，不要给安装、打补丁或出片的选择。",
        )
    if vague and not photos:
        return _result(
            "ask_photos",
            "请先发你自己的照片。",
            ask="photos",
            limits=limits,
            assistant_note="「给我跑一下」「试一下」「做一个」不是同意占位演示，也不是同意合成测试音。不要提供技术试跑菜单。",
        )
    if not photos:
        return _result(
            "ask_photos",
            "请先发你要放进视频的照片。",
            ask="photos",
            limits=limits,
        )
    missing = [key for key in COPY_FIELDS if not copy[key]]
    if missing:
        got = [COPY_LABELS[key] for key in COPY_FIELDS if copy[key]]
        prefix = ("已记下" + "、".join(got) + "。") if got else "照片已收到。"
        need = "、".join(COPY_LABELS[key] for key in missing)
        return _result(
            "ask_copy",
            prefix + "请再发" + need + "。名单请自己核对，我不会猜名字，也不会用示例化名。",
            ask="copy",
            missing_copy=missing,
            limits=limits,
        )
    choice = state.get("music_choice") or ""
    source_video = (state.get("source_video") or "").strip()
    kind = _audio_kind(state, audio, audio_label)
    if kind == "need-audio":
        if mentions_other_song(text):
            return _result(
                "ask_audio",
                f"原片同款指的是{ORIGINAL_REFERENCE}。你要的如果是别的音乐，请告诉我是哪一首，或直接发文件。",
                ask="audio",
                limits=limits,
                assistant_note="不要猜测私人视频路径，也不要下载。",
            )
        if mentions_original(text, choice):
            if source_video and "同意提取" in text:
                return _result(
                    "extract_audio",
                    "可以按你的明确要求，从你给出的这段本地视频里提取整条音轨。里面如果有人声或环境声，会一起留下。这一步只是取出声音，不代表已经获得歌曲版权。",
                    ask="audio",
                    limits=limits,
                    assistant_note="只处理用户给出的这个文件。不要从技能包素材里取，也不要去网上找。",
                )
            return _result(
                "ask_original_file",
                f"好，用原片同款：{ORIGINAL_REFERENCE}。请上传你有权使用的音频；或者发一段含有这段配乐的本地视频，并说明同意提取。包里没有这首歌，我也不会去网上找。",
                ask="audio",
                limits=limits,
                assistant_note="曲名只是参考。选择同款不等于已经有文件或授权。不要猜测私人视频路径。",
            )
        if mentions_own_song(text, choice) or "音乐用" in text:
            return _result(
                "ask_audio",
                "请把音乐文件发过来。",
                ask="audio",
                limits=limits,
            )
        return _result(
            "ask_audio",
            f"音乐可以用：原片同款、自己选歌，或明确静音。原片同款指{ORIGINAL_REFERENCE}，包里没有这首歌。",
            ask="audio",
            limits=limits,
            assistant_note="这是音乐内容的三个短选项，不是安装或打补丁菜单。",
        )
    if kind == "conflict":
        return _result(
            "refuse",
            "音乐文件和「不要音乐」不能同时成立。请选定一种。",
            ask="audio",
            limits=limits,
        )
    if kind == "synthetic-test-tone" and not synthetic_allowed(state):
        return _result(
            "ask_audio",
            "还没有同意使用合成测试音。请改发你的音乐文件，或明确说「不要音乐」。"
            "合成测试音不会被当成你的歌曲。",
            ask="audio",
            limits=limits,
        )
    if kind == "file" and not audio_label:
        raise GateError("已有音乐文件时需要 audio_label，确认前要向用户报出文件名")
    if kind == "file" and mentions_original(text, choice) and not state.get("audio_source"):
        state["audio_source"] = f"参考曲目是{ORIGINAL_REFERENCE}。曲名不是授权，实际使用的是这个文件。"
    summary = canonical_summary(
        int(state.get("photo_count") or 1),
        kind,
        audio_label,
        placeholders_allowed(state),
        int(state.get("width") or 1920),
        state.get("audio_source") or "",
    )
    if not confirmed:
        return _result("confirm_before_render", "导出前请确认：" + summary, summary=summary, limits=limits)
    action = {"silent": "render_silent", "synthetic-test-tone": "render_synthetic"}.get(kind, "render")
    return _result(action, "用户已确认：" + summary, summary=summary, limits=limits)

def _audio_kind(state, audio, audio_label):
    text = state.get("utterance") or ""
    wants_silence = silence_allowed(text)
    wants_synth = synthetic_allowed(state)
    if audio and wants_silence:
        return "conflict"
    if audio:
        if "合成测试音" in audio_label or audio_label == "synthetic-test-tone.wav":
            return "synthetic-test-tone"
        return "file"
    if wants_silence:
        return "silent"
    if wants_synth:
        return "synthetic-test-tone"
    return "need-audio"

def _result(action, tell, ask=None, summary=None, missing_copy=None, limits=None, assistant_note=""):
    return {
        "action": action,
        "render": action in ("render", "render_silent", "render_synthetic"),
        "ask": ask,
        "tell_user": tell,
        "assistant_note": assistant_note,
        "summary": summary,
        "missing_copy": missing_copy,
        "limits": limits,
        "show_technical_details": False,
        "offer_choice_menu": False,
        "gate_version": GATE_VERSION,
    }

def load_config(path):
    path = Path(path)
    if not path.is_file():
        raise GateError(f"配置不存在：{path}。已停止。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError(f"配置不是合法 JSON：{path}。已停止。{exc}") from exc

def resolve_config_files(config_path):
    config_path = Path(config_path).resolve()
    cfg = load_config(config_path)
    base = config_path.parent
    photos_cfg = cfg.get("photos")
    if not isinstance(photos_cfg, list) or not photos_cfg:
        raise GateError("配置里没有照片。已停止，没有用效果图或示例图补上。")
    photos = []
    asset_hashes = packaged_asset_hashes()
    example_ids = example_hashes()
    fixture_hits = []
    for item in photos_cfg:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item.get("path"):
            raise GateError("每张照片都要有 path。已停止。")
        path = Path(item["path"]).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        if not path.is_file():
            raise GateError(f"照片不存在：{path}。已停止，没有用技能包里的图形顶替。")
        if not has_stream(path, "video"):
            raise GateError(f"照片无法作为画面读取：{path}。已停止。")
        digest = sha256_file(path)
        if digest in asset_hashes or inside(path, ASSETS):
            raise GateError(f"照片指向了效果素材 {path.name}。已停止。请改用客户自己的照片。")
        if digest in example_ids or inside(path, EXAMPLES):
            fixture_hits.append(example_ids.get(digest, str(path)))
        for key in ("focus_x", "focus_y"):
            focus = item.get(key, 0.5)
            if isinstance(focus, bool) or not isinstance(focus, (int, float)) or not 0 <= focus <= 1:
                raise GateError(key + " 需在 0 至 1 之间")
        photos.append(path)
    kind, audio = _resolve_audio_file(cfg, base)
    if audio is not None:
        digest = sha256_file(audio)
        if digest in example_ids or inside(audio, EXAMPLES):
            fixture_hits.append(example_ids.get(digest, str(audio)))
        if audio.name == "synthetic-test-tone.wav" and kind != "synthetic-test-tone":
            raise GateError("synthetic-test-tone.wav 不能当作客户的音乐文件。已停止。")
    return cfg, photos, kind, audio, fixture_hits

def _resolve_audio_file(cfg, base):
    silent = cfg.get("silent") is True
    kind = cfg.get("audio_kind")
    if "audio" not in cfg and kind != "synthetic-test-tone":
        raise GateError("配置里没有 audio。已停止，没有改成静音，也没有生成测试音。")
    audio_value = cfg.get("audio")
    if kind == "synthetic-test-tone":
        if not isinstance(audio_value, str) or Path(audio_value).name != "synthetic-test-tone.wav":
            raise GateError("合成测试音的文件名必须是 synthetic-test-tone.wav，不能伪装成客户的歌。")
        path = _resolve_existing_audio(base, audio_value)
        return "synthetic-test-tone", path
    if silent:
        if audio_value is not None:
            raise GateError("明确静音时 audio 必须是 null。已停止。")
        return "silent", None
    if audio_value is None or (isinstance(audio_value, str) and not audio_value.strip()):
        raise GateError("audio 为空，但没有明确静音。已停止，没有改成静音。")
    if not isinstance(audio_value, str):
        raise GateError("audio 必须是音乐文件路径，或在用户明确不要音乐时为 null。")
    return "file", _resolve_existing_audio(base, audio_value)

def _resolve_existing_audio(base, value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file():
        raise GateError(f"配乐文件不存在：{path}。已停止，没有改成静音或换成其他音频。")
    if not has_stream(path, "audio"):
        raise GateError(f"配乐没有音频轨道：{path}。已停止，没有改成静音。")
    return path

def build_manifest(state, config_path, out_dir, manifest_path, width=1920):
    if not isinstance(width, int) or width not in (960, 1920):
        raise GateError("宽度只允许 1920，或用户明确要求预览时的 960。")
    if width == 960 and "预览" not in (state.get("utterance") or ""):
        raise GateError("960 只在用户明确说预览时使用。正式导出是 1920×1080。已停止。")
    state = dict(state)
    state["width"] = width
    cfg, photos, kind, audio, fixtures = resolve_config_files(config_path)
    state["photo_count"] = len(photos)
    state["photos"] = True
    if kind == "file":
        state["audio"] = True
        state["audio_label"] = audio.name
        state["synthetic_tone_accepted"] = False
        if not state.get("audio_source") and mentions_original(state.get("utterance") or "", state.get("music_choice") or ""):
            state["audio_source"] = f"参考曲目是{ORIGINAL_REFERENCE}。曲名不是授权，实际使用的是这个文件。"
        audio_from = cfg.get("audio_from")
        if isinstance(audio_from, str) and audio_from.strip():
            state["audio_source"] = (
                f"来源：从你要求提取的视频 {Path(audio_from).name} 取出的整条音轨。"
                "这只是技术提取，不是版权证明。"
            )
    elif kind == "silent":
        state["audio"] = False
        state["audio_label"] = ""
    else:
        state["audio"] = True
        state["audio_label"] = "synthetic-test-tone.wav"
        state["synthetic_tone_accepted"] = True
    if fixtures and not placeholders_allowed(state):
        raise GateError(
            "这些文件是开发用示例，不是客户默认素材：" + "、".join(fixtures)
            + "。已停止。用户必须明确同意占位照片和化名。"
        )
    if kind == "synthetic-test-tone" and not synthetic_allowed(state):
        raise GateError("未明确同意合成测试音。已停止，没有把它当成客户的 BGM。")
    if kind == "silent" and not silence_allowed(state.get("utterance") or ""):
        raise GateError("配置写了静音，但用户原话里没有「不要音乐」。已停止。")
    decision = decide(state)
    if not decision["render"]:
        raise GateError("材料还不能导出：" + decision["tell_user"])
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        raise GateError(f"输出目录已存在：{out_dir}。已停止。请换一个新目录，不要覆盖旧版本。")
    major, version_line = ffmpeg_major()
    summary = decision["summary"]
    manifest = {
        "gate_version": GATE_VERSION,
        "encode_allowed": True,
        "confirmed": True,
        "limits": decision["limits"],
        "utterance": state.get("utterance") or "",
        "summary": summary,
        "width": width,
        "audio_kind": kind,
        "placeholders": placeholders_allowed(state),
        "synthetic_tone": kind == "synthetic-test-tone",
        "config_sha256": sha256_file(config_path),
        "output_dir": str(out_dir),
        "photos": [{"path": str(path), "sha256": sha256_file(path)} for path in photos],
        "audio_source": state.get("audio_source") or "",
        "reference_track": ORIGINAL_REFERENCE if mentions_original(state.get("utterance") or "", state.get("music_choice") or "") else "",
        "audio": None if audio is None else {"path": str(audio), "sha256": sha256_file(audio), "kind": kind},
        "ffmpeg": {
            "version": version_line,
            "major": major,
            "complex_filter_option": filter_file_option(major, "complex"),
            "ffmpeg_9_executed_here": False,
        },
    }
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.resolve() == out_dir or inside(manifest_path, out_dir):
        raise GateError("清单不能写进尚未创建的输出目录。")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

def assert_manifest(manifest_path, config_path, out_dir, width):
    path = Path(manifest_path)
    if not path.is_file():
        raise GateError("没有清单。已停止，没有导出。安装、试跑和未确认的材料都不能直接渲染。")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("encode_allowed") is not True or manifest.get("confirmed") is not True:
        raise GateError("清单没有确认导出。已停止。")
    if manifest.get("limits", {}).get("agent_flags_are_not_a_security_boundary") is not True:
        raise GateError("清单缺少限度说明。已停止。")
    if Path(manifest.get("output_dir", "")).resolve() != Path(out_dir).resolve():
        raise GateError("清单里的输出目录和本次 --out 不一致。已停止。")
    if int(manifest.get("width") or 0) != int(width):
        raise GateError("清单里的宽度和本次导出不一致。已停止。")
    if int(width) == 960 and "预览" not in (manifest.get("utterance") or ""):
        raise GateError("960 只在用户明确说预览时使用。已停止。")
    if sha256_file(config_path) != manifest.get("config_sha256"):
        raise GateError("配置在确认后被改过。已停止。请重新汇总并确认。")
    if Path(out_dir).exists():
        raise GateError(f"输出目录已存在：{out_dir}。已停止。请换一个新目录。")
    _cfg, photos, kind, audio, _fixtures = resolve_config_files(config_path)
    if kind != manifest.get("audio_kind"):
        raise GateError("音乐处理方式和已确认的清单不一致。已停止。")
    photo_hashes = [item.get("sha256") for item in manifest.get("photos") or []]
    if [sha256_file(item) for item in photos] != photo_hashes:
        raise GateError("照片和已确认的清单不一致。已停止。")
    if audio is None:
        if manifest.get("audio") is not None:
            raise GateError("清单里有音乐，配置却是静音。已停止。")
    else:
        recorded = (manifest.get("audio") or {}).get("sha256")
        if sha256_file(audio) != recorded:
            raise GateError("音乐文件和已确认的清单不一致。已停止。")
    state = {
        "intent": "personal",
        "utterance": manifest.get("utterance") or "",
        "photos": True,
        "names": True,
        "date": True,
        "lists": True,
        "thanks": True,
        "audio": kind == "file" or kind == "synthetic-test-tone",
        "audio_label": Path(audio).name if audio is not None else "",
        "audio_source": manifest.get("audio_source") or "",
        "confirmed": True,
        "placeholders_accepted": bool(manifest.get("placeholders")),
        "synthetic_tone_accepted": kind == "synthetic-test-tone",
        "photo_count": len(photos),
        "width": width,
    }
    decision = decide(state)
    if not decision["render"] or decision.get("summary") != manifest.get("summary"):
        raise GateError("清单和当前规则不一致。已停止。请重新确认。")
    return manifest, photos, kind, audio

def extract_user_audio(video, dest, utterance):
    """Copy the whole audio track from a user-supplied local video. Not a license."""
    if "同意提取" not in (utterance or ""):
        raise GateError("还没有明确要求提取。已停止。从视频取出声音不会自动获得歌曲版权。")
    video = Path(video).expanduser()
    if not video.is_absolute():
        video = Path.cwd() / video
    video = video.resolve()
    if not video.is_file():
        raise GateError(f"找不到你给出的视频：{video}。已停止，没有改去找别的文件。")
    if inside(video, EXAMPLES) or inside(video, ASSETS):
        raise GateError("不能从技能包的示例或效果素材里提取音频。已停止。")
    if not has_stream(video, "audio"):
        raise GateError(f"这条视频没有音轨：{video.name}。已停止，没有改成静音。")
    dest = Path(dest)
    if inside(dest, EXAMPLES) or inside(dest, ASSETS):
        raise GateError("提取结果不能写进技能包。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    ff = _binary("ffmpeg")
    result = subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-c:a", "aac", str(dest)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode or not dest.is_file() or not has_stream(dest, "audio"):
        raise GateError("没有从这段视频里取出音轨。已停止，没有改成静音。" + (result.stderr or "")[-300:])
    note = "提取的是整条音轨。若有人声或环境声会一起留下，这里不会拆成纯音乐。这一步只是技术提取，不构成歌曲授权。"
    return {"path": str(dest.resolve()), "source": video.name, "note": note}

def write_test_tone(state, dest):
    dest = Path(dest)
    if dest.name != "synthetic-test-tone.wav":
        raise GateError("合成测试音只能写成 synthetic-test-tone.wav，避免伪装成客户的歌。")
    if not synthetic_allowed(state):
        raise GateError("没有「同意合成测试音」的原话。已停止，没有生成声音。")
    if not bool(state.get("confirmed")) or is_vague_request(state.get("utterance") or ""):
        raise GateError("生成测试音前需要用户确认，而且「跑一下」不算确认。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    ff = _binary("ffmpeg")
    result = subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(dest)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode or not dest.is_file():
        raise GateError("合成测试音没有写成。已停止。" + (result.stderr or "")[-300:])
    if not has_stream(dest, "audio"):
        raise GateError("合成测试音没有音轨。已停止。")
    return dest

def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def main():
    parser = argparse.ArgumentParser(description="黑胶婚礼致谢的材料清单。不直接导出视频。")
    parser.add_argument("command", choices=("decide", "manifest", "write-test-tone", "extract"))
    parser.add_argument("--video", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--width", type=int, default=1920)
    args = parser.parse_args()
    try:
        if args.command == "decide":
            if not args.state:
                raise GateError("decide 需要 --state")
            print(json.dumps(decide(_read_json(args.state)), ensure_ascii=False))
            return
        if args.command == "extract":
            if not args.state or not args.video or not args.dest:
                raise GateError("extract 需要 --state --video --dest")
            payload = extract_user_audio(args.video, args.dest, _read_json(args.state).get("utterance") or "")
            print(json.dumps(payload, ensure_ascii=False))
            return
        if args.command == "write-test-tone":
            if not args.state or not args.dest:
                raise GateError("write-test-tone 需要 --state 和 --dest")
            path = write_test_tone(_read_json(args.state), args.dest)
            print(json.dumps({"wrote": str(path), "kind": "synthetic-test-tone"}, ensure_ascii=False))
            return
        if not args.state or not args.config or not args.out or not args.manifest:
            raise GateError("manifest 需要 --state --config --out --manifest")
        manifest = build_manifest(_read_json(args.state), args.config, args.out, args.manifest, args.width)
        print(json.dumps({"manifest": str(Path(args.manifest).resolve()), "summary": manifest["summary"]}, ensure_ascii=False))
    except GateError as exc:
        print("已停止：" + str(exc), file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
