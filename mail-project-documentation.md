# Gmail File-Sender (CeroMailer) — Project Documentation

## 1. The Problem

At my institute, I often need to send practicals, quizzes, and other files
from an institute computer to my own Gmail. Doing this manually — opening
Gmail, composing a message, attaching the file, typing the address — every
single time is repetitive and slow. It gets worse because I don't always sit
at the same computer, and institute PCs are locked down: I can't install
large applications, I don't have admin rights, and something like Windows
Task Scheduler needs technical access I don't usually have.

This project automates that: pick a file, type where it should go, and it's
sent. No manual composing, no logging into anything on the lab machine, and
nothing to configure each time.

## 2. Goals

- Send one or more files to a Gmail address without composing an email by
  hand each time.
- Make it usable by anyone at the institute, not just me — no accounts, no
  logins, no setup on the machine it's run from.
- Don't depend on unreliable free hosting for anything that has to keep
  working.
- Support two ways of using it — a command-line version and a webpage
  version — and let the person choose.
- Install with a single line in PowerShell, with no admin rights.

All five of these are met now. The sections below explain how, and what had
to change along the way.

## 3. Tech Stack and What Each Piece Does

| Language / Tool | Role |
|---|---|
| **Python** | The sending logic (connects to Gmail's SMTP server, builds the email, attaches files, detects file types) and the command-line tool |
| **HTML/CSS + JS** | The webpage: a form with receiver, subject, body, and an optional file picker |
| **Vercel** | Hosts two small serverless functions: one that hands out upload sessions, and one that actually sends the email. The Gmail credentials live here and nowhere else |
| **Supabase** | Temporary file storage for uploads, plus a Postgres table that logs every send and enforces the rate limits |
| **PowerShell + batch** | The one-line installer and the `ceromailer` launcher |
| **GitHub** | Hosts the code, and serves the installer files directly from the repository |

PHP was part of the original plan but was dropped once the project moved to
a serverless architecture. Section 6 explains why.

## 4. How Sending Actually Works

Gmail won't accept a script logging in with a normal account password. It
requires an **App Password**, a 16-character code generated after turning on
2-Step Verification. This is used in place of a password specifically for
programs like this one.

Python's built-in `smtplib` library handles the connection to Gmail's SMTP
server (`smtp.gmail.com`, port `587`), logs in with the App Password, and
sends the message.

### The first working version (proof of concept)

```python
import smtplib
from email.message import EmailMessage

sender_email = "youraccount@gmail.com"
app_password = "your16charapppassword"
receiver_email = "youraccount@gmail.com"

msg = EmailMessage()
msg["Subject"] = "Test Email from Python"
msg["From"] = sender_email
msg["To"] = receiver_email
msg.set_content("Hello! This is a test email sent from my Python script.")

with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login(sender_email, app_password)
    server.send_message(msg)

print("Email sent successfully!")
```

That script is still in the repo as `testmail.py`. It confirmed the core
mechanism worked before I added anything on top of it.

### How it works now

The final version splits the job in two so that big files never have to pass
through the sending function itself:

1. The webpage or CLI asks `/api/create-session` for a session ID. The server
   generates a long random one (256 bits, using Python's `secrets` module).
2. The file(s) are uploaded straight to a private Supabase Storage bucket,
   inside a folder named after that session ID.
3. The webpage or CLI sends `/api/send` a small JSON message: the session ID,
   the receiver, the subject, and the body. It never sends file paths.
4. `/api/send` first checks the rate limit and the daily cap (one atomic
   database call), then looks inside that session's folder, downloads
   whatever is there, attaches it all to one email, and sends it through
   Gmail's SMTP server with the certificate properly verified.
5. It logs the send and deletes the files from storage.

If no files were uploaded, the email just goes out without attachments.

## 5. Build Progression

Each piece was built and tested on its own before moving to the next, rather
than writing everything at once and hoping it worked.

### Step 1 — Hardcoded test email
Fixed sender, receiver, and message, just to prove the App Password and
`smtplib` connection worked at all.

### Step 2 — Accepting real input
Hardcoded values were replaced with `input()` prompts, so the script could
send to any address with any subject and body at runtime.

### Step 3 — Attaching real files
The script was extended to attach an actual file, using Python's built-in
`mimetypes` library to detect the file type automatically (`.py`, `.html`,
`.php`, images, etc.), so the same code works for any file without
hardcoding formats.

```python
import mimetypes

mime_type, _ = mimetypes.guess_type(file_path)
if mime_type is None:
    mime_type = "application/octet-stream"
main_type, sub_type = mime_type.split("/")

with open(file_path, "rb") as f:
    file_data = f.read()
    file_name = file_path.split("\\")[-1]

msg.add_attachment(file_data, maintype=main_type, subtype=sub_type, filename=file_name)
```

`"rb"` (read binary) mode is used so text files and binary files (images,
PDFs) are read the same way, without separate handling per type.

### Step 4 — Moving the sending logic online
The working script became a Vercel serverless function so the Gmail
credentials could live on the server instead of on whatever PC I was using.
Supabase was set up for the log table and for temporary file storage.

### Step 5 — The webpage
A plain HTML form that uploads the file to Supabase and then calls the
function. It started with one required file and ended up taking any number
of files, or none.

### Step 6 — Optional and multiple attachments
Early on, leaving the file out made the whole send fail, even though the
text part had nothing to do with it. The file became optional, and the form
and the function both learned to handle several attachments in one email.

### Step 7 — The command-line version
`cli.py` follows the same steps as the webpage: ask for a session, upload,
send. It opens a normal file-picker window for choosing files (or lets you
press Enter to send with no attachment), and it falls back to typing a path
if the picker can't open.

### Step 8 — A security pass
Once everything worked, I went back and tightened it up. The details are in
Section 8.

### Step 9 — The installer
`install.ps1` and `ceromailer.cmd` turn the CLI into something you can
install with one line and start by typing `ceromailer`. See Section 9.

## 6. Architecture Decisions — What Changed and Why

The design went through several real revisions as practical constraints came
up. I'm documenting the *why* here, not just the final answer, because the
reasoning matters as much as the result.

**Considered:** hosting a PHP + Python backend on a free host (InfinityFree
or similar) for a web dashboard.
**Rejected:** free hosting has limited, unreliable storage. That's not
something to depend on for a tool meant to be used regularly.

**Considered:** a hosted "file-drop with a code" system: upload a file, get a
short code or QR, download it elsewhere with that code.
**Rejected:** it still needs hosting and storage, so the same reliability
concern applies, even though the idea itself was reasonable.

**Considered:** using a third-party email API (EmailJS) to avoid dealing with
Gmail credentials at all.
**Decided against:** it would mean depending on someone else's limits, and
its attachment limits turned out to be far too small for this (see Section
7). Instead the project builds its own equivalent: a small serverless
function on **Vercel** holding a *spare* Gmail account's App Password, with
**Supabase** handling logging and rate-limit tracking.

**Considered:** using Supabase to also run the sending logic.
**Rejected:** Supabase's free tier pauses a project after a week of
inactivity and needs a manual restore. This tool won't be used every day
(school breaks, gaps between practicals), so putting the *sending* function
there would mean it silently stops working during quiet periods. Vercel's
functions don't have that behavior. So the split is: **Vercel runs the
sending logic** (must always work instantly), and **Supabase holds logs,
rate-limit data, and temporary files**.

**Considered:** sending the file inside the request to the sending function.
**Rejected:** Vercel caps request bodies at 4.5 MB, and that is a hard limit,
not a setting. A 40 MB PDF would just be refused. So the browser (or CLI)
uploads the file directly to Supabase Storage first, and only a tiny JSON
message goes to the function. This also made Supabase's own 50 MB per-file
cap the real limit on attachment size.

**Considered:** letting the client choose its own storage filenames and send
those paths to the function.
**Rejected:** the function runs with a powerful key, so it would happily
fetch whatever path it was told to. That means someone could point it at a
file that wasn't theirs. Instead the server issues a random session ID, files
live under that ID, and the function only ever looks inside that one folder.

**Decided:** use a **separate, spare Gmail account** dedicated to this
service, rather than a personal one. This isolates any risk (spam flags,
rate-limit issues) from a personal inbox. Whatever account logs in through
`smtplib` is the address that shows up as the sender. Gmail doesn't allow
spoofing a different "From" address than the one authenticated.

**Considered:** rotating between several Gmail accounts so the daily sending
limit would never be reached.
**Rejected:** that is exactly the pattern Google's abuse detection looks for,
it could get all the accounts flagged together, and at my real volume (a
handful of emails a day) the limit is nowhere near a problem anyway.

**Decided against:** a temporary/disposable-email feature (generate a
throwaway inbox, auto-forward to a real Gmail). I explored it in depth, but
it solved a problem the architecture had already solved another way: nobody
ever types or logs into any Gmail credentials except the one spare account
living server-side. Dropped from scope.

**Considered:** other delivery channels (SMS, Telegram, WhatsApp, Instagram).
**Rejected, mostly:** sending SMS to Indian numbers needs business
registration and can't carry real attachments; Telegram bots can't message
someone who hasn't pressed Start first; unofficial WhatsApp automation risks
a ban; and Instagram doesn't let an account message someone first. Gmail is
the one channel that is free, carries real attachments, and needs nothing
from the receiver.

**Decided:** the function is written in **Python**, even though Vercel's
default is JavaScript. The first working version was already Python, so the
function reuses that same logic almost line for line.

**Decided against:** packaging the CLI as a standalone `.exe` with
PyInstaller. The original plan was an `.exe` so no Python would be needed,
but every institute PC already has Python, and an unsigned `.exe` downloaded
from the internet is exactly what Windows SmartScreen warns about (and some
locked-down labs block outright). A code-signing certificate costs real money
every year, which isn't worth it for a personal project. A plain script with
a small launcher avoids the problem entirely. If a PC ever doesn't have
Python, the webpage still works.

**Decided:** the installer puts everything in `%LOCALAPPDATA%\CeroMailer`
rather than Program Files, because writing to Program Files needs admin
rights I don't have. The folder is added to the *user* PATH, which doesn't
need admin either.

**Decided:** on every launch, `ceromailer` asks fresh whether you want the
command-line version or the webpage, not just once at install time.

## 7. What the Alternatives Would Cost

Part of why this is a "build it with free-tier tools" project rather than
just paying for an existing service. Prices are what these services listed in
2026, so check their pages if you're reading this much later.

- **EmailJS:** the free tier allows only 50 KB per request, so real file
  attachments aren't possible. Paid plans start around $9/month for 500 KB
  attachments, and you'd need the $40/month Business plan to reach attachments
  of roughly 30 MB, which is still under the 50 MB I wanted.
- **Google Workspace:** starts around $7 per user per month (billed
  annually) just to get more sending headroom than a personal Gmail account.
  For a tool that sends a handful of emails a day, that's recurring money for
  headroom that would never get used.
- **This project:** $0/month. A free Vercel project, a free Supabase project,
  and a spare Gmail account, all inside their free tiers.

## 8. Handling Abuse and Failure Cases

The sending function has to be reachable from a browser with no login, so a
few safeguards are built in:

- **Rate limiting:** max 5 requests per IP address within a 3-second window.
- **Daily cap:** a hard stop at 400 sends per day, comfortably under the
  roughly 500 a normal Gmail account can send before Google flags it. The
  real worst case here is the spare account getting suspended, more than
  anything Vercel or Supabase would restrict on their own.
- **Both checks are atomic.** They happen inside one database function that
  takes a lock per IP, so a burst of requests arriving at the same instant
  can't all slip through before any of them is counted. The checks also run
  *before* the function touches any stored files.
- **That database function is locked down.** It has a fixed search path, and
  only the server-side key is allowed to run it, so nobody can call it
  directly from a browser to burn through the rate limit.
- **Server-issued sessions.** File paths are never trusted from the client.
  Session IDs must be exactly 64 hex characters, and the function only looks
  inside that session's own folder.
- **Cleanup.** Files are deleted after a send, and leftovers from abandoned
  uploads (someone uploads, then closes the tab) are swept away when they are
  more than an hour old.
- **Input sanitization:** the receiver's address and the subject line are
  validated, checked to be plain text, and stripped of newline characters
  before going into email headers, which prevents header injection (someone
  smuggling in extra headers like an unauthorized Bcc).
- **Secrets stay server-side.** The App Password and the Supabase secret key
  exist only as environment variables on Vercel. They are never in client
  code and never committed to the repository. The key visible in the webpage
  is Supabase's public one, which is meant to be exposed.
- **Storage rules:** anonymous visitors can only *upload* into the bucket.
  They can't list, read, change, or delete anything in it. The log table has
  row-level security on with no public access.
- **CORS** is locked to the project's own site, and the function refuses to
  start if that setting is missing rather than quietly allowing everyone.
- **SMTP** connections use a properly verified TLS certificate, and the
  webpage's Supabase library is pinned to an exact version.
- **No accidental double sends.** The Send button disables itself the moment
  it's clicked, so impatient clicking can't fire the same email several
  times.

### Known trade-offs

- **There is no login.** That's the whole point of the project (nothing to
  set up on a lab PC), but it means the endpoint is reachable by anyone who
  finds it. The rate limit, the daily cap, and the CORS lock are what limit
  the damage.
- **Sessions aren't stored in a database.** Their security comes from being
  impossible to guess, not from a record saying "this one was issued and
  unused."
- **Size limits lean on Supabase.** The 50 MB cap is per file and is enforced
  by Supabase's free tier. The sending function doesn't separately cap the
  total size of everything attached to one email.
- **New-account reputation.** Early test emails from the fresh spare account
  landed in spam. That's down to the account's lack of history, not the
  code. Setting a proper sender name ("Cero Mailer"), writing real subjects
  and bodies, and marking the first few messages as "not spam" all help, and
  it improves on its own with normal use.

## 9. Install and Run

On any PC with Python, open a normal (not admin) PowerShell window and run:

```powershell
irm https://raw.githubusercontent.com/UlquiorraCiffer/CeroMailer/main/install.ps1 | iex
```

The installer:

1. Creates `%LOCALAPPDATA%\CeroMailer`.
2. Downloads `cli.py` and `ceromailer.cmd` into it, overwriting any older
   copies, so running it again is also how you update.
3. Adds that folder to your user PATH.

After that, open a new terminal and type:

```
ceromailer
```

You get a small menu: `[1]` command-line mode or `[2]` open the webpage. The
launcher uses `py` if it exists and `python` otherwise, doesn't need
PowerShell scripts to be allowed to run, and the CLI uses only Python's
built-in libraries, so there is nothing else to install. If the PATH change
hasn't taken effect, you can still `cd` into the install folder and run
`.\ceromailer`.

## 10. Problems I Hit and How I Fixed Them

- **A silent empty email body.** `msg.set_content= input("Body:")` used
  assignment instead of calling the method, so it overwrote `set_content`
  instead of running it, and the email arrived with no body. The fix was
  `msg.set_content(input("Body:"))`. The lesson: a name meant to *do*
  something needs `()`; a name meant to *hold* something uses `=`.
- **The 4.5 MB wall.** Large files can't go through a Vercel function, so
  uploads go straight to storage (see Section 6).
- **Vercel couldn't find my function.** The first deploy failed with "no
  python entrypoint found." I'd picked a Python framework preset during
  import, which makes Vercel expect a single app file instead of separate
  files in `/api`. Switching the preset to "Other" and removing the extra
  config file I'd added fixed it.
- **A page that did nothing when I clicked Send.** The Supabase script
  creates a global called `supabase`, and my own variable had the same name,
  which stopped the whole script from loading. The form then just reloaded.
  Renaming my variable to `supabaseClient` fixed it.
- **A request that arrived with no error at all.** Pasting a whole updated
  file over my edited one brought back the placeholder text for the Supabase
  URL and key. Lesson: check the actual line before assuming the logic is
  wrong.
- **A rate limit with a gap.** Checking the count first and recording the send
  afterward means simultaneous requests can all pass the check. Moving the
  check and the log entry into one locked database function closed that gap.
- **Eight emails from one frantic click-fest.** The rate limit is a sliding
  window, so it was never going to stop one person's repeated clicks. The fix
  was on the button itself: disable it the moment it's clicked.
- **Emails landing in spam.** See the trade-offs in Section 8.
- **A merge conflict on the README.** I'd edited it on GitHub's website while
  also changing the same file locally. Pulling first and resolving the
  conflict by hand sorted it out.

## 11. Current Status

**Working and tested:**
- Sending through the webpage and the CLI, with no file, one file, or several
- Server-issued upload sessions, with cleanup afterward
- Atomic rate limiting and the daily cap
- The Send button's double-click protection
- Logging of every send
- Live on Vercel, with the code on GitHub

**Written, with a real-world check still to do:**
- The one-line installer and the `ceromailer` launcher. They work from a
  normal PowerShell window; what's left to confirm is that the institute's
  network allows downloading from GitHub's raw file server and that `py` or
  `python` is on the PATH there. If a PC can't run it, the webpage is the
  fallback.

**Ideas for later:**
- Marking the Gmail password and Supabase key as "sensitive" variables in
  Vercel's dashboard so they can't be viewed again after being saved
- A server-side cap on the total size of attachments in one email

## 12. What This Project Demonstrates

- Integrating with a real external service (Gmail SMTP) through a standard
  library
- Correctly distinguishing method calls from variable assignment, and
  debugging when the two get confused
- Automatic file-type detection instead of hardcoding formats
- Working around a hard platform limit (the 4.5 MB request cap) by changing
  the design instead of giving up on the idea
- Weighing real architecture trade-offs: hosted vs. serverless, storage
  reliability, third-party dependency vs. building it yourself, and planning
  for abuse before it happens rather than after
- Hardening a public endpoint: not trusting client input, making checks
  atomic, locking down database permissions, and cleaning up after itself
- Designing around an actual constraint (locked-down, shared institute PCs)
  instead of a textbook assignment with no real limitations