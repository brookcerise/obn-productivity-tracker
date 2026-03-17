# Obsidian Productivity Index (obn-pi)

A lightweight macOS CLI tool that tracks your Obsidian writing productivity and generates a composite score based on word output, writing depth, and consistency.

## The Index

```
Productivity Index = (Word Score × 0.4) + (Depth Score × 0.3) + (Consistency Score × 0.3)
```

| Component | Weight | Formula |
|-----------|--------|---------|
| **Word Score** | 40% | `(words today / your avg) × 100` |
| **Depth Score** | 30% | `(avg para length / your avg) × 100` |
| **Consistency Score** | 30% | `(streak days / target) × 100` |

## Install

```bash
git clone https://github.com/brookcerise/obn-productivity-tracker.git
cd obn-productivity-tracker
./install.sh /path/to/your/obsidian/vault
```

Add `~/.local/bin` to your PATH if not already there:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Commands

```bash
obn-pi                  # Today's productivity summary
obn-pi status           # Service status, vault info, history stats
obn-pi plot             # 7-day TUI bar chart
obn-pi 2026-03-15       # Score for a specific date
obn-pi uninstall        # Remove the service
```

## Scoring

| PI Range | Rating |
|----------|--------|
| 120+ | EXCEPTIONAL |
| 100–119 | ABOVE BASELINE |
| 80–99 | ON TRACK |
| 50–79 | LIGHT DAY |
| 1–49 | MINIMAL |
| 0 | NO ACTIVITY |

## How It Works

1. Scans all `.md` files in your vault modified on the target day
2. Strips frontmatter, code blocks, and wikilinks (counts prose only)
3. Calculates word count, average paragraph length, files modified
4. Compares against rolling 14-day baselines (auto-adjusts after 3+ days)
5. Logs to `~/.obn-pi/log.md` and `~/.obn-pi/history.json`

## Service

The installer creates a macOS LaunchAgent that runs daily at 23:55.

```bash
launchctl load ~/Library/LaunchAgents/com.obn.productivity-tracker.plist    # start
launchctl unload ~/Library/LaunchAgents/com.obn.productivity-tracker.plist  # stop
```

## Files

| File | Purpose |
|------|---------|
| `~/.obn-pi/config.json` | Baselines, targets, vault path |
| `~/.obn-pi/history.json` | Daily analysis history |
| `~/.obn-pi/log.md` | Human-readable daily log |
| `~/.local/share/obn-pi/obn_pi.py` | Installed script |

## Requirements

- macOS (for the LaunchAgent service)
- Python 3.8+
- An Obsidian vault (or any directory with markdown files)
