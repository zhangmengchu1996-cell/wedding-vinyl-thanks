# 配置说明

UTF-8 JSON，相对路径以配置文件目录为准。助手填写，用户无需改配置。客户配置和 `examples/config.example.json` 要分开：示例只给开发者看格式、做回归，里面是占位图和化名。

客户视频必需：

- photos：数组，每项包含 path，可选 focus_x/focus_y，均为 0 至 1。路径必须指向用户自己的照片。文件不存在就停止，不要换成 `examples/photos`。
- lines：逐行内容。姓名使用用户给出的原文，不猜测、不替换、不去重。
- audio：用户提供的音乐文件路径。不能省略。

用户明确说不要音乐时，才同时写成 `"audio": null` 和 `"silent": true`。只写 null、留空、或整项不写，都会停止，不会自动静音，也不会生成提示音。音乐文件打不开或没有音轨时同样停止，不要改成静音再导出。

可选：duration（最短目标秒数，默认按文字自动计算，至少 20 秒）；font（本地中文字体路径，默认 macOS 宋体）；title（备注）；effects（效果强度）。客户配置不要写 sample。

客户配置示例（把路径和姓名换成刚收到的内容，不要原样拿去渲染）：

```json
{
  "photos": [{"path": "客户照片/01.jpg", "focus_x": 0.5, "focus_y": 0.5}],
  "font": "/本机中文字体.ttf",
  "audio": "客户音乐.m4a",
  "effects": {"stars_opacity": 0.85, "wave_opacity": 0.22},
  "lines": [
    {"text": "谢 幕 答 谢", "heading": true},
    {"text": "婚期，例如 2026.10.01"},
    {"text": ""},
    {"text": "新郎 客户姓名  &  新娘 客户姓名"},
    {"text": "感谢你们，奔赴这场相聚"},
    {"text": "亲友团", "heading": true},
    {"names": ["这里换成客户名单里的整个人名"]},
    {"text": "感谢你们，见证我们的幸福"}
  ]
}
```

用户明确不要音乐时，把音频两项写成：

```json
"audio": null,
"silent": true
```

开发者示例才使用 `"sample": true`，并且命令行同时加上 `--accept-sample`。两项缺一就停止。客户视频两样都不要。示例命令：

```bash
python3 -X utf8 scripts/render.py examples/config.example.json --out 新的输出目录 --accept-sample
```

只检查 FFmpeg、FFprobe 和可选字体，不读取配置、不导出。结果里的 `default_font_present` 只说明 macOS 默认宋体在不在；为 false 时改找本机中文字体，不要改跑示例：

```bash
python3 -X utf8 scripts/render.py --check-deps
```

名单使用 names 数组，按整个人名换行，顺序与重名保留。“、”分隔的名单须设置 name_list=true 或先转为 names；不对普通正文的顿号自动拆分。无分隔长名单先整理成 names。单个人名超过 20 个全角字符时提示调整称谓，不截断。普通 text 允许按字换行；heading=true 表示金色标题，空 text 为空行。

长名单自动延长，不超过 28 像素/秒；开头 8 秒、结尾 6 秒停留。有音乐则循环补足并首尾淡入淡出；未做自动卡点或响度归一。静音只在 `"silent": true` 且 `"audio": null` 时出现，星光和音波仍然绘制。

effects 两个透明度范围 0 至 1，0 关闭，1 完全显示，默认均开启。音波为装饰图形。照片直切，唱片轻摆，星芒循环闪烁。所有效果素材随包携带，缺失就停止，不用别的文件顶替。

输出：video.mp4、config.snapshot.json、text-timing.json、sources.json、verification.json 及预览图。每次使用新输出目录。snapshot 里的 silent 为 true 表示这次是用户明确要求的静音；sample 为 true 表示这次用的是示例素材。

开发者回归（不会启动 Codex 或 WorkBuddy）：

```bash
cd scripts && python3 -X utf8 -m unittest test_layout.py test_intake.py
```

覆盖：只安装、没有材料、部分材料、含音乐的完整材料、明确演示、明确静音、文件缺失。
