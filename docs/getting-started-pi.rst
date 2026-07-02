Getting started: Pi
===================

`Pi <https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent>`__ is
a minimal coding harness. Codex and Claude Code are closely tied to OpenAI and
Anthropic respectively. In contrast, Pi is agnostic to model. It is also much
more flexible than Codex or Claude Code.

**Prerequisites:** Here we assume that you can successfully run :cmd:`launch.py
codex` and :cmd:`launch.py claude` as documented at
:doc:`getting-started-codex` and :doc:`getting-started-claude` respectively.


.. note::

   :nih:`NIH-specific` When choosing different Bedrock models, you'll need to
   choose ones that start with ``us.``.

Step 1. Export env var
----------------------
Export the ``PI_USE_BEDROCK`` environment variable, for example in your :file:`.bashrc`:

.. code-block:: bash

   export PI_USE_BEDROCK=1

The other env vars you have set for Claude Code and the AWS SSO setup, as part
of the prerequisites, are used for Pi as well.

.. _pi-auth-reload:

Step 2 (optional). Install auth-refresh extension
-------------------------------------------------

If you want to use OpenAI models in Pi via the ChatGPT Enterprise login and
want to avoid the need to restart Pi if auth expires when you are mid-session:

Copy the :file:`tools/reload-auth.ts` file from this repo into your
:file:`~/.pi/agents/extensions` directory.

Restart Pi. When using :cmd:`/model`, models will be available with the
``[openai-codex]`` tag.

.. details:: What does this do?

   When you run :ref:`refresh`, it will convert the Codex-generated
   :file:`~/.codex/auth.json` into a format that Pi can use, and saves it as
   :file:`~/.pi/agent/auth.json`. That gets mounted into the container.

   However, unlike Codex, the Pi harness reads this file once at startup and
   then does not read it again. That means if your auth expires when you're
   mid-session, there's no way of refreshing it.

   So this Pi extension provides a mechanism to do so. It hooks into the
   ``before_agent_start`` and ``turn_start`` events, checks to see if the file
   has been modified, and if so, read in the contents to refresh the auth.
