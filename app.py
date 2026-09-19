"""J-18 Water Pipeline Portal — server.

Local / office PC:   pip install -r requirements.txt && python app.py
Cloud (Render etc.): gunicorn app:app --bind 0.0.0.0:$PORT

Settings come from environment variables first, then config.json next to this
file, then the defaults below. On a public host put the API key and the admin
password in environment variables — config.json is not meant to be committed.
"""
import json, os, re, secrets, hashlib, hmac, datetime, time, urllib.request, urllib.error
from functools import wraps
from collections import defaultdict
from flask import Flask, request, jsonify, session, send_from_directory, redirect, abort
from werkzeug.middleware.proxy_fix import ProxyFix

from store import Store

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.environ.get("CONFIG_PATH") or os.path.join(HERE, "config.json")

DEFAULT_CFG = {
    "host": "0.0.0.0", "port": 8000,
    "admin_user": "admin", "admin_password": "change-me",
    # false = the portal is a closed site: a user ID and password are needed even to look.
    # true  = anyone with the link can read; a sign-in is still needed to change anything.
    "public_read": False,
    "session_days": 14,
    # AI provider: "gemini", "groq", "xai", "anthropic", or "openai_compatible"
    "ai_provider": "gemini",
    "ai_max_tokens": 4000,
    "ai_context_char_limit": 40000,    # ~10k tokens of project data per request
    "ai_temperature": 0.1,
    "ai_daily_limit": 400,             # portal-wide cap, kept under the free-tier day quota
    "gemini_api_key": "", "gemini_model": "gemini-3.1-flash-lite",
    "gemini_thinking_level": "",       # "low" / "minimal" if your model supports it; blank = leave it to Google
    "groq_api_key": "", "groq_model": "openai/gpt-oss-120b",
    "xai_api_key": "", "xai_model": "grok-4-fast",
    "anthropic_api_key": "", "anthropic_model": "claude-sonnet-5",
    "openai_compatible_base_url": "", "openai_compatible_api_key": "", "openai_compatible_model": "",
}

_file_cfg = {}
if os.path.exists(CFG_PATH):
    try:
        _file_cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    except Exception as e:
        print(f"config.json could not be read ({e}); using defaults and environment variables")


def cfg(key):
    """Environment variable, else config.json, else the default — typed like the default."""
    default = DEFAULT_CFG.get(key)
    raw = os.environ.get(key.upper()) or os.environ.get("PORTAL_" + key.upper())
    if raw is None:
        return _file_cfg.get(key, default)
    raw = raw.strip()
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try: return int(float(raw))
        except ValueError: return default
    if isinstance(default, float):
        try: return float(raw)
        except ValueError: return default
    return raw


ST = Store()

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # behind a cloud load balancer
app.json.sort_keys = False   # keep stage/weightage order as authored


def _https_only():
    """Mark the login cookie https-only when the site really is on https.

    Set by hand with HTTPS_ONLY=1/0; otherwise inferred, because a cookie marked
    secure is never sent over plain http and would lock out an office PC on the
    intranet, while leaving it unmarked on a public site is a real exposure.
    """
    raw = os.environ.get("HTTPS_ONLY", _file_cfg.get("https_only"))
    if raw is None:
        return bool(os.environ.get("RENDER") or os.environ.get("FLY_APP_NAME") or os.environ.get("DYNO"))
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


HTTPS_ONLY = _https_only()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(HTTPS_ONLY),
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=int(cfg("session_days") or 14)),
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,
)


# ---------- setup ----------
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def today(): return datetime.date.today().isoformat()


def make_hash(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()


def setting(k, default=None):
    r = ST.one("SELECT v FROM settings WHERE k=?", (k,))
    return r["v"] if r else default


def set_setting(k, v):
    with ST.txn(write=True) as c:
        c.run("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def secret_key():
    """Signing key for the login cookie.

    From SECRET_KEY if it is set. Otherwise one is generated once and kept in the
    database, so a restart does not sign everybody out — which a key generated at
    boot would do on every redeploy.
    """
    env = os.environ.get("SECRET_KEY") or _file_cfg.get("secret_key")
    if env:
        return env
    k = setting("secret_key")
    if not k:
        k = secrets.token_hex(32)
        set_setting("secret_key", k)
    return k


def init_db():
    """Create the tables and, on a brand-new database, put the first admin and the
    shipped baseline in.

    A cloud host starts several workers at the same moment, so every step here has
    to survive another worker doing it a millisecond earlier: the inserts ignore a
    row that is already there rather than crashing the worker.
    """
    ST.init()
    if not ST.one("SELECT 1 AS x FROM users LIMIT 1"):
        s, h = make_hash(str(cfg("admin_password")))
        ST.run("INSERT INTO users(username,name,salt,hash,admin) VALUES(?,?,?,?,1) "
               "ON CONFLICT(username) DO NOTHING", (str(cfg("admin_user")), "Administrator", s, h))
    if not ST.one("SELECT 1 AS x FROM state WHERE id=1"):
        html = open(os.path.join(HERE, "static", "index.html"), encoding="utf-8").read()
        m = re.search(r'<script id="shipped" type="application/json">(.*?)</script>', html, re.S)
        shipped = m.group(1).replace("<\\/", "</")
        json.loads(shipped)  # validate
        ST.run("INSERT INTO state(id,version,doc,saved_by,saved_at) VALUES(1,1,?,?,?) "
               "ON CONFLICT(id) DO NOTHING", (shipped, "shipped", now()))


init_db()
app.secret_key = secret_key()


# ---------- auth ----------
def current_user():
    u = session.get("user")
    if not u:
        return None
    r = ST.one("SELECT username,name,admin FROM users WHERE username=?", (u,))
    return dict(user=r["username"], name=r["name"], admin=bool(r["admin"])) if r else None


def login_required(admin=False):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = current_user()
            if not u:
                return jsonify(error="sign in required"), 401
            if admin and not u["admin"]:
                return jsonify(error="admin only"), 403
            return f(*a, **k)
        return w
    return deco


def may_read():
    return bool(cfg("public_read")) or current_user() is not None


# A wrong password five times in a row from the same address parks that address for
# fifteen minutes. Enough to make guessing passwords over the internet pointless,
# not enough to lock out someone who mistyped.
FAILS = defaultdict(list)
MAX_FAILS, LOCK_SECONDS = 5, 900


def locked_for(ip):
    hits = [t for t in FAILS[ip] if time.time() - t < LOCK_SECONDS]
    FAILS[ip] = hits
    return int(LOCK_SECONDS - (time.time() - hits[0])) if len(hits) >= MAX_FAILS else 0


@app.post("/api/login")
def login():
    ip = request.remote_addr or "?"
    wait = locked_for(ip)
    if wait:
        return jsonify(error=f"too many attempts — try again in {wait // 60 + 1} minute(s)"), 429
    d = request.get_json(force=True, silent=True) or {}
    r = ST.one("SELECT * FROM users WHERE username=?", (str(d.get("user", "")).strip(),))
    ok = False
    if r:
        _, h = make_hash(str(d.get("password", "")), r["salt"])
        ok = hmac.compare_digest(h, r["hash"])
    if not ok:
        FAILS[ip].append(time.time())
        return jsonify(error="user ID or password not recognised"), 401
    FAILS.pop(ip, None)
    session.permanent = True
    session["user"] = r["username"]
    return jsonify(user=dict(user=r["username"], name=r["name"], admin=bool(r["admin"])))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.post("/api/password")
@login_required()
def change_password():
    """Anyone can change their own password, with the current one as proof."""
    d = request.get_json(force=True, silent=True) or {}
    me = current_user()["user"]
    r = ST.one("SELECT * FROM users WHERE username=?", (me,))
    _, h = make_hash(str(d.get("old", "")), r["salt"])
    if not hmac.compare_digest(h, r["hash"]):
        return jsonify(error="current password is not right"), 403
    new = str(d.get("new", ""))
    if len(new) < 8:
        return jsonify(error="new password must be at least 8 characters"), 400
    s, nh = make_hash(new)
    ST.run("UPDATE users SET salt=?,hash=? WHERE username=?", (s, nh, me))
    return jsonify(ok=True)


@app.get("/api/users")
@login_required(admin=True)
def users():
    return jsonify([dict(user=r["username"], name=r["name"], admin=bool(r["admin"]))
                    for r in ST.all("SELECT username,name,admin FROM users ORDER BY username")])


@app.post("/api/users")
@login_required(admin=True)
def add_user():
    d = request.get_json(force=True, silent=True) or {}
    u = str(d.get("user", "")).strip()
    pw = str(d.get("password", ""))
    if not u or not pw:
        return "user ID and password required", 400
    if len(pw) < 8:
        return "password must be at least 8 characters", 400
    if ST.one("SELECT 1 AS x FROM users WHERE username=?", (u,)):
        return "user ID already exists", 400
    s, h = make_hash(pw)
    ST.run("INSERT INTO users(username,name,salt,hash,admin) VALUES(?,?,?,?,?)",
           (u, d.get("name") or u, s, h, 1 if d.get("admin") else 0))
    return jsonify(ok=True)


@app.patch("/api/users/<u>")
@login_required(admin=True)
def reset_pw(u):
    pw = str((request.get_json(force=True, silent=True) or {}).get("password", ""))
    if len(pw) < 8:
        return "password must be at least 8 characters", 400
    s, h = make_hash(pw)
    ST.run("UPDATE users SET salt=?,hash=? WHERE username=?", (s, h, u))
    return jsonify(ok=True)


@app.delete("/api/users/<u>")
@login_required(admin=True)
def del_user(u):
    if u == current_user()["user"]:
        return "cannot remove yourself", 400
    ST.run("DELETE FROM users WHERE username=?", (u,))
    return jsonify(ok=True)


# ---------- pages ----------
@app.get("/")
def index():
    # With public_read off the portal page itself is not served to a stranger: the
    # shipped baseline data sits inside it, so gating it in the browser alone would
    # still hand the project data to anyone who opened the page source.
    if not may_read():
        return redirect("/login")
    return send_from_directory(os.path.join(HERE, "static"), "index.html")


@app.get("/login")
def login_page():
    if current_user():
        return redirect("/")
    return send_from_directory(os.path.join(HERE, "static"), "login.html")


@app.get("/api/health")
def health():
    """For an uptime pinger, and to see at a glance what the server is using."""
    return jsonify(ok=True, at=now(), storage=ST.kind, provider=cfg("ai_provider"),
                   public_read=bool(cfg("public_read")))


# ---------- state ----------
@app.get("/api/state")
def get_state():
    if not may_read():
        return jsonify(error="sign in required"), 401
    r = ST.one("SELECT * FROM state WHERE id=1")
    if request.args.get("meta"):
        return jsonify(version=r["version"], by=r["saved_by"], at=r["saved_at"])
    return jsonify(state=json.loads(r["doc"]), version=r["version"], by=r["saved_by"], at=r["saved_at"],
                   user=current_user(), publicRead=bool(cfg("public_read")))


@app.put("/api/state")
@login_required()
def put_state():
    d = request.get_json(force=True, silent=True) or {}
    u = current_user()["user"]
    with ST.txn(write=True) as c:
        # the row lock is what makes the version check below trustworthy when two
        # people press save in the same second
        r = c.one("SELECT version,doc,saved_by FROM state WHERE id=1" + c.for_update)
        if int(d.get("version", -1)) != r["version"]:
            return jsonify(error="version conflict", state=json.loads(r["doc"]),
                           version=r["version"], by=r["saved_by"]), 409
        v = r["version"] + 1
        js = json.dumps(d["state"], ensure_ascii=False)
        t = now()
        c.run("UPDATE state SET version=?,doc=?,saved_by=?,saved_at=? WHERE id=1", (v, js, u, t))
        c.run("INSERT INTO log(at_ts,username,version,changes) VALUES(?,?,?,?)",
              (t, u, v, json.dumps(d.get("changes") or [], ensure_ascii=False)))
        c.run("INSERT INTO snapshots(version,at_ts,username,doc) VALUES(?,?,?,?)", (v, t, u, js))
        c.run("DELETE FROM snapshots WHERE version < ?", (v - 200,))   # keep the last 200 versions
    return jsonify(version=v)


@app.get("/api/log")
def get_log():
    if not may_read():
        return jsonify(error="sign in required"), 401
    rows = ST.all("SELECT at_ts,username,version,changes FROM log ORDER BY id DESC LIMIT 300")
    return jsonify([dict(at=r["at_ts"], user=r["username"], version=r["version"],
                         changes=json.loads(r["changes"] or "[]")) for r in rows])


@app.get("/api/snapshot/<int:v>")
@login_required(admin=True)
def snapshot(v):
    r = ST.one("SELECT * FROM snapshots WHERE version=?", (v,))
    if not r:
        abort(404)
    return jsonify(state=json.loads(r["doc"]), version=v, at=r["at_ts"], user=r["username"])


@app.get("/api/backup")
@login_required(admin=True)
def backup():
    """One file holding the live data, the change log and the user list (no passwords).

    Download it now and then, or on a schedule: it restores through Import JSON on
    the Settings tab, and it is the copy that does not depend on the host staying up.
    """
    r = ST.one("SELECT * FROM state WHERE id=1")
    out = jsonify(
        exportedAt=now(), version=r["version"],
        state=json.loads(r["doc"]),
        log=[dict(at=x["at_ts"], user=x["username"], version=x["version"], changes=json.loads(x["changes"] or "[]"))
             for x in ST.all("SELECT at_ts,username,version,changes FROM log ORDER BY id DESC LIMIT 2000")],
        users=[dict(user=x["username"], name=x["name"], admin=bool(x["admin"]))
               for x in ST.all("SELECT username,name,admin FROM users ORDER BY username")],
    )
    out.headers["Content-Disposition"] = f'attachment; filename="J18_portal_backup_{today()}.json"'
    return out


# ---------- AI ----------
TASKS = {
    "daily": "Write today's Daily Progress Report summary for circulation to the Engineer-in-Charge: mainline activities posted today and cumulative, HDD status by crossing, documents pending, quantity items needing approval, and points needing attention. Plain prose and short tables; no invented figures.",
    "brief": "Write a one-page management brief on the project status: contract facts, physical progress (mainline weighted %, HDD count/status), executed value vs WO value, the focus list, and the three most important decisions or actions needed from management. No invented figures.",
    "focus": "Go through each item on the focus list. For each, state why it is raised (which rule), what the contractual reference in the data suggests, and the concrete next action with who should do it (IOCL site / contractor / PLHO / higher authority). Be specific to the data.",
    "letter_docs": "Draft a formal letter from IOCL WRPL Koyali (Senior Operations Manager, on behalf of the Engineer-in-Charge) to the contractor listing the documents not yet submitted or pending resubmission with their current stage, the contractual basis (SCC clauses in the reference fields), and a request to submit within a stated period. Leave the period and the letter number as blanks to fill.",
    "letter_qty": "Draft an internal note seeking approval of higher authority for BoQ items whose entered/anticipated quantity exceeds the Work Order quantity by more than the threshold. Show a table: item, WO qty, anticipated qty, variation %, extra value at WO rate (qty difference × rate × (1 − discount)), reason from remarks. State the total financial implication. Do not invent reasons where remarks are blank — mark them as 'reason to be recorded'.",
    "risks": "Identify schedule and execution risks from the data: HDDs without permission or approved drawing, documents stuck in review, pre-project activities not complete, quantity overruns, and the gap between today's date and the scheduled/extended completion date. Rank them and suggest mitigation. Do not invent facts.",
    "ask": "Answer the user's question using only the project data provided. If the data does not contain the answer, say so.",
}
SYSTEM = ("You are an assistant embedded in the project-management portal for IOCL Pipelines Division's project "
          "'Laying of 36\" OD Water Pipeline from Fhajalpur tie-in (Mahi River) to Gujarat Refinery, J-18'. "
          "The user is the IOCL site officer managing the contract. Use only the JSON project data supplied; quote quantities and dates from it exactly; "
          "use Indian number formatting (lakh/crore) for money; keep to the point; never fabricate figures, clause numbers or names not present in the data.")

UA = "J18-Portal/1.1"   # a bare urllib user-agent gets blocked by some CDNs (Cloudflare 1010)

CUT = ("\n\n[The model ran out of room and stopped here. Raise AI_MAX_TOKENS, "
       "or ask for a narrower part of this.]")


def _pick_openai(j):
    """Text plus a note if the reply was truncated; never a silent empty string."""
    ch = (j.get("choices") or [{}])[0]
    txt = ((ch.get("message") or {}).get("content") or "").strip()
    why = ch.get("finish_reason")
    if not txt:
        raise ValueError(f"the model returned no text (finish_reason: {why or 'unknown'})")
    return txt + (CUT if why == "length" else "")


def _pick_gemini(j):
    cand = (j.get("candidates") or [{}])[0]
    parts = ((cand.get("content") or {}).get("parts") or [])
    txt = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    why = cand.get("finishReason")
    if not txt:
        if why == "MAX_TOKENS":
            # A thinking model can spend the whole output allowance before it writes
            # anything. More room, or a lower thinking level, is the fix.
            raise ValueError("the model used its whole output allowance on internal reasoning and wrote nothing "
                             "— raise AI_MAX_TOKENS (try 8000) or set GEMINI_THINKING_LEVEL=low")
        if why == "SAFETY" or why == "PROHIBITED_CONTENT":
            raise ValueError(f"the model declined to answer (finishReason: {why})")
        raise ValueError(f"the model returned no text (finishReason: {why or 'unknown'})")
    return txt + (CUT if why == "MAX_TOKENS" else "")


def _pick_anthropic(j):
    txt = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text").strip()
    if not txt:
        raise ValueError(f"the model returned no text (stop_reason: {j.get('stop_reason') or 'unknown'})")
    return txt + (CUT if j.get("stop_reason") == "max_tokens" else "")


# provider -> (config key prefix, base url, default model). All of these speak the
# OpenAI chat/completions format, so one code path serves them.
OPENAI_STYLE = {
    "groq": ("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "xai": ("xai", "https://api.x.ai/v1", "grok-4-fast"),
    "openai_compatible": ("openai_compatible", "", ""),   # base url from config
}
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _post(url, headers, body, timeout=180):
    """Returns (parsed json, error text). HTTP errors come back with the provider's own words."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode(errors='replace')[:400]}"
    except Exception as e:
        return None, str(e)


def _gemini_variants(system, prompt, mx, temp):
    """Request shapes to try in order, so one unsupported field never kills the answer.

    Field support differs between Gemini model generations: `systemInstruction` is
    accepted by current models and `thinkingConfig` only by the thinking ones. A 400
    on the richer shape falls through to the plainer one instead of surfacing as a
    failed question.
    """
    gen = {"maxOutputTokens": mx, "temperature": temp}
    lvl = str(cfg("gemini_thinking_level") or "").strip()
    base = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if lvl:
        yield {**base, "generationConfig": {**gen, "thinkingConfig": {"thinkingLevel": lvl.upper()}}}
    yield {**base, "generationConfig": gen}
    yield {"contents": [{"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}], "generationConfig": gen}


def call_llm(system, prompt):
    """Returns (text, error). Providers: gemini, groq, xai, anthropic, openai_compatible."""
    prov = str(cfg("ai_provider") or "gemini")
    mx = int(cfg("ai_max_tokens"))
    temp = float(cfg("ai_temperature"))

    if prov == "gemini":
        key = str(cfg("gemini_api_key") or "")
        model = str(cfg("gemini_model") or DEFAULT_CFG["gemini_model"])
        if not key:
            return None, "No Gemini API key configured (set GEMINI_API_KEY)."
        url = f"{GEMINI_BASE}/models/{model}:generateContent"
        headers = {"content-type": "application/json", "x-goog-api-key": key, "user-agent": UA}
        last = None
        for body in _gemini_variants(system, prompt, mx, temp):
            for attempt in (1, 2):                      # one retry: free tiers drop the odd request
                j, err = _post(url, headers, body)
                if j is not None:
                    try:
                        return _pick_gemini(j), None
                    except ValueError as e:
                        return None, f"gemini: {e}"
                if err.startswith("429"):
                    return None, ("Gemini rate limit / daily free quota reached. Wait a minute and ask again. " + err)
                if err.startswith("400") or err.startswith("404"):
                    last = f"gemini API error {err}"
                    break                               # bad field or bad model name: try the next shape
                last = f"gemini API error {err}" if err[:3].isdigit() else f"Could not reach gemini: {err}"
                if attempt == 1:
                    time.sleep(2)
            else:
                continue
        return None, last

    if prov == "anthropic":
        key = str(cfg("anthropic_api_key") or "")
        if not key:
            return None, "No Anthropic API key configured (set ANTHROPIC_API_KEY)."
        url = "https://api.anthropic.com/v1/messages"
        body = {"model": cfg("anthropic_model"), "max_tokens": mx, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"content-type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01", "user-agent": UA}
        pick = _pick_anthropic
    else:
        pfx, base, default_model = OPENAI_STYLE.get(prov, OPENAI_STYLE["groq"])
        key = str(cfg(f"{pfx}_api_key") or "")
        base = str(cfg(f"{pfx}_base_url") or "") or base
        model = str(cfg(f"{pfx}_model") or "") or default_model
        if not key or not base:
            return None, f"No API key / base URL for provider '{prov}'."
        url = base.rstrip("/") + "/chat/completions"
        body = {"model": model, "max_tokens": mx, "temperature": temp,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        headers = {"content-type": "application/json", "authorization": "Bearer " + key, "user-agent": UA}
        pick = _pick_openai

    last = None
    for attempt in (1, 2):
        j, err = _post(url, headers, body)
        if j is not None:
            try:
                return pick(j), None
            except ValueError as e:
                last = f"{prov}: {e}"
        elif err.startswith("429"):
            return None, f"{prov} rate limit reached (free tier). Wait a minute and ask again. {err}"
        else:
            last = f"{prov} API error {err}" if err[:3].isdigit() else f"Could not reach {prov}: {err}"
        if attempt == 1:
            time.sleep(2)
    return None, last


# ---------- context compaction ----------
# The browser sends the whole project as JSON. Sent raw that is ~7,000 tokens on an
# empty project and far more once filled, which trips per-minute token limits on free
# API tiers. So: keep only the sections a task needs, drop empty fields, and write the
# rows as compact lines instead of JSON.

SECTIONS_FOR_TASK = {
    "daily":       ["project", "ml", "mlLog", "hdd", "csw", "focus"],
    "brief":       ["project", "ml", "hdd", "csw", "docs", "boq", "focus"],
    "focus":       ["project", "focus", "pre", "docs", "hdd", "csw", "boq"],
    "letter_docs": ["project", "docs", "pre"],
    "letter_qty":  ["project", "boq"],
    "risks":       ["project", "focus", "pre", "docs", "hdd", "csw", "boq", "ml"],
}
# words in a question that pull a section in
SECTION_HINTS = {
    "pre":   ("pre-project", "mobilis", "security deposit", "agreement", "kick-off", "permission", "noc", "survey", "geotech"),
    "docs":  ("document", "report", "drawing", "submission", "review", "plho", "approval of", "submitted"),
    "hdd":   ("hdd", "shdd", "crossing", "bore", "pilot", "reaming", "pull", "nala", "river", "pond", "nh "),
    "csw":   ("civil", "chamber", "air vent", "scour", "valve pit", "rcc", "location finalis"),
    "ml":    ("mainline", "dpr", "progress", "welding", "trench", "lowering", "hydrotest", "row", "stringing"),
    "mlLog": ("today", "yesterday", "this week", "posted", "log", "daily"),
    "boq":   ("quantity", "qty", "boq", "rate", "value", "variation", "10 %", "10%", "amount", "bill", "sor"),
    "focus": ("attention", "pending", "issue", "problem", "overdue", "focus", "delay", "risk"),
}


def _row(d, skip=()):
    """One row as 'key=value' pairs, empty and noise fields dropped."""
    out = []
    for k, v in d.items():
        if k in skip or v in (None, "", [], {}, False):
            continue
        if isinstance(v, dict):                      # stage maps: name=value, done stages only
            done = ", ".join(f"{kk} {vv}" for kk, vv in v.items() if vv)
            if done: out.append(f"{k}: {done}")
        else:
            s = str(v)
            out.append(f"{k}={s[:160]}")
        if len(out) > 22: break
    return "; ".join(out)


def compact_context(ctx, task, question):
    if not isinstance(ctx, dict):
        return json.dumps(ctx, ensure_ascii=False)[:40000]
    wanted = list(SECTIONS_FOR_TASK.get(task, []))
    if not wanted:                                    # free question: pick by keywords
        q = (question or "").lower()
        wanted = ["project", "focus"]
        for sec, words in SECTION_HINTS.items():
            if any(w in q for w in words) and sec not in wanted:
                wanted.append(sec)
        if len(wanted) <= 2:                          # nothing matched: give the overview
            wanted = ["project", "focus", "ml", "hdd", "csw", "docs"]

    parts = [f"TODAY: {ctx.get('today')}"]
    p = ctx.get("project") or {}
    if "project" in wanted and p:
        parts.append("PROJECT: " + _row(p))
    r = ctx.get("rules") or {}
    parts.append(f"RULES: quantity variation threshold {r.get('thr')}%, document review period {r.get('rev')} d, "
                 f"no-update period {r.get('hdd')} d; document stages: {' > '.join(r.get('stages') or [])}")
    if ctx.get("mlPct") is not None:
        parts.append(f"MAINLINE WEIGHTED PROGRESS: {round(ctx['mlPct'] * 100, 1)} %")

    LIMITS = {"focus": 40, "pre": 30, "docs": 30, "hdd": 40, "csw": 20, "ml": 35, "mlLog": 30, "boq": 45}
    SKIP = {"hdd": ("id", "trigger"), "csw": ("id", "trigger"), "pre": ("id", "trigger"),
            "docs": ("id", "trigger"), "ml": ("id",), "mlLog": ("id", "actId"), "boq": ("id",)}

    def _priority(sec, rows):
        """Most decision-relevant rows first, so a cap never hides what matters."""
        if sec == "boq":       # entered quantities first, biggest variation first
            with_qty = [x for x in rows if x.get("exec") not in (None, "")]
            rest = [x for x in rows if x.get("exec") in (None, "")]
            def var(x):
                try: return abs((x["exec"] - x["qty"]) / x["qty"] * 100)
                except Exception: return 0
            return sorted(with_qty, key=var, reverse=True) + rest
        if sec in ("hdd", "csw"):     # started but unfinished first
            return sorted(rows, key=lambda x: (x.get("pct") in (0, None), -(x.get("pct") or 0)))
        return rows

    for sec in wanted:
        rows = ctx.get(sec)
        if not isinstance(rows, list) or not rows: continue
        rows = _priority(sec, rows)
        n = LIMITS.get(sec, 30)
        lines = [_row(x, SKIP.get(sec, ("id",))) if isinstance(x, dict) else str(x)[:200] for x in rows[:n]]
        head = f"{sec.upper()} ({len(rows)} rows" + (f", first {n} shown" if len(rows) > n else "") + "):"
        parts.append(head + "\n" + "\n".join("- " + l for l in lines if l))
    return "\n\n".join(parts)


def est_tokens(s):
    return len(s) // 4      # rough, good enough to warn on


def ai_quota():
    """(used today, daily cap). The cap is the portal's own, kept under the provider's."""
    cap = int(cfg("ai_daily_limit") or 0)
    r = ST.one("SELECT n FROM ai_usage WHERE day=?", (today(),))
    return int(r["n"]) if r else 0, cap


def ai_count():
    with ST.txn(write=True) as c:
        c.run("INSERT INTO ai_usage(day,n) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET n=ai_usage.n+1", (today(),))


@app.post("/api/ai")
@login_required()
def ai():
    used, cap = ai_quota()
    if cap and used >= cap:
        return jsonify(error=f"The portal's own daily limit of {cap} AI requests is reached "
                             f"(it keeps the free API quota from running out). It resets at midnight."), 429
    d = request.get_json(force=True, silent=True) or {}
    task = TASKS.get(d.get("task"), TASKS["ask"])
    q = (d.get("question") or "").strip()
    ctx = compact_context(d.get("context"), d.get("task"), q)
    budget = int(cfg("ai_context_char_limit"))
    trimmed = False
    if len(ctx) > budget:
        ctx = ctx[:budget] + "\n[...project data trimmed to fit the request limit...]"
        trimmed = True
    prompt = f"{task}\n\n{'User question: ' + q if q else ''}\n\nProject data:\n{ctx}"
    text, err = call_llm(SYSTEM, prompt)
    if err:
        return jsonify(error=err), 502
    ai_count()
    if trimmed:
        text += ("\n\n[Only part of the project data fitted in this request, so ask about one "
                 "area at a time (HDD, civil work, documents, quantities) for a complete answer.]")
    return jsonify(text=text, provider=cfg("ai_provider"), tokens=est_tokens(prompt),
                   used=used + 1, cap=cap)


@app.get("/api/ai/info")
def ai_info():
    prov = str(cfg("ai_provider") or "gemini")
    pfx = OPENAI_STYLE[prov][0] if prov in OPENAI_STYLE else prov
    used, cap = ai_quota()
    return jsonify(provider=prov, model=cfg(f"{pfx}_model"), configured=bool(cfg(f"{pfx}_api_key")),
                   used=used, cap=cap)


@app.get("/api/ai/models")
@login_required()
def ai_models():
    """The model IDs this key can actually call — the cure for a guessed model name."""
    prov = str(cfg("ai_provider") or "gemini")
    if prov == "gemini":
        key = str(cfg("gemini_api_key") or "")
        if not key:
            return jsonify(models=[], note="No API key configured."), 400
        req = urllib.request.Request(f"{GEMINI_BASE}/models?pageSize=200",
                                     headers={"x-goog-api-key": key, "user-agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r).get("models", [])
            ids = sorted(m["name"].split("/")[-1] for m in data
                         if "generateContent" in (m.get("supportedGenerationMethods") or ["generateContent"]))
            return jsonify(models=ids, current=cfg("gemini_model"), provider=prov)
        except Exception as e:
            return jsonify(models=[], note=f"Could not list models: {e}"), 502
    if prov not in OPENAI_STYLE:
        return jsonify(models=[], note=f"Model listing is not available for '{prov}'.")
    pfx, base, _ = OPENAI_STYLE[prov]
    key = str(cfg(f"{pfx}_api_key") or "")
    base = str(cfg(f"{pfx}_base_url") or "") or base
    if not key or not base:
        return jsonify(models=[], note="No API key configured."), 400
    req = urllib.request.Request(base.rstrip("/") + "/models",
                                 headers={"authorization": "Bearer " + key, "user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ids = sorted(m.get("id", "") for m in json.load(r).get("data", []))
        return jsonify(models=ids, current=cfg(f"{pfx}_model"), provider=prov)
    except Exception as e:
        return jsonify(models=[], note=f"Could not list models: {e}"), 502


@app.get("/api/ai/test")
@login_required()
def ai_test():
    """Quick check that the configured provider and key work."""
    text, err = call_llm("Reply with exactly: OK", "Reply with exactly: OK")
    if err:
        return jsonify(ok=False, error=err), 502
    return jsonify(ok=True, provider=cfg("ai_provider"), response=(text or "").strip()[:40])


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or cfg("port") or 8000)
    print(f"Portal running: http://{cfg('host')}:{port}  ·  storage: {ST.describe()}  ·  AI: {cfg('ai_provider')}")
    if str(cfg("admin_password")) == DEFAULT_CFG["admin_password"]:
        print("!! The admin password is still 'change-me'. Sign in and change it on the Settings tab.")
    app.run(host=str(cfg("host")), port=port, debug=False)
