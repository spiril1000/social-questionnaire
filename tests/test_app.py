"""Tests for the questionnaire app, using Flask's test client (no server or browser needed).

Every test gets a fresh app with its own temporary /config and /data, the admin login turned on
(PRODUCTION=true, admin/secret) and the "hookup" preset.
"""

import base64
import importlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}
SAME_ORIGIN = {**AUTH, "Origin": "http://localhost"}  # admin POSTs must come from the site itself
FETCH = {**SAME_ORIGIN, "X-Requested-With": "fetch"}  # how admin.js posts

# A complete hookup survey (only "overall" is required)
FORM = {
    "for": "Alex", "overall": "5", "source": "Destiny", "amenities_0": "4", "amenities_2": "1",
    "nps": "9", "duration": "About right", "return": "Absolutely", "comment": "<b>Breakfast</b> lacking",
    "contact": "instagram", "contact_handle": "@alex", "name": "A",
}


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """Returns a function that (re)loads the app module with the given env overrides."""
    def load(**env):
        defaults = {
            "PRESET": "hookup", "PRODUCTION": "true", "ADMIN_USER": "admin", "ADMIN_PASSWORD": "secret",
            "N8N_WEBHOOK_URL": "", "PROXY_COUNT": "1",
            "CONFIG_DIR": str(tmp_path / "config"), "DATA_DIR": str(tmp_path / "data"),
        }
        for key, value in {**defaults, **env}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        import app
        return importlib.reload(app)  # config is read at import time
    return load


@pytest.fixture
def m(make_app):
    return make_app()


@pytest.fixture
def client(m):
    return m.app.test_client()


def stored_responses(m):
    with closing(sqlite3.connect(m.DB_PATH)) as db:
        return [(rid, for_name, json.loads(answers))
                for rid, for_name, answers in db.execute("SELECT id, for_name, answers FROM responses ORDER BY id")]


# --- Survey ---------------------------------------------------------------------------------

def test_survey_greets_by_name(client):
    r = client.get("/?for=Alex")
    assert r.status_code == 200
    assert b"Dear valued customer" in r.data and b">Alex<" in r.data


def test_submit_saves_answers_and_shows_ticket(m, client):
    r = client.post("/submit", data=FORM)
    assert r.status_code == 302 and r.location.endswith("/thanks?ticket=4801")
    assert b"#4801" in client.get(r.location).data

    [(rid, for_name, answers)] = stored_responses(m)
    assert for_name == "Alex"
    assert answers["overall"] == 5 and answers["nps"] == 9
    assert answers["amenities"] == {"Conversation": 4, "Breakfast offering": 1}
    assert answers["contact"] == {"method": "Instagram", "handle": "@alex"}


def test_missing_required_answer_is_rejected(m, client):
    r = client.post("/submit", data={"for": "Alex"})
    assert r.status_code == 400 and b"data-error" in r.data
    assert stored_responses(m) == []


def test_invalid_values_are_dropped(m, client):
    client.post("/submit", data={**FORM, "overall": "9", "source": "Not an option", "nps": "11"})
    assert stored_responses(m) == []  # overall=9 is invalid, so the required question is unanswered
    client.post("/submit", data={**FORM, "source": "Not an option", "nps": "11"})
    [(_, _, answers)] = stored_responses(m)
    assert answers["source"] is None and answers["nps"] is None


@pytest.mark.parametrize("method, handle, expected", [
    ("snapchat", "sam_snaps", {"method": "Snapchat", "handle": "sam_snaps"}),
    ("phone", "", None),  # a method without the number is no answer
    ("none", "ignored", {"method": "Don't contact me"}),
])
def test_contact_question(m, client, method, handle, expected):
    client.post("/submit", data={**FORM, "contact": method, "contact_handle": handle})
    assert stored_responses(m)[-1][2]["contact"] == expected


def test_honeypot_pretends_success_but_saves_nothing(m, client):
    r = client.post("/submit", data={**FORM, "website": "spam"})
    assert r.status_code == 302
    assert stored_responses(m) == []


def test_rate_limit(client):
    codes = [client.post("/submit", data=FORM).status_code for _ in range(6)]
    assert codes == [302] * 5 + [429]


def test_rate_limit_ignores_forwarded_for_without_proxy(make_app):
    client = make_app(PROXY_COUNT="0").app.test_client()
    codes = [client.post("/submit", data=FORM, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
             for i in range(6)]
    assert codes[-1] == 429  # a faked header doesn't give a fresh IP


def test_n8n_webhook(m, client):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    m.N8N_WEBHOOK_URL = f"http://127.0.0.1:{server.server_port}/hook"
    try:
        client.post("/submit", data=FORM)
        for _ in range(50):
            if received:
                break
            time.sleep(0.05)
    finally:
        server.shutdown()

    [payload] = received
    assert payload["survey"] == "hookup" and payload["ticket"] == 4801 and payload["rating"] == 5
    assert payload["contact"] == {"method": "Instagram", "handle": "@alex"}
    assert payload["questions"]["overall"].startswith("Overall")


def test_failing_webhook_does_not_break_submit(m, client):
    m.N8N_WEBHOOK_URL = "http://127.0.0.1:1/nope"
    assert client.post("/submit", data=FORM).status_code == 302
    assert len(stored_responses(m)) == 1


# --- Admin login ------------------------------------------------------------------------------

def test_admin_requires_login(client):
    assert client.get("/admin").status_code == 401
    wrong = {"Authorization": "Basic " + base64.b64encode(b"admin:wrong").decode()}
    assert client.get("/admin", headers=wrong).status_code == 401
    assert client.get("/admin", headers=AUTH).status_code == 200


def test_admin_refuses_to_open_without_credentials(make_app):
    client = make_app(ADMIN_USER=None, ADMIN_PASSWORD=None).app.test_client()
    assert client.get("/admin").status_code == 503


def test_admin_is_open_when_not_production(make_app):
    client = make_app(PRODUCTION="false").app.test_client()
    assert client.get("/admin").status_code == 200


def test_admin_rejects_cross_site_posts(client):
    data = {"label": "x", "type": "stars"}
    assert client.post("/admin/questions/new", data=data, headers=AUTH).status_code == 403
    assert client.post("/admin/questions/new", data=data, headers={**AUTH, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/admin/questions/new", data=data, headers=SAME_ORIGIN).status_code == 302


@pytest.mark.parametrize("page", ["/admin", "/admin/questions", "/admin/questions/new",
                                  "/admin/questions/overall", "/admin/settings"])
def test_admin_pages_render(client, page):
    assert client.get(page, headers=AUTH).status_code == 200


# --- Admin: responses -------------------------------------------------------------------------

def test_admin_escapes_answers(client):
    client.post("/submit", data=FORM)
    html = client.get("/admin", headers=AUTH).data
    assert b"&lt;b&gt;Breakfast" in html and b"<b>Breakfast" not in html


def test_edit_response_keeps_answers_to_deleted_questions(m, client):
    client.post("/submit", data=FORM)
    [(rid, _, answers)] = stored_responses(m)
    with closing(sqlite3.connect(m.DB_PATH)) as db:
        db.execute("UPDATE responses SET answers = ? WHERE id = ?", (json.dumps({**answers, "gone": "kept"}), rid))
        db.commit()

    r = client.get(f"/admin/responses/{rid}", headers=AUTH)
    assert b'value="@alex"' in r.data and b'value="instagram" selected' in r.data

    r = client.post(f"/admin/responses/{rid}", headers=SAME_ORIGIN, data={
        "for_name": "Robin", "overall": "2", "contact": "phone", "contact_handle": "+1 555 0100", "comment": "",
    })
    assert r.status_code == 302 and r.location.endswith(f"/admin#r-{rid}")
    [(_, for_name, saved)] = stored_responses(m)
    assert for_name == "Robin" and saved["overall"] == 2 and saved["comment"] is None
    assert saved["contact"] == {"method": "Phone number", "handle": "+1 555 0100"}
    assert saved["gone"] == "kept"
    assert b"deleted question" in client.get("/admin", headers=AUTH).data


def test_delete_response(m, client):
    client.post("/submit", data=FORM)
    [(rid, _, _)] = stored_responses(m)
    assert client.post(f"/admin/responses/{rid}/delete", headers=FETCH).status_code == 204
    assert stored_responses(m) == []
    assert client.get(f"/admin/responses/{rid}", headers=AUTH).status_code == 404


# --- Admin: questions -------------------------------------------------------------------------

def test_add_question_validation(client):
    r = client.post("/admin/questions/new", headers=SAME_ORIGIN, data={"label": "", "type": "choice", "options": "one"})
    assert r.status_code == 400 and b"two options" in r.data


def test_add_edit_and_delete_question(m, client):
    r = client.post("/admin/questions/new", headers=SAME_ORIGIN,
                    data={"label": "Best snack?", "type": "choice", "options": "Chips\n\nPizza\n", "required": "on"})
    new = m.load_questions()[-1]
    assert r.status_code == 302 and r.location.endswith(f"#q-{new['id']}")
    assert new["id"].startswith("best_snack_") and new["options"] == ["Chips", "Pizza"] and new["required"]
    assert b"Best snack?" in client.get("/").data
    assert client.post("/submit", data=FORM).status_code == 400  # the new question is required

    client.post(f"/admin/questions/{new['id']}", headers=SAME_ORIGIN, data={"label": "Snack?", "type": "text"})
    assert m.load_questions()[-1] == {"id": new["id"], "type": "text", "label": "Snack?"}

    assert client.post(f"/admin/questions/{new['id']}/delete", headers=FETCH).status_code == 204
    assert new["id"] not in [q["id"] for q in m.load_questions()]


def test_move_question(m, client):
    first, second = [q["id"] for q in m.load_questions()][:2]
    assert client.post(f"/admin/questions/{first}/move", data={"direction": "down"}, headers=FETCH).status_code == 204
    assert [q["id"] for q in m.load_questions()][:2] == [second, first]
    # Without JavaScript: a redirect back to the question, not to the top of the page
    r = client.post(f"/admin/questions/{first}/move", data={"direction": "up"}, headers=SAME_ORIGIN)
    assert r.status_code == 302 and r.location.endswith(f"/admin/questions#q-{first}")


def test_reset_questions(m, client):
    client.post("/admin/questions/overall/delete", headers=FETCH)
    client.post("/admin/questions/reset", headers=SAME_ORIGIN)
    assert m.load_questions() == m.get_preset("hookup")["questions"]


# --- Admin: settings --------------------------------------------------------------------------

def test_save_settings(m, client):
    r = client.post("/admin/settings", headers=SAME_ORIGIN,
                    data={"brand_name": "Love Corp", "intro_title": "Hej", "color_scheme": "ocean", "logo": "ghost"})
    assert r.status_code == 200 and b"Saved" in r.data
    settings = m.load_settings()
    assert settings["brand_name"] == "Love Corp" and settings["color_scheme"] == "ocean"
    assert settings["thanks_title"] == m.get_preset("hookup")["settings"]["thanks_title"]  # empty field kept

    page = client.get("/?for=Bo").data
    assert b"Love Corp" in page and b"Hej" in page and b"#1d4ed8" in page

    client.post("/admin/settings", headers=SAME_ORIGIN, data={"color_scheme": "nope", "logo": "nope"})
    assert m.load_settings()["color_scheme"] == "ocean"


def test_reset_settings_to_another_preset(m, client):
    questions = m.load_questions()
    r = client.post("/admin/settings/reset", headers=SAME_ORIGIN, data={"preset": "ghosted"})
    assert r.status_code == 302 and r.location.endswith("/admin/settings?reset=ghosted")
    assert m.load_settings()["logo"] == "ghost" and m.load_questions() == questions

    client.post("/admin/settings/reset", headers=SAME_ORIGIN, data={"preset": "date", "questions": "on"})
    assert m.load_settings()["logo"] == "wine" and m.load_questions() == m.get_preset("date")["questions"]

    client.post("/admin/settings/reset", headers=SAME_ORIGIN, data={"preset": "unknown"})
    assert m.load_settings() == m.get_preset("hookup")["settings"]


def test_settings_preview_saves_nothing(m, client):
    r = client.post("/admin/settings/preview", headers=SAME_ORIGIN,
                    data={"brand_name": "Unsaved Co", "thanks_title": "Preview thanks!", "color_scheme": "mint"})
    assert r.status_code == 200 and b"Unsaved Co" in r.data and b"#047857" in r.data
    assert m.load_settings()["brand_name"] == m.get_preset("hookup")["settings"]["brand_name"]

    # Submitting the preview shows the thank-you page with the same unsaved settings
    preview_json = json.dumps(m.parse_settings_form({"brand_name": "Unsaved Co", "thanks_title": "Preview thanks!"}))
    r = client.post("/admin/settings/preview", headers=SAME_ORIGIN,
                    data={"page": "thanks", "settings_json": preview_json, "overall": "5"})
    assert b"Preview thanks!" in r.data
    assert stored_responses(m) == []
    assert client.post("/admin/settings/preview", headers=SAME_ORIGIN, data={"settings_json": "not json"}).status_code == 200


# --- Icons and the installable admin ----------------------------------------------------------

def test_favicon_follows_settings(client):
    client.post("/admin/settings", headers=SAME_ORIGIN, data={"color_scheme": "ocean", "logo": "ghost"})
    r = client.get("/favicon.svg")
    assert r.mimetype == "image/svg+xml" and b"#1d4ed8" in r.data and b"evenodd" in r.data
    assert b"favicon.svg?v=ghost-ocean" in client.get("/").data
    assert client.get("/favicon.ico").status_code == 302


def test_manifest_is_public_and_only_on_admin_pages(m, client):
    manifest = json.loads(client.get("/admin/manifest.webmanifest").data)  # no login needed
    assert manifest["start_url"] == "/admin" and manifest["scope"] == "/admin"
    assert manifest["short_name"] == "Hookup admin" and manifest["display"] == "standalone"
    assert client.get(manifest["icons"][0]["src"]).status_code == 200
    assert b'rel="manifest"' in client.get("/admin", headers=AUTH).data
    assert b'rel="manifest"' not in client.get("/").data


def test_manifest_falls_back_to_svg_without_cairo(m, client):
    m.cairosvg = None
    [icon] = json.loads(client.get("/admin/manifest.webmanifest").data)["icons"]
    assert icon["type"] == "image/svg+xml"
    assert client.get("/admin/icon-192.png").status_code == 404


def test_png_icon(m, client):
    if m.cairosvg is None:
        pytest.skip("cairo is not installed")
    r = client.get("/admin/icon-192.png")
    assert r.mimetype == "image/png" and r.data.startswith(b"\x89PNG")
    assert client.get("/admin/icon-999.png").status_code == 404


# --- Presets and themes -----------------------------------------------------------------------

def test_presets_are_complete(m):
    for name in m.PRESETS:
        preset = m.get_preset(name)
        assert set(preset["settings"]) == set(m.BASE_SETTINGS), name
        assert preset["settings"]["color_scheme"] in m.SCHEMES and preset["settings"]["logo"] in m.LOGOS
        ids = [q["id"] for q in preset["questions"]]
        assert len(ids) == len(set(ids)), f"{name}: duplicate question ids"
        assert all(q["type"] in m.TYPES for q in preset["questions"]), name


@pytest.mark.parametrize("preset", ["hookup", "ghosted", "date"])
def test_every_preset_renders(make_app, preset):
    client = make_app(PRESET=preset).app.test_client()
    assert client.get("/?for=Sam").status_code == 200
    assert client.get("/thanks?ticket=4801").status_code == 200
