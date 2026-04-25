Configuration and credential files
==================================

This page is the single reference for the configuration and credential files
used by the agent tools in this repository, and for how :cmd:`launch.py`
mounts them into containers.

Codex
-----

- **Path**: :file:`~/.codex`
- **Contents**: Configuration and authentication data
- **Credentials file**: :file:`~/.codex/auth.json` contains authentication
  tokens
- **Security**: Treat this file like a password; it allows Codex to
  authenticate as you

Claude Code
-----------

- :file:`~/.claude/` – general settings, session history, skills, and other
  persistent state
- :file:`~/.claude.json` – UI settings, metrics, and approved directories
- **Security**: Prior conversation content in :file:`~/.claude/` may be
  exposed to containers when the directory is mounted

AWS SSO
-------

- **Path**: :file:`~/.aws/`
- **Contents**: AWS configuration and SSO credentials
- **Required when**: Using Claude Code (or Pi) with Amazon Bedrock, i.e. when
  ``CLAUDE_CODE_USE_BEDROCK=1`` or ``PI_USE_BEDROCK=1`` is set in the effective
  container environment

Pi
--

- **Path**: :file:`~/.pi`
- **Mounted when**: Running the ``pi`` subcommand and the directory exists on
  the host

Mount behavior in containers
----------------------------

:cmd:`launch.py` automatically mounts these paths based on the subcommand:

- ``codex``: mounts :file:`~/.codex`
- ``claude``: mounts :file:`~/.claude`, :file:`~/.claude.json`, and
  :file:`~/.aws` (when Bedrock is enabled)
- ``pi``: mounts :file:`~/.pi` (if it exists), and :file:`~/.aws` when Bedrock
  is enabled
- ``shell``: mounts the Codex, Claude, and Pi paths above

See :doc:`running-containers` for details on the container runtime environment,
including background on why the host home directory is not mounted.
