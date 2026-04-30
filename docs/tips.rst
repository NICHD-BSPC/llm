Tips
====

A collection of tips and guidance in no particular order:

- Be disciplined about using git. Ideally, everything should be committed before
  starting an agent, otherwise it can be hard to incrementally roll back
  changes.

- If you're using multiple agents/models (like both Codex and Claude Code),
  playing the models off of each other can get better results than just one
  alone. For example, have Claude write a plan, have Codex evaluate/improve the
  plan, and do another round with Claude. Or have each of them write out their
  code reviews to a markdown file, and have them review each other's review. Or
  have one of them consolidate the review items from both models into a single
  document.

- Remember, *every time you send a prompt the ENTIRE history of the session is
  sent*. If you have a 100k token conversation and you reply "yes", that sends
  100k + 1 tokens to the model. This means it is better to think of this as
  a longer form of communication, like email, rather than a chat or text message
  (despite the interface strongly suggesting short messages). Caching can help
  a lot with this, but the cache typically has a short (e.g, 5 min) lifetime.

- Consider using an :file:`AGENTS.md` (for Codex or Pi) or :file:`CLAUDE.md`
  (for Claude or Pi) in the top level of the repo to keep track of information
  about the code base you're working on. This avoids the agent needing to search
  for the right files on every new session, which consumes excessive tokens.
  See :doc:`config-files` for more on configuration files used by each agent.

- Agents typically use :cmd:`ripgrep` (:cmd:`rg`) to search. Ripgrep respects
  :file:`.gitignore` files, so ensure conda envs are added to ``.gitignore`` to
  prevent agents from looking through the hundreds of thousands of files in
  a typical env. See :ref:`ts-conda` for related container issues with conda
  environments.
