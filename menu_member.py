"""👤 회원 — 이메일을 아이디로 쓰는 회원가입·로그인 (v146)

동작 요약
  · 가입: ① 이메일 입력 → 6자리 인증번호 메일 → ② 번호·비밀번호·개인정보 동의 → 가입 완료(바로 로그인).
          관리자 화면 [👤 회원]에서 '이메일 인증'을 끄면 번호 없이 가입된다(가짜 메일이 섞일 수 있음).
  · 비밀번호는 PBKDF2-SHA256(24만 회) + 회원별 소금으로만 저장한다(원문 저장·메일 발송 없음). 분실 시 메일 인증번호로 새로 정한다.
  · 로그인 유지: 무작위 세션 번호(DB에는 해시만), 쿠키는 HttpOnly·SameSite=Lax·https 에서 Secure, 30일(쓸 때마다 연장).
  · 보호 장치: 인증메일 요청 제한(같은 메일 60초·시간당 5회, 같은 IP 시간당 10회, 하루 전체 상한), 로그인 실패 제한(같은 메일 15분 5회·같은 IP 20회),
              모든 변경 요청은 같은 출처(Origin)만 허용, 계정 존재 여부를 알려주지 않는 응답, 탈퇴 시 모든 정보 삭제.
  · 회원 단계(관리자 [메뉴 관리]에서 만든 단계)는 이 모듈이 viewer_level() 로 본체에 알려주며, 메뉴 노출이 그대로 따른다.
  · SNS 로그인(네이버·구글·카카오): OAuth 2.0 인가코드 방식. 키는 코드에 넣지 않고 Render 환경변수로만 받는다
      NAVER_CLIENT_ID/NAVER_CLIENT_SECRET · GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET · KAKAO_REST_API_KEY(+KAKAO_CLIENT_SECRET 선택).
      제공자가 '인증된 이메일'을 주면 그 이메일이 아이디가 되고(같은 이메일 회원이 있으면 한 계정으로 연결), 카카오처럼 이메일을 못 받으면
      <제공자>_<번호>@sns.local 형태의 내부 아이디로 만든다(이 주소로는 메일을 보내지 않는다).
  · 관리자 화면 [👤 회원]: 가입 허용·이메일 인증·기본 단계 설정, 회원 검색, 단계 변경, 차단/해제, 강제 로그아웃, 삭제.
"""
import os, re, time, json, hmac, hashlib, secrets
import urllib.request, urllib.parse, urllib.error
from flask import Blueprint, jsonify, request, g, has_request_context, redirect
from menu_ctx import C
import menu_ui as U

bp = Blueprint("member", __name__)

_CORE_FUNCS = ("_admin_json", "_admin_deny", "_alog", "_dbx", "_dbrows", "_json_body", "_ensure_v135_tables", "_same_origin", "_client_ip",
               "_send_mail", "_mask_email", "setting_get", "setting_set", "member_levels")
for _n in _CORE_FUNCS:
    globals()[_n] = (lambda n: (lambda *a, **k: getattr(C, n)(*a, **k)))(_n)

COOKIE = "mini_m"
SESSION_SEC = 30 * 24 * 3600
PW_ITER = 240000
CODE_TTL = 600
CODE_TRIES = 5
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
DAILY_MAIL_CAP_DEFAULT = 80          # Resend 무료(하루 100통) 안에서 인증메일에 쓸 상한


# ───────────────────────── 표 ─────────────────────────
def _ensure_tables(c, pg):
    c.execute("""CREATE TABLE IF NOT EXISTS members(
        email TEXT PRIMARY KEY, salt TEXT NOT NULL, pw_hash TEXT NOT NULL, level TEXT NOT NULL DEFAULT '1',
        status TEXT NOT NULL DEFAULT 'active', created_at BIGINT NOT NULL, last_login BIGINT NOT NULL DEFAULT 0,
        agreed_at BIGINT NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0, ip TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS member_codes(
        cid TEXT PRIMARY KEY, email TEXT NOT NULL, purpose TEXT NOT NULL, salt TEXT NOT NULL, code_hash TEXT NOT NULL,
        created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0, ip TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_member_codes_em ON member_codes(email, created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS member_sessions(
        sid_hash TEXT PRIMARY KEY, email TEXT NOT NULL, created_at BIGINT NOT NULL, last_seen BIGINT NOT NULL, expires_at BIGINT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_member_sess_em ON member_sessions(email)")
    pk = "SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.execute(f"CREATE TABLE IF NOT EXISTS member_log(id {pk}, at BIGINT NOT NULL, event TEXT NOT NULL, ip TEXT, email TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_member_log_ev ON member_log(event, at)")
    c.execute("""CREATE TABLE IF NOT EXISTS member_social(
        provider TEXT NOT NULL, pid TEXT NOT NULL, email TEXT NOT NULL, created_at BIGINT NOT NULL, PRIMARY KEY(provider, pid))""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_member_social_em ON member_social(email)")
    c.execute("""CREATE TABLE IF NOT EXISTS member_oauth_state(
        state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, next_url TEXT NOT NULL, created_at BIGINT NOT NULL)""")


def _q(sql, args=(), fetch=False):
    _ensure_v135_tables()
    return C._dbx(sql, args, fetch=fetch)


def _mlog(event, email=""):
    try:
        _q("INSERT INTO member_log(at,event,ip,email) VALUES(?,?,?,?)", (int(time.time()), event, _client_ip(), (email or "")[:120]))
    except Exception as e:
        print(f"[회원] 기록 실패(무시): {e}")


def _count(event, since, ip=None, email=None):
    sql, a = "SELECT COUNT(*) FROM member_log WHERE event=? AND at>=?", [event, int(since)]
    if ip is not None:
        sql += " AND ip=?"; a.append(ip)
    if email is not None:
        sql += " AND email=?"; a.append(email)
    return int(_q(sql, a, fetch=True)[0][0])


# ───────────────────────── 설정 ─────────────────────────
def _on():
    return setting_get("member_on", "1") == "1"


def _signup_open():
    return _on() and setting_get("member_signup", "1") == "1"


def _verify_on():
    return setting_get("member_verify", "1") == "1"


def _default_level():
    ids = [x["id"] for x in member_levels()]
    v = setting_get("member_default_level", "")
    return v if v in ids else (ids[0] if ids else "1")


def _daily_cap():
    try:
        return max(0, min(5000, int(setting_get("member_mail_cap", str(DAILY_MAIL_CAP_DEFAULT)))))
    except Exception:
        return DAILY_MAIL_CAP_DEFAULT


# ───────────────────────── 비밀번호·코드 ─────────────────────────
def _hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), PW_ITER).hex()


def _pw_problem(pw, email=""):
    if not isinstance(pw, str) or len(pw) < 8:
        return "비밀번호는 8자 이상으로 정해 주세요."
    if len(pw) > 64:
        return "비밀번호는 64자 이하로 정해 주세요."
    if email and pw.lower() == email.lower():
        return "비밀번호를 이메일과 다르게 정해 주세요."
    kinds = sum(bool(re.search(p, pw)) for p in (r"[A-Za-z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if kinds < 2:
        return "비밀번호에 영문·숫자·기호 중 2가지 이상을 섞어 주세요."
    if len(set(pw)) < 4:
        return "너무 단순한 비밀번호예요. 다른 글자를 섞어 주세요."
    return ""


def _norm_email(v):
    e = str(v or "").strip().lower()
    return e if (len(e) <= 120 and EMAIL_RE.match(e)) else ""


def _code_hash(salt, code):
    return hashlib.sha256((salt + ":" + code).encode("utf-8")).hexdigest()


def _code_ok(email, purpose, code, consume=True):
    """입력한 인증번호가 맞는가. 최신 미사용 코드 하나만 보고, 틀리면 시도 횟수를 올린다(5번 틀리면 폐기)."""
    code = re.sub(r"\D", "", str(code or ""))
    if len(code) != 6:
        return False
    rows = _q("SELECT cid,salt,code_hash,expires_at,attempts FROM member_codes WHERE email=? AND purpose=? AND used=0 ORDER BY created_at DESC LIMIT 1",
              (email, purpose), fetch=True)
    if not rows:
        return False
    cid, salt, ch, exp, tries = rows[0][0], rows[0][1], rows[0][2], int(rows[0][3]), int(rows[0][4])
    if time.time() > exp or tries >= CODE_TRIES:
        return False
    if not hmac.compare_digest(ch, _code_hash(salt, code)):
        _q("UPDATE member_codes SET attempts=attempts+1 WHERE cid=?", (cid,))
        return False
    if consume:
        _q("UPDATE member_codes SET used=1 WHERE cid=?", (cid,))
    return True


# ───────────────────────── 세션 ─────────────────────────
def _new_session(email):
    sid = secrets.token_urlsafe(32)
    now = int(time.time())
    _q("DELETE FROM member_sessions WHERE expires_at<?", (now,))
    _q("INSERT INTO member_sessions(sid_hash,email,created_at,last_seen,expires_at) VALUES(?,?,?,?,?)", (C._sha(sid), email, now, now, now + SESSION_SEC))
    # 한 계정이 오래된 기기 세션을 무한히 쌓지 않도록 최근 8개만 남긴다
    old = _q("SELECT sid_hash FROM member_sessions WHERE email=? ORDER BY created_at DESC", (email,), fetch=True) or []
    for r in old[8:]:
        _q("DELETE FROM member_sessions WHERE sid_hash=?", (r[0],))
    return sid


def _with_cookie(resp, sid):
    resp.set_cookie(COOKIE, sid, max_age=SESSION_SEC, httponly=True, samesite="Lax", secure=bool(C._WEB_MODE), path="/")
    return resp


def _clear_cookie(resp):
    resp.delete_cookie(COOKIE, path="/")
    return resp


def current_member():
    """지금 요청의 로그인 회원 {'email','level','status','created_at'} 또는 None(요청당 한 번만 확인)."""
    if not has_request_context():
        return None
    if g.get("_mem_done"):
        return g.get("_mem")
    g._mem_done = True
    g._mem = None
    tok = request.cookies.get(COOKIE, "")
    if not tok or len(tok) > 100 or not _on():
        return None
    try:
        now = int(time.time())
        sh = C._sha(tok)
        rows = _q("SELECT s.email, s.last_seen, s.expires_at, m.level, m.status, m.created_at FROM member_sessions s JOIN members m ON m.email=s.email WHERE s.sid_hash=?",
                  (sh,), fetch=True)
        if not rows:
            return None
        email, last_seen, exp, level, status, created = rows[0][0], int(rows[0][1]), int(rows[0][2]), rows[0][3], rows[0][4], int(rows[0][5])
        if now > exp or status != "active":
            _q("DELETE FROM member_sessions WHERE sid_hash=?", (sh,))
            return None
        if now - last_seen > 3600:
            _q("UPDATE member_sessions SET last_seen=?, expires_at=? WHERE sid_hash=?", (now, now + SESSION_SEC, sh))
        ids = [x["id"] for x in member_levels()]
        if level not in ids:                      # 관리자가 그 단계를 지웠다면 가장 낮은 단계로 본다
            level = ids[0] if ids else "1"
        g._mem = {"email": email, "level": level, "status": status, "created_at": created}
    except Exception as e:
        print(f"[회원] 세션 확인 실패: {e}")
    return g.get("_mem")


def _viewer_level_hook():
    m = current_member()
    return m["level"] if m else None


# ───────────────────────── 공통 응답·검사 ─────────────────────────
def _out(obj, code=200):
    resp = jsonify(obj)
    resp.status_code = code
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _guard():
    """회원 요청 공통 검사 → 통과하면 None, 아니면 응답."""
    if not _on():
        return _out({"error": "지금은 회원 기능을 쓰지 않아요."}, 404)
    if not _same_origin():
        return _out({"error": "잘못된 요청이에요(다른 사이트에서 보낸 요청)."}, 403)
    return None


def _level_name(lid):
    for x in member_levels():
        if x["id"] == lid:
            return x["name"]
    return ""


def _ymd(ts):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + 9 * 3600)) if ts else "-"
    except Exception:
        return "-"


def _me_json():
    m = current_member()
    out = {"on": _on(), "signup": _signup_open(), "verify": _verify_on(), "logged": bool(m), "social": _social_map()}
    if m:
        em = m["email"]
        has_pw = (_q("SELECT pw_hash FROM members WHERE email=?", (em,), fetch=True) or [["!"]])[0][0] != "!"
        prov = [r[0] for r in (_q("SELECT provider FROM member_social WHERE email=? ORDER BY created_at", (em,), fetch=True) or [])]
        internal = em.endswith(SNS_DOMAIN)
        out.update({"email": "" if internal else em, "short": ("SNS 회원" if internal else _mask_email(em)), "level": m["level"], "level_name": _level_name(m["level"]), "since": _ymd(m["created_at"]),
                    "has_pw": has_pw, "providers": [PROVIDERS[x]["label"] for x in prov if x in PROVIDERS], "internal": internal})
    return out


# ───────────────────────── 공개 API ─────────────────────────
@bp.route("/member/api/me")
def api_me():
    if not _on():
        return _out({"on": False, "signup": False, "logged": False})
    return _out(_me_json())


@bp.route("/member/api/code", methods=["POST"])
def api_code():
    """인증번호 메일 보내기. purpose = signup(가입) | reset(비밀번호 다시 정하기). 계정이 있는지 없는지는 응답으로 알려주지 않는다."""
    deny = _guard()
    if deny:
        return deny
    d = _json_body()
    email = _norm_email(d.get("email"))
    purpose = d.get("purpose")
    if purpose not in ("signup", "reset") or not email:
        return _out({"error": "이메일 주소를 올바르게 입력해 주세요."}, 400)
    if email.endswith(SNS_DOMAIN):
        return _out({"error": "이 주소는 쓸 수 없어요. 다른 이메일을 입력해 주세요."}, 400)
    if purpose == "signup" and not _signup_open():
        return _out({"error": "지금은 새 회원가입을 받지 않아요."}, 403)
    if purpose == "signup" and not _verify_on():
        return _out({"error": "이메일 인증이 꺼져 있어요. 인증 없이 바로 가입해 주세요."}, 400)
    now = int(time.time())
    ip = _client_ip()
    last = _q("SELECT MAX(created_at) FROM member_codes WHERE email=?", (email,), fetch=True)[0][0]
    if last and now - int(last) < 60:
        return _out({"error": f"인증번호는 60초에 한 번만 받을 수 있어요. {60 - (now - int(last))}초 뒤에 다시 눌러 주세요."}, 429)
    if int(_q("SELECT COUNT(*) FROM member_codes WHERE email=? AND created_at>=?", (email, now - 3600), fetch=True)[0][0]) >= 5:
        return _out({"error": "이 메일로 보낼 수 있는 인증번호 횟수(1시간 5회)를 넘었어요. 잠시 후 다시 시도해 주세요."}, 429)
    if _count("code_req", now - 3600, ip=ip) >= 10:
        return _out({"error": "이 접속 환경에서 인증번호를 너무 많이 요청했어요. 1시간 뒤에 다시 시도해 주세요."}, 429)
    if int(_q("SELECT COUNT(*) FROM member_codes WHERE created_at>=?", (now - 86400,), fetch=True)[0][0]) >= _daily_cap():
        return _out({"error": "오늘 보낼 수 있는 인증 메일 수를 모두 썼어요. 내일 다시 시도해 주세요."}, 429)
    _mlog("code_req", email)
    exists = bool(_q("SELECT 1 FROM members WHERE email=?", (email,), fetch=True))
    if purpose == "reset" and not exists:
        return _out({"ok": True, "ttl": CODE_TTL})         # 계정이 없어도 같은 응답(가입 여부 노출 방지)
    if purpose == "signup" and exists:
        subject, text = "[종목분석 미니] 이미 가입된 이메일이에요", (
            "이 이메일은 이미 종목분석 미니에 가입되어 있어요.\n로그인 화면에서 이메일과 비밀번호로 로그인하시고, 비밀번호가 기억나지 않으면 [비밀번호 찾기]를 눌러 주세요.\n"
            "본인이 요청하지 않았다면 이 메일은 무시하셔도 됩니다.")
    else:
        code = "%06d" % secrets.randbelow(1000000)
        salt = secrets.token_hex(8)
        _q("INSERT INTO member_codes(cid,email,purpose,salt,code_hash,created_at,expires_at,attempts,used,ip) VALUES(?,?,?,?,?,?,?,0,0,?)",
           (secrets.token_hex(12), email, purpose, salt, _code_hash(salt, code), now, now + CODE_TTL, ip))
        what = "회원가입" if purpose == "signup" else "비밀번호 다시 정하기"
        subject = f"[종목분석 미니] {what} 인증번호 {code}"
        text = (f"종목분석 미니 {what} 인증번호입니다.\n\n    {code}\n\n10분 안에 입력해 주세요. 5번 틀리면 새 번호를 받아야 해요.\n"
                "본인이 요청하지 않았다면 이 메일은 무시하셔도 됩니다(번호를 알려주지 않으면 아무 일도 일어나지 않아요).")
    try:
        _send_mail([email], subject, text)
    except Exception as e:
        _alog("member_mail_fail", str(e)[:150])
        why = str(e)
        if why == "mail_not_configured":
            msg = "메일 발송이 아직 설정되지 않았어요. 운영자에게 알려 주세요."
        elif "403" in why or "422" in why:
            msg = "인증 메일을 보내지 못했어요. 운영자가 메일 발송 도메인 설정을 마쳐야 다른 사람에게도 메일을 보낼 수 있어요."
        else:
            msg = "인증 메일을 보내지 못했어요. 잠시 후 다시 시도해 주세요."
        return _out({"error": msg}, 502)
    return _out({"ok": True, "ttl": CODE_TTL})


@bp.route("/member/api/signup", methods=["POST"])
def api_signup():
    deny = _guard()
    if deny:
        return deny
    if not _signup_open():
        return _out({"error": "지금은 새 회원가입을 받지 않아요."}, 403)
    d = _json_body()
    email = _norm_email(d.get("email"))
    pw = d.get("password")
    if not email or email.endswith(SNS_DOMAIN):
        return _out({"error": "이메일 주소를 올바르게 입력해 주세요."}, 400)
    if d.get("agree") is not True:
        return _out({"error": "개인정보 수집·이용에 동의해 주세요."}, 400)
    bad = _pw_problem(pw, email)
    if bad:
        return _out({"error": bad}, 400)
    if _count("signup_try", int(time.time()) - 3600, ip=_client_ip()) >= 20:
        return _out({"error": "시도가 너무 많아요. 1시간 뒤에 다시 해 주세요."}, 429)
    _mlog("signup_try", email)
    if _verify_on():
        if not _code_ok(email, "signup", d.get("code")):
            return _out({"error": "인증번호가 맞지 않거나 만료됐어요. 번호를 다시 확인하거나 새로 받아 주세요."}, 400)
    if _q("SELECT 1 FROM members WHERE email=?", (email,), fetch=True):
        return _out({"error": "이미 가입된 이메일이에요. 로그인해 주세요."}, 409)
    salt = secrets.token_hex(16)
    now = int(time.time())
    try:
        _q("INSERT INTO members(email,salt,pw_hash,level,status,created_at,last_login,agreed_at,verified,ip) VALUES(?,?,?,?,?,?,?,?,?,?)",
           (email, salt, _hash_pw(pw, salt), _default_level(), "active", now, now, now, 1 if _verify_on() else 0, _client_ip()))
    except Exception:
        return _out({"error": "이미 가입된 이메일이에요. 로그인해 주세요."}, 409)
    _alog("member_signup", C._mask_email(email))
    sid = _new_session(email)
    g._mem_done = False
    resp = _out({"ok": True})
    return _with_cookie(resp, sid)


_DUMMY_SALT = "00" * 16


@bp.route("/member/api/login", methods=["POST"])
def api_login():
    deny = _guard()
    if deny:
        return deny
    d = _json_body()
    email = _norm_email(d.get("email"))
    pw = d.get("password")
    now = int(time.time())
    ip = _client_ip()
    if not email or not isinstance(pw, str) or not pw or len(pw) > 200:
        return _out({"error": "이메일과 비밀번호를 입력해 주세요."}, 400)
    if _count("login_fail", now - 900, email=email) >= 5 or _count("login_fail", now - 900, ip=ip) >= 20:
        return _out({"error": "로그인 실패가 많아 15분 동안 잠겼어요. 잠시 후 다시 시도하거나 [비밀번호 찾기]를 이용해 주세요."}, 429)
    rows = _q("SELECT salt,pw_hash,status FROM members WHERE email=?", (email,), fetch=True)
    salt, ph, status = (rows[0][0], rows[0][1], rows[0][2]) if rows else (_DUMMY_SALT, "x", "none")
    ok = hmac.compare_digest(_hash_pw(pw, salt), ph) if rows else (_hash_pw(pw, salt) == "")
    if not rows or not ok:
        _mlog("login_fail", email)
        return _out({"error": "이메일 또는 비밀번호가 맞지 않아요."}, 401)
    if status != "active":
        return _out({"error": "이용이 제한된 계정이에요. 문의는 제작자 블로그로 남겨 주세요."}, 403)
    _q("UPDATE members SET last_login=? WHERE email=?", (now, email))
    sid = _new_session(email)
    return _with_cookie(_out({"ok": True}), sid)


@bp.route("/member/api/logout", methods=["POST"])
def api_logout():
    deny = _guard()
    if deny:
        return deny
    tok = request.cookies.get(COOKIE, "")
    if tok:
        _q("DELETE FROM member_sessions WHERE sid_hash=?", (C._sha(tok),))
    return _clear_cookie(_out({"ok": True}))


@bp.route("/member/api/reset", methods=["POST"])
def api_reset():
    """인증번호로 비밀번호 다시 정하기. 성공하면 모든 기기에서 로그아웃시키고 새로 로그인된다."""
    deny = _guard()
    if deny:
        return deny
    d = _json_body()
    email = _norm_email(d.get("email"))
    pw = d.get("password")
    if not email:
        return _out({"error": "이메일 주소를 올바르게 입력해 주세요."}, 400)
    bad = _pw_problem(pw, email)
    if bad:
        return _out({"error": bad}, 400)
    if _count("reset_try", int(time.time()) - 3600, ip=_client_ip()) >= 20:
        return _out({"error": "시도가 너무 많아요. 1시간 뒤에 다시 해 주세요."}, 429)
    _mlog("reset_try", email)
    rows = _q("SELECT status FROM members WHERE email=?", (email,), fetch=True)
    if not rows or not _code_ok(email, "reset", d.get("code")):
        return _out({"error": "인증번호가 맞지 않거나 만료됐어요. 번호를 다시 확인하거나 새로 받아 주세요."}, 400)
    if rows[0][0] != "active":
        return _out({"error": "이용이 제한된 계정이에요."}, 403)
    salt = secrets.token_hex(16)
    _q("UPDATE members SET salt=?, pw_hash=? WHERE email=?", (salt, _hash_pw(pw, salt), email))
    _q("DELETE FROM member_sessions WHERE email=?", (email,))
    _alog("member_reset", C._mask_email(email))
    sid = _new_session(email)
    return _with_cookie(_out({"ok": True}), sid)


@bp.route("/member/api/password", methods=["POST"])
def api_password():
    deny = _guard()
    if deny:
        return deny
    m = current_member()
    if not m:
        return _out({"error": "로그인이 필요해요."}, 401)
    d = _json_body()
    old, new = d.get("old"), d.get("password")
    rows = _q("SELECT salt,pw_hash FROM members WHERE email=?", (m["email"],), fetch=True)
    if rows and rows[0][1] == "!":
        return _out({"error": "SNS로 가입한 계정은 비밀번호가 없어요. 로그인 화면의 [비밀번호를 잊으셨나요?]로 비밀번호를 새로 정할 수 있어요."}, 400)
    if not rows or not isinstance(old, str) or not hmac.compare_digest(_hash_pw(old, rows[0][0]), rows[0][1]):
        return _out({"error": "지금 비밀번호가 맞지 않아요."}, 400)
    bad = _pw_problem(new, m["email"])
    if bad:
        return _out({"error": bad}, 400)
    salt = secrets.token_hex(16)
    _q("UPDATE members SET salt=?, pw_hash=? WHERE email=?", (salt, _hash_pw(new, salt), m["email"]))
    keep = C._sha(request.cookies.get(COOKIE, ""))
    _q("DELETE FROM member_sessions WHERE email=? AND sid_hash<>?", (m["email"], keep))       # 다른 기기는 로그아웃
    return _out({"ok": True})


@bp.route("/member/api/withdraw", methods=["POST"])
def api_withdraw():
    deny = _guard()
    if deny:
        return deny
    m = current_member()
    if not m:
        return _out({"error": "로그인이 필요해요."}, 401)
    d = _json_body()
    rows = _q("SELECT salt,pw_hash FROM members WHERE email=?", (m["email"],), fetch=True)
    pw = d.get("password")
    if rows and rows[0][1] == "!":
        if d.get("confirm") != "탈퇴":                                      # 비밀번호 없는 SNS 계정은 '탈퇴'를 직접 입력해 확인
            return _out({"error": "확인 칸에 ‘탈퇴’ 두 글자를 입력해 주세요."}, 400)
    elif not rows or not isinstance(pw, str) or not hmac.compare_digest(_hash_pw(pw, rows[0][0]), rows[0][1]):
        return _out({"error": "비밀번호가 맞지 않아요."}, 400)
    _delete_member(m["email"])
    _alog("member_withdraw", C._mask_email(m["email"]))
    return _clear_cookie(_out({"ok": True}))


def _delete_member(email):
    for t in ("member_sessions", "member_codes", "member_social"):
        _q(f"DELETE FROM {t} WHERE email=?", (email,))
    _q("DELETE FROM member_log WHERE email=?", (email,))
    _q("DELETE FROM members WHERE email=?", (email,))


# ───────────────────────── SNS 로그인 (네이버·구글·카카오) ─────────────────────────
PROVIDERS = {
    "naver": {"label": "네이버", "env": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"), "scope": "",
              "auth": "https://nid.naver.com/oauth2.0/authorize", "token": "https://nid.naver.com/oauth2.0/token", "me": "https://openapi.naver.com/v1/nid/me"},
    "google": {"label": "구글", "env": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"), "scope": "openid email",
               "auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token", "me": "https://openidconnect.googleapis.com/v1/userinfo"},
    "kakao": {"label": "카카오", "env": ("KAKAO_REST_API_KEY", "KAKAO_CLIENT_SECRET"), "scope": "",
              "auth": "https://kauth.kakao.com/oauth/authorize", "token": "https://kauth.kakao.com/oauth/token", "me": "https://kapi.kakao.com/v2/user/me"},
}
OAUTH_COOKIE = "mini_os"
OAUTH_TTL = 600
SNS_DOMAIN = "@sns.local"


def _creds(prov):
    """(client_id, client_secret). 카카오는 client secret 이 선택이라 id 만 있어도 켜진다."""
    ide, sece = PROVIDERS[prov]["env"]
    cid = os.environ.get(ide, "").strip()
    sec = os.environ.get(sece, "").strip()
    return cid, sec


def _configured(prov):
    cid, sec = _creds(prov)
    return bool(cid and (sec or prov == "kakao"))


def _social_map():
    return {k: _configured(k) for k in PROVIDERS}


def _base_url():
    b = os.environ.get("MEMBER_OAUTH_BASE_URL", "").strip().rstrip("/")
    if not b:
        b = request.host_url.rstrip("/")
        if C._WEB_MODE and b.startswith("http://"):
            b = "https://" + b[7:]
    return b


def _redirect_uri(prov):
    return f"{_base_url()}/member/oauth/{prov}/callback"


def _safe_next(n):
    n = str(n or "")
    return n if (n.startswith("/") and not n.startswith("//") and "\\" not in n and len(n) <= 300) else "/"


def _oauth_fetch(url, data=None, headers=None):
    """OAuth 서버 호출(표준 라이브러리). data 가 있으면 POST(form). → (상태코드, JSON 또는 None)."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=dict(headers or {}, **{"Accept": "application/json", "User-Agent": "stock-mini-oauth/1.0"}))
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=10, context=getattr(C, "_SSL_CTX", None)) as r:
            raw = r.read(300000)
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(300000), e.code
    try:
        return code, json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return code, None


def _fail_page(code):
    """로그인 화면으로 돌아가 한국어 안내를 띄운다(주소에는 오류 '코드'만 싣는다)."""
    resp = redirect(f"/member?sns_err={code}")
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    resp.headers["Cache-Control"] = "no-store"
    return resp


SNS_ERR = {
    "off": "지금은 SNS 로그인을 쓰지 않아요.", "cfg": "이 SNS 로그인은 아직 준비 중이에요(운영자 설정 필요).", "state": "로그인 요청이 만료됐거나 올바르지 않아요. 다시 시도해 주세요.",
    "denied": "SNS 로그인을 취소했어요.", "token": "SNS에서 로그인 정보를 받지 못했어요. 잠시 후 다시 시도해 주세요.", "noemail": "이메일 제공에 동의해야 가입할 수 있어요. 다시 시도하며 이메일 항목에 동의해 주세요.",
    "closed": "지금은 새 회원가입을 받지 않아요. 이미 가입한 회원만 로그인할 수 있어요.", "blocked": "이용이 제한된 계정이에요.", "many": "시도가 너무 많아요. 잠시 후 다시 해 주세요.", "fail": "SNS 로그인에 실패했어요. 잠시 후 다시 시도해 주세요.",
}


@bp.route("/member/oauth/<prov>/start")
def oauth_start(prov):
    if prov not in PROVIDERS:
        return "not found", 404
    if not _on():
        return _fail_page("off")
    if not _configured(prov):
        return _fail_page("cfg")
    ip = _client_ip()
    if _count("oauth_start", int(time.time()) - 600, ip=ip) >= 30:
        return _fail_page("many")
    _mlog("oauth_start")
    state = secrets.token_urlsafe(24)
    now = int(time.time())
    _q("DELETE FROM member_oauth_state WHERE created_at<?", (now - OAUTH_TTL,))
    _q("INSERT INTO member_oauth_state(state_hash,provider,next_url,created_at) VALUES(?,?,?,?)", (C._sha(state), prov, _safe_next(request.args.get("next")), now))
    cfg = PROVIDERS[prov]
    cid, _ = _creds(prov)
    q = {"response_type": "code", "client_id": cid, "redirect_uri": _redirect_uri(prov), "state": state}
    if cfg["scope"]:
        q["scope"] = cfg["scope"]
    if prov == "kakao" and os.environ.get("KAKAO_REQUEST_EMAIL", "") == "1":
        q["scope"] = "account_email"
    if prov == "google":
        q["prompt"] = "select_account"
    resp = redirect(cfg["auth"] + "?" + urllib.parse.urlencode(q))
    resp.set_cookie(OAUTH_COOKIE, state, max_age=OAUTH_TTL, httponly=True, samesite="Lax", secure=bool(C._WEB_MODE), path="/")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _profile(prov, code, state):
    """인가코드 → (제공자 회원번호, 이메일, 이메일 인증 여부). 실패하면 None."""
    cfg = PROVIDERS[prov]
    cid, sec = _creds(prov)
    data = {"grant_type": "authorization_code", "client_id": cid, "code": code, "redirect_uri": _redirect_uri(prov)}
    if sec:
        data["client_secret"] = sec
    if prov == "naver":
        data["state"] = state
    st, tj = _oauth_fetch(cfg["token"], data)
    tok = (tj or {}).get("access_token") if isinstance(tj, dict) else None
    if st != 200 or not tok or not isinstance(tok, str):
        print(f"[회원] {prov} 토큰 교환 실패 status={st}")
        return None
    st, me = _oauth_fetch(cfg["me"], None, {"Authorization": "Bearer " + tok})
    if st != 200 or not isinstance(me, dict):
        print(f"[회원] {prov} 프로필 조회 실패 status={st}")
        return None
    if prov == "naver":
        r = me.get("response") if isinstance(me.get("response"), dict) else {}
        return str(r.get("id") or ""), str(r.get("email") or ""), bool(r.get("email"))          # 네이버는 가입 때 확인된 주소만 준다
    if prov == "google":
        return str(me.get("sub") or ""), str(me.get("email") or ""), me.get("email_verified") in (True, "true")
    ka = me.get("kakao_account") if isinstance(me.get("kakao_account"), dict) else {}
    return str(me.get("id") or ""), str(ka.get("email") or ""), bool(ka.get("is_email_valid") and ka.get("is_email_verified"))


@bp.route("/member/oauth/<prov>/callback")
def oauth_callback(prov):
    if prov not in PROVIDERS:
        return "not found", 404
    if not _on():
        return _fail_page("off")
    if not _configured(prov):
        return _fail_page("cfg")
    state = request.args.get("state", "")
    ck = request.cookies.get(OAUTH_COOKIE, "")
    if not state or not ck or len(state) > 100 or not hmac.compare_digest(state, ck):
        return _fail_page("state")
    rows = _q("SELECT provider,next_url,created_at FROM member_oauth_state WHERE state_hash=?", (C._sha(state),), fetch=True)
    _q("DELETE FROM member_oauth_state WHERE state_hash=?", (C._sha(state),))              # 한 번만 쓸 수 있다
    if not rows or rows[0][0] != prov or int(time.time()) - int(rows[0][2]) > OAUTH_TTL:
        return _fail_page("state")
    nxt = _safe_next(rows[0][1])
    if request.args.get("error") or not request.args.get("code"):
        return _fail_page("denied")
    code = request.args.get("code", "")
    if len(code) > 2000:
        return _fail_page("fail")
    try:
        prof = _profile(prov, code, state)
    except Exception as e:
        print(f"[회원] {prov} 로그인 오류: {type(e).__name__}: {str(e)[:100]}")
        prof = None
    if not prof or not prof[0] or len(prof[0]) > 100:
        return _fail_page("token")
    pid, mail, verified = prof
    email = _norm_email(mail) if verified else ""
    now = int(time.time())
    row = _q("SELECT email FROM member_social WHERE provider=? AND pid=?", (prov, pid), fetch=True)
    if row:
        email = row[0][0]
    else:
        if not email:
            if prov != "kakao":
                return _fail_page("noemail")
            email = f"kakao_{re.sub(r'[^0-9A-Za-z]', '', pid)}{SNS_DOMAIN}"           # 카카오: 이메일 제공 권한이 없을 때의 내부 아이디
        existing = _q("SELECT status,verified FROM members WHERE email=?", (email,), fetch=True)
        if existing and not int(existing[0][1] or 0):
            # 이메일 인증 없이 가입된 계정(주인이 확인되지 않음)에 SNS(인증된 이메일)가 연결되면, 예전 비밀번호와 로그인을 모두 무효로 돌려 계정을 진짜 주인에게 넘긴다
            _q("UPDATE members SET pw_hash='!', verified=1 WHERE email=?", (email,))
            _q("DELETE FROM member_sessions WHERE email=?", (email,))
        if not existing:
            if not _signup_open():
                return _fail_page("closed")
            salt = secrets.token_hex(16)
            try:
                _q("INSERT INTO members(email,salt,pw_hash,level,status,created_at,last_login,agreed_at,verified,ip) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (email, salt, "!", _default_level(), "active", now, now, now, 1, _client_ip()))
            except Exception:
                pass
            _alog("member_signup_sns", f"{prov} {C._mask_email(email)}")
        try:
            _q("INSERT INTO member_social(provider,pid,email,created_at) VALUES(?,?,?,?)", (prov, pid, email, now))
        except Exception:
            pass                                                                            # 동시에 두 번 눌러 이미 연결됨
    st = _q("SELECT status FROM members WHERE email=?", (email,), fetch=True)
    if not st:
        return _fail_page("fail")
    if st[0][0] != "active":
        return _fail_page("blocked")
    _q("UPDATE members SET last_login=? WHERE email=?", (now, email))
    _mlog("oauth_login_" + prov, email)
    sid = _new_session(email)
    resp = redirect(nxt)
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    resp.headers["Cache-Control"] = "no-store"
    return _with_cookie(resp, sid)



# ───────────────────────── 화면 ─────────────────────────
PAGE_CSS = """
.mbBox{max-width:460px;margin:0 auto}.mbTabs{display:flex;gap:6px;margin:0 0 14px}.mbTabs button{flex:1;appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--ink2);border-radius:12px;padding:10px;font:inherit;font-weight:700;cursor:pointer}
.mbTabs button.on{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border-color:transparent}
.mbF{display:flex;flex-direction:column;gap:10px}.mbF label{font-weight:700;font-size:13.5px;display:flex;flex-direction:column;gap:5px}
.mbF input[type=email],.mbF input[type=password],.mbF input[type=text],.mbF input[type=tel]{border:1px solid var(--line);border-radius:12px;padding:11px 13px;font:inherit;background:var(--surface);color:var(--ink);width:100%;box-sizing:border-box}
.mbF input:focus{outline:2px solid var(--accent2);outline-offset:1px}
.mbRow{display:flex;gap:8px;align-items:stretch}.mbRow input{flex:1;min-width:0}
.mbMsg{font-size:13.5px;border-radius:10px;padding:9px 12px;display:none}.mbMsg.on{display:block}.mbMsg.bad{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca}.mbMsg.ok{background:#ecfdf5;color:#047857;border:1px solid #a7f3d0}
.mbHint{color:var(--ink3);font-size:12.5px;line-height:1.5}.mbAgree{flex-direction:row!important;align-items:flex-start;gap:8px!important;font-weight:500!important;font-size:13px!important}.mbAgree input{margin-top:3px}
.mbMe dl{display:grid;grid-template-columns:90px 1fr;gap:8px 12px;margin:0 0 16px}.mbMe dt{color:var(--ink3);font-size:13px}.mbMe dd{margin:0;font-weight:700;word-break:break-all}
.mbAct{display:flex;gap:8px;flex-wrap:wrap}.mbSub{margin-top:14px;padding-top:14px;border-top:1px dashed var(--line)}
.mbSns{margin-top:18px;padding-top:16px;border-top:1px dashed var(--line);display:flex;flex-direction:column;gap:8px}.mbSns h4{margin:0 0 2px;font-size:13px;color:var(--ink3);font-weight:700}
.mbSnsB{display:flex;align-items:center;justify-content:center;gap:8px;border-radius:12px;padding:12px;font:inherit;font-weight:800;text-decoration:none;border:1px solid transparent;cursor:pointer;box-sizing:border-box}
.mbSnsB.naver{background:#03c75a;color:#fff}.mbSnsB.kakao{background:#fee500;color:#191600}.mbSnsB.google{background:#fff;color:#1f2937;border-color:#d1d5db}
.mbSnsB.off{opacity:.45;pointer-events:none;filter:grayscale(.6)}.mbSnsB i{font-style:normal;font-weight:900;font-size:15px;width:20px;text-align:center}
"""

PAGE_JS = r"""
(function(){
var S={me:null,view:'login',codeSent:false,cd:0,timer:null};
var NEXT=(function(){try{var n=new URLSearchParams(location.search).get('next')||'';return(n.charAt(0)==='/'&&n.charAt(1)!=='/')?n:'/'}catch(e){return'/'}})();
var root=document.getElementById('mbRoot');
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function J(u,o){return fetch(u,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(o||{})}).then(function(r){return r.json().then(function(j){j._s=r.status;return j},function(){return{error:'서버 응답을 읽지 못했어요.',_s:r.status}})},function(){return{error:'네트워크 오류예요. 잠시 후 다시 시도해 주세요.',_s:0}})}
function msg(box,t,kind){box.className='mbMsg'+(t?' on '+(kind||'bad'):'');box.textContent=t||''}
function field(label,type,id,ph,ac){var l=el('label',null,label);var i=el('input');i.type=type;i.id=id;if(ph)i.placeholder=ph;if(ac)i.autocomplete=ac;i.setAttribute('autocapitalize','off');i.spellcheck=false;l.appendChild(i);return l}
function V(id){var e=document.getElementById(id);return e?e.value:''}
function done(){try{if(window.self!==window.top){window.parent.location.reload();return}}catch(e){}location.href=NEXT}
function load(){fetch('/member/api/me',{cache:'no-store',credentials:'same-origin'}).then(function(r){return r.json()}).then(function(j){S.me=j;draw()}).catch(function(){root.textContent='불러오지 못했어요. 새로고침해 주세요.'})}
function tabs(){var t=el('div','mbTabs');[['login','로그인'],['signup','회원가입']].forEach(function(x){var b=el('button',null,x[1]);b.type='button';if(S.view===x[0])b.className='on';b.onclick=function(){S.view=x[0];S.codeSent=false;draw()};t.appendChild(b)});return t}
function countdown(btn,sec){S.cd=sec;clearInterval(S.timer);function tick(){if(!btn.isConnected){clearInterval(S.timer);return}if(S.cd>0){btn.disabled=true;btn.textContent='다시 받기 ('+S.cd+'초)';S.cd--}else{btn.disabled=false;btn.textContent='인증번호 다시 받기';clearInterval(S.timer)}}tick();S.timer=setInterval(tick,1000)}
function snsBox(card,mode){var me=S.me,sc=me.social||{};if(mode==='signup'&&!me.signup)return;var w=el('div','mbSns');w.appendChild(el('h4',null,mode==='signup'?'또는 SNS 계정으로 간편 가입':'또는 SNS 계정으로 로그인'));
 [['naver','네이버','N','로'],['google','구글','G','로'],['kakao','카카오톡','K','으로']].forEach(function(x){var a=el('a','mbSnsB '+x[0]+(sc[x[0]]?'':' off'));a.appendChild(el('i',null,x[2]));a.appendChild(document.createTextNode(x[1]+x[3]+(mode==='signup'?' 시작하기':' 로그인')+(sc[x[0]]?'':' (준비 중)')));
  if(sc[x[0]]){a.href='/member/oauth/'+x[0]+'/start?next='+encodeURIComponent(NEXT);a.target='_top';a.rel='nofollow'}else a.setAttribute('aria-disabled','true');w.appendChild(a)});
 var h=el('p','mbHint');h.appendChild(document.createTextNode('SNS로 시작하면 '+(mode==='signup'?'가입과 ':'')+'개인정보 수집·이용(이메일·SNS 회원번호)에 동의한 것으로 봅니다. 자세한 내용은 '));var a2=el('a',null,'개인정보처리방침');a2.href='/privacy';a2.target='_blank';a2.rel='noopener';h.appendChild(a2);h.appendChild(document.createTextNode('을 확인하세요.'));w.appendChild(h);card.appendChild(w)}
var SNSERR=%SNSERR%;
function drawLogin(card){var f=el('form','mbF');f.noValidate=true;
 f.appendChild(field('이메일 (아이디)','email','mbEm','example@email.com','username'));f.appendChild(field('비밀번호','password','mbPw','비밀번호','current-password'));
 var m=el('div','mbMsg');f.appendChild(m);var b=el('button','mu-btn primary big','로그인');b.type='submit';f.appendChild(b);
 var l=el('a',null,'비밀번호를 잊으셨나요?');l.href='#';l.className='mbHint';l.onclick=function(e){e.preventDefault();S.view='reset';S.codeSent=false;draw()};f.appendChild(l);
 f.onsubmit=function(e){e.preventDefault();b.disabled=true;msg(m,'');J('/member/api/login',{email:V('mbEm'),password:V('mbPw')}).then(function(j){if(j.ok){msg(m,'로그인했어요','ok');done()}else{msg(m,j.error||'로그인하지 못했어요');b.disabled=false}})};card.appendChild(f);snsBox(card,'login')}
function drawSignup(card){var me=S.me,f=el('form','mbF');f.noValidate=true;
 if(!me.signup){card.appendChild(el('p','mbHint','지금은 새 회원가입을 받지 않아요. 이미 회원이면 로그인해 주세요.'));return}
 f.appendChild(field('이메일 (아이디로 쓰여요)','email','mbEm','example@email.com','username'));
 var m=el('div','mbMsg');
 if(me.verify){var r=el('div','mbRow');var b1=el('button','mu-btn',S.codeSent?'인증번호 다시 받기':'인증번호 받기');b1.type='button';
  b1.onclick=function(){b1.disabled=true;msg(m,'');J('/member/api/code',{email:V('mbEm'),purpose:'signup'}).then(function(j){if(j.ok){S.codeSent=true;msg(m,'인증번호를 보냈어요. 메일함(스팸함 포함)을 확인해 주세요. 10분 안에 입력하세요.','ok');countdown(b1,60);var c=document.getElementById('mbCode');if(c)c.focus()}else{msg(m,j.error||'보내지 못했어요');b1.disabled=false}})};
  var wrap=el('div');wrap.style.cssText='display:flex;flex-direction:column;gap:6px';wrap.appendChild(b1);f.appendChild(wrap);
  f.appendChild(field('인증번호 (6자리)','text','mbCode','메일로 받은 6자리 숫자','one-time-code'));var ci=f.querySelector('#mbCode');ci.inputMode='numeric';ci.maxLength=6}
 f.appendChild(field('비밀번호 (8자 이상, 영문·숫자·기호 중 2가지 이상)','password','mbPw','비밀번호','new-password'));
 f.appendChild(field('비밀번호 확인','password','mbPw2','한 번 더 입력','new-password'));
 var ag=el('label','mbAgree');var cb=el('input');cb.type='checkbox';cb.id='mbAgree';ag.appendChild(cb);var sp=el('span');sp.appendChild(document.createTextNode('개인정보 수집·이용에 동의합니다. 수집 항목은 이메일·비밀번호(암호화 저장)뿐이며, 탈퇴하면 모두 삭제돼요. '));var a=el('a',null,'자세히');a.href='/privacy';a.target='_blank';a.rel='noopener';sp.appendChild(a);ag.appendChild(sp);f.appendChild(ag);
 f.appendChild(m);var b=el('button','mu-btn primary big','가입하기');b.type='submit';f.appendChild(b);
 if(!me.verify)f.appendChild(el('p','mbHint','※ 지금은 이메일 인증 없이 가입돼요. 비밀번호를 잊으면 되찾기 어려울 수 있으니 정확한 이메일을 쓰세요.'));
 f.onsubmit=function(e){e.preventDefault();if(V('mbPw')!==V('mbPw2')){msg(m,'비밀번호 확인이 달라요');return}if(!cb.checked){msg(m,'개인정보 수집·이용에 동의해 주세요');return}
  b.disabled=true;msg(m,'');J('/member/api/signup',{email:V('mbEm'),code:V('mbCode'),password:V('mbPw'),agree:true}).then(function(j){if(j.ok){msg(m,'가입이 끝났어요! 이동합니다…','ok');done()}else{msg(m,j.error||'가입하지 못했어요');b.disabled=false}})};
 card.appendChild(f);snsBox(card,'signup')}
function drawReset(card){var f=el('form','mbF');f.noValidate=true;f.appendChild(el('b',null,'비밀번호 다시 정하기'));
 f.appendChild(field('가입한 이메일','email','mbEm','example@email.com','username'));var m=el('div','mbMsg');
 var b1=el('button','mu-btn',S.codeSent?'인증번호 다시 받기':'인증번호 받기');b1.type='button';
 b1.onclick=function(){b1.disabled=true;msg(m,'');J('/member/api/code',{email:V('mbEm'),purpose:'reset'}).then(function(j){if(j.ok){S.codeSent=true;msg(m,'가입된 이메일이면 인증번호를 보냈어요. 메일함(스팸함 포함)을 확인해 주세요.','ok');countdown(b1,60)}else{msg(m,j.error||'보내지 못했어요');b1.disabled=false}})};
 f.appendChild(b1);f.appendChild(field('인증번호 (6자리)','text','mbCode','메일로 받은 6자리 숫자','one-time-code'));var ci=f.querySelector('#mbCode');ci.inputMode='numeric';ci.maxLength=6;
 f.appendChild(field('새 비밀번호','password','mbPw','8자 이상, 영문·숫자·기호 2가지 이상','new-password'));f.appendChild(field('새 비밀번호 확인','password','mbPw2','한 번 더 입력','new-password'));
 f.appendChild(m);var b=el('button','mu-btn primary big','비밀번호 바꾸고 로그인');b.type='submit';f.appendChild(b);
 var l=el('a',null,'← 로그인으로 돌아가기');l.href='#';l.className='mbHint';l.onclick=function(e){e.preventDefault();S.view='login';draw()};f.appendChild(l);
 f.onsubmit=function(e){e.preventDefault();if(V('mbPw')!==V('mbPw2')){msg(m,'새 비밀번호 확인이 달라요');return}b.disabled=true;msg(m,'');
  J('/member/api/reset',{email:V('mbEm'),code:V('mbCode'),password:V('mbPw')}).then(function(j){if(j.ok){msg(m,'바꿨어요! 이동합니다…','ok');done()}else{msg(m,j.error||'바꾸지 못했어요');b.disabled=false}})};card.appendChild(f)}
function drawMe(card){var me=S.me,w=el('div','mbMe');var dl=el('dl');[['아이디',me.internal?'SNS 회원':me.email],['로그인 방식',(me.providers&&me.providers.length?me.providers.join('·')+' 연결':'')+(me.has_pw?(me.providers&&me.providers.length?' · ':'')+'이메일':'')||'-'],['회원 단계',me.level_name||'-'],['가입일',me.since]].forEach(function(x){dl.appendChild(el('dt',null,x[0]));dl.appendChild(el('dd',null,x[1]))});w.appendChild(dl);
 var act=el('div','mbAct');var lo=el('button','mu-btn','로그아웃');lo.onclick=function(){J('/member/api/logout').then(function(){done()})};act.appendChild(lo);
 var home=el('a','mu-btn primary','종목분석으로 →');home.href='/';home.target='_top';act.appendChild(home);w.appendChild(act);
 var pw=el('div','mbSub');if(me.has_pw)pw.appendChild(el('b',null,'🔑 비밀번호 바꾸기'));var f=el('form','mbF');f.noValidate=true;f.style.marginTop='8px';
 f.appendChild(field('지금 비밀번호','password','mbOld','','current-password'));f.appendChild(field('새 비밀번호','password','mbNew','8자 이상, 영문·숫자·기호 2가지 이상','new-password'));var m=el('div','mbMsg');f.appendChild(m);
 var b=el('button','mu-btn','비밀번호 바꾸기');b.type='submit';f.appendChild(b);
 f.onsubmit=function(e){e.preventDefault();if(!confirm('비밀번호를 바꿀까요? 다른 기기는 모두 로그아웃돼요.'))return;b.disabled=true;J('/member/api/password',{old:V('mbOld'),password:V('mbNew')}).then(function(j){b.disabled=false;if(j.ok){msg(m,'비밀번호를 바꿨어요.','ok');document.getElementById('mbOld').value='';document.getElementById('mbNew').value=''}else msg(m,j.error||'바꾸지 못했어요')})};
 if(me.has_pw){pw.appendChild(f);w.appendChild(pw)}
 var wd=el('div','mbSub');wd.appendChild(el('b',null,'🗑 회원 탈퇴'));wd.appendChild(el('p','mbHint','탈퇴하면 이메일·비밀번호·SNS 연결 정보가 바로 삭제되고 되돌릴 수 없어요.'));var f2=el('form','mbF');f2.noValidate=true;
 if(me.has_pw)f2.appendChild(field('비밀번호 확인','password','mbWd','','current-password'));else f2.appendChild(field('확인을 위해 ‘탈퇴’ 라고 입력해 주세요','text','mbWd','탈퇴','off'));var m2=el('div','mbMsg');f2.appendChild(m2);var b2=el('button','mu-btn','탈퇴하기');b2.type='submit';f2.appendChild(b2);
 f2.onsubmit=function(e){e.preventDefault();if(!confirm('정말 탈퇴할까요? 모든 회원 정보가 삭제되고 되돌릴 수 없어요.'))return;b2.disabled=true;J('/member/api/withdraw',me.has_pw?{password:V('mbWd')}:{confirm:V('mbWd').trim()}).then(function(j){if(j.ok){done()}else{b2.disabled=false;msg(m2,j.error||'탈퇴하지 못했어요')}})};
 wd.appendChild(f2);w.appendChild(wd);card.appendChild(w)}
function draw(){root.innerHTML='';var me=S.me;if(!me.on){root.appendChild(el('p','mbHint','지금은 회원 기능을 쓰지 않아요.'));return}
 var box=el('div','mbBox');var card=el('div','mu-card');var b=el('div','mu-card-b');
 if(me.logged){var h=el('div','mu-card-h','👤 내 정보');card.appendChild(h);drawMe(b)}
 else{if(SNSMSG){var eb=el('div','mbMsg on bad',SNSMSG);eb.style.marginBottom='10px';b.appendChild(eb)}if(S.view!=='reset')b.appendChild(tabs());if(S.view==='signup')drawSignup(b);else if(S.view==='reset')drawReset(b);else drawLogin(b)}
 card.appendChild(b);box.appendChild(card);root.appendChild(box);var f=root.querySelector('input');if(f&&!me.logged)try{f.focus()}catch(e){}}
var q=new URLSearchParams(location.search);if(q.get('tab')==='signup')S.view='signup';var SNSMSG=SNSERR[q.get('sns_err')||'']||'';load();
})();
"""


@bp.route("/member")
def page():
    if not _on():
        return "not found", 404
    body = f'<style>{PAGE_CSS}</style><div id="mbRoot"><p class="mu-sub">불러오는 중…</p></div>'
    js = PAGE_JS.replace("%SNSERR%", json.dumps(SNS_ERR, ensure_ascii=False).replace("<", "\\u003c"))
    html = U.page("회원", body, icon="👤", subtitle="이메일 또는 네이버·구글·카카오로 간편하게 가입하고 로그인해요", script=js, disclaimer=False)
    resp = C.app.make_response(html)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ───────────────────────── 관리자 API ─────────────────────────
def _stats():
    now = int(time.time())
    total = int(_q("SELECT COUNT(*) FROM members", fetch=True)[0][0])
    today0 = now - ((now + 9 * 3600) % 86400)
    new_today = int(_q("SELECT COUNT(*) FROM members WHERE created_at>=?", (today0,), fetch=True)[0][0])
    new_7d = int(_q("SELECT COUNT(*) FROM members WHERE created_at>=?", (now - 7 * 86400,), fetch=True)[0][0])
    blocked = int(_q("SELECT COUNT(*) FROM members WHERE status<>'active'", fetch=True)[0][0])
    online = int(_q("SELECT COUNT(DISTINCT email) FROM member_sessions WHERE last_seen>=?", (now - 1800,), fetch=True)[0][0])
    mails = int(_q("SELECT COUNT(*) FROM member_codes WHERE created_at>=?", (now - 86400,), fetch=True)[0][0])
    return {"total": total, "new_today": new_today, "new_7d": new_7d, "blocked": blocked, "online": online, "mails_24h": mails}


def _state():
    mail = "resend" if C.RESEND_API_KEY else ("smtp" if C.SMTP_HOST else "none")
    return {"settings": {"on": _on(), "signup": setting_get("member_signup", "1") == "1", "verify": _verify_on(), "default_level": _default_level(), "mail_cap": _daily_cap()},
            "levels": member_levels(), "stats": _stats(), "mail": mail, "mail_from": C.MAIL_FROM if mail != "none" else "",
            "sandbox_sender": "resend.dev" in (C.MAIL_FROM or ""),
            "social": [{"id": k, "label": v["label"], "ok": _configured(k), "env": [v["env"][0]] + ([v["env"][1]] if k != "kakao" else [v["env"][1] + "(선택)"]), "redirect": _redirect_uri(k)}
                       for k, v in PROVIDERS.items()]}


@bp.route("/admin/api/member/state")
def adm_state():
    deny = _admin_deny()
    if deny:
        return deny
    return _admin_json(_state())


@bp.route("/admin/api/member/settings", methods=["POST"])
def adm_settings():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    ids = {x["id"] for x in member_levels()}
    lv = str(d.get("default_level", ""))
    try:
        cap = int(d.get("mail_cap"))
    except Exception:
        cap = -1
    if lv not in ids or not (0 <= cap <= 5000):
        return _admin_json({"error": "기본 회원 단계 또는 인증 메일 하루 상한(0~5000)이 올바르지 않아요."}, 400)
    for k, key in (("on", "member_on"), ("signup", "member_signup"), ("verify", "member_verify")):
        C.setting_set(key, "1" if d.get(k) else "0")
    C.setting_set("member_default_level", lv)
    C.setting_set("member_mail_cap", str(cap))
    _alog("member_settings", f"on={int(bool(d.get('on')))} signup={int(bool(d.get('signup')))} verify={int(bool(d.get('verify')))} level={lv} cap={cap}")
    return _admin_json(_state())


@bp.route("/admin/api/member/list")
def adm_list():
    deny = _admin_deny()
    if deny:
        return deny
    q = re.sub(r"[%_\\\s]", "", str(request.args.get("q", "")).lower())[:60]
    try:
        page_no = max(1, int(request.args.get("page", 1)))
    except Exception:
        page_no = 1
    per = 50
    where, args = ("WHERE email LIKE ?", ["%" + q + "%"]) if q else ("", [])
    total = int(_q(f"SELECT COUNT(*) FROM members {where}", args, fetch=True)[0][0])
    rows = _q(f"SELECT email,level,status,created_at,last_login,verified FROM members {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
              args + [per, (page_no - 1) * per], fetch=True) or []
    prov = {}
    if rows:
        ph = ",".join("?" * len(rows))
        for e, pv in (_q(f"SELECT email,provider FROM member_social WHERE email IN ({ph})", [r[0] for r in rows], fetch=True) or []):
            prov.setdefault(e, []).append(PROVIDERS[pv]["label"] if pv in PROVIDERS else pv)
    out = [{"email": r[0], "level": r[1], "status": r[2], "created": _ymd(r[3]), "last": _ymd(r[4]), "verified": bool(r[5]), "sns": prov.get(r[0], [])} for r in rows]
    return _admin_json({"rows": out, "total": total, "page": page_no, "per": per})


def _target(d):
    email = _norm_email(d.get("email"))
    if not email or not _q("SELECT 1 FROM members WHERE email=?", (email,), fetch=True):
        return None
    return email


@bp.route("/admin/api/member/update", methods=["POST"])
def adm_update():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    d = _json_body()
    email = _target(d)
    if not email:
        return _admin_json({"error": "없는 회원이에요."}, 404)
    if "level" in d:
        if str(d["level"]) not in {x["id"] for x in member_levels()}:
            return _admin_json({"error": "없는 회원 단계예요."}, 400)
        _q("UPDATE members SET level=? WHERE email=?", (str(d["level"]), email))
    if "status" in d:
        if d["status"] not in ("active", "blocked"):
            return _admin_json({"error": "상태 값이 올바르지 않아요."}, 400)
        _q("UPDATE members SET status=? WHERE email=?", (d["status"], email))
        if d["status"] == "blocked":
            _q("DELETE FROM member_sessions WHERE email=?", (email,))
    _alog("member_update", f"{C._mask_email(email)} level={d.get('level', '-')} status={d.get('status', '-')}")
    return _admin_json({"ok": True})


@bp.route("/admin/api/member/logout", methods=["POST"])
def adm_logout():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    email = _target(_json_body())
    if not email:
        return _admin_json({"error": "없는 회원이에요."}, 404)
    _q("DELETE FROM member_sessions WHERE email=?", (email,))
    _alog("member_force_logout", C._mask_email(email))
    return _admin_json({"ok": True})


@bp.route("/admin/api/member/delete", methods=["POST"])
def adm_delete():
    deny = _admin_deny(write=True)
    if deny:
        return deny
    email = _target(_json_body())
    if not email:
        return _admin_json({"error": "없는 회원이에요."}, 404)
    _delete_member(email)
    _alog("member_delete", C._mask_email(email))
    return _admin_json({"ok": True})


ADMIN_JS = r"""
var MB={S:null,q:'',page:1,L:null,p:null};
function mbLoad(p){MB.p=p;api('/admin/api/member/state').then(function(j){if(cur!=='mem')return;MB.S=j;mbDraw(p);mbList()})}
function mbDraw(p){p.innerHTML='';var S=MB.S,s=S.settings,st=S.stats;
 var top=el('div','c');top.appendChild(el('b',null,'👤 회원 관리'));
 top.appendChild(el('p','note','이메일을 아이디로 쓰는 회원가입·로그인 기능이에요. 가입한 회원은 [🧭 메뉴 관리]에서 정한 회원 단계에 따라 메뉴가 보여요. 비밀번호는 암호화돼 저장되어 운영자도 볼 수 없어요.'));
 var g=el('div','grid');[['전체 회원',st.total],['오늘 가입',st.new_today],['최근 7일 가입',st.new_7d],['지금 접속(30분)',st.online],['차단',st.blocked],['인증메일(24h)',st.mails_24h]].forEach(function(x){var k=el('div','k');k.appendChild(el('small',null,x[0]));k.appendChild(el('b',null,String(x[1])));g.appendChild(k)});top.appendChild(g);p.appendChild(top);
 var mc=el('div','c');mc.appendChild(el('b',null,'✉ 메일 발송 상태'));
 var ms=S.mail==='none'?'❌ 메일 발송이 설정되지 않았어요(RESEND_API_KEY). 이메일 인증 가입이 동작하지 않아요. 아래 [이메일 인증]을 끄면 인증 없이 가입은 가능해요.':'✅ '+(S.mail==='resend'?'Resend':'SMTP')+' 로 발송 · 보내는 주소: '+S.mail_from;
 mc.appendChild(el('p','note',ms));
 if(S.mail!=='none'&&S.sandbox_sender)mc.appendChild(el('p','note','⚠ 지금 보내는 주소가 resend.dev(시험용)예요. 이 주소는 Resend 계정 주인의 메일로만 보낼 수 있어서 다른 사람 가입 인증 메일은 실패해요. Resend에서 내 도메인을 인증하고 Render 환경변수 MAIL_FROM 을 "종목분석 미니 <no-reply@내도메인>" 으로 설정하세요.'));
 p.appendChild(mc);
 var nc=el('div','c');nc.appendChild(el('b',null,'🔗 SNS 로그인 상태 (네이버·구글·카카오)'));
 nc.appendChild(el('p','note','각 서비스 개발자 센터에서 앱을 만들고, 아래 [Redirect URI]를 그대로 등록한 뒤, Render 환경변수에 키를 넣으면 로그인 화면의 버튼이 자동으로 켜져요. 키는 코드나 화면에 저장하지 않아요.'));
 (S.social||[]).forEach(function(x){var r=el('div','m');r.style.cssText='margin:6px 0;line-height:1.55';r.appendChild(el('b',null,(x.ok?'✅ ':'⬜ ')+x.label+(x.ok?' — 사용 중':' — 환경변수 미설정(버튼이 준비 중으로 보여요)')));r.appendChild(document.createElement('br'));r.appendChild(document.createTextNode('환경변수: '+x.env.join(' · ')));r.appendChild(document.createElement('br'));r.appendChild(document.createTextNode('Redirect URI: '+x.redirect));nc.appendChild(r)});
 nc.appendChild(el('p','note','카카오는 일반 앱에서 이메일 제공 권한을 받기 어려워요. 이메일을 못 받으면 ‘kakao_번호@sns.local’ 내부 아이디로 가입돼요(비즈 앱 승인 뒤 환경변수 KAKAO_REQUEST_EMAIL=1 을 넣으면 이메일을 요청해요).'));
 p.appendChild(nc);
 var sc=el('div','c');sc.appendChild(el('b',null,'⚙ 회원 설정'));var f=el('div','bar');
 function chk(label,on){var l=el('label');l.style.cssText='display:flex;gap:6px;align-items:center';var c=el('input');c.type='checkbox';c.checked=!!on;l.appendChild(c);l.appendChild(document.createTextNode(label));f.appendChild(l);return c}
 var cOn=chk('회원 기능 사용(끄면 로그인·가입 버튼이 사라져요)',s.on),cSg=chk('새 회원가입 받기',s.signup),cVf=chk('이메일 인증 사용(권장)',s.verify);
 var f2=el('div','bar');f2.appendChild(el('span','m','신규 회원 기본 단계'));var sel=el('select');S.levels.forEach(function(l){var o=el('option',null,l.name);o.value=l.id;sel.appendChild(o)});sel.value=s.default_level;f2.appendChild(sel);
 f2.appendChild(el('span','m','인증 메일 하루 상한'));var cap=el('input');cap.type='number';cap.min=0;cap.max=5000;cap.value=s.mail_cap;cap.style.width='90px';f2.appendChild(cap);f2.appendChild(el('span','m','통 (Resend 무료는 하루 100통)'));
 sc.appendChild(f);sc.appendChild(f2);
 sc.appendChild(bt('💾 회원 설정 저장','bt',function(){apiJ('/admin/api/member/settings',{on:cOn.checked,signup:cSg.checked,verify:cVf.checked,default_level:sel.value,mail_cap:parseInt(cap.value,10)}).then(function(j){if(j.error){toast(j.error);return}MB.S=j;toast('회원 설정을 저장했어요');mbDraw(p);mbList()})}));
 p.appendChild(sc);
 var lc=el('div','c');lc.appendChild(el('b',null,'📋 회원 목록'));var bar=el('div','bar');var qi=el('input');qi.placeholder='이메일 검색';qi.value=MB.q;qi.style.width='220px';
 qi.onkeydown=function(e){if(e.key==='Enter'){MB.q=qi.value;MB.page=1;mbList()}};bar.appendChild(qi);bar.appendChild(bt('검색','bt2',function(){MB.q=qi.value;MB.page=1;mbList()}));lc.appendChild(bar);
 var box=el('div');box.id='mbList';lc.appendChild(box);p.appendChild(lc)}
function mbList(){var box=$('mbList');if(!box)return;api('/admin/api/member/list?q='+encodeURIComponent(MB.q)+'&page='+MB.page).then(function(j){if(cur!=='mem'||!$('mbList'))return;MB.L=j;box=$('mbList');box.innerHTML='';
 if(!j.rows.length){box.appendChild(el('p','note',MB.q?'검색 결과가 없어요.':'아직 가입한 회원이 없어요.'));return}
 var tw=el('div');tw.style.cssText='overflow-x:auto';var t=el('table');var h=el('tr');['이메일','단계','상태','가입일','마지막 로그인','관리'].forEach(function(x){h.appendChild(el('th',null,x))});t.appendChild(h);
 j.rows.forEach(function(r){var tr=el('tr');var e=el('td');e.appendChild(el('b',null,r.email));if(r.sns&&r.sns.length)e.appendChild(el('div','m','🔗 '+r.sns.join('·')+' 연결'));if(!r.verified)e.appendChild(el('div','m','인증 없이 가입'));tr.appendChild(e);
  var lv=el('td');var sel=el('select');MB.S.levels.forEach(function(l){var o=el('option',null,l.name);o.value=l.id;sel.appendChild(o)});sel.value=r.level;lv.appendChild(sel);
  var sv=bt('💾 단계 저장','bt3',function(){apiJ('/admin/api/member/update',{email:r.email,level:sel.value}).then(function(x){if(x.error){toast(x.error);return}r.level=sel.value;toast(r.email+' 단계를 저장했어요');mbList()})});sv.style.marginLeft='6px';lv.appendChild(sv);tr.appendChild(lv);
  var stt=el('td');stt.appendChild(el('span',r.status==='active'?'m':'bad',r.status==='active'?'정상':'⛔ 차단'));tr.appendChild(stt);
  tr.appendChild(el('td','m',r.created));tr.appendChild(el('td','m',r.last));
  var ac=el('td');
  ac.appendChild(bt(r.status==='active'?'차단 적용':'차단 해제','bt3',function(){apiJ('/admin/api/member/update',{email:r.email,status:r.status==='active'?'blocked':'active'}).then(function(x){if(x.error){toast(x.error);return}toast(r.status==='active'?'차단을 적용했어요':'차단을 해제했어요');mbLoad(MB.p)})}));
  var lo=bt('강제 로그아웃','bt3',function(){apiJ('/admin/api/member/logout',{email:r.email}).then(function(x){toast(x.error||'모든 기기에서 로그아웃시켰어요')})});lo.style.marginLeft='6px';ac.appendChild(lo);
  var dl=bt('삭제','bt3',function(){if(!confirm(r.email+' 회원을 삭제할까요? 되돌릴 수 없어요.'))return;apiJ('/admin/api/member/delete',{email:r.email}).then(function(x){if(x.error){toast(x.error);return}toast('삭제했어요');mbLoad(MB.p)})});dl.style.marginLeft='6px';ac.appendChild(dl);tr.appendChild(ac);
  t.appendChild(tr)});tw.appendChild(t);box.appendChild(tw);
 var pages=Math.max(1,Math.ceil(j.total/j.per));var nv=el('div','bar');nv.appendChild(el('span','m',j.total+'명 · '+j.page+' / '+pages+' 쪽'));
 var pv=bt('◀ 이전','bt3',function(){MB.page--;mbList()});pv.disabled=j.page<=1;var nx=bt('다음 ▶','bt3',function(){MB.page++;mbList()});nx.disabled=j.page>=pages;nv.appendChild(pv);nv.appendChild(nx);box.appendChild(nv)})}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_admin_tab("mem", "👤 회원", ADMIN_JS, "mbLoad")
    C.set_viewer_level_hook(_viewer_level_hook)
    return bp
