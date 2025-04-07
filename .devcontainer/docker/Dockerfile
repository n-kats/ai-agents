FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  ca-certificates \
  sudo \
  git \
  bash \
  bash-completion \
  libnss3 \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libx11-xcb1 \
  libgtk-3-0 \
  libgbm1 \
  libxshmfence1 \
  libdrm2 \
  shellcheck \
  tig \
  nodejs \
  npm \
  vim \
  language-pack-ja \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV LANG=ja_JP.UTF-8
ENV LANGUAGE=ja_JP:ja

RUN echo "ubuntu:ubuntu" | chpasswd && \
  usermod -aG sudo ubuntu && \
  echo "ubuntu ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
USER ubuntu
RUN curl -LsSf https://astral.sh/uv/install.sh | bash
ENV PATH="/home/ubuntu/.local/bin:${PATH}"
RUN uv python install 3.12.0
WORKDIR /workspace
ENV UV_LINK_MODE=copy
RUN echo 'eval "$(uv generate-shell-completion bash)"' >> /home/ubuntu/.bashrc
