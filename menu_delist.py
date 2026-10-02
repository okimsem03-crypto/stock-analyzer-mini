"""🚫 거래정지·상장폐지 메뉴 (관리자 전용으로 시작, 공개 여부는 관리자 화면에서 정함)

  · 후보 수집: 네이버 모바일 증권 API(거래 상태·최근 거래일·등락률)로 전 종목을 훑어 신호가 있는 종목만 모은다.
    자동 신호는 틀릴 수 있다.
  · 검증: AI 프롬프트(수동 = 복사·붙여넣기 / 자동 = 서버 API 키)로 공시 근거를 확인하고, 최종 확정은 관리자가 누른다.
  · 공개 화면에는 '관리자가 확정한 종목'만 나온다(자동 신호·AI 의견은 공개하지 않는다).
이 파일은 본체의 함수를 C 로 호출한다(menu_ctx.py 설명 참고).
"""
import re, time, json, sqlite3, threading
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, current_app as app
from menu_ctx import C

bp = Blueprint("delist", __name__)

# 본체 함수 — 호출할 때마다 본체에서 찾아 쓴다(시험에서 바꿔 끼워도 반영되도록).
_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_dbx", "_dbrows", "_json_body", "_ensure_v135_tables",
               "normalize_ticker", "setting_get", "setting_set", "_kst_str", "_now_kst", "menu_visible",
               "_naver_mobile_basic", "_naver_trading_status_flags", "ai_pick_provider", "ai_complete",
               "get_db", "get_ticker_info", "prompt_get", "_prompt_fill", "_prompt_check", "_job_busy", "_job_new")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)
_AIJOBS = {}          # register() 에서 본체의 작업 목록으로 교체된다


DL_VERDICTS = ("거래정지", "관리종목", "상장폐지확정", "정리매매", "정상", "확인불가")


DL_PUBLIC_LABELS = ("거래정지", "관리종목", "상장폐지확정", "정리매매")


DL_CHUNK = 15                 # AI 한 번(프롬프트 하나)에 넣는 종목 수


DL_AI_MAX_PER_RUN = 150       # 한 번에 AI로 검증하는 최대 종목 수(비용·시간 보호)


DL_PCT_LIMIT = 30.5           # 일일 가격제한폭(±30%)을 넘는 등락 = 정리매매·신규상장일 가능성


_DL_SCAN = {"running": False, "total": 0, "done": 0, "ok": 0, "flagged": 0, "started": 0, "finished": 0,
            "error": "", "cancel": False}


DELIST_VERIFY_DEFAULT = """당신은 한국 주식시장(KOSPI·KOSDAQ·KONEX)의 공시를 확인하는 조사 보조원입니다. 오늘은 {today}입니다.
아래 {count}개 종목은 프로그램이 '거래정지 또는 상장폐지 절차에 있을 가능성'이 있다고 자동으로 걸러낸 후보입니다. 자동 신호는 틀릴 수 있습니다.
각 종목의 현재 상태를 한국거래소 KIND(kind.krx.co.kr)·금융감독원 DART(dart.fss.or.kr) 등 공식 공시를 근거로 확인해 주세요.

[판정 — 반드시 아래 6개 단어 중 하나만 사용]
- 거래정지: 지금 매매거래가 정지된 상태(감사의견 거절·횡령/배임·기업심사·불성실공시 등 사유 포함)
- 관리종목: 관리종목으로 지정되어 있지만 거래는 이뤄지는 상태
- 상장폐지확정: 거래소가 상장폐지를 결정·확정한 상태(정리매매 예정 포함)
- 정리매매: 정리매매 기간 중
- 정상: 정상 거래 중이며 위 사유가 없음
- 확인불가: 공식 자료로 확인하지 못함

[규칙]
1. 공식 공시로 확인한 사실만 쓰세요. 추측·소문·커뮤니티 글은 근거로 쓰지 마세요. 확실하지 않으면 '확인불가'라고 쓰세요.
2. '상장폐지확정'은 거래소의 결정 공시 등 근거가 있을 때만 쓰세요.
3. 근거에는 공시 제목·날짜·사유를 한 줄로 쓰고, 투자 조언·전망·평가는 쓰지 마세요.
4. 특정 회사나 개인을 비방하는 표현을 쓰지 마세요.

[출력 형식 — 이 형식 외의 문장은 쓰지 마세요]
종목마다 정확히 한 줄이며, 칸은 | 로 구분합니다.
종목코드|판정|근거(한 줄)|기준일(YYYY-MM-DD, 모르면 -)|출처(공시명 또는 사이트)
예) 123456|거래정지|감사의견 거절로 매매거래 정지(사업보고서 감사의견 비적정)|2026-04-01|KIND 공시

[대상 종목]
{items}
"""


_DL_KEYWORDS = ("거래정지", "매매거래정지", "상장폐지", "정리매매", "관리종목", "불성실공시", "투자주의환기")


def _dl_walk_strings(obj, depth=0, path=""):
    if depth > 3:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _dl_walk_strings(v, depth + 1, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            yield from _dl_walk_strings(v, depth + 1, path)
    elif isinstance(obj, str):
        yield path, obj


def _dl_signals(basic, stale_days, include_caution, today):
    """네이버 기본정보(JSON)에서 신호를 뽑는다. 반환 (kind|None, [신호문장], 가격, 최근거래일)."""
    sig, kind = [], None
    price = 0
    try:
        price = int(str(basic.get("closePrice") or "0").replace(",", "") or 0)
    except Exception:
        price = 0
    last = ""
    lt = str(basic.get("localTradedAt") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", lt):
        last = lt[:10]
    for f in _naver_trading_status_flags(basic):
        sig.append("네이버 " + f)
        kind = "halt"
    for path, s in _dl_walk_strings(basic):
        for kw in _DL_KEYWORDS:
            if kw in s and len(s) <= 60:
                sig.append(f"네이버 표시: {path.split('.')[-1]}={s}")
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
        pct = float(basic.get("fluctuationsRatio"))
        if abs(pct) > DL_PCT_LIMIT:
            sig.append(f"하루 등락률 {pct:+.1f}% (가격제한폭 ±30% 초과 — 정리매매 또는 신규상장일 가능성)")
            kind = "delist" if kind in (None, "delist") else kind
    except Exception:
        pass
    if include_caution and 0 < price < 1000 and not kind:
        sig.append(f"현재가 {price:,}원 (동전주 구간 — 관리종목 사유가 될 수 있음)")
        kind = "caution"
    seen, out = set(), []
    for s in sig:
        if s not in seen:
            seen.add(s); out.append(s)
    return kind, out[:6], price, last


def _dl_universe():
    try:
        with sqlite3.connect(get_db()) as c:
            rows = c.execute("SELECT ticker, name, market FROM ticker_names").fetchall()
        return [(t, n or "", m or "") for t, n, m in rows if re.fullmatch(r"[0-9A-Z]{6}", t or "")]
    except Exception:
        return []


def _dl_scan_run(stale_days, include_caution):
    job = _DL_SCAN
    try:
        _ensure_v135_tables()
        uni = _dl_universe()
        job.update(total=len(uni), done=0, ok=0, flagged=0, error="")
        if not uni:
            job["error"] = "종목 목록이 비어 있어요. 첫 화면의 [종목목록 갱신]을 먼저 눌러 주세요."
            return
        today = _now_kst().date()
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def one(item):
            if job["cancel"]:
                return item, None
            return item, _naver_mobile_basic(item[0])

        results = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(one, it) for it in uni]
            for f in as_completed(futs):
                try:
                    it, basic = f.result()
                except Exception:
                    job["done"] += 1
                    continue
                job["done"] += 1
                if basic:
                    job["ok"] += 1
                    kind, sig, price, last = _dl_signals(basic, stale_days, include_caution, today)
                    results[it[0]] = (it, kind, sig, price, last)
        if job["cancel"]:
            job["error"] = "중단했어요(받아 온 결과까지만 반영하지 않고 버렸어요)."
            return
        job["flagged"] = sum(1 for v in results.values() if v[1])
        now = int(time.time())
        existing = {r[0]: r[1] for r in (_dbx("SELECT ticker, kind FROM delist_watch", fetch=True) or [])}
        for tk, (it, kind, sig, price, last) in results.items():
            if kind:
                _dbx("""INSERT INTO delist_watch(ticker,name,market,kind,signals,price,last_trade,first_seen,last_seen,active)
                        VALUES(?,?,?,?,?,?,?,?,?,1)
                        ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, market=excluded.market, kind=excluded.kind,
                          signals=excluded.signals, price=excluded.price, last_trade=excluded.last_trade,
                          last_seen=excluded.last_seen, active=1""",
                     (tk, it[1], it[2], kind, json.dumps(sig, ensure_ascii=False), price, last, now, now))
            elif tk in existing and existing[tk] != "manual":
                # 이번엔 신호가 없다 → 목록에서 내린다(AI·관리자 기록이 없으면 지운다). 받아 오지 못한 종목은 건드리지 않는다.
                _dbx("UPDATE delist_watch SET active=0, signals=?, last_seen=? WHERE ticker=?",
                     (json.dumps(["최근 스캔에서는 신호가 없었어요"], ensure_ascii=False), now, tk))
        _dbx("DELETE FROM delist_watch WHERE active=0 AND ai_verdict='' AND admin_state=''")
        if job["ok"] < len(uni) * 0.5:
            job["error"] = f"네이버 응답이 적었어요({job['ok']}/{len(uni)}). 결과가 불완전할 수 있으니 잠시 뒤 다시 실행해 보세요."
    except Exception as e:
        job["error"] = f"스캔 중 오류: {type(e).__name__}: {str(e)[:120]}"
        print(f"[관리자메뉴] 스캔 오류: {e}")
    finally:
        job["running"] = False
        job["finished"] = int(time.time())
        try:
            setting_set("delist_last_scan", json.dumps({k: job[k] for k in ("total", "ok", "flagged", "finished", "error")}, ensure_ascii=False))
        except Exception:
            pass


def _dl_row_out(r):
    try:
        r["signals"] = json.loads(r.get("signals") or "[]")
    except Exception:
        r["signals"] = []
    return r


DL_COLS = ("ticker", "name", "market", "kind", "signals", "price", "last_trade", "first_seen", "last_seen", "active",
           "ai_verdict", "ai_basis", "ai_source", "ai_date", "ai_at", "ai_mode", "admin_state", "admin_label", "admin_note", "admin_at")


def _dl_items_text(rows):
    lines = []
    for r in rows:
        sig = "; ".join(r["signals"]) if isinstance(r["signals"], list) else str(r["signals"])
        lines.append(f"{r['ticker']} | {r['name']} | {r['market']} | 자동신호: {sig or '-'} | 최근가 {int(r['price'] or 0):,}원 | 마지막 거래일 {r['last_trade'] or '-'}")
    return "\n".join(lines)


def _dl_pick(tickers, scope):
    """AI에 보낼 종목 고르기: 직접 고른 것 또는 '아직 AI 검증 안 한 후보' 전체."""
    if tickers:
        tks = [normalize_ticker(t) for t in tickers[:400]]
        tks = [t for t in tks if t]
        if not tks:
            return []
        q = ",".join("?" * len(tks))
        rows = _dbrows(f"SELECT {','.join(DL_COLS)} FROM delist_watch WHERE ticker IN ({q})", DL_COLS, tks)
    else:
        rows = _dbrows(f"SELECT {','.join(DL_COLS)} FROM delist_watch WHERE active=1 AND ai_verdict='' AND admin_state='' "
                       "ORDER BY (kind='delist') DESC, ticker", DL_COLS)
    rows = [_dl_row_out(r) for r in rows][:DL_AI_MAX_PER_RUN]
    return rows


def _dl_build_prompts(rows, body=None):
    body = body or prompt_get("delist_verify")
    today = _now_kst().strftime("%Y-%m-%d")
    out = []
    for i in range(0, len(rows), DL_CHUNK):
        part = rows[i:i + DL_CHUNK]
        out.append({"n": len(out) + 1, "count": len(part), "tickers": [r["ticker"] for r in part],
                    "prompt": _prompt_fill(body, today=today, count=len(part), items=_dl_items_text(part))})
    return out


_DL_SYN = (
    ("상장폐지확정", ("상장폐지확정", "상장폐지 확정", "상폐확정", "상장폐지결정", "상장폐지 결정", "상장폐지")),
    ("정리매매", ("정리매매",)),
    ("거래정지", ("거래정지", "매매거래정지", "매매정지")),
    ("관리종목", ("관리종목", "관리 종목")),
    ("확인불가", ("확인불가", "확인 불가", "알 수 없", "확인되지", "불명")),
)


def _dl_norm_verdict(s):
    s = re.sub(r"[\*\`_\[\]\(\)]", "", (s or "")).strip()
    if s in DL_VERDICTS:
        return s
    compact = s.replace(" ", "")
    for label, keys in _DL_SYN:
        for k in keys:
            if k.replace(" ", "") in compact:
                return label
    if compact.startswith("정상") or "이상없" in compact:
        return "정상"
    return ""


def dl_parse_ai_text(text):
    """AI 답변 → [{ticker, verdict, basis, date, source}] 와 읽지 못한 줄 수. '|' 로 칸을 나눈 줄만 읽는다."""
    rows, bad = [], 0
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or "|" not in raw.replace("｜", "|"):
            continue
        cells = [x.strip() for x in raw.replace("｜", "|").strip("|").split("|")]
        cells = [re.sub(r"\*\*|`", "", x).strip() for x in cells]
        if len(cells) < 2:
            continue
        m = re.search(r"\b([0-9A-Z]{6})\b", cells[0])
        if not m or cells[0].startswith("종목코드") or set(cells[0]) <= set("-: "):
            continue
        verdict = _dl_norm_verdict(cells[1])
        if not verdict:
            bad += 1
            continue
        date = cells[3] if len(cells) > 3 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[3]) else ""
        clean = lambda s, n: re.sub(r"[<>]", "", s)[:n]
        rows.append({"ticker": m.group(1), "verdict": verdict, "basis": clean(cells[2] if len(cells) > 2 else "", 200),
                     "date": date, "source": clean(cells[4] if len(cells) > 4 else "", 80)})
    return rows, bad


def dl_apply_ai(rows, mode):
    """읽은 결과를 후보 목록에 저장. 목록에 없는 종목은 무시."""
    known = {r[0] for r in (_dbx("SELECT ticker FROM delist_watch", fetch=True) or [])}
    now, applied, unknown = int(time.time()), 0, 0
    for r in rows:
        if r["ticker"] not in known:
            unknown += 1
            continue
        _dbx("UPDATE delist_watch SET ai_verdict=?, ai_basis=?, ai_source=?, ai_date=?, ai_at=?, ai_mode=? WHERE ticker=?",
             (r["verdict"], r["basis"], r["source"], r["date"], now, mode, r["ticker"]))
        applied += 1
    return applied, unknown


def _dl_ai_job(jid, rows):
    job = _AIJOBS[jid]
    applied_total = unknown_total = 0
    try:
        prompts = _dl_build_prompts(rows)
        job["total"] = len(prompts)
        for p in prompts:
            try:
                text, note = ai_complete(p["prompt"], max_tokens=4096)
                parsed, bad = dl_parse_ai_text(text)
                a, u = dl_apply_ai(parsed, "auto")
                applied_total += a
                unknown_total += u
                if note and note not in job["msg"]:
                    job["msg"] = (job["msg"] + " " + note).strip()
                if bad or a < p["count"]:
                    job["errors"].append(f"{p['n']}번째 묶음: {p['count']}개 중 {a}개만 읽었어요")
            except Exception as e:
                job["errors"].append(f"{p['n']}번째 묶음 실패: {str(e)[:120]}")
            job["done"] += 1
            time.sleep(1)
        job["result"] = {"applied": applied_total, "unknown": unknown_total, "requested": len(rows)}
        job["status"] = "done"
    except Exception as e:
        job["errors"].append(f"{type(e).__name__}: {str(e)[:120]}")
        job["status"] = "error"


def _dl_enhance_stats():
    try:
        rows = _dbx("SELECT ai_verdict, COUNT(*) FROM delist_watch WHERE ai_verdict<>'' GROUP BY ai_verdict", fetch=True) or []
        parts = [f"{v} {n}건" for v, n in rows]
        last = setting_get("delist_last_parse", "")
        s = "AI 판정 분포: " + (", ".join(parts) if parts else "아직 없음")
        return s + (f"\n마지막 붙여넣기 결과: {last}" if last else "")
    except Exception:
        return "통계 없음"


@bp.route("/admin/api/delist/list")
def admin_api_delist_list():
    deny = _admin_deny()
    if deny:
        return deny
    rows = []
    if _ensure_v135_tables():
        rows = [_dl_row_out(r) for r in _dbrows(
            f"SELECT {','.join(DL_COLS)} FROM delist_watch WHERE active=1 OR admin_state<>'' OR ai_verdict<>'' "
            "ORDER BY (kind='delist') DESC, last_seen DESC, ticker LIMIT 800", DL_COLS)]
    try:
        last = json.loads(setting_get("delist_last_scan", "") or "{}")
    except Exception:
        last = {}
    for r in rows:
        r["first_seen"] = _kst_str(r["first_seen"]); r["last_seen"] = _kst_str(r["last_seen"])
        r["ai_at"] = _kst_str(r["ai_at"]) if r["ai_at"] else ""
        r["admin_at"] = _kst_str(r["admin_at"]) if r["admin_at"] else ""
    return _admin_json({"rows": rows, "last_scan": last, "scan": {k: _DL_SCAN[k] for k in ("running", "total", "done", "ok", "flagged", "error")},
                        "universe": len(_dl_universe()), "verdicts": list(DL_VERDICTS), "public_labels": list(DL_PUBLIC_LABELS),
                        "public": menu_visible("delist")})


@bp.route("/admin/api/delist/scan", methods=["POST"])
def admin_api_delist_scan():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if _DL_SCAN["running"]:
        return _admin_json({"error": "이미 스캔 중이에요."}, 409)
    if not _ensure_v135_tables():
        return _admin_json({"error": "저장소를 준비하지 못했어요."}, 500)
    stale = int(setting_get("delist_stale_days") or 10)
    caution = setting_get("delist_include_caution") == "1"
    _DL_SCAN.update(running=True, cancel=False, total=0, done=0, ok=0, flagged=0, started=int(time.time()), error="")
    threading.Thread(target=_dl_scan_run, args=(stale, caution), daemon=True).start()
    _alog("delist_scan", f"stale={stale} caution={int(caution)}")
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
    return _admin_json({k: _DL_SCAN[k] for k in ("running", "total", "done", "ok", "flagged", "error")})


@bp.route("/admin/api/delist/mark", methods=["POST"])
def admin_api_delist_mark():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    tks = [normalize_ticker(t) for t in (d.get("tickers") or [])[:400]]
    tks = [t for t in tks if t]
    state = str(d.get("state", ""))
    label = str(d.get("label", "")).strip()
    note = re.sub(r"[<>]", "", str(d.get("note", "")))[:120]
    if not tks or state not in ("confirmed", "excluded", ""):
        return _admin_json({"error": "요청이 올바르지 않아요."}, 400)
    if state == "confirmed" and label not in DL_PUBLIC_LABELS:
        return _admin_json({"error": "확정할 때는 판정(거래정지·관리종목·상장폐지확정·정리매매) 중 하나를 골라 주세요."}, 400)
    now = int(time.time())
    n = 0
    for t in tks:
        _dbx("UPDATE delist_watch SET admin_state=?, admin_label=?, admin_note=?, admin_at=? WHERE ticker=?",
             (state, label if state == "confirmed" else "", note, now if state else 0, t))
        n += 1
    _alog("delist_mark", f"{state or 'clear'} {label} n={n}")
    return _admin_json({"ok": True, "n": n})


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
    _dbx("""INSERT INTO delist_watch(ticker,name,market,kind,signals,first_seen,last_seen,active) VALUES(?,?,?,?,?,?,?,1)
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


@bp.route("/admin/api/delist/ai-prompt", methods=["POST"])
def admin_api_delist_ai_prompt():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    body = str(d.get("body") or "").strip() or None
    if body:
        err = _prompt_check("delist_verify", body)
        if err:
            return _admin_json({"error": err}, 400)
    rows = _dl_pick(d.get("tickers") or [], d.get("scope"))
    if not rows:
        return _admin_json({"error": "AI에 보낼 후보가 없어요(먼저 스캔하거나 종목을 고르세요)."}, 400)
    return _admin_json({"chunks": _dl_build_prompts(rows, body), "total": len(rows), "max": DL_AI_MAX_PER_RUN})


@bp.route("/admin/api/delist/ai-paste", methods=["POST"])
def admin_api_delist_ai_paste():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    text = str(d.get("text") or "")[:60000]
    rows, bad = dl_parse_ai_text(text)
    names = {r[0]: r[1] for r in (_dbx("SELECT ticker, name FROM delist_watch", fetch=True) or [])}
    for r in rows:
        r["name"] = names.get(r["ticker"], "")
        r["known"] = r["ticker"] in names
    out = {"rows": rows, "bad": bad, "known": sum(1 for r in rows if r["known"])}
    if not d.get("dry"):
        applied, unknown = dl_apply_ai(rows, "manual")
        out.update(applied=applied, unknown=unknown)
        try:
            setting_set("delist_last_parse", f"{len(rows)}줄 읽음, 못 읽은 줄 {bad}, 목록에 없는 종목 {unknown}")
        except Exception:
            pass
        _alog("delist_ai_paste", f"applied={applied} bad={bad}")
    return _admin_json(out)


@bp.route("/admin/api/delist/ai-auto", methods=["POST"])
def admin_api_delist_ai_auto():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if not ai_pick_provider():
        return _admin_json({"error": "서버에 AI API 키가 없어요. 수동 방식을 쓰거나 Render 환경변수에 키를 넣어 주세요."}, 400)
    if _job_busy("ai"):
        return _admin_json({"error": "이미 AI 검증이 진행 중이에요."}, 409)
    rows = _dl_pick(_json_body().get("tickers") or [], _json_body().get("scope"))
    if not rows:
        return _admin_json({"error": "AI에 보낼 후보가 없어요."}, 400)
    jid = _job_new("ai", total=(len(rows) + DL_CHUNK - 1) // DL_CHUNK)
    threading.Thread(target=_dl_ai_job, args=(jid, rows), daemon=True).start()
    _alog("delist_ai_auto", f"n={len(rows)} provider={ai_pick_provider()}")
    return _admin_json({"job": jid, "n": len(rows)})


@bp.route("/api/delist/public")
def api_delist_public():
    if not menu_visible("delist"):
        return "not found", 404
    rows = []
    if _ensure_v135_tables():
        rows = _dbrows("SELECT ticker, name, market, admin_label, admin_note, admin_at FROM delist_watch "
                       "WHERE admin_state='confirmed' ORDER BY admin_at DESC, ticker LIMIT 500",
                       ("ticker", "name", "market", "label", "note", "at"))
    for r in rows:
        r["at"] = datetime.fromtimestamp(int(r["at"]), _now_kst().tzinfo).strftime("%Y-%m-%d") if r["at"] else ""
    resp = jsonify({"rows": rows})
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


DELIST_PUBLIC_HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>거래정지·상장폐지 종목 · 종목분석 미니</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f1f5f9;font-family:system-ui,'Malgun Gothic',sans-serif;color:#1f2937}
header{background:#0f172a;color:#fff;padding:12px 16px;display:flex;gap:10px;align-items:center}header a{color:#93c5fd;text-decoration:none;font-size:13px}header b{flex:1}
.w{max-width:860px;margin:0 auto;padding:14px 16px 40px}.note{background:#fff7ed;border:1px solid #fdba74;border-radius:12px;padding:12px 14px;font-size:13px;line-height:1.6;margin-bottom:12px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;font-size:14px}td,th{padding:9px 10px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}th{background:#f8fafc;font-size:12.5px}
.tag{display:inline-block;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:700;background:#fee2e2;color:#b91c1c}.sub{color:#64748b;font-size:12px}a.s{color:#2563eb;text-decoration:none}
.empty{background:#fff;border-radius:12px;padding:22px;text-align:center;color:#64748b}
</style></head><body><header><b>🚫 거래정지·상장폐지 종목</b><a href="/">← 종목분석으로</a></header>
<div class="w"><div class="note">운영자가 거래소 공시 등을 확인해 직접 확정한 종목만 보여드립니다. <b>실제 상태는 바뀔 수 있으므로 투자 전에 반드시 한국거래소(KIND)·DART 공시로 다시 확인하세요.</b> 투자 권유가 아니며, 투자 판단과 책임은 본인에게 있습니다.</div>
<div id="box"><div class="empty">불러오는 중…</div></div></div>
<script>
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
fetch('/api/delist/public').then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){
 var b=document.getElementById('box');b.innerHTML='';
 if(!d.rows.length){b.appendChild(el('div','empty','현재 확정된 종목이 없습니다.'));return}
 var t=el('table'),h=el('tr');['종목','상태','메모','확정일'].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 d.rows.forEach(function(r){var tr=el('tr'),td=el('td');var a=el('a','s',r.name+' ('+r.ticker+')');a.href='/?t='+encodeURIComponent(r.ticker);td.appendChild(a);td.appendChild(el('div','sub',r.market||''));tr.appendChild(td);
  var s=el('td');s.appendChild(el('span','tag',r.label));tr.appendChild(s);tr.appendChild(el('td','sub',r.note||''));tr.appendChild(el('td','sub',r.at||''));t.appendChild(tr)});
 b.appendChild(t)}).catch(function(){var b=document.getElementById('box');b.innerHTML='';b.appendChild(el('div','empty','지금은 볼 수 없는 화면입니다.'))});
</script></body></html>"""


@bp.route("/delist")
def delist_public_page():
    if not menu_visible("delist"):
        return "not found", 404
    resp = app.make_response(DELIST_PUBLIC_HTML)
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


# ── 표 만들기 · 등록 ──
def _ensure_delist_table(cur, use_pg):
    cur.execute("""CREATE TABLE IF NOT EXISTS delist_watch(
        ticker TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', market TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT '', signals TEXT NOT NULL DEFAULT '', price BIGINT NOT NULL DEFAULT 0,
        last_trade TEXT NOT NULL DEFAULT '', first_seen BIGINT NOT NULL DEFAULT 0, last_seen BIGINT NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        ai_verdict TEXT NOT NULL DEFAULT '', ai_basis TEXT NOT NULL DEFAULT '', ai_source TEXT NOT NULL DEFAULT '',
        ai_date TEXT NOT NULL DEFAULT '', ai_at BIGINT NOT NULL DEFAULT 0, ai_mode TEXT NOT NULL DEFAULT '',
        admin_state TEXT NOT NULL DEFAULT '', admin_label TEXT NOT NULL DEFAULT '', admin_note TEXT NOT NULL DEFAULT '',
        admin_at BIGINT NOT NULL DEFAULT 0)""")


def _valid_days(k, v):
    return str(int(v)) if v.isdigit() and 3 <= int(v) <= 60 else None


def _valid_bool(k, v):
    return v if v in ("0", "1") else None


def register():
    global _AIJOBS
    _AIJOBS = C._AIJOBS
    C.register_menu({"id": "delist", "label": "거래정지·상폐", "icon": "🚫", "public_path": "/delist",
                     "admin_path": "/admin#dl", "desc": "거래정지·상장폐지(확정·정리매매) 종목 목록",
                     "access": "admin"})
    C.register_settings({"delist_stale_days": "10", "delist_include_caution": "0"},
                        {"delist_stale_days": _valid_days, "delist_include_caution": _valid_bool})
    C.register_prompt("delist_verify", {
        "title": "거래정지·상폐 검증 프롬프트", "default": DELIST_VERIFY_DEFAULT,
        "required": ["{items}"], "must_have": ["종목코드|판정"],
        "vars": "{today}=오늘 날짜 · {count}=종목 수 · {items}=대상 종목 목록(필수)",
        "desc": "후보 종목을 AI에게 확인시킬 때 쓰는 프롬프트(수동·자동 공통).",
        "stats_fn": _dl_enhance_stats})
    C.register_table_hook(_ensure_delist_table)
    return bp
