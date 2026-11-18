"""Beginner intake decisions for wedding-vinyl-thanks.

The assistant follows the same order in SKILL.md. These functions do not render,
do not read customer files, and do not invent names. Tests lock the decisions.
"""

COPY_FIELDS = ("names", "date", "lists", "thanks")
COPY_LABELS = {
    "names": "新郎新娘姓名",
    "date": "婚期",
    "lists": "分组名单",
    "thanks": "感谢文字",
}

INSTALL_MSG = (
    "技能已经装好。要做你自己的婚礼致谢视频时，请先发照片（清晰一些，人脸尽量完整）。"
    "我不会先导出示例视频，也不会用示例姓名或静音代替你的材料。"
    "如果只想检查这台电脑的 Python、FFmpeg 和字体，告诉我即可，检查不会出片。"
)
ASK_PHOTOS = "请先发你要放进视频的照片。这一步先不用发名单和音乐。"
ASK_AUDIO = (
    "文字已记下。请发音乐文件（BGM）。"
    "如果确定不要音乐，请直接说「不要音乐」，我才会做静音。"
    "不会自动静音，也不会自己生成一段提示音。"
)
REFUSE_MSG = (
    "不能用技能包里的占位照片、示例化名，或我编出来的姓名，来做你的视频。"
    "请发你自己的照片。我不会先出一版静音示例。"
)
BOTH_AUDIO_MSG = "音乐文件和「不要音乐」不能同时成立。请选定一种：发一个音乐文件，或者说不要音乐。"


def decide(state):
    """Return the next intake action. render is true only when a video may be made."""
    if not isinstance(state, dict):
        raise ValueError("state 必须是字典")
    intent = state.get("intent")
    if intent not in ("install", "personal", "demo"):
        raise ValueError("intent 必须是 install、personal 或 demo")
    photos = bool(state.get("photos"))
    copy = {key: bool(state.get(key)) for key in COPY_FIELDS}
    audio = bool(state.get("audio"))
    silence = bool(state.get("silence_opt_in"))
    confirmed = bool(state.get("confirmed"))
    invented = bool(state.get("invented_names"))
    placeholders = bool(state.get("placeholders"))
    audio_label = (state.get("audio_label") or "").strip()
    # Silence is a choice about music, not personal wedding material.
    provided = photos or any(copy.values()) or audio

    # Installation alone is not a render request, even if the package contains samples.
    if intent == "install" and not provided:
        return _result("acknowledge_install", INSTALL_MSG)

    # A demo is optional and only uses the bundled sample when the user gave no personal material.
    if intent == "demo" and not provided and not invented:
        return _demo(silence, confirmed)

    if invented or placeholders:
        return _result("refuse", REFUSE_MSG, ask="photos")
    if not photos:
        return _result("ask_photos", ASK_PHOTOS, ask="photos")
    missing = [key for key in COPY_FIELDS if not copy[key]]
    if missing:
        return _result("ask_copy", _ask_copy(missing, copy), ask="copy", missing_copy=missing)
    if audio and silence:
        return _result("refuse", BOTH_AUDIO_MSG, ask="audio")
    if not audio and not silence:
        return _result("ask_audio", ASK_AUDIO, ask="audio")
    if audio and not audio_label:
        raise ValueError("已有音乐时需要 audio_label，确认前要向用户报出文件名")
    summary = _summary(audio_label if audio else None, silence, demo=False)
    if not confirmed:
        return _result("confirm_before_render", _confirm(summary), summary=summary)
    return _result("render", "用户已确认，可以按这份材料导出。", summary=summary)


def _demo(silence, confirmed):
    summary = _summary(None if silence else "examples/music.m4a", silence, demo=True)
    summary["photos"] = "examples/photos 占位图"
    summary["names"] = "示例化名，不是客户姓名"
    if silence:
        music = "你已明确不要音乐，演示将导出静音"
    else:
        music = "演示使用技能包里的示例音乐 examples/music.m4a"
    message = (
        "你要求看演示。这一版会使用技能包里的占位照片和化名（例如张三、李四），不是你的婚礼。"
        + music
        + "。确认后我才导出这支演示。要做你自己的视频，请改发真实照片。"
    )
    if not confirmed:
        return _result("confirm_before_render", message, summary=summary, config_sample=True)
    return _result("render_demo", "用户已确认演示，才可以使用示例配置和 --accept-sample。", summary=summary, config_sample=True)


def _summary(audio_label, silence, demo):
    return {
        "demo": demo,
        "photos": True,
        "names": True,
        "date": True,
        "lists": True,
        "thanks": True,
        "audio": audio_label,
        "silent": silence,
    }


def _confirm(summary):
    if summary["silent"]:
        music = "你已明确不要音乐，将导出静音"
    else:
        music = "音乐文件：" + summary["audio"]
    return (
        "材料已经齐，导出前请确认：照片已收到；新郎新娘姓名、婚期、分组名单和感谢文字已收到；"
        + music
        + "。确认后我才开始导出 1920×1080 的视频。"
    )


def _ask_copy(missing, have):
    need = "、".join(COPY_LABELS[key] for key in missing)
    got = [COPY_LABELS[key] for key in COPY_FIELDS if have[key]]
    prefix = ("已记下" + "、".join(got) + "。") if got else "照片已收到。"
    return prefix + "请再发" + need + "。名单请自己核对，我不会猜名字，也不会用示例里的化名。"


def _result(action, tell, ask=None, summary=None, missing_copy=None, config_sample=False):
    return {
        "action": action,
        "render": action in ("render", "render_demo"),
        "ask": ask,
        "tell_user": tell,
        "summary": summary,
        "missing_copy": missing_copy,
        "config_sample": config_sample if action in ("render_demo", "confirm_before_render") else False,
    }
