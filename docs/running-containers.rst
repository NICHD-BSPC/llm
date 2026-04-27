Running agents in containers
============================

This page describes how to run agents inside containers, either on a local
machine such as a laptop or on a remote machine such as Biowulf. It covers the
background on what containers are and why this repo uses them, and then the
operational details of launching them with :cmd:`launch.py`.

It is assumed that you at least have successfully finished the
:doc:`getting-started-codex` and/or :doc:`getting-started-claude` sections.

Running a container
-------------------

Use ``launch.py``. This does all sorts of prep work and mounts the right things
in the right places.

.. code-block:: bash

   launch.py codex

This will:

- Mount the credentials needed inside the container
- Mount the agent config directory
- Mount the current working directory
- Start the agent

See :ref:`launch` for details.

.. _running-containers-resuming:

Resuming
--------

Because the agent config directory is mounted from the host, conversations are
saved there and can be resumed later:

.. code-block:: bash

   launch.py codex resume 019d72f9-14e6-7790-9588-418e36739265

Other directories
-----------------

If you need access to other directories, mount them at runtime. By default they
are mounted at the same absolute path as on the host:

.. code-block:: bash

   # this will create a directory, /data/examples, inside the container which
   # will have the contents of the host's /data/examples directory.
   launch.py --mount /data/examples codex


What's a container?
-------------------

A container is a lightweight, isolated collection of software. You build a
container image, which includes an operating system and whatever software you
need, and then run that image as a container.

Containers add setup overhead, but they provide strong isolation from the rest
of the system.

Why containers?
---------------

Without a container, agent tools generally have read access to the entire host
filesystem. If you have PII or sensitive information anywhere on the system, it
could potentially be exposed to agents.

Codex and Claude Code both support sandboxing. That can help restrict writes,
but it does not reliably restrict reads. Those tools usually need access to
standard binaries like :cmd:`git` and :cmd:`ls` outside the working directory, which
still requires filesystem visibility.

Running inside a container narrows that exposure to the mounted workspace and
the small set of config paths these scripts intentionally provide. Tools such as
:cmd:`git` and :cmd:`ls` are installed inside the container, so the agent does not
need to read them from the host.

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
It is already available on NIH HPC; see :nih:`NIH-specific` `Biowulf's Singularity page <https://hpc.nih.gov/apps/singularity.html>`_.

.. _container-notes-terminology:

Terminology
-----------

These docs distinguish between *local*, *remote*, *host*, and *native*.

We distinguish between *local* and *remote* because browser-based login flows behave
differently depending on where the browser is running. The current login
methods need to run on a computer with a web browser that can redirect back
to ``localhost``; in practice, that usually means a local machine.

- Local: the machine where you are logging in with a web browser, for example a
  laptop or desktop
- Remote: a host in a data center, such as Biowulf, without that browser flow
  available

When discussing containers, the *host* is the system running Podman, Docker, or
Singularity.

We use *native* to describe running an agent tool directly on the host rather than
inside a container.

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

This section explains why :cmd:`refresh.py` exists.

The login methods used here are browser-based single sign-on flows. The
browser must be able to redirect to a specific localhost port, so the login
must happen on a local machine and the resulting credentials then copied to
a remote machine if needed:

- :cmd:`codex login` opens a browser to ``https://auth.openai.com/log-in``,
  then waits for a localhost redirect and saves credentials to
  :file:`~/.codex/auth.json`
- :cmd:`aws sso login` opens a browser to the configured page (e.g.,
  :nih:`NIH-specific` ``https://nih.awsapps.com/start``),
  then waits for a localhost redirect and saves credentials under
  :file:`~/.aws/sso`

Using Codex as an example, :cmd:`codex login` opens a web browser. Codex stays
open and listens on a particular localhost port. After you log in, the browser
redirects back to that localhost port and Codex records the login.

This does not work cleanly inside a container. The container does not have a
GUI, and if you paste the login URL into a browser running on the host, the
browser redirects to the *host's* localhost rather than the *container's*
localhost. The callback never reaches Codex inside the isolated container, so it
waits indefinitely.

The same issue exists on remote systems. If you run :cmd:`codex login` on
a remote system, it helpfully prints a URL to visit. If you paste that into
a local browser and log in, the website redirects to your *local* machine, but
Codex is still listening inside the container on the *remote* machine. The
redirect never reaches the remote, let alone inside the container on the remote,
so login cannot complete there.

Port forwarding and tunneling can work around this, but copying the relevant
credential files is simpler. :cmd:`refresh.py` automates that. This is also one of
the approaches suggested in the `Codex auth documentation <https://developers.openai.com/codex/auth#fallback-authenticate-locally-and-copy-your-auth-cache>`_.

How mounting works
------------------

Images are used to create containers. By default, this repo uses the images
created by the GitHub Actions workflow, which in turn are created from the
definition in the Dockerfile. This includes the installation of multiple agentic
tools inside the image.

The goal of a container is to isolate it from the rest of the system. But in
order to be useful, we need to allow *some* parts of the system into the
container. For example, we need to provide credentials to an agent running inside
a container so it can call out to a model. We typically want to add the current
working directory inside the model so that we can work on the files there.

We can mount files from the host into the container by giving a source location
on the host and an intended destination path inside the container. We can
provide environment variables that will be passed in to the container.

The `launch.py` script does some of these things automatically, and allows you
to specify additional things as well.

.. _container-notes-persistent-mounts:

Mounts and config
-----------------

Files and directories on the host can be mounted into a container to
selectively make them available inside the otherwise isolated environment.

The host home directory is not mounted. Even though Singularity mounts it by
default, this setup disables that behavior to reduce exposure.

The user inside the container is called `devuser`, and the home directory is
created at `/home/devuser` inside the container image.

:cmd:`launch.py` mounts a small set of host config and credential paths into
the container, depending on the subcommand. See :doc:`config-files` for the
full list and per-subcommand behavior.

Refreshing credentials
----------------------

You must refresh credentials *outside the container*. Part of the isolation of
a container is a network isolation. When you log in with SSO methods (like AWS
SSO or ChatGPT Enterprise), after logging in the website redirects you to
localhost on the machine running the web browser. But this does not make it into
the container (by design).

Instead, we log in using the local machine (no container), the credentials get
saved to a file, and when we mount that file or directory, the container sees
the updated version.

Similarly, we typically don't run a web browser on a remote system, so after
logging in locally we also need to transport our credentials to the remote.

``refresh.py`` takes care of all of this.

.. code-block:: bash

   refresh.py

To refresh only one credential type:

.. code-block:: bash

   refresh.py --kind codex

To transport to a remote (like NIH's Biowulf):

.. code-block:: bash

   refresh.py --remote biowulf.nih.gov


Conda envs only work on Linux
-----------------------------

The container is ``linux/x86_64``. If the host matches that architecture (like
NIH's Biowful) you can mount tools into the container using ``--path-prepend``
or ``--conda-env``. This is a convenient way to provide development tools inside
the container without rebuilding the image.

You can also pass environment variables through with repeated ``--env
KEY=VALUE`` options.

.. code-block:: bash

   launch.py \
     --conda-env ~/miniconda3/envs/env-to-use \
     --mount ~/data/examples \
     codex

However, if you mount binaries from a macOS ARM64 host, they will not run inside
the container because of the architecture mismatch. There is a workaround but it
is not straightforward. The primary limitation is that the macOS filesystem *is
not case-sensitive*. So common conda packages, like ``ncurses``, that rely on
case-senstive filenames, will not install.
