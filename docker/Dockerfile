FROM ubuntu:26.04

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH
ARG VM_UID=1000
ARG VM_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN if [[ "${TARGETARCH}" != "amd64" ]]; then \
      echo "Google Chrome for Linux requires an amd64 image (got ${TARGETARCH})" >&2; \
      exit 1; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      adwaita-icon-theme \
      build-essential \
      ca-certificates \
      curl \
      dbus-x11 \
      fonts-dejavu-core \
      fonts-liberation \
      git \
      jq \
      less \
      locales \
      maim \
      nano \
      novnc \
      openssh-server \
      procps \
      python3 \
      python3-pip \
      socat \
      sudo \
      supervisor \
      tesseract-ocr \
      thunar \
      tigervnc-standalone-server \
      tigervnc-tools \
      unzip \
      vim-tiny \
      websockify \
      wget \
      wmctrl \
      x11-utils \
      xauth \
      xclip \
      xdotool \
      xfce4-panel \
      xfce4-session \
      xfce4-settings \
      xfce4-terminal \
      xfdesktop4 \
      xfwm4 \
      zip \
 && curl -fsSL -o /tmp/google-chrome.deb \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
 && apt-get install -y --no-install-recommends /tmp/google-chrome.deb \
 && rm -f /tmp/google-chrome.deb \
 && locale-gen en_US.UTF-8 \
 && rm -rf /var/lib/apt/lists/*

RUN groupmod --new-name vm ubuntu \
 && groupmod --gid "${VM_GID}" vm \
 && usermod --login vm --uid "${VM_UID}" --gid "${VM_GID}" --home /home/vm --move-home --shell /bin/bash ubuntu \
 && usermod -aG sudo vm \
 && printf 'vm ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/vm \
 && chmod 0440 /etc/sudoers.d/vm \
 && install -d -m 0755 /run/sshd \
 && printf '%s\n' \
      'PasswordAuthentication yes' \
      'PermitRootLogin no' \
      'X11Forwarding no' \
      'AllowTcpForwarding yes' \
      >/etc/ssh/sshd_config.d/desktop-vm.conf

COPY chrome /usr/local/bin/chrome
COPY start-desktop /usr/local/bin/start-desktop
COPY start-chrome /usr/local/bin/start-chrome
COPY desktop-screenshot /usr/local/bin/desktop-screenshot
COPY desktop-ocr /usr/local/bin/desktop-ocr
COPY agent-screenshot /usr/local/bin/agent-screenshot
COPY agent-clear-screenshots /usr/local/bin/agent-clear-screenshots
COPY entrypoint /usr/local/bin/desktop-vm-entrypoint
COPY supervisord.conf /etc/supervisor/conf.d/desktop-vm.conf
COPY desktop-env.sh /etc/profile.d/desktop-env.sh

RUN chmod 0755 \
      /usr/local/bin/chrome \
      /usr/local/bin/start-desktop \
      /usr/local/bin/desktop-screenshot \
      /usr/local/bin/desktop-ocr \
      /usr/local/bin/agent-screenshot \
      /usr/local/bin/agent-clear-screenshots \
      /usr/local/bin/start-chrome \
      /usr/local/bin/desktop-vm-entrypoint \
      /etc/profile.d/desktop-env.sh

ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

EXPOSE 22 5901 6080 9222

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
  CMD curl -fsS http://127.0.0.1:9222/json/version >/dev/null \
   && bash -c '</dev/tcp/127.0.0.1/22' \
   && bash -c '</dev/tcp/127.0.0.1/6080' \
   || exit 1

ENTRYPOINT ["/usr/local/bin/desktop-vm-entrypoint"]
