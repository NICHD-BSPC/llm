LLM containers
==============

In `NICHD's Bioinformatics and Scientific Programming Core
<https://www.nichd.nih.gov/about/org/dir/other-facilities/cores/bioinformatics>`__,
we wanted to use multiple LLM agent tools in a secure way on multiple systems.

Specifically, we wanted to run agens in isolated containers to prevent them
from seeing arbitrary directories on the system. See :ref:`why-containers` for
more on this topic.

When everything is set up, usage looks like this:

.. code-block:: bash

   refresh.py        # refresh credentials if needed
   launch.py codex   # run Codex in a container
   launch.py claude  # or Claude Code
   launch.py pi      # or pi

Or, to use on a remote machine:

.. code-block:: bash

   # Run this on a *local* machine to refresh and push credentials to the
   # right place on the remote.
   refresh.py --remote $REMOTE_HOST

   # then log in to the remote host and run:
   launch.py codex  # or claude or pi

You can hide directories or make them read-only; you can mount conda
environments to make tools available inside the container; you can mount
arbitrary other directories. The point though is that you do these things
*deliberately* and *explicitly* instead of letting the agent dig around for
what it wants:

.. code-block:: bash

   launch.py \
     --ro my/read-only/dir \          # agent can read (but not write) to my/read-only
     --mask secret/dir \ .            # agent only sees an empty directory for secret/dir
     --conda-env path/to/conda/env \  # agent can use the executables in path/to/conda/env
     --certs ~/certs.pem \            # run over VPN
     codex

**Multiple agent harnesses** depending on your preferences:

- `Codex CLI <https://developers.openai.com/codex/cli>`__, using models hosted by OpenAI enterprise using `ChatGPT Enterprise <https://openai.com/chatgpt/enterprise/>`__ authentication or `Amazon Bedrock <https://aws.amazon.com/bedrock/>`__ using `AWS SSO <https://aws.amazon.com/iam/identity-center/>`__.
- `Claude Code CLI <https://code.claude.com/docs/en/overview>`__, using models hosted by Amazon Bedrock using AWS SSO.
- `Pi coding agent <https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent>`__, also using models hosted by Amazon Bedrock using AWS SSO.

**Multiple container runtimes** for different systems:

- `Podman <https://podman.io/>`__ images, for running containers on a local Mac
- `Singularity <https://docs.sylabs.io/guides/latest/user-guide/>`__ images, for running containers on a Linux HPC system

**Tools** to make it as easy as possible to authenticate and launch while still remaining secure:

- :ref:`refresh` to refresh your credentials and optionally push them to a remote system
- :ref:`launch` to launch a container running the LLM tool
- ``build.py`` to build container images (only required if you want to build your own; you can use our hosted images)

**See** https://nichd-bspc.github.io/llm **for documentation.**

**See** https://github.com/nichd-bspc/llm **for code.**

.. note::

   While most of this documentation applies to any type of system, there are
   some NIH-specific components that are indicated by :nih:`NIH-specific`.

Contents
--------

**Getting started**

.. toctree::
   :maxdepth: 1

   getting-started-codex
   getting-started-claude
   getting-started-pi

**Next steps**

.. toctree::
   :maxdepth: 1

   tools
   config-files
   running-containers
   troubleshooting

**Details**

.. toctree::
   :maxdepth: 1

   certificates
   aws-sso
   bedrock-keys
   tips
   developer
   ai-disclosure
   CHANGELOG
