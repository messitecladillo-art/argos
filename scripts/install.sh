#!/usr/bin/env bash
# Argos — Linux/macOS installer
# Run: curl -fsSL https://raw.githubusercontent.com/messitecladillo-art/argos/main/scripts/install.sh | bash
set -euo pipefail

BRANCH="${1:-main}"
REPO_URL="https://github.com/messitecladillo-art/argos.git"
INSTALL_DIR="${ARGOS_HOME:-$HOME/.argos}"

echo -e "\033[1;36m"
echo "  +--------------------------------------------------+"
echo "  |       A R G O S                                   |"
echo "  |       Multi-Agent Collaboration System            |"
echo "  +--------------------------------------------------+"
echo -e "\033[0m"

echo -e "\033[90mInstalling to: $INSTALL_DIR\033[0m"

# ── Check Python ──────────────────────────────────────
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oP '3\.(1[1-9]|[2-9])')
        if [[ -n "$ver" ]]; then
            PYTHON_CMD="$cmd"
            echo -e "\033[32mFound Python: $($PYTHON_CMD --version) ($cmd)\033[0m"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo -e "\033[31mERROR: Python 3.11+ is required.\033[0m"
    exit 1
fi

# ── Clone or update ───────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo -e "\033[90mUpdating existing install...\033[0m"
    git -C "$INSTALL_DIR" pull origin "$BRANCH"
else
    echo -e "\033[90mCloning Argos...\033[0m"
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
        echo -e "\033[33mGit clone failed. Downloading zip...\033[0m"
        curl -fsSL "https://github.com/messitecladillo-art/argos/archive/refs/heads/$BRANCH.zip" -o /tmp/argos.zip
        unzip -qo /tmp/argos.zip -d /tmp
        mv "/tmp/argos-$BRANCH" "$INSTALL_DIR"
        rm /tmp/argos.zip
    }
fi

# ── Setup venv ────────────────────────────────────────
cd "$INSTALL_DIR"
echo -e "\033[90mCreating virtual environment...\033[0m"
"$PYTHON_CMD" -m venv .venv
VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"

# ── Install ───────────────────────────────────────────
echo -e "\033[90mInstalling dependencies...\033[0m"
"$VENV_PYTHON" -m pip install --upgrade pip -q
"$VENV_PYTHON" -m pip install -e . -q

# ── Generate .env ─────────────────────────────────────
if [[ ! -f ".env" ]]; then
    SECRET_KEY=$("$VENV_PYTHON" -c "import secrets; print(secrets.token_hex(32))")
    cp .env.example .env
    sed -i "s/^# SECRET_KEY=/SECRET_KEY=$SECRET_KEY/" .env
    echo -e "\033[32mGenerated .env with SECRET_KEY\033[0m"
fi

# ── Symlink binaries ──────────────────────────────────
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV_PYTHON" "$HOME/.local/bin/argos-python"
cat > "$HOME/.local/bin/argos-cli" << 'SCRIPT'
#!/usr/bin/env bash
exec "$HOME/.argos/.venv/bin/python" -m argos.cli "$@"
SCRIPT
cat > "$HOME/.local/bin/argos-tui" << 'SCRIPT'
#!/usr/bin/env bash
exec "$HOME/.argos/.venv/bin/python" -m argos.tui.app "$@"
SCRIPT
chmod +x "$HOME/.local/bin/argos-cli" "$HOME/.local/bin/argos-tui"

cd /

# ── Success ───────────────────────────────────────────
echo ""
echo -e "\033[1;32m  +--------------------------------------------------+"
echo    "  |       Installation Complete!                      |"
echo -e "  +--------------------------------------------------+\033[0m"
echo ""
echo "  Ensure ~/.local/bin is in your PATH, then:"
echo ""
echo -e "  \033[1;36m  argos-cli info\033[0m       # System overview"
echo -e "  \033[1;36m  argos-cli check\033[0m      # Configuration check"
echo -e "  \033[1;36m  argos-tui\033[0m           # Terminal dashboard"
echo ""
echo "  Start the web server:"
echo -e "  \033[1;36m  cd $INSTALL_DIR && $VENV_PYTHON run.py\033[0m"
echo ""
