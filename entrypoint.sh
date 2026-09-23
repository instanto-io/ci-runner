#!/usr/bin/env bash
# Registers an organisation runner. Container-fleet runners are ephemeral and
# restart after each job; individually provisioned hosts can retain only their
# runner state and register once with a short-lived token.
set -euo pipefail

case "${1:-run}" in
  run) ;;
  verify) exec setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner /usr/local/bin/verify-toolchain ;;
  *) exec "$@" ;;
esac

# setpriv changes user but not HOME, and browsers write there.
as_runner() { setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner "$@"; }

name="${RUNNER_NAME:-$(hostname)}"
labels="${RUNNER_LABELS:-instanto-container}"
ephemeral="${RUNNER_EPHEMERAL:-true}"
state_dir="${RUNNER_STATE_DIR:-}"
home=/home/runner

# A persistent runner registers once with a short-lived token. Restore its own
# runner credentials after a container restart without retaining the
# organisation-level PAT that ephemeral runners use.
if [ "$ephemeral" = false ] && [ -n "$state_dir" ] && [ -s "$state_dir/.runner" ]; then
  for file in .runner .credentials .credentials_rsaparams; do
    [ -f "$state_dir/$file" ] && install -o runner -g runner -m 600 "$state_dir/$file" "$home/$file"
  done
  as_runner bash -c "rm -rf '$home/_work/'* '$home/.cache/'* /tmp/* 2>/dev/null || true"
  exec setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner ./run.sh
fi

scope="${GITHUB_REPO:-${GITHUB_ORG:-}}"
: "${scope:?GITHUB_REPO or GITHUB_ORG must name the runner registration scope}"
token_file="${RUNNER_REGISTRATION_TOKEN_FILE:-}"
pat_file="${RUNNER_REGISTRATION_PAT_FILE:-/run/secrets/runner_registration_pat}"
credential_file="${token_file:-$pat_file}"
[ -r "$credential_file" ] || { echo "No registration credential at $credential_file" >&2; exit 1; }

# Some file sharing implementations (OrbStack's, for one) ignore in-container
# ownership on a bind mount, so the credential's own mode cannot be relied on.
# The directory holding it is container-local, so restrict that instead.
chmod 700 "$(dirname "$credential_file")" 2>/dev/null || true

# A job runs as the runner user. If that user could still read the credential, any
# job could take it, so refuse to start rather than expose it.
if as_runner test -r "$credential_file"; then
  echo "$credential_file is readable by the runner user; restrict it to its owner (chmod 600)." >&2
  exit 1
fi

# The container is restarted rather than recreated, so clear what the last job left.
as_runner bash -c "cd $home && rm -rf _work/* .runner .credentials .credentials_rsaparams .cache/* /tmp/* 2>/dev/null || true"

if [ -n "$token_file" ]; then
  token=$(cat "$token_file")
else
  token=$(curl -fsS -X POST \
    -H "Authorization: Bearer $(cat "$pat_file")" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/orgs/${GITHUB_ORG}/actions/runners/registration-token" | jq -r .token)
fi
[ -n "$token" ] && [ "$token" != null ] || { echo "Could not obtain a registration token for ${scope}" >&2; exit 1; }

cd "$home"
config_args=(--unattended --replace --disableupdate)
[ "$ephemeral" = true ] && config_args+=(--ephemeral)
as_runner ./config.sh "${config_args[@]}" \
  --url "https://github.com/${scope}" --token "$token" \
  --name "$name" --labels "$labels" --work _work
unset token

if [ "$ephemeral" = false ] && [ -n "$state_dir" ]; then
  install -d -m 700 "$state_dir"
  for file in .runner .credentials .credentials_rsaparams; do
    [ -f "$home/$file" ] && install -m 600 "$home/$file" "$state_dir/$file"
  done
fi

exec setpriv --reuid=runner --regid=runner --init-groups env HOME=/home/runner ./run.sh
