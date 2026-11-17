#!/usr/bin/env python3
"""Deterministic local vinyl credits renderer. Python stdlib + FFmpeg only."""
import argparse, hashlib, json, math, os, random, shutil, struct, subprocess, zlib
from pathlib import Path
from layout import layout_lines

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

def run(args,cwd=None):
    r=subprocess.run(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-6000:])
    return r.stdout

def prepare(config,out):
    cfg=json.loads(config.read_text(encoding="utf-8"));base=config.parent
    assert cfg.get('photos') and cfg.get('lines'),'需要照片和逐行文字'
    ff=binary('ffmpeg');probe=binary('ffprobe')
    font=Path(cfg.get('font','/System/Library/Fonts/Supplemental/Songti.ttc')).expanduser()
    if not font.is_absolute():font=base/font
    assert font.is_file(),'字体不存在，请设置font'
    photos=[]
    for item in cfg['photos']:
        p=(base/item['path']).resolve();assert p.is_file(),f'照片不存在: {p}'
        for k in ['focus_x','focus_y']:assert 0<=item.get(k,.5)<=1,'焦点需在0至1之间'
        photos.append(p)
    audio=(base/cfg['audio']).resolve() if cfg.get('audio') else None
    if audio:
        assert audio.is_file(),'配乐不存在'
        meta=json.loads(run([probe,'-v','error','-show_streams','-of','json',str(audio)]))
        assert any(s['codec_type']=='audio' for s in meta['streams']),'配乐没有音频轨道'
    lines=layout_lines(cfg['lines'])
    effects=cfg.setdefault('effects',{})
    for name,default in [('stars_opacity',0.85),('wave_opacity',0.22)]:
        effects.setdefault(name,default)
        if not 0<=effects[name]<=1:raise ValueError(name+'必须在0至1之间')
    height=len(lines)*52+100
    travel=max(0,height-850)
    duration=max(float(cfg.get('duration',0)),20,travel/28+14)
    duration=math.ceil(duration*30)/30
    assert duration<=1800,'名单过长，请拆成多个视频'
    speed=travel/(duration-14)
    out.mkdir(parents=True,exist_ok=False)
    font_copy=out/('font'+(font.suffix.lower() if font.suffix else '.ttc'));shutil.copyfile(font,font_copy)
    cfg['photos']=[{**i,'path':str(p)} for i,p in zip(cfg['photos'],photos)]
    cfg['font']=str(font);cfg['audio']=str(audio) if audio else None
    cfg['duration']=duration
    save_text(out/'config.snapshot.json',json.dumps(cfg,ensure_ascii=False,indent=2))
    filters=[];timings=[]
    for i,(text,heading,size) in enumerate(lines):
        save_text(out/f'line_{i}.txt',text)
        if text:
            filters.append(f"drawtext=fontfile={font_copy.name}:textfile=line_{i}.txt:expansion=none:fontsize={size}:fontcolor={'0xCDB784' if heading else '0xF2EEE7'}:x=(w-tw)/2:y={i*52+25}")
            enter=(8+(i*52+25-900)/speed) if speed and i*52+25>=900 else 0
            leave=min(duration,(i*52+25+50)/speed+8) if speed else duration
            timings.append({'text':text,'visible_from':round(enter,2),'visible_until':round(leave,2)})
    save_text(out/'text.filters',','.join(filters))
    run([ff,'-v','error','-f','lavfi','-i',f'color=c=black@0.0:s=820x{height}:r=1,format=rgba','-filter_script:v','text.filters','-frames:v','1','-threads','1','text.png'],out)
    assets=Path(__file__).resolve().parent.parent/'assets'
    shutil.copyfile(assets/'record.png',out/'ring.png')
    shutil.copyfile(assets/'wave.png',out/'wave.png')
    shutil.copyfile(assets/'stars.mov',out/'stars.mov')
    run([ff,'-v','error','-f','lavfi','-i','color=black:s=1920x1080:r=1','-frames:v','1','-threads','1','background.png'],out)
    for i,(p,item) in enumerate(zip(photos,cfg['photos'])):
        fx=item.get('focus_x',.5);fy=item.get('focus_y',.5)
        filt=f"scale=560:560:force_original_aspect_ratio=increase,crop=560:560:(iw-ow)*{fx}:(ih-oh)*{fy},format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-280,Y-280),278),255,0)'"
        run([ff,'-v','error','-i',str(p),'-vf',filt,'-frames:v','1','-threads','1',f'photo{i}.png'],out)
    save_text(out/'text-timing.json',json.dumps(timings,ensure_ascii=False,indent=2))
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [config,*photos]+([audio] if audio else [])}
    save_text(out/'sources.json',json.dumps(hashes,ensure_ascii=False,indent=2))
    return cfg,duration,travel,photos,audio

def main():
    p=argparse.ArgumentParser();p.add_argument('config',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--prepare-only',action='store_true');p.add_argument('--width',type=int,choices=[960,1920],default=1920)
    a=p.parse_args();out=a.out.resolve();cfg,duration,travel,photos,audio=prepare(a.config.resolve(),out)
    if a.prepare_only:print(json.dumps({'prepared':str(out),'duration':duration}));return
    ff=binary('ffmpeg');cmd=[ff,'-hide_banner','-loglevel','warning','-filter_complex_threads','1']
    dur=str(duration)
    for f in ['background.png','ring.png','text.png']+[f'photo{i}.png' for i in range(len(photos))]+['wave.png']:cmd+=['-loop','1','-framerate','30','-t',dur,'-i',f]
    cmd+=['-stream_loop','-1','-t',dur,'-i','stars.mov']
    if audio:cmd+=['-stream_loop','-1','-t',dur,'-i',str(audio)]
    graph=["[1:v]format=rgba,rotate='0.523599*sin(2*PI*t/16)':c=none:ow=800:oh=800[ring]","[0:v][ring]overlay=110:140[b0]"]
    last='b0'
    for i in range(len(photos)):
        start=i*duration/len(photos);end=(i+1)*duration/len(photos)
        graph.append(f"[{last}][{i+3}:v]overlay=230:260:enable='gte(t,{start})*lt(t,{end})'[b{i+1}]");last=f'b{i+1}'
    effects=cfg['effects']
    wave_index=len(photos)+3;stars_index=len(photos)+4
    graph += [f"[{stars_index}:v]format=rgba,colorchannelmixer=aa={effects['stars_opacity']}[stars]",
              f"[{last}][stars]overlay=0:0[starred]",
              f"[{wave_index}:v]format=rgba,colorchannelmixer=aa={effects['wave_opacity']}[wave]",
              "[starred][wave]overlay=1040:390[decorated]",
              "color=black@0.0:s=820x900:r=30,format=rgba[panel]",
              f"[panel][2:v]overlay=x=0:y='-{travel}*min(1,max(0,(t-8)/{duration-14}))':shortest=1:format=auto[pane]",
              f"[decorated][pane]overlay=1040:90,scale={a.width}:{a.width*9//16},format=yuv420p[v]"]
    if audio:graph.append(f'[{len(photos)+5}:a]afade=t=in:d=1,afade=t=out:st={duration-3}:d=3[a]')
    save_text(out/'render.filters',';\n'.join(graph))
    cmd+=['-filter_complex_script','render.filters','-map','[v]']
    if audio:cmd+=['-map','[a]','-c:a','aac','-b:a','192k']
    cmd+=['-t',str(duration),'-r','30','-c:v','libx264','-preset','veryfast','-crf','20','-threads','4','-movflags','+faststart','video.partial.mp4']
    save_text(out/'command.json',json.dumps(cmd,ensure_ascii=False,indent=2))
    with (out/'render.log').open('w') as log:
        r=subprocess.run(cmd,cwd=out,stdout=log,stderr=log)
    if r.returncode:raise RuntimeError('导出失败，见 '+str(out/'render.log'))
    meta=json.loads(run([binary('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(out/'video.partial.mp4')]))
    v=next(s for s in meta['streams'] if s['codec_type']=='video')
    assert v['width']==a.width and v['height']==a.width*9//16
    assert abs(float(meta['format']['duration'])-duration)<.2
    save_text(out/'verification.json',json.dumps(meta,ensure_ascii=False,indent=2))
    (out/'video.partial.mp4').rename(out/'video.mp4')
    for label,t in [('start',1),('middle',duration/2),('end',duration-.2)]:
        run([ff,'-v','error','-ss',str(t),'-i',str(out/'video.mp4'),'-frames:v','1','-threads','1',str(out/f'{label}.jpg')])
    print(json.dumps({'video':str(out/'video.mp4'),'duration':duration},ensure_ascii=False))
if __name__=='__main__':main()
