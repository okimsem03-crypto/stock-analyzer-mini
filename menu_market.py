"""📊 시장수급 — 그날의 시장 수급을 주체별(개인·외국인·기관 + 가능한 세부 주체)로 분석해 보여 주고, AI 해설·이미지·블로그 글까지 만든다.

원본 프로그램의 [📊 시장수급] 탭(코스피·코스닥 투자자별 순매수)을 웹 미니에 맞게 옮겼다.

자료 출처 — 지금 네이버에서 실제로 받을 수 있는 것만 쓴다(2026-09-11 개편으로 예전 투자자별 매매동향 페이지는 HTTP 410 으로 사라짐)
  ① 시장 전체(src='index')  m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/trend — 개인·외국인·기관 순매수(억원) 하루치.
        하루치만 주는 주소라서, 가져올 때마다 날짜별로 쌓아 이력을 만든다(과거 날짜 조회(bizdate)가 되면 그만큼 한꺼번에 채운다).
        응답에 '…Value' 로 끝나는 숫자 항목이 더 있으면 그것도 주체로 함께 저장한다.
  ② 수집 종목 합산(src='univ')  [📥 종목 수급 가져오기](시가총액 상위 N종목, 최근 20거래일)가 날짜별로 더한 개인·외국인·기관 순매수.
        시장 전체 값이 아니라 '수집한 종목의 합'이지만, 20거래일 흐름이 바로 생긴다.
  ③ 세부 주체(src='paste')  KRX 정보데이터시스템·증권사 표를 관리자가 붙여 넣으면 금융투자·보험·투신·사모·은행·연기금·기타금융·기타법인·국가 등을 추가한다.
  · 거래원(증권사 창구)은 종목 단위 자료라 시장 전체 메뉴에는 넣지 않았다(네이버가 주는 주소도 확인되지 않음).
  · 종목별 상위(외국인·기관·개인 순매수 상위/하위)는 investor_scan_cache(수집한 종목의 1·5·20일 합계)를 쓴다.

회원 화면은 기능별 등급(sum·detail·flow·stocks·extra·ai·img·exp·guide)으로 열고, 가져오기·붙여넣기·AI 저장·블로그 글은 관리자 전용이다.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from flask import Blueprint, request

from menu_ctx import C
import menu_blog as B

bp = Blueprint("market", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "prompt_get", "_now_kst", "setting_get", "setting_set")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

MENU = "market"
BASE = "https://m.stock.naver.com"
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
KEY_AI = "market_ai_last"
KEY_LAST = "market_last_fetch"
KEY_IDX = "market_idx_last"
STALE_DAYS = 7
MARKETS = ("KOSPI", "KOSDAQ")
MK_NAME = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "ALL": "코스피+코스닥"}
BLOG_SECS = ("stats", "actors", "flow", "stocks", "themes", "ai")

ACT_LABEL = {"retail": "개인", "foreign": "외국인", "inst": "기관합계", "securities": "금융투자", "insurance": "보험", "trust": "투신", "private_fund": "사모",
             "bank": "은행", "other_fin": "기타금융", "pension": "연기금등", "other": "기타법인", "gov": "국가·지자체", "foreign_other": "기타외국인"}
ACT_ORDER = ["retail", "foreign", "inst", "securities", "insurance", "trust", "private_fund", "bank", "other_fin", "pension", "other", "gov", "foreign_other"]
MAIN3 = ("retail", "foreign", "inst")
# 응답의 '…Value' 항목 이름 → 주체 키(모르는 이름은 x_이름 으로 저장)
VALUE_NAMES = {"personalValue": "retail", "foreignValue": "foreign", "institutionalValue": "inst", "investmentValue": "securities", "insuranceValue": "insurance",
            "trustValue": "trust", "privateFundValue": "private_fund", "bankValue": "bank", "etcFinanceValue": "other_fin", "pensionValue": "pension",
            "etcCorporationValue": "other", "nationValue": "gov"}
# 붙여 넣은 표의 이름(공백·괄호 제거 후 포함 여부) → 주체 키. 긴 이름부터 맞춘다.
PASTE_NAMES = [("기타금융", "other_fin"), ("금융투자", "securities"), ("기타법인", "other"), ("기타외국인", "foreign_other"), ("연기금", "pension"), ("기관합계", "inst"),
               ("기관계", "inst"), ("외국인합계", "foreign"), ("외국인", "foreign"), ("개인", "retail"), ("보험", "insurance"), ("투신", "trust"), ("사모", "private_fund"),
               ("은행", "bank"), ("국가", "gov"), ("지자체", "gov"), ("기관", "inst")]
UNITS = {"eok": 100000000.0, "mil": 1000000.0, "won": 1.0}


# ══════════════════════════════════════════════════════════════
# 표 · 작은 도구
# ══════════════════════════════════════════════════════════════
def _ensure_tables(cur, use_pg):
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    cur.execute(f"""CREATE TABLE IF NOT EXISTS market_flow_day(
        market TEXT NOT NULL, date TEXT NOT NULL, actor TEXT NOT NULL, src TEXT NOT NULL DEFAULT 'index', amount {real} DEFAULT 0,
        updated_at TEXT DEFAULT '', PRIMARY KEY(market,date,actor,src))""")


def _s(x, n=80):
    return re.sub(r"[\x00-\x1f]", "", str(x or "")).strip()[:n]


def _today():
    return _now_kst().strftime("%Y-%m-%d")


def _stamp():
    return _now_kst().strftime("%Y-%m-%d %H:%M:%S")


def _n(x):
    try:
        v = float(x)
        return 0 if v != v or v in (float("inf"), float("-inf")) else v
    except Exception:
        return 0


def _fl(x):
    try:
        v = float(x)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    except Exception:
        return None


def _date(s):
    d = re.sub(r"\D", "", str(s or ""))[:8]
    if len(d) < 8:
        return ""
    y, m, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
    if not (2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= dd <= 31):
        return ""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _try(*sqls):
    for q in sqls:
        try:
            return _dbx(q, (), fetch=True) or []
        except Exception:
            continue
    return None


def _iarg(name, lo, hi, default):
    try:
        v = int(str(request.args.get(name) or "").strip())
    except Exception:
        return default
    return max(lo, min(hi, v))


def _arg(name, allowed, default):
    v = (request.args.get(name) or "").strip()
    return v if v in allowed else default


def _eok(won):
    return round(float(won or 0) / 1e8, 1)


def _fmt_eok(v):
    """억원 값 → '+1,234억' / '-1.2조'."""
    v = float(v or 0)
    a = abs(v)
    s = "-" if v < 0 else ("+" if v > 0 else "")
    if a >= 10000:
        return "%s%.1f조" % (s, a / 10000)
    return "%s%s억" % (s, format(int(round(a)), ","))


def _pct(v, d=2):
    return "-" if v is None else "%+.*f%%" % (d, v)


def _json_get(key):
    try:
        v = setting_get(key, "")
        d = json.loads(v) if v else {}
        return d if isinstance(d, (dict, list)) else {}
    except Exception:
        return {}


def _json_put(key, d):
    try:
        setting_set(key, json.dumps(d, ensure_ascii=False))
    except Exception as e:
        print(f"[시장수급] 기록 저장 실패(무시): {e}")


# ══════════════════════════════════════════════════════════════
# DB — 일별 수급 읽기·쓰기
# ══════════════════════════════════════════════════════════════
def _conn():
    return C._pg_get() if C._USE_PG else C._history_conn()


def _run(ops):
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


def _save_day(mk, date, vals, src):
    """vals={주체: 원}. 같은 시장·날짜·주체·출처는 덮어쓴다."""
    ops, now = [], _stamp()
    for ac, am in vals.items():
        ops.append(("DELETE FROM market_flow_day WHERE market=? AND date=? AND actor=? AND src=?", (mk, date, ac, src)))
        ops.append(("INSERT INTO market_flow_day(market,date,actor,src,amount,updated_at) VALUES(?,?,?,?,?,?)", (mk, date, ac, src, float(am), now)))
    for k in range(0, len(ops), 300):
        _run(ops[k:k + 300])


def _rows(market, srcs):
    """{주체: {날짜: 원}} — srcs 순서대로 읽고, 같은 날짜·주체는 뒤쪽 출처가 앞쪽을 덮는다."""
    out = {}
    rows = _try("SELECT date,actor,amount,src FROM market_flow_day WHERE market='%s' ORDER BY date" % market.replace("'", "")) or []
    by_src = {s: [] for s in srcs}
    for d, a, v, s in rows:
        if s in by_src:
            by_src[s].append((str(d), str(a), float(v or 0)))
    for s in srcs:
        for d, a, v in by_src[s]:
            out.setdefault(a, {})[d] = v
    return out


def _counts():
    rows = _try("SELECT market,src,COUNT(*),MIN(date),MAX(date) FROM market_flow_day GROUP BY market,src") or []
    out = {}
    for mk, src, n, d0, d1 in rows:
        out.setdefault(str(src), {})[str(mk)] = {"rows": int(n), "from": str(d0), "to": str(d1)}
    return out


VIEWS = {"market": ("index", "paste"), "univ": ("univ",)}


def _views_available():
    c = _counts()
    out = []
    if c.get("index") or c.get("paste"):
        out.append("market")
    if c.get("univ"):
        out.append("univ")
    return out


def _pick_view(v):
    av = _views_available()
    if v in av:
        return v
    return av[0] if av else ""


# ══════════════════════════════════════════════════════════════
# 분석 — 주체별 기간 합계·연속일수·페이스·신호 문장
# ══════════════════════════════════════════════════════════════
def _order(keys):
    return [k for k in ACT_ORDER if k in keys] + sorted(k for k in keys if k not in ACT_ORDER)


def _label(k):
    if k in ACT_LABEL:
        return ACT_LABEL[k]
    return k[2:] if k.startswith("x_") else k


def _analyze_series(ser, days):
    """ser={주체:{날짜:원}} → 분석 한 덩어리(금액은 억원). 날짜가 없으면 None."""
    dates = sorted({d for a in ser.values() for d in a})[-days:]
    if not dates:
        return None
    keys = _order([k for k, v in ser.items() if any(d in v for d in dates)])
    nd = len(dates)
    pers = [n for n in (1, 5, 10, 20) if n <= nd]
    if nd not in pers:
        pers.append(nd)
    acts, cum = [], {}
    for k in keys:
        vals = [ser[k].get(d, 0.0) / 1e8 for d in dates]
        have = sum(1 for d in dates if d in ser[k])
        p = {str(n): round(sum(vals[-n:]), 1) for n in pers}
        st = 0
        for v in reversed(vals):
            if v > 0 and st >= 0:
                st += 1
            elif v < 0 and st <= 0:
                st -= 1
            else:
                break
        n5, n20 = min(5, nd), min(20, nd)
        acts.append({"key": k, "label": _label(k), "main": k in MAIN3, "p": p, "streak": st, "have": have,
                     "pace5": round(sum(vals[-n5:]) / n5, 1), "pace20": round(sum(vals[-n20:]) / n20, 1)})
        t, c = 0.0, []
        for v in vals:
            t += v
            c.append(round(t, 1))
        cum[k] = c
    tot1 = sum(abs(a["p"]["1"]) for a in acts if a["key"] in MAIN3) or 0
    for a in acts:
        a["share1"] = round(abs(a["p"]["1"]) * 100 / tot1) if (a["key"] in MAIN3 and tot1) else None
    hist = []
    for i, d in enumerate(dates):
        h = {"date": d}
        for k in keys:
            h[k] = round(ser[k].get(d, 0.0) / 1e8, 1)
        hist.append(h)
    return {"base_date": dates[-1], "days": nd, "dates": dates, "periods": pers, "actors": acts, "hist": hist, "cum": cum}


def _combine(sers):
    """코스피+코스닥 합계 — 주체·날짜별로 더한다."""
    out = {}
    for s in sers:
        for a, dv in s.items():
            for d, v in dv.items():
                out.setdefault(a, {})[d] = out.setdefault(a, {}).get(d, 0.0) + v
    return out


def _act(an, key):
    for a in (an or {}).get("actors") or []:
        if a["key"] == key:
            return a
    return None


def _verdict(ans):
    """외국인+기관 합산 5일 페이스와 20일 페이스 비교(원본과 같은 기준)."""
    p5 = p20 = 0.0
    any_ = False
    for an in ans:
        for k in ("foreign", "inst"):
            a = _act(an, k)
            if a:
                any_ = True
                p5 += a["pace5"]
                p20 += a["pace20"]
    if not any_:
        return None
    if p5 > 0 and p5 > p20:
        t, tone = "매수세 강화 중", "up"
    elif p5 > 0:
        t, tone = "매수 우위(다소 둔화)", "up"
    elif p5 <= 0 and p5 < p20:
        t, tone = "매도세 강화 중", "dn"
    else:
        t, tone = "매도 우위(다소 완화)", "dn"
    return {"text": t, "tone": tone, "pace5": round(p5, 1), "pace20": round(p20, 1)}


def _pp(an, a, n):
    """주체 a 의 n일 합계(자료가 n일보다 짧으면 가진 만큼의 합계)."""
    p = a["p"]
    return p.get(str(n), p[str(an["days"])])


def _streak_txt(st):
    return "" if not st else ("%d일 연속 순매수" % st if st > 0 else "%d일 연속 순매도" % (-st))


def _signals(name, an):
    """읽기 쉬운 신호 문장(초보자용). 같은 말을 반복하지 않도록 시장마다 몇 줄만."""
    out = []
    if not an:
        return out
    f, i, r = _act(an, "foreign"), _act(an, "inst"), _act(an, "retail")
    main = [a for a in (r, f, i) if a]
    if main:
        top = max(main, key=lambda a: a["p"]["1"])
        low = min(main, key=lambda a: a["p"]["1"])
        if top["p"]["1"] > 0:
            out.append("%s — 하루 기준 가장 많이 산 쪽은 %s(%s)" % (name, top["label"], _fmt_eok(top["p"]["1"])))
        if low["p"]["1"] < 0:
            out.append("%s — 하루 기준 가장 많이 판 쪽은 %s(%s)" % (name, low["label"], _fmt_eok(low["p"]["1"])))
    for a in main:
        if abs(a["streak"]) >= 3:
            out.append("%s — %s %s" % (name, a["label"], _streak_txt(a["streak"])))
    if f and i:
        k5 = (_pp(an, f, 5), _pp(an, i, 5))
        if k5[0] > 0 and k5[1] > 0:
            out.append("%s — 외국인·기관이 최근 5거래일 함께 순매수(쌍끌이)" % name)
        elif k5[0] < 0 and k5[1] < 0:
            out.append("%s — 외국인·기관이 최근 5거래일 함께 순매도(동반 매도)" % name)
        elif (k5[0] > 0) != (k5[1] > 0):
            out.append("%s — 외국인과 기관의 방향이 엇갈려요(5일: 외국인 %s · 기관 %s)" % (name, _fmt_eok(k5[0]), _fmt_eok(k5[1])))
    if r and f and i and _pp(an, r, 5) > 0 and (_pp(an, f, 5) + _pp(an, i, 5)) < 0:
        out.append("%s — 외국인·기관이 판 물량을 개인이 받아 내는 모양(5일)" % name)
    elif r and f and i and _pp(an, r, 5) < 0 and (_pp(an, f, 5) + _pp(an, i, 5)) > 0:
        out.append("%s — 개인이 판 물량을 외국인·기관이 받아 내는 모양(5일)" % name)
    if an["days"] >= 10:
        for a in (f, i):
            if a and _pp(an, a, 20) <= 0 and _pp(an, a, 5) > 0:
                out.append("%s — %s: 길게는 순매도였지만 최근 5일은 순매수로 돌아서는 모습" % (name, a["label"]))
            elif a and _pp(an, a, 20) >= 0 and _pp(an, a, 5) < 0:
                out.append("%s — %s: 길게는 순매수였지만 최근 5일은 순매도로 돌아서는 모습" % (name, a["label"]))
    detail = [a for a in an["actors"] if a["key"] not in MAIN3]
    if detail:
        top = max(detail, key=lambda a: a["p"]["1"])
        low = min(detail, key=lambda a: a["p"]["1"])
        if top["p"]["1"] > 0:
            out.append("%s — 세부 주체 중 가장 많이 산 쪽은 %s(%s)" % (name, top["label"], _fmt_eok(top["p"]["1"])))
        if low["p"]["1"] < 0:
            out.append("%s — 세부 주체 중 가장 많이 판 쪽은 %s(%s)" % (name, low["label"], _fmt_eok(low["p"]["1"])))
    return out[:9]


def _analysis(view, days):
    """{ok, view, base_date, markets:{KOSPI,KOSDAQ,ALL}, verdict, signals}"""
    srcs = VIEWS.get(view)
    if not srcs:
        return None
    sers = {mk: _rows(mk, srcs) for mk in MARKETS}
    sers = {mk: s for mk, s in sers.items() if s}
    if not sers:
        return None
    mk_an = {}
    for mk, s in sers.items():
        a = _analyze_series(s, days)
        if a:
            mk_an[mk] = a
    if not mk_an:
        return None
    if len(mk_an) == 2:
        both = _analyze_series(_combine([sers[m] for m in MARKETS]), days)
        if both:
            mk_an["ALL"] = both
    ver = _verdict([a for k, a in mk_an.items() if k in MARKETS])
    sig = []
    for mk in MARKETS:
        sig += _signals(MK_NAME[mk], mk_an.get(mk))
    base = max(a["base_date"] for a in mk_an.values())
    return {"ok": True, "view": view, "base_date": base, "days": max(a["days"] for a in mk_an.values()), "markets": mk_an, "verdict": ver, "signals": sig}


def _slim(an, full):
    """공개 요약에는 주요 3주체와 기간 합계만(그래프용 이력·세부 주체는 별도 기능)."""
    out = {k: v for k, v in an.items() if k != "markets"}
    out["markets"] = {}
    for mk, m in an["markets"].items():
        mm = {k: v for k, v in m.items() if k not in ("hist", "cum", "dates")}
        if not full:
            mm["actors"] = [a for a in m["actors"] if a["key"] in MAIN3]
        out["markets"][mk] = mm
    if not full:
        out["signals"] = [s for s in an["signals"] if "세부 주체" not in s]
    return out


# ══════════════════════════════════════════════════════════════
# 종목별 상위 — investor_scan_cache(수집한 종목의 1·5·20일 합계)
# ══════════════════════════════════════════════════════════════
def _stock_rows():
    q1 = ("SELECT i.ticker,i.name,i.foreign_1,i.inst_1,i.foreign_5,i.inst_5,i.foreign_20,i.inst_20,i.retail_1,i.retail_5,i.retail_20,i.base_date,p.market,p.price,p.day_pct "
          "FROM investor_scan_cache i LEFT JOIN stock_price_cache p ON p.ticker=i.ticker")
    q2 = ("SELECT i.ticker,i.name,i.foreign_1,i.inst_1,i.foreign_5,i.inst_5,i.foreign_20,i.inst_20,0,0,0,i.base_date,p.market,p.price,p.day_pct "
          "FROM investor_scan_cache i LEFT JOIN stock_price_cache p ON p.ticker=i.ticker")
    q3 = ("SELECT i.ticker,i.name,i.foreign_1,i.inst_1,i.foreign_5,i.inst_5,i.foreign_20,i.inst_20,0,0,0,'','',0,NULL FROM investor_scan_cache i")
    got = _try(q1, q2, q3)
    if got is None:
        return None, 0
    cut = (_now_kst().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    out, has_retail = [], False
    for x in got:
        t = str(x[0] or "").strip().upper()
        if not TICKER_RE.match(t):
            continue
        base = _date(x[11])
        if base and base < cut:
            continue
        v = [_n(x[k]) for k in range(2, 11)]
        if any(v[6:9]):
            has_retail = True
        mk = str(x[12] or "").upper()
        out.append({"ticker": t, "name": str(x[1] or t)[:40], "market": mk if mk in MARKETS else "", "price": int(_n(x[13])) or None, "pct": _fl(x[14]),
                    "f": {"1": v[0], "5": v[2], "20": v[4]}, "i": {"1": v[1], "5": v[3], "20": v[5]}, "r": {"1": v[6], "5": v[7], "20": v[8]}, "base": base})
    return out, has_retail


def _stock_top(actor, per, side, market, top):
    rows, has_retail = _stock_rows()
    if rows is None:
        return None, False
    if market in MARKETS:
        rows = [r for r in rows if r["market"] == market]

    def val(r):
        if actor == "comb":
            return r["f"][per] + r["i"][per]
        if actor == "dual":
            return (r["f"][per] + r["i"][per]) if (r["f"][per] > 0 and r["i"][per] > 0) else None
        return r[{"foreign": "f", "inst": "i", "retail": "r"}[actor]][per]
    cand = [(val(r), r) for r in rows]
    cand = [(v, r) for v, r in cand if v is not None and v != 0]
    if actor == "dual":
        side = "buy"
    cand = [(v, r) for v, r in cand if (v > 0 if side == "buy" else v < 0)]
    cand.sort(key=lambda t: -t[0] if side == "buy" else t[0])
    items = [{"ticker": r["ticker"], "name": r["name"], "market": r["market"], "price": r["price"], "pct": r["pct"], "amount": _eok(v),
              "f": _eok(r["f"][per]), "i": _eok(r["i"][per]), "r": _eok(r["r"][per]), "base": r["base"]} for v, r in cand[:top]]
    return {"items": items, "total": len(rows), "match": len(cand)}, has_retail


def _themes_extra():
    got = _try("SELECT no,name,total,change_rate,rise,fall,steady FROM collect_theme_list ORDER BY change_rate DESC")
    if not got:
        return None
    its = [{"no": int(x[0] or 0), "name": str(x[1] or "")[:40], "total": int(x[2] or 0), "rate": round(_n(x[3]), 2), "rise": int(x[4] or 0), "fall": int(x[5] or 0)} for x in got]
    return {"top": its[:8], "bottom": [t for t in reversed(its[-5:]) if t["rate"] < 0][:5], "count": len(its)}


# ══════════════════════════════════════════════════════════════
# 네이버에서 받기 — 한 곳으로 모아 둠(시험에서는 이 함수만 바꿔 끼운다)
# ══════════════════════════════════════════════════════════════
def _http_json(path, params=None):
    last = None
    for _ in range(2):
        try:
            r = C._RAW_HTTP.get(BASE + path, params=params, timeout=(5, 10), headers=dict(C.NAVER_M_HEADERS), _redirects=0)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError("HTTP %s" % r.status_code)
        except Exception as e:
            last = e
        time.sleep(0.3)
    raise last or RuntimeError("요청 실패")


def _num(v):
    try:
        t = str(v).replace(",", "").replace("+", "").strip()
        return float(t) if t not in ("", "-", "None") else None
    except Exception:
        return None


def _fetch_idx_trend(mk, bizdate=None):
    """시장 전체 투자자별 순매수 하루치 → {'date','vals':{주체: 원}} 또는 None. 억원 단위로 받아 원으로 바꾼다."""
    try:
        j = _http_json("/api/index/%s/trend" % mk, {"bizdate": bizdate} if bizdate else None)
    except Exception:
        return None
    if not isinstance(j, dict):
        return None
    d = _date(j.get("bizdate"))
    if not d:
        return None
    vals = {}
    for k, v in j.items():
        if not str(k).endswith("Value"):
            continue
        x = _num(v)
        if x is None:
            continue
        ac = VALUE_NAMES.get(k) or ("x_" + str(k)[:-5][:24])
        vals[ac] = x * 1e8
    return {"date": d, "vals": vals} if vals else None


def _fetch_idx_basic(mk):
    try:
        j = _http_json("/api/index/%s/basic" % mk)
    except Exception:
        return None
    if not isinstance(j, dict):
        return None
    px = _num(j.get("closePrice"))
    if px is None:
        return None
    return {"price": px, "pct": _num(j.get("fluctuationsRatio")), "diff": _num(j.get("compareToPreviousClosePrice")), "at": str(j.get("localTradedAt") or "")[:10]}


_MP = {}


def _mkprog(mk, have, want):
    """시장별로 쌓은 날짜 수를 합쳐 ‘수급 받기’ 진행률(진행률 장부)에 적는다."""
    try:
        _MP[mk] = min(have, want)
        C.prog_item("market/fetch", sum(_MP.values()), want * len(MARKETS), f"{sum(_MP.values())}/{want * len(MARKETS)}일치 받음")
    except Exception:
        pass


def _collect_market(mk, want):
    """오늘 값을 받고, 과거 날짜(bizdate)가 되는 만큼 거슬러 올라가 채운다. 이미 쌓인 날짜는 건너뛴다."""
    t0 = time.time()
    have = set(_rows(mk, ("index",)).get("retail", {}).keys())
    t = _fetch_idx_trend(mk)
    if not t:
        return {"ok": False, "error": "%s 수급을 받지 못했어요(네이버 응답 없음 또는 주소 변경)" % MK_NAME[mk]}
    _save_day(mk, t["date"], t["vals"], "index")
    added = 0 if t["date"] in have else 1
    have.add(t["date"])
    _mkprog(mk, len(have), want)
    cur = datetime.strptime(t["date"], "%Y-%m-%d")
    misses = tries = 0
    while len(have) < want and misses < 3 and tries < want + 8 and time.time() - t0 < 45:
        cur -= timedelta(days=1)
        if cur.weekday() >= 5:
            continue
        ds = cur.strftime("%Y-%m-%d")
        if ds in have:
            continue
        tries += 1
        r = _fetch_idx_trend(mk, cur.strftime("%Y%m%d"))
        if r and r["date"] == ds:
            _save_day(mk, ds, r["vals"], "index")
            have.add(ds)
            added += 1
            misses = 0
            _mkprog(mk, len(have), want)
        else:
            misses += 1
    return {"ok": True, "latest": t["date"], "added": added, "total": len(have), "actors": sorted(t["vals"]), "backfill": added > (0 if t["date"] in have else 1)}


_LOCK = threading.Lock()


@bp.route("/admin/api/market/fetch", methods=["POST"])
def api_fetch():
    """관리자 전용 — 네이버에서 시장 전체 수급(코스피·코스닥)을 받아 날짜별로 쌓는다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if not _LOCK.acquire(blocking=False):
        return _admin_json({"ok": False, "error": "이미 가져오는 중이에요. 잠시 뒤 다시 눌러 주세요."})
    try:
        b = _json_body() or {}
        want = max(5, min(60, int(_n(b.get("days")) or 20)))
        _MP.clear()
        C.prog_begin("market/fetch", "시장수급 가져오기", [("코스피·코스닥 수급 받기", 85), ("지수 정보", 10), ("저장", 5)])
        with ThreadPoolExecutor(max_workers=2) as ex:
            res = dict(zip(MARKETS, ex.map(lambda m: _collect_market(m, want), MARKETS)))
        C.prog_stage("market/fetch", 1, "지수 기본 정보 조회 중")
        idx = {}
        for mk in MARKETS:
            x = _fetch_idx_basic(mk)
            if x:
                idx[mk] = x
        if idx:
            _json_put(KEY_IDX, dict(idx, at=_stamp()))
        C.prog_stage("market/fetch", 2, "저장 중")
        okn = sum(1 for r in res.values() if r.get("ok"))
        info = {"at": _stamp(), "res": res, "ok": okn, "want": want}
        _json_put(KEY_LAST, info)
        _alog("market_fetch", "ok=%d/%d" % (okn, len(MARKETS)))
        C.prog_end("market/fetch", okn > 0, "완료" if okn else "실패")
        return _admin_json({"ok": okn > 0, "res": res, "at": info["at"], "error": "" if okn else "두 시장 모두 받지 못했어요. 잠시 뒤 다시 시도해 주세요(네이버 응답 없음·주소 변경 가능)."})
    finally:
        _LOCK.release()


# ══════════════════════════════════════════════════════════════
# 세부 주체 붙여넣기 — KRX·증권사 표를 읽어 src='paste' 로 저장
# ══════════════════════════════════════════════════════════════
def _paste_key(name):
    t = re.sub(r"[\s()（）\[\]·.,]", "", str(name or ""))
    for kw, k in PASTE_NAMES:
        if kw in t:
            return k
    return None


def _split_line(ln):
    if "\t" in ln:
        return [c.strip() for c in ln.split("\t")]
    if '"' in ln and "," in ln:
        import csv
        try:
            return [c.strip() for c in next(csv.reader([ln]))]
        except Exception:
            pass
    if "," in ln and not re.search(r"\d,\d{3}(?!\d)", ln):
        return [c.strip() for c in ln.split(",")]
    if re.search(r"\s{2,}", ln.strip()):
        return [c.strip() for c in re.split(r"\s{2,}", ln.strip())]
    return ln.split()


def _pnum(c):
    """표 칸의 숫자 읽기 — 쉼표·+·△▲▼ 는 허용하고, 숫자 이외 글자가 섞이면 값으로 보지 않는다."""
    t = str(c or "").strip().replace(",", "").replace(" ", "").replace("+", "").replace("△", "-").replace("▲", "").replace("▼", "-")
    if not re.match(r"^-?\d+(\.\d+)?$", t):
        return None
    try:
        return float(t)
    except Exception:
        return None


def _parse_paste(text, date, unit):
    """붙여 넣은 표 → ({(날짜, 주체): 원}, 읽지 못한 이름, 오류). 두 가지 모양을 읽는다.
       ① 가로형: 날짜 | 개인 | 외국인 | 금융투자 … (날짜마다 한 줄)  ② 세로형(KRX 투자자별 거래실적): 투자자구분 | 매도 | 매수 | 순매수 (주체마다 한 줄, 날짜는 따로)"""
    mult = UNITS.get(unit, 1e8)
    lines = [ln for ln in str(text or "").replace("\r", "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return {}, [], "표가 너무 짧아요. 머리글 줄과 값 줄을 함께 붙여 넣어 주세요."
    rows = [_split_line(ln) for ln in lines[:400]]
    head = rows[0]
    out, unknown = {}, []
    h0 = re.sub(r"\s", "", head[0]).lower() if head else ""
    if h0 in ("날짜", "일자", "date", "기간", "거래일") or _date(head[0]) and len(head) > 2 and all(_paste_key(c) for c in head[1:] if c):
        names = head[1:]
        keys = []
        for nm in names:
            k = _paste_key(nm)
            keys.append(k)
            if not k and nm and nm not in unknown and not re.search(r"합계|계$|전체|^$", nm):
                unknown.append(_s(re.sub(r"[<>&\"']", "", nm), 20))
        for r in rows[1:]:
            d = _date(r[0].replace(".", "").replace("/", "").replace("-", "")) if r else ""
            if not d and r:
                m = re.match(r"^(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})", r[0])
                if m:
                    y, mo, dd = m.groups()
                    d = "%s-%02d-%02d" % (("20" + y) if len(y) == 2 else y, int(mo), int(dd))
            if not d:
                continue
            for k, c in zip(keys, r[1:]):
                v = _pnum(c)
                if k and v is not None:
                    out[(d, k)] = v * mult
        if not out:
            return {}, unknown, "날짜와 주체 이름(개인·외국인·금융투자 …)이 있는 표로 읽지 못했어요."
        return out, unknown, ""
    # 세로형
    col = None
    for ci, c in enumerate(head):
        if "순매수" in re.sub(r"\s", "", c):
            col = ci
    if col is None:
        return {}, [], "머리글에 ‘날짜’ 또는 ‘순매수’ 열이 있어야 해요."
    d = _date(date) or _today()
    for r in rows[1:]:
        if len(r) <= col:
            continue
        k = _paste_key(r[0])
        v = _pnum(r[col])
        if k and v is not None:
            out[(d, k)] = v * mult
        elif r[0] and not re.search(r"합계|전체|^$", r[0]) and r[0] not in unknown:
            unknown.append(_s(re.sub(r"[<>&\"']", "", r[0]), 20))
    if not out:
        return {}, unknown, "주체 이름(개인·외국인·기관합계·금융투자 …)을 읽지 못했어요."
    return out, unknown, ""


@bp.route("/admin/api/market/paste", methods=["POST"])
def api_paste():
    """관리자 전용 — KRX·증권사 표(세부 주체)를 붙여 넣어 저장한다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    mk = str(b.get("market") or "").upper()
    if mk not in MARKETS:
        return _admin_json({"error": "시장(코스피·코스닥)을 골라 주세요."}, 400)
    unit = str(b.get("unit") or "eok")
    if unit not in UNITS:
        return _admin_json({"error": "단위(억원·백만원·원)를 골라 주세요."}, 400)
    data, unknown, err = _parse_paste(str(b.get("text") or "")[:60000], b.get("date"), unit)
    if err:
        return _admin_json({"error": err, "unknown": unknown[:10]}, 400)
    by = {}
    for (d, k), v in data.items():
        by.setdefault(d, {})[k] = v
    for d, vals in by.items():
        _save_day(mk, d, vals, "paste")
    _alog("market_paste", "%s days=%d actors=%d" % (mk, len(by), len({k for (_d, k) in data})))
    return _admin_json({"ok": True, "market": mk, "days": len(by), "dates": sorted(by)[-3:], "actors": [_label(k) for k in _order({k for (_d, k) in data})], "unknown": unknown[:10]})


@bp.route("/admin/api/market/delete", methods=["POST"])
def api_delete():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    src = str((_json_body() or {}).get("src") or "")
    if src not in ("index", "univ", "paste"):
        return _admin_json({"error": "지울 자료를 골라 주세요."}, 400)
    _run([("DELETE FROM market_flow_day WHERE src=?", (src,))])
    _alog("market_delete", src)
    return _admin_json({"ok": True})


# ══════════════════════════════════════════════════════════════
# 읽기 API (기능별 등급으로 회원에게 열림)
# ══════════════════════════════════════════════════════════════
def _empty():
    return _admin_json({"ok": True, "empty": True,
                        "msg": "시장수급 자료가 아직 없어요. 관리자가 [📥 시장 수급 가져오기]를 누르면 코스피·코스닥 수급이 쌓이기 시작해요.",
                        "need": ["market_flow_day"]})


def _get_analysis():
    view = _pick_view(_arg("view", ("market", "univ"), "market"))
    if not view:
        return None, None
    an = _analysis(view, _iarg("days", 1, 60, 20))
    return view, an


@bp.route("/admin/api/market/summary", methods=["GET"])
def api_summary():
    deny = _admin_deny()
    if deny:
        return deny
    view, an = _get_analysis()
    if not an:
        return _empty()
    out = _slim(an, False)
    out["views"] = _views_available()
    out["idx"] = {k: v for k, v in _json_get(KEY_IDX).items() if k in MARKETS} if isinstance(_json_get(KEY_IDX), dict) else {}
    return _admin_json(out)


@bp.route("/admin/api/market/detail", methods=["GET"])
def api_detail():
    deny = _admin_deny()
    if deny:
        return deny
    view, an = _get_analysis()
    if not an:
        return _empty()
    out = _slim(an, True)
    out["views"] = _views_available()
    return _admin_json(out)


@bp.route("/admin/api/market/history", methods=["GET"])
def api_history():
    deny = _admin_deny()
    if deny:
        return deny
    view, an = _get_analysis()
    if not an:
        return _empty()
    out = {"ok": True, "view": view, "base_date": an["base_date"], "markets": {}}
    for mk, m in an["markets"].items():
        out["markets"][mk] = {"dates": m["dates"], "hist": m["hist"], "cum": m["cum"], "actors": [{"key": a["key"], "label": a["label"], "main": a["main"]} for a in m["actors"]]}
    return _admin_json(out)


@bp.route("/admin/api/market/stocks", methods=["GET"])
def api_stocks():
    deny = _admin_deny()
    if deny:
        return deny
    actor = _arg("actor", ("foreign", "inst", "retail", "comb", "dual"), "foreign")
    per = _arg("per", ("1", "5", "20"), "5")
    side = _arg("side", ("buy", "sell"), "buy")
    mk = _arg("market", ("all", "KOSPI", "KOSDAQ"), "all")
    res, has_retail = _stock_top(actor, per, side, mk, _iarg("top", 5, 30, 15))
    if res is None or not res["total"]:
        return _admin_json({"ok": True, "empty": True, "msg": "종목별 수급 자료가 없어요. 관리자가 [📥 종목 수급 가져오기]를 실행하면 순위가 생겨요."})
    res.update({"ok": True, "actor": actor, "per": per, "side": side, "market": mk, "has_retail": has_retail})
    return _admin_json(res)


@bp.route("/admin/api/market/extra", methods=["GET"])
def api_extra():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json({"ok": True, "themes": _themes_extra(), "idx": {k: v for k, v in _json_get(KEY_IDX).items() if k in MARKETS} if isinstance(_json_get(KEY_IDX), dict) else {}})


# ══════════════════════════════════════════════════════════════
# AI 프롬프트(수동 — 서버가 AI를 부르지 않는다) · AI 저장 · 블로그 글
# ══════════════════════════════════════════════════════════════
MK_DEFAULT = """당신은 한국 주식시장 수급을 쉽게 풀어 쓰는 분석가입니다. 아래는 {period_str} 기준 코스피·코스닥의 투자자별 순매수 데이터입니다(금액은 억원, +는 순매수, -는 순매도).

[기준일: {base_date} / 작성일: {today}]
{summary}

[작성 지침 — 반드시 준수]
- 국내 주식 초보 투자자를 위한 정보 정리 글입니다. 위 데이터에 없는 숫자나 사실은 지어내지 마세요.
- 특정 종목·업종의 매수·매도를 권하거나 지수·주가를 단정하지 말고, "~로 보입니다", "~할 가능성이 있습니다" 같은 관찰 표현을 쓰세요.
- 마크다운으로 작성하세요. 최상위 섹션은 '## 제목', 하위 항목은 '### 제목', 강조는 **굵게**, 목록은 '- '을 사용합니다. <br> 같은 HTML 태그는 쓰지 마세요.
- 수치는 반드시 억원(1조 이상은 조) 단위로 구체적으로 쓰고, 순매수·순매도가 무슨 뜻인지 한 번은 쉬운 말로 설명하세요.
- 자료에 없는 주체(예: 거래원)는 언급하지 마세요.

[구성 — 순서대로 작성]
## 📊 오늘 수급 한 줄 요약
- 가장 많이 산 주체와 판 주체, 코스피·코스닥의 온도 차이를 3줄 이내로 요약하세요.

## 🔍 주체별로 보면
### 외국인
- 1일·5일·20일 방향과 연속 일수, 글로벌 자금 흐름으로 해석할 수 있는 부분(단정 금지)
### 기관
- 기관합계와, 세부 기관(금융투자·투신·연기금 등)이 자료에 있으면 그 움직임
### 개인
- 개인이 외국인·기관과 같은 편인지 반대편인지, 그 의미

## ⚖ 코스피 vs 코스닥
- 대형주 시장과 중소형주 시장의 자금 흐름이 어떻게 다른지

## 🏷 종목·테마로 이어서 보기
- 아래 자료에 종목·테마 순위가 있으면 눈에 띄는 것 2~3개만 사실 위주로 언급하세요(없으면 이 섹션은 생략).

## ⚠ 유의사항
이 글은 공개된 수급 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다. 수급은 결과일 뿐 이후 주가를 보장하지 않습니다. 투자 판단과 책임은 투자자 본인에게 있습니다.

[블로그 제목 후보]
- 위 내용을 블로그에 올릴 때 쓸 제목 3개를 한 줄씩 '- '로 쓰세요. 수급 사실 중심으로 쓰고, 매수 권유·수익 보장·"폭등" 같은 표현은 쓰지 마세요.
"""


def _summary_text(an, st, th, idx):
    lines = []
    for mk in MARKETS:
        m = an["markets"].get(mk)
        if not m:
            continue
        lines.append("=== %s (기준일 %s, 자료 %d거래일) ===" % (MK_NAME[mk], m["base_date"], m["days"]))
        ix = (idx or {}).get(mk)
        if ix:
            lines.append("  지수 %s (%s)" % (format(ix["price"], ",.2f"), _pct(ix.get("pct"))))
        for a in m["actors"]:
            ps = " · ".join("%s일 %s" % (n, _fmt_eok(a["p"][str(n)])) for n in m["periods"])
            lines.append("  %s: %s%s" % (a["label"], ps, (" | " + _streak_txt(a["streak"])) if abs(a["streak"]) >= 2 else ""))
        lines.append("")
    if an.get("verdict"):
        v = an["verdict"]
        lines.append("[종합] 외국인+기관 일평균 순매수: 최근 5일 %s, 20일 평균 %s → %s" % (_fmt_eok(v["pace5"]), _fmt_eok(v["pace20"]), v["text"]))
        lines.append("")
    for k, t in (("foreign", "외국인"), ("inst", "기관")):
        for side, sl in (("buy", "순매수"), ("sell", "순매도")):
            r = (st or {}).get((k, side))
            if r and r["items"]:
                lines.append("[%s %s 상위(5일, 수집 종목 기준)] %s" % (t, sl, ", ".join("%s %s" % (x["name"], _fmt_eok(x["amount"])) for x in r["items"][:5])))
    if th and th.get("top"):
        lines.append("[강세 테마(네이버)] " + ", ".join("%s %s" % (x["name"], _pct(x["rate"])) for x in th["top"][:5]))
    return "\n".join(lines).strip()


def _gather(view, days):
    an = _analysis(view, days)
    if not an:
        return None, None, None, None
    st = {}
    for k in ("foreign", "inst"):
        for side in ("buy", "sell"):
            res, _hr = _stock_top(k, "5", side, "all", 8)
            st[(k, side)] = res
    return an, st, _themes_extra(), (_json_get(KEY_IDX) if isinstance(_json_get(KEY_IDX), dict) else {})


@bp.route("/admin/api/market/prompt", methods=["GET"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
    view = _pick_view(_arg("view", ("market", "univ"), "market"))
    if not view:
        return _empty()
    days = _iarg("days", 1, 60, 20)
    an, st, th, idx = _gather(view, days)
    if not an:
        return _empty()
    summary = _summary_text(an, st, th, idx)
    body = prompt_get("market_ai") or MK_DEFAULT
    for k, v in (("{summary}", summary), ("{period_str}", "최근 %d거래일" % an["days"]), ("{base_date}", an["base_date"]), ("{today}", _today())):
        body = body.replace(k, v)
    label = "%s 수급 %s" % ("시장 전체" if view == "market" else "수집 종목 합산", an["base_date"])
    return _admin_json({"ok": True, "prompt": body, "label": label, "base_date": an["base_date"]})


def _ai_get():
    d = _json_get(KEY_AI)
    return d if isinstance(d, dict) else {}


@bp.route("/admin/api/market/ai", methods=["GET"])
def api_ai_get():
    deny = _admin_deny()
    if deny:
        return deny
    d = _ai_get()
    text = str(d.get("text") or "")
    if not text.strip():
        return _admin_json({"ok": True, "found": False})
    day = str(d.get("date") or "")
    return _admin_json({"ok": True, "found": True, "text": text, "label": str(d.get("label") or ""), "date": day, "at": str(d.get("at") or ""), "stale": day != _today()})


@bp.route("/admin/api/market/ai", methods=["POST"])
def api_ai_save():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    text = str(b.get("text") or "").replace("\x00", "").strip()[:20000]
    if len(text) < 100:
        return _admin_json({"error": "AI 답변(100자 이상)이 필요해요."}, 400)
    now = _now_kst()
    rec = {"date": now.strftime("%Y-%m-%d"), "at": now.strftime("%Y-%m-%d %H:%M:%S"), "label": _s(b.get("label"), 80), "text": text}
    _json_put(KEY_AI, rec)
    _alog("market_ai_save", "len=%d" % len(text))
    return _admin_json({"ok": True, "date": rec["date"], "at": rec["at"], "len": len(text)})


_TITLE_BLOCK = re.compile(r"^[ \t]*\[블로그\s*제목\s*후보[^\]]*\][ \t]*\n(?:[ \t]*(?:[-•*·]|\d+[.)])[ \t]*.+\n?)*", re.M)


def _split_ai(text):
    text = str(text or "").replace("\r", "")
    return _TITLE_BLOCK.sub("", text).strip(), B.extract_titles(text)


def _td(txt, w, align="right", color="#111827", bold=False, extra=""):
    return ('<td width="%d%%" align="%s" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:12.5px;%scolor:%s;white-space:nowrap;%s">%s</td>'
            % (w, align, "font-weight:800;" if bold else "", color, extra, txt))


def _vcell(v, w, bold=False):
    return _td(_fmt_eok(v), w, "right", B.updown(v), bold)


def _blog_build(an, st, th, idx, ai_text, inc, title):
    E = B.E
    today = _now_kst().strftime("%Y-%m-%d")
    base = an["base_date"]
    ai_body, titles = _split_ai(ai_text) if (ai_text or "").strip() else ("", [])
    ver = an.get("verdict")
    allm = an["markets"].get("ALL") or next(iter(an["markets"].values()))
    f_all, i_all, r_all = _act(allm, "foreign"), _act(allm, "inst"), _act(allm, "retail")
    lead = ""
    if f_all and i_all:
        lead = "외국인 %s · 기관 %s" % (_fmt_eok(f_all["p"]["1"]), _fmt_eok(i_all["p"]["1"]))
    auto_title = "📊 %s 코스피·코스닥 수급 | 외국인·기관·개인 순매수%s" % (base, (" — " + lead) if lead else "")
    title = title or (titles[0] if titles else auto_title)
    names = []
    for k in st or {}:
        for x in ((st[k] or {}).get("items") or [])[:3]:
            if x["name"] not in names:
                names.append(x["name"])
    tags, tag_html = B.hashtags(names[:10], today, extra=["시장수급", "코스피수급", "코스닥수급", "외국인순매수", "기관순매수", "개인순매수", "투자자별매매동향"])
    h = [B.seo_box(auto_title, "%s 기준 코스피·코스닥 투자자별(개인·외국인·기관) 순매수와 최근 흐름을 정리했어요. 매수 추천이 아닌 참고 정보예요." % base,
                   ["시장수급", "외국인 순매수", "기관 순매수", "개인 순매수", "투자자별 매매동향", "코스피 수급", "코스닥 수급"]),
         B.head_box("★ MARKET FLOW · %s" % base, '오늘의 <span style="color:%s;">시장 수급</span> 한눈에' % B.GOLD, "코스피·코스닥 투자자별 순매수 · 기준일 %s · 자료 %d거래일" % (E(base), an["days"]))]
    if inc.get("stats"):
        def tile(label, val, color, w):
            return ('<td width="%d%%" align="center" style="padding:11px 4px;background-color:#f8faff;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;margin-bottom:3px;">%s</div>'
                    '<div style="font-size:17px;font-weight:900;color:%s;">%s</div></td>' % (w, label, color, val))
        cells = ""
        if ver:
            cells += tile("외국인+기관 흐름", ver["text"], "#dc2626" if ver["tone"] == "up" else "#2563eb", 25)
        for a, w in ((r_all, 25), (f_all, 25), (i_all, 25)):
            if a:
                cells += tile("%s 1일" % a["label"], _fmt_eok(a["p"]["1"]), B.updown(a["p"]["1"]), w)
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;margin:14px 0 4px;' + B.FONT + '"><tr>' + cells + "</tr></table>")
        h.append('<p style="font-size:11.5px;color:#9ca3af;margin:4px 0 10px;">%s 합계 기준 · 빨강 +는 순매수, 파랑 −는 순매도예요.</p>' % MK_NAME["ALL"])
        sg = an.get("signals") or []
        if sg:
            h.append(B.side_title("&#128161; 오늘의 수급 포인트", "#d97706") + '<div style="font-size:13.5px;color:#334155;line-height:2.0;">' + "".join("&#9642; %s<br>" % E(s) for s in sg[:8]) + "</div>")
    if inc.get("actors"):
        for mk in ("KOSPI", "KOSDAQ"):
            m = an["markets"].get(mk)
            if not m:
                continue
            pers = [p for p in m["periods"] if p in (1, 5, 10, 20)] or [m["periods"][-1]]
            pers = pers[:4]
            wcol = int(54 / max(1, len(pers)))
            head = ('<th width="22%%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;text-align:left;">주체</th>'
                    + "".join('<th width="%d%%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">%d일</th>' % (wcol, p) for p in pers)
                    + '<th width="%d%%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">연속</th>' % (100 - 22 - wcol * len(pers)))
            trs = ""
            for a in m["actors"]:
                strk = _streak_txt(a["streak"]) if abs(a["streak"]) >= 2 else "-"
                trs += ('<tr><td width="22%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:%s;color:#111827;white-space:nowrap;">%s</td>' % ("800" if a["main"] else "600", E(a["label"]))
                        + "".join(_vcell(a["p"][str(p)], wcol, a["main"]) for p in pers)
                        + _td(strk.replace("연속 ", "·"), 100 - 22 - wcol * len(pers), "center", "#64748b"))
                trs += "</tr>"
            ix = (idx or {}).get(mk)
            sub = " · 지수 %s (%s)" % (format(ix["price"], ",.2f"), _pct(ix.get("pct"))) if ix else ""
            h.append(B.side_title("&#128202; %s 투자자별 순매수%s" % (MK_NAME[mk], E(sub)), "#1e40af" if mk == "KOSPI" else "#0f766e")
                     + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '"><tr>' + head + "</tr>" + trs + "</table>")
    if inc.get("flow"):
        for mk in ("KOSPI", "KOSDAQ"):
            m = an["markets"].get(mk)
            if not m or m["days"] < 2:
                continue
            cols = [a for a in m["actors"] if a["key"] in MAIN3 or a["key"] in ("securities", "trust", "pension")][:5]
            wc = int(76 / max(1, len(cols)))
            head = ('<th width="24%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;text-align:left;">날짜</th>'
                    + "".join('<th width="%d%%" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">%s</th>' % (wc, E(a["label"])) for a in cols))
            trs = ""
            for hrow in list(reversed(m["hist"]))[:10]:
                trs += ('<tr><td width="24%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:12.5px;color:#374151;white-space:nowrap;">%s</td>' % E(hrow["date"][5:].replace("-", "."))
                        + "".join(_vcell(hrow.get(a["key"], 0), wc) for a in cols) + "</tr>")
            h.append(B.side_title("&#128197; %s 최근 일별 흐름" % MK_NAME[mk], "#4f46e5") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '"><tr>' + head + "</tr>" + trs + "</table>")
    if inc.get("stocks") and st:
        blocks = ""
        for k, lab in (("foreign", "외국인"), ("inst", "기관")):
            for side, sl, colr in (("buy", "순매수", "#c62828"), ("sell", "순매도", "#1565c0")):
                r = st.get((k, side))
                if not r or not r["items"]:
                    continue
                trs = "".join('<tr><td width="12%%" align="center" style="padding:6px 2px;border-bottom:1px solid #eef2f7;font-size:12px;color:#64748b;">%d</td>'
                              '<td width="50%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;color:#111827;">%s</td>%s%s</tr>'
                              % (n, B.nlink(x["ticker"], E(x["name"])), _vcell(x["amount"], 22, True),
                                 _td(_pct(x["pct"]) if x.get("pct") is not None else "-", 16, "right", B.updown(x.get("pct") or 0)))
                              for n, x in enumerate(r["items"][:7], 1))
                blocks += (B.side_title("&#127942; %s %s 상위 (최근 5일)" % (lab, sl), colr)
                           + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '">' + trs + "</table>")
        if blocks:
            h.append(blocks)
            h.append('<p style="font-size:11.5px;color:#9ca3af;margin:6px 0 0;">종목별 수급은 시가총액 상위 일부 종목의 &lsquo;순매수 수량×종가&rsquo; 추정치이고, 오른쪽은 당일 등락률이에요.</p>')
    if inc.get("themes") and th and th.get("top"):
        trs = "".join('<tr><td width="56%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:700;color:#111827;">%s</td>%s%s</tr>'
                      % (E(x["name"]), _td(_pct(x["rate"]), 22, "right", B.updown(x["rate"]), True), _td("&#9650;%d &#9660;%d" % (x["rise"], x["fall"]), 22, "right", "#64748b"))
                      for x in th["top"][:6])
        h.append(B.side_title("&#128293; 오늘 강세 테마 (네이버)", "#c2410c") + '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '">' + trs + "</table>")
    if inc.get("ai") and ai_body:
        pairs = []
        for k in st or {}:
            for x in ((st[k] or {}).get("items") or []):
                pairs.append((x["name"], x["ticker"]))
        h.append(B.side_title("&#129302; AI 수급 해설", "#0d1b3e"))
        h.append(B.link_names(B.ai_to_html(ai_body), pairs))
    h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border:2px solid #d97706;border-collapse:collapse;margin:14px 0 4px;' + B.FONT + '"><tr><td bgcolor="#fffbeb" style="background-color:#fffbeb;padding:12px 16px;">'
             '<div style="font-size:13px;font-weight:900;color:#92400e;">&#9888;&#65039; 수급은 결과일 뿐 방향을 보장하지 않아요</div><div style="font-size:12.5px;color:#92400e;line-height:1.85;margin-top:4px;">'
             '외국인·기관이 많이 샀다고 오른다는 뜻도, 많이 팔았다고 내린다는 뜻도 아닙니다. 하루·며칠의 수급은 금방 바뀔 수 있어요. '
             '시장 전체 수급은 네이버가 제공하는 값이고, 종목별 수급은 수집한 종목의 추정치라 실제와 차이가 있을 수 있어요.</div></td></tr></table>')
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/market/blog", methods=["POST"])
def api_blog():
    """관리자 전용 — 저장한 수급과 AI 해설로 블로그용 HTML 글을 만든다(서버가 글을 올리지는 않아요)."""
    deny = _admin_deny()
    if deny:
        return deny
    b = _json_body() or {}
    view = _pick_view(str(b.get("view") or "market"))
    if not view:
        return _admin_json({"error": "시장수급 자료가 없어요. 먼저 [📥 시장 수급 가져오기]를 실행하세요."}, 404)
    an, st, th, idx = _gather(view, max(5, min(60, int(_n(b.get("days")) or 20))))
    if not an:
        return _admin_json({"error": "시장수급 자료가 없어요."}, 404)
    inc = b.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k in BLOG_SECS} if isinstance(inc, dict) else {k: True for k in BLOG_SECS}
    out = _blog_build(an, st, th, idx, str(b.get("ai") or "")[:20000], inc, _s(b.get("title"), 150))
    pseudo = "D" + an["base_date"].replace("-", "")[2:]
    logs, warn = B.dup_info(pseudo, "market")
    out.update({"ticker": pseudo, "name": "시장수급 " + an["base_date"], "dups": logs, "dup_warn": warn})
    return _admin_json(out)


# ══════════════════════════════════════════════════════════════
# 관리자 전용 점검
# ══════════════════════════════════════════════════════════════
@bp.route("/admin/api/market/diag", methods=["GET"])
def api_diag():
    deny = _admin_deny()
    if deny:
        return deny
    inv = _try("SELECT COUNT(*),MAX(base_date) FROM investor_scan_cache")
    th = _try("SELECT COUNT(*) FROM collect_theme_list")
    ai = _ai_get()
    return _admin_json({"ok": True, "counts": _counts(), "last": _json_get(KEY_LAST), "stocks": (inv[0][0] if inv else None), "stock_base": (inv[0][1] if inv else ""),
                        "themes": (th[0][0] if th else None), "ai_date": ai.get("date", ""), "views": _views_available(), "actors": ACT_LABEL})


TAB_JS = r"""
var MK={sec:'sum',css:false,view:'market',per:'5',days:'20',sum:null,hist:null,det:null,ex:null,ai:{text:'',date:'',old:null},flag:{img:false,blog:false,posted:false},_chain:0,imgPanel:null,blogPanel:null,
 st:{actor:'foreign',per:'5',side:'buy',market:'all',data:null},ln:{mk:'ALL',on:{}},diag:null,job:null,jtm:0,jwas:false,lim:'0',skip:true,memGo:null};
var MK_SECS=[['sum','📊 오늘의 수급','sum'],['flow','📈 일별 흐름','flow'],['detail','🧩 주체별 상세','detail'],['stocks','🔝 종목 상위','stocks'],['extra','🔥 테마·지수','extra'],['ai','🤖 AI 해설','ai'],['img','🖼 수급 이미지','img'],['blog','📝 블로그 쓰기','blog'],['guide','📘 읽는 법','guide']];
var MK_COL={retail:'#f59e0b',foreign:'#3b82f6',inst:'#10b981',securities:'#8b5cf6',insurance:'#ec4899',trust:'#14b8a6',private_fund:'#f97316',bank:'#64748b',other_fin:'#a16207',pension:'#0ea5e9',other:'#84cc16',gov:'#78716c',foreign_other:'#6366f1'};
var MK_NM={KOSPI:'코스피',KOSDAQ:'코스닥',ALL:'코스피+코스닥'};
var MK_CSS='.mkHd{padding:14px 16px}.mkHd h2{margin:0 0 4px;font-size:18px}'+
'.mkNav{display:flex;gap:2px;flex-wrap:wrap;margin:10px 0 8px;border-bottom:1.5px solid #e2e8f0}.mkNav button{border:0;border-bottom:3px solid transparent;margin-bottom:-1.5px;background:transparent;color:#64748b;border-radius:0;padding:8px 11px;font:inherit;font-size:13px;font-weight:700;cursor:pointer}.mkNav button:hover{color:#1e293b}.mkNav button.mkOn{border-bottom-color:#1e40af;color:#1e40af}'+
'.mkStp{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}.mkStp button{flex:1 1 170px;display:flex;align-items:center;gap:10px;text-align:left;border:1.5px solid #bfdbfe;background:#fff;color:#1e3a8a;border-radius:14px;padding:9px 12px;font:inherit;font-size:13.5px;font-weight:800;cursor:pointer;line-height:1.35}'+
'.mkStp button small{display:block;font-weight:600;font-size:11.5px;color:#64748b}.mkStp .n{width:26px;height:26px;border-radius:50%;background:#bfdbfe;color:#1e3a8a;display:flex;align-items:center;justify-content:center;font-weight:900;flex:0 0 auto}'+
'.mkStp .done{border-color:#86efac;background:#f0fdf4}.mkStp .done .n{background:#16a34a;color:#fff}.mkStp .cur{border-color:#1e40af;box-shadow:0 0 0 3px rgba(30,64,175,.18)}'+
'.mkL{display:inline-flex;flex-direction:column;gap:2px;font-size:11.5px;color:#64748b}.mkL select{min-width:92px}'+
'.mkW{overflow-x:auto;-webkit-overflow-scrolling:touch}.mkT{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}.mkT th{background:#eff6ff;white-space:nowrap}.mkT td.r,.mkT th.r{text-align:right;white-space:nowrap}.mkT .nm{font-weight:800;color:#0f172a}.mkT .sb{font-size:11px;color:#94a3b8}'+
'.mkUp{color:#dc2626;font-weight:700}.mkDn{color:#2563eb;font-weight:700}.mkZ{color:#94a3b8}'+
'.mkCard{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:8px 0}.mkCard h3{margin:0 0 6px;font-size:15px}'+
'.mkGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;margin:8px 0}'+
'.mkTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:8px 0}.mkTile{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px;text-align:center}.mkTile .l{font-size:11.5px;color:#64748b;font-weight:700}.mkTile .v{font-size:19px;font-weight:900;margin-top:2px}.mkTile .s{font-size:10.5px;color:#94a3b8}'+
'.mkVd{border-radius:14px;padding:12px 16px;margin:8px 0;color:#fff;font-weight:900}.mkVd.up{background:linear-gradient(135deg,#9f1239,#e11d48)}.mkVd.dn{background:linear-gradient(135deg,#1e3a8a,#2563eb)}.mkVd small{display:block;font-weight:600;opacity:.9;margin-top:3px;font-size:12px}'+
'.mkRow{display:grid;grid-template-columns:70px 1fr 78px;align-items:center;gap:8px;margin:5px 0;font-size:12.5px}.mkBar{position:relative;height:16px;background:#f1f5f9;border-radius:8px;overflow:hidden}.mkBar i{position:absolute;top:0;bottom:0}.mkBar b{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#94a3b8}'+
'.mkSg li{font-size:13px;line-height:1.7;color:#334155}.mkSvg{display:block;width:100%;height:auto}.mkLg{font-size:11.5px;color:#64748b;margin:4px 0}.mkLg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 3px 0 8px;vertical-align:-1px}'+
'.mkAiOut{white-space:pre-wrap;word-break:break-word;font-size:13.5px;line-height:1.65;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin-top:8px}'+
'.mkAiOut .h2{display:block;font-weight:900;color:#fff;background:#1e40af;border-radius:8px;padding:5px 10px;margin:10px 0 4px}.mkAiOut .h3{display:block;font-weight:800;border-left:5px solid #1e40af;padding-left:8px;margin:8px 0 2px}'+
'.mkGd h4{margin:12px 0 4px;font-size:14px}.mkGd p,.mkGd li{font-size:13px;line-height:1.65;color:#334155;margin:3px 0}.mkGd ul{margin:4px 0 4px 18px;padding:0}'+
'.mkPg{height:10px;border-radius:6px;background:#e2e8f0;overflow:hidden;margin:6px 0}.mkPg>div{height:100%;background:#1e40af;width:0}.mkTa{width:100%;min-height:120px;font:inherit;font-size:12px;border:1.5px solid #cbd5e1;border-radius:8px;padding:8px;box-sizing:border-box}'+
'.mkImgG .c{margin:8px 0}';
function mkCss(){if(MK.css)return;MK.css=true;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=MK_CSS;document.head.appendChild(s)}
function mkQ(o){var a=[];Object.keys(o).forEach(function(k){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]))});return a.join('&')}
function mkCls(v){return v>0?'mkUp':(v<0?'mkDn':'mkZ')}
function mkFe(v){if(v==null||isNaN(v))return '-';v=Number(v);var a=Math.abs(v),s=v>0?'+':(v<0?'-':'');if(a>=10000)return s+(a/10000).toFixed(1)+'조';return s+Math.round(a).toLocaleString('ko-KR')+'억'}
function mkPct(v){if(v==null||isNaN(v))return '-';return (v>0?'+':'')+Number(v).toFixed(2)+'%'}
function mkStrk(s){return !s?'-':(s>0?s+'일 연속 순매수':(-s)+'일 연속 순매도')}
function mkStamp(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())}
function mkDl(blob,name){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href)},4000)}
function mkSel(bar,lbl,obj,key,opts,fn){var l=el('label','mkL');l.appendChild(el('span',null,lbl));var s=el('select');opts.forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];s.appendChild(op)});s.value=obj[key];s.onchange=function(){obj[key]=s.value;if(fn)fn()};l.appendChild(s);bar.appendChild(l);return s}
function mkTbl(heads,aligns){var w=el('div','mkW'),t=el('table','mkT'),h=el('tr');heads.forEach(function(x,i){h.appendChild(el('th',aligns&&aligns[i]==='r'?'r':'',x))});t.appendChild(h);w.appendChild(t);return {wrap:w,t:t}}
function mkPlace(box,fid,txt){var c=el('div','mkCard');c.appendChild(el('b',null,txt||'이 기능은 잠겨 있어요'));c.appendChild(el('p','note','등급이 열리면 이 자리에 내용이 나타나요. 위 안내를 눌러 자세히 확인해 보세요.'));box.appendChild(c);ftSec(box,fid)}
function mkDate(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+'-'+z(d.getMonth()+1)+'-'+z(d.getDate())}

/* ── 화면 뼈대 ── */
function mkLoad(p){mkCss();p.innerHTML='';
 var hd=el('div','c mkHd');hd.appendChild(el('h2',null,'📊 시장수급 — 오늘의 코스피·코스닥 수급'));
 hd.appendChild(el('div','m','개인·외국인·기관이 코스피·코스닥을 얼마나 사고팔았는지 보여 줘요. 정보 제공용이며 투자 권유가 아니에요.'));
 var sb=el('div');sb.id='mkSum';hd.appendChild(sb);p.appendChild(hd);
 var ad=el('div','c');ad.id='mkAdm';p.appendChild(adm(ad));var sp=el('div','mkStp');sp.id='mkSteps';p.appendChild(sp);var nv=el('div','mkNav');nv.id='mkNav';p.appendChild(nv);var bd=el('div');bd.id='mkBody';p.appendChild(bd);
 p.appendChild(el('p','note','※ 시장 전체 수급은 네이버가 주는 개인·외국인·기관 순매수(억원)이고 하루치씩 쌓아 이력을 만들어요. “수집 종목 합산”은 시가총액 상위 일부 종목의 ‘순매수 수량×종가’ 합이라 시장 전체와 차이가 있어요. 수급은 결과일 뿐 이후 주가를 보장하지 않아요. 투자 판단과 책임은 이용자 본인에게 있어요.'));
 if(MEMBER_MODE&&MK.sec==='blog')MK.sec='sum';mkNavDraw();mkShow();mkSteps();if(!MEMBER_MODE){mkAdmLoad();mkAiLoad();mkJobPoll(false)}}
function mkNavDraw(){var n=$('mkNav');if(!n)return;n.innerHTML='';MK_SECS.forEach(function(s){if(MEMBER_MODE&&s[0]==='blog')return;var b=el('button',MK.sec===s[0]?'mkOn':'',(ftOk(s[2])?'':'🔒 ')+s[1]);b.type='button';b.onclick=function(){mkGo(s[0])};n.appendChild(b)})}
var MKFLOW=['ai','img','blog','post'];
function mkHas(){return !!(MK.sum&&!MK.sum.empty)}
function mkSteps(){var sp=$('mkSteps');if(!sp)return;var has=mkHas(),ai=!!(MK.ai.text&&MK.ai.text.trim()),F=MK.flag;
 var steps=[{t:'시장 수급',sub:has?((MK.sum.days||0)+'거래일 · '+(MK.sum.base_date||'')):'가져오거나 조회하세요',done:has,go:function(){mkStepRun('sum')}},
  {t:'AI 해설',sub:ai?'완료 · 다시 만들기':'눌러서 시작',done:ai,go:function(){mkStepRun('ai')}},
  {t:MEMBER_MODE?'수급 이미지':'이미지 만들기',sub:F.img?'만들었어요 · 다시 만들기':'눌러서 만들기',done:F.img,go:function(){mkStepRun('img')}},
  {t:'글 만들기',sub:F.blog?'완료 · 다시 만들기':'눌러서 만들기',done:F.blog,hide:MEMBER_MODE,go:function(){mkStepRun('blog')}},
  {t:'블로그에 쓰기',sub:F.posted?'복사·열기 완료':(F.blog?'복사하고 블로그 열기':'글을 먼저 만드세요'),done:F.posted,off:!F.blog,hide:MEMBER_MODE,go:function(){mkStepRun('post')}}];
 window.FlowBar.draw(sp,{steps:steps,runAll:MEMBER_MODE?null:function(){mkStepRun('all')},note:MEMBER_MODE?'':'[⚡ 블로그까지 한 번에]는 AI 해설 → 이미지 → 글 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 블로그 글쓰기 화면에 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'})}
function mkStepRun(id){
 if(id==='sum'){mkGo('sum');return}
 if(!mkHas()&&MK.sec==='sum'){toast(MEMBER_MODE?'아직 시장수급 자료가 없어요.':'먼저 아래 [📥 시장 수급 가져오기]를 눌러 주세요.');return}
 if(id==='ai'){if(!ftOk('ai')){lockDlg('ai');return}mkGo('ai');mkAiRun();return}
 if(id==='img'){if(!ftOk('img')){lockDlg('img');return}if(MEMBER_MODE){mkGo('img');if(MK.memGo&&!MK.memGo.disabled)MK.memGo.click();return}MK.flag.img=false;if(window.MiniFlow)MiniFlow.go('market',MKFLOW,MKACTS,'img');else mkGo('img');return}
 if(MEMBER_MODE)return;
 if(id==='blog'){MK.flag.blog=false;if(window.MiniFlow)MiniFlow.go('market',MKFLOW,MKACTS,'blog');else mkGo('blog');return}
 if(id==='post'){mkPostGo(false);return}
 if(id==='all'){if(!window.MiniFlow)return;toast('⚡ 블로그까지 이어서 진행해요');MiniFlow.force('market',MKFLOW,MKACTS)}}
function mkPostGo(auto){var P=MK.blogPanel;if(MK.sec==='blog'&&P&&P.built()){P.copyOpen(auto);return true}
 if(!MK.flag.blog){if(!auto)toast('먼저 ④ 글 만들기를 해 주세요');return false}
 mkGo('blog');var k=0,t=setInterval(function(){var Q=MK.blogPanel;if(Q&&Q.built()){clearInterval(t);Q.copyOpen(auto)}else if(++k>40)clearInterval(t)},250);return true}
var MKACTS={
 ai:function(next){if(!mkHas())return;if((MK.ai.text||'').trim()){next();return}if(!ftOk('ai'))return;mkGo('ai');mkAiRun()},
 img:function(next){if(MK.flag.img){next();return}mkEnsure().then(function(){mkGo('img');if(!MK.imgPanel)return;return MK.imgPanel.gen(true).then(function(){if(MK.imgPanel&&MK.imgPanel.items())next()})}).catch(function(){})},
 blog:function(next){if(MK.flag.blog&&MK.sec==='blog'&&MK.blogPanel&&MK.blogPanel.built()){next();return}mkEnsure().then(function(){MK.flag.blog=false;mkGo('blog');if(!MK.blogPanel)return;return MK.blogPanel.rebuild().then(function(j){if(j&&!j.error)next()})}).catch(function(){})},
 post:function(next){if(mkPostGo(true))next()}};
function mkGo(sec){MK.sec=sec;mkNavDraw();mkShow()}
function mkShow(){var b=$('mkBody');if(!b)return;b.innerHTML='';var box=el('div');b.appendChild(box);
 var m={sum:mkSecSum,flow:mkSecFlow,detail:mkSecDetail,stocks:mkSecStocks,extra:mkSecExtra,ai:mkSecAi,img:mkSecImg,blog:mkSecBlog,guide:mkSecGuide}[MK.sec],fid=MK_SECS.filter(function(s){return s[0]===MK.sec})[0][2];
 if(!ftOk(fid)){var f=FEATS&&FEATS[fid];mkPlace(box,fid,'🔒 '+(f?f.label:'잠긴 기능'));return}m(box)}
function mkQ0(){return {view:MK.view,days:MK.days}}
function mkEnsure(){if(mkHas())return Promise.resolve(MK.sum);return api('/admin/api/market/summary?'+mkQ(mkQ0())).then(function(j){if(j.error)throw new Error(j.error);if(j.empty)throw new Error(j.msg||'시장수급 자료가 없어요.');MK.sum=j;mkSteps();return j})}
function mkStatus(){var b=$('mkSum');if(!b)return;b.innerHTML='';var j=MK.sum;if(!j||j.empty)return;var st=el('div','mkStp0');st.style.cssText='display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0';
 function chip(t,on){var c=el('span',null,t);c.style.cssText='display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;border:1px solid '+(on?'#bfdbfe':'#e2e8f0')+';background:'+(on?'#eff6ff':'#f1f5f9')+';color:'+(on?'#1d4ed8':'#334155');return c}
 st.appendChild(chip('기준일 '+j.base_date,true));st.appendChild(chip('자료 '+j.days+'거래일'));st.appendChild(chip(j.view==='market'?'시장 전체':'수집 종목 합산',j.view==='market'));
 var ix=j.idx||{};['KOSPI','KOSDAQ'].forEach(function(k){if(ix[k])st.appendChild(chip(MK_NM[k]+' '+Number(ix[k].price).toLocaleString('ko-KR',{minimumFractionDigits:2,maximumFractionDigits:2})+' ('+mkPct(ix[k].pct)+')'))});
 b.appendChild(st)}

/* ── ① 오늘의 수급 ── */
function mkSecSum(box){
 var bar=el('div','bar');var ch=function(){MK.sum=null;MK.hist=null;MK.det=null;mkSteps();mkShow()};
 bar.appendChild(el('span','m','자료 선택'));mkSel(bar,'',MK,'view',[['market','시장 전체(네이버+붙여넣기)'],['univ','수집 종목 합산']],ch);mkSel(bar,'',MK,'per',[['1','1일'],['5','5일'],['20','20일']],function(){mkSecSumDraw()});box.appendChild(bar);
 var o=el('div');o.id='mkSumO';box.appendChild(o);
 o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/market/summary?'+mkQ(mkQ0())).then(function(j){if(j.error)return;if(j.empty){MK.sum={empty:true};o.innerHTML='';o.appendChild(el('p','note',j.msg||'자료가 없어요.'));mkStatus();mkSteps();return}
  MK.sum=j;if(j.views&&j.views.length&&j.views.indexOf(MK.view)<0)MK.view=j.views[0];mkStatus();mkSteps();mkSecSumDraw()})}
function mkPerKey(m){var k=MK.per;return m.periods.indexOf(Number(k))>=0?k:String(m.periods[m.periods.length-1])}
function mkSecSumDraw(){var o=$('mkSumO'),j=MK.sum;if(!o||!j||j.empty)return;o.innerHTML='';
 if(j.verdict){var v=el('div','mkVd '+j.verdict.tone,'외국인+기관 흐름: '+j.verdict.text);v.appendChild(el('small',null,'최근 5일 일평균 '+mkFe(j.verdict.pace5)+' · 20일 평균 '+mkFe(j.verdict.pace20)+' (코스피+코스닥 합산, 순매수 기준)'));o.appendChild(v)}
 var g=el('div','mkGrid');['ALL','KOSPI','KOSDAQ'].forEach(function(mk){var m=j.markets[mk];if(!m)return;var c=el('div','mkCard');var pk=mkPerKey(m);c.appendChild(el('h3',null,MK_NM[mk]+' · 최근 '+pk+'일'));
  var mx=0;m.actors.forEach(function(a){mx=Math.max(mx,Math.abs(a.p[pk]||0))});mx=mx||1;
  m.actors.forEach(function(a){var r=el('div','mkRow');r.appendChild(el('span',null,a.label));var bar=el('div','mkBar');var w=Math.round(Math.abs(a.p[pk]||0)*50/mx);var i=document.createElement('i');i.style.width=w+'%';i.style.background=(a.p[pk]||0)>=0?'#e11d48':'#2563eb';if((a.p[pk]||0)>=0)i.style.left='50%';else i.style.right='50%';bar.appendChild(i);bar.appendChild(document.createElement('b'));r.appendChild(bar);r.appendChild(el('span','r '+mkCls(a.p[pk]),mkFe(a.p[pk])));c.appendChild(r)});
  var t=el('div','mkTiles');m.actors.filter(function(a){return a.main}).forEach(function(a){var x=el('div','mkTile');x.appendChild(el('div','l',a.label+' 1일'));x.appendChild(el('div','v '+mkCls(a.p['1']),mkFe(a.p['1'])));x.appendChild(el('div','s',a.streak&&Math.abs(a.streak)>=2?mkStrk(a.streak):'연속 없음'));t.appendChild(x)});c.appendChild(t);g.appendChild(c)});o.appendChild(g);
 if(j.signals&&j.signals.length){var c2=el('div','mkCard');c2.appendChild(el('h3',null,'💡 오늘의 수급 포인트'));var u=el('ul','mkSg');j.signals.forEach(function(s){u.appendChild(el('li',null,s))});c2.appendChild(u);o.appendChild(c2)}
 o.appendChild(el('p','note','빨강(+)은 순매수, 파랑(−)은 순매도예요. 막대는 한 카드 안에서 가장 큰 값을 기준으로 길이를 맞춘 것이라 카드끼리 길이를 비교하지 마세요.'))}

/* ── ② 일별 흐름: 누적 선그래프 + 일별 표 ── */
function mkSvg(tag,at){var e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.keys(at||{}).forEach(function(k){e.setAttribute(k,at[k])});return e}
function mkLine(dates,series){var W=720,H=260,pl=58,pr=12,pt=14,pb=34,cw=W-pl-pr,ch=H-pt-pb,n=dates.length,svg=mkSvg('svg',{viewBox:'0 0 '+W+' '+H,'class':'mkSvg'});
 if(n<2||!series.length){var t=mkSvg('text',{x:W/2,y:H/2,'text-anchor':'middle','font-size':14,fill:'#94a3b8'});t.textContent='그래프를 그리려면 2일 이상의 자료가 필요해요';svg.appendChild(t);return svg}
 var all=[0];series.forEach(function(s){s.data.forEach(function(v){all.push(v)})});var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),pd=(hi-lo)*0.12||1;lo-=pd;hi+=pd;
 var X=function(i){return pl+i*cw/(n-1)},Y=function(v){return pt+ch*(hi-v)/(hi-lo)};
 for(var k=0;k<=4;k++){var v=lo+(hi-lo)*k/4,y=Y(v);svg.appendChild(mkSvg('line',{x1:pl,x2:W-pr,y1:y,y2:y,stroke:'#e2e8f0','stroke-width':1}));var tx=mkSvg('text',{x:pl-6,y:y+4,'text-anchor':'end','font-size':11,fill:'#64748b'});tx.textContent=mkFe(v).replace('+','');svg.appendChild(tx)}
 svg.appendChild(mkSvg('line',{x1:pl,x2:W-pr,y1:Y(0),y2:Y(0),stroke:'#64748b','stroke-width':1.5,'stroke-dasharray':'5 4'}));
 var step=Math.max(1,Math.floor(n/6));for(var i=0;i<n;i+=step){var xt=mkSvg('text',{x:X(i),y:H-12,'text-anchor':'middle','font-size':11,fill:'#64748b'});xt.textContent=dates[i].slice(5).replace('-','.');svg.appendChild(xt)}
 series.forEach(function(s){var d='';s.data.forEach(function(v,i){d+=(i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)});svg.appendChild(mkSvg('path',{d:d,fill:'none',stroke:s.color,'stroke-width':3,'stroke-linejoin':'round'}));
  if(n<=25)s.data.forEach(function(v,i){svg.appendChild(mkSvg('circle',{cx:X(i),cy:Y(v),r:3,fill:s.color}))})});return svg}
function mkSecFlow(box){box.appendChild(el('p','note','주체별 누적 순매수 선이에요. 0선 위에서 오른쪽 위로 가면 매수가 이어지는 것, 0선 아래에서 오른쪽 아래로 가면 매도가 이어지는 것이고, 선이 꺾이는 날이 수급이 바뀐 날이에요.'));
 var bar=el('div','bar');mkSel(bar,'자료',MK,'view',[['market','시장 전체'],['univ','수집 종목 합산']],function(){MK.hist=null;mkShow()});mkSel(bar,'시장',MK.ln,'mk',[['ALL','코스피+코스닥'],['KOSPI','코스피'],['KOSDAQ','코스닥']],function(){mkFlowDraw()});box.appendChild(bar);
 var o=el('div');o.id='mkFlowO';box.appendChild(o);
 if(MK.hist){mkFlowDraw();return}o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/market/history?'+mkQ(mkQ0())).then(function(j){if(j.error)return;if(j.empty){o.innerHTML='';o.appendChild(el('p','note',j.msg));return}MK.hist=j;mkFlowDraw()})}
function mkFlowDraw(){var o=$('mkFlowO'),j=MK.hist;if(!o||!j)return;o.innerHTML='';var mk=j.markets[MK.ln.mk]?MK.ln.mk:Object.keys(j.markets)[0],m=j.markets[mk];if(!m)return;
 var keys=m.actors.map(function(a){return a.key});if(!Object.keys(MK.ln.on).length||!keys.some(function(k){return MK.ln.on[k]}))keys.forEach(function(k){MK.ln.on[k]=(k==='retail'||k==='foreign'||k==='inst')});
 var ck=el('div','bar');m.actors.forEach(function(a){var l=el('label');l.style.cssText='font-size:12.5px;margin-right:10px;white-space:nowrap';var i=el('input');i.type='checkbox';i.checked=!!MK.ln.on[a.key];i.onchange=function(){MK.ln.on[a.key]=i.checked;mkFlowDraw()};l.appendChild(i);var sp=el('span',null,' '+a.label);sp.style.color=MK_COL[a.key]||'#334155';sp.style.fontWeight='700';l.appendChild(sp);ck.appendChild(l)});o.appendChild(ck);
 var series=m.actors.filter(function(a){return MK.ln.on[a.key]}).map(function(a){return {label:a.label,color:MK_COL[a.key]||'#334155',data:m.cum[a.key]||[]}});
 var c=el('div','mkCard');c.appendChild(el('h3',null,MK_NM[mk]+' 누적 순매수 (억원, '+m.dates.length+'거래일)'));c.appendChild(mkLine(m.dates,series));var lg=el('div','mkLg');series.forEach(function(s){var i=document.createElement('i');i.style.background=s.color;lg.appendChild(i);lg.appendChild(document.createTextNode(s.label))});c.appendChild(lg);o.appendChild(c);
 var cols=m.actors.filter(function(a){return MK.ln.on[a.key]});var tb=mkTbl(['날짜'].concat(cols.map(function(a){return a.label})),['','r','r','r','r','r','r','r','r','r','r','r','r','r']);
 m.hist.slice().reverse().forEach(function(h,idx){var tr=el('tr');tr.appendChild(el('td','nm',h.date.slice(5).replace('-','.')+(idx===0?' (최신)':'')));cols.forEach(function(a){tr.appendChild(el('td','r '+mkCls(h[a.key]),mkFe(h[a.key])))});tb.t.appendChild(tr)});
 var sm=el('tr');sm.appendChild(el('td','nm','Σ 합계'));cols.forEach(function(a){var t=0;m.hist.forEach(function(h){t+=h[a.key]||0});sm.appendChild(el('td','r '+mkCls(t),mkFe(t)))});tb.t.appendChild(sm);
 var cc=el('div','mkCard');cc.appendChild(el('h3',null,'📅 일별 순매수 (최신일부터)'));cc.appendChild(tb.wrap);
 if(!MEMBER_MODE||ftOk('exp')){var eb=bt('📄 CSV 내려받기','bt3',function(){var L=['날짜,'+cols.map(function(a){return a.label}).join(',')];m.hist.slice().reverse().forEach(function(h){L.push(h.date+','+cols.map(function(a){return h[a.key]}).join(','))});mkDl(new Blob(['﻿'+L.join('\n')],{type:'text/csv'}),'시장수급_'+mk+'_'+mkStamp()+'.csv')});cc.appendChild(ft(eb,'exp'))}
 o.appendChild(cc)}

/* ── ③ 주체별 상세 ── */
function mkSecDetail(box){var bar=el('div','bar');mkSel(bar,'자료',MK,'view',[['market','시장 전체'],['univ','수집 종목 합산']],function(){MK.det=null;mkShow()});box.appendChild(bar);var o=el('div');o.id='mkDetO';box.appendChild(o);
 if(MK.det){mkDetDraw();return}o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/market/detail?'+mkQ(mkQ0())).then(function(j){if(j.error)return;if(j.empty){o.innerHTML='';o.appendChild(el('p','note',j.msg));return}MK.det=j;mkDetDraw()})}
function mkDetDraw(){var o=$('mkDetO'),j=MK.det;if(!o||!j)return;o.innerHTML='';
 var extra=0;['KOSPI','KOSDAQ'].forEach(function(mk){var m=j.markets[mk];if(m)m.actors.forEach(function(a){if(!a.main)extra++})});
 if(!extra)o.appendChild(el('p','note','지금은 개인·외국인·기관 3주체만 있어요. 금융투자·보험·투신·연기금 같은 세부 주체는 관리자가 KRX 표를 붙여 넣으면 여기에 함께 나와요(네이버가 세부 분류 주소를 닫았어요).'));
 ['KOSPI','KOSDAQ','ALL'].forEach(function(mk){var m=j.markets[mk];if(!m)return;var c=el('div','mkCard');c.appendChild(el('h3',null,MK_NM[mk]+' · 기준 '+m.base_date+' · '+m.days+'거래일'));
  var heads=['주체'].concat(m.periods.map(function(p){return p+'일'})).concat(['연속','5일 평균/일','20일 평균/일','1일 비중']);var al=['','r','r','r','r','r','r','r','r','r'];var tb=mkTbl(heads,al);
  m.actors.forEach(function(a){var tr=el('tr');tr.appendChild(el('td','nm',a.label+(a.main?'':' ·세부')));m.periods.forEach(function(p){tr.appendChild(el('td','r '+mkCls(a.p[String(p)]),mkFe(a.p[String(p)])))});
   tr.appendChild(el('td','r',a.streak?mkStrk(a.streak).replace('일 연속 ','일·'):'-'));tr.appendChild(el('td','r '+mkCls(a.pace5),mkFe(a.pace5)));tr.appendChild(el('td','r '+mkCls(a.pace20),mkFe(a.pace20)));tr.appendChild(el('td','r',a.share1==null?'-':a.share1+'%'));tb.t.appendChild(tr)});
  c.appendChild(tb.wrap);o.appendChild(c)});
 o.appendChild(el('p','note','연속은 가장 최근 날부터 같은 방향(순매수·순매도)이 며칠 이어졌는지, 평균/일은 그 기간 순매수를 일수로 나눈 값이에요. 비중은 개인·외국인·기관 세 주체 절대값 합에서 차지하는 하루 기준 비율이에요.'))}

/* ── ④ 종목 상위 ── */
function mkSecStocks(box){box.appendChild(el('p','note','시가총액 상위 일부 종목(관리자가 가져온 만큼)의 최근 1·5·20거래일 순매수 합계로 줄 세운 순위예요. 종목 이름을 누르면 네이버 증권 종목 화면이 열려요.'));
 var S=MK.st,bar=el('div','bar');var rd=function(){S.data=null;mkStocksLoad()};
 mkSel(bar,'주체',S,'actor',[['foreign','외국인'],['inst','기관'],['retail','개인'],['comb','외국인+기관'],['dual','쌍끌이(외·기 동시 순매수)']],rd);mkSel(bar,'기간',S,'per',[['1','1일'],['5','5일'],['20','20일']],rd);mkSel(bar,'방향',S,'side',[['buy','순매수 상위'],['sell','순매도 상위']],rd);mkSel(bar,'시장',S,'market',[['all','코스피+코스닥'],['KOSPI','코스피'],['KOSDAQ','코스닥']],rd);box.appendChild(bar);
 var o=el('div');o.id='mkStO';box.appendChild(o);mkStocksLoad()}
function mkStocksLoad(){var o=$('mkStO'),S=MK.st;if(!o)return;o.innerHTML='';o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/market/stocks?'+mkQ({actor:S.actor,per:S.per,side:S.side,market:S.market,top:20})).then(function(j){if(j.error)return;o.innerHTML='';if(j.empty){o.appendChild(el('p','note',j.msg));return}
  if(S.actor==='retail'&&!j.has_retail)o.appendChild(el('p','note bad','개인 수급은 관리자가 [📥 종목 수급 가져오기]를 한 번 더 실행하면 채워져요.'));
  if(!j.items.length){o.appendChild(el('p','note','조건에 맞는 종목이 없어요.'));return}
  o.appendChild(el('p','note','수집 종목 '+j.total+'개 중 '+j.match+'개가 조건에 맞아요 · 상위 '+j.items.length+'개'));
  var HR=!!j.has_retail,tb=mkTbl(HR?['#','종목','선택한 기간','외국인','기관','개인','기타*','등락률']:['#','종목','선택한 기간','외국인','기관','개인','등락률'],HR?['','','r','r','r','r','r','r']:['','','r','r','r','r','r']);
  j.items.forEach(function(x,i){var tr=el('tr');tr.appendChild(el('td',null,String(i+1)));var td=el('td','nm');var a=el('a',null,x.name);a.href='https://finance.naver.com/item/main.naver?code='+encodeURIComponent(x.ticker);a.target='_blank';a.rel='noopener';td.appendChild(window.StockName?window.StockName(x.ticker,x.name):a);td.appendChild(el('div','sb',x.ticker+(x.market?' · '+x.market:'')));tr.appendChild(td);
   tr.appendChild(el('td','r '+mkCls(x.amount),mkFe(x.amount)));tr.appendChild(el('td','r '+mkCls(x.f),mkFe(x.f)));tr.appendChild(el('td','r '+mkCls(x.i),mkFe(x.i)));tr.appendChild(el('td','r '+mkCls(x.r),mkFe(x.r)));if(HR){var ox=-((x.f||0)+(x.i||0)+(x.r||0));tr.appendChild(el('td','r '+mkCls(ox),mkFe(ox)))}tr.appendChild(el('td','r '+mkCls(x.pct),mkPct(x.pct)));tb.t.appendChild(tr)});o.appendChild(tb.wrap);if(HR)o.appendChild(el('p','note','* 기타 = −(개인+외국인+기관) 추정값(기타법인·기타외국인 등). 네이버는 종목별로 개인·외국인·기관(합계)만 줘서 사모·연기금 등은 나눌 수 없어요.'))})}

/* ── ⑤ 강세 테마·지수 ── */
function mkSecExtra(box){var o=el('div');box.appendChild(o);o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/market/extra').then(function(j){if(j.error)return;o.innerHTML='';MK.ex=j;var ix=j.idx||{};var t=el('div','mkTiles');['KOSPI','KOSDAQ'].forEach(function(k){if(!ix[k])return;var x=el('div','mkTile');x.appendChild(el('div','l',MK_NM[k]+' 지수'));x.appendChild(el('div','v '+mkCls(ix[k].pct),Number(ix[k].price).toLocaleString('ko-KR',{minimumFractionDigits:2,maximumFractionDigits:2})));x.appendChild(el('div','s',mkPct(ix[k].pct)));t.appendChild(x)});if(t.children.length)o.appendChild(t);
  var th=j.themes;if(!th){o.appendChild(el('p','note','네이버 테마 자료가 없어요. 관리자가 🏷 네이버테마 메뉴에서 [테마 가져오기]를 실행하면 보여요.'));return}
  var g=el('div','mkGrid');[['🔥 강세 테마',th.top],['🧊 약세 테마',th.bottom]].forEach(function(p){var c=el('div','mkCard');c.appendChild(el('h3',null,p[0]));if(!p[1].length){c.appendChild(el('p','note','해당하는 테마가 없어요.'))}else{var tb=mkTbl(['테마','등락률','상승/하락'],['','r','r']);p[1].forEach(function(x){var tr=el('tr');tr.appendChild(el('td','nm',x.name));tr.appendChild(el('td','r '+mkCls(x.rate),mkPct(x.rate)));tr.appendChild(el('td','r','▲'+x.rise+' ▼'+x.fall));tb.t.appendChild(tr)});c.appendChild(tb.wrap)}g.appendChild(c)});o.appendChild(g)})}

/* ── ⑥ AI 해설(수동: 프롬프트 복사 → 답변 붙여넣기) ── */
function mkSecAi(box){box.appendChild(el('p','note',MEMBER_MODE?'오늘의 수급 요약을 담은 프롬프트를 만들어 사용하는 AI(제미나이·챗GPT·클로드 등)에 붙여 넣을 수 있게 해요. AI가 답하면 복사해서 이 창으로 돌아오면 아래에 보여 줘요(이 화면에서만 보관돼요). AI 답변은 참고용이며 틀릴 수 있어요.':'오늘의 수급 요약(주체별·종목·테마)을 담은 프롬프트를 AI에 붙여 넣어요. AI 답변을 복사하고 이 창으로 돌아오면 읽어 와서 저장하고, 다음 단계(수급 이미지 → 블로그 글)로 이어져요. AI 답변은 참고용이며 틀릴 수 있어요.'));
 var bar=el('div','bar');bar.appendChild(ft(bt('🤖 AI 프롬프트 만들기','bt',mkAiRun),'ai'));box.appendChild(bar);var out=el('div');out.id='mkAiOut';box.appendChild(out);mkAiDraw()}
function mkAiRun(){if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}
 api('/admin/api/market/prompt?'+mkQ(mkQ0())).then(function(j){if(j.error){toast(j.error);return}if(j.empty){toast(j.msg);return}
  window.MiniAI.run({title:'시장수급 AI 해설 — '+j.label,key:'market',steps:[{label:j.label,prompt:j.prompt}],minLen:150,hint:'AI가 "## 📊 오늘 수급 한 줄 요약 …" 형식으로 답하면 답변 전체를 복사하고 이 창으로 돌아오세요.',
   preview:function(t){var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString('ko-KR')+'자 — '+t.slice(0,240)+(t.length>240?' …':'');return {node:x,canApply:t.trim().length>=100,strict:true}},
   apply:function(t){MK.ai.text=String(t||'').slice(0,20000);MK.ai.date='';MK.flag.img=false;MK.flag.blog=false;MK.flag.posted=false;
    if(MEMBER_MODE){mkAiDraw();mkSteps();return Promise.resolve({message:'AI 해설을 아래 화면에 보여 줬어요(이 화면에서만 보관돼요).'})}
    return apiJ('/admin/api/market/ai',{text:MK.ai.text,label:j.label}).then(function(z){var ok=!z.error;if(ok)MK.ai.date=z.date;mkAiDraw();mkSteps();
     if(ok)setTimeout(function(){if(window.MiniFlow)MiniFlow.run('market',MKFLOW,MKACTS,'ai')},60);
     return {message:ok?'AI 해설을 저장했어요. 다음 단계(이미지 → 블로그 글)로 이어져요.':'읽었지만 저장하지 못했어요: '+z.error}}).catch(function(){mkAiDraw();mkSteps();return {message:'읽었지만 저장하지 못했어요(네트워크).'}})}})})}
function mkAiLoad(){if(MEMBER_MODE)return;api('/admin/api/market/ai').then(function(j){if(!j||j.error||!j.found)return;if(j.stale){MK.ai.old={text:j.text,date:j.date}}else{MK.ai.text=j.text;MK.ai.date=j.date}mkAiDraw();mkSteps()})}
function mkAiDraw(){var out=$('mkAiOut');if(!out)return;out.innerHTML='';var t=MK.ai.text;if(!t){out.appendChild(el('p','note','아직 AI 해설이 없어요. [AI 프롬프트 만들기]를 눌러 보세요.'));
  var o=MK.ai.old;if(o&&!MEMBER_MODE){var r0=el('div','bar');r0.appendChild(el('span','m','지난 AI 해설이 저장돼 있어요('+(o.date||'')+'). 오늘 수급과 맞지 않을 수 있어요.'));r0.appendChild(bt('지난 해설 불러오기','bt3',function(){MK.ai.text=o.text;MK.ai.date=o.date;MK.ai.old=null;MK.flag.img=false;MK.flag.blog=false;mkAiDraw();mkSteps()}));out.appendChild(r0)}return}
 var box=el('div','mkAiOut');t.split('\n').forEach(function(l){var m;var s=l.replace(/\*\*/g,'');if((m=/^##\s+(.*)$/.exec(s))){box.appendChild(el('span','h2',m[1]))}else if((m=/^###\s+(.*)$/.exec(s))){box.appendChild(el('span','h3',m[1]))}else{box.appendChild(document.createTextNode(s));box.appendChild(document.createElement('br'))}});out.appendChild(box);
 var r=el('div','bar');r.appendChild(bt('📋 해설 복사하기','bt3',function(){var ok=window.MiniAI&&window.MiniAI.copy?window.MiniAI.copy(MK.ai.text):false;toast(ok?'복사했어요':'복사가 막혔어요')}));r.appendChild(bt('✖ 지우기','bt3',function(){MK.ai.text='';MK.ai.date='';mkAiDraw();mkSteps()}));out.appendChild(r);
 if(MK.ai.date&&!MEMBER_MODE)out.appendChild(el('p','note','💾 저장돼 있어요('+MK.ai.date+') — 수급 이미지·블로그 글에 쓰여요. [지우기]는 이 화면에서만 지우고 저장본은 남아요.'));
 out.appendChild(el('p','note','⚠ AI가 만든 참고 글이에요. 숫자와 내용이 틀릴 수 있고, 특정 종목의 매수·매도 권유가 아니에요.'))}

/* ── ⑦ 수급 이미지(브라우저 캔버스) ── */
function mkImgBuild(scale){return mkEnsure().then(function(){return Promise.all([api('/admin/api/market/history?'+mkQ(mkQ0())),api('/admin/api/market/detail?'+mkQ(mkQ0()))])}).then(function(r){if(r[0].error||r[1].error)throw new Error(r[0].error||r[1].error);if(!window.MkImg)throw new Error('이미지 도구가 올라가지 않았어요.');return window.MkImg.build(r[1],r[0],MK.ai.text||'',scale)})}
function mkSecImg(box){box.appendChild(el('p','note',MEMBER_MODE?'오늘의 수급 요약을 한 장의 대시보드 이미지로 만들어 내려받아요. 만든 뒤 [이미지 내려받기]로 내 기기에 저장하세요. 참고 자료이며 투자 권유가 아니에요.':'① 수급 대시보드(주체별 순매수·누적 그래프) ② AI 해설 요약(AI 해설이 있을 때)을 이미지로 그려요. 저장 폴더·자동/수동 저장은 [⚙ 저장 설정]에서 정해요. 이 이미지를 블로그 글 위쪽에 올려 쓰세요.'));
 var ib=el('div');box.appendChild(ib);if(!window.ImgKit){ib.appendChild(el('p','note bad','이미지 도구(menu_img.py)가 올라가지 않았어요.'));return}
 if(MEMBER_MODE){mkImgMember(ib);return}
 MK.imgPanel=ImgKit.panel(ib,{menu:'market',name:'시장수급',ticker:mkStamp(),perStock:false,onDone:function(){MK.flag.img=true;mkSteps()},next:function(){if(window.MiniFlow)MiniFlow.run('market',MKFLOW,MKACTS,'img')},gen:function(scale){return mkImgBuild(scale)}});
 if(MK.flag.img)MK.imgPanel.gen(false)}
function mkImgMember(ib){var K=window.ImgKit,row=el('div','bar'),view=el('div','mkImgG'),st=el('div','m');
 var go=bt('🖼 이미지 만들기','bt',function(){go.disabled=true;go.textContent='⏳ 그리는 중…';view.innerHTML='';st.textContent='';
  Promise.resolve(K.fonts()).then(function(){return mkImgBuild(2)}).then(function(items){items.forEach(function(it){var c=el('div','c');c.appendChild(el('b',null,K.CIRC[it.idx-1]+' '+it.label));
    var pw=Math.min(720,it.canvas.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(it.canvas.height*pw/it.canvas.width);sm.getContext('2d').drawImage(it.canvas,0,0,sm.width,sm.height);
    var im=new Image();im.alt=it.label;im.src=sm.toDataURL('image/png');im.style.cssText='width:100%;height:auto;display:block;border-radius:8px;margin:6px 0';c.appendChild(im);
    c.appendChild(bt('💾 이미지 내려받기','bt2',function(){it.canvas.toBlob(function(bl){if(!bl){toast('이미지를 만들지 못했어요');return}mkDl(bl,K.fileName(it.idx,'시장수급',mkStamp()))},'image/png')}));view.appendChild(c)});
   st.textContent='이미지를 만들었어요. 각 이미지의 [이미지 내려받기]로 내 기기에 저장하세요.';go.textContent='🔄 다시 만들기';MK.flag.img=true;mkSteps()})
  .catch(function(e){st.textContent='이미지를 만들지 못했어요: '+(e&&e.message||e);go.textContent='🖼 이미지 만들기'}).then(function(){go.disabled=false})});
 MK.memGo=go;row.appendChild(go);ib.appendChild(row);ib.appendChild(st);ib.appendChild(view)}
(function(){
var K=window.ImgKit;if(!K||window.MkImg)return;
var T=K.text,RR=K.rr;
var NAVY0='#0a1228',NAVY1='#16275a',GOLD='#d6b25e',PAPER='#f4f0e6',INK='#0f172a',MUT='#64748b',UP='#e11d48',DN='#2563eb';
function fe(v){if(v==null||isNaN(v))return '-';v=Number(v);var a=Math.abs(v),s=v>0?'+':(v<0?'-':'');if(a>=10000)return s+(a/10000).toFixed(1)+'조';return s+Math.round(a).toLocaleString('ko-KR')+'억'}
function band(c,W,kick,title,sub){var g=c.createLinearGradient(0,0,0,210);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,210);c.fillStyle=GOLD;c.fillRect(0,0,W,8);
 T(c,kick,W/2,60,{s:20,w:800,c:GOLD,a:'center',ls:5});T(c,title,W/2,132,{s:54,w:900,c:'#fff',a:'center',max:W-120});T(c,sub,W/2,178,{s:21,w:600,c:'#cbd5e1',a:'center',max:W-120})}
function card(c,x,y,w,h){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,24);c.fillStyle='#fff';c.fill();c.restore()}
function foot(c,W,y){c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,y,W-120,2);T(c,'수급은 결과일 뿐 이후 주가를 보장하지 않아요. 공개 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다.',W/2,y+38,{s:19,w:600,c:MUT,a:'center',max:W-120});T(c,'모든 투자 판단과 책임은 투자자 본인에게 있어요 · 출처 네이버 증권 · stock.oky.kr',W/2,y+72,{s:19,w:700,c:'#94a3b8',a:'center',max:W-120})}
function pick(m,pk){return m.periods.indexOf(pk)>=0?String(pk):String(m.periods[m.periods.length-1])}
function panel(c,x,y,w,name,m){var acts=m.actors.slice(0,9),RH=62,h=96+acts.length*RH+30;card(c,x,y,w,h);c.fillStyle=GOLD;RR(c,x+26,y+26,6,30,3);c.fill();T(c,name,x+46,y+50,{s:28,w:900,c:INK});T(c,m.base_date+' 기준 · 5일 순매수(막대) · 1일·20일(숫자)',x+w-26,y+49,{s:16,w:500,c:'#94a3b8',a:'right'});
 var k5=pick(m,5),mx=1;acts.forEach(function(a){mx=Math.max(mx,Math.abs(a.p[k5]||0))});var bx=x+190,bw=w-190-250,mid=bx+bw/2;
 acts.forEach(function(a,i){var yy=y+84+i*RH,v=a.p[k5]||0;T(c,a.label,x+30,yy+30,{s:24,w:a.main?900:700,c:INK});c.fillStyle='#f1f5f9';RR(c,bx,yy+8,bw,34,8);c.fill();var L=Math.abs(v)*(bw/2)/mx;c.fillStyle=v>=0?UP:DN;if(v>=0)c.fillRect(mid,yy+8,L,34);else c.fillRect(mid-L,yy+8,L,34);c.fillStyle='#94a3b8';c.fillRect(mid-1,yy+4,2,42);
  T(c,fe(v),bx+bw+14,yy+34,{s:24,w:900,c:v>=0?UP:DN});T(c,'1일 '+fe(a.p[pick(m,1)])+' · 20일 '+fe(a.p[pick(m,20)]),x+w-24,yy+60,{s:15,w:600,c:MUT,a:'right'})});return h}
function lineChart(c,x,y,w,h,hist,title){card(c,x,y,w,h);c.fillStyle=GOLD;RR(c,x+26,y+26,6,30,3);c.fill();T(c,title,x+46,y+50,{s:28,w:900,c:INK});
 var keys=['retail','foreign','inst'],col={retail:'#f59e0b',foreign:'#3b82f6',inst:'#10b981'},nm={retail:'개인',foreign:'외국인',inst:'기관'};var m=hist,n=m.dates.length;
 var px=x+110,pw=w-150,py=y+96,ph=h-96-70;if(n<2){T(c,'2일 이상 자료가 쌓이면 그려져요',x+w/2,y+h/2,{s:22,w:600,c:'#94a3b8',a:'center'});return}
 var all=[0];keys.forEach(function(k){(m.cum[k]||[]).forEach(function(v){all.push(v)})});var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),pd=(hi-lo)*0.12||1;lo-=pd;hi+=pd;var X=function(i){return px+i*pw/(n-1)},Y=function(v){return py+ph*(hi-v)/(hi-lo)};
 for(var g=0;g<=4;g++){var v=lo+(hi-lo)*g/4,yy=Y(v);c.fillStyle='#e2e8f0';c.fillRect(px,yy,pw,1.5);T(c,fe(v).replace('+',''),px-10,yy+6,{s:16,w:600,c:MUT,a:'right'})}
 c.fillStyle='#64748b';c.fillRect(px,Y(0)-1,pw,2.5);
 keys.forEach(function(k){var d=m.cum[k];if(!d)return;c.strokeStyle=col[k];c.lineWidth=5;c.lineJoin='round';c.beginPath();d.forEach(function(v,i){if(i)c.lineTo(X(i),Y(v));else c.moveTo(X(i),Y(v))});c.stroke()});
 var st=Math.max(1,Math.floor(n/6));for(var i=0;i<n;i+=st)T(c,m.dates[i].slice(5).replace('-','.'),X(i),py+ph+32,{s:16,w:600,c:MUT,a:'center'});
 var lx=x+w/2-190;keys.forEach(function(k,i){c.fillStyle=col[k];c.fillRect(lx+i*130,y+h-34,22,10);T(c,nm[k],lx+i*130+30,y+h-24,{s:18,w:700,c:INK})})}
function dash(det,his,scale){var kp=det.markets.KOSPI,kq=det.markets.KOSDAQ,al=det.markets.ALL||kp||kq,W=1080;
 var ph=function(m){return m?96+Math.min(9,m.actors.length)*62+30:0},cl=his.markets.ALL||his.markets.KOSPI||his.markets.KOSDAQ;
 var H=210+30+120+30+(kp?ph(kp)+30:0)+(kq?ph(kq)+30:0)+(cl&&cl.dates.length>=2?400+30:0)+118;var mk=K.make(W,H,scale),c=mk.c;c.fillStyle=PAPER;c.fillRect(0,0,W,H);
 band(c,W,'MARKET FLOW','오늘의 시장 수급',det.base_date+' · 코스피·코스닥 투자자별 순매수 · 자료 '+det.days+'거래일');
 var y=240,vd=det.verdict,ac=(al?al.actors:[]).filter(function(a){return a.main});var tl=[];if(vd)tl.push(['외국인+기관 흐름',vd.text,vd.tone==='up'?UP:DN]);ac.forEach(function(a){tl.push([a.label+' 1일',fe(a.p['1']),a.p['1']>=0?UP:DN])});
 var tw=(W-100-16*(tl.length-1))/Math.max(1,tl.length);tl.forEach(function(t,i){var x=50+i*(tw+16);card(c,x,y,tw,120,18);T(c,t[0],x+tw/2,y+40,{s:20,w:700,c:MUT,a:'center'});T(c,t[1],x+tw/2,y+88,{s:t[1].length>6?30:36,w:900,c:t[2],a:'center',max:tw-16})});y+=150;
 if(kp){var h1=panel(c,50,y,W-100,'코스피',kp);y+=h1+30}if(kq){var h2=panel(c,50,y,W-100,'코스닥',kq);y+=h2+30}
 if(cl&&cl.dates.length>=2){lineChart(c,50,y,W-100,400,cl,(his.markets.ALL?'코스피+코스닥':(his.markets.KOSPI?'코스피':'코스닥'))+' 누적 순매수 (억원)');y+=430}
 foot(c,W,H-118);return mk.cv}
function aiCard(ai,date,scale){var W=1080,tmp=K.make(W,100,1).c,font='600 26px '+K.FONT,maxW=W-200,lines=[];
 String(ai).replace(/\r/g,'').replace(/\*\*/g,'').split('\n').forEach(function(l){var t=l.trim();if(!t||/^\[블로그\s*제목/.test(t))return;var h=/^#{1,4}\s*(.*)$/.exec(t);if(h){lines.push({h:1,t:h[1]});return}K.wrap(tmp,t.replace(/^[-•·*]\s*/,'• '),maxW,font).forEach(function(s){lines.push({t:s})})});
 if(!lines.length)return null;lines=lines.slice(0,34);var H=210+40+lines.length*42+90+100,mk=K.make(W,H,scale),c=mk.c;c.fillStyle=PAPER;c.fillRect(0,0,W,H);band(c,W,'AI COMMENT','AI 수급 해설',date+' · 참고용 요약');
 card(c,50,240,W-100,H-240-110,24);var y=290;lines.forEach(function(l){if(l.h){y+=8;T(c,l.t,100,y+26,{s:30,w:900,c:'#1e40af',max:maxW});y+=46}else{T(c,l.t,100,y+26,{s:26,w:600,c:'#1e293b',max:maxW});y+=42}});foot(c,W,H-100);return mk.cv}
window.MkImg={build:function(det,his,ai,scale){var out=[{idx:1,label:'시장 수급 대시보드',canvas:dash(det,his,scale)}];if(ai&&String(ai).trim()){var a=aiCard(ai,det.base_date,scale);if(a)out.push({idx:2,label:'AI 수급 해설 요약',canvas:a})}return out}};
})();

/* ── ⑧ 블로그 쓰기 ── */
function mkSecBlog(box){if(MEMBER_MODE)return;
 box.appendChild(el('p','note','수급 요약·일별 흐름·종목 상위·강세 테마·AI 해설로 블로그용 글(HTML)을 만들어요. 글은 자동으로 올라가지 않고, [복사하고 블로그 열기]로 복사한 뒤 블로그 글쓰기 화면에 붙여 넣는 방식이에요. ⑦에서 저장한 대시보드 이미지는 글 위쪽에 직접 올려 주세요.'));
 var bx=el('div');box.appendChild(bx);if(!window.BlogKit){bx.appendChild(el('p','note bad','블로그 도구(menu_blog.py)가 올라가지 않았어요.'));MK.blogPanel=null;return}
 var secs=[['stats','요약·수급 포인트'],['actors','주체별 순매수 표'],['flow','일별 흐름 표'],['stocks','종목 상위'],['themes','강세 테마'],['ai','AI해설']];
 MK.blogPanel=window.BlogKit.panel(bx,{idp:'mk',key:'market',kind:'market',ticker:'D'+mkStamp().slice(2),name:'시장수급 '+mkDate(),sections:secs,dup_warn:'',onBuilt:function(){MK.flag.blog=true;MK.flag.posted=false;mkSteps()},onCopied:function(){MK.flag.posted=true;mkSteps()},
  build:function(inc,title){return mkEnsure().then(function(){return apiJ('/admin/api/market/blog',{view:MK.view,days:Number(MK.days),ai:MK.ai.text||'',inc:inc,title:title})}).catch(function(e){return {error:(e&&e.message)||'만들지 못했어요'}})}});
 if(MK.flag.blog)MK.blogPanel.rebuild()}

/* ── 📘 읽는 법 ── */
function mkSecGuide(box){var g=el('div','mkGd');function H(t){g.appendChild(el('h4',null,t))}function P(t){g.appendChild(el('p',null,t))}function UL(a){var u=el('ul');a.forEach(function(x){u.appendChild(el('li',null,x))});g.appendChild(u)}
 H('이 메뉴는 무엇을 보여 주나요?');P('코스피·코스닥 시장에서 개인·외국인·기관이 하루 동안 얼마나 사고팔았는지(순매수)를 보여 주고, 최근 며칠의 흐름과 연속 일수, 종목별 상위, 강세 테마까지 한 곳에 모아 정리해요. “사라·팔라”는 뜻이 아니라 돈이 어디로 움직였는지를 보는 정보예요.');
 H('순매수·순매도란?');P('하루 동안 산 금액에서 판 금액을 뺀 값이에요. 플러스(+, 빨강)면 순매수, 마이너스(−, 파랑)면 순매도예요. 단위는 억원(1조 이상은 조)이에요. 개인·외국인·기관의 합은 기타 법인 등이 있어서 정확히 0은 아니에요.');
 H('화면 구성');UL(['① 오늘의 수급: 외국인+기관 흐름 판정(최근 5일 일평균 vs 20일 평균), 주체별 막대, 수급 포인트 문장','② 일별 흐름: 주체별 누적 순매수 선그래프와 일별 표(CSV 내려받기)','③ 주체별 상세: 기간별 합계·연속 일수·일평균·비중(세부 주체 자료가 있으면 함께)','④ 종목 상위: 외국인·기관·개인·쌍끌이 순매수/순매도 상위 종목(네이버 증권 링크)','⑤ 테마·지수: 오늘 강세·약세 네이버 테마와 코스피·코스닥 지수','⑥ AI 해설 → ⑦ 수급 이미지 → ⑧ 블로그 쓰기(관리자)']);
 H('자료는 어디서 오나요?');UL(['시장 전체: 네이버가 주는 개인·외국인·기관 순매수. 하루치만 주기 때문에 관리자가 가져올 때마다 하루씩 쌓여요(과거 날짜 조회가 되면 한꺼번에 채워요). 그래서 도입 직후에는 며칠치만 보일 수 있어요.','수집 종목 합산: 관리자가 [종목 수급 가져오기]로 받은 시가총액 상위 종목의 최근 20거래일 ‘순매수 수량×종가’를 날짜별로 더한 값이라 시장 전체와 차이가 있지만 20일 흐름이 바로 생겨요.','세부 주체(금융투자·보험·투신·사모·은행·연기금·기타금융·기타법인 등): 네이버가 세부 분류 주소를 닫아서, 관리자가 KRX 정보데이터시스템 표를 붙여 넣은 날만 나와요.','거래원(증권사 창구)은 종목 단위 자료라 이 메뉴에는 없어요.']);
 H('연속 일수·쌍끌이');UL(['연속 일수: 가장 최근 거래일부터 같은 방향이 며칠 이어졌는지예요.','쌍끌이: 외국인과 기관이 같은 기간 모두 순매수인 경우(동반 매도는 모두 순매도).','외국인+기관 흐름: 두 주체의 합산 일평균이 5일이 20일보다 매수 쪽(또는 매도 쪽)으로 강해졌는지 비교한 판정이에요.']);
 H('읽을 때 꼭 알아 두세요');UL(['수급은 결과일 뿐 원인이 아니고, 같은 수급이라도 이후 주가는 달라질 수 있어요.','하루·며칠 수급은 금방 바뀌어요. 길게 이어진 흐름과 함께 보세요.','이 화면은 정보 제공용이며 특정 종목의 매수·매도 권유가 아니에요. 투자 판단과 책임은 이용자 본인에게 있어요.']);box.appendChild(g)}

/* ── 관리자 전용: 가져오기·붙여넣기·점검 ── */
function mkAdmLoad(){var b=$('mkAdm');if(!b)return;api('/admin/api/market/diag').then(function(j){MK.diag=j;mkAdmDraw()})}
function mkFetchMk(then){var b0=$('mkColB0'),b2=$('mkFetchMkB');if(!MK.pd)MK.pd='20';
 [b0,b2].forEach(function(x){if(x)x.disabled=true});if(b0)b0.textContent='⏳ 시장 수급 가져오는 중…(10~40초)';
 function back(){if(b0){b0.textContent='📥 오늘 수급 가져오기';b0.disabled=!!(MK.job&&MK.job.running)}if(b2)b2.disabled=false}
 apiJ('/admin/api/market/fetch',{days:Number(MK.pd)}).then(function(z){back();
  var info=$('mkFetchInfo');if(info){info.innerHTML='';if(z.res)['KOSPI','KOSDAQ'].forEach(function(k){var x=z.res[k];if(!x)return;info.appendChild(el('p','note'+(x.ok?'':' bad'),MK_NM[k]+': '+(x.ok?('최신 '+x.latest+' · 이번에 '+x.added+'일 추가 · 쌓인 날짜 '+x.total+'일 · 주체 '+x.actors.join(', ')):x.error)))});if(z.error)info.appendChild(el('p','note bad',z.error))}
  if(z.ok){toast('시장 수급을 가져왔어요');MK.sum=null;MK.hist=null;MK.det=null;MK.flag.img=false;MK.flag.blog=false;MK.flag.posted=false;mkAdmLoad();api('/admin/api/market/summary?'+mkQ(mkQ0())).then(function(s){if(!s.error&&!s.empty){MK.sum=s;if(s.views&&s.views.indexOf(MK.view)<0)MK.view=s.views[0]}mkStatus();mkSteps();mkShow();
    if(then){then();return}if(window.MiniFlow)setTimeout(function(){MiniFlow.run('market',MKFLOW,MKACTS)},80)})}
  else{MK.chain=false;toast(z.error||'가져오지 못했어요')}}).catch(function(){back();MK.chain=false;toast('네트워크 오류')})}
function mkStartInv(chain){if(MK.job&&MK.job.running){toast('이미 가져오기가 실행 중이에요.');return}
 apiJ('/admin/api/collect/investor/start',{limit:Number(MK.lim),skip_today:!!MK.skip,with_theme:true}).then(function(z){if(z.error){toast(z.error);MK.chain=false;return}toast('종목 수급 가져오기를 시작했어요');MK.chain=!!chain;MK.jwas=true;mkJobPoll(true)})}
function mkAdmDraw(){var b=$('mkAdm');if(!b)return;var j=MK.diag;if(!MK.pd)MK.pd='20';
 var C=window.CBar.make(b,{title:'📥 자료 가져오기',btn:{label:'📥 오늘 수급 가져오기',id:'mkColB0',fn:function(){if(MK.job&&MK.job.running){toast('이미 가져오기가 실행 중이에요.');return}MK.chain=true;mkFetchMk(function(){mkStartInv(true)})}},
  stopId:'mkColB3',stopFn:function(){MK.chain=false;apiJ('/admin/api/collect/stop',{}).then(function(z){if(z.error){toast(z.error);return}toast('멈추는 중이에요…');mkJobPoll(true)})},stId:'mkColSt',pgId:'mkColPg'});
 if(!j||j.error){C.st.textContent='점검 정보를 읽지 못했어요.';return}
 var cnt=j.counts||{},ix=cnt.index&&(cnt.index.KOSPI||cnt.index.KOSDAQ);
 C.st.textContent=(j.last&&j.last.at)?('✅ 마지막 '+j.last.at+' · 시장 '+(ix?ix.rows:0)+'행 · 종목 '+(j.stocks==null?0:j.stocks)+'개(기준일 '+(j.stock_base||'-')+')'):'⚠ 아직 가져온 자료가 없어요 — 왼쪽 버튼을 한 번 눌러 주세요(시장 → 종목 순서로 이어서 받아요, 몇 분 걸려요).';
 var d=C.inn;
 /* 따로 받기 */
 d.appendChild(el('p','note','버튼을 따로 누르고 싶을 때만 쓰세요. 시장 수급은 하루 한 번이면 충분해요.'));
 var r=el('div','bar');mkSel(r,'가져올 기간',MK,'pd',[['20','최근 20일(가능한 만큼)'],['40','최근 40일'],['60','최근 60일']]);
 var b1=bt('📥 시장 수급만','bt3',function(){MK.chain=false;mkFetchMk()});b1.id='mkFetchMkB';r.appendChild(b1);d.appendChild(r);
 var fi=el('div');fi.id='mkFetchInfo';d.appendChild(fi);
 var cr=el('div','bar');mkSel(cr,'가져올 종목',MK,'lim',[['0','전종목(코스피+코스닥)'],['2000','시총 상위 2000'],['1000','시총 상위 1000'],['500','시총 상위 500'],['300','시총 상위 300'],['200','시총 상위 200'],['100','시총 상위 100']]);
 var lb=el('label');lb.style.fontSize='12.5px';var ck=el('input');ck.type='checkbox';ck.checked=!!MK.skip;ck.onchange=function(){MK.skip=ck.checked};lb.appendChild(ck);lb.appendChild(document.createTextNode(' 오늘 이미 가져온 종목은 건너뛰기(이어서 하기)'));cr.appendChild(lb);
 var c1=bt('📥 종목 수급만','bt3',function(){MK.chain=false;mkStartInv(false)});c1.id='mkColB1';cr.appendChild(c1);d.appendChild(cr);
 var li=el('div');li.id='mkColLast';d.appendChild(li);mkJobDraw();
 /* 세부 주체 붙여넣기(접힘) */
 var pd=document.createElement('details');var ps=document.createElement('summary');ps.textContent='📋 세부 주체(금융투자·보험·투신·연기금 …) 직접 붙여넣기';pd.appendChild(ps);var pc=el('div','mkCard');
 pc.appendChild(el('p','note','KRX 정보데이터시스템(data.krx.co.kr) → 통계 → 투자자별 매매동향(거래실적)에서 표를 복사해 붙여 넣으세요. 두 모양을 읽어요: ① 세로형(투자자구분 | 매도 | 매수 | 순매수, 하루치 — 아래 날짜 칸 사용) ② 가로형(날짜 | 개인 | 외국인 | 금융투자 | … , 날짜마다 한 줄). 같은 날짜·주체는 덮어써요.'));
 var P={market:'KOSPI',unit:'won',date:mkDate()};var pr=el('div','bar');mkSel(pr,'시장',P,'market',[['KOSPI','코스피'],['KOSDAQ','코스닥']]);mkSel(pr,'금액 단위',P,'unit',[['won','원(KRX 기본)'],['mil','백만원'],['eok','억원']]);
 var dl=el('label','mkL');dl.appendChild(el('span',null,'날짜(세로형일 때)'));var di=el('input');di.type='date';di.value=P.date;di.onchange=function(){P.date=di.value};dl.appendChild(di);pr.appendChild(dl);pc.appendChild(pr);
 var ta=el('textarea','mkTa');ta.id='mkPasteTa';ta.placeholder='여기에 표를 붙여 넣으세요 (Ctrl+V)';pc.appendChild(ta);var pb=el('div','bar');var pi=el('div');
 pb.appendChild(bt('💾 붙여넣은 표 저장','bt',function(){apiJ('/admin/api/market/paste',{market:P.market,unit:P.unit,date:P.date,text:ta.value}).then(function(z){pi.innerHTML='';if(z.error){pi.appendChild(el('p','note bad','⚠ '+z.error+((z.unknown&&z.unknown.length)?' (읽지 못한 이름: '+z.unknown.join(', ')+')':'')));return}
  pi.appendChild(el('p','note',MK_NM[z.market]+' '+z.days+'일 저장 · 주체 '+z.actors.join(', ')+(z.unknown&&z.unknown.length?' · 읽지 못한 이름 '+z.unknown.join(', '):'')));toast('세부 주체를 저장했어요');ta.value='';MK.sum=null;MK.hist=null;MK.det=null;mkAdmLoad();mkShow()})}));pc.appendChild(pb);pc.appendChild(pi);pd.appendChild(pc);d.appendChild(pd);
 /* 점검·지우기 */
 var c=cnt,SN={index:'시장 전체(네이버)',univ:'수집 종목 합산',paste:'붙여넣은 세부 주체'},lines=[];Object.keys(SN).forEach(function(s){var q=c[s];if(!q){lines.push(SN[s]+': 없음');return}lines.push(SN[s]+': '+Object.keys(q).map(function(m){return MK_NM[m]+' '+q[m].from+'~'+q[m].to+'('+q[m].rows+'행)'}).join(' · '))});
 d.appendChild(el('p','note',lines.join('  |  ')));d.appendChild(el('p','note','종목 수급 '+(j.stocks==null?'-':j.stocks)+'종목(기준일 '+(j.stock_base||'-')+') · 네이버 테마 '+(j.themes==null?'-':j.themes)+'개 · 저장된 AI 해설 '+(j.ai_date||'없음')));
 var dr=el('div','bar');Object.keys(SN).forEach(function(s){if(!c[s])return;dr.appendChild(bt('🗑 '+SN[s]+' 지우기','bt3',function(){if(!confirm(SN[s]+' 자료를 모두 지울까요?'))return;apiJ('/admin/api/market/delete',{src:s}).then(function(z){if(z.error){toast(z.error);return}toast('지웠어요');MK.sum=null;MK.hist=null;MK.det=null;mkAdmLoad();mkShow()})}))});d.appendChild(dr)}
function mkJobPoll(keep){api('/admin/api/collect/status').then(function(j){if(j.error||!$('mkColPg'))return;MK.job=(j.job||{});MK.jall=j;mkJobDraw();var run=!!(MK.job&&MK.job.running);
  if(run){MK.jwas=true;if(MK.jtm)clearTimeout(MK.jtm);MK.jtm=setTimeout(function(){mkJobPoll(true)},1500)}else if(MK.jwas){MK.jwas=false;var chn=MK.chain,okE=!(MK.job&&MK.job.error);MK.chain=false;MK.st.data=null;MK.sum=null;MK.hist=null;MK.det=null;mkAdmLoad();mkShow();if(chn&&okE&&window.MiniFlow)mkEnsure().then(function(){mkSteps();setTimeout(function(){MiniFlow.run('market',MKFLOW,MKACTS)},80)}).catch(function(){})}})}
function mkJobDraw(){var pg=$('mkColPg'),ls=$('mkColLast');var jb=MK.job||{},j=MK.jall||{},LI=j.last_inv||{},T=j.tables||{};['mkColB0','mkColB1','mkFetchMkB'].forEach(function(id){var x=$(id);if(x)x.disabled=!!jb.running});var st=$('mkColB3');if(st)st.disabled=!jb.running;
 if(pg){pg.innerHTML='';if((jb.running||jb.phase==='end')&&jb.kind!=='theme'){var pct=jb.total?Math.min(100,Math.round(jb.done*100/jb.total)):0;pg.appendChild(el('div','m',(jb.running?'⏳ ':'')+'수급 가져오기 — '+(jb.msg||'')+(jb.total?' ('+jb.done+'/'+jb.total+', '+pct+'%)':'')+(jb.cur?' · '+jb.cur:'')+(jb.fail?' · 실패 '+jb.fail:'')+' · '+jb.elapsed+'초'));
   var w=el('div','mkPg'),f=document.createElement('div');f.style.width=(jb.running?Math.max(3,pct):(jb.error?0:100))+'%';if(jb.error)f.style.background='#f87171';w.appendChild(f);pg.appendChild(w);if(jb.error)pg.appendChild(el('p','note bad','⚠ '+jb.error))}}
 if(ls){ls.innerHTML='';ls.appendChild(el('p','note',LI.at?('마지막: '+LI.at+' · '+LI.ok+'종목 · 기준일 '+(LI.base_date||'-')+(LI.skip?' · 건너뜀 '+LI.skip:'')+(LI.fail?' · 실패 '+LI.fail:'')):'종목 수급: 아직 가져온 적 없어요'));ls.appendChild(el('p','note','표 현황 — 수급 '+(T.investor_scan_cache==null?'-':T.investor_scan_cache)+'행 · 시세 '+(T.stock_price_cache==null?'-':T.stock_price_cache)+'행'))}}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.prog_declare("market/fetch", "시장수급 가져오기")
    C.register_menu({"id": MENU, "label": "시장수급", "icon": "📊", "public_path": "/m/market", "admin_path": "/admin#mk",
                     "desc": "코스피·코스닥의 그날 수급을 개인·외국인·기관(가능하면 금융투자·연기금 등 세부 주체까지)별로 보여 주고, 최근 흐름·연속 일수·종목별 상위·강세 테마를 한 화면에 정리해요. 정보 제공용이며 투자 권유가 아니에요.",
                     "access": "admin"})
    C.register_prompt("market_ai", {
        "title": "시장수급 AI 프롬프트", "default": MK_DEFAULT, "required": ["{summary}"], "must_have": [],
        "vars": "{summary}=시장·주체별 수급 요약(필수) · {period_str}=기간 · {base_date}=기준일 · {today}=오늘 날짜",
        "desc": "시장수급 화면의 [AI 프롬프트 만들기]가 AI에게 보내는 요청문. 매수·매도 권유를 하지 않도록 쓰는 것이 원칙이에요."})
    C.register_admin_tab("mk", "📊 시장수급", TAB_JS, "mkLoad", menu=MENU)
    C.register_flow(MENU, "📊 시장수급", "① 시장 수급 가져오기(직접 시작)", [
        {"id": "ai", "label": "② AI 해설", "desc": "수급을 가져오면 AI 요청문 창을 자동으로 열어요. AI 답변을 복사해 돌아오면 저장되고 다음 단계로 이어져요(오늘 저장한 AI 해설이 있으면 건너뛰어요)."},
        {"id": "img", "label": "③ 수급 대시보드 이미지", "desc": "AI 단계가 끝나면 블로그용 수급 대시보드 이미지를 자동으로 그려요(저장은 [⚙ 저장 설정]의 자동/수동 설정을 따라요)."},
        {"id": "blog", "label": "④ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요."},
        {"id": "post", "label": "⑤ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요. 브라우저가 복사·새 창을 막으면 [📋 복사하고 블로그 열기]를 한 번 눌러 주세요."}])
    F = C.register_feature
    F(MENU, "sum", "오늘의 수급 요약", "코스피·코스닥 개인·외국인·기관 순매수(1·5·20일), 외국인+기관 흐름 판정, 수급 포인트 문장", default="public", endpoints=["/admin/api/market/summary"])
    F(MENU, "guide", "수급 읽는 법", "순매수·연속 일수·쌍끌이 등 용어와 자료 출처 해설(서버 호출 없음)", default="public", endpoints=[])
    F(MENU, "detail", "주체별 상세", "세부 주체(금융투자·투신·연기금 등)까지 포함한 기간별 순매수, 연속 일수, 5일·20일 일평균 페이스", default="member", endpoints=["/admin/api/market/detail"])
    F(MENU, "flow", "일별 흐름·누적 그래프", "주체별 일별 순매수 표와 누적 순매수 선그래프", default="member", endpoints=["/admin/api/market/history"])
    F(MENU, "stocks", "종목별 수급 상위", "외국인·기관·개인·쌍끌이 종목의 순매수/순매도 상위(1·5·20일)", default="member", endpoints=["/admin/api/market/stocks"])
    F(MENU, "extra", "강세 테마·지수", "오늘 강세·약세 네이버 테마와 코스피·코스닥 지수", default="member", endpoints=["/admin/api/market/extra"])
    F(MENU, "ai", "AI 수급 해설", "수급 요약으로 AI 프롬프트를 만들고 답변을 붙여 보기(수동 — 서버가 AI를 부르지 않아요)", default="L2", endpoints=["/admin/api/market/prompt"], kind="action")
    F(MENU, "img", "수급 이미지 내려받기", "수급 요약을 대시보드·누적 그래프 이미지로 그려 내려받아요", default="L2", endpoints=[], kind="tool")
    F(MENU, "exp", "표 내려받기", "지금 보는 표를 CSV 파일로 내려받기", default="L2", endpoints=[], kind="action")
    # 가져오기(fetch)·세부 주체 붙여넣기(paste)·자료 지우기(delete)·AI 저장(ai POST/GET)·블로그 글(blog)·점검(diag)은 관리자 업무 → 어떤 기능에도 넣지 않았다(회원 화면에서는 404).
    return bp
