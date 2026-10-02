"""🏛 기업 심층분석 (관리자 전용 메뉴) — 원본 프로그램의 심층분석 + 추가 기능, 블로그 글쓰기 포함.

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
def build_deep(ticker, custom_peers=None):
    payload, _hit = _get_analysis(ticker)
    if not payload or payload.get("error"):
        return None, (payload or {}).get("error") or "분석 결과를 가져오지 못했어요."
    f = payload.get("fundamentals") or {}
    cache, cache_at = saved_quant(ticker)
    nyears = years_from_naver(payload)
    years = merge_years((cache or {}).get("years"), nyears)
    divs = build_divs(cache, years, f)
    peers = peer_metrics(peer_codes(ticker, payload, custom_peers))
    valu = valuation(payload, peers)
    sc = score_card(years, divs)
    five = int(round(sc["prof"] * 0.25 + sc["stab"] * 0.20 + sc["grow"] * 0.20 + sc["gov"] * 0.15 + valu["score"] * 0.20))
    sc.update({"valu": valu["score"], "total": five, "grade": grade(five),
               "grades": {"prof": grade(sc["prof"]), "stab": grade(sc["stab"]), "grow": grade(sc["grow"]), "gov": grade(sc["gov"]), "valu": grade(valu["score"])},
               "orig_grade": grade(sc["orig_total"])})
    sup = L.supply_analysis(L._trend_rows(ticker))
    disc = L.disclosures(ticker)
    news = ((payload.get("details") or {}).get("news") or [])[:10]
    profile, holders = (cache or {}).get("profile"), (cache or {}).get("holders") or []
    prof_src = "DART(원본 저장)" if profile else ""
    if not profile:
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
    L_.append(f"체력 진단(0~100): 수익성 {s['prof']}({s['grades']['prof']}) 안정성 {s['stab']}({s['grades']['stab']}) 성장성 {s['grow']}({s['grades']['grow']}) 주주환원·거버넌스 {s['gov']}({s['grades']['gov']}) 밸류에이션 {s['valu']}({s['grades']['valu']}) → 종합 {s['total']}점 {s['grade']}등급 (원본 4축식 {s['orig_total']}점)")
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
    tags, tag_html = B.hashtags([name, name + "심층분석"], date_k, extra=["기업분석", "재무분석", "기업심층분석"])
    h = [B.seo_box(title, f"{name}의 5개년 재무와 체력 진단, 밸류에이션, 수급·공시를 데이터로 정리한 기업 심층분석입니다. (기준 {d.get('as_of')})", kw)]
    badge = f'<span style="font-size:12px;font-weight:800;color:{B.NAVY};background-color:{B.GOLD};padding:2px 10px;border-radius:10px;">종합 {s["total"]}점 · {s["grade"]}등급</span>'
    h.append(B.head_box("COMPANY DEEP DIVE", f'🏛 {E(name)} <span style="font-size:15px;color:#cbd5e1;">{E(ticker)}</span>',
                        f'{E(d.get("market"))} · {E(d.get("sector") or "-")} · 시총 {E(d.get("cap") or "-")} · {date_k}<br>{badge}', B.delist_box(d.get("delisting")) and ""))
    h.append(B.delist_box(d.get("delisting")))
    h.append(B.engage_box())
    p = d.get("price") or {}
    f = d.get("fundamentals") or {}
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
        h.append(f'<p style="font-size:15px;margin:10px 0 0;{B.FONT}"><b>종합 {s["total"]}점 · {s["grade"]}등급</b> <span style="font-size:11px;color:#9ca3af;">(수익성 25%·안정성 20%·성장성 20%·거버넌스 15%·밸류에이션 20% — 원본 4축 방식으로는 {s["orig_total"]}점 {s["orig_grade"]}등급, 참고용 지표)</span></p>'
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
        col = {"risk": ("#fef2f2", "#b91c1c", "주의"), "pos": ("#f0fdf4", "#15803d", "호재성"), "info": ("#f9fafb", "#6b7280", "참고")}
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
    return _admin_json(x)


@bp.route("/admin/api/deep/prompt", methods=["POST"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
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
var DP={tk:null,d:null,ai:{},peers:{},q:'',sugg:[],saved:null};
function dpCol(s){return s>=70?'#16a34a':(s>=50?'#d97706':'#dc2626')}
function dpN(v,d){if(v==null)return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?1:d})}
function dpCls(v){return v>0?'up':(v<0?'dn':'')}
function dpSty(e,s){e.style.cssText=s;return e}
function dpLoad(p){p.innerHTML='';var top=el('div','c');top.appendChild(el('b',null,'🏛 기업 심층분석'));
 top.appendChild(el('p','note','종목을 고르면 5개년 재무·체력 진단(5축)·밸류에이션·PEER·체크리스트·수급·공시를 한 화면에 모아 보여주고, AI 정성 분석과 블로그 글(복사하고 바로 열기)까지 이어서 만들 수 있어요. 원본 프로그램에서 이미 분석해 둔 종목은 그 저장분(DART 5개년·최대주주·AI 글)을 함께 불러옵니다.'));
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
function dpSavedDraw(p){var sv=$('dpSaved');if(!sv)return;sv.innerHTML='';if(!DP.saved||!DP.saved.length)return;sv.appendChild(el('span','m','원본 저장분 있는 종목(최근순): '));
 DP.saved.slice(0,24).forEach(function(x){var b=bt((x.name||x.ticker)+' '+x.at.slice(5),'bt3',function(){dpOpen(x.ticker,p)});b.style.margin='2px';sv.appendChild(b)})}
function dpOpen(tk,p,peers){DP.tk=tk;var b=$('dpBody');b.innerHTML='';b.appendChild(el('div','c','⏳ 재무·수급·공시·PEER를 모으는 중… (처음 한 번 5~10초)'));
 apiJ('/admin/api/deep/data',{ticker:tk,peers:peers||DP.peers[tk]||[]}).then(function(j){if(j.error){b.innerHTML='';b.appendChild(el('div','c bad','⚠ '+j.error));return}DP.d=j;dpDraw(p)})}
function dpBar(parent,name,score,grade,note){var r=el('div');dpSty(r,'display:grid;grid-template-columns:90px 42px 34px 1fr;gap:8px;align-items:center;margin:6px 0;font-size:13px');r.appendChild(el('b',null,name));var n=el('b',null,score);n.style.color=dpCol(score);r.appendChild(n);var g=el('b',null,grade||'');g.style.color=dpCol(score);r.appendChild(g);
 var w=el('div');dpSty(w,'height:10px;background:#e5e7eb;border-radius:6px;overflow:hidden');var i=el('div');dpSty(i,'height:100%;width:'+score+'%;background:'+dpCol(score));w.appendChild(i);r.appendChild(w);parent.appendChild(r);if(note){var m=el('div','m',note);m.style.margin='-2px 0 4px 132px';parent.appendChild(m)}}
function dpTable(parent,head,rows,opt){var tw=el('div');tw.style.overflowX='auto';var t=el('table'),h=el('tr');head.forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 rows.forEach(function(r){var tr=el('tr');r.forEach(function(c,i){var td=el('td',(opt&&opt.cls&&opt.cls[i])||'',c==null?'-':String(c));tr.appendChild(td)});t.appendChild(tr)});tw.appendChild(t);parent.appendChild(tw)}
function dpDraw(p){var d=DP.d,b=$('dpBody');if(!d||!b)return;b.innerHTML='';var s=d.score;
 var hero=el('div','c');var hh=el('div');dpSty(hh,'display:flex;align-items:center;gap:16px;flex-wrap:wrap');
 var big=el('div',null,s.total+'점');dpSty(big,'font-size:42px;font-weight:900;line-height:1;color:'+dpCol(s.total));hh.appendChild(big);
 var t=el('div');t.appendChild(el('b',null,d.name+' ('+d.ticker+') · '+s.grade+'등급'));t.appendChild(el('div','m',(d.market||'')+' · '+(d.sector||'-')+' · 시총 '+(d.cap||'-')+' · 기준 '+(d.as_of||'')));t.appendChild(el('div','m','재무 출처: '+d.years_src+(d.saved.quant_at?' ('+d.saved.quant_at+' 저장)':'')));hh.appendChild(t);hero.appendChild(hh);
 if(d.dup_warn){var w=el('div','note bad','⚠ '+d.dup_warn);w.style.marginTop='8px';hero.appendChild(w)}
 if(d.delisting&&d.delisting.level&&d.delisting.level!=='none'){var w2=el('div','note bad','⚠ 상장폐지·거래정지 유의 신호('+d.delisting.level+'): '+(d.delisting.reasons||[]).join(' / '));w2.style.marginTop='6px';hero.appendChild(w2)}
 var lk=el('div','m');[['네이버증권',d.links.naver],['DART',d.links.dart],['KIND',d.links.kind]].forEach(function(x){var a=el('a',null,x[0]);a.href=x[1];a.target='_blank';a.rel='noopener';lk.appendChild(a);lk.appendChild(document.createTextNode('  '))});hero.appendChild(lk);b.appendChild(hero);
 // 5축
 var c1=el('div','c');c1.appendChild(el('b',null,'🎯 5축 체력 진단'));var g=s.grades,bs=s.basis;
 dpBar(c1,'수익성',s.prof,g.prof,'영업이익률 '+dpN(bs.opm)+'% · ROE '+dpN(bs.roe)+'%');dpBar(c1,'안정성',s.stab,g.stab,'부채비율 '+dpN(bs.debt_ratio,0)+'% · 유동(당좌)비율 '+dpN(bs.cur_ratio,0)+'% · 흑자 '+bs.black_years+'년');
 dpBar(c1,'성장성',s.grow,g.grow,'매출 CAGR '+dpN(bs.rev_cagr)+'% · 영업이익 CAGR '+dpN(bs.op_cagr)+'%');dpBar(c1,'거버넌스',s.gov,g.gov,'최근3년 배당 '+bs.div_paid_3y+'회 · 수익률 '+dpN(bs.div_yld)+'% · 성향 '+dpN(bs.payout)+'%');
 dpBar(c1,'밸류에이션',s.valu,g.valu,(d.valuation.notes||[]).join(' · '));c1.appendChild(el('p','note','종합 = 수익성 25% + 안정성 20% + 성장성 20% + 거버넌스 15% + 밸류에이션 20%. 원본 4축 방식으로 계산하면 '+s.orig_total+'점('+s.orig_grade+'등급)이에요. 참고용 지표입니다.'));b.appendChild(c1);
 // 재무표
 var c2=el('div','c');c2.appendChild(el('b',null,'📊 연도별 재무 (억원)'));var ys=d.years;var rows=[['매출액'].concat(ys.map(function(y){return dpN(y.rev,0)})),['  전년비(%)'].concat(ys.map(function(y){return dpN(y.rev_g)})),['영업이익'].concat(ys.map(function(y){return dpN(y.op,0)})),['영업이익률(%)'].concat(ys.map(function(y){return dpN(y.opm)})),['순이익'].concat(ys.map(function(y){return dpN(y.ni,0)})),['ROE(%)'].concat(ys.map(function(y){return dpN(y.roe)})),['부채비율(%)'].concat(ys.map(function(y){return dpN(y.debt_ratio,0)})),['유동(당좌)비율(%)'].concat(ys.map(function(y){return dpN(y.cur_ratio,0)}))];
 if(ys.some(function(y){return y.ocf!=null}))rows.push(['영업현금흐름'].concat(ys.map(function(y){return dpN(y.ocf,0)})),['간이 FCF'].concat(ys.map(function(y){return dpN(y.fcf,0)})));rows.push(['EPS(원)'].concat(ys.map(function(y){return dpN(y.eps,0)})),['주당배당금(원)'].concat(ys.map(function(y){return dpN(y.dps,0)})));
 dpTable(c2,['항목'].concat(ys.map(function(y){return y.label+(y.estimate?'(E)':'')})),rows);c2.appendChild(el('p','note','(E)는 증권사 컨센서스 추정치. 5개년 DART 자료는 원본 저장분이 있는 종목에서 나와요.'));b.appendChild(c2);
 // 프로필·주주
 if(d.profile||d.holders.length){var c3=el('div','c');c3.appendChild(el('b',null,'🏢 기업 현황'+(d.profile_src?' ('+d.profile_src+')':'')));if(d.profile){var pr=d.profile;c3.appendChild(el('p','note',['대표 '+(pr.ceo||'-'),'설립 '+(pr.est_dt||'-'),'결산 '+(pr.acc_mt||'-'),(pr.corp_cls||''),(pr.adres||'')].join(' · ')))}
  if(d.holders.length)dpTable(c3,['주주','관계','지분율(%)'],d.holders.map(function(h){return [h.nm,h.relate,dpN(h.rt,2)]}));b.appendChild(c3)}
 // 밸류에이션
 var c4=el('div','c');c4.appendChild(el('b',null,'💹 밸류에이션 밴드 (참고 계산)'));var v=d.valuation;
 if(v.bands.length){dpTable(c4,['방법','낮은 값','중간','높은 값','근거'],v.bands.map(function(x){return [x.name,dpN(x.low,0),dpN(x.mid,0),dpN(x.high,0),x.basis]}));c4.appendChild(el('p','note','현재가 '+dpN(v.price,0)+'원'+(v.upside!=null?' · 컨센서스 목표가 대비 '+(v.upside>0?'+':'')+v.upside+'%':'')+'. PEER·업종 배수를 단순 적용한 값이라 적정주가·목표가가 아니에요.'))}else c4.appendChild(el('p','note','PEER 배수나 EPS 자료가 부족해 밴드를 만들지 못했어요.'));b.appendChild(c4);
 // PEER
 var c5=el('div','c');c5.appendChild(el('b',null,'🤝 PEER 비교'));
 if(d.peers.length){var me=[d.name+' (본 종목)',dpN(d.fundamentals.PER),dpN(d.fundamentals.PBR,2),dpN(bs.roe),dpN(bs.opm),'-',dpN((d.price||{}).pct20)];dpTable(c5,['종목','PER','PBR','ROE(%)','영업이익률(%)','시총(억)','20일(%)'],[me].concat(d.peers.map(function(x){return [x.name+' '+x.ticker,dpN(x.per),dpN(x.pbr,2),dpN(x.roe),dpN(x.opm),dpN(x.cap_eok,0),dpN(x.pct20)]})))}else c5.appendChild(el('p','note','동일 업종 PEER를 찾지 못했어요. 아래에 종목코드를 직접 넣을 수 있어요.'));
 var pr=el('div','bar');var pi=el('input');pi.placeholder='PEER 종목코드 (쉼표로 구분, 예: 000660,005380)';pi.style.width='300px';pi.value=(DP.peers[d.ticker]||[]).join(',');pr.appendChild(pi);pr.appendChild(bt('PEER 다시 계산','bt2',function(){var a=pi.value.split(/[ ,]+/).map(function(x){return x.trim().toUpperCase()}).filter(function(x){return /^[0-9A-Z]{6}$/.test(x)}).slice(0,6);DP.peers[d.ticker]=a;dpOpen(d.ticker,p,a)}));c5.appendChild(pr);b.appendChild(c5);
 // 체크리스트
 var c6=el('div','c');var okn=d.checklist.filter(function(x){return x.state==='ok'}).length,tot=d.checklist.filter(function(x){return x.state!=='na'}).length;c6.appendChild(el('b',null,'📝 투자 전 체크리스트 ('+okn+'/'+tot+' 충족)'));
 dpTable(c6,['','항목','내용'],d.checklist.map(function(x){return [x.state==='ok'?'✅':(x.state==='warn'?'⚠️':'➖'),x.label,x.note]}));b.appendChild(c6);
 // 수급·공시
 var c7=el('div','c');c7.appendChild(el('b',null,'👥 수급 · 📄 공시 · 📰 뉴스'));var sp=d.supply;if(sp){c7.appendChild(el('p','note',sp.summary||''));
  dpTable(c7,['기간','외국인(억)','기관(억)','개인(억)'],['1','3','5','10','20'].filter(function(n){return sp.per[n]&&sp.per[n].days>=Number(n)}).map(function(n){var x=sp.per[n];return [n+'일',dpN(x.foreign_eok,0),dpN(x.inst_eok,0),dpN(x.indiv_eok,0)]}))}
 dpTable(c7,['날짜','분류','공시 제목'],(d.disc||[]).slice(0,8).map(function(x){return [x.date.slice(5),x.tag,x.title]}));
 (d.news||[]).slice(0,6).forEach(function(n){c7.appendChild(el('div','m','▪ '+n.title+' ('+n.press+' '+n.date+')'))});b.appendChild(c7);
 // AI
 var c8=el('div','c');c8.appendChild(el('b',null,'🤖 AI 정성 분석 (사업현황·밸류체인·정량해석·정성분석·리스크·뉴스)'));
 c8.appendChild(el('p','note','위 데이터를 정리한 프롬프트를 만들어 설정된 AI를 열어요. 답변을 복사하고 이 탭으로 돌아오면 자동으로 읽어 옵니다. 프롬프트는 [프롬프트] 탭에서 고칠 수 있어요.'));
 var rr=el('div');rr.appendChild(bt('🤖 AI 분석 만들기','bt',function(){dpAI(d)}));
 if(d.saved.has_ai){rr.appendChild(bt('📂 원본 저장 AI 글 불러오기 ('+d.saved.ai_at+')','bt2',function(){DP.ai[d.ticker]=d.saved.ai_text;var ta=$('dpAiTa');if(ta)ta.value=d.saved.ai_text;dpAiState();toast('원본 프로그램이 저장해 둔 AI 글을 불러왔어요')}))}c8.appendChild(rr);
 var st=el('div','m');st.id='dpAiState';c8.appendChild(st);var ta=el('textarea');ta.id='dpAiTa';ta.placeholder='AI 답변을 직접 붙여넣어도 돼요.';dpSty(ta,'width:100%;min-height:120px;box-sizing:border-box');ta.value=DP.ai[d.ticker]||'';ta.oninput=function(){DP.ai[d.ticker]=ta.value;dpAiState()};c8.appendChild(ta);b.appendChild(c8);dpAiState();
 // 블로그
 var c9=el('div','c');c9.appendChild(el('b',null,'📝 블로그 글 만들기 (원본 방식 HTML)'));var bx=el('div');c9.appendChild(bx);b.appendChild(c9);
 var secs=[['profile','기업현황'],['fin','5개년재무'],['score','체력진단'],['valu','밸류에이션'],['peers','PEER'],['check','체크리스트'],['supply','수급'],['disc','공시·뉴스'],['ai','AI분석'],['terms','용어풀이']];
 window.BlogKit.panel(bx,{idp:'dp',key:'deepdive',kind:'deepdive',ticker:d.ticker,name:d.name,sections:secs,dup_warn:d.dup_warn,
  build:function(inc,title){return apiJ('/admin/api/deep/blog',{ticker:d.ticker,peers:DP.peers[d.ticker]||[],ai:DP.ai[d.ticker]||'',inc:inc,title:title})},onLogged:function(z){d.dup_warn=z.dup_warn}})}
function dpAiState(){var d=DP.d,z=$('dpAiState');if(!z||!d)return;var t=DP.ai[d.ticker]||'';z.textContent=t.trim()?('✅ AI 글 '+t.length.toLocaleString()+'자 — 블로그 글에 포함돼요.'):'아직 AI 글이 없어요(없어도 블로그 글은 만들 수 있어요).'}
function dpAI(d){if(!window.MiniAI){toast('AI 도우미 파일(menu_ui.py)이 올라가지 않았어요.');return}
 apiJ('/admin/api/deep/prompt',{ticker:d.ticker,peers:DP.peers[d.ticker]||[]}).then(function(j){if(j.error){toast(j.error);return}
  window.MiniAI.run({title:'기업 심층분석 AI — '+j.name,key:'deep',steps:[{label:j.name,prompt:j.prompt}],minLen:400,hint:'AI가 "## 1. 사업 현황 …" 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){var ok=/##\s*1\./.test(t)||t.length>900;var n=(t.match(/^#{1,4}\s*\d+\./gm)||[]).length;var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString()+'자 · 섹션 '+n+'개 — '+t.slice(0,300)+(t.length>300?' …':'');return {node:x,canApply:ok,text:ok?null:'형식(## 1. 사업 현황 …)이 보이지 않아요. 다른 답변이 복사된 건 아닌지 확인하세요.'}},
   apply:function(t){DP.ai[d.ticker]=t;var ta=$('dpAiTa');if(ta)ta.value=t;dpAiState();return Promise.resolve({message:'AI 글을 읽어 왔어요. 아래 [글 만들기]를 누르세요.'})}})})}
"""


def register():
    C.register_menu({"id": "deep", "label": "심층분석", "icon": "🏛", "public_path": "/deepdive", "admin_path": "/admin#dp",
                     "desc": "5개년 재무·체력 진단·밸류에이션·PEER·AI 정성 분석 + 블로그 글쓰기", "access": "admin", "admin_only": True})
    C.register_prompt("deep_report", {
        "title": "기업 심층분석 AI 프롬프트", "default": DEEP_DEFAULT, "required": ["{data}"], "must_have": ["## 1."],
        "vars": "{data}=종목 데이터 요약(필수) · {name} · {ticker} · {today}",
        "desc": "심층분석 화면에서 AI에게 보내는 요청문. '## 1.'~'## 7.' 제목 형식을 유지해야 블로그 글의 섹션 카드로 나뉘어 들어가요."})
    C.register_admin_tab("dp", "🏛 심층분석", TAB_JS, "dpLoad")
    return bp
