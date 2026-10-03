"""공통 화면 틀 + 수동 AI 도우미(모든 공개 메뉴가 함께 씀).

  · /assets/mini-ui.css  — 공개 메뉴 공통 디자인(카드·박스·표·배지·버튼, 다크모드·모바일 대응)
  · /assets/mini-ui.js   — MiniAI: "설정된 AI 열기 → 답변 복사하면 자동 입력 → 미리보기 → 저장" 흐름
  · /menus               — 메뉴 모음 화면(공개된 메뉴만 카드로)
  · page(...)            — 메뉴 화면을 같은 틀로 감싸 주는 함수(다른 메뉴 모듈이 가져다 씀)

메뉴 파일을 새로 만들 때는 menu_delist.py 처럼 page() 로 본문만 넘기면 헤더·푸터·디자인이 자동으로 같아진다.
"""
import html as _html

from flask import Blueprint, jsonify

from menu_ctx import C

bp = Blueprint("ui", __name__)

AI_SITES = {
    "gemini": {"name": "제미나이", "icon": "🔷", "url": "https://gemini.google.com/app", "q": ""},
    "chatgpt": {"name": "챗GPT", "icon": "🟢", "url": "https://chatgpt.com/", "q": "https://chatgpt.com/?q="},
    "claude": {"name": "클로드", "icon": "🟠", "url": "https://claude.ai/new", "q": "https://claude.ai/new?q="},
    "perplexity": {"name": "퍼플렉시티", "icon": "🟣", "url": "https://www.perplexity.ai/", "q": "https://www.perplexity.ai/search?q="},
}
DEFAULT_AI_SITE = "gemini"


def ai_site():
    v = C.setting_get("manual_ai_site", DEFAULT_AI_SITE)
    return v if v in AI_SITES else DEFAULT_AI_SITE


# ───────────────────────── 공통 CSS ─────────────────────────
UI_CSS = r"""
:root{--bg:#f4f6fb;--surface:#fff;--surface2:#f8fafc;--ink:#0f172a;--ink2:#475569;--ink3:#94a3b8;--line:#e5e9f2;
--navy:#0b1730;--navy2:#16294f;--accent:#3151d3;--accent2:#5b7cfa;--gold:#c9a227;
--red:#dc2626;--redbg:#fef2f2;--blue:#1d4ed8;--bluebg:#eff6ff;--green:#15803d;--greenbg:#f0fdf4;--amber:#b45309;--amberbg:#fffbeb;
--shadow:0 1px 2px rgba(15,23,42,.05),0 8px 24px -10px rgba(15,23,42,.14);--r:16px}
@media(prefers-color-scheme:dark){:root{--bg:#0a1020;--surface:#111a2e;--surface2:#0e1627;--ink:#e8edf7;--ink2:#a9b4c9;--ink3:#6b7a96;--line:#1f2b45;
--redbg:#2a1316;--bluebg:#101c3a;--greenbg:#0f2218;--amberbg:#2a1f0c;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -10px rgba(0,0,0,.6)}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body.mu{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 'Pretendard','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;word-break:keep-all;overflow-wrap:anywhere}
.mu-wrap a,.mu-foot a{color:var(--accent)}.mu-top{background:var(--navy);color:#fff;position:sticky;top:0;z-index:20;box-shadow:0 2px 12px rgba(0,0,0,.25)}
.mu-top-in{max-width:980px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.mu-brand{font-weight:800;letter-spacing:-.02em;color:#fff;text-decoration:none;margin-right:10px;white-space:nowrap}.mu-brand i{font-style:normal;color:var(--gold)}
.mu-nav{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.mu-nav a{color:#c7d2ee;text-decoration:none;font-size:13px;padding:5px 11px;border-radius:999px;border:1px solid rgba(255,255,255,.14);white-space:nowrap}
.mu-nav a:hover,.mu-nav a.on{background:rgba(255,255,255,.14);color:#fff}
.mu-hero{background:linear-gradient(135deg,var(--navy) 0%,var(--navy2) 60%,#243a73 100%);color:#fff;position:relative;overflow:hidden}
.mu-hero:after{content:"";position:absolute;right:-60px;top:-60px;width:240px;height:240px;border-radius:50%;background:radial-gradient(closest-side,rgba(201,162,39,.35),transparent)}
.mu-hero-in{max-width:980px;margin:0 auto;padding:30px 16px 34px;position:relative;z-index:1}
.mu-hero h1{margin:0 0 6px;font-size:26px;letter-spacing:-.03em;display:flex;align-items:center;gap:10px}
.mu-hero h1 .ic{display:inline-grid;place-items:center;width:44px;height:44px;border-radius:13px;background:rgba(255,255,255,.12);font-size:23px}
.mu-hero p{margin:0;color:#c7d2ee;font-size:14.5px;max-width:640px}
.mu-wrap{max-width:980px;margin:-18px auto 0;padding:0 16px 48px;position:relative;z-index:2}
.mu-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);margin:0 0 16px;overflow:hidden}
.mu-card-h{display:flex;align-items:center;gap:8px;padding:13px 18px;border-bottom:1px solid var(--line);font-weight:700;background:var(--surface2)}
.mu-card-h small{margin-left:auto;color:var(--ink3);font-weight:500;font-size:12.5px}.mu-card-b{padding:16px 18px}
.mu-grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.mu-stats{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:0 0 16px}
.mu-stat{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow);position:relative}
.mu-stat:before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:3px;border-radius:3px;background:var(--accent2)}
.mu-stat.red:before{background:var(--red)}.mu-stat.green:before{background:var(--green)}.mu-stat.gold:before{background:var(--gold)}
.mu-stat .l{font-size:12.5px;color:var(--ink2)}.mu-stat .v{font-size:24px;font-weight:800;letter-spacing:-.03em;margin-top:2px}.mu-stat .s{font-size:12px;color:var(--ink3)}
.mu-menu{display:flex;gap:14px;align-items:flex-start;padding:18px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);text-decoration:none;color:inherit;box-shadow:var(--shadow);transition:transform .15s,border-color .15s}
.mu-menu:hover{transform:translateY(-2px);border-color:var(--accent2)}
.mu-menu .t{width:46px;height:46px;border-radius:13px;background:linear-gradient(135deg,var(--bluebg),var(--surface2));border:1px solid var(--line);display:grid;place-items:center;font-size:23px;flex:none}
.mu-menu b{display:block;font-size:16px;letter-spacing:-.02em;color:var(--ink)}.mu-menu span{display:block;color:var(--ink2);font-size:13.5px;margin-top:2px}
.mu-menu em{margin-left:auto;font-style:normal;color:var(--ink3);align-self:center}
.mu-callout{display:flex;gap:11px;border-radius:14px;padding:13px 16px;margin:0 0 16px;border:1px solid;font-size:13.8px;line-height:1.65}
.mu-callout .i{font-size:18px;flex:none;line-height:1.4}.mu-callout.info{background:var(--bluebg);border-color:#bfdbfe;color:var(--blue)}
.mu-callout.warn{background:var(--amberbg);border-color:#fcd34d;color:var(--amber)}.mu-callout.danger{background:var(--redbg);border-color:#fecaca;color:var(--red)}
.mu-callout.ok{background:var(--greenbg);border-color:#bbf7d0;color:var(--green)}
@media(prefers-color-scheme:dark){.mu-callout.info,.mu-callout.warn,.mu-callout.danger,.mu-callout.ok{border-color:var(--line)}}
.mu-callout b{color:inherit}.mu-callout div{color:var(--ink)}
.mu-alert{border:2px solid var(--red);background:linear-gradient(180deg,var(--redbg),var(--surface));border-radius:var(--r);padding:16px 20px 14px;margin:0 0 16px;box-shadow:0 10px 30px -14px rgba(220,38,38,.45)}
.mu-alert-h{display:flex;align-items:center;gap:10px;color:var(--red);font-size:17px;letter-spacing:-.02em;margin-bottom:6px}.mu-alert-h span{font-size:22px}
.mu-alert-l{margin:6px 0 0;padding-left:22px;color:var(--ink);font-size:14px;line-height:1.7}.mu-alert-l li{margin:3px 0}.mu-alert-l b{color:var(--red)}.mu-alert a{color:var(--red);font-weight:700}
.mu-alert.slim{display:flex;gap:10px;padding:12px 16px;border-width:1.5px;font-size:13.5px;margin-top:16px}.mu-alert.slim b{color:var(--red)}
.mu-search{display:flex;gap:8px;margin:0 0 14px;flex-wrap:wrap}.mu-search input{flex:1;min-width:200px;border:1.5px solid var(--line);border-radius:14px;padding:13px 16px;font:inherit;font-size:16px;background:var(--surface);color:var(--ink);box-shadow:var(--shadow)}
.mu-search input:focus{outline:none;border-color:var(--accent2);box-shadow:0 0 0 3px rgba(91,124,250,.2)}
.mu-verdict{border-radius:14px;padding:13px 16px;margin:0 0 14px;border:1px solid;font-size:14px;line-height:1.7}.mu-verdict b{display:block;font-size:15.5px}
.mu-verdict.hit{background:var(--redbg);border-color:#fecaca;color:var(--red)}.mu-verdict.miss{background:var(--amberbg);border-color:#fcd34d;color:var(--amber)}.mu-verdict div{color:var(--ink)}
.mu-badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:700;background:var(--surface2);color:var(--ink2);border:1px solid var(--line)}
.mu-badge.red{background:var(--redbg);color:var(--red);border-color:transparent}.mu-badge.blue{background:var(--bluebg);color:var(--blue);border-color:transparent}
.mu-badge.green{background:var(--greenbg);color:var(--green);border-color:transparent}.mu-badge.amber{background:var(--amberbg);color:var(--amber);border-color:transparent}
.mu-tw{overflow-x:auto}.mu-tbl{width:100%;border-collapse:collapse;font-size:14px}
.mu-tbl th{position:sticky;top:0;background:var(--surface2);color:var(--ink2);font-size:12.5px;text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
.mu-tbl td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top}.mu-tbl tr:last-child td{border-bottom:0}.mu-tbl tbody tr:hover td{background:var(--surface2)}
.mu-sub{color:var(--ink3);font-size:12.5px}.mu-btn{appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:12px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.mu-btn:hover{border-color:var(--accent2)}.mu-btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border-color:transparent;box-shadow:0 6px 16px -6px rgba(49,81,211,.6)}
.mu-btn.primary:hover{filter:brightness(1.07)}.mu-btn.big{padding:13px 22px;font-size:16px;border-radius:14px}.mu-btn[disabled]{opacity:.5;cursor:default}
.mu-empty{padding:34px 16px;text-align:center;color:var(--ink3)}.mu-empty b{display:block;font-size:30px;margin-bottom:4px}
.mu-foot{max-width:980px;margin:0 auto;padding:0 16px 40px;color:var(--ink3);font-size:12.5px;line-height:1.7;text-align:center}
.mu-foot a{color:var(--ink2)}
@media(max-width:560px){.mu-hero h1{font-size:21px}.mu-hero-in{padding:22px 16px 28px}.mu-tbl th,.mu-tbl td{padding:10px}.mu-brand{margin-right:0}.mu-nav{margin-left:0;width:100%}}

/* ── MiniAI(수동 AI 도우미 창) ── */
.ma-ov{position:fixed;inset:0;background:rgba(8,13,27,.62);backdrop-filter:blur(3px);z-index:9999;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:4vh 12px}
.ma-box{background:var(--surface,#fff);color:var(--ink,#0f172a);border-radius:20px;width:100%;max-width:720px;box-shadow:0 30px 80px -20px rgba(0,0,0,.55);overflow:hidden;font:15px/1.6 'Pretendard','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif}
.ma-h{background:linear-gradient(135deg,#0b1730,#243a73);color:#fff;padding:16px 20px;display:flex;align-items:center;gap:10px}
.ma-h b{font-size:17px;letter-spacing:-.02em;flex:1}.ma-x{background:rgba(255,255,255,.14);color:#fff;border:0;border-radius:10px;width:32px;height:32px;font-size:16px;cursor:pointer}
.ma-dots{display:flex;gap:6px;padding:10px 20px 0;flex-wrap:wrap}.ma-dot{font-size:12px;padding:3px 10px;border-radius:999px;border:1px solid var(--line,#e5e9f2);color:var(--ink3,#94a3b8)}
.ma-dot.on{background:#3151d3;color:#fff;border-color:#3151d3}.ma-dot.done{background:#dcfce7;color:#15803d;border-color:#bbf7d0}
.ma-b{padding:14px 20px 20px}.ma-step{border:1px solid var(--line,#e5e9f2);border-radius:14px;padding:14px 16px;margin:0 0 12px;background:var(--surface2,#f8fafc)}
.ma-step.cur{border-color:#5b7cfa;box-shadow:0 0 0 3px rgba(91,124,250,.14);background:var(--surface,#fff)}
.ma-sn{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#3151d3;color:#fff;font-size:13px;font-weight:700;margin-right:8px}
.ma-step.done .ma-sn{background:#16a34a}.ma-st{font-weight:700}.ma-d{color:var(--ink2,#475569);font-size:13.5px;margin:6px 0 0}
.ma-chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.ma-chip{border:1px solid var(--line,#e5e9f2);background:var(--surface,#fff);color:var(--ink,#0f172a);border-radius:999px;padding:6px 13px;font:inherit;font-size:13.5px;cursor:pointer}
.ma-chip.on{background:#0b1730;color:#fff;border-color:#0b1730;font-weight:700}
.ma-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
.ma-live{display:flex;align-items:center;gap:8px;font-size:13.5px;margin-top:10px;padding:9px 12px;border-radius:11px;background:var(--bluebg,#eff6ff);color:var(--blue,#1d4ed8)}
.ma-live.ok{background:var(--greenbg,#f0fdf4);color:var(--green,#15803d)}.ma-live.bad{background:var(--amberbg,#fffbeb);color:var(--amber,#b45309)}
.ma-pulse{width:9px;height:9px;border-radius:50%;background:currentColor;animation:mapulse 1.3s infinite}@keyframes mapulse{0%{opacity:1;transform:scale(1)}60%{opacity:.25;transform:scale(1.6)}100%{opacity:1;transform:scale(1)}}
.ma-ta{width:100%;min-height:120px;border:1px solid var(--line,#e5e9f2);border-radius:12px;padding:10px 12px;font:13px/1.55 ui-monospace,Consolas,monospace;background:var(--surface,#fff);color:var(--ink,#0f172a);resize:vertical;margin-top:10px}
.ma-ta.glow{border-color:#5b7cfa;box-shadow:0 0 0 3px rgba(91,124,250,.18)}
.ma-pv{margin-top:10px;max-height:300px;overflow:auto;border:1px solid var(--line,#e5e9f2);border-radius:12px}
.ma-sw{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--ink2,#475569);margin-top:10px}
.ma-btn{appearance:none;border:1px solid var(--line,#e5e9f2);background:var(--surface,#fff);color:var(--ink,#0f172a);border-radius:12px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer}
.ma-btn.p{background:linear-gradient(135deg,#3151d3,#5b7cfa);color:#fff;border-color:transparent;box-shadow:0 6px 16px -6px rgba(49,81,211,.6)}.ma-btn.big{padding:13px 22px;font-size:16px;border-radius:14px}.ma-btn[disabled]{opacity:.5;cursor:default}.ma-btn.okd[disabled]{opacity:1;background:#16a34a;color:#fff;box-shadow:none}
.ma-pre{white-space:pre-wrap;font:12px/1.5 ui-monospace,Consolas,monospace;max-height:200px;overflow:auto;background:var(--surface,#fff);border:1px solid var(--line,#e5e9f2);border-radius:10px;padding:8px 10px;margin-top:10px}

html.emb .mu-top,html.emb .mu-hero,html.emb .mu-foot{display:none}
html.emb .mu-wrap{padding-top:14px}
[data-tk]{cursor:pointer}
a[data-tk],.tkl{color:#2563eb;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:3px}
"""

# ───────────────────────── 공통 JS (MiniAI) ─────────────────────────
# 관리자 화면(CSP 가 엄격)에도 같은 코드를 넣으므로 {{ {% {# 를 쓰지 않는다.
UI_JS = r"""
(function(){
if(window.MiniAI) return;
var SITES={gemini:{n:'제미나이',i:'🔷',u:'https://gemini.google.com/app',q:''},chatgpt:{n:'챗GPT',i:'🟢',u:'https://chatgpt.com/',q:'https://chatgpt.com/?q='},
 claude:{n:'클로드',i:'🟠',u:'https://claude.ai/new',q:'https://claude.ai/new?q='},perplexity:{n:'퍼플렉시티',i:'🟣',u:'https://www.perplexity.ai/',q:'https://www.perplexity.ai/search?q='}};
var PREFILL_MAX=1800;
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function norm(s){return String(s||'').replace(/\s+/g,' ').trim()}
function lsGet(k){try{return localStorage.getItem(k)}catch(e){return null}}
function lsSet(k,v){try{localStorage.setItem(k,v)}catch(e){}}
function copyText(text){var ok=false;try{var ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.appendChild(ta);ta.focus({preventScroll:true});ta.select();ta.setSelectionRange(0,text.length);ok=document.execCommand('copy');document.body.removeChild(ta)}catch(e){ok=false}
 try{if(navigator.clipboard&&navigator.clipboard.writeText&&window.isSecureContext){navigator.clipboard.writeText(text).catch(function(){});if(!ok)ok=true}}catch(e){}return ok}
function openUrl(u){var a=document.createElement('a');a.href=u;a.target='_blank';a.rel='noopener';document.body.appendChild(a);a.click();document.body.removeChild(a)}
function ensureStyle(){if(document.getElementById('ma-style-flag'))return;var f=el('span');f.id='ma-style-flag';f.style.display='none';document.body.appendChild(f);
 if(document.querySelector('link[href*="mini-ui.css"]'))return;
 if(!window.__MA_CSS__){var lk=document.createElement('link');lk.rel='stylesheet';lk.href='/assets/mini-ui.css';document.head.appendChild(lk);return}var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';
 var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=window.__MA_CSS__;document.head.appendChild(s)}
var cfgSite=null;
function siteDefault(){var s=lsGet('mini_ai_site');if(s&&SITES[s])return s;return (cfgSite&&SITES[cfgSite])?cfgSite:'gemini'}
fetch('/api/ui/config',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){cfgSite=j.ai_site}).catch(function(){});

// opt: {title, steps:[{label, prompt}], minLen, hint, preview:function(text)->Promise<{ok,node|text,canApply}>, apply:function(text,step)->Promise<{message}>, autoApply, onClose}
function run(opt){
 ensureStyle();
 var steps=(opt.steps||[]).filter(function(s){return s&&s.prompt});if(!steps.length)return;
 var cur=0,notice='',site=siteDefault(),armed=false,seen={},lastText='',busy=false,closed=false,doneSet={};
 var minLen=opt.minLen||60;
 var ov=el('div','ma-ov'),box=el('div','ma-box');ov.appendChild(box);
 var h=el('div','ma-h');h.appendChild(el('b',null,opt.title||'AI로 분석하기'));var x=el('button','ma-x','✕');x.onclick=close;h.appendChild(x);box.appendChild(h);
 var dots=el('div','ma-dots');box.appendChild(dots);var body=el('div','ma-b');box.appendChild(body);
 ov.addEventListener('mousedown',function(e){if(e.target===ov)ov._dn=1});ov.addEventListener('mouseup',function(e){if(e.target===ov&&ov._dn)close();ov._dn=0});
 document.body.appendChild(ov);document.body.style.overflow='hidden';
 function close(){if(closed)return;closed=true;armed=false;window.removeEventListener('focus',onBack);document.removeEventListener('visibilitychange',onVis);document.removeEventListener('keydown',onKey);document.body.removeChild(ov);document.body.style.overflow='';if(opt.onClose)opt.onClose()}
 function onKey(e){if(e.key==='Escape')close()}document.addEventListener('keydown',onKey);
 function drawDots(){dots.innerHTML='';if(steps.length<2)return;steps.forEach(function(s,i){var d=el('span','ma-dot'+(doneSet[i]?' done':(i===cur?' on':'')),(doneSet[i]?'✓ ':'')+(s.label||('프롬프트 '+(i+1))));dots.appendChild(d)})}
 var live,ta,pvBox,applyBtn,autoCb;
 function setLive(msg,kind,pulse){if(!live)return;live.className='ma-live'+(kind?' '+kind:'');live.innerHTML='';if(pulse)live.appendChild(el('span','ma-pulse'));live.appendChild(el('span',null,msg))}
 function draw(){
  drawDots();body.innerHTML='';var s=steps[cur];
  if(notice){body.appendChild(el('div','ma-live ok',notice));notice=''}
  // 1) AI 열기
  var s1=el('div','ma-step'+(armed?'':' cur'));var t1=el('div');t1.appendChild(el('span','ma-sn','1'));t1.appendChild(el('span','ma-st','프롬프트 복사하고 AI 열기'));s1.appendChild(t1);
  var chips=el('div','ma-chips');Object.keys(SITES).forEach(function(k){var c=el('button','ma-chip'+(k===site?' on':''),SITES[k].i+' '+SITES[k].n);c.onclick=function(){site=k;lsSet('mini_ai_site',k);draw()};chips.appendChild(c)});s1.appendChild(chips);
  var row=el('div','ma-row');var go=el('button','ma-btn p big',SITES[site].i+' 복사하고 '+SITES[site].n+' 열기');go.onclick=function(){openAI(s)};row.appendChild(go);
  var sh=el('button','ma-btn','프롬프트 보기');sh.onclick=function(){var p=s1.querySelector('.ma-pre');if(p){p.remove();return}var pre=el('pre','ma-pre');pre.textContent=s.prompt;s1.appendChild(pre)};row.appendChild(sh);
  var rc=el('button','ma-btn','📋 다시 복사');rc.onclick=function(){armed=true;seen[norm(s.prompt)]=1;var k=copyText(s.prompt);setLive(k?'프롬프트를 다시 복사했어요.':'복사가 막혔어요. [프롬프트 보기]에서 직접 복사해 주세요.',k?'ok':'bad')};row.appendChild(rc);s1.appendChild(row);
  s1.appendChild(el('div','ma-d',(SITES[site].q&&encodeURIComponent(s.prompt).length<=PREFILL_MAX*3?SITES[site].n+'가 열리면 질문이 자동으로 입력됩니다. 입력이 비어 있으면 입력칸에 Ctrl+V 하세요.':SITES[site].n+'가 열리면 입력칸에 Ctrl+V(붙여넣기) 한 번만 하세요. 프롬프트는 이미 복사되어 있습니다.')));
  body.appendChild(s1);
  // 2) 답변 복사
  var s2=el('div','ma-step'+(armed?' cur':''));var t2=el('div');t2.appendChild(el('span','ma-sn','2'));t2.appendChild(el('span','ma-st','AI 답변을 복사하고 이 창으로 돌아오기'));s2.appendChild(t2);
  s2.appendChild(el('div','ma-d',opt.hint||'답변이 끝나면 답변 아래의 복사 버튼(또는 전체 선택 후 Ctrl+C)을 누르고 이 탭으로 돌아오세요. 돌아오는 순간 자동으로 읽어옵니다.'));
  live=el('div','ma-live');s2.appendChild(live);setLive(armed?'AI 답변을 기다리는 중… 복사하고 이 탭으로 돌아오세요.':'위 버튼을 누르면 자동 감지가 시작됩니다.',null,armed);
  var r2=el('div','ma-row');var pull=el('button','ma-btn','📥 클립보드에서 가져오기');pull.onclick=function(){pullClip(true)};r2.appendChild(pull);s2.appendChild(r2);body.appendChild(s2);
  // 3) 확인·적용
  var s3=el('div','ma-step');var t3=el('div');t3.appendChild(el('span','ma-sn','3'));t3.appendChild(el('span','ma-st','내용 확인하고 저장'));s3.appendChild(t3);
  ta=el('textarea','ma-ta');ta.placeholder='여기에 AI 답변이 자동으로 들어옵니다. 안 들어오면 이 칸을 누르고 Ctrl+V 하세요.';ta.value=lastText;
  ta.addEventListener('paste',function(){setTimeout(function(){onText(ta.value,true)},30)});var ptm=null;ta.addEventListener('input',function(){lastText=ta.value;if(applyBtn&&!busy&&!doneSet[cur])applyBtn.disabled=!(ta.value.trim().length>=Math.min(minLen,40));clearTimeout(ptm);ptm=setTimeout(function(){if(ta.value.trim())preview(ta.value,true)},400)});s3.appendChild(ta);
  pvBox=el('div');s3.appendChild(pvBox);var r3=el('div','ma-row');
  var pv=el('button','ma-btn','미리보기');pv.onclick=function(){preview(ta.value)};r3.appendChild(pv);
  applyBtn=el('button','ma-btn p','저장');applyBtn.setAttribute('data-noconfirm','1');applyBtn.disabled=true;applyBtn.onclick=function(){doApply()};r3.appendChild(applyBtn);s3.appendChild(r3);
  if(opt.apply){var sw=el('label','ma-sw');autoCb=el('input');autoCb.type='checkbox';var _av=lsGet('mini_ai_auto_'+(opt.key||'x'));autoCb.checked=(_av===null)?true:(_av==='1')||!!opt.autoApply;autoCb.onchange=function(){lsSet('mini_ai_auto_'+(opt.key||'x'),autoCb.checked?'1':'0')};sw.appendChild(autoCb);sw.appendChild(el('span',null,'답변을 읽으면 확인 없이 바로 저장 (저장되면 "✅ 저장 완료"로 바뀌어요)'));s3.appendChild(sw)}
  body.appendChild(s3);if(lastText)preview(lastText,true)}
 function openAI(s){var ok=copyText(s.prompt);var S=SITES[site],u=S.u;
  if(S.q){var enc=encodeURIComponent(s.prompt);if(enc.length<=PREFILL_MAX*3)u=S.q+enc}
  openUrl(u);armed=true;seen[norm(s.prompt)]=1;draw();setLive(ok?'📋 프롬프트 복사 완료 — '+S.n+'에서 답변을 받은 뒤 복사하고 돌아오세요.':'복사가 막혔어요. [프롬프트 보기]에서 직접 복사해 주세요.',ok?'ok':'bad',ok)}
 function stripPrompt(t){var raw=String(t||'').trim();for(var i=0;i<steps.length;i++){var p=String(steps[i].prompt||'').trim();if(p.length<80)continue;var tail=p.slice(-48).replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/\s+/g,'\\s+');
   try{var m=new RegExp(tail).exec(raw);if(m&&raw.slice(0,60).replace(/\s+/g,' ')===p.slice(0,60).replace(/\s+/g,' ')){var rest=raw.slice(m.index+m[0].length).trim();if(rest.length>=minLen)return rest}}catch(e){}}
  return raw}
 function looksLikeAnswer(t,manual){t=stripPrompt(t);if(t.length<minLen)return false;var n=norm(t);if(!manual&&seen[n])return false;
  for(var i=0;i<steps.length;i++){var p=norm(steps[i].prompt);if(n===p||(p&&n.slice(0,60)===p.slice(0,60)))return false}return true}
 function pullClip(manual,tries){tries=tries||0;
  if(!(navigator.clipboard&&navigator.clipboard.readText)){if(manual)setLive('이 브라우저는 자동 읽기를 지원하지 않아요. 아래 칸을 누르고 Ctrl+V 하세요.','bad');if(ta){ta.classList.add('glow');ta.focus()}return}
  navigator.clipboard.readText().then(function(t){t=stripPrompt((t||'').trim());if(looksLikeAnswer(t,manual))onText(t,false);else if(manual){if(t&&seen[norm(t)])setLive('이미 읽어온 답변이에요. 아래 칸의 내용을 확인하고 저장하세요.','ok');else setLive('클립보드에 AI 답변이 없어요. AI 화면에서 답변 아래 복사 버튼을 먼저 누르세요.','bad')}})
  .catch(function(){if(tries<2&&!closed){setTimeout(function(){pullClip(manual,tries+1)},700);return}
   setLive('브라우저가 클립보드 읽기를 막았어요. 아래 칸을 누르고 Ctrl+V 하세요. (주소창 왼쪽 자물쇠에서 클립보드 허용을 켜면 다음부터 자동입니다)','bad');if(ta){ta.classList.add('glow');ta.focus()}})}
 var tm=null;function onBack(){if(!armed||closed)return;clearTimeout(tm);tm=setTimeout(function(){pullClip(false)},350)}
 function onVis(){if(document.visibilityState==='visible')onBack()}
 window.addEventListener('focus',onBack);document.addEventListener('visibilitychange',onVis);
 function onText(t,fromPaste){if(!t)return;t=stripPrompt(t);lastText=t;if(ta){ta.value=t;ta.classList.remove('glow')}seen[norm(t)]=1;setLive('✅ 답변을 읽어왔어요. 아래 내용을 확인하세요.','ok');
  preview(t,true).then(function(r){if(r&&r.canApply&&r.strict!==false&&opt.apply&&autoCb&&autoCb.checked)doApply()})}
 function preview(t,quiet){if(!opt.preview){if(applyBtn)applyBtn.disabled=!t;return Promise.resolve({canApply:!!t})}
  if(!t||!t.trim()){if(!quiet)setLive('답변 내용이 비어 있어요.','bad');return Promise.resolve(null)}
  return Promise.resolve(opt.preview(t,steps[cur])).then(function(r){r=r||{};pvBox.innerHTML='';if(r.node){var w=el('div','ma-pv');w.appendChild(r.node);pvBox.appendChild(w)}else if(r.text){pvBox.appendChild(el('div','ma-live'+(r.canApply?' ok':' bad'),r.text))}
   if(applyBtn&&!doneSet[cur])applyBtn.disabled=!r.canApply;return r}).catch(function(){setLive('미리보기 중 오류가 났어요.','bad');return null})}
 function doApply(){if(busy||!opt.apply)return;busy=true;if(applyBtn){applyBtn.disabled=true;applyBtn.textContent='저장 중…'}
  Promise.resolve(opt.apply(ta.value,steps[cur])).then(function(r){r=r||{};doneSet[cur]=1;drawDots();
   var msg=r.message||'저장했어요.';
   if(applyBtn){applyBtn.textContent='✅ 저장 완료';applyBtn.classList.add('okd')}if(ta)ta.readOnly=true;setLive('✅ '+msg,'ok');
   setTimeout(function(){busy=false;if(closed)return;
    if(cur<steps.length-1){cur++;armed=false;lastText='';notice='✅ '+msg+' — 이제 아래 '+(steps[cur].label||'다음')+' 단계를 진행하세요.';draw()}
    else{drawDots();body.innerHTML='';var d=el('div','ma-step done');d.appendChild(el('div','ma-st','🎉 '+msg));var b=el('button','ma-btn p','닫기');b.style.marginTop='12px';b.onclick=close;d.appendChild(b);body.appendChild(d);armed=false}},1200)})
  .catch(function(){busy=false;if(applyBtn){applyBtn.disabled=false;applyBtn.textContent='저장'}setLive('저장 중 오류가 났어요. 다시 [저장]을 눌러 주세요.','bad')})}
 draw();
 return {close:close};
}
window.MiniAI={run:run,copy:copyText,sites:SITES};
// 종목 클릭 → 메인 화면의 종목분석·심층분석 탭을 연다. data-tk="종목코드" 가 붙은 요소를 누르면 동작(탭 안에서 열렸을 때).
window.GoStock=function(t){t=String(t||'').trim().toUpperCase();if(!t)return false;try{var P=window.parent;if(P&&P!==window&&P.MiniTabs&&P.MiniTabs.openStock){P.MiniTabs.openStock(t);return true}}catch(e){}
 try{window.open('/?t='+encodeURIComponent(t),'mini_main')}catch(e){}return true};
document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('[data-tk]'):null;if(!a)return;var t=a.getAttribute('data-tk');if(!t)return;
 if(e.ctrlKey||e.metaKey||e.shiftKey||e.button===1)return;e.preventDefault();e.stopPropagation();window.GoStock(t)},true);
})();
"""


# ───────────────────────── 페이지 틀 ─────────────────────────
def esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def callout(kind, text_html, icon=None):
    ic = icon or {"info": "ℹ️", "warn": "⚠️", "danger": "🚨", "ok": "✅"}.get(kind, "ℹ️")
    return f'<div class="mu-callout {kind}"><span class="i">{ic}</span><div>{text_html}</div></div>'


DISCLAIMER = ("본 화면의 정보는 공개된 자료를 정리한 참고용이며 투자 권유가 아닙니다. "
              "투자 판단과 그에 따른 책임은 이용자 본인에게 있으며, 투자 전 공시·원문을 반드시 직접 확인하세요.")


def page(title, body, icon="", subtitle="", script="", active="", disclaimer=True):
    """메뉴 화면 한 장을 같은 디자인으로 만들어 돌려준다. body·script 는 호출한 쪽이 책임지고 만든 HTML/JS."""
    ver = esc(getattr(C, "APP_VERSION", ""))
    hero = (f'<div class="mu-hero"><div class="mu-hero-in"><h1>{("<span class=ic>" + esc(icon) + "</span>") if icon else ""}{esc(title)}</h1>'
            f'{("<p>" + esc(subtitle) + "</p>") if subtitle else ""}</div></div>')
    foot = (f'<div class="mu-foot">{esc(DISCLAIMER) if disclaimer else ""}<br><a href="/">종목분석</a> · <a href="/menus">전체 메뉴</a> · '
            f'<a href="/privacy">개인정보처리방침</a></div>')
    nav = ('<nav class="mu-nav" id="muNav"><a href="/">종목분석</a><a href="/menus"' + (' class="on"' if active == "menus" else "") + '>전체 메뉴</a></nav>')
    nav_js = ("fetch('/api/menus',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){var n=document.getElementById('muNav');"
              "(j.menus||[]).forEach(function(m){var a=document.createElement('a');a.href=m.path;a.textContent=m.icon+' '+m.label;"
              f"if(m.id==={_js_str(active)})a.className='on';n.appendChild(a)}});var on=n.querySelector('a.on');if(on&&n.scrollTo){{n.scrollTo({{left:Math.max(0,on.offsetLeft-(n.clientWidth-on.offsetWidth)/2),behavior:'smooth'}})}}}}).catch(function(){{}});")
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="theme-color" content="#0b1730"><title>{esc(title)} · 종목분석 미니</title>'
            f'<script>try{{if(window.self!==window.top)document.documentElement.classList.add("emb")}}catch(e){{}}</script>'
            f'<link rel="stylesheet" href="/assets/mini-ui.css?v={ver}"></head><body class="mu">'
            f'<header class="mu-top"><div class="mu-top-in"><a class="mu-brand" href="/">종목분석 <i>미니</i></a>{nav}</div></header>'
            f'{hero}<main class="mu-wrap">{body}</main>{foot}'
            f'<script src="/assets/mini-ui.js?v={ver}"></script><script>{nav_js}\n{script}</script></body></html>')


def _js_str(s):
    import json
    return json.dumps(str(s or ""), ensure_ascii=False).replace("</", "<\\/")


# ───────────────────────── 경로 ─────────────────────────
def _asset(text, mime):
    resp = C.app.make_response(text)
    resp.headers["Content-Type"] = mime + "; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@bp.route("/assets/mini-ui.css")
def ui_css():
    return _asset(UI_CSS, "text/css")


@bp.route("/assets/mini-ui.js")
def ui_js():
    return _asset(UI_JS, "application/javascript")


@bp.route("/api/ui/config")
def ui_config():
    resp = jsonify({"ai_site": ai_site(), "ai_sites": {k: v["name"] for k, v in AI_SITES.items()}})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/menus")
def menus_page():
    cards = []
    for m in C.menus_ordered():
        if not C.menu_visible(m["id"]):
            continue
        cards.append(f'<a class="mu-menu" href="{esc(m["public_path"])}"><div class="t">{esc(m["icon"])}</div>'
                     f'<div><b>{esc(m["label"])}</b><span>{esc(m.get("desc", ""))}</span></div><em>›</em></a>')
    if cards:
        body = ('<div class="mu-card"><div class="mu-card-h">🧰 이용할 수 있는 도구<small>' + str(len(cards)) + '개</small></div>'
                '<div class="mu-card-b"><div class="mu-grid">' + "".join(cards) + '</div></div></div>')
    else:
        body = '<div class="mu-card"><div class="mu-empty"><b>🛠️</b>아직 공개된 메뉴가 없어요. 곧 하나씩 열립니다.</div></div>'
    body = ('<div class="mu-card"><div class="mu-card-h">🔎 종목 분석<small>핵심 기능</small></div><div class="mu-card-b">'
            '<a class="mu-menu" href="/"><div class="t">📈</div><div><b>종목 분석</b><span>종목명이나 코드를 입력하면 가격·재무·뉴스·AI 분석용 프롬프트까지 한 번에 정리합니다.</span></div><em>›</em></a></div></div>') + body
    resp = C.app.make_response(page("전체 메뉴", body, icon="🧭", subtitle="필요한 도구를 골라 쓰세요. 모두 같은 화면 구성으로 되어 있습니다.", active="menus"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ───────────────────────── 등록 ─────────────────────────
def _valid_site(k, v):
    return v if v in AI_SITES else None


def register():
    C.register_settings({"manual_ai_site": DEFAULT_AI_SITE}, {"manual_ai_site": _valid_site})
    # 관리자 화면(엄격한 보안 설정)에서도 같은 도우미를 쓰도록 JS·CSS 를 함께 넣는다.
    C.register_admin_lib("window.__MA_CSS__=" + _js_str("/* ── MiniAI" + UI_CSS.split("/* ── MiniAI")[1]) + ";\n" + UI_JS)
    return bp
