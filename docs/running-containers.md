# Running agents in containers

> [!IMPORTANT] Contents
> [TOC]

Here we document how to run agents inside containers, either on a local machine (like a laptop) or on a remote (like Biowulf). See [container-notes](container-notes.md) for what this means.

## Prerequisites

- It is expected that you, or a sysadmin, has already built a container and that it is available on the host you plan to run it on. See [building containers](building-containers.md) for more on this.
- If running locally, you have [Podman Desktop](https://podman-desktop.io/) installed and it is running
- If running remotely (like on Biowulf), you have Singularity installed and available on your PATH. E.g., on Biowulf, `module load singularity`.
- You have the `refresh.py` script available from this repo on your local machine
- If running remotely, you have the `launch.py` script available
- The examples below assume these scripts are on your `PATH`. If not, invoke them with `./` from the repo directory (e.g., `./refresh.py`).
- If using AWS SSO for Claude Code, you have the required dependencies installed and available (see [conda env](conda-env.md) for users and [aws-sso](aws-sso.md) for sysadmins)

## Local

### Refresh credentials

The following will refresh your credentials for both Codex and AWS (used by Claude Code).

```bash
refresh.py
```

If you only want to refresh one, use the `--kind` argument, e.g.,

```bash
refresh.py --kind codex
```
### Run the container

Use the launch script to launch the Docker/podman container:

```bash
launch.py --backend podman codex
```

or

```bash
launch.py --backend podman claude
```

 This will:

- mount the credentials needed into the container
- mount the agent's respective config directory into the container
- mount the current working directory into the container
- start the agent

The rest of this section describes more advanced use.

#### Resuming

Since the respective agent's config directory is mounted from the host, conversations will be saved to that config directory on the host. So after exiting a container, you can resume later, e.g.:


```bash
launch.py --backend podman codex resume 019d72f9-14e6-7790-9588-418e36739265
```


#### Other directories

If you need access to other directories, they can be mounted at runtime. By default they will be mounted at the same absolute path as the host:


```bash
# If the host user is "username" on a Mac, the container
# will have /Users/username/data/examples mounted:
launch.py --mount ~/data/examples --backend podman codex
```

#### Tools inside the container (when the host is Linux x86_64)

The container is linux/x86_64 architecture. If you are running on a host with this architecture, you can mount tools inside the container with the `--path-prepend` argument or the `--conda-env` argument. This is a convenient way of having development tools available inside the container without having to re-create the container with all the tools.

You can also pass environment variables through to the container with `--env KEY=VALUE`. Specify `--env` multiple times to pass multiple variables.

```bash
launch.py \
  --conda-env ~/miniconda3/envs/env-to-use \
  --mount ~/data/examples \
  codex
```

#### Tools inside the container (when the host is not Linux x86_64)

If you mount binaries from a macOS (ARM64) host, **they will not run inside the container** because of the different architecture. Consider running on a remote Linux host instead. Alternatively, you can create an environment specific to the container: launch a shell container, mount the current directory, create a temp conda installation, create an env in the path, and then start a new container running an agent with `--conda-env`:

```bash
# launch a shell instead of claude or codex
launch.py --mount $(pwd):/workspace --backend podman shell
```

```bash
# once inside the container, install conda and create an environment,
# ./linux-env, in this  directory. It will show up on the host (but won't be
# usable by the host due to different architecture). Here we're just installing
# Python and pandas
curl -fsSLo Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3.sh -b -p /tmp/conda
source /tmp/conda/etc/profile.d/conda.sh
conda create -y -p ./linux-env python pandas
exit
```

Then, launch a Codex or Claude Code container with that conda env provided as the `--conda-env` arg:

```bash
launch.py --conda-env ./linux-env --backend podman codex
```

To check:

```bash
# Inside Codex, inside the container, check the path to Python
# using ! to make a shell call from Codex; it should be coming from the
# linux-env/bin directory:
! which python
```

## Remote

The main difference with running on a remote system is that you need to refresh your credentials *locally* and then transport them to the right place on the remote. Use `refresh.py` for this:

```bash
refresh.py --remote helix.nih.gov
```

See [container-notes](container-notes.md) for details on why this is.

Once on the remote,

```bash
launch.py codex
```

will work the same way it does locally.

See [container-notes](container-notes.md) for more details on how paths are mounted.

*Back to [README.md](../README.md)*
