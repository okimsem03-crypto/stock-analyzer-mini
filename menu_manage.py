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
    for m in menus_ordered():
        on, tok = menu_policy(m["id"])
        menus.append({"id": m["id"], "icon": m["icon"], "label": m["label"], "desc": m.get("desc", ""), "on": bool(on),
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


JS = r"""
var MM={S:null,draft:null,dirty:false,q:''};
function mmClone(o){return JSON.parse(JSON.stringify(o))}
function mmLoad(p){api('/admin/api/menumgr/state').then(function(j){if(cur!=='mm')return;MM.S=j;MM.draft=mmClone(j);MM.dirty=false;mmDraw(p)})}
function mmFree(){var used={};MM.draft.levels.forEach(function(l){used[l.id]=1});for(var i=1;i<=10;i++){if(!used[String(i)])return String(i)}return null}
function mmDirty(p){MM.dirty=true;var b=$('mmsave');if(b){b.disabled=false;b.textContent='💾 저장 (변경사항 있음)'}}
function mmDraw(p){p.innerHTML='';var D=MM.draft;
 var top=el('div','c');top.appendChild(el('b',null,'🧭 메뉴 관리'));
 top.appendChild(el('p','note','메인 화면 위쪽 메뉴 바에 어떤 메뉴를, 누구에게 보여줄지 정해요. 관리자로 로그인하면 숨김 메뉴도 🔒 표시로 항상 보입니다. 아래에서 고친 뒤 [저장]을 눌러야 적용돼요.'));
 var sv=bt('💾 저장','bt',function(){mmSave(p)});sv.id='mmsave';sv.textContent='💾 저장';sv.disabled=!MM.dirty;top.appendChild(sv);p.appendChild(top);
 // ── 회원 단계
 var lc=el('div','c');lc.appendChild(el('b',null,'👥 회원 단계 (최대 '+D.max+'단계)'));
 lc.appendChild(el('p','note','회원이 몇 단계로 나뉠지 자유롭게 정해요. 위쪽이 낮은 단계예요. 비회원은 항상 따로 있습니다. 가입한 회원은 [👤 회원] 탭에서 단계를 바꿀 수 있고, 새로 가입하면 [👤 회원]에서 정한 기본 단계가 돼요.'));
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
 mc.appendChild(el('p','note','✅ 켜짐 = 아래 체크한 사람에게 보임 · 🙈 숨김 = 관리자만 보임. "비회원"을 체크하면 모든 사람에게 공개돼요. 메뉴는 앞으로 계속 늘어나요 — 이름으로 찾거나 ▲▼로 순서를 바꾸세요(메인 화면 메뉴 바 순서).'));
 var sb=el('input');sb.placeholder='메뉴 이름 검색';sb.value=MM.q;sb.style.width='220px';sb.oninput=function(){MM.q=sb.value;mmRows()};mc.appendChild(sb);
 var tw=el('div');tw.style.cssText='overflow-x:auto;margin-top:8px';var tb=el('div');tw.appendChild(tb);mc.appendChild(tw);p.appendChild(mc);
 function mmRows(){tb.innerHTML='';var t=el('table');var h=el('tr');['순서','메뉴','상태','비회원'].concat(D.levels.map(function(l){return l.name})).concat(['열기']).forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
  var q=(MM.q||'').trim().toLowerCase();
  D.menus.forEach(function(m,i){if(q&&(m.label+' '+m.desc+' '+m.id).toLowerCase().indexOf(q)<0)return;var tr=el('tr');
   var o=el('td');var u=bt('▲','bt3',function(){if(i>0){var x=D.menus[i-1];D.menus[i-1]=m;D.menus[i]=x;mmDirty(p);mmDraw(p)}});u.disabled=i===0;var w=bt('▼','bt3',function(){if(i<D.menus.length-1){var x=D.menus[i+1];D.menus[i+1]=m;D.menus[i]=x;mmDirty(p);mmDraw(p)}});w.disabled=i===D.menus.length-1;o.appendChild(u);o.appendChild(w);tr.appendChild(o);
   var nm=el('td');nm.appendChild(el('b',null,m.icon+' '+m.label));nm.appendChild(el('div','m',m.desc||''));tr.appendChild(nm);
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


def register():
    C.register_admin_tab("mm", "🧭 메뉴 관리", JS, "mmLoad")
    return bp
