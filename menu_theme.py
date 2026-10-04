"""🏷 네이버테마 — 네이버 증권 테마의 오늘 등락률 순위, 테마 안 종목, 테마별 수급, 일별 추이를 보여 주고 AI 해설·이미지·블로그 글까지 만든다.

원본 프로그램의 네이버 테마 가져오기를 별도 메뉴로 분리했다(예전에는 수급분석 화면 안의 가져오기 상자에 있었다).

자료
  · collect_theme_list  테마 번호·이름·종목 수·오늘 등락률·상승/하락/보합 종목 수   ← [🏷 테마 가져오기] (menu_collect 의 가져오기 기능을 그대로 쓴다)
  · stock_theme_map     종목-테마 연결(theme_type='naver')
  · theme_day           가져올 때마다 하루 한 줄씩 쌓는 테마별 등락률 이력(연속 강세·순위 변화·일별 추이)
  · stock_price_cache / investor_scan_cache  테마 안 종목의 등락률과 외국인·기관·개인 수급(시가총액 상위 종목만 있음)

회원 화면은 기능별 등급(list·detail·flow·trend·ai·img·exp·guide)으로 열고, 가져오기·AI 저장·블로그 글·점검은 관리자 전용이다.
"""
import json
import re
import time

from flask import Blueprint, request

from menu_ctx import C
import menu_blog as B

bp = Blueprint("theme", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "prompt_get", "_now_kst", "setting_get", "setting_set")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

MENU = "theme"
KEY_AI = "theme_ai_last"
BLOG_SECS = ("stats", "top", "bottom", "leaders", "flow", "ai")
_CACHE = {"at": 0.0, "d": None}
CACHE_TTL = 20


# ══════════════════════════════════════════════════════════════
# 작은 도구
# ══════════════════════════════════════════════════════════════
def _s(x, n=80):
    return re.sub(r"[\x00-\x1f]", "", str(x or "")).strip()[:n]


def _today():
    return _now_kst().strftime("%Y-%m-%d")


def _n(x):
    try:
        v = float(x)
        return 0 if v != v or v in (float("inf"), float("-inf")) else v
    except Exception:
        return 0


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


def _eok(won):
    return round(float(won or 0) / 1e8, 1)


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
        print(f"[네이버테마] 기록 저장 실패(무시): {e}")


# ══════════════════════════════════════════════════════════════
# 자료 읽기 — 테마 목록 + 일별 이력 + 종목 연결(20초 캐시)
# ══════════════════════════════════════════════════════════════
def _streak(vals):
    """등락률 목록(오래된 → 최근)의 끝에서부터 같은 부호가 며칠 이어졌는지(+면 강세, −면 약세)."""
    k, sign = 0, 0
    for v in reversed(vals):
        sg = 1 if v > 0 else (-1 if v < 0 else 0)
        if sg == 0:
            break
        if sign == 0:
            sign = sg
        if sg != sign:
            break
        k += 1
    return k * sign


def _load(force=False):
    now = time.time()
    d0 = _CACHE["d"]
    if not force and d0 is not None and now - _CACHE["at"] < (CACHE_TTL if d0["themes"] else 2):
        return d0
    out = {"themes": [], "hist": {}, "dates": [], "members": {}, "price": {}, "inv": {}, "base_date": "", "fetched_at": ""}
    rows = _try("SELECT l.no,l.name,l.total,l.change_rate,l.rise,l.fall,l.steady,l.fetched_at FROM collect_theme_list l ORDER BY l.change_rate DESC")
    if rows:
        out["themes"] = [{"no": int(r[0] or 0), "name": _s(r[1], 40), "total": int(r[2] or 0), "rate": round(_n(r[3]), 2), "rise": int(r[4] or 0),
                          "fall": int(r[5] or 0), "steady": int(r[6] or 0)} for r in rows]
        out["fetched_at"] = max((str(r[7] or "") for r in rows), default="")
    hs = _try("SELECT date,no,rate FROM theme_day ORDER BY date") or []
    dates = sorted({str(r[0]) for r in hs})[-40:]
    ds = set(dates)
    for d_, no, rt in hs:
        if str(d_) in ds:
            out["hist"].setdefault(int(no), {})[str(d_)] = round(_n(rt), 2)
    out["dates"] = dates
    mem = _try("SELECT theme,ticker,name FROM stock_theme_map WHERE theme_type='naver'") or []
    for th, tk, nm in mem:
        out["members"].setdefault(str(th), []).append((str(tk), str(nm)))
    pr = _try("SELECT ticker,name,market,price,day_pct,cap_num FROM stock_price_cache",
              "SELECT ticker,name,market,price,NULL,NULL FROM stock_price_cache") or []
    for tk, nm, mk, pc, dp, cap in pr:
        out["price"][str(tk)] = {"name": nm, "market": mk or "", "price": int(_n(pc)), "pct": (None if dp is None else round(_n(dp), 2)), "cap": int(_n(cap))}
    inv = _try("SELECT ticker,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,retail_1,retail_5,retail_20,base_date FROM investor_scan_cache",
               "SELECT ticker,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,0,0,0,base_date FROM investor_scan_cache",
               "SELECT ticker,foreign_1,inst_1,foreign_5,inst_5,foreign_20,inst_20,0,0,0,'' FROM investor_scan_cache") or []
    for r in inv:
        out["inv"][str(r[0])] = {"f1": _eok(r[1]), "i1": _eok(r[2]), "f5": _eok(r[3]), "i5": _eok(r[4]), "f20": _eok(r[5]), "i20": _eok(r[6]),
                                 "r1": _eok(r[7]), "r5": _eok(r[8]), "r20": _eok(r[9])}
        if str(r[10] or "") > out["base_date"]:
            out["base_date"] = str(r[10] or "")
    # 일별 이력으로 연속 일수·전일 값 붙이기
    for t in out["themes"]:
        hh = out["hist"].get(t["no"], {})
        vals = [hh[d] for d in dates if d in hh]
        t["streak"] = _streak(vals) if vals else (1 if t["rate"] > 0 else (-1 if t["rate"] < 0 else 0))
        t["prev"] = vals[-2] if len(vals) >= 2 else None
        t["days"] = len(vals)
    for rank, t in enumerate(out["themes"], 1):
        t["rank"] = rank
    with_prev = sorted([t for t in out["themes"] if t["prev"] is not None], key=lambda x: -x["prev"])
    pr_rank = {t["no"]: i for i, t in enumerate(with_prev, 1)}
    for t in out["themes"]:
        t["rank_prev"] = pr_rank.get(t["no"])
    _CACHE["d"], _CACHE["at"] = out, now
    return out


def _empty():
    return _admin_json({"ok": True, "empty": True, "msg": "네이버 테마 자료가 아직 없어요. 관리자가 이 화면 아래 [🏷 테마 가져오기]를 실행하면 보여요."})


def _members_rows(d, name):
    rows = []
    for tk, nm in d["members"].get(name, []):
        p = d["price"].get(tk) or {}
        iv = d["inv"].get(tk)
        row = {"ticker": tk, "name": p.get("name") or nm, "market": p.get("market") or "", "price": p.get("price") or 0, "pct": p.get("pct"), "cap": p.get("cap") or 0, "has_inv": bool(iv)}
        for k in ("f1", "i1", "f5", "i5", "f20", "i20", "r1", "r5", "r20"):
            row[k] = (iv or {}).get(k, 0)
        rows.append(row)
    return rows


def _flow_rank(d, per, side, minn, top):
    out = []
    for t in d["themes"]:
        mem = [r for r in _members_rows(d, t["name"]) if r["has_inv"]]
        if len(mem) < minn:
            continue
        f, i = sum(r["f" + per] for r in mem), sum(r["i" + per] for r in mem)
        r_ = sum(r["r" + per] for r in mem)
        c = f + i
        if (side == "buy" and c <= 0) or (side == "sell" and c >= 0):
            continue
        out.append({"no": t["no"], "name": t["name"], "rate": t["rate"], "n": len(mem), "total": len(d["members"].get(t["name"], [])), "f": round(f, 1), "i": round(i, 1),
                    "r": round(r_, 1), "c": round(c, 1), "pos": sum(1 for r in mem if r["f" + per] + r["i" + per] > 0)})
    out.sort(key=lambda x: (-x["c"] if side == "buy" else x["c"], x["name"]))
    return out[:top]


# ══════════════════════════════════════════════════════════════
# 조회 API
# ══════════════════════════════════════════════════════════════
@bp.route("/admin/api/theme/list", methods=["GET"])
def api_list():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["themes"]:
        return _empty()
    q = _s(request.args.get("q"), 30).lower()
    sort = _arg("sort", ("rate", "rise", "streak", "total"), "rate")
    side = _arg("side", ("up", "down", "all"), "all")
    top = _iarg("top", 5, 300, 60)
    its = [t for t in d["themes"] if (not q or q in t["name"].lower())]
    if side == "up":
        its = [t for t in its if t["rate"] > 0]
    elif side == "down":
        its = [t for t in its if t["rate"] < 0]
    key = {"rate": lambda t: (-t["rate"], t["name"]), "rise": lambda t: (-t["rise"], t["name"]), "streak": lambda t: (-abs(t["streak"]), -t["rate"], t["name"]), "total": lambda t: (-t["total"], t["name"])}[sort]
    its = sorted(its, key=key)
    if side == "down" and sort == "rate":
        its = sorted(its, key=lambda t: (t["rate"], t["name"]))
    allr = d["themes"]
    up = sum(1 for t in allr if t["rate"] > 0)
    dn = sum(1 for t in allr if t["rate"] < 0)
    avg = round(sum(t["rate"] for t in allr) / len(allr), 2) if allr else 0
    return _admin_json({"ok": True, "items": its[:top], "matched": len(its), "count": len(allr), "up": up, "down": dn, "avg": avg, "dates": len(d["dates"]),
                        "fetched_at": d["fetched_at"], "base_date": d["base_date"], "sort": sort, "side": side})


@bp.route("/admin/api/theme/detail", methods=["GET"])
def api_detail():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["themes"]:
        return _empty()
    try:
        no = int(request.args.get("no") or 0)
    except Exception:
        no = 0
    t = next((x for x in d["themes"] if x["no"] == no), None)
    if not t:
        return _admin_json({"error": "없는 테마예요."}, 404)
    rows = _members_rows(d, t["name"])
    rows.sort(key=lambda r: (-(r["pct"] if r["pct"] is not None else -999), r["ticker"]))
    inv = [r for r in rows if r["has_inv"]]
    sums = {k: round(sum(r[k] for r in inv), 1) for k in ("f1", "i1", "f5", "i5", "f20", "i20", "r1", "r5", "r20")}
    pcts = [r["pct"] for r in rows if r["pct"] is not None]
    hh = d["hist"].get(no, {})
    return _admin_json({"ok": True, "theme": t, "items": rows[:80], "total": len(rows), "inv_n": len(inv), "sums": sums, "base_date": d["base_date"],
                        "avg_pct": (round(sum(pcts) / len(pcts), 2) if pcts else None), "up_n": sum(1 for p in pcts if p > 0), "down_n": sum(1 for p in pcts if p < 0),
                        "hist": {"dates": [x for x in d["dates"] if x in hh], "rates": [hh[x] for x in d["dates"] if x in hh]}})


@bp.route("/admin/api/theme/flow", methods=["GET"])
def api_flow():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["themes"]:
        return _empty()
    if not d["inv"]:
        return _admin_json({"ok": True, "empty": True, "msg": "종목 수급 자료가 없어요. 관리자가 📊 시장수급 메뉴에서 [📥 종목 수급 가져오기]를 실행하면 테마별 수급이 계산돼요."})
    per = _arg("period", ("1", "5", "20"), "5")
    side = _arg("side", ("buy", "sell"), "buy")
    items = _flow_rank(d, per, side, _iarg("min", 1, 20, 2), _iarg("top", 5, 60, 30))
    return _admin_json({"ok": True, "items": items, "period": per, "side": side, "base_date": d["base_date"], "inv_stocks": len(d["inv"])})


@bp.route("/admin/api/theme/history", methods=["GET"])
def api_history():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["themes"]:
        return _empty()
    days = _iarg("days", 3, 40, 10)
    side = _arg("side", ("up", "down"), "up")
    n = _iarg("n", 3, 10, 6)
    dates = d["dates"][-days:]
    if len(dates) < 2:
        return _admin_json({"ok": True, "few": True, "dates": dates, "series": [], "msg": "테마 등락률은 가져올 때마다 하루씩 쌓여요. 이틀 이상 쌓이면 일별 추이가 그려져요(지금 %d일)." % len(dates)})
    pool = sorted(d["themes"], key=lambda t: (-t["rate"] if side == "up" else t["rate"], t["name"]))[:n]
    series = []
    for t in pool:
        hh = d["hist"].get(t["no"], {})
        series.append({"no": t["no"], "name": t["name"], "rates": [hh.get(x) for x in dates], "latest": t["rate"], "streak": t["streak"]})
    return _admin_json({"ok": True, "dates": dates, "series": series, "side": side})


# ══════════════════════════════════════════════════════════════
# AI 프롬프트(수동 AI — 서버가 AI를 부르지 않는다)
# ══════════════════════════════════════════════════════════════
TH_DEFAULT = """아래는 오늘 한국 주식시장의 네이버 증권 테마별 등락률과 수급 자료입니다. (기준일 {base_date})

[테마 자료]
{summary}

다음 형식으로 한국어로 설명해 주세요. 주식 초보도 이해하도록 쉬운 말로 쓰고, [테마 자료]에 없는 숫자·뉴스·이유는 지어내지 마세요.
특정 종목이나 테마의 매수·매도를 권하거나 목표가를 제시하지 말고, 관찰 중심("~로 보입니다")으로 쓰세요.

## 🔥 오늘 한 줄 요약
오늘 어떤 테마가 강했고 어떤 테마가 약했는지 한두 문장

## 📈 강세 테마 읽기
강세 테마 3~4개를 골라 각각 2~3줄: 등락률, 상승 종목 비율, 연속 강세 여부, 대표 종목(자료에 있는 것만)

## 📉 약세 테마 읽기
약세 테마 2~3개를 간단히

## 💰 수급으로 본 테마
수급 자료가 있으면 외국인·기관이 몰린 테마와 등락률이 같은 방향인지 비교(없으면 이 항목은 생략)

## 🔎 내일 확인할 점
오늘 흐름이 이어지는지 볼 때 같이 확인하면 좋은 자료(공시·실적·거래대금 등) 2~3가지

## ⚠ 유의사항
테마는 단기 관심이 몰리는 묶음이라 변동이 크고 같은 테마 안에서도 종목별 차이가 크다는 점, 이 글은 공개 자료를 정리한 참고용이며 투자 권유가 아니고 판단과 책임은 이용자 본인에게 있다는 점을 한두 줄로.

마지막에 아래 형식으로 블로그 제목 후보를 3개 제안해 주세요.
[블로그 제목 후보]
- 제목1
- 제목2
- 제목3
"""


def _leaders(d, name, n=3):
    rows = [r for r in _members_rows(d, name) if r["pct"] is not None]
    rows.sort(key=lambda r: (-r["pct"], r["ticker"]))
    return rows[:n]


def _summary_text(d):
    th = d["themes"]
    up = sum(1 for t in th if t["rate"] > 0)
    dn = sum(1 for t in th if t["rate"] < 0)
    avg = sum(t["rate"] for t in th) / len(th) if th else 0
    L = ["[전체] 테마 %d개 · 상승 %d · 하락 %d · 평균 %s" % (len(th), up, dn, _pct(avg))]

    def line(i, t):
        ld = _leaders(d, t["name"], 3)
        st = ""
        if abs(t["streak"]) >= 2:
            st = " · %d일 연속 %s" % (abs(t["streak"]), "강세" if t["streak"] > 0 else "약세")
        rk = ""
        if t.get("rank_prev"):
            rk = " · 전일 %d위→%d위" % (t["rank_prev"], t["rank"])
        lead = (" · 대표: " + ", ".join("%s %s" % (x["name"], _pct(x["pct"])) for x in ld)) if ld else ""
        return "%d. %s %s (상승 %d·하락 %d·전체 %d%s%s)%s" % (i, t["name"], _pct(t["rate"]), t["rise"], t["fall"], t["total"], st, rk, lead)
    L.append("[강세 테마 TOP8]")
    L += [line(i, t) for i, t in enumerate(th[:8], 1)]
    bt = [t for t in reversed(th[-5:]) if t["rate"] < 0]
    if bt:
        L.append("[약세 테마 BOTTOM5]")
        L += [line(i, t) for i, t in enumerate(bt, 1)]
    if d["inv"]:
        fl = _flow_rank(d, "5", "buy", 2, 6)
        if fl:
            L.append("[수급 상위 테마 — 최근 5일 외국인+기관 순매수, 수집 종목 기준]")
            for i, x in enumerate(fl, 1):
                L.append("%d. %s 외국인 %s · 기관 %s · 개인 %s (수급 자료 %d종목, 오늘 %s)" % (i, x["name"], _fmt_eok(x["f"]), _fmt_eok(x["i"]), _fmt_eok(x["r"]), x["n"], _pct(x["rate"])))
        sl = _flow_rank(d, "5", "sell", 2, 4)
        if sl:
            L.append("[수급 이탈 테마 — 최근 5일 외국인+기관 순매도]")
            for i, x in enumerate(sl, 1):
                L.append("%d. %s 외국인 %s · 기관 %s (오늘 %s)" % (i, x["name"], _fmt_eok(x["f"]), _fmt_eok(x["i"]), _pct(x["rate"])))
    return "\n".join(L)


def _base_label(d):
    return (d["fetched_at"] or "")[:10] or _today()


@bp.route("/admin/api/theme/prompt", methods=["GET"])
def api_prompt():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load()
    if not d["themes"]:
        return _empty()
    base = _base_label(d)
    body = prompt_get("theme_ai") or TH_DEFAULT
    for k, v in (("{summary}", _summary_text(d)), ("{base_date}", base), ("{today}", _today())):
        body = body.replace(k, v)
    return _admin_json({"ok": True, "prompt": body, "label": "네이버 테마 %s" % base, "base_date": base})


def _ai_get():
    d = _json_get(KEY_AI)
    return d if isinstance(d, dict) else {}


@bp.route("/admin/api/theme/ai", methods=["GET"])
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


@bp.route("/admin/api/theme/ai", methods=["POST"])
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
    _alog("theme_ai_save", "len=%d" % len(text))
    return _admin_json({"ok": True, "date": rec["date"], "at": rec["at"], "len": len(text)})


# ══════════════════════════════════════════════════════════════
# 블로그 글 (관리자 전용)
# ══════════════════════════════════════════════════════════════
_TITLE_BLOCK = re.compile(r"^[ \t]*\[블로그\s*제목\s*후보[^\]]*\][ \t]*\n(?:[ \t]*(?:[-•*·]|\d+[.)])[ \t]*.+\n?)*", re.M)


def _split_ai(text):
    text = str(text or "").replace("\r", "")
    return _TITLE_BLOCK.sub("", text).strip(), B.extract_titles(text)


def _td(txt, w, align="right", color="#111827", bold=False):
    return ('<td width="%d%%" align="%s" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:12.5px;%scolor:%s;white-space:nowrap;">%s</td>'
            % (w, align, "font-weight:800;" if bold else "", color, txt))


def _th(txt, w, align="right"):
    return '<th width="%d%%" align="%s" style="padding:7px 4px;font-size:12px;color:#475569;background-color:#f1f5f9;border-bottom:2px solid #e2e8f0;white-space:nowrap;">%s</th>' % (w, align, txt)


def _tbl(inner):
    return '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;' + B.FONT + '">' + inner + "</table>"


def _theme_table(items, accent_title, color):
    trs = ""
    for n, t in enumerate(items, 1):
        st = ""
        if abs(t["streak"]) >= 2:
            st = "%d일 %s" % (abs(t["streak"]), "연속↑" if t["streak"] > 0 else "연속↓")
        trs += ('<tr><td width="9%%" align="center" style="padding:6px 2px;border-bottom:1px solid #eef2f7;font-size:12px;color:#64748b;">%d</td>'
                '<td width="39%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:800;color:#111827;">%s</td>%s%s%s</tr>'
                % (n, B.E(t["name"]), _td(_pct(t["rate"]), 18, "right", B.updown(t["rate"]), True), _td("&#9650;%d &#9660;%d" % (t["rise"], t["fall"]), 17, "right", "#64748b"),
                   _td(st or "-", 17, "center", "#64748b")))
    head = _th("#", 9, "center") + _th("테마", 39, "left") + _th("등락률", 18) + _th("상승/하락", 17) + _th("연속", 17, "center")
    return B.side_title(accent_title, color) + _tbl("<tr>" + head + "</tr>" + trs)


def _blog_build(d, ai_text, inc, title):
    E = B.E
    th = d["themes"]
    today = _today()
    base = _base_label(d)
    ai_body, titles = _split_ai(ai_text) if (ai_text or "").strip() else ("", [])
    up = sum(1 for t in th if t["rate"] > 0)
    dn = sum(1 for t in th if t["rate"] < 0)
    avg = sum(t["rate"] for t in th) / len(th) if th else 0
    top = th[:8]
    auto_title = "🏷 %s 오늘의 강세 테마 | %s" % (base, " · ".join(t["name"] for t in th[:3]))
    title = title or (titles[0] if titles else auto_title)
    names, pairs = [], []
    for t in top[:5]:
        for x in _leaders(d, t["name"], 2):
            if x["name"] not in names:
                names.append(x["name"])
            pairs.append((x["name"], x["ticker"]))
    tags, tag_html = B.hashtags(names[:10], today, extra=["네이버테마", "강세테마", "테마주", "오늘의테마"] + [t["name"].replace(" ", "") for t in th[:3]])
    h = [B.seo_box(auto_title, "%s 기준 네이버 증권 테마별 등락률, 대표 종목, 수급을 정리했어요. 매수 추천이 아닌 참고 정보예요." % base,
                   ["네이버 테마", "강세 테마", "테마주", "오늘의 테마", "테마별 수급"] + [t["name"] for t in th[:3]]),
         B.head_box("★ NAVER THEME · %s" % base, '오늘의 <span style="color:%s;">강세 테마</span> 한눈에' % B.GOLD, "네이버 증권 테마 %d개 · 상승 %d · 하락 %d · 평균 %s" % (len(th), up, dn, E(_pct(avg))))]
    if inc.get("stats") and th:
        def tile(label, val, color, w):
            return ('<td width="%d%%" align="center" style="padding:11px 4px;background-color:#f8faff;border:1px solid #e5e7eb;"><div style="font-size:11px;color:#6b7280;margin-bottom:3px;">%s</div>'
                    '<div style="font-size:15px;font-weight:900;color:%s;">%s</div></td>' % (w, label, color, val))
        cells = (tile("1위 테마", E(th[0]["name"]), "#111827", 28) + tile("1위 등락률", E(_pct(th[0]["rate"])), B.updown(th[0]["rate"]), 24)
                 + tile("상승 테마", "%d개" % up, "#dc2626", 24) + tile("하락 테마", "%d개" % dn, "#2563eb", 24))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;margin:14px 0 4px;' + B.FONT + '"><tr>' + cells + "</tr></table>")
        sg = []
        for t in top[:5]:
            if abs(t["streak"]) >= 3:
                sg.append("%s 테마가 %d일 연속 %s예요." % (t["name"], abs(t["streak"]), "강세" if t["streak"] > 0 else "약세"))
            if t.get("rank_prev") and t["rank_prev"] - t["rank"] >= 10:
                sg.append("%s 테마가 어제 %d위에서 오늘 %d위로 올라왔어요." % (t["name"], t["rank_prev"], t["rank"]))
        if sg:
            h.append(B.side_title("&#128161; 오늘의 테마 포인트", "#d97706") + '<div style="font-size:13.5px;color:#334155;line-height:2.0;">' + "".join("&#9642; %s<br>" % E(s) for s in sg[:6]) + "</div>")
    if inc.get("top") and top:
        h.append(_theme_table(top, "&#128293; 오늘 강세 테마 TOP %d" % len(top), "#c2410c"))
    if inc.get("bottom"):
        bt = [t for t in reversed(th[-5:]) if t["rate"] < 0]
        if bt:
            h.append(_theme_table(bt, "&#10052;&#65039; 오늘 약세 테마", "#1d4ed8"))
    if inc.get("leaders") and top:
        trs = ""
        for t in top[:6]:
            for x in _leaders(d, t["name"], 2):
                trs += ('<tr><td width="30%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:12px;color:#64748b;">%s</td>'
                        '<td width="42%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;">%s</td>%s</tr>'
                        % (E(t["name"]), B.nlink(x["ticker"], E(x["name"])), _td(_pct(x["pct"]), 28, "right", B.updown(x["pct"]), True)))
        if trs:
            h.append(B.side_title("&#127942; 강세 테마 대표 종목 (당일 등락률 상위)", "#4f46e5") + _tbl("<tr>" + _th("테마", 30, "left") + _th("종목", 42, "left") + _th("등락률", 28) + "</tr>" + trs))
            h.append('<p style="font-size:11.5px;color:#9ca3af;margin:6px 0 0;">시세가 수집된 종목만 보여 주며, 테마에 속한 모든 종목을 뜻하지 않아요.</p>')
    if inc.get("flow") and d["inv"]:
        fl = _flow_rank(d, "5", "buy", 2, 6)
        if fl:
            trs = "".join('<tr><td width="34%%" style="padding:6px 4px;border-bottom:1px solid #eef2f7;font-size:13px;font-weight:800;color:#111827;">%s</td>%s%s%s%s</tr>'
                          % (E(x["name"]), _td(_fmt_eok(x["f"]), 18, "right", B.updown(x["f"])), _td(_fmt_eok(x["i"]), 18, "right", B.updown(x["i"])),
                             _td(_fmt_eok(x["c"]), 18, "right", B.updown(x["c"]), True), _td(_pct(x["rate"]), 12 + 0, "right", B.updown(x["rate"])))
                          for x in fl)
            h.append(B.side_title("&#128176; 수급이 몰린 테마 (최근 5일 외국인+기관)", "#0f766e")
                     + _tbl("<tr>" + _th("테마", 34, "left") + _th("외국인", 18) + _th("기관", 18) + _th("합계", 18) + _th("오늘", 12) + "</tr>" + trs))
            h.append('<p style="font-size:11.5px;color:#9ca3af;margin:6px 0 0;">시가총액 상위 일부 종목의 &lsquo;순매수 수량×종가&rsquo; 추정치를 테마별로 더한 값이라 실제와 차이가 있어요.</p>')
    if inc.get("ai") and ai_body:
        h.append(B.side_title("&#129302; AI 테마 해설", "#0d1b3e"))
        h.append(B.link_names(B.ai_to_html(ai_body), pairs))
    h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border:2px solid #d97706;border-collapse:collapse;margin:14px 0 4px;' + B.FONT + '"><tr><td bgcolor="#fffbeb" style="background-color:#fffbeb;padding:12px 16px;">'
             '<div style="font-size:13px;font-weight:900;color:#92400e;">&#9888;&#65039; 테마는 단기 관심이 몰리는 묶음이에요</div><div style="font-size:12.5px;color:#92400e;line-height:1.85;margin-top:4px;">'
             '오늘 강했던 테마가 내일도 강하다는 보장은 없고, 같은 테마 안에서도 종목마다 흐름이 크게 달라요. 이 글은 네이버 증권 공개 자료를 정리한 참고 정보이며 투자 권유가 아닙니다.</div></td></tr></table>')
    h.append(B.risk_box())
    h.append(B.engage_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/theme/blog", methods=["POST"])
def api_blog():
    deny = _admin_deny()
    if deny:
        return deny
    b = _json_body() or {}
    d = _load(True)
    if not d["themes"]:
        return _admin_json({"error": "네이버 테마 자료가 없어요. 먼저 [🏷 테마 가져오기]를 실행하세요."}, 404)
    inc = b.get("inc")
    inc = {k: bool((inc or {}).get(k, True)) for k in BLOG_SECS} if isinstance(inc, dict) else {k: True for k in BLOG_SECS}
    out = _blog_build(d, str(b.get("ai") or "")[:20000], inc, _s(b.get("title"), 150))
    pseudo = "D" + _base_label(d).replace("-", "")[2:]
    logs, warn = B.dup_info(pseudo, "theme")
    out.update({"ticker": pseudo, "name": "네이버테마 " + _base_label(d), "dups": logs, "dup_warn": warn})
    return _admin_json(out)


@bp.route("/admin/api/theme/diag", methods=["GET"])
def api_diag():
    deny = _admin_deny()
    if deny:
        return deny
    d = _load(True)
    ai = _ai_get()
    return _admin_json({"ok": True, "themes": len(d["themes"]), "links": sum(len(v) for v in d["members"].values()), "dates": d["dates"][-5:], "date_n": len(d["dates"]),
                        "fetched_at": d["fetched_at"], "price_n": len(d["price"]), "inv_n": len(d["inv"]), "inv_base": d["base_date"], "ai_date": ai.get("date", "")})


@bp.route("/admin/api/theme/delete", methods=["POST"])
def api_delete():
    """일별 이력(theme_day)만 지운다 — 현재 테마 목록·종목 연결은 그대로."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    try:
        conn = C._pg_get() if C._USE_PG else C._history_conn()
        try:
            c = conn.cursor()
            c.execute("DELETE FROM theme_day")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return _admin_json({"error": "지우지 못했어요: %s" % str(e)[:80]}, 500)
    _CACHE["d"] = None
    _alog("theme_day_delete", "")
    return _admin_json({"ok": True})


# ══════════════════════════════════════════════════════════════
# 화면
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""var TH={sec:'list',css:false,q:'',sort:'rate',side:'all',top:'60',ls:null,no:0,det:null,fl:{per:'5',side:'buy'},flD:null,tr:{side:'up',days:'10'},trD:null,ai:{text:'',date:'',old:null},flag:{img:false,blog:false},imgPanel:null,blogPanel:null,diag:null,job:null,jtm:0,jwas:false,memGo:null};
var TH_SECS=[['list','① 🏷 테마 순위','list'],['detail','② 🔎 테마 안 종목','detail'],['flow','③ 💰 테마별 수급','flow'],['trend','④ 📈 일별 추이','trend'],['ai','⑤ 🤖 AI 해설','ai'],['img','⑥ 🖼 테마 이미지','img'],['blog','⑦ 📝 블로그 쓰기','blog'],['guide','📘 읽는 법','guide']];
var TH_COL=['#e11d48','#f59e0b','#10b981','#3b82f6','#8b5cf6','#14b8a6','#f97316','#64748b','#ec4899','#84cc16'];
var TH_CSS='.thHd{padding:14px 16px}.thHd h2{margin:0 0 4px;font-size:18px}'+
'.thNav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 8px}.thNav button{border:1.5px solid #cbd5e1;background:#fff;color:#334155;border-radius:999px;padding:7px 13px;font:inherit;font-size:13px;font-weight:700;cursor:pointer}.thNav button.thOn{background:#c2410c;border-color:#c2410c;color:#fff}'+
'.thStp{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}.thStp button{flex:1 1 170px;display:flex;align-items:center;gap:10px;text-align:left;border:1.5px solid #fed7aa;background:#fff;color:#9a3412;border-radius:14px;padding:9px 12px;font:inherit;font-size:13.5px;font-weight:800;cursor:pointer;line-height:1.35}'+
'.thStp button small{display:block;font-weight:600;font-size:11.5px;color:#64748b}.thStp .n{width:26px;height:26px;border-radius:50%;background:#fed7aa;color:#9a3412;display:flex;align-items:center;justify-content:center;font-weight:900;flex:0 0 auto}'+
'.thStp .done{border-color:#86efac;background:#f0fdf4}.thStp .done .n{background:#16a34a;color:#fff}.thStp .cur{border-color:#c2410c;box-shadow:0 0 0 3px rgba(194,65,12,.18)}'+
'.thL{display:inline-flex;flex-direction:column;gap:2px;font-size:11.5px;color:#64748b}.thL select{min-width:92px}'+
'.thW{overflow-x:auto;-webkit-overflow-scrolling:touch}.thT{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}.thT th{background:#fff7ed;white-space:nowrap}.thT td.r,.thT th.r{text-align:right;white-space:nowrap}.thT .nm{font-weight:800;color:#0f172a}.thT .sb{font-size:11px;color:#94a3b8}.thT tr.thClk{cursor:pointer}.thT tr.thClk:hover{background:#fff7ed}'+
'.thUp{color:#dc2626;font-weight:700}.thDn{color:#2563eb;font-weight:700}.thZ{color:#94a3b8}'+
'.thCard{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:8px 0}.thCard h3{margin:0 0 6px;font-size:15px}'+
'.thTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:8px 0}.thTile{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:8px 10px;text-align:center}.thTile .l{font-size:11.5px;color:#64748b;font-weight:700}.thTile .v{font-size:18px;font-weight:900;margin-top:2px}.thTile .s{font-size:10.5px;color:#94a3b8}'+
'.thBr{display:grid;grid-template-columns:minmax(90px,150px) 1fr 64px;align-items:center;gap:8px;margin:4px 0;font-size:12.5px}.thBar{position:relative;height:14px;background:#f1f5f9;border-radius:7px;overflow:hidden}.thBar i{position:absolute;top:0;bottom:0}.thBar b{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#94a3b8}'+
'.thSvg{display:block;width:100%;height:auto}.thLg{font-size:11.5px;color:#64748b;margin:4px 0}.thLg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 3px 0 8px;vertical-align:-1px}'+
'.thAiOut{white-space:pre-wrap;word-break:break-word;font-size:13.5px;line-height:1.65;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin-top:8px}'+
'.thAiOut .h2{display:block;font-weight:900;color:#fff;background:#c2410c;border-radius:8px;padding:5px 10px;margin:10px 0 4px}.thAiOut .h3{display:block;font-weight:800;border-left:5px solid #c2410c;padding-left:8px;margin:8px 0 2px}'+
'.thGd h4{margin:12px 0 4px;font-size:14px}.thGd p,.thGd li{font-size:13px;line-height:1.65;color:#334155;margin:3px 0}.thGd ul{margin:4px 0 4px 18px;padding:0}'+
'.thPg{height:10px;border-radius:6px;background:#e2e8f0;overflow:hidden;margin:6px 0}.thPg>div{height:100%;background:#c2410c;width:0}.thImgG .c{margin:8px 0}';
function thCss(){if(TH.css)return;TH.css=true;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';var s=document.createElement('style');if(nn)s.setAttribute('nonce',nn);s.textContent=TH_CSS;document.head.appendChild(s)}
function thQ(o){var a=[];Object.keys(o).forEach(function(k){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]))});return a.join('&')}
function thCls(v){return v>0?'thUp':(v<0?'thDn':'thZ')}
function thFe(v){if(v==null||isNaN(v))return '-';v=Number(v);var a=Math.abs(v),s=v>0?'+':(v<0?'-':'');if(a>=10000)return s+(a/10000).toFixed(1)+'조';return s+Math.round(a).toLocaleString('ko-KR')+'억'}
function thPct(v){if(v==null||isNaN(v))return '-';return (v>0?'+':'')+Number(v).toFixed(2)+'%'}
function thStk(s){return !s||Math.abs(s)<2?'-':(Math.abs(s)+'일 '+(s>0?'연속↑':'연속↓'))}
function thStamp(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())}
function thDate(){var d=new Date(),z=function(n){return ('0'+n).slice(-2)};return d.getFullYear()+'-'+z(d.getMonth()+1)+'-'+z(d.getDate())}
function thDl(blob,name){var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(a.href)},4000)}
function thCsv(lines,name){thDl(new Blob(['﻿'+lines.join('\n')],{type:'text/csv'}),name+'_'+thStamp()+'.csv')}
function thSel(bar,lbl,obj,key,opts,fn){var l=el('label','thL');if(lbl)l.appendChild(el('span',null,lbl));var s=el('select');opts.forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];s.appendChild(op)});s.value=obj[key];s.onchange=function(){obj[key]=s.value;if(fn)fn()};l.appendChild(s);bar.appendChild(l);return s}
function thTbl(heads,aligns){var w=el('div','thW'),t=el('table','thT'),h=el('tr');heads.forEach(function(x,i){h.appendChild(el('th',aligns&&aligns[i]==='r'?'r':'',x))});t.appendChild(h);w.appendChild(t);return {wrap:w,t:t}}
function thPlace(box,fid,txt){var c=el('div','thCard');c.appendChild(el('b',null,txt||'이 기능은 잠겨 있어요'));c.appendChild(el('p','note','등급이 열리면 이 자리에 내용이 나타나요. 위 안내를 눌러 자세히 확인해 보세요.'));box.appendChild(c);ftSec(box,fid)}
function thNaverLink(tk,nm){var a=el('a','nm',nm);a.href='https://finance.naver.com/item/main.naver?code='+encodeURIComponent(tk);a.target='_blank';a.rel='noopener';return a}

/* ── 화면 뼈대 ── */
function thLoad(p){thCss();p.innerHTML='';
 var hd=el('div','c thHd');hd.appendChild(el('h2',null,'🏷 네이버테마 — 오늘의 강세·약세 테마'));
 hd.appendChild(el('div','m',(MEMBER_MODE?'① 테마 순위 → ② 테마 안 종목 → ③ 테마별 수급 → ④ 일별 추이. ':'① 테마 가져오기 → ② AI 해설 → ③ 테마 이미지 → ④ 블로그 쓰기. ')+'네이버 증권 테마가 오늘 얼마나 올랐는지, 어떤 종목이 끌었는지, 외국인·기관이 어느 테마에 몰렸는지 보여 줘요. 정보 제공용이며 투자 권유가 아니에요.'));
 var sb=el('div');sb.id='thSum';hd.appendChild(sb);p.appendChild(hd);
 var sp=el('div','thStp');sp.id='thSteps';p.appendChild(sp);var nv=el('div','thNav');nv.id='thNav';p.appendChild(nv);var bd=el('div');bd.id='thBody';p.appendChild(bd);
 p.appendChild(el('p','note','※ 테마 등락률·종목은 네이버 증권이 주는 값이에요. 테마별 수급은 시가총액 상위로 수집한 종목의 ‘순매수 수량×종가’ 합이라 테마 전체와 차이가 있어요. 테마는 단기 관심이 몰리는 묶음이라 변동이 크고, 투자 판단과 책임은 이용자 본인에게 있어요.'));
 var ad=el('div','c');ad.id='thAdm';p.appendChild(adm(ad));
 if(MEMBER_MODE&&TH.sec==='blog')TH.sec='list';thNavDraw();thShow();thSteps();if(!MEMBER_MODE){thAdmLoad();thAiLoad();thJobPoll(false)}}
function thNavDraw(){var n=$('thNav');if(!n)return;n.innerHTML='';TH_SECS.forEach(function(s){if(MEMBER_MODE&&s[0]==='blog')return;var b=el('button',TH.sec===s[0]?'thOn':'',(ftOk(s[2])?'':'🔒 ')+s[1]);b.type='button';b.onclick=function(){thGo(s[0])};n.appendChild(b)})}
var THFLOW=['ai','img','blog'];
function thHas(){return !!(TH.ls&&!TH.ls.empty)}
function thSteps(){var sp=$('thSteps');if(!sp)return;sp.innerHTML='';var has=thHas(),ai=!!(TH.ai.text&&TH.ai.text.trim());
 var defs=[['네이버 테마',has?(TH.ls.count+'개 · '+((TH.ls.fetched_at||'').slice(0,10))):'가져오거나 조회하세요','list',has],['AI 해설',ai?'완료 · 다시 만들기':'눌러서 시작','ai',ai],[MEMBER_MODE?'테마 이미지':'테마 대시보드 이미지',TH.flag.img?'만들었어요':'눌러서 만들기','img',TH.flag.img]];
 if(!MEMBER_MODE)defs.push(['블로그 쓰기',TH.flag.blog?'글 만들었어요':'눌러서 만들기','blog',TH.flag.blog]);
 var first=-1;defs.forEach(function(d,i){if(first<0&&!d[3])first=i});
 defs.forEach(function(d,i){var b=el('button',(d[3]?'done':'')+(i===first?' cur':''));b.type='button';b.setAttribute('data-noconfirm','1');b.appendChild(el('span','n',d[3]?'✓':String(i+1)));var t=el('span');t.appendChild(document.createTextNode(d[0]));t.appendChild(el('small',null,d[1]));b.appendChild(t);b.onclick=function(){thStepRun(d[2])};sp.appendChild(b)})}
function thStepRun(id){
 if(id==='list'){thGo('list');return}
 if(!thHas()&&TH.sec==='list'){toast(MEMBER_MODE?'아직 네이버 테마 자료가 없어요.':'먼저 아래 [🏷 테마 가져오기]를 눌러 주세요.');return}
 if(id==='ai'){if(!ftOk('ai')){lockDlg('ai');return}thGo('ai');thAiRun();return}
 if(id==='img'){if(!ftOk('img')){lockDlg('img');return}if(MEMBER_MODE){thGo('img');if(TH.memGo&&!TH.memGo.disabled)TH.memGo.click();return}if(window.MiniFlow)MiniFlow.go('theme',THFLOW,THACTS,'img');else thGo('img');return}
 if(id==='blog'){if(MEMBER_MODE)return;if(window.MiniFlow)MiniFlow.go('theme',THFLOW,THACTS,'blog');else thGo('blog')}}
var THACTS={
 ai:function(next){if(!thHas())return;if((TH.ai.text||'').trim()){next();return}if(!ftOk('ai'))return;thGo('ai');thAiRun()},
 img:function(next){thEnsure().then(function(){thGo('img');if(!TH.imgPanel)return;return TH.imgPanel.gen(true).then(function(){if(TH.imgPanel&&TH.imgPanel.items())next()})}).catch(function(){})},
 blog:function(){thEnsure().then(function(){thGo('blog');if(TH.blogPanel)TH.blogPanel.rebuild()}).catch(function(){})}};
function thGo(sec){TH.sec=sec;thNavDraw();thShow()}
function thShow(){var b=$('thBody');if(!b)return;b.innerHTML='';var box=el('div');b.appendChild(box);
 var m={list:thSecList,detail:thSecDetail,flow:thSecFlow,trend:thSecTrend,ai:thSecAi,img:thSecImg,blog:thSecBlog,guide:thSecGuide}[TH.sec],fid=TH_SECS.filter(function(s){return s[0]===TH.sec})[0][2];
 if(!ftOk(fid)){var f=FEATS&&FEATS[fid];thPlace(box,fid,'🔒 '+(f?f.label:'잠긴 기능'));return}m(box)}
function thListQ(){return thQ({q:TH.q,sort:TH.sort,side:TH.side,top:TH.top})}
function thEnsure(){if(thHas())return Promise.resolve(TH.ls);return api('/admin/api/theme/list?'+thQ({top:'300'})).then(function(j){if(j.error)throw new Error(j.error);if(j.empty)throw new Error(j.msg||'테마 자료가 없어요.');TH.ls=j;thSteps();return j})}
function thStatus(){var b=$('thSum');if(!b)return;b.innerHTML='';var j=TH.ls;if(!j||j.empty)return;var st=el('div');st.style.cssText='display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0';
 function chip(t,on){var c=el('span',null,t);c.style.cssText='display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;border:1px solid '+(on?'#fed7aa':'#e2e8f0')+';background:'+(on?'#fff7ed':'#f1f5f9')+';color:'+(on?'#c2410c':'#334155');return c}
 st.appendChild(chip('테마 '+j.count+'개',true));st.appendChild(chip('상승 '+j.up+' · 하락 '+j.down));st.appendChild(chip('평균 '+thPct(j.avg)));if(j.fetched_at)st.appendChild(chip('가져온 때 '+j.fetched_at.slice(0,16)));st.appendChild(chip('일별 이력 '+j.dates+'일'));b.appendChild(st)}

/* ── ① 테마 순위 ── */
function thSecList(box){
 var bar=el('div','bar');var q=el('input');q.type='search';q.placeholder='테마 이름 검색';q.value=TH.q;q.onkeydown=function(e){if(e.key==='Enter'){TH.q=q.value.trim();thListGo()}};bar.appendChild(q);bar.appendChild(bt('검색','bt3',function(){TH.q=q.value.trim();thListGo()}));
 thSel(bar,'보기',TH,'side',[['all','전체'],['up','강세만'],['down','약세만']],thListGo);thSel(bar,'정렬',TH,'sort',[['rate','등락률'],['rise','상승 종목 수'],['streak','연속 일수'],['total','종목 수']],thListGo);thSel(bar,'개수',TH,'top',[['30','30개'],['60','60개'],['100','100개'],['300','전체']],thListGo);box.appendChild(bar);
 var o=el('div');o.id='thListO';box.appendChild(o);thListGo()}
function thListGo(){var o=$('thListO');if(!o)return;o.innerHTML='';o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/theme/list?'+thListQ()).then(function(j){if(j.error)return;o.innerHTML='';if(j.empty){TH.ls={empty:true};o.appendChild(el('p','note',j.msg||'자료가 없어요.'));thStatus();thSteps();return}
  if(TH.top==='300'&&!TH.q&&TH.side==='all'&&TH.sort==='rate'){TH.ls=j}else if(!thHas()){api('/admin/api/theme/list?'+thQ({top:'300'})).then(function(a){if(!a.error&&!a.empty){TH.ls=a;thStatus();thSteps()}})}else{TH.ls.count=j.count;TH.ls.up=j.up;TH.ls.down=j.down;TH.ls.avg=j.avg;TH.ls.dates=j.dates;TH.ls.fetched_at=j.fetched_at}
  thStatus();thSteps();thListDraw(o,j)})}
function thListDraw(o,j){var mx=1;j.items.forEach(function(t){mx=Math.max(mx,Math.abs(t.rate))});
 var tl=el('div','thTiles');[['상승 테마',j.up+'개','thUp'],['하락 테마',j.down+'개','thDn'],['평균 등락률',thPct(j.avg),thCls(j.avg)],['검색 결과',j.matched+'개','']].forEach(function(x){var t=el('div','thTile');t.appendChild(el('div','l',x[0]));t.appendChild(el('div','v '+x[2],x[1]));tl.appendChild(t)});o.appendChild(tl);
 var card=el('div','thCard');card.appendChild(el('h3',null,'테마 막대 (등락률) — 누르면 안에 든 종목을 보여 줘요'));
 j.items.slice(0,12).forEach(function(t){var r=el('div','thBr');r.style.cursor='pointer';r.onclick=function(){thOpen(t.no)};r.appendChild(el('span',null,t.name));var bar=el('div','thBar');var i=document.createElement('i');i.style.width=Math.round(Math.abs(t.rate)*50/mx)+'%';i.style.background=t.rate>=0?'#e11d48':'#2563eb';if(t.rate>=0)i.style.left='50%';else i.style.right='50%';bar.appendChild(i);bar.appendChild(document.createElement('b'));r.appendChild(bar);r.appendChild(el('span','r '+thCls(t.rate),thPct(t.rate)));card.appendChild(r)});o.appendChild(card);
 var T=thTbl(['#','테마','등락률','상승','하락','종목','연속','전일 순위'],['','','r','r','r','r','r','r']);
 j.items.forEach(function(t){var tr=el('tr','thClk');tr.onclick=function(){thOpen(t.no)};tr.appendChild(el('td',null,String(t.rank)));tr.appendChild(el('td','nm',t.name));tr.appendChild(el('td','r '+thCls(t.rate),thPct(t.rate)));tr.appendChild(el('td','r thUp',String(t.rise)));tr.appendChild(el('td','r thDn',String(t.fall)));tr.appendChild(el('td','r',String(t.total)));tr.appendChild(el('td','r '+thCls(t.streak),thStk(t.streak)));
  tr.appendChild(el('td','r',t.rank_prev?(t.rank_prev+'위'+(t.rank_prev>t.rank?' ▲'+(t.rank_prev-t.rank):(t.rank_prev<t.rank?' ▼'+(t.rank-t.rank_prev):' -'))):'-'));T.t.appendChild(tr)});o.appendChild(T.wrap);
 if(!MEMBER_MODE||ftOk('exp')){var cc=el('div','bar');var eb=bt('📄 CSV 내려받기','bt3',function(){var L=['순위,테마,등락률(%),상승,하락,보합,종목수,연속일수'];j.items.forEach(function(t){L.push([t.rank,'"'+t.name.replace(/"/g,'""')+'"',t.rate,t.rise,t.fall,t.steady,t.total,t.streak].join(','))});thCsv(L,'네이버테마')});cc.appendChild(ft(eb,'exp'));o.appendChild(cc)}
 o.appendChild(el('p','note','연속: 일별 이력이 쌓인 날 기준으로 같은 방향(↑강세/↓약세)이 며칠 이어졌는지예요. 이력은 관리자가 테마를 가져올 때마다 하루씩 쌓여요(지금 '+j.dates+'일).'))}
function thOpen(no){if(!ftOk('detail')){lockDlg('detail');return}TH.no=no;TH.det=null;thGo('detail')}

/* ── ② 테마 안 종목 ── */
function thSecDetail(box){
 var bar=el('div','bar');var s=el('select');var op0=el('option',null,'테마를 고르세요');op0.value='0';s.appendChild(op0);
 thEnsure().then(function(j){j.items.slice().sort(function(a,b){return a.name<b.name?-1:1}).forEach(function(t){var op=el('option',null,t.name+' ('+thPct(t.rate)+')');op.value=String(t.no);s.appendChild(op)});s.value=String(TH.no||0)}).catch(function(){});
 s.onchange=function(){TH.no=Number(s.value)||0;TH.det=null;thDetGo()};var lb=el('label','thL');lb.appendChild(el('span',null,'테마'));lb.appendChild(s);bar.appendChild(lb);box.appendChild(bar);
 var o=el('div');o.id='thDetO';box.appendChild(o);thDetGo()}
function thDetGo(){var o=$('thDetO');if(!o)return;o.innerHTML='';if(!TH.no){o.appendChild(el('p','note','위에서 테마를 고르거나 ① 테마 순위에서 테마를 눌러 보세요.'));return}
 o.appendChild(el('p','note','⏳ 불러오는 중…'));api('/admin/api/theme/detail?'+thQ({no:TH.no})).then(function(j){if(j.error)return;o.innerHTML='';if(j.empty){o.appendChild(el('p','note',j.msg));return}TH.det=j;thDetDraw(o,j)})}
function thDetDraw(o,j){var t=j.theme,S=j.sums;
 var tl=el('div','thTiles');[['등락률',thPct(t.rate),thCls(t.rate)],['상승/하락 종목',t.rise+' / '+t.fall,''],['시세 있는 종목 평균',j.avg_pct==null?'-':thPct(j.avg_pct),thCls(j.avg_pct||0)],['연속',thStk(t.streak),thCls(t.streak)]].forEach(function(x){var c=el('div','thTile');c.appendChild(el('div','l',x[0]));c.appendChild(el('div','v '+x[2],x[1]));tl.appendChild(c)});o.appendChild(tl);
 if(j.inv_n){var c2=el('div','thCard');c2.appendChild(el('h3',null,'💰 이 테마 수급 (수급 자료가 있는 '+j.inv_n+'종목 합, 억원)'));var T0=thTbl(['주체','1일','5일','20일'],['','r','r','r']);[['외국인','f'],['기관','i'],['개인','r']].forEach(function(a){var tr=el('tr');tr.appendChild(el('td','nm',a[0]));['1','5','20'].forEach(function(p){var v=S[a[1]+p];tr.appendChild(el('td','r '+thCls(v),thFe(v)))});T0.t.appendChild(tr)});c2.appendChild(T0.wrap);c2.appendChild(el('p','note','기준일 '+(j.base_date||'-')+' · 시가총액 상위로 수집한 종목만 더한 추정치예요.'));o.appendChild(c2)}
 else o.appendChild(el('p','note','이 테마 종목의 수급 자료가 없어요(수집한 시가총액 상위 종목에 들지 않음).'));
 if(j.hist&&j.hist.dates.length>=2){var c3=el('div','thCard');c3.appendChild(el('h3',null,'📈 이 테마의 일별 등락률'));c3.appendChild(thLine(j.hist.dates,[{name:t.name,color:'#c2410c',data:j.hist.rates}]));o.appendChild(c3)}
 var T=thTbl(['종목','시장','현재가','등락률','시총(억)','외국인5일','기관5일','개인5일'],['','','r','r','r','r','r','r']);
 j.items.forEach(function(x){var tr=el('tr');var td=el('td');td.appendChild(thNaverLink(x.ticker,x.name));td.appendChild(el('div','sb',x.ticker));tr.appendChild(td);tr.appendChild(el('td',null,x.market||'-'));tr.appendChild(el('td','r',x.price?x.price.toLocaleString('ko-KR'):'-'));tr.appendChild(el('td','r '+thCls(x.pct||0),x.pct==null?'-':thPct(x.pct)));tr.appendChild(el('td','r',x.cap?Math.round(x.cap/1e8).toLocaleString('ko-KR'):'-'));
  ['f5','i5','r5'].forEach(function(k){tr.appendChild(el('td','r '+(x.has_inv?thCls(x[k]):'thZ'),x.has_inv?thFe(x[k]):'-'))});T.t.appendChild(tr)});o.appendChild(T.wrap);
 o.appendChild(el('p','note','시세가 수집된 종목 '+j.items.filter(function(x){return x.pct!=null}).length+'개 / 테마 종목 '+j.total+'개. 종목명을 누르면 네이버 증권으로 이동해요(새 창).'));
 if(!MEMBER_MODE||ftOk('exp')){var cc=el('div','bar');var eb=bt('📄 CSV 내려받기','bt3',function(){var L=['종목코드,종목,시장,현재가,등락률(%),시총(원),외국인5일(억),기관5일(억),개인5일(억)'];j.items.forEach(function(x){L.push([x.ticker,'"'+x.name.replace(/"/g,'""')+'"',x.market,x.price,x.pct==null?'':x.pct,x.cap,x.f5,x.i5,x.r5].join(','))});thCsv(L,'테마_'+t.name.replace(/[^0-9A-Za-z가-힣]/g,''))});cc.appendChild(ft(eb,'exp'));o.appendChild(cc)}}

/* ── ③ 테마별 수급 ── */
function thSecFlow(box){box.appendChild(el('p','note','시가총액 상위로 수집한 종목의 수급을 테마별로 더한 값이에요(외국인+기관 합계 순). 테마에 수급 자료가 있는 종목이 2개 이상일 때만 보여 줘요.'));
 var bar=el('div','bar');thSel(bar,'기간',TH.fl,'per',[['1','1일'],['5','5일'],['20','20일']],thFlowGo);thSel(bar,'방향',TH.fl,'side',[['buy','순매수 상위'],['sell','순매도 상위']],thFlowGo);box.appendChild(bar);var o=el('div');o.id='thFlowO';box.appendChild(o);thFlowGo()}
function thFlowGo(){var o=$('thFlowO');if(!o)return;o.innerHTML='';o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/theme/flow?'+thQ({period:TH.fl.per,side:TH.fl.side})).then(function(j){if(j.error)return;o.innerHTML='';if(j.empty){o.appendChild(el('p','note',j.msg));return}TH.flD=j;
  if(!j.items.length){o.appendChild(el('p','note','조건에 맞는 테마가 없어요.'));return}
  var T=thTbl(['#','테마','외국인','기관','개인','외국인+기관','수급 종목','오늘'],['','','r','r','r','r','r','r']);
  j.items.forEach(function(x,i){var tr=el('tr','thClk');tr.onclick=function(){thOpen(x.no)};tr.appendChild(el('td',null,String(i+1)));tr.appendChild(el('td','nm',x.name));['f','i','r','c'].forEach(function(k){tr.appendChild(el('td','r '+thCls(x[k]),thFe(x[k])))});tr.appendChild(el('td','r',x.pos+'/'+x.n));tr.appendChild(el('td','r '+thCls(x.rate),thPct(x.rate)));T.t.appendChild(tr)});o.appendChild(T.wrap);
  o.appendChild(el('p','note','기준일 '+(j.base_date||'-')+' · 수급 자료가 있는 종목 '+j.inv_stocks+'개 · 수급 종목 칸은 (합계가 순매수인 종목 수/수급 자료 종목 수)예요. 행을 누르면 테마 안 종목을 보여 줘요.'));
  if(!MEMBER_MODE||ftOk('exp')){var cc=el('div','bar');var eb=bt('📄 CSV 내려받기','bt3',function(){var L=['테마,외국인(억),기관(억),개인(억),외국인+기관(억),수급종목수,오늘등락률(%)'];j.items.forEach(function(x){L.push(['"'+x.name.replace(/"/g,'""')+'"',x.f,x.i,x.r,x.c,x.n,x.rate].join(','))});thCsv(L,'테마별수급_'+j.period+'일')});cc.appendChild(ft(eb,'exp'));o.appendChild(cc)}})}

/* ── ④ 일별 추이 ── */
function thSvg(tag,at){var e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.keys(at||{}).forEach(function(k){e.setAttribute(k,at[k])});return e}
function thLine(dates,series){var W=720,H=260,pl=48,pr=12,pt=14,pb=34,cw=W-pl-pr,ch=H-pt-pb,n=dates.length,svg=thSvg('svg',{viewBox:'0 0 '+W+' '+H,'class':'thSvg'});
 if(n<2||!series.length){var t=thSvg('text',{x:W/2,y:H/2,'text-anchor':'middle','font-size':14,fill:'#94a3b8'});t.textContent='그래프를 그리려면 2일 이상의 자료가 필요해요';svg.appendChild(t);return svg}
 var all=[0];series.forEach(function(s){s.data.forEach(function(v){if(v!=null)all.push(v)})});var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),pd=(hi-lo)*0.12||1;lo-=pd;hi+=pd;
 var X=function(i){return pl+i*cw/(n-1)},Y=function(v){return pt+ch*(hi-v)/(hi-lo)};
 for(var k=0;k<=4;k++){var v=lo+(hi-lo)*k/4,y=Y(v);svg.appendChild(thSvg('line',{x1:pl,x2:W-pr,y1:y,y2:y,stroke:'#e2e8f0','stroke-width':1}));var tx=thSvg('text',{x:pl-6,y:y+4,'text-anchor':'end','font-size':11,fill:'#64748b'});tx.textContent=v.toFixed(1)+'%';svg.appendChild(tx)}
 svg.appendChild(thSvg('line',{x1:pl,x2:W-pr,y1:Y(0),y2:Y(0),stroke:'#64748b','stroke-width':1.5,'stroke-dasharray':'5 4'}));
 var step=Math.max(1,Math.floor(n/6));for(var i=0;i<n;i+=step){var xt=thSvg('text',{x:X(i),y:H-12,'text-anchor':'middle','font-size':11,fill:'#64748b'});xt.textContent=dates[i].slice(5).replace('-','.');svg.appendChild(xt)}
 series.forEach(function(s){var d='',pen=false;s.data.forEach(function(v,i){if(v==null){pen=false;return}d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1);pen=true});svg.appendChild(thSvg('path',{d:d,fill:'none',stroke:s.color,'stroke-width':3,'stroke-linejoin':'round'}));
  if(n<=25)s.data.forEach(function(v,i){if(v!=null)svg.appendChild(thSvg('circle',{cx:X(i),cy:Y(v),r:3,fill:s.color}))})});return svg}
function thSecTrend(box){box.appendChild(el('p','note','테마를 가져온 날마다 그날의 등락률을 하나씩 쌓아 그려요. 오늘 기준 강세(또는 약세) 상위 테마들이 최근 며칠 어떻게 움직였는지 볼 수 있어요.'));
 var bar=el('div','bar');thSel(bar,'대상',TH.tr,'side',[['up','오늘 강세 상위'],['down','오늘 약세 상위']],thTrGo);thSel(bar,'기간',TH.tr,'days',[['5','최근 5일'],['10','최근 10일'],['20','최근 20일'],['40','최근 40일']],thTrGo);box.appendChild(bar);var o=el('div');o.id='thTrO';box.appendChild(o);thTrGo()}
function thTrGo(){var o=$('thTrO');if(!o)return;o.innerHTML='';o.appendChild(el('p','note','⏳ 불러오는 중…'));
 api('/admin/api/theme/history?'+thQ({side:TH.tr.side,days:TH.tr.days})).then(function(j){if(j.error)return;o.innerHTML='';if(j.empty){o.appendChild(el('p','note',j.msg));return}TH.trD=j;if(j.few){o.appendChild(el('p','note',j.msg));return}
  var c=el('div','thCard');var ser=j.series.map(function(s,i){return {name:s.name,color:TH_COL[i%TH_COL.length],data:s.rates}});c.appendChild(thLine(j.dates,ser));var lg=el('div','thLg');ser.forEach(function(s){var i=document.createElement('i');i.style.background=s.color;lg.appendChild(i);lg.appendChild(document.createTextNode(s.name))});c.appendChild(lg);o.appendChild(c);
  var T=thTbl(['테마'].concat(j.dates.map(function(d){return d.slice(5).replace('-','.')})),['']);for(var q=0;q<j.dates.length;q++)T.t.rows[0].cells[q+1].className='r';
  j.series.forEach(function(s){var tr=el('tr');tr.appendChild(el('td','nm',s.name));s.rates.forEach(function(v){tr.appendChild(el('td','r '+thCls(v||0),v==null?'-':thPct(v)))});T.t.appendChild(tr)});o.appendChild(T.wrap);
  if(!MEMBER_MODE||ftOk('exp')){var cc=el('div','bar');var eb=bt('📄 CSV 내려받기','bt3',function(){var L=['테마,'+j.dates.join(',')];j.series.forEach(function(s){L.push('"'+s.name.replace(/"/g,'""')+'",'+s.rates.map(function(v){return v==null?'':v}).join(','))});thCsv(L,'테마추이')});cc.appendChild(ft(eb,'exp'));o.appendChild(cc)}})}

/* ── ⑤ AI 해설 ── */
function thSecAi(box){box.appendChild(el('p','note',MEMBER_MODE?'테마 요약으로 AI에게 보낼 요청문을 만들어 드려요. AI 답변을 복사해 돌아오면 아래에 보여 드려요(이 화면에서만 보관돼요).':'테마 요약으로 AI 요청문을 만들어요. AI 답변을 복사해 돌아오면 저장되고 이미지·블로그 글에 쓰여요.'));
 var bar=el('div','bar');bar.appendChild(ft(bt('🤖 AI 프롬프트 만들기','bt',thAiRun),'ai'));box.appendChild(bar);var out=el('div');out.id='thAiOut';box.appendChild(out);thAiDraw()}
function thAiRun(){if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}
 api('/admin/api/theme/prompt').then(function(j){if(j.error){toast(j.error);return}if(j.empty){toast(j.msg);return}
  window.MiniAI.run({title:'네이버테마 AI 해설 — '+j.label,key:'theme',steps:[{label:j.label,prompt:j.prompt}],minLen:150,hint:'AI가 "## 🔥 오늘 한 줄 요약 …" 형식으로 답하면 답변 전체를 복사하고 이 창으로 돌아오세요.',
   preview:function(t){var x=el('div');x.textContent='읽은 글 '+t.length.toLocaleString('ko-KR')+'자 — '+t.slice(0,240)+(t.length>240?' …':'');return {node:x,canApply:t.trim().length>=100,strict:true}},
   apply:function(t){TH.ai.text=String(t||'').slice(0,20000);TH.ai.date='';TH.flag.img=false;TH.flag.blog=false;
    if(MEMBER_MODE){thAiDraw();thSteps();return Promise.resolve({message:'AI 해설을 아래 화면에 보여 줬어요(이 화면에서만 보관돼요).'})}
    return apiJ('/admin/api/theme/ai',{text:TH.ai.text,label:j.label}).then(function(z){var ok=!z.error;if(ok)TH.ai.date=z.date;thAiDraw();thSteps();
     if(ok)setTimeout(function(){if(window.MiniFlow)MiniFlow.run('theme',THFLOW,THACTS,'ai')},60);
     return {message:ok?'AI 해설을 저장했어요. 다음 단계(이미지 → 블로그 글)로 이어져요.':'읽었지만 저장하지 못했어요: '+z.error}}).catch(function(){thAiDraw();thSteps();return {message:'읽었지만 저장하지 못했어요(네트워크).'}})}})})}
function thAiLoad(){if(MEMBER_MODE)return;api('/admin/api/theme/ai').then(function(j){if(!j||j.error||!j.found)return;if(j.stale){TH.ai.old={text:j.text,date:j.date}}else{TH.ai.text=j.text;TH.ai.date=j.date}thAiDraw();thSteps()})}
function thAiDraw(){var out=$('thAiOut');if(!out)return;out.innerHTML='';var t=TH.ai.text;if(!t){out.appendChild(el('p','note','아직 AI 해설이 없어요. [AI 프롬프트 만들기]를 눌러 보세요.'));
  var o=TH.ai.old;if(o&&!MEMBER_MODE){var r0=el('div','bar');r0.appendChild(el('span','m','지난 AI 해설이 저장돼 있어요('+(o.date||'')+'). 오늘 테마와 맞지 않을 수 있어요.'));r0.appendChild(bt('지난 해설 불러오기','bt3',function(){TH.ai.text=o.text;TH.ai.date=o.date;TH.ai.old=null;TH.flag.img=false;TH.flag.blog=false;thAiDraw();thSteps()}));out.appendChild(r0)}return}
 var box=el('div','thAiOut');t.split('\n').forEach(function(l){var m;var s=l.replace(/\*\*/g,'');if((m=/^##\s+(.*)$/.exec(s))){box.appendChild(el('span','h2',m[1]))}else if((m=/^###\s+(.*)$/.exec(s))){box.appendChild(el('span','h3',m[1]))}else{box.appendChild(document.createTextNode(s));box.appendChild(document.createElement('br'))}});out.appendChild(box);
 var r=el('div','bar');r.appendChild(bt('📋 해설 복사하기','bt3',function(){var ok=window.MiniAI&&window.MiniAI.copy?window.MiniAI.copy(TH.ai.text):false;toast(ok?'복사했어요':'복사가 막혔어요')}));r.appendChild(bt('✖ 지우기','bt3',function(){TH.ai.text='';TH.ai.date='';thAiDraw();thSteps()}));out.appendChild(r);
 if(TH.ai.date&&!MEMBER_MODE)out.appendChild(el('p','note','💾 저장돼 있어요('+TH.ai.date+') — 테마 이미지·블로그 글에 쓰여요. [지우기]는 이 화면에서만 지우고 저장본은 남아요.'));
 out.appendChild(el('p','note','⚠ AI가 만든 참고 글이에요. 숫자와 내용이 틀릴 수 있고, 특정 종목·테마의 매수·매도 권유가 아니에요.'))}

/* ── ⑥ 테마 이미지(브라우저 캔버스) ── */
function thImgBuild(scale){return thEnsure().then(function(){return Promise.all([api('/admin/api/theme/list?'+thQ({top:'300'})),api('/admin/api/theme/flow?'+thQ({period:'5',side:'buy'}))])}).then(function(r){if(r[0].error)throw new Error(r[0].error);if(!window.ThImg)throw new Error('이미지 도구가 올라가지 않았어요.');return window.ThImg.build(r[0],(r[1]&&!r[1].error&&!r[1].empty)?r[1]:null,TH.ai.text||'',scale)})}
function thSecImg(box){box.appendChild(el('p','note',MEMBER_MODE?'오늘의 테마 순위를 한 장의 대시보드 이미지로 만들어 내려받아요. 참고 자료이며 투자 권유가 아니에요.':'① 테마 대시보드(강세·약세 막대, 테마별 수급) ② AI 해설 요약(AI 해설이 있을 때)을 이미지로 그려요. 저장 폴더·자동/수동 저장은 [⚙ 저장 설정]에서 정해요. 이 이미지를 블로그 글 위쪽에 올려 쓰세요.'));
 var ib=el('div');box.appendChild(ib);if(!window.ImgKit){ib.appendChild(el('p','note bad','이미지 도구(menu_img.py)가 올라가지 않았어요.'));return}
 if(MEMBER_MODE){thImgMember(ib);return}
 TH.imgPanel=ImgKit.panel(ib,{menu:'theme',name:'네이버테마',ticker:thStamp(),perStock:false,onDone:function(){TH.flag.img=true;thSteps()},gen:function(scale){return thImgBuild(scale)}});
 if(TH.flag.img)TH.imgPanel.gen(false)}
function thImgMember(ib){var K=window.ImgKit,row=el('div','bar'),view=el('div','thImgG'),st=el('div','m');
 var go=bt('🖼 이미지 만들기','bt',function(){go.disabled=true;go.textContent='⏳ 그리는 중…';view.innerHTML='';st.textContent='';
  Promise.resolve(K.fonts()).then(function(){return thImgBuild(2)}).then(function(items){items.forEach(function(it){var c=el('div','c');c.appendChild(el('b',null,K.CIRC[it.idx-1]+' '+it.label));
    var pw=Math.min(720,it.canvas.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(it.canvas.height*pw/it.canvas.width);sm.getContext('2d').drawImage(it.canvas,0,0,sm.width,sm.height);
    var im=new Image();im.alt=it.label;im.src=sm.toDataURL('image/png');im.style.cssText='width:100%;height:auto;display:block;border-radius:8px;margin:6px 0';c.appendChild(im);
    c.appendChild(bt('💾 이미지 내려받기','bt2',function(){it.canvas.toBlob(function(bl){if(!bl){toast('이미지를 만들지 못했어요');return}thDl(bl,K.fileName(it.idx,'네이버테마',thStamp()))},'image/png')}));view.appendChild(c)});
   st.textContent='이미지를 만들었어요. 각 이미지의 [이미지 내려받기]로 내 기기에 저장하세요.';go.textContent='🔄 다시 만들기';TH.flag.img=true;thSteps()})
  .catch(function(e){st.textContent='이미지를 만들지 못했어요: '+(e&&e.message||e);go.textContent='🖼 이미지 만들기'}).then(function(){go.disabled=false})});
 TH.memGo=go;row.appendChild(go);ib.appendChild(row);ib.appendChild(st);ib.appendChild(view)}
(function(){
var K=window.ImgKit;if(!K||window.ThImg)return;
var T=K.text,RR=K.rr;
var NAVY0='#1c0f05',NAVY1='#431407',GOLD='#f0b45a',PAPER='#f7f1e8',INK='#0f172a',MUT='#64748b',UP='#e11d48',DN='#2563eb';
function pc(v){if(v==null||isNaN(v))return '-';return (v>0?'+':'')+Number(v).toFixed(2)+'%'}
function fe(v){if(v==null||isNaN(v))return '-';v=Number(v);var a=Math.abs(v),s=v>0?'+':(v<0?'-':'');if(a>=10000)return s+(a/10000).toFixed(1)+'조';return s+Math.round(a).toLocaleString('ko-KR')+'억'}
function band(c,W,kick,title,sub){var g=c.createLinearGradient(0,0,0,210);g.addColorStop(0,NAVY0);g.addColorStop(1,NAVY1);c.fillStyle=g;c.fillRect(0,0,W,210);c.fillStyle=GOLD;c.fillRect(0,0,W,8);
 T(c,kick,W/2,60,{s:20,w:800,c:GOLD,a:'center',ls:5});T(c,title,W/2,132,{s:54,w:900,c:'#fff',a:'center',max:W-120});T(c,sub,W/2,178,{s:21,w:600,c:'#e7d3bd',a:'center',max:W-120})}
function card(c,x,y,w,h){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,24);c.fillStyle='#fff';c.fill();c.restore()}
function foot(c,W,y){c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,y,W-120,2);T(c,'테마는 단기 관심이 몰리는 묶음이라 변동이 커요. 공개 데이터를 정리한 참고 자료이며 투자 권유가 아닙니다.',W/2,y+38,{s:19,w:600,c:MUT,a:'center',max:W-120});T(c,'모든 투자 판단과 책임은 투자자 본인에게 있어요 · 출처 네이버 증권 · stock.oky.kr',W/2,y+72,{s:19,w:700,c:'#94a3b8',a:'center',max:W-120})}
function bars(c,x,y,w,title,sub,items,kind){var RH=58,h=96+items.length*RH+26;card(c,x,y,w,h);c.fillStyle=GOLD;RR(c,x+26,y+26,6,30,3);c.fill();T(c,title,x+46,y+50,{s:28,w:900,c:INK});T(c,sub,x+w-26,y+49,{s:16,w:500,c:'#94a3b8',a:'right'});
 var mx=1;items.forEach(function(t){mx=Math.max(mx,Math.abs(kind==='flow'?t.c:t.rate))});var bx=x+300,bw=w-300-190,mid=bx+bw/2;
 items.forEach(function(t,i){var yy=y+84+i*RH,v=kind==='flow'?t.c:t.rate;T(c,t.name,x+30,yy+30,{s:24,w:800,c:INK,max:255});c.fillStyle='#f1f5f9';RR(c,bx,yy+8,bw,32,8);c.fill();var L=Math.abs(v)*(bw/2)/mx;c.fillStyle=v>=0?UP:DN;if(v>=0)c.fillRect(mid,yy+8,L,32);else c.fillRect(mid-L,yy+8,L,32);c.fillStyle='#94a3b8';c.fillRect(mid-1,yy+4,2,40);
  T(c,kind==='flow'?fe(v):pc(v),x+w-26,yy+32,{s:24,w:900,c:v>=0?UP:DN,a:'right'});if(kind!=='flow')T(c,'▲'+t.rise+' ▼'+t.fall,bx+bw+12,yy+32,{s:16,w:600,c:MUT});else T(c,'외'+fe(t.f)+' 기'+fe(t.i),bx+bw+12,yy+32,{s:14,w:600,c:MUT,max:170})});return h}
function dash(ls,fl,scale){var W=1080,th=ls.items,top=th.slice(0,8),bt0=th.slice().reverse().filter(function(t){return t.rate<0}).slice(0,5),fi=fl&&fl.items?fl.items.slice(0,5):[];
 var H=210+30+120+30+(96+top.length*58+26)+30+(bt0.length?96+bt0.length*58+26+30:0)+(fi.length?96+fi.length*58+26+30:0)+118;var mk=K.make(W,H,scale),c=mk.c;c.fillStyle=PAPER;c.fillRect(0,0,W,H);
 band(c,W,'NAVER THEME','오늘의 강세 테마',(ls.fetched_at||'').slice(0,10)+' · 네이버 증권 테마 '+ls.count+'개 · 상승 '+ls.up+' · 하락 '+ls.down);
 var y=240,tl=[['1위 테마',th[0]?th[0].name:'-',INK],['1위 등락률',th[0]?pc(th[0].rate):'-',th[0]&&th[0].rate>=0?UP:DN],['상승 테마',ls.up+'개',UP],['하락 테마',ls.down+'개',DN]];
 var tw=(W-100-16*(tl.length-1))/tl.length;tl.forEach(function(t,i){var x=50+i*(tw+16);card(c,x,y,tw,120,18);T(c,t[0],x+tw/2,y+40,{s:20,w:700,c:MUT,a:'center'});T(c,t[1],x+tw/2,y+88,{s:t[1].length>6?28:36,w:900,c:t[2],a:'center',max:tw-16})});y+=150;
 y+=bars(c,50,y,W-100,'강세 테마 TOP '+top.length,'등락률(막대) · 상승/하락 종목 수',top,'rate')+30;
 if(bt0.length)y+=bars(c,50,y,W-100,'약세 테마','등락률(막대) · 상승/하락 종목 수',bt0,'rate')+30;
 if(fi.length)y+=bars(c,50,y,W-100,'수급이 몰린 테마 (5일)','외국인+기관 순매수(막대) · 수집 종목 기준',fi,'flow')+30;
 foot(c,W,H-118);return mk.cv}
function aiCard(ai,date,scale){var W=1080,tmp=K.make(W,100,1).c,font='600 26px '+K.FONT,maxW=W-200,lines=[];
 String(ai).replace(/\r/g,'').replace(/\*\*/g,'').split('\n').forEach(function(l){var t=l.trim();if(!t||/^\[블로그\s*제목/.test(t))return;var h=/^#{1,4}\s*(.*)$/.exec(t);if(h){lines.push({h:1,t:h[1]});return}K.wrap(tmp,t.replace(/^[-•·*]\s*/,'• '),maxW,font).forEach(function(s){lines.push({t:s})})});
 if(!lines.length)return null;lines=lines.slice(0,34);var H=210+40+lines.length*42+90+100,mk=K.make(W,H,scale),c=mk.c;c.fillStyle=PAPER;c.fillRect(0,0,W,H);band(c,W,'AI COMMENT','AI 테마 해설',date+' · 참고용 요약');
 card(c,50,240,W-100,H-240-110,24);var y=290;lines.forEach(function(l){if(l.h){y+=8;T(c,l.t,100,y+26,{s:30,w:900,c:'#c2410c',max:maxW});y+=46}else{T(c,l.t,100,y+26,{s:26,w:600,c:'#1e293b',max:maxW});y+=42}});foot(c,W,H-100);return mk.cv}
window.ThImg={build:function(ls,fl,ai,scale){var out=[{idx:1,label:'테마 대시보드',canvas:dash(ls,fl,scale)}];if(ai&&String(ai).trim()){var a=aiCard(ai,(ls.fetched_at||'').slice(0,10),scale);if(a)out.push({idx:2,label:'AI 테마 해설 요약',canvas:a})}return out}};
})();

/* ── ⑦ 블로그 쓰기 ── */
function thSecBlog(box){if(MEMBER_MODE)return;
 box.appendChild(el('p','note','테마 요약·강세/약세 순위·대표 종목·테마별 수급·AI 해설로 블로그용 글(HTML)을 만들어요. 글은 자동으로 올라가지 않고, [복사하고 블로그 열기]로 복사한 뒤 블로그 글쓰기 화면에 붙여 넣는 방식이에요. ⑥에서 저장한 대시보드 이미지는 글 위쪽에 직접 올려 주세요.'));
 var bx=el('div');box.appendChild(bx);if(!window.BlogKit){bx.appendChild(el('p','note bad','블로그 도구(menu_blog.py)가 올라가지 않았어요.'));TH.blogPanel=null;return}
 var secs=[['stats','요약·포인트'],['top','강세 테마 표'],['bottom','약세 테마 표'],['leaders','대표 종목'],['flow','테마별 수급'],['ai','AI해설']];
 TH.blogPanel=window.BlogKit.panel(bx,{idp:'th',key:'theme',kind:'theme',ticker:'D'+thStamp().slice(2),name:'네이버테마 '+thDate(),sections:secs,dup_warn:'',onBuilt:function(){TH.flag.blog=true;thSteps()},
  build:function(inc,title){return thEnsure().then(function(){return apiJ('/admin/api/theme/blog',{ai:TH.ai.text||'',inc:inc,title:title})}).catch(function(e){return {error:(e&&e.message)||'만들지 못했어요'}})}});
 if(TH.flag.blog)TH.blogPanel.rebuild()}

/* ── 📘 읽는 법 ── */
function thSecGuide(box){var g=el('div','thGd');function H(t){g.appendChild(el('h4',null,t))}function P(t){g.appendChild(el('p',null,t))}function UL(a){var u=el('ul');a.forEach(function(x){u.appendChild(el('li',null,x))});g.appendChild(u)}
 H('테마란?');P('네이버 증권이 “2차전지”, “로봇”, “반도체 장비”처럼 비슷한 이유로 함께 움직이는 종목들을 묶어 놓은 분류예요. 테마 등락률은 그 테마에 든 종목들의 오늘 등락을 모아 낸 값이에요. “이 테마를 사라”는 뜻이 아니라 오늘 시장의 관심이 어디로 쏠렸는지 보는 정보예요.');
 H('화면 구성');UL(['① 테마 순위: 등락률 순위, 상승/하락 종목 수, 연속 강세(약세) 일수, 전일 대비 순위 변화. 행을 누르면 ②로 이동해요.','② 테마 안 종목: 테마에 든 종목의 등락률과 외국인·기관·개인 수급(수집한 종목만)','③ 테마별 수급: 외국인+기관이 몰린(또는 빠진) 테마 순위','④ 일별 추이: 강세·약세 상위 테마의 일별 등락률 선그래프(이력이 쌓여야 그려져요)','⑤ AI 해설 → ⑥ 이미지 → ⑦ 블로그 글(관리자)']);
 H('읽을 때 알아 두세요');UL(['상승 종목 수가 많은 테마는 한두 종목이 아니라 여러 종목이 같이 오른 것이라 흐름이 더 넓다고 볼 수 있어요. 반대로 한두 종목만 크게 오르면 평균 등락률이 높아도 테마 전체가 강한 것은 아니에요.','연속 일수는 이 사이트가 테마를 가져온 날만 세요. 이력이 쌓이기 전에는 “-”로 보일 수 있어요.','테마별 수급은 시가총액 상위로 수집한 종목만 더한 추정치예요. 테마 종목이 수집 범위에 적으면 실제와 크게 다를 수 있어요.','테마는 단기 관심이 몰리는 묶음이라 변동이 크고, 테마 안에서도 종목마다 흐름이 달라요.','이 화면은 정보 제공용이며 특정 종목·테마의 매수·매도 권유가 아니에요. 투자 판단과 책임은 이용자 본인에게 있어요.']);box.appendChild(g)}

/* ── 관리자 전용: 테마 가져오기·점검 ── */
function thAdmLoad(){var b=$('thAdm');if(!b)return;api('/admin/api/theme/diag').then(function(j){TH.diag=j;thAdmDraw()})}
function thAdmDraw(){var b=$('thAdm');if(!b)return;b.innerHTML='';b.appendChild(el('b',null,'🛠 네이버 테마 가져오기·점검 (관리자만 보여요)'));var j=TH.diag;if(!j||j.error){b.appendChild(el('p','note bad','점검 정보를 읽지 못했어요.'));return}
 b.appendChild(el('p','note','[🏷 테마 가져오기]는 네이버 증권의 테마 목록과 테마별 종목을 받아 저장해요(1~2분 걸려요, 하루 한 번이면 충분해요). 가져올 때마다 그날의 테마 등락률이 일별 이력으로 쌓여 연속 강세·일별 추이에 쓰여요. 같은 테마·종목 연결은 수급분석 메뉴의 테마별 수급에도 함께 쓰여요.'));
 var r=el('div','bar');var b1=bt('🏷 테마 가져오기','bt',function(){if(TH.job&&TH.job.running){toast('이미 가져오기가 실행 중이에요.');return}apiJ('/admin/api/collect/theme/start',{}).then(function(z){if(z.error){toast(z.error);return}toast('테마 가져오기를 시작했어요');TH.jwas=true;thJobPoll(true)})});b1.id='thColB1';r.appendChild(b1);
 var b3=bt('⏹ 멈춤','bt3',function(){apiJ('/admin/api/collect/stop',{}).then(function(z){if(z.error){toast(z.error);return}toast('멈추는 중이에요…');thJobPoll(true)})});b3.id='thColB3';r.appendChild(b3);b.appendChild(r);
 var pg=el('div');pg.id='thColPg';b.appendChild(pg);var ls=el('div');ls.id='thColLast';b.appendChild(ls);thJobDraw();
 b.appendChild(el('p','note','현황 — 테마 '+j.themes+'개 · 종목 연결 '+j.links+'건 · 일별 이력 '+j.date_n+'일'+(j.dates&&j.dates.length?'('+j.dates.join(', ')+')':'')+' · 시세 '+j.price_n+'종목 · 수급 '+j.inv_n+'종목(기준일 '+(j.inv_base||'-')+') · 저장된 AI 해설 '+(j.ai_date||'없음')));
 if(j.date_n){var dr=el('div','bar');dr.appendChild(bt('🗑 일별 이력 지우기','bt3',function(){if(!confirm('테마 일별 이력(연속 일수·추이)을 모두 지울까요? 현재 테마 목록은 그대로 남아요.'))return;apiJ('/admin/api/theme/delete',{}).then(function(z){if(z.error){toast(z.error);return}toast('지웠어요');TH.ls=null;TH.trD=null;thAdmLoad();thShow()})}));b.appendChild(dr)}}
function thJobPoll(keep){api('/admin/api/collect/status').then(function(j){if(j.error||!$('thColPg'))return;TH.job=(j.job||{});TH.jall=j;thJobDraw();var run=!!(TH.job&&TH.job.running);
  if(run){TH.jwas=true;if(TH.jtm)clearTimeout(TH.jtm);TH.jtm=setTimeout(function(){thJobPoll(true)},1500)}
  else if(TH.jwas){TH.jwas=false;var okEnd=TH.job&&TH.job.kind==='theme'&&!TH.job.error;TH.ls=null;TH.det=null;TH.trD=null;TH.flag.img=false;TH.flag.blog=false;thAdmLoad();
   api('/admin/api/theme/list?'+thQ({top:'300'})).then(function(s){if(!s.error&&!s.empty)TH.ls=s;thStatus();thSteps();thShow();if(okEnd&&TH.ls&&window.MiniFlow)setTimeout(function(){MiniFlow.run('theme',THFLOW,THACTS)},80)})}})}
function thJobDraw(){var pg=$('thColPg'),ls=$('thColLast');var jb=TH.job||{},j=TH.jall||{},LT=j.last_theme||{};var b1=$('thColB1');if(b1)b1.disabled=!!jb.running;var st=$('thColB3');if(st)st.disabled=!jb.running;
 if(pg){pg.innerHTML='';if((jb.running||jb.phase==='end')&&jb.kind==='theme'){var pct=jb.total?Math.min(100,Math.round(jb.done*100/jb.total)):0;pg.appendChild(el('div','m',(jb.running?'⏳ ':'')+'테마 가져오기 — '+(jb.msg||'')+(jb.total?' ('+jb.done+'/'+jb.total+', '+pct+'%)':'')+(jb.cur?' · '+jb.cur:'')+(jb.fail?' · 실패 '+jb.fail:'')+' · '+jb.elapsed+'초'));
   var w=el('div','thPg'),f=document.createElement('div');f.style.width=(jb.running?Math.max(3,pct):(jb.error?0:100))+'%';if(jb.error)f.style.background='#f87171';w.appendChild(f);pg.appendChild(w);if(jb.error)pg.appendChild(el('p','note bad','⚠ '+jb.error))}
  else if(jb.running&&jb.kind!=='theme')pg.appendChild(el('p','note','다른 가져오기(종목 수급)가 실행 중이에요. 끝나면 테마 가져오기를 눌러 주세요.'))}
 if(ls){ls.innerHTML='';ls.appendChild(el('p','note',LT.at?('마지막: '+LT.at+' · 테마 '+LT.themes+'개 · 종목 연결 '+(LT.stocks||0).toLocaleString('ko-KR')+'건'+(LT.fail?' · 실패 '+LT.fail:'')):'테마: 아직 가져온 적 없어요'))}}
"""


def register():
    C.register_menu({"id": MENU, "label": "네이버테마", "icon": "🏷", "public_path": "/m/theme", "admin_path": "/admin#th",
                     "desc": "네이버 증권 테마의 오늘 등락률 순위, 테마 안 종목, 테마별 외국인·기관 수급, 일별 추이를 보여 줘요. 정보 제공용이며 투자 권유가 아니에요.",
                     "access": "admin"})
    C.register_prompt("theme_ai", {
        "title": "네이버테마 AI 프롬프트", "default": TH_DEFAULT, "required": ["{summary}"], "must_have": [],
        "vars": "{summary}=테마 순위·수급 요약(필수) · {base_date}=기준일 · {today}=오늘 날짜",
        "desc": "네이버테마 화면의 [AI 프롬프트 만들기]가 AI에게 보내는 요청문. 매수·매도 권유를 하지 않도록 쓰는 것이 원칙이에요."})
    C.register_admin_tab("th", "🏷 네이버테마", TAB_JS, "thLoad", menu=MENU)
    C.register_flow(MENU, "🏷 네이버테마", "① 테마 가져오기(직접 시작)", [
        {"id": "ai", "label": "② AI 해설", "desc": "테마를 가져오면 AI 요청문 창을 자동으로 열어요. AI 답변을 복사해 돌아오면 저장되고 다음 단계로 이어져요(오늘 저장한 AI 해설이 있으면 건너뛰어요)."},
        {"id": "img", "label": "③ 테마 대시보드 이미지", "desc": "AI 단계가 끝나면 블로그용 테마 대시보드 이미지를 자동으로 그려요(저장은 [⚙ 저장 설정]의 자동/수동 설정을 따라요)."},
        {"id": "blog", "label": "④ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요. 글은 자동으로 올라가지 않고 복사해서 붙여 넣어요."}])
    F = C.register_feature
    F(MENU, "list", "테마 순위", "오늘 등락률 기준 강세·약세 테마 순위, 상승/하락 종목 수, 연속 강세 일수, 전일 대비 순위 변화", default="public", endpoints=["/admin/api/theme/list"])
    F(MENU, "guide", "읽는 법", "테마 등락률·연속 일수·테마별 수급 용어와 자료 출처 해설(서버 호출 없음)", default="public", endpoints=[])
    F(MENU, "detail", "테마 안 종목", "테마를 눌러 안에 든 종목의 등락률·외국인·기관·개인 수급 합계 보기", default="member", endpoints=["/admin/api/theme/detail"])
    F(MENU, "flow", "테마별 수급", "외국인·기관이 몰린(또는 빠진) 테마 순위(1·5·20일)", default="member", endpoints=["/admin/api/theme/flow"])
    F(MENU, "trend", "일별 추이", "강세·약세 테마의 일별 등락률 선그래프", default="member", endpoints=["/admin/api/theme/history"])
    F(MENU, "ai", "AI 테마 해설", "테마 요약으로 AI 프롬프트를 만들고 답변을 붙여 보기(수동 — 서버가 AI를 부르지 않아요)", default="L2", endpoints=["/admin/api/theme/prompt"], kind="action")
    F(MENU, "img", "테마 이미지 내려받기", "강세·약세 테마와 테마별 수급을 대시보드 이미지로 그려 내려받아요", default="L2", endpoints=[], kind="tool")
    F(MENU, "exp", "표 내려받기", "지금 보는 표를 CSV 파일로 내려받기", default="L2", endpoints=[], kind="action")
    # 가져오기·AI 저장·블로그 글·점검·이력 지우기는 관리자 업무 → 어떤 기능에도 넣지 않았다(회원 화면에서는 404).
    return bp
