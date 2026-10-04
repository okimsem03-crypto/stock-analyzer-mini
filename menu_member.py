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
.mbTabs button.on{background:var(--accent);color:#fff;border-color:transparent}
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
    today0 = now - ((now + 9 * 3600) % 86400)
    r = _q("SELECT (SELECT COUNT(*) FROM members), (SELECT COUNT(*) FROM members WHERE created_at>=?), (SELECT COUNT(*) FROM members WHERE created_at>=?), "
           "(SELECT COUNT(*) FROM members WHERE status<>'active'), (SELECT COUNT(DISTINCT email) FROM member_sessions WHERE last_seen>=?), "
           "(SELECT COUNT(*) FROM member_codes WHERE created_at>=?)", (today0, now - 7 * 86400, now - 1800, now - 86400), fetch=True)[0]
    return {"total": int(r[0]), "new_today": int(r[1]), "new_7d": int(r[2]), "blocked": int(r[3]), "online": int(r[4]), "mails_24h": int(r[5])}


_KR2 = ("co.kr", "or.kr", "go.kr", "ne.kr", "re.kr", "pe.kr", "ac.kr", "ms.kr", "hs.kr", "es.kr", "sc.kr")


def _root_domain(host):
    """stock.oky.kr → oky.kr (co.kr 같은 2단계 도메인은 한 칸 더). 메일 도메인 인증에 쓸 '내 도메인' 추정."""
    h = (host or "").split(":")[0].strip().lower()
    parts = h.split(".")
    if len(parts) < 3 or re.match(r"^[\d.]+$", h):
        return h
    return ".".join(parts[-3:]) if ".".join(parts[-2:]) in _KR2 else ".".join(parts[-2:])


def _env_set(*names):
    return {n: bool(os.environ.get(n, "").strip()) for n in names}


# 제공자별 설정 안내(화면은 이 내용을 그대로 그린다). {redirect}·{base}·{host} 는 서버가 채운다.
PROVIDER_GUIDE = {
    "naver": {
        "links": [["애플리케이션 등록 (여기서 시작)", "https://developers.naver.com/apps/#/register"], ["내 애플리케이션 목록 (키 확인)", "https://developers.naver.com/apps/#/list"]],
        "steps": ["위 [애플리케이션 등록] 링크를 열고 네이버 계정으로 로그인해요.",
                  "애플리케이션 이름에 ‘종목분석 미니’(아무 이름이나 가능)를 쓰고, 사용 API에서 ‘네이버 로그인’을 골라요.",
                  "‘제공 정보’에서 이메일 주소를 반드시 ‘필수’로 체크해요. (이메일이 회원 아이디가 되기 때문이에요)",
                  "서비스 환경에서 ‘PC 웹’을 추가하고, 아래 [서비스 URL]·[Callback URL]을 복사해 그대로 붙여 넣어요.",
                  "[등록하기]를 누른 뒤 앱 개요 화면의 Client ID·Client Secret을 복사해 Render 환경변수에 넣어요(아래 ‘Render에 넣을 값’)."],
        "values": [["서비스 URL", "{base}", "https:// 로 시작, 끝에 / 없이"], ["Callback URL", "{redirect}", "한 글자라도 다르면 로그인이 안 돼요"]],
        "tip": "처음엔 ‘개발 중’ 상태라 앱 멤버(내 계정 + [멤버관리]에 추가한 계정)만 로그인돼요. 일반 회원이 쓰게 하려면 앱 화면의 [검수 요청]을 승인받아야 해요.",
    },
    "google": {
        "links": [["사용자 인증 정보 (OAuth 클라이언트 만들기)", "https://console.cloud.google.com/apis/credentials"], ["OAuth 동의 화면(브랜딩)", "https://console.cloud.google.com/auth/branding"],
                  ["대상 (테스트 → 프로덕션 게시)", "https://console.cloud.google.com/auth/audience"]],
        "steps": ["Google Cloud 콘솔에 로그인하고, 위쪽 프로젝트 선택 상자에서 [새 프로젝트]를 만들어요(이름 예: stock-mini).",
                  "[OAuth 동의 화면(브랜딩)]에서 앱 이름 ‘종목분석 미니’, 사용자 지원 이메일, 개발자 연락처 이메일을 입력해요. 대상(User type)은 ‘외부’를 골라요.",
                  "[사용자 인증 정보] → [+ 사용자 인증 정보 만들기] → ‘OAuth 클라이언트 ID’ → 애플리케이션 유형 ‘웹 애플리케이션’을 골라요.",
                  "‘승인된 리디렉션 URI’에 아래 [승인된 리디렉션 URI]를 추가하고 [만들기]를 눌러요. (JavaScript 원본은 비워 둬도 돼요)",
                  "나온 클라이언트 ID·클라이언트 보안 비밀번호를 복사해 Render 환경변수에 넣어요.",
                  "[대상] 화면에서 ‘앱 게시(프로덕션으로)’를 눌러요. 테스트 상태로 두면 등록한 테스트 사용자만 로그인돼요. 쓰는 권한이 email·openid뿐이라 별도 심사 없이 게시돼요."],
        "values": [["승인된 리디렉션 URI", "{redirect}", "한 글자라도 다르면 redirect_uri_mismatch 오류가 나요"], ["(선택) 승인된 JavaScript 원본", "{base}", "비워 둬도 돼요"], ["필요한 권한(범위)", "openid email", "기본 범위라 따로 추가하지 않아도 돼요"]],
        "tip": "설정을 바꾼 직후에는 구글에 반영되기까지 몇 분 걸릴 수 있어요.",
    },
    "kakao": {
        "links": [["카카오 개발자 콘솔 (내 애플리케이션)", "https://developers.kakao.com/console/app"], ["카카오 로그인 FAQ (공식)", "https://developers.kakao.com/docs/latest/ko/kakaologin/faq"]],
        "steps": ["카카오 개발자 콘솔에서 [애플리케이션 추가하기]로 앱을 만들어요(앱 이름 ‘종목분석 미니’).",
                  "[앱] → [플랫폼 키] → ‘REST API 키’를 열어 키 값을 복사해요. 이 값이 KAKAO_REST_API_KEY예요.",
                  "[제품 설정] → [카카오 로그인]에서 ‘활성화’를 켜요(화면에 따라 [카카오 로그인] → [고급] 쪽에 있어요).",
                  "Redirect URI에 아래 값을 등록해요. 메뉴가 안 보이면 [플랫폼 키]의 REST API 키 상세에 있는 ‘카카오 로그인 리다이렉트 URI’ 항목에 등록해요.",
                  "[동의항목]에서 닉네임 등을 설정해요. 이메일(account_email)은 비즈 앱으로 전환·심사를 통과해야 받을 수 있어요(없어도 가입은 돼요).",
                  "REST API 키 상세의 ‘클라이언트 시크릿’이 사용(활성) 상태면 그 코드도 KAKAO_CLIENT_SECRET에 넣어요. 사용 안 함이면 비워 둬도 돼요."],
        "values": [["Redirect URI", "{redirect}", "한 글자라도 다르면 KOE006 오류가 나요"], ["사이트 도메인", "{host}", "플랫폼(웹) 등록란이 있으면 입력"]],
        "tip": "이메일을 못 받으면 ‘kakao_번호@sns.local’ 내부 아이디로 가입돼요. 비즈 앱 승인 뒤 환경변수 KAKAO_REQUEST_EMAIL=1 을 추가하면 이메일을 요청해요.",
    },
}


def _guide():
    base = _base_url()
    host = urllib.parse.urlparse(base).netloc
    root = _root_domain(host)
    names = ["RESEND_API_KEY", "MAIL_FROM", "SMTP_HOST", "MEMBER_OAUTH_BASE_URL", "KAKAO_REQUEST_EMAIL"] + [n for v in PROVIDERS.values() for n in v["env"]]
    envs = _env_set(*names)
    provs = []
    for k, v in PROVIDERS.items():
        g_ = PROVIDER_GUIDE[k]
        fill = lambda t: t.replace("{base}", base).replace("{redirect}", _redirect_uri(k)).replace("{host}", host)
        provs.append({"id": k, "label": v["label"], "ok": _configured(k), "redirect": _redirect_uri(k),
                      "env": [{"name": v["env"][0], "set": envs[v["env"][0]], "opt": False, "hint": "발급된 ID(키)"},
                              {"name": v["env"][1], "set": envs[v["env"][1]], "opt": k == "kakao", "hint": "발급된 비밀번호(시크릿)" + (" — 사용 안 함이면 비워도 돼요" if k == "kakao" else "")}],
                      "links": g_["links"], "steps": g_["steps"], "tip": g_["tip"], "values": [[a, fill(b), c] for a, b, c in g_["values"]]})
    admin_to = (C.ADMIN_EMAILS or [""])[0]
    return {"base": base, "host": host, "root": root, "suggest_from": f"종목분석 미니 <no-reply@{root}>", "admin_email": admin_to, "env": envs, "providers": provs,
            "oauth_base_set": envs["MEMBER_OAUTH_BASE_URL"]}


def _state():
    mail = "resend" if C.RESEND_API_KEY else ("smtp" if C.SMTP_HOST else "none")
    return {"settings": {"on": _on(), "signup": setting_get("member_signup", "1") == "1", "verify": _verify_on(), "default_level": _default_level(), "mail_cap": _daily_cap()},
            "levels": member_levels(), "stats": _stats(), "mail": mail, "mail_from": C.MAIL_FROM if mail != "none" else "",
            "sandbox_sender": "resend.dev" in (C.MAIL_FROM or ""),
            "social": [{"id": k, "label": v["label"], "ok": _configured(k), "env": [v["env"][0]] + ([v["env"][1]] if k != "kakao" else [v["env"][1] + "(선택)"]), "redirect": _redirect_uri(k)}
                       for k, v in PROVIDERS.items()],
            "guide": _guide()}


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


_MT = {"last": 0.0, "hour": []}


@bp.route("/admin/api/member/mailtest", methods=["POST"])
def adm_mailtest():
    """메일 설정이 제대로인지 지정한 주소로 시험 메일 1통을 보낸다(관리자 전용, 20초에 1번·시간당 10번)."""
    deny = _admin_deny(write=True)
    if deny:
        return deny
    to = str(_json_body().get("to", "")).strip()
    if not EMAIL_RE.match(to):
        return _admin_json({"error": "받을 메일 주소가 올바르지 않아요."}, 400)
    now = time.time()
    _MT["hour"] = [t for t in _MT["hour"] if now - t < 3600]
    if now - _MT["last"] < 20 or len(_MT["hour"]) >= 10:
        return _admin_json({"error": "시험 메일은 20초에 한 번, 시간당 10번까지만 보낼 수 있어요. 잠시 뒤 다시 눌러 주세요."}, 429)
    _MT["last"] = now
    _MT["hour"].append(now)
    try:
        _send_mail([to], "[종목분석 미니] 메일 발송 시험", "이 메일이 보이면 메일 발송 설정이 정상이에요.\n(관리자 화면 [👤 회원]의 시험 메일 버튼으로 보냈어요.)")
    except Exception as e:
        msg = str(e)
        if msg == "mail_not_configured":
            why = "메일 발송이 아직 설정되지 않았어요. Render 환경변수 RESEND_API_KEY 를 먼저 넣어 주세요."
        elif "http 401" in msg or "http 400" in msg and "api" in msg.lower():
            why = "Resend가 API 키를 받아들이지 않았어요. RESEND_API_KEY 값을 다시 확인해 주세요(re_ 로 시작)."
        elif "http 403" in msg:
            why = "Resend가 보내기를 거절했어요. 보내는 주소의 도메인이 아직 인증(Verified) 전이거나, 시험용 주소(resend.dev)로는 Resend 가입 메일에만 보낼 수 있어요. 도메인 인증과 MAIL_FROM 을 확인해 주세요."
        elif "http 422" in msg:
            why = "보내는 주소(MAIL_FROM) 형식이 올바르지 않아요. 예: 종목분석 미니 <no-reply@내도메인>"
        elif "http 429" in msg:
            why = "Resend 발송 한도에 걸렸어요. 잠시 뒤 다시 시도해 주세요."
        else:
            why = "메일을 보내지 못했어요(" + msg[:120] + ")."
        _alog("member_mailtest_fail", C._mask_email(to))
        return _admin_json({"error": why}, 502)
    _alog("member_mailtest", C._mask_email(to))
    return _admin_json({"ok": True, "to": to})


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
// ───── 설정 안내(메일·SNS 로그인): 단계 · 복사 버튼 · 바로가기 링크 ─────
function mbSt(e,css){e.style.cssText=css;return e}
function mbCopy(text,b){
 function done(ok){var o=b.getAttribute('data-t')||b.textContent;b.setAttribute('data-t',o);b.textContent=ok?'✅ 복사됨':'⚠ 직접 복사';toast(ok?'복사했어요':'복사가 막혔어요. 글자를 직접 선택해 복사해 주세요',ok?'ok':'bad');setTimeout(function(){b.textContent=o},1600)}
 function fb(){var ok=false;try{var ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.appendChild(ta);ta.select();ok=document.execCommand('copy');document.body.removeChild(ta)}catch(e){}done(ok)}
 if(navigator.clipboard&&navigator.clipboard.writeText&&window.isSecureContext){navigator.clipboard.writeText(text).then(function(){done(true)},fb)}else fb()}
function mbA(label,url){var a=el('a',null,label+' ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';mbSt(a,'display:inline-block;margin:3px 8px 3px 0;padding:6px 11px;border-radius:8px;background:#eef2ff;border:1px solid #c7d2fe;color:#3730a3;font-weight:700;font-size:12.5px;text-decoration:none');return a}
function mbLinks(list){var d=el('div');mbSt(d,'margin:4px 0 2px');(list||[]).forEach(function(x){d.appendChild(mbA(x[0],x[1]))});return d}
function mbVal(label,val,note){var w=el('div');mbSt(w,'margin:7px 0');var r=el('div');mbSt(r,'display:flex;gap:8px;align-items:center;flex-wrap:wrap');var l=el('span',null,label);mbSt(l,'min-width:150px;font-size:12.5px;font-weight:700;color:#334155');r.appendChild(l);
 var c=el('code',null,val);mbSt(c,'flex:1;min-width:200px;padding:6px 9px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:7px;font-size:12.5px;word-break:break-all;user-select:all');r.appendChild(c);
 var b=bt('📋 복사','bt3',function(){mbCopy(val,b)});r.appendChild(b);w.appendChild(r);
 if(note){var n=el('div','m',note);mbSt(n,'margin:2px 0 0 2px');w.appendChild(n)}return w}
function mbEnv(name,isSet,opt,hint){var r=el('div');mbSt(r,'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0');
 var s=el('span',null,isSet?'✅ 설정됨':(opt?'⬜ 선택':'⬜ 아직'));mbSt(s,'min-width:78px;font-size:12px;font-weight:800;color:'+(isSet?'#15803d':(opt?'#64748b':'#b45309')));r.appendChild(s);
 var c=el('code',null,name);mbSt(c,'padding:5px 9px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:7px;font-size:12.5px;user-select:all');r.appendChild(c);
 var b=bt('📋 이름 복사','bt3',function(){mbCopy(name,b)});r.appendChild(b);if(hint){r.appendChild(el('span','m',hint))}return r}
function mbStep(n,title){var d=el('div');mbSt(d,'display:flex;gap:10px;margin:12px 0');var nn=el('span',null,String(n));mbSt(nn,'flex:0 0 26px;height:26px;border-radius:50%;background:#3151d3;color:#fff;font-weight:800;font-size:13px;display:flex;align-items:center;justify-content:center');d.appendChild(nn);
 var bd=el('div');mbSt(bd,'flex:1;min-width:0');bd.appendChild(el('b',null,title));d.appendChild(bd);d._b=bd;return d}
function mbBox(title,badge,kind,open){var d=document.createElement('details');d.open=!!open;mbSt(d,'margin:10px 0;border:1px solid #e2e8f0;border-radius:12px;padding:0 14px;background:#fff');
 var sm=document.createElement('summary');mbSt(sm,'cursor:pointer;padding:11px 0;font-weight:800;font-size:14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap');sm.appendChild(document.createTextNode(title));
 var bg=el('span',null,badge);mbSt(bg,'font-size:12px;font-weight:800;border-radius:999px;padding:2px 10px;'+(kind==='ok'?'background:#dcfce7;color:#166534':(kind==='warn'?'background:#fef3c7;color:#92400e':'background:#fee2e2;color:#991b1b')));sm.appendChild(bg);d.appendChild(sm);
 var bd=el('div');mbSt(bd,'padding:0 0 12px');d.appendChild(bd);d._b=bd;return d}
function mbNote(t,kind){var n=el('div',null,t);mbSt(n,'margin:8px 0;padding:8px 11px;border-radius:9px;font-size:12.5px;line-height:1.6;'+(kind==='warn'?'background:#fffbeb;border:1px solid #fde68a;color:#92400e':'background:#f8fafc;border:1px solid #e2e8f0;color:#475569'));return n}
function mbRenderCard(p,S){var G=S.guide,c=el('div','c');c.appendChild(el('b',null,'🧭 먼저 알아 두세요 — Render 환경변수 넣는 법'));
 c.appendChild(el('p','note','메일·SNS 로그인 키는 보안을 위해 코드나 화면이 아니라 Render 서버의 환경변수에만 넣어요. 아래 모든 안내의 ‘Render에 넣을 값’은 같은 방법으로 넣어요.'));
 var bx=mbBox('📌 Render 환경변수 넣는 방법 (처음 한 번만 읽으면 돼요)','1~3분','ok',false);var b=bx._b;
 b.appendChild(mbLinks([['Render 대시보드 열기','https://dashboard.render.com/']]));
 [['내 웹 서비스 선택','대시보드 목록에서 이 사이트의 서비스(예: stock-analyzer-mini)를 눌러요.'],['Environment 메뉴','왼쪽 메뉴의 [Environment]를 누르고 [Add Environment Variable]을 눌러요.'],
  ['Key / Value 입력','Key 칸에는 아래의 환경변수 이름(📋 이름 복사)을, Value 칸에는 발급받은 값을 붙여 넣어요. 값 앞뒤에 따옴표·공백이 없어야 해요.'],
  ['저장하고 다시 배포','[Save, rebuild, and deploy](또는 [Save Changes])를 누르면 1~3분 뒤 서버가 새로 떠요. 그 뒤 이 화면을 새로고침(F5)하면 ✅ 로 바뀌어요.']].forEach(function(x,i){var st=mbStep(i+1,x[0]);st._b.appendChild(el('div','m',x[1]));b.appendChild(st)});
 b.appendChild(mbNote('⚠ 키 값은 다른 사람에게 보내거나 채팅·메일에 붙여 넣지 마세요. 이 화면은 키 값을 표시하지 않고, ‘설정됨/아직’만 보여 줘요.','warn'));
 c.appendChild(bx);p.appendChild(c)}
function mbMailCard(p,S){var G=S.guide,c=el('div','c');
 var none=S.mail==='none',sand=!none&&S.sandbox_sender,okm=!none&&!sand;
 c.appendChild(el('b',null,'✉ 메일 발송 상태 · 설정 안내 (회원가입 인증번호 메일)'));
 var st=el('p','note',none?'❌ 메일 발송이 설정되지 않았어요. 아래 ①~⑤를 따라 하면 돼요. (설정 전에는 [이메일 인증]을 끄면 인증 없이 가입은 가능해요)':(sand?'⚠ 메일은 나가지만 보내는 주소가 시험용(resend.dev)이에요. 이 주소는 Resend 가입 메일로만 보낼 수 있어서 다른 사람 인증 메일은 실패해요. 아래 ②~④로 내 도메인을 연결하세요.':'✅ '+(S.mail==='resend'?'Resend':'SMTP')+' 로 발송 · 보내는 주소: '+S.mail_from));
 c.appendChild(st);
 var bx=mbBox('📖 설정 방법 단계별 안내',okm?'설정 완료':(sand?'도메인 연결 필요':'설정 필요'),okm?'ok':(sand?'warn':'bad'),!okm);var b=bx._b;
 var s1=mbStep(1,'Resend 가입 (무료)');s1._b.appendChild(el('div','m','메일 발송 서비스예요. 무료는 하루 100통까지라 인증 메일용으로 충분해요.'));s1._b.appendChild(mbLinks([['Resend 가입하기','https://resend.com/signup']]));b.appendChild(s1);
 var s2=mbStep(2,'내 도메인 추가 → DNS 등록 → Verified 확인');s2._b.appendChild(el('div','m','다른 사람에게도 메일을 보내려면 내 도메인 인증이 필요해요. Resend [Domains] → [Add Domain]에 아래 도메인을 입력해요.'));
 s2._b.appendChild(mbVal('Resend에 입력할 도메인',G.root,'이 사이트 주소('+G.host+')에서 추정한 값이에요. 다른 도메인을 쓰려면 그 도메인으로 바꿔 입력하세요.'));
 s2._b.appendChild(el('div','m','추가하면 Resend가 TXT·MX 같은 DNS 레코드 몇 줄을 보여 줘요. 그 값을 도메인을 산 곳(가비아·후이즈·Cloudflare 등)의 DNS 관리 화면에 그대로 추가하고, Resend에서 [Verify DNS Records]를 눌러 ‘Verified’가 될 때까지 기다려요(몇 분~몇 시간).'));
 s2._b.appendChild(mbLinks([['Resend 도메인 관리','https://resend.com/domains']]));b.appendChild(s2);
 var s3=mbStep(3,'API 키 만들기 → RESEND_API_KEY');s3._b.appendChild(el('div','m','[API Keys] → [Create API Key] → 권한 ‘Sending access’로 만들고, 화면에 한 번만 보이는 키(re_ 로 시작)를 복사해요. Render 환경변수에 아래 이름으로 넣어요.'));
 s3._b.appendChild(mbLinks([['Resend API 키 만들기','https://resend.com/api-keys']]));s3._b.appendChild(mbEnv('RESEND_API_KEY',G.env.RESEND_API_KEY,false,'값: 방금 복사한 키'));b.appendChild(s3);
 var s4=mbStep(4,'보내는 주소 → MAIL_FROM');s4._b.appendChild(el('div','m','도메인이 Verified가 되면, 아래 값을 Render 환경변수 MAIL_FROM의 Value로 넣어요. (no-reply 대신 다른 앞부분도 괜찮아요)'));
 s4._b.appendChild(mbEnv('MAIL_FROM',G.env.MAIL_FROM,false,'값은 아래 줄'));s4._b.appendChild(mbVal('MAIL_FROM 값',G.suggest_from,'큰따옴표 없이 그대로 붙여 넣어요.'));b.appendChild(s4);
 var s5=mbStep(5,'Render에 저장하고 다시 배포');s5._b.appendChild(el('div','m','위 ‘Render 환경변수 넣는 방법’대로 두 값을 넣고 저장해요. 1~3분 뒤 이 화면을 새로고침해요.'));
 var rb=bt('🔄 상태 다시 확인','bt2',function(){mbLoad(p)});s5._b.appendChild(rb);b.appendChild(s5);
 var s6=mbStep(6,'테스트 메일로 확인');s6._b.appendChild(el('div','m','받을 주소를 확인하고 버튼을 누르면 시험 메일 1통을 보내요(20초에 한 번).'));
 var row=el('div','bar');var ti=el('input');ti.type='email';ti.value=G.admin_email||'';ti.placeholder='받을 메일 주소';ti.style.width='260px';row.appendChild(ti);var out=el('div','note','');
 row.appendChild(bt('✉ 테스트 메일 보내기','bt',function(){out.textContent='보내는 중…';apiJ('/admin/api/member/mailtest',{to:ti.value}).then(function(j){if(j.error){out.textContent='❌ '+j.error;return}out.textContent='✅ '+j.to+' 로 보냈어요. 받은편지함(또는 스팸함)을 확인하세요.'})}));
 s6._b.appendChild(row);s6._b.appendChild(out);b.appendChild(s6);
 b.appendChild(mbNote('도움말: Render 무료 서버는 SMTP 포트를 막아서 Resend(https 방식)를 써요. 메일이 스팸함으로 가면 도메인 인증(Verified)이 됐는지, MAIL_FROM의 도메인이 인증한 도메인과 같은지 확인하세요.'));
 c.appendChild(bx);p.appendChild(c)}
function mbSnsCard(p,S){var G=S.guide,c=el('div','c');c.appendChild(el('b',null,'🔗 SNS 로그인 상태 · 설정 안내 (네이버·구글·카카오)'));
 c.appendChild(el('p','note','각 서비스 개발자 센터에서 앱을 만들고 → 아래 [입력할 값]을 복사해 붙여 넣고 → 발급된 키를 Render 환경변수에 넣으면, 로그인 화면의 버튼이 자동으로 켜져요. 하나씩만 해도 돼요.'));
 (G.providers||[]).forEach(function(x){var bx=mbBox((x.ok?'✅ ':'⬜ ')+x.label+' 로그인',x.ok?'사용 중':'설정 필요',x.ok?'ok':'bad',!x.ok);var b=bx._b;
  b.appendChild(mbLinks(x.links));
  x.steps.forEach(function(t,i){var st=mbStep(i+1,t);b.appendChild(st)});
  var vb=el('div');mbSt(vb,'margin:14px 0 4px');vb.appendChild(el('b',null,'📝 개발자 센터에 입력할 값 (복사해서 그대로 붙여 넣기)'));b.appendChild(vb);
  x.values.forEach(function(v){b.appendChild(mbVal(v[0],v[1],v[2]))});
  var eb=el('div');mbSt(eb,'margin:14px 0 4px');eb.appendChild(el('b',null,'🔑 Render에 넣을 값 (발급된 키를 Value에 붙여 넣기)'));b.appendChild(eb);
  x.env.forEach(function(e){b.appendChild(mbEnv(e.name,e.set,e.opt,e.hint))});
  var lines=x.env.filter(function(e){return !e.opt}).map(function(e){return e.name+'=여기에_복사한_값'}).join('\n');
  var cb=bt('📋 한 번에 붙여넣기용 .env 형식 복사','bt3',function(){mbCopy(lines,cb)});mbSt(cb,'margin:6px 0');b.appendChild(cb);
  b.appendChild(el('div','m','Render [Environment]의 [Add from .env]에 붙여 넣은 뒤 ‘여기에_복사한_값’만 실제 값으로 바꿔도 돼요.'));
  b.appendChild(mbNote('💡 '+x.tip));
  b.appendChild(bt('🔄 상태 다시 확인','bt2',function(){mbLoad(p)}));
  c.appendChild(bx)});
 var ob=mbBox('⚙ 로그인 후 돌아오는 주소가 다르게 나올 때 (선택)','필요할 때만','ok',false);
 ob._b.appendChild(el('div','m','위 Redirect URI/Callback URL의 도메인이 실제 사이트 주소와 다르면(예: onrender.com 으로 표시) 아래 환경변수를 Render에 추가하세요. 이 사이트의 정식 주소를 값으로 써요.'));
 ob._b.appendChild(mbEnv('MEMBER_OAUTH_BASE_URL',G.oauth_base_set,true,'정식 주소 고정'));ob._b.appendChild(mbVal('MEMBER_OAUTH_BASE_URL 값',G.base,'끝에 / 없이'));c.appendChild(ob);
 c.appendChild(mbNote('카카오는 일반 앱에서 이메일 제공 권한을 받기 어려워요. 이메일을 못 받으면 ‘kakao_번호@sns.local’ 내부 아이디로 가입돼요(비즈 앱 승인 뒤 환경변수 KAKAO_REQUEST_EMAIL=1 을 넣으면 이메일을 요청해요).'));
 p.appendChild(c)}
function mbLoad(p){MB.p=p;api('/admin/api/member/state').then(function(j){if(cur!=='mem')return;MB.S=j;mbDraw(p);mbList()})}
function mbDraw(p){p.innerHTML='';var S=MB.S,s=S.settings,st=S.stats;
 var top=el('div','c');top.appendChild(el('b',null,'👤 회원 관리'));
 top.appendChild(el('p','note','이메일을 아이디로 쓰는 회원가입·로그인 기능이에요. 가입한 회원은 [🧭 메뉴 관리]에서 정한 회원 단계에 따라 메뉴가 보여요. 비밀번호는 암호화돼 저장되어 운영자도 볼 수 없어요.'));
 var g=el('div','grid');[['전체 회원',st.total],['오늘 가입',st.new_today],['최근 7일 가입',st.new_7d],['지금 접속(30분)',st.online],['차단',st.blocked],['인증메일(24h)',st.mails_24h]].forEach(function(x){var k=el('div','k');k.appendChild(el('small',null,x[0]));k.appendChild(el('b',null,String(x[1])));g.appendChild(k)});top.appendChild(g);p.appendChild(top);
 mbRenderCard(p,S);mbMailCard(p,S);mbSnsCard(p,S);
 var sc=el('div','c');sc.appendChild(el('b',null,'⚙ 회원 설정'));var f=el('div','bar');
 function chk(label,on){var l=el('label');l.style.cssText='display:flex;gap:6px;align-items:center';var c=el('input');c.type='checkbox';c.checked=!!on;l.appendChild(c);l.appendChild(document.createTextNode(label));f.appendChild(l);return c}
 var cOn=chk('회원 기능 사용(끄면 로그인·가입 버튼이 사라져요)',s.on),cSg=chk('새 회원가입 받기',s.signup),cVf=chk('이메일 인증 사용(권장)',s.verify);
 var f2=el('div','bar');f2.appendChild(el('span','m','신규 회원 기본 단계'));var sel=el('select');S.levels.forEach(function(l){var o=el('option',null,l.name);o.value=l.id;sel.appendChild(o)});sel.value=s.default_level;f2.appendChild(sel);
 f2.appendChild(el('span','m','인증 메일 하루 상한'));var cap=el('input');cap.type='number';cap.min=0;cap.max=5000;cap.value=s.mail_cap;cap.style.width='90px';f2.appendChild(cap);f2.appendChild(el('span','m','통 (Resend 무료는 하루 100통)'));
 sc.appendChild(f);sc.appendChild(f2);
 sc.appendChild(bt('💾 회원 설정 저장','bt',function(){apiJ('/admin/api/member/settings',{on:cOn.checked,signup:cSg.checked,verify:cVf.checked,default_level:sel.value,mail_cap:parseInt(cap.value,10)}).then(function(j){if(j.error){toast(j.error);return}MB.S=j;toast('회원 설정을 저장했어요');mbDraw(p);mbList()})}));
 p.appendChild(sc);
 var lc=el('div','c');lc.appendChild(el('b',null,'📋 회원 목록'));var bar=el('div','bar');var qi=el('input');qi.placeholder='이메일 검색';qi.value=MB.q;qi.style.width='220px';
 qi.onkeydown=function(e){if(e.key==='Enter'){MB.q=qi.value;MB.page=1;mbList()}};bar.appendChild(qi);bar.appendChild(bt('🔍 검색','bt2',function(){MB.q=qi.value;MB.page=1;mbList()}));lc.appendChild(bar);
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
  var dl=bt('🗑 삭제','bt3',function(){if(!confirm(r.email+' 회원을 삭제할까요? 되돌릴 수 없어요.'))return;apiJ('/admin/api/member/delete',{email:r.email}).then(function(x){if(x.error){toast(x.error);return}toast('삭제했어요');mbLoad(MB.p)})});dl.style.marginLeft='6px';ac.appendChild(dl);tr.appendChild(ac);
  t.appendChild(tr)});tw.appendChild(t);box.appendChild(tw);
 var pages=Math.max(1,Math.ceil(j.total/j.per));var nv=el('div','bar');nv.appendChild(el('span','m',j.total+'명 · '+j.page+' / '+pages+' 쪽'));
 var pv=bt('◀ 이전','bt3',function(){MB.page--;mbList()});pv.disabled=j.page<=1;var nx=bt('다음 ▶','bt3',function(){MB.page++;mbList()});nx.disabled=j.page>=pages;nv.appendChild(pv);nv.appendChild(nx);box.appendChild(nv)})}
"""


def register():
    C.register_table_hook(_ensure_tables)
    C.register_admin_tab("mem", "👤 회원", ADMIN_JS, "mbLoad")
    C.set_viewer_level_hook(_viewer_level_hook)
    return bp
