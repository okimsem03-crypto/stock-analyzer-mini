"""공통 화면 틀 + 수동 AI 도우미(모든 공개 메뉴가 함께 씀).

  · /assets/mini-ui.css  — 공개 메뉴 공통 디자인(카드·박스·표·배지·버튼, 다크모드·모바일 대응)
  · /assets/mini-ui.js   — MiniAI: "설정된 AI 열기 → 답변 복사하면 자동 입력 → 미리보기 → 저장" 흐름
  · /menus               — 메뉴 모음 화면(공개된 메뉴만 카드로)
  · page(...)            — 메뉴 화면을 같은 틀로 감싸 주는 함수(다른 메뉴 모듈이 가져다 씀)

메뉴 파일을 새로 만들 때는 menu_delist.py 처럼 page() 로 본문만 넘기면 헤더·푸터·디자인이 자동으로 같아진다.
"""
import html as _html

from flask import Blueprint, jsonify, request

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
:root{--bg:#f5f6f9;--surface:#fff;--surface2:#f7f8fb;--ink:#141b2b;--ink2:#475266;--ink3:#8a93a6;--line:#e4e7ee;
--navy:#0f2342;--navy2:#1a3763;--accent:#2457d6;--accent2:#4a78e8;--gold:#b98a2e;
--red:#dc2626;--redbg:#fef2f2;--blue:#1d4ed8;--bluebg:#eff4ff;--green:#15803d;--greenbg:#f0fdf4;--amber:#b45309;--amberbg:#fffbeb;
--shadow:0 1px 2px rgba(15,35,66,.04);--r:12px}
@media(prefers-color-scheme:dark){:root{--bg:#0a1020;--surface:#111a2e;--surface2:#0e1627;--ink:#e8edf7;--ink2:#a9b4c9;--ink3:#6b7a96;--line:#1f2b45;
--redbg:#2a1316;--bluebg:#101c3a;--greenbg:#0f2218;--amberbg:#2a1f0c;--shadow:0 1px 2px rgba(0,0,0,.4)}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body.mu{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 'Pretendard','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif;word-break:keep-all;overflow-wrap:anywhere;-webkit-font-smoothing:antialiased}
.mu-wrap a,.mu-foot a{color:var(--accent)}.mu-top{background:var(--surface);color:var(--ink);position:sticky;top:0;z-index:20;border-bottom:1px solid var(--line)}
.mu-top-in{max-width:1080px;margin:0 auto;padding:0 18px;min-height:54px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.mu-brand{font-weight:800;letter-spacing:-.02em;color:var(--navy);text-decoration:none;margin-right:10px;white-space:nowrap}.mu-brand i{font-style:normal;color:var(--accent)}
@media(prefers-color-scheme:dark){.mu-brand{color:#fff}}
.mu-nav{display:flex;gap:2px;flex-wrap:wrap;margin-left:auto}
.mu-nav a{color:var(--ink2);text-decoration:none;font-size:13px;font-weight:600;padding:6px 11px;border-radius:8px;border:0;white-space:nowrap}
.mu-nav a:hover,.mu-nav a.on{background:var(--surface2);color:var(--navy)}
.mu-nav a.on{background:var(--bluebg);color:var(--accent)}
.mu-g{position:relative;display:inline-flex;align-items:center;gap:2px}
.mu-gb{display:inline-flex;align-items:center;gap:5px;color:var(--ink2);background:transparent;font:inherit;font-size:13px;font-weight:600;padding:6px 11px;border-radius:8px;border:0;white-space:nowrap;cursor:pointer;max-width:240px}
.mu-gb b{font-weight:600;overflow:hidden;text-overflow:ellipsis}.mu-gb em{font-style:normal;font-size:9px;opacity:.6;transition:transform .15s}
.mu-gb:hover,.mu-g.open .mu-gb{background:var(--surface2);color:var(--navy)}.mu-g.on .mu-gb{background:var(--bluebg);color:var(--accent)}.mu-g.open .mu-gb em{transform:rotate(180deg)}
.mu-dd{display:none;position:absolute;left:0;top:calc(100% + 6px);z-index:30;min-width:190px;padding:5px;flex-direction:column;gap:1px;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 16px 40px -12px rgba(15,35,66,.3)}
.mu-g.open .mu-dd{display:flex}.mu-g.r .mu-dd{left:auto;right:0}
.mu-dd a{color:var(--ink);border:0;border-radius:7px;padding:7px 10px;font-size:13px}.mu-dd a:hover{background:var(--surface2);color:var(--navy)}.mu-dd a.on{background:var(--bluebg);color:var(--accent)}
.mu-hero{background:var(--surface);color:var(--ink);border-bottom:1px solid var(--line);position:relative}
.mu-hero-in{max-width:1080px;margin:0 auto;padding:22px 18px 20px;position:relative}
.mu-hero h1{margin:0 0 4px;font-size:22px;letter-spacing:-.03em;display:flex;align-items:center;gap:10px;color:var(--navy)}
@media(prefers-color-scheme:dark){.mu-hero h1{color:#fff}}
.mu-hero h1 .ic{display:inline-grid;place-items:center;width:36px;height:36px;border-radius:10px;background:var(--surface2);border:1px solid var(--line);font-size:19px}
.mu-hero p{margin:0;color:var(--ink2);font-size:13.5px;max-width:680px}
.mu-wrap{max-width:1080px;margin:0 auto;padding:18px 18px 48px;position:relative;z-index:2}
.mu-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow);margin:0 0 14px;overflow:hidden}
.mu-card-h{display:flex;align-items:center;gap:8px;padding:10px 16px;border-bottom:1px solid var(--line);font-weight:700;font-size:13.5px;background:var(--surface2)}
.mu-card-h small{margin-left:auto;color:var(--ink3);font-weight:500;font-size:12px}.mu-card-b{padding:14px 16px}
.mu-grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
.mu-stats{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin:0 0 14px}
.mu-stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:11px 14px;box-shadow:var(--shadow);position:relative}
.mu-stat:before{content:"";position:absolute;left:0;top:12px;bottom:12px;width:3px;border-radius:3px;background:var(--accent2)}
.mu-stat.red:before{background:var(--red)}.mu-stat.green:before{background:var(--green)}.mu-stat.gold:before{background:var(--gold)}
.mu-stat .l{font-size:12px;color:var(--ink2)}.mu-stat .v{font-size:21px;font-weight:800;letter-spacing:-.03em;margin-top:1px}.mu-stat .s{font-size:11.5px;color:var(--ink3)}
.mu-menu{display:flex;gap:12px;align-items:flex-start;padding:14px;background:var(--surface);border:1px solid var(--line);border-radius:10px;text-decoration:none;color:inherit;transition:border-color .15s,background .15s}
.mu-menu:hover{border-color:var(--accent2);background:var(--surface2)}
.mu-menu .t{width:38px;height:38px;border-radius:10px;background:var(--surface2);border:1px solid var(--line);display:grid;place-items:center;font-size:19px;flex:none}
.mu-menu b{display:block;font-size:14.5px;letter-spacing:-.02em;color:var(--ink)}.mu-menu span{display:block;color:var(--ink2);font-size:12.5px;margin-top:2px;line-height:1.55}
.mu-menu em{margin-left:auto;font-style:normal;color:var(--ink3);align-self:center}
.mu-callout{display:flex;gap:10px;border-radius:10px;padding:11px 14px;margin:0 0 14px;border:1px solid;font-size:13px;line-height:1.65}
.mu-callout .i{font-size:16px;flex:none;line-height:1.4}.mu-callout.info{background:var(--bluebg);border-color:#c9d8fb;color:var(--blue)}
.mu-callout.warn{background:var(--amberbg);border-color:#f3dba0;color:var(--amber)}.mu-callout.danger{background:var(--redbg);border-color:#fbcaca;color:var(--red)}
.mu-callout.ok{background:var(--greenbg);border-color:#bbf0cd;color:var(--green)}
@media(prefers-color-scheme:dark){.mu-callout.info,.mu-callout.warn,.mu-callout.danger,.mu-callout.ok{border-color:var(--line)}}
.mu-callout b{color:inherit}.mu-callout div{color:var(--ink)}
.mu-alert{border:1px solid #f1b4b4;border-left:4px solid var(--red);background:var(--redbg);border-radius:var(--r);padding:13px 16px 11px;margin:0 0 14px}
.mu-alert-h{display:flex;align-items:center;gap:9px;color:var(--red);font-size:15px;letter-spacing:-.02em;margin-bottom:5px}.mu-alert-h span{font-size:19px}
.mu-alert-l{margin:5px 0 0;padding-left:20px;color:var(--ink);font-size:13px;line-height:1.7}.mu-alert-l li{margin:2px 0}.mu-alert-l b{color:var(--red)}.mu-alert a{color:var(--red);font-weight:700}
.mu-alert.slim{display:flex;gap:10px;padding:10px 14px;font-size:13px;margin-top:14px}.mu-alert.slim b{color:var(--red)}
.mu-search{display:flex;gap:8px;margin:0 0 12px;flex-wrap:wrap}.mu-search input{flex:1;min-width:200px;border:1px solid var(--line);border-radius:10px;padding:10px 14px;font:inherit;font-size:15px;background:var(--surface);color:var(--ink)}
.mu-search input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(36,87,214,.14)}
.mu-verdict{border-radius:10px;padding:11px 14px;margin:0 0 12px;border:1px solid;font-size:13.5px;line-height:1.7}.mu-verdict b{display:block;font-size:15px}
.mu-verdict.hit{background:var(--redbg);border-color:#fbcaca;color:var(--red)}.mu-verdict.miss{background:var(--amberbg);border-color:#f3dba0;color:var(--amber)}.mu-verdict div{color:var(--ink)}
.mu-badge{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11.5px;font-weight:700;background:var(--surface2);color:var(--ink2);border:1px solid var(--line)}
.mu-badge.red{background:var(--redbg);color:var(--red);border-color:transparent}.mu-badge.blue{background:var(--bluebg);color:var(--blue);border-color:transparent}
.mu-badge.green{background:var(--greenbg);color:var(--green);border-color:transparent}.mu-badge.amber{background:var(--amberbg);color:var(--amber);border-color:transparent}
.mu-tw{overflow-x:auto}.mu-tbl{width:100%;border-collapse:collapse;font-size:13px}
.mu-tbl th{position:sticky;top:0;background:var(--surface2);color:var(--ink2);font-size:12px;text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
.mu-tbl td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}.mu-tbl tr:last-child td{border-bottom:0}.mu-tbl tbody tr:hover td{background:var(--surface2)}
.mu-sub{color:var(--ink3);font-size:12px}.mu-btn{appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:7px 14px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.mu-btn:hover{border-color:var(--accent2)}.mu-btn.primary{background:var(--accent);color:#fff;border-color:transparent}
.mu-btn.primary:hover{background:#1b45b8}.mu-btn.big{padding:11px 20px;font-size:15px;border-radius:10px}.mu-btn[disabled]{opacity:.5;cursor:default}
.mu-empty{padding:30px 16px;text-align:center;color:var(--ink3)}.mu-empty b{display:block;font-size:26px;margin-bottom:4px}
.mu-foot{max-width:1080px;margin:0 auto;padding:0 18px 36px;color:var(--ink3);font-size:12px;line-height:1.7;text-align:center}
.mu-foot a{color:var(--ink2)}
@media(max-width:560px){.mu-hero h1{font-size:19px}.mu-hero-in{padding:16px 14px 14px}.mu-tbl th,.mu-tbl td{padding:8px}.mu-brand{margin-right:0}.mu-nav{margin-left:0;width:100%}.mu-top-in{padding:8px 12px}.mu-wrap{padding:12px 12px 40px}}

/* ── MiniAI(수동 AI 도우미 창) ── */
.ma-ov{position:fixed;inset:0;background:rgba(8,13,27,.62);backdrop-filter:blur(3px);z-index:9999;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:4vh 12px}
.ma-box{background:var(--surface,#fff);color:var(--ink,#0f172a);border-radius:14px;width:100%;max-width:720px;box-shadow:0 30px 80px -20px rgba(0,0,0,.55);overflow:hidden;font:14px/1.6 'Pretendard','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif}
.ma-h{background:#0f2342;color:#fff;padding:14px 18px;display:flex;align-items:center;gap:10px}
.ma-h b{font-size:17px;letter-spacing:-.02em;flex:1}.ma-x{background:rgba(255,255,255,.14);color:#fff;border:0;border-radius:10px;width:32px;height:32px;font-size:16px;cursor:pointer}
.ma-dots{display:flex;gap:6px;padding:10px 20px 0;flex-wrap:wrap}.ma-dot{font-size:12px;padding:3px 10px;border-radius:999px;border:1px solid var(--line,#e5e9f2);color:var(--ink3,#94a3b8)}
.ma-dot.on{background:#2457d6;color:#fff;border-color:#2457d6}.ma-dot.done{background:#dcfce7;color:#15803d;border-color:#bbf7d0}
.ma-b{padding:14px 20px 20px}.ma-step{border:1px solid var(--line,#e5e9f2);border-radius:14px;padding:14px 16px;margin:0 0 12px;background:var(--surface2,#f8fafc)}
.ma-step.cur{border-color:#4a78e8;box-shadow:0 0 0 3px rgba(91,124,250,.14);background:var(--surface,#fff)}
.ma-sn{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#2457d6;color:#fff;font-size:13px;font-weight:700;margin-right:8px}
.ma-step.done .ma-sn{background:#16a34a}.ma-st{font-weight:700}.ma-d{color:var(--ink2,#475569);font-size:13.5px;margin:6px 0 0}
.ma-chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.ma-chip{border:1px solid var(--line,#e5e9f2);background:var(--surface,#fff);color:var(--ink,#0f172a);border-radius:999px;padding:6px 13px;font:inherit;font-size:13.5px;cursor:pointer}
.ma-chip.on{background:#0b1730;color:#fff;border-color:#0b1730;font-weight:700}
.ma-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
.ma-live{display:flex;align-items:center;gap:8px;font-size:13.5px;margin-top:10px;padding:9px 12px;border-radius:11px;background:var(--bluebg,#eff6ff);color:var(--blue,#1d4ed8)}
.ma-live.ok{background:var(--greenbg,#f0fdf4);color:var(--green,#15803d)}.ma-live.bad{background:var(--amberbg,#fffbeb);color:var(--amber,#b45309)}
.ma-pulse{width:9px;height:9px;border-radius:50%;background:currentColor;animation:mapulse 1.3s infinite}@keyframes mapulse{0%{opacity:1;transform:scale(1)}60%{opacity:.25;transform:scale(1.6)}100%{opacity:1;transform:scale(1)}}
.ma-ta{width:100%;min-height:120px;border:1px solid var(--line,#e5e9f2);border-radius:12px;padding:10px 12px;font:13px/1.55 ui-monospace,Consolas,monospace;background:var(--surface,#fff);color:var(--ink,#0f172a);resize:vertical;margin-top:10px}
.ma-ta.glow{border-color:#4a78e8;box-shadow:0 0 0 3px rgba(91,124,250,.18)}
.ma-pv{margin-top:10px;max-height:300px;overflow:auto;border:1px solid var(--line,#e5e9f2);border-radius:12px}
.ma-sw{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--ink2,#475569);margin-top:10px}
.ma-btn{appearance:none;border:1px solid var(--line,#e5e9f2);background:var(--surface,#fff);color:var(--ink,#0f172a);border-radius:8px;padding:8px 14px;font:inherit;font-size:13.5px;font-weight:600;cursor:pointer}
.ma-btn.p{background:#2457d6;color:#fff;border-color:transparent}.ma-btn.big{padding:13px 22px;font-size:16px;border-radius:14px}.ma-btn[disabled]{opacity:.5;cursor:default}.ma-btn.okd[disabled]{opacity:1;background:#16a34a;color:#fff;box-shadow:none}
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
function ownAttr(){try{return document.documentElement.getAttribute('data-mini-helper')||''}catch(e){return ''}}
function topAttr(){try{if(window.top&&window.top!==window)return window.top.document.documentElement.getAttribute('data-mini-helper')||''}catch(e){}return ''}
function helperVer(){return ownAttr()||topAttr()}
function helperHas(){return !!helperVer()}
function helperOk(){return helperHas()&&verGE(helperVer(),'1.5.1')}
function helperOn(){return helperOk()&&lsGet('mini_ai_helper')!=='0'}
// 메뉴 화면은 메인 화면 안의 탭(iframe)으로 열리는데, 도우미는 맨 바깥 화면에만 붙어요 → 작업을 바깥 화면에 맡겼다가 결과를 다시 받아요(메인 화면의 중계)
function bridge(kind,obj){try{var n=document.createElement('div');n.hidden=true;n.setAttribute('data-mini-bridge',kind);n.textContent=JSON.stringify(obj);document.documentElement.appendChild(n);setTimeout(function(){try{n.parentNode&&n.parentNode.removeChild(n)}catch(e){}},15000)}catch(e){}}
function helperPost(job){try{if(ownAttr()){var jj={id:job.id,prompt:job.prompt,host:job.host,open:job.open||''};window.postMessage(Object.assign({miniHelper:'job'},jj),location.origin);bridge('job',jj)}else window.top.postMessage({miniRelay:'job',id:job.id,prompt:job.prompt,host:job.host,open:job.open||''},location.origin)}catch(e){}}
function newJob(){var a='abcdefghijklmnopqrstuvwxyz0123456789',o='';for(var i=0;i<12;i++)o+=a.charAt(Math.floor(Math.random()*a.length));return o}
function openUrl(u){var a=document.createElement('a');a.href=u;a.target='_blank';a.rel='noopener';document.body.appendChild(a);a.click();document.body.removeChild(a)}
function ensureStyle(){if(document.getElementById('ma-style-flag'))return;var f=el('span');f.id='ma-style-flag';f.style.display='none';document.body.appendChild(f);
 if(document.querySelector('link[href*="mini-ui.css"]'))return;
 if(!window.__MA_CSS__){var lk=document.createElement('link');lk.rel='stylesheet';lk.href=window.__MA_CSS_URL__||'/assets/mini-ui.css';document.head.appendChild(lk);return}var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';
 var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=window.__MA_CSS__;document.head.appendChild(s)}
var cfgSite=null;
function siteDefault(){var s=lsGet('mini_ai_site');if(s&&SITES[s])return s;return (cfgSite&&SITES[cfgSite])?cfgSite:'gemini'}
var cfgMode=null;
var cfgP=fetch('/api/ui/config',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){cfgSite=j.ai_site;cfgMode=j.run_mode||'auto';return j}).catch(function(){return {}});
// [v171] 관리자 로그인 + 서버 AI 키가 있는지(있으면 창 없이 서버가 AI를 대신 실행)
var admP=null,admAt=0;
function admInfo(){var now=Date.now();if(admP&&now-admAt<30000)return admP;admAt=now;
 admP=fetch('/admin/api/whoami',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.ok?r.json():{admin:false}}).then(function(w){if(!w||!w.admin)return {admin:false};
  return fetch('/admin/api/ai/status',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.ok?r.json():{}}).then(function(a){return {admin:true,csrf:w.csrf||'',server:!!a.server,provider:a.provider||'',mode:a.mode||'auto'}})}).catch(function(){return {admin:false}});return admP}
function resolveMode(opt){return cfgP.then(function(){var m=lsGet('mini_ai_run')||cfgMode||'auto';if(opt&&opt.noAuto)m='manual';if(m==='manual')return {m:'manual'};
  if(m==='auto')return admInfo().then(function(a){return (a.admin&&a.server&&lsGet('mini_ai_server')!=='0')?{m:'server',a:a}:{m:'browser'}});return {m:'browser'}})}
var PROVN={gemini:'Gemini',anthropic:'Claude',openai:'OpenAI'};

// opt: {title, steps:[{label, prompt}], minLen, hint, preview:function(text)->Promise<{ok,node|text,canApply}>, apply:function(text,step)->Promise<{message}>, autoApply, onClose}
function run(opt){
 ensureStyle();
 var steps=(opt.steps||[]).filter(function(s){return s&&s.prompt});if(!steps.length)return;
 var cur=0,notice='',site=siteDefault(),armed=false,seen={},lastText='',busy=false,closed=false,doneSet={},curJob=null,gotMsg=false,hTm=null;
 var sTm=null,autoOn=false,needClick=false,srvRun=0,retried={},lastMsg=null,aLive=null,runMode='manual',runInfo=null,autoNote='';var srvErr='',acked=false;
 var minLen=opt.minLen||60;
 var ov=el('div','ma-ov'),box=el('div','ma-box');ov.setAttribute('tabindex','-1');ov.appendChild(box);
 var h=el('div','ma-h');h.appendChild(el('b',null,opt.title||'AI로 분석하기'));var x=el('button','ma-x','✕');x.onclick=close;h.appendChild(x);box.appendChild(h);
 var dots=el('div','ma-dots');box.appendChild(dots);var body=el('div','ma-b');box.appendChild(body);
 ov.addEventListener('mousedown',function(e){if(e.target===ov)ov._dn=1});ov.addEventListener('mouseup',function(e){if(e.target===ov&&ov._dn)close();ov._dn=0});
 document.body.appendChild(ov);document.body.style.overflow='hidden';
 function close(){if(closed)return;closed=true;armed=false;clearTimeout(hTm);clearTimeout(sTm);window.removeEventListener('message',onMsg);window.removeEventListener('focus',onBack);window.removeEventListener('pageshow',onBack);document.removeEventListener('pointerdown',onPtr,true);clearInterval(wTm);document.removeEventListener('visibilitychange',onVis);document.removeEventListener('keydown',onKey);document.body.removeChild(ov);document.body.style.overflow='';if(opt.onClose)opt.onClose()}
 function onKey(e){if(e.key==='Escape')close()}document.addEventListener('keydown',onKey);
 function drawDots(){dots.innerHTML='';if(steps.length<2)return;steps.forEach(function(s,i){var d=el('span','ma-dot'+(doneSet[i]?' done':(i===cur?' on':'')),(doneSet[i]?'✓ ':'')+(s.label||('프롬프트 '+(i+1))));dots.appendChild(d)})}
 var live,ta,pvBox,applyBtn,autoCb;
 function setLive(msg,kind,pulse){lastMsg={m:msg,k:kind,p:pulse};if(live){live.className='ma-live'+(kind?' '+kind:'');live.innerHTML='';if(pulse)live.appendChild(el('span','ma-pulse'));live.appendChild(el('span',null,msg))}
  if(aLive&&autoOn){aLive.className='ma-live'+(kind?' '+kind:'');aLive.innerHTML='';if(pulse)aLive.appendChild(el('span','ma-pulse'));aLive.appendChild(el('span',null,msg))}}
 function draw(){
  drawDots();body.innerHTML='';var s=steps[cur];
  if(notice){body.appendChild(el('div','ma-live ok',notice));notice=''}
  if(srvErr&&!lastText){var eb=el('div','ma-live bad');eb.style.flexDirection='column';eb.style.alignItems='flex-start';eb.appendChild(el('div',null,'⚠ 서버 AI가 실패했어요 — '+srvErr));
   if(runInfo&&runInfo.server){var rb=el('button','ma-btn','🔁 서버 AI 다시 시도');rb.style.marginTop='6px';rb.onclick=function(){srvErr='';runMode='server';autoOn=true;needClick=false;lastText='';startAuto()};eb.appendChild(rb)}
   body.appendChild(eb)}
  aLive=null;
  if(autoOn){var ab=el('div','ma-step cur');var at=el('div');at.appendChild(el('span','ma-sn','🤖'));at.appendChild(el('span','ma-st','완전 자동 진행 중'+(steps.length>1?' ('+(cur+1)+'/'+steps.length+' · '+(s.label||'')+')':'')));ab.appendChild(at);
   ab.appendChild(el('div','ma-d',autoNote||''));aLive=el('div','ma-live ok');ab.appendChild(aLive);
   var ar=el('div','ma-row');if(armed&&runMode!=='server'){var pb2=el('button','ma-btn','📥 답변 가져오기');pb2.title='AI 화면에서 복사한 답변을 지금 읽어 와요';pb2.onclick=function(){pullClip(true)};ar.appendChild(pb2)}var tm2=el('button','ma-btn','✋ 직접 진행하기');tm2.onclick=function(){toManual()};ar.appendChild(tm2);ab.appendChild(ar);body.appendChild(ab)}
  var showS1=!autoOn||needClick,showS2=!autoOn,showS3=!autoOn;
  // 1) AI 열기
  var s1=el('div','ma-step'+(armed?'':' cur'));var t1=el('div');t1.appendChild(el('span','ma-sn','1'));t1.appendChild(el('span','ma-st','프롬프트 복사하고 AI 열기'));s1.appendChild(t1);
  var chips=el('div','ma-chips');Object.keys(SITES).forEach(function(k){var c=el('button','ma-chip'+(k===site?' on':''),SITES[k].i+' '+SITES[k].n);c.onclick=function(){site=k;lsSet('mini_ai_site',k);draw()};chips.appendChild(c)});s1.appendChild(chips);
  var row=el('div','ma-row');var go=el('button','ma-btn p big',SITES[site].i+' 복사하고 '+SITES[site].n+' 열기');go.onclick=function(){openAI(s)};row.appendChild(go);
  var sh=el('button','ma-btn','프롬프트 보기');sh.onclick=function(){var p=s1.querySelector('.ma-pre');if(p){p.remove();return}var pre=el('pre','ma-pre');pre.textContent=s.prompt;s1.appendChild(pre)};row.appendChild(sh);
  var rc=el('button','ma-btn','📋 다시 복사');rc.onclick=function(){armed=true;seen[norm(s.prompt)]=1;var k=copyText(s.prompt);setLive(k?'프롬프트를 다시 복사했어요.':'복사가 막혔어요. [프롬프트 보기]에서 직접 복사해 주세요.',k?'ok':'bad')};row.appendChild(rc);s1.appendChild(row);
  if(helperOk()){var hl=el('label','ma-sw');var hc=el('input');hc.type='checkbox';hc.checked=helperOn();hc.onchange=function(){lsSet('mini_ai_helper',hc.checked?'1':'0');draw()};hl.appendChild(hc);hl.appendChild(el('span',null,'🤖 AI 도우미 사용 — 입력·전송·답변 복사를 자동으로 (끄면 직접 붙여넣기)'));s1.appendChild(hl);
   s1.appendChild(el('div','ma-d','✅ 도우미 연결됨 (v'+helperVer()+')'))}
  else{var hn=el('div','ma-live bad');hn.appendChild(document.createTextNode(helperHas()?'❌ 설치된 AI 도우미(v'+helperVer()+')가 옛 버전이라 작업을 받지 못해요 — [설치·점검 방법]에서 최신 버전(1.5.11)으로 업데이트(재설치)한 뒤 이 화면을 새로고침하세요. 그때까지는 ‘복사 → 붙여넣기’ 방식으로 진행돼요. ':'❌ AI 도우미가 이 화면에서 감지되지 않아요 — 지금은 ‘복사 → 붙여넣기’ 방식으로 진행돼요. 설치했다면: 크롬 확장 프로그램 → Tampermonkey → 사이트 액세스 ‘모든 사이트에서’, ‘사용자 스크립트 허용’ 켜기 → 이 화면 새로고침. '));
   var hr=el('button','ma-btn','🔄 다시 확인');hr.onclick=function(){if(helperHas()){draw()}else{hr.textContent='아직 감지 안 됨 — 새로고침이 필요해요'}};hn.appendChild(hr);hn.appendChild(document.createTextNode(' '));
   var ha=el('a',null,'설치·점검 방법');ha.href='/ai-helper';ha.target='_blank';ha.rel='noopener';hn.appendChild(ha);s1.appendChild(hn)}
  s1.appendChild(el('div','ma-d',helperOn()?SITES[site].n+' 새 탭이 열리면 도우미가 프롬프트 입력 → 전송 → 답변 복사까지 알아서 하고, 끝나면 탭을 닫으며 답변을 이 창으로 보내 줘요. 위쪽 🤖 띠에서 진행 상황을 볼 수 있어요.':(SITES[site].q&&encodeURIComponent(s.prompt).length<=PREFILL_MAX*3?SITES[site].n+'가 열리면 질문이 자동으로 입력됩니다. 입력이 비어 있으면 입력칸에 Ctrl+V 하세요.':SITES[site].n+'가 열리면 입력칸에 Ctrl+V(붙여넣기) 한 번만 하세요. 프롬프트는 이미 복사되어 있습니다.')));
  if(showS1)body.appendChild(s1);
  // 2) 답변 복사
  var s2=el('div','ma-step'+(armed?' cur':''));var t2=el('div');t2.appendChild(el('span','ma-sn','2'));t2.appendChild(el('span','ma-st','AI 답변을 복사하고 이 창으로 돌아오기'));s2.appendChild(t2);
  s2.appendChild(el('div','ma-d',opt.hint||'답변이 끝나면 답변 아래의 복사 버튼(또는 전체 선택 후 Ctrl+C)을 누르고 이 탭으로 돌아오세요. 돌아오는 순간 자동으로 읽어옵니다.'));
  live=el('div','ma-live');s2.appendChild(live);if(!autoOn)setLive(armed?'AI 답변을 기다리는 중… 복사하고 이 탭으로 돌아오세요.':'위 버튼을 누르면 자동 감지가 시작됩니다.',null,armed);
  var r2=el('div','ma-row');var pull=el('button','ma-btn','📥 클립보드에서 가져오기');pull.onclick=function(){pullClip(true)};r2.appendChild(pull);s2.appendChild(r2);if(showS2)body.appendChild(s2);
  // 3) 확인·적용
  var s3=el('div','ma-step');var t3=el('div');t3.appendChild(el('span','ma-sn','3'));t3.appendChild(el('span','ma-st','내용 확인하고 저장'));s3.appendChild(t3);
  ta=el('textarea','ma-ta');ta.placeholder='여기에 AI 답변이 자동으로 들어옵니다. 안 들어오면 이 칸을 누르고 Ctrl+V 하세요.';ta.value=lastText;
  ta.addEventListener('paste',function(){setTimeout(function(){onText(ta.value,true)},30)});var ptm=null;ta.addEventListener('input',function(){lastText=ta.value;if(applyBtn&&!busy&&!doneSet[cur])applyBtn.disabled=!(ta.value.trim().length>=Math.min(minLen,40));clearTimeout(ptm);ptm=setTimeout(function(){if(ta.value.trim())preview(ta.value,true)},400)});s3.appendChild(ta);
  pvBox=el('div');s3.appendChild(pvBox);var r3=el('div','ma-row');
  var pv=el('button','ma-btn','미리보기');pv.onclick=function(){preview(ta.value)};r3.appendChild(pv);
  applyBtn=el('button','ma-btn p','저장');applyBtn.setAttribute('data-noconfirm','1');applyBtn.disabled=true;applyBtn.onclick=function(){doApply()};r3.appendChild(applyBtn);s3.appendChild(r3);
  if(opt.apply){var sw=el('label','ma-sw');autoCb=el('input');autoCb.type='checkbox';var _av=lsGet('mini_ai_auto_'+(opt.key||'x'));autoCb.checked=(_av===null)?true:(_av==='1')||!!opt.autoApply;autoCb.onchange=function(){lsSet('mini_ai_auto_'+(opt.key||'x'),autoCb.checked?'1':'0')};sw.appendChild(autoCb);sw.appendChild(el('span',null,'답변을 읽으면 확인 없이 바로 저장 (저장되면 "✅ 저장 완료"로 바뀌어요)'));s3.appendChild(sw)}
  if(showS3)body.appendChild(s3);if(lastText)preview(lastText,true);
  if(autoOn&&lastMsg)setLive(lastMsg.m,lastMsg.k,lastMsg.p)}
 /* [v186] AI 창은 '작은 팝업 창' 하나로만 열어요(같은 이름의 창을 다시 쓰므로 두 번 열리지 않고, 답변을 받으면 사이트가 직접 닫아요). 팝업이 막히면 false → 기존 방식(도우미/새 탭)으로. */
 function openWin(url){try{if(lsGet('mini_ai_popup')==='0')return false;var now=Date.now(),W=window.top||window,ex=W.__miniAiWin;if(ex&&!ex.closed&&now-(W.__miniAiWinT||0)<2500){try{ex.focus()}catch(e){}return true}
  var sw=screen.availWidth||1200,sh=screen.availHeight||800,w=Math.min(540,sw-40),h=Math.min(780,sh-80),l=Math.max(0,(screen.availLeft||0)+sw-w-16),t=Math.max(0,(screen.availTop||0)+40);
  var win=window.open(url,'mini_ai_win','popup=yes,width='+w+',height='+h+',left='+l+',top='+t+',resizable=yes,scrollbars=yes');
  if(!win)return false;W.__miniAiWin=win;W.__miniAiWinT=now;try{win.focus()}catch(e){}return true}catch(e){return false}}
 function winClose(){try{var W=window.top||window,w=W.__miniAiWin;if(w&&!w.closed)setTimeout(function(){try{w.close()}catch(e){}},1200);W.__miniAiWin=null}catch(e){}}
 function openAI(s,auto){var ok=copyText(s.prompt);var S=SITES[site],u=S.u,viaHelper=false,blocked=false;
  var hv=helperVer(),hOpen=helperOn()&&hv&&verGE(hv,'1.5.1');
  if(helperOn()){curJob=newJob();var hostN='';try{hostN=new URL(S.u).hostname}catch(e){}
   var pl='';try{if(s.prompt.length<=24000)pl='&p='+btoa(unescape(encodeURIComponent(s.prompt))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')}catch(e){pl=''}
   var tabUrl=S.u+'#miniai='+curJob+pl;
   var popOk=openWin(tabUrl);helperPost({id:curJob,prompt:s.prompt,host:hostN,open:(!popOk&&hOpen)?tabUrl:''});gotMsg=false;acked=false;clearTimeout(hTm);
   var w=null;if(popOk||hOpen)w=true;else{try{w=window.open(tabUrl,'_blank')}catch(e){w=null}}
   if(w){viaHelper=true;var jb=curJob;hTm=setTimeout(function(){if(!gotMsg&&!closed&&curJob===jb)fallbackManual((acked?'⚠ 도우미가 작업은 받았지만 20초가 지나도 '+S.n+' 탭에서 진행 신호가 없어요(로그인·화면 개편 여부 확인). 프롬프트는 복사돼 있으니 입력칸에 Ctrl+V 해서 이어가세요. 점검:':'⚠ 20초가 지나도 도우미 응답이 없어요. 프롬프트는 복사돼 있으니 '+S.n+' 입력칸에 Ctrl+V 해서 이어가세요. 도우미가 동작하게 하려면:')+' ① 크롬 확장 프로그램 → Tampermonkey → 사이트 액세스 ‘모든 사이트에서’ ② 같은 곳의 ‘사용자 스크립트 허용’ 켜기 ③ 열려 있는 AI 탭을 새로고침 ④ 이 화면도 새로고침 후 다시 시도.')},20000)}else{curJob=null;blocked=!tryOpen(u)}}
  else{var pre=false;if(S.q){var enc=encodeURIComponent(s.prompt);if(enc.length<=PREFILL_MAX*3){u=S.q+enc;pre=true}}
   if(auto&&!ok&&!pre){blocked=true}else blocked=!tryOpen(u)}
  if(blocked&&auto){needClick=true;armed=false;draw();setLive('⚠ 브라우저가 새 탭 열기(또는 복사)를 막았어요. 아래 버튼을 한 번만 눌러 주세요 — 그다음부터는 자동이에요. (주소창 오른쪽 ‘팝업 차단됨’ 아이콘 → 이 사이트 항상 허용 → 다음부터는 누를 필요도 없어요)','bad');return}
  needClick=false;armed=true;seen[norm(s.prompt)]=1;draw();
  if(viaHelper)setLive('🤖 도우미가 '+S.n+' 탭에서 진행 중이에요 — 입력·전송·답변 복사가 끝나면 자동으로 돌아와요. (안 되면 직접 Ctrl+V)','ok',true);
  else if(auto)setLive(ok||pre?'📋 '+S.n+'가 열렸어요 — 답변이 끝나면 복사 버튼만 누르고 이 탭으로 돌아오세요. 나머지(읽기·저장·다음 단계)는 자동이에요.':'복사가 막혔어요. 아래 [프롬프트 보기]에서 직접 복사해 주세요.',ok||pre?'ok':'bad',ok||pre);
  else setLive(ok?'📋 프롬프트 복사 완료 — '+S.n+'에서 답변을 받은 뒤 복사하고 돌아오세요.':'복사가 막혔어요. [프롬프트 보기]에서 직접 복사해 주세요.',ok?'ok':'bad',ok)}
 // 도우미가 응답이 없거나 오래 멈추면: 자동 화면을 접고 직접 진행 화면(복사 → 자동 읽기)으로 바꿔 줘요 — '멈춘 채로' 두지 않아요
 function fallbackManual(msg){if(closed||lastText)return;clearTimeout(sTm);autoOn=false;needClick=false;armed=true;draw();setLive(msg,'bad')}
 function tryOpen(u){if(openWin(u))return true;var w=null;try{w=window.open('about:blank','_blank');if(w){try{w.opener=null}catch(e){}w.location.href=u;return true}}catch(e){}return false}
 // ── [v171] 완전 자동: 서버 AI(관리자+API 키) → 창 없이 실행 / 아니면 AI 사이트를 자동으로 열어 진행 ──
 function toManual(){srvRun++;autoOn=false;needClick=false;draw();if(!armed)setLive('직접 진행 모드예요. 위 버튼을 누르면 자동 감지가 시작됩니다.',null,false)}
 function postJ(u,o){return fetch(u,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':(runInfo&&runInfo.csrf)||''},body:JSON.stringify(o||{})}).then(function(r){return r.json().catch(function(){return {}}).then(function(j){if(!r.ok&&!j.error)j.error='HTTP '+r.status;return j})})}
 function runServer(s,extra){var tok=++srvRun;srvErr='';var pn=PROVN[runInfo&&runInfo.provider]||'AI';autoNote='서버가 '+pn+'로 직접 분석해요. 새 창·복사·붙여넣기 없이 끝까지 자동으로 진행돼요(보통 20~90초).';armed=false;draw();
  var t0=Date.now();setLive('🤖 '+pn+'가 분석 중이에요…','ok',true);
  postJ('/admin/api/ai/start',{prompt:s.prompt+(extra||''),max_tokens:opt.maxTokens||12000}).then(function(j){if(tok!==srvRun||closed)return;if(!j.job)throw new Error(j.error||'시작하지 못했어요');poll(j.job,tok,t0,0)}).catch(function(e){if(tok!==srvRun||closed)return;srvFail(String((e&&e.message)||e),s)})}
 function poll(id,tok,t0,n){setTimeout(function(){if(tok!==srvRun||closed)return;
   fetch('/admin/api/job/'+id,{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.json()}).then(function(j){if(tok!==srvRun||closed)return;
    if(j.status==='running'){setLive('🤖 '+(PROVN[runInfo&&runInfo.provider]||'AI')+'가 분석 중이에요… '+Math.round((Date.now()-t0)/1000)+'초','ok',true);if(n>200)return srvFail('응답이 너무 오래 걸려요',steps[cur]);return poll(id,tok,t0,n+1)}
    if(j.status==='done'&&j.result&&j.result.text){lastRaw=j.result.text;onText(String(j.result.text).trim(),false,true);return}
    srvFail((j.errors&&j.errors[0])||j.error||'AI 응답 실패',steps[cur])}).catch(function(){if(tok!==srvRun||closed)return;if(n>200)srvFail('응답을 받지 못했어요',steps[cur]);else poll(id,tok,t0,n+1)})},n===0?1500:2500)}
 function oldHelperNote(){return (helperHas()&&!helperOk())?' ⚠ 설치된 AI 도우미(v'+helperVer()+')는 옛 버전이라 쓰지 않아요 — /ai-helper 에서 최신 버전(1.5.11)으로 업데이트(재설치)하면 완전 자동이 돼요.':''}
 function srvHint(m){m=String(m||'');var h='';
  if(/429|quota|RESOURCE_EXHAUSTED|rate.?limit/i.test(m))h='AI 사용 한도(쿼터)를 넘었거나 결제 설정이 필요해요.';
  else if(/401|403|API.?key|PERMISSION|unauthor/i.test(m))h='API 키가 틀렸거나 권한이 없어요(Render 환경변수 확인).';
  else if(/404|not.?found|model/i.test(m))h='모델 이름이 맞지 않아요(관리자 → 설정 → AI의 모델 칸 확인).';
  else if(/503|500|overload|UNAVAILABLE|timed? ?out/i.test(m))h='AI 서버가 바쁘거나 응답이 늦었어요. 잠시 뒤 다시 시도해 보세요.';
  else if(/빈 답|MAX_TOKENS|SAFETY/i.test(m))h='AI가 답을 비워 보냈어요. 다시 시도해 보세요.';
  return m.slice(0,200)+(h?' → '+h:'')}
 var lastRaw='';
 function srvFail(msg,s){srvRun++;srvErr=srvHint(msg);
  // 서버 AI가 안 되면 AI 사이트를 자동으로 열어 이어가기(브라우저 자동)
  runMode='browser';autoNote='서버 AI가 안 돼서(' + String(msg).slice(0,80) + ') AI 사이트를 자동으로 열어 진행해요.'+oldHelperNote();setLive('⚠ 서버 AI 실패 — AI 사이트로 자동 전환합니다…','bad');openAI(s||steps[cur],true)}
 function startAuto(){if(closed||!autoOn)return;var s=steps[cur];retried[cur]=retried[cur]||0;
  if(runMode==='server')runServer(s);else{autoNote=(helperOn()?'도우미가 AI 사이트에서 입력·전송·답변 복사까지 자동으로 해요.':'AI 사이트가 자동으로 열려요. 답변이 끝나면 복사 버튼만 누르고 이 탭으로 돌아오세요 — 읽기·저장·다음 단계는 자동이에요.'+oldHelperNote());openAI(s,true)}}
 function bootAuto(){resolveMode(opt).then(function(r){if(closed)return;runMode=r.m;runInfo=r.a||null;if(r.m==='manual'){if(autoOn){autoOn=false;draw()}return}autoOn=true;startAuto()})}
 function onMsg(e){if(closed||(e.source!==window&&e.source!==window.top)||e.origin!==location.origin)return;var d=e.data;if(!d||(d.miniHelper!=='status'&&d.miniHelper!=='result')||!curJob||d.id!==curJob)return;if(d.ack){acked=true;if(armed)setLive('🤖 '+d.msg,'ok',true);return}gotMsg=true;clearTimeout(hTm);clearTimeout(sTm);var jb2=curJob;sTm=setTimeout(function(){if(!closed&&curJob&&curJob===jb2&&!lastText)fallbackManual('⚠ 도우미가 4분 넘게 답이 없어요. AI 화면에서 답변 아래 복사 버튼을 누르고 이 탭으로 돌아오면 자동으로 읽어요. (또는 아래 [📥 클립보드에서 가져오기])')},240000);
  if(d.miniHelper==='status'){if(armed)setLive('🤖 '+d.msg,'ok',true);return}
  if(d.miniHelper==='result'){if(d.error){setLive('🤖 자동 진행이 멈췄어요('+d.error+'). 프롬프트는 복사돼 있어요 — AI 입력칸에 Ctrl+V 하고 직접 이어가세요.','bad');return}
   var t=stripPrompt(String(d.text||'').trim());if(t.length<minLen){setLive('🤖 답변이 너무 짧게 읽혔어요('+t.length+'자). AI 화면에서 직접 복사해 주세요.','bad');return}
   if(seen[norm(t)]&&lastText&&norm(lastText)===norm(t))return;curJob=null;onText(t,false)}}
 window.addEventListener('message',onMsg);
 function stripPrompt(t){var raw=String(t||'').trim();for(var i=0;i<steps.length;i++){var p=String(steps[i].prompt||'').trim();if(p.length<80)continue;var tail=p.slice(-48).replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/\s+/g,'\\s+');
   try{var m=new RegExp(tail).exec(raw);if(m&&raw.slice(0,60).replace(/\s+/g,' ')===p.slice(0,60).replace(/\s+/g,' ')){var rest=raw.slice(m.index+m[0].length).trim();if(rest.length>=minLen)return rest}}catch(e){}}
  return raw}
 function looksLikeAnswer(t,manual){t=stripPrompt(t);if(t.length<minLen)return false;var n=norm(t);if(!manual&&seen[n])return false;
  for(var i=0;i<steps.length;i++){var p=norm(steps[i].prompt);if(n===p||(p&&n.slice(0,60)===p.slice(0,60)))return false}return true}
 var pulling=false,pfail=0,hinted=false;
 function pullClip(manual,tries,quiet){tries=tries||0;
  if(!(navigator.clipboard&&navigator.clipboard.readText)){if(manual)setLive('이 브라우저는 자동 읽기를 지원하지 않아요. 아래 칸을 누르고 Ctrl+V 하세요.','bad');if(ta){ta.classList.add('glow');if(manual)ta.focus()}return}
  if(pulling&&!manual&&tries===0)return;pulling=true;
  navigator.clipboard.readText().then(function(t){pulling=false;pfail=0;t=stripPrompt((t||'').trim());if(looksLikeAnswer(t,manual))onText(t,false);else if(manual){if(t&&seen[norm(t)])setLive('이미 읽어온 답변이에요. 아래 칸의 내용을 확인하고 저장하세요.','ok');else setLive('클립보드에 AI 답변이 없어요. AI 화면에서 답변 아래 복사 버튼을 먼저 누르세요.','bad')}})
  .catch(function(){pulling=false;if(closed)return;
   if(quiet){pfail++;if(pfail>=4&&!hinted&&armed&&!lastText){hinted=true;setLive('자동 읽기가 아직 안 돼요. 이 창을 한 번 클릭하거나 [📥 클립보드에서 가져오기]를 누르세요. (자물쇠 아이콘에서 클립보드 허용을 켜면 다음부터 완전 자동)','bad')}return}
   if(tries<2){setTimeout(function(){pullClip(manual,tries+1,quiet)},700);return}
   setLive('브라우저가 클립보드 읽기를 막았어요. [📥 클립보드에서 가져오기]를 누르거나 아래 칸을 누르고 Ctrl+V 하세요. (주소창 왼쪽 자물쇠에서 클립보드 허용을 켜면 다음부터 자동입니다)','bad');if(ta){ta.classList.add('glow');if(manual)ta.focus()}})}
 // 복사한 뒤 돌아오면 바로 읽기: 창 포커스/탭 전환 이벤트 + (iframe 안에서는 이벤트가 빠지는 경우가 있어) 1초 간격 감시를 함께 사용
 function takeFocus(){try{if(document.hasFocus())return;window.focus();if(ov&&ov.focus)ov.focus({preventScroll:true})}catch(e){}}
 var tm=null;function onBack(){if(!armed||closed)return;clearTimeout(tm);tm=setTimeout(function(){takeFocus();pullClip(false,0,true)},250)}
 function onPtr(){if(!lastText)onBack()}
 function onVis(){if(document.visibilityState==='visible'){hinted=false;onBack()}}
 var wTm=setInterval(function(){if(closed){clearInterval(wTm);return}if(!armed||busy||lastText||document.visibilityState!=='visible')return;takeFocus();pullClip(false,0,true)},1000);
 window.addEventListener('focus',onBack);document.addEventListener('visibilitychange',onVis);window.addEventListener('pageshow',onBack);document.addEventListener('pointerdown',onPtr,true);
 function onText(t,fromPaste,fromSrv){if(!t)return;winClose();t=stripPrompt(t);lastText=t;if(ta){ta.value=t;ta.classList.remove('glow')}seen[norm(t)]=1;setLive(autoOn?'✅ 답변을 받았어요 — 확인하고 저장하는 중…':'✅ 답변을 읽어왔어요. 아래 내용을 확인하세요.','ok',autoOn);
  preview(t,true).then(function(r){
   if(closed)return;
   if(r&&r.canApply&&opt.apply){if(autoOn||(r.strict!==false&&autoCb&&autoCb.checked))doApply();return}
   if(autoOn)autoFail(r,fromSrv)})}
 // 답변 형식이 안 맞을 때: 서버 AI면 한 번 더 요청, 그래도 안 되면(또는 브라우저 방식이면) 직접 확인하도록 넘김
 function autoFail(r,fromSrv){var why=(r&&r.text)||'답변 형식을 읽지 못했어요.';
  if(fromSrv&&runMode==='server'&&!retried[cur]){retried[cur]=1;lastText='';setLive('⚠ '+why+' — 서버 AI에 형식을 다시 지켜 달라고 한 번 더 요청해요…','bad',true);
   runServer(steps[cur],'\n\n[주의] 직전 응답은 위에서 요구한 출력 형식을 지키지 못했습니다. 설명·사과 없이, 요구한 형식 그대로만 다시 출력하세요.');return}
  autoOn=false;needClick=false;notice='⚠ 자동 저장을 못 했어요 — '+why+' 내용을 확인하고 [저장]을 눌러 주세요.';draw()}
 function preview(t,quiet){if(!opt.preview){if(applyBtn)applyBtn.disabled=!t;return Promise.resolve({canApply:!!t})}
  if(!t||!t.trim()){if(!quiet)setLive('답변 내용이 비어 있어요.','bad');return Promise.resolve(null)}
  return Promise.resolve(opt.preview(t,steps[cur])).then(function(r){r=r||{};pvBox.innerHTML='';if(r.node){var w=el('div','ma-pv');w.appendChild(r.node);pvBox.appendChild(w)}else if(r.text){pvBox.appendChild(el('div','ma-live'+(r.canApply?' ok':' bad'),r.text))}
   if(applyBtn&&!doneSet[cur])applyBtn.disabled=!r.canApply;return r}).catch(function(){setLive('미리보기 중 오류가 났어요.','bad');return null})}
 function doApply(){if(busy||!opt.apply)return;busy=true;if(applyBtn){applyBtn.disabled=true;applyBtn.textContent='저장 중…'}
  Promise.resolve(opt.apply(ta.value,steps[cur])).then(function(r){r=r||{};doneSet[cur]=1;drawDots();
   var msg=r.message||'저장했어요.';
   if(applyBtn){applyBtn.textContent='✅ 저장 완료';applyBtn.classList.add('okd')}if(ta)ta.readOnly=true;setLive('✅ '+msg,'ok');
   setTimeout(function(){busy=false;if(closed)return;
    if(cur<steps.length-1){cur++;armed=false;lastText='';if(autoOn){notice='✅ '+msg;draw();startAuto()}else{notice='✅ '+msg+' — 이제 아래 '+(steps[cur].label||'다음')+' 단계를 진행하세요.';draw()}}
    else if(autoOn&&opt.autoClose!==false){close()}
    else{drawDots();body.innerHTML='';var d=el('div','ma-step done');d.appendChild(el('div','ma-st','🎉 '+msg));var b=el('button','ma-btn p','닫기');b.style.marginTop='12px';b.onclick=close;d.appendChild(b);body.appendChild(d);armed=false}},1200)})
  .catch(function(){busy=false;if(applyBtn){applyBtn.disabled=false;applyBtn.textContent='저장'}setLive('저장 중 오류가 났어요. 다시 [저장]을 눌러 주세요.','bad')})}
 autoOn=!opt.noAuto&&((lsGet('mini_ai_run')||cfgMode||'auto')!=='manual');autoNote='AI 실행 방식을 확인하는 중…';lastMsg={m:'🤖 자동 진행을 준비하고 있어요…',k:'ok',p:true};
 draw();
 if(!opt.noAuto)bootAuto();
 return {close:close};
}
function verGE(a,b){var x=String(a||'0').split('.'),y=String(b).split('.');for(var i=0;i<3;i++){var p=parseInt(x[i]||0,10),q=parseInt(y[i]||0,10);if(p!==q)return p>q}return true}
// 블로그 글쓰기 화면에 넣을 내용(제목·상단 이미지·본문)을 도우미에게 맡긴다. 돌려주는 값: sent | off | none(도우미 없음) | old(옛 버전) | err
function blogSend(job){try{if(lsGet('mini_blog_paste')==='0')return 'off';var v=helperVer();if(!v)return 'none';if(!verGE(v,'1.5.1'))return 'old';
 var op=(verGE(v,'1.5.1')&&job.open&&/^https:\/\/([a-z0-9-]+\.)?blog\.naver\.com\//.test(String(job.open)))?String(job.open):'';
 var id=newJob(),imgs=(job.imgs&&job.imgs.length)?job.imgs.slice(0,10):(job.img?[job.img]:[]),m={id:id,title:job.title||'',html:job.html||'',img:imgs[0]||job.img||'',imgs:imgs,open:op};
 if(ownAttr()){window.postMessage({miniHelper:'blogjob',id:m.id,title:m.title,html:m.html,img:m.img,imgs:m.imgs,open:m.open},location.origin);bridge('blogjob',m)}else window.top.postMessage({miniRelay:'blogjob',id:m.id,title:m.title,html:m.html,img:m.img,imgs:m.imgs,open:m.open},location.origin);return op?'sentopen':'sent'}catch(e){return 'err'}}
window.MiniAI={run:run,copy:copyText,sites:SITES,blogSend:blogSend,helperVer:helperVer};
// 점수 오해 방지: '체력지표'가 기업 평가점수가 아님을 알리는 짧은 안내 + 자세히 보기 창
var SCORE_TXT={deep:{calc:'수익성 25% + 안정성 20% + 성장성 20% + 거버넌스 15% + 밸류에이션 20% 를 합친 값(0~100)이에요. 각 축은 공개된 5개년 재무·시세 숫자를 정해진 규칙으로 점수화해요.'},
 lab:{calc:'기술·모멘텀·수급·재무·밸류에이션 5개 축을 정해진 규칙으로 점수화해 합친 값(0~100)이에요. 공개된 시세·재무 숫자만 써요.'}};
function scoreOpen(kind){var T=SCORE_TXT[kind]||SCORE_TXT.deep;var old=document.getElementById('scoreInfoOv');if(old)old.remove();
 var ov=el('div');ov.id='scoreInfoOv';ov.setAttribute('role','dialog');ov.setAttribute('aria-modal','true');var st=ov.style;st.position='fixed';st.left='0';st.top='0';st.right='0';st.bottom='0';st.background='rgba(2,6,23,.55)';st.zIndex='99999';st.display='flex';st.alignItems='center';st.justifyContent='center';st.padding='16px';
 var bx=el('div');var b=bx.style;b.background='#fff';b.color='#0f172a';b.borderRadius='16px';b.maxWidth='520px';b.width='100%';b.maxHeight='88vh';b.overflowY='auto';b.padding='18px 20px';b.boxShadow='0 20px 60px rgba(0,0,0,.4)';b.lineHeight='1.7';b.fontSize='14px';
 var h=el('div',null,'ⓘ 체력지표란? — 기업 평가점수가 아니에요');h.style.fontWeight='900';h.style.fontSize='17px';h.style.marginBottom='8px';bx.appendChild(h);
 function sec(t,items){var d=el('div',null,t);d.style.fontWeight='800';d.style.margin='10px 0 2px';bx.appendChild(d);items.forEach(function(x){var p=el('div',null,'• '+x);p.style.margin='2px 0';bx.appendChild(p)})}
 sec('무엇인가요',['공개된 재무·시세 자료를 정해진 규칙으로 계산한 참고용 숫자예요.',T.calc]);
 sec('담지 않는 것',['사업의 질·경쟁력, 경영진, 산업 전망, 앞으로의 실적, 뉴스·공시의 의미, 적정 주가는 반영되지 않아요.']);
 sec('읽을 때 주의',['숫자가 높다고 좋은 회사·좋은 투자라는 뜻이 아니고, 낮다고 나쁜 회사라는 뜻도 아니에요.','업종·상장 시기·자료 유무에 따라 달라져요(금융업·신규상장·적자 성장기업은 구조적으로 낮게 나올 수 있어요). 다른 업종끼리 숫자를 견줘 보는 건 맞지 않아요.','신용등급·투자의견·추천이 아니에요. 투자 판단과 책임은 본인에게 있어요. 공시 원문(DART·KIND)을 꼭 확인하세요.']);
 var bt=el('button',null,'닫기');var s2=bt.style;s2.marginTop='14px';s2.padding='9px 18px';s2.border='0';s2.borderRadius='10px';s2.background='#0f172a';s2.color='#fff';s2.fontWeight='800';s2.cursor='pointer';s2.fontSize='14px';bt.setAttribute('data-noconfirm','1');bx.appendChild(bt);
 function close(){ov.remove();document.removeEventListener('keydown',onk)}function onk(e){if(e.key==='Escape')close()}bt.onclick=close;ov.onclick=function(e){if(e.target===ov)close()};document.addEventListener('keydown',onk);ov.appendChild(bx);document.body.appendChild(ov);bt.focus()}
function scoreNote(kind,dark){var w=el('div');var st=w.style;st.fontSize='12px';st.lineHeight='1.5';st.margin='6px 0 0';st.color=dark?'#cbd5e1':'#64748b';
 w.appendChild(document.createTextNode('※ 공개 자료를 규칙으로 계산한 참고 지표이며 기업 평가점수가 아니에요 '));var b=el('button',null,'ⓘ 자세히');var s=b.style;s.border='1px solid '+(dark?'#94a3b8':'#cbd5e1');s.background='transparent';s.color=dark?'#e2e8f0':'#334155';s.borderRadius='999px';s.padding='1px 9px';s.fontSize='11.5px';s.cursor='pointer';b.setAttribute('data-noconfirm','1');b.onclick=function(){scoreOpen(kind)};w.appendChild(b);return w}
window.ScoreInfo={open:scoreOpen,note:scoreNote};
// 종목 클릭 → 종목분석·심층분석 중 고르는 작은 팝업. data-tk="종목코드"(선택: data-nm="종목명") 가 붙은 요소를 누르면 뜬다.
// 네이버 증권 이동은 팝업이 아니라 종목 옆 작은 아이콘(NvIcon) 으로 따로 둔다.
var SPN=null;
function spCss(){if(document.getElementById('skPopCss'))return;var nn='',n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';
 var s=document.createElement('style');s.id='skPopCss';if(nn)s.setAttribute('nonce',nn);
 s.textContent='.tkl{cursor:pointer;text-decoration:underline;text-decoration-color:#cbd5e1;text-underline-offset:3px}.tkl:hover{text-decoration-color:currentColor}'+
 '.skPop{position:fixed;z-index:2147483000;background:#fff;color:#0f172a;border:1px solid #cbd5e1;border-radius:14px;box-shadow:0 14px 40px rgba(15,23,42,.30);padding:10px;width:244px;font:14px/1.5 system-ui,-apple-system,"Malgun Gothic",sans-serif}'+
 '.skPop .hd{display:flex;align-items:center;gap:6px;margin:0 0 8px}.skPop .hd b{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.skPop .hd i{font-style:normal;font-size:11.5px;color:#94a3b8}'+
 '.skPop .x{border:0;background:#f1f5f9;color:#475569;border-radius:8px;width:26px;height:26px;cursor:pointer;font-size:13px}'+
 '.skPop button.go{display:flex;align-items:center;gap:9px;width:100%;text-align:left;border:1.5px solid #e2e8f0;background:#fff;color:#0f172a;border-radius:11px;padding:9px 11px;margin:5px 0 0;font:inherit;font-size:14px;font-weight:800;cursor:pointer}'+
 '.skPop button.go:hover,.skPop button.go:focus{border-color:#2563eb;background:#eff6ff;outline:0}.skPop button.go small{display:block;font-weight:500;font-size:11.5px;color:#64748b}'+
 '@media(max-width:520px){.skPop{left:0!important;right:0!important;top:auto!important;bottom:0;width:auto;border-radius:16px 16px 0 0;padding:14px 14px calc(14px + env(safe-area-inset-bottom))}.skPop button.go{padding:12px 13px;font-size:15px}}'+
 'a.skNv{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-left:5px;border:1px solid #86efac;background:#f0fdf4;color:#15803d;border-radius:5px;font:700 11px/1 system-ui,sans-serif;text-decoration:none;vertical-align:1px;flex:0 0 auto}a.skNv:hover{background:#16a34a;color:#fff;border-color:#16a34a}';
 document.head.appendChild(s)}
function spClose(){if(SPN){try{SPN.remove()}catch(e){}SPN=null}document.removeEventListener('keydown',spKey,true);document.removeEventListener('mousedown',spOut,true);document.removeEventListener('touchstart',spOut,true)}
function spKey(e){if(e.key==='Escape')spClose()}
function spOut(e){if(SPN&&!SPN.contains(e.target))spClose()}
/* [v187] 종목 이동은 어디서든 '같은 창' — 메인 화면 탭(MiniTabs)이 있으면 그 탭으로, 없으면(관리자 화면·단독 메뉴 화면) 현재 창을 종목분석으로 바꿔요(새 창을 따로 띄우지 않아요). */
window.GoStock=function(t,kind){t=String(t||'').trim().toUpperCase();if(!t)return false;
 var cands=[];try{if(window.parent&&window.parent!==window)cands.push(window.parent)}catch(e){}try{if(window.top&&window.top!==window&&cands.indexOf(window.top)<0)cands.push(window.top)}catch(e){}
 for(var i=0;i<cands.length;i++){try{var P=cands[i];if(P.MiniTabs){if(kind==='deep'&&P.MiniTabs.openDeep){P.MiniTabs.openDeep(t);return true}if(kind==='stock'&&P.MiniTabs.openStock){P.MiniTabs.openStock(t,true);return true}if(!kind&&P.MiniTabs.openStock){P.MiniTabs.openStock(t);return true}}}catch(e){}}
 var url='/?t='+encodeURIComponent(t)+(kind==='deep'?'&m=deep':'');
 try{if(window.MiniTabs&&window.MiniTabs.openStock&&window.top===window){if(kind==='deep'&&window.MiniTabs.openDeep){window.MiniTabs.openDeep(t);return true}window.MiniTabs.openStock(t,kind==='stock');return true}}catch(e){}
 try{if(window.top&&window.top!==window){window.top.location.href=url;return true}}catch(e){}
 location.href=url;return true};
window.GoMain=function(){try{if(window.top&&window.top!==window){window.top.location.href='/';return true}}catch(e){}location.href='/';return true};
window.StockPop=function(t,name,anchor){t=String(t||'').trim().toUpperCase();if(!t)return false;spClose();spCss();
 var bx=el('div','skPop');bx.setAttribute('role','dialog');bx.setAttribute('aria-label','종목 이동 선택');SPN=bx;
 var hd=el('div','hd');hd.appendChild(el('b',null,name||t));hd.appendChild(el('i',null,t));var x=el('button','x','✕');x.type='button';x.setAttribute('aria-label','닫기');x.setAttribute('data-noconfirm','1');x.onclick=spClose;hd.appendChild(x);bx.appendChild(hd);
 function go(ic,lb,sub,kind){var b=el('button','go');b.type='button';b.setAttribute('data-noconfirm','1');b.appendChild(el('span',null,ic));var d=el('span');d.appendChild(document.createTextNode(lb));d.appendChild(el('small',null,sub));b.appendChild(d);b.onclick=function(){spClose();window.GoStock(t,kind)};bx.appendChild(b);return b}
 var b1=go('📈','종목분석','가격·지표·체력지표 한눈에','stock');go('🔎','심층분석','재무·공시·뉴스·AI 분석','deep');
 document.body.appendChild(bx);
 if(window.innerWidth>520){var r=anchor&&anchor.getBoundingClientRect?anchor.getBoundingClientRect():{left:window.innerWidth/2-122,bottom:window.innerHeight/3,top:window.innerHeight/3};
  var w=bx.offsetWidth||244,h=bx.offsetHeight||150,l=Math.max(8,Math.min(r.left,window.innerWidth-w-8)),tp=r.bottom+6;if(tp+h>window.innerHeight-8)tp=Math.max(8,r.top-h-6);bx.style.left=l+'px';bx.style.top=tp+'px'}
 document.addEventListener('keydown',spKey,true);setTimeout(function(){document.addEventListener('mousedown',spOut,true);document.addEventListener('touchstart',spOut,true)},0);try{b1.focus({preventScroll:true})}catch(e){}return true};
window.NvIcon=function(t){spCss();t=String(t||'').trim().toUpperCase();var a=el('a','skNv','↗');a.href='https://finance.naver.com/item/main.naver?code='+encodeURIComponent(t);a.target='_blank';a.rel='noopener';a.title='네이버 증권에서 보기(새 창)';a.setAttribute('aria-label','네이버 증권에서 보기');a.setAttribute('data-noconfirm','1');
 a.addEventListener('click',function(e){e.stopPropagation()});return a};
// 종목 이름 + (눌러서 분석 메뉴 고르기) + 네이버 아이콘 한 묶음
window.StockName=function(t,name,opt){spCss();opt=opt||{};var w=el('span','skNm');var n=el('span','tkl nm',name||t);n.setAttribute('data-nv','1');n.setAttribute('data-tk',t);n.setAttribute('data-nm',name||'');n.title='눌러서 종목분석·심층분석 고르기';n.tabIndex=0;n.setAttribute('role','button');
 n.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();window.StockPop(t,name,n)}});w.appendChild(n);if(opt.naver!==false)w.appendChild(window.NvIcon(t));return w};
document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('[data-tk]'):null;if(!a)return;var t=a.getAttribute('data-tk');if(!t)return;
 if(e.ctrlKey||e.metaKey||e.shiftKey||e.button===1)return;e.preventDefault();e.stopPropagation();
 var nm=a.getAttribute('data-nm')||(a.textContent||'').replace(/\s+/g,' ').replace(/\s*\(\s*[0-9A-Za-z]{6}\s*\)\s*$/,'').trim().slice(0,24);if(nm===t)nm='';window.StockPop(t,nm,a)},true);
// 종목 이름 표시(.tkl[data-tk]) 옆에 네이버 증권 아이콘을 자동으로 붙인다(메뉴마다 따로 만들지 않아도 되게). 표 칸·너무 긴 글·이미 붙은 곳은 건너뛴다.
var NVOK={SPAN:1,A:1,B:1,STRONG:1,EM:1,I:1,LABEL:1,H3:0};
function nvScan(){try{var l=document.querySelectorAll('.tkl[data-tk]:not([data-nv])');for(var i=0;i<l.length;i++){var n=l[i];n.setAttribute('data-nv','1');var t=(n.getAttribute('data-tk')||'').trim();
 if(!/^[0-9A-Za-z]{6}$/.test(t)||!NVOK[n.tagName]||!n.parentNode)continue;if(n.closest('a.skNv,.skNm,button,[data-nonv]'))continue;if((n.textContent||'').length>40)continue;
 var nx=n.nextSibling;if(nx&&nx.nodeType===1&&nx.className==='skNv')continue;n.parentNode.insertBefore(window.NvIcon(t),n.nextSibling)}}catch(e){}}
var nvT=0;function nvLater(){if(nvT)return;nvT=setTimeout(function(){nvT=0;nvScan()},60)}
function nvInit(){nvScan();try{new MutationObserver(nvLater).observe(document.body,{childList:true,subtree:true})}catch(e){}}
if(document.body)nvInit();else document.addEventListener('DOMContentLoaded',nvInit);
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
    foot = (f'<div class="mu-foot">{esc(DISCLAIMER) if disclaimer else ""}<br><a href="/">종목분석</a> · <a href="/menus">전체 메뉴</a> · <a href="/plans">등급 안내</a> · '
            f'<a href="/privacy">개인정보처리방침</a></div>')
    nav = ('<nav class="mu-nav" id="muNav"><a href="/">종목분석</a><a href="/menus"' + (' class="on"' if active == "menus" else "") + '>전체 메뉴</a></nav>')
    nav_js = ("fetch('/api/menus',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){var n=document.getElementById('muNav');"
              "var gl={};(j.groups||[]).forEach(function(g){gl[g.id]=g});var cg=null,bx=null,dd=null;"
              "function closeAll(x){[].forEach.call(n.querySelectorAll('.mu-g.open'),function(o){if(o!==x)o.classList.remove('open')})}"
              "document.addEventListener('click',function(e){if(!e.target.closest||!e.target.closest('.mu-g'))closeAll()});document.addEventListener('keydown',function(e){if(e.key==='Escape')closeAll()});"
              "(j.menus||[]).forEach(function(m){var a=document.createElement('a');a.href=m.path;a.textContent=m.icon+' '+m.label;"
              f"var isOn=m.id==={_js_str(active)};if(isOn)a.className='on';"
              "var gid=m.group||'etc';if(gid!==cg){cg=gid;bx=document.createElement('span');bx.className='mu-g';var g=gl[gid];"
              "if(gid==='main'||!g){dd=bx}else{var gb=document.createElement('button');gb.type='button';gb.className='mu-gb';var lb=document.createElement('b');lb.textContent=g.icon+' '+g.label;gb.appendChild(lb);var cr=document.createElement('em');cr.textContent='▾';gb.appendChild(cr);"
              "dd=document.createElement('div');dd.className='mu-dd';bx.appendChild(gb);bx.appendChild(dd);(function(B,G,L){G.onclick=function(e){e.stopPropagation();var was=B.classList.contains('open');closeAll(B);B.classList.toggle('open',!was);B.classList.remove('r');if(!was){var r=B.querySelector('.mu-dd').getBoundingClientRect();if(r.right>window.innerWidth-8)B.classList.add('r')}}})(bx,gb,lb);bx._lb=lb;bx._base=g.icon+' '+g.label}n.appendChild(bx)}"
              "dd.appendChild(a);if(isOn&&bx._lb){bx.classList.add('on');bx._lb.textContent=bx._base+' · '+m.label}});"
              f"var on=n.querySelector('a.on');if(on&&n.scrollTo){{n.scrollTo({{left:Math.max(0,on.offsetLeft-(n.clientWidth-on.offsetWidth)/2),behavior:'smooth'}})}}}}).catch(function(){{}});")
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


# ───────────────────────── AI 도우미(브라우저 사용자 스크립트) ─────────────────────────
# Tampermonkey 같은 확장에 설치하는 .user.js. 설치하면 [AI 열기]가 입력·전송·답변 복사·탭 닫기까지 자동이 된다(없어도 기존 방식 그대로).
HELPER_JS = r"""// ==UserScript==
// @name         종목분석 미니 · AI 도우미
// @namespace    __ORIGIN__
// @version      1.5.11
// @updateURL    __ORIGIN__/assets/mini-ai-helper.user.js
// @downloadURL  __ORIGIN__/assets/mini-ai-helper.user.js
// @description  종목분석 미니에서 [AI 열기]를 누르면 AI 사이트에서 프롬프트 입력 → 전송 → 답변 복사 → 탭 닫기까지 자동으로 해 주고, 블로그 글쓰기 화면이 열리면 제목·상단 이미지·본문을 자동으로 넣어 줍니다(발행은 직접).
// @match        __ORIGIN__/*
// @match        https://gemini.google.com/*
// @match        https://chatgpt.com/*
// @match        https://claude.ai/*
// @match        https://www.perplexity.ai/*
// @match        https://blog.naver.com/*
// @match        https://*.blog.naver.com/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_addValueChangeListener
// @grant        GM_setClipboard
// @grant        GM_openInTab
// @grant        unsafeWindow
// @grant        window.close
// @run-at       document-start
// ==/UserScript==
/* 종목분석 미니 AI 도우미 v1.5.11
 * · 종목분석 미니 화면에서 보낸 작업(프롬프트)만 처리합니다. 다른 경로로 열린 AI 화면은 건드리지 않아요.
 * · 이 스크립트는 사용자의 브라우저 안에서만 동작하며, 로그인 정보·대화 내용을 어디로도 보내지 않습니다.
 * · AI 사이트 화면이 개편되면 자동 진행이 멈출 수 있어요. 그때는 프롬프트가 복사돼 있으니 직접 붙여넣으면 됩니다. */
(function () {
  'use strict';
  var ORIGIN = '__ORIGIN__', VER = '1.5.11';
  function gget(k) { try { return Promise.resolve(GM_getValue(k, null)); } catch (e) { return Promise.resolve(null); } }
  function gset(k, v) { try { return Promise.resolve(GM_setValue(k, v)); } catch (e) { return Promise.resolve(); } }
  function gdel(k) { try { return Promise.resolve(GM_deleteValue(k)); } catch (e) { return Promise.resolve(); } }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* ───────── 1) 종목분석 미니 화면 쪽: 작업을 받아 저장하고, 결과를 화면에 전달 ───────── */
  if (location.origin === ORIGIN) {
    if (window.top !== window) return;   /* 메뉴 탭(iframe)에는 붙지 않아요 — 바깥 화면만 */
    var marked = false, mark = function () { try { document.documentElement.setAttribute('data-mini-helper', VER); marked = true; } catch (e) {} };
    mark(); document.addEventListener('DOMContentLoaded', mark);
    if (!marked) { var mt = setInterval(function () { mark(); if (marked) clearInterval(mt); }, 20); }
    /* v1.5.1: 작업 전달 통로를 2개 둬요(postMessage + 화면에 잠깐 붙는 숨은 요소). Tampermonkey 는 보호된 실행 환경 때문에
       e.source === window 비교가 거짓이 되는 경우가 있어서, 그 비교는 하지 않고 '같은 사이트(origin)에서 온 것'만 확인해요. */
    var handled = {}, opened = {};
    function once(kind, id) { var k = kind + ':' + id, n = Date.now(); if (handled[k] && n - handled[k] < 10000) return false; handled[k] = n; return true; }
    function say(id, msg) { try { window.postMessage({ miniHelper: 'status', id: String(id), msg: msg, ack: 1 }, ORIGIN); } catch (e) {} }
    function onJob(d) {
      if (!d || !d.id) return;
      if (d.miniHelper === 'blogjob' && d.html) {   /* 블로그 글쓰기 화면에 넣을 내용(제목·상단 이미지·본문) */
        if (!once('b', d.id)) return;
        var il = (Array.isArray(d.imgs) ? d.imgs : []).filter(function (x) { return typeof x === 'string' && x.indexOf('data:image/') === 0; }).slice(0, 10); if (!il.length && d.img) il = [String(d.img)];
        gset('blogjob', { id: String(d.id), title: String(d.title || ''), html: String(d.html), img: String(d.img || ''), imgs: il, ts: Date.now() });
        try {   /* 블로그 글쓰기 탭도 도우미가 직접 열어요(팝업 차단 없음). 네이버 블로그 주소만 허용 */
          var bu = String(d.open || '');
          if (bu && /^https:\/\/([a-z0-9-]+\.)?blog\.naver\.com\//.test(bu)) GM_openInTab(bu, { active: true, insert: true, setParent: true });
        } catch (e) {}
        return;
      }
      if (d.miniHelper !== 'job' || !d.prompt) return;
      if (!once('j', d.id)) return;
      gdel('result'); gdel('status');
      gset('job', { id: String(d.id), prompt: String(d.prompt), host: String(d.host || ''), ts: Date.now() });
      say(d.id, '도우미가 작업을 받았어요 — AI 탭을 여는 중…');
      /* 클릭 없이(자동 진행 중에도) AI 탭을 직접 열어요 — 브라우저 팝업 차단을 받지 않아요. 주소는 AI 사이트(https)만 허용 */
      try {
        var ou = String(d.open || '');
        if (ou && /^https:\/\/(gemini\.google\.com|chatgpt\.com|claude\.ai|www\.perplexity\.ai)\//.test(ou)) {
          var tb = GM_openInTab(ou, { active: true, insert: true, setParent: true });
          if (tb) opened[String(d.id)] = tb;   /* 답변이 오면 이 손잡이로 AI 탭을 닫아요(AI 탭 스스로 닫기가 막힌 브라우저에서도 닫혀요) */
        }
      } catch (e) { say(d.id, '도우미가 탭을 열지 못했어요(' + (e && e.message || e) + ')'); }
    }
    window.addEventListener('message', function (e) {
      if (e.origin !== ORIGIN) return;
      onJob(e.data);
    });
    try {
      var take = function (n) {
        if (!n || n.nodeType !== 1 || !n.getAttribute || !n.hasAttribute('data-mini-bridge')) return;
        try { var d = JSON.parse(n.textContent || '{}'); d.miniHelper = n.getAttribute('data-mini-bridge'); onJob(d); } catch (e) {}
      };
      var mo = new MutationObserver(function (ms) { ms.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, take); }); });
      var startObs = function () { if (!document.documentElement) { setTimeout(startObs, 10); return; } mo.observe(document.documentElement, { childList: true }); };
      startObs();
    } catch (e) {}
    try {
      GM_addValueChangeListener('result', function (n, o, v, remote) {
        if (!remote || !v) return;
        window.postMessage({ miniHelper: 'result', id: v.id, text: v.text || '', error: v.error || '' }, ORIGIN);
        if (!v.error) {   /* 답변을 받았으면 우리가 연 AI 탭을 닫아요 */
          var tb = opened[String(v.id)];
          if (tb) setTimeout(function () { try { tb.close(); } catch (e) {} delete opened[String(v.id)]; }, 1500);
        }
      });
      GM_addValueChangeListener('status', function (n, o, v, remote) {
        if (!remote || !v) return;
        window.postMessage({ miniHelper: 'status', id: v.id, msg: v.msg || '' }, ORIGIN);
      });
    } catch (e) {}
    return;
  }


  /* ───────── 1-2) 네이버 블로그 글쓰기 화면: 제목·상단 이미지·본문 자동 입력(발행은 직접) ───────── */
  if (/(^|\.)blog\.naver\.com$/.test(location.hostname)) {
    (function naverBlog() {
      var bn = null;
      function banner(t, kind, btns) {
        try {
          if (!bn) {
            bn = document.createElement('div');
            var st = bn.style; st.position = 'fixed'; st.left = '50%'; st.top = '10px'; st.transform = 'translateX(-50%)'; st.zIndex = '2147483647'; st.maxWidth = '92vw';
            st.font = '600 13px/1.5 system-ui,sans-serif'; st.padding = '9px 14px'; st.borderRadius = '12px'; st.boxShadow = '0 6px 22px rgba(0,0,0,.25)'; st.color = '#fff';
            (document.body || document.documentElement).appendChild(bn);
          }
          bn.style.background = kind === 'bad' ? '#b91c1c' : (kind === 'ok' ? '#15803d' : (kind === 'warn' ? '#b45309' : '#1e3a8a'));
          bn.textContent = '🤖 종목분석 미니 도우미 · ' + t;
          if (btns && !btns.length) btns = [btns];
          (btns || []).forEach(function (btn) { var b = document.createElement('button'); b.textContent = btn.label; b.style.marginLeft = '10px'; b.style.cursor = 'pointer'; b.onclick = btn.fn; bn.appendChild(b); });
        } catch (e) {}
      }
      /* 화면이 바뀌어 안 맞으면 여기 선택자만 고치면 돼요 */
      var SEL = {
        root: ['.se-main-container', '.se-content', '#SE-editor', '.se-canvas'],
        title: ['.se-documentTitle .se-text-paragraph', '.se-section-documentTitle .se-text-paragraph', '.se-title-text .se-text-paragraph', '.se-title-text'],
        bodyP: ['.se-component.se-text:not(.se-documentTitle) .se-text-paragraph', '.se-section-text .se-text-paragraph', '.se-main-container .se-text-paragraph'],
        image: ['.se-component.se-image', '.se-module-image', '.se-image-resource']
      };
      function q1(list, root) { for (var i = 0; i < list.length; i++) { try { var e = (root || document).querySelector(list[i]); if (e) return e; } catch (x) {} } return null; }
      function qa(list, root) { for (var i = 0; i < list.length; i++) { try { var a = (root || document).querySelectorAll(list[i]); if (a && a.length) return Array.prototype.slice.call(a); } catch (x) {} } return []; }
      function inTitle(p) { return !!(p.closest && p.closest('.se-documentTitle,.se-section-documentTitle,.se-title-text')); }
      function bodyParas() { return qa(SEL.bodyP).filter(function (p) { return !inTitle(p); }); }
      function bodyLen() { var r = q1(SEL.root); return r ? (r.innerText || '').replace(/\s+/g, '').length : 0; }
      function imgCount() { return qa(SEL.image).length; }
      function caretTo(node) {
        try {
          var host = node.closest('[contenteditable="true"]') || node;
          if (host.focus) host.focus();
          var t = node.querySelector('span') || node, r = document.createRange(), s = window.getSelection();
          r.selectNodeContents(t); r.collapse(false); s.removeAllRanges(); s.addRange(r);
          return true;
        } catch (e) { return false; }
      }
      function pasteInto(node, data) {   /* 사람이 Ctrl+V 한 것과 같은 '붙여넣기' 신호를 편집기에 보낸다 */
        var dt = new DataTransfer();
        if (data.html) dt.setData('text/html', data.html);
        if (data.text) dt.setData('text/plain', data.text);
        if (data.file) dt.items.add(data.file);
        var tgt = document.activeElement && document.activeElement !== document.body ? document.activeElement : node;
        var ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
        return tgt.dispatchEvent(ev);
      }
      function dataUrlToFile(u, name) {
        try {
          var m = /^data:([^;]+);base64,(.*)$/.exec(u); if (!m) return null;
          var bin = atob(m[2]), a = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
          return new File([a], name + (m[1].indexOf('jpeg') >= 0 ? '.jpg' : '.png'), { type: m[1] });
        } catch (e) { return null; }
      }
      function dismissPopups() {
        try {
          var pops = document.querySelectorAll('.se-popup, .se-popup-container, [class*="popup"]');
          Array.prototype.forEach.call(pops, function (p) {
            var tx = p.innerText || '';
            if (/작성 중인 글|이어서 작성|임시 저장된 글/.test(tx)) {
              var btns = p.querySelectorAll('button');
              for (var i = 0; i < btns.length; i++) if (/^\s*취소\s*$/.test(btns[i].textContent)) { btns[i].click(); break; }
            }
          });
          var hp = document.querySelector('.se-help-panel-close-button, button[class*="help-panel-close"]'); if (hp) hp.click();
        } catch (e) {}
      }
      var REPORT = '';
      function diag() {   /* 안 맞을 때: 편집기 구조를 복사해 보내 주면 선택자를 고칠 수 있어요 */
        var out = [];
        Array.prototype.forEach.call(document.querySelectorAll('[class*="se-"]'), function (n, i) { if (i < 160) out.push((n.tagName + '.' + String(n.className).replace(/\s+/g, '.')).slice(0, 110) + (n.getAttribute('contenteditable') ? ' [ce=' + n.getAttribute('contenteditable') + ']' : '')); });
        var t = 'URL ' + location.href + '\n자동 시도 결과: ' + (REPORT || '(없음)') + '\n' + out.join('\n');
        try { GM_setClipboard(t, 'text'); } catch (e) { try { navigator.clipboard.writeText(t); } catch (e2) {} }
        banner('편집기 구조를 복사했어요. 채팅에 붙여넣어 보내 주세요.', 'ok');
      }
      async function waitFn(fn, ms) { var t0 = Date.now(); while (Date.now() - t0 < ms) { var v = null; try { v = fn(); } catch (e) {} if (v) return v; await sleep(500); } return null; }

      function imgCount2() { var n = imgCount(), r = q1(SEL.root), m = 0; try { m = r ? r.querySelectorAll('img').length : 0; } catch (e) {} return Math.max(n, m); }
      function toPng(u) {   /* 클립보드에는 PNG 이미지만 안전하게 들어가요 */
        return new Promise(function (res) {
          try { var im = new Image(); im.onload = function () { try { var c = document.createElement('canvas'); c.width = im.naturalWidth; c.height = im.naturalHeight; c.getContext('2d').drawImage(im, 0, 0); c.toBlob(function (b) { res(b); }, 'image/png'); } catch (e) { res(null); } }; im.onerror = function () { res(null); }; im.src = u; } catch (e) { res(null); }
        });
      }
      function clipText(t) { try { GM_setClipboard(t, 'text'); return Promise.resolve(true); } catch (e) {} try { return navigator.clipboard.writeText(t).then(function () { return true; }, function () { return false; }); } catch (e2) { return Promise.resolve(false); } }
      function clipHtml(h, t) {
        try { return navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([h], { type: 'text/html' }), 'text/plain': new Blob([t], { type: 'text/plain' }) })]).then(function () { return true; }, function () { try { GM_setClipboard(h, 'html'); return true; } catch (e) { return clipText(t); } }); }
        catch (e) { try { GM_setClipboard(h, 'html'); return Promise.resolve(true); } catch (e2) { return clipText(t); } }
      }
      function clipImage(u) { return toPng(u).then(function (b) { if (!b) return false; try { return navigator.clipboard.write([new ClipboardItem({ 'image/png': b })]).then(function () { return true; }, function () { return false; }); } catch (e) { return false; } }); }

      async function run() {
        /* 이 칸(프레임)에 편집기가 있을 때만 일을 가져온다 */
        var ready = await waitFn(function () { return q1(SEL.root) && q1(SEL.title) && bodyParas().length ? true : null; }, 45000);
        if (!ready) return;
        var job = await gget('blogjob');
        if (!job || Date.now() - job.ts > 180000) return;
        await gdel('blogjob');
        var plain = (function () { var d = document.createElement('div'); d.innerHTML = job.html; return (d.innerText || d.textContent || '').trim(); })();
        function titleOk() { var tp = q1(SEL.title); return !!(tp && job.title && (tp.innerText || '').indexOf(job.title.slice(0, Math.min(8, job.title.length))) >= 0); }
        banner('글쓰기 화면을 확인하는 중…');
        await sleep(2500); dismissPopups(); await sleep(600); dismissPopups(); await sleep(400);
        var todo = [], abort = false, REP = [], done = {};
        var SKIPB = { label: '⏭ 자동 시도 건너뛰고 직접 붙여넣기', fn: function () { abort = true; } };
        /* ── 1단계: 자동 입력 시도 — 편집기가 받아 주는 방법을 차례로 찾아요(한 번 통한 방법은 기억해 다음에 먼저 써요) ── */
        var uw = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;
        function fire(el, type, C, init) { try { return el.dispatchEvent(new C(type, Object.assign({ bubbles: true, cancelable: true, composed: true }, init || {}))); } catch (e) { return null; } }
        function realClick(el) {   /* 사람이 칸을 누른 것과 같은 마우스 신호 → 편집기가 '여기에 커서가 있다'고 인식하게 */
          try { var r = el.getBoundingClientRect(), o = { clientX: r.left + Math.min(r.width / 2, 60), clientY: r.top + r.height / 2, button: 0, buttons: 1 };
            fire(el, 'pointerdown', PointerEvent, o); fire(el, 'mousedown', MouseEvent, o); try { (el.closest('[contenteditable="true"]') || el).focus(); } catch (e) {}
            o.buttons = 0; fire(el, 'pointerup', PointerEvent, o); fire(el, 'mouseup', MouseEvent, o); fire(el, 'click', MouseEvent, o); } catch (e) {}
        }
        function mkDT(d) { var dt = new DataTransfer(); try { if (d.html) dt.setData('text/html', d.html); if (d.text) dt.setData('text/plain', d.text); if (d.file) dt.items.add(d.file); } catch (e) {} return dt; }
        function dropOn(el, d) { var dt = mkDT(d), r = el.getBoundingClientRect(), o = { dataTransfer: dt, clientX: r.left + 20, clientY: r.top + 10 }; ['dragenter', 'dragover', 'drop'].forEach(function (t) { fire(el, t, DragEvent, o); }); }
        function inputType(el, type, data, d) { try { var init = { inputType: type, bubbles: true, cancelable: true, composed: true }; if (data != null) init.data = data; if (d) init.dataTransfer = mkDT(d); var ev = new InputEvent('beforeinput', init); el.dispatchEvent(ev); return ev.defaultPrevented; } catch (e) { return false; } }
        function host(n) { return (n.closest && n.closest('[contenteditable="true"]')) || n; }
        var IMG = {   /* 이미지 넣는 방법들 */
          drop_file: function (n, f) { realClick(n); dropOn(host(n), { file: f }); },
          paste_file: function (n, f) { realClick(n); caretTo(n); pasteInto(n, { file: f }); },
          paste_inputtype: function (n, f) { realClick(n); caretTo(n); inputType(host(n), 'insertFromPaste', null, { file: f }); },
          fileinput: function (n, f) {   /* 사진 버튼이 만드는 '파일 선택' 칸에 파일을 직접 꽂아요(창은 안 뜸) */
            realClick(n);
            var put = function (inp) { try { var dt = new DataTransfer(); dt.items.add(f); inp.files = dt.files; fire(inp, 'input', Event); fire(inp, 'change', Event); return true; } catch (e) { return false; } };
            var ex = Array.prototype.slice.call(document.querySelectorAll('input[type="file"]')).filter(function (i) { return !i.accept || /image/.test(i.accept); })[0];
            if (ex) { put(ex); return; }
            var proto = uw.HTMLInputElement.prototype, orig = proto.click, used = false;
            proto.click = function () { if (this.type === 'file' && !used) { used = true; put(this); return; } return orig.apply(this, arguments); };
            setTimeout(function () { proto.click = orig; }, 6000);
            var btn = document.querySelector('.se-image-toolbar-button, button[data-name="image"], button[class*="image-toolbar"]');
            if (btn) { fire(btn, 'mousedown', MouseEvent); fire(btn, 'mouseup', MouseEvent); try { btn.click(); } catch (e) {} }
          }
        };
        var lastKeys = {};
        async function tryList(label, defs, args, verify, waitMs, settleMs) {
          var keys = Object.keys(defs), memo = await gget('st_' + label);
          if (memo && defs[memo]) keys = [memo].concat(keys.filter(function (k) { return k !== memo; }));
          for (var i = 0; i < keys.length && !abort; i++) {
            banner(label + (args.tag || '') + ' 넣는 중… (방법 ' + (i + 1) + '/' + keys.length + ')', null, [SKIPB]);
            var before = args.base ? args.base() : null;
            try { defs[keys[i]].apply(null, args.get()); } catch (e) {}
            var ok = !!(await waitFn(function () { return verify(before) ? true : null; }, waitMs));
            REP.push(label + ':' + keys[i] + (ok ? '✓' : '✗'));
            if (ok) { lastKeys[label] = keys[i]; gset('st_' + label, keys[i]); if (settleMs) await sleep(settleMs); return true; }
          }
          return false;
        }
        REPORT = '';
        try {
          var IL = (job.imgs && job.imgs.length) ? job.imgs : (job.img ? [job.img] : []);
          done.total = IL.length; done.n = 0;
          for (var ii = 0; ii < IL.length && !abort; ii++) {   /* [v1.5.11] 그림을 한 장이 아니라 모두, 순서대로 올려요 */
            var fimg = dataUrlToFile(IL[ii], 'img' + (ii + 1));
            if (!fimg) continue;
            var tgtIdx = ii;
            var okI = await tryList('이미지', IMG, { tag: IL.length > 1 ? ' ' + (ii + 1) + '/' + IL.length : '', get: function () { var ps = bodyParas(); return [tgtIdx === 0 ? ps[0] : ps[ps.length - 1], fimg]; }, base: function () { return imgCount2(); } }, function (n0) { return imgCount2() > n0; }, 5000, 2500);
            if (okI) done.n++; else break;
          }
          if (done.total && done.n >= done.total) done.img = 1;
        } catch (e) { REP.push('오류:' + String((e && e.message) || e).slice(0, 60)); }
        REPORT = REP.join(' ');
        /* ── 2단계: 본문·제목은 사람이 Ctrl+V — 도우미는 '복사'만 도와요(네이버 편집기는 가짜 입력을 거부하거나 모양을 깨요) ──
           사이트에서 [복사하고 블로그 열기]를 누르면 이미 '제목 포함 본문'이 서식 그대로 클립보드에 있어요. 도우미는 클립보드를 건드리지 않고,
           버튼을 눌렀을 때만(사람이 누른 순간에만) 다시 복사해요. */
        var hasImg = !!(job.img || (job.imgs && job.imgs.length)), imgOk = !hasImg || !!done.img, n0 = imgCount2();
        function bodyOnly() { var t = 0; bodyParas().forEach(function (p) { t += (p.innerText || '').replace(/[\s​]+/g, '').length; }); return t; }
        var b0 = bodyOnly(), plainLen = plain.replace(/\s+/g, '').length;
        function titleHas() { var tp = q1(SEL.title); if (!tp || tp.querySelector('.se-placeholder')) return false; return (tp.innerText || '').replace(/[\s​]+/g, '').length > 0; }
        function bodyHas() { return bodyOnly() > b0 + Math.min(60, plainLen * 0.3); }
        function imgNow() { return imgOk || (!(done.total > 1) && imgCount2() > n0); }
        function copyRich(h, t) {   /* 사이트와 같은 방식: copy 이벤트에 text/html + text/plain 을 실어요(표·서식 유지) */
          var ok = false;
          try {
            var ta = document.createElement('textarea'); ta.value = ' '; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
            (document.body || document.documentElement).appendChild(ta); ta.focus(); ta.select();
            var got = false, hnd = function (e) { try { e.clipboardData.setData('text/html', h); e.clipboardData.setData('text/plain', t); e.preventDefault(); got = true; } catch (x) {} };
            document.addEventListener('copy', hnd, true); var r = false; try { r = document.execCommand('copy'); } catch (x) {}
            document.removeEventListener('copy', hnd, true); ta.parentNode.removeChild(ta); ok = !!(r && got);
          } catch (e) {}
          if (!ok) { try { clipHtml(h, t); ok = true; } catch (e) {} }
          return ok;
        }
        var note = '', lastSig = '', tStart = Date.now(), timer = null;
        function setNote(t) { note = t; draw(true); }
        function draw(force) {
          var im = imgNow(), bd = bodyHas(), tt = titleHas(), sig = [im, bd, tt, note].join('|');
          if (!force && sig === lastSig) return; lastSig = sig;
          var parts = [];
          if (hasImg) parts.push(im ? (done.total > 1 ? '✅ 이미지 ' + done.n + '/' + done.total + '장' : '✅ 상단 이미지') : (done.total > 1 && done.n ? '⚠ 이미지 ' + done.n + '/' + done.total + '장만 들어갔어요(나머지는 [🖼 이미지 복사] 후 Ctrl+V)' : null) ||  '⚠ 상단 이미지는 자동으로 안 들어갔어요([🖼 이미지 복사] → 본문 첫 줄 클릭 → Ctrl+V, 필요 없으면 무시)');
          parts.push(bd ? '✅ 본문' : '📝 본문: 이미지 아래 빈 줄을 클릭하고 Ctrl+V (제목 포함 본문이 복사돼 있어요)');
          parts.push(tt ? '✅ 제목' : '📝 제목: 본문 맨 위 제목 줄을 제목 칸으로 옮기거나 [📋 제목만 복사] 후 제목 칸에 Ctrl+V');
          var all = bd && tt && (im || !hasImg);
          if (all) { clearInterval(timer); }
          banner(parts.join(' · ') + (all ? ' — 확인 후 [발행]을 눌러 주세요.' : '') + (note ? ' · ' + note : ''), all ? 'ok' : (im ? null : 'warn'), [
            { label: '📋 본문 다시 복사', fn: function () { setNote(copyRich(job.html, plain) ? '본문(제목 포함)을 복사했어요.' : '복사가 막혔어요 — 사이트에서 [복사하고 블로그 열기]를 다시 눌러 주세요.'); } },
            { label: '📋 제목만 복사', fn: function () { clipText(job.title || '').then(function (ok) { setNote(ok ? '제목을 복사했어요 — 제목 칸에 Ctrl+V 하고, 본문은 [📋 본문 다시 복사]로 다시 복사하세요.' : '복사가 막혔어요.'); }); } }
          ].concat(hasImg && !im ? [{ label: '🖼 이미지 복사', fn: function () { clipImage((job.imgs && job.imgs[done.n]) || job.img).then(function (ok) { setNote(ok ? '이미지를 복사했어요 — 본문 첫 줄에 Ctrl+V 후 [📋 본문 다시 복사].' : '이미지 복사가 막혔어요.'); }); } }] : []).concat([{ label: '🔍 구조 복사', fn: diag }]));
        }
        draw(true);
        timer = setInterval(function () { if (Date.now() - tStart > 1800000) { clearInterval(timer); return; } draw(false); }, 700);
      }
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { run(); }); else run();
    })();
    return;
  }

  /* ───────── 2) AI 사이트 쪽 ───────── */
  if (window.top !== window) return;
  var m = /[#&]miniai=([A-Za-z0-9_-]{6,64})/.exec(location.hash);
  var PL = /[#&]p=([A-Za-z0-9_-]+)/.exec(location.hash);
  function dec(x) { try { x = x.replace(/-/g, '+').replace(/_/g, '/'); while (x.length % 4) x += '='; return decodeURIComponent(escape(atob(x))); } catch (e) { return ''; } }
  var HASHJOB = (m && PL) ? { id: m[1], prompt: dec(PL[1]), host: location.hostname, ts: Date.now() } : null;   /* 주소에 프롬프트를 같이 실어 보내서, 저장소 전달이 안 돼도 진행돼요 */
  if (HASHJOB && HASHJOB.prompt.length < 20) HASHJOB = null;
  var JOB = m ? m[1] : null;   /* 주소 끝(#miniai=…)이 사라진 경우에도 방금 보낸 작업을 찾아 이어가요(findJob) */
  if (m) { try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {} }

  /* 사이트별 화면 위치(선택자). 사이트가 바뀌면 여기만 고치면 됩니다. */
  var PROFILES = {
    'gemini.google.com': {
      name: '제미나이',
      input: ['rich-textarea .ql-editor', 'div.ql-editor[contenteditable="true"]', '[contenteditable="true"][role="textbox"]'],
      send: ['button.send-button', 'button[aria-label*="보내기"]', 'button[aria-label*="Send"]'],
      stop: ['button.send-button.stop', 'button[aria-label*="중지"]', 'button[aria-label*="Stop"]', 'button[aria-label*="응답 중지"]'],
      answer: ['model-response message-content', 'message-content', '.model-response-text']
    },
    'chatgpt.com': {
      name: '챗GPT',
      input: ['#prompt-textarea', 'div[contenteditable="true"]#prompt-textarea', 'textarea[name="prompt-textarea"]'],
      send: ['button[data-testid="send-button"]', 'button[aria-label*="Send"]', 'button[aria-label*="보내기"]'],
      stop: ['button[data-testid="stop-button"]', 'button[aria-label*="Stop"]', 'button[aria-label*="중지"]'],
      answer: ['[data-message-author-role="assistant"] .markdown', '[data-message-author-role="assistant"]']
    },
    'claude.ai': {
      name: '클로드',
      input: ['div.ProseMirror[contenteditable="true"]', '[contenteditable="true"][role="textbox"]', 'fieldset div[contenteditable="true"]'],
      send: ['button[aria-label*="Send"]', 'button[aria-label*="보내기"]', 'button[aria-label*="메시지 보내기"]'],
      stop: ['button[aria-label*="Stop"]', 'button[aria-label*="중지"]', 'button[aria-label*="응답 중지"]'],
      answer: ['.font-claude-response', 'div[class*="font-claude-response"]', '[data-is-streaming]']
    },
    'www.perplexity.ai': {
      name: '퍼플렉시티',
      input: ['#ask-input', 'div[contenteditable="true"][role="textbox"]', 'textarea'],
      send: ['button[aria-label*="Submit"]', 'button[aria-label*="제출"]', 'button[data-testid="submit-button"]'],
      stop: ['button[aria-label*="Stop"]', 'button[aria-label*="중지"]'],
      answer: ['[id^="markdown-content"]', 'div.prose']
    }
    /*__EXTRA_PROFILES__*/
  };
  var P = PROFILES[location.hostname];
  if (!P) return;

  var cancelled = false, bar = null, barMsg = null;
  function pick(list) {
    for (var i = 0; i < list.length; i++) { try { var e = document.querySelector(list[i]); if (e) return e; } catch (x) {} }
    return null;
  }
  function pickAll(list) {
    for (var i = 0; i < list.length; i++) { try { var a = document.querySelectorAll(list[i]); if (a && a.length) return Array.prototype.slice.call(a); } catch (x) {} }
    return [];
  }
  function isVis(e) {
    try { if (!e || !e.getBoundingClientRect) return false; var r = e.getBoundingClientRect(); if (r.width < 20 || r.height < 8) return false; var cs = getComputedStyle(e); return cs.visibility !== 'hidden' && cs.display !== 'none'; } catch (x) { return false; }
  }
  /* 화면에 실제로 보이는 입력창만 고른다(제미나이는 숨은 편집기가 여러 개 있을 수 있어요) */
  function pickVisible(list) {
    for (var i = 0; i < list.length; i++) {
      try { var a = document.querySelectorAll(list[i]); for (var k = 0; k < a.length; k++) if (isVis(a[k])) return a[k]; } catch (x) {}
    }
    return null;
  }
  function disabled(b) { return !b || b.disabled || b.getAttribute('aria-disabled') === 'true'; }
  /* 전송 버튼 찾기(2차): 사이트 화면이 바뀌어 정해 둔 선택자가 안 맞아도, 입력창 근처의 '보내기' 모양 버튼을 글자·aria-label 로 찾는다 */
  function genericSend(inp) {
    var root = inp.closest('form') || inp.parentElement;
    for (var up = 0; up < 7 && root; up++, root = root.parentElement) {
      var bs = root.querySelectorAll('button,[role="button"]');
      var c = Array.prototype.filter.call(bs, function (b) {
        var t = ((b.getAttribute('aria-label') || '') + ' ' + (b.getAttribute('title') || '') + ' ' + (b.getAttribute('mattooltip') || '') + ' ' + (b.getAttribute('data-testid') || '') + ' ' + (b.textContent || '')).trim();
        return /send|submit|보내|전송|제출/i.test(t) && !/stop|중지|취소|cancel|attach|첨부|upload|업로드|mic|음성/i.test(t) && !disabled(b) && b.offsetParent !== null;
      });
      if (c.length) return c[c.length - 1];
    }
    return null;
  }
  function waitFor(fn, ms, what) {
    return new Promise(function (res, rej) {
      var t0 = Date.now();
      (function tick() {
        if (cancelled) return rej(new Error('사용자가 중지했어요'));
        var v = null; try { v = fn(); } catch (e) {}
        if (v) return res(v);
        if (Date.now() - t0 > ms) return rej(new Error(what + '을(를) 찾지 못했어요'));
        setTimeout(tick, 400);
      })();
    });
  }

  /* 화면 위쪽 안내 띠 */
  function banner(msg, kind, action) {
    try {
      if (!bar) {
        bar = document.createElement('div');
        bar.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:2147483647;background:#312e81;color:#fff;font:600 14px/1.5 system-ui,-apple-system,"Malgun Gothic",sans-serif;padding:9px 14px;display:flex;gap:12px;align-items:center;box-shadow:0 4px 18px rgba(0,0,0,.35)';
        barMsg = document.createElement('span'); barMsg.style.flex = '1'; bar.appendChild(barMsg);
        var x = document.createElement('button'); x.textContent = '중지';
        x.style.cssText = 'border:0;border-radius:8px;padding:4px 12px;font:inherit;cursor:pointer;background:#fff;color:#312e81';
        x.onclick = function () { cancelled = true; banner('⏹ 자동 진행을 멈췄어요. 이 탭에서 직접 이어서 쓰세요.', 'bad'); x.remove(); };
        bar.appendChild(x);
        (document.body || document.documentElement).appendChild(bar);
      }
      barMsg.textContent = msg;
      if (bar._act) { try { bar._act.remove(); } catch (e) {} bar._act = null; }
      if (action) {
        var ab = document.createElement('button'); ab.textContent = action.label;
        ab.style.cssText = 'border:0;border-radius:8px;padding:4px 12px;font:inherit;cursor:pointer;background:#fde68a;color:#78350f';
        ab.onclick = function () { try { ab.remove(); } catch (e) {} bar._act = null; action.fn(); };
        bar.insertBefore(ab, bar.lastChild); bar._act = ab;
      }
      bar.style.background = kind === 'bad' ? '#b45309' : (kind === 'ok' ? '#15803d' : '#312e81');
    } catch (e) {}
  }
  function status(msg) { banner('🤖 종목분석 미니 도우미 · ' + msg); gset('status', { id: JOB, msg: msg, ts: Date.now() }); }

  /* 입력창에 프롬프트 넣기 */
  function inputText(el) { return (el.value != null ? el.value : (el.innerText || el.textContent || '')); }
  function clearInput(el) {
    try {
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') { setInput(el, ''); return; }
      el.focus(); var sel = window.getSelection(), r = document.createRange(); r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r);
      try { document.execCommand('delete'); } catch (e) {}
      if (inputText(el).replace(/\s+/g, '').length) { el.innerHTML = '<p><br></p>'; el.dispatchEvent(new Event('input', { bubbles: true })); }
    } catch (e) {}
  }
  /* 직접 DOM 에 넣기 — 화면이 뒤쪽 탭이라 포커스가 없어도 되는 방법(Quill·ProseMirror 는 DOM 변화를 읽어요) */
  function domFill(el, text) {
    el.innerHTML = '';
    text.split('\n').forEach(function (line) {
      var p = document.createElement('p'); if (line) p.textContent = line; else p.appendChild(document.createElement('br')); el.appendChild(p);
    });
    try { el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text })); } catch (e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
  }
  async function fillPrompt(text) {
    var need = text.replace(/\s+/g, '').length * 0.8, last = null;
    for (var k = 0; k < 9; k++) {
      if (cancelled) throw new Error('사용자가 중지했어요');
      var el = pickVisible(P.input) || last;
      if (!el) { await sleep(700); continue; }
      last = el;
      try { window.focus(); } catch (e) {}
      if (k > 0) { clearInput(el); await sleep(300); }
      var mode = k % 3;   /* 0: 붙여넣기식 입력(기본) · 1: 붙여넣기 이벤트 · 2: 직접 DOM */
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || mode === 0) setInput(el, text);
      else if (mode === 1) { try { el.focus(); var dt = new DataTransfer(); dt.setData('text/plain', text); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); } catch (e) {} }
      else domFill(el, text);
      await sleep(800 + k * 150);
      var cur = pickVisible(P.input) || el;
      if (inputText(cur).replace(/\s+/g, '').length >= need) {
        await sleep(600);   /* 화면이 입력을 지워 버리는지 한 번 더 확인 */
        cur = pickVisible(P.input) || cur;
        if (inputText(cur).replace(/\s+/g, '').length >= need) return cur;
      }
      status('입력이 안 들어가서 다시 시도해요… (' + (k + 1) + '/9)');
    }
    throw new Error('입력창에 프롬프트가 들어가지 않았어요');
  }
  function setInput(el, text) {
    el.focus();
    var tag = el.tagName;
    if (tag === 'TEXTAREA' || tag === 'INPUT') {
      var proto = tag === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    var sel = window.getSelection(), r = document.createRange();
    r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r);
    var ok = false;
    try { ok = document.execCommand('insertText', false, text); } catch (e) {}
    if (!ok || inputText(el).replace(/\s+/g, '').length < text.replace(/\s+/g, '').length * 0.9) {
      try {
        var dt = new DataTransfer(); dt.setData('text/plain', text);
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
      } catch (e) {}
    }
  }
  function enter(el) {
    ['keydown', 'keypress', 'keyup'].forEach(function (t) {
      el.dispatchEvent(new KeyboardEvent(t, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
    });
  }

  /* 답변 화면(HTML)을 마크다운 글로 바꾸기 — AI 사이트의 복사 버튼과 비슷한 결과 */
  var SKIP = /^(BUTTON|SVG|STYLE|SCRIPT|NOSCRIPT|MAT-ICON|SOURCE-FOOTNOTE|SOURCES-CAROUSEL|SUP)$/i;
  function inline(n) { var s = ''; for (var c = n.firstChild; c; c = c.nextSibling) s += md(c, 0); return s.replace(/\s+/g, ' ').trim(); }
  function md(n, depth) {
    if (n.nodeType === 3) return n.nodeValue.replace(/\s+/g, ' ');
    if (n.nodeType !== 1) return '';
    var t = n.tagName.toUpperCase();
    if (SKIP.test(t) || (n.className && /sr-only|visually-hidden/.test(String(n.className)))) return '';
    var kids = function (d) { var s = ''; for (var c = n.firstChild; c; c = c.nextSibling) s += md(c, d == null ? depth : d); return s; };
    var h = /^H([1-6])$/.exec(t);
    if (h) return '\n\n' + new Array(+h[1] + 1).join('#') + ' ' + inline(n) + '\n\n';
    switch (t) {
      case 'P': return '\n\n' + kids().trim() + '\n\n';
      case 'BR': return '\n';
      case 'HR': return '\n\n---\n\n';
      case 'STRONG': case 'B': { var s1 = kids().trim(); return s1 ? '**' + s1 + '**' : ''; }
      case 'EM': case 'I': { var s2 = kids().trim(); return s2 ? '*' + s2 + '*' : ''; }
      case 'CODE': return n.parentNode && n.parentNode.tagName === 'PRE' ? n.textContent : '`' + n.textContent + '`';
      case 'PRE': return '\n\n```\n' + n.textContent.replace(/\n+$/, '') + '\n```\n\n';
      case 'BLOCKQUOTE': return '\n\n' + kids().trim().split('\n').map(function (l) { return '> ' + l; }).join('\n') + '\n\n';
      case 'UL': case 'OL': {
        var out = '\n', i = 0, pad = new Array((depth || 0) + 1).join('  ');
        for (var c = n.firstChild; c; c = c.nextSibling) {
          if (c.nodeType !== 1 || c.tagName.toUpperCase() !== 'LI') continue;
          i++;
          var body = ''; for (var k = c.firstChild; k; k = k.nextSibling) body += md(k, (depth || 0) + 1);
          body = body.replace(/^\n+/, '').replace(/\n{3,}/g, '\n\n').replace(/\s+$/, '');
          out += pad + (t === 'OL' ? i + '. ' : '- ') + body.replace(/\n\n+/g, '\n') + '\n';
        }
        return out + '\n';
      }
      case 'TABLE': {
        var rows = Array.prototype.slice.call(n.querySelectorAll('tr')).map(function (tr) {
          return Array.prototype.slice.call(tr.children).map(function (td) { return inline(td).replace(/\|/g, '\\|'); });
        }).filter(function (r) { return r.length; });
        if (!rows.length) return '';
        var w = rows[0].length, line = function (r) { var c = r.slice(); while (c.length < w) c.push(''); return '| ' + c.join(' | ') + ' |'; };
        var o2 = '\n\n' + line(rows[0]) + '\n|' + new Array(w + 1).join(' --- |') + '\n';
        for (var q = 1; q < rows.length; q++) o2 += line(rows[q]) + '\n';
        return o2 + '\n';
      }
      case 'A': return kids();
      default: {
        var s = kids(), blockish = /^(DIV|SECTION|ARTICLE|MESSAGE-CONTENT|MODEL-RESPONSE|MAIN)$/.test(t);
        return blockish ? s + '\n' : s;
      }
    }
  }
  function toMarkdown(el) { return md(el, 0).replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim(); }

  function answers() { return pickAll(P.answer); }
  function lastAnswer(base) { var a = answers(); return a.length > base ? a[a.length - 1] : null; }

  async function waitDone(base) {
    var t0 = Date.now(), sawStop = false, lastLen = -1, stableSince = Date.now(), noStopSince = 0;
    while (Date.now() - t0 < 12 * 60000) {
      await sleep(700);
      if (cancelled) throw new Error('사용자가 중지했어요');
      var stop = !!pick(P.stop); if (stop) sawStop = true;
      var a = lastAnswer(base), len = a ? (a.innerText || a.textContent || '').length : 0;
      if (!sawStop && !len && Date.now() - t0 > 90000) throw new Error('답변이 시작되지 않았어요(전송이 안 된 것 같아요)');
      if (len !== lastLen) { lastLen = len; stableSince = Date.now(); }
      if (stop) noStopSince = 0; else if (!noStopSince) noStopSince = Date.now();
      var quiet = Date.now() - stableSince;
      if (len > 0 && !stop && noStopSince && Date.now() - noStopSince > 2500 && quiet > 2500 && (sawStop || quiet > 9000)) return a;
      status('답변을 만드는 중… ' + (len ? len.toLocaleString() + '자' : '대기'));
    }
    throw new Error('답변이 너무 오래 걸려서 멈췄어요');
  }

  var WHY = '', TABID = Math.random().toString(36).slice(2);
  async function findJob() {
    for (var i = 0; i < 40; i++) {   /* 최대 16초 기다려요(확장 프로그램 저장소 반영이 늦는 경우 대비) */
      var j = await gget('job');
      if (!j) WHY = '저장된 작업이 없어요';
      else if (JOB) { if (j.id === JOB) return j; WHY = '다른 작업이 저장돼 있어요(번호 불일치)'; }
      else if (j.host === location.hostname && Date.now() - j.ts < 30000) {
        if (j.claim && j.claim !== TABID) { WHY = '같은 사이트의 다른 탭이 이미 작업을 가져갔어요'; }   /* 제미나이 탭이 여러 개일 때 남의 작업을 가로채지 않아요 */
        else { JOB = j.id; j.claim = TABID; await gset('job', j); return j; }
      }
      await sleep(400);
    }
    return null;
  }
  /* 작업을 못 찾았을 때의 구조 방법: 종목분석 미니가 열기 직전에 클립보드에 복사해 둔 프롬프트를 읽어 같은 방식으로 진행 */
  function rescue() {
    banner('⚠ 종목분석 미니에서 보낸 작업을 찾지 못했어요(' + (WHY || '원인 모름') + '). 아래 [복사된 프롬프트로 진행]을 누르면 복사해 둔 프롬프트로 이어서 자동 진행해요.', 'bad', { label: '📋 복사된 프롬프트로 진행', fn: function () {
      var rd = null;
      try { rd = navigator.clipboard.readText(); } catch (e) { rd = null; }
      if (!rd) { banner('⚠ 이 브라우저에서 클립보드를 읽을 수 없어요. 입력칸에 Ctrl+V 하고 직접 진행하세요.', 'bad'); return; }
      rd.then(function (t) {
        t = String(t || '').trim();
        if (t.length < 100) { banner('⚠ 복사된 프롬프트가 없어요. 종목분석 미니에서 [📋 다시 복사]를 누르고 다시 시도하세요.', 'bad'); return; }
        runJob({ id: JOB, prompt: t, host: location.hostname, ts: Date.now() });
      }).catch(function () { banner('⚠ 클립보드 읽기가 허용되지 않았어요(주소창 왼쪽 권한에서 허용). 입력칸에 Ctrl+V 하고 직접 진행하세요.', 'bad'); });
    } });
  }

  async function main() {
    if (JOB) banner('🤖 종목분석 미니 도우미 · 작업을 확인하는 중…');
    var job = HASHJOB;
    if (job) await gset('job', job); else job = await findJob();
    if (!job && !JOB) return;   /* 그냥 직접 연 AI 화면: 아무것도 하지 않아요 */
    if (!job) { rescue(); return; }
    /* 작업은 끝날 때까지 지우지 않아요: 화면이 새로고침돼 도우미가 다시 시작돼도 작업을 잃지 않게 */
    if (job.sent) {
      var msg0 = '전송한 뒤 AI 화면이 새로고침돼서 답변을 자동으로 읽지 못했어요. AI 대화에서 답변을 직접 복사하고 종목분석 미니로 돌아가세요.';
      await gset('result', { id: JOB, error: msg0, ts: Date.now() }); await gdel('job');
      banner('⚠ ' + msg0, 'bad'); return;
    }
    await runJob(job);
  }
  async function runJob(job) {
    try {
      status(P.name + ' 입력창을 찾는 중…');
      var inp = await waitFor(function () { return pickVisible(P.input); }, 45000, '입력창');
      await sleep(900);
      status('프롬프트를 입력하는 중…');
      inp = await fillPrompt(job.prompt);
      var base = answers().length;
      status('전송하는 중…');
      await gset('job', { id: job.id, prompt: job.prompt, host: job.host, ts: Date.now(), sent: true });
      var btn = null;
      try { btn = await waitFor(function () { var b = pick(P.send); if (b && !disabled(b)) return b; return genericSend(inp); }, 12000, '전송 버튼'); } catch (e) { btn = null; }
      if (btn) btn.click(); else enter(inp);
      await sleep(1500);
      var plen = job.prompt.replace(/\s+/g, '').length;
      var sent = function () { return !!pick(P.stop) || answers().length > base || inputText(inp).replace(/\s+/g, '').length < plen * 0.3; };
      if (!sent()) {
        status('전송이 안 된 것 같아 한 번 더 시도해요…');
        enter(inp); await sleep(1500);
        if (!sent()) { var b2 = genericSend(inp) || pick(P.send); if (b2 && !disabled(b2)) b2.click(); await sleep(1500); }
      }
      var a = await waitDone(base);
      var text = toMarkdown(a);
      if (text.length < 20) throw new Error('답변 글을 읽지 못했어요');
      try { GM_setClipboard(text, 'text'); } catch (e) { try { navigator.clipboard.writeText(text); } catch (e2) {} }
      await gset('result', { id: JOB, text: text, ts: Date.now() });
      await gdel('job');
      banner('✅ 답변을 복사해서 종목분석 미니로 보냈어요 (' + text.length.toLocaleString() + '자). 이 탭은 곧 닫혀요.', 'ok');
      await sleep(1600);
      for (var ci = 0; ci < 3; ci++) { try { window.close(); } catch (e) {} await sleep(500); }
      banner('✅ 답변을 종목분석 미니로 보냈어요. 이 탭은 닫고 돌아가세요. (자동으로 안 닫히면 도우미를 최신 버전(1.5.11)으로 다시 설치해 주세요)', 'ok');
    } catch (err) {
      var msg = String((err && err.message) || err);
      await gset('result', { id: JOB, error: msg, ts: Date.now() });
      await gdel('job');
      banner('⚠ 자동 진행이 멈췄어요: ' + msg + ' — 프롬프트는 복사돼 있어요. [다시 시도]를 누르거나 입력칸에 Ctrl+V 하고 직접 이어서 진행하세요.', 'bad', { label: '🔁 다시 시도', fn: function () { cancelled = false; runJob(job); } });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { main(); }); else main();
})();
"""

# ───────────────────────── 경로 ─────────────────────────
def _asset(text, mime):
    resp = C.app.make_response(text)
    resp.headers["Content-Type"] = mime + "; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@bp.route("/assets/mini-ui.css")
def ui_css():
    return _asset(UI_CSS, "text/css")


@bp.route("/assets/mini-ai.css")
def ai_css():
    # 종목분석 메인 화면용 — 전체 공통 CSS(박스 모델·변수 등)는 빼고 'AI 창' 부분만 준다(메인 화면 모양이 바뀌지 않게).
    return _asset("/* ── MiniAI" + UI_CSS.split("/* ── MiniAI")[1], "text/css")


@bp.route("/assets/mini-ui.js")
def ui_js():
    return _asset(UI_JS, "application/javascript")


def _origin():
    """이 사이트의 주소(https://도메인). 사용자 스크립트가 '이 사이트'를 알아보는 데 쓴다."""
    host = request.host
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
    if host.split(":")[0] not in ("127.0.0.1", "localhost"):
        proto = "https"
    return f"{proto}://{host}"


@bp.route("/assets/mini-ai-helper.user.js")
def helper_js():
    resp = C.app.make_response(HELPER_JS.replace("__ORIGIN__", _origin()))
    resp.headers["Content-Type"] = "text/javascript; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/ai-helper")
def helper_page():
    body = (
        '<div class="mu-card"><div class="mu-card-h">🤖 AI 도우미<small>선택 사항 · 한 번만 설치</small></div><div class="mu-card-b">'
        '<p id="ahState" style="font-weight:700;margin:0 0 10px">설치 여부를 확인하는 중…</p>'
        '<p>설치하면 [제미나이/챗GPT/클로드/퍼플렉시티 열기]를 누르는 순간 <b>프롬프트 입력 → 전송 → 답변 끝날 때까지 대기 → 답변 복사 → 탭 닫기 → 이 사이트로 답변 전달</b>까지 자동으로 진행돼요. '
        '설치하지 않아도 지금처럼(붙여넣기 → 답변 복사) 그대로 쓸 수 있어요.</p>'
        '<ol style="line-height:1.9;padding-left:20px">'
        '<li>크롬(또는 엣지)에 <b>Tampermonkey(탬퍼몽키)</b> 확장을 설치해요. 크롬 웹 스토어에서 ‘Tampermonkey’ 검색.</li>'
        '<li>크롬 주소창에 <code>chrome://extensions</code> → Tampermonkey [세부정보] → <b>‘사용자 스크립트 허용’</b>을 켜요(최근 크롬에서 필요).</li>'
        '<li>아래 <b>[도우미 설치]</b> 버튼을 누르면 Tampermonkey 설치 화면이 떠요 → [설치].</li>'
        '<li>크롬 <code>chrome://extensions</code> → Tampermonkey [세부정보] → <b>‘사이트 액세스’를 ‘모든 사이트에서’</b>로 바꿔요(‘클릭 시’나 특정 사이트면 제미나이 등에서 동작하지 않아요).</li>'
        '<li>이 사이트를 새로고침한 뒤, AI 창에서 [AI 열기]를 눌러 보세요. 새로 열린 AI 화면 위쪽에 🤖 안내 띠가 나오면 성공이에요.</li></ol>'
        '<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:12px;padding:12px 14px;margin:6px 0 14px;font-size:13.5px;line-height:1.8">'
        '<b>🤖 완전 자동 진행 (v1.5.1~)</b><br>이제 AI 분석 버튼을 누르면 창에서 또 누를 필요 없이 <b>AI 탭이 저절로 열리고</b>(팝업 차단을 받지 않아요) 입력·전송·답변 복사·저장·다음 단계까지 이어져요. 관리자 로그인 상태에서 서버에 AI API 키가 있으면 도우미 없이도 서버가 직접 분석해 줘요. 이 기능은 도우미를 <b>다시 설치(업데이트)</b>해야 켜져요.</div>'
        '<div style="background:#eff6ff;border:1px solid #93c5fd;border-radius:12px;padding:12px 14px;margin:6px 0 14px;font-size:13.5px;line-height:1.8">'
        '<b>✍ 블로그 자동 입력 (v1.4.0~)</b><br>글 만들기 뒤 [복사하고 블로그 열기]를 누르면, 열린 <b>네이버 글쓰기 화면</b>에 도우미가 <b>제목 → 본문 맨 위 대표 이미지 → 본문</b>을 자동으로 넣어요. <b>발행은 직접</b> 눌러요. 안 들어가면 안내 띠가 뜨고, 복사돼 있으니 본문을 눌러 Ctrl+V 하면 돼요. 끄려면 브라우저 콘솔에서 <code>localStorage.setItem(\'mini_blog_paste\',\'0\')</code>. 이 기능은 도우미를 <b>다시 설치(업데이트)</b>해야 켜져요.</div>'
        '<div style="background:#fffbeb;border:1px solid #fcd34d;border-radius:12px;padding:12px 14px;margin:6px 0 14px;font-size:13.5px;line-height:1.8">'
        '<b>🔧 설치했는데 자동으로 안 될 때 (순서대로 확인)</b><br>'
        '① 위 ‘설치 여부’가 ✅ 로 나오는지 — 안 나오면 이 화면을 새로고침(Ctrl+F5)<br>'
        '② Tampermonkey [세부정보]에서 <b>사용자 스크립트 허용 ON</b>, <b>사이트 액세스 = 모든 사이트에서</b><br>'
        '③ Tampermonkey 대시보드에서 ‘종목분석 미니 · AI 도우미’가 <b>켜짐</b>(파란 스위치)인지, 버전이 <b>1.5.10</b>인지 — 아니면 아래 [도우미 설치]를 다시 눌러 ‘업데이트/재설치’<br>'
        '④ AI 사이트(제미나이 등)에 <b>로그인</b>된 상태인지, 이미 열려 있던 AI 탭은 새로고침<br>'
        '⑤ 그래도 안 되면: [AI 열기] 때 프롬프트는 이미 복사돼 있으니 AI 입력칸에 Ctrl+V → 전송 → 답변 복사 후 이 창으로 돌아오면 기존 방식으로 가져와요.</div>'
        '<p><a class="mu-btn" href="/assets/mini-ai-helper.user.js" style="display:inline-block;padding:10px 18px;border-radius:12px;background:#2457d6;color:#fff;font-weight:700;text-decoration:none">⬇ 도우미 설치</a></p>'
        '<p style="color:#64748b;font-size:13px;line-height:1.7">· 이 스크립트는 내 브라우저 안에서만 동작하고, 로그인 정보나 대화 내용을 어디로도 보내지 않아요.<br>'
        '· 이 사이트에서 보낸 작업만 처리해요. 다른 경로로 연 AI 화면은 건드리지 않아요.<br>'
        '· AI 사이트 화면이 개편되면 자동 진행이 중간에 멈출 수 있어요. 그때는 프롬프트가 이미 복사돼 있으니 입력칸에 Ctrl+V 하고 기존 방식으로 이어서 하면 돼요.<br>'
        '· 자동 진행 중에는 AI 화면 위쪽 띠의 [중지]로 멈출 수 있어요. 이 창의 AI 도우미 창에서 ‘도우미 사용’ 체크를 끄면 언제든 기존 방식으로 돌아가요.</p>'
        '</div></div>'
    )
    script = ("function ahChk(last){var s=document.documentElement.getAttribute('data-mini-helper');var e=document.getElementById('ahState');"
              "if(s){var old=s.split('.').map(Number);var isOld=old[0]<1||(old[0]===1&&old[1]<5||(old[1]===5&&(old[2]||0)<8));e.textContent='✅ 도우미가 설치되어 있어요 (v'+s+')'+(isOld?' — 새 버전(1.5.11)이 있어요. 아래 [도우미 설치]를 눌러 업데이트하세요.':'');e.style.color=isOld?'#b45309':'#15803d'}else if(last){e.textContent='아직 설치되어 있지 않아요(또는 설치 직후라면 새로고침하세요).';e.style.color='#b45309'}}"
              "ahChk(false);setTimeout(function(){ahChk(false)},300);setTimeout(function(){ahChk(true)},1200);")
    resp = C.app.make_response(page("AI 도우미", body, icon="🤖", subtitle="AI 입력·전송·답변 복사를 자동으로 해 주는 선택 도구", script=script))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/api/ui/config")
def ui_config():
    resp = jsonify({"ai_site": ai_site(), "run_mode": (C.setting_get("ai_run_mode") if C.setting_get("ai_run_mode") in ("auto", "browser", "manual") else "auto"), "ai_sites": {k: v["name"] for k, v in AI_SITES.items()}})
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ───────────────────────── 등록 ─────────────────────────
def _valid_site(k, v):
    return v if v in AI_SITES else None


def register():
    C.register_settings({"manual_ai_site": DEFAULT_AI_SITE}, {"manual_ai_site": _valid_site})
    # 관리자 화면(엄격한 보안 설정)에서도 같은 도우미를 쓰도록 JS·CSS 를 함께 넣는다.
    C.register_admin_lib("window.__MA_CSS__=" + _js_str("/* ── MiniAI" + UI_CSS.split("/* ── MiniAI")[1]) + ";\n" + UI_JS)
    return bp
