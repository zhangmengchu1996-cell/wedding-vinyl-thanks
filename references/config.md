# 配置说明

UTF-8 JSON，相对路径以配置文件目录为准。助手填写，用户无需改配置。

必需：photos（数组，每项包含path，可选focus_x/focus_y，均为0至1）；lines（逐行内容）。
可选：duration（最短目标秒数，默认按文字自动计算，至少20秒）；audio（音乐路径或null）；font（本地中文字体路径，默认macOS宋体）；title（备注）；effects（效果强度）。

示例：
```json
{
  "duration": 30,
  "photos": [{"path":"photos/01.jpg","focus_x":0.5,"focus_y":0.5}],
  "font": "/本机中文字体.ttf",
  "audio": "music.m4a",
  "effects": {"stars_opacity":0.85,"wave_opacity":0.22},
  "lines": [
    {"text":"谢 幕 答 谢","heading":true},
    {"text":"2026.10.01"},
    {"text":""},
    {"text":"新郎 张三  &  新娘 李四"},
    {"text":"感谢你们，奔赴这场相聚"},
    {"text":"亲友团","heading":true},
    {"names":["王小明","赵小红","陈大伟","刘芳"]},
    {"text":"感谢你们，见证我们的幸福"}
  ]
}
```

名单使用names数组，按整个人名换行，顺序与重名保留。“、”分隔的名单须设置name_list=true或先转为names；不对普通正文的顿号自动拆分。无分隔长名单先整理成names。单个人名超过20个全角字符时提示调整称谓，不截断。普通text允许按字换行；heading=true表示金色标题，空text为空行。

长名单自动延长，不超过28像素/秒；开头8秒、结尾6秒停留。音乐缺省静音，有音乐则循环补足并首尾淡入淡出；未做自动卡点或响度归一。

effects两个透明度范围0至1，0关闭，1完全显示，默认均开启。音波为装饰图形。照片直切，唱片轻摆，星芒循环闪烁。所有效果素材随包携带。

输出：video.mp4、config.snapshot.json、text-timing.json、sources.json、verification.json及预览图。每次使用新输出目录。
