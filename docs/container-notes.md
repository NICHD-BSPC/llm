# Notes on containers

> [!important] Contents
> [TOC]


## What's a container?

A container is a lightweight, isolated collection of software. You build a *container image*, which includes things like an operating system and any software you want to install (here, it's Linux along with Codex and Claude Code and some supporting tools). Then you run the image, which creates a running container. You can run multiple containers from the same image. Each container is isolated from the rest of the system, unless you explicitly choose to allow it to interact with the host system.

It's some extra setup, but it affords strong isolation from the rest of the system.

## Why containers?

Without a container, agent tools generally have read access to the *entire* host filesystem. If you have PII or sensitive information *anywhere on the system* then it is possible it could be exposed to agents. Codex and Claude Code support sandboxing. This can help with restricting writes, but they do not reliably limit reads. For example, they typically need to be able to access standard tools like `git` and `ls` that are outside the working directory, which requires read access.

Running inside a container narrows that exposure to the mounted workspace and the small set of config paths the scripts intentionally provide. Tools like `git` and `ls` are installed *inside the container*, there's no need for the agent to read anything on the host.

In essence, containers limit the "blast radius" of any potential issues caused by agents.

Because the container already provides this isolation, Codex's own sandboxing is disabled inside the container (`--sandbox danger-full-access`). The container boundary replaces the built-in sandbox rather than layering on top of it.

## Podman, Docker, Singularity?

Docker is a popular container runtime. However it has a restrictive license and may require a paid license for use at NIH.

Podman is a drop-in replacement for Docker with a more permissive license. Unlike Docker, Podman *does not* need to run containers as root. Install Podman Desktop to use it.

Singularity is a different way of handling containers. A Singularity container can be built from a Docker/Podman container. Singularity does not need to be run as root. Install Singularity on a Linux system to use it. It is already available on NIH's HPC (see [Biowulf's singularity page](https://hpc.nih.gov/apps/singularity.html)).

## Persistent mounts and config

The host home directory is not mounted. Even though Singularity mounts it by default, we disable with `--no-home`. This restricts the agents' access. 

However, some tools need access to some sort of home directory inside the container. It is helpful to have that live in some separate place on the host. In this repo, the home directory of the container user (`devuser`) points to this location on the host: `~/.local/share/llm-devcontainer/home`. 

That gives the container a stable, persistent home across runs without exposing the full host home directory.

In addition, these host paths are mounted into the container as needed:

- `~/.codex` for Codex config and auth
- `~/.claude` for Claude Code config and state
- `~/.claude.json` for Claude UI settings and stats
- `~/.aws` for AWS SSO credentials used by Claude Code via Bedrock

These are handled and configured by the [`launch.py`](../launch.py) container launcher script.

## Login model

This section describes the details of how login works to help explain why we need the [`refresh.py`](../refresh.py) script.

Using Codex as an example, `codex login` opens a web browser. Codex remains open, constantly listening on a particular port on localhost (port 1455). Once you log in, the browser redirects to localhost:1455, Codex sees the successful auth, and registers the login.

This does not work well inside a container: the container doesn't have a GUI and so it can't open a browser. If you paste the link into a browser, that browser is running on the host, not the container. So when the browser redirects to localhost:1455, Codex is still running inside the container listening...but the intentionally-isolated container can't see localhost:1455. So that redirect never makes it *inside* the container where Codex can see it, and it waits indefinitely.

It's a similar situation on a remote system: Codex is listening on the remote's localhost:1455 but you're logging into a website in your local machine's browser. The redirect goes to your local machine, not to Biowulf.

There are ways of port forwarding and tunneling that can work around this. But copying the file is straightforward and `refresh.py` makes it easy.

This is also one of the methods suggested by the Codex docs (see [Fallback: Authenticate locally and copy your auth cache](https://developers.openai.com/codex/auth#fallback-authenticate-locally-and-copy-your-auth-cache)).
