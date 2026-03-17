#!/bin/bash
#
# Obsidian Productivity Index — Installer
# Installs obn_pi.py as a macOS LaunchAgent service
#
# Usage:
#   ./install.sh /path/to/your/obsidian/vault
#   ./install.sh /path/to/vault --uninstall
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.obn-productivity-tracker"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.obn.productivity-tracker.plist"
PLIST_PATH="$LAUNCH_AGENT_DIR/$PLIST_NAME"

# ── Helpers ────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[obn-pi]${NC} $*"; }
ok()    { echo -e "${GREEN}[obn-pi]${NC} $*"; }
warn()  { echo -e "${YELLOW}[obn-pi]${NC} $*"; }
error() { echo -e "${RED}[obn-pi]${NC} $*" >&2; }

# ── Uninstall ──────────────────────────────────────────────────────────────

uninstall() {
    info "Uninstalling Obsidian Productivity Index..."
    
    # Stop and unload service
    if [ -f "$PLIST_PATH" ]; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        rm -f "$PLIST_PATH"
        ok "Removed LaunchAgent"
    fi
    
    # Remove installed files (keep history/config)
    if [ -d "$INSTALL_DIR" ]; then
        rm -f "$INSTALL_DIR/obn_pi.py"
        warn "Keeping $INSTALL_DIR for history/config persistence"
    fi
    
    ok "Uninstalled. History and config preserved at $INSTALL_DIR"
    exit 0
}

# ── Install ────────────────────────────────────────────────────────────────

install() {
    local VAULT_DIR="$1"
    
    if [ -z "$VAULT_DIR" ]; then
        error "Usage: install.sh /path/to/obsidian/vault"
        exit 1
    fi
    
    VAULT_DIR="$(cd "$VAULT_DIR" && pwd)"
    
    if [ ! -d "$VAULT_DIR" ]; then
        error "Vault directory not found: $VAULT_DIR"
        exit 1
    fi
    
    info "Installing Obsidian Productivity Index..."
    info "Vault: $VAULT_DIR"
    
    # Create install directory
    mkdir -p "$INSTALL_DIR"
    
    # Copy script
    cp "$SCRIPT_DIR/obn_pi.py" "$INSTALL_DIR/obn_pi.py"
    chmod +x "$INSTALL_DIR/obn_pi.py"
    ok "Copied obn_pi.py to $INSTALL_DIR"
    
    # Generate plist with correct paths
    mkdir -p "$LAUNCH_AGENT_DIR"
    sed -e "s|OBN_PI_INSTALL_DIR|$INSTALL_DIR|g" \
        -e "s|OBN_PI_VAULT_DIR|$VAULT_DIR|g" \
        "$SCRIPT_DIR/com.obn.productivity-tracker.plist" > "$PLIST_PATH"
    ok "Generated LaunchAgent plist"
    
    # Load service
    launchctl load "$PLIST_PATH"
    ok "Service loaded — will run daily at 23:55"
    
    # Initialize with today's data
    info "Running initial analysis..."
    python3 "$INSTALL_DIR/obn_pi.py" "$VAULT_DIR" --init
    
    echo ""
    ok "Installation complete!"
    echo ""
    info "Commands:"
    echo "  python3 $INSTALL_DIR/obn_pi.py $VAULT_DIR          # Today's summary"
    echo "  python3 $INSTALL_DIR/obn_pi.py $VAULT_DIR --log    # View log"
    echo "  python3 $INSTALL_DIR/obn_pi.py $VAULT_DIR --date 2026-03-15  # Past date"
    echo ""
    info "Files:"
    echo "  Config:  ~/.obn_pi_config.json"
    echo "  History: ~/.obn_pi_history.json"
    echo "  Log:     ~/.obn_pi_log.md"
    echo ""
    info "Service management:"
    echo "  launchctl load $PLIST_PATH      # Start"
    echo "  launchctl unload $PLIST_PATH    # Stop"
    echo "  ./install.sh --uninstall        # Remove"
}

# ── Main ───────────────────────────────────────────────────────────────────

case "${1:-}" in
    --uninstall|-u)
        uninstall
        ;;
    --help|-h)
        echo "Usage: ./install.sh /path/to/obsidian/vault"
        echo "       ./install.sh --uninstall"
        echo "       ./install.sh --help"
        ;;
    *)
        install "$1"
        ;;
esac
