#!/usr/bin/env python3
"""
Obsidian Productivity Index (OBN-PI) — CLI entry point

Commands:
  obn-pi              Today's productivity summary
  obn-pi status       Service status
  obn-pi plot         7-day TUI chart
  obn-pi install      Install service (run once)
  obn-pi uninstall    Remove service
  obn-pi [DATE]       Summary for YYYY-MM-DD
  obn-pi --init       Initialize baselines
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "obn-pi"
CONFIG_DIR = Path.home() / ".obn-pi"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
LOG_FILE = CONFIG_DIR / "log.md"
SNAPSHOT_FILE = CONFIG_DIR / "snapshot.json"
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents/com.obn.productivity-tracker.plist"
INSTALL_DIR = Path.home() / ".local/share/obn-pi"
PLIST_NAME = "com.obn.productivity-tracker"

DEFAULT_CONFIG = {
    "target_streak_days": 5,
    "word_baseline": 500,
    "avg_paragraph_length": 80,
    "vault_dir": "",
}

# ── Colors ─────────────────────────────────────────────────────────────────

class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"

def color(text, *codes):
    return "".join(codes) + str(text) + C.RESET

# ── Config ─────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        # Merge defaults for missing keys
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# ── Text Analysis ──────────────────────────────────────────────────────────

def strip_non_prose(text: str) -> str:
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'\[\[([^\]|]*?\|)?([^\]]*?)\]\]', r'\2', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text

def count_words(text: str) -> int:
    return len(strip_non_prose(text).split())

def get_paragraph_stats(text: str) -> tuple:
    """Returns (paragraph_count, avg_paragraph_length)."""
    stripped = strip_non_prose(text)
    paras = [p.strip() for p in re.split(r'\n\s*\n', stripped) if p.strip()]
    if not paras:
        return 0, 0.0
    total_words = sum(len(p.split()) for p in paras)
    return len(paras), total_words / len(paras)

def file_hash(path: Path) -> str:
    """Quick hash of file content for change detection."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

# ── Snapshot System (for non-git vaults) ───────────────────────────────────

def load_snapshot() -> dict:
    """Load previous file snapshot: {filepath: {words: int, hash: str}}"""
    if SNAPSHOT_FILE.exists():
        try:
            return json.loads(SNAPSHOT_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def save_snapshot(snapshot: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2))

def take_snapshot(vault_dir: str) -> dict:
    """Snapshot all .md files: {filepath: {words, hash}}"""
    vault = Path(vault_dir)
    snap = {}
    for f in vault.rglob("*.md"):
        if f.is_file():
            try:
                content = f.read_text(encoding='utf-8', errors='replace')
                rel = str(f.relative_to(vault))
                snap[rel] = {
                    "words": count_words(content),
                    "hash": file_hash(f),
                    "paras": get_paragraph_stats(content)[0],
                }
            except Exception:
                pass
    return snap

def delta_from_snapshot(vault_dir: str, target_date: datetime) -> dict:
    """
    Calculate word delta by comparing current files against previous snapshot.
    Returns {total_words, delta_words, total_paras, avg_para_length, files_changed}.
    """
    vault = Path(vault_dir)
    prev_snapshot = load_snapshot()
    current_snapshot = take_snapshot(vault_dir)
    
    total_words = 0
    total_paras = 0
    para_word_total = 0
    files_changed = 0
    
    for rel_path, cur in current_snapshot.items():
        prev = prev_snapshot.get(rel_path, {"words": 0})
        delta = cur["words"] - prev["words"]
        
        if delta > 0:
            total_words += delta
            files_changed += 1
        
        total_words += 0  # only count increases
        # For paragraph stats, use current file stats
        fpath = vault / rel_path
        try:
            content = fpath.read_text(encoding='utf-8', errors='replace')
            paras, avg_len = get_paragraph_stats(content)
            if paras > 0:
                total_paras += paras
                para_word_total += int(avg_len * paras)
        except Exception:
            pass
    
    # Only count positive deltas (new words written)
    # Also include files that didn't exist before (new files)
    new_words = 0
    for rel_path, cur in current_snapshot.items():
        prev = prev_snapshot.get(rel_path)
        if prev is None:
            new_words += cur["words"]
        else:
            diff = cur["words"] - prev["words"]
            if diff > 0:
                new_words += diff
    
    avg_para = (para_word_total / total_paras) if total_paras > 0 else 0
    
    # Save current as new snapshot
    save_snapshot(current_snapshot)
    
    return {
        "total_words_in_vault": sum(c["words"] for c in current_snapshot.values()),
        "new_words": new_words,
        "files_changed": files_changed,
        "total_paras": total_paras,
        "avg_paragraph_length": round(avg_para, 1),
    }

# ── Git-based Delta (preferred for git-tracked vaults) ────────────────────

def is_git_repo(vault_dir: str) -> bool:
    """Check if vault is a git repo."""
    result = subprocess.run(
        ["git", "-C", vault_dir, "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True
    )
    return result.returncode == 0 and result.stdout.strip() == "true"

def delta_from_git(vault_dir: str, target_date: datetime) -> dict:
    """Use git diff to get word changes since yesterday."""
    day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = day_start - timedelta(days=1)
    
    # Get files changed on target date
    since_str = yesterday.strftime("%Y-%m-%d %H:%M:%S")
    until_str = day_start.strftime("%Y-%m-%d %H:%M:%S")
    
    # Get diff between yesterday's state and today's state
    # First, find the commit before target date
    try:
        # Get files that were modified on the target date
        result = subprocess.run(
            ["git", "-C", vault_dir, "log",
             f"--since={since_str}", f"--until={until_str}",
             "--pretty=format:", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True
        )
        changed_files = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()
    except Exception:
        changed_files = set()
    
    # For each changed file, get the diff
    new_words = 0
    total_paras = 0
    para_word_total = 0
    files_changed = 0
    vault = Path(vault_dir)
    
    for rel_path in changed_files:
        if not rel_path or not rel_path.endswith('.md'):
            continue
        fpath = vault / rel_path
        if not fpath.exists():
            continue
        
        try:
            # Get the diff for this file
            diff_result = subprocess.run(
                ["git", "-C", vault_dir, "diff", 
                 f"HEAD@{{{until_str}}}", "--", rel_path],
                capture_output=True, text=True
            )
            
            # Count added lines (excluding diff metadata)
            added_lines = []
            for line in diff_result.stdout.split('\n'):
                if line.startswith('+') and not line.startswith('+++'):
                    added_lines.append(line[1:])
            
            added_text = '\n'.join(added_lines)
            added_word_count = count_words(added_text)
            if added_word_count > 0:
                new_words += added_word_count
                files_changed += 1
            
            # Paragraph stats from current file
            content = fpath.read_text(encoding='utf-8', errors='replace')
            paras, avg_len = get_paragraph_stats(content)
            if paras > 0:
                total_paras += paras
                para_word_total += int(avg_len * paras)
                
        except Exception:
            pass
    
    # If git approach found nothing (e.g., committed in one shot), fall back to snapshot
    if new_words == 0 and files_changed == 0:
        return delta_from_snapshot(vault_dir, target_date)
    
    avg_para = (para_word_total / total_paras) if total_paras > 0 else 0
    
    return {
        "total_words_in_vault": 0,
        "new_words": new_words,
        "files_changed": files_changed,
        "total_paras": total_paras,
        "avg_paragraph_length": round(avg_para, 1),
    }

# ── Analyze Day ────────────────────────────────────────────────────────────

def analyze_day(vault_dir: str, target_date: datetime) -> dict:
    """
    Analyze writing for a given day. Uses git diff if available,
    falls back to snapshot delta.
    """
    if is_git_repo(vault_dir):
        delta = delta_from_git(vault_dir, target_date)
    else:
        delta = delta_from_snapshot(vault_dir, target_date)
    
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "words": delta["new_words"],
        "paragraphs": delta["total_paras"],
        "avg_paragraph_length": delta["avg_paragraph_length"],
        "files_modified": delta["files_changed"],
    }

# ── Scoring ────────────────────────────────────────────────────────────────

def calc_scores(day_data: dict, config: dict, streak: int) -> dict:
    ws = min((day_data["words"] / max(config["word_baseline"], 1)) * 100, 200)
    ds = min((day_data["avg_paragraph_length"] / max(config["avg_paragraph_length"], 1)) * 100, 200)
    cs = min((streak / max(config["target_streak_days"], 1)) * 100, 100)
    pi = (ws * 0.4) + (ds * 0.3) + (cs * 0.3)
    return {
        "word_score": round(ws, 2),
        "depth_score": round(ds, 2),
        "consistency_score": round(cs, 2),
        "productivity_index": round(pi, 2),
        "streak": streak,
    }

# ── History ────────────────────────────────────────────────────────────────

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []

def save_history(history: list):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))

def calc_streak(history: list, target_date: str) -> int:
    if not history:
        return 0
    dates = sorted(set(h["date"] for h in history if h["words"] > 0), reverse=True)
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

def update_baselines(config: dict, history: list) -> dict:
    if len(history) < 3:
        return config
    recent = history[-14:]
    words = [h["words"] for h in recent if h["words"] > 0]
    paras = [h["avg_paragraph_length"] for h in recent if h["avg_paragraph_length"] > 0]
    if words:
        config["word_baseline"] = round(sum(words) / len(words))
    if paras:
        config["avg_paragraph_length"] = round(sum(paras) / len(paras))
    return config

# ── Output: Summary ────────────────────────────────────────────────────────

def rating(pi: float) -> str:
    if pi >= 120: return color("EXCEPTIONAL", C.BOLD, C.GREEN)
    if pi >= 100: return color("ABOVE BASELINE", C.GREEN)
    if pi >= 80:  return color("ON TRACK", C.CYAN)
    if pi >= 50:  return color("LIGHT DAY", C.YELLOW)
    if pi > 0:    return color("MINIMAL", C.YELLOW)
    return color("NO ACTIVITY", C.DIM)

def print_summary(day_data: dict, scores: dict, config: dict):
    pi = scores["productivity_index"]
    bar_len = min(int(pi / 200 * 40), 40)
    bar = "█" * bar_len + "░" * (40 - bar_len)
    
    source = "git" if is_git_repo(config.get("vault_dir", ".")) else "snapshot"
    
    print()
    print(f"  {color('OBSIDIAN PRODUCTIVITY INDEX', C.BOLD, C.CYAN)}")
    print(f"  {day_data['date']}  ·  {rating(pi)}  {color(f'[{source}]', C.DIM)}")
    print()
    print(f"  {color(bar, C.CYAN)}")
    print(f"  {color(f'{pi:.1f}', C.BOLD)} / 200")
    print()
    print(f"  {color('Word', C.BOLD)}       {scores['word_score']:>6.1f}  (×0.4 = {scores['word_score']*0.4:.1f})")
    print(f"  {color('Depth', C.BOLD)}      {scores['depth_score']:>6.1f}  (×0.3 = {scores['depth_score']*0.3:.1f})")
    print(f"  {color('Consistency', C.BOLD)} {scores['consistency_score']:>6.1f}  (×0.3 = {scores['consistency_score']*0.3:.1f})")
    print()
    print(f"  +{day_data['words']} new words · {day_data['avg_paragraph_length']:.0f} avg para · "
          f"{day_data['files_modified']} files · {scores['streak']}d streak")
    print()

# ── Output: TUI Plot ──────────────────────────────────────────────────────

def print_plot():
    history = load_history()
    if not history:
        print("No history yet. Run obn-pi a few days first.")
        return
    
    last7 = history[-7:]
    
    max_pi = max(h.get("productivity_index", 0) for h in last7) if last7 else 100
    max_pi = max(max_pi, 50)
    chart_height = 12
    
    def bar_color(val, max_val):
        ratio = val / max(max_val, 1)
        if ratio >= 1.0: return C.GREEN
        if ratio >= 0.7: return C.CYAN
        if ratio >= 0.4: return C.YELLOW
        return C.RED
    
    print()
    print(f"  {color('PRODUCTIVITY INDEX — LAST 7 DAYS', C.BOLD, C.CYAN)}")
    print()
    
    col_width = 8
    cols = []
    for h in last7:
        pi = h.get("productivity_index", 0)
        label = h["date"][5:]
        val_str = f"{pi:.0f}"
        cols.append((label, pi, val_str))
    
    for row in range(chart_height, 0, -1):
        threshold = (row / chart_height) * max_pi
        line = "  "
        for label, pi, val_str in cols:
            if pi >= threshold:
                bc = bar_color(pi, max_pi)
                block = "██"
            else:
                bc = C.DIM
                block = "  "
            
            if row == chart_height and pi >= threshold:
                line += color(f"{val_str:>5}", bc) + "  "
            elif row == 1:
                line += color(label, C.DIM) + "  "
            else:
                line += block + "  "
        print(line)
    
    print(f"  {'─' * (col_width * len(cols))}")
    
    print()
    avg_pi = sum(h.get("productivity_index", 0) for h in last7) / len(last7)
    total_words = sum(h.get("words", 0) for h in last7)
    best = max(last7, key=lambda h: h.get("productivity_index", 0))
    print(f"  Avg: {color(f'{avg_pi:.0f}', C.CYAN)}  ·  "
          f"Total: {color(f'+{total_words} words', C.GREEN)}  ·  "
          f"Best: {color(best['date'][5:], C.YELLOW)} ({best.get('productivity_index', 0):.0f})")
    print()

# ── Output: Status ─────────────────────────────────────────────────────────

def print_status():
    print()
    print(f"  {color('OBN-PI STATUS', C.BOLD, C.CYAN)}")
    print()
    
    cfg = load_config()
    vault = cfg.get("vault_dir", "(not set)")
    print(f"  Vault:   {vault}")
    
    if vault and vault != "(not set)":
        method = "git diff" if is_git_repo(vault) else "file snapshot"
        print(f"  Method:  {method}")
    
    print(f"  Config:  {CONFIG_FILE}")
    print(f"  History: {HISTORY_FILE}")
    
    if LAUNCH_AGENT.exists():
        try:
            subprocess.run(["launchctl", "list", PLIST_NAME],
                          capture_output=True, timeout=5)
            print(f"  Service: {color('ACTIVE', C.GREEN)} (loaded)")
        except Exception:
            print(f"  Service: {color('LOADED', C.YELLOW)}")
        print(f"  Plist:   {LAUNCH_AGENT}")
    else:
        print(f"  Service: {color('NOT INSTALLED', C.RED)}")
    
    history = load_history()
    if history:
        total_days = len([h for h in history if h["words"] > 0])
        total_words = sum(h["words"] for h in history)
        print(f"  Days tracked:  {total_days}")
        print(f"  Total words:   +{total_words:,}")
        if history[-1]["words"] > 0:
            streak = calc_streak(history, history[-1]["date"])
            print(f"  Current streak: {streak} days")
    else:
        print(f"  History: no data yet")
    print()

# ── Commands ───────────────────────────────────────────────────────────────

def cmd_summary(date_str: str = None):
    cfg = load_config()
    if not cfg.get("vault_dir"):
        print("Error: No vault configured. Run 'obn-pi install /path/to/vault' first.")
        sys.exit(1)
    
    target = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
    history = load_history()
    streak = calc_streak(history, target.strftime("%Y-%m-%d"))
    day_data = analyze_day(cfg["vault_dir"], target)
    scores = calc_scores(day_data, cfg, streak)
    
    history = [h for h in history if h["date"] != day_data["date"]]
    history.append({**day_data, **scores})
    save_history(history)
    
    cfg = update_baselines(cfg, history)
    save_config(cfg)
    
    print_summary(day_data, scores, cfg)

def cmd_install(vault_dir: str):
    cfg = load_config()
    cfg["vault_dir"] = str(Path(vault_dir).resolve())
    save_config(cfg)
    
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    script_src = Path(__file__).resolve()
    script_dest = INSTALL_DIR / "obn_pi.py"
    
    import shutil
    shutil.copy2(script_src, script_dest)
    os.chmod(script_dest, 0o755)
    
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    
    # Symlink as obn-pi
    link = bin_dir / "obn-pi"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(script_dest)
    
    # Generate plist
    la_dir = Path.home() / "Library/LaunchAgents"
    la_dir.mkdir(parents=True, exist_ok=True)
    
    plist_path = la_dir / f"{PLIST_NAME}.plist"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{script_dest}</string>
        <string>--log-only</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{INSTALL_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>23</integer>
        <key>Minute</key>
        <integer>55</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{Path.home()}/Library/Logs/obn_pi.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/Library/Logs/obn_pi.err</string>
</dict>
</plist>"""
    
    plist_path.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
    
    # Check PATH
    path_check = ""
    if str(bin_dir) not in os.environ.get("PATH", ""):
        path_check = f"\n  ⚠️  Add to ~/.bashrc: export PATH=\"{bin_dir}:$PATH\""
    
    # Initial snapshot
    take_snapshot(cfg["vault_dir"])
    
    print(f"\n  {color('Installed!', C.GREEN, C.BOLD)}")
    print(f"  Vault: {cfg['vault_dir']}")
    print(f"  Command: {color('obn-pi', C.CYAN)} (in {bin_dir})")
    print(f"  Service: daily at 23:55")
    if path_check:
        print(f"  {path_check}")
    print()
    
    cmd_summary()

def cmd_uninstall():
    if LAUNCH_AGENT.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT)], capture_output=True)
        LAUNCH_AGENT.unlink()
        print(f"  {color('Service removed', C.GREEN)}")
    
    link = Path.home() / ".local/bin/obn-pi"
    if link.exists() or link.is_symlink():
        link.unlink()
        print(f"  {color('Command removed', C.GREEN)}")
    
    print(f"  Config/history preserved at {CONFIG_DIR}")
    print(f"  Run 'rm -rf {CONFIG_DIR}' to fully remove data")

def cmd_plot():
    print_plot()

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Obsidian Productivity Index",
        add_help=True,
    )
    parser.add_argument("command", nargs="?", default="summary",
                        help="summary | status | plot | install | uninstall | YYYY-MM-DD")
    parser.add_argument("vault_dir", nargs="?", default=None,
                        help="vault path (for install)")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--log-only", action="store_true")
    
    args = parser.parse_args()
    cmd = args.command
    
    if cmd == "install":
        if not args.vault_dir:
            print("Usage: obn-pi install /path/to/vault")
            sys.exit(1)
        cmd_install(args.vault_dir)
    elif cmd == "uninstall":
        cmd_uninstall()
    elif cmd == "status":
        print_status()
    elif cmd == "plot":
        cmd_plot()
    elif cmd == "summary" or cmd is None:
        cmd_summary()
    elif args.init or args.log_only:
        cmd_summary()
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', cmd):
        cmd_summary(cmd)
    else:
        print(f"Unknown command: {cmd}")
        print("Try: obn-pi | obn-pi status | obn-pi plot | obn-pi install /path/to/vault")
        sys.exit(1)

if __name__ == "__main__":
    main()
