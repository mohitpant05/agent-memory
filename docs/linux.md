# Linux

Written against an always-on box (i5-12500H, 16GB, RTX 3050 4GB).
Qdrant in Docker; Ollama and the MCP server on the host under systemd.

## Install

    git clone https://github.com/mohitpant05/agent-memory.git
    cd agent-memory
    ./memory-layer install      # writes .env, stops for review
    nano .env                   # check MEM0_HOST and MEM0_LLM_MODEL
    ./memory-layer install      # installs everything, starts nothing
    ./memory-layer start
    ./memory-layer verify

Docker, ollama and uv are installed automatically if missing. If docker was
just installed you may need to log out and back in for group membership.

## Exposure — read this

The MCP server has **no inbound authentication**. Anyone who can reach the port
gets full read/write/delete on every memory. The installer refuses
`MEM0_HOST=0.0.0.0`.

**SSH tunnel** (default, `MEM0_HOST=127.0.0.1`) — from the client machine:

    ssh -N -L 8081:127.0.0.1:8081 user@box

**Tailscale** — install on both machines, set `MEM0_HOST` to the tailnet IP.
Better if the client ever leaves the LAN.

## GPU with small VRAM

The embedder and the extraction model cannot both be resident on a 4GB card;
Ollama would evict one per call. The installer builds a CPU-pinned embedder
(`bge-m3-cpu`, a Modelfile with `PARAMETER num_gpu 0`) so the LLM keeps the
whole GPU, and sets `OLLAMA_MAX_LOADED_MODELS=1`.

Do not use `qwen3:*` or other reasoning models — see [patches](../patches/).

## Operations

    journalctl -u mem0-mcp -f
    sudo systemctl restart mem0-mcp
    ./memory-layer stop         # memories survive
    docker compose -f platform/linux/docker-compose.yml down -v   # DESTROYS them
