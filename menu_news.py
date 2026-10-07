"""📰 뉴스분석 (이용자 화면 /m/news + 관리자 탭) — 원본 프로그램의 뉴스분석·뉴스분석 게시판·긍정뉴스 지속종목을 웹용으로 옮긴 메뉴.

원본(app_desktop)의 구성을 '값만' 옮긴다(키·비밀번호는 쓰지 않음)
  ① 뉴스 수집(종목별·시장 최신) → ② 호재성/악재성·테마 키워드 분류(분류 참고용) → ③ AI 해석(수동: 프롬프트 복사 → 답변 붙여넣기 → 구조화)
  ④ 종목 추출(AI 식별명 → 종목 사전 검증 → 본문 토큰 매칭 → 테마 보완, 블록리스트·증권사/방송사 제외) → ⑤ 분석 기록 보관함(news_analysis_log)
  ⑥ 기록 집계: 테마·이슈 요약, 긍정뉴스 지속종목 점수(원본 공식 그대로)
웹에서 달라진 점
  · 서버는 외부 AI 를 부르지 않는다. 프롬프트를 만들어 주고, 사용자가 AI 사이트에서 받은 답을 붙여 넣으면 서버가 구조화해 보여 준다.
  · 기사 원문 전문은 저장·표시하지 않는다(제목·출처·링크·짧은 발췌만). 관리자가 보관함에 저장할 때도 원문은 짧은 발췌만 남긴다.
  · 기능별 등급 공개: 최신 뉴스·종목 뉴스(public) / 분류·테마·긍정뉴스(member) / 보관함·AI(L2). 저장·삭제·캐시 비우기는 관리자만(기능 등록 없음).

데이터: [📦 데이터 가져오기]로 옮긴 news_analysis_log(원본 기록)·stock_theme_map(업종·테마)는 읽기만 하고,
웹에서 관리자가 저장하는 분석은 nw_log(웹 전용)에 쌓는다 — 나중에 원본 DB 를 다시 가져와도 웹 기록이 지워지지 않는다.
"""
import html as _html
import ipaddress
import json
import os
import re
import socket
import sqlite3
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin
from flask import Blueprint, request
from menu_ctx import C
import menu_blog as B

bp = Blueprint("news", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_json_body", "_dbx", "_http", "_cache_get", "_cache_set", "_now_kst",
               "prompt_get", "get_db", "search_tickers", "_naver_news")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

MENU = "news"
TICKER_RE = re.compile(r"^[0-9A-Za-z]{6}$")
ID_RE = re.compile(r"^[ow][0-9]{1,12}$")
MAX_TEXT = 60000
NEED_DATA = "📦 데이터 가져오기 메뉴에서 ‘뉴스분석 기록(news_analysis_log)’ 표를 가져오면 보여요."
EPOCH = [0]                      # 저장·삭제·캐시 비우기 때 올려서 예전 캐시를 버린다


def _clear():
    """시험·관리자용: 이 모듈의 캐시를 모두 버린다."""
    EPOCH[0] += 1
    _DCACHE.clear()
    _SCACHE.clear()


# ══════════════════════════════════════════════════════════════
# 등급 문(gateway) 보조
# ══════════════════════════════════════════════════════════════
def _gw():
    return bool(request.environ.get("mini.gateway"))


def _fok(fid):
    """이 요청을 보낸 사람에게 기능 fid 가 열려 있는가(관리자 화면이면 항상 True)."""
    return (not _gw()) or bool(C.feature_ok(MENU, fid))


def _lock(fid):
    spec = C.feature_spec(MENU, fid) or {"label": fid}
    need = C.feature_need_text(MENU, fid)
    return _admin_json({"error": f"🔒 ‘{spec['label']}’ 기능은 {need}부터 쓸 수 있어요.", "feature": fid,
                        "login": C.viewer_token() == C.GUEST, "need": need}, 403)


def _err(msg, code=400):
    return _admin_json({"error": msg}, code)


# ══════════════════════════════════════════════════════════════
# 표 (웹 전용 저장소)
# ══════════════════════════════════════════════════════════════
def _ensure_tables(c, use_pg):
    pk = "SERIAL PRIMARY KEY" if use_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.execute(f"CREATE TABLE IF NOT EXISTS nw_log(id {pk}, created_at TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', "
              "content TEXT NOT NULL DEFAULT '', ai_text TEXT NOT NULL DEFAULT '', stocks_json TEXT NOT NULL DEFAULT '[]', kind TEXT NOT NULL DEFAULT 'stock')")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nw_log_at ON nw_log(created_at)")
    # [v186] 뉴스 보관함 — 가져온 뉴스를 분류해 쌓는다(추세 분석용)
    c.execute(f"CREATE TABLE IF NOT EXISTS nw_arch(id {pk}, uid TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT '', press TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', "
              "pub_at TEXT NOT NULL DEFAULT '', pub_day TEXT NOT NULL DEFAULT '', senti TEXT NOT NULL DEFAULT 'z', pos_kw TEXT NOT NULL DEFAULT '', neg_kw TEXT NOT NULL DEFAULT '', "
              "snippet TEXT NOT NULL DEFAULT '', srcs TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL DEFAULT '', seen_n INTEGER NOT NULL DEFAULT 1, related INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nw_arch_day ON nw_arch(pub_day)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nw_arch_senti ON nw_arch(senti)")
    c.execute("CREATE TABLE IF NOT EXISTS nw_arch_tk(aid INTEGER NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', direct INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(aid, ticker))")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nw_arch_tk_t ON nw_arch_tk(ticker)")
    c.execute("CREATE TABLE IF NOT EXISTS nw_arch_th(aid INTEGER NOT NULL, theme TEXT NOT NULL, PRIMARY KEY(aid, theme))")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nw_arch_th_t ON nw_arch_th(theme)")


# ══════════════════════════════════════════════════════════════
# 글자 다루기 — 종목 추출 규칙(원본 v2 설계 그대로: 토큰화 + 블록리스트 + 단어경계)
# ══════════════════════════════════════════════════════════════
_BLOCK = set(x.upper() for x in """
AI GPU CPU NPU TPU SoC IC LED LCD OLED DDR HBM SSD HDD RAM ROM NAND DRAM VRAM RTX GTX RX RDNA GCN DLSS FSR XeSS CUDA
PC IT IP API SDK UI UX AR VR MR XR UHD USB HDMI GB TB MB FPS Hz
LTE 5G 6G WIFI BT NFC RF IoT M2M OS VM SaaS PaaS CI CD ML DL NLP
LoL TFT RPG RTS MMO MMORPG MOBA PVP PVE DLC NPC GM BGM OST NFT P2E e스포츠 이스포츠
T1 GEN DRX KDF NS HLE BRO DK LSB LCK LPL LCS LEC VCS MSI Worlds
CEO CFO CTO COO CSO CMO CBO CPO VP SVP EVP MD PD PM QA HR PR IR
ETF ETP ETN PER PBR ROE ROA EPS BPS EV EBITDA ESG IPO SPO M&A VC PE FI PF USD KRW JPY EUR CNY GBP
kg km kW MW GW TW nm mm cm m A4 A3 B2 B1 V1 V2 V3 R1 R2
UN EU US UK KR SG JP CN TW HK AU DE FR WHO WTO IMF WEF G7 G20 OECD NASA DARPA DoD NSA CIA FBI
TESLA GEFORCE NVLINK NVME OK ID NO ON IN OF TO AT BY OR AND NEW OLD TOP HOT BIG THE ONE ALL ANY
GTC GDC CES MWC IFA E3 대상 AP시스템 AP 시스템
""".split())
_BROADCAST = {"에스비에스", "아이엠비씨", "와이티엔", "스카이라이프", "케이엔엔", "한국경제TV", "디지틀조선", "SBS", "iMBC", "YTN", "KNN", "SBS미디어홀딩스", "SBS콘텐츠허브"}
_SPLIT = re.compile(r"[\s\(\)\[\]\{\}「」『』〈〉《》,、。．！？!?'\"/\\|·•※①②③…\-_=+#@$%^&*<>:;~`]+")
_PARTS = sorted("""으로서는 에서부터 로부터는 이라는데 이라고는 이라는 라는 이라고 라고 에서의 로부터 으로서 에게서 에서는 에게는 까지는 에서도 에게도
이라도 이지만 이고서 이며 이나 이든 이든지 에의 에서만 에게만 로서의 으로서의 에로 로의 으로의 에서 에게 부터 까지 이랑 으로 이다 들의 들은 들이 들을 들에 들로
은 는 이 가 을 를 와 과 의 에 로 도 만 랑 하는 하여 하고 하며 하는데 하지만 하더라도 하고서 하였 했 됩니다 입니다 습니다 였다 했다 한 된 될 할""".split(),
                key=lambda p: -len(p))
_JOSA1 = "의은는이가을를에로도만와과랑서"
_HANGUL = re.compile(r"^[가-힣]+$")


def _strip_particle(tok):
    for p in _PARTS:
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[:-len(p)]
    return tok


def _tokenize(text):
    out = set()
    for t in _SPLIT.split(text or ""):
        if len(t) < 2:
            continue
        out.add(t)
        a = _strip_particle(t)
        out.add(a)
        out.add(_strip_particle(a))
        c = re.sub(r"[0-9A-Za-z]+$", "", t)
        if len(c) >= 2:
            out.add(c)
            out.add(_strip_particle(c))
    return out


def _prefix_map(toks):
    pm = {}
    for t in toks:
        for L in range(4, len(t)):
            pm.setdefault(t[:L], []).append(t)
    return pm


def _match(name, toks, pm, full):
    """종목명이 본문에 '직접 언급'됐는지 — 맞으면 이유 문자열, 아니면 None."""
    if len(name) < 2 or name.upper() in _BLOCK:
        return None
    if name in toks:
        return "토큰 직접 일치"
    ns = name.replace(" ", "")
    if ns in toks:
        return "공백 무시 일치"
    if len(name) >= 4 and _HANGUL.match(name):
        for t in pm.get(name, ()):
            rest = t[len(name):]
            if rest and rest[0] in _JOSA1:
                return "어절 접두 일치 (조사 포함)"
            if len(rest) <= 2:
                return "어절 접두 일치"
    m = re.match(r"[A-Za-z0-9]+", name)
    if m and len(name) >= 4 and re.search(r"[가-힣]", name) and len(m.group()) >= 2 and m.group().upper() not in _BLOCK:
        if name in full or ns in full:
            return "복합 종목 원문 일치"
    if len(name) >= 3 and not re.search(r"[가-힣]", name) and name.upper() not in _BLOCK:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", full, re.I):
            return "영문 단어경계 일치"
    return None


def _excluded(name, sector):
    """뉴스에 출처·논평자로만 나오는 증권사·방송사, 블록리스트는 관련종목이 아니므로 뺀다."""
    if not name or name.upper() in _BLOCK:
        return True
    sector = sector or ""
    if name.endswith("증권") or "증권" in sector:
        return True
    if name in _BROADCAST or "방송" in sector:
        return True
    return False


# ══════════════════════════════════════════════════════════════
# 종목 사전(ticker_names) · 업종/테마(stock_theme_map)
# ══════════════════════════════════════════════════════════════
_DCACHE = {}
_SCACHE = {}


def _dict():
    """{entries: 이름 긴 순, by_name, by_ticker}. 종목 사전이 비어 있으면 빈 목록."""
    path = str(get_db())
    hit = _DCACHE.get(path)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    rows = []
    try:
        con = sqlite3.connect(path, timeout=10)
        try:
            for t, n, mk in con.execute("SELECT ticker, name, market FROM ticker_names"):
                t = str(t or "").strip().upper()
                n = str(n or "").strip()
                if n and TICKER_RE.match(t):
                    rows.append({"ticker": t, "name": n, "market": str(mk or "")})
        finally:
            con.close()
    except Exception:
        rows = []
    rows.sort(key=lambda r: -len(r["name"]))
    by_name = {}
    for r in rows:
        by_name.setdefault(r["name"], r)
    d = {"entries": rows, "by_name": by_name, "by_ticker": {r["ticker"]: r for r in rows}}
    _DCACHE[path] = (time.time(), d)
    return d


def _sectors():
    """{ticker: 업종} — stock_theme_map 이 없으면 빈 값."""
    key = ("sec", str(get_db()))
    hit = _SCACHE.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    out = {}
    try:
        for t, s in _dbx("SELECT ticker, MAX(sector) FROM stock_theme_map GROUP BY ticker", (), fetch=True) or []:
            if t and s:
                out[str(t).strip().upper()] = str(s)
    except Exception:
        out = {}
    _SCACHE[key] = (time.time(), out)
    return out


_THEME_KW = {   # 원본 테마 보완 키워드(본문에 합쳐 2회 이상 나올 때만 테마로 인정)
    "반도체": "반도체,칩,파운드리,HBM,메모리,웨이퍼,DRAM,낸드",
    "게임": "게임,게이머,PC방,온라인게임,모바일게임,신작게임,게임사",
    "AI·소프트웨어": "인공지능,딥러닝,머신러닝,클라우드,데이터센터,LLM",
    "그래픽카드·GPU": "그래픽카드,GPU서버,AI반도체,엔비디아,지포스",
    "2차전지": "배터리,전기차,리튬,양극재,음극재,에너지저장",
    "바이오": "신약,임상,FDA,바이오,제약,항암,치료제",
    "방산": "방산,무기,K-방산,미사일,방위산업",
    "조선": "조선,LNG선,선박,수주",
    "원전": "원전,SMR,핵에너지,원자력",
}


def _theme_extra(full, seen, limit):
    out = []
    if limit <= 0:
        return out
    hits = []
    for th, kws in _THEME_KW.items():
        n = sum(full.count(k) for k in kws.split(","))
        if n >= 2:
            hits.append(th)
    for th in hits[:5]:
        try:
            rows = _dbx("SELECT ticker, name, market, sector FROM stock_theme_map WHERE theme LIKE ? ORDER BY name LIMIT 5", (f"%{th.split('·')[0]}%",), fetch=True) or []
        except Exception:
            return out
        for t, n, mk, sec in rows:
            t = str(t or "").strip().upper()
            n = str(n or "").strip()
            if not TICKER_RE.match(t) or t in seen or _excluded(n, sec):
                continue
            seen.add(t)
            out.append({"ticker": t, "name": n, "market": str(mk or ""), "sector": str(sec or ""), "mentioned": False, "reason": f"연관 테마: {th}"})
            if len(out) >= limit:
                return out
    return out


# ══════════════════════════════════════════════════════════════
# 뉴스 제목 분류 — 호재성/악재성 단어, 테마 키워드 (분류 참고용 · 투자 권유 아님)
# ══════════════════════════════════════════════════════════════
POS_WORDS = ["수주", "공급 계약", "공급계약", "계약 체결", "흑자전환", "흑자 전환", "흑자 확대", "흑자", "사상 최대", "역대 최대", "최대 실적", "호실적", "어닝 서프라이즈",
             "깜짝 실적", "실적 개선", "실적 호조", "영업이익 증가", "매출 증가", "목표가 상향", "목표주가 상향", "투자의견 상향", "신고가", "FDA 승인", "품목허가",
             "허가 획득", "승인 획득", "임상 성공", "특허 획득", "증설", "대규모 투자", "투자 유치", "배당 확대", "자사주 매입", "자사주 소각", "주주환원", "수혜",
             "급등", "상승세", "강세", "반등", "돌파", "기대감", "호재", "성장세", "턴어라운드", "수출 증가", "수출 호조", "점유율 확대"]
NEG_WORDS = ["적자전환", "적자 전환", "적자 지속", "적자", "영업손실", "순손실", "실적 부진", "어닝 쇼크", "실적 쇼크", "실적 악화", "영업이익 감소", "매출 감소",
             "목표가 하향", "목표주가 하향", "투자의견 하향", "급락", "폭락", "약세", "하락세", "하락", "부진", "우려", "리스크", "소송", "피소", "제재", "과징금", "횡령",
             "배임", "상장폐지", "거래정지", "관리종목", "불성실공시", "유상증자", "전환사채", "감자", "리콜", "파업", "화재", "압수수색", "기소", "적발", "벌금", "취소",
             "해지", "철회", "지연", "불확실", "둔화", "쇼크", "부도", "파산", "감사의견 거절", "의견거절", "매도세", "차질", "중단", "급감", "논란", "결렬", "무산"]
POS_OVR = ["적자 탈출", "적자 벗어", "적자폭 축소", "적자 폭 축소", "적자 축소", "손실 축소", "손실폭 축소", "우려 해소", "우려 완화", "불확실성 해소", "불확실성 완화",
           "리스크 해소", "낙폭 축소", "낙폭 만회", "하락 멈춰"]
NEG_OVR = ["흑자 폭 감소", "흑자폭 감소", "흑자 축소", "흑자폭 축소", "상승폭 축소", "상승 폭 축소", "수주 취소", "계약 취소", "계약 해지", "승인 거부", "허가 거부",
           "승인 지연", "허가 지연", "수주 부진", "수주 감소"]
THEMES = {
    "반도체": "반도체,HBM,파운드리,메모리,웨이퍼,DRAM,D램,낸드,칩",
    "AI·소프트웨어": "인공지능,AI,딥러닝,클라우드,데이터센터,LLM,생성형",
    "2차전지": "배터리,2차전지,이차전지,전기차,리튬,양극재,음극재,전고체,에너지저장,ESS",
    "바이오·제약": "신약,임상,FDA,바이오,제약,항암,치료제,백신",
    "방산": "방산,방위산업,무기,미사일,K-방산,전투기",
    "조선": "조선,LNG선,선박,해양플랜트",
    "원전": "원전,SMR,원자력,핵에너지",
    "게임·엔터": "게임,게이머,엔터,K팝,아이돌,콘서트",
    "자동차": "자동차,완성차,자율주행,전장",
    "금리·환율": "금리,기준금리,환율,달러,국채",
    "에너지·원자재": "유가,원유,정유,천연가스,석유화학,철강,구리",
    "건설·부동산": "건설,부동산,분양,재건축,아파트,PF",
    "로봇·자동화": "로봇,자동화,휴머노이드",
    "우주항공": "우주,위성,발사체,항공",
}
_ALL_KW = sorted([(w, "p") for w in POS_WORDS] + [(w, "n") for w in NEG_WORDS], key=lambda x: -len(x[0]))


def _kw_re(kw):
    if re.fullmatch(r"[A-Za-z0-9\- ]+", kw):
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])", re.I)
    return None


_THEME_RX = {th: [(k, _kw_re(k)) for k in kws.split(",")] for th, kws in THEMES.items()}


def _count_kw(text, kw, rx):
    return len(rx.findall(text)) if rx else text.count(kw)


def themes_of(text, min_hits=1):
    out = []
    for th, kws in _THEME_RX.items():
        n = sum(_count_kw(text, k, rx) for k, rx in kws)
        if n >= min_hits:
            out.append(th)
    return out


def classify(title):
    """제목 한 줄 → {label,k,pos,neg,themes}. 단어 기준의 단순 분류라 틀릴 수 있어요(분류 참고용)."""
    t = str(title or "")
    pos, neg = [], []
    for ph in POS_OVR:
        if ph in t:
            pos.append(ph)
            t = t.replace(ph, " ")
    for ph in NEG_OVR:
        if ph in t:
            neg.append(ph)
            t = t.replace(ph, " ")
    for kw, k in _ALL_KW:
        if kw in t:
            (pos if k == "p" else neg).append(kw)
            t = t.replace(kw, " ")
    p, n = len(pos), len(neg)
    label, k = ("호재성", "p") if p > n else ("악재성", "n") if n > p else ("혼재", "x") if p else ("중립", "z")
    return {"label": label, "k": k, "pos": pos[:6], "neg": neg[:6], "themes": themes_of(str(title or ""), 1)[:3]}


# ══════════════════════════════════════════════════════════════
# 뉴스 수집 (네이버 금융 모바일 — 본체 헬퍼와 같은 방식, 실패해도 빈 목록)
# ══════════════════════════════════════════════════════════════
_CATS = {"main": ("mainnews", "주요 뉴스"), "flash": ("flashnews", "실시간 속보"), "rank": ("ranknews", "많이 본 뉴스")}


def _clean(s, n=300):
    s = _html.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()[:n]


def _market_news(cat):
    """네이버 금융 뉴스 목록(제목·언론사·시각·링크·짧은 발췌 80자). 실패하면 (빈 목록, 안내문)."""
    key = ("nw_mkt", EPOCH[0], cat)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    items, note = [], ""
    try:
        r = _http().get("https://m.stock.naver.com/api/news/list", params={"category": _CATS[cat][0], "pageSize": 25, "page": 1},
                        timeout=6, headers=C.NAVER_M_HEADERS)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        for it in r.json() or []:
            oid, aid, dt = str(it.get("oid") or ""), str(it.get("aid") or ""), str(it.get("dt") or "")
            title = _clean(it.get("tit"), 200)
            if not title or not oid.isdigit() or not aid.isdigit():
                continue
            sn = _clean(it.get("subcontent"), 400)
            items.append({"title": title, "press": _clean(it.get("ohnm"), 30), "datetime": dt,
                          "date": f"{dt[4:6]}.{dt[6:8]} {dt[8:10]}:{dt[10:12]}" if len(dt) >= 12 else dt,
                          "url": f"https://n.news.naver.com/mnews/article/{oid}/{aid}",
                          "snippet": (sn[:80] + "…") if len(sn) > 80 else sn, "sn": sn[:240]})
    except Exception as e:
        print(f"[뉴스분석] 시장 뉴스 조회 오류(무시): {e}")
        note = "지금은 네이버 금융 뉴스를 가져오지 못했어요. 잠시 뒤 [새로 불러오기]를 눌러 주세요."
    out = (items[:25], note)
    _cache_set(key, out, 180 if items else 20)
    if items:
        archive_async(items[:25], "m:" + cat)             # [v186] 가져온 뉴스는 분류해서 보관함에 쌓는다
    return out


def _stock_news(ticker):
    key = ("nw_stk", EPOCH[0], ticker)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    try:
        rows = _naver_news(ticker) or []
    except Exception as e:
        print(f"[뉴스분석] {ticker} 뉴스 조회 오류(무시): {e}")
        rows = []
    items = []
    for x in rows[:12]:
        title = _clean(x.get("title"), 200)
        url = str(x.get("url") or "")
        if not title:
            continue
        items.append({"title": title, "press": _clean(x.get("press"), 30), "date": str(x.get("date") or ""), "datetime": str(x.get("datetime") or ""),
                      "url": url if re.match(r"^https?://[^\s<>\"']{4,400}$", url) else "", "related": int(x.get("related") or 0)})
    _cache_set(key, items, 300 if items else 20)
    return items


def _decorate(items, with_cls):
    """제목마다 분류를 붙이고(분류 기능이 열려 있을 때만) 요약 집계를 만든다."""
    if not with_cls:
        return items, None
    cnt = {"p": 0, "n": 0, "x": 0, "z": 0}
    out = []
    for it in items:
        c = classify(it["title"])
        cnt[c["k"]] += 1
        out.append(dict(it, cls=c))
    return out, {"호재성": cnt["p"], "악재성": cnt["n"], "혼재": cnt["x"], "중립": cnt["z"], "total": len(out)}


@bp.route("/admin/api/news/latest")
def api_latest():
    deny = _admin_deny()
    if deny:
        return deny
    cat = request.args.get("cat", "main")
    if cat not in _CATS:
        cat = "main"
    items, note = _market_news(cat)
    items = [{k: v for k, v in it.items() if k != "sn"} for it in items]          # 'sn'(조금 더 긴 발췌)은 서버 안에서만 쓴다
    ok_cls = _fok("classify")
    items, summ = _decorate(items, ok_cls)
    return _admin_json({"cat": cat, "label": _CATS[cat][1], "items": items, "summary": summ, "note": note or ("" if items else "가져온 뉴스가 없어요."),
                        "locked": [] if ok_cls else ["classify"], "source": "네이버 금융"})


@bp.route("/admin/api/news/refresh", methods=["POST"])
def api_refresh():
    """관리자 전용(기능 등록 없음) — 수집해 둔 뉴스 캐시를 비운다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    _clear()
    _alog("news_refresh", "")
    return _admin_json({"ok": True})


# ══════════════════════════════════════════════════════════════
# 분석 기록 읽기 (원본 news_analysis_log + 웹 nw_log)
# ══════════════════════════════════════════════════════════════
def _norm_stock(s):
    if not isinstance(s, dict):
        return None
    t = str(s.get("ticker") or "").strip().upper()
    if t.isdigit():
        t = t.zfill(6)
    if not TICKER_RE.match(t):
        return None
    try:
        sv = int(s.get("senti") or 0)
    except Exception:
        sv = 0
    return {"ticker": t, "name": str(s.get("name") or "")[:40], "market": str(s.get("market") or "")[:12], "sector": str(s.get("sector") or "")[:30],
            "mentioned": bool(s.get("mentioned")), "senti": max(-1, min(1, sv)), "reason": str(s.get("reason") or "")[:80]}


def _stocks_of(raw):
    try:
        d = json.loads(raw or "[]")
    except Exception:
        return []
    return [x for x in (_norm_stock(s) for s in (d if isinstance(d, list) else [])) if x]


def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _cutoff(days):
    from datetime import timedelta
    return (_now_kst() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _articles(days):
    """최근 days일 분석 기록을 기사 단위로(같은 제목·같은 날 재저장분은 1건으로) 돌려준다. (목록, 상태)"""
    key = ("nw_arts", EPOCH[0], str(get_db()), days)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    cut = _cutoff(days)
    rows, st = [], {}
    for table, src in (("news_analysis_log", "o"), ("nw_log", "w")):
        try:
            got = _dbx(f"SELECT id, created_at, title, source, stocks_json, SUBSTR(ai_text, 1, 3000) FROM {table} WHERE created_at >= ? ORDER BY id DESC LIMIT 6000",
                       (cut,), fetch=True) or []
            st[src] = "ok"
            for r in got:
                rows.append({"id": f"{src}{r[0]}", "created_at": str(r[1] or ""), "title": str(r[2] or ""), "source": str(r[3] or ""),
                             "stocks_json": r[4], "ai": str(r[5] or "")})
        except Exception:
            st[src] = "missing"
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    seen, arts = set(), []
    for r in rows:
        k = (r["title"], r["created_at"][:10])
        if k in seen:
            continue
        seen.add(k)
        arts.append({"id": r["id"], "title": r["title"][:200], "source": r["source"][:80], "date": r["created_at"][:10], "created_at": r["created_at"],
                     "stocks": _stocks_of(r["stocks_json"]), "ai": r["ai"]})
    out = (arts, st)
    _cache_set(key, out, 120)
    return out


def _data_note(arts, st):
    if arts:
        return ""
    if st.get("o") == "missing" and st.get("w") == "missing":
        return NEED_DATA
    return "이 기간에 저장된 뉴스 분석 기록이 없어요. 기간을 늘려 보세요."


def leaderboard(arts, min_days):
    """원본 _news_sentiment_leaderboard — 직접 언급되며 긍정(호재)으로 분류된 '날'이 많고 부정이 적은 순."""
    acc = {}
    for a in arts:
        d = a["date"]
        for s in a["stocks"]:
            e = acc.setdefault(s["ticker"], {"name": s["name"], "market": s["market"], "pd": set(), "nd": set(), "pc": 0, "nc": 0, "sp": 0, "sn": 0, "heads": []})
            if s["name"]:
                e["name"] = s["name"]
            v = s["senti"]
            if s["mentioned"]:
                if v > 0:
                    e["pd"].add(d)
                    e["pc"] += 1
                    e["heads"].append({"date": d, "title": a["title"], "senti": 1})
                elif v < 0:
                    e["nd"].add(d)
                    e["nc"] += 1
                    e["heads"].append({"date": d, "title": a["title"], "senti": -1})
            else:
                if v > 0:
                    e["sp"] += 1
                elif v < 0:
                    e["sn"] += 1
    rows = []
    for t, e in acc.items():
        pdays, ndays = len(e["pd"]), len(e["nd"])
        if pdays < min_days:
            continue
        total = pdays + ndays
        ratio = pdays / total if total else 0.0
        score = pdays * 10 + e["pc"] * 3 - ndays * 8 - e["nc"] * 3 + e["sp"] - e["sn"] + ratio * 20
        rows.append({"ticker": t, "name": e["name"], "market": e["market"], "direct_pos_days": pdays, "direct_neg_days": ndays, "direct_pos_count": e["pc"],
                     "direct_neg_count": e["nc"], "swept_pos_count": e["sp"], "swept_neg_count": e["sn"], "pos_ratio": round(ratio * 100), "score": round(score, 1),
                     "first_pos_date": min(e["pd"]) if e["pd"] else "", "last_pos_date": max(e["pd"]) if e["pd"] else "",
                     "headlines": sorted(e["heads"], key=lambda h: h["date"], reverse=True)[:6]})
    rows.sort(key=lambda r: -r["score"])
    return rows


def _int_arg(name, default, lo, hi):
    try:
        v = int(request.args.get(name, default))
    except Exception:
        v = default
    return max(lo, min(hi, v))


@bp.route("/admin/api/news/leader")
def api_leader():
    deny = _admin_deny()
    if deny:
        return deny
    days, mn = _int_arg("days", 21, 7, 90), _int_arg("min_days", 2, 1, 10)
    arts, st = _articles(days)
    rows = leaderboard(arts, mn)[:25]
    note = "" if rows else (_data_note(arts, st) or "조건에 맞는 종목이 없어요. 최소 긍정 보도일을 낮추거나 기간을 늘려 보세요.")
    return _admin_json({"rows": rows, "days": days, "min_days": mn, "articles": len(arts), "note": note,
                        "scanned_at": _now_kst().strftime("%Y-%m-%d %H:%M")})


@bp.route("/admin/api/news/themes")
def api_themes():
    deny = _admin_deny()
    if deny:
        return deny
    days = _int_arg("days", 14, 3, 90)
    arts, st = _articles(days)
    note = _data_note(arts, st)
    stocks, sectors = {}, {}
    th_arts = {}
    secmap = _sectors()
    for a in arts:
        hits = themes_of(a["title"] + " " + a["ai"], 2)
        names = [s["name"] for s in a["stocks"] if s["mentioned"]]
        for th in hits:
            e = th_arts.setdefault(th, {"n": 0, "names": {}, "titles": []})
            e["n"] += 1
            for nm in names:
                e["names"][nm] = e["names"].get(nm, 0) + 1
            if len(e["titles"]) < 3:
                e["titles"].append({"title": a["title"], "date": a["date"], "source": a["source"]})
        seen_sec = set()
        for s in a["stocks"]:
            if not s["mentioned"]:
                continue
            e = stocks.setdefault(s["ticker"], {"ticker": s["ticker"], "name": s["name"], "sector": s["sector"] or secmap.get(s["ticker"], ""), "articles": 0, "pos": 0, "neg": 0})
            e["articles"] += 1
            e["pos"] += 1 if s["senti"] > 0 else 0
            e["neg"] += 1 if s["senti"] < 0 else 0
            sec = e["sector"]
            if sec and sec not in seen_sec:
                seen_sec.add(sec)
                x = sectors.setdefault(sec, {"sector": sec, "articles": 0, "pos": 0, "neg": 0})
                x["articles"] += 1
                x["pos"] += 1 if s["senti"] > 0 else 0
                x["neg"] += 1 if s["senti"] < 0 else 0
    # 최근 제목은 날짜 내림차순으로 다시 3개
    for th, e in th_arts.items():
        e["titles"] = [{"title": a["title"], "date": a["date"], "source": a["source"]} for a in sorted(
            [a for a in arts if th in themes_of(a["title"] + " " + a["ai"], 2)], key=lambda a: a["created_at"], reverse=True)[:3]]
    themes = [{"theme": th, "articles": e["n"], "names": [k for k, _ in sorted(e["names"].items(), key=lambda kv: -kv[1])[:4]], "titles": e["titles"]}
              for th, e in sorted(th_arts.items(), key=lambda kv: -kv[1]["n"])[:10]]
    return _admin_json({"days": days, "articles": len(arts), "themes": themes,
                        "sectors": sorted(sectors.values(), key=lambda x: -x["articles"])[:10],
                        "stocks": sorted(stocks.values(), key=lambda x: (-x["articles"], -x["pos"]))[:20], "note": note})


# ══════════════════════════════════════════════════════════════
# 종목 뉴스
# ══════════════════════════════════════════════════════════════
def _resolve(q):
    q = (q or "").strip()
    if not q:
        return None, [], "종목 이름이나 6자리 코드를 입력해 주세요."
    if len(q) > 30:
        return None, [], "검색어가 너무 길어요."
    d = _dict()
    up = q.upper()
    if TICKER_RE.match(up) and (up in d["by_ticker"] or up.isdigit()):
        r = d["by_ticker"].get(up)
        return {"ticker": up, "name": r["name"] if r else "", "market": r["market"] if r else ""}, [], ""
    if q in d["by_name"]:
        r = d["by_name"][q]
        return dict(r), [], ""
    cands = [{"ticker": r["ticker"], "name": r["name"], "market": r.get("market", "")} for r in (search_tickers(q) or [])][:8]
    if len(cands) == 1:
        return cands[0], [], ""
    if not cands:
        return None, [], "해당하는 종목을 찾지 못했어요. 이름을 다시 확인하거나 6자리 종목코드를 입력해 보세요."
    return None, cands, ""


@bp.route("/admin/api/news/stock")
def api_stock():
    deny = _admin_deny()
    if deny:
        return deny
    pick, cands, msg = _resolve(request.args.get("q", ""))
    if msg:
        return _admin_json({"error": msg})
    if not pick:
        return _admin_json({"candidates": cands})
    t = pick["ticker"]
    items = _stock_news(t)
    ok_cls = _fok("classify")
    items, summ = _decorate(items, ok_cls)
    out = {"ticker": t, "name": pick.get("name", ""), "market": pick.get("market", ""), "items": items, "summary": summ, "locked": [] if ok_cls else ["classify"],
           "note": "" if items else "최근 14일 동안 가져온 뉴스가 없어요. 네이버 연결이 불안정할 수도 있으니 잠시 뒤 다시 해 보세요.", "source": "네이버 금융", "days": 14}
    if _fok("themes"):
        arts, st = _articles(30)
        mine = [(a, s) for a in arts for s in a["stocks"] if s["ticker"] == t]
        direct = [s for a, s in mine if s["mentioned"]]
        out["record"] = {"days": 30, "articles": len(mine), "direct": len(direct), "pos": sum(1 for s in direct if s["senti"] > 0),
                         "neg": sum(1 for s in direct if s["senti"] < 0)}
    else:
        out["locked"].append("themes")
    return _admin_json(out)


@bp.route("/admin/api/news/classify", methods=["GET", "POST"])
def api_classify():
    deny = _admin_deny(write=request.method == "POST")
    if deny:
        return deny
    if request.method == "GET":
        return _admin_json({"pos": POS_WORDS, "neg": NEG_WORDS, "pos_ovr": POS_OVR, "neg_ovr": NEG_OVR, "themes": THEMES})
    d = _json_body()
    titles = d.get("titles")
    if not isinstance(titles, list):
        return _err("분류할 제목을 한 줄에 하나씩 넣어 주세요.")
    lines = [re.sub(r"\s+", " ", str(x or "")).strip()[:200] for x in titles[:40]]
    lines = [x for x in lines if x]
    if not lines:
        return _err("분류할 제목을 한 줄에 하나씩 넣어 주세요.")
    rows = [dict(classify(x), title=x) for x in lines]
    cnt = {"호재성": 0, "악재성": 0, "혼재": 0, "중립": 0}
    for r in rows:
        cnt[r["label"]] += 1
    return _admin_json({"rows": rows, "summary": cnt, "total": len(rows)})


# ══════════════════════════════════════════════════════════════
# 보관함 (원본 news_analysis_log + 웹 nw_log) — 제목·출처·링크·짧은 발췌·AI 분석문만
# ══════════════════════════════════════════════════════════════
def _link(src):
    s = str(src or "").strip()
    return s if re.match(r"^https?://[^\s<>\"']{4,400}$", s) else ""


@bp.route("/admin/api/news/log/list")
def api_log_list():
    deny = _admin_deny()
    if deny:
        return deny
    q = (request.args.get("q") or "").strip()[:60]
    page = _int_arg("page", 1, 1, 50)
    PS = 30
    where, args = "", []
    if q:
        lk = _like(q)
        # 원문(content)은 보여주지 않는 항목이므로 검색에도 쓰지 않는다(검색 결과로 원문 내용을 짐작하지 못하게)
        where = " WHERE (title LIKE ? ESCAPE '\\' OR ai_text LIKE ? ESCAPE '\\')"
        args = [lk, lk]
    rows, total, st = [], 0, {}
    for table, src in (("news_analysis_log", "o"), ("nw_log", "w")):
        try:
            got = _dbx(f"SELECT id, created_at, title, source, SUBSTR(content, 1, 100), stocks_json FROM {table}{where} ORDER BY id DESC LIMIT ?",
                       tuple(args) + (page * PS,), fetch=True) or []
            total += int((_dbx(f"SELECT COUNT(*) FROM {table}{where}", tuple(args), fetch=True) or [[0]])[0][0] or 0)
            st[src] = "ok"
            for r in got:
                rows.append((str(r[1] or ""), src, r))
        except Exception:
            st[src] = "missing"
    rows.sort(key=lambda x: (x[0], int(x[2][0] or 0)), reverse=True)
    out = []
    for at, src, r in rows[(page - 1) * PS: page * PS]:
        stocks = _stocks_of(r[5])
        out.append({"id": f"{src}{r[0]}", "created_at": at[:16], "title": str(r[2] or "")[:200] or "(제목 없음)", "source": str(r[3] or "")[:80], "link": _link(r[3]),
                    "snippet": re.sub(r"\s+", " ", str(r[4] or "")).strip()[:100], "src": "orig" if src == "o" else "web",
                    "stocks": [{"ticker": s["ticker"], "name": s["name"], "senti": s["senti"]} for s in stocks[:6]], "n_stocks": len(stocks)})
    note = ""
    if not out:
        note = NEED_DATA if st.get("o") == "missing" and st.get("w") == "missing" else ("검색 결과가 없어요." if q else "아직 저장된 분석 기록이 없어요.")
    return _admin_json({"rows": out, "total": total, "page": page, "page_size": PS, "q": q, "note": note})


@bp.route("/admin/api/news/log/detail")
def api_log_detail():
    deny = _admin_deny()
    if deny:
        return deny
    i = str(request.args.get("id", ""))
    if not ID_RE.match(i):
        return _err("보관함 번호가 올바르지 않아요.")
    table = "news_analysis_log" if i[0] == "o" else "nw_log"
    try:
        rows = _dbx(f"SELECT id, created_at, title, source, SUBSTR(content, 1, 200), ai_text, stocks_json FROM {table} WHERE id=?", (int(i[1:]),), fetch=True)
    except Exception:
        return _admin_json({"error": NEED_DATA if i[0] == "o" else "웹 보관함 표를 읽지 못했어요."})
    if not rows:
        return _admin_json({"error": "게시물이 없어요(이미 삭제됐을 수 있어요)."})
    r = rows[0]
    return _admin_json({"id": i, "created_at": str(r[1] or "")[:16], "title": str(r[2] or "")[:200] or "(제목 없음)", "source": str(r[3] or "")[:200], "link": _link(r[3]),
                        "excerpt": re.sub(r"\s+", " ", str(r[4] or "")).strip(), "ai_text": str(r[5] or "")[:120000], "stocks": _stocks_of(r[6])[:40],
                        "src": "orig" if i[0] == "o" else "web"})


@bp.route("/admin/api/news/log/delete", methods=["POST"])
def api_log_delete():
    """관리자 전용(기능 등록 없음)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    i = str(_json_body().get("id", ""))
    if not ID_RE.match(i):
        return _err("보관함 번호가 올바르지 않아요.")
    try:
        _dbx(f"DELETE FROM {'news_analysis_log' if i[0] == 'o' else 'nw_log'} WHERE id=?", (int(i[1:]),))
    except Exception:
        return _err("삭제하지 못했어요(표가 없거나 읽기 전용이에요).", 500)
    _clear()
    _alog("news_delete", i)
    return _admin_json({"ok": True})


@bp.route("/admin/api/news/save", methods=["POST"])
def api_save():
    """관리자 전용(기능 등록 없음) — 파싱한 AI 분석을 웹 보관함(nw_log)에 저장. 원문은 짧은 발췌(300자)만 남긴다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    ai = str(d.get("ai_text") or "").strip()
    if len(ai) < 40:
        return _err("저장할 AI 분석 내용이 너무 짧아요.")
    title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:200]
    stocks = [x for x in (_norm_stock(s) for s in (d.get("stocks") if isinstance(d.get("stocks"), list) else [])) if x][:40]
    kind = "general" if d.get("kind") == "general" else "stock"
    at = _now_kst().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _dbx("INSERT INTO nw_log(created_at, title, source, content, ai_text, stocks_json, kind) VALUES(?,?,?,?,?,?,?)",
             (at, title, str(d.get("source") or "")[:200], re.sub(r"\s+", " ", str(d.get("excerpt") or "")).strip()[:300], ai[:120000],
              json.dumps(stocks, ensure_ascii=False), kind))
        rows = _dbx("SELECT id FROM nw_log WHERE created_at=? AND title=? ORDER BY id DESC LIMIT 1", (at, title), fetch=True) or [[0]]
    except Exception as e:
        print(f"[뉴스분석] 저장 실패: {e}")
        return _err("보관함에 저장하지 못했어요. 잠시 뒤 다시 해 보세요.", 500)
    _clear()
    _alog("news_save", f"{title[:40]} stocks={len(stocks)}")
    return _admin_json({"ok": True, "id": f"w{rows[0][0]}"})


# ══════════════════════════════════════════════════════════════
# 🗄 뉴스 보관함(v186) — 가져온 뉴스를 분류해 DB에 쌓는다(나중에 추세 분석용)
#   · 뉴스를 가져올 때마다 자동으로 저장: 제목·언론사·링크·발행시각·짧은 발췌(원문 전문은 저장하지 않음)
#   · 분류: 호재성/악재성(단어 기준) · 테마 · 관련 종목(검색한 종목 + 제목에 나온 종목) · 가져온 곳(주요/속보/많이 본/종목검색)
#   · 같은 기사는 한 줄(기사 번호 기준) — 다시 보이면 '본 횟수'만 올라가요(여러 번 보도된 정도도 추세 자료)
# ══════════════════════════════════════════════════════════════
import hashlib
import queue

SENTI_NM = {"p": "호재성", "n": "악재성", "x": "혼재", "z": "중립"}
_AQ = queue.Queue(maxsize=300)
_ASEEN = {}
_ALOCK = threading.Lock()
_AWORKER = {"t": None}
ARCH_ST = {"saved": 0, "last": "", "err": ""}


def _arch_uid(it):
    url = str(it.get("url") or "")
    m = re.search(r"article/(\d+)/(\d+)", url) or re.search(r"office[Ii]d=(\d+).*?article[Ii]d=(\d+)", url) or re.search(r"oid=(\d+).*?aid=(\d+)", url)
    if m:
        return "n%s-%s" % (m.group(1), m.group(2))
    raw = "%s|%s|%s" % (it.get("title", ""), it.get("press", ""), it.get("datetime", ""))
    return "t" + hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:20]


def _arch_time(it):
    dt = re.sub(r"\D", "", str(it.get("datetime") or ""))
    if len(dt) >= 12:
        return "%s-%s-%s %s:%s" % (dt[:4], dt[4:6], dt[6:8], dt[8:10], dt[10:12]), "%s-%s-%s" % (dt[:4], dt[4:6], dt[6:8])
    now = _now_kst()
    return now.strftime("%Y-%m-%d %H:%M"), now.strftime("%Y-%m-%d")


def _aq(sql):
    return sql.replace("?", "%s") if C._USE_PG else sql


def archive_items(items, src, ticker="", tname=""):
    """뉴스 목록을 보관함에 저장(동기). 저장·갱신한 건수를 돌려준다. 실패해도 예외를 밖으로 내지 않는다."""
    if not items:
        return 0
    now = _now_kst().strftime("%Y-%m-%d %H:%M:%S")
    todo = []
    with _ALOCK:
        if len(_ASEEN) > 8000:
            for k in sorted(_ASEEN, key=lambda x: _ASEEN[x])[:4000]:
                _ASEEN.pop(k, None)
        for it in items[:60]:
            title = _clean(it.get("title"), 200)
            if not title:
                continue
            uid = _arch_uid(it)
            key = (uid, ticker or "", src)
            if time.time() - _ASEEN.get(key, 0) < 900:      # 15분 안에 같은 곳에서 본 기사는 다시 세지 않는다
                continue
            _ASEEN[key] = time.time()
            todo.append((uid, title, it))
    if not todo:
        return 0
    conn = None
    n = 0
    try:
        conn = C._pg_get() if C._USE_PG else C._history_conn()
        c = conn.cursor()
        for uid, title, it in todo:
            cl = classify(title)
            snip = _clean(it.get("sn") or it.get("snippet") or "", 240)
            full = title + " " + snip
            themes = themes_of(full, 1)[:4]
            tks = []
            if ticker:
                tks.append((ticker, tname or (_dict()["by_ticker"].get(ticker) or {}).get("name", ""), 1))
            if src.startswith("m:"):                          # 시장 뉴스는 제목에 나온 종목도 찾는다(종목 검색 뉴스는 비용을 아끼려고 검색한 종목만)
                try:
                    for r in _db_extra(full, set(), 5):
                        tks.append((r["ticker"], r["name"], 1))
                except Exception:
                    pass
            pub_at, pub_day = _arch_time(it)
            c.execute(_aq("SELECT id, srcs FROM nw_arch WHERE uid=?"), (uid,))
            row = c.fetchone()
            if row:
                aid = row[0]
                srcs = str(row[1] or "")
                if ("," + src + ",") not in srcs:
                    srcs = (srcs or ",") + src + ","
                c.execute(_aq("UPDATE nw_arch SET last_seen=?, seen_n=seen_n+1, srcs=?, related=CASE WHEN related<? THEN ? ELSE related END WHERE id=?"),
                          (now, srcs, int(it.get("related") or 0), int(it.get("related") or 0), aid))
            else:
                c.execute(_aq("INSERT INTO nw_arch(uid,title,press,url,pub_at,pub_day,senti,pos_kw,neg_kw,snippet,srcs,first_seen,last_seen,seen_n,related) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT(uid) DO NOTHING"),
                          (uid, title, _clean(it.get("press"), 30), str(it.get("url") or "")[:400], pub_at, pub_day, cl["k"], ",".join(cl["pos"]), ",".join(cl["neg"]), snip,
                           "," + src + ",", now, now, int(it.get("related") or 0)))
                c.execute(_aq("SELECT id FROM nw_arch WHERE uid=?"), (uid,))
                r2 = c.fetchone()
                aid = r2[0] if r2 else 0
            if not aid:
                continue
            for th in themes:
                c.execute(_aq("INSERT INTO nw_arch_th(aid,theme) VALUES(?,?) ON CONFLICT(aid,theme) DO NOTHING"), (aid, th))
            for tk, nm, dr in tks:
                c.execute(_aq("INSERT INTO nw_arch_tk(aid,ticker,name,direct) VALUES(?,?,?,?) ON CONFLICT(aid,ticker) DO NOTHING"), (aid, tk, str(nm or "")[:40], dr))
            n += 1
        conn.commit()
        ARCH_ST["saved"] += n
        ARCH_ST["last"] = now
        ARCH_ST["err"] = ""
    except Exception as e:
        ARCH_ST["err"] = str(e)[:120]
        print(f"[뉴스보관] 저장 실패(무시): {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return n


def _arch_loop():
    while True:
        job = _AQ.get()
        try:
            archive_items(*job)
        except Exception as e:
            print(f"[뉴스보관] 작업 오류(무시): {e}")


def archive_async(items, src, ticker="", tname=""):
    """뉴스 수집을 느리게 만들지 않도록 뒤에서 저장한다(대기열이 가득 차면 이번 건은 건너뜀)."""
    if not items:
        return
    with _ALOCK:
        if _AWORKER["t"] is None or not _AWORKER["t"].is_alive():
            t = threading.Thread(target=_arch_loop, daemon=True)
            _AWORKER["t"] = t
            t.start()
    try:
        _AQ.put_nowait((list(items), src, ticker, tname))
    except queue.Full:
        pass


def _news_hook(source, ticker, items):
    if source == "stock" and ticker:
        archive_async(items, "s", ticker)


def _arch_where(args):
    """공통 조건 → (WHERE 문, 값 목록, JOIN 문). 쿼리 인자: days·senti·ticker·theme·q·day·press."""
    where, vals, join = [], [], ""
    days = args.get("days")
    try:
        days = int(days)
    except Exception:
        days = 30
    if days > 0:
        where.append("a.pub_day>=?")
        vals.append((_now_kst() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d"))
    sn = str(args.get("senti") or "")
    if sn in SENTI_NM:
        where.append("a.senti=?")
        vals.append(sn)
    tk = re.sub(r"[^0-9A-Za-z]", "", str(args.get("ticker") or ""))[:8]
    if tk:
        join += " JOIN nw_arch_tk k ON k.aid=a.id"
        where.append("k.ticker=?")
        vals.append(tk.upper())
    th = _clean(args.get("theme"), 30)
    if th:
        join += " JOIN nw_arch_th h ON h.aid=a.id"
        where.append("h.theme=?")
        vals.append(th)
    day = str(args.get("day") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        where.append("a.pub_day=?")
        vals.append(day)
    press = _clean(args.get("press"), 30)
    if press:
        where.append("a.press=?")
        vals.append(press)
    q = _clean(args.get("q"), 40)
    if q:
        where.append("a.title LIKE ?")
        vals.append("%" + q.replace("%", "").replace("_", "") + "%")
    return (" WHERE " + " AND ".join(where)) if where else "", vals, join


def _arch_rows(args, limit, offset=0):
    w, vals, join = _arch_where(args)
    rows = _dbx("SELECT a.id,a.title,a.press,a.url,a.pub_at,a.senti,a.pos_kw,a.neg_kw,a.srcs,a.seen_n,a.related FROM nw_arch a" + join + w +
                " ORDER BY a.pub_at DESC, a.id DESC LIMIT %d OFFSET %d" % (limit, offset), vals, fetch=True) or []
    total = (_dbx("SELECT COUNT(DISTINCT a.id) FROM nw_arch a" + join + w, vals, fetch=True) or [[0]])[0][0]
    ids = [int(r[0]) for r in rows]
    tk, th = {}, {}
    if ids:
        ph = ",".join("?" * len(ids))
        for aid, t, nm in _dbx("SELECT aid,ticker,name FROM nw_arch_tk WHERE aid IN (%s)" % ph, ids, fetch=True) or []:
            tk.setdefault(int(aid), []).append({"ticker": t, "name": nm})
        for aid, t in _dbx("SELECT aid,theme FROM nw_arch_th WHERE aid IN (%s)" % ph, ids, fetch=True) or []:
            th.setdefault(int(aid), []).append(t)
    items = [{"id": int(r[0]), "title": r[1], "press": r[2], "url": r[3], "at": r[4], "senti": r[5], "label": SENTI_NM.get(r[5], ""), "pos": r[6], "neg": r[7],
              "srcs": [x for x in str(r[8] or "").split(",") if x], "seen": int(r[9] or 1), "related": int(r[10] or 0),
              "stocks": tk.get(int(r[0]), []), "themes": th.get(int(r[0]), [])} for r in rows]
    return items, int(total or 0)


def _arch_ok():
    deny = _admin_deny()
    if deny:
        return deny
    return None


@bp.route("/admin/api/news/arch/summary")
def api_arch_summary():
    deny = _arch_ok()
    if deny:
        return deny
    args = dict(request.args)
    args.pop("ticker", None)
    args.pop("theme", None)
    w, vals, _j = _arch_where({"days": args.get("days", 30)})
    try:
        tot = (_dbx("SELECT COUNT(*), MIN(pub_day), MAX(pub_day) FROM nw_arch", (), fetch=True) or [[0, "", ""]])[0]
        by = {r[0]: int(r[1]) for r in (_dbx("SELECT a.senti, COUNT(*) FROM nw_arch a" + w + " GROUP BY a.senti", vals, fetch=True) or [])}
        perday = {}
        for d, sn, n in _dbx("SELECT a.pub_day, a.senti, COUNT(*) FROM nw_arch a" + w + " GROUP BY a.pub_day, a.senti ORDER BY a.pub_day", vals, fetch=True) or []:
            perday.setdefault(d, {"day": d, "p": 0, "n": 0, "x": 0, "z": 0})[sn] = int(n)
        agg = "COUNT(*), SUM(CASE WHEN a.senti='p' THEN 1 ELSE 0 END), SUM(CASE WHEN a.senti='n' THEN 1 ELSE 0 END)"
        th = [{"name": r[0], "n": int(r[1]), "p": int(r[2] or 0), "neg": int(r[3] or 0)} for r in (_dbx(
            "SELECT h.theme, " + agg + " FROM nw_arch_th h JOIN nw_arch a ON a.id=h.aid" + w + " GROUP BY h.theme ORDER BY 2 DESC LIMIT 30", vals, fetch=True) or [])]
        tk = [{"ticker": r[0], "name": r[1] or "", "n": int(r[2]), "p": int(r[3] or 0), "neg": int(r[4] or 0)} for r in (_dbx(
            "SELECT k.ticker, MAX(k.name), " + agg + " FROM nw_arch_tk k JOIN nw_arch a ON a.id=k.aid" + w + " GROUP BY k.ticker ORDER BY 3 DESC LIMIT 40", vals, fetch=True) or [])]
        pr = [{"name": r[0], "n": int(r[1]), "p": int(r[2] or 0), "neg": int(r[3] or 0)} for r in (_dbx(
            "SELECT a.press, " + agg + " FROM nw_arch a" + w + (" AND" if w else " WHERE") + " a.press<>'' GROUP BY a.press ORDER BY 2 DESC LIMIT 15", vals, fetch=True) or [])]
        today = (_dbx("SELECT COUNT(*) FROM nw_arch WHERE pub_day=?", (_now_kst().strftime("%Y-%m-%d"),), fetch=True) or [[0]])[0][0]
    except Exception as e:
        return _err("보관함을 읽지 못했어요: %s" % str(e)[:60], 500)
    return _admin_json({"ok": True, "total": int(tot[0] or 0), "first": tot[1] or "", "last": tot[2] or "", "today": int(today or 0), "by": by, "n": sum(by.values()),
                        "days": sorted(perday.values(), key=lambda x: x["day"]), "themes": th, "stocks": tk, "press": pr,
                        "state": {"saved": ARCH_ST["saved"], "last": ARCH_ST["last"], "err": ARCH_ST["err"]}})


@bp.route("/admin/api/news/arch/list")
def api_arch_list():
    deny = _arch_ok()
    if deny:
        return deny
    size = _int_arg("size", 50, 10, 100)
    page = _int_arg("page", 1, 1, 2000)
    try:
        items, total = _arch_rows(request.args, size, (page - 1) * size)
    except Exception as e:
        return _err("보관함을 읽지 못했어요: %s" % str(e)[:60], 500)
    return _admin_json({"ok": True, "items": items, "total": total, "page": page, "size": size})


@bp.route("/admin/api/news/arch/csv")
def api_arch_csv():
    deny = _arch_ok()
    if deny:
        return deny
    try:
        items, total = _arch_rows(request.args, 20000, 0)
    except Exception as e:
        return _err("보관함을 읽지 못했어요: %s" % str(e)[:60], 500)

    def q(x):
        return '"' + str(x if x is not None else "").replace('"', '""') + '"'
    lines = ["발행시각,제목,언론사,호재악재,테마,종목,근거단어,가져온곳,본횟수,링크"]
    for x in items:
        lines.append(",".join([q(x["at"]), q(x["title"]), q(x["press"]), q(x["label"]), q("|".join(x["themes"])), q("|".join("%s:%s" % (s["ticker"], s["name"]) for s in x["stocks"])),
                               q(" ".join(filter(None, [x["pos"], x["neg"]]))), q("|".join(x["srcs"])), q(x["seen"]), q(x["url"])]))
    from flask import Response
    resp = Response("\ufeff" + "\n".join(lines), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="news_archive_%s.csv"' % _now_kst().strftime("%Y%m%d")
    return C._admin_headers(resp)


@bp.route("/admin/api/news/arch/reclass", methods=["POST"])
def api_arch_reclass():
    """관리자 전용 — 분류 단어를 고친 뒤, 저장된 뉴스의 호재/악재·테마를 새 기준으로 다시 매긴다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    conn = None
    n = 0
    try:
        conn = C._pg_get() if C._USE_PG else C._history_conn()
        c = conn.cursor()
        c.execute("SELECT id,title,snippet FROM nw_arch")
        rows = c.fetchall()
        for aid, title, snip in rows:
            cl = classify(title)
            c.execute(_aq("UPDATE nw_arch SET senti=?,pos_kw=?,neg_kw=? WHERE id=?"), (cl["k"], ",".join(cl["pos"]), ",".join(cl["neg"]), aid))
            c.execute(_aq("DELETE FROM nw_arch_th WHERE aid=?"), (aid,))
            for th in themes_of(str(title) + " " + str(snip or ""), 1)[:4]:
                c.execute(_aq("INSERT INTO nw_arch_th(aid,theme) VALUES(?,?) ON CONFLICT(aid,theme) DO NOTHING"), (aid, th))
            n += 1
        conn.commit()
    except Exception as e:
        return _err("다시 분류하지 못했어요: %s" % str(e)[:60], 500)
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    _alog("news_arch_reclass", "n=%d" % n)
    return _admin_json({"ok": True, "n": n})


@bp.route("/admin/api/news/arch/prune", methods=["POST"])
def api_arch_prune():
    """관리자 전용 — N일보다 오래된 기사를 지운다(기본 180일)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    try:
        days = max(30, min(3650, int(d.get("days") or 180)))
    except Exception:
        days = 180
    cut = (_now_kst() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        ids = [r[0] for r in (_dbx("SELECT id FROM nw_arch WHERE pub_day<?", (cut,), fetch=True) or [])]
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            ph = ",".join("?" * len(part))
            _dbx("DELETE FROM nw_arch_tk WHERE aid IN (%s)" % ph, part)
            _dbx("DELETE FROM nw_arch_th WHERE aid IN (%s)" % ph, part)
            _dbx("DELETE FROM nw_arch WHERE id IN (%s)" % ph, part)
    except Exception as e:
        return _err("지우지 못했어요: %s" % str(e)[:60], 500)
    _alog("news_arch_prune", "days=%d n=%d" % (days, len(ids)))
    return _admin_json({"ok": True, "n": len(ids), "days": days})


# ══════════════════════════════════════════════════════════════
# AI 해석 — 프롬프트 만들기 · 붙여넣은 답변 구조화 (서버는 AI 를 부르지 않는다)
# ══════════════════════════════════════════════════════════════
NEWS_DEFAULT = r"""아래 뉴스를 분석하여 투자 관점의 참고 정보를 제공합니다. (투자 권유가 아닌 정보 제공 목적)

[출처]: {source}
[제목]: {title}
[분석일]: {today}

[원문 스크립트]  (신문/기사 원문 또는 방송 스크립트. 아래 내용을 '분석·해설'하되 원문 문장을 그대로 옮기지 마세요.)
{text}

⚖️ 저작권·인용 원칙 (반드시 준수):
- 원문 문장을 그대로 복사·전재하지 말고, 반드시 당신의 표현으로 다시 서술(요약·해설·재구성)하세요.
- 불가피한 직접 인용은 큰따옴표로 표시하되 한 번에 15단어 이내로 최소화하고, 같은 부분을 반복 인용하지 마세요.
- 숫자·기관명·일정 같은 '사실(fact)'은 자유롭게 활용하되, 문장·표현 자체는 새로 쓰세요.
- 목표는 원문 '전재'가 아니라 '투자 관점의 분석·해설' 제공입니다.

📏 분량·완전성 원칙:
- 원문에 담긴 내용을 최대한 빠짐없이 전달하되, 원문에 없는 내용을 지어내지는 마세요.
- 원문이 여러 주제·쟁점을 다루면 어느 하나도 빠뜨리지 말고 각각을 충분히 서술하세요.

🎙️ 말투 규칙: 모든 문장은 뉴스 아나운서가 전하듯 정중한 존댓말('~습니다', '~됩니다', '~로 보입니다', '~전망입니다')로 작성하세요. 개조식 단정 종결('~함', '~됨')이나 반말은 쓰지 마세요. (표·수치 항목의 짧은 라벨은 예외)
🚫 표현 규칙: 사거나 팔도록 권하는 말, '지금 해야 한다' 같은 단정 표현은 쓰지 말고, 근거와 확인할 점 중심으로 설명하세요.

다음 구조로 분석하세요:

## 📰 뉴스 핵심 요약
먼저 다음 한 줄로 시작하세요:
**한 줄 요약**: (이 뉴스 전체를 25~40자로 압축)

이어서 아래 소제목으로 방송 브리핑 문단을 작성하세요:
### 📻 뉴스 브리핑
아나운서가 뉴스를 전하듯, 핵심을 완결된 문장으로 충분히 이어 서술하세요(한 문단, 목록기호 없이). 무슨 일이 있었고 · 왜 중요하며 · 시장에는 어떤 의미인지가 담겨야 합니다.

이어서 원문을 관점별로 재구성해 번호 목록으로 정리하세요(내용이 많으면 10개 이상). 각 항목은 반드시 아래 형식을 지키세요(관점 라벨을 굵게):
    N. **관점라벨** — 쉬운 평문 두세 문장
관점라벨은 아래 목록에서 하나를 골라 글자 그대로 쓰세요:
  핵심 사건·주장 / 배경·원인 / 핵심 수치·데이터 / 이해관계자 / 인과·파급 / 일정·타임라인 / 시장·업계 반응 / 쟁점·이견 / 정책·규제 동향

### 🧮 핵심 수치·팩트
각 줄 형식: `- 항목 — 값 — 의미/맥락 한 줄`. (정량 수치가 없으면 "본문에 구체적 수치 없음" 한 줄)

### ⏱ 타임라인
시점 정보가 있으면 시간순으로 3~6줄. 형식: `- (시점) 사건 요약`. (없으면 이 소제목은 생략)

## 📊 시장 영향 분석
- 주식시장 전반에 미치는 영향 · 수혜 섹터와 피해 섹터 구분 (근거와 함께 2~4문장)

## 🎯 직접 언급 종목 분석
- 뉴스에서 직접 언급된 기업별로: 언급 맥락 → 확인할 포인트 → 단기·중기 영향 가능성 (실적·수주·정책 등 근거와 연결)

## 🔗 연관 종목 살펴보기
- 직접 언급은 없지만 영향을 받을 수 있는 종목과 그 이유(공급망·밸류체인 위치 명시)

## ⚠️ 리스크 및 주의사항
- 뉴스의 불확실한 부분, 확인이 필요한 전제, 투자 리스크

## 💡 점검 포인트 (참고용)
- 단기(1주 이내) / 중기(1~3개월) 관점에서 투자자가 직접 확인해 볼 체크포인트(권유·매매 지시 표현 금지)

---
[필수] 분석 마지막에 아래 JSON 블록을 반드시 포함하세요.
반드시 한국거래소(KOSPI/KOSDAQ) **실제 상장 회사명**만 포함하세요.
기술 용어(GPU, AI 등), 해외 기업, 팀명, 게임 제목은 제외하세요.

```json
{
  "mentioned": ["종목A", "종목B"],
  "related":   ["종목C"],
  "sentiment": {"종목A": 1, "종목B": -1, "종목C": 0},
  "title_ko": ""
}
```

※ 위 종목A·종목B·종목C는 형식 예시일 뿐이니 그대로 쓰지 말고, 이 뉴스에서 실제로 식별한 회사명으로 채우세요.
title_ko: 위 [제목]이 영어 등 외국어이면 자연스러운 한국어 번역 제목을, 한국어이거나 없으면 빈 문자열("")을 넣으세요.
mentioned: 뉴스 본문에 해당 기업의 사업이 직접 언급된 한국 상장사
related: 동종업계·공급망 관점에서 간접적으로 영향을 받을 수 있는 한국 상장사
sentiment: 이 뉴스가 각 종목에 미치는 영향의 분류 — 호재 1 / 중립 0 / 악재 -1 (식별한 모든 종목 포함, 분류 참고용)
확실하지 않으면 빈 리스트([])로 두세요.
"""

NEWS_OVERVIEW_DEFAULT = r"""당신은 20년 경력의 한국 주식시장 애널리스트입니다. 아래는 {today} 기준 '{cat}' 뉴스 {count}건의 제목·언론사·짧은 발췌입니다.
이 뉴스들을 한꺼번에 살펴보고, 초보 투자자도 이해할 수 있게 '전체 뉴스 총평'과 투자 관점의 참고 정보를 정리해 주세요. (투자 권유가 아닌 정보 제공 목적)

[사이트에서 단어 기준으로 미리 집계한 참고 값 — 틀릴 수 있으니 참고만 하세요]
{stats}

[뉴스 목록]
{headlines}

⚖️ 작성 원칙
- 제목·발췌의 문장을 그대로 옮기지 말고 당신의 표현으로 재구성하세요. 목록에 없는 사실·수치를 지어내지 마세요.
- 사거나 팔도록 권하는 말, '지금 해야 한다' 같은 단정 표현은 쓰지 말고 근거와 확인할 점 중심으로 설명하세요.
- 말투는 뉴스 앵커처럼 정중한 존댓말('~습니다', '~로 보입니다')로 쓰세요.

다음 구조로 작성하세요:

## 🧭 오늘 뉴스 총평
먼저 다음 한 줄로 시작하세요:
**한 줄 요약**: (오늘 시장 분위기를 25~40자로 압축)
이어서 시장 전반의 분위기·분위기를 만든 핵심 사건·투자자가 가장 주목할 흐름을 3~5문장으로 서술하세요.

## 🔥 핵심 이슈 TOP 5
번호 목록. 각 항목 형식: `N. **이슈명** — 무슨 일인지 · 왜 중요한지 · 영향을 받는 업종` (2~3문장)

## 📈 호재 · 📉 악재 정리
- 호재로 읽히는 흐름과 근거 / 악재·부담으로 읽히는 흐름과 근거를 나누어 불릿으로 정리하세요(같은 뉴스도 종목마다 영향이 다를 수 있음을 한 줄 덧붙이기).

## 🎯 관련 종목 살펴보기
- 뉴스에 직접 언급된 한국 상장사와, 영향을 받을 수 있는 연관 종목을 각각 '종목 — 연결되는 이유 — 확인할 포인트' 형식으로 정리하세요.

## ⚠️ 리스크 · 불확실성
- 뉴스에서 아직 확정되지 않은 부분, 확인이 필요한 전제, 투자 리스크

## 💡 점검 포인트 (참고용)
- 단기(1주 이내) / 중기(1~3개월) 관점에서 투자자가 직접 확인해 볼 체크포인트(권유·매매 지시 표현 금지)

---
[필수] 분석 마지막에 아래 JSON 블록을 반드시 포함하세요.
반드시 한국거래소(KOSPI/KOSDAQ) **실제 상장 회사명**만 포함하세요. 기술 용어, 해외 기업, 팀명은 제외하세요.

```json
{
  "mentioned": ["종목A", "종목B"],
  "related":   ["종목C"],
  "sentiment": {"종목A": 1, "종목B": -1, "종목C": 0},
  "title_ko": ""
}
```

※ 종목A·B·C 는 형식 예시일 뿐이니 그대로 쓰지 말고, 위 뉴스에서 실제로 식별한 회사명으로 채우세요. 확실하지 않으면 빈 리스트([])로 두세요.
mentioned: 뉴스 목록에 직접 언급된 한국 상장사 / related: 동종업계·공급망 관점에서 간접적으로 영향을 받을 수 있는 한국 상장사
sentiment: 오늘 뉴스가 각 종목에 미치는 영향의 분류 — 호재 1 / 중립 0 / 악재 -1 (식별한 모든 종목 포함, 분류 참고용). title_ko 는 빈 문자열("")로 두세요.
"""

GENERAL_DEFAULT = r"""당신은 경제 뉴스 에디터입니다. 아래 문서를 초보 투자자도 이해할 수 있게 요약하세요.

[제목] {title}
[출처] {source}
[본문]
{text}

[작성 지침]
- '## 한눈에 보기' (3~5줄 핵심 요약) → '## 주요 내용' (불릿 위주, 내용을 빠짐없이 담을 만큼 충분히 — 최소 7개 이상, 각 불릿은 수치·근거 포함해 1~3문장) → '## 시사점' (2~4문단) 구조
- 지나치게 축약하지 말고 원문의 내용을 최대한 담으세요(단, 문서에 없는 내용 창작 금지). 원문 문장을 그대로 옮기지 말고 새 문장으로 쓰세요.
- 전문용어는 괄호로 쉽게 풀어쓰기. 과장·투자권유 표현 금지. 문서에 없는 수치 창작 금지.
- 응답 맨 마지막 줄에 반드시 아래 JSON 한 줄 출력:
META_JSON: {"seo_title":"핵심 키워드가 들어간 제목 (40자 내외)","tags":["태그1","태그2","태그3","태그4","태그5"]}
"""

SENTI_ALL_DEFAULT = r"""당신은 20년 경력의 한국 주식시장 애널리스트입니다. 최근 {days}일간 저장된 뉴스분석 기록을 종목별로 집계해,
"직접 언급되며 긍정(호재)으로 분류된 날"이 많은 순으로 정렬한 목록입니다. 이 패턴을 정보 제공 관점에서 정리해 주세요.

※ 매우 중요 — 이 데이터의 한계를 먼저 이해하세요: 이 순위는 이 사이트에 분석·저장된 뉴스 기사에서 추출된 것으로, 시장 전체 뉴스를 다 훑은 게 아닙니다.
삼성전자·SK하이닉스처럼 원래 모든 시장뉴스에 등장하는 초대형주는 긍정 언급도 많지만 부정 언급도 같이 많을 수 있습니다(아래 "직접부정 X일"을 함께 확인하세요).
긍정 비율이 높고(예: 90% 이상) 언급 자체는 상대적으로 적은 종목이 더 뚜렷한 개별 종목 호재를 반영하는 경우도 있습니다.

[뉴스 감성 집계 순위 — 최근 {days}일]
{block}

작성 지침 — 아래 섹션 구조를 정확히 지켜 주세요:

[뉴스 심리 총평]
전반적으로 어떤 업종·테마에 긍정 뉴스가 몰려있는지 3~4문장으로 요약하세요.

[긍정 보도가 꾸준했던 종목]
긍정 비율이 높고 언급이 꾸준한 종목 2~3개를 골라, 데이터(긍정일수·비율)를 근거로 설명하세요. 가격변화 데이터가 없으면 주가와의 관계는 언급하지 마세요.

[주의가 필요한 경우]
직접부정 언급도 함께 많은 종목(긍정·부정이 혼재된 경우)은 단순히 "뉴스가 많다"와 "호재가 뚜렷하다"를 구분해야 한다는 점을 설명하세요.

[투자 유의사항]
뉴스와 주가의 상관관계는 인과관계가 아닙니다. 이미 알려진 뉴스에 뒤늦게 진입하면 고점 추격매수가 될 수 있고, 긍정 뉴스가 지속되다 갑자기 꺾이는 경우(호재 소진)도 있다는 점을 안내하세요.
자체 판단과 추가 확인 없이 이 목록만으로 투자하지 말라고 명확히 안내하세요. 투자 권유가 아닙니다.

규칙:
- 제공된 데이터에 없는 사실은 절대 지어내지 마세요.
- <br> 태그 없이 마크다운(**굵게**)만 사용하세요. 각 섹션은 반드시 [섹션명] 제목으로 시작하세요.
"""

SENTI_STOCK_DEFAULT = r"""당신은 20년 경력의 한국 주식시장 애널리스트입니다. 아래 종목은 최근 뉴스분석 기록에서 직접 언급되며 긍정(호재)으로 분류된 날이 {direct_pos_days}일
(긍정비율 {pos_ratio}%)로 집계된 종목입니다. 정보 제공 관점의 코멘트를 작성해 주세요(투자 권유 아님).

[종목] {name}({ticker}) | {market}
[뉴스 감성 집계] 직접긍정 {direct_pos_days}일 / 직접부정 {direct_neg_days}일 (긍정비율 {pos_ratio}%), 연관기사 긍정 {swept_pos_count}건
[최초 긍정보도 이후 주가 변화] {perf_txt} (기준일: {first_pos_date})
[저장된 관련 헤드라인]
{news_lines}

작성 지침 — 아래 섹션 구조를 정확히 지켜 주세요:

[뉴스 흐름 요약]
저장된 헤드라인들을 바탕으로 이 종목에 어떤 긍정적 흐름이 있었는지 4~6문장으로 설명하세요. 헤드라인을 인용할 때는 [1]처럼 번호로 표시하세요.

[주가와의 관계]
"최초 긍정보도 이후 주가 변화" 수치가 있다면 뉴스가 주가에 선행했는지 동행했는지 가능성을 조심스럽게 제시하세요("~일 가능성이 있습니다"). 데이터가 없으면 "가격 데이터가 확인되지 않았다"고만 안내하세요.

[체크포인트]
이 흐름이 지속될지 판단하기 위해 투자자가 추가로 확인해야 할 사항을 - 기호로 3~4개 제시하세요(실적 발표 일정, 추가 공시, 동종업계 동향 등).

[투자 유의사항]
이미 알려진 뉴스에 뒤늦게 진입하면 고점 추격매수가 될 수 있다는 점, 긍정 뉴스가 지속되다 갑자기 꺾이는 경우(호재 소진)도 있다는 점을 명확히 경고하세요.

규칙:
- 확인되지 않은 사실을 단정적으로 서술하지 마세요. 전부 가능성·추정 표현을 사용하세요.
- <br> 태그 없이 마크다운(**굵게**, - 목록)만 사용하세요. 각 섹션은 반드시 [섹션명] 제목으로 시작하세요.
"""


def _fill(body, vals):
    """{이름} 자리만 한 번에 바꾼다(본문 속 중괄호·같은 이름 글자는 건드리지 않음)."""
    return re.sub(r"\{(" + "|".join(map(re.escape, vals)) + r")\}", lambda m: str(vals[m.group(1)]), body)


@bp.route("/admin/api/news/prompt", methods=["POST"])
def api_prompt():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    mode = "general" if d.get("mode") == "general" else "stock"
    text = str(d.get("text") or "").strip()
    if len(text) < 20:
        return _err("먼저 뉴스 본문(또는 제목 목록)을 20자 이상 붙여 넣어 주세요.")
    title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:200]
    source = re.sub(r"\s+", " ", str(d.get("source") or "")).strip()[:200]
    body = prompt_get("news_analyze" if mode == "stock" else "news_general")
    p = _fill(body, {"source": source or "미상", "title": title or "(제목 없음)", "today": _now_kst().strftime("%Y년 %m월 %d일"), "text": text[:MAX_TEXT]})
    return _admin_json({"prompt": p, "mode": mode, "chars": len(p), "truncated": len(text) > MAX_TEXT})


def _extract_json(raw):
    """AI 답변에서 mentioned/related/sentiment/title_ko JSON 블록을 찾는다. (dict|None, 블록을 뺀 본문)"""
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw)
    if not m:
        m = re.search(r"```\s*(\{[\s\S]*?\"mentioned\"[\s\S]*?\})\s*```", raw)
    if m:
        try:
            return json.loads(m.group(1)), raw[:m.start()] + raw[m.end():]
        except Exception:
            raw = raw[:m.start()] + raw[m.end():]      # 깨진 JSON 블록은 읽지 못하더라도 화면 글에서는 뺀다
    k = raw.rfind('"mentioned"')
    if k >= 0:                                # 코드 블록 표시가 빠진 답변 — 중괄호를 직접 맞춰 본다
        a = raw.rfind("{", 0, k)
        if a >= 0:
            depth = 0
            for i in range(a, min(len(raw), a + 6000)):
                if raw[i] == "{":
                    depth += 1
                elif raw[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[a:i + 1]), raw[:a] + raw[i + 1:]
                        except Exception:
                            break
    return None, raw


def _senti_val(v):
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("호재", "긍정", "positive", "pos", "+1", "1"):
            return 1
        if s in ("악재", "부정", "negative", "neg", "-1"):
            return -1
        return 0
    try:
        return max(-1, min(1, int(v)))
    except Exception:
        return 0


def _validate_names(names, seen, mentioned):
    d = _dict()
    sec = _sectors()
    out = []
    for nm in names if isinstance(names, list) else []:
        nm = str(nm or "").strip()
        if len(nm) < 2 or nm.upper() in _BLOCK:
            continue
        rec = d["by_name"].get(nm)
        if not rec and len(nm) >= 3:
            low = nm.lower()
            cands = [r for r in d["entries"] if low in r["name"].lower()]       # 부분일치 폴백 — 가장 짧은 이름 우선
            rec = min(cands, key=lambda r: len(r["name"])) if cands else None
        if not rec or rec["ticker"] in seen:
            continue
        sector = sec.get(rec["ticker"], "")
        if _excluded(rec["name"], sector):
            continue
        seen.add(rec["ticker"])
        out.append({"ticker": rec["ticker"], "name": rec["name"], "market": rec["market"], "sector": sector, "mentioned": mentioned,
                    "reason": "AI 식별: 직접 언급" if mentioned else "AI 식별: 연관 수혜", "ai_name": nm})
    return out


def _db_extra(full, seen, limit):
    out = []
    if limit <= 0:
        return out
    toks = _tokenize(full)
    pm = _prefix_map(toks)
    sec = _sectors()
    for r in _dict()["entries"]:                   # 이름 긴 순 — 'SK하이닉스'가 'SK'보다 먼저
        if r["ticker"] in seen:
            continue
        why = _match(r["name"], toks, pm, full)
        if not why or _excluded(r["name"], sec.get(r["ticker"], "")):
            continue
        seen.add(r["ticker"])
        out.append({"ticker": r["ticker"], "name": r["name"], "market": r["market"], "sector": sec.get(r["ticker"], ""), "mentioned": True, "reason": f"본문 직접 언급 ({why})"})
        if len(out) >= limit:
            break
    return out


def parse_stock_answer(raw, title="", article=""):
    """원본 /api/news-analyze-full 의 후처리(4~9단계)를 그대로: JSON 블록 → 종목 사전 검증 → 본문 매칭 → 테마 보완 → 감성 부착."""
    raw = str(raw or "").strip()
    warnings = []
    js, rest = _extract_json(raw)
    found = isinstance(js, dict) and "mentioned" in js
    if not isinstance(js, dict):
        js = None
    if js is None:
        warnings.append("답변 끝의 ```json 블록을 찾지 못했어요. AI 답변 마지막의 JSON까지 통째로 복사했는지 확인해 주세요(종목은 본문에서 찾은 것만 보여줘요).")
        js = {"mentioned": [], "related": []}
    ai_text = re.sub(r"\n-{3,}\n?", "\n", rest).strip()
    full = (str(title or "") + " " + str(article or "")).strip() or ai_text
    seen = set()
    stocks = _validate_names(js.get("mentioned"), seen, True) + _validate_names(js.get("related"), seen, False)
    if not _dict()["entries"]:
        warnings.append("종목 사전(ticker_names)이 비어 있어 종목을 확인하지 못했어요. 관리자에게 종목목록 갱신을 요청해 주세요.")
    if len(stocks) < 8:
        stocks += _db_extra(full, seen, 10 - len(stocks))
    if len(stocks) < 5:
        stocks += _theme_extra(full, seen, 6 - len(stocks))
    stocks.sort(key=lambda s: 0 if s["mentioned"] else 1)
    smap = js.get("sentiment") if isinstance(js.get("sentiment"), dict) else {}
    for s in stocks:
        v = smap.get(s["name"])
        if v is None and s.get("ai_name"):
            v = smap.get(s["ai_name"])                 # AI 가 쓴 표기명으로도 한 번 더 찾는다(표기 차이로 호재/악재가 사라지는 것 방지)
        s["senti"] = _senti_val(v)
        s.pop("ai_name", None)
    stocks = stocks[:40]
    if not stocks and js.get("mentioned") is not None:
        warnings.append("확인된 상장사가 없어요. 뉴스가 특정 상장사와 무관하거나 AI가 회사명을 적지 않았을 수 있어요.")
    return {"ai_text": ai_text[:120000], "stocks": stocks, "title_ko": str(js.get("title_ko") or "").strip()[:200], "has_json": found,
            "warnings": warnings, "mode": "stock"}


def parse_general_answer(raw, title=""):
    raw = str(raw or "").strip()
    meta = None
    for m in re.finditer(r"META_JSON\s*:\s*(\{.*?\})", raw, re.S):
        try:
            meta = json.loads(m.group(1))
        except Exception:
            continue
    out = re.sub(r"\n?META_JSON\s*:\s*\{.*?\}\s*", "\n", raw, flags=re.S).rstrip()
    tags = []
    if isinstance(meta, dict) and isinstance(meta.get("tags"), list):
        tags = [str(x).strip()[:30] for x in meta["tags"] if str(x).strip()][:8]
    return {"ai_text": out[:120000], "seo_title": (str((meta or {}).get("seo_title") or "").strip()[:120] if isinstance(meta, dict) else "") or str(title or "").strip()[:120] or "문서 요약",
            "tags": tags, "warnings": [] if meta else ["답변 끝의 META_JSON 줄을 찾지 못했어요(요약 본문은 그대로 보여줘요)."], "mode": "general", "stocks": []}



# ══════════════════════════════════════════════════════════════
# 전체 뉴스 대시보드 · 전체 AI 총평 · URL 분석 · 관련종목 시세(그래프)
# ══════════════════════════════════════════════════════════════
def _overview(cat):
    """뉴스 목록 전체를 한 번에 집계 — 호재/악재 건수, 테마, 언론사, 많이 언급된 종목. (AI 없이 단어·종목 사전 규칙)"""
    key = ("nw_ov", EPOCH[0], cat)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    items, note = _market_news(cat)
    cnt = {"p": 0, "n": 0, "x": 0, "z": 0}
    th_n, th_p, th_ng, press = Counter(), Counter(), Counter(), Counter()
    stocks = {}
    for i, it in enumerate(items):
        c = classify(it["title"])
        cnt[c["k"]] += 1
        full = it["title"] + " " + (it.get("sn") or "")
        for th in themes_of(full, 1)[:3]:
            th_n[th] += 1
            if c["k"] == "p":
                th_p[th] += 1
            elif c["k"] == "n":
                th_ng[th] += 1
        if it.get("press"):
            press[it["press"]] += 1
        for r in _db_extra(full, set(), 4):
            e = stocks.setdefault(r["ticker"], {"ticker": r["ticker"], "name": r["name"], "market": r["market"], "sector": r["sector"], "n": 0, "pos": 0, "neg": 0, "idx": []})
            e["n"] += 1
            e["idx"].append(i)
            if c["k"] == "p":
                e["pos"] += 1
            elif c["k"] == "n":
                e["neg"] += 1
    top = sorted(stocks.values(), key=lambda e: (-e["n"], -(e["pos"] - e["neg"])))[:10]
    out = {"cat": cat, "label": _CATS[cat][1], "n": len(items), "asof": _now_kst().strftime("%Y-%m-%d %H:%M"),
           "counts": {"호재성": cnt["p"], "악재성": cnt["n"], "혼재": cnt["x"], "중립": cnt["z"]},
           "themes": [{"name": k, "n": v, "pos": th_p[k], "neg": th_ng[k]} for k, v in th_n.most_common(8)],
           "press": [{"name": k, "n": v} for k, v in press.most_common(6)], "stocks": top, "note": note}
    _cache_set(key, out, 180 if items else 20)
    return out


@bp.route("/admin/api/news/overview")
def api_overview():
    deny = _admin_deny()
    if deny:
        return deny
    if not _fok("overview"):
        return _lock("overview")
    cat = request.args.get("cat", "main")
    return _admin_json(_overview(cat if cat in _CATS else "main"))


@bp.route("/admin/api/news/overview/prompt", methods=["POST"])
def api_overview_prompt():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    cat = str(d.get("cat") or "main")
    cat = cat if cat in _CATS else "main"
    items, note = _market_news(cat)
    if not items:
        return _err(note or "가져온 뉴스가 없어요. 잠시 뒤 다시 눌러 주세요.")
    ov = _overview(cat)
    lines = []
    for i, it in enumerate(items, 1):
        sn = (it.get("sn") or "").strip()
        lines.append(f"{i}. [{it.get('press') or '-'} {it.get('date') or ''}] {it['title']}" + (f" — {sn[:160]}" if sn else ""))
    heads = "\n".join(lines)
    stats = "· 호재성 {p}건 · 악재성 {n}건 · 혼재 {x}건 · 중립 {z}건\n· 자주 나온 테마: {th}\n· 제목에 자주 나온 종목: {st}".format(
        p=ov["counts"]["호재성"], n=ov["counts"]["악재성"], x=ov["counts"]["혼재"], z=ov["counts"]["중립"],
        th=", ".join(f"{t['name']}({t['n']})" for t in ov["themes"][:6]) or "없음",
        st=", ".join(f"{s['name']}({s['n']})" for s in ov["stocks"][:8]) or "없음")
    body = prompt_get("news_overview")
    p = _fill(body, {"today": _now_kst().strftime("%Y년 %m월 %d일"), "cat": _CATS[cat][1], "count": len(items), "stats": stats, "headlines": heads})
    tk = _tk()
    _cache_set(("nw_body", tk), heads, 1800)
    return _admin_json({"prompt": p, "title": f"전체 뉴스 총평 · {_CATS[cat][1]}", "tk": tk, "chars": len(p), "count": len(items)})


def _tk():
    return os.urandom(8).hex()


# ── URL 한 줄로 분석: 기사 주소 → 제목·출처·본문(서버가 읽어 AI 요청문 안에만 넣는다. 저장·화면 표시 없음) ──
_URL_HITS = {}
_URL_LOCK = threading.Lock()
_SRC_MAP = {"yna.co.kr": "연합뉴스", "yonhapnews.co.kr": "연합뉴스", "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "chosun.com": "조선일보",
            "biz.chosun.com": "조선비즈", "joongang.co.kr": "중앙일보", "donga.com": "동아일보", "hani.co.kr": "한겨레", "sedaily.com": "서울경제",
            "etnews.com": "전자신문", "zdnet.co.kr": "지디넷코리아", "news.naver.com": "네이버뉴스", "n.news.naver.com": "네이버뉴스",
            "edaily.co.kr": "이데일리", "newsis.com": "뉴시스", "fnnews.com": "파이낸셜뉴스", "asiae.co.kr": "아시아경제", "mt.co.kr": "머니투데이",
            "news1.kr": "뉴스1", "heraldcorp.com": "헤럴드경제", "biz.heraldcorp.com": "헤럴드경제"}
_BODY_SEL = ["article#dic_area", "div#dic_area", "div#newsct_article", "div#news_read", "div.articleCont", "div.news_end", "div#articletxt",
             "div.news_cnt_detail_wrap", "div.art_txt", "section.article-body", "div#article_body", "div.news_body", "div.article_view",
             "div#articleBody", "div.article_txt", "div[itemprop='articleBody']", "article"]
_MAX_HTML = 2_500_000


def _public_host(host):
    if not host or len(host) > 200:
        raise ValueError("주소가 올바르지 않아요.")
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        raise ValueError("주소를 찾을 수 없어요. 주소를 다시 확인해 주세요.")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except Exception:
            raise ValueError("주소를 확인할 수 없어요.")
        if not ip.is_global:
            raise ValueError("내부망·사설 주소는 열 수 없어요.")


def _check_url(u):
    pr = urlparse(u)
    if pr.scheme not in ("http", "https") or not pr.hostname:
        raise ValueError("http:// 또는 https:// 로 시작하는 기사 주소를 넣어 주세요.")
    if pr.port not in (None, 80, 443):
        raise ValueError("사용할 수 없는 포트의 주소예요.")
    if "@" in (pr.netloc or ""):
        raise ValueError("계정 정보가 들어 있는 주소는 열 수 없어요.")
    _public_host(pr.hostname)
    return pr


def _decode(raw, ctype):
    declared = None
    m = re.search(r"charset=[\"']?([\w\-]+)", ctype or "", re.I)
    if m:
        declared = m.group(1).lower()
    if not declared:
        m2 = re.search(rb"charset=[\"']?([\w\-]+)", raw[:4096], re.I)
        if m2:
            declared = m2.group(1).decode("ascii", "ignore").lower()
    if declared in ("ks_c_5601-1987", "ksc5601", "euckr", "euc_kr", "cp949", "ms949"):
        declared = "euc-kr"
    for cand in (declared, "utf-8", "euc-kr", "cp949"):
        if not cand:
            continue
        try:
            return raw.decode(cand)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _fetch_article(url):
    """공개 기사 주소 → {title, source, body}. 내부망 접근 차단·리다이렉트 매 단계 검사·용량 제한."""
    from bs4 import BeautifulSoup
    cur = url.strip()
    if len(cur) > 1500:
        raise ValueError("주소가 너무 길어요.")
    pr = _check_url(cur)
    low = (pr.hostname or "").lower()
    if low.endswith("youtube.com") or low.endswith("youtu.be"):
        raise ValueError("유튜브 주소는 아직 지원하지 않아요. 기사 주소를 넣어 주세요.")
    if low.endswith("news.google.com"):
        raise ValueError("구글 뉴스 주소는 기사 원문 주소를 열 수 없어요. 언론사 기사 주소(또는 네이버 뉴스 주소)를 넣어 주세요.")
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6"}
    resp = None
    for _ in range(6):
        r = C._RAW_HTTP.get(cur, timeout=(5, 10), headers=hdr, _redirects=0)         # 본체의 단순 HTTP 클라이언트(requests 는 서버에서 멈춘 적이 있어 쓰지 않음) — 이동은 우리가 한 단계씩 검사하며 따라간다
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            cur = urljoin(cur, r.headers["location"])
            _check_url(cur)
            continue
        resp = r
        break
    if resp is None:
        raise ValueError("주소가 너무 많이 이동해서 열 수 없어요.")
    if resp.status_code >= 400:
        raise ValueError(f"기사 사이트가 열리지 않아요(HTTP {resp.status_code}). 사이트가 접근을 막았을 수 있어요.")
    ctype = resp.headers.get("content-type", "")
    if ctype and not re.search(r"html|xml|text", ctype, re.I):
        raise ValueError("웹 기사 페이지가 아니에요.")
    raw = resp.content[:_MAX_HTML]
    html = _decode(raw, ctype)
    soup = BeautifulSoup(html, "html.parser")
    og = soup.select_one("meta[property='og:title']")
    title = (og.get("content") or "").strip() if og and og.get("content") else ""
    if not title:
        h1 = soup.select_one("h1")
        title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "")
    title = re.sub(r"\s+", " ", title)[:200]
    body_el = None
    for sel in _BODY_SEL:
        e = soup.select_one(sel)
        if e and len(e.get_text(strip=True)) > 100:
            body_el = e
            break
    if body_el is None:
        divs = soup.find_all("div")
        body_el = max(divs, key=lambda d: len(d.get_text(strip=True)), default=None) if divs else None
    body = ""
    if body_el is not None:
        for t in body_el.find_all(["script", "style", "aside", "nav", "figure", "button", "iframe", "form"]):
            t.decompose()
        body = re.sub(r"\n{3,}", "\n\n", body_el.get_text(separator="\n", strip=True)).strip()
    note = ""
    if len(body) < 80:
        d = soup.select_one("meta[property='og:description']") or soup.select_one("meta[name='description']")
        if d and d.get("content"):
            body = d["content"].strip()
            note = "기사 본문을 읽지 못해 요약문(메타 설명)으로 분석해요."
        else:
            raise ValueError("본문을 읽지 못했어요. 사이트가 접근을 막았거나 로그인이 필요한 기사일 수 있어요. 본문을 직접 붙여 넣는 [🤖 AI 해석] 탭을 이용해 주세요.")
    host = (urlparse(cur).hostname or "").lower()
    host2 = re.sub(r"^(www|m)\.", "", host)
    ogs = soup.select_one("meta[property='og:site_name']")
    source = _SRC_MAP.get(host2) or (ogs.get("content").strip() if ogs and ogs.get("content") else host2)
    return {"title": title, "source": source[:60], "body": body[:MAX_TEXT], "url": cur, "note": note}


def _url_throttle():
    if not _gw():
        return False
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")[:60]
    now = time.time()
    with _URL_LOCK:
        hits = [t for t in _URL_HITS.get(ip, []) if now - t < 60]
        if len(hits) >= 8:
            _URL_HITS[ip] = hits
            return True
        hits.append(now)
        _URL_HITS[ip] = hits
        if len(_URL_HITS) > 2000:
            for k in list(_URL_HITS)[:1000]:
                _URL_HITS.pop(k, None)
    return False


@bp.route("/admin/api/news/url", methods=["POST"])
def api_url():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if _url_throttle():
        return _err("잠시 뒤에 다시 눌러 주세요. 1분에 8번까지 읽을 수 있어요.", 429)
    d = _json_body()
    mode = "general" if d.get("mode") == "general" else "stock"
    try:
        art = _fetch_article(str(d.get("url") or ""))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        print(f"[뉴스분석] URL 읽기 오류(무시): {type(e).__name__}: {e}")
        return _err("기사를 읽지 못했어요. 주소를 확인하거나 잠시 뒤 다시 시도해 주세요.")
    body = prompt_get("news_analyze" if mode == "stock" else "news_general")
    p = _fill(body, {"source": art["source"] or "미상", "title": art["title"] or "(제목 없음)", "today": _now_kst().strftime("%Y년 %m월 %d일"), "text": art["body"]})
    tk = _tk()
    _cache_set(("nw_body", tk), art["body"], 1800)
    return _admin_json({"title": art["title"], "source": art["source"], "url": art["url"], "prompt": p, "mode": mode, "tk": tk, "chars": len(art["body"]),
                        "excerpt": re.sub(r"\s+", " ", art["body"])[:160], "note": art["note"]})


# ── 관련종목 미니 그래프(최근 시세) ──
def _mini_one(tk):
    key = ("nw_mini", tk)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    out = None
    try:
        import datetime as _dt
        st = (_dt.datetime.now() - _dt.timedelta(days=75)).strftime("%Y-%m-%d")
        df = C._fetch_ohlcv(tk, st)
        if df is not None and len(df) >= 2:
            cl = [float(x) for x in df["Close"].dropna().tolist()][-30:]
            if len(cl) >= 2:
                last = cl[-1]

                def pct(n):
                    return round((last / cl[-1 - n] - 1) * 100, 2) if len(cl) > n and cl[-1 - n] else None
                out = {"closes": [round(x, 2) for x in cl], "last": round(last, 2), "chg": pct(1), "chg5": pct(5), "chg20": pct(20)}
    except Exception as e:
        print(f"[뉴스분석] {tk} 시세 조회 오류(무시): {type(e).__name__}")
    _cache_set(key, out if out else {}, 600 if out else 60)
    return out or {}


@bp.route("/admin/api/news/mini", methods=["POST"])
def api_mini():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if not _fok("overview"):
        return _lock("overview")
    d = _json_body()
    tks = []
    for t in d.get("tickers") if isinstance(d.get("tickers"), list) else []:
        t = str(t or "").strip().upper()
        if TICKER_RE.match(t) and t not in tks:
            tks.append(t)
    tks = tks[:12]
    if not tks:
        return _admin_json({"minis": {}})
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(_mini_one, tks))
    return _admin_json({"minis": {t: r for t, r in zip(tks, res) if r}})


# ══════════════════════════════════════════════════════════════
# 블로그 글 만들기(관리자 전용 — 어떤 기능에도 등록하지 않음 → 회원 화면에서는 404)
#   AI 분석문 + 관련 종목(호재/악재 참고 표시·30일 시세) 을 네이버 블로그 붙여넣기용 HTML 로 만든다.
#   기사 원문은 담지 않는다(출처 이름과 원문 링크만). 화면에서 보내 준 분석문·종목만 쓰고 서버에 저장하지 않는다.
# ══════════════════════════════════════════════════════════════
BLOG_SECS = (("summary", "한 줄 요약"), ("stocks", "관련 종목·시세"), ("ai", "AI 분석 본문"), ("src", "출처·원문 링크"))
_FENCE = re.compile(r"```.*?```", re.S)


def _blog_clean(text):
    t = _FENCE.sub("", str(text or "")[:40000])
    return "\n".join(l for l in t.replace("\r", "").split("\n") if not re.match(r"^\s*\*\*한 줄 요약\*\*", l)).strip()


def _blog_sum(text):
    m = re.search(r"\*\*한 줄 요약\*\*\s*[:：]\s*(.+)", str(text or ""))
    return re.sub(r"\*\*", "", m.group(1)).strip()[:200] if m else ""


def build_news_blog(d):
    E = B.E
    now = _now_kst()
    date_k = B.date_korean(now)
    kind = str(d.get("kind") or "news")
    if kind not in ("news", "url", "ov"):
        kind = "news"
    inc = d.get("inc") if isinstance(d.get("inc"), dict) else {}
    inc = {k: bool(inc.get(k, True)) for k, _ in BLOG_SECS}
    ai_raw = str(d.get("ai_text") or "")[:40000]
    ai = _blog_clean(ai_raw)
    sm = _blog_sum(ai_raw)
    ntitle = str(d.get("news_title") or "").strip()[:150]
    source = str(d.get("source") or "").strip()[:40]
    url = str(d.get("url") or "").strip()
    url = url if re.match(r"^https?://[^\s<>\"'\\]{4,400}$", url) else ""
    stocks = [x for x in (_norm_stock(s) for s in (d.get("stocks") if isinstance(d.get("stocks"), list) else [])[:12]) if x]
    titles = B.extract_titles(ai_raw)
    title = str(d.get("title") or "").strip()[:150]
    if not title:
        if titles:
            title = titles[0]
        elif kind == "ov":
            title = f"오늘의 주요 뉴스 AI 총평 — 호재·악재 흐름 정리 ({date_k})"
        else:
            title = f"{ntitle or '뉴스'} — 뉴스 AI 분석·관련 종목 ({date_k})"
    names = [s["name"] for s in stocks if s["name"]][:4]
    kw = (["뉴스 분석", "주식 뉴스", "관련주"] + [n + " 뉴스" for n in names[:3]] + [s["ticker"] for s in stocks[:2]])[:8]
    tags, tag_html = B.hashtags(names, date_k, extra=["뉴스분석", "주식뉴스", "관련주", "호재악재"])
    h = [B.seo_box(title, ("오늘 뉴스 전체의 흐름과 자주 나온 종목을 AI로 정리했습니다." if kind == "ov" else "뉴스 한 건을 AI로 풀어 읽고 관련 종목을 정리했습니다.") + f" (기준 {date_k})", kw)]
    sub = f"{E(source or '네이버 금융')} · {date_k}" + (f"<br>관련 종목 {len(stocks)}개" if stocks else "")
    h.append(B.head_box("NEWS BRIEF", E((ntitle or title)[:150]), sub))
    if inc["summary"] and sm:
        h.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;border-collapse:collapse;{B.FONT}"><tr><td bgcolor="#eff6ff" style="background-color:#eff6ff;border-left:6px solid #1e3a8a;padding:14px 18px;">'
                 f'<div style="font-size:12px;font-weight:800;color:#1e3a8a;margin-bottom:4px;">&#128221; 한 줄 요약</div><div style="font-size:16px;font-weight:800;color:#0f172a;line-height:1.7;">{E(sm)}</div></td></tr></table>')
    h.append(B.engage_box())
    if inc["stocks"] and stocks:
        with ThreadPoolExecutor(max_workers=6) as ex:
            ms = list(ex.map(_mini_one, [s["ticker"] for s in stocks]))
        rows = ""
        for s, m_ in zip(stocks, ms):
            m_ = m_ or {}
            sv = s["senti"]
            chip = ("#fef2f2", "#c62828", "호재 분류") if sv > 0 else (("#eff6ff", "#1565c0", "악재 분류") if sv < 0 else ("#f3f4f6", "#4b5563", "중립"))
            ch = m_.get("chg")
            c20 = m_.get("chg20")
            px = (f"{m_['last']:,.0f}원" if m_.get("last") else "-")
            chg = "-" if ch is None else f'<span style="color:{B.updown(ch)}">{ch:+.2f}%</span>'
            ch20 = "-" if c20 is None else f'<span style="color:{B.updown(c20)}">{c20:+.2f}%</span>'
            rows += (f'<tr><td style="padding:8px 6px;border-bottom:1px solid #f0f0f0;font-size:13.5px;font-weight:800;color:{B.NAVY};">{E(s["name"] or s["ticker"])}'
                     f'<div style="font-size:11px;font-weight:400;color:#94a3b8;">{E(s["ticker"])}{" · " + E(s["market"]) if s["market"] else ""}{" · " + E(s["sector"]) if s["sector"] else ""}</div></td>'
                     f'<td align="center" style="padding:8px 4px;border-bottom:1px solid #f0f0f0;"><span style="background-color:{chip[0]};color:{chip[1]};font-size:11px;font-weight:800;padding:2px 7px;">{chip[2]}</span>'
                     f'<div style="font-size:11px;color:#94a3b8;margin-top:2px;">{"직접 언급" if s["mentioned"] else "연관"}</div></td>'
                     f'<td align="right" style="padding:8px 6px;border-bottom:1px solid #f0f0f0;font-size:13px;">{px}</td>'
                     f'<td align="right" style="padding:8px 6px;border-bottom:1px solid #f0f0f0;font-size:13px;">{chg}</td>'
                     f'<td align="right" style="padding:8px 6px;border-bottom:1px solid #f0f0f0;font-size:13px;">{ch20}</td></tr>')
        th = "".join(f'<td align="{a}" style="padding:8px 6px;background-color:#eef2ff;font-size:12px;font-weight:700;color:#312e81;border-bottom:1px solid #c7d2fe;">{t}</td>'
                     for t, a in (("종목", "left"), ("분류(참고)", "center"), ("현재가", "right"), ("전일", "right"), ("20일", "right")))
        h.append(B.side_title("&#128202; 관련 종목 <span style=\"font-size:12px;font-weight:700;color:#94a3b8;\">(뉴스에서 식별 · 시세는 최근 종가 기준)</span>", "#1e3a8a"))
        h.append('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;' + B.FONT + '"><tr>' + th + "</tr>" + rows + "</table>")
        h.append('<p style="font-size:11.5px;color:#9ca3af;margin:4px 0 0;">호재·악재 분류는 AI 또는 단어 규칙의 참고 값이며, 특정 종목을 권유하는 내용이 아닙니다. 뉴스에 언급됐다고 주가가 오르거나 내리는 것은 아닙니다.</p>')
    if inc["ai"] and ai:
        secs = B.split_sections(ai)
        used = False
        for num in sorted(k for k in secs if k > 0):
            ttl, body = secs[num]
            if body.strip():
                h.append(B.section_card("&#128240;", ttl or f"분석 {num}", "", body, "#1e3a8a", "#f5f8ff"))
                used = True
        pre = secs.get(0, ("", ""))[1].strip()
        if pre or not used:
            h.append(B.ai_to_html(pre if used else ai))
    if inc["src"] and (url or source):
        lk = (f'<a href="{E(url)}" target="_blank" style="color:#1d4ed8;font-weight:700;">기사 원문 보기</a>' if url else "")
        h.append(f'<p style="font-size:12px;color:#6b7280;margin:14px 0 0;">&#128279; 출처: {E(source or "네이버 금융")}{" · " + lk if lk else ""} · 기사 내용은 저작권이 언론사에 있어 원문을 싣지 않고 링크로만 안내합니다. 공시는 DART·KIND에서 직접 확인하세요.</p>')
    h.append(B.risk_box())
    h.append(tag_html)
    body = "".join(h)
    return {"html": body, "title": title, "titles": titles, "tags": tags, "size": len(body), "ok_size": len(body) < 400000}


@bp.route("/admin/api/news/blog", methods=["POST"])
def api_blog():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body() or {}
    if len(str(d.get("ai_text") or "").strip()) < 30:
        return _admin_json({"error": "먼저 AI 분석을 끝내야 블로그 글을 만들 수 있어요."}, 400)
    b = build_news_blog(d)
    t = str(d.get("ticker") or "").strip().upper()
    if B.LOG_TICKER_RE.match(t):
        logs, warn = B.dup_info(t, "news")
        b.update({"dups": logs, "dup_warn": warn})
    return _admin_json(b)


@bp.route("/admin/api/news/parse", methods=["POST"])
def api_parse():
    """붙여넣은 AI 답변을 구조화해 돌려준다. 아무것도 저장하지 않는다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    raw = str(d.get("text") or "").strip()
    if len(raw) < 40:
        return _err("AI 답변이 너무 짧아요. 답변 전체를 복사해 붙여 넣어 주세요.")
    if len(raw) > 200000:
        return _err("답변이 너무 길어요.")
    title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip()[:200]
    if d.get("mode") == "general":
        return _admin_json(parse_general_answer(raw, title))
    article = str(d.get("article") or "")[:MAX_TEXT]
    tk = str(d.get("tk") or "")
    if tk and re.fullmatch(r"[0-9a-f]{16}", tk):
        article = _cache_get(("nw_body", tk)) or article        # 서버가 읽어 둔 본문(화면으로는 돌려주지 않음) — 종목 본문 매칭에만 쓴다
    return _admin_json(parse_stock_answer(raw, title, article))


@bp.route("/admin/api/news/leader/prompt", methods=["POST"])
def api_leader_prompt():
    """긍정뉴스 지속종목 AI 프롬프트(1차 총평 · 2차 종목 코멘트). 집계는 서버가 직접 계산한다."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if not _fok("leader"):
        return _lock("leader")
    d = _json_body()
    try:
        days = max(7, min(90, int(d.get("days") or 21)))
        mn = max(1, min(10, int(d.get("min_days") or 2)))
    except Exception:
        return _err("기간 값이 올바르지 않아요.")
    arts, st = _articles(days)
    rows = leaderboard(arts, mn)[:25]
    if not rows:
        return _err("집계된 종목이 없어요. 기간을 늘리거나 최소 보도일을 낮춰 보세요.")
    if d.get("kind") == "stock":
        t = str(d.get("ticker") or "").strip().upper()
        r = next((x for x in rows if x["ticker"] == t), None)
        if not r:
            return _err("집계 목록에 없는 종목이에요.")
        lines = "\n".join(f"[{i + 1}] {h['date']} ({'긍정' if h['senti'] == 1 else '부정'}) {h['title']}" for i, h in enumerate(r["headlines"])) or "(저장된 헤드라인 없음)"
        p = _fill(prompt_get("news_senti_stock"), {"direct_pos_days": r["direct_pos_days"], "pos_ratio": r["pos_ratio"], "name": r["name"], "ticker": r["ticker"],
                                                   "market": r["market"], "direct_neg_days": r["direct_neg_days"], "swept_pos_count": r["swept_pos_count"],
                                                   "perf_txt": "데이터 없음", "first_pos_date": r["first_pos_date"] or "?", "news_lines": lines})
        return _admin_json({"prompt": p, "kind": "stock", "name": r["name"]})
    block = "\n".join(f"- {r['name']}({r['ticker']}) 점수:{r['score']} | 직접긍정 {r['direct_pos_days']}일(비율 {r['pos_ratio']}%) / 직접부정 {r['direct_neg_days']}일 | 가격변화 데이터 없음"
                      for r in rows[:15]) or "(없음)"
    return _admin_json({"prompt": _fill(prompt_get("news_senti_all"), {"days": days, "block": block}), "kind": "overview", "count": len(rows[:15])})


# ══════════════════════════════════════════════════════════════
# 화면 (JS) — 관리자 탭과 이용자 화면(/m/news)이 같은 코드를 쓴다
# ══════════════════════════════════════════════════════════════
TAB_JS = r"""
var NW={view:'latest',arch:{days:'30',view:'stock',ticker:'',tname:'',theme:'',senti:'',day:'',press:'',q:'',page:1},cat:'main',lead:{days:21,min:2,ans:{}},theme:{days:14},board:{q:'',page:1},pre:null,cur:null,parsed:null,parsedFor:'',res:null,css:false};
var NWV=[['latest','📰 뉴스룸','latest'],['stock','🔎 종목 뉴스','stock'],['cls','🏷 분류 체험','classify'],['theme','🧩 테마·이슈','themes'],['lead','📈 긍정뉴스 지속','leader'],['arch','🗄 뉴스 DB','archive'],['board','🗂 보관함','board'],['ai','🤖 AI 해석','ai']];
var NWCSS='.nwH{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:#fff;border-radius:16px;padding:16px 18px;margin-bottom:10px}.nwH h2{margin:0;font-size:22px}.nwH p{margin:6px 0 0;font-size:13px;color:#cbd5e1;line-height:1.55}'+
'.nwWarn{background:#fffbeb;border:1px solid #fcd34d;color:#92400e;border-radius:10px;padding:8px 12px;font-size:12.5px;line-height:1.55;margin:8px 0}.nwWarn.sm{font-size:12px;padding:6px 10px}'+
'.nwTabs{display:flex;gap:6px;overflow-x:auto;padding:2px 0 8px;margin-bottom:6px;-webkit-overflow-scrolling:touch}.nwTabs button{flex:0 0 auto;border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:8px 13px;font-size:13px;cursor:pointer;white-space:nowrap}.nwTabs button.on{background:#0f172a;color:#fff;border-color:#0f172a}.nwTabs button.lk{opacity:.7}'+
'.nwS{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:14px 15px;margin:0 0 12px}.nwS>h3{margin:0 0 4px;font-size:16px}.nwS>.ds{font-size:12.5px;color:#64748b;line-height:1.55;margin:0 0 10px}'+
'.nwIt{padding:9px 0;border-bottom:1px solid #eef2f7}.nwIt:last-child{border-bottom:none}.nwIt a.tt{color:#0f172a;font-weight:700;text-decoration:none;overflow-wrap:anywhere;line-height:1.5}.nwIt a.tt:hover{text-decoration:underline}.nwIt .mt{font-size:11.5px;color:#64748b;margin-top:2px}.nwIt .sn{font-size:12px;color:#94a3b8;margin-top:2px;overflow-wrap:anywhere}'+
'.nwCh{display:inline-block;border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:800;margin:0 4px 2px 0;white-space:nowrap}.nwCh.p{background:#fee2e2;color:#b91c1c}.nwCh.n{background:#dbeafe;color:#1d4ed8}.nwCh.x{background:#fef3c7;color:#92400e}.nwCh.z{background:#f1f5f9;color:#475569}.nwCh.t{background:#ede9fe;color:#5b21b6}.nwCh.a{background:#ecfdf5;color:#047857}'+
'.nwTiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px;margin:0 0 10px}.nwTile{background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:8px 11px}.nwTile .l{font-size:11px;color:#64748b;font-weight:700}.nwTile .v{font-size:18px;font-weight:900;color:#0f172a}'+
'.nwTw{overflow-x:auto;-webkit-overflow-scrolling:touch}.nwT{border-collapse:collapse;width:100%;font-size:13px}.nwT th{background:#f1f5f9;color:#475569;font-weight:800;padding:8px 9px;text-align:left;white-space:nowrap}.nwT td{padding:8px 9px;border-bottom:1px solid #eef2f7;vertical-align:top}.nwT td.r,.nwT th.r{text-align:right}'+
'.nwIn{border:1px solid #cbd5e1;border-radius:8px;padding:8px 10px;font:inherit;font-size:14px;background:#fff;min-width:0}.nwTa{width:100%;box-sizing:border-box;min-height:140px;border:1px solid #cbd5e1;border-radius:8px;padding:9px;font:inherit;font-size:13.5px;line-height:1.55}'+
'.nwPick{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.nwPick button{border:1px solid #cbd5e1;background:#fff;border-radius:10px;padding:7px 11px;font-size:13px;cursor:pointer}'+
'.nwCard{border:1px solid #e5e7eb;border-radius:12px;padding:10px 12px;margin:8px 0;background:#fff}.nwCard .hd{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.nwCard .nm{font-weight:900;font-size:15px}.nwCard .sc{margin-left:auto;font-weight:900;font-size:17px}.nwBar{height:8px;background:#eef2f7;border-radius:5px;overflow:hidden;margin:6px 0}.nwBar i{display:block;height:100%;border-radius:5px}'+
'.nwSum{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:9px 12px;margin:8px 0;font-size:14px;line-height:1.6}.nwH4{margin:14px 0 4px;font-size:15px;background:#0f172a;color:#fff;border-radius:8px;padding:6px 10px}.nwH5{margin:10px 0 3px;font-size:14px;border-left:4px solid #1e3a8a;padding-left:8px}.nwP{margin:4px 0;font-size:14px;line-height:1.7;overflow-wrap:anywhere}.nwLi{margin:3px 0 3px 4px;font-size:14px;line-height:1.65;padding-left:14px;text-indent:-14px;overflow-wrap:anywhere}.nwNo{margin:5px 0;font-size:14px;line-height:1.65;overflow-wrap:anywhere}.nwNo b.n{display:inline-block;min-width:22px}'+
'.nwPv{font-size:13px;line-height:1.55;padding:8px 10px}.nwSecC{border:1px solid #e5e7eb;border-radius:12px;padding:10px 12px;margin:8px 0}.nwSecC .t{font-weight:900;margin-bottom:4px}.nwCard .mt{font-size:12px;color:#64748b;margin-top:3px;line-height:1.5}.nwCard .sn{font-size:12px;color:#64748b;margin-top:3px;overflow-wrap:anywhere}';
function nwCss(){if(NW.css||document.getElementById('nwCss'))return;NW.css=true;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';var s=document.createElement('style');s.id='nwCss';if(nn)s.setAttribute('nonce',nn);s.textContent=NWCSS;document.head.appendChild(s);nrEnv()}
function nwSec(parent,title,desc){var s=el('div','nwS');s.appendChild(el('h3',null,title));if(desc)s.appendChild(el('p','ds',desc));parent.appendChild(s);return s}
function nwTk(node,t){node.setAttribute('data-tk',t);node.className=(node.className?node.className+' ':'')+'tkl';node.title='눌러서 종목분석 열기';
 if(!window.GoStock){node.onclick=function(e){e.preventDefault();if(typeof window.__openTicker==='function'){window.__openTicker(t)}else{window.open('/?t='+encodeURIComponent(t),'mini_main')}}}return node}
function nwLink(href,text,cls){var a=el('a',cls||null,text);if(/^https?:\/\//.test(href||'')){a.href=href;a.target='_blank';a.rel='noopener noreferrer'}return a}
function nwChip(k,text,title){var c=el('span','nwCh '+k,text);if(title)c.title=title;return c}
function nwSent(v){return v>0?nwChip('p','호재','AI/기록의 분류 값(참고용)'):(v<0?nwChip('n','악재','AI/기록의 분류 값(참고용)'):nwChip('z','중립'))}
function nwNum(v,d){if(v==null)return '-';return Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d==null?0:d})}
function nwWait(box,t){box.innerHTML='';box.appendChild(el('p','note','⏳ '+(t||'불러오는 중…')))}
function nwFail(box,e){box.innerHTML='';box.appendChild(el('p','note bad','불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.'))}
function nwNote(parent){parent.appendChild(el('div','nwWarn sm','호재성·악재성은 단어를 기준으로 한 분류 참고용이며 투자 권유가 아닙니다. 원문과 공시를 직접 확인하세요.'))}
function nwInline(parent,s){String(s).split(/(\*\*[^*]+\*\*)/).forEach(function(p){if(!p)return;if(/^\*\*[^*]+\*\*$/.test(p))parent.appendChild(el('b',null,p.slice(2,-2)));else parent.appendChild(document.createTextNode(p))})}
function nwMd(parent,text){String(text||'').split(/\r?\n/).forEach(function(ln){var s=ln.replace(/\s+$/,'');if(!s.trim())return;var m;
 if((m=/^\*\*한 줄 요약\*\*\s*[:：]\s*(.+)$/.exec(s))){var b=el('div','nwSum');b.appendChild(el('b',null,'📝 한 줄 요약 — '));nwInline(b,m[1]);parent.appendChild(b)}
 else if((m=/^###\s+(.*)$/.exec(s))){var h=el('div','nwH5');nwInline(h,m[1].replace(/\*\*/g,''));parent.appendChild(h)}
 else if((m=/^##\s+(.*)$/.exec(s))){var h2=el('div','nwH4');nwInline(h2,m[1].replace(/\*\*/g,''));parent.appendChild(h2)}
 else if((m=/^\s*[-•*]\s+(.*)$/.exec(s))){var li=el('div','nwLi');li.appendChild(document.createTextNode('• '));nwInline(li,m[1]);parent.appendChild(li)}
 else if((m=/^(\d{1,2})\.\s+(.*)$/.exec(s))){var no=el('div','nwNo');no.appendChild(el('b','n',m[1]+'.'));nwInline(no,m[2]);parent.appendChild(no)}
 else{var p=el('div','nwP');nwInline(p,s);parent.appendChild(p)}})}
function nwSections(parent,text){var cur=null,buf=[];function flush(){if(cur===null&&!buf.join('').trim())return;var c=el('div','nwSecC');if(cur)c.appendChild(el('div','t',cur));nwMd(c,buf.join('\n'));parent.appendChild(c)}
 String(text||'').split(/\r?\n/).forEach(function(ln){var m=/^\[([^\[\]]+)\]\s*$/.exec(ln.trim());if(m&&!/^\d+$/.test(m[1])){flush();cur=m[1];buf=[]}else buf.push(ln)});flush()}
/* 판 전체 */
function nwLoad(p){nwCss();p.innerHTML='';
 var hd=el('div','nwH');hd.appendChild(el('h2',null,'📰 뉴스분석'));hd.appendChild(el('p',null,'뉴스 제목을 모아 보고, 호재·악재 단어와 테마를 참고용으로 분류해 보는 곳이에요. 종목 이름을 누르면 종목분석으로 이동해요.'));p.appendChild(hd);
 p.appendChild(el('div','nwWarn sm','⚠ 호재성·악재성 표시는 단어 기준의 분류 참고용이며 투자 권유가 아닙니다. 원문과 공시를 직접 확인하세요.'));
 var tabs=el('div','nwTabs');tabs.id='nwTabs';p.appendChild(tabs);var body=el('div');body.id='nwBody';p.appendChild(body);nwShow(NW.view)}
function nwShow(v){NW.view=v;var tabs=$('nwTabs'),body=$('nwBody');if(!tabs||!body)return;tabs.innerHTML='';
 NWV.forEach(function(x){var ok=ftOk(x[2]);var b=el('button',(x[0]===v?'on':'')+(ok?'':' lk'),(ok?'':'🔒 ')+x[1]);b.onclick=function(){nwShow(x[0])};tabs.appendChild(b)});
 body.innerHTML='';var box=el('div');body.appendChild(box);
 var fn={latest:nrRoom,stock:nwVStock,cls:nwVCls,theme:nwVTheme,lead:nwVLead,arch:nwVArch,board:nwVBoard,ai:nwVAI}[v];if(fn)fn(box)}
function nwLocked(s,fid,sample){s.appendChild(el('p','note',sample));ftSec(s,fid)}
/* ══ 🗄 뉴스 DB(v186): 가져온 뉴스를 분류해 쌓아 둔 보관함 — 종목별·테마별·호재/악재·날짜·언론사 ══ */
function nwArchQ(extra){var A=NW.arch,o={days:A.days,ticker:A.ticker,theme:A.theme,senti:A.senti,day:A.day,press:A.press,q:A.q};if(extra)Object.keys(extra).forEach(function(k){o[k]=extra[k]});var a=[];Object.keys(o).forEach(function(k){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]))});return a.join('&')}
function nwVArch(box){var A=NW.arch;var s=nwSec(box,'🗄 뉴스 DB — 분류해서 쌓아 둔 뉴스','뉴스를 가져올 때마다(주요·속보·많이 본 뉴스, 종목 뉴스, 종목분석 화면의 뉴스) 호재/악재·테마·관련 종목과 함께 자동 저장돼요. 나중에 종목·테마별 추세를 보려는 자료예요. 제목·언론사·링크·발행시각만 저장하고 기사 원문은 저장하지 않아요.');
 if(!ftOk('archive')){nwLocked(s,'archive','예) 종목별·테마별·호재/악재별 뉴스 건수와 날짜별 추세를 볼 수 있어요.');return}
 var sum=el('div');sum.id='nwAS';s.appendChild(sum);var fl=el('div');fl.id='nwAF';s.appendChild(fl);var out=el('div');out.id='nwAL';s.appendChild(out);
 nwArchSum()}
function nwArchSum(){var A=NW.arch,sum=$('nwAS');if(!sum)return;nwWait(sum,'뉴스 DB를 읽는 중…');
 api('/admin/api/news/arch/summary?days='+A.days).then(function(j){sum=$('nwAS');if(!sum)return;sum.innerHTML='';if(j.error){NeedNote(sum,j.error,'','note bad');return}
  var bar=el('div','bar');[['7','7일'],['14','14일'],['30','30일'],['90','90일'],['0','전체']].forEach(function(x){var b=el('button','thCh'+(A.days===x[0]?' on':''),x[1]);b.type='button';b.onclick=function(){A.days=x[0];A.page=1;nwArchSum()};bar.appendChild(b)});sum.appendChild(bar);
  var tl=el('div','nwTiles');[['저장된 뉴스',j.total.toLocaleString('ko-KR')+'건'],['보관 기간',j.first?(j.first.slice(5)+' ~ '+j.last.slice(5)):'-'],['오늘 발행',j.today+'건'],['선택 기간',j.n.toLocaleString('ko-KR')+'건'],['호재성',(j.by.p||0)+'건'],['악재성',(j.by.n||0)+'건']].forEach(function(x){var t=el('div','nwTile');t.appendChild(el('div','l',x[0]));t.appendChild(el('div','v',x[1]));tl.appendChild(t)});sum.appendChild(tl);
  if(!j.total){sum.appendChild(el('p','note','아직 저장된 뉴스가 없어요. [📰 뉴스룸]에서 뉴스를 불러오거나 종목 뉴스를 검색하면 이 자리에 쌓이기 시작해요.'))}
  if(j.state&&j.state.err)sum.appendChild(el('p','note bad','⚠ 마지막 저장 오류: '+j.state.err));
  /* 날짜별 추세(호재·악재 쌓임 막대) */
  if(j.days.length){var c=el('div','nwSecC');c.appendChild(el('div','t','📅 날짜별 뉴스 건수 (눌러서 그날 뉴스 보기)'));var mx=1;j.days.forEach(function(d){mx=Math.max(mx,d.p+d.n+d.x+d.z)});
   var w=el('div');w.style.cssText='display:flex;align-items:flex-end;gap:3px;height:96px;overflow-x:auto;padding-bottom:2px';
   j.days.forEach(function(d){var tot=d.p+d.n+d.x+d.z;var col=el('div');col.style.cssText='flex:1 0 14px;max-width:34px;display:flex;flex-direction:column;justify-content:flex-end;height:100%;cursor:pointer'+(A.day===d.day?';outline:2px solid #0f172a;outline-offset:1px':'');col.title=d.day+' · 전체 '+tot+'건 (호재 '+d.p+' / 악재 '+d.n+')';
    [['z','#cbd5e1'],['x','#fcd34d'],['n','#3b82f6'],['p','#ef4444']].forEach(function(k){if(!d[k[0]])return;var i=document.createElement('i');i.style.cssText='display:block;width:100%;background:'+k[1]+';height:'+Math.max(2,Math.round(d[k[0]]*82/mx))+'px';col.appendChild(i)});
    col.onclick=function(){A.day=(A.day===d.day?'':d.day);A.page=1;nwArchSum()};w.appendChild(col)});c.appendChild(w);
   c.appendChild(el('div','mt','🟥 호재성 · 🟦 악재성 · 🟨 혼재 · ⬜ 중립 — 맨 왼쪽이 가장 오래된 날'));sum.appendChild(c)}
  /* 분류 표 */
  var tabs=el('div','bar');var V=[['stock','🏷 종목별'],['theme','🧩 테마별'],['senti','👍👎 호재·악재'],['press','📰 언론사별']];V.forEach(function(x){var b=el('button','thCh'+(A.view===x[0]?' on':''),x[1]);b.type='button';b.onclick=function(){A.view=x[0];nwArchSum()};tabs.appendChild(b)});sum.appendChild(tabs);
  var rows=[];if(A.view==='stock')rows=j.stocks.map(function(x){return {k:x.ticker,name:(x.name||x.ticker)+' ('+x.ticker+')',n:x.n,p:x.p,neg:x.neg,set:function(){A.ticker=x.ticker;A.tname=x.name}}});
  else if(A.view==='theme')rows=j.themes.map(function(x){return {k:x.name,name:x.name,n:x.n,p:x.p,neg:x.neg,set:function(){A.theme=x.name}}});
  else if(A.view==='press')rows=j.press.map(function(x){return {k:x.name,name:x.name,n:x.n,p:x.p,neg:x.neg,set:function(){A.press=x.name}}});
  else rows=[['p','호재성'],['n','악재성'],['x','혼재'],['z','중립']].map(function(x){return {k:x[0],name:x[1],n:j.by[x[0]]||0,p:x[0]==='p'?(j.by.p||0):0,neg:x[0]==='n'?(j.by.n||0):0,set:function(){A.senti=x[0]}}});
  if(!rows.length){sum.appendChild(el('p','note','이 기간에는 해당 분류가 없어요.'))}else{
   var T=el('div','nwTw'),t=el('table','nwT'),h=el('tr');['이름','뉴스','호재','악재','호재 비율'].forEach(function(x,i){h.appendChild(el('th',i?'r':'',x))});t.appendChild(h);
   rows.forEach(function(r){var tr=el('tr');tr.style.cursor='pointer';tr.appendChild(el('td',null,r.name));tr.appendChild(el('td','r',String(r.n)));tr.appendChild(el('td','r',String(r.p)));tr.appendChild(el('td','r',String(r.neg)));var d=r.p+r.neg;tr.appendChild(el('td','r',d?Math.round(r.p*100/d)+'%':'-'));tr.onclick=function(){r.set();A.page=1;nwArchFilt();nwArchList()};t.appendChild(tr)});T.appendChild(t);sum.appendChild(T);
   sum.appendChild(el('p','note','호재 비율 = 호재성 ÷ (호재성+악재성). 제목의 단어를 기준으로 한 참고 분류라 틀릴 수 있어요. 행을 누르면 그 분류의 뉴스를 아래에 보여 줘요.'))}
  nwArchFilt();nwArchList()})}
function nwArchFilt(){var A=NW.arch,f=$('nwAF');if(!f)return;f.innerHTML='';var bar=el('div','bar');var inp=el('input','nwIn');inp.type='text';inp.placeholder='제목 검색';inp.maxLength=40;inp.value=A.q;bar.appendChild(inp);
 bar.appendChild(bt('검색','bt3',function(){A.q=inp.value.trim();A.page=1;nwArchList()}));inp.onkeydown=function(e){if(e.key==='Enter'){A.q=inp.value.trim();A.page=1;nwArchList()}};
 function chip(txt,fn){var c=nwChip('a',txt+' ✕');c.style.cursor='pointer';c.onclick=function(){fn();A.page=1;nwArchSum()};bar.appendChild(c)}
 if(A.ticker)chip('종목 '+(A.tname||A.ticker),function(){A.ticker='';A.tname=''});if(A.theme)chip('테마 '+A.theme,function(){A.theme=''});if(A.senti)chip({p:'호재성',n:'악재성',x:'혼재',z:'중립'}[A.senti],function(){A.senti=''});if(A.day)chip('날짜 '+A.day,function(){A.day=''});if(A.press)chip('언론사 '+A.press,function(){A.press=''});
 var a=el('a','bt3','📄 CSV 내려받기');a.href='/admin/api/news/arch/csv?'+nwArchQ();a.setAttribute('download','');a.style.cssText='text-decoration:none;display:inline-block';bar.appendChild(a);
 if(!MEMBER_MODE){bar.appendChild(bt('♻ 다시 분류','bt3',function(){if(!confirm('분류 단어를 고친 뒤 저장된 모든 뉴스의 호재/악재·테마를 새 기준으로 다시 매길까요?'))return;apiJ('/admin/api/news/arch/reclass',{}).then(function(z){toast(z.error?z.error:(z.n+'건을 다시 분류했어요'));nwArchSum()})}));
  bar.appendChild(bt('🗑 오래된 뉴스 지우기','bt3',function(){var d=prompt('몇 일보다 오래된 뉴스를 지울까요? (최소 30일)','180');if(!d)return;apiJ('/admin/api/news/arch/prune',{days:Number(d)||180}).then(function(z){toast(z.error?z.error:(z.n+'건을 지웠어요'));nwArchSum()})}))}
 f.appendChild(bar)}
function nwArchList(){var A=NW.arch,out=$('nwAL');if(!out)return;var f=$('nwAF');if(f){var a=f.querySelector('a');if(a)a.href='/admin/api/news/arch/csv?'+nwArchQ()}
 nwWait(out,'뉴스를 불러오는 중…');api('/admin/api/news/arch/list?'+nwArchQ({page:A.page,size:50})).then(function(j){out=$('nwAL');if(!out)return;out.innerHTML='';if(j.error){NeedNote(out,j.error,'','note bad');return}
  out.appendChild(el('p','note','조건에 맞는 뉴스 '+j.total.toLocaleString('ko-KR')+'건'));if(!j.items.length)return;
  j.items.forEach(function(x){var r=el('div','nwIt');var h=el('div');h.appendChild(nwChip(x.senti,x.label));x.themes.forEach(function(t){h.appendChild(nwChip('t',t))});x.stocks.forEach(function(sk){var c=nwChip('a',sk.name||sk.ticker);nwTk(c,sk.ticker);h.appendChild(c)});
   h.appendChild(x.url?nwLink(x.url,x.title,'tt'):el('span','tt',x.title));r.appendChild(h);
   r.appendChild(el('div','mt',[x.press,x.at,(x.seen>1?'본 횟수 '+x.seen:''),(x.related?'관련 기사 '+x.related+'건':'')].filter(Boolean).join(' · ')));
   if(x.pos||x.neg)r.appendChild(el('div','sn','근거 단어: '+[x.pos,x.neg].filter(Boolean).join(', ')));out.appendChild(r)});
  var pg=el('div','bar');if(A.page>1)pg.appendChild(bt('◀ 이전','bt3',function(){A.page--;nwArchList()}));if(j.page*j.size<j.total)pg.appendChild(bt('다음 ▶','bt3',function(){A.page++;nwArchList()}));out.appendChild(pg)}).catch(function(){nwFail(out)})}
/* 뉴스 목록(최신·종목 공통) */
function nwItems(out,j){out.innerHTML='';if(j.error){NeedNote(out,j.error,'','note bad');return}
 var it=j.items||[];if(!it.length){NeedNote(out,j.note,'가져온 뉴스가 없어요.');return}
 if(j.summary){var tl=el('div','nwTiles');[['호재성',j.summary['호재성']],['악재성',j.summary['악재성']],['혼재',j.summary['혼재']],['중립',j.summary['중립']]].forEach(function(x){var t=el('div','nwTile');t.appendChild(el('div','l',x[0]));t.appendChild(el('div','v',x[1]+'건'));tl.appendChild(t)});out.appendChild(tl);nwNote(out)}
 else if((j.locked||[]).indexOf('classify')>=0){var lb=el('div','nwWarn sm','🔒 호재성·악재성·테마 분류 표시는 등급이 열려 있어야 볼 수 있어요. ');var a=el('a',null,'자세히');a.href='#';a.onclick=function(e){e.preventDefault();lockDlg('classify')};lb.appendChild(a);out.appendChild(lb)}
 it.forEach(function(x){var r=el('div','nwIt');var h=el('div');
  if(x.cls){h.appendChild(nwChip(x.cls.k,x.cls.label));(x.cls.themes||[]).forEach(function(t){h.appendChild(nwChip('t',t))})}
  h.appendChild(x.url?nwLink(x.url,x.title,'tt'):el('span','tt',x.title));r.appendChild(h);
  r.appendChild(el('div','mt',[x.press,x.date,(x.related?'관련 기사 '+x.related+'건':'')].filter(Boolean).join(' · ')));
  if(x.cls&&(x.cls.pos.length||x.cls.neg.length)){r.appendChild(el('div','sn','근거 단어: '+x.cls.pos.concat(x.cls.neg).join(', ')))}
  if(x.snippet)r.appendChild(el('div','sn',x.snippet));out.appendChild(r)});
 out.appendChild(el('p','note','출처: '+(j.source||'네이버 금융')+' · 제목을 누르면 언론사 원문으로 이동해요.'))}
/* ══ 뉴스룸(v154): 위=대시보드 · 왼쪽=뉴스 목록 · 오른쪽=분석 작업대 ══ */
var NR={cat:'main',items:[],lat:null,ov:null,sel:-1,q:'',f:'all',th:'',res:{},minis:{},ws:'',load:0,urlv:'',imgP:null,dashP:null,dashOpen:false};
var NRFLOW=['ai','img','blog','post'];
var NRACTS={
 ai:function(next){var rs=NR.res[NR.ws],x=NR.sel>=0?NR.items[NR.sel]:null;if(rs){next();return}if(MiniFlow.forced('news')&&x)nrStartNews(x)},
 img:function(next){var rs=NR.res[NR.ws];if(rs&&rs.img){next();return}
  /* 분석 직후에는 이미지 화면이 아직 안 만들어졌을 수 있어요(30ms 뒤 생성) → 만들어질 때까지 기다리거나 직접 만들고, 끝나면 이어가요 */
  function go(n){if(NR.res[NR.ws]!==rs)return;var P=NR.imgP||(NR.mountImg&&NR.mountImg());if(!P){if(n<24)setTimeout(function(){go(n+1)},250);return}
   var e=$('nrImgR');if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'nearest'});
   P.gen(true).then(function(){var done=function(){var it=P.items&&P.items();return !!(it&&it.length)};if(done()){next();return}
    var t=0,iv=setInterval(function(){t++;if(NR.res[NR.ws]!==rs){clearInterval(iv);return}if(done()){clearInterval(iv);next()}else if(t>40)clearInterval(iv)},500)},function(){})}
  go(0)}, blog:function(next){if(MEMBER_MODE||!NR.blogP)return;var rs=NR.res[NR.ws];if(rs&&rs.blog&&NR.blogP.built()){next();return}var e=$('nrBlogR');if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'nearest'});NR.blogP.rebuild().then(function(j){if(j&&!j.error)next()})},
 post:function(next){if(nrPostGo(true))next()}};
function nrPostGo(auto){var P=NR.blogP;if(MEMBER_MODE||!P)return false;var rs=NR.res[NR.ws];if(P.built()){var b=$('nrBlogR');if(b&&b.scrollIntoView)b.scrollIntoView({behavior:'smooth',block:'nearest'});P.copyOpen(auto);return true}
 if(!(rs&&rs.blog)){if(!auto)toast('먼저 ④ 글 만들기를 해 주세요');return false}
 P.rebuild().then(function(j){if(j)P.copyOpen(auto)});return true}
var NRCSS='.nrRoot{display:block}.nrDash{background:#fff;border:1px solid #dbe3ee;border-radius:16px;padding:14px 16px;margin:0 0 12px;box-shadow:0 2px 10px rgba(15,23,42,.05)}'+
'.nrDh{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:8px}.nrDh h2{margin:0;font-size:20px}.nrAs{font-size:12px;color:#64748b}'+
'.nrBar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0}.nrBar button{font:inherit;font-size:13px;border-radius:999px;padding:7px 13px;cursor:pointer;border:1px solid #cbd5e1;background:#fff;color:#0f172a}.nrBar button.on{background:#0f172a;color:#fff;border-color:#0f172a}.nrBar button.pri{background:#1e3a8a;color:#fff;border-color:#1e3a8a;font-weight:800}.nrBar .sp{flex:1}'+
'.nrSb{display:flex;height:16px;border-radius:9px;overflow:hidden;background:#eef2f7;margin:2px 0 10px}.nrSb i{display:block;height:100%}'+
'.nrCols{display:grid;grid-template-columns:1fr 1fr;gap:14px}.nrBox h4{margin:0 0 6px;font-size:13.5px;color:#334155}.nrRw{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:13px}.nrRw .nm{flex:0 0 96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700;cursor:pointer;background:none;border:0;padding:0;font:inherit;font-weight:700;text-align:left;color:#0f172a}.nrRw .nm:hover{text-decoration:underline}.nrRw .tr{flex:1;height:10px;background:#eef2f7;border-radius:6px;overflow:hidden;min-width:40px}.nrRw .tr i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#60a5fa,#1e3a8a)}.nrRw .ct{flex:0 0 auto;font-size:11.5px;color:#64748b;white-space:nowrap}.nrRw.on .nm{color:#1e3a8a;text-decoration:underline}'+
'.nrGrid{display:grid;grid-template-columns:minmax(300px,5fr) minmax(0,7fr);gap:12px;align-items:start}.nrL,.nrR{min-width:0}'+
'.nrL{background:#fff;border:1px solid #dbe3ee;border-radius:16px;padding:10px 12px}.nrL .nrLs{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:6px}.nrL .nrLs input{flex:1;min-width:120px}.nrL .nrLs button{font:inherit;font-size:12.5px;border-radius:999px;padding:5px 10px;cursor:pointer;border:1px solid #cbd5e1;background:#fff}.nrL .nrLs button.on{background:#0f172a;color:#fff;border-color:#0f172a}'+
'.nrList{max-height:76vh;overflow-y:auto;-webkit-overflow-scrolling:touch}'+
'.nrIt{display:flex;gap:8px;align-items:flex-start;padding:9px 8px;border-bottom:1px solid #eef2f7;cursor:pointer;border-radius:8px}.nrIt:hover{background:#f8fafc}.nrIt.on{background:#eff6ff;box-shadow:inset 3px 0 0 #1e3a8a}.nrIt .nrTx{flex:1;min-width:0}.nrIt .tt{font-weight:700;color:#0f172a;line-height:1.5;overflow-wrap:anywhere;font-size:14px}.nrIt .mt{font-size:11.5px;color:#64748b;margin-top:2px}'+
'.nrOrg{flex:0 0 auto;align-self:center;border:1px solid #94a3b8;color:#1e3a8a;background:#fff;border-radius:8px;padding:5px 9px;font-size:12px;font-weight:800;text-decoration:none;white-space:nowrap}.nrOrg:hover{background:#1e3a8a;color:#fff;border-color:#1e3a8a}'+
'.nrR{position:sticky;top:8px;max-height:calc(100vh - 16px);overflow-y:auto}'+
'.nrU{background:#fff;border:1px solid #dbe3ee;border-radius:16px;padding:10px 12px;margin-bottom:10px}.nrU .nrUr{display:flex;gap:6px;flex-wrap:wrap}.nrU input{flex:1;min-width:160px}.nrU .hp{font-size:11.5px;color:#64748b;margin-top:5px;line-height:1.5}'+
'.nrNc{background:#fff;border:1px solid #bfdbfe;border-left:5px solid #1e3a8a;border-radius:14px;padding:12px 14px;margin-bottom:10px}.nrNc h3{margin:6px 0 4px;font-size:17px;line-height:1.5;overflow-wrap:anywhere}.nrNc .mt{font-size:12px;color:#64748b}.nrNc .bar{margin-top:8px}'+
'.nrEm{background:#f8fafc;border:1px dashed #cbd5e1;border-radius:14px;padding:22px 16px;color:#475569;font-size:13.5px;line-height:1.75;text-align:center}'+
'.nrSg{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px;margin:6px 0 10px}.nrSc{border:1px solid #e5e7eb;border-radius:12px;padding:9px 11px;background:#fff}.nrSh{display:flex;gap:5px;align-items:center;flex-wrap:wrap}.nrSh .nm{font-size:15px}.nrSc .mt{font-size:11.5px;color:#64748b;margin:2px 0}.nrSc .sn{font-size:12px;color:#475569;margin-top:4px;line-height:1.5;overflow-wrap:anywhere}'+
'.nrMn{display:flex;align-items:center;gap:8px;font-size:12px;color:#64748b;min-height:34px}.nrMn canvas{width:110px;height:34px;flex:0 0 auto}.nrMn .px{font-weight:800;color:#0f172a}.nrMn .up{color:#e11d48;font-weight:800}.nrMn .dn{color:#2563eb;font-weight:800}'+
'.nrRh{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.nrRh h3{margin:0;flex:1;font-size:16px;min-width:140px}.nrImg{margin-top:8px}'+
'.nrStp{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}.nrStp button{flex:1 1 128px;display:flex;align-items:center;gap:8px;text-align:left;border:1.5px solid #bfdbfe;background:#fff;color:#1e3a8a;border-radius:12px;padding:7px 10px;font:inherit;font-size:13px;font-weight:800;cursor:pointer;line-height:1.35}.nrStp button small{display:block;font-weight:600;font-size:11px;color:#64748b}.nrStp .n{width:24px;height:24px;border-radius:50%;background:#bfdbfe;color:#1e3a8a;display:flex;align-items:center;justify-content:center;font-weight:900;flex:0 0 auto}.nrStp .done{border-color:#86efac;background:#f0fdf4}.nrStp .done .n{background:#16a34a;color:#fff}.nrStp .cur{border-color:#1e3a8a;box-shadow:0 0 0 3px rgba(30,58,138,.16)}'+
'.nrBlog{margin-top:10px;scroll-margin-top:60px}'+
'@media(max-width:900px){.nrGrid{grid-template-columns:1fr}.nrR{position:static;max-height:none;overflow:visible}.nrCols{grid-template-columns:1fr}.nrList{max-height:60vh}}';
function nrEnv(){if(document.getElementById('nrCss'))return;var nn='';var n=document.querySelector('style[nonce],script[nonce]');if(n)nn=n.nonce||n.getAttribute('nonce')||'';var s=document.createElement('style');s.id='nrCss';if(nn)s.setAttribute('nonce',nn);s.textContent=NRCSS;document.head.appendChild(s)}
/* 원문 읽기: 화면 오른쪽 절반 창 (네이버 기사는 액자(iframe)로 못 담아서 별도 창) */
function nwReader(url,ev){if(ev&&(ev.ctrlKey||ev.shiftKey||ev.metaKey||ev.button===1))return true;
 var aw=(window.screen&&screen.availWidth)||1280,ah=(window.screen&&screen.availHeight)||800;var w=Math.max(520,Math.min(960,Math.round(aw/2)));var l=((screen.availLeft)||0)+aw-w,t=(screen.availTop)||0;
 var f='popup=yes,width='+w+',height='+ah+',left='+l+',top='+t+',scrollbars=yes,resizable=yes';var wnd=null;try{wnd=window.open('','nwReader',f)}catch(e){wnd=null}
 if(!wnd){return true}
 try{wnd.opener=null}catch(e){}try{wnd.location.href=url;wnd.focus()}catch(e){return true}return false}
function nrOrig(url){var a=el('a','nrOrg','원문 ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.title='화면 오른쪽에 원문 창을 열어요(Ctrl+클릭: 새 탭)';
 a.onclick=function(e){e.stopPropagation();if(!nwReader(url,e))e.preventDefault()};return a}
/* 시세 미니 그래프 */
function nrSpark(cv,cl){var w=110,h=34,dp=window.devicePixelRatio||1;cv.width=w*dp;cv.height=h*dp;var c=cv.getContext('2d');c.scale(dp,dp);var mn=Math.min.apply(null,cl),mx=Math.max.apply(null,cl),rg=mx-mn||1,up=cl[cl.length-1]>=cl[0],col=up?'#dc2626':'#2563eb';
 c.beginPath();cl.forEach(function(v,i){var x=2+(w-4)*i/(cl.length-1),y=h-3-(h-6)*(v-mn)/rg;if(i)c.lineTo(x,y);else c.moveTo(x,y)});c.lineWidth=2;c.lineJoin='round';c.strokeStyle=col;c.stroke();c.lineTo(w-2,h);c.lineTo(2,h);c.closePath();c.globalAlpha=.12;c.fillStyle=col;c.fill()}
function nrPaintMinis(){var bs=document.querySelectorAll('[data-mn]');for(var i=0;i<bs.length;i++){var b=bs[i];if(b.getAttribute('data-done')==='1')continue;var m=NR.minis[b.getAttribute('data-mn')];
 if(m===undefined||m===null){if(!b.firstChild)b.textContent='시세 불러오는 중…';continue}
 b.setAttribute('data-done','1');b.innerHTML='';if(!m||!m.closes){b.textContent='시세 정보 없음';continue}
 var cv=document.createElement('canvas');b.appendChild(cv);nrSpark(cv,m.closes);var t=el('div');t.appendChild(el('div','px',nwNum(m.last)+'원'));
 var ch=el('div',m.chg>0?'up':(m.chg<0?'dn':''),'전일 '+(m.chg==null?'-':(m.chg>0?'+':'')+m.chg+'%')+(m.chg20==null?'':' · 20일 '+(m.chg20>0?'+':'')+m.chg20+'%'));t.appendChild(ch);b.appendChild(t)}}
function nrFetchMinis(tks){if(!ftOk('overview')){nrPaintMinis();return Promise.resolve()}var need=[];tks.forEach(function(t){if(NR.minis[t]===undefined&&need.indexOf(t)<0)need.push(t)});need=need.slice(0,12);
 if(!need.length){nrPaintMinis();return Promise.resolve()}
 need.forEach(function(t){NR.minis[t]=null});nrPaintMinis();
 return apiJ('/admin/api/news/mini',{tickers:need}).then(function(j){var m=(j&&j.minis)||{};need.forEach(function(t){NR.minis[t]=m[t]||false});nrPaintMinis()}).catch(function(){need.forEach(function(t){NR.minis[t]=false});nrPaintMinis()})}
function nrStockCards(parent,stocks){var g=el('div','nrSg');var tks=[];
 stocks.slice(0,12).forEach(function(s){var c=el('div','nrSc');var h=el('div','nrSh');h.appendChild(nwTk(el('b','nm',s.name||s.ticker),s.ticker));h.appendChild(nwSent(s.senti));h.appendChild(nwChip(s.mentioned?'a':'z',s.mentioned?'직접 언급':'연관'));c.appendChild(h);
  c.appendChild(el('div','mt',s.ticker+(s.market?' · '+s.market:'')+(s.sector?' · '+s.sector:'')));var mn=el('div','nrMn');mn.setAttribute('data-mn',s.ticker);c.appendChild(mn);
  if(s.reason)c.appendChild(el('div','sn',s.reason));g.appendChild(c);tks.push(s.ticker)});
 parent.appendChild(g);setTimeout(function(){nrFetchMinis(tks)},0)}
/* 한 줄 요약·본문 줄 뽑기(이미지용) */
function nrSum(t){var m=/\*\*한 줄 요약\*\*\s*[:：]\s*(.+)/.exec(t||'');if(m)return m[1].replace(/\*\*/g,'').trim();var ls=String(t||'').split(/\r?\n/).map(function(s){return s.trim()}).filter(function(s){return s&&!/^#/.test(s)});return ls[0]?ls[0].replace(/\*\*/g,''):''}
function nrLines(t,max){var out=[];String(t||'').split(/\r?\n/).forEach(function(s){s=s.trim();if(!s||/^#/.test(s)||/한 줄 요약/.test(s)||/^```/.test(s))return;s=s.replace(/\*\*/g,'').replace(/^[-•*]\s+/,'• ');if(out.length<max&&s.length>3)out.push(s)});return out}
/* 판 */
function nrRoom(box){nrEnv();
 var s0=el('div','nwS');s0.appendChild(el('h3',null,'📰 뉴스룸'));s0.appendChild(el('p','ds','위쪽은 오늘의 뉴스 대시보드, 왼쪽은 뉴스 목록, 오른쪽은 분석 작업대예요. 뉴스를 누르면 오른쪽에서 AI 분석·관련 종목을 보고, [원문 ↗]을 누르면 화면 오른쪽 창에 기사 원문이 열려요.'));
 if(!ftOk('latest')){box.appendChild(s0);nwLocked(s0,'latest','주요 뉴스·실시간 속보·많이 본 뉴스 제목을 모아 볼 수 있어요.');return}
 var root=el('div','nrRoot');box.appendChild(root);var d=el('div','nrDash');d.id='nrDash';root.appendChild(d);
 var g=el('div','nrGrid');var L=el('div','nrL');L.id='nrL';var R=el('div','nrR');R.id='nrR';g.appendChild(L);g.appendChild(R);root.appendChild(g);
 root.appendChild(el('div','nwWarn sm','호재성·악재성은 단어를 기준으로 한 분류 참고용이며 투자 권유가 아닙니다. AI 분석도 틀릴 수 있으니 원문과 공시를 직접 확인하세요. 기사 원문은 저장·복제하지 않고, 분석을 위해 서버가 읽은 본문은 화면에 다시 보여주지 않아요.'));
 nrLoad()}
function nrLoad(){var my=++NR.load;var L=$('nrL'),d=$('nrDash');if(!L||!d)return;nwWait(L,'뉴스를 가져오는 중…');
 var a=api('/admin/api/news/latest?cat='+encodeURIComponent(NR.cat));var b=ftOk('overview')?api('/admin/api/news/overview?cat='+encodeURIComponent(NR.cat)).catch(function(){return null}):Promise.resolve(null);
 Promise.all([a,b]).then(function(r){if(my!==NR.load)return;var j=r[0];if(j.error){L.innerHTML='';NeedNote(L,j.error,'','note bad');return}
  NR.lat=j;NR.items=j.items||[];NR.ov=(r[1]&&!r[1].error)?r[1]:null;NR.sel=-1;if(NR.ws.indexOf('n:')===0)NR.ws='';
  nrDash();nrFeed();nrWs()}).catch(function(){if(my===NR.load)nwFail(L)})}
function nrDash(){var d=$('nrDash');if(!d)return;d.innerHTML='';
 var h=el('div','nrDh');h.appendChild(el('h2',null,'📰 오늘의 뉴스 대시보드'));h.appendChild(el('span','nrAs',(NR.lat?NR.lat.label:'')+' '+NR.items.length+'건'+((NR.ov&&NR.ov.asof)?' · '+NR.ov.asof+' 기준':'')));d.appendChild(h);
 var bar=el('div','nrBar');[['main','주요 뉴스'],['flash','실시간 속보'],['rank','많이 본 뉴스']].forEach(function(c){var b=el('button',c[0]===NR.cat?'on':'',c[1]);b.onclick=function(){if(NR.cat===c[0])return;NR.cat=c[0];NR.q='';NR.f='all';NR.th='';if(NR.ws.indexOf('ov:')===0)NR.ws='';nrLoad()};bar.appendChild(b)});
 bar.appendChild(el('span','sp'));
 var hasOv=!!NR.res['ov:'+NR.cat];var ba=el('button','pri',hasOv?'🤖 전체 AI 총평 보기':'🤖 전체 AI 총평');ba.onclick=function(){if(hasOv){NR.sel=-1;NR.ws='ov:'+NR.cat;nrList();nrWs();return}nrOverall()};bar.appendChild(ba);
 var bi=el('button',null,'🖼 대시보드 이미지');bi.onclick=function(){if(!ftOk('overview')){lockDlg('overview');return}NR.dashOpen=!NR.dashOpen;nrDashImg()};bar.appendChild(bi);
 var br=el('button',null,'🔄 새로고침');br.onclick=function(){nrLoad()};bar.appendChild(br);
 bar.appendChild(adm(bt('🔄 수집 캐시 비우기','bt3',function(){apiJ('/admin/api/news/refresh',{}).then(function(){toast('캐시를 비웠어요');nrLoad()})})));d.appendChild(bar);
 var cn=NR.ov?NR.ov.counts:(NR.lat&&NR.lat.summary?NR.lat.summary:null);
 var tl=el('div','nwTiles');var tl0=[['뉴스',NR.items.length+'건']];if(cn){tl0.push(['호재성',cn['호재성']+'건'],['악재성',cn['악재성']+'건'],['혼재',cn['혼재']+'건'],['중립',cn['중립']+'건'])}
 tl0.forEach(function(x){var t=el('div','nwTile');t.appendChild(el('div','l',x[0]));t.appendChild(el('div','v',x[1]));tl.appendChild(t)});d.appendChild(tl);
 if(cn){var tot=(cn['호재성']+cn['악재성']+cn['혼재']+cn['중립'])||1;var sb=el('div','nrSb');sb.title='호재성 · 악재성 · 혼재 · 중립 비중';[['호재성','#ef4444'],['악재성','#3b82f6'],['혼재','#f59e0b'],['중립','#cbd5e1']].forEach(function(x){var i=el('i');i.style.width=(cn[x[0]]*100/tot)+'%';i.style.background=x[1];sb.appendChild(i)});d.appendChild(sb)}
 if(NR.ov){var cols=el('div','nrCols');var b1=el('div','nrBox');b1.appendChild(el('h4',null,'🧩 자주 나온 테마 (누르면 목록이 걸러져요)'));
  var mx=Math.max.apply(null,NR.ov.themes.map(function(t){return t.n}).concat([1]));
  if(!NR.ov.themes.length)b1.appendChild(el('p','note','뚜렷한 테마 키워드가 아직 없어요.'));
  NR.ov.themes.forEach(function(t){var r=el('div','nrRw'+(NR.th===t.name?' on':''));var nm=el('button','nm',t.name);nm.onclick=function(){NR.th=NR.th===t.name?'':t.name;nrFeedBar();nrList();nrDash()};r.appendChild(nm);var tr=el('div','tr');var i=el('i');i.style.width=Math.max(8,t.n*100/mx)+'%';tr.appendChild(i);r.appendChild(tr);r.appendChild(el('span','ct',t.n+'건'+(t.pos||t.neg?' · 호재 '+t.pos+' / 악재 '+t.neg:'')));b1.appendChild(r)});cols.appendChild(b1);
  var b2=el('div','nrBox');b2.appendChild(el('h4',null,'📌 제목에 자주 나온 종목 · 최근 시세'));
  if(!NR.ov.stocks.length)b2.appendChild(el('p','note','제목에서 종목 이름이 확인된 뉴스가 아직 없어요.'));
  var tks=[];NR.ov.stocks.slice(0,6).forEach(function(s){var c=el('div','nrSc');var hh=el('div','nrSh');hh.appendChild(nwTk(el('b','nm',s.name),s.ticker));hh.appendChild(el('span','m',s.n+'건 · 호재 '+s.pos+' / 악재 '+s.neg));c.appendChild(hh);var mn=el('div','nrMn');mn.setAttribute('data-mn',s.ticker);c.appendChild(mn);b2.appendChild(c);tks.push(s.ticker)});cols.appendChild(b2);d.appendChild(cols);nrFetchMinis(tks)}
 else if(!ftOk('overview')){var lk=el('div','nrBox');nwLocked(lk,'overview','예) 호재·악재 건수, 자주 나온 테마, 제목에 많이 나온 종목과 최근 시세 그래프를 한눈에 볼 수 있어요.');d.appendChild(lk)}
 else d.appendChild(el('p','note','대시보드 집계를 불러오지 못했어요. [새로고침]을 눌러 주세요.'));
 var ib=el('div','nrImg');ib.id='nrImgD';d.appendChild(ib);if(NR.dashOpen)nrDashImg(true)}
/* 대시보드 이미지 */
function nrDashStocks(){var res=NR.res['ov:'+NR.cat];if(res&&res.j.stocks&&res.j.stocks.length)return res.j.stocks.slice(0,10);
 return ((NR.ov&&NR.ov.stocks)||[]).slice(0,8).map(function(s){return {ticker:s.ticker,name:s.name,market:s.market,sector:s.sector,senti:s.pos>s.neg?1:(s.neg>s.pos?-1:0),mentioned:true,reason:'제목에 '+s.n+'번 나왔어요(호재성 '+s.pos+' · 악재성 '+s.neg+')'}})}
function nrDashImg(keep){var b=$('nrImgD');if(!b)return;if(!NR.dashOpen){b.innerHTML='';NR.dashP=null;return}
 if(!window.ImgKit||!window.NwImg){b.textContent='이미지 도우미를 불러오지 못했어요. 새로고침해 주세요.';return}
 var gen=function(scale){if(!NR.ov)return Promise.reject(new Error('대시보드 집계가 아직 없어요. 새로고침 후 다시 눌러 주세요.'));var stocks=nrDashStocks();var res=NR.res['ov:'+NR.cat];
  return nrFetchMinis(stocks.map(function(s){return s.ticker})).then(function(){return window.NwImg.dash({ov:NR.ov,label:NR.lat?NR.lat.label:'',stocks:stocks,minis:NR.minis,ai:res?{summary:nrSum(res.j.ai_text),lines:nrLines(res.j.ai_text,8)}:null},scale)})};
 NR.dashP=nrImgMount(b,{name:'뉴스대시보드',ticker:window.ImgKit.dateDir(),perStock:false,gen:gen})}
function nrImgMount(box,o){var K=window.ImgKit;if(!MEMBER_MODE&&K&&K.panel)return K.panel(box,{menu:'news',name:o.name,ticker:o.ticker,perStock:o.perStock,onDone:o.onDone,gen:o.gen});
 box.innerHTML='';var row=el('div','bar'),view=el('div','nrSg'),st=el('div','m');var S={items:null};
 var go=bt('🖼 이미지 만들기','bt',function(){go.disabled=true;go.textContent='⏳ 그리는 중…';view.innerHTML='';st.textContent='';
  Promise.resolve(K&&K.fonts?K.fonts():0).then(function(){return o.gen(2)}).then(function(items){S.items=items;items.forEach(function(it){var c=el('div','nrSc');c.appendChild(el('b',null,K.CIRC[it.idx-1]+' '+it.label));
   var pw=Math.min(720,it.canvas.width),sm=document.createElement('canvas');sm.width=pw;sm.height=Math.round(it.canvas.height*pw/it.canvas.width);sm.getContext('2d').drawImage(it.canvas,0,0,sm.width,sm.height);
   var im=new Image();im.alt=it.label;im.src=sm.toDataURL('image/png');im.className='nrPv';im.style.width='100%';im.style.height='auto';c.appendChild(im);
   c.appendChild(bt('💾 이미지 내려받기','bt2',function(){it.canvas.toBlob(function(bl){if(!bl){toast('이미지를 만들지 못했어요');return}var a=document.createElement('a');a.href=URL.createObjectURL(bl);a.download=K.fileName(it.idx,o.name,o.ticker);document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},4000)},'image/png')}));view.appendChild(c)});
   st.textContent='이미지를 만들었어요. [이미지 내려받기]로 내 기기에 저장하세요.';go.textContent='🔄 다시 만들기'}).catch(function(e){st.textContent='이미지를 만들지 못했어요: '+(e&&e.message||e);go.textContent='🖼 이미지 만들기'}).then(function(){go.disabled=false})});
 row.appendChild(go);box.appendChild(row);box.appendChild(st);box.appendChild(view);return {gen:function(){go.click();return Promise.resolve()},items:function(){return S.items},refresh:function(){}}}
/* 왼쪽: 뉴스 목록 */
function nrFeed(){var L=$('nrL');if(!L)return;L.innerHTML='';var bar=el('div');bar.id='nrFb';L.appendChild(bar);var ls=el('div','nrList');ls.id='nrList';L.appendChild(ls);nrFeedBar();nrList()}
function nrFeedBar(){var b=$('nrFb');if(!b)return;var had=document.activeElement&&document.activeElement.id==='nrQ';b.innerHTML='';var s=el('div','nrLs');
 var inp=el('input','nwIn');inp.id='nrQ';inp.type='text';inp.placeholder='제목·언론사 검색';inp.maxLength=40;inp.value=NR.q;inp.setAttribute('aria-label','뉴스 검색');inp.oninput=function(){NR.q=inp.value;nrList()};s.appendChild(inp);b.appendChild(s);
 var hasCls=NR.items.some(function(x){return x.cls});
 if(hasCls){var s2=el('div','nrLs');[['all','전체'],['p','호재'],['n','악재'],['x','혼재'],['z','중립']].forEach(function(f){var c=el('button',NR.f===f[0]?'on':'',f[1]);c.onclick=function(){NR.f=f[0];nrFeedBar();nrList()};s2.appendChild(c)});b.appendChild(s2)}
 if(NR.th){var s3=el('div','nrLs');var c=el('button','on','테마: '+NR.th+' ✕');c.onclick=function(){NR.th='';nrFeedBar();nrList();nrDash()};s3.appendChild(c);b.appendChild(s3)}
 if(had)inp.focus()}
function nrFilt(){var q=NR.q.trim().toLowerCase();return NR.items.map(function(x,i){return {x:x,i:i}}).filter(function(o){var x=o.x;if(NR.f!=='all'&&(!x.cls||x.cls.k!==NR.f))return false;if(NR.th&&(!x.cls||(x.cls.themes||[]).indexOf(NR.th)<0))return false;if(q&&((x.title||'')+' '+(x.press||'')).toLowerCase().indexOf(q)<0)return false;return true})}
function nrList(){var ls=$('nrList');if(!ls)return;ls.innerHTML='';var rows=nrFilt();
 if(!NR.items.length){NeedNote(ls,NR.lat&&NR.lat.note,'가져온 뉴스가 없어요.');return}
 if(!rows.length){ls.appendChild(el('p','note','조건에 맞는 뉴스가 없어요.'));return}
 rows.forEach(function(o){var x=o.x,r=el('div','nrIt'+(o.i===NR.sel?' on':''));r.tabIndex=0;r.setAttribute('role','button');r.setAttribute('data-i',o.i);
  var tx=el('div','nrTx');var h=el('div');if(x.cls){h.appendChild(nwChip(x.cls.k,x.cls.label))}h.appendChild(el('span','tt',x.title));tx.appendChild(h);
  tx.appendChild(el('div','mt',[x.press,x.date].filter(Boolean).join(' · ')+(NR.res['n:'+x.url]?' · ✅ AI 분석함':'')));r.appendChild(tx);if(x.url)r.appendChild(nrOrig(x.url));
  r.onclick=function(){nrSelect(o.i)};r.onkeydown=function(e){if(e.target===r&&(e.key==='Enter'||e.key===' ')){e.preventDefault();nrSelect(o.i)}};ls.appendChild(r)});
 ls.appendChild(el('p','note','출처: '+((NR.lat&&NR.lat.source)||'네이버 금융')+' · 뉴스를 누르면 오른쪽에서 분석해요.'))}
function nrSelect(i){NR.sel=i;var x=NR.items[i];NR.ws=(x&&x.url&&NR.res['n:'+x.url])?'n:'+x.url:'';nrList();nrWs();
 if(window.matchMedia&&matchMedia('(max-width:900px)').matches){var r=$('nrR');if(r&&r.scrollIntoView)r.scrollIntoView({behavior:'smooth',block:'start'})}}
/* 오른쪽: 작업대 */
function nrUrlBar(R){var s=el('div','nrU');var row=el('div','nrUr');var inp=el('input','nwIn');inp.id='nrUrl';inp.type='text';inp.placeholder='기사 주소(URL)만 붙여 넣어도 AI 분석을 만들어요';inp.maxLength=1500;inp.value=NR.urlv;inp.setAttribute('aria-label','기사 주소');inp.oninput=function(){NR.urlv=inp.value};
 var go=bt('🔗 URL로 AI 분석','bt',function(){nrUrl(inp.value)});inp.onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();nrUrl(inp.value)}};row.appendChild(inp);row.appendChild(go);s.appendChild(row);
 s.appendChild(el('div','hp','네이버 뉴스·언론사 기사 주소를 지원해요(유튜브·구글 뉴스 주소는 아직 안 돼요). 서버가 기사를 읽어 AI 요청문을 만들어 주고, 본문은 저장하거나 화면에 보여주지 않아요.'));
 if(!ftOk('url')){var lk=el('div');nwLocked(lk,'url','예) 기사 주소만 붙여 넣으면 AI 요청문이 만들어져요.');s.appendChild(lk)}R.appendChild(s)}
function nrNewsCard(R,x){var c=el('div','nrNc');var h=el('div');if(x.cls){h.appendChild(nwChip(x.cls.k,x.cls.label));(x.cls.themes||[]).forEach(function(t){h.appendChild(nwChip('t',t))})}c.appendChild(h);c.appendChild(el('h3',null,x.title));
 c.appendChild(el('div','mt',[x.press,x.date].filter(Boolean).join(' · ')));if(x.cls&&(x.cls.pos.length||x.cls.neg.length))c.appendChild(el('div','mt','근거 단어: '+x.cls.pos.concat(x.cls.neg).join(', ')));
 var has=!!NR.res['n:'+x.url];var bar=el('div','bar');bar.appendChild(bt(has?'🔄 AI 다시 분석':'🤖 이 뉴스 AI 분석','bt',function(){nrStartNews(x)}));
 if(x.url){var o=nrOrig(x.url);o.className='nrOrg';o.textContent='📖 원문 읽기 ↗';bar.appendChild(o);bar.appendChild(bt('주소 복사','bt3',function(){copyTxt(x.url)}))}c.appendChild(bar);
 var cand=[];if(NR.ov&&NR.ov.cat===NR.cat){NR.ov.stocks.forEach(function(s){if((s.idx||[]).indexOf(NR.sel)>=0)cand.push({ticker:s.ticker,name:s.name,market:s.market,sector:s.sector,senti:(x.cls&&x.cls.k==='p')?1:((x.cls&&x.cls.k==='n')?-1:0),mentioned:true,reason:'제목에서 종목 이름이 확인돼요(AI 분석 전의 참고 후보).'})})}
 if(cand.length&&!has){c.appendChild(el('div','mt','🔎 제목에서 찾은 관련 종목 후보'));nrStockCards(c,cand)}R.appendChild(c)}
function nrWs(){var R=$('nrR');if(!R)return;R.innerHTML='';nrUrlBar(R);var sp0=el('div','nrStp');sp0.id='nrSteps';R.appendChild(sp0);var rs=NR.res[NR.ws];var x=NR.sel>=0?NR.items[NR.sel]:null;
 if(x)nrNewsCard(R,x);
 if(rs)nrResult(R,rs);
 else if(!x){var e=el('div','nrEm');e.appendChild(el('div',null,'👈 뉴스 목록에서 뉴스를 누르면 여기에서 분석해요.'));e.appendChild(el('div',null,'① 뉴스 선택 → ② [🤖 AI 분석] → ③ 관련 종목·시세 그래프·이미지'));e.appendChild(el('div',null,'위쪽 [🤖 전체 AI 총평]으로 오늘 뉴스 전체의 흐름을 볼 수도 있어요.'));R.appendChild(e)}
 nrSteps()}
function nrResult(R,rs){var j=rs.j,ctx=rs.ctx;var c=el('div','nwS nrRes');var h=el('div','nrRh');h.appendChild(el('h3',null,'🤖 '+ctx.label));
 h.appendChild(bt('🔄 다시 분석','bt3',function(){nrRedo(ctx)}));c.appendChild(h);
 c.appendChild(el('p','ds','AI 답변을 정리한 화면이에요. 호재/악재 표시는 AI 또는 단어 규칙의 분류 참고 값이며 투자 권유가 아니에요.'));
 if(ctx.note)c.appendChild(el('p','note',ctx.note));
 var sm=nrSum(j.ai_text);if(sm){var b0=el('div','nwSum');b0.appendChild(el('b',null,'📝 한 줄 요약 — '));b0.appendChild(document.createTextNode(sm));c.appendChild(b0)}
 if(ctx.url){var ol=el('div','mt','원문: ');ol.appendChild(nrOrig(ctx.url));c.appendChild(ol)}
 if(j.stocks&&j.stocks.length){c.appendChild(el('h4','nwH4','📊 관련 종목 '+j.stocks.length+'개 · 최근 30일 시세'));nrStockCards(c,j.stocks)}else c.appendChild(el('p','note','확인된 종목이 없어요.'));
 (j.warnings||[]).forEach(function(w){c.appendChild(el('p','note bad','⚠ '+w))});
 var body=el('div');nwMd(body,String(j.ai_text||'').split(/\r?\n/).filter(function(l){return !/^\*\*한 줄 요약\*\*/.test(l)}).join('\n'));c.appendChild(body);
 var ab=el('div','bar');ab.appendChild(bt('분석문 복사','bt2',function(){copyTxt(j.ai_text)}));
 ab.appendChild(adm(bt('💾 보관함에 저장 (관리자)','bt',function(){apiJ('/admin/api/news/save',{title:j.title_ko||ctx.title||'',source:ctx.source||'',excerpt:ctx.excerpt||'',ai_text:j.ai_text,stocks:j.stocks,kind:'stock'}).then(function(z){if(z.error){toast(z.error);return}toast('보관함에 저장했어요')})})));
 var bi=el('button','bt3','🖼 이미지 만들기');if(MEMBER_MODE)ab.appendChild(bi);c.appendChild(ab);var ib=el('div','nrImg');ib.id='nrImgR';c.appendChild(ib);nrBlogMount(c,rs,j,ctx);R.appendChild(c);
 NR.imgP=null;NR.mountImg=function(){if(!NR.imgP&&$('nrImgR')===ib)mount();return NR.imgP};function mount(){if(!ftOk('overview')){lockDlg('overview');return}if(!window.ImgKit||!window.NwImg){ib.textContent='이미지 도우미를 불러오지 못했어요. 새로고침해 주세요.';return}
  var nm=(ctx.title||'뉴스').replace(/\s+/g,' ').slice(0,18),id=ctx.kind==='ov'?window.ImgKit.dateDir():(String(ctx.url||'').replace(/\D/g,'').slice(-8)||window.ImgKit.dateDir());
  NR.imgP=nrImgMount(ib,{name:ctx.kind==='ov'?'뉴스총평':nm,ticker:id,perStock:ctx.kind!=='ov',onDone:function(){rs.img=true;nrSteps()},gen:function(scale){var tks=(j.stocks||[]).map(function(s){return s.ticker});
   return nrFetchMinis(tks).then(function(){return window.NwImg.res({title:j.title_ko||ctx.title,source:ctx.source,kind:ctx.kind,label:ctx.label,summary:sm,lines:nrLines(j.ai_text,7),stocks:j.stocks||[],minis:NR.minis,cls:ctx.cls||null},scale)})}})}
 bi.onclick=function(){if(NR.imgP){NR.imgP.gen(false);return}mount();if(NR.imgP&&NR.imgP.gen)NR.imgP.gen(false)};NR.imgGo=function(){bi.onclick()};
 if(!MEMBER_MODE&&ftOk('overview'))setTimeout(function(){if($('nrImgR')===ib&&!NR.imgP)mount()},30)}
/* 차례(단계) 메뉴 — 뉴스 고르기 → AI 분석 → 이미지 → (관리자) 블로그 글 만들기 → 복사하고 블로그 쓰기 */
function nrRedo(ctx){if(ctx.kind==='ov')nrOverall();else if(ctx.kind==='url')nrUrl(ctx.url);else{var x=NR.items[NR.sel];if(x)nrStartNews(x);else if(ctx.url)nrUrl(ctx.url)}}
function nrSteps(){var sp=$('nrSteps');if(!sp)return;var rs=NR.res[NR.ws],x=NR.sel>=0?NR.items[NR.sel]:null;
 var ai=!!rs,img=!!(rs&&(rs.img||(NR.imgP&&NR.imgP.items&&NR.imgP.items()))),bl=!!(rs&&rs.blog),cp=!!(rs&&rs.copied);
 var steps=[{t:'뉴스 고르기',sub:rs||x?'선택됨':'목록에서 뉴스를 눌러요',done:!!(rs||x),go:function(){nrStepRun('pick')}},
  {t:'AI 분석',sub:ai?'완료 · 다시 분석':'눌러서 시작',done:ai,go:function(){nrStepRun('ai')}},
  {t:'이미지 만들기',sub:img?'완료 · 다시 만들기':(ai?'눌러서 만들기':'분석 뒤에 해요'),done:img,off:!ai,go:function(){nrStepRun('img')}},
  {t:'글 만들기',sub:bl?'완료 · 다시 만들기':(ai?'눌러서 만들기':'분석 뒤에 해요'),done:bl,off:!ai,hide:MEMBER_MODE,go:function(){nrStepRun('blog')}},
  {t:'블로그에 쓰기',sub:cp?'복사·열기 완료':(bl?'복사하고 블로그 열기':'글을 먼저 만드세요'),done:cp,off:!bl,hide:MEMBER_MODE,go:function(){nrStepRun('post')}}];
 window.FlowBar.draw(sp,{steps:steps,runAll:MEMBER_MODE?null:function(){nrStepRun('all')},note:MEMBER_MODE?'':'[⚡ 블로그까지 한 번에]는 (고른 뉴스의) AI 분석 → 이미지 → 글 → 블로그 복사·열기를 설정과 상관없이 끝까지 이어요. 단계별 자동/수동은 [⚙ 설정]에서 바꿔요. 블로그 글쓰기 화면에 붙여 넣기(Ctrl+V)만 직접 하면 돼요.'})}
function nrStepRun(id){var rs=NR.res[NR.ws],x=NR.sel>=0?NR.items[NR.sel]:null;
 if(id==='pick'){var L=$('nrL');if(L&&L.scrollIntoView)L.scrollIntoView({behavior:'smooth',block:'start'});if(!x&&!rs)toast('왼쪽 목록에서 분석할 뉴스를 눌러 주세요');return}
 if(id==='ai'){if(rs){nrRedo(rs.ctx);return}if(x){nrStartNews(x);return}toast('먼저 뉴스를 고르거나 위쪽 [전체 AI 총평]·URL 분석으로 시작하세요');return}
 if(id==='all'){if(MEMBER_MODE||!window.MiniFlow)return;if(!rs&&!x){toast('먼저 뉴스를 고르거나 위쪽 [전체 AI 총평]·URL 분석으로 시작하세요');return}toast('⚡ 블로그까지 이어서 진행해요');MiniFlow.force('news',NRFLOW,NRACTS);return}
 if(!rs){toast('먼저 AI 분석을 끝내 주세요');return}
 if(id==='img'){var e=$('nrImgR');if(e&&e.scrollIntoView)e.scrollIntoView({behavior:'smooth',block:'nearest'});if(!MEMBER_MODE&&window.MiniFlow){rs.img=false;window.MiniFlow.go('news',NRFLOW,NRACTS,'img')}else if(NR.imgGo)NR.imgGo();return}
 if(MEMBER_MODE)return;
 if(id==='blog'){rs.blog=false;if(window.MiniFlow)window.MiniFlow.go('news',NRFLOW,NRACTS,'blog');return}
 if(id==='post'){nrPostGo(false)}}
/* 블로그 글 쓰기 구역(관리자) — 서버가 AI 분석문·관련 종목을 블로그용 HTML 로 만든다 */
function nrBlogMount(c,rs,j,ctx){NR.blogP=null;if(MEMBER_MODE||!window.BlogKit)return;
 var bs=el('div','nwS nrBlog');bs.id='nrBlogR';bs.appendChild(el('h4','nwH4','📝 블로그 글 쓰기 (관리자만 보여요)'));
 bs.appendChild(el('p','note','AI 분석문과 관련 종목(호재·악재 분류는 참고 표시)·최근 시세를 네이버 블로그용 글로 만들어요. 만든 뒤 [복사하고 블로그 열기]를 누르고 붙여넣기만 하면 돼요. 기사 원문은 싣지 않고 출처 링크만 넣어요.'));
 var bx=el('div');bs.appendChild(bx);c.appendChild(bs);var d=new Date(),z=function(n){return ('0'+n).slice(-2)},st=(j.stocks||[]),one=(ctx.kind!=='ov'&&st.length)?st[0]:null;
 var tk=one?one.ticker:('D'+String(d.getFullYear()).slice(2)+z(d.getMonth()+1)+z(d.getDate()));
 NR.blogP=window.BlogKit.panel(bx,{idp:'nrb',key:'news',kind:'news',ticker:tk,name:one?one.name:'뉴스분석',sections:[['summary','한 줄 요약'],['stocks','관련 종목·시세'],['ai','AI 분석 본문'],['src','출처·원문 링크']],
  build:function(inc,title){return apiJ('/admin/api/news/blog',{ticker:tk,title:title,news_title:j.title_ko||ctx.title||'',source:ctx.source||'',url:ctx.url||'',kind:ctx.kind,ai_text:j.ai_text,stocks:st,inc:inc})},
  onBuilt:function(){rs.blog=true;rs.copied=false;nrSteps()},onCopied:function(){rs.copied=true;nrSteps()}})}
/* 분석 시작 */
function nrPv(j){var x=el('div','nwPv');x.textContent='종목 '+j.stocks.length+'개 정리됨'+(j.stocks.length?': '+j.stocks.slice(0,6).map(function(s){return s.name}).join(', ')+(j.stocks.length>6?' 외':''):'')+' · 분석문 '+j.ai_text.length.toLocaleString()+'자';(j.warnings||[]).forEach(function(w){x.appendChild(el('div','m','⚠ '+w))});return x}
function nrAI(ctx){if(!ftOk('ai')){lockDlg('ai');return}if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}
 var parsed=null,pfor='';function parse(t){if(parsed&&pfor===t)return Promise.resolve(parsed);return apiJ('/admin/api/news/parse',{mode:'stock',text:t,title:ctx.title||'',tk:ctx.tk||'',article:''}).then(function(j){if(!j.error){parsed=j;pfor=t}return j})}
 window.MiniAI.run({title:'뉴스 AI — '+ctx.label,key:'news',steps:[{label:ctx.label,prompt:ctx.prompt}],minLen:200,hint:'AI 답변 끝의 ```json 블록까지 통째로 복사해 이 탭으로 돌아오세요.',
  preview:function(t){return parse(t).then(function(j){if(j.error)return {text:j.error,canApply:false};return {node:nrPv(j),canApply:true,strict:!(j.warnings&&j.warnings.length)}}).catch(function(){return {text:'답변을 읽는 중 오류가 났어요. 다시 시도해 주세요.',canApply:false}})},
  apply:function(t){return parse(t).then(function(j){if(j.error)return {message:'읽지 못했어요: '+j.error};
   var key=ctx.key;NR.res[key]={j:j,ctx:ctx,at:Date.now()};NR.ws=key;if(ctx.kind!=='news')NR.sel=-1;
   setTimeout(function(){nrList();nrWs();if(ctx.kind==='ov')nrDash();if(!MEMBER_MODE&&window.MiniFlow)window.MiniFlow.run('news',NRFLOW,NRACTS,'ai')},80);
   return {message:'정리해서 화면에 보여줬어요(서버에는 저장하지 않아요).'}})}})}
function nrOverall(){if(!ftOk('ai')){lockDlg('ai');return}apiJ('/admin/api/news/overview/prompt',{cat:NR.cat}).then(function(j){if(j.error){toast(j.error);return}
 nrAI({key:'ov:'+NR.cat,kind:'ov',title:j.title,source:'네이버 금융',url:'',tk:j.tk,prompt:j.prompt,label:j.title})})}
function nrUrl(u){u=String(u||'').trim();if(!ftOk('url')){lockDlg('url');return}if(!/^https?:\/\//i.test(u)){toast('http:// 또는 https:// 로 시작하는 기사 주소를 붙여 넣어 주세요');return}
 toast('기사를 읽는 중…');apiJ('/admin/api/news/url',{url:u,mode:'stock'}).then(function(j){if(j.error||!j.prompt){if(!j.feature)toast(j.error||'기사를 읽지 못했어요');return}
  var ctx={key:'u:'+j.url,kind:'url',title:j.title,source:j.source,url:j.url,tk:j.tk,prompt:j.prompt,label:'URL 분석 · '+(j.title||j.url).slice(0,40),note:j.note||'',excerpt:j.excerpt||''};nrAI(ctx)})}
function nrStartNews(x){if(!ftOk('ai')){lockDlg('ai');return}if(!x||!x.url){toast('원문 주소가 없는 뉴스예요');return}toast('기사 본문을 읽는 중…');
 var mk=function(j,note){nrAI({key:'n:'+x.url,kind:'news',title:x.title,source:x.press||j.source||'',url:x.url,tk:j.tk||'',prompt:j.prompt,label:'뉴스 분석 · '+x.title.slice(0,40),note:note||j.note||'',excerpt:j.excerpt||'',cls:x.cls||null})};
 apiJ('/admin/api/news/url',{url:x.url,mode:'stock'}).then(function(j){if(j.prompt){mk(j);return}
  if(j.feature||/1분에/.test(j.error||'')){if(j.error)toast(j.error);return}
  apiJ('/admin/api/news/prompt',{mode:'stock',title:x.title,source:x.press||'',text:x.title+'\n'+(x.snippet||x.title)+'\n(기사 본문을 읽지 못해 제목·발췌만으로 분석해요)'}).then(function(k){if(k.error){toast(k.error);return}mk(k,'기사 본문을 읽지 못해 제목·발췌만으로 분석했어요. 정확하지 않을 수 있어요.')})})}

/* 종목 뉴스 */
function nwVStock(box){var s=nwSec(box,'🔎 종목 뉴스 조회','종목 이름이나 6자리 코드를 넣으면 최근 2주 안의 관련 뉴스 제목을 모아 보여드려요. 같은 사건을 다룬 기사는 대표 1건과 관련 기사 수로 묶여요.');
 if(!ftOk('stock')){nwLocked(s,'stock','예) 삼성전자 → 최근 2주 뉴스 제목과 호재성·악재성 분류');return}
 var bar=el('div','bar');var inp=el('input','nwIn');inp.type='text';inp.placeholder='예) 삼성전자 또는 005930';inp.maxLength=30;inp.setAttribute('aria-label','종목 이름 또는 코드');inp.value=NW.sk||'';
 var go=bt('조회하기','bt',function(){run(inp.value)});bar.appendChild(inp);bar.appendChild(go);s.appendChild(bar);
 var pk=el('div','nwPick');['삼성전자','SK하이닉스','현대차','NAVER'].forEach(function(n){var b=el('button',null,n);b.onclick=function(){inp.value=n;run(n)};pk.appendChild(b)});s.appendChild(pk);
 var out=el('div');s.appendChild(out);inp.onkeydown=function(e){if(e.key==='Enter')run(inp.value)};
 function run(q){q=String(q||'').trim();if(!q){toast('종목 이름이나 코드를 먼저 입력하세요');return}NW.sk=q;nwWait(out,'뉴스를 찾는 중…');
  api('/admin/api/news/stock?q='+encodeURIComponent(q)).then(function(j){out.innerHTML='';
   if(j.candidates){out.appendChild(el('p','note','어느 종목인가요? 하나를 골라 주세요.'));var pk2=el('div','nwPick');j.candidates.forEach(function(c){var b=el('button',null,c.name+' ('+c.ticker+')');b.onclick=function(){inp.value=c.ticker;run(c.ticker)};pk2.appendChild(b)});out.appendChild(pk2);return}
   if(j.error){NeedNote(out,j.error,'','note bad');return}
   var hd=el('div','bar');var nm=nwTk(el('b',null,(j.name||j.ticker)+' ('+j.ticker+')'),j.ticker);hd.appendChild(nm);if(j.market)hd.appendChild(el('span','m',j.market));out.appendChild(hd);
   if(j.record){var rc=el('div','nwWarn sm');rc.textContent='📚 최근 '+j.record.days+'일 저장된 분석 기록: 이 종목이 나온 기사 '+j.record.articles+'건 (직접 언급 '+j.record.direct+'건 · 호재 분류 '+j.record.pos+' · 악재 분류 '+j.record.neg+'). 분류 참고용이에요.';out.appendChild(rc)}
   var list=el('div');out.appendChild(list);nwItems(list,j);
   if(j.items&&j.items.length){var ab=el('div','bar');ab.appendChild(ft(bt('🤖 이 제목들로 AI 해석 준비','bt2',function(){NW.pre={title:(j.name||j.ticker)+' 최근 뉴스 제목',source:'네이버 금융 뉴스 제목',text:j.items.map(function(x){return '- '+(x.date?'('+x.date+') ':'')+x.title+(x.press?' ['+x.press+']':'')}).join('\n')};nwShow('ai')}),'ai'));out.appendChild(ab)}
  }).catch(function(){nwFail(out)})}
 if(NW.sk)run(NW.sk)}
/* 분류 체험 */
function nwVCls(box){var s=nwSec(box,'🏷 키워드 분류 체험','뉴스 제목을 한 줄에 하나씩 붙여 넣으면 호재성·악재성 단어와 테마 키워드를 찾아 분류해 드려요(최대 40줄). 단어만 보는 단순한 분류라 틀릴 수 있어요.');
 if(!ftOk('classify')){nwLocked(s,'classify','예) “A사 대규모 공급계약 체결, 흑자전환” → 호재성 · 근거 단어 표시');return}
 var ta=el('textarea','nwTa');ta.placeholder='예)\nA사, 1조원 규모 공급계약 체결…흑자전환 기대감\nB사 영업손실 확대, 목표가 하향\n(실제 뉴스 제목을 한 줄에 하나씩)';ta.maxLength=12000;ta.setAttribute('aria-label','뉴스 제목 목록');s.appendChild(ta);
 var bar=el('div','bar');var out=el('div');
 bar.appendChild(bt('분류하기','bt',function(){var ls=ta.value.split(/\r?\n/).map(function(x){return x.trim()}).filter(Boolean);if(!ls.length){toast('분류할 제목을 먼저 입력하세요');return}
  nwWait(out,'분류하는 중…');apiJ('/admin/api/news/classify',{titles:ls.slice(0,40)}).then(function(j){out.innerHTML='';if(j.error){NeedNote(out,j.error,'','note bad');return}
   var tl=el('div','nwTiles');['호재성','악재성','혼재','중립'].forEach(function(k){var t=el('div','nwTile');t.appendChild(el('div','l',k));t.appendChild(el('div','v',(j.summary[k]||0)+'줄'));tl.appendChild(t)});out.appendChild(tl);nwNote(out);
   j.rows.forEach(function(r){var d=el('div','nwIt');var h=el('div');h.appendChild(nwChip(r.k,r.label));(r.themes||[]).forEach(function(t){h.appendChild(nwChip('t',t))});h.appendChild(el('span',null,r.title));d.appendChild(h);
    if(r.pos.length||r.neg.length)d.appendChild(el('div','sn','근거 단어: '+r.pos.concat(r.neg).join(', ')));out.appendChild(d)})}).catch(function(){nwFail(out)})}));
 bar.appendChild(bt('✖ 지우기','bt3',function(){ta.value='';out.innerHTML=''}));s.appendChild(bar);s.appendChild(out);
 var dt=el('details');dt.appendChild(el('summary',null,'📖 분류에 쓰는 단어 보기'));var dv=el('div');dt.appendChild(dv);var loaded=false;
 dt.addEventListener('toggle',function(){if(!dt.open||loaded)return;loaded=true;api('/admin/api/news/classify').then(function(j){if(j.error){NeedNote(dv,j.error,'','note bad');return}
  function row(t,k,arr){var d=el('div','nwIt');d.appendChild(el('b',null,t));var w=el('div');arr.forEach(function(x){w.appendChild(nwChip(k,x))});d.appendChild(w);dv.appendChild(d)}
  row('호재성 단어','p',j.pos);row('악재성 단어','n',j.neg);row('호재로 뒤집는 표현(예: 적자 탈출)','p',j.pos_ovr);row('악재로 뒤집는 표현(예: 수주 취소)','n',j.neg_ovr);
  Object.keys(j.themes).forEach(function(k){row('테마 · '+k,'t',j.themes[k].split(','))});dv.appendChild(el('p','note','제목에서 위 단어가 더 많이 나온 쪽으로 분류하고, 같으면 혼재, 없으면 중립이에요.'))}).catch(function(){dv.appendChild(el('p','note bad','불러오지 못했어요.'))})});
 s.appendChild(dt)}
/* 테마·이슈 */
function nwVTheme(box){var s=nwSec(box,'🧩 뉴스 기반 테마·이슈 요약','이 사이트에 저장된 뉴스 분석 기록을 기간별로 모아, 자주 나온 테마와 함께 언급된 종목, 기사가 많았던 업종을 보여드려요. 저장된 분석 결과를 열람하는 화면이에요.');
 if(!ftOk('themes')){nwLocked(s,'themes','예) 최근 14일 — 반도체 테마 기사 12건, 함께 언급된 종목 3개');return}
 var bar=el('div','bar');var sel=el('select');sel.setAttribute('aria-label','기간');[7,14,30,60].forEach(function(d){var o=el('option',null,'최근 '+d+'일');o.value=d;if(d===NW.theme.days)o.selected=true;sel.appendChild(o)});bar.appendChild(sel);
 var out=el('div');bar.appendChild(bt('불러오기','bt',function(){NW.theme.days=+sel.value;run()}));s.appendChild(bar);s.appendChild(out);
 function run(){nwWait(out,'기록을 모으는 중…');api('/admin/api/news/themes?days='+NW.theme.days).then(function(j){out.innerHTML='';if(j.error){NeedNote(out,j.error,'','note bad');return}
  if(j.note){NeedNote(out,j.note);return}
  var tl=el('div','nwTiles');[['분석 기사',j.articles+'건'],['테마',j.themes.length+'개'],['언급 종목',j.stocks.length+'개+']].forEach(function(x){var t=el('div','nwTile');t.appendChild(el('div','l',x[0]));t.appendChild(el('div','v',x[1]));tl.appendChild(t)});out.appendChild(tl);nwNote(out);
  if(j.themes.length){out.appendChild(el('b',null,'🔥 자주 나온 테마'));j.themes.forEach(function(t){var c=el('div','nwCard');var h=el('div','hd');h.appendChild(nwChip('t',t.theme));h.appendChild(el('span','m','기사 '+t.articles+'건'));c.appendChild(h);
   if(t.names.length){var w=el('div','mt','함께 언급된 종목: ');t.names.forEach(function(n){w.appendChild(el('span',null,n+'  '))});c.appendChild(w)}
   t.titles.forEach(function(x){c.appendChild(el('div','sn',x.date+' · '+x.title+(x.source&&!/^https?:/.test(x.source)?' ('+x.source+')':'')))});out.appendChild(c)})}
  else out.appendChild(el('p','note','테마 키워드가 2번 이상 나온 기사가 아직 없어요.'));
  if(j.sectors.length){var d=el('div','bar');d.appendChild(el('b',null,'🏭 기사가 많았던 업종'));out.appendChild(d);var w2=el('div');j.sectors.forEach(function(x){w2.appendChild(nwChip('a',x.sector+' '+x.articles+'건'))});out.appendChild(w2)}
  if(j.stocks.length){var d2=el('div','bar');d2.appendChild(el('b',null,'📌 직접 언급이 많았던 종목'));out.appendChild(d2);var tw=el('div','nwTw');var t=el('table','nwT'),hr=el('tr');['종목','업종','기사','호재 분류','악재 분류'].forEach(function(x,i){hr.appendChild(el('th',i>1?'r':'',x))});t.appendChild(hr);
   j.stocks.forEach(function(x){var tr=el('tr');var c0=el('td');c0.appendChild(nwTk(el('b',null,x.name||x.ticker),x.ticker));c0.appendChild(el('div','m',x.ticker));tr.appendChild(c0);tr.appendChild(el('td',null,x.sector||'-'));tr.appendChild(el('td','r',x.articles));tr.appendChild(el('td','r',x.pos));tr.appendChild(el('td','r',x.neg));t.appendChild(tr)});tw.appendChild(t);out.appendChild(tw)}
  }).catch(function(){nwFail(out)})}
 run()}
/* 긍정뉴스 지속 종목 */
function nwVLead(box){var s=nwSec(box,'📈 긍정뉴스 지속 종목','저장된 뉴스 분석 기록을 종목별로 모아, 직접 언급되며 꾸준히 호재로 분류된 종목을 점수순으로 보여드려요. 점수는 긍정일 수·비율·부정일 수로 계산한 참고 값이에요.');
 if(!ftOk('leader')){nwLocked(s,'leader','예) 최근 21일 — 긍정 4일·부정 0일·긍정비율 100%인 종목 순위');return}
 var bar=el('div','bar');var sd=el('select'),sm=el('select');sd.setAttribute('aria-label','집계 기간');sm.setAttribute('aria-label','최소 긍정 보도일');
 [14,21,30,60].forEach(function(d){var o=el('option',null,'최근 '+d+'일');o.value=d;if(d===NW.lead.days)o.selected=true;sd.appendChild(o)});[1,2,3,5].forEach(function(d){var o=el('option',null,'긍정 '+d+'일 이상');o.value=d;if(d===NW.lead.min)o.selected=true;sm.appendChild(o)});
 bar.appendChild(sd);bar.appendChild(sm);bar.appendChild(bt('집계하기','bt',function(){NW.lead.days=+sd.value;NW.lead.min=+sm.value;run()}));
 bar.appendChild(ft(bt('🤖 AI 총평 프롬프트 복사','bt2',function(){nwLeadAI('overview',null)}),'ai'));s.appendChild(bar);
 var out=el('div');s.appendChild(out);var ans=el('div');ans.id='nwLeadAns';s.appendChild(ans);nwLeadAns();
 function run(){nwWait(out,'집계하는 중…');api('/admin/api/news/leader?days='+NW.lead.days+'&min_days='+NW.lead.min).then(function(j){out.innerHTML='';if(j.error){NeedNote(out,j.error,'','note bad');return}
  if(!j.rows.length){NeedNote(out,j.note,'조건에 맞는 종목이 없어요. 최소 보도일을 낮추거나 기간을 늘려 보세요.');return}
  out.appendChild(el('p','note','최근 '+j.days+'일 · 분석 기사 '+j.articles+'건 · 조건 충족 '+j.rows.length+'종목 · '+j.scanned_at+' 기준'));nwNote(out);
  out.appendChild(el('div','nwWarn sm','⚠ 이미 알려진 뉴스에 뒤늦게 진입하면 고점 추격이 될 수 있고, 삼성전자·SK하이닉스처럼 늘 뉴스에 나오는 대형주는 긍정·부정이 함께 많을 수 있어요. 이 순위만으로 투자하지 마세요.'));
  j.rows.forEach(function(r,i){var c=el('div','nwCard');var h=el('div','hd');h.appendChild(el('span','m',(i+1)+'위'));h.appendChild(nwTk(el('span','nm',r.name||r.ticker),r.ticker));h.appendChild(el('span','m',r.ticker+(r.market?' · '+r.market:'')));h.appendChild(el('span','sc',r.score+'점'));c.appendChild(h);
   c.appendChild(el('div','mt','호재 분류 '+r.direct_pos_days+'일 · 악재 분류 '+r.direct_neg_days+'일 · 긍정비율 '+r.pos_ratio+'%'+(r.first_pos_date?' · 첫 긍정 보도 '+r.first_pos_date:'')));
   var br=el('div','nwBar');var fi=el('i');fi.style.width=r.pos_ratio+'%';fi.style.background=r.pos_ratio>=90?'#047857':(r.pos_ratio>=70?'#16a34a':'#94a3b8');br.appendChild(fi);c.appendChild(br);
   var dt=el('details');dt.appendChild(el('summary',null,'관련 헤드라인 '+r.headlines.length+'건'));r.headlines.forEach(function(x){var d=el('div','sn');d.appendChild(nwChip(x.senti>0?'p':'n',x.senti>0?'호재':'악재'));d.appendChild(document.createTextNode(x.date+' · '+x.title));dt.appendChild(d)});c.appendChild(dt);
   var ab=el('div','bar');ab.appendChild(ft(bt('🤖 이 종목 AI 코멘트 프롬프트','bt3',function(){nwLeadAI('stock',r)}),'ai'));c.appendChild(ab);out.appendChild(c)})}).catch(function(){nwFail(out)})}
 run()}
function nwLeadAns(){var b=$('nwLeadAns');if(!b)return;b.innerHTML='';Object.keys(NW.lead.ans).forEach(function(k){var a=NW.lead.ans[k];var c=el('div','nwS');c.appendChild(el('h3',null,'🤖 '+a.title));c.appendChild(el('p','ds','AI 답변을 정리한 화면이에요(서버에는 저장하지 않아요). 분류 참고용이며 투자 권유가 아닙니다.'));nwSections(c,a.text);b.appendChild(c)})}
function nwLeadAI(kind,row){if(!ftOk('ai')){lockDlg('ai');return}if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}
 apiJ('/admin/api/news/leader/prompt',{kind:kind,days:NW.lead.days,min_days:NW.lead.min,ticker:row?row.ticker:''}).then(function(j){if(j.error){toast(j.error);return}
  var ttl=kind==='stock'?(row.name+' 뉴스 흐름 코멘트'):('최근 '+NW.lead.days+'일 뉴스 심리 총평');
  window.MiniAI.run({title:'긍정뉴스 AI — '+ttl,key:'newslead',steps:[{label:ttl,prompt:j.prompt}],minLen:150,hint:'AI가 [섹션명] 형식으로 답하면 그 답변 전체를 복사하고 이 탭으로 돌아오세요.',
   preview:function(t){var x=el('div','nwPv');x.textContent='읽은 글 '+t.length.toLocaleString()+'자 — '+t.slice(0,240)+(t.length>240?' …':'');return {node:x,canApply:t.trim().length>=120,strict:true}},
   apply:function(t){NW.lead.ans[kind==='stock'?row.ticker:'overview']={title:ttl,text:t};setTimeout(nwLeadAns,50);return {message:'답변을 화면에 정리했어요(서버에는 저장하지 않아요).'}}})})}
/* 보관함 */
function nwVBoard(box){var s=nwSec(box,'🗂 분석 기록 보관함','이 사이트에서 분석해 저장한 뉴스들의 제목·출처·AI 분석문을 모아 둔 곳이에요. 기사 원문은 보여주지 않고, 원문은 출처 링크에서 확인해요.');
 if(!ftOk('board')){nwLocked(s,'board','예) 제목·출처·함께 언급된 종목 목록과 AI 분석문을 다시 볼 수 있어요.');return}
 var bar=el('div','bar');var inp=el('input','nwIn');inp.type='text';inp.placeholder='제목·분석 내용 검색';inp.maxLength=60;inp.value=NW.board.q;inp.setAttribute('aria-label','보관함 검색');bar.appendChild(inp);
 bar.appendChild(bt('검색하기','bt',function(){NW.board.q=inp.value.trim();NW.board.page=1;list()}));s.appendChild(bar);inp.onkeydown=function(e){if(e.key==='Enter'){NW.board.q=inp.value.trim();NW.board.page=1;list()}};
 var out=el('div');s.appendChild(out);
 function list(){nwWait(out,'불러오는 중…');api('/admin/api/news/log/list?q='+encodeURIComponent(NW.board.q)+'&page='+NW.board.page).then(function(j){out.innerHTML='';if(j.error){NeedNote(out,j.error,'','note bad');return}
  if(!j.rows.length){NeedNote(out,j.note,'기록이 없어요.');return}
  out.appendChild(el('p','note','총 '+j.total.toLocaleString()+'건 — 항목을 누르면 AI 분석문을 볼 수 있어요.'));
  j.rows.forEach(function(r){var c=el('div','nwIt');c.style.cursor='pointer';var h=el('div');h.appendChild(el('span','tt',r.title));c.appendChild(h);
   c.appendChild(el('div','mt',r.created_at+(r.source&&!/^https?:/.test(r.source)?' · '+r.source:(r.link?' · 링크 있음':''))+(r.src==='web'?' · 웹 저장':'')));if(r.snippet)c.appendChild(el('div','sn',r.snippet+'…'));
   if(r.stocks.length){var w=el('div');r.stocks.forEach(function(x){var ch=nwChip(x.senti>0?'p':(x.senti<0?'n':'z'),x.name||x.ticker);nwTk(ch,x.ticker);w.appendChild(ch)});c.appendChild(w)}
   c.onclick=function(){detail(r.id)};out.appendChild(c)});
  var pg=el('div','bar');if(NW.board.page>1)pg.appendChild(bt('◀ 이전','bt3',function(){NW.board.page--;list()}));if(j.page*j.page_size<j.total)pg.appendChild(bt('다음 ▶','bt3',function(){NW.board.page++;list()}));out.appendChild(pg)}).catch(function(){nwFail(out)})}
 function detail(id){nwWait(out,'불러오는 중…');api('/admin/api/news/log/detail?id='+encodeURIComponent(id)).then(function(j){out.innerHTML='';var top=el('div','bar');top.appendChild(bt('← 목록으로','bt3',list));
  top.appendChild(adm(bt('🗑 삭제','bt3',function(){if(!confirm('이 분석 게시물을 삭제할까요?'))return;apiJ('/admin/api/news/log/delete',{id:id}).then(function(z){if(z.error){toast(z.error);return}toast('삭제했어요');list()})})));out.appendChild(top);
  if(j.error){NeedNote(out,j.error,'','note bad');return}
  out.appendChild(el('h3',null,j.title));var mt=el('div','mt',j.created_at+(j.source&&!j.link?' · '+j.source:'')+' ');if(j.link){mt.appendChild(nwLink(j.link,'원문 링크 열기 ↗'))}out.appendChild(mt);
  if(j.stocks.length){var w=el('div');w.style.margin='8px 0';j.stocks.forEach(function(x){var ch=nwChip(x.senti>0?'p':(x.senti<0?'n':'z'),(x.name||x.ticker)+' ('+x.ticker+')'+(x.mentioned?'':' · 연관'));ch.title=x.reason||'';nwTk(ch,x.ticker);w.appendChild(ch)});out.appendChild(w);nwNote(out)}
  var body=el('div');nwMd(body,j.ai_text);out.appendChild(body);
  if(j.excerpt)out.appendChild(el('p','note','원문 발췌(앞 200자): '+j.excerpt+' … 원문 전문은 보여주지 않아요.'))}).catch(function(){nwFail(out)})}
 list()}
/* AI 해석 */
function nwVAI(box){var s=nwSec(box,'🤖 AI 뉴스 해석','① 뉴스 본문(또는 제목 목록)을 붙여 넣고 프롬프트를 만든 뒤 → ② 챗GPT·제미나이·클로드 등에서 답을 받아 → ③ 그 답을 붙여 넣으면 이 화면에 종목·호재/악재 분류까지 정리해 보여줘요. 서버는 AI를 직접 부르지 않아요.');
 if(!ftOk('ai')){nwLocked(s,'ai','예) 기사 붙여넣기 → 프롬프트 복사 → AI 답변 붙여넣기 → 관련 종목·분류 표 + 핵심 요약');return}
 s.appendChild(el('div','nwWarn sm','뉴스 원문은 저작권이 있어요. 직접 읽은 기사 내용을 개인 분석 용도로만 붙여 넣어 주세요. 결과 화면에는 원문을 다시 보여주지 않고, 이용자가 붙여 넣은 원문은 서버에 저장하지 않아요.'));
 var pre=NW.pre||{};var row1=el('div','bar');var md=el('select');md.setAttribute('aria-label','분석 방식');[['stock','📈 증권 뉴스 분석(종목 추출)'],['general','📰 일반 문서 요약']].forEach(function(o){var op=el('option',null,o[1]);op.value=o[0];md.appendChild(op)});row1.appendChild(md);s.appendChild(row1);
 var r2=el('div','bar');var so=el('input','nwIn');so.type='text';so.placeholder='출처(예: 한국경제)';so.maxLength=100;so.value=pre.source||'';so.setAttribute('aria-label','출처');var ti=el('input','nwIn');ti.type='text';ti.placeholder='뉴스 제목';ti.maxLength=150;ti.value=pre.title||'';ti.setAttribute('aria-label','뉴스 제목');r2.appendChild(so);r2.appendChild(ti);s.appendChild(r2);
 var ta=el('textarea','nwTa');ta.placeholder='분석할 뉴스 본문(또는 제목 목록)을 붙여 넣으세요. 20자 이상';ta.maxLength=60000;ta.value=pre.text||'';ta.setAttribute('aria-label','뉴스 본문');s.appendChild(ta);
 var cnt=el('div','m');function upd(){cnt.textContent=ta.value.length.toLocaleString()+' / 60,000자'}ta.oninput=upd;upd();s.appendChild(cnt);NW.pre=null;
 var bar=el('div','bar');bar.appendChild(bt('AI 프롬프트 복사하고 열기','bt',function(){
  var text=ta.value.trim();if(text.length<20){toast('먼저 뉴스 본문(또는 제목 목록)을 20자 이상 붙여 넣어 주세요');return}
  if(!window.MiniAI){toast('AI 도우미를 불러오지 못했어요. 새로고침해 주세요.');return}
  apiJ('/admin/api/news/prompt',{mode:md.value,title:ti.value,source:so.value,text:text}).then(function(j){if(j.error){toast(j.error);return}
   NW.cur={mode:md.value,title:ti.value.trim(),source:so.value.trim(),text:text};NW.parsed=null;NW.parsedFor='';
   window.MiniAI.run({title:md.value==='stock'?'뉴스 AI 해석':'일반 문서 요약',key:'news',steps:[{label:'뉴스 해석',prompt:j.prompt}],minLen:200,
    hint:md.value==='stock'?'AI 답변 끝의 ```json 블록까지 통째로 복사해 이 탭으로 돌아오세요.':'AI 답변 끝의 META_JSON 줄까지 통째로 복사해 이 탭으로 돌아오세요.',
    preview:function(t){return nwPreview(t)},apply:function(t){return nwApply(t)}})})}));
 bar.appendChild(bt('비우기','bt3',function(){ta.value='';so.value='';ti.value='';upd()}));s.appendChild(bar);
 var res=el('div');res.id='nwRes';s.appendChild(res);nwDrawRes()}
function nwParse(t){var c=NW.cur||{mode:'stock',title:'',text:''};if(NW.parsed&&NW.parsedFor===t)return Promise.resolve(NW.parsed);
 return apiJ('/admin/api/news/parse',{mode:c.mode,text:t,title:c.title,article:c.mode==='stock'?c.text:''}).then(function(j){if(!j.error){NW.parsed=j;NW.parsedFor=t}return j})}
function nwPreview(t){return nwParse(t).then(function(j){if(j.error)return {text:j.error,canApply:false};var x=el('div','nwPv');
  if(j.mode==='general'){x.textContent='요약 '+j.ai_text.length.toLocaleString()+'자 · 제목 후보: '+j.seo_title+(j.tags.length?' · 태그 '+j.tags.length+'개':'')}
  else{x.textContent='종목 '+j.stocks.length+'개 정리됨'+(j.stocks.length?': '+j.stocks.slice(0,6).map(function(s){return s.name}).join(', ')+(j.stocks.length>6?' 외':''):'')+' · 분석문 '+j.ai_text.length.toLocaleString()+'자'}
  (j.warnings||[]).forEach(function(w){x.appendChild(el('div','m','⚠ '+w))});
  return {node:x,canApply:true,strict:!(j.warnings&&j.warnings.length)}}).catch(function(){return {text:'답변을 읽는 중 오류가 났어요. 다시 시도해 주세요.',canApply:false}})}
function nwApply(t){return nwParse(t).then(function(j){if(j.error)return {message:'읽지 못했어요: '+j.error};NW.res=j;NW.resEx=(NW.cur&&NW.cur.text||'').replace(/\s+/g,' ').trim().slice(0,300);NW.resSrc={title:(NW.cur||{}).title||'',source:(NW.cur||{}).source||''};setTimeout(nwDrawRes,50);return {message:'정리해서 화면에 보여줬어요(서버에는 저장하지 않아요).'}})}
function nwDrawRes(){var b=$('nwRes');if(!b)return;b.innerHTML='';var j=NW.res;if(!j)return;
 var c=el('div','nwS');c.appendChild(el('h3',null,j.mode==='general'?'📰 문서 요약 결과':'📊 AI 해석 결과'));c.appendChild(el('p','ds','AI 답변을 정리한 화면이에요. 호재/악재 표시는 AI 또는 단어 규칙의 분류 참고 값이며 투자 권유가 아니에요.'));
 if(j.title_ko)c.appendChild(el('div','mt','번역 제목: '+j.title_ko));
 if(j.mode==='general'){c.appendChild(el('div','nwSum','제목 후보: '+j.seo_title));if(j.tags.length){var tg=el('div');j.tags.forEach(function(x){tg.appendChild(nwChip('t','#'+x))});c.appendChild(tg)}}
 else if(j.stocks.length){var tw=el('div','nwTw');var t=el('table','nwT'),hr=el('tr');['구분','종목','업종','분류','근거'].forEach(function(x){hr.appendChild(el('th',null,x))});t.appendChild(hr);
  j.stocks.forEach(function(s){var tr=el('tr');tr.appendChild(el('td',null,s.mentioned?'직접 언급':'연관'));var c1=el('td');c1.appendChild(nwTk(el('b',null,s.name),s.ticker));c1.appendChild(el('div','m',s.ticker+(s.market?' · '+s.market:'')));tr.appendChild(c1);tr.appendChild(el('td',null,s.sector||'-'));var c2=el('td');c2.appendChild(nwSent(s.senti));tr.appendChild(c2);tr.appendChild(el('td','m',s.reason||''));t.appendChild(tr)});tw.appendChild(t);c.appendChild(tw)}
 else c.appendChild(el('p','note','확인된 종목이 없어요.'));
 (j.warnings||[]).forEach(function(w){c.appendChild(el('p','note bad','⚠ '+w))});
 var body=el('div');nwMd(body,j.ai_text);c.appendChild(body);
 var ab=el('div','bar');ab.appendChild(bt('분석문 복사','bt2',function(){copyTxt(j.ai_text)}));
 ab.appendChild(adm(bt('💾 보관함에 저장 (관리자)','bt',function(){apiJ('/admin/api/news/save',{title:j.title_ko||(NW.resSrc||{}).title||j.seo_title||'',source:(NW.resSrc||{}).source||'',excerpt:NW.resEx||'',ai_text:j.ai_text,stocks:j.stocks,kind:j.mode}).then(function(z){if(z.error){toast(z.error);return}toast('보관함에 저장했어요')})})));
 c.appendChild(ab);b.appendChild(c)}
"""


IMG_JS = r"""
(function(){
var K=window.ImgKit;if(!K||window.NwImg)return;
var T=K.text,RR=K.rr,N=K.n;
var INK='#0f172a',MUT='#64748b',UP='#e11d48',DN='#2563eb',GOLD='#d6b25e';
var SC={p:'#ef4444',n:'#3b82f6',x:'#f59e0b',z:'#cbd5e1'};
function today(){var x=new Date(),z=function(n){return ('0'+n).slice(-2)};return x.getFullYear()+'.'+z(x.getMonth()+1)+'.'+z(x.getDate())}
function shadow(c,x,y,w,h,r){c.save();c.shadowColor='rgba(15,23,42,.14)';c.shadowBlur=22;c.shadowOffsetY=6;RR(c,x,y,w,h,r||24);c.fillStyle='#fff';c.fill();c.restore()}
function head(c,W,kicker,title,sub){var g=c.createLinearGradient(0,0,W,260);g.addColorStop(0,'#0a1228');g.addColorStop(.6,'#16275a');g.addColorStop(1,'#1e3a8a');c.fillStyle=g;c.fillRect(0,0,W,250);
 T(c,kicker,W/2,64,{s:20,w:800,c:GOLD,a:'center',ls:6});T(c,title,W/2,132,{s:52,w:900,c:'#fff',a:'center',max:W-120});T(c,sub,W/2,186,{s:24,w:600,c:'#bfdbfe',a:'center',max:W-120});T(c,today()+' 기준 · 공개 뉴스 제목 자동 집계(참고용)',W/2,226,{s:19,w:600,c:'rgba(255,255,255,.7)',a:'center'})}
function foot(c,W,y){c.fillStyle='rgba(100,116,139,.35)';c.fillRect(60,y,W-120,2);T(c,'호재성·악재성은 단어 기준의 분류 참고 값이며 투자 권유가 아니에요. AI 해석은 틀릴 수 있어요.',W/2,y+40,{s:18,w:600,c:MUT,a:'center',max:W-120});T(c,'투자 전 원문 기사와 DART·KIND 공시를 꼭 확인하세요',W/2,y+70,{s:18,w:700,c:'#92400e',a:'center',max:W-120})}
function title2(c,y,h,t,sub){shadow(c,40,y,1000,h,24);c.fillStyle=GOLD;RR(c,66,y+26,6,30,3);c.fill();T(c,t,86,y+50,{s:26,w:900,c:INK});if(sub)T(c,sub,1014,y+49,{s:16,w:500,c:'#94a3b8',a:'right'})}
function spark(c,x,y,w,h,cl){if(!cl||cl.length<2){T(c,'시세 없음',x+w/2,y+h/2+6,{s:16,w:600,c:'#94a3b8',a:'center'});return}
 var mn=Math.min.apply(null,cl),mx=Math.max.apply(null,cl),rg=mx-mn||1,col=cl[cl.length-1]>=cl[0]?UP:DN;c.save();c.beginPath();cl.forEach(function(v,i){var px=x+w*i/(cl.length-1),py=y+h-(v-mn)/rg*h;if(i)c.lineTo(px,py);else c.moveTo(px,py)});c.lineWidth=3;c.lineJoin='round';c.strokeStyle=col;c.stroke();c.lineTo(x+w,y+h);c.lineTo(x,y+h);c.closePath();c.globalAlpha=.1;c.fillStyle=col;c.fill();c.restore()}
function wrapLines(lines,maxW,font,maxN){var tm=K.make(10,10,1).c,out=[];lines.forEach(function(s){K.wrap(tm,s,maxW,font).forEach(function(l){out.push(l)})});if(out.length>maxN){out=out.slice(0,maxN);out[maxN-1]=out[maxN-1].replace(/.{0,2}$/,'')+'…'}return out}
function sentLabel(s){return s>0?['호재',SC.p]:(s<0?['악재',SC.n]:['중립','#94a3b8'])}
/* 종목 줄(이름·분류·그래프·시세·이유) */
function stockRows(c,y,stocks,minis){var yy=y;stocks.forEach(function(s,i){var rh=s.reason?98:76;if(i%2===0){c.fillStyle='#f8fafc';c.fillRect(56,yy-4,968,rh)}
 T(c,s.name||s.ticker,76,yy+30,{s:25,w:800,c:INK,max:230});T(c,s.ticker+(s.market?' · '+s.market:'')+(s.sector?' · '+s.sector:''),76,yy+54,{s:15,w:600,c:'#94a3b8',max:230});
 var sl=sentLabel(s.senti);RR(c,330,yy+10,64,30,15);c.fillStyle=sl[1];c.fill();T(c,sl[0],362,yy+32,{s:17,w:800,c:'#fff',a:'center'});T(c,s.mentioned?'직접 언급':'연관',362,yy+58,{s:14,w:700,c:MUT,a:'center'});
 var m=minis&&minis[s.ticker];spark(c,420,yy+8,300,52,m&&m.closes);
 if(m&&m.last!=null){T(c,N(m.last)+'원',1004,yy+30,{s:22,w:800,c:INK,a:'right'});var ch=m.chg;T(c,'전일 '+(ch==null?'-':(ch>0?'+':'')+ch+'%')+(m.chg20==null?'':' · 20일 '+(m.chg20>0?'+':'')+m.chg20+'%'),1004,yy+54,{s:16,w:800,c:ch>0?UP:(ch<0?DN:MUT),a:'right',max:270})}
 if(s.reason)T(c,s.reason,76,yy+86,{s:16,w:500,c:'#475569',max:920});yy+=rh+8});return yy}
function stocksH(stocks){var h=0;stocks.forEach(function(s){h+=(s.reason?98:76)+8});return h}
function dash(D,scale){var W=1080,ov=D.ov,cn=ov.counts,tot=(cn['호재성']+cn['악재성']+cn['혼재']+cn['중립'])||1;
 var th=(ov.themes||[]).slice(0,6),st=(ov.stocks||[]).slice(0,8),ai=D.ai;var alines=ai?wrapLines([ai.summary].concat(ai.lines||[]).filter(Boolean),920,'600 21px '+K.FONT,10):[];
 var H=250+40+170+30+130+30+(th.length?80+th.length*54:0)+(th.length?30:0)+(st.length?80+st.length*54:0)+(st.length?30:0)+(ai?(80+alines.length*34+30):0)+150;
 var m=K.make(W,H,scale),c=m.c;c.fillStyle='#f4f1ec';c.fillRect(0,0,W,H);head(c,W,'MARKET NEWS BRIEF','뉴스 대시보드',(D.label||'주요 뉴스')+' · '+ov.n+'건 · '+ov.asof);
 var y=290,cw=(W-80-4*14)/5;[['뉴스',ov.n,INK],['호재성',cn['호재성'],UP],['악재성',cn['악재성'],DN],['혼재',cn['혼재'],'#d97706'],['중립',cn['중립'],MUT]].forEach(function(s,i){var x=40+i*(cw+14);shadow(c,x,y,cw,170,22);T(c,s[0],x+cw/2,y+50,{s:22,w:800,c:MUT,a:'center'});T(c,String(s[1]),x+cw/2,y+122,{s:64,w:900,c:s[2],a:'center'})});y+=200;
 shadow(c,40,y,1000,130,24);T(c,'호재·악재 비중',70,y+42,{s:22,w:800,c:INK});var bx=70,bw=940,xx=bx;[['호재성',SC.p],['악재성',SC.n],['혼재',SC.x],['중립',SC.z]].forEach(function(s){var w=bw*cn[s[0]]/tot;if(w<=0)return;c.fillStyle=s[1];c.fillRect(xx,y+58,w,30);if(w>56)T(c,s[0]+' '+Math.round(cn[s[0]]*100/tot)+'%',xx+w/2,y+80,{s:16,w:800,c:s[0]==='중립'?'#334155':'#fff',a:'center'});xx+=w});
 T(c,'제목의 단어 기준 분류(참고용)',70,y+116,{s:15,w:600,c:'#94a3b8'});y+=160;
 if(th.length){var h1=80+th.length*54;title2(c,y,h1,'🧩 자주 나온 테마','기사 수');var mx=Math.max.apply(null,th.map(function(t){return t.n}).concat([1]));th.forEach(function(t,i){var yy=y+88+i*54;T(c,t.name,70,yy+18,{s:21,w:700,c:'#334155',max:300});RR(c,380,yy,360,24,12);c.fillStyle='#eef2f7';c.fill();RR(c,380,yy,Math.max(24,360*t.n/mx),24,12);var g=c.createLinearGradient(380,0,740,0);g.addColorStop(0,'#60a5fa');g.addColorStop(1,'#1e3a8a');c.fillStyle=g;c.fill();T(c,t.n+'건',1010,yy+20,{s:22,w:900,c:INK,a:'right'});T(c,'호재 '+t.pos+' / 악재 '+t.neg,930,yy+20,{s:15,w:700,c:MUT,a:'right'})});y+=h1+30}
 if(st.length){var h2=80+st.length*54;title2(c,y,h2,'📌 제목에 자주 나온 종목','언급 횟수');var mx2=Math.max.apply(null,st.map(function(t){return t.n}).concat([1]));st.forEach(function(t,i){var yy=y+88+i*54;T(c,t.name,70,yy+18,{s:21,w:800,c:INK,max:230});T(c,t.ticker,70,yy+38,{s:13,w:600,c:'#94a3b8'});RR(c,330,yy,400,24,12);c.fillStyle='#eef2f7';c.fill();RR(c,330,yy,Math.max(24,400*t.n/mx2),24,12);c.fillStyle='#6366f1';c.fill();T(c,t.n+'건',1010,yy+20,{s:22,w:900,c:INK,a:'right'});T(c,'호재 '+t.pos+' / 악재 '+t.neg,930,yy+20,{s:15,w:700,c:MUT,a:'right'})});y+=h2+30}
 if(ai){var h3=80+alines.length*34+30;title2(c,y,h3,'🤖 AI 총평','AI가 정리한 참고 의견');alines.forEach(function(l,i){T(c,l,70,y+92+i*34,{s:21,w:i===0?800:500,c:i===0?INK:'#334155'})});y+=h3+30}
 foot(c,W,y);return m.cv}
function related(D,scale){var W=1080,st=(D.stocks||[]).slice(0,10);var H=250+40+90+Math.max(1,stocksH(st))+40+150;var m=K.make(W,H,scale),c=m.c;c.fillStyle='#f4f1ec';c.fillRect(0,0,W,H);head(c,W,'RELATED STOCKS','뉴스 관련 종목',(D.label||'주요 뉴스')+' · '+st.length+'종목 · 최근 30일 시세');
 var y=290,hh=90+Math.max(1,stocksH(st))+10;title2(c,y,hh,'관련 종목 · 시세 그래프','최근 30거래일 종가');if(!st.length)T(c,'확인된 종목이 없어요',86,y+130,{s:22,w:600,c:MUT});else stockRows(c,y+78,st,D.minis);y+=hh+30;foot(c,W,y);return m.cv}
function res(D,scale){var W=1080,st=(D.stocks||[]).slice(0,8);var lines=wrapLines([D.summary].concat(D.lines||[]).filter(Boolean),920,'600 21px '+K.FONT,10);var tl=wrapLines([D.title||'뉴스'],900,'900 34px '+K.FONT,3);
 var H=250+40+(80+tl.length*46)+30+(80+lines.length*34+30)+30+(st.length?(90+stocksH(st)+10)+30:0)+150;var m=K.make(W,H,scale),c=m.c;c.fillStyle='#f4f1ec';c.fillRect(0,0,W,H);
 head(c,W,D.kind==='ov'?'MARKET NEWS · AI VIEW':'NEWS ANALYSIS',D.kind==='ov'?'오늘 뉴스 AI 총평':'뉴스 분석 카드',(D.source||'')+(D.kind==='ov'?'':' · AI 해석(참고용)'));
 var y=290,h1=80+tl.length*46;shadow(c,40,y,1000,h1,24);c.fillStyle=GOLD;RR(c,66,y+26,6,30,3);c.fill();T(c,D.kind==='ov'?'분석 대상':'기사 제목',86,y+50,{s:22,w:800,c:MUT});tl.forEach(function(l,i){T(c,l,70,y+98+i*46-10,{s:32,w:900,c:INK})});y+=h1+30;
 var h2=80+lines.length*34+30;title2(c,y,h2,'🤖 AI 해석 요약','참고용');lines.forEach(function(l,i){T(c,l,70,y+92+i*34,{s:21,w:i===0?800:500,c:i===0?INK:'#334155'})});y+=h2+30;
 if(st.length){var h3=90+stocksH(st)+10;title2(c,y,h3,'📊 관련 종목 · 시세 그래프','최근 30거래일 종가');stockRows(c,y+78,st,D.minis);y+=h3+30}
 foot(c,W,y);return m.cv}
window.NwImg={dash:function(D,scale){var it=[{idx:1,label:'뉴스 대시보드',canvas:dash(D,scale)}];if((D.stocks||[]).length)it.push({idx:2,label:'관련 종목 시세',canvas:related(D,scale)});return it},
 res:function(D,scale){return [{idx:1,label:D.kind==='ov'?'AI 총평 카드':'뉴스 분석 카드',canvas:res(D,scale)}]}};
})();
"""


def register():
    C.register_table_hook(_ensure_tables)
    try:
        C.register_news_hook(_news_hook)
    except Exception as e:
        print(f"[뉴스보관] 훅 등록 실패(무시): {e}")
    C.register_menu({"id": "news", "label": "뉴스분석", "icon": "📰", "public_path": "/m/news", "admin_path": "/admin#nw",
                     "desc": "최신 뉴스·종목 뉴스 제목 모아보기, 호재성/악재성·테마 키워드 분류(참고용), 저장된 분석 기록·AI 해석(수동)", "access": "admin"})
    C.register_prompt("news_analyze", {
        "title": "뉴스분석 AI 프롬프트(증권 뉴스)", "default": NEWS_DEFAULT, "required": ["{text}"], "must_have": ["```json"],
        "vars": "{source}=출처 · {title}=제목 · {today}=분석일 · {text}=뉴스 본문(필수)",
        "desc": "뉴스분석에서 AI에게 보내는 요청문. 마지막의 ```json 블록(mentioned/related/sentiment/title_ko)이 있어야 종목·호재/악재 분류를 자동으로 읽어요."})
    C.register_prompt("news_overview", {
        "title": "뉴스분석 AI 프롬프트(전체 뉴스 총평)", "default": NEWS_OVERVIEW_DEFAULT, "required": ["{headlines}"], "must_have": ["```json"],
        "vars": "{today}=분석일 · {cat}=뉴스 구분 · {count}=뉴스 건수 · {stats}=사이트 집계 참고값 · {headlines}=뉴스 목록(필수)",
        "desc": "뉴스 목록 전체를 AI가 총평하는 요청문. 마지막의 ```json 블록(mentioned/related/sentiment)이 있어야 관련종목 표·그래프를 자동으로 만들어요."})
    C.register_prompt("news_general", {
        "title": "뉴스분석 AI 프롬프트(일반 문서 요약)", "default": GENERAL_DEFAULT, "required": ["{text}"], "must_have": ["META_JSON"],
        "vars": "{source}=출처 · {title}=제목 · {text}=문서 본문(필수)", "desc": "수출입동향·보고서 같은 일반 문서를 쉬운 글로 요약할 때 쓰는 요청문. 마지막 META_JSON 줄을 유지해야 제목·태그를 읽어요."})
    C.register_prompt("news_senti_all", {
        "title": "긍정뉴스 지속종목 AI 프롬프트(1차 총평)", "default": SENTI_ALL_DEFAULT, "required": ["{block}"], "must_have": ["[뉴스 심리 총평]"],
        "vars": "{days}=집계 기간 · {block}=종목 순위 목록(필수)", "desc": "긍정뉴스 지속종목 순위 전체를 AI가 총평하는 요청문. [섹션명] 형식을 유지해야 화면에 카드로 나뉘어 보여요."})
    C.register_prompt("news_senti_stock", {
        "title": "긍정뉴스 지속종목 AI 프롬프트(종목 코멘트)", "default": SENTI_STOCK_DEFAULT, "required": ["{news_lines}"], "must_have": ["[뉴스 흐름 요약]"],
        "vars": "{name} {ticker} {market} {direct_pos_days} {direct_neg_days} {pos_ratio} {swept_pos_count} {perf_txt} {first_pos_date} {news_lines}=헤드라인(필수)",
        "desc": "한 종목의 뉴스 흐름을 AI가 코멘트하는 요청문. [섹션명] 형식을 유지해야 화면에 카드로 나뉘어 보여요."})
    C.register_admin_tab("nw", "📰 뉴스분석", TAB_JS + "\n" + IMG_JS, "nwLoad", menu="news")
    C.register_feature(MENU, "latest", "최신 뉴스 모음", "네이버 금융 주요 뉴스·속보·많이 본 뉴스의 제목·언론사·링크 모아보기", default="public",
                       endpoints=["/admin/api/news/latest"])
    C.register_feature(MENU, "stock", "종목 뉴스 조회", "종목 이름·코드로 최근 2주 뉴스 제목 조회", default="public", endpoints=["/admin/api/news/stock"])
    C.register_feature(MENU, "classify", "키워드 분류(호재성·악재성·테마)", "뉴스 제목의 호재성·악재성 단어와 테마 키워드를 참고용으로 분류", default="member",
                       endpoints=["/admin/api/news/classify"])
    C.register_feature(MENU, "themes", "테마·이슈 요약", "저장된 뉴스 분석 기록을 모아 본 테마·업종·언급 종목 요약", default="member", endpoints=["/admin/api/news/themes"])
    C.register_feature(MENU, "leader", "긍정뉴스 지속 종목", "직접 언급되며 호재로 분류된 날이 많은 종목 순위(참고용)", default="member", endpoints=["/admin/api/news/leader"])
    C.register_feature(MENU, "archive", "뉴스 DB(분류 저장)", "가져온 뉴스를 종목·테마·호재/악재·날짜로 분류해 쌓아 둔 보관함 — 추세 분석용(관리자 전용)", default="admin",
                       endpoints=["/admin/api/news/arch/summary", "/admin/api/news/arch/list", "/admin/api/news/arch/csv"])
    C.register_feature(MENU, "board", "분석 기록 보관함", "저장된 뉴스 분석의 제목·출처·AI 분석문 열람과 검색", default="L2",
                       endpoints=["/admin/api/news/log/list", "/admin/api/news/log/detail"])
    C.register_feature(MENU, "ai", "AI 뉴스 해석(수동)", "뉴스를 붙여 넣어 AI 프롬프트를 만들고, 받은 답을 종목·분류 표로 정리", default="L2", kind="ai",
                       endpoints=["/admin/api/news/prompt", "/admin/api/news/parse", "/admin/api/news/leader/prompt", "/admin/api/news/overview/prompt"])
    C.register_feature(MENU, "overview", "전체 뉴스 대시보드·관련종목 그래프", "뉴스 전체의 호재·악재 건수, 자주 나온 테마·종목을 한눈에 보는 대시보드(이미지 만들기 포함)와 관련종목 시세 그래프", default="member",
                       endpoints=["/admin/api/news/overview", "/admin/api/news/mini"])
    C.register_feature(MENU, "url", "기사 주소(URL)로 AI 분석", "기사 주소만 넣으면 본문을 읽어 AI 요청문을 만들어 줘요(뉴스를 클릭해 분석할 때도 사용)", default="L2", kind="ai",
                       endpoints=["/admin/api/news/url"])
    C.register_flow("news", "📰 뉴스분석", "① 뉴스를 누르거나 [전체 AI 총평]·URL 분석을 시작(직접 시작)", [
        {"id": "ai", "label": "② AI 분석", "desc": "시작하면 AI 요청문 창을 자동으로 열어요. 답변을 복사해 돌아오면 관련종목 표·그래프가 만들어져요."},
        {"id": "img", "label": "③ 이미지 만들기", "desc": "AI 분석이 끝나면 대시보드·관련종목 이미지를 자동으로 그려요."},
        {"id": "blog", "label": "④ 블로그 글 만들기", "desc": "이미지 다음에 블로그용 글(HTML)을 자동으로 만들어요(관리자 화면)."},
        {"id": "post", "label": "⑤ 블로그 복사·열기", "desc": "글이 만들어지면 서식을 복사하고 블로그 글쓰기 화면을 새 창으로 열어요. 붙여 넣기(Ctrl+V)만 직접 하면 돼요. 브라우저가 복사·새 창을 막으면 [📋 복사하고 블로그 열기]를 한 번 눌러 주세요."}])
    return bp
