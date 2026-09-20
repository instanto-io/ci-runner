# Self-hosted GitHub Actions runner for Instanto builds.
#
# One image for amd64 and arm64. It carries every tool the organisation's builds
# call, including a C toolchain for TeaVM's C backend, so a host needs only a
# container engine. Each container is an ephemeral
# runner: it registers, takes one job, exits, and is restarted clean.

ARG RUNNER_VERSION=2.337.0
FROM ghcr.io/actions/actions-runner:${RUNNER_VERSION}

ARG TARGETARCH
ARG MAVEN_VERSION=3.9.16
ARG NODE_VERSION=22.23.2
ARG PLAYWRIGHT_VERSION=1.55.0

USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg jq tar unzip xz-utils python3 \
        fonts-liberation fonts-noto-core fonts-noto-color-emoji \
        clang gcc libc6-dev \
    && install -d -m 0755 /etc/apt/keyrings \
    # Temurin JDK
    && curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public \
        | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb noble main" \
        > /etc/apt/sources.list.d/adoptium.list \
    # Google Chrome. TeaVM starts it by the name google-chrome-stable.
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && echo "deb [arch=${TARGETARCH} signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    # Firefox from Mozilla. Ubuntu's firefox package is a snap wrapper that
    # does not run in a container.
    && curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg \
        -o /etc/apt/keyrings/packages.mozilla.org.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
        > /etc/apt/sources.list.d/mozilla.list \
    && printf 'Package: firefox*\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' > /etc/apt/preferences.d/mozilla \
    && apt-get update \
    # Named explicitly: the JDK would otherwise pull in liboss4-salsa-asound2 for
    # its audio dependency, which conflicts with the libasound2t64 the browsers need.
    && apt-get install -y --no-install-recommends libasound2t64 temurin-21-jdk google-chrome-stable firefox \
    && rm -rf /var/lib/apt/lists/*

# Chrome's own sandbox cannot start inside an unprivileged container; the
# container is the isolation boundary. TeaVM passes no such flag itself.
RUN printf '#!/bin/sh\nexec /usr/bin/google-chrome-stable --no-sandbox "$@"\n' > /usr/local/bin/google-chrome-stable \
    && chmod 0755 /usr/local/bin/google-chrome-stable

RUN curl -fsSLo /tmp/maven.tar.gz \
        "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/${MAVEN_VERSION}/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
    && echo "$(curl -fsSL "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/${MAVEN_VERSION}/apache-maven-${MAVEN_VERSION}-bin.tar.gz.sha512")  /tmp/maven.tar.gz" \
        | sha512sum -c - \
    && install -d /opt/maven \
    && tar -xzf /tmp/maven.tar.gz --strip-components=1 -C /opt/maven \
    && ln -s /opt/maven/bin/mvn /usr/local/bin/mvn \
    && rm /tmp/maven.tar.gz

RUN case "${TARGETARCH}" in amd64) arch=x64 ;; arm64) arch=arm64 ;; *) echo "unsupported: ${TARGETARCH}"; exit 1 ;; esac \
    && curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz" \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" \
        | grep " node-v${NODE_VERSION}-linux-${arch}.tar.xz\$" | sed "s|node-v.*|/tmp/node.tar.xz|" | sha256sum -c - \
    && tar -xJf /tmp/node.tar.xz --strip-components=1 -C /usr/local \
    && rm /tmp/node.tar.xz

# Playwright's browsers and their system libraries, installed once here so builds
# never need sudo. The Java and Node clients of the same version share them.
#
# The clients reinstall the browsers the first time they are used unless told the
# image provides them; left to itself, each test spends minutes failing to write
# a lock file here before giving up. The directory belongs to the runner user so
# that a build needing a different version can still install one.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN npx -y "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium firefox webkit \
    && chmod -R a+rX /ms-playwright \
    && chown -R runner:runner /ms-playwright \
    && rm -rf /var/lib/apt/lists/* /root/.npm

ENV JAVA_HOME=/usr/lib/jvm/temurin-21-jdk-${TARGETARCH} \
    MAVEN_HOME=/opt/maven

# Jobs run as the runner user with no sudo, so a job cannot change the image's
# system state for the next one.
RUN rm -f /etc/sudoers.d/* \
    && echo "Defaults env_keep += \"DEBIAN_FRONTEND\"" > /etc/sudoers \
    && install -d -o runner -g runner /home/runner/.m2 /home/runner/_work

COPY --chmod=0755 entrypoint.sh /usr/local/bin/ci-runner
COPY --chmod=0755 verify-toolchain.sh /usr/local/bin/verify-toolchain

# The entrypoint starts as root only to read the registration credential, then
# runs the runner as the unprivileged runner user.
ENTRYPOINT ["/usr/local/bin/ci-runner"]
CMD ["run"]
