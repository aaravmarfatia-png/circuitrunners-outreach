# CircuitRunners Outreach

[![Release](https://img.shields.io/github/v/release/aaravmarfatia-png/circuitrunners-outreach?display_name=tag)](https://github.com/aaravmarfatia-png/circuitrunners-outreach/releases)
[![Download site](https://img.shields.io/badge/downloads-website-2b8fff)](https://aaravmarfatia-png.github.io/circuitrunners-outreach/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Windows-lightgrey)](https://aaravmarfatia-png.github.io/circuitrunners-outreach/)

A desktop app that creates **personalized Gmail drafts** for school outreach for the Wheeler High School CircuitRunners Robotics Team. It never sends email — it only writes drafts to your Gmail Drafts folder for you to review and send.

**Download:** https://aaravmarfatia-png.github.io/circuitrunners-outreach/

## What it does

- Fills a message template per school type (Elementary / Middle / Response / Post-Demo) with the recipient, sender, and school name.
- CCs the team coordinators on every draft.
- Attaches demo photos for Elementary/Middle outreach.
- Creates the message as a Gmail **draft** — you always review and send yourself.

## Install

See the [download page](https://aaravmarfatia-png.github.io/circuitrunners-outreach/) for macOS (`.dmg`) and Windows (MSI build kit).

The apps are unsigned, so the first launch needs a one-time approval:
- **macOS:** right-click the app -> Open -> Open (or System Settings -> Privacy & Security -> Open Anyway).
- **Windows:** if SmartScreen appears, More info -> Run anyway.

On first run you provide your own Google OAuth client (`credentials.json`) and sign in. The app shows the steps.

## Data handling

- **Reads:** the contacts CSV you choose and the local photos you add.
- **Writes:** Gmail **drafts** only — never sends.
- **Stores locally (per-user):** your `credentials.json`, OAuth token, photos, and settings, under your user data folder.
- **Scope:** requests only `https://www.googleapis.com/auth/gmail.compose` (create/manage drafts; cannot send).

## Develop / build from source

Requires Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest            # run the test suite
.venv/bin/python gui.py     # run the app locally
```

Build installers:
- **macOS (.dmg / .app):** PyInstaller — see the packaging notes and `CircuitRunners Outreach.spec`.
- **Windows (.msi):** run `build_windows.bat` from the Windows build kit on a Windows PC (cx_Freeze via `setup.py`).

## Project layout

| Path | Purpose |
|------|---------|
| `outreach_drafts.py` | Core logic: auth, templates, MIME building, draft creation |
| `gui.py` | Desktop GUI (tkinter) |
| `tests/` | pytest + hypothesis test suite |
| `docs/` | GitHub Pages download site |
| `setup.py` | cx_Freeze config for the Windows `.msi` |

## Contributing

Feature work happens on `feature/*` branches. Open a pull request against `main`. Please keep the test suite green (`pytest`).

## License

[MIT](./LICENSE)
