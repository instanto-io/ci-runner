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

The `cstainton` account's repositories cannot use organisation runners directly.
On Mini2025, `controller.py` polls all repositories owned by that account and
starts one clean, one-job repository runner when a matching job queues. Its
default limit is one active temporary runner. An optional, ignored
`.controller-state/hosts.json` can place that job on other LAN hosts in turn:

```json
{"hosts":[{"name":"worker-a","ssh":"worker-a","image":"instanto-ci-runner:local","registry_host_name":"package-host.example.lan","token_dir":"/home/user/.local/share/instanto-ci-runner/controller-tokens","entrypoint_path":"/home/user/.local/share/instanto-ci-runner/entrypoint.sh","min_available_mb":4000}]}
```

Each remote host needs the runner image and the updated entrypoint at those
private paths. The SSH user needs Docker access. Keep real hostnames and LAN
addresses only in the ignored file. The controller resolves `registry_host_name`
on the target host and checks the package HTTPS endpoint before starting a job.
It copies a short-lived runner registration token into the remote private directory and removes it after the
container exits. `min_available_mb` leaves room for the host's existing
organisation runner when it is working. The controller can raise
`--max-runners` after host capacity is measured.
It uses the machine's existing signed-in GitHub CLI to request a one-hour
registration token. The CLI credential stays on the host; the build container
receives only the repository registration token, with no Docker socket or host
workspace mount. The container is removed after its job. Fork pull-request jobs
are excluded from this LAN pool and should use GitHub-hosted runners.

Run `python3 controller.py --dry-run --once` to see queued candidates. On macOS,
`python3 install-controller.py` installs the controller as a user LaunchAgent.
It needs a valid `gh auth login` for the repository owner, Docker and the local
`instanto-ci-runner:local` image. Its private state and logs live in the ignored
`.controller-state` directory. The local runner uses Docker's `host-gateway`
mapping; remote hosts use their private `registry_host_name` configuration.
It never needs a GitHub Packages token.

Linux organisation runners use `PACKAGES_LAN_HOST` in their private deployment
`.env`. Set the same name as the encrypted `PACKAGES_LAN_HOST` secret used by
the provisioning workflow. `refresh-package-route.py` resolves that name on
the Docker host, verifies TLS for `packages.instanto.io`, and updates the
container's `/etc/hosts` mapping. A user systemd timer checks every two minutes
and waits for an active job to finish before recreating a container whose
mapping is stale. The host must resolve the name and have Docker access; the
container does not need LAN DNS. Run `refresh-package-route.py --check` on a
host to verify its current container route.

For a Linux host runner that builds directly on the host, stage
`refresh-host-package-route.py`, `install-host-package-route.sh`, and the
`instanto-host-package-route` systemd units together in a private directory.
Put the package server's LAN hostname alone in `package-route-host.conf` there;
do not commit that file. Run `python3 refresh-host-package-route.py
--source-check --config package-route-host.conf` to check DNS and HTTPS, then
run `sudo sh install-host-package-route.sh` once. The root systemd timer keeps
the host's `/etc/hosts` mapping current without storing a LAN address in git.

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

Mini2025 starts one organisation runner by default. Use
`docker compose --profile extra-capacity up -d` only when it has room for a
second heavy job.

Check a host's image before registering it: `docker compose run --rm runner-1 verify`.
