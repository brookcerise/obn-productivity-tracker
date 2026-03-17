#!/bin/bash
#
# Obsidian Productivity Index — Installer
#
# Usage:
#   ./install.sh /path/to/your/obsidian/vault
#   ./install.sh --uninstall
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/obn-pi"
BIN_DIR="$HOME/.local/bin"
PLIST_NAME="com.obn.productivity-tracker.plist"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/$PLIST_NAME"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${CYAN}[obn-pi]${NC} $*"; }
ok()    { echo -e "${GREEN}[obn-pi]${NC} $*"; }
warn()  { echo -e "${YELLOW}[obn-pi]${NC} $*"; }
error() { echo -e "${RED}[obn-pi]${NC} $*" >&2; }

# ── Uninstall ──────────────────────────────────────────────────────────────

if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "-u" ]; then
    info "Uninstalling obn-pi..."
    
    # Stop service
    if [ -f "$LAUNCH_AGENT" ]; then
        launchctl unload "$LAUNCH_AGENT" 2>/dev/null || true
        rm -f "$LAUNCH_AGENT"
        ok "Removed LaunchAgent"
    fi
    
    # Remove binary
    rm -f "$BIN_DIR/obn-pi"
    ok "Removed $BIN_DIR/obn-pi"
    
    # Keep install dir (has history/config)
    warn "Keeping $INSTALL_DIR (history/config preserved)"
    warn "Run 'rm -rf $INSTALL_DIR' to fully remove"
    
    ok "Uninstalled."
    exit 0
fi

# ── Install ────────────────────────────────────────────────────────────────

VAULT_DIR="${1:-}"

if [ -z "$VAULT_DIR" ]; then
    echo "Usage: ./install.sh /path/to/obsidian/vault"
    echo "       ./install.sh --uninstall"
    exit 1
fi

VAULT_DIR="$(cd "$VAULT_DIR" 2>/dev/null && pwd)"

if [ ! -d "$VAULT_DIR" ]; then
    error "Directory not found: $VAULT_DIR"
    exit 1
fi

info "Installing obn-pi..."
info "Vault: $VAULT_DIR"

# Create dirs
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$HOME/.obn-pi"

# Copy script
cp "$SCRIPT_DIR/obn_pi.py" "$INSTALL_DIR/obn_pi.py"
chmod +x "$INSTALL_DIR/obn_pi.py"
ok "Installed script to $INSTALL_DIR"

# Create symlink in ~/.local/bin
ln -sf "$INSTALL_DIR/obn_pi.py" "$BIN_DIR/obn-pi"
ok "Linked $BIN_DIR/obn-pi"

# Write config
cat > "$HOME/.obn-pi/config.json" <<EOF
{
  "target_streak_days": 5,
  "word_baseline": 1000,
  "avg_paragraph_length": 80,
  "vault_dir": "$VAULT_DIR",
  "history_file": "$HOME/.obn-pi/history.json"
}
EOF
ok "Config written"

# Create LaunchAgent
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENT_DIR"

cat > "$LAUNCH_AGENT_DIR/$PLIST_NAME" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.obn.productivity-tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$INSTALL_DIR/obn_pi.py</string>
        <string>--log-only</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>23</integer>
        <key>Minute</key>
        <integer>55</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/obn_pi.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/obn_pi.err</string>
</dict>
</plist>
EOF
ok "LaunchAgent created"

# Load service
launchctl load "$LAUNCH_AGENT_DIR/$PLIST_NAME"
ok "Service loaded (runs daily at 23:55)"

# Check PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR is not in your PATH"
    warn "Add this to your ~/.bashrc:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

# Initial run
info "Running initial analysis..."
"$BIN_DIR/obn-pi"

echo ""
ok "Done. Use obn-pi anywhere:"
echo "  obn-pi              Today's score"
echo "  obn-pi status       Service & vault info"
echo "  obn-pi plot         7-day TUI chart"
echo "  obn-pi 2026-03-15   Past date"
echo "  obn-pi uninstall    Remove service"
