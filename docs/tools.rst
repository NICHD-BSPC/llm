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

- Refreshes Codex authentication (:file:`~/.codex/auth.json`). This is mounted inside running Codex containers, so they will see the new credentials when refreshed.
- Refreshes AWS SSO credentials (:file:`~/aws/sso`). This is mounted inside running Claude and Pi containers, so they will see the new credentials when refreshed.
- Optionally pushes refreshed credentials to a remote host (such as NIH's Biowulf).
- Optionally pushes entire config directories to remote.
- Optionally prints Bedrock bearer-token exports for tools that do not use the AWS SDK.

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
- Defaults to automatically pulling the latest containers published by this
  repo, from GitHub Container Registry (https://ghcr.io/nichd-bspc/llm)
- By default, mounts the current working directory and only the
  credential/config paths relevant to the called tool
- Starts :cmd:`codex`, :cmd:`claude`, :cmd:`pi`, or an interactive shell
- Passes through mounts, env vars, cert bundles, and optional conda environments

Examples
~~~~~~~~

.. note::

   Unless noted otherwise, these examples use Codex for simplicity. Replace
   ``codex`` with ``claude``, ``pi``, or ``shell`` as needed.

Basic usage
^^^^^^^^^^^

Run codex, detecting container runtime automatically (Podman on Mac, Singularity
on Linux):

.. code-block:: bash

   launch.py codex
   launch.py claude
   launch.py pi

Run a shell for debugging -- this will mount credentials for all supported
agents:

.. code-block:: bash

   launch.py shell

Resume a session:

.. code-block:: bash

   launch.py codex --resume 019dd08c-a96f-7090-8708-8a4f4cfa8834

One-shot prompt with an attached image and then exit:

.. code-block:: bash

   launch.py codex exec \
     -i ./image.png \
     -o out.json \
     -- \
     "extract the text from this image and return as JSON"

Check help:

.. code-block:: bash

   launch.py codex -h

Mounts and read-only
^^^^^^^^^^^^^^^^^^^^

Let the container see something outside the working directory:

.. code-block:: bash

   launch.py --mount /data/experiment1 codex

Mount a directory read-only inside the container:

.. code-block:: bash

   launch.py --mount /data/experiment1:/data/experiment1:ro codex

Mount the current working directory as read-only, so the agent can read but not
modify your files:

.. code-block:: bash

   launch.py --read-only codex

   # short form
   launch.py --ro claude

Mount a conda env into the container and prepend it to the path so the agent
can use it (*only works on Linux*):

.. code-block:: bash

   launch.py --conda-env my-env codex

This is equivalent to the following "mount + prepend to path" combination,
which can be used for more complex scenarios:

.. code-block:: bash

   launch.py \
     --mount $(conda info --base)/envs/my-env \
     --prepend-path ~/conda/envs/my-env/bin \
     codex

Environment and certificates
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Provide additional environment variables or override what's in the environment:

.. code-block:: bash

   launch.py \
     --env OMP_NUM_THREADS=1 \
     --env HOME=/tmp \
     codex

Provide a certificates file you've previously downloaded to allow enterprise TLS
interception (see :doc:`certificates`):

.. code-block:: bash

   launch.py --certs ~/certs.pem codex

Backend and debugging
^^^^^^^^^^^^^^^^^^^^^

Force podman instead of Singularity:

.. code-block:: bash

   launch.py --backend podman codex

Print out the command to be run as composed by :file:`launch.py` and then exit
without running. Useful for debugging:

.. code-block:: bash

   launch.py --dry-run codex

When developing locally or using other containers, specify the image name
(Podman) or SIF name (Singularity):

.. code-block:: bash

   # after running build.py locally
   launch.py --image-name llm-devcontainer codex

   # or another published image
   launch.py --image-name quay.io/org/container codex

   # or on Linux host, defaults to Singularity:
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
- ``TOOL`` – the subcommand being run (e.g., ``codex``, ``claude``, ``pi``); this is only used for information
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
