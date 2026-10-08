# ci-runner

Self-hosted GitHub Actions runners for the instanto-io organisation, packaged as a
container image. A machine needs nothing but Docker (or OrbStack on a Mac) to take
jobs: every tool the organisation's builds use is already in the image.

## What a runner provides

The container includes the Java and browser toolchain used by the
organisation's builds. Jobs run as an unprivileged user.

| In the image | Version |
|---|---|
| GitHub Actions runner | 2.337.0 |
| Temurin JDK | 21 |
| Maven | 3.9.16 |
| Google Chrome, Firefox | stable |
| Playwright browsers (Chromium, Firefox, WebKit) | 1.55.0 |
| Node | 22 |
| clang, gcc (for TeaVM's C backend) | Ubuntu 24.04 |
| Python 3, git, curl | Ubuntu 24.04 |
| Docker client, buildx, compose | stable |

Each runner also has a Docker daemon of its own, in a Docker-in-Docker sidecar
container next to it, so jobs can run Testcontainers tests and build images. A port
that a job's container publishes answers on `localhost`, as it does on a
developer's machine. Before and after every job the runner removes the containers,
networks and volumes the last job left in that daemon; images stay as a cache
until they have gone a week unused. Jobs never reach the host's own daemon. The
sidecar has to be privileged, though, so it keeps jobs away from the host's
containers and credentials by accident, not against a job written to escape.

A container normally registers for one job, exits and restarts clean.
Each runner keeps its own Maven cache. Target these jobs with
`runs-on: [self-hosted, instanto-container]`. Use
`compose.persistent.yaml` when a long-lived runner is needed.

## Run it on a machine

1. Create a **classic** personal access token with the `admin:org` scope. GitHub's
   endpoint for organisation runner registration accepts classic tokens only. Save it
   as `runner-registration.pat` here and `chmod 600` it; the container refuses to start
   if a job could read it.
2. `cp .env.example .env` and set `RUNNER_HOST` to the machine's name.
3. `docker compose up -d --build`.

One runner starts by default, with its Docker sidecar. `docker compose --profile
extra-capacity up -d` adds a second pair on a machine with room for it: allow
roughly 4 GB of memory and 2 CPUs per runner while browser tests run, plus what the
job's own containers need. The sidecar image is `docker:29-dind`; set `DIND_IMAGE`
in `.env` to use another.

To pull a published image instead of building, set `CI_RUNNER_IMAGE` in `.env`.

## Check a runner

`docker compose run --rm runner-1 verify` checks the toolchain before
registration, including that the sidecar's daemon answers and that a published port
is reachable on `localhost`. The [probe workflow](.github/workflows/probe.yml) checks the
capabilities and connectivity of registered machines.
