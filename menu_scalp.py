"""⚡ 초단기 후보 (장 시작 전) — 참고 자료 (투자 권유 아님) · 공개 범위는 [메뉴·설정]/[기능 공개]에서 정함(기본: 관리자만)

[관점] "오늘 시가 부근에서 사서 오후에 정리하면 / 1~2영업일 안에 오를 가능성이 있는가". 중장기 투자 의견이 아니에요.
  · 당일 오후 청산형: 시가 매수 → 당일 종가 기준으로 목표(+손절폭 1배)·손절 확인
  · 1~2영업일형:     시가 매수 → 2영업일 안에 목표(+손절폭 2배)·손절 확인

[무엇을 하나요]
  오늘추천이 저장해 둔 가장 최근 스캔(전일 종가 기준)에 '시장 흐름·수급·테마·뉴스·재무'를 겹쳐서 후보를 규칙으로 골라요.
  ① 장 환경(게이트)   미국 증시·VIX·원/달러로 '공격 / 중립 / 관망 / 휴식' 판정 → 추천 개수·기준 점수 조절(최대한 적극적: 휴식 때도 3개는 보여줘요)
  ② 종목 점수(100점)  수급 30 · 거래·가격 모멘텀 25 · 추세 위치 20 · 테마 15 · 뉴스 10  (+ 재무 보정 -9~+2)
  ③ 재무 필터         2년 연속 영업적자·자본잠식 의심·부채비율 500%↑·ROE -30%↓ 는 제외, 부진 신호가 3개 이상이어도 제외(자료가 없으면 제외하지 않고 '자료 없음' 표시)
  ④ 가격 관찰선       전일 종가 기준 진입 관심 구간·손절·당일 목표·2영업일 목표(호가 단위)·갭 상승 추격 금지선
  ⑤ 자동 흐름         후보 만들기 → AI 분석(요청문 → 답변 복사) → 블로그 글 만들기 → 블로그 복사·열기 (단계별 자동/수동은 [⚙ 설정]의 단계 진행 방식)
  ⑥ 성과 확인         후보를 기록해 두고 당일 종가(오후 청산 가정)와 2영업일 결과를 가져와 승률·평균 손익으로 점수 비중을 점검
  ⑦ 종목 링크         후보마다 [종목분석]·[심층분석] 링크가 기본으로 붙어요(블로그 글에도 포함)

[한계] 뉴스는 제목만 보고, 장중 수급·호가·프로그램 매매는 보지 않아요. 일봉만 쓰므로 같은 날 손절·목표에 모두 닿으면 손절로 계산해요.
       수수료·거래세·체결 오차는 성과에 반영되지 않아요.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from flask import Blueprint, request
from menu_ctx import C
import menu_blog as B
import menu_daily as D
import menu_lab as L

bp = Blueprint("scalp", __name__)
MENU = "scalp"

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_dbrows", "_cache_get", "_cache_set", "_now_kst",
               "setting_get", "setting_set", "_naver_news", "_naver_finance", "_fetch_ohlcv", "prompt_get", "_prompt_fill", "_public_site_url")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

E = B.E

# ── 점수 비중(합 100) ──
W_FLOW, W_MOM, W_TREND, W_THEME, W_NEWS = 30, 25, 20, 15, 10
KEEP = 25                      # 저장·표시하는 순위 수
MIN_CAP_EOK = 700              # 유동성 하한(시총 억원) — 이보다 작으면 체결이 불리해 제외
MIN_PRICE = 1000               # 동전주 제외
CHECK_TOP = 40                 # 뉴스·재무는 중간 순위 상위 N개만 조회(시간 절약) — 최종 후보는 모두 이 안에서 나와요
GATE_TABLE = [                 # (이름, 추천 개수, 기준 점수) — 최대한 적극적으로: 휴식 때도 3개는 보여준다
    ("공격 가능", 12, 55), ("중립", 8, 60), ("관망·보수적", 5, 66), ("휴식 권장", 3, 74)]

POS_WORDS = ("수주", "계약 체결", "공급 계약", "단독 공급", "공급계약", "승인", "허가", "흑자", "최대 실적", "사상 최대", "호실적", "어닝 서프라이즈", "실적 개선",
             "신제품", "인수", "mou", "양산", "특허", "투자 유치", "목표가 상향", "목표주가 상향", "자사주 매입", "자사주 소각", "배당 확대", "정부 지원", "정책 수혜", "수혜")
NEG_WORDS = ("유상증자", "전환사채", "신주인수권", "신주 발행", "감자", "적자", "소송", "리콜", "목표가 하향", "목표주가 하향", "하향", "불성실", "공매도", "오버행",
             "블록딜", "대규모 손실", "손실 확대", "계약 해지", "계약 취소", "철회", "중단")
DANGER_WORDS = ("상장폐지", "횡령", "배임", "거래정지", "감사의견", "관리종목", "불성실공시", "회생", "파산", "부도")

SCALP_PROMPT_DEFAULT = """당신은 한국 주식 시장의 단기 매매를 돕는 데이터 분석가입니다. 아래 [자료]만 근거로 '{target_date}' 장 시작 전 관찰 후보를 정리하세요. (작성일 {today})
관점: 오늘 시가 부근에서 사서 당일 오후에 정리하거나, 1~2영업일 안에 오를 가능성이 있는지를 봅니다. 중장기 투자 의견이 아닙니다.

[규칙]
- [자료]에 없는 숫자·사실을 지어내지 않습니다. 모르면 "자료에 없음"이라고 씁니다.
- 매수·매도를 지시하거나 수익을 약속하지 않습니다. "관찰 포인트", "진입을 미룰 조건"처럼 관찰 중심으로 씁니다.
- 뉴스는 제목만 있으므로 내용을 추측하지 않고 "제목 기준"임을 밝힙니다.
- 재무 점검에 '주의'가 붙은 종목은 그 이유를 한 줄 언급합니다.
- 마크다운 제목은 아래 5개를 순서대로, 정확히 "## 번호. 제목" 형식으로만 씁니다.

## 1. 한줄 결론 (오늘 장 환경과 공격 수위)
## 2. 핵심 후보 (최대 5종목 — 종목명(코드) · 관점[당일 오후 청산형 / 1~2영업일형] · 근거 2줄 · 진입을 미룰 조건 · 손절 기준)
## 3. 주의할 종목과 이유
## 4. 장 시작 30분 체크리스트 ("- " 목록 3~4개)
## 5. 블로그 제목 후보 (검색에 잘 걸리는 제목 3개, 각 줄 앞에 "- ")

[자료]
{data}
"""


def _f(v, d=None):
    return D._f(v, d)


def _cl(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _gw():
    return bool(request.environ.get("mini.gateway"))


def _fok(fid):
    """관리자 화면이면 항상 True, 회원 화면(gateway)이면 그 기능이 지금 보는 사람에게 열려 있는가."""
    return (not _gw()) or bool(C.feature_ok(MENU, fid))


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
        pp = 5.0
        warns.append(f"전일 {day:+.1f}% 급등 — 갭 상승 시 추격 주의")
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
            pts += 3
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


# ══════════════════════════════════════════════════════════════
# ③ 재무 필터 — 순수 함수 (표: _naver_finance → {"periods":[{title,estimate}], "rows":[{name, values}]})
# ══════════════════════════════════════════════════════════════
def _actuals(tbl, name):
    """이름의 행에서 '실적'(추정 아님) 값만 시간순으로. 값이 없으면 빈 목록."""
    if not tbl:
        return []
    row = next((r for r in (tbl.get("rows") or []) if r.get("name") == name), None)
    if not row:
        return []
    pers = tbl.get("periods") or []
    out = []
    for i, v in enumerate(row.get("values") or []):
        est = bool(pers[i].get("estimate")) if i < len(pers) else False
        if not est and v is not None:
            out.append(float(v))
    return out


def assess_fin(tbl):
    """재무 점검. 반환 {known, exclude, severe, minor, good, adj, summary}.
       - severe(하나라도 있으면 제외): 2년 연속 영업적자 · 자본잠식 의심(BPS≤0) · 부채비율 500%↑(당좌비율이 있는 일반 기업) · ROE -30%↓
       - minor(3개 이상이면 제외, 아니면 개당 -3점·최대 -9): 최근 영업적자 · 순손실 · ROE 음수 · 부채비율 300~500% · 당좌비율 50%↓ · 영업이익 반토막
       - good: 흑자 + ROE 8%↑ + 부채비율 150%↓ → +2점. 자료가 없으면 known=False(제외하지 않고 -2점·'자료 없음')."""
    if not tbl or not (tbl.get("rows")):
        return {"known": False, "exclude": False, "severe": [], "minor": [], "good": [], "adj": -2.0, "summary": "재무 자료 없음"}
    op, ni, roe, debt, quick, bps = (_actuals(tbl, k) for k in ("영업이익", "당기순이익", "ROE", "부채비율", "당좌비율", "BPS"))
    op1, op0 = (op[-1] if op else None), (op[-2] if len(op) >= 2 else None)
    ni1 = ni[-1] if ni else None
    roe1 = roe[-1] if roe else None
    debt1 = debt[-1] if debt else None
    quick1 = quick[-1] if quick else None
    bps1 = bps[-1] if bps else None
    severe, minor, good = [], [], []
    if op1 is not None and op0 is not None and op1 < 0 and op0 < 0:
        severe.append("2년 연속 영업적자")
    if bps1 is not None and bps1 <= 0:
        severe.append("자본잠식 의심(BPS 0 이하)")
    if debt1 is not None and debt1 >= 500 and quick1 is not None:
        severe.append(f"부채비율 {debt1:.0f}%")
    if roe1 is not None and roe1 <= -30:
        severe.append(f"ROE {roe1:.0f}%")
    if op1 is not None and op1 < 0 and not (op0 is not None and op0 < 0):
        minor.append("최근 연간 영업적자")
    if ni1 is not None and ni1 < 0:
        minor.append("순손실")
    if roe1 is not None and -30 < roe1 < 0:
        minor.append(f"ROE {roe1:.1f}%")
    if debt1 is not None and 300 <= debt1 < 500:
        minor.append(f"부채비율 {debt1:.0f}%")
    if quick1 is not None and quick1 < 50:
        minor.append(f"당좌비율 {quick1:.0f}%")
    if op1 is not None and op0 is not None and op0 > 0 and op1 > 0 and (op1 - op0) / op0 <= -0.5:
        minor.append("영업이익 50% 이상 감소")
    if op1 is not None and ni1 is not None and roe1 is not None and op1 > 0 and ni1 > 0 and roe1 >= 8 and (debt1 is None or debt1 < 150):
        good.append(f"재무 양호(흑자·ROE {roe1:.0f}%" + (f"·부채 {debt1:.0f}%)" if debt1 is not None else ")"))
    exclude = bool(severe) or len(minor) >= 3
    adj = max(-9.0, -3.0 * len(minor)) + (2.0 if good else 0.0)
    if severe:
        summ = "제외: " + " · ".join(severe)
    elif exclude:
        summ = "제외: 재무 부진 신호 " + " · ".join(minor)
    elif minor:
        summ = "주의: " + " · ".join(minor)
    elif good:
        summ = good[0]
    else:
        summ = "큰 문제 신호 없음"
    return {"known": True, "exclude": exclude, "severe": severe, "minor": minor, "good": good, "adj": adj, "summary": summ}


# ══════════════════════════════════════════════════════════════
# ④ 가격 관찰선
# ══════════════════════════════════════════════════════════════
def levels(price, cap_eok):
    """전일 종가 기준 진입·손절·목표(호가 단위). 대형주는 좁게, 소형주는 넓게.
       당일 오후 청산형 목표 = 손절폭 1배, 1~2영업일형 목표 = 손절폭 2배."""
    if not price or price <= 0:
        return None
    cap = cap_eok or 0
    stop_pct = 2.0 if cap >= 10000 else (2.5 if cap >= 3000 else 3.0)
    lo = tick_round(price * 1.000, "up")
    hi = tick_round(price * 1.020, "down")
    mid = (lo + max(hi, lo)) / 2.0
    return {"entry_lo": lo, "entry_hi": max(hi, lo), "chase": tick_round(price * 1.05, "down"),
            "stop": tick_round(mid * (1 - stop_pct / 100.0), "down"), "stop_pct": stop_pct,
            "target_day": tick_round(mid * (1 + stop_pct / 100.0), "up"), "target_day_pct": stop_pct,
            "target": tick_round(mid * (1 + stop_pct * 2 / 100.0), "up"), "target_pct": stop_pct * 2,
            "gap_floor": tick_round(price * 0.98, "up")}


def prelim(r, th):
    """뉴스·재무 이전 점수(수급·모멘텀·추세·테마). 반환 dict 또는 None(제외)."""
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


def finalize(base, news, fin):
    """news: (pts, why, warns, danger) 또는 None(조회 못 함) · fin: assess_fin 결과. 제외면 None."""
    parts = dict(base["parts"])
    why, warns, miss = list(base["why"]), list(base["warns"]), list(base["miss"])
    if news is None:
        parts["news"] = W_NEWS * 0.4
        miss.append("뉴스")
    else:
        npts, nw, nwr, danger = news
        if danger:
            return None
        parts["news"] = npts
        why += nw
        warns += nwr
    if fin.get("exclude"):
        return None
    if not fin.get("known"):
        miss.append("재무")
        warns.append("재무 자료 없음 — 직접 확인하세요")
    elif fin["minor"]:
        warns.append("재무 주의: " + " · ".join(fin["minor"]))
    elif fin["good"]:
        why.append(fin["good"][0])
    adj = fin.get("adj", 0.0)
    total = sum(parts.values()) + adj
    parts["fin"] = adj
    return {"score": int(round(max(0.0, min(100.0, total)))), "parts": {k: round(v, 1) for k, v in parts.items()}, "why": why, "warns": warns, "miss": miss}


# ══════════════════════════════════════════════════════════════
# 표 · 자료 모으기
# ══════════════════════════════════════════════════════════════
def _ensure_tables(c, use_pg):
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    c.execute(f"CREATE TABLE IF NOT EXISTS dly_scalp(scalp_date TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', rk INTEGER NOT NULL DEFAULT 0, "
              f"main INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0, gate TEXT NOT NULL DEFAULT '', base_price {real}, stop_pct {real}, target_pct {real}, "
              f"o_next {real}, h_next {real}, l_next {real}, c_next {real}, result TEXT NOT NULL DEFAULT '', eval_at TEXT NOT NULL DEFAULT '', "
              f"PRIMARY KEY(scalp_date, ticker))")
    # [v198] 당일(오후 청산)·1~2영업일 결과 열 — 이미 만들어진 표에는 열만 덧붙인다(기존 기록 유지)
    for col, typ in (("target_day_pct", real), ("h1", real), ("l1", real), ("c1", real), ("h2", real), ("l2", real), ("c2", real), ("res2", "TEXT NOT NULL DEFAULT ''")):
        try:
            if use_pg:
                c.execute(f"ALTER TABLE dly_scalp ADD COLUMN IF NOT EXISTS {col} {typ}")
            else:
                have = {r[1] for r in c.execute("PRAGMA table_info(dly_scalp)").fetchall()}
                if col not in have:
                    c.execute(f"ALTER TABLE dly_scalp ADD COLUMN {col} {typ}")
        except Exception as e:
            print(f"[초단기] 열 추가 건너뜀({col}): {e}")
    c.execute("CREATE TABLE IF NOT EXISTS dly_scalp_ai(scalp_date TEXT PRIMARY KEY, result TEXT NOT NULL DEFAULT '', updated BIGINT NOT NULL DEFAULT 0)")


def _norm_name(x):
    return re.sub(r"[\s·]", "", str(x or ""))


def _live_themes():
    """[v200] 네이버 ‘실시간’ 테마 순위(네이버테마 메뉴의 실시간 탭과 같은 자료, 20초 캐시). 실패하면 (None, 0)."""
    try:
        import menu_theme as T
        d, age = T._live_cached(("rank", "theme", "daily"), lambda: T._live_rank("theme", "daily"))
        return (d if d and d.get("items") else None), age
    except Exception as e:
        print(f"[초단기] 실시간 테마 조회 실패(저장본 사용): {type(e).__name__}: {e}")
        return None, 0


def _theme_ctx(now):
    """테마 자료 → ({ticker: [테마이름…]}, {이름: 정보}, 경고글, 메타{fetched, trade_date, live}).
       [v200] 등락률·상승/하락 종목 수는 네이버 실시간 순위를 우선 쓰고(‘쌓아 둔’ 저장본은 옛 값), 종목-테마 연결은 저장본 + 실시간 상위 종목으로 만든다.
       실시간 조회가 안 될 때만 저장본(collect_theme_list)으로 돌아간다."""
    info, tmap, note = {}, {}, ""
    meta = {"fetched": "", "trade_date": "", "live": False}
    try:
        rows = _dbx("SELECT no,name,change_rate,rise,fall,steady,fetched_at FROM collect_theme_list", fetch=True) or []
    except Exception:
        rows = []
    live, _age = _live_themes()
    if not rows and not live:
        return tmap, info, "테마 자료가 없어요 — [🏷 테마 가져오기]를 먼저 해 두면 테마 점수가 반영돼요.", meta
    hist = {}
    try:
        cut = (now - timedelta(days=25)).strftime("%Y-%m-%d")
        for d, nm, rate in (_dbx("SELECT date,name,rate FROM theme_day WHERE date>=? ORDER BY date", (cut,), fetch=True) or []):
            hist.setdefault(_norm_name(nm), []).append((str(d), _f(rate, 0.0) or 0.0))
    except Exception:
        pass
    try:
        td = _dbx("SELECT MAX(date) FROM theme_day", (), fetch=True) or []
        stored_td = str(td[0][0] or "")[:10] if td else ""
    except Exception:
        stored_td = ""
    stored = {}
    newest = ""
    for no, name, rate, rise, fall, steady, fa in rows:
        newest = max(newest, str(fa or ""))
        stored[_norm_name(name)] = {"name": name, "rate": _f(rate, 0.0) or 0.0, "rise": int(_f(rise, 0) or 0), "fall": int(_f(fall, 0) or 0)}

    def strong_days(key, today_date, today_rate):
        series = [(d, rt) for d, rt in hist.get(key, []) if d != today_date]
        series.sort(reverse=True)
        n = 0
        if today_rate is not None:
            if today_rate >= 2.0:
                n = 1
            else:
                return 0
        for _, rt in series:
            if rt >= 2.0:
                n += 1
            else:
                break
        return n

    if live:
        ud = str(live.get("updated") or "")
        m = re.match(r"(\d{4}-\d{2}-\d{2})", ud)
        live_date = m.group(1) if m else now.strftime("%Y-%m-%d")
        meta.update({"live": True, "trade_date": live_date, "fetched": (ud[:16].replace("T", " ") if ud else now.strftime("%Y-%m-%d %H:%M"))})
        for x in live["items"]:
            key = _norm_name(x["name"])
            nm = stored[key]["name"] if key in stored else x["name"]
            rise, fall = int(x.get("rise") or 0), int(x.get("fall") or 0)
            info[nm] = {"no": 0, "name": nm, "rate": float(x.get("rate") or 0.0), "rise": rise, "fall": fall,
                        "breadth": (rise / float(rise + fall)) if (rise + fall) > 0 else None, "days_strong": strong_days(key, live_date, float(x.get("rate") or 0.0))}
            for k in ("t_rate", "t_cap", "t_val", "t_vol"):
                for sct in (x.get(k) or []):
                    c = str(sct.get("code") or "").zfill(6)
                    if c.isdigit() and nm not in tmap.setdefault(c, []):
                        tmap[c].append(nm)
    else:
        meta.update({"trade_date": stored_td, "fetched": str(newest or "")[:16]})
        for key, v in stored.items():
            rise, fall = v["rise"], v["fall"]
            info[v["name"]] = {"no": 0, "name": v["name"], "rate": v["rate"], "rise": rise, "fall": fall,
                               "breadth": (rise / float(rise + fall)) if (rise + fall) > 0 else None, "days_strong": strong_days(key, stored_td, None)}
        if newest and str(newest)[:10] < (now - timedelta(days=4)).strftime("%Y-%m-%d"):
            note = f"테마 자료가 {str(newest)[:10]} 것이라 오래됐어요 — [🏷 테마 가져오기]로 새로 받으면 더 정확해요."
        else:
            note = "네이버 실시간 테마를 받지 못해 ‘쌓아 둔’ 테마 자료를 썼어요."
    try:
        for tk, th in (_dbx("SELECT ticker,theme FROM stock_theme_map WHERE theme_type='naver'", (), fetch=True) or []):
            key = _norm_name(th)
            nm = next((n for n in (th,) if n in info), None)
            if nm is None:
                nm = next((v["name"] for v in info.values() if _norm_name(v["name"]) == key), None)
            if nm and nm not in tmap.setdefault(str(tk).zfill(6), []):
                tmap[str(tk).zfill(6)].append(nm)
    except Exception:
        pass
    return tmap, info, note, meta


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


def _news_for(tk):
    hit = _cache_get(("scalp_news", tk))
    if hit is not None:
        return hit
    try:
        items = _naver_news(tk) or []
    except Exception:
        items = []
    _cache_set(("scalp_news", tk), items, 600)
    return items


def _fin_for(tk):
    try:
        return _naver_finance(tk, "annual")
    except Exception:
        return None


def _links(tk):
    return {"stock": f"/?t={tk}", "deep": f"/?t={tk}&m=deep"}


# ══════════════════════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════════════════════
def _flow_overlay(pool, want_last):
    """[v199] 시장수급 [가져오기]로 새로 받은 수급(investor_scan_cache)을 스캔 저장본 위에 덮어쓴다 — 스캔은 전일에 저장된 값이라
       수급을 다시 받아도 후보에 반영되지 않던 문제. 반환 (갱신 종목 수, 기준일 대표값, 가져온 시각 최신값)."""
    try:
        fc = D._flow_cache()
    except Exception:
        fc = {}
    if not fc:
        return 0, "", ""
    n, bases = 0, {}
    for r in pool:
        x = fc.get(r["ticker"])
        if not x:
            continue
        for k in ("f1", "i1", "f5", "i5", "f20", "i20"):
            r[k] = x[k]
        r["flags"] = [f for f in (r.get("flags") or []) if f not in ("쌍끌이", "수급전환")]
        try:
            D._flow_flags(r)
        except Exception:
            pass
        n += 1
        if x.get("base"):
            bases[x["base"]] = bases.get(x["base"], 0) + 1
    base = max(bases.items(), key=lambda kv: kv[1])[0] if bases else ""
    at = ""
    try:
        q = _dbx("SELECT MAX(scanned_at) FROM investor_scan_cache", (), fetch=True) or []
        at = str(q[0][0] or "")[:16] if q else ""
    except Exception:
        pass
    return n, base, at


def _fresh_flow(tk, target):
    """[v200] 종목별 최근 거래일 외국인·기관 순매수를 네이버에서 바로 조회(10분 캐시) — ‘쌓아 둔’ 수급이 며칠 전 것이어도 최신으로 계산.
       아직 끝나지 않은 날(대상일 당일 장중)은 쓰지 않는다. 반환 {f1,i1,f5,i5,f20,i20,base} 또는 None."""
    try:
        rows = [x for x in (L._trend_rows(tk) or []) if x.get("date") and x["date"] < target and x.get("close")]
        sp = L.supply_analysis(rows) if rows else None
        if not sp:
            return None
        per = sp["per"]
        out = {"base": rows[0]["date"]}
        p1, p5, p20 = per.get("1"), per.get("5"), per.get("20")
        if not p1:
            return None
        out["f1"], out["i1"] = p1["foreign_eok"], p1["inst_eok"]
        if p5 and p5["days"] >= 5:
            out["f5"], out["i5"] = p5["foreign_eok"], p5["inst_eok"]
        if p20 and p20["days"] >= 15:
            out["f20"], out["i20"] = p20["foreign_eok"], p20["inst_eok"]
        return out
    except Exception:
        return None


def _diff_with_prev(res):
    """같은 대상일에 이미 만든 후보가 있으면 이번에 무엇이 바뀌었는지 요약(다시 만들었는데 변화가 없어 보인다는 불안 해소)."""
    prev = _last()
    if not prev or prev.get("target_date") != res["target_date"] or not prev.get("picks"):
        return None
    pm = {p["ticker"]: p for p in prev["picks"]}
    cm = {p["ticker"]: p for p in res["picks"]}
    pmain = {t for t, p in pm.items() if p.get("main")}
    cmain = {t for t, p in cm.items() if p.get("main")}
    ch = [(cm[t]["score"] - pm[t]["score"], t) for t in cm if t in pm]
    moved = sum(1 for d, _ in ch if d != 0)
    return {"prev_at": prev.get("built_at", ""), "new": [cm[t]["name"] for t in cmain - pmain][:8], "dropped": [pm[t]["name"] for t in pmain - cmain][:8],
            "moved": moved, "avg": round(sum(d for d, _ in ch) / len(ch), 2) if ch else 0.0,
            "gate_prev": (prev.get("gate") or {}).get("label", "")}


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
        warns.append(f"스캔 저장 종목이 {len(rows)}개뿐이라 후보 폭이 좁아요. [🌟 오늘추천 → ⚙ 옵션]에서 저장 개수를 늘리고 최소 점수를 낮춰 스캔하면 더 넓게 볼 수 있어요.")
    risk = D.risk_set()
    for r in rows:
        r["cap_eok"] = _cap_of(r)
    pool = [r for r in rows if r["ticker"] not in risk]
    fl_n, fl_base, fl_at = _flow_overlay(pool, want_last)

    try:
        mac = D.macro_snapshot()
    except Exception:
        mac = {"text": "", "rows": []}
    gate = gate_from_macro(mac.get("rows"))
    if gate["missing"]:
        warns.append("거시 지표(미국 증시·VIX·환율)를 받지 못해 장 환경은 ‘중립’으로 두었어요.")

    tmap, info, tnote, tmeta = _theme_ctx(now)
    if tnote:
        warns.append(tnote)
    # ── 자료 기준(신선도) 표 — 화면에서 ‘어느 시점 자료인지’를 한눈에 보여 신뢰를 높인다 ──
    today_s = now.strftime("%Y-%m-%d")
    intraday = (target == today_s and 9 <= now.hour < 16)
    fresh = [{"k": "스캔(기술 지표)", "asof": scan_date, "ok": not stale, "note": f"{len(rows)}종목 저장본" + ("" if not stale else " — 직전 거래일 기준이 아니에요")}]

    # 1차 점수 → 상위만 현재가 갱신 → 뉴스·재무 확인
    pre = []
    for r in pool:
        th = best_theme(r["ticker"], tmap, info)
        b = prelim(r, th)
        if b:
            pre.append((sum(b["parts"].values()), r, th, b))
    pre.sort(key=lambda x: -x[0])
    head = pre[:CHECK_TOP + 30]
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
    # [v200] 상위 후보는 종목별 최신 수급을 직접 조회해 다시 점수를 매기고 순위를 바꾼다
    cand = refreshed[:CHECK_TOP + 20]
    ffl = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fresh_flow, r["ticker"], target): r["ticker"] for _, r, _, _ in cand}
        try:
            for f in as_completed(futs, timeout=25):
                try:
                    v = f.result()
                    if v:
                        ffl[futs[f]] = v
                except Exception:
                    pass
        except Exception:
            warns.append("종목별 최신 수급 조회가 오래 걸려 일부 종목은 저장된 수급을 썼어요.")
    rescored = []
    bases = {}
    for _, r, th, b in cand:
        v = ffl.get(r["ticker"])
        if v:
            r = dict(r)
            for k in ("f1", "i1", "f5", "i5", "f20", "i20"):
                if k in v:
                    r[k] = v[k]
            r["flags"] = [f for f in (r.get("flags") or []) if f not in ("쌍끌이", "수급전환")]
            try:
                D._flow_flags(r)
            except Exception:
                pass
            bases[v["base"]] = bases.get(v["base"], 0) + 1
            b = prelim(r, th) or b
        rescored.append((sum(b["parts"].values()), r, th, b))
    rescored.sort(key=lambda x: -x[0])
    top = rescored[:CHECK_TOP]
    ff_base = max(bases.items(), key=lambda kv: kv[1])[0] if bases else ""
    ff_n = len(ffl)
    # ── 수급·테마 신선도 ──
    if ff_n:
        okf = bool(ff_base) and ff_base >= want_last
        fresh.append({"k": "외국인·기관 수급", "asof": ff_base or "?", "ok": okf,
                      "note": f"상위 {len(cand)}종목 중 {ff_n}종목은 네이버에서 방금 조회한 최신 수급" + (f", 나머지는 저장본(기준 {fl_base or '?'})" if fl_n or len(cand) > ff_n else "")
                      + ("" if okf else f" — 직전 거래일({want_last}) 자료가 아니에요")})
        if not okf:
            warns.append(f"수급 기준일이 {ff_base or '알 수 없음'}이에요(직전 거래일 {want_last}).")
    elif fl_n:
        okf = bool(fl_base) and fl_base >= want_last
        fresh.append({"k": "외국인·기관 수급", "asof": fl_base or "?", "ok": okf, "note": f"종목별 최신 조회는 실패해 {fl_n}종목은 ‘가져온’ 수급 저장본을 썼어요(가져온 시각 {fl_at})" + ("" if okf else f" — 직전 거래일({want_last}) 자료가 아니에요")})
        if not okf:
            warns.append(f"수급 자료 기준일이 {fl_base or '알 수 없음'}이에요(직전 거래일 {want_last}). 네이버 조회가 막혔다면 잠시 뒤 다시 만들어 보세요.")
    else:
        fresh.append({"k": "외국인·기관 수급", "asof": "스캔 저장본", "ok": False, "note": "최신 수급을 받지 못해 스캔 때 저장된 값을 썼어요"})
        warns.append("최신 수급을 받지 못해 스캔 때 저장된 수급을 그대로 썼어요. 잠시 뒤 다시 만들거나 [시장수급 가져오기]를 해 보세요.")
    tdate = tmeta.get("trade_date") or ""
    if info:
        src_lbl = "네이버 실시간" if tmeta.get("live") else "‘가져온’ 저장본"
        if intraday and tdate == today_s:
            tnote2, tok = f"{src_lbl} · 오늘 장중 등락률", True
        elif tdate and tdate >= want_last:
            tnote2, tok = (f"{src_lbl} · 전 거래일({tdate}) 종가 기준이에요(장 시작 전에는 네이버가 전일 값을 줘요). 장 시작 뒤 다시 만들면 오늘 값으로 바뀌어요", True)
        else:
            tnote2, tok = (f"{src_lbl} · 기준일이 {tdate or '알 수 없음'}로 오래됐어요", False)
        fresh.append({"k": "테마 강세", "asof": tdate or "?", "ok": tok and bool(tmeta.get("live") or tdate >= want_last), "note": f"갱신 {tmeta.get('fetched', '')} · {tnote2}"})
        if not tok:
            warns.append(f"테마 기준일이 {tdate or '알 수 없음'}라 최근 강세 테마가 아니에요.")
    else:
        fresh.append({"k": "테마 강세", "asof": "-", "ok": False, "note": "테마 자료 없음"})
    fresh.append({"k": "미국 증시·VIX·환율", "asof": now.strftime("%Y-%m-%d %H:%M"), "ok": not gate["missing"], "note": "10분 이내 조회값" if not gate["missing"] else "받지 못함 — 중립 처리"})
    fresh.append({"k": "뉴스·재무", "asof": now.strftime("%H:%M"), "ok": True, "note": "상위 40종목을 이번에 조회(뉴스는 최대 10분 캐시)"})

    news, fins = {}, {}

    def check(tk):
        return tk, _news_for(tk), _fin_for(tk)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(check, r["ticker"]) for _, r, _, _ in top]
        t_end = time.time() + 45
        try:
            for f in as_completed(futs, timeout=max(1, t_end - time.time())):
                try:
                    tk, n, fn = f.result()
                    news[tk] = n
                    fins[tk] = fn
                except Exception:
                    pass
        except Exception:
            warns.append("뉴스·재무 조회가 오래 걸려 일부 종목은 해당 항목을 ‘자료 없음’으로 두었어요.")
    out, excluded = [], []
    for _, r, th, b in top:
        tk = r["ticker"]
        nw = classify_news(news[tk], now) if tk in news else None
        fin = assess_fin(fins.get(tk))
        if fin.get("exclude"):
            excluded.append({"ticker": tk, "name": r["name"], "why": fin["summary"]})
            continue
        fz = finalize(b, nw, fin)
        if not fz:
            excluded.append({"ticker": tk, "name": r["name"], "why": "위험 키워드 뉴스"})
            continue
        lv = levels(r["price"], r.get("cap_eok"))
        titles = [x.get("title") for x in (news.get(tk) or [])[:2] if x.get("title")]
        out.append({"ticker": tk, "name": r["name"], "market": r["market"], "cap_eok": r.get("cap_eok") or None, "price": r["price"], "day_pct": r.get("day_pct"),
                    "score": fz["score"], "parts": fz["parts"], "why": fz["why"][:7], "warns": fz["warns"][:5], "miss": fz["miss"],
                    "theme": ({"name": th["name"], "rate": th["rate"], "days": th["days_strong"]} if th else None), "levels": lv, "news": titles,
                    "fin": {"known": fin["known"], "summary": fin["summary"], "minor": fin["minor"], "good": fin["good"]}, "links": _links(tk)})
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
    if k < n_main:
        warns.append(f"기준 점수({ms}점) 이상인 종목이 {k}개뿐이에요. 억지로 채우지 않았어요.")
    if gate["label"] == "휴식 권장":
        warns.append("장 환경이 좋지 않아 ‘휴식 권장’이에요. 그래도 점수가 높은 종목 몇 개는 보여 드리지만 작게 접근하세요.")
    if excluded:
        warns.append(f"재무·뉴스 점검으로 제외한 종목 {len(excluded)}개: " + ", ".join(f"{x['name']}({x['why'][:22]})" for x in excluded[:6]) + (" …" if len(excluded) > 6 else ""))
    ths = sorted(info.values(), key=lambda t: -t["rate"])[:6]
    return {"ok": True, "target_date": target, "scan_date": scan_date, "stale": stale, "built_at": now.strftime("%Y-%m-%d %H:%M"), "pool": len(pool),
            "gate": gate, "macro": mac.get("text") or "", "themes": [{"name": t["name"], "rate": t["rate"], "breadth": t["breadth"], "days": t["days_strong"]} for t in ths],
            "warns": warns, "excluded": excluded[:30], "picks": out, "fresh": fresh, "theme_asof": tdate, "intraday": intraday,
            "pick_themes": _pick_themes(out)}


def _pick_themes(picks):
    """후보에 가장 많이 들어 있는 테마(상위 5) — 화면의 ‘강세 테마’가 후보와 맞는지 확인용."""
    cnt = {}
    for p in picks:
        t = p.get("theme")
        if t:
            c = cnt.setdefault(t["name"], {"name": t["name"], "n": 0, "rate": t["rate"]})
            c["n"] += 1
    return sorted(cnt.values(), key=lambda x: (-x["n"], -x["rate"]))[:5]


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
            _dbx("INSERT INTO dly_scalp(scalp_date,ticker,name,rk,main,score,gate,base_price,stop_pct,target_pct,target_day_pct) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                 "ON CONFLICT(scalp_date,ticker) DO NOTHING",
                 (t, p["ticker"], p["name"], p["rank"], 1 if p["main"] else 0, p["score"], g, p["price"], lv.get("stop_pct"), lv.get("target_pct"), lv.get("target_day_pct")))
        except Exception as e:
            print(f"[초단기] 저장 오류(무시): {e}")
    setting_set("scalp_last", json.dumps(res, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════
# 성과 확인 — 당일(오후 청산 가정) · 2영업일
# ══════════════════════════════════════════════════════════════
def classify_window(bars, stop_pct, target_pct):
    """bars: [(시가,고가,저가,종가)…] 첫 날 시가에 샀다고 가정. 날마다 저가가 손절선에, 고가가 목표선에 닿았는지 본다.
       같은 날 둘 다 닿으면 순서를 알 수 없어 손절로 보수적으로 센다. 끝까지 안 닿으면 마지막 종가로 평가.
       반환 (결과, {close, best, worst}) — 결과: win | loss | flat_up | flat_dn. close/best/worst 는 매수가 대비 %."""
    if not bars or not bars[0][0]:
        return "", {}
    entry = bars[0][0]
    best = max((b[1] / entry - 1) * 100 for b in bars)
    worst = min((b[2] / entry - 1) * 100 for b in bars)
    close = (bars[-1][3] / entry - 1) * 100
    res = None
    for o, h, l, c in bars:
        if (l / entry - 1) * 100 <= -stop_pct:
            res = "loss"
            break
        if (h / entry - 1) * 100 >= target_pct:
            res = "win"
            break
    if res is None:
        res = "flat_up" if close > 0 else "flat_dn"
    return res, {"close": round(close, 2), "best": round(best, 2), "worst": round(worst, 2)}


def _pnl(res, stop_pct, target_pct, close_pct):
    if res == "win":
        return target_pct
    if res == "loss":
        return -stop_pct
    return close_pct


def evaluate_pending():
    """결과가 비어 있는 기록(당일·2영업일)을 채운다. 반환 (새로 채운 건수, 아직 기다려야 하는 건수)."""
    now = _now_kst()
    today = now.strftime("%Y-%m-%d")
    after_close = now.hour >= 16
    try:
        pend = _dbx("SELECT scalp_date,ticker,base_price,stop_pct,target_pct,target_day_pct,result,res2 FROM dly_scalp "
                    "WHERE (result='' OR res2='') AND result<>'nodata' ORDER BY scalp_date", (), fetch=True) or []
    except Exception:
        pend = []
    wait = done = 0
    jobs = []
    for d, tk, base, sp, tp, tdp, res0, res2 in pend:
        d = str(d)
        if d > today or (d == today and not after_close):
            wait += 1
            continue
        sp = _f(sp, 2.5) or 2.5
        jobs.append((d, tk, _f(base), sp, _f(tp, sp * 2) or sp * 2, _f(tdp, sp) or sp, res0 or "", res2 or ""))

    def one(j):
        d, tk = j[0], j[1]
        try:
            df = _fetch_ohlcv(tk, d)
            if df is None or len(df) == 0:
                return j, None
            bars = []
            for idx, x in df.sort_index().iterrows():
                ds = idx.strftime("%Y-%m-%d")
                if ds < d:
                    continue
                if ds > today or (ds == today and not after_close):
                    break          # 아직 끝나지 않은 날은 쓰지 않는다
                bars.append((ds, float(x["Open"]), float(x["High"]), float(x["Low"]), float(x["Close"])))
                if len(bars) >= 3:
                    break
            return j, bars
        except Exception:
            return j, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        for j, bars in ex.map(one, jobs[:90]):
            d, tk, base, sp, tp, tdp, res0, res2 = j
            if bars is None:
                wait += 1
                continue
            if not bars or bars[0][0] != d:
                if d < (now - timedelta(days=6)).strftime("%Y-%m-%d"):
                    _dbx("UPDATE dly_scalp SET result='nodata', res2='nodata', eval_at=? WHERE scalp_date=? AND ticker=?", (today, d, tk))
                wait += 1
                continue
            b = [x[1:] for x in bars]
            changed = False
            if not res0:
                r0, _ = classify_window(b[:1], sp, tdp)
                _dbx("UPDATE dly_scalp SET o_next=?,h_next=?,l_next=?,c_next=?,result=?,eval_at=? WHERE scalp_date=? AND ticker=?", (b[0][0], b[0][1], b[0][2], b[0][3], r0, today, d, tk))
                changed = True
            if not res2 and len(b) >= 2:
                _dbx("UPDATE dly_scalp SET h1=?,l1=?,c1=? WHERE scalp_date=? AND ticker=?", (b[1][1], b[1][2], b[1][3], d, tk))
            if not res2 and len(b) >= 3:
                r2, _ = classify_window(b[:3], sp, tp)
                _dbx("UPDATE dly_scalp SET h2=?,l2=?,c2=?,res2=?,eval_at=? WHERE scalp_date=? AND ticker=?", (b[2][1], b[2][2], b[2][3], r2, today, d, tk))
                changed = True
            if changed:
                done += 1
            else:
                wait += 1
    return done, wait


def _agg(sel):
    n = len(sel)
    if not n:
        return {"n": 0}
    win = sum(1 for x in sel if x["res"] == "win")
    loss = sum(1 for x in sel if x["res"] == "loss")
    up = sum(1 for x in sel if x["close"] > 0)
    return {"n": n, "win": win, "loss": loss, "win_rate": round(win / n * 100, 1), "up_rate": round(up / n * 100, 1),
            "avg_close": round(sum(x["close"] for x in sel) / n, 2), "avg_best": round(sum(x["best"] for x in sel) / n, 2),
            "avg_rule": round(sum(x["pnl"] for x in sel) / n, 2)}


def stats():
    try:
        rows = _dbx("SELECT scalp_date,ticker,name,main,score,gate,base_price,stop_pct,target_pct,target_day_pct,o_next,h_next,l_next,c_next,result,h1,l1,c1,h2,l2,c2,res2 "
                    "FROM dly_scalp WHERE result NOT IN ('','nodata') ORDER BY scalp_date DESC, rk", (), fetch=True) or []
    except Exception:
        rows = []
    day, two, recent = [], [], []
    for (d, tk, nm, main, sc, g, base, sp, tp, tdp, o, h, l, c, r0, h1, l1, c1, h2, l2, c2, r2) in rows:
        o, h, l, c = _f(o), _f(h), _f(l), _f(c)
        if not o:
            continue
        sp = _f(sp, 2.5) or 2.5
        tp = _f(tp, sp * 2) or sp * 2
        tdp = _f(tdp, sp) or sp
        _, m0 = classify_window([(o, h, l, c)], sp, tdp)
        it = {"date": str(d), "ticker": tk, "name": nm, "main": int(main or 0), "score": int(sc or 0), "gate": g,
              "day": {"res": r0, **m0, "pnl": round(_pnl(r0, sp, tdp, m0["close"]), 2)}}
        day.append({"main": it["main"], "gate": g, "res": r0, **m0, "pnl": it["day"]["pnl"]})
        if r2 and r2 != "nodata" and _f(c2):
            _, m2 = classify_window([(o, h, l, c), (o, _f(h1), _f(l1), _f(c1)), (o, _f(h2), _f(l2), _f(c2))], sp, tp)
            it["two"] = {"res": r2, **m2, "pnl": round(_pnl(r2, sp, tp, m2["close"]), 2)}
            two.append({"main": it["main"], "gate": g, "res": r2, **m2, "pnl": it["two"]["pnl"]})
        recent.append(it)

    def split(lst):
        by_gate = {}
        for x in lst:
            if x["main"]:
                by_gate.setdefault(x["gate"], []).append(x)
        return {"main": _agg([x for x in lst if x["main"]]), "ref": _agg([x for x in lst if not x["main"]]), "by_gate": {k: _agg(v) for k, v in by_gate.items()}}
    return {"day": split(day), "two": split(two), "recent": recent[:40]}


# ══════════════════════════════════════════════════════════════
# AI 요청문 · 저장된 AI 답변
# ══════════════════════════════════════════════════════════════
def make_data_text(res):
    g = res["gate"]
    L = [f"장 시작 전 · 대상일 {res['target_date']} · 스캔 기준일 {res['scan_date']}",
         f"장 환경 판정: {g['label']} (점수 {g['score']}) — " + " / ".join(f"{a} {b:+.1f}({c})" for a, b, c in g["parts"]),
         "거시: " + (res.get("macro") or "자료 없음")]
    if res.get("themes"):
        L.append("강세 테마: " + ", ".join(f"{t['name']}({t['rate']:+.1f}%·{t['days']}일째)" for t in res["themes"]))
    L.append("")
    for p in res["picks"][:14]:
        lv = p.get("levels") or {}
        pt = p["parts"]
        L.append(f"{p['rank']}. {p['name']}({p['ticker']}) {'★' if p['main'] else ''}점수 {p['score']} [수급 {pt['flow']}·모멘텀 {pt['mom']}·추세 {pt['trend']}·테마 {pt['theme']}·뉴스 {pt['news']}·재무보정 {pt.get('fin', 0):+.0f}]")
        dp = p["day_pct"] if p["day_pct"] is not None else 0
        L.append(f"   전일 종가 {p['price']:,.0f}원({dp:+.1f}%) · 시총 {p['cap_eok'] or 0:,}억 · 진입 관심 {lv.get('entry_lo', 0):,}~{lv.get('entry_hi', 0):,} · 손절 {lv.get('stop', 0):,} · "
                 f"당일 목표 {lv.get('target_day', 0):,} · 2영업일 목표 {lv.get('target', 0):,}")
        if p["why"]:
            L.append("   근거: " + " / ".join(p["why"]))
        if p["warns"]:
            L.append("   주의: " + " / ".join(p["warns"]))
        L.append("   재무: " + ((p.get("fin") or {}).get("summary") or "자료 없음"))
        if p["news"]:
            L.append("   뉴스(제목): " + " | ".join(p["news"]))
    return "\n".join(L)


def make_prompt(res):
    now = _now_kst()
    body = prompt_get("scalp_pick") or SCALP_PROMPT_DEFAULT
    return _prompt_fill(body, target_date=res["target_date"], today=now.strftime("%Y-%m-%d"), data=make_data_text(res))


def _ai_get(date):
    try:
        r = _dbx("SELECT result FROM dly_scalp_ai WHERE scalp_date=?", (date,), fetch=True) or []
        return r[0][0] if r else ""
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════
# 블로그 글
# ══════════════════════════════════════════════════════════════
BLOG_SECTIONS = [("env", "장 환경"), ("picks", "관찰 후보"), ("ai", "AI 분석"), ("links", "종목 링크"), ("track", "지난 성과")]


def _strip_title_section(text):
    """AI 답변에서 '블로그 제목 후보' 덩어리(제목 줄 + 목록)는 본문에서 뺀다."""
    out, skip = [], False
    for ln in str(text or "").replace("\r", "").split("\n"):
        s = ln.strip()
        if re.match(r"^#{1,4}\s*\d+[.)]?\s*블로그 제목", s):
            skip = True
            continue
        if skip and re.match(r"^#{1,4}\s", s):
            skip = False
        if not skip:
            out.append(ln)
    return "\n".join(out).strip()


def _won(v):
    return f"{int(v):,}" if v is not None else "-"


def build_blog(res, ai_text="", inc=None, title="", site="", st=None):
    inc = {k: True for k, _ in BLOG_SECTIONS} if not isinstance(inc, dict) else {k: bool(inc.get(k, True)) for k, _ in BLOG_SECTIONS}
    date = res["target_date"]
    picks = res["picks"]
    main = [p for p in picks if p["main"]]
    show = main or picks[:5]
    n = len(show)
    g = res["gate"]
    titles = B.extract_titles(ai_text)
    auto_title = f"⚡ {date} 장 시작 전 단기 관찰 종목 {n}선 | 당일·1~2일 관점 | 수급·테마·뉴스·재무 점검"
    title = title or (titles[0] if titles else auto_title)
    names = [p["name"] for p in show[:12]]
    tags, tag_html = B.hashtags(names, date, extra=["장전체크", "단기매매", "오늘의관찰종목"])
    h = [B.seo_box(auto_title, "미국 증시·수급·테마·뉴스·재무를 겹쳐서 오늘 장 초반에 살펴볼 종목을 규칙으로 정리했어요. 당일 오후 청산 또는 1~2영업일 관점의 참고 자료예요.",
                   ["장전체크", "단기매매", "오늘의관찰종목", "수급", "테마"]),
         B.head_box(f"⚡ PRE-MARKET WATCH · {date}", f'장 시작 전 단기 관찰 종목 <span style="color:{B.GOLD};">{n}선</span>', "수급 · 테마 · 뉴스 · 재무 점검 · 당일/1~2영업일 관점")]
    if inc["env"]:
        col = {"공격 가능": "#047857", "중립": "#1d4ed8", "관망·보수적": "#b45309", "휴식 권장": "#b91c1c"}.get(g["label"], "#1d4ed8")
        rows = "".join(f'<tr><td style="padding:4px 8px;font-size:12.5px;color:#4b5563;border-bottom:1px solid #f1f5f9;">{E(a)}</td><td style="padding:4px 8px;font-size:12.5px;color:#111827;border-bottom:1px solid #f1f5f9;">{E(c)}</td></tr>'
                       for a, b, c in g["parts"])
        th = ""
        if res.get("themes"):
            th = '<p style="font-size:13px;color:#1f2937;line-height:1.9;margin:8px 0 0;">강세 테마: ' + " · ".join(
                f'<b>{E(t["name"])}</b>({t["rate"]:+.1f}%{"·" + str(t["days"]) + "일째" if t["days"] >= 2 else ""})' for t in res["themes"][:5]) + "</p>"
        h.append(B.side_title("&#127758; 오늘의 장 환경", "#2563eb")
                 + f'<p style="font-size:15px;font-weight:900;color:{col};margin:6px 0;">장 환경: {E(g["label"])} (점수 {g["score"]:+.1f}) — 오늘은 상위 {len(main)}종목을 관찰 후보로 봅니다</p>'
                 + (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;{B.FONT}">{rows}</table>' if rows else "")
                 + (f'<p style="font-size:12.5px;color:#6b7280;margin:6px 0 0;">거시: {E(res.get("macro") or "")}</p>' if res.get("macro") else "") + th)
    if inc["picks"]:
        h.append(B.side_title("&#128203; 관찰 후보 (전일 종가 기준 · 장 시작 전)" + ("" if main else ' <span style="font-size:12px;color:#94a3b8;">기준 점수를 넘는 종목이 없어 상위 5개만 참고로 보여요</span>'), "#d97706"))
        for p in show:
            lv = p.get("levels") or {}
            pt = p["parts"]
            body = [f'구성: 수급 {pt["flow"]:.0f} · 모멘텀 {pt["mom"]:.0f} · 추세 {pt["trend"]:.0f} · 테마 {pt["theme"]:.0f} · 뉴스 {pt["news"]:.0f}' + (f' · 재무보정 {pt.get("fin", 0):+.0f}' if pt.get("fin") else "")]
            if p["why"]:
                body.append("근거: " + E(" / ".join(p["why"])))
            if (p.get("fin") or {}).get("summary"):
                body.append("재무: " + E(p["fin"]["summary"]))
            if p["warns"]:
                body.append('<span style="color:#b45309;">주의: ' + E(" / ".join(p["warns"])) + "</span>")
            if p["news"]:
                body.append("뉴스(제목 기준): " + E(" | ".join(p["news"])))
            if lv:
                body.append(f'<b>가격 관찰선</b>(전일 종가 {_won(p["price"])}원 기준): 진입 관심 {_won(lv["entry_lo"])}~{_won(lv["entry_hi"])} · 손절 {_won(lv["stop"])}(-{lv["stop_pct"]}%) · '
                            f'당일 목표 {_won(lv["target_day"])}(+{lv["target_day_pct"]}%) · 2영업일 목표 {_won(lv["target"])}(+{lv["target_pct"]}%) · 시가가 {_won(lv["chase"])}원 이상이면 추격 금지')
            if inc["links"] and site:
                tk = p["ticker"]
                body.append(f'<a href="{E(site)}/?t={tk}" target="_blank" style="color:#2563eb;font-weight:700;text-decoration:none;">&#128200; {E(p["name"])} 종목분석</a> &nbsp;·&nbsp; '
                            f'<a href="{E(site)}/?t={tk}&amp;m=deep" target="_blank" style="color:#7c3aed;font-weight:700;text-decoration:none;">&#127963; {E(p["name"])} 심층분석</a>')
            h.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-collapse:collapse;margin:0 0 12px;{B.FONT}"><tr>'
                     f'<td bgcolor="#0d1b3e" style="background-color:#0d1b3e;padding:9px 12px;"><span style="font-size:15px;font-weight:900;color:#ffffff;">{p["rank"]}. {E(p["name"])}</span> '
                     f'<span style="font-size:12px;color:#cbd5e1;">{E(p["ticker"])} · {E(p["market"])} · 시총 {_won(p["cap_eok"])}억</span></td>'
                     f'<td bgcolor="#0d1b3e" align="right" style="background-color:#0d1b3e;padding:9px 12px;font-size:16px;font-weight:900;color:{B.GOLD};">{p["score"]}점</td></tr>'
                     f'<tr><td colspan="2" style="padding:10px 12px;font-size:13px;color:#1f2937;line-height:1.9;">' + "<br>".join(body) + "</td></tr></table>")
    if inc["ai"] and ai_text.strip():
        h.append(B.side_title("&#129302; AI 분석", "#0d1b3e"))
        h.append(B.ai_to_html(_strip_title_section(ai_text)))
    if inc["track"] and st:
        d, t = (st.get("day") or {}).get("main") or {}, (st.get("two") or {}).get("main") or {}
        if (d.get("n") or 0) >= 5:
            def tr(lbl, v):
                return (f'<tr><td style="padding:5px 8px;border:1px solid #e5e7eb;font-size:12.5px;">{lbl}</td><td align="right" style="padding:5px 8px;border:1px solid #e5e7eb;font-size:12.5px;">{v.get("n", 0)}건</td>'
                        f'<td align="right" style="padding:5px 8px;border:1px solid #e5e7eb;font-size:12.5px;">{v.get("win_rate", "-")}%</td><td align="right" style="padding:5px 8px;border:1px solid #e5e7eb;font-size:12.5px;">{v.get("up_rate", "-")}%</td>'
                        f'<td align="right" style="padding:5px 8px;border:1px solid #e5e7eb;font-size:12.5px;">{v.get("avg_close", 0):+.2f}%</td></tr>')
            h.append(B.side_title("&#128202; 지난 관찰 후보의 결과 (시가 매수 가정 · 참고)", "#16a34a")
                     + f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;{B.FONT}"><tr><th align="left" style="padding:5px 8px;background:#f1f5f9;font-size:12px;">구분</th><th style="padding:5px 8px;background:#f1f5f9;font-size:12px;">건수</th>'
                       f'<th style="padding:5px 8px;background:#f1f5f9;font-size:12px;">목표 도달</th><th style="padding:5px 8px;background:#f1f5f9;font-size:12px;">종가 플러스</th><th style="padding:5px 8px;background:#f1f5f9;font-size:12px;">평균 수익률</th></tr>'
                     + tr("당일(오후 청산)", d) + (tr("2영업일", t) if t.get("n") else "") + '</table><p style="font-size:11.5px;color:#9ca3af;margin:4px 0 0;">같은 날 손절·목표에 모두 닿으면 손절로 계산했고, 수수료·세금·체결 오차는 빠져 있어요.</p>')
    h.append('<p style="font-size:12px;color:#6b7280;line-height:1.8;margin:12px 0 0;">※ 규칙 기반 자동 선별 결과로 매수 권유가 아닙니다. 뉴스는 제목만 확인했고, 장중 수급·호가·프로그램 매매는 반영하지 않았습니다. '
             '장 시작 후 시가·거래량·호가를 직접 확인하고, 손절 기준을 먼저 정한 뒤 판단하세요. 투자 책임은 본인에게 있습니다.</p>')
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════
def _last():
    try:
        return json.loads(setting_get("scalp_last") or "") or None
    except Exception:
        return None


def _feat_deny(fid, msg):
    return _admin_json({"error": msg, "feature": fid, "login": C.viewer_token() == C.GUEST, "need": C.feature_need_text(MENU, fid)}, 403)


@bp.route("/admin/api/scalp/state", methods=["GET"])
def api_state():
    deny = _admin_deny()
    if deny:
        return deny
    if _gw() and not _fok("list"):
        return _feat_deny("list", "이 기능은 아직 열려 있지 않아요.")
    last = _last()
    tgt = (last or {}).get("target_date") or target_session_date()
    out = {"last": last, "target": target_session_date(), "ai": _ai_get(tgt) if _fok("ai") else "", "stats": stats() if _fok("track") else None}
    if _gw() and last:       # 회원 화면: 관리용 경고·제외 목록은 주지 않는다
        last = dict(last)
        last.pop("excluded", None)
        out["last"] = last
    return _admin_json(out)


@bp.route("/admin/api/scalp/run", methods=["POST"])
def api_run():
    deny = _admin_deny(write=True)
    if deny or _gw():
        return deny or _admin_json({"error": "관리자만 쓸 수 있어요."}, 403)
    b = _json_body() or {}
    try:
        res = build(str(b.get("date") or "") or None)
    except Exception as e:
        print(f"[초단기] 만들기 오류: {type(e).__name__}: {e}")
        return _admin_json({"error": "후보를 만드는 중 오류가 났어요: " + str(e)[:80]}, 500)
    if res.get("error"):
        return _admin_json(res, 400)
    res["diff"] = _diff_with_prev(res)
    _save(res)
    _alog("scalp_run", f"{res['target_date']} {res['gate']['label']} {len(res['picks'])}")
    return _admin_json(dict(res, ai=_ai_get(res["target_date"])))


@bp.route("/admin/api/scalp/track", methods=["POST"])
def api_track():
    deny = _admin_deny(write=True)
    if deny or _gw():
        return deny or _admin_json({"error": "관리자만 쓸 수 있어요."}, 403)
    try:
        done, wait = evaluate_pending()
    except Exception as e:
        return _admin_json({"error": "성과 확인 중 오류: " + str(e)[:80]}, 500)
    return _admin_json({"ok": True, "done": done, "wait": wait, "stats": stats()})


@bp.route("/admin/api/scalp/prompt", methods=["GET"])
def api_prompt():
    deny = _admin_deny()
    if deny or _gw():
        return deny or _admin_json({"error": "관리자만 쓸 수 있어요."}, 403)
    last = _last()
    if not last or not last.get("picks"):
        return _admin_json({"error": "먼저 [⚡ 후보 만들기]를 누르세요."}, 404)
    return _admin_json({"prompt": make_prompt(last), "count": len(last["picks"]), "date": last["target_date"]})


@bp.route("/admin/api/scalp/ai", methods=["POST"])
def api_ai_save():
    deny = _admin_deny(write=True)
    if deny or _gw():
        return deny or _admin_json({"error": "관리자만 쓸 수 있어요."}, 403)
    d = _json_body() or {}
    date = str(d.get("date") or "").strip()
    text = str(d.get("result") or "").strip()[:60000]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return _admin_json({"error": "날짜가 올바르지 않아요."}, 400)
    if len(text) < 50:
        return _admin_json({"error": "AI 답변이 너무 짧아요."}, 400)
    _dbx("INSERT INTO dly_scalp_ai(scalp_date,result,updated) VALUES(?,?,?) ON CONFLICT(scalp_date) DO UPDATE SET result=excluded.result, updated=excluded.updated",
         (date, text, int(time.time())))
    _alog("scalp_ai", f"{date} {len(text)}자")
    return _admin_json({"ok": True, "titles": B.extract_titles(text)})


@bp.route("/admin/api/scalp/blog", methods=["POST"])
def api_blog():
    deny = _admin_deny()
    if deny or _gw():
        return deny or _admin_json({"error": "관리자만 쓸 수 있어요."}, 403)
    d = _json_body() or {}
    last = _last()
    if not last or not last.get("picks"):
        return _admin_json({"error": "먼저 [⚡ 후보 만들기]를 누르세요."}, 404)
    ai = str(d.get("ai") or "")[:60000] or _ai_get(last["target_date"])
    try:
        site = (_public_site_url() or "").rstrip("/")
    except Exception:
        site = ""
    b = build_blog(last, ai, d.get("inc"), str(d.get("title") or "").strip()[:150], site, stats())
    pseudo = "S" + last["target_date"].replace("-", "")[2:]
    logs, warn = B.dup_info(pseudo, "scalp")
    b.update({"ticker": pseudo, "name": f"초단기 {last['target_date']}", "dups": logs, "dup_warn": warn})
    return _admin_json(b)


# ══════════════════════════════════════════════════════════════
# 화면 탭 (관리자 화면 + 공개했을 때의 /m/scalp)
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var SC={last:null,stats:null,ai:'',target:'',busy:false,flag:{blog:false,posted:false},blogPanel:null};
var SCFLOW=['ai','blog','post'];
function scSt(n,css){n.style.cssText=css;return n}
function scBadge(t,bg,fg){var b=el('span',null,t);scSt(b,'display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.5px;font-weight:800;margin:0 4px 4px 0;background:'+bg+';color:'+fg);return b}
function scFmt(n){return n==null?'-':Math.round(n).toLocaleString('ko-KR')}
function scPct(v){return v==null?'-':(v>0?'+':'')+v.toFixed(1)+'%'}
function scGo2(id){var e=$(id);if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'start'})}
function scLink(txt,href,col){var a=el('a',null,txt);a.href=href;a.target='_blank';a.rel='noopener';scSt(a,'display:inline-block;padding:4px 10px;border-radius:8px;border:1px solid '+col+';color:'+col+';font-size:12.5px;font-weight:800;text-decoration:none;margin:4px 6px 0 0');return a}
var SCACTS={
 ai:function(next){if(!SC.last)return;if((SC.ai||'').trim()){next();return}scGo2('scAiSec');scAIRun()},
 blog:function(next){if(!SC.last||!SC.blogPanel)return;if(SC.flag.blog&&SC.blogPanel.built()){next();return}scGo2('scBlogSec');SC.blogPanel.rebuild().then(function(j){if(j&&!j.error)next()})},
 post:function(next){if(scPostGo(true))next()}};
function scPostGo(auto){var P=SC.blogPanel;if(!P)return false;if(P.built()){P.copyOpen(auto);return true}
 if(!SC.flag.blog){if(!auto)toast('먼저 글 만들기를 해 주세요');return false}
 P.rebuild().then(function(j){if(j)P.copyOpen(auto)});return true}
function scLoad(p){p.innerHTML='';var box=el('div');box.id='scBox';p.appendChild(box);
 if(MEMBER_MODE&&!ftOk('list')){var c=el('div','c');c.appendChild(scSt(el('b',null,'⚡ 초단기 후보 — 장 시작 전'),'font-size:18px'));c.appendChild(el('div','note','후보 종목·장 환경·가격 관찰선을 보여주는 기능이에요. 참고 자료이며 투자 권유가 아니에요.'));box.appendChild(c);ftSec(c,'list');return}
 scDraw();
 api('/admin/api/scalp/state').then(function(j){if(cur!=='sc'&&!MEMBER_MODE)return;SC.last=j.last;SC.stats=j.stats;SC.ai=j.ai||'';SC.target=j.target;scDraw()}).catch(function(){})}
function scDraw(){var p=$('scBox');if(!p)return;p.innerHTML='';SC.blogPanel=null;SC.flag.blog=false;SC.flag.posted=false;
 var hd=el('div','c');scSt(hd,'background:linear-gradient(135deg,#0a1228,#1b2f66);color:#fff;border:0');hd.appendChild(scSt(el('div',null,'⚡ 초단기 후보 — 장 시작 전'),'font-size:20px;font-weight:900'));
 hd.appendChild(scSt(el('div',null,'관점: 오늘 시가 부근에서 사서 오후에 정리하거나, 1~2영업일 안에 오를 가능성이 있는 종목을 찾아요. 전일 종가·수급·테마·뉴스·재무·미국 증시를 겹쳐 규칙으로 골라요(재무가 나쁜 종목은 제외). 참고 자료이며 매수 권유가 아니에요.'),'font-size:13px;opacity:.9;margin-top:6px;line-height:1.6'));
 var r=el('div');scSt(r,'margin-top:12px;display:flex;gap:8px;flex-wrap:wrap');
 var go=bt('⚡ 후보 만들기','bt',function(){scRun(go)});go.id='scGo';r.appendChild(adm(go));
 r.appendChild(adm(bt('📊 지난 성과 확인','bt3',function(){scTrack()})));
 r.appendChild(adm(bt('📋 AI 요청문 복사','bt3',function(){scPrompt()})));hd.appendChild(r);p.appendChild(hd);
 if(!MEMBER_MODE){var sp=el('div');sp.id='scSteps';p.appendChild(sp);scSteps()}
 var L=SC.last;if(!L){p.appendChild(el('div','c','아직 만든 후보가 없어요. '+(MEMBER_MODE?'관리자가 후보를 만들면 여기에 보여요.':'[⚡ 후보 만들기]를 눌러 보세요. (먼저 [🌟 오늘추천]에서 스캔 + [시장수급]/[테마] 가져오기를 해 두면 정확해져요)')));scStats(p);return}
 scGate(p,L);scList(p,L);scAiSec(p);if(!MEMBER_MODE)scBlogSec(p);scStats(p)}
function scSteps(){var h=$('scSteps');if(!h||MEMBER_MODE||!window.FlowBar)return;var d=[!!SC.last,!!(SC.ai||'').trim(),!!SC.flag.blog,!!SC.flag.posted];
 window.FlowBar.draw(h,{steps:[
  {t:'후보 만들기',sub:d[0]?'완료 · 다시 만들기':'눌러서 시작',done:d[0],go:function(){var g=$('scGo');if(g)scRun(g)}},
  {t:'AI 분석',sub:d[1]?'저장됨 · 다시 받기':'눌러서 시작',done:d[1],go:function(){if(!SC.last){toast('먼저 후보를 만드세요');return}scGo2('scAiSec');scAIRun()}},
  {t:'글 만들기',sub:d[2]?'완료 · 다시 만들기':'눌러서 만들기',done:d[2],go:function(){if(!SC.blogPanel){toast('먼저 후보를 만드세요');return}scGo2('scBlogSec');SC.blogPanel.rebuild()}},
  {t:'블로그에 쓰기',sub:d[3]?'복사·열기 완료':'복사하고 블로그 열기',done:d[3],go:function(){scPostGo(false)}}],
  runAll:function(){scAll()},allLabel:'⚡ 블로그까지 한 번에',
  note:'[⚡ 블로그까지 한 번에]는 후보 만들기 → AI 분석(요청문 열기·답변 복사) → 글 만들기 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'})}
function scAll(){var g=$('scGo');if(!g)return;toast('⚡ 후보를 만들고 블로그까지 이어서 진행해요');scRun(g,function(){MiniFlow.force('scalp',SCFLOW,SCACTS)})}
function scGate(p,L){var g=L.gate,c=el('div','c');var col=g.label==='공격 가능'?'#047857':(g.label==='중립'?'#1d4ed8':(g.label==='관망·보수적'?'#b45309':'#b91c1c'));
 var t=el('div');scSt(t,'display:flex;align-items:center;gap:10px;flex-wrap:wrap');t.appendChild(scBadge('장 환경: '+g.label,col,'#fff'));t.appendChild(el('b',null,'점수 '+g.score));
 t.appendChild(el('span','m','추천 '+g.n_main+'종목 · 기준 '+g.min_score+'점 이상 · 대상일 '+L.target_date+' · 스캔 기준일 '+L.scan_date+' · 만든 시각 '+L.built_at));c.appendChild(t);
 if(g.parts&&g.parts.length){var u=el('div','note');u.textContent=g.parts.map(function(x){return x[0]+' '+(x[1]>0?'+':'')+x[1]+' ('+x[2]+')'}).join(' · ');c.appendChild(u)}
 if(L.macro)c.appendChild(el('div','note','거시: '+L.macro));
 if(L.themes&&L.themes.length){var th=el('div');scSt(th,'margin-top:6px');th.appendChild(el('span','m','강세 테마('+(L.theme_asof||'기준일 모름')+' 기준) '));L.themes.forEach(function(x){th.appendChild(scBadge(x.name+' '+scPct(x.rate)+(x.days>=4?' 🔥'+x.days+'일째':''),x.days>=4?'#fee2e2':'#e0e7ff',x.days>=4?'#991b1b':'#3730a3'))});c.appendChild(th)}
 if(L.pick_themes&&L.pick_themes.length){var pt=el('div');scSt(pt,'margin-top:4px');pt.appendChild(el('span','m','후보에 많이 든 테마 '));L.pick_themes.forEach(function(x){pt.appendChild(scBadge(x.name+' '+x.n+'종목','#fef3c7','#92400e'))});c.appendChild(pt)}
 (L.warns||[]).forEach(function(w){var d=el('div','note','⚠ '+w);d.style.color='#b45309';c.appendChild(d)});p.appendChild(c);scFresh(p,L)}
function scFresh(p,L){var c=el('div','c');c.appendChild(scSt(el('b',null,'📅 자료 기준 — 이 후보가 어느 시점 자료로 만들어졌는지'),'font-size:14px'));
 (L.fresh||[]).forEach(function(f){var d=el('div','note',(f.ok?'✅ ':'⚠ ')+f.k+' · '+f.asof+' · '+f.note);if(!f.ok)d.style.color='#b45309';c.appendChild(d)});
 var df=L.diff;if(df){var t=el('div','note','🔄 직전 후보('+df.prev_at+') 대비: 점수가 바뀐 종목 '+df.moved+'개(평균 '+(df.avg>0?'+':'')+df.avg+'점)'+(df.new.length?' · ★ 새로 진입: '+df.new.join(', '):'')+(df.dropped.length?' · ★ 탈락: '+df.dropped.join(', '):'')+(df.gate_prev&&df.gate_prev!==L.gate.label?' · 장 환경 '+df.gate_prev+' → '+L.gate.label:''));scSt(t,'margin-top:6px;font-weight:700');c.appendChild(t)}
 c.appendChild(el('div','note','후보를 만들 때마다 네이버 실시간 테마와 상위 후보의 종목별 최신 수급을 직접 조회해요(따로 [가져오기]를 하지 않아도 돼요). 기술 지표(RSI·이평선)는 [🌟 오늘추천] 스캔 값이라 새로 스캔하면 후보 폭이 넓어져요. 장 시작 전에는 테마 등락률이 전일 값이고, 장 시작 뒤 다시 만들면 오늘 값으로 바뀌어요.'));
 p.appendChild(c)}
function scList(p,L){var c=el('div','c');c.appendChild(scSt(el('b',null,'후보 TOP '+L.picks.length+' (스캔 풀 '+L.pool+'종목 중)'),'font-size:15px'));
 c.appendChild(el('div','note','점수 = 수급 30 + 거래·가격 모멘텀 25 + 추세 위치 20 + 테마 15 + 뉴스 10 (+ 재무 보정). ★ 는 오늘 장 환경 기준 ‘추천 개수’ 안에 든 종목이고, 나머지는 참고용이에요. 재무가 나쁜 종목은 이미 빠져 있어요.'));
 L.picks.forEach(function(x){var row=el('div');scSt(row,'border:1px solid '+(x.main?'#f0b429':'#e2e8f0')+';border-radius:12px;padding:10px 12px;margin-top:8px;background:'+(x.main?'#fffbeb':'#fff'));
  var h=el('div');scSt(h,'display:flex;gap:8px;align-items:baseline;flex-wrap:wrap');var nm=el('b',null,(x.main?'★ ':'')+x.rank+'. '+x.name);nm.setAttribute('data-tk',x.ticker);h.appendChild(nm);h.appendChild(el('span','m',x.ticker+' · '+x.market+' · 시총 '+scFmt(x.cap_eok)+'억'));
  var sc=el('b',null,x.score+'점');scSt(sc,'margin-left:auto;font-size:16px;color:'+(x.score>=70?'#047857':(x.score>=60?'#1d4ed8':'#64748b')));h.appendChild(sc);row.appendChild(h);
  var pt=x.parts,b=el('div');scSt(b,'margin-top:4px');[['수급',pt.flow,30],['모멘텀',pt.mom,25],['추세',pt.trend,20],['테마',pt.theme,15],['뉴스',pt.news,10]].forEach(function(k){var q=k[1]/k[2];b.appendChild(scBadge(k[0]+' '+Math.round(k[1]),q>=.7?'#d1fae5':(q>=.4?'#e0f2fe':'#f1f5f9'),q>=.7?'#065f46':(q>=.4?'#075985':'#475569')))});
  if(pt.fin)b.appendChild(scBadge('재무보정 '+(pt.fin>0?'+':'')+Math.round(pt.fin),pt.fin>0?'#d1fae5':'#fee2e2',pt.fin>0?'#065f46':'#991b1b'));
  if(x.theme)b.appendChild(scBadge('🏷 '+x.theme.name+' '+scPct(x.theme.rate),'#ede9fe','#5b21b6'));
  (x.miss||[]).forEach(function(m){b.appendChild(scBadge(m+' 자료 없음','#f1f5f9','#64748b'))});row.appendChild(b);
  row.appendChild(el('div','note','전일 종가 '+scFmt(x.price)+'원 ('+scPct(x.day_pct)+')'));
  if(x.why&&x.why.length)row.appendChild(el('div','note','✅ '+x.why.join(' · ')));
  if(x.fin&&x.fin.summary){var fz=el('div','note','💼 재무: '+x.fin.summary);if(x.fin.minor&&x.fin.minor.length)fz.style.color='#b45309';row.appendChild(fz)}
  if(x.warns&&x.warns.length){var w=el('div','note','⚠ '+x.warns.join(' · '));w.style.color='#b45309';row.appendChild(w)}
  if(x.news&&x.news.length)row.appendChild(el('div','note','📰 '+x.news.join(' | ')+'  (제목 기준)'));
  var lv=x.levels;if(lv){var d=el('div');scSt(d,'margin-top:6px;padding:6px 8px;border-radius:8px;background:#f1f5f9;font-size:12.5px;line-height:1.7');
   d.textContent='진입 관심 '+scFmt(lv.entry_lo)+' ~ '+scFmt(lv.entry_hi)+'원 · 손절 '+scFmt(lv.stop)+'원(-'+lv.stop_pct+'%) · 당일 오후 목표 '+scFmt(lv.target_day)+'원(+'+lv.target_day_pct+'%) · 2영업일 목표 '+scFmt(lv.target)+'원(+'+lv.target_pct+'%) · 시가가 '+scFmt(lv.chase)+'원(+5%)보다 높게 열면 추격 금지 · '+scFmt(lv.gap_floor)+'원(-2%) 아래로 열면 제외 · 장 시작 30분 안에 +1%를 못 가면 정리 검토';row.appendChild(d)}
  var lk=x.links||{stock:'/?t='+x.ticker,deep:'/?t='+x.ticker+'&m=deep'};var lr=el('div');lr.appendChild(scLink('📈 종목분석',lk.stock,'#2563eb'));lr.appendChild(scLink('🏛 심층분석',lk.deep,'#7c3aed'));row.appendChild(lr);
  c.appendChild(row)});p.appendChild(c)}
function scAiSec(p){var c=el('div','c');c.id='scAiSec';c.appendChild(scSt(el('b',null,'🤖 AI 분석'),'font-size:15px'));
 c.appendChild(el('div','note',MEMBER_MODE?'AI가 후보를 정리한 결과예요. 참고용이며 틀릴 수 있어요.':'후보·장 환경·수급·테마·뉴스·재무 요약을 담은 요청문을 설정된 AI에 보내요. 답변을 복사하고 이 탭으로 돌아오면 자동으로 읽어 와 저장하고, 블로그 글에 포함돼요.'));
 var st=el('div','m');st.id='scAiSt';c.appendChild(st);
 if(!MEMBER_MODE){var r=el('div');scSt(r,'margin:6px 0;display:flex;gap:8px;flex-wrap:wrap');r.appendChild(bt((SC.ai||'').trim()?'🔁 AI 분석 다시 받기':'🤖 AI 분석 받기','bt',function(){scAIRun()}));c.appendChild(r)}
 var ta=el('textarea');ta.id='scAiTa';ta.placeholder=MEMBER_MODE?'아직 AI 분석이 없어요.':'AI 답변을 직접 붙여넣어도 돼요.';scSt(ta,'width:100%;min-height:120px;box-sizing:border-box;margin-top:6px');ta.value=SC.ai||'';if(MEMBER_MODE)ta.readOnly=true;
 ta.oninput=function(){SC.ai=ta.value;scAiState()};c.appendChild(ta);
 if(!MEMBER_MODE){var sr=el('div');scSt(sr,'margin-top:6px');sr.appendChild(bt('💾 이 답변 저장','bt2',function(){scAiSave(ta.value)}));c.appendChild(sr)}
 p.appendChild(c);scAiState()}
function scAiState(msg){var z=$('scAiSt');if(!z)return;var t=SC.ai||'';z.textContent=(msg?msg+' · ':'')+(t.trim()?('✅ AI 글 '+t.length.toLocaleString()+'자'+(MEMBER_MODE?'':' — 블로그 글에 포함돼요.')):(MEMBER_MODE?'아직 AI 분석이 없어요.':'아직 AI 글이 없어요(없어도 블로그 글은 만들 수 있어요).'))}
function scAiSave(t){if((t||'').trim().length<50){toast('AI 답변을 먼저 넣으세요');return Promise.resolve(false)}
 toast('⏳ AI 답변을 저장하는 중…');return apiJ('/admin/api/scalp/ai',{date:SC.last.target_date,result:t}).then(function(j){if(j.error){toast('⚠ '+j.error);return false}SC.ai=t;var ta=$('scAiTa');if(ta)ta.value=t;scAiState('저장했어요');scSteps();toast('✅ AI 분석을 저장했어요');return true})}
function scAIRun(){if(!SC.last){toast('먼저 후보를 만드세요');return}if(!window.MiniAI){toast('AI 도우미 파일(menu_ui.py)이 올라가지 않았어요.');return}
 api('/admin/api/scalp/prompt').then(function(j){if(j.error){toast('⚠ '+j.error);return}
  window.MiniAI.run({title:'초단기 후보 AI — '+j.date,key:'scalp',steps:[{label:j.date+' 후보 '+j.count+'종목',prompt:j.prompt}],minLen:300,hint:'AI가 "## 1. 한줄 결론 …" 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){var ok=/##\s*1\./.test(t)||t.length>600;var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString()+'자 — '+t.slice(0,260)+(t.length>260?' …':'');return {node:x,canApply:t.trim().length>=200,strict:ok}},
   apply:function(t){return scAiSave(t).then(function(ok){if(!ok)return {message:'읽었지만 저장하지 못했어요.'};setTimeout(function(){MiniFlow.run('scalp',SCFLOW,SCACTS,'ai')},50);return {message:'AI 분석을 저장했어요.'}})}})},function(){toast('⚠ 요청문을 만들지 못했어요')})}
function scBlogSec(p){var c=el('div','c');c.id='scBlogSec';c.appendChild(scSt(el('b',null,'📝 블로그 글 (⚡ 장 시작 전 단기 관찰 종목)'),'font-size:15px'));
 c.appendChild(el('div','note','후보 카드마다 [종목분석]·[심층분석] 링크가 기본으로 들어가요(‘종목 링크’ 항목에서 끌 수 있어요). 블로그 글쓰기 주소·자동 열기는 [⚙ 블로그 설정]에서 정해요.'));
 var bx=el('div');c.appendChild(bx);p.appendChild(c);if(!window.BlogKit)return;
 var d=SC.last.target_date,secs=[['env','장환경'],['picks','관찰후보'],['ai','AI분석'],['links','종목링크'],['track','지난성과']];
 SC.blogPanel=window.BlogKit.panel(bx,{idp:'sc',key:'scalp',kind:'scalp',ticker:'S'+d.replace(/-/g,'').slice(2),name:'초단기 '+d,sections:secs,dup_warn:'',onBuilt:function(){SC.flag.blog=true;SC.flag.posted=false;scSteps()},onCopied:function(){SC.flag.posted=true;scSteps()},
  build:function(inc,title){return apiJ('/admin/api/scalp/blog',{ai:SC.ai||'',inc:inc,title:title})}})}
function scStatBlock(c,title,S){var m=(S&&S.main)||{n:0};c.appendChild(scSt(el('div',null,title),'font-weight:800;margin-top:10px'));
 if(!m.n){c.appendChild(el('div','note','아직 확인된 기록이 없어요.'));return}
 var tl=el('div');scSt(tl,'display:flex;gap:8px;flex-wrap:wrap;margin-top:6px');[['★ 건수',m.n+'건'],['목표 도달',m.win_rate+'%'],['종가 플러스',m.up_rate+'%'],['평균 종가 수익',scPct(m.avg_close)],['평균 최고가',scPct(m.avg_best)],['규칙 적용 평균',scPct(m.avg_rule)]].forEach(function(k){var t=el('div');scSt(t,'padding:8px 12px;border-radius:10px;background:#f1f5f9');t.appendChild(scSt(el('div',null,k[0]),'font-size:11.5px;color:#64748b'));t.appendChild(scSt(el('div',null,k[1]),'font-size:16px;font-weight:900'));tl.appendChild(t)});c.appendChild(tl);
 var rf=S.ref||{n:0};c.appendChild(el('div','note','참고 순위(★ 밖) '+(rf.n?rf.n+'건 · 목표 도달 '+rf.win_rate+'% · 평균 종가 수익 '+scPct(rf.avg_close):'기록 없음')+' — ★이 참고보다 좋아야 점수가 의미 있어요.'));
 var bg=Object.keys(S.by_gate||{});if(bg.length)c.appendChild(el('div','note','장 환경별(★만): '+bg.map(function(k){var v=S.by_gate[k];return k+' '+v.n+'건 '+(v.n?'종가+ '+v.up_rate+'%':'')}).join(' · ')))}
function scStats(p){var S=SC.stats;if(!S)return;var c=el('div','c');c.appendChild(scSt(el('b',null,'📊 지난 성과 (시가에 샀다고 가정 · 참고)'),'font-size:15px'));
 if(!((S.day&&S.day.main&&S.day.main.n)||0)){c.appendChild(el('div','note','아직 확인된 기록이 없어요. 후보를 만든 날의 장이 끝나면 [📊 지난 성과 확인]을 눌러 시가·고가·저가·종가를 가져와요(2영업일 결과는 이틀 뒤). 최소 20~30건은 쌓여야 의미가 생겨요.'));p.appendChild(c);return}
 scStatBlock(c,'① 당일 오후 청산 (시가 매수 → 당일 종가, 목표 = 손절폭 1배)',S.day);scStatBlock(c,'② 2영업일 (시가 매수 → 2영업일 안에 목표 = 손절폭 2배)',S.two);
 c.appendChild(el('div','note','※ 같은 날 손절·목표에 모두 닿았으면 손절로 계산(보수적). 수수료·거래세·체결 오차는 빠져 있어요.'));
 var det=el('details');det.appendChild(el('summary',null,'최근 기록 '+S.recent.length+'건'));var nm={win:'🎯 목표',loss:'🛑 손절',flat_up:'➕ 플러스',flat_dn:'➖ 마이너스'};
 S.recent.forEach(function(x){var d=el('div','note',x.date+' '+(x.main?'★':' ')+' '+x.name+' · 당일 종가 '+scPct(x.day.close)+' ('+(nm[x.day.res]||x.day.res)+')'+(x.two?' · 2영업일 '+scPct(x.two.close)+' ('+(nm[x.two.res]||x.two.res)+')':' · 2영업일 결과 대기'));det.appendChild(d)});c.appendChild(det);p.appendChild(c)}
function scRun(btn,then){if(SC.busy){toast('이미 만드는 중이에요');return}SC.busy=true;btn.disabled=true;btn.textContent='⏳ 만드는 중… (최대 1분)';toast('⏳ 후보를 만드는 중이에요 (수급·테마·뉴스·재무 확인, 최대 1분)');
 apiJ('/admin/api/scalp/run',{}).then(function(j){SC.busy=false;if(j.error){toast('⚠ '+j.error);scDraw();return}SC.last=j;SC.ai=j.ai||'';toast('✅ 후보 '+j.picks.length+'종목을 만들었어요 (장 환경: '+j.gate.label+')');
  api('/admin/api/scalp/state').then(function(s){SC.stats=s.stats}).catch(function(){}).then(function(){scDraw();if(then){setTimeout(then,100)}else{setTimeout(function(){MiniFlow.run('scalp',SCFLOW,SCACTS)},200)}})},function(){SC.busy=false;toast('⚠ 후보 만들기에 실패했어요');scDraw()})}
function scTrack(){toast('⏳ 지난 후보의 결과를 가져오는 중이에요');apiJ('/admin/api/scalp/track',{}).then(function(j){if(j.error){toast('⚠ '+j.error);return}SC.stats=j.stats;toast('✅ '+j.done+'건 확인 완료'+(j.wait?' · '+j.wait+'건은 아직 결과가 없어요':''));var ai=SC.ai;scDraw()},function(){toast('⚠ 성과 확인에 실패했어요')})}
function scPrompt(){api('/admin/api/scalp/prompt').then(function(j){if(j.error){toast('⚠ '+j.error);return}var t=j.prompt,ok=false;try{var ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.appendChild(ta);ta.select();ok=document.execCommand('copy');document.body.removeChild(ta)}catch(e){}
  try{if(!ok&&navigator.clipboard){navigator.clipboard.writeText(t);ok=true}}catch(e){}toast(ok?'✅ AI 요청문을 복사했어요 ('+t.length.toLocaleString()+'자) — AI 창에 붙여 넣으세요':'⚠ 복사하지 못했어요. 브라우저 권한을 확인해 주세요')},function(){toast('⚠ 요청문을 만들지 못했어요')})}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_settings({"scalp_last": ""})
    C.register_menu({"id": MENU, "label": "초단기(장전)", "icon": "⚡", "public_path": "/m/scalp", "admin_path": "/admin#sc",
                     "desc": "전일 종가·수급·테마·뉴스·재무·미국 증시를 겹쳐 오늘 시가 부근에서 당일 오후 또는 1~2영업일 안에 살펴볼 후보를 규칙으로 골라요. 재무가 나쁜 종목은 제외해요. 참고 자료이며 투자 권유가 아니에요.",
                     "access": "admin"})
    C.register_prompt("scalp_pick", {
        "title": "초단기 후보(장전) AI 프롬프트", "default": SCALP_PROMPT_DEFAULT, "required": ["{data}"], "must_have": ["## 1."],
        "vars": "{data}=후보·장 환경 자료(필수) · {target_date} · {today}",
        "desc": "초단기(장전) 후보를 AI에게 정리시키는 요청문. '## 1.' 형식 제목을 유지해야 블로그 글에 예쁘게 들어가요."})
    C.register_admin_tab("sc", "⚡ 초단기(장전)", TAB_JS, "scLoad", menu=MENU)
    C.register_flow(MENU, "⚡ 초단기(장전)", "① 후보 만들기(직접 시작)", [
        {"id": "ai", "label": "② AI 분석", "desc": "후보가 만들어지면 AI 요청문 창을 자동으로 열어요. 답변을 복사해 돌아오면 다음 단계로 이어져요(이미 저장돼 있으면 건너뛰어요)."},
        {"id": "blog", "label": "③ 글 만들기", "desc": "AI 분석 다음에 블로그용 글(HTML)을 자동으로 만들어요. 후보마다 종목분석·심층분석 링크가 들어가요."},
        {"id": "post", "label": "④ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요."}])
    F = C.register_feature
    F(MENU, "list", "후보·장 환경 보기", "장 환경 판정, 후보 종목의 점수·근거·재무 점검·가격 관찰선·종목분석/심층분석 링크.", default="admin", endpoints=["/admin/api/scalp/state"])
    F(MENU, "ai", "AI 분석 결과 보기", "AI가 후보를 정리해 저장해 둔 글(읽기 전용).", default="admin")
    F(MENU, "track", "지난 성과 보기", "후보를 시가에 샀다고 가정한 당일 오후 청산·2영업일 결과와 승률(읽기 전용).", default="admin")
    # 후보 만들기(run)·성과 확인(track POST)·AI 저장(ai)·요청문(prompt)·블로그 글(blog)은 관리자 업무 → 어떤 기능에도 넣지 않았다(회원 화면에서는 열리지 않음).
    return bp
