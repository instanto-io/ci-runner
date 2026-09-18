#!/usr/bin/env bash
# Registers an ephemeral organisation runner, runs one job, and exits. The
# container's restart policy starts the next one.
set -euo pipefail

case "${1:-run}" in
  run) ;;
  verify) exec setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner /usr/local/bin/verify-toolchain ;;
  *) exec "$@" ;;
esac

: "${GITHUB_ORG:?GITHUB_ORG must name the organisation to register with}"
pat_file="${RUNNER_REGISTRATION_PAT_FILE:-/run/secrets/runner_registration_pat}"
[ -r "$pat_file" ] || { echo "No registration credential at $pat_file" >&2; exit 1; }

# setpriv changes user but not HOME, and browsers write there.
as_runner() { setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner "$@"; }

# Some file sharing implementations (OrbStack's, for one) ignore in-container
# ownership on a bind mount, so the credential's own mode cannot be relied on.
# The directory holding it is container-local, so restrict that instead.
chmod 700 "$(dirname "$pat_file")" 2>/dev/null || true

# A job runs as the runner user. If that user could still read the credential, any
# job could take it, so refuse to start rather than expose it.
if as_runner test -r "$pat_file"; then
  echo "$pat_file is readable by the runner user; restrict it to its owner (chmod 600)." >&2
  exit 1
fi

name="${RUNNER_NAME:-$(hostname)}"
labels="${RUNNER_LABELS:-instanto-container}"
home=/home/runner

# The container is restarted rather than recreated, so clear what the last job left.
as_runner bash -c "cd $home && rm -rf _work/* .runner .credentials .credentials_rsaparams .cache/* /tmp/* 2>/dev/null || true"

token=$(curl -fsS -X POST \
  -H "Authorization: Bearer $(cat "$pat_file")" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/orgs/${GITHUB_ORG}/actions/runners/registration-token" | jq -r .token)
[ -n "$token" ] && [ "$token" != null ] || { echo "Could not obtain a registration token for ${GITHUB_ORG}" >&2; exit 1; }

cd "$home"
as_runner ./config.sh --unattended --ephemeral --replace --disableupdate \
  --url "https://github.com/${GITHUB_ORG}" --token "$token" \
  --name "$name" --labels "$labels" --work _work
unset token

exec setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner ./run.sh
