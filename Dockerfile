# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=1000
ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_VERSION=22.22.2
ARG CLAUDE_VERSION=
ARG CODEX_VERSION=
ARG PI_VERSION=
ARG REPOSITORY_URL=https://github.com/nichd-bspc/llm
ARG TARGETARCH
ARG TARGETPLATFORM

LABEL org.opencontainers.image.source="${REPOSITORY_URL}" \
      org.opencontainers.image.description="LLM agent container with Claude Code, Codex, and Pi"

# The following --mount... construct lets us pass in temporary secrets (here,
# enterprise certs) at build time without letting them leak into the built
# container
RUN --mount=type=secret,id=mitm_ca_bundle,required=false,target=/run/secrets/mitm_ca_bundle.pem \
    APT_HTTPS_OPTS="$(if [ -f /run/secrets/mitm_ca_bundle.pem ]; then printf '%s' '-o Acquire::https::CaInfo=/run/secrets/mitm_ca_bundle.pem'; fi)" && \
    apt-get ${APT_HTTPS_OPTS} update && \
    apt-get ${APT_HTTPS_OPTS} install -y --no-install-recommends \
      bash \
      bubblewrap \
      ca-certificates \
      curl \
      fzf \
      git \
      jq \
      less \
      locales \
      man-db \
      procps \
      python3 \
      ripgrep \
      sudo \
      unzip \
      vim \
      xz-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN sed -i 's/^# *en_US.UTF-8 UTF-8$/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Add defined user with defined uid/gid
RUN groupadd -o --gid "${USER_GID}" "${USERNAME}" && \
    useradd -o --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}" && \
    mkdir -p /etc/sudoers.d && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}" && \
    chmod 0440 "/etc/sudoers.d/${USERNAME}"

# Detect architecture once and store mappings for later RUN commands
RUN case "${TARGETARCH}" in \
    amd64) \
      echo 'AWS_ARCH=x86_64' >> /etc/arch.env && \
      echo 'CLAUDE_PLATFORM=linux-x64' >> /etc/arch.env && \
      echo 'CODEX_ASSET=codex-x86_64-unknown-linux-musl.tar.gz' >> /etc/arch.env && \
      echo 'CODEX_BINARY=codex-x86_64-unknown-linux-musl' >> /etc/arch.env && \
      echo 'NODE_ARCH=x64' >> /etc/arch.env ;; \
    arm64) \
      echo 'AWS_ARCH=aarch64' >> /etc/arch.env && \
      echo 'CLAUDE_PLATFORM=linux-arm64' >> /etc/arch.env && \
      echo 'CODEX_ASSET=codex-aarch64-unknown-linux-musl.tar.gz' >> /etc/arch.env && \
      echo 'CODEX_BINARY=codex-aarch64-unknown-linux-musl' >> /etc/arch.env && \
      echo 'NODE_ARCH=arm64' >> /etc/arch.env ;; \
    *) echo "Unsupported architecture: ${TARGETPLATFORM}/${TARGETARCH}" >&2; exit 1 ;; \
  esac

# Various env vars
ENV DEVCONTAINER=true \
    HOME=/home/${USERNAME} \
    SHELL=/bin/bash \
    EDITOR=vim \
    VISUAL=vim \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    TERM=xterm-256color \
    COLORTERM=truecolor \
    # Claude Code complains if this is not in the PATH \
    PATH="$PATH:/home/${USERNAME}/.local/bin"

RUN --mount=type=secret,id=mitm_ca_bundle,required=false,target=/run/secrets/mitm_ca_bundle.pem \
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" && \
  if [ -f /run/secrets/mitm_ca_bundle.pem ]; then CURL_CA_BUNDLE=/run/secrets/mitm_ca_bundle.pem; fi && \
  export CURL_CA_BUNDLE && \
  . /etc/arch.env && \
  \
  # Install Node.js from the official upstream tarball. \
  NODE_DISTRO="node-v${NODE_VERSION}-linux-${NODE_ARCH}" && \
  NODE_TARBALL="${NODE_DISTRO}.tar.xz" && \
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" -o /tmp/SHASUMS256.txt && \
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}" -o /tmp/node.tar.xz && \
  EXPECTED_SHA256="$(awk -v tarball="${NODE_TARBALL}" '$2 == tarball { print $1 }' /tmp/SHASUMS256.txt)" && \
  test -n "${EXPECTED_SHA256}" && \
  echo "${EXPECTED_SHA256}  /tmp/node.tar.xz" | sha256sum -c - && \
  tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner && \
  rm -f /tmp/SHASUMS256.txt /tmp/node.tar.xz && \
  \
  # Install AWS CLI v2. \
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o /tmp/awscliv2.zip && \
  cd /tmp && unzip -q awscliv2.zip && \
  ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update && \
  rm -rf /tmp/aws /tmp/awscliv2.zip && \
  \
  # Claude Code installation method from official docs \
  install -d -m 0755 /etc/apt/keyrings && \
  curl -fsSL https://downloads.claude.ai/keys/claude-code.asc \
    -o /etc/apt/keyrings/claude-code.asc && \
  echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" \
    | tee /etc/apt/sources.list.d/claude-code.list && \
  apt update && apt install claude-code && \
  \
  # Codex installation from official docs \
  npm i -g @openai/codex && \
  \
  # Pi installation from official docs \
  npm install -g @mariozechner/pi-coding-agent


RUN mkdir -p \
      /workspace \
      /home/${USERNAME} && \
    chown -R ${USER_UID}:${USER_GID} \
      /workspace \
      /home/${USERNAME}

# Models often reach for python, but on ubuntu 24.04 only python3 is available. So symlink it.
RUN ln -s /usr/bin/python3 /usr/bin/python

USER ${USERNAME}
WORKDIR /workspace
CMD ["/bin/bash"]
