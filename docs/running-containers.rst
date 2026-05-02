Running agents in containers
============================

**The quickest way to get started is to start with** :doc:`getting-started-codex`.

Then see :doc:`tools` for details and examples for using :ref:`refresh` and
:ref:`launch`.

The rest of this page has details and additional context on containers.

.. _running-containers-resuming:


What's a container?
-------------------

A container is a lightweight, isolated collection of software. You build a
container image, which includes an operating system and whatever software you
need, and then run that image as a container.

Containers add setup overhead, but they provide strong isolation from the rest
of the system.

.. _why-containers:

Why containers for running agents?
----------------------------------

Without a container, agent tools generally have read access to the entire host
filesystem. If you have PII or sensitive information anywhere on the system, it
could potentially be exposed to agents.

Codex and Claude Code both support sandboxing. That can help restrict writes,
but it does not reliably restrict reads. Those tools usually need access to
standard binaries like :cmd:`git` and :cmd:`ls` outside the working directory, which
still requires filesystem visibility.

However, using a sandbox still requires vigilant monitoring of the model's
requests and careful management of allow/deny lists in respective agents'
config files to avoid exposing private information. With no standardized config
format, it's tricky to maintain this.

Running inside a container uses the principle of least privilege, narrowing
exposure to the mounted workspace and the small set of config paths (here, this
is done by :ref:`launch`). Tools such as :cmd:`git` and :cmd:`ls` are installed
inside the container, so the agent does not need to read them from the host.

In practice, containers reduce the blast radius of problems caused by agents.

Because the container already provides isolation, Codex's own sandbox is
disabled inside the container with ``--sandbox danger-full-access``. The
container boundary replaces the built-in sandbox rather than layering on top of
it.

Podman, Docker, Singularity?
----------------------------

Docker is a popular container runtime. However, it has a restrictive license
and may require a paid license for use at NIH.

Podman is a drop-in replacement for Docker with a more permissive license.
Unlike Docker, Podman does not need to run containers as root. Install Podman
Desktop to use it.

Singularity is a different container runtime. A Singularity container can be
built from a Docker or Podman container. It also does not need to run as root.
It is already available on NIH HPC; see :nih:`NIH-specific` `Biowulf's
Singularity page <https://hpc.nih.gov/apps/singularity.html>`_.


.. _images-created:

How are the images created?
---------------------------

This repo uses GitHub Actions to automatically build images on each change to
the code and tests those images (to the extent that it can, without actual
credentials to use models).

The `main workflow
<https://github.com/NICHD-BSPC/llm/tree/main/.github/workflows/main.yml>`__
builds a Podman container using the `Dockerfile
<https://github.com/nichd-bspc/llm/tree/main/Dockerfile>`__ as the
specification (which, among other things, includes installation of Codex,
Claude Code, and Pi). It saves this as a Docker Archive tarball, which is then
passed to Singularity to convert it into the Singularity Image Format (SIF).

When this happens on code in the ``main`` branch, both images are pushed to the
`GitHub Container Registry (GHCR)
<https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry>`__.

GitHub Actions publishes the Podman image to GHCR with these tags:

- ``sha-<git sha>``
- ``latest`` on ``main``
- ``claude-<version>``
- ``codex-<version>``
- ``pi-<version>``

The GitHub Actions container workflow builds ``linux/amd64`` images only. It
first builds and tests the Podman image, then derives the version tags by
running the built container and reading ``claude --version``, ``codex
--version``, and ``pi --version``. The Singularity phase then converts that
same tested Podman image into a SIF artifact.

The workflow also sets ``org.opencontainers.image.source`` to the GitHub
repository URL so the GHCR package stays linked to the repository and inherits
its permissions and visibility.

Running containers without ``launch.py``
----------------------------------------

You can use the containers outside the context of :ref:`launch` like
this to get a bash shell, from which you can start one of the agents.

This will not mount the credentials properly, and Singularity will
**automatically mount your entire home directory** unless you use ``--no-home``
and will **expose all env vars** unless you use ``--cleanenv``.

Consider using the output of :cmd:`launch.py --dry-run shell` as a starting
point for composing your own commands, since that shows all of the mounts and
environment variable exports needed.

.. code-block:: bash

   podman run --rm -it ghcr.io/nichd-bspc/llm

.. code-block:: bash

   singularity exec ghcr.io/nichd-bspc/llm-sif bash

.. _container-notes-terminology:

Terminology
-----------

Throughout these docs we use the terms *local*, *remote*, *host*, and *native*.

- Local: the machine where you are logging in with a web browser, for example a
  laptop or desktop
- Remote: a host in a data center, such as Biowulf, without that browser-based
  flow available
- Host: the system running Podman/Docker/Singularity
- Native: running an agent tool directly on the host rather than inside a container

For example:

+------------+--------------------------------+---------------+--------+-------+
| Machine    | Running                        | Native?       | Local? | Host  |
+============+================================+===============+========+=======+
| Mac laptop | Codex in Podman container      | containerized | local  | macOS |
+------------+--------------------------------+---------------+--------+-------+
| Biowulf    | Codex in Singularity container | containerized | remote | Linux |
+------------+--------------------------------+---------------+--------+-------+
| Mac laptop | Codex installed on macOS       | native        | local  | N/A   |
+------------+--------------------------------+---------------+--------+-------+
| Biowulf    | Codex installed on Linux       | native        | remote | N/A   |
+------------+--------------------------------+---------------+--------+-------+

.. _container-notes-login-model:

Login model
-----------

This section explains why :ref:`refresh` exists.

In browser-based single sign-on flows like those used here, the browser must be
able to redirect to a specific localhost port that a tool is listening on in
order for the tool to detect that login was successful and then save a local
file to persist that information. For example:

- For Codex, :cmd:`codex login` opens a browser to
  ``https://auth.openai.com/log-in``, then waits for a localhost redirect to
  a specific port and when it receives it, saves credentials to
  :file:`~/.codex/auth.json`
- For Claude, :cmd:`aws sso login` opens a browser to the configured page
  (e.g., :nih:`NIH-specific` ``https://nih.awsapps.com/start``), then waits for
  a localhost redirect to a specific port and when it receives it, saves
  credentials under :file:`~/.aws/sso`

This does not work cleanly inside a container. The container does not have a
GUI (and therefore no browser). If you paste the login URL into a browser
running on the host, the browser redirects to the *host's* localhost rather
than the *container's* localhost. So the callback never reaches Codex inside the
isolated container. . . and it waits indefinitely.

The same issue exists on remote systems. If you run :cmd:`codex login` on
a remote system, it helpfully prints a URL to visit. If you paste that into
a local browser and log in, the website redirects to your *local* machine. But
Codex is still listening inside the container on the *remote* machine. The
redirect never reaches the remote, let alone inside the container on the
remote, so login cannot complete there either.

Port forwarding and tunneling can work around this, but copying the relevant
credential files is simpler.

:ref:`refresh` automates this. Locally, it is just running :cmd:`codex login`
and :cmd:`aws sso login` (but only if you're not already logged in). It knows
what files need to be transported to the remote host (see :doc:`config-files`
for these) and takes care of the ``rsync`` commands for that as well.

This copying mechanism is also one of the
approaches suggested in the `Codex auth documentation
<https://developers.openai.com/codex/auth#fallback-authenticate-locally-and-copy-your-auth-cache>`_.

Refreshing credentials without stopping container
-------------------------------------------------

You must refresh credentials *outside the container* (see
:ref:`container-notes-login-model`) but you don't need to stop the container to
do this. See :ref:`ts-credentials-expired` for troubleshooting expired or
missing credentials. For example, Claude Code running in a container may not be able to
connect due to credentials expiring, but as soon as you use :ref:`refresh` and
the credentials on the host are updated, Claude Code will immediately see them
since they are mounted into the container. While Claude Code does retry
attempts, if it has been a while between old credentials expiring and new ones
being available then you might need to re-send your latest prompt.


.. _container-notes-persistent-mounts:

Mounts and config
-----------------

The goal of a container is to isolate it from the rest of the system. But in
order to be useful, we need to allow *some* parts of the system into the
container. For example, we need to provide credentials to an agent running inside
a container, and we typically want to add the current working directory inside
the model so that we can work on the files there.

We can mount files from the host into the container when first starting the
container by giving a source location on the host and an intended destination
path inside the container. The :ref:`launch` script does this automatically for
the working directory and the crendential files, and allows you to specify
additional paths if needed with ``--mount``.

The host's home directory is not mounted. Even though Singularity mounts it by
default, this setup disables that behavior to reduce exposure.

Only the credentials and config needed for each tool is mounted -- unless you
call :ref:`launch` with ``shell`` which will mount them all.

If you regularly mount the same extra paths, set
``LLM_DEVCONTAINER_MOUNTS`` to a shell-style list of mount specs using the same
format as ``--mount``. For example:

.. code-block:: bash

   export LLM_DEVCONTAINER_MOUNTS="$HOME/data $HOME/.gitconfig:/home/devuser/.gitconfig:ro"

The user inside the container is called ``devuser``, and the home directory is
created at :file:`/home/devuser` inside the container image.


Conda envs only work on Linux
-----------------------------

The container is ``linux/x86_64`` architecture. If the host matches that
architecture (like NIH's Biowulf) you can mount directories into the container
using ``--path-prepend`` or ``--conda-env``. This is a convenient way to
provide development tools, like everything inside a conda environment, inside
the container without needing to change the image.

.. code-block:: bash

   launch.py \
     --conda-env ~/miniconda3/envs/env-to-use \
     --mount ~/data/examples \
     codex

However, if you mount binaries from a macOS ARM64 host, they will not run inside
the container because of the architecture mismatch. There is a workaround but it
is not straightforward and requires root. The primary limitation is that the
macOS filesystem *is not case-sensitive*. So common conda packages, like
``ncurses``, that rely on case-senstive filenames, will not install.

This case-sensitivity is on the host macOS side, but a container running on
a macOS host is inherently affected by this. So even running conda inside
a container to build a ``linux/amd64`` env will fail (typically tools
depending on ``ncurses`` -- of which there are many -- will fail because
ncurses requires case sensitivity).

Workaround for using conda on macOS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One workaround is to not use a container at all. This is risky since it exposes
the rest of the machine. You may want to carefully construct a config file in
the local directory (:file:`.codex` or :file:`.claude`) with appropriate
permissions to lock down the sandbox.

Another workaround is to create a case-sensitive volume on macOS and get it
into the running container.

.. warning::

   This workaround is not straightforward, but it's mostly a one-time setup and
   it does work.

**1. Make a case-sensitive volume (one-time setup).**

First, create a new volume on macOS that *is* case sensitive:

- Open Disk Utility (:file:`/Applications/Utilities/Disk Utility`)
- Select your APFS container in the sidebar
- Click + (*Add Volume*)
- Set the format to *APFS (Case-sensitive)*
- Name it (e.g., ``devel``) and click Add
- The new volume mounts at :file:`/Volumes/devel`

**2. Re-initialize podman (every restart of Podman).**

Next, we need to tell Podman about that new volume, and get it mounted in the
podman machine. The podman machine is the VM used by Podman to emulate Linux --
it's sort of the parent container of the normal containers we use. We do this
by re-making the podman machine, including its default mounts but also our new
one (you'll need to change your volume name to the one you created above):

.. code-block:: bash

  # Re-initialize the podman machine with our new mount. Needs to happen every
  # time Podman Desktop is restarted.
  podman machine stop
  podman machine rm --force
  podman machine init \
    --volume /Users:/Users \
    --volume /private:/private \
    --volume /Volumes/devel:/Volumes/devel
  podman machine start

**This needs to be re-run every time Podman Desktop restarts**, because Podman
Desktop uses default mounts that do not include our custom one. There does not
appear to be a config file we can change to make this more permanent.

**3. Install conda on the case-sensitive volume (one-time setup).**

Here is how to create and mount the right directories to be able to install
a version of conda to that case-sensitive directory, using the Linux container.
This effectively creates a ``linux/amd64``-usable conda installation we can use
to create ``linux/amd64`` environments. Note that this method makes separate
cache and conda dirs to mount into the container's home directory to avoid
contaminating the host's directories.

This command:

- creates directories to be used by conda and mounts them
- mounts the case-sensitive volume
- runs the container using :cmd:`shell`, and effectively sending an in-line
  bash script with ``bash -c ...`` that performs the Miniforge installation
  from the `Miniforge docs <https://github.com/conda-forge/miniforge>`__.
- exits the container when done

.. code-block:: bash

   # install miniforge on case-sensitive volume, using container
   mkdir -p ~/.devcontainer/.{cache,conda}
   launch.py \
     --mount ~/.devcontainer/.conda:/home/devuser/.conda \
     --mount ~/.devcontainer/.cache:/home/devuser/.cache \
     --mount /Volumes/devel \
     shell \
     bash -c ' \
     curl -fSsL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh" \
     > /Volumes/devel/miniforge.sh && \
     bash /Volumes/devel/miniforge.sh -p /Volumes/devel/miniforge -u -b -s '

**4. Create environments (as needed).**

Now that conda is installed, for conda env creation and mainentance you can use
the following:

.. code-block::

   # launch a shell for conda maintenance
   launch.py \
     --mount ~/.devcontainer/.conda:/home/devuser/.conda \
     --mount ~/.devcontainer/.cache:/home/devuser/.cache \
     --mount /Volumes/devel \
     --path-prepend /Volumes/devel/miniforge/bin \
     shell

If you're working in a project directory on the regular macOS filesystem and
want a case-sensitive env you can let an agent use:

.. code-block::

   # single command for creating an env
   launch.py \
     --mount ~/.devcontainer/.conda:/home/devuser/.conda \
     --mount ~/.devcontainer/.cache:/home/devuser/.cache \
     --mount /Volumes/devel \
     --path-prepend /Volumes/devel/miniforge/bin \
     shell conda create -p /Volumes/devel/proj-env --file requirements.txt


**5. Using environments (routine usage).**

Now whenever you run an agent, provide that path to ``--conda-env``. In this
example for testing, we're running :cmd:`codex exec` to just run that prompt
and then exit, but running the agent as normal will allow it to use that conda
env.

.. code-block::

   # routine usage
   launch.py \
     --conda-env /Volumes/devel/proj-env \
     codex exec "what version of pandas do I have installed, and what directory is it in?"

