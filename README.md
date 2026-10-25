# downloads-organizer

A macOS background service that watches `~/Downloads`. When a download finishes it reads
the content, asks a local Ollama model (`gemma3:12b`) for a descriptive filename and one
tag, renames the file in place, and sets the tag in Finder. Everything runs on this Mac.
No cloud APIs, no data leaves the machine.

```
Statement (4).pdf  ->  riverside-water-utility-bill-2026-10-03.pdf   [finance]
```

## Features

- Runs entirely on your Mac with [Ollama](https://ollama.com). No cloud, no API keys.
- Reads PDFs (including scans), images, Word, Excel, text, code, ZIPs, audio and video.
- One Finder tag per file from a list you control.
- Readable names for class notes: `2.4 Algebra 2 - Quadratic Functions.pdf`.
- Keeps page numbers: `page_1.png` becomes `math-textbook-page1.png`.
- Right-click any file in Finder > **Quick Actions > Rename with AI**.
- Never overwrites or deletes a file. `undo` puts names back.
- Starts at login and restarts itself after a crash.

## Install

**New to this? Follow the [step-by-step setup guide](docs/SETUP.md).** It covers
Homebrew, Python, Ollama, Full Disk Access, and troubleshooting.

Short version, if you already have Homebrew, Python 3.12+, and Ollama running:

```bash
git clone https://github.com/SB-Sachin/downloads-organizer.git ~/downloads-organizer
cd ~/downloads-organizer
./setup.sh
```

Then grant Full Disk Access to the Python binary that `setup.sh` prints
([how](docs/SETUP.md#8-grant-full-disk-access)), restart the service with
`launchctl kickstart -k gui/$(id -u)/com.user.downloads-organizer`, and turn on
**Launch at login** in the Ollama app settings.

## Commands

Run these from this folder.

| Command | What it does |
| --- | --- |
| `.venv/bin/python -m organizer run` | Start the watcher in the foreground |
| `.venv/bin/python -m organizer run --dry-run` | Print the proposed name and tag, rename nothing |
| `.venv/bin/python -m organizer once PATH` | Process one file (`--dry-run` previews, `--force` redoes a handled file) |
| `.venv/bin/python -m organizer undo` | Revert the last rename |
| `.venv/bin/python -m organizer undo --today` | Revert every rename made today |
| `.venv/bin/python -m organizer status` | Service state, queue size, model state, last 10 renames |
| `.venv/bin/python -m organizer doctor` | Check Ollama, the model, the tag tool, and folder access |

Stop the launchd service before using `run` in the foreground, or two copies will watch
the same folder:

```bash
launchctl bootout gui/$(id -u)/com.user.downloads-organizer
```

## Rename from Finder

`setup.sh` adds a Finder Quick Action. Select one or more files in any folder, right-click,
and choose **Quick Actions > Rename with AI**. Each file is renamed and tagged, and a
notification shows the result. It works on files the service has already handled, and
`undo` reverts these renames too.

If the menu item is missing, turn it on in **System Settings > General > Login Items &
Extensions > Finder** (or right-click > Quick Actions > Customize...). To add or remove it
by hand:

```bash
.venv/bin/python -m organizer finder-action install
.venv/bin/python -m organizer finder-action remove
```

## Configuration

Edit `config.toml`, then restart the service with the `kickstart` command above.

| Setting | Default | Meaning |
| --- | --- | --- |
| `watch_folder` | `~/Downloads` | Folder to watch (top level only) |
| `model` | `gemma3:12b` | Ollama model; must read images |
| `ollama_host` | `http://localhost:11434` | Ollama server |
| `keep_alive` | `-1` | Keep the model loaded in memory |
| `max_name_length` | `60` | Longest name, cut at a hyphen |
| `min_confidence` | `0.4` | Below this the name is kept and only the tag is applied |
| `max_content_bytes_gb` | `2` | Larger files are named from metadata only |
| `date_prefix` | `false` | Prefix names with the file's modification date |
| `tags` | 31 preset tags | The model picks exactly one; add or remove names freely |

## How it behaves

- **Ignored:** hidden files, directories, symlinks, empty files, and partial downloads
  (`.crdownload`, `.download`, `.part`, `.partial`, `.tmp`, `.opdownload`), including the
  placeholder file a browser keeps beside a partial download.
- **Finished means:** size and modification time identical for 3 readings 2 seconds apart,
  and the file opens for reading. It gives up after 15 minutes.
- **First run:** files already in Downloads are left alone. Only new downloads are handled.
  After that, files that arrived while the service was off are picked up at startup.
- **Never overwrites:** a name collision gets `-2`, `-3`, and so on. Renames use the macOS
  exclusive rename call, so two files can never race onto one name. Files never leave
  the folder and are never deleted.
- **Seen once:** each file is identified by a hash of its first 1 MB plus its size. A file
  already handled is skipped, so a file you undo or rename by hand stays as you left it.
  A second download of an identical file is also skipped.
- **Class notes, homework, and worksheets** are named the way the page reads:
  `2.4 Algebra 2 - Quadratic Functions.pdf` (section, class, then the unit title from the
  top of the page). The teacher's name and class period are left out. A second page with
  the same name becomes `... (2).pdf`. If the page shows no title, or neither a section
  nor a class, the normal hyphenated name is used.
- **Page and sequence numbers** in the original name carry over, so `page_1.png`,
  `page_2.png` become `math-textbook-page1.png`, `math-textbook-page2.png` (or
  `2.4 Algebra 2 - Quadratic Functions page1.png` for class notes). Labels kept: page, pg,
  p, part, slide, sheet, day, week, lesson, problem, question, step, or a bare trailing
  number (`notes_3`). Browser copy numbers like ` (1)` and camera counters like
  `IMG_0042` are not kept.
- **Installers** (`.dmg`, `.pkg`, `.iso`) get a cleaned-up version of their own name and
  the `installers` tag with no model call. `.app` bundles are directories and are skipped.
- **Original name:** stored on the file in the `com.user.original-name` extended attribute:

```bash
xattr -p com.user.original-name ~/Downloads/some-file.pdf
```

- **Undo** restores the name. It leaves the Finder tag in place.

## Files

| Path | Contents |
| --- | --- |
| `~/Library/Logs/downloads-organizer/organizer.log` | Every decision (5 MB x 3 backups) |
| `~/Library/Logs/downloads-organizer/stderr.log` | Crashes before logging starts |
| `~/Library/Application Support/downloads-organizer/renames.jsonl` | Every rename, used by `undo` |
| `~/Library/Application Support/downloads-organizer/state.db` | Processed hashes, last-seen time |

## Tests

```bash
.venv/bin/python -m pytest            # fast suite, model mocked
.venv/bin/python -m pytest -m slow    # calls the real model with a text file and an image
```

## Uninstall

```bash
./uninstall.sh
```

This stops the agent and removes the plist. The state database and logs stay in place.

## Troubleshooting

- **Nothing gets renamed:** run `doctor`. The usual cause is missing Full Disk Access.
- **Service keeps restarting:** read `~/Library/Logs/downloads-organizer/stderr.log`.
- **Slow first rename after login:** the model takes a few seconds to load into memory.
