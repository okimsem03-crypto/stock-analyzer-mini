"""⚡ 초단기 후보 (장 시작 전) — 관리자 전용 · 참고 자료 (투자 권유 아님)

[무엇을 하나요]
  오늘추천이 저장해 둔 가장 최근 스캔(전일 종가 기준)에 '시장 흐름·수급·테마·뉴스'를 겹쳐서,
  오늘 장 초반 단기 매매에서 살펴볼 만한 후보를 규칙으로 골라요. AI 없이도 돌아가고, 근거가 숫자로 남아요.

  ① 장 환경(게이트)   미국 증시(나스닥·S&P)·VIX·원/달러로 '공격 / 중립 / 관망 / 휴식'을 정해 추천 개수와 기준 점수를 조절
  ② 종목 점수(100점)  수급 30 · 거래·가격 모멘텀 25 · 추세 위치 20 · 테마 15 · 뉴스 10
  ③ 진입·손절·목표    전일 종가 기준 호가 단위로 계산(손익비 1:2), 갭 상승이 크면 추격 금지
  ④ 성과 확인         다음 거래일의 시가·고가·저가·종가로 '규칙대로 했다면'을 기록 → 승률·평균 손익으로 가중치를 점검

[데이터]
  dly_pick(스캔) · investor_scan_cache(수급) · collect_theme_list / theme_day / stock_theme_map(테마) · 네이버 뉴스 제목 · 거시 지표
  자료가 없으면 그 항목은 중립 점수로 두고 화면에 '자료 없음'을 표시해요(없는 값을 지어내지 않아요).

[한계] 뉴스는 제목만 보고, 장중 수급·호가·프로그램 매매는 보지 않아요. 수수료·거래세·체결 오차는 성과에 반영되지 않아요.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from flask import Blueprint, request
from menu_ctx import C
import menu_daily as D

bp = Blueprint("scalp", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_dbrows", "_cache_get", "_cache_set", "_now_kst",
               "setting_get", "setting_set", "_naver_news", "_fetch_ohlcv")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

# ── 점수 비중(합 100) ──
W_FLOW, W_MOM, W_TREND, W_THEME, W_NEWS = 30, 25, 20, 15, 10
KEEP = 20                      # 저장·표시하는 순위 수
MIN_CAP_EOK = 1000             # 유동성 하한(시총 억원) — 이보다 작으면 체결이 불리해 제외
MIN_PRICE = 1000               # 동전주 제외
NEWS_TOP = 30                  # 뉴스는 중간 순위 상위 N개만 조회(시간 절약)
GATE_TABLE = [                 # (이름, 추천 개수, 기준 점수)
    ("공격 가능", 8, 60), ("중립", 5, 65), ("관망·보수적", 3, 72), ("휴식 권장", 0, 80)]

POS_WORDS = ("수주", "계약 체결", "공급 계약", "단독 공급", "공급계약", "승인", "허가", "흑자", "최대 실적", "사상 최대", "호실적", "어닝 서프라이즈", "실적 개선",
             "신제품", "인수", "mou", "양산", "특허", "투자 유치", "목표가 상향", "목표주가 상향", "자사주 매입", "자사주 소각", "배당 확대", "정부 지원", "정책 수혜", "수혜")
NEG_WORDS = ("유상증자", "전환사채", "신주인수권", "신주 발행", "감자", "적자", "소송", "리콜", "목표가 하향", "목표주가 하향", "하향", "불성실", "공매도", "오버행",
             "블록딜", "대규모 손실", "손실 확대", "계약 해지", "계약 취소", "철회", "중단")
DANGER_WORDS = ("상장폐지", "횡령", "배임", "거래정지", "감사의견", "관리종목", "불성실공시", "회생", "파산", "부도")


def _f(v, d=None):
    return D._f(v, d)


def _cl(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


# ══════════════════════════════════════════════════════════════
# 호가 단위 · 거래일
# ══════════════════════════════════════════════════════════════
def tick_size(p):
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < lim:
            return t
    return 1000


def tick_round(p, mode="nearest"):
    t = tick_size(p)
    q = p / t
    n = int(q) if mode == "down" else (int(q) + (0 if q == int(q) else 1) if mode == "up" else int(round(q)))
    return int(n * t)


def _is_bizday(d):
    return d.weekday() < 5


def target_session_date(now=None):
    """이 목록이 쓰일 거래일(YYYY-MM-DD). 평일 16시 전이면 오늘, 아니면 다음 평일. (공휴일은 알지 못해요)"""
    now = now or _now_kst()
    d = now.date()
    if not _is_bizday(d) or now.hour >= 16:
        d = d + timedelta(days=1)
        while not _is_bizday(d):
            d = d + timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def prev_bizday(ds):
    from datetime import datetime
    d = datetime.strptime(ds, "%Y-%m-%d").date() - timedelta(days=1)
    while not _is_bizday(d):
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
# ① 장 환경(게이트) — 순수 함수
# ══════════════════════════════════════════════════════════════
def gate_from_macro(rows):
    """rows: [{name, close, pct}]. 반환 {score, label, n_main, min_score, parts:[(이름,점수,설명)], missing}"""
    m = {r["name"]: r for r in (rows or []) if r.get("name")}
    parts, g = [], 0.0
    us = [m[k]["pct"] for k in ("나스닥", "S&P500") if k in m and m[k].get("pct") is not None]
    if us:
        avg = sum(us) / len(us)
        v = _cl(avg / 1.0, -2.0, 2.0)
        g += v
        parts.append(("미국 증시", round(v, 1), f"나스닥·S&P500 평균 {avg:+.2f}%"))
    vx = m.get("VIX(변동성)")
    if vx:
        lv, pc = _f(vx.get("close")), vx.get("pct")
        v = 0.0
        if lv is not None and lv > 30:
            v -= 2.0
        elif lv is not None and lv > 25:
            v -= 1.0
        if pc is not None and pc >= 10:
            v -= 1.0
        elif pc is not None and pc <= -5 and lv is not None and lv < 20:
            v += 0.5
        g += v
        parts.append(("변동성(VIX)", round(v, 1), f"VIX {vx.get('close')}" + (f" ({pc:+.1f}%)" if pc is not None else "")))
    fx = m.get("원/달러")
    if fx and fx.get("pct") is not None:
        pc = fx["pct"]
        v = -1.0 if pc >= 0.7 else (0.5 if pc <= -0.5 else 0.0)
        g += v
        parts.append(("원/달러", round(v, 1), f"{fx.get('close')} ({pc:+.2f}%)"))
    missing = not parts
    if g >= 1.0:
        idx = 0
    elif g > -1.0:
        idx = 1
    elif g > -2.5:
        idx = 2
    else:
        idx = 3
    name, n_main, min_score = GATE_TABLE[idx]
    return {"score": round(g, 1), "label": name, "n_main": n_main, "min_score": min_score, "parts": parts, "missing": missing}


# ══════════════════════════════════════════════════════════════
# ② 종목 점수 — 순수 함수
# ══════════════════════════════════════════════════════════════
def score_flow(r):
    """수급(0~30). 전일(1일)·5일 외국인+기관 순매수를 시총 대비 %로 본다. 자료가 없으면 None."""
    cap = max(float(r.get("cap_eok") or 0), 100.0)
    f1, i1, f5, i5 = r.get("f1"), r.get("i1"), r.get("f5"), r.get("i5")
    if f5 is None or i5 is None:
        return None, []
    why = []
    x5 = (f5 + i5) / cap * 100.0
    c5 = _cl(x5 / 0.5)
    if f1 is not None and i1 is not None:
        x1 = (f1 + i1) / cap * 100.0
        c1 = _cl(x1 / 0.15)
        raw = 0.5 * c1 + 0.5 * c5
        if f1 > 0 and i1 > 0:
            why.append(f"전일 외국인·기관 동반 순매수({f1 + i1:+,.0f}억)")
        elif f1 + i1 > 0:
            why.append(f"전일 외국인·기관 합산 순매수({f1 + i1:+,.0f}억)")
        elif f1 + i1 < 0:
            why.append(f"전일 외국인·기관 합산 순매도({f1 + i1:+,.0f}억)")
    else:
        raw = c5
    if f5 > 0 and i5 > 0:
        why.append(f"5일 쌍끌이 순매수({f5 + i5:+,.0f}억)")
    elif (f5 + i5) > 0:
        why.append(f"5일 합산 순매수({f5 + i5:+,.0f}억)")
    else:
        why.append(f"5일 합산 순매도({f5 + i5:+,.0f}억)")
    flags = r.get("flags") or []
    bonus = 3 if ("쌍끌이" in flags or "수급전환" in flags) else 0
    if "수급전환" in flags:
        why.append("수급 전환(최근 순매수로 돌아섬)")
    pts = W_FLOW / 2.0 + (W_FLOW / 2.0) * raw + bonus
    return max(0.0, min(float(W_FLOW), pts)), why


def score_momentum(r):
    """거래·가격 모멘텀(0~25): 거래량 배수(최대 14) + 전일 등락(최대 11). 너무 올랐으면(과열) 점수를 깎는다."""
    why, warns = [], []
    vr = r.get("vr")
    vp = 0.0
    if vr is not None:
        vp = _cl((vr - 0.8) / 1.7, 0.0, 1.0) * 14.0
        if vr >= 2.0:
            why.append(f"거래량 평균의 {vr:.1f}배(거래 급증)")
        elif vr >= 1.3:
            why.append(f"거래량 평균의 {vr:.1f}배")
    else:
        vp = 5.0
    day = r.get("day_pct")
    if day is None:
        pp = 5.0
    elif 1 <= day <= 6:
        pp = 11.0
        why.append(f"전일 {day:+.1f}% 상승(건강한 상승 구간)")
    elif 6 < day <= 12:
        pp = 8.0
        why.append(f"전일 {day:+.1f}% 강한 상승")
    elif 12 < day <= 20:
        pp = 3.0
        warns.append(f"전일 {day:+.1f}% 급등 — 추격 위험")
    elif day > 20:
        pp = 0.0
        warns.append(f"전일 {day:+.1f}% (상한가권) — 오늘 추격 어려움")
    elif 0 <= day < 1:
        pp = 6.0
    elif -3 <= day < 0:
        pp = 4.0
    else:
        pp = 1.0
        warns.append(f"전일 {day:+.1f}% 하락")
    return min(25.0, vp + pp), why, warns


def score_trend(r):
    """추세 위치(0~20): 이평 배열(8) + 52주 위치(8) + RSI(4). RSI 과열이면 경고."""
    why, warns = [], []
    pts = 0.0
    al = r.get("align") or ""
    if al == "정배열":
        pts += 8
        why.append("이동평균 정배열")
    elif al == "혼재":
        pts += 3
    p52 = r.get("pos52")
    if p52 is not None:
        if 98 < p52:
            pts += 6
            why.append("52주 신고가 부근")
            warns.append("52주 고점권 — 돌파 후 눌림 여부 확인")
        elif 70 <= p52 <= 98:
            pts += 8
            why.append(f"52주 상단권({p52:.0f}%) — 고점 돌파 시도 구간")
        elif 50 <= p52 < 70:
            pts += 5
        elif p52 >= 30:
            pts += 2
        else:
            pts += 1
    rsi = r.get("rsi")
    if rsi is not None:
        if 50 <= rsi <= 68:
            pts += 4
        elif 68 < rsi <= 75:
            pts += 2
            warns.append(f"RSI {rsi:.0f} — 다소 과열")
        elif rsi > 75:
            warns.append(f"RSI {rsi:.0f} — 과열(눌림 가능성)")
        elif rsi >= 40:
            pts += 2
        else:
            pts += 1
    return min(20.0, pts), why, warns


def score_theme(th):
    """테마(0~15). th: {name, rate, breadth, days_strong} 또는 None(자료 없음 → 중립 5)."""
    if not th:
        return 5.0, [], [], False
    r, b, d = th.get("rate") or 0.0, th.get("breadth"), th.get("days_strong") or 0
    b = 0.5 if b is None else b
    if r >= 3 and b >= 0.65:
        p = 15.0
    elif r >= 1.5 and b >= 0.55:
        p = 10.0
    elif r >= 0.5:
        p = 6.0
    elif r >= 0:
        p = 3.0
    else:
        p = 0.0
    why, warns = [], []
    if p >= 6:
        why.append(f"테마 ‘{th['name']}’ 강세({r:+.1f}%, 상승종목 {b * 100:.0f}%)")
    if d >= 4:
        p -= 5
        warns.append(f"테마 ‘{th['name']}’ {d}일째 강세 — 과열 주의")
    elif d in (1, 2) and r >= 1.5:
        p += 2
        why.append("테마 강세 초기(1~2일차)")
    return max(0.0, min(float(W_THEME), p)), why, warns, True


def classify_news(items, now, hours=48):
    """뉴스 제목 분류. items: [{title, datetime}] → (pts 0~10, why, warns, danger)."""
    cut = (now - timedelta(hours=hours)).strftime("%Y%m%d%H%M")
    pos = neg = 0
    danger = []
    seen = set()
    for it in items or []:
        if str(it.get("datetime") or "") < cut:
            continue
        t = str(it.get("title") or "")
        key = re.sub(r"\s+", "", t)[:24]
        if key in seen:
            continue
        seen.add(key)
        tl = t.lower()
        if any(w in t for w in DANGER_WORDS):
            danger.append(t)
        if any(w in tl for w in POS_WORDS):
            pos += 1
        if any(w in t for w in NEG_WORDS):
            neg += 1
    why, warns = [], []
    pts = 4.0
    pts += min(6.0, pos * 3.0) - neg * 4.0
    if pos:
        why.append(f"최근 2일 호재성 뉴스 {pos}건(제목 기준)")
    if neg:
        warns.append(f"최근 2일 악재성 뉴스 {neg}건(제목 기준)")
    if danger:
        warns.append("위험 키워드 뉴스: " + danger[0][:40])
    return max(0.0, min(float(W_NEWS), pts)), why, warns, bool(danger)


def levels(price, cap_eok):
    """전일 종가 기준 진입·손절·목표(호가 단위). 대형주는 좁게, 소형주는 넓게. 손익비 1:2."""
    if not price or price <= 0:
        return None
    cap = cap_eok or 0
    stop_pct = 2.0 if cap >= 10000 else (2.5 if cap >= 3000 else 3.0)
    lo = tick_round(price * 1.000, "up")
    hi = tick_round(price * 1.020, "down")
    entry_mid = (lo + hi) / 2.0
    return {"entry_lo": lo, "entry_hi": max(hi, lo), "chase": tick_round(price * 1.05, "down"),
            "stop": tick_round(entry_mid * (1 - stop_pct / 100.0), "down"), "stop_pct": stop_pct,
            "target": tick_round(entry_mid * (1 + stop_pct * 2 / 100.0), "up"), "target_pct": stop_pct * 2,
            "gap_floor": tick_round(price * 0.98, "up")}


def prelim(r, th):
    """뉴스 이전 점수(수급·모멘텀·추세·테마). 반환 dict 또는 None(제외)."""
    price = r.get("price")
    cap = r.get("cap_eok") or 0
    if not price or price < MIN_PRICE:
        return None
    if cap and cap < MIN_CAP_EOK:
        return None
    day = r.get("day_pct")
    if day is not None and day >= 25:
        return None            # 상한가권은 장 초반 진입 자체가 어려워 후보에서 뺀다
    if day is not None and day <= -8:
        return None
    parts, why, warns, miss = {}, [], [], []
    fl, w = score_flow(r)
    if fl is None:
        fl = W_FLOW * 0.4
        miss.append("수급")
        warns.append("수급 자료 없음 — 시장수급 [가져오기] 후 다시 만드세요")
    else:
        why += w
    parts["flow"] = fl
    mo, w, wr = score_momentum(r)
    parts["mom"] = mo
    why += w
    warns += wr
    tr, w, wr = score_trend(r)
    parts["trend"] = tr
    why += w
    warns += wr
    tp, w, wr, ok = score_theme(th)
    parts["theme"] = tp
    why += w
    warns += wr
    if not ok:
        miss.append("테마")
    return {"parts": parts, "why": why, "warns": warns, "miss": miss}


def finalize(base, news_pts, news_why, news_warns, danger, has_news):
    parts = dict(base["parts"])
    parts["news"] = news_pts if has_news else W_NEWS * 0.4
    total = sum(parts.values())
    why = base["why"] + news_why
    warns = base["warns"] + news_warns
    miss = list(base["miss"]) + ([] if has_news else ["뉴스"])
    if danger:
        return None
    return {"score": int(round(total)), "parts": {k: round(v, 1) for k, v in parts.items()}, "why": why, "warns": warns, "miss": miss}


# ══════════════════════════════════════════════════════════════
# 자료 모으기
# ══════════════════════════════════════════════════════════════
def _ensure_tables(c, use_pg):
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    c.execute(f"CREATE TABLE IF NOT EXISTS dly_scalp(scalp_date TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', rk INTEGER NOT NULL DEFAULT 0, "
              f"main INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0, gate TEXT NOT NULL DEFAULT '', base_price {real}, stop_pct {real}, target_pct {real}, "
              f"o_next {real}, h_next {real}, l_next {real}, c_next {real}, result TEXT NOT NULL DEFAULT '', eval_at TEXT NOT NULL DEFAULT '', "
              f"PRIMARY KEY(scalp_date, ticker))")


def _theme_ctx(now):
    """테마 자료 → ({ticker: [테마이름…]}, {이름: 정보}, 경고글). 비어 있어도 오류 없이 빈 값."""
    info, tmap, note = {}, {}, ""
    try:
        rows = _dbx("SELECT no,name,change_rate,rise,fall,steady,fetched_at FROM collect_theme_list", fetch=True) or []
    except Exception:
        rows = []
    if not rows:
        return tmap, info, "테마 자료가 없어요 — [🏷 테마 가져오기]를 먼저 해 두면 테마 점수가 반영돼요."
    hist = {}
    try:
        cut = (now - timedelta(days=20)).strftime("%Y-%m-%d")
        for d, no, rate in (_dbx("SELECT date,no,rate FROM theme_day WHERE date>=? ORDER BY date", (cut,), fetch=True) or []):
            hist.setdefault(int(no), []).append((str(d), _f(rate, 0.0) or 0.0))
    except Exception:
        pass
    newest = ""
    for no, name, rate, rise, fall, steady, fa in rows:
        newest = max(newest, str(fa or ""))
        rise, fall = int(_f(rise, 0) or 0), int(_f(fall, 0) or 0)
        h = sorted(hist.get(int(no), []), reverse=True)
        n = 0
        for _, rt in h:
            if rt >= 2.0:
                n += 1
            else:
                break
        info[name] = {"no": int(no), "name": name, "rate": _f(rate, 0.0) or 0.0, "rise": rise, "fall": fall,
                      "breadth": (rise / float(rise + fall)) if (rise + fall) > 0 else None, "days_strong": n}
    try:
        for tk, th in (_dbx("SELECT ticker,theme FROM stock_theme_map WHERE theme_type='naver'", (), fetch=True) or []):
            tmap.setdefault(str(tk).zfill(6), []).append(th)
    except Exception:
        pass
    if newest and str(newest)[:10] < (now - timedelta(days=4)).strftime("%Y-%m-%d"):
        note = f"테마 자료가 {str(newest)[:10]} 것이라 오래됐어요 — [🏷 테마 가져오기]로 새로 받으면 더 정확해요."
    return tmap, info, note


def best_theme(ticker, tmap, info):
    best, key = None, -99.0
    for nm in tmap.get(ticker, []):
        t = info.get(nm)
        if not t:
            continue
        k = t["rate"] + 3.0 * ((t["breadth"] if t["breadth"] is not None else 0.5) - 0.5)
        if k > key:
            best, key = t, k
    return best


def _cap_of(r):
    m = re.sub(r"[^0-9]", "", str(r.get("cap") or ""))
    return int(m) if m else 0


def _news_for(tk, now):
    hit = _cache_get(("scalp_news", tk))
    if hit is not None:
        return hit
    try:
        items = _naver_news(tk) or []
    except Exception:
        items = []
    _cache_set(("scalp_news", tk), items, 1800)
    return items


# ══════════════════════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════════════════════
def build(scan_date=None):
    now = _now_kst()
    target = target_session_date(now)
    dates = D._dates(60)
    if not dates:
        return {"error": "저장된 스캔이 없어요. 먼저 [🌟 오늘추천]에서 스캔하세요."}
    scan_date = scan_date or dates[0]["date"]
    rows, src = D.load_rows(scan_date)
    if not rows:
        return {"error": f"{scan_date} 스캔 자료가 비어 있어요."}
    warns = []
    want_last = prev_bizday(target)
    stale = scan_date < want_last
    if stale:
        warns.append(f"가장 최근 스캔이 {scan_date}라서 직전 거래일({want_last}) 기준이 아니에요. [🌟 오늘추천]에서 새로 스캔한 뒤 다시 만드세요.")
    if src == "orig":
        warns.append("원본 프로그램 기록으로 만든 목록이라 수급(1일) 자료가 없을 수 있어요.")
    if len(rows) < 80:
        warns.append(f"스캔 저장 종목이 {len(rows)}개뿐이라 후보 폭이 좁아요. [⚙ 옵션]에서 저장 개수를 늘리고 최소 점수를 낮춰 스캔하면 더 넓게 볼 수 있어요.")
    risk = D.risk_set()
    for r in rows:
        r["cap_eok"] = _cap_of(r)
    pool = [r for r in rows if r["ticker"] not in risk]

    try:
        mac = D.macro_snapshot()
    except Exception:
        mac = {"text": "", "rows": []}
    gate = gate_from_macro(mac.get("rows"))
    if gate["missing"]:
        warns.append("거시 지표(미국 증시·VIX·환율)를 받지 못해 장 환경은 ‘중립’으로 두었어요.")

    tmap, info, tnote = _theme_ctx(now)
    if tnote:
        warns.append(tnote)

    # 1차 점수 → 상위만 현재가 갱신·뉴스
    pre = []
    for r in pool:
        th = best_theme(r["ticker"], tmap, info)
        b = prelim(r, th)
        if b:
            pre.append((sum(b["parts"].values()), r, th, b))
    pre.sort(key=lambda x: -x[0])
    head = pre[:60]
    try:
        live = D.live_prices([x[1]["ticker"] for x in head])
    except Exception:
        live = {}
    refreshed = []
    for _, r, th, b in head:
        lv = live.get(r["ticker"])
        if lv and lv[0]:
            r = dict(r, price=lv[0], day_pct=lv[1] if lv[1] is not None else r.get("day_pct"))
        b2 = prelim(r, th)
        if b2:
            refreshed.append((sum(b2["parts"].values()), r, th, b2))
    refreshed.sort(key=lambda x: -x[0])
    top = refreshed[:NEWS_TOP]
    news = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_news_for, r["ticker"], now): r["ticker"] for _, r, _, _ in top}
        t_end = time.time() + 30
        try:
            for f in as_completed(futs, timeout=max(1, t_end - time.time())):
                try:
                    news[futs[f]] = f.result()
                except Exception:
                    pass
        except Exception:
            warns.append("뉴스 조회가 오래 걸려 일부 종목은 뉴스 점수를 중립으로 두었어요.")
    out = []
    for _, r, th, b in top:                     # 뉴스까지 확인한 상위 종목만 최종 후보로 삼는다(위험 뉴스 확인 누락 방지)
        tk = r["ticker"]
        has = tk in news
        if has:
            npts, nw, nwr, dg = classify_news(news[tk], now)
        else:
            npts, nw, nwr, dg = 0.0, [], [], False
        fin = finalize(b, npts, nw, nwr, dg, has)
        if not fin:
            continue
        lv = levels(r["price"], r.get("cap_eok"))
        titles = [x.get("title") for x in (news.get(tk) or [])[:2] if x.get("title")]
        out.append({"ticker": tk, "name": r["name"], "market": r["market"], "cap_eok": r.get("cap_eok") or None, "price": r["price"], "day_pct": r.get("day_pct"),
                    "score": fin["score"], "parts": fin["parts"], "why": fin["why"][:6], "warns": fin["warns"][:4], "miss": fin["miss"],
                    "theme": ({"name": th["name"], "rate": th["rate"], "days": th["days_strong"]} if th else None), "levels": lv, "news": titles})
    out.sort(key=lambda x: (-x["score"], x["ticker"]))
    out = out[:KEEP]
    n_main = gate["n_main"]
    ms = gate["min_score"]
    k = 0
    for i, p in enumerate(out, 1):
        p["rank"] = i
        p["main"] = bool(k < n_main and p["score"] >= ms)
        if p["main"]:
            k += 1
    if n_main == 0:
        warns.append("장 환경이 좋지 않아 오늘은 ‘휴식 권장’이에요. 아래 목록은 참고용으로만 보세요.")
    elif k < n_main:
        warns.append(f"기준 점수({ms}점) 이상인 종목이 {k}개뿐이에요. 억지로 채우지 않았어요.")
    ths = sorted(info.values(), key=lambda t: -t["rate"])[:6]
    res = {"ok": True, "target_date": target, "scan_date": scan_date, "stale": stale, "built_at": now.strftime("%Y-%m-%d %H:%M"), "pool": len(pool),
           "gate": gate, "macro": mac.get("text") or "", "themes": [{"name": t["name"], "rate": t["rate"], "breadth": t["breadth"], "days": t["days_strong"]} for t in ths],
           "warns": warns, "picks": out}
    return res


def _save(res):
    t = res["target_date"]
    try:
        _dbx("DELETE FROM dly_scalp WHERE scalp_date=? AND result=''", (t,))
    except Exception:
        pass
    g = res["gate"]["label"]
    for p in res["picks"]:
        lv = p.get("levels") or {}
        try:
            _dbx("INSERT INTO dly_scalp(scalp_date,ticker,name,rk,main,score,gate,base_price,stop_pct,target_pct) VALUES(?,?,?,?,?,?,?,?,?,?) "
                 "ON CONFLICT(scalp_date,ticker) DO NOTHING",
                 (t, p["ticker"], p["name"], p["rank"], 1 if p["main"] else 0, p["score"], g, p["price"], lv.get("stop_pct"), lv.get("target_pct")))
        except Exception as e:
            print(f"[초단기] 저장 오류(무시): {e}")
    setting_set("scalp_last", json.dumps(res, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════
# 성과 확인 — 다음 거래일 시가·고가·저가·종가
# ══════════════════════════════════════════════════════════════
def classify_result(base, o, h, l, c, stop_pct, target_pct):
    """시가에 샀다고 가정하고 손절·목표에 닿았는지 본다. 같은 날 둘 다 닿았으면 순서를 알 수 없어 손절로 보수적으로 센다."""
    if not o:
        return "", {}
    hi = (h / o - 1) * 100
    lo = (l / o - 1) * 100
    cl = (c / o - 1) * 100
    gap = (o / base - 1) * 100 if base else 0
    hit_t = hi >= target_pct
    hit_s = lo <= -stop_pct
    if hit_s:
        res = "loss"          # 둘 다 닿은 경우도 손절로 계산
    elif hit_t:
        res = "win"
    else:
        res = "flat_up" if cl > 0 else "flat_dn"
    return res, {"gap": round(gap, 2), "high": round(hi, 2), "low": round(lo, 2), "close": round(cl, 2), "both": bool(hit_s and hit_t)}


def _pnl(res, stop_pct, target_pct, close_pct):
    if res == "win":
        return target_pct
    if res == "loss":
        return -stop_pct
    return close_pct


def evaluate_pending():
    now = _now_kst()
    today = now.strftime("%Y-%m-%d")
    try:
        pend = _dbx("SELECT scalp_date,ticker,base_price,stop_pct,target_pct FROM dly_scalp WHERE result='' ORDER BY scalp_date", (), fetch=True) or []
    except Exception:
        pend = []
    done, wait = 0, 0
    jobs = []
    for d, tk, base, sp, tp in pend:
        d = str(d)
        if d > today or (d == today and now.hour < 16):
            wait += 1
            continue
        jobs.append((d, tk, _f(base), _f(sp, 2.5) or 2.5, _f(tp, 5.0) or 5.0))

    def one(j):
        d, tk, base, sp, tp = j
        try:
            df = _fetch_ohlcv(tk, d)
            if df is None or len(df) == 0:
                return j, None
            import pandas as pd
            row = df[df.index == pd.Timestamp(d)]
            if len(row) == 0:
                return j, "nodata"
            x = row.iloc[0]
            return j, (float(x["Open"]), float(x["High"]), float(x["Low"]), float(x["Close"]))
        except Exception:
            return j, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        for j, v in ex.map(one, jobs[:80]):
            d, tk, base, sp, tp = j
            if v is None:
                wait += 1
                continue
            if v == "nodata":
                if d < (now - timedelta(days=5)).strftime("%Y-%m-%d"):
                    _dbx("UPDATE dly_scalp SET result='nodata', eval_at=? WHERE scalp_date=? AND ticker=?", (today, d, tk))
                wait += 1
                continue
            o, h, l, c = v
            res, m = classify_result(base, o, h, l, c, sp, tp)
            _dbx("UPDATE dly_scalp SET o_next=?,h_next=?,l_next=?,c_next=?,result=?,eval_at=? WHERE scalp_date=? AND ticker=?", (o, h, l, c, res, today, d, tk))
            done += 1
    return done, wait


def stats():
    try:
        rows = _dbx("SELECT scalp_date,ticker,name,main,score,gate,base_price,stop_pct,target_pct,o_next,h_next,l_next,c_next,result FROM dly_scalp "
                    "WHERE result NOT IN ('','nodata') ORDER BY scalp_date DESC, rk", (), fetch=True) or []
    except Exception:
        rows = []

    def agg(sel):
        n = len(sel)
        if not n:
            return {"n": 0}
        win = sum(1 for x in sel if x["res"] == "win")
        loss = sum(1 for x in sel if x["res"] == "loss")
        up = sum(1 for x in sel if x["close"] > 0)
        return {"n": n, "win": win, "loss": loss, "up_close": up, "win_rate": round(win / n * 100, 1), "up_rate": round(up / n * 100, 1),
                "avg_close": round(sum(x["close"] for x in sel) / n, 2), "avg_high": round(sum(x["high"] for x in sel) / n, 2),
                "avg_gap": round(sum(x["gap"] for x in sel) / n, 2), "avg_rule": round(sum(x["pnl"] for x in sel) / n, 2)}
    items = []
    for d, tk, nm, main, sc, g, base, sp, tp, o, h, l, c, res in rows:
        o, h, l, c, base = _f(o), _f(h), _f(l), _f(c), _f(base)
        sp, tp = _f(sp, 2.5) or 2.5, _f(tp, 5.0) or 5.0
        if not o:
            continue
        _, m = classify_result(base, o, h, l, c, sp, tp)
        items.append({"date": str(d), "ticker": tk, "name": nm, "main": int(main or 0), "score": int(sc or 0), "gate": g, "res": res, "gap": m["gap"],
                      "high": m["high"], "low": m["low"], "close": m["close"], "pnl": round(_pnl(res, sp, tp, m["close"]), 2)})
    by_gate = {}
    for x in items:
        by_gate.setdefault(x["gate"], []).append(x)
    return {"main": agg([x for x in items if x["main"]]), "ref": agg([x for x in items if not x["main"]]),
            "by_gate": {k: agg([y for y in v if y["main"]]) for k, v in by_gate.items()}, "recent": items[:40]}


def make_prompt(res):
    g = res["gate"]
    L = ["당신은 한국 주식 단기 매매를 돕는 데이터 분석가입니다. 아래 [자료]만 근거로 오늘 장 시작 후 30분 안에 살펴볼 후보를 판단하세요.",
         "규칙: ① 자료에 없는 사실을 지어내지 않습니다. ② 매수·매도를 단정하지 말고 ‘관찰 포인트’와 ‘피해야 할 조건’으로 씁니다. ③ 뉴스는 제목만 있으므로 내용을 추측하지 않습니다.",
         "출력: (1) 오늘 장 환경 한 줄 요약 (2) 후보별 [관찰 포인트 / 진입을 미룰 조건 / 손절 기준 재확인] 3줄씩, 최대 5종목 (3) 오늘 피해야 할 종목 유형 (4) 한계와 주의.",
         "", f"[자료] 장 시작 전 · 대상일 {res['target_date']} · 스캔 기준일 {res['scan_date']}",
         f"장 환경 판정: {g['label']} (점수 {g['score']}) — " + " / ".join(f"{a} {b:+.1f}({c})" for a, b, c in g["parts"]),
         "거시: " + (res.get("macro") or "자료 없음")]
    if res.get("themes"):
        L.append("강세 테마: " + ", ".join(f"{t['name']}({t['rate']:+.1f}%·{t['days']}일째)" for t in res["themes"]))
    L.append("")
    for p in res["picks"][:12]:
        lv = p.get("levels") or {}
        L.append(f"{p['rank']}. {p['name']}({p['ticker']}) 점수 {p['score']} [수급 {p['parts']['flow']}·모멘텀 {p['parts']['mom']}·추세 {p['parts']['trend']}·테마 {p['parts']['theme']}·뉴스 {p['parts']['news']}]")
        L.append(f"   전일 종가 {p['price']:,.0f}원({p['day_pct'] if p['day_pct'] is not None else 0:+.1f}%) · 시총 {p['cap_eok'] or 0:,}억 · 진입 관심 {lv.get('entry_lo', 0):,}~{lv.get('entry_hi', 0):,} · 손절 {lv.get('stop', 0):,} · 목표 {lv.get('target', 0):,}")
        if p["why"]:
            L.append("   근거: " + " / ".join(p["why"]))
        if p["warns"]:
            L.append("   주의: " + " / ".join(p["warns"]))
        if p["news"]:
            L.append("   뉴스(제목): " + " | ".join(p["news"]))
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════
# API (관리자 전용)
# ══════════════════════════════════════════════════════════════
def _last():
    try:
        return json.loads(setting_get("scalp_last") or "") or None
    except Exception:
        return None


@bp.route("/admin/api/scalp/state", methods=["GET"])
def api_state():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json({"last": _last(), "target": target_session_date(), "stats": stats()})


@bp.route("/admin/api/scalp/run", methods=["POST"])
def api_run():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    b = _json_body() or {}
    try:
        res = build(str(b.get("date") or "") or None)
    except Exception as e:
        print(f"[초단기] 만들기 오류: {type(e).__name__}: {e}")
        return _admin_json({"error": "후보를 만드는 중 오류가 났어요: " + str(e)[:80]}, 500)
    if res.get("error"):
        return _admin_json(res, 400)
    _save(res)
    _alog("scalp_run", f"{res['target_date']} {res['gate']['label']} {len(res['picks'])}")
    return _admin_json(res)


@bp.route("/admin/api/scalp/track", methods=["POST"])
def api_track():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    try:
        done, wait = evaluate_pending()
    except Exception as e:
        return _admin_json({"error": "성과 확인 중 오류: " + str(e)[:80]}, 500)
    return _admin_json({"ok": True, "done": done, "wait": wait, "stats": stats()})


@bp.route("/admin/api/scalp/prompt", methods=["GET"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
    last = _last()
    if not last or not last.get("picks"):
        return _admin_json({"error": "먼저 [⚡ 후보 만들기]를 누르세요."}, 404)
    return _admin_json({"prompt": make_prompt(last)})


# ══════════════════════════════════════════════════════════════
# 관리자 화면 탭
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var SC={last:null,stats:null,busy:false};
function scSt(n,css){n.style.cssText=css;return n}
function scBadge(t,bg,fg){var b=el('span',null,t);scSt(b,'display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.5px;font-weight:800;margin:0 4px 4px 0;background:'+bg+';color:'+fg);return b}
function scFmt(n){return n==null?'-':Math.round(n).toLocaleString('ko-KR')}
function scPct(v){return v==null?'-':(v>0?'+':'')+v.toFixed(1)+'%'}
function scLoad(p){p.innerHTML='';var box=el('div');box.id='scBox';p.appendChild(box);scDraw();
 api('/admin/api/scalp/state').then(function(j){if(cur!=='sc')return;SC.last=j.last;SC.stats=j.stats;SC.target=j.target;scDraw()}).catch(function(){})}
function scDraw(){var p=$('scBox');if(!p)return;p.innerHTML='';
 var hd=el('div','c');scSt(hd,'background:linear-gradient(135deg,#0a1228,#1b2f66);color:#fff;border:0');hd.appendChild(scSt(el('div',null,'⚡ 초단기 후보 — 장 시작 전'),'font-size:20px;font-weight:900'));
 hd.appendChild(scSt(el('div',null,'전일 종가·수급·테마·뉴스·미국 증시를 겹쳐서 오늘 장 초반에 살펴볼 후보를 규칙으로 골라요. 참고 자료이며 매수 권유가 아니에요. 장이 열리기 전(전일 마감 후~개장 전)에 만드는 것을 권장해요.'),'font-size:13px;opacity:.9;margin-top:6px;line-height:1.6'));
 var r=el('div');scSt(r,'margin-top:12px;display:flex;gap:8px;flex-wrap:wrap');
 var go=bt('⚡ 후보 만들기','bt',function(){scRun(go)});go.id='scGo';r.appendChild(go);
 r.appendChild(bt('📊 지난 성과 확인','bt3',function(){scTrack()}));
 r.appendChild(bt('📋 AI 요청문 복사','bt3',function(){scPrompt()}));hd.appendChild(r);p.appendChild(hd);
 var L=SC.last;if(!L){var e=el('div','c','아직 만든 후보가 없어요. [⚡ 후보 만들기]를 눌러 보세요. (먼저 [🌟 오늘추천]에서 스캔 + [시장수급]/[테마] 가져오기를 해 두면 정확해져요)');p.appendChild(e);scStats(p);return}
 scGate(p,L);scList(p,L);scStats(p)}
function scGate(p,L){var g=L.gate,c=el('div','c');var col=g.label==='공격 가능'?'#047857':(g.label==='중립'?'#1d4ed8':(g.label==='관망·보수적'?'#b45309':'#b91c1c'));
 var t=el('div');scSt(t,'display:flex;align-items:center;gap:10px;flex-wrap:wrap');t.appendChild(scBadge('장 환경: '+g.label,col,'#fff'));t.appendChild(el('b',null,'점수 '+g.score));
 t.appendChild(el('span','m','추천 '+g.n_main+'종목 · 기준 '+g.min_score+'점 이상 · 대상일 '+L.target_date+' · 스캔 기준일 '+L.scan_date+' · 만든 시각 '+L.built_at));c.appendChild(t);
 if(g.parts&&g.parts.length){var u=el('div','note');u.textContent=g.parts.map(function(x){return x[0]+' '+(x[1]>0?'+':'')+x[1]+' ('+x[2]+')'}).join(' · ');c.appendChild(u)}
 if(L.macro)c.appendChild(el('div','note','거시: '+L.macro));
 if(L.themes&&L.themes.length){var th=el('div');scSt(th,'margin-top:6px');th.appendChild(el('span','m','강세 테마 '));L.themes.forEach(function(x){th.appendChild(scBadge(x.name+' '+scPct(x.rate)+(x.days>=4?' 🔥'+x.days+'일째':''),x.days>=4?'#fee2e2':'#e0e7ff',x.days>=4?'#991b1b':'#3730a3'))});c.appendChild(th)}
 (L.warns||[]).forEach(function(w){var d=el('div','note','⚠ '+w);d.style.color='#b45309';c.appendChild(d)});p.appendChild(c)}
function scList(p,L){var c=el('div','c');c.appendChild(scSt(el('b',null,'후보 TOP '+L.picks.length+' (스캔 풀 '+L.pool+'종목 중)'),'font-size:15px'));
 c.appendChild(el('div','note','점수 = 수급 30 + 거래·가격 모멘텀 25 + 추세 위치 20 + 테마 15 + 뉴스 10. ★ 표시는 오늘 장 환경 기준 ‘추천 개수’ 안에 든 종목이고, 나머지는 참고용이에요.'));
 L.picks.forEach(function(x){var row=el('div');scSt(row,'border:1px solid '+(x.main?'#f0b429':'#e2e8f0')+';border-radius:12px;padding:10px 12px;margin-top:8px;background:'+(x.main?'#fffbeb':'#fff'));
  var h=el('div');scSt(h,'display:flex;gap:8px;align-items:baseline;flex-wrap:wrap');h.appendChild(el('b',null,(x.main?'★ ':'')+x.rank+'. '+x.name));h.appendChild(el('span','m',x.ticker+' · '+x.market+' · 시총 '+scFmt(x.cap_eok)+'억'));
  var sc=el('b',null,x.score+'점');scSt(sc,'margin-left:auto;font-size:16px;color:'+(x.score>=70?'#047857':(x.score>=60?'#1d4ed8':'#64748b')));h.appendChild(sc);row.appendChild(h);
  var pt=x.parts,b=el('div');scSt(b,'margin-top:4px');[['수급',pt.flow,30],['모멘텀',pt.mom,25],['추세',pt.trend,20],['테마',pt.theme,15],['뉴스',pt.news,10]].forEach(function(k){var r=k[1]/k[2];b.appendChild(scBadge(k[0]+' '+k[1],r>=.7?'#d1fae5':(r>=.4?'#e0f2fe':'#f1f5f9'),r>=.7?'#065f46':(r>=.4?'#075985':'#475569')))});
  if(x.theme)b.appendChild(scBadge('🏷 '+x.theme.name+' '+scPct(x.theme.rate),'#ede9fe','#5b21b6'));
  (x.miss||[]).forEach(function(m){b.appendChild(scBadge(m+' 자료 없음','#f1f5f9','#64748b'))});row.appendChild(b);
  row.appendChild(el('div','note','전일 종가 '+scFmt(x.price)+'원 ('+scPct(x.day_pct)+')'));
  if(x.why&&x.why.length)row.appendChild(el('div','note','✅ '+x.why.join(' · ')));
  if(x.warns&&x.warns.length){var w=el('div','note','⚠ '+x.warns.join(' · '));w.style.color='#b45309';row.appendChild(w)}
  if(x.news&&x.news.length)row.appendChild(el('div','note','📰 '+x.news.join(' | ')+'  (제목 기준)'));
  var lv=x.levels;if(lv){var d=el('div');scSt(d,'margin-top:6px;padding:6px 8px;border-radius:8px;background:#f1f5f9;font-size:12.5px;line-height:1.7');
   d.textContent='진입 관심 '+scFmt(lv.entry_lo)+' ~ '+scFmt(lv.entry_hi)+'원 · 손절 '+scFmt(lv.stop)+'원(-'+lv.stop_pct+'%) · 목표 '+scFmt(lv.target)+'원(+'+lv.target_pct+'%) · 시가가 '+scFmt(lv.chase)+'원(+5%)보다 높게 열면 추격 금지 · '+scFmt(lv.gap_floor)+'원(-2%) 아래로 열면 제외 · 장 시작 30분 안에 +1%를 못 가면 정리 검토';row.appendChild(d)}
  c.appendChild(row)});p.appendChild(c)}
function scStats(p){var S=SC.stats;if(!S)return;var c=el('div','c');c.appendChild(scSt(el('b',null,'📊 지난 성과 (다음 거래일 시가에 샀다고 가정)'),'font-size:15px'));
 var m=S.main||{n:0};if(!m.n){c.appendChild(el('div','note','아직 확인된 기록이 없어요. 후보를 만든 다음 거래일이 지나면 [📊 지난 성과 확인]을 눌러 시가·고가·저가·종가를 가져와요. 최소 20~30건은 쌓여야 의미가 생겨요.'));p.appendChild(c);return}
 var tl=el('div');scSt(tl,'display:flex;gap:8px;flex-wrap:wrap;margin-top:8px');[['★ 추천 건수',m.n+'건'],['목표 도달',m.win_rate+'%'],['종가 플러스',m.up_rate+'%'],['평균 시가→종가',scPct(m.avg_close)],['평균 시가→고가',scPct(m.avg_high)],['규칙 적용 평균',scPct(m.avg_rule)]].forEach(function(k){var t=el('div');scSt(t,'padding:8px 12px;border-radius:10px;background:#f1f5f9');t.appendChild(scSt(el('div',null,k[0]),'font-size:11.5px;color:#64748b'));t.appendChild(scSt(el('div',null,k[1]),'font-size:16px;font-weight:900'));tl.appendChild(t)});c.appendChild(tl);
 var rf=S.ref||{n:0};c.appendChild(el('div','note','참고 순위(★ 밖) '+(rf.n?rf.n+'건 · 목표 도달 '+rf.win_rate+'% · 평균 시가→종가 '+scPct(rf.avg_close):'기록 없음')+' — ★이 참고보다 좋아야 점수가 의미 있어요.'));
 var bg=Object.keys(S.by_gate||{});if(bg.length)c.appendChild(el('div','note','장 환경별(★만): '+bg.map(function(k){var v=S.by_gate[k];return k+' '+v.n+'건 '+(v.n?'종가+ '+v.up_rate+'%':'')}).join(' · ')));
 c.appendChild(el('div','note','※ 같은 날 손절·목표에 모두 닿았으면 손절로 계산(보수적). 수수료·거래세·체결 오차는 빠져 있어요.'));
 var det=el('details');det.appendChild(el('summary',null,'최근 기록 '+S.recent.length+'건'));S.recent.forEach(function(x){var d=el('div','note',x.date+' '+(x.main?'★':' ')+' '+x.name+' · 갭 '+scPct(x.gap)+' · 고가 '+scPct(x.high)+' · 저가 '+scPct(x.low)+' · 종가 '+scPct(x.close)+' → '+({win:'🎯 목표',loss:'🛑 손절',flat_up:'➕ 종가 플러스',flat_dn:'➖ 종가 마이너스'}[x.res]||x.res));det.appendChild(d)});c.appendChild(det);p.appendChild(c)}
function scRun(btn){if(SC.busy){toast('이미 만드는 중이에요');return}SC.busy=true;btn.disabled=true;btn.textContent='⏳ 만드는 중… (최대 1분)';toast('⏳ 후보를 만드는 중이에요 (수급·테마·뉴스 확인, 최대 1분)');
 apiJ('/admin/api/scalp/run',{}).then(function(j){SC.busy=false;if(j.error){toast('⚠ '+j.error);scDraw();return}SC.last=j;toast('✅ 후보 '+j.picks.length+'종목을 만들었어요 (장 환경: '+j.gate.label+')');scDraw();api('/admin/api/scalp/state').then(function(s){SC.stats=s.stats;scDraw()})},function(){SC.busy=false;toast('⚠ 후보 만들기에 실패했어요');scDraw()})}
function scTrack(){toast('⏳ 지난 후보의 다음 거래일 결과를 가져오는 중이에요');apiJ('/admin/api/scalp/track',{}).then(function(j){if(j.error){toast('⚠ '+j.error);return}SC.stats=j.stats;toast('✅ '+j.done+'건 확인 완료'+(j.wait?' · '+j.wait+'건은 아직 결과가 없어요':''));scDraw()},function(){toast('⚠ 성과 확인에 실패했어요')})}
function scPrompt(){api('/admin/api/scalp/prompt').then(function(j){if(j.error){toast('⚠ '+j.error);return}var t=j.prompt,ok=false;try{var ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.appendChild(ta);ta.select();ok=document.execCommand('copy');document.body.removeChild(ta)}catch(e){}
  try{if(!ok&&navigator.clipboard){navigator.clipboard.writeText(t);ok=true}}catch(e){}toast(ok?'✅ AI 요청문을 복사했어요 ('+t.length.toLocaleString()+'자) — AI 창에 붙여 넣으세요':'⚠ 복사하지 못했어요. 브라우저 권한을 확인해 주세요')},function(){toast('⚠ 요청문을 만들지 못했어요')})}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_settings({"scalp_last": ""})
    C.register_admin_tab("sc", "⚡ 초단기(장전)", TAB_JS, "scLoad")
    return bp
