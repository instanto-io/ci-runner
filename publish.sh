#!/usr/bin/env bash
# Builds the runner image and publishes it to the registry named by CI_RUNNER_REGISTRY.
#
# Run it on a machine of the architecture you are publishing: the image carries
# browsers and a JDK, so building under emulation is slow. An arm64 host
# publishes arm64; an x86-64 host publishes amd64.
set -euo pipefail

# BuildKit is the default in a terminal but not in every service environment, and
# the Dockerfile uses COPY --chmod, which needs it.
export DOCKER_BUILDKIT=1

registry=${CI_RUNNER_REGISTRY:?set CI_RUNNER_REGISTRY to the registry host:port}
repository=${CI_RUNNER_REPOSITORY:-instanto-docker/ci-runner}
arch=$(docker version --format '{{.Server.Arch}}')
image="${registry}/${repository}"

echo "Building ${image}:${arch} on $(uname -m)"
# TARGETARCH is passed explicitly: the legacy builder does not set it, and the
# Dockerfile uses it to select architecture-specific packages.
docker build --platform "linux/${arch}" --build-arg "TARGETARCH=${arch}" -t "${image}:${arch}" .

echo "Checking the toolchain before publishing"
docker run --rm --shm-size=2g "${image}:${arch}" verify

echo "Publishing"
docker push "${image}:${arch}"

# One tag per architecture, joined under latest so consumers pull by name alone.
# buildx pushes each tag as an index (the image and its provenance), which
# docker manifest cannot join, so buildx joins them. A failed join is reported
# with its reason, and the per-architecture tag stands on its own.
tags=("${image}:${arch}")
for other in amd64 arm64; do
  [ "$other" = "$arch" ] && continue
  if docker buildx imagetools inspect "${image}:${other}" >/dev/null 2>&1; then
    tags+=("${image}:${other}")
  fi
done
if docker buildx imagetools create --tag "${image}:latest" "${tags[@]}"; then
  echo "Published ${image}:latest for: ${tags[*]##*:}"
else
  echo "Published ${image}:${arch}. Joining the architectures under latest failed; see above."
fi
