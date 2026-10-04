"""📦 데이터 가져오기 (관리자 도구) — 원본 프로그램의 DB를 웹 DB로 옮긴다.

흐름: 내 PC에서 export_for_web.py 실행 → 만들어진 파일(.jsonl.gz)을 관리자 화면 [📦 데이터]에서 올림
      → 서버가 파일 무결성(해시)과 표 구조를 검사해 미리보기를 보여줌 → 관리자가 표를 골라 가져오기(백그라운드 작업).

안전 장치
  · 관리자 로그인 + CSRF 필수. 아래 허용 목록(TABLES)에 있는 표만 만들거나 바꾼다 — 파일이 다른 표(관리자 세션 등)를
    건드릴 수 없다. 표·열 이름은 정규식으로 검사하고 값은 모두 파라미터로만 넣는다.
  · 표마다 한 트랜잭션: 실패하면 그 표는 원래대로 남는다. 이미 데이터가 있는 표는 '덮어쓰기'를 명시해야 교체한다.
  · 개인 기록(관심종목·장부·예측 등)은 별도 확인을 거쳐야 하고, 설정·프롬프트 표는 API 키·비밀번호가 없는
    항목만 통과시킨다(내보내기 도구와 서버에서 이중으로 거른다).
이 표들을 읽는 화면은 이후 단계에서 메뉴 모듈이 만들며, 각 메뉴의 접근 등급이 노출 범위를 정한다.
"""
import os, re, gzip, json, time, hashlib, secrets, threading, tempfile
from flask import Blueprint, request, send_file
from menu_ctx import C

bp = Blueprint("dataimport", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_history_conn", "_job_new", "_job_busy", "_dbx")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

FORMAT = "stock-export-1"
MAX_UPLOAD = 100 * 1024 * 1024        # 올릴 수 있는 파일 크기(Cloudflare 무료 한도와 같음)
MAX_LINE = 6 * 1024 * 1024            # 한 줄(한 행) 상한
MAX_UNPACKED = 1200 * 1024 * 1024     # 압축을 푼 총량 상한(압축 폭탄 방지)
MAX_ROWS_PER_TABLE = 3_000_000
BATCH = 1000
STAGE_TTL = 2 * 3600

# dest 표 이름: (종류, 화면에 보일 이름). 종류: market=시장·종목 자료 / admin=관리자 전용 자료 / personal=개인 기록
TABLES = {
    "company_relations": ("market", "기업 관계(관계 네트워크)"), "stock_theme_map": ("market", "종목-테마 연결"),
    "stock_price_cache": ("market", "종목 시세 캐시"), "investor_scan_cache": ("market", "투자자별 수급 캐시"),
    "dart_cache": ("market", "DART 공시 캐시"), "deepdive_cache": ("market", "심층분석 캐시"),
    "deepdive_ai": ("market", "심층분석 AI 결과"), "deepdive_peers": ("market", "심층분석 동종업체"),
    "network_cache": ("market", "관계 네트워크 캐시"), "newlisting_meta": ("market", "신규상장 정보"),
    "delist_snapshots": ("market", "상폐 스냅샷(원본)"), "limit_scan_log": ("market", "상하한가 스캔 기록"),
    "analysis_cache": ("market", "종목분석 캐시(원본)"),
    "daily_recommend": ("admin", "오늘추천 기록"), "daily_ai_result": ("admin", "오늘추천 AI 결과"),
    "discovery_pick_track": ("admin", "종목발굴 추적"), "challenge_pick_track": ("admin", "도전주 추적"),
    "challenge_saved_results": ("admin", "도전주 저장 결과"), "ai_pick_track": ("admin", "AI 추천 추적"),
    "sp_pick_track": ("admin", "종합추천 추적"), "sp_pick_blog": ("admin", "종합추천 블로그"),
    "sell_signal_log": ("admin", "매도신호 기록"), "ir_saved_results": ("admin", "저장된 분석 결과"),
    "macro_pick_track": ("admin", "거시경제 예측 추적"), "prompt_evolution": ("admin", "AI 학습(프롬프트 진화) 이력"),
    "issue_analysis_log": ("admin", "이슈분석 기록"), "news_analysis_log": ("admin", "뉴스분석 기록"),
    "news_analysis_session": ("admin", "뉴스분석 세션"),
    "legacy_app_settings": ("admin", "원본 설정(안전한 항목만)"), "legacy_ai_prompts": ("admin", "원본 AI 프롬프트"),
    "watchlist": ("personal", "관심종목"), "watchlist_categories": ("personal", "관심종목 분류"),
    "predictions": ("personal", "예측 기록"), "vp_checks": ("personal", "예측 점검"),
    "purchase_records": ("personal", "매수 기록"), "trade_ledger": ("personal", "장부(거래 내역)"),
    "blog_post_track": ("personal", "블로그 추적"), "blog_audit_posts": ("personal", "블로그 글 점검"),
    "blog_neighbors": ("personal", "블로그 이웃"), "deepdive_blog_log": ("personal", "심층분석 블로그 기록"),
    "analysis_log": ("personal", "분석 기록"), "recent_searches": ("personal", "최근 검색"),
    "user_themes": ("personal", "내 테마"), "user_theme_stocks": ("personal", "내 테마 종목"),
}
CAT_LABEL = {"market": "시장·종목 자료", "admin": "관리자 전용 자료", "personal": "개인 기록"}

_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SETTINGS_ALLOW = ("sc_", "scan_", "ai_track_", "short_", "theme_last_", "heatmap_sectors", "issue_keywords",
                   "delist_criteria")
_SETTINGS_DENY = re.compile(r"(key|pw|pass|secret|hash|salt|token|smtp|mail|_id$|lock)", re.I)
_SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,}|sk-ant-[A-Za-z0-9_\-]{20,})")

_STAGE = {}        # 올려 둔 파일 1개: {"id","path","at","name","preview"}
_LOCK = threading.Lock()


def _q(name):
    if not _NAME_RE.match(name):
        raise ValueError("허용되지 않은 이름")
    return '"' + name + '"'


# ── 파일 읽기 ──
class BadFile(ValueError):
    pass


def _iter_file(path):
    """(종류, 객체 또는 줄 바이트) 를 차례로 돌려준다. 종류: ctl(JSON 객체) / row(행 한 줄)."""
    total = 0
    try:
        with gzip.open(path, "rb") as f:
            while True:
                line = f.readline(MAX_LINE + 1)
                if not line:
                    return
                if len(line) > MAX_LINE:
                    raise BadFile("한 행이 너무 커요.")
                total += len(line)
                if total > MAX_UNPACKED:
                    raise BadFile("압축을 푼 크기가 너무 커요.")
                if line[:1] == b"[":
                    yield "row", line
                elif line[:1] == b"{":
                    try:
                        yield "ctl", json.loads(line)
                    except ValueError:
                        raise BadFile("파일 형식이 올바르지 않아요.")
                elif line.strip():
                    raise BadFile("파일 형식이 올바르지 않아요.")
    except (OSError, EOFError) as e:
        raise BadFile("압축 파일을 읽지 못했어요(내보내기 도구로 만든 .jsonl.gz 파일이 맞나요?).")


def _check_meta(m):
    t = m.get("table")
    if not isinstance(t, str) or not _NAME_RE.match(t):
        raise BadFile("표 이름이 올바르지 않아요.")
    cols = m.get("cols")
    if not isinstance(cols, list) or not cols or len(cols) > 200:
        raise BadFile(f"{t}: 열 정보가 올바르지 않아요.")
    seen = set()
    for c in cols:
        if not (isinstance(c, list) and len(c) == 2 and isinstance(c[0], str) and _NAME_RE.match(c[0])
                and c[1] in ("int", "real", "text") and c[0] not in seen):
            raise BadFile(f"{t}: 열 이름·형식이 올바르지 않아요.")
        seen.add(c[0])
    names = [c[0] for c in cols]
    pk = m.get("pk") or []
    if not isinstance(pk, list) or any(p not in names for p in pk):
        raise BadFile(f"{t}: 기본키 정보가 올바르지 않아요.")
    for ix in m.get("indexes") or []:
        if not (isinstance(ix, dict) and isinstance(ix.get("cols"), list) and ix["cols"]
                and all(c in names for c in ix["cols"])):
            raise BadFile(f"{t}: 색인 정보가 올바르지 않아요.")
    return t


def scan_file(path):
    """파일 전체를 훑어 표별 행 수·해시를 검사한다. 문제가 있으면 BadFile."""
    header, tables, cur, sha, n = None, [], None, None, 0
    for kind, obj in _iter_file(path):
        if kind == "ctl":
            if header is None:
                if obj.get("format") != FORMAT:
                    raise BadFile("이 프로그램용 내보내기 파일이 아니에요(형식 불일치).")
                header = obj
            elif "table" in obj:
                if cur is not None:
                    raise BadFile("파일이 중간에 끊겼어요.")
                _check_meta(obj)
                cur, sha, n = dict(obj), hashlib.sha256(), 0
            elif "end" in obj:
                if cur is None or obj.get("end") != cur["table"]:
                    raise BadFile("파일 구조가 올바르지 않아요.")
                if obj.get("rows") != n or n != cur.get("rows"):
                    raise BadFile(f"{cur['table']}: 행 수가 맞지 않아요(파일이 손상됐을 수 있어요).")
                if obj.get("sha256") != sha.hexdigest():
                    raise BadFile(f"{cur['table']}: 내용 확인값이 달라요(파일이 손상됐을 수 있어요).")
                cur["counted"] = n
                tables.append(cur)
                cur = None
            else:
                raise BadFile("파일 구조가 올바르지 않아요.")
        else:
            if cur is None:
                raise BadFile("파일 구조가 올바르지 않아요.")
            sha.update(obj)
            n += 1
            if n > MAX_ROWS_PER_TABLE:
                raise BadFile("행이 너무 많아요.")
    if header is None or cur is not None:
        raise BadFile("파일이 중간에 끊겼어요.")
    if not tables:
        raise BadFile("들어 있는 표가 없어요.")
    return header, tables


def _existing(dest):
    try:
        rows = _dbx(f"SELECT COUNT(*) FROM {_q(dest)}", (), fetch=True)
        return int(rows[0][0])
    except Exception:
        return None


def _preview(header, tables):
    out = []
    for m in tables:
        t = m["table"]
        cat = TABLES.get(t)
        out.append({"table": t, "label": cat[1] if cat else t, "category": cat[0] if cat else "",
                    "cat_label": CAT_LABEL.get(cat[0], "") if cat else "", "rows": m["counted"],
                    "cols": len(m["cols"]), "existing": _existing(t) if cat else None,
                    "allowed": bool(cat), "problem": "" if cat else "허용되지 않은 표라 가져오지 않아요."})
    return {"created": header.get("created", ""), "source": str(header.get("source", ""))[:80], "tables": out}


def _cleanup():
    now = time.time()
    d = tempfile.gettempdir()
    for fn in os.listdir(d):
        if fn.startswith("stock_import_") and fn.endswith(".gz"):
            p = os.path.join(d, fn)
            try:
                if now - os.path.getmtime(p) > STAGE_TTL:
                    os.remove(p)
            except OSError:
                pass
    if _STAGE and now - _STAGE.get("at", 0) > STAGE_TTL:
        _STAGE.clear()


# ── 관리자 API ──
@bp.route("/admin/api/import/state")
def import_state():
    deny = _admin_deny()
    if deny:
        return deny
    _cleanup()
    known = [{"table": t, "label": v[1], "category": v[0], "cat_label": CAT_LABEL[v[0]], "existing": _existing(t)}
             for t, v in TABLES.items()]
    tool = os.path.isfile(_tool_path())
    return _admin_json({"tables": known, "staged": _STAGE.get("preview"), "staged_name": _STAGE.get("name", ""),
                        "staged_id": _STAGE.get("id", ""),
                        "tool": tool, "max_mb": MAX_UPLOAD // (1024 * 1024), "busy": _job_busy("import")})


def _tool_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_for_web.py")


@bp.route("/admin/tools/export_for_web.py")
def import_tool_download():
    deny = _admin_deny()
    if deny:
        return deny
    p = _tool_path()
    if not os.path.isfile(p):
        return _admin_json({"error": "도구 파일이 서버에 없어요(export_for_web.py 를 함께 올렸는지 확인하세요)."}, 404)
    resp = send_file(p, as_attachment=True, download_name="export_for_web.py", mimetype="text/x-python")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.route("/admin/api/import/upload", methods=["POST"])
def import_upload():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if _job_busy("import"):
        return _admin_json({"error": "가져오기가 진행 중이에요. 끝난 뒤 다시 올리세요."}, 409)
    request.max_content_length = MAX_UPLOAD + 1024 * 1024      # 이 요청만 큰 파일 허용(전역 상한은 5MB)
    try:
        f = request.files.get("f")
    except Exception:
        return _admin_json({"error": f"파일이 너무 커요(최대 {MAX_UPLOAD // 1024 // 1024}MB). --tables 옵션으로 나눠 내보내세요."}, 413)
    if not f or not f.filename:
        return _admin_json({"error": "파일을 선택하세요."}, 400)
    _cleanup()
    with _LOCK:
        old = _STAGE.pop("path", None)
        _STAGE.clear()
        if old and os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
        sid = secrets.token_hex(8)
        path = os.path.join(tempfile.gettempdir(), f"stock_import_{sid}.gz")
        f.save(path)
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                magic = fh.read(2)
            if size > MAX_UPLOAD or magic != b"\x1f\x8b":
                raise BadFile("내보내기 도구가 만든 .jsonl.gz 파일이 아니에요.")
            header, tables = scan_file(path)
        except BadFile as e:
            try:
                os.remove(path)
            except OSError:
                pass
            return _admin_json({"error": str(e)}, 400)
        prev = _preview(header, tables)
        _STAGE.update(id=sid, path=path, at=time.time(), name=os.path.basename(f.filename)[:80], preview=prev,
                      metas={m["table"]: m for m in tables})
    _alog("data_import_upload", f"{_STAGE['name']} · 표 {len(prev['tables'])}개")
    return _admin_json({"preview": prev, "name": _STAGE["name"]})


@bp.route("/admin/api/import/discard", methods=["POST"])
def import_discard():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    if _job_busy("import"):
        return _admin_json({"error": "가져오기가 진행 중이에요."}, 409)
    with _LOCK:
        p = _STAGE.get("path")
        _STAGE.clear()
    if p and os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass
    return _admin_json({"ok": True})


@bp.route("/admin/api/import/run", methods=["POST"])
def import_run():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = C._json_body()
    if not _STAGE.get("path") or d.get("id") != _STAGE.get("id"):
        return _admin_json({"error": "올려 둔 파일이 없어요(2시간이 지나면 지워져요). 다시 올려 주세요."}, 400)
    metas = _STAGE["metas"]
    want = [t for t in (d.get("tables") or []) if isinstance(t, str)]
    overwrite = {t for t in (d.get("overwrite") or []) if isinstance(t, str)}
    if not want:
        return _admin_json({"error": "가져올 표를 고르세요."}, 400)
    bad = [t for t in want if t not in metas or t not in TABLES]
    if bad:
        return _admin_json({"error": f"가져올 수 없는 표예요: {', '.join(bad[:3])}"}, 400)
    if any(TABLES[t][0] == "personal" for t in want) and not d.get("include_personal"):
        return _admin_json({"error": "개인 기록은 별도 확인이 필요해요."}, 400)
    for t in want:
        ex = _existing(t)
        if ex and t not in overwrite:
            return _admin_json({"error": f"{t} 표에 이미 {ex:,}행이 있어요. 덮어쓰기를 확인하세요."}, 409)
    if _job_busy("import"):
        return _admin_json({"error": "이미 진행 중이에요."}, 409)
    jid = _job_new("import", total=len(want))
    threading.Thread(target=_import_job, args=(jid, _STAGE["path"], [metas[t] for t in want]), daemon=True).start()
    _alog("data_import_run", ", ".join(want)[:200])
    return _admin_json({"job": jid})


# ── 가져오기 본작업 ──
def _coerce(row, types):
    out = []
    for v, t in zip(row, types):
        if v is None:
            out.append(None)
        elif t == "int":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and v != int(v)):
                raise ValueError("정수 열에 정수가 아닌 값")
            out.append(int(v))
        elif t == "real":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("숫자 열에 숫자가 아닌 값")
            out.append(float(v))
        else:
            out.append(v.replace("\x00", "") if isinstance(v, str) else str(v))
    return out


def _keep_row(table, names, row):
    """설정·프롬프트 표는 비밀이 섞이지 않은 행만 통과시킨다(서버에서 한 번 더 거름)."""
    if table == "legacy_app_settings":
        k = row[names.index("key")] if "key" in names else ""
        v = row[names.index("value")] if "value" in names else ""
        k = str(k or "")
        return k.startswith(_SETTINGS_ALLOW) and not _SETTINGS_DENY.search(k) and not _SECRET_VALUE.search(str(v or ""))
    if table == "legacy_ai_prompts":
        return not any(isinstance(x, str) and _SECRET_VALUE.search(x) for x in row)
    return True


def _create_sql(meta, pg):
    ct = {"int": "BIGINT" if pg else "INTEGER", "real": "DOUBLE PRECISION" if pg else "REAL", "text": "TEXT"}
    pk = meta.get("pk") or []
    ident = bool(meta.get("identity")) and len(pk) == 1
    parts = []
    for name, typ in meta["cols"]:
        if ident and name == pk[0]:
            parts.append(f"{_q(name)} BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if pg
                         else f"{_q(name)} INTEGER PRIMARY KEY AUTOINCREMENT")
        else:
            parts.append(f"{_q(name)} {ct[typ]}")
    if pk and not ident:
        parts.append("PRIMARY KEY (" + ", ".join(_q(c) for c in pk) + ")")
    return f"CREATE TABLE {_q(meta['table'])} (" + ", ".join(parts) + ")"


def _import_one(path, meta, pg):
    table = meta["table"]
    names = [c[0] for c in meta["cols"]]
    types = [c[1] for c in meta["cols"]]
    conn = _history_conn()
    inserted = 0
    try:
        cur = conn.cursor()
        if not pg:
            conn.isolation_level = None          # 직접 BEGIN/COMMIT (SQLite 에서도 표 교체를 한 덩어리로)
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("BEGIN IMMEDIATE")
        cur.execute(f"DROP TABLE IF EXISTS {_q(table)}")
        cur.execute(_create_sql(meta, pg))
        ins = f"INSERT INTO {_q(table)} (" + ", ".join(_q(n) for n in names) + ") VALUES "
        batch, sha, seen, in_table = [], hashlib.sha256(), 0, False

        def flush():
            nonlocal inserted, batch
            if not batch:
                return
            if pg:
                from psycopg2.extras import execute_values
                execute_values(cur, ins + "%s", batch, page_size=BATCH)
            else:
                cur.executemany(ins + "(" + ",".join("?" * len(names)) + ")", batch)
            inserted += len(batch)
            batch = []

        for kind, obj in _iter_file(path):
            if kind == "ctl":
                if obj.get("table") == table:
                    in_table = True
                elif in_table and obj.get("end") == table:
                    if obj.get("sha256") != sha.hexdigest() or obj.get("rows") != seen:
                        raise ValueError("파일 내용 확인값이 달라졌어요")
                    break
                continue
            if not in_table:
                continue
            sha.update(obj)
            seen += 1
            row = json.loads(obj)
            if len(row) != len(names):
                raise ValueError("열 개수가 맞지 않는 행이 있어요")
            if not _keep_row(table, names, row):
                continue
            batch.append(_coerce(row, types))
            if len(batch) >= BATCH:
                flush()
        flush()
        for i, ix in enumerate(meta.get("indexes") or []):
            cur.execute(f"CREATE {'UNIQUE ' if ix.get('unique') else ''}INDEX {_q('ix_' + table + '_' + str(i))} ON {_q(table)} ("
                        + ", ".join(_q(c) for c in ix["cols"]) + ")")
        pk = meta.get("pk") or []
        if pg and meta.get("identity") and len(pk) == 1:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', '{pk[0]}'), COALESCE(MAX({_q(pk[0])}), 1), MAX({_q(pk[0])}) IS NOT NULL) FROM {_q(table)}")
        cur.execute(f"SELECT COUNT(*) FROM {_q(table)}")
        after = int(cur.fetchone()[0])
        if after != inserted:
            raise ValueError(f"넣은 행 수({inserted:,})와 저장된 행 수({after:,})가 달라요")
        if pg:
            conn.commit()
        else:
            cur.execute("COMMIT")
        return {"table": table, "status": "ok", "rows_in_file": meta["counted"], "rows": after,
                "msg": "" if after == meta["counted"] else f"안전하지 않은 항목 {meta['counted'] - after}행은 제외"}
    except Exception as e:
        try:
            if pg:
                conn.rollback()
            else:
                cur.execute("ROLLBACK")
        except Exception:
            pass
        return {"table": table, "status": "error", "rows_in_file": meta["counted"], "rows": 0,
                "msg": f"{type(e).__name__}: {str(e)[:150]} — 이 표는 원래대로 남아 있어요"}
    finally:
        conn.close()


def _import_job(jid, path, metas):
    job = C._AIJOBS[jid]
    results = []
    try:
        for m in metas:
            r = _import_one(path, m, bool(C._USE_PG))
            results.append(r)
            if r["status"] != "ok":
                job["errors"].append(f"{r['table']}: {r['msg']}")
            job["done"] += 1
            job["result"] = {"tables": list(results)}
        job["status"] = "done" if all(r["status"] == "ok" for r in results) else "error"
        ok_n = sum(1 for r in results if r["status"] == "ok")
        job["msg"] = f"{ok_n}/{len(results)}개 표 완료"
        _alog("data_import_done", job["msg"], ip="server", ua="background job")
    except Exception as e:
        job["errors"].append(f"{type(e).__name__}: {str(e)[:150]}")
        job["status"] = "error"


# ── 관리자 화면 탭 ──
JS = r"""
var IM={st:null};
function imLoad(p){p.innerHTML='';p.textContent='불러오는 중…';
 api('/admin/api/import/state').then(function(d){IM.st=d;imDraw(p,d)})}
function imDraw(p,d){p.innerHTML='';
 var a=el('div','c');a.appendChild(el('b',null,'📦 원본 프로그램 데이터 가져오기'));
 a.appendChild(el('p','note','① 내 PC에서 내보내기 도구를 한 번 실행합니다(원본 DB는 읽기만 하며 API 키·비밀번호는 담기지 않습니다). ② 만들어진 파일(stock_export_…jsonl.gz)을 아래에서 올립니다. ③ 가져올 표를 고르고 [가져오기]를 누릅니다. 이미 데이터가 있는 표는 교체 여부를 한 번 더 물어봅니다.'));
 if(d.tool){var l=el('a',null,'⬇ 내보내기 도구 받기 (export_for_web.py)');l.href='/admin/tools/export_for_web.py';l.style.cssText='display:inline-block;margin:4px 0;color:#2563eb';a.appendChild(l)}
 else a.appendChild(el('p','note bad','내보내기 도구 파일이 서버에 없어요(export_for_web.py 업로드 확인).'));
 var f=el('input');f.type='file';f.accept='.gz,.jsonl.gz';var r=el('div','bar');r.appendChild(f);
 var up=bt('올려서 검사','bt',function(){if(!f.files.length){toast('파일을 고르세요');return}
  var fd=new FormData();fd.append('f',f.files[0]);up.disabled=true;up.textContent='올리는 중…';
  fetch('/admin/api/import/upload',{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':CSRF},body:fd}).then(function(x){if(x.status===401){location.replace('/admin');throw 0}return x.json()}).then(function(j){
   up.disabled=false;up.textContent='올려서 검사';if(j.error){toast(j.error);return}imLoad(p)}).catch(function(){up.disabled=false;up.textContent='올려서 검사';toast('올리지 못했어요')})});
 r.appendChild(up);a.appendChild(r);
 a.appendChild(el('p','note','파일 크기 최대 '+d.max_mb+'MB · 올린 파일은 서버 임시 공간에만 두고 2시간 뒤 지웁니다.'));
 p.appendChild(a);
 if(d.staged){imPreview(p,d)}
 var k=el('div','c');k.id='imcur';p.appendChild(k);imCur(d)}
function imCur(d){var k=$('imcur');k.innerHTML='';k.appendChild(el('b',null,'지금 웹 DB에 있는 가져오기 대상 표'));
 var t=el('table'),h=el('tr');['표','종류','현재 행 수'].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 d.tables.forEach(function(x){var tr=el('tr');tr.appendChild(el('td',null,x.label+' ('+x.table+')'));tr.appendChild(el('td',null,x.cat_label));tr.appendChild(el('td',null,x.existing==null?'없음':x.existing.toLocaleString()));t.appendChild(tr)});
 k.appendChild(t)}
function imPreview(p,d){var s=d.staged,c=el('div','c');
 c.appendChild(el('b',null,'올린 파일: '+d.staged_name));
 c.appendChild(el('p','note','내보낸 시각 '+(s.created||'?')+' · 파일 무결성(해시) 검사 통과 · 표 '+s.tables.length+'개'));
 var t=el('table'),h=el('tr');['가져오기','표','종류','파일 행 수','웹 DB 현재','비고'].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 var boxes=[];
 s.tables.forEach(function(x){var tr=el('tr'),td=el('td'),cb=el('input');cb.type='checkbox';cb.disabled=!x.allowed;cb.checked=x.allowed&&x.category!=='personal'&&!(x.existing>0);td.appendChild(cb);tr.appendChild(td);boxes.push([x,cb]);
  tr.appendChild(el('td',null,x.label+' ('+x.table+')'));tr.appendChild(el('td',x.category==='personal'?'bad':'',x.cat_label||'-'));
  tr.appendChild(el('td',null,x.rows.toLocaleString()));tr.appendChild(el('td',null,x.existing==null?'-':x.existing.toLocaleString()));
  tr.appendChild(el('td',x.existing>0||x.category==='personal'||!x.allowed?'bad':'',x.problem||(x.existing>0?'이미 데이터가 있어요 — 체크하면 교체':(x.category==='personal'?'개인 기록: 꼭 필요할 때만':''))));t.appendChild(tr)});
 c.appendChild(t);var bar=el('div','bar'),out=el('div','note');
 var go=bt('선택한 표 가져오기','bt',function(){var tabs=[],ov=[],pers=false,lines=[];
  boxes.forEach(function(b){if(b[1].checked){tabs.push(b[0].table);if(b[0].existing>0){ov.push(b[0].table);lines.push(b[0].label+' '+b[0].existing.toLocaleString()+'행 → 교체')}if(b[0].category==='personal')pers=true}});
  if(!tabs.length){toast('가져올 표를 고르세요');return}
  if(ov.length&&!confirm('이미 있는 데이터를 새 파일 내용으로 교체합니다:\n'+lines.join('\n')+'\n\n계속할까요?'))return;
  if(pers&&!confirm('개인 기록(관심종목·장부·예측 등)을 웹 DB에 저장합니다. 공개 화면에는 나오지 않지만 서버 DB에 남습니다. 계속할까요?'))return;
  go.disabled=true;apiJ('/admin/api/import/run',{id:d.staged_id,tables:tabs,overwrite:ov,include_personal:pers}).then(function(j){
   if(j.error){go.disabled=false;toast(j.error);return}
   out.textContent='가져오는 중…';poll(j.job,function(q){out.textContent='가져오는 중… '+q.done+'/'+q.total+' 표'},function(q){go.disabled=false;imResult(out,q);api('/admin/api/import/state').then(function(z){imCur(z)})})})});
 bar.appendChild(go);bar.appendChild(bt('올린 파일 지우기','bt3',function(){apiJ('/admin/api/import/discard',{}).then(function(){imLoad(p)})}));
 c.appendChild(bar);c.appendChild(out);p.appendChild(c)}
function imResult(out,q){out.innerHTML='';var res=(q.result&&q.result.tables)||[];
 res.forEach(function(r){var d=el('div',r.status==='ok'?'good':'bad',(r.status==='ok'?'✅ ':'❌ ')+r.table+' — '+(r.status==='ok'?r.rows.toLocaleString()+'행 저장 확인'+(r.msg?' ('+r.msg+')':''):r.msg));out.appendChild(d)});
 if(!res.length)out.textContent=(q.errors||[]).join(' / ')||'결과 없음'}
"""


def register():
    C.register_admin_tab("im", "📦 데이터 가져오기", JS, "imLoad")
    return bp
