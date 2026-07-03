Changelog
=========

2026-07-03
----------

- Build arm64 containers for better performance on macOS Podman


2026-07-02
----------

- Add ``--ro`` flag to ``launch.py`` to protect subdirectories of the working
  directory and make them read-only
- Rename original ``--read-only``, which made the *entire* working directory
  read-only, to ``--global-read-only``.

2026-07-01
----------

- Add ``--mask`` flag to ``launch.py`` to hide sensitive subdirectories of the
  working directory from the container
- Update docs on Pi
- When running ``refresh.py``, also update the :file:`~/.pi/agent/auth.json`
  with the contents of :file:`~/.codex/auth.json`
- Add ``auth-reload`` extension for Pi to hot-reload ChatGPT
  subscription/enterprise auth

2026-06-28
----------

- Documentation updates

2026-06-21
----------

- Improve image tagging to support per-harness “latest” tags

2026-06-14
----------

- Make Singularity container tagging match Podman tagging

2026-06-05
----------

- Schedule routine image builds in GHA

2026-05-28
----------

- Update documentation to reflect the new Pi package hosting location.
- Add troubleshooting notes for some common issues.

2026-05-08
----------

- Revise AWS credentials handling to better support Pi

2026-05-04
----------

- Containers can now run Pi with proper config file handling.
- Upgrade container to Node.js 25.
- Optimize config file copying in ``refresh.py`` , in particular batched
  rsync calls
- Improve version tagging to include “latest” for all images

2026-05-02
----------

- Containers now automatically pull images via Podman if not available
  locally.
- Add documentation for using conda environments on macOS.

2026-05-01
----------

- Add support for ``LLM_MOUNTS`` env var for simplified mounting

2026-04-30
----------

- Add contributing guidelines, troubleshooting guide, and improve
  cross-linking between docs.
- Add tips for copying data into containers.
- Update Singularity-related comments and remove obsolete test code.

2026-04-29
----------

- Fix handling of home directories in Singularity containers, ensuring
  ``$HOME`` is properly set.
- Switch from npm-based installation of Claude Code to apt install
- Add ``claude-status.sh`` utility script.

2026-04-28
----------

- Add support for running containers in read-only mode via
  ``--read-only`` flag.

2026-04-27
----------

- Better versioning for container images with separate tags for
  different harness versions
- Simplify GitHub Actions workflows for building and publishing images.
- Improved Pi version detection and fallback installation logic.
- Fixed mount handling: stopped mounting
  ``~/.local/share/llm-devcontainer``, create codex directory if
  missing.

2026-04-26
----------

- Versioned container images

2026-04-25
----------

- Refactor env var handling, particularly for AWS Bedrock configuration.
  Better diagnostics for containerized Pi.
- Simplify ``build.py``
- Add support for named conda environments with a macOS-specific
  warning.

2026-04-24
----------

- Add Pi support
- Initial unit tests
- Container building improvements: more efficient Docker layers,
  improved architecture detection, cleaner argument parsing.

2026-04-23
----------

- Pass along environment variables (CLAUDE\ *, ANTHROPIC*, AWS\*) with
  proper defaults.
- Better path handling for Singularity, ``--cleanenv`` support, and
  warnings about nested mounts.
- Initial test framework

2026-04-22
----------

- Add support for injecting SSL certificates at build time and mounting
  them into containers
- Simplify Docker/Podman build process when certificates aren’t needed.
- Documentation improvements including CSS styling and initial Sphinx
  setup.
- Default image names now pull from ghcr.io registry.

2026-04-17
----------

- Set up GitHub Actions workflow for building and pushing container
  images to GitHub Container Registry (ghcr.io).

2026-04-16
----------

- Add initial tests for both Podman and Singularity
- Various CI adjustments for container user handling and naming
  conventions.

2026-04-15
----------

- Refactor launch system

2026-04-13
----------

- Initial release.
