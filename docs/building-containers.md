# Building containers for running agents

> [!IMPORTANT] Contents
> [TOC]


The tools here support the following workflow:

- use `build.py build` to build a podman container for local use
- use `build.py publish` to push the podman container to a remote and build a singularity container on the remote
- use `refresh.py` to update credentials so that the container can use them
- use `launch.py` to launch the container

See [running containers](running-containers.md) for more about `refresh.py` and `launch.py`. This page is about *building the containers in the first place*.

This aims to have a setup that is convenient but also secure. For example:

- Only mounted files are visible inside the container, usually just the current working directory.
- Persistent config mounts let Codex and Claude Code resume prior sessions across fresh containers.
- `refresh.py` authenticates on the local machine and can copy the required auth files to a remote system.
- The image build handles the enterprise TLS interception present at NIH.
- You can mount a project-local environment or conda environment instead of baking a full development environment into the image.

While there is some setup, in the end, once it's setup instead of this:

```bash
codex
```

you run this:

```bash
launch.py codex
```

## Prerequisites

For building the containers:

- [Podman Desktop](https://podman-desktop.io/) installed for local image builds and local `podman` runs. Test with `podman run hello-world`.
- Singularity installed if you want to run on a remote system via `.sif` (this is installed on Biowulf; use `module load singularity`)

For testing the containers, you will also need the prerequisites listed for [Running Containers](running-containers.md), specifically the `launch.py` and `refresh.py` scripts available and AWS SSO set up if using Claude Code.

## Typical workflow

### 1. Build the image

Build once initially, then rebuild whenever you want updated tooling.

```bash
./build.py build
```

If your network uses TLS interception (the enterprise network decrypts and re-encrypts HTTPS traffic for security monitoring), the first build may fail because the container doesn't yet trust the enterprise certificates. If you see lines like the following, starting with `Ign:`, then this is likely the problem:

```text
Ign:30 https://archive.ubuntu.com/ubuntu noble-updates/main amd64 libk5crypto3 amd64 1.20.1-6ubuntu2.6
Ign:31 https://archive.ubuntu.com/ubuntu noble/main amd64 libkeyutils1 amd64 1.6.3-3build1
Ign:32 https://archive.ubuntu.com/ubuntu noble-updates/main amd64 libkrb5-3 amd64 1.20.1-6ubuntu2.6
...
```

This usually happens while on VPN.

To solve this, save a local enterprise PEM CA bundle as `certs.pem` (or use the `--certs-file` argument for a different path), and the image building will pick it up and use it. For the NIH PKI data source, run the following command to save it as `certs.pem` so it will be picked up by the container building (only available behind firewall):

```bash
# for NIH specifically
curl -fSsL -o certs.pem http://nihdpkicrl.nih.gov/certdata/DPKI-2023-Intermediate-rekey-FullChainBase64.crt
```

When running `build.py build`,

- default image name is `llm-devcontainer`. Change with `--image-name`.
- default platform is `linux/amd64`. On ARM64 macOS this runs under emulation,
  which is usually fine because CPU is not the bottleneck. Change with `--arch`.
- by default, cache is used. To force a fresh rebuild, use `--no-cache`.

> [!NOTE] Check
> Test with `refresh.py` to refresh credentials, followed by `launch.py --backend podman codex`. This will start the container, mount the current directory to the same path inside the container, and immediately start codex. Use `!`-prefixed commands (like `! ls ~`) to call out to the shell to ensure no other directories are mounted.

### 2. Push to remote

You can push the built image to a remote that has Singularity, like Biowulf.

To push to NIH HPC, use Helix (not Biowulf). You should make sure that Singularity is on your default path. If you've pushed before, you'll want to use `--force` to update with the new one. Some notes on this:

- Each command is printed out as it runs -- look for the cyan text. If there are any issues during the various steps, you can always paste those commands to troubleshoot midway rather than restart from the beginning. 
- Or use the `--dry-run` argument to list these commands and run them yourself.
- On Helix, the default temporary directory, `/tmp`, is not executable which causes Singularity to complain. So set an override temp dir with enough space using `--tmpdir`.
- Depending on the time of day Helix may be extremely slow making a Singularity image. So you may want to copy the printed singularity build command and run it on an interactive node.

Altogether, the command will look something like the following; `$REMOTE_PATH` is used here as a placeholder. If you are setting this up for a group on Biowulf, `$REMOTE_PATH` should probably be somewhere in a group share:

```bash
./build.py publish \
  --remote-path $REMOTE_PATH \
  --force \
  --tmpdir /data/$USER/tmp \
  helix.nih.gov
```

This will:

- build the image (using cache unless `--no-cache` is provided)
- save as local tarball (default `./img.tar`)
- push the tarball to the remote (default `$REMOTE_PATH/img.tar`; change with `--remote-tar`)
- push the launcher to the remote (default `$REMOTE_PATH/launch.py`; change with `--remote-launcher`)
- build a singularity container on the remote (default `$REMOTE_PATH/llm.sif`; change with `--remote-sif`)


Add `$REMOTE_PATH` to your PATH on the remote so you can call `launch.py` from anywhere.

> [!NOTE] Check
> To test, run `refresh.py --remote helix.nih.gov` to refresh credentials locally and then push to Helix. Then, on Helix or an interactive node, run `launch.py codex`. Check directory mounting similar to the local check above

*Back to [README.md](../README.md)*
