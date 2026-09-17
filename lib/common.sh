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
  local url="$1" name="$2" tries="${3:-30}" i
  for i in $(seq 1 "$tries"); do
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
