# Tests
Run the unit tests with:

```bash
python -m unittest discover -s tests
```

Claude Code and Codex require login, so CI does not run them interactively. Instead, it runs `run-diagnostics.sh` in shell mode inside each container backend to check credential mounts, write access, and tool availability.

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
