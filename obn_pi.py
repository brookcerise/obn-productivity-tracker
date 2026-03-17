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
PLIST_NAME = "com.obn.productivity-tracker"
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents" / f"{PLIST_NAME}.plist"
INSTALL_DIR = Path.home() / ".local/share/obn-pi"

DEFAULT_CONFIG = {
    "target_streak_days": 5,
    "word_baseline": 1000,
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
    MAGENTA = "\033[35m"
    RESET = "\033[0m"

def color(text, *codes):
    return "".join(codes) + str(text) + C.RESET

# ── Config ─────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# ── File Analysis ──────────────────────────────────────────────────────────

def strip_non_prose(text: str) -> str:
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'\[\[([^\]|]*?\|)?([^\]]*?)\]\]', r'\2', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text

def count_words(text: str) -> int:
    return len(strip_non_prose(text).split())

def count_paragraphs(text: str) -> int:
    stripped = strip_non_prose(text)
    return len([p for p in re.split(r'\n\s*\n', stripped) if p.strip()])

def get_modified_files(vault_dir: str, since: datetime) -> list[Path]:
    vault = Path(vault_dir)
    if not vault.exists():
        print(f"Error: vault not found: {vault_dir}", file=sys.stderr)
        sys.exit(1)
    return [f for f in vault.rglob("*.md") if f.is_file() 
            and datetime.fromtimestamp(f.stat().st_mtime) >= since]

def analyze_day(vault_dir: str, target_date: datetime) -> dict:
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
                total_words += count_words(content)
                total_paragraphs += count_paragraphs(content)
                files_analyzed += 1
        except Exception:
            pass
    
    avg_para = (total_words / total_paragraphs) if total_paragraphs > 0 else 0
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "words": total_words,
        "paragraphs": total_paragraphs,
        "avg_paragraph_length": round(avg_para, 1),
        "files_modified": files_analyzed,
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
    
    print()
    print(f"  {color('OBSIDIAN PRODUCTIVITY INDEX', C.BOLD, C.CYAN)}")
    print(f"  {day_data['date']}  ·  {rating(pi)}")
    print()
    print(f"  {color(bar, C.CYAN)}")
    print(f"  {color(f'{pi:.1f}', C.BOLD)} / 200")
    print()
    print(f"  {color('Word', C.BOLD)}       {scores['word_score']:>6.1f}  (×0.4 = {scores['word_score']*0.4:.1f})")
    print(f"  {color('Depth', C.BOLD)}      {scores['depth_score']:>6.1f}  (×0.3 = {scores['depth_score']*0.3:.1f})")
    print(f"  {color('Consistency', C.BOLD)} {scores['consistency_score']:>6.1f}  (×0.3 = {scores['consistency_score']*0.3:.1f})")
    print()
    print(f"  {day_data['words']} words · {day_data['avg_paragraph_length']:.0f} avg para · "
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
    max_pi = max(max_pi, 50)  # floor for readability
    chart_height = 12
    
    # Colors for gradient
    def bar_color(val, max_val):
        ratio = val / max(max_val, 1)
        if ratio >= 1.0: return C.GREEN
        if ratio >= 0.7: return C.CYAN
        if ratio >= 0.4: return C.YELLOW
        return C.RED
    
    print()
    print(f"  {color('PRODUCTIVITY INDEX — LAST 7 DAYS', C.BOLD, C.CYAN)}")
    print()
    
    # Build columns
    col_width = 8
    cols = []
    for h in last7:
        pi = h.get("productivity_index", 0)
        label = h["date"][5:]  # MM-DD
        val_str = f"{pi:.0f}"
        cols.append((label, pi, val_str))
    
    # Render chart top to bottom
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
            
            # Show value at the top of each bar
            if row == chart_height and pi >= threshold:
                line += color(f"{val_str:>5}", bc) + "  "
            elif row == 1:
                line += color(label, C.DIM) + "  "
            else:
                line += block + "  "
        print(line)
    
    # X-axis
    print(f"  {'─' * (col_width * len(cols))}")
    
    # Legend
    print()
    avg_pi = sum(h.get("productivity_index", 0) for h in last7) / len(last7)
    total_words = sum(h.get("words", 0) for h in last7)
    best = max(last7, key=lambda h: h.get("productivity_index", 0))
    print(f"  Avg: {color(f'{avg_pi:.0f}', C.CYAN)}  ·  "
          f"Total: {color(f'{total_words} words', C.GREEN)}  ·  "
          f"Best: {color(best['date'][5:], C.YELLOW)} ({best.get('productivity_index', 0):.0f})")
    print()

# ── Output: Status ─────────────────────────────────────────────────────────

def print_status():
    print()
    print(f"  {color('OBN-PI STATUS', C.BOLD, C.CYAN)}")
    print()
    
    # Config
    cfg = load_config()
    vault = cfg.get("vault_dir", "(not set)")
    print(f"  Vault:   {vault}")
    print(f"  Config:  {CONFIG_FILE}")
    print(f"  History: {HISTORY_FILE}")
    
    # Service
    if LAUNCH_AGENT.exists():
        try:
            result = subprocess.run(
                ["launchctl", "list", PLIST_NAME],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Parse PID
                pid_line = [l for l in result.stdout.splitlines() if '"' in l]
                print(f"  Service: {color('ACTIVE', C.GREEN)} (loaded)")
            else:
                print(f"  Service: {color('LOADED', C.YELLOW)} (not running)")
        except Exception:
            print(f"  Service: {color('LOADED', C.YELLOW)}")
        print(f"  Plist:   {LAUNCH_AGENT}")
    else:
        print(f"  Service: {color('NOT INSTALLED', C.RED)}")
    
    # History stats
    history = load_history()
    if history:
        total_days = len([h for h in history if h["words"] > 0])
        total_words = sum(h["words"] for h in history)
        print(f"  Days tracked:  {total_days}")
        print(f"  Total words:   {total_words:,}")
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
    
    # Update history
    history = [h for h in history if h["date"] != day_data["date"]]
    history.append({**day_data, **scores})
    save_history(history)
    
    # Update baselines
    cfg = update_baselines(cfg, history)
    save_config(cfg)
    
    print_summary(day_data, scores, cfg)

def cmd_install(vault_dir: str):
    cfg = load_config()
    cfg["vault_dir"] = str(Path(vault_dir).resolve())
    save_config(cfg)
    
    # Ensure script is in install dir
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    script_src = Path(__file__).resolve()
    script_dest = INSTALL_DIR / "obn_pi.py"
    
    import shutil
    shutil.copy2(script_src, script_dest)
    os.chmod(script_dest, 0o755)
    
    # Generate plist
    la_dir = Path.home() / "Library/LaunchAgents"
    la_dir.mkdir(parents=True, exist_ok=True)
    
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
    
    LAUNCH_AGENT.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(LAUNCH_AGENT)], capture_output=True)
    
    print(f"  {color('Installed!', C.GREEN, C.BOLD)}")
    print(f"  Vault: {cfg['vault_dir']}")
    print(f"  Service: runs daily at 23:55")
    print()
    
    # Initialize
    cmd_summary()

def cmd_uninstall():
    if LAUNCH_AGENT.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT)], capture_output=True)
        LAUNCH_AGENT.unlink()
        print(f"  {color('Service removed', C.GREEN)}")
    
    cfg = load_config()
    vault = cfg.get("vault_dir", "")
    
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
    
    # Route command
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
    elif args.init:
        cmd_summary()
    elif args.log_only:
        cmd_summary()
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', cmd):
        cmd_summary(cmd)
    else:
        print(f"Unknown command: {cmd}")
        print("Try: obn-pi | obn-pi status | obn-pi plot | obn-pi install /path/to/vault")
        sys.exit(1)

if __name__ == "__main__":
    main()
