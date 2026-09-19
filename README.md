# J-18 Water Pipeline · Project Portal

A single-screen management view of IOCL Pipelines Division's project *Laying of 36" OD
water pipeline from Fhajalpur tie-in (Mahi River) to Gujarat Refinery — J-18*:
physical progress, HDD and shallow crossings, civil work, documentation, pre-project
activities, BoQ quantities and a focus list of what needs attention — plus an AI
assistant that answers questions and drafts letters from the live data.

**New here? Read [DEPLOY.md](DEPLOY.md).** It takes you from nothing to a working
website, click by click, without assuming any programming.

| I want to… | Read |
|---|---|
| put this on the internet, free, with sign-in | [DEPLOY.md](DEPLOY.md) |
| run it on an office PC inside the IOCL network | [DEPLOY.md](DEPLOY.md), Part G |
| know who updates what, and when | [DAILY_UPDATE.md](DAILY_UPDATE.md) |
| see every setting that can be changed | [.env.example](.env.example) |

## What is in this folder

| File | What it is |
|---|---|
| `static/index.html` | the whole portal — one file, no libraries, works offline |
| `static/login.html` | the sign-in page a visitor meets first |
| `app.py` | the server: sign-in, the shared copy, the change log, the AI calls |
| `store.py` | where the data is kept — SQLite on a PC, PostgreSQL in the cloud |
| `requirements.txt`, `Procfile`, `render.yaml`, `Dockerfile` | what a host needs to run it |
| `.env.example` | every setting, with a note on each |

## How it runs

Three ways, same portal:

1. **Shared website** (what DEPLOY.md sets up) — one copy everybody signs into, with
   the change log and the AI assistant. This is the one you want.
2. **Office PC** — the same thing on the intranet, data in a file next to the code.
3. **The single HTML file on its own** — open `static/index.html` by double-clicking
   it. Everything works except sign-in, the shared copy and the AI, and entries stay
   in that one browser. Useful for a look on a laptop with no network.

## Settings

Every setting can be given as an environment variable (what a cloud host uses), or as
a key in a `config.json` file next to `app.py` (easier on an office PC). The
environment wins when both are set. The full list, with explanations, is in
[.env.example](.env.example); the ones that matter most:

| Setting | Default | What it does |
|---|---|---|
| `PUBLIC_READ` | `false` | `false` = a user ID is needed even to read the portal |
| `DATABASE_URL` | *(blank)* | blank = a file on disk; set = PostgreSQL, which a free host needs |
| `ADMIN_PASSWORD` | `change-me` | the first admin's password, used only when the database is created |
| `SECRET_KEY` | *(generated)* | signs the sign-in cookie; set it so restarts don't sign everyone out |
| `GEMINI_API_KEY` | *(blank)* | your key from aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | which model answers |
| `AI_DAILY_LIMIT` | `400` | the portal's own cap, so the free quota can't be spent by accident |

The AI assistant also speaks to Groq, xAI (Grok), Anthropic and any OpenAI-compatible
endpoint — set `AI_PROVIDER` and that provider's key.

## What is pre-filled, and where it came from

| Tab | Source |
|---|---|
| Overview facts | WO 70182948 (contract value ₹20,52,43,805.84 excl. GST; LOA signed 07.08.2024; 12 months; EIC GM WRPL Koyali) |
| Quantities | BoQ23098 — 335 SOR items; WO rates = estimated rates with 0.55 % discount on net |
| Pre-project activities | tender SIT/SCC clauses and WO clauses, cited in the Reference column |
| Mainline DPR | reference DPR_ML format; scopes from BoQ (6,000 m + 200 m open-cut; 9 km air drying / N2 / EGP / preservation; markers, bends, chambers) |
| HDD register | 34 crossings from the tentative crossing list — 4 major HDD (1,516 m) and 30 shallow HDD (384 m) |
| Civil work | 13 locations from SIT cl. 4.2.0: 2 mainline-cum-intersection valve chambers, 8 air vent chambers, 3 scour valve pits |
| Documentation | contractor submission → site review → finalisation → rough sketch → final drawing → PLHO review → approval |

Stage weightages, document stages and the focus-list thresholds are all editable on
the Settings tab — nothing above is hard-coded into the program.

## Focus-list rules

* **Quantity** — entered qty exceeds WO qty by more than the threshold (default 10 %) and approval is not *Approved*.
* **Document** — sitting at a "review" stage longer than the review period (default 15 days), due within the lead days, or marked Trigger.
* **Pre-project** — target within the lead days or overdue and not Complete, or marked Trigger.
* **HDD** — no update for N days while in progress, work started without permission, rig work without an approved drawing, or marked Trigger.
* **Mainline** — no DPR posted for N days.

## Replacing the shipped baseline

`static/index.html` carries the starting data inside
`<script id="shipped" type="application/json">`. Replacing that JSON changes what a
brand-new database is seeded with, and what **Reset to shipped data** restores. It
does **not** touch a portal that is already running — that data lives in the database.
