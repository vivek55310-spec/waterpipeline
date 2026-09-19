# Putting the portal on the internet — step by step

Everything here is free. No credit card, no software to install on your PC, nothing
to type into a black terminal window. Work through the parts in order; the whole
thing takes about 40 minutes the first time.

When you finish you will have:

* a web address like `https://j18-portal.onrender.com` that works from any phone or PC,
* a sign-in page — no user ID, no entry,
* one shared copy of the data that everybody edits and everybody sees,
* an AI assistant answering questions from *today's* data, using your own Gemini key.

> **Before you start.** This portal holds contract values, quantities and vendor
> correspondence for an IOCL work order. Putting it on a public host means the data
> sits on a company outside IOCL. That is normal for this kind of tool, but it is
> your call, not a technical detail — if your IT or vigilance policy does not allow
> it, skip to **Part G**, which runs the very same portal on an office PC inside the
> IOCL network instead.

---

## Part A — Put the code on GitHub (5 min)

The hosting company needs to read the code from somewhere. That somewhere is GitHub.

1. Go to **https://github.com** and sign in (create a free account if you have none).
2. The code is already in your repository **`vivek55310-spec/waterpipeline`**, on a
   branch called `claude/website-deployment-data-updates-dqvzg8`.
3. Open that repository, click the **Compare & pull request** button GitHub shows for
   the branch, then **Create pull request** → **Merge pull request**. The code is now
   on the `main` branch, which is what the host will read.

That is all you ever need to do on GitHub. Later, whenever the code changes on `main`,
the website updates itself.

---

## Part B — Get your Gemini API key (3 min)

This is the key that lets the portal ask Google's AI your questions. It is free.

1. Go to **https://aistudio.google.com/apikey** and sign in with a Google account.
2. Click **Create API key**, pick or create a project when it asks.
3. A long string starting with `AIza…` appears. Click the copy icon.
4. Paste it somewhere safe for the next ten minutes — Notepad is fine. **Do not paste
   it into WhatsApp, an email, or the code.** Anyone who has it can spend your quota.

What the free plan gives you (Google's numbers, not mine, and they do change):
Gemini **3.1 Flash-Lite** allows roughly **500 requests a day**, which is far more than
a site office will ask. The portal caps itself at 400 a day so you cannot be
surprised by a hard stop mid-afternoon; you can change that cap later.

---

## Part C — Create the database (7 min)

Here is the one thing that trips everybody up, so read this paragraph twice.

A free web host gives your app a **temporary disk**. Every time the site restarts —
and a free site restarts often — anything written to that disk is **erased**. If the
portal kept its data in a file on the host, you would lose a day's entries without
warning. So the data goes into a separate free database that is designed to keep it.

1. Go to **https://neon.com** and click **Sign up** (signing in with GitHub is quickest).
2. It offers to create a project. Name it `j18-portal`. Region: pick the one nearest
   India — **AWS ap-southeast-1 (Singapore)** is a good choice. Click **Create**.
3. You land on a dashboard with a box called **Connection string**. Click **Copy**.
   It looks like:
   `postgresql://neondb_owner:XXXXXXXX@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
4. Paste that next to your API key in Notepad. This is the address *and* the password
   of your database — keep it exactly as private as the API key.

Neon's free plan has no expiry date and gives 0.5 GB of storage (this portal uses a
few megabytes) and 100 compute-hours a month. "Compute-hours" means *time the
database is awake*; it falls asleep after five minutes with nobody using it, and the
portal is written so that a browser tab left open in the background does not keep
waking it up.

---

## Part D — Create the website (10 min)

1. Go to **https://render.com** and click **Get Started** → sign in with GitHub.
2. In the dashboard click **New** → **Web Service**.
3. Choose **Build and deploy from a Git repository** → **Connect** next to
   `vivek55310-spec/waterpipeline`. If the repository is not listed, click
   **Configure account** and give Render permission to see it.
4. Fill the form:

   | Field | What to put |
   |---|---|
   | Name | `j18-portal` (this becomes your web address) |
   | Region | Singapore |
   | Branch | `main` |
   | Runtime / Language | Python 3 |
   | Build command | `pip install -r requirements.txt` |
   | Start command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 240` |
   | Instance type | **Free** |

5. Scroll to **Environment Variables** and click **Add Environment Variable** for each
   row below. The left column is the *Key*, the right is the *Value*.

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string from Part C |
   | `GEMINI_API_KEY` | the `AIza…` key from Part B |
   | `GEMINI_MODEL` | `gemini-3.1-flash-lite` |
   | `AI_PROVIDER` | `gemini` |
   | `ADMIN_PASSWORD` | a long password you invent now — write it down |
   | `SECRET_KEY` | mash the keyboard for 40-odd characters, letters and digits |
   | `PUBLIC_READ` | `false` |
   | `HTTPS_ONLY` | `1` |

6. Click **Create Web Service**. Render now builds the site; the log scrolls past for
   two or three minutes and ends with `Booting worker`. When the status at the top
   turns green and says **Live**, open the address shown there.

7. You should see the sign-in page. Sign in with user `admin` and the
   `ADMIN_PASSWORD` you chose. **The portal opens.**

> `ADMIN_PASSWORD` is only read when the database is brand new — it creates the first
> admin account and is ignored afterwards. Change the password inside the portal
> (Settings & data → My sign-in), not here.

---

## Part E — Set it up for your team (5 min)

Inside the portal, go to **Settings & data**:

1. **My sign-in → Change my password.** Do this first, even though you just set one.
2. **Users → Add user.** One row per person: a user ID (`rksharma`), their name, a
   password of at least 8 characters, and the **Admin** tick only for people who
   should be able to create users and download backups.
   Tell each person their user ID and password, and tell them to change it on the
   same panel when they first sign in.
3. **AI assistant tab → Test connection.** It should answer `Connection OK — gemini
   replied "OK"`. If it complains that the model does not exist, click **List models**
   next to it: that shows the exact model names your key can use, and you paste the
   one you want into the `GEMINI_MODEL` environment variable on Render.

Anyone you gave a user ID to can now open the address on their phone, sign in, and
start entering progress.

---

## Part F — Three finishing touches

**1. Stop the site falling asleep.** A free Render service sleeps after 15 minutes
with no visitors, and the next person then waits about 50 seconds for it to wake.
To avoid that, go to **https://uptimerobot.com**, make a free account, and add a
monitor: type **HTTP(s)**, URL `https://your-address.onrender.com/api/health`,
interval **5 minutes**. That address is a deliberately cheap page that does not touch
the database, so it keeps the website awake without spending your Neon hours.

**2. Take a backup now and then.** Settings & data → **Download full backup** (admins
only) saves one file holding the data, the change log and the user list. Do it on the
first of the month and keep it on the office drive. If the host ever loses everything,
that file restores the portal through **Import JSON**.

**3. Your own web address (optional).** If IOCL gives you a name like
`j18.iocl.in`, Render → Settings → **Custom Domain** walks you through it and issues
the https certificate free.

---

## Part G — The office-PC alternative (no internet, no cloud)

If the data must stay inside the IOCL network, the same code runs on any Windows PC
that stays switched on:

1. Install Python 3.11+ from **python.org** — tick **"Add python.exe to PATH"** on the
   first screen of the installer.
2. Copy this folder onto the PC, say to `D:\j18-portal`.
3. Open Command Prompt and type these two lines:

   ```
   cd /d D:\j18-portal
   pip install flask
   python app.py
   ```

4. It prints `Portal running: http://0.0.0.0:8000`. Find that PC's address with
   `ipconfig` (something like `10.12.34.56`) and tell everyone to open
   `http://10.12.34.56:8000` in their browser.
5. Sign in as `admin` / `change-me` and **immediately change the password** on
   Settings & data.

Here the data lives in `portal.db` next to `app.py` — back that file up to the office
drive. Set the AI key by creating a file `config.json` in the same folder:

```json
{ "ai_provider": "gemini",
  "gemini_api_key": "AIza-your-key-here",
  "gemini_model": "gemini-3.1-flash-lite",
  "admin_password": "your-first-admin-password" }
```

The PC needs to reach `generativelanguage.googleapis.com` for the AI tab to work; if
the office proxy blocks it, everything except the AI tab still works normally.

---

## When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Render log: `ModuleNotFoundError: psycopg` | the driver did not install | check the build command is `pip install -r requirements.txt` |
| Render log: `could not connect to server` | `DATABASE_URL` is wrong or truncated | copy it again from Neon, paste the whole string |
| Sign-in page keeps coming back | the browser is refusing the cookie | make sure you opened the `https://` address, and that `HTTPS_ONLY` is `1` |
| `too many attempts — try again in N minutes` | five wrong passwords from your address | wait it out; it protects the site from password guessing |
| AI: `API key not valid` | key mistyped or restricted | make a fresh key at aistudio.google.com/apikey |
| AI: `rate limit / daily free quota reached` | the free day's allowance is spent | wait until it resets, or use a cheaper model |
| AI: `used its whole output allowance on internal reasoning` | a thinking model ran out of room | raise `AI_MAX_TOKENS` to 8000, or set `GEMINI_THINKING_LEVEL` to `low` |
| Site takes ~50 s to open | the free service was asleep | set up the UptimeRobot ping in Part F |
| `version conflict` while saving | two people saved the same second | the page reloads the newer copy; re-enter your line |

Every setting in the table in Part D can be changed later: Render → your service →
**Environment** → edit → **Save, rebuild, and deploy**. The list of everything that
can be set is in `.env.example`.
