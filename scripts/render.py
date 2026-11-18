#!/usr/bin/env python3
"""Deterministic local vinyl credits renderer. Python stdlib + FFmpeg only.

Customer renders require the user's own photos, copy, and either a music file
or an explicit silent opt-in. Bundled examples stay sample-only.
"""
import argparse, hashlib, json, math, os, random, shutil, struct, subprocess, sys, zlib
from pathlib import Path
from layout import layout_lines

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
SAMPLE_COUPLE = "新郎 张三  &  新娘 李四"
SAMPLE_GUESTS = ("王小明", "赵小红", "陈大伟", "刘芳", "周杰", "吴倩")

class MaterialError(RuntimeError):
    """Stop. Do not substitute example media, a generated tone, or silence."""

def save_text(path,text):
    path.write_text(text,encoding="utf-8")

def png(path,w,h,pixel):
    def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
    data=bytearray()
    for y in range(h):
        data.append(0)
        for x in range(w):data.extend(pixel(x,y))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b''))

def binary(name):
    v=os.environ.get(name.upper()) or shutil.which(name)
    if v:return v
    p=Path('/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static')/name
    if p.exists():return str(p)
    raise ValueError('找不到 '+name+'；请安装或设置 '+name.upper())

def require_tool(name):
    try:
        return binary(name)
    except ValueError as exc:
        raise MaterialError(str(exc) + "。已停止，没有改跑示例视频。") from exc

def run(args,cwd=None):
    r=subprocess.run(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-6000:])
    return r.stdout

def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inside(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False

def bundled_hashes():
    photos=set()
    photo_dir=EXAMPLES / "photos"
    if photo_dir.is_dir():
        for item in photo_dir.iterdir():
            if item.is_file():
                photos.add(sha256_file(item))
    music=EXAMPLES / "music.m4a"
    return photos, (sha256_file(music) if music.is_file() else None)

def sample_reasons(cfg, config_path, photos, audio):
    """Reasons this render is using developer sample content. Empty means customer content."""
    reasons=[]
    example_cfg=EXAMPLES / "config.example.json"
    if example_cfg.is_file() and Path(config_path).resolve()==example_cfg.resolve():
        reasons.append("配置是 examples/config.example.json")
    photo_hashes, music_hash=bundled_hashes()
    for photo in photos:
        if inside(photo, EXAMPLES) or sha256_file(photo) in photo_hashes:
            reasons.append("照片使用了技能包示例占位图：" + Path(photo).name)
    if audio is not None and (inside(audio, EXAMPLES) or (music_hash and sha256_file(audio)==music_hash)):
        reasons.append("配乐使用了技能包示例音乐")
    texts=[]; guests=[]
    for row in cfg.get("lines") or []:
        if isinstance(row, str):
            texts.append(row)
        elif isinstance(row, dict):
            if isinstance(row.get("text"), str):
                texts.append(row["text"])
            if isinstance(row.get("names"), list):
                guests.extend(row["names"])
    if SAMPLE_COUPLE in texts and all(name in guests for name in SAMPLE_GUESTS):
        reasons.append("文案使用了示例化名（张三、李四和示例亲友名单）")
    unique=[]
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique

def validate_sample_use(reasons, sample_flag, accept_sample):
    if sample_flag is not True and sample_flag is not False:
        raise MaterialError("sample 只能是 true 或 false。客户视频不要写 sample。")
    if reasons and not (sample_flag is True and accept_sample):
        detail="；".join(reasons)
        raise MaterialError(
            "检测到技能包自带的示例内容，不能当作客户成片：" + detail
            + "。已停止，没有导出，也没有改成静音。"
            + "只有用户明确要求演示时，配置写 \"sample\": true，并且命令行加上 --accept-sample。"
        )
    if (sample_flag is True or accept_sample) and not reasons:
        raise MaterialError(
            "配置标了示例或带了 --accept-sample，但这份材料不是技能包示例。"
            + "客户视频请去掉 sample 和 --accept-sample。"
        )

def resolve_audio(cfg, base, probe):
    """Return a music file, or None only when the user explicitly opted into silence."""
    if "silent" in cfg and cfg["silent"] is not True and cfg["silent"] is not False:
        raise MaterialError("silent 只能是 true 或 false。用户明确不要音乐时才设为 true，并同时把 audio 设为 null。")
    silent=cfg.get("silent") is True
    if "audio" not in cfg:
        raise MaterialError(
            "配置里没有 audio。请填写用户提供的音乐文件路径；"
            "只有用户明确说不要音乐时，才设置 \"audio\": null 且 \"silent\": true。"
            "不要省略后自动静音，也不要生成提示音。"
        )
    audio_value=cfg.get("audio")
    if isinstance(audio_value, str) and not audio_value.strip():
        audio_value=""
    if silent and audio_value is None:
        return None
    if silent and audio_value is not None:
        raise MaterialError("silent 为 true 时 audio 必须是 null。请只保留一种：音乐文件，或用户明确要求的静音。")
    if audio_value is None or audio_value=="":
        raise MaterialError(
            "audio 为空，但没有 \"silent\": true。缺少音乐时请停下说明，不要静音导出。"
            "若用户明确不要音乐，设置 \"audio\": null 且 \"silent\": true。"
        )
    if not isinstance(audio_value, str):
        raise MaterialError("audio 必须是音乐文件路径，或在用户明确要求静音时为 null。")
    audio=Path(audio_value).expanduser()
    if not audio.is_absolute():
        audio=base / audio
    audio=audio.resolve()
    if not audio.is_file():
        raise MaterialError(f"配乐文件不存在：{audio}。已停止，没有改成静音或替换成其他音频。请核对路径后重试。")
    try:
        meta=json.loads(run([probe, "-v", "error", "-show_streams", "-of", "json", str(audio)]))
    except RuntimeError as exc:
        detail=str(exc).strip().splitlines()[-1][:300] if str(exc).strip() else ""
        raise MaterialError(f"配乐无法读取：{audio}。已停止，没有改成静音，也没有换成其他音频。{detail}") from exc
    streams=meta.get("streams") or []
    if not any(item.get("codec_type")=="audio" for item in streams):
        raise MaterialError(f"配乐没有音频轨道：{audio}。已停止，没有改成静音。")
    return audio

def check_deps(font_arg):
    ff=require_tool("ffmpeg")
    require_tool("ffprobe")
    version=run([ff, "-version"]).splitlines()[0]
    info={"dependencies_ok": True, "ffmpeg": version, "ffprobe": True, "rendered": False}
    default=Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    info["default_font_present"]=default.is_file()
    if font_arg:
        font=Path(font_arg).expanduser()
        if not font.is_file():
            raise MaterialError(f"字体不存在：{font}。已停止，没有改用示例视频。")
        info["font"]=str(font.resolve())
    return info

def prepare(config, out, accept_sample=False):
    cfg=json.loads(Path(config).read_text(encoding="utf-8"));base=Path(config).parent
    if not cfg.get("photos") or not cfg.get("lines"):
        raise MaterialError("缺少照片或文字。已停止，没有用示例内容补上。")
    ff=require_tool("ffmpeg");probe=require_tool("ffprobe")
    font=Path(cfg.get("font","/System/Library/Fonts/Supplemental/Songti.ttc")).expanduser()
    if not font.is_absolute():font=base/font
    if not font.is_file():
        raise MaterialError(f"字体不存在：{font}。已停止。请把 font 设成这台电脑上的中文字体路径，不要改用示例视频。")
    photos=[]
    for item in cfg["photos"]:
        if not isinstance(item, dict) or not item.get("path") or not isinstance(item.get("path"), str):
            raise MaterialError("每张照片都要有 path。已停止，没有用示例照片补上。")
        p=(base/item["path"]).resolve()
        if not p.is_file():
            raise MaterialError(f"照片不存在：{p}。已停止，没有用技能包里的示例照片顶替。")
        for k in ["focus_x","focus_y"]:
            focus=item.get(k,.5)
            if isinstance(focus, bool) or not isinstance(focus,(int,float)) or not 0<=focus<=1:
                raise MaterialError(k+" 需在 0 至 1 之间")
        photos.append(p)
    audio=resolve_audio(cfg, base, probe)
    sample_flag=cfg["sample"] if "sample" in cfg else False
    reasons=sample_reasons(cfg, Path(config), photos, audio)
    validate_sample_use(reasons, sample_flag, accept_sample)
    try:
        lines=layout_lines(cfg["lines"])
    except ValueError as exc:
        raise MaterialError(str(exc) + " 已停止，没有用示例文案替换。") from exc
    if "effects" in cfg and not isinstance(cfg["effects"], dict):
        raise MaterialError("effects 必须是对象。已停止。")
    effects=cfg.setdefault("effects",{})
    for name,default in [("stars_opacity",0.85),("wave_opacity",0.22)]:
        effects.setdefault(name,default)
        if not 0<=effects[name]<=1:raise MaterialError(name+"必须在0至1之间")
    height=len(lines)*52+100
    travel=max(0,height-850)
    duration=max(float(cfg.get("duration",0)),20,travel/28+14)
    duration=math.ceil(duration*30)/30
    if duration>1800:raise MaterialError("名单过长，请拆成多个视频")
    speed=travel/(duration-14)
    out=Path(out)
    try:
        out.mkdir(parents=True,exist_ok=False)
    except FileExistsError as exc:
        raise MaterialError(f"输出目录已存在：{out}。已停止。请换一个新目录，不要覆盖旧版本。") from exc
    font_copy=out/("font"+(font.suffix.lower() if font.suffix else ".ttc"));shutil.copyfile(font,font_copy)
    cfg["photos"]=[{**i,"path":str(p)} for i,p in zip(cfg["photos"],photos)]
    cfg["font"]=str(font)
    cfg["audio"]=str(audio) if audio else None
    cfg["silent"]=audio is None
    cfg["sample"]=bool(reasons)
    cfg["accept_sample"]=bool(accept_sample)
    cfg["duration"]=duration
    save_text(out/"config.snapshot.json",json.dumps(cfg,ensure_ascii=False,indent=2))
    filters=[];timings=[]
    for i,(text,heading,size) in enumerate(lines):
        save_text(out/f"line_{i}.txt",text)
        if text:
            filters.append(f"drawtext=fontfile={font_copy.name}:textfile=line_{i}.txt:expansion=none:fontsize={size}:fontcolor={'0xCDB784' if heading else '0xF2EEE7'}:x=(w-tw)/2:y={i*52+25}")
            enter=(8+(i*52+25-900)/speed) if speed and i*52+25>=900 else 0
            leave=min(duration,(i*52+25+50)/speed+8) if speed else duration
            timings.append({"text":text,"visible_from":round(enter,2),"visible_until":round(leave,2)})
    save_text(out/"text.filters",",".join(filters))
    run([ff,"-v","error","-f","lavfi","-i",f"color=c=black@0.0:s=820x{height}:r=1,format=rgba","-filter_script:v","text.filters","-frames:v","1","-threads","1","text.png"],out)
    assets=ROOT / "assets"
    for name in ("record.png","wave.png","stars.mov"):
        source=assets/name
        if not source.is_file():
            raise MaterialError(f"效果素材缺失：{source}。已停止，没有用其他素材替换。")
    shutil.copyfile(assets/"record.png",out/"ring.png")
    shutil.copyfile(assets/"wave.png",out/"wave.png")
    shutil.copyfile(assets/"stars.mov",out/"stars.mov")
    run([ff,"-v","error","-f","lavfi","-i","color=black:s=1920x1080:r=1","-frames:v","1","-threads","1","background.png"],out)
    for i,(p,item) in enumerate(zip(photos,cfg["photos"])):
        fx=item.get("focus_x",.5);fy=item.get("focus_y",.5)
        filt=f"scale=560:560:force_original_aspect_ratio=increase,crop=560:560:(iw-ow)*{fx}:(ih-oh)*{fy},format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-280,Y-280),278),255,0)'"
        run([ff,"-v","error","-i",str(p),"-vf",filt,"-frames:v","1","-threads","1",f"photo{i}.png"],out)
    save_text(out/"text-timing.json",json.dumps(timings,ensure_ascii=False,indent=2))
    hashes={str(p):sha256_file(p) for p in [Path(config),*photos]+([audio] if audio else [])}
    save_text(out/"sources.json",json.dumps(hashes,ensure_ascii=False,indent=2))
    return cfg,duration,travel,photos,audio

def main():
    try:
        _main()
    except MaterialError as exc:
        print("已停止："+str(exc), file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as exc:
        print("已停止："+str(exc), file=sys.stderr)
        raise SystemExit(1)

def _main():
    p=argparse.ArgumentParser(description="黑胶婚礼致谢渲染。安装技能或检查依赖不会导出示例视频。")
    p.add_argument("config", nargs="?", type=Path, help="客户自己的配置 JSON。不要把示例配置当作客户成片。")
    p.add_argument("--out", type=Path, help="新的输出目录，不能已存在")
    p.add_argument("--prepare-only", action="store_true", help="只准备版式，不导出 MP4")
    p.add_argument("--width", type=int, choices=[960,1920], default=1920, help="1920 为正式导出，960 仅当用户要求预览")
    p.add_argument("--check-deps", action="store_true", help="只检查 FFmpeg/FFprobe，不读取配置、不渲染")
    p.add_argument("--font", type=Path, help="配合 --check-deps，检查字体文件是否存在")
    p.add_argument("--accept-sample", action="store_true", help="仅当用户明确要求演示时，才允许导出示例素材")
    a=p.parse_args()
    if a.check_deps:
        if a.config or a.out or a.prepare_only or a.accept_sample:
            raise MaterialError("检查依赖时不要提供配置、输出目录或示例参数，也不会渲染。")
        print(json.dumps(check_deps(a.font), ensure_ascii=False))
        return
    if a.font:
        raise MaterialError("渲染时请把字体写进配置的 font。--font 只配合 --check-deps，用来检查字体在不在。")
    if not a.config or not a.out:
        raise MaterialError("请提供客户配置和 --out。仅安装或检查依赖时不要渲染，也不要改跑示例配置。")
    out=a.out.resolve();cfg,duration,travel,photos,audio=prepare(a.config.resolve(),out,accept_sample=a.accept_sample)
    if a.prepare_only:
        print(json.dumps({"prepared":str(out),"duration":duration,"silent":audio is None,"sample":cfg["sample"]},ensure_ascii=False))
        return
    ff=binary("ffmpeg");cmd=[ff,"-hide_banner","-loglevel","warning","-filter_complex_threads","1"]
    dur=str(duration)
    for f in ["background.png","ring.png","text.png"]+[f"photo{i}.png" for i in range(len(photos))]+["wave.png"]:cmd+=["-loop","1","-framerate","30","-t",dur,"-i",f]
    cmd+=["-stream_loop","-1","-t",dur,"-i","stars.mov"]
    if audio:cmd+=["-stream_loop","-1","-t",dur,"-i",str(audio)]
    graph=["[1:v]format=rgba,rotate='0.523599*sin(2*PI*t/16)':c=none:ow=800:oh=800[ring]","[0:v][ring]overlay=110:140[b0]"]
    last="b0"
    for i in range(len(photos)):
        start=i*duration/len(photos);end=(i+1)*duration/len(photos)
        graph.append(f"[{last}][{i+3}:v]overlay=230:260:enable='gte(t,{start})*lt(t,{end})'[b{i+1}]");last=f"b{i+1}"
    effects=cfg["effects"]
    wave_index=len(photos)+3;stars_index=len(photos)+4
    graph += [f"[{stars_index}:v]format=rgba,colorchannelmixer=aa={effects['stars_opacity']}[stars]",
              f"[{last}][stars]overlay=0:0[starred]",
              f"[{wave_index}:v]format=rgba,colorchannelmixer=aa={effects['wave_opacity']}[wave]",
              "[starred][wave]overlay=1040:390[decorated]",
              "color=black@0.0:s=820x900:r=30,format=rgba[panel]",
              f"[panel][2:v]overlay=x=0:y='-{travel}*min(1,max(0,(t-8)/{duration-14}))':shortest=1:format=auto[pane]",
              f"[decorated][pane]overlay=1040:90,scale={a.width}:{a.width*9//16},format=yuv420p[v]"]
    if audio:graph.append(f"[{len(photos)+5}:a]afade=t=in:d=1,afade=t=out:st={duration-3}:d=3[a]")
    save_text(out/"render.filters",";\n".join(graph))
    cmd+=["-filter_complex_script","render.filters","-map","[v]"]
    if audio:cmd+=["-map","[a]","-c:a","aac","-b:a","192k"]
    cmd+=["-t",str(duration),"-r","30","-c:v","libx264","-preset","veryfast","-crf","20","-threads","4","-movflags","+faststart","video.partial.mp4"]
    save_text(out/"command.json",json.dumps(cmd,ensure_ascii=False,indent=2))
    with (out/"render.log").open("w") as log:
        r=subprocess.run(cmd,cwd=out,stdout=log,stderr=log)
    if r.returncode:
        hint="配乐处理失败，没有去掉音乐继续导出。" if audio else ""
        raise RuntimeError("导出失败，没有改成静音，也没有换成示例素材。"+hint+"请查看日志："+str(out/"render.log"))
    meta=json.loads(run([binary("ffprobe"),"-v","error","-show_streams","-show_format","-of","json",str(out/"video.partial.mp4")]))
    v=next(s for s in meta["streams"] if s["codec_type"]=="video")
    if v["width"]!=a.width or v["height"]!=a.width*9//16:
        raise RuntimeError(f"导出尺寸不符：{v['width']}x{v['height']}")
    if abs(float(meta["format"]["duration"])-duration)>=.2:
        raise RuntimeError("导出时长不符，已停止。")
    if audio and not any(s["codec_type"]=="audio" for s in meta["streams"]):
        raise RuntimeError("成片缺少音轨。已停止，没有把有音乐的配置改成静音交付。")
    if not audio and any(s["codec_type"]=="audio" for s in meta["streams"]):
        raise RuntimeError("用户要求静音，但成片仍有音轨。已停止。")
    save_text(out/"verification.json",json.dumps(meta,ensure_ascii=False,indent=2))
    (out/"video.partial.mp4").rename(out/"video.mp4")
    for label,t in [("start",1),("middle",duration/2),("end",duration-.2)]:
        run([ff,"-v","error","-ss",str(t),"-i",str(out/"video.mp4"),"-frames:v","1","-threads","1",str(out/f"{label}.jpg")])
    print(json.dumps({"video":str(out/"video.mp4"),"duration":duration,"silent":audio is None,"sample":cfg["sample"]},ensure_ascii=False))

if __name__=="__main__":main()
