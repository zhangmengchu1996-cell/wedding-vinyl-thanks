"""Wrap prose, but keep each explicitly supplied guest name intact."""
import re

def width(s):return sum(1 if ord(c)>127 else .6 for c in s)

def layout_lines(rows):
    result=[]
    for row in rows:
        if isinstance(row,str):row={'text':row}
        heading=bool(row.get('heading'));size=38 if heading else 34
        text=row.get('text','')
        if not isinstance(text,str) or '\n' in text:raise ValueError('每项文字必须是单行')
        names=row.get('names')
        if names is not None and (not isinstance(names,list) or not names):raise ValueError('names需要非空姓名列表')
        # Enumerated lists from copied documents are split only at separators.
        if names is None and row.get('name_list') and not heading:names=[s.strip() for s in text.split('、') if s.strip()]
        if names is not None:
            line='';separator='　　'
            for name in names:
                if not isinstance(name,str) or not name.strip() or '\n' in name:raise ValueError('姓名必须为非空单行文字')
                if width(name)>20:raise ValueError('单个姓名/称谓过长，请调整称谓，不能自动截断：'+name)
                trial=line+separator+name if line else name
                if width(trial)>19 and line:result.append((line,heading,size));line=name
                else:line=trial
            if line:result.append((line,heading,size))
        else:
            line=''
            for ch in text:
                if width(line+ch)>20:result.append((line,heading,size));line=''
                line+=ch
            result.append((line,heading,size))
    if not any(t for t,_,_ in result):raise ValueError('文案不能全部为空')
    return result
