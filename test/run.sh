#!/usr/bin/env bash
#
# Tests for the composite actions in this repository.
#
# The `run:` block of a composite action is plain bash, so it can be driven
# directly: extract it, then run it against throwaway git repositories with
# environment variables standing in for the action inputs. Outputs are read
# from $GITHUB_OUTPUT exactly as the runner would.
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

  out="$(cd "$WORK/repo" && env "$@" bash "$SCRIPT" 2>&1)"; st=$?

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
  [ -f "$A" ] || { echo "missing $A" >&2; exit 2; }

  # Pull the script out of the single composite step. actionlint cannot lint an
  # action.yml on its own (it parses one as a workflow), so this extraction is
  # also the only structural check the file gets.
  SCRIPT="$(mktemp)"; trap 'rm -f "$SCRIPT"' RETURN
  awk '/^      run: \|$/ {f=1; next}
       f { if ($0 ~ /^        / || $0 == "") print substr($0, 9); else exit }' "$A" >"$SCRIPT"
  [ -s "$SCRIPT" ] || { echo "could not extract run: block from $A" >&2; exit 2; }

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
  run "short-ish bad ref -> fail"     fail 0 0 INPUT_REF="v1.2" DRY_RUN=false "${BASE[@]:0:3}" BUMP= CURRENT= NEXT= NEXT_STRICT=
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

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(resolve-release)

for t in "${targets[@]}"; do
  case "$t" in
    resolve-release) test_resolve_release ;;
    *) echo "unknown action: $t" >&2; exit 2 ;;
  esac
  printf '\n'
done

printf 'passed=%s failed=%s\n' "$pass" "$fail"
[ "$fail" -eq 0 ]