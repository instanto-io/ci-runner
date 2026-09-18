#!/usr/bin/env bash
# Checks that the image can do what the organisation's builds ask of it,
# including starting each browser headless the way the test runners do.
set -uo pipefail
failures=0
check() {
  local what=$1; shift
  if out=$("$@" 2>&1); then
    printf '  ok    %-26s %s\n' "$what" "$(echo "$out" | head -1)"
  else
    printf '  FAIL  %-26s %s\n' "$what" "$(echo "$out" | tail -1)"
    failures=$((failures + 1))
  fi
}

echo "$(uname -m) as $(id -un)"
check java                 java -version
check mvn                  mvn -v
check node                 node --version
check python3              python3 --version
check git                  git --version
check curl                 curl --version
check clang                clang --version
check gcc                  gcc --version
check google-chrome-stable google-chrome-stable --version
check firefox              firefox --version
check "no sudo"            bash -c '! sudo -n true 2>/dev/null && echo "jobs cannot sudo"'

work=$(mktemp -d)
printf '#include <math.h>\n#include <stdio.h>\nint main(void){printf("%.0f\\n", sqrt(16.0));return 0;}\n' > "$work/c.c"
check "c toolchain"        bash -c "cd '$work' && clang -std=c11 -O0 c.c -o c -lm && ./c"
check "chrome headless"    timeout 60 google-chrome-stable --headless --disable-gpu --dump-dom about:blank
check "firefox headless"   bash -c "mkdir -p '$work/ff' && timeout 60 firefox --headless --profile '$work/ff' --screenshot '$work/ff.png' about:blank >/dev/null 2>&1; test -s '$work/ff.png' && echo 'screenshot written'"
check "playwright browsers" bash -c 'for b in chromium firefox webkit; do ls -d /ms-playwright/${b}-* >/dev/null || exit 1; done; echo "chromium, firefox, webkit in /ms-playwright"'
rm -rf "$work"

[ "$failures" -eq 0 ] && echo "toolchain ok" || { echo "$failures check(s) failed"; exit 1; }
