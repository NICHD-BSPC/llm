Tools Reference
===============

This repository revolves around three utility scripts:

- :file:`refresh.py` refreshes local credentials and can copy them to a remote host
- :file:`launch.py` starts Codex or Claude Code inside a container
- :file:`build.py` builds the container image itself

Most users only need :file:`refresh.py` and :file:`launch.py`.

Use :file:`build.py` only if you want to build your own image rather than use
the hosted one.

.. _getscripts:

How to get the scripts
----------------------

You will need :file:`refresh.py` on the local machine, and :file:`launch.py` on
whatever machine (local and/or remote) you want to run a container on.

Two main ways of getting them.

1. Clone the repo, say to your home directory. **This is the recommended
   method,** because you can always run :cmd:`git pull origin main` to update
   the scripts.

   .. code-block:: bash

      git clone https://github.com/nichd-bspc/llm ~/llm

2. Or manually download them, say to a :file:`~/bin` directory:

   .. code-block:: bash

      # on local machine
      curl -fSsL -o ~/bin/launch.py https://raw.githubusercontent.com/nichd-bspc/llm/main/launch.py
      curl -fSsL -o ~/bin/refresh.py https://raw.githubusercontent.com/nichd-bspc/llm/main/refresh.py
      chmod +x ~/bin/launch.py ~/bin/refresh.py

      # on remote we only need launch.py
      curl -fSsL -o ~/bin/launch.py https://raw.githubusercontent.com/nichd-bspc/llm/main/launch.py
      chmod +x ~/bin/launch.py

Then either call them directly with the full path name, or add them to your
``PATH``. For example, if you cloned the repo to your ome directory, you would
add this to your :file:`~/.bashrc` (or wherever you set your ``$PATH``
variable):

.. code-block:: bash

   export PATH="$PATH:~/llm"

.. tip::

   You know it's working if you open a new terminal and can run :cmd:`launch.py
   -h` and/or :cmd:`refresh.py -h` to see the help.

.. _refresh:

``refresh.py``
--------------

Refreshes credentials locally, and optionally copies them to a remote host.

- Refreshes Codex authentication (:file:`~/.codex/auth.json`)
- Refreshes AWS SSO credentials (:file:`~/aws/sso`, used for Claude)
- Copies refreshed credentials to a remote host (such as NIH's Biowulf)
- Optionally pushes entire config directories to remote
- Prints Bedrock bearer-token exports for tools that do not use the AWS SDK

Examples
~~~~~~~~

Refresh codex & aws locally:

.. code-block:: bash

   refresh.py

Only refresh codex, and push to remote system:

.. code-block:: bash

   refresh.py --kind codex --remote biowulf.nih.gov

Refresh all, push credentials **as well as entire agent config dirs** to remote system:

.. code-block:: bash

   refresh.py --full --remote biowulf.nih.gov

See what files will be pushed with ``--full``:

.. code-block:: bash

   refresh.py --show-files

Export a temporary Bedrock token, which can be used for other tools that don't
support AWS SSO:

.. code-block:: bash

   eval "$(./refresh.py --bedrock-export)"

.. _launch:

``launch.py``
-------------

Runs the agent inside a container, assuming credentials are already available.

- Detects Podman vs Singularity, or accepts an explicit backend
- By default, mounts the current working directory and credential/config paths
  relevant to the called tool
- Starts :cmd:`codex`, :cmd:`claude`, :cmd:`pi`, or an interactive shell
- Passes through mounts, env vars, cert bundles, and optional conda environments

Examples
~~~~~~~~

Run codex, detecting container runtime automatically (Podman on Mac, Singularity
on Linux):

.. code-block:: bash

   launch.py codex

Or Claude:

.. code-block:: bash

   launch.py claude

Or Pi:

.. code-block:: bash

   launch.py pi

Run a shell for debugging -- this will mount credentials for all supported
agents:

.. code-block:: bash

   launch.py shell

The rest of these examples will use Codex.

Force podman instead of Singularity

.. code-block:: bash

   launch.py --backend singularity codex

Let the container see something outside the working directory:

.. code-block:: bash

   launch.py --mount /data/experiment1 codex

Mount a conda env into the container (*only works on Linux*)

.. code-block:: bash

   launch.py --conda-env my-env codex

This is equivalent to the following "mount + prepend to path" combination:

.. code-block:: bash

   launch.py \
     --mount $(conda info --base)/envs/my-env \
     --prepend-path ~/conda/envs/my-env/bin \
     codex

Provide a certificates file you've previously downloaded to allow enterprise TLS
interception:

.. code-block:: bash

   launch.py --certs ~/certs.pem codex

Provide additional environment variables:

.. code-block:: bash

   launch.py \
     --env OMP_NUM_THREADS=1
     --env \
     codex

Print out the command to be run as composed by :file:`launch.py` and then exit
without running. Useful for debugging.

.. code-block:: bash

   launch.py --dry-run codex


When developing locally or using other containers, specify the image name
(Podman) or SIF name (Singularity):

.. code-block:: bash

   # after running build.py locally
   launch.py --image-name llm-devcontainer codex

   # or another published image
   launch.py --image-name quay.io/org/container codex

   # or on Linux host, defaults to Sinuglarity:
   launch.py --sif-name llm.sif codex




.. _launchenv:

Environment variables created by :file:`launch.py`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Supply additional env vars at the command line with ``--env NAME=VALUE``. This
can be used to override defaults. The following environment variables are set by
default in the container:

**Base environment:**

- ``HOME`` – set to ``/home/devuser``
- ``USER``, ``LOGNAME``, ``USERNAME`` – set to ``devuser``
- ``TOOL`` – the subcommand being run (e.g., ``codex``, ``claude``, ``pi``)
- ``HOST_MOUNT_DIR`` – the current working directory on the host
- ``PATH`` – constructed from the base Ubuntu PATH plus ``/home/devuser/.local/bin``, with optional prepends from ``--conda-env`` or ``--path-prepend``

**Tool-specific inherited variables:**

- For ``claude`` and ``shell``: All host environment variables starting with ``CLAUDE_CODE`` or ``ANTHROPIC_``
- For ``pi`` and ``shell``: All host environment variables starting with ``PI_``
- For ``claude``, ``pi``, and ``shell``: When Bedrock is enabled (via
  ``CLAUDE_CODE_USE_BEDROCK=1`` or ``PI_USE_BEDROCK=1``): All host environment
  variables starting with ``AWS_``

**Certificate variables (when** ``--certs`` **is provided):**

When ``--certs`` (or ``LLM_DEVCONTAINER_CERTS``) is provided (see
:doc:`certificates`), that file is mounted into the container at
:file:`/tmp/llm-devcontainer-cert.pem` and the following env vars are set,
pointing to that path:

- ``SSL_CERT_FILE``
- ``GIT_SSL_CAINFO``
- ``AWS_CA_BUNDLE``
- ``REQUESTS_CA_BUNDLE``
- ``NODE_EXTRA_CA_CERTS``
- ``CURL_CA_BUNDLE``

.. _build:

``build.py``
------------

Builds the local Podman image.

- Builds a Podman image from this repo's :file:`Dockerfile`
- Supports ``--no-cache``, ``--dry-run``, ``--image-name``, ``--arch``, and
  ``--certs``

.. code-block:: bash

   ./build.py
   ./build.py --no-cache

See :doc:`building-containers`. Image maintainers should keep a full checkout
and run :cmd:`./build.py` from the repo root.

Related pages
-------------

- :doc:`getting-started-codex`
- :doc:`getting-started-claude`
- :doc:`running-containers`
- :doc:`building-containers`
