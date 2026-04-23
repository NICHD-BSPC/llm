# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=1000
ARG DEBIAN_FRONTEND=noninteractive

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
RUN ARCH="$(dpkg --print-architecture)" && \
  case "${ARCH}" in \
    amd64) \
      echo 'AWS_ARCH=x86_64' >> /etc/arch.env && \
      echo 'CLAUDE_PLATFORM=linux-x64' >> /etc/arch.env && \
      echo 'CODEX_ASSET=codex-x86_64-unknown-linux-musl.tar.gz' >> /etc/arch.env && \
      echo 'CODEX_BINARY=codex-x86_64-unknown-linux-musl' >> /etc/arch.env ;; \
    arm64) \
      echo 'AWS_ARCH=aarch64' >> /etc/arch.env && \
      echo 'CLAUDE_PLATFORM=linux-arm64' >> /etc/arch.env && \
      echo 'CODEX_ASSET=codex-aarch64-unknown-linux-musl.tar.gz' >> /etc/arch.env && \
      echo 'CODEX_BINARY=codex-aarch64-unknown-linux-musl' >> /etc/arch.env ;; \
    *) echo "Unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
  esac

# Install AWS CLI v2
RUN --mount=type=secret,id=mitm_ca_bundle,required=false,target=/run/secrets/mitm_ca_bundle.pem \
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" && \
  if [ -f /run/secrets/mitm_ca_bundle.pem ]; then CURL_CA_BUNDLE=/run/secrets/mitm_ca_bundle.pem; fi && \
  export CURL_CA_BUNDLE && \
  . /etc/arch.env && \
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o /tmp/awscliv2.zip && \
  cd /tmp && unzip -q awscliv2.zip && \
  ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update && \
  rm -rf /tmp/aws /tmp/awscliv2.zip

# Install Claude CLI, using the download base URL parsed from the install script
RUN --mount=type=secret,id=mitm_ca_bundle,required=false,target=/run/secrets/mitm_ca_bundle.pem \
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" && \
  if [ -f /run/secrets/mitm_ca_bundle.pem ]; then CURL_CA_BUNDLE=/run/secrets/mitm_ca_bundle.pem; fi && \
  export CURL_CA_BUNDLE && \
  . /etc/arch.env && \
  INSTALL_SCRIPT="$(curl -fsSL https://claude.ai/install.sh)" && \
  DOWNLOAD_BASE_URL="$(printf '%s' "${INSTALL_SCRIPT}" | grep -o 'DOWNLOAD_BASE_URL=\"[^\"]*\"' | head -1 | cut -d'"' -f2)" && \
  test -n "${DOWNLOAD_BASE_URL}" && \
  CLAUDE_VERSION="$(curl -fsSL "${DOWNLOAD_BASE_URL}/latest")" && \
  CLAUDE_CHECKSUM="$(curl -fsSL "${DOWNLOAD_BASE_URL}/${CLAUDE_VERSION}/manifest.json" | jq -r --arg platform "${CLAUDE_PLATFORM}" '.platforms[$platform].checksum // empty')" && \
  test -n "${CLAUDE_CHECKSUM}" && \
  curl -fsSL "${DOWNLOAD_BASE_URL}/${CLAUDE_VERSION}/${CLAUDE_PLATFORM}/claude" -o /tmp/claude && \
  printf '%s  %s\n' "${CLAUDE_CHECKSUM}" /tmp/claude | sha256sum -c - && \
  install -m 0755 /tmp/claude /usr/local/bin/claude && \
  rm -f /tmp/claude

# Install Codex from the published GitHub release tarball.
RUN --mount=type=secret,id=mitm_ca_bundle,required=false,target=/run/secrets/mitm_ca_bundle.pem \
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" && \
  if [ -f /run/secrets/mitm_ca_bundle.pem ]; then CURL_CA_BUNDLE=/run/secrets/mitm_ca_bundle.pem; fi && \
  export CURL_CA_BUNDLE && \
  . /etc/arch.env && \
  CODEX_TAG="$(curl -fsSL https://api.github.com/repos/openai/codex/releases/latest | jq -r '.tag_name')" && \
  CODEX_VERSION="${CODEX_TAG#rust-v}" && \
  test -n "${CODEX_VERSION}" && \
  curl -fsSL "https://github.com/openai/codex/releases/download/${CODEX_TAG}/${CODEX_ASSET}" -o /tmp/codex.tar.gz && \
  tar -xzf /tmp/codex.tar.gz -C /tmp && \
  install -m 0755 "/tmp/${CODEX_BINARY}" /usr/local/bin/codex && \
  rm -rf /tmp/codex.tar.gz "/tmp/${CODEX_BINARY}"

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
    PATH="$PATH:/home/${USERNAME}/.local/bin"

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
