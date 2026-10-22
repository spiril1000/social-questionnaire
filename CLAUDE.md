# CLAUDE.md

Guidance for Claude Code in this repo. The README is the user-facing documentation; this file covers what isn't obvious from it.

## What this is
`social-questionnaire` is a joke questionnaire web app: a "Customer Experience Survey" after a hookup, a ghosting "Exit Interview", a "Post-Date Survey". It's published as the Docker image `ghcr.io/spiril1000/social-questionnaire`.
- **One image, many sites:** every site is its own container with a `PRESET` env var, plus its own `/config` volume (`questions.json`, `settings.json`) and `/data` volume (`responses.db`, SQLite).
- **Stack:** Flask + Jinja + vanilla CSS/JS. There's no build step and no frontend framework, and it should stay that way.

## Layout
- `src/app.py`: all routes, storage, validation and helpers. Read the module docstring first; the file is split into commented sections.
- `src/presets.py`: `PRESETS` (hookup, ghosted, date), `BASE_SETTINGS` (every admin-editable setting with its default), `TYPES` (question types) and `CONTACT_METHODS`.
- `src/themes.py`: 5 colour `SCHEMES` and the `LOGOS` list. The logo SVG paths live in `templates/_logo.html`.
- `src/templates/`:
  - `base_swipe.html` + `survey.html` / `thanks.html`: the public pages
  - `base.html` + `admin_*.html`: the admin
  - `icon.svg`: the favicon and app icon
- `src/static/`:
  - `swipe.css` / `swipe.js`: survey, one card per question
  - `admin.css` / `admin.js`: in-place move and delete
  - `install.js`: the phone install banner
- `tests/test_app.py`: pytest with Flask's test client. The `make_app` fixture reloads `app` with env overrides, because config is read at import time.

## Commands (Windows, from the repo root)
- Tests: `.venv\Scripts\python -m pytest`. Run these after every change.
- Run locally: **F5** in VS Code (`.vscode/launch.json`), or set `PRESET` and `PORT` and run `.venv\Scripts\python src\app.py`.
  - Ports 8000/8001/8002 are used for hookup/ghosted/date.
  - There's no admin login locally (`PRODUCTION` isn't set).
  - Data goes to `.localdata/<preset>/` (gitignored). It holds the user's own test data, so don't delete it.
  - The terminal prints a LAN URL for testing on a phone.
- Python: Inkscape's bundled Python is first on the user's PATH. Always use `.venv\Scripts\python`, never a bare `python`, for app and test commands.
- Docker Desktop usually isn't running locally. The image is built and tested by GitHub Actions.

## Conventions
- **Mobile first, for both the survey and the admin.** The user mainly uses the admin on their phone. Use touch targets ≥ 44px, put hover styles inside `@media (hover: hover)`, and use sticky save bars.
- **Colours come only from the scheme's CSS variables** (`--c1..--c4`, `--glow`, `--shade`), set on `<html>` by the base templates. Don't hardcode accent colours.
- **Progressive enhancement:** the survey and admin forms work without JavaScript. Admin actions that use fetch (`data-ajax`) get `204` back for `X-Requested-With: fetch`, and a redirect to an `#anchor` otherwise (`admin_done()`).
- **Form field names are shared** between `survey.html`, `admin_response_edit.html` and `parse_answers()`:
  - `<id>` for most types
  - `<id>_<row index>` for a rating grid
  - `<id>_handle` for contact details
  - `<id>_comment` for the optional comment under a question with `"comment": true`. Comments are stored in their own `comments` column (JSON), not in `answers`, and `parse_comments()` reads them.
- **New settings:** add a default in `BASE_SETTINGS`, a `field(...)` in `admin_settings.html`, and use `{{ settings.x }}` where it's shown. Existing sites pick up the default automatically through `load_settings()`.
- **Security must stay:**
  - Admin Basic auth only applies when `PRODUCTION=true`, which the Dockerfile sets.
  - Admin POSTs require a same-origin `Origin` or `Referer`.
  - The honeypot field, the per-IP rate limit (`PROXY_COUNT` decides which proxy headers to trust), and the text length caps.
  - The local dev server binds `0.0.0.0` with `use_debugger=False`.
- **Previews store nothing:** `/admin/preview` renders the survey with unsaved settings (`preview=settings`) or an unsaved question (`preview=question`, `?qid=`), and its form posts back to itself to show the thank-you page.
- **Public endpoints by design:** `/favicon.svg`, `/admin/icon*` and `/admin/manifest.webmanifest`, because phones fetch them without logging in.
- **Comment density:** match the existing code, which has short "why" comments and section headers. Keep the README updated when behaviour changes.
- **No personal data in this repo.** The defaults use neutral "Acme …" brands. The owner's own branding lives in their sites' admin settings.

## Releases and the homelab
- GitHub Actions (`.github/workflows/docker-publish.yml`) runs the tests, then builds amd64 + arm64 images:
  - `main` publishes `:latest` and `:sha-…`
  - a tag `vX.Y.Z` publishes `:X.Y.Z` and `:X.Y`
- The owner's homelab repo is `C:\Users\Andreas\Documents\Code\Congo`.
  - It runs three sites (`services/social/{hookup,ghosted,date}`) from `:latest`, at `<site>.spiril1000.dk` behind https-portal.
  - Watchtower updates them automatically.
  - Congo's `services/social/README.md` documents adding sites there.
- Commits: only when asked. End commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
