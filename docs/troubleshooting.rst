Troubleshooting
===============

This page collects common issues and how to diagnose them. When something
goes wrong, start with :ref:`ts-general-checks` and then look for a section
matching your symptoms.

.. _ts-general-checks:

General checks
--------------

**Are the scripts on your PATH?**

:file:`launch.py` must be available on every machine where you run containers
(local and remote). :file:`refresh.py` is only needed on the local machine.

.. code-block:: bash

   which launch.py    # should print a path
   which refresh.py   # local machine only

If either command prints nothing, add the directory containing the scripts to
your ``PATH`` (see :ref:`getscripts`), or call the script by its full path.

On a remote system it is easy to forget to download :file:`launch.py` or to
put it somewhere that is not on the ``PATH``.

**Are required environment variables set?**

Many problems come down to missing or incorrect environment variables. Check
the critical ones (on **each** system you are running containers on):

.. code-block:: bash

   # For Claude Code / Pi with Bedrock
   echo $CLAUDE_CODE_USE_BEDROCK   # should be 1
   echo $AWS_PROFILE               # should be your profile name
   echo $AWS_REGION                # should be your region, e.g. us-east-1

   # For Pi with Bedrock
   echo $PI_USE_BEDROCK            # should be 1

If any of these are blank, add them to your :file:`~/.bashrc` (or equivalent)
and source it or open a new terminal.

**Do the credential files exist?**

.. code-block:: bash

   # Codex
   ls ~/.codex/auth.json

   # Claude / Pi (AWS SSO)
   ls ~/.aws/config
   ls ~/.aws/sso/cache/

   # Claude Code config
   ls ~/.claude.json
   ls -d ~/.claude

If any are missing, run :ref:`refresh` to create them.

.. _ts-container-runtime:

Container runtime not found
---------------------------

**Symptom:** ``missing command 'podman' in PATH`` or ``missing command
'singularity' in PATH``.

**Podman (Mac):**

- Install `Podman Desktop <https://podman-desktop.io/>`__ and make sure it is
  running. The Podman CLI requires the Podman machine to be started.
- Verify: :cmd:`podman --version`

**Singularity (Linux / HPC):**

- Singularity is typically provided as a module on HPC systems. On
  :nih:`NIH-specific` Biowulf:

  .. code-block:: bash

     module load singularity
     singularity --version

- This must be done *after* getting an interactive node (e.g., :cmd:`sinteractive`).
  Singularity may not be available on login nodes.

.. _ts-image-not-found:

Container image not found
-------------------------

**Symptom:** ``podman image '...' not found`` or ``singularity image '...'
not found``.

**Podman:**

The default image is pulled automatically on first use. If you specified
a custom ``--image-name``, make sure you have either built it locally with
:ref:`build` or that it is available on the registry.

In some cases, you may need to do an explicit :cmd:`podman pull` to get Podman
to recognize the latest image:

  .. code-block:: bash

     podman pull ghcr.io/nichd-bspc/llm:latest

**Singularity:**

The default SIF is pulled automatically from GitHub Container Registry. If you
specified a custom ``--sif-path``, make sure the file exists:

  .. code-block:: bash

     ls -lh /path/to/your.sif

- If using ``oras://`` URIs on a system that requires authentication to
  the registry, check that you can reach it.

.. _ts-credentials-expired:

Credentials expired or missing
------------------------------

**Symptom:** The agent starts but cannot connect to the model, or you see
authentication errors like ``ExpiredTokenException``, ``UnauthorizedException``,
or ``The SSO session ... has expired``.

1. On your **local** machine, run :ref:`refresh`:

   .. code-block:: bash

      refresh.py

2. If the session is on a **remote** system, include the hostname:

   .. code-block:: bash

      refresh.py --remote biowulf.nih.gov

3. You do **not** need to restart the container. Because credential files are
   mounted into the container, the running agent will pick up refreshed
   credentials on the next request.

4. If it has been a long time since credentials expired, the agent may have
   given up retrying. Re-send your last prompt.

**Codex login failures:**

:cmd:`refresh.py` calls :cmd:`codex login` under the hood. If this fails,
verify that Codex is installed locally:

.. code-block:: bash

   which codex
   codex --version

If Codex is not installed, follow the local install steps in
:doc:`getting-started-codex`.

**AWS SSO login failures:**

:cmd:`refresh.py` calls :cmd:`aws sso login` under the hood. If this
fails:

- Verify AWS CLI v2 is installed: :cmd:`aws --version` (must be ``2.x``)
- Verify your profile is configured: :cmd:`aws configure list`
- Verify ``AWS_PROFILE`` is set correctly
- Try logging in manually: :cmd:`aws sso login`
- See :doc:`aws-sso` for the full SSO setup walkthrough

.. _ts-ssl-tls:

SSL/TLS connection errors
-------------------------

**Symptom:** Connection errors inside the container, especially on VPN or
enterprise networks. You may see messages about certificate verification
failures, ``CERTIFICATE_VERIFY_FAILED``, or ``SSL: CERTIFICATE_VERIFY_FAILED``.

The container does not have access to host-installed enterprise certificates.
See :doc:`certificates` for full details.

If you are **not** on VPN or an enterprise network and still see SSL errors,
make sure you are not accidentally setting ``LLM_DEVCONTAINER_CERTS`` to
a nonexistent or invalid file.

.. _ts-remote:

Remote system issues
--------------------

Credentials must be refreshed on the local machine and pushed to the remote;
see :ref:`container-notes-login-model` for why this is necessary.

**Credentials not arriving on remote:**

:cmd:`refresh.py --remote HOST` uses :cmd:`rsync` over SSH. If credentials
do not appear on the remote:

- Verify you can SSH to the host without errors: :cmd:`ssh HOST hostname`
- Check that :cmd:`rsync` is available locally: :cmd:`which rsync`
- Use ``--show-files`` to see what would be transferred:

  .. code-block:: bash

     refresh.py --show-files

- Run with ``--full`` if you need to push entire config directories (not
  just credentials):

  .. code-block:: bash

     refresh.py --full --remote biowulf.nih.gov

**Environment variables not set on remote:**

Environment variables exported in your *local* :file:`~/.bashrc` are not
available on the remote host. You must also add the relevant exports
(``CLAUDE_CODE_USE_BEDROCK``, ``AWS_PROFILE``, ``AWS_REGION``, model
defaults, etc.) to the **remote** :file:`~/.bashrc`.

If you use :cmd:`sinteractive` on Biowulf, note that the interactive node
inherits the login node's environment, so exporting in :file:`~/.bashrc` on
Biowulf is sufficient.

.. _ts-singularity:

Singularity-specific issues
---------------------------

**Home directory warnings:**

Singularity normally auto-mounts your home directory. :cmd:`launch.py`
disables this for isolation (see :ref:`container-notes-persistent-mounts`).
If you see warnings about home directory handling, they can generally be
ignored.

**File permission errors:**

Singularity maps your host UID into the container. If files inside the
container are owned by a different user, you may get permission errors. This
usually happens when using a custom SIF built with different user
assumptions. The default image uses ``devuser`` (UID 1000), and
:cmd:`launch.py` handles the mapping.

**Module not loaded:**

On HPC systems, remember to load the Singularity module before running
:cmd:`launch.py`:

.. code-block:: bash

   module load singularity

.. _ts-podman:

Podman-specific issues
----------------------

**Podman machine not running:**

If :cmd:`podman` commands fail with connection errors, make sure Podman
Desktop is running and the Podman machine is started:

.. code-block:: bash

   podman machine list
   podman machine start   # if not running, can also use GUI

**Image pull failures:**

If pulling from GHCR fails, check network connectivity and authentication:

.. code-block:: bash

   podman pull ghcr.io/nichd-bspc/llm:latest

The images are public, so no authentication should be needed. If on VPN,
check for TLS interception issues (:ref:`ts-ssl-tls`).

**Architecture mismatch:**

The container is built for ``linux/amd64``. On Apple Silicon Macs, Podman
handles the emulation transparently. If you encounter architecture-related
errors, ensure your Podman machine is configured for ``amd64`` emulation.

.. _ts-conda:

Conda environments in containers
---------------------------------

**Symptom:** Binaries from a mounted conda environment do not work inside the
container, or packages fail to install.

Mounting conda environments only works on Linux hosts where the architecture
matches the container (``linux/x86_64``). On macOS with Apple Silicon, the
host conda environment is ``arm64`` and the binaries will not run inside the
``amd64`` container.

Additionally, macOS filesystems are case-insensitive, which prevents some
conda packages (like ``ncurses``) from working even if the architecture
matched.

On a compatible Linux host:

.. code-block:: bash

   launch.py --conda-env my-env codex

.. _ts-dry-run:

Using dry-run for debugging
---------------------------

When something is not working, :cmd:`launch.py --dry-run` prints the exact
container command that would be run, without actually running it. This is
useful for inspecting mounts, environment variables, and arguments:

.. code-block:: bash

   launch.py --dry-run codex
   launch.py --dry-run claude
   launch.py --dry-run shell

Compare the output against what you expect: are credential paths mounted?
Are the right environment variables being passed? Is the image correct?

You can also launch a ``shell`` to poke around inside the container
interactively:

.. code-block:: bash

   launch.py shell

This mounts credentials for all agents and drops you into a bash shell
inside the container, where you can inspect the environment directly.

Claude Code-specific issues
---------------------------

- **Update notice:** Claude may display

    ``Update available! Run: your package manager update command``

  This is usually a false positive. The container uses the *stable* version of
  Claude Code as published to the Debain repository. To double-check you can
  run the :cmd:`/doctor` command from within Claude Code. For example, at the
  time of writing these docs, that update message was being shown but
  :cmd:`/doctor` showed the following, indicating that the current version is
  in fact the stable version:

  .. code-block:: text

     Diagnostics
     Currently running: package-manager (2.1.116)
     Commit: 9e176d077241
     Platform: linux-x64
     Package manager: deb
     Path: /usr/bin/claude
     Config install method: not set
     Search: OK (bundled)

     Updates
     Auto-updates: Managed by package manager
     Auto-update channel: latest
     Stable version: 2.1.116
     Latest version: 2.1.123

  In this case, the update is a false positive and can be ignored. Hopefully this
  will be fixed in future stable versions.

- **Copying text:** In recent versions, by default Claude Code will
  *automatically copy* text that you select. If you are used to other text
  selection mechanisms (like tmux), you can use :cmd:`/config` and change *Copy
  on select* to *false*. This will add a new entry in :file:`~/.claude.json`.
