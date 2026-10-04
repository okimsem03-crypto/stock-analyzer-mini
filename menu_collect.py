"""📥 수급·테마 가져오기 (관리자 전용) — 원본 프로그램의 [투자자 수급 스캔]·[네이버 테마 임포트]를 웹 미니에 맞게 옮긴 수집기.

원본은 데스크톱 프로그램이 직접 네이버에서 받아 오지만, 웹 미니는 서버(Render)가 네이버 모바일 증권 주소에서 받아 와서
수급분석 메뉴가 읽는 표에 채운다. (예전에는 PC에서 만든 표를 [📦 데이터 가져오기]로 올려야 했다.)

  · investor_scan_cache  종목별 외국인·기관 순매수 대금(원) 1일·5일·20일 합계 + 기준일 base_date  ← 수급 가져오기
  · stock_price_cache    현재가·등락률·시가총액(억)·시장 — 수급 가져오기가 함께 채움(점수·RSI 같은 기존 값은 건드리지 않음)
  · stock_theme_map      종목-테마 연결(theme_type='naver')                                     ← 테마 가져오기
  · collect_theme_list   네이버 테마 목록(테마 번호·이름·종목 수·등락률)                         ← 테마 가져오기

네이버 주소(실측 확인)
  /api/stocks/marketValue/{KOSPI|KOSDAQ}?page&pageSize   시가총액 순 종목 목록(종목 선정용)
  /api/stock/{code}/trend?pageSize=20                    일별 외국인·기관·개인 순매수 수량 + 종가
  /api/stocks/theme?page&pageSize                        테마 목록
  /api/stocks/theme/{no}?page&pageSize                   테마 안 종목

계산: 순매수 금액(원) ≈ 그날 순매수 수량 × 그날 종가 를 날마다 구해 1일(가장 최근 거래일)·5일·20일로 더한다.
      → 거래소 공식 순매수 대금이 아니라 '수량×종가' 근사치이고, 이 주소가 주는 기간이 최근 20거래일이라 20일이 최대다.
수집은 서버 안 백그라운드 스레드 하나로 돌고(동시에 한 작업만), 진행 상황을 화면이 계속 물어본다. 멈춤 버튼이 있다.
모든 주소는 관리자 전용(회원 화면에 열지 않음) — 외부 사이트를 호출하는 쓰기 작업이라서다.
"""
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from flask import Blueprint, request

from menu_ctx import C

bp = Blueprint("collect", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_now_kst", "setting_get", "setting_set")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

BASE = "https://m.stock.naver.com"
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
LIMITS = (100, 200, 300, 500)
DEFAULT_LIMIT = 300
WORKERS = 6
KEY_INV = "collect_investor_last"
KEY_THEME = "collect_theme_last"

_LOCK = threading.Lock()
_ST = {"running": False, "kind": "", "phase": "", "total": 0, "done": 0, "ok": 0, "fail": 0, "skip": 0, "cur": "", "started": 0.0,
       "ended": 0.0, "error": "", "stop": False, "msg": "", "result": {}}


# ══════════════════════════════════════════════════════════════
# 표 만들기(앱이 시작될 때 한 번) — 없으면 만든다
# ══════════════════════════════════════════════════════════════
def _ensure_tables(cur, use_pg):
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    cur.execute(f"""CREATE TABLE IF NOT EXISTS investor_scan_cache(
        ticker TEXT PRIMARY KEY, name TEXT, foreign_1 {real} DEFAULT 0, inst_1 {real} DEFAULT 0, foreign_5 {real} DEFAULT 0,
        inst_5 {real} DEFAULT 0, foreign_20 {real} DEFAULT 0, inst_20 {real} DEFAULT 0, scanned_at TEXT DEFAULT '', base_date TEXT DEFAULT '')""")
    # 개인 순매수(시장수급 메뉴용) — 열이 없으면 덧붙인다(옛 표라도 오류 없이)
    try:
        if use_pg:
            for c_ in ("retail_1", "retail_5", "retail_20"):
                cur.execute(f"ALTER TABLE investor_scan_cache ADD COLUMN IF NOT EXISTS {c_} {real} DEFAULT 0")
        else:
            have_ = {r_[1] for r_ in cur.execute("PRAGMA table_info(investor_scan_cache)").fetchall()}
            for c_ in ("retail_1", "retail_5", "retail_20"):
                if c_ not in have_:
                    cur.execute(f"ALTER TABLE investor_scan_cache ADD COLUMN {c_} {real} DEFAULT 0")
    except Exception as e_:
        print(f"[가져오기] 개인 수급 열 추가 실패(무시): {e_}")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS market_flow_day(
        market TEXT NOT NULL, date TEXT NOT NULL, actor TEXT NOT NULL, src TEXT NOT NULL DEFAULT 'index', amount {real} DEFAULT 0,
        updated_at TEXT DEFAULT '', PRIMARY KEY(market,date,actor,src))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS stock_theme_map(
        ticker TEXT NOT NULL, name TEXT NOT NULL, market TEXT DEFAULT '', sector TEXT DEFAULT '', theme TEXT NOT NULL,
        theme_type TEXT DEFAULT 'user', PRIMARY KEY(ticker,theme))""")
    big = "BIGINT" if use_pg else "INTEGER"
    cur.execute(f"""CREATE TABLE IF NOT EXISTS stock_price_cache(
        ticker TEXT PRIMARY KEY, name TEXT, market TEXT, sector TEXT, price {big}, day_pct {real}, per TEXT, pbr TEXT, market_cap TEXT,
        cap_num {big} DEFAULT 0, rsi {real}, score {big}, updated_at TEXT DEFAULT '')""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS collect_theme_list(
        no {big} PRIMARY KEY, name TEXT NOT NULL DEFAULT '', total {big} DEFAULT 0, change_rate {real} DEFAULT 0,
        rise {big} DEFAULT 0, fall {big} DEFAULT 0, steady {big} DEFAULT 0, fetched_at TEXT DEFAULT '')""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS theme_day(
        date TEXT NOT NULL, no {big} NOT NULL, name TEXT NOT NULL DEFAULT '', rate {real} DEFAULT 0,
        rise {big} DEFAULT 0, fall {big} DEFAULT 0, steady {big} DEFAULT 0, PRIMARY KEY(date,no))""")


# ══════════════════════════════════════════════════════════════
# 네이버 호출 — 한 곳으로 모아 둠(시험에서는 이 함수만 바꿔 끼운다)
# ══════════════════════════════════════════════════════════════
def _get_json(path, params=None):
    """네이버 모바일 증권 JSON 한 번 받기. 실패하면 한 번 더. 끝내 안 되면 예외."""
    last = None
    for k in range(2):
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
    """'-350,942' / '+614,278' / '276,000' → 정수. 읽을 수 없으면 0."""
    try:
        t = re.sub(r"[^0-9.\-]", "", str(s or "").replace("+", ""))
        if t in ("", "-", "."):
            return 0
        return int(round(float(t)))
    except Exception:
        return 0


def _fl(s):
    try:
        t = re.sub(r"[^0-9.\-]", "", str(s or "").replace("+", ""))
        return float(t) if t not in ("", "-", ".") else None
    except Exception:
        return None


def _bdate(s):
    d = re.sub(r"\D", "", str(s or ""))[:8]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""


def _mkt(it):
    ex = it.get("stockExchangeType") or {}
    n = str(ex.get("nameEng") or ex.get("name") or "").upper()
    return n if n in ("KOSPI", "KOSDAQ") else ""


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


def _begin(kind, msg):
    with _LOCK:
        if _ST["running"]:
            return False
        _ST.update(running=True, kind=kind, phase="start", total=0, done=0, ok=0, fail=0, skip=0, cur="", started=time.time(), ended=0.0,
                   error="", stop=False, msg=msg, result={})
    return True


def _end(error="", result=None):
    with _LOCK:
        _ST.update(running=False, ended=time.time(), error=error, phase="end", result=result or {})
        if _ST["stop"] and not error:
            _ST["msg"] = "⏹ 멈췄어요 — 여기까지 가져온 자료는 저장되어 있어요."


def _last_get(key):
    try:
        v = setting_get(key, "")
        return json.loads(v) if v else {}
    except Exception:
        return {}


def _last_set(key, d):
    try:
        setting_set(key, json.dumps(d, ensure_ascii=False))
    except Exception as e:
        print(f"[가져오기] 기록 저장 실패(무시): {e}")


def _reload_flow():
    try:
        m = sys.modules.get("menu_flow")
        if m is not None:
            m._load(force=True)
    except Exception as e:
        print(f"[가져오기] 수급분석 다시 읽기 실패(무시): {e}")
    try:
        t = sys.modules.get("menu_theme")
        if t is not None:
            t._CACHE["d"] = None          # 네이버테마 화면이 읽어 둔 자료 비우기
    except Exception as e:
        print(f"[가져오기] 네이버테마 다시 읽기 실패(무시): {e}")


# ══════════════════════════════════════════════════════════════
# DB 쓰기 — 한 연결로 묶어서(PG 는 ? → %s)
# ══════════════════════════════════════════════════════════════
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


def _stamp():
    return _now_kst().strftime("%Y-%m-%d %H:%M:%S")


# ══════════════════════════════════════════════════════════════
# ① 수급 가져오기
# ══════════════════════════════════════════════════════════════
def _universe(limit):
    """시가총액 순 종목 목록(코스피·코스닥 각각 limit개까지 받아 합쳐 시총 큰 순서로 limit개)."""
    pool = {}
    for mk in ("KOSPI", "KOSDAQ"):
        got, page = 0, 1
        while got < limit and page <= 12:
            if _stopped():
                return []
            data = _get_json(f"/api/stocks/marketValue/{mk}", {"page": page, "pageSize": 100})
            stocks = data.get("stocks") or []
            if not stocks:
                break
            for it in stocks:
                tk = str(it.get("itemCode") or "").strip().upper()
                if not TICKER_RE.match(tk) or tk in pool:
                    continue
                if str(it.get("stockEndType") or "stock") not in ("stock", ""):
                    continue
                pool[tk] = {"ticker": tk, "name": str(it.get("stockName") or tk)[:40], "market": _mkt(it) or mk,
                            "price": _num(it.get("closePrice")), "pct": _fl(it.get("fluctuationsRatio")), "cap": _num(it.get("marketValue"))}
                got += 1
            tc = data.get("totalCount")
            if tc is not None and page * 100 >= int(tc or 0):
                break
            page += 1
            time.sleep(0.05)
    rows = sorted(pool.values(), key=lambda r: -r["cap"])
    return rows[:limit]


def _one_ticker2(tk):
    """종목 하나의 최근 20거래일 수급 → (7개 값, 개인 1·5·20일, 날짜별 [(날짜,외국인,기관,개인)]). 값이 없으면 None.
    금액은 '순매수 수량 × 그날 종가'(원)."""
    data = _get_json(f"/api/stock/{tk}/trend", {"pageSize": 20})
    if not isinstance(data, list) or not data:
        return None
    rows = []
    for d in data:
        bd = _bdate(d.get("bizdate"))
        px = abs(_num(d.get("closePrice")))
        if not bd or not px:
            continue
        rows.append((bd, _num(d.get("foreignerPureBuyQuant")) * px, _num(d.get("organPureBuyQuant")) * px, _num(d.get("individualPureBuyQuant")) * px))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0], reverse=True)         # 최신 날짜가 앞
    f = [r[1] for r in rows]
    i = [r[2] for r in rows]
    p = [r[3] for r in rows]
    t7 = (f[0], i[0], sum(f[:5]), sum(i[:5]), sum(f[:20]), sum(i[:20]), rows[0][0])
    return t7, (p[0], sum(p[:5]), sum(p[:20])), rows


def _one_ticker(tk):
    """종목 하나의 최근 20거래일 수급 → (f1,i1,f5,i5,f20,i20,기준일). 값이 없으면 None."""
    r = _one_ticker2(tk)
    return r[0] if r else None


def _save_investor(batch):
    """batch: [(row, vals)] — investor_scan_cache 는 지우고 다시 넣고, stock_price_cache 는 있으면 값만 고치고 없으면 넣는다."""
    now = _stamp()
    ops = []
    for r, v in batch:
        ops.append(("DELETE FROM investor_scan_cache WHERE ticker=?", (r["ticker"],)))
        ops.append(("INSERT INTO investor_scan_cache(ticker,name,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,scanned_at,base_date) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (r["ticker"], r["name"], float(v[0]), float(v[1]), float(v[2]), float(v[3]), float(v[4]), float(v[5]), now, v[6])))
    _run(ops)


def _univ_complete(agg):
    """수집한 종목 수가 적은 날짜(상장일이 짧은 종목만 있는 오래된 날짜)는 합계가 왜곡되므로 빼고, 모든 날짜를 그대로 둔다(시장별 최근 20거래일)."""
    dates = sorted({k[1] for k in agg}, reverse=True)[:20]
    keep = set(dates)
    return {k: v for k, v in agg.items() if k[1] in keep}


_RETAIL_WARNED = []


def _add_retail_cols():
    """📦 가져오기로 올린 표처럼 개인 열이 없는 표에 열을 덧붙인다(실패하면 False)."""
    real = "DOUBLE PRECISION" if C._USE_PG else "REAL"
    ok_ = False
    for c_ in ("retail_1", "retail_5", "retail_20"):
        try:
            _run([(f"ALTER TABLE investor_scan_cache ADD COLUMN {c_} {real} DEFAULT 0", None)])
            ok_ = True
        except Exception:
            pass
    return ok_


def _save_retail(batch):
    """개인 순매수 1·5·20일 — 열이 없는 옛 표면 열을 덧붙여 보고, 안 되면 조용히 건너뛴다(한 번만 알림)."""
    ops = [("UPDATE investor_scan_cache SET retail_1=?,retail_5=?,retail_20=? WHERE ticker=?", (float(p[0]), float(p[1]), float(p[2]), r["ticker"])) for r, p in batch]
    for attempt in (0, 1):
        try:
            for k in range(0, len(ops), 200):
                _run(ops[k:k + 200])
            return
        except Exception as e:
            if attempt == 0 and _add_retail_cols():
                continue
            if not _RETAIL_WARNED:
                _RETAIL_WARNED.append(1)
                print(f"[가져오기] 개인 수급 저장 실패(무시): {e}")
            return


def _save_univ_daily(agg, add=False):
    """수집 종목 합산 일별 수급(시장수급 메뉴용) — agg={(시장,날짜,주체): 원}.
    add=False(처음부터 모두 받은 경우): 기존 합산을 모두 지우고 새로 넣는다. add=True(오늘 이어서 받은 경우): 기존 합계에 더한다."""
    if not agg:
        return
    try:
        old = {}
        if add:
            for mk, dt, ac, am in (_dbx("SELECT market,date,actor,amount FROM market_flow_day WHERE src='univ'", (), fetch=True) or []):
                old[(str(mk), str(dt), str(ac))] = float(am or 0)
        ops = [("DELETE FROM market_flow_day WHERE src='univ'", None)] if not add else []
        for (mk, dt, ac), v in agg.items():
            if add:
                ops.append(("DELETE FROM market_flow_day WHERE market=? AND date=? AND actor=? AND src='univ'", (mk, dt, ac)))
            ops.append(("INSERT INTO market_flow_day(market,date,actor,src,amount) VALUES(?,?,?,?,?)", (mk, dt, ac, "univ", float(v) + old.get((mk, dt, ac), 0.0))))
        for k in range(0, len(ops), 300):
            _run(ops[k:k + 300])
    except Exception as e:
        print(f"[가져오기] 수집 종목 합산 저장 실패(무시): {e}")


def _save_prices(rows):
    have = {str(x[0]) for x in (_dbx("SELECT ticker FROM stock_price_cache", (), fetch=True) or [])}
    now = _stamp()
    ops = []
    for r in rows:
        if r["ticker"] in have:
            ops.append(("UPDATE stock_price_cache SET name=?,market=?,price=?,day_pct=?,cap_num=?,updated_at=? WHERE ticker=?",
                        (r["name"], r["market"], int(r["price"] or 0), r["pct"], int(r["cap"] or 0), now, r["ticker"])))
        else:
            ops.append(("INSERT INTO stock_price_cache(ticker,name,market,sector,price,day_pct,cap_num,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (r["ticker"], r["name"], r["market"], "", int(r["price"] or 0), r["pct"], int(r["cap"] or 0), now)))
    for k in range(0, len(ops), 200):
        _run(ops[k:k + 200])


def _today_done():
    """오늘 이미 가져온 종목(이어서 하기용) — scanned_at 날짜가 오늘인 종목."""
    today = _now_kst().strftime("%Y-%m-%d")
    try:
        rows = _dbx("SELECT ticker,scanned_at FROM investor_scan_cache", (), fetch=True) or []
    except Exception:
        return set()
    return {str(a).upper() for a, b in rows if str(b or "")[:10] == today}


def _investor_worker(limit, skip_today):
    try:
        _set(phase="list", msg="① 시가총액 상위 종목 목록 받는 중…")
        uni = _universe(limit)
        if _stopped():
            return _end()
        if not uni:
            return _end("종목 목록을 받지 못했어요. 네이버 응답이 없거나 주소 구조가 바뀌었을 수 있어요.")
        try:
            _save_prices(uni)
        except Exception as e:
            print(f"[가져오기] 시세 저장 실패(무시): {e}")
        skip = _today_done() if skip_today else set()
        todo = [r for r in uni if r["ticker"] not in skip]
        _set(phase="trend", total=len(uni), skip=len(uni) - len(todo), done=len(uni) - len(todo), msg="② 종목별 수급 받는 중…")
        buf, rbuf, bases, aborted = [], [], [], False
        agg = {}
        first_fail = {"n": 0, "ok": 0}

        def job(r):
            if _stopped():
                return r, None, "stop"
            try:
                return r, _one_ticker2(r["ticker"]), ""
            except Exception as e:
                return r, None, str(e)[:60]

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for r, v, err in ex.map(job, todo):
                if err == "stop":
                    continue
                with _LOCK:
                    _ST["done"] += 1
                    _ST["cur"] = f"{r['name']}({r['ticker']})"
                    if v:
                        _ST["ok"] += 1
                    else:
                        _ST["fail"] += 1
                if v:
                    buf.append((r, v[0]))
                    rbuf.append((r, v[1]))
                    for dd_, fa_, ia_, pa_ in v[2]:
                        for ac_, am_ in (("foreign", fa_), ("inst", ia_), ("retail", pa_)):
                            k_ = (r["market"] or "KOSPI", dd_, ac_)
                            agg[k_] = agg.get(k_, 0.0) + am_
                    bases.append(v[0][6])
                    first_fail["ok"] += 1
                else:
                    first_fail["n"] += 1
                if len(buf) >= 40:
                    _save_investor(buf)
                    _save_retail(rbuf)
                    buf, rbuf = [], []
                if first_fail["ok"] == 0 and first_fail["n"] >= 15:
                    _set(stop=True)           # 처음 15개가 모두 실패 → 네이버 쪽 문제로 보고 중단(남은 일은 곧 끝남)
                    aborted = True
                    break
        if buf:
            _save_investor(buf)
            _save_retail(rbuf)
        if agg and not aborted:
            _save_univ_daily(_univ_complete(agg), add=bool(skip))
        if aborted:
            return _end("처음 15개 종목이 모두 실패해 멈췄어요. 잠시 뒤 다시 시도해 주세요(네이버 응답 없음·차단 가능).")
        snap = _snapshot()
        base = max(bases) if bases else ""
        res = {"at": _stamp(), "universe": len(uni), "ok": snap["ok"], "fail": snap["fail"], "skip": snap["skip"], "base_date": base,
               "limit": limit, "stopped": bool(_stopped())}
        _last_set(KEY_INV, res)
        _reload_flow()
        _end("", res)
        if not res["stopped"]:
            _set(msg=f"✅ 수급 {snap['ok']}종목을 가져왔어요" + (f" (이미 오늘 가져온 {snap['skip']}종목은 건너뜀)" if snap["skip"] else "") + (f" · 기준일 {base}" if base else ""))
    except Exception as e:
        _end(f"가져오는 중 오류: {str(e)[:120]}")


# ══════════════════════════════════════════════════════════════
# ② 네이버 테마 가져오기
# ══════════════════════════════════════════════════════════════
def _theme_list():
    out, page = [], 1
    while page <= 20:
        data = _get_json("/api/stocks/theme", {"page": page, "pageSize": 50})
        groups = data.get("groups") or []
        if not groups:
            break
        for g in groups:
            if g.get("no") is None or not g.get("name"):
                continue
            out.append({"no": int(g["no"]), "name": str(g["name"])[:80], "total": _num(g.get("totalCount")), "rate": _fl(g.get("changeRate")) or 0.0,
                        "rise": _num(g.get("riseCount")), "fall": _num(g.get("fallCount")), "steady": _num(g.get("steadyCount"))})
        tc = data.get("totalCount")
        if tc is not None and len(out) >= int(tc or 0):
            break
        page += 1
        time.sleep(0.05)
    return out


def _theme_stocks(no):
    rows, page = [], 1
    while page <= 6:
        data = _get_json(f"/api/stocks/theme/{no}", {"page": page, "pageSize": 50})
        stocks = data.get("stocks") or []
        if not stocks:
            break
        for s in stocks:
            tk = str(s.get("itemCode") or "").strip().upper()
            nm = str(s.get("stockName") or "").strip()
            if TICKER_RE.match(tk) and nm:
                rows.append((tk, nm[:40], _mkt(s)))
        tc = data.get("totalCount")
        if tc is not None and len(rows) >= int(tc or 0):
            break
        page += 1
    return rows


def _save_theme_day(themes):
    """테마별 오늘 등락률을 날짜별로 쌓아 둔다(연속 강세·순위 변화용) — 실패해도 가져오기는 그대로 성공."""
    day = _now_kst().strftime("%Y-%m-%d")
    ops = [("DELETE FROM theme_day WHERE date=?", (day,))]
    for th in themes:
        ops.append(("INSERT INTO theme_day(date,no,name,rate,rise,fall,steady) VALUES(?,?,?,?,?,?,?)", (day, th["no"], th["name"], th["rate"], th["rise"], th["fall"], th["steady"])))
    try:
        for k in range(0, len(ops), 400):
            _run(ops[k:k + 400])
        _run([("DELETE FROM theme_day WHERE date<?", ((_now_kst() - __import__("datetime").timedelta(days=400)).strftime("%Y-%m-%d"),))])
    except Exception as e:
        print(f"[테마수집] 일별 기록 저장 실패(무시): {e}")


def _theme_worker():
    try:
        _set(phase="list", msg="① 네이버 테마 목록 받는 중…")
        themes = _theme_list()
        if _stopped():
            return _end()
        if not themes:
            return _end("테마를 찾지 못했어요. 네이버 응답이 없거나 주소 구조가 바뀌었을 수 있어요.")
        _set(phase="stocks", total=len(themes), msg=f"② 테마 {len(themes)}개의 종목 받는 중…")
        pairs, seen = [], set()
        for th in themes:
            if _stopped():
                break
            _set(cur=th["name"])
            try:
                for tk, nm, mk in _theme_stocks(th["no"]):
                    if (tk, th["name"]) not in seen:
                        seen.add((tk, th["name"]))
                        pairs.append((tk, nm, mk, th["name"]))
                with _LOCK:
                    _ST["ok"] += 1
            except Exception:
                with _LOCK:
                    _ST["fail"] += 1
            with _LOCK:
                _ST["done"] += 1
            time.sleep(0.1)
        snap = _snapshot()
        if _stopped():
            return _end()           # 멈춤: 일부만 받은 채로 기존 자료를 지우면 안 되므로 저장하지 않는다
        if snap["ok"] < max(1, len(themes) // 2) or len(pairs) < 20:
            return _end(f"테마 {snap['fail']}개를 받지 못해(성공 {snap['ok']}개) 기존 테마 자료를 그대로 두었어요. 잠시 뒤 다시 시도해 주세요.")
        # 저장: 네이버 테마만 지우고 다시 넣는다(직접 만든 테마·시스템 테마는 그대로)
        now = _stamp()
        ops = [("DELETE FROM stock_theme_map WHERE theme_type='naver'", None)]
        for tk, nm, mk, tn in pairs:
            ops.append(("DELETE FROM stock_theme_map WHERE ticker=? AND theme=?", (tk, tn)))
            ops.append(("INSERT INTO stock_theme_map(ticker,name,market,sector,theme,theme_type) VALUES(?,?,?,?,?,?)", (tk, nm, mk, "", tn, "naver")))
        ops.append(("DELETE FROM collect_theme_list", None))
        for th in themes:
            ops.append(("DELETE FROM collect_theme_list WHERE no=?", (th["no"],)))
            ops.append(("INSERT INTO collect_theme_list(no,name,total,change_rate,rise,fall,steady,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
                        (th["no"], th["name"], th["total"], th["rate"], th["rise"], th["fall"], th["steady"], now)))
        for k in range(0, len(ops), 400):
            _run(ops[k:k + 400])
        _save_theme_day(themes)
        res = {"at": _stamp(), "themes": len(themes), "stocks": len(pairs), "uniq_tickers": len({p[0] for p in pairs}), "fail": snap["fail"]}
        _last_set(KEY_THEME, res)
        _reload_flow()
        _end("", res)
        _set(msg=f"✅ 테마 {len(themes)}개 · 종목 연결 {len(pairs):,}건을 가져왔어요")
    except Exception as e:
        _end(f"가져오는 중 오류: {str(e)[:120]}")


# ══════════════════════════════════════════════════════════════
# API (관리자 전용)
# ══════════════════════════════════════════════════════════════
def _count(sql):
    try:
        r = _dbx(sql, (), fetch=True)
        return int(r[0][0]) if r else 0
    except Exception:
        return None


@bp.route("/admin/api/collect/status", methods=["GET"])
def api_status():
    deny = _admin_deny()
    if deny:
        return deny
    inv = _last_get(KEY_INV)
    th = _last_get(KEY_THEME)
    return _admin_json({"ok": True, "job": _snapshot(), "last_inv": inv, "last_theme": th,
                        "tables": {"investor_scan_cache": _count("SELECT COUNT(*) FROM investor_scan_cache"),
                                   "stock_price_cache": _count("SELECT COUNT(*) FROM stock_price_cache"),
                                   "stock_theme_map": _count("SELECT COUNT(*) FROM stock_theme_map WHERE theme_type='naver'"),
                                   "collect_theme_list": _count("SELECT COUNT(*) FROM collect_theme_list")}})


@bp.route("/admin/api/collect/investor/start", methods=["POST"])
def api_inv_start():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    try:
        limit = int(b.get("limit") or DEFAULT_LIMIT)
    except Exception:
        limit = DEFAULT_LIMIT
    if limit not in LIMITS:
        limit = DEFAULT_LIMIT
    skip = bool(b.get("skip_today", True))
    if not _begin("investor", "시작하는 중…"):
        return _admin_json({"ok": False, "error": "이미 다른 가져오기가 실행 중이에요. 끝나거나 멈춘 뒤 다시 눌러 주세요."})
    _alog("collect_investor", f"limit={limit} skip_today={int(skip)}")
    threading.Thread(target=_investor_worker, args=(limit, skip), daemon=True).start()
    return _admin_json({"ok": True})


@bp.route("/admin/api/collect/theme/start", methods=["POST"])
def api_theme_start():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if not _begin("theme", "시작하는 중…"):
        return _admin_json({"ok": False, "error": "이미 다른 가져오기가 실행 중이에요. 끝나거나 멈춘 뒤 다시 눌러 주세요."})
    _alog("collect_theme", "start")
    threading.Thread(target=_theme_worker, daemon=True).start()
    return _admin_json({"ok": True})


@bp.route("/admin/api/collect/stop", methods=["POST"])
def api_stop():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    _set(stop=True)
    _alog("collect_stop", "")
    return _admin_json({"ok": True})


@bp.route("/admin/api/collect/theme/list", methods=["GET"])
def api_theme_list():
    """가져온 네이버 테마 목록(종목 수·등락률) — 관리자가 '무엇을 가져왔는지' 눈으로 확인하는 용도."""
    deny = _admin_deny()
    if deny:
        return deny
    q = (request.args.get("q") or "").strip()[:30]
    try:
        rows = _dbx("SELECT l.no,l.name,l.total,l.change_rate,l.fetched_at,"
                    "(SELECT COUNT(*) FROM stock_theme_map m WHERE m.theme=l.name AND m.theme_type='naver') FROM collect_theme_list l ORDER BY l.change_rate DESC", (), fetch=True) or []
    except Exception:
        rows = []
    items = []
    for no, name, total, rate, at, have in rows:
        if q and q.lower() not in str(name).lower():
            continue
        items.append({"no": int(no), "name": name, "total": int(total or 0), "have": int(have or 0), "rate": float(rate or 0), "at": str(at or "")})
    return _admin_json({"ok": True, "count": len(items), "items": items[:300], "q": q})


def register():
    C.register_table_hook(_ensure_tables)
    return bp
