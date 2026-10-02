"""🌟 오늘추천 (관리자 전용 메뉴) — 원본 프로그램의 '오늘의 추천' + 추가 기능, 블로그 글쓰기 포함.

원본(app_desktop)의 구성을 그대로 따른다
  ① 시가총액 상위 종목 스캔 → 기술 점수(통합점수·20일선 이격·거래량·52주 위치 + RSI) ② 음봉강세(하락한 날 숨은 강세) 점수
  ③ 발굴 신호 배지(수급전환·쌍끌이·거래급증·압축) ④ 날짜별 저장·열람 ⑤ AI 추천주 선정(호흡 단기/중기/장기, 오답노트 반영)
  ⑥ 블로그 글('🌟 오늘의 추천 주식 N선' 제목, 통계·목록·AI 결과) ⑦ 위험(상장폐지·거래정지) 종목 자동 제외
웹 미니에서 더한 것
  · 스캔을 서버가 뒤에서 돌리고 진행률을 보여줌(시장·시총 범위·최소 점수·개수 조절) · 원본 DB에서 가져온 6천여 건 이력도 날짜별로 열람
  · 목록 필터(점수·정배열·음봉강세·신호·검색)와 정렬 · 전 스캔 대비 🆕 신규, 연속 등장 일수 · 스캔 후 수익률(현재가)
  · 거시 환경(코스피·코스닥·미국 지수·VIX·환율·금리)과 종목별 최근 뉴스·수급을 AI 요청문에 함께 넣음
  · AI 추천 이후 성과 추적(승률·평균 수익률·호흡별) → 다음 요청문의 '오답노트'로 자동 반영
  · 수동 AI 도우미(복사 → 답변 자동 입력)와 [복사하고 블로그 열기] 한 번으로 글쓰기

저장은 웹 전용 표(dly_pick·dly_ai·dly_track)에 한다. 원본에서 가져온 표(daily_recommend·daily_ai_result·ai_pick_track)는
읽기만 하므로, 나중에 원본 DB를 다시 가져와도 웹에서 스캔한 기록이 지워지지 않는다.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, request
from menu_ctx import C
import menu_blog as B
import menu_lab as L

bp = Blueprint("daily", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_dbrows", "_http", "_cache_get", "_cache_set", "_now_kst", "prompt_get",
               "setting_get", "setting_set", "get_ticker_info", "get_price_data", "_naver_mobile_basic", "_naver_mobile_integration", "_parse_cap_eok",
               "_prompt_fill", "_naver_news")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

E = B.E
TICKER_RE = B.TICKER_RE
HZ_DAYS = {"단기": 7, "중기": 30, "장기": 90}
DEFAULT_CFG = {"markets": ["KOSPI", "KOSDAQ"], "cap_top": 200, "min_score": 50, "count": 50, "kospi_ratio": 0}   # kospi_ratio 0 = 합쳐서 시총 순


def _f(v, d=None):
    """숫자로 바꾸기(실패하면 d). 'N/A'·빈 문자열·콤마 처리."""
    if v is None or isinstance(v, bool):
        return d
    try:
        return float(re.sub(r"[,%배원\s]", "", str(v)))
    except Exception:
        return d


def _norm(raw, lo, hi):
    return 0 if hi <= lo else int(min(100, max(0, round((raw - lo) / (hi - lo) * 100))))


# ══════════════════════════════════════════════════════════════
# 점수 (원본 _unified_score(재무 없음) / _dip_score 그대로)
# ══════════════════════════════════════════════════════════════
def unified_score(p):
    ts = p.get("tech_score", 0) or 0
    rsi = p.get("rsi", 50) or 50
    rsi_add = 2 if 40 <= rsi <= 65 else (-1 if rsi > 75 or rsi < 25 else 0)
    return _norm(ts + rsi_add, -5, 8)


def dip_score(p):
    """오늘 하락했지만 구조는 건강한 종목(음봉강세) 점수. 상승·보합이면 0."""
    day = p.get("day_pct", 0) or 0
    if day >= 0:
        return 0
    rsi, pos52, vr = p.get("rsi", 50) or 50, p.get("pos52", 50) or 50, p.get("vol_ratio", 1) or 1
    ma20d, align = p.get("ma20_diff", 0) or 0, p.get("ma_align", "") or ""
    raw = 0
    raw += 5 if align == "정배열" else 1 if align == "혼재" else -4 if align == "역배열" else 0
    raw += 4 if -5 <= ma20d <= -0.5 else 2 if -0.5 < ma20d <= 3 else 0 if -10 <= ma20d < -5 else -3
    raw += 4 if vr < 0.5 else 3 if vr < 0.8 else 1 if vr < 1.2 else -1 if vr < 2.0 else -4
    if 30 <= rsi <= 42:
        raw += 4
    elif 42 < rsi <= 52:
        raw += 3
    elif 52 < rsi <= 60:
        raw += 1
    elif rsi < 30:
        raw += 2
    elif rsi > 70:
        raw -= 3
    raw += 3 if 40 <= pos52 <= 65 else 1 if 65 < pos52 <= 80 else -2 if pos52 > 80 else -2 if pos52 < 20 else 0
    raw += 3 if -3 <= day <= -0.5 else 1 if -5 <= day < -3 else -3 if day < -7 else 0
    return min(100, max(0, int((raw + 10) / 33 * 100)))


# ══════════════════════════════════════════════════════════════
# 표 · 설정
# ══════════════════════════════════════════════════════════════
def _ensure_tables(c, use_pg):
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    c.execute(f"CREATE TABLE IF NOT EXISTS dly_pick(scan_date TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', market TEXT NOT NULL DEFAULT '', "
              f"price {real}, day_pct {real}, per {real}, pbr {real}, cap_eok BIGINT, rsi {real}, score INTEGER NOT NULL DEFAULT 0, dip_score INTEGER NOT NULL DEFAULT 0, "
              f"ma_align TEXT NOT NULL DEFAULT '', pos52 {real}, vol_ratio {real}, pct52 {real}, disc_flags TEXT NOT NULL DEFAULT '', "
              f"f5 {real}, i5 {real}, f20 {real}, i20 {real}, PRIMARY KEY(scan_date, ticker))")
    c.execute("CREATE TABLE IF NOT EXISTS dly_ai(scan_date TEXT PRIMARY KEY, result TEXT NOT NULL DEFAULT '', market_context TEXT NOT NULL DEFAULT '', "
              "picks TEXT NOT NULL DEFAULT '[]', updated BIGINT NOT NULL DEFAULT 0)")
    c.execute(f"CREATE TABLE IF NOT EXISTS dly_track(pick_date TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', horizon TEXT NOT NULL DEFAULT '', "
              f"pick_price {real}, pick_score INTEGER NOT NULL DEFAULT 0, pick_type TEXT NOT NULL DEFAULT 'normal', eval_price {real}, eval_date TEXT NOT NULL DEFAULT '', "
              "outcome TEXT NOT NULL DEFAULT '', PRIMARY KEY(pick_date, ticker))")


def _valid_cfg(k, v):
    try:
        d = json.loads(v) if isinstance(v, str) else v
    except Exception:
        return None
    return json.dumps(_clean_cfg(d), ensure_ascii=False) if isinstance(d, dict) else None


def _clean_cfg(d):
    d = d if isinstance(d, dict) else {}
    mk = [m for m in (d.get("markets") or DEFAULT_CFG["markets"]) if m in ("KOSPI", "KOSDAQ")] or list(DEFAULT_CFG["markets"])

    def iv(k, lo, hi):
        try:
            return int(max(lo, min(hi, int(float(d.get(k, DEFAULT_CFG[k]))))))
        except Exception:
            return DEFAULT_CFG[k]
    return {"markets": mk, "cap_top": iv("cap_top", 30, 600), "min_score": iv("min_score", 0, 95), "count": iv("count", 5, 150), "kospi_ratio": iv("kospi_ratio", 0, 100)}


def get_cfg():
    try:
        return _clean_cfg(json.loads(setting_get("daily_cfg") or "{}"))
    except Exception:
        return dict(DEFAULT_CFG)


# ══════════════════════════════════════════════════════════════
# 읽기 — 웹 스캔(dly_pick)과 원본에서 가져온 표(daily_recommend)를 같은 모양으로
# ══════════════════════════════════════════════════════════════
_LEG_COLS = "scan_date, ticker, name, market, price, day_pct, per, pbr, market_cap, rsi, score, dip_score, ma_align, pos52, vol_ratio, pct52, disc_flags"


def _row(d):
    return {"scan_date": d["scan_date"], "ticker": str(d["ticker"] or "").zfill(6), "name": d.get("name") or "", "market": d.get("market") or "",
            "price": _f(d.get("price")), "day_pct": _f(d.get("day_pct")), "per": _f(d.get("per")), "pbr": _f(d.get("pbr")), "cap": d.get("cap") or "",
            "rsi": _f(d.get("rsi")), "score": int(_f(d.get("score"), 0) or 0), "dip": int(_f(d.get("dip_score"), 0) or 0), "align": d.get("ma_align") or "",
            "pos52": _f(d.get("pos52")), "vr": _f(d.get("vol_ratio")), "pct52": _f(d.get("pct52")),
            "flags": [x for x in str(d.get("disc_flags") or "").split(",") if x],
            "f5": _f(d.get("f5")), "i5": _f(d.get("i5")), "f20": _f(d.get("f20")), "i20": _f(d.get("i20"))}


def _web_rows(date):
    cols = ["scan_date", "ticker", "name", "market", "price", "day_pct", "per", "pbr", "cap_eok", "rsi", "score", "dip_score", "ma_align", "pos52", "vol_ratio", "pct52",
            "disc_flags", "f5", "i5", "f20", "i20"]
    try:
        rows = _dbrows(f"SELECT {', '.join(cols)} FROM dly_pick WHERE scan_date=? ORDER BY score DESC, ticker", cols, (date,))
    except Exception:
        return []
    out = []
    for r in rows:
        r["cap"] = f"{int(r['cap_eok']):,}억원" if r.get("cap_eok") else ""
        out.append(_row(r))
    return out


def _legacy_rows(date):
    cols = [c.strip() for c in _LEG_COLS.split(",")]
    try:
        rows = _dbrows(f"SELECT {_LEG_COLS} FROM daily_recommend WHERE scan_date=? ORDER BY score DESC", cols, (date,))
    except Exception:
        return []
    return [_row(dict(r, cap=r.get("market_cap"))) for r in rows]


def _dates(limit=40):
    out = {}
    for src, sql in (("web", "SELECT scan_date, COUNT(*) FROM dly_pick GROUP BY scan_date"), ("orig", "SELECT scan_date, COUNT(*) FROM daily_recommend GROUP BY scan_date")):
        try:
            for d, n in (_dbx(sql, fetch=True) or []):
                if d and (d not in out or src == "web"):
                    out[str(d)] = (int(n), src)
        except Exception:
            pass
    ds = sorted(out, reverse=True)[:limit]
    return [{"date": d, "n": out[d][0], "src": out[d][1]} for d in ds]


def load_rows(date):
    rows = _web_rows(date)
    src = "web"
    if not rows:
        rows, src = _legacy_rows(date), "orig"
    return rows, src


def risk_set():
    """상장폐지·거래정지 위험으로 걸러진(또는 관리자가 확정한) 종목 — 추천에서 뺀다."""
    try:
        rs = _dbx("SELECT ticker FROM delist_watch WHERE (active=1 AND admin_state<>'excluded') OR admin_state='confirmed'", fetch=True) or []
        return {r[0] for r in rs}
    except Exception:
        return set()


def _streaks(dates, rows):
    """각 종목이 최근 스캔 날짜에서 연속 몇 번 나왔는지(맨 위 날짜 기준)와 직전 스캔 날짜의 종목 집합."""
    if not dates:
        return {}, set(), ""
    seq = [d["date"] for d in dates]
    cur = rows[0]["scan_date"] if rows else seq[0]
    if cur not in seq:
        return {}, set(), ""
    i = seq.index(cur)
    older = seq[i + 1:i + 12]
    sets = []
    for d in older:
        r, _s = load_rows(d)
        sets.append({x["ticker"] for x in r})
    prev = sets[0] if sets else set()
    out = {}
    for r in rows:
        n = 1
        for s in sets:
            if r["ticker"] in s:
                n += 1
            else:
                break
        out[r["ticker"]] = n
    return out, prev, (older[0] if older else "")


def live_prices(tickers):
    """현재가·등락률(네이버 모바일, 60초 캐시). {ticker: (price, pct)}"""
    out = {}

    def one(t):
        hit = _cache_get(("dly_live", t))
        if hit is not None:
            return t, hit
        b = _naver_mobile_basic(t)
        v = None
        if b:
            p = _f(b.get("closePrice"))
            if p:
                v = (p, _f(b.get("fluctuationsRatio")))
        _cache_set(("dly_live", t), v or (None, None), 60)
        return t, v or (None, None)
    tickers = list(dict.fromkeys(tickers))[:120]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, v in ex.map(one, tickers):
            if v and v[0]:
                out[t] = v
    return out


@bp.route("/admin/api/daily/state", methods=["GET"])
def api_state():
    deny = _admin_deny()
    if deny:
        return deny
    last = {}
    try:
        last = json.loads(setting_get("daily_last_scan") or "{}")
    except Exception:
        pass
    return _admin_json({"cfg": get_cfg(), "dates": _dates(), "scan": _scan_view(), "last": last})


@bp.route("/admin/api/daily/list", methods=["GET"])
def api_list():
    deny = _admin_deny()
    if deny:
        return deny
    dates = _dates()
    date = str(request.args.get("date", "")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        date = dates[0]["date"] if dates else ""
    if not date:
        return _admin_json({"date": "", "rows": [], "src": "", "dates": dates})
    rows, src = load_rows(date)
    rk = risk_set()
    excluded = [r["ticker"] for r in rows if r["ticker"] in rk]
    rows = [r for r in rows if r["ticker"] not in rk]
    streak, prev, prev_date = _streaks(dates, rows)
    for r in rows:
        r["streak"] = streak.get(r["ticker"], 1)
        r["new"] = bool(prev) and r["ticker"] not in prev
    if request.args.get("live") == "1" and rows:
        lp = live_prices([r["ticker"] for r in rows])
        for r in rows:
            v = lp.get(r["ticker"])
            if v and r["price"]:
                r["now"], r["now_pct"] = v[0], v[1]
                r["since"] = round((v[0] / r["price"] - 1) * 100, 2)
    return _admin_json({"date": date, "rows": rows, "src": src, "dates": dates, "excluded": len(excluded), "prev_date": prev_date})


# ══════════════════════════════════════════════════════════════
# 스캔 (뒤에서 도는 작업 + 진행률)
# ══════════════════════════════════════════════════════════════
_JOB = {"running": False, "cancel": False, "total": 0, "done": 0, "kept": 0, "current": "", "started": 0, "finished": 0, "error": "", "scan_date": "", "saved": 0}


def _scan_view():
    return {k: _JOB[k] for k in ("running", "total", "done", "kept", "current", "started", "finished", "error", "scan_date", "saved")}


def _ranking(mk, want):
    """네이버 모바일 시가총액 순위(상위 want개). 거래정지·ETF 등은 건너뛴다."""
    rows = []
    pages = min(15, (want + 59) // 60 + 1)
    for page in range(1, pages + 1):
        try:
            r = _http().get(f"https://m.stock.naver.com/api/stocks/marketValue/{mk}", params={"page": page, "pageSize": 60}, headers=C.NAVER_M_HEADERS, timeout=8)
            if r.status_code != 200:
                break
            stocks = (r.json() or {}).get("stocks") or []
            if not stocks:
                break
            for s in stocks:
                tk = str(s.get("itemCode", "")).strip().zfill(6)
                if not tk or (s.get("stockEndType") not in (None, "stock")):
                    continue
                if s.get("tradableStatus") not in (None, "tradable"):
                    continue
                rows.append({"ticker": tk, "name": s.get("stockName", ""), "market": mk, "cap": _f(s.get("marketValue"), 0) or 0})
        except Exception as e:
            print(f"[오늘추천] 순위 {mk} {page}쪽 오류(무시): {e}")
            break
    return rows[:want]


def _universe(cfg):
    mks = cfg["markets"]
    n = cfg["cap_top"]
    if len(mks) == 2 and cfg["kospi_ratio"] > 0:
        k = int(n * cfg["kospi_ratio"] / 100)
        lst = _ranking("KOSPI", k) + _ranking("KOSDAQ", n - k)
    else:
        lst = []
        for m in mks:
            lst += _ranking(m, n)
        lst = sorted(lst, key=lambda x: -x["cap"])[:n]
    seen, out = set(), []
    for x in lst:
        if x["ticker"] not in seen:
            seen.add(x["ticker"])
            out.append(x)
    return out


def _eval_one(item, min_score):
    p = get_price_data(item["ticker"])
    if not p or not p.get("price"):
        return None
    sc, dp = unified_score(p), dip_score(p)
    disc = []
    if (p.get("vol_ratio") or 0) >= 2.0:
        disc.append("거래급증")
    if (p.get("bb_squeeze") or 0) == 1:
        disc.append("압축")
    if (p.get("pos52") or 0) >= 95:
        disc.append("신고가권")
    day = p.get("day_pct", 0) or 0
    is_dip = day < 0 and dp >= 60
    if not (sc >= min_score or is_dip or (disc and sc >= max(0, min_score - 10))):
        return None
    return {"ticker": item["ticker"], "name": item["name"], "market": item["market"], "cap_eok": int(item["cap"] or 0) or None, "price": p["price"], "day_pct": day,
            "rsi": p.get("rsi"), "score": sc, "dip_score": dp, "ma_align": p.get("ma_align") or "", "pos52": p.get("pos52"), "vol_ratio": p.get("vol_ratio"),
            "pct52": p.get("pct52"), "flags": disc, "last": p.get("last_trade_date") or "", "per": None, "pbr": None, "f5": None, "i5": None, "f20": None, "i20": None}


def _enrich(r):
    """통과한 종목만 PER·PBR·시총과 수급(외국인·기관 5일/20일)을 더한다."""
    try:
        integ = _naver_mobile_integration(r["ticker"]) or {}
        im = {x.get("code"): x.get("value") for x in (integ.get("totalInfos") or [])}
        r["per"], r["pbr"] = _f(im.get("per")), _f(im.get("pbr"))
        cap = _parse_cap_eok(im.get("marketValue"))
        if cap:
            r["cap_eok"] = cap
    except Exception:
        pass
    try:
        sp = L.supply_analysis(L._trend_rows(r["ticker"]))
        if sp:
            for n, a, b in ((5, "f5", "i5"), (20, "f20", "i20")):
                x = sp["per"].get(str(n))
                if x and x.get("days", 0) >= n:
                    r[a], r[b] = x["foreign_eok"], x["inst_eok"]
            f5, i5, f20, i20 = r["f5"], r["i5"], r["f20"], r["i20"]
            if f20 is not None and i20 is not None:
                if f20 > 0 and i20 > 0:
                    r["flags"].append("쌍끌이")
                if (f20 <= 0 < f5) or (i20 <= 0 < i5):
                    r["flags"].append("수급전환")
    except Exception:
        pass
    return r


def _scan_run(cfg):
    job = _JOB
    try:
        uni = _universe(cfg)
        risk = risk_set()
        uni = [u for u in uni if u["ticker"] not in risk]
        job.update(total=len(uni), done=0, kept=0, current="종목 목록 확인 완료")
        if not uni:
            job["error"] = "네이버에서 종목 목록을 받지 못했어요. 잠시 뒤 다시 시도해 주세요."
            return
        results = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(_eval_one, u, cfg["min_score"]): u for u in uni}
            for f in as_completed(futs):
                u = futs[f]
                job["done"] += 1
                job["current"] = f"{job['done']}/{len(uni)} — {u['name']}"
                if job["cancel"]:
                    for g in futs:
                        g.cancel()
                    break
                try:
                    r = f.result()
                except Exception:
                    r = None
                if r:
                    results.append(r)
                    job["kept"] = len(results)
        if job["cancel"]:
            job["error"] = "중단했어요(저장하지 않았어요)."
            return
        if len(results) == 0 and job["done"] > 0:
            job["error"] = "조건을 통과한 종목이 없어요. 최소 점수를 낮춰 보세요."
            return
        results.sort(key=lambda x: (-x["score"], x["ticker"]))
        top = results[:cfg["count"]]
        have = {r["ticker"] for r in top}
        extra = sorted((r for r in results[cfg["count"]:] if r["day_pct"] < 0 and r["dip_score"] >= 60), key=lambda x: -x["dip_score"])[:10]
        top += [r for r in extra if r["ticker"] not in have]
        job["current"] = f"PER·수급 정보 보강 중 ({len(top)}종목)"
        with ThreadPoolExecutor(max_workers=6) as ex:
            top = list(ex.map(_enrich, top))
        # 기준일 = 종목들의 마지막 거래일 중 가장 많은 날(주말·장 시작 전에도 정확)
        cnt = {}
        for r in results:
            if r["last"]:
                cnt[r["last"]] = cnt.get(r["last"], 0) + 1
        scan_date = max(cnt, key=cnt.get) if cnt else _now_kst().strftime("%Y-%m-%d")
        job["scan_date"] = scan_date
        _dbx("DELETE FROM dly_pick WHERE scan_date=?", (scan_date,))
        for r in top:
            _dbx("INSERT INTO dly_pick(scan_date,ticker,name,market,price,day_pct,per,pbr,cap_eok,rsi,score,dip_score,ma_align,pos52,vol_ratio,pct52,disc_flags,f5,i5,f20,i20) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (scan_date, r["ticker"], r["name"], r["market"], r["price"], r["day_pct"], r["per"], r["pbr"], r["cap_eok"], r["rsi"], r["score"], r["dip_score"],
                  r["ma_align"], r["pos52"], r["vol_ratio"], r["pct52"], ",".join(dict.fromkeys(r["flags"])), r["f5"], r["i5"], r["f20"], r["i20"]))
        job["saved"] = len(top)
        job["current"] = f"완료 — {len(top)}종목 저장"
    except Exception as e:
        job["error"] = f"스캔 중 오류: {type(e).__name__}: {str(e)[:120]}"
        print(f"[오늘추천] 스캔 오류: {e}")
    finally:
        job["running"] = False
        job["finished"] = int(time.time())
        try:
            setting_set("daily_last_scan", json.dumps({"date": job["scan_date"], "saved": job["saved"], "total": job["total"], "finished": job["finished"], "error": job["error"]}, ensure_ascii=False))
        except Exception:
            pass


@bp.route("/admin/api/daily/scan", methods=["POST"])
def api_scan():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if _JOB["running"]:
        return _admin_json({"error": "이미 스캔 중이에요."}, 409)
    cfg = _clean_cfg(_json_body() or {})
    setting_set("daily_cfg", json.dumps(cfg, ensure_ascii=False))
    _JOB.update(running=True, cancel=False, total=0, done=0, kept=0, current="종목 목록 가져오는 중…", started=int(time.time()), finished=0, error="", scan_date="", saved=0)
    threading.Thread(target=_scan_run, args=(cfg,), daemon=True).start()
    _alog("daily_scan", json.dumps(cfg, ensure_ascii=False))
    return _admin_json({"ok": True, "cfg": cfg})


@bp.route("/admin/api/daily/scan-status", methods=["GET"])
def api_scan_status():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_scan_view())


@bp.route("/admin/api/daily/scan-cancel", methods=["POST"])
def api_scan_cancel():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    _JOB["cancel"] = True
    return _admin_json({"ok": True})


@bp.route("/admin/api/daily/delete", methods=["POST"])
def api_delete():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    date = str((_json_body() or {}).get("date", "")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return _admin_json({"error": "날짜가 올바르지 않아요."}, 400)
    _dbx("DELETE FROM dly_pick WHERE scan_date=?", (date,))
    _alog("daily_delete", date)
    return _admin_json({"ok": True, "note": "웹에서 스캔한 기록만 지워져요(원본에서 가져온 기록은 그대로)."})


# ══════════════════════════════════════════════════════════════
# 거시 환경 · 뉴스 · 오답노트
# ══════════════════════════════════════════════════════════════
def macro_snapshot():
    hit = _cache_get(("dly_macro",))
    if hit is not None:
        return hit
    items = [("코스피", "https://m.stock.naver.com/api/index/KOSPI/basic", "close"), ("코스닥", "https://m.stock.naver.com/api/index/KOSDAQ/basic", "close"),
             ("나스닥", "https://api.stock.naver.com/index/.IXIC/basic", "close"), ("다우", "https://api.stock.naver.com/index/.DJI/basic", "close"),
             ("S&P500", "https://api.stock.naver.com/index/.INX/basic", "close"), ("VIX(변동성)", "https://api.stock.naver.com/index/.VIX/basic", "close"),
             ("원/달러", "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW", "fx"), ("미국10년물 금리", "https://api.stock.naver.com/marketindex/bond/US10YT=RR", "close")]

    def one(it):
        nm, url, kind = it
        try:
            r = _http().get(url, headers=C.NAVER_M_HEADERS, timeout=6)
            if r.status_code != 200:
                return nm, None
            j = r.json()
            j = j.get("exchangeInfo") if kind == "fx" and isinstance(j, dict) else j
            if not isinstance(j, dict):
                return nm, None
            return nm, (j.get("closePrice"), j.get("fluctuationsRatio"))
        except Exception:
            return nm, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(one, items))
    rows = [(n, v) for n, v in res if v and v[0]]
    text = " · ".join(f"{n} {v[0]}" + (f"({_f(v[1], 0):+.2f}%)" if _f(v[1]) is not None else "") for n, v in rows)
    out = {"text": text, "rows": [{"name": n, "close": v[0], "pct": _f(v[1])} for n, v in rows]}
    _cache_set(("dly_macro",), out, 300)
    return out


def news_titles(tickers, n=2):
    def one(t):
        try:
            return t, [x["title"] for x in (_naver_news(t) or [])[:n] if x.get("title")]
        except Exception:
            return t, []
    with ThreadPoolExecutor(max_workers=8) as ex:
        return {t: v for t, v in ex.map(one, tickers) if v}


def _track_rows(days=120):
    """AI 추천 성과 원자료: 웹(dly_track) + 원본(ai_pick_track). 같은 (날짜,종목)은 웹 쪽 우선."""
    cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    out = {}
    try:
        cols = ["pick_date", "ticker", "name", "horizon", "pick_price", "pick_score", "eval_price", "eval_date", "outcome"]
        for r in _dbrows(f"SELECT {', '.join(cols)} FROM ai_pick_track WHERE pick_date>=?", cols, (cut,)):
            hz = (r.get("horizon") or "").split("-")[0].strip() or "미분류"
            out[(r["pick_date"], str(r["ticker"]).zfill(6))] = {"date": r["pick_date"], "ticker": str(r["ticker"]).zfill(6), "name": r["name"] or "", "horizon": hz,
                "pick_price": _f(r["pick_price"]), "score": int(_f(r["pick_score"], 0) or 0), "eval_price": _f(r["eval_price"]), "eval_date": r["eval_date"] or "",
                "outcome": r["outcome"] or "", "src": "orig"}
    except Exception:
        pass
    try:
        cols = ["pick_date", "ticker", "name", "horizon", "pick_price", "pick_score", "eval_price", "eval_date", "outcome"]
        for r in _dbrows(f"SELECT {', '.join(cols)} FROM dly_track WHERE pick_date>=?", cols, (cut,)):
            out[(r["pick_date"], r["ticker"])] = {"date": r["pick_date"], "ticker": r["ticker"], "name": r["name"], "horizon": r["horizon"] or "미분류", "pick_price": _f(r["pick_price"]),
                "score": int(r["pick_score"] or 0), "eval_price": _f(r["eval_price"]), "eval_date": r["eval_date"] or "", "outcome": r["outcome"] or "", "src": "web"}
    except Exception:
        pass
    return sorted(out.values(), key=lambda x: (x["date"], x["ticker"]), reverse=True)


def _ret(t):
    p = t.get("eval_price") or t.get("now")
    return round((p / t["pick_price"] - 1) * 100, 2) if p and t.get("pick_price") else None


def learning_note():
    """과거 추천 성과 요약(확정 평가 기준)을 AI 요청문에 넣을 글로. 평가된 건이 5건 미만이면 빈 글."""
    ev = [t for t in _track_rows(365) if t["outcome"] in ("win", "lose", "flat") and _ret(t) is not None]
    if len(ev) < 5:
        return ""
    win = sum(1 for t in ev if t["outcome"] == "win")
    avg = sum(_ret(t) for t in ev) / len(ev)
    lines = ["[과거 추천 성과 자가 학습 데이터 (오답노트)]", f"- 확정 평가 {len(ev)}건: 승률 {round(win / len(ev) * 100, 1)}%, 평균 수익률 {avg:+.2f}% (호흡 만기 시점 가격 기준)"]
    for hz in ("단기", "중기", "장기"):
        g = [t for t in ev if t["horizon"] == hz]
        if len(g) >= 3:
            lines.append(f"- [{hz}] 승률 {round(sum(1 for t in g if t['outcome'] == 'win') / len(g) * 100, 1)}%, 평균 {sum(_ret(t) for t in g) / len(g):+.2f}% ({len(g)}건)")
    bs = [t for t in ev if t["score"] >= 70]
    bw = [t for t in ev if 0 < t["score"] < 70]
    if len(bs) >= 3 and len(bw) >= 3:
        lines.append(f"- 점수대별 평균: 70점 이상 {sum(_ret(t) for t in bs) / len(bs):+.2f}% vs 70점 미만 {sum(_ret(t) for t in bw) / len(bw):+.2f}%")
    bad = sorted(ev, key=_ret)[:5]
    lines.append("- ❌ 실패 사례(손실 상위): " + ", ".join(f"{t['name']}({_ret(t):+.1f}%/{t['horizon']})" for t in bad))
    good = sorted(ev, key=_ret, reverse=True)[:5]
    lines.append("- ✅ 성공 사례(수익 상위): " + ", ".join(f"{t['name']}({_ret(t):+.1f}%/{t['horizon']})" for t in good))
    lines.append("※ 승률이 낮았던 호흡·점수대 조합은 이번 선정에서 비중을 낮추고, 실패 사례와 비슷한 특성의 종목은 선정 근거를 더 엄격히 검증하세요.")
    return "\n".join(lines)[:1600]


# ══════════════════════════════════════════════════════════════
# AI 요청문
# ══════════════════════════════════════════════════════════════
DAILY_DEFAULT = """당신은 대한민국 주식 시장 전문 퀀트 알고리즘 에이전트입니다.
제시된 [{context}] 후보 종목 데이터를 바탕으로, 최적의 투자 적기 종목 3~5개를 선별해 주세요. (오늘은 {today})
아래 데이터를 표면적으로 훑지 말고, 각 항목이 서로 무엇을 의미하는지 실제로 따져서 판단하세요.

[오늘의 시장 날씨 (후보군 내부 온도)]
{market_weather}
※ 이건 오늘 스캔된 후보 종목들 자기들끼리의 평균일 뿐, 실제 시장 전체 상황이 아닙니다 — 아래 [실제 거시 환경]이 진짜 외부 지표입니다.

[실제 거시 환경 (지수·변동성·환율·금리)]
{macro_snapshot}
※ 요즘처럼 거시 요인(금리, 환율, 미국 증시 방향, 변동성 지수)이 시장을 지배하는 시기에는, 개별 종목의 기술적 강세만으로 상승을 낙관하면 안 됩니다. VIX가 높거나 미국 지수가 약세면 국내 기술적 강세 종목도 거시 역풍에 눌려 하락할 수 있습니다. 거시 환경이 부정적일수록 선정 기준을 더 보수적으로, 리스크 경고를 더 구체적으로 작성하세요.

{learning_note}

[AI 판단 지침 (생각의 사슬) — 반드시 순서대로 검토]
1. 거시 필터: 위 [실제 거시 환경]이 뚜렷하게 부정적(VIX 급등, 미국 증시 급락, 원화 급락 등)이면, 아무리 개별 종목이 좋아 보여도 추천 개수를 줄이거나 방어적 종목 위주로 조정하세요. 거시가 종목보다 우선합니다.
2. 수급 초입 vs 후행 구분: 각 후보의 [수급 5일/20일] 수치를 비교하세요. "20일치는 매도(-) 또는 미미했는데 5일치부터 강하게 매수(+)로 전환"된 종목은 수급이 막 시작된 초입 신호로 보고 가산점을 주세요. 반대로 "20일치부터 이미 꾸준히 강한 매수가 지속"된 종목은 이미 주가에 상당 부분 반영됐을 수 있으니, 52주 위치·RSI가 아직 과열이 아닌지 따져 상승 여력을 판단하세요. [신호:수급전환]이 [신호:쌍끌이]만 붙은 종목보다 일반적으로 더 선행성이 있습니다.
3. 뉴스 모멘텀 우선: 📰[최근뉴스:...] 표시가 붙은 종목은 실제 현재 시장의 관심사와 연결돼 있다는 뜻이니, 선정 이유에 이 실제 근거를 구체적으로 인용하세요. 뉴스는 제목만 있으므로 내용을 추측하지 마세요. 두 후보의 기술적 점수가 비슷하다면 뉴스 모멘텀이 있는 쪽을 우선하세요.
4. 과열 필터링: PBR이 3 이상이면서 RSI가 70 이상인 '단기 과열/고평가' 종목은 선정에서 후순위로 미루세요.
5. 투자 호흡(Horizon) 판별: 추천할 종목이 단기 모멘텀용인지, 중장기 가치/추세용인지 스스로 판단하세요. 뉴스 모멘텀 근거인 종목은 대체로 단기, 수급 초입+저평가 근거인 종목은 중장기에 가까운 경향이 있습니다.
6. 오답노트 반영: 위 [과거 추천 성과 자가 학습 데이터]가 제공된 경우, 승률이 낮았던 호흡·점수대를 식별하고 같은 실수를 반복하지 마세요. 종합의견에 이번 추천이 과거 실패 패턴과 어떻게 다른지 1줄로 명시하세요.
7. [데이터]에 없는 숫자·사실은 지어내지 않습니다. 매수·매도를 단정하지 말고 관찰 중심("~로 보입니다")으로 쓰세요.

━━━ [후보 목록] ━━━
{main_lines}
{dip_section}

[출력 형식 가이드 - 포맷 엄격 준수]
반드시 아래 형식을 지켜 답변하세요. 종목명 앞에는 스스로 판단한 투자 호흡 뱃지 [단기-1주], [중기-1개월], [장기-3개월] 중 하나를 반드시 붙여주세요.

[추천종목]
1. [단기-1주] 종목명(코드): 선정 이유 (2줄 이내, 반드시 후보 목록에 제시된 실제 근거를 1개 이상 그대로 인용 — 숫자("RSI 32.1", "외인 5일 +8억")뿐 아니라 뉴스 태그가 있다면 그것도 인용하세요. 수급을 근거로 들 때는 "5일치 전환"인지 "20일치부터 지속"인지 구분해서 언급하세요. 숫자·근거 없이 "수급이 좋다"·"차트가 양호하다"처럼 뭉뚱그린 설명만 쓰지 마세요.)
2. [중기-1개월] 종목명(코드): 선정 이유
...

[종합의견]
- 거시 환경과 오늘 시장 분위기를 반영한 전략 요약 (2~3줄) — 거시가 부정적이면 이를 명시하고 왜 그럼에도 이 종목들을 골랐는지(혹은 왜 보수적으로 줄였는지) 설명하세요.
- 리스크 관리 가이드

[블로그 제목 후보]
- 검색에 잘 걸리는 제목 3개 (각 줄 앞에 "- ", 날짜·종목 수·핵심 키워드 포함)

[기계 판독용 출력 - 반드시 준수]
응답의 맨 마지막 줄에 추천 종목 전체를 아래 JSON 형식 한 줄로 정확히 출력하세요. 다른 텍스트와 절대 섞지 마세요.
PICKS_JSON: [{"ticker":"005930","horizon":"단기"},{"ticker":"000660","horizon":"중기"}]
"""


def _fmt_line(i, r, news):
    inv = ""
    if r.get("f5") is not None or r.get("f20") is not None:
        g = lambda v: "N/A" if v is None else f"{v:+.1f}억"
        inv = f" [수급 5일: 외인{g(r.get('f5'))}/기관{g(r.get('i5'))}, 20일: 외인{g(r.get('f20'))}/기관{g(r.get('i20'))}]"
    sig = f" [신호:{','.join(r['flags'])}]" if r["flags"] else ""
    nw = f" 📰[최근뉴스:{' / '.join(news[r['ticker']])}]" if r["ticker"] in news else ""
    per = "N/A" if r["per"] is None else f"{r['per']:g}"
    pbr = "N/A" if r["pbr"] is None else f"{r['pbr']:g}"
    rsi = "N/A" if r["rsi"] is None else f"{r['rsi']:.1f}"
    pct = "N/A" if r["day_pct"] is None else f"{r['day_pct']:+.2f}%"
    pos = "N/A" if r["pos52"] is None else f"{r['pos52']:.0f}%"
    return (f"{i}. {r['name']}({r['ticker']}){inv}{sig} 점수:{r['score']} PER:{per} PBR:{pbr} RSI:{rsi} 이평:{r['align'] or '?'} 등락:{pct} 52주:{pos}{nw}")


def build_prompt(date, rows):
    main = sorted(rows, key=lambda r: -r["score"])[:25]
    mt = {r["ticker"] for r in main}
    dips = [r for r in sorted(rows, key=lambda r: -r["dip"]) if r["ticker"] not in mt and (r["day_pct"] or 0) < 0 and r["dip"] >= 60][:10]
    # 원본에서 가져온 날짜(수급 숫자가 없는 행)는 상위 후보만 수급을 새로 조회해 채운다
    need = [r for r in main[:12] if r.get("f5") is None]
    if need:
        for r in need:
            try:
                sp = L.supply_analysis(L._trend_rows(r["ticker"]))
                if sp:
                    for n, a, b in ((5, "f5", "i5"), (20, "f20", "i20")):
                        x = sp["per"].get(str(n))
                        if x and x.get("days", 0) >= n:
                            r[a], r[b] = x["foreign_eok"], x["inst_eok"]
            except Exception:
                pass
    news = news_titles([r["ticker"] for r in sorted(main, key=lambda r: -r["score"])[:12]])
    allr = main + dips
    up = sum(1 for r in allr if (r["day_pct"] or 0) > 0)
    dn = sum(1 for r in allr if (r["day_pct"] or 0) < 0)
    avg = sum((r["day_pct"] or 0) for r in allr) / max(len(allr), 1)
    mood = "상승장 (Bullish)" if avg > 0.5 else "하락장 (Bearish)" if avg < -0.5 else "보합장 (Neutral)"
    weather = f"현재 분석 풀 {len(allr)}개 종목 중 상승 {up}개, 하락 {dn}개. 평균 등락률 {avg:+.2f}%. 전반적인 시장 분위기는 [{mood}]입니다."
    mac = macro_snapshot()["text"] or "(실시간 지수 데이터를 가져오지 못했습니다 — 위 후보군 자체 평균만 참고)"
    ln = learning_note() or "(아직 학습 데이터가 충분히 쌓이지 않았습니다 — 평가 완료 5건 이상 쌓이면 자동 반영)"
    dip_sec = ("\n━━━ [음봉강세 후보] ━━━\n(오늘 하락했지만 정배열·소량 음봉·MA20 지지권 등 구조적으로 건강한 종목 — 저점 매수 후보)\n"
               + "\n".join(_fmt_line(i + 1, r, news) for i, r in enumerate(dips))) if dips else ""
    body = prompt_get("daily_pick")
    prompt = _prompt_fill(body, context=f"{date} 오늘추천", today=date, market_weather=weather, macro_snapshot=mac, learning_note=ln,
                          main_lines="\n".join(_fmt_line(i + 1, r, news) for i, r in enumerate(main)), dip_section=dip_sec)
    return prompt, weather, [r["ticker"] for r in allr]


def _date_arg():
    d = _json_body() or {}
    date = str(d.get("date", "")).strip()
    return d, (date if re.match(r"^\d{4}-\d{2}-\d{2}$", date) else "")


@bp.route("/admin/api/daily/prompt", methods=["POST"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
    d, date = _date_arg()
    if not date:
        return _admin_json({"error": "날짜를 고르세요."}, 400)
    rows, _src = load_rows(date)
    rk = risk_set()
    rows = [r for r in rows if r["ticker"] not in rk]
    if not rows:
        return _admin_json({"error": "이 날짜의 추천 종목이 없어요. 먼저 스캔하세요."}, 404)
    prompt, weather, tks = build_prompt(date, rows)
    return _admin_json({"prompt": prompt, "len": len(prompt), "count": len(tks), "market_context": weather})


# ── AI 답변 → 추천 종목 뽑기 · 저장 ──
def parse_ai(text, rows):
    """AI 답변에서 추천 종목(호흡·이유)을 뽑는다. 기계 판독 줄(PICKS_JSON)이 있으면 우선, 없으면 '1. [단기-1주] 종목명(코드): 이유' 줄."""
    names = {r["ticker"]: r["name"] for r in rows}
    picks = []
    reasons = {}
    for ln in str(text).replace("\r", "").split("\n"):
        m = re.match(r"^\s*\d+[.)]\s*\[(단기|중기|장기)[^\]]*\]\s*(.+?)\s*[(（]\s*([0-9A-Za-z]{6})\s*[)）]\s*[:：]?\s*(.*)$", ln)
        if m:
            reasons[m.group(3).upper()] = (m.group(1), m.group(2).strip(), m.group(4).strip())
    jm = re.search(r"PICKS_JSON\s*:\s*(\[.*\])", str(text))
    if jm:
        try:
            for x in json.loads(jm.group(1)):
                t = str(x.get("ticker", "")).strip().upper()
                hz = str(x.get("horizon", "")).strip()[:2]
                if TICKER_RE.match(t):
                    picks.append({"ticker": t, "horizon": hz if hz in HZ_DAYS else (reasons.get(t, ("",))[0] or "미분류")})
        except Exception:
            picks = []
    if not picks:
        picks = [{"ticker": t, "horizon": v[0]} for t, v in reasons.items()]
    out, seen = [], set()
    for p in picks:
        t = p["ticker"]
        if t in seen:
            continue
        seen.add(t)
        rs = reasons.get(t)
        out.append({"ticker": t, "horizon": p["horizon"] if p["horizon"] in HZ_DAYS else "미분류", "name": names.get(t) or (rs[1] if rs else "") or (get_ticker_info(t)[0] or ""),
                    "reason": rs[2] if rs else ""})
    return out[:10]


@bp.route("/admin/api/daily/ai", methods=["GET"])
def api_ai_get():
    deny = _admin_deny()
    if deny:
        return deny
    date = str(request.args.get("date", "")).strip()
    try:
        r = _dbrows("SELECT result, market_context, picks, updated FROM dly_ai WHERE scan_date=?", ["result", "market_context", "picks", "updated"], (date,))
        if r and (r[0]["result"] or "").strip():
            return _admin_json({"found": True, "result": r[0]["result"], "market_context": r[0]["market_context"], "picks": json.loads(r[0]["picks"] or "[]"), "updated": r[0]["updated"], "src": "web"})
    except Exception:
        pass
    try:
        r = _dbrows("SELECT result, market_context, updated_at FROM daily_ai_result WHERE scan_date=?", ["result", "market_context", "updated_at"], (date,))
        if r and (r[0]["result"] or "").strip():
            rows, _s = load_rows(date)
            return _admin_json({"found": True, "result": r[0]["result"], "market_context": r[0]["market_context"] or "", "picks": parse_ai(r[0]["result"], rows), "updated": r[0]["updated_at"] or "", "src": "orig"})
    except Exception:
        pass
    return _admin_json({"found": False})


@bp.route("/admin/api/daily/ai", methods=["POST"])
def api_ai_save():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d, date = _date_arg()
    text = str(d.get("result") or "").strip()[:60000]
    if not date or len(text) < 50:
        return _admin_json({"error": "날짜와 AI 답변(50자 이상)이 필요해요."}, 400)
    rows, _src = load_rows(date)
    picks = parse_ai(text, rows)
    byt = {r["ticker"]: r for r in rows}
    ctx = str(d.get("market_context") or "")[:600]
    _dbx("INSERT INTO dly_ai(scan_date,result,market_context,picks,updated) VALUES(?,?,?,?,?) ON CONFLICT(scan_date) DO UPDATE SET result=excluded.result, "
         "market_context=excluded.market_context, picks=excluded.picks, updated=excluded.updated", (date, text, ctx, json.dumps(picks, ensure_ascii=False), int(time.time())))
    n = 0
    for p in picks:
        r = byt.get(p["ticker"])
        price = (r or {}).get("price")
        if price is None:
            b = _naver_mobile_basic(p["ticker"])
            price = _f((b or {}).get("closePrice"))
        _dbx("INSERT INTO dly_track(pick_date,ticker,name,horizon,pick_price,pick_score,pick_type) VALUES(?,?,?,?,?,?,?) "
             "ON CONFLICT(pick_date,ticker) DO UPDATE SET name=excluded.name, horizon=CASE WHEN excluded.horizon<>'' AND excluded.horizon<>'미분류' THEN excluded.horizon ELSE dly_track.horizon END",
             (date, p["ticker"], p["name"], p["horizon"], price, (r or {}).get("score", 0), "dip" if r and r["dip"] >= 60 and (r["day_pct"] or 0) < 0 else "normal"))
        n += 1
    _alog("daily_ai_save", f"{date} picks={n}")
    return _admin_json({"ok": True, "picks": picks, "tracked": n})


# ══════════════════════════════════════════════════════════════
# 성과 추적
# ══════════════════════════════════════════════════════════════
def _outcome(ret):
    return "win" if ret >= 1.0 else ("lose" if ret <= -1.0 else "flat")


@bp.route("/admin/api/daily/track", methods=["GET"])
def api_track():
    deny = _admin_deny()
    if deny:
        return deny
    rows = _track_rows(120)
    lp = live_prices([r["ticker"] for r in rows[:80]]) if rows else {}
    today = _now_kst().strftime("%Y-%m-%d")
    changed = 0
    for r in rows:
        v = lp.get(r["ticker"])
        r["now"] = v[0] if v else None
        days = HZ_DAYS.get(r["horizon"], 30)
        try:
            age = (time.mktime(time.strptime(today, "%Y-%m-%d")) - time.mktime(time.strptime(r["date"], "%Y-%m-%d"))) / 86400
        except Exception:
            age = 0
        r["age"] = int(age)
        r["due"] = age >= days
        # 호흡 만기가 지난 웹 추천은 그 시점 가격으로 확정 평가한다(원본 규칙과 같은 방식)
        if r["src"] == "web" and not r["outcome"] and r["due"] and r["now"] and r["pick_price"]:
            rt = round((r["now"] / r["pick_price"] - 1) * 100, 2)
            r["eval_price"], r["eval_date"], r["outcome"] = r["now"], today, _outcome(rt)
            _dbx("UPDATE dly_track SET eval_price=?, eval_date=?, outcome=? WHERE pick_date=? AND ticker=? AND outcome=''", (r["now"], today, r["outcome"], r["date"], r["ticker"]))
            changed += 1
        r["ret"] = _ret(r)
    stat = {}
    for key, flt in (("전체", lambda t: True), ("단기", lambda t: t["horizon"] == "단기"), ("중기", lambda t: t["horizon"] == "중기"), ("장기", lambda t: t["horizon"] == "장기")):
        g = [t for t in rows if flt(t) and t["ret"] is not None]
        ev = [t for t in g if t["outcome"] in ("win", "lose", "flat")]
        stat[key] = {"n": len(g), "avg": round(sum(t["ret"] for t in g) / len(g), 2) if g else None, "up": round(sum(1 for t in g if t["ret"] > 0) / len(g) * 100) if g else None,
                     "ev": len(ev), "win": round(sum(1 for t in ev if t["outcome"] == "win") / len(ev) * 100) if ev else None}
    return _admin_json({"rows": rows[:150], "stat": stat, "settled": changed})


# ══════════════════════════════════════════════════════════════
# 블로그 HTML (원본 방식)
# ══════════════════════════════════════════════════════════════
SECTIONS = [("stats", "요약 통계"), ("market", "시장 환경"), ("top", "점수 TOP"), ("ai", "AI 추천 결과"), ("list", "추천 목록"), ("dip", "음봉강세"), ("track", "지난 추천 성과")]
HZ_COL = {"단기": ("#dc2626", "#fef2f2"), "중기": ("#d97706", "#fffbeb"), "장기": ("#2563eb", "#eff6ff"), "미분류": ("#6b7280", "#f3f4f6")}


def _n(v, d=1):
    return "-" if v is None else format(v, f",.{d}f")


def _pct(v):
    if v is None:
        return "-"
    return f'<span style="color:{B.updown(v)};font-weight:700;">{v:+.2f}%</span>'


def _th(h):
    return f'<td align="center" style="padding:8px 5px;background-color:#1a2744;color:#ffffff;font-size:12px;font-weight:800;">{h}</td>'


def _td(c, i=0, bold=False, bg=""):
    al = "left" if i == 1 else "center"
    return f'<td align="{al}" style="padding:7px 5px;font-size:12.5px;color:{B.TXT};border-bottom:1px solid #f0f0f0;{"font-weight:800;" if bold else ""}{("background-color:" + bg + ";") if bg else ""}">{c}</td>'


def _sig_html(flags):
    col = {"수급전환": "#7c3aed", "쌍끌이": "#16a34a", "거래급증": "#dc2626", "압축": "#0d9488", "신고가권": "#d97706"}
    return " ".join(f'<span style="background-color:{col.get(f, "#6b7280")};color:#ffffff;font-size:10.5px;font-weight:800;padding:1px 6px;">{E(f)}</span>' for f in flags)


def _list_table(rows, top=40):
    head = "".join(_th(h) for h in ("#", "종목", "점수", "현재가", "등락", "PER", "PBR", "RSI", "이평", "신호"))
    body = ""
    for i, r in enumerate(rows[:top], 1):
        sc = r["score"]
        pill = f'<span style="background-color:{"#dc2626" if sc >= 70 else "#ea580c" if sc >= 60 else "#16a34a" if sc >= 50 else "#6b7280"};color:#ffffff;font-weight:900;font-size:12px;padding:2px 8px;border-radius:10px;">{sc}</span>'
        al = {"정배열": "#15803d", "역배열": "#dc2626"}.get(r["align"], "#6b7280")
        nm = f'<a href="https://finance.naver.com/item/main.naver?code={E(r["ticker"])}" target="_blank" style="color:#111827;text-decoration:none;font-weight:800;">{E(r["name"])}</a><br><span style="font-size:10.5px;color:#9ca3af;">{E(r["ticker"])}</span>'
        cells = [str(i), nm, pill, _n(r["price"], 0), _pct(r["day_pct"]), _n(r["per"]), _n(r["pbr"], 2), _n(r["rsi"]),
                 f'<span style="color:{al};font-weight:700;">{E(r["align"] or "-")}</span>', _sig_html(r["flags"]) or "-"]
        body += "<tr>" + "".join(_td(c, k) for k, c in enumerate(cells)) + "</tr>"
    return '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '"><tr>' + head + "</tr>" + body + "</table>"


def split_ai(text):
    """AI 답변을 [추천종목] / [종합의견] / [블로그 제목 후보] 덩어리로 나눈다. 기계 판독 줄은 뺀다."""
    t = re.sub(r"^.*PICKS_JSON\s*:.*$", "", str(text), flags=re.M).replace("\r", "")
    out = {"pre": [], "picks": [], "opinion": [], "other": []}
    cur = "pre"
    for ln in t.split("\n"):
        s = ln.strip()
        m = re.match(r"^[#\s]*\[?\s*(추천\s*종목|종합\s*의견|블로그\s*제목\s*후보[^\]]*|기계\s*판독[^\]]*)\s*\]?\s*$", s)
        if m:
            k = m.group(1)
            cur = "picks" if k.startswith("추천") else "opinion" if k.startswith("종합") else "skip"
            continue
        if cur == "skip":
            continue
        out[cur].append(ln)
    return {k: "\n".join(v).strip() for k, v in out.items() if k != "skip"}


def _picks_html(picks, byt, parts_raw):
    if not picks:
        return ""
    rows = ""
    for i, p in enumerate(picks, 1):
        r = byt.get(p["ticker"]) or {}
        c, bg = HZ_COL.get(p["horizon"], HZ_COL["미분류"])
        sc = r.get("score")
        info = " · ".join(x for x in (f"점수 {sc}점" if sc is not None else "", f"{_n(r.get('price'), 0)}원" if r.get("price") else "", f"PER {_n(r.get('per'))}" if r.get("per") else "",
                                      f"RSI {_n(r.get('rsi'))}" if r.get("rsi") is not None else "", r.get("align") or "") if x)
        rows += (f'<tr><td width="14%" align="center" valign="top" bgcolor="{bg}" style="background-color:{bg};padding:12px 6px;border-bottom:1px solid #e5e7eb;">'
                 f'<div style="font-size:11px;font-weight:900;color:{c};">AI #{i}</div><div style="font-size:12px;font-weight:900;color:#ffffff;background-color:{c};margin-top:4px;padding:2px 0;">{E(p["horizon"])}</div></td>'
                 f'<td valign="top" style="padding:12px 14px;border-bottom:1px solid #e5e7eb;"><div style="font-size:16px;font-weight:900;color:#0d1b3e;">{E(p["name"])} <span style="font-size:11px;color:#9ca3af;font-weight:700;">{E(p["ticker"])}</span></div>'
                 f'<div style="font-size:11.5px;color:#6b7280;margin:3px 0 6px;">{E(info)}</div>'
                 f'<div style="font-size:14px;color:#1f2937;line-height:1.85;word-break:keep-all;">{B.inline(p.get("reason") or "", "#b45309")}</div></td></tr>')
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:2px solid #0d1b3e;margin:6px 0 14px;' + B.FONT + '"><tr>'
            '<td colspan="2" bgcolor="#0d1b3e" style="background-color:#0d1b3e;padding:13px 18px;"><span style="font-size:16px;font-weight:900;color:#f0b429;">&#129302; AI 추천주 선정 결과</span>'
            '<span style="font-size:11px;color:#93c5fd;margin-left:8px;">기술적 분석 + 수급 + 뉴스 종합 판단</span></td></tr>' + rows + "</table>")


def track_summary_html():
    ev = [t for t in _track_rows(180) if t["outcome"] in ("win", "lose", "flat") and _ret(t) is not None][:12]
    if len(ev) < 3:
        return ""
    win = sum(1 for t in ev if t["outcome"] == "win")
    body = "".join(_tr_track(t) for t in ev)
    return (B.side_title("&#128202; 지난 AI 추천 성과 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(호흡 만기 시점 기준 · 최근 %d건)</span>" % len(ev), "#0d9488")
            + f'<p style="font-size:13px;color:{B.TXT};line-height:1.8;margin:0 0 8px;">최근 평가 {len(ev)}건 중 <b>{win}건</b>이 +1% 이상(승률 {round(win / len(ev) * 100)}%). 과거 성과가 앞으로의 수익을 보장하지 않으며, 잘 안 맞은 사례도 그대로 공개합니다.</p>'
            + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '"><tr>' + "".join(_th(h) for h in ("추천일", "종목", "호흡", "추천가", "평가가", "수익률")) + "</tr>" + body + "</table>")


def _tr_track(t):
    cells = [E(t["date"][5:]), E(t["name"] or t["ticker"]), E(t["horizon"]), _n(t["pick_price"], 0), _n(t["eval_price"], 0), _pct(_ret(t))]
    return "<tr>" + "".join(_td(c, 1 if k == 1 else 0) for k, c in enumerate(cells)) + "</tr>"


def build_blog(date, rows, ai_text="", inc=None, title="", n=30, macro=None):
    inc = inc or {k: True for k, _ in SECTIONS}
    rk = risk_set()
    rows = [r for r in rows if r["ticker"] not in rk]
    rows = sorted(rows, key=lambda r: -r["score"])
    cnt = len(rows)
    byt = {r["ticker"]: r for r in rows}
    aip = parse_ai(ai_text, rows) if ai_text.strip() else []
    avg = round(sum(r["score"] for r in rows) / cnt) if cnt else 0
    s70 = sum(1 for r in rows if r["score"] >= 70)
    s60 = sum(1 for r in rows if 60 <= r["score"] < 70)
    align = sum(1 for r in rows if r["align"] == "정배열")
    up = sum(1 for r in rows if (r["day_pct"] or 0) > 0)
    dn = sum(1 for r in rows if (r["day_pct"] or 0) < 0)
    parts = split_ai(ai_text) if ai_text.strip() else {}
    titles = B.extract_titles(ai_text)
    if not titles and ai_text:
        m = re.search(r"\[블로그\s*제목\s*후보[^\]]*\]\s*\n((?:[-•*]\s*.+\n?)+)", ai_text)
        if m:
            titles = [re.sub(r"^[-•*]\s*", "", x).strip(" \"“”") for x in m.group(1).strip().split("\n")][:5]
    ai_part = f" · AI 추천 {len(aip)}종목" if aip else ""
    auto_title = f"🌟 오늘의 추천 주식 {cnt}선 ({date}){ai_part} | 기술적 분석 자동선별 | 정배열 {align}개 · 70점↑ {s70}개"
    title = title or (titles[0] if titles else auto_title)
    names = [r["name"] for r in rows[:15]]
    tags, tag_html = B.hashtags(names, date, extra=["오늘의추천주", "주식추천"])
    h = []
    h.append(B.seo_box(auto_title, "시가총액 상위 종목을 기술적 지표(이평선·RSI·거래량·52주 위치)로 자동 선별하고 수급·뉴스까지 점검한 오늘의 후보를 정리했어요.", ["오늘의추천주", "주식추천", "정배열", "음봉강세"] + names[:3]))
    h.append(B.head_box(f"★ DAILY STOCK PICK · {date}", f'오늘의 추천 주식 <span style="color:{B.GOLD};">{cnt}선</span>', "기술적 분석 자동 선별 · 수급 · 뉴스 점검"))
    if inc.get("stats"):
        def cell(label, val, c):
            return (f'<td align="center" style="padding:10px 4px;background-color:#f8faff;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;margin-bottom:3px;">{label}</div>'
                    f'<div style="font-size:19px;font-weight:900;color:{c};">{val}</div></td>')
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:14px 0;' + B.FONT + '"><tr>'
                 + cell("평균점수", f"{avg}점", "#2563eb") + cell("&#128293; 70점↑", f"{s70}개", "#dc2626") + cell("&#128064; 60점↑", f"{s60}개", "#ea580c") + cell("&#128200; 정배열", f"{align}개", "#16a34a")
                 + cell("&#9650; 상승", f"{up}개", "#dc2626") + cell("&#9660; 하락", f"{dn}개", "#2563eb") + cell("&#129302; AI추천", f"{len(aip)}개", "#d97706") + "</tr></table>")
    if inc.get("market"):
        mc = macro if macro is not None else macro_snapshot()
        if mc.get("rows"):
            body = "".join(f'<td align="center" style="padding:8px 4px;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;">{E(x["name"])}</div><div style="font-size:14px;font-weight:900;color:#111827;">{E(x["close"])}</div>'
                           f'<div style="font-size:11.5px;">{_pct(x["pct"])}</div></td>' for x in mc["rows"])
            h.append(B.side_title("&#127758; 오늘의 시장 환경", "#2563eb") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '"><tr>' + body + "</tr></table>")
    if inc.get("top") and rows:
        trs = ""
        for r in rows[:10]:
            c = B.tone(r["score"])
            trs += (f'<tr><td width="26%" style="padding:5px 4px;font-size:13px;font-weight:800;color:#111827;">{E(r["name"])}</td><td width="62%" style="padding:5px 4px;">{B.bar(r["score"], c)}</td>'
                    f'<td width="12%" align="right" style="padding:5px 4px;font-size:13px;font-weight:900;color:{c};">{r["score"]}</td></tr>')
        h.append(B.side_title("&#127942; 점수 TOP 10", "#d97706") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '">' + trs + "</table>")
    if inc.get("ai") and ai_text.strip():
        h.append(B.side_title("&#129302; AI 추천주 분석", "#0d1b3e"))
        if aip:
            h.append(_picks_html(aip, byt, parts))
        if parts.get("opinion"):
            h.append(B.section_card("&#129517;", "종합의견", "시장 전략 · 리스크 관리", parts["opinion"], "#4f46e5", "#f5f6ff"))
        elif not aip:
            h.append(B.ai_to_html(re.sub(r"^.*PICKS_JSON.*$", "", ai_text, flags=re.M)))
        if parts.get("pre") and not aip:
            h.append(B.ai_to_html(parts["pre"]))
    if inc.get("list") and rows:
        h.append(B.side_title(f"&#128203; 오늘의 추천 종목 TOP {min(n, cnt)}", "#2563eb") + _list_table(rows, n))
        h.append('<p style="font-size:11.5px;color:#9ca3af;margin:6px 0 0;">점수는 20일선 이격·거래량·52주 위치·RSI로 계산한 0~100점 기술 지표예요. 신호: 수급전환(20일 약세→5일 매수 전환) · 쌍끌이(외국인·기관 20일 동반 순매수) · 거래급증(평소 2배↑) · 압축(변동성 축소) · 신고가권.</p>')
    if inc.get("dip"):
        dips = [r for r in sorted(rows, key=lambda r: -r["dip"]) if (r["day_pct"] or 0) < 0 and r["dip"] >= 60][:8]
        if dips:
            h.append(B.side_title("&#128269; 음봉강세 후보 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(오늘 하락했지만 구조는 건강한 종목)</span>", "#7c3aed"))
            h.append(_list_table(dips, 8))
    if inc.get("track"):
        h.append(track_summary_html())
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/daily/blog", methods=["POST"])
def api_blog():
    deny = _admin_deny()
    if deny:
        return deny
    d, date = _date_arg()
    if not date:
        return _admin_json({"error": "날짜를 고르세요."}, 400)
    rows, _src = load_rows(date)
    if not rows:
        return _admin_json({"error": "이 날짜의 추천 종목이 없어요."}, 404)
    inc = d.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k, _ in SECTIONS} if isinstance(inc, dict) else None
    try:
        n = max(5, min(60, int(d.get("n") or 30)))
    except Exception:
        n = 30
    b = build_blog(date, rows, str(d.get("ai") or "")[:60000], inc, str(d.get("title") or "").strip()[:150], n)
    pseudo = "D" + date.replace("-", "")[2:]
    logs, warn = B.dup_info(pseudo, "daily")
    b.update({"ticker": pseudo, "name": f"오늘추천 {date}", "dups": logs, "dup_warn": warn})
    return _admin_json(b)


# ══════════════════════════════════════════════════════════════
# 관리자 화면 탭 (JS)
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var DY={st:null,date:'',rows:[],src:'',dates:[],excl:0,f:{min:0,align:false,dip:false,sig:'',q:'',sort:'score'},live:false,ai:{},tab:'list',_poll:null};
function dyCol(s){return s>=70?'#dc2626':(s>=60?'#ea580c':(s>=50?'#16a34a':'#6b7280'))}
function dyN(v,d){if(v==null)return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?1:d})}
function dySty(e,s){e.style.cssText=s;return e}
function dyLoad(p){p.innerHTML='';var top=el('div','c');top.appendChild(el('b',null,'🌟 오늘추천'));
 top.appendChild(el('p','note','시가총액 상위 종목을 기술 지표로 점수화해 오늘의 후보를 고르고, AI 추천주 선정과 블로그 글까지 이어서 만들어요(원본 프로그램 방식). 위험(상장폐지·거래정지) 신호 종목은 자동으로 빠집니다. 투자 권유가 아닌 참고용이며, 일반 이용자에게는 보이지 않는 관리자 전용 메뉴예요.'));p.appendChild(top);
 var sc=el('div','c');sc.id='dyScan';p.appendChild(sc);var mid=el('div');mid.id='dyMain';p.appendChild(mid);
 api('/admin/api/daily/state').then(function(j){if(cur!=='dy')return;DY.st=j;dyScanDraw();DY.dates=j.dates||[];if(j.scan&&j.scan.running)dyPoll();
  var d0=DY.date||(DY.dates[0]&&DY.dates[0].date)||'';if(d0)dyOpen(d0);else dyMainDraw()})}
function dyScanDraw(){var b=$('dyScan');if(!b)return;b.innerHTML='';var c=DY.st.cfg,last=DY.st.last||{};b.appendChild(el('b',null,'🔍 스캔 (오늘의 후보 만들기)'));
 b.appendChild(el('p','note','시가총액 순으로 종목을 훑어 점수를 매기고 기준을 넘은 종목을 저장해요. 종목 수에 따라 1~3분 걸리며 이 화면을 떠나도 계속 돌아요. 장 마감 후나 장중 아무 때나 실행해도 됩니다(같은 날짜는 덮어씀).'));
 var r=el('div','bar');var ck={};['KOSPI','KOSDAQ'].forEach(function(m){var l=el('label');l.style.marginRight='10px';var i=el('input');i.type='checkbox';i.checked=c.markets.indexOf(m)>=0;ck[m]=i;l.appendChild(i);l.appendChild(document.createTextNode(' '+m));r.appendChild(l)});b.appendChild(r);
 function num(lbl,val,w,mn,mx){var s=el('span','m',lbl+' ');var i=el('input');i.type='number';i.value=val;i.min=mn;i.max=mx;i.style.width=w;s.appendChild(i);s.style.marginRight='12px';r2.appendChild(s);return i}
 var r2=el('div','bar');var ct=num('시총 상위',c.cap_top,'70px',30,600),ms=num('최소 점수',c.min_score,'60px',0,95),cn=num('저장 개수',c.count,'60px',5,150),kr=num('코스피 비중%(0=합쳐서)',c.kospi_ratio,'60px',0,100);b.appendChild(r2);
 var r3=el('div','bar');var go=bt('🔍 지금 스캔','bt',function(){var mk=Object.keys(ck).filter(function(k){return ck[k].checked});if(!mk.length){toast('시장을 하나 이상 고르세요');return}
  apiJ('/admin/api/daily/scan',{markets:mk,cap_top:+ct.value,min_score:+ms.value,count:+cn.value,kospi_ratio:+kr.value}).then(function(j){if(j.error){toast(j.error);return}DY.st.cfg=j.cfg;toast('스캔을 시작했어요');dyPoll()})});go.id='dyGo';r3.appendChild(go);
 r3.appendChild(bt('중단','bt3',function(){apiJ('/admin/api/daily/scan-cancel',{}).then(function(){toast('중단 요청')})}));b.appendChild(r3);
 var pg=el('div');pg.id='dyProg';dySty(pg,'margin-top:8px');b.appendChild(pg);
 if(last.date){var m=el('div','m','마지막 스캔: '+last.date+' · '+(last.saved||0)+'종목 저장'+(last.error?' · ⚠ '+last.error:''));b.appendChild(m)}}
function dyPoll(){clearInterval(DY._poll);var g=$('dyGo');if(g)g.disabled=true;DY._poll=setInterval(function(){if(cur!=='dy'){clearInterval(DY._poll);return}
  api('/admin/api/daily/scan-status').then(function(s){var pg=$('dyProg');if(!pg)return;pg.innerHTML='';var pc=s.total?Math.round(s.done/s.total*100):0;
   var w=el('div');dySty(w,'height:12px;background:#e5e7eb;border-radius:7px;overflow:hidden');var i=el('div');dySty(i,'height:100%;width:'+pc+'%;background:#2563eb');w.appendChild(i);pg.appendChild(w);
   pg.appendChild(el('div','m',(s.running?'⏳ ':'')+(s.current||'')+' · 통과 '+s.kept+'종목'));
   if(!s.running){clearInterval(DY._poll);var g2=$('dyGo');if(g2)g2.disabled=false;if(s.error){pg.appendChild(el('div','note bad','⚠ '+s.error))}else if(s.scan_date){toast('스캔 완료 — '+s.saved+'종목 저장');
    api('/admin/api/daily/state').then(function(j){DY.st=j;DY.dates=j.dates;dyScanDraw();dyOpen(s.scan_date)})}}})},1500)}
function dyOpen(date,live){DY.date=date;if(live!=null)DY.live=live;var m=$('dyMain');if(m&&!DY.rows.length)m.innerHTML='<div class="c">⏳ 불러오는 중…</div>';
 api('/admin/api/daily/list?date='+encodeURIComponent(date)+(DY.live?'&live=1':'')).then(function(j){if(cur!=='dy')return;DY.rows=j.rows||[];DY.src=j.src;DY.dates=j.dates||DY.dates;DY.excl=j.excluded||0;DY.prev=j.prev_date||'';DY.date=j.date;dyMainDraw()})}
function dyMainDraw(){var m=$('dyMain');if(!m)return;m.innerHTML='';
 if(!DY.dates.length){m.appendChild(el('div','c','아직 저장된 추천이 없어요. 위의 [🔍 지금 스캔]을 눌러 시작하세요.'));return}
 var dc=el('div','c');dc.appendChild(el('b',null,'📅 날짜'));var chips=el('div');dySty(chips,'display:flex;flex-wrap:wrap;gap:5px;margin-top:6px');
 DY.dates.slice(0,24).forEach(function(d){var b=bt(d.date.slice(5)+' ('+d.n+')'+(d.src==='orig'?' 원본':''),d.date===DY.date?'bt':'bt3',function(){DY.rows=[];dyOpen(d.date)});chips.appendChild(b)});dc.appendChild(chips);
 var ar=el('div','bar');ar.style.marginTop='8px';ar.appendChild(bt('🔄 현재가로 수익률 보기','bt2',function(){dyOpen(DY.date,true)}));
 if(DY.src==='web')ar.appendChild(bt('🗑 이 날짜 스캔 삭제','bt3',function(){if(!confirm(DY.date+' 스캔 기록을 지울까요? (AI 결과·성과 기록은 그대로)'))return;apiJ('/admin/api/daily/delete',{date:DY.date}).then(function(){DY.rows=[];DY.date='';api('/admin/api/daily/state').then(function(j){DY.dates=j.dates;if(j.dates.length)dyOpen(j.dates[0].date);else dyMainDraw()})})}));
 dc.appendChild(ar);m.appendChild(dc);
 var tb=el('div','bar');tb.style.margin='8px 0';[['list','📋 추천 목록'],['ai','🤖 AI 추천·블로그'],['track','📈 성과 추적']].forEach(function(t){tb.appendChild(bt(t[1],DY.tab===t[0]?'bt':'bt3',function(){DY.tab=t[0];dyMainDraw()}))});m.appendChild(tb);
 var body=el('div');m.appendChild(body);if(DY.tab==='list')dyList(body);else if(DY.tab==='ai')dyAI(body);else dyTrack(body)}
function dyFiltered(){var f=DY.f,q=f.q.trim().toLowerCase();var a=DY.rows.filter(function(r){if(r.score<f.min&&!(f.dip&&r.dip>=60))return false;if(f.align&&r.align!=='정배열')return false;if(f.dip&&!(r.day_pct<0&&r.dip>=60))return false;
  if(f.sig&&r.flags.indexOf(f.sig)<0)return false;if(q&&(r.name.toLowerCase().indexOf(q)<0&&r.ticker.indexOf(q)<0))return false;return true});
 var k=f.sort;a.sort(function(x,y){if(k==='dip')return y.dip-x.dip;if(k==='pct')return (y.day_pct||0)-(x.day_pct||0);if(k==='since')return (y.since||-99)-(x.since||-99);if(k==='streak')return (y.streak||0)-(x.streak||0);return y.score-x.score});return a}
function dyList(b){var rows=DY.rows;var c=el('div','c');
 var avg=rows.length?Math.round(rows.reduce(function(s,r){return s+r.score},0)/rows.length):0;var s70=rows.filter(function(r){return r.score>=70}).length,al=rows.filter(function(r){return r.align==='정배열'}).length,up=rows.filter(function(r){return r.day_pct>0}).length,nw=rows.filter(function(r){return r.new}).length;
 c.appendChild(el('div',null,'📊 '+DY.date+' · '+rows.length+'종목 · 평균 '+avg+'점 · 70점↑ '+s70+' · 정배열 '+al+' · 상승 '+up+'/하락 '+(rows.length-up)+(nw?' · 🆕 신규 '+nw+(DY.prev?' (직전 '+DY.prev.slice(5)+' 대비)':''):'')+(DY.excl?' · 위험종목 '+DY.excl+'개 자동 제외':'')+(DY.src==='orig'?' · 원본 프로그램 기록':'')));
 var f=DY.f,fr=el('div','bar');fr.style.marginTop='8px';var q=el('input');q.placeholder='종목 검색';q.value=f.q;q.style.width='120px';q.oninput=function(){f.q=q.value;dyListBody(lb)};fr.appendChild(q);
 var ms=el('input');ms.type='number';ms.value=f.min;ms.style.width='56px';ms.title='최소 점수';ms.oninput=function(){f.min=+ms.value||0;dyListBody(lb)};fr.appendChild(el('span','m',' 점수≥'));fr.appendChild(ms);
 function ck(lbl,key){var l=el('label');l.style.marginLeft='8px';var i=el('input');i.type='checkbox';i.checked=f[key];i.onchange=function(){f[key]=i.checked;dyListBody(lb)};l.appendChild(i);l.appendChild(document.createTextNode(' '+lbl));fr.appendChild(l)}ck('정배열만','align');ck('음봉강세만','dip');
 var sg=el('select');[['','신호 전체'],['수급전환','수급전환'],['쌍끌이','쌍끌이'],['거래급증','거래급증'],['압축','압축'],['신고가권','신고가권']].forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];if(o[0]===f.sig)op.selected=true;sg.appendChild(op)});sg.onchange=function(){f.sig=sg.value;dyListBody(lb)};fr.appendChild(sg);
 var so=el('select');[['score','점수순'],['dip','음봉강세순'],['pct','등락순'],['since','스캔후수익순'],['streak','연속등장순']].forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];if(o[0]===f.sort)op.selected=true;so.appendChild(op)});so.onchange=function(){f.sort=so.value;dyListBody(lb)};fr.appendChild(so);c.appendChild(fr);
 var lb=el('div');lb.style.overflowX='auto';c.appendChild(lb);b.appendChild(c);dyListBody(lb)}
function dyListBody(lb){lb.innerHTML='';var a=dyFiltered();var t=el('table'),h=el('tr');['#','종목','점수','음봉강세','현재가','등락','스캔후','PER','PBR','RSI','이평','52주','수급(억) 5일 외/기','신호','연속',''].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 a.slice(0,200).forEach(function(r,i){var tr=el('tr');tr.appendChild(el('td',null,i+1));var nm=el('td');nm.appendChild(el('b',null,r.name));nm.appendChild(el('div','m',r.ticker+(r.market?' · '+r.market:'')+(r.new?' 🆕':'')));tr.appendChild(nm);
  var s=el('td',null,r.score);s.style.cssText='font-weight:800;color:'+dyCol(r.score);tr.appendChild(s);tr.appendChild(el('td',r.dip>=60&&r.day_pct<0?'up':'',r.dip?r.dip:'-'));
  tr.appendChild(el('td',null,dyN(r.now||r.price,0)));var pc=r.now_pct!=null?r.now_pct:r.day_pct;tr.appendChild(el('td',pc>0?'up':(pc<0?'dn':''),pc==null?'-':(pc>0?'+':'')+pc.toFixed(2)+'%'));
  tr.appendChild(el('td',r.since>0?'up':(r.since<0?'dn':''),r.since==null?'-':(r.since>0?'+':'')+r.since.toFixed(2)+'%'));tr.appendChild(el('td',null,dyN(r.per)));tr.appendChild(el('td',null,dyN(r.pbr,2)));tr.appendChild(el('td',null,dyN(r.rsi)));tr.appendChild(el('td',null,r.align||'-'));tr.appendChild(el('td',null,r.pos52==null?'-':Math.round(r.pos52)+'%'));
  tr.appendChild(el('td','m',r.f5==null?'-':dyN(r.f5,0)+' / '+dyN(r.i5,0)));tr.appendChild(el('td',null,r.flags.join(' ')||'-'));tr.appendChild(el('td',null,r.streak>1?r.streak+'일':'-'));
  var ac=el('td');ac.appendChild(bt('🏛','bt3',function(){try{localStorage.setItem('mini_deep_ticker',r.ticker)}catch(e){}cur='dp';nav();load()}));var lk=el('a',null,' 증권');lk.href='https://finance.naver.com/item/main.naver?code='+r.ticker;lk.target='_blank';lk.rel='noopener';ac.appendChild(lk);tr.appendChild(ac);t.appendChild(tr)});
 Array.prototype.forEach.call(t.querySelectorAll('td,th'),function(x){x.style.whiteSpace='nowrap';x.style.wordBreak='normal'});
 lb.appendChild(t);if(!a.length)lb.appendChild(el('p','note','조건에 맞는 종목이 없어요.'));if(a.length>200)lb.appendChild(el('p','note','상위 200개만 보여줘요.'));
 lb.appendChild(el('p','note','🏛 = 심층분석으로 열기. 점수는 20일선 이격·거래량·52주 위치·RSI 기반 기술 지표(0~100)이고, 음봉강세는 오늘 하락했지만 정배열·소량 음봉·MA20 지지 등 구조가 건강한 정도예요. 스캔후 = 스캔 당시 가격 대비 현재가(🔄 버튼으로 불러와요).'))}
function dyAI(b){var c=el('div','c');c.appendChild(el('b',null,'🤖 AI 추천주 선정'));
 c.appendChild(el('p','note','후보 25개(+음봉강세 10개)와 거시 환경·수급·최근 뉴스·과거 성과(오답노트)를 담은 요청문을 만들어 설정된 AI를 열어요. 답변을 복사하고 이 탭으로 돌아오면 자동으로 읽어 오고, 추천 종목은 성과 추적에 저장돼요. 요청문은 [프롬프트] 탭에서 고칠 수 있어요.'));
 var rr=el('div');rr.appendChild(bt('🤖 AI 추천주 만들기','bt',function(){dyAIRun()}));c.appendChild(rr);var st=el('div','m');st.id='dyAiSt';c.appendChild(st);
 var ta=el('textarea');ta.id='dyAiTa';ta.placeholder='AI 답변을 직접 붙여넣어도 돼요.';dySty(ta,'width:100%;min-height:140px;box-sizing:border-box;margin-top:6px');ta.value=DY.ai[DY.date]||'';ta.oninput=function(){DY.ai[DY.date]=ta.value;dyAiState()};c.appendChild(ta);
 var sr=el('div','bar');sr.appendChild(bt('💾 이 답변 저장(성과 추적 시작)','bt2',function(){var t=ta.value;if(t.trim().length<50){toast('AI 답변을 먼저 넣으세요');return}apiJ('/admin/api/daily/ai',{date:DY.date,result:t,market_context:DY.mc||''}).then(function(j){if(j.error){toast(j.error);return}toast('저장했어요 — 추천 '+j.picks.length+'종목을 성과 추적에 넣었어요');dyPicks(j.picks)})}));c.appendChild(sr);
 var pk=el('div');pk.id='dyPicks';c.appendChild(pk);b.appendChild(c);
 if(DY.ai[DY.date]==null){api('/admin/api/daily/ai?date='+encodeURIComponent(DY.date)).then(function(j){if(DY.tab!=='ai')return;if(j.found){DY.ai[DY.date]=j.result;DY.mc=j.market_context;var t=$('dyAiTa');if(t)t.value=j.result;dyPicks(j.picks);dyAiState('저장된 AI 결과를 불러왔어요('+(j.src==='orig'?'원본 프로그램':'웹')+')')}})}else dyAiState();
 var bc=el('div','c');bc.appendChild(el('b',null,'📝 블로그 글 만들기 (🌟 오늘의 추천 주식 N선)'));var bx=el('div');bc.appendChild(bx);b.appendChild(bc);
 var secs=[['stats','요약통계'],['market','시장환경'],['top','점수TOP'],['ai','AI추천결과'],['list','추천목록'],['dip','음봉강세'],['track','지난성과']];
 window.BlogKit.panel(bx,{idp:'dy',key:'daily',kind:'daily',ticker:'D'+DY.date.replace(/-/g,'').slice(2),name:'오늘추천 '+DY.date,sections:secs,dup_warn:'',
  build:function(inc,title){return apiJ('/admin/api/daily/blog',{date:DY.date,ai:DY.ai[DY.date]||'',inc:inc,title:title,n:30})}})}
function dyPicks(ps){var pk=$('dyPicks');if(!pk)return;pk.innerHTML='';if(!ps||!ps.length)return;pk.appendChild(el('div','m','추천 종목: '+ps.map(function(p){return p.name+'('+p.ticker+', '+p.horizon+')'}).join(' · ')))}
function dyAiState(msg){var z=$('dyAiSt');if(!z)return;var t=DY.ai[DY.date]||'';z.textContent=(msg?msg+' · ':'')+(t.trim()?('✅ AI 글 '+t.length.toLocaleString()+'자 — 블로그 글에 포함돼요.'):'아직 AI 글이 없어요(없어도 블로그 글은 만들 수 있어요).')}
function dyAIRun(){if(!window.MiniAI){toast('AI 도우미 파일(menu_ui.py)이 올라가지 않았어요.');return}
 apiJ('/admin/api/daily/prompt',{date:DY.date}).then(function(j){if(j.error){toast(j.error);return}DY.mc=j.market_context;
  window.MiniAI.run({title:'오늘추천 AI — '+DY.date,key:'daily',steps:[{label:DY.date+' 후보 '+j.count+'종목',prompt:j.prompt}],minLen:300,hint:'AI가 [추천종목] [종합의견] 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){var ok=/\[추천종목\]/.test(t)||/PICKS_JSON/.test(t)||/\[(단기|중기|장기)/.test(t);var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString()+'자 — '+t.slice(0,260)+(t.length>260?' …':'');return {node:x,canApply:ok,text:ok?null:'[추천종목] 형식이 보이지 않아요. 다른 답변이 복사된 건 아닌지 확인하세요.'}},
   apply:function(t){DY.ai[DY.date]=t;var ta=$('dyAiTa');if(ta)ta.value=t;return apiJ('/admin/api/daily/ai',{date:DY.date,result:t,market_context:DY.mc||''}).then(function(z){if(z.error)return {message:'읽었지만 저장하지 못했어요: '+z.error};dyPicks(z.picks);dyAiState();return {message:'AI 답변을 읽고 저장했어요(추천 '+z.picks.length+'종목 성과 추적 시작). 아래 [글 만들기]를 누르세요.'}})}})})}
function dyTrack(b){var c=el('div','c');c.appendChild(el('b',null,'📈 AI 추천 성과 추적'));c.appendChild(el('p','note','AI가 추천한 종목의 추천가 대비 현재 수익률이에요. 호흡(단기 7일·중기 30일·장기 90일)이 지나면 그 시점 가격으로 승/패(±1% 기준)를 확정하고, 확정된 건이 5건 이상 쌓이면 다음 AI 요청문의 오답노트에 자동 반영돼요. 원본 프로그램의 기록도 함께 보여줘요.'));
 var body=el('div');c.appendChild(body);body.appendChild(el('div','m','⏳ 현재가를 불러오는 중…'));b.appendChild(c);
 api('/admin/api/daily/track').then(function(j){if(DY.tab!=='track')return;body.innerHTML='';var s=j.stat;var t0=el('table'),h=el('tr');['구분','건수','평균 수익률','수익 비율','확정 평가','승률'].forEach(function(x){h.appendChild(el('th',null,x))});t0.appendChild(h);
  ['전체','단기','중기','장기'].forEach(function(k){var v=s[k];var tr=el('tr');tr.appendChild(el('td',null,k));tr.appendChild(el('td',null,v.n));tr.appendChild(el('td',v.avg>0?'up':(v.avg<0?'dn':''),v.avg==null?'-':(v.avg>0?'+':'')+v.avg+'%'));tr.appendChild(el('td',null,v.up==null?'-':v.up+'%'));tr.appendChild(el('td',null,v.ev));tr.appendChild(el('td',null,v.win==null?'-':v.win+'%'));t0.appendChild(tr)});body.appendChild(t0);
  var tw=el('div');tw.style.overflowX='auto';tw.style.marginTop='8px';var t=el('table'),hh=el('tr');['추천일','종목','호흡','점수','추천가','현재가','수익률','경과','결과','출처'].forEach(function(x){hh.appendChild(el('th',null,x))});t.appendChild(hh);
  j.rows.forEach(function(r){var tr=el('tr');tr.appendChild(el('td',null,r.date.slice(5)));tr.appendChild(el('td',null,r.name+' '+r.ticker));tr.appendChild(el('td',null,r.horizon));tr.appendChild(el('td',null,r.score||'-'));tr.appendChild(el('td',null,dyN(r.pick_price,0)));tr.appendChild(el('td',null,dyN(r.now||r.eval_price,0)));
   tr.appendChild(el('td',r.ret>0?'up':(r.ret<0?'dn':''),r.ret==null?'-':(r.ret>0?'+':'')+r.ret+'%'));tr.appendChild(el('td',null,r.age+'일'+(r.due?' ✔':'')));tr.appendChild(el('td',null,r.outcome==='win'?'✅ 승':(r.outcome==='lose'?'❌ 패':(r.outcome==='flat'?'➖ 보합':'진행중'))));tr.appendChild(el('td','m',r.src==='orig'?'원본':'웹'));t.appendChild(tr)});
  tw.appendChild(t);body.appendChild(tw);if(!j.rows.length)body.appendChild(el('p','note','아직 추적 중인 추천이 없어요. [🤖 AI 추천·블로그]에서 AI 답변을 저장하면 시작돼요.'));if(j.settled)body.appendChild(el('p','note','이번에 만기 평가 '+j.settled+'건을 확정했어요.'))})}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_settings({"daily_cfg": json.dumps(DEFAULT_CFG, ensure_ascii=False), "daily_last_scan": ""}, {"daily_cfg": _valid_cfg})
    C.register_menu({"id": "daily", "label": "오늘추천", "icon": "🌟", "public_path": "/daily", "admin_path": "/admin#dy",
                     "desc": "시총 상위 종목 점수 스캔·AI 추천주 선정·성과 추적·블로그 글쓰기", "access": "admin", "admin_only": True})
    C.register_prompt("daily_pick", {
        "title": "오늘추천 AI 프롬프트", "default": DAILY_DEFAULT, "required": ["{main_lines}"], "must_have": ["[추천종목]"],
        "vars": "{main_lines}=후보 목록(필수) · {dip_section} · {market_weather} · {macro_snapshot} · {learning_note} · {context} · {today}",
        "desc": "오늘추천 화면에서 AI에게 보내는 요청문. '[추천종목]' 형식과 마지막 PICKS_JSON 줄을 유지해야 추천 종목이 자동 저장·성과 추적돼요."})
    C.register_admin_tab("dy", "🌟 오늘추천", TAB_JS, "dyLoad")
    return bp
