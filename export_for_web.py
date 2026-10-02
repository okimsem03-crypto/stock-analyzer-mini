#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
원본 프로그램의 DB(stock_app.db)를 '웹 미니로 옮기기 좋은 파일' 하나로 내보냅니다.

 · 이 파일은 내 PC에서 한 번 실행합니다. 인터넷에 접속하지도, 비밀번호를 묻지도 않습니다.
 · 원본 DB는 읽기만 하고 절대 바꾸지 않습니다.
 · API 키·비밀번호·앱 잠금 등이 들어 있는 설정 표(app_settings)는 통째로 옮기지 않고, 스캔 조건 같은
   안전한 항목만 골라 담습니다. 개인 기록(관심종목·장부·예측 등)은 기본으로 빠집니다.
 · 결과 파일(stock_export_날짜.jsonl.gz)을 관리자 화면 [📦 데이터]에서 올리면 됩니다.

사용법
   python export_for_web.py                       → DB 위치를 물어봅니다(파일을 이 창에 끌어다 놓아도 됩니다)
   python export_for_web.py C:\\경로\\stock_app.db    → 바로 실행
   옵션: --personal   개인 기록(관심종목·장부·예측·블로그추적 등)도 포함
         --tables a,b 지정한 표만 포함(파일이 너무 클 때 나눠서 올리기)
         --out 파일   결과 파일 이름 지정
파이썬 표준 기능만 사용합니다(추가 설치 없음).
"""
import sys, os, re, json, gzip, math, hashlib, sqlite3, argparse, datetime

FORMAT = "stock-export-1"

# 표 분류 — 서버(menus/dataimport.py)의 허용 목록과 같아야 합니다(시험으로 확인).
MARKET = ["company_relations", "stock_theme_map", "stock_price_cache", "investor_scan_cache", "dart_cache",
          "deepdive_cache", "deepdive_ai", "deepdive_peers", "network_cache", "newlisting_meta",
          "delist_snapshots", "limit_scan_log", "analysis_cache"]
ADMIN = ["daily_recommend", "daily_ai_result", "discovery_pick_track", "challenge_pick_track",
         "challenge_saved_results", "ai_pick_track", "sp_pick_track", "sp_pick_blog", "sell_signal_log",
         "ir_saved_results", "macro_pick_track", "prompt_evolution", "issue_analysis_log",
         "news_analysis_log", "news_analysis_session"]
PERSONAL = ["watchlist", "watchlist_categories", "predictions", "vp_checks", "purchase_records", "trade_ledger",
            "blog_post_track", "blog_audit_posts", "blog_neighbors", "deepdive_blog_log", "analysis_log",
            "recent_searches", "user_themes", "user_theme_stocks"]
# 이름을 바꿔 담는 표: 원본 이름 → 웹 이름
RENAMED = {"app_settings": "legacy_app_settings", "ai_prompts": "legacy_ai_prompts"}
# app_settings 에서 가져갈 항목(앞부분 일치) / 이름에 이 글자가 있으면 어떤 경우에도 가져가지 않음
SETTINGS_ALLOW = ("sc_", "scan_", "ai_track_", "short_", "theme_last_", "heatmap_sectors", "issue_keywords",
                  "delist_criteria")
SETTINGS_DENY = re.compile(r"(key|pw|pass|secret|hash|salt|token|smtp|mail|_id$|lock)", re.I)
SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,}|sk-ant-[A-Za-z0-9_\-]{20,})")


def settings_ok(key, value):
    if not key.startswith(SETTINGS_ALLOW) or SETTINGS_DENY.search(key):
        return False
    return not SECRET_VALUE.search(str(value or ""))


def classify(declared):
    d = (declared or "").upper()
    if "INT" in d:
        return "int"
    if any(x in d for x in ("REAL", "FLOA", "DOUB")):
        return "real"
    return "text"


def final_type(declared, observed):
    observed = set(observed) - {"null"}
    if "text" in observed or "blob" in observed:
        return "text"
    if observed and observed <= {"integer", "real"}:
        return "real" if ("real" in observed or classify(declared) == "real") else "int"
    return classify(declared)


def clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, bytes):
        return None
    if isinstance(v, str):
        return v.replace("\x00", "")
    return v


def find_db(arg):
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [arg] if arg else []
    cands += [os.path.join(os.getcwd(), "stock_app.db"), os.path.join(here, "stock_app.db"),
              os.path.join(here, "..", "stock_app.db")]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    if arg:
        return None
    print("원본 DB(stock_app.db) 위치를 찾지 못했어요.")
    p = input("stock_app.db 파일을 이 창에 끌어다 놓고 Enter 를 누르세요: ").strip().strip('"').strip("'")
    return os.path.abspath(p) if p and os.path.isfile(p) else None


def main():
    ap = argparse.ArgumentParser(description="원본 DB → 웹 미니 가져오기 파일")
    ap.add_argument("db", nargs="?")
    ap.add_argument("--personal", action="store_true")
    ap.add_argument("--tables", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    db = find_db(a.db)
    if not db:
        print("DB 파일을 찾지 못해 종료합니다.")
        return 1
    want_personal = a.personal
    if not a.personal and not a.tables and sys.stdin.isatty() and not a.db:
        want_personal = input("개인 기록(관심종목·장부·예측 등)도 포함할까요? [y/N] ").strip().lower() == "y"
    conn = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    plan = [(t, t) for t in MARKET + ADMIN if t in present]
    plan += [(s, d) for s, d in RENAMED.items() if s in present]
    if want_personal:
        plan += [(t, t) for t in PERSONAL if t in present]
    if a.tables:
        pick = {x.strip() for x in a.tables.split(",") if x.strip()}
        plan = [(s, d) for s, d in plan if s in pick or d in pick]
    known = set(MARKET + ADMIN + PERSONAL + list(RENAMED))
    skipped = sorted(present - known - {"sqlite_sequence", "ticker_names"})
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out = a.out or os.path.join(os.path.dirname(db), f"stock_export_{stamp}.jsonl.gz")
    print(f"원본 DB: {db}\n내보낼 표 {len(plan)}개 → {out}\n")
    total_rows = 0
    metas = []
    with gzip.open(out, "wb", compresslevel=6) as gz:
        def w(obj):
            gz.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        w({"format": FORMAT, "created": datetime.datetime.now().isoformat(timespec="seconds"),
           "source": os.path.basename(db), "tables": [d for _, d in plan]})
        for src, dest in plan:
            info = conn.execute(f'PRAGMA table_info("{src}")').fetchall()
            cols = [r[1] for r in info]
            pkcols = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
            types = []
            for r in info:
                obs = [x[0] for x in conn.execute(f'SELECT DISTINCT typeof("{r[1]}") FROM "{src}"')]
                types.append(final_type(r[2], obs))
            idx = []
            for row in conn.execute(f'PRAGMA index_list("{src}")').fetchall():
                _, iname, uniq, origin = row[0], row[1], row[2], row[3]
                partial = row[4] if len(row) > 4 else 0
                if origin == "pk" or partial:
                    continue
                icols = [x[2] for x in conn.execute(f'PRAGMA index_info("{iname}")').fetchall()]
                if icols and all(c in cols for c in icols):
                    idx.append({"cols": icols, "unique": bool(uniq)})
            identity = len(pkcols) == 1 and types[cols.index(pkcols[0])] == "int"
            rows_iter = conn.execute("SELECT " + ",".join(f'"{c}"' for c in cols) + f' FROM "{src}"')
            sha = hashlib.sha256()
            n = 0
            lines = []
            for row in rows_iter:
                if src == "app_settings":
                    if not settings_ok(row[cols.index("key")], row[cols.index("value")]):
                        continue
                line = json.dumps([clean(v) for v in row], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                lines.append(line)
                sha.update(line)
                n += 1
            w({"table": dest, "src": src, "cols": [[c, t] for c, t in zip(cols, types)], "pk": pkcols,
               "identity": identity, "indexes": idx, "rows": n})
            for line in lines:
                gz.write(line)
            w({"end": dest, "rows": n, "sha256": sha.hexdigest()})
            total_rows += n
            metas.append((dest, n))
            note = "  (안전한 설정 항목만)" if src == "app_settings" else ""
            print(f"  {dest:<26}{n:>9,}행{note}")
    size = os.path.getsize(out) / 1024 / 1024
    print(f"\n완료: {len(plan)}개 표, 총 {total_rows:,}행 → {out} ({size:.1f}MB)")
    if skipped:
        print("이번에 가져가지 않은 표(알 수 없는 표):", ", ".join(skipped))
    if not want_personal:
        print("개인 기록(관심종목·장부·예측 등)은 포함하지 않았습니다.")
    if size > 90:
        print("⚠ 파일이 90MB를 넘어 올리기 어려울 수 있어요. --tables 옵션으로 나누어 내보내세요.")
    print("\n다음: 관리자 화면 → [📦 데이터] 에서 이 파일을 올리세요. 이 파일은 올린 뒤 지워도 됩니다.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 1
    if os.name == "nt" and sys.stdin.isatty() and len(sys.argv) == 1:
        input("\nEnter 를 누르면 창이 닫힙니다.")
    sys.exit(code)
