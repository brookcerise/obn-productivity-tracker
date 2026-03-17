#!/usr/bin/env python3
"""
Obsidian Productivity Index (OBN-PI) Tracker

Calculates a composite productivity score based on:
  - Word Score (40% weight): words written today vs personal baseline
  - Depth Score (30% weight): paragraph length vs personal average
  - Consistency Score (30% weight): writing streak vs target

Usage:
  python3 obn_pi.py <vault_dir> [--config config.json]
  python3 obn_pi.py <vault_dir> --init        # First run, set baselines
  python3 obn_pi.py <vault_dir> --summary     # Print summary to stdout
  python3 obn_pi.py <vault_dir> --log-only    # Just update the log file
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "obn-productivity-tracker"
DEFAULT_CONFIG = {
    "target_streak_days": 5,
    "word_baseline": 1000,
    "avg_paragraph_length": 80,
    "history_file": "~/.obn_pi_history.json",
    "vault_dir": "",
}

# ── File Analysis ──────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    """Count words in text, ignoring code blocks and frontmatter."""
    text = strip_non_prose(text)
    return len(text.split())

def count_paragraphs(text: str) -> int:
    """Count paragraphs (separated by blank lines), ignoring code blocks."""
    text = strip_non_prose(text)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    return len(paragraphs)

def strip_non_prose(text: str) -> str:
    """Remove YAML frontmatter, code blocks, and wikilinks."""
    # Remove frontmatter
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
    # Remove code blocks
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    # Remove wikilinks (keep display text if present)
    text = re.sub(r'\[\[([^\]|]*?\|)?([^\]]*?)\]\]', r'\2', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    return text

def get_modified_files(vault_dir: str, since: datetime) -> list[Path]:
    """Get all markdown files modified since `since` timestamp."""
    vault = Path(vault_dir)
    if not vault.exists():
        print(f"Error: vault directory does not exist: {vault_dir}", file=sys.stderr)
        sys.exit(1)
    
    files = []
    for md_file in vault.rglob("*.md"):
        if md_file.is_file():
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
            if mtime >= since:
                files.append(md_file)
    return files

def analyze_day(vault_dir: str, target_date: datetime) -> dict:
    """Analyze all markdown files modified on a given date."""
    day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    files = get_modified_files(vault_dir, day_start)
    
    total_words = 0
    total_paragraphs = 0
    files_analyzed = 0
    
    for f in files:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if day_start <= mtime < day_end:
                content = f.read_text(encoding='utf-8', errors='replace')
                words = count_words(content)
                paragraphs = count_paragraphs(content)
                total_words += words
                total_paragraphs += paragraphs
                files_analyzed += 1
        except Exception as e:
            print(f"Warning: could not read {f}: {e}", file=sys.stderr)
    
    avg_paragraph_len = (total_words / total_paragraphs) if total_paragraphs > 0 else 0
    
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "words": total_words,
        "paragraphs": total_paragraphs,
        "avg_paragraph_length": round(avg_paragraph_len, 1),
        "files_modified": files_analyzed,
    }

# ── Scoring ────────────────────────────────────────────────────────────────

def calculate_word_score(words_today: int, baseline: int) -> float:
    """Word Score: (words today / baseline) × 100. Capped at 200."""
    if baseline <= 0:
        return 0
    return min((words_today / baseline) * 100, 200)

def calculate_depth_score(avg_para_len: float, baseline: float) -> float:
    """Depth Score: (avg paragraph today / baseline) × 100. Capped at 200."""
    if baseline <= 0:
        return 0
    return min((avg_para_len / baseline) * 100, 200)

def calculate_consistency_score(current_streak: int, target_days: int) -> float:
    """Consistency Score: (current streak / target) × 100. Capped at 100."""
    if target_days <= 0:
        return 0
    return min((current_streak / target_days) * 100, 100)

def calculate_productivity_index(word_score: float, depth_score: float, 
                                  consistency_score: float) -> float:
    """Composite: Word×0.4 + Depth×0.3 + Consistency×0.3"""
    return (word_score * 0.4) + (depth_score * 0.3) + (consistency_score * 0.3)

# ── History & Streaks ──────────────────────────────────────────────────────

def load_history(history_file: str) -> list[dict]:
    """Load analysis history from JSON file."""
    path = Path(os.path.expanduser(history_file))
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return []
    return []

def save_history(history_file: str, history: list[dict]):
    """Save analysis history to JSON file."""
    path = Path(os.path.expanduser(history_file))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2))

def calculate_streak(history: list[dict], target_date: str) -> int:
    """Calculate current writing streak ending at target_date."""
    if not history:
        return 0
    
    dates = sorted(set(entry["date"] for entry in history if entry["words"] > 0), reverse=True)
    if not dates:
        return 0
    
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    streak = 0
    current = target
    
    for d in dates:
        d_parsed = datetime.strptime(d, "%Y-%m-%d").date()
        if d_parsed == current:
            streak += 1
            current -= timedelta(days=1)
        elif d_parsed < current:
            break
    
    return streak

def update_baselines(config: dict, history: list[dict]) -> dict:
    """Recalculate baselines from history (rolling average of last 14 days)."""
    if len(history) < 3:
        return config
    
    recent = history[-14:]
    word_counts = [h["words"] for h in recent if h["words"] > 0]
    para_lengths = [h["avg_paragraph_length"] for h in recent if h["avg_paragraph_length"] > 0]
    
    if word_counts:
        config["word_baseline"] = round(sum(word_counts) / len(word_counts))
    if para_lengths:
        config["avg_paragraph_length"] = round(sum(para_lengths) / len(para_lengths))
    
    return config

# ── Output ─────────────────────────────────────────────────────────────────

def print_summary(day_data: dict, scores: dict, config: dict, streak: int):
    """Pretty-print the daily productivity summary."""
    pi = scores["productivity_index"]
    
    # Rating
    if pi >= 120:
        rating = "EXCEPTIONAL"
    elif pi >= 100:
        rating = "ABOVE BASELINE"
    elif pi >= 80:
        rating = "ON TRACK"
    elif pi >= 50:
        rating = "LIGHT DAY"
    elif pi > 0:
        rating = "MINIMAL"
    else:
        rating = "NO ACTIVITY"
    
    print(f"═══════════════════════════════════════════")
    print(f"  OBSIDIAN PRODUCTIVITY INDEX")
    print(f"  {day_data['date']}  |  {rating}")
    print(f"═══════════════════════════════════════════")
    print(f"")
    print(f"  📊 COMPOSITE SCORE: {pi:.1f}")
    print(f"")
    print(f"  Component Breakdown:")
    print(f"  ├─ Word Score:     {scores['word_score']:>6.1f}  (×0.4 = {scores['word_score']*0.4:.1f})")
    print(f"  ├─ Depth Score:    {scores['depth_score']:>6.1f}  (×0.3 = {scores['depth_score']*0.3:.1f})")
    print(f"  └─ Consistency:    {scores['consistency_score']:>6.1f}  (×0.3 = {scores['consistency_score']*0.3:.1f})")
    print(f"")
    print(f"  Raw Metrics:")
    print(f"  ├─ Words written:    {day_data['words']:>6}")
    print(f"  ├─ Avg para length:  {day_data['avg_paragraph_length']:>6.1f}")
    print(f"  ├─ Files modified:   {day_data['files_modified']:>6}")
    print(f"  └─ Writing streak:   {streak:>6} days")
    print(f"")
    print(f"  Baselines (rolling 14d):")
    print(f"  ├─ Word baseline:      {config['word_baseline']:>6}")
    print(f"  ├─ Paragraph baseline: {config['avg_paragraph_length']:>6.1f}")
    print(f"  └─ Target streak:      {config['target_streak_days']:>6} days/wk")
    print(f"═══════════════════════════════════════════")

def append_to_log(log_path: str, day_data: dict, scores: dict):
    """Append a daily summary to a markdown log file."""
    path = Path(os.path.expanduser(log_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    
    entry = (
        f"\n## {day_data['date']}\n"
        f"- **PI:** {scores['productivity_index']:.1f}\n"
        f"- **Words:** {day_data['words']} | **Avg Para:** {day_data['avg_paragraph_length']:.1f}\n"
        f"- **Files:** {day_data['files_modified']} | **Streak:** {scores['streak']} days\n"
        f"- **Components:** W={scores['word_score']:.1f} D={scores['depth_score']:.1f} C={scores['consistency_score']:.1f}\n"
    )
    
    with open(path, 'a', encoding='utf-8') as f:
        f.write(entry)

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Obsidian Productivity Index Tracker")
    parser.add_argument("vault_dir", help="Path to your Obsidian vault")
    parser.add_argument("--config", default="~/.obn_pi_config.json", help="Config file path")
    parser.add_argument("--init", action="store_true", help="Initialize config with baselines")
    parser.add_argument("--summary", action="store_true", help="Print summary to stdout")
    parser.add_argument("--log-only", action="store_true", help="Only update log, no stdout")
    parser.add_argument("--date", help="Analyze specific date (YYYY-MM-DD), default: today")
    parser.add_argument("--log", default="~/.obn_pi_log.md", help="Markdown log file path")
    args = parser.parse_args()
    
    # Load or create config
    config_path = Path(os.path.expanduser(args.config))
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = DEFAULT_CONFIG.copy()
    
    config["vault_dir"] = args.vault_dir
    
    # Determine target date
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        target_date = datetime.now()
    
    # Load history
    history_file = config.get("history_file", "~/.obn_pi_history.json")
    history = load_history(history_file)
    
    # Analyze today
    day_data = analyze_day(args.vault_dir, target_date)
    
    # Calculate streak
    streak = calculate_streak(history, day_data["date"])
    
    # Calculate scores
    word_score = calculate_word_score(day_data["words"], config["word_baseline"])
    depth_score = calculate_depth_score(day_data["avg_paragraph_length"], 
                                         config["avg_paragraph_length"])
    consistency_score = calculate_consistency_score(streak, config["target_streak_days"])
    
    pi = calculate_productivity_index(word_score, depth_score, consistency_score)
    
    scores = {
        "word_score": round(word_score, 2),
        "depth_score": round(depth_score, 2),
        "consistency_score": round(consistency_score, 2),
        "productivity_index": round(pi, 2),
        "streak": streak,
    }
    
    # Update history (don't duplicate same date)
    history = [h for h in history if h["date"] != day_data["date"]]
    history.append({**day_data, **scores})
    save_history(history_file, history)
    
    # Update baselines if enough history
    config = update_baselines(config, history)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))
    
    # Output
    if args.init:
        print("Initialized. Baselines set from today's analysis.")
        print(f"Config saved to: {config_path}")
    
    if args.summary or (not args.log_only and not args.init):
        print_summary(day_data, scores, config, streak)
    
    # Append to log
    append_to_log(args.log, day_data, scores)

if __name__ == "__main__":
    main()
