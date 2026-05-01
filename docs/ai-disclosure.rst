Disclosure of AI use
====================

AI was used in muliple ways in this project. Every line was manually inspected.
The committing author is entirely responsible and accountable for the entirety
of their commits.

Claude Code (wih Sonnet 4.6, Opus 4.6, Opus 4.7) and Codex (with GPT 5.4) were
used in the following ways:

- Sketching out initial ideas for launch.py
- Converting an eariler functional based approach of launch.py to an object-oriented
  approach using a handwritten, intentionally-incomplete draft as a template
- Proposing documentation reorganization
- Cleaning up documentation: identifying repeated sections; consolidating where
  possible (including some AI-rewritten sections in the process), adding cross-links where appropriate
- Generating draft of the troubleshooting page (using the rest of the docs as input)
- Generating code that was then reviewed/fixed/edited by hand, line-by-line
- Initial drafts of GitHub Actions workflows, espeically providing snippets for
  uploading to GitHub Container Registry with tagged images, and later
  refactoring of workflows into a single job.
- Iterating on ideas for how best to mount host files and dirs into the
  container without clobbering each other
- Code review, making suggestions, and applying those suggestions (which were
  then manually reviewed/fixed/edited).
- The `run-diagnostics` and `container-diagnostics` scripts (and the idea of
  running with `script` to get around TTY requirements) used in testing
