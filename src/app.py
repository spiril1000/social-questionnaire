"""social-questionnaire: joke questionnaire sites ("Customer Experience Survey" after a hookup,
an exit interview when ghosted, ...). One image, many sites: every site is its own container
running this app with a different PRESET and its own /config and /data volumes. See README.md.

Pages
    /                   the survey, one question per screen (survey.html + static/swipe.js)
    /thanks             the "ticket received" page after submitting
    /admin              responses (view, edit, delete)
    /admin/questions    question editor
    /admin/settings     colour scheme, logo, texts and reset-to-preset
    /admin/preview      the survey with unsaved settings or an unsaved question; stores nothing

Storage
    CONFIG_DIR/questions.json   the questions, seeded from the preset on first start
    CONFIG_DIR/settings.json    only what was changed in the admin; the rest comes from the preset
    DATA_DIR/responses.db       SQLite, one row per submitted survey

Environment
    PRESET           which preset seeds this site (presets.py), default "hookup"
    PRODUCTION       "true" turns on the admin login (always set in Docker)
    ADMIN_USER / ADMIN_PASSWORD   the admin login (HTTP Basic auth)
    N8N_WEBHOOK_URL  optional: every submission is POSTed here as JSON
    PROXY_COUNT      reverse proxies in front of the app (default 1); 0 when it's exposed directly
    CONFIG_DIR / DATA_DIR         set by the Dockerfile; locally they default to .localdata/<preset>
"""

import copy
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, Response, abort, g, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from presets import BASE_SETTINGS, CONTACT_METHODS, MAX_TEXT, PRESETS, TYPES, get_preset
from themes import LOGOS, SCHEMES, scheme_css

try:
    import cairosvg  # renders the home-screen icon PNGs; needs the cairo library (installed in the Docker image)
except Exception:  # no cairo (e.g. some Windows setups): the app manifest falls back to an SVG icon
    cairosvg = None


##########################################################################################
# Configuration

PRESET = os.environ.get("PRESET", "hookup")
PRODUCTION = os.environ.get("PRODUCTION", "").lower() == "true"
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
PROXY_COUNT = int(os.environ.get("PROXY_COUNT", "1"))

# Local runs (python src/app.py) keep each preset's files in <repo>/.localdata/<preset>
LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".localdata", PRESET)
CONFIG_DIR = os.environ.get("CONFIG_DIR", os.path.join(LOCAL_DIR, "config"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(LOCAL_DIR, "data"))
QUESTIONS_PATH = os.path.join(CONFIG_DIR, "questions.json")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
DB_PATH = os.path.join(DATA_DIR, "responses.db")

RATE_LIMIT = 5  # survey submissions per IP...
RATE_WINDOW = 3600  # ...per this many seconds
TICKET_OFFSET = 4800  # ticket number = response id + this, so we look like a busy business
MAX_LIST_ITEMS = 20  # options / rows per question
MAX_COMMENT = 500  # the optional comment under a question
CONTACT_LABELS = {key: label for key, label, _ in CONTACT_METHODS}

app = Flask(__name__)
# Trust the X-Forwarded-* headers set by that many reverse proxies (for the client IP used by the
# rate limit, and https). With PROXY_COUNT=0 they're ignored, so clients can't fake them.
if PROXY_COUNT > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=PROXY_COUNT, x_proto=PROXY_COUNT, x_host=PROXY_COUNT)

if not PRODUCTION:
    app.logger.warning("PRODUCTION is not 'true': /admin has NO login. Fine locally, never on the server.")


##########################################################################################
# Storage: responses in SQLite, questions and settings in JSON files

def init_storage():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,   -- ISO 8601, UTC
                for_name TEXT,              -- the ?for=Name the link was sent with
                answers TEXT NOT NULL,      -- JSON: {question id: answer}
                comments TEXT               -- JSON: {question id: comment}, for questions with a comment field
            )"""
        )
        # Databases created before comments existed
        if "comments" not in {row[1] for row in db.execute("PRAGMA table_info(responses)")}:
            db.execute("ALTER TABLE responses ADD COLUMN comments TEXT")


init_storage()


def get_db():
    """One SQLite connection per request, closed again by close_db()."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


_store_lock = threading.Lock()  # wrap read-modify-write of the JSON files in this


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return copy.deepcopy(default)


def save_json(path, data):
    # Write to a temp file and swap it in, so a crash never leaves half a file
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_questions():
    return load_json(QUESTIONS_PATH, get_preset(PRESET)["questions"])


def save_questions(questions):
    save_json(QUESTIONS_PATH, questions)


def load_settings():
    # The preset's values first, so settings added in later versions show up on existing sites
    return {**get_preset(PRESET)["settings"], **load_json(SETTINGS_PATH, {})}


def icon_version(settings):
    """Changes whenever the logo or colours change, so browsers fetch the new icons (?v=...)."""
    return f"{settings['logo']}-{settings['color_scheme']}"


##########################################################################################
# Reading forms

def parse_int(value, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def clean_name(value):
    """The ?for=Name a survey link was sent with."""
    return (value or "").strip()[:50]


def split_lines(text):
    """Non-empty lines of a textarea, for options and rating rows."""
    items = [line.strip()[:200] for line in (text or "").splitlines()]
    return [item for item in items if item][:MAX_LIST_ITEMS]


def parse_answers(form, questions):
    """Validate a submitted survey (or the admin's edit of one) against the questions.

    Field names: <id> for most types, <id>_<row index> for each rating-grid row, and
    <id>_handle for the username/number of a contact question.
    Returns (answers, ids of required questions without an answer).
    """
    answers, missing = {}, []
    for q in questions:
        qid, qtype = q["id"], q["type"]
        if qtype == "stars":
            value = parse_int(form.get(qid), 1, 5)
        elif qtype == "nps":
            value = parse_int(form.get(qid), 0, 10)
        elif qtype == "choice":
            value = form.get(qid) if form.get(qid) in q["options"] else None
        elif qtype == "matrix":
            ratings = {row: parse_int(form.get(f"{qid}_{i}"), 1, 5) for i, row in enumerate(q["rows"])}
            value = {row: rating for row, rating in ratings.items() if rating is not None} or None
        elif qtype == "text":
            value = (form.get(qid) or "").strip()[:MAX_TEXT] or None
        elif qtype == "contact":
            method = form.get(qid)
            handle = (form.get(f"{qid}_handle") or "").strip()[:200]
            if method == "none":
                value = {"method": CONTACT_LABELS["none"]}
            elif method in CONTACT_LABELS and handle:
                value = {"method": CONTACT_LABELS[method], "handle": handle}
            else:
                value = None
        else:
            value = None

        if value is None and q.get("required"):
            missing.append(qid)
        answers[qid] = value
    return answers, missing


def parse_comments(form, qids):
    """The optional comments (field <id>_comment) under the given questions: {question id: text}."""
    comments = {}
    for qid in qids:
        text = (form.get(f"{qid}_comment") or "").strip()[:MAX_COMMENT]
        if text:
            comments[qid] = text
    return comments


def answers_to_form(answers, questions):
    """The reverse of parse_answers(): stored answers as form values, to prefill the admin edit form."""
    method_keys = {label: key for key, label, _ in CONTACT_METHODS}
    values = {}
    for q in questions:
        qid, value = q["id"], answers.get(q["id"])
        if value is None:
            continue
        if q["type"] == "matrix" and isinstance(value, dict):
            for i, row in enumerate(q["rows"]):
                if row in value:
                    values[f"{qid}_{i}"] = str(value[row])
        elif q["type"] == "contact" and isinstance(value, dict):
            values[qid] = method_keys.get(value.get("method"), "other")
            values[f"{qid}_handle"] = value.get("handle", "")
        elif not isinstance(value, dict):
            values[qid] = str(value)
    return values


def parse_question_form(form):
    """A question from the admin editor. Returns (question, error messages)."""
    errors = []
    label = (form.get("label") or "").strip()[:300]
    qtype = form.get("type")
    if not label:
        errors.append("The question needs some text.")
    if qtype not in TYPES:
        errors.append("Pick a question type.")
        qtype = "text"

    question = {"type": qtype, "label": label}
    subtitle = (form.get("subtitle") or "").strip()[:300]
    if subtitle:
        question["subtitle"] = subtitle
    if form.get("required"):
        question["required"] = True
    if form.get("comment"):
        question["comment"] = True
    if qtype == "choice":
        question["options"] = split_lines(form.get("options"))
        if len(question["options"]) < 2:
            errors.append("Multiple choice needs at least two options (one per line).")
        elif len(set(question["options"])) != len(question["options"]):
            errors.append("Options must be unique.")
    elif qtype == "matrix":
        question["rows"] = split_lines(form.get("rows"))
        if not question["rows"]:
            errors.append("A rating grid needs at least one row (one per line).")
    elif qtype == "text" and form.get("multiline"):
        question["multiline"] = True
    return question, errors


def new_question_id(label, existing):
    """A readable, unique id like "best_snack_3f2a"; answers are stored under it."""
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:24] or "q"
    while True:
        qid = f"{base}_{secrets.token_hex(2)}"
        if qid not in existing:
            return qid


def parse_settings_form(form):
    """Settings from the settings page (or a preview). Empty fields and unknown schemes/logos
    keep their current value."""
    current = load_settings()
    allowed = {"color_scheme": SCHEMES, "logo": LOGOS}
    settings = {}
    for key in BASE_SETTINGS:
        value = (form.get(key) or "").strip()[:500]
        valid = value in allowed[key] if key in allowed else bool(value)
        settings[key] = value if valid else current[key]
    return settings


##########################################################################################
# Templates

@app.context_processor
def inject_theme():
    """Available in every template: the settings, the colour scheme and the preset name."""
    settings = g.get("settings_override") or load_settings()  # the settings preview uses unsaved values
    return {
        "settings": settings,
        "scheme": SCHEMES.get(settings["color_scheme"]) or SCHEMES["flame"],
        "scheme_css": scheme_css(settings["color_scheme"]),
        "icon_version": icon_version(settings),
        "png_icons": cairosvg is not None,
        "preset": PRESET,
    }


@app.template_filter("answer")
def format_answer(value, qtype=None):
    """A stored answer as text for the admin. Copes with answers saved before a question's type was edited."""
    if isinstance(value, dict) and "method" in value:  # contact details
        return f"{value['method']}: {value['handle']}" if value.get("handle") else value["method"]
    if isinstance(value, dict):  # rating grid
        return "\n".join(f"{row}: {format_answer(rating, 'stars')}" for row, rating in value.items())
    if isinstance(value, int) and qtype == "stars" and 0 <= value <= 5:
        return "★" * value + "☆" * (5 - value)
    if isinstance(value, int) and qtype == "nps":
        return f"{value}/10"
    return str(value)


@app.template_filter("zip")
def zip_filter(values, labels):
    """(value, label) pairs for <select> options, e.g. range(1, 6) | zip(...)."""
    return list(zip(values, labels))


##########################################################################################
# Small helpers

_submissions = defaultdict(deque)  # ip -> timestamps of recent submissions
_submissions_lock = threading.Lock()


def rate_limited(ip):
    """True if this IP already submitted RATE_LIMIT times in the last RATE_WINDOW seconds."""
    now = time.time()
    with _submissions_lock:
        times = _submissions[ip]
        while times and now - times[0] > RATE_WINDOW:
            times.popleft()
        if len(times) >= RATE_LIMIT:
            return True
        times.append(now)
        return False


def notify_n8n(payload):
    """POST a submission to n8n in the background. A failing webhook never breaks the survey."""
    if not N8N_WEBHOOK_URL:
        return

    def send():
        try:
            req = urllib.request.Request(
                N8N_WEBHOOK_URL,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as exc:
            app.logger.warning("n8n webhook failed: %s", exc)

    threading.Thread(target=send, daemon=True).start()


def require_admin(view):
    """Protect an admin route with HTTP Basic auth (only when PRODUCTION=true)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not PRODUCTION:
            return view(*args, **kwargs)
        if not ADMIN_USER or not ADMIN_PASSWORD:
            abort(503, "Admin credentials are not configured")
        auth = request.authorization
        if (
            auth is None
            or not hmac.compare_digest(auth.username or "", ADMIN_USER)
            or not hmac.compare_digest(auth.password or "", ADMIN_PASSWORD)
        ):
            return Response(
                "Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Quality Assurance"'}
            )
        # The browser sends Basic auth automatically, so refuse form posts coming from other sites
        if request.method == "POST":
            origin = request.headers.get("Origin") or request.headers.get("Referer")
            if not origin or urlsplit(origin).netloc != request.host:
                abort(403, "Cross-site request blocked")
        return view(*args, **kwargs)
    return wrapper


def admin_done(endpoint, anchor=None):
    """Response after an admin action: 204 for the in-page fetch() calls from admin.js; without
    JavaScript, a redirect back to the item (#anchor) so the page doesn't jump to the top."""
    if request.headers.get("X-Requested-With") == "fetch":
        return "", 204
    return redirect(url_for(endpoint, _anchor=anchor))


def render_survey(questions, for_name, values=None, errors=(), start=0, **extra):
    """The survey. start: the slide swipe.js opens on (0 is the intro), for previewing one question."""
    return render_template(
        "survey.html", questions=questions, for_name=for_name, values=values or {}, errors=errors,
        contact_methods=CONTACT_METHODS, start=start, **extra,
    )


##########################################################################################
# Survey

@app.get("/")
def survey():
    return render_survey(load_questions(), clean_name(request.args.get("for")))


@app.post("/submit")
def submit():
    # Honeypot: a hidden field only bots fill in. Pretend it worked.
    if request.form.get("website"):
        return redirect(url_for("thanks", ticket=TICKET_OFFSET))

    questions = load_questions()
    for_name = clean_name(request.form.get("for"))
    answers, missing = parse_answers(request.form, questions)
    if missing:  # only happens without JavaScript; swipe.js checks before submitting
        return render_survey(questions, for_name, values=request.form, errors=missing), 400
    comments = parse_comments(request.form, [q["id"] for q in questions if q.get("comment")])

    if rate_limited(request.remote_addr or "unknown"):
        return render_template("thanks.html", ticket=None, rate_limited=True), 429

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = get_db()
    cur = db.execute(
        "INSERT INTO responses (created_at, for_name, answers, comments) VALUES (?, ?, ?, ?)",
        (created_at, for_name or None, json.dumps(answers), json.dumps(comments) if comments else None),
    )
    db.commit()
    ticket = TICKET_OFFSET + cur.lastrowid

    # Shortcut fields (rating, nps, contact, comment) use the preset question ids, so they are
    # empty when those questions were deleted; "answers" + "questions" always have everything.
    notify_n8n({
        "survey": PRESET,
        "ticket": ticket,
        "for_name": for_name or None,
        "rating": answers.get("overall"),
        "nps": answers.get("nps"),
        "contact": answers.get("contact"),
        "comment": answers.get("comment"),
        "answers": answers,
        "comments": comments,
        "questions": {q["id"]: q["label"] for q in questions},
        "submitted_at": created_at,
    })
    return redirect(url_for("thanks", ticket=ticket))


@app.get("/thanks")
def thanks():
    return render_template("thanks.html", ticket=parse_int(request.args.get("ticket"), 0, 10**9), rate_limited=False)


@app.get("/healthz")
def healthz():
    return "ok"


##########################################################################################
# Icons and the installable admin app. Public on purpose: browsers fetch these without the
# admin login, and they contain nothing but the name, colours and logo.

def icon_response(body, mimetype):
    return Response(body, mimetype=mimetype, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.svg")
def favicon():
    return icon_response(render_template("icon.svg", app_icon=False), "image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico():
    return redirect(url_for("favicon"))


@app.get("/admin/icon.svg")
def app_icon_svg():
    return icon_response(render_template("icon.svg", app_icon=True), "image/svg+xml")


@app.get("/admin/icon-<int:size>.png")
def app_icon_png(size):
    if size not in (180, 192, 512) or cairosvg is None:
        abort(404)
    svg = render_template("icon.svg", app_icon=True).encode()
    return icon_response(cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size), "image/png")


@app.get("/admin/manifest.webmanifest")
def admin_manifest():
    """Makes /admin installable as a phone app (start page and scope /admin, so not the survey)."""
    settings = load_settings()
    version = icon_version(settings)
    if cairosvg:
        icons = [
            {"src": url_for("app_icon_png", size=size, v=version), "sizes": f"{size}x{size}",
             "type": "image/png", "purpose": "any maskable"}
            for size in (192, 512)
        ]
    else:
        icons = [{"src": url_for("app_icon_svg", v=version), "sizes": "any",
                  "type": "image/svg+xml", "purpose": "any maskable"}]
    manifest = {
        "id": "/admin",
        "name": f"{settings['brand_name']} admin",
        "short_name": f"{PRESET.title()} admin",
        "start_url": "/admin",
        "scope": "/admin",
        "display": "standalone",
        "background_color": "#f3f4f7",
        "theme_color": (SCHEMES.get(settings["color_scheme"]) or SCHEMES["flame"])["c1"],
        "icons": icons,
    }
    return Response(json.dumps(manifest), mimetype="application/manifest+json")


##########################################################################################
# Admin: responses

@app.get("/admin")
@require_admin
def admin():
    questions = load_questions()
    known = {q["id"] for q in questions}
    responses = []
    for row in get_db().execute("SELECT * FROM responses ORDER BY id DESC"):
        answers = json.loads(row["answers"])
        comments = json.loads(row["comments"] or "{}")
        responses.append({
            "id": row["id"],
            "ticket": TICKET_OFFSET + row["id"],
            "created_at": row["created_at"],
            "for_name": row["for_name"],
            "answers": answers,
            "comments": comments,
            # Answers (and comments) to questions that have since been deleted are still shown
            "orphans": {k: answers.get(k) for k in {**answers, **comments}
                        if k not in known and (answers.get(k) is not None or k in comments)},
        })
    return render_template("admin.html", responses=responses, questions=questions)


@app.route("/admin/responses/<int:rid>", methods=["GET", "POST"])
@require_admin
def admin_response_edit(rid):
    db = get_db()
    row = db.execute("SELECT * FROM responses WHERE id = ?", (rid,)).fetchone()
    if row is None:
        abort(404)
    questions = load_questions()
    stored = json.loads(row["answers"])
    stored_comments = json.loads(row["comments"] or "{}")
    # A comment field for questions that have one, or that got a comment before it was turned off
    commentable = [q["id"] for q in questions if q.get("comment") or q["id"] in stored_comments]

    if request.method == "POST":
        # Same validation as the survey, but nothing is required. Answers to deleted questions
        # aren't on the form, so they are kept as they were.
        answers = parse_answers(request.form, questions)[0]
        known = {q["id"] for q in questions}
        answers = {**{k: v for k, v in stored.items() if k not in known}, **answers}
        comments = {k: v for k, v in stored_comments.items() if k not in commentable}
        comments.update(parse_comments(request.form, commentable))
        db.execute(
            "UPDATE responses SET for_name = ?, answers = ?, comments = ? WHERE id = ?",
            (clean_name(request.form.get("for_name")) or None, json.dumps(answers),
             json.dumps(comments) if comments else None, rid),
        )
        db.commit()
        return redirect(url_for("admin", _anchor=f"r-{rid}"))

    return render_template(
        "admin_response_edit.html", rid=rid, ticket=TICKET_OFFSET + rid, for_name=row["for_name"] or "",
        questions=questions, values=answers_to_form(stored, questions), contact_methods=CONTACT_METHODS,
        commentable=commentable, comments=stored_comments,
    )


@app.post("/admin/responses/<int:rid>/delete")
@require_admin
def admin_response_delete(rid):
    db = get_db()
    db.execute("DELETE FROM responses WHERE id = ?", (rid,))
    db.commit()
    return admin_done("admin")


##########################################################################################
# Admin: questions

@app.get("/admin/questions")
@require_admin
def admin_questions():
    return render_template("admin_questions.html", questions=load_questions(), types=TYPES)


@app.route("/admin/questions/new", methods=["GET", "POST"])
@app.route("/admin/questions/<qid>", methods=["GET", "POST"])
@require_admin
def admin_question_edit(qid=None):
    current = next((q for q in load_questions() if q["id"] == qid), None)
    if qid is not None and current is None:
        abort(404)
    is_new = current is None

    if request.method == "GET":
        return render_template(
            "admin_question_edit.html", question=current or {"type": "stars"}, is_new=is_new, types=TYPES, errors=[],
        )

    question, errors = parse_question_form(request.form)
    if errors:
        return render_template(
            "admin_question_edit.html", question=question, is_new=is_new, types=TYPES, errors=errors,
        ), 400

    with _store_lock:
        questions = load_questions()
        if is_new:
            question["id"] = new_question_id(question["label"], {q["id"] for q in questions})
            questions.append(question)
        else:
            question["id"] = qid  # keep the id, so existing answers stay linked
            questions = [question if q["id"] == qid else q for q in questions]
        save_questions(questions)
    return redirect(url_for("admin_questions", _anchor=f"q-{question['id']}"))


@app.post("/admin/questions/<qid>/delete")
@require_admin
def admin_question_delete(qid):
    with _store_lock:
        save_questions([q for q in load_questions() if q["id"] != qid])
    return admin_done("admin_questions")


@app.post("/admin/questions/<qid>/move")
@require_admin
def admin_question_move(qid):
    step = -1 if request.form.get("direction") == "up" else 1
    with _store_lock:
        questions = load_questions()
        index = next((i for i, q in enumerate(questions) if q["id"] == qid), None)
        if index is not None and 0 <= index + step < len(questions):
            questions[index], questions[index + step] = questions[index + step], questions[index]
            save_questions(questions)
    return admin_done("admin_questions", anchor=f"q-{qid}")


@app.post("/admin/questions/reset")
@require_admin
def admin_questions_reset():
    with _store_lock:
        save_questions(copy.deepcopy(get_preset(PRESET)["questions"]))
    return redirect(url_for("admin_questions"))


##########################################################################################
# Admin: settings

@app.route("/admin/settings", methods=["GET", "POST"])
@require_admin
def admin_settings():
    saved = request.method == "POST"
    if saved:
        with _store_lock:
            save_json(SETTINGS_PATH, parse_settings_form(request.form))
    presets = []  # for the reset dialog
    for key in PRESETS:
        preset_settings = get_preset(key)["settings"]
        presets.append({"key": key, "settings": preset_settings, "scheme": SCHEMES[preset_settings["color_scheme"]]})
    return render_template(
        "admin_settings.html", schemes=SCHEMES, logos=LOGOS, scheme_css_for=scheme_css, presets=presets,
        saved=saved, reset_to=request.args.get("reset"),
    )


@app.post("/admin/settings/reset")
@require_admin
def admin_settings_reset():
    """Reset the settings (and optionally the questions) to any preset, not just this site's own."""
    name = request.form.get("preset")
    name = name if name in PRESETS else PRESET
    with _store_lock:
        if name == PRESET:
            if os.path.exists(SETTINGS_PATH):
                os.remove(SETTINGS_PATH)  # no overrides: back to this site's preset
        else:
            save_json(SETTINGS_PATH, get_preset(name)["settings"])
        if request.form.get("questions"):
            save_questions(copy.deepcopy(get_preset(name)["questions"]))
    return redirect(url_for("admin_settings", reset=name))


##########################################################################################
# Admin: preview

@app.route("/admin/preview", methods=["GET", "POST"])
@require_admin
def admin_preview():
    """The survey (or its thank-you page) as it would look, opened in a new tab by the Preview
    buttons. Nothing is stored:
    - the questions page opens it as is (GET)
    - the settings page posts its form with preview=settings, to use those unsaved settings
    - the question editor posts its form with preview=question (and ?qid= when editing), to show
      the unsaved question in its place, starting on that question
    The settings travel along as JSON in the preview's own form, and submitting it only shows
    the thank-you page."""
    form = request.form
    source = form if form.get("preview") == "settings" else load_settings()
    if "settings_json" in form:
        try:
            source = json.loads(form["settings_json"])
        except ValueError:
            source = {}
    g.settings_override = parse_settings_form(source if isinstance(source, dict) else {})
    preview_json = json.dumps(g.settings_override)
    if form.get("page") == "thanks":
        return render_template("thanks.html", ticket=TICKET_OFFSET + 1, rate_limited=False, preview_json=preview_json)

    questions, start = load_questions(), 0
    if form.get("preview") == "question":
        question = parse_question_form(form)[0]
        qid = request.args.get("qid")
        index = next((i for i, q in enumerate(questions) if q["id"] == qid), None)
        if index is None:  # a new question goes last
            question["id"] = "preview"
            questions.append(question)
            index = len(questions) - 1
        else:
            question["id"] = qid
            questions[index] = question
        start = index + 1  # slide 0 is the intro
    return render_survey(questions, "Alex", preview_json=preview_json, start=start)


##########################################################################################
# Running locally: `python src/app.py` (or F5 in VS Code). In Docker, gunicorn imports `app` instead.

def lan_ip():
    """This PC's address on the local network. Nothing is sent; connect() on UDP only picks a route."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":  # print once, not again on every auto-reload
        ip = lan_ip()
        print(f"\n  {PRESET} questionnaire running locally (no admin login)")
        print(f"    This PC:     http://localhost:{port}/?for=Test")
        if ip:
            print(f"    Your phone:  http://{ip}:{port}/?for=Test")
            print(f"    Admin:       http://{ip}:{port}/admin")
        print()
    # 0.0.0.0 so phones on the same Wi-Fi can connect. use_debugger=False: Flask's in-browser
    # debugger would let anyone on the network run code on this PC.
    app.run(host="0.0.0.0", port=port, debug=True, use_debugger=False)
