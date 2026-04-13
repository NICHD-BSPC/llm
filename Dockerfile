FROM ubuntu:24.04

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=1000
ARG DEBIAN_FRONTEND=noninteractive

# Chicken-or-egg problem: on an enterprise network with TLS interception, we
# need to install certs...but that needs ca-certificates package, which can't
# be installed without certs. So we first install ca-certificates *without*
# TLS, then install the certs, then install everything with the new certs as
# usual.

COPY certs.pem /tmp/certs.pem

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

RUN find /etc/apt -type f \( -name '*.list' -o -name '*.sources' \) \
      -exec sed -i \
        -e 's|http://deb.debian.org|https://deb.debian.org|g' \
        -e 's|http://security.debian.org|https://security.debian.org|g' \
        -e 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' \
        -e 's|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' \
        -e 's|http://ports.ubuntu.com/ubuntu-ports|https://ports.ubuntu.com/ubuntu-ports|g' {} + && \
    apt-get update \
      -o Acquire::https::Verify-Peer=false \
      -o Acquire::https::Verify-Host=false && \
    apt-get install -y --no-install-recommends \
      -o Acquire::https::Verify-Peer=false \
      -o Acquire::https::Verify-Host=false \
      ca-certificates && \
    if [ -s /tmp/certs.pem ]; then \
      mkdir -p /usr/local/share/ca-certificates/enterprise; \
      awk 'BEGIN {c=0} /-----BEGIN CERTIFICATE-----/ {c++} {print > "/usr/local/share/ca-certificates/enterprise/cert-" c ".crt"}' /tmp/certs.pem; \
      update-ca-certificates 2>&1 | grep -v "skipping ca-certificates.crt"; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
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
RUN . /etc/arch.env && \
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o /tmp/awscliv2.zip && \
  cd /tmp && unzip -q awscliv2.zip && \
  ./aws/install --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update && \
  rm -rf /tmp/aws /tmp/awscliv2.zip

# Install Claude CLI, using the GCS bucket parsed from the install script
RUN . /etc/arch.env && \
  INSTALL_SCRIPT="$(curl -fsSL https://claude.ai/install.sh)" && \
  GCS_BUCKET="$(printf '%s' "${INSTALL_SCRIPT}" | grep -o 'GCS_BUCKET="[^"]*"' | head -1 | cut -d'"' -f2)" && \
  CLAUDE_VERSION="$(curl -fsSL "${GCS_BUCKET}/latest")" && \
  curl -fsSL "${GCS_BUCKET}/${CLAUDE_VERSION}/${CLAUDE_PLATFORM}/claude" -o /tmp/claude && \
  install -m 0755 /tmp/claude /usr/local/bin/claude && \
  rm -f /tmp/claude

# Install Codex from the published GitHub release tarball.
RUN . /etc/arch.env && \
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
