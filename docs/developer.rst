Developers
==========

Building containers
-------------------

Images are already created as part of this repo's GitHub Actions -- see
:ref:`images-created`. But if you want to build your own custom containers or
do other development work, here is how to build them yourself.

1. Build the podman image
~~~~~~~~~~~~~~~~~~~~~~~~~

This assumes you are successfully running Codex from a container, which means
you have Podman Desktop installed and running.

The :file:`Dockerfile` is where the build is specified, so modifying that will
most likely be your entrypoint for customization.

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
- The default platform matches the host architecture (``linux/arm64`` on
  Apple Silicon, otherwise ``linux/amd64``). Change it with ``--arch``, and
  pass the same value to :cmd:`launch.py --arch`.
- Cache is used by default. To force a fresh rebuild, use ``--no-cache``.
- If you do not pass explicit tool versions, the image installs the latest
  available Claude Code, Codex, and Pi releases. To pin them, pass all three of
  ``--claude-version``, ``--codex-version``, and ``--pi-version``.
- Certificates are only used if passed explicitly with ``--certs``;
  :cmd:`build.py` does not read ``LLM_DEVCONTAINER_CERTS``.

.. tip::

   Test with :cmd:`refresh.py` to refresh credentials, followed by
   :cmd:`launch.py --image-name llm-devcontainer codex` (see :ref:`launch`
   for all options). This starts the container, mounts the current directory
   to the same path inside the container, and immediately starts Codex. Use
   ``!``-prefixed shell commands such as ``! ls ~`` to verify that other host
   directories are not mounted.


2. Convert to Singularity image
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a tarball of the Podman image:

.. code-block:: bash

   podman save -o llm-image.tar --format docker-archive llm-devcontainer

Transport it to a machine with Singularity installed:

.. code-block:: bash

   rsync -arv --progress llm-image.tar user@hostname:/path/on/remote/llm-image.tar

On the remote host, with Singularity installed, convert to SIF:

.. code-block:: bash

   singularity build llm.sif docker-archive:/path/on/remote/llm-image.tar


Adding a new agent
------------------

Steps to support a new agent in the container and :file:`launch.py`:

- Install it in Dockerfile
- Add credential paths to ``CREDENTIAL_PATHS`` in :file:`launch.py` (see :ref:`launch` for current defaults)
- Add command and credentials reference to ``SUBCOMMAND_CONFIG`` in :file:`launch.py`
- Append credentials to shell section of ``SUBCOMMAND_CONFIG`` as well
- Add a per-harness default tag to ``DEFAULT_IMAGE_TAGS`` in :file:`launch.py`
- Add a ``Launcher.setup_<tool>_config()`` method if the tool's config
  directory/files need to exist before mounting
- If :ref:`refresh` should manage its credentials, add them to
  ``CREDENTIAL_PATHS`` in :file:`refresh.py` and to the ``--kind`` choices
- If using Bedrock, add a detection method to ``Launcher._bedrock_enabled()``.
  Make up a new env var if needed
- Pass thru ``Launcher._host_env_with_prefixes()`` if relevant
- In :file:`.github/workflows/main.yml`, extract the tool version and add a
  ``publish_harness_tags`` call so ``<tool>-latest`` and ``<tool>-<version>``
  tags are published
- Document credential and config files in :doc:`config-files`, add a
  getting-started page (or section), and update :doc:`troubleshooting` and
  :doc:`CHANGELOG`
