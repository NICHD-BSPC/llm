.. _tools:

Tools Reference
===============

This repository provides four utility scripts:

1. :file:`refresh.py` refreshes local credentials and can copy them to a remote host
2. :file:`launch.py` starts agents inside a container
3. :file:`agentsview.py` a browser view of agent sessions
4. :file:`build.py` builds the container image itself

You'll usually only need :file:`refresh.py` and :file:`launch.py`.

Use :file:`build.py` only if you want to build your own image rather than use
the hosted one.

.. _getscripts:

How to get the scripts
----------------------

You will need :file:`refresh.py` and :file:`agentsview.py` on the local
machine, and :file:`launch.py` on whatever machine (local and/or remote) you
want to run an agent container on.

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
      curl -fSsL -o ~/bin/agentsview.py https://raw.githubusercontent.com/nichd-bspc/llm/main/agentsview.py
      chmod +x ~/bin/launch.py ~/bin/refresh.py ~/bin/agentsview.py

      # on remote we only need launch.py
      curl -fSsL -o ~/bin/launch.py https://raw.githubusercontent.com/nichd-bspc/llm/main/launch.py
      chmod +x ~/bin/launch.py

Then either call them directly with the full path name, or add them to your
``PATH``. For example, if you cloned the repo to your home directory, you would
add this to your :file:`~/.bashrc` (or wherever you set your ``$PATH``
variable):

.. code-block:: bash

   export PATH="$PATH:~/llm"

.. note::

   See `Julia Evans' excellent writeup
   <https://jvns.ca/blog/2025/02/13/how-to-add-a-directory-to-your-path/>`__ on
   ``$PATH`` and adding to it if you're unfamiliar with the concept.

.. tip::

   You know it's working if you open a new terminal and can run :cmd:`launch.py
   -h` and/or :cmd:`refresh.py -h` to see the help.

.. _refresh:

``refresh.py``
--------------

Refreshes credentials locally, and optionally copies them to a remote host.

- Refreshes Codex authentication (:file:`~/.codex/auth.json`). This is mounted inside running Codex containers, so they will see the new credentials when refreshed.
- Refreshes AWS SSO credentials and exports a managed profile bundle under
  :file:`~/.aws/llm-export`. The bundle is used via ``credential_process`` so
  containers can read refreshed credentials; see :ref:`config-aws-export` for
  why this indirection exists.
- Converts the OpenAI auth tokens in :file:`~/.codex.auth.json` to
  a Pi-compatible format and stores in :file:`~/.pi/agent/auth.json` so that Pi
  can use ChatGPT Enterprise within a container. This needs the
  :ref:`auth-reload <pi-auth-reload>` extension installed.
- Optionally pushes refreshed credentials to a remote host (such as NIH's Biowulf).
- Optionally pushes entire config directories to remote.
- Optionally prints Bedrock bearer-token exports for tools that do not use the AWS SDK.

.. note::

   If credentials expire mid-session, run :cmd:`refresh.py` and retry the
   prompt. Use ``--remote HOST`` when the container runs remotely. The mounted
   managed file can update without recreating the container, but an SDK or agent
   may cache credentials until its normal refresh point. If retrying still uses
   expired credentials, restart the agent process; see
   :ref:`ts-credentials-expired`.

Examples
~~~~~~~~

Refresh codex & aws locally:

.. code-block:: bash

   refresh.py

Refresh all and push credentials to a remote system. This exports the managed
AWS session credential bundle to :file:`~/.aws/llm-export` on the remote. The
local SSO cache is not transferred:

.. code-block:: bash

   refresh.py --remote biowulf.nih.gov

Only refresh codex, and push to remote system:

.. code-block:: bash

   refresh.py --kind codex --remote biowulf.nih.gov

Skip creating and transferring the managed AWS export for this invocation:

.. code-block:: bash

   refresh.py --no-export-creds --remote biowulf.nih.gov

``--no-export-creds`` removes :file:`~/.aws/llm-export` from that invocation's
remote transfer set, even if a stale bundle already exists locally. It does not
delete an older bundle already present on the remote.

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

``--bedrock-export`` is a separate execution mode. It ignores ``--kind`` and
``--remote`` and does not enter the normal credential-refresh or transfer
workflow.

Use a specific AWS source profile for this run, rather than whatever
``AWS_PROFILE`` says:

.. code-block:: bash

   refresh.py --aws-profile AWSPowerUserAccess-00001

.. _refresh-aws-profile:

Selecting the AWS source profile
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:cmd:`refresh.py` reads credentials from a *source* profile and writes them to
the managed ``llm-export`` *destination* profile. The source profile is
resolved once per run, in this order:

1. ``--aws-profile PROFILE``
2. an inherited ``AWS_PROFILE`` environment variable
3. otherwise, normal AWS CLI default-profile behavior

The resolved profile is used consistently for the credential expiration check,
:cmd:`aws sso login`, the process-format credential export, and Bedrock
bearer-token generation. The selected source profile name and the destination
profile name are logged; credential values never are.

There is no separate profile configuration file for this tool -- use the AWS
CLI's own profiles.

.. _refresh-macos-shortcut:

Running from a macOS Shortcut
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:file:`refresh_macos_shortcut.sh` wraps ``refresh.py --remote`` so it can run
from the macOS Shortcuts app (e.g., from the menu bar, a keyboard shortcut, or
Siri) instead of a terminal. It shows desktop notifications as it goes and
writes a log you can check if something goes wrong.

What it does:

- Loads your SSH key into the agent using the passphrase saved in the login
  keychain (``ssh-add --apple-load-keychain``), so the rsync to the remote does
  not need a terminal prompt.
- Runs ``refresh.py --remote HOST --user USER --notification-events``.
- Shows notifications, like when :cmd:`refresh.py` is about to open a browser
  for AWS SSO or Codex login, and success/failure.
- If the only error was that the remote couldn't be contacted (e.g., you're not
  on VPN), then the log is not shown. Any other errors, the log is shown.

The script reads these environment variables:

.. list-table::
   :header-rows: 1

   * - Variable
     - Required
     - Meaning
   * - ``LLM_REMOTE_HOST``
     - yes
     - Remote host to push credentials to (passed to ``--remote``)
   * - ``LLM_REFRESH_SCRIPT``
     - yes
     - Full path to :file:`refresh.py`
   * - ``LLM_REMOTE_USER``
     - no
     - Username on the remote (passed to ``--user``); defaults to ``$USER``

Shortcuts runs scripts with a minimal environment, so your shell startup
files are **not** read. Set the variables in the shortcut itself, or in a file
that the shortcut sources.

To set it up:

1. Open Shortcuts.app and create a new shortcut.
2. Add a **Run Shell Script** action, with shell set to ``bash``.
3. Set the script to something like:

   .. code-block:: bash

      export LLM_REMOTE_HOST=biowulf.nih.gov
      export LLM_REMOTE_USER=myusername   # only if different from local $USER
      export LLM_REFRESH_SCRIPT="<path to refresh.py>"
      export PATH="<where aws cli is installed>:$PATH"
      "<path to refresh_macos_shortcut.sh>"

   or, if you have those env vars stored somewhere else like :file:`~/.extra`,

   .. code-block:: bash

      source ~/.extra
      source ~/.path
      "<path to refresh_macos_shortcut.sh>"

4. Run it once by hand. macOS may ask to allow notifications and to let
   Shortcuts control other apps; allow both.

5. Add a shortcut key (this is under the circled "i" menu for the shortcut,
   under "Details" tab).

The log for the most recent run is at
:file:`~/Library/Logs/llm-refresh.log` and is overwritten on each run. It has
everything :cmd:`refresh.py` printed plus the exit code.

.. note::

   The script's stdin is ``/dev/null``, so anything in :cmd:`refresh.py` that
   waits for keyboard input fails right away (and shows up in the log) instead
   of hanging. If you need to answer a prompt, run :cmd:`refresh.py` from a
   terminal instead.

.. _launch:

``launch.py``
-------------

Runs the agent inside a container, assuming credentials are already available,
e.g., by running :ref:`refresh`.

- Starts :cmd:`codex`, :cmd:`claude`, :cmd:`pi`, :cmd:`omp`, or an interactive shell in a container
- Passes through mounts, env vars, cert bundles, and optional conda environments
- Detects Podman vs Singularity, or accepts an explicit backend
- Defaults to automatically pulling the latest container for the launched
  harness, published by this repo to GitHub Container Registry
  (https://ghcr.io/nichd-bspc/llm). Each harness has its own ``latest`` tag
  (``codex-latest``, ``claude-latest``, ``pi-latest``, and ``omp-latest``) that
  only moves when that harness changes version, so you don't pull a fresh image
  every day if the harness is unchanged. The ``shell`` subcommand uses the
  overall ``latest`` tag though, so that will change every day. Use ``--tag``
  to pick a different tag (e.g. ``--tag latest`` for the latest overall image, or
  ``--tag codex-0.125.0`` to pin a version), or ``--image-name`` / ``--sif-path``
  for full control.
- By default, mounts the current working directory and only the
  credential/config paths relevant to the called tool

Default config and credential mounts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, :cmd:`launch.py` mounts the current working directory.

Also by defaut, it mounts the following host paths in a tool-specific manner
into :file:`/home/devuser` inside the container when they exist:

- :cmd:`launch.py codex`: :file:`~/.codex`
- :cmd:`launch.py claude`: :file:`~/.claude` and :file:`~/.claude.json`
- :cmd:`launch.py pi`: :file:`~/.pi`
- :cmd:`launch.py omp`: :file:`~/.omp`
- :cmd:`launch.py shell`: :file:`~/.codex`, :file:`~/.claude`,
  :file:`~/.claude.json`, :file:`~/.pi`, and :file:`~/.omp`

For ``omp`` and ``shell``, the Codex access token in :file:`~/.codex/auth.json`
is additionally passed as ``OPENAI_CODEX_OAUTH_TOKEN`` (via the private
environment file, like other secrets) so OMP can use its ``openai-codex``
provider. The token is read at launch; if it is expired, it is skipped with
a warning. Run :cmd:`refresh.py --kind codex` to renew it. OMP prefers a stored
``/login`` credential over this variable.

Amazon Bedrock credential mounts are added under these circumstances:

- ``claude``: when ``CLAUDE_CODE_USE_BEDROCK=1``
- ``pi``: when ``PI_USE_BEDROCK=1``
- ``omp``: when ``OMP_USE_BEDROCK=1``
- ``shell``: when any of those three variables is ``1``

If the managed bundle under :file:`~/.aws/llm-export` is valid, ``launch.py``
automatically uses the ``llm-export`` profile unless an AWS profile or static
credentials were explicitly supplied with ``--env``. An inherited host
``AWS_PROFILE`` remains the source-profile default for :cmd:`refresh.py`, but
the valid managed bundle takes priority for the container. Only the managed
bundle is mounted in this mode, read-only. An explicit or fallback non-managed
AWS profile mounts :file:`~/.aws` read-only; static credentials do not add an
AWS mount.

Automatic selection requires more than the presence of a file: :cmd:`launch.py`
checks the managed config, exact ``credential_process`` path, process JSON
fields and expiration, and private credential-file permissions. If a managed
bundle exists but is invalid and no explicit launcher override was supplied,
launch fails early and asks you to run :cmd:`refresh.py` rather than falling
back to inherited credentials.

AWS authentication modes and precedence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bedrock launches distinguish these credential sources, in order:

1. **Explicit static credentials.** A complete access-key and secret-key pair
   supplied with repeatable ``--env`` options takes precedence. It is delivered
   through a private temporary environment file and does not add an AWS mount.
2. **Explicit profile.** ``AWS_PROFILE`` supplied with ``--env`` selects that
   profile. The full host :file:`~/.aws` directory is mounted read-only because
   an arbitrary profile may use shared credentials, SSO cache files, or its own
   ``credential_process``.
3. **Managed profile.** With neither explicit override, a valid managed bundle
   is selected as ``llm-export`` and only :file:`~/.aws/llm-export` is mounted
   read-only. An existing invalid bundle fails with a refresh instruction
   rather than silently changing AWS identity.
4. **Inherited profile fallback.** Without a managed bundle, an inherited host
   ``AWS_PROFILE`` selects that profile and mounts :file:`~/.aws` read-only.
5. **Inherited static fallback.** If no profile or managed bundle exists, a
   complete access-key and secret-key pair inherited from the host is supported
   without an AWS mount. Partial static credentials fail validation.

When either inherited fallback is used, :cmd:`launch.py` warns that the managed
bundle is missing and suggests creating it with :cmd:`refresh.py`. Explicit
profiles and static credentials supplied with ``--env`` do not produce this
warning.

In short:

.. code-block:: text

   Host AWS_PROFILE -> refresh.py source profile
   Managed llm-export -> default container profile

Remote hosts normally leave ``AWS_PROFILE`` unset. To request a different
container profile, use ``launch.py --env AWS_PROFILE=...`` explicitly.

``AWS_BEARER_TOKEN_BEDROCK`` is a separate fixed bearer token, primarily for
clients that do not use the AWS SDK; see :doc:`bedrock-keys`. It is protected by
the same temporary environment-file handling when passed with ``--env``, but it
is not the managed ``llm-export`` profile.

If host proxy variables are set, :file:`launch.py` passes them through to the
container.

See :doc:`config-files` for what those files and directories contain.

Example usage
~~~~~~~~~~~~~

.. note::

   Unless noted otherwise, these examples use Codex for simplicity. Replace
   ``codex`` with ``claude``, ``pi``, ``omp``, or ``shell`` as needed.

Basic usage
^^^^^^^^^^^

.. note::

   Any arguments that come **before** the tool (codex/claude/pi/omp) are interpreted as arguments for ``launch.py``.

   Any arguments that come **after** the tool are interpreted as arguments for the tool.

   For example, this shows the help for :cmd:`launch.py` (note the ``-h`` comes *before* ``codex``):

   .. code-block:: bash

      launch.py -h codex

   But this shows the help for codex, as run through the container (note the ``-h`` comes *after* ``codex``):

   .. code-block:: bash

      launch.py codex -h

Run codex, detecting container runtime automatically (Podman on Mac, Singularity
on Linux):

.. code-block:: bash

   launch.py codex

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

   launch.py --global-read-only codex

Keep the working directory writable but protect a single subdirectory. The
``--ro`` path is re-mounted read-only on top of the read-write workspace, so its
contents remain readable but cannot be modified:

.. code-block:: bash

   launch.py --ro data codex

``--ro`` takes a path relative to the current working directory (or an absolute
path inside it) and may be repeated to protect several subdirectories.

Hide a sensitive subdirectory of the working directory from the container. The
rest of the working directory is mounted as usual, but the masked path is
shadowed by an empty, read-only directory so its contents are not visible
inside the container:

.. code-block:: bash

   launch.py --mask secrets codex

``--mask`` takes a path relative to the current working directory (or an
absolute path inside it) and may be repeated to mask several subdirectories.

To keep a default set of extra mounts, put them in
``LLM_DEVCONTAINER_MOUNTS`` as a shell-style (space-separated) list:

.. code-block:: bash

   export LLM_DEVCONTAINER_MOUNTS="$HOME/data /scratch/shared:/scratch/shared:ro"

   # equivalent of the following, but will happen by default:
   # launch.py --mount $HOME/data --mount /scratch/shared:/scratch/shared:ro

Mount a conda env into the container and prepend it to the path so the agent
can use it (only works on Linux, but see :ref:`conda-only-linux` for
a workaround):

.. code-block:: bash

   launch.py --conda-env my-env codex

Using ``--conda-env`` is a shortcut for the following:

.. code-block:: bash

   launch.py \
     --mount $(conda info --base)/envs/my-env \
     --prepend-path ~/conda/envs/my-env/bin \
     codex

Environment and certificates
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Provide additional environment variables to the container, or override what's
in the environment:

.. code-block:: bash

   launch.py \
     --env OMP_NUM_THREADS=1 \
     --env HOME=/tmp \
     codex

AWS access keys, secret keys, session/security tokens, and Bedrock bearer tokens
are passed to both supported container runtimes through a temporary environment
file rather than as command arguments. The file and its private temporary
directory are removed after the container exits or if launch fails. Sensitive
values are not shown by ``--dry-run``; only the temporary file path appears.
Newlines, NUL bytes, and quote characters are rejected in these values because
they cannot be represented consistently in both runtimes' environment-file
formats.

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
without running. Useful for debugging (see also :ref:`ts-dry-run`):

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

To stay on the published images but choose a different tag, use ``--tag``:

.. code-block:: bash

   # use the latest overall image instead of the per-harness latest
   launch.py --tag latest codex

   # pin a specific harness version
   launch.py --tag codex-0.125.0 codex




.. _launchenv:

Environment variables created by :file:`launch.py`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Supply additional env vars at the command line with ``--env NAME=VALUE``. This
can be used to override defaults. The following environment variables are set by
default in the container:

**Base environment:**

- ``HOME`` – set to ``/home/devuser``
- ``USER``, ``LOGNAME``, ``USERNAME`` – set to ``devuser``
- ``TOOL`` – the subcommand being run (``codex``, ``claude``, ``pi``, ``omp``, or ``shell``); this is only used for information
- ``HOST_MOUNT_DIR`` – the current working directory on the host
- ``PATH`` – constructed from the base Ubuntu PATH plus ``/home/devuser/.local/bin``, with optional prepends from ``--conda-env`` or ``--path-prepend``

**Tool-specific inherited variables:**

- For ``claude`` and ``shell``: All host environment variables starting with ``CLAUDE_CODE`` or ``ANTHROPIC_``
- For ``pi``, ``omp``, and ``shell``: All host environment variables starting with ``PI_``
- For ``omp`` and ``shell``: All host environment variables starting with ``OMP_``
- For ``claude``, ``pi``, ``omp``, and ``shell``: When Bedrock is enabled via
  the corresponding launcher switch: Host environment variables starting with
  ``AWS_``. If ``AWS_PROFILE`` is set or the automatic ``llm-export`` profile
  is in use, direct static credential variables are not sent to the container
  so that the selected profile's ``credential_process`` works properly.
  Sensitive AWS values that are sent use a private temporary environment file
  and do not appear in container-runtime command arguments.

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

.. _agentsview:

``agentsview.py``
-----------------

Browse Claude, Pi, OMP, and Codex sessions using
`agentsview <https://github.com/kenn-io/agentsview>`__ running in a Podman image.

By default, this serves on localhost port 8080, so visit 127.0.0.1:8080 in
a browser to explore the interface. If any of the supported harnesses have
existing directories, they will be mounted read-only into the container for
exploration.

The `agentsview docs <https://www.agentsview.io/>`__ describe all sorts of ways to
explore sessions. This includes things like cost, flagging issues, search all
transcripts to find that thing you were working on 6 weeks ago, and look for
trends. All data stays local, and telemetry is disabled.

Example usage:

.. code-block:: bash

   # Serve on http://127.0.0.1:8080
   agentsview.py

   # Serve on http://127.0.0.1:9000 instead, and run in the background.
   # Stop later with `podman stop agentsview`
   agentsview.py --port 9000 --detach

   agentsview.py --remote biowulf.nih.gov                    # local + biowulf.nih.gov
   agentsview.py --remote biowulf.nih.gov --remote vm        # local + two remotes
   agentsview.py --remote-only biowulf.nih.gov               # just biowulf.nih.gov

   # Log each ssh/rsync/podman command as it runs
   agentsview.py --verbose

Within the agentsview app, the Machine filter lets you choose between
local/remotes, and the list of sessions along the left side shows the hostname
for remote sessions.

Further details:

The script rewrites ``/data/config.toml`` on every run. This is needed to
configure the local and remote sessions, but it means that settings changed in
the agentsview UI are not saved between runs.

For remote hosts, the script checks for available session paths over SSH,
pulls a snapshot for each host with rsync into a private temporary directory,
and removes it when the foreground server exits. Run again to refresh.
``--remote`` is repeatable; ``--remote-only`` serves one remote without local
sessions. Both take plain hostnames; ``--user`` applies to every remote.
``--detach`` is local-only.

The temp dir is removed when you stop the server with Ctrl-C or when it exits
on an error. But if the script is killed instead (e.g., ``kill PID`` or
``timeout``), the temporary directory (``agentsview-*`` under your system's
temp dir) is left behind and the container keeps running. Stop it with
``podman stop agentsview`` (or ``agentsview-HOST`` for remote-only) and remove
the directory by hand. Symlinked session directories on the remote are
followed, and pulled paths are checked before starting the container.

.. warning::

   Removing the temporary directory does **not** remove the remote sessions
   from your machine. agentsview archives every session it indexes into its
   data volume (``agentsview-data`` for combined, ``agentsview-data-HOST``
   for remote-only), and keeps them after the source files are gone. To delete
   that copy, stop the container and remove the relevant Podman volume.


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

See :doc:`developer`. Image maintainers should keep a full checkout
and run :cmd:`./build.py` from the repo root.
