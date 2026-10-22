# social-questionnaire

Tongue-in-cheek questionnaire sites to send to someone afterwards. Think a "Customer Experience Survey" after a hookup, an "Exit Interview" when you've been ghosted, or a "Post-Date Survey" after a date. Each one is presented as a swipeable, full-screen mobile survey, with a mobile-first admin panel for reading the responses.

One Docker image runs any number of sites. Each site is its own container, with its own questions, texts, colours, logo and responses.

```bash
docker run -d -p 8000:8000 -e PRESET=ghosted -e ADMIN_USER=admin -e ADMIN_PASSWORD=change-me \
  -v ./config:/config -v ./data:/data ghcr.io/spiril1000/social-questionnaire:latest
```
Then open http://localhost:8000/?for=Alex for the survey and http://localhost:8000/admin for the admin.

## Features

- **Survey:**
  - one question per screen, with swipe-style card animations and an animated gradient background
  - a back button, progress bars and auto-advance after tapping an answer
  - personal links: `?for=Alex` greets them by name
- **Question types:** star rating, multiple choice, rating grid, 0–10 score, free text, and contact details (Instagram, Snapchat, Facebook, phone, other, or "don't contact me", plus their username or number). Any question can have a small subtitle under it and an optional comment box under the answers.
- **Three presets** (`hookup`, `ghosted`, `date`) with their own questions and jokes. Pick one per site and change everything afterwards in the admin.
- **Mobile-first admin:**
  - read, edit and delete responses
  - share the survey link (optionally with their name) straight from the phone's share menu
  - add, edit, reorder, preview and delete questions
  - 5 colour schemes, 5 logos and every text on the survey, with a live preview and reset-to-preset
- **Installable admin:** on a phone the admin can be added to the home screen as an app. It opens on `/admin`, never the survey.
- **Notifications (optional):** each submission can be POSTed as JSON to a webhook, e.g. [n8n](https://n8n.io) → Telegram/Discord.
- **Small and self-contained:** Flask + SQLite, no external services, no JavaScript build step, works without JavaScript too.

## Quick start with Docker Compose

1. Download [`docker-compose.yml`](docker-compose.yml) and [`.env.example`](.env.example) into a folder.
2. Copy `.env.example` to `.env` and set `ADMIN_PASSWORD`.
3. Run `docker compose up -d`.
4. Visit http://localhost:8000/admin and log in with `ADMIN_USER` / `ADMIN_PASSWORD`.

Questions and settings are stored in `./config`, and responses in `./data`.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `PRESET` | `hookup` | Starting questions, texts, colours and logo: `hookup`, `ghosted` or `date`. It's only used to seed a new site and by the admin's reset buttons. |
| `ADMIN_USER`, `ADMIN_PASSWORD` | – | Login for `/admin` (HTTP Basic auth). **Required**: without them the admin refuses to open. |
| `N8N_WEBHOOK_URL` | empty | Optional. Every submission is POSTed here as JSON (see [Webhook](#webhook)). |
| `PROXY_COUNT` | `1` | How many reverse proxies sit in front of the app. They set `X-Forwarded-For`, which is used for the client IP and HTTPS detection. Use `0` if the app is reachable directly. |
| `PUID`, `PGID` | `1000` | The user and group the app runs as. They also own `/config` and `/data`. |
| `PRODUCTION` | `true` | Turns on the admin login. Leave it on. It's only `false` when running from source for local testing. |

| Volume | Contents |
| --- | --- |
| `/config` | `questions.json` (the questions) and `settings.json` (what you changed on the settings page) |
| `/data` | `responses.db` (SQLite) |

Both are created on first start. Back them up together.

## Running several sites

Run one container per site, each with its own `PRESET`, name and volumes:

```yaml
services:
  hookup:
    image: ghcr.io/spiril1000/social-questionnaire:latest
    environment: [PRESET=hookup]
    env_file: .env
    volumes: [./hookup/config:/config, ./hookup/data:/data]
    ports: ["8000:8000"]
  ghosted:
    image: ghcr.io/spiril1000/social-questionnaire:latest
    environment: [PRESET=ghosted]
    env_file: .env
    volumes: [./ghosted/config:/config, ./ghosted/data:/data]
    ports: ["8001:8000"]
```

A `PRESET` that doesn't exist starts as a copy of `hookup`. That's fine for a new kind of site: rename everything in the admin.

## Behind a reverse proxy

The app listens on port 8000 and works behind nginx, Traefik, Caddy and similar, on a subdomain or its own domain. It isn't built for a sub-path.
- With exactly one proxy in front, keep `PROXY_COUNT=1`. That lets the rate limit see the real client IP.
- Installing the admin as a phone app requires **HTTPS**.

## The admin

| Page | |
| --- | --- |
| `/admin` | **Share the survey:** type their name (optional) and tap Share to open the phone's share menu with the `?for=Name` link (on a computer the link is copied). Below that, the responses, newest first. Edit or delete them. Answers to questions you've since deleted are kept and labelled. |
| `/admin/questions` | Add, edit, reorder and delete questions. Changes go live immediately. Each question can have a subtitle and a comment field, with its own placeholder text or the default from Settings. **Preview** opens the survey without storing anything; in the question editor it shows your unsaved question and starts on it. |
| `/admin/settings` | Colour scheme, logo, company name and every text. **Preview** shows unsaved changes in a new tab, and nothing you submit there is stored. **Reset settings to a preset…** can also replace the questions. |

Phones show an install banner on the admin pages:
- **Android/Chrome:** an Install button.
- **iPhone/Safari:** instructions for Share → *Add to Home Screen*.

The home-screen icon is your logo on your colour scheme.

## Webhook

If `N8N_WEBHOOK_URL` is set, each submission is POSTed to it in the background. If the webhook fails, the submission is still saved.

```json
{
  "survey": "ghosted",
  "ticket": 4801,
  "for_name": "Alex",
  "rating": 4,
  "nps": 2,
  "contact": { "method": "Instagram", "handle": "@alex" },
  "comment": "...",
  "answers": { "overall": 4, "reason": "Witness protection", "...": "..." },
  "comments": { "overall": "Great vibes, questionable playlist" },
  "questions": { "overall": "How would you rate your experience before the disappearance?", "...": "..." },
  "submitted_at": "2026-10-22T12:00:00+00:00"
}
```
`rating`, `nps`, `contact` and `comment` are shortcuts for the preset questions with those ids. They're empty if you delete those questions. `answers` and `questions` always contain everything. `comments` has the text from the comment fields of questions that have one, by question id.

## Security

- **Admin login:** the admin uses HTTP Basic auth.
  - Use it over HTTPS.
  - Admin form posts from other websites are rejected.
- **Public endpoints:** the icons and the app manifest (`/favicon.svg`, `/admin/icon*`, `/admin/manifest.webmanifest`) are public, because phones fetch them without logging in. They contain only the name, colours and logo.
- **Survey spam protection:**
  - a hidden honeypot field
  - at most 5 submissions per IP per hour
  - free text capped at 2000 characters
- **Container:** it runs as `PUID:PGID`, not root.

## Development

The code is plain Flask with Jinja templates, plus vanilla CSS and JavaScript. There's no build step.

```
src/
  app.py         routes, storage, validation (overview at the top)
  presets.py     the presets: questions, texts, question types, contact methods
  themes.py      colour schemes and the list of logos
  templates/     survey, thank-you and admin pages, icons
  static/        swipe.css/js (survey), admin.css/js, install.js (install banner)
tests/           pytest, using Flask's test client
```

### Run it locally
```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt        # Windows: .venv\Scripts\pip ...
PRESET=ghosted PORT=8001 .venv/bin/python src/app.py  # or F5 in VS Code (.vscode/launch.json)
```
- There's no admin login when running from source, because `PRODUCTION` isn't set.
- Data goes to `.localdata/<preset>/`.
- The terminal prints a `http://192.168.x.x:8000` link, so you can try the survey on your phone over the same Wi-Fi.
- On Windows, the PNG app icons need a cairo DLL on the `PATH`, for example the one bundled with Inkscape. Without it the app falls back to an SVG icon.

### Tests
```bash
.venv/bin/python -m pytest
```

### Where to change things

| To… | Change |
| --- | --- |
| Add or change a preset | `PRESETS` in `src/presets.py`. Only list the settings that differ from `BASE_SETTINGS`. Question ids must be unique, since answers are stored under them. |
| Add a setting (a new text) | a default in `BASE_SETTINGS`, a `field(...)` in `admin_settings.html`, and `{{ settings.<name> }}` where it's shown. Existing sites get the default automatically. |
| Add a colour scheme | `SCHEMES` in `src/themes.py` |
| Add a logo | `LOGOS` in `src/themes.py`, plus its SVG path (24×24 grid) in `logo_paths()` in `templates/_logo.html` |
| Add a question type | `TYPES` (`presets.py`), `parse_answers()` and `answers_to_form()` (`app.py`), its markup in `survey.html` and `admin_response_edit.html`, `TYPE_ICONS` in `_icons.html`, and `static/swipe.js` if it needs special step logic |

### Releases

[GitHub Actions](.github/workflows/docker-publish.yml) runs the tests and builds the image for `linux/amd64` and `linux/arm64`:
- a push to `main` publishes `:latest`
- a tag `v1.2.3` publishes `:1.2.3` and `:1.2`

```bash
git tag v1.0.0 && git push origin v1.0.0
```
GitHub makes a new package private on its first push. Make it public once under the package's **Package settings → Change visibility**.

## License

[MIT](LICENSE)
