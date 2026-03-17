# Obsidian Productivity Index (OBN-PI)

A lightweight macOS tool that tracks your Obsidian writing productivity and generates a composite score based on word output, writing depth, and consistency.

## The Index

```
Productivity Index = (Word Score × 0.4) + (Depth Score × 0.3) + (Consistency Score × 0.3)
```

### Component Breakdown

| Component | Weight | What it measures | Formula |
|-----------|--------|------------------|---------|
| **Word Score** | 40% | Output volume vs your baseline | `(words today / your avg words) × 100` |
| **Depth Score** | 30% | Paragraph length vs your average | `(avg para length / your avg para) × 100` |
| **Consistency Score** | 30% | Writing streak vs your target | `(current streak / target days) × 100` |

### Scoring

| PI Range | Rating |
|----------|--------|
| 120+ | EXCEPTIONAL |
| 100–119 | ABOVE BASELINE |
| 80–99 | ON TRACK |
| 50–79 | LIGHT DAY |
| 1–49 | MINIMAL |
| 0 | NO ACTIVITY |

## Quick Start

```bash
# Install (sets up daily macOS service)
./install.sh /path/to/your/obsidian/vault

# Manual run — today's summary
python3 obn_pi.py /path/to/vault

# Check a specific date
python3 obn_pi.py /path/to/vault --date 2026-03-15
```

## How It Works

1. **Scans** all `.md` files in your vault modified on the target day
2. **Strips** frontmatter, code blocks, and wikilinks (counts only prose)
3. **Calculates** word count, average paragraph length, and files modified
4. **Compares** against rolling 14-day baselines (auto-updates)
5. **Logs** to `~/.obn_pi_log.md` and `~/.obn_pi_history.json`

## Files

| File | Purpose |
|------|---------|
| `~/.obn_pi_config.json` | Baselines, targets, paths |
| `~/.obn_pi_history.json` | Daily analysis history |
| `~/.obn_pi_log.md` | Human-readable daily log |
| `~/Library/Logs/obn_pi.log` | Service stdout |

## Service Management

The installer creates a macOS LaunchAgent that runs daily at 23:55.

```bash
# Stop the service
launchctl unload ~/Library/LaunchAgents/com.obn.productivity-tracker.plist

# Start the service
launchctl load ~/Library/LaunchAgents/com.obn.productivity-tracker.plist

# Uninstall completely
./install.sh --uninstall
```

## Configuration

Edit `~/.obn_pi_config.json` to customize:

```json
{
  "target_streak_days": 5,
  "word_baseline": 1000,
  "avg_paragraph_length": 80,
  "vault_dir": "/path/to/vault",
  "history_file": "~/.obn_pi_history.json"
}
```

- **target_streak_days**: Days per week you want to write (affects consistency score)
- **word_baseline**: Your typical words per session (auto-adjusts after 3+ days)
- **avg_paragraph_length**: Your typical paragraph length (auto-adjusts after 3+ days)

## Requirements

- macOS (for the LaunchAgent service)
- Python 3.8+
- An Obsidian vault (or any directory with markdown files)

## License

MIT
