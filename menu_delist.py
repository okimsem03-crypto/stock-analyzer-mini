"""🚫 거래정지·상장폐지(투자주의) 메뉴 — 원본 프로그램의 '투자주의 · 상장폐지 위험 스크리닝' 화면 구성을 따른다.

  · 스크리닝: 네이버 모바일 증권의 전 종목 시세 목록(시가총액 순위 API) 한 번으로 종목별 시가총액·현재가·등락률·거래상태를
    함께 받아, 관리자가 정한 '기준(시총 미달·동전주 등)'에 맞는 종목과 거래상태 이상 신호가 있는 종목을 가려낸다.
    자동 계산은 틀릴 수 있으며, 결과는 '위험(기준 미달 · 거래상태 이상)'과 '경계(기준 근접)'로만 나눠 보여준다(확정 아님).
  · 신규진입·졸업: 직전에 저장해 둔 스냅샷과 비교한다.
  · 이미지 대시보드·블로그 글·AI 조언을 한 화면에서 만든다.
  · 공개 화면에는 '네이버 거래상태에 거래정지·관리종목·상장폐지·정리매매가 표시된 종목(관리자가 제외한 것 빼고)'만 나온다(기준 미달·추정 신호는 공개하지 않는다).
이 파일은 본체의 함수를 C 로 호출한다(menu_ctx.py 설명 참고).
"""
import re, time, json, sqlite3, threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, jsonify, request, current_app as app
from menu_ctx import C
import menu_ui as U
import menu_blog as B

bp = Blueprint("delist", __name__)

# 본체 함수 — 호출할 때마다 본체에서 찾아 쓴다(시험에서 바꿔 끼워도 반영되도록).
_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_dbx", "_dbrows", "_json_body", "_ensure_v135_tables",
               "normalize_ticker", "setting_get", "setting_set", "_kst_str", "_now_kst", "menu_visible",
               "_naver_mobile_basic", "_naver_trading_status_flags", "ai_pick_provider", "ai_complete",
               "get_db", "get_ticker_info", "prompt_get", "_prompt_fill", "_prompt_check", "_job_busy", "_job_new",
               "_http", "_history_conn")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)
_AIJOBS = {}          # register() 에서 본체의 작업 목록으로 교체된다
E = B.E

DL_VERDICTS = ("거래정지", "관리종목", "상장폐지확정", "정리매매", "정상", "확인불가")
DL_PUBLIC_LABELS = ("거래정지", "관리종목", "상장폐지확정", "정리매매")
DL_PCT_LIMIT = 30.5           # 일일 가격제한폭(±30%)을 넘는 등락 = 정리매매·신규상장일 가능성
_KIND_LABEL = {"halt": "거래정지 신호", "delist": "상폐·정리매매 신호", "screen": "기준 미달", "manual": "직접 추가"}

_DL_SCAN = {"running": False, "phase": "", "total": 0, "done": 0, "pages_total": 0, "pages_done": 0, "ok": 0,
            "flagged": 0, "danger": 0, "warn": 0, "started": 0, "finished": 0, "error": "", "cancel": False}

# ── 스크리닝 기준(원본 delist_criteria 와 같은 값) ──
DEFAULT_CRITERIA = {
    "updated_at": "2026-07-01",
    "source_note": "금융위·한국거래소 상장폐지 개혁방안(2026.2.12 발표, 7.1 시행) 기준",
    "rules": [
        {"key": "cap_kosdaq", "on": True, "market": "KOSDAQ", "metric": "market_cap", "op": "lt", "value": 200, "unit": "억원",
         "warn_days": 30, "grace_days": 90, "recover_days": 45, "label": "코스닥 시가총액 200억 미만",
         "desc": "보통주 시가총액이 200억원 미만인 상태가 연속 30거래일 지속되면 관리종목으로 지정됩니다. 이후 90거래일 동안 연속 45거래일 이상 기준을 회복하지 못하면 상장폐지됩니다. (2027.1.1 300억으로 상향 예정)"},
        {"key": "cap_kospi", "on": True, "market": "KOSPI", "metric": "market_cap", "op": "lt", "value": 300, "unit": "억원",
         "warn_days": 30, "grace_days": 90, "recover_days": 45, "label": "코스피 시가총액 300억 미만",
         "desc": "코스피 보통주 시가총액이 300억원 미만인 상태가 연속 30거래일 지속되면 관리종목으로 지정되고, 90거래일 중 연속 45거래일 이상 회복하지 못하면 상장폐지됩니다. (2027.1.1 500억으로 상향 예정)"},
        {"key": "penny", "on": True, "market": "ALL", "metric": "price", "op": "lt", "value": 1000, "unit": "원",
         "warn_days": 30, "grace_days": 90, "recover_days": 45, "label": "동전주 (주가 1,000원 미만)",
         "desc": "종가가 1,000원 미만인 상태가 연속 30거래일 지속되면 관리종목으로 지정되고, 90거래일 동안 연속 45거래일 이상 1,000원을 회복하지 못하면 상장폐지됩니다. 액면병합으로 우회해도 '병합 후 액면가 미만'이면 대상에 포함됩니다."},
        {"key": "cap_warn_kosdaq", "on": True, "market": "KOSDAQ", "metric": "market_cap", "op": "lt", "value": 260, "unit": "억원",
         "warn_days": 0, "grace_days": 0, "recover_days": 0, "label": "코스닥 시총 경계 (300억 상향 대비)",
         "desc": "2027.1.1부터 코스닥 시가총액 기준이 300억원으로 상향될 예정입니다. 300억원에 근접(약 260억원 미만)한 종목은 선제적인 주의가 필요합니다."},
        {"key": "penny_warn", "on": True, "market": "ALL", "metric": "price", "op": "lt", "value": 1200, "unit": "원",
         "warn_days": 0, "grace_days": 0, "recover_days": 0, "label": "동전주 경계 (1,000원 근접)",
         "desc": "주가가 1,000원에 근접한(1,200원 미만) 종목은 변동성에 따라 동전주 요건에 진입할 수 있어 선제적 관찰이 필요합니다."},
    ],
}


def clean_criteria(crit):
    """관리자가 보낸(또는 AI가 제안한) 기준을 검사해 정리한다. 형식이 틀리면 None."""
    if not isinstance(crit, dict) or not isinstance(crit.get("rules"), list):
        return None
    rules = []
    for r in crit["rules"][:20]:
        try:
            rules.append({
                "key": re.sub(r"[^A-Za-z0-9_]", "", str(r.get("key") or ""))[:40] or ("rule_%d" % len(rules)),
                "on": bool(r.get("on", True)),
                "market": (str(r.get("market") or "ALL").upper() if str(r.get("market") or "ALL").upper() in ("KOSPI", "KOSDAQ", "ALL") else "ALL"),
                "metric": r.get("metric") if r.get("metric") in ("market_cap", "price") else "market_cap",
                "op": "lt",
                "value": max(0.0, float(r.get("value") or 0)),
                "unit": "억원" if r.get("metric") == "market_cap" else "원",
                "warn_days": max(0, min(400, int(float(r.get("warn_days") or 0)))),
                "grace_days": max(0, min(400, int(float(r.get("grace_days") or 0)))),
                "recover_days": max(0, min(400, int(float(r.get("recover_days") or 0)))),
                "label": re.sub(r"[<>]", "", str(r.get("label") or ""))[:80],
                "desc": re.sub(r"[<>]", "", str(r.get("desc") or ""))[:800],
            })
        except Exception:
            continue
    if not rules:
        return None
    return {"updated_at": re.sub(r"[<>]", "", str(crit.get("updated_at") or datetime.now().strftime("%Y-%m-%d")))[:20],
            "source_note": re.sub(r"[<>]", "", str(crit.get("source_note") or ""))[:300], "rules": rules}


def dl_criteria():
    try:
        c = clean_criteria(json.loads(setting_get("delist_criteria", "") or "null"))
    except Exception:
        c = None
    return c or clean_criteria(json.loads(json.dumps(DEFAULT_CRITERIA)))


# ── 프롬프트 ──
DELIST_ADVICE_DEFAULT = """당신은 개인 투자자를 위한 리스크 관리 안내자입니다. 오늘은 {today}입니다.
아래는 프로그램이 공개 시세 데이터로 자동 계산한 '투자주의(상장폐지 위험 스크리닝)' 결과 요약입니다. 확정된 사실이 아니라 기준 미달 여부를 계산한 참고 자료입니다.

[요약]
{summary}

[상위 종목(위험·경계)]
{items}

위 자료만 바탕으로 초보 투자자가 이해하기 쉽게 아래 형식으로 작성하세요. 특정 종목의 매수·매도를 권유하지 마세요. 종목이 상장폐지·관리종목·거래정지된다고 단정하거나 예측하지 말고 '가능성이 있어 보인다', '확인이 필요하다'처럼 조심스럽게 쓰세요.
기재되지 않은 사실(소송, 횡령, 공시 내용 등)은 지어내지 마세요.

## 1. 한 줄 요약
## 2. 투자 시 주의할 점 (3~5개, 초보자 눈높이)
## 3. 유형별 접근 방향 (시가총액 미달형 / 동전주형 / 거래상태 이상형 — 각각 무엇을 어떻게 확인할지)
## 4. 매매 전 체크리스트 (KIND·DART 공시 확인 방법 포함)
## 5. 마무리 (본 내용은 참고용이며 투자 책임은 본인에게 있다는 안내 포함)
"""


# ── 신호 · 평가 ──
_DL_KEYWORDS = ("거래정지", "매매거래정지", "상장폐지", "정리매매", "관리종목", "불성실공시", "투자주의환기")


def _dl_int(v, d=0):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except Exception:
        return d


def _dl_flt(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def _dl_signals(item, stale_days, today):
    """네이버 시세 목록 한 줄(JSON)에서 거래상태 신호를 뽑는다. 반환 (kind|None, [신호문장], 최근거래일)."""
    sig, kind = [], None
    last = ""
    lt = str(item.get("localTradedAt") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", lt):
        last = lt[:10]
    st = item.get("tradeStopType") if isinstance(item.get("tradeStopType"), dict) else {}
    nm = str(st.get("name") or "").upper()
    if nm and nm != "TRADING":
        sig.append("네이버 거래상태: " + str(st.get("text") or st.get("name")))
        kind = "halt"
    for f in _naver_trading_status_flags(item):
        sig.append("네이버 " + f)
        kind = kind or "halt"
    for s in (st.get("text"), st.get("name"), item.get("tradableStatus"), item.get("tradableStatusCode"), item.get("marketStatus")):
        s = str(s or "")
        for kw in _DL_KEYWORDS:
            if kw in s:
                sig.append(f"네이버 표시: {s}")
                kind = "delist" if kw in ("상장폐지", "정리매매") else (kind or "halt")
                break
    if last:
        try:
            d = datetime.strptime(last, "%Y-%m-%d").date()
            days = (today - d).days
            if days >= stale_days:
                sig.append(f"마지막 거래일 {last} ({days}일째 거래 기록 없음 — 거래정지 가능성)")
                kind = kind or "halt"
        except Exception:
            pass
    try:
        pct = float(str(item.get("fluctuationsRatio")).replace(",", ""))
        if abs(pct) > DL_PCT_LIMIT:
            sig.append(f"하루 등락률 {pct:+.1f}% (가격제한폭 ±30% 초과 — 정리매매 또는 신규상장일 가능성)")
            kind = "delist" if kind in (None, "delist") else kind
    except Exception:
        pass
    seen, out = set(), []
    for s in sig:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return kind, out[:6], last


def _dl_eval(rules, mk, price, cap):
    """기준 목록에 비춰 미달한 항목을 모은다(원본 _delist_scan_rows 와 같은 방식)."""
    out = []
    for r in rules:
        if not r.get("on", True):
            continue
        rmk = (r.get("market") or "ALL").upper()
        if rmk != "ALL" and rmk != mk:
            continue
        metric = r.get("metric")
        if metric == "market_cap":
            if not cap:
                continue
            cur = cap
        else:
            if not price:
                continue
            cur = price
        if cur < float(r.get("value") or 0):
            out.append({"key": r.get("key"), "label": r.get("label"), "sev": "danger" if int(r.get("recover_days") or 0) > 0 else "warn",
                        "cur": cur, "value": float(r.get("value") or 0), "unit": r.get("unit") or ""})
    return out


def _dl_get_json(url, params, tries=3):
    for i in range(tries):
        try:
            r = _http().get(url, params=params, headers=C.NAVER_M_HEADERS, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(0.4 * (i + 1))
    return None


def _dl_fetch_market(mk, job):
    """한 시장의 전 종목 시세 목록. 반환 (종목 리스트, 서버가 알려 준 전체 수) — 못 받으면 (None, 0)."""
    url = f"https://m.stock.naver.com/api/stocks/marketValue/{mk}"
    first = _dl_get_json(url, {"page": 1, "pageSize": 60})
    if not first:
        return None, 0
    total = _dl_int(first.get("totalCount"))
    ps = max(1, _dl_int(first.get("pageSize"), 60))
    stocks = list(first.get("stocks") or [])
    pages = min(80, (total + ps - 1) // ps) if total else 1
    job["pages_total"] += pages
    job["pages_done"] += 1

    def one(p):
        if job["cancel"]:
            return []
        j = _dl_get_json(url, {"page": p, "pageSize": 60})
        job["pages_done"] += 1
        return (j or {}).get("stocks") or []
    if pages > 1:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for part in ex.map(one, range(2, pages + 1)):
                stocks += part
    return stocks, total


def _dl_screen_run():
    job = _DL_SCAN
    try:
        _ensure_v135_tables()
        crit = dl_criteria()
        stale = int(setting_get("delist_stale_days") or 10)
        job.update(phase="시세 목록 받는 중", total=0, done=0, ok=0, flagged=0, danger=0, warn=0, pages_total=0, pages_done=0, error="")
        res = {}

        def getm(mk):
            try:
                res[mk] = _dl_fetch_market(mk, job)
            except Exception as e:
                print(f"[투자주의] {mk} 목록 오류: {e}")
                res[mk] = (None, 0)
        ths = [threading.Thread(target=getm, args=(mk,), daemon=True) for mk in ("KOSPI", "KOSDAQ")]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        if job["cancel"]:
            job["error"] = "중단했어요(받아 온 결과는 반영하지 않았어요)."
            return
        stocks, expected = [], 0
        for mk in ("KOSPI", "KOSDAQ"):
            lst, tot = res.get(mk) or (None, 0)
            expected += tot
            for s in (lst or []):
                s["__mk"] = mk
                stocks.append(s)
        if not stocks:
            job["error"] = "네이버에서 시세 목록을 받지 못했어요. 잠시 뒤 다시 실행해 주세요."
            return
        complete = (not expected) or len(stocks) >= expected * 0.97
        job.update(phase="기준 평가", total=len(stocks), ok=len(stocks), done=len(stocks))
        today = _now_kst().date()
        flagged, bulk = {}, {}
        for s in stocks:
            if s.get("stockEndType") not in (None, "stock"):
                continue
            tk = str(s.get("itemCode") or "").strip().upper()
            if not re.fullmatch(r"[0-9A-Z]{6}", tk):
                continue
            mk = s["__mk"]
            price, cap = _dl_int(s.get("closePrice")), _dl_int(s.get("marketValue"))
            pct = _dl_flt(s.get("fluctuationsRatio"))
            kind, sig, last = _dl_signals(s, stale, today)
            bulk[tk] = (price, cap, pct, last)
            matched = _dl_eval(crit["rules"], mk, price, cap)
            if not matched and not kind:
                continue
            risk = "danger" if (kind in ("halt", "delist") or any(m["sev"] == "danger" for m in matched)) else "warn"
            flagged[tk] = {"name": s.get("stockName") or "", "market": mk, "kind": kind or "screen", "signals": sig, "price": price, "cap": cap,
                           "pct": pct, "last": last, "matched": matched, "risk": risk}
        job.update(phase="저장", flagged=len(flagged), danger=sum(1 for v in flagged.values() if v["risk"] == "danger"),
                   warn=sum(1 for v in flagged.values() if v["risk"] == "warn"))
        now = int(time.time())
        conn = _history_conn()
        try:
            cur = conn.cursor()
            ph = (lambda q: q.replace("?", "%s")) if C._USE_PG else (lambda q: q)
            cur.execute("SELECT ticker, kind FROM delist_watch")
            existing = {r[0]: r[1] for r in cur.fetchall()}
            for tk, v in flagged.items():
                cur.execute(ph("""INSERT INTO delist_watch(ticker,name,market,kind,signals,price,last_trade,first_seen,last_seen,active,cap,pct,matched,risk)
                        VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?)
                        ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, market=excluded.market, kind=excluded.kind,
                          signals=excluded.signals, price=excluded.price, last_trade=excluded.last_trade, last_seen=excluded.last_seen,
                          active=1, cap=excluded.cap, pct=excluded.pct, matched=excluded.matched, risk=excluded.risk"""),
                            (tk, v["name"], v["market"], v["kind"], json.dumps(v["signals"], ensure_ascii=False), v["price"], v["last"], now, now,
                             v["cap"], v["pct"], json.dumps(v["matched"], ensure_ascii=False), v["risk"]))
            today_s = _dl_today()
            cur.execute("UPDATE delist_watch SET ai_verdict='', ai_basis='', ai_source='', ai_date='', ai_at=0, ai_mode='' WHERE ai_mode IN ('manual','auto')")   # AI 검증 기능을 없앴으므로 예전 AI 결과는 정리
            for tk, v in flagged.items():
                lb, bs = _dl_status_label(v["signals"])
                if lb:
                    cur.execute(ph("UPDATE delist_watch SET ai_verdict=?, ai_basis=?, ai_source=?, ai_date=?, ai_at=?, ai_mode='scan' WHERE ticker=?"),
                                (lb, bs, DL_STATUS_SOURCE, today_s, now, tk))
                else:
                    cur.execute(ph("UPDATE delist_watch SET ai_verdict='', ai_basis='', ai_source='', ai_date='', ai_at=0, ai_mode='' WHERE ticker=? AND ai_mode='scan'"), (tk,))
            if complete:
                for tk, kd in existing.items():
                    if tk in flagged:
                        continue
                    if kd == "manual":
                        b = bulk.get(tk)
                        if b:
                            cur.execute(ph("UPDATE delist_watch SET price=?, cap=?, pct=?, last_trade=?, last_seen=? WHERE ticker=?"), (b[0], b[1], b[2], b[3], now, tk))
                        continue
                    cur.execute(ph("UPDATE delist_watch SET active=0, risk='', matched='[]', signals=?, last_seen=? WHERE ticker=?"),
                                (json.dumps(["최근 스크리닝에서는 해당 없음"], ensure_ascii=False), now, tk))
                # 거래가 재개되어 더는 거래정지·관리종목 표시가 없는 종목은 공개 기록도 함께 내린다(상장폐지·정리매매는 목록에서 사라져도 기록을 남긴다)
                cur.execute("UPDATE delist_watch SET ai_verdict='', ai_basis='', ai_source='', ai_date='', ai_at=0, ai_mode='' WHERE active=0 AND ai_mode='scan' AND ai_verdict IN ('거래정지','관리종목')")
                cur.execute("DELETE FROM delist_watch WHERE active=0 AND ai_verdict='' AND admin_state=''")
            conn.commit()
        finally:
            conn.close()
        if complete:
            try:
                _dl_save_snapshot()
            except Exception as e:
                print(f"[투자주의] 자동 기준 저장 실패(무시): {e}")
        if not complete:
            job["error"] = f"시세 목록을 일부만 받았어요({len(stocks)}/{expected}). 이번에는 목록에서 내리는 정리를 하지 않았어요 — 잠시 뒤 다시 실행해 보세요."
    except Exception as e:
        job["error"] = f"스크리닝 중 오류: {type(e).__name__}: {str(e)[:120]}"
        print(f"[관리자메뉴] 스크리닝 오류: {e}")
    finally:
        job["running"] = False
        job["phase"] = "끝" if not job["error"] else job["phase"]
        job["finished"] = int(time.time())
        try:
            setting_set("delist_last_scan", json.dumps({k: job[k] for k in ("total", "ok", "flagged", "danger", "warn", "finished", "error")}, ensure_ascii=False))
        except Exception:
            pass


# [v150] 네이버가 직접 알려 주는 거래상태 표시(거래정지·관리종목·상장폐지·정리매매)가 있으면 그 종목을 '공개 목록'에 자동으로 올린다.
# 마지막 거래일이 오래됐다·하루 등락률이 크다 같은 추정 신호와 시가총액·주가 기준 미달은 공개하지 않는다(후보·블로그 '투자주의'에만 쓴다).
_DL_STATUS_MAP = (
    ("상장폐지확정", ("상장폐지",)),
    ("정리매매", ("정리매매",)),
    ("거래정지", ("거래정지", "매매정지")),
    ("관리종목", ("관리종목",)),
)
DL_STATUS_SOURCE = "네이버 증권 거래상태"


def _dl_status_label(sig):
    """자동 신호 문장들에서 네이버가 직접 알려 준 상태 하나를 뽑는다. 반환 (상태이름, 근거문장) 또는 ('', '')."""
    for s in sig or []:
        s = str(s)
        if not s.startswith("네이버 "):
            continue
        compact = s.replace(" ", "")
        for label, keys in _DL_STATUS_MAP:
            if any(k in compact for k in keys):
                return label, s[len("네이버 "):][:200]
    return "", ""


# ── 행 · 요약 · 스냅샷 ──
DL_COLS = ("ticker", "name", "market", "kind", "signals", "price", "last_trade", "first_seen", "last_seen", "active",
           "ai_verdict", "ai_basis", "ai_source", "ai_date", "ai_at", "ai_mode", "admin_state", "admin_label", "admin_note", "admin_at",
           "cap", "pct", "matched", "risk")


def _dl_row_out(r):
    for k in ("signals", "matched"):
        try:
            v = json.loads(r.get(k) or "[]")
        except Exception:
            v = []
        r[k] = v if isinstance(v, list) else []
    return r


def _dl_rows(only_active=False):
    where = "active=1" if only_active else "(active=1 OR admin_state<>'' OR ai_verdict<>'')"
    rows = [_dl_row_out(r) for r in _dbrows(
        f"SELECT {','.join(DL_COLS)} FROM delist_watch WHERE {where} "
        "ORDER BY (risk='danger') DESC, (kind IN ('halt','delist')) DESC, cap ASC, ticker LIMIT 1800", DL_COLS)]
    return rows


def _dl_summary(rows):
    act = [r for r in rows if r["active"]]
    return {"total": len(act), "danger": sum(1 for r in act if r["risk"] == "danger"), "warn": sum(1 for r in act if r["risk"] == "warn"),
            "status": sum(1 for r in act if r["kind"] in ("halt", "delist")),
            "public": sum(1 for r in rows if _is_public(r))}


def _pub_label(r):
    """[v150] 공개 목록에 올라가는 상태 이름 — ① 스크리닝이 네이버 거래상태에서 읽어 기록한 판정(ai_mode='scan') ② 예전에 관리자가 확정해 둔 것. 제외한 종목은 없음.
    거래정지·관리종목은 지금도 자동 신호가 있을 때만(풀렸으면 내려감), 상장폐지확정·정리매매는 목록에서 사라져도 유지."""
    if r.get("admin_state") == "excluded":
        return ""
    v = r.get("ai_verdict") or ""
    if v in DL_PUBLIC_LABELS and (r.get("ai_source") or "").strip() and r.get("ai_mode") == "scan":
        if v in ("거래정지", "관리종목") and not r.get("active"):
            return ""
        return v
    if r.get("admin_state") == "confirmed" and r.get("admin_label") in DL_PUBLIC_LABELS:
        return r["admin_label"]
    return ""


def _is_public(r):
    return bool(_pub_label(r))


def _dl_today():
    return _now_kst().strftime("%Y-%m-%d")


def _dl_snap_items(rows):
    return [{"ticker": r["ticker"], "name": r["name"], "market": r["market"], "risk": r["risk"] or ("danger" if r["kind"] in ("halt", "delist") else "warn"),
             "price": r["price"], "cap": r["cap"], "pct": r["pct"], "kind": r["kind"],
             "labels": [m.get("label") for m in r["matched"]], "ai": r["ai_verdict"]} for r in rows if r["active"]]


def _dl_save_snapshot(rows=None):
    """[v149] 스크리닝이 끝날 때 자동으로 오늘 결과를 저장한다 — 다음 스크리닝 때 '신규 진입·졸업'을 비교하는 기준이 된다(버튼 없음)."""
    rows = rows if rows is not None else _dl_rows(True)
    if not rows:
        return None
    today = _dl_today()
    sm = _dl_summary(rows)
    df = _dl_diff(rows)
    items = _dl_snap_items(rows)
    _dbx("""INSERT INTO delist_snaps(snap_date,total,danger,warn,items_json,summary_json,added_json,graduated_json,prev_date,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(snap_date) DO UPDATE SET total=excluded.total, danger=excluded.danger, warn=excluded.warn, items_json=excluded.items_json,
              summary_json=excluded.summary_json, added_json=excluded.added_json, graduated_json=excluded.graduated_json,
              prev_date=excluded.prev_date, updated_at=excluded.updated_at""",
         (today, sm["total"], sm["danger"], sm["warn"], json.dumps(items, ensure_ascii=False), json.dumps(sm, ensure_ascii=False),
          json.dumps(df["added"], ensure_ascii=False), json.dumps(df["graduated"], ensure_ascii=False), df["prev_date"], int(time.time())))
    return {"date": today, "n": len(items)}


def _dl_prev_snap(today):
    try:
        rows = _dbx("SELECT snap_date, items_json FROM delist_snaps WHERE snap_date < ? ORDER BY snap_date DESC LIMIT 1", (today,), fetch=True)
        if rows:
            return rows[0][0], {it["ticker"]: it for it in json.loads(rows[0][1] or "[]")}
    except Exception:
        pass
    return "", {}


def _dl_diff(rows):
    prev_date, prev = _dl_prev_snap(_dl_today())
    cur = {r["ticker"]: r for r in rows if r["active"]}
    added = [{"ticker": t, "name": r["name"], "market": r["market"], "risk": r["risk"], "price": r["price"], "cap": r["cap"]} for t, r in cur.items() if t not in prev]
    grad = [{"ticker": t, "name": it.get("name") or t, "market": it.get("market") or "", "risk": it.get("risk") or ""} for t, it in prev.items() if t not in cur]
    added.sort(key=lambda x: (x["risk"] != "danger", x.get("cap") or 9e9))
    grad.sort(key=lambda x: (x["risk"] != "danger", x["name"]))
    return {"has_baseline": bool(prev), "prev_date": prev_date, "added": added[:300], "graduated": grad[:300]}


def _dl_items_text(rows):
    lines = []
    for r in rows:
        sig = "; ".join(r["signals"]) if isinstance(r["signals"], list) else str(r["signals"])
        mt = ", ".join(m.get("label") or "" for m in (r.get("matched") or [])) or "-"
        cap = f"시총 {int(r['cap']):,}억" if r.get("cap") else "시총 -"
        lines.append(f"{r['ticker']} | {r['name']} | {r['market']} | {cap} | 현재가 {int(r['price'] or 0):,}원 | 해당 기준: {mt} | 자동신호: {sig or '-'} | 마지막 거래일 {r['last_trade'] or '-'}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 관리자 API
# ══════════════════════════════════════════════════════════════
def _advice_get():
    try:
        d = json.loads(setting_get("delist_advice", "") or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _is_gw():
    """회원 화면(/mapi/ 문)을 거쳐 온 요청인가."""
    return bool(request.environ.get("mini.gateway"))


_AI_BLANK = {"ai_verdict": "", "ai_basis": "", "ai_source": "", "ai_date": "", "ai_at": "", "ai_mode": ""}


def _gw_cand_rows(rows):
    """회원 화면용 후보 행 정리 — ① 관리자가 '공개에서 제외'한 종목과 자동 신호가 없는 행을 빼고, ② AI 의견·관리자 표시/메모는 지운다(후보 기능은 자동 신호만).
    돌려주는 값: (행 목록, 제외된 종목코드 집합)."""
    excl = {r["ticker"] for r in rows if r["admin_state"] == "excluded"}
    out = []
    for r in rows:
        if r["ticker"] in excl or not r["active"]:
            continue
        r = dict(r)
        r.update(_AI_BLANK)
        r["admin_state"] = r["admin_label"] = r["admin_note"] = ""
        r["admin_at"] = ""
        out.append(r)
    return out, excl


def _excluded_set():
    try:
        return {r[0] for r in (_dbx("SELECT ticker FROM delist_watch WHERE admin_state='excluded'", fetch=True) or [])}
    except Exception:
        return set()


@bp.route("/admin/api/delist/list")
def admin_api_delist_list():
    deny = _admin_deny()
    if deny:
        return deny
    rows = []
    diff = {"has_baseline": False, "prev_date": "", "added": [], "graduated": []}
    if _ensure_v135_tables():
        rows = _dl_rows()
        diff = _dl_diff(rows)
    try:
        last = json.loads(setting_get("delist_last_scan", "") or "{}")
    except Exception:
        last = {}
    for r in rows:
        r["first_seen"] = _kst_str(r["first_seen"]) if r["first_seen"] else ""
        r["last_seen"] = _kst_str(r["last_seen"]) if r["last_seen"] else ""
        r["ai_at"] = _kst_str(r["ai_at"]) if r["ai_at"] else ""
        r["admin_at"] = _kst_str(r["admin_at"]) if r["admin_at"] else ""
    crit = dl_criteria()
    if last.get("finished"):
        last["finished_txt"] = _kst_str(last["finished"])
    adv = _advice_get()
    if _is_gw():
        # [v148] 회원 화면(gateway)에는 '후보'를 열어 준 등급에게만, 그것도 AI 의견·내 결정(제외 등)을 뺀 자동 신호 부분만 내려간다.
        if not C.feature_ok("delist", "candidates"):
            return _admin_json({"error": "🔒 ‘후보 목록’ 기능은 아직 열려 있지 않아요.", "feature": "candidates", "need": C.feature_need_text("delist", "candidates")}, 403)
        rows, excl = _gw_cand_rows(rows)
        diff = {"has_baseline": diff["has_baseline"], "prev_date": diff["prev_date"],
                "added": [x for x in diff["added"] if x["ticker"] not in excl], "graduated": [x for x in diff["graduated"] if x["ticker"] not in excl]}
        if not C.feature_ok("delist", "advice"):
            adv = {}
        return _admin_json({"rows": rows, "summary": _dl_summary(rows), "last_scan": {"finished_txt": last.get("finished_txt", ""), "total": last.get("total", 0)},
                            "diff": diff, "criteria": crit, "advice": adv, "kinds": _KIND_LABEL, "today": _dl_today()})
    for r in rows:
        r["pub"] = _pub_label(r)
    return _admin_json({"rows": rows, "summary": _dl_summary(rows), "last_scan": last, "scan": {k: _DL_SCAN[k] for k in _DL_SCAN if k != "cancel"},
                        "diff": diff, "criteria": crit, "advice": adv, "kinds": _KIND_LABEL,
                        "public_labels": list(DL_PUBLIC_LABELS), "today": _dl_today()})


@bp.route("/admin/api/delist/scan", methods=["POST"])
def admin_api_delist_scan():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if _DL_SCAN["running"]:
        return _admin_json({"error": "이미 스크리닝 중이에요."}, 409)
    if not _ensure_v135_tables():
        return _admin_json({"error": "저장소를 준비하지 못했어요."}, 500)
    _DL_SCAN.update(running=True, cancel=False, started=int(time.time()), error="", phase="준비")
    threading.Thread(target=_dl_screen_run, daemon=True).start()
    _alog("delist_scan", "screen")
    return _admin_json({"ok": True})


@bp.route("/admin/api/delist/scan-cancel", methods=["POST"])
def admin_api_delist_scan_cancel():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    _DL_SCAN["cancel"] = True
    return _admin_json({"ok": True})


@bp.route("/admin/api/delist/scan-status")
def admin_api_delist_scan_status():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json({k: _DL_SCAN[k] for k in _DL_SCAN if k != "cancel"})


@bp.route("/admin/api/delist/criteria", methods=["GET", "POST"])
def admin_api_delist_criteria():
    deny = _admin_deny(write=(request.method == "POST"))
    if deny:
        return deny
    if request.method == "POST":
        c = clean_criteria(_json_body().get("criteria"))
        if not c:
            return _admin_json({"error": "기준 형식이 올바르지 않아요(규칙이 하나도 없거나 값이 이상해요)."}, 400)
        c["updated_at"] = c.get("updated_at") or _dl_today()
        setting_set("delist_criteria", json.dumps(c, ensure_ascii=False))
        _alog("delist_criteria", f"rules={len(c['rules'])}")
    return _admin_json({"criteria": dl_criteria()})


@bp.route("/admin/api/delist/criteria-prompt", methods=["POST"])
def admin_api_delist_criteria_prompt():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    cur = _json_body().get("criteria")
    cur = clean_criteria(cur) or dl_criteria()
    prompt = (
        "당신은 한국 자본시장(코스피·코스닥) 상장폐지 규정 전문가입니다.\n"
        "아래는 현재 앱에 저장된 '상장폐지 위험 스크리닝 기준'(JSON)입니다. 한국거래소(KRX)·금융위원회의\n"
        "가장 최신 상장폐지/관리종목 지정 규정(시가총액·주가(동전주) 요건, 연속 거래일 요건, 액면병합 우회 방지,\n"
        "향후 상향 예정 수치 등)에 비추어 각 규칙의 수치·설명이 정확한지 점검하고, 필요하면 수정하세요.\n"
        "규칙을 추가/삭제해도 됩니다. 확인되지 않은 내용은 지어내지 말고 기존 값을 유지하세요.\n\n"
        "반드시 아래 JSON 스키마와 동일한 형태로만 답하세요(코드블록·설명 문장 금지, 순수 JSON):\n"
        '{"updated_at":"YYYY-MM-DD","source_note":"근거 요약","rules":['
        '{"key":"영문키","on":true,"market":"KOSPI|KOSDAQ|ALL","metric":"market_cap|price",'
        '"op":"lt","value":숫자,"unit":"억원|원","warn_days":30,"grace_days":90,"recover_days":45,'
        '"label":"짧은 이름","desc":"어디에 해당하기에 주의가 필요한지 상세 설명(연속 거래일 요건·회복 요건·우회 방지 포함)"}]}\n\n'
        "market_cap 규칙의 value 단위는 억원, price 규칙의 value 단위는 원입니다.\n"
        "실제 관리종목·상장폐지 요건에 해당하는 규칙은 recover_days>0 으로, 단순 경계(주의)용 규칙은 grace_days=0, recover_days=0 으로 두세요.\n\n"
        "현재 저장된 기준:\n" + json.dumps(cur, ensure_ascii=False, indent=2))
    return _admin_json({"prompt": prompt})


@bp.route("/admin/api/delist/criteria-parse", methods=["POST"])
def admin_api_delist_criteria_parse():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    txt = str(_json_body().get("text") or "").strip()[:30000]
    m = re.search(r"```(?:json)?\s*(.+?)```", txt, re.S)
    if m:
        txt = m.group(1).strip()
    try:
        obj = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
    except Exception:
        return _admin_json({"error": "AI 답변을 JSON으로 읽지 못했어요. 답변 전체가 복사됐는지 확인하세요.", "rules": 0})
    c = clean_criteria(obj)
    if not c:
        return _admin_json({"error": "AI 답변에 rules 배열이 없거나 값이 이상해요.", "rules": 0})
    return _admin_json({"proposed": c, "rules": len(c["rules"])})


@bp.route("/admin/api/delist/mark", methods=["POST"])
def admin_api_delist_mark():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    tks = [normalize_ticker(t) for t in (d.get("tickers") or [])[:900]]
    tks = [t for t in tks if t]
    state = str(d.get("state", ""))
    label = str(d.get("label", "")).strip()
    note = re.sub(r"[<>]", "", str(d.get("note", "")))[:120]
    if not tks or state not in ("excluded", ""):
        return _admin_json({"error": "요청이 올바르지 않아요."}, 400)
    now = int(time.time())
    conn = _history_conn()
    try:
        cur = conn.cursor()
        ph = (lambda q: q.replace("?", "%s")) if C._USE_PG else (lambda q: q)
        for t in tks:
            cur.execute(ph("UPDATE delist_watch SET admin_state=?, admin_label=?, admin_note=?, admin_at=? WHERE ticker=?"),
                        (state, "", note, now if state else 0, t))
        conn.commit()
    finally:
        conn.close()
    _alog("delist_mark", f"{state or 'clear'} {label} n={len(tks)}")
    return _admin_json({"ok": True, "n": len(tks)})


@bp.route("/admin/api/delist/add", methods=["POST"])
def admin_api_delist_add():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    t = normalize_ticker(str(_json_body().get("ticker", "")))
    nm, mk = get_ticker_info(t) if t else (None, None)
    if not t or not nm:
        return _admin_json({"error": "종목을 찾지 못했어요(종목코드 6자리 확인)."}, 400)
    now = int(time.time())
    _dbx("""INSERT INTO delist_watch(ticker,name,market,kind,signals,first_seen,last_seen,active,risk) VALUES(?,?,?,?,?,?,?,1,'warn')
            ON CONFLICT(ticker) DO UPDATE SET active=1, last_seen=excluded.last_seen""",
         (t, nm, mk or "", "manual", json.dumps(["관리자가 직접 추가"], ensure_ascii=False), now, now))
    _alog("delist_add", t)
    return _admin_json({"ok": True, "ticker": t, "name": nm})


@bp.route("/admin/api/delist/diag/<ticker>")
def admin_api_delist_diag(ticker):
    """네이버가 실제로 보내 주는 기본정보를 그대로 보여 준다(자동 신호가 맞는지 확인용)."""
    deny = _admin_deny()
    if deny:
        return deny
    t = normalize_ticker(ticker)
    basic = _naver_mobile_basic(t) if t else None
    if not basic:
        return _admin_json({"error": "네이버에서 받지 못했어요."}, 502)
    txt = json.dumps(basic, ensure_ascii=False, indent=1)
    return _admin_json({"ticker": t, "raw": txt[:4000]})


@bp.route("/admin/api/delist/advice-prompt", methods=["POST"])
def admin_api_delist_advice_prompt():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    rows = _dl_rows(True)
    if not rows:
        return _admin_json({"error": "먼저 스크리닝을 실행하세요."}, 400)
    sm = _dl_summary(rows)
    summary = (f"전체 {sm['total']}종목 — 위험 {sm['danger']}종목(기준 미달·거래상태 이상 신호), 경계 {sm['warn']}종목(기준 근접), 거래상태 이상 신호 {sm['status']}종목, "
               f"공개 목록 {sm['public']}종목(네이버 거래상태 기준). 적용 기준: " + " / ".join(r["label"] for r in dl_criteria()["rules"] if r.get("on", True)))
    top = [r for r in rows if r["risk"] == "danger"][:25] + [r for r in rows if r["risk"] == "warn"][:10]
    body = prompt_get("delist_advice")
    return _admin_json({"prompt": _prompt_fill(body, today=_dl_today(), summary=summary, items=_dl_items_text(top))})


@bp.route("/admin/api/delist/advice-save", methods=["POST"])
def admin_api_delist_advice_save():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    t = re.sub(r"<[^>]*>", "", str(_json_body().get("text") or "")).strip()[:20000]
    setting_set("delist_advice", json.dumps({"text": t, "date": _dl_today(), "at": int(time.time())}, ensure_ascii=False) if t else "")
    _alog("delist_advice", f"len={len(t)}")
    return _admin_json({"ok": True, "len": len(t), "date": _dl_today()})


# ── 블로그 글 ──
BLOG_SECTIONS = [("stats", "요약통계"), ("danger", "위험종목표"), ("warn", "경계종목표"), ("diff", "신규진입·졸업"), ("pub", "공개종목"), ("advice", "AI조언"), ("rules", "스크리닝기준")]


def _cap_txt(c):
    if not c:
        return "-"
    c = int(c)
    return f"{c / 10000:,.1f}조" if c >= 10000 else f"{c:,}억"


def _tbl(head, rows, widths):
    th = "".join(f'<td width="{w}%" style="padding:7px 5px;background-color:#f1f5f9;border:1px solid #e2e8f0;font-size:12px;font-weight:900;color:#334155;">{h}</td>' for h, w in zip(head, widths))
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f'<td style="padding:6px 5px;border:1px solid #e2e8f0;font-size:12.5px;color:#111827;vertical-align:top;">{c}</td>' for c in r) + "</tr>"
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:8px 0;{B.FONT}"><tr>{th}</tr>{body}</table>'


def build_blog(inc=None, title="", n=40):
    inc = inc or {k: True for k, _ in BLOG_SECTIONS}
    rows = _dl_rows(True)
    rows = [r for r in rows if r["admin_state"] != "excluded"]
    sm = _dl_summary(rows)
    today = _dl_today()
    crit = dl_criteria()
    danger = [r for r in rows if r["risk"] == "danger"]
    warn = [r for r in rows if r["risk"] == "warn"]
    auto_title = f"⚠️ 투자주의 종목 점검 {today} — 상장유지 기준 미달·거래상태 이상 신호 {sm['danger']}종목 (확정 아님, 참고용)"
    title = title or auto_title
    names = [r["name"] for r in danger[:12]]
    tags, tag_html = B.hashtags(names, today, extra=["투자주의", "상장폐지위험", "관리종목", "동전주", "시가총액", "주식리스크"])
    h = [B.seo_box(auto_title, "시가총액·주가 기준에 미달했거나 거래 상태에 이상 신호가 있는 종목을 공개 데이터로 자동 계산해 정리했어요(확정이 아닌 참고용).",
                   ["투자주의", "상장폐지", "관리종목", "동전주", "시가총액미달"]),
         B.head_box(f"⚠ INVESTMENT CAUTION · {today}", f'투자주의 종목 점검 <span style="color:{B.GOLD};">{sm["total"]}종목</span>', "공개 데이터 기준 자동 계산 · 확정이 아닌 참고용",
                    warn_html="본 목록은 상장폐지·관리종목 지정·거래정지를 단정하거나 예측하는 것이 아니며, 계산상 기준에 미달하거나 유의 신호가 보인 종목을 모아 둔 참고 자료입니다.")]
    if inc.get("stats"):
        def cell(label, val, c):
            return (f'<td align="center" style="padding:10px 4px;background-color:#f8faff;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;margin-bottom:3px;">{label}</div>'
                    f'<div style="font-size:19px;font-weight:900;color:{c};">{val}</div></td>')
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:14px 0;' + B.FONT + '"><tr>'
                 + cell("전체", f"{sm['total']}개", "#1e293b") + cell("&#128308; 위험", f"{sm['danger']}개", "#dc2626") + cell("&#128993; 경계", f"{sm['warn']}개", "#d97706")
                 + cell("거래상태 신호", f"{sm['status']}개", "#7c3aed") + cell("&#127760; 공개 중", f"{sm['public']}개", "#0d9488") + "</tr></table>")
        h.append('<p style="font-size:12px;color:#6b7280;line-height:1.8;margin:4px 0 10px;">종가·시가총액이 기준에 미달한 상태가 <b>연속 30거래일</b> 이어지면 관리종목으로 지정될 수 있고, 지정 후 <b>90거래일 안에 연속 45거래일 이상</b> 회복하지 못하면 상장폐지 절차로 이어질 수 있습니다. '
                 '아래는 <b>현재 시점의 스냅샷</b>이라 실제 지정·폐지 여부와 다를 수 있습니다.</p>')

    def stock_rows(lst, limit):
        out = []
        for r in lst[:limit]:
            why = ", ".join(E(m.get("label") or "") for m in r["matched"]) or "&#8212;"
            sig = ("<br>" + E(r["signals"][0])) if r["signals"] and r["kind"] in ("halt", "delist") else ""
            pl = _pub_label(r)
            ai = f'<br><span style="color:#0d9488;font-weight:800;">네이버 거래상태: {E(pl)}</span>' if pl else ""
            out.append([f'<b>{E(r["name"])}</b><br><span style="color:#94a3b8;font-size:11px;">{E(r["ticker"])} · {E(r["market"])}</span>', _cap_txt(r["cap"]),
                        f'{int(r["price"] or 0):,}원', why + sig + ai])
        return out
    if inc.get("danger") and danger:
        h.append(B.side_title(f"&#128308; 위험 구간 종목 (기준 미달 · 거래상태 이상 신호) {len(danger)}개 중 상위 {min(n, len(danger))}개", "#dc2626"))
        h.append(_tbl(["종목", "시총", "현재가", "해당 기준 · 신호"], stock_rows(danger, n), [26, 12, 14, 48]))
    if inc.get("warn") and warn:
        h.append(B.side_title(f"&#128993; 경계 종목 (기준 근접) {len(warn)}개 중 상위 {min(25, len(warn))}개", "#d97706"))
        h.append(_tbl(["종목", "시총", "현재가", "해당 기준"], stock_rows(warn, 25), [26, 12, 14, 48]))
    if inc.get("diff"):
        df = _dl_diff(rows)
        if df["has_baseline"]:
            ad = ", ".join(E(x["name"]) for x in df["added"][:20]) or "없음"
            gr = ", ".join(E(x["name"]) for x in df["graduated"][:20]) or "없음"
            h.append(B.side_title(f"&#127381; 직전 점검({E(df['prev_date'])}) 대비 변화", "#7c3aed"))
            h.append(f'<p style="font-size:13px;line-height:1.9;margin:4px 0;"><b style="color:#dc2626;">신규 진입 {len(df["added"])}개</b>: {ad}</p>'
                     f'<p style="font-size:13px;line-height:1.9;margin:4px 0;"><b style="color:#16a34a;">졸업(기준 벗어남) {len(df["graduated"])}개</b>: {gr}</p>')
    if inc.get("pub"):
        pubs = _public_rows()
        if pubs:
            cnt = {}
            for r in pubs:
                cnt[r["label"]] = cnt.get(r["label"], 0) + 1
            summ = " · ".join(f"{E(k)} {v}개" for k, v in sorted(cnt.items(), key=lambda x: -x[1]))
            h.append(B.side_title("&#127760; 네이버 거래상태에 표시된 종목", "#0d9488"))
            h.append(f'<p style="font-size:13px;line-height:1.9;margin:4px 0;">{len(pubs)}개 종목 — {summ}. 거래소 공시와 다를 수 있어 <b>KIND·DART 원문 확인이 꼭 필요</b>합니다.</p>')
            h.append(_tbl(["종목", "상태", "확인일"], [[f'<b>{E(r["name"])}</b> <span style="color:#94a3b8;font-size:11px;">{E(r["ticker"])} · {E(r["market"])}</span>', E(r["label"]), E(r["at"])] for r in pubs[:30]], [50, 26, 24]))
    if inc.get("advice"):
        adv = _advice_get()
        if adv.get("text"):
            h.append(B.side_title("&#128161; 투자 시 주의점 · 접근 방향 (AI 정리)", "#0d1b3e"))
            h.append(B.ai_to_html(adv["text"]))
    if inc.get("rules"):
        rr = [[E(r["label"]), ("실제 요건" if r["recover_days"] > 0 else "경계(주의)"), E(r["desc"])] for r in crit["rules"] if r.get("on", True)]
        h.append(B.side_title("&#9881; 스크리닝에 쓴 기준", "#64748b"))
        h.append(_tbl(["기준", "구분", "설명"], rr, [24, 12, 64]))
        h.append(f'<p style="font-size:11.5px;color:#9ca3af;">기준 갱신일 {E(crit["updated_at"])} · {E(crit["source_note"])} · 규정은 바뀔 수 있어요.</p>')
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": [], "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/delist/blog", methods=["POST"])
def admin_api_delist_blog():
    deny = _admin_deny()
    if deny:
        return deny
    d = _json_body()
    inc = d.get("inc")
    inc = {k: bool((inc or {}).get(k, False)) for k, _ in BLOG_SECTIONS} if isinstance(inc, dict) else None
    b = build_blog(inc, str(d.get("title") or "").strip()[:150])
    b.update({"name": "투자주의 " + _dl_today(), "ticker": "D" + _dl_today().replace("-", "")[2:], "dups": [], "dup_warn": ""})
    return _admin_json(b)


# ══════════════════════════════════════════════════════════════
# 공개 화면 — 네이버 거래상태에 표시된 종목만
# ══════════════════════════════════════════════════════════════
def _public_rows():
    """공개 목록 — 스크리닝이 네이버 거래상태에서 읽은 판정이 거래정지·관리종목·상장폐지확정·정리매매인 종목(제외한 것 빼고). 자동 신호·AI 근거 글은 내보내지 않는다."""
    rows = []
    if _ensure_v135_tables():
        cols = ("ticker", "name", "market", "active", "ai_verdict", "ai_source", "ai_mode", "ai_date", "ai_at", "admin_state", "admin_label", "admin_note", "admin_at")
        rows = _dbrows(f"SELECT {','.join(cols)} FROM delist_watch WHERE admin_state<>'excluded' AND (ai_verdict IN ('거래정지','관리종목','상장폐지확정','정리매매') OR admin_state='confirmed') "
                       "ORDER BY ticker LIMIT 2000", cols)
    out = []
    for r in rows:
        lb = _pub_label(r)
        if not lb:
            continue
        ts = int(r["ai_at"]) if (r["ai_verdict"] == lb and r["ai_at"]) else int(r["admin_at"] or 0)
        d = (r["ai_date"] or "") if r["ai_verdict"] == lb else ""
        if not d and ts:
            d = datetime.fromtimestamp(ts, _now_kst().tzinfo).strftime("%Y-%m-%d")
        out.append({"ticker": r["ticker"], "name": r["name"], "market": r["market"], "label": lb, "note": "", "at": d, "_ts": ts})
    out.sort(key=lambda x: (-x["_ts"], x["ticker"]))
    for x in out:
        x.pop("_ts", None)
    return out[:500]


@bp.route("/api/delist/public")
def api_delist_public():
    if not menu_visible("delist"):
        return "not found", 404
    resp = jsonify({"rows": _public_rows()})
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


@bp.route("/admin/api/delist/public-preview")
def api_delist_public_preview():
    """공개 종목 목록(공개 화면 /delist 와 같은 데이터). 회원 화면의 ‘거래정지·상폐 종목 목록’ 기능이 읽는다 — 공개 종목만 나가므로 후보 정보가 없다."""
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json({"rows": _public_rows()})


# ── [v148] 회원 화면용 읽기 전용 주소들 — 모두 '공개 종목(네이버 거래상태 기준)'에서만 값을 만든다(후보·AI 의견·제외 표시는 읽지 않음) ──
_TK_RE = re.compile(r"^[0-9A-Za-z]{6}$")


@bp.route("/admin/api/delist/stats")
def admin_api_delist_stats():
    """상태별 통계·이력 — 공개 종목 수, 상태별·시장별 수, 월별 수, 확인일별 이력."""
    deny = _admin_deny()
    if deny:
        return deny
    rows = _public_rows()
    by_label, by_market, by_month, by_date = {}, {}, {}, {}
    for r in rows:
        lb = r["label"] or "기타"
        by_label[lb] = by_label.get(lb, 0) + 1
        mk = r["market"] if r["market"] in ("KOSPI", "KOSDAQ") else "기타"
        by_market[mk] = by_market.get(mk, 0) + 1
        if r["at"]:
            by_month[r["at"][:7]] = by_month.get(r["at"][:7], 0) + 1
            by_date.setdefault(r["at"], []).append({"ticker": r["ticker"], "name": r["name"], "label": lb})
    dates = sorted(by_date, reverse=True)
    timeline = [{"date": d, "n": len(by_date[d]), "items": by_date[d][:20]} for d in dates[:30]]
    return _admin_json({"total": len(rows), "by_label": by_label, "by_market": by_market,
                        "by_month": [{"month": k, "n": by_month[k]} for k in sorted(by_month)[-12:]], "timeline": timeline,
                        "first_at": dates[-1] if dates else "", "last_at": dates[0] if dates else ""})


@bp.route("/admin/api/delist/detail/<ticker>")
def admin_api_delist_detail(ticker):
    """공개 목록에 있는 종목 하나의 근거·공시 요약 — 공개 목록에 없는 종목은 없는 것으로 답한다(후보를 확인하는 통로가 되지 않도록)."""
    deny = _admin_deny()
    if deny:
        return deny
    t = str(ticker or "").strip().upper()
    if not _TK_RE.match(t):
        return _admin_json({"error": "종목코드는 6자리예요."}, 400)
    if not _ensure_v135_tables():
        return _admin_json({"error": "저장소를 준비하지 못했어요."}, 500)
    cols = ("ticker", "name", "market", "active", "ai_verdict", "ai_basis", "ai_source", "ai_mode", "ai_date", "ai_at", "admin_state", "admin_label", "admin_at",
            "price", "cap", "pct", "last_trade", "last_seen", "matched", "signals")
    rs = _dbrows(f"SELECT {','.join(cols)} FROM delist_watch WHERE ticker=?", cols, (t,))
    r = _dl_row_out(rs[0]) if rs else None
    lb = _pub_label(r) if r else ""
    if not lb:
        return _admin_json({"error": "공개 목록에 없는 종목이에요."}, 404)
    rules = {x.get("key"): x for x in dl_criteria().get("rules", [])}
    matched = [{"label": str(m.get("label") or m.get("key") or "")[:60], "cur": m.get("cur"), "value": m.get("value"), "unit": str(m.get("unit") or "")[:8],
                "desc": str((rules.get(m.get("key")) or {}).get("desc") or "")[:600]} for m in r["matched"] if isinstance(m, dict)][:8]
    ai = r["ai_verdict"] == lb
    ts = int(r["ai_at"]) if (ai and r["ai_at"]) else int(r["admin_at"] or 0)
    at = (r["ai_date"] if ai and r["ai_date"] else (datetime.fromtimestamp(ts, _now_kst().tzinfo).strftime("%Y-%m-%d") if ts else ""))
    return _admin_json({"ticker": t, "name": r["name"], "market": r["market"], "label": lb, "note": "", "at": at,
                        "basis": str(r["ai_basis"] or "")[:200] if ai else "", "source": str(r["ai_source"] or "")[:80] if ai else "",
                        "price": r["price"], "cap": r["cap"], "pct": r["pct"], "last_trade": r["last_trade"],
                        "as_of": datetime.fromtimestamp(int(r["last_seen"]), _now_kst().tzinfo).strftime("%Y-%m-%d") if r["last_seen"] else "",
                        "matched": matched, "signals": [str(x)[:160] for x in r["signals"]][:6]})


@bp.route("/admin/api/delist/advice")
def admin_api_delist_advice():
    """저장해 둔 AI 조언 글(투자 시 주의점). 후보 종목 이름이 들어 있을 수 있어 기본은 관리자 전용 — 관리자가 글을 읽어 본 뒤 연다."""
    deny = _admin_deny()
    if deny:
        return deny
    a = _advice_get()
    return _admin_json({"text": str(a.get("text") or "")[:20000], "date": str(a.get("date") or "")})


@bp.route("/admin/api/delist/img-data")
def admin_api_delist_img_data():
    """종목 현황 이미지(내려받기용)를 그릴 재료 — 공개 목록과 상태별 수만."""
    deny = _admin_deny()
    if deny:
        return deny
    rows = _public_rows()
    by_label = {}
    for r in rows:
        by_label[r["label"] or "기타"] = by_label.get(r["label"] or "기타", 0) + 1
    return _admin_json({"rows": [{"ticker": r["ticker"], "name": r["name"], "market": r["market"], "label": r["label"], "at": r["at"]} for r in rows[:30]],
                        "total": len(rows), "by_label": by_label, "today": _dl_today()})


# ══════════════════════════════════════════════════════════════
# 관리자 화면 탭 (JS) — el, bt, api, apiJ, toast, $, poll 은 관리자 화면 도우미. {{ {% {# 금지
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var DL={rows:[],sum:{},diff:null,snaps:[],crit:null,advice:{},meta:null,view:null,sel:{},open:{},more:40,timer:null,critOpen:false,critEdit:null,
 f:{scope:'all',mkt:'',ai:'',st:'',q:'',sort:'default'}};
var DLCSS='.dlH{background:linear-gradient(135deg,#7f1d1d 0%,#b91c1c 55%,#dc2626 100%);color:#fff;border-radius:16px;padding:16px 18px;margin-bottom:10px}.dlH h3{margin:0;font-size:19px;font-weight:900}.dlH p{margin:5px 0 0;font-size:12.5px;color:#fecaca;line-height:1.65}'+
'.dlChips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.dlChip{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);border-radius:12px;padding:7px 13px;min-width:92px}.dlChip small{display:block;font-size:11px;color:#fecaca}.dlChip b{font-size:20px;font-weight:900}'+
'.dlNote{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:9px 13px;font-size:12px;color:#78350f;line-height:1.75;margin-bottom:10px}'+
'.dlBtns{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0}.dlB{border:1px solid #cbd5e1;background:#fff;color:#0f172a;border-radius:9px;padding:8px 13px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit}.dlB:hover{background:#f1f5f9}.dlB.p{background:#dc2626;border-color:#dc2626;color:#fff}.dlB.n{background:#0f172a;border-color:#0f172a;color:#fff}.dlB.t{background:#0d9488;border-color:#0d9488;color:#fff}.dlB:disabled{opacity:.5;cursor:default}.dlB.on{background:#0f172a;border-color:#0f172a;color:#fff}'+
'.dlBar{height:12px;background:#e2e8f0;border-radius:7px;overflow:hidden;margin:6px 0}.dlBar i{display:block;height:100%;background:linear-gradient(90deg,#dc2626,#f97316);width:0}'+
'.dlTbl{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px;background:#fff}.dlTbl th{position:sticky;top:0;background:#f1f5f9;color:#475569;font-weight:800;padding:8px 8px;text-align:left;border-bottom:2px solid #e2e8f0;white-space:nowrap}.dlTbl td{padding:8px 8px;border-bottom:1px solid #eef2f7;vertical-align:top}.dlTbl td.r,.dlTbl th.r{text-align:right;white-space:nowrap}'+
'.dlBd{display:inline-block;border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:800}.dlBd.d{background:#fee2e2;color:#991b1b}.dlBd.w{background:#fef3c7;color:#92400e}.dlBd.o{background:#e2e8f0;color:#475569}.dlBd.s{background:#ede9fe;color:#5b21b6}'+
'.dlCh{display:inline-block;border-radius:7px;background:#f1f5f9;border:1px solid #e2e8f0;padding:1px 7px;margin:1px 3px 1px 0;font-size:11.5px;color:#334155;cursor:help}.dlCh.d{background:#fff1f2;border-color:#fecdd3;color:#9f1239}'+
'.dlDt td{background:#f8fafc;font-size:12px;color:#475569;line-height:1.8}.dlSeg{display:flex;gap:2px}.up{color:#e11d48}.dn{color:#2563eb}'+
'.dlRule{display:grid;grid-template-columns:44px 1.5fr 92px 92px 92px 74px 74px;gap:6px;align-items:start;padding:7px 0;border-bottom:1px solid #eef2f7;font-size:12.5px}.dlRule input,.dlRule select,.dlRule textarea{width:100%;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:7px;padding:5px 7px;font-size:12.5px;font-family:inherit}'+
'.dlDiff{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:700px){.dlDiff{grid-template-columns:1fr}.dlRule{grid-template-columns:1fr 1fr}}.dlList{max-height:220px;overflow:auto;border:1px solid #e5e7eb;border-radius:10px;padding:6px 10px;background:#fff;font-size:12.5px;line-height:1.9}'+
'.dlAdv{white-space:pre-wrap;line-height:1.75;font-size:13px;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:10px 13px;max-height:360px;overflow:auto}'+
'.dlKpi{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.dlKpi div{border:1px solid #e2e8f0;border-radius:12px;padding:8px 14px;min-width:92px;background:#fff}.dlKpi small{display:block;color:#64748b;font-size:11.5px}.dlKpi b{font-size:20px;font-weight:900;color:#1a2744}'+
'.dlBk{display:grid;grid-template-columns:96px 1fr 44px;gap:8px;align-items:center;font-size:12.5px;margin:5px 0}.dlBk .t{height:12px;background:#e2e8f0;border-radius:7px;overflow:hidden}.dlBk .t i{display:block;height:100%;background:linear-gradient(90deg,#dc2626,#f97316)}.dlBk .n{text-align:right;font-weight:800}'+
'.dlKv{display:grid;grid-template-columns:110px 1fr;gap:4px 10px;font-size:13px;margin:8px 0}.dlKv b{color:#475569;font-weight:700}.dlTl{border-left:3px solid #fecaca;padding:2px 0 2px 10px;margin:8px 0}';
var DLCSS2='#dlS1,#dlS2,#dlS3,#dlS4{scroll-margin-top:88px}.dlSteps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;position:sticky;top:0;z-index:6;background:#f1f5f9;padding:8px 0;margin:0 0 6px}'+
'.dlStp{background:#fff;border:2px solid #e2e8f0;border-radius:12px;padding:9px 11px;cursor:pointer;display:flex;gap:9px;align-items:center}.dlStp:hover,.dlStp:focus{border-color:#fca5a5;outline:none}.dlStp.done{border-color:#86efac;background:#f0fdf4}.dlStp.off{opacity:.6}'+
'.dlStp .n{width:26px;height:26px;border-radius:50%;background:#dc2626;color:#fff;font-weight:900;display:flex;align-items:center;justify-content:center;flex:none;font-size:13px}.dlStp.done .n{background:#16a34a}.dlStp b{font-size:13.5px;display:block;color:#1a2744}.dlStp small{display:block;color:#64748b;font-size:11.5px}'+
'@media(max-width:640px){.dlSteps{grid-template-columns:repeat(3,1fr)}.dlStp{padding:8px 6px;gap:6px}.dlStp small{display:none}}.dlSH{display:flex;gap:10px;align-items:center;margin-bottom:8px}.dlSN{width:30px;height:30px;border-radius:50%;background:#dc2626;color:#fff;font-weight:900;display:flex;align-items:center;justify-content:center;flex:none}.dlSH b{font-size:15.5px;color:#1a2744}.dlSub{margin-top:14px;padding-top:10px;border-top:1px dashed #cbd5e1}';
function dlCss(){if(window.ImgKit&&ImgKit.addCss){ImgKit.addCss('dlCss',DLCSS);ImgKit.addCss('dlCss2',DLCSS2)}}
function dlN(v,d){if(v==null||v==='')return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d})}
function dlCap(c){if(!c)return '-';return c>=10000?(c/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조':dlN(c)+'억'}
function dlCard(title,sub){var c=el('div','c');if(title){var h=el('div');h.style.cssText='font-weight:900;font-size:14px;color:#1a2744';h.appendChild(document.createTextNode(title));if(sub){var s=el('span',null,'  '+sub);s.style.cssText='font-weight:400;font-size:11px;color:#94a3b8';h.appendChild(s)}c.appendChild(h)}return c}
function dlB(txt,cls,fn){var b=el('button','dlB'+(cls?' '+cls:''),txt);b.onclick=fn;return b}
function dlRiskOf(r){return r.risk||((r.kind==='halt'||r.kind==='delist')?'danger':'')}
function dlRule(key,label){var rs=(DL.crit&&DL.crit.rules)||[];for(var i=0;i<rs.length;i++){if((key&&rs[i].key===key)||(label&&rs[i].label===label))return rs[i]}return null}
/* ── 불러오기 ── */
function dlLoad(p){dlCss();DL.p=p;p.innerHTML='';
 if(MEMBER_MODE){dlMemDraw(p);return}
 if(!DL.meta)p.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/delist/list').then(function(d){if(cur!=='dl')return;dlApplyData(d);dlDraw()}).catch(function(){if(cur==='dl')p.appendChild(el('p','note bad','목록을 불러오지 못했어요. 다시 시도해 주세요.'))})}
function dlApplyData(d){DL.rows=d.rows||[];DL.sum=d.summary||{};DL.diff=d.diff;DL.snaps=d.snaps||[];DL.crit=d.criteria;DL.advice=d.advice||{};DL.meta=d;if(!DL.critEdit)DL.critEdit=JSON.parse(JSON.stringify(d.criteria))}
function dlReload(cb){api('/admin/api/delist/list').then(function(d){dlApplyData(d);if(cur==='dl'&&DL.p){dlDraw()}if(cb)cb()})}
/* ── 화면: ①스크리닝(자동 공개) → ②이미지 → ③블로그 (위에서 아래로 한 줄기) ── */
function dlStepCard(n,title,sub,id){var c=el('div','c');c.id=id;var h=el('div','dlSH');h.appendChild(el('span','dlSN',String(n)));var t=el('div');t.appendChild(el('b',null,title));if(sub)t.appendChild(el('div','m',sub));h.appendChild(t);c.appendChild(h);return c}
function dlStepper(sm,ls){var S=el('div','dlSteps');S.id='dlSteps';var has=sm.total>0;
 var items=[['1','스크리닝',ls.finished?((ls.finished_txt||'')+' · '+dlN(sm.total)+'개'):'아직 안 했어요',!!ls.finished,'dlS1'],
  ['2','이미지',has?'PNG 2장 만들기':'스크리닝 먼저',false,'dlS3'],
  ['3','블로그 글',has?'HTML 만들기':'스크리닝 먼저',false,'dlS4']];
 items.forEach(function(x){var b=el('div','dlStp'+(x[3]?' done':'')+(!has&&x[0]!=='1'?' off':''));b.setAttribute('role','button');b.tabIndex=0;
  b.appendChild(el('span','n',x[3]?'✓':x[0]));var t=el('div');t.appendChild(el('b',null,x[1]));t.appendChild(el('small',null,x[2]));b.appendChild(t);
  function go(){dlGo(x[4]);dlStepRun(x[4])}
  b.onclick=go;b.onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}};S.appendChild(b)});return S}
function dlDraw(){var p=DL.p;if(!p||cur!=='dl')return;var sy=window.pageYOffset||0;p.innerHTML='';var d=DL.meta,sm=DL.sum,ls=d.last_scan||{};
 var H=el('div','dlH');H.appendChild(el('h3',null,'🚫 거래정지·상장폐지 위험 종목'));
 H.appendChild(el('p',null,'스크리닝(①) 한 번으로 네이버 거래상태가 거래정지·상폐인 종목은 공개 목록에 자동으로 올라가고, 이어서 이미지(②)와 블로그 글(③)을 위에서 아래로 만들어요. 기준 미달 종목은 추정이라 공개하지 않아요.'));
 var ch=el('div','dlChips');function chip(l,v,fn){var c=el('div','dlChip');c.appendChild(el('small',null,l));c.appendChild(el('b',null,v));if(fn){c.style.cursor='pointer';c.onclick=fn}ch.appendChild(c)}
 function sc(v){return function(){DL.f.scope=v;dlToolDraw();dlTable();dlGo('dlS1')}}
 chip('전체',dlN(sm.total)+'개',sc('all'));chip('🔴 위험',dlN(sm.danger)+'개',sc('danger'));chip('🟡 경계',dlN(sm.warn)+'개',sc('warn'));chip('거래상태 신호',dlN(sm.status)+'개',sc('status'));chip('🌐 공개 중',dlN(sm.public)+'개');H.appendChild(ch);p.appendChild(H);
 p.appendChild(dlStepper(sm,ls));
 /* ① 스크리닝 + 결과 */
 var c1=dlStepCard(1,'스크리닝','네이버에서 전 종목(코스피·코스닥) 시세를 받아 기준에 맞는 종목을 가려내요(보통 10~40초)','dlS1');
 var a1=el('div','dlBtns');a1.appendChild(dlB('🔍 스크리닝 실행','p',dlScan));
 a1.appendChild(el('span','note',ls.finished?('마지막 '+(ls.finished_txt||'')+' · 받은 종목 '+dlN(ls.total)+'개'+(ls.error?' · ⚠ '+ls.error:'')):'아직 스크리닝한 적이 없어요. 먼저 [🔍 스크리닝 실행]을 눌러 주세요.'));c1.appendChild(a1);
 var st=el('div','note');st.id='dlSt';c1.appendChild(st);var bar=el('div','dlBar');bar.id='dlBarW';bar.style.display='none';bar.appendChild(el('i'));c1.appendChild(bar);
 var nt=el('div','dlNote');nt.textContent='ⓘ 공통 요건 — 종가·시가총액이 기준에 미달한 상태가 연속 30거래일 지속되면 관리종목으로 지정될 수 있고, 지정 후 90거래일 안에 연속 45거래일 이상 회복하지 못하면 상장폐지 절차로 이어질 수 있어요. 이 화면은 현재 시점의 기준 미달 여부라 실제 지정·폐지와 다를 수 있으니 KIND·DART 공시로 꼭 확인하세요.';c1.appendChild(nt);
 var tool=el('div');tool.id='dlTool';c1.appendChild(tool);var tb=el('div');tb.id='dlTb';tb.style.overflowX='auto';c1.appendChild(tb);p.appendChild(c1);dlToolDraw();dlTable();
 var pubn=el('div','note','🌐 공개 규칙 — 네이버 거래상태에 거래정지·관리종목·상장폐지·정리매매가 표시된 종목은 스크리닝 때 일반 이용자 목록(/delist)에 자동으로 올라가요(거래가 재개되면 내려가요). 시가총액·주가 기준 미달과 ‘오래 거래 없음·등락률 큼’은 추정이라 공개하지 않고 이 화면과 블로그 글에만 써요. 잘못 올라간 종목은 표의 ▾ 상세에서 [공개에서 제외]를 누르세요.');c1.appendChild(pubn);
 var lk=el('div','dlBtns');var pa=el('a',null,'🌐 일반 이용자 목록 화면 열기');pa.href='/delist';pa.target='_blank';pa.rel='noopener';lk.appendChild(pa);
 if(TABS.some(function(t){return t[0]==='fe'}))lk.appendChild(dlB('🎚 공개 등급 설정','',function(){cur='fe';nav();load()}));c1.appendChild(lk);
 /* ③ 이미지 */
 var c3=dlStepCard(2,'이미지','블로그에 올릴 PNG 2장 — ① 메인 대시보드(전체·기준별·위험 상위) ② 위험 종목 표','dlS3');c3.appendChild(el('p','note','[🖼 이미지 만들기]를 누르면 아래에 미리보기가 나오고, 그림마다 [💾 저장]을 누르면 돼요. 스크리닝을 끝낸 뒤 만드세요.'));
 var ib=el('div');c3.appendChild(ib);p.appendChild(c3);
 DL.imgPanel=ImgKit.panel(ib,{menu:'delist',name:'투자주의',ticker:(d.today||'').replace(/-/g,''),gen:function(scale){if(!DL.rows.length)return Promise.reject(new Error('결과가 없어요. 먼저 스크리닝을 실행하세요.'));return Promise.resolve(window.DlImg.build(DL,scale))}});
 /* ④ 블로그 */
 var c4=dlStepCard(3,'블로그 글','네이버 블로그용 HTML — “확정 아님” 표현과 위험 안내가 자동으로 들어가요','dlS4');
 var adv=el('div','dlSub');adv.id='dlAdvBox';adv.appendChild(el('b',null,'💡 투자 주의 조언 (선택) — 글에 함께 들어가요'));c4.appendChild(adv);
 var bs=el('div','dlSub');bs.appendChild(el('b',null,'📝 글 만들기'));var bx=el('div');bs.appendChild(bx);c4.appendChild(bs);p.appendChild(c4);dlAdvDraw(adv);
 DL.blogPanel=window.BlogKit.panel(bx,{idp:'dl',key:'caution',kind:'caution',ticker:'D'+(d.today||'').replace(/-/g,'').slice(2),name:'투자주의 '+(d.today||''),sections:[['stats','요약통계'],['danger','위험종목표'],['warn','경계종목표'],['diff','신규진입·졸업'],['pub','공개종목'],['advice','AI조언'],['rules','스크리닝기준']],dup_warn:'',
  build:function(inc,title){return apiJ('/admin/api/delist/blog',{inc:inc,title:title})}});
 /* 참고 */
 var cD=dlCard('🆕 신규 진입 · 🎓 졸업','직전 스크리닝 대비 변화 — 스크리닝이 끝날 때마다 결과가 자동으로 저장돼 다음 번과 비교해요');cD.id='dlDiffBox';p.appendChild(cD);dlDiffDraw(cD);
 var cR=dlCard('⚙️ 스크리닝 기준 (고급)',(DL.crit&&DL.crit.updated_at?'기준 갱신 '+DL.crit.updated_at+' · ':'')+((DL.crit&&DL.crit.source_note)||''));cR.id='dlCritBox';p.appendChild(cR);dlCritDraw(cR);
 dlWatch(true);if(DL._drawn)window.scrollTo(0,sy);DL._drawn=true}
/* 단계 자동 진행([⚙ 설정] 의 단계 진행 방식): 스크리닝이 끝나면 이미지 → 블로그 글 순서로 설정대로 이어 간다 */
var DLFLOW=['img','blog'];
var DLACTS={
 img:function(next){if(!DL.rows.length||!DL.imgPanel)return;dlGo('dlS3');DL.imgPanel.gen(true).then(function(){if(DL.imgPanel&&DL.imgPanel.items())next()},function(){})},
 blog:function(){if(!DL.rows.length||!DL.blogPanel)return;dlGo('dlS4');DL.blogPanel.rebuild()}};
function dlStepRun(id){/* 단계 줄을 누르면 그 단계 작업을 바로 실행(이어지는 단계는 설정대로) */
 if(id==='dlS1'){dlScan(true);return}
 if(!DL.rows.length){toast('먼저 ① 스크리닝을 실행하세요');return}
 if(id==='dlS3')MiniFlow.go('delist',DLFLOW,DLACTS,'img');
 else if(id==='dlS4')MiniFlow.go('delist',DLFLOW,DLACTS,'blog')}
function dlGo(id){var e=$(id);if(e)e.scrollIntoView({behavior:'smooth',block:'start'})}
/* ── 스크리닝 ── */
function dlScan(now){if(!now&&!confirm('네이버에서 전 종목(코스피·코스닥) 시세 목록을 받아 기준에 맞는 종목을 가려냅니다(보통 10~40초). 계속할까요?'))return;
 apiJ('/admin/api/delist/scan',{}).then(function(j){if(j.error){toast(j.error);return}toast('스크리닝을 시작했어요');DL._wasRunning=true;dlWatch()})}
function dlWatch(quiet){if(DL.timer)clearInterval(DL.timer);
 function tick(){if(cur!=='dl'||!$('dlSt')){clearInterval(DL.timer);DL.timer=null;return}
  api('/admin/api/delist/scan-status').then(function(s){var e=$('dlSt'),b=$('dlBarW');if(!e)return;
   if(s.running){var pc=s.pages_total?Math.min(99,Math.round(s.pages_done*100/s.pages_total)):5;e.textContent='⏳ '+(s.phase||'진행 중')+(s.pages_total?' — 시세 목록 '+s.pages_done+'/'+s.pages_total+'쪽':'')+(s.total?' · 받은 종목 '+dlN(s.total):'');e.className='note';
    if(b){b.style.display='';b.firstChild.style.width=pc+'%'}}
   else{if(b)b.style.display='none';
    if(DL._wasRunning){DL._wasRunning=false;clearInterval(DL.timer);DL.timer=null;e.textContent=s.error?'⚠ '+s.error:'✅ 스크리닝 완료 — 위험 '+s.danger+'개 · 경계 '+s.warn+'개 (받은 종목 '+dlN(s.total)+')';e.className='note'+(s.error?' bad':'');if(!s.error)toast('스크리닝이 끝났어요 — 위험 '+s.danger+'개 · 경계 '+s.warn+'개');dlReload(s.error?null:function(){MiniFlow.run('delist',DLFLOW,DLACTS)});return}
    e.textContent=s.error?'⚠ '+s.error:'';e.className='note'+(s.error?' bad':'');if(!s.running&&!DL._wasRunning){clearInterval(DL.timer);DL.timer=null}}})}
 tick();DL.timer=setInterval(tick,1500)}
/* ── 표 ── */
function dlRows(){return DL.rows}
function dlVisible(){var f=DL.f;var a=dlRows().filter(function(r){var rk=dlRisk(r);
  if(f.scope==='danger'&&rk!=='danger')return false;if(f.scope==='warn'&&rk!=='warn')return false;if(f.scope==='status'&&r.kind!=='halt'&&r.kind!=='delist')return false;
  if(f.mkt&&r.market!==f.mkt)return false;
  if(f.st==='pub'&&!r.pub)return false;if(f.st==='excluded'&&r.admin_state!=='excluded')return false;
  if(f.q&&(r.name+' '+r.ticker).toLowerCase().indexOf(f.q.toLowerCase())<0)return false;return true});
 var s=f.sort,cmp={name_asc:function(x,y){return x.name.localeCompare(y.name,'ko')},name_desc:function(x,y){return y.name.localeCompare(x.name,'ko')},cap_asc:function(x,y){return (x.cap||9e9)-(y.cap||9e9)},cap_desc:function(x,y){return (y.cap||0)-(x.cap||0)},price_asc:function(x,y){return (x.price||9e9)-(y.price||9e9)},price_desc:function(x,y){return (y.price||0)-(x.price||0)},pct_asc:function(x,y){return (x.pct==null?9e9:x.pct)-(y.pct==null?9e9:y.pct)},pct_desc:function(x,y){return (y.pct==null?-9e9:y.pct)-(x.pct==null?-9e9:x.pct)}}[s];
 if(cmp)a=a.slice().sort(cmp);return a}
function dlRisk(r){return dlRiskOf(r)}
function dlToolDraw(){var t=$('dlTool');if(!t)return;t.innerHTML='';var f=DL.f;
 var r1=el('div','dlBtns');r1.appendChild(el('span','note','표시 범위'));[['all','전체(위험+경계)'],['danger','🔴 위험만'],['warn','🟡 경계만'],['status','거래상태 신호']].forEach(function(o){r1.appendChild(dlB(o[1],f.scope===o[0]?'on':'',function(){f.scope=o[0];DL.more=40;dlToolDraw();dlTable()}))});
 var so=el('select');[['default','기본순(위험도)'],['name_asc','가나다순'],['name_desc','가나다 역순'],['cap_asc','시총 낮은순'],['cap_desc','시총 높은순'],['price_asc','주가 낮은순'],['price_desc','주가 높은순'],['pct_asc','등락률 낮은순'],['pct_desc','등락률 높은순']].forEach(function(o){var x=el('option',null,o[1]);x.value=o[0];so.appendChild(x)});so.value=f.sort;so.onchange=function(){f.sort=so.value;dlTable()};r1.appendChild(so);
 var mk=el('select');[['','시장: 전체'],['KOSPI','코스피'],['KOSDAQ','코스닥']].forEach(function(o){var x=el('option',null,o[1]);x.value=o[0];mk.appendChild(x)});mk.value=f.mkt;mk.onchange=function(){f.mkt=mk.value;dlTable()};r1.appendChild(mk);
 var st=el('select');[['','공개: 전체'],['pub','🌐 공개 중'],['excluded','공개 제외']].forEach(function(o){var x=el('option',null,o[1]);x.value=o[0];st.appendChild(x)});st.value=f.st;st.onchange=function(){f.st=st.value;dlTable()};r1.appendChild(adm(st));
 var q=el('input');q.placeholder='🔍 종목명·코드 검색';q.value=f.q;q.style.minWidth='170px';q.oninput=function(){f.q=q.value;clearTimeout(DL._qt);DL._qt=setTimeout(function(){dlTable()},200)};r1.appendChild(q);t.appendChild(r1);
 var r2=el('div','dlBtns');r2.appendChild(adm(el('span','note','스크리닝에 안 잡힌 종목을 따로 지켜보려면')));
 var ai3=el('input');ai3.placeholder='종목코드 6자리';ai3.maxLength=6;ai3.style.width='130px';r2.appendChild(adm(ai3));r2.appendChild(adm(dlB('＋ 직접 추가','',function(){apiJ('/admin/api/delist/add',{ticker:ai3.value}).then(function(j){if(j.error)toast(j.error);else{toast(j.name+' 추가 — 저장 완료');dlReload()}})})));t.appendChild(r2)}
function dlTable(){var box=$('dlTb');if(!box)return;box.innerHTML='';var rows=dlVisible();var shown=rows.slice(0,DL.more);
 box.appendChild(el('p','note',rows.length+'개 표시 (전체 '+dlRows().length+'개) · 자동 계산은 틀릴 수 있어요. 종목 이름을 누르면 종목분석·심층분석이 열리고, ▾ 를 누르면 근거·공시 링크가 나와요.'));
 if(!rows.length){box.appendChild(el('p','note','표시할 종목이 없어요. 위의 [🔍 스크리닝 실행]을 눌러 보세요.'));return}
 var t=el('table','dlTbl'),h=el('tr');[['#',''],['종목',''],['시총','r'],['현재가 · 등락','r'],['단계',''],['해당 기준 · 신호',''],['공개','']].forEach(function(x){var th=el('th',x[1],x[0]);h.appendChild(th)});t.appendChild(h);
 shown.forEach(function(r,i){var tr=el('tr');
  var no=el('td',null,String(i+1));no.style.color='#94a3b8';tr.appendChild(no);
  var n=el('td');n.style.cssText='min-width:130px;word-break:keep-all';var nm=el('b','tkl',r.name);nm.setAttribute('data-tk',r.ticker);nm.title='눌러서 종목분석·심층분석 열기';n.appendChild(nm);n.appendChild(el('div','m',r.ticker+' · '+(r.market||'')));
  var ex=el('span',null,' ▾');ex.style.cssText='cursor:pointer;color:#64748b';ex.title='상세';ex.onclick=function(){DL.open[r.ticker]=!DL.open[r.ticker];dlTable()};n.firstChild.parentNode.firstChild.after(ex);tr.appendChild(n);
  tr.appendChild(el('td','r',dlCap(r.cap)));var pc=el('td','r');pc.appendChild(document.createTextNode(dlN(r.price)+'원'));if(r.pct!=null){var pp=el('div',r.pct>0?'up':(r.pct<0?'dn':''),(r.pct>0?'+':'')+Number(r.pct).toFixed(2)+'%');pp.style.fontSize='11.5px';pc.appendChild(pp)}tr.appendChild(pc);
  var rk=dlRisk(r);var sg=el('td');sg.appendChild(el('span','dlBd '+(rk==='danger'?'d':(rk==='warn'?'w':'o')),rk==='danger'?'🔴 위험':(rk==='warn'?'🟡 경계':'해당 없음')));if(r.kind==='halt'||r.kind==='delist'){var k2=el('div');k2.appendChild(el('span','dlBd s',(DL.meta.kinds||{})[r.kind]||r.kind));k2.style.marginTop='3px';sg.appendChild(k2)}tr.appendChild(sg);
  var w=el('td');(r.matched||[]).forEach(function(m){var rl=dlRule(m.key,m.label);var x=el('span','dlCh'+(m.sev==='danger'?' d':''),m.label||m.key);x.title=(rl&&rl.desc)||'';w.appendChild(x)});(r.signals||[]).slice(0,2).forEach(function(s){w.appendChild(el('div','m',s))});if(!w.firstChild)w.appendChild(el('span','m','—'));tr.appendChild(w);
  var m=el('td');if(r.pub)m.appendChild(el('b','good','🌐 '+r.pub));else if(r.admin_state==='excluded')m.appendChild(el('span','m','공개 제외'));else m.appendChild(el('span','m','—'));tr.appendChild(m);t.appendChild(tr);
  if(DL.open[r.ticker]){var d2=el('tr','dlDt');var dc=el('td');dc.colSpan=7;var tx='';(r.matched||[]).forEach(function(m){var rl=dlRule(m.key,m.label);tx+='• '+(m.label||m.key)+(m.cur!=null?' — 현재 '+dlN(m.cur)+(m.unit||'')+' < 기준 '+dlN(m.value)+(m.unit||''):'')+(rl&&rl.desc?'\n   '+rl.desc:'')+'\n'});(r.signals||[]).forEach(function(s){tx+='• 신호: '+s+'\n'});if(r.last_trade)tx+='• 마지막 거래일 '+r.last_trade+'\n';
   var pre=el('div',null,tx||'상세 정보가 없어요.');pre.style.whiteSpace='pre-wrap';dc.appendChild(pre);var bx=el('div','dlBtns');bx.appendChild(adm(dlB('네이버 원본 확인','',function(){dlRaw(r.ticker)})));bx.appendChild(adm(r.admin_state==='excluded'?dlB('↺ 공개 제외 해제','',function(){dlExclude(r,false)}):dlB('🚫 공개에서 제외','',function(){dlExclude(r,true)})));var lk=el('a',null,'KIND 공시');lk.href='https://kind.krx.co.kr/common/searchcorpname.do?method=searchCorpNameMain&searchCorpName='+encodeURIComponent(r.name);lk.target='_blank';lk.rel='noopener';bx.appendChild(lk);var lk2=el('a',null,' DART');lk2.href='https://dart.fss.or.kr/dsab007/main.do?textCrpNm='+encodeURIComponent(r.name);lk2.target='_blank';lk2.rel='noopener';bx.appendChild(lk2);dc.appendChild(bx);d2.appendChild(dc);t.appendChild(d2)}});
 box.appendChild(t);if(rows.length>shown.length){var mb=dlB('더 보기 ('+(rows.length-shown.length)+'개 남음)','',function(){DL.more+=300;dlTable()});mb.style.marginTop='8px';box.appendChild(mb)}
 var pn=el('div');pn.id='dlpanel';box.appendChild(pn)}
function dlRaw(tk){var pn=$('dlpanel');if(!pn)return;api('/admin/api/delist/diag/'+tk).catch(function(){return {error:'지금은 원본을 확인할 수 없어요.'}}).then(function(j){pn.innerHTML='';var c=el('div','c');c.appendChild(el('div','m',tk+' — 네이버가 보내 준 기본정보 원본(자동 신호가 맞는지 확인용)'));var pre=el('pre',null,j.raw||j.error||'');pre.style.cssText='white-space:pre-wrap;font-size:11.5px;max-height:260px;overflow:auto';c.appendChild(pre);c.appendChild(bt('닫기','bt3',function(){pn.innerHTML=''}));pn.appendChild(c);pn.scrollIntoView()})}
function dlExclude(r,on){if(!confirm(on?('‘'+r.name+'’ 을(를) 일반 이용자 목록에서 뺄까요?\n(잘못 올라간 경우에 쓰세요. 언제든 다시 해제할 수 있어요)'):('‘'+r.name+'’ 의 공개 제외를 풀까요?')))return;
 apiJ('/admin/api/delist/mark',{tickers:[r.ticker],state:on?'excluded':''}).then(function(j){if(j.error)toast(j.error);else{toast(on?'공개에서 제외했어요 — 저장 완료':'공개 제외를 풀었어요 — 저장 완료');dlReload()}})}
/* ── AI 조언 ── */
function dlAdvDraw(c){c=c||$('dlAdvBox');if(!c)return;Array.prototype.slice.call(c.querySelectorAll('.dlAdv,.dlBtns,.m')).forEach(function(x){x.remove()});
 var a=DL.advice||{};if(a.text){var b=el('div','dlAdv',a.text);c.appendChild(b);c.appendChild(el('div','m','저장일 '+(a.date||'')+' · '+a.text.length.toLocaleString()+'자 — 블로그 글에 포함돼요.'))}else c.appendChild(el('div','m','아직 없어요. 아래 [🤖 AI 조언 만들기]를 눌러 보세요(스크리닝 후, 선택 사항).'));
 var r=el('div','dlBtns');r.appendChild(dlB('🤖 AI 조언 만들기','',dlAdvice));if(a.text)r.appendChild(dlB('🗑 지우기','',function(){apiJ('/admin/api/delist/advice-save',{text:''}).then(function(){DL.advice={};toast('지웠어요 — 저장 완료');dlAdvDraw()})}));c.appendChild(r)}
function dlAdvice(){if(!window.MiniAI){toast('AI 도우미 파일(menu_ui.py)이 올라가지 않았어요.');return}
 apiJ('/admin/api/delist/advice-prompt',{}).then(function(j){if(j.error){toast(j.error);return}
  window.MiniAI.run({title:'투자주의 AI 조언',key:'dladv',steps:[{label:'AI 조언',prompt:j.prompt}],minLen:300,hint:'AI가 "## 1. 한 줄 요약 …" 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){var ok=/##\s*1\./.test(t);var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString()+'자 — '+t.slice(0,260)+(t.length>260?' …':'');return {node:x,canApply:t.trim().length>=200,strict:ok,text:ok?null:'형식(## 1. 한 줄 요약 …)이 보이지 않아요. 맞는 답변이면 [저장]을 눌러도 돼요.'}},
   apply:function(t){return apiJ('/admin/api/delist/advice-save',{text:t}).then(function(z){DL.advice={text:t.replace(/<[^>]*>/g,'').trim(),date:z.date};setTimeout(dlAdvDraw,50);return {message:'AI 조언을 저장했어요('+z.len.toLocaleString()+'자). 블로그 글에 포함돼요.'}})}})})}
/* ── 신규진입 · 졸업 · 스냅샷 · 이력 ── */
function dlDiffDraw(c){c=c||$('dlDiffBox');if(!c)return;Array.prototype.slice.call(c.querySelectorAll('.dlDiff,.dlBtns,.m')).forEach(function(x){x.remove()});var d=DL.diff||{};
 if(!d.has_baseline){c.appendChild(el('div','m','첫 스크리닝이에요. 다음 스크리닝부터 직전 결과와 비교한 ‘신규 진입·졸업’이 여기에 나와요.'))}
 else{c.appendChild(el('div','m','직전 스크리닝('+d.prev_date+') 대비'));var g=el('div','dlDiff');
  function box(title,arr,cls){var b=el('div');b.appendChild(el('b',cls,title+' '+arr.length+'개'));var l=el('div','dlList');if(!arr.length)l.textContent='없음';arr.slice(0,120).forEach(function(x){var s=el('span','dlCh'+(x.risk==='danger'?' d':''),x.name);s.setAttribute('data-tk',x.ticker);s.style.cursor='pointer';l.appendChild(s)});b.appendChild(l);g.appendChild(b)}
  box('🆕 신규 진입',d.added||[],'bad');box('🎓 졸업(기준 벗어남)',d.graduated||[],'good');c.appendChild(g)}
}
/* ── 기준 편집 ── */
function dlCritDraw(c){c=c||$('dlCritBox');if(!c)return;Array.prototype.slice.call(c.querySelectorAll('.dlCrit')).forEach(function(x){x.remove()});var w=el('div','dlCrit');
 var hd=el('div','dlBtns');hd.appendChild(dlB(DL.critOpen?'▾ 접기':'▸ 펴기 (기준 보기·수정)','',function(){DL.critOpen=!DL.critOpen;dlCritDraw()}));w.appendChild(hd);
 if(DL.critOpen){var E2=DL.critEdit;w.appendChild(el('p','note','규정이 바뀌면 값을 직접 고치거나 [🤖 AI로 최신 기준 확인]을 쓰세요. 시총 단위=억원, 주가 단위=원. 회복일>0 = 실제 요건, 0 = 경계(주의)용. 바꾼 뒤에는 [💾 기준 저장]을 누르고 스크리닝을 다시 실행하세요.'));
  var head=el('div','dlRule');head.style.fontWeight='800';['사용','조건 이름 / 설명','시장','지표','기준값','회복일',''].forEach(function(x){head.appendChild(el('div',null,x))});w.appendChild(head);
  E2.rules.forEach(function(r,i){var row=el('div','dlRule');var on=el('input');on.type='checkbox';on.checked=r.on!==false;on.onchange=function(){r.on=on.checked};var d1=el('div');d1.appendChild(on);row.appendChild(d1);
   var d2=el('div');var lb=el('input');lb.value=r.label;lb.oninput=function(){r.label=lb.value};d2.appendChild(lb);var ds=el('textarea');ds.rows=2;ds.value=r.desc;ds.oninput=function(){r.desc=ds.value};ds.style.marginTop='4px';d2.appendChild(ds);row.appendChild(d2);
   var mk=el('select');['ALL','KOSPI','KOSDAQ'].forEach(function(v){var o=el('option',null,v);o.value=v;mk.appendChild(o)});mk.value=r.market;mk.onchange=function(){r.market=mk.value};var d3=el('div');d3.appendChild(mk);row.appendChild(d3);
   var me=el('select');[['market_cap','시가총액(억)'],['price','주가(원)']].forEach(function(v){var o=el('option',null,v[1]);o.value=v[0];me.appendChild(o)});me.value=r.metric;me.onchange=function(){r.metric=me.value;r.unit=r.metric==='price'?'원':'억원'};var d4=el('div');d4.appendChild(me);row.appendChild(d4);
   var va=el('input');va.type='number';va.value=r.value;va.oninput=function(){r.value=Number(va.value)};var d5=el('div');d5.appendChild(va);row.appendChild(d5);
   var rc=el('input');rc.type='number';rc.value=r.recover_days;rc.oninput=function(){r.recover_days=Number(rc.value)};var d6=el('div');d6.appendChild(rc);row.appendChild(d6);
   var d7=el('div');d7.appendChild(bt('🗑 삭제','bt3',function(){E2.rules.splice(i,1);dlCritDraw()}));row.appendChild(d7);w.appendChild(row)});
  var bb=el('div','dlBtns');bb.appendChild(dlB('＋ 조건 추가','',function(){E2.rules.push({key:'rule_'+Date.now().toString(36).slice(-5),on:true,market:'ALL',metric:'market_cap',op:'lt',value:100,unit:'억원',warn_days:0,grace_days:0,recover_days:0,label:'새 조건',desc:''});dlCritDraw()}));
  bb.appendChild(dlB('🤖 AI로 최신 기준 확인·갱신','n',dlCritAI));bb.appendChild(dlB('💾 기준 저장','t',function(){E2.updated_at=DL.meta.today;apiJ('/admin/api/delist/criteria',{criteria:E2}).then(function(j){if(j.error){toast(j.error);return}DL.crit=j.criteria;DL.critEdit=JSON.parse(JSON.stringify(j.criteria));toast('기준을 저장했어요 — 스크리닝을 다시 실행하면 반영돼요');dlCritDraw()})}));
  bb.appendChild(dlB('↺ 저장된 값으로 되돌리기','',function(){DL.critEdit=JSON.parse(JSON.stringify(DL.crit));dlCritDraw()}));w.appendChild(bb)}
 c.appendChild(w)}
function dlCritAI(){if(!window.MiniAI){toast('AI 도우미 파일(menu_ui.py)이 올라가지 않았어요.');return}
 apiJ('/admin/api/delist/criteria-prompt',{criteria:DL.critEdit}).then(function(j){if(j.error){toast(j.error);return}
  window.MiniAI.run({title:'AI로 최신 상폐 기준 확인',key:'dlcrit',steps:[{label:'기준 확인',prompt:j.prompt}],minLen:80,hint:'AI가 JSON으로만 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요. 기준 편집 칸에 불러온 뒤 직접 확인하고 [💾 기준 저장]을 누르세요.',
   preview:function(t){return apiJ('/admin/api/delist/criteria-parse',{text:t}).then(function(x){var d=el('div');d.textContent=x.error?x.error:('규칙 '+x.rules+'개를 읽었어요 — '+x.proposed.rules.map(function(r){return r.label}).join(' / '));return {node:d,canApply:!x.error,strict:!x.error}})},
   apply:function(t){return apiJ('/admin/api/delist/criteria-parse',{text:t}).then(function(x){if(x.error)return {message:x.error};DL.critEdit=x.proposed;DL.critOpen=true;setTimeout(dlCritDraw,50);return {message:'기준 편집 칸에 불러왔어요(아직 저장 전). 확인하고 [💾 기준 저장]을 누르세요.'}})}})})}
/* ══════════ [v148] 회원 화면(/m/delist) — 공개 목록 중심. 후보는 열어 준 등급에게만, 관리자 업무 버튼은 보이지 않아요 ══════════ */
DL.mem={q:'',rows:null};
function dlMemSafe(pr,msg){return pr.catch(function(){return {error:msg||'지금은 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'}})}
function dlMemTone(l){return /폐지/.test(l)?'d':(/정지|관리/.test(l)?'w':(/정리/.test(l)?'s':'o'))}
function dlMemLoading(box){box.innerHTML='';box.appendChild(el('p','note','⏳ 불러오는 중…'))}
function dlMemLink(t,h){var a=el('a',null,t);a.href=h;a.target='_blank';a.rel='noopener';return a}
function dlMemDraw(p){p.innerHTML='';
 var H=el('div','dlH');H.appendChild(el('h3',null,'🚫 거래정지·상장폐지 — 종목 안내'));
 H.appendChild(el('p',null,'네이버 증권의 거래상태에 거래정지·관리종목·상장폐지·정리매매로 표시된 종목을 모아 보여드려요(확인일 표시). 거래소 공시와 다를 수 있으니 투자 전 반드시 KIND·DART 원문을 직접 확인하세요. 컴퓨터가 자동으로 가려낸 후보는 기본으로는 보여드리지 않아요.'));p.appendChild(H);
 var al=el('div','dlNote');al.appendChild(el('b',null,'🚨 투자 경고 — '));al.appendChild(document.createTextNode('이 화면은 참고용 정보이며 매수·매도 권유가 아니에요. 거래정지·상장폐지 상태는 수시로 바뀌고, 목록에 없다고 안전하다는 뜻도 아니에요. 투자 전에 KIND·DART 공시와 증권사 앱에서 직접 확인하세요. 투자 판단과 책임은 본인에게 있어요.'));p.appendChild(al);
 p.appendChild(dlMemConfirmed());p.appendChild(dlMemStats());p.appendChild(dlMemDetailBox());p.appendChild(dlMemAdvice());p.appendChild(dlMemImg());p.appendChild(dlMemCand())}
/* ① 종목 목록 */
function dlMemConfirmed(){var c=dlCard('① 🚫 거래정지·상폐 종목 목록','네이버 거래상태 기준 · 이름이나 코드로 검색해 보세요');c.id='dlmConf';
 c.appendChild(el('p','note','상태는 거래정지 · 관리종목 · 상장폐지확정 · 정리매매 중 하나예요. 종목 이름을 누르면 종목분석이 열려요. 이 목록에 없다고 안전하다는 뜻은 아니에요.'));
 if(!ftOk('confirmed')){c.appendChild(el('p','note','이 기능이 열리면 종목을 검색하고 볼 수 있어요.'));return ftSec(c,'confirmed')}
 var bar=el('div','dlBtns');var q=el('input');q.type='search';q.placeholder='🔍 종목명 또는 6자리 코드';q.maxLength=30;q.setAttribute('aria-label','종목 검색');q.style.minWidth='170px';q.style.flex='1 1 170px';
 function go(){DL.mem.q=(q.value||'').trim();dlMemConfDraw()}
 q.onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();go()}};q.oninput=function(){if(!q.value.trim()&&DL.mem.q){DL.mem.q='';dlMemConfDraw()}};
 bar.appendChild(q);bar.appendChild(dlB('검색하기','n',go));bar.appendChild(dlB('전체 보기','',function(){q.value='';go()}));c.appendChild(bar);
 var v=el('div');v.id='dlmV';c.appendChild(v);var box=el('div');box.id='dlmConfBox';box.style.overflowX='auto';c.appendChild(box);dlMemLoading(box);
 dlMemSafe(api('/admin/api/delist/public-preview')).then(function(j){if(j.error){box.innerHTML='';box.appendChild(el('p','note bad',j.error));return}DL.mem.rows=j.rows||[];dlMemConfDraw()});
 return c}
function dlMemConfDraw(){var box=$('dlmConfBox'),v=$('dlmV');if(!box||!v||DL.mem.rows==null)return;box.innerHTML='';v.innerHTML='';
 var q=DL.mem.q,ql=q.toLowerCase();var rows=DL.mem.rows.filter(function(r){return !ql||(r.name+' '+r.ticker).toLowerCase().indexOf(ql)>=0});
 if(q){var vb=el('div','dlNote');
  if(rows.length){vb.appendChild(el('b',null,'⚠️ “'+q+'” — 목록에 '+rows.length+'건 있어요. '));vb.appendChild(document.createTextNode('아래 상태를 확인하고, 투자 전 반드시 KIND·DART 공시 원문으로 직접 다시 확인하세요.'))}
  else{vb.appendChild(el('b',null,'“'+q+'” — 목록에는 없어요. '));vb.appendChild(document.createTextNode('안전한 종목이라는 뜻은 아니에요. 아직 확인하지 못했거나 최근에 바뀐 상태일 수 있으니 '));vb.appendChild(dlMemLink('KIND','https://kind.krx.co.kr'));vb.appendChild(document.createTextNode('·'));vb.appendChild(dlMemLink('DART','https://dart.fss.or.kr'));vb.appendChild(document.createTextNode('에서 직접 확인하세요. '));
   if(/^[0-9A-Za-z]{6}$/.test(q)){var an=el('a',null,'이 종목 분석 보기 →');an.href='/?t='+encodeURIComponent(q.toUpperCase());an.setAttribute('data-tk',q.toUpperCase());vb.appendChild(an)}}
  v.appendChild(vb)}
 box.appendChild(el('p','note',(q?'검색 결과 ':'전체 ')+rows.length+'건'));
 if(!rows.length){box.appendChild(el('p','note',q?'검색한 종목이 목록에 없어요.':'현재 목록에 오른 종목이 없어요.'));return}
 var t=el('table','dlTbl'),h=el('tr');['종목','상태','확인일','근거'].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 rows.forEach(function(r){var tr=el('tr');var n=el('td');n.style.minWidth='120px';var a=el('a',null,r.name+' ('+r.ticker+')');a.href='/?t='+encodeURIComponent(r.ticker);a.setAttribute('data-tk',r.ticker);a.style.fontWeight='700';n.appendChild(a);n.appendChild(el('div','m',r.market||''));tr.appendChild(n);
  var s=el('td');s.style.whiteSpace='nowrap';s.appendChild(el('span','dlBd '+dlMemTone(r.label||''),r.label||'-'));tr.appendChild(s);var d=el('td','m',r.at||'');d.style.whiteSpace='nowrap';tr.appendChild(d);
  var g=el('td');g.style.whiteSpace='nowrap';var gb=ft(dlB('근거 보기','',function(){dlMemDetail(r.ticker)}),'detail');gb.style.whiteSpace='nowrap';g.appendChild(gb);tr.appendChild(g);t.appendChild(tr)});
 box.appendChild(t)}
/* ② 상태별 통계·이력 */
function dlMemBars(box,obj,order){var mx=1;Object.keys(obj).forEach(function(k){if(obj[k]>mx)mx=obj[k]});(order||Object.keys(obj)).forEach(function(k){var r=el('div','dlBk');r.appendChild(el('span',null,k));var tr=el('div','t'),i=el('i');i.style.width=Math.max(4,Math.round(obj[k]*100/mx))+'%';tr.appendChild(i);r.appendChild(tr);r.appendChild(el('span','n',String(obj[k])));box.appendChild(r)})}
function dlMemStats(){var c=dlCard('② 📊 상태별 통계·이력','종목 수와 언제·어떤 상태로 확인됐는지');c.id='dlmStat';
 c.appendChild(el('p','note','목록에 오른 종목만 센 숫자예요(자동 계산 후보는 들어 있지 않아요). 확인일은 스크리닝에서 그 상태가 처음 확인된 날(가장 최근 확인일)이에요.'));
 if(!ftOk('stats')){c.appendChild(el('p','note','이 기능이 열리면 종목 수, 상태별·시장별·월별 통계와 확인일별 이력을 볼 수 있어요.'));return ftSec(c,'stats')}
 var box=el('div');c.appendChild(box);dlMemLoading(box);
 dlMemSafe(api('/admin/api/delist/stats')).then(function(j){box.innerHTML='';if(j.error){box.appendChild(el('p','note bad',j.error));return}
  var k=el('div','dlKpi');function kp(l,v){var d=el('div');d.appendChild(el('small',null,l));d.appendChild(el('b',null,String(v)));k.appendChild(d)}
  kp('목록 종목',j.total+'개');kp('최근 확인일',j.last_at||'-');kp('첫 확인일',j.first_at||'-');box.appendChild(k);
  if(!j.total){box.appendChild(el('p','note','아직 목록에 오른 종목이 없어요.'));return}
  var lb=Object.keys(j.by_label||{}).sort(function(a,b){return j.by_label[b]-j.by_label[a]});box.appendChild(el('b',null,'상태별'));dlMemBars(box,j.by_label||{},lb);
  var mk=Object.keys(j.by_market||{});box.appendChild(el('b',null,'시장별'));dlMemBars(box,j.by_market||{},mk);
  if((j.by_month||[]).length){var bm={},ord=[];j.by_month.forEach(function(x){bm[x.month]=x.n;ord.push(x.month)});box.appendChild(el('b',null,'월별 확인 수(최근 12개월)'));dlMemBars(box,bm,ord)}
  box.appendChild(el('b',null,'확인일별 이력'));
  (j.timeline||[]).forEach(function(x){var tl=el('div','dlTl');tl.appendChild(el('b',null,x.date+' · '+x.n+'종목'));var w=el('div');(x.items||[]).forEach(function(it){var sp=el('span','dlCh',it.name+' · '+it.label);sp.setAttribute('data-tk',it.ticker);sp.style.cursor='pointer';w.appendChild(sp)});tl.appendChild(w);box.appendChild(tl)})});
 return c}
/* ③ 종목별 근거·공시 요약 */
function dlMemDetailBox(){var c=dlCard('③ 🔎 종목별 근거·공시 요약','위 표에서 [근거 보기]를 누르면 여기에 나와요');c.id='dlmDet';
 c.appendChild(el('p','note','현재가·시총·해당 기준은 컴퓨터가 계산한 참고값이에요. 실제 지정·폐지 여부는 KIND·DART 공시 원문으로 직접 확인하세요.'));
 var box=el('div');box.id='dlmDetBox';box.appendChild(el('p','note',ftOk('detail')?'아직 고른 종목이 없어요. 위 표에서 [근거 보기]를 눌러 주세요.':'이 기능이 열리면 종목별 근거와 공시 확인 링크를 볼 수 있어요.'));c.appendChild(box);
 return ftSec(c,'detail')}
function dlMemDetail(tk){var box=$('dlmDetBox');if(!box)return;if(!ftOk('detail')){lockDlg('detail');return}dlMemLoading(box);
 dlMemSafe(api('/admin/api/delist/detail/'+encodeURIComponent(tk))).then(function(j){box.innerHTML='';if(j.error){box.appendChild(el('p','note bad',j.error));return}
  var hd=el('div','dlBtns');hd.appendChild(el('b',null,j.name+' ('+j.ticker+')'));hd.appendChild(el('span','dlBd '+dlMemTone(j.label||''),j.label||'-'));hd.appendChild(el('span','m',(j.market||'')+(j.at?' · 확인일 '+j.at:'')));box.appendChild(hd);
  if(j.note)box.appendChild(el('p','note','운영자 메모: '+j.note));
  var kv=el('div','dlKv');function row(l,v){kv.appendChild(el('b',null,l));kv.appendChild(el('span',null,v))}
  row('현재가',j.price?dlN(j.price)+'원':'-');row('시가총액',dlCap(j.cap));row('최근 등락률',j.pct==null?'-':(j.pct>0?'+':'')+Number(j.pct).toFixed(2)+'%');row('마지막 거래일',j.last_trade||'-');row('자동 점검일',j.as_of||'-');box.appendChild(kv);
  if((j.matched||[]).length){box.appendChild(el('b',null,'해당하는 기준(자동 계산)'));j.matched.forEach(function(m){var d=el('div','m','• '+m.label+(m.cur!=null?' — 현재 '+dlN(m.cur)+(m.unit||'')+' < 기준 '+dlN(m.value)+(m.unit||''):''));box.appendChild(d);if(m.desc){var e=el('div','m',m.desc);e.style.marginLeft='12px';box.appendChild(e)}})}
  if((j.signals||[]).length){box.appendChild(el('b',null,'자동 신호(참고)'));j.signals.forEach(function(x){box.appendChild(el('div','m','• '+x))})}
  var lk=el('div','dlBtns');lk.appendChild(dlMemLink('KIND 공시 확인 ↗','https://kind.krx.co.kr/common/searchcorpname.do?method=searchCorpNameMain&searchCorpName='+encodeURIComponent(j.name)));lk.appendChild(dlMemLink('DART 공시 확인 ↗','https://dart.fss.or.kr/dsab007/main.do?textCrpNm='+encodeURIComponent(j.name)));box.appendChild(lk);
  var cc=$('dlmDet');if(cc&&cc.scrollIntoView)cc.scrollIntoView({behavior:'smooth',block:'start'})})}
/* ④ 투자 주의 안내문(AI 조언) */
function dlMemAdvice(){var c=dlCard('④ 💡 투자 주의 안내문','AI 조언으로 정리한 투자 시 주의점');c.id='dlmAdv';
 if(!ftOk('advice')){c.appendChild(el('p','note','이 글은 운영자가 내용을 읽어 본 뒤 열어요. 아직 공개되지 않았어요.'));return ftSec(c,'advice')}
 var box=el('div');c.appendChild(box);dlMemLoading(box);
 dlMemSafe(api('/admin/api/delist/advice')).then(function(j){box.innerHTML='';if(j.error){box.appendChild(el('p','note bad',j.error));return}
  if(!j.text){box.appendChild(el('p','note','아직 등록된 안내문이 없어요.'));return}box.appendChild(el('div','dlAdv',j.text));box.appendChild(el('p','note','작성일 '+(j.date||'-')+' · AI가 정리한 일반적인 주의점이며 투자 권유가 아니에요.'))});
 return c}
/* ⑤ 종목 현황 이미지 내려받기 */
function dlMemImg(){var c=dlCard('⑤ 🖼 종목 현황 이미지','거래정지·상폐 종목 현황을 PNG 그림으로 내려받아요');c.id='dlmImg';
 c.appendChild(el('p','note','[이미지 만들기]를 누르면 지금의 종목 현황 그림 1장이 만들어져요. 마음에 들면 [내려받기]를 눌러 보관하세요.'));
 var bx=el('div','dlBtns'),out=el('div');var gen=dlB('🖼 이미지 만들기','n',function(){dlMemImgMake(out,gen)});bx.appendChild(ft(gen,'img'));c.appendChild(bx);c.appendChild(out);
 if(!ftOk('img'))c.appendChild(el('p','note','이 기능이 열리면 종목 현황 이미지를 만들어 내려받을 수 있어요.'));
 return ftSec(c,'img')}
function dlMemImgMake(out,btn){var K=window.ImgKit;if(!K||!window.DlImg||!window.DlImg.confirmed){toast('이미지 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}
 btn.disabled=true;btn.textContent='⏳ 그리는 중…';out.innerHTML='';
 dlMemSafe(api('/admin/api/delist/img-data')).then(function(j){if(j.error)throw new Error(j.error);return Promise.resolve(K.fonts?K.fonts():0).then(function(){return window.DlImg.confirmed(j,2)}).then(function(cv){return {cv:cv,day:(j.today||'').replace(/-/g,'')}})}).then(function(x){var cv=x.cv;
  var im=new Image();im.alt='거래정지·상폐 종목 현황 이미지';var pw=Math.min(720,cv.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(cv.height*pw/cv.width);sm.getContext('2d').drawImage(cv,0,0,sm.width,sm.height);im.src=sm.toDataURL('image/png');im.style.cssText='max-width:100%;height:auto;border:1px solid #e2e8f0;border-radius:10px';out.appendChild(im);
  var r=el('div','dlBtns');r.appendChild(dlB('💾 내려받기','t',function(){cv.toBlob(function(b){if(!b){toast('이미지를 만들지 못했어요');return}var u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download='거래정지상폐_종목현황_'+(x.day||'')+'.png';document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(u)},4000)},'image/png')}));out.appendChild(r);btn.textContent='🔄 다시 만들기'})
  .catch(function(e){btn.textContent='🖼 이미지 만들기';toast('이미지를 만들지 못했어요: '+((e&&e.message)||'잠시 후 다시 시도해 주세요'))}).then(function(){btn.disabled=false})}
/* ⑥ 후보 목록(자동 신호) — 기본은 관리자 전용 */
function dlMemCand(){var c=dlCard('⑥ 🧪 후보 목록(자동 신호)','컴퓨터가 자동으로 가려낸 후보 · 확인된 것이 아니에요');c.id='dlmCand';
 c.appendChild(el('p','note bad','⚠ 자동 계산은 틀릴 수 있고 확인된 것이 아니에요. 후보에 있다고 거래정지·상장폐지가 된다는 뜻이 아니에요. 반드시 KIND·DART 공시로 직접 확인하세요.'));
 if(!ftOk('candidates')){c.appendChild(el('p','note','자동 신호는 틀릴 수 있어서, 운영자가 신중히 열어 둔 경우에만 볼 수 있어요.'));return ftSec(c,'candidates')}
 var tool=el('div');tool.id='dlTool';c.appendChild(tool);var tb=el('div');tb.id='dlTb';tb.style.overflowX='auto';c.appendChild(tb);dlMemLoading(tb);
 dlMemSafe(api('/admin/api/delist/list')).then(function(d){if(d.error||!d.rows){tb.innerHTML='';tb.appendChild(el('p','note bad',d.error||'후보를 불러오지 못했어요.'));return}
  dlApplyData(d);dlToolDraw();dlTable()});
 return c}
"""

IMG_JS = r"""
(function(){
var K=window.ImgKit;if(!K||window.DlImg)return;
var T=K.text,RR=K.rr,N=K.n;
var INK='#0f172a',MUT='#64748b',RED='#dc2626',AMB='#d97706';
function capT(c){if(!c)return '-';return c>=10000?(c/10000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조':N(c)+'억'}
function today(){var x=new Date(),z=function(n){return ('0'+n).slice(-2)};return x.getFullYear()+'.'+z(x.getMonth()+1)+'.'+z(x.getDate())}
function shadow(c,x,y,w,h,r){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,r||24);c.fillStyle='#fff';c.fill();c.restore()}
function head(c,W,sub){var g=c.createLinearGradient(0,0,W,260);g.addColorStop(0,'#450a0a');g.addColorStop(.55,'#991b1b');g.addColorStop(1,'#dc2626');c.fillStyle=g;c.fillRect(0,0,W,250);
 T(c,'INVESTMENT CAUTION',W/2,64,{s:20,w:800,c:'#fecaca',a:'center',ls:6});T(c,'투자주의 · 상장유지 기준 점검',W/2,130,{s:54,w:900,c:'#fff',a:'center',max:W-120});T(c,sub,W/2,186,{s:24,w:600,c:'#fecaca',a:'center',max:W-120});
 T(c,today()+' 기준 · 공개 시세 자동 계산(확정 아님)',W/2,226,{s:19,w:600,c:'rgba(255,255,255,.75)',a:'center'})}
function foot(c,W,y){c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,y,W-120,2);T(c,'공개 데이터 기반 참고 자료이며 상장폐지·관리종목·거래정지를 단정하거나 예측하지 않아요. 투자 판단과 책임은 본인에게 있어요.',W/2,y+40,{s:18,w:600,c:MUT,a:'center',max:W-120});
 T(c,'투자 전 한국거래소 KIND · 금융감독원 DART 공시 원문을 꼭 확인하세요',W/2,y+70,{s:18,w:700,c:'#92400e',a:'center',max:W-120})}
function rows(D){return D.rows.filter(function(r){return r.active!==0})}
function risk(r){return r.risk||((r.kind==='halt'||r.kind==='delist')?'danger':'')}
function main(D,scale){var W=1080,all=rows(D),dg=all.filter(function(r){return risk(r)==='danger'}),wn=all.filter(function(r){return risk(r)==='warn'}),stt=all.filter(function(r){return r.kind==='halt'||r.kind==='delist'});
 var rules={};all.forEach(function(r){(r.matched||[]).forEach(function(m){var k=m.label||m.key;rules[k]=(rules[k]||0)+1})});if(stt.length)rules['거래상태 이상 신호']=stt.length;
 var rk=Object.keys(rules).map(function(k){return [k,rules[k]]}).sort(function(a,b){return b[1]-a[1]}).slice(0,6);
 var top=dg.slice().sort(function(a,b){return (a.cap||9e9)-(b.cap||9e9)}).slice(0,10);
 var H=250+40+170+30+(80+rk.length*58)+30+(80+Math.max(1,top.length)*60)+30+150;var m=K.make(W,H,scale),c=m.c;c.fillStyle='#f4f1ec';c.fillRect(0,0,W,H);head(c,W,'전체 '+all.length+'종목 · 위험 '+dg.length+' · 경계 '+wn.length);
 var y=290,cw=(W-80-3*16)/4;[['전체',all.length,INK],['🔴 위험',dg.length,RED],['🟡 경계',wn.length,AMB],['거래상태 신호',stt.length,'#7c3aed']].forEach(function(s,i){var x=40+i*(cw+16);shadow(c,x,y,cw,170,22);T(c,s[0],x+cw/2,y+54,{s:24,w:800,c:MUT,a:'center'});T(c,String(s[1]),x+cw/2,y+128,{s:72,w:900,c:s[2],a:'center'})});y+=200;
 var bh=80+rk.length*58;shadow(c,40,y,1000,bh,24);c.fillStyle=RED;RR(c,66,y+26,6,30,3);c.fill();T(c,'기준별 해당 종목 수',86,y+50,{s:26,w:900,c:INK});
 var mx=Math.max.apply(null,rk.map(function(a){return a[1]}).concat([1]));rk.forEach(function(a,i){var yy=y+90+i*58;T(c,a[0],70,yy+18,{s:21,w:700,c:'#334155',max:360});RR(c,440,yy,470,24,12);c.fillStyle='#eef2f7';c.fill();RR(c,440,yy,Math.max(24,470*a[1]/mx),24,12);var g=c.createLinearGradient(440,0,910,0);g.addColorStop(0,'#f97316');g.addColorStop(1,'#dc2626');c.fillStyle=g;c.fill();T(c,a[1]+'개',1010,yy+20,{s:24,w:900,c:INK,a:'right'})});
 if(!rk.length)T(c,'해당 종목이 없어요',70,y+110,{s:22,w:600,c:MUT});y+=bh+30;
 var th=80+Math.max(1,top.length)*60;shadow(c,40,y,1000,th,24);c.fillStyle=RED;RR(c,66,y+26,6,30,3);c.fill();T(c,'🔴 위험 구간 — 시총 낮은 순 TOP '+top.length,86,y+50,{s:26,w:900,c:INK});
 top.forEach(function(r,i){var yy=y+84+i*60;if(i%2===0){c.fillStyle='#f8fafc';c.fillRect(56,yy-8,968,56)}T(c,String(i+1),86,yy+30,{s:22,w:900,c:'#94a3b8',a:'center'});T(c,r.name,120,yy+30,{s:24,w:800,c:INK,max:300});T(c,r.market==='KOSPI'?'코스피':'코스닥',430,yy+30,{s:18,w:700,c:MUT});T(c,capT(r.cap),600,yy+30,{s:22,w:800,c:'#334155',a:'right'});T(c,N(r.price)+'원',790,yy+30,{s:22,w:700,c:'#334155',a:'right'});
  var lb=(r.matched&&r.matched[0]&&r.matched[0].label)||((r.signals&&r.signals[0])||'거래상태 신호');T(c,lb.replace(/ \(.*$/,''),1004,yy+30,{s:16,w:700,c:'#9f1239',a:'right',max:200})});
 if(!top.length)T(c,'위험 구간 종목이 없어요',86,y+130,{s:22,w:600,c:MUT});y+=th+30;foot(c,W,y);return m.cv}
function table(D,scale){var W=1080,all=rows(D).filter(function(r){return risk(r)==='danger'}).slice(0,16),wn=rows(D).filter(function(r){return risk(r)==='warn'}).length;var df=D.diff||{};
 var H=250+40+(df.has_baseline?120:0)+90+Math.max(1,all.length)*62+30+150;var m=K.make(W,H,scale),c=m.c;c.fillStyle='#f4f1ec';c.fillRect(0,0,W,H);head(c,W,'위험 구간 종목 표 · 경계 '+wn+'종목은 별도');var y=290;
 if(df.has_baseline){shadow(c,40,y,1000,100,22);T(c,'직전 저장일 '+df.prev_date+' 대비',70,y+40,{s:22,w:800,c:MUT});T(c,'🆕 신규 진입 '+(df.added||[]).length+'개',70,y+80,{s:28,w:900,c:RED});T(c,'🎓 졸업 '+(df.graduated||[]).length+'개',520,y+80,{s:28,w:900,c:'#16a34a'});y+=130}
 var th=90+Math.max(1,all.length)*62;shadow(c,40,y,1000,th,24);c.fillStyle=RED;RR(c,66,y+26,6,30,3);c.fill();T(c,'위험 구간 종목 (기준 미달 · 거래상태 신호)',86,y+50,{s:26,w:900,c:INK});
 c.fillStyle='#f1f5f9';c.fillRect(56,y+70,968,40);['종목','시총','현재가','해당 기준'].forEach(function(h,i){T(c,h,[76,560,720,742][i],y+98,{s:19,w:800,c:'#475569',a:i===1||i===2?'right':'left'})});
 all.forEach(function(r,i){var yy=y+122+i*62;if(i%2===1){c.fillStyle='#f8fafc';c.fillRect(56,yy-12,968,60)}T(c,r.name,76,yy+22,{s:23,w:800,c:INK,max:300});T(c,r.ticker+' · '+(r.market==='KOSPI'?'코스피':'코스닥'),76,yy+44,{s:15,w:600,c:'#94a3b8'});T(c,capT(r.cap),560,yy+30,{s:22,w:800,c:'#334155',a:'right'});T(c,N(r.price)+'원',720,yy+30,{s:21,w:700,c:'#334155',a:'right'});
  var lb=(r.matched||[]).map(function(m){return m.label}).join(' · ')||((r.signals&&r.signals[0])||'거래상태 신호');lb=String(lb).split(' (')[0].split(' — ')[0];if(lb.length>26)lb=lb.slice(0,25)+'…';T(c,lb,742,yy+30,{s:17,w:700,c:'#9f1239',max:270})});
 if(!all.length)T(c,'위험 구간 종목이 없어요',86,y+150,{s:22,w:600,c:MUT});y+=th+30;foot(c,W,y);return m.cv}
function tone(l){return /폐지/.test(l)?['#fee2e2','#991b1b']:(/정지|관리/.test(l)?['#fef3c7','#92400e']:(/정리/.test(l)?['#ede9fe','#5b21b6']:['#e2e8f0','#475569']))}
function conf(D,scale){var W=1080,rows=(D.rows||[]).slice(0,15),by=D.by_label||{},tot=D.total||0,keys=Object.keys(by).sort(function(a,b){return by[b]-by[a]}).slice(0,3);
 var more=tot>rows.length?44:0,th=90+Math.max(1,rows.length)*62+more,H=250+40+170+30+th+30+150;var m=K.make(W,H,scale),c=m.c;c.fillStyle='#f4f1ec';c.fillRect(0,0,W,H);
 var g=c.createLinearGradient(0,0,W,260);g.addColorStop(0,'#450a0a');g.addColorStop(.55,'#991b1b');g.addColorStop(1,'#dc2626');c.fillStyle=g;c.fillRect(0,0,W,250);
 T(c,'DELISTING WATCH',W/2,64,{s:20,w:800,c:'#fecaca',a:'center',ls:6});T(c,'거래정지·상장폐지 종목',W/2,130,{s:54,w:900,c:'#fff',a:'center',max:W-120});T(c,'네이버 거래상태 기준 '+tot+'개 · 투자 전 공시 원문 직접 확인',W/2,186,{s:24,w:600,c:'#fecaca',a:'center',max:W-120});
 T(c,(D.today||today()).replace(/-/g,'.')+' 기준 · 참고용 정보(투자 권유 아님)',W/2,226,{s:19,w:600,c:'rgba(255,255,255,.75)',a:'center'});
 var y=290,items=[['목록 종목',tot,INK]].concat(keys.map(function(k){return [k,by[k],RED]})),cw=(W-80-(items.length-1)*16)/items.length;
 items.forEach(function(s,i){var x=40+i*(cw+16);shadow(c,x,y,cw,170,22);T(c,s[0],x+cw/2,y+54,{s:24,w:800,c:MUT,a:'center',max:cw-20});T(c,String(s[1]),x+cw/2,y+128,{s:72,w:900,c:s[2],a:'center'})});y+=200;
 shadow(c,40,y,1000,th,24);c.fillStyle=RED;RR(c,66,y+26,6,30,3);c.fill();T(c,'거래정지·상폐 종목 목록',86,y+50,{s:26,w:900,c:INK});
 rows.forEach(function(r,i){var yy=y+84+i*62;if(i%2===0){c.fillStyle='#f8fafc';c.fillRect(56,yy-8,968,58)}T(c,String(i+1),86,yy+30,{s:22,w:900,c:'#94a3b8',a:'center'});T(c,r.name,120,yy+26,{s:24,w:800,c:INK,max:380});T(c,r.ticker+' · '+(r.market==='KOSPI'?'코스피':(r.market==='KOSDAQ'?'코스닥':(r.market||''))),120,yy+46,{s:15,w:600,c:'#94a3b8'});
  var tn=tone(r.label||'');RR(c,540,yy+4,190,40,20);c.fillStyle=tn[0];c.fill();T(c,r.label||'-',635,yy+31,{s:20,w:800,c:tn[1],a:'center',max:170});T(c,r.at||'',1004,yy+30,{s:20,w:700,c:'#334155',a:'right'})});
 if(!rows.length)T(c,'현재 목록에 오른 종목이 없어요',86,y+130,{s:22,w:600,c:MUT});if(more)T(c,'… 외 '+(tot-rows.length)+'종목은 화면에서 확인하세요',86,y+th-26,{s:20,w:700,c:MUT});
 y+=th+30;foot(c,W,y);return m.cv}
window.DlImg={build:function(D,scale){return [{idx:1,label:'메인 대시보드',canvas:main(D,scale)},{idx:2,label:'위험 종목 표',canvas:table(D,scale)}]},confirmed:function(D,scale){return conf(D,scale)}};
})();
"""

# ══════════════════════════════════════════════════════════════
# 공개 화면(네이버 거래상태에 표시된 종목)
# ══════════════════════════════════════════════════════════════
DELIST_BODY = r"""
<div class="mu-alert" role="alert">
 <div class="mu-alert-h"><span>🚨</span><b>투자 경고 — 반드시 직접 확인하고, 투자 책임은 본인에게 있습니다</b></div>
 <ol class="mu-alert-l">
  <li>이 목록은 <b>참고용 정보</b>이며 매수·매도 권유나 추천이 아닙니다.</li>
  <li>거래정지·상장폐지 상태는 <b>수시로 바뀝니다</b>(거래 재개, 상장폐지 결정, 정리매매 등). 목록에 <b>없다고 안전하다는 뜻이 아니며</b>, 있다고 최신 상태라는 보장도 없습니다.</li>
  <li><b>투자 전에 반드시</b> 한국거래소 <a href="https://kind.krx.co.kr" target="_blank" rel="noopener">KIND</a>·금융감독원 <a href="https://dart.fss.or.kr" target="_blank" rel="noopener">DART</a> 공시 원문과 증권사 앱의 거래 상태를 <b>직접</b> 확인하세요.</li>
  <li>투자 판단과 그 결과(손실 포함)의 <b>모든 책임은 투자자 본인</b>에게 있으며, 운영자는 이 정보로 인한 손해에 책임지지 않습니다.</li>
 </ol>
</div>
<form class="mu-search" id="sf" onsubmit="return false">
 <input id="q" type="search" placeholder="종목명 또는 6자리 종목코드를 입력하세요 (예: 삼성전자, 005930)" autocomplete="off" aria-label="종목 검색">
 <button class="mu-btn primary" id="sb" type="submit">🔍 검색</button>
 <button class="mu-btn" id="sr" type="button" style="display:none">전체 보기</button>
</form>
<div id="verdict"></div>
<div class="mu-stats" id="stats"></div>
<div class="mu-card"><div class="mu-card-h">🚫 거래정지·상폐 종목 목록<small id="cnt"></small></div>
<div id="box"><div class="mu-empty">불러오는 중…</div></div></div>
<div class="mu-alert slim"><span>⚠️</span><div><b>다시 한 번 — 투자 전 KIND·DART에서 직접 확인하세요.</b> 이 화면은 네이버 증권 거래상태에 표시된 종목만 보여 드리며 거래소 공시와 다를 수 있고 모든 종목의 상태를 보장하지 않습니다. 투자 책임은 본인에게 있습니다.</div></div>
"""

DELIST_SCRIPT = r"""
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
var ROWS=[],QRY='';
function tone(l){return /상장폐지|폐지/.test(l)?'red':(/정지|관리/.test(l)?'amber':(/정리/.test(l)?'blue':''))}
function stats(){var s=document.getElementById('stats');s.innerHTML='';var by={};ROWS.forEach(function(r){by[r.label]=(by[r.label]||0)+1});
 function box(l,v,c,sub){var d=el('div','mu-stat '+(c||''));d.appendChild(el('div','l',l));d.appendChild(el('div','v',String(v)));if(sub)d.appendChild(el('div','s',sub));s.appendChild(d)}
 box('목록 종목',ROWS.length,'gold','네이버 거래상태');Object.keys(by).sort(function(a,b){return by[b]-by[a]}).slice(0,3).forEach(function(k){box(k,by[k],tone(k)==='red'?'red':'')});
 if(ROWS.length){var last=ROWS.reduce(function(m,r){return r.at>m?r.at:m},'');box('최근 확인일',last||'-','green')}}
function match(r,q){var t=(r.name+' '+r.ticker).toLowerCase();return t.indexOf(q)>=0}
function verdict(rows,q){var v=document.getElementById('verdict');v.innerHTML='';if(!q)return;
 var box=el('div','mu-verdict '+(rows.length?'hit':'miss'));
 if(rows.length){box.appendChild(el('b',null,'⚠️ "'+q+'" — 목록에 '+rows.length+'건 있습니다.'));box.appendChild(el('div',null,'아래 상태를 확인하고, 투자 전 반드시 KIND·DART 공시 원문으로 직접 다시 확인하세요.'))}
 else{box.appendChild(el('b',null,'"'+q+'" — 목록에는 없습니다.'));
  var d=el('div',null,'이것이 "안전한 종목"이라는 뜻은 아닙니다. 아직 확인하지 못했거나 최근에 바뀐 상태일 수 있으니 반드시 ');var a=el('a',null,'KIND');a.href='https://kind.krx.co.kr';a.target='_blank';a.rel='noopener';d.appendChild(a);d.appendChild(document.createTextNode('·'));
  var b=el('a',null,'DART');b.href='https://dart.fss.or.kr';b.target='_blank';b.rel='noopener';d.appendChild(b);d.appendChild(document.createTextNode(' 에서 직접 확인하세요. '));
  if(/^\d{6}$/.test(q)){var c=el('a',null,'이 종목 분석 보기 →');c.href='/?t='+q;c.setAttribute('data-tk',q);d.appendChild(c)}box.appendChild(d)}
 v.appendChild(box)}
function draw(){var b=document.getElementById('box');b.innerHTML='';var q=QRY.toLowerCase();
 var rows=ROWS.filter(function(r){return !q||match(r,q)});document.getElementById('cnt').textContent=(q?'검색 결과 ':'전체 ')+rows.length+'건';
 document.getElementById('sr').style.display=q?'':'none';verdict(rows,QRY);
 if(!rows.length){var e=el('div','mu-empty');e.appendChild(el('b',null,q?'🔍':'🗂️'));e.appendChild(document.createTextNode(q?'검색한 종목이 목록에 없어요.':'현재 목록에 오른 종목이 없습니다.'));b.appendChild(e);return}
 var w=el('div','mu-tw'),t=el('table','mu-tbl'),th=el('thead'),h=el('tr');['종목','상태','확인일'].forEach(function(x){h.appendChild(el('th',null,x))});th.appendChild(h);t.appendChild(th);var tb=el('tbody');
 rows.forEach(function(r){var tr=el('tr'),td=el('td');var a=el('a',null,r.name+' ('+r.ticker+')');a.style.fontWeight='700';a.href='/?t='+encodeURIComponent(r.ticker);a.setAttribute('data-tk',r.ticker);td.appendChild(a);td.appendChild(el('div','mu-sub',r.market||''));tr.appendChild(td);
  var s=el('td');s.appendChild(el('span','mu-badge '+tone(r.label),r.label));tr.appendChild(s);var d=el('td','mu-sub',r.at||'');d.style.whiteSpace='nowrap';tr.appendChild(d);tb.appendChild(tr)});
 t.appendChild(tb);w.appendChild(t);b.appendChild(w)}
function go(){QRY=(document.getElementById('q').value||'').trim();draw()}
document.getElementById('sf').addEventListener('submit',go);document.getElementById('sb').addEventListener('click',go);
document.getElementById('q').addEventListener('input',function(){if(!this.value.trim()){QRY='';draw()}});
document.getElementById('sr').addEventListener('click',function(){document.getElementById('q').value='';QRY='';draw()});
fetch('/api/delist/public').then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){ROWS=d.rows||[];stats();draw()})
 .catch(function(){var b=document.getElementById('box');b.innerHTML='';b.appendChild(el('div','mu-empty','지금은 볼 수 없는 화면입니다.'))});
"""


def _page_html(api):
    return U.page("거래정지·상장폐지 종목", DELIST_BODY, icon="🚫", subtitle="네이버 증권 거래상태에 표시된 거래정지·상장폐지 종목을 모았습니다. 투자 전 원문을 꼭 확인하세요.",
                  script=DELIST_SCRIPT.replace("'/api/delist/public'", "'" + api + "'"), active="delist")


@bp.route("/delist")
def delist_public_page():
    if not menu_visible("delist"):
        return "not found", 404
    resp = app.make_response(_page_html("/api/delist/public"))
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@bp.route("/admin/preview/delist")
def delist_admin_preview():
    """숨김 상태여도 관리자는 일반 이용자가 보게 될 화면을 미리 볼 수 있다(관리자 로그인 쿠키는 /admin 아래로만 오므로 이 주소를 쓴다)."""
    deny = _admin_deny()
    if deny:
        return deny
    resp = app.make_response(_page_html("/admin/api/delist/public-preview"))
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    return resp



# ── 표 만들기 · 등록 ──
def _ensure_delist_table(cur, use_pg):
    real = "DOUBLE PRECISION" if use_pg else "REAL"
    cur.execute(f"""CREATE TABLE IF NOT EXISTS delist_watch(
        ticker TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', market TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT '', signals TEXT NOT NULL DEFAULT '', price BIGINT NOT NULL DEFAULT 0,
        last_trade TEXT NOT NULL DEFAULT '', first_seen BIGINT NOT NULL DEFAULT 0, last_seen BIGINT NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        ai_verdict TEXT NOT NULL DEFAULT '', ai_basis TEXT NOT NULL DEFAULT '', ai_source TEXT NOT NULL DEFAULT '',
        ai_date TEXT NOT NULL DEFAULT '', ai_at BIGINT NOT NULL DEFAULT 0, ai_mode TEXT NOT NULL DEFAULT '',
        admin_state TEXT NOT NULL DEFAULT '', admin_label TEXT NOT NULL DEFAULT '', admin_note TEXT NOT NULL DEFAULT '',
        admin_at BIGINT NOT NULL DEFAULT 0,
        cap BIGINT NOT NULL DEFAULT 0, pct {real}, matched TEXT NOT NULL DEFAULT '[]', risk TEXT NOT NULL DEFAULT '')""")
    # v145: 이미 만들어진 표에 새 칸을 더한다(있으면 건너뜀)
    new = (("cap", "BIGINT NOT NULL DEFAULT 0"), ("pct", real), ("matched", "TEXT NOT NULL DEFAULT '[]'"), ("risk", "TEXT NOT NULL DEFAULT ''"))
    if use_pg:
        for col, typ in new:
            cur.execute(f"ALTER TABLE delist_watch ADD COLUMN IF NOT EXISTS {col} {typ}")
    else:
        cur.execute("PRAGMA table_info(delist_watch)")
        have = {r[1] for r in cur.fetchall()}
        for col, typ in new:
            if col not in have:
                cur.execute(f"ALTER TABLE delist_watch ADD COLUMN {col} {typ}")
        # 예전(v140~v144) 스캔 결과는 위험 단계가 비어 있다 → 신호가 있던 것은 '위험'으로 채운다
    cur.execute("UPDATE delist_watch SET risk='danger' WHERE risk='' AND active=1 AND kind IN ('halt','delist')")
    cur.execute("UPDATE delist_watch SET risk='warn' WHERE risk='' AND active=1 AND kind IN ('caution','manual')")
    cur.execute("""CREATE TABLE IF NOT EXISTS delist_snaps(
        snap_date TEXT PRIMARY KEY, total INTEGER NOT NULL DEFAULT 0, danger INTEGER NOT NULL DEFAULT 0, warn INTEGER NOT NULL DEFAULT 0,
        items_json TEXT NOT NULL DEFAULT '[]', summary_json TEXT NOT NULL DEFAULT '{}', added_json TEXT NOT NULL DEFAULT '[]',
        graduated_json TEXT NOT NULL DEFAULT '[]', prev_date TEXT NOT NULL DEFAULT '', updated_at BIGINT NOT NULL DEFAULT 0)""")


def _valid_days(k, v):
    return str(int(v)) if v.isdigit() and 3 <= int(v) <= 60 else None


def _valid_bool(k, v):
    return v if v in ("0", "1") else None


def register():
    global _AIJOBS
    _AIJOBS = C._AIJOBS
    C.register_menu({"id": "delist", "label": "거래정지·상폐", "icon": "🚫", "public_path": "/m/delist",
                     "admin_path": "/admin#dl", "preview_path": "/m/delist",
                     "desc": "네이버 거래상태 기준 거래정지·상장폐지(관리종목·정리매매) 종목 목록과 상태별 통계", "access": "admin"})
    C.register_settings({"delist_stale_days": "10", "delist_include_caution": "0"},
                        {"delist_stale_days": _valid_days, "delist_include_caution": _valid_bool})
    C.register_prompt("delist_advice", {
        "title": "투자주의 AI 조언 프롬프트", "default": DELIST_ADVICE_DEFAULT,
        "required": ["{summary}", "{items}"], "must_have": ["## 1."],
        "vars": "{today}=오늘 날짜 · {summary}=결과 요약(필수) · {items}=상위 종목(필수)",
        "desc": "스크리닝 결과를 바탕으로 '투자 시 주의점·접근 방향'을 쓰게 하는 요청문. 블로그 글에 함께 들어가요."})
    C.register_flow("delist", "🚫 거래정지·상폐", "① 스크리닝 실행(직접 시작)", [
        {"id": "img", "label": "② 이미지 만들기", "desc": "스크리닝이 끝나면 PNG 이미지 2장을 자동으로 그려요."},
        {"id": "blog", "label": "③ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요. 만든 뒤 복사해서 올리면 돼요."}])
    C.register_table_hook(_ensure_delist_table)
    C.register_admin_tab("dl", "🚫 거래정지·상폐", TAB_JS + "\n" + IMG_JS, "dlLoad", menu="delist")
    # 🎚 기능별 등급 공개 — 읽기 전용 기능만. 스캔·기준 저장·공개 제외·블로그·설정·가져오기 같은 관리자 업무 주소는
    # 어떤 기능에도 넣지 않는다(= 회원 화면에서는 404, 관리자만).
    C.register_feature("delist", "confirmed", "거래정지·상폐 종목 목록", "네이버 증권 거래상태에 표시된 거래정지·관리종목·상장폐지·정리매매 종목을 검색·열람해요(공개 화면 /delist 와 같은 데이터).",
                       default="public", endpoints=["/admin/api/delist/public-preview"])
    C.register_feature("delist", "stats", "상태별 통계·이력", "종목 수, 상태별·시장별·월별 수와 확인일별 이력을 봐요.",
                       default="member", endpoints=["/admin/api/delist/stats"])
    C.register_feature("delist", "detail", "종목별 근거·공시 요약", "종목마다 확인 근거·출처·현재가·시총·해당 기준·공시 확인 링크를 모아 봐요.",
                       default="L2", endpoints=["/admin/api/delist/detail/*"])
    C.register_feature("delist", "advice", "투자 주의 안내문(AI 조언)", "AI 조언으로 만든 ‘투자 시 주의점’ 글. 후보 종목 이름이 들어 있을 수 있어 관리자가 읽어 본 뒤 열어요.",
                       default="admin", endpoints=["/admin/api/delist/advice"])
    C.register_feature("delist", "img", "종목 현황 이미지 내려받기", "거래정지·상폐 종목 현황을 PNG 이미지로 만들어 내려받아요.",
                       default="L3", endpoints=["/admin/api/delist/img-data"])
    C.register_feature("delist", "candidates", "후보 목록(자동 신호)", "자동 계산으로 가려낸 후보(신규 진입·졸업 포함). 자동 신호는 틀릴 수 있어 일반 공개는 관리자가 신중히 열어요(AI 의견·제외 종목은 안 보여요).",
                       default="admin", endpoints=["/admin/api/delist/list"])
    return bp
