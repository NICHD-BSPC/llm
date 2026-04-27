Developers
==========

Building containers
-------------------

1. Build the podman image
~~~~~~~~~~~~~~~~~~~~~~~~~

Build once initially, then rebuild whenever you want updated tooling:

.. code-block:: bash

   ./build.py

If your network uses TLS interception, the first build may fail because the
container does not yet trust the enterprise certificates. See
:doc:`certificates` for how to download a local PEM CA bundle and make it
available via ``--certs`` or ``LLM_DEVCONTAINER_CERTS``.

When running :cmd:`build.py`:

- The default image name is ``llm-devcontainer``. Change it with
  ``--image-name``.
- The default platform is ``linux/amd64``. On ARM64 macOS this runs under
  emulation, which is usually acceptable because CPU is not the bottleneck.
  Change it with ``--arch``.
- Cache is used by default. To force a fresh rebuild, use ``--no-cache``.
- If you do not pass explicit tool versions, the image installs the latest
  available Claude Code, Codex, and Pi releases. The container records the
  installed versions in ``/usr/local/share/llm/tool-versions.env``.

GitHub Actions publishes the Podman image to GHCR with these tags:

- ``sha-<git sha>``
- ``latest`` on ``main``
- ``claude-<version>-codex-<version>-pi-<version>``

The GitHub Actions container workflow builds ``linux/amd64`` images only. It
first builds and tests the Podman image, then derives the version tag by
running the built container and reading ``claude --version``, ``codex
--version``, and ``pi --version``. The Singularity phase then converts that
same tested Podman image into a SIF artifact.

The workflow also sets ``org.opencontainers.image.source`` to the GitHub
repository URL so the GHCR package stays linked to the repository.

.. tip::

   Test with :cmd:`refresh.py` to refresh credentials, followed by
   :cmd:`launch.py --image-name llm-devcontainer codex`. This starts the
   container, mounts the current directory to the same path inside the
   container, and immediately starts Codex. Use ``!``-prefixed shell commands
   such as ``! ls ~`` to verify that other host directories are not mounted.


2. Convert to Singularity image
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a tarball of the Podman image:

.. code-block:: bash

   podman save -o llm-image.tar --format docker-archive llm-devcontainer

Transport it to a remote machine:

.. code-block:: bash

   rsync -arv --progress llm-image.tar user@hostname:/path/on/remote/llm-image.tar

On the remote host, with Singularity installed, convert to SIF:

.. code-block:: bash

   singularity build llm.sif docker-archive:/path/on/remote/llm-image.tar


Add a new agent
---------------

Steps to support a new agent in the container and :file:`launch.py`:

- Install it in Dockerfile
- Add credential paths to ``CREDENTIAL_PATHS`` in :file:`launch.py`
- Add command and credentials reference to ``SUBCOMMAND_CONFIG`` in :file:`launch.py`
- Append credentials to shell section of ``SUBCOMMAND_CONFIG`` as well
- If using Bedrock, add a detection method to ``Launcher._bedrock_enabled()``.
  Make up a new env var if needed
- Pass thru ``Launcher._host_env_with_prefixes()`` if relevant
- Document
