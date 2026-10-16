#!/usr/bin/env bash
# Runs before and after every job, so no job inherits what another left behind.
#
# - The Maven repository. A job that installs io.instanto snapshots would otherwise
#   leave copies that later jobs use in place of the registry's, until the registry
#   has a newer one. Every job resolves its dependencies afresh: io.instanto
#   artefacts from packages.instanto.io on the LAN, the rest from Maven Central.
# - The job's Docker sidecar (clean-docker.sh).
#
# A runner restarts its container rather than recreating it, and a long-lived
# runner takes many jobs in one container, so this cannot wait for a restart.
set -uo pipefail

rm -rf "${HOME:-/home/runner}/.m2" 2>/dev/null || true
install -d "${HOME:-/home/runner}/.m2" 2>/dev/null || true
echo "Maven repository: cleared"

exec /usr/local/bin/clean-docker.sh
