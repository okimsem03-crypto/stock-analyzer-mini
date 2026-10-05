"""🧭 메뉴 관리 (관리자 화면 탭) — 메뉴 목록, 보이기/숨김, 회원 단계별 노출, 메뉴 순서, 회원 단계(최대 10개) 구성.

규칙(본체 menu_visible 이 그대로 따른다)
  · 메뉴마다 [켜짐/숨김] 스위치 + 볼 수 있는 단계 체크(비회원, 그리고 관리자가 만든 회원 단계들).
  · '비회원' 체크 = 모든 사람에게 공개. 숨김이면 체크와 상관없이 관리자만 본다. 관리자는 항상 모두 본다.
  · 회원 단계는 관리자가 최대 10개까지 이름·설명·순서를 자유롭게 구성한다(위쪽이 낮은 단계).
  · 회원가입·로그인은 menu_member.py 가 맡는다(v146). 로그인한 회원은 본체 viewer_level() 로 자기 단계가 되고, 로그인 안 한 방문자는 '비회원'이다.
"""
import json
from flask import Blueprint, request
from menu_ctx import C

bp = Blueprint("menumgr", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "setting_set", "member_levels", "clean_levels", "menu_policy",
               "menu_policy_set", "menus_ordered")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)


def _state():
    levels = member_levels()
    menus = []
    gl = {g["id"]: g["icon"] + " " + g["label"] for g in C.MENU_GROUPS}
    for m in C.menus_grouped(menus_ordered()):
        on, tok = menu_policy(m["id"])
        menus.append({"group": C.menu_group(m), "group_label": gl.get(C.menu_group(m), ""), "id": m["id"], "icon": m["icon"], "label": m["label"], "desc": m.get("desc", ""), "on": bool(on),
                      "levels": ([C.GUEST] if C.GUEST in tok else []) + [x["id"] for x in levels if x["id"] in tok], "public_path": m["public_path"], "admin_path": m["admin_path"],
                      "preview_path": m.get("preview_path") or m["public_path"], "admin_only": bool(m.get("admin_only"))})
    return {"levels": levels, "max": C.MAX_MEMBER_LEVELS, "menus": menus, "guest": C.GUEST}


@bp.route("/admin/api/menumgr/state")
def api_state():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_state())


@bp.route("/admin/api/menumgr/save", methods=["POST"])
def api_save():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    levels = clean_levels(d.get("levels"))
    if levels is None:
        return _admin_json({"error": f"회원 단계가 올바르지 않아요(최대 {C.MAX_MEMBER_LEVELS}개, 이름 1~12자, 설명 60자 이하, < > & 따옴표 사용 불가)."}, 400)
    if len({x["name"] for x in levels}) != len(levels):
        return _admin_json({"error": "같은 이름의 회원 단계가 있어요."}, 400)
    known = {m["id"] for m in C.MENUS}
    valid = {x["id"] for x in levels} | {C.GUEST}
    items = d.get("menus")
    if not isinstance(items, list):
        return _admin_json({"error": "메뉴 목록이 올바르지 않아요."}, 400)
    plan = []
    for it in items:
        if not isinstance(it, dict) or it.get("id") not in known or not isinstance(it.get("levels", []), list):
            return _admin_json({"error": "알 수 없는 메뉴가 있어요."}, 400)
        plan.append((it["id"], bool(it.get("on")), {t for t in it.get("levels", []) if t in valid}))
    order = d.get("order", [])
    if not isinstance(order, list) or any(o not in known for o in order):
        return _admin_json({"error": "메뉴 순서가 올바르지 않아요."}, 400)
    C.setting_set("member_levels", json.dumps(levels, ensure_ascii=False))     # 단계를 먼저 저장해야 메뉴 규칙이 새 단계 기준으로 정리된다
    for mid, on, tok in plan:
        menu_policy_set(mid, on, tok)
    C.setting_set("menu_order", json.dumps(list(dict.fromkeys(order))))
    _alog("menu_manage", f"levels={len(levels)} menus={len(plan)} shown={sum(1 for p in plan if p[1])}")
    return _admin_json(_state())


def _tier_rank(on, tok, levels, admin_only=False):
    """공개 등급 순서: 0=누구나, 1=첫 회원 단계 이상, … , 99=관리자 전용(숨김 포함)."""
    if admin_only or not on or not tok:
        return 99
    if C.GUEST in tok:
        return 0
    ids = [x["id"] for x in levels]
    idx = [ids.index(t) for t in tok if t in ids]
    return 1 + min(idx) if idx else 99


def _badge(rank, levels):
    if rank == 0:
        return "누구나"
    if rank >= 99 or rank - 1 >= len(levels):
        return "관리자 전용"
    return levels[rank - 1]["name"] + " 이상"


@bp.route("/admin/api/workbench")
def api_workbench():
    """[v168] 관리자 '메뉴 작업대' — 공개 등급 순서(누구나 → 일반 → 정회원 → 우수 → 관리자 전용)로 정렬한 메뉴 목록과 기능 공개 요약."""
    deny = _admin_deny()
    if deny:
        return deny
    levels = member_levels()
    rows = []
    for i, m in enumerate(C.menus_grouped(menus_ordered())):
        on, tok = menu_policy(m["id"])
        rk = _tier_rank(on, tok, levels, bool(m.get("admin_only")))
        fs = [f for f in C.FEATURES if f["menu"] == m["id"]]
        cnt = {"all": 0, "member": 0, "admin": 0}
        for f in fs:
            frk = _tier_rank(True, C.feature_policy(m["id"], f["id"]), levels)
            if rk >= 99 or frk >= 99:
                cnt["admin"] += 1
            elif frk == 0 and rk == 0:
                cnt["all"] += 1
            else:
                cnt["member"] += 1
        rows.append({"id": m["id"], "tab": C.MENU_TAB.get(m["id"]) or "", "icon": m["icon"], "label": m["label"], "rank": rk, "badge": _badge(rk, levels),
                     "on": bool(on), "admin_only": bool(m.get("admin_only")), "public_path": m["public_path"], "feats": len(fs), "cnt": cnt, "_o": i})
    rows.sort(key=lambda r: (r["rank"], r["_o"]))
    for r in rows:
        r.pop("_o", None)
    return _admin_json({"items": rows, "levels": [{"id": x["id"], "name": x["name"]} for x in levels], "guest": C.GUEST})


JS = r"""
var MM={S:null,draft:null,dirty:false,q:''};
function mmClone(o){return JSON.parse(JSON.stringify(o))}
function mmLoad(p){api('/admin/api/menumgr/state').then(function(j){if(cur!=='mm'&&cur!=='pb')return;MM.S=j;MM.draft=mmClone(j);MM.dirty=false;mmDraw(p)})}
function mmFree(){var used={};MM.draft.levels.forEach(function(l){used[l.id]=1});for(var i=1;i<=10;i++){if(!used[String(i)])return String(i)}return null}
function mmDirty(p){MM.dirty=true;var b=$('mmsave');if(b){b.disabled=false;b.textContent='💾 저장 (변경사항 있음)'}}
function mmDraw(p){p.innerHTML='';var D=MM.draft;
 var top=el('div','c');
 var th=el('div','bar');th.appendChild(el('b',null,'🧭 메뉴 관리'));th.appendChild(el('span','m','메인 화면 메뉴 바에 누구에게 보일지 · 순서 · 회원 단계 (고친 뒤 [저장]을 눌러야 적용)'));var sv=bt('💾 저장','bt',function(){mmSave(p)});sv.id='mmsave';sv.textContent='💾 저장';sv.disabled=!MM.dirty;th.appendChild(sv);top.innerHTML='';top.appendChild(th);p.appendChild(top);
 // ── 회원 단계
 var lc=el('div','c');lc.appendChild(el('b',null,'👥 회원 단계 (최대 '+D.max+'단계)'));
 lc.firstChild.title='위쪽이 낮은 단계예요. 비회원은 항상 따로 있어요. 가입한 회원의 단계는 [👤 회원] 탭에서 바꿔요.';
 D.levels.forEach(function(l,i){var r=el('div','bar');r.appendChild(el('span','m',(i+1)+'단계'));
  var n=el('input');n.value=l.name;n.maxLength=12;n.placeholder='단계 이름';n.style.width='150px';n.oninput=function(){l.name=n.value;mmDirty(p)};r.appendChild(n);
  var d=el('input');d.value=l.desc||'';d.maxLength=60;d.placeholder='설명(선택)';d.style.width='260px';d.oninput=function(){l.desc=d.value;mmDirty(p)};r.appendChild(d);
  var up=bt('▲','bt3',function(){if(i>0){var t=D.levels[i-1];D.levels[i-1]=l;D.levels[i]=t;mmDirty(p);mmDraw(p)}});up.disabled=i===0;r.appendChild(up);
  var dn=bt('▼','bt3',function(){if(i<D.levels.length-1){var t=D.levels[i+1];D.levels[i+1]=l;D.levels[i]=t;mmDirty(p);mmDraw(p)}});dn.disabled=i===D.levels.length-1;r.appendChild(dn);
  r.appendChild(bt('🗑 삭제','bt3',function(){if(!confirm('"'+l.name+'" 단계를 지울까요? 이 단계에만 보이던 메뉴 설정에서도 빠집니다.'))return;D.levels.splice(i,1);D.menus.forEach(function(m){m.levels=m.levels.filter(function(t){return t!==l.id})});mmDirty(p);mmDraw(p)}));
  lc.appendChild(r)});
 var add=bt('+ 단계 추가','bt2',function(){var id=mmFree();if(!id){toast('최대 '+D.max+'단계까지예요');return}D.levels.push({id:id,name:'새 단계',desc:''});mmDirty(p);mmDraw(p)});add.disabled=D.levels.length>=D.max;lc.appendChild(add);
 lc.appendChild(el('span','m',' '+D.levels.length+' / '+D.max));p.appendChild(lc);
 // ── 메뉴 목록
 var mc=el('div','c');mc.appendChild(el('b',null,'📋 메뉴 목록 ('+D.menus.length+'개)'));
 var sb=el('input');sb.placeholder='메뉴 이름 검색';sb.value=MM.q;sb.style.width='160px';sb.oninput=function(){MM.q=sb.value;mmRows()};var mh=mc.firstChild;mh.title='✅ 켜짐 = 체크한 사람에게 보임 · 🙈 숨김 = 관리자만 보임 · "비회원"을 체크하면 모두에게 공개 · ▲▼로 같은 분류 안에서 순서 변경';mc.removeChild(mh);var mbar=el('div','bar');mbar.appendChild(mh);mbar.appendChild(el('span','m','✅ 켜짐=체크한 사람에게 보임 · 🙈 숨김=관리자만 · ▲▼ 순서'));mbar.appendChild(sb);mc.appendChild(mbar);
 var tw=el('div');tw.style.cssText='overflow-x:auto;margin-top:8px';var tb=el('div');tw.appendChild(tb);mc.appendChild(tw);p.appendChild(mc);
 function mmRows(){tb.innerHTML='';var t=el('table');var h=el('tr');['순서','분류','메뉴','상태','비회원'].concat(D.levels.map(function(l){return l.name})).concat(['열기']).forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
  var q=(MM.q||'').trim().toLowerCase();
  D.menus.forEach(function(m,i){if(q&&(m.label+' '+m.desc+' '+m.id).toLowerCase().indexOf(q)<0)return;var tr=el('tr');
   var o=el('td');var u=bt('▲','bt3',function(){if(i>0){var x=D.menus[i-1];D.menus[i-1]=m;D.menus[i]=x;mmDirty(p);mmDraw(p)}});u.disabled=i===0||D.menus[i-1].group!==m.group;var w=bt('▼','bt3',function(){if(i<D.menus.length-1){var x=D.menus[i+1];D.menus[i+1]=m;D.menus[i]=x;mmDirty(p);mmDraw(p)}});w.disabled=i===D.menus.length-1||D.menus[i+1].group!==m.group;o.appendChild(u);o.appendChild(w);tr.appendChild(o);
   tr.appendChild(el('td','m',m.group_label||''));
   var nm=el('td');nm.appendChild(el('b',null,m.icon+' '+m.label));var nd=el('div','m',m.desc||'');nd.title=m.desc||'';nd.style.cssText='max-width:360px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';nm.appendChild(nd);tr.appendChild(nm);
   var st=el('td');if(m.admin_only){st.appendChild(el('span','m','🔒 관리자 전용'))}else{var tg=bt(m.on?'✅ 켜짐':'🙈 숨김',m.on?'bt':'bt3',function(){m.on=!m.on;mmDirty(p);mmDraw(p)});st.appendChild(tg)}tr.appendChild(st);
   function cb(tok){var td=el('td');var c=el('input');c.type='checkbox';c.checked=m.levels.indexOf(tok)>=0;c.disabled=!m.on||!!m.admin_only;c.onchange=function(){var s=m.levels.filter(function(x){return x!==tok});if(c.checked)s.push(tok);m.levels=s;mmDirty(p);mmDraw(p)};td.appendChild(c);return td}
   tr.appendChild(cb(D.guest));D.levels.forEach(function(l){tr.appendChild(cb(l.id))});
   var lk=el('td');var a=el('a',null,'열기');a.href=m.preview_path||m.public_path;a.target='mini_admin_view';a.rel='noopener';lk.appendChild(a);tr.appendChild(lk);
   t.appendChild(tr)});
  tb.appendChild(t);var g=el('p','note','');var vis=D.menus.filter(function(m){return m.on&&m.levels.indexOf(D.guest)>=0}).length;g.textContent='지금 비회원(일반 방문자)에게 보이는 메뉴: '+vis+'개';tb.appendChild(g)}
 mmRows()}
function mmSave(p){var D=MM.draft;var names={};for(var i=0;i<D.levels.length;i++){var n=(D.levels[i].name||'').trim();if(!n){toast('이름이 빈 회원 단계가 있어요');return}D.levels[i].name=n}
 apiJ('/admin/api/menumgr/save',{levels:D.levels,menus:D.menus.map(function(m){return {id:m.id,on:m.on,levels:m.levels}}),order:D.menus.map(function(m){return m.id})}).then(function(j){
  if(j.error){toast(j.error);return}MM.S=j;MM.draft=mmClone(j);MM.dirty=false;toast('저장했어요 — 메인 화면 메뉴에 바로 반영돼요');mmDraw(p)})}
"""


PB_JS = r"""
var PB={sub:'ov'};
function pbRank(m,L){if(m.admin_only||!m.on||!m.tokens.length)return 99;if(m.tokens.indexOf('guest')>=0)return 0;var ids=L.map(function(x){return x.id}),b=99;m.tokens.forEach(function(t){var i=ids.indexOf(t);if(i>=0&&i+1<b)b=i+1});return b}
function pbDirty(){var d=false;try{if(MM&&MM.dirty)d=true;if(FE&&FE.draft&&FE.draft.menus.some(function(m,i){return feDirty(i)}))d=true}catch(e){}return d}
function pbGo(sub,p,mi){if(sub!==PB.sub&&pbDirty()&&!confirm('저장하지 않은 변경이 있어요. 저장하지 않고 이동할까요?'))return;if(mi!=null&&typeof FE!=='undefined')FE.sel=mi;PB.sub=sub;pbLoad(p)}
function pbLoad(p){p.innerHTML='';var top=el('div','c');var th=el('div','bar');th.appendChild(el('b',null,'🎚 공개 관리'));th.appendChild(el('span','m','누구에게 무엇을 열지 한 곳에서 정해요 · 관리자는 어떤 설정이든 모든 메뉴·기능을 항상 쓸 수 있어요(블로그 쓰기 포함)'));top.appendChild(th);
 var bar=el('div','bar');[['ov','📋 한눈에 보기'],['fe','🎚 기능별 공개'],['mm','🧭 메뉴 순서·회원 단계']].forEach(function(x){bar.appendChild(bt(x[1],PB.sub===x[0]?'bt':'bt2',function(){pbGo(x[0],p)}))});top.appendChild(bar);p.appendChild(top);
 var box=el('div');p.appendChild(box);if(PB.sub==='fe')feLoad(box);else if(PB.sub==='mm')mmLoad(box);else pbOv(box,p)}
function pbOv(box,p){api('/admin/api/feat/matrix').then(function(j){if(cur!=='pb'||PB.sub!=='ov')return;var L=j.levels,G=j.guest;
 var cols=[[G,'비회원']].concat(L.map(function(x){return [x.id,x.name]}));
 var c=el('div','c');c.appendChild(el('b',null,'📋 공개 현황 — 공개 등급이 낮은(누구나) 메뉴부터'));
 c.appendChild(el('p','note','칸의 숫자 = 그 등급이 쓸 수 있는 기능 수 / 전체 기능 수 · — = 그 등급에게는 메뉴 자체가 안 보임 · 이름을 누르면 기능별 공개 설정으로 이동해요.'));
 var rows=j.menus.map(function(m,i){return {m:m,i:i,r:pbRank(m,L)}});rows.sort(function(a,b){return a.r-b.r||a.i-b.i});
 var tw=el('div');tw.style.overflowX='auto';var t=el('table');var h=el('tr');['메뉴','공개 범위'].concat(cols.map(function(x){return x[1]})).concat(['바로가기']).forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 var last=-1;
 rows.forEach(function(o){var m=o.m;if(o.r!==last){last=o.r;var hr=el('tr');var hd=el('td','m',o.r===0?'🌐 누구나':(o.r>=99?'🔒 관리자 전용 (아직 공개 전 · 관리자만 테스트)':'🟢 '+(L[o.r-1]?L[o.r-1].name:'회원')+' 이상'));hd.colSpan=cols.length+3;hd.style.cssText='background:#f1f5f9;font-weight:800';hr.appendChild(hd);t.appendChild(hr)}
  var tr=el('tr');var nm=el('td');var a=el('a',null,m.icon+' '+m.label);a.href='#';a.onclick=function(e){e.preventDefault();pbGo('fe',p,o.i)};nm.appendChild(a);tr.appendChild(nm);
  tr.appendChild(el('td','m',m.admin_only?'관리자 전용':(!m.on?'🙈 숨김':(o.r===0?'누구나':(o.r>=99?'관리자 전용':L[o.r-1].name+' 이상')))));
  cols.forEach(function(cc){var td=el('td');var vis=m.on&&!m.admin_only&&m.tokens.indexOf(cc[0])>=0;
   if(!vis)td.appendChild(el('span','m','—'));else{var n=m.feats.filter(function(f){return f.tokens.indexOf(cc[0])>=0}).length,N=m.feats.length;td.appendChild(el('span',N&&n===N?'good':(n?'':'m'),'✅ '+(N?n+'/'+N:'')))}tr.appendChild(td)});
  var ac=el('td');var wb=WB&&WB.items.filter(function(x){return x.id===m.id})[0];
  if(wb&&wb.tab){var b1=bt('🧰 작업대','bt3',function(){cur=wb.tab;nav();load()});ac.appendChild(b1)}
  if(m.shell){var a2=el('a','bt3','👁 이용자 화면');a2.href='/m/'+m.id;a2.target='_blank';a2.rel='noopener';a2.style.textDecoration='none';a2.style.marginLeft='4px';ac.appendChild(a2)}
  tr.appendChild(ac);t.appendChild(tr)});
 tw.appendChild(t);c.appendChild(tw);
 var vis=j.menus.filter(function(m){return m.on&&!m.admin_only&&m.tokens.indexOf(G)>=0}).length;
 c.appendChild(el('p','note','지금 비회원에게 보이는 메뉴: '+vis+'개 / 전체 '+j.menus.length+'개 · 새로 만든 메뉴는 기본이 "관리자 전용"이라, 테스트를 마친 뒤 [기능별 공개]에서 등급을 열어 주세요.'));
 box.innerHTML='';box.appendChild(c)})}
"""


def register():
    C.register_admin_tab("mm", "🧭 메뉴 관리", JS, "mmLoad")
    C.register_admin_tab("pb", "🎚 공개 관리", PB_JS, "pbLoad")
    return bp
