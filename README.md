# ci-runner

Self-hosted GitHub Actions runners for the instanto-io organisation, run as containers.

The image carries every tool the organisation's builds use, so a host needs only a
container engine. Each container is an **ephemeral** runner: it registers, runs one job,
exits and is restarted clean. Jobs run as an unprivileged user without sudo.

| In the image | Version |
|---|---|
| GitHub Actions runner | 2.337.0 |
| Temurin JDK | 21 |
| Maven | 3.9.16 |
| Google Chrome, Firefox (Mozilla build) | stable |
| Playwright browsers and libraries (Chromium, Firefox, WebKit) | 1.55.0 |
| Node | 22 |
| clang, gcc (TeaVM's C backend) | Ubuntu 24.04 |
| Python 3, git, curl | Ubuntu 24.04 |

Published to the local registry as `mini2023.local:3002/instanto-docker/ci-runner`,
by running `./publish.sh` on a machine of the architecture being published. Currently
`arm64` only, built on the Mac; an x86-64 host publishes `amd64` the same way and the
script joins both under `:latest`.
Runners carry the label `instanto-container`; jobs target it with
`runs-on: [self-hosted, instanto-container]`.

## Run on a host

Needs Docker, or OrbStack on a Mac.

1. Create a **classic** personal access token with the **`admin:org`** scope. GitHub's
   endpoint for organisation runner registration tokens supports classic tokens only;
   there is no fine-grained permission for it. Save it as `runner-registration.pat` in
   this directory and `chmod 600` it. The container refuses to start if a job could
   read it.
2. `cp .env.example .env` and set `RUNNER_HOST`.
3. `docker compose up -d --build`, or set `CI_RUNNER_IMAGE` in `.env` to pull the
   published image instead of building:
   `CI_RUNNER_IMAGE=mini2023.local:3002/instanto-docker/ci-runner:latest`. Pulling
   needs `mini2023.local:3002` in the host's `insecure-registries` and a
   `docker login` as `instanto-docker`.

Check a host's image before registering it: `docker compose run --rm runner-1 verify`.
