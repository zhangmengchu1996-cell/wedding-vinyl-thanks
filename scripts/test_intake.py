"""Regression checks for the v0.2.1 beginner intake.

These run the decision table and the local renderer. They do not launch Codex
or WorkBuddy, and they do not use private wedding data.
"""
import hashlib, json, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path

from intake import decide
from package_skill import build_zip
from render import (
    EXAMPLES,
    MaterialError,
    ROOT,
    resolve_audio,
    sample_reasons,
    validate_sample_use,
)

FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
ASSETS = {
    "assets/stars.mov": "d1c484e47f2008ab2a7d547453c4f4b9329047a800dc6b4e851fe57fa117e4b5",
    "assets/record.png": "bce2c77dc69609f29e7a8a7cf4b985d8e904871ec2d3f03a0abad556b13b97bd",
    "assets/wave.png": "59a8b55518b83e4224215196b57e52e26df8d5b35b6e496bae171661b20dcf41",
}
RENDER = ROOT / "scripts" / "render.py"
LINES = [
    {"text": "谢 幕 答 谢", "heading": True},
    {"text": "2026.06.18"},
    {"text": "新郎 陈一  &  新娘 林二"},
    {"text": "感谢你们到场"},
    {"names": ["周叔", "吴姨"]},
    {"text": "感谢一路相伴"},
]


def decide_personal(**overrides):
    state = {
        "intent": "personal",
        "photos": False,
        "names": False,
        "date": False,
        "lists": False,
        "thanks": False,
        "audio": False,
        "silence_opt_in": False,
        "confirmed": False,
        "invented_names": False,
        "placeholders": False,
        "audio_label": "",
    }
    state.update(overrides)
    return decide(state)


def full_material(**overrides):
    state = dict(
        photos=True,
        names=True,
        date=True,
        lists=True,
        thanks=True,
        audio=True,
        audio_label="march.m4a",
    )
    state.update(overrides)
    return decide_personal(**state)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(RENDER), *args],
        capture_output=True,
        text=True,
    )


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def make_photo(path):
    ffmpeg("-f", "lavfi", "-i", "color=c=0x336699:s=80x80", "-frames:v", "1", str(path))


def make_music(path):
    # Distinct file for this regression only. Do not copy this into a customer render.
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=523:duration=1", "-c:a", "aac", str(path))


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class IntakeDecisionTests(unittest.TestCase):
    def test_install_only_acknowledges_and_does_not_render(self):
        decision = decide({"intent": "install"})
        self.assertEqual(decision["action"], "acknowledge_install")
        self.assertFalse(decision["render"])
        self.assertIn("已经装好", decision["tell_user"])
        self.assertIn("照片", decision["tell_user"])
        self.assertIn("不会先导出示例视频", decision["tell_user"])

    def test_install_only_ignores_bundled_placeholders(self):
        decision = decide({"intent": "install", "placeholders": True, "confirmed": True})
        self.assertEqual(decision["action"], "acknowledge_install")
        self.assertFalse(decision["render"])
        self.assertFalse(decision["config_sample"])

    def test_personal_no_materials_asks_for_photos_only(self):
        decision = decide_personal()
        self.assertEqual(decision["action"], "ask_photos")
        self.assertEqual(decision["ask"], "photos")
        self.assertFalse(decision["render"])
        self.assertNotIn("音乐文件", decision["tell_user"])

    def test_partial_photos_only_asks_for_copy_not_audio(self):
        decision = decide_personal(photos=True)
        self.assertEqual(decision["action"], "ask_copy")
        self.assertEqual(decision["missing_copy"], ["names", "date", "lists", "thanks"])
        self.assertFalse(decision["render"])

    def test_partial_copy_asks_only_for_what_is_missing(self):
        decision = decide_personal(photos=True, names=True, date=True, audio=True, audio_label="march.m4a")
        self.assertEqual(decision["action"], "ask_copy")
        self.assertEqual(decision["missing_copy"], ["lists", "thanks"])
        self.assertIn("分组名单", decision["tell_user"])
        self.assertIn("感谢文字", decision["tell_user"])
        self.assertNotIn("请先发你要放进视频的照片", decision["tell_user"])
        self.assertFalse(decision["render"])

    def test_partial_without_music_asks_for_bgm_not_silence(self):
        decision = decide_personal(photos=True, names=True, date=True, lists=True, thanks=True)
        self.assertEqual(decision["action"], "ask_audio")
        self.assertIn("不会自动静音", decision["tell_user"])
        self.assertIn("不要音乐", decision["tell_user"])
        self.assertFalse(decision["render"])

    def test_full_material_including_music_waits_for_confirmation(self):
        decision = full_material()
        self.assertEqual(decision["action"], "confirm_before_render")
        self.assertFalse(decision["render"])
        self.assertIn("march.m4a", decision["tell_user"])
        self.assertNotIn("将导出静音", decision["tell_user"])
        self.assertFalse(decision["config_sample"])
        self.assertEqual(decision["summary"]["audio"], "march.m4a")
        self.assertFalse(decision["summary"]["silent"])

    def test_full_material_including_music_renders_after_confirmation(self):
        decision = full_material(confirmed=True)
        self.assertEqual(decision["action"], "render")
        self.assertTrue(decision["render"])
        self.assertFalse(decision["config_sample"])
        self.assertEqual(decision["summary"]["audio"], "march.m4a")

    def test_explicit_silence_is_not_used_before_earlier_materials(self):
        decision = decide_personal(silence_opt_in=True)
        self.assertEqual(decision["action"], "ask_photos")
        self.assertFalse(decision["render"])

    def test_explicit_silence_is_summarized_then_rendered_only_after_confirmation(self):
        waiting = decide_personal(
            photos=True, names=True, date=True, lists=True, thanks=True, silence_opt_in=True
        )
        self.assertEqual(waiting["action"], "confirm_before_render")
        self.assertFalse(waiting["render"])
        self.assertIn("你已明确不要音乐，将导出静音", waiting["tell_user"])
        self.assertTrue(waiting["summary"]["silent"])
        self.assertIsNone(waiting["summary"]["audio"])
        done = decide_personal(
            photos=True, names=True, date=True, lists=True, thanks=True,
            silence_opt_in=True, confirmed=True,
        )
        self.assertEqual(done["action"], "render")
        self.assertTrue(done["render"])
        self.assertTrue(done["summary"]["silent"])

    def test_explicit_demo_waits_then_uses_sample_flag(self):
        waiting = decide({"intent": "demo"})
        self.assertEqual(waiting["action"], "confirm_before_render")
        self.assertFalse(waiting["render"])
        self.assertTrue(waiting["config_sample"])
        self.assertIn("占位", waiting["tell_user"])
        self.assertIn("化名", waiting["tell_user"])
        self.assertIn("examples/music.m4a", waiting["tell_user"])
        done = decide({"intent": "demo", "confirmed": True})
        self.assertEqual(done["action"], "render_demo")
        self.assertTrue(done["render"])
        self.assertTrue(done["config_sample"])

    def test_explicit_silent_demo_mentions_both(self):
        decision = decide({"intent": "demo", "silence_opt_in": True})
        self.assertFalse(decision["render"])
        self.assertIn("占位", decision["tell_user"])
        self.assertIn("明确不要音乐", decision["tell_user"])

    def test_personal_request_does_not_start_with_a_demo(self):
        decision = decide({"intent": "demo", "photos": True})
        self.assertNotEqual(decision["action"], "render_demo")
        self.assertEqual(decision["action"], "ask_copy")
        self.assertFalse(decision["render"])

    def test_placeholders_or_invented_names_are_refused(self):
        for flag in ("placeholders", "invented_names"):
            decision = full_material(**{flag: True})
            self.assertEqual(decision["action"], "refuse", flag)
            self.assertFalse(decision["render"])
            self.assertIn("占位", decision["tell_user"])

    def test_audio_and_silence_together_are_refused(self):
        decision = full_material(silence_opt_in=True)
        self.assertEqual(decision["action"], "refuse")
        self.assertFalse(decision["render"])

    def test_install_with_real_photos_continues_intake_without_a_demo(self):
        decision = decide({"intent": "install", "photos": True})
        self.assertEqual(decision["action"], "ask_copy")
        self.assertFalse(decision["render"])


class SampleAndAudioGuardTests(unittest.TestCase):
    def test_packaged_assets_are_unchanged(self):
        for relative, digest in ASSETS.items():
            path = ROOT / relative
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, relative)

    def test_renderer_has_no_synthetic_audio_source(self):
        source = RENDER.read_text(encoding="utf-8")
        self.assertNotIn("anullsrc", source)
        self.assertNotIn("sine=", source)

    def test_example_config_is_marked_and_blocked_without_accept_sample(self):
        cfg = json.loads((EXAMPLES / "config.example.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["sample"], True)
        self.assertEqual(cfg["audio"], "music.m4a")
        self.assertNotIn("silent", cfg)
        photos = [(EXAMPLES / item["path"]).resolve() for item in cfg["photos"]]
        audio = (EXAMPLES / cfg["audio"]).resolve()
        reasons = sample_reasons(cfg, EXAMPLES / "config.example.json", photos, audio)
        self.assertTrue(any("config.example.json" in reason for reason in reasons))
        self.assertTrue(any("占位图" in reason for reason in reasons))
        self.assertTrue(any("示例音乐" in reason for reason in reasons))
        self.assertTrue(any("化名" in reason for reason in reasons))
        with self.assertRaises(MaterialError) as caught:
            validate_sample_use(reasons, True, False)
        self.assertIn("已停止", str(caught.exception))
        self.assertIn("没有改成静音", str(caught.exception))
        validate_sample_use(reasons, True, True)

    def test_real_names_that_overlap_the_sample_couple_are_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "own.m4a"
            make_photo(photo)
            make_music(music)
            cfg = {"lines": [
                {"text": "新郎 张三  &  新娘 李四"},
                {"names": ["王阿姨", "李叔"]},
            ]}
            reasons = sample_reasons(cfg, directory / "customer.json", [photo], music)
        self.assertEqual(reasons, [])
        validate_sample_use(reasons, False, False)

    def test_exact_sample_guest_list_is_blocked_even_with_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "own.m4a"
            make_photo(photo)
            make_music(music)
            cfg = {"lines": [
                {"text": "新郎 张三  &  新娘 李四"},
                {"names": ["王小明", "赵小红", "陈大伟", "刘芳", "周杰", "吴倩"]},
            ]}
            reasons = sample_reasons(cfg, directory / "customer.json", [photo], music)
        self.assertTrue(any("化名" in reason for reason in reasons))

    def test_missing_audio_choice_stops(self):
        with self.assertRaises(MaterialError) as caught:
            resolve_audio({}, Path("/tmp"), "ffprobe")
        self.assertIn("没有 audio", str(caught.exception))
        self.assertIn("不要省略后自动静音", str(caught.exception))

    def test_null_audio_without_opt_in_stops(self):
        with self.assertRaises(MaterialError) as caught:
            resolve_audio({"audio": None}, Path("/tmp"), "ffprobe")
        self.assertIn("不要静音导出", str(caught.exception))

    def test_explicit_silence_is_accepted_by_the_resolver(self):
        self.assertIsNone(resolve_audio({"audio": None, "silent": True}, Path("/tmp"), "ffprobe"))

    def test_missing_audio_file_stops_without_fallback(self):
        with self.assertRaises(MaterialError) as caught:
            resolve_audio({"audio": "missing-song.m4a"}, Path("/tmp/not-a-real-dir"), "ffprobe")
        message = str(caught.exception)
        self.assertIn("配乐文件不存在", message)
        self.assertIn("没有改成静音", message)

    def test_silence_and_a_music_path_conflict(self):
        with self.assertRaises(MaterialError):
            resolve_audio({"audio": "song.m4a", "silent": True}, Path("/tmp"), "ffprobe")

    def test_sample_flag_matrix(self):
        with self.assertRaises(MaterialError):
            validate_sample_use(["占位图"], False, False)
        with self.assertRaises(MaterialError):
            validate_sample_use(["占位图"], True, False)
        with self.assertRaises(MaterialError):
            validate_sample_use(["占位图"], False, True)
        validate_sample_use(["占位图"], True, True)
        with self.assertRaises(MaterialError):
            validate_sample_use([], True, True)
        with self.assertRaises(MaterialError):
            validate_sample_use([], False, True)
        validate_sample_use([], False, False)
        with self.assertRaises(MaterialError):
            validate_sample_use([], "true", False)


class RendererWorkflowTests(unittest.TestCase):
    def config(self, directory, photo, audio=None, silent=False, sample=False, lines=None):
        payload = {
            "font": FONT,
            "photos": [{"path": photo.name, "focus_x": 0.5, "focus_y": 0.4}],
            "lines": lines or LINES,
        }
        if sample:
            payload["sample"] = True
        if silent:
            payload["audio"] = None
            payload["silent"] = True
        elif audio is not None:
            payload["audio"] = audio.name
        return write_json(directory / "customer.json", payload)

    def test_missing_photo_stops_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = write_json(directory / "customer.json", {
                "font": FONT,
                "photos": [{"path": "missing.jpg"}],
                "lines": LINES,
                "audio": "missing.m4a",
            })
            out = directory / "out"
            with self.assertRaises(MaterialError) as caught:
                from render import prepare
                prepare(config, out)
            self.assertIn("照片不存在", str(caught.exception))
            self.assertIn("没有用技能包里的示例照片", str(caught.exception))
            self.assertFalse(out.exists())

    def test_unreadable_audio_stops_before_creating_output(self):
        from render import prepare
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            make_photo(photo)
            (directory / "song.m4a").write_text("not audio", encoding="utf-8")
            config = self.config(directory, photo, directory / "song.m4a")
            out = directory / "out"
            with self.assertRaises(MaterialError) as caught:
                prepare(config, out)
            self.assertIn("没有改成静音", str(caught.exception))
            self.assertFalse(out.exists())
            self.assertFalse((out / "video.mp4").exists())

    def test_copied_placeholder_photo_stops_without_sample_opt_in(self):
        from render import prepare
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "wedding.jpg"
            photo.write_bytes((EXAMPLES / "photos" / "01.jpg").read_bytes())
            music = directory / "own.m4a"
            make_music(music)
            config = self.config(directory, photo, music)
            out = directory / "out"
            with self.assertRaises(MaterialError) as caught:
                prepare(config, out)
            self.assertIn("占位图", str(caught.exception))
            self.assertFalse(out.exists())

    def test_explicit_sample_prepare_still_works(self):
        from render import prepare
        example = json.loads((EXAMPLES / "config.example.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            payload = {
                "sample": True,
                "font": FONT,
                "audio": str(EXAMPLES / "music.m4a"),
                "photos": [{"path": str(EXAMPLES / "photos" / "01.jpg"), "focus_x": 0.5, "focus_y": 0.5}],
                "lines": example["lines"],
            }
            config = write_json(directory / "demo.json", payload)
            blocked = directory / "blocked"
            with self.assertRaises(MaterialError):
                prepare(config, blocked)
            self.assertFalse(blocked.exists())
            out = directory / "prepared"
            _cfg, duration, _travel, _photos, audio = prepare(config, out, accept_sample=True)
            self.assertTrue(audio is not None)
            self.assertGreaterEqual(duration, 20)
            snapshot = json.loads((out / "config.snapshot.json").read_text(encoding="utf-8"))
            self.assertIs(snapshot["sample"], True)
            self.assertFalse(snapshot["silent"])
            self.assertEqual(
                hashlib.sha256((out / "stars.mov").read_bytes()).hexdigest(),
                ASSETS["assets/stars.mov"],
            )

    def test_customer_prepare_records_music_and_explicit_silence(self):
        from render import prepare
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "march.m4a"
            make_photo(photo)
            make_music(music)
            music_out = directory / "with-music"
            prepare(self.config(directory, photo, music), music_out)
            music_snapshot = json.loads((music_out / "config.snapshot.json").read_text(encoding="utf-8"))
            self.assertFalse(music_snapshot["silent"])
            self.assertFalse(music_snapshot["sample"])
            self.assertTrue(music_snapshot["audio"].endswith("march.m4a"))
            silence_out = directory / "silent"
            prepare(self.config(directory, photo, silent=True), silence_out)
            silence_snapshot = json.loads((silence_out / "config.snapshot.json").read_text(encoding="utf-8"))
            self.assertTrue(silence_snapshot["silent"])
            self.assertIsNone(silence_snapshot["audio"])

    def test_customer_music_and_explicit_silence_both_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "march.m4a"
            make_photo(photo)
            make_music(music)
            music_out = directory / "music-out"
            music_run = run_cli(str(self.config(directory, photo, music)), "--out", str(music_out), "--width", "960")
            self.assertEqual(music_run.returncode, 0, music_run.stderr[-2000:])
            self.assert_video(music_out, expect_audio=True)
            command = json.loads((music_out / "command.json").read_text(encoding="utf-8"))
            self.assertTrue(any(str(music) in item for item in command))
            filters = (music_out / "render.filters").read_text(encoding="utf-8")
            self.assertIn("stars.mov", " ".join(command))
            self.assertIn("colorchannelmixer=aa=0.85", filters)
            self.assertIn("colorchannelmixer=aa=0.22", filters)
            self.assertIn("rotate=", filters)
            silence_out = directory / "silence-out"
            silence_run = run_cli(
                str(self.config(directory, photo, silent=True)), "--out", str(silence_out), "--width", "960"
            )
            self.assertEqual(silence_run.returncode, 0, silence_run.stderr[-2000:])
            self.assert_video(silence_out, expect_audio=False)
            silence_filters = (silence_out / "render.filters").read_text(encoding="utf-8")
            self.assertNotIn("afade", silence_filters)
            self.assertIn("colorchannelmixer=aa=0.85", silence_filters)

    def assert_video(self, out, expect_audio):
        video = out / "video.mp4"
        self.assertTrue(video.is_file())
        self.assertEqual(
            hashlib.sha256((out / "stars.mov").read_bytes()).hexdigest(),
            ASSETS["assets/stars.mov"],
        )
        self.assertEqual(
            hashlib.sha256((out / "ring.png").read_bytes()).hexdigest(),
            ASSETS["assets/record.png"],
        )
        self.assertEqual(
            hashlib.sha256((out / "wave.png").read_bytes()).hexdigest(),
            ASSETS["assets/wave.png"],
        )
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        streams = json.loads(probe.stdout)["streams"]
        kinds = [item["codec_type"] for item in streams]
        video_stream = next(item for item in streams if item["codec_type"] == "video")
        self.assertEqual(video_stream["width"], 960)
        self.assertEqual(video_stream["height"], 540)
        self.assertIn("video", kinds)
        if expect_audio:
            self.assertIn("audio", kinds)
        else:
            self.assertNotIn("audio", kinds)
        first = out / "frame-a.jpg"
        second = out / "frame-b.jpg"
        ffmpeg("-ss", "1.0", "-i", str(video), "-frames:v", "1", str(first))
        ffmpeg("-ss", "1.7", "-i", str(video), "-frames:v", "1", str(second))
        self.assertNotEqual(first.read_bytes(), second.read_bytes())

    def test_cli_check_deps_does_not_render_example(self):
        checked = run_cli("--check-deps")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        payload = json.loads(checked.stdout)
        self.assertTrue(payload["dependencies_ok"])
        self.assertFalse(payload["rendered"])
        self.assertNotIn("video", checked.stdout)
        blocked = run_cli("--check-deps", str(EXAMPLES / "config.example.json"))
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("已停止", blocked.stderr)
        self.assertIn("不会渲染", blocked.stderr)
        missing_font = run_cli("--check-deps", "--font", "/no/such/font.ttf")
        self.assertEqual(missing_font.returncode, 1)
        self.assertIn("字体不存在", missing_font.stderr)

    def test_existing_output_directory_stops(self):
        from render import prepare
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "march.m4a"
            make_photo(photo)
            make_music(music)
            out = directory / "out"
            out.mkdir()
            with self.assertRaises(MaterialError) as caught:
                prepare(self.config(directory, photo, music), out)
            self.assertIn("输出目录已存在", str(caught.exception))
            self.assertFalse((out / "video.mp4").exists())

    def test_cli_omitted_audio_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            make_photo(photo)
            config = self.config(directory, photo)
            out = directory / "out"
            result = run_cli(str(config), "--out", str(out))
            self.assertEqual(result.returncode, 1)
            self.assertIn("已停止", result.stderr)
            self.assertIn("没有 audio", result.stderr)
            self.assertFalse((out / "video.mp4").exists())


class DocumentationTests(unittest.TestCase):
    def test_docs_agree_on_the_workflow_fix(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        config = (ROOT / "references" / "config.md").read_text(encoding="utf-8")
        effects = (ROOT / "references" / "effects.md").read_text(encoding="utf-8")
        self.assertIn("v0.2.1", skill)
        self.assertIn("只是安装", skill)
        self.assertIn("--check-deps", skill)
        self.assertIn("--accept-sample", skill)
        self.assertIn('"silent": true', skill)
        self.assertIn("你已明确不要音乐，将导出静音", skill)
        self.assertIn("没有在 Codex 或 WorkBuddy 应用里重跑", skill)
        self.assertNotIn("无音乐可明确先做静音样片", skill)
        self.assertIn("v0.2.1", readme)
        self.assertIn("不要音乐", readme)
        self.assertIn("不会自动静音", readme)
        self.assertNotIn("音乐文件（可选）", readme)
        self.assertNotIn("先出一版静音样片", readme)
        self.assertIn('"silent": true', config)
        self.assertIn("--accept-sample", config)
        self.assertIn("--check-deps", config)
        self.assertNotIn("音乐缺省静音", config)
        self.assertIn("明确选择静音", effects)
        for document in (skill, readme, config):
            self.assertIn("照片", document)
            self.assertLess(document.index("照片"), document.index("音乐"))


class PackageTests(unittest.TestCase):
    def test_zip_root_contains_skill_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "wedding-vinyl-thanks-v0.2.1.zip"
            build_zip(dest)
            with zipfile.ZipFile(dest) as archive:
                names = archive.namelist()
            self.assertEqual(names[0], "SKILL.md")
            self.assertIn("README.md", names)
            self.assertIn("LICENSE", names)
            self.assertIn("assets/stars.mov", names)
            self.assertIn("assets/record.png", names)
            self.assertIn("assets/wave.png", names)
            self.assertIn("examples/config.example.json", names)
            self.assertIn("scripts/render.py", names)
            self.assertFalse(any(name.startswith("/") or name.startswith("wedding-vinyl-thanks/") for name in names))
            self.assertFalse(any(name.endswith(".pyc") or name.endswith(".zip") for name in names))


if __name__ == "__main__":
    unittest.main()
