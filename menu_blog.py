"""✍ 블로그 공용 모듈 — 메뉴별 블로그 글쓰기 주소, 복사·열기·작성 이력, 블로그 HTML 공용 부품.

분석실(menu_lab) · 심층분석(menu_deep) · 오늘추천(menu_daily) 이 모두 이 모듈을 같이 쓴다.

· 메뉴별 블로그 글쓰기 주소: 원본 프로그램 설정(blog_menu_urls)에 있던 값을 기본값으로 미리 넣어 두었다.
  (https://blog.naver.com/<아이디>?Redirect=Write&categoryNo=<번호>) — 관리자 [✍ 블로그 주소] 탭에서 메뉴마다 바꾼다.
· 복사하고 바로 열기: [📋 복사하고 블로그 열기] 한 번이면 서식 있는 HTML 이 복사되고 해당 메뉴의 글쓰기 화면이 열린다. 붙여넣기만 하면 된다.
· 작성 이력: 어떤 종목으로 어떤 메뉴의 글을 썼는지 기록하고, 같은 종목을 또 쓰려 하면 경고한다.
· 블로그 HTML 부품: 원본 방식(표 + 인라인 서식 → 네이버 스마트에디터 붙여넣기)의 제목 줄·섹션 카드·응원 상자·위험 고지·해시태그.
"""
import html as _html
import json
import re
import time
from flask import Blueprint, request, Response
from menu_ctx import C

bp = Blueprint("blogkit", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_dbrows", "setting_get", "setting_set", "get_ticker_info")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

E = lambda s: _html.escape("" if s is None else str(s), quote=True)
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
LOG_TICKER_RE = re.compile(r"^(?:[0-9A-Za-z]{6}|D[0-9]{6})$")      # 글 기록용: 종목코드 또는 오늘추천 날짜표(D+YYMMDD)

# ══════════════════════════════════════════════════════════════
# 메뉴별 블로그 글쓰기 주소 (원본 DB 의 blog_menu_urls 를 기본값으로)
# ══════════════════════════════════════════════════════════════
DEFAULT_BLOG_ID = "okykr"
# (키, 이름, 카테고리 번호) — 앞의 3개는 지금 쓰는 메뉴, 나머지는 원본에 있던 메뉴(앞으로 옮겨 올 때 바로 쓰도록 미리 준비)
BLOG_MENUS = [
    ("stock", "종목분석", 16), ("deepdive", "기업심층분석", 18), ("daily", "오늘추천", 16),
    ("news", "뉴스분석 블로그", 19), ("flow", "수급분석 리포트", 20), ("aiflow", "AI수급 리포트", 20),
    ("heatmap", "히트맵 블로그", 20), ("calendar", "경제캘린더", 20), ("sell", "매도신호", 20), ("macro", "거시경제 리포트", 20),
    ("all", "전체종목 리포트", 20), ("caution", "투자주의", 20), ("issue", "이슈분석", 20), ("risk", "위험종목", 20),
    ("newlist", "신규상장", 20), ("disc", "공시분석", 20), ("vol", "변동성분석", 20),
]
_KEYS = {k for k, _, _ in BLOG_MENUS}
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{2,30}$")
_URL_RE = re.compile(r"^https?://[^\s<>\"'\\]{4,300}$")
FALLBACK_URL = "https://blog.naver.com/GoBlogWrite.naver"


def blog_id():
    v = str(setting_get("naver_blog_id", DEFAULT_BLOG_ID) or "").strip()
    return v if _ID_RE.match(v) else DEFAULT_BLOG_ID


def default_url(key, bid=None):
    cat = next((c for k, _, c in BLOG_MENUS if k == key), None)
    bid = bid or blog_id()
    return f"https://blog.naver.com/{bid}?Redirect=Write&categoryNo={cat}" if cat else FALLBACK_URL


def _overrides():
    try:
        d = json.loads(setting_get("blog_menu_urls", "") or "{}")
        return {k: v for k, v in d.items() if k in _KEYS and _URL_RE.match(str(v))} if isinstance(d, dict) else {}
    except Exception:
        return {}


def url_for(key):
    """메뉴 키(stock·deepdive·daily …)의 블로그 글쓰기 주소. 바꾸지 않았으면 기본값."""
    return _overrides().get(key) or default_url(key)


def auto_open():
    return str(setting_get("blog_auto_open", "1")) != "0"


def urls_state():
    ov, bid = _overrides(), blog_id()
    menus = []
    for k, label, _c in BLOG_MENUS:
        d = default_url(k, bid)
        u = ov.get(k) or d
        menus.append({"key": k, "label": label, "url": u, "default": d, "custom": u != d})
    return {"id": bid, "auto_open": auto_open(), "menus": menus, "default_id": DEFAULT_BLOG_ID}


def _valid_id(k, v):
    v = str(v or "").strip()
    return v if _ID_RE.match(v) else None


def _valid_auto(k, v):
    v = str(v).strip().lower()
    return "1" if v in ("1", "true", "on", "yes") else ("0" if v in ("0", "false", "off", "no") else None)


def _valid_urls(k, v):
    try:
        d = json.loads(v) if isinstance(v, str) else v
    except Exception:
        return None
    if not isinstance(d, dict) or any(x not in _KEYS or not _URL_RE.match(str(u)) for x, u in d.items()):
        return None
    return json.dumps(d, ensure_ascii=False)


@bp.route("/admin/api/blog/urls", methods=["GET"])
def api_urls():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(urls_state())


@bp.route("/admin/api/blog/urls", methods=["POST"])
def api_urls_save():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body() or {}
    bid = str(d.get("id") or blog_id()).strip()
    if not _ID_RE.match(bid):
        return _admin_json({"error": "블로그 아이디는 영문·숫자·_- 2~30자예요."}, 400)
    urls = d.get("urls")
    if not isinstance(urls, dict):
        return _admin_json({"error": "주소 목록이 올바르지 않아요."}, 400)
    keep = {}
    for k, u in urls.items():
        u = str(u or "").strip()
        if k not in _KEYS:
            return _admin_json({"error": "알 수 없는 메뉴가 있어요."}, 400)
        if not u or u == default_url(k, bid):
            continue                                   # 기본값과 같으면 저장하지 않는다(아이디를 바꾸면 기본값이 같이 바뀜)
        if not _URL_RE.match(u):
            return _admin_json({"error": f"‘{next(l for kk, l, _ in BLOG_MENUS if kk == k)}’ 주소가 올바르지 않아요(http:// 또는 https:// 로 시작, 공백 없이)."}, 400)
        keep[k] = u
    setting_set("naver_blog_id", bid)
    setting_set("blog_menu_urls", json.dumps(keep, ensure_ascii=False))
    if "auto_open" in d:
        setting_set("blog_auto_open", "1" if d.get("auto_open") else "0")
    _alog("blog_urls", f"id={bid} custom={len(keep)}")
    return _admin_json(urls_state())


# ══════════════════════════════════════════════════════════════
# 작성 이력 (표 이름은 v139 의 lab_blog_log 를 그대로 쓴다 — 이미 쌓인 기록 유지)
# ══════════════════════════════════════════════════════════════
KINDS = {"stock": "종목분석", "deepdive": "심층분석", "daily": "오늘추천", "caution": "투자주의"}


def _ensure_table(c, use_pg):
    pk = "SERIAL PRIMARY KEY" if use_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.execute(f"CREATE TABLE IF NOT EXISTS lab_blog_log(id {pk}, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', "
              "title TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'stock', url TEXT NOT NULL DEFAULT '', "
              "memo TEXT NOT NULL DEFAULT '', at BIGINT NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lab_blog_ticker ON lab_blog_log(ticker, at)")


_COLS = ("id", "ticker", "name", "title", "kind", "url", "memo", "at")


def _legacy_deepdive(ticker):
    """원본 프로그램이 남긴 심층분석 발행 기록(deepdive_blog_log, 가져온 경우에만)."""
    try:
        rows = _dbx("SELECT name, posted_at FROM deepdive_blog_log WHERE ticker=? ORDER BY posted_at DESC LIMIT 5", (ticker,), fetch=True) or []
    except Exception:
        return []
    out = []
    for nm, at in rows:
        try:
            ts = int(time.mktime(time.strptime(str(at)[:19], "%Y-%m-%d %H:%M:%S")))
        except Exception:
            continue
        out.append({"id": 0, "ticker": ticker, "name": nm or "", "title": "(원본 프로그램에서 발행)", "kind": "deepdive", "url": "", "memo": "원본 기록", "at": ts})
    return out


def recent_logs(ticker, kind=None, n=5):
    if kind:
        rows = _dbrows("SELECT id,ticker,name,title,kind,url,memo,at FROM lab_blog_log WHERE ticker=? AND kind=? ORDER BY at DESC, id DESC LIMIT ?", _COLS, (ticker, kind, n))
    else:
        rows = _dbrows("SELECT id,ticker,name,title,kind,url,memo,at FROM lab_blog_log WHERE ticker=? ORDER BY at DESC, id DESC LIMIT ?", _COLS, (ticker, n))
    if kind in (None, "deepdive"):
        rows = sorted(rows + _legacy_deepdive(ticker), key=lambda r: -r["at"])[:n]
    return rows


def dup_warning(logs):
    if not logs:
        return ""
    last = logs[0]
    days = max(0, int((time.time() - last["at"]) // 86400))
    kind = KINDS.get(last.get("kind"), "")
    who = "이 날짜는" if re.match(r"^D\d{6}$", str(last.get("ticker", ""))) else "이 종목은"
    return (f"{who} {'오늘' if days == 0 else str(days) + '일 전에'} 이미 {kind + ' ' if kind else ''}글을 쓴 기록이 있어요"
            f"(‘{last['title'][:40]}’){' · 최근 기록 ' + str(len(logs)) + '건' if len(logs) > 1 else ''}. 같은 내용이 겹치지 않게 확인하세요.")


def dup_info(ticker, kind=None):
    logs = recent_logs(ticker, kind)
    return logs, dup_warning(logs)


@bp.route("/admin/api/blog/log", methods=["GET"])
def api_log_list():
    deny = _admin_deny()
    if deny:
        return deny
    q = str(request.args.get("q", "")).strip()[:30]
    kind = str(request.args.get("kind", "")).strip()
    where, args = [], []
    if q:
        where.append("(ticker=? OR name LIKE ? OR title LIKE ?)")
        args += [q.upper(), f"%{q}%", f"%{q}%"]
    if kind in KINDS:
        where.append("kind=?")
        args.append(kind)
    sql = "SELECT id,ticker,name,title,kind,url,memo,at FROM lab_blog_log" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY at DESC, id DESC LIMIT 300"
    rows = _dbrows(sql, _COLS, tuple(args))
    cnt = {}
    for r in rows:
        k = (r["ticker"], r["kind"])
        cnt[k] = cnt.get(k, 0) + 1
    return _admin_json({"rows": rows, "multi": sorted({f"{t}|{k}" for (t, k), v in cnt.items() if v >= 2}), "kinds": KINDS})


@bp.route("/admin/api/blog/log", methods=["POST"])
def api_log_add():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body() or {}
    t = str(d.get("ticker", "")).strip().upper()
    if not LOG_TICKER_RE.match(t):
        return _admin_json({"error": "종목코드가 올바르지 않아요."}, 400)
    title = str(d.get("title") or "").strip()[:150]
    if not title:
        return _admin_json({"error": "글 제목이 비어 있어요."}, 400)
    url = str(d.get("url") or "").strip()[:400]
    if url and not re.match(r"^https?://", url):
        return _admin_json({"error": "글 주소는 http(s):// 로 시작해야 해요."}, 400)
    kind = str(d.get("kind") or "stock").strip()
    if kind not in KINDS:
        kind = "stock"
    name = str(d.get("name") or "").strip()[:40] or (get_ticker_info(t)[0] or "")
    _dbx("INSERT INTO lab_blog_log(ticker,name,title,kind,url,memo,at) VALUES(?,?,?,?,?,?,?)",
         (t, name, title, kind, url, str(d.get("memo") or "").strip()[:200], int(time.time())))
    _alog("blog_log", f"{kind} {t} {title[:30]}")
    logs, warn = dup_info(t, kind)
    return _admin_json({"ok": True, "dups": logs, "dup_warn": warn})


@bp.route("/admin/api/blog/log/<int:lid>", methods=["POST", "DELETE"])
def api_log_edit(lid):
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if request.method == "DELETE":
        _dbx("DELETE FROM lab_blog_log WHERE id=?", (lid,))
        _alog("blog_log_del", str(lid))
        return _admin_json({"ok": True})
    d = _json_body() or {}
    url = str(d.get("url") or "").strip()[:400]
    if url and not re.match(r"^https?://", url):
        return _admin_json({"error": "글 주소는 http(s):// 로 시작해야 해요."}, 400)
    _dbx("UPDATE lab_blog_log SET url=?, memo=? WHERE id=?", (url, str(d.get("memo") or "").strip()[:200], lid))
    return _admin_json({"ok": True})


_PREVIEWS = {}          # id -> (만든 시각, html) — 미리보기용 임시 보관(메모리, 10분)


def _preview_gc():
    now = time.time()
    for k in [k for k, v in _PREVIEWS.items() if now - v[0] > 600]:
        _PREVIEWS.pop(k, None)
    while len(_PREVIEWS) > 30:
        _PREVIEWS.pop(min(_PREVIEWS, key=lambda k: _PREVIEWS[k][0]), None)


@bp.route("/admin/api/blog/preview", methods=["POST"])
def api_preview_put():
    """관리자 화면은 보안 설정(CSP)이 엄격해 글 서식을 직접 못 그린다 — 서버가 별도 문서로 내어주고 틀(iframe)로 보여준다."""
    deny = _admin_deny()
    if deny:
        return deny
    h = str((_json_body() or {}).get("html") or "")
    if not h or len(h) > 800000:
        return _admin_json({"error": "미리볼 내용이 없거나 너무 커요."}, 400)
    import secrets
    _preview_gc()
    pid = secrets.token_urlsafe(12)
    _PREVIEWS[pid] = (time.time(), h)
    return _admin_json({"id": pid})


@bp.route("/admin/blog/preview/<pid>")
def api_preview_get(pid):
    deny = _admin_deny()
    if deny:
        return deny
    hit = _PREVIEWS.get(pid)
    if not hit:
        return "미리보기가 만료됐어요. 다시 [글 만들기]를 눌러 주세요.", 404
    doc = ('<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta name="referrer" content="no-referrer"></head><body style="margin:0;padding:14px;background:#fff">' + hit[1] + "</body></html>")
    resp = Response(doc, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    return resp


@bp.route("/admin/assets/blogkit.js")
def asset_js():
    deny = _admin_deny()
    if deny:
        return deny
    resp = Response(BLOGKIT_JS, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ══════════════════════════════════════════════════════════════
# 블로그 HTML 공용 부품 (원본 방식: 표 + 인라인 서식)
# ══════════════════════════════════════════════════════════════
NAVY, GOLD, BROWN, LINE, TXT = "#1a2744", "#fbbf24", "#92400e", "#e5e7eb", "#1f2937"
FONT = "font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;"


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def tone(score):
    return "#16a34a" if score >= 70 else ("#d97706" if score >= 50 else "#dc2626")


def updown(v):
    return "#c62828" if (v or 0) > 0 else ("#1565c0" if (v or 0) < 0 else "#374151")


def title_bar(title, color=NAVY):
    """큰 제목 띠(색 배경 + 흰 글씨)."""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 8px;{FONT}"><tr>'
            f'<td bgcolor="{color}" style="background-color:{color};padding:11px 16px;border-radius:8px;">'
            f'<span style="font-size:16px;font-weight:900;color:#ffffff;">{title}</span></td></tr></table>')


def side_title(title, accent="#4f46e5"):
    """원본 심층분석 스타일 — 왼쪽 굵은 선 + 밑줄 제목."""
    return (f'<div style="font-size:16px;font-weight:900;color:{NAVY};margin:26px 0 11px;padding:5px 0 9px 13px;border-left:5px solid {accent};'
            f'border-bottom:2px solid #eef2ff;letter-spacing:-0.3px;line-height:1.4;{FONT}">{title}</div>')


def bar(score, color):
    w = int(clamp(score))
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
            f'<td width="{w}%" bgcolor="{color}" style="background-color:{color};height:12px;font-size:1px;line-height:12px;">&nbsp;</td>'
            f'<td width="{100 - w}%" bgcolor="#e5e7eb" style="background-color:#e5e7eb;height:12px;font-size:1px;line-height:12px;">&nbsp;</td></tr></table>')


def inline(s, accent=None):
    s = E(s)
    s = re.sub(r"\*\*(.+?)\*\*", r'<b style="color:#111827;">\1</b>', s)
    if accent:
        s = re.sub(r"([0-9][0-9,\.]*\s?(?:%|배|억원|조원|원|년|일|점))", lambda m: f'<b style="color:{accent};">{m.group(1)}</b>', s)
    return s


def section_card(icon, title, subtitle, text, accent="#4f46e5", tint="#f5f6ff"):
    """원본 심층분석의 AI 섹션 카드 — 색 헤더 + 연한 본문 박스. 본문은 문단별(빈 줄 기준)로 나눠 숫자를 굵게."""
    if not text or not str(text).strip():
        return ""
    paras = []
    for i, p in enumerate(re.split(r"\n\s*\n", str(text).strip())):
        p = p.strip()
        if not p:
            continue
        lines = [inline(x, accent) for x in p.split("\n") if x.strip()]
        paras.append(f'<p style="font-size:15px;color:#1f2937;line-height:2.0;margin:0 0 15px 0;word-break:keep-all;letter-spacing:-0.2px;">' + "<br>".join(lines) + "</p>")
    sub = f'<span style="font-size:12px;font-weight:700;color:#e5e7eb;margin-left:8px;">{E(subtitle)}</span>' if subtitle else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:22px 0;{FONT}">'
            f'<tr><td bgcolor="{accent}" style="background-color:{accent};padding:13px 20px;border-radius:12px 12px 0 0;">'
            f'<span style="font-size:17px;font-weight:900;color:#ffffff;letter-spacing:-0.3px;">{icon} {E(title)}</span>{sub}</td></tr>'
            f'<tr><td bgcolor="{tint}" style="background-color:{tint};padding:18px 22px;border:1px solid #e5e7eb;border-top:none;border-left:5px solid {accent};'
            f'border-radius:0 0 12px 12px;">{"".join(paras)}</td></tr></table>')


def ai_to_html(text):
    """AI 답변(마크다운 비슷한 글) → 서식 있는 HTML 조각. 모든 글자는 이스케이프한다."""
    if not text or not text.strip():
        return ""
    parts, buf = [], []

    def flush():
        if buf:
            parts.append('<p style="font-size:15px;color:#1e293b;line-height:2.0;margin:0 0 12px;word-break:keep-all;">' + "<br>".join(buf) + "</p>")
            buf.clear()
    for raw in text.replace("\r", "").split("\n"):
        t = raw.strip()
        if not t:
            flush()
            continue
        if re.match(r"^#{1,4}\s+", t) or re.match(r"^\[\d+[.)]", t):
            flush()
            title = re.sub(r"^#{1,4}\s*", "", t).strip("[] ")
            parts.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 8px;"><tr>'
                         f'<td style="border-left:6px solid {GOLD};padding:6px 12px;font-size:17px;font-weight:900;color:{NAVY};{FONT}">{inline(title)}</td></tr></table>')
        elif re.match(r"^[-•·*]\s+", t):
            flush()
            item = inline(re.sub(r"^[-•·*]\s+", "", t))
            parts.append('<p style="font-size:15px;color:#1e293b;line-height:1.9;margin:0 0 6px;padding-left:12px;">• ' + item + "</p>")
        else:
            buf.append(inline(t))
    flush()
    return "".join(parts)


def split_sections(text):
    """'## 1. 제목' 형식의 AI 답변을 {번호: (제목, 본문)} 로 나눈다(번호가 없는 앞부분은 0)."""
    out, cur, buf = {}, 0, []
    title = ""
    for ln in str(text or "").replace("\r", "").split("\n"):
        m = re.match(r"^#{1,4}\s*(\d+)[.)]?\s*(.*)$", ln.strip())
        if m:
            if buf or title:
                out[cur] = (title, "\n".join(buf).strip())
            cur, title, buf = int(m.group(1)), m.group(2).strip(), []
        else:
            buf.append(ln)
    if buf or title:
        out[cur] = (title, "\n".join(buf).strip())
    return out


def extract_titles(ai_text):
    out, on = [], False
    for ln in (ai_text or "").splitlines():
        s = ln.strip()
        if re.match(r"^#{1,4}\s*\d+[.)]?\s*블로그 제목", s) or ("블로그 제목" in s and s.startswith("[")):
            on = True
            continue
        if on:
            if s.startswith("#") or s.startswith("["):
                break
            m = re.match(r"^[-•·*\d.)\s]+(.+)$", s)
            if m and len(m.group(1).strip()) >= 6:
                out.append(re.sub(r"[\"“”]", "", m.group(1)).strip("* ").strip())
    return out[:5]


def head_box(kicker, title_html, sub, warn_html=""):
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;{FONT}"><tr>'
            f'<td bgcolor="{NAVY}" align="center" style="background-color:{NAVY};padding:24px 16px;border-top:6px solid {GOLD};">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;color:{GOLD};margin-bottom:6px;">{E(kicker)}</div>'
            f'<div style="font-size:24px;font-weight:900;color:#ffffff;">{title_html}</div>'
            f'<div style="font-size:13px;color:#d1d5db;margin-top:8px;">{sub}</div></td></tr>'
            f'<tr><td bgcolor="#fff3cd" style="background-color:#fff3cd;padding:12px 16px;border-left:5px solid #f59e0b;"><div style="font-size:12.5px;color:{BROWN};line-height:1.9;">'
            '&#9888;&#65039; <b>투자 경고문</b> | 본 자료는 공개 데이터를 정리한 참고 정보이며 <b>특정 종목의 매수·매도를 권유하지 않습니다.</b> 주식 투자는 원금 손실의 위험이 있고, 투자 결정과 손익의 책임은 <b>투자자 본인</b>에게 있습니다.</div></td></tr>'
            + warn_html + '</table>')


def seo_box(title, copy, keywords):
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;border-collapse:collapse;{FONT}"><tr>'
            f'<td bgcolor="#ffffff" style="background-color:#ffffff;border:2px solid {BROWN};padding:14px 18px;">'
            f'<div style="font-size:17px;font-weight:900;color:#111827;line-height:1.55;word-break:keep-all;">&#128204; {E(title)}</div>'
            f'<div style="font-size:13px;color:{TXT};line-height:1.8;margin-top:8px;">&#128161; {E(copy)}<br>'
            f'<span style="color:#8a7f6a;font-size:12px;">&#128273; 검색키워드: {E(", ".join(keywords))}</span></div></td></tr></table>')


def delist_box(dr):
    """상장폐지·거래정지 위험 신호가 있을 때 글 위쪽에 붙이는 빨간 경고(없으면 빈 글자)."""
    if not isinstance(dr, dict) or dr.get("level") in (None, "", "none"):
        return ""
    rs = "".join(f'<div style="margin-top:4px;">&#8226; {E(r)}</div>' for r in (dr.get("reasons") or [])[:4])
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0;border-collapse:collapse;{FONT}"><tr><td bgcolor="#7f1d1d" '
            f'style="background-color:#7f1d1d;padding:14px 18px;border-radius:10px;"><div style="font-size:14px;font-weight:900;color:#fde047;">&#9888;&#65039; 상장폐지·거래정지 관련 유의 신호</div>'
            f'<div style="font-size:12.5px;color:#fecaca;line-height:1.8;margin-top:6px;">공개 데이터상 아래 신호가 관찰됩니다. 자동 추정이라 오류가 있을 수 있으니 KRX·DART 공시로 반드시 직접 확인하세요.{rs}</div></td></tr></table>')


def engage_box():
    def cell(emoji, head, sub, bg, bd, hc, sc):
        return (f'<td width="32%" bgcolor="{bg}" align="center" valign="top" style="background-color:{bg};padding:16px 8px;border:3px solid {bd};">'
                f'<div style="font-size:30px;line-height:1;margin-bottom:6px;">{emoji}</div><div style="font-size:14px;font-weight:900;color:{hc};margin-bottom:4px;">{head}</div>'
                f'<div style="font-size:11px;color:{sc};line-height:1.7;">{sub}</div></td>')
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0;border-collapse:collapse;' + FONT + '"><tr>'
            f'<td colspan="5" bgcolor="{NAVY}" align="center" style="background-color:{NAVY};padding:12px 16px;">'
            f'<div style="font-size:16px;font-weight:900;color:{GOLD};">&#10024; 이 포스팅이 도움이 되셨나요? &#10024;</div>'
            '<div style="font-size:11px;color:#d1d5db;margin-top:4px;">여러분의 응원이 더 좋은 분석 콘텐츠를 만드는 힘이 됩니다 &#128591;</div></td></tr><tr>'
            + cell("&#10084;&#65039;", "공감 클릭", "하단 &#9829; 버튼을<br>눌러 응원해 주세요!", "#fff0f3", "#f87171", "#c62828", "#7f1d1d")
            + '<td width="2%" bgcolor="#e5e7eb" style="background-color:#e5e7eb;"></td>'
            + cell("&#128172;", "댓글 환영", "궁금한 종목이나<br>의견을 남겨주세요!", "#eff6ff", "#60a5fa", "#1d4ed8", "#1e3a5f")
            + '<td width="2%" bgcolor="#e5e7eb" style="background-color:#e5e7eb;"></td>'
            + cell("&#129309;", "서로이웃 신청", "매일 분석을<br>이웃과 함께 보세요!", "#f0fdf4", "#34d399", "#065f46", "#064e3b")
            + "</tr></table>")


def risk_box():
    lines = ["본 글은 공개 데이터와 AI 도구로 정리한 <b style=\"color:#991b1b;\">참고 자료</b>이며 <b style=\"color:#991b1b;\">투자 권유가 아닙니다.</b>",
             "제시된 수치는 <b style=\"color:#991b1b;\">과거·현재 시점의 데이터</b>이며 <b style=\"color:#991b1b;\">미래 수익을 보장하지 않습니다.</b>",
             "공시·뉴스는 제목 기준으로 정리했으므로 <b style=\"color:#991b1b;\">원문을 직접 확인</b>하시기 바랍니다.",
             "<b style=\"color:#991b1b;\">모든 투자 결정과 손익은 투자자 본인에게 귀속</b>됩니다."]
    body = "".join(f'<span style="color:#7f1d1d;">&#128308; {t}</span><br>' for t in lines)
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="border:3px solid #f87171;margin:18px 0 10px;border-collapse:collapse;' + FONT + '"><tr>'
            '<td bgcolor="#fef2f2" style="background-color:#fef2f2;padding:14px 18px;"><div style="font-size:14px;font-weight:900;color:#991b1b;text-align:center;margin-bottom:8px;">&#9888;&#65039; 투자 위험 고지</div>'
            f'<table width="100%" cellpadding="0" cellspacing="0"><tr><td bgcolor="#ffffff" style="background-color:#ffffff;padding:11px 14px;"><p style="font-size:12px;line-height:1.9;margin:0;">{body}</p></td></tr></table></td></tr></table>')


def delist_blocks(risk, name="", ticker=""):
    """상장폐지·거래정지 위험 신호가 있을 때 글 위쪽(눈에 띄게)·아래쪽(자세히)에 넣을 경고 상자.
    단정·예측 표현은 피하고 '공개 데이터상 ~로 표시/확인된다'로만 쓰며, 확인은 원문(KIND·DART)으로 돌린다. 위험이 없으면 ("", "", [])."""
    risk = risk or {}
    lv = risk.get("level")
    if lv not in ("danger", "caution"):
        return "", "", []
    nm = E(name or "해당 종목")
    reasons = [str(r) for r in (risk.get("reasons") or []) if r][:6]
    strong = lv == "danger"
    bd, bg, tc, ac = ("#dc2626", "#fef2f2", "#991b1b", "#b91c1c") if strong else ("#d97706", "#fffbeb", "#92400e", "#b45309")
    head = ("&#128680; 투자 유의 — 거래 상태와 관련된 이상 신호가 공개 데이터에서 확인되었습니다" if strong
            else "&#9888;&#65039; 투자 유의 — 거래 상태와 관련해 살펴볼 만한 정황이 일부 확인되었습니다")
    lead = (f'<table width="100%" cellpadding="0" cellspacing="0" style="border:3px solid {bd};border-collapse:collapse;margin:0 0 14px;{FONT}"><tr>'
            f'<td bgcolor="{bg}" style="background-color:{bg};padding:13px 16px;">'
            f'<div style="font-size:15px;font-weight:900;color:{tc};line-height:1.6;">{head}</div>'
            f'<div style="font-size:12.5px;color:{tc};line-height:1.85;margin-top:6px;">{nm}에 대해 공개된 시세·거래상태 데이터에서 아래와 같은 신호가 표시되어 있습니다. '
            f'이는 <b>상장폐지나 거래정지를 단정하거나 예측하는 내용이 아니며</b>, 자동 점검 결과를 참고용으로 옮긴 것입니다. '
            f'매매 전 <b>한국거래소(KIND)·DART의 공시 원문</b>으로 실제 지정 여부와 사유를 꼭 직접 확인해 주세요.</div></td></tr></table>')
    li = "".join(f'<tr><td width="4%" valign="top" style="padding:4px 0;font-size:13px;color:{ac};">&#9642;</td><td style="padding:4px 0;font-size:13px;color:#374151;line-height:1.75;">{E(r)}</td></tr>' for r in reasons)
    kind = "https://kind.krx.co.kr/common/searchcorpname.do?method=searchCorpNameMain&searchCorpName=" + (ticker or "")
    dart = "https://dart.fss.or.kr/dsab007/main.do?option=corp&textCrpNm=" + (ticker or "")
    bottom = (f'<table width="100%" cellpadding="0" cellspacing="0" style="border:2px solid {bd};border-collapse:collapse;margin:16px 0 6px;{FONT}"><tr>'
              f'<td bgcolor="{bg}" style="background-color:{bg};padding:14px 18px;">'
              f'<div style="font-size:14px;font-weight:900;color:{tc};margin-bottom:6px;">&#128680; 꼭 읽어 주세요 — 거래 상태 관련 유의사항</div>'
              f'<table width="100%" cellpadding="0" cellspacing="0">{li}</table>'
              f'<div style="font-size:12px;color:{tc};line-height:1.9;margin-top:8px;">'
              f'&#128308; 위 내용은 공개 데이터를 자동으로 점검한 결과로, <b>오류나 지연이 있을 수 있으며 사실 확정이 아닙니다.</b><br>'
              f'&#128308; 투자주의·경고·위험 지정, 관리종목, 거래정지, 상장적격성 심사 등 <b>실제 현황은 시시각각 달라질 수 있습니다.</b><br>'
              f'&#128308; 이런 신호가 있는 종목은 <b>가격 변동 폭과 거래 중단 위험이 클 수 있어</b> 투자 결정에 각별한 주의가 필요합니다.<br>'
              f'&#128308; 본 글은 특정 종목의 매수·매도를 권유하지 않으며, <b>모든 판단과 책임은 투자자 본인에게 있습니다.</b><br>'
              f'<a href="{kind}" target="_blank" style="color:#1d4ed8;font-weight:800;">KIND 공시 확인</a> · '
              f'<a href="{dart}" target="_blank" style="color:#1d4ed8;font-weight:800;">DART 확인</a></div></td></tr></table>')
    return lead, bottom, ["투자유의", "거래상태확인"]


def hashtags(names, date_str, extra=()):
    base = ["주식투자", "재테크", "주식분석", "기술적분석", "국내주식"]
    ex = [re.sub(r"\s", "", n or "") for n in names] + [re.sub(r"[년월일\s.\-]", "", date_str)]
    tags = [t for t in dict.fromkeys(list(extra) + ex + base) if t]
    return tags, '<div style="margin-top:14px;padding:10px 0;border-top:1px solid #e5e7eb;font-size:11px;color:#6b7280;line-height:2.2;">' + " ".join("#" + t for t in tags) + "</div>"


def date_korean(now):
    return f"{now.year}년 {now.month}월 {now.day}일"


# ══════════════════════════════════════════════════════════════
# 화면 JS — BlogKit (관리자 화면 공용 + 메인 화면 분석실에서 같이 씀)
# 규칙: {{ {% {# 를 쓰지 않는다. 다른 JS 도구에 기대지 않는 독립 코드.
# ══════════════════════════════════════════════════════════════
BLOGKIT_JS = r"""
(function(){
if(window.BlogKit)return;
var K={urls:null,_p:null};
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function sty(e,s){e.style.cssText=s;return e}
function csrf(){try{if(typeof CSRF!=='undefined'&&CSRF)return CSRF}catch(e){}return (window.__ADM__||{}).csrf||''}
function call(u,b){var o={credentials:'same-origin',cache:'no-store'};if(b){o.method='POST';o.headers={'Content-Type':'application/json','X-CSRF-Token':csrf()};o.body=JSON.stringify(b)}
 return fetch(u,o).then(function(r){return r.json().catch(function(){return {error:'응답을 읽지 못했어요'}})})}
function toast(m){try{if(typeof window.showToast==='function'){window.showToast(m);return}}catch(e){}try{if(typeof window.toast==='function'){window.toast(m);return}}catch(e){}alert(m)}
K.load=function(force){if(force)K._p=null;if(!K._p)K._p=call('/admin/api/blog/urls').then(function(j){K.urls=j;return j}).catch(function(){return {menus:[],auto_open:true}});return K._p};
K.urlOf=function(key){var m=((K.urls||{}).menus||[]).filter(function(x){return x.key===key})[0];return m?m.url:'https://blog.naver.com/GoBlogWrite.naver'};
K.labelOf=function(key){var m=((K.urls||{}).menus||[]).filter(function(x){return x.key===key})[0];return m?m.label:key};
K.autoOpen=function(){return !K.urls||K.urls.auto_open!==false};
// 서식(text/html) 그대로 복사 — copy 이벤트를 가로채 HTML 과 글자를 함께 싣는다(원본 방식). 동기 실행이라 바로 뒤에 창을 열어도 팝업 차단에 안 걸린다.
K.copyHtml=function(html){var plain=html.replace(/<[^>]+>/g,' ').replace(/&nbsp;/g,' ').replace(/\s+/g,' ').trim();var ok=false;
 try{var ta=document.createElement('textarea');ta.value=' ';ta.setAttribute('readonly','');ta.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.appendChild(ta);ta.focus();ta.select();var done=false;
  var h=function(e){try{e.clipboardData.setData('text/html',html);e.clipboardData.setData('text/plain',plain);e.preventDefault();done=true}catch(x){}};
  document.addEventListener('copy',h,true);var r=false;try{r=document.execCommand('copy')}catch(x){}document.removeEventListener('copy',h,true);document.body.removeChild(ta);ok=!!(r&&done)}catch(e){}
 if(!ok){try{if(navigator.clipboard&&window.ClipboardItem){navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([html],{type:'text/html'}),'text/plain':new Blob([plain],{type:'text/plain'})})]);ok=true}}catch(e){}}
 return ok};
K.save=function(name,title,html){var b=new Blob(['<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>'+String(title||'').replace(/</g,'')+'</title></head><body style="max-width:860px;margin:0 auto;padding:20px">'+html+'</body></html>'],{type:'text/html'});var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},500)};
function bt(txt,primary,fn){var b=el('button',null,txt);sty(b,'font:inherit;font-size:13px;font-weight:700;border-radius:10px;padding:8px 14px;cursor:pointer;margin:0 6px 6px 0;border:1.5px solid '+(primary?'#312e81':'#c7d2fe')+';background:'+(primary?'#312e81':'#fff')+';color:'+(primary?'#fff':'#312e81'));b.onclick=fn;return b}
// opt: {key,kind,ticker,name,sections:[[k,label]],build:function(inc,title)->Promise<{html,title,titles,tags,size,ok_size,dup_warn}>,dup_warn:'',idp:'접두어'}
K.panel=function(box,opt){var idp=opt.idp||'bk';box.innerHTML='';
 var dw=el('div');dw.id=idp+'Dup';sty(dw,'background:#fff7ed;border:1.5px solid #fdba74;color:#9a3412;border-radius:10px;padding:9px 12px;font-size:12.5px;line-height:1.6;margin:6px 0;display:'+(opt.dup_warn?'':'none'));dw.textContent=opt.dup_warn?('⚠ '+opt.dup_warn):'';box.appendChild(dw);
 var inc={};if(opt.sections&&opt.sections.length){var ck=el('div');sty(ck,'margin:6px 0');opt.sections.forEach(function(a){var l=el('label');sty(l,'font-size:12.5px;margin-right:12px;white-space:nowrap');var i=el('input');i.type='checkbox';i.checked=true;i.dataset.k=a[0];inc[a[0]]=true;i.onchange=function(){inc[a[0]]=i.checked};l.appendChild(i);l.appendChild(document.createTextNode(' '+a[1]));ck.appendChild(l)});box.appendChild(ck)}
 var ti=el('input');ti.type='text';ti.id=idp+'Title';ti.maxLength=150;ti.placeholder='글 제목 (비우면 자동 · AI가 제목 후보를 주면 첫 번째 사용)';sty(ti,'width:100%;box-sizing:border-box;font:inherit;font-size:13px;border:1.5px solid #d1d5db;border-radius:9px;padding:8px;margin:4px 0');box.appendChild(ti);
 var last=null,mainFn=null;var r=el('div');var out=el('div');var go=bt('🧱 글 만들기',true,function(){make()});r.appendChild(go);box.appendChild(r);box.appendChild(out);
 K.load();
 function make(){out.innerHTML='';out.appendChild(sty(el('div',null,'⏳ 만드는 중…'),'font-size:12.5px;color:#6b7280'));go.disabled=true;
  Promise.resolve(opt.build(inc,ti.value)).then(function(j){go.disabled=false;out.innerHTML='';if(!j||j.error){out.appendChild(sty(el('div',null,'⚠ '+((j&&j.error)||'만들지 못했어요')),'color:#b91c1c;font-size:13px'));return}
   if(!ti.value)ti.value=j.title||'';
    last=j;if(opt.onBuilt){try{opt.onBuilt(j)}catch(x){}}
   if(j.dup_warn!=null){dw.textContent=j.dup_warn?('⚠ '+j.dup_warn):'';dw.style.display=j.dup_warn?'':'none'}
   if(j.titles&&j.titles.length){var tl=sty(el('div',null,'AI 제목 후보: '),'font-size:12px;color:#6b7280;margin:6px 0');j.titles.forEach(function(t){var a=bt(t.length>34?t.slice(0,34)+'…':t,false,function(){ti.value=t});sty(a,'margin:2px;padding:3px 9px;font-size:12px');tl.appendChild(a)});out.appendChild(tl)}
   K.load().then(function(){
    var lab=K.labelOf(opt.key),ao=K.autoOpen();var rr=el('div');
    mainFn=function(){var ok=K.copyHtml(j.html);if(!ok){toast('복사가 막혔어요. 아래 [HTML 파일로 저장]을 쓰거나 미리보기를 드래그해 복사하세요.');return}if(opt.onCopied){try{opt.onCopied()}catch(x){}}
     if(ao){window.open(K.urlOf(opt.key),'_blank','noopener');toast('📋 복사했어요 — 열린 블로그 글쓰기 화면에서 Ctrl+V 하세요 ('+lab+')')}else toast('📋 블로그용 HTML을 복사했어요 — 블로그 글쓰기 화면에서 Ctrl+V 하세요.')};
    var main=bt(ao?'📋 복사하고 블로그 열기':'📋 서식 그대로 복사',true,mainFn);
    rr.appendChild(main);
    if(ao)rr.appendChild(bt('복사만',false,function(){toast(K.copyHtml(j.html)?'📋 복사했어요.':'복사가 막혔어요.')}));
    rr.appendChild(bt('✍ 블로그만 열기',false,function(){window.open(K.urlOf(opt.key),'_blank','noopener')}));
    rr.appendChild(bt('💾 HTML 파일로 저장',false,function(){K.save((opt.ticker||'blog')+'_'+(opt.kind||'blog')+'.html',j.title,j.html)}));
    out.appendChild(rr);
    var info=sty(el('div',null,'열리는 곳: '+lab+' → '+K.urlOf(opt.key)+' · 글 크기 '+Math.round((j.size||j.html.length)/1000)+'KB'+(j.tags&&j.tags.length?' · 태그 '+j.tags.map(function(t){return '#'+t}).join(' '):'')+(j.ok_size===false?' — ⚠ 너무 커서 일부 섹션을 빼고 다시 만드세요':'')),'font-size:12px;color:#6b7280;line-height:1.6;margin:2px 0 8px');out.appendChild(info);
    var fr=document.createElement('iframe');fr.setAttribute('sandbox','');sty(fr,'width:100%;height:520px;border:1.5px solid #d1d5db;border-radius:10px;background:#fff');out.appendChild(fr);
    call('/admin/api/blog/preview',{html:j.html}).then(function(z){if(z.id)fr.src='/admin/blog/preview/'+z.id});
    var lg=sty(el('div'),'margin-top:12px;border-top:1px dashed #c7d2fe;padding-top:10px');lg.appendChild(sty(el('b',null,'✅ 블로그에 올렸다면 기록 남기기 (중복 방지)'),'font-size:13px'));
    var u=el('input');u.type='text';u.placeholder='올린 글 주소(선택) https://blog.naver.com/…';sty(u,'width:100%;box-sizing:border-box;font:inherit;font-size:13px;border:1.5px solid #d1d5db;border-radius:9px;padding:8px;margin:6px 0 4px');lg.appendChild(u);
    var m=el('input');m.type='text';m.placeholder='메모(선택)';sty(m,'width:100%;box-sizing:border-box;font:inherit;font-size:13px;border:1.5px solid #d1d5db;border-radius:9px;padding:8px;margin:0 0 6px');lg.appendChild(m);
    var sv=bt('작성 기록 남기기',true,function(){call('/admin/api/blog/log',{ticker:opt.ticker,name:opt.name,title:ti.value||j.title,url:u.value,memo:m.value,kind:opt.kind||'stock'}).then(function(z){if(z.error){toast(z.error);return}toast('작성 기록을 남겼어요 (관리자 화면 📝 블로그 이력)');dw.textContent='⚠ '+z.dup_warn;dw.style.display='';sv.disabled=true;sv.textContent='기록 완료';if(opt.onLogged)opt.onLogged(z)})});lg.appendChild(sv);out.appendChild(lg)})})}
 return {rebuild:make,built:function(){return !!last},copyOpen:function(){if(mainFn)mainFn();else toast('먼저 [글 만들기]를 눌러 글을 만드세요.')}}};
window.BlogKit=K;
})();
"""

TAB_JS = r"""
var BU={S:null,draft:null};
function buLoad(p){api('/admin/api/blog/urls').then(function(j){if(cur!=='bu')return;BU.S=j;BU.draft=JSON.parse(JSON.stringify(j));buDraw(p)})}
function buDraw(p){p.innerHTML='';var D=BU.draft;
 var top=el('div','c');top.appendChild(el('b',null,'✍ 블로그 글쓰기 주소'));
 top.appendChild(el('p','note','메뉴마다 글을 올릴 블로그(카테고리) 주소를 미리 정해 둬요. 원본 프로그램에서 쓰던 카테고리 번호가 이미 들어가 있습니다. 글을 만든 뒤 [📋 복사하고 블로그 열기]를 누르면 서식이 복사되고 이 주소의 글쓰기 화면이 바로 열려요 — 붙여넣기(Ctrl+V)만 하면 됩니다.'));
 var r=el('div','bar');r.appendChild(el('span','m','블로그 아이디'));var idi=el('input');idi.value=D.id;idi.maxLength=30;idi.style.width='160px';idi.oninput=function(){D.id=idi.value;buDirty()};r.appendChild(idi);
 r.appendChild(el('span','m',' 기본 주소는 https://blog.naver.com/아이디?Redirect=Write&categoryNo=번호 형태예요. 아이디를 바꾸면 "수정 안 한" 메뉴의 기본 주소가 같이 바뀝니다.'));top.appendChild(r);
 var r2=el('label','bar');var cb=el('input');cb.type='checkbox';cb.checked=D.auto_open!==false;cb.onchange=function(){D.auto_open=cb.checked;buDirty()};r2.appendChild(cb);r2.appendChild(el('span',null,' 복사하면 블로그 글쓰기 화면을 바로 함께 열기 (끄면 복사만 해요)'));top.appendChild(r2);
 var sv=bt('💾 저장','bt',function(){buSave(p)});sv.id='busave';top.appendChild(sv);p.appendChild(top);
 var c=el('div','c');var tw=el('div');tw.style.overflowX='auto';var t=el('table'),h=el('tr');['메뉴','블로그 글쓰기 주소','상태',''].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 D.menus.forEach(function(m){var tr=el('tr');tr.appendChild(el('td',null,m.label));var td=el('td');var i=el('input');i.value=m.url;i.style.width='min(560px,70vw)';i.oninput=function(){m.url=i.value;buDirty()};td.appendChild(i);tr.appendChild(td);
  tr.appendChild(el('td','m',m.url!==m.default?'✏ 수정됨':'기본값'));
  var a=el('td');var lk=el('a',null,'열어보기');lk.href=m.url;lk.target='_blank';lk.rel='noopener';a.appendChild(lk);a.appendChild(bt('기본값','bt3',function(){m.url=D.id&&BU.S?m.default.replace(/blog\.naver\.com\/[^?]+/,'blog.naver.com/'+D.id):m.default;buDirty();buDraw(p)}));tr.appendChild(a);t.appendChild(tr)});
 tw.appendChild(t);c.appendChild(tw);c.appendChild(el('p','note','※ 앞의 3개(종목분석·기업심층분석·오늘추천)가 지금 쓰는 메뉴이고, 나머지는 원본 프로그램의 메뉴로 앞으로 옮겨 올 때 바로 쓰도록 미리 넣어 둔 주소예요. 네이버 블로그 말고 다른 블로그 주소를 넣어도 됩니다.'));p.appendChild(c)}
function buDirty(){var b=$('busave');if(b)b.textContent='💾 저장 (변경사항 있음)'}
function buSave(p){var D=BU.draft;var urls={};D.menus.forEach(function(m){urls[m.key]=m.url});
 apiJ('/admin/api/blog/urls',{id:D.id,auto_open:D.auto_open,urls:urls}).then(function(j){if(j.error){toast(j.error);return}BU.S=j;BU.draft=JSON.parse(JSON.stringify(j));if(window.BlogKit)window.BlogKit.load(true);toast('저장했어요');buDraw(p)})}
var BL={rows:[],q:'',kind:'',multi:[]};
function blLoad(p){api('/admin/api/blog/log?q='+encodeURIComponent(BL.q||'')+'&kind='+encodeURIComponent(BL.kind||'')).then(function(j){if(cur!=='bl')return;BL.rows=j.rows||[];BL.multi=j.multi||[];BL.kinds=j.kinds||{};blDraw(p)})}
function blDraw(p){p.innerHTML='';var top=el('div','c');top.appendChild(el('b',null,'📝 블로그 작성 이력'));
 top.appendChild(el('p','note','분석실·심층분석·오늘추천에서 블로그 글을 만든 뒤 남긴 기록이에요. 같은 종목을 같은 메뉴로 또 쓰면 ⚠ 표시가 붙고, 글을 만들 때도 경고가 떠서 중복 작성을 막아 줍니다. 총 '+BL.rows.length+'건'+(BL.multi.length?' · 2건 이상 쓴 종목 '+BL.multi.length+'개':'')+'.'));
 var q=el('input');q.placeholder='종목명·코드·제목 검색';q.value=BL.q;q.style.width='220px';q.onkeydown=function(e){if(e.key==='Enter'){BL.q=q.value;blLoad(p)}};top.appendChild(q);
 var ks=el('select');[['','모든 메뉴']].concat(Object.keys(BL.kinds||{}).map(function(k){return [k,BL.kinds[k]]})).forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];if(o[0]===BL.kind)op.selected=true;ks.appendChild(op)});ks.onchange=function(){BL.kind=ks.value;blLoad(p)};top.appendChild(ks);
 top.appendChild(bt('🔍 검색','bt2',function(){BL.q=q.value;blLoad(p)}));p.appendChild(top);
 var lc=el('div','c');var tw=el('div');tw.style.overflowX='auto';var t=el('table'),h=el('tr');['날짜','메뉴','종목','제목','글 주소','메모',''].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 BL.rows.forEach(function(r){var tr=el('tr');var d=new Date(r.at*1000);tr.appendChild(el('td',null,(d.getMonth()+1)+'/'+d.getDate()+' '+('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)));
  tr.appendChild(el('td',null,(BL.kinds||{})[r.kind]||r.kind));var dup=BL.multi.indexOf(r.ticker+'|'+r.kind)>=0;tr.appendChild(el('td',dup?'bad':'',(dup?'⚠ ':'')+(r.name||'')+' '+r.ticker));tr.appendChild(el('td',null,r.title));
  var u=el('td');var ui=el('input');ui.value=r.url||'';ui.placeholder='https://…';ui.style.width='170px';u.appendChild(ui);tr.appendChild(u);
  var m=el('td');var mi=el('input');mi.value=r.memo||'';mi.style.width='120px';m.appendChild(mi);tr.appendChild(m);
  var a=el('td');a.appendChild(bt('💾 저장','bt3',function(){apiJ('/admin/api/blog/log/'+r.id,{url:ui.value,memo:mi.value}).then(function(j){toast(j.error?j.error:'저장했어요')})}));
  if(r.url){var lk=el('a',null,' 열기');lk.href=r.url;lk.target='_blank';lk.rel='noopener';a.appendChild(lk)}
  a.appendChild(bt('🗑 삭제','bt3',function(){if(!confirm('이 기록을 지울까요?'))return;fetch('/admin/api/blog/log/'+r.id,{method:'DELETE',credentials:'same-origin',headers:{'X-CSRF-Token':CSRF}}).then(function(){blLoad(p)})}));tr.appendChild(a);t.appendChild(tr)});
 if(!BL.rows.length){var tr=el('tr'),td=el('td',null,'아직 기록이 없어요.');td.colSpan=7;tr.appendChild(td);t.appendChild(tr)}
 tw.appendChild(t);lc.appendChild(tw);p.appendChild(lc)}
"""


def register():
    C.register_table_hook(_ensure_table)
    C.register_settings({"naver_blog_id": DEFAULT_BLOG_ID, "blog_menu_urls": "", "blog_auto_open": "1"},
                        {"naver_blog_id": _valid_id, "blog_menu_urls": _valid_urls, "blog_auto_open": _valid_auto})
    C.register_admin_lib(BLOGKIT_JS)
    C.register_admin_tab("bu", "✍ 블로그 주소", TAB_JS, "buLoad")
    # 📝 블로그 이력 탭은 같은 JS 안에 있으므로 loader 만 따로 연결한다
    C.register_admin_tab("bl", "📝 블로그 이력", "", "blLoad")
    return bp
