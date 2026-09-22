# Installing Dress Studio on a new Windows machine

If you're the person who's been developing this and already have a working
setup, you don't need this file — it exists so a colleague doesn't have to
read `README.md`/`CLAUDE.md`/`TASK.md` (written for continuing the
*development* of this project, not for using it).

---

## The easy way: `DressStudioSetup.bat`

If you were handed a file called `DressStudioSetup.bat`, this is all you
need to do:

1. Put it anywhere (Desktop is fine) and **double-click it**.
2. A black window opens and does everything automatically: downloads the
   app, installs it, and opens it in your browser. **It automatically uses
   your graphics card if you have an NVIDIA one** — no setup needed, it
   detects this itself and installs the matching version.
3. Wait. First run downloads ~2-3 GB (the AI models) and can take 15-30
   minutes depending on your internet connection — it's mostly unattended
   downloading, not something you need to interact with.
4. When it's done, your browser opens the app automatically.

**Three shortcuts are created on your desktop the first time it
finishes** — use these from then on instead of hunting for the `.bat` file:

- **Dress Studio** — launches the app.
- **Stop Dress Studio** — quits it.
- **Uninstall Dress Studio** — removes it (see "Uninstalling" below).

(Double-clicking `DressStudioSetup.bat` itself always still works too — it
skips everything already installed and goes straight to opening the app, a
few seconds, and also checks for updates first.)

**Dress Studio keeps running after you close the black window** — it
starts in the background on purpose, so closing that window (or your
browser tab) doesn't stop it. Use the **"Stop Dress Studio"** shortcut when
you actually want to quit it. This changed 2026-09-23 — it used to require
leaving the window open, which was confusing ("I closed the terminal and
now it says the page can't be reached").

If it stops with a red `ERROR:` message, read it — it's written to say
plainly what's wrong (usually: Python or Git not installed yet — see
"Prerequisites" below) rather than failing silently.

Skip the rest of this file unless something goes wrong — the sections
below are the manual version of exactly what the `.bat` does for you,
useful for troubleshooting or if you'd rather run each step yourself.

**Why a `.bat` and not a `.exe`?** An earlier version of this was a
compiled `.exe`. In practice, security software on a machine that's never
seen it before sometimes kills a compiled executable mid-run just because
it's "an unrecognized binary spawning PowerShell and Git" — even when
there's nothing wrong with it (this happened on a real test — the window
flashed and closed with no error shown). A `.bat` file is plain text: it
does the exact same steps by calling the same `install.ps1` /
`install-torch.ps1` / `run.ps1` scripts, but there's nothing compiled for a
security scanner to distrust.

---

## Prerequisites (needed either way)

**Python 3.11 or newer** and **Git** must be on the machine first — the
`.bat` checks for these and tells you if either is missing, it doesn't
install them for you.

1. **Python** — [python.org/downloads](https://www.python.org/downloads/).
   During install, **tick "Add python.exe to PATH"** on the first screen —
   the single most common thing people miss, and everything below fails
   with a confusing error if it's unchecked.
2. **Git** — [git-scm.com/downloads](https://git-scm.com/downloads).
   Default options are fine throughout the installer.

To check both worked, open a new PowerShell window (Start menu → type
"PowerShell") and run `python --version` and `git --version` — each should
print a version number. If either says "not recognized", the PATH checkbox
above was likely missed — reinstall and check it, or restart the machine
(PATH changes sometimes need a restart to take effect). Then re-run
`DressStudioSetup.bat`, or continue manually below.

---

## The manual way (what the .bat does, step by step)

### 1. Get the code

```powershell
cd $HOME\Documents
git clone https://github.com/Parthesh10/dress-augmentation-for-catalogue-.git "Dress Augmentation"
cd "Dress Augmentation"
```

### 2. Run the two install scripts, in order

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
powershell -ExecutionPolicy Bypass -File install-torch.ps1
```

- `install.ps1` sets up the app itself (a few small packages: image
  handling, the web interface). Fast, a few seconds.
- `install-torch.ps1` sets up the AI models used to cut the garment out of
  the photo and detect where the floor is in a background photo. This is
  the slow, multi-GB one. **It checks for an NVIDIA GPU automatically**
  (via `nvidia-smi`) and installs the matching CUDA build if it finds one,
  or a CPU-only build otherwise — either way, no manual choice needed.
  CPU is fully correct, just slower per photo (roughly 30-180 seconds vs.
  a few seconds on GPU).

### 3. Run the app

```powershell
.\run.ps1
```

Starts a small local web server and opens it in your browser
(`http://127.0.0.1:7860`). Leave the window open while you work — closing
it stops the server. **Next time**, skip straight to this step — no need
to repeat installs.

---

## Using it

Three tabs across the top:

- **Process a dress** — the real pipeline. Upload a photo, tell it what
  kind of garment it is (or leave it on auto), pick a background, click
  process, download the finished image(s).
- **Compare backdrops** — upload one or more photos and see them against
  every available background at once, side by side, before committing to
  one in the Process tab. Preview only, doesn't export.
- **What's built** — a status page showing which features are finished vs.
  still in progress.

Your own uploaded backdrop photos get saved permanently in a small local
library (under "Your saved backdrop photos") so you can reuse them across
sessions — they stay on your machine only, nothing is uploaded anywhere
else.

---

## Uninstalling

Two ways, both do the same thing:

- Double-click the **"Uninstall Dress Studio"** shortcut on your desktop
  (created next to "Dress Studio" the first time setup finished).
- Or: Windows Settings → Apps → search "Dress Studio" → Uninstall.

Either one removes the installed app environment and AI models (frees
several GB) and all three desktop shortcuts. **Your saved backdrop photos
and processed images are kept by default** — the uninstaller asks
separately, with an explicit typed confirmation, before it will delete
those too. Say no (or just press Enter) to keep everything except the
installed software; you can always reinstall later with
`DressStudioSetup.bat` and your saved photos will still be there.

It also stops Dress Studio first if it's currently running, since Windows
won't let a file be deleted while the app still has it open.

---

## Troubleshooting

**"Python was not found" / "Git was not found"** — install prerequisites
above, tick "Add to PATH" for Python, then run `DressStudioSetup.bat` (or
the relevant script) again.

**The matting/background-removal step fails with an error naming a missing
interpreter path** — `install-torch.ps1` either wasn't run, or didn't
finish (check for a red error in its output). Re-run it, or re-run
`DressStudioSetup.bat`, which will pick up where it left off.

**The browser opens to "can't reach this page"** — wait a few seconds and
refresh; the server takes a moment to finish starting the first time.

**The app seems to ignore a fix / still shows old behaviour** — `run.ps1`
already stops any leftover server from a previous session before starting
a new one, so this is rare, but if it happens: click **"Stop Dress
Studio"** on your desktop, then **"Dress Studio"** to start it fresh.

**Something else** — copy the exact error text and send it to whoever gave
you this guide; nearly every failure mode in this app prints a specific,
readable reason rather than a generic crash.

---

## For whoever is sharing this with colleagues

`DressStudioSetup.bat` is the single file to hand out — it's plain text
(open it in Notepad any time to see exactly what it does), committed
directly to the repo, so there's nothing to build or rebuild. Get it to a
colleague however's easiest: a GitHub Release asset, email, chat, a shared
drive. It clones the public repo and runs the same `install.ps1` /
`install-torch.ps1` / `run.ps1` a manual install would, just without
anyone having to type the commands.
