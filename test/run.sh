#!/usr/bin/env bash
#
# Tests for the composite actions in this repository.
#
# The action's logic lives in a plain Python script, so it can be driven
# directly: run it against throwaway git repositories with environment
# variables standing in for the action inputs. Outputs are read from
# $GITHUB_OUTPUT exactly as the runner would.
#
#   ./test/run.sh              # all actions
#   ./test/run.sh resolve-release
#
# Exits non-zero if any case fails.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

pass=0
fail=0
current=""

green() { printf '\033[32m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }

ok()   { pass=$((pass + 1)); printf '  %s %s\n' "$(green 'ok  ')" "$1"; }
bad()  {
  fail=$((fail + 1))
  printf '  %s %s\n' "$(red 'FAIL')" "$1"
  shift
  while [ $# -gt 0 ]; do printf '         %s\n' "$1"; shift; done
}

# fixture <manifest-version> [tag]
# Builds $WORK: a git repo on `main` with a tag, plus a bare `origin` so the
# push paths can be exercised for real.
setup() {
  local manifest_ver="$1" want_tag="${2:-}" bin
  WORK="$(mktemp -d)"
  bin="$WORK/bin"; mkdir -p "$bin"

  # A `just` stand-in: the real recipe rewrites version files, and the action
  # requires the bump to change something.
  cat >"$bin/just" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "bump" ] || { echo "stub just: unsupported" >&2; exit 1; }
sed -i -E "s/^version = \".*\"/version = \"$2\"/" Cargo.toml
STUB
  chmod +x "$bin/just"

  git init -q --bare "$WORK/origin.git"
  git init -q "$WORK/repo"
  (
    cd "$WORK/repo"
    git config user.email t@t; git config user.name t
    git remote add origin "$WORK/origin.git"
    printf 'name = "x"\nversion = "%s"\n' "$manifest_ver" >Cargo.toml
    git add -A; git commit -qm init
    git branch -M main
    git push -q -u origin main
    [ -n "$want_tag" ] && git tag -a "$want_tag" -m r && git push -q origin "refs/tags/$want_tag"
  ) >/dev/null 2>&1

  PATH="$bin:$PATH"
  export PATH
}

teardown() { rm -rf "$WORK"; }

# run <name> <expect-exit: ok|fail> <expect-skip> <expect-publish> [env…]
# Followed by optional `expect_remote_tag <vX.Y.Z>` to assert a tag landed.
expect_remote_tag=""
run() {
  local name="$1" xstat="$2" xskip="$3" xpub="$4"; shift 4
  local out st skip pub head=""
  setup "${MV:-1.2.3}" "${TAG:-v1.2.3}"
  export GITHUB_OUTPUT="$WORK/out"

  out="$(cd "$WORK/repo" && env "$@" python3 "$SCRIPT" 2>&1)"; st=$?

  skip=0; pub=0
  [ -f "$GITHUB_OUTPUT" ] && {
    skip="$(grep -c '^skip=true$' "$GITHUB_OUTPUT")" || skip=0
    pub="$(grep -c '^publish=true$' "$GITHUB_OUTPUT")" || pub=0
  }

  local good=1 why=""
  case "$xstat" in
    ok)   { [ "$st" -eq 0 ] || { good=0; why="exit=$st want=0"; }; } ;;
    fail) { [ "$st" -ne 0 ] || { good=0; why="exit=0 want=non-zero"; }; } ;;
  esac
  [ "$skip" = "$xskip" ] || { good=0; why="$why skip=$skip want=$xskip"; }
  [ "$pub"  = "$xpub"  ] || { good=0; why="$why publish=$pub want=$xpub"; }

  if [ -n "$expect_remote_tag" ]; then
    head="$(git -C "$WORK/origin.git" tag -l "$expect_remote_tag")"
    [ -n "$head" ] || { good=0; why="$why tag $expect_remote_tag not pushed"; }
  fi

  if [ "$good" -eq 1 ]; then ok "$name"
  else bad "$name" "$why" "$(printf '%s' "$out" | tail -2 | sed 's/^/          /')"; fi
  teardown
}

# ---------------------------------------------------------------------------

test_resolve_release() {
  local A=resolve-release/action.yml
  local PY=resolve-release/resolve-release.py
  [ -f "$A" ] || { echo "missing $A" >&2; exit 2; }
  [ -f "$PY" ] || { echo "missing $PY" >&2; exit 2; }

  # actionlint cannot lint an action.yml on its own (it parses one as a
  # workflow), so these two checks are what the action metadata gets.
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$PY" \
    || { echo "$PY does not parse" >&2; exit 2; }
  grep -q 'resolve-release.py' "$A" \
    || { echo "$A does not invoke $PY" >&2; exit 2; }
  SCRIPT="$PWD/$PY"   # absolute: cases run with cwd inside a throwaway repo

  echo "resolve-release"
  local BASE=(INPUT_REF= DRY_RUN=false GATE_SHA= MANIFEST_PATH=Cargo.toml
              BUMP_COMMAND="just bump" BUMP= CURRENT=v1.2.3 NEXT= NEXT_STRICT=)

  # Nothing releasable. NEXT is empty when semver-action returns before
  # setting `bump`, so it — not BUMP — is the reliable "nothing to ship" signal.
  run "no new commits -> skip"        ok 1 0 "${BASE[@]}"
  run "bump=none -> skip"             ok 1 0 "${BASE[@]}" BUMP=none
  expect_remote_tag=""; run "bump=none leaves no tag" ok 1 0 "${BASE[@]}" BUMP=none

  # A dry run must never mutate, on any path.
  run "dry-run ship -> skip"          ok 1 0 DRY_RUN=true BUMP=patch CURRENT=v1.2.3 NEXT=v1.2.4 NEXT_STRICT=1.2.4 \
                                       INPUT_REF= GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump"
  run "dry-run sha -> skip"           ok 1 0 INPUT_REF=abc1234 DRY_RUN=true BUMP= CURRENT=v1.2.3 NEXT= NEXT_STRICT= \
                                       GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump"
  run "dry-run tag -> skip"           ok 1 0 INPUT_REF=v1.2.3 DRY_RUN=true BUMP= CURRENT=v1.2.3 NEXT= NEXT_STRICT= \
                                       GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump"

  # A malformed ref is rejected before anything mutates, dry-run included.
  # Spelled out rather than spliced from BASE: `env` applies assignments left
  # to right, so re-listing INPUT_REF= would silently win over the value above.
  run "malformed ref -> fail"         fail 0 0 INPUT_REF=v1.2 DRY_RUN=false GATE_SHA= MANIFEST_PATH= \
                                       BUMP_COMMAND= BUMP= CURRENT= NEXT= NEXT_STRICT=
  run "bad ref on dry-run -> fail"    fail 0 0 INPUT_REF="main" DRY_RUN=true GATE_SHA= MANIFEST_PATH=Cargo.toml \
                                       BUMP_COMMAND="just bump" BUMP= CURRENT= NEXT= NEXT_STRICT=

  # Commit test-builds never publish.
  run "sha -> no publish"             ok 0 0 INPUT_REF=abc1234 DRY_RUN=false GATE_SHA= MANIFEST_PATH= \
                                       BUMP_COMMAND= BUMP= CURRENT= NEXT= NEXT_STRICT=

  # Tag rebuild.
  run "tag rebuild -> publish"        ok 0 1 INPUT_REF=v1.2.3 DRY_RUN=false GATE_SHA= MANIFEST_PATH= \
                                       BUMP_COMMAND= BUMP= CURRENT= NEXT= NEXT_STRICT=
  run "missing tag -> fail"           fail 0 0 INPUT_REF=v9.9.9 DRY_RUN=false GATE_SHA= MANIFEST_PATH= \
                                       BUMP_COMMAND= BUMP= CURRENT= NEXT= NEXT_STRICT=

  # Nothing ungated may ship.
  run "gate sha mismatch -> fail"     fail 0 0 GATE_SHA=deadbeef MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump" \
                                       BUMP=patch CURRENT=v1.2.3 NEXT=v1.2.4 NEXT_STRICT=1.2.4 INPUT_REF= DRY_RUN=false

  # Never republish or go backwards.
  run "next == latest -> fail"        fail 0 0 GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump" \
                                       BUMP=patch CURRENT=v1.2.3 NEXT=v1.2.3 NEXT_STRICT=1.2.3 INPUT_REF= DRY_RUN=false
  run "next < latest -> fail"         fail 0 0 GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump" \
                                       BUMP=patch CURRENT=v1.2.3 NEXT=v1.0.0 NEXT_STRICT=1.0.0 INPUT_REF= DRY_RUN=false

  # The happy path: bump, commit, tag, push — with a real remote to push to.
  expect_remote_tag="v1.2.4"
  run "ship -> bump, tag, push"       ok 0 1 GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump" \
                                       BUMP=patch CURRENT=v1.2.3 NEXT=v1.2.4 NEXT_STRICT=1.2.4 INPUT_REF= DRY_RUN=false

  # Manifest-less projects tag HEAD and commit nothing.
  expect_remote_tag="v1.2.4"
  run "manifest-less -> tag only"     ok 0 1 GATE_SHA= MANIFEST_PATH= BUMP_COMMAND= \
                                       BUMP=patch CURRENT=v1.2.3 NEXT=v1.2.4 NEXT_STRICT=1.2.4 INPUT_REF= DRY_RUN=false

  # A stranded bump commit gets its tag rather than being skipped.
  expect_remote_tag="v9.9.9"
  MV=9.9.9 run "manifest ahead -> tag stranded commit" ok 0 1 GATE_SHA= MANIFEST_PATH=Cargo.toml \
                                       BUMP_COMMAND="just bump" BUMP= CURRENT=v1.2.3 NEXT= NEXT_STRICT= \
                                       INPUT_REF= DRY_RUN=false

  # A manifest that is not ahead must not trigger recovery.
  expect_remote_tag=""
  run "manifest level -> no recovery" ok 1 0 GATE_SHA= MANIFEST_PATH=Cargo.toml BUMP_COMMAND="just bump" \
                                       BUMP= CURRENT=v1.2.3 NEXT= NEXT_STRICT= INPUT_REF= DRY_RUN=false
}

# ---------------------------------------------------------------------------

# Describe a zip: one "<octal mode> <member>" line per entry.
# Python rather than `unzip -Z`, which is not part of the toolset these tests
# are allowed to rely on.
zip_entries() {
  python3 - "$1" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    for i in z.infolist():
        print(f"{(i.external_attr >> 16) & 0o7777:04o} {i.filename}")
PY
}

# Package a fixture in a throwaway directory and describe what came out.
#
# pkg <source> [env…] sets:
#   PKG_ARCHIVE  archive file name, or empty when nothing was produced
#   PKG_STEM     the name-version-target stem
#   PKG_ENTRIES  archive members, one per line
#   PKG_MODE     mode of app.sh inside the archive, or "none"
#   PKG_STAGED   files left behind in the output directory, one per line
pkg() {
  local source="$1"; shift
  PKG_WORK="$(mktemp -d)"
  mkdir -p "$PKG_WORK/out"
  (
    cd "$PKG_WORK" || exit 2
    # Fixture: an executable, a plain file, and a directory with one of each.
    printf '#!/bin/sh\necho hi\n' >app.sh && chmod +x app.sh
    printf 'licence\n' >LICENSE
    mkdir -p extra && printf 'x\n' >extra/nested.txt

    GITHUB_OUTPUT="$PKG_WORK/out.outputs" \
    env SOURCE="$source" OUTDIR=out \
        NAME="${NAME-rsrpc}" VERSION="${VERSION-0.29.0}" \
        TARGET="${TARGET-x86_64-unknown-linux-gnu}" \
        FORMAT="${FORMAT-zip}" LAYOUT="${LAYOUT-dir}" RUNNER_OS="${RUNNER_OS-Linux}" \
        "$@" python3 "$SCRIPT" >"$PKG_WORK/out.log" 2>&1
  )
  local st=$?

  PKG_ARCHIVE=""; PKG_STEM=""; PKG_ENTRIES=""; PKG_MODE="none"; PKG_STAGED=""
  if [ "$st" -eq 0 ] && [ -f "$PKG_WORK/out.outputs" ]; then
    PKG_ARCHIVE="$(grep -m1 '^archive=' "$PKG_WORK/out.outputs" | cut -d= -f2-)"
    PKG_STEM="$(grep -m1 '^stem=' "$PKG_WORK/out.outputs" | cut -d= -f2-)"
    if [ -f "$PKG_WORK/out/$PKG_ARCHIVE" ]; then
      local listing; listing="$(zip_entries "$PKG_WORK/out/$PKG_ARCHIVE" 2>/dev/null)"
      PKG_ENTRIES="$(printf '%s\n' "$listing" | cut -d' ' -f2-)"
      PKG_MODE="$(printf '%s\n' "$listing" | awk '$2 ~ /app\.sh$/ { print $1; exit }')"
    fi
    PKG_STAGED="$(cd "$PKG_WORK/out" && ls -A | grep -vx "$PKG_ARCHIVE" || true)"
  fi
  PKG_LOG="$(tail -3 "$PKG_WORK/out.log" 2>/dev/null)"
  return $st
}

assert_eq() { # <what> <got> <want>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "got:  $2" "want: $3"; fi
}

assert_contains() { # <what> <haystack> <needle>
  case "$2" in
    *"$3"*) ok "$1" ;;
    *) bad "$1" "missing: $3" "in: $(printf '%s' "$2" | tr '\n' ' ')" ;;
  esac
}

assert_lacks() { # <what> <haystack> <needle>
  case "$2" in
    *"$3"*) bad "$1" "unexpectedly present: $3" ;;
    *) ok "$1" ;;
  esac
}

test_package_artifact() {
  local A=package-artifact/action.yml
  local PY=package-artifact/package-artifact.py
  [ -f "$A" ] || { echo "missing $A" >&2; exit 2; }
  [ -f "$PY" ] || { echo "missing $PY" >&2; exit 2; }

  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$PY" \
    || { echo "$PY does not parse" >&2; exit 2; }
  grep -q 'package-artifact.py' "$A" \
    || { echo "$A does not invoke $PY" >&2; exit 2; }
  SCRIPT="$PWD/$PY"

  echo "package-artifact"

  # The name is the whole point: <name>-<version>-<target>, version stamped so
  # a consumer can match it, which is what the Homebrew tap bot requires.
  pkg "app.sh" || true
  assert_eq "name is <name>-<version>-<target>.zip" \
    "$PKG_ARCHIVE" "rsrpc-0.29.0-x86_64-unknown-linux-gnu.zip"
  assert_eq "stem output matches" "$PKG_STEM" "rsrpc-0.29.0-x86_64-unknown-linux-gnu"

  # A leading v must not leak into the archive name.
  VERSION=v0.29.0 pkg "app.sh" || true
  assert_eq "leading v is dropped" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.zip"

  # Default layout keeps everything under one top-level directory.
  assert_contains "layout=dir wraps in a directory" "$PKG_ENTRIES" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu/app.sh"

  # Extraction must not scatter files, and the staging copy must not survive.
  assert_eq "staging dir is cleaned up" "$PKG_STAGED" ""

  # upload-artifact strips the executable bit, so it has to live in the archive.
  assert_eq "executable bit is recorded in zip" "$PKG_MODE" "0755"

  # flat is opt-out, and single-source only.
  LAYOUT=flat pkg "extra" || true
  assert_contains "layout=flat places at root" "$PKG_ENTRIES" "nested.txt"
  pkg "app.sh" EXTRA="LICENSE" LAYOUT=flat || true
  assert_contains "layout=flat refuses several sources" "$PKG_LOG" "use dir for several"

  # EXTRA adds files to a single-source package, which is how a binary and its
  # launcher script travel together.
  pkg "app.sh" EXTRA="LICENSE" || true
  assert_contains "EXTRA adds a second file" "$PKG_ENTRIES" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu/LICENSE"

  # A directory source is packaged whole, recursively.
  pkg "extra" || true
  assert_contains "directory source is recursive" "$PKG_ENTRIES" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu/extra/nested.txt"

  # Format selection: an explicit request always wins.
  FORMAT=tar.gz pkg "app.sh" || true
  assert_eq "tar.gz on request" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.gz"
  FORMAT=tar.xz pkg "app.sh" || true
  assert_eq "tar.xz on request" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"
  # ...and an empty format falls back to the runner's convention.
  FORMAT= RUNNER_OS=Windows_NT pkg "app.sh" || true
  assert_eq "zip is the Windows default" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.zip"
  FORMAT= RUNNER_OS=Linux pkg "app.sh" || true
  assert_eq "tar.gz is the non-Windows default" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.gz"

  # tar has to keep the executable bit too, for the same reason.
  FORMAT=tar.gz pkg "app.sh" || true
  local tar_mode
  tar_mode="$(tar -tvzf "$PKG_WORK/out/$PKG_ARCHIVE" 2>/dev/null \
              | awk '$NF ~ /app\.sh$/ {print substr($1,2); exit}')"
  assert_eq "executable bit is recorded in tar.gz" "$tar_mode" "rwxr-xr-x"

  # Bad input is rejected before anything is written.
  pkg "missing-file" || true
  assert_eq "missing source produces nothing" "$PKG_ARCHIVE" ""
  assert_contains "missing source explains itself" "$PKG_LOG" "does not exist"
  pkg "" || true
  assert_eq "empty source produces nothing" "$PKG_ARCHIVE" ""
  assert_contains "empty source explains itself" "$PKG_LOG" "nothing to package"
  NAME="" pkg "app.sh" || true
  assert_contains "empty name fails" "$PKG_LOG" "name is required"
  NAME="a/b" pkg "app.sh" || true
  assert_contains "name rejects a path separator" "$PKG_LOG" "path separator"
  TARGET="" pkg "app.sh" || true
  assert_contains "empty target fails" "$PKG_LOG" "target is required"
  FORMAT=rars pkg "app.sh" || true
  assert_contains "unknown format fails" "$PKG_LOG" "is not one of"
  LAYOUT=sideways pkg "app.sh" || true
  assert_contains "unknown layout fails" "$PKG_LOG" "is not one of"
  VERSION=latest pkg "app.sh" || true
  assert_contains "non-numeric version fails" "$PKG_LOG" "does not start with a digit"

  # Rebuilding in place must not grow the archive. This is inherent to the
  # writers rather than to the action, so it is a guard against a future
  # format switching to an appending mode rather than a claim about the code.
  pkg "app.sh" || true
  local first; first="$(wc -c <"$PKG_WORK/out/$PKG_ARCHIVE")"
  rm -f "$PKG_WORK/out.outputs"
  ( cd "$PKG_WORK" && GITHUB_OUTPUT="$PKG_WORK/out.outputs" env SOURCE=app.sh \
      OUTDIR=out NAME=rsrpc VERSION=0.29.0 TARGET=x86_64-unknown-linux-gnu \
      FORMAT=zip LAYOUT=dir RUNNER_OS=Linux python3 "$SCRIPT" >/dev/null 2>&1 )
  local second; second="$(wc -c <"$PKG_WORK/out/$PKG_ARCHIVE")"
  assert_eq "rebuild replaces rather than appends" "$second" "$first"

  rm -rf "$PKG_WORK"
}

# ---------------------------------------------------------------------------

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(resolve-release package-artifact)

for t in "${targets[@]}"; do
  case "$t" in
    resolve-release) test_resolve_release ;;
    package-artifact) test_package_artifact ;;
    *) echo "unknown action: $t" >&2; exit 2 ;;
  esac
  printf '\n'
done

printf 'passed=%s failed=%s\n' "$pass" "$fail"
[ "$fail" -eq 0 ]