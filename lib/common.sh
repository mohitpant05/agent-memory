#!/usr/bin/env bash
# Shared helpers. Sourced by the entrypoint; not executed directly.

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m%s\033[0m\n' "$*"; }
warn() { printf '  \033[33m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

detect_platform() {
  case "$(uname -s)" in
    Darwin) echo macos ;;
    Linux)
      # WSL is Linux, but Docker/GPU behave differently enough to name it.
      if grep -qi microsoft /proc/version 2>/dev/null; then echo wsl; else echo linux; fi ;;
    *) echo unsupported ;;
  esac
}

# Locate patches/. A missing patch does NOT fail loudly at runtime - it silently
# reproduces the "extraction returns zero facts" trap - so resolve it here and
# abort if absent.
find_patches() {
  local c
  : "${REPO_ROOT:=$PWD}"
  for c in "$REPO_ROOT/patches" "$PWD/patches" "$HOME/.mem0/patches" "/opt/mem0/patches"; do
    if [ -f "$c/zz_mem0_qwen_patch.py" ] && [ -f "$c/fact_prompt.txt" ]; then
      printf '%s\n' "$(cd "$c" && pwd)"; return 0
    fi
  done
  return 1
}

# ollama list prints "name:latest"; a bare "name" never matches without this.
model_present() {
  ollama list 2>/dev/null | awk '{print $1}' | sed 's/:latest$//' | grep -qx "${1%:latest}"
}

ensure_model() {
  if model_present "$1"; then ok "$1 present"; else
    printf '  pulling %s ...\n' "$1"; ollama pull "$1"
  fi
}

wait_for() {
  local url="$1" name="$2" tries="${3:-30}"
  while [ "$tries" -gt 0 ]; do
    tries=$((tries - 1))
    curl -sf -m 3 "$url" >/dev/null 2>&1 && { ok "$name ready"; return 0; }
    sleep 2
  done
  fail "$name did not become ready at $url"
}

# Install the runtime patches into a venv's site-packages and point .env at the
# prompt file's real location on THIS machine.
install_patches() {
  local venv="$1" envfile="$2" patches sp
  patches="$(find_patches)" || fail "patches/ not found (need zz_mem0_qwen_patch.py + fact_prompt.txt)"
  sp="$(echo "$venv"/lib/python3.*/site-packages)"
  cp "$patches/zz_mem0_qwen_patch.py" "$sp/"
  printf 'import zz_mem0_qwen_patch\n' > "$sp/zz_mem0_qwen_patch.pth"
  if grep -q '^MEM0_FACT_PROMPT_FILE=' "$envfile"; then
    sed -i.bak "s|^MEM0_FACT_PROMPT_FILE=.*|MEM0_FACT_PROMPT_FILE=$patches/fact_prompt.txt|" "$envfile"
    rm -f "$envfile.bak"
  else
    printf 'MEM0_FACT_PROMPT_FILE=%s/fact_prompt.txt\n' "$patches" >> "$envfile"
  fi
  ok "runtime patches installed (think=False, fact prompt, delete guard)"
}

# Dependencies are installed explicitly, then the wrapper with --no-deps:
#
#  1. Upstream declares mcp[cli]>=1.23.0 and mem0ai>=1.0.3 with no upper bound,
#     but the pinned commit predates both 2.x releases. mcp 2.x renamed
#     FastMCP -> MCPServer (the server cannot import); mem0ai 2.x moved
#     search(user_id=) to search(filters={...}) which hooks.py still calls the
#     old way. Both need a ceiling.
#
#  2. Upstream asks for mem0ai[graph], which drags in apache-age-python ->
#     psycopg2. That is source-only, needs pg_config AND openssl to link, and is
#     never imported here because the graph layer is disabled. Dropped entirely
#     rather than fought with.
install_server() {
  local venv="$1" ref="$2"
  uv venv --clear --python 3.12 "$venv" >/dev/null
  VIRTUAL_ENV="$venv" uv pip install --quiet \
    "mcp[cli]>=1.23,<2" \
    "mem0ai[llms]>=1.0.3,<2" \
    "anthropic>=0.77.0" \
    "neo4j>=5.23.1" \
    "python-dotenv>=1.2.1"
  VIRTUAL_ENV="$venv" uv pip install --quiet --no-deps \
    "mem0-mcp-selfhosted @ git+https://github.com/elvismdev/mem0-mcp-selfhosted.git@${ref}"
  VIRTUAL_ENV="$venv" "$venv/bin/python" -c \
    "from mcp.server.fastmcp import FastMCP; import mem0_mcp_selfhosted.server" \
    || fail "import check failed - dependency resolution is wrong"
  ok "server installed and imports cleanly"
}

# ---------------------------------------------------------------- deps ------
# Only four things are actually required: docker, ollama, uv and curl. Python is
# NOT installed separately - uv downloads its own CPython 3.12 for the venv.
# Node/npm are not needed at all: the server is Python, Qdrant is a container
# and Ollama is a static binary.
have() { command -v "$1" >/dev/null 2>&1; }
: "${SUDO:=}"

install_deps() {
  local plat="$1" missing=()
  for c in curl git; do have "$c" || missing+=("$c"); done
  [ ${#missing[@]} -gt 0 ] && fail "install these first: ${missing[*]}"
  unset missing

  if [ "$plat" = macos ]; then
    if ! have brew; then
      warn "Homebrew not found - installing (this prompts for your password)"
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      for p in /opt/homebrew/bin /usr/local/bin; do [ -x "$p/brew" ] && eval "$("$p/brew" shellenv)"; done
    fi
    have uv     || { warn "installing uv";     brew install uv; }
    have ollama || { warn "installing ollama"; brew install ollama; }
    if ! have docker; then
      warn "installing Docker Desktop"
      brew install --cask docker
      printf '  Docker Desktop needs a manual first launch. Opening it now.\n'
      open -a Docker || true
    fi
    pgrep -q ollama || { (ollama serve >/dev/null 2>&1 &) ; sleep 3; }
  else
    if ! have docker; then
      warn "installing docker"
      $SUDO apt-get update -qq
      $SUDO apt-get install -y -qq docker.io docker-compose-v2
      $SUDO usermod -aG docker "${SUDO_USER:-$USER}" || true
      warn "added you to the docker group - log out and back in if docker still needs sudo"
    fi
    have uv     || { warn "installing uv";     curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
    have ollama || { warn "installing ollama"; curl -fsSL https://ollama.com/install.sh | sh; }
  fi

  have uv || fail "uv still not on PATH - open a new shell and re-run"
  ok "dependencies satisfied (docker, ollama, uv)"
}

# A container from a DIFFERENT compose project holding our name would otherwise
# fail mid-install with a raw daemon error.
check_compose_conflict() {
  local proj; proj="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' mem0-qdrant 2>/dev/null || true)"
  if [ -n "$proj" ] && [ "$proj" != "agent-memory" ]; then
    cat >&2 <<EOM
A container named mem0-qdrant already exists from compose project "$proj".
That is almost certainly an older hand-rolled setup. Your memories are in the
named volume and will NOT be lost. Free the name with:

    docker rm -f mem0-qdrant

then re-run. (The volume mem0-qdrant is untouched by that command.)
EOM
    exit 1
  fi
}

# ---------------------------------------------------------- autostart -------
# Ollama going away is the single most likely way this breaks, and it is
# invisible: the MCP server initialises mem0 lazily, so clients still report
# "Connected" while every add and search fails.
#
# On macOS, Ollama.app SUPERVISES ITS OWN SERVER. Do not install a LaunchAgent
# for `ollama serve` - it crash-loops on "bind: address already in use" because
# the app already owns the port. Two supervisors fight. The correct fix is a
# login item.
ollama_autostart_state() {
  case "$(detect_platform)" in
    macos)
      if [ ! -d /Applications/Ollama.app ]; then
        echo "cli-only"; return
      fi
      if osascript -e 'tell application "System Events" to get the name of every login item' \
           2>/dev/null | grep -qi ollama; then
        echo "login-item"
      else
        echo "missing"
      fi ;;
    *)
      if systemctl is-enabled --quiet ollama 2>/dev/null; then echo "systemd"; else echo "missing"; fi ;;
  esac
}

ensure_ollama_autostart() {
  local state; state="$(ollama_autostart_state)"
  case "$state" in
    login-item|systemd) ok "ollama starts automatically ($state)" ;;
    cli-only)
      warn "ollama is a CLI-only install with no supervisor; it will not survive a reboot"
      warn "start it with 'ollama serve', or install Ollama.app" ;;
    missing)
      if [ "$(detect_platform)" = macos ]; then
        warn "ollama would not survive a reboot - adding Ollama.app as a login item"
        osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Ollama.app", hidden:true}' >/dev/null 2>&1 || true
        if [ "$(ollama_autostart_state)" = "login-item" ]; then
          ok "ollama set to start at login"
        else
          warn "could not set the login item - add Ollama.app under System Settings > General > Login Items"
        fi
      else
        $SUDO systemctl enable ollama >/dev/null 2>&1 \
          && ok "ollama enabled at boot" \
          || warn "could not enable ollama at boot - run: sudo systemctl enable ollama"
      fi ;;
  esac
}
