"""🧪 관리자 분석실 — 관리자 모드에서만 종목분석 화면에 붙는 '확장 분석 + 블로그 글쓰기' 도구.

공개 이용자에게는 아무것도 보이지 않는다(서버 API·JS 파일 모두 관리자 로그인 필요).

구성
  ① 5축 종합점수(기술·모멘텀·수급·재무·밸류) — 원본의 통합점수 구조를 따르되 항목을 더 쪼갠 버전
  ② 수급(외국인·기관·개인 최근 10~20거래일, 연속 순매수) — 네이버 모바일 API(로그인 불필요)
  ③ 재무 심층분석(성장·수익·안정·주주환원) + 공시 분류(위험/호재/참고) + (선택) DART 주요계정
  ④ AI 종합 리포트 프롬프트(관리자가 프롬프트 탭에서 수정 가능, 수동 AI 도우미로 진행)
  ⑤ 원본 방식 블로그 HTML(표·인라인 서식 — 네이버 블로그 에디터에 붙여넣기) + 작성 이력(중복 경고)

DART API 키는 코드에 넣지 않는다. 환경변수 DART_API_KEY 가 있을 때만 DART 주요계정을 추가로 보여준다.
"""
import html as _html
import io
import json
import re
import time
import zipfile
import os
import xml.etree.ElementTree as ET
from flask import Blueprint, Response
from menu_ctx import C
import menu_blog as B
import menu_img as IMG

bp = Blueprint("lab", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_dbrows", "_http", "_cache_get", "_cache_set",
               "_get_analysis", "_now_kst", "prompt_get", "setting_get", "get_ticker_info")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

E = lambda s: _html.escape("" if s is None else str(s), quote=True)
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")


# ══════════════════════════════════════════════════════════════
# 작은 도구
# ══════════════════════════════════════════════════════════════
def _num(v):
    """'+46,127' '46.41%' '-' → 숫자(float) 또는 None"""
    try:
        s = str(v).replace(",", "").replace("%", "").replace("+", "").replace("원", "").replace("배", "").strip()
        if s in ("", "-", "N/A", "None"):
            return None
        return float(s)
    except Exception:
        return None


def _clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def _grade(sc):
    return "높은 편" if sc >= 70 else ("보통" if sc >= 50 else "낮은 편")      # 지표 수준 표현(기업에 대한 긍정·주의 평가처럼 읽히지 않게)


def _eok(v):
    """억원 숫자 → 읽기 쉬운 글자"""
    if v is None:
        return "-"
    return f"{v / 10000:,.1f}조" if abs(v) >= 10000 else f"{v:,.0f}억"


def _fmt_date(d):
    d = str(d or "")
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d


# ══════════════════════════════════════════════════════════════
# ② 수급 — 네이버 모바일 trend (최대 20거래일)
# ══════════════════════════════════════════════════════════════
def _trend_rows(ticker):
    key = ("lab_trend", ticker)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    rows = []
    try:
        r = _http().get(f"https://m.stock.naver.com/api/stock/{ticker}/trend", params={"pageSize": 20}, timeout=6,
                        headers=C.NAVER_M_HEADERS)
        if r.status_code == 200 and isinstance(r.json(), list):
            for d in r.json():
                close = _num(d.get("closePrice"))
                rows.append({"date": _fmt_date(d.get("bizdate")), "close": close,
                             "foreign": _num(d.get("foreignerPureBuyQuant")), "inst": _num(d.get("organPureBuyQuant")),
                             "indiv": _num(d.get("individualPureBuyQuant")), "volume": _num(d.get("accumulatedTradingVolume")),
                             "fhold": _num(d.get("foreignerHoldRatio"))})
    except Exception as e:
        print(f"[분석실] 수급 조회 오류(무시): {e}")
    _cache_set(key, rows, 600 if rows else 60)
    return rows


def supply_analysis(rows):
    """rows: 최신순. 반환: 기간별 순매수(주·억원), 연속일수, 점수(0~100), 요약 문장."""
    rows = [r for r in rows if r.get("close")]
    if not rows:
        return None
    out = {"rows": rows[:10], "n": len(rows)}
    per = {}
    for n in (1, 3, 5, 10, 20):
        sub = rows[:n]
        if len(sub) < min(n, 1):
            continue
        d = {"days": len(sub)}
        for k in ("foreign", "inst", "indiv"):
            d[k] = sum((r.get(k) or 0) for r in sub)
            d[k + "_eok"] = round(sum((r.get(k) or 0) * r["close"] for r in sub) / 1e8, 1)
        d["value_eok"] = round(sum((r.get("volume") or 0) * r["close"] for r in sub) / 1e8, 1)
        per[str(n)] = d
    out["per"] = per

    def streak(k):
        s, sign = 0, 0
        for r in rows:
            v = r.get(k) or 0
            sg = 1 if v > 0 else (-1 if v < 0 else 0)
            if s == 0:
                if sg == 0:
                    break
                sign = sg
            if sg != sign:
                break
            s += 1
        return {"days": s, "dir": "순매수" if sign > 0 else ("순매도" if sign < 0 else "-")} if s else {"days": 0, "dir": "-"}
    out["streak"] = {"foreign": streak("foreign"), "inst": streak("inst")}
    p5 = per.get("5") or per.get("3") or per.get("1")
    ratio = ((p5["foreign_eok"] + p5["inst_eok"]) / p5["value_eok"]) if p5 and p5["value_eok"] else 0
    sc = 50 + _clamp(ratio * 250, -30, 30)
    for k, w in (("foreign", 1.0), ("inst", 1.0)):
        st = out["streak"][k]
        if st["days"] >= 2:
            sc += w * min(st["days"], 5) * (2 if st["dir"] == "순매수" else -2)
    p20 = per.get("20") or per.get("10")
    if p20 and p20["value_eok"]:
        sc += _clamp((p20["foreign_eok"] + p20["inst_eok"]) / p20["value_eok"] * 60, -8, 8)
    sc = int(round(_clamp(sc)))
    out["score"] = sc
    fs, ins = out["streak"]["foreign"], out["streak"]["inst"]
    bits = []
    if p5:
        bits.append(f"최근 {p5['days']}거래일 외국인 {p5['foreign_eok']:+,.0f}억·기관 {p5['inst_eok']:+,.0f}억·개인 {p5['indiv_eok']:+,.0f}억")
    if fs["days"] >= 2:
        bits.append(f"외국인 {fs['days']}일 연속 {fs['dir']}")
    if ins["days"] >= 2:
        bits.append(f"기관 {ins['days']}일 연속 {ins['dir']}")
    if p5 and p5["foreign_eok"] > 0 and p5["inst_eok"] > 0:
        bits.append("외국인·기관 동반 순매수")
    elif p5 and p5["foreign_eok"] < 0 and p5["inst_eok"] < 0:
        bits.append("외국인·기관 동반 순매도")
    out["summary"] = " · ".join(bits)
    out["fhold"] = rows[0].get("fhold")
    return out


# ══════════════════════════════════════════════════════════════
# ③ 재무 심층분석 (네이버 재무 + 선택 DART)
# ══════════════════════════════════════════════════════════════
def _fin_table(payload):
    fa = ((payload.get("details") or {}).get("financials") or {}).get("annual") or {}
    pers, rows = fa.get("periods") or [], {r["name"]: r["values"] for r in (fa.get("rows") or [])}
    if not pers or not rows:
        return None
    idx = list(range(len(pers)))[-5:]
    keep = ["매출액", "영업이익", "당기순이익", "영업이익률", "순이익률", "ROE", "부채비율", "당좌비율", "주당배당금", "EPS", "BPS"]
    return {"periods": [{"title": pers[i]["title"], "estimate": bool(pers[i].get("estimate"))} for i in idx],
            "rows": [{"name": k, "values": [rows[k][i] if i < len(rows[k]) else None for i in idx]} for k in keep if k in rows]}


def _last_actual(tbl, name):
    """가장 최근 '실적' 값과 그 직전 값."""
    if not tbl:
        return None, None
    vals = next((r["values"] for r in tbl["rows"] if r["name"] == name), None)
    if not vals:
        return None, None
    act = [v for v, p in zip(vals, tbl["periods"]) if not p["estimate"] and v is not None]
    return (act[-1] if act else None), (act[-2] if len(act) >= 2 else None)


def _growth(cur, prv):
    if cur is None or prv in (None, 0):
        return None
    return round((cur - prv) / abs(prv) * 100, 1)


def deep_fin(payload, dart=None):
    """성장성·수익성·안정성·주주환원 4개 항목을 0~100 점수와 한 줄 평가로."""
    tbl = _fin_table(payload)
    f = payload.get("fundamentals") or {}
    out = {"table": tbl, "items": [], "comments": [], "score": None}
    if not tbl:
        return out
    rev, rev0 = _last_actual(tbl, "매출액")
    op, op0 = _last_actual(tbl, "영업이익")
    ni, ni0 = _last_actual(tbl, "당기순이익")
    opm, _ = _last_actual(tbl, "영업이익률")
    roe, _ = _last_actual(tbl, "ROE")
    debt, _ = _last_actual(tbl, "부채비율")
    quick, _ = _last_actual(tbl, "당좌비율")
    dps, dps0 = _last_actual(tbl, "주당배당금")
    items = []

    g_rev, g_op = _growth(rev, rev0), _growth(op, op0)
    sc = 50
    notes = []
    if g_rev is not None:
        sc += _clamp(g_rev * 1.2, -20, 20)
        notes.append(f"매출 {g_rev:+.1f}%")
    if g_op is not None:
        sc += _clamp(g_op * 0.3, -15, 15)
        notes.append(f"영업이익 {g_op:+.1f}%")
    if op is not None and op0 is not None and op0 < 0 <= op:
        sc += 10
        notes.append("흑자전환")
    if op is not None and op0 is not None and op0 > 0 > op:
        sc -= 15
        notes.append("적자전환")
    items.append(("성장성", int(_clamp(sc)), " · ".join(notes) or "자료 부족"))

    sc, notes = 50, []
    if opm is not None:
        sc += _clamp((opm - 5) * 2.5, -25, 30)
        notes.append(f"영업이익률 {opm:.1f}%")
    if roe is not None:
        sc += _clamp((roe - 8) * 1.5, -20, 20)
        notes.append(f"ROE {roe:.1f}%")
    if ni is not None and ni < 0:
        sc -= 10
        notes.append("순손실")
    items.append(("수익성", int(_clamp(sc)), " · ".join(notes) or "자료 부족"))

    sc, notes = 55, []
    if debt is not None:
        sc += _clamp((100 - debt) * 0.25, -25, 20)
        notes.append(f"부채비율 {debt:.0f}%")
    if quick is not None:
        sc += _clamp((quick - 100) * 0.1, -10, 10)
        notes.append(f"당좌비율 {quick:.0f}%")
    items.append(("안정성", int(_clamp(sc)), " · ".join(notes) or "자료 부족"))

    sc, notes = 40, []
    div = f.get("DIV")
    if div:
        sc += _clamp(div * 10, 0, 40)
        notes.append(f"배당수익률 {div:.2f}%")
    if dps:
        sc += 10
        notes.append(f"주당배당금 {dps:,.0f}원")
        if dps0 and dps >= dps0:
            sc += 10
            notes.append("배당 유지·증가")
    items.append(("주주환원", int(_clamp(sc)), " · ".join(notes) or "배당 정보 없음"))

    out["items"] = [{"name": n, "score": s, "grade": _grade(s), "note": t} for n, s, t in items]
    out["score"] = int(round(sum(s for _, s, _ in items[:3]) / 3 * 0.85 + items[3][1] * 0.15))
    cm = []
    if g_rev is not None and g_rev >= 10:
        cm.append(f"매출이 전년 대비 {g_rev:+.1f}% 늘어 외형 성장이 뚜렷합니다.")
    elif g_rev is not None and g_rev < 0:
        cm.append(f"매출이 전년 대비 {g_rev:+.1f}% 줄었습니다. 원인(업황·일회성)을 확인해 보세요.")
    if opm is not None and opm >= 15:
        cm.append(f"영업이익률 {opm:.1f}%로 수익성이 높은 편입니다.")
    elif opm is not None and opm < 3:
        cm.append(f"영업이익률이 {opm:.1f}%로 낮아 비용 부담이 큰 구조입니다.")
    if debt is not None and debt >= 200:
        cm.append(f"부채비율이 {debt:.0f}%로 높아 금리·차환 위험을 살펴야 합니다.")
    elif debt is not None and debt < 50:
        cm.append(f"부채비율 {debt:.0f}%로 재무 안정성이 좋습니다.")
    if f.get("PER") and f.get("PBR"):
        cm.append(f"PER {f['PER']}배 · PBR {f['PBR']}배" + (f" (업종 PER {f['sector_PER']}배)" if f.get("sector_PER") else "") + " 수준입니다.")
    out["comments"] = cm
    if dart:
        out["dart"] = dart
    return out


# ── (선택) DART 주요계정 ──
_DART_MAP = {}
_DART_MAP_AT = 0


def _dart_key():
    return (os.environ.get("DART_API_KEY") or "").strip()


def _dart_corp(ticker):
    global _DART_MAP, _DART_MAP_AT
    key = _dart_key()
    if not key:
        return None
    if not _DART_MAP or time.time() - _DART_MAP_AT > 7 * 86400:
        r = _http().get("https://opendart.fss.or.kr/api/corpCode.xml", params={"crtfc_key": key}, timeout=25)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        mp = {}
        for it in root.iter("list"):
            sc = (it.findtext("stock_code") or "").strip()
            if sc:
                mp[sc] = (it.findtext("corp_code") or "").strip()
        if mp:
            _DART_MAP, _DART_MAP_AT = mp, time.time()
    return _DART_MAP.get(ticker)


def dart_accounts(ticker):
    """최근 3개 사업연도 주요계정(억원). 키가 없거나 실패하면 None."""
    key = _dart_key()
    if not key:
        return None
    ck = ("lab_dart", ticker)
    hit = _cache_get(ck)
    if hit is not None:
        return hit or None
    out = None
    try:
        corp = _dart_corp(ticker)
        if corp:
            years = {}
            this_year = _now_kst().year
            for y in range(this_year - 1, this_year - 4, -1):
                r = _http().get("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json",
                                params={"crtfc_key": key, "corp_code": corp, "bsns_year": str(y), "reprt_code": "11011"}, timeout=10)
                j = r.json() if r.status_code == 200 else {}
                if j.get("status") != "000":
                    continue
                rows = j.get("list") or []
                pick = {}
                for fs in ("CFS", "OFS"):       # 연결 우선
                    for it in rows:
                        if it.get("fs_div") == fs and it.get("account_nm") not in pick:
                            v = _num(it.get("thstrm_amount"))
                            if v is not None:
                                pick[it["account_nm"]] = round(v / 1e8, 1)
                    if pick:
                        break
                if pick:
                    years[str(y)] = {k: pick.get(k) for k in ("자산총계", "부채총계", "자본총계", "매출액", "영업이익", "당기순이익")}
            if years:
                out = {"years": years, "source": "DART 사업보고서(연결 우선)"}
    except Exception as e:
        print(f"[분석실] DART 조회 오류(무시): {e}")
    _cache_set(ck, out or {}, 6 * 3600 if out else 600)
    return out


# ── 공시 ──
_DISC_RULES = [
    ("risk", "유상증자", ("유상증자",)), ("risk", "감자", ("감자결정", "무상감자", "유상감자")),
    ("risk", "전환사채·BW", ("전환사채", "신주인수권부사채", "교환사채")), ("risk", "대주주 변경", ("최대주주 변경", "최대주주변경", "경영권")),
    ("risk", "횡령·배임", ("횡령", "배임")), ("risk", "관리·상폐", ("관리종목", "상장폐지", "거래정지", "상장적격성", "불성실공시")),
    ("risk", "소송·회생", ("소송", "회생", "파산", "부도")), ("risk", "감사의견", ("감사의견", "의견거절", "한정")),
    ("pos", "공급계약", ("단일판매", "공급계약", "수주")), ("pos", "자사주", ("자기주식취득", "자기주식 취득", "자사주")),
    ("pos", "배당", ("현금ㆍ현물배당", "현금배당", "배당결정")), ("pos", "실적", ("영업(잠정)실적", "잠정실적", "매출액또는손익구조")),
    ("pos", "특허·승인", ("특허", "품목허가", "임상")),
]


def classify_disclosure(title):
    t = str(title or "")
    for lvl, tag, keys in _DISC_RULES:
        if any(k in t for k in keys):
            return lvl, tag
    return "info", "참고"


def disclosures(ticker, n=30):
    ck = ("lab_disc", ticker)
    hit = _cache_get(ck)
    if hit is not None:
        return hit
    out = []
    try:
        r = _http().get(f"https://m.stock.naver.com/api/stock/{ticker}/disclosure", params={"page": 1, "pageSize": n}, timeout=6,
                        headers=C.NAVER_M_HEADERS)
        if r.status_code == 200 and isinstance(r.json(), list):
            for d in r.json():
                lvl, tag = classify_disclosure(d.get("title"))
                out.append({"date": str(d.get("datetime") or "")[:10], "title": _html.unescape(str(d.get("title") or "")).strip(),
                            "author": d.get("author") or "", "level": lvl, "tag": tag})
    except Exception as e:
        print(f"[분석실] 공시 조회 오류(무시): {e}")
    _cache_set(ck, out, 600 if out else 60)
    return out


# ══════════════════════════════════════════════════════════════
# ① 5축 점수
# ══════════════════════════════════════════════════════════════
def five_axis(payload, sup, deep):
    p, f = payload.get("price") or {}, payload.get("fundamentals") or {}
    axes = []
    # 기술
    ts = p.get("tech_score") or 0
    rsi = p.get("rsi") if p.get("rsi") is not None else 50
    rsi_add = 2 if 40 <= rsi <= 65 else (-1 if rsi > 75 or rsi < 25 else 0)
    raw = ts + rsi_add
    sc = int(round(_clamp((raw + 5) / 13 * 100)))
    nt = [f"RSI {rsi}", f"이평선 {p.get('ma_align', '-')}"]
    if p.get("ma20_diff") is not None:
        nt.append(f"20일선 이격 {p['ma20_diff']}%")
    if p.get("bb_squeeze"):
        nt.append("볼린저 수축")
    axes.append({"key": "tech", "name": "기술", "score": sc, "note": " · ".join(nt)})
    # 모멘텀
    m = 50.0
    nt = []
    if p.get("pct20") is not None:
        m += _clamp(p["pct20"] * 0.8, -20, 20)
        nt.append(f"20일 {p['pct20']:+.1f}%")
    if p.get("pct5") is not None:
        m += _clamp(p["pct5"] * 0.8, -8, 8)
        nt.append(f"5일 {p['pct5']:+.1f}%")
    if p.get("pos52") is not None:
        m += _clamp((p["pos52"] - 50) * 0.2, -10, 10)
        nt.append(f"52주 위치 {p['pos52']}%")
    al = p.get("ma_align")
    m += 8 if al == "정배열" else (-8 if al == "역배열" else 0)
    if p.get("vol_ratio") and p["vol_ratio"] >= 2 and (p.get("day_pct") or 0) > 0:
        m += 5
        nt.append(f"거래량 {p['vol_ratio']}배")
    axes.append({"key": "mom", "name": "모멘텀", "score": int(round(_clamp(m))), "note": " · ".join(nt) or "자료 부족"})
    # 수급
    if sup:
        axes.append({"key": "sup", "name": "수급", "score": sup["score"], "note": sup["summary"] or "자료 부족"})
    # 재무
    if deep and deep.get("score") is not None:
        axes.append({"key": "fin", "name": "재무", "score": deep["score"], "note": " / ".join(f"{i['name']} {i['score']}" for i in deep["items"][:3])})
    # 밸류
    v, nt = 50.0, []
    per, pbr, div, sp = f.get("PER"), f.get("PBR"), f.get("DIV"), f.get("sector_PER")
    if per and per > 0:
        v += 18 if per < 10 else (8 if per < 20 else (-4 if per < 50 else -14))
        if sp and per < sp:
            v += 6
        nt.append(f"PER {per}")
    elif per is not None and per <= 0:
        v -= 12
        nt.append("적자(PER 없음)")
    if pbr and pbr > 0:
        v += 10 if pbr < 1 else (3 if pbr < 3 else (-6 if pbr > 10 else 0))
        nt.append(f"PBR {pbr}")
    if div:
        v += _clamp(div * 3, 0, 10)
        nt.append(f"배당 {div}%")
    cons = (payload.get("details") or {}).get("consensus") or {}
    if cons.get("target_price") and p.get("price"):
        up = (cons["target_price"] / p["price"] - 1) * 100
        v += _clamp(up * 0.25, -8, 10)
        nt.append(f"목표주가 대비 {up:+.0f}%")
    axes.append({"key": "val", "name": "밸류", "score": int(round(_clamp(v))), "note": " · ".join(nt) or "자료 부족"})
    W = {"tech": .22, "mom": .18, "sup": .26, "fin": .22, "val": .12}
    tw = sum(W[a["key"]] for a in axes)
    total = int(round(sum(a["score"] * W[a["key"]] for a in axes) / tw)) if tw else 0
    for a in axes:
        a["grade"] = _grade(a["score"])
    return {"axes": axes, "total": total, "grade": _grade(total)}


# ══════════════════════════════════════════════════════════════
# 종합 — API 에서 쓰는 한 덩어리
# ══════════════════════════════════════════════════════════════
def build_ext(ticker):
    payload, _hit = _get_analysis(ticker)
    if not payload or payload.get("error"):
        return None, (payload or {}).get("error") or "분석 결과를 가져오지 못했어요."
    sup = supply_analysis(_trend_rows(ticker))
    dart = None
    try:
        dart = dart_accounts(ticker)
    except Exception:
        dart = None
    deep = deep_fin(payload, dart)
    sc = five_axis(payload, sup, deep)
    disc = disclosures(ticker)
    news = ((payload.get("details") or {}).get("news") or [])[:8]
    risk = [d for d in disc if d["level"] == "risk"]
    out = {"ticker": ticker, "name": payload.get("name"), "market": payload.get("market"), "as_of": payload.get("as_of"),
           "score": sc, "supply": sup, "fin": deep, "disc": disc, "disc_risk": len(risk), "news": news,
           "dart_enabled": bool(_dart_key()), "price": payload.get("price") and {k: payload["price"].get(k) for k in (
               "price", "prev", "day_pct", "volume", "vol_ratio", "pos52", "rsi", "ma_align", "ma20_diff", "pct5", "pct20", "high_52w", "low_52w")},
           "fundamentals": payload.get("fundamentals"), "cap": (payload.get("details") or {}).get("market_cap"),
           "consensus": (payload.get("details") or {}).get("consensus"), "delisting": payload.get("delisting_risk")}
    return out, None


def data_text(x):
    """AI 에게 줄 데이터 요약(글자). 없는 값은 쓰지 않는다."""
    p, f = x.get("price") or {}, x.get("fundamentals") or {}
    L = [f"종목: {x['name']}({x['ticker']}) · 시장 {x.get('market')} · 시가총액 {x.get('cap') or '-'} · 기준 {x.get('as_of')}"]
    if p:
        L.append(f"주가: {(p.get('price') or 0):,}원 (전일비 {p.get('day_pct')}%), 5일 {p.get('pct5')}%, 20일 {p.get('pct20')}%, 52주 위치 {p.get('pos52')}% (최고 {p.get('high_52w')}, 최저 {p.get('low_52w')})")
        L.append(f"기술: RSI {p.get('rsi')}, 이평선 {p.get('ma_align')}, 20일선 이격 {p.get('ma20_diff')}%, 거래량비 {p.get('vol_ratio')}배")
    L.append("밸류: " + ", ".join(f"{k} {v}" for k, v in f.items() if v is not None))
    c = x.get("consensus")
    if c:
        L.append(f"애널리스트 컨센서스: 목표주가 {c.get('target_price')}, 투자의견 평균 {c.get('recomm_mean')} ({c.get('date')})")
    s = x["score"]
    L.append(f"체력지표 {s['total']}(공개 시세·재무를 규칙으로 계산한 참고 값 · 기업 평가점수 아님 · {s['grade']}): " + ", ".join(f"{a['name']} {a['score']}" for a in s["axes"]))
    sp = x.get("supply")
    if sp:
        L.append("수급: " + sp["summary"])
        for r in sp["rows"][:5]:
            L.append(f"  {r['date']} 종가 {r['close']:,.0f} 외국인 {r['foreign']:+,.0f}주 기관 {r['inst']:+,.0f}주 개인 {r['indiv']:+,.0f}주")
    t = (x.get("fin") or {}).get("table")
    if t:
        L.append("재무(연간, 억원·%): " + " | ".join(t["periods"][i]["title"] + (":예상" if t["periods"][i]["estimate"] else "") for i in range(len(t["periods"]))))
        for r in t["rows"]:
            L.append(f"  {r['name']}: " + ", ".join("-" if v is None else f"{v:,.1f}" for v in r["values"]))
    for it in (x.get("fin") or {}).get("items", []):
        L.append(f"  {it['name']} {it['score']}점 — {it['note']}")
    d = (x.get("fin") or {}).get("dart")
    if d:
        L.append("DART 주요계정(억원): " + json.dumps(d["years"], ensure_ascii=False))
    if x.get("disc"):
        L.append("최근 공시:")
        for d in x["disc"][:10]:
            L.append(f"  {d['date']} [{d['tag']}] {d['title']}")
    if x.get("news"):
        L.append("최근 뉴스 제목:")
        for n in x["news"][:8]:
            L.append(f"  {n.get('date')} {n.get('press')} — {n.get('title')}")
    dr = x.get("delisting")
    if isinstance(dr, dict) and dr.get("level") not in (None, "", "none"):
        L.append(f"상장폐지·거래정지 위험 신호({dr.get('level')}): " + " / ".join(str(r) for r in (dr.get("reasons") or []))[:400])
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════
# ④ AI 종합 리포트 프롬프트
# ══════════════════════════════════════════════════════════════
LAB_REPORT_DEFAULT = """당신은 한국 주식 시장을 설명하는 데이터 애널리스트입니다. 아래 [데이터]만 근거로 '{name}({ticker})' 종합 분석 글을 작성하세요.
오늘은 {today}입니다. 블로그에 올릴 글이므로 독자(주식 초보~중급)가 읽기 쉽게 쓰되, 아래 규칙을 반드시 지키세요.

[규칙]
- [데이터]에 없는 숫자·사실을 지어내지 않습니다. 모르면 "자료에 없음"이라고 씁니다.
- 매수·매도·목표가를 권유하거나 단정하지 않습니다. "~로 보입니다", "~를 확인해 볼 만합니다"처럼 관찰 중심으로 씁니다.
- 수치는 구체적으로 인용하되(예: 외국인 5일 +120억), 해석은 한두 문장으로 짧게 씁니다.
- 공시·뉴스는 제목만 있으므로 내용을 추측하지 말고 "제목 기준"임을 밝힙니다.
- 마크다운 제목은 아래 8개를 순서대로, 정확히 "## 번호. 제목" 형식으로만 씁니다. 소제목 아래는 짧은 문단과 "- " 목록을 섞어 씁니다.

## 1. 한줄 결론
## 2. 핵심 포인트
## 3. 주가 흐름과 기술적 위치
## 4. 수급 분석
## 5. 재무와 밸류에이션
## 6. 공시·뉴스 체크
## 7. 리스크와 확인할 점
## 8. 블로그 제목 후보 (검색에 잘 걸리는 제목 3개, 각 줄 앞에 "- ")

[데이터]
{data}
"""


# ══════════════════════════════════════════════════════════════
# ⑤ 블로그 HTML (원본 방식: 표 + 인라인 서식 → 네이버 블로그 붙여넣기)
# ══════════════════════════════════════════════════════════════
NAVY, GOLD, BROWN, LINE, TXT, FONT = B.NAVY, B.GOLD, B.BROWN, B.LINE, B.TXT, B.FONT
SECTIONS = [("summary", "핵심 지표"), ("score", "5축 체력지표"), ("supply", "수급"), ("fin", "재무·심층분석"), ("disc", "공시"), ("news", "뉴스"), ("pubai", "AI 분석(하단)"), ("ai", "AI 종합 리포트")]
_up, _h, _bar, _tc = B.updown, B.title_bar, B.bar, B.tone
ai_to_html, extract_titles, engage_box, risk_box = B.ai_to_html, B.extract_titles, B.engage_box, B.risk_box


def hashtags(x, date_str, extra=()):
    return B.hashtags([x["name"], (x["name"] or "") + "주가"], date_str, extra=extra)


def build_blog(x, ai_text="", inc=None, title="", pub_ai=""):
    inc = {k: True for k, _ in SECTIONS} if inc is None else inc
    now = _now_kst()
    date_k = f"{now.year}년 {now.month}월 {now.day}일"
    p, f = x.get("price") or {}, x.get("fundamentals") or {}
    s = x["score"]
    name, ticker = x["name"], x["ticker"]
    titles = extract_titles(ai_text) or extract_titles(pub_ai)
    if not title:
        title = titles[0] if titles else f"{name}({ticker}) 주가 분석 — 수급·재무·공시 한눈에 ({date_k})"
    sup = x.get("supply")
    kw = [f"{name} 주가", f"{name} 전망", f"{name} 수급", f"{ticker}", "AI 주식 분석", "기술적 분석", date_k.replace("년 ", "").replace("월 ", "").replace("일", "")]
    dl_lead, dl_bottom, dl_tags = B.delist_blocks(x.get("delisting"), name, ticker)   # 상폐·거래정지 위험 신호가 있으면 글 위·아래에 경고
    tags, tag_html = hashtags(x, date_k, extra=dl_tags)
    naver = f"https://finance.naver.com/item/main.naver?code={ticker}"
    h = []
    # SEO 박스
    h.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;border-collapse:collapse;{FONT}"><tr>'
             f'<td bgcolor="#ffffff" style="background-color:#ffffff;border:2px solid {BROWN};padding:14px 18px;">'
             f'<div style="font-size:17px;font-weight:900;color:#111827;line-height:1.55;word-break:keep-all;">&#128204; {E(title)}</div>'
             f'<div style="font-size:13px;color:{TXT};line-height:1.8;margin-top:8px;">&#128161; {E(name)}의 주가 위치·수급·재무·공시를 데이터로 정리한 분석입니다. (기준 {E(x.get("as_of"))})<br>'
             f'<span style="color:#8a7f6a;font-size:12px;">&#128273; 검색키워드: {E(", ".join(kw))}</span></div></td></tr></table>')
    # 헤더
    h.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;{FONT}"><tr>'
             f'<td bgcolor="{NAVY}" align="center" style="background-color:{NAVY};padding:24px 16px;border-top:6px solid {GOLD};">'
             f'<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;color:{GOLD};margin-bottom:6px;">STOCK ANALYSIS REPORT</div>'
             f'<div style="font-size:24px;font-weight:900;color:#ffffff;">{E(name)} <span style="font-size:15px;color:#cbd5e1;">{E(ticker)}</span></div>'
             f'<div style="font-size:13px;color:#d1d5db;margin-top:8px;">{date_k} · {E(x.get("market"))} · 체력지표 {s["total"]} ({s["grade"]}) · 기업 평가점수 아님</div></td></tr>'
             f'<tr><td bgcolor="#fff3cd" style="background-color:#fff3cd;padding:12px 16px;border-left:5px solid #f59e0b;"><div style="font-size:12.5px;color:{BROWN};line-height:1.9;">'
             '&#9888;&#65039; <b>투자 경고문</b> | 본 자료는 공개 데이터를 정리한 참고 정보이며 <b>특정 종목의 매수·매도를 권유하지 않습니다.</b> 주식 투자는 원금 손실의 위험이 있고, 투자 결정과 손익의 책임은 <b>투자자 본인</b>에게 있습니다.</div></td></tr></table>')
    if dl_lead:
        h.append(dl_lead)
    h.append(engage_box())
    # 핵심 지표
    if inc.get("summary") and p:
        cells = [("현재가", f"{p.get('price'):,.0f}원" if p.get("price") else "-", _up(p.get("day_pct"))), ("전일대비", f"{p.get('day_pct', 0):+.2f}%", _up(p.get("day_pct"))),
                 ("시가총액", E(x.get("cap") or "-"), "#111827"), ("PER", E(f.get("PER") or "-"), "#111827"), ("PBR", E(f.get("PBR") or "-"), "#111827"),
                 ("배당수익률", f"{f['DIV']}%" if f.get("DIV") else "-", "#111827"), ("RSI", E(p.get("rsi")), "#111827"), ("이평선", E(p.get("ma_align")), "#111827"),
                 ("52주 위치", f"{p['pos52']}%" if p.get("pos52") is not None else "-", "#111827")]
        h.append(_h("&#128202; 핵심 지표 요약", "#0891b2"))
        rows = []
        for i in range(0, len(cells), 3):
            rows.append("<tr>" + "".join(f'<td width="33%" align="center" style="padding:12px 6px;border:1px solid {LINE};{FONT}"><div style="font-size:11px;color:#6b7280;">{a}</div>'
                                         f'<div style="font-size:16px;font-weight:800;color:{c};margin-top:3px;">{b}</div></td>' for a, b, c in cells[i:i + 3]) + "</tr>")
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:6px;">' + "".join(rows) + "</table>")
        if p.get("high_52w"):
            h.append(f'<p style="font-size:12px;color:#6b7280;margin:4px 0 0;">52주 최고 {p["high_52w"]:,.0f}원 · 최저 {p["low_52w"]:,.0f}원'
                     + (f' · 네이버 컨센서스 목표주가 {x["consensus"]["target_price"]:,.0f}원' if (x.get("consensus") or {}).get("target_price") else "") + "</p>")
    # 5축
    if inc.get("score"):
        h.append(_h("&#127919; 5축 체력지표 (참고)", "#312e81"))
        rows = []
        for a in s["axes"]:
            col = _tc(a["score"])
            rows.append(f'<tr><td width="14%" style="padding:9px 6px;border-bottom:1px solid {LINE};font-size:14px;font-weight:800;color:{NAVY};{FONT}">{E(a["name"])}</td>'
                        f'<td width="12%" align="center" style="padding:9px 4px;border-bottom:1px solid {LINE};font-size:17px;font-weight:900;color:{col};">{a["score"]}</td>'
                        f'<td width="30%" style="padding:9px 6px;border-bottom:1px solid {LINE};">{_bar(a["score"], col)}</td>'
                        f'<td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:12px;color:#4b5563;">{E(a["note"])}</td></tr>')
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">' + "".join(rows) + "</table>"
                 f'<p style="font-size:15px;margin:10px 0 0;{FONT}"><b>체력지표 {s["total"]}</b> · <span style="color:{_tc(s["total"])};font-weight:800;">{s["grade"]}</span>'
                 ' <span style="font-size:11px;color:#9ca3af;">(기술 22%·모멘텀 18%·수급 26%·재무 22%·밸류 12%, 없는 항목은 제외하고 환산 — 공개 시세·재무 자료를 규칙으로 계산한 참고 지표이며 기업 평가점수가 아니에요. 사업의 질·전망·적정 주가는 반영되지 않아요)</span></p>')
    # 수급
    if inc.get("supply") and sup:
        h.append(_h("&#128101; 수급 현황 (외국인·기관·개인)", "#0f766e"))
        if sup["summary"]:
            h.append(f'<p style="font-size:14px;color:{TXT};line-height:1.9;margin:0 0 8px;">{E(sup["summary"])}</p>')
        th = "".join(f'<td align="center" style="padding:8px 6px;font-size:12px;font-weight:700;color:#134e4a;background-color:#ccfbf1;border-bottom:1px solid #99f6e4;">{t}</td>' for t in ("날짜", "종가", "외국인(주)", "기관(주)", "개인(주)"))
        rows = ["<tr>" + th + "</tr>"]
        for r in sup["rows"]:
            tds = [r["date"][5:], f"{r['close']:,.0f}"] + [f"{(r.get(k) or 0):+,.0f}" for k in ("foreign", "inst", "indiv")]
            cols = ["#374151", "#374151"] + [_up(r.get(k)) for k in ("foreign", "inst", "indiv")]
            rows.append("<tr>" + "".join(f'<td align="center" style="padding:7px 6px;font-size:13px;color:{c};border-bottom:1px solid #f0f0f0;">{t}</td>' for t, c in zip(tds, cols)) + "</tr>")
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + FONT + '">' + "".join(rows) + "</table>")
        pp = sup["per"]
        ln = []
        for n in ("5", "10", "20"):
            if n in pp and pp[n]["days"] >= int(n):
                d = pp[n]
                ln.append(f"{n}일 합계 — 외국인 {d['foreign_eok']:+,.0f}억 · 기관 {d['inst_eok']:+,.0f}억 · 개인 {d['indiv_eok']:+,.0f}억")
        if ln:
            h.append(f'<p style="font-size:12.5px;color:#4b5563;line-height:1.9;margin:8px 0 0;">{"<br>".join(E(t) for t in ln)}<br><span style="color:#9ca3af;">※ 순매수대금은 일별 종가×순매수량으로 환산한 추정치입니다.</span></p>')
    # 재무
    fin = x.get("fin") or {}
    if inc.get("fin") and (fin.get("table") or fin.get("dart")):
        h.append(_h("&#128209; 재무·심층분석", "#7c2d12"))
        t = fin.get("table")
        if t:
            head = "<tr><td style=\"padding:8px 6px;background-color:#ffedd5;font-size:12px;font-weight:700;color:#7c2d12;\">항목</td>" + "".join(
                f'<td align="center" style="padding:8px 6px;background-color:#ffedd5;font-size:12px;font-weight:700;color:#7c2d12;">{E(pr["title"])}{"(E)" if pr["estimate"] else ""}</td>' for pr in t["periods"]) + "</tr>"
            rows = [head]
            for r in t["rows"]:
                if r["name"] in ("EPS", "BPS", "당좌비율"):
                    continue
                rows.append(f'<tr><td style="padding:7px 6px;font-size:13px;font-weight:700;color:#374151;border-bottom:1px solid #f0f0f0;">{E(r["name"])}</td>' + "".join(
                    f'<td align="center" style="padding:7px 6px;font-size:13px;color:#374151;border-bottom:1px solid #f0f0f0;">{"-" if v is None else format(v, ",.1f")}</td>' for v in r["values"]) + "</tr>")
            h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + FONT + '">' + "".join(rows) + "</table>"
                     '<p style="font-size:11px;color:#9ca3af;margin:4px 0 8px;">매출·이익 단위: 억원 / 비율: % / (E)는 증권사 컨센서스 추정치</p>')
        if fin.get("items"):
            rows = []
            for it in fin["items"]:
                col = _tc(it["score"])
                rows.append(f'<tr><td width="16%" style="padding:8px 6px;border-bottom:1px solid {LINE};font-size:14px;font-weight:800;color:{NAVY};">{E(it["name"])}</td>'
                            f'<td width="10%" align="center" style="padding:8px 4px;border-bottom:1px solid {LINE};font-size:16px;font-weight:900;color:{col};">{it["score"]}</td>'
                            f'<td style="padding:8px 8px;border-bottom:1px solid {LINE};font-size:12.5px;color:#4b5563;">{E(it["note"])}</td></tr>')
            h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + FONT + '">' + "".join(rows) + "</table>")
        for cmt in fin.get("comments", []):
            h.append(f'<p style="font-size:14px;color:{TXT};line-height:1.9;margin:6px 0 0;">&#9654; {E(cmt)}</p>')
        d = fin.get("dart")
        if d:
            ys = sorted(d["years"].keys())
            keys = ["자산총계", "부채총계", "자본총계", "매출액", "영업이익", "당기순이익"]
            head = "<tr><td style=\"padding:7px 6px;background-color:#e0e7ff;font-size:12px;font-weight:700;\">DART(억원)</td>" + "".join(f'<td align="center" style="padding:7px 6px;background-color:#e0e7ff;font-size:12px;font-weight:700;">{E(y)}</td>' for y in ys) + "</tr>"
            body = "".join(f'<tr><td style="padding:6px;font-size:12.5px;border-bottom:1px solid #f0f0f0;">{k}</td>' + "".join(
                f'<td align="center" style="padding:6px;font-size:12.5px;border-bottom:1px solid #f0f0f0;">{"-" if d["years"][y].get(k) is None else format(d["years"][y][k], ",.0f")}</td>' for y in ys) + "</tr>" for k in keys)
            h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:10px;">' + head + body + "</table>")
    # 공시
    if inc.get("disc") and x.get("disc"):
        h.append(_h("&#128196; 최근 공시 체크", "#374151"))
        rows = []
        colors = {"risk": ("#fef2f2", "#b91c1c", "주의"), "pos": ("#f0fdf4", "#15803d", "호재성"), "info": ("#f9fafb", "#6b7280", "참고")}
        for d in x["disc"][:8]:
            bg, fg, lb = colors[d["level"]]
            rows.append(f'<tr><td width="14%" style="padding:7px 6px;font-size:12px;color:#6b7280;border-bottom:1px solid #f0f0f0;">{E(d["date"][5:])}</td>'
                        f'<td width="16%" align="center" style="padding:7px 4px;border-bottom:1px solid #f0f0f0;"><span style="background-color:{bg};color:{fg};font-size:11px;font-weight:800;padding:2px 6px;">{lb}·{E(d["tag"])}</span></td>'
                        f'<td style="padding:7px 6px;font-size:13px;color:{TXT};border-bottom:1px solid #f0f0f0;">{E(d["title"])}</td></tr>')
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + FONT + '">' + "".join(rows) + "</table>"
                 '<p style="font-size:11px;color:#9ca3af;margin:4px 0 0;">※ 공시 제목을 키워드로 분류한 것으로, 호재·악재 판단이 아닙니다. 원문은 KRX·DART에서 확인하세요.</p>')
    # 뉴스
    if inc.get("news") and x.get("news"):
        h.append(_h("&#128240; 최근 뉴스", "#1e3a8a"))
        h.append("".join(f'<p style="font-size:13.5px;color:{TXT};line-height:1.8;margin:0 0 4px;">&#9642; {E(n.get("title"))} <span style="color:#9ca3af;font-size:11.5px;">{E(n.get("press"))} · {E(n.get("date"))}</span></p>' for n in x["news"][:6]))
    # AI — 화면 하단 'AI 분석'(기업 소개·밸류에이션·실적…)을 먼저, 그다음 분석실 'AI 종합 리포트'
    if inc.get("pubai") and pub_ai.strip():
        h.append(_h("&#129302; AI 분석 (기업·밸류에이션·실적)", "#312e81"))
        h.append(ai_to_html(pub_ai))
    if inc.get("ai") and ai_text.strip():
        h.append(_h("&#129302; AI 종합 분석", "#312e81"))
        h.append(ai_to_html(ai_text))
    h.append(f'<p style="font-size:12px;color:#6b7280;margin:14px 0 0;">&#128279; <a href="{naver}" target="_blank" style="color:#03c75a;font-weight:700;">네이버증권에서 {E(name)} 보기</a> · 데이터 출처: 네이버증권(시세·수급·공시·재무)'
             + (", DART" if fin.get("dart") else "") + "</p>")
    if dl_bottom:
        h.append(dl_bottom)
    h.append(risk_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


# ══════════════════════════════════════════════════════════════
# API (모두 관리자 전용)
# ══════════════════════════════════════════════════════════════
def _bad_ticker():
    return _admin_json({"error": "종목코드가 올바르지 않아요."}, 400)


@bp.route("/admin/api/lab/ext", methods=["POST"])
def api_ext():
    deny = _admin_deny()
    if deny:
        return deny
    t = str((_json_body() or {}).get("ticker", "")).strip().upper()
    if not TICKER_RE.match(t):
        return _bad_ticker()
    x, err = build_ext(t)
    if err:
        return _admin_json({"error": err}, 502)
    x["dups"], x["dup_warn"] = B.dup_info(t, "stock")
    return _admin_json(x)


@bp.route("/admin/api/lab/prompt", methods=["POST"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
    t = str((_json_body() or {}).get("ticker", "")).strip().upper()
    if not TICKER_RE.match(t):
        return _bad_ticker()
    x, err = build_ext(t)
    if err:
        return _admin_json({"error": err}, 502)
    body = (prompt_get("lab_report").replace("{name}", str(x["name"])).replace("{ticker}", t)
            .replace("{today}", _now_kst().strftime("%Y-%m-%d")).replace("{data}", data_text(x)))
    return _admin_json({"prompt": body, "name": x["name"], "len": len(body)})


@bp.route("/admin/api/lab/blog", methods=["POST"])
def api_blog():
    deny = _admin_deny()
    if deny:
        return deny
    d = _json_body() or {}
    t = str(d.get("ticker", "")).strip().upper()
    if not TICKER_RE.match(t):
        return _bad_ticker()
    ai = str(d.get("ai") or "")[:30000]
    pub_ai = str(d.get("pub_ai") or "")[:30000]
    inc = d.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k, _ in SECTIONS} if isinstance(inc, dict) else None
    x, err = build_ext(t)
    if err:
        return _admin_json({"error": err}, 502)
    b = build_blog(x, ai, inc, str(d.get("title") or "").strip()[:150], pub_ai)
    logs, warn = B.dup_info(t, "stock")
    b.update({"name": x["name"], "ticker": t, "dups": logs, "dup_warn": warn})
    return _admin_json(b)


@bp.route("/admin/assets/lab.js")
def asset_js():
    deny = _admin_deny()
    if deny:
        return deny
    resp = Response(C.FLOW_JS + B.BLOGKIT_JS + IMG.IMGKIT_JS + IMG.STOCK_JS + MAIN_JS, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ══════════════════════════════════════════════════════════════
# 화면 JS — ① 종목분석 화면에 붙는 분석실(MAIN_JS)  ② 관리자 탭(TAB_JS)
# ══════════════════════════════════════════════════════════════
MAIN_JS = r"""
(function(){
if(window.__LAB__)return;var LAB=window.__LAB__={tk:null,x:null,ai:{},blog:null,open:false,st:{img:false,blog:false,posted:false}};
var BASE='/admin/api/lab/';
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function api(u,b){var o={credentials:'same-origin',cache:'no-store'};if(b){o.method='POST';o.headers={'Content-Type':'application/json','X-CSRF-Token':(window.__ADM__||{}).csrf||''};o.body=JSON.stringify(b)}
 return fetch(u,o).then(function(r){return r.json().catch(function(){return {error:'응답을 읽지 못했어요'}})})}
function toast(m){if(window.showToast)window.showToast(m);else alert(m)}
var css='#labCard{margin:0 0 20px;border:1.5px solid #c7d2fe;border-radius:16px;background:linear-gradient(180deg,#f5f7ff,#fff);padding:16px 16px 14px;box-shadow:0 6px 24px rgba(49,46,129,.08)}'+
'#labCard .lh{display:flex;align-items:center;gap:8px;flex-wrap:wrap}#labCard .lh b{font-size:16px;color:#312e81}#labCard .lt{font-size:11px;background:#312e81;color:#fff;border-radius:99px;padding:2px 9px;font-weight:700}'+
'#labCard .ld{font-size:12.5px;color:#6b7280;margin:6px 0 10px;line-height:1.6}#labCard .lrow{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}'+
'#labCard button{font:inherit;font-size:13px;font-weight:700;border-radius:10px;padding:8px 14px;cursor:pointer;border:1.5px solid #c7d2fe;background:#fff;color:#312e81}#labCard button.p{background:#312e81;color:#fff;border-color:#312e81}#labCard button:disabled{opacity:.5;cursor:default}'+
'#labCard .lsec{margin-top:14px;border-top:1px dashed #c7d2fe;padding-top:12px}#labCard .lsec h4{margin:0 0 8px;font-size:14px;color:#1e1b4b}'+
'#labCard .ax{display:grid;grid-template-columns:62px 38px 1fr;gap:8px;align-items:center;margin:6px 0;font-size:13px}#labCard .ax .bar{height:10px;background:#e5e7eb;border-radius:6px;overflow:hidden}#labCard .ax .bar i{display:block;height:100%}'+
'#labCard .axn{font-size:11.5px;color:#6b7280;margin:-2px 0 4px 108px}#labCard .big{font-size:34px;font-weight:900;line-height:1}'+
'#labCard table{width:100%;border-collapse:collapse;font-size:12.5px}#labCard th{background:#eef2ff;color:#312e81;padding:6px;text-align:center;font-weight:700}#labCard td{padding:6px;border-bottom:1px solid #eef0f6;text-align:center}#labCard td.l{text-align:left}'+
'#labCard .up{color:#c62828}#labCard .dn{color:#1565c0}#labCard .tag{font-size:11px;font-weight:800;padding:1px 7px;border-radius:6px;white-space:nowrap}#labCard .t-risk{background:#fef2f2;color:#b91c1c}#labCard .t-pos{background:#f0fdf4;color:#15803d}#labCard .t-info{background:#f3f4f6;color:#6b7280}'+
'#labCard .warn{background:#fff7ed;border:1.5px solid #fdba74;color:#9a3412;border-radius:10px;padding:9px 12px;font-size:12.5px;line-height:1.6;margin:8px 0}#labCard .note{font-size:12px;color:#6b7280;line-height:1.6}'+
'#labCard textarea,#labCard input[type=text]{width:100%;box-sizing:border-box;font:inherit;font-size:13px;border:1.5px solid #d1d5db;border-radius:9px;padding:8px}#labCard textarea{min-height:110px}#labCard iframe{width:100%;height:520px;border:1.5px solid #d1d5db;border-radius:10px;background:#fff}'+
'#labCard label.ck{font-size:12.5px;margin-right:12px;white-space:nowrap}'+
'#labCard .steps{scroll-margin-top:84px;display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px}#labCard .stp{display:flex;align-items:center;gap:8px;flex:1 1 150px;min-width:140px;text-align:left;border:1.5px solid #c7d2fe;background:#fff;color:#312e81;border-radius:12px;padding:9px 12px;cursor:pointer;font:inherit;font-size:13px;font-weight:700;line-height:1.3}'+
'#labCard .stp .n{flex:0 0 26px;height:26px;border-radius:50%;background:#e0e7ff;color:#312e81;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900}#labCard .stp small{display:block;font-size:11px;font-weight:600;color:#6b7280}'+
'#labCard .stp.done{border-color:#86efac;background:#f0fdf4}#labCard .stp.done .n{background:#16a34a;color:#fff}#labCard .stp.cur{border-color:#312e81;box-shadow:0 0 0 3px rgba(49,46,129,.16)}#labCard .stp.cur .n{background:#312e81;color:#fff}#labCard .stp.off{opacity:.55}'+
'#labCard .nextline{font-size:12.5px;color:#312e81;font-weight:700;margin:4px 0 2px}#labCard details.lsec>summary{cursor:pointer;font-size:14px;font-weight:800;color:#1e1b4b;list-style:none;display:flex;align-items:center;gap:6px}#labCard details.lsec>summary::-webkit-details-marker{display:none}#labCard details.lsec>summary::before{content:"▸";color:#6366f1}#labCard details.lsec[open]>summary::before{content:"▾"}'+
'#labCard .lsec h4 .sn{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:#312e81;color:#fff;font-size:12px;margin-right:6px}';
function ensureCss(){if(document.getElementById('labCss'))return;var s=el('style');s.id='labCss';s.textContent=css;document.head.appendChild(s)}
function col(s){return s>=70?'#16a34a':(s>=50?'#d97706':'#dc2626')}
function sgn(v,d){if(v==null)return '-';var n=Number(v);return (n>0?'+':'')+n.toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d})}
function cls(v){return v>0?'up':(v<0?'dn':'')}
function slot(){return document.getElementById('labSlot')}
function card(){ensureCss();var s=slot();if(!s)return null;var c=document.getElementById('labCard');if(!c){c=el('div');c.id='labCard';s.appendChild(c)}return c}
function head(c,x){c.innerHTML='';var h=el('div','lh');h.appendChild(el('b',null,'🧪 관리자 분석실'));h.appendChild(el('span','lt','관리자 전용'));c.appendChild(h);
 c.appendChild(el('div','ld','일반 이용자에게는 보이지 않는 관리자 전용 작업대예요. 종목을 분석하면 ① 분석이 자동으로 열리고, 아래 번호 순서대로 ② AI → ③ 이미지 → ④ 글 만들기 → ⑤ 블로그에 쓰기를 진행하세요.'))}
function draw0(){var c=card();if(!c)return;head(c);var r=el('div','lrow');var b=el('button','p','🧪 분석실 펼치기 — '+(LAB.name||LAB.tk));b.onclick=load;r.appendChild(b);r.appendChild(deepBtn());c.appendChild(r)}
function deepBtn(){var d=el('button',null,'🏛 심층분석 열기');d.onclick=function(){try{if(window.MiniTabs&&MiniTabs.openDeep(LAB.tk))return}catch(e){}try{localStorage.setItem('mini_deep_ticker',LAB.tk)}catch(e){}if(typeof openAdminWin==='function')openAdminWin('#dp');else window.open('/admin#dp','mini_admin')};return d}
function load(){var c=card();head(c);c.appendChild(el('div','note','⏳ 수급·공시·재무를 모으는 중… (처음 한 번 3~6초)'));
 api(BASE+'ext',{ticker:LAB.tk}).then(function(x){if(x.error){LAB.autoImg=false;head(c);c.appendChild(el('div','warn','⚠ '+x.error));var r=el('div','lrow'),b=el('button',null,'다시 시도');b.onclick=load;r.appendChild(b);c.appendChild(r);return}
  LAB.x=x;LAB.open=true;draw()})}
function secScore(c,x){var s=el('div','lsec');s.appendChild(el('h4',null,'🎯 5축 체력지표 (참고)'));var g=el('div');g.style.cssText='display:flex;align-items:center;gap:14px;margin-bottom:8px';
 var big=el('div','big',String(x.score.total));big.style.color=col(x.score.total);g.appendChild(big);var gt=el('div');gt.appendChild(el('b',null,x.score.grade));gt.appendChild(el('div','note','기술·모멘텀·수급·재무·밸류를 가중 평균한 참고 지표예요. 기업 평가점수가 아니며 투자 판단 근거가 아니에요.'));if(window.ScoreInfo)gt.appendChild(ScoreInfo.note('lab'));g.appendChild(gt);s.appendChild(g);
 x.score.axes.forEach(function(a){var r=el('div','ax');r.appendChild(el('b',null,a.name));var n=el('b',null,a.score);n.style.color=col(a.score);r.appendChild(n);var b=el('div','bar'),i=el('i');i.style.width=a.score+'%';i.style.background=col(a.score);b.appendChild(i);r.appendChild(b);s.appendChild(r);s.appendChild(el('div','axn',a.note))});c.appendChild(s)}
function secSupply(c,x){var sp=x.supply,s=el('div','lsec');s.appendChild(el('h4',null,'👥 수급 (외국인·기관·개인)'));if(!sp){s.appendChild(el('div','note','수급 자료를 가져오지 못했어요.'));c.appendChild(s);return}
 s.appendChild(el('div','note',sp.summary||''));var t=el('table'),h=el('tr');['기간','외국인(억)','기관(억)','개인(억)'].forEach(function(z){h.appendChild(el('th',null,z))});t.appendChild(h);
 ['1','3','5','10','20'].forEach(function(n){var d=sp.per[n];if(!d||d.days<Number(n))return;var r=el('tr');r.appendChild(el('td',null,n+'일'));['foreign_eok','inst_eok','indiv_eok'].forEach(function(k){r.appendChild(el('td',cls(d[k]),sgn(d[k])))});t.appendChild(r)});s.appendChild(t);
 var t2=el('table');t2.style.marginTop='8px';var h2=el('tr');['날짜','종가','외국인(주)','기관(주)','개인(주)'].forEach(function(z){h2.appendChild(el('th',null,z))});t2.appendChild(h2);
 sp.rows.forEach(function(r){var tr=el('tr');tr.appendChild(el('td',null,r.date.slice(5)));tr.appendChild(el('td',null,Number(r.close).toLocaleString('ko-KR')));['foreign','inst','indiv'].forEach(function(k){tr.appendChild(el('td',cls(r[k]),sgn(r[k])))});t2.appendChild(tr)});s.appendChild(t2);
 s.appendChild(el('div','note','※ 순매수대금은 종가×순매수량 추정치. 외국인 보유율 '+(sp.fhold!=null?sp.fhold+'%':'-')));c.appendChild(s)}
function secFin(c,x){var f=x.fin||{},s=el('div','lsec');s.appendChild(el('h4',null,'📑 재무·심층분석'+(f.score!=null?' — '+f.score+'점':'')));
 if(f.items&&f.items.length){f.items.forEach(function(it){var r=el('div','ax');r.appendChild(el('b',null,it.name));var n=el('b',null,it.score);n.style.color=col(it.score);r.appendChild(n);var b=el('div','bar'),i=el('i');i.style.width=it.score+'%';i.style.background=col(it.score);b.appendChild(i);r.appendChild(b);s.appendChild(r);s.appendChild(el('div','axn',it.note))})}
 else s.appendChild(el('div','note','재무 자료가 없어요(신규 상장·데이터 미제공).'));
 if(f.table){var t=el('table'),h=el('tr');h.appendChild(el('th',null,'항목'));f.table.periods.forEach(function(p){h.appendChild(el('th',null,p.title+(p.estimate?'(E)':'')))});t.appendChild(h);
  f.table.rows.forEach(function(r){var tr=el('tr');tr.appendChild(el('td','l',r.name));r.values.forEach(function(v){tr.appendChild(el('td',null,v==null?'-':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:1})))});t.appendChild(tr)});t.style.marginTop='8px';s.appendChild(t)}
 (f.comments||[]).forEach(function(m){s.appendChild(el('div','note','▶ '+m))});
 if(f.dart){var d=f.dart,ys=Object.keys(d.years).sort();var t3=el('table'),h3=el('tr');h3.appendChild(el('th',null,'DART(억원)'));ys.forEach(function(y){h3.appendChild(el('th',null,y))});t3.appendChild(h3);
  ['자산총계','부채총계','자본총계','매출액','영업이익','당기순이익'].forEach(function(k){var tr=el('tr');tr.appendChild(el('td','l',k));ys.forEach(function(y){var v=d.years[y][k];tr.appendChild(el('td',null,v==null?'-':Number(v).toLocaleString('ko-KR')))});t3.appendChild(tr)});t3.style.marginTop='8px';s.appendChild(t3)}
 else if(!x.dart_enabled)s.appendChild(el('div','note','ℹ DART 주요계정은 서버 환경변수 DART_API_KEY 를 넣으면 추가로 표시돼요(선택).'));
 c.appendChild(s)}
function secDisc(c,x){var s=el('div','lsec');s.appendChild(el('h4',null,'📄 공시·뉴스'+(x.disc_risk?' — ⚠ 주의 공시 '+x.disc_risk+'건':'')));
 if(!x.disc.length)s.appendChild(el('div','note','최근 공시가 없거나 가져오지 못했어요.'));
 var t=el('table');x.disc.slice(0,10).forEach(function(d){var tr=el('tr');tr.appendChild(el('td',null,d.date.slice(5)));var tg=el('td'),sp=el('span','tag t-'+d.level,d.tag);tg.appendChild(sp);tr.appendChild(tg);tr.appendChild(el('td','l',d.title));t.appendChild(tr)});s.appendChild(t);
 if(x.news&&x.news.length){var n=el('div');n.style.marginTop='8px';x.news.slice(0,5).forEach(function(z){var p=el('div','note');p.textContent='▪ '+z.title+' ('+z.press+' '+z.date+')';n.appendChild(p)});s.appendChild(n)}
 s.appendChild(el('div','note','※ 공시는 제목 키워드로 분류한 것으로 호재·악재 판단이 아니에요. 원문은 KRX·DART에서 확인하세요.'));c.appendChild(s)}
function pubText(){var b=document.getElementById('aiPasteBox');return b?String(b.value||'').trim():''}
function pubState(){var t=pubText();return t?('✅ 하단 AI 분석 있음 ('+t.length.toLocaleString()+'자) — 블로그 글에 포함돼요.'):'하단 AI 분석이 아직 없어요. [AI 한 번에 진행]을 쓰면 같이 만들어져요.'}
function secAI(c,x){var s=el('div','lsec');s.id='labS2';s.appendChild(el('h4',null,'② 🤖 AI 분석 + AI 종합 리포트'));
 s.appendChild(el('div','note','화면 하단의 [AI 분석](기업 소개·밸류에이션·실적)과 이 분석실의 [AI 종합 리포트]를 이어서 한 번에 진행해요. 첫 답변을 복사하고 돌아오면 하단 카드에 자동으로 채우고, 이어서 두 번째 질문으로 넘어갑니다. 두 결과 모두 블로그 글에 들어가요.'));
 var r=el('div','lrow'),b0=el('button','p','🤖 AI 한 번에 진행 (분석 + 리포트)');b0.onclick=runBoth;r.appendChild(b0);var b=el('button',null,'AI 리포트만');b.onclick=runAI;r.appendChild(b);s.appendChild(r);
 var ps=el('div','note');ps.id='labPubState';ps.textContent=pubState();s.appendChild(ps);
 var has=LAB.ai[LAB.tk];var st=el('div','note');st.id='labAiState';st.textContent=has?('✅ AI 종합 리포트 저장됨 ('+has.length.toLocaleString()+'자) — 아래 블로그 글에 포함돼요.'):'아직 AI 종합 리포트가 없어요(없어도 블로그 글은 만들 수 있어요).';s.appendChild(st);
 var ta=el('textarea');ta.id='labAiTa';ta.placeholder='AI 종합 리포트 답변을 직접 붙여넣어도 됩니다.';ta.value=has||'';ta.oninput=function(){LAB.ai[LAB.tk]=ta.value;var z=document.getElementById('labAiState');if(z)z.textContent=ta.value.trim()?('✍ 직접 입력/붙여넣기 ('+ta.value.length.toLocaleString()+'자)'):'아직 AI 종합 리포트가 없어요(없어도 블로그 글은 만들 수 있어요).'};s.appendChild(ta);c.appendChild(s)}
/* 단계 자동 진행([⚙ 설정] 의 단계 진행 방식): 분석 열기 → AI → 이미지 → 글 → 블로그에 쓰기. 수동으로 둔 단계에서는 멈춘다. */
var LABFLOW=['ai','img','blog','post'];
var LABACTS={
 ai:function(next){if(pubText()&&LAB.ai[LAB.tk]&&String(LAB.ai[LAB.tk]).trim()){next();return}scrollTo2('labS2');runBoth()},
 img:function(next){if(LAB.st.img){next();return}if(!LAB.imgPanel)return;scrollTo2('labS3');LAB.imgPanel.gen(true).then(function(){if(LAB.st.img)next()},function(){})},
 blog:function(next){if(LAB.st.blog){next();return}if(!LAB.blogPanel)return;scrollTo2('labS4');LAB.blogPanel.rebuild()},
 post:function(next){if(LAB.st.blog&&LAB.blogPanel){if(!LAB.blogPanel.built()){LAB.blogPanel.rebuild().then(function(j){if(j){LAB.blogPanel.copyOpen(true);next()}});return}LAB.blogPanel.copyOpen(true);next()}}};
function labFlow(from){if(window.MiniFlow)window.MiniFlow.run('stock',LABFLOW,LABACTS,from)}
function afterAI(){drawSteps();var fl=window.MiniFlow;if(window.ImgKit&&window.ImgKit.mode()==='auto'&&window.ImgKit.when()==='ai'&&LAB.imgPanel&&!LAB.st.img&&!(fl&&fl.auto('stock','img')))LAB.imgPanel.gen(true);setTimeout(function(){labFlow('ai')},200)}
function applyLab(t){LAB.ai[LAB.tk]=t;setTimeout(afterAI,50);var ta=document.getElementById('labAiTa');if(ta)ta.value=t;var z=document.getElementById('labAiState');if(z)z.textContent='✅ AI 종합 리포트 저장됨 ('+t.length.toLocaleString()+'자) — 아래 블로그 글에 포함돼요.'}
function applyPub(t){setTimeout(drawSteps,50);var b=document.getElementById('aiPasteBox');if(b){b.value=t;try{renderAiResult()}catch(e){}}var z=document.getElementById('labPubState');if(z)z.textContent=pubState()}
function prevLab(t){var ok=/##\s*1\./.test(t)||t.length>600;var d=el('div');d.textContent=t.slice(0,500)+(t.length>500?' …':'');var can=t.trim().length>=200;return {node:d,canApply:can,strict:ok,text:ok?null:'형식(## 1. 한줄 결론 …)이 보이지 않아요. 다른 답변이면 저장하지 마세요. 맞는 답변이면 [저장]을 눌러도 돼요.'}}
function prevPub(t){var ok=/\[\s*\d+\s*\./.test(t)||/^#{1,3}\s*\d+\./m.test(t)||t.length>500;var d=el('div');d.textContent=t.slice(0,500)+(t.length>500?' …':'');var can=t.trim().length>=200;return {node:d,canApply:can,strict:ok,text:ok?null:'형식([1. 기업 소개 …])이 보이지 않아요. 다른 답변이면 저장하지 마세요. 맞는 답변이면 [저장]을 눌러도 돼요.'}}
function pubPrompt(){var p=null;try{p=(typeof CUR_PROMPT!=='undefined')?CUR_PROMPT:null}catch(e){}if(p)return Promise.resolve(p);
 try{return _fetchAiPrompt().then(function(d){return (d&&d.prompt)||''}).catch(function(){return ''})}catch(e){return Promise.resolve('')}}
function runBoth(){if(!window.MiniAI){toast('AI 도우미를 불러오는 중이에요. 잠시 뒤 다시 눌러 주세요.');return}
 Promise.all([pubPrompt(),api(BASE+'prompt',{ticker:LAB.tk})]).then(function(a){var pp=a[0],j=a[1];if(j.error){toast(j.error);return}if(!pp){toast('하단 AI 분석 질문을 만들지 못했어요. [AI 리포트만]으로 진행해 주세요.');return}
  window.MiniAI.run({title:'AI 분석 + 종합 리포트 — '+j.name,key:'labboth',autoApply:true,minLen:300,
   steps:[{label:'① AI 분석(하단)',prompt:pp,kind:'pub'},{label:'② AI 종합 리포트',prompt:j.prompt,kind:'lab'}],
   hint:'답변이 끝나면 답변 전체를 복사하고 이 탭으로 돌아오세요. 자동으로 읽어와 저장하고 다음 질문으로 넘어갑니다.',
   preview:function(t,st){return st&&st.kind==='lab'?prevLab(t):prevPub(t)},
   apply:function(t,st){if(st&&st.kind==='lab'){applyLab(t);return Promise.resolve({message:'AI 분석과 종합 리포트를 모두 저장했어요. 아래 [블로그 글 만들기]를 누르세요.'})}applyPub(t);return Promise.resolve({message:'하단 AI 분석을 채웠어요.'})}})})}
function runAI(){if(!window.MiniAI){toast('AI 도우미를 불러오는 중이에요. 잠시 뒤 다시 눌러 주세요.');return}
 api(BASE+'prompt',{ticker:LAB.tk}).then(function(j){if(j.error){toast(j.error);return}
  window.MiniAI.run({title:'AI 종합 리포트 — '+j.name,key:'lab',steps:[{label:j.name,prompt:j.prompt,kind:'lab'}],minLen:300,hint:'AI가 "## 1. 한줄 결론 …" 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){return prevLab(t)},
   apply:function(t){applyLab(t);return Promise.resolve({message:'AI 종합 리포트를 읽어 왔어요. 아래 [블로그 글 만들기]를 누르세요.'})}})})}
function secImg(c,x){var s=el('div','lsec');s.id='labS3';s.appendChild(el('h4',null,'③ 🖼 블로그용 이미지 (메인 · 통합)'));
 s.appendChild(el('div','note','① 체력지표 게이지가 가운데 오는 메인 이미지, ② 주가 차트·재무 차트·동일업종 비교·기술적 지표를 한 장으로 묶은 통합 이미지예요. 저장 폴더와 자동/수동 저장은 [⚙ 저장 설정]에서 정해요.'));
 var box=el('div');s.appendChild(box);c.appendChild(s);
 LAB.imgPanel=window.ImgKit.panel(box,{menu:'stock',name:LAB.x.name,ticker:LAB.tk,onDone:function(){LAB.st.img=true;drawSteps()},gen:function(scale){if(!LAB.cur)return Promise.reject(new Error('분석 결과를 찾지 못했어요. 종목을 다시 분석해 주세요.'));return Promise.resolve(window.ImgKit.stock.build(LAB.cur,LAB.x,scale))}})}
var SEC=[['summary','핵심지표'],['score','5축점수'],['supply','수급'],['fin','재무'],['disc','공시'],['news','뉴스'],['pubai','AI분석(하단)'],['ai','AI종합리포트']];
function secBlog(c,x){var s=el('div','lsec');s.id='labS4';s.appendChild(el('h4',null,'④⑤ 📝 글 만들기 → 블로그에 쓰기 (네이버 블로그용 HTML)'));var box=el('div');s.appendChild(box);c.appendChild(s);
 LAB.blogPanel=window.BlogKit.panel(box,{idp:'lab',key:'stock',kind:'stock',ticker:LAB.tk,name:LAB.x.name,sections:SEC,dup_warn:x.dup_warn,onBuilt:function(){LAB.st.blog=true;drawSteps();labFlow('blog')},onCopied:function(){LAB.st.posted=true;drawSteps()},
  build:function(inc,title){var pt=pubText();if(!pt)inc.pubai=false;return api(BASE+'blog',{ticker:LAB.tk,ai:(LAB.ai[LAB.tk]||''),pub_ai:pt,inc:inc,title:title})},
  onLogged:function(z){LAB.x.dup_warn=z.dup_warn}})}

function stepDone(){var ai=(pubText()?1:0)+(LAB.ai[LAB.tk]&&String(LAB.ai[LAB.tk]).trim()?1:0);return [!!LAB.x,ai,!!LAB.st.img,!!LAB.st.blog,!!LAB.st.posted,ai]}
function scrollTo2(id){var e=document.getElementById(id);if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'start'})}
function drawSteps(){var h=document.getElementById('labSteps');if(!h)return;h.innerHTML='';var d=stepDone(),ai=d[5];
 var acts=[
  {t:'분석 열기',sub:d[0]?'자동 완료 · 다시 불러오기':'불러오는 중',go:function(){load()}},
  {t:'AI 분석 + 종합 리포트',sub:ai>=2?'둘 다 완료':(ai===1?'1/2 완료 · 이어서 진행':'눌러서 시작'),go:function(){scrollTo2('labS2');runBoth()}},
  {t:'이미지 만들기',sub:d[2]?'완료 · 다시 만들기':(window.ImgKit&&window.ImgKit.mode()==='auto'?'자동 저장 켜짐':'눌러서 만들기'),go:function(){scrollTo2('labS3');if(LAB.imgPanel)LAB.imgPanel.gen(true).then(function(){if(LAB.st.img)labFlow('img')},function(){})}},
  {t:'글 만들기',sub:d[3]?'완료 · 다시 만들기':'눌러서 만들기',go:function(){scrollTo2('labS4');if(LAB.blogPanel)LAB.blogPanel.rebuild()}},
  {t:'블로그에 쓰기',sub:d[4]?'복사·열기 완료':(d[3]?'복사하고 블로그 열기':'글을 먼저 만드세요'),go:function(){scrollTo2('labS4');if(LAB.blogPanel)LAB.blogPanel.copyOpen()}}];
 var done=[d[0],ai>=1,d[2],d[3],d[4]],cur=-1;for(var i=0;i<done.length;i++){if(!done[i]){cur=i;break}}
 var cnt=0;done.forEach(function(v){if(v)cnt++});var key=LAB.tk+'|';if(LAB._pk===key&&cnt>LAB._pc){setTimeout(function(){scrollTo2('labSteps')},650)}LAB._pk=key;LAB._pc=cnt;   /* 단계가 하나 끝나면 위쪽 작업 순서 줄로 자동 이동 */
 var steps=acts.map(function(a,i){return {t:a.t,sub:a.sub,done:!!done[i],go:a.go,off:(i===4&&!d[3])}});
 window.FlowBar.draw(h,{steps:steps,runAll:function(){toast('⚡ 블로그까지 이어서 진행해요');if(window.MiniFlow)window.MiniFlow.force('stock',LABFLOW,LABACTS)},note:'[⚡ 블로그까지 한 번에]는 AI 분석 → 이미지 → 글 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 블로그 글쓰기 화면에 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'});h.style.scrollMarginTop='84px'}
function draw(){var c=card();if(!c)return;var x=LAB.x;head(c,x);
 var sp=el('div','steps');sp.id='labSteps';c.appendChild(sp);
 var r=el('div','lrow'),b=el('button',null,'🔄 새로 불러오기');b.onclick=load;r.appendChild(b);var b2=el('button',null,'접기');b2.onclick=function(){LAB.open=false;draw0()};r.appendChild(b2);c.appendChild(r);
 if(x.delisting&&x.delisting.level&&x.delisting.level!=='none'){c.appendChild(el('div','warn','⚠ 상장폐지·거래정지 위험 신호가 있어요 — 위쪽 경고 상자를 먼저 확인하세요.'))}
 var d=el('details','lsec');d.id='labS1';d.open=true;d.appendChild(el('summary',null,'① 분석 결과 — 체력지표 '+x.score.total+' · '+x.score.grade+' (5축·수급·재무·공시)'));c.appendChild(d);
 secScore(d,x);secSupply(d,x);secFin(d,x);secDisc(d,x);
 secAI(c,x);secImg(c,x);secBlog(c,x);drawSteps();
 if(LAB.autoImg){LAB.autoImg=false;if(LAB.imgPanel)LAB.imgPanel.gen(true)}
 if(LAB._ft!==LAB.tk){LAB._ft=LAB.tk;setTimeout(function(){labFlow()},300)}}
window.__onAnalysis=function(d){if(!d||!d.ticker)return;var changed=LAB.tk!==d.ticker;LAB.tk=d.ticker;LAB.name=d.name;LAB.cur=d;if(changed){LAB.x=null;LAB.blog=null;LAB.open=false;LAB.st={img:false,blog:false,posted:false};LAB.imgPanel=null;LAB.blogPanel=null}
 if(!window.MiniAI&&!LAB._ldm){LAB._ldm=1;var s=document.createElement('script');s.src='/assets/mini-ui.js';document.head.appendChild(s)}
 var c=document.getElementById('labCard');if(c)c.remove();
 if(LAB.x&&LAB.x.ticker===d.ticker&&LAB.open){draw();return}
 LAB.autoImg=!!(window.ImgKit&&window.ImgKit.mode()==='auto'&&window.ImgKit.when()==='analysis');
 load()};
window.__onReset=function(){var c=document.getElementById('labCard');if(c)c.remove();LAB._ft=null;LAB.tk=null;LAB.x=null;LAB.open=false};
if(window.__LAB_PENDING__){window.__onAnalysis(window.__LAB_PENDING__);window.__LAB_PENDING__=null}
})();
"""


# ══════════════════════════════════════════════════════════════
def register():
    C.register_prompt("lab_report", {
        "title": "AI 종합 리포트(분석실) 프롬프트", "default": LAB_REPORT_DEFAULT, "required": ["{data}"], "must_have": ["## 1."],
        "vars": "{data}=종목 데이터 요약(필수) · {name} · {ticker} · {today}",
        "desc": "관리자 분석실에서 AI에게 보내는 종합 리포트 요청문. '## 1.' 형식 제목을 유지해야 블로그 글에 예쁘게 들어가요."})
    C.register_flow("stock", "📈 종목분석 (분석실)", "① 종목 분석 열기(분석이 열리면 자동으로 시작)", [
        {"id": "ai", "label": "② AI 분석 + 종합 리포트", "desc": "분석이 열리면 AI 요청문 창을 자동으로 열어요. 답변을 복사해 돌아오면 다음 단계로 이어져요(이미 둘 다 있으면 건너뛰어요)."},
        {"id": "img", "label": "③ 이미지 만들기", "desc": "AI 단계가 끝나면 이미지를 자동으로 그려요."},
        {"id": "blog", "label": "④ 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요."},
        {"id": "post", "label": "⑤ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요. 브라우저가 복사·새 창을 막으면 [📋 복사하고 블로그 열기]를 한 번 눌러 주세요."}])
    return bp
