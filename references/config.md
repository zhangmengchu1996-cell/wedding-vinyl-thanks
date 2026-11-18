# 配置说明

UTF-8 JSON，相对路径以配置文件目录为准。助手填写，用户不用改配置，也不用自己运行命令。

客户视频必需：

- photos：数组，每项包含 path，可选 focus_x / focus_y，范围 0 至 1。路径必须是用户自己的照片，文件必须真实存在。
- lines：用户给出的文字。名单用 names 数组，整个人名换行，不猜测、不替换、不去重。
- audio：用户的音乐文件路径。不能省略。

用户原话明确不要音乐时，才写成 `"audio": null` 和 `"silent": true`。只写 null、留空或整项不写，都会停止，不会自动静音。

用户另外明确同意合成测试音时，才使用：

```json
"audio": "synthetic-test-tone.wav",
"audio_kind": "synthetic-test-tone"
```

这个文件只能由 `scripts/gate.py write-test-tone` 在同意之后写出，汇总里必须写明它不是客户的歌曲。

开发者仓库里的 `examples/` 不是客户默认配置，安装包不包含它。配置不要指向效果素材 `assets/record.png`、`assets/wave.png`、`assets/stars.mov`。

导出前先写清单。清单记录照片和音乐的 SHA-256、用户原话、白话汇总和 FFmpeg 版本。渲染时会重新计算哈希；对不上就停止。助手填写的原话不是安全边界，但缺文件、坏音频、未确认和覆盖旧目录会被脚本拦住。

```bash
python3 -X utf8 scripts/gate.py manifest --state 状态.json --config 客户配置.json --out 新的输出目录 --manifest 清单.json
python3 -X utf8 scripts/render.py 客户配置.json --manifest 清单.json --out 新的输出目录
```

正式宽度是 1920。只有原话里有「预览」才用 `--width 960`。

名单使用 names 数组，按整个人名换行，顺序与重名保留。“、”分隔的名单须设置 name_list=true 或先转为 names。单个人名超过 20 个全角字符时提示调整称谓，不截断。普通 text 允许按字换行。heading=true 表示金色标题。

长名单自动延长，不超过 28 像素/秒。开头约 8 秒，滚动在结束前 6 秒停住，结尾至少停留 6 秒。有音乐则循环补足并首尾淡入淡出。静音只在用户明确不要音乐时出现，星光和音波仍然绘制。

effects 默认 stars_opacity=0.85、wave_opacity=0.22。缺效果素材就停止。

输出目录必须是新的。输出包括 video.mp4、config.snapshot.json、text-timing.json、sources.json、verification.json 和首、中、尾预览图。snapshot 里的 hold_seconds 是 6。

只检查依赖、不导出：

```bash
python3 -X utf8 scripts/check_environment.py
```

FFmpeg 6.1 已在本机实际启动。FFmpeg 9.0 移除了 `-filter_complex_script`，脚本会改用 `-/filter_complex` 读取同一份滤镜图。没有 9.0 二进制的环境不能声称已经跑过 9.0。
