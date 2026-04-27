Disclosure of AI use
====================

AI was used in muliple ways in this project. Every line was manually inspected:

- Sketching out initial ideas
- Converting an eariler functional based approach to an object-oriented
  approach using a handwritten, intentionally-incomplete draft as a template
- Proposing documentation reorganization
- Cleaning up documentation: identifying repeated sections; consolidating where
  possible (including some AI-rewritten sections in the process)
- Generating code that was then reviewed/fixed/edited by hand, line-by-line
- Initial drafts of GitHub Actions, providing snippets for uploading to
  GitHub Container Registry with tagged images, refactoring
- Iterating on ideas for how best to mount host files and dirs into the
  container without clobbering each other
- Code review, making suggestions, and applying those suggestions (which were
  then manually reviewed/fixed/edited).
- the `run-diagnostics` and `container-diagnostics` scripts (and running with
  `script` to get around TTY requirements) used in testing
