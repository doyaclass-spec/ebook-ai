"""AI 전자책 메이커 v2.1 — 한국 출판 판형·타이포·판권·ISBN·인쇄납품·맞춤법·워터마크"""

from flask import Flask, render_template, request, jsonify, send_file
from weasyprint import HTML
import anthropic, json, io, os, re, traceback, base64, uuid, math
from datetime import datetime

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

claude_client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

try:
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY', ''))
    GEMINI_AVAILABLE = bool(os.environ.get('GEMINI_API_KEY'))
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from supabase import create_client
    supabase = create_client(os.environ.get('SUPABASE_URL',''), os.environ.get('SUPABASE_KEY','')) if os.environ.get('SUPABASE_URL') else None
    SUPABASE_AVAILABLE = bool(supabase)
except Exception:
    supabase = None; SUPABASE_AVAILABLE = False

try:
    from ebooklib import epub; EPUB_AVAILABLE = True
except ImportError:
    EPUB_AVAILABLE = False

# ── 테마 ─────────────────────────────────────────────────────
THEMES = {
    'green':  {'main':'#1A7A3C','dark':'#0F5228','deep':'#083D1E','mid':'#2E9E57','light':'#E8F5ED','pale':'#F2FAF5','accent':'#4CAF72'},
    'blue':   {'main':'#1E50A2','dark':'#12306A','deep':'#0A1F47','mid':'#3369C4','light':'#E8F0FB','pale':'#F0F5FF','accent':'#5B8DEF'},
    'red':    {'main':'#B91C1C','dark':'#7F1D1D','deep':'#450A0A','mid':'#DC2626','light':'#FEE2E2','pale':'#FFF5F5','accent':'#F87171'},
    'purple': {'main':'#6D28D9','dark':'#4C1D95','deep':'#2E1065','mid':'#7C3AED','light':'#EDE9FE','pale':'#FAF5FF','accent':'#A78BFA'},
    'navy':   {'main':'#1E3A5F','dark':'#0F2040','deep':'#060F1E','mid':'#2E5FA3','light':'#E8EEF8','pale':'#F2F6FF','accent':'#5B84C4'},
}

# ── 한국 출판 판형 ─────────────────────────────────────────────
PAPER_SIZES = {
    'a4':      {'label':'A4 (210×297mm)',      'w':210,'h':297,'ml':22,'mr':22,'mt':20,'mb':22},
    'singguk': {'label':'신국판 (152×225mm)',  'w':152,'h':225,'ml':18,'mr':15,'mt':18,'mb':20},
    'guk':     {'label':'국판 (148×210mm)',    'w':148,'h':210,'ml':16,'mr':14,'mt':16,'mb':18},
    'crown':   {'label':'크라운판 (176×248mm)','w':176,'h':248,'ml':20,'mr':17,'mt':20,'mb':22},
    'p46':     {'label':'46판 (127×188mm)',    'w':127,'h':188,'ml':14,'mr':12,'mt':14,'mb':16},
}

# ── 출판 유형별 타이포 프리셋 ─────────────────────────────────
TYPO_PRESETS = {
    'business': {'label':'자기계발/비즈니스','font_size':10.5,'line_height':2.0, 'letter_spacing':'0em',   'indent':5},
    'novel':    {'label':'소설/에세이',      'font_size':10.0,'line_height':1.95,'letter_spacing':'-0.02em','indent':4},
    'textbook': {'label':'교재/전문서',      'font_size':10.0,'line_height':1.85,'letter_spacing':'0em',   'indent':0},
    'kids':     {'label':'아동/청소년',      'font_size':11.5,'line_height':2.1, 'letter_spacing':'0.01em','indent':5},
}

# ── CSS ──────────────────────────────────────────────────────
def get_css(t, paper='a4', layout='1col', typo=None, print_mode=False, watermark=False, watermark_text=''):
    ps  = PAPER_SIZES.get(paper, PAPER_SIZES['a4'])
    typ = typo or TYPO_PRESETS['business']
    bl  = 3 if print_mode else 0
    pw  = ps['w'] + bl*2
    ph  = ps['h'] + bl*2

    wm = ''
    if watermark and watermark_text:
        wt = watermark_text.replace("'","\\'")
        wm = f"""body::after{{content:'{wt}';position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-35deg);font-family:'BookUI',sans-serif;font-size:42pt;font-weight:900;color:rgba(0,0,0,0.06);white-space:nowrap;pointer-events:none;z-index:9999;letter-spacing:4pt;}}"""

    col = "".join([
        ".two-col{column-count:2;column-gap:8mm;column-rule:0.5pt solid #DDD;}",
        ".two-col p{text-indent:0;}"
    ]) if layout == '2col' else ''

    fs  = typ.get('font_size',10.5)
    lh  = typ.get('line_height',2.0)
    ls  = typ.get('letter_spacing','0em')
    ind = typ.get('indent',5)
    m   = t['main']; md = t['dark']; mp = t['deep']
    ml2 = t['light']; pal = t['pale']; acc = t['accent']

    return f"""
@font-face{{font-family:'BookBody';src:local('Noto Serif CJK KR');font-weight:400;}}
@font-face{{font-family:'BookBody';src:local('Noto Serif CJK KR SemiBold');font-weight:600;}}
@font-face{{font-family:'BookBody';src:local('Noto Serif CJK KR Bold');font-weight:700;}}
@font-face{{font-family:'BookUI';src:local('Noto Sans CJK KR');font-weight:400;}}
@font-face{{font-family:'BookUI';src:local('Noto Sans CJK KR Bold');font-weight:700;}}
@font-face{{font-family:'BookUI';src:local('Noto Sans CJK KR Black');font-weight:900;}}
@page{{size:{pw}mm {ph}mm;margin:{ps['mt']+bl}mm {ps['mr']+bl}mm {ps['mb']+bl}mm {ps['ml']+bl}mm;
  @top-left{{content:string(bt);font-family:'BookUI';font-size:8pt;color:{m};font-weight:700;vertical-align:bottom;padding-bottom:4mm;border-bottom:1.8pt solid {m};}}
  @top-right{{content:string(ct);font-family:'BookUI';font-size:8pt;color:#888;vertical-align:bottom;padding-bottom:4mm;border-bottom:.4pt solid #CCC;}}
  @bottom-center{{content:counter(page);font-family:'BookUI';font-size:9pt;font-weight:700;color:#FFF;background:{m};border-radius:50%;width:6mm;height:6mm;text-align:center;vertical-align:middle;padding-top:1.2mm;}}
}}
@page:left{{margin-left:{ps['ml']+bl+5}mm;margin-right:{ps['mr']+bl}mm;@top-right{{content:none;border:none;}}}}
@page:right{{margin-left:{ps['ml']+bl}mm;margin-right:{ps['mr']+bl+5}mm;@top-left{{content:none;border:none;}}}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'BookBody','Noto Serif CJK KR',serif;font-size:{fs}pt;line-height:{lh};letter-spacing:{ls};color:#2D2D2D;word-break:keep-all;overflow-wrap:break-word;text-align:justify;word-spacing:-0.05em;}}
{wm}
.pb{{page-break-after:always;}}.keep{{page-break-inside:avoid;}}
.btr{{string-set:bt content();display:none;}}
/* 판권 */
.colophon{{page-break-before:always;min-height:200mm;display:flex;flex-direction:column;justify-content:flex-end;padding-bottom:10mm;}}
.colophon-rule{{height:0.5pt;background:#CCC;margin-bottom:8mm;}}
.colophon-title{{font-family:'BookUI';font-size:14pt;font-weight:900;color:#1E1E2E;margin-bottom:2mm;}}
.colophon-sub{{font-family:'BookUI';font-size:9pt;color:#888;margin-bottom:6mm;}}
.colophon-tbl{{width:100%;font-family:'BookUI';font-size:9pt;border-collapse:collapse;}}
.colophon-tbl td{{padding:1.5mm 0;vertical-align:top;}}
.colophon-tbl td:first-child{{width:26mm;color:#888;}}
.colophon-copy{{font-family:'BookUI';font-size:8pt;color:#aaa;margin-top:6mm;border-top:0.5pt solid #EEE;padding-top:4mm;line-height:1.7;}}
/* 헤더/섹션 */
.ptitle-reg{{string-set:bt content();display:none;}}
.prologue-title{{font-family:'BookUI';font-size:22pt;font-weight:900;color:{md};margin-top:10mm;margin-bottom:2mm;string-set:ct "프롤로그";}}
.author-line{{font-family:'BookUI';font-size:11pt;color:#555;text-align:right;margin-top:8mm;}}
.dual-line{{height:6pt;margin-bottom:6mm;position:relative;}}
.dual-line::before{{content:'';position:absolute;top:0;left:0;right:0;height:2.5pt;background:{m};}}
.dual-line::after{{content:'';position:absolute;bottom:0;left:0;right:0;height:.6pt;background:#CCC;}}
.part-opener{{page-break-before:always;page-break-after:always;height:200mm;display:flex;flex-direction:column;justify-content:center;}}
.part-box{{background:{mp};border-radius:6pt;padding:14mm 12mm 12mm;position:relative;overflow:hidden;min-height:70mm;}}
.pd1{{position:absolute;right:-15mm;top:-15mm;width:70mm;height:70mm;border-radius:50%;background:rgba(255,255,255,.06);}}
.pd2{{position:absolute;right:10mm;bottom:-20mm;width:90mm;height:90mm;border-radius:50%;background:rgba(255,255,255,.04);}}
.pd3{{position:absolute;right:0;top:0;bottom:0;width:35%;background:{m};border-radius:0 6pt 6pt 0;}}
.pd4{{position:absolute;right:35%;top:0;bottom:0;width:5mm;background:{mp};}}
.pbn{{position:absolute;right:4%;bottom:5mm;font-family:'BookUI';font-size:72pt;font-weight:900;color:rgba(255,255,255,.18);line-height:1;}}
.plbl{{font-family:'BookUI';font-size:9.5pt;font-weight:700;color:{acc};letter-spacing:2pt;margin-bottom:3mm;position:relative;z-index:2;}}
.psep{{height:.5pt;background:rgba(255,255,255,.25);margin-bottom:5mm;width:60%;position:relative;z-index:2;}}
.ptitle{{font-family:'BookUI';font-size:20pt;font-weight:900;color:#FFF;line-height:1.5;position:relative;z-index:2;width:58%;}}
.psub{{font-family:'BookUI';font-size:9.5pt;color:rgba(170,220,190,.9);margin-top:5mm;position:relative;z-index:2;}}
.pintro{{margin-top:8mm;font-size:{fs}pt;color:#555;line-height:{lh};}}
.chapter-img{{width:100%;max-height:55mm;object-fit:cover;border-radius:4pt;margin-bottom:6mm;display:block;}}
.ch-wrap{{margin-top:8mm;margin-bottom:8mm;}}
.ch-num{{font-family:'BookUI';font-size:8.5pt;font-weight:700;color:{m};letter-spacing:1.5pt;margin-bottom:1.5mm;string-set:ct content();}}
.ch-title{{font-family:'BookUI';font-size:18pt;font-weight:900;color:#1E1E2E;line-height:1.45;margin-bottom:4mm;}}
.sec-num{{font-family:'BookUI';font-size:8pt;font-weight:700;color:{m};letter-spacing:1pt;margin-top:8mm;margin-bottom:1.5mm;}}
.sec-title{{font-family:'BookUI';font-size:14.5pt;font-weight:900;color:#1E1E2E;line-height:1.5;margin-bottom:2mm;}}
.sec-line{{height:.6pt;background:{ml2};margin-bottom:5mm;}}
.sub-h{{font-family:'BookUI';font-size:11pt;font-weight:700;color:{md};margin-top:7mm;margin-bottom:3mm;}}
p{{margin-bottom:3.5mm;text-indent:{ind}mm;}}p.ni{{text-indent:0;}}
.tip{{margin:5mm 0;border-radius:5pt;overflow:hidden;page-break-inside:avoid;}}
.tip-h{{background:{m};padding:2.5mm 5mm;font-family:'BookUI';font-size:10pt;font-weight:700;color:#FFF;}}
.tip-b{{background:{ml2};padding:4mm 5mm;}}
.tip-b p{{text-indent:0;font-family:'BookUI';font-size:10pt;line-height:1.8;color:#2D2D2D;margin-bottom:1.5mm;}}
.warn{{background:#FFFBEA;border:1.5pt solid #D4A017;border-radius:5pt;padding:4mm 5mm;margin:5mm 0;page-break-inside:avoid;}}
.warn-h{{font-family:'BookUI';font-size:10pt;font-weight:700;color:#D4A017;margin-bottom:2mm;}}
.warn p{{text-indent:0;font-family:'BookUI';font-size:9.5pt;line-height:1.8;margin-bottom:1mm;}}
.quote{{border-left:3.5pt solid {m};padding:4mm 6mm;margin:6mm 0;background:{pal};page-break-inside:avoid;}}
.quote p{{text-indent:0;font-family:'BookBody';font-size:12pt;font-weight:600;color:{md};line-height:1.8;margin:0;}}
.tbl-wrap{{margin:5mm 0;page-break-inside:avoid;}}
.tbl-cap{{font-family:'BookUI';font-size:8.5pt;color:#888;text-align:center;margin-top:1.5mm;}}
table{{width:100%;border-collapse:collapse;font-family:'BookUI';font-size:9pt;}}
thead tr{{background:{m};color:#FFF;}}
thead th{{padding:3mm;text-align:center;font-weight:700;border-bottom:2pt solid {md};}}
tbody tr:nth-child(odd){{background:#FFF;}}tbody tr:nth-child(even){{background:{pal};}}
tbody td{{padding:2.5mm 3mm;border-bottom:.4pt solid #DDD;text-align:center;vertical-align:middle;}}
td.tl{{text-align:left;}}td.tb{{font-weight:700;color:{md};}}tr.hl td{{background:#D4EDDA!important;font-weight:700;color:{md};}}
.info-table{{width:100%;border-collapse:collapse;font-family:'BookUI';font-size:9pt;margin:5mm 0;page-break-inside:avoid;}}
.info-table thead tr{{background:{m};color:#FFF;}}
.info-table thead th{{padding:3mm 4mm;text-align:left;font-weight:700;}}
.info-table tbody tr{{border-bottom:1pt solid {ml2};}}
.info-table tbody td{{padding:3mm 4mm;vertical-align:middle;}}
.info-table tbody tr:nth-child(even){{background:{pal};}}
.badge{{display:inline-block;padding:1mm 4mm;border-radius:20pt;font-size:8.5pt;font-weight:700;}}
.badge-green{{background:{ml2};color:{md};}}.badge-gray{{background:#F1F5F9;color:#475569;}}
.badge-yellow{{background:#FFFBEA;color:#B45309;}}.badge-red{{background:#FEE2E2;color:#991B1B;}}
.prog-bar-wrap{{width:100%;background:#E5E7EB;border-radius:10pt;height:4mm;}}
.prog-bar{{height:4mm;border-radius:10pt;background:{m};}}
.chart-wrap{{margin:5mm 0;page-break-inside:avoid;text-align:center;}}
.chart-cap{{font-family:'BookUI';font-size:8.5pt;color:#888;margin-top:2mm;}}
.numlist{{list-style:none;margin:4mm 0;}}
.numlist li{{display:flex;align-items:flex-start;margin-bottom:3mm;}}
.nc{{display:inline-flex;align-items:center;justify-content:center;width:6mm;height:6mm;min-width:6mm;border-radius:50%;background:{m};color:#FFF;font-family:'BookUI';font-size:8pt;font-weight:700;margin-right:3mm;margin-top:1.5mm;}}
.numlist li .tx{{font-family:'BookBody';font-size:{fs}pt;line-height:{lh};color:#2D2D2D;}}
.cards{{display:flex;gap:3mm;margin:5mm 0;}}
.card{{flex:1;border:.5pt solid {ml2};border-radius:5pt;overflow:hidden;page-break-inside:avoid;}}
.card-top{{background:{pal};border-bottom:1.5pt solid {m};padding:3mm 2mm;text-align:center;}}
.card-num{{font-family:'BookUI';font-size:16pt;font-weight:900;color:{m};line-height:1;margin-bottom:1mm;}}
.card-ttl{{font-family:'BookUI';font-size:9pt;font-weight:700;color:{md};line-height:1.4;}}
.card-body{{padding:3mm 2mm;text-align:center;font-family:'BookUI';font-size:8.5pt;color:#555;line-height:1.6;}}
.outro{{margin-top:12mm;display:flex;align-items:center;background:{pal};border-radius:4pt;overflow:hidden;}}
.outro-lbl{{background:{m};padding:2.5mm 4mm;font-family:'BookUI';font-size:8.5pt;font-weight:700;color:#FFF;white-space:nowrap;}}
.outro-tx{{padding:2.5mm 4mm;font-family:'BookUI';font-size:9.5pt;color:#2D2D2D;}}
.toc-title{{font-family:'BookUI';font-size:22pt;font-weight:900;color:{md};margin-top:8mm;margin-bottom:2mm;string-set:ct "목차";}}
.toc-part{{display:flex;align-items:center;margin-top:5mm;margin-bottom:2mm;padding:3mm;background:{pal};border-left:3pt solid {m};}}
.toc-part .tt{{font-family:'BookUI';font-size:10.5pt;font-weight:700;color:{md};flex:1;}}
.toc-ch{{display:flex;align-items:baseline;margin:2.5mm 0 .5mm;}}
.toc-ch .tt{{font-family:'BookUI';font-size:10pt;font-weight:700;color:#1E1E2E;flex:1;}}
.toc-sec{{display:flex;align-items:baseline;margin:1mm 0;padding-left:8mm;}}
.toc-sec .tt{{font-family:'BookUI';font-size:9.5pt;color:#555;flex:1;}}
.toc-dots{{flex:1;border-bottom:.5pt dotted #CCC;margin:0 2mm 1.5mm;min-width:5mm;}}
.toc-pg{{font-family:'BookUI';font-size:9.5pt;font-weight:700;color:{m};min-width:6mm;text-align:right;}}
@footnote{{margin:0;padding:0;}}
.fn{{float:footnote;font-family:'BookUI';font-size:8.5pt;color:#555;line-height:1.6;}}
.fn::footnote-call{{font-size:6.5pt;vertical-align:super;color:{m};font-weight:700;}}
.fn::footnote-marker{{font-size:6.5pt;color:{m};font-weight:700;margin-right:1mm;}}
.ref-section{{page-break-before:always;margin-top:8mm;}}
.ref-title{{font-family:'BookUI';font-size:14pt;font-weight:900;color:{md};margin-bottom:4mm;string-set:ct "참고문헌";}}
.ref-rule{{height:2.5pt;background:{m};margin-bottom:3px;}}
.ref-item{{font-family:'BookUI';font-size:9pt;line-height:1.8;color:#333;margin-bottom:2mm;padding-left:8mm;text-indent:-8mm;}}
.ref-num{{color:{m};font-weight:700;}}
.idx-section{{page-break-before:always;margin-top:8mm;}}
.idx-title{{font-family:'BookUI';font-size:14pt;font-weight:900;color:{md};margin-bottom:4mm;string-set:ct "색인";}}
.idx-rule{{height:2.5pt;background:{m};margin-bottom:3px;}}
.idx-grid{{column-count:3;column-gap:6mm;margin-top:4mm;}}
.idx-letter{{font-family:'BookUI';font-size:11pt;font-weight:900;color:{m};margin-top:5mm;margin-bottom:2mm;border-bottom:1pt solid {ml2};padding-bottom:1mm;break-after:avoid;column-span:none;}}
.idx-item{{font-family:'BookUI';font-size:9pt;line-height:1.7;color:#333;break-inside:avoid;}}
.idx-high{{font-weight:700;color:#1E1E2E;}}
.idx-variant{{font-size:8.5pt;color:#666;padding-left:4mm;display:block;}}
{col}"""


def render_block(b, t, chapter_images, ch_count_ref, colophon_data, author):
    bt = b.get('type',''); c = b.get('content',''); sub = b.get('sub','')
    m=t['main']; md=t['dark']; ml2=t['light']; pal=t['pale']; acc=t['accent']

    if bt == 'title_page':
        return f'''<div style="height:220mm;display:flex;flex-direction:column;justify-content:center;">
<div style="border-left:4pt solid {m};padding:8mm 10mm;margin-bottom:8mm;">
<div style="font-family:BookUI;font-size:26pt;font-weight:900;color:{md};line-height:1.4;">{c}</div>
<div style="font-family:BookUI;font-size:12pt;color:#888;margin-top:4mm;">{sub}</div>
</div>
<div style="font-family:BookUI;font-size:11pt;color:#555;text-align:right;">{author}</div>
</div>'''

    elif bt == 'colophon':
        cp = colophon_data or {}
        rows = ''
        for label, key, fallback in [
            ('지은이','author',author),('펴낸이','publisher_name',''),
            ('펴낸곳','publisher',''),('출판등록','reg_num',''),
            ('주소','address',''),('전화','phone',''),('이메일','email',''),
            ('초판 1쇄','pub_date',datetime.now().strftime('%Y년 %m월 %d일')),
            ('ISBN','isbn',''),('정가','price',''),
        ]:
            val = cp.get(key, fallback)
            if val: rows += f'<tr><td>{label}</td><td>{val}</td></tr>'
        cr = cp.get('copyright', f'© {datetime.now().year} {author}. All rights reserved.')
        disc = '이 책의 저작권은 저자에게 있습니다. 저작권법에 의해 보호를 받는 저작물이므로 무단 전재와 복제를 금합니다.'
        return f'''<div class="colophon">
<div class="colophon-rule"></div>
<div class="colophon-title">{b.get("title", c or "")}</div>
<div class="colophon-sub">{sub}</div>
<table class="colophon-tbl">{rows}</table>
<div class="colophon-copy">{cr}<br>{disc}</div>
</div>'''

    elif bt == 'prologue':
        paras = ''.join(f'<p>{p}</p>' for p in c.split('\n\n') if p.strip())
        au = f'<p class="author-line">{b.get("author","")}</p>' if b.get("author") else ''
        return f'<div class="prologue-title">프롤로그</div><div class="dual-line"></div>{paras}{au}'

    elif bt == 'toc':
        h = '<div class="toc-title">목차</div><div class="dual-line"></div>'
        for e in b.get('entries',[]):
            lvl=e.get('level','section'); txt=e.get('text',''); pg=e.get('page','')
            dots='<span class="toc-dots"></span>' if pg else ''
            pgs=f'<span class="toc-pg">{pg}</span>' if pg else ''
            if lvl=='part': h+=f'<div class="toc-part"><span class="tt">{txt}</span></div>'
            elif lvl=='chapter': h+=f'<div class="toc-ch"><span class="tt">{txt}</span>{dots}{pgs}</div>'
            else: h+=f'<div class="toc-sec"><span class="tt">{txt}</span>{dots}{pgs}</div>'
        return h

    elif bt == 'part':
        num=b.get('num','01')
        return f'''<div class="part-opener">
<div class="part-box"><div class="pd1"></div><div class="pd2"></div><div class="pd3"></div><div class="pd4"></div>
<div class="pbn">{num}</div><div class="plbl">PART &nbsp; {num}</div><div class="psep"></div>
<div class="ptitle">{c.replace(chr(10),"<br>")}</div>
{'<div class="psub">'+sub+'</div>' if sub else ''}
</div>{'<p class="pintro ni">'+b.get("intro","")+'</p>' if b.get("intro") else ''}</div>'''

    elif bt == 'chapter':
        ch_count_ref[0] += 1
        num=b.get('num',''); lbl=f'CHAPTER &nbsp; {num}' if num else 'CHAPTER'
        img=''
        if ch_count_ref[0] in chapter_images:
            img=f'<img class="chapter-img" src="data:image/png;base64,{chapter_images[ch_count_ref[0]]}">'
        return f'<div class="ch-wrap keep">{img}<div class="ch-num">{lbl}</div><div class="ch-title">{c}</div><div class="dual-line"></div></div>'

    elif bt == 'section':
        num=b.get('num',''); lbl=f'SECTION &nbsp; {num}' if num else 'SECTION'
        return f'<div class="sec-num">{lbl}</div><div class="sec-title">{c}</div><div class="sec-line"></div>'

    elif bt == 'subheading':
        return f'<div class="sub-h">{c}</div>'

    elif bt == 'paragraph':
        two=b.get('two_col',False)
        paras=''.join(f'<p>{p.replace(chr(10),"<br>")}</p>' for p in c.split('\n\n') if p.strip())
        return f'{"<div class=two-col>" if two else ""}{paras}{"</div>" if two else ""}'

    elif bt == 'tip':
        lines=''.join(f'<p>{l}</p>' for l in c.split('\n') if l.strip())
        return f'<div class="tip keep"><div class="tip-h">{b.get("icon","✅")} &nbsp;{sub}</div><div class="tip-b">{lines}</div></div>'

    elif bt == 'warn':
        lines=''.join(f'<p>{l}</p>' for l in c.split('\n') if l.strip())
        return f'<div class="warn keep"><div class="warn-h">⚠ &nbsp;{sub}</div>{lines}</div>'

    elif bt == 'quote':
        return f'<div class="quote keep"><p>{c}</p></div>'

    elif bt == 'table':
        rows=b.get('rows',[])
        if not rows: return ''
        thead='<tr>'+''.join(f'<th>{h}</th>' for h in rows[0])+'</tr>'
        tbody=''
        for row in rows[1:]:
            is_hl=any(str(x).startswith('★') for x in row)
            cells=''
            for i,x in enumerate(row):
                s=str(x)
                if s.startswith('**') and s.endswith('**'): s=s[2:-2]; cls=' class="tb"'
                elif i==0: cls=' class="tl"'
                else: cls=''
                cells+=f'<td{cls}>{s}</td>'
            tbody+=f'<tr{" class=hl" if is_hl else ""}>{cells}</tr>'
        cap=f'<div class="tbl-cap">{b.get("caption","")}</div>' if b.get("caption") else ''
        return f'<div class="tbl-wrap keep"><table><thead>{thead}</thead><tbody>{tbody}</tbody></table>{cap}</div>'

    elif bt == 'info_table':
        rows=b.get('rows',[]); cols=b.get('cols',[])
        if not rows or not cols: return ''
        thead='<tr>'+''.join(f'<th>{col["label"]}</th>' for col in cols)+'</tr>'
        tbody=''
        for row in rows:
            cells=''
            for col in cols:
                val=row.get(col['key'],''); ct=col.get('type','text')
                if ct=='badge': cells+=f'<td><span class="badge badge-{col.get("color","green")}">{val}</span></td>'
                elif ct=='progress':
                    pct=int(val) if str(val).isdigit() else 0
                    cells+=f'<td><div class="prog-bar-wrap"><div class="prog-bar" style="width:{pct}%"></div></div><span style="font-size:8pt;color:#888;">{val}%</span></td>'
                elif ct=='star':
                    s=int(val) if str(val).isdigit() else 0
                    cells+=f'<td><span style="color:{m};font-size:10pt;">{"★"*s}</span><span style="color:#DDD;font-size:10pt;">{"★"*(5-s)}</span></td>'
                else: cells+=f'<td class="tl">{val}</td>'
            tbody+=f'<tr>{cells}</tr>'
        cap=f'<div class="tbl-cap">{b.get("caption","")}</div>' if b.get("caption") else ''
        return f'<div class="tbl-wrap keep"><table class="info-table"><thead>{thead}</thead><tbody>{tbody}</tbody></table>{cap}</div>'

    elif bt == 'chart':
        svg=gen_chart(b.get('chart_type','bar'),b.get('data',[]),t)
        title_h=f'<div style="font-family:BookUI;font-size:10pt;font-weight:700;color:{md};margin-bottom:3mm;">{b.get("title","")}</div>' if b.get("title") else ''
        cap_h=f'<div class="chart-cap">{b.get("caption","")}</div>' if b.get("caption") else ''
        return f'<div class="chart-wrap keep">{title_h}{svg}{cap_h}</div>'

    elif bt == 'numlist':
        lis=''.join(f'<li><span class="nc">{i+1}</span><span class="tx">{item}</span></li>' for i,item in enumerate(b.get('items',[])))
        return f'<ul class="numlist">{lis}</ul>'

    elif bt == 'cards':
        ch=''.join(f'<div class="card"><div class="card-top"><div class="card-num">{card.get("num","")}</div><div class="card-ttl">{card.get("title","")}</div></div><div class="card-body">{card.get("body","").replace(chr(10),"<br>")}</div></div>' for card in b.get('cards',[]))
        cap=f'<div class="tbl-cap">{b.get("caption","")}</div>' if b.get("caption") else ''
        return f'<div class="cards keep">{ch}</div>{cap}'

    elif bt == 'outro':
        return f'<div class="outro keep"><div class="outro-lbl">다음 장 미리보기</div><div class="outro-tx">{c} →</div></div>'

    elif bt == 'pagebreak':
        return '<div class="pb"></div>'

    # ─── 각주 포함 paragraph (content_html 있는 경우) ───
    elif bt == 'paragraph' and b.get('content_html'):
        two=b.get('two_col',False)
        # content_html에 이미 <span class="fn"> 태그가 들어있음
        html = b['content_html']
        # 문단 분리
        paras = ''.join(f'<p>{p.strip()}</p>' for p in html.split('\n\n') if p.strip())
        return f'{"<div class=two-col>" if two else ""}{paras}{"</div>" if two else ""}'

    # ─── 참고문헌 ───
    elif bt == 'references':
        items = b.get('items', [])
        rows = ''
        for item in items:
            num = item.get('num','')
            text = item.get('text','')
            rows += f'<div class="ref-item"><span class="ref-num">[{num}]</span> {text}</div>'
        return f'''<div class="ref-section keep">
<div class="ref-title">참고문헌</div>
<div class="ref-rule"></div>
<div style="height:3px;background:#CCC;margin-bottom:6mm;"></div>
{rows}
</div>'''

    # ─── 색인 ───
    elif bt == 'index':
        groups = b.get('groups', [])
        inner = ''
        for grp in groups:
            letter = grp.get('letter','')
            items_html = ''
            for item in grp.get('items',[]):
                term = item.get('term','')
                importance = item.get('importance','medium')
                variants = item.get('variants',[])
                cls = 'idx-high' if importance=='high' else ''
                var_html = ''.join(f'<span class="idx-variant">→ {v}</span>' for v in variants)
                items_html += f'<div class="idx-item {cls}">{term}{var_html}</div>'
            inner += f'<div class="idx-letter">{letter}</div>{items_html}'

        return f'''<div class="idx-section">
<div class="idx-title">{b.get("title","색인")}</div>
<div class="idx-rule"></div>
<div style="height:3px;background:#CCC;margin-bottom:4mm;"></div>
<div class="idx-grid">{inner}</div>
</div>'''

    return ''


def gen_chart(chart_type, data, t):
    if not data: return ''
    W,H=500,240; m=t['main']
    if chart_type=='bar':
        mx=max(d.get('value',0) for d in data); n=len(data)
        bw=min(50,(W-80)//n-8); gap=(W-80-bw*n)//(n+1)
        bars=lbs=vals=''
        for i,d in enumerate(data):
            v=d.get('value',0); x=50+gap+i*(bw+gap); bh=int((v/mx)*160) if mx else 0; y=190-bh
            bars+=f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" fill="{m}" rx="3" opacity=".85"/>'
            vals+=f'<text x="{x+bw//2}" y="{y-4}" text-anchor="middle" font-size="9" fill="{m}" font-family="sans-serif" font-weight="bold">{v}</text>'
            lbs+=f'<text x="{x+bw//2}" y="208" text-anchor="middle" font-size="9" fill="#555" font-family="sans-serif">{d.get("label","")[:6]}</text>'
        grid=''.join(f'<line x1="45" y1="{190-int(i/4*160)}" x2="{W-10}" y2="{190-int(i/4*160)}" stroke="#EEE" stroke-width="1"/>' for i in range(1,5))
        return f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{grid}{bars}{vals}{lbs}<line x1="45" y1="30" x2="45" y2="192" stroke="#CCC" stroke-width="1"/><line x1="44" y1="191" x2="{W-10}" y2="191" stroke="#CCC" stroke-width="1"/></svg>'
    elif chart_type=='pie':
        total=sum(d.get('value',0) for d in data); cols=[m,'#888',t.get('mid','#999'),'#B91C1C','#6D28D9']
        cx,cy,r=130,120,95; paths=legs=''; angle=-90
        for i,d in enumerate(data):
            v=d.get('value',0)
            if not total: break
            sw=360*v/total
            x1=cx+r*math.cos(math.radians(angle)); y1=cy+r*math.sin(math.radians(angle))
            angle+=sw
            x2=cx+r*math.cos(math.radians(angle)); y2=cy+r*math.sin(math.radians(angle))
            col=cols[i%len(cols)]
            paths+=f'<path d="M{cx},{cy} L{round(x1,1)},{round(y1,1)} A{r},{r} 0 {1 if sw>180 else 0},1 {round(x2,1)},{round(y2,1)} Z" fill="{col}" stroke="white" stroke-width="2"/>'
            legs+=f'<rect x="265" y="{35+i*22}" width="12" height="12" fill="{col}" rx="2"/><text x="282" y="{45+i*22}" font-size="10" fill="#333" font-family="sans-serif">{d.get("label","")} {round(v/total*100)}%</text>'
        return f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{paths}{legs}</svg>'
    elif chart_type=='line':
        mx=max(d.get('value',0) for d in data); pts=[]; lbs=''
        for i,d in enumerate(data):
            x=50+i*(420//max(len(data)-1,1)); y=180-int((d.get('value',0)/mx)*140) if mx else 180
            pts.append(f'{x},{y}')
            lbs+=f'<text x="{x}" y="205" text-anchor="middle" font-size="9" fill="#555" font-family="sans-serif">{d.get("label","")[:6]}</text>'
            lbs+=f'<text x="{x}" y="{y-6}" text-anchor="middle" font-size="9" fill="{m}" font-family="sans-serif" font-weight="bold">{d.get("value",0)}</text>'
        poly=f'<polyline points="{" ".join(pts)}" fill="none" stroke="{m}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        dots=''.join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="4" fill="{m}" stroke="white" stroke-width="1.5"/>' for p in pts)
        grid=''.join(f'<line x1="45" y1="{180-int(i/4*140)}" x2="475" y2="{180-int(i/4*140)}" stroke="#EEE" stroke-width="1"/>' for i in range(1,5))
        return f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{grid}{poly}{dots}{lbs}<line x1="45" y1="30" x2="45" y2="182" stroke="#CCC" stroke-width="1"/><line x1="44" y1="181" x2="475" y2="181" stroke="#CCC" stroke-width="1"/></svg>'
    return ''


def build_pdf_html(data, chapter_images=None, print_mode=False):
    t      = THEMES.get(data.get('theme','green'), THEMES['green'])
    paper  = data.get('paper','a4')
    layout = data.get('layout','1col')
    author = data.get('author','')

    typo = TYPO_PRESETS.get(data.get('typo_preset','business'), TYPO_PRESETS['business']).copy()
    for k in ('font_size','line_height','letter_spacing','indent'):
        if data.get(k) is not None:
            typo[k] = float(data[k]) if k != 'letter_spacing' and k != 'indent' else (int(data[k]) if k=='indent' else data[k])

    css  = get_css(t, paper, layout, typo, print_mode,
                   data.get('watermark',False), data.get('watermark_text', data.get('title','')))
    ch   = [0]
    body = ''.join(render_block(b, t, chapter_images or {}, ch, data.get('colophon',{}), author)
                   for b in data.get('blocks',[]))

    # ISBN XMP 메타데이터
    isbn = data.get('colophon',{}).get('isbn','')
    xmp  = f'<meta name="ISBN" content="{isbn}">' if isbn else ''

    return f'<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">{xmp}<style>{css}</style></head><body><span class="btr">{data.get("title","")}</span>{body}</body></html>'


def add_crop_marks(pdf_bytes, paper='a4', bleed=3):
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas as rc
        from reportlab.lib.units import mm
        ps=PAPER_SIZES.get(paper,PAPER_SIZES['a4'])
        pw=(ps['w']+bleed*2)*mm; ph=(ps['h']+bleed*2)*mm
        bm=bleed*mm; mk=5*mm; gp=2*mm
        buf=io.BytesIO()
        c=rc.Canvas(buf,pagesize=(pw,ph))
        c.setStrokeColorRGB(0,0,0); c.setLineWidth(0.25)
        lines=[
            (bm-gp-mk,ph-bm,bm-gp,ph-bm),(bm,ph-bm+gp,bm,ph-bm+gp+mk),
            (pw-bm+gp,ph-bm,pw-bm+gp+mk,ph-bm),(pw-bm,ph-bm+gp,pw-bm,ph-bm+gp+mk),
            (bm-gp-mk,bm,bm-gp,bm),(bm,bm-gp-mk,bm,bm-gp),
            (pw-bm+gp,bm,pw-bm+gp+mk,bm),(pw-bm,bm-gp-mk,pw-bm,bm-gp),
        ]
        for x1,y1,x2,y2 in lines: c.line(x1,y1,x2,y2)
        c.save(); buf.seek(0)
        r=PdfReader(io.BytesIO(pdf_bytes)); mr=PdfReader(buf); w=PdfWriter()
        for i,page in enumerate(r.pages):
            if i < len(mr.pages): page.merge_page(mr.pages[0])
            w.add_page(page)
        out=io.BytesIO(); w.write(out); out.seek(0); return out.getvalue()
    except Exception as e:
        print(f'재단선 오류: {e}'); return pdf_bytes


SYSTEM_PROMPT = """당신은 원고를 출판 품질 전자책으로 변환하는 전문 편집자입니다.
순수 JSON만 출력하세요 (마크다운 코드블록 없이).

출력: {"title":"제목","subtitle":"부제","author":"저자","blocks":[...]}

블록: title_page, prologue, toc, pagebreak, part, chapter, section, subheading,
paragraph(two_col:bool), tip, warn, quote, table, info_table, chart(bar/pie/line),
numlist, cards, outro, colophon

규칙:
1. 순서: title_page→prologue→toc→pagebreak→본문→colophon
2. 구어체→출판 문어체
3. 수치 데이터→chart, 비교→info_table(star/progress/badge), 핵심→tip, 주의→warn, 명언→quote, 단계→numlist
4. 챕터 마지막 outro
5. 마지막 블록 반드시 colophon
6. 사용자 요청사항 최우선"""


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    return jsonify({
        'claude':GEMINI_AVAILABLE or bool(os.environ.get('ANTHROPIC_API_KEY')),
        'gemini':GEMINI_AVAILABLE,'supabase':SUPABASE_AVAILABLE,'epub':EPUB_AVAILABLE,
        'paper_sizes':{k:v['label'] for k,v in PAPER_SIZES.items()},
        'typo_presets':{k:v['label'] for k,v in TYPO_PRESETS.items()},
    })

@app.route('/api/convert', methods=['POST'])
def convert():
    try:
        d=request.get_json(); raw=d.get('text','').strip(); hint=d.get('hint','')
        if not raw or len(raw)<50: return jsonify({'error':'50자 이상 입력해주세요'}),400
        sys=SYSTEM_PROMPT+(f'\n\n추가 요청: {hint}' if hint else '')
        bi=d.get('book_info',{})
        msg=claude_client.messages.create(model='claude-sonnet-4-20250514',max_tokens=8000,system=sys,
            messages=[{'role':'user','content':f'제목:{bi.get("title","자동추출")}\n저자:{bi.get("author","미정")}\n원고:\n{raw[:15000]}'}])
        text=msg.content[0].text.strip()
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.MULTILINE)
        text=re.sub(r'\s*```$','',text,flags=re.MULTILINE).strip()
        return jsonify({'success':True,'book':json.loads(text)})
    except json.JSONDecodeError as e: return jsonify({'error':f'JSON 파싱 오류: {e}'}),500
    except Exception as e: traceback.print_exc(); return jsonify({'error':str(e)}),500

@app.route('/api/spellcheck', methods=['POST'])
def spellcheck():
    try:
        d=request.get_json(); text=d.get('text','').strip()
        if not text: return jsonify({'error':'텍스트 없음'}),400
        msg=claude_client.messages.create(model='claude-sonnet-4-20250514',max_tokens=8000,
            system="한국어 출판 교열 전문가. 맞춤법·띄어쓰기·구어체→문어체 교정. 내용 변경 금지. 교정된 텍스트만 출력.",
            messages=[{'role':'user','content':text[:10000]}])
        return jsonify({'success':True,'corrected':msg.content[0].text.strip()})
    except Exception as e: return jsonify({'error':str(e)}),500

@app.route('/api/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        d=request.get_json(); pm=d.get('print_mode',False); imgs={}
        if d.get('use_images') and GEMINI_AVAILABLE:
            cc=0
            for b in d.get('blocks',[]):
                if b.get('type')=='chapter':
                    cc+=1
                    try:
                        model=genai.GenerativeModel('gemini-3.1-flash-image-preview')
                        r=model.generate_content([f"Minimalist book chapter illustration: {b.get('content','')}. {d.get('theme','green')} colors, white background, no text."],generation_config={'response_modalities':['image']})
                        for part in r.candidates[0].content.parts:
                            if hasattr(part,'inline_data') and part.inline_data:
                                imgs[cc]=base64.b64encode(part.inline_data.data).decode()
                    except: pass
        html=build_pdf_html(d,imgs,pm)
        pdf=HTML(string=html).write_pdf(presentational_hints=True)
        if pm: pdf=add_crop_marks(pdf,d.get('paper','a4'))
        if SUPABASE_AVAILABLE:
            try:
                supabase.table('ebooks').insert({'id':str(uuid.uuid4()),'title':d.get('title',''),'author':d.get('author',''),'theme':d.get('theme','green'),'block_count':len(d.get('blocks',[])),'pdf_size_kb':len(pdf)//1024,'book_json':json.dumps(d,ensure_ascii=False),'created_at':datetime.utcnow().isoformat()}).execute()
            except: pass
        fname=(d.get('title') or '전자책').replace(' ','_')+('_인쇄납품용' if pm else '')+'.pdf'
        buf=io.BytesIO(pdf); buf.seek(0)
        return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=fname)
    except Exception as e: traceback.print_exc(); return jsonify({'error':str(e)}),500

@app.route('/api/preview', methods=['POST'])
def preview():
    try:
        d=request.get_json()
        return build_pdf_html(d),200,{'Content-Type':'text/html;charset=utf-8'}
    except Exception as e: return jsonify({'error':str(e)}),500

# ─── 교정·교열 변경 추적 ──────────────────────────────────────
@app.route('/api/track-changes', methods=['POST'])
def track_changes():
    """블록 단위 교열 — 원본 vs 교정본 diff 반환"""
    try:
        d = request.get_json()
        blocks = d.get('blocks', [])
        if not blocks:
            return jsonify({'error':'블록이 없습니다'}), 400

        # paragraph / tip / warn / quote 블록만 교열 대상
        EDITABLE = {'paragraph','tip','warn','quote','prologue','subheading'}
        targets = [(i,b) for i,b in enumerate(blocks) if b.get('type') in EDITABLE and b.get('content','').strip()]

        if not targets:
            return jsonify({'error':'교열할 텍스트 블록이 없습니다'}), 400

        # Claude에게 블록별 교열 요청 (JSON 배열 반환)
        items_txt = '\n'.join(f'[{i}] {b.get("content","")[:600]}' for i,b in targets)

        msg = claude_client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=8000,
            system="""한국어 출판 교열 전문가입니다.
입력된 번호가 붙은 텍스트들을 교열하여 아래 JSON 형식으로만 출력하세요.
변경이 없으면 changed:false로 설정하세요.
출판 교열 원칙:
- 맞춤법·띄어쓰기 교정
- 구어체 → 문어체 변환
- 중복 표현 제거  
- 문장 호응 교정
- 내용(사실) 자체는 절대 변경 금지

출력 형식 (JSON 배열만, 마크다운 없이):
[{"idx":번호, "original":"원본", "corrected":"교정본", "changed":true/false, "reasons":["이유1","이유2"]}]""",
            messages=[{'role':'user','content':f'다음 텍스트들을 교열해주세요:\n\n{items_txt}'}]
        )

        raw = msg.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*','',raw,flags=re.MULTILINE)
        raw = re.sub(r'\s*```$','',raw,flags=re.MULTILINE).strip()
        diffs = json.loads(raw)

        # 원본 블록 인덱스 매핑
        result = []
        for item in diffs:
            if not isinstance(item, dict): continue
            local_idx = item.get('idx', 0)
            if local_idx < len(targets):
                block_idx, block = targets[local_idx]
                result.append({
                    'block_idx': block_idx,
                    'type': block.get('type',''),
                    'original': item.get('original', block.get('content','')),
                    'corrected': item.get('corrected', block.get('content','')),
                    'changed': item.get('changed', False),
                    'reasons': item.get('reasons', []),
                })

        changed_count = sum(1 for r in result if r['changed'])
        return jsonify({'success':True, 'diffs':result, 'changed_count':changed_count, 'total':len(result)})

    except json.JSONDecodeError as e:
        return jsonify({'error':f'JSON 파싱 오류: {e}'}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error':str(e)}), 500


@app.route('/api/apply-changes', methods=['POST'])
def apply_changes():
    """선택한 변경사항을 블록에 적용"""
    try:
        d = request.get_json()
        blocks = d.get('blocks', [])
        approved = d.get('approved', [])  # [{block_idx, corrected}]

        for item in approved:
            idx = item.get('block_idx')
            if idx is not None and 0 <= idx < len(blocks):
                blocks[idx]['content'] = item['corrected']

        return jsonify({'success':True, 'blocks':blocks})
    except Exception as e:
        return jsonify({'error':str(e)}), 500


# ─── 각주·미주·참고문헌 처리 ──────────────────────────────────
def process_footnotes(blocks):
    """
    본문에서 [^숫자] 마크를 감지해 각주 블록으로 변환.
    각주 정의는 원고 내 [^1]: 내용 형식 또는 footnotes 블록에서 읽음.
    """
    footnote_defs = {}  # {1: "각주 내용"}
    cleaned_blocks = []

    # 1단계: footnotes 블록 또는 [^n]: 패턴 수집
    fn_block_found = False
    for b in blocks:
        if b.get('type') == 'footnotes':
            fn_block_found = True
            for item in b.get('items', []):
                num = item.get('num')
                text = item.get('text', '')
                if num: footnote_defs[int(num)] = text
        elif b.get('type') == 'references':
            # 참고문헌은 endnotes로 처리 (책 마지막)
            cleaned_blocks.append(b)
        else:
            cleaned_blocks.append(b)

    # 2단계: paragraph 본문에서 [^n]: 정의 추출
    new_blocks = []
    fn_counter = [0]

    for b in cleaned_blocks:
        if b.get('type') not in ('paragraph','tip','warn','quote','prologue'):
            new_blocks.append(b)
            continue

        content = b.get('content', '')

        # [^n]: 정의 추출 (본문 안에 있는 경우)
        def_pattern = re.compile(r'^\[\^(\d+)\]:\s*(.+)$', re.MULTILINE)
        for m in def_pattern.finditer(content):
            footnote_defs[int(m.group(1))] = m.group(2).strip()
        content = def_pattern.sub('', content).strip()

        # [^n] 참조를 WeasyPrint footnote span으로 변환
        ref_pattern = re.compile(r'\[\^(\d+)\]')
        def replace_fn(match):
            num = int(match.group(1))
            fn_text = footnote_defs.get(num, f'각주 {num}')
            fn_counter[0] += 1
            return f'<span class="footnote" role="doc-footnote">{fn_text}</span>'

        content_html = ref_pattern.sub(replace_fn, content)

        if content_html != content:
            b = dict(b)
            b['content_html'] = content_html  # HTML 렌더링용
            b['content'] = ref_pattern.sub(lambda m: f'({footnote_defs.get(int(m.group(1)), m.group(1))})', content)

        new_blocks.append(b)

    return new_blocks, fn_counter[0]


@app.route('/api/process-footnotes', methods=['POST'])
def process_footnotes_api():
    """원고에서 [^n] 각주 마크를 감지하고 처리"""
    try:
        d = request.get_json()
        blocks = d.get('blocks', [])
        processed, count = process_footnotes(blocks)
        return jsonify({'success':True, 'blocks':processed, 'footnote_count':count})
    except Exception as e:
        return jsonify({'error':str(e)}), 500


# ─── 색인 자동 생성 ───────────────────────────────────────────
@app.route('/api/generate-index', methods=['POST'])
def generate_index():
    """Claude로 핵심 키워드 추출 → 색인 블록 생성"""
    try:
        d = request.get_json()
        blocks = d.get('blocks', [])

        # 텍스트 수집
        all_text = []
        for b in blocks:
            if b.get('type') in ('paragraph','section','subheading','tip','warn','quote'):
                c = b.get('content','')
                if c: all_text.append(c)

        full_text = '\n'.join(all_text)[:12000]

        if not full_text.strip():
            return jsonify({'error':'색인을 만들 텍스트가 없습니다'}), 400

        msg = claude_client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=3000,
            system="""한국어 출판 색인 전문가입니다.
주어진 텍스트에서 독자가 찾아볼 만한 핵심 키워드를 추출하여 색인을 만들어주세요.

규칙:
1. 전문 용어, 고유명사, 핵심 개념어 위주로 선별
2. 일반 조사·접속사 제외
3. 유사어는 대표 표현 하나로 통일
4. 가나다순 정렬
5. 20~40개 키워드 추출

출력 형식 (JSON만, 마크다운 없이):
{"keywords": [{"term":"키워드","variants":["유사표현1"],"importance":"high|medium|low"}]}""",
            messages=[{'role':'user','content':f'다음 텍스트에서 색인 키워드를 추출해주세요:\n\n{full_text}'}]
        )

        raw = msg.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*','',raw,flags=re.MULTILINE)
        raw = re.sub(r'\s*```$','',raw,flags=re.MULTILINE).strip()
        kw_data = json.loads(raw)
        keywords = kw_data.get('keywords', [])

        # 색인 블록 생성 (가나다순 그룹화)
        # 자음 분류
        CHOSUNG = ['ㄱ','ㄴ','ㄷ','ㄹ','ㅁ','ㅂ','ㅅ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
        def get_chosung(ch):
            if '가' <= ch <= '힣':
                return CHOSUNG[(ord(ch)-0xAC00)//588]
            return ch[0].upper() if ch else '기타'

        groups = {}
        for kw in keywords:
            term = kw.get('term','')
            if not term: continue
            cs = get_chosung(term[0])
            if cs not in groups: groups[cs] = []
            groups[cs].append({
                'term': term,
                'variants': kw.get('variants',[]),
                'importance': kw.get('importance','medium')
            })

        # 색인 HTML 블록 데이터
        index_block = {
            'type': 'index',
            'title': '색인',
            'groups': [{'letter':k, 'items':v} for k,v in sorted(groups.items())],
            'keyword_count': len(keywords)
        }

        return jsonify({'success':True, 'index_block':index_block, 'keyword_count':len(keywords)})

    except json.JSONDecodeError as e:
        return jsonify({'error':f'JSON 파싱 오류: {e}'}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error':str(e)}), 500

@app.route('/api/history')
def history():
    if not SUPABASE_AVAILABLE: return jsonify([])
    try:
        r=supabase.table('ebooks').select('id,title,author,theme,block_count,pdf_size_kb,created_at').order('created_at',desc=True).limit(20).execute()
        return jsonify(r.data)
    except: return jsonify([])

@app.route('/api/history/<iid>')
def history_item(iid):
    if not SUPABASE_AVAILABLE: return jsonify({'error':'없음'}),404
    try:
        r=supabase.table('ebooks').select('*').eq('id',iid).execute()
        if r.data:
            item=r.data[0]; item['book_json']=json.loads(item['book_json']); return jsonify(item)
        return jsonify({'error':'없음'}),404
    except Exception as e: return jsonify({'error':str(e)}),500

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
