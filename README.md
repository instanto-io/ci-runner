# ci-runner

Self-hosted GitHub Actions runners for the instanto-io organisation, packaged as a
container image. A machine needs nothing but Docker (or OrbStack on a Mac) to take
jobs: every tool the organisation's builds use is already in the image.

## What it offers

**One image with the whole toolchain.** Jobs run as an unprivileged user without
sudo, so a build cannot change the machine it runs on.

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

`docker compose run --rm runner-1 verify` checks the toolchain on a machine before
it registers.

**Clean runners by default.** A container registers, runs one job, exits and is
restarted fresh, so nothing leaks from one job into the next. Each runner keeps its
own Maven repository, so builds stay fast without sharing state between concurrent
jobs. Jobs target these runners with `runs-on: [self-hosted, instanto-container]`.

**A long-lived runner where that suits better.** `compose.persistent.yaml` runs a
single runner that registers once and keeps its registration and Maven cache
between jobs. The *Provision container runner* workflow installs or updates one on a
chosen machine.

**Package traffic stays local.** Projects always name the organisation's package
registry by its public address. On each machine a small scheduled job points that
address at a local route instead, checks the certificate, and refreshes the runner
when the route changes, waiting for any running job to finish first. Private
addresses are kept in untracked configuration, never in git or in project builds.

**Runners for a personal account's repositories.** GitHub will not let an
organisation's runners serve repositories owned by a personal account.
`controller.py` watches that account's repositories and, when a job queues, starts a
one-job runner for it, on this machine or on another in turn. The management
credential never leaves the host; a job container receives only a short-lived
registration token for one repository. Fork pull requests are never run this way.
`python3 controller.py --dry-run --once` shows what it would start, and
`python3 install-controller.py` installs it as a macOS login service.

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

## Workflows

- **image** builds the image natively for each architecture on machines labelled
  `image-builder`, and publishes it to the organisation's private container registry
  under a single multi-architecture tag. The registry's address is the
  `CI_RUNNER_REGISTRY` repository variable. `./publish.sh` does the same by hand,
  with `CI_RUNNER_REGISTRY` set in the environment.
- **provision** installs or updates a long-lived runner on a chosen machine.
- **probe** reports what each machine offers and checks it can reach the package
  registry, so gaps show up before a build lands there.
