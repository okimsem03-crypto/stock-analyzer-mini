"""🎚 기능별 등급 공개 — 메뉴 하나 안에서 기능마다 '누구에게 열지' 정하고, 그대로 이용자 화면으로 보여준다.

구성
  · /m/<메뉴>              이용자용 메뉴 화면(관리자 탭과 같은 화면을 회원 모드로). 위쪽에 '이 메뉴로 할 수 있는 일' 안내와
                          기능별 🔒 표시가 붙는다. 서버 호출은 모두 /mapi/ 문(gateway)을 지나며 등록된 기능 주소만, 등급이 맞을 때만 통과.
  · /api/features/<메뉴>   그 메뉴의 기능 목록과 '지금 보는 사람'의 사용 가능 여부(화면이 잠금 표시에 쓴다)
  · /plans                 회원 등급별 이용 안내표(공개 화면)
  · /menus                 전체 메뉴 — 메뉴마다 기능 칩(✅ 열림 / 🔒 등급 필요)
  · 관리자 탭 [🎚 기능 공개]  기능 × 등급 체크표. 저장 전 확인 창, 등급별 미리보기(?as=) 링크.

새 메뉴 모듈에서 하는 일(요약)
  C.register_menu({... "public_path": "/m/<id>", "admin_path": "/admin#<탭>"})
  C.register_admin_tab("탭id", "라벨", JS, "로더함수", menu="<id>")
  C.register_feature("<id>", "기능id", "이름", desc, default="member", endpoints=["/admin/api/<id>/x", ...])
  JS 안에서: ft(버튼, '기능id') · ftSec(영역, '기능id') · adm(관리자 전용 노드) · MEMBER_MODE · FEATS
"""
import json
import re
import secrets

from flask import Blueprint, request

from menu_ctx import C
import menu_ui as U

bp = Blueprint("menuaccess", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "setting_set", "setting_get", "member_levels", "menu_policy",
               "menu_policy_set", "menus_ordered")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)


def esc(s):
    return U.esc(s)


# ───────────────────────── 공통 계산 ─────────────────────────
def _level_names():
    return {x["id"]: x["name"] for x in member_levels()}


def need_text(tokens):
    """볼 수 있는 사람 집합 → '정회원 이상 회원' 같은 한 줄."""
    lv = member_levels()
    if not tokens:
        return "관리자 전용(아직 공개 전)"
    if C.GUEST in tokens:
        return "누구나"
    ids = [x["id"] for x in lv if x["id"] in tokens]
    if not ids:
        return "관리자 전용(아직 공개 전)"
    names = _level_names()
    tail = [x["id"] for x in lv][len(lv) - len(ids):]
    return f"{names[ids[0]]} 이상" if ids == tail else "·".join(names[i] for i in ids) + " 회원"


def viewer_label(tok):
    if tok == "admin":
        return "관리자"
    if tok == C.GUEST:
        return "비회원"
    return _level_names().get(tok, "회원")


def _menu(mid):
    return next((m for m in C.MENUS if m["id"] == mid), None)


def feats_of(mid):
    return [f for f in C.FEATURES if f["menu"] == mid]


def feats_state(mid, tok):
    out = {}
    for f in feats_of(mid):
        ok = C.feature_ok(mid, f["id"], tok)
        tk = C.feature_policy(mid, f["id"])
        out[f["id"]] = {"label": f["label"], "desc": f.get("desc", ""), "ok": bool(ok), "need": C.feature_need_text(mid, f["id"]),
                        "login": tok == C.GUEST and not ok and bool(tk), "kind": f.get("kind", "view"), "open": bool(tk)}
    return out


def menu_need(mid):
    on, tk = menu_policy(mid)
    return need_text(tk if on else set())


# ───────────────────────── 이용자 API ─────────────────────────
@bp.route("/api/features/<mid>")
def api_features(mid):
    m = _menu(mid)
    if not m:
        return C._admin_json({"error": "없는 메뉴예요."}, 404)
    tok = C.viewer_token()
    is_admin = C.admin_viewer()
    lv = member_levels()
    d = {"menu": {"id": mid, "label": m["label"], "icon": m["icon"], "desc": m.get("desc", "")},
         "viewer": tok, "viewer_name": viewer_label(tok), "is_admin": bool(is_admin), "preview": bool(is_admin and tok != "admin"),
         "menu_ok": bool(C.menu_visible_token(mid, tok)), "menu_need": menu_need(mid), "login": tok == C.GUEST,
         "feats": feats_state(mid, tok), "order": [f["id"] for f in feats_of(mid)],
         "levels": [{"id": x["id"], "name": x["name"]} for x in lv]}
    resp = C._admin_json(d)
    return resp


# ───────────────────────── 이용자용 메뉴 화면(/m/<메뉴>) ─────────────────────────
MEM_CSS = r"""
#intro{margin:0 0 12px}.itCard{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:14px 16px}
.itTop{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.itTop b{font-size:17px}.itBadge{background:#e0e7ff;color:#3730a3;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700}
.itBadge.pv{background:#fef3c7;color:#92400e}.itDesc{color:#475569;font-size:13px;margin:6px 0 8px;line-height:1.55}
.itChips{display:flex;gap:6px;flex-wrap:wrap}.chip{border:1px solid #bbf7d0;background:#f0fdf4;color:#166534;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:600}
.chip.lk{border-color:#fcd34d;background:#fffbeb;color:#92400e;cursor:pointer}.chip small{font-weight:400;opacity:.85;margin-left:4px}
.itAct{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}.itAct a{border-radius:10px;padding:8px 14px;font-size:13px;font-weight:700;text-decoration:none;border:1px solid #cbd5e1;background:#fff;color:#334155}
.itAct a.go{background:#2563eb;border-color:#2563eb;color:#fff}.itAct select{border:1px solid #cbd5e1;border-radius:8px;padding:6px 8px;font-size:12.5px}
.itLock{text-align:center;padding:34px 16px}.itLock h2{margin:0 0 8px}body.emb #intro .itDesc{display:none}
"""

MEM_BOOT = r"""
(function(){
 var Q=location.search||'',m=/[?&]as=([^&]+)/.exec(Q),PA=m?decodeURIComponent(m[1]):'';
 if(PA){var of=window.fetch;window.fetch=function(u,o){o=o||{};o.headers=Object.assign({},o.headers||{},{'X-Preview-As':PA});return of(u,o)}}
 document.body.classList.add('mem');
 var nx=encodeURIComponent('/m/'+MENU_ID);
 function chip(f,fid){var s=FEATS[fid],c=el('span','chip'+(s.ok?'':' lk'),(s.ok?'✅ ':'🔒 ')+s.label);if(!s.ok){c.appendChild(el('small',null,s.need));c.onclick=function(){lockDlg(fid)}}else if(s.desc)c.title=s.desc;return c}
 function link(t,h,go,top){var a=el('a',go?'go':null,t);a.href=h;if(top!==false)a.target='_top';return a}
 fetch('/api/features/'+MENU_ID,{credentials:'same-origin'}).then(function(r){return r.json()}).then(function(j){
  if(j.error){$('pane').textContent=j.error;return}
  FEATS=j.feats;$('mbt').textContent=j.menu.icon+' '+j.menu.label;document.title=j.menu.label+' · 종목분석 미니';
  var bs=$('mbs');bs.textContent=(j.preview?'👁 미리보기: ':'')+j.viewer_name;
  if(!j.login&&!j.is_admin){var l=$('mbl');l.textContent='내 정보';l.href='/member'}
  var it=$('intro');it.innerHTML='';var cd=el('div','itCard'),tp=el('div','itTop');tp.appendChild(el('b',null,j.menu.icon+' '+j.menu.label));
  tp.appendChild(el('span','itBadge'+(j.preview?' pv':''),(j.preview?'미리보기 · ':'지금 등급 · ')+j.viewer_name));cd.appendChild(tp);
  if(j.menu.desc)cd.appendChild(el('div','itDesc',j.menu.desc));
  if(j.order.length){var ch=el('div','itChips');j.order.forEach(function(fid){ch.appendChild(chip(FEATS[fid],fid))});cd.appendChild(ch)}
  var ac=el('div','itAct');
  if(j.login&&j.menu_ok)ac.appendChild(link('로그인하고 더 쓰기','/member?next='+nx,true));
  if(j.login&&j.menu_ok)ac.appendChild(link('회원가입','/member?tab=signup&next='+nx,false));
  ac.appendChild(link('등급별 이용 안내','/plans',false));
  if(j.is_admin){var sel=el('select');[['','관리자 화면(전체)'],['guest','👁 비회원으로 보기']].concat(j.levels.map(function(x){return [x.id,'👁 '+x.name+'으로 보기']})).forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];sel.appendChild(op)});
   sel.value=PA;sel.onchange=function(){location.href='/m/'+MENU_ID+(sel.value?'?as='+sel.value:'')+(/embed=1/.test(Q)?(sel.value?'&':'?')+'embed=1':'')};ac.appendChild(sel)}
  cd.appendChild(ac);it.appendChild(cd);
  if(!j.menu_ok){var p=$('pane');p.innerHTML='';var b=el('div','c itLock');b.appendChild(el('h2',null,'🔒 '+j.menu.label));
   b.appendChild(el('p','note',j.menu_need==='관리자 전용(아직 공개 전)'?'아직 일반 이용자에게 공개되지 않은 메뉴예요. 곧 열립니다.':'이 메뉴는 '+j.menu_need+'부터 볼 수 있어요.'));
   if(j.login){var r=el('div','itAct');r.style.justifyContent='center';r.appendChild(link('로그인','/member?next='+nx,true));r.appendChild(link('회원가입','/member?tab=signup&next='+nx,false));b.appendChild(r)}
   p.appendChild(b);return}
  load()}).catch(function(){$('pane').textContent='화면을 불러오지 못했어요. 새로고침해 주세요.'});
})();
"""


def shell_page(mid, tab):
    m = _menu(mid)
    js = C.ADMIN_TAB_JS[tab]
    page = C.ADMIN_APP_HTML
    page = page.replace("<title>관리자 · 종목분석 미니</title>", "<title>" + esc(m["label"]) + " · 종목분석 미니</title>", 1)
    page = page.replace("</style></head>", MEM_CSS + "</style></head>", 1)
    page = page.replace('<div class="w"><nav id="nav"></nav>', '<div class="w"><div id="intro"></div><nav id="nav"></nav>', 1)
    page = page.replace('var CSRF="{{ csrf }}";var cur=\'sum\';var EXT={};', 'var CSRF="";var cur=' + json.dumps(tab) + ';var EXT={};', 1)
    page = re.sub(r"var TABS=\[\[.*?\]\];", "var TABS=[];", page, count=1)
    page = page.replace("var MEMBER_MODE=false,FEATS=null,MENU_ID='';", "var MEMBER_MODE=true,FEATS=null,MENU_ID=" + json.dumps(mid) + ";", 1)
    lib = "\n".join(C.ADMIN_LIB_JS + [js])
    a = page.index("/*__MODULE_JS__*/")
    b = page.index("</script></body></html>")
    page = page[:a] + lib + "\n" + MEM_BOOT + page[b:]
    page = page.replace("/admin/api/", "/mapi/")
    return page


@bp.route("/m/<mid>")
def member_menu(mid):
    m = _menu(mid)
    tab = C.MENU_TAB.get(mid)
    if not m or not tab or tab not in C.ADMIN_TAB_JS:
        return "not found", 404
    nonce = secrets.token_urlsafe(16)
    html = C.render_template_string(shell_page(mid, tab), nonce=nonce, csrf="", version=C.APP_VERSION)
    resp = C.app.make_response(html)
    return C._admin_headers(resp, nonce)


# ───────────────────────── 등급 안내(/plans) ─────────────────────────
PLANS_CSS = """<style>
.pl{overflow-x:auto}.pl table{width:100%;border-collapse:collapse;font-size:13px;background:#fff;min-width:560px}
.pl th,.pl td{border-bottom:1px solid #e2e8f0;padding:9px 8px;text-align:center}.pl th:first-child,.pl td:first-child{text-align:left}
.pl thead th{background:#0f172a;color:#fff;position:sticky;top:0;font-weight:700}.pl thead th small{display:block;font-weight:400;opacity:.75;font-size:11px}
.pl th.me,.pl td.me{background:#eff6ff}.pl thead th.me{background:#1d4ed8}.pl tr.mh td{background:#f1f5f9;font-weight:800;text-align:left}
.pl .y{color:#15803d;font-weight:800}.pl .n{color:#cbd5e1}.pl td small{display:block;color:#64748b;font-size:11.5px;font-weight:400}
.plCta{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.plCta a{border-radius:10px;padding:10px 16px;font-size:14px;font-weight:700;text-decoration:none;border:1px solid #cbd5e1;background:#fff;color:#334155}.plCta a.go{background:#2563eb;color:#fff;border-color:#2563eb}
</style>"""


def plans_table(tok):
    lv = member_levels()
    cols = [(C.GUEST, "비회원", "")] + [(x["id"], x["name"], x.get("desc", "")) for x in lv]
    head = "<thead><tr><th>기능</th>" + "".join(
        f'<th class="{"me" if c[0] == tok else ""}">{esc(c[1])}{("<small>" + esc(c[2]) + "</small>") if c[2] else ""}</th>' for c in cols) + "</tr></thead>"
    rows = []
    for m in menus_ordered():
        on, mtk = menu_policy(m["id"])
        fs = [f for f in feats_of(m["id"]) if C.feature_policy(m["id"], f["id"])]
        if not fs or not on or not mtk:
            continue
        rows.append(f'<tr class="mh"><td colspan="{len(cols) + 1}">{esc(m["icon"])} {esc(m["label"])}</td></tr>')
        for f in fs:
            ftk = C.feature_policy(m["id"], f["id"])
            tds = []
            for c in cols:
                ok = c[0] in ftk and c[0] in mtk
                tds.append(f'<td class="{"me" if c[0] == tok else ""}">' + ('<span class="y">✓</span>' if ok else '<span class="n">—</span>') + "</td>")
            rows.append(f'<tr><td>{esc(f["label"])}{("<small>" + esc(f["desc"]) + "</small>") if f.get("desc") else ""}</td>' + "".join(tds) + "</tr>")
    if not rows:
        return '<div class="mu-empty"><b>🛠️</b>아직 공개된 기능이 없어요. 곧 하나씩 열립니다.</div>'
    return '<div class="pl"><table>' + head + "<tbody>" + "".join(rows) + "</tbody></table></div>"


@bp.route("/plans")
def plans_page():
    tok = C.viewer_token()
    cta = ""
    if tok == C.GUEST:
        cta = '<div class="plCta"><a class="go" href="/member?tab=signup">무료로 회원가입</a><a href="/member">로그인</a></div>'
    body = (PLANS_CSS + '<div class="mu-card"><div class="mu-card-h">🎚 회원 등급별 이용 안내<small>지금 등급: ' + esc(viewer_label(tok)) + '</small></div><div class="mu-card-b">'
            + '<p style="margin:0 0 10px;color:#475569;font-size:13.5px">✓ 표시가 있는 기능을 해당 등급부터 쓸 수 있어요. 파란 칸이 지금 내 등급이에요.</p>' + cta + plans_table(tok) + "</div></div>")
    resp = C.app.make_response(U.page("등급별 이용 안내", body, icon="🎚", subtitle="메뉴 안의 기능마다 쓸 수 있는 회원 등급이 달라요.", active="plans"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ───────────────────────── 전체 메뉴(/menus) ─────────────────────────
MENUS_CSS = """<style>
.mc{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}.mcC{display:flex;flex-direction:column;gap:8px;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:15px;text-decoration:none;color:inherit;transition:.15s}
.mcC:hover{border-color:#93c5fd;box-shadow:0 8px 24px rgba(37,99,235,.12);transform:translateY(-1px)}.mcT{display:flex;gap:10px;align-items:center}.mcT .ic{font-size:26px}.mcT b{font-size:16px}
.mcD{color:#475569;font-size:13px;line-height:1.5}.mcF{display:flex;gap:5px;flex-wrap:wrap}.mcF span{font-size:11.5px;border-radius:999px;padding:3px 9px;border:1px solid #bbf7d0;background:#f0fdf4;color:#166534;font-weight:600}
.mcF span.lk{border-color:#fcd34d;background:#fffbeb;color:#92400e}.mcG{font-size:12px;color:#2563eb;font-weight:700;margin-top:auto}
</style>"""


@bp.route("/menus")
def menus_page():
    tok = C.viewer_token()
    cards = []
    for m in menus_ordered():
        if not C.menu_visible_token(m["id"], tok):
            continue
        fs = feats_of(m["id"])
        chips = []
        for f in fs[:8]:
            ok = C.feature_ok(m["id"], f["id"], tok)
            chips.append(f'<span class="{"" if ok else "lk"}">{"✅" if ok else "🔒"} {esc(f["label"])}</span>')
        if len(fs) > 8:
            chips.append(f'<span>+{len(fs) - 8}</span>')
        href = m["public_path"]
        cards.append(f'<a class="mcC" href="{esc(href)}"><div class="mcT"><span class="ic">{esc(m["icon"])}</span><b>{esc(m["label"])}</b></div>'
                     f'<div class="mcD">{esc(m.get("desc", ""))}</div>' + (f'<div class="mcF">{"".join(chips)}</div>' if chips else "") + '<div class="mcG">열기 ›</div></a>')
    first = ('<a class="mcC" href="/"><div class="mcT"><span class="ic">📈</span><b>종목 분석</b></div><div class="mcD">종목명이나 코드를 입력하면 가격·재무·뉴스·AI 분석용 프롬프트까지 한 번에 정리합니다.</div>'
             '<div class="mcF"><span>✅ 누구나</span></div><div class="mcG">열기 ›</div></a>')
    body = MENUS_CSS + '<div class="mu-card"><div class="mu-card-h">🧰 도구 모음<small>' + esc(viewer_label(tok)) + ' 기준</small></div><div class="mu-card-b"><div class="mc">' + first + "".join(cards) + "</div>"
    body += '<p style="margin:14px 0 0;font-size:13px;color:#64748b">🔒 표시는 더 높은 등급에서 열리는 기능이에요. <a href="/plans">등급별 이용 안내</a>에서 한눈에 볼 수 있어요.</p></div></div>'
    resp = C.app.make_response(U.page("전체 메뉴", body, icon="🧭", subtitle="필요한 도구를 골라 쓰세요. 기능마다 열리는 등급이 달라요.", active="menus"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ───────────────────────── 관리자: 🎚 기능 공개 ─────────────────────────
def _ordered(tokens):
    ids = [x["id"] for x in member_levels()]
    return ([C.GUEST] if C.GUEST in tokens else []) + [i for i in ids if i in tokens]


def _matrix():
    lv = member_levels()
    menus = []
    for m in menus_ordered():
        on, tk = menu_policy(m["id"])
        fs = []
        for f in feats_of(m["id"]):
            raw = setting_get(f"feat_{m['id']}_{f['id']}", "")
            fs.append({"id": f["id"], "label": f["label"], "desc": f.get("desc", ""), "kind": f.get("kind", "view"), "default": f["default"],
                       "tokens": _ordered(C.feature_policy(m["id"], f["id"])), "custom": raw != "", "endpoints": len(f["endpoints"])})
        menus.append({"id": m["id"], "icon": m["icon"], "label": m["label"], "desc": m.get("desc", ""), "admin_only": bool(m.get("admin_only")),
                      "shell": bool(C.MENU_TAB.get(m["id"])), "on": bool(on), "tokens": _ordered(tk if on else set()), "feats": fs})
    return {"levels": lv, "guest": C.GUEST, "menus": menus}


@bp.route("/admin/api/feat/matrix")
def api_matrix():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_matrix())


@bp.route("/admin/api/feat/save", methods=["POST"])
def api_save():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    mid = str(d.get("menu", ""))
    m = _menu(mid)
    if not m:
        return _admin_json({"error": "알 수 없는 메뉴예요."}, 400)
    valid = {C.GUEST} | {x["id"] for x in member_levels()}
    feats = d.get("feats")
    if not isinstance(feats, dict):
        return _admin_json({"error": "기능 목록이 올바르지 않아요."}, 400)
    known = {f["id"] for f in feats_of(mid)}
    changed = 0
    if d.get("reset"):
        for fid in known:
            setting_set(f"feat_{mid}_{fid}", "")
        _alog("feat_reset", mid)
        return _admin_json(_matrix())
    for fid, toks in feats.items():
        if fid not in known or not isinstance(toks, list):
            return _admin_json({"error": "알 수 없는 기능이 있어요."}, 400)
        C.feature_policy_set(mid, fid, {t for t in toks if t in valid})
        changed += 1
    mt = d.get("menu_tokens")
    if isinstance(mt, list) and not m.get("admin_only"):
        tk = {t for t in mt if t in valid}
        menu_policy_set(mid, bool(tk), tk)
    _alog("feat_save", f"{mid} feats={changed}")
    return _admin_json(_matrix())


TAB_JS = r"""
var FE={S:null,draft:null};
function feClone(o){return JSON.parse(JSON.stringify(o))}
function feLoad(p){api('/admin/api/feat/matrix').then(function(j){if(cur!=='fe')return;FE.S=j;FE.draft=feClone(j);feDraw(p)})}
function feHas(a,t){return a.indexOf(t)>=0}
function feSet(a,t,on){var i=a.indexOf(t);if(on&&i<0)a.push(t);if(!on&&i>=0)a.splice(i,1)}
function feCols(){var L=FE.S.levels;return [[FE.S.guest,'비회원']].concat(L.map(function(x){return [x.id,x.name]}))}
function feQuick(sel,toks,cols){var v=sel.value;sel.value='';var ids=cols.map(function(c){return c[0]});var out=[];
 if(v==='none')out=[];else if(v==='all')out=ids.slice();else if(v==='member')out=ids.slice(1);else if(v.indexOf('L')===0){var n=parseInt(v.slice(1),10);out=ids.slice(1+n-1)}
 toks.length=0;out.forEach(function(x){toks.push(x)})}
function feDraw(p){p.innerHTML='';var cols=feCols();
 var top=el('div','c');top.appendChild(el('b',null,'🎚 기능 공개 — 메뉴 안의 기능마다 누구에게 열지 정해요'));
 top.appendChild(el('p','note','칸을 체크한 등급이 그 기능을 쓸 수 있어요. 아무도 체크하지 않으면 관리자만 써요. 관리자는 항상 모두 쓸 수 있어요. 이용자 화면은 [👁 미리보기]로 등급별로 직접 확인해 보세요. 메뉴 자체의 공개(메뉴 바에 보이기)는 각 메뉴의 첫 줄이에요. 회원 단계(이름·개수)는 [🧭 메뉴 관리]에서 바꿔요.'));
 var lk=el('div','bar');var a1=el('a',null,'📋 이용자용 등급 안내표 보기 ↗');a1.href='/plans';a1.target='_blank';a1.rel='noopener';lk.appendChild(a1);top.appendChild(lk);p.appendChild(top);
 FE.draft.menus.forEach(function(m,mi){var S=FE.S.menus[mi];var c=el('div','c');
  var h=el('div','bar');h.appendChild(el('b',null,m.icon+' '+m.label));h.appendChild(el('span','m',m.desc||''));c.appendChild(h);
  if(!m.shell)c.appendChild(el('p','note','이 메뉴는 아직 이용자용 화면(/m/'+m.id+')이 없어요 — 기능 등록만 되어 있어요.'));
  var pv=el('div','bar');pv.appendChild(el('span','m','👁 미리보기:'));cols.concat([['admin','관리자']]).forEach(function(cc){if(cc[0]==='admin')return;var a=el('a','bt3',cc[1]+'으로');a.href='/m/'+m.id+'?as='+cc[0];a.target='_blank';a.rel='noopener';a.style.textDecoration='none';pv.appendChild(a)});
  if(m.shell)c.appendChild(pv);
  var tw=el('div');tw.style.overflowX='auto';var t=el('table');var hr=el('tr');hr.appendChild(el('th',null,'기능'));cols.forEach(function(cc){hr.appendChild(el('th',null,cc[1]))});hr.appendChild(el('th',null,'빠른 설정'));t.appendChild(hr);
  function row(label,desc,toks,aria,note){var tr=el('tr');var td=el('td');td.appendChild(el('b',null,label));if(desc)td.appendChild(el('div','m',desc));if(note)td.appendChild(el('div','m',note));tr.appendChild(td);
   var boxes=[];cols.forEach(function(cc){var tdc=el('td');var cb=el('input');cb.type='checkbox';cb.checked=feHas(toks,cc[0]);cb.setAttribute('aria-label',aria+' · '+cc[1]);
    cb.onchange=function(){feSet(toks,cc[0],cb.checked)};boxes.push([cc[0],cb]);tdc.appendChild(cb);tr.appendChild(tdc)});
   var tq=el('td');var sel=el('select');sel.setAttribute('aria-label','빠른 설정');[['','선택…'],['none','관리자만'],['all','누구나'],['member','모든 회원']].concat(FE.S.levels.map(function(x,i){return ['L'+(i+1),x.name+' 이상']})).forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];sel.appendChild(op)});
   sel.onchange=function(){feQuick(sel,toks,cols);boxes.forEach(function(b){b[1].checked=feHas(toks,b[0])})};tq.appendChild(sel);tr.appendChild(tq);t.appendChild(tr)}
  if(m.admin_only)row('📌 메뉴 보이기','이 메뉴는 관리자 전용으로 고정돼 있어요.',[],'메뉴 보이기');else row('📌 메뉴 보이기','메뉴 바·전체 메뉴에 나타나는 등급',m.tokens,'메뉴 보이기');
  m.feats.forEach(function(f){row(f.label,f.desc,f.tokens,f.label,f.custom?'· 직접 정한 값':'· 기본값')});
  tw.appendChild(t);c.appendChild(tw);
  if(!m.feats.length)c.appendChild(el('p','note','이 메뉴는 기능별 설정이 아직 없어요.'));
  var bar=el('div','bar');
  bar.appendChild(bt('💾 이 메뉴 공개 설정 저장','bt',function(){var fs={};m.feats.forEach(function(f){fs[f.id]=f.tokens});
   apiJ('/admin/api/feat/save',{menu:m.id,feats:fs,menu_tokens:m.admin_only?null:m.tokens}).then(function(j){if(j.error){toast(j.error);return}FE.S=j;FE.draft=feClone(j);toast('저장했어요');feDraw(p)})}));
  bar.appendChild(bt('↩ 기본값으로 되돌리기','bt2',function(){if(!confirm('‘'+m.label+'’ 기능의 공개 설정을 처음 기본값으로 되돌릴까요?'))return;apiJ('/admin/api/feat/save',{menu:m.id,feats:{},reset:true}).then(function(j){if(j.error){toast(j.error);return}FE.S=j;FE.draft=feClone(j);toast('되돌렸어요');feDraw(p)})}));
  c.appendChild(bar);
  var warn=m.feats.filter(function(f){return !m.admin_only&&f.tokens.some(function(t){return m.tokens.indexOf(t)<0})});
  if(warn.length)c.appendChild(el('p','note bad','⚠ 메뉴 자체가 열려 있지 않은 등급이 있어서, 그 등급에게는 기능이 열려 있어도 보이지 않아요: '+warn.map(function(f){return f.label}).join(', ')));
  p.appendChild(c)})}
"""


def register():
    C.register_admin_tab("fe", "🎚 기능 공개", TAB_JS, "feLoad")
    return bp
