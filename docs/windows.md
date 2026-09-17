# Windows

**Untested.** Use WSL2 — the scripts are bash and expect systemd.

## WSL2

Treat the distro as a Linux host and follow [linux.md](linux.md), with four
differences:

1. **The NVIDIA driver goes on Windows, not inside WSL.** WSL2 sees the GPU
   through the Windows driver. Installing a Linux driver in the distro breaks
   the passthrough. Verify inside WSL with `nvidia-smi`.

2. **Docker Desktop with the WSL2 backend**, and enable integration for your
   distro under Settings → Resources → WSL Integration.

3. **Run the scripts inside WSL**, not PowerShell.

4. **systemd must be enabled** — older WSL2 does not start it. In
   `/etc/wsl.conf`:

       [boot]
       systemd=true

   Then `wsl --shutdown` from PowerShell and reopen. Without it the installer
   fails on the missing `systemctl`.

`detect_platform` reports WSL separately from bare Linux, so you will see it
named in the output.

## Reaching it from Windows-side clients

WSL2 forwards `localhost`, so `http://127.0.0.1:8081/mcp` usually works from a
Windows Claude Code. If not, take the distro IP from `wsl hostname -I` and set
`MEM0_HOST` to it.

## Native Windows

Possible but unsupported by these scripts: install Ollama for Windows, run
Qdrant under Docker Desktop, create the venv by hand with the pins from
`lib/common.sh`, copy `patches/zz_mem0_qwen_patch.py` into
`venv\Lib\site-packages\` with a matching `.pth`, and use Task Scheduler or NSSM
instead of systemd. The `.env` values are identical.
