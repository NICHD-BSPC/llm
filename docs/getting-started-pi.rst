Getting started: Pi and OMP
===========================

Codex and Claude Code are closely tied to OpenAI and
Anthropic respectively. In contrast,
`Pi <https://github.com/earendil-works/pi/tree/main/packages/coding-agent>`__
and `OMP <https://github.com/can1357/oh-my-pi>`__ (Oh My Pi) are agnostic to
model. Pi is a minimal harness; OMP is sort of the opposite.


**Prerequisites:** Here we assume that you can successfully run :cmd:`launch.py
codex` and :cmd:`launch.py claude` as documented at
:doc:`getting-started-codex` and :doc:`getting-started-claude` respectively.


.. note::

   :nih:`NIH-specific` When choosing different Bedrock models, you'll need to
   choose ones that start with ``us.``.

Step 1. Export env vars
-----------------------

Export these environment variables, for example in your :file:`.bashrc`:

.. code-block:: bash

   export PI_USE_BEDROCK=1
   export OMP_USE_BEDROCK=1


The other env vars you have set for Claude Code and the AWS SSO setup, as part
of the prerequisites, are used for Pi and OMP as well.

.. _pi-auth-reload:

Step 2 (optional, Pi only). Install auth-reload extension
---------------------------------------------------------

If you want to use OpenAI models in Pi via the ChatGPT Enterprise login and
want to avoid the need to restart Pi if auth expires when you are mid-session:

Copy the :file:`tools/reload-auth.ts` file from this repo into your
:file:`~/.pi/agent/extensions` directory.

Restart Pi. When using :cmd:`/model`, models will be available with the
``[openai-codex]`` tag.

.. details:: What does this do?

   When you run :ref:`refresh`, it will convert the Codex-generated
   :file:`~/.codex/auth.json` into a format that Pi can use, and saves
   it as :file:`~/.pi/agent/auth.json`. That gets mounted into the container.

   However, unlike Codex, Pi reads this file once at startup and then does not
   read it again. That means if your auth expires when you're mid-session,
   there's no way of refreshing it.

   So this extension provides a mechanism to do so. It hooks into the
   ``before_agent_start`` and ``turn_start`` events, checks to see if the file
   has been modified, and if so, read in the contents to refresh the auth.

.. note::

   OMP does not use this extension or :file:`~/.pi`. Instead, when you run
   :cmd:`launch.py omp`, the access token from the host's
   :file:`~/.codex/auth.json` is passed into the container as the
   ``OPENAI_CODEX_OAUTH_TOKEN`` environment variable. This is fixed for the
   lifetime of the container, so if it expires mid-session, run
   :ref:`refresh` and restart :cmd:`launch.py omp`.

Step 3. Run locally (Podman container)
--------------------------------------

On a local Mac, with Podman Desktop running, in a directory you are
comfortable giving the agent access to:

.. code-block:: bash

   refresh.py      # refresh credentials if needed
   launch.py pi    # or: launch.py omp

Use :cmd:`/model` to choose a model, then submit a prompt like "testing" to
confirm that the model responds.

Step 4. Run remotely (Singularity)
----------------------------------

As with Claude Code, push credentials from your *local* machine, then log in to
the remote and launch:

.. code-block:: bash

   # locally
   refresh.py --remote biowulf.nih.gov

   # then on the remote (after e.g. sinteractive; module load singularity)
   launch.py pi    # or: launch.py omp

.. tip::

   You know it's working when :cmd:`launch.py pi` or :cmd:`launch.py omp`
   starts, :cmd:`/model` lists Bedrock (and optionally ``openai-codex``)
   models, and a prompt gets a response.

See :ref:`config-pi` and :ref:`config-omp` for configuration.
