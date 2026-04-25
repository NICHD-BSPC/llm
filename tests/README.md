# Tests
Since Claude Code and Codex need login, we cannot run automated tests in CI that use these tools.

However, we can run the `run-diagnostics.sh` script in shell mode inside the container, which can test behaviour like credential mounts, write access, and tool availability.

Interactively, the same script can be run inside the container using Claude Code or Codex to run it and report on the output. This tests the login behavior of the models and ensures that the additional command needed to run the models is not adversely affecting behavior.

```bash
tests/run-diagnostics.sh shell podman
```

```bash
tests/run-diagnostics.sh shell singularity
```

For Claude or shell Bedrock diagnostics, enable Bedrock in the host environment
or pass ``-e CLAUDE_CODE_USE_BEDROCK=1``. AWS settings should come from the
host environment or from explicit ``-e AWS_PROFILE=...`` and
``-e AWS_REGION=...`` overrides.
