# LLM containers

Run agent harnesses (Claude Code, Codex, Pi, OMP) within containers to restrict
their access and keep them from poking around where they shouldn't.

Run `refresh.py` to refresh credentials, then use `launch.py <harness>`.

Works locally on a Mac (using Podman) or remotely on an HPC (using
Singularity), using enterprise credentials.

**See** https://nichd-bspc.github.io/llm **for documentation.**
