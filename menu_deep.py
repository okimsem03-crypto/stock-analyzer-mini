"""🏛 기업 심층분석 (기능별 등급 공개 메뉴 · 기본은 관리자만) — 원본 프로그램의 심층분석 + 추가 기능, 블로그 글쓰기 포함.

원본(app_desktop)의 구성을 그대로 따른다
  ① 기업 현황(회사 프로필) ② 최대주주 ③ 5개년 재무 ④ 체력 진단(수익성·안정성·성장성·거버넌스, S/A/B/C 등급)
  ⑤ PEER 비교 ⑥ AI 정성 분석(사업현황·밸류체인·정량해석·정성분석·리스크·뉴스) ⑦ 블로그 발행 기록(중복 경고) ⑧ 용어 풀이
웹 미니에서 더한 것
  · 5번째 축 '밸류에이션'(PER·PBR·PEER 대비·컨센서스) + 5축 종합 · 투자 전 체크리스트(자동 판정)
  · 밸류에이션 밴드(EPS×PER, BPS×PBR, 컨센서스 목표주가 — 참고용 계산) · 수급·공시·뉴스 한 화면
  · 이미 가져온 원본 심층분석 저장분(DART 5개년·최대주주·AI 글)이 있는 종목은 그대로 불러와 쓴다(378종목 등)
  · AI 분석은 수동 AI 도우미(복사 → 답변 자동 입력)로, 블로그는 [복사하고 블로그 열기] 한 번으로

DART API 키는 코드에 넣지 않는다. 환경변수 DART_API_KEY 가 있을 때만 회사 프로필·최대주주를 DART 에서 직접 가져온다.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request
from menu_ctx import C
import menu_blog as B
import menu_lab as L

bp = Blueprint("deep", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_dbrows", "_http", "_cache_get", "_cache_set",
               "_get_analysis", "_now_kst", "prompt_get", "setting_get", "get_ticker_info", "search_tickers")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

E = B.E
TICKER_RE = B.TICKER_RE
grade = lambda s: "S" if s >= 80 else "A" if s >= 65 else "B" if s >= 50 else "C"
_BAND = {"S": "매우 높은 편", "A": "높은 편", "B": "보통", "C": "낮은 편"}      # 화면·글에는 S/A/B/C 등급 대신 이 표현을 쓴다(신용등급처럼 읽히지 않게)


# ══════════════════════════════════════════════════════════════
# 원본 저장분(가져온 표) 읽기 — 표가 없거나 비어 있어도 오류 없이 None
# ══════════════════════════════════════════════════════════════
def saved_quant(ticker):
    try:
        rows = _dbx("SELECT data, updated_at FROM deepdive_cache WHERE ticker=?", (ticker,), fetch=True)
        if rows and rows[0][0]:
            d = json.loads(rows[0][0])
            if isinstance(d, dict) and d.get("years"):
                return d, str(rows[0][1] or "")
    except Exception:
        pass
    return None, ""


_AI_SECS = [("sec2", "사업 현황"), ("sec_chain", "밸류체인"), ("sec_quant", "정량 해석"), ("sec5", "정성 분석"), ("sec6", "리스크 요인"), ("sec_news", "뉴스 분석")]


def saved_ai(ticker):
    """원본이 저장한 AI 글 → '## n. 제목' 형식의 글 하나로 합친다(없으면 None)."""
    try:
        rows = _dbx("SELECT sec2, sec_chain, sec_quant, sec5, sec6, sec_news, updated_at FROM deepdive_ai WHERE ticker=?", (ticker,), fetch=True)
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    parts = []
    for i, (k, title) in enumerate(_AI_SECS):
        body = str(r[i] or "").strip()
        if body:
            parts.append(f"## {i + 1}. {title}\n{body}")
    return {"text": "\n\n".join(parts), "updated": str(r[6] or "")} if parts else None


def saved_peers(ticker):
    try:
        rows = _dbx("SELECT peers_json FROM deepdive_peers WHERE ticker=?", (ticker,), fetch=True)
        if rows and rows[0][0]:
            return [str(p.get("ticker")) for p in json.loads(rows[0][0]) if p.get("ticker")]
    except Exception:
        pass
    return []


@bp.route("/admin/api/deep/saved", methods=["GET"])
def api_saved():
    """원본 심층분석을 이미 해 둔 종목 목록(최근 순)."""
    deny = _admin_deny()
    if deny:
        return deny
    out = []
    try:
        rows = _dbx("SELECT ticker, updated_at FROM deepdive_cache ORDER BY updated_at DESC LIMIT 60", (), fetch=True) or []
        for t, at in rows:
            nm = get_ticker_info(t)[0] or ""
            out.append({"ticker": t, "name": nm, "at": str(at or "")[:10]})
    except Exception:
        pass
    return _admin_json({"rows": out})


@bp.route("/admin/api/deep/search", methods=["GET"])
def api_search():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json({"rows": (search_tickers(request.args.get("q", "")) or [])[:12]})


# ══════════════════════════════════════════════════════════════
# 연도별 재무(네이버 + 원본 저장분)
# ══════════════════════════════════════════════════════════════
def years_from_naver(payload):
    tbl = L._fin_table(payload)
    if not tbl:
        return []
    rows = {r["name"]: r["values"] for r in tbl["rows"]}
    out = []
    for i, p in enumerate(tbl["periods"]):
        m = re.match(r"(\d{4})", str(p["title"]))
        if not m:
            continue

        def g(n):
            v = rows.get(n)
            return v[i] if v and i < len(v) else None
        out.append({"y": int(m.group(1)), "rev": g("매출액"), "op": g("영업이익"), "ni": g("당기순이익"), "opm": g("영업이익률"), "roe": g("ROE"),
                    "debt_ratio": g("부채비율"), "cur_ratio": g("당좌비율"), "eps": g("EPS"), "bps": g("BPS"), "dps": g("주당배당금"),
                    "ocf": None, "fcf": None, "estimate": bool(p.get("estimate")), "label": p["title"]})
    return out


def merge_years(cache_years, naver_years):
    """원본 저장분(DART 5개년, 현금흐름 포함)이 있으면 그것을 바탕으로 하고, 더 최근인 네이버 연도(추정 포함)를 이어 붙인다."""
    if not cache_years:
        ys = [dict(y, src="네이버") for y in naver_years]
    else:
        ys = []
        for y in cache_years:
            z = lambda k: (y.get(k) or None)          # 원본은 없는 값을 0 으로 저장 → 없음(None)으로
            if not isinstance(y.get("y"), int) or not (z("rev") or z("op") or z("ni")):
                continue
            rev, op, ni, asset, liab, equi = z("rev"), y.get("op"), y.get("ni"), z("asset"), z("liab"), z("equi")
            if not equi and asset and liab:
                equi = asset - liab
            opm = y.get("opm") if y.get("opm") is not None else (round(op / rev * 100, 1) if rev and op is not None else None)
            roe = y.get("roe") if y.get("roe") is not None else (round(ni / equi * 100, 1) if equi and equi > 0 and ni is not None else None)
            dr = y.get("debt_ratio") if y.get("debt_ratio") is not None else (round(liab / equi * 100, 1) if equi and equi > 0 and liab else None)
            ys.append({"y": int(y["y"]), "rev": rev, "op": op, "ni": ni, "opm": opm, "roe": roe,
                       "debt_ratio": dr, "cur_ratio": y.get("cur_ratio"), "eps": z("eps"), "bps": z("bps"), "dps": None,
                       "ocf": z("ocf"), "fcf": y.get("fcf"), "estimate": False, "label": f"{y['y']}.12", "src": "DART(원본 저장)"})
        last = max((y["y"] for y in ys), default=0)
        have = {y["y"] for y in ys}
        for ny in naver_years:
            if ny["y"] > last and ny["y"] not in have:
                ys.append(dict(ny, src="네이버"))
        # DPS·EPS 는 네이버 값으로 채운다(같은 해)
        nmap = {y["y"]: y for y in naver_years}
        for y in ys:
            n = nmap.get(y["y"])
            if n:
                for k in ("dps", "eps", "bps"):
                    if y.get(k) is None:
                        y[k] = n.get(k)
    ys.sort(key=lambda y: y["y"])
    prev = None
    for y in ys:
        y["rev_g"] = round((y["rev"] - prev) / abs(prev) * 100, 1) if (y.get("rev") is not None and prev not in (None, 0)) else None
        prev = y.get("rev")
    return ys[-6:]


def build_divs(cache, years, fund):
    """연도별 배당 {년: {dps, yld, payout}} — 원본 저장분 우선, 없으면 네이버 주당배당금."""
    out = {}
    for yy, v in ((cache or {}).get("dividends") or {}).items():
        try:
            out[int(yy)] = {"dps": v.get("dps"), "yld": v.get("yld"), "payout": v.get("payout")}
        except Exception:
            pass
    for y in years:
        if y.get("dps") and y["y"] not in out and not y.get("estimate"):
            po = round(y["dps"] / y["eps"] * 100, 1) if y.get("eps") and y["eps"] > 0 else None
            out[y["y"]] = {"dps": y["dps"], "yld": None, "payout": po}
    last_actual = max((y for y in years if not y.get("estimate")), key=lambda y: y["y"], default=None)
    if last_actual and last_actual["y"] in out and out[last_actual["y"]].get("yld") is None and fund.get("DIV"):
        out[last_actual["y"]]["yld"] = fund["DIV"]
    return out


# ══════════════════════════════════════════════════════════════
# 체력 진단 — 원본 4축(수익성·안정성·성장성·거버넌스) 그대로 + 5번째 '밸류에이션'
# ══════════════════════════════════════════════════════════════
def _cagr(a, b, n):
    try:
        if a and b and a > 0 and b > 0 and n > 0:
            return ((b / a) ** (1.0 / n) - 1) * 100
    except Exception:
        pass
    return None


def score_card(years, divs):
    ys = [y for y in years if (y.get("rev") or y.get("op") or y.get("ni")) and not y.get("estimate")]
    last = ys[-1] if ys else {}
    opm, roe = last.get("opm"), last.get("roe")
    # 금융업(은행·보험·증권): 매출액이 없고 부채비율이 구조적으로 높다 → 영업이익률·부채비율 대신 ROE·순이익 흐름으로 본다
    fin = (not last.get("rev")) and bool(ys)
    prof = 0
    if fin:
        if roe is not None:
            prof += 50 if roe >= 12 else 42 if roe >= 9 else 32 if roe >= 7 else 22 if roe >= 4 else 10 if roe > 0 else 0
        if len(ys) >= 2 and (ys[-1].get("ni") or 0) > (ys[-2].get("ni") or 0):
            prof += 25
        if len(ys) >= 2 and (ys[-1].get("op") or 0) > (ys[-2].get("op") or 0):
            prof += 25
    elif opm is not None:
        prof += 40 if opm >= 15 else 32 if opm >= 10 else 25 if opm >= 7 else 18 if opm >= 5 else 12 if opm >= 3 else 6 if opm > 0 else 0
    if roe is not None:
        prof += 40 if roe >= 15 else 33 if roe >= 12 else 26 if roe >= 9 else 18 if roe >= 6 else 10 if roe >= 3 else 5 if roe > 0 else 0
    if len(ys) >= 2:
        if (ys[-1].get("opm") or 0) > (ys[-2].get("opm") or 0):
            prof += 10
        if (ys[-1].get("ni") or 0) > (ys[-2].get("ni") or 0):
            prof += 10
    stab = 0
    dr = last.get("debt_ratio")
    if fin:
        dr = None
    if dr is not None:
        stab += 40 if dr <= 50 else 32 if dr <= 100 else 24 if dr <= 150 else 14 if dr <= 200 else 6 if dr <= 300 else 0
    cr = last.get("cur_ratio")
    if cr is not None:
        stab += 30 if cr >= 200 else 24 if cr >= 150 else 18 if cr >= 120 else 10 if cr >= 100 else 4
    black = sum(1 for y in ys[-5:] if (y.get("ni") or 0) > 0)
    stab += min(100, black * 20 + 0) if fin else min(30, black * 6)
    grow = 0
    n_span = len(ys) - 1
    rc = _cagr(ys[0].get("rev"), ys[-1].get("rev"), n_span) if n_span >= 1 else None
    oc = _cagr(ys[0].get("op"), ys[-1].get("op"), n_span) if n_span >= 1 else None
    if fin:
        rc = _cagr(ys[0].get("ni"), ys[-1].get("ni"), n_span) if n_span >= 1 else None
    for c in (rc, oc):
        if c is not None:
            grow += 40 if c >= 15 else 33 if c >= 10 else 25 if c >= 5 else 15 if c >= 2 else 8 if c >= 0 else 0
    rg = last.get("rev_g")
    if fin and len(ys) >= 2 and ys[-2].get("ni") and ys[-1].get("ni") is not None and ys[-2]["ni"] > 0:
        rg = round((ys[-1]["ni"] - ys[-2]["ni"]) / ys[-2]["ni"] * 100, 1)
    if rg is not None:
        grow += 20 if rg >= 10 else 14 if rg >= 5 else 8 if rg >= 0 else 0
    gov = 0
    dy = sorted(divs.keys())[-3:]
    paid = sum(1 for y in dy if (divs.get(y, {}).get("dps") or 0) > 0)
    gov += min(40, paid * 13)
    ld = divs.get(dy[-1], {}) if dy else {}
    yld = ld.get("yld")
    if yld is not None:
        gov += 30 if yld >= 4 else 24 if yld >= 3 else 16 if yld >= 2 else 8 if yld >= 1 else (4 if yld > 0 else 0)
    po = ld.get("payout")
    if po is not None:
        gov += 30 if 20 <= po <= 60 else 18 if (10 <= po < 20 or 60 < po <= 80) else 8 if po > 0 else 0
    prof, stab, grow, gov = [min(100, x) for x in (prof, stab, grow, gov)]
    orig = round(prof * 0.3 + stab * 0.25 + grow * 0.25 + gov * 0.2)
    return {"prof": prof, "stab": stab, "grow": grow, "gov": gov, "orig_total": orig,
            "basis": {"opm": opm, "roe": roe, "debt_ratio": dr, "cur_ratio": cr, "black_years": black,
                      "rev_cagr": round(rc, 1) if rc is not None else None, "op_cagr": round(oc, 1) if oc is not None else None,
                      "div_paid_3y": paid, "div_yld": yld, "payout": po, "years_used": len(ys), "financial": fin}}


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def valuation(payload, peers):
    """밸류에이션 축 점수(0~100)와 밴드. 밴드는 '적정주가'가 아니라 가정을 둔 참고 계산이다."""
    f = payload.get("fundamentals") or {}
    p = payload.get("price") or {}
    per, pbr, div = f.get("PER"), f.get("PBR"), f.get("DIV")
    pers = [x["per"] for x in peers if x.get("per") and x["per"] > 0]
    pbrs = [x["pbr"] for x in peers if x.get("pbr") and x["pbr"] > 0]
    mper, mpbr = _median(pers), _median(pbrs)
    sc, notes = 50.0, []
    if per is not None and per > 0:
        sc += 18 if per < 10 else 10 if per < 15 else 2 if per < 25 else -8 if per < 40 else -16
        notes.append(f"PER {per}")
        if mper:
            r = per / mper
            sc += 10 if r < 0.8 else (-8 if r > 1.4 else 0)
            notes.append(f"PEER 중앙값 {mper:.1f}배 대비 {r:.2f}배")
    elif per is not None:
        sc -= 15
        notes.append("적자(PER 없음)")
    if pbr is not None and pbr > 0:
        sc += 12 if pbr < 1 else 6 if pbr < 2 else 0 if pbr < 4 else -6 if pbr < 8 else -12
        notes.append(f"PBR {pbr}")
    cons = (payload.get("details") or {}).get("consensus") or {}
    up = None
    if cons.get("target_price") and p.get("price"):
        up = round((cons["target_price"] / p["price"] - 1) * 100, 1)
        sc += B.clamp(up * 0.2, -8, 10)
        notes.append(f"컨센서스 목표가 대비 {up:+.1f}%")
    if div and div >= 3:
        sc += 6
        notes.append(f"배당 {div}%")
    bands = []
    eps, bps, price = f.get("EPS"), f.get("BPS"), p.get("price")
    if eps and eps > 0 and (len(pers) >= 2 or f.get("sector_PER")):
        if len(pers) >= 2:
            lo, mid, hi = sorted(pers)[0], _median(pers), sorted(pers)[-1]
            basis = f"PEER {len(pers)}곳 PER {lo:.1f}~{hi:.1f}배(중앙 {mid:.1f})"
        else:
            mid = f["sector_PER"]
            lo, hi = mid * 0.75, mid * 1.25
            basis = f"업종 PER {mid}배 ±25%"
        bands.append({"name": "EPS × PER", "low": round(eps * lo), "mid": round(eps * mid), "high": round(eps * hi), "basis": basis + f" · EPS {eps:,.0f}원"})
    if bps and bps > 0 and len(pbrs) >= 2:
        lo, mid, hi = sorted(pbrs)[0], _median(pbrs), sorted(pbrs)[-1]
        bands.append({"name": "BPS × PBR", "low": round(bps * lo), "mid": round(bps * mid), "high": round(bps * hi), "basis": f"PEER {len(pbrs)}곳 PBR {lo:.2f}~{hi:.2f}배(중앙 {mid:.2f}) · BPS {bps:,.0f}원"})
    if cons.get("target_price"):
        bands.append({"name": "애널리스트 컨센서스", "low": None, "mid": round(cons["target_price"]), "high": None,
                      "basis": f"목표주가 평균 · 투자의견 {cons.get('recomm_mean')} · {cons.get('date') or ''}"})
    return {"score": int(round(B.clamp(sc))), "notes": notes, "bands": bands, "price": price, "upside": up, "peer_per": mper, "peer_pbr": mpbr}


# ══════════════════════════════════════════════════════════════
# PEER
# ══════════════════════════════════════════════════════════════
def peer_codes(ticker, payload, custom):
    out = []
    for c in (custom or []) + saved_peers(ticker) + [x.get("ticker") for x in ((payload.get("details") or {}).get("peers") or [])]:
        c = str(c or "").strip().upper()
        if TICKER_RE.match(c) and c != ticker and c not in out:
            out.append(c)
    return out[:6]


def _peer_one(code):
    try:
        pl, _ = _get_analysis(code)
        if not pl or pl.get("error"):
            return None
        f, p = pl.get("fundamentals") or {}, pl.get("price") or {}
        tbl = L._fin_table(pl)
        roe, _a = L._last_actual(tbl, "ROE")
        opm, _b = L._last_actual(tbl, "영업이익률")
        return {"ticker": code, "name": pl.get("name"), "price": p.get("price"), "day_pct": p.get("day_pct"), "per": f.get("PER"), "pbr": f.get("PBR"),
                "cap_eok": (pl.get("details") or {}).get("cap_eok"), "roe": roe, "opm": opm, "pct20": p.get("pct20"), "pos52": p.get("pos52")}
    except Exception as e:
        print(f"[심층분석] PEER {code} 조회 오류(무시): {e}")
        return None


def peer_metrics(codes):
    if not codes:
        return []
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(_peer_one, codes))
    return [r for r in res if r]


# ══════════════════════════════════════════════════════════════
# DART(선택): 회사 프로필·최대주주
# ══════════════════════════════════════════════════════════════
def dart_profile(ticker):
    key = L._dart_key()
    if not key:
        return None, []
    ck = ("deep_dart", ticker)
    hit = _cache_get(ck)
    if hit is not None:
        return (hit.get("profile"), hit.get("holders") or []) if hit else (None, [])
    prof, holders = None, []
    try:
        corp = L._dart_corp(ticker)
        if corp:
            r = _http().get("https://opendart.fss.or.kr/api/company.json", params={"crtfc_key": key, "corp_code": corp}, timeout=8)
            j = r.json() if r.status_code == 200 else {}
            if j.get("status") == "000":
                prof = {"ceo": j.get("ceo_nm"), "est_dt": j.get("est_dt"), "acc_mt": j.get("acc_mt"), "hm_url": j.get("hm_url"), "adres": j.get("adres"), "corp_cls": j.get("corp_cls"), "corp_name": j.get("corp_name")}
            yr = _now_kst().year - 1
            r = _http().get("https://opendart.fss.or.kr/api/hyslrSttus.json", params={"crtfc_key": key, "corp_code": corp, "bsns_year": str(yr), "reprt_code": "11011"}, timeout=8)
            j = r.json() if r.status_code == 200 else {}
            if j.get("status") == "000":
                for it in (j.get("list") or [])[:8]:
                    rt = L._num(it.get("trmend_posesn_stock_qota_rt"))
                    if it.get("nm") and rt is not None:
                        holders.append({"nm": it["nm"], "relate": it.get("relate") or "", "rt": rt})
    except Exception as e:
        print(f"[심층분석] DART 조회 오류(무시): {e}")
    _cache_set(ck, {"profile": prof, "holders": holders} if (prof or holders) else {}, 6 * 3600 if (prof or holders) else 600)
    return prof, holders


# ══════════════════════════════════════════════════════════════
# 체크리스트
# ══════════════════════════════════════════════════════════════
def checklist(years, divs, sup, disc, delisting, valu, fund):
    ys = [y for y in years if (y.get("rev") or y.get("op") or y.get("ni")) and not y.get("estimate")]
    last = ys[-1] if ys else {}
    items = []

    def add(label, ok, note, na=False):
        items.append({"label": label, "state": "na" if na else ("ok" if ok else "warn"), "note": note})
    add("최근 영업이익 흑자", (last.get("op") or 0) > 0, f"영업이익 {last.get('op'):,.0f}억" if last.get("op") is not None else "", na=last.get("op") is None)
    n3 = [y for y in ys[-3:]]
    add("최근 3년 순이익 흑자", all((y.get("ni") or 0) > 0 for y in n3) if n3 else False, f"{sum(1 for y in n3 if (y.get('ni') or 0) > 0)}/{len(n3)}년 흑자" if n3 else "", na=not n3)
    _fin = not last.get("rev")
    add("부채비율 200% 이하", (last.get("debt_ratio") or 0) <= 200, ("금융업은 부채비율 비교 제외" if _fin else f"부채비율 {last.get('debt_ratio')}%"), na=_fin or last.get("debt_ratio") is None)
    add("유동(당좌)비율 100% 이상", (last.get("cur_ratio") or 0) >= 100, f"{last.get('cur_ratio')}%", na=last.get("cur_ratio") is None)
    add("ROE 8% 이상", (last.get("roe") or 0) >= 8, f"ROE {last.get('roe')}%", na=last.get("roe") is None)
    add("매출 증가(전년 대비)", (last.get("rev_g") or 0) > 0, f"{last.get('rev_g')}%", na=last.get("rev_g") is None)
    if any(y.get("ocf") is not None for y in ys):
        add("영업현금흐름 플러스", (last.get("ocf") or 0) > 0, f"영업CF {last.get('ocf'):,.0f}억" if last.get("ocf") is not None else "", na=last.get("ocf") is None)
    add("배당 지급 이력", any((v.get("dps") or 0) > 0 for v in divs.values()), "최근 배당 있음" if any((v.get("dps") or 0) > 0 for v in divs.values()) else "배당 이력 없음")
    p5 = ((sup or {}).get("per") or {}).get("5")
    add("최근 5일 외국인·기관 순매수 합 플러스", bool(p5 and (p5["foreign_eok"] + p5["inst_eok"]) > 0), f"{p5['foreign_eok'] + p5['inst_eok']:+,.0f}억" if p5 else "", na=not p5)
    risk = [d for d in (disc or []) if d["level"] == "risk"]
    add("최근 공시에 주의 키워드 없음", not risk, (risk[0]["title"][:30] if risk else "주의 공시 없음"), na=disc is None)
    lvl = (delisting or {}).get("level") if isinstance(delisting, dict) else None
    add("상장폐지·거래정지 신호 없음", lvl in (None, "", "none"), "신호 없음" if lvl in (None, "", "none") else f"신호: {lvl}")
    if valu.get("upside") is not None:
        add("컨센서스 목표가가 현재가보다 높음", valu["upside"] > 0, f"{valu['upside']:+.1f}%")
    return items


GLOSSARY = [("PER(주가수익비율)", "주가 ÷ 주당순이익. 이익 대비 주가가 몇 배인지. 낮을수록 이익에 비해 싸다고 보지만 업종마다 기준이 다릅니다."),
            ("PBR(주가순자산비율)", "주가 ÷ 주당순자산. 1배 미만이면 장부상 순자산보다 싸게 거래된다는 뜻입니다."),
            ("ROE(자기자본이익률)", "순이익 ÷ 자기자본. 주주가 맡긴 돈으로 얼마나 벌었는지. 보통 8~10% 이상이면 양호하게 봅니다."),
            ("영업이익률", "영업이익 ÷ 매출. 본업으로 매출 100원당 몇 원을 남기는지 보여줍니다."),
            ("부채비율", "부채 ÷ 자기자본. 높을수록 빚 부담이 크고 금리·경기 변화에 민감합니다."),
            ("유동(당좌)비율", "1년 안에 갚을 빚을 현금성 자산으로 감당할 수 있는지. 100% 이상이면 단기 지급 여유가 있다고 봅니다."),
            ("CAGR(연평균 성장률)", "여러 해에 걸친 성장을 한 해 평균으로 환산한 값입니다."),
            ("배당성향", "순이익 중 배당으로 나눠준 비율. 너무 높으면 지속 가능성, 너무 낮으면 주주환원이 약하다는 신호일 수 있어요."),
            ("컨센서스", "여러 증권사 애널리스트 전망의 평균. 목표주가는 참고일 뿐 실제 주가를 보장하지 않습니다.")]


# ══════════════════════════════════════════════════════════════
# 한 덩어리로
# ══════════════════════════════════════════════════════════════
DEEP_STAGES = [("기본 분석(시세·재무·뉴스)", 45), ("5개년 재무 정리", 8), ("동종업종(PEER) 비교", 17), ("점수·밸류에이션", 5), ("수급·공시", 15), ("기업 개요(DART)", 10)]


def _pk():
    """지금 요청의 주소 끝(deep/data 등)을 진행률 키로 쓴다. 요청 밖(시험 등)에서는 None."""
    try:
        from flask import request as _rq
        return _rq.path.split("/admin/api/", 1)[1]
    except Exception:
        return None


def _pg(pk, i, text=""):
    if pk:
        try:
            C.prog_stage(pk, i, text)
        except Exception:
            pass


def build_deep(ticker, custom_peers=None):
    pk = _pk()
    if pk:
        try:
            C.prog_begin(pk, "심층분석 자료 모으기", DEEP_STAGES)
        except Exception:
            pk = None
    _pg(pk, 0, f"{ticker} 시세·재무·뉴스 분석 중")
    payload, _hit = _get_analysis(ticker)
    if not payload or payload.get("error"):
        if pk:
            C.prog_end(pk, False, "실패")
        return None, (payload or {}).get("error") or "분석 결과를 가져오지 못했어요."
    _pg(pk, 1, "5개년 재무 정리 중")
    f = payload.get("fundamentals") or {}
    cache, cache_at = saved_quant(ticker)
    nyears = years_from_naver(payload)
    years = merge_years((cache or {}).get("years"), nyears)
    divs = build_divs(cache, years, f)
    _pg(pk, 2, "같은 업종 종목 비교 자료 조회 중")
    peers = peer_metrics(peer_codes(ticker, payload, custom_peers))
    _pg(pk, 3, "점수·밸류에이션 계산 중")
    valu = valuation(payload, peers)
    sc = score_card(years, divs)
    five = int(round(sc["prof"] * 0.25 + sc["stab"] * 0.20 + sc["grow"] * 0.20 + sc["gov"] * 0.15 + valu["score"] * 0.20))
    sc.update({"valu": valu["score"], "total": five, "grade": grade(five),
               "grades": {"prof": grade(sc["prof"]), "stab": grade(sc["stab"]), "grow": grade(sc["grow"]), "gov": grade(sc["gov"]), "valu": grade(valu["score"])},
               "orig_grade": grade(sc["orig_total"])})
    _pg(pk, 4, "외국인·기관 수급과 공시 조회 중")
    sup = L.supply_analysis(L._trend_rows(ticker))
    disc = L.disclosures(ticker)
    news = ((payload.get("details") or {}).get("news") or [])[:10]
    profile, holders = (cache or {}).get("profile"), (cache or {}).get("holders") or []
    prof_src = "DART(원본 저장)" if profile else ""
    if not profile:
        _pg(pk, 5, "DART 기업 개요 조회 중")
        try:
            profile, holders2 = dart_profile(ticker)
            holders = holders or holders2
            prof_src = "DART" if profile else ""
        except Exception:
            profile = None
    dl = payload.get("delisting_risk")
    ai = saved_ai(ticker)
    logs, warn = B.dup_info(ticker, "deepdive")
    d = {"ticker": ticker, "name": payload.get("name"), "market": payload.get("market"), "sector": (payload.get("details") or {}).get("sector"),
         "as_of": payload.get("as_of"), "cap": (payload.get("details") or {}).get("market_cap"), "price": payload.get("price") and {k: payload["price"].get(k) for k in (
             "price", "day_pct", "rsi", "ma_align", "pos52", "pct5", "pct20", "high_52w", "low_52w", "vol_ratio")},
         "fundamentals": f, "profile": profile, "profile_src": prof_src, "holders": holders[:8], "years": years, "divs": {str(k): v for k, v in divs.items()},
         "score": sc, "valuation": valu, "peers": peers, "checklist": checklist(years, divs, sup, disc, dl, valu, f), "supply": sup, "disc": disc, "news": news,
         "consensus": (payload.get("details") or {}).get("consensus"), "delisting": dl, "dups": logs, "dup_warn": warn,
         "dart_enabled": bool(L._dart_key()),
         "saved": {"quant_at": cache_at[:10] if cache else "", "has_ai": bool(ai), "ai_at": (ai or {}).get("updated", "")[:10], "ai_text": (ai or {}).get("text", "")},
         "years_src": "원본 저장분(DART 5개년) + 네이버 최신" if cache else "네이버 재무(최근 연도 중심)",
         "links": {"naver": f"https://finance.naver.com/item/main.naver?code={ticker}", "dart": "https://dart.fss.or.kr/dsab007/main.do?option=corp&textCrpNm=" + ticker,
                   "kind": "https://kind.krx.co.kr/common/searchcorpname.do?method=searchCorpNameMain&searchCorpName=" + ticker}}
    if pk:
        C.prog_end(pk, True, "완료")
    return d, None


# ══════════════════════════════════════════════════════════════
# AI 프롬프트
# ══════════════════════════════════════════════════════════════
DEEP_DEFAULT = """당신은 한국 상장기업을 분석하는 기업분석 애널리스트입니다. 아래 [데이터]만 근거로 '{name}({ticker})'의 기업 심층분석 글을 작성하세요.
오늘은 {today}입니다. 블로그에 올릴 글이므로 주식 초보~중급 독자가 읽기 쉽게, 그러나 구체적인 숫자를 인용해 쓰세요.

[규칙]
- [데이터]에 없는 숫자·사실을 지어내지 않습니다. 회사의 사업 내용처럼 데이터에 없는 일반 상식은 "알려진 바에 따르면"으로 구분하고, 확실하지 않으면 쓰지 않습니다.
- 매수·매도·목표가를 권유하거나 단정하지 않습니다. 관찰 중심("~로 보입니다", "~를 확인해 볼 만합니다")으로 씁니다.
- 연도별 수치는 추세(증가·감소·회복)와 함께 인용하고, 점수(체력 진단)는 근거 수치와 연결해 해석합니다.
- 공시·뉴스는 제목만 있으므로 내용을 추측하지 말고 "제목 기준"임을 밝힙니다.
- 아래 7개 제목을 순서대로, 정확히 "## 번호. 제목" 형식으로만 씁니다. 각 섹션은 2~3개 문단(빈 줄로 구분)으로 쓰고, 리스크 섹션은 "- " 목록을 섞어도 됩니다.

## 1. 사업 현황
## 2. 밸류체인
## 3. 정량 해석
## 4. 정성 분석
## 5. 리스크 요인
## 6. 뉴스 분석
## 7. 블로그 제목 후보 (검색에 잘 걸리는 제목 3개, 각 줄 앞에 "- ")

[섹션별 안내]
1. 사업 현황: 사업 구조와 수익원, 최근 실적 흐름, 성장 동력.
2. 밸류체인: 산업 가치사슬에서 회사의 위치(원재료·고객·경쟁 구도). 데이터에 없으면 일반적으로 알려진 수준만.
3. 정량 해석: 5개년 재무, 체력 진단 5축, 밸류에이션(PER·PBR·PEER 대비·밴드)을 풀어서.
4. 정성 분석: 최대주주·지배구조(데이터가 있을 때), 배당·주주환원, 수급 흐름.
5. 리스크 요인: 재무·업황·공시·상장유지 관련 위험과 앞으로 모니터링할 포인트.
6. 뉴스 분석: 최근 뉴스 제목들이 실적·주가에 갖는 의미(제목 기준).

[데이터]
{data}
"""


def data_text(d):
    f, p = d.get("fundamentals") or {}, d.get("price") or {}
    L_ = [f"종목: {d['name']}({d['ticker']}) · {d.get('market')} · 시가총액 {d.get('cap') or '-'} · 기준 {d.get('as_of')}"]
    if p:
        L_.append(f"주가: {(p.get('price') or 0):,}원 (전일비 {p.get('day_pct')}%), 5일 {p.get('pct5')}%, 20일 {p.get('pct20')}%, 52주 위치 {p.get('pos52')}% (최고 {p.get('high_52w')}, 최저 {p.get('low_52w')}), RSI {p.get('rsi')}, 이평선 {p.get('ma_align')}")
    L_.append("밸류: " + ", ".join(f"{k} {v}" for k, v in f.items() if v is not None))
    pr = d.get("profile")
    if pr:
        L_.append(f"회사 프로필: 대표 {pr.get('ceo')} · 설립 {pr.get('est_dt')} · 결산 {pr.get('acc_mt')} · {pr.get('corp_cls')}")
    if d.get("holders"):
        L_.append("최대주주·특수관계인: " + ", ".join(f"{h['nm']}({h.get('relate') or ''}) {h['rt']}%" for h in d["holders"][:6]))
    L_.append(f"연간 재무(억원, 출처: {d['years_src']}):")
    for y in d["years"]:
        L_.append(f"  {y['label']}{'(추정)' if y.get('estimate') else ''}: 매출 {y.get('rev')} (전년비 {y.get('rev_g')}%), 영업이익 {y.get('op')} (OPM {y.get('opm')}%), 순이익 {y.get('ni')}, ROE {y.get('roe')}%, 부채비율 {y.get('debt_ratio')}%, 유동(당좌)비율 {y.get('cur_ratio')}%"
                  + (f", 영업CF {y.get('ocf')}, FCF {y.get('fcf')}" if y.get("ocf") is not None else "") + f", EPS {y.get('eps')}, DPS {y.get('dps')}")
    if d.get("divs"):
        L_.append("배당: " + ", ".join(f"{k}년 DPS {v.get('dps')}원(수익률 {v.get('yld')}%, 성향 {v.get('payout')}%)" for k, v in sorted(d["divs"].items())))
    s = d["score"]
    L_.append(f"체력 진단(0~100): 수익성 {s['prof']}({s['grades']['prof']}) 안정성 {s['stab']}({s['grades']['stab']}) 성장성 {s['grow']}({s['grades']['grow']}) 주주환원·거버넌스 {s['gov']}({s['grades']['gov']}) 밸류에이션 {s['valu']}({s['grades']['valu']}) → 체력지표 {s['total']}(공개 재무·시세를 규칙으로 계산한 참고 값 · 기업 평가점수 아님) {_BAND.get(s['grade'], '')} (원본 4축식 {s['orig_total']})")
    b = s["basis"]
    if b.get("financial"):
        L_.append("  (금융업: 매출액·부채비율이 업종 특성상 비교 어려워 ROE·순이익·영업이익 흐름 중심으로 점수 산정)")
    L_.append(f"  근거: OPM {b['opm']}%, ROE {b['roe']}%, 부채비율 {b['debt_ratio']}%, 유동비율 {b['cur_ratio']}%, 흑자 {b['black_years']}년, 매출 CAGR {b['rev_cagr']}%, 영업이익 CAGR {b['op_cagr']}%, 최근3년 배당 {b['div_paid_3y']}회")
    v = d["valuation"]
    if v["bands"]:
        L_.append("밸류에이션 밴드(참고 계산, 적정주가 아님): " + " / ".join(f"{x['name']} {x.get('low') or '-'}~{x.get('mid')}~{x.get('high') or '-'}원({x['basis']})" for x in v["bands"]))
    if d["peers"]:
        L_.append("PEER 비교: " + " / ".join(f"{x['name']} PER {x.get('per')} PBR {x.get('pbr')} ROE {x.get('roe')}% OPM {x.get('opm')}%" for x in d["peers"]))
    if d.get("supply"):
        L_.append("수급: " + d["supply"]["summary"])
    if d.get("disc"):
        L_.append("최근 공시(제목): " + " | ".join(f"{x['date']} [{x['tag']}] {x['title']}" for x in d["disc"][:8]))
    if d.get("news"):
        L_.append("최근 뉴스(제목): " + " | ".join(f"{n.get('date')} {n.get('title')}" for n in d["news"][:10]))
    ck = d.get("checklist") or []
    L_.append("체크리스트: " + ", ".join(f"{'O' if c['state'] == 'ok' else ('X' if c['state'] == 'warn' else '-')} {c['label']}" for c in ck))
    dr = d.get("delisting")
    if isinstance(dr, dict) and dr.get("level") not in (None, "", "none"):
        L_.append(f"상장폐지·거래정지 유의 신호({dr.get('level')}): " + " / ".join(str(r) for r in (dr.get("reasons") or []))[:400] + " — 단정하지 말고 '유의가 필요할 수 있다'고 완곡하게, 공시 확인을 권하며 서술할 것.")
    return "\n".join(L_)


# ══════════════════════════════════════════════════════════════
# 블로그 HTML (원본 방식)
# ══════════════════════════════════════════════════════════════
SECTIONS = [("profile", "기업 현황"), ("fin", "5개년 재무"), ("score", "체력 진단"), ("valu", "밸류에이션"), ("peers", "PEER"), ("check", "체크리스트"),
            ("supply", "수급"), ("disc", "공시·뉴스"), ("ai", "AI 분석"), ("terms", "용어 풀이")]
AI_STYLE = {1: ("🏢", "사업 현황", "구조 · 수익원 · 성장 동력", "#4f46e5", "#f5f6ff"), 2: ("🔗", "밸류체인", "산업 가치사슬 내 위치", "#0d9488", "#f0fdfa"),
            3: ("📈", "정량 해석", "재무 · 밸류에이션 풀이", "#2563eb", "#eff6ff"), 4: ("🧭", "정성 분석", "지배구조 · 주주환원", "#7c3aed", "#faf5ff"),
            5: ("⚠️", "리스크 요인", "위험 요인 · 모니터링 포인트", "#dc2626", "#fef2f2"), 6: ("🔎", "뉴스 분석", "최근 흐름 · 실적/주가 함의", "#b45309", "#fffbeb")}


def _n(v, d=1):
    return "-" if v is None else format(v, f",.{d}f")


def _tbl(head, rows, widths=None, first_left=True):
    th = "".join(f'<td align="center" style="padding:8px 6px;background-color:#eef2ff;font-size:12px;font-weight:700;color:#312e81;border-bottom:1px solid #c7d2fe;">{h}</td>' for h in head)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f'<td align="{"left" if (i == 0 and first_left) else "center"}" style="padding:7px 6px;font-size:13px;color:#374151;border-bottom:1px solid #f0f0f0;{"font-weight:700;" if i == 0 else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
    return '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '"><tr>' + th + "</tr>" + body + "</table>"


def build_deep_blog(d, ai_text="", inc=None, title=""):
    inc = {k: True for k, _ in SECTIONS} if inc is None else inc
    now = _now_kst()
    date_k = B.date_korean(now)
    name, ticker, s = d["name"], d["ticker"], d["score"]
    secs = B.split_sections(ai_text)
    titles = B.extract_titles(ai_text)
    if not title:
        title = titles[0] if titles else f"{name}({ticker}) 기업 심층분석 — 재무·밸류에이션·리스크 정리 ({date_k})"
    kw = [f"{name} 주가", f"{name} 심층분석", f"{name} 재무", f"{name} 전망", ticker, "기업분석", "재무제표 분석"]
    dl_lead, dl_bottom, dl_tags = B.delist_blocks(d.get("delisting"), name, ticker)   # 상폐·거래정지 위험 신호가 있으면 글 위·아래에 경고
    tags, tag_html = B.hashtags([name, name + "심층분석"], date_k, extra=dl_tags + ["기업분석", "재무분석", "기업심층분석"])
    h = [B.seo_box(title, f"{name}의 5개년 재무와 체력 진단, 밸류에이션, 수급·공시를 데이터로 정리한 기업 심층분석입니다. (기준 {d.get('as_of')})", kw)]
    badge = f'<span style="font-size:12px;font-weight:800;color:{B.NAVY};background-color:{B.GOLD};padding:2px 10px;border-radius:10px;">체력지표 {s["total"]} · {_BAND.get(s["grade"], "")}</span>'
    h.append(B.head_box("COMPANY DEEP DIVE", f'🏛 {E(name)} <span style="font-size:15px;color:#cbd5e1;">{E(ticker)}</span>',
                        f'{E(d.get("market"))} · {E(d.get("sector") or "-")} · 시총 {E(d.get("cap") or "-")} · {date_k}<br>{badge}', B.delist_box(d.get("delisting")) and ""))
    h.append(B.delist_box(d.get("delisting")))
    h.append(B.engage_box())
    p = d.get("price") or {}
    f = d.get("fundamentals") or {}
    if dl_lead:
        h.append(dl_lead)
    pf = d.get("profile")
    if inc.get("profile"):
        rows = [("현재가", f"{(p.get('price') or 0):,.0f}원 ({p.get('day_pct', 0):+.2f}%)"), ("시가총액", E(d.get("cap") or "-")), ("PER / PBR", f"{_n(f.get('PER'))}배 / {_n(f.get('PBR'), 2)}배"),
                ("EPS / BPS", f"{_n(f.get('EPS'), 0)}원 / {_n(f.get('BPS'), 0)}원"), ("배당수익률", f"{f['DIV']}%" if f.get("DIV") else "-"),
                ("52주 최고/최저", f"{_n(p.get('high_52w'), 0)} / {_n(p.get('low_52w'), 0)}")]
        if pf:
            rows = [("대표이사", E(pf.get("ceo") or "-")), ("설립일", E(pf.get("est_dt") or "-")), ("결산월", E(pf.get("acc_mt") or "-")), ("시장구분", E(pf.get("corp_cls") or d.get("market") or "-"))] + rows
        cells = ""
        for i in range(0, len(rows), 2):
            pair = rows[i:i + 2]
            cells += "<tr>" + "".join(f'<td width="16%" bgcolor="#f8fafc" style="background-color:#f8fafc;padding:9px 10px;font-size:12px;font-weight:700;color:#475569;border:1px solid #e5e7eb;">{a}</td>'
                                      f'<td width="34%" style="padding:9px 10px;font-size:13px;color:#111827;border:1px solid #e5e7eb;">{b}</td>' for a, b in pair) + ("<td></td><td></td>" if len(pair) == 1 else "") + "</tr>"
        h.append(B.side_title("🏢 기업 현황" + (f' <span style="font-size:12px;font-weight:700;color:#94a3b8;">({E(d.get("profile_src"))})</span>' if pf else ""), "#1a2744"))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '">' + cells + "</table>")
        if d.get("holders"):
            h.append(B.side_title("🏢 최대주주 및 특수관계인 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(DART)</span>", "#4f46e5"))
            h.append(_tbl(["주주", "관계", "지분율(%)"], [[E(x["nm"]), E(x.get("relate") or ""), _n(x["rt"], 2)] for x in d["holders"]]))
    if inc.get("fin") and d.get("years"):
        ys = d["years"]
        head = ["항목"] + [E(y["label"]) + ("(E)" if y.get("estimate") else "") for y in ys]
        rows = [["매출액(억)"] + [_n(y.get("rev"), 0) for y in ys], ["  전년비(%)"] + [_n(y.get("rev_g")) for y in ys], ["영업이익(억)"] + [_n(y.get("op"), 0) for y in ys],
                ["영업이익률(%)"] + [_n(y.get("opm")) for y in ys], ["순이익(억)"] + [_n(y.get("ni"), 0) for y in ys], ["ROE(%)"] + [_n(y.get("roe")) for y in ys],
                ["부채비율(%)"] + [_n(y.get("debt_ratio"), 0) for y in ys], ["유동(당좌)비율(%)"] + [_n(y.get("cur_ratio"), 0) for y in ys]]
        if any(y.get("ocf") is not None for y in ys):
            rows += [["영업현금흐름(억)"] + [_n(y.get("ocf"), 0) for y in ys], ["간이 FCF(억)"] + [_n(y.get("fcf"), 0) for y in ys]]
        rows += [["EPS(원)"] + [_n(y.get("eps"), 0) for y in ys], ["주당배당금(원)"] + [_n(y.get("dps"), 0) for y in ys]]
        h.append(B.side_title(f'📊 5개년 재무 <span style="font-size:12px;font-weight:700;color:#94a3b8;">({E(d["years_src"])})</span>', "#2563eb"))
        h.append(_tbl(head, rows))
        h.append('<p style="font-size:11px;color:#9ca3af;margin:4px 0 0;">(E)는 증권사 컨센서스 추정치입니다.</p>')
    if inc.get("score"):
        axes = [("수익성", s["prof"], s["grades"]["prof"], "영업이익률·ROE·개선 여부"), ("안정성", s["stab"], s["grades"]["stab"], "부채·유동비율·흑자 연속"), ("성장성", s["grow"], s["grades"]["grow"], "매출·영업이익 연평균 성장"),
                ("거버넌스", s["gov"], s["grades"]["gov"], "배당 이력·수익률·성향"), ("밸류에이션", s["valu"], s["grades"]["valu"], "PER·PBR·PEER 대비·컨센서스")]
        rows = "".join(f'<tr><td width="16%" style="padding:9px 6px;border-bottom:1px solid {B.LINE};font-size:14px;font-weight:800;color:{B.NAVY};{B.FONT}">{a}</td>'
                       f'<td width="11%" align="center" style="padding:9px 4px;border-bottom:1px solid {B.LINE};font-size:17px;font-weight:900;color:{B.tone(v)};">{v}</td>'
                       f'<td width="9%" align="center" style="padding:9px 4px;border-bottom:1px solid {B.LINE};font-size:13px;font-weight:900;color:{B.tone(v)};">{g}</td>'
                       f'<td width="26%" style="padding:9px 6px;border-bottom:1px solid {B.LINE};">{B.bar(v, B.tone(v))}</td>'
                       f'<td style="padding:9px 8px;border-bottom:1px solid {B.LINE};font-size:12px;color:#4b5563;">{n}</td></tr>' for a, v, g, n in axes)
        h.append(B.side_title("🎯 5축 체력 진단", "#059669"))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">' + rows + "</table>")
        b = s["basis"]
        h.append(f'<p style="font-size:15px;margin:10px 0 0;{B.FONT}"><b>체력지표 {s["total"]} · {_BAND.get(s["grade"], "")}</b> <span style="font-size:11px;color:#9ca3af;">(수익성 25%·안정성 20%·성장성 20%·거버넌스 15%·밸류에이션 20%를 공개 재무·시세 자료로 규칙 계산한 참고 지표예요. 기업 평가점수가 아니며 사업의 질·전망·적정 주가는 반영되지 않고, 업종·상장 시기·자료 유무에 따라 달라져요. 원본 4축 방식으로는 {s["orig_total"]} · {_BAND.get(s["orig_grade"], "")})</span></p>'
                 f'<p style="font-size:12px;color:#6b7280;margin:4px 0 0;">근거: 영업이익률 {_n(b["opm"])}% · ROE {_n(b["roe"])}% · 부채비율 {_n(b["debt_ratio"], 0)}% · 유동(당좌)비율 {_n(b["cur_ratio"], 0)}% · 흑자 {b["black_years"]}년 · 매출 CAGR {_n(b["rev_cagr"])}% · 영업이익 CAGR {_n(b["op_cagr"])}%</p>')
    if inc.get("valu") and (d["valuation"]["bands"]):
        v = d["valuation"]
        rows = [[E(x["name"]), _n(x.get("low"), 0), f'<b>{_n(x.get("mid"), 0)}</b>', _n(x.get("high"), 0), E(x["basis"])] for x in v["bands"]]
        h.append(B.side_title("💹 밸류에이션 밴드 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(참고 계산)</span>", "#0891b2"))
        h.append(_tbl(["방법", "낮은 값(원)", "중간(원)", "높은 값(원)", "근거"], rows))
        h.append(f'<p style="font-size:11.5px;color:#9ca3af;margin:4px 0 0;">현재가 {_n(v.get("price"), 0)}원. 위 밴드는 PEER·업종 배수를 단순 적용한 참고 계산이며 적정주가나 목표가가 아닙니다.</p>')
    if inc.get("peers") and d.get("peers"):
        rows = [[E(x["name"]) + f' <span style="font-size:11px;color:#94a3b8;">{E(x["ticker"])}</span>', _n(x.get("per")), _n(x.get("pbr"), 2), _n(x.get("roe")), _n(x.get("opm")), f'{_n(x.get("cap_eok"), 0)}', f'{_n(x.get("pct20"))}'] for x in d["peers"]]
        me = [E(d["name"]) + " (본 종목)", _n(f.get("PER")), _n(f.get("PBR"), 2), _n(d["score"]["basis"]["roe"]), _n(d["score"]["basis"]["opm"]), _n(None), _n((d.get("price") or {}).get("pct20"))]
        h.append(B.side_title("🤝 PEER 비교 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(동일 업종)</span>", "#0d9488"))
        h.append(_tbl(["종목", "PER", "PBR", "ROE(%)", "영업이익률(%)", "시총(억)", "20일(%)"], [me] + rows))
    if inc.get("check") and d.get("checklist"):
        ic = {"ok": ("✅", "#15803d"), "warn": ("⚠️", "#b45309"), "na": ("➖", "#9ca3af")}
        rows = "".join(f'<tr><td width="8%" align="center" style="padding:7px;border-bottom:1px solid #f0f0f0;font-size:15px;">{ic[c["state"]][0]}</td><td style="padding:7px 6px;border-bottom:1px solid #f0f0f0;font-size:13.5px;font-weight:700;color:#1f2937;">{E(c["label"])}</td>'
                       f'<td style="padding:7px 6px;border-bottom:1px solid #f0f0f0;font-size:12px;color:{ic[c["state"]][1]};">{E(c["note"])}</td></tr>' for c in d["checklist"])
        okn = sum(1 for c in d["checklist"] if c["state"] == "ok")
        tot = sum(1 for c in d["checklist"] if c["state"] != "na")
        h.append(B.side_title(f"📝 투자 전 체크리스트 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">({okn}/{tot} 충족)</span>", "#ca8a04"))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '">' + rows + "</table>")
    sup = d.get("supply")
    if inc.get("supply") and sup:
        h.append(B.side_title("👥 수급 현황", "#0f766e"))
        if sup["summary"]:
            h.append(f'<p style="font-size:14px;color:{B.TXT};line-height:1.9;margin:0 0 8px;">{E(sup["summary"])}</p>')
        rows = []
        for n in ("5", "10", "20"):
            if n in sup["per"] and sup["per"][n]["days"] >= int(n):
                x = sup["per"][n]
                rows.append([f"{n}일", f'<span style="color:{B.updown(x["foreign_eok"])}">{x["foreign_eok"]:+,.0f}</span>', f'<span style="color:{B.updown(x["inst_eok"])}">{x["inst_eok"]:+,.0f}</span>', f'<span style="color:{B.updown(x["indiv_eok"])}">{x["indiv_eok"]:+,.0f}</span>'])
        if rows:
            h.append(_tbl(["기간", "외국인(억)", "기관(억)", "개인(억)"], rows))
    if inc.get("disc") and (d.get("disc") or d.get("news")):
        h.append(B.side_title("📄 최근 공시·뉴스 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(제목 기준)</span>", "#b45309"))
        col = {"risk": ("#fff7ed", "#c2410c", "주의"), "pos": ("#fef2f2", "#c62828", "호재성"), "info": ("#f9fafb", "#6b7280", "참고")}
        rows = "".join(f'<tr><td width="13%" style="padding:6px;font-size:12px;color:#6b7280;border-bottom:1px solid #f0f0f0;">{E(x["date"][5:])}</td><td width="16%" align="center" style="padding:6px 4px;border-bottom:1px solid #f0f0f0;">'
                       f'<span style="background-color:{col[x["level"]][0]};color:{col[x["level"]][1]};font-size:11px;font-weight:800;padding:2px 6px;">{col[x["level"]][2]}·{E(x["tag"])}</span></td><td style="padding:6px;font-size:13px;color:{B.TXT};border-bottom:1px solid #f0f0f0;">{E(x["title"])}</td></tr>' for x in (d.get("disc") or [])[:6])
        if rows:
            h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '">' + rows + "</table>")
        h.append("".join(f'<p style="font-size:13.5px;color:{B.TXT};line-height:1.8;margin:6px 0 0;">&#9642; {E(n.get("title"))} <span style="color:#9ca3af;font-size:11.5px;">{E(n.get("press"))} · {E(n.get("date"))}</span></p>' for n in (d.get("news") or [])[:6]))
    if inc.get("ai") and ai_text.strip():
        used = False
        for num in sorted(k for k in secs if k in AI_STYLE):
            ttl, body = secs[num]
            if body.strip():
                ic_, nm, sub, ac, tn = AI_STYLE[num]
                h.append(B.section_card(ic_, nm, sub, body, ac, tn))
                used = True
        extra = "\n".join(f"## {k}. {t}\n{b}" for k, (t, b) in secs.items() if k not in AI_STYLE and k != 7 and k != 0 and b.strip())
        pre = secs.get(0, ("", ""))[1].strip()
        if pre or extra or not used:
            h.append(B.ai_to_html((pre + "\n\n" if pre else "") + extra if (pre or extra) else ai_text))
    if inc.get("terms"):
        h.append(B.side_title("📚 용어 풀이 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(초심자용)</span>", "#64748b"))
        h.append("".join(f'<p style="font-size:13px;color:#374151;line-height:1.8;margin:0 0 6px;"><b>{E(a)}</b> — {E(b)}</p>' for a, b in GLOSSARY))
    lk = d["links"]
    h.append(f'<p style="font-size:12px;color:#6b7280;margin:14px 0 0;">&#128279; <a href="{lk["naver"]}" target="_blank" style="color:#03c75a;font-weight:700;">네이버증권</a> · <a href="{lk["dart"]}" target="_blank" style="color:#1d4ed8;font-weight:700;">DART 공시</a> · '
             f'<a href="{lk["kind"]}" target="_blank" style="color:#1d4ed8;font-weight:700;">KIND</a> · 데이터 출처: 네이버증권{", DART" if d.get("profile_src") or d["years_src"].startswith("원본") else ""}</p>')
    if dl_bottom:
        h.append(dl_bottom)
    h.append(B.risk_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════
def _req():
    d = _json_body() or {}
    t = str(d.get("ticker", "")).strip().upper()
    peers = [str(x).strip().upper() for x in (d.get("peers") or []) if isinstance(x, str)][:6]
    return d, t, [x for x in peers if TICKER_RE.match(x)]


# 한 응답(deep/data)이 여러 기능의 자료를 섞어 내보내므로, 회원 화면(/mapi/)에서는 서버가 '잠긴 기능'의 키를 응답에서 뺀다.
# 섹션(=기능 id) ↔ 응답 키. base(종합점수·5축·기업현황·타일)는 deep/data 주소 자체의 문이라 따로 빼지 않는다.
SEC_KEYS = {"fin": ("years", "divs"), "val": ("valuation", "consensus"), "peer": ("peers",), "chk": ("checklist",), "sup": ("supply", "disc", "news")}
GW_STRIP = ("dups", "dup_warn")        # 블로그 작성 이력은 관리자 업무 정보 — 회원 응답에는 항상 뺀다


def _gw():
    return bool(request.environ.get("mini.gateway"))


def locked_secs():
    """지금 보는 사람에게 잠겨 있는 섹션 기능 id 목록(관리자 화면이면 항상 빈 목록)."""
    if not _gw():
        return []
    return [f for f in list(SEC_KEYS) + ["ai"] if not C.feature_ok("deep", f)]


def gate_data(x):
    """회원 화면이면 잠긴 섹션의 키를 빼고 "locked" 목록을 붙인다. 관리자 화면(gateway 아님)은 그대로."""
    if not _gw():
        return x
    lk = locked_secs()
    for f in lk:
        for k in SEC_KEYS.get(f, ()):
            x.pop(k, None)
    if "ai" in lk:
        sv = dict(x.get("saved") or {})
        sv.update(has_ai=False, ai_at="", ai_text="")
        x["saved"] = sv
    for k in GW_STRIP:
        x.pop(k, None)
    x["dups"], x["dup_warn"] = [], ""
    x["locked"] = lk
    return x


@bp.route("/admin/api/deep/data", methods=["POST"])
def api_data():
    deny = _admin_deny()
    if deny:
        return deny
    d, t, peers = _req()
    if not TICKER_RE.match(t):
        return _admin_json({"error": "종목코드가 올바르지 않아요."}, 400)
    x, err = build_deep(t, peers)
    if err:
        return _admin_json({"error": err}, 502)
    return _admin_json(gate_data(x))


@bp.route("/admin/api/deep/prompt", methods=["POST"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
    if _gw():
        # AI 요청문에는 재무·밸류에이션·PEER·체크리스트·수급 자료가 모두 들어가므로, 그 중 하나라도 잠겨 있으면 만들어 주지 않는다(우회 방지)
        lk = [f for f in SEC_KEYS if not C.feature_ok("deep", f)]
        if lk:
            need = C.feature_need_text("deep", lk[0])
            return _admin_json({"error": "AI 요청문에는 재무·밸류에이션·PEER·체크리스트·수급 자료가 모두 들어가요. ‘" + C.feature_spec("deep", lk[0])["label"] + "’ 기능이 열려야 만들 수 있어요.",
                                "feature": lk[0], "login": C.viewer_token() == C.GUEST, "need": need}, 403)
    d, t, peers = _req()
    if not TICKER_RE.match(t):
        return _admin_json({"error": "종목코드가 올바르지 않아요."}, 400)
    x, err = build_deep(t, peers)
    if err:
        return _admin_json({"error": err}, 502)
    body = (prompt_get("deep_report").replace("{name}", str(x["name"])).replace("{ticker}", t)
            .replace("{today}", _now_kst().strftime("%Y-%m-%d")).replace("{data}", data_text(x)))
    return _admin_json({"prompt": body, "name": x["name"], "len": len(body)})


@bp.route("/admin/api/deep/blog", methods=["POST"])
def api_blog():
    deny = _admin_deny()
    if deny:
        return deny
    d, t, peers = _req()
    if not TICKER_RE.match(t):
        return _admin_json({"error": "종목코드가 올바르지 않아요."}, 400)
    inc = d.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k, _ in SECTIONS} if isinstance(inc, dict) else None
    x, err = build_deep(t, peers)
    if err:
        return _admin_json({"error": err}, 502)
    b = build_deep_blog(x, str(d.get("ai") or "")[:40000], inc, str(d.get("title") or "").strip()[:150])
    logs, warn = B.dup_info(t, "deepdive")
    b.update({"name": x["name"], "ticker": t, "dups": logs, "dup_warn": warn})
    return _admin_json(b)


# ══════════════════════════════════════════════════════════════
# 관리자 화면 탭 (JS) — 관리자 화면용 도우미(el, bt, api, apiJ, toast, $)를 쓴다. {{ {% {# 금지
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var DP={tk:null,d:null,ai:{},peers:{},q:'',sugg:[],saved:null,st:{}};
function dpCol(s){return s>=70?'#16a34a':(s>=50?'#d97706':'#dc2626')}
function dpN(v,d){if(v==null)return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?1:d})}
function dpCls(v){return v>0?'up':(v<0?'dn':'')}
function dpSty(e,s){e.style.cssText=s;return e}
function dpLock(box,fid,txt){box.appendChild(el('p','note',txt));return ftSec(box,fid)}
function dpImgMember(box,d){var K=window.ImgKit,row=el('div','bar'),view=dpSty(el('div'),'display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-top:8px'),st=el('div','m');
 var go=bt('🖼 이미지 만들기','bt',function(){go.disabled=true;go.textContent='⏳ 그리는 중…';view.innerHTML='';st.textContent='';
  Promise.resolve(K.fonts()).then(function(){return window.DpImg.build(d,2)}).then(function(items){items.forEach(function(it){var c=el('div','c');c.appendChild(el('b',null,K.CIRC[it.idx-1]+' '+it.label));
    var pw=Math.min(720,it.canvas.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(it.canvas.height*pw/it.canvas.width);sm.getContext('2d').drawImage(it.canvas,0,0,sm.width,sm.height);
    var im=new Image();im.alt=it.label;im.src=sm.toDataURL('image/png');im.style.cssText='width:100%;height:auto;display:block;border-radius:8px;margin:6px 0';c.appendChild(im);
    c.appendChild(bt('💾 이미지 내려받기','bt2',function(){it.canvas.toBlob(function(b){if(!b){toast('이미지를 만들지 못했어요');return}var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=K.fileName(it.idx,d.name,d.ticker);document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},4000)},'image/png')}));view.appendChild(c)});
   st.textContent='이미지를 만들었어요. 각 이미지의 [이미지 내려받기]로 내 기기에 저장하세요.';go.textContent='🔄 다시 만들기'})
   .catch(function(e){st.textContent='이미지를 만들지 못했어요: '+(e&&e.message||e);go.textContent='🖼 이미지 만들기'}).then(function(){go.disabled=false})});
 row.appendChild(go);box.appendChild(row);box.appendChild(st);box.appendChild(view)}
function dpLoad(p){p.innerHTML='';var top=el('div','c');top.appendChild(el('b',null,'🏛 기업 심층분석'));
 top.appendChild(el('p','note',MEMBER_MODE?'종목 이름이나 6자리 코드를 입력하면 5개년 재무·체력 진단(5축)·밸류에이션·PEER·체크리스트·수급·공시를 한 화면에 모아 보여줘요. 숫자를 읽기 쉽게 정리한 참고 자료이며 투자 권유가 아니에요. 등급에 따라 잠긴 구역은 🔒로 표시돼요.':'종목을 고르면 5개년 재무·체력 진단(5축)·밸류에이션·PEER·체크리스트·수급·공시를 한 화면에 모아 보여주고, AI 정성 분석과 블로그 글(복사하고 바로 열기)까지 이어서 만들 수 있어요. 원본 프로그램에서 이미 분석해 둔 종목은 그 저장분(DART 5개년·최대주주·AI 글)을 함께 불러옵니다.'));
 if(!ftOk('base')){p.appendChild(ftSec(top,'base'));return}
 var r=el('div','bar');var q=el('input');q.placeholder='종목명 또는 코드 (예: 삼성전자, 005930)';q.style.width='260px';q.value=DP.q;r.appendChild(q);
 var sg=el('div');sg.id='dpSug';dpSty(sg,'display:flex;gap:6px;flex-wrap:wrap;margin-top:6px');
 function sugg(){DP.q=q.value;if(!q.value.trim()){sg.innerHTML='';return}api('/admin/api/deep/search?q='+encodeURIComponent(q.value)).then(function(j){sg.innerHTML='';(j.rows||[]).forEach(function(x){var tk=x.ticker||x[0],nm=x.name||x[1];sg.appendChild(bt(nm+' '+tk,'bt3',function(){sg.innerHTML='';q.value='';dpOpen(tk,p)}))})})}
 q.oninput=function(){clearTimeout(DP._t);DP._t=setTimeout(sugg,250)};q.onkeydown=function(e){if(e.key==='Enter'){var v=q.value.trim();if(/^[0-9A-Za-z]{6}$/.test(v))dpOpen(v.toUpperCase(),p);else sugg()}};
 top.appendChild(r);top.appendChild(sg);
 var sv=el('div');sv.id='dpSaved';dpSty(sv,'margin-top:8px');top.appendChild(sv);p.appendChild(top);
 var body=el('div');body.id='dpBody';p.appendChild(body);
 if(!DP.saved){api('/admin/api/deep/saved').then(function(j){DP.saved=j.rows||[];dpSavedDraw(p)})}else dpSavedDraw(p);
 var pre=null;try{pre=localStorage.getItem('mini_deep_ticker');if(pre)localStorage.removeItem('mini_deep_ticker')}catch(e){}
 if(pre&&/^[0-9A-Za-z]{6}$/.test(pre))dpOpen(pre,p);else if(DP.d)dpDraw(p)}
window.__openTicker=function(t){try{localStorage.setItem('mini_deep_ticker',String(t||''))}catch(e){}cur='dp';nav();load()};
function dpSavedDraw(p){var sv=$('dpSaved');if(!sv)return;sv.innerHTML='';if(!DP.saved||!DP.saved.length)return;sv.appendChild(el('span','m','원본 저장분 있는 종목(최근순): '));
 DP.saved.slice(0,24).forEach(function(x){var b=bt((x.name||x.ticker)+' '+x.at.slice(5),'bt3',function(){dpOpen(x.ticker,p)});b.style.margin='2px';sv.appendChild(b)})}
function dpOpen(tk,p,peers){DP.tk=tk;DP.st={};var b=$('dpBody');b.innerHTML='';b.appendChild(el('div','c','⏳ 재무·수급·공시·PEER를 모으는 중… (처음 한 번 5~10초)'));
 apiJ('/admin/api/deep/data',{ticker:tk,peers:peers||DP.peers[tk]||[]}).then(function(j){if(j.error){b.innerHTML='';b.appendChild(el('div','c bad','⚠ '+j.error));return}DP.d=j;DP._chain=1;dpDraw(p)})}
var DPCSS='.dpStp{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}.dpSc{text-align:center;font-weight:800;font-size:12px;color:#facc15;margin-top:2px}.dpStp button{flex:1 1 170px;display:flex;align-items:center;gap:10px;text-align:left;border:1.5px solid #c7d2fe;background:#fff;color:#312e81;border-radius:14px;padding:10px 14px;font:inherit;font-size:13.5px;font-weight:800;cursor:pointer;line-height:1.35}.dpStp button small{display:block;font-weight:600;font-size:11.5px;color:#64748b}.dpStp .n{width:26px;height:26px;border-radius:50%;background:#c7d2fe;color:#312e81;display:flex;align-items:center;justify-content:center;font-weight:900;flex:0 0 auto}.dpStp .done{border-color:#86efac;background:#f0fdf4}.dpStp .done .n{background:#16a34a;color:#fff}.dpStp .cur{border-color:#4f46e5;box-shadow:0 0 0 3px rgba(79,70,229,.18)}.dpStp button:disabled{opacity:.55;cursor:default}'+
'.dpH{background:linear-gradient(135deg,#0a1228 0%,#16275a 62%,#243a73 100%);color:#fff;border-radius:18px;padding:20px 22px;display:grid;grid-template-columns:200px 1fr 340px;gap:14px;align-items:center;position:relative;overflow:hidden;margin-bottom:12px;box-shadow:0 14px 36px -16px rgba(10,18,40,.7)}'+
'.dpH:after{content:"";position:absolute;right:-70px;top:-70px;width:260px;height:260px;border-radius:50%;background:radial-gradient(closest-side,rgba(214,178,94,.38),transparent)}'+
'.dpH>*{position:relative;z-index:1}.dpHm h2{margin:0;font-size:26px;font-weight:900;letter-spacing:-.02em}.dpHm .kk{font-size:11px;letter-spacing:.2em;color:#d6b25e;font-weight:800}.dpHm .mt{color:#cbd5e1;font-size:13px;margin-top:6px;line-height:1.7}'+
'.dpHm .hl{margin-top:10px;display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:5px 13px;font-size:13px;font-weight:800;color:#f6e7b4}.dpHm .lk a{color:#93c5fd;font-size:12px;margin-right:12px}'+
'@media(max-width:1100px){.dpH{grid-template-columns:1fr;justify-items:center;text-align:center}}'+
'.dpW{border-radius:14px;padding:12px 15px;margin-bottom:10px;font-size:13.5px;line-height:1.7;font-weight:700}.dpW.d{background:#fef2f2;border:2px solid #dc2626;color:#991b1b}.dpW.c{background:#fffbeb;border:2px solid #d97706;color:#92400e}.dpW small{display:block;font-weight:600;opacity:.9}'+
'.dpTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:9px;margin-bottom:12px}.dpTile{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:11px 13px;box-shadow:0 1px 2px rgba(15,23,42,.04)}.dpTile .l{font-size:11.5px;color:#64748b;font-weight:700}.dpTile .v{font-size:19px;font-weight:900;color:#0f172a;margin-top:2px}.dpTile .s{font-size:11.5px;font-weight:700;margin-top:1px}'+
'.dpNav{position:sticky;top:44px;z-index:4;display:flex;gap:6px;flex-wrap:wrap;background:rgba(244,246,251,.94);backdrop-filter:blur(6px);padding:8px 2px;margin-bottom:6px}.dpNav button{border:1.5px solid #c7d2fe;background:#fff;color:#312e81;border-radius:999px;padding:5px 12px;font:inherit;font-size:12.5px;font-weight:800;cursor:pointer}.dpNav button:hover{background:#312e81;color:#fff}'+
'.dpS{background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:16px 18px;margin-bottom:12px;box-shadow:0 1px 2px rgba(15,23,42,.04),0 10px 26px -18px rgba(15,23,42,.35);scroll-margin-top:90px}.dpS>.dpT{display:flex;align-items:center;gap:9px;font-size:16px;font-weight:900;color:#0f172a;margin-bottom:10px}.dpS>.dpT:before{content:"";width:5px;height:20px;border-radius:3px;background:var(--ac,#2563eb)}.dpS>.dpT small{font-size:12px;color:#94a3b8;font-weight:700}'+
'.dpAx{display:grid;grid-template-columns:78px 40px 1fr;gap:10px;align-items:center;margin:9px 0;font-size:13px}.dpAx .n{font-weight:800}.dpAx .sc{font-weight:900;font-size:16px;text-align:right}.dpAx .tr{height:12px;background:#eef2f7;border-radius:7px;overflow:hidden;position:relative}.dpAx .tr i{display:block;height:100%;border-radius:7px}.dpAx .nt{grid-column:2/4;color:#64748b;font-size:12px;margin-top:-4px}'+
'.dpt{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}.dpt th{background:#f1f5f9;color:#475569;font-weight:800;padding:8px 10px;text-align:right;white-space:nowrap;border-bottom:2px solid #e2e8f0}.dpt th:first-child,.dpt td:first-child{text-align:left}.dpt td{padding:8px 10px;text-align:right;border-bottom:1px solid #eef2f7;white-space:nowrap}.dpt tr:nth-child(even) td{background:#fafbfd}.dpt td.up{color:#e11d48;font-weight:700}.dpt td.dn{color:#2563eb;font-weight:700}'+
'.dpCk{display:grid;grid-template-columns:30px 130px 1fr;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #eef2f7;font-size:13px}.dpCk .ic{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:13px}.dpCk .ic.ok{background:#16a34a}.dpCk .ic.warn{background:#d97706}.dpCk .ic.na{background:#94a3b8}.dpCk b{font-weight:800}.dpCk span{color:#64748b}'+
'.dpCv{max-width:100%;height:auto;display:block}.dpTop .dpCv{margin:0 auto}';
function dpCss(){if(window.ImgKit&&ImgKit.addCss)ImgKit.addCss('dpCss',DPCSS)}
function dpCv(w,h,fn){var K=window.ImgKit;var m=K.make(w,h,2);fn(m.c,w,h);m.cv.className='dpCv';m.cv.style.width=w+'px';m.cv.style.maxWidth='100%';return m.cv}
function dpAxes(d,dark){var s=d.score,c=dark?['#60a5fa','#2dd4bf','#c4b5fd','#fbbf24','#fb7185']:['#2563eb','#0f766e','#7c3aed','#d97706','#e11d48'];
 return [{name:'수익성',score:s.prof,col:c[0],g:s.grades.prof},{name:'안정성',score:s.stab,col:c[1],g:s.grades.stab},{name:'성장성',score:s.grow,col:c[2],g:s.grades.grow},{name:'거버넌스',score:s.gov,col:c[3],g:s.grades.gov},{name:'밸류에이션',score:s.valu,col:c[4],g:s.grades.valu}]}
function dpHead(d){var ax=dpAxes(d).filter(function(a){return a.score!=null});if(!ax.length)return '';var o=ax.slice().sort(function(a,b){return b.score-a.score}),b=o[0],w=o[o.length-1];
 if(ax.length<2||b.score-w.score<12)return '5개 축이 고르게 '+(b.score>=60?'양호한':'중립적인')+' 모습';return b.name+' 강점 · '+w.name+(w.score<50?' 점검 필요':' 보완 여지')}
function dpCap(c){var m=String(c||'').replace(/,/g,'').match(/([0-9.]+)\s*억/);if(!m)return c||'-';var v=Number(m[1]);return v>=10000?(v/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조원':Number(v).toLocaleString('ko-KR')+'억원'}
function dpSector(d){var x=d.sector;return (x&&x!=='—'&&x!=='-')?x:''}
function dpCol2(sc){return sc>=70?'#22c55e':(sc>=50?'#f59e0b':'#ef4444')}
function dpTile(par,l,v,sub,cls){var t=el('div','dpTile');t.appendChild(el('div','l',l));t.appendChild(el('div','v',v));if(sub){var s=el('div','s '+(cls||''),sub);s.style.color=cls==='up'?'#e11d48':(cls==='dn'?'#2563eb':'#64748b');t.appendChild(s)}par.appendChild(t)}
function dpSec(b,id,title,sub,color){var s=el('div','dpS');s.id='dps_'+id;if(color)s.style.setProperty('--ac',color);var t=el('div','dpT');t.appendChild(document.createTextNode(title));if(sub)t.appendChild(el('small',null,sub));s.appendChild(t);b.appendChild(s);return s}
function dpTable(parent,head,rows,opt){var tw=el('div');tw.style.overflowX='auto';var t=el('table','dpt'),h=el('tr');head.forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 rows.forEach(function(r){var tr=el('tr');r.forEach(function(c,i){var td=el('td',(opt&&opt.cls&&opt.cls(r,i))||'',c==null?'-':String(c));if(opt&&opt.tk){var kk2=opt.tk(r,i);if(kk2){td.setAttribute('data-tk',kk2);td.className=(td.className?td.className+' ':'')+'tkl'}}tr.appendChild(td)});t.appendChild(tr)});tw.appendChild(t);parent.appendChild(tw)}
function dpBand(g){return {S:'매우 높은 편',A:'높은 편',B:'보통',C:'낮은 편'}[g]||''}
function dpSign(v){return v>0?'up':(v<0?'dn':'')}
function dpBandCv(v){var bands=v.bands.filter(function(x){return x.low!=null&&x.mid!=null&&x.high!=null}).slice(0,4);if(!bands.length)return document.createElement('div');var W=760,rh=64,H=bands.length*rh+30;return dpCv(W,H,function(c){bands.forEach(function(x,i){var y=i*rh+24,lo=Math.min(x.low,v.price||x.low)*0.9,hi=Math.max(x.high,v.price||x.high)*1.08,sx=function(z){return 150+(z-lo)/(hi-lo)*(W-170)};
  ImgKit.text(c,x.name,0,y+22,{s:13,w:800,c:'#334155',max:140});
  ImgKit.rr(c,150,y+10,W-170,12,6);c.fillStyle='#eef2f7';c.fill();ImgKit.rr(c,sx(x.low),y+6,Math.max(6,sx(x.high)-sx(x.low)),20,8);c.fillStyle='rgba(13,148,136,.35)';c.fill();c.strokeStyle='#0d9488';c.lineWidth=1.6;c.stroke();
  c.fillStyle='#0f766e';c.fillRect(sx(x.mid)-1.5,y+3,3,26);
  if(v.price){var px=sx(v.price);c.fillStyle='#e11d48';c.fillRect(px-1.5,y-2,3,36);ImgKit.text(c,'현재가 '+dpN(v.price,0),Math.min(W-50,Math.max(50,px)),y-6,{s:11.5,w:800,c:'#e11d48',a:'center'})}
  var xl=sx(x.low),xm=sx(x.mid),xh=sx(x.high);ImgKit.text(c,dpN(x.low,0),xl,y+46,{s:11.5,w:700,c:'#64748b',a:xl<190?'left':'center'});ImgKit.text(c,dpN(x.high,0),xh,y+46,{s:11.5,w:700,c:'#64748b',a:'right'});if(xm-xl>80&&xh-xm>80)ImgKit.text(c,dpN(x.mid,0),xm,y+46,{s:12,w:900,c:'#0f766e',a:'center'})})})}
function dpFinCv(ys){var K=ImgKit,W=820,H=330;return dpCv(W,H,function(c){K.legend(c,6,16,[{name:'매출액',color:'#2563eb'},{name:'영업이익',color:'#f59e0b'},{name:'영업이익률(%)',color:'#e11d48',line:1}],13);
 K.bars(c,0,24,W,H-24,{labels:ys.map(function(y){return String(y.y).slice(2)+'년'}),est:ys.map(function(y){return !!y.estimate}),bars:[{name:'매출액',values:ys.map(function(y){return y.rev}),color:'#2563eb'},{name:'영업이익',values:ys.map(function(y){return y.op}),color:'#f59e0b'}],
  line:{name:'영업이익률',values:ys.map(function(y){return y.opm}),color:'#e11d48',unit:'%'},fmt:dpEok,fs:13})})}
function dpEok(v){if(v==null||isNaN(v))return '-';var a=Math.abs(v);if(a>=10000)return (v/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조';return Math.round(v).toLocaleString('ko-KR')}
function dpDraw(p){var d=DP.d,b=$('dpBody');if(!d||!b)return;dpCss();b.innerHTML='';var stp=el('div','dpStp');stp.id='dpSteps';b.appendChild(stp);dpSteps();var s=d.score,bs=s.basis,AX=dpAxes(d),pr0=d.price||{},fu=d.fundamentals||{},LK=d.locked||[];function dpLk(f){return LK.indexOf(f)>=0||!ftOk(f)}
 /* ── 위쪽 큰 카드 ── */
 var H=el('div','dpH');var hl=el('div');hl.appendChild(dpCv(190,190,function(c){ImgKit.ring(c,95,95,74,s.total,{th:17,col:dpCol2(s.total),sub:dpBand(s.grade),glow:10,ss:15})}));hl.appendChild(el('div','dpSc','체력지표(참고)'));if(window.ScoreInfo)hl.appendChild(ScoreInfo.note('deep',true));H.appendChild(hl);
 var hm=el('div','dpHm');hm.appendChild(el('div','kk','COMPANY DEEP DIVE'));hm.appendChild(el('h2',null,d.name));hm.appendChild(el('div','mt',d.ticker+' · '+(d.market||'')+(dpSector(d)?' · '+dpSector(d):'')+' · 시총 '+dpCap(d.cap)+' · 기준 '+(d.as_of||'')));
 var hs=dpHead(d);if(hs)hm.appendChild(el('div','hl','💡 '+hs));hm.appendChild(el('div','mt','재무 출처: '+d.years_src+(d.saved.quant_at?' ('+d.saved.quant_at+' 저장)':'')));
 var lk=el('div','lk');[['네이버증권',d.links.naver],['DART',d.links.dart],['KIND',d.links.kind]].forEach(function(x){var a=el('a',null,x[0]+' ↗');a.href=x[1];a.target='_blank';a.rel='noopener';lk.appendChild(a)});hm.appendChild(lk);H.appendChild(hm);
 var hr=el('div','dpTop');hr.appendChild(dpCv(340,270,function(c){ImgKit.radar(c,170,132,80,dpAxes(d,true),{fs:12.5,label:'#e2e8f0',grid:'rgba(255,255,255,.28)',fill:'rgba(250,204,21,.22)',stroke:'#facc15',lw:2.6})}));H.appendChild(hr);b.appendChild(H);
 /* ── 경고 ── */
 if(d.dup_warn){var w=el('div','dpW c','⚠ '+d.dup_warn);b.appendChild(w)}
 if(d.delisting&&d.delisting.level&&d.delisting.level!=='none'){var dg=d.delisting.level==='danger';var w2=el('div','dpW '+(dg?'d':'c'),(dg?'🚨 투자 유의 — 거래 상태 이상 신호가 확인됐어요 (확정 아님)':'⚠️ 투자 유의 — 거래 상태와 관련해 살펴볼 정황이 있어요 (확정 아님)'));
  w2.appendChild(el('small',null,(d.delisting.reasons||[]).join(' / ')));w2.appendChild(el('small',null,'블로그 글·이미지에도 단정하지 않는 표현으로 경고가 함께 들어가요. 매매 전 KIND·DART 공시 원문으로 꼭 확인하세요.'));b.appendChild(w2)}
 /* ── 핵심 타일 ── */
 var T=el('div','dpTiles');dpTile(T,'현재가',pr0.price!=null?dpN(pr0.price,0)+'원':'-',pr0.day_pct!=null?((pr0.day_pct>0?'▲ ':(pr0.day_pct<0?'▼ ':''))+Math.abs(pr0.day_pct).toFixed(2)+'%'):'',dpSign(pr0.day_pct));
 dpTile(T,'시가총액',dpCap(d.cap));dpTile(T,'PER',fu.PER!=null?dpN(fu.PER)+'배':'-');dpTile(T,'PBR',fu.PBR!=null?dpN(fu.PBR,2)+'배':'-');dpTile(T,'ROE',bs.roe!=null?dpN(bs.roe)+'%':'-');dpTile(T,'영업이익률',bs.opm!=null?dpN(bs.opm)+'%':'-');dpTile(T,'부채비율',bs.debt_ratio!=null?dpN(bs.debt_ratio,0)+'%':'-');dpTile(T,'배당수익률',bs.div_yld!=null?dpN(bs.div_yld)+'%':(fu.DIV!=null?dpN(fu.DIV)+'%':'-'));b.appendChild(T);
 var nav=el('div','dpNav');b.appendChild(nav);function navAdd(id,t){nav.appendChild(bt(t,'',function(){var e=$('dps_'+id);if(e)e.scrollIntoView({behavior:'smooth',block:'start'})}))}
 /* ── 5축 ── */
 var c1=dpSec(b,'ax','🎯 5축 체력 진단','체력지표 '+s.total+' · '+dpBand(s.grade)+' (기업 평가점수 아님)','#2563eb');navAdd('ax','🎯 체력');
 var NT=[ '영업이익률 '+dpN(bs.opm)+'% · ROE '+dpN(bs.roe)+'%','부채비율 '+dpN(bs.debt_ratio,0)+'% · 유동(당좌)비율 '+dpN(bs.cur_ratio,0)+'% · 흑자 '+bs.black_years+'년','매출 CAGR '+dpN(bs.rev_cagr)+'% · 영업이익 CAGR '+dpN(bs.op_cagr)+'%','최근3년 배당 '+bs.div_paid_3y+'회 · 수익률 '+dpN(bs.div_yld)+'% · 성향 '+dpN(bs.payout)+'%',((d.valuation||{}).notes||[]).join(' · ')];
 AX.forEach(function(a,i){var r=el('div','dpAx');r.appendChild(el('span','n',a.name));var sc=el('span','sc',a.score==null?'-':a.score);sc.style.color=dpCol2(a.score||0);r.appendChild(sc);var tr=el('div','tr');var f=el('i');f.style.width=(a.score||0)+'%';f.style.background='linear-gradient(90deg,'+a.col+','+dpCol2(a.score||0)+')';tr.appendChild(f);r.appendChild(tr);if(NT[i])r.appendChild(el('div','nt',(a.g?a.g+' · ':'')+NT[i]));c1.appendChild(r)});
 c1.appendChild(el('p','note','체력지표 = 수익성 25% + 안정성 20% + 성장성 20% + 거버넌스 15% + 밸류에이션 20%를 공개 재무·시세 자료로 규칙 계산한 참고 지표예요. 원본 4축 방식으로는 '+s.orig_total+'('+dpBand(s.orig_grade)+')이에요. 기업의 가치나 투자 매력을 평가한 점수가 아니에요.'));if(window.ScoreInfo)c1.appendChild(ScoreInfo.note('deep'))
 /* ── 재무 ── */
 var ys=d.years||[],c2=dpSec(b,'fin','📊 5개년 재무','단위 억원 · (E)=컨센서스 추정','#0891b2');navAdd('fin','📊 재무');
 if(dpLk('fin'))dpLock(c2,'fin','5개년 매출·영업이익 차트와 연도별 재무표는 등급에 따라 열려요.');else{if(ys.length)c2.appendChild(dpFinCv(ys));
 var rows=[['매출액'].concat(ys.map(function(y){return dpN(y.rev,0)})),['  전년비(%)'].concat(ys.map(function(y){return dpN(y.rev_g)})),['영업이익'].concat(ys.map(function(y){return dpN(y.op,0)})),['영업이익률(%)'].concat(ys.map(function(y){return dpN(y.opm)})),['순이익'].concat(ys.map(function(y){return dpN(y.ni,0)})),['ROE(%)'].concat(ys.map(function(y){return dpN(y.roe)})),['부채비율(%)'].concat(ys.map(function(y){return dpN(y.debt_ratio,0)})),['유동(당좌)비율(%)'].concat(ys.map(function(y){return dpN(y.cur_ratio,0)}))];
 if(ys.some(function(y){return y.ocf!=null}))rows.push(['영업현금흐름'].concat(ys.map(function(y){return dpN(y.ocf,0)})),['간이 FCF'].concat(ys.map(function(y){return dpN(y.fcf,0)})));rows.push(['EPS(원)'].concat(ys.map(function(y){return dpN(y.eps,0)})),['주당배당금(원)'].concat(ys.map(function(y){return dpN(y.dps,0)})));
 dpTable(c2,['항목'].concat(ys.map(function(y){return y.label+(y.estimate?'(E)':'')})),rows,{cls:function(r,i){if(i===0)return '';if(r[0].indexOf('전년비')>=0||r[0]==='영업이익'||r[0]==='순이익'){var n=Number(String(r[i]).replace(/,/g,''));return isNaN(n)?'':(n>0?(r[0]==='영업이익'||r[0]==='순이익'?'':'up'):(n<0?'dn':''))}return ''}});
 c2.appendChild(el('p','note','5개년 DART 자료는 원본 저장분이 있는 종목에서 나와요.'))}
 /* ── 기업 현황 ── */
 if(d.profile||d.holders.length){var c3=dpSec(b,'prof','🏢 기업 현황',d.profile_src||'','#64748b');if(d.profile){var pr=d.profile;c3.appendChild(el('p','note',['대표 '+(pr.ceo||'-'),'설립 '+(pr.est_dt||'-'),'결산 '+(pr.acc_mt||'-'),(pr.corp_cls||''),(pr.adres||'')].join(' · ')))}
  if(d.holders.length)dpTable(c3,['주주','관계','지분율(%)'],d.holders.map(function(h){return [h.nm,h.relate,dpN(h.rt,2)]}))}
 /* ── 밸류에이션 ── */
 var c4=dpSec(b,'val','💹 밸류에이션 밴드','참고 계산 · 적정주가 아님','#0d9488');navAdd('val','💹 밸류에이션');var v=d.valuation||{bands:[]};
 if(dpLk('val'))dpLock(c4,'val','PER·PBR 밴드와 컨센서스 대비 위치는 등급에 따라 열려요.');else if(v.bands.length){c4.appendChild(dpBandCv(v));dpTable(c4,['방법','낮은 값','중간','높은 값','근거'],v.bands.map(function(x){return [x.name,dpN(x.low,0),dpN(x.mid,0),dpN(x.high,0),x.basis]}));c4.appendChild(el('p','note','🔴 현재가 '+dpN(v.price,0)+'원'+(v.upside!=null?' · 컨센서스 목표가 대비 '+(v.upside>0?'+':'')+v.upside+'%':'')+'. 초록 막대=낮은~높은 값, 짙은 선=중간. PEER·업종 배수를 단순 적용한 값이라 적정주가·목표가가 아니에요.'))}else c4.appendChild(el('p','note','PEER 배수나 EPS 자료가 부족해 밴드를 만들지 못했어요.'));
 /* ── PEER ── */
 var c5=dpSec(b,'peer','🤝 PEER 비교','동일 업종','#7c3aed');navAdd('peer','🤝 PEER');
 if(dpLk('peer'))dpLock(c5,'peer','같은 업종 종목과의 PER·PBR·ROE 비교는 등급에 따라 열려요.');else{var PE=d.peers||[];
 if(PE.length){var me=[d.name+' (본 종목)',dpN(fu.PER),dpN(fu.PBR,2),dpN(bs.roe),dpN(bs.opm),'-',dpN((d.price||{}).pct20)];dpTable(c5,['종목','PER','PBR','ROE(%)','영업이익률(%)','시총(억)','20일(%)'],[me].concat(PE.map(function(x){var r=[x.name+' '+x.ticker,dpN(x.per),dpN(x.pbr,2),dpN(x.roe),dpN(x.opm),dpN(x.cap_eok,0),dpN(x.pct20)];r._t=x.ticker;return r})),{tk:function(r,i){return i===0?r._t:null}})}else c5.appendChild(el('p','note','동일 업종 PEER를 찾지 못했어요. 아래에 종목코드를 직접 넣을 수 있어요.'));
 var pr=el('div','bar');var pi=el('input');pi.placeholder='PEER 종목코드 (쉼표로 구분, 예: 000660,005380)';pi.style.width='300px';pi.value=(DP.peers[d.ticker]||[]).join(',');pr.appendChild(pi);pr.appendChild(bt('PEER 다시 계산','bt2',function(){var a=pi.value.split(/[ ,]+/).map(function(x){return x.trim().toUpperCase()}).filter(function(x){return /^[0-9A-Z]{6}$/.test(x)}).slice(0,6);DP.peers[d.ticker]=a;dpOpen(d.ticker,p,a)}));c5.appendChild(pr)}
 /* ── 체크리스트 ── */
 var CK=d.checklist||[],okn=CK.filter(function(x){return x.state==='ok'}).length,tot=CK.filter(function(x){return x.state!=='na'}).length;var c6=dpSec(b,'chk','📝 투자 전 체크리스트',dpLk('chk')?'':okn+'/'+tot+' 충족','#ca8a04');navAdd('chk','📝 체크');
 if(dpLk('chk'))dpLock(c6,'chk','수익성·안정성·배당·공시 등 자동 점검표는 등급에 따라 열려요.');else CK.forEach(function(x){var r=el('div','dpCk');r.appendChild(el('div','ic '+x.state,x.state==='ok'?'✓':(x.state==='warn'?'!':'–')));r.appendChild(el('b',null,x.label));r.appendChild(el('span',null,x.note));c6.appendChild(r)});
 /* ── 수급·공시 ── */
 var c7=dpSec(b,'sup','👥 수급 · 📄 공시 · 📰 뉴스','','#0f766e');navAdd('sup','👥 수급·공시');var sp=d.supply;
 if(dpLk('sup'))dpLock(c7,'sup','외국인·기관·개인 수급과 최근 공시·뉴스 제목은 등급에 따라 열려요.');else{if(sp){c7.appendChild(el('p','note',sp.summary||''));
  dpTable(c7,['기간','외국인(억)','기관(억)','개인(억)'],['1','3','5','10','20'].filter(function(n){return sp.per[n]&&sp.per[n].days>=Number(n)}).map(function(n){var x=sp.per[n];return [n+'일',dpN(x.foreign_eok,0),dpN(x.inst_eok,0),dpN(x.indiv_eok,0)]}),{cls:function(r,i){if(i===0)return '';var n=Number(String(r[i]).replace(/,/g,''));return n>0?'up':(n<0?'dn':'')}})}
 if((d.disc||[]).length)dpTable(c7,['날짜','분류','공시 제목'],d.disc.slice(0,8).map(function(x){return [x.date.slice(5),x.tag,x.title]}));
 (d.news||[]).slice(0,6).forEach(function(n){c7.appendChild(el('div','m','▪ '+n.title+' ('+n.press+' '+n.date+')'))})}
 /* ── AI ── */
 var c8=dpSec(b,'ai','🤖 AI 정성 분석','사업현황·밸류체인·정량해석·정성분석·리스크·뉴스','#4f46e5');navAdd('ai','🤖 AI');
 if(dpLk('ai'))dpLock(c8,'ai','AI 분석용 프롬프트 만들기와 AI 글 보기는 등급에 따라 열려요.');else{
 c8.appendChild(el('p','note',MEMBER_MODE?'위 자료를 정리한 AI 요청문(프롬프트)을 만들어 드려요. 복사해서 내가 쓰는 AI에 붙여 넣고, 받은 답을 아래 칸에 붙여 두면 이 화면에서만 보관돼요(서버에 저장되지 않아요). AI 답변은 참고용이며 틀릴 수 있어요.':'위 데이터를 정리한 프롬프트를 만들어 설정된 AI를 열어요. 답변을 복사하고 이 탭으로 돌아오면 자동으로 읽어 옵니다. 프롬프트는 [프롬프트] 탭에서 고칠 수 있어요.'));
 var rr=el('div','bar');rr.appendChild(bt('🤖 AI 분석 만들기','bt',function(){dpAI(d)}));
 if(d.saved.has_ai){rr.appendChild(bt('📂 원본 저장 AI 글 불러오기 ('+d.saved.ai_at+')','bt2',function(){DP.ai[d.ticker]=d.saved.ai_text;var ta=$('dpAiTa');if(ta)ta.value=d.saved.ai_text;dpAiState();toast('원본 프로그램이 저장해 둔 AI 글을 불러왔어요')}))}c8.appendChild(rr);
 var st=el('div','m');st.id='dpAiState';c8.appendChild(st);var ta=el('textarea');ta.id='dpAiTa';ta.placeholder='AI 답변을 직접 붙여넣어도 돼요.';dpSty(ta,'width:100%;min-height:120px;box-sizing:border-box');ta.value=DP.ai[d.ticker]||'';ta.oninput=function(){DP.ai[d.ticker]=ta.value;dpAiState()};c8.appendChild(ta);dpAiState();}
 /* ── 이미지 ── */
 var c10=dpSec(b,'img',MEMBER_MODE?'🖼 요약 이미지 (3장)':'🖼 블로그용 이미지 (3장)','① 메인 · ② 5개년 재무 · ③ 통합 요약','#e11d48');navAdd('img','🖼 이미지');
 if(dpLk('img'))dpLock(c10,'img','체력지표·5축·재무 차트를 이미지로 만들어 내려받는 기능은 등급에 따라 열려요.');else{
 c10.appendChild(el('p','note',MEMBER_MODE?'① 체력지표·5축 레이더 메인 이미지, ② 5개년 매출·영업이익 차트와 재무표, ③ 체력·밸류에이션·PEER·체크리스트 통합 이미지예요. 지금 화면에 보이는 자료로 그려지며, 잠긴 구역은 이미지에서도 비어 있어요.':'① 체력지표·5축 레이더가 가운데 오는 메인 이미지, ② 5개년 매출·영업이익 차트와 재무표, ③ 체력·밸류에이션·PEER·체크리스트를 한 장에 모은 통합 이미지예요. 저장 폴더와 자동/수동 저장은 [⚙ 저장 설정]에서 정해요.'));
 var ib=el('div');c10.appendChild(ib);if(MEMBER_MODE)dpImgMember(ib,d);else DP.imgPanel=ImgKit.panel(ib,{menu:'deep',name:d.name,ticker:d.ticker,onDone:function(){DP.st.img=true;dpSteps()},next:function(){if(window.MiniFlow)MiniFlow.run('deep',DPFLOW,DPACTS,'img')},gen:function(scale){return Promise.resolve(window.DpImg.build(d,scale))}});}
 /* ── 블로그 ── */
 if(!MEMBER_MODE){var c9=dpSec(b,'blog','📝 블로그 글 쓰기','원본 방식 HTML'+((d.delisting&&d.delisting.level&&d.delisting.level!=='none')?' · ⚠ 위험 경고 자동 포함':''),'#16a34a');navAdd('blog','📝 글');var bx=el('div');c9.appendChild(bx);
 var secs=[['profile','기업현황'],['fin','5개년재무'],['score','체력진단'],['valu','밸류에이션'],['peers','PEER'],['check','체크리스트'],['supply','수급'],['disc','공시·뉴스'],['ai','AI분석'],['terms','용어풀이']];
 DP.blogPanel=window.BlogKit.panel(bx,{idp:'dp',key:'deepdive',kind:'deepdive',ticker:d.ticker,name:d.name,sections:secs,dup_warn:d.dup_warn,
  build:function(inc,title){return apiJ('/admin/api/deep/blog',{ticker:d.ticker,peers:DP.peers[d.ticker]||[],ai:DP.ai[d.ticker]||'',inc:inc,title:title})},onBuilt:function(){DP.st.blog=true;DP.st.copied=false;dpSteps()},onCopied:function(){DP.st.copied=true;dpSteps()},onLogged:function(z){d.dup_warn=z.dup_warn}})}
 if(DP._chain&&!MEMBER_MODE){DP._chain=0;MiniFlow.run('deep',DPFLOW,DPACTS)}}
/* 단계 자동 진행([⚙ 설정] 의 단계 진행 방식): 분석이 열리면 AI → 이미지 → 블로그 글 순서로 설정대로 이어 간다 */
function dpGo2(id){var e=$('dps_'+id);if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'start'})}
function dpSteps(){var sp=$('dpSteps'),d=DP.d;if(!sp||!d)return;var ai=!!(DP.ai[d.ticker]||'').trim(),S=DP.st;
 var steps=[{t:'분석 열기',sub:'불러옴 · 완료',done:true,go:function(){dpStepRun('open')}},
  {t:MEMBER_MODE?'AI 요청문':'AI 정성 분석',sub:ai?'글 있음 · 다시 만들기':'눌러서 시작',done:ai,go:function(){dpStepRun('ai')}},
  {t:MEMBER_MODE?'요약 이미지':'이미지 만들기',sub:S.img?'완료 · 다시 만들기':'눌러서 만들기',done:!!S.img,go:function(){dpStepRun('img')}},
  {t:'글 만들기',sub:S.blog?'완료 · 다시 만들기':'눌러서 만들기',done:!!S.blog,hide:MEMBER_MODE,go:function(){dpStepRun('blog')}},
  {t:'블로그에 쓰기',sub:S.copied?'복사·열기 완료':(S.blog?'복사하고 블로그 열기':'글을 먼저 만드세요'),done:!!S.copied,off:!S.blog,hide:MEMBER_MODE,go:function(){dpStepRun('post')}}];
 window.FlowBar.draw(sp,{steps:steps,runAll:MEMBER_MODE?null:function(){dpStepRun('all')},note:MEMBER_MODE?'':'[⚡ 블로그까지 한 번에]는 AI 분석 → 이미지 → 글 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 블로그 글쓰기 화면에 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'})}
function dpStepRun(id){var d=DP.d;if(!d)return;
 if(id==='open'){dpGo2('ax');return}
 if(id==='ai'){dpGo2('ai');if(MEMBER_MODE&&(d.locked||[]).indexOf('ai')>=0){lockDlg('ai');return}dpAI(d);return}
 if(MEMBER_MODE){dpGo2('img');return}
 if(id==='post'){dpGo2('blog');dpPostGo(false);return}
 if(id==='all'){toast('⚡ 블로그까지 이어서 진행해요');MiniFlow.force('deep',DPFLOW,DPACTS);return}
 if(id==='img')DP.st.img=false;else DP.st.blog=false;
 MiniFlow.go('deep',DPFLOW,DPACTS,id)}
function dpPostGo(auto){var P=DP.blogPanel;if(!P){if(!auto)toast('블로그 구역을 불러오지 못했어요.');return false}
 if(!P.built()){if(!auto)toast('먼저 글을 만들어요. 다 만들어지면 이 단계를 한 번 더 눌러 복사하세요.');if(!auto)P.rebuild();return false}
 P.copyOpen(auto);return true}
var DPFLOW=['ai','img','blog','post'];
var DPACTS={
 ai:function(next){var d=DP.d;if(!d||MEMBER_MODE)return;if((DP.ai[d.ticker]||'').trim()){next();return}var e=$('dps_ai')||$('dpAiTa');if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'start'});dpAI(d)},
 img:function(next){if(!DP.imgPanel)return;if(DP.st.img){next();return}var e=$('dps_img');if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'start'});DP.imgPanel.gen(true).then(function(){if(DP.imgPanel&&DP.imgPanel.items())next()},function(){})},
 blog:function(next){if(!DP.blogPanel)return;if(DP.st.blog&&DP.blogPanel.built()){next();return}dpGo2('blog');DP.blogPanel.rebuild().then(function(j){if(j&&!j.error)next()})},
 post:function(next){dpGo2('blog');if(dpPostGo(true))next()}};
function dpAiState(){var d=DP.d,z=$('dpAiState');dpSteps();if(!z||!d)return;var t=DP.ai[d.ticker]||'';z.textContent=t.trim()?('✅ AI 글 '+t.length.toLocaleString()+'자'+(MEMBER_MODE?' — 이 화면에만 있어요.':' — 블로그 글에 포함돼요.')):(MEMBER_MODE?'아직 AI 글이 없어요.':'아직 AI 글이 없어요(없어도 블로그 글은 만들 수 있어요).')}
function dpAI(d){if(!window.MiniAI){toast('AI 도우미 파일(menu_ui.py)이 올라가지 않았어요.');return}
 apiJ('/admin/api/deep/prompt',{ticker:d.ticker,peers:DP.peers[d.ticker]||[]}).then(function(j){if(j.error){toast(j.error);return}
  window.MiniAI.run({title:'기업 심층분석 AI — '+j.name,key:'deep',steps:[{label:j.name,prompt:j.prompt}],minLen:400,hint:'AI가 "## 1. 사업 현황 …" 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){var ok=/##\s*1\./.test(t)||t.length>900;var n=(t.match(/^#{1,4}\s*\d+\./gm)||[]).length;var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString()+'자 · 섹션 '+n+'개 — '+t.slice(0,300)+(t.length>300?' …':'');var can=t.trim().length>=300;return {node:x,canApply:can,strict:ok,text:ok?null:'형식(## 1. 사업 현황 …)이 보이지 않아요. 다른 답변이면 저장하지 마세요. 맞는 답변이면 [저장]을 눌러도 돼요.'}},
   apply:function(t){DP.ai[d.ticker]=t;var ta=$('dpAiTa');if(ta)ta.value=t;dpAiState();setTimeout(function(){MiniFlow.run('deep',DPFLOW,DPACTS,'ai')},200);return Promise.resolve({message:'AI 글을 읽어 왔어요. 설정에 따라 이미지·글이 이어서 만들어져요.'})}})})}
(function(){
var K=window.ImgKit;if(!K||window.DpImg)return;
var T=K.text,N=K.n,RR=K.rr;
var NAVY0='#0a1228',NAVY1='#16275a',GOLD='#d6b25e',GOLD2='#f6e7b4',PAPER='#f4f0e6',INK='#0f172a',MUT='#64748b',UP='#e11d48',DN='#2563eb';
function col(s){return s>=70?'#22c55e':(s>=50?'#f59e0b':'#ef4444')}
function cap(c){var m=String(c||'').replace(/,/g,'').match(/([0-9.]+)\s*억/);if(!m)return c||'';var v=Number(m[1]);return v>=10000?(v/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조원':Number(v).toLocaleString('ko-KR')+'억원'}
function sec(d){var x=d.sector;return (x&&x!=='—'&&x!=='-')?x:''}
function eok(v){if(v==null||isNaN(v))return '-';var a=Math.abs(v);if(a>=10000)return (v/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조';return Math.round(v).toLocaleString('ko-KR')}
function axes(d,dark){var s=d.score,c=dark?['#60a5fa','#2dd4bf','#c4b5fd','#fbbf24','#fb7185']:['#2563eb','#0f766e','#7c3aed','#d97706','#e11d48'];
 return [{name:'수익성',score:s.prof,col:c[0],g:s.grades.prof},{name:'안정성',score:s.stab,col:c[1],g:s.grades.stab},{name:'성장성',score:s.grow,col:c[2],g:s.grades.grow},{name:'거버넌스',score:s.gov,col:c[3],g:s.grades.gov},{name:'밸류에이션',score:s.valu,col:c[4],g:s.grades.valu}]}
function headline(d){var ax=axes(d).filter(function(a){return a.score!=null});if(!ax.length)return '';var o=ax.slice().sort(function(a,b){return b.score-a.score}),b=o[0],w=o[o.length-1];
 if(ax.length<2||b.score-w.score<12)return '5개 축이 고르게 '+(b.score>=60?'양호한':'중립적인')+' 모습';return b.name+' 강점 · '+w.name+(w.score<50?' 점검 필요':' 보완 여지')}
function risk(d){var r=d.delisting;return r&&(r.level==='danger'||r.level==='caution')?r.level:''}
function today(){var x=new Date(),z=function(n){return ('0'+n).slice(-2)};return x.getFullYear()+'.'+z(x.getMonth()+1)+'.'+z(x.getDate())}
function card(c,x,y,w,h,title,color){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,24);c.fillStyle='#fff';c.fill();c.restore();
 if(title){c.fillStyle=color||'#2563eb';RR(c,x+26,y+26,8,30,4);c.fill();T(c,title,x+46,y+50,{s:28,w:900,c:INK})}}
function riskBand(c,x,y,w,lv){var dg=lv==='danger',bg=dg?'#fef2f2':'#fffbeb',bd=dg?'#dc2626':'#d97706',tc=dg?'#991b1b':'#92400e';RR(c,x,y,w,86,18);c.fillStyle=bg;c.fill();c.lineWidth=3;c.strokeStyle=bd;c.stroke();
 T(c,(dg?'투자 유의 — 거래 상태 이상 신호가 공개 데이터에서 확인됐어요':'투자 유의 — 거래 상태와 관련해 살펴볼 정황이 있어요'),x+w/2,y+36,{s:25,w:900,c:tc,a:'center',max:w-40});
 T(c,'확정이 아닌 자동 점검 결과예요 · 매매 전 KIND·DART 공시 원문을 꼭 확인하세요',x+w/2,y+68,{s:20,w:700,c:tc,a:'center',max:w-40})}
function foot(c,W,y,d){c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,y,W-120,2);
 T(c,'공개 데이터 기반 참고 자료이며 투자 권유가 아닙니다. 체력지표는 기업 평가점수가 아니에요. 모든 투자 판단과 책임은 투자자 본인에게 있어요.',W/2,y+40,{s:19,w:600,c:MUT,a:'center',max:W-120});
 T(c,'기준 '+(d.as_of||today())+' · 출처 네이버증권·DART · stock.oky.kr',W/2,y+72,{s:19,w:700,c:'#94a3b8',a:'center',max:W-120})}
function bandTxt(g){return {S:'매우 높은 편',A:'높은 편',B:'보통',C:'낮은 편'}[g]||''}
function band(c,W,kick,title,sub){var g=c.createLinearGradient(0,0,0,200);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,200);c.fillStyle=GOLD;c.fillRect(0,0,W,8);
 T(c,kick,W/2,58,{s:20,w:800,c:GOLD,a:'center',ls:5});T(c,title,W/2,124,{s:50,w:900,c:'#fff',a:'center',max:W-120});T(c,sub,W/2,170,{s:22,w:600,c:'#cbd5e1',a:'center',max:W-120})}

/* ① 메인 */
function main(d,scale){var rk=risk(d),dy=rk?70:0,W=1080,H=1490+dy,m=K.make(W,H,scale),c=m.c,s=d.score,bs=s.basis,p=d.price||{},f=d.fundamentals||{};
 c.fillStyle=PAPER;c.fillRect(0,0,W,H);var g=c.createLinearGradient(0,0,0,800+dy);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,800+dy);
 var rg=c.createRadialGradient(W-120,80,10,W-120,80,360);rg.addColorStop(0,'rgba(214,178,94,.38)');rg.addColorStop(1,'rgba(214,178,94,0)');c.fillStyle=rg;c.fillRect(0,0,W,800);
 c.fillStyle=GOLD;c.fillRect(0,0,W,8);
 T(c,'COMPANY DEEP DIVE · 기업 심층분석',W/2,66,{s:20,w:800,c:GOLD,a:'center',ls:4});
 T(c,d.name,W/2,160,{s:74,w:900,c:'#fff',a:'center',max:900});
 T(c,d.ticker+' · '+(d.market||'')+(sec(d)?' · '+sec(d):'')+(d.cap?' · 시총 '+cap(d.cap):''),W/2,210,{s:26,w:600,c:'#cbd5e1',a:'center',max:940});
 if(rk)riskBand(c,60,236,W-120,rk);
 var cy=470+dy,r=158;K.ring(c,W/2,cy,r,s.total,{th:30,col:col(s.total),glow:26,fs:118,sub:bandTxt(s.grade),ss:34,sc:GOLD2});T(c,'체력지표(참고)',W/2,cy-r-18,{s:21,w:800,c:GOLD,a:'center',ls:3});
 var hl=headline(d);if(hl)T(c,hl,W/2,cy+r+60,{s:32,w:800,c:GOLD2,a:'center',max:900});
 T(c,'공개 재무·시세를 규칙으로 계산한 참고 지표 · 기업 평가점수가 아니에요 (원본 4축 기준 '+s.orig_total+')',W/2,cy+r+104,{s:21,w:600,c:'#94a3b8',a:'center',max:960});
 card(c,50,780+dy,W-100,350,'5축 체력 진단','#2563eb');
 K.radar(c,W/2,962+dy,106,axes(d),{fs:22,label:'#334155',grid:'rgba(100,116,139,.35)',fill:'rgba(37,99,235,.2)',stroke:'#2563eb',lw:4,dot:7,fillBg:'rgba(37,99,235,.04)'});
 var tiles=[['현재가',p.price!=null?N(p.price,0)+'원':'-',p.day_pct!=null?((p.day_pct>0?'▲ ':(p.day_pct<0?'▼ ':''))+Math.abs(p.day_pct).toFixed(2)+'%'):'',p.day_pct>0?UP:(p.day_pct<0?DN:MUT)],['PER',f.PER!=null?N(f.PER,1)+'배':'-','',MUT],['PBR',f.PBR!=null?N(f.PBR,2)+'배':'-','',MUT],
  ['ROE',bs.roe!=null?N(bs.roe,1)+'%':'-','',MUT],['영업이익률',bs.opm!=null?N(bs.opm,1)+'%':'-','',MUT],['부채비율',bs.debt_ratio!=null?N(bs.debt_ratio,0)+'%':'-','',MUT]];
 tiles.forEach(function(t,i){var x=50+(i%3)*337,y=1160+dy+Math.floor(i/3)*112;c.save();c.shadowColor='rgba(15,23,42,.12)';c.shadowBlur=16;c.shadowOffsetY=4;RR(c,x,y,306,98,18);c.fillStyle='#fff';c.fill();c.restore();
  T(c,t[0],x+22,y+34,{s:20,w:700,c:MUT});T(c,t[1],x+22,y+76,{s:38,w:900,c:INK,max:200});if(t[2])T(c,t[2],x+284,y+34,{s:22,w:800,c:t[3],a:'right'})});
 foot(c,W,1396+dy,d);return m.cv}

/* ② 5개년 재무 */
function fin(d,scale){var W=1080,H=1450,m=K.make(W,H,scale),c=m.c,ys=d.years||[];c.fillStyle=PAPER;c.fillRect(0,0,W,H);band(c,W,'5-YEAR FINANCIALS',d.name+' 5개년 재무',d.ticker+' · 금액 억원(1만 억 이상은 조) · E=컨센서스 추정');
 card(c,50,226,W-100,500,'매출 · 영업이익 · 영업이익률','#0891b2');K.legend(c,84,300,[{name:'매출액',color:'#2563eb'},{name:'영업이익',color:'#f59e0b'},{name:'영업이익률(%)',color:'#e11d48',line:1}],20);
 K.bars(c,76,314,W-152,386,{labels:ys.map(function(y){return String(y.y).slice(2)+'년'}),est:ys.map(function(y){return !!y.estimate}),bars:[{name:'매출액',values:ys.map(function(y){return y.rev}),color:'#2563eb'},{name:'영업이익',values:ys.map(function(y){return y.op}),color:'#f59e0b'}],line:{name:'영업이익률',values:ys.map(function(y){return y.opm}),color:'#e11d48',unit:'%'},fmt:eok,fs:19});
 card(c,50,756,W-100,520,'연도별 요약','#4f46e5');
 var rows=[['매출액',function(y){return N(y.rev,0)}],['전년비(%)',function(y){return y.rev_g==null?'-':(y.rev_g>0?'+':'')+N(y.rev_g,1)},'sg'],['영업이익',function(y){return N(y.op,0)},'sg0'],['영업이익률(%)',function(y){return N(y.opm,1)}],['순이익',function(y){return N(y.ni,0)},'sg0'],['ROE(%)',function(y){return N(y.roe,1)}],['부채비율(%)',function(y){return N(y.debt_ratio,0)}]];
 var n=Math.max(1,ys.length),x0=84,lw=230,cw=(W-100-34-lw-20)/n,y0=842,rh=56;
 ys.forEach(function(y,i){T(c,String(y.y).slice(2)+'년'+(y.estimate?'E':''),x0+lw+cw*i+cw-6,y0,{s:22,w:800,c:'#475569',a:'right'})});c.fillStyle='#e2e8f0';c.fillRect(x0,y0+14,W-100-68,2);
 rows.forEach(function(r,ri){var y=y0+34+ri*rh;if(ri%2===0){c.fillStyle='rgba(241,245,249,.8)';RR(c,x0-8,y-4,W-100-52,rh-6,10);c.fill()}T(c,r[0],x0,y+30,{s:23,w:800,c:'#334155'});
  ys.forEach(function(yy,i){var v=r[1](yy),cc=INK;if(r[2]==='sg'&&yy.rev_g!=null)cc=yy.rev_g>0?UP:(yy.rev_g<0?DN:INK);if(r[2]==='sg0'){var raw=r[0]==='영업이익'?yy.op:yy.ni;if(raw!=null)cc=raw<0?DN:INK}T(c,v,x0+lw+cw*i+cw-6,y+30,{s:23,w:700,c:cc,a:'right',max:cw-8})})});
 foot(c,W,1308,d);return m.cv}

/* ③ 통합 */
function sum(d,scale){var rk=risk(d),oy=rk?100:0,W=1080,vv0=((d.valuation||{}).bands||[]).filter(function(b){return b.low!=null&&b.mid!=null&&b.high!=null}).slice(0,3),bh0=Math.max(150,120+vv0.length*78),ph0=100+(((d.peers||[]).slice(0,3)).length+2)*54,chh0=100+((d.checklist||[]).slice(0,6)).length*62,H=226+oy+440+bh0+30+ph0+30+chh0+34+110,m=K.make(W,H,scale),c=m.c,s=d.score,bs=s.basis,AX=axes(d);c.fillStyle=PAPER;c.fillRect(0,0,W,H);band(c,W,'DEEP DIVE SUMMARY',d.name+' 통합 요약',d.ticker+' · '+(d.market||'')+(sec(d)?' · '+sec(d):'')+(d.cap?' · 시총 '+cap(d.cap):''));
 if(rk)riskBand(c,60,220,W-120,rk);
 var y=226+oy;
 /* A. 5축 */
 card(c,50,y,W-100,410,'5축 체력 진단 · 체력지표 '+s.total+'(참고)','#2563eb');
 var NT=['영업이익률 '+N(bs.opm,1)+'% · ROE '+N(bs.roe,1)+'%','부채비율 '+N(bs.debt_ratio,0)+'% · 당좌비율 '+N(bs.cur_ratio,0)+'%','매출 CAGR '+N(bs.rev_cagr,1)+'% · 영업이익 CAGR '+N(bs.op_cagr,1)+'%','최근3년 배당 '+bs.div_paid_3y+'회 · 성향 '+N(bs.payout,1)+'%',((d.valuation&&d.valuation.notes)||[]).join(' · ')];
 AX.forEach(function(a,i){var yy=y+92+i*62;T(c,a.name,84,yy+10,{s:24,w:800,c:'#334155'});RR(c,236,yy-8,430,20,10);c.fillStyle='#eef2f7';c.fill();RR(c,236,yy-8,Math.max(14,430*(a.score||0)/100),20,10);var gg=c.createLinearGradient(236,0,666,0);gg.addColorStop(0,a.col);gg.addColorStop(1,col(a.score||0));c.fillStyle=gg;c.fill();
  T(c,a.score==null?'-':String(a.score),712,yy+12,{s:28,w:900,c:col(a.score||0),a:'right'});T(c,NT[i]||'',236,yy+34,{s:18,w:600,c:MUT,max:470})});
 K.ring(c,882,y+232,76,s.total,{th:16,col:col(s.total),tc:INK,fs:46,sub:bandTxt(s.grade),ss:20,sc:MUT,track:'rgba(148,163,184,.3)'});
 y+=440;
 /* B. 밸류에이션 */
  var v=d.valuation||{bands:[]},bands=(v.bands||[]).filter(function(b){return b.low!=null&&b.mid!=null&&b.high!=null}).slice(0,3),bh=Math.max(150,120+bands.length*78);card(c,50,y,W-100,bh,'밸류에이션 밴드 (참고 계산)','#0d9488');
 if(!bands.length)T(c,'PEER 배수·EPS 자료가 부족해 밴드를 만들지 못했어요.',84,y+110,{s:22,w:600,c:MUT});
 bands.forEach(function(b,i){var yy=y+120+i*78,lo=Math.min(b.low,v.price||b.low)*0.9,hi=Math.max(b.high,v.price||b.high)*1.08,sx=function(z){return 300+(z-lo)/(hi-lo)*(W-100-300-40)};T(c,b.name,84,yy+12,{s:22,w:800,c:'#334155',max:200});
  RR(c,300,yy-2,W-100-340,14,7);c.fillStyle='#eef2f7';c.fill();RR(c,sx(b.low),yy-8,Math.max(8,sx(b.high)-sx(b.low)),26,10);c.fillStyle='rgba(13,148,136,.35)';c.fill();c.strokeStyle='#0d9488';c.lineWidth=2;c.stroke();c.fillStyle='#0f766e';c.fillRect(sx(b.mid)-2,yy-12,4,34);
  if(v.price){var px=sx(v.price);c.fillStyle=UP;c.fillRect(px-2,yy-18,4,46);if(i===0)T(c,'현재가 '+N(v.price,0),Math.min(W-170,Math.max(px,330)),yy-26,{s:19,w:900,c:UP,a:'center'})}
  var xl=sx(b.low),xm=sx(b.mid),xh=sx(b.high);T(c,N(b.low,0),xl,yy+44,{s:17,w:700,c:MUT,a:xl<340?'left':'center'});T(c,N(b.high,0),xh,yy+44,{s:17,w:700,c:MUT,a:'right'});if(xm-xl>110&&xh-xm>110)T(c,N(b.mid,0),xm,yy+44,{s:19,w:900,c:'#0f766e',a:'center'})});
 y+=bh+30;
 /* C. PEER */
 var peers=(d.peers||[]).slice(0,3),ph=100+(peers.length+2)*54;card(c,50,y,W-100,ph,'PEER 비교 (동일 업종)','#7c3aed');
 var cols=[['종목',84,'left'],['PER',560,'right'],['PBR',650,'right'],['ROE',760,'right'],['영업이익률',900,'right'],['20일',1004,'right']];cols.forEach(function(k){T(c,k[0],k[1],y+104,{s:20,w:800,c:'#475569',a:k[2]})});c.fillStyle='#e2e8f0';c.fillRect(84,y+116,W-100-68,2);
 var f=d.fundamentals||{},prs=[[d.name+' (본 종목)',f.PER,f.PBR,bs.roe,bs.opm,(d.price||{}).pct20,1]].concat(peers.map(function(x){return [x.name,x.per,x.pbr,x.roe,x.opm,x.pct20,0]}));
 prs.forEach(function(r,i){var yy=y+124+i*54;if(r[6]){c.fillStyle='rgba(124,58,237,.08)';RR(c,76,yy-2,W-100-52,50,10);c.fill()}T(c,r[0],84,yy+32,{s:22,w:r[6]?900:700,c:INK,max:440});
  [[1,560,1],[2,650,2],[3,760,1],[4,900,1],[5,1004,1]].forEach(function(k){var val=r[k[0]];T(c,val==null?'-':N(val,k[2]),k[1],yy+32,{s:22,w:700,c:k[0]===5&&val!=null?(val>0?UP:(val<0?DN:INK)):INK,a:'right'})})});
 if(!peers.length)T(c,'동일 업종 PEER 자료를 찾지 못했어요.',84,y+ph-24,{s:19,w:600,c:MUT});
 y+=ph+30;
 /* D. 체크리스트 */
 var ck=(d.checklist||[]).slice(0,6),okn=(d.checklist||[]).filter(function(x){return x.state==='ok'}).length,tot=(d.checklist||[]).filter(function(x){return x.state!=='na'}).length,chh=100+ck.length*62;card(c,50,y,W-100,chh,'투자 전 체크리스트 ('+okn+'/'+tot+' 충족)','#ca8a04');
 ck.forEach(function(x,i){var yy=y+96+i*62,cc=x.state==='ok'?'#16a34a':(x.state==='warn'?'#d97706':'#94a3b8');c.beginPath();c.arc(100,yy+20,17,0,Math.PI*2);c.fillStyle=cc;c.fill();T(c,x.state==='ok'?'✓':(x.state==='warn'?'!':'–'),100,yy+28,{s:22,w:900,c:'#fff',a:'center'});
  T(c,x.label,132,yy+16,{s:22,w:800,c:INK,max:260});T(c,x.note||'',132,yy+42,{s:18,w:600,c:MUT,max:W-100-120})});
 y+=chh+34;foot(c,W,y,d);
 return m.cv}
window.DpImg={build:function(d,scale){return [{idx:1,label:'메인 이미지',canvas:main(d,scale)},{idx:2,label:'5개년 재무',canvas:fin(d,scale)},{idx:3,label:'통합 요약',canvas:sum(d,scale)}]}};
})();
"""


def register():
    for _k, _l in ("deep/data", "심층분석 자료 모으기"), ("deep/prompt", "심층분석 AI 요청문 만들기"), ("deep/blog", "심층분석 블로그 글 만들기"):
        C.prog_declare(_k, _l)
    C.register_menu({"id": "deep", "label": "심층분석", "icon": "🏛", "public_path": "/m/deep", "admin_path": "/admin#dp",
                     "desc": "종목 하나를 5개년 재무·5축 체력 진단·밸류에이션·PEER 비교·체크리스트·수급·공시까지 깊이 살펴봐요. 투자 권유가 아닌 참고용 정보예요.",
                     "access": "admin"})
    C.register_prompt("deep_report", {
        "title": "기업 심층분석 AI 프롬프트", "default": DEEP_DEFAULT, "required": ["{data}"], "must_have": ["## 1."],
        "vars": "{data}=종목 데이터 요약(필수) · {name} · {ticker} · {today}",
        "desc": "심층분석 화면에서 AI에게 보내는 요청문. '## 1.'~'## 7.' 제목 형식을 유지해야 블로그 글의 섹션 카드로 나뉘어 들어가요."})
    C.register_admin_tab("dp", "🏛 심층분석", TAB_JS, "dpLoad", menu="deep")
    # ── 기능별 공개(기본값은 관리자가 [🎚 기능 공개]에서 바꾼다) ──
    # deep/data 한 주소가 아래 기능들의 자료를 섞어 내보낸다 → 주소 자체의 문은 base 이고, 나머지 섹션은 gate_data() 가 서버에서 뺀다.
    F = C.register_feature
    F("deep", "base", "체력지표·5축·기업현황", "종목 검색, 체력지표(참고)·5축 레이더, 핵심 타일(현재가·PER·PBR·ROE…), 기업 현황. 다른 구역의 바탕이라 이 기능이 열려 있어야 화면이 나와요.",
      default="public", endpoints=["/admin/api/deep/search", "/admin/api/deep/saved", "/admin/api/deep/data"])
    F("deep", "fin", "5개년 재무", "매출·영업이익·순이익·ROE·부채비율 등 연도별 재무 차트와 표.", default="member")
    F("deep", "val", "밸류에이션", "PER·PBR 밴드와 컨센서스 대비 위치(참고 계산, 적정주가 아님).", default="member")
    F("deep", "chk", "투자 전 체크리스트", "수익성·안정성·배당·공시 등을 자동으로 점검한 표.", default="member")
    F("deep", "peer", "PEER 비교", "같은 업종 종목과 PER·PBR·ROE·영업이익률 비교.", default="L2")
    F("deep", "sup", "수급·공시·뉴스", "외국인·기관·개인 수급 흐름과 최근 공시·뉴스 제목.", default="L2")
    F("deep", "ai", "AI 정성 분석 요청문", "자료를 담은 AI 요청문(프롬프트)을 만들어 복사해요. 재무·밸류에이션·PEER·체크리스트·수급이 모두 열려 있어야 만들어져요.",
      default="L2", endpoints=["/admin/api/deep/prompt"], kind="tool")
    F("deep", "img", "요약 이미지 내려받기", "체력지표·5축·재무·통합 요약을 이미지 3장으로 만들어 내려받아요.", default="L3", kind="tool")
    # 블로그 글 만들기(deep/blog)·작성 이력 등 관리자 업무는 어떤 기능에도 넣지 않았다 → 관리자 화면에서만 동작(회원 화면에서는 아예 숨김)
    C.register_flow("deep", "🏛 심층분석", "① 종목 심층분석 열기(분석이 열리면 자동으로 시작)", [
        {"id": "ai", "label": "② AI 정성 분석", "desc": "분석이 열리면 AI 요청문 창을 자동으로 열어요. 답변을 복사해 돌아오면 다음 단계로 이어져요(이미 AI 글이 있으면 건너뛰어요)."},
        {"id": "img", "label": "③ 이미지 만들기", "desc": "AI 단계가 끝나면 이미지 3장을 자동으로 그려요."},
        {"id": "blog", "label": "④ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요."},
        {"id": "post", "label": "⑤ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요. 브라우저가 복사·새 창을 막으면 [📋 복사하고 블로그 열기]를 한 번 눌러 주세요."}])
    return bp
