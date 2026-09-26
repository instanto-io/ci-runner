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

One runner starts by default. `docker compose --profile extra-capacity up -d` adds a
second on a machine with room for it: allow roughly 4 GB of memory and 2 CPUs per
runner while browser tests run.

To pull a published image instead of building, set `CI_RUNNER_IMAGE` in `.env`.

## Check a runner

`docker compose run --rm runner-1 verify` checks the toolchain before
registration. The [probe workflow](.github/workflows/probe.yml) checks the
capabilities and connectivity of registered machines.
