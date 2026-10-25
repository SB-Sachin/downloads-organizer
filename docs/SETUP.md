# Setup guide

This guide takes you from a fresh Mac to a working downloads-organizer, one step at a time.
It takes about 20 minutes, most of it waiting for the model to download.

When you finish:

- Every file that lands in `~/Downloads` is read by an AI model running on your own Mac,
  given a descriptive name, and tagged in Finder.
- The service starts by itself at login and restarts itself if it crashes.
- You can right-click any file in Finder and choose **Rename with AI**.
- Nothing you download is ever sent to the internet.

## Contents

1. [Requirements](#1-requirements)
2. [Install Homebrew](#2-install-homebrew)
3. [Install Python](#3-install-python)
4. [Install Ollama](#4-install-ollama)
5. [Download the model](#5-download-the-model)
6. [Get the code](#6-get-the-code)
7. [Run setup.sh](#7-run-setupsh)
8. [Grant Full Disk Access](#8-grant-full-disk-access)
9. [Check that it works](#9-check-that-it-works)
10. [Turn on the Finder Quick Action](#10-turn-on-the-finder-quick-action)
11. [Everyday use](#11-everyday-use)
12. [Customize it](#12-customize-it)
13. [Update](#13-update)
14. [Uninstall](#14-uninstall)
15. [Troubleshooting](#15-troubleshooting)
16. [How it works](#16-how-it-works)

---

## 1. Requirements

| | Minimum | Notes |
| --- | --- | --- |
| Mac | Apple silicon (M1 or later) | Intel Macs work but the model is slow |
| macOS | 14 Sonoma or later | |
| Memory | 16 GB | The default model uses about 9 GB while loaded. 8 GB Macs: see [smaller models](#smaller-model) |
| Free disk | 12 GB | 8 GB for the model, the rest for Python packages |
| Admin password | Needed once | For Full Disk Access |

All commands below go in the **Terminal** app (press Cmd+Space, type `Terminal`, press Return).
Paste one command at a time.

## 2. Install Homebrew

Homebrew installs command-line tools. Check whether you already have it:

```bash
brew --version
```

If you see a version number, skip to step 3. Otherwise install it:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

At the end the installer prints two or three commands under **Next steps** that add
`brew` to your PATH. Run them, then close and reopen Terminal and check `brew --version`
again.

## 3. Install Python

You need Python 3.12 or newer. Check:

```bash
python3 --version
```

If it says 3.12 or higher, skip ahead. If it says 3.9 (the version Apple ships) or the
command is missing, install a current one:

```bash
brew install python@3.13
```

> **Which Python is used?** `setup.sh` picks the newest of `python3.14`, `python3.13`,
> `python3.12`, `python3` that is 3.12 or later. Conda and pyenv installs work too.
> Step 8 shows you how to find the exact binary that needs permission.

## 4. Install Ollama

[Ollama](https://ollama.com) runs AI models on your Mac.

1. Download it from <https://ollama.com/download> and drag **Ollama** into Applications.
   (Or: `brew install --cask ollama`.)
2. Open Ollama from Applications. A llama icon appears in the menu bar.
3. Click the menu bar icon, open **Settings**, and turn on **Launch at login**.
   Without this, the organizer waits after every reboot until you open Ollama yourself.
4. Check that it is running:

```bash
curl http://localhost:11434/api/version
```

You should see something like `{"version":"0.12.3"}`.

## 5. Download the model

The default model is `gemma3:12b`. It reads text and images, which matters for
screenshots, photos, and scanned PDFs. It is about 8 GB:

```bash
ollama pull gemma3:12b
```

`setup.sh` also does this if you skip it, but running it now lets you watch the progress.

<a name="smaller-model"></a>
**Smaller model for 8 GB Macs.** Use `gemma3:4b` instead (about 3 GB). Names are a
little less precise. Pull it with `ollama pull gemma3:4b`, and after step 6 change
`model = "gemma3:12b"` to `model = "gemma3:4b"` in `config.toml`. Any replacement must
be able to read images.

## 6. Get the code

Pick a permanent home for the project. The background service runs the code from this
folder, so **if you move or delete the folder, the service stops working** (run
`./setup.sh` again from the new place to fix it).

Good places: your home folder or `~/Developer`. Avoid `~/Downloads` (the organizer would
watch its own files), and avoid Desktop or Documents if iCloud syncs them.

```bash
cd ~
git clone https://github.com/SB-Sachin/downloads-organizer.git
cd downloads-organizer
```

No git? Click **Code > Download ZIP** on the GitHub page, unzip it, and move the folder
to your home folder. Then `cd ~/downloads-organizer`.

## 7. Run setup.sh

```bash
./setup.sh
```

If you get `permission denied`, run `chmod +x setup.sh uninstall.sh` and try again.

The script prints eight numbered steps:

| Step | What it does |
| --- | --- |
| 1/8 | Checks that this is macOS and Homebrew is installed |
| 2/8 | Installs the `tag` tool (`brew install tag`), which writes Finder tags |
| 3/8 | Creates `.venv` (a private Python environment) and installs the packages in `requirements.txt` |
| 4/8 | Pulls the model from `config.toml` if it is missing |
| 5/8 | Writes `~/Library/LaunchAgents/com.user.downloads-organizer.plist`, which tells macOS how to run the service |
| 6/8 | Loads the service with `launchctl` and starts it |
| 7/8 | Adds the **Rename with AI** Finder Quick Action |
| 8/8 | Runs `doctor`, which checks everything |

It is safe to run `setup.sh` again at any time; it updates what is there.

At this point `doctor` probably shows
`[FAIL] background service folder access`. That is expected. The next step fixes it.

## 8. Grant Full Disk Access

macOS protects the Downloads folder. A program started from Terminal inherits Terminal's
permission, but the background service runs on its own and needs its own permission. It
never gets a pop-up asking for it, so you grant it by hand.

macOS gives permission to the **real Python program**, not to the shortcut inside
`.venv`. Find the real one:

```bash
.venv/bin/python -c 'import os, sys; print(os.path.realpath(sys.executable))'
```

It prints a path such as one of these:

```
/opt/homebrew/Cellar/python@3.13/3.13.7/Frameworks/Python.framework/Versions/3.13/bin/python3.13
/Users/you/miniconda3/bin/python3.13
```

Copy that path, then:

1. Open **System Settings** (Apple menu > System Settings).
2. Go to **Privacy & Security**, scroll down, and click **Full Disk Access**.
3. Click the **+** button below the list. Unlock with Touch ID or your password.
4. In the file window press **Cmd+Shift+G**. A "Go to folder" box appears.
5. Paste the path you copied and press **Return**. The Python file is selected.
6. Click **Open**. A `python3.13` (or similar) entry appears in the list.
7. Make sure its switch is **on**.

Restart the service so it picks up the new permission:

```bash
launchctl kickstart -k gui/$(id -u)/com.user.downloads-organizer
```

> **After a Python upgrade** (for example `brew upgrade` moving 3.13.7 to 3.13.8) the real
> path changes and the permission is lost. Run `./setup.sh` again, repeat this step with
> the new path, and remove the old entry.

## 9. Check that it works

Run the built-in check:

```bash
.venv/bin/python -m organizer doctor
```

Every line should start with `[ok  ]`:

```
[ok  ] Ollama reachable: http://localhost:11434
[ok  ] model gemma3:12b installed
[ok  ] tag tool: /opt/homebrew/bin/tag
[ok  ] watch folder readable: /Users/you/Downloads
[ok  ] background service folder access: last start could read the folder
       service: running (pid 4242)
```

Now try a real file. In one Terminal window, watch the log:

```bash
tail -f ~/Library/Logs/downloads-organizer/organizer.log
```

In a second window, drop a test file into Downloads:

```bash
printf 'Cooking Merit Badge Requirements\n1. Explain the hazards you may encounter while cooking.\n' > ~/Downloads/test_1.txt
```

Within 10 to 30 seconds the log shows a line like:

```
renamed original='test_1.txt' new='cooking-merit-badge-requirements-1.txt' tag=scouts confidence=0.95 seconds=4.2
```

The file in Finder now has the new name and a **scouts** tag. Press Ctrl+C to stop
watching the log. To put the old name back:

```bash
.venv/bin/python -m organizer undo
```

> **Files already in Downloads are left alone.** On its first run the service only looks
> at files that arrive afterwards. Use the Finder Quick Action (next step) for older files.

## 10. Turn on the Finder Quick Action

`setup.sh` installed a Quick Action. To use it, select one or more files anywhere in
Finder, right-click, and choose **Quick Actions > Rename with AI**. A notification shows
each new name.

If it is missing from the menu:

1. Right-click any file, choose **Quick Actions > Customize…**, and tick **Rename with AI**.
2. Or open **System Settings > General > Login Items & Extensions**, click the **(i)**
   next to **Finder**, and tick it there.

The first time, macOS may ask whether to allow notifications. The rename works either way.

## 11. Everyday use

Run these from the project folder (`cd ~/downloads-organizer`):

| Command | What it does |
| --- | --- |
| `.venv/bin/python -m organizer status` | Is the service running, queue size, model state, last 10 renames |
| `.venv/bin/python -m organizer undo` | Put back the name of the last renamed file |
| `.venv/bin/python -m organizer undo --today` | Put back every rename from today |
| `.venv/bin/python -m organizer once FILE` | Rename one file now |
| `.venv/bin/python -m organizer once FILE --dry-run` | Show the name it would pick, change nothing |
| `.venv/bin/python -m organizer doctor` | Check the setup |
| `.venv/bin/python -m organizer run --dry-run` | Watch Downloads and print proposals without renaming (stop the service first, see below) |

Service control:

```bash
launchctl kickstart -k gui/$(id -u)/com.user.downloads-organizer   # restart
launchctl bootout gui/$(id -u)/com.user.downloads-organizer        # stop until next setup.sh
./setup.sh                                                          # start again
```

Every file keeps its first name in an extended attribute:

```bash
xattr -p com.user.original-name ~/Downloads/some-renamed-file.pdf
```

## 12. Customize it

Settings live in `config.toml`. After any change, restart the service (see above).

| Setting | Default | Meaning |
| --- | --- | --- |
| `watch_folder` | `"~/Downloads"` | Folder to watch. Only its top level, not subfolders |
| `model` | `"gemma3:12b"` | Ollama model. Must read images |
| `ollama_host` | `"http://localhost:11434"` | Where Ollama listens |
| `keep_alive` | `-1` | Keep the model in memory. `"10m"` frees memory after 10 idle minutes; the next file then takes a few seconds longer |
| `max_name_length` | `60` | Longest name, not counting the extension |
| `min_confidence` | `0.4` | Below this the file keeps its name and only gets a tag |
| `max_content_bytes_gb` | `2` | Larger files are named from their filename and size only |
| `date_prefix` | `false` | `true` starts names with the file's date, like `2026-10-14-...` |
| `tags` | 31 tags | The model picks exactly one per file |

### Tags

Edit the `tags` list to add or remove tags. Short, distinct names work best: overlapping
tags (say `finance` and `receipts`) make the choice less predictable. Keep `installers`
(used for `.dmg`, `.pkg`, `.iso` without asking the model) and `other` (the fallback).

### How names are built

| Kind of file | Example result |
| --- | --- |
| Most files | `acme-power-electric-bill-2026-09-14.pdf` |
| Class notes, homework, worksheets | `2.4 Algebra 2 - Quadratic Functions.pdf` (section, class, title at the top of the page) |
| Numbered originals (`page_1.png`, `page_2.png`) | `math-textbook-page1.png`, `math-textbook-page2.png` |
| Numbered class notes | `2.4 Algebra 2 - Quadratic Functions page1.png` |
| Installers | `Docker Desktop (1).dmg` becomes `docker-desktop-1.dmg` |

Rules worth knowing:

- Dates appear only when the content shows one, as `yyyy-mm-dd`.
- Teacher names and class periods are left out of class-note names.
- Number labels kept from the original name: page, pg, p, part, slide, sheet, day, week,
  lesson, problem, question, step, or a bare number at the end (`notes_3`). Browser copy
  numbers like ` (1)` and camera counters like `IMG_0042` are dropped.
- If a name is taken, the new file gets `-2`, `-3` (or ` (2)` for class notes).
  Nothing is ever overwritten.

## 13. Update

```bash
cd ~/downloads-organizer
git pull
./setup.sh
```

Your `config.toml` changes are kept by `git pull` unless the same lines changed upstream;
git tells you if so.

## 14. Uninstall

```bash
cd ~/downloads-organizer
./uninstall.sh
```

This stops the service, removes its launchd file, and removes the Finder Quick Action.
Your renamed files stay as they are. To remove everything else:

```bash
rm -r ~/Library/Application\ Support/downloads-organizer   # rename history, undo data
rm -r ~/Library/Logs/downloads-organizer                    # logs
rm -r ~/downloads-organizer                                 # the code
ollama rm gemma3:12b                                        # the model (8 GB)
```

Also remove the Python entry from **Full Disk Access** if nothing else needs it.

## 15. Troubleshooting

Start with `doctor` and the log:

```bash
.venv/bin/python -m organizer doctor
tail -50 ~/Library/Logs/downloads-organizer/organizer.log
cat ~/Library/Logs/downloads-organizer/stderr.log
```

| Symptom | Cause and fix |
| --- | --- |
| Nothing gets renamed, log says `macOS denied access` | Full Disk Access is missing or points at an old Python. Redo [step 8](#8-grant-full-disk-access) |
| `doctor`: `Ollama reachable` fails | Open the Ollama app. Turn on **Launch at login** |
| `doctor`: model not installed | `ollama pull gemma3:12b` (or the model in `config.toml`) |
| `doctor`: service `not loaded in launchd` | Run `./setup.sh` |
| Log says `skipped ... reason=already processed` | That exact file was handled before (also after `undo`, on purpose). Use **Rename with AI** in Finder to redo it |
| An old file was not renamed | Files present before the first run are left alone. Use the Finder Quick Action |
| Name kept, only a tag added | The model was unsure (`low confidence` in the log). Lower `min_confidence` or rename it yourself |
| First file after login is slow | The model loads into memory once, 5 to 20 seconds |
| `./setup.sh: permission denied` | `chmod +x setup.sh uninstall.sh` |
| `zsh: no such file or directory: ./setup.sh` | You are in the wrong folder. `cd ~/downloads-organizer` first |
| Service keeps restarting | Read `stderr.log`. Often the project folder was moved: run `./setup.sh` from its new place |
| Quick Action missing | See [step 10](#10-turn-on-the-finder-quick-action). Then `.venv/bin/python -m organizer finder-action install` |
| Wrong tag for a kind of file | Make your tag list less overlapping, or add a clearer tag |

## 16. How it works

```
FSEvents ─▶ ignore rules ─▶ queue ─▶ worker ─▶ finished? ─▶ seen before? ─▶ read content
                                                                               │
          Finder tag ◀── rename (never overwrite) ◀── name rules ◀── local model
```

1. **Watch.** macOS FSEvents reports new, moved, and changed files in the top level of
   Downloads. Hidden files, folders, and partial downloads (`.crdownload`, `.download`,
   `.part`, `.partial`, `.tmp`, `.opdownload`) are ignored.
2. **Wait until finished.** Size and modification time must stay the same for three
   checks two seconds apart, and the file must open. It gives up after 15 minutes.
3. **Skip repeats.** A hash of the first 1 MB plus the size identifies each file, stored
   in `~/Library/Application Support/downloads-organizer/state.db`.
4. **Read.** Text files, PDFs (text, or an image of page 1 for scans), images, Word,
   Excel, ZIP listings, audio and video metadata, or the output of `file` for anything else.
5. **Ask the model.** Ollama answers with a name, one tag from your list, and a
   confidence, in a fixed JSON format. One file at a time.
6. **Rename and tag.** In place, with the macOS exclusive rename so no file is ever
   replaced. The rename is logged in `renames.jsonl`, which `undo` reads.

**Privacy.** The only network traffic is to Ollama on `localhost`. No cloud APIs.

**Files on your Mac:**

| Path | What |
| --- | --- |
| `~/Library/LaunchAgents/com.user.downloads-organizer.plist` | Tells macOS to run the service |
| `~/Library/Services/Rename with AI.workflow` | The Finder Quick Action |
| `~/Library/Application Support/downloads-organizer/` | `state.db`, `renames.jsonl` |
| `~/Library/Logs/downloads-organizer/` | `organizer.log` (5 MB, 3 backups), `stdout.log`, `stderr.log` |

### Run the tests

```bash
.venv/bin/python -m pytest            # about 170 tests, model mocked, under 10 seconds
.venv/bin/python -m pytest -m slow    # calls the real model
```
