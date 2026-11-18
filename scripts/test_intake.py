"""v0.2.2 intake and guard checks.

These are local script tests. They are not a Codex or WorkBuddy conversation.
"""
import hashlib, json, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path

from gate import (
    ORIGINAL_REFERENCE,
    GateError,
    build_manifest,
    decide,
    extract_user_audio,
    filter_file_option,
    is_vague_request,
    write_test_tone,
)
from layout import layout_lines
from package_skill import build

ROOT = Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
STARS = "d1c484e47f2008ab2a7d547453c4f4b9329047a800dc6b4e851fe57fa117e4b5"
WB_DESCRIPTION = "在WorkBuddy桌面端引导新手黑胶婚礼致谢视频，替换照片、名单、文案和音乐，保留闪烁星光、音波装饰和滚动文字，导出横屏MP4。"


def full_state(**overrides):
    state = {
        "intent": "personal",
        "utterance": "这是我的照片、姓名、婚期、分组名单和感谢文字，音乐用 march.m4a",
        "photos": True,
        "names": True,
        "date": True,
        "lists": True,
        "thanks": True,
        "audio": True,
        "audio_label": "march.m4a",
        "confirmed": False,
        "photo_count": 1,
        "width": 1920,
    }
    state.update(overrides)
    return state


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def make_photo(path):
    ffmpeg("-f", "lavfi", "-i", "color=c=0x336699:s=80x80", "-frames:v", "1", str(path))


def make_music(path):
    # Regression fixture only. Customer packages do not tell the assistant to do this.
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=523:duration=2", "-c:a", "aac", str(path))


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return Path(path)


class DecisionTests(unittest.TestCase):
    def test_install_checks_dependencies_and_does_not_render(self):
        decision = decide({"intent": "install", "utterance": "装好了"})
        self.assertEqual(decision["action"], "acknowledge_install")
        self.assertFalse(decision["render"])
        self.assertEqual(decision["tell_user"], "技能已经装好。请发你要放进视频的照片。")
        self.assertFalse(decision["offer_choice_menu"])
        self.assertFalse(decision["show_technical_details"])

    def test_vague_run_with_no_materials_asks_for_photos(self):
        for phrase in ("给我跑一下", "试一下", "做一个", "帮我跑一下", "测试一下"):
            decision = decide({
                "intent": "personal",
                "utterance": phrase,
                "placeholders_accepted": True,
                "synthetic_tone_accepted": True,
                "confirmed": True,
                "audio": True,
            })
            self.assertFalse(decision["render"], phrase)
            self.assertEqual(decision["action"], "ask_photos", phrase)
            self.assertEqual(decision["tell_user"], "请先发你自己的照片。")
            self.assertIn("不是同意", decision["assistant_note"])
            self.assertNotIn("你挑一个", decision["tell_user"])
            self.assertTrue(is_vague_request(phrase))

    def test_vague_request_cannot_confirm_even_when_flags_are_set(self):
        decision = decide(full_state(utterance="给我跑一下", confirmed=True))
        self.assertFalse(decision["render"])
        self.assertNotEqual(decision["action"], "render")

    def test_photos_only_asks_for_copy(self):
        decision = decide(full_state(
            names=False, date=False, lists=False, thanks=False, audio=False, audio_label="",
        ))
        self.assertEqual(decision["action"], "ask_copy")
        self.assertEqual(decision["missing_copy"], ["names", "date", "lists", "thanks"])
        self.assertFalse(decision["render"])

    def test_partial_copy_asks_only_for_the_missing_part(self):
        decision = decide(full_state(lists=False, thanks=False, audio=False, audio_label=""))
        self.assertEqual(decision["missing_copy"], ["lists", "thanks"])
        self.assertFalse(decision["render"])

    def test_photos_and_copy_without_music_asks_for_bgm(self):
        decision = decide(full_state(utterance="照片和文字都齐了", audio=False, audio_label=""))
        self.assertEqual(decision["action"], "ask_audio")
        self.assertIn("原片同款", decision["tell_user"])
        self.assertIn("自己选歌", decision["tell_user"])
        self.assertIn("明确静音", decision["tell_user"])
        self.assertIn(ORIGINAL_REFERENCE, decision["tell_user"])
        self.assertIn("包里没有这首歌", decision["tell_user"])
        self.assertFalse(decision["render"])
        self.assertFalse(decision["offer_choice_menu"])

    def test_complete_material_waits_for_confirmation(self):
        waiting = decide(full_state())
        self.assertEqual(waiting["action"], "confirm_before_render")
        self.assertFalse(waiting["render"])
        self.assertIn("march.m4a", waiting["summary"])
        self.assertNotIn("将导出静音", waiting["summary"])
        done = decide(full_state(confirmed=True))
        self.assertEqual(done["action"], "render")
        self.assertTrue(done["render"])

    def test_explicit_silence_is_summarized_before_render(self):
        state = full_state(utterance="照片和文字都齐了，不要音乐", audio=False, audio_label="")
        waiting = decide(state)
        self.assertFalse(waiting["render"])
        self.assertIn("你已明确不要音乐，将导出静音", waiting["summary"])
        done = decide(dict(state, confirmed=True))
        self.assertEqual(done["action"], "render_silent")
        self.assertTrue(done["render"])

    def test_silence_phrase_is_ignored_until_photos_and_copy_exist(self):
        decision = decide({"intent": "personal", "utterance": "不要音乐"})
        self.assertEqual(decision["action"], "ask_photos")
        self.assertFalse(decision["render"])

    def test_placeholder_consent_without_test_tone_still_asks_for_music(self):
        decision = decide(full_state(
            utterance="我同意使用占位照片和化名来看演示",
            placeholders_accepted=True,
            synthetic_tone_accepted=True,
            audio=False,
            audio_label="",
            confirmed=True,
        ))
        self.assertEqual(decision["action"], "ask_audio")
        self.assertFalse(decision["render"])
        self.assertNotIn("合成测试音，不是你的歌曲", decision["tell_user"])

    def test_synthetic_tone_requires_its_own_consent(self):
        refused = decide(full_state(
            utterance="我同意使用占位照片",
            placeholders_accepted=True,
            synthetic_tone_accepted=True,
            audio=False,
            audio_label="",
        ))
        self.assertNotEqual(refused["action"], "render_synthetic")
        agreed = decide(full_state(
            utterance="我同意使用占位照片，并且同意合成测试音",
            placeholders_accepted=True,
            synthetic_tone_accepted=True,
            audio=False,
            audio_label="",
            confirmed=True,
        ))
        self.assertEqual(agreed["action"], "render_synthetic")
        self.assertIn("不是你的歌曲", agreed["summary"])

    def test_original_choice_without_a_file_cannot_render(self):
        decision = decide(full_state(
            utterance="用原片同款",
            music_choice="原片同款",
            audio=False,
            audio_label="",
            confirmed=True,
        ))
        self.assertEqual(decision["action"], "ask_original_file")
        self.assertFalse(decision["render"])
        self.assertIn("不会去网上找", decision["tell_user"])
        self.assertNotIn("http", decision["tell_user"])
        self.assertIsNone(decision.get("source_video"))

    def test_supplied_audio_is_reused_and_named_in_the_summary(self):
        decision = decide(full_state(utterance="就用我发的 march.m4a，原片同款", confirmed=True))
        self.assertEqual(decision["action"], "render")
        self.assertIn("音乐文件：march.m4a", decision["summary"])
        self.assertIn(ORIGINAL_REFERENCE, decision["summary"])
        self.assertNotEqual(decision["summary"].strip(), ORIGINAL_REFERENCE)

    def test_other_song_asks_which_piece(self):
        decision = decide(full_state(utterance="我想用别的歌，不是这首", audio=False, audio_label=""))
        self.assertEqual(decision["action"], "ask_audio")
        self.assertIn("哪一首", decision["tell_user"])
        self.assertFalse(decision["render"])

    def test_extract_requires_consent_and_keeps_the_whole_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            clip = directory / "user-video.mp4"
            silent = directory / "no-audio.mp4"
            dest = directory / "taken.m4a"
            ffmpeg(
                "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-shortest", "-c:v", "libx264", "-c:a", "aac", str(clip),
            )
            ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", "-c:v", "libx264", str(silent))
            with self.assertRaises(GateError) as missing_consent:
                extract_user_audio(clip, dest, "用原片同款")
            self.assertIn("不会自动获得歌曲版权", str(missing_consent.exception))
            with self.assertRaises(GateError) as no_track:
                extract_user_audio(silent, dest, "同意提取")
            self.assertIn("没有音轨", str(no_track.exception))
            self.assertIn("没有改成静音", str(no_track.exception))
            with self.assertRaises(GateError) as packaged:
                extract_user_audio(ROOT / "assets" / "stars.mov", dest, "同意提取")
            self.assertIn("不能从技能包", str(packaged.exception))
            taken = extract_user_audio(clip, dest, "我有权使用这段声音，同意提取")
            self.assertIn("整条音轨", taken["note"])
            self.assertIn("不构成歌曲授权", taken["note"])
            self.assertNotIn("纯净", taken["note"])
            self.assertNotIn("无人声", taken["note"])
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", taken["path"]],
                capture_output=True, text=True, check=True,
            )
            kinds = [item["codec_type"] for item in json.loads(probe.stdout)["streams"]]
            self.assertEqual(kinds, ["audio"])

    def test_already_installed_does_not_repeat_the_install_line(self):
        decision = decide({"intent": "install", "utterance": "装好了", "already_installed": True})
        self.assertEqual(decision["tell_user"], "请发你要放进视频的照片。")
        self.assertNotIn("已经装好", decision["tell_user"])
        self.assertFalse(decision["render"])

    def test_user_reply_has_no_technical_menu(self):
        decision = decide({"intent": "install", "utterance": "装好了"})
        for banned in ("FFMPEG=", "你挑一个", "兼容补丁", ".tools", "/System/Library"):
            self.assertNotIn(banned, decision["tell_user"])

    def test_limits_are_declared(self):
        decision = decide({"intent": "install", "utterance": "装好了"})
        self.assertTrue(decision["limits"]["agent_flags_are_not_a_security_boundary"])


class FileGuardTests(unittest.TestCase):
    def config(self, directory, photo, audio=None, silent=False, synthetic=False, names=None):
        payload = {
            "font": FONT,
            "photos": [{"path": photo.name, "focus_x": 0.5, "focus_y": 0.4}],
            "lines": [
                {"text": "谢 幕 答 谢", "heading": True},
                {"text": "2026.06.18"},
                {"text": "新郎 陈一  &  新娘 林二"},
                {"text": "感谢你们到场"},
                {"names": names or ["周叔", "吴姨", "周叔"]},
                {"text": "感谢一路相伴"},
            ],
        }
        if synthetic:
            payload["audio"] = "synthetic-test-tone.wav"
            payload["audio_kind"] = "synthetic-test-tone"
        elif silent:
            payload["audio"] = None
            payload["silent"] = True
        elif audio is not None:
            payload["audio"] = audio.name
        return write_json(directory / "customer.json", payload)

    def test_missing_photo_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = write_json(directory / "customer.json", {
                "font": FONT,
                "photos": [{"path": "missing.jpg"}],
                "lines": [{"text": "谢谢"}],
                "audio": "missing.m4a",
            })
            with self.assertRaises(GateError) as caught:
                build_manifest(full_state(confirmed=True), config, directory / "out", directory / "manifest.json")
            self.assertIn("照片不存在", str(caught.exception))
            self.assertFalse((directory / "out").exists())

    def test_bad_audio_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            make_photo(photo)
            (directory / "song.m4a").write_text("not audio", encoding="utf-8")
            config = self.config(directory, photo, directory / "song.m4a")
            with self.assertRaises(GateError) as caught:
                build_manifest(full_state(confirmed=True), config, directory / "out", directory / "manifest.json")
            self.assertIn("已停止", str(caught.exception))
            self.assertFalse((directory / "out" / "video.mp4").exists())

    def test_silence_flag_without_the_phrase_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            make_photo(photo)
            config = self.config(directory, photo, silent=True)
            with self.assertRaises(GateError) as caught:
                build_manifest(full_state(confirmed=True), config, directory / "out", directory / "manifest.json")
            self.assertIn("不要音乐", str(caught.exception))

    def test_example_photo_is_not_a_customer_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "wedding.jpg"
            photo.write_bytes((ROOT / "examples" / "photos" / "01.jpg").read_bytes())
            music = directory / "march.m4a"
            make_music(music)
            config = self.config(directory, photo, music)
            with self.assertRaises(GateError) as caught:
                build_manifest(full_state(confirmed=True), config, directory / "out", directory / "manifest.json")
            self.assertIn("开发用示例", str(caught.exception))

    def test_asset_graphic_cannot_be_used_as_a_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = write_json(directory / "customer.json", {
                "font": FONT,
                "photos": [{"path": str(ROOT / "assets" / "record.png")}],
                "lines": [{"text": "谢谢"}],
                "audio": "march.m4a",
            })
            with self.assertRaises(GateError) as caught:
                build_manifest(full_state(confirmed=True), config, directory / "out", directory / "manifest.json")
            self.assertIn("效果素材", str(caught.exception))

    def test_confirmed_manifest_records_real_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "march.m4a"
            make_photo(photo)
            make_music(music)
            config = self.config(directory, photo, music)
            manifest = build_manifest(
                full_state(confirmed=True), config, directory / "out", directory / "manifest.json"
            )
            self.assertTrue(manifest["encode_allowed"])
            self.assertTrue(manifest["limits"]["agent_flags_are_not_a_security_boundary"])
            self.assertEqual(manifest["photos"][0]["sha256"], hashlib.sha256(photo.read_bytes()).hexdigest())
            self.assertEqual(manifest["audio"]["sha256"], hashlib.sha256(music.read_bytes()).hexdigest())
            self.assertIn("march.m4a", manifest["summary"])
            self.assertFalse((directory / "out").exists())

    def test_render_without_manifest_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            make_photo(photo)
            config = self.config(directory, photo, silent=True)
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "render.py"), str(config), "--out", str(directory / "out")],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("已停止", result.stderr)
            self.assertFalse((directory / "out").exists())

    def test_prepare_keeps_long_chinese_names_and_hold(self):
        names = [f"欧阳测试{i:02d}" for i in range(1, 25)] + ["欧阳测试01"]
        rows = layout_lines([{"names": names}])
        flat = [part for line, _heading, _size in rows for part in line.split("　　")]
        self.assertEqual(flat, names)
        with self.assertRaises(ValueError):
            layout_lines([{"names": ["非常长的称谓" * 8]}])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            photo = directory / "own.jpg"
            music = directory / "march.m4a"
            make_photo(photo)
            make_music(music)
            config = self.config(directory, photo, music, names=names)
            build_manifest(full_state(confirmed=True), config, directory / "out", directory / "manifest.json")
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "render.py"), str(config),
                 "--manifest", str(directory / "manifest.json"), "--out", str(directory / "out"), "--prepare-only"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-1500:])
            timing = json.loads((directory / "out" / "text-timing.json").read_text(encoding="utf-8"))
            visible = "".join(item["text"] for item in timing)
            for name in names:
                self.assertIn(name, visible)
            snapshot = json.loads((directory / "out" / "config.snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["hold_seconds"], 6)
            self.assertGreaterEqual(snapshot["duration"], 20)
            self.assertAlmostEqual(snapshot["scroll_ends_at"], snapshot["duration"] - 6, places=2)

    def test_write_test_tone_refuses_without_consent_and_labels_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "synthetic-test-tone.wav"
            with self.assertRaises(GateError):
                write_test_tone({"utterance": "给我跑一下", "confirmed": True, "synthetic_tone_accepted": True}, dest)
            self.assertFalse(dest.exists())
            write_test_tone({
                "utterance": "我同意合成测试音",
                "confirmed": True,
                "synthetic_tone_accepted": True,
            }, dest)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(dest)],
                capture_output=True, text=True, check=True,
            )
            kinds = [item["codec_type"] for item in json.loads(probe.stdout)["streams"]]
            self.assertIn("audio", kinds)
            with self.assertRaises(GateError):
                write_test_tone({
                    "utterance": "我同意合成测试音",
                    "confirmed": True,
                    "synthetic_tone_accepted": True,
                }, Path(tmp) / "music.m4a")


class FfmpegAndDocTests(unittest.TestCase):
    def test_filter_option_switches_at_ffmpeg_9(self):
        self.assertEqual(filter_file_option(6, "complex"), "-filter_complex_script")
        self.assertEqual(filter_file_option(7, "complex"), "-/filter_complex")
        self.assertEqual(filter_file_option(9, "complex"), "-/filter_complex")
        self.assertEqual(filter_file_option(6, "video"), "-filter_script:v")
        self.assertEqual(filter_file_option(7, "video"), "-/filter:v")
        self.assertEqual(filter_file_option(9, "video"), "-/filter:v")

    def test_installed_ffmpeg_accepts_legacy_script_option_only(self):
        legacy = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filter_complex_script", "/no/such.filters", "-f", "lavfi", "-i", "color=black:s=16x16", "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        modern = subprocess.run(
            ["ffmpeg", "-hide_banner", "-/filter_complex", "/no/such.filters"],
            capture_output=True, text=True,
        )
        self.assertIn("filter_complex_script", legacy.stderr)
        self.assertNotIn("Unrecognized option", legacy.stderr)
        self.assertIn("Unrecognized option", modern.stderr)
        version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
        self.assertIn("6.1.1", version.stdout.splitlines()[0])

    def test_looping_inputs_are_duration_limited(self):
        source = (ROOT / "scripts" / "render.py").read_text(encoding="utf-8")
        compact = source.replace(" ", "").replace("\n", "")
        self.assertIn('"-stream_loop","-1","-t",dur,"-i","stars.mov"', compact)
        self.assertNotIn('"-stream_loop","-1","-i"', compact)
        self.assertNotIn('"-loop","1"', compact)
        self.assertIn("loop=loop=-1:size=1:start=0", source)
        self.assertIn("trim=duration=", source)
        self.assertIn('"-filter_complex_threads","1"', compact)

    def test_renderer_does_not_synthesize_audio(self):
        source = (ROOT / "scripts" / "render.py").read_text(encoding="utf-8")
        self.assertNotIn("sine=", source)
        self.assertNotIn("anullsrc", source)
        self.assertIn("0.523599*sin(2*PI*t/16)", source)
        self.assertIn("stars_opacity", source)
        self.assertIn("0.85", source)
        self.assertIn("0.22", source)

    def test_stars_match_the_workbuddy_v020_package(self):
        self.assertEqual(hashlib.sha256((ROOT / "assets" / "stars.mov").read_bytes()).hexdigest(), STARS)

    def test_check_environment_runs_ffmpeg_and_does_not_render(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_environment.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "运行环境已就绪。")
        details = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_environment.py"), "--details"],
            capture_output=True, text=True,
        )
        self.assertEqual(details.returncode, 0, details.stderr)
        payload = json.loads(details.stdout)
        self.assertTrue(payload["ready"])
        self.assertFalse(payload["rendered"])
        self.assertFalse(payload["changed_system"])
        self.assertFalse(payload["removed_quarantine"])
        self.assertFalse(payload["signed_binaries"])
        self.assertIn("6.1.1", payload["ffmpeg_version"])
        self.assertFalse(payload["ffmpeg_9_executed"])
        self.assertNotIn("FFMPEG=", payload["user_message"])
        source = (ROOT / "scripts" / "check_environment.py").read_text(encoding="utf-8")
        for banned in ("codesign", "xattr", "com.apple.quarantine", "spctl"):
            self.assertNotIn(banned, source)

    def test_docs_and_metadata(self):
        codex = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        workbuddy = (ROOT / "packaging" / "workbuddy" / "SKILL.md").read_text(encoding="utf-8")
        workflow = (ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
        self.assertIn("name: wedding-vinyl-thanks\n", codex)
        self.assertNotIn("display_name:", codex)
        self.assertIn("name: wedding-vinyl-thanks-workbuddy\n", workbuddy)
        self.assertIn("display_name: 黑胶婚礼致谢 · 星光音波版\n", workbuddy)
        self.assertIn("description: " + WB_DESCRIPTION, workbuddy)
        for document in (codex, workbuddy, workflow):
            self.assertIn("给我跑一下", document)
            self.assertIn("技能已经装好。请发你要放进视频的照片。", document)
            self.assertIn("运行环境已就绪", document)
            self.assertIn("不要给「打兼容补丁", document)
            self.assertIn("不要临时签名", document)
            self.assertIn("合成测试音", document)
            self.assertIn("不要音乐", document)
            self.assertIn("安全边界", document)
            self.assertIn("不包括第三方音乐", document)
            self.assertIn("原片同款", document)
            self.assertNotIn("你挑一个", document)


class PackageTests(unittest.TestCase):
    def test_both_zips_have_skill_at_the_root_and_original_stars(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            codex = directory / "codex.zip"
            workbuddy = directory / "workbuddy.zip"
            build(codex, ROOT / "SKILL.md", ["README.md"])
            build(workbuddy, ROOT / "packaging" / "workbuddy" / "SKILL.md")
            for path, skill_name in ((codex, "wedding-vinyl-thanks"), (workbuddy, "wedding-vinyl-thanks-workbuddy")):
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    skill = archive.read("SKILL.md").decode("utf-8")
                    stars = archive.read("assets/stars.mov")
                    blob = "\n".join(
                        archive.read(name).decode("utf-8", errors="ignore")
                        for name in names if name.endswith((".md", ".py"))
                    )
                self.assertEqual(names[0], "SKILL.md")
                self.assertIn(f"name: {skill_name}", skill)
                self.assertNotIn("examples/", "\n".join(names))
                self.assertFalse(any(name.startswith("scripts/test_") for name in names))
                self.assertEqual(hashlib.sha256(stars).hexdigest(), STARS)
                self.assertIn("assets/record.png", names)
                self.assertIn("assets/wave.png", names)
                self.assertIn("LICENSE", names)
                self.assertIn("scripts/gate.py", names)
                self.assertIn("scripts/render.py", names)
                audio_suffixes = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}
                self.assertFalse(any(Path(name).suffix.lower() in audio_suffixes for name in names))
                self.assertNotIn("http://", blob.lower())
                self.assertNotIn("https://music.", blob.lower())
                self.assertIn("包里没有这首歌", skill)


if __name__ == "__main__":
    unittest.main()
