"""🖼 이미지 저장 — 블로그에 올릴 그림(PNG)을 만들고, 정해 둔 폴더에 날짜·메뉴별로 정리해서 저장한다.

· ① 메인 이미지: 종목명·종합점수 게이지(가운데 강조)·5축 레이더/막대·매물대/수급/재무 요약
· ② 통합 이미지: 주가 차트(이동평균·매물대) + 재무 차트 + 동일업종 비교 + 기술적 지표를 한 장에
· 저장 위치: [다운로드 폴더]/20261002/종목분석/① 종목명_종목코드.png  (동그라미 숫자 = 이미지 순서)
· 폴더·자동/수동 모드는 이 기기(브라우저)에만 저장된다(폴더 접근 권한은 기기마다 따로 허용해야 하므로).
  메뉴 폴더 이름과 이미지 선명도(배율)는 서버 설정(img_cfg)에 저장돼 모든 기기에서 같다.
· 폴더 지정은 데스크톱 크롬·엣지에서 가능하다. 지원하지 않는 브라우저는 일반 다운로드로 저장한다.

그림은 전부 브라우저(캔버스)에서 그린다 — 서버는 설정 값만 저장한다.
"""
import json
import re
from flask import Blueprint
from menu_ctx import C

bp = Blueprint("img", __name__)

DEFAULT_CFG = {"folders": {"stock": "종목분석", "deep": "심층분석", "daily": "오늘추천"}, "scale": 2}
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_cfg(d):
    d = d if isinstance(d, dict) else {}
    fo = dict(DEFAULT_CFG["folders"])
    for k, v in (d.get("folders") or {}).items() if isinstance(d.get("folders"), dict) else []:
        k, v = str(k), str(v).strip().strip(".")
        if re.match(r"^[a-z][a-z0-9_]{0,23}$", k) and 1 <= len(v) <= 20 and not _BAD.search(v):
            fo[k] = v
    try:
        sc = float(d.get("scale", DEFAULT_CFG["scale"]))
    except Exception:
        sc = DEFAULT_CFG["scale"]
    sc = min((1, 1.5, 2, 3), key=lambda x: abs(x - sc))
    return {"folders": fo, "scale": sc}


def _valid_cfg(k, v):
    try:
        d = json.loads(v) if isinstance(v, str) else v
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    # 폴더 이름에 쓸 수 없는 글자가 들어 있으면 조용히 고치지 않고 거부한다(저장이 안 된 걸 알 수 있게)
    for x in (d.get("folders") or {}).values() if isinstance(d.get("folders"), dict) else []:
        if _BAD.search(str(x)) or not (1 <= len(str(x).strip()) <= 20):
            return None
    return json.dumps(clean_cfg(d), ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# ImgKit — 저장(폴더·모드·다운로드) + 화면 패널.  종목 그림 그리기는 STOCK_JS.
# ══════════════════════════════════════════════════════════════
IMGKIT_JS = r"""
(function(){
if(window.ImgKit)return;
var K=window.ImgKit={supported:!!window.showDirectoryPicker,_cfg:null};
var FONT='"Pretendard","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo","Noto Sans CJK KR",sans-serif';
var CIRC=['①','②','③','④','⑤','⑥','⑦','⑧','⑨','⑩'];
K.FONT=FONT;K.CIRC=CIRC;
var DEF={folders:{stock:'종목분석',deep:'심층분석',daily:'오늘추천'},scale:2};
function lsGet(k,d){try{var v=localStorage.getItem(k);return v==null?d:v}catch(e){return d}}
function lsSet(k,v){try{localStorage.setItem(k,v)}catch(e){}}
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function toast(m){if(typeof window.toast==='function')window.toast(m);else if(typeof window.showToast==='function')window.showToast(m);else try{console.log(m)}catch(e){}}
K.toast=toast;
/* ── 서버 설정(메뉴 폴더 이름·배율) ── */
K.loadCfg=function(force){if(K._cfg&&!force)return Promise.resolve(K._cfg);
 return fetch('/admin/api/settings',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
  var d={};try{d=JSON.parse(j.img_cfg||'{}')}catch(e){}
  var fo={};Object.keys(DEF.folders).forEach(function(k){fo[k]=DEF.folders[k]});Object.keys(d.folders||{}).forEach(function(k){fo[k]=d.folders[k]});
  K._cfg={folders:fo,scale:Number(d.scale)||DEF.scale};return K._cfg}).catch(function(){K._cfg={folders:DEF.folders,scale:DEF.scale};return K._cfg})};
K.menuFolder=function(menu){var c=K._cfg||DEF;return (c.folders&&c.folders[menu])||menu};
/* ── 이 기기 설정: 자동/수동 ── */
K.mode=function(){return lsGet('mini_img_mode','manual')==='auto'?'auto':'manual'};
K.setMode=function(m){lsSet('mini_img_mode',m==='auto'?'auto':'manual')};
/* 자동 저장 시점: 'ai' = AI 분석·리포트가 끝난 뒤(기본), 'analysis' = 종목 분석 직후 */
K.when=function(){return lsGet('mini_img_when','ai')==='analysis'?'analysis':'ai'};
K.setWhen=function(w){lsSet('mini_img_when',w==='analysis'?'analysis':'ai')};
/* ── 폴더 핸들(IndexedDB) ── */
function idb(){return new Promise(function(res,rej){try{var r=indexedDB.open('mini_img',1);r.onupgradeneeded=function(){r.result.createObjectStore('kv')};r.onsuccess=function(){res(r.result)};r.onerror=function(){rej(r.error)}}catch(e){rej(e)}})}
function idbGet(k){return idb().then(function(db){return new Promise(function(res,rej){var q=db.transaction('kv').objectStore('kv').get(k);q.onsuccess=function(){res(q.result||null)};q.onerror=function(){rej(q.error)}})}).catch(function(){return null})}
function idbSet(k,v){return idb().then(function(db){return new Promise(function(res,rej){var tx=db.transaction('kv','readwrite');if(v==null)tx.objectStore('kv').delete(k);else tx.objectStore('kv').put(v,k);tx.oncomplete=function(){res(true)};tx.onerror=function(){rej(tx.error)}})}).catch(function(){return false})}
K.handle=function(){return K.supported?idbGet('dir'):Promise.resolve(null)};
K.pick=function(){if(!K.supported)return Promise.reject(new Error('이 브라우저는 폴더 지정을 지원하지 않아요(데스크톱 크롬·엣지에서 가능).'));
 var go;try{go=window.showDirectoryPicker({id:'mini_img',mode:'readwrite',startIn:'documents'})}catch(e){return Promise.reject(K.explain(e))}
 return go.then(function(h){return idbSet('dir',h).then(function(){return idbGet('dir')}).then(function(back){if(!back)throw new Error('폴더를 골랐지만 브라우저가 기억하지 못했어요. 시크릿 창이거나 사이트 데이터 저장이 막혀 있으면 폴더를 기억할 수 없어요.');return h})}).catch(function(e){throw K.explain(e)})};
K.explain=function(e){var n=(e&&e.name)||'',m=(e&&e.message)||String(e||'');
 if(n==='AbortError')return Object.assign(new Error('폴더 선택을 취소했어요.'),{name:'AbortError'});
 if(n==='SecurityError'||/system files|blocked|시스템/i.test(m))return Object.assign(new Error('이 폴더는 브라우저가 보안상 선택하지 못하게 막아 둔 폴더예요. 다운로드·문서·바탕 화면 폴더 자체는 고를 수 없어요 → 그 안에 새 폴더(예: 블로그이미지)를 만든 뒤 그 폴더를 선택해 주세요.'),{name:'SecurityError'});
 if(n==='NotAllowedError')return Object.assign(new Error('폴더 선택 창을 열 수 없었어요(클릭 직후가 아니거나 팝업이 막힌 상태). 버튼을 다시 눌러 주세요.'),{name:n});
 return e instanceof Error?e:new Error(m)};
K.forget=function(){return idbSet('dir',null)};
K.perm=function(h,ask){if(!h||!h.queryPermission)return Promise.resolve(false);
 return h.queryPermission({mode:'readwrite'}).then(function(p){if(p==='granted')return true;if(!ask)return false;return h.requestPermission({mode:'readwrite'}).then(function(q){return q==='granted'})}).catch(function(){return false})};
K.info=function(){return K.handle().then(function(h){if(!h)return {supported:K.supported,name:'',perm:'none'};
 return K.perm(h,false).then(function(ok){return {supported:K.supported,name:h.name||'(선택한 폴더)',perm:ok?'granted':'prompt',h:h}})})};
/* ── 이름 만들기 ── */
K.dateDir=function(d){d=d||new Date();var z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())};
K.fileName=function(idx,name,ticker){var nm=String(name||'').replace(/[\\\/:*?"<>|\s]+/g,'_').replace(/^_+|_+$/g,'')||'종목';return (CIRC[idx-1]||('('+idx+')'))+' '+nm+(ticker?'_'+ticker:'')+'.png'};
K.path=function(o){return K.dateDir()+'/'+K.menuFolder(o.menu)+'/'+K.fileName(o.idx,o.name,o.ticker)};
function download(blob,fn){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=fn;document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},4000)}
/* 저장: 폴더가 지정돼 있고 권한이 있으면 폴더에, 아니면 일반 다운로드. noAsk=true 면 권한을 묻지 않고 'needperm' 을 돌려준다(자동 모드용). */
K.save=function(blob,o){var fn=K.fileName(o.idx,o.name,o.ticker);
 return K.loadCfg().then(function(){return K.handle()}).then(function(h){
  if(!h||!K.supported){download(blob,fn);return {where:'download',path:fn}}
  return K.perm(h,!o.noAsk).then(function(ok){
   if(!ok){if(o.noAsk)return {where:'needperm',path:fn};download(blob,fn);return {where:'download',path:fn,note:'폴더 권한이 없어 일반 다운로드로 저장했어요.'}}
   var dd=K.dateDir(),mf=K.menuFolder(o.menu);
   return h.getDirectoryHandle(dd,{create:true}).then(function(d1){return d1.getDirectoryHandle(mf,{create:true})}).then(function(d2){return d2.getFileHandle(fn,{create:true})})
    .then(function(fh){return fh.createWritable()}).then(function(w){return w.write(blob).then(function(){return w.close()})})
    .then(function(){return {where:'folder',path:h.name+'/'+dd+'/'+mf+'/'+fn}})
    .catch(function(e){download(blob,fn);return {where:'download',path:fn,note:'폴더에 저장하지 못해 일반 다운로드로 저장했어요('+(e&&e.name||'오류')+').'}})})})};
K.toBlob=function(canvas){return new Promise(function(res){canvas.toBlob(function(b){res(b)},'image/png')})};
/* ── 캔버스 도우미 ── */
K.rr=function(c,x,y,w,h,r){r=Math.min(r,w/2,h/2);c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath()};
K.text=function(c,s,x,y,o){o=o||{};c.save();c.font=(o.w||600)+' '+(o.s||24)+'px '+FONT;c.fillStyle=o.c||'#111';c.textAlign=o.a||'left';c.textBaseline=o.b||'alphabetic';
 if(o.ls&&('letterSpacing' in c))c.letterSpacing=o.ls+'px';
 var t=String(s),sz=o.s||24;if(o.max){while(c.measureText(t).width>o.max&&sz>10){sz-=1;c.font=(o.w||600)+' '+sz+'px '+FONT}}
 if(o.st){c.lineJoin='round';c.lineWidth=o.sw||4;c.strokeStyle=o.st;c.strokeText(t,x,y)}c.fillText(t,x,y);c.restore()};
K.wrap=function(c,s,maxW,font){c.save();c.font=font;var out=[],ln='';String(s).split('').forEach(function(ch){var t=ln+ch;if(c.measureText(t).width>maxW&&ln){out.push(ln);ln=ch.trim()?ch:''}else ln=t});if(ln)out.push(ln);c.restore();return out};
K.make=function(w,h,scale){var cv=document.createElement('canvas');cv.width=Math.round(w*scale);cv.height=Math.round(h*scale);var c=cv.getContext('2d');c.scale(scale,scale);c.textBaseline='alphabetic';return {cv:cv,c:c}};
K.n=function(v,d){if(v==null||v===''||isNaN(v))return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d})};
K.sgn=function(v,d){if(v==null||isNaN(v))return '-';var n=Number(v);return (n>0?'+':'')+n.toLocaleString('ko-KR',{maximumFractionDigits:d==null?1:d})};
K.fonts=function(){try{if(document.fonts&&document.fonts.load){return Promise.all([document.fonts.load('700 20px '+FONT),document.fonts.load('900 20px '+FONT)]).catch(function(){})}}catch(e){}return Promise.resolve()};

/* ── 화면 패널 ──
   o: {menu, name, ticker, gen:function()->Promise<[{idx,label,canvas}]>, auto:bool, title}  */
var CSS='.ikp{margin-top:6px}.ikp .ikr{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}.ikp .ikn{font-size:12px;color:#6b7280;line-height:1.6}'+
'.ikp .ikb{font:inherit;font-size:13px;font-weight:700;border-radius:10px;padding:8px 14px;cursor:pointer;border:1.5px solid #c7d2fe;background:#fff;color:#312e81}.ikp .ikb.p{background:#312e81;color:#fff;border-color:#312e81}.ikp .ikb:disabled{opacity:.5;cursor:default}'+
'.ikp .ikv{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:10px}.ikp .ikc{border:1.5px solid #e5e7eb;border-radius:12px;padding:8px;background:#fafafa}.ikp .ikc img{width:100%;height:auto;display:block;border-radius:8px}.ikp .ikc b{font-size:13px;color:#1e1b4b}'+
'.ikp .ikw{background:#fff7ed;border:1.5px solid #fdba74;color:#9a3412;border-radius:10px;padding:8px 12px;font-size:12.5px;line-height:1.6;margin:8px 0}';
function ensureCss(){if(document.getElementById('ikCss'))return;var s=el('style');s.id='ikCss';s.textContent=CSS;document.head.appendChild(s)}
K.panel=function(box,o){ensureCss();box.innerHTML='';var P=el('div','ikp');box.appendChild(P);
 var S={items:null,busy:false};
 var st=el('div','ikn');var warn=el('div');var row=el('div','ikr'),view=el('div','ikv');
 var bGen=el('button','ikb p','🖼 이미지 만들기');var bAll=el('button','ikb','💾 둘 다 저장');bAll.style.display='none';
 var bSet=el('button','ikb','⚙ 저장 설정');
 bSet.onclick=function(){try{if(typeof openAdminWin==='function'){openAdminWin('#ik');return}}catch(e){}window.open('/admin#ik','mini_admin')};
 row.appendChild(bGen);row.appendChild(bAll);row.appendChild(bSet);P.appendChild(row);P.appendChild(st);P.appendChild(warn);P.appendChild(view);
 function whereText(i){var p=i.supported&&i.name&&i.perm!=='none'?(i.name+'/'+K.dateDir()+'/'+K.menuFolder(o.menu)+'/'):'브라우저 기본 다운로드 폴더';
  return '저장 위치: '+p+' · 모드: '+(K.mode()==='auto'?'자동 저장':'수동 저장(버튼)')}
 function refresh(){return K.loadCfg().then(function(){return K.info()}).then(function(i){st.textContent=whereText(i);
  warn.innerHTML='';if(i.supported&&i.name&&i.perm==='prompt'){var w=el('div','ikw','🔒 폴더 "'+i.name+'" 접근 권한이 이 세션에서 아직 허용되지 않았어요. [권한 허용]을 한 번 누르면 이 창을 닫을 때까지 자동·수동 저장이 모두 폴더로 들어갑니다.');
   var b=el('button','ikb p','권한 허용');b.style.marginLeft='8px';b.onclick=function(){K.perm(i.h,true).then(function(ok){toast(ok?'폴더 권한을 허용했어요':'권한이 허용되지 않았어요');refresh();if(ok&&S.pendingAuto){S.pendingAuto=false;saveAll(true)}})};w.appendChild(b);warn.appendChild(w)}
  return i})}
 function one(it,noAsk){return K.toBlob(it.canvas).then(function(b){return K.save(b,{menu:o.menu,idx:it.idx,name:o.name,ticker:o.ticker,noAsk:noAsk})})}
 function report(rs){var f=rs.filter(function(r){return r.where==='folder'}),d=rs.filter(function(r){return r.where==='download'}),n=rs.filter(function(r){return r.where==='needperm'});
  if(n.length){S.pendingAuto=true;refresh();toast('폴더 권한이 필요해요 — [권한 허용]을 눌러 주세요');return}
  if(f.length)toast('저장했어요: '+f[0].path+(f.length>1?' 외 '+(f.length-1)+'장':''));
  else if(d.length)toast((d[0].note||'다운로드 폴더에 저장했어요')+' ('+d.length+'장)')}
 function saveAll(noAsk){if(!S.items)return Promise.resolve();return Promise.all(S.items.map(function(it){return one(it,noAsk)})).then(report)}
 function draw(){view.innerHTML='';S.items.forEach(function(it){var c=el('div','ikc');c.appendChild(el('b',null,K.CIRC[it.idx-1]+' '+it.label));var im=new Image();im.alt=it.label;
  var pw=Math.min(720,it.canvas.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(it.canvas.height*pw/it.canvas.width);sm.getContext('2d').drawImage(it.canvas,0,0,sm.width,sm.height);im.src=sm.toDataURL('image/png');c.appendChild(im);var r=el('div','ikr');var sv=el('button','ikb','💾 저장');sv.onclick=function(){one(it,false).then(function(x){report([x])})};r.appendChild(sv);
  c.appendChild(r);c.appendChild(el('div','ikn',K.fileName(it.idx,o.name,o.ticker)+' · '+it.canvas.width+'×'+it.canvas.height));view.appendChild(c)});bAll.style.display=''}
 function gen(auto){if(S.busy)return Promise.resolve();S.busy=true;bGen.disabled=true;bGen.textContent='⏳ 그리는 중…';
  return K.loadCfg().then(K.fonts).then(function(){return o.gen(K._cfg.scale)}).then(function(items){S.items=items;draw();bGen.textContent='🔄 다시 만들기';if(o.onDone){try{o.onDone()}catch(e){}}
   return refresh().then(function(){if(auto&&K.mode()==='auto')return saveAll(true)})})
   .catch(function(e){toast('이미지를 만들지 못했어요: '+(e&&e.message||e));bGen.textContent='🖼 이미지 만들기'})
   .then(function(){S.busy=false;bGen.disabled=false})}
 bGen.onclick=function(){gen(false)};bAll.onclick=function(){saveAll(false)};
 refresh();
 return {gen:gen,refresh:refresh,items:function(){return S.items}}};
})();
"""

# ══════════════════════════════════════════════════════════════
# 종목분석 그림 — ① 메인 / ② 통합
# ══════════════════════════════════════════════════════════════
STOCK_JS = r"""
(function(){
if(!window.ImgKit||ImgKit.stock)return;
var K=ImgKit,FONT=K.FONT,T=K.text,N=K.n,SG=K.sgn;
var UP='#e11d48',DN='#2563eb',NAVY0='#0a1228',NAVY1='#16275a',GOLD='#d6b25e',GOLD2='#f6e7b4',PAPER='#f4f0e6',INK='#0f172a',MUT='#64748b';
var AXC={tech:'#2563eb',mom:'#7c3aed',sup:'#0f766e',fin:'#16a34a',val:'#d97706'};
function scCol(s){return s>=70?'#22c55e':(s>=50?'#f59e0b':'#ef4444')}
function scColDark(s){return s>=70?'#4ade80':(s>=50?'#fbbf24':'#f87171')}
function today(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+'-'+z(d.getMonth()+1)+'-'+z(d.getDate())}
function shadowCard(c,x,y,w,h,r,fill){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;K.rr(c,x,y,w,h,r);c.fillStyle=fill||'#fff';c.fill();c.restore()}
function lastActual(fin){var a=fin&&fin.annual;if(!a||!a.periods)return null;var idx=-1;a.periods.forEach(function(p,i){if(!p.estimate)idx=i});if(idx<0)idx=a.periods.length-1;
 function g(n){var r=(a.rows||[]).filter(function(z){return z.name===n})[0];return r?r.values[idx]:null}
 return {title:a.periods[idx].title,rev:g('매출액'),op:g('영업이익'),opm:g('영업이익률'),ni:g('당기순이익')}}
function eok(v){if(v==null||isNaN(v))return '-';var a=Math.abs(v);if(a>=10000)return (v/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조';return Math.round(v).toLocaleString('ko-KR')+'억'}
function headline(ext){var ax=(ext&&ext.score&&ext.score.axes||[]).filter(function(a){return a.score!=null});if(!ax.length)return '';
 var s=ax.slice().sort(function(a,b){return b.score-a.score}),best=s[0],worst=s[s.length-1];
 if(ax.length<2)return best.name+' '+best.score+'점';
 if(best.score-worst.score<12)return '5개 축이 고르게 '+(best.score>=60?'양호한':'중립적인')+' 모습';
 return best.name+' 강점 · '+worst.name+(worst.score<50?' 점검 필요':' 보완 여지')}
function gradeText(g){return g==='긍정'?'긍정 신호 우세':(g==='주의'?'주의 · 점검 필요':'중립 · 혼조')}

/* ═════════ ① 메인 이미지 ═════════ */
function drawMain(cur,ext,scale){
 var W=1080,H=1560,m=K.make(W,H,scale),c=m.c,p=cur.price||{},f=cur.fundamentals||{},d=cur.details||{};
 var sc=ext&&ext.score||{axes:[],total:0,grade:'중립'};
 /* 바탕: 위는 짙은 남색, 아래는 종이색 */
 c.fillStyle=PAPER;c.fillRect(0,0,W,H);
 var g=c.createLinearGradient(0,0,0,820);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,820);
 var rg=c.createRadialGradient(540,520,20,540,520,520);rg.addColorStop(0,'rgba(214,178,94,.26)');rg.addColorStop(.55,'rgba(214,178,94,.07)');rg.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=rg;c.fillRect(0,0,W,820);
 /* 금색 경계선 */
 var gl=c.createLinearGradient(0,0,W,0);gl.addColorStop(0,'rgba(214,178,94,0)');gl.addColorStop(.5,GOLD);gl.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=gl;c.fillRect(0,817,W,5);
 /* 상단 라벨(좌우 대칭 장식선) */
 T(c,'STOCK ANALYSIS REPORT',540,66,{s:19,w:700,c:GOLD,a:'center',ls:6});
 [[130,370],[710,950]].forEach(function(l){var q=c.createLinearGradient(l[0],0,l[1],0);q.addColorStop(0,'rgba(214,178,94,0)');q.addColorStop(.5,'rgba(214,178,94,.8)');q.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=q;c.fillRect(l[0],60,l[1]-l[0],2)});
 /* 종목명 + 시장·코드 */
 T(c,cur.name||'',540,152,{s:78,w:900,c:'#ffffff',a:'center',max:900});
 var mk=(cur.market||'')+'  ·  '+(cur.ticker||'');c.save();c.font='700 22px '+FONT;var mw=c.measureText(mk).width+44;c.restore();
 K.rr(c,540-mw/2,176,mw,38,19);c.strokeStyle='rgba(214,178,94,.7)';c.lineWidth=1.5;c.stroke();T(c,mk,540,202,{s:22,w:700,c:GOLD2,a:'center'});
 /* 현재가 + 등락 (한 줄 가운데 정렬) */
 var pr=p.price!=null?N(p.price)+'원':'-',dp=p.day_pct,dc=dp>0?'#ff7b8f':(dp<0?'#7fb2ff':'#cbd5e1'),ds=dp==null?'':((dp>0?'▲ ':(dp<0?'▼ ':''))+SG(Math.abs(dp),2).replace('+','')+'%');
 c.save();c.font='900 52px '+FONT;var w1=c.measureText(pr).width;c.font='800 32px '+FONT;var w2=ds?c.measureText(ds).width:0;c.restore();var gap=ds?26:0,x0=540-(w1+gap+w2)/2;
 T(c,pr,x0,282,{s:52,w:900,c:'#fff'});if(ds)T(c,ds,x0+w1+gap,280,{s:32,w:800,c:dc});
 T(c,'데이터 기준 '+(cur.as_of||today()),540,320,{s:18,w:500,c:'rgba(203,213,225,.75)',a:'center'});
 /* 게이지 — 가운데 */
 var cx=540,cy=585,R=218,total=Number(sc.total)||0,col=scColDark(total),N_T=60;
 c.save();c.lineCap='round';
 c.strokeStyle='rgba(214,178,94,.55)';c.lineWidth=2;c.beginPath();c.arc(cx,cy,R+22,Math.PI,2*Math.PI);c.stroke();
 c.strokeStyle='rgba(214,178,94,.22)';c.lineWidth=1.5;c.beginPath();c.arc(cx,cy,R-62,Math.PI,2*Math.PI);c.stroke();
 for(var i=0;i<N_T;i++){var fr=i/(N_T-1),a=Math.PI+fr*Math.PI,lit=fr*100<=total+0.01;c.beginPath();
  c.moveTo(cx+(R-30)*Math.cos(a),cy+(R-30)*Math.sin(a));c.lineTo(cx+R*Math.cos(a),cy+R*Math.sin(a));c.lineWidth=lit?7:5;
  c.strokeStyle=lit?'hsl('+Math.round(fr*135)+',85%,'+(54+fr*8)+'%)':'rgba(255,255,255,.13)';c.stroke()}
 c.restore();
 /* 끝점 광택 */
 var ea=Math.PI+Math.min(total,100)/100*Math.PI,ex=cx+(R+11)*Math.cos(ea),ey=cy+(R+11)*Math.sin(ea),eg=c.createRadialGradient(ex,ey,1,ex,ey,22);eg.addColorStop(0,'#ffffff');eg.addColorStop(.35,col);eg.addColorStop(1,'rgba(255,255,255,0)');c.fillStyle=eg;c.beginPath();c.arc(ex,ey,22,0,7);c.fill();
 T(c,'0',cx-R+3,cy+36,{s:18,w:600,c:'rgba(203,213,225,.7)',a:'center'});T(c,'100',cx+R-3,cy+36,{s:18,w:600,c:'rgba(203,213,225,.7)',a:'center'});
 T(c,'종합 점수',cx,cy-150,{s:22,w:700,c:GOLD,a:'center',ls:3});
 /* 점수 숫자: 금빛 그라데이션 */
 c.save();c.font='900 150px '+FONT;c.textAlign='center';var ng=c.createLinearGradient(0,cy-150,0,cy-10);ng.addColorStop(0,'#ffffff');ng.addColorStop(1,GOLD2);c.fillStyle=ng;c.shadowColor='rgba(214,178,94,.55)';c.shadowBlur=26;c.fillText(String(total),cx,cy-18);c.restore();
 /* 등급 알약 + 한 줄 진단 */
 var gt=gradeText(sc.grade),pw=300,pg=c.createLinearGradient(cx-pw/2,0,cx+pw/2,0);pg.addColorStop(0,'#c9a24b');pg.addColorStop(.5,'#f6e7b4');pg.addColorStop(1,'#c9a24b');
 c.save();c.shadowColor='rgba(0,0,0,.35)';c.shadowBlur=14;c.shadowOffsetY=4;K.rr(c,cx-pw/2,cy+58,pw,58,29);c.fillStyle=pg;c.fill();c.restore();T(c,gt,cx,cy+96,{s:28,w:900,c:NAVY0,a:'center'});
 var hl=headline(ext);if(hl){var ls=K.wrap(c,hl,820,'600 28px '+FONT);ls.slice(0,2).forEach(function(l,i){T(c,l,cx,cy+166+i*38,{s:28,w:600,c:'rgba(255,255,255,.92)',a:'center'})})}
 /* 좌우 보조 지표 (대칭) */
 var L=[['시가총액',d.market_cap&&d.market_cap!=='N/A'?d.market_cap:'-'],['PER',f.PER!=null?N(f.PER,1)+'배':'-'],['PBR',f.PBR!=null?N(f.PBR,2)+'배':'-']];
 var Rr=[['RSI(14)',p.rsi!=null?N(p.rsi,1):'-'],['52주 위치',p.pos52!=null?N(p.pos52,0)+'%':'-'],['거래량 배수',p.vol_ratio!=null?N(p.vol_ratio,1)+'배':'-']];
 function flank(items,x,w){items.forEach(function(it,i){var y=360+i*104;c.save();K.rr(c,x,y,w,88,16);c.fillStyle='rgba(255,255,255,.07)';c.fill();c.strokeStyle='rgba(214,178,94,.38)';c.lineWidth=1.5;c.stroke();c.restore();
  T(c,it[0],x+w/2,y+32,{s:19,w:600,c:'rgba(246,231,180,.85)',a:'center'});T(c,it[1],x+w/2,y+68,{s:32,w:800,c:'#fff',a:'center',max:w-24})})}
 flank(L,40,236);flank(Rr,804,236);
 /* 5축 카드 */
 shadowCard(c,40,850,1000,384,26);
 T(c,'5축 종합 진단',540,896,{s:30,w:900,c:INK,a:'center'});var uw=c.createLinearGradient(440,0,640,0);uw.addColorStop(0,'rgba(214,178,94,0)');uw.addColorStop(.5,GOLD);uw.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=uw;c.fillRect(440,908,200,3);
 c.fillStyle='#eceff4';c.fillRect(540,940,1.5,250);
 var ax=sc.axes||[],n=ax.length;
 if(n>=3){var rcx=290,rcy=1060,RR=92;
  for(var gi=1;gi<=5;gi++){c.beginPath();for(var j=0;j<n;j++){var aa=-Math.PI/2+2*Math.PI*j/n;var xx=rcx+RR*gi/5*Math.cos(aa),yy=rcy+RR*gi/5*Math.sin(aa);j?c.lineTo(xx,yy):c.moveTo(xx,yy)}c.closePath();c.strokeStyle=gi===5?'rgba(100,116,139,.45)':'rgba(148,163,184,.25)';c.lineWidth=gi===5?1.6:1;c.stroke()}
  for(var j2=0;j2<n;j2++){var a2=-Math.PI/2+2*Math.PI*j2/n;c.beginPath();c.moveTo(rcx,rcy);c.lineTo(rcx+RR*Math.cos(a2),rcy+RR*Math.sin(a2));c.strokeStyle='rgba(148,163,184,.35)';c.lineWidth=1;c.stroke()}
  c.beginPath();ax.forEach(function(a,j){var aa=-Math.PI/2+2*Math.PI*j/n,r=RR*Math.max(0,Math.min(100,a.score||0))/100,xx=rcx+r*Math.cos(aa),yy=rcy+r*Math.sin(aa);j?c.lineTo(xx,yy):c.moveTo(xx,yy)});c.closePath();
  var rf=c.createRadialGradient(rcx,rcy,5,rcx,rcy,RR);rf.addColorStop(0,'rgba(214,178,94,.38)');rf.addColorStop(1,'rgba(37,99,235,.22)');c.fillStyle=rf;c.fill();c.strokeStyle='#1e3a8a';c.lineWidth=3;c.lineJoin='round';c.stroke();
  ax.forEach(function(a,j){var aa=-Math.PI/2+2*Math.PI*j/n,r=RR*Math.max(0,Math.min(100,a.score||0))/100,xx=rcx+r*Math.cos(aa),yy=rcy+r*Math.sin(aa),cl=AXC[a.key]||'#2563eb';
   c.beginPath();c.arc(xx,yy,7,0,7);c.fillStyle=cl;c.fill();c.strokeStyle='#fff';c.lineWidth=2.5;c.stroke();
   var lx=rcx+(RR+30)*Math.cos(aa),ly=rcy+(RR+30)*Math.sin(aa),co=Math.cos(aa),an=Math.abs(co)<.25?'center':(co>0?'left':'right');
   T(c,a.name,lx,ly+(Math.sin(aa)>0.5?14:(Math.sin(aa)<-.5?-4:4)),{s:21,w:800,c:cl,a:an})})}
 else T(c,'축 데이터가 부족해요',290,1060,{s:22,w:600,c:MUT,a:'center'});
 /* 오른쪽 점수 막대 — 카드 오른쪽 절반 안에서 가운데 정렬 */
 var bx=585,bw=420,by=946,step=Math.min(54,Math.floor(240/Math.max(n,1)));
 ax.forEach(function(a,i){var y=by+i*step,cl=AXC[a.key]||'#2563eb',s=a.score==null?0:a.score;
  T(c,a.name,bx,y+18,{s:23,w:800,c:INK});T(c,a.score==null?'-':String(a.score),bx+bw,y+19,{s:26,w:900,c:scCol(s),a:'right'});
  K.rr(c,bx,y+28,bw,12,6);c.fillStyle='#e8ebf1';c.fill();var bg=c.createLinearGradient(bx,0,bx+bw,0);bg.addColorStop(0,cl);bg.addColorStop(1,scCol(s));K.rr(c,bx,y+28,Math.max(12,bw*s/100),12,6);c.fillStyle=bg;c.fill()});
 T(c,'기술 22% · 모멘텀 18% · 수급 26% · 재무 22% · 밸류 12% 가중 평균(없는 항목 제외) · 참고용 지표',540,1216,{s:15,w:500,c:'#94a3b8',a:'center'});
 /* 하단 3카드 */
 var vp=p.vp||{},sp=ext&&ext.supply&&ext.supply.per&&ext.supply.per['5'],fa=lastActual(d.financials);
 var cards=[['매물대 (지지·저항)',[['VAH 저항',vp.vah!=null?N(vp.vah)+'원':'-',UP],['POC 핵심',vp.poc!=null?N(vp.poc)+'원':'-',INK],['VAL 지지',vp.val!=null?N(vp.val)+'원':'-',DN]],vp.va_pos?('현재가: '+vp.va_pos):''],
  ['수급 (최근 5일, 억원)',sp?[['외국인',SG(sp.foreign_eok,0),sp.foreign_eok>0?UP:(sp.foreign_eok<0?DN:INK)],['기관',SG(sp.inst_eok,0),sp.inst_eok>0?UP:(sp.inst_eok<0?DN:INK)],['개인',SG(sp.indiv_eok,0),sp.indiv_eok>0?UP:(sp.indiv_eok<0?DN:INK)]]:[['외국인','-',INK],['기관','-',INK],['개인','-',INK]],'종가×순매수량 추정'],
  ['재무 ('+(fa?fa.title:'연간')+')',[['매출액',fa?eok(fa.rev):'-',INK],['영업이익',fa?eok(fa.op):'-',fa&&fa.op<0?DN:INK],['영업이익률',fa&&fa.opm!=null?N(fa.opm,1)+'%':'-',fa&&fa.opm<0?DN:INK]],'네이버증권 연간 실적']];
 cards.forEach(function(cd,i){var x=40+i*342,w=316,y=1250;shadowCard(c,x,y,w,230,22);
  c.fillStyle=GOLD;K.rr(c,x+22,y+22,5,26,3);c.fill();T(c,cd[0],x+38,y+43,{s:21,w:800,c:INK,max:w-56});
  cd[1].forEach(function(r,j){var yy=y+90+j*42;T(c,r[0],x+26,yy,{s:19,w:600,c:MUT});T(c,r[1],x+w-26,yy,{s:25,w:800,c:r[2],a:'right',max:w-120})});
  if(cd[2])T(c,cd[2],x+w/2,y+212,{s:15,w:500,c:'#94a3b8',a:'center',max:w-30})});
 /* 푸터 */
 var fg=c.createLinearGradient(0,0,W,0);fg.addColorStop(0,'rgba(214,178,94,0)');fg.addColorStop(.5,GOLD);fg.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=fg;c.fillRect(100,1508,880,2);
 T(c,'본 이미지는 공개 데이터를 정리한 참고 자료이며 특정 종목의 매수·매도를 권유하지 않습니다. 투자 판단과 책임은 투자자 본인에게 있습니다.',540,1534,{s:15,w:500,c:'#7b8494',a:'center'});
 return m.cv}

/* ═════════ ② 통합 이미지 ═════════ */
function panelBox(c,y,h,title,sub){shadowCard(c,40,y,1000,h,24);c.fillStyle=GOLD;K.rr(c,66,y+26,6,30,3);c.fill();T(c,title,86,y+50,{s:26,w:900,c:INK});if(sub)T(c,sub,1014,y+49,{s:16,w:500,c:'#94a3b8',a:'right'})}
function drawCombo(cur,ext,scale){
 var p=cur.price||{},f=cur.fundamentals||{},d=cur.details||{},ch=p.chart,peers=(d.peers||[]).slice(0,6);
 var HEAD=190,A=600,B=420,Cc=112+(peers.length+1)*46+(d.consensus&&d.consensus.target_price?44:0),D=500,FOOT=90,GAP=26;
 var W=1080,H=HEAD+GAP+A+GAP+B+GAP+Cc+GAP+D+GAP+FOOT,m=K.make(W,H,scale),c=m.c;
 c.fillStyle=PAPER;c.fillRect(0,0,W,H);
 var g=c.createLinearGradient(0,0,0,HEAD);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,HEAD);
 var gl=c.createLinearGradient(0,0,W,0);gl.addColorStop(0,'rgba(214,178,94,0)');gl.addColorStop(.5,GOLD);gl.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=gl;c.fillRect(0,HEAD-3,W,4);
 T(c,'INTEGRATED CHART REPORT',540,44,{s:16,w:700,c:GOLD,a:'center',ls:5});
 T(c,(cur.name||'')+'  '+(cur.ticker||''),540,104,{s:50,w:900,c:'#fff',a:'center',max:900});
 var dp=p.day_pct,dc=dp>0?'#ff7b8f':(dp<0?'#7fb2ff':'#cbd5e1');
 var line=(p.price!=null?N(p.price)+'원':'-'),chg=dp==null?'':('  '+(dp>0?'▲ ':(dp<0?'▼ ':''))+Math.abs(dp).toFixed(2)+'%');
 c.save();c.font='800 30px '+FONT;var lw=c.measureText(line).width;c.font='700 24px '+FONT;var cw=chg?c.measureText(chg).width:0;c.restore();var x0=540-(lw+cw)/2;
 T(c,line,x0,150,{s:30,w:800,c:'#fff'});if(chg)T(c,chg,x0+lw,149,{s:24,w:700,c:dc});
 T(c,(cur.market||'')+' · 데이터 기준 '+(cur.as_of||today()),540,176,{s:15,w:500,c:'rgba(203,213,225,.75)',a:'center'});
 var y=HEAD+GAP;
 /* A. 주가 차트 */
 panelBox(c,y,A,'주가 차트','일봉 · 이동평균 · 매물대');
 (function(){var X0=112,X1=1000,XC=868,PY0=y+110,PY1=y+420,VY0=y+440,VY1=y+520;
  if(!ch||!ch.dates||!ch.dates.length){T(c,'차트 데이터가 없어요',540,y+300,{s:22,w:600,c:MUT,a:'center'});return}
  var n0=ch.dates.length,k=Math.min(90,n0),s0=n0-k,xs=function(i){return X0+(XC-X0)*(i+.5)/k};
  var hi=-1e18,lo=1e18;for(var i=s0;i<n0;i++){if(ch.high[i]!=null)hi=Math.max(hi,ch.high[i]);if(ch.low[i]!=null)lo=Math.min(lo,ch.low[i]);[ch.ma5,ch.ma20,ch.ma60].forEach(function(a){if(a&&a[i]!=null){hi=Math.max(hi,a[i]);lo=Math.min(lo,a[i])}})}
  var vp=p.vp||{};[vp.vah,vp.poc,vp.val].forEach(function(v){if(v!=null&&v<hi*1.25&&v>lo*0.75){hi=Math.max(hi,v);lo=Math.min(lo,v)}});
  var pad=(hi-lo)*.06;hi+=pad;lo-=pad;var ys=function(v){return PY1-(PY1-PY0)*(v-lo)/(hi-lo)};
  c.font='500 14px '+FONT;
  for(var gi=0;gi<=5;gi++){var gv=lo+(hi-lo)*gi/5,gy=ys(gv);c.strokeStyle='#eef1f6';c.lineWidth=1;c.beginPath();c.moveTo(X0,gy);c.lineTo(X1,gy);c.stroke();T(c,N(gv),X0-8,gy+5,{s:14,w:500,c:'#94a3b8',a:'right'})}
  /* 범례 */
  var lg=[['MA5','#f59e0b'],['MA20','#2563eb'],['MA60','#16a34a'],['VAH','#e11d48'],['POC','#8993a4'],['VAL','#2563eb']],lx=X0;
  lg.forEach(function(l){c.fillStyle=l[1];c.fillRect(lx,y+84,18,4);T(c,l[0],lx+24,y+90,{s:14,w:700,c:MUT});lx+=82});
  var bw=Math.max(2,(XC-X0)/k*.62);
  for(var i2=s0;i2<n0;i2++){var o=ch.open[i2],h=ch.high[i2],l=ch.low[i2],cl=ch.close[i2];if(o==null||cl==null)continue;var up=cl>=o,col=up?UP:DN,x=xs(i2-s0);
   c.strokeStyle=col;c.lineWidth=1.4;c.beginPath();c.moveTo(x,ys(h));c.lineTo(x,ys(l));c.stroke();var yt=ys(Math.max(o,cl)),yb=ys(Math.min(o,cl));c.fillStyle=col;c.fillRect(x-bw/2,yt,bw,Math.max(1.5,yb-yt))}
  [['ma5','#f59e0b'],['ma20','#2563eb'],['ma60','#16a34a']].forEach(function(z){var a=ch[z[0]];if(!a)return;c.beginPath();var st=false;for(var i3=s0;i3<n0;i3++){if(a[i3]==null)continue;var x=xs(i3-s0),yy=ys(a[i3]);st?c.lineTo(x,yy):c.moveTo(x,yy);st=true}c.strokeStyle=z[1];c.lineWidth=2.2;c.lineJoin='round';c.stroke()});
  [[vp.vah,'#e11d48','VAH '+N(vp.vah),[7,6]],[vp.poc,'#8993a4','POC '+N(vp.poc),[]],[vp.val,'#2563eb','VAL '+N(vp.val),[7,6]]].forEach(function(z){if(z[0]==null||z[0]>hi||z[0]<lo)return;var yy=ys(z[0]);c.save();c.setLineDash(z[3]);c.strokeStyle=z[1];c.lineWidth=1.6;c.beginPath();c.moveTo(X0,yy);c.lineTo(X1,yy);c.stroke();c.restore();
   c.save();c.font='700 14px '+FONT;var tw=c.measureText(z[2]).width+14;c.restore();K.rr(c,XC+14,yy-11,tw,22,6);c.fillStyle=z[1];c.fill();T(c,z[2],XC+14+tw/2,yy+5,{s:14,w:700,c:'#fff',a:'center'})});
  /* 거래량 */
  var vm=0;for(var i4=s0;i4<n0;i4++)vm=Math.max(vm,ch.volume[i4]||0);
  for(var i5=s0;i5<n0;i5++){var v=ch.volume[i5]||0,up2=ch.close[i5]>=ch.open[i5],hh=(VY1-VY0)*v/(vm||1);c.fillStyle=up2?'rgba(225,29,72,.35)':'rgba(37,99,235,.35)';c.fillRect(xs(i5-s0)-bw/2,VY1-hh,bw,hh)}
  T(c,'거래량',X0-8,VY0+12,{s:13,w:600,c:'#94a3b8',a:'right'});
  [0,Math.floor(k/2),k-1].forEach(function(ii,j){T(c,ch.dates[s0+ii].slice(2),xs(ii),VY1+28,{s:14,w:500,c:'#94a3b8',a:j===0?'left':(j===2?'right':'center')})});
  var last=ch.close[n0-1];T(c,'최근 '+k+'거래일 · 종가 '+N(last)+'원',540,y+A-26,{s:16,w:500,c:MUT,a:'center'})})();
 y+=A+GAP;
 /* B. 재무 차트 */
 panelBox(c,y,B,'재무 차트','연간 · 억원 · (E)=컨센서스 추정');
 (function(){var a=d.financials&&d.financials.annual;if(!a||!a.periods||!a.periods.length){T(c,'재무 데이터가 없어요',540,y+B/2,{s:22,w:600,c:MUT,a:'center'});return}
  var P=a.periods.slice(-5),off=a.periods.length-P.length;function row(nm){var r=(a.rows||[]).filter(function(z){return z.name===nm})[0];return r?r.values.slice(off):[]}
  var rev=row('매출액'),op=row('영업이익'),opm=row('영업이익률'),X0=112,X1=1000,Y0=y+120,Y1=y+B-70,mx=0,mn=0;
  rev.concat(op).forEach(function(v){if(v!=null){mx=Math.max(mx,v);mn=Math.min(mn,v)}});if(mx<=0)mx=1;var ys=function(v){return Y1-(Y1-Y0)*(v-mn)/(mx-mn)},z0=ys(0);
  for(var gi=0;gi<=4;gi++){var gv=mn+(mx-mn)*gi/4,gy=ys(gv);c.strokeStyle='#eef1f6';c.lineWidth=1;c.beginPath();c.moveTo(X0,gy);c.lineTo(X1,gy);c.stroke();T(c,eok(gv),X0-8,gy+5,{s:13,w:500,c:'#94a3b8',a:'right'})}
  var cw=(X1-X0)/P.length,bw=Math.min(62,cw*.28);
  [['매출액','#94a3b8'],['영업이익',NAVY1],['영업이익률(%)',UP]].forEach(function(l,i){c.fillStyle=l[1];c.fillRect(X0+i*150,y+80,18,8);T(c,l[0],X0+i*150+24,y+90,{s:14,w:700,c:MUT})});
  var pts=[];
  P.forEach(function(pp,i){var cx=X0+cw*(i+.5),est=pp.estimate;
   [[rev[i],'#94a3b8',-bw-3],[op[i],NAVY1,3]].forEach(function(z){var v=z[0];if(v==null)return;var yy=ys(v);c.save();c.globalAlpha=est?.5:1;c.fillStyle=z[1];K.rr(c,cx+z[2],Math.min(yy,z0),bw,Math.max(2,Math.abs(z0-yy)),4);c.fill();c.restore();T(c,eok(v),cx+z[2]+bw/2,(v>=0?yy-7:yy+17),{s:13,w:700,c:v<0?DN:INK,a:'center'})});
   T(c,pp.title+(est?'(E)':''),cx,Y1+30,{s:15,w:700,c:est?'#94a3b8':INK,a:'center'});if(opm[i]!=null)pts.push([cx,opm[i]])});
  if(pts.length){var om=0,on=0;pts.forEach(function(q){om=Math.max(om,q[1]);on=Math.min(on,q[1])});if(om<=on)om=on+1;var oy=function(v){return Y0+30+(Y1-Y0-70)*(1-(v-on)/(om-on))};
   c.beginPath();pts.forEach(function(q,i){var yy=oy(q[1]);i?c.lineTo(q[0],yy):c.moveTo(q[0],yy)});c.strokeStyle=UP;c.lineWidth=3;c.lineJoin='round';c.stroke();
   pts.forEach(function(q){var yy=oy(q[1]);c.beginPath();c.arc(q[0],yy,6,0,7);c.fillStyle='#fff';c.fill();c.strokeStyle=UP;c.lineWidth=3;c.stroke();T(c,N(q[1],1)+'%',q[0],yy-14,{s:14,w:800,c:UP,a:'center',st:'#fff',sw:5})})}})();
 y+=B+GAP;
 /* C. 동일업종 비교 */
 panelBox(c,y,Cc,'동일업종 비교','등락률 기준 · 네이버 동일업종');
 (function(){var rows=[{name:cur.name,price:p.price,day_pct:p.day_pct,me:1}].concat(peers);if(rows.length<2&&!(f.sector_PER)){T(c,'동일업종 자료가 없어요',540,y+Cc/2,{s:22,w:600,c:MUT,a:'center'});return}
  var mx=3;rows.forEach(function(r){if(r.day_pct!=null)mx=Math.max(mx,Math.abs(r.day_pct))});mx=Math.ceil(mx);
  var AX=560,HW=190,y0=y+84;c.fillStyle='#dfe3ea';c.fillRect(AX-1,y0-8,2,rows.length*46);
  rows.forEach(function(r,i){var yy=y0+i*46;if(r.me){K.rr(c,58,yy-6,964,40,10);c.fillStyle='rgba(214,178,94,.16)';c.fill()}
   T(c,r.name||'',78,yy+21,{s:21,w:r.me?900:600,c:INK,max:200});
   var v=r.day_pct;if(v!=null){var bw=Math.max(3,HW*Math.abs(v)/mx),col=v>0?UP:(v<0?DN:'#94a3b8');c.fillStyle=col;K.rr(c,v>=0?AX:AX-bw,yy+2,bw,24,5);c.fill();T(c,SG(v,2)+'%',v>=0?AX+bw+10:AX-bw-10,yy+21,{s:18,w:800,c:col,a:v>=0?'left':'right'})}
   T(c,r.price!=null?N(r.price)+'원':'-',1004,yy+21,{s:19,w:600,c:MUT,a:'right'})});
  var by=y0+rows.length*46+4,cs=d.consensus;
  if(cs&&cs.target_price){var gap=p.price?(cs.target_price/p.price-1)*100:null;T(c,'증권사 목표주가 평균 '+N(cs.target_price)+'원'+(gap!=null?'  (현재가 대비 '+SG(gap,1)+'%)':'')+(cs.date?'  · '+cs.date+' 기준':''),540,by+22,{s:18,w:700,c:'#92400e',a:'center',max:900})}})();
 y+=Cc+GAP;
 /* D. 기술적 지표 */
 panelBox(c,y,D,'기술적 지표','참고용 · 투자 권유 아님');
 (function(){var rsi=p.rsi,cells=[],last=function(a){return a&&a.length?a[a.length-1]:null};
  var cA=last(ch&&ch.senkou_a?ch.senkou_a.slice(0,ch.dates.length):null),cB=last(ch&&ch.senkou_b?ch.senkou_b.slice(0,ch.dates.length):null),px=p.price,ich='-',ichC=INK;
  if(cA!=null&&cB!=null&&px!=null){var top=Math.max(cA,cB),bot=Math.min(cA,cB);if(px>top){ich='구름 위 (강세 영역)';ichC=UP}else if(px<bot){ich='구름 아래 (약세 영역)';ichC=DN}else{ich='구름 안 (방향 탐색)';ichC='#b45309'}}
  var al=p.ma_align;
  cells=[{t:'RSI(14)',v:rsi!=null?N(rsi,1):'-',s:rsi==null?'':(rsi>=70?'과매수 구간':(rsi<=30?'과매도 구간':'중립 구간')),c:rsi>=70?UP:(rsi<=30?DN:INK),bar:rsi!=null?{v:rsi,min:0,max:100,z:[30,70]}:null},
   {t:'이동평균 배열',v:al||'-',s:'MA5 '+N(last(ch&&ch.ma5))+' · MA20 '+N(last(ch&&ch.ma20))+' · MA60 '+N(last(ch&&ch.ma60)),c:al==='정배열'?UP:(al==='역배열'?DN:INK)},
   {t:'거래량 배수',v:p.vol_ratio!=null?N(p.vol_ratio,1)+'배':'-',s:'20일 평균 대비',c:p.vol_ratio>=2?'#b45309':INK,bar:p.vol_ratio!=null?{v:Math.min(p.vol_ratio,4),min:0,max:4,z:[]}:null},
   {t:'52주 위치',v:p.pos52!=null?N(p.pos52,0)+'%':'-',s:'최저 '+N(p.low_52w)+' ~ 최고 '+N(p.high_52w),c:INK,bar:p.pos52!=null?{v:p.pos52,min:0,max:100,z:[]}:null},
   {t:'20일선 이격도',v:p.ma20_diff!=null?SG(p.ma20_diff,1)+'%':'-',s:p.ma20_diff>=10?'단기 과열 주의':(p.ma20_diff<=-10?'단기 낙폭 과대':'보통 범위'),c:p.ma20_diff>0?UP:(p.ma20_diff<0?DN:INK)},
   {t:'5일 / 20일 등락률',v:(p.pct5!=null?SG(p.pct5,1)+'%':'-')+' / '+(p.pct20!=null?SG(p.pct20,1)+'%':'-'),s:'단기 · 중기 흐름',c:p.pct20>0?UP:(p.pct20<0?DN:INK)},
   {t:'일목균형표',v:ich,s:'현재가와 구름대 비교',c:ichC,small:1},
   {t:'변동성 (볼린저)',v:p.bb_squeeze?'수축(스퀴즈)':'보통',s:p.bb_squeeze?'방향성 돌파 전조일 수 있음':'특이 신호 없음',c:p.bb_squeeze?'#b45309':INK}];
  cells.forEach(function(z,i){var col=i%2,rw=Math.floor(i/2),x=66+col*486,yy=y+82+rw*98,w=462,h=84;K.rr(c,x,yy,w,h,14);c.fillStyle='#f7f8fb';c.fill();c.strokeStyle='#e5e8ef';c.lineWidth=1;c.stroke();
   T(c,z.t,x+18,yy+28,{s:17,w:700,c:MUT});T(c,z.v,x+w-18,yy+36,{s:z.small?21:30,w:900,c:z.c,a:'right',max:230});
   if(z.bar){var bx=x+18,bw=w-36,by=yy+50;K.rr(c,bx,by,bw,10,5);c.fillStyle='#e3e7ee';c.fill();(z.bar.z||[]).forEach(function(q){c.fillStyle='rgba(100,116,139,.6)';c.fillRect(bx+bw*(q-z.bar.min)/(z.bar.max-z.bar.min)-1,by-3,2,16)});
    var fx=bw*(z.bar.v-z.bar.min)/(z.bar.max-z.bar.min);var gg=c.createLinearGradient(bx,0,bx+bw,0);gg.addColorStop(0,DN);gg.addColorStop(.5,GOLD);gg.addColorStop(1,UP);K.rr(c,bx,by,Math.max(10,fx),10,5);c.fillStyle=gg;c.fill();c.beginPath();c.arc(bx+Math.max(5,fx),by+5,8,0,7);c.fillStyle='#fff';c.fill();c.strokeStyle=INK;c.lineWidth=2.5;c.stroke();
    T(c,z.s,x+w-18,yy+76,{s:13,w:500,c:'#94a3b8',a:'right',max:w-36})}
   else T(c,z.s,x+18,yy+68,{s:15,w:500,c:'#94a3b8',max:w-36})})})();
 y+=D+GAP;
 var fg=c.createLinearGradient(0,0,W,0);fg.addColorStop(0,'rgba(214,178,94,0)');fg.addColorStop(.5,GOLD);fg.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=fg;c.fillRect(100,y+6,880,2);
 T(c,'공개 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다 · 데이터: 네이버증권 · 종목분석 미니',540,y+44,{s:15,w:500,c:'#7b8494',a:'center'});
 return m.cv}

K.stock={drawMain:drawMain,drawCombo:drawCombo,
 build:function(cur,ext,scale){return [{idx:1,label:'메인 분석 이미지',canvas:drawMain(cur,ext,scale)},{idx:2,label:'통합 이미지 (차트·재무·업종·지표)',canvas:drawCombo(cur,ext,scale)}]}};
})();
"""

# ══════════════════════════════════════════════════════════════
# 관리자 탭 — 이미지 저장 설정
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var IK={cfg:null};
function ikLoad(p){p.innerHTML='';var top=el('div','c');top.appendChild(el('b',null,'🖼 이미지 저장 설정'));
 top.appendChild(el('p','note','블로그에 올릴 분석 이미지를 어디에·어떻게 저장할지 정해요. 저장 위치는 [지정 폴더]/날짜(20261002)/메뉴 폴더(종목분석)/① 종목명_종목코드.png 형태로 자동 정리됩니다. 폴더·자동/수동 모드는 이 기기(이 브라우저)에만 저장돼요.'));p.appendChild(top);
 var fc=el('div','c');fc.id='ikFolder';p.appendChild(fc);var mc=el('div','c');mc.id='ikMode';p.appendChild(mc);var nc=el('div','c');nc.id='ikNames';p.appendChild(nc);
 window.ImgKit.loadCfg(true).then(function(c){IK.cfg=JSON.parse(JSON.stringify(c));ikDraw()})}
function ikDraw(){ikFolder();ikMode();ikNames()}
function ikFolder(){var b=$('ikFolder');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'📁 다운로드 폴더'));
 var dg=el('p','note','브라우저 점검: 폴더 선택 기능 '+(window.ImgKit.supported?'✅ 사용 가능':'❌ 지원 안 함')+' · 보안 연결(https) '+(window.isSecureContext?'✅':'❌')+' · 이 창 '+(window.top===window?'✅ 단독 창':'⚠ 다른 화면 안에 들어 있음'));b.appendChild(dg);
 if(!window.ImgKit.supported){b.appendChild(el('p','note bad','이 브라우저는 폴더 지정을 지원하지 않아요. 데스크톱 크롬·엣지를 쓰시면 폴더를 지정할 수 있고, 지금은 일반 다운로드 폴더에 저장됩니다(파일 이름은 ① 종목명_코드.png 로 같아요).'));return}
 window.ImgKit.info().then(function(i){var s=el('p','m');
  if(!i.name)s.textContent='아직 폴더를 지정하지 않았어요 → 브라우저 기본 다운로드 폴더에 저장됩니다.';
  else s.textContent='지정된 폴더: '+i.name+(i.perm==='granted'?' · ✅ 접근 허용됨':' · 🔒 이 세션에서 접근 허용이 필요해요(저장할 때 한 번 물어봐요)');
  b.appendChild(s);var r=el('div','bar');
  r.appendChild(bt('📁 폴더 지정하기','bt',function(){var ee=$('ikErr');if(ee)ee.remove();window.ImgKit.pick().then(function(h){toast('폴더를 지정했어요: '+(h.name||'선택한 폴더'));ikFolder()}).catch(function(e){var m=(e&&e.message)||'폴더를 지정하지 못했어요';toast(m);if(e&&e.name==='AbortError')return;var x=el('div','note bad','⚠ '+m);x.id='ikErr';b.appendChild(x)})}));
  if(i.name&&i.perm!=='granted')r.appendChild(bt('🔓 접근 허용','bt2',function(){window.ImgKit.perm(i.h,true).then(function(ok){toast(ok?'허용했어요':'허용되지 않았어요');ikFolder()})}));
  if(i.name)r.appendChild(bt('폴더 지정 해제','bt3',function(){window.ImgKit.forget().then(function(){toast('해제했어요');ikFolder()})}));
  r.appendChild(bt('🧪 시험 저장','bt2',function(){var cv=document.createElement('canvas');cv.width=480;cv.height=160;var c=cv.getContext('2d');c.fillStyle='#16275a';c.fillRect(0,0,480,160);c.fillStyle='#f6e7b4';c.font='700 26px sans-serif';c.fillText('저장 시험 이미지',40,70);c.font='16px sans-serif';c.fillText(new Date().toLocaleString('ko-KR'),40,110);
   window.ImgKit.toBlob(cv).then(function(bl){return window.ImgKit.save(bl,{menu:'stock',idx:1,name:'시험',ticker:'000000'})}).then(function(x){toast(x.where==='folder'?('저장했어요: '+x.path):((x.note||'다운로드 폴더에 저장했어요')))})}));
  b.appendChild(r);b.appendChild(el('p','note','💡 폴더를 고를 때 주의: 크롬은 "다운로드", "문서", "바탕 화면" 폴더 자체를 고르게 해 주지 않아요. 문서나 다운로드 폴더 안에 새 폴더(예: 블로그이미지)를 만들어서 그 폴더를 선택하세요.'));b.appendChild(el('p','note','※ 보안상 브라우저는 폴더 접근 권한을 브라우저를 다시 열면 한 번씩 다시 물어봐요. 자동 저장 모드에서는 분석 화면에 [권한 허용] 버튼이 나타나고, 한 번 누르면 그 뒤로는 묻지 않습니다.'))})}
function ikMode(){var b=$('ikMode');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'⚙ 저장 방식 (이 기기)'));
 var cur=window.ImgKit.mode();[['manual','수동 저장 — 이미지를 확인한 뒤 [저장] 버튼을 눌러 저장'],['auto','자동 저장 — 관리자 분석실에서 이미지가 만들어지면 곧바로 폴더에 저장']].forEach(function(o){var l=el('label','bar');var i=el('input');i.type='radio';i.name='immode';i.checked=cur===o[0];i.onchange=function(){window.ImgKit.setMode(o[0]);toast('저장 방식: '+(o[0]==='auto'?'자동':'수동'))};l.appendChild(i);l.appendChild(el('span',null,' '+o[1]));b.appendChild(l)});
 var wh=window.ImgKit.when();b.appendChild(el('div','m','자동 저장 시점 (자동 저장일 때만 적용)'));[['ai','AI 분석·종합 리포트가 끝난 뒤 (권장 — 작업 순서대로)'],['analysis','종목을 분석한 직후 (AI 없이 바로)']].forEach(function(o){var l=el('label','bar');var i=el('input');i.type='radio';i.name='imwhen';i.checked=wh===o[0];i.onchange=function(){window.ImgKit.setWhen(o[0]);toast('자동 저장 시점을 바꿨어요')};l.appendChild(i);l.appendChild(el('span',null,' '+o[1]));b.appendChild(l)});
 b.appendChild(el('p','note','같은 날 같은 종목을 다시 저장하면 같은 이름의 파일을 덮어씁니다. 자동 저장이 아니어도 분석실의 [이미지 만들기] 단계에서 언제든 직접 저장할 수 있어요.'))}
function ikNames(){var b=$('ikNames');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'🗂 메뉴 폴더 이름 · 이미지 선명도 (모든 기기 공통)'));
 var C=IK.cfg,names={stock:'종목분석 (메인 분석 화면)',deep:'심층분석',daily:'오늘추천'};var tw=el('div');var t=el('table');
 Object.keys(C.folders).forEach(function(k){var tr=el('tr');tr.appendChild(el('td',null,names[k]||k));var td=el('td');var i=el('input');i.value=C.folders[k];i.maxLength=20;i.style.width='180px';i.oninput=function(){C.folders[k]=i.value};td.appendChild(i);tr.appendChild(td);t.appendChild(tr)});tw.appendChild(t);b.appendChild(tw);
 var r=el('div','bar');r.appendChild(el('span','m','이미지 선명도 '));var sel=el('select');[[1,'보통 (1080px)'],[1.5,'선명 (1620px)'],[2,'아주 선명 (2160px) — 권장'],[3,'최대 (3240px, 용량 큼)']].forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];if(Number(C.scale)===o[0])op.selected=true;sel.appendChild(op)});sel.onchange=function(){C.scale=Number(sel.value)};r.appendChild(sel);b.appendChild(r);
 var pv=el('p','note');b.appendChild(bt('💾 저장','bt',function(){apiJ('/admin/api/settings',{img_cfg:JSON.stringify(C)}).then(function(j){if(j.error){toast(j.error);return}window.ImgKit.loadCfg(true);toast('저장했어요')})}));
 pv.textContent='저장 예) 20261002/'+C.folders.stock+'/① 산일전기_062040.png , ② 산일전기_062040.png  (① 메인 이미지, ② 통합 이미지). 폴더 이름에는 \\ / : * ? " < > | 를 쓸 수 없어요.';b.appendChild(pv)}
"""


def register():
    C.register_settings({"img_cfg": json.dumps(DEFAULT_CFG, ensure_ascii=False)}, {"img_cfg": _valid_cfg})
    C.register_admin_lib(IMGKIT_JS + STOCK_JS)
    C.register_admin_tab("ik", "🖼 이미지 저장", TAB_JS, "ikLoad")
    return bp
