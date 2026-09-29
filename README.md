# CeroMailer

A tool that lets me send a file from any institute computer straight to my
own Gmail — no login, no install, no USB drive, no "email it to myself and
hope I remember later." Pick a file, type where it should go, hit send.

## Why this exists

At my institute, I regularly need to get practicals, quizzes, and other
files off a lab computer and into my own inbox. The obvious way — open
Gmail, compose, attach, send — gets old fast when you're doing it every
class, on a different machine every time. Institute PCs are locked down
too: no installing anything heavy, and no admin access for something like
Task Scheduler.

So I built something smaller and dumber than a full app, but that actually
solves the problem: a webpage and a command-line tool that both do exactly
one thing — take a file and a destination, and send it.

## How it works

There are two ways to use it, both hitting the same backend:

- **A webpage** — open it, fill in the receiver's address, subject, body,
  pick a file (or files, or none at all), hit Send.
- **A CLI script** — same idea, but from a terminal, with a native file
  picker instead of typing a path.

Behind both of them:

1. The client requests a unique upload session ID from `/api/create-session`.
2. The file(s) get uploaded straight to **Supabase Storage** under `sessions/<sessionId>/` from the browser or the script — never through the backend function itself.
3. A small JSON message (`{ sessionId, receiver, subject, body }`) goes to a **Vercel serverless function** (`/api/send`).
4. That function checks rate limits and a daily send cap against a
   **Supabase** table, downloads the file(s) back out of storage, attaches
   them to an email, and sends it through Gmail's SMTP server using a
   spare Gmail account's App Password.
5. It logs the send, then deletes the temporary files from storage.

The Gmail credentials and the Supabase service key only ever live in
Vercel's environment variables — never in this repo, never on whatever
lab PC happens to run the CLI.

## Why it's built this way

The architecture went through a few real revisions, not just a straight
line from idea to finished thing:

- **Why not just send the file straight to the backend function?**
  Vercel's serverless functions cap request bodies at 4.5MB, which is a
  hard limit, not a setting. A 40MB PDF would just get rejected. So the
  browser/CLI uploads the file directly to storage first, and only a tiny
  JSON message goes to the function itself.

- **Why a spare Gmail account instead of my real one?**
  So any spam flags, rate-limit trouble, or general weirdness from
  automated sending stays completely isolated from my actual inbox.

- **Why Python for the backend function, when Vercel defaults to
  JavaScript?**
  Because the very first working version of this project — a plain script
  using `smtplib` and `mimetypes` — was already written in Python. Rather
  than translate working logic into a different language, the serverless
  function reuses that same code almost line for line.

- **Why Supabase for both logging and storage, instead of something
  simpler?**
  It's free, it comes with both a Postgres table and file storage in one
  place, and it lets me enforce upload size limits and access policies
  without writing that logic myself.

## Handling abuse (because this thing is public-ish)

Since the sending function has to be reachable from a browser with no
login involved, a few guardrails are built in:

- Rate limiting: max 5 requests per IP in a 3-second window.
- A daily cap on total sends, comfortably under Gmail's own ~500/day
  threshold for a personal account, so the spare account never gets
  anywhere near getting flagged.
- Input sanitization on the receiver address and subject line, so nobody
  can smuggle extra email headers in.
- CORS locked to this project's own frontend, so no other website can
  quietly use this as a free email relay.
- A 50MB file size cap (Supabase's free-tier ceiling, so it's enforced
  whether or not I remember to check it myself).

## What this would have cost with other options

Part of why this exists as a "build it yourself with free-tier tools" project
rather than just paying for an existing service:

- **EmailJS** — the free tier caps requests to 50KB per email, which rules
  out real file attachments entirely. Their paid tiers start around $9/month
  for 500KB attachments, and you'd need their $40/month Business tier just
  to reach attachments up to about 30MB — still short of the 50MB this
  project needed, and that's an ongoing monthly cost for something used a
  few times a week at most.
- **Google Workspace** (the "just get more Gmail sending headroom"
  option) — starts around $7/user/month for the cheapest tier, billed
  annually, just to raise the daily sending cap past a personal Gmail
  account's limit. For a student project that realistically sends a
  handful of emails a day, that's real recurring money for headroom that
  will basically never get used.
- **This project** — $0/month. A free Vercel project, a free Supabase
  project, and a spare Gmail account, all on their free tiers, which
  comfortably cover this project's actual usage.

(Pricing above is what these services listed as of 2026 — check their
current pages if you're reading this much later, since pricing pages
change.)

## What I learned building this

- How to actually work around a hard platform limit (the 4.5MB request
  cap) instead of just hitting it and giving up on the idea.
- The difference between calling a method and assigning to it — an early
  bug where `msg.set_content = input(...)` silently did nothing useful,
  instead of `msg.set_content(input(...))` actually setting the email
  body.
- Why a brand-new email account lands in spam no matter how "correct" the
  code sending it is — deliverability is about sender reputation and
  history, not just getting the SMTP call right.
- Debugging a `SyntaxError` caused by a naming collision between a library
  I loaded (`window.supabase`) and my own variable name — nothing to do
  with logic, just two things trying to use the same name.
- That "add this file type restriction" isn't always the safer choice —
  since the whole point here is attaching *any* file type a practical or
  quiz might come as, locking the storage bucket to specific MIME types
  would have worked against the actual goal.

## Status

**Working right now:**
- File sending via the webpage, with optional and multi-file attachments
- File sending via the CLI, with a native file picker
- Rate limiting, daily caps, and logging, all backed by Supabase
- Deployed and live on Vercel

**Still ahead:**
- Packaging the CLI into a standalone `.exe` with PyInstaller, so it runs
  on a lab PC with no Python installed
- A one-line PowerShell installer, served off this repo
- A menu that lets someone pick CLI or webpage the first time they run it

## Tech stack

| Piece | Role |
|---|---|
| Python | Core sending logic, both locally and in the deployed function |
| HTML/CSS/JS | The webpage frontend |
| Vercel | Hosts the serverless `/api/send` function |
| Supabase | File storage, send logs, and rate-limit tracking |