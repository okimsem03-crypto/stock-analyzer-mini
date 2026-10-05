"""💧 수급분석 (기능별 등급 공개 메뉴) — 원본 프로그램 '수급분석'의 값 이식판.

원본은 요청마다 라이브(pykrx → 네이버)로 종목별 수급을 조회하지만, 웹 미니는 [📦 데이터 가져오기]로 옮겨 둔 표만 읽는다.
  · investor_scan_cache  종목별 외국인·기관 순매수 대금(원) — 1일 / 5일 / 20일 합계 (+ 기준일 base_date, 수집시각 scanned_at)
  · stock_price_cache    현재가·등락률·시총(억)·종합점수·시장 구분 (선택: 없으면 가격·시장 필터만 빠진다)
  · stock_theme_map      종목-테마 연결 (선택: 없으면 '테마별 수급'만 비어 보인다. 개인 테마(user)는 쓰지 않는다)
표가 없거나 비어 있으면 오류 대신 "📦 데이터 가져오기 메뉴에서 ○○ 표를 가져오면 보여요" 안내를 돌려준다.

신호식은 원본 그대로(캐시는 1·5·20일만 있어 원본 메뉴의 2일/10일은 재현 불가)
  · 쌍끌이   f20>0 AND i20>0                       (쌍끌이⚠: 그리고 f1<0 AND i1<0 AND |f1|+|i1| > (f20+i20)*0.3)
  · 수급전환 (f20<=0 AND f5>0) OR (i20<=0 AND i5>0)
  · 동반매도 f20<0 AND i20<0
  · 수급 점수(원본 종목발굴 점수 중 수급 항목) 쌍끌이 +18 / 쌍끌이⚠ +10 / 수급전환 +22 / 동반매도 −15
웹에서 더한 보조 지표(원본에 없음, 화면에 그렇게 표시): 지속 순매수(1·5·20일 모두 +), 수급 급증(오늘 합산이 20일 일평균의 3배↑).
신선도: base_date(없으면 scanned_at 날짜)가 오늘보다 7일 넘게 앞서면 '오래된 자료'로 보고 신호 계산에서 뺀다(표에서는 회색).
  ※ 가져온 표의 base_date 는 'YYYYMMDD' 와 'YYYY-MM-DD' 가 섞여 있어 모두 읽는다.

기능별 등급 공개: 요약·읽는 법 = 누구나, 순위·신호 = 회원, 종목별·테마별·AI·내보내기 = 2단계 이상(관리자가 [🎚 기능 공개]에서 바꿈).
한 주소는 거의 한 기능의 데이터만 내보내되, 다른 기능 값이 섞인 곳(종목별 응답의 '테마', 순위·종목별·테마 응답의 신호 칩·점수)은 잠기면 뺀다.
추천형 문구는 쓰지 않는다 — 정보 제공형 + 투자 권유 아님 안내.
"""
import re
import threading
import time
from collections import Counter
from datetime import timedelta

from flask import Blueprint, request

from menu_ctx import C
import menu_blog as B

bp = Blueprint("flow", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "prompt_get", "_now_kst", "feature_ok")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

MENU = "flow"
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
STALE_DAYS = 7
CACHE_TTL = 30
INV_LBL = {"foreign": "외국인", "inst": "기관", "comb": "외국인+기관 합산"}
PER_LBL = {"1": "1일", "5": "5일", "20": "20일"}
SIG_KINDS = ("dual", "warn", "turn", "bsell", "persist", "surge")
NEED_MSG = {"investor_scan_cache": "투자자별 수급 캐시(investor_scan_cache)"}


# ══════════════════════════════════════════════════════════════
# 가져온 표 읽기 — 표·열이 없어도 오류 없이 None/빈 목록
# ══════════════════════════════════════════════════════════════
def _try(*sqls):
    """앞의 SQL부터 차례로 시도해 처음 성공한 결과를 돌려준다. 전부 실패(표 없음 등)하면 None."""
    for s in sqls:
        try:
            return _dbx(s, (), fetch=True) or []
        except Exception:
            continue
    return None


def _n(x):
    try:
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):
            return 0
        return int(round(v))
    except Exception:
        return 0


def _fl(x):
    try:
        v = float(x)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    except Exception:
        return None


def _date(s):
    """'20260918' / '2026-09-18' / '2026-09-30 07:33:47' → '2026-09-18' (읽을 수 없으면 '')."""
    d = re.sub(r"\D", "", str(s or ""))[:8]
    if len(d) < 8:
        return ""
    y, m, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
    if not (2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= dd <= 31):
        return ""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _signals(r):
    """원본 신호식(캐시 기반). 값은 모두 원 단위 — 부호만 본다."""
    f1, i1, f5, i5, f20, i20 = r["f1"], r["i1"], r["f5"], r["i5"], r["f20"], r["i20"]
    sg, score = [], 0
    dual = f20 > 0 and i20 > 0
    warn = dual and f1 < 0 and i1 < 0 and (abs(f1) + abs(i1)) > (f20 + i20) * 0.3
    if dual:
        sg.append("dual")
        score += 10 if warn else 18
        if warn:
            sg.append("warn")
    tw = []
    if f20 <= 0 and f5 > 0:
        tw.append("외국인")
    if i20 <= 0 and i5 > 0:
        tw.append("기관")
    if tw:
        sg.append("turn")
        score += 22
    if f20 < 0 and i20 < 0:
        sg.append("bsell")
        score -= 15
    pw = []
    if f1 > 0 and f5 > 0 and f20 > 0:
        sg.append("pf")
        pw.append("외국인")
    if i1 > 0 and i5 > 0 and i20 > 0:
        sg.append("pi")
        pw.append("기관")
    c1, c20 = f1 + i1, f20 + i20
    ratio = round(c1 / (c20 / 20.0), 1) if (c1 > 0 and c20 > 0) else 0
    if c1 > 0 and c20 > 0 and c1 >= 3 * (c20 / 20.0):
        sg.append("surge")
    return sg, score, tw, pw, ratio


def _build():
    """수급 표 + 시세 표 + 테마 표를 읽어 종목별 한 줄로 합친다(30초 캐시)."""
    out = {"rows": [], "by": {}, "themes": {}, "missing": [], "tables": {}, "meta": {}, "has_price": False, "has_theme": False}
    inv = _try("SELECT ticker,name,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,base_date,scanned_at,retail_1,retail_5,retail_20 FROM investor_scan_cache",
               "SELECT ticker,name,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,base_date,scanned_at,0,0,0 FROM investor_scan_cache",
               "SELECT ticker,name,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,'',scanned_at,0,0,0 FROM investor_scan_cache",
               "SELECT ticker,name,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,'','',0,0,0 FROM investor_scan_cache")
    out["tables"]["investor_scan_cache"] = None if inv is None else len(inv)
    if not inv:
        out["missing"].append("investor_scan_cache")
        return out
    pri = _try("SELECT ticker,name,market,sector,price,day_pct,cap_num,score,rsi FROM stock_price_cache",
               "SELECT ticker,name,market,'',price,day_pct,cap_num,NULL,NULL FROM stock_price_cache",
               "SELECT ticker,name,market,'',price,NULL,NULL,NULL,NULL FROM stock_price_cache")
    out["tables"]["stock_price_cache"] = None if pri is None else len(pri)
    pm = {}
    for x in pri or []:
        t = str(x[0] or "").strip().upper()
        if TICKER_RE.match(t):
            pm[t] = x
    out["has_price"] = bool(pm)
    th = _try("SELECT ticker,theme,theme_type FROM stock_theme_map WHERE theme_type IN ('naver','system')",
              "SELECT ticker,theme,'' FROM stock_theme_map")
    out["tables"]["stock_theme_map"] = None if th is None else len(th)
    now = _now_kst()
    today = now.strftime("%Y-%m-%d")
    cut = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    rows, by = [], {}
    scan_max, base_max, today_cnt = "", "", 0
    for x in inv:
        t = str(x[0] or "").strip().upper()
        if not TICKER_RE.match(t):
            continue
        v = [_n(x[k]) for k in range(2, 8)]
        if not any(v):
            continue
        p = pm.get(t)
        base, scanned = _date(x[8]), _date(x[9])
        eff = base or scanned
        r = {"ticker": t, "name": str(x[1] or (p[1] if p else "") or t)[:40], "market": str((p[2] if p else "") or "").upper() if p else "",
             "price": (_n(p[4]) or None) if p else None, "pct": _fl(p[5]) if p else None, "cap": (_n(p[6]) if p else 0),
             "score": (_n(p[7]) if (p and p[7] is not None) else None),
             "f1": v[0], "i1": v[1], "f5": v[2], "i5": v[3], "f20": v[4], "i20": v[5], "base": base, "eff": eff, "stale": bool(eff and eff < cut)}
        r["market"] = r["market"] if r["market"] in ("KOSPI", "KOSDAQ") else ""
        r["c1"], r["c5"], r["c20"] = v[0] + v[1], v[2] + v[3], v[4] + v[5]
        rt = [_n(x[10]), _n(x[11]), _n(x[12])]            # 개인 순매수(원) — 없으면 0,0,0
        if any(rt):                                       # 기타(법인 등) = −(개인+외국인+기관) 잔여 추정
            r["r1"], r["r5"], r["r20"] = rt
            r["o1"], r["o5"], r["o20"] = -(rt[0] + v[0] + v[1]), -(rt[1] + v[2] + v[3]), -(rt[2] + v[4] + v[5])
        else:
            r["r1"] = r["r5"] = r["r20"] = r["o1"] = r["o5"] = r["o20"] = None
        if r["stale"]:
            r.update(sg=[], ss=0, tw=[], pw=[], ratio=0)
        else:
            sg, ss, tw, pw, ratio = _signals(r)
            r.update(sg=sg, ss=ss, tw=tw, pw=pw, ratio=ratio)
        if base and base > base_max:
            base_max = base
        sa = str(x[9] or "")[:16]
        if sa and sa > scan_max:
            scan_max = sa
        if scanned == today:
            today_cnt += 1
        if t in by:
            rows[rows.index(by[t])] = r
        else:
            rows.append(r)
        by[t] = r
    out["rows"], out["by"] = rows, by
    tm = {}
    for x in th or []:
        t = str(x[0] or "").strip().upper()
        nm = str(x[1] or "").strip()
        if TICKER_RE.match(t) and nm and len(nm) <= 80:
            tm.setdefault(nm, set()).add(t)
    out["themes"] = tm
    out["has_theme"] = bool(tm)
    fresh = [r for r in rows if not r["stale"]]
    out["meta"] = {"count": len(rows), "fresh": len(fresh), "stale": len(rows) - len(fresh), "base_date": base_max, "last_scan": scan_max, "today_cnt": today_cnt,
                   "is_today": today_cnt > 0, "today": today, "stale_cut": cut}
    if not rows:
        out["missing"].append("investor_scan_cache")
    return out


_CACHE = {"at": 0.0, "d": None}
_LOCK = threading.Lock()


def _load(force=False):
    now = time.time()
    with _LOCK:
        d0 = _CACHE["d"]
        if not force and d0 is not None and now - _CACHE["at"] < (CACHE_TTL if d0["rows"] else 5):
            return d0
    d = _build()
    with _LOCK:
        _CACHE["d"], _CACHE["at"] = d, now
    return d


def _empty_resp(d):
    need = d.get("missing") or ["investor_scan_cache"]
    return _admin_json({"ok": True, "empty": True, "need": need,
                        "msg": "수급 자료가 아직 없어요. 📊 시장수급 메뉴에서 [종목 수급 가져오기]를 누르거나, 📦 데이터 가져오기 메뉴에서 ‘" + "’·‘".join(NEED_MSG.get(x, x) for x in need) + "’ 표를 가져오면 보여요."})


# ══════════════════════════════════════════════════════════════
# 요청 값 검사
# ══════════════════════════════════════════════════════════════
def _arg(name, allowed, default):
    v = (request.args.get(name) or "").strip()
    return v if v in allowed else default


def _iarg(name, lo, hi, default):
    try:
        v = int(str(request.args.get(name) or "").strip())
    except Exception:
        return default
    return max(lo, min(hi, v))


def _market():
    v = (request.args.get("market") or "").strip().upper()
    return v if v in ("KOSPI", "KOSDAQ") else "all"


def _fresh():
    return (request.args.get("fresh") or "1").strip() != "0"


def _pool_rows(d, market, fresh):
    rows = d["rows"]
    if fresh:
        rows = [r for r in rows if not r["stale"]]
    if market != "all":
        rows = [r for r in rows if r["market"] == market]
    return rows


def _sig_locked():
    """회원 화면(gateway)에서 [신호] 기능이 잠겨 있으면 True — 다른 기능 응답에 섞인 신호 값(칩·점수)을 뺀다."""
    return bool(request.environ.get("mini.gateway")) and not feature_ok(MENU, "sig")


def _strip_sig(it):
    for k in ("sg", "ss", "tw", "pw", "ratio"):
        it.pop(k, None)
    return it


def _item(r):
    return {"ticker": r["ticker"], "name": r["name"], "market": r["market"], "price": r["price"], "pct": r["pct"], "cap": r["cap"], "score": r["score"],
            "f1": r["f1"], "i1": r["i1"], "f5": r["f5"], "i5": r["i5"], "f20": r["f20"], "i20": r["i20"],
            "r1": r.get("r1"), "r5": r.get("r5"), "r20": r.get("r20"), "o1": r.get("o1"), "o5": r.get("o5"), "o20": r.get("o20"),
            "base": r["eff"], "stale": r["stale"], "sg": r["sg"], "ss": r["ss"]}


def _val(r, inv, per):
    if inv == "foreign":
        return r["f" + per]
    if inv == "inst":
        return r["i" + per]
    return r["c" + per]


def _ranked(d, inv, per, side, market, pool, fresh):
    """(조건에 맞는 전체 목록, 대상 종목 수). 정렬: 순매수=큰 값 먼저, 순매도=작은(더 음수) 값 먼저."""
    rows = _pool_rows(d, market, fresh)
    if pool in ("cap100", "cap300"):
        n = 100 if pool == "cap100" else 300
        keep = {r["ticker"] for r in sorted((r for r in rows if r["cap"] > 0), key=lambda r: -r["cap"])[:n]}
        rows = [r for r in rows if r["ticker"] in keep]
    elif pool == "score60":
        rows = [r for r in rows if r["score"] is not None and r["score"] >= 60]
    uni = len(rows)
    if side == "buy":
        hit = sorted((r for r in rows if _val(r, inv, per) > 0), key=lambda r: (-_val(r, inv, per), r["ticker"]))
    else:
        hit = sorted((r for r in rows if _val(r, inv, per) < 0), key=lambda r: (_val(r, inv, per), r["ticker"]))
    return hit, uni


def _rank_args():
    return (_arg("inv", INV_LBL, "comb"), _arg("period", PER_LBL, "5"), _arg("side", ("buy", "sell"), "buy"), _market(),
            _arg("pool", ("all", "cap100", "cap300", "score60"), "all"), _fresh())


# ══════════════════════════════════════════════════════════════
# API — 기능마다 주소가 따로다(회원 화면은 등록된 주소만 열림)
# ══════════════════════════════════════════════════════════════
@bp.route("/admin/api/flow/summary", methods=["GET"])
def api_summary():
    """[sum] 상태 + 신호 개수 + 시장별 합계."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    fresh = [r for r in d["rows"] if not r["stale"]]
    cnt = Counter()
    for r in fresh:
        sg = r["sg"]
        for k in ("dual", "warn", "turn", "bsell", "surge"):
            if k in sg:
                cnt[k] += 1
        if "pf" in sg or "pi" in sg:
            cnt["persist"] += 1
    mk = {}
    for name in ("KOSPI", "KOSDAQ"):
        rs = [r for r in fresh if r["market"] == name]
        mk[name] = {"n": len(rs), **{k: sum(r[k] for r in rs) for k in ("f1", "i1", "f5", "i5", "f20", "i20")}}
    m = d["meta"]
    return _admin_json({"ok": True, "status": {**m, "has_price": d["has_price"], "has_theme": d["has_theme"]},
                        "counts": {k: cnt.get(k, 0) for k in SIG_KINDS}, "market": mk})


@bp.route("/admin/api/flow/rank", methods=["GET"])
def api_rank():
    """[rank] 순위 표."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    inv, per, side, market, pool, fresh = _rank_args()
    top = _iarg("top", 1, 40, 20)
    hit, uni = _ranked(d, inv, per, side, market, pool, fresh)
    items = [_item(r) for r in hit[:top]]
    out = {"ok": True, "items": items, "matched": len(hit), "universe": uni, "base_date": d["meta"]["base_date"],
           "q": {"inv": inv, "period": per, "side": side, "market": market, "pool": pool, "top": top, "fresh": fresh}, "has_price": d["has_price"]}
    if _sig_locked():
        out["items"] = [_strip_sig(x) for x in items]
        out["locked"] = ["sig"]
    return _admin_json(out)


@bp.route("/admin/api/flow/signals", methods=["GET"])
def api_signals():
    """[sig] 신호별 종목 목록."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    kind = _arg("kind", SIG_KINDS, "dual")
    market, top = _market(), _iarg("top", 1, 60, 30)
    fresh = _fresh()
    rows = _pool_rows(d, market, fresh)
    rows = [r for r in rows if not r["stale"]]    # 신호는 신선한 자료에서만 계산한다
    if kind == "persist":
        hit = [r for r in rows if "pf" in r["sg"] or "pi" in r["sg"]]
    else:
        hit = [r for r in rows if kind in r["sg"]]
    keys = {"dual": lambda r: (-r["c20"], r["ticker"]), "warn": lambda r: (-r["c20"], r["ticker"]), "turn": lambda r: (-r["c5"], r["ticker"]),
            "bsell": lambda r: (r["c20"], r["ticker"]), "persist": lambda r: (-r["c20"], r["ticker"]), "surge": lambda r: (-r["ratio"], r["ticker"])}
    hit.sort(key=keys[kind])
    items = []
    for r in hit[:top]:
        it = _item(r)
        it["who"] = r["tw"] if kind == "turn" else (r["pw"] if kind == "persist" else [])
        it["ratio"] = r["ratio"]
        items.append(it)
    return _admin_json({"ok": True, "kind": kind, "items": items, "matched": len(hit), "base_date": d["meta"]["base_date"], "has_price": d["has_price"]})


@bp.route("/admin/api/flow/search", methods=["GET"])
def api_search():
    """[rank·stock] 종목 이름·코드 찾기 — 수급 표에 있는 종목만(이름·코드·시장만 돌려줌)."""
    deny = _admin_deny()
    if deny:
        return deny
    q = (request.args.get("q") or "").strip()[:20]
    if not q:
        return _admin_json({"rows": []})
    d = _load()
    ql = q.replace(" ", "").lower()
    out = []
    for r in d["rows"]:
        nm = r["name"].replace(" ", "").lower()
        if ql in nm or ql in r["ticker"].lower():
            out.append((0 if (nm == ql or r["ticker"].lower() == ql) else 1 if nm.startswith(ql) else 2, len(nm), r))
    out.sort(key=lambda x: (x[0], x[1], x[2]["ticker"]))
    return _admin_json({"rows": [{"ticker": x[2]["ticker"], "name": x[2]["name"], "market": x[2]["market"]} for x in out[:12]]})


@bp.route("/admin/api/flow/stock", methods=["GET"])
def api_stock():
    """[stock] 종목 하나의 수급(1·5·20일) + 같은 시장 내 순위. 테마 목록은 [theme] 기능이라 잠겨 있으면 뺀다."""
    deny = _admin_deny()
    if deny:
        return deny
    t = (request.args.get("ticker") or "").strip().upper()
    if not TICKER_RE.match(t):
        return _admin_json({"error": "종목코드는 6자리 영문·숫자예요(예: 005930)."}, 400)
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    r = d["by"].get(t)
    if not r:
        return _admin_json({"error": "수급 자료에 이 종목이 없어요. (수급 자료는 시가총액 상위 종목 위주예요)"}, 404)
    pos = {}
    if not r["stale"]:
        peers = [x for x in d["rows"] if not x["stale"] and (not r["market"] or x["market"] == r["market"])]
        for k in ("c5", "c20"):
            pos[k] = [1 + sum(1 for x in peers if x[k] > r[k]), len(peers)]
    it = _item(r)
    it["tw"], it["pw"], it["ratio"] = r["tw"], r["pw"], r["ratio"]
    out = {"ok": True, "item": it, "pos": pos, "market_scope": r["market"] or "전체", "has_price": d["has_price"]}
    locked = []
    if _sig_locked():
        _strip_sig(it)
        locked.append("sig")
    themes = sorted(nm for nm, s in d["themes"].items() if t in s)[:10]
    if request.environ.get("mini.gateway") and not feature_ok(MENU, "theme"):
        locked.append("theme")
    else:
        out["themes"] = themes
    if locked:
        out["locked"] = locked
    return _admin_json(out)


@bp.route("/admin/api/flow/theme", methods=["GET"])
def api_theme():
    """[theme] 테마별 수급 합계 목록, 또는 theme=<이름> 이면 그 테마 종목 표."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    if not d["themes"]:
        return _admin_json({"ok": True, "empty": True, "need": ["stock_theme_map"], "msg": "테마 자료가 아직 없어요. 🏷 네이버테마 메뉴에서 [테마 가져오기]를 누르거나, 📦 데이터 가져오기 메뉴에서 ‘종목-테마 연결(stock_theme_map)’ 표를 가져오면 보여요."})
    per = _arg("period", ("5", "20"), "20")
    side = _arg("side", ("buy", "sell"), "buy")
    fresh_rows = {r["ticker"]: r for r in d["rows"] if not r["stale"]}
    name = (request.args.get("theme") or "").strip()
    if name:
        if name not in d["themes"]:
            return _admin_json({"error": "없는 테마예요."}, 404)
        mem = sorted((fresh_rows[t] for t in d["themes"][name] if t in fresh_rows), key=lambda r: (-r["c" + per], r["ticker"]))[:60]
        items = [_item(r) for r in mem]
        out = {"ok": True, "theme": name, "period": per, "items": items, "total": len(d["themes"][name]), "has_price": d["has_price"], "base_date": d["meta"]["base_date"]}
        if _sig_locked():
            out["items"] = [_strip_sig(x) for x in items]
            out["locked"] = ["sig"]
        return _admin_json(out)
    mn, top = _iarg("min", 1, 20, 3), _iarg("top", 1, 40, 30)
    lst = []
    for nm, ts in d["themes"].items():
        mem = [fresh_rows[t] for t in ts if t in fresh_rows]
        if len(mem) < mn:
            continue
        f, i = sum(r["f" + per] for r in mem), sum(r["i" + per] for r in mem)
        c = f + i
        if (side == "buy" and c <= 0) or (side == "sell" and c >= 0):
            continue
        lst.append({"theme": nm, "n": len(mem), "total": len(ts), "f": f, "i": i, "c": c, "dual": sum(1 for r in mem if "dual" in r["sg"]),
                    "pos": sum(1 for r in mem if r["c" + per] > 0)})
    lst.sort(key=lambda x: (-x["c"] if side == "buy" else x["c"], x["theme"]))
    out = {"ok": True, "items": lst[:top], "matched": len(lst), "period": per, "side": side, "base_date": d["meta"]["base_date"]}
    if _sig_locked():
        for x in out["items"]:
            x.pop("dual", None)
        out["locked"] = ["sig"]
    return _admin_json(out)


# ══════════════════════════════════════════════════════════════
# AI 프롬프트(수동 AI 도우미용 — 서버가 AI를 부르지 않는다)
# ══════════════════════════════════════════════════════════════
FLOW_DEFAULT = """아래는 한국 주식시장에서 최근 기관·외국인 투자자의 {side_lbl} 규모가 큰 종목의 수급 데이터입니다.
(기준일 {base_date} · 순위 기준: {rank_lbl} · 금액은 원을 억/만 단위로 줄인 값이고, 1일·5일·20일은 최근 N거래일 합계입니다.)

[수급 데이터]
{data_rows}

다음 형식으로 한국어로 설명해 주세요. 주식 초보도 이해하도록 쉬운 말로 쓰고, [수급 데이터]에 없는 숫자나 사실은 지어내지 마세요.
특정 종목의 매수·매도를 권하거나 목표가를 제시하지 말고, 관찰 중심("~로 보입니다")으로 쓰세요.

## 🔍 수급 특징이 두드러진 종목
외국인·기관의 {side_lbl}이 눈에 띄는 종목 3~5개를 골라 정리합니다.

### 1. 종목명 (종목코드)
- **수급 포인트**: 1일·5일·20일 흐름과 외국인/기관 구분
- **함께 볼 점**: 수급만으로는 알 수 없는 한계와 같이 확인하면 좋은 자료(공시·실적·주가 위치 등)

(이하 같은 형식)

## 📊 전체 수급 흐름 요약
한두 문장

## ⚠ 유의사항
이 해설은 공개된 수급 자료를 정리한 참고용이며 투자 권유가 아니라는 점, 수급은 과거 단기 동향으로 미래 수익을 보장하지 않고 투자 판단과 책임은 이용자 본인에게 있다는 점을 한두 줄로 적습니다.
"""


def _amt(v):
    v = int(v or 0)
    if v == 0:
        return "0"
    s, a = ("+" if v > 0 else "-"), abs(v)
    if a >= 1e12:
        return f"{s}{a / 1e12:.2f}조"
    if a >= 1e10:
        return f"{s}{round(a / 1e8):,}억"
    if a >= 1e8:
        return f"{s}{a / 1e8:.1f}억"
    if a >= 1e4:
        return f"{s}{round(a / 1e4):,}만"
    return f"{s}1만 미만"


@bp.route("/admin/api/flow/prompt", methods=["GET"])
def api_prompt():
    """[ai] 상위 20종목을 한 줄씩 직렬화해 프롬프트를 만든다."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    inv, per, side, market, pool, fresh = _rank_args()
    hit, uni = _ranked(d, inv, per, side, market, pool, True)
    if not hit:
        return _admin_json({"error": "조건에 맞는 종목이 없어서 프롬프트를 만들 수 없어요."}, 400)
    lines = []
    for r in hit[:20]:
        seg = [f"[{r['name']}({r['ticker']}){r['market']}]"]
        for p in ("1", "5", "20"):
            seg.append(f"외국인{p}일:{_amt(r['f' + p])}")
            seg.append(f"기관{p}일:{_amt(r['i' + p])}")
            seg.append(f"합산{p}일:{_amt(r['c' + p])}")
        lines.append(" | ".join(seg))
    side_lbl = "순매수" if side == "buy" else "순매도"
    rank_lbl = f"{INV_LBL[inv]} {PER_LBL[per]} {side_lbl} 상위" + ("" if market == "all" else f" · {market}")
    body = prompt_get("flow_ai") or FLOW_DEFAULT
    for k, v in (("{data_rows}", "\n".join(lines)), ("{side_lbl}", side_lbl), ("{base_date}", d["meta"]["base_date"] or "알 수 없음"), ("{rank_lbl}", rank_lbl)):
        body = body.replace(k, v)
    return _admin_json({"ok": True, "prompt": body, "n": len(lines), "label": rank_lbl})


# ══════════════════════════════════════════════════════════════
# 블로그 글(관리자 전용 — 어떤 기능에도 등록하지 않음). 서버는 HTML 만 만들고 글은 올리지 않아요.
# ══════════════════════════════════════════════════════════════
BLOG_SECS = ("stats", "rank", "signal", "ai")
_TITLE_BLOCK = re.compile(r"^[ \t]*\[블로그\s*제목\s*후보[^\]]*\][ \t]*\n(?:[ \t]*(?:[-•*·]|\d+[.)])[ \t]*.+\n?)*", re.M)


def _split_ai(text):
    text = str(text or "").replace("\r", "")
    return _TITLE_BLOCK.sub("", text).strip(), B.extract_titles(text)


def _bf(b, name, allowed, default):
    v = str(b.get(name) or "").strip()
    return v if v in allowed else default


def _ftd(txt, w, align="right", color="#111827", bold=False):
    return ('<td width="%d%%" align="%s" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:12.5px;%scolor:%s;white-space:nowrap;">%s</td>'
            % (w, align, "font-weight:800;" if bold else "", color, txt))


def _rank_tbl(title, color, items, keys):
    """items: 행 목록, keys: [(머리글, 값을 꺼내는 함수)] — 첫 열은 종목(링크), 마지막 열은 등락률."""
    E = B.E
    head = ('<th width="8%" style="padding:7px 2px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;">#</th>'
            '<th width="34%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;text-align:left;">종목</th>')
    wv = int(46 / max(1, len(keys)))
    head += "".join('<th width="%d%%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">%s</th>' % (wv, E(k[0])) for k in keys)
    head += '<th width="%d%%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">등락</th>' % (100 - 42 - wv * len(keys))
    trs = ""
    for n, r in enumerate(items, 1):
        pct = r.get("pct")
        trs += ('<tr><td width="8%%" align="center" style="padding:6px 2px;border-bottom:1px solid #eef2f7;font-size:12px;color:#64748b;">%d</td>'
                '<td width="34%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;color:#111827;">%s</td>' % (n, B.nlink(r["ticker"], E(r["name"])))
                + "".join(_ftd(E(_amt(f(r))), wv, "right", B.updown(f(r)), True) for _, f in keys)
                + _ftd(("%+.2f%%" % pct) if pct is not None else "-", 100 - 42 - wv * len(keys), "right", B.updown(pct or 0)) + "</tr>")
    return (B.side_title(title, color) + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '"><tr>' + head + "</tr>" + trs + "</table>")


def _flow_blog_build(d, ai_text, inc, title):
    E = B.E
    today = _now_kst().strftime("%Y-%m-%d")
    base = d["meta"].get("base_date") or today
    fresh = [r for r in d["rows"] if not r["stale"]]
    ai_body, titles = _split_ai(ai_text) if (ai_text or "").strip() else ("", [])
    cnt = Counter()
    for r in fresh:
        for k in ("dual", "turn", "bsell", "surge"):
            if k in r["sg"]:
                cnt[k] += 1
    f_buy = sorted((r for r in fresh if r["f5"] > 0), key=lambda r: -r["f5"])[:8]
    i_buy = sorted((r for r in fresh if r["i5"] > 0), key=lambda r: -r["i5"])[:8]
    c_sell = sorted((r for r in fresh if r["c5"] < 0), key=lambda r: r["c5"])[:8]
    c_buy = sorted((r for r in fresh if r["c5"] > 0), key=lambda r: -r["c5"])[:8]
    dual = sorted((r for r in fresh if "dual" in r["sg"]), key=lambda r: -r["c20"])[:8]
    bsell = sorted((r for r in fresh if "bsell" in r["sg"]), key=lambda r: r["c20"])[:8]
    lead = ("%s 외국인·기관 동반 순매수 1위 %s" % (base, c_buy[0]["name"])) if c_buy else base
    auto_title = "💧 %s 수급 | 외국인·기관 순매수 상위·쌍끌이 종목" % base
    title = title or (titles[0] if titles else auto_title)
    names = []
    for lst in (c_buy, f_buy, i_buy, dual):
        for r in lst[:3]:
            if r["name"] not in names:
                names.append(r["name"])
    tags, tag_html = B.hashtags(names[:10], today, extra=["수급분석", "외국인순매수", "기관순매수", "쌍끌이", "수급전환", "투자자별매매동향"])
    h = [B.seo_box(auto_title, "%s 기준 외국인·기관 순매수 상위 종목과 쌍끌이·수급전환 신호를 정리했어요. 매수 추천이 아닌 참고 정보예요." % base,
                   ["수급분석", "외국인 순매수", "기관 순매수", "쌍끌이", "수급전환", "투자자별 매매동향"]),
         B.head_box("★ SUPPLY & DEMAND · %s" % base, '외국인·기관 <span style="color:%s;">수급</span> 한눈에' % B.GOLD, "최근 5일·20일 순매수 상위 · 기준일 %s · 대상 %d종목" % (E(base), len(fresh)))]
    if inc.get("stats"):
        def tile(label, val, color):
            return ('<td width="25%%" align="center" style="padding:11px 4px;background-color:#f8faff;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;margin-bottom:3px;">%s</div>'
                    '<div style="font-size:17px;font-weight:900;color:%s;">%s</div></td>' % (label, color, val))
        cells = (tile("쌍끌이", "%d종목" % cnt["dual"], "#dc2626") + tile("수급전환", "%d종목" % cnt["turn"], "#d97706")
                 + tile("동반매도", "%d종목" % cnt["bsell"], "#2563eb") + tile("수급 급증", "%d종목" % cnt["surge"], "#7c3aed"))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;margin:14px 0 4px;' + B.FONT + '"><tr>' + cells + "</tr></table>")
        h.append('<p style="font-size:11.5px;color:#9ca3af;margin:4px 0 10px;">쌍끌이=외국인·기관 20일 동반 순매수 · 수급전환=최근 5일 순매수로 돌아섬 · 동반매도=20일 동반 순매도</p>')
    if inc.get("rank"):
        K5 = [("외국인5일", lambda r: r["f5"]), ("기관5일", lambda r: r["i5"])]
        if c_buy:
            h.append(_rank_tbl("&#127942; 외국인+기관 합산 순매수 상위 (5일)", "#c62828", c_buy, [("합산5일", lambda r: r["c5"])] + K5[:1]))
        if f_buy:
            h.append(_rank_tbl("&#127758; 외국인 순매수 상위 (5일)", "#1e40af", f_buy, [("외국인5일", lambda r: r["f5"]), ("20일", lambda r: r["f20"])]))
        if i_buy:
            h.append(_rank_tbl("&#127970; 기관 순매수 상위 (5일)", "#0f766e", i_buy, [("기관5일", lambda r: r["i5"]), ("20일", lambda r: r["i20"])]))
        if c_sell:
            h.append(_rank_tbl("&#128201; 외국인+기관 합산 순매도 상위 (5일)", "#1565c0", c_sell, [("합산5일", lambda r: r["c5"]), ("외국인", lambda r: r["f5"])]))
        h.append('<p style="font-size:11.5px;color:#9ca3af;margin:6px 0 0;">금액은 &lsquo;순매수 수량×종가&rsquo; 추정치이고, 오른쪽은 당일 등락률이에요.</p>')
    if inc.get("signal"):
        if dual:
            h.append(_rank_tbl("&#129309; 쌍끌이 종목 (외국인·기관 20일 동반 순매수)", "#dc2626", dual, [("합산20일", lambda r: r["c20"]), ("외국인20일", lambda r: r["f20"])]))
        if bsell:
            h.append(_rank_tbl("&#9888;&#65039; 동반매도 종목 (외국인·기관 20일 동반 순매도)", "#2563eb", bsell, [("합산20일", lambda r: r["c20"]), ("외국인20일", lambda r: r["f20"])]))
    if inc.get("ai") and ai_body:
        pairs = [(r["name"], r["ticker"]) for lst in (c_buy, f_buy, i_buy, dual, bsell, c_sell) for r in lst]
        h.append(B.side_title("&#129302; AI 수급 해설", "#0d1b3e"))
        h.append(B.link_names(B.ai_to_html(ai_body), pairs))
    h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border:2px solid #d97706;border-collapse:collapse;margin:14px 0 4px;' + B.FONT + '"><tr><td bgcolor="#fffbeb" style="background-color:#fffbeb;padding:12px 16px;">'
             '<div style="font-size:13px;font-weight:900;color:#92400e;">&#9888;&#65039; 수급은 결과일 뿐 방향을 보장하지 않아요</div><div style="font-size:12.5px;color:#92400e;line-height:1.85;margin-top:4px;">'
             '외국인·기관이 많이 샀다고 오른다는 뜻도, 많이 팔았다고 내린다는 뜻도 아닙니다. 며칠의 수급은 금방 바뀔 수 있고, 종목별 수급은 추정치라 실제와 차이가 있을 수 있어요.</div></td></tr></table>')
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/flow/blog", methods=["POST"])
def api_blog():
    """관리자 전용 — 수급 순위·신호와 AI 해설로 블로그용 HTML 글을 만든다(서버가 글을 올리지는 않아요)."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _admin_json({"error": "수급 자료가 없어요. 먼저 [📦 수급 자료 가져오기]를 실행하세요."}, 404)
    b = _json_body() or {}
    inc = b.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k in BLOG_SECS} if isinstance(inc, dict) else {k: True for k in BLOG_SECS}
    out = _flow_blog_build(d, str(b.get("ai") or "")[:20000], inc, str(b.get("title") or "").strip()[:150])
    base = d["meta"].get("base_date") or _now_kst().strftime("%Y-%m-%d")
    pseudo = "D" + re.sub(r"\D", "", base)[2:8]
    logs, warn = B.dup_info(pseudo, "flow")
    out.update({"ticker": pseudo, "name": "수급분석 " + base, "dups": logs, "dup_warn": warn})
    return _admin_json(out)


# ══════════════════════════════════════════════════════════════
# 관리자 전용(어떤 기능에도 등록하지 않음 → 회원 화면에서는 404)
# ══════════════════════════════════════════════════════════════
def _diag(d):
    rows = d["rows"]
    dist = Counter((r["base"] or ("(없음·수집일 " + (r["eff"] or "?") + ")")) for r in rows)
    return {"ok": True, "tables": d["tables"], "meta": d["meta"], "has_price": d["has_price"], "has_theme": d["has_theme"], "themes": len(d["themes"]),
            "missing": d["missing"], "dist": dist.most_common(8), "no_base": sum(1 for r in rows if not r["base"]),
            "no_market": sum(1 for r in rows if not r["market"]), "cache_age": int(time.time() - _CACHE["at"]) if _CACHE["d"] is not None else None}


@bp.route("/admin/api/flow/diag", methods=["GET"])
def api_diag():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_diag(_load()))


@bp.route("/admin/api/flow/reload", methods=["POST"])
def api_reload():
    """읽어 둔 표를 비우고 다시 읽는다(데이터를 새로 가져온 직후 바로 보고 싶을 때)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _load(force=True)
    _alog("flow_reload", f"rows={len(d['rows'])}")
    return _admin_json(_diag(d))


# ══════════════════════════════════════════════════════════════
# 화면(관리자 탭 = 이용자 /m/flow 와 같은 JS)
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var FL={sec:'rank',sum:null,
 rk:{inv:'comb',period:'5',side:'buy',market:'all',top:'20',pool:'all',fresh:'1',data:null,open:{},seq:0},
 sg:{kind:'dual',market:'all',top:'30',fresh:'1',data:null,seq:0},
 st:{tk:'',data:null,seq:0,q:''},
 th:{period:'20',side:'buy',min:'3',name:'',list:null,mem:null,seq:0},
 ai:{inv:'comb',period:'5',side:'buy',market:'all',text:''},
 tbl:null,css:false,tmr:null,flag:{img:false,blog:false,posted:false},imgPanel:null,blogPanel:null};
var FL_KIND=[['dual','쌍끌이','외국인과 기관이 최근 20거래일 동안 함께 순매수한 종목'],
 ['warn','쌍끌이⚠','쌍끌이 중인데 오늘 외국인·기관이 함께 크게 순매도해(20일 합의 30% 초과) 흐름 변화를 살펴볼 종목'],
 ['turn','수급전환','외국인 또는 기관이 20일로는 순매도·중립이었는데 최근 5일은 순매수로 돌아선 종목'],
 ['bsell','동반매도','외국인과 기관이 20일 동안 함께 순매도한 종목'],
 ['persist','지속 순매수','1일·5일·20일 모두 순매수인 종목(외국인 또는 기관) — 웹에서 더한 보조 지표'],
 ['surge','수급 급증','오늘 합산(외국인+기관) 순매수가 20일 일평균의 3배 이상인 종목 — 웹에서 더한 보조 지표']];
var FL_SECS=[['rank','📊 순위','rank'],['sig','🧭 신호 종목','sig'],['stock','🔎 종목별','stock'],['theme','🏷 테마별','theme'],['ai','🤖 AI 해설','ai'],['img','🖼 이미지','exp'],['blog','📝 블로그 쓰기','exp'],['guide','📘 읽는 법','guide']];
var FL_CSS='.flHd{padding:14px 16px}.flHd h2{margin:0 0 4px;font-size:18px}.flSt{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0}'+
'.flCh{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;background:#f1f5f9;color:#334155;border:1px solid #e2e8f0;white-space:nowrap}'+
'.flCh.a{background:#ecfdf5;color:#047857;border-color:#a7f3d0}.flCh.w{background:#fffbeb;color:#b45309;border-color:#fcd34d}.flCh.s{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe}.flCh.g{background:#f8fafc;color:#64748b}'+
'.flTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:8px;margin:10px 0}.flTile{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;text-align:left;cursor:pointer;font:inherit;color:inherit}'+
'.flTile:hover{border-color:#5eead4}.flTile .l{font-size:12px;color:#64748b;font-weight:700}.flTile .v{font-size:22px;font-weight:900;color:#0f172a;margin-top:2px}.flTile .s{font-size:11px;color:#94a3b8;margin-top:1px}'+
'.flNav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 8px}.flNav button{border:1.5px solid #cbd5e1;background:#fff;color:#334155;border-radius:999px;padding:7px 13px;font:inherit;font-size:13px;font-weight:700;cursor:pointer}'+
'.flNav button.flOn{background:#0f766e;border-color:#0f766e;color:#fff}'+
'.flW{overflow-x:auto;-webkit-overflow-scrolling:touch}.flT{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}.flT th{background:#f1f5f9;white-space:nowrap}.flT td{word-break:keep-all;vertical-align:middle}'+
'.flT td.r,.flT th.r{text-align:right;white-space:nowrap}.flT tr.flDt td{background:#f8fafc}.flT .nm{font-weight:800;color:#0f172a}.flT .tkl{color:#2563eb}.flT .sb{font-size:11px;color:#94a3b8;margin-top:1px}'+
'.flT tr.flOld td{color:#94a3b8}.flT tr.flOld .nm{color:#94a3b8}'+
'.flUp{color:#dc2626;font-weight:700}.flDn{color:#2563eb;font-weight:700}.flZ{color:#94a3b8}'+
'.flBw{height:5px;background:#eef2f7;border-radius:3px;margin-top:3px;min-width:56px;overflow:hidden}.flBw i{display:block;height:100%;border-radius:3px}'+
'.flL{display:inline-flex;flex-direction:column;gap:2px;font-size:11.5px;color:#64748b}.flL select{min-width:92px}'+
'.flSug{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.flKv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}'+
'.flKv div{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px;font-size:12.5px}.flKv b{display:block;font-size:11.5px;color:#64748b;margin-bottom:2px}'+
'.flAiOut{white-space:pre-wrap;word-break:break-word;font-size:13.5px;line-height:1.65;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin-top:8px}'+
'.flAiOut .h2{display:block;font-weight:900;color:#fff;background:#0f766e;border-radius:8px;padding:5px 10px;margin:10px 0 4px}.flAiOut .h3{display:block;font-weight:800;border-left:5px solid #0f766e;padding-left:8px;margin:8px 0 2px}'+
'.flGd h4{margin:12px 0 4px;font-size:14px}.flGd p,.flGd li{font-size:13px;line-height:1.65;color:#334155;margin:3px 0}.flGd ul{margin:4px 0 4px 18px;padding:0}'+
'.flCard{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:8px 0}.flCard h3{margin:0 0 4px;font-size:16px}'+
'@media(max-width:520px){.flT{font-size:12px}.flT td,.flT th{padding:6px 6px}.flTile .v{font-size:19px}.flHd{padding:12px}.flL select{min-width:84px}}';
function flCss(){if(FL.css)return;FL.css=true;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';
 var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=FL_CSS;document.head.appendChild(s)}
function flFv(v){v=Number(v)||0;if(v===0)return '0';var s=v>0?'+':'-',a=Math.abs(v);
 if(a>=1e12)return s+(a/1e12).toFixed(2)+'조';if(a>=1e10)return s+Math.round(a/1e8).toLocaleString('ko-KR')+'억';if(a>=1e8)return s+(a/1e8).toFixed(1)+'억';
 if(a>=1e4)return s+Math.round(a/1e4).toLocaleString('ko-KR')+'만';return s+'<1만'}
function flAbs(v){var s=flFv(Math.abs(v));return s.charAt(0)==='+'?s.slice(1):s}
function flCls(v){return v>0?'flUp':(v<0?'flDn':'flZ')}
function flN(v,d){if(v==null||isNaN(v))return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d,minimumFractionDigits:d==null?0:d})}
function flCap(v){v=Number(v)||0;if(!v)return '-';return v>=10000?(v/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조':v.toLocaleString('ko-KR')+'억'}
function flTk(node,t){if(typeof window.GoStock==='function'||typeof window.__openTicker==='function'){node.className=(node.className?node.className+' ':'')+'tkl';node.setAttribute('data-tk',t);node.title='눌러서 종목분석·심층분석 열기'}return node}
function flQ(o){var a=[];Object.keys(o).forEach(function(k){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]))});return a.join('&')}
function flSel(bar,lbl,obj,key,opts,fn){var l=el('label','flL');l.appendChild(el('span',null,lbl));var s=el('select');opts.forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];s.appendChild(op)});s.value=obj[key];s.onchange=function(){obj[key]=s.value;fn()};l.appendChild(s);bar.appendChild(l);return s}
function flChips(it,onlyFirst){var w=document.createDocumentFragment(),sg=it.sg||[],n=0;if(it.sg===undefined){var lk=el('span','flZ','🔒');lk.title='신호는 수급 신호 기능이 열린 등급부터 보여요';w.appendChild(lk);return w}
 function add(t,c,tip){var x=el('span','flCh '+c,t);if(tip)x.title=tip;w.appendChild(x);w.appendChild(document.createTextNode(' '));n++}
 if(sg.indexOf('warn')>=0)add('쌍끌이⚠','w','쌍끌이 중이지만 오늘 동반 순매도가 커요');else if(sg.indexOf('dual')>=0)add('쌍끌이','a','20일 외국인·기관 동시 순매수');
 if(sg.indexOf('turn')>=0)add('수급전환','a','20일은 매도·중립 → 5일은 순매수');
 if(sg.indexOf('bsell')>=0)add('동반매도','s','20일 외국인·기관 동시 순매도');
 if(sg.indexOf('pf')>=0||sg.indexOf('pi')>=0)add('지속','g','1·5·20일 모두 순매수');
 if(sg.indexOf('surge')>=0)add('급증','g','오늘 합산이 20일 일평균의 3배 이상');
 if(!n)w.appendChild(el('span','flZ','-'));return w}
function flEmpty(box,j){var c=el('div','flCard');c.appendChild(el('b',null,'📦 아직 보여 줄 수급 자료가 없어요'));
 if(MEMBER_MODE){c.appendChild(el('p','note','아직 준비 중인 자료예요. 자료가 채워지면 여기에 보여요.'))}
 else{var th=(j.need||[]).indexOf('stock_theme_map')>=0;c.appendChild(el('p','note',th?'[🏷 네이버테마] 메뉴에서 [테마 가져오기]를 누르면 1~2분 안에 채워져요.':'[📊 시장수급] 메뉴에서 [종목 수급 가져오기]를 누르면 몇 분 안에 채워져요.'));
  var g=bt('📊 시장수급 메뉴로 이동','bt',function(){flGoTab('mk')});c.appendChild(g);c.appendChild(bt('🏷 네이버테마 메뉴로 이동','bt2',function(){flGoTab('th')}));NeedNote(c,'또는 PC 프로그램에서 만든 표를 📦 데이터 가져오기 메뉴로 올려도 돼요.')}
 box.appendChild(c)}
function flPlace(box,fid,txt){var c=el('div','flCard');c.appendChild(el('b',null,txt||'이 기능은 잠겨 있어요'));c.appendChild(el('p','note','등급이 열리면 이 자리에 내용이 나타나요. 위 안내를 눌러 자세히 확인해 보세요.'));
 var sk=el('div');sk.style.cssText='height:90px;background:repeating-linear-gradient(90deg,#f1f5f9 0 40px,#e2e8f0 40px 42px);border-radius:10px';c.appendChild(sk);box.appendChild(c);ftSec(box,fid)}
function flTblBuild(heads,aligns){var w=el('div','flW'),t=el('table','flT'),h=el('tr');heads.forEach(function(x,i){h.appendChild(el('th',aligns&&aligns[i]==='r'?'r':'',x))});t.appendChild(h);w.appendChild(t);return {wrap:w,t:t}}
function flStockBtn(tk,txt){var b=bt(txt||'📈 종목별 추이','bt3',function(){flStockOpen(tk)});return ft(b,'stock')}

/* ── 표 내보내기·이미지(기능 'exp'): 지금 화면의 표를 CSV 파일 / PNG 그림으로 내려받는다 ── */
function flSetTbl(title,cols,items,asof){FL.tbl={title:title,asof:asof||'',head:cols.map(function(c){return c.h}),num:cols.map(function(c){return !!c.num}),
 raw:items.map(function(it){return cols.map(function(c){return c.raw(it)})}),disp:items.map(function(it){return cols.map(function(c){var r=c.raw(it);return c.disp?c.disp(it,r):String(r==null?'':r)})})}}
function flDl(blob,name){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href)},4000)}
function flStamp(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())}
function flCsv(){var T=FL.tbl;if(!T||!T.raw.length){toast('내려받을 표가 아직 없어요. 먼저 조회해 주세요.');return}
 function q(x,num){if(x==null)return '';var s=String(x);if(!num&&/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'}
 var L=[T.head.map(function(h){return q(h)}).join(',')];T.raw.forEach(function(r){L.push(r.map(function(x,i){return q(x,T.num[i])}).join(','))});
 L.push('');L.push(q('금액 단위: 원 · 기준일 '+(T.asof||'-')+' · 정보 제공용이며 투자 권유가 아닙니다'));
 flDl(new Blob(['﻿'+L.join('\r\n')],{type:'text/csv;charset=utf-8'}),'수급분석_'+flStamp()+'.csv');toast('CSV 파일을 내려받았어요')}
function flPng(){var T=FL.tbl;if(!T||!T.disp.length){toast('내려받을 표가 아직 없어요. 먼저 조회해 주세요.');return}
 var rows=T.disp.slice(0,30),cw=T.head.map(function(h,i){return i===0?(T.head[0]==='#'?44:200):(T.num[i]?110:150)}),W=cw.reduce(function(a,b){return a+b},0)+40;W=Math.max(W,640);var rh=34,H=130+rows.length*rh+70,S=2;
 var cv=document.createElement('canvas');cv.width=W*S;cv.height=H*S;var c=cv.getContext('2d');c.scale(S,S);var F="'Malgun Gothic','Apple SD Gothic Neo',sans-serif";
 c.fillStyle='#f8fafc';c.fillRect(0,0,W,H);c.fillStyle='#0f766e';c.fillRect(0,0,W,70);c.fillStyle='#fff';c.font='800 22px '+F;c.fillText('💧 '+T.title,20,32);c.font='600 13px '+F;c.fillText('수급 기준일 '+(T.asof||'-')+' · 금액은 원 단위를 억·만으로 줄여 표시',20,56);
 var y=96;c.fillStyle='#e2e8f0';c.fillRect(20,y-22,W-40,30);c.fillStyle='#334155';c.font='800 13px '+F;var x=20;T.head.forEach(function(h,i){c.textAlign=T.num[i]?'right':'left';c.fillText(h,T.num[i]?x+cw[i]-8:x+8,y);x+=cw[i]});
 rows.forEach(function(r,ri){y+=rh;if(ri%2===1){c.fillStyle='#f1f5f9';c.fillRect(20,y-22,W-40,rh)}x=20;r.forEach(function(v,i){var raw=T.raw[ri][i];c.fillStyle=T.num[i]&&typeof raw==='number'?(raw>0?'#dc2626':(raw<0?'#2563eb':'#94a3b8')):'#0f172a';c.font=(i===1||T.head[i]==='종목'||T.head[i]==='테마'?'800 ':'600 ')+'13px '+F;c.textAlign=T.num[i]?'right':'left';
  var s=String(v);var mx=cw[i]-14;while(s.length>1&&c.measureText(s).width>mx)s=s.slice(0,-2)+'…';c.fillText(s,T.num[i]?x+cw[i]-8:x+8,y);x+=cw[i]})});
 c.textAlign='left';c.fillStyle='#64748b';c.font='600 12px '+F;c.fillText('공개된 수급 자료를 정리한 정보 제공용이며 특정 종목의 매수·매도 권유가 아닙니다. 수급은 과거 단기 동향이고 미래 수익을 보장하지 않습니다.',20,H-30);
 c.fillText('투자 판단과 책임은 이용자 본인에게 있습니다.',20,H-12);
 try{cv.toBlob(function(b){if(!b){toast('이미지를 만들지 못했어요');return}flDl(b,'수급분석_'+flStamp()+'.png');toast('이미지를 내려받았어요')},'image/png')}catch(e){toast('이미지를 만들지 못했어요')}}
function flExpBar(parent){var r=el('div','bar');r.appendChild(ft(bt('📄 표 내려받기(CSV)','bt3',flCsv),'exp'));r.appendChild(ft(bt('🖼 이미지 내려받기','bt3',flPng),'exp'));
 r.appendChild(el('span','m','지금 보이는 표를 파일로 가져가요'));parent.appendChild(r)}

/* ── 위쪽: 상태 + 요약(기능 'sum') ── */
function flLoad(p){flCss();p.innerHTML='';
 var hd=el('div','c flHd');hd.appendChild(el('h2',null,'💧 수급분석'));hd.appendChild(el('div','m','외국인·기관이 최근 며칠 동안 어떤 종목을 순매수(산 금액이 판 금액보다 많음)·순매도했는지 정리해 보여 줘요. 정보 제공용이며 투자 권유가 아닙니다.'));
 var sb=el('div');sb.id='flSum';hd.appendChild(sb);p.appendChild(hd);
 if(!MEMBER_MODE){var cp=el('div','c');cp.id='flCol';p.appendChild(cp);flColInit()}
 if(!MEMBER_MODE){var sp=el('div');sp.id='flSteps';p.appendChild(sp)}
 var nv=el('div','flNav');nv.id='flNav';p.appendChild(nv);var bd=el('div');bd.id='flBody';p.appendChild(bd);
 var ft2=el('p','note','※ 수급 자료는 가져온 캐시(1일·5일·20일 합계)이고 시가총액 상위 종목 위주예요. 일부 종목은 20일 값이 더 짧은 기간일 수 있어요. 본 화면은 공개된 자료를 정리한 정보 제공용이며 특정 종목의 매수·매도 권유가 아닙니다. 수급은 과거 단기 동향으로 미래 수익을 보장하지 않으며 투자 판단과 책임은 이용자 본인에게 있습니다.');p.appendChild(ft2);
 var ad=el('div','c');ad.id='flAdm';p.appendChild(adm(ad));
 flSumLoad();flNavDraw();flShow();flSteps();if(!MEMBER_MODE)flDiagLoad()}
function flSumLoad(){var b=$('flSum');if(!b)return;b.innerHTML='';
 if(!ftOk('sum')){b.appendChild(el('p','note','🔒 수급 요약은 지금 등급에서 볼 수 없어요.'));ftSec(b,'sum');return}
 b.appendChild(el('div','m','불러오는 중…'));
 api('/admin/api/flow/summary').then(function(j){var b2=$('flSum');if(!b2)return;b2.innerHTML='';if(j.error)return;FL.sum=j;flSteps();if(j.empty){flEmpty(b2,j);return}
  var s=j.status,st=el('div','flSt');st.appendChild(el('span','flCh a','📅 수급 기준일 '+(s.base_date||'알 수 없음')));if(s.last_scan)st.appendChild(el('span','flCh','마지막 갱신 '+s.last_scan));
  st.appendChild(el('span','flCh','종목 '+s.count.toLocaleString('ko-KR')+'개'));
  if(s.stale>0)st.appendChild(el('span','flCh w','오래된 자료 '+s.stale+'개는 신호에서 제외'));
  if(s.base_date&&s.base_date<s.today)st.appendChild(el('span','flCh w','⚠ 기준일이 오늘보다 앞서요(휴장이거나 자료 갱신 전)'));
  if(!s.has_price)st.appendChild(el('span','flCh w','시세 표가 없어 현재가·시장 구분은 빠져요'));b2.appendChild(st);
  var g=el('div','flTiles');FL_KIND.forEach(function(k){var t=el('button','flTile');t.type='button';t.appendChild(el('div','l',k[1]));t.appendChild(el('div','v',String(j.counts[k[0]]||0)));t.appendChild(el('div','s','종목'));t.title=k[2];
   t.onclick=function(){if(!ftOk('sig')){lockDlg('sig');return}FL.sg.kind=k[0];FL.sg.data=null;flGo('sig')};g.appendChild(t)});b2.appendChild(g);
  var tb=flTblBuild(['시장 · 구분','1일','5일','20일'],['','r','r','r']);var any=false;
  ['KOSPI','KOSDAQ'].forEach(function(m){var x=j.market[m];if(!x||!x.n)return;any=true;[['외국인','f'],['기관','i'],['합산','c']].forEach(function(z){var tr=el('tr');tr.appendChild(el('td',null,m+' ('+x.n+'종목) · '+z[0]));
   ['1','5','20'].forEach(function(p){var v=z[1]==='c'?x['f'+p]+x['i'+p]:x[z[1]+p];tr.appendChild(el('td','r '+flCls(v),flFv(v)))});tb.t.appendChild(tr)})});
  if(any){b2.appendChild(el('div','m','시장 전체 합계(수급 자료에 담긴 종목 합) — 숫자가 +면 순매수, −면 순매도'));b2.appendChild(tb.wrap)}})}
function flNavDraw(){var n=$('flNav');if(!n)return;n.innerHTML='';FL_SECS.forEach(function(s){if(MEMBER_MODE&&(s[0]==='img'||s[0]==='blog'))return;var b=el('button',FL.sec===s[0]?'flOn':'',(ftOk(s[2])?'':'🔒 ')+s[1]);b.type='button';b.onclick=function(){flGo(s[0])};n.appendChild(b)})}
function flGo(sec){FL.sec=sec;flNavDraw();flShow()}
function flShow(){var b=$('flBody');if(!b)return;b.innerHTML='';var box=el('div');b.appendChild(box);
 var m={rank:flSecRank,sig:flSecSig,stock:flSecStock,theme:flSecTheme,ai:flSecAi,img:flSecImg,blog:flSecBlog,guide:flSecGuide}[FL.sec],fid=FL_SECS.filter(function(s){return s[0]===FL.sec})[0][2];
 if(!ftOk(fid)){var f=FEATS&&FEATS[fid];flPlace(box,fid,'🔒 '+(f?f.label:'잠긴 기능'));return}m(box)}

/* ── 순위(기능 'rank') ── */
function flSecRank(box){var S=FL.rk;box.appendChild(el('p','note','투자자별·기간별로 순매수(또는 순매도) 금액이 큰 종목을 순서대로 보여 줘요. 숫자가 빨강(+)이면 순매수, 파랑(−)이면 순매도예요. 기간은 최근 N거래일 합계예요.'));
 var bar=el('div','bar');var go=function(){flRankGo()};
 flSel(bar,'투자자',S,'inv',[['comb','외국인+기관 합산'],['foreign','외국인'],['inst','기관']],go);flSel(bar,'기간',S,'period',[['1','1일(오늘)'],['5','5일'],['20','20일']],go);
 flSel(bar,'방향',S,'side',[['buy','순매수 많은 순'],['sell','순매도 많은 순']],go);flSel(bar,'시장',S,'market',[['all','전체'],['KOSPI','코스피'],['KOSDAQ','코스닥']],go);
 flSel(bar,'종목 범위',S,'pool',[['all','전체'],['cap100','시총 상위 100'],['cap300','시총 상위 300'],['score60','종합점수 60↑']],go);flSel(bar,'개수',S,'top',[['10','10개'],['20','20개'],['30','30개'],['40','40개']],go);
 var lb=el('label');lb.style.fontSize='12.5px';var ck=el('input');ck.type='checkbox';ck.checked=S.fresh==='0';ck.onchange=function(){S.fresh=ck.checked?'0':'1';go()};lb.appendChild(ck);lb.appendChild(document.createTextNode(' 오래된 자료도 보기'));bar.appendChild(lb);
 bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);var out=el('div');out.id='flRkOut';box.appendChild(out);if(S.data)flRankDraw(out);else flRankGo()}
function flRankGo(){var S=FL.rk,out=$('flRkOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/flow/rank?'+flQ({inv:S.inv,period:S.period,side:S.side,market:S.market,pool:S.pool,top:S.top,fresh:S.fresh})).then(function(j){if(my!==S.seq)return;var o=$('flRkOut');if(!o)return;o.innerHTML='';if(j.error){o.appendChild(el('p','note bad','⚠ '+j.error));return}S.data=j;flRankDraw(o)}).catch(function(){var o=$('flRkOut');if(o){o.innerHTML='';o.appendChild(el('p','note bad','⚠ 불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.'))}})}
function flRankDraw(out){var j=FL.rk.data;out.innerHTML='';if(!j)return;if(j.empty){flEmpty(out,j);return}var q=j.q,lbl={foreign:'외국인',inst:'기관',comb:'외국인+기관 합산'}[q.inv]+' '+q.period+'일 '+(q.side==='buy'?'순매수':'순매도');
 out.appendChild(el('p','note',lbl+' 기준 · 조건에 맞는 종목 '+j.matched+'개 중 상위 '+j.items.length+'개 · 대상 '+j.universe+'종목 · 수급 기준일 '+(j.base_date||'-')));
 if(!j.items.length){out.appendChild(el('p','note','조건에 맞는 종목이 없어요. 시장·종목 범위를 넓혀 보세요.'));FL.tbl=null;return}
 var key=q.inv==='foreign'?'f':(q.inv==='inst'?'i':'c');var mx=0;j.items.forEach(function(it){var v=flVal(it,key,q.period);if(Math.abs(v)>mx)mx=Math.abs(v)});
 var drv={foreign:1,inst:2,comb:3}[q.inv];var HR=j.items.some(function(it){return it.o5!=null});var tb=flTblBuild(HR?['#','종목','현재가','외국인'+(drv===1?' ▼':''),'기관'+(drv===2?' ▼':''),'합산'+(drv===3?' ▼':''),'개인','기타*','신호']:['#','종목','현재가','외국인'+(drv===1?' ▼':''),'기관'+(drv===2?' ▼':''),'합산'+(drv===3?' ▼':''),'신호'],HR?['','','r','r','r','r','r','r','']:['','','r','r','r','r','']);
 j.items.forEach(function(it,i){var tr=el('tr',it.stale?'flOld':'');tr.appendChild(el('td','flZ',String(i+1)));var nm=el('td');var a=flTk(el('span','nm',it.name),it.ticker);nm.appendChild(a);if(window.NvIcon)nm.appendChild(window.NvIcon(it.ticker));
  var tg=el('span','flZ',' ▾');tg.style.cursor='pointer';tg.title='1·5·20일 자세히';tg.onclick=function(){FL.rk.open[it.ticker]=!FL.rk.open[it.ticker];flRankDraw(out)};nm.appendChild(tg);
  nm.appendChild(el('div','sb',it.ticker+(it.market?' · '+it.market:'')+(it.stale?' · 오래된 자료('+it.base+')':'')));tr.appendChild(nm);
  var pc=el('td','r');pc.appendChild(document.createTextNode(it.price?flN(it.price)+'원':'-'));if(it.pct!=null){var pp=el('div',flCls(it.pct),(it.pct>0?'+':'')+Number(it.pct).toFixed(2)+'%');pp.style.fontSize='11px';pc.appendChild(pp)}tr.appendChild(pc);
  [['f',1],['i',2],['c',3]].forEach(function(z){var v=flVal(it,z[0],q.period),td=el('td','r');td.appendChild(el('span',flCls(v),flFv(v)));if(drv===z[1]&&mx){var w=el('div','flBw'),f=el('i');f.style.width=Math.max(3,Math.round(Math.abs(v)/mx*100))+'%';f.style.background=v>0?'#f87171':'#60a5fa';w.appendChild(f);td.appendChild(w)}tr.appendChild(td)});
  if(HR){[it['r'+q.period],it['o'+q.period]].forEach(function(v){var td=el('td','r');td.appendChild(el('span',v==null?'flZ':flCls(v),v==null?'-':flFv(v)));tr.appendChild(td)})}
  var sg=el('td');sg.appendChild(flChips(it));tr.appendChild(sg);tb.t.appendChild(tr);
  if(FL.rk.open[it.ticker]){var d2=el('tr','flDt'),dc=el('td');dc.colSpan=HR?9:7;var kv=el('div','flKv');[['1일',1],['5일',5],['20일',20]].forEach(function(z){var b=el('div');b.appendChild(el('b',null,'최근 '+z[0]));
    (HR?[['외국인','f'],['기관','i'],['합산','c'],['개인','r'],['기타*','o']]:[['외국인','f'],['기관','i'],['합산','c']]).forEach(function(y){var v=flVal(it,y[1],String(z[1]));var l=el('div');l.style.cssText='background:none;border:0;padding:0';l.appendChild(document.createTextNode(y[0]+' '));l.appendChild(el('span',flCls(v),flFv(v)));b.appendChild(l)});kv.appendChild(b)});dc.appendChild(kv);
   var br=el('div','bar');br.appendChild(flStockBtn(it.ticker));if(it.cap)br.appendChild(el('span','m','시총 '+flCap(it.cap)));if(it.score!=null)br.appendChild(el('span','m','종합점수 '+it.score));dc.appendChild(br);d2.appendChild(dc);tb.t.appendChild(d2)}});
 out.appendChild(tb.wrap);if(HR)out.appendChild(el('p','note','* 기타 = −(개인+외국인+기관) 추정값(기타법인·기타외국인 등). 네이버는 종목별로 개인·외국인·기관(합계)만 줘서 사모·연기금 등은 나눌 수 없어요. 금액은 ‘순매수 수량×종가’ 근사치예요.'));
 flSetTbl('수급 순위 · '+lbl,[{h:'#',raw:function(it){return j.items.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'현재가(원)',raw:function(it){return it.price},num:1,disp:function(it,r){return r?flN(r):'-'}},
  {h:'외국인 '+q.period+'일(원)',raw:function(it){return flVal(it,'f',q.period)},num:1,disp:function(it,r){return flFv(r)}},{h:'기관 '+q.period+'일(원)',raw:function(it){return flVal(it,'i',q.period)},num:1,disp:function(it,r){return flFv(r)}},
  {h:'합산 '+q.period+'일(원)',raw:function(it){return flVal(it,'c',q.period)},num:1,disp:function(it,r){return flFv(r)}}],j.items,j.base_date);
 flExpBar(out)}
function flVal(it,k,p){if(k==='c')return (it['f'+p]||0)+(it['i'+p]||0);return it[k+p]||0}

/* ── 신호 종목(기능 'sig') ── */
function flSecSig(box){var S=FL.sg;box.appendChild(el('p','note','원본 프로그램의 수급 신호식을 그대로 쓴 목록이에요. 칩을 눌러 신호를 바꿔 보세요. 수급 점수는 원본 종목발굴 점수 중 수급 항목(쌍끌이 +18 · 쌍끌이⚠ +10 · 수급전환 +22 · 동반매도 −15)이에요.'));
 var cr=el('div','flSug');FL_KIND.forEach(function(k){var cnt=FL.sum&&FL.sum.counts?FL.sum.counts[k[0]]:null;var b=el('button','flCh'+(S.kind===k[0]?' a':''),k[1]+(cnt!=null?' '+cnt:''));b.type='button';b.title=k[2];b.style.cursor='pointer';b.onclick=function(){S.kind=k[0];S.data=null;flShow()};cr.appendChild(b)});box.appendChild(cr);
 var ds=FL_KIND.filter(function(k){return k[0]===S.kind})[0];box.appendChild(el('p','note','▶ '+ds[1]+': '+ds[2]));
 var bar=el('div','bar'),go=function(){flSigGo()};flSel(bar,'시장',S,'market',[['all','전체'],['KOSPI','코스피'],['KOSDAQ','코스닥']],go);flSel(bar,'개수',S,'top',[['10','10개'],['30','30개'],['60','60개']],go);bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);
 var out=el('div');out.id='flSgOut';box.appendChild(out);if(S.data)flSigDraw(out);else flSigGo()}
function flSigGo(){var S=FL.sg,out=$('flSgOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/flow/signals?'+flQ({kind:S.kind,market:S.market,top:S.top})).then(function(j){if(my!==S.seq)return;var o=$('flSgOut');if(!o)return;o.innerHTML='';if(j.error){o.appendChild(el('p','note bad','⚠ '+j.error));return}S.data=j;flSigDraw(o)}).catch(function(){var o=$('flSgOut');if(o){o.innerHTML='';o.appendChild(el('p','note bad','⚠ 불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.'))}})}
function flSigDraw(out){var j=FL.sg.data;out.innerHTML='';if(!j)return;if(j.empty){flEmpty(out,j);return}
 out.appendChild(el('p','note','해당 종목 '+j.matched+'개 중 상위 '+j.items.length+'개 · 수급 기준일 '+(j.base_date||'-')));if(!j.items.length){out.appendChild(el('p','note','지금 이 신호에 해당하는 종목이 없어요.'));FL.tbl=null;return}
 var tb=flTblBuild(['#','종목','수급 점수','외국인 20일','기관 20일','합산 5일','합산 1일','비고'],['','','r','r','r','r','r','']);
 j.items.forEach(function(it,i){var tr=el('tr');tr.appendChild(el('td','flZ',String(i+1)));var nm=el('td');nm.appendChild(flTk(el('span','nm',it.name),it.ticker));nm.appendChild(el('div','sb',it.ticker+(it.market?' · '+it.market:'')+(it.price?' · '+flN(it.price)+'원':'')));tr.appendChild(nm);
  tr.appendChild(el('td','r '+flCls(it.ss),(it.ss>0?'+':'')+it.ss));tr.appendChild(el('td','r '+flCls(it.f20),flFv(it.f20)));tr.appendChild(el('td','r '+flCls(it.i20),flFv(it.i20)));
  var c5=it.f5+it.i5,c1=it.f1+it.i1;tr.appendChild(el('td','r '+flCls(c5),flFv(c5)));tr.appendChild(el('td','r '+flCls(c1),flFv(c1)));
  var nt=el('td');var tx='';if(j.kind==='turn')tx=(it.who||[]).join('·')+' 전환';else if(j.kind==='persist')tx=(it.who||[]).join('·')+' 지속';else if(j.kind==='surge')tx='20일 일평균의 '+it.ratio+'배';else if(j.kind==='warn')tx='오늘 동반 순매도 '+flFv(c1);
  nt.appendChild(tx?el('span','m',tx):flChips(it));tr.appendChild(nt);tb.t.appendChild(tr)});out.appendChild(tb.wrap);
 flSetTbl('수급 신호 · '+FL_KIND.filter(function(k){return k[0]===j.kind})[0][1],[{h:'#',raw:function(it){return j.items.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'수급 점수',raw:function(it){return it.ss},num:1,disp:function(it,r){return (r>0?'+':'')+r}},
  {h:'외국인 20일(원)',raw:function(it){return it.f20},num:1,disp:function(it,r){return flFv(r)}},{h:'기관 20일(원)',raw:function(it){return it.i20},num:1,disp:function(it,r){return flFv(r)}},{h:'합산 5일(원)',raw:function(it){return it.f5+it.i5},num:1,disp:function(it,r){return flFv(r)}},{h:'합산 1일(원)',raw:function(it){return it.f1+it.i1},num:1,disp:function(it,r){return flFv(r)}}],j.items,j.base_date);
 flExpBar(out)}

/* ── 종목별 추이(기능 'stock') ── */
function flSecStock(box){var S=FL.st;box.appendChild(el('p','note','종목 이름이나 코드를 넣으면 그 종목의 외국인·기관 순매수(최근 1일·5일·20일)와 하루 평균 흐름을 보여 줘요. 오른쪽(최근)으로 갈수록 선이 올라가면 최근 수급이 더 강해졌다는 뜻이에요.'));
 var r=el('div','bar');var q=el('input');q.placeholder='종목명 또는 코드 (예: 삼성전자, 005930)';q.style.width='min(260px,100%)';q.value=S.q;q.id='flStQ';r.appendChild(q);
 var sg=el('div','flSug');sg.id='flStSug';
 function sugg(){S.q=q.value;sg.innerHTML='';if(!q.value.trim())return;api('/admin/api/flow/search?q='+encodeURIComponent(q.value.trim())).then(function(j){var s2=$('flStSug');if(!s2)return;s2.innerHTML='';(j.rows||[]).forEach(function(x){s2.appendChild(bt(x.name+' '+x.ticker,'bt3',function(){q.value='';S.q='';s2.innerHTML='';flStockOpen(x.ticker)}))});if(j.rows&&!j.rows.length)s2.appendChild(el('span','m','수급 자료에 없는 종목이에요.'))})}
 q.oninput=function(){clearTimeout(FL.tmr);FL.tmr=setTimeout(sugg,260)};q.onkeydown=function(e){if(e.key==='Enter'){var v=q.value.trim();if(/^[0-9A-Za-z]{6}$/.test(v))flStockOpen(v.toUpperCase());else sugg()}};
 r.appendChild(bt('조회하기','bt',function(){var v=q.value.trim();if(/^[0-9A-Za-z]{6}$/.test(v))flStockOpen(v.toUpperCase());else sugg()}));box.appendChild(r);box.appendChild(sg);
 var out=el('div');out.id='flStOut';box.appendChild(out);if(S.data)flStockDraw(out);else out.appendChild(el('p','note','위에서 종목을 골라 보세요. 순위 표의 ▾ 칸에서 바로 넘어올 수도 있어요.'))}
function flStockOpen(tk){if(!ftOk('stock')){lockDlg('stock');return}var S=FL.st;S.tk=tk;if(FL.sec!=='stock'){FL.sec='stock';flNavDraw();flShow()}
 var out=$('flStOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/flow/stock?ticker='+encodeURIComponent(tk)).then(function(j){if(my!==S.seq)return;var o=$('flStOut');if(!o)return;o.innerHTML='';if(j.error){o.appendChild(el('p','note bad','⚠ '+j.error));S.data=null;return}S.data=j;flStockDraw(o)}).catch(function(){var o=$('flStOut');if(o){o.innerHTML='';o.appendChild(el('p','note bad','⚠ 불러오지 못했어요.'))}})}
function flLine(labels,series){var NS='http://www.w3.org/2000/svg',W=360,H=190,L=62,R=24,T=18,B=34;var svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.setAttribute('width','100%');svg.setAttribute('role','img');svg.setAttribute('aria-label','일평균 수급 꺾은선 그래프');
 var all=[0];series.forEach(function(s){s.vals.forEach(function(v){all.push(v)})});var mn=Math.min.apply(null,all),mx=Math.max.apply(null,all);if(mx===mn){mx+=1;mn-=1}var pad=(mx-mn)*0.12;mx+=pad;mn-=pad;
 function X(i){return L+(W-L-R)*i/(labels.length-1)}function Y(v){return T+(H-T-B)*(mx-v)/(mx-mn)}
 function ln(x1,y1,x2,y2,col,w,dash){var e=document.createElementNS(NS,'line');e.setAttribute('x1',x1);e.setAttribute('y1',y1);e.setAttribute('x2',x2);e.setAttribute('y2',y2);e.setAttribute('stroke',col);e.setAttribute('stroke-width',w);if(dash)e.setAttribute('stroke-dasharray',dash);svg.appendChild(e)}
 function tx(x,y,s,col,anchor,sz,wt){var e=document.createElementNS(NS,'text');e.setAttribute('x',x);e.setAttribute('y',y);e.setAttribute('fill',col);e.setAttribute('font-size',sz||11);e.setAttribute('text-anchor',anchor||'middle');if(wt)e.setAttribute('font-weight',wt);e.textContent=s;svg.appendChild(e)}
 var z=Y(0);var r1=document.createElementNS(NS,'rect');r1.setAttribute('x',L);r1.setAttribute('y',T);r1.setAttribute('width',W-L-R);r1.setAttribute('height',Math.max(0,z-T));r1.setAttribute('fill','#fef2f2');svg.appendChild(r1);
 var r2=document.createElementNS(NS,'rect');r2.setAttribute('x',L);r2.setAttribute('y',z);r2.setAttribute('width',W-L-R);r2.setAttribute('height',Math.max(0,H-B-z));r2.setAttribute('fill','#eff6ff');svg.appendChild(r2);
 ln(L,z,W-R,z,'#475569',1.6);tx(L-6,z+4,'0','#475569','end');tx(L-6,T+8,flAbs(mx-pad),'#94a3b8','end',10);tx(L-6,H-B,'-'+flAbs(mn+pad),'#94a3b8','end',10);
 labels.forEach(function(l,i){tx(X(i),H-12,l,'#64748b','middle',11.5,'700')});
 series.forEach(function(s){var d='';s.vals.forEach(function(v,i){d+=(i?'L':'M')+X(i)+' '+Y(v)+' '});var pth=document.createElementNS(NS,'path');pth.setAttribute('d',d);pth.setAttribute('fill','none');pth.setAttribute('stroke',s.color);pth.setAttribute('stroke-width',2.4);if(s.dash)pth.setAttribute('stroke-dasharray',s.dash);svg.appendChild(pth);
  s.vals.forEach(function(v,i){var c=document.createElementNS(NS,'circle');c.setAttribute('cx',X(i));c.setAttribute('cy',Y(v));c.setAttribute('r',3.6);c.setAttribute('fill',s.color);svg.appendChild(c)})});
 return svg}
function flStockDraw(out){var j=FL.st.data;out.innerHTML='';if(!j)return;if(j.empty){flEmpty(out,j);return}var it=j.item;var c=el('div','flCard');var h=el('h3');h.appendChild(flTk(el('span',null,it.name),it.ticker));h.appendChild(document.createTextNode(' '));h.appendChild(el('span','m',it.ticker+(it.market?' · '+it.market:'')));c.appendChild(h);
 var mt=[];if(it.price)mt.push('현재가 '+flN(it.price)+'원'+(it.pct!=null?' ('+(it.pct>0?'+':'')+Number(it.pct).toFixed(2)+'%)':''));if(it.cap)mt.push('시총 '+flCap(it.cap));if(it.score!=null)mt.push('종합점수 '+it.score);mt.push('수급 기준일 '+(it.base||'-'));c.appendChild(el('div','m',mt.join(' · ')));
 if(it.stale)c.appendChild(el('p','note bad','⚠ 이 종목의 수급 자료는 기준일이 오래됐어요(7일 초과). 신호는 계산하지 않았어요.'));
 else if(it.sg===undefined)c.appendChild(el('p','note','🔒 신호·수급 점수는 수급 신호 기능이 열린 등급부터 보여요.'));
 else{var sr=el('div');sr.style.margin='8px 0';sr.appendChild(flChips(it));sr.appendChild(el('span','m',' 수급 점수 '+(it.ss>0?'+':'')+it.ss+'(원본 종목발굴 점수 중 수급 항목)'));c.appendChild(sr);
  if(j.pos&&j.pos.c20)c.appendChild(el('div','m',j.market_scope+' 안에서 합산 순매수 순위 — 5일 '+j.pos.c5[0]+'위 · 20일 '+j.pos.c20[0]+'위 (대상 '+j.pos.c20[1]+'종목)'))}
 var tb=flTblBuild(['구분','1일','5일','20일','하루평균(5일)','하루평균(20일)'],['','r','r','r','r','r']);var ser=[];
 [['외국인','f','#2563eb',null],['기관','i','#f97316',null],['합산','c','#475569','5 4']].concat(it.o5!=null?[['개인','r','#16a34a',null,1],['기타*','o','#7c3aed',null,1]]:[]).forEach(function(z){var v1=flVal(it,z[1],'1'),v5=flVal(it,z[1],'5'),v20=flVal(it,z[1],'20');var tr=el('tr');tr.appendChild(el('td',null,z[0]));[v1,v5,v20,v5/5,v20/20].forEach(function(v){tr.appendChild(el('td','r '+flCls(v),flFv(v)))});tb.t.appendChild(tr);if(!z[4])ser.push({name:z[0],color:z[2],dash:z[3],vals:[v20/20,v5/5,v1]})});
 c.appendChild(tb.wrap);var lg=el('div','m');lg.textContent='그래프 — 하루 평균 순매수(선): 20일 → 5일 → 1일(최근). 파랑 외국인 · 주황 기관 · 점선 합산. 빨간 바탕=순매수 영역, 파란 바탕=순매도 영역.';c.appendChild(lg);var gw=el('div');gw.style.cssText='max-width:520px';gw.appendChild(flLine(['20일 평균','5일 평균','오늘'],ser));c.appendChild(gw);
 if(j.themes&&j.themes.length){var tw=el('div');tw.style.marginTop='8px';tw.appendChild(el('span','m','소속 테마: '));j.themes.forEach(function(t){var b=el('button','flCh s',t);b.type='button';b.style.cursor='pointer';b.onclick=function(){if(!ftOk('theme')){lockDlg('theme');return}FL.th.name=t;FL.th.mem=null;flGo('theme')};tw.appendChild(b);tw.appendChild(document.createTextNode(' '))});c.appendChild(tw)}
 else if(j.locked&&j.locked.indexOf('theme')>=0)c.appendChild(el('p','note','🔒 소속 테마는 테마별 수급 기능이 열린 등급부터 보여요.'));
 var lk=el('div','bar');if(window.NvIcon){lk.appendChild(window.NvIcon(it.ticker));lk.appendChild(el('span','m',' 네이버 증권에서 보기(새 창)'))}else{var a=el('a',null,'네이버 증권에서 보기 ↗');a.href='https://finance.naver.com/item/main.naver?code='+encodeURIComponent(it.ticker);a.target='_blank';a.rel='noopener';lk.appendChild(a)}c.appendChild(lk);out.appendChild(c)}

/* ── 테마별(기능 'theme') ── */
function flSecTheme(box){var S=FL.th;box.appendChild(el('p','note','같은 테마로 묶인 종목들의 외국인·기관 순매수 합계예요. 테마 이름을 누르면 그 테마 안의 종목별 수급을 볼 수 있어요. 종목이 3개 이상 있는 테마만 모아요.'));
 var bar=el('div','bar'),go=function(){S.name='';S.list=null;S.mem=null;flThemeGo()};flSel(bar,'기간',S,'period',[['5','5일'],['20','20일']],go);flSel(bar,'방향',S,'side',[['buy','순매수 많은 테마'],['sell','순매도 많은 테마']],go);flSel(bar,'최소 종목 수',S,'min',[['3','3개 이상'],['5','5개 이상'],['10','10개 이상']],go);bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);
 var out=el('div');out.id='flThOut';box.appendChild(out);flThemeGo(true)}
function flThemeGo(keep){var S=FL.th,out=$('flThOut');if(!out)return;var my=++S.seq;
 if(S.name){if(keep&&S.mem){flThemeMem(out);return}out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
  api('/admin/api/flow/theme?'+flQ({theme:S.name,period:S.period})).then(function(j){if(my!==S.seq)return;var o=$('flThOut');if(!o)return;if(j.error){o.innerHTML='';o.appendChild(el('p','note bad','⚠ '+j.error));return}S.mem=j;flThemeMem(o)});return}
 if(keep&&S.list){flThemeList(out);return}out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/flow/theme?'+flQ({period:S.period,side:S.side,min:S.min,top:30})).then(function(j){if(my!==S.seq)return;var o=$('flThOut');if(!o)return;if(j.error){o.innerHTML='';o.appendChild(el('p','note bad','⚠ '+j.error));return}S.list=j;flThemeList(o)})}
function flThemeList(out){var j=FL.th.list;out.innerHTML='';if(!j)return;if(j.empty){flEmpty(out,j);return}out.appendChild(el('p','note','조건에 맞는 테마 '+j.matched+'개 중 상위 '+j.items.length+'개 · 최근 '+j.period+'일 합계 · 수급 기준일 '+(j.base_date||'-')));
 if(!j.items.length){out.appendChild(el('p','note','조건에 맞는 테마가 없어요.'));FL.tbl=null;return}var mx=0;j.items.forEach(function(x){if(Math.abs(x.c)>mx)mx=Math.abs(x.c)});
 var tb=flTblBuild(['#','테마','종목 수','외국인','기관','합산','쌍끌이'],['','','r','r','r','r','r']);
 j.items.forEach(function(x,i){var tr=el('tr');tr.appendChild(el('td','flZ',String(i+1)));var td=el('td');var a=el('span','nm',x.theme);a.style.cursor='pointer';a.style.color='#0f766e';a.style.textDecoration='underline';a.onclick=function(){FL.th.name=x.theme;FL.th.mem=null;flThemeGo()};td.appendChild(a);td.appendChild(el('div','sb','순매수 종목 '+x.pos+'/'+x.n));tr.appendChild(td);
  tr.appendChild(el('td','r',String(x.n)));tr.appendChild(el('td','r '+flCls(x.f),flFv(x.f)));tr.appendChild(el('td','r '+flCls(x.i),flFv(x.i)));var cc=el('td','r');cc.appendChild(el('span',flCls(x.c),flFv(x.c)));var w=el('div','flBw'),f=el('i');f.style.width=Math.max(3,Math.round(Math.abs(x.c)/mx*100))+'%';f.style.background=x.c>0?'#f87171':'#60a5fa';w.appendChild(f);cc.appendChild(w);tr.appendChild(cc);tr.appendChild(el('td','r',x.dual==null?'🔒':String(x.dual)));tb.t.appendChild(tr)});out.appendChild(tb.wrap);
 flSetTbl('테마별 수급 · 최근 '+j.period+'일',[{h:'#',raw:function(x){return j.items.indexOf(x)+1}},{h:'테마',raw:function(x){return x.theme}},{h:'종목 수',raw:function(x){return x.n},num:1,disp:function(x,r){return String(r)}},{h:'외국인(원)',raw:function(x){return x.f},num:1,disp:function(x,r){return flFv(r)}},{h:'기관(원)',raw:function(x){return x.i},num:1,disp:function(x,r){return flFv(r)}},{h:'합산(원)',raw:function(x){return x.c},num:1,disp:function(x,r){return flFv(r)}},{h:'쌍끌이 종목',raw:function(x){return x.dual==null?'':x.dual},num:1,disp:function(x,r){return String(r)}}],j.items,j.base_date);flExpBar(out)}
function flThemeMem(out){var j=FL.th.mem;out.innerHTML='';if(!j)return;var bk=el('div','bar');bk.appendChild(bt('← 테마 목록으로','bt3',function(){FL.th.name='';FL.th.mem=null;flThemeGo(true)}));bk.appendChild(el('b',null,'🏷 '+j.theme));out.appendChild(bk);
 out.appendChild(el('p','note','이 테마에서 수급 자료가 있는 종목 '+j.items.length+'개(테마 전체 '+j.total+'종목) · 최근 '+j.period+'일 합산 순서 · 수급 기준일 '+(j.base_date||'-')));
 var tb=flTblBuild(['#','종목','현재가','외국인','기관','합산','신호'],['','','r','r','r','r','']);
 j.items.forEach(function(it,i){var tr=el('tr');tr.appendChild(el('td','flZ',String(i+1)));var nm=el('td');nm.appendChild(flTk(el('span','nm',it.name),it.ticker));nm.appendChild(el('div','sb',it.ticker+(it.market?' · '+it.market:'')));tr.appendChild(nm);tr.appendChild(el('td','r',it.price?flN(it.price)+'원':'-'));
  [flVal(it,'f',j.period),flVal(it,'i',j.period),flVal(it,'c',j.period)].forEach(function(v){tr.appendChild(el('td','r '+flCls(v),flFv(v)))});var sg=el('td');sg.appendChild(flChips(it));tr.appendChild(sg);tb.t.appendChild(tr)});out.appendChild(tb.wrap);
 flSetTbl('테마 수급 · '+j.theme+' · 최근 '+j.period+'일',[{h:'#',raw:function(it){return j.items.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'외국인(원)',raw:function(it){return flVal(it,'f',j.period)},num:1,disp:function(it,r){return flFv(r)}},{h:'기관(원)',raw:function(it){return flVal(it,'i',j.period)},num:1,disp:function(it,r){return flFv(r)}},{h:'합산(원)',raw:function(it){return flVal(it,'c',j.period)},num:1,disp:function(it,r){return flFv(r)}}],j.items,j.base_date);flExpBar(out)}

/* ── AI 해설 프롬프트(기능 'ai') — 수동 AI 도우미: 프롬프트 복사 → AI 사이트 → 답변 붙여넣기 ── */
function flSecAi(box){var S=FL.ai;box.appendChild(el('p','note','지금 조건의 상위 20종목 수급 데이터를 담은 프롬프트를 만들어, 사용하는 AI(제미나이·챗GPT·클로드 등)에 붙여 넣을 수 있게 해요. AI가 답하면 복사해서 이 창으로 돌아오면 아래에 보여 줘요. AI 답변은 참고용이며 틀릴 수 있어요.'));
 var bar=el('div','bar'),noop=function(){};flSel(bar,'투자자',S,'inv',[['comb','외국인+기관 합산'],['foreign','외국인'],['inst','기관']],noop);flSel(bar,'기간',S,'period',[['1','1일'],['5','5일'],['20','20일']],noop);flSel(bar,'방향',S,'side',[['buy','순매수'],['sell','순매도']],noop);flSel(bar,'시장',S,'market',[['all','전체'],['KOSPI','코스피'],['KOSDAQ','코스닥']],noop);
 bar.appendChild(ft(bt('🤖 AI 프롬프트 만들기','bt',flAiRun),'ai'));box.appendChild(bar);var out=el('div');out.id='flAiOut';box.appendChild(out);flAiDraw()}
function flAiRun(){if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}var S=FL.ai;
 api('/admin/api/flow/prompt?'+flQ({inv:S.inv,period:S.period,side:S.side,market:S.market})).then(function(j){if(j.error){toast(j.error);return}if(j.empty){toast(j.msg);return}
  window.MiniAI.run({title:'수급 AI 해설 — '+j.label,key:'flow',steps:[{label:j.label,prompt:j.prompt}],minLen:150,hint:'AI가 "## 수급 특징이 두드러진 종목 …" 형식으로 답하면 답변 전체를 복사하고 이 창으로 돌아오세요.',
   preview:function(t){var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString('ko-KR')+'자 — '+t.slice(0,240)+(t.length>240?' …':'');return {node:x,canApply:t.trim().length>=100,strict:true}},
   apply:function(t){FL.ai.text=String(t||'').slice(0,20000);FL.flag.img=false;FL.flag.blog=false;FL.flag.posted=false;flAiDraw();flSteps();if(!MEMBER_MODE)setTimeout(function(){if(window.MiniFlow)MiniFlow.run('flow',FLFLOW,FLACTS,'ai')},60);return Promise.resolve({message:MEMBER_MODE?'AI 해설을 아래 화면에 보여 줬어요.':'AI 해설을 저장했어요. 설정에 따라 이미지 → 글 → 블로그 복사·열기로 이어져요.'})}})})}
function flAiDraw(){var out=$('flAiOut');if(!out)return;out.innerHTML='';var t=FL.ai.text;if(!t){out.appendChild(el('p','note','아직 AI 해설이 없어요. [AI 프롬프트 만들기]를 눌러 보세요.'));return}
 var box=el('div','flAiOut');t.split('\n').forEach(function(l){var m;var s=l.replace(/\*\*/g,'');if((m=/^##\s+(.*)$/.exec(s))){box.appendChild(el('span','h2',m[1]))}else if((m=/^###\s+(.*)$/.exec(s))){box.appendChild(el('span','h3',m[1]))}else{box.appendChild(document.createTextNode(s));box.appendChild(document.createElement('br'))}});out.appendChild(box);
 var r=el('div','bar');r.appendChild(bt('📋 해설 복사하기','bt3',function(){var ok=window.MiniAI&&window.MiniAI.copy?window.MiniAI.copy(FL.ai.text):false;toast(ok?'복사했어요':'복사가 막혔어요')}));r.appendChild(bt('✖ 지우기','bt3',function(){FL.ai.text='';flAiDraw()}));out.appendChild(r);
 out.appendChild(el('p','note','⚠ AI가 만든 참고 글이에요. 숫자와 내용이 틀릴 수 있고, 특정 종목의 매수·매도 권유가 아니에요.'))}

/* ── 단계 바(5단계: 수급 자료 → AI 해설 → 이미지 → 글 → 블로그에 쓰기) + 자동/수동 진행([⚙ 설정]) — 관리자만 ── */
var FLFLOW=['ai','img','blog','post'];
function flHas(){return !!(FL.sum&&!FL.sum.empty)}
function flSteps(){var sp=$('flSteps');if(!sp||MEMBER_MODE)return;var has=flHas(),ai=!!(FL.ai.text&&FL.ai.text.trim()),F=FL.flag;
 var steps=[{t:'수급 자료',sub:has?((FL.sum.status&&FL.sum.status.base_date)||'')+' · 완료':'가져오거나 조회하세요',done:has,go:function(){flStepRun('rank')}},
  {t:'AI 해설',sub:ai?'완료 · 다시 만들기':'눌러서 시작',done:ai,go:function(){flStepRun('ai')}},
  {t:'이미지 만들기',sub:F.img?'만들었어요 · 다시 만들기':'눌러서 만들기',done:F.img,go:function(){flStepRun('img')}},
  {t:'글 만들기',sub:F.blog?'완료 · 다시 만들기':'눌러서 만들기',done:F.blog,go:function(){flStepRun('blog')}},
  {t:'블로그에 쓰기',sub:F.posted?'복사·열기 완료':(F.blog?'복사하고 블로그 열기':'글을 먼저 만드세요'),done:F.posted,off:!F.blog,go:function(){flStepRun('post')}}];
 window.FlowBar.draw(sp,{steps:steps,runAll:function(){flStepRun('all')},note:'[⚡ 블로그까지 한 번에]는 AI 해설 → 이미지 → 글 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 블로그 글쓰기 화면에 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'})}
function flStepRun(id){
 if(id==='rank'){flGo('rank');return}
 if(!flHas()){toast('먼저 수급 자료를 가져와 주세요(아래 [📦 수급 자료] 상자).');return}
 if(id==='ai'){if(!ftOk('ai')){lockDlg('ai');return}flGo('ai');flAiRun();return}
 if(id==='img'){FL.flag.img=false;MiniFlow.go('flow',FLFLOW,FLACTS,'img');return}
 if(id==='blog'){FL.flag.blog=false;MiniFlow.go('flow',FLFLOW,FLACTS,'blog');return}
 if(id==='post'){flPostGo(false);return}
 if(id==='all'){toast('⚡ 블로그까지 이어서 진행해요');MiniFlow.force('flow',FLFLOW,FLACTS)}}
function flPostGo(auto){var P=FL.blogPanel;if(FL.sec==='blog'&&P&&P.built()){P.copyOpen(auto);return true}
 if(!FL.flag.blog){if(!auto)toast('먼저 ④ 글 만들기를 해 주세요');return false}
 flGo('blog');var k=0,t=setInterval(function(){var Q=FL.blogPanel;if(Q&&Q.built()){clearInterval(t);Q.copyOpen(auto)}else if(++k>40)clearInterval(t)},250);return true}
var FLACTS={
 ai:function(next){if(!flHas())return;if((FL.ai.text||'').trim()){next();return}if(!ftOk('ai'))return;flGo('ai');flAiRun()},
 img:function(next){if(FL.flag.img){next();return}flEnsure().then(function(){flGo('img');if(!FL.imgPanel)return;return FL.imgPanel.gen(true).then(function(){if(FL.imgPanel&&FL.imgPanel.items())next()})}).catch(function(){})},
 blog:function(next){if(FL.flag.blog&&FL.sec==='blog'&&FL.blogPanel&&FL.blogPanel.built()){next();return}flEnsure().then(function(){FL.flag.blog=false;flGo('blog');if(!FL.blogPanel)return;return FL.blogPanel.rebuild().then(function(j){if(j&&!j.error)next()})}).catch(function(){})},
 post:function(next){if(flPostGo(true))next()}};
/* 이미지·글은 지금 순위 조건의 표를 쓴다 — 순위를 한 번도 안 열었으면 기본 조건으로 불러온다 */
function flEnsure(){var S=FL.rk;if(S.data&&!S.data.empty&&S.data.items&&S.data.items.length)return Promise.resolve(S.data);
 return api('/admin/api/flow/rank?'+flQ({inv:S.inv,period:S.period,side:S.side,market:S.market,pool:S.pool,top:S.top,fresh:S.fresh})).then(function(j){if(j.error)throw new Error(j.error);if(j.empty)throw new Error(j.msg||'수급 자료가 없어요.');S.data=j;return j})}
function flStampD(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+'-'+z(d.getMonth()+1)+'-'+z(d.getDate())}
function flSecImg(box){if(MEMBER_MODE)return;box.appendChild(el('p','note','지금 순위 조건(투자자·기간·방향)의 상위 10종목과 신호 종목 수를 한 장의 대시보드 이미지로 만들어요. 저장 폴더와 자동/수동 저장은 [⚙ 저장 설정]에서 정해요.'));
 var ib=el('div');box.appendChild(ib);if(!window.ImgKit){ib.appendChild(el('p','note bad','이미지 도구(menu_img.py)가 올라가지 않았어요.'));return}
 FL.imgPanel=ImgKit.panel(ib,{menu:'flow',name:'수급분석',ticker:flStamp(),perStock:false,onDone:function(){FL.flag.img=true;flSteps()},gen:function(scale){return flEnsure().then(function(j){if(!window.FlImg)throw new Error('이미지 도구를 불러오지 못했어요.');return window.FlImg.build(j,FL.sum,scale)})}});
 if(FL.flag.img)FL.imgPanel.gen(false)}
function flSecBlog(box){if(MEMBER_MODE)return;box.appendChild(el('p','note','순위·신호·AI 해설로 블로그용 글(HTML)을 만들어요. 글은 자동으로 올라가지 않고, [복사하고 블로그 열기]로 복사한 뒤 블로그 글쓰기 화면에 붙여 넣는 방식이에요. 이미지는 글 위쪽에 직접 올려 주세요.'));
 var bx=el('div');box.appendChild(bx);if(!window.BlogKit){bx.appendChild(el('p','note bad','블로그 도구(menu_blog.py)가 올라가지 않았어요.'));FL.blogPanel=null;return}
 var secs=[['stats','요약통계'],['rank','순위표'],['signal','신호 종목'],['ai','AI 해설']];
 FL.blogPanel=window.BlogKit.panel(bx,{idp:'fl',key:'flow',kind:'flow',ticker:'D'+flStamp().slice(2),name:'수급분석 '+flStampD(),sections:secs,dup_warn:'',onBuilt:function(){FL.flag.blog=true;FL.flag.posted=false;flSteps()},onCopied:function(){FL.flag.posted=true;flSteps()},
  build:function(inc,title){return flEnsure().then(function(){return apiJ('/admin/api/flow/blog',{ai:FL.ai.text||'',inc:inc,title:title})}).catch(function(e){return {error:(e&&e.message)||'만들지 못했어요'}})}});
 if(FL.flag.blog)FL.blogPanel.rebuild()}
(function(){
var K=window.ImgKit;if(!K||window.FlImg)return;var T=K.text,RR=K.rr;
var NAVY0='#0a1228',NAVY1='#16275a',GOLD='#d6b25e',PAPER='#f4f0e6',INK='#0f172a',MUT='#64748b',UP='#e11d48',DN='#2563eb';
function card(c,x,y,w,h,r){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,r||24);c.fillStyle='#fff';c.fill();c.restore()}
function fv(v){v=Number(v)||0;if(v===0)return '0';var s=v>0?'+':'-',a=Math.abs(v);if(a>=1e12)return s+(a/1e12).toFixed(2)+'조';if(a>=1e10)return s+Math.round(a/1e8).toLocaleString('ko-KR')+'억';if(a>=1e8)return s+(a/1e8).toFixed(1)+'억';if(a>=1e4)return s+Math.round(a/1e4).toLocaleString('ko-KR')+'만';return s+'<1만'}
function cl(v){return v>0?UP:(v<0?DN:MUT)}
function dash(j,sum,scale){var its=(j.items||[]).slice(0,10),n=its.length,q=j.q||{},RH=76,W=1080,tH=100,tbH=74+n*RH+44,H=210+30+tH+30+tbH+30+118,m=K.make(W,H,scale),c=m.c;
 c.fillStyle=PAPER;c.fillRect(0,0,W,H);var g=c.createLinearGradient(0,0,0,210);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,210);c.fillStyle=GOLD;c.fillRect(0,0,W,8);
 var inv={foreign:'외국인',inst:'기관',comb:'외국인+기관 합산'}[q.inv]||'외국인+기관',sd=q.side==='sell'?'순매도':'순매수';
 T(c,'SUPPLY & DEMAND',W/2,60,{s:20,w:800,c:GOLD,a:'center',ls:5});T(c,inv+' '+(q.period||'5')+'일 '+sd+' 상위',W/2,132,{s:52,w:900,c:'#fff',a:'center',max:W-120});T(c,'수급 기준일 '+(j.base_date||'-')+' · 대상 '+(j.universe||0).toLocaleString('ko-KR')+'종목',W/2,178,{s:21,w:600,c:'#cbd5e1',a:'center',max:W-120});
 var ct=(sum&&sum.counts)||{},tl=[['쌍끌이',(ct.dual||0)+'종목',UP],['수급전환',(ct.turn||0)+'종목','#d97706'],['동반매도',(ct.bsell||0)+'종목',DN],['수급 급증',(ct.surge||0)+'종목','#7c3aed']],tw=(W-100-16*3)/4,y1=240;
 tl.forEach(function(t,i){var x=50+i*(tw+16);card(c,x,y1,tw,tH,18);T(c,t[0],x+tw/2,y1+36,{s:20,w:700,c:MUT,a:'center'});T(c,t[1],x+tw/2,y1+80,{s:34,w:900,c:t[2],a:'center',max:tw-16})});
 var y2=y1+tH+30;card(c,50,y2,W-100,tbH,24);c.fillStyle=GOLD;RR(c,76,y2+26,6,30,3);c.fill();T(c,'순위 TOP '+n,96,y2+50,{s:26,w:900,c:INK});
 var cx=[120,420,640,860,1010];T(c,'종목',cx[0],y2+90,{s:18,w:700,c:MUT});T(c,'외국인',cx[2],y2+90,{s:18,w:700,c:MUT,a:'right'});T(c,'기관',cx[3],y2+90,{s:18,w:700,c:MUT,a:'right'});T(c,'등락',cx[4],y2+90,{s:18,w:700,c:MUT,a:'right'});
 var p=q.period||'5';its.forEach(function(it,i){var y=y2+110+i*RH;if(i%2===0){c.fillStyle='#f8fafc';c.fillRect(66,y,W-132,RH-6)}
  T(c,String(i+1),96,y+46,{s:24,w:900,c:'#94a3b8',a:'center'});T(c,it.name,cx[0],y+36,{s:26,w:800,c:INK,max:290});T(c,(it.market||'')+' · '+(it.ticker||''),cx[0],y+62,{s:16,w:500,c:'#94a3b8'});
  var f=it['f'+p],ii=it['i'+p];T(c,fv(f),cx[2],y+46,{s:24,w:800,c:cl(f),a:'right'});T(c,fv(ii),cx[3],y+46,{s:24,w:800,c:cl(ii),a:'right'});
  var pc=it.pct;T(c,pc==null?'-':((pc>0?'+':'')+Number(pc).toFixed(2)+'%'),cx[4],y+46,{s:22,w:700,c:cl(pc||0),a:'right'})});
 var fy=H-118;c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,fy,W-120,2);T(c,'금액은 순매수 수량×종가 추정치예요. 공개 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다.',W/2,fy+38,{s:19,w:600,c:MUT,a:'center',max:W-120});
 T(c,'모든 투자 판단과 책임은 투자자 본인에게 있어요 · 출처 네이버증권 · stock.oky.kr',W/2,fy+72,{s:19,w:700,c:'#94a3b8',a:'center',max:W-120});return m.cv}
window.FlImg={build:function(j,sum,scale){return [{idx:1,label:'수급 대시보드',canvas:dash(j,sum,scale)}]}};
})();

/* ── 읽는 법(기능 'guide', 서버 호출 없음) ── */
function flSecGuide(box){var g=el('div','flGd');
 function H(t){g.appendChild(el('h4',null,t))}function P(t){g.appendChild(el('p',null,t))}function UL(a){var u=el('ul');a.forEach(function(x){u.appendChild(el('li',null,x))});g.appendChild(u)}
 H('순매수·순매도란?');P('하루 동안 외국인(또는 기관)이 산 금액에서 판 금액을 뺀 값이에요. 플러스(+, 빨강)면 순매수, 마이너스(−, 파랑)면 순매도예요. 기간(1일·5일·20일)은 최근 거래일을 모두 더한 값이고, 1일은 가장 최근 거래일 하루예요.');
 H('왜 외국인과 기관을 볼까요?');P('규모가 큰 투자자의 자금 흐름은 주가와 함께 움직이는 경우가 많아 참고 자료로 쓰여요. 다만 수급은 결과일 뿐 원인이 아니고, 같은 수급이라도 이후 주가는 달라질 수 있어요.');
 H('신호 용어(원본 프로그램과 같은 기준)');UL(['쌍끌이: 외국인과 기관이 20일 동안 모두 순매수','쌍끌이⚠: 쌍끌이인데 오늘 두 주체가 함께 순매도하고 그 금액이 20일 합계의 30%를 넘어, 흐름이 바뀌는지 살펴볼 때','수급전환: 외국인 또는 기관이 20일로는 순매도·중립이었는데 최근 5일은 순매수로 바뀐 것','동반매도: 외국인과 기관이 20일 동안 모두 순매도']);
 H('수급 점수란?');P('원본 프로그램의 종목발굴 점수 중 수급 부분만 따로 보여 줘요: 쌍끌이 +18, 쌍끌이⚠ +10, 수급전환 +22, 동반매도 −15. 높다고 오른다는 뜻이 아니라 “수급 모양이 얼마나 뚜렷한가”를 한 숫자로 줄인 거예요.');
 H('웹에서 더한 보조 지표(원본에는 없어요)');UL(['지속 순매수: 1일·5일·20일이 모두 순매수인 경우(외국인 또는 기관)','수급 급증: 오늘 합산 순매수가 20일 하루 평균의 3배 이상인 경우']);
 H('읽을 때 꼭 알아 두세요');UL(['자료는 가져온 캐시라 “수급 기준일”이 오늘보다 앞설 수 있어요(휴장·갱신 전).','기준일이 7일 넘게 지난 종목은 신호에서 빼고 표에서 회색으로 보여요.','수급 금액은 거래대금 기준 추정치라 실제와 조금 다를 수 있어요. 일부 종목은 20일 값이 더 짧은 기간일 수 있어요.','시가총액 상위 종목 위주라 작은 종목은 없을 수 있어요.','이 화면은 정보 제공용이며 특정 종목의 매수·매도 권유가 아니에요. 투자 판단과 책임은 이용자 본인에게 있어요.']);
 box.appendChild(g)}

/* ── 관리자 전용: 수급·테마 가져오기는 별도 메뉴로 옮겼어요(📊 시장수급 · 🏷 네이버테마) ── */
function flGoTab(h){cur=h;nav();load();try{history.replaceState(null,'','#'+h)}catch(e){}}
function flColInit(){var b=$('flCol');if(!b)return;b.innerHTML='';
 b.appendChild(el('b',null,'📥 수급·테마 가져오기는 별도 메뉴로 옮겼어요 (관리자만 보여요)'));
 b.appendChild(el('p','note','종목 수급 가져오기는 [📊 시장수급] 메뉴에서, 네이버 테마 가져오기는 [🏷 네이버테마] 메뉴에서 해요. 가져온 자료는 이 수급분석 화면의 순위·신호·테마별 수급에 그대로 쓰여요.'));
 var r=el('div','bar');r.appendChild(bt('📊 시장수급 메뉴로 이동','bt',function(){flGoTab('mk')}));r.appendChild(bt('🏷 네이버테마 메뉴로 이동','bt2',function(){flGoTab('th')}));b.appendChild(r)}

/* ── 관리자 전용 점검 카드(회원 화면에서는 숨김) ── */
function flDiagLoad(){var b=$('flAdm');if(!b)return;api('/admin/api/flow/diag').then(function(j){flDiagDraw(j)})}
function flDiagDraw(j){var b=$('flAdm');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'🛠 수급 자료 점검 (관리자만 보여요)'));if(!j||j.error){b.appendChild(el('p','note bad','점검 정보를 읽지 못했어요.'));return}
 var T=j.tables||{};function nn(v){return v==null?'표 없음':v.toLocaleString('ko-KR')+'행'}
 b.appendChild(el('p','note','investor_scan_cache '+nn(T.investor_scan_cache)+' · stock_price_cache '+nn(T.stock_price_cache)+' · stock_theme_map '+nn(T.stock_theme_map)+(j.themes?' (테마 '+j.themes+'개)':'')));
 if(j.meta&&j.meta.count!=null)b.appendChild(el('p','note','수급 종목 '+j.meta.count+'개 · 신선 '+j.meta.fresh+' · 오래됨 '+j.meta.stale+' · 기준일 없음 '+j.no_base+' · 시장 구분 없음 '+j.no_market+' · 오늘 수집 '+j.meta.today_cnt+'개 · 신선 기준일 '+j.meta.stale_cut+' 이후'));
 if(j.dist&&j.dist.length)b.appendChild(el('p','note','기준일 분포: '+j.dist.map(function(x){return x[0]+' ×'+x[1]}).join(' · ')));
 if(j.missing&&j.missing.length)b.appendChild(el('p','note bad','비어 있는 표: '+j.missing.join(', ')+' — 📊 시장수급 메뉴의 [종목 수급 가져오기]를 누르거나 📦 데이터 가져오기 메뉴에서 가져오세요.'));
 b.appendChild(bt('🔄 읽어 둔 자료 비우고 다시 읽기','bt2',function(){apiJ('/admin/api/flow/reload',{}).then(function(r){if(r.error){toast(r.error);return}FL.rk.data=null;FL.sg.data=null;FL.th.list=null;FL.th.mem=null;FL.st.data=null;flDiagDraw(r);flSumLoad();flShow();toast('다시 읽었어요')})}))}
"""


def register():
    C.register_menu({"id": MENU, "label": "수급분석", "icon": "💧", "public_path": "/m/flow", "admin_path": "/admin#fl",
                     "desc": "외국인·기관이 최근 1일·5일·20일 동안 어떤 종목을 순매수·순매도했는지 순위, 신호(쌍끌이·수급전환 등), 종목별·테마별로 정리해 보여 줘요.",
                     "access": "admin"})
    C.register_prompt("flow_ai", {
        "title": "수급분석 AI 프롬프트", "default": FLOW_DEFAULT, "required": ["{data_rows}"], "must_have": [],
        "vars": "{data_rows}=상위 20종목 수급 데이터(필수) · {side_lbl}=순매수/순매도 · {base_date}=수급 기준일 · {rank_lbl}=순위 기준 설명",
        "desc": "수급분석 화면의 [AI 프롬프트 만들기]가 AI에게 보내는 요청문. 매수·매도 권유를 하지 않도록 쓰는 것이 원칙이에요."})
    C.register_admin_tab("fl", "💧 수급분석", TAB_JS, "flLoad", menu=MENU)
    C.register_flow(MENU, "💧 수급분석", "① 수급 자료 가져오기(직접 시작)", [
        {"id": "ai", "label": "② AI 해설", "desc": "[🤖 AI 해설]을 시작하면 AI 요청문 창이 열려요. AI 답변을 복사해 돌아오면 저장되고 다음 단계로 이어져요(이미 저장한 해설이 있으면 건너뛰어요)."},
        {"id": "img", "label": "③ 수급 대시보드 이미지", "desc": "AI 단계가 끝나면 블로그용 수급 대시보드 이미지를 자동으로 그려요(저장은 [⚙ 저장 설정]의 자동/수동 설정을 따라요)."},
        {"id": "blog", "label": "④ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요."},
        {"id": "post", "label": "⑤ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요. 브라우저가 복사·새 창을 막으면 [📋 복사하고 블로그 열기]를 한 번 눌러 주세요."}])
    F = C.register_feature
    F(MENU, "sum", "수급 요약", "수급 기준일·신호별 종목 수·시장별 외국인/기관 합계", default="public", endpoints=["/admin/api/flow/summary"])
    F(MENU, "guide", "수급 읽는 법", "순매수·쌍끌이·수급전환 등 용어와 읽는 방법 해설", default="public", endpoints=[])
    F(MENU, "rank", "수급 순위 표", "투자자·기간·시장별 순매수/순매도 상위 종목", default="member", endpoints=["/admin/api/flow/rank", "/admin/api/flow/search"])
    F(MENU, "sig", "수급 신호 종목", "쌍끌이·수급전환·동반매도·지속 순매수·수급 급증 종목 목록과 수급 점수", default="member", endpoints=["/admin/api/flow/signals"])
    F(MENU, "stock", "종목별 수급 추이", "종목 하나의 1·5·20일 수급, 하루평균 그래프, 시장 내 순위", default="L2", endpoints=["/admin/api/flow/stock", "/admin/api/flow/search"])
    F(MENU, "theme", "테마별 수급", "테마별 외국인·기관 순매수 합계와 테마 안 종목 표", default="L2", endpoints=["/admin/api/flow/theme"])
    F(MENU, "ai", "AI 수급 해설", "상위 종목 수급 데이터로 AI 프롬프트를 만들고 답변을 붙여 보기(수동)", default="L2", endpoints=["/admin/api/flow/prompt"], kind="action")
    F(MENU, "exp", "표 내려받기·이미지", "지금 보는 표를 CSV 파일이나 PNG 이미지로 내려받기", default="L2", endpoints=[], kind="action")
    return bp
