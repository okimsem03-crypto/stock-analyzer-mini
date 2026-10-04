"""🎯 도전주 분석 (기능별 등급 공개 메뉴 · 법적 검토 전까지 기본은 관리자만) — 원본 프로그램 '도전주' 탭의 값 이식판.

원본은 시세 캐시(stock_price_cache)와 수급 캐시(investor_scan_cache)를 읽어 종목마다 '도전점수'를 매기고
(거래량 돌파·RSI 모멘텀·당일 등락·변동성 압축·수급 + 종합 기술점수 40%), 상위 30종목은 네트워크로 52주 위치·정배열을 보강한다.
웹 미니는 [📦 데이터 가져오기]로 옮겨 둔 표만 읽는다.
  · stock_price_cache     price·day_pct·rsi·score·vol_ratio·bb_squeeze·market·sector·cap_num  (필수. vol_ratio/bb_squeeze 열이 없으면 그 신호만 빠진다)
  · investor_scan_cache   외국인·기관 5일/20일 순매수 대금(원)  (선택: 없으면 수급 가감·신호가 모두 0)
  · stock_theme_map       종목 → 테마(사전순 첫 테마, 개인 테마(user)는 쓰지 않는다)  (선택)
  · delist_watch / delist_snapshots   상장폐지·거래정지 위험 종목은 목록에서 뺀다  (선택)
  · challenge_pick_track / challenge_saved_results   원본에서 가져온 저장 기록 + 웹에서 저장하는 기록(같은 표를 이어 쓴다)
표가 없거나 비어 있으면 오류 대신 "📦 데이터 가져오기 메뉴에서 ○○ 표를 가져오면 보여요" 안내를 돌려준다.

점수식·임계값은 원본 그대로(_challenge_scan_core). 원본과 다른 점(화면에 그렇게 표시):
  · 후보 목록은 캐시만으로 계산(네트워크 없음). 52주 위치·정배열 보강('정밀검증')은 관리자의 [정밀검증 스캔]에서만 한다.
  · 낙폭 우량주·빠른 스캔(실시간 FDR 조회)은 이식하지 않았다. 성과 기록에서는 낙폭 모드로 저장된 옛 기록(신호에 📉 포함)을 뺀다.
  · '승률·적중률' 대신 '저장일 가격 대비 현재 시세 캐시 가격의 등락'으로 표현한다(추천·권유로 읽히지 않게).

기능별 등급 공개(모두 기본 '관리자만' — 관리자가 [🎚 기능 공개]에서 하나씩 연다):
  list 후보 목록 · detail 점수·근거 상세 · saved 과거 결과 보관함 · track 성과 기록 · guide 기준 설명 · ai AI 해설 프롬프트 · exp 표/이미지 내보내기.
관리자 전용(어떤 기능에도 등록하지 않음 → 회원 화면에서는 404): 정밀검증 스캔(scan)·결과 저장(save)·보관함 삭제(saved/delete)·
  성과 기록 삭제(track/delete)·기준 저장(cfg)·점검(diag/reload).
한 주소가 여러 등급의 데이터를 섞는 곳(list·saved/get 은 '상세' 열, prompt 는 상세 값)은 gateway 요청일 때 잠긴 부분을 응답에서 뺀다.
추천형 문구는 쓰지 않는다 — 'OO 기준에 부합한 종목 목록(정보)' + 투자 권유 아님 안내.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from flask import Blueprint, request

from menu_ctx import C

bp = Blueprint("challenge", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "prompt_get", "_now_kst", "feature_ok", "setting_get", "setting_set",
               "get_price_data")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

MENU = "challenge"
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
KEY_RE = re.compile(r"^[0-9A-Za-z_\-]{1,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CACHE_TTL = 30
MAX_SAVE = 200
GRADES = ("S", "A", "B")
SIGS = ("고득점", "거래급증", "강한모멘텀", "눌림목", "과열주의⚠", "돌파임박", "쌍끌이", "수급유입", "수급전환", "신고가근접", "52주상단", "정배열")
DETAIL_KEYS = ("rsi", "vol_ratio", "score", "bb_squeeze", "pos52", "ma_align", "pct52", "f5", "i5", "f20", "i20", "theme", "per", "pbr", "cap")
NEED_MSG = {"stock_price_cache": "종목 시세 캐시(stock_price_cache)", "challenge_pick_track": "도전주 추적(challenge_pick_track)",
            "challenge_saved_results": "도전주 저장 결과(challenge_saved_results)"}
DEFAULT_CFG = {"markets": ["KOSPI", "KOSDAQ"], "min_score": 50, "limit": 120, "enrich_top": 30, "exclude_risk": 1}


# ══════════════════════════════════════════════════════════════
# 값 정리
# ══════════════════════════════════════════════════════════════
def _fl(x):
    try:
        v = float(x)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    except Exception:
        return None


def _n(x, d=0):
    v = _fl(x)
    return d if v is None else int(round(v))


def _s(x, n):
    return str(x if x is not None else "").replace("\x00", "").strip()[:n]


def _norm_market(m):
    """원본 _norm_market: 공백·—·N/A → '', 코스닥/KOSDAQ → KOSDAQ, 코스피/KOSPI → KOSPI, 코넥스/KONEX → KONEX, 그 외 대문자 원문."""
    s = str(m or "").strip()
    if s in ("", "—", "-", "N/A", "NONE", "None", "none", "n/a"):
        return ""
    u = s.upper()
    if "KOSDAQ" in u or "코스닥" in s:
        return "KOSDAQ"
    if "KOSPI" in u or "코스피" in s:
        return "KOSPI"
    if "KONEX" in u or "코넥스" in s:
        return "KONEX"
    return u[:12]


def _grade(ch):
    return "S" if ch >= 75 else ("A" if ch >= 62 else "B")


def _try(*sqls):
    """앞의 SQL부터 차례로 시도해 처음 성공한 (행들, 번호). 전부 실패(표·열 없음 등)하면 (None, -1)."""
    for i, s in enumerate(sqls):
        try:
            return (_dbx(s[0], s[1] if len(s) > 1 else (), fetch=True) or []), i
        except Exception:
            continue
    return None, -1


# ══════════════════════════════════════════════════════════════
# 도전점수 (원본 _challenge_scan_core 의 캐시 단계 그대로)
# ══════════════════════════════════════════════════════════════
def _calc(r, parts=None):
    """(도전점수 0~100 정수, 신호 목록). parts 리스트를 주면 (항목, 값 설명, 가감) 을 채운다."""
    sc = int(r["score"] or 0)
    rsi = float(r["rsi"] or 0)
    vr = float(r["vol"] or 0)
    dp = float(r["day_pct"] or 0)
    sq = int(r["sq"] or 0)
    iv = r.get("iv")
    f5, i5, f20, i20 = (iv["f5"], iv["i5"], iv["f20"], iv["i20"]) if iv else (0, 0, 0, 0)
    ch, sg = 0.0, []

    def P(k, v, p):
        if parts is not None:
            parts.append((k, v, p))

    a = min(100, sc) * 0.40
    ch += a
    P("종합 기술점수", f"{sc}점 × 0.4", a)
    if sc >= 70:
        sg.append("고득점")
    if vr >= 3.0:
        p = 18
        sg.append("거래급증")
    elif vr >= 2.0:
        p = 12
        sg.append("거래급증")
    elif vr >= 1.3:
        p = 6
    else:
        p = 0
    ch += p
    P("거래량(20일 평균 대비)", f"{vr:.2f}배", p)
    if 52 <= rsi <= 68:
        p = 12
        sg.append("강한모멘텀")
    elif 45 <= rsi < 52 or 68 < rsi <= 72:
        p = 6
    elif 40 <= rsi < 45:
        p = 3
        sg.append("눌림목")
    elif rsi >= 78:
        p = -10
        sg.append("과열주의⚠")
    else:
        p = 0
    ch += p
    P("RSI 모멘텀", f"RSI {rsi:.1f}", p)
    if 1 <= dp <= 8:
        p = 8
    elif 8 < dp <= 15:
        p = 4
    elif dp > 15:
        p = -4
    elif 0 <= dp < 1:
        p = 3
    elif -3 <= dp < 0:
        p = 2
    else:
        p = 0
    ch += p
    P("당일 등락", f"{dp:+.2f}%", p)
    p = 8 if sq == 1 else 0
    if p:
        sg.append("돌파임박")
    ch += p
    P("변동성 압축(볼린저밴드 수축)", "수축" if sq == 1 else "해당 없음", p)
    if f5 > 0 and i5 > 0:
        p = 12
        sg.append("쌍끌이")
    elif f5 > 0 or i5 > 0:
        p = 6
        sg.append("수급유입")
    elif f5 < 0 and i5 < 0:
        p = -10
    else:
        p = 0
    ch += p
    P("수급 5일(외국인·기관)", ("외국인 %s · 기관 %s" % ("+" if f5 > 0 else "-" if f5 < 0 else "0", "+" if i5 > 0 else "-" if i5 < 0 else "0")) if iv else "수급 자료 없음", p)
    p = 8 if (iv and ((f20 <= 0 and f5 > 0) or (i20 <= 0 and i5 > 0))) else 0
    if p:
        sg.append("수급전환")
    ch += p
    P("수급 전환(20일 매도·중립 → 5일 순매수)", "전환" if p else "해당 없음", p)
    return max(0, min(100, int(round(ch)))), sg


# ══════════════════════════════════════════════════════════════
# 가져온 표 읽기(30초 캐시) — 표·열이 없어도 오류 없이 빈 결과
# ══════════════════════════════════════════════════════════════
def _risk_set():
    """상장폐지·거래정지 위험으로 걸러진 종목: 웹 delist_watch(오늘추천과 같은 기준) + 원본 delist_snapshots 최신 1건의 danger/warn."""
    out = set()
    rs, _i = _try(("SELECT ticker FROM delist_watch WHERE (active=1 AND risk<>'warn' AND admin_state<>'excluded') OR admin_state='confirmed'",))
    for x in rs or []:
        t = str(x[0] or "").strip().upper()
        if TICKER_RE.match(t):
            out.add(t)
    rs, _i = _try(("SELECT items_json FROM delist_snapshots ORDER BY snap_date DESC LIMIT 1",))
    if rs:
        try:
            for it in json.loads(rs[0][0] or "[]"):
                if isinstance(it, dict) and str(it.get("status", "")) in ("danger", "warn"):
                    t = str(it.get("ticker", "")).strip().upper()
                    if TICKER_RE.match(t):
                        out.add(t)
        except Exception:
            pass
    return out


def _build():
    out = {"rows": [], "by": {}, "risk": set(), "tables": {}, "missing": [], "meta": {}}
    pri, qi = _try(
        ("SELECT ticker,name,market,sector,price,day_pct,per,pbr,cap_num,rsi,score,COALESCE(vol_ratio,0),COALESCE(bb_squeeze,0),updated_at FROM stock_price_cache WHERE price IS NOT NULL",),
        ("SELECT ticker,name,market,sector,price,day_pct,per,pbr,cap_num,rsi,score,0,0,updated_at FROM stock_price_cache WHERE price IS NOT NULL",),
        ("SELECT ticker,name,market,'',price,day_pct,'','',cap_num,rsi,score,0,0,'' FROM stock_price_cache WHERE price IS NOT NULL",),
        ("SELECT ticker,name,market,'',price,day_pct,'','',0,rsi,score,0,0,'' FROM stock_price_cache WHERE price IS NOT NULL",))
    out["tables"]["stock_price_cache"] = None if pri is None else len(pri)
    if not pri:
        out["missing"].append("stock_price_cache")
        return out
    inv, _i = _try(("SELECT ticker,foreign_5,inst_5,foreign_20,inst_20,scanned_at FROM investor_scan_cache",),
                   ("SELECT ticker,foreign_5,inst_5,foreign_20,inst_20,'' FROM investor_scan_cache",))
    out["tables"]["investor_scan_cache"] = None if inv is None else len(inv)
    th, _i = _try(("SELECT ticker,MIN(theme) FROM stock_theme_map WHERE theme_type IN ('naver','system') GROUP BY ticker",),
                  ("SELECT ticker,MIN(theme) FROM stock_theme_map GROUP BY ticker",))
    out["tables"]["stock_theme_map"] = None if th is None else len(th)
    ivm, inv_last = {}, ""
    for x in inv or []:
        t = str(x[0] or "").strip().upper()
        if TICKER_RE.match(t):
            ivm[t] = {"f5": _fl(x[1]) or 0.0, "i5": _fl(x[2]) or 0.0, "f20": _fl(x[3]) or 0.0, "i20": _fl(x[4]) or 0.0}
            sa = str(x[5] or "")[:16]
            if sa > inv_last:
                inv_last = sa
    thm = {}
    for x in th or []:
        t = str(x[0] or "").strip().upper()
        nm = _s(x[1], 40)
        if TICKER_RE.match(t) and nm:
            thm[t] = nm
    rows, by, upd = [], {}, ""
    for x in pri:
        t = str(x[0] or "").strip().upper()
        price = _fl(x[4])
        if not TICKER_RE.match(t) or price is None:
            continue
        r = {"ticker": t, "name": _s(x[1], 40) or t, "mk": _norm_market(x[2]), "sector": _s(x[3], 40), "price": int(round(price)), "day_pct": _fl(x[5]),
             "per": _s(x[6], 12), "pbr": _s(x[7], 12), "cap": _n(x[8]), "rsi": _fl(x[9]), "score": (None if _fl(x[10]) is None else int(round(_fl(x[10])))),
             "vol": _fl(x[11]) or 0.0, "sq": 1 if (_fl(x[12]) or 0) >= 1 else 0, "theme": thm.get(t, ""), "iv": ivm.get(t)}
        r["ch"], r["sg"] = _calc(r)
        r["nsig"] = len(r["sg"])
        u = str(x[13] or "")[:10]
        if u > upd:
            upd = u
        if t in by:
            rows[rows.index(by[t])] = r
        else:
            rows.append(r)
        by[t] = r
    out["rows"], out["by"] = rows, by
    out["risk"] = _risk_set()
    out["meta"] = {"universe": len(rows), "price_asof": upd, "inv_last": inv_last, "has_vol": qi == 0, "has_inv": bool(ivm), "has_theme": bool(thm), "risk_n": len(out["risk"])}
    if not rows:
        out["missing"].append("stock_price_cache")
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
    need = d.get("missing") or ["stock_price_cache"]
    return _admin_json({"ok": True, "empty": True, "need": need,
                        "msg": "📦 데이터 가져오기 메뉴에서 ‘" + "’·‘".join(NEED_MSG.get(x, x) for x in need) + "’ 표를 가져오면 도전주 자료가 보여요."})


# ══════════════════════════════════════════════════════════════
# 설정(관리자가 기준을 저장) · 요청 값 검사
# ══════════════════════════════════════════════════════════════
def _clean_cfg(d):
    d = d if isinstance(d, dict) else {}
    mk = [m for m in (d.get("markets") or DEFAULT_CFG["markets"]) if m in ("KOSPI", "KOSDAQ")] or list(DEFAULT_CFG["markets"])

    def iv(k, lo, hi):
        try:
            return int(max(lo, min(hi, int(float(d.get(k, DEFAULT_CFG[k]))))))
        except Exception:
            return DEFAULT_CFG[k]
    ms = iv("min_score", 40, 80)
    return {"markets": list(dict.fromkeys(mk)), "min_score": ms - ms % 5, "limit": iv("limit", 10, 200), "enrich_top": iv("enrich_top", 0, 30),
            "exclude_risk": 1 if str(d.get("exclude_risk", 1)).lower() not in ("0", "false", "no", "") else 0}


def _valid_cfg(k, v):
    try:
        d = json.loads(v) if isinstance(v, str) else v
    except Exception:
        return None
    return json.dumps(_clean_cfg(d), ensure_ascii=False) if isinstance(d, dict) else None


def get_cfg():
    try:
        return _clean_cfg(json.loads(setting_get("challenge_cfg") or "{}"))
    except Exception:
        return dict(DEFAULT_CFG)


def _iarg(name, lo, hi, default):
    try:
        v = int(str(request.args.get(name) or "").strip())
    except Exception:
        return default
    return max(lo, min(hi, v))


def _markets_from(v, default):
    ms = [x for x in str(v or "").upper().replace(" ", "").split(",") if x in ("KOSPI", "KOSDAQ")]
    return list(dict.fromkeys(ms)) or list(default)


def _locked_detail():
    return bool(request.environ.get("mini.gateway")) and not feature_ok(MENU, "detail")


# ══════════════════════════════════════════════════════════════
# 후보 고르기 · 응답 항목
# ══════════════════════════════════════════════════════════════
def _select(d, markets, min_score, limit, exclude_risk):
    """원본 2-3~2-6: 위험 종목 제외 → 시장 필터(시장 미상은 둘 다 선택일 때만) → 점수 컷 → (-점수, -신호 수, -기술점수) 정렬 → 상한."""
    mset = set(markets)
    out = []
    for r in d["rows"]:
        if exclude_risk and r["ticker"] in d["risk"]:
            continue
        mk = r["mk"]
        if mk in ("KOSPI", "KOSDAQ", "KONEX"):
            if mk not in mset:
                continue
        elif not ("KOSPI" in mset and "KOSDAQ" in mset):
            continue
        if r["ch"] < min_score:
            continue
        out.append(r)
    out.sort(key=lambda x: (-x["ch"], -x["nsig"], -(x["score"] or 0), x["ticker"]))
    return out[:limit], len(out)


def _pub(r):
    f = r["iv"] or {}
    return {"ticker": r["ticker"], "name": r["name"], "market": r["mk"] if r["mk"] in ("KOSPI", "KOSDAQ") else "", "sector": r["sector"], "price": r["price"],
            "day_pct": r["day_pct"], "ch_score": r["ch"], "grade": _grade(r["ch"]), "signals": list(r["sg"]), "sig_count": r["nsig"],
            "rsi": r["rsi"], "vol_ratio": round(r["vol"], 2), "score": r["score"], "bb_squeeze": r["sq"], "pos52": None, "ma_align": "", "pct52": None,
            "f5": f.get("f5") if f else None, "i5": f.get("i5") if f else None, "f20": f.get("f20") if f else None, "i20": f.get("i20") if f else None,
            "theme": r["theme"], "per": r["per"], "pbr": r["pbr"], "cap": r["cap"]}


def _strip(it):
    for k in DETAIL_KEYS:
        it.pop(k, None)
    return it


def _clean_item(x):
    """저장·불러온 항목을 화이트리스트로 정리한다(알 수 없는 열·그래프 데이터는 버림)."""
    if not isinstance(x, dict):
        return None
    t = str(x.get("ticker", "")).strip().upper()
    if not TICKER_RE.match(t):
        return None
    mk = _norm_market(x.get("market"))
    sg = [_s(s, 24) for s in (x.get("signals") or []) if isinstance(s, str) and s.strip()][:15] if isinstance(x.get("signals"), list) else []
    ch = max(0, min(100, _n(x.get("ch_score"))))
    g = _s(x.get("grade"), 1).upper()
    pr = _fl(x.get("price"))
    it = {"ticker": t, "name": _s(x.get("name"), 40) or t, "market": mk if mk in ("KOSPI", "KOSDAQ") else "", "sector": _s(x.get("sector"), 40),
          "price": None if pr is None else int(round(pr)), "day_pct": _fl(x.get("day_pct")), "ch_score": ch, "grade": g if g in GRADES else _grade(ch), "signals": sg,
          "sig_count": max(0, min(30, _n(x.get("sig_count"), len(sg)))),
          "rsi": _fl(x.get("rsi")), "vol_ratio": _fl(x.get("vol_ratio")), "score": (None if _fl(x.get("score")) is None else int(round(_fl(x.get("score"))))),
          "bb_squeeze": 1 if (_fl(x.get("bb_squeeze")) or 0) >= 1 else 0, "pos52": _fl(x.get("pos52")), "ma_align": _s(x.get("ma_align"), 10), "pct52": _fl(x.get("pct52")),
          "f5": _fl(x.get("f5")), "i5": _fl(x.get("i5")), "f20": _fl(x.get("f20")), "i20": _fl(x.get("i20")),
          "theme": _s(x.get("theme"), 40), "per": _s(x.get("per"), 12), "pbr": _s(x.get("pbr"), 12), "cap": _n(x.get("cap", x.get("cap_num")))}
    return it


def _grade_cnt(items):
    return {g: sum(1 for i in items if i["grade"] == g) for g in GRADES}


def _list_payload(d, items, matched, q, extra=None):
    locked = []
    if _locked_detail():
        items = [_strip(i) for i in items]
        locked.append("detail")
    out = {"ok": True, "items": items, "matched": matched, "grade_cnt": _grade_cnt(items), "q": q, "cfg": get_cfg(),
           "meta": {k: d["meta"][k] for k in ("universe", "price_asof", "inv_last", "has_vol", "has_inv", "has_theme", "risk_n")}}
    if locked:
        out["locked"] = locked
    if extra:
        out.update(extra)
    return out


# ══════════════════════════════════════════════════════════════
# API — 기능마다 주소가 따로다(회원 화면은 등록된 주소만 열림)
# ══════════════════════════════════════════════════════════════
@bp.route("/admin/api/challenge/list", methods=["GET"])
def api_list():
    """[list] 기준에 부합한 종목 목록(캐시만 사용). '상세' 열은 detail 기능이 잠겨 있으면 뺀다."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    cfg = get_cfg()
    markets = _markets_from(request.args.get("markets"), cfg["markets"])
    ms = _iarg("min_score", 40, 80, cfg["min_score"])
    top = _iarg("top", 5, 200, cfg["limit"])
    risk = cfg["exclude_risk"]
    sel, matched = _select(d, markets, ms, min(top, 200), risk)
    q = {"markets": markets, "min_score": ms, "top": top, "exclude_risk": risk}
    return _admin_json(_list_payload(d, [_pub(r) for r in sel], matched, q))


def _enrich(items, k):
    """원본 2-6 정밀검증: 상위 k개에 get_price_data 로 52주 위치·정배열을 붙이고 점수를 올린 뒤 다시 정렬한다. 성공한 종목 수를 돌려준다."""
    if k <= 0 or not items:
        return 0
    ok = 0
    ex = ThreadPoolExecutor(max_workers=10)
    futs = {ex.submit(get_price_data, it["ticker"]): it for it in items[:k]}
    try:
        for f in as_completed(futs, timeout=25):
            it = futs[f]
            try:
                p = f.result()
            except Exception:
                continue
            if not p or not isinstance(p, dict):
                continue
            ok += 1
            it["pos52"], it["ma_align"], it["pct52"] = _fl(p.get("pos52")), _s(p.get("ma_align"), 10), _fl(p.get("pct52"))
            bonus = 0
            if (it["pos52"] or 0) >= 85:
                bonus += 5
                it["signals"].append("신고가근접")
            elif (it["pos52"] or 0) >= 70:
                it["signals"].append("52주상단")
            if "정배열" in it["ma_align"]:
                bonus += 4
                it["signals"].append("정배열")
            if bonus:
                it["ch_score"] = max(0, min(100, it["ch_score"] + bonus))
                it["grade"] = _grade(it["ch_score"])
            it["sig_count"] = len(it["signals"])
    except Exception:
        pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    items.sort(key=lambda x: (-x["ch_score"], -x["sig_count"], -(x["score"] or 0), x["ticker"]))
    return ok


@bp.route("/admin/api/challenge/scan", methods=["POST"])
def api_scan():
    """관리자 전용 — 캐시 후보에 '정밀검증'(52주 위치·정배열 네트워크 조회)을 더해 돌려준다. 저장하지는 않는다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _load(force=True)
    if not d["rows"]:
        return _empty_resp(d)
    b = _json_body() or {}
    cfg = get_cfg()
    markets = _markets_from(",".join(b.get("markets") or []) if isinstance(b.get("markets"), list) else b.get("markets"), cfg["markets"])
    try:
        ms = max(40, min(80, int(b.get("min_score", cfg["min_score"]))))
    except Exception:
        ms = cfg["min_score"]
    try:
        top = max(5, min(200, int(b.get("top", cfg["limit"]))))
    except Exception:
        top = cfg["limit"]
    enrich = str(b.get("enrich", "1")).lower() not in ("0", "false", "no", "")
    sel, matched = _select(d, markets, ms, top, cfg["exclude_risk"])
    items = [_pub(r) for r in sel]
    got = _enrich(items, cfg["enrich_top"]) if enrich else 0
    _alog("challenge_scan", json.dumps({"markets": markets, "min": ms, "n": len(items), "enriched": got}, ensure_ascii=False))
    q = {"markets": markets, "min_score": ms, "top": top, "exclude_risk": cfg["exclude_risk"]}
    return _admin_json(_list_payload(d, items, matched, q, {"scan": True, "enriched": got, "enrich_asked": min(cfg["enrich_top"], len(items)) if enrich else 0}))


@bp.route("/admin/api/challenge/explain", methods=["GET"])
def api_explain():
    """[detail] 종목 하나의 점수 구성(항목별 가감)."""
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
        return _admin_json({"error": "시세 캐시에 이 종목이 없어요."}, 404)
    parts = []
    ch, _sg = _calc(r, parts)
    return _admin_json({"ok": True, "ticker": t, "name": r["name"], "total": ch, "grade": _grade(ch), "excluded": t in d["risk"],
                        "parts": [{"k": k, "v": v, "p": round(p, 1)} for k, v, p in parts], "cut": {"S": 75, "A": 62}})


# ── 보관함(저장된 스냅샷) ──
def _json_items(s):
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


@bp.route("/admin/api/challenge/saved", methods=["GET"])
def api_saved():
    """[saved] 저장 목록(최근 50개)."""
    deny = _admin_deny()
    if deny:
        return deny
    try:
        rows = _dbx("SELECT save_key,label,saved_at,items_json FROM challenge_saved_results ORDER BY saved_at DESC LIMIT 50", fetch=True) or []
    except Exception:
        return _admin_json({"ok": True, "empty": True, "need": ["challenge_saved_results"],
                            "msg": "📦 데이터 가져오기 메뉴에서 ‘" + NEED_MSG["challenge_saved_results"] + "’ 표를 가져오면 과거 결과가 보여요. (웹에서 저장한 결과는 바로 쌓여요)"})
    out = []
    for r in rows:
        its = _json_items(r[3])
        out.append({"key": str(r[0]), "label": _s(r[1], 80) or str(r[2] or "")[:16], "saved_at": str(r[2] or "")[:19], "cnt": len(its),
                    "oversold": any(isinstance(i, dict) and "drawdown" in i for i in its[:3])})
    return _admin_json({"ok": True, "items": out})


@bp.route("/admin/api/challenge/saved/get", methods=["GET"])
def api_saved_get():
    """[saved] 저장된 스냅샷 하나의 종목들. 저장 당시 값이며, 상세 열은 detail 이 잠겨 있으면 뺀다."""
    deny = _admin_deny()
    if deny:
        return deny
    k = (request.args.get("key") or "").strip()
    if not KEY_RE.match(k):
        return _admin_json({"error": "저장 번호가 올바르지 않아요."}, 400)
    try:
        rows = _dbx("SELECT save_key,label,saved_at,items_json FROM challenge_saved_results WHERE save_key=?", (k,), fetch=True) or []
    except Exception:
        rows = []
    if not rows:
        return _admin_json({"error": "저장된 결과를 찾지 못했어요."}, 404)
    raw = _json_items(rows[0][3])
    items = [i for i in (_clean_item(x) for x in raw[:MAX_SAVE]) if i]
    locked = []
    if _locked_detail():
        items = [_strip(i) for i in items]
        locked.append("detail")
    out = {"ok": True, "key": str(rows[0][0]), "label": _s(rows[0][1], 80), "saved_at": str(rows[0][2] or "")[:19], "items": items, "grade_cnt": _grade_cnt(items),
           "oversold": any(isinstance(i, dict) and "drawdown" in i for i in raw[:3])}
    if locked:
        out["locked"] = locked
    return _admin_json(out)


@bp.route("/admin/api/challenge/save", methods=["POST"])
def api_save():
    """관리자 전용 — 화면의 결과를 스냅샷(보관함)과 성과 기록(같은 날 같은 종목은 처음 1건만)으로 저장한다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    try:
        C._ensure_v135_tables()                 # 저장 표가 아직 없으면 만든다(표 만들기 함수 모음은 본체가 관리)
    except Exception:
        pass
    b = _json_body() or {}
    raw = b.get("items")
    if not isinstance(raw, list) or not raw:
        return _admin_json({"error": "저장할 결과가 없어요. 먼저 조회하거나 스캔하세요."}, 400)
    items = [i for i in (_clean_item(x) for x in raw[:MAX_SAVE]) if i]
    if not items:
        return _admin_json({"error": "저장할 수 있는 종목이 없어요."}, 400)
    now = _now_kst()
    today, stamp = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S")
    have = set()
    try:
        have = {str(r[0]).upper() for r in (_dbx("SELECT ticker FROM challenge_pick_track WHERE pick_date=?", (today,), fetch=True) or [])}
    except Exception:
        pass
    new = tried = 0
    for it in items:
        if not it["price"]:
            continue
        tried += 1
        if it["ticker"] in have:
            continue
        args = (today, it["ticker"], it["name"], it["market"], it["theme"], ",".join(it["signals"]), it["sig_count"], it["ch_score"], it["grade"], float(it["price"]))
        try:
            try:
                _dbx("INSERT INTO challenge_pick_track(pick_date,ticker,name,market,theme,signals,sig_count,ch_score,grade,pick_price,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     args + (stamp,))
            except Exception:
                _dbx("INSERT INTO challenge_pick_track(pick_date,ticker,name,market,theme,signals,sig_count,ch_score,grade,pick_price) VALUES(?,?,?,?,?,?,?,?,?,?)", args)
            have.add(it["ticker"])
            new += 1
        except Exception:
            pass
    key = now.strftime("%Y%m%d_%H%M%S")
    label = _s(b.get("label"), 60) or (now.strftime("%Y-%m-%d %H:%M") + f" 도전주 ({len(items)}종목)")
    try:
        _dbx("DELETE FROM challenge_saved_results WHERE save_key=?", (key,))
        _dbx("INSERT INTO challenge_saved_results(save_key,label,items_json,saved_at) VALUES(?,?,?,?)", (key, label, json.dumps(items, ensure_ascii=False), stamp))
    except Exception as e:
        return _admin_json({"error": f"저장하지 못했어요: {type(e).__name__}", "saved": 0}, 500)
    _alog("challenge_save", f"{key} n={len(items)} new={new}")
    return _admin_json({"ok": True, "saved": tried, "new": new, "date": today, "key": key, "label": label})


@bp.route("/admin/api/challenge/saved/delete", methods=["POST"])
def api_saved_delete():
    """관리자 전용 — 보관함 스냅샷 하나를 지운다(성과 기록은 그대로)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    k = str((_json_body() or {}).get("key", "")).strip()
    if not KEY_RE.match(k):
        return _admin_json({"error": "저장 번호가 올바르지 않아요."}, 400)
    try:
        _dbx("DELETE FROM challenge_saved_results WHERE save_key=?", (k,))
    except Exception:
        return _admin_json({"error": "지우지 못했어요(표가 없어요)."}, 404)
    _alog("challenge_saved_delete", k)
    return _admin_json({"ok": True})


# ── 성과 기록(저장일 가격 대비 현재 시세 캐시 가격) ──
def _bucket():
    return {"cnt": 0, "up": 0, "sum": 0.0}


def _add(b, ret):
    b["cnt"] += 1
    b["sum"] += ret
    if ret > 0:
        b["up"] += 1


def _fin(b):
    return {"cnt": b["cnt"], "up": b["up"], "up_rate": round(b["up"] / b["cnt"] * 100, 1) if b["cnt"] else 0, "avg_ret": round(b["sum"] / b["cnt"], 2) if b["cnt"] else 0}


def _band(ch):
    return "75점 이상(S권)" if ch >= 75 else "62~74점(A권)" if ch >= 62 else "50~61점(B권)" if ch >= 50 else "50점 미만"


@bp.route("/admin/api/challenge/track", methods=["GET"])
def api_track():
    """[track] 저장한 기록의 이후 등락. 오늘 저장한 건은 평가를 미룬다(내일부터). 이 표의 값은 이용 결과·수익이 아니다."""
    deny = _admin_deny()
    if deny:
        return deny
    days = _iarg("days", 0, 365, 30)
    limit = _iarg("limit", 20, 300, 60)
    now = _now_kst()
    today = now.strftime("%Y-%m-%d")
    cond, args = "t.pick_date < ?", [today]
    if days:
        cond += " AND t.pick_date >= ?"
        args.append((now - timedelta(days=days)).strftime("%Y-%m-%d"))
    rows, _i = _try(
        (f"SELECT t.id,t.pick_date,t.ticker,t.name,t.signals,t.sig_count,t.ch_score,t.grade,t.pick_price,s.price FROM challenge_pick_track t LEFT JOIN stock_price_cache s ON s.ticker=t.ticker WHERE {cond}", tuple(args)),
        (f"SELECT t.id,t.pick_date,t.ticker,t.name,t.signals,t.sig_count,t.ch_score,t.grade,t.pick_price,NULL FROM challenge_pick_track t WHERE {cond}", tuple(args)))
    if rows is None:
        return _admin_json({"ok": True, "empty": True, "need": ["challenge_pick_track"],
                            "msg": "📦 데이터 가져오기 메뉴에서 ‘" + NEED_MSG["challenge_pick_track"] + "’ 표를 가져오면 성과 기록이 보여요. (웹에서 결과를 저장하면 바로 쌓여요)"})
    tot, bg, bs, bsig, bcnt, bdate, recent = _bucket(), {}, {}, {}, {}, {}, []
    skipped_os = 0
    for r in rows:
        sig = str(r[4] or "")
        if "📉" in sig:
            skipped_os += 1
            continue
        pp, cp = _fl(r[8]), _fl(r[9])
        if not pp or not cp or pp <= 0 or cp <= 0:
            continue
        ret = (cp - pp) / pp * 100.0
        sl = [x.strip() for x in sig.split(",") if x.strip()][:15]
        ch, g = _n(r[6]), _s(r[7], 1) or "-"
        _add(tot, ret)
        _add(bg.setdefault(g, _bucket()), ret)
        _add(bs.setdefault(_band(ch), _bucket()), ret)
        _add(bcnt.setdefault(str(_n(r[5])), _bucket()), ret)
        _add(bdate.setdefault(str(r[1])[:10], _bucket()), ret)
        for s in sl:
            _add(bsig.setdefault(s[:24], _bucket()), ret)
        recent.append({"id": _n(r[0]), "date": str(r[1])[:10], "ticker": str(r[2]).upper(), "name": _s(r[3], 40), "signals": sl, "ch_score": ch, "grade": g,
                       "pick_price": pp, "cur_price": cp, "ret": round(ret, 2), "up": ret > 0})
    recent.sort(key=lambda x: (x["date"], x["ch_score"]), reverse=True)
    try:
        tc = _dbx("SELECT COUNT(*) FROM challenge_pick_track WHERE pick_date=?", (today,), fetch=True)
        today_cnt = _n(tc[0][0]) if tc else 0
        tr = _dbx("SELECT COUNT(*) FROM challenge_pick_track", fetch=True)
        total_rec = _n(tr[0][0]) if tr else 0
    except Exception:
        today_cnt = total_rec = 0
    dates = sorted(bdate.keys(), reverse=True)[:30]
    return _admin_json({"ok": True, "total": _fin(tot), "by_grade": {k: _fin(v) for k, v in bg.items()}, "by_score": {k: _fin(v) for k, v in bs.items()},
                        "by_signal": {k: _fin(v) for k, v in bsig.items()}, "by_sig_count": {k: _fin(v) for k, v in bcnt.items()},
                        "by_date": {k: _fin(bdate[k]) for k in dates}, "recent": recent[:limit], "today_cnt": today_cnt, "total_records": total_rec,
                        "skipped_oversold": skipped_os, "days": days, "limit": limit})


@bp.route("/admin/api/challenge/track/delete", methods=["POST"])
def api_track_delete():
    """관리자 전용 — 성과 기록을 번호(ids) 또는 저장일(pick_date)로 지운다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    ids = b.get("ids")
    pd = str(b.get("pick_date", "")).strip()
    try:
        if isinstance(ids, list) and ids:
            ids = [int(x) for x in ids[:500] if str(x).lstrip("-").isdigit()]
            if not ids:
                return _admin_json({"error": "번호가 올바르지 않아요."}, 400)
            n = 0
            for i in ids:
                _dbx("DELETE FROM challenge_pick_track WHERE id=?", (i,))
                n += 1
            _alog("challenge_track_delete", f"ids={len(ids)}")
            return _admin_json({"ok": True, "deleted": n})
        if DATE_RE.match(pd):
            c = _dbx("SELECT COUNT(*) FROM challenge_pick_track WHERE pick_date=?", (pd,), fetch=True)
            _dbx("DELETE FROM challenge_pick_track WHERE pick_date=?", (pd,))
            _alog("challenge_track_delete", pd)
            return _admin_json({"ok": True, "deleted": _n(c[0][0]) if c else 0})
    except Exception:
        return _admin_json({"error": "지우지 못했어요(표가 없어요)."}, 404)
    return _admin_json({"error": "ids 또는 pick_date(YYYY-MM-DD)가 필요해요."}, 400)


# ══════════════════════════════════════════════════════════════
# AI 프롬프트(수동 AI 도우미용 — 서버가 AI를 부르지 않는다)
# ══════════════════════════════════════════════════════════════
CH_DEFAULT = """아래는 오늘({today}) 국내 증시({market_label})에서 '도전 점수' 기준(거래량 증가·수급·RSI 모멘텀·변동성 압축·52주 위치 등)에 부합한 종목 {count}종목의 데이터입니다.
종목은 도전 점수 순으로 정렬되어 있고, 도전 점수는 '기준에 얼마나 많이 부합하는가'를 보여 주는 값이지 사거나 팔아야 한다는 뜻이 아닙니다.

[기준 부합 종목 목록]
{items_text}

[작성 지침 — 반드시 준수]
- 국내 주식 초보 투자자를 위한 정보 정리 글입니다. 위 데이터에 없는 숫자나 사실은 지어내지 마세요.
- 특정 종목의 매수·매도를 권하거나 목표가·수익률을 단정하지 말고, "~로 보입니다", "~할 가능성이 있습니다" 같은 관찰 표현을 쓰세요.
- 마크다운으로 작성하세요. 최상위 섹션은 '## 제목', 하위 항목은 '### 제목', 강조는 **굵게**, 목록은 '- '을 사용합니다. <br> 같은 HTML 태그는 쓰지 마세요.
- 신호(거래급증·쌍끌이·수급유입·정배열·52주 위치·돌파임박 등)가 무엇을 뜻하는지 데이터에 있는 항목만 인용해 쉬운 말로 설명하세요.
- 과열주의⚠ 신호가 있는 종목은 반드시 단기 과열 위험을 함께 언급하세요.

[구성 — 순서대로 작성]
## 🎯 기준 부합 종목의 공통 특징
- 목록 전체의 공통점(업종·수급 주체·기술적 모습)을 3~4줄로 요약하세요.

## 🔍 특징이 두드러진 종목
목록에서 3~5개를 골라 각각 아래 형식으로 정리하세요.
- **[종목명(코드)]** — 데이터에서 읽히는 특징 1~2줄(해당하는 항목만 인용)
- 함께 확인할 점: 과열·매물·공시·실적 등 숫자만으로 알 수 없는 부분 1줄

## 📊 도전 점수와 신호 읽는 법
- 도전 점수가 무엇을 합산한 값인지, 신호 배지가 무엇을 뜻하는지 초보자도 이해하도록 2~3줄로 설명하세요.

## ⚠ 유의사항
이 글은 공개된 시세·수급 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다. 점수가 높아도 이후 주가는 오를 수도 내릴 수도 있고 원금 손실이 생길 수 있습니다. 투자 판단과 책임은 투자자 본인에게 있습니다.
"""


def _items_text(rows, with_detail):
    lines = []
    for r in rows:
        it = _pub(r)
        seg = [f"- [{it['grade']}·{it['ch_score']}점] {it['name']}({it['ticker']}) {it['market']} {it['sector']}".rstrip()]
        pc = it["day_pct"]
        seg.append(f"현재가 {it['price']:,}원 ({pc:+.1f}%)" if pc is not None else f"현재가 {it['price']:,}원")
        if with_detail:
            seg.append(f"RSI {it['rsi'] if it['rsi'] is not None else '-'} 거래량배수 {it['vol_ratio']}배 기술점수 {it['score'] if it['score'] is not None else '-'}")
        seg.append("신호: " + (", ".join(it["signals"]) or "—"))
        lines.append(" | ".join(seg))
    return "\n".join(lines)


@bp.route("/admin/api/challenge/prompt", methods=["GET"])
def api_prompt():
    """[ai] 선택한 종목(없으면 목록 상위)을 한 줄씩 직렬화해 프롬프트를 만든다. 상세 값은 detail 이 잠겨 있으면 뺀다."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    cfg = get_cfg()
    tks = [t for t in (x.strip().upper() for x in (request.args.get("tickers") or "").split(",")) if TICKER_RE.match(t)][:30]
    if tks:
        rows = [d["by"][t] for t in dict.fromkeys(tks) if t in d["by"] and not (cfg["exclude_risk"] and t in d["risk"])]
    else:
        markets = _markets_from(request.args.get("markets"), cfg["markets"])
        rows, _m = _select(d, markets, _iarg("min_score", 40, 80, cfg["min_score"]), _iarg("top", 3, 30, 20), cfg["exclude_risk"])
    if not rows:
        return _admin_json({"error": "조건에 맞는 종목이 없어서 프롬프트를 만들 수 없어요."}, 400)
    have_mk = {r["mk"] for r in rows}
    mks = [x for x in ("KOSPI", "KOSDAQ") if x in have_mk]
    label = "·".join("코스피" if m == "KOSPI" else "코스닥" for m in mks) or "국내증시"
    body = prompt_get("challenge_ai") or CH_DEFAULT
    for k, v in (("{items_text}", _items_text(rows, not _locked_detail())), ("{today}", _now_kst().strftime("%Y-%m-%d")), ("{market_label}", label), ("{count}", str(len(rows)))):
        body = body.replace(k, v)
    return _admin_json({"ok": True, "prompt": body, "n": len(rows), "label": f"{label} {len(rows)}종목"})


# ══════════════════════════════════════════════════════════════
# 관리자 전용 — 기준 저장 · 점검 (어떤 기능에도 등록하지 않음 → 회원 화면에서는 404)
# ══════════════════════════════════════════════════════════════
@bp.route("/admin/api/challenge/cfg", methods=["POST"])
def api_cfg():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    cfg = _clean_cfg(_json_body() or {})
    setting_set("challenge_cfg", json.dumps(cfg, ensure_ascii=False))
    _alog("challenge_cfg", json.dumps(cfg, ensure_ascii=False))
    return _admin_json({"ok": True, "cfg": cfg})


def _diag(d):
    rows = d["rows"]
    return {"ok": True, "tables": d["tables"], "meta": d["meta"], "missing": d["missing"], "cfg": get_cfg(),
            "grades": {g: sum(1 for r in rows if _grade(r["ch"]) == g and r["ch"] >= 50) for g in GRADES}, "no_market": sum(1 for r in rows if r["mk"] not in ("KOSPI", "KOSDAQ")),
            "no_theme_cache": not d["meta"].get("has_theme", False) if d["meta"] else True, "cache_age": int(time.time() - _CACHE["at"]) if _CACHE["d"] is not None else None}


@bp.route("/admin/api/challenge/diag", methods=["GET"])
def api_diag():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_diag(_load()))


@bp.route("/admin/api/challenge/reload", methods=["POST"])
def api_reload():
    """읽어 둔 표를 비우고 다시 읽는다(데이터를 새로 가져온 직후 바로 보고 싶을 때)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _load(force=True)
    _alog("challenge_reload", f"rows={len(d['rows'])}")
    return _admin_json(_diag(d))


def _ensure_tables(c, use_pg):
    """원본과 같은 모양의 저장 표 — 가져오기로 같은 이름의 표가 들어오면 그 표로 바뀌고, 이 코드는 두 모양 모두에서 동작한다."""
    pk = "SERIAL PRIMARY KEY" if use_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    c.execute(f"CREATE TABLE IF NOT EXISTS challenge_saved_results(id {pk}, save_key TEXT NOT NULL UNIQUE, label TEXT DEFAULT '', items_json TEXT DEFAULT '[]', saved_at TEXT DEFAULT '')")
    c.execute(f"CREATE TABLE IF NOT EXISTS challenge_pick_track(id {pk}, pick_date TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT, market TEXT, theme TEXT, signals TEXT, "
              f"sig_count INTEGER DEFAULT 0, ch_score INTEGER DEFAULT 0, grade TEXT DEFAULT '', pick_price {real}, created_at TEXT DEFAULT '', UNIQUE(pick_date, ticker))")


# ══════════════════════════════════════════════════════════════
# 화면(관리자 탭 = 이용자 /m/challenge 와 같은 JS)
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var CH={sec:'list',css:false,cfg:null,tbl:null,ex:{},open:{},
 ld:{market:'all',min:'50',top:'120',view:(window.innerWidth<=560?'card':'table'),data:null,seq:0,sort:{col:'ch_score',asc:false},inited:false,sel:{},enrich:true,busy:false,refs:{}},
 sv:{list:null,cur:null,seq:0},tr:{days:'30',limit:'60',data:null,seq:0},ai:{text:''}};
var CH_SECS=[['list','🎯 후보 목록','list'],['saved','📂 보관함','saved'],['track','📈 성과 기록','track'],['ai','🤖 AI 해설','ai'],['guide','📘 기준 설명','guide']];
var CH_SIG={'고득점':['⭐','#fefce8','#a16207','종합 기술점수 70점 이상'],'거래급증':['⚡','#fffbeb','#b45309','거래량이 20일 평균의 2배 이상'],'강한모멘텀':['🔥','#fef2f2','#dc2626','RSI 52~68 — 힘은 있으면서 과열은 아닌 구간'],
 '눌림목':['🌊','#f0f9ff','#0369a1','RSI 40~45 — 오른 뒤 쉬어 가는 구간'],'과열주의⚠':['🌡','#fef2f2','#dc2626','RSI 78 이상 — 단기 과열 구간이라 변동에 주의'],'돌파임박':['📦','#f5f3ff','#6d28d9','볼린저밴드가 좁아진 상태(변동성 압축)'],
 '쌍끌이':['🟢','#dcfce7','#15803d','외국인과 기관이 5일 동안 함께 순매수'],'수급유입':['💰','#ecfdf5','#047857','외국인 또는 기관이 5일 동안 순매수'],'수급전환':['🔁','#ccfbf1','#0f766e','20일은 순매도·중립이었는데 5일은 순매수로 전환'],
 '신고가근접':['🎯','#fef2f2','#b91c1c','52주 위치 85% 이상 — 위쪽에 쌓인 매물이 적은 구간(정밀검증 값)'],'52주상단':['📈','#fff7ed','#c2410c','52주 위치 70% 이상(정밀검증 값)'],'정배열':['📶','#eff6ff','#1d4ed8','단기>중기>장기 이동평균이 위로 정렬(정밀검증 값)']};
var CH_CSS='.chHd{padding:14px 16px}.chHd h2{margin:0 0 4px;font-size:18px}.chSt{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0}'+
'.chCh{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;background:#f1f5f9;color:#334155;border:1px solid #e2e8f0;white-space:nowrap}'+
'.chCh.a{background:#eef2ff;color:#4338ca;border-color:#c7d2fe}.chCh.w{background:#fffbeb;color:#b45309;border-color:#fcd34d}.chCh.g{background:#f8fafc;color:#64748b}'+
'.chNav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 8px}.chNav button{border:1.5px solid #cbd5e1;background:#fff;color:#334155;border-radius:999px;padding:7px 13px;font:inherit;font-size:13px;font-weight:700;cursor:pointer}'+
'.chNav button.chOn{background:#4338ca;border-color:#4338ca;color:#fff}'+
'.chW{overflow-x:auto;-webkit-overflow-scrolling:touch}.chT{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}.chT th{background:#eef2ff;white-space:nowrap}.chT th.chSrt{cursor:pointer}.chT td{word-break:keep-all;vertical-align:middle}'+
'.chT td.r,.chT th.r{text-align:right;white-space:nowrap}.chT tr.chDt td{background:#f8fafc}.chT .nm{font-weight:800;color:#0f172a}.chT .sb{font-size:11px;color:#94a3b8;margin-top:1px}.chT tr.chSelR td{background:#f5f3ff}'+
'.chUp{color:#dc2626;font-weight:700}.chDn{color:#2563eb;font-weight:700}.chZ{color:#94a3b8}.chSc{font-size:16px;font-weight:900;color:#0f172a}'+
'.chGr{display:inline-block;color:#fff;font-size:10.5px;font-weight:900;padding:2px 7px;border-radius:5px;margin-left:4px}'+
'.chSg{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 6px;border-radius:5px;margin:0 3px 3px 0;white-space:nowrap}'+
'.chL{display:inline-flex;flex-direction:column;gap:2px;font-size:11.5px;color:#64748b}.chL select{min-width:92px}'+
'.chCards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px;margin:8px 0}.chCard{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px}.chCard.chSelC{border-color:#4338ca;background:#f5f3ff}'+
'.chTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}.chTile{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px}.chTile .l{font-size:12px;color:#64748b;font-weight:700}.chTile .v{font-size:22px;font-weight:900;color:#0f172a;margin-top:2px}.chTile .s{font-size:11px;color:#94a3b8}'+
'.chKv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}.chKv div{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px;font-size:12.5px}.chKv b{display:block;font-size:11.5px;color:#64748b;margin-bottom:2px}'+
'.chAiOut{white-space:pre-wrap;word-break:break-word;font-size:13.5px;line-height:1.65;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin-top:8px}'+
'.chAiOut .h2{display:block;font-weight:900;color:#fff;background:#4338ca;border-radius:8px;padding:5px 10px;margin:10px 0 4px}.chAiOut .h3{display:block;font-weight:800;border-left:5px solid #4338ca;padding-left:8px;margin:8px 0 2px}'+
'.chGd h4{margin:12px 0 4px;font-size:14px}.chGd p,.chGd li{font-size:13px;line-height:1.65;color:#334155;margin:3px 0}.chGd ul{margin:4px 0 4px 18px;padding:0}'+
'.chCard2{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:8px 0}.chCard2 h3{margin:0 0 4px;font-size:16px}'+
'@media(max-width:520px){.chT{font-size:12px}.chT td,.chT th{padding:6px 6px}.chTile .v{font-size:19px}.chHd{padding:12px}.chL select{min-width:84px}}';
function chCss(){if(CH.css)return;CH.css=true;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';
 var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=CH_CSS;document.head.appendChild(s)}
function chN(v,d){if(v==null||isNaN(v))return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d,minimumFractionDigits:d==null?0:d})}
function chFv(v){v=Number(v)||0;if(v===0)return '0';var s=v>0?'+':'-',a=Math.abs(v);
 if(a>=1e12)return s+(a/1e12).toFixed(2)+'조';if(a>=1e10)return s+Math.round(a/1e8).toLocaleString('ko-KR')+'억';if(a>=1e8)return s+(a/1e8).toFixed(1)+'억';
 if(a>=1e4)return s+Math.round(a/1e4).toLocaleString('ko-KR')+'만';return s+'<1만'}
function chCls(v){return v>0?'chUp':(v<0?'chDn':'chZ')}
function chPct(v,d){if(v==null||isNaN(v))return '-';return (v>0?'+':'')+Number(v).toFixed(d==null?2:d)+'%'}
function chTk(node,t){if(typeof window.GoStock==='function'||typeof window.__openTicker==='function'){node.className=(node.className?node.className+' ':'')+'tkl';node.setAttribute('data-tk',t);node.title='눌러서 종목분석·심층분석 열기'}return node}
function chQ(o){var a=[];Object.keys(o).forEach(function(k){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]))});return a.join('&')}
function chSel(bar,lbl,obj,key,opts,fn){var l=el('label','chL');l.appendChild(el('span',null,lbl));var s=el('select');opts.forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];s.appendChild(op)});s.value=obj[key];s.onchange=function(){obj[key]=s.value;if(fn)fn()};l.appendChild(s);bar.appendChild(l);return s}
function chGrade(g){var c={S:'#4f46e5',A:'#0891b2',B:'#64748b'}[g]||'#94a3b8';var x=el('span','chGr',(g||'-')+'급');x.style.background=c;return x}
function chSigs(list){var w=document.createDocumentFragment();(list||[]).forEach(function(s){var m=CH_SIG[s];var x=el('span','chSg',(m?m[0]+' ':'')+s);x.style.background=m?m[1]:'#eee';x.style.color=m?m[2]:'#555';if(m)x.title=m[3];w.appendChild(x)});if(!(list||[]).length)w.appendChild(el('span','chZ','-'));return w}
function chTblBuild(heads,aligns){var w=el('div','chW'),t=el('table','chT'),h=el('tr');heads.forEach(function(x,i){h.appendChild(el('th',aligns&&aligns[i]==='r'?'r':'',x))});t.appendChild(h);w.appendChild(t);return {wrap:w,t:t,h:h}}
function chEmpty(box,j){var c=el('div','chCard2');c.appendChild(el('b',null,'📦 아직 보여 줄 자료가 없어요'));c.appendChild(el('p','note',j.msg||'데이터 가져오기 메뉴에서 표를 가져오면 보여요.'));box.appendChild(c)}
function chPlace(box,fid,txt){var c=el('div','chCard2');c.appendChild(el('b',null,txt||'이 기능은 잠겨 있어요'));c.appendChild(el('p','note','등급이 열리면 이 자리에 내용이 나타나요. 위 안내를 눌러 자세히 확인해 보세요.'));
 var sk=el('div');sk.style.cssText='height:90px;background:repeating-linear-gradient(90deg,#f1f5f9 0 40px,#e2e8f0 40px 42px);border-radius:10px';c.appendChild(sk);box.appendChild(c);ftSec(box,fid)}
function chDetailOk(j){return ftOk('detail')&&!(j&&j.locked&&j.locked.indexOf('detail')>=0)}
function chErr(o,msg){if(!o)return;o.innerHTML='';o.appendChild(el('p','note bad','⚠ '+msg))}

/* ── 표 내보내기·이미지(기능 'exp') ── */
function chSetTbl(title,cols,items,asof){CH.tbl={title:title,asof:asof||'',head:cols.map(function(c){return c.h}),num:cols.map(function(c){return !!c.num}),
 raw:items.map(function(it){return cols.map(function(c){return c.raw(it)})}),disp:items.map(function(it){return cols.map(function(c){var r=c.raw(it);return c.disp?c.disp(it,r):String(r==null?'':r)})})}}
function chDl(blob,name){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href)},4000)}
function chStamp(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())}
function chCsv(){var T=CH.tbl;if(!T||!T.raw.length){toast('내려받을 표가 아직 없어요. 먼저 조회해 주세요.');return}
 function q(x,num){if(x==null)return '';var s=String(x);if(!num&&/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'}
 var L=[T.head.map(function(h){return q(h)}).join(',')];T.raw.forEach(function(r){L.push(r.map(function(x,i){return q(x,T.num[i])}).join(','))});
 L.push('');L.push(q('기준 '+(T.asof||'-')+' · 도전점수 기준에 부합한 종목 목록(정보)이며 투자 권유가 아닙니다'));
 chDl(new Blob(['﻿'+L.join('\r\n')],{type:'text/csv;charset=utf-8'}),'도전주분석_'+chStamp()+'.csv');toast('CSV 파일을 내려받았어요')}
function chPng(){var T=CH.tbl;if(!T||!T.disp.length){toast('내려받을 표가 아직 없어요. 먼저 조회해 주세요.');return}
 var rows=T.disp.slice(0,30),cw=T.head.map(function(h,i){return i===0?(T.head[0]==='#'?44:200):(T.num[i]?104:150)}),W=cw.reduce(function(a,b){return a+b},0)+40;W=Math.max(W,640);var rh=34,H=130+rows.length*rh+70,S=2;
 var cv=document.createElement('canvas');cv.width=W*S;cv.height=H*S;var c=cv.getContext('2d');c.scale(S,S);var F="'Malgun Gothic','Apple SD Gothic Neo',sans-serif";
 c.fillStyle='#f8fafc';c.fillRect(0,0,W,H);c.fillStyle='#4338ca';c.fillRect(0,0,W,70);c.fillStyle='#fff';c.font='800 22px '+F;c.fillText('🎯 '+T.title,20,32);c.font='600 13px '+F;c.fillText('기준 '+(T.asof||'-')+' · 도전점수 기준에 부합한 종목 목록(정보)',20,56);
 var y=96;c.fillStyle='#e0e7ff';c.fillRect(20,y-22,W-40,30);c.fillStyle='#334155';c.font='800 13px '+F;var x=20;T.head.forEach(function(h,i){c.textAlign=T.num[i]?'right':'left';c.fillText(h,T.num[i]?x+cw[i]-8:x+8,y);x+=cw[i]});
 rows.forEach(function(r,ri){y+=rh;if(ri%2===1){c.fillStyle='#f1f5f9';c.fillRect(20,y-22,W-40,rh)}x=20;r.forEach(function(v,i){c.fillStyle='#0f172a';c.font=(i===1?'800 ':'600 ')+'13px '+F;c.textAlign=T.num[i]?'right':'left';
  var s=String(v);var mx=cw[i]-14;while(s.length>1&&c.measureText(s).width>mx)s=s.slice(0,-2)+'…';c.fillText(s,T.num[i]?x+cw[i]-8:x+8,y);x+=cw[i]})});
 c.textAlign='left';c.fillStyle='#64748b';c.font='600 12px '+F;c.fillText('공개된 시세·수급 자료를 점수 기준으로 정리한 정보 제공용이며 특정 종목의 매수·매도 권유가 아닙니다. 점수는 미래 수익을 보장하지 않습니다.',20,H-30);
 c.fillText('투자 판단과 책임은 이용자 본인에게 있습니다.',20,H-12);
 try{cv.toBlob(function(b){if(!b){toast('이미지를 만들지 못했어요');return}chDl(b,'도전주분석_'+chStamp()+'.png');toast('이미지를 내려받았어요')},'image/png')}catch(e){toast('이미지를 만들지 못했어요')}}
function chExpBar(parent){var r=el('div','bar');r.appendChild(ft(bt('📄 표 내려받기(CSV)','bt3',chCsv),'exp'));r.appendChild(ft(bt('🖼 이미지 내려받기','bt3',chPng),'exp'));
 r.appendChild(el('span','m','지금 보이는 표를 파일로 가져가요'));parent.appendChild(r)}

/* ── 위쪽 틀 ── */
function chLoad(p){chCss();p.innerHTML='';
 var hd=el('div','c chHd');hd.appendChild(el('h2',null,'🎯 도전주 분석'));hd.appendChild(el('div','m','거래량 증가·수급·RSI 모멘텀·변동성 압축을 점수(도전 점수)로 매겨, 기준에 부합한 종목을 정리해 보여 줘요. 종목을 추천하는 화면이 아니라 기준에 맞는 종목 목록(정보)이에요. 투자 권유가 아니며 판단과 책임은 이용자 본인에게 있어요.'));
 var sb=el('div');sb.id='chSum';hd.appendChild(sb);p.appendChild(hd);
 var nv=el('div','chNav');nv.id='chNav';p.appendChild(nv);var bd=el('div');bd.id='chBody';p.appendChild(bd);
 p.appendChild(el('p','note','※ 자료는 가져온 시세·수급 캐시를 점수식으로 계산한 값이에요(시세 기준일이 오늘보다 앞설 수 있어요). 점수가 높다는 것은 기준에 많이 부합한다는 뜻일 뿐 오른다는 뜻이 아니며, 이후 주가는 오를 수도 내릴 수도 있어요. 이 화면은 정보 제공용이며 특정 종목의 매수·매도 권유가 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다.'));
 var ad=el('div','c');ad.id='chAdm';p.appendChild(adm(ad));
 chNavDraw();chShow();if(!MEMBER_MODE)chAdmLoad()}
function chNavDraw(){var n=$('chNav');if(!n)return;n.innerHTML='';CH_SECS.forEach(function(s){var b=el('button',CH.sec===s[0]?'chOn':'',(ftOk(s[2])?'':'🔒 ')+s[1]);b.type='button';b.onclick=function(){chGo(s[0])};n.appendChild(b)})}
function chGo(sec){CH.sec=sec;chNavDraw();chShow()}
function chShow(){var b=$('chBody');if(!b)return;b.innerHTML='';var box=el('div');b.appendChild(box);
 var m={list:chSecList,saved:chSecSaved,track:chSecTrack,ai:chSecAi,guide:chSecGuide}[CH.sec],fid=CH_SECS.filter(function(s){return s[0]===CH.sec})[0][2];
 if(!ftOk(fid)){var f=FEATS&&FEATS[fid];chPlace(box,fid,'🔒 '+(f?f.label:'잠긴 기능'));return}m(box)}
function chStatus(j){var b=$('chSum');if(!b)return;b.innerHTML='';if(!j||j.empty||!j.meta)return;var m=j.meta,st=el('div','chSt');
 st.appendChild(el('span','chCh a','📅 시세 기준일 '+(m.price_asof||'알 수 없음')));st.appendChild(el('span','chCh','계산 대상 '+chN(m.universe)+'종목'));
 if(m.has_inv)st.appendChild(el('span','chCh','수급 갱신 '+(m.inv_last||'-')));else st.appendChild(el('span','chCh w','수급 표 없음 — 수급 신호·가감은 빠져요'));
 if(!m.has_vol)st.appendChild(el('span','chCh w','거래량·변동성 열 없음 — 그 신호는 빠져요'));
 if(m.risk_n&&j.q&&j.q.exclude_risk)st.appendChild(el('span','chCh g','상장폐지·거래정지 위험 '+m.risk_n+'종목은 제외'));b.appendChild(st)}

/* ── 후보 목록(기능 'list') + 점수·근거 상세(기능 'detail') ── */
function chSecList(box){var S=CH.ld;box.appendChild(el('p','note','시세·수급 캐시로 매긴 도전 점수(0~100)가 기준 이상인 종목을 점수 순서로 보여 줘요. 등급은 S(75↑)·A(62↑)·B예요. 신호 배지를 마우스로 가리키면 뜻이 나와요. 점수가 높을수록 기준에 더 많이 부합한다는 뜻이에요.'));
 var bar=el('div','bar');var go=function(){chListGo(false)};
 S.refs.market=chSel(bar,'시장',S,'market',[['all','코스피+코스닥'],['KOSPI','코스피'],['KOSDAQ','코스닥']],go);
 S.refs.min=chSel(bar,'최소 점수',S,'min',[['40','40 (넓게)'],['45','45'],['50','50 (기본)'],['55','55'],['60','60'],['65','65'],['70','70'],['75','75'],['80','80 (엄격)']],go);
 S.refs.top=chSel(bar,'보여줄 개수',S,'top',[['20','20개'],['40','40개'],['60','60개'],['120','120개'],['200','200개']],go);
 chSel(bar,'보기',S,'view',[['table','표'],['card','카드']],function(){chListDraw()});
 bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);
 var ab=el('div','bar');ab.id='chScanBar';
 var lb=el('label');lb.style.fontSize='12.5px';var ck=el('input');ck.type='checkbox';ck.checked=S.enrich;ck.onchange=function(){S.enrich=ck.checked};lb.appendChild(ck);lb.appendChild(document.createTextNode(' 정밀검증 포함(52주 위치·정배열, 상위 종목만 · 수십 초)'));ab.appendChild(lb);
 var sc=bt('🔬 정밀검증 스캔','bt2',chScan);sc.id='chScanBtn';ab.appendChild(sc);ab.appendChild(bt('💾 결과 저장','bt',chSave));ab.appendChild(el('span','m','관리자만 보여요 · 저장하면 보관함과 성과 기록에 쌓여요'));box.appendChild(adm(ab));
 var sb=el('div','bar');sb.id='chSelBar';box.appendChild(sb);
 var out=el('div');out.id='chOut';box.appendChild(out);if(S.data)chListDraw();else chListGo(true)}
function chListGo(first){var S=CH.ld,out=$('chOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 var q=first&&!S.inited?{}:{markets:S.market==='all'?'KOSPI,KOSDAQ':S.market,min_score:S.min,top:S.top};
 api('/admin/api/challenge/list?'+chQ(q)).then(function(j){if(my!==S.seq)return;var o=$('chOut');if(!o)return;if(j.error){chErr(o,j.error);return}chListSet(j)}).catch(function(){chErr($('chOut'),'불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.')})}
function chListSet(j){var S=CH.ld;S.data=j;CH.ex={};CH.open={};
 if(!S.inited&&j.q){S.inited=true;S.market=j.q.markets.length===2?'all':j.q.markets[0];S.min=String(j.q.min_score);S.top=String(Math.min(200,j.q.top));CH.cfg=j.cfg;
  var ok=function(sel,v){if(sel){sel.value=v;if(sel.value!==v){var op=el('option',null,v);op.value=v;sel.appendChild(op);sel.value=v}}};ok(S.refs.market,S.market);ok(S.refs.min,S.min);ok(S.refs.top,S.top)}
 var o=$('chOut');if(o)chListDraw()}
function chSorted(items){var s=CH.ld.sort,col=s.col;var a=items.map(function(it,i){return [it,i]});
 a.sort(function(x,y){var u=x[0][col],v=y[0][col];if(u==null||u==='')u=-Infinity;if(v==null||v==='')v=-Infinity;var d=u<v?-1:(u>v?1:0);if(d===0)return x[1]-y[1];return s.asc?d:-d});return a.map(function(z){return z[0]})}
function chSortBy(col){var s=CH.ld.sort;if(s.col===col)s.asc=!s.asc;else{s.col=col;s.asc=false}chListDraw()}
function chSelCount(){return Object.keys(CH.ld.sel).filter(function(k){return CH.ld.sel[k]}).length}
function chSelDraw(items){var b=$('chSelBar');if(!b)return;b.innerHTML='';if(!items||!items.length)return;b.appendChild(el('span','m','☑ 선택(AI 해설에 쓰여요):'));
 var pick=function(f){CH.ld.sel={};items.forEach(function(it,i){if(f(it,i))CH.ld.sel[it.ticker]=true});chListDraw()};
 [['S급만',function(it){return it.grade==='S'}],['A급 이상',function(it){return it.grade==='S'||it.grade==='A'}],['상위 10',function(it,i){return i<10}],['전체',function(){return true}],['해제',function(){return false}]].forEach(function(z){b.appendChild(bt(z[0],'bt3',function(){pick(z[1])}))});
 var c=el('span','m','선택 '+chSelCount()+'종목');c.id='chSelCnt';b.appendChild(c)}
function chListDraw(){var S=CH.ld,out=$('chOut');if(!out)return;var j=S.data;out.innerHTML='';if(!j)return;chStatus(j);if(j.empty){chEmpty(out,j);return}
 var items=chSorted(j.items||[]);chSelDraw(items);var dOk=chDetailOk(j);
 var gc=j.grade_cnt||{};out.appendChild(el('p','note',(j.scan?'🔬 정밀검증 스캔 결과 · ':'')+'기준에 부합한 종목 '+chN(j.matched)+'개 중 점수 상위 '+items.length+'개 · S '+(gc.S||0)+' · A '+(gc.A||0)+' · B '+(gc.B||0)+(j.scan?' · 52주 위치·정배열 확인 '+j.enriched+'/'+j.enrich_asked+'종목':'')));
 if(!dOk){var lk=el('div','bar');lk.appendChild(el('span','m','🔒 RSI·거래량·수급·점수 구성 같은 상세 값은 잠겨 있어요.'));lk.appendChild(bt('열리는 등급 보기','bt3',function(){lockDlg('detail')}));out.appendChild(lk)}
 if(!items.length){out.appendChild(el('p','note','조건에 맞는 종목이 없어요. 최소 점수를 40 쪽으로 낮추거나 시장을 넓혀 보세요.'));CH.tbl=null;return}
 if(S.view==='card')chCards(out,items,dOk);else chTable(out,items,{sel:true,explain:true,sortable:true,detail:dOk});
 var cols=[{h:'#',raw:function(it){return items.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'시장',raw:function(it){return it.market}},{h:'현재가(원)',raw:function(it){return it.price},num:1,disp:function(it,r){return r==null?'-':chN(r)}},
  {h:'등락률(%)',raw:function(it){return it.day_pct},num:1,disp:function(it,r){return r==null?'-':chPct(r)}},{h:'도전점수',raw:function(it){return it.ch_score},num:1},{h:'등급',raw:function(it){return it.grade}},{h:'신호',raw:function(it){return it.signals.join(' · ')}}];
 if(dOk)cols=cols.concat([{h:'RSI',raw:function(it){return it.rsi},num:1,disp:function(it,r){return r==null?'-':chN(r,1)}},{h:'거래량배수',raw:function(it){return it.vol_ratio},num:1,disp:function(it,r){return r?chN(r,2)+'배':'-'}},{h:'52주위치(%)',raw:function(it){return it.pos52},num:1,disp:function(it,r){return r==null?'-':chN(r,1)}}]);
 chSetTbl('도전 점수 기준 부합 종목'+(j.scan?' (정밀검증)':''),cols,items,j.meta?j.meta.price_asof:'');chExpBar(out)}
function chThSort(h,heads){heads.forEach(function(x){var th=el('th',(x[2]?'r':'')+(x[1]?' chSrt':''),x[0]+(CH.ld.sort.col===x[1]?(CH.ld.sort.asc?' ▲':' ▼'):''));if(x[1])th.onclick=function(){chSortBy(x[1])};h.appendChild(th)})}
function chTable(out,items,o){var det=!!o.detail,S=CH.ld;var w=el('div','chW'),t=el('table','chT'),h=el('tr');
 if(o.sel){var th0=el('th',null,'');var all=el('input');all.type='checkbox';all.checked=items.length>0&&items.every(function(it){return S.sel[it.ticker]});all.title='전체 선택';all.onchange=function(){items.forEach(function(it){S.sel[it.ticker]=all.checked});chListDraw()};th0.appendChild(all);h.appendChild(th0)}
 var heads=[['#',null,0],['종목',null,0],['현재가',o.sortable?'price':null,1,o.sortable],['등락',o.sortable?'day_pct':null,1,o.sortable],['도전점수',o.sortable?'ch_score':null,1,o.sortable]];
 if(det)heads=heads.concat([['RSI',o.sortable?'rsi':null,1,o.sortable],['거래량배수',o.sortable?'vol_ratio':null,1,o.sortable],['52주위치',o.sortable?'pos52':null,1,o.sortable],['수급 5일',null,1]]);
 heads.push(['신호',null,0]);chThSort(h,heads);t.appendChild(h);
 var ncol=heads.length+(o.sel?1:0);
 items.forEach(function(it,i){var tr=el('tr',S.sel[it.ticker]&&o.sel?'chSelR':'');
  if(o.sel){var c0=el('td');var cb=el('input');cb.type='checkbox';cb.checked=!!S.sel[it.ticker];cb.onchange=function(){S.sel[it.ticker]=cb.checked;chListDraw()};c0.appendChild(cb);tr.appendChild(c0)}
  tr.appendChild(el('td','chZ',String(i+1)));var nm=el('td');nm.appendChild(chTk(el('span','nm',it.name),it.ticker));
  if(o.explain){var tg=el('span','chZ',' ▾');tg.style.cursor='pointer';tg.title='점수 구성 보기';tg.setAttribute('data-ex',it.ticker);tg.onclick=function(){if(!ftOk('detail')){lockDlg('detail');return}CH.open[it.ticker]=!CH.open[it.ticker];if(CH.open[it.ticker]&&!CH.ex[it.ticker])chExFetch(it.ticker);else chListDraw()};if(!ftOk('detail'))tg.title='🔒 점수·근거 상세';nm.appendChild(tg)}
  nm.appendChild(el('div','sb',it.ticker+(it.market?' · '+it.market:'')+(it.sector?' · '+it.sector:'')));tr.appendChild(nm);
  var pc=el('td','r');pc.appendChild(document.createTextNode(it.price?chN(it.price)+'원':'-'));tr.appendChild(pc);
  tr.appendChild(el('td','r '+chCls(it.day_pct),chPct(it.day_pct)));
  var sc=el('td','r');sc.appendChild(el('span','chSc',String(it.ch_score)));sc.appendChild(chGrade(it.grade));tr.appendChild(sc);
  if(det){tr.appendChild(el('td','r',it.rsi==null?'-':chN(it.rsi,1)));tr.appendChild(el('td','r',it.vol_ratio?chN(it.vol_ratio,2)+'x':'-'));tr.appendChild(el('td','r',it.pos52==null?'—':chN(it.pos52,1)+'%'));
   var sp=(it.f5==null&&it.i5==null)?null:(it.f5||0)+(it.i5||0);tr.appendChild(el('td','r '+chCls(sp),sp==null?'-':chFv(sp)))}
  var sg=el('td');sg.appendChild(chSigs(it.signals));tr.appendChild(sg);t.appendChild(tr);
  if(o.explain&&CH.open[it.ticker]){var d2=el('tr','chDt'),dc=el('td');dc.colSpan=ncol;dc.appendChild(chExBox(it));d2.appendChild(dc);t.appendChild(d2)}});
 w.appendChild(t);out.appendChild(w)}
function chCards(out,items,det){var g=el('div','chCards');var S=CH.ld;
 items.forEach(function(it,i){var c=el('div','chCard'+(S.sel[it.ticker]?' chSelC':''));var top=el('div');top.style.cssText='display:flex;justify-content:space-between;align-items:flex-start;gap:8px';
  var l=el('div');var cb=el('input');cb.type='checkbox';cb.checked=!!S.sel[it.ticker];cb.onchange=function(){S.sel[it.ticker]=cb.checked;chListDraw()};l.appendChild(cb);l.appendChild(document.createTextNode(' '));l.appendChild(chTk(el('b','nm',it.name),it.ticker));
  l.appendChild(el('div','m',it.ticker+(it.market?' · '+it.market:'')+(it.sector?' · '+it.sector:'')));top.appendChild(l);
  var r=el('div');r.style.textAlign='right';r.appendChild(el('span','chSc',String(it.ch_score)));r.appendChild(chGrade(it.grade));top.appendChild(r);c.appendChild(top);
  var pr=el('div');pr.style.margin='6px 0';pr.appendChild(document.createTextNode((it.price?chN(it.price)+'원 ':'-')+' '));pr.appendChild(el('span',chCls(it.day_pct),chPct(it.day_pct)));c.appendChild(pr);
  if(det)c.appendChild(el('div','m','RSI '+(it.rsi==null?'-':chN(it.rsi,1))+' · 거래량 '+(it.vol_ratio?chN(it.vol_ratio,2)+'배':'-')+(it.pos52!=null?' · 52주 '+chN(it.pos52,1)+'%':'')));
  var sg=el('div');sg.style.marginTop='6px';sg.appendChild(chSigs(it.signals));c.appendChild(sg);
  var ac=el('div','bar');ac.appendChild(ft(bt('▾ 점수 구성','bt3',function(){if(!ftOk('detail')){lockDlg('detail');return}CH.open[it.ticker]=!CH.open[it.ticker];if(CH.open[it.ticker]&&!CH.ex[it.ticker])chExFetch(it.ticker);else chListDraw()}),'detail'));c.appendChild(ac);
  if(CH.open[it.ticker])c.appendChild(chExBox(it));g.appendChild(c)});out.appendChild(g)}
function chExFetch(tk){api('/admin/api/challenge/explain?ticker='+encodeURIComponent(tk)).then(function(j){CH.ex[tk]=j;chListDraw()}).catch(function(){CH.ex[tk]={error:'불러오지 못했어요.'};chListDraw()})}
function chExBox(it){var x=el('div'),j=CH.ex[it.ticker];if(!j){x.appendChild(el('p','note','⏳ 불러오는 중…'));return x}
 if(j.error){x.appendChild(el('p','note bad','⚠ '+j.error));return x}
 var tb=chTblBuild(['항목','값','점수에 더해진 값'],['','','r']);var sum=0;
 j.parts.forEach(function(p){sum+=p.p;var tr=el('tr');tr.appendChild(el('td',null,p.k));tr.appendChild(el('td',null,p.v));tr.appendChild(el('td','r '+chCls(p.p),(p.p>0?'+':'')+p.p));tb.t.appendChild(tr)});
 var extra=0;if(it.pos52!=null&&it.pos52>=85)extra+=5;if((it.ma_align||'').indexOf('정배열')>=0)extra+=4;
 if(it.pos52!=null||it.ma_align){var tr2=el('tr');tr2.appendChild(el('td',null,'정밀검증(52주 위치·정배열)'));tr2.appendChild(el('td',null,'52주 위치 '+(it.pos52==null?'-':chN(it.pos52,1)+'%')+' · 이동평균 '+(it.ma_align||'-')));tr2.appendChild(el('td','r '+chCls(extra),(extra>0?'+':'')+extra));tb.t.appendChild(tr2)}
 var tt=el('tr');tt.appendChild(el('td',null,'합계(반올림, 0~100으로 제한)'));tt.appendChild(el('td',null,'등급 기준: S 75↑ · A 62↑ · B'));tt.appendChild(el('td','r',String(j.total+extra>100?100:j.total+extra)));tb.t.appendChild(tt);x.appendChild(tb.wrap);
 var kv=el('div','chKv');[['시가총액',it.cap?(it.cap>=10000?chN(it.cap/10000,1)+'조':chN(it.cap)+'억'):'-'],['PER · PBR',(it.per||'-')+' · '+(it.pbr||'-')],['테마',it.theme||'-'],['기술점수(종합)',it.score==null?'-':String(it.score)],['수급 5일 외국인 · 기관',(it.f5==null?'-':chFv(it.f5))+' · '+(it.i5==null?'-':chFv(it.i5))],['수급 20일 외국인 · 기관',(it.f20==null?'-':chFv(it.f20))+' · '+(it.i20==null?'-':chFv(it.i20))]].forEach(function(z){var d=el('div');d.appendChild(el('b',null,z[0]));d.appendChild(document.createTextNode(z[1]));kv.appendChild(d)});x.appendChild(kv);
 x.appendChild(el('p','note','점수 구성은 시세·수급 캐시로 계산한 값이에요(52주 위치·정배열은 관리자의 정밀검증 스캔 결과에만 반영돼요).'+(j.excluded?' 이 종목은 상장폐지·거래정지 위험 표시가 있어 목록에서는 빠져요.':'')));return x}

/* ── 관리자 전용: 정밀검증 스캔 · 결과 저장 ── */
function chScan(){var S=CH.ld;if(S.busy)return;S.busy=true;var b=$('chScanBtn');if(b){b.disabled=true;b.textContent='⏳ 스캔 중…(수십 초)'}
 var out=$('chOut');if(out){out.innerHTML='';out.appendChild(el('p','note','🔬 정밀검증 스캔 중… 상위 종목의 52주 위치·정배열을 네트워크로 확인해요(최대 30초).'))}
 apiJ('/admin/api/challenge/scan',{markets:S.market==='all'?['KOSPI','KOSDAQ']:[S.market],min_score:S.min,top:S.top,enrich:S.enrich?'1':'0'}).then(function(j){S.busy=false;var b2=$('chScanBtn');if(b2){b2.disabled=false;b2.textContent='🔬 정밀검증 스캔'}
  if(j.error){chErr($('chOut'),j.error);return}S.sel={};S.data=j;CH.ex={};CH.open={};S.inited=true;toast('정밀검증 스캔 완료 — '+(j.items||[]).length+'종목');chListDraw()}).catch(function(){S.busy=false;var b2=$('chScanBtn');if(b2){b2.disabled=false;b2.textContent='🔬 정밀검증 스캔'}chErr($('chOut'),'스캔하지 못했어요.')})}
function chSave(){var j=CH.ld.data;if(!j||!j.items||!j.items.length){toast('먼저 조회하거나 스캔하세요.');return}
 apiJ('/admin/api/challenge/save',{items:j.items}).then(function(r){if(r.error){toast(r.error);return}toast('💾 '+r.date+' 기준 부합 종목 '+r.saved+'건을 저장했어요(성과 기록에는 새로 '+r.new+'건)');CH.sv.list=null}).catch(function(){toast('저장하지 못했어요.')})}

/* ── 과거 결과 보관함(기능 'saved') ── */
function chSecSaved(box){box.appendChild(el('p','note','관리자가 저장해 둔 과거 결과예요. 저장한 순간의 값이라 지금 시세와 달라요. 목록에서 [보기]를 누르면 그때의 종목과 점수를 볼 수 있어요.'));
 var out=el('div');out.id='chSvOut';box.appendChild(out);if(CH.sv.cur){chSvView(out)}else if(CH.sv.list){chSvDraw(out)}else chSvGo()}
function chSvGo(){var out=$('chSvOut');if(!out)return;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/challenge/saved').then(function(j){var o=$('chSvOut');if(!o)return;if(j.error){chErr(o,j.error);return}CH.sv.list=j;chSvDraw(o)}).catch(function(){chErr($('chSvOut'),'불러오지 못했어요.')})}
function chSvDraw(out){var j=CH.sv.list;out.innerHTML='';if(!j)return;if(j.empty){chEmpty(out,j);return}
 if(!j.items.length){out.appendChild(el('p','note','저장된 결과가 아직 없어요.'));return}
 var tb=chTblBuild(['저장 결과','저장 시각','종목 수',''],['','','r','']);
 j.items.forEach(function(x){var tr=el('tr');var td=el('td');td.appendChild(el('span','nm',x.label));if(x.oversold)td.appendChild(el('div','sb','낙폭 모드로 저장된 옛 결과'));tr.appendChild(td);tr.appendChild(el('td',null,x.saved_at));tr.appendChild(el('td','r',String(x.cnt)));
  var ac=el('td');ac.appendChild(bt('보기','bt3',function(){chSvOpen(x.key)}));var del=bt('🗑 삭제','bt3',function(){if(!confirm('이 저장 결과를 삭제할까요? (성과 기록은 그대로 남아요)'))return;apiJ('/admin/api/challenge/saved/delete',{key:x.key}).then(function(r){if(r.error){toast(r.error);return}toast('삭제했어요');CH.sv.list=null;chSvGo()})});ac.appendChild(adm(del));tr.appendChild(ac);tb.t.appendChild(tr)});out.appendChild(tb.wrap)}
function chSvOpen(k){var out=$('chSvOut');if(!out)return;var my=++CH.sv.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/challenge/saved/get?key='+encodeURIComponent(k)).then(function(j){if(my!==CH.sv.seq)return;var o=$('chSvOut');if(!o)return;if(j.error){chErr(o,j.error);return}CH.sv.cur=j;chSvView(o)}).catch(function(){chErr($('chSvOut'),'불러오지 못했어요.')})}
function chSvView(out){var j=CH.sv.cur;out.innerHTML='';var bk=el('div','bar');bk.appendChild(bt('← 목록으로','bt3',function(){CH.sv.cur=null;chShow()}));bk.appendChild(el('b',null,'📂 '+(j.label||j.key)));out.appendChild(bk);
 var gc=j.grade_cnt||{};out.appendChild(el('p','note','저장 시각 '+j.saved_at+' · '+j.items.length+'종목 · S '+(gc.S||0)+' · A '+(gc.A||0)+' · B '+(gc.B||0)+' · 가격·점수는 저장 당시 값이에요.'+(j.oversold?' (낙폭 모드로 저장된 옛 결과라 점수 의미가 달라요)':'')));
 var dOk=chDetailOk(j);if(!dOk){var lk=el('div','bar');lk.appendChild(el('span','m','🔒 RSI·거래량·수급 같은 상세 값은 잠겨 있어요.'));lk.appendChild(bt('열리는 등급 보기','bt3',function(){lockDlg('detail')}));out.appendChild(lk)}
 if(!j.items.length){out.appendChild(el('p','note','이 저장 결과에는 읽을 수 있는 종목이 없어요.'));return}
 chTable(out,j.items.slice().sort(function(a,b){return b.ch_score-a.ch_score}),{sel:false,explain:false,sortable:false,detail:dOk});
 var its=j.items.slice().sort(function(a,b){return b.ch_score-a.ch_score});
 chSetTbl('도전주 저장 결과 · '+(j.label||j.key),[{h:'#',raw:function(it){return its.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'저장가(원)',raw:function(it){return it.price},num:1,disp:function(it,r){return r==null?'-':chN(r)}},
  {h:'도전점수',raw:function(it){return it.ch_score},num:1},{h:'등급',raw:function(it){return it.grade}},{h:'신호',raw:function(it){return it.signals.join(' · ')}}],its,j.saved_at);chExpBar(out)}

/* ── 성과 기록(기능 'track') ── */
function chSecTrack(box){var S=CH.tr;box.appendChild(el('p','note','관리자가 저장한 날의 가격과 지금 시세 캐시 가격을 비교한 기록이에요. 이 목록을 따라 투자했을 때의 수익이 아니며(비용·기간 보정 없음), 과거 결과가 미래를 보장하지 않아요. 오늘 저장한 건은 내일부터 계산돼요.'));
 var bar=el('div','bar'),go=function(){chTrackGo()};chSel(bar,'기간',S,'days',[['0','전체'],['7','7일'],['30','30일'],['90','90일']],go);chSel(bar,'최근 기록 개수',S,'limit',[['30','30개'],['60','60개'],['150','150개'],['300','300개']],go);bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);
 var out=el('div');out.id='chTrOut';box.appendChild(out);if(S.data)chTrackDraw(out);else chTrackGo()}
function chTrackGo(){var S=CH.tr,out=$('chTrOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/challenge/track?'+chQ({days:S.days,limit:S.limit})).then(function(j){if(my!==S.seq)return;var o=$('chTrOut');if(!o)return;if(j.error){chErr(o,j.error);return}S.data=j;chTrackDraw(o)}).catch(function(){chErr($('chTrOut'),'불러오지 못했어요.')})}
function chStatTbl(out,title,obj,keys,keyLbl,delFn){var ks=keys||Object.keys(obj);if(!ks.length)return;out.appendChild(el('h4',null,title));var tb=chTblBuild([keyLbl,'건수','오른 비율','평균 등락'].concat(delFn?['']:[]),['','r','r','r'].concat(delFn?['']:[]));
 ks.forEach(function(k){var x=obj[k];var tr=el('tr');tr.appendChild(el('td',null,k));tr.appendChild(el('td','r',String(x.cnt)));tr.appendChild(el('td','r',x.up_rate+'% ('+x.up+'/'+x.cnt+')'));tr.appendChild(el('td','r '+chCls(x.avg_ret),chPct(x.avg_ret)));
  if(delFn){var td=el('td');td.appendChild(adm(bt('🗑 삭제','bt3',function(){delFn(k)})));tr.appendChild(td)}tb.t.appendChild(tr)});out.appendChild(tb.wrap)}
function chTrackDraw(out){var j=CH.tr.data;out.innerHTML='';if(!j)return;if(j.empty){chEmpty(out,j);return}var t=j.total;
 if(!t.cnt){out.appendChild(el('p','note',j.today_cnt>0&&j.total_records===j.today_cnt?'오늘 저장한 '+j.today_cnt+'건은 내일부터 계산돼요.':(j.total_records?'계산할 수 있는 기록이 아직 없어요(저장가나 현재 시세가 없거나 기간 밖이에요).':'아직 저장된 성과 기록이 없어요. 관리자가 결과를 저장하면 쌓여요.')));CH.tbl=null;return}
 var g=el('div','chTiles');[['계산된 기록',chN(t.cnt)+'건','저장일 대비 현재 시세'],['오른 비율',t.up_rate+'%',t.up+'건 상승 · '+(t.cnt-t.up)+'건 하락·보합'],['평균 등락',chPct(t.avg_ret),'단순 평균(비용 제외)'],['누적 기록',chN(j.total_records)+'건','오늘 저장 '+j.today_cnt+'건은 내일부터']].forEach(function(z){var d=el('div','chTile');d.appendChild(el('div','l',z[0]));d.appendChild(el('div','v',z[1]));d.appendChild(el('div','s',z[2]));g.appendChild(d)});out.appendChild(g);
 if(j.skipped_oversold)out.appendChild(el('p','note','낙폭 모드로 저장된 옛 기록 '+j.skipped_oversold+'건은 점수 의미가 달라 계산에서 뺐어요.'));
 chStatTbl(out,'등급별',j.by_grade,['S','A','B','-'].filter(function(k){return j.by_grade[k]}),'등급');
 chStatTbl(out,'도전점수대별',j.by_score,['75점 이상(S권)','62~74점(A권)','50~61점(B권)','50점 미만'].filter(function(k){return j.by_score[k]}),'점수대');
 chStatTbl(out,'신호별',j.by_signal,Object.keys(j.by_signal).sort(function(a,b){return j.by_signal[b].cnt-j.by_signal[a].cnt}).slice(0,14),'신호');
 chStatTbl(out,'충족 신호 개수별',j.by_sig_count,Object.keys(j.by_sig_count).sort(function(a,b){return Number(a)-Number(b)}),'신호 개수');
 chStatTbl(out,'저장일별',j.by_date,Object.keys(j.by_date),'저장일',function(d){if(!confirm(d+' 에 저장한 성과 기록을 모두 삭제할까요?'))return;apiJ('/admin/api/challenge/track/delete',{pick_date:d}).then(function(r){if(r.error){toast(r.error);return}toast('삭제했어요('+r.deleted+'건)');CH.tr.data=null;chTrackGo()})});
 out.appendChild(el('h4',null,'최근 기록'));var tb=chTblBuild(['저장일','종목','등급·점수','신호','저장가','현재가','등락'],['','','','','r','r','r']);
 j.recent.forEach(function(r){var tr=el('tr');tr.appendChild(el('td',null,r.date.slice(5)));var nm=el('td');nm.appendChild(chTk(el('span','nm',r.name),r.ticker));nm.appendChild(el('div','sb',r.ticker));tr.appendChild(nm);
  var sc=el('td');sc.appendChild(document.createTextNode(r.ch_score+' '));sc.appendChild(chGrade(r.grade));tr.appendChild(sc);var sg=el('td');sg.appendChild(chSigs(r.signals));tr.appendChild(sg);
  tr.appendChild(el('td','r',chN(r.pick_price)));tr.appendChild(el('td','r',chN(r.cur_price)));tr.appendChild(el('td','r '+chCls(r.ret),(r.up?'▲ ':'▼ ')+chPct(r.ret)));tb.t.appendChild(tr)});out.appendChild(tb.wrap);
 chSetTbl('도전주 성과 기록',[{h:'저장일',raw:function(r){return r.date}},{h:'종목',raw:function(r){return r.name}},{h:'코드',raw:function(r){return r.ticker}},{h:'도전점수',raw:function(r){return r.ch_score},num:1},{h:'등급',raw:function(r){return r.grade}},
  {h:'저장가(원)',raw:function(r){return r.pick_price},num:1,disp:function(r,v){return chN(v)}},{h:'현재가(원)',raw:function(r){return r.cur_price},num:1,disp:function(r,v){return chN(v)}},{h:'등락률(%)',raw:function(r){return r.ret},num:1,disp:function(r,v){return chPct(v)}}],j.recent,'저장일 대비 현재 시세 캐시');chExpBar(out)}

/* ── AI 해설 프롬프트(기능 'ai') — 수동 AI 도우미 ── */
function chSecAi(box){box.appendChild(el('p','note','후보 목록에서 체크한 종목(없으면 위쪽 상위 20종목)의 데이터를 담은 프롬프트를 만들어, 사용하는 AI(제미나이·챗GPT·클로드 등)에 붙여 넣을 수 있게 해요. AI가 답하면 복사해서 이 창으로 돌아오면 아래에 보여 줘요. AI 답변은 참고용이며 틀릴 수 있어요.'));
 var n=chSelCount();box.appendChild(el('p','note','대상: '+(n?'후보 목록에서 선택한 '+Math.min(n,30)+'종목(최대 30개)':'현재 조건(시장·최소 점수)의 점수 상위 20종목')));
 var bar=el('div','bar');bar.appendChild(ft(bt('🤖 AI 프롬프트 만들기','bt',chAiRun),'ai'));box.appendChild(bar);var out=el('div');out.id='chAiOut';box.appendChild(out);chAiDraw()}
function chAiRun(){if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}var S=CH.ld;
 var tk=Object.keys(S.sel).filter(function(k){return S.sel[k]}).slice(0,30).join(',');
 api('/admin/api/challenge/prompt?'+chQ({tickers:tk,markets:S.market==='all'?'KOSPI,KOSDAQ':S.market,min_score:S.min,top:20})).then(function(j){if(j.error){toast(j.error);return}if(j.empty){toast(j.msg);return}
  window.MiniAI.run({title:'도전주 AI 해설 — '+j.label,key:'challenge',steps:[{label:j.label,prompt:j.prompt}],minLen:150,hint:'AI가 "## 🎯 기준 부합 종목의 공통 특징 …" 형식으로 답하면 답변 전체를 복사하고 이 창으로 돌아오세요.',
   preview:function(t){var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString('ko-KR')+'자 — '+t.slice(0,240)+(t.length>240?' …':'');return {node:x,canApply:t.trim().length>=100,strict:true}},
   apply:function(t){CH.ai.text=String(t||'').slice(0,20000);chAiDraw();return Promise.resolve({message:'AI 해설을 아래 화면에 보여 줬어요.'})}})})}
function chAiDraw(){var out=$('chAiOut');if(!out)return;out.innerHTML='';var t=CH.ai.text;if(!t){out.appendChild(el('p','note','아직 AI 해설이 없어요. [AI 프롬프트 만들기]를 눌러 보세요.'));return}
 var box=el('div','chAiOut');t.split('\n').forEach(function(l){var m;var s=l.replace(/\*\*/g,'');if((m=/^##\s+(.*)$/.exec(s))){box.appendChild(el('span','h2',m[1]))}else if((m=/^###\s+(.*)$/.exec(s))){box.appendChild(el('span','h3',m[1]))}else{box.appendChild(document.createTextNode(s));box.appendChild(document.createElement('br'))}});out.appendChild(box);
 var r=el('div','bar');r.appendChild(bt('📋 해설 복사하기','bt3',function(){var ok=window.MiniAI&&window.MiniAI.copy?window.MiniAI.copy(CH.ai.text):false;toast(ok?'복사했어요':'복사가 막혔어요')}));r.appendChild(bt('✖ 지우기','bt3',function(){CH.ai.text='';chAiDraw()}));out.appendChild(r);
 out.appendChild(el('p','note','⚠ AI가 만든 참고 글이에요. 숫자와 내용이 틀릴 수 있고, 특정 종목의 매수·매도 권유가 아니에요.'))}

/* ── 기준 설명(기능 'guide', 서버 호출 없음) ── */
function chSecGuide(box){var g=el('div','chGd');
 function H(t){g.appendChild(el('h4',null,t))}function P(t){g.appendChild(el('p',null,t))}function UL(a){var u=el('ul');a.forEach(function(x){u.appendChild(el('li',null,x))});g.appendChild(u)}
 H('도전 점수란?');P('종목마다 시세·수급 자료를 7가지 기준으로 채점해 0~100점으로 합친 값이에요. “이 종목을 사라”는 뜻이 아니라, 거래가 붙고 수급이 들어오고 모멘텀이 건강한 모습에 얼마나 많이 부합하는지를 한 숫자로 줄인 거예요. 등급은 S(75점 이상)·A(62점 이상)·B예요.');
 H('점수는 이렇게 계산돼요(원본 프로그램과 같은 기준)');var tb=chTblBuild(['기준','조건','더해지는 점수'],['','','r']);
 [['종합 기술점수','기술 점수(0~100)의 40%','최대 +40'],['거래량 돌파','20일 평균 대비 3배↑ / 2배↑ / 1.3배↑','+18 / +12 / +6'],['RSI 모멘텀','52~68 / 45~52·68~72 / 40~45 / 78↑(과열)','+12 / +6 / +3 / −10'],
  ['당일 등락','+1~8% / +8~15% / +15%↑ / 0~1% / −3~0%','+8 / +4 / −4 / +3 / +2'],['변동성 압축','볼린저밴드가 최근 60일 중 가장 좁은 20% 구간','+8'],['수급 5일','외국인·기관 모두 순매수 / 한쪽만 / 둘 다 순매도','+12 / +6 / −10'],
  ['수급 전환','20일은 순매도·중립이었는데 5일은 순매수','+8']].forEach(function(r){var tr=el('tr');tr.appendChild(el('td',null,r[0]));tr.appendChild(el('td',null,r[1]));tr.appendChild(el('td','r',r[2]));tb.t.appendChild(tr)});g.appendChild(tb.wrap);
 P('합계는 0~100으로 제한하고, 설정한 최소 점수(기본 50점) 미만은 목록에서 빠져요. 관리자가 [정밀검증 스캔]을 돌리면 상위 종목에 52주 위치 85%↑(+5, 신고가근접)·정배열(+4) 보너스가 더해져요.');
 H('신호 배지');UL(['⭐ 고득점: 종합 기술점수 70점 이상','⚡ 거래급증: 거래량이 20일 평균의 2배 이상','🔥 강한모멘텀: RSI 52~68','🌊 눌림목: RSI 40~45','🌡 과열주의⚠: RSI 78 이상 — 단기 과열 구간','📦 돌파임박: 변동성 압축','🟢 쌍끌이 · 💰 수급유입 · 🔁 수급전환: 외국인·기관 5일 수급','🎯 신고가근접 · 📈 52주상단 · 📶 정배열: 정밀검증 값(관리자 스캔·저장 결과에서만)']);
 H('성과 기록은 어떻게 읽나요?');P('관리자가 저장한 날의 가격과 지금 시세 캐시 가격을 비교한 값이에요. 같은 날 같은 종목은 처음 저장한 값만 남아요. 비용·세금·보유 기간을 반영하지 않았고, 이 목록을 따라 투자했을 때의 수익이 아니에요.');
 H('읽을 때 꼭 알아 두세요');UL(['시세·수급은 가져온 캐시라 기준일이 오늘보다 앞설 수 있어요. 수급 표가 없으면 수급 점수는 모두 0이에요.','상장폐지·거래정지 위험으로 표시된 종목은 목록에서 빼요. ETF·스팩·우선주는 따로 거르지 않아요.','일부 종목은 20일 수급이 더 짧은 기간일 수 있어요(수급전환 신호 해석에 주의).','점수가 높아도 이후 주가는 오를 수도 내릴 수도 있어요. 이 화면은 정보 제공용이며 특정 종목의 매수·매도 권유가 아니에요. 투자 판단과 책임은 이용자 본인에게 있어요.']);
 box.appendChild(g)}

/* ── 관리자 전용 카드: 기준 저장 + 점검(회원 화면에서는 숨김) ── */
function chAdmLoad(){var b=$('chAdm');if(!b)return;api('/admin/api/challenge/diag').then(function(j){chAdmDraw(j)})}
function chAdmDraw(j){var b=$('chAdm');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'🛠 도전주 설정·점검 (관리자만 보여요)'));if(!j||j.error){b.appendChild(el('p','note bad','점검 정보를 읽지 못했어요.'));return}
 var T=j.tables||{};function nn(v){return v==null?'표 없음':v.toLocaleString('ko-KR')+'행'}
 b.appendChild(el('p','note','stock_price_cache '+nn(T.stock_price_cache)+' · investor_scan_cache '+nn(T.investor_scan_cache)+' · stock_theme_map '+nn(T.stock_theme_map)));
 if(j.meta&&j.meta.universe!=null)b.appendChild(el('p','note','계산 대상 '+j.meta.universe+'종목 · 시세 기준일 '+(j.meta.price_asof||'-')+' · 수급 갱신 '+(j.meta.inv_last||'-')+' · 시장 미상 '+j.no_market+'종목 · 기준(50점↑) S '+j.grades.S+' · A '+j.grades.A+' · B '+j.grades.B+' · 위험 제외 대상 '+j.meta.risk_n));
 if(j.missing&&j.missing.length)b.appendChild(el('p','note bad','비어 있는 표: '+j.missing.join(', ')+' — 📦 데이터 가져오기 메뉴에서 가져오세요.'));
 var c=j.cfg||{markets:['KOSPI','KOSDAQ'],min_score:50,limit:120,enrich_top:30,exclude_risk:1},S={min_score:String(c.min_score),limit:String(c.limit),enrich_top:String(c.enrich_top)};
 b.appendChild(el('p','note','기준(이용자 화면의 기본값): 시장·최소 점수·개수·정밀검증 대상·위험 종목 제외'));var bar=el('div','bar');
 var ks=el('input');ks.type='checkbox';ks.checked=c.markets.indexOf('KOSPI')>=0;var kd=el('input');kd.type='checkbox';kd.checked=c.markets.indexOf('KOSDAQ')>=0;
 var l1=el('label');l1.appendChild(ks);l1.appendChild(document.createTextNode(' 코스피 '));var l2=el('label');l2.appendChild(kd);l2.appendChild(document.createTextNode(' 코스닥 '));bar.appendChild(l1);bar.appendChild(l2);
 var mo=[];for(var x=40;x<=80;x+=5)mo.push([String(x),String(x)+'점']);
 chSel(bar,'기본 최소 점수',S,'min_score',mo);chSel(bar,'목록 상한',S,'limit',[['30','30개'],['60','60개'],['120','120개(원본)'],['200','200개']]);chSel(bar,'정밀검증 상위',S,'enrich_top',[['0','안 함'],['10','10종목'],['20','20종목'],['30','30종목(원본)']]);
 var rk=el('input');rk.type='checkbox';rk.checked=!!c.exclude_risk;var l3=el('label');l3.appendChild(rk);l3.appendChild(document.createTextNode(' 상장폐지·거래정지 위험 제외'));bar.appendChild(l3);
 bar.appendChild(bt('💾 기준 저장','bt',function(){var mk=[];if(ks.checked)mk.push('KOSPI');if(kd.checked)mk.push('KOSDAQ');if(!mk.length){toast('코스피나 코스닥 중 하나는 골라 주세요.');return}
  apiJ('/admin/api/challenge/cfg',{markets:mk,min_score:S.min_score,limit:S.limit,enrich_top:S.enrich_top,exclude_risk:rk.checked?1:0}).then(function(r){if(r.error){toast(r.error);return}toast('기준을 저장했어요');CH.ld.data=null;CH.ld.inited=false;chAdmLoad()})}));b.appendChild(bar);
 b.appendChild(bt('🔄 읽어 둔 자료 비우고 다시 읽기','bt2',function(){apiJ('/admin/api/challenge/reload',{}).then(function(r){if(r.error){toast(r.error);return}CH.ld.data=null;CH.ex={};chAdmDraw(r);chShow();toast('다시 읽었어요')})}))}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_settings({"challenge_cfg": json.dumps(DEFAULT_CFG, ensure_ascii=False)}, {"challenge_cfg": _valid_cfg})
    C.register_menu({"id": MENU, "label": "도전주", "icon": "🎯", "public_path": "/m/challenge", "admin_path": "/admin#ch",
                     "desc": "거래량·수급·RSI 모멘텀·변동성 압축을 점수로 매겨 ‘도전 점수’ 기준에 부합한 종목을 정리해 보여 줘요. 추천이 아니라 기준에 맞는 종목 목록(정보)이며 투자 권유가 아니에요.",
                     "access": "admin"})
    C.register_prompt("challenge_ai", {
        "title": "도전주 AI 프롬프트", "default": CH_DEFAULT, "required": ["{items_text}"], "must_have": [],
        "vars": "{items_text}=기준 부합 종목 목록(필수) · {today}=오늘 날짜 · {market_label}=시장 이름 · {count}=종목 수",
        "desc": "도전주 화면의 [AI 프롬프트 만들기]가 AI에게 보내는 요청문. 매수·매도 권유를 하지 않도록 쓰는 것이 원칙이에요."})
    C.register_admin_tab("ch", "🎯 도전주", TAB_JS, "chLoad", menu=MENU)
    # ── 기능별 공개: 추천형에 가까워 법적 검토 전에는 모두 관리자만(default admin). 관리자가 [🎚 기능 공개]에서 하나씩 연다. ──
    F = C.register_feature
    F(MENU, "list", "후보 목록 보기", "도전 점수 기준에 부합한 종목 이름·현재가·등락·점수·등급·신호. 이 기능이 열려 있어야 목록이 나와요(주소: 목록).", default="admin",
      endpoints=["/admin/api/challenge/list"])
    F(MENU, "detail", "점수·근거 상세", "RSI·거래량 배수·52주 위치·수급 금액·테마와 종목별 점수 구성(항목별 가감). 잠기면 목록·보관함에서 이 값들이 빠져요.", default="admin",
      endpoints=["/admin/api/challenge/explain"])
    F(MENU, "saved", "과거 결과 보관함", "관리자가 저장해 둔 과거 결과 목록과 그때의 종목·점수(저장 당시 값).", default="admin",
      endpoints=["/admin/api/challenge/saved", "/admin/api/challenge/saved/get"])
    F(MENU, "track", "성과 기록", "저장일 가격 대비 현재 시세 캐시 가격의 등락 기록과 등급·점수대·신호별 통계(읽기 전용).", default="admin",
      endpoints=["/admin/api/challenge/track"])
    F(MENU, "guide", "기준 설명", "도전 점수 계산 기준·신호 배지·성과 기록 읽는 법 해설(서버 호출 없음).", default="admin", endpoints=[])
    F(MENU, "ai", "AI 해설 프롬프트", "선택한 종목 데이터로 AI 프롬프트를 만들고 답변을 붙여 보기(수동 — 서버가 AI를 부르지 않아요).", default="admin",
      endpoints=["/admin/api/challenge/prompt"], kind="action")
    F(MENU, "exp", "표·이미지 내려받기", "지금 보는 표를 CSV 파일이나 PNG 이미지로 내려받기", default="admin", endpoints=[], kind="action")
    # 정밀검증 스캔(scan)·결과 저장(save)·보관함 삭제(saved/delete)·성과 기록 삭제(track/delete)·기준 저장(cfg)·점검(diag, reload)은
    # 관리자 업무 → 어떤 기능에도 넣지 않았다(회원 화면에서는 404).
    return bp
