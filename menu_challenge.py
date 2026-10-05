"""🎯 도전주 — '많이 떨어졌지만 회복 신호가 보이는 종목' 정리 (기능별 등급 공개 · 법적 검토 전까지 기본은 관리자만).

[v160 개념 변경] 예전 '도전점수'(거래량·RSI 모멘텀 점수) 방식을 버리고, 원본 프로그램의 '낙폭 우량주 스캔'(52주 고점 대비 낙폭)을 바탕으로 바꿨다.
  ① 낙폭   52주 고점 대비 하락률이 기준(기본 -30%) 이상인 종목만 본다.
  ② 회복   그중 아래 3가지가 '살아나고 있는지'를 따로 판정한다.
           · 재무  분기 영업이익이 흑자이거나 전 분기보다 나아지고, 매출이 늘고, 부채비율이 과하지 않은가
           · 수급  최근 5일 외국인·기관이 순매수로 돌아섰는가(쌍끌이 · 20일 내내 팔다가 5일은 사는 '전환')
           · 테마  이 종목이 속한 네이버 테마가 오늘 오르고, 같은 테마의 낙폭 종목들이 20일선을 되찾고 있는가
  ③ 그래프  종목마다 가격(고점·저점·20일선), 분기 영업이익, 20일 수급, 테마 등락을 그림으로 보여 준다.
  '회복 점수'(0~100)는 낙폭 25 + 재무 25 + 수급 25 + 테마 15 + 가격 안정 10 을 더한 값이다(S 75↑ · A 60↑ · B).

자료 흐름(웹 미니 전용 · 관리자가 [🔎 낙폭 스캔]을 누르면 서버가 백그라운드로 진행)
  1) 네이버 시총 순 종목 목록(동전주·시총 미달·상장폐지 위험 제외)
  2) 종목마다 일봉(_fetch_ohlcv) → 52주 고점·저점·반등폭·RSI·20일선·거래량 → challenge_dd_cache
  3) 낙폭 -20% 이상 종목만: 네이버 trend(20일 수급) + finance(분기·연간 재무) → challenge_dd_cache 에 함께 저장
  4) 네이버 테마 등락(collect_theme_list)을 날짜별로 challenge_theme_hist 에 한 줄씩 남김(테마 흐름 그래프용)
  테마는 📥 수급·테마 가져오기의 stock_theme_map / collect_theme_list 를 읽는다(없으면 테마 축은 '자료 없음').
  delist_watch / delist_snapshots 의 상장폐지·거래정지 위험 종목은 목록에서 뺀다.
  challenge_pick_track / challenge_saved_results 는 예전과 같은 표를 이어 쓰되, 새 방식으로 저장한 기록에는 '낙폭회복' 신호가 붙고
  성과 기록은 그 기록만 계산한다(옛 '도전점수' 기록은 뜻이 달라 뺀다).
캐시가 비어 있으면 오류 대신 "관리자가 [🔎 낙폭 스캔]을 실행하면 보여요" 안내를 돌려준다.

기능별 등급 공개(모두 기본 '관리자만' — 관리자가 [🎚 기능 공개]에서 하나씩 연다):
  list 후보 목록(낙폭·3축 판정·점수) · detail 그래프와 상세 수치 · saved 보관함 · track 성과 기록 · guide 기준 설명 · ai AI 해설 프롬프트 · exp 표/이미지 내려받기.
관리자 전용(어떤 기능에도 등록하지 않음 → 회원 화면에서는 404): 낙폭 스캔(scan/start·status·stop)·결과 저장(save)·보관함 삭제·성과 기록 삭제·기준 저장(cfg)·점검(diag/reload).
gateway 요청일 때 '상세'가 잠겨 있으면 그래프·수치 열을 응답에서 뺀다. 추천형 문구는 쓰지 않는다 — '회복 신호가 보이는 낙폭 종목 목록(정보)' + 투자 권유 아님 안내.
"""
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from flask import Blueprint, request

from menu_ctx import C
import menu_blog as B

bp = Blueprint("challenge", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "prompt_get", "_now_kst", "feature_ok", "setting_get", "setting_set")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

MENU = "challenge"
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
KEY_RE = re.compile(r"^[0-9A-Za-z_\-]{1,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CACHE_TTL = 30
MAX_SAVE = 200
GRADES = ("S", "A", "B")
SENTINEL = "낙폭회복"                     # 새 방식으로 저장한 기록의 표시(성과 기록은 이 표시가 있는 것만 계산)
SIGS = ("낙폭회복", "재무개선", "흑자전환", "재무양호", "수급전환", "쌍끌이", "수급유입", "테마강세", "테마회복", "반등시작", "단기추세전환", "과매도권")
DETAIL_KEYS = ("hi52", "hi_date", "lo_after", "rebound", "rsi", "vol_ratio", "ma_state", "f5", "i5", "f20", "i20", "cap", "theme",
               "fin", "flow", "chart", "themes", "notes", "price_at")
NEED_MSG = {"challenge_dd_cache": "낙폭 스캔 결과(challenge_dd_cache)", "challenge_pick_track": "도전주 추적(challenge_pick_track)",
            "challenge_saved_results": "도전주 저장 결과(challenge_saved_results)"}
DEFAULT_CFG = {"markets": ["KOSPI", "KOSDAQ"], "drop_pct": 30, "min_axes": 2, "limit": 60, "exclude_risk": 1, "scan_limit": 400}
DROPS = (20, 25, 30, 40, 50, 60)
SCAN_LIMITS = (200, 400, 600, 1000)
PENNY_FLOOR = 1000                         # 동전주 기준(원) — 원본 기본값
CAP_FLOOR = {"KOSPI": 300, "KOSDAQ": 200}  # 시총 미달 기준(억원) — 원본 기본값
DEEP_MIN = 20                              # 이보다 덜 빠진 종목은 재무·수급을 받지 않는다(낙폭 기준 최솟값)
WORKERS = 6
BASE = "https://m.stock.naver.com"
KEY_LAST = "challenge_scan_last"
KEY_AI = "challenge_ai_last"               # 마지막으로 저장한 AI 분석 {date, at, label, text, tickers}
BLOG_SECS = ("stats", "axes", "top", "ai", "list", "notes")

_LOCK = threading.Lock()
_ST = {"running": False, "phase": "", "total": 0, "done": 0, "ok": 0, "fail": 0, "skip": 0, "cand": 0, "cur": "", "started": 0.0, "ended": 0.0,
       "error": "", "stop": False, "msg": "", "result": {}}


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
    """공백·—·N/A → '', 코스닥/KOSDAQ → KOSDAQ, 코스피/KOSPI → KOSPI, 코넥스/KONEX → KONEX, 그 외 대문자 원문."""
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
    return "S" if ch >= 75 else ("A" if ch >= 60 else "B")


def _try(*sqls):
    """앞의 SQL부터 차례로 시도해 처음 성공한 (행들, 번호). 전부 실패(표·열 없음 등)하면 (None, -1)."""
    for i, s in enumerate(sqls):
        try:
            return (_dbx(s[0], s[1] if len(s) > 1 else (), fetch=True) or []), i
        except Exception:
            continue
    return None, -1


def _jl(s, default):
    try:
        v = json.loads(s) if isinstance(s, str) and s else None
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════
# 가져오기(네이버·일봉) — 시험에서는 아래 4개 함수만 바꿔 끼운다
# ══════════════════════════════════════════════════════════════
def _get_json(path, params=None):
    last = None
    for _k in range(2):
        try:
            r = C._RAW_HTTP.get(BASE + path, params=params, timeout=(5, 10), headers=dict(C.NAVER_M_HEADERS), _redirects=0)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError("HTTP %s" % r.status_code)
        except Exception as e:
            last = e
        time.sleep(0.4)
    raise last or RuntimeError("요청 실패")


def _num(s):
    try:
        t = re.sub(r"[^0-9.\-]", "", str(s or "").replace("+", ""))
        if t in ("", "-", "."):
            return 0
        return int(round(float(t)))
    except Exception:
        return 0


def _pf(s):
    try:
        t = re.sub(r"[^0-9.\-]", "", str(s or "").replace("+", ""))
        return float(t) if t not in ("", "-", ".") else None
    except Exception:
        return None


def _universe(limit):
    """시가총액 순 종목(코스피·코스닥 합쳐 limit개). 동전주·시총 미달은 여기서 뺀다."""
    pool = {}
    for mk in ("KOSPI", "KOSDAQ"):
        got, page = 0, 1
        while got < limit and page <= 12:
            if _stopped():
                return []
            data = _get_json("/api/stocks/marketValue/" + mk, {"page": page, "pageSize": 100})
            stocks = data.get("stocks") or []
            if not stocks:
                break
            for it in stocks:
                tk = str(it.get("itemCode") or "").strip().upper()
                if not TICKER_RE.match(tk) or tk in pool:
                    continue
                if str(it.get("stockEndType") or "stock") not in ("stock", ""):
                    continue
                ex = it.get("stockExchangeType") or {}
                nm = str(ex.get("nameEng") or ex.get("name") or "").upper()
                pool[tk] = {"ticker": tk, "name": str(it.get("stockName") or tk)[:40], "market": nm if nm in ("KOSPI", "KOSDAQ") else mk,
                            "price": _num(it.get("closePrice")), "cap": _num(it.get("marketValue"))}
                got += 1
            tc = data.get("totalCount")
            if tc is not None and page * 100 >= int(tc or 0):
                break
            page += 1
            time.sleep(0.05)
    rows = sorted(pool.values(), key=lambda r: -r["cap"])
    out = []
    for r in rows:
        if r["price"] and r["price"] < PENNY_FLOOR:
            continue                                       # 동전주
        if r["cap"] and r["cap"] < CAP_FLOOR.get(r["market"], 200):
            continue                                       # 시총 미달
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _ohlcv(tk):
    """일봉 DataFrame(최근 약 420일). 못 받으면 None."""
    st = (datetime.now() - timedelta(days=420)).strftime("%Y-%m-%d")
    return C._fetch_ohlcv(tk, st)


def _trend(tk):
    """네이버 trend 원본(최근 20거래일 외국인·기관 순매수 수량 + 종가)."""
    return _get_json("/api/stock/%s/trend" % tk, {"pageSize": 20})


def _finance(tk, period):
    return C._naver_finance(tk, period)


# ══════════════════════════════════════════════════════════════
# 진행 상태
# ══════════════════════════════════════════════════════════════
def _set(**k):
    with _LOCK:
        _ST.update(k)


def _snapshot():
    with _LOCK:
        s = dict(_ST)
    s["elapsed"] = int((s["ended"] if (not s["running"] and s["ended"]) else time.time()) - s["started"]) if s["started"] else 0
    s.pop("stop", None)
    return s


def _stopped():
    with _LOCK:
        return bool(_ST["stop"])


def _begin(msg):
    with _LOCK:
        if _ST["running"]:
            return False
        _ST.update(running=True, phase="start", total=0, done=0, ok=0, fail=0, skip=0, cand=0, cur="", started=time.time(), ended=0.0,
                   error="", stop=False, msg=msg, result={})
    return True


def _end(error="", result=None):
    try:
        _load(force=True)                      # 받은 만큼 바로 목록에 보이게 읽어 둔 자료를 새로 읽는다
    except Exception as e:
        print("[도전주] 다시 읽기 실패(무시): %s" % e)
    with _LOCK:
        _ST.update(running=False, ended=time.time(), error=error, phase="end", result=result or {})
        if _ST["stop"] and not error:
            _ST["msg"] = "⏹ 멈췄어요 — 여기까지 받은 자료는 저장되어 있어요."


def _stamp():
    return _now_kst().strftime("%Y-%m-%d %H:%M:%S")


def _conn():
    return C._pg_get() if C._USE_PG else C._history_conn()


def _run(ops):
    """[(sql, args_or_None)] 를 한 번에 실행하고 커밋. SQL 은 ? 로 쓴다."""
    conn = _conn()
    try:
        c = conn.cursor()
        for sql, args in ops:
            q = sql.replace("?", "%s") if C._USE_PG else sql
            if args is None:
                c.execute(q)
            else:
                c.execute(q, tuple(args))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
# 낙폭 계산(일봉 → 한 줄) · 수급 · 재무
# ══════════════════════════════════════════════════════════════
def _sample_idx(n, hi_i, lo_i, k=70):
    if n <= k:
        return list(range(n))
    s = {round(i * (n - 1) / (k - 1)) for i in range(k)}
    s.update((hi_i, lo_i, n - 1))
    return sorted(s)


def _dd_calc(df):
    """일봉 → 낙폭 한 줄(dict). 자료가 모자라면 None. 52주 = 최근 252거래일."""
    try:
        d = df.dropna(subset=["Close"]).tail(252)
        n = len(d)
        if n < 60:
            return None
        cl = [float(x) for x in d["Close"].tolist()]
        hs = [float(x) if x == x else c for x, c in zip(d["High"].tolist(), cl)] if "High" in d else cl
        ls = [float(x) if x == x else c for x, c in zip(d["Low"].tolist(), cl)] if "Low" in d else cl
        vs = [float(x) if x == x else 0.0 for x in d["Volume"].tolist()] if "Volume" in d else [0.0] * n
        price = cl[-1]
        hi = max(hs)
        hi_i = hs.index(hi)
        if price <= 0 or hi <= 0:
            return None
        lo_after = min(ls[hi_i:])
        lo_i = hi_i + ls[hi_i:].index(lo_after)
        dd = (price / hi - 1) * 100
        rebound = (price / lo_after - 1) * 100 if lo_after > 0 else 0.0
        # RSI 14 (단순 평균)
        rsi = None
        if n >= 15:
            ch = [cl[i] - cl[i - 1] for i in range(n - 14, n)]
            g = sum(x for x in ch if x > 0) / 14
            l_ = sum(-x for x in ch if x < 0) / 14
            rsi = 100.0 if l_ == 0 and g > 0 else (50.0 if l_ == 0 else 100 - 100 / (1 + g / l_))
        ma = lambda k, end=None: (sum(cl[(end or n) - k:(end or n)]) / k) if (end or n) >= k else None
        ma5, ma20, ma60 = ma(5), ma(20), ma(60)
        if ma5 and ma20 and ma60 and price > ma5 > ma20 > ma60:
            st = "정배열"
        elif ma20 and ma5 and price > ma20 and ma5 >= ma20:
            st = "단기상승"
        elif ma20 and price > ma20:
            st = "20일선 위"
        else:
            st = "20일선 아래"
        vr = None
        if n >= 21 and sum(vs[-21:-1]) > 0:
            vr = vs[-1] / (sum(vs[-21:-1]) / 20)
        prev = cl[-2] if n >= 2 else price
        day_pct = (price / prev - 1) * 100 if prev else 0.0
        idx = _sample_idx(n, hi_i, lo_i)
        m20 = []
        for i in idx:
            v = ma(20, i + 1)
            m20.append(None if v is None else int(round(v)))
        dates = [x.strftime("%Y-%m-%d") for x in d.index]
        chart = {"c": [int(round(cl[i])) for i in idx], "m": m20, "hi": idx.index(hi_i), "lo": idx.index(lo_i), "d0": dates[idx[0]], "d1": dates[-1], "dh": dates[hi_i]}
        return {"price": int(round(price)), "hi52": int(round(hi)), "hi_date": dates[hi_i], "lo_after": int(round(lo_after)), "dd": round(dd, 1), "rebound": round(rebound, 1),
                "rsi": None if rsi is None else round(rsi, 1), "vol_ratio": None if vr is None else round(vr, 2), "day_pct": round(day_pct, 2), "ma_state": st,
                "above20": 1 if st != "20일선 아래" else 0, "price_at": dates[-1], "chart": chart}
    except Exception as e:
        print("[도전주] 낙폭 계산 실패(무시): %s" % e)
        return None


def _flow_calc(raw):
    """trend 원본 → [[MM-DD, 외국인(억), 기관(억)] …] 오래된 날부터. 수량×종가 근사치. 없으면 None."""
    if not isinstance(raw, list) or not raw:
        return None
    rows = []
    for d in raw:
        bd = re.sub(r"\D", "", str(d.get("bizdate") or ""))[:8]
        px = abs(_num(d.get("closePrice")))
        if len(bd) != 8 or not px:
            continue
        rows.append((bd, _num(d.get("foreignerPureBuyQuant")) * px / 1e8, _num(d.get("organPureBuyQuant")) * px / 1e8))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    return [["%s-%s" % (r[0][4:6], r[0][6:8]), round(r[1], 1), round(r[2], 1)] for r in rows[-20:]]


def _fin_calc(q, a):
    """분기·연간 재무 → 그래프용 한 줄. 둘 다 없으면 None. 금액은 억원, 부채비율은 %."""
    def pick(fin, name, actual_only=True):
        if not fin:
            return [], []
        per = fin.get("periods") or []
        row = next((r for r in fin.get("rows") or [] if r.get("name") == name), None)
        if not row:
            return [], []
        labs, vals = [], []
        for p, v in zip(per, row.get("values") or []):
            if actual_only and p.get("estimate"):
                continue
            labs.append(str(p.get("title") or "")[:8])
            vals.append(v)
        return labs, vals
    ql, qop = pick(q, "영업이익")
    _l2, qrev = pick(q, "매출액")
    _l3, qni = pick(q, "당기순이익")
    al, aop = pick(a, "영업이익")
    _l4, adebt = pick(a, "부채비율")
    _l5, aroe = pick(a, "ROE")
    if not qop and not aop:
        return None
    keep = lambda arr, k: [None if x is None else round(float(x), 1) for x in arr[-k:]]
    debt = next((x for x in reversed(adebt) if x is not None), None)
    roe = next((x for x in reversed(aroe) if x is not None), None)
    return {"q": ql[-6:], "op": keep(qop, 6), "rev": keep(qrev, 6), "ni": keep(qni, 6), "a": al[-3:], "aop": keep(aop, 3),
            "debt": None if debt is None else round(float(debt), 1), "roe": None if roe is None else round(float(roe), 1)}


# ══════════════════════════════════════════════════════════════
# 3축 판정(읽을 때 계산 — 기준을 바꿔도 다시 스캔할 필요 없음)
# ══════════════════════════════════════════════════════════════
def _axis_fin(fin):
    """→ (상태 ok|weak|no|na, 근거 목록, 신호 목록). 최근 분기 영업이익·매출·부채비율."""
    if not fin or not [x for x in (fin.get("op") or []) if x is not None]:
        return "na", ["재무 자료를 받지 못했어요(네이버 재무 없음)."], []
    op = [x for x in (fin.get("op") or []) if x is not None]
    rev = [x for x in (fin.get("rev") or []) if x is not None]
    debt = fin.get("debt")
    notes, sg, pts = [], [], 0
    last, prev = op[-1], (op[-2] if len(op) >= 2 else None)
    q = fin.get("q") or []
    ql = q[-1] if q else "최근 분기"
    if last > 0:
        pts += 1
        notes.append("%s 영업이익 흑자(%s억)" % (ql, format(int(round(last)), ",")))
    else:
        notes.append("%s 영업이익 적자(%s억)" % (ql, format(int(round(last)), ",")))
    up = prev is not None and last > prev
    if up:
        pts += 1
        notes.append("전 분기보다 영업이익이 나아졌어요(%s → %s억)" % (format(int(round(prev)), ","), format(int(round(last)), ",")))
    elif prev is not None:
        notes.append("전 분기보다 영업이익이 줄었어요(%s → %s억)" % (format(int(round(prev)), ","), format(int(round(last)), ",")))
    turn = last > 0 and len(op) >= 2 and min(op[-4:-1]) <= 0
    if turn:
        sg.append("흑자전환")
    elif up:
        sg.append("재무개선")
    if len(rev) >= 2:
        base = rev[-5] if len(rev) >= 5 else rev[-2]
        lab = "전년 동기" if len(rev) >= 5 else "전 분기"
        if rev[-1] >= base > 0:
            pts += 1
            notes.append("매출이 %s보다 늘었어요(%+.1f%%)" % (lab, (rev[-1] / base - 1) * 100))
        elif base > 0:
            notes.append("매출이 %s보다 줄었어요(%+.1f%%)" % (lab, (rev[-1] / base - 1) * 100))
    bad = False
    if len(op) >= 4 and all(x < 0 for x in op[-4:]):
        bad = True
        notes.append("최근 4개 분기 연속 영업적자예요")
    if debt is not None:
        if debt <= 200:
            pts += 1
            notes.append("부채비율 %.0f%% (200%% 이하)" % debt)
        else:
            notes.append("부채비율 %.0f%% — 200%%를 넘어요" % debt)
            if debt > 300:
                bad = True
    else:
        notes.append("부채비율 자료 없음")
    if debt is not None and debt <= 200 and not bad and last > 0 and not turn and not up:
        sg.append("재무양호")
    if bad:
        return "no", notes, [x for x in sg if x != "재무양호"]
    if pts >= 3 and (up or last > 0):
        return "ok", notes, sg
    if pts == 2:
        return "weak", notes, sg
    return "no", notes, sg


def _axis_flow(flow):
    """→ (상태, 근거, 신호, 합계 dict). 5일 vs 이전 15일 외국인·기관 순매수(억원, 수량×종가 근사)."""
    if not flow:
        return "na", ["수급 자료를 받지 못했어요."], [], {}
    f = [x[1] for x in flow]
    i = [x[2] for x in flow]
    f5, i5, f20, i20 = sum(f[-5:]), sum(i[-5:]), sum(f), sum(i)
    recent = f5 + i5
    prior = (f20 + i20) - recent
    sums = {"f5": f5, "i5": i5, "f20": f20, "i20": i20}
    fm = lambda v: "%s%s억" % ("+" if v > 0 else "", format(int(round(v)), ","))
    notes = ["최근 5일 외국인 %s · 기관 %s" % (fm(f5), fm(i5))]
    sg = []
    both = f5 > 0 and i5 > 0
    turn = recent > 0 and prior <= 0 and len(flow) >= 10
    if both:
        sg.append("쌍끌이")
        notes.append("외국인과 기관이 함께 순매수(쌍끌이)")
    if turn:
        sg.append("수급전환")
        notes.append("이전 %d일은 순매도·중립(%s)이었는데 최근 5일은 순매수로 돌아섰어요" % (len(flow) - 5, fm(prior)))
    if recent > 0 and not both and not turn:
        sg.append("수급유입")
        notes.append("한쪽(외국인 또는 기관)만 순매수예요")
    if recent <= 0:
        notes.append("최근 5일 합계가 순매도예요(%s)" % fm(recent))
    if both or turn:
        return "ok", notes, sg, sums
    if recent > 0:
        return "weak", notes, sg, sums
    return "no", notes, sg, sums


def _axis_theme(tk, th):
    """th = 읽어 둔 테마 자료(_build 의 d['th']). → (상태, 근거, 신호, 테마 목록)."""
    names = th["of"].get(tk) or []
    if not names:
        return "na", ["테마 자료가 없어요(📥 수급·테마 가져오기의 테마 가져오기를 먼저 실행하세요)." if not th["has"] else "이 종목은 네이버 테마에 속해 있지 않아요."], [], []
    rows = []
    for nm in names:
        info = th["info"].get(nm) or {}
        peers = [p for p in th["members"].get(nm, ()) if p != tk and p in th["dd"]]
        up = [p for p in peers if th["dd"][p]["above20"]]
        pr = (len(up) / len(peers)) if peers else None
        rows.append({"name": nm, "rate": info.get("rate"), "rise": info.get("rise"), "fall": info.get("fall"), "total": info.get("total"),
                     "peers": len(peers), "peers_up": None if pr is None else round(pr * 100), "hist": th["hist"].get(nm, [])[-10:]})
    rows.sort(key=lambda r: (-(r["rate"] if r["rate"] is not None else -99), r["name"]))
    rows = rows[:3]
    best = rows[0]
    rate = best["rate"]
    pu = best["peers_up"]
    notes = []
    if rate is not None:
        notes.append("‘%s’ 테마 오늘 %+.2f%%%s" % (best["name"], rate, (" (상승 %s · 하락 %s종목)" % (best["rise"], best["fall"])) if best["rise"] is not None else ""))
    if pu is not None:
        notes.append("같은 테마의 낙폭 종목 %d개 중 %d%%가 20일선 위예요" % (best["peers"], pu))
    sg = []
    strong = rate is not None and rate >= 1.0 and (pu is None or pu >= 50)
    weak = (rate is not None and rate > 0) or (pu is not None and pu >= 50)
    if strong:
        sg.append("테마강세")
        return "ok", notes, sg, rows
    if weak:
        if pu is not None and pu >= 50:
            sg.append("테마회복")
        return "weak", notes, sg, rows
    notes.append("테마가 아직 약해요")
    return "no", notes, sg, rows


def _score(r, fin_st, flow_st, theme_st, parts=None):
    """회복 점수 0~100 (낙폭 25 + 재무 25 + 수급 25 + 테마 15 + 가격 안정 10) → (점수, 신호 보탬)."""
    def P(k, v, p):
        if parts is not None:
            parts.append((k, v, p))
    dd = abs(r["dd"])
    p_dd = 25 if dd >= 50 else 20 if dd >= 40 else 15 if dd >= 30 else 8 if dd >= 20 else 0
    P("낙폭(52주 고점 대비)", "%.1f%%" % r["dd"], p_dd)
    p_f = {"ok": 25, "weak": 12}.get(fin_st, 0)
    P("재무 회복", {"ok": "회복 확인", "weak": "일부", "no": "미흡", "na": "자료 없음"}[fin_st], p_f)
    p_w = {"ok": 25, "weak": 10}.get(flow_st, 0)
    P("수급 회복", {"ok": "회복 확인", "weak": "일부", "no": "미흡", "na": "자료 없음"}[flow_st], p_w)
    p_t = {"ok": 15, "weak": 7}.get(theme_st, 0)
    P("테마 회복", {"ok": "회복 확인", "weak": "일부", "no": "미흡", "na": "자료 없음"}[theme_st], p_t)
    p_p, sg = 0, []
    if (r["rebound"] or 0) >= 10:
        p_p += 5
        sg.append("반등시작")
    if r["ma_state"] in ("정배열", "단기상승"):
        p_p += 5
        sg.append("단기추세전환")
    if r["rsi"] is not None and r["rsi"] <= 35:
        sg.append("과매도권")
    P("가격 안정(저점 대비 +10%↑ · 단기 추세)", "저점 대비 %+.1f%% · %s" % (r["rebound"] or 0, r["ma_state"]), p_p)
    return max(0, min(100, p_dd + p_f + p_w + p_t + p_p)), sg


# ══════════════════════════════════════════════════════════════
# 표 만들기(앱이 시작될 때 한 번)
# ══════════════════════════════════════════════════════════════
def _ensure_tables(c, use_pg):
    pk = "SERIAL PRIMARY KEY" if use_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    big = "BIGINT" if use_pg else "INTEGER"
    c.execute(f"CREATE TABLE IF NOT EXISTS challenge_saved_results(id {pk}, save_key TEXT NOT NULL UNIQUE, label TEXT DEFAULT '', items_json TEXT DEFAULT '[]', saved_at TEXT DEFAULT '')")
    c.execute(f"CREATE TABLE IF NOT EXISTS challenge_pick_track(id {pk}, pick_date TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT, market TEXT, theme TEXT, signals TEXT, "
              f"sig_count INTEGER DEFAULT 0, ch_score INTEGER DEFAULT 0, grade TEXT DEFAULT '', pick_price {real}, created_at TEXT DEFAULT '', UNIQUE(pick_date, ticker))")
    c.execute(f"CREATE TABLE IF NOT EXISTS challenge_dd_cache(ticker TEXT PRIMARY KEY, name TEXT, market TEXT, cap_num {big} DEFAULT 0, price {big}, hi52 {big}, "
              f"hi_date TEXT DEFAULT '', lo_after {big}, dd {real}, rebound {real}, rsi {real}, vol_ratio {real}, day_pct {real}, ma_state TEXT DEFAULT '', "
              f"above20 INTEGER DEFAULT 0, price_at TEXT DEFAULT '', chart_json TEXT DEFAULT '', flow_json TEXT DEFAULT '', fin_json TEXT DEFAULT '', "
              f"scanned_at TEXT DEFAULT '', deep_at TEXT DEFAULT '')")
    c.execute(f"CREATE TABLE IF NOT EXISTS challenge_theme_hist(day TEXT NOT NULL, theme TEXT NOT NULL, rate {real}, PRIMARY KEY(day, theme))")


# ══════════════════════════════════════════════════════════════
# 낙폭 스캔(관리자 · 서버 안 백그라운드 스레드 하나)
# ══════════════════════════════════════════════════════════════
def _risk_set():
    """상장폐지·거래정지 위험으로 걸러진 종목: 웹 delist_watch + 원본 delist_snapshots 최신 1건의 danger/warn."""
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


def _last_get():
    try:
        v = setting_get(KEY_LAST, "")
        return json.loads(v) if v else {}
    except Exception:
        return {}


def _today():
    return _now_kst().strftime("%Y-%m-%d")


def _today_scanned():
    try:
        rows = _dbx("SELECT ticker,scanned_at,deep_at FROM challenge_dd_cache", (), fetch=True) or []
    except Exception:
        return set(), set()
    t = _today()
    return ({str(a).upper() for a, b, c in rows if str(b or "")[:10] == t}, {str(a).upper() for a, b, c in rows if str(c or "")[:10] == t})


def _save_dd(batch):
    """batch: [(universe행, 낙폭 dict)] — 지우고 다시 넣되 이미 받아 둔 수급·재무는 남긴다."""
    if not batch:
        return
    old = {}
    try:
        for x in _dbx("SELECT ticker,flow_json,fin_json,deep_at FROM challenge_dd_cache", (), fetch=True) or []:
            old[str(x[0]).upper()] = (x[1] or "", x[2] or "", x[3] or "")
    except Exception:
        pass
    now = _stamp()
    ops = []
    for u, v in batch:
        fj, nj, da = old.get(u["ticker"], ("", "", ""))
        ops.append(("DELETE FROM challenge_dd_cache WHERE ticker=?", (u["ticker"],)))
        ops.append(("INSERT INTO challenge_dd_cache(ticker,name,market,cap_num,price,hi52,hi_date,lo_after,dd,rebound,rsi,vol_ratio,day_pct,ma_state,above20,price_at,"
                    "chart_json,flow_json,fin_json,scanned_at,deep_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (u["ticker"], u["name"], u["market"], int(u["cap"] or 0), v["price"], v["hi52"], v["hi_date"], v["lo_after"], v["dd"], v["rebound"], v["rsi"], v["vol_ratio"],
                     v["day_pct"], v["ma_state"], v["above20"], v["price_at"], json.dumps(v["chart"], ensure_ascii=False, separators=(",", ":")), fj, nj, now, da)))
    for k in range(0, len(ops), 200):
        _run(ops[k:k + 200])


def _save_deep(batch):
    """batch: [(ticker, flow|None, fin|None)] — 받은 것만 고친다."""
    now = _stamp()
    ops = []
    for tk, flow, fin in batch:
        sets, args = [], []
        if flow is not None:
            sets.append("flow_json=?")
            args.append(json.dumps(flow, separators=(",", ":")))
        if fin is not None:
            sets.append("fin_json=?")
            args.append(json.dumps(fin, ensure_ascii=False, separators=(",", ":")))
        if not sets:
            continue
        sets.append("deep_at=?")
        args += [now, tk]
        ops.append(("UPDATE challenge_dd_cache SET " + ",".join(sets) + " WHERE ticker=?", args))
    for k in range(0, len(ops), 200):
        _run(ops[k:k + 200])


def _snap_theme_hist():
    """오늘의 네이버 테마 등락률을 날짜별로 남긴다(테마 흐름 그래프용). 테마 목록이 없으면 건너뜀."""
    try:
        rows = _dbx("SELECT name,change_rate FROM collect_theme_list", (), fetch=True) or []
    except Exception:
        return 0
    if not rows:
        return 0
    day = _today()
    cut = (_now_kst() - timedelta(days=60)).strftime("%Y-%m-%d")
    ops = [("DELETE FROM challenge_theme_hist WHERE day=?", (day,)), ("DELETE FROM challenge_theme_hist WHERE day<?", (cut,))]
    for nm, rate in rows:
        if nm:
            ops.append(("INSERT INTO challenge_theme_hist(day,theme,rate) VALUES(?,?,?)", (day, str(nm)[:80], _fl(rate) or 0.0)))
    for k in range(0, len(ops), 400):
        _run(ops[k:k + 400])
    return len(rows)


def _scan_worker(limit, skip_today):
    try:
        _set(phase="list", msg="① 시가총액 상위 종목 목록 받는 중…")
        uni = _universe(limit)
        if _stopped():
            return _end()
        if not uni:
            return _end("종목 목록을 받지 못했어요. 네이버 응답이 없거나 주소 구조가 바뀌었을 수 있어요.")
        risk = _risk_set()
        uni = [u for u in uni if u["ticker"] not in risk]
        done_p, done_d = _today_scanned() if skip_today else (set(), set())
        todo = [u for u in uni if u["ticker"] not in done_p]
        _set(phase="price", total=len(uni), skip=len(uni) - len(todo), done=len(uni) - len(todo), msg="② 종목별 일봉으로 52주 고점 대비 낙폭 계산 중…")
        buf, aborted, cnt = [], False, {"ok": 0, "n": 0}

        def job1(u):
            if _stopped():
                return u, None, "stop"
            try:
                df = _ohlcv(u["ticker"])
                v = _dd_calc(df) if df is not None and len(df) >= 60 else None
                return u, v, "" if v else "no"
            except Exception as e:
                return u, None, str(e)[:60]

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for u, v, err in ex.map(job1, todo):
                if err == "stop":
                    continue
                with _LOCK:
                    _ST["done"] += 1
                    _ST["cur"] = "%s(%s)" % (u["name"], u["ticker"])
                    if v:
                        _ST["ok"] += 1
                        if v["dd"] <= -DEEP_MIN:
                            _ST["cand"] += 1
                    else:
                        _ST["fail"] += 1
                if v:
                    buf.append((u, v))
                    cnt["ok"] += 1
                else:
                    cnt["n"] += 1
                if len(buf) >= 30:
                    _save_dd(buf)
                    buf = []
                if cnt["ok"] == 0 and cnt["n"] >= 15:
                    _set(stop=True)
                    aborted = True
                    break
        if buf:
            _save_dd(buf)
        if aborted:
            return _end("처음 15개 종목의 일봉을 모두 받지 못해 멈췄어요. 잠시 뒤 다시 시도해 주세요(시세 서버 응답 없음·차단 가능).")
        if _stopped():
            return _end()
        if todo and cnt["ok"] == 0 and len(todo) == len(uni):
            return _end("일봉을 한 종목도 받지 못했어요. 잠시 뒤 다시 시도해 주세요(시세 서버 응답 없음·차단 가능).")
        # ── 낙폭이 큰 종목만 수급·재무 ──
        tick = {u["ticker"] for u in uni}
        try:
            rows = _dbx("SELECT ticker,name,dd FROM challenge_dd_cache WHERE dd<=? ORDER BY dd ASC", (-DEEP_MIN,), fetch=True) or []
        except Exception:
            rows = []
        deep = [{"ticker": str(a).upper(), "name": str(b or "")} for a, b, c in rows if str(a).upper() in tick][:250]
        skip_d = [d for d in deep if d["ticker"] in done_d]
        deep = [d for d in deep if d["ticker"] not in done_d]
        _set(phase="deep", total=len(deep) + len(skip_d), done=len(skip_d), ok=0, fail=0, skip=len(skip_d), cand=len(deep) + len(skip_d),
             msg="③ 낙폭 %d%% 이상 종목 %d개의 수급·재무 받는 중…" % (DEEP_MIN, len(deep) + len(skip_d)))
        buf2 = []

        def job2(d):
            if _stopped():
                return d, None, None, "stop"
            flow = fin = None
            try:
                flow = _flow_calc(_trend(d["ticker"]))
            except Exception:
                flow = None
            try:
                fin = _fin_calc(_finance(d["ticker"], "quarter"), _finance(d["ticker"], "annual"))
            except Exception:
                fin = None
            return d, flow, fin, ""

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for d, flow, fin, err in ex.map(job2, deep):
                if err == "stop":
                    continue
                with _LOCK:
                    _ST["done"] += 1
                    _ST["cur"] = "%s(%s)" % (d["name"], d["ticker"])
                    if flow is not None or fin is not None:
                        _ST["ok"] += 1
                    else:
                        _ST["fail"] += 1
                buf2.append((d["ticker"], flow, fin))
                if len(buf2) >= 20:
                    _save_deep(buf2)
                    buf2 = []
        if buf2:
            _save_deep(buf2)
        stopped = _stopped()
        th_n = 0
        if not stopped:
            _set(phase="theme", msg="④ 테마 등락 기록 남기는 중…")
            th_n = _snap_theme_hist()
        snap = _snapshot()
        res = {"at": _stamp(), "universe": len(uni), "deep": len(deep) + len(skip_d), "deep_ok": snap["ok"], "deep_fail": snap["fail"],
               "limit": limit, "stopped": bool(stopped), "themes": th_n}
        try:
            setting_set(KEY_LAST, json.dumps(res, ensure_ascii=False))
        except Exception as e:
            print("[도전주] 스캔 기록 저장 실패(무시): %s" % e)
        _end("", res)
        if not stopped:
            _set(msg="✅ 낙폭 스캔을 마쳤어요 — 대상 %d종목 중 낙폭 %d%%↑ %d종목의 재무·수급을 받았어요" % (len(uni), DEEP_MIN, len(deep) + len(skip_d)))
    except Exception as e:
        _end("스캔 중 오류: %s" % str(e)[:120])


# ══════════════════════════════════════════════════════════════
# 읽기(30초 캐시) — 표·열이 없어도 오류 없이 빈 결과
# ══════════════════════════════════════════════════════════════
def _load_theme(dd):
    th = {"of": {}, "members": {}, "info": {}, "hist": {}, "dd": dd, "has": False, "days": 0}
    rs, _i = _try(("SELECT ticker,theme FROM stock_theme_map WHERE theme_type='naver'",), ("SELECT ticker,theme FROM stock_theme_map",))
    for x in rs or []:
        t, nm = str(x[0] or "").strip().upper(), _s(x[1], 80)
        if TICKER_RE.match(t) and nm:
            th["of"].setdefault(t, []).append(nm)
            th["members"].setdefault(nm, []).append(t)
    th["has"] = bool(th["of"])
    rs, _i = _try(("SELECT name,change_rate,rise,fall,total FROM collect_theme_list",))
    for x in rs or []:
        th["info"][_s(x[0], 80)] = {"rate": _fl(x[1]), "rise": _n(x[2]), "fall": _n(x[3]), "total": _n(x[4])}
    rs, _i = _try(("SELECT day,theme,rate FROM challenge_theme_hist ORDER BY day",))
    days = set()
    for x in rs or []:
        th["hist"].setdefault(_s(x[1], 80), []).append([str(x[0])[5:10], _fl(x[2]) or 0.0])
        days.add(str(x[0]))
    th["days"] = len(days)
    return th


def _build():
    out = {"rows": [], "by": {}, "risk": set(), "tables": {}, "missing": [], "meta": {}}
    pri, _qi = _try(("SELECT ticker,name,market,cap_num,price,hi52,hi_date,lo_after,dd,rebound,rsi,vol_ratio,day_pct,ma_state,above20,price_at,chart_json,flow_json,fin_json,scanned_at,deep_at "
                     "FROM challenge_dd_cache WHERE price IS NOT NULL AND dd IS NOT NULL",))
    out["tables"]["challenge_dd_cache"] = None if pri is None else len(pri)
    if not pri:
        out["missing"].append("challenge_dd_cache")
        return out
    dd = {}
    for x in pri:
        t = str(x[0] or "").strip().upper()
        if TICKER_RE.match(t):
            dd[t] = {"above20": 1 if _n(x[14]) else 0}
    th = _load_theme(dd)
    out["tables"]["stock_theme_map"] = len(th["of"]) if th["has"] else None
    out["tables"]["collect_theme_list"] = len(th["info"]) if th["info"] else None
    rows, scan_at, asof = [], "", ""
    has_flow = has_fin = False
    for x in pri:
        t = str(x[0] or "").strip().upper()
        price = _fl(x[4])
        if not TICKER_RE.match(t) or price is None:
            continue
        r = {"ticker": t, "name": _s(x[1], 40) or t, "mk": _norm_market(x[2]), "cap": _n(x[3]), "price": int(round(price)), "hi52": _n(x[5]), "hi_date": _s(x[6], 10),
             "lo_after": _n(x[7]), "dd": _fl(x[8]) or 0.0, "rebound": _fl(x[9]) or 0.0, "rsi": _fl(x[10]), "vol": _fl(x[11]), "day_pct": _fl(x[12]),
             "ma_state": _s(x[13], 12), "price_at": _s(x[15], 10), "chart": _jl(x[16], {}), "flow": _jl(x[17], []) or None, "fin": _jl(x[18], {}) or None}
        s_at = str(x[19] or "")[:16]
        if s_at > scan_at:
            scan_at = s_at
        if r["price_at"] > asof:
            asof = r["price_at"]
        r["cand"] = r["dd"] <= -DEEP_MIN
        if r["cand"]:
            has_flow = has_flow or bool(r["flow"])
            has_fin = has_fin or bool(r["fin"])
            fs, fn, fsg = _axis_fin(r["fin"])
            ws, wn, wsg, sums = _axis_flow(r["flow"])
            ts, tn, tsg, trows = _axis_theme(t, th)
            r.update(fin_st=fs, flow_st=ws, theme_st=ts, notes={"fin": fn, "flow": wn, "theme": tn}, sums=sums, themes=trows)
            r["ch"], psg = _score(r, fs, ws, ts)
            r["sg"] = [SENTINEL] + fsg + wsg + tsg + psg
            r["axes"] = sum(1 for z in (fs, ws, ts) if z == "ok")
            r["nsig"] = len(r["sg"])
        rows.append(r)
    out["rows"], out["by"] = rows, {r["ticker"]: r for r in rows}
    out["risk"] = _risk_set()
    out["meta"] = {"universe": len(rows), "cand": sum(1 for r in rows if r["cand"]), "scan_at": scan_at, "price_asof": asof, "has_flow": has_flow, "has_fin": has_fin,
                   "has_theme": th["has"], "theme_days": th["days"], "risk_n": len(out["risk"])}
    return out


_CACHE = {"at": 0.0, "d": None}
_CLOCK = threading.Lock()


def _load(force=False):
    now = time.time()
    with _CLOCK:
        d0 = _CACHE["d"]
        if not force and d0 is not None and now - _CACHE["at"] < (CACHE_TTL if d0["rows"] else 5):
            return d0
    d = _build()
    with _CLOCK:
        _CACHE["d"], _CACHE["at"] = d, now
    return d


def _empty_resp(d):
    return _admin_json({"ok": True, "empty": True, "need": ["challenge_dd_cache"],
                        "msg": "아직 낙폭 스캔 결과가 없어요. 관리자가 [🔎 낙폭 스캔]을 실행하면 52주 고점 대비 많이 떨어진 종목의 재무·수급·테마 회복 신호가 보여요."})


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
    dp = iv("drop_pct", 20, 60)
    dp = min(DROPS, key=lambda x: abs(x - dp))
    sl = iv("scan_limit", 200, 1000)
    sl = min(SCAN_LIMITS, key=lambda x: abs(x - sl))
    return {"markets": list(dict.fromkeys(mk)), "drop_pct": dp, "min_axes": iv("min_axes", 0, 3), "limit": iv("limit", 10, 200), "scan_limit": sl,
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
def _select(d, markets, drop, min_axes, limit, exclude_risk):
    """낙폭 기준 이상 → 위험 종목 제외 → 시장 필터(시장 미상은 둘 다 선택일 때만) → 회복 확인 축 수 → (-점수, -축, 낙폭 큰 순) 정렬 → 상한."""
    mset = set(markets)
    out = []
    for r in d["rows"]:
        if not r["cand"] or r["dd"] > -drop:
            continue
        if exclude_risk and r["ticker"] in d["risk"]:
            continue
        mk = r["mk"]
        if mk in ("KOSPI", "KOSDAQ", "KONEX"):
            if mk not in mset:
                continue
        elif not ("KOSPI" in mset and "KOSDAQ" in mset):
            continue
        if r["axes"] < min_axes:
            continue
        out.append(r)
    out.sort(key=lambda x: (-x["ch"], -x["axes"], x["dd"], x["ticker"]))
    return out[:limit], len(out)


def _pub(r):
    s = r.get("sums") or {}
    fin = r["fin"]
    return {"ticker": r["ticker"], "name": r["name"], "market": r["mk"] if r["mk"] in ("KOSPI", "KOSDAQ") else "", "price": r["price"], "day_pct": r["day_pct"],
            "ch_score": r["ch"], "grade": _grade(r["ch"]), "signals": list(r["sg"]), "sig_count": r["nsig"], "dd": r["dd"], "axes": r["axes"],
            "fin_st": r["fin_st"], "flow_st": r["flow_st"], "theme_st": r["theme_st"],
            "hi52": r["hi52"], "hi_date": r["hi_date"], "lo_after": r["lo_after"], "rebound": r["rebound"], "rsi": r["rsi"], "vol_ratio": r["vol"], "ma_state": r["ma_state"],
            "f5": s.get("f5"), "i5": s.get("i5"), "f20": s.get("f20"), "i20": s.get("i20"), "cap": r["cap"],
            "theme": (r["themes"][0]["name"] if r["themes"] else ""), "fin": fin, "flow": r["flow"], "chart": r["chart"], "themes": r["themes"], "notes": r["notes"],
            "price_at": r["price_at"]}


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
    st = lambda k: (_s(x.get(k), 4) if _s(x.get(k), 4) in ("ok", "weak", "no", "na") else "")
    it = {"ticker": t, "name": _s(x.get("name"), 40) or t, "market": mk if mk in ("KOSPI", "KOSDAQ") else "",
          "price": None if pr is None else int(round(pr)), "day_pct": _fl(x.get("day_pct")), "ch_score": ch, "grade": g if g in GRADES else _grade(ch), "signals": sg,
          "sig_count": max(0, min(30, _n(x.get("sig_count"), len(sg)))), "dd": _fl(x.get("dd")), "axes": max(0, min(3, _n(x.get("axes")))),
          "fin_st": st("fin_st"), "flow_st": st("flow_st"), "theme_st": st("theme_st"),
          "hi52": None if _fl(x.get("hi52")) is None else _n(x.get("hi52")), "rebound": _fl(x.get("rebound")), "rsi": _fl(x.get("rsi")),
          "f5": _fl(x.get("f5")), "i5": _fl(x.get("i5")), "f20": _fl(x.get("f20")), "i20": _fl(x.get("i20")),
          "theme": _s(x.get("theme"), 40), "cap": _n(x.get("cap", x.get("cap_num")))}
    return it


def _grade_cnt(items):
    return {g: sum(1 for i in items if i["grade"] == g) for g in GRADES}


def _list_payload(d, items, matched, q, extra=None):
    locked = []
    ax = {"fin": sum(1 for i in items if i.get("fin_st") == "ok"), "flow": sum(1 for i in items if i.get("flow_st") == "ok"), "theme": sum(1 for i in items if i.get("theme_st") == "ok")}
    if _locked_detail():
        items = [_strip(i) for i in items]
        locked.append("detail")
    out = {"ok": True, "items": items, "matched": matched, "grade_cnt": _grade_cnt(items), "ax_cnt": ax, "q": q, "cfg": get_cfg(),
           "meta": {k: d["meta"][k] for k in ("universe", "cand", "scan_at", "price_asof", "has_flow", "has_fin", "has_theme", "theme_days", "risk_n")}}
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
    """[list] 낙폭 + 회복 신호 목록(저장된 스캔 결과만 사용). 그래프·수치 열은 detail 기능이 잠겨 있으면 뺀다."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _empty_resp(d)
    cfg = get_cfg()
    markets = _markets_from(request.args.get("markets"), cfg["markets"])
    drop = _iarg("drop", 10, 70, cfg["drop_pct"])
    axes = _iarg("axes", 0, 3, cfg["min_axes"])
    top = _iarg("top", 5, 200, cfg["limit"])
    risk = cfg["exclude_risk"]
    sel, matched = _select(d, markets, drop, axes, top, risk)
    q = {"markets": markets, "drop": drop, "axes": axes, "top": top, "exclude_risk": risk}
    return _admin_json(_list_payload(d, [_pub(r) for r in sel], matched, q))


@bp.route("/admin/api/challenge/explain", methods=["GET"])
def api_explain():
    """[detail] 종목 하나의 회복 점수 구성(항목별 가감)과 3축 근거 문장."""
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
        return _admin_json({"error": "낙폭 스캔 결과에 이 종목이 없어요."}, 404)
    if not r["cand"]:
        return _admin_json({"error": "낙폭이 %d%%보다 작아서 회복 점수를 계산하지 않아요." % DEEP_MIN}, 404)
    parts = []
    ch, _sg = _score(r, r["fin_st"], r["flow_st"], r["theme_st"], parts)
    return _admin_json({"ok": True, "ticker": t, "name": r["name"], "total": ch, "grade": _grade(ch), "excluded": t in d["risk"],
                        "parts": [{"k": k, "v": v, "p": round(p, 1)} for k, v, p in parts], "notes": r["notes"], "cut": {"S": 75, "A": 60}})


# ── 낙폭 스캔 시작·진행·멈춤(관리자 전용 — 외부 사이트를 부르는 쓰기 작업) ──
@bp.route("/admin/api/challenge/scan/start", methods=["POST"])
def api_scan_start():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    try:
        limit = int(b.get("limit") or get_cfg()["scan_limit"])
    except Exception:
        limit = DEFAULT_CFG["scan_limit"]
    if limit not in SCAN_LIMITS:
        limit = DEFAULT_CFG["scan_limit"]
    skip = bool(b.get("skip_today", True))
    if not _begin("시작하는 중…"):
        return _admin_json({"ok": False, "error": "이미 낙폭 스캔이 진행 중이에요. 끝나거나 멈춘 뒤 다시 눌러 주세요."})
    _alog("challenge_scan", "limit=%d skip_today=%d" % (limit, int(skip)))
    threading.Thread(target=_scan_worker, args=(limit, skip), daemon=True).start()
    return _admin_json({"ok": True})


@bp.route("/admin/api/challenge/scan/status", methods=["GET"])
def api_scan_status():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    return _admin_json({"ok": True, "job": _snapshot(), "last": _last_get(), "meta": d["meta"], "limits": list(SCAN_LIMITS)})


@bp.route("/admin/api/challenge/scan/stop", methods=["POST"])
def api_scan_stop():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    _set(stop=True)
    _alog("challenge_scan_stop", "")
    return _admin_json({"ok": True})



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
                    "old": bool(its) and not any(isinstance(i, dict) and "dd" in i for i in its[:3])})
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
           "old": bool(raw) and not any(isinstance(i, dict) and "dd" in i for i in raw[:3])}
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
        if SENTINEL not in it["signals"]:
            it["signals"].insert(0, SENTINEL)          # 새 방식(낙폭 회복)으로 저장한 기록의 표시
            it["sig_count"] = len(it["signals"])
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
    label = _s(b.get("label"), 60) or (now.strftime("%Y-%m-%d %H:%M") + f" 낙폭 회복 ({len(items)}종목)")
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


# ── 성과 기록(저장일 가격 대비 최근 스캔 가격) ──
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
    return "75점 이상(S권)" if ch >= 75 else "60~74점(A권)" if ch >= 60 else "60점 미만(B권)"


@bp.route("/admin/api/challenge/track", methods=["GET"])
def api_track():
    """[track] 저장한 기록(낙폭 회복 방식)의 이후 등락. 오늘 저장한 건은 평가를 미룬다(내일부터). 이 표의 값은 이용 결과·수익이 아니다."""
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
        (f"SELECT t.id,t.pick_date,t.ticker,t.name,t.signals,t.sig_count,t.ch_score,t.grade,t.pick_price,COALESCE(d.price,s.price) FROM challenge_pick_track t LEFT JOIN challenge_dd_cache d ON d.ticker=t.ticker LEFT JOIN stock_price_cache s ON s.ticker=t.ticker WHERE {cond}", tuple(args)),
        (f"SELECT t.id,t.pick_date,t.ticker,t.name,t.signals,t.sig_count,t.ch_score,t.grade,t.pick_price,d.price FROM challenge_pick_track t LEFT JOIN challenge_dd_cache d ON d.ticker=t.ticker WHERE {cond}", tuple(args)),
        (f"SELECT t.id,t.pick_date,t.ticker,t.name,t.signals,t.sig_count,t.ch_score,t.grade,t.pick_price,s.price FROM challenge_pick_track t LEFT JOIN stock_price_cache s ON s.ticker=t.ticker WHERE {cond}", tuple(args)),
        (f"SELECT t.id,t.pick_date,t.ticker,t.name,t.signals,t.sig_count,t.ch_score,t.grade,t.pick_price,NULL FROM challenge_pick_track t WHERE {cond}", tuple(args)))
    if rows is None:
        return _admin_json({"ok": True, "empty": True, "need": ["challenge_pick_track"],
                            "msg": "📦 데이터 가져오기 메뉴에서 ‘" + NEED_MSG["challenge_pick_track"] + "’ 표를 가져오면 성과 기록이 보여요. (웹에서 결과를 저장하면 바로 쌓여요)"})
    tot, bg, bs, bsig, bcnt, bdate, recent = _bucket(), {}, {}, {}, {}, {}, []
    skipped_old = 0
    for r in rows:
        sig = str(r[4] or "")
        if SENTINEL not in sig:
            skipped_old += 1                       # 예전 '도전점수' 방식으로 저장된 기록은 뜻이 달라 뺀다
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
                        "skipped_old": skipped_old, "days": days, "limit": limit})


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
CH_DEFAULT = """아래는 오늘({today}) 국내 증시({market_label})에서 '52주 고점 대비 많이 떨어졌지만 재무·수급·테마 중 회복 신호가 보이는' 종목 {count}종목의 데이터입니다.
종목은 회복 점수 순으로 정렬되어 있고, 회복 점수는 '낙폭이 크고 회복 신호가 몇 가지나 확인되는가'를 보여 주는 값이지 사거나 팔아야 한다는 뜻이 아닙니다.
수급은 '순매수 수량 × 종가'로 추정한 근사치이고, 재무는 네이버 증권의 분기·연간 공시 요약입니다.

[낙폭·회복 신호 종목 목록]
{items_text}

[작성 지침 — 반드시 준수]
- 국내 주식 초보 투자자를 위한 정보 정리 글입니다. 위 데이터에 없는 숫자나 사실은 지어내지 마세요.
- 특정 종목의 매수·매도를 권하거나 목표가·수익률을 단정하지 말고, "~로 보입니다", "~할 가능성이 있습니다" 같은 관찰 표현을 쓰세요.
- 마크다운으로 작성하세요. 최상위 섹션은 '## 제목', 하위 항목은 '### 제목', 강조는 **굵게**, 목록은 '- '을 사용합니다. <br> 같은 HTML 태그는 쓰지 마세요.
- '많이 떨어진 종목'은 싸 보여도 더 떨어질 수 있다는 점(떨어지는 칼날)을 글 안에서 반드시 한 번 이상 언급하세요.
- 재무·수급·테마가 '회복 확인'인 이유를 데이터에 있는 항목(분기 영업이익, 5일 수급, 테마 등락 등)만 인용해 쉬운 말로 설명하세요.
- 자료가 없는 항목(자료 없음)은 '확인되지 않았다'고만 쓰고 추측하지 마세요.

[구성 — 순서대로 작성]
## 📉 낙폭 종목의 공통 특징
- 목록 전체의 낙폭 정도, 회복 신호가 몰린 축(재무·수급·테마), 눈에 띄는 테마를 3~4줄로 요약하세요.

## 🔍 회복 신호가 두드러진 종목
목록에서 3~5개를 골라 각각 아래 형식으로 정리하세요.
- **[종목명(코드)]** — 낙폭과 저점 대비 반등폭, 확인된 회복 신호(재무/수급/테마) 1~2줄
- 함께 확인할 점: 낮아진 이유(실적·업황·공시 등 숫자만으로 알 수 없는 부분) 1줄

## 📊 낙폭·회복 점수 읽는 법
- 회복 점수가 낙폭·재무·수급·테마·가격 안정을 합산한 값이라는 점과, 3축 판정이 무엇을 뜻하는지 초보자도 이해하도록 2~3줄로 설명하세요.

## ⚠ 유의사항
이 글은 공개된 시세·수급·재무 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다. 낙폭이 크고 회복 신호가 보여도 이후 주가는 오를 수도 내릴 수도 있고 원금 손실이 생길 수 있습니다. 투자 판단과 책임은 투자자 본인에게 있습니다.

[블로그 제목 후보]
- 위 내용을 블로그에 올릴 때 쓸 제목 3개를 한 줄씩 '- '로 쓰세요. 낙폭·회복 신호 같은 사실 중심으로 쓰고, 매수 권유·수익 보장·"급등" 같은 표현은 쓰지 마세요.
"""

_ST_LBL = {"ok": "회복 확인", "weak": "일부", "no": "미흡", "na": "자료 없음"}


def _eok(v):
    return "자료 없음" if v is None else "%s%s억" % ("+" if v > 0 else "", format(int(round(v)), ","))


def _items_text(rows, with_detail):
    lines = []
    for r in rows:
        it = _pub(r)
        seg = [("- [%s·%d점] %s(%s) %s" % (it["grade"], it["ch_score"], it["name"], it["ticker"], it["market"])).rstrip()]
        pc = it["day_pct"]
        seg.append(("현재가 {:,}원 ({:+.1f}%)".format(it["price"], pc)) if pc is not None else "현재가 {:,}원".format(it["price"]))
        seg.append("52주 고점 대비 %.1f%%" % it["dd"])
        seg.append("회복 신호 %d/3 (재무 %s · 수급 %s · 테마 %s)" % (it["axes"], _ST_LBL[it["fin_st"]], _ST_LBL[it["flow_st"]], _ST_LBL[it["theme_st"]]))
        if with_detail:
            seg.append("52주 고점 %s원(%s) · 고점 이후 저점 %s원 · 저점 대비 %+.1f%% · 20일선 %s" % (format(it["hi52"], ","), it["hi_date"], format(it["lo_after"], ","), it["rebound"], it["ma_state"] or "-"))
            seg.append("RSI %s · 수급(5일) 외국인 %s 기관 %s" % (it["rsi"] if it["rsi"] is not None else "-", _eok(it["f5"]), _eok(it["i5"])))
            for k, lab in (("fin", "재무"), ("flow", "수급"), ("theme", "테마")):
                ns = (it["notes"] or {}).get(k) or []
                if ns:
                    seg.append("%s: %s" % (lab, "; ".join(ns[:3])))
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
        rows = [d["by"][t] for t in dict.fromkeys(tks) if t in d["by"] and d["by"][t]["cand"] and not (cfg["exclude_risk"] and t in d["risk"])]
    else:
        markets = _markets_from(request.args.get("markets"), cfg["markets"])
        rows, _m = _select(d, markets, _iarg("drop", 10, 70, cfg["drop_pct"]), _iarg("axes", 0, 3, cfg["min_axes"]), _iarg("top", 3, 30, 20), cfg["exclude_risk"])
    if not rows:
        return _admin_json({"error": "조건에 맞는 종목이 없어서 프롬프트를 만들 수 없어요."}, 400)
    have_mk = {r["mk"] for r in rows}
    mks = [x for x in ("KOSPI", "KOSDAQ") if x in have_mk]
    label = "·".join("코스피" if m == "KOSPI" else "코스닥" for m in mks) or "국내증시"
    body = prompt_get("challenge_ai") or CH_DEFAULT
    for k, v in (("{items_text}", _items_text(rows, not _locked_detail())), ("{today}", _now_kst().strftime("%Y-%m-%d")), ("{market_label}", label), ("{count}", str(len(rows)))):
        body = body.replace(k, v)
    return _admin_json({"ok": True, "prompt": body, "n": len(rows), "label": "%s %d종목" % (label, len(rows))})


# ══════════════════════════════════════════════════════════════
# 관리자 전용 — AI 분석 저장 · 블로그 글 만들기 (어떤 기능에도 등록하지 않음 → 회원 화면에서는 404)
# 흐름: 낙폭회복 리스트 → AI 분석(수동: 프롬프트 복사 → 답변 붙여넣기) → 대시보드 이미지(브라우저 캔버스) → 블로그 글(HTML)
# ══════════════════════════════════════════════════════════════
def _ai_get():
    try:
        v = setting_get(KEY_AI, "")
        d = json.loads(v) if v else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@bp.route("/admin/api/challenge/ai", methods=["GET"])
def api_ai_get():
    """마지막으로 저장한 AI 분석. 오늘 날짜가 아니면 stale=true(오래된 분석이라 새로 받도록 안내)."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _ai_get()
    text = str(d.get("text") or "")
    if not text.strip():
        return _admin_json({"ok": True, "found": False})
    day = str(d.get("date") or "")
    return _admin_json({"ok": True, "found": True, "text": text, "label": str(d.get("label") or ""), "date": day, "at": str(d.get("at") or ""),
                        "tickers": [t for t in (d.get("tickers") or []) if isinstance(t, str)][:60], "stale": day != _today()})


@bp.route("/admin/api/challenge/ai", methods=["POST"])
def api_ai_save():
    """관리자 전용 — AI 답변을 저장한다(블로그 글·이미지가 이 글을 가져다 쓴다). 서버가 AI를 부르지는 않는다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    text = str(b.get("text") or "").replace("\x00", "").strip()[:20000]
    if len(text) < 100:
        return _admin_json({"error": "AI 답변(100자 이상)이 필요해요."}, 400)
    tks = [t for t in (str(x).strip().upper() for x in (b.get("tickers") or []) if isinstance(x, str)) if TICKER_RE.match(t)][:60]
    now = _now_kst()
    rec = {"date": now.strftime("%Y-%m-%d"), "at": now.strftime("%Y-%m-%d %H:%M:%S"), "label": _s(b.get("label"), 80), "text": text, "tickers": tks}
    setting_set(KEY_AI, json.dumps(rec, ensure_ascii=False))
    _alog("challenge_ai_save", "len=%d tickers=%d" % (len(text), len(tks)))
    return _admin_json({"ok": True, "date": rec["date"], "at": rec["at"], "len": len(text)})


_ST_EMO = {"ok": "&#9989;", "weak": "&#128312;", "no": "&#10060;", "na": "&#9898;"}
_ST_NAME = {"ok": "회복 확인", "weak": "일부", "no": "미흡", "na": "자료 없음"}
_TITLE_BLOCK = re.compile(r"^[ \t]*\[블로그\s*제목\s*후보[^\]]*\][ \t]*\n(?:[ \t]*(?:[-•*·]|\d+[.)])[ \t]*.+\n?)*", re.M)


def _split_ai(text):
    """AI 답변 → (블로그 제목 후보 블록을 뺀 본문, 제목 후보 목록)."""
    text = str(text or "").replace("\r", "")
    titles = B.extract_titles(text)
    return _TITLE_BLOCK.sub("", text).strip(), titles


def _pct(v, d=1):
    return "-" if v is None else "%+.*f%%" % (d, v)


def _pick_rows(d, b):
    """블로그 글에 쓸 종목: 화면에 보이던 종목(tickers)이 있으면 그대로(위험 제외 설정 존중), 없으면 기본 기준으로 고른다."""
    cfg = get_cfg()
    tks = [t for t in (str(x).strip().upper() for x in (b.get("tickers") or []) if isinstance(x, str)) if TICKER_RE.match(t)]
    if tks:
        return [d["by"][t] for t in dict.fromkeys(tks) if t in d["by"] and d["by"][t]["cand"] and not (cfg["exclude_risk"] and t in d["risk"])][:30]
    sel, _m = _select(d, cfg["markets"], cfg["drop_pct"], cfg["min_axes"], 30, cfg["exclude_risk"])
    return sel


def _blog_build(items, meta, ai_text, inc, title, n):
    today = _now_kst().strftime("%Y-%m-%d")
    cnt = len(items)
    asof = str(meta.get("price_asof") or "-")
    avg_dd = sum(i["dd"] for i in items) / cnt if cnt else 0
    avg_sc = round(sum(i["ch_score"] for i in items) / cnt) if cnt else 0
    sa = sum(1 for i in items if i["grade"] in ("S", "A"))
    all3 = sum(1 for i in items if i["axes"] >= 3)
    okc = {k: sum(1 for i in items if i[k + "_st"] == "ok") for k in ("fin", "flow", "theme")}
    ai_body, titles = _split_ai(ai_text) if (ai_text or "").strip() else ("", [])
    auto_title = "📉 낙폭 큰 종목 중 회복 신호 %d선 (%s) | 재무·수급·테마 점검 | 3축 모두 확인 %d개" % (cnt, today, all3)
    title = title or (titles[0] if titles else auto_title)
    names = [i["name"] for i in items[:15]]
    tags, tag_html = B.hashtags(names, today, extra=["낙폭과대주", "낙폭회복", "회복신호", "도전주"])
    E = B.E
    h = [B.seo_box(auto_title, "52주 고점에서 크게 떨어진 종목 가운데 재무·수급·테마가 다시 살아나는 신호가 있는지 점검해 정리했어요. 매수 추천이 아닌 참고 정보예요.",
                   ["낙폭과대주", "낙폭회복", "회복신호", "재무개선", "수급전환"] + names[:3]),
         B.head_box("★ DROP & RECOVERY · %s" % today, '낙폭 큰 종목의 <span style="color:%s;">회복 신호 %d선</span>' % (B.GOLD, cnt), "52주 고점 대비 낙폭 · 재무 · 수급 · 테마 점검 · 시세 기준일 %s" % E(asof))]
    if inc.get("stats"):
        def cell(label, val, c):
            return ('<td align="center" style="padding:10px 4px;background-color:#f8faff;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;margin-bottom:3px;">%s</div>'
                    '<div style="font-size:19px;font-weight:900;color:%s;">%s</div></td>' % (label, c, val))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:14px 0;' + B.FONT + '"><tr>'
                 + cell("&#128201; 후보", "%d개" % cnt, "#111827") + cell("평균 낙폭", _pct(avg_dd), "#2563eb") + cell("평균 점수", "%d점" % avg_sc, "#4f46e5")
                 + cell("S·A급", "%d개" % sa, "#dc2626") + cell("&#128185; 재무", "%d개" % okc["fin"], "#16a34a") + cell("&#128176; 수급", "%d개" % okc["flow"], "#16a34a")
                 + cell("&#128293; 테마", "%d개" % okc["theme"], "#16a34a") + "</tr></table>")
    if inc.get("axes") and cnt:
        rows = ""
        for k, lab in (("fin", "&#128185; 재무"), ("flow", "&#128176; 수급"), ("theme", "&#128293; 테마")):
            c = {s: sum(1 for i in items if i[k + "_st"] == s) for s in ("ok", "weak", "no", "na")}
            rows += ('<tr><td width="16%%" style="padding:6px 4px;font-size:13px;font-weight:800;color:#111827;white-space:nowrap;">%s</td><td width="34%%" style="padding:6px 4px;">%s</td>'
                     '<td style="padding:6px 4px;font-size:12px;color:#475569;">회복 확인 <b>%d</b> · 일부 %d · 미흡 %d · 자료 없음 %d</td></tr>'
                     % (lab, B.bar(round(c["ok"] * 100 / cnt), "#4f46e5"), c["ok"], c["weak"], c["no"], c["na"]))
        h.append(B.side_title("&#128300; 재무·수급·테마 회복 신호 현황", "#4f46e5") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '">' + rows + "</table>")
    if inc.get("top") and cnt:
        trs = ""
        for i in items[:10]:
            c = B.tone(i["ch_score"])
            trs += ('<tr><td width="34%%" style="padding:6px 4px;font-size:13px;font-weight:800;color:#111827;">%s</td><td width="36%%" style="padding:6px 4px;">%s</td>'
                    '<td width="16%%" align="right" style="padding:6px 4px;font-size:12.5px;font-weight:800;color:#2563eb;white-space:nowrap;">%s</td>'
                    '<td width="14%%" align="right" style="padding:6px 4px;font-size:13px;font-weight:900;color:%s;white-space:nowrap;">%d</td></tr>' % (B.nlink(i["ticker"], E(i["name"])), B.bar(i["ch_score"], c), _pct(i["dd"]), c, i["ch_score"]))
        h.append(B.side_title("&#127942; 회복 점수 TOP 10", "#d97706") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '">' + trs + "</table>")
    if inc.get("ai") and ai_body:
        h.append(B.side_title("&#129302; AI 분석", "#0d1b3e"))
        h.append(B.link_names(B.ai_to_html(ai_body), [(i["name"], i["ticker"]) for i in items]))
    if inc.get("list") and cnt:
        trs = ""
        for k, i in enumerate(items[:n], 1):
            sc = B.tone(i["ch_score"])
            trs += ('<tr><td width="6%%" align="center" style="padding:7px 2px;border-bottom:1px solid #eef2f7;font-size:12px;color:#64748b;">%d</td>'
                    '<td width="32%%" style="padding:7px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:800;color:#111827;">%s<div style="font-size:11px;font-weight:400;color:#94a3b8;">%s %s</div></td>'
                    '<td width="14%%" align="right" style="padding:7px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:900;color:%s;white-space:nowrap;">%d<span style="font-size:11px;color:#64748b;"> %s</span></td>'
                    '<td width="14%%" align="right" style="padding:7px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:800;color:#2563eb;white-space:nowrap;">%s</td>'
                    '<td width="15%%" align="right" style="padding:7px 4px;border-bottom:1px solid #eef2f7;font-size:12.5px;color:#c62828;white-space:nowrap;">%s</td>'
                    '<td width="19%%" align="center" style="padding:7px 2px;border-bottom:1px solid #eef2f7;font-size:14px;white-space:nowrap;">%s%s%s</td></tr>'
                    % (k, B.nlink(i["ticker"], E(i["name"])), E(i["ticker"]), E(i["market"]), sc, i["ch_score"], E(i["grade"]), _pct(i["dd"]), _pct(i["rebound"]) if i["rebound"] is not None else "-",
                       _ST_EMO.get(i["fin_st"], ""), _ST_EMO.get(i["flow_st"], ""), _ST_EMO.get(i["theme_st"], "")))
        wd = (6, 32, 14, 14, 15, 19)
        head = "".join('<th width="%d%%" style="padding:7px 2px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">%s</th>' % (w_, x)
                       for w_, x in zip(wd, ("#", "종목", "점수", "낙폭", "저점대비", "재무·수급·테마")))
        h.append(B.side_title("&#128203; 낙폭 회복 후보 TOP %d" % min(n, cnt), "#2563eb") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '"><tr>' + head + "</tr>" + trs + "</table>")
        h.append('<p style="font-size:11.5px;color:#9ca3af;margin:6px 0 0;">낙폭은 52주 고점 대비, 저점 대비는 고점 이후 최저가 대비 반등폭이에요. &#9989; 회복 확인 · &#128312; 일부 · &#10060; 미흡 · &#9898; 자료 없음. 회복 점수는 신호가 몇 가지 확인되는지 보여 줄 뿐 오른다는 뜻이 아니에요.</p>')
    if inc.get("notes") and cnt:
        blocks = ""
        for i in items[:5]:
            ns = i.get("notes") or {}
            lines = "".join('<div style="font-size:12.5px;color:#374151;line-height:1.8;">&#9642; <b>%s</b> (%s): %s</div>' % (lab, _ST_NAME.get(i[k + "_st"], ""), E("; ".join((ns.get(k) or [])[:3]) or "표시할 근거가 없어요"))
                            for k, lab in (("fin", "재무"), ("flow", "수급"), ("theme", "테마")))
            blocks += ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:10px 0;' + B.FONT + '"><tr><td bgcolor="#f8faff" style="background-color:#f8faff;padding:11px 14px;border:1px solid #e5e7eb;border-left:5px solid #4f46e5;">'
                       '<div style="font-size:14px;font-weight:900;color:#111827;margin-bottom:4px;">%s <span style="font-size:11.5px;font-weight:600;color:#94a3b8;">%s · 낙폭 %s · %d점</span></div>%s</td></tr></table>' % (B.nlink(i["ticker"], E(i["name"])), E(i["ticker"]), _pct(i["dd"]), i["ch_score"], lines))
        h.append(B.side_title("&#128270; 회복 근거 (상위 5종목)", "#0891b2") + blocks)
    h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border:2px solid #d97706;border-collapse:collapse;margin:14px 0 4px;' + B.FONT + '"><tr><td bgcolor="#fffbeb" style="background-color:#fffbeb;padding:12px 16px;">'
             '<div style="font-size:13px;font-weight:900;color:#92400e;">&#9888;&#65039; 많이 떨어진 종목은 더 떨어질 수 있어요</div><div style="font-size:12.5px;color:#92400e;line-height:1.85;margin-top:4px;">'
             '고점 대비 낙폭이 크면 싸 보이지만, 실적 악화·업황 부진·공시 같은 이유가 있을 수 있고 회복 신호가 나타난 뒤에도 다시 내려갈 수 있습니다(떨어지는 칼날). '
             '수급은 &lsquo;순매수 수량×종가&rsquo;로 추정한 근사치이며, 재무는 네이버 증권 요약이라 최신 공시와 차이가 있을 수 있어요. 반드시 공시 원문으로 직접 확인해 주세요.</div></td></tr></table>')
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/challenge/blog", methods=["POST"])
def api_blog():
    """관리자 전용 — 화면에 보이던 종목과 저장한 AI 분석으로 블로그용 HTML 글을 만든다(서버가 글을 올리지는 않아요)."""
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["rows"]:
        return _admin_json({"error": "낙폭 스캔 결과가 없어요. 먼저 [🔎 낙폭 스캔]을 실행하세요."}, 404)
    b = _json_body() or {}
    rows = _pick_rows(d, b)
    if not rows:
        return _admin_json({"error": "조건에 맞는 종목이 없어요."}, 404)
    inc = b.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k in BLOG_SECS} if isinstance(inc, dict) else {k: True for k in BLOG_SECS}
    try:
        n = max(5, min(30, int(b.get("n") or 20)))
    except Exception:
        n = 20
    ai = str(b.get("ai") or "")[:20000]
    out = _blog_build([_pub(r) for r in rows], d["meta"], ai, inc, _s(b.get("title"), 150), n)
    pseudo = "D" + _now_kst().strftime("%y%m%d")
    logs, warn = B.dup_info(pseudo, "challenge")
    out.update({"ticker": pseudo, "name": "도전주 낙폭회복 " + _today(), "dups": logs, "dup_warn": warn})
    return _admin_json(out)


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
    rows = [r for r in d["rows"] if r["cand"]]
    return {"ok": True, "tables": d["tables"], "meta": d["meta"], "missing": d["missing"], "cfg": get_cfg(), "last": _last_get(),
            "axes": {"fin": sum(1 for r in rows if r["fin_st"] == "ok"), "flow": sum(1 for r in rows if r["flow_st"] == "ok"), "theme": sum(1 for r in rows if r["theme_st"] == "ok")},
            "na": {"fin": sum(1 for r in rows if r["fin_st"] == "na"), "flow": sum(1 for r in rows if r["flow_st"] == "na"), "theme": sum(1 for r in rows if r["theme_st"] == "na")},
            "grades": {g: sum(1 for r in rows if _grade(r["ch"]) == g) for g in GRADES}, "no_market": sum(1 for r in d["rows"] if r["mk"] not in ("KOSPI", "KOSDAQ")),
            "cache_age": int(time.time() - _CACHE["at"]) if _CACHE["d"] is not None else None}


@bp.route("/admin/api/challenge/diag", methods=["GET"])
def api_diag():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_diag(_load()))


@bp.route("/admin/api/challenge/reload", methods=["POST"])
def api_reload():
    """읽어 둔 표를 비우고 다시 읽는다(스캔을 새로 마친 직후 바로 보고 싶을 때)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _load(force=True)
    _alog("challenge_reload", "rows=%d" % len(d["rows"]))
    return _admin_json(_diag(d))


# ══════════════════════════════════════════════════════════════
# 화면(관리자 탭 = 이용자 /m/challenge 와 같은 JS)
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var CH={sec:'list',css:false,cfg:null,tbl:null,ex:{},open:{},
 ld:{market:'all',drop:'30',axes:'1',top:'60',sortk:'ch_score',view:'card',data:null,seq:0,sort:{col:'ch_score',asc:false},inited:false,sel:{},busy:false,refs:{},was:false,tm:0,job:null},
 sv:{list:null,cur:null,seq:0},tr:{days:'30',limit:'60',data:null,seq:0},ai:{text:'',date:'',old:null},flag:{img:false,blog:false,posted:false},_chain:0,imgPanel:null,blogPanel:null};
var CH_SECS=[['list','① 📉 낙폭 회복 후보','list'],['ai','② 🤖 AI 분석','ai'],['img','③ 🖼 대시보드 이미지','img'],['blog','④ 📝 블로그 쓰기','blog'],['saved','📂 보관함','saved'],['track','📈 성과 기록','track'],['guide','📘 기준 설명','guide']];
var CH_ST={ok:['✅','회복 확인','#15803d','#dcfce7'],weak:['🔸','일부 회복','#b45309','#fffbeb'],no:['❌','미흡','#64748b','#f1f5f9'],na:['⚪','자료 없음','#94a3b8','#f8fafc']};
var CH_SIG={'낙폭회복':['📉','#eef2ff','#4338ca','52주 고점 대비 크게 떨어진 종목 중 회복 신호를 점검한 목록'],'재무개선':['💹','#fef2f2','#dc2626','최근 분기 영업이익이 전 분기보다 나아졌어요'],'흑자전환':['🔄','#fef2f2','#b91c1c','최근 분기에 영업이익이 흑자로 돌아섰어요'],
 '재무양호':['🏦','#f0f9ff','#0369a1','영업이익 흑자이고 부채비율이 200% 이하예요'],'수급전환':['🔁','#ccfbf1','#0f766e','이전에는 순매도·중립이었는데 최근 5일은 순매수로 전환'],'쌍끌이':['🟢','#dcfce7','#15803d','외국인과 기관이 5일 동안 함께 순매수'],
 '수급유입':['💰','#ecfdf5','#047857','외국인 또는 기관이 5일 동안 순매수'],'테마강세':['🔥','#fff7ed','#c2410c','속한 테마가 오늘 +1% 이상이고 동료 종목도 20일선 위에 있어요'],'테마회복':['🌱','#f7fee7','#4d7c0f','같은 테마 낙폭 종목의 절반 이상이 20일선을 되찾았어요'],
 '반등시작':['↗','#fefce8','#a16207','고점 이후 저점 대비 10% 이상 올라왔어요'],'단기추세전환':['📶','#eff6ff','#1d4ed8','주가가 5일·20일선 위로 올라선 단기 상승 구간'],'과매도권':['🌊','#f0f9ff','#0369a1','RSI 35 이하 — 많이 눌린 구간']};
var CH_CSS='.chHd{padding:14px 16px}.chHd h2{margin:0 0 4px;font-size:18px}.chSt{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0}'+
'.chCh{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;background:#f1f5f9;color:#334155;border:1px solid #e2e8f0;white-space:nowrap}'+
'.chCh.a{background:#eef2ff;color:#4338ca;border-color:#c7d2fe}.chCh.w{background:#fffbeb;color:#b45309;border-color:#fcd34d}.chCh.g{background:#f8fafc;color:#64748b}'+
'.chNav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 8px}.chNav button{border:1.5px solid #cbd5e1;background:#fff;color:#334155;border-radius:999px;padding:7px 13px;font:inherit;font-size:13px;font-weight:700;cursor:pointer}'+
'.chNav button.chOn{background:#4338ca;border-color:#4338ca;color:#fff}'+
'.chW{overflow-x:auto;-webkit-overflow-scrolling:touch}.chT{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}.chT th{background:#eef2ff;white-space:nowrap}.chT th.chSrt{cursor:pointer}.chT td{word-break:keep-all;vertical-align:middle}'+
'.chT td.r,.chT th.r{text-align:right;white-space:nowrap}.chT tr.chDt td{background:#f8fafc}.chT .nm{font-weight:800;color:#0f172a}.chT .sb{font-size:11px;color:#94a3b8;margin-top:1px}.chT tr.chSelR td{background:#f5f3ff}'+
'.chUp{color:#e11d48;font-weight:700}.chDn{color:#2563eb;font-weight:700}.chZ{color:#94a3b8}.chSc{font-size:16px;font-weight:900;color:#0f172a}'+
'.chGr{display:inline-block;color:#fff;font-size:10.5px;font-weight:900;padding:2px 7px;border-radius:5px;margin-left:4px}'+
'.chSg{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 6px;border-radius:5px;margin:0 3px 3px 0;white-space:nowrap}'+
'.chBd{display:inline-block;font-size:11px;font-weight:800;padding:2px 7px;border-radius:999px;margin:0 4px 3px 0;white-space:nowrap;border:1px solid #e2e8f0}'+
'.chL{display:inline-flex;flex-direction:column;gap:2px;font-size:11.5px;color:#64748b}.chL select{min-width:92px}'+
'.chCards{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:10px;margin:8px 0}.chCard{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px}.chCard.chSelC{border-color:#4338ca;background:#f5f3ff}'+
'.chTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}.chTile{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px}.chTile .l{font-size:12px;color:#64748b;font-weight:700}.chTile .v{font-size:22px;font-weight:900;color:#0f172a;margin-top:2px}.chTile .s{font-size:11px;color:#94a3b8}'+
'.chKv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}.chKv div{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px;font-size:12.5px}.chKv b{display:block;font-size:11.5px;color:#64748b;margin-bottom:2px}'+
'.chAiOut{white-space:pre-wrap;word-break:break-word;font-size:13.5px;line-height:1.65;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin-top:8px}'+
'.chAiOut .h2{display:block;font-weight:900;color:#fff;background:#4338ca;border-radius:8px;padding:5px 10px;margin:10px 0 4px}.chAiOut .h3{display:block;font-weight:800;border-left:5px solid #4338ca;padding-left:8px;margin:8px 0 2px}'+
'.chGd h4{margin:12px 0 4px;font-size:14px}.chGd p,.chGd li{font-size:13px;line-height:1.65;color:#334155;margin:3px 0}.chGd ul{margin:4px 0 4px 18px;padding:0}'+
'.chCard2{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:8px 0}.chCard2 h3{margin:0 0 4px;font-size:16px}'+
'.chSvg{display:block;width:100%;height:auto}.chGx{margin:8px 0 2px}.chGx3{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin-top:8px}'+
'.chAx{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px}.chAxH{display:flex;justify-content:space-between;align-items:center;gap:6px;font-size:13px;font-weight:800;color:#0f172a;margin-bottom:4px}'+
'.chAx ul{margin:4px 0 0 16px;padding:0}.chAx li{font-size:11.5px;color:#475569;line-height:1.5}.chLg{font-size:11px;color:#64748b;margin-top:2px}.chLg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 3px 0 6px;vertical-align:-1px}'+
'.chPg{height:10px;border-radius:6px;background:#e2e8f0;overflow:hidden;margin:6px 0}.chPg>div{height:100%;background:#4338ca;width:0}'+
'.chStp{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}.chStp button{flex:1 1 170px;display:flex;align-items:center;gap:10px;text-align:left;border:1.5px solid #c7d2fe;background:#fff;color:#312e81;border-radius:14px;padding:9px 12px;font:inherit;font-size:13.5px;font-weight:800;cursor:pointer;line-height:1.35}'+
'.chStp button small{display:block;font-weight:600;font-size:11.5px;color:#64748b}.chStp .n{width:26px;height:26px;border-radius:50%;background:#c7d2fe;color:#312e81;display:flex;align-items:center;justify-content:center;font-weight:900;flex:0 0 auto}'+
'.chStp .done{border-color:#86efac;background:#f0fdf4}.chStp .done .n{background:#16a34a;color:#fff}.chStp .cur{border-color:#4f46e5;box-shadow:0 0 0 3px rgba(79,70,229,.18)}'+
'.chPan{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;margin-top:10px}.chImgG{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-top:8px}'+
'@media(max-width:520px){.chT{font-size:12px}.chT td,.chT th{padding:6px 6px}.chTile .v{font-size:19px}.chHd{padding:12px}.chL select{min-width:84px}.chCards{grid-template-columns:1fr}}';
function chCss(){if(CH.css)return;CH.css=true;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';
 var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=CH_CSS;document.head.appendChild(s)}
function chN(v,d){if(v==null||isNaN(v))return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d,minimumFractionDigits:d==null?0:d})}
function chEok(v){if(v==null||isNaN(v))return '-';var a=Math.abs(v),s=v<0?'-':'';if(a>=10000)return s+(a/10000).toFixed(1)+'조';return s+Math.round(a).toLocaleString('ko-KR')+'억'}
function chFe(v){if(v==null||isNaN(v))return '-';v=Number(v);return (v>0?'+':'')+Math.round(v).toLocaleString('ko-KR')+'억'}
function chCls(v){return v>0?'chUp':(v<0?'chDn':'chZ')}
function chPct(v,d){if(v==null||isNaN(v))return '-';return (v>0?'+':'')+Number(v).toFixed(d==null?2:d)+'%'}
function chTk(node,t){if(typeof window.GoStock==='function'||typeof window.__openTicker==='function'){node.className=(node.className?node.className+' ':'')+'tkl';node.setAttribute('data-tk',t);node.title='눌러서 종목분석·심층분석 열기'}return node}
function chQ(o){var a=[];Object.keys(o).forEach(function(k){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]))});return a.join('&')}
function chSel(bar,lbl,obj,key,opts,fn){var l=el('label','chL');l.appendChild(el('span',null,lbl));var s=el('select');opts.forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];s.appendChild(op)});s.value=obj[key];s.onchange=function(){obj[key]=s.value;if(fn)fn()};l.appendChild(s);bar.appendChild(l);return s}
function chGrade(g){var c={S:'#4f46e5',A:'#0891b2',B:'#64748b'}[g]||'#94a3b8';var x=el('span','chGr',(g||'-')+'급');x.style.background=c;return x}
function chSigs(list){var w=document.createDocumentFragment();(list||[]).forEach(function(s){var m=CH_SIG[s];var x=el('span','chSg',(m?m[0]+' ':'')+s);x.style.background=m?m[1]:'#eee';x.style.color=m?m[2]:'#555';if(m)x.title=m[3];w.appendChild(x)});if(!(list||[]).length)w.appendChild(el('span','chZ','-'));return w}
function chBadge(lbl,st,long){var m=CH_ST[st]||CH_ST.na;var x=el('span','chBd',m[0]+' '+lbl+(long?' '+m[1]:''));x.style.background=m[3];x.style.color=m[2];x.title=lbl+': '+m[1];return x}
function chAxes(it){var w=document.createDocumentFragment();w.appendChild(chBadge('재무',it.fin_st||'na'));w.appendChild(chBadge('수급',it.flow_st||'na'));w.appendChild(chBadge('테마',it.theme_st||'na'));return w}
function chTblBuild(heads,aligns){var w=el('div','chW'),t=el('table','chT'),h=el('tr');heads.forEach(function(x,i){h.appendChild(el('th',aligns&&aligns[i]==='r'?'r':'',x))});t.appendChild(h);w.appendChild(t);return {wrap:w,t:t,h:h}}
function chEmpty(box,j){var c=el('div','chCard2');c.appendChild(el('b',null,'📉 아직 보여 줄 자료가 없어요'));NeedNote(c,j.msg,'관리자가 [🔎 낙폭 스캔]을 실행하면 보여요.');
 var a=el('div','bar');a.appendChild(bt('🔎 낙폭 스캔 시작','bt',function(){chScanStart()}));c.appendChild(adm(a));box.appendChild(c)}
function chPlace(box,fid,txt){var c=el('div','chCard2');c.appendChild(el('b',null,txt||'이 기능은 잠겨 있어요'));c.appendChild(el('p','note','등급이 열리면 이 자리에 내용이 나타나요. 위 안내를 눌러 자세히 확인해 보세요.'));
 var sk=el('div');sk.style.cssText='height:90px;background:repeating-linear-gradient(90deg,#f1f5f9 0 40px,#e2e8f0 40px 42px);border-radius:10px';c.appendChild(sk);box.appendChild(c);ftSec(box,fid)}
function chDetailOk(j){return ftOk('detail')&&!(j&&j.locked&&j.locked.indexOf('detail')>=0)}
function chErr(o,msg){if(!o)return;o.innerHTML='';o.appendChild(el('p','note bad','⚠ '+msg))}

/* ── 그래프(SVG, 서버가 준 숫자만 그림) ── */
function chSv(w,h){var s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('viewBox','0 0 '+w+' '+h);s.setAttribute('class','chSvg');s.setAttribute('role','img');return s}
function chSe(p,tag,a,txt){var e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(var k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;p.appendChild(e);return e}
function chPriceSvg(it){var c=it.chart;if(!c||!c.c||c.c.length<2)return null;var W=340,H=150,L=6,R=62,T=16,B=22,n=c.c.length,vals=c.c.slice();(c.m||[]).forEach(function(v){if(v!=null)vals.push(v)});
 var hi=it.hi52||Math.max.apply(null,c.c),mx=Math.max.apply(null,vals.concat([hi])),mn=Math.min.apply(null,vals);if(mx===mn){mx+=1;mn-=1}
 var X=function(i){return L+(W-L-R)*i/(n-1)},Y=function(v){return T+(H-T-B)*(1-(v-mn)/(mx-mn))};var s=chSv(W,H);
 chSe(s,'line',{x1:L,x2:W-R,y1:Y(hi),y2:Y(hi),stroke:'#fca5a5','stroke-dasharray':'3 3'});
 var pts=c.c.map(function(v,i){return X(i).toFixed(1)+','+Y(v).toFixed(1)}).join(' ');
 chSe(s,'polygon',{points:X(0).toFixed(1)+','+(H-B)+' '+pts+' '+X(n-1).toFixed(1)+','+(H-B),fill:'#e0e7ff',opacity:'0.55'});
 var d='',pen=false;(c.m||[]).forEach(function(v,i){if(v==null){pen=false;return}d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' ';pen=true});
 if(d)chSe(s,'path',{d:d,fill:'none',stroke:'#f59e0b','stroke-width':'1.4','stroke-dasharray':'4 3'});
 chSe(s,'polyline',{points:pts,fill:'none',stroke:'#334155','stroke-width':'1.8','stroke-linejoin':'round'});
 var hx=X(c.hi),hy=Y(c.c[c.hi]),lx=X(c.lo),ly=Y(c.c[c.lo]),ex=X(n-1),ey=Y(c.c[n-1]);
 chSe(s,'circle',{cx:hx,cy:hy,r:'3.6',fill:'#dc2626'});chSe(s,'text',{x:Math.max(26,Math.min(hx,W-R-30)),y:Math.max(10,hy-6),'font-size':'10','text-anchor':'middle',fill:'#dc2626','font-weight':'700'},'고점 '+(c.dh||'').slice(5));
 if(c.lo!==c.hi&&c.lo<n-1){chSe(s,'circle',{cx:lx,cy:ly,r:'3.6',fill:'#2563eb'});chSe(s,'text',{x:Math.max(16,Math.min(lx,W-R-16)),y:Math.min(H-B-3,ly+13),'font-size':'10','text-anchor':'middle',fill:'#2563eb','font-weight':'700'},'저점')}
 chSe(s,'circle',{cx:ex,cy:ey,r:'3.6',fill:'#0f172a'});chSe(s,'line',{x1:W-R+4,x2:W-R+4,y1:Y(hi),y2:ey,stroke:'#dc2626','stroke-width':'1.5'});
 chSe(s,'text',{x:W-R+9,y:(Y(hi)+ey)/2+3,'font-size':'11','font-weight':'800',fill:'#2563eb'},chPct(it.dd,1));
 chSe(s,'text',{x:W-R+9,y:Math.max(12,ey-5),'font-size':'10',fill:'#0f172a'},chN(it.price)+'원');
 chSe(s,'text',{x:L,y:H-6,'font-size':'10',fill:'#94a3b8'},(c.d0||'').slice(2));chSe(s,'text',{x:W-R,y:H-6,'font-size':'10','text-anchor':'end',fill:'#94a3b8'},(c.d1||'').slice(2));
 chSe(s,'text',{x:W-R-4,y:T-4,'font-size':'10','text-anchor':'end',fill:'#f59e0b'},'┅ 20일선');return s}
function chFinSvg(it){var f=it.fin;if(!f||!f.op||!f.op.length)return null;var W=340,H=130,L=6,R=6,T=16,B=22,op=f.op,n=op.length,mx=1;op.forEach(function(v){if(v!=null)mx=Math.max(mx,Math.abs(v))});
 var s=chSv(W,H),zy=T+(H-T-B)/2,half=(H-T-B)/2-8,bw=(W-L-R)/n;chSe(s,'line',{x1:L,x2:W-R,y1:zy,y2:zy,stroke:'#94a3b8'});
 op.forEach(function(v,i){if(v==null)return;var h=Math.abs(v)/mx*half,x=L+bw*i+bw*0.18,w=bw*0.64;chSe(s,'rect',{x:x,y:v>=0?zy-h:zy,width:w,height:Math.max(h,1),fill:v>=0?'#dc2626':'#2563eb',opacity:i===n-1?'1':'0.55'});
  chSe(s,'text',{x:x+w/2,y:v>=0?zy-h-3:zy+h+11,'font-size':'10','text-anchor':'middle',fill:'#334155','font-weight':i===n-1?'800':'500'},chEok(v));
  chSe(s,'text',{x:x+w/2,y:H-6,'font-size':'10','text-anchor':'middle',fill:'#94a3b8'},(f.q&&f.q[i]||'').slice(2))});return s}
function chFlowSvg(it){var f=it.flow;if(!f||!f.length)return null;var W=340,H=130,L=6,R=6,T=14,B=22,n=f.length,mx=1;f.forEach(function(r){mx=Math.max(mx,Math.abs(r[1]),Math.abs(r[2]))});
 var s=chSv(W,H),zy=T+(H-T-B)/2,half=(H-T-B)/2-2,bw=(W-L-R)/n,b0=Math.max(0,n-5);
 chSe(s,'rect',{x:L+bw*b0,y:T-8,width:bw*(n-b0),height:H-T-B+10,fill:'#eef2ff'});chSe(s,'text',{x:L+bw*b0+2,y:T,'font-size':'9',fill:'#4338ca','font-weight':'700'},'최근 5일');
 chSe(s,'line',{x1:L,x2:W-R,y1:zy,y2:zy,stroke:'#94a3b8'});
 f.forEach(function(r,i){var x=L+bw*i;[[1,'#7c3aed'],[2,'#ea580c']].forEach(function(z,k){var v=r[z[0]],h=Math.abs(v)/mx*half;chSe(s,'rect',{x:x+bw*0.08+k*bw*0.42,y:v>=0?zy-h:zy,width:bw*0.4,height:Math.max(h,0.6),fill:z[1]})})});
 chSe(s,'text',{x:L,y:H-6,'font-size':'10',fill:'#94a3b8'},f[0][0]);chSe(s,'text',{x:W-R,y:H-6,'font-size':'10','text-anchor':'end',fill:'#94a3b8'},f[n-1][0]);
 chSe(s,'text',{x:L,y:T-2,'font-size':'9',fill:'#94a3b8'},'일별 순매수(억) ±'+Math.round(mx));return s}
function chThemeSvg(it){var th=it.themes;if(!th||!th.length)return null;var W=340,rh=24,T=6,H=T+rh*th.length+6,s=chSv(W,H),cx=200,mx=3;th.forEach(function(t){if(t.rate!=null)mx=Math.max(mx,Math.abs(t.rate))});
 chSe(s,'line',{x1:cx,x2:cx,y1:T-2,y2:H-4,stroke:'#cbd5e1'});
 th.forEach(function(t,i){var y=T+rh*i,nm=String(t.name||'');if(nm.length>11)nm=nm.slice(0,10)+'…';chSe(s,'text',{x:4,y:y+15,'font-size':'11',fill:'#334155','font-weight':i===0?'800':'500'},nm);
  var r=t.rate==null?0:t.rate,w=Math.abs(r)/mx*(W-cx-48);chSe(s,'rect',{x:r>=0?cx:cx-w,y:y+4,width:Math.max(w,1),height:14,fill:r>=0?'#e11d48':'#2563eb',opacity:'0.8'});
  chSe(s,'text',{x:W-4,y:y+15,'font-size':'11','text-anchor':'end',fill:'#0f172a','font-weight':'800'},t.rate==null?'-':chPct(t.rate,2))});
 return s}
function chSparkSvg(h){if(!h||h.length<2)return null;var W=340,H=46,L=6,R=40,T=8,B=14,n=h.length,mx=0,mn=0;h.forEach(function(p){mx=Math.max(mx,p[1]);mn=Math.min(mn,p[1])});if(mx===mn){mx+=1;mn-=1}
 var X=function(i){return L+(W-L-R)*i/(n-1)},Y=function(v){return T+(H-T-B)*(1-(v-mn)/(mx-mn))},s=chSv(W,H);chSe(s,'line',{x1:L,x2:W-R,y1:Y(0),y2:Y(0),stroke:'#cbd5e1'});
 chSe(s,'polyline',{points:h.map(function(p,i){return X(i).toFixed(1)+','+Y(p[1]).toFixed(1)}).join(' '),fill:'none',stroke:'#c2410c','stroke-width':'1.8'});
 chSe(s,'text',{x:L,y:H-2,'font-size':'9',fill:'#94a3b8'},h[0][0]);chSe(s,'text',{x:W-R,y:H-2,'font-size':'9','text-anchor':'end',fill:'#94a3b8'},h[n-1][0]);
 chSe(s,'text',{x:W-R+4,y:Y(h[n-1][1])+3,'font-size':'10',fill:'#c2410c','font-weight':'800'},chPct(h[n-1][1],1));return s}
function chAxPanel(title,st,svg,notes,extra){var d=el('div','chAx'),h=el('div','chAxH');h.appendChild(el('span',null,title));h.appendChild(chBadge('',st,true));d.appendChild(h);
 if(svg)d.appendChild(svg);else d.appendChild(el('p','note','그래프를 그릴 자료가 없어요.'));if(extra)d.appendChild(extra);
 var ul=el('ul');(notes||[]).slice(0,5).forEach(function(x){ul.appendChild(el('li',null,x))});if((notes||[]).length)d.appendChild(ul);return d}
function chLegend(items){var l=el('div','chLg');items.forEach(function(z){var i=el('i');i.style.background=z[0];l.appendChild(i);l.appendChild(document.createTextNode(z[1]))});return l}
function chGraphBox(it){var g=el('div','chGx'),ps=chPriceSvg(it);
 if(!ps){g.appendChild(el('p','note','🔒 그래프와 상세 수치는 잠겨 있어요.'));return g}
 var pb=el('div','chAx'),ph=el('div','chAxH');ph.appendChild(el('span',null,'📉 가격 — 52주 고점에서 지금까지'));pb.appendChild(ph);pb.appendChild(el('div','m','고점 '+chN(it.hi52)+'원 → 저점 '+chN(it.lo_after)+'원 → 현재 '+chN(it.price)+'원'));pb.appendChild(ps);
 pb.appendChild(el('p','note','고점 대비 '+chPct(it.dd,1)+' · 저점 대비 '+chPct(it.rebound,1)+' 반등 · 20일선: '+(it.ma_state||'-')+(it.rsi!=null?' · RSI '+chN(it.rsi,0):'')));g.appendChild(pb);
 var n=it.notes||{},f3=el('div','chGx3');
 f3.appendChild(chAxPanel('💹 재무 — 분기 영업이익(억)',it.fin_st||'na',chFinSvg(it),n.fin,it.fin&&it.fin.debt!=null?el('div','chLg','연간 기준 부채비율 '+chN(it.fin.debt,0)+'%'+(it.fin.roe!=null?' · ROE '+chN(it.fin.roe,1)+'%':'')):null));
 f3.appendChild(chAxPanel('💰 수급 — 20일 외국인·기관',it.flow_st||'na',chFlowSvg(it),n.flow,chLegend([['#7c3aed','외국인'],['#ea580c','기관']])));
 var tp=chThemeSvg(it),ex=null;if(it.themes&&it.themes[0]){var sp=chSparkSvg(it.themes[0].hist);if(sp){ex=el('div');ex.appendChild(el('div','chLg','‘'+it.themes[0].name+'’ 테마 등락률 흐름(스캔한 날짜별)'));ex.appendChild(sp)}}
 f3.appendChild(chAxPanel('🔥 테마 — 오늘 등락(%)',it.theme_st||'na',tp,n.theme,ex));g.appendChild(f3);return g}

/* ── 표 내보내기·이미지(기능 'exp') ── */
function chSetTbl(title,cols,items,asof){CH.tbl={title:title,asof:asof||'',head:cols.map(function(c){return c.h}),num:cols.map(function(c){return !!c.num}),
 raw:items.map(function(it){return cols.map(function(c){return c.raw(it)})}),disp:items.map(function(it){return cols.map(function(c){var r=c.raw(it);return c.disp?c.disp(it,r):String(r==null?'':r)})})}}
function chDl(blob,name){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href)},4000)}
function chStamp(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())}
function chCsv(){var T=CH.tbl;if(!T||!T.raw.length){toast('내려받을 표가 아직 없어요. 먼저 조회해 주세요.');return}
 function q(x,num){if(x==null)return '';var s=String(x);if(!num&&/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'}
 var L=[T.head.map(function(h){return q(h)}).join(',')];T.raw.forEach(function(r){L.push(r.map(function(x,i){return q(x,T.num[i])}).join(','))});
 L.push('');L.push(q('기준 '+(T.asof||'-')+' · 52주 고점 대비 낙폭과 재무·수급·테마 회복 신호를 정리한 목록(정보)이며 투자 권유가 아닙니다'));
 chDl(new Blob(['﻿'+L.join('\r\n')],{type:'text/csv;charset=utf-8'}),'낙폭회복_'+chStamp()+'.csv');toast('CSV 파일을 내려받았어요')}
function chPng(){var T=CH.tbl;if(!T||!T.disp.length){toast('내려받을 표가 아직 없어요. 먼저 조회해 주세요.');return}
 var rows=T.disp.slice(0,30),cw=T.head.map(function(h,i){return i===0?(T.head[0]==='#'?44:200):(T.num[i]?96:130)}),W=cw.reduce(function(a,b){return a+b},0)+40;W=Math.max(W,640);var rh=34,H=130+rows.length*rh+70,S=2;
 var cv=document.createElement('canvas');cv.width=W*S;cv.height=H*S;var c=cv.getContext('2d');c.scale(S,S);var F="'Malgun Gothic','Apple SD Gothic Neo',sans-serif";
 c.fillStyle='#f8fafc';c.fillRect(0,0,W,H);c.fillStyle='#4338ca';c.fillRect(0,0,W,70);c.fillStyle='#fff';c.font='800 22px '+F;c.fillText('📉 '+T.title,20,32);c.font='600 13px '+F;c.fillText('기준 '+(T.asof||'-')+' · 52주 고점 대비 낙폭과 회복 신호 목록(정보)',20,56);
 var y=96;c.fillStyle='#e0e7ff';c.fillRect(20,y-22,W-40,30);c.fillStyle='#334155';c.font='800 13px '+F;var x=20;T.head.forEach(function(h,i){c.textAlign=T.num[i]?'right':'left';c.fillText(h,T.num[i]?x+cw[i]-8:x+8,y);x+=cw[i]});
 rows.forEach(function(r,ri){y+=rh;if(ri%2===1){c.fillStyle='#f1f5f9';c.fillRect(20,y-22,W-40,rh)}x=20;r.forEach(function(v,i){c.fillStyle='#0f172a';c.font=(i===1?'800 ':'600 ')+'13px '+F;c.textAlign=T.num[i]?'right':'left';
  var s=String(v);var mx=cw[i]-14;while(s.length>1&&c.measureText(s).width>mx)s=s.slice(0,-2)+'…';c.fillText(s,T.num[i]?x+cw[i]-8:x+8,y);x+=cw[i]})});
 c.textAlign='left';c.fillStyle='#64748b';c.font='600 12px '+F;c.fillText('공개된 시세·수급·재무 자료를 기준에 따라 정리한 정보 제공용이며 특정 종목의 매수·매도 권유가 아닙니다. 낙폭이 커도 더 떨어질 수 있어요.',20,H-30);
 c.fillText('투자 판단과 책임은 이용자 본인에게 있습니다.',20,H-12);
 try{cv.toBlob(function(b){if(!b){toast('이미지를 만들지 못했어요');return}chDl(b,'낙폭회복_'+chStamp()+'.png');toast('이미지를 내려받았어요')},'image/png')}catch(e){toast('이미지를 만들지 못했어요')}}
function chExpBar(parent){var r=el('div','bar');r.appendChild(ft(bt('📄 표 내려받기(CSV)','bt3',chCsv),'exp'));r.appendChild(ft(bt('🖼 이미지 내려받기','bt3',chPng),'exp'));
 r.appendChild(el('span','m','지금 보이는 표를 파일로 가져가요'));parent.appendChild(r)}

/* ── 위쪽 틀 ── */
function chLoad(p){chCss();p.innerHTML='';
 var hd=el('div','c chHd');hd.appendChild(el('h2',null,'🎯 도전주 — 낙폭 회복 후보'));hd.appendChild(el('div','m',(MEMBER_MODE?'① 낙폭 회복 후보 → ② AI 분석 → ③ 대시보드 이미지. ':'① 낙폭 회복 후보 → ② AI 분석 → ③ 대시보드 이미지 → ④ 글 만들기 → ⑤ 블로그에 쓰기. ')+'52주 고점 대비 크게 떨어진 종목 가운데, 재무·수급·테마가 다시 살아나고 있는 종목을 그래프와 함께 보여 줘요. 종목을 추천하는 화면이 아니라 회복 신호가 보이는 낙폭 종목 목록(정보)이에요. 많이 떨어진 종목은 더 떨어질 수도 있어요. 투자 권유가 아니며 판단과 책임은 이용자 본인에게 있어요.'));
 var sb=el('div');sb.id='chSum';hd.appendChild(sb);p.appendChild(hd);
 var sp=el('div','chStp');sp.id='chSteps';p.appendChild(sp);var nv=el('div','chNav');nv.id='chNav';p.appendChild(nv);var bd=el('div');bd.id='chBody';p.appendChild(bd);
 p.appendChild(el('p','note','※ 낙폭·가격은 관리자가 마지막으로 스캔한 일봉 기준이고(오늘보다 앞설 수 있어요), 수급은 최근 20거래일 ‘순매수 수량×종가’ 근사치, 재무는 네이버 증권 분기·연간 요약이에요. 회복 점수는 신호가 몇 가지 확인되는지 보여 줄 뿐 오른다는 뜻이 아니며, 이후 주가는 오를 수도 내릴 수도 있어요. 이 화면은 정보 제공용이며 특정 종목의 매수·매도 권유가 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다.'));
 var ad=el('div','c');ad.id='chAdm';p.appendChild(adm(ad));
 if(MEMBER_MODE&&CH.sec==='blog')CH.sec='list';chNavDraw();chShow();chSteps();if(!MEMBER_MODE){chAdmLoad();chPoll(true);chAiLoad()}}
function chNavDraw(){var n=$('chNav');if(!n)return;n.innerHTML='';CH_SECS.forEach(function(s){if(MEMBER_MODE&&s[0]==='blog')return;var b=el('button',CH.sec===s[0]?'chOn':'',(ftOk(s[2])?'':'🔒 ')+s[1]);b.type='button';b.onclick=function(){chGo(s[0])};n.appendChild(b)})}
/* ── 단계 바(① 낙폭회복 리스트 → ② AI 분석 → ③ 대시보드 이미지 → ④ 블로그 쓰기) + 자동/수동 진행([⚙ 설정]의 단계 진행 방식) ── */
var CHFLOW=['ai','img','blog','post'];
function chItems(){var j=CH.ld.data;return (j&&j.items)||[]}
function chPickItems(){var all=chItems(),sel=CH.ld.sel||{};var a=all.filter(function(x){return sel[x.ticker]});return (a.length?a:all).slice(0,30)}
function chDate(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+'-'+z(d.getMonth()+1)+'-'+z(d.getDate())}
function chListQ(){var S=CH.ld;return S.inited?{markets:S.market==='all'?'KOSPI,KOSDAQ':S.market,drop:S.drop,axes:S.axes,top:S.top}:{}}
/* 목록이 아직 없으면(이미지·블로그 탭을 먼저 연 경우) 지금 기준으로 한 번 불러온다 */
function chEnsureP(){if(chItems().length)return Promise.resolve(chPickItems());
 return api('/admin/api/challenge/list?'+chQ(chListQ())).then(function(j){if(j.error)throw new Error(j.error);if(j.empty)throw new Error(j.msg||'낙폭 스캔 결과가 없어요. 관리자가 [🔎 낙폭 스캔]을 실행하면 보여요.');chListSet(j);if(!chItems().length)throw new Error('조건에 맞는 종목이 없어요.');return chPickItems()})}
function chSteps(){var sp=$('chSteps');if(!sp)return;var n=chItems().length,has=n>0,ai=!!(CH.ai.text&&CH.ai.text.trim()),F=CH.flag;
 var steps=[{t:'낙폭회복 리스트',sub:has?(n+'종목 · 완료'):'조회하세요',done:has,go:function(){chStepRun('list')}},
  {t:'AI 분석',sub:ai?'완료 · 다시 만들기':'눌러서 시작',done:ai,go:function(){chStepRun('ai')}},
  {t:MEMBER_MODE?'요약 이미지':'이미지 만들기',sub:F.img?'만들었어요 · 다시 만들기':'눌러서 만들기',done:F.img,go:function(){chStepRun('img')}},
  {t:'글 만들기',sub:F.blog?'완료 · 다시 만들기':'눌러서 만들기',done:F.blog,hide:MEMBER_MODE,go:function(){chStepRun('blog')}},
  {t:'블로그에 쓰기',sub:F.posted?'복사·열기 완료':(F.blog?'복사하고 블로그 열기':'글을 먼저 만드세요'),done:F.posted,off:!F.blog,hide:MEMBER_MODE,go:function(){chStepRun('post')}}];
 window.FlowBar.draw(sp,{steps:steps,runAll:MEMBER_MODE?null:function(){chStepRun('all')},note:MEMBER_MODE?'':'[⚡ 블로그까지 한 번에]는 AI 분석 → 이미지 → 글 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 블로그 글쓰기 화면에 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'})}
function chStepRun(id){
 if(id==='list'){chGo('list');return}
 if(!chItems().length&&CH.sec==='list'){toast('먼저 ① 낙폭 회복 후보를 조회해 주세요');return}
 if(id==='ai'){if(!ftOk('ai')){lockDlg('ai');return}chGo('ai');chAiRun();return}
 if(id==='img'){if(!ftOk('img')){lockDlg('img');return}if(MEMBER_MODE){chGo('img');if(CH.memGo&&!CH.memGo.disabled)CH.memGo.click();return}CH.flag.img=false;if(window.MiniFlow)MiniFlow.go('challenge',CHFLOW,CHACTS,'img');else{chGo('img')}return}
 if(MEMBER_MODE)return;
 if(id==='blog'){CH.flag.blog=false;if(window.MiniFlow)MiniFlow.go('challenge',CHFLOW,CHACTS,'blog');else{chGo('blog')}return}
 if(id==='post'){chPostGo(false);return}
 if(id==='all'){if(!window.MiniFlow)return;toast('⚡ 블로그까지 이어서 진행해요');MiniFlow.force('challenge',CHFLOW,CHACTS)}}
/* 블로그 글이 만들어져 있으면 복사하고 블로그 글쓰기 화면을 연다(자동 단계에서는 브라우저가 복사·새 창을 막으면 안내만 하고, 직접 한 번 누르면 돼요) */
function chPostGo(auto){var P=CH.blogPanel;if(CH.sec==='blog'&&P&&P.built()){P.copyOpen(auto);return true}
 if(!CH.flag.blog){if(!auto)toast('먼저 ④ 글 만들기를 해 주세요');return false}
 chGo('blog');var k=0,t=setInterval(function(){var Q=CH.blogPanel;if(Q&&Q.built()){clearInterval(t);Q.copyOpen(auto)}else if(++k>40)clearInterval(t)},250);return true}
var CHACTS={
 ai:function(next){if(!chItems().length)return;if((CH.ai.text||'').trim()){next();return}if(!ftOk('ai'))return;chGo('ai');chAiRun()},
 img:function(next){if(CH.flag.img){next();return}chEnsureP().then(function(){chGo('img');if(!CH.imgPanel)return;return CH.imgPanel.gen(true).then(function(){if(CH.imgPanel&&CH.imgPanel.items())next()})}).catch(function(){})},
 blog:function(next){if(CH.flag.blog&&CH.sec==='blog'&&CH.blogPanel&&CH.blogPanel.built()){next();return}chEnsureP().then(function(){CH.flag.blog=false;chGo('blog');if(!CH.blogPanel)return;return CH.blogPanel.rebuild().then(function(j){if(j&&!j.error)next()})}).catch(function(){})},
 post:function(next){if(chPostGo(true))next()}};
function chGo(sec){CH.sec=sec;chNavDraw();chShow()}
function chShow(){var b=$('chBody');if(!b)return;b.innerHTML='';var box=el('div');b.appendChild(box);
 var m={list:chSecList,saved:chSecSaved,track:chSecTrack,ai:chSecAi,img:chSecImg,blog:chSecBlog,guide:chSecGuide}[CH.sec],fid=CH_SECS.filter(function(s){return s[0]===CH.sec})[0][2];
 if(!ftOk(fid)){var f=FEATS&&FEATS[fid];chPlace(box,fid,'🔒 '+(f?f.label:'잠긴 기능'));return}m(box)}
function chStatus(j){var b=$('chSum');if(!b)return;b.innerHTML='';if(!j||j.empty||!j.meta)return;var m=j.meta,st=el('div','chSt');
 st.appendChild(el('span','chCh a','🔎 스캔 '+(m.scan_at||'알 수 없음')));st.appendChild(el('span','chCh','시세 기준일 '+(m.price_asof||'-')));st.appendChild(el('span','chCh','스캔 '+chN(m.universe)+'종목 · 낙폭 20%↑ '+chN(m.cand)+'종목'));
 if(!m.has_fin)st.appendChild(el('span','chCh w','재무 자료 없음 — 재무 축은 판정 못 해요'));if(!m.has_flow)st.appendChild(el('span','chCh w','수급 자료 없음 — 수급 축은 판정 못 해요'));
 if(!m.has_theme)st.appendChild(el('span','chCh w','테마 자료 없음 — 테마 축은 판정 못 해요'));else if(m.theme_days<2)st.appendChild(el('span','chCh g','테마 흐름 그래프는 스캔이 2일 이상 쌓이면 그려져요'));
 if(m.risk_n&&j.q&&j.q.exclude_risk)st.appendChild(el('span','chCh g','상장폐지·거래정지 위험 '+m.risk_n+'종목은 제외'));b.appendChild(st)}

/* ── 낙폭 스캔(관리자) ── */
function chScanCard(){var c=el('div','c');c.id='chScanCard';return c}
function chScanDraw(s){var c=$('chScanCard');if(!c)return;c.innerHTML='';var job=s&&s.job||{},run=!!job.running;c.appendChild(el('b',null,'🔎 낙폭 스캔 (관리자만 보여요)'));
 c.appendChild(el('p','note','시총 상위 종목의 일봉으로 52주 고점 대비 낙폭을 계산하고, 낙폭 20% 이상 종목의 수급·재무를 받아 와요. 동전주·시총 미달·상장폐지 위험 종목은 빠져요. 종목 수에 따라 몇 분 걸리고, 멈춰도 받은 자료는 남아요. 테마는 📥 수급·테마 가져오기에서 받은 값을 읽어요.'));
 var bar=el('div','bar'),cfg=CH.cfg||{scan_limit:400};CH.scanSel=CH.scanSel||String(cfg.scan_limit||400);var o={v:CH.scanSel};
 chSel(bar,'스캔 대상(시총 순)',o,'v',[['200','200종목(빠름)'],['400','400종목(기본)'],['600','600종목'],['1000','1000종목(오래 걸려요)']],function(){CH.scanSel=o.v});
 var lb=el('label');lb.style.fontSize='12.5px';var ck=el('input');ck.type='checkbox';ck.checked=CH.scanSkip!==false;ck.onchange=function(){CH.scanSkip=ck.checked};lb.appendChild(ck);lb.appendChild(document.createTextNode(' 오늘 이미 받은 종목은 건너뛰기(이어서 하기)'));bar.appendChild(lb);
 var b1=bt(run?'⏳ 스캔 중…':'🔎 낙폭 스캔 시작','bt',function(){chScanStart()});b1.id='chScanBtn';b1.disabled=run;bar.appendChild(b1);
 var b2=bt('⏹ 멈춤','bt3',function(){apiJ('/admin/api/challenge/scan/stop',{}).then(function(){toast('멈추는 중이에요');chPoll(true)})});b2.disabled=!run;bar.appendChild(b2);c.appendChild(bar);
 if(run||job.phase==='end'){var pct=job.total?Math.min(100,Math.round(job.done/job.total*100)):0;var pg=el('div','chPg'),in_=el('div');in_.style.width=pct+'%';pg.appendChild(in_);c.appendChild(pg);
  c.appendChild(el('p','note',(job.msg||'')+(run?' · '+job.done+'/'+job.total+' ('+pct+'%) · 성공 '+job.ok+' · 실패 '+job.fail+(job.skip?' · 건너뜀 '+job.skip:'')+(job.cur?' · '+job.cur:'')+' · '+job.elapsed+'초':'')));
  if(job.error)c.appendChild(el('p','note bad','⚠ '+job.error))}
 var l=s&&s.last;if(l&&l.at)c.appendChild(el('p','note','마지막 스캔 '+l.at+' · 대상 '+l.universe+'종목 · 낙폭 20%↑ '+l.deep+'종목(수급·재무 성공 '+l.deep_ok+' · 실패 '+l.deep_fail+')'+(l.stopped?' · 도중에 멈춤':'')))}
function chScanStart(){apiJ('/admin/api/challenge/scan/start',{limit:Number(CH.scanSel||(CH.cfg&&CH.cfg.scan_limit)||400),skip_today:CH.scanSkip!==false}).then(function(r){if(r.error){toast(r.error);return}if(r.ok===false){toast(r.error||'시작하지 못했어요');return}toast('낙폭 스캔을 시작했어요');CH.ld.was=true;chPoll(true)}).catch(function(){toast('시작하지 못했어요.')})}
function chPoll(now){var S=CH.ld;if(S.tm){clearTimeout(S.tm);S.tm=0}
 var go=function(){S.tm=0;if(!$('chScanCard')&&!$('chAdm'))return;api('/admin/api/challenge/scan/status').then(function(s){if(s.error)return;CH.stat=s;var run=s.job&&s.job.running;chScanDraw(s);
  if(run){S.was=true;S.tm=setTimeout(go,2000)}else if(S.was){S.was=false;var bad=!!(s.job&&s.job.error);toast(bad?'스캔이 끝나지 않았어요':'낙폭 스캔이 끝났어요');S.data=null;CH.ex={};if(!bad){CH.ai.text='';CH.ai.date='';CH.flag={img:false,blog:false,posted:false};CH._chain=1}chSteps();
   if(CH.sec==='list'){chListGo(false)}else if(!bad){chEnsureP().catch(function(){})}chAdmLoad()}}).catch(function(){})};
 if(now)go();else S.tm=setTimeout(go,2000)}

/* ── 후보 목록(기능 'list') + 그래프·상세(기능 'detail') ── */
function chSecList(box){var S=CH.ld;box.appendChild(el('p','note','52주 고점 대비 낙폭이 기준 이상인 종목 가운데 재무·수급·테마의 회복 신호를 점검해 회복 점수 순으로 보여 줘요. 각 축은 ✅회복 확인 · 🔸일부 · ❌미흡 · ⚪자료 없음이에요. 카드의 그래프로 고점에서 얼마나 빠졌고 지금 어디쯤인지 한눈에 볼 수 있어요.'));
 var bar=el('div','bar');var go=function(){chListGo(false)};
 S.refs.market=chSel(bar,'시장',S,'market',[['all','코스피+코스닥'],['KOSPI','코스피'],['KOSDAQ','코스닥']],go);
 S.refs.drop=chSel(bar,'낙폭 기준',S,'drop',[['20','-20% 이상'],['25','-25%'],['30','-30% (기본)'],['40','-40%'],['50','-50%'],['60','-60% 이상']],go);
 S.refs.axes=chSel(bar,'회복 확인 축',S,'axes',[['0','전체(0개↑)'],['1','1개↑'],['2','2개↑'],['3','3개 모두']],go);
 S.refs.top=chSel(bar,'보여줄 개수',S,'top',[['20','20개'],['40','40개'],['60','60개'],['120','120개'],['200','200개']],go);
 chSel(bar,'정렬',S,'sortk',[['ch_score','회복 점수 높은 순'],['dd','낙폭 큰 순'],['rebound','저점 대비 반등 큰 순'],['day_pct','등락률 높은 순']],function(){S.sort={col:S.sortk,asc:S.sortk==='dd'};chListDraw()});
 chSel(bar,'보기',S,'view',[['card','카드(그래프)'],['table','표']],function(){chListDraw()});
 bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);
 var sc=chScanCard();box.appendChild(adm(sc));if(CH.stat)chScanDraw(CH.stat);
 var ab=el('div','bar');ab.appendChild(bt('💾 결과 저장','bt',chSave));ab.appendChild(el('span','m','관리자만 보여요 · 저장하면 보관함과 성과 기록에 쌓여요'));box.appendChild(adm(ab));
 var sb=el('div','bar');sb.id='chSelBar';box.appendChild(sb);
 var out=el('div');out.id='chOut';box.appendChild(out);if(S.data)chListDraw();else chListGo(true)}
function chListGo(first){var S=CH.ld,out=$('chOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 var q=first&&!S.inited?{}:{markets:S.market==='all'?'KOSPI,KOSDAQ':S.market,drop:S.drop,axes:S.axes,top:S.top};
 api('/admin/api/challenge/list?'+chQ(q)).then(function(j){if(my!==S.seq)return;var o=$('chOut');if(!o)return;if(j.error){chErr(o,j.error);return}chListSet(j)}).catch(function(){chErr($('chOut'),'불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.')})}
function chListSet(j){var S=CH.ld;S.data=j;CH.ex={};CH.open={};
 if(!S.inited&&j.q){S.inited=true;S.market=j.q.markets.length===2?'all':j.q.markets[0];S.drop=String(j.q.drop);S.axes=String(j.q.axes);S.top=String(Math.min(200,j.q.top));CH.cfg=j.cfg;
  var ok=function(sel,v){if(sel){sel.value=v;if(sel.value!==v){var op=el('option',null,v);op.value=v;sel.appendChild(op);sel.value=v}}};ok(S.refs.market,S.market);ok(S.refs.drop,S.drop);ok(S.refs.axes,S.axes);ok(S.refs.top,S.top)}
 var o=$('chOut');if(o)chListDraw();chSteps();
 if(CH._chain&&j.items&&j.items.length){CH._chain=0;if(!MEMBER_MODE&&window.MiniFlow)MiniFlow.run('challenge',CHFLOW,CHACTS)}}
function chSorted(items){var s=CH.ld.sort,col=s.col;var a=items.map(function(it,i){return [it,i]});
 a.sort(function(x,y){var u=x[0][col],v=y[0][col];if(u==null||u==='')u=s.asc?Infinity:-Infinity;if(v==null||v==='')v=s.asc?Infinity:-Infinity;var d=u<v?-1:(u>v?1:0);if(d===0)return x[1]-y[1];return s.asc?d:-d});return a.map(function(z){return z[0]})}
function chSortBy(col){var s=CH.ld.sort;if(s.col===col)s.asc=!s.asc;else{s.col=col;s.asc=(col==='dd')}chListDraw()}
function chSelCount(){return Object.keys(CH.ld.sel).filter(function(k){return CH.ld.sel[k]}).length}
function chSelDraw(items){var b=$('chSelBar');if(!b)return;b.innerHTML='';if(!items||!items.length)return;b.appendChild(el('span','m','☑ 선택(AI 해설에 쓰여요):'));
 var pick=function(f){CH.ld.sel={};items.forEach(function(it,i){if(f(it,i))CH.ld.sel[it.ticker]=true});chListDraw()};
 [['3축 모두 회복',function(it){return it.axes>=3}],['2개 이상',function(it){return it.axes>=2}],['상위 10',function(it,i){return i<10}],['전체',function(){return true}],['해제',function(){return false}]].forEach(function(z){b.appendChild(bt(z[0],'bt3',function(){pick(z[1])}))});
 var c=el('span','m','선택 '+chSelCount()+'종목');c.id='chSelCnt';b.appendChild(c)}
function chIsOpen(tk,i){return CH.open[tk]===undefined?(i<5):!!CH.open[tk]}
function chListDraw(){var S=CH.ld,out=$('chOut');if(!out)return;var j=S.data;out.innerHTML='';if(!j)return;chStatus(j);if(j.empty){chEmpty(out,j);return}
 var items=chSorted(j.items||[]);chSelDraw(items);var dOk=chDetailOk(j);
 var gc=j.grade_cnt||{},ax=j.ax_cnt||{};out.appendChild(el('p','note','낙폭 기준을 넘은 종목 '+chN(j.matched)+'개 중 회복 점수 상위 '+items.length+'개 · S '+(gc.S||0)+' · A '+(gc.A||0)+' · B '+(gc.B||0)+' · 재무 회복 '+(ax.fin||0)+' · 수급 회복 '+(ax.flow||0)+' · 테마 회복 '+(ax.theme||0)));
 if(!dOk){var lk=el('div','bar');lk.appendChild(el('span','m','🔒 가격·재무·수급·테마 그래프와 상세 수치는 잠겨 있어요.'));lk.appendChild(bt('열리는 등급 보기','bt3',function(){lockDlg('detail')}));out.appendChild(lk)}
 if(!items.length){out.appendChild(el('p','note','조건에 맞는 종목이 없어요. 낙폭 기준을 낮추거나 회복 확인 축을 줄여 보세요.'));CH.tbl=null;return}
 if(S.view==='card')chCards(out,items,dOk);else chTable(out,items,{sel:true,explain:true,sortable:true,detail:dOk});
 var cols=[{h:'#',raw:function(it){return items.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'시장',raw:function(it){return it.market}},{h:'현재가(원)',raw:function(it){return it.price},num:1,disp:function(it,r){return r==null?'-':chN(r)}},
  {h:'등락률(%)',raw:function(it){return it.day_pct},num:1,disp:function(it,r){return r==null?'-':chPct(r)}},{h:'낙폭(%)',raw:function(it){return it.dd},num:1,disp:function(it,r){return r==null?'-':chN(r,1)}},
  {h:'재무',raw:function(it){return (CH_ST[it.fin_st]||CH_ST.na)[1]}},{h:'수급',raw:function(it){return (CH_ST[it.flow_st]||CH_ST.na)[1]}},{h:'테마',raw:function(it){return (CH_ST[it.theme_st]||CH_ST.na)[1]}},
  {h:'회복점수',raw:function(it){return it.ch_score},num:1},{h:'등급',raw:function(it){return it.grade}},{h:'신호',raw:function(it){return it.signals.join(' · ')}}];
 if(dOk)cols=cols.concat([{h:'저점대비(%)',raw:function(it){return it.rebound},num:1,disp:function(it,r){return r==null?'-':chN(r,1)}},{h:'수급5일 외국인(억)',raw:function(it){return it.f5},num:1,disp:function(it,r){return r==null?'-':chN(r)}},{h:'수급5일 기관(억)',raw:function(it){return it.i5},num:1,disp:function(it,r){return r==null?'-':chN(r)}}]);
 chSetTbl('낙폭 회복 후보',cols,items,j.meta?j.meta.price_asof:'');chExpBar(out)}
function chThSort(h,heads){heads.forEach(function(x){var th=el('th',(x[2]?'r':'')+(x[1]?' chSrt':''),x[0]+(CH.ld.sort.col===x[1]?(CH.ld.sort.asc?' ▲':' ▼'):''));if(x[1])th.onclick=function(){chSortBy(x[1])};h.appendChild(th)})}
function chToggle(it){if(!ftOk('detail')){lockDlg('detail');return}var cur=chIsOpen(it.ticker,99);CH.open[it.ticker]=!cur;chListDraw()}
function chTable(out,items,o){var det=!!o.detail,S=CH.ld;var w=el('div','chW'),t=el('table','chT'),h=el('tr');
 if(o.sel){var th0=el('th',null,'');var all=el('input');all.type='checkbox';all.checked=items.length>0&&items.every(function(it){return S.sel[it.ticker]});all.title='전체 선택';all.onchange=function(){items.forEach(function(it){S.sel[it.ticker]=all.checked});chListDraw()};th0.appendChild(all);h.appendChild(th0)}
 var heads=[['#',null,0],['종목',null,0],['현재가',o.sortable?'price':null,1,o.sortable],['등락',o.sortable?'day_pct':null,1,o.sortable],['낙폭',o.sortable?'dd':null,1,o.sortable],['회복 축',null,0],['회복점수',o.sortable?'ch_score':null,1,o.sortable]];
 if(det)heads=heads.concat([['저점대비',o.sortable?'rebound':null,1,o.sortable],['수급 5일',null,1]]);
 heads.push(['신호',null,0]);chThSort(h,heads);t.appendChild(h);
 var ncol=heads.length+(o.sel?1:0);
 items.forEach(function(it,i){var tr=el('tr',S.sel[it.ticker]&&o.sel?'chSelR':'');
  if(o.sel){var c0=el('td');var cb=el('input');cb.type='checkbox';cb.checked=!!S.sel[it.ticker];cb.onchange=function(){S.sel[it.ticker]=cb.checked;chListDraw()};c0.appendChild(cb);tr.appendChild(c0)}
  tr.appendChild(el('td','chZ',String(i+1)));var nm=el('td');nm.appendChild(chTk(el('span','nm',it.name),it.ticker));
  if(o.explain){var tg=el('span','chZ',' ▾');tg.style.cursor='pointer';tg.title='그래프·점수 구성 보기';tg.setAttribute('data-ex',it.ticker);tg.onclick=function(){chToggle(it)};if(!ftOk('detail'))tg.title='🔒 그래프·상세';nm.appendChild(tg)}
  nm.appendChild(el('div','sb',it.ticker+(it.market?' · '+it.market:'')+(it.theme?' · '+it.theme:'')));tr.appendChild(nm);
  tr.appendChild(el('td','r',it.price?chN(it.price)+'원':'-'));tr.appendChild(el('td','r '+chCls(it.day_pct),chPct(it.day_pct)));
  tr.appendChild(el('td','r '+chCls(it.dd),it.dd==null?'-':chPct(it.dd,1)));
  var ax=el('td');ax.appendChild(chAxes(it));tr.appendChild(ax);
  var sc=el('td','r');sc.appendChild(el('span','chSc',String(it.ch_score)));sc.appendChild(chGrade(it.grade));tr.appendChild(sc);
  if(det){tr.appendChild(el('td','r '+chCls(it.rebound),it.rebound==null?'-':chPct(it.rebound,1)));var sp=(it.f5==null&&it.i5==null)?null:(it.f5||0)+(it.i5||0);tr.appendChild(el('td','r '+chCls(sp),sp==null?'-':chFe(sp)))}
  var sg=el('td');sg.appendChild(chSigs(it.signals));tr.appendChild(sg);t.appendChild(tr);
  if(o.explain&&CH.open[it.ticker]){var d2=el('tr','chDt'),dc=el('td');dc.colSpan=ncol;dc.appendChild(chDetailBox(it));d2.appendChild(dc);t.appendChild(d2)}});
 w.appendChild(t);out.appendChild(w)}
function chCards(out,items,det){var g=el('div','chCards');var S=CH.ld;
 items.forEach(function(it,i){var c=el('div','chCard'+(S.sel[it.ticker]?' chSelC':''));var top=el('div');top.style.cssText='display:flex;justify-content:space-between;align-items:flex-start;gap:8px';
  var l=el('div');var cb=el('input');cb.type='checkbox';cb.checked=!!S.sel[it.ticker];cb.onchange=function(){S.sel[it.ticker]=cb.checked;chListDraw()};l.appendChild(cb);l.appendChild(document.createTextNode(' '));l.appendChild(chTk(el('b','nm',it.name),it.ticker));
  l.appendChild(el('div','m',it.ticker+(it.market?' · '+it.market:'')+(it.cap?' · 시총 '+chEok(it.cap):'')+(it.theme?' · '+it.theme:'')));top.appendChild(l);
  var r=el('div');r.style.textAlign='right';r.appendChild(el('span','chSc',String(it.ch_score)));r.appendChild(chGrade(it.grade));top.appendChild(r);c.appendChild(top);
  var pr=el('div');pr.style.margin='6px 0 2px';pr.appendChild(document.createTextNode((it.price?chN(it.price)+'원 ':'-')+' '));pr.appendChild(el('span',chCls(it.day_pct),chPct(it.day_pct)));pr.appendChild(document.createTextNode('  · 고점 대비 '));pr.appendChild(el('b',chCls(it.dd),chPct(it.dd,1)));c.appendChild(pr);
  var ax=el('div');ax.appendChild(chAxes(it));c.appendChild(ax);var sg=el('div');sg.appendChild(chSigs(it.signals));c.appendChild(sg);
  var op=chIsOpen(it.ticker,i);
  if(det){if(it.chart){var pb=el('div','chGx');if(op){pb.appendChild(chGraphBox(it))}else{var ps=chPriceSvg(it);if(ps)pb.appendChild(ps)}c.appendChild(pb)}
   var ac=el('div','bar');ac.appendChild(ft(bt(op?'▴ 그래프 접기':'▾ 재무·수급·테마 그래프','bt3',function(){CH.open[it.ticker]=!op;chListDraw()}),'detail'));ac.appendChild(ft(bt('🧮 점수 구성','bt3',function(){chExToggle(it)}),'detail'));c.appendChild(ac);
   if(CH.ex[it.ticker]&&CH.ex[it.ticker].show)c.appendChild(chExBox(it))}
  else{var ac2=el('div','bar');ac2.appendChild(ft(bt('▾ 그래프·점수 구성','bt3',function(){lockDlg('detail')}),'detail'));c.appendChild(ac2)}
  g.appendChild(c)});out.appendChild(g)}
function chExToggle(it){if(!ftOk('detail')){lockDlg('detail');return}var x=CH.ex[it.ticker];if(x&&x.parts){x.show=!x.show;chListDraw();return}
 CH.ex[it.ticker]={show:true,loading:true};chListDraw();api('/admin/api/challenge/explain?ticker='+encodeURIComponent(it.ticker)).then(function(j){j.show=true;CH.ex[it.ticker]=j;chListDraw()}).catch(function(){CH.ex[it.ticker]={show:true,error:'불러오지 못했어요.'};chListDraw()})}
function chDetailBox(it){var x=el('div');x.appendChild(chGraphBox(it));var b=el('div','bar');b.appendChild(bt('🧮 점수 구성 보기','bt3',function(){chExToggle(it)}));x.appendChild(b);if(CH.ex[it.ticker]&&CH.ex[it.ticker].show)x.appendChild(chExBox(it));return x}
function chExBox(it){var x=el('div'),j=CH.ex[it.ticker];if(!j||j.loading){x.appendChild(el('p','note','⏳ 불러오는 중…'));return x}
 if(j.error){x.appendChild(el('p','note bad','⚠ '+j.error));return x}
 var tb=chTblBuild(['항목','값','점수에 더해진 값'],['','','r']);
 j.parts.forEach(function(p){var tr=el('tr');tr.appendChild(el('td',null,p.k));tr.appendChild(el('td',null,p.v));tr.appendChild(el('td','r '+chCls(p.p),(p.p>0?'+':'')+p.p));tb.t.appendChild(tr)});
 var tt=el('tr');tt.appendChild(el('td',null,'합계(0~100)'));tt.appendChild(el('td',null,'등급 기준: S 75↑ · A 60↑ · B'));tt.appendChild(el('td','r',String(j.total)));tb.t.appendChild(tt);x.appendChild(tb.wrap);
 x.appendChild(el('p','note','회복 점수는 낙폭(최대 25)·재무(25)·수급(25)·테마(15)·가격 안정(10)을 더한 값이에요. 수급은 순매수 수량×종가 근사치예요.'+(j.excluded?' 이 종목은 상장폐지·거래정지 위험 표시가 있어 목록에서는 빠져요.':'')));return x}

/* ── 관리자 전용: 결과 저장 ── */
function chSave(){var j=CH.ld.data;if(!j||!j.items||!j.items.length){toast('먼저 조회하세요.');return}
 apiJ('/admin/api/challenge/save',{items:j.items}).then(function(r){if(r.error){toast(r.error);return}toast('💾 '+r.date+' 기준 낙폭 회복 후보 '+r.saved+'건을 저장했어요(성과 기록에는 새로 '+r.new+'건)');CH.sv.list=null}).catch(function(){toast('저장하지 못했어요.')})}

/* ── 과거 결과 보관함(기능 'saved') ── */
function chSecSaved(box){box.appendChild(el('p','note','관리자가 저장해 둔 과거 결과예요. 저장한 순간의 값이라 지금 시세와 달라요. 목록에서 [보기]를 누르면 그때의 종목과 낙폭·회복 판정을 볼 수 있어요(그래프는 저장하지 않아요).'));
 var out=el('div');out.id='chSvOut';box.appendChild(out);if(CH.sv.cur){chSvView(out)}else if(CH.sv.list){chSvDraw(out)}else chSvGo()}
function chSvGo(){var out=$('chSvOut');if(!out)return;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/challenge/saved').then(function(j){var o=$('chSvOut');if(!o)return;if(j.error){chErr(o,j.error);return}CH.sv.list=j;chSvDraw(o)}).catch(function(){chErr($('chSvOut'),'불러오지 못했어요.')})}
function chSvDraw(out){var j=CH.sv.list;out.innerHTML='';if(!j)return;if(j.empty){chEmpty(out,j);return}
 if(!j.items.length){out.appendChild(el('p','note','저장된 결과가 아직 없어요.'));return}
 var tb=chTblBuild(['저장 결과','저장 시각','종목 수',''],['','','r','']);
 j.items.forEach(function(x){var tr=el('tr');var td=el('td');td.appendChild(el('span','nm',x.label));if(x.old)td.appendChild(el('div','sb','예전 ‘도전점수’ 방식으로 저장된 결과'));tr.appendChild(td);tr.appendChild(el('td',null,x.saved_at));tr.appendChild(el('td','r',String(x.cnt)));
  var ac=el('td');ac.appendChild(bt('보기','bt3',function(){chSvOpen(x.key)}));var del=bt('🗑 삭제','bt3',function(){if(!confirm('이 저장 결과를 삭제할까요? (성과 기록은 그대로 남아요)'))return;apiJ('/admin/api/challenge/saved/delete',{key:x.key}).then(function(r){if(r.error){toast(r.error);return}toast('삭제했어요');CH.sv.list=null;chSvGo()})});ac.appendChild(adm(del));tr.appendChild(ac);tb.t.appendChild(tr)});out.appendChild(tb.wrap)}
function chSvOpen(k){var out=$('chSvOut');if(!out)return;var my=++CH.sv.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/challenge/saved/get?key='+encodeURIComponent(k)).then(function(j){if(my!==CH.sv.seq)return;var o=$('chSvOut');if(!o)return;if(j.error){chErr(o,j.error);return}CH.sv.cur=j;chSvView(o)}).catch(function(){chErr($('chSvOut'),'불러오지 못했어요.')})}
function chSvView(out){var j=CH.sv.cur;out.innerHTML='';var bk=el('div','bar');bk.appendChild(bt('← 목록으로','bt3',function(){CH.sv.cur=null;chShow()}));bk.appendChild(el('b',null,'📂 '+(j.label||j.key)));out.appendChild(bk);
 var gc=j.grade_cnt||{};out.appendChild(el('p','note','저장 시각 '+j.saved_at+' · '+j.items.length+'종목 · S '+(gc.S||0)+' · A '+(gc.A||0)+' · B '+(gc.B||0)+' · 가격·점수는 저장 당시 값이에요.'+(j.old?' (예전 ‘도전점수’ 방식으로 저장된 결과라 점수 의미가 달라요)':'')));
 var dOk=chDetailOk(j);if(!dOk){var lk=el('div','bar');lk.appendChild(el('span','m','🔒 저점 대비·수급 같은 상세 값은 잠겨 있어요.'));lk.appendChild(bt('열리는 등급 보기','bt3',function(){lockDlg('detail')}));out.appendChild(lk)}
 if(!j.items.length){out.appendChild(el('p','note','이 저장 결과에는 읽을 수 있는 종목이 없어요.'));return}
 var its=j.items.slice().sort(function(a,b){return b.ch_score-a.ch_score});
 chTable(out,its,{sel:false,explain:false,sortable:false,detail:dOk});
 chSetTbl('낙폭 회복 저장 결과 · '+(j.label||j.key),[{h:'#',raw:function(it){return its.indexOf(it)+1}},{h:'종목',raw:function(it){return it.name}},{h:'코드',raw:function(it){return it.ticker}},{h:'저장가(원)',raw:function(it){return it.price},num:1,disp:function(it,r){return r==null?'-':chN(r)}},
  {h:'낙폭(%)',raw:function(it){return it.dd},num:1,disp:function(it,r){return r==null?'-':chN(r,1)}},{h:'회복점수',raw:function(it){return it.ch_score},num:1},{h:'등급',raw:function(it){return it.grade}},{h:'신호',raw:function(it){return it.signals.join(' · ')}}],its,j.saved_at);chExpBar(out)}

/* ── 성과 기록(기능 'track') ── */
function chSecTrack(box){var S=CH.tr;box.appendChild(el('p','note','관리자가 저장한 날의 가격과 가장 최근 스캔 가격을 비교한 기록이에요. 이 목록을 따라 투자했을 때의 수익이 아니며(비용·기간 보정 없음), 과거 결과가 미래를 보장하지 않아요. 오늘 저장한 건은 내일부터 계산돼요.'));
 var bar=el('div','bar'),go=function(){chTrackGo()};chSel(bar,'기간',S,'days',[['0','전체'],['7','7일'],['30','30일'],['90','90일']],go);chSel(bar,'최근 기록 개수',S,'limit',[['30','30개'],['60','60개'],['150','150개'],['300','300개']],go);bar.appendChild(bt('조회하기','bt',go));box.appendChild(bar);
 var out=el('div');out.id='chTrOut';box.appendChild(out);if(S.data)chTrackDraw(out);else chTrackGo()}
function chTrackGo(){var S=CH.tr,out=$('chTrOut');if(!out)return;var my=++S.seq;out.innerHTML='';out.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/challenge/track?'+chQ({days:S.days,limit:S.limit})).then(function(j){if(my!==S.seq)return;var o=$('chTrOut');if(!o)return;if(j.error){chErr(o,j.error);return}S.data=j;chTrackDraw(o)}).catch(function(){chErr($('chTrOut'),'불러오지 못했어요.')})}
function chStatTbl(out,title,obj,keys,keyLbl,delFn){var ks=keys||Object.keys(obj);if(!ks.length)return;out.appendChild(el('h4',null,title));var tb=chTblBuild([keyLbl,'건수','오른 비율','평균 등락'].concat(delFn?['']:[]),['','r','r','r'].concat(delFn?['']:[]));
 ks.forEach(function(k){var x=obj[k];var tr=el('tr');tr.appendChild(el('td',null,k));tr.appendChild(el('td','r',String(x.cnt)));tr.appendChild(el('td','r',x.up_rate+'% ('+x.up+'/'+x.cnt+')'));tr.appendChild(el('td','r '+chCls(x.avg_ret),chPct(x.avg_ret)));
  if(delFn){var td=el('td');td.appendChild(adm(bt('🗑 삭제','bt3',function(){delFn(k)})));tr.appendChild(td)}tb.t.appendChild(tr)});out.appendChild(tb.wrap)}
function chTrackDraw(out){var j=CH.tr.data;out.innerHTML='';if(!j)return;if(j.empty){chEmpty(out,j);return}var t=j.total;
 if(j.skipped_old)out.appendChild(el('p','note','예전 ‘도전점수’ 방식으로 저장된 기록 '+j.skipped_old+'건은 뜻이 달라 계산에서 뺐어요.'));
 if(!t.cnt){out.appendChild(el('p','note',j.today_cnt>0&&j.total_records===j.today_cnt?'오늘 저장한 '+j.today_cnt+'건은 내일부터 계산돼요.':(j.total_records?'계산할 수 있는 기록이 아직 없어요(저장가나 최근 스캔 가격이 없거나 기간 밖이에요).':'아직 저장된 성과 기록이 없어요. 관리자가 결과를 저장하면 쌓여요.')));CH.tbl=null;return}
 var g=el('div','chTiles');[['계산된 기록',chN(t.cnt)+'건','저장일 대비 최근 스캔 가격'],['오른 비율',t.up_rate+'%',t.up+'건 상승 · '+(t.cnt-t.up)+'건 하락·보합'],['평균 등락',chPct(t.avg_ret),'단순 평균(비용 제외)'],['누적 기록',chN(j.total_records)+'건','오늘 저장 '+j.today_cnt+'건은 내일부터']].forEach(function(z){var d=el('div','chTile');d.appendChild(el('div','l',z[0]));d.appendChild(el('div','v',z[1]));d.appendChild(el('div','s',z[2]));g.appendChild(d)});out.appendChild(g);
 chStatTbl(out,'등급별',j.by_grade,['S','A','B','-'].filter(function(k){return j.by_grade[k]}),'등급');
 chStatTbl(out,'회복점수대별',j.by_score,['75점 이상(S권)','60~74점(A권)','60점 미만(B권)'].filter(function(k){return j.by_score[k]}),'점수대');
 chStatTbl(out,'신호별',j.by_signal,Object.keys(j.by_signal).sort(function(a,b){return j.by_signal[b].cnt-j.by_signal[a].cnt}).slice(0,14),'신호');
 chStatTbl(out,'충족 신호 개수별',j.by_sig_count,Object.keys(j.by_sig_count).sort(function(a,b){return Number(a)-Number(b)}),'신호 개수');
 chStatTbl(out,'저장일별',j.by_date,Object.keys(j.by_date),'저장일',function(d){if(!confirm(d+' 에 저장한 성과 기록을 모두 삭제할까요?'))return;apiJ('/admin/api/challenge/track/delete',{pick_date:d}).then(function(r){if(r.error){toast(r.error);return}toast('삭제했어요('+r.deleted+'건)');CH.tr.data=null;chTrackGo()})});
 out.appendChild(el('h4',null,'최근 기록'));var tb=chTblBuild(['저장일','종목','등급·점수','신호','저장가','현재가','등락'],['','','','','r','r','r']);
 j.recent.forEach(function(r){var tr=el('tr');tr.appendChild(el('td',null,r.date.slice(5)));var nm=el('td');nm.appendChild(chTk(el('span','nm',r.name),r.ticker));nm.appendChild(el('div','sb',r.ticker));tr.appendChild(nm);
  var sc=el('td');sc.appendChild(document.createTextNode(r.ch_score+' '));sc.appendChild(chGrade(r.grade));tr.appendChild(sc);var sg=el('td');sg.appendChild(chSigs(r.signals));tr.appendChild(sg);
  tr.appendChild(el('td','r',chN(r.pick_price)));tr.appendChild(el('td','r',chN(r.cur_price)));tr.appendChild(el('td','r '+chCls(r.ret),(r.up?'▲ ':'▼ ')+chPct(r.ret)));tb.t.appendChild(tr)});out.appendChild(tb.wrap);
 chSetTbl('낙폭 회복 성과 기록',[{h:'저장일',raw:function(r){return r.date}},{h:'종목',raw:function(r){return r.name}},{h:'코드',raw:function(r){return r.ticker}},{h:'회복점수',raw:function(r){return r.ch_score},num:1},{h:'등급',raw:function(r){return r.grade}},
  {h:'저장가(원)',raw:function(r){return r.pick_price},num:1,disp:function(r,v){return chN(v)}},{h:'현재가(원)',raw:function(r){return r.cur_price},num:1,disp:function(r,v){return chN(v)}},{h:'등락률(%)',raw:function(r){return r.ret},num:1,disp:function(r,v){return chPct(v)}}],j.recent,'저장일 대비 최근 스캔 가격');chExpBar(out)}

/* ── AI 해설 프롬프트(기능 'ai') — 수동 AI 도우미 ── */
function chAiLoad(){api('/admin/api/challenge/ai').then(function(r){if(!r||r.error||!r.found)return;if(r.stale){CH.ai.old=r;if($('chAiOut'))chAiDraw();return}if(!(CH.ai.text||'').trim()){CH.ai.text=r.text;CH.ai.date=r.date}chSteps();if($('chAiOut'))chAiDraw()}).catch(function(){})}
function chSecAi(box){box.appendChild(el('p','note',MEMBER_MODE?'후보 목록에서 체크한 종목(없으면 현재 조건의 상위 20종목)의 낙폭·재무·수급·테마 데이터를 담은 프롬프트를 만들어, 사용하는 AI(제미나이·챗GPT·클로드 등)에 붙여 넣을 수 있게 해요. AI가 답하면 복사해서 이 창으로 돌아오면 아래에 보여 줘요(이 화면에서만 보관돼요). AI 답변은 참고용이며 틀릴 수 있어요.':'후보 목록에서 체크한 종목(없으면 현재 조건의 상위 20종목)의 낙폭·재무·수급·테마 데이터를 담은 프롬프트를 만들어 AI(제미나이·챗GPT·클로드 등)에 붙여 넣어요. AI 답변을 복사하고 이 창으로 돌아오면 읽어 와서 저장하고, 다음 단계(대시보드 이미지 → 블로그 글)로 이어져요. AI 답변은 참고용이며 틀릴 수 있어요.'));
 var n=chSelCount();box.appendChild(el('p','note','대상: '+(n?'후보 목록에서 선택한 '+Math.min(n,30)+'종목(최대 30개)':'현재 조건(시장·낙폭·회복 축)의 회복 점수 상위 20종목')));
 var bar=el('div','bar');bar.appendChild(ft(bt('🤖 AI 프롬프트 만들기','bt',chAiRun),'ai'));box.appendChild(bar);var out=el('div');out.id='chAiOut';box.appendChild(out);chAiDraw()}
function chAiRun(){if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}var S=CH.ld;
 var tk=Object.keys(S.sel).filter(function(k){return S.sel[k]}).slice(0,30).join(',');
 api('/admin/api/challenge/prompt?'+chQ({tickers:tk,markets:S.market==='all'?'KOSPI,KOSDAQ':S.market,drop:S.drop,axes:S.axes,top:20})).then(function(j){if(j.error){toast(j.error);return}if(j.empty){toast(j.msg);return}
  window.MiniAI.run({title:'낙폭 회복 AI 해설 — '+j.label,key:'challenge',steps:[{label:j.label,prompt:j.prompt}],minLen:150,hint:'AI가 "## 📉 낙폭 종목의 공통 특징 …" 형식으로 답하면 답변 전체를 복사하고 이 창으로 돌아오세요.',
   preview:function(t){var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString('ko-KR')+'자 — '+t.slice(0,240)+(t.length>240?' …':'');return {node:x,canApply:t.trim().length>=100,strict:true}},
   apply:function(t){CH.ai.text=String(t||'').slice(0,20000);CH.ai.date='';CH.flag.img=false;CH.flag.blog=false;CH.flag.posted=false;
    if(MEMBER_MODE){chAiDraw();chSteps();return Promise.resolve({message:'AI 해설을 아래 화면에 보여 줬어요(이 화면에서만 보관돼요).'})}
    var tks=chPickItems().map(function(x){return x.ticker});
    return apiJ('/admin/api/challenge/ai',{text:CH.ai.text,label:j.label,tickers:tks}).then(function(z){var ok=!z.error;if(ok)CH.ai.date=z.date;chAiDraw();chSteps();
     if(ok)setTimeout(function(){if(window.MiniFlow)MiniFlow.run('challenge',CHFLOW,CHACTS,'ai')},60);
     return {message:ok?'AI 분석을 저장했어요. 다음 단계(이미지 → 블로그 글)로 이어져요.':'읽었지만 저장하지 못했어요: '+z.error}}).catch(function(){chAiDraw();chSteps();return {message:'읽었지만 저장하지 못했어요(네트워크).'}})}})})}
function chAiDraw(){var out=$('chAiOut');if(!out)return;out.innerHTML='';var t=CH.ai.text;if(!t){out.appendChild(el('p','note','아직 AI 분석이 없어요. [AI 프롬프트 만들기]를 눌러 보세요.'));
  var o=CH.ai.old;if(o&&!MEMBER_MODE){var r0=el('div','bar');r0.appendChild(el('span','m','지난 AI 분석이 저장돼 있어요('+(o.date||'')+'). 지금 목록과 맞지 않을 수 있어요.'));r0.appendChild(bt('지난 분석 불러오기','bt3',function(){CH.ai.text=o.text;CH.ai.date=o.date;CH.ai.old=null;CH.flag.img=false;CH.flag.blog=false;chAiDraw();chSteps()}));out.appendChild(r0)}return}
 var box=el('div','chAiOut');t.split('\n').forEach(function(l){var m;var s=l.replace(/\*\*/g,'');if((m=/^##\s+(.*)$/.exec(s))){box.appendChild(el('span','h2',m[1]))}else if((m=/^###\s+(.*)$/.exec(s))){box.appendChild(el('span','h3',m[1]))}else{box.appendChild(document.createTextNode(s));box.appendChild(document.createElement('br'))}});out.appendChild(box);
 var r=el('div','bar');r.appendChild(bt('📋 해설 복사하기','bt3',function(){var ok=window.MiniAI&&window.MiniAI.copy?window.MiniAI.copy(CH.ai.text):false;toast(ok?'복사했어요':'복사가 막혔어요')}));r.appendChild(bt('✖ 지우기','bt3',function(){CH.ai.text='';CH.ai.date='';chAiDraw();chSteps()}));out.appendChild(r);
 if(CH.ai.date&&!MEMBER_MODE)out.appendChild(el('p','note','💾 저장돼 있어요('+CH.ai.date+') — 대시보드 이미지·블로그 글에 쓰여요. [지우기]는 이 화면에서만 지우고 저장본은 남아요.'));
 out.appendChild(el('p','note','⚠ AI가 만든 참고 글이에요. 숫자와 내용이 틀릴 수 있고, 특정 종목의 매수·매도 권유가 아니에요.'))}

/* ── ③ 대시보드 이미지(기능 'img') — 브라우저 캔버스로 그려 저장(서버 호출 없음) ── */
function chImgMeta(){var j=CH.ld.data||{};return {asof:j.meta&&j.meta.price_asof,drop:j.q&&j.q.drop}}
function chImgBuild(scale){return chEnsureP().then(function(items){if(!window.ChImg)throw new Error('이미지 도구(menu_img.py)가 올라가지 않았어요.');return window.ChImg.build(items,CH.ai.text||'',chDate(),scale,chImgMeta())})}
function chSecImg(box){box.appendChild(el('p','note',MEMBER_MODE?'후보 목록의 낙폭·회복 점수·재무/수급/테마 판정을 한 장의 대시보드 이미지로 만들어 내려받아요. 만든 뒤 [이미지 내려받기]로 내 기기에 저장하세요. 참고 자료이며 투자 권유가 아니에요.':'① 대시보드(요약·3축 현황·TOP 10) · ② 종목별 가격 그래프(그래프 상세 기능이 열려 있을 때) · ③ AI 분석 요약(AI 분석이 있을 때)을 이미지로 그려요. 저장 폴더·자동/수동 저장은 [⚙ 저장 설정]에서 정해요. 이 이미지를 블로그 글 위쪽에 올려 쓰세요.'));
 var ib=el('div','chPan');box.appendChild(ib);
 if(!window.ImgKit){ib.appendChild(el('p','note bad','이미지 도구(menu_img.py)가 올라가지 않았어요.'));return}
 if(MEMBER_MODE){chImgMember(ib);return}
 CH.imgPanel=ImgKit.panel(ib,{menu:'challenge',name:'낙폭회복',ticker:chStamp(),perStock:false,onDone:function(){CH.flag.img=true;chSteps()},gen:function(scale){return chImgBuild(scale)}});
 if(CH.flag.img)CH.imgPanel.gen(false)}
function chImgMember(ib){var K=window.ImgKit,row=el('div','bar'),view=el('div','chImgG'),st=el('div','m');
 var go=bt('🖼 이미지 만들기','bt',function(){go.disabled=true;go.textContent='⏳ 그리는 중…';view.innerHTML='';st.textContent='';
  Promise.resolve(K.fonts()).then(function(){return chImgBuild(2)}).then(function(items){items.forEach(function(it){var c=el('div','c');c.appendChild(el('b',null,K.CIRC[it.idx-1]+' '+it.label));
    var pw=Math.min(720,it.canvas.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(it.canvas.height*pw/it.canvas.width);sm.getContext('2d').drawImage(it.canvas,0,0,sm.width,sm.height);
    var im=new Image();im.alt=it.label;im.src=sm.toDataURL('image/png');im.style.cssText='width:100%;height:auto;display:block;border-radius:8px;margin:6px 0';c.appendChild(im);
    c.appendChild(bt('💾 이미지 내려받기','bt2',function(){it.canvas.toBlob(function(bl){if(!bl){toast('이미지를 만들지 못했어요');return}chDl(bl,K.fileName(it.idx,'낙폭회복',chStamp()))},'image/png')}));view.appendChild(c)});
   st.textContent='이미지를 만들었어요. 각 이미지의 [이미지 내려받기]로 내 기기에 저장하세요.';go.textContent='🔄 다시 만들기';CH.flag.img=true;chSteps()})
  .catch(function(e){st.textContent='이미지를 만들지 못했어요: '+(e&&e.message||e);go.textContent='🖼 이미지 만들기'}).then(function(){go.disabled=false})});
 CH.memGo=go;row.appendChild(go);ib.appendChild(row);ib.appendChild(st);ib.appendChild(view)}

/* ── ④ 블로그 쓰기(관리자 전용, 서버가 HTML 글을 만들고 복사해서 붙여 넣는 방식) ── */
function chSecBlog(box){if(MEMBER_MODE)return;
 box.appendChild(el('p','note','낙폭 회복 후보 + AI 분석으로 블로그용 글(HTML)을 만들어요. 글은 자동으로 올라가지 않고, [복사하고 블로그 열기]로 복사한 뒤 블로그 글쓰기 화면에 붙여 넣는 방식이에요. ③에서 저장한 대시보드 이미지는 글 위쪽에 직접 올려 주세요.'));
 var bx=el('div','chPan');box.appendChild(bx);
 if(!window.BlogKit){bx.appendChild(el('p','note bad','블로그 도구(menu_blog.py)가 올라가지 않았어요.'));CH.blogPanel=null;return}
 var secs=[['stats','요약통계'],['axes','3축 현황'],['top','점수TOP'],['ai','AI분석'],['list','후보표'],['notes','회복 근거']];
 CH.blogPanel=window.BlogKit.panel(bx,{idp:'ch',key:'challenge',kind:'challenge',ticker:'D'+chStamp().slice(2),name:'도전주 낙폭회복 '+chDate(),sections:secs,dup_warn:'',onBuilt:function(){CH.flag.blog=true;CH.flag.posted=false;chSteps()},onCopied:function(){CH.flag.posted=true;chSteps()},
  build:function(inc,title){return chEnsureP().then(function(items){return apiJ('/admin/api/challenge/blog',{tickers:items.map(function(x){return x.ticker}),ai:CH.ai.text||'',inc:inc,title:title,n:20})}).catch(function(e){return {error:(e&&e.message)||'만들지 못했어요'}})}});
 if(CH.flag.blog)CH.blogPanel.rebuild()}

(function(){
var K=window.ImgKit;if(!K||window.ChImg)return;
var T=K.text,N=K.n,RR=K.rr;
var NAVY0='#0a1228',NAVY1='#16275a',GOLD='#d6b25e',PAPER='#f4f0e6',INK='#0f172a',MUT='#64748b',UP='#e11d48',DN='#2563eb',IND='#4f46e5';
var STC={ok:['#4f46e5','#ffffff'],weak:['#f59e0b','#ffffff'],no:['#e2e8f0','#64748b'],na:['#f1f5f9','#94a3b8']};
var STM={ok:'✓',weak:'△',no:'✕',na:'-'};
var STN={ok:'회복 확인',weak:'일부',no:'미흡',na:'자료 없음'};
function gcol(g){return g==='S'?'#4f46e5':(g==='A'?'#0891b2':'#64748b')}
function pc(v,d){if(v==null||isNaN(v))return '-';return (v>0?'+':'')+Number(v).toFixed(d==null?1:d)+'%'}
function band(c,W,kick,title,sub){var g=c.createLinearGradient(0,0,0,210);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,210);c.fillStyle=GOLD;c.fillRect(0,0,W,8);
 var rg=c.createRadialGradient(W-100,40,10,W-100,40,300);rg.addColorStop(0,'rgba(214,178,94,.35)');rg.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=rg;c.fillRect(0,0,W,210);
 T(c,kick,W/2,60,{s:20,w:800,c:GOLD,a:'center',ls:5});T(c,title,W/2,132,{s:56,w:900,c:'#fff',a:'center',max:W-120});T(c,sub,W/2,178,{s:21,w:600,c:'#cbd5e1',a:'center',max:W-120})}
function card(c,x,y,w,h,r){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,r||24);c.fillStyle='#fff';c.fill();c.restore()}
function foot(c,W,y,note){c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,y,W-120,2);var k=0;
 if(note){T(c,note,W/2,y+38,{s:19,w:700,c:'#92400e',a:'center',max:W-120});k=34}
 T(c,'낙폭이 큰 종목은 더 떨어질 수 있어요(떨어지는 칼날). 공개 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다.',W/2,y+38+k,{s:19,w:600,c:MUT,a:'center',max:W-120});
 T(c,'모든 투자 판단과 책임은 투자자 본인에게 있어요 · 출처 네이버증권 · stock.oky.kr',W/2,y+72+k,{s:19,w:700,c:'#94a3b8',a:'center',max:W-120})}
function badge(c,x,y,w,h,lab,st){var m=STC[st]||STC.na;RR(c,x,y,w,h,10);c.fillStyle=m[0];c.fill();T(c,lab,x+w/2,y+h*0.40,{s:15,w:800,c:m[1],a:'center'});T(c,STM[st]||'-',x+w/2,y+h*0.84,{s:22,w:900,c:m[1],a:'center'})}
function cnt(items,k){var o={ok:0,weak:0,no:0,na:0};items.forEach(function(i){var s=i[k+'_st'];o[s in o?s:'na']++});return o}

function dash(items,date,scale,meta){var n=Math.min(10,items.length),RH=90,W=1080;
 var tH=100,aH=280,tbH=56+n*RH+16,H=210+30+tH+30+aH+30+tbH+30+118,m=K.make(W,H,scale),c=m.c;c.fillStyle=PAPER;c.fillRect(0,0,W,H);
 var drop=meta&&meta.drop?meta.drop:30;
 band(c,W,'DROP & RECOVERY','낙폭 회복 후보 '+items.length+'선',date+' · 52주 고점 대비 -'+drop+'% 이상 · 재무·수급·테마 점검'+(meta&&meta.asof?' · 시세 기준일 '+meta.asof:''));
 var cnt0=items.length,avgDd=cnt0?items.reduce(function(s,i){return s+(i.dd||0)},0)/cnt0:0,avgSc=cnt0?Math.round(items.reduce(function(s,i){return s+i.ch_score},0)/cnt0):0,sa=items.filter(function(i){return i.grade==='S'||i.grade==='A'}).length,a3=items.filter(function(i){return i.axes>=3}).length;
 var tl=[['후보',cnt0+'종목',INK],['평균 낙폭',pc(avgDd),DN],['평균 점수',avgSc+'점',IND],['S·A급',sa+'개','#dc2626'],['3축 모두 확인',a3+'개','#16a34a']],tw=(W-100-16*4)/5,y1=240;
 tl.forEach(function(t,i){var x=50+i*(tw+16);card(c,x,y1,tw,tH,18);T(c,t[0],x+tw/2,y1+36,{s:20,w:700,c:MUT,a:'center'});T(c,t[1],x+tw/2,y1+80,{s:34,w:900,c:t[2],a:'center',max:tw-16})});
 var y2=y1+tH+30;card(c,50,y2,W-100,aH,24);c.fillStyle=GOLD;RR(c,76,y2+26,6,30,3);c.fill();T(c,'재무·수급·테마 회복 신호 현황',96,y2+50,{s:26,w:900,c:INK});T(c,'후보 '+cnt0+'종목 기준',W-76,y2+49,{s:16,w:500,c:'#94a3b8',a:'right'});
 var bx=250,bw=W-100-200-26,keys=[['fin','재무'],['flow','수급'],['theme','테마']];
 keys.forEach(function(k,r){var y=y2+84+r*52,o=cnt(items,k[0]);T(c,k[1],96,y+27,{s:24,w:800,c:INK});var x=bx;
  ['ok','weak','no','na'].forEach(function(s){var w=cnt0?bw*o[s]/cnt0:0;if(w<=0)return;c.fillStyle=STC[s][0];c.fillRect(x,y,w,36);if(w>=34)T(c,String(o[s]),x+w/2,y+26,{s:20,w:800,c:STC[s][1],a:'center'});x+=w});
  T(c,'회복 확인 '+o.ok,W-76,y+27,{s:19,w:800,c:IND,a:'right'})});
 var lx=bx,ly=y2+aH-26;['ok','weak','no','na'].forEach(function(s){c.fillStyle=STC[s][0];RR(c,lx,ly-14,18,18,5);c.fill();T(c,STN[s],lx+26,ly+1,{s:17,w:700,c:MUT});lx+=26+STN[s].length*18+34});
 var y3=y2+aH+30;card(c,50,y3,W-100,tbH,24);
 [['종목',150,'left'],['점수',500,'right'],['낙폭 (반등=저점 대비)',760,'right'],['재무',820,'center'],['수급',886,'center'],['테마',952,'center']].forEach(function(h){T(c,h[0],h[1],y3+40,{s:19,w:800,c:'#475569',a:h[2]})});c.fillStyle='#e2e8f0';c.fillRect(74,y3+54,W-148,2);
 items.slice(0,n).forEach(function(it,i){var y=y3+60+i*RH;if(i%2===0){c.fillStyle='rgba(241,245,249,.7)';RR(c,66,y+2,W-132,RH-6,14);c.fill()}
  var cx=106,cy=y+RH/2-3;c.beginPath();c.arc(cx,cy,24,0,Math.PI*2);if(i<3){var gg=c.createLinearGradient(cx-24,cy-24,cx+24,cy+24);gg.addColorStop(0,GOLD);gg.addColorStop(1,'#f6e7b4');c.fillStyle=gg}else c.fillStyle='#e2e8f0';c.fill();T(c,String(i+1),cx,cy+9,{s:26,w:900,c:i<3?'#5b4208':'#334155',a:'center'});
  T(c,it.name,150,y+42,{s:30,w:900,c:INK,max:230});T(c,it.ticker+(it.market?' · '+it.market:''),150,y+70,{s:18,w:600,c:MUT,max:230});
  T(c,String(it.ch_score),470,y+52,{s:38,w:900,c:gcol(it.grade),a:'right'});RR(c,482,y+22,40,30,8);c.fillStyle=gcol(it.grade);c.fill();T(c,it.grade,502,y+44,{s:21,w:900,c:'#fff',a:'center'});
  var d=it.dd==null?0:Math.min(1,Math.abs(it.dd)/70);RR(c,560,y+60,200,10,5);c.fillStyle='#e2e8f0';c.fill();if(d>0){RR(c,560+200*(1-d),y+60,Math.max(10,200*d),10,5);c.fillStyle=DN;c.fill()}
  T(c,pc(it.dd),760,y+50,{s:28,w:900,c:DN,a:'right'});if(it.rebound!=null)T(c,'반등 '+pc(it.rebound),560,y+44,{s:16,w:600,c:MUT});
  badge(c,790,y+14,60,56,'재무',it.fin_st);badge(c,856,y+14,60,56,'수급',it.flow_st);badge(c,922,y+14,60,56,'테마',it.theme_st)});
 foot(c,W,H-118+8,'');return m.cv}

function charts(items,date,scale){var list=items.filter(function(i){return i.chart&&i.chart.c&&i.chart.c.length>=2}).slice(0,6);if(!list.length)return null;
 var W=1080,CW=480,CHh=340,rows=Math.ceil(list.length/2),H=210+40+rows*(CHh+22)+140,m=K.make(W,H,scale),c=m.c;c.fillStyle=PAPER;c.fillRect(0,0,W,H);
 band(c,W,'PRICE vs 52W HIGH','종목별 가격 그래프',date+' · 고점에서 얼마나 빠졌고 지금 어디쯤인지');
 list.forEach(function(it,k){var x=50+(k%2)*(CW+20),y=250+Math.floor(k/2)*(CHh+22);card(c,x,y,CW,CHh,22);
  T(c,it.name,x+24,y+46,{s:30,w:900,c:INK,max:260});T(c,it.ticker+(it.market?' · '+it.market:''),x+24,y+74,{s:17,w:600,c:MUT});
  T(c,String(it.ch_score),x+CW-70,y+54,{s:36,w:900,c:gcol(it.grade),a:'right'});RR(c,x+CW-62,y+26,40,30,8);c.fillStyle=gcol(it.grade);c.fill();T(c,it.grade,x+CW-42,y+48,{s:21,w:900,c:'#fff',a:'center'});
  var ch=it.chart,n=ch.c.length,L=x+24,R=x+CW-120,Tp=y+106,Bt=y+240,hi=it.hi52||Math.max.apply(null,ch.c),vals=ch.c.slice();(ch.m||[]).forEach(function(v){if(v!=null)vals.push(v)});
  var mx=Math.max.apply(null,vals.concat([hi])),mn=Math.min.apply(null,vals);if(mx===mn){mx+=1;mn-=1}
  var X=function(i){return L+(R-L)*i/(n-1)},Y=function(v){return Tp+(Bt-Tp)*(1-(v-mn)/(mx-mn))};
  c.save();c.setLineDash([6,5]);c.strokeStyle='#fca5a5';c.lineWidth=2;c.beginPath();c.moveTo(L,Y(hi));c.lineTo(R,Y(hi));c.stroke();c.restore();
  c.beginPath();c.moveTo(X(0),Bt);ch.c.forEach(function(v,i){c.lineTo(X(i),Y(v))});c.lineTo(X(n-1),Bt);c.closePath();c.fillStyle='rgba(199,210,254,.5)';c.fill();
  if(ch.m){c.save();c.setLineDash([8,6]);c.strokeStyle='#f59e0b';c.lineWidth=2;c.beginPath();var pen=false;ch.m.forEach(function(v,i){if(v==null){pen=false;return}if(pen)c.lineTo(X(i),Y(v));else{c.moveTo(X(i),Y(v));pen=true}});c.stroke();c.restore()}
  c.strokeStyle='#334155';c.lineWidth=3;c.lineJoin='round';c.beginPath();ch.c.forEach(function(v,i){if(i)c.lineTo(X(i),Y(v));else c.moveTo(X(i),Y(v))});c.stroke();
  function dot(i,col){c.beginPath();c.arc(X(i),Y(ch.c[i]),6,0,Math.PI*2);c.fillStyle=col;c.fill()}
  dot(ch.hi,'#dc2626');if(ch.lo!==ch.hi&&ch.lo<n-1)dot(ch.lo,'#2563eb');dot(n-1,'#0f172a');
  T(c,'고점',Math.max(L+20,Math.min(X(ch.hi),R-20)),Math.max(Tp-4,Y(ch.c[ch.hi])-12),{s:15,w:800,c:'#dc2626',a:'center'});
  c.fillStyle='#dc2626';c.fillRect(R+14,Math.min(Y(hi),Y(ch.c[n-1])),3,Math.abs(Y(ch.c[n-1])-Y(hi)));
  T(c,pc(it.dd),R+24,(Y(hi)+Y(ch.c[n-1]))/2+8,{s:24,w:900,c:'#2563eb'});T(c,N(it.price)+'원',R+24,Math.max(Tp+10,Y(ch.c[n-1])-12),{s:16,w:600,c:INK});
  T(c,(ch.d0||'').slice(2),L,y+262,{s:14,w:600,c:'#94a3b8'});T(c,(ch.d1||'').slice(2),R,y+262,{s:14,w:600,c:'#94a3b8',a:'right'});T(c,'┅ 20일선',(L+R)/2,y+262,{s:14,w:600,c:'#f59e0b',a:'center'});
  badge(c,x+24,y+274,56,52,'재무',it.fin_st);badge(c,x+86,y+274,56,52,'수급',it.flow_st);badge(c,x+148,y+274,56,52,'테마',it.theme_st);
  if(it.rebound!=null)T(c,'저점 대비 '+pc(it.rebound),x+CW-24,y+314,{s:19,w:700,c:MUT,a:'right'})});
 foot(c,W,H-130,'');return m.cv}

function clean(s){return String(s||'').replace(/\*\*/g,'').replace(/^[\s\-•·*]+/,'').trim()}
function aiParse(text){var out={common:[],picks:[]},sec='',cur=null;
 String(text||'').replace(/\r/g,'').split('\n').forEach(function(raw){var l=raw.trim();if(!l)return;var m;
  if((m=/^##\s+(.*)$/.exec(l))&&l.indexOf('###')!==0){sec=/공통/.test(m[1])?'common':(/두드러진|회복 신호/.test(m[1])&&!/읽는 법/.test(m[1])?'picks':'x');cur=null;return}
  if(/^\[블로그/.test(l)){sec='x';return}
  if(sec==='common'){var t=clean(l.replace(/^###\s*/,''));if(t)out.common.push(t);return}
  if(sec==='picks'){if(/^###\s+/.test(l)){cur={h:clean(l.replace(/^###\s*/,'')),t:''};out.picks.push(cur);return}
   if(/^[-•·*]\s*\**\s*함께 확인/.test(l)||/^[-•·*]\s*함께 확인/.test(l))return;
   var q=clean(l);if(/^[-•·*]/.test(l)){var p=q.split(/\s[—–]\s|\s-\s/);cur={h:p[0],t:p.slice(1).join(' · ')};out.picks.push(cur)}else if(cur){cur.t+=(cur.t?' ':'')+q}}});
 if(!out.common.length&&!out.picks.length){String(text||'').split('\n').map(clean).filter(function(x){return x&&!/^#/.test(x)&&!/^\[/.test(x)}).slice(0,6).forEach(function(x){out.common.push(x)})}
 out.picks=out.picks.filter(function(p){return p.h}).slice(0,5);out.common=out.common.slice(0,5);return out}
function aiCard(text,date,scale){var P=aiParse(text);if(!P.common.length&&!P.picks.length)return null;var W=1080,mc=K.make(10,10,1).c,F600='600 22px '+K.FONT,F800='800 26px '+K.FONT;
 var cm=P.common.map(function(t){return K.wrap(mc,t,880,F600).slice(0,3)}),pk=P.picks.map(function(p){return {h:p.h,l:K.wrap(mc,p.t,880,F600).slice(0,3)}});
 var h1=cm.length?(80+cm.reduce(function(s,l){return s+l.length*30+12},0)+16):0,h2=pk.length?(80+pk.reduce(function(s,p){return s+40+p.l.length*30+16},0)+10):0,H=210+40+(h1?h1+24:0)+(h2?h2+24:0)+150,m=K.make(W,H,scale),c=m.c;
 c.fillStyle=PAPER;c.fillRect(0,0,W,H);band(c,W,'AI ANALYSIS','AI 분석 요약',date+' · AI가 정리한 참고 글(사실·수익을 보장하지 않아요)');var y=250;
 if(h1){card(c,50,y,W-100,h1,24);c.fillStyle=DN;RR(c,76,y+26,6,30,3);c.fill();T(c,'📉 낙폭 종목의 공통 특징',96,y+50,{s:26,w:900,c:INK});var yy=y+92;cm.forEach(function(ls){c.beginPath();c.arc(84,yy-7,5,0,Math.PI*2);c.fillStyle=IND;c.fill();ls.forEach(function(l,k){T(c,l,100,yy+k*30,{s:22,w:600,c:'#334155',max:900})});yy+=ls.length*30+12});y+=h1+24}
 if(h2){card(c,50,y,W-100,h2,24);c.fillStyle=UP;RR(c,76,y+26,6,30,3);c.fill();T(c,'🔍 회복 신호가 두드러진 종목',96,y+50,{s:26,w:900,c:INK});var y4=y+92;pk.forEach(function(p){T(c,p.h,90,y4+4,{s:26,w:900,c:'#312e81',max:900});p.l.forEach(function(l,k){T(c,l,90,y4+38+k*30,{s:22,w:600,c:'#334155',max:900})});y4+=40+p.l.length*30+16});}
 foot(c,W,H-140,'AI가 정리한 의견이며 사실·수익을 보장하지 않아요 · 반드시 직접 확인하세요');return m.cv}

window.ChImg={build:function(items,ai,date,scale,meta){var its=(items||[]).slice().sort(function(a,b){return (b.ch_score-a.ch_score)||((b.axes||0)-(a.axes||0))});
 var out=[{idx:1,label:'낙폭 회복 대시보드',canvas:dash(its,date,scale,meta||{})}];var g=charts(its,date,scale);if(g)out.push({idx:out.length+1,label:'종목별 가격 그래프',canvas:g});
 if(ai&&String(ai).trim()){var a=aiCard(ai,date,scale);if(a)out.push({idx:out.length+1,label:'AI 분석 요약',canvas:a})}return out}};
})();

/* ── 기준 설명(기능 'guide', 서버 호출 없음) ── */
function chSecGuide(box){var g=el('div','chGd');
 function H(t){g.appendChild(el('h4',null,t))}function P(t){g.appendChild(el('p',null,t))}function UL(a){var u=el('ul');a.forEach(function(x){u.appendChild(el('li',null,x))});g.appendChild(u)}
 H('이 메뉴는 무엇을 보여 주나요?');P('52주(약 1년) 최고가에서 많이 떨어진 종목 가운데, 주가만 눌린 것이 아니라 재무·수급·테마가 다시 살아나는 모습이 있는지 점검해서 그래프와 함께 보여 줘요. “이 종목을 사라”는 뜻이 아니라, 떨어진 종목 중에서 회복 신호가 몇 가지나 확인되는지를 정리한 정보예요. 이미 많이 떨어진 종목은 이유가 있어서일 수 있고 더 떨어질 수도 있어요(떨어지는 칼날).');
 H('진행 순서 — 리스트 → AI 분석 → 대시보드 이미지 → 블로그 쓰기');UL(['① 낙폭 회복 후보: 관리자가 낙폭 스캔을 마치면 목록이 새로 뜨고 위쪽 단계 바가 ①을 완료로 표시해요.','② AI 분석: 목록의 낙폭·재무·수급·테마 데이터를 담은 프롬프트를 내 AI에 붙여 넣고, AI 답변을 복사해 오면 읽어 와요(서버가 AI를 부르지 않아요). 관리자는 답변이 서버에 저장돼요.','③ 대시보드 이미지: 요약 타일·3축 현황·TOP 10 표, 종목별 가격 그래프, AI 분석 요약을 이미지로 그려 저장해요.','④ 블로그 쓰기(관리자): 목록과 AI 분석으로 블로그용 글(HTML)을 만들어요. 복사해서 블로그 글쓰기 화면에 붙여 넣고, ③ 이미지는 직접 올려요.','관리자는 [⚙ 설정]의 ‘단계 진행 방식’에서 ②~④를 스캔 직후 자동으로 이어 갈지(자동) 하나씩 직접 누를지(수동) 고를 수 있어요.']);
 H('① 낙폭 — 어떻게 고르나요?');P('최근 252거래일의 고가 중 가장 높은 값을 52주 고점으로 보고, 현재가가 그 값보다 몇 % 낮은지로 계산해요. 기본은 -30% 이상 떨어진 종목이고(-20~-60% 선택), 동전주(1,000원 미만)·시총 미달(코스피 300억·코스닥 200억 미만)·상장폐지 위험 종목은 처음부터 빼요. 수급·재무는 낙폭 -20% 이상 종목만 받아 와요.');
 H('② 회복 신호 3축');var tb=chTblBuild(['축','✅ 회복 확인','🔸 일부 회복'],['','','']);
 [['💹 재무(분기 영업이익)','4가지 중 3개 이상: 최근 분기 영업이익 흑자 · 전 분기보다 증가 · 매출이 전년 동기(없으면 전 분기)보다 증가 · 부채비율 200% 이하. 단 4분기 연속 적자이거나 부채비율 300% 초과면 ❌','2개 충족'],
  ['💰 수급(20일)','외국인·기관이 최근 5일 모두 순매수(쌍끌이)이거나, 이전 15일은 순매도·중립이었다가 최근 5일 합계가 순매수로 바뀐 경우(수급전환)','최근 5일 합계만 순매수'],
  ['🔥 테마(네이버 테마)','속한 테마 중 가장 센 테마가 오늘 +1% 이상이고, 같은 테마의 낙폭 종목 절반 이상이 20일선 위','테마가 오늘 +이거나 동료 종목 절반 이상이 20일선 위']].forEach(function(r){var tr=el('tr');r.forEach(function(x){tr.appendChild(el('td',null,x))});tb.t.appendChild(tr)});g.appendChild(tb.wrap);
 P('자료를 받지 못한 축은 ⚪자료 없음으로 표시하고 점수도 0점이에요. 수급은 거래소 공식 순매수 대금이 아니라 ‘순매수 수량 × 종가’로 추정한 근사치이고, 최근 20거래일이 최대예요.');
 H('③ 회복 점수(0~100)');var t2=chTblBuild(['항목','기준','점수'],['','','r']);
 [['낙폭','-50%↓ / -40%↓ / -30%↓ / -20%↓','25 / 20 / 15 / 8'],['재무','회복 확인 / 일부 회복','25 / 12'],['수급','회복 확인 / 일부 회복','25 / 10'],['테마','회복 확인 / 일부 회복','15 / 7'],['가격 안정','저점 대비 +10% 이상 반등 · 5·20일선 위 단기 상승','각 +5']].forEach(function(r){var tr=el('tr');tr.appendChild(el('td',null,r[0]));tr.appendChild(el('td',null,r[1]));tr.appendChild(el('td','r',r[2]));t2.t.appendChild(tr)});g.appendChild(t2.wrap);
 P('등급은 S(75점 이상)·A(60점 이상)·B예요. 점수가 높다는 것은 낙폭이 크고 회복 신호가 많이 확인된다는 뜻일 뿐 오른다는 뜻이 아니에요.');
 H('그래프 읽는 법');UL(['📉 가격: 굵은 선은 종가, 점선은 20일선, 빨간 점은 52주 고점, 파란 점은 고점 이후 저점이에요. 오른쪽 빨간 숫자가 고점 대비 낙폭이에요.','💹 재무: 최근 6개 분기 영업이익(억원). 빨간 막대는 흑자, 파란 막대는 적자이고 가장 진한 막대가 최근 분기예요.','💰 수급: 최근 20거래일 일별 순매수(억원). 보라는 외국인, 주황은 기관이고 연한 파란 배경이 최근 5일이에요.','🔥 테마: 속한 테마(최대 3개)의 오늘 등락률. 스캔이 2일 이상 쌓이면 가장 센 테마의 날짜별 흐름도 그려져요.']);
 H('성과 기록은 어떻게 읽나요?');P('관리자가 저장한 날의 가격과 가장 최근 스캔 가격을 비교한 값이에요. 같은 날 같은 종목은 처음 저장한 값만 남아요. 비용·세금·보유 기간을 반영하지 않았고, 이 목록을 따라 투자했을 때의 수익이 아니에요. 예전 ‘도전점수’ 방식으로 저장된 기록은 뜻이 달라 계산에서 빼요.');
 H('읽을 때 꼭 알아 두세요');UL(['낙폭·가격은 관리자가 마지막으로 스캔한 일봉이라 오늘보다 앞설 수 있어요(상단의 스캔 시각 확인).','시총 상위 일부(스캔 대상 수만큼)만 훑어요. 목록에 없다고 회복 신호가 없다는 뜻은 아니에요.','ETF·스팩·우선주는 종목 목록의 ‘일반 주식’ 분류에서 제외돼요.','재무는 네이버 증권 요약이라 최신 공시와 차이가 있을 수 있어요. 일회성 이익으로 흑자가 된 경우도 구별하지 못해요.','이 화면은 정보 제공용이며 특정 종목의 매수·매도 권유가 아니에요. 투자 판단과 책임은 이용자 본인에게 있어요.']);
 box.appendChild(g)}

/* ── 관리자 전용 카드: 기준 저장 + 점검(회원 화면에서는 숨김) ── */
function chAdmLoad(){var b=$('chAdm');if(!b)return;api('/admin/api/challenge/diag').then(function(j){chAdmDraw(j)})}
function chAdmDraw(j){var b=$('chAdm');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'🛠 도전주 설정·점검 (관리자만 보여요)'));if(!j||j.error){b.appendChild(el('p','note bad','점검 정보를 읽지 못했어요.'));return}
 var T=j.tables||{};function nn(v){return v==null?'표 없음':v.toLocaleString('ko-KR')+'행'}
 b.appendChild(el('p','note','낙폭 스캔 결과 '+nn(T.challenge_dd_cache)+' · 테마 연결 '+(T.stock_theme_map==null?'없음':T.stock_theme_map.toLocaleString('ko-KR')+'종목')+' · 테마 목록 '+(T.collect_theme_list==null?'없음':T.collect_theme_list+'개')));
 if(j.meta&&j.meta.universe!=null)b.appendChild(el('p','note','스캔 '+j.meta.universe+'종목 · 낙폭 20%↑ '+j.meta.cand+'종목 · 마지막 스캔 '+(j.meta.scan_at||'-')+' · 시세 기준일 '+(j.meta.price_asof||'-')+' · 시장 미상 '+j.no_market+'종목 · 회복 확인 재무 '+j.axes.fin+' · 수급 '+j.axes.flow+' · 테마 '+j.axes.theme+' · 자료 없음 재무 '+j.na.fin+' · 수급 '+j.na.flow+' · 테마 '+j.na.theme+' · 위험 제외 대상 '+j.meta.risk_n));
 if(j.missing&&j.missing.length)b.appendChild(el('p','note bad','아직 스캔 결과가 없어요 — 위쪽 [🔎 낙폭 스캔 시작]을 눌러 주세요.'));
 var c=j.cfg||{markets:['KOSPI','KOSDAQ'],drop_pct:30,min_axes:1,limit:60,exclude_risk:1,scan_limit:400},S={drop_pct:String(c.drop_pct),min_axes:String(c.min_axes),limit:String(c.limit),scan_limit:String(c.scan_limit)};CH.cfg=c;
 b.appendChild(el('p','note','기준(이용자 화면의 기본값): 시장·낙폭 기준·회복 확인 축·개수·스캔 대상·위험 종목 제외'));var bar=el('div','bar');
 var ks=el('input');ks.type='checkbox';ks.checked=c.markets.indexOf('KOSPI')>=0;var kd=el('input');kd.type='checkbox';kd.checked=c.markets.indexOf('KOSDAQ')>=0;
 var l1=el('label');l1.appendChild(ks);l1.appendChild(document.createTextNode(' 코스피 '));var l2=el('label');l2.appendChild(kd);l2.appendChild(document.createTextNode(' 코스닥 '));bar.appendChild(l1);bar.appendChild(l2);
 chSel(bar,'기본 낙폭 기준',S,'drop_pct',[['20','-20%'],['25','-25%'],['30','-30%(원본)'],['40','-40%'],['50','-50%'],['60','-60%']]);chSel(bar,'기본 회복 확인 축',S,'min_axes',[['0','전체'],['1','1개↑'],['2','2개↑'],['3','3개']]);
 chSel(bar,'목록 상한',S,'limit',[['30','30개'],['60','60개'],['120','120개'],['200','200개']]);chSel(bar,'기본 스캔 대상',S,'scan_limit',[['200','200종목'],['400','400종목'],['600','600종목'],['1000','1000종목']]);
 var rk=el('input');rk.type='checkbox';rk.checked=!!c.exclude_risk;var l3=el('label');l3.appendChild(rk);l3.appendChild(document.createTextNode(' 상장폐지·거래정지 위험 제외'));bar.appendChild(l3);
 bar.appendChild(bt('💾 기준 저장','bt',function(){var mk=[];if(ks.checked)mk.push('KOSPI');if(kd.checked)mk.push('KOSDAQ');if(!mk.length){toast('코스피나 코스닥 중 하나는 골라 주세요.');return}
  apiJ('/admin/api/challenge/cfg',{markets:mk,drop_pct:S.drop_pct,min_axes:S.min_axes,limit:S.limit,scan_limit:S.scan_limit,exclude_risk:rk.checked?1:0}).then(function(r){if(r.error){toast(r.error);return}toast('기준을 저장했어요');CH.ld.data=null;CH.ld.inited=false;CH.scanSel=null;chAdmLoad()})}));b.appendChild(bar);
 b.appendChild(bt('🔄 읽어 둔 자료 비우고 다시 읽기','bt2',function(){apiJ('/admin/api/challenge/reload',{}).then(function(r){if(r.error){toast(r.error);return}CH.ld.data=null;CH.ex={};chAdmDraw(r);chShow();toast('다시 읽었어요')})}))}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_settings({"challenge_cfg": json.dumps(DEFAULT_CFG, ensure_ascii=False)}, {"challenge_cfg": _valid_cfg})
    C.register_menu({"id": MENU, "label": "도전주", "icon": "🎯", "public_path": "/m/challenge", "admin_path": "/admin#ch",
                     "desc": "52주 고점 대비 크게 떨어진 종목 가운데 재무·수급·테마가 다시 살아나는 종목을 그래프와 함께 정리해 보여 줘요. 추천이 아니라 회복 신호가 보이는 낙폭 종목 목록(정보)이며 투자 권유가 아니에요.",
                     "access": "admin"})
    C.register_prompt("challenge_ai", {
        "title": "도전주(낙폭 회복) AI 프롬프트", "default": CH_DEFAULT, "required": ["{items_text}"], "must_have": [],
        "vars": "{items_text}=낙폭·회복 신호 종목 목록(필수) · {today}=오늘 날짜 · {market_label}=시장 이름 · {count}=종목 수",
        "desc": "도전주 화면의 [AI 프롬프트 만들기]가 AI에게 보내는 요청문. 매수·매도 권유를 하지 않도록 쓰는 것이 원칙이에요."})
    C.register_admin_tab("ch", "🎯 도전주", TAB_JS, "chLoad", menu=MENU)
    C.register_flow(MENU, "🎯 도전주", "① 낙폭 스캔(직접 시작)", [
        {"id": "ai", "label": "② AI 분석", "desc": "스캔이 끝나 낙폭 회복 목록이 뜨면 AI 요청문 창을 자동으로 열어요. AI 답변을 복사해 돌아오면 저장되고 다음 단계로 이어져요(오늘 저장한 AI 분석이 있으면 건너뛰어요)."},
        {"id": "img", "label": "③ 대시보드 이미지", "desc": "AI 단계가 끝나면 블로그용 대시보드 이미지를 자동으로 그려요(저장은 [⚙ 저장 설정]의 자동/수동 설정을 따라요)."},
        {"id": "blog", "label": "④ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요."},
        {"id": "post", "label": "⑤ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요. 브라우저가 복사·새 창을 막으면 [📋 복사하고 블로그 열기]를 한 번 눌러 주세요."}])
    # ── 기능별 공개: 추천형에 가까워 법적 검토 전에는 모두 관리자만(default admin). 관리자가 [🎚 기능 공개]에서 하나씩 연다. ──
    F = C.register_feature
    F(MENU, "list", "후보 목록 보기", "52주 고점 대비 낙폭과 재무·수급·테마 회복 판정(✅🔸❌⚪), 회복 점수·등급·신호. 이 기능이 열려 있어야 목록이 나와요(주소: 목록).", default="admin",
      endpoints=["/admin/api/challenge/list"])
    F(MENU, "detail", "그래프·상세 수치", "가격(고점·저점·20일선)·분기 영업이익·20일 수급·테마 등락 그래프와 근거 문장, 종목별 점수 구성. 잠기면 목록·보관함에서 이 값들이 빠져요.", default="admin",
      endpoints=["/admin/api/challenge/explain"])
    F(MENU, "saved", "과거 결과 보관함", "관리자가 저장해 둔 과거 결과 목록과 그때의 종목·낙폭·점수(저장 당시 값).", default="admin",
      endpoints=["/admin/api/challenge/saved", "/admin/api/challenge/saved/get"])
    F(MENU, "track", "성과 기록", "저장일 가격 대비 최근 스캔 가격의 등락 기록과 등급·점수대·신호별 통계(읽기 전용).", default="admin",
      endpoints=["/admin/api/challenge/track"])
    F(MENU, "guide", "기준 설명", "낙폭 기준·3축 판정·회복 점수·그래프 읽는 법 해설(서버 호출 없음).", default="admin", endpoints=[])
    F(MENU, "ai", "AI 해설 프롬프트", "선택한 종목 데이터로 AI 프롬프트를 만들고 답변을 붙여 보기(수동 — 서버가 AI를 부르지 않아요).", default="admin",
      endpoints=["/admin/api/challenge/prompt"], kind="action")
    F(MENU, "img", "요약 이미지 내려받기", "낙폭 회복 후보를 대시보드·가격 그래프·AI 분석 요약 이미지로 그려 내려받아요(그래프 이미지는 '그래프·상세 수치'가 열려 있어야 포함).", default="admin", endpoints=[], kind="tool")
    F(MENU, "exp", "표·이미지 내려받기", "지금 보는 표를 CSV 파일이나 PNG 이미지로 내려받기", default="admin", endpoints=[], kind="action")
    # AI 분석 저장·불러오기(ai GET/POST)·블로그 글 만들기(blog)는 관리자 업무 → 어떤 기능에도 넣지 않았다(회원은 AI 답변을 이 화면에만 보관).
    # 낙폭 스캔(scan/start·status·stop)·결과 저장(save)·보관함 삭제(saved/delete)·성과 기록 삭제(track/delete)·기준 저장(cfg)·점검(diag, reload)은
    # 관리자 업무 → 어떤 기능에도 넣지 않았다(회원 화면에서는 404).
    return bp
