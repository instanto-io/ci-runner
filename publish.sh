#!/usr/bin/env bash
# Builds the runner image and publishes it to the local registry.
#
# Run it on a machine of the architecture you are publishing: the image carries
# browsers and a JDK, so building under emulation is slow. This Mac publishes
# arm64; an x86-64 host publishes amd64.
set -euo pipefail

# BuildKit is the default in a terminal but not in every service environment, and
# the Dockerfile uses COPY --chmod, which needs it.
export DOCKER_BUILDKIT=1

registry=${CI_RUNNER_REGISTRY:-mini2023.local:3002}
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

# One tag per architecture, joined into a list so consumers pull by name alone.
# docker manifest speaks HTTPS to the registry regardless of --insecure for some
# operations, so the join is attempted and the per-architecture tag stands on its
# own if it does not succeed.
tags=("${image}:${arch}")
for other in amd64 arm64; do
  [ "$other" = "$arch" ] && continue
  if docker manifest inspect --insecure "${image}:${other}" >/dev/null 2>&1; then
    tags+=("${image}:${other}")
  fi
done
docker manifest rm "${image}:latest" >/dev/null 2>&1 || true
if docker manifest create --insecure "${image}:latest" "${tags[@]}" >/dev/null 2>&1 \
   && docker manifest push --insecure "${image}:latest" >/dev/null 2>&1; then
  echo "Published ${image}:latest for: ${tags[*]##*:}"
else
  echo "Published ${image}:${arch}. The latest tag was left alone: joining the"
  echo "architectures needs a registry reachable over HTTPS from this host."
fi
