#!/usr/bin/env bash
# Clears the runner's Docker-in-Docker daemon before and after each job, so no job
# sees containers, networks or volumes another job left behind. Images stay as a
# download cache, like the Maven repository, until they have gone a week unused.
#
# A runner without a sidecar has no DOCKER_HOST and nothing to clear. A sidecar
# that cannot be reached is reported but does not fail the job: most jobs do not
# use Docker, and those that do fail with Docker's own error.
set -uo pipefail

[ -n "${DOCKER_HOST:-}" ] || exit 0

for _ in $(seq 1 30); do
  docker info >/dev/null 2>&1 && break
  sleep 1
done
if ! docker info >/dev/null 2>&1; then
  echo "warning: the runner's Docker daemon at ${DOCKER_HOST} is not answering" >&2
  exit 0
fi

containers=$(docker ps -aq)
[ -z "$containers" ] || docker rm -f -v $containers >/dev/null
docker network prune -f >/dev/null
docker volume prune -af >/dev/null
docker image prune -af --filter until=168h >/dev/null
docker builder prune -af --filter until=168h >/dev/null 2>&1 || true
echo "Docker: $(docker info --format '{{.ServerVersion}}') at ${DOCKER_HOST}, cleared"
