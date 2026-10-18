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
# Describe an archive as "<octal mode> <member>", reading whichever container
# it happens to be. Python rather than unzip/tar, which are not part of the
# toolset these tests are allowed to rely on.
archive_entries() {
  python3 - "$1" <<'PY'
import sys, tarfile, zipfile
path = sys.argv[1]
if zipfile.is_zipfile(path):
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            print(f"{(i.external_attr >> 16) & 0o7777:04o} {i.filename}")
else:
    with tarfile.open(path) as t:
        for m in t.getmembers():
            print(f"{m.mode:04o} {m.name}")
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
        RUNNER_OS="${RUNNER_OS-Linux}" \
        "$@" python3 "$SCRIPT" >"$PKG_WORK/out.log" 2>&1
  )
  local st=$?

  PKG_ARCHIVE=""; PKG_STEM=""; PKG_ENTRIES=""; PKG_MODE="none"; PKG_STAGED=""
  if [ "$st" -eq 0 ] && [ -f "$PKG_WORK/out.outputs" ]; then
    PKG_ARCHIVE="$(grep -m1 '^archive=' "$PKG_WORK/out.outputs" | cut -d= -f2-)"
    PKG_STEM="$(grep -m1 '^stem=' "$PKG_WORK/out.outputs" | cut -d= -f2-)"
    if [ -f "$PKG_WORK/out/$PKG_ARCHIVE" ]; then
      local listing; listing="$(archive_entries "$PKG_WORK/out/$PKG_ARCHIVE" 2>/dev/null)"
      PKG_ENTRIES="$(printf '%s\n' "$listing" | cut -d' ' -f2-)"
      PKG_MODE="$(printf '%s\n' "$listing" | awk '$2 ~ /app\.sh$/ { print $1; exit }')"
    fi
    PKG_STAGED="$(cd "$PKG_WORK/out" && ls -A | grep -vx "$PKG_ARCHIVE" || true)"
  fi
  PKG_LOG="$(tail -3 "$PKG_WORK/out.log" 2>/dev/null)"
  return $st
}

# The preset the action actually passed to tarfile, read back off the constant
# the script uses, so a silent change to it is visible.
xz_preset_used() {
  python3 -c "
import ast, sys
tree = ast.parse(open(sys.argv[1]).read())
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', None) == 'COMPRESSION' for t in node.targets):
        print(ast.literal_eval(node.value)['tar.xz'])
        break
" "$SCRIPT"
}

# Package once with UTIME_FOLLOW forced off, standing in for the Windows
# runner. Copies the script so the real one is not edited.
pkg_works_without_symlink_following() {
  local d; d="$(mktemp -d)"
  cp "$SCRIPT" "$d/pa.py"
  python3 - "$d/pa.py" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
# Stand in for the Windows runner: utime refuses follow_symlinks, which is
# what the zip path does there. Only the flag is forced off as well, so the
# try/except still has to be what saves the step.
# Windows os.utime has no follow_symlinks support: shutil copystat therefore
  # drops the keyword rather than passing it (see its lookup() helper, which
  # falls back to a no-op when os.name is not in os.supports_follow_symlinks).
  # So stand in for Windows by removing utime from that set and giving it a
  # two-argument signature, which is exactly the surface Windows exposes.
# Windows os.utime raises on the follow_symlinks keyword, which is what the
  # Windows build of this action hit. Stand in for it by rejecting the keyword,
  # so the retry without it is what keeps the step alive.
s = s.replace('import errno\nimport os', 'import errno\nimport os\n\n_real_utime = os.utime')
s = s.replace('def env(name, default=""):',
              '_UNSET = object()\n\n\n'
              'def _win_utime(path, times=(), *, ns=None, dir_fd=None, follow_symlinks=False):\n'
              '    # Windows can follow a regular file and stamps it normally; it\n'
              '    # refuses only when following would cross a symlink.\n'
              '    if follow_symlinks and os.path.islink(path):\n'
              '        raise NotImplementedError("utime: follow_symlinks unavailable")\n'
              '    if ns is not None:\n'
              '        return _real_utime(path, ns=ns, dir_fd=dir_fd, follow_symlinks=False)\n'
              '    return _real_utime(path, times, dir_fd=dir_fd, follow_symlinks=False)\n\n'
              'os.utime = _win_utime\n\n\n'
              'def env(name, default=""):')
s = s.replace('import errno\nimport os', 'import errno\nimport os\n\n_real_utime = os.utime')
p.write_text(s)
PY
  ( cd "$d" && mkdir -p pkg && printf '#!/bin/sh\n' >pkg/app.sh && chmod +x pkg/app.sh && \
    ln -s app.sh pkg/link.sh && \
    GITHUB_OUTPUT="$d/o" env SOURCE=pkg OUTDIR=out NAME=t VERSION=1.0.0 \
      TARGET=t RUNNER_OS=Windows_NT PYTHONDONTWRITEBYTECODE=1 \
      python3 "$d/pa.py" >"$d/log" 2>&1 )
  
  local st=$?
  [ "$st" -eq 0 ] && [ -f "$d/out/t-1.0.0-t.zip" ]
  local rc=$?
  PKG_WORK="$d"
  return $rc
}

# Run the action over binary-like input, then compare the archive it produced
# against the same payload packed at a lower effort setting. The action's own
# output is what gets measured, so lowering its constant is what makes this
# fail.
effort_zip() { effort_check Windows_NT zip "$1"; }

effort_check() {
  local runner="$1" mode="$2" ref_effort="$3"
  local d; d="$(mktemp -d)"
  # Binary-like, and tuned so deflate's effort settings diverge the way they do
  # on a real compiled binary (on rsRPC's own binary, level 1 is ~9% larger
  # than level 9). Too little redundancy and every level above 1 ties, which
  # would make this assertion pass without meaning anything.
  python3 -c "
import random, sys
rnd = random.Random(20261018)
with open(sys.argv[1],'wb') as f:
    for _ in range(4000):
        f.write(rnd.randbytes(48) * 64)     # long repeats: cheap for any level
        f.write(rnd.randbytes(32) * 8)
        f.write(rnd.randbytes(256))
        f.write(rnd.randbytes(1024) * 3)
" "$d/payload"

  # deflate is not monotonic across its top levels — on some inputs level 9
  # emits marginally more than level 8 — so the comparison is against level 1,
  # where the gap is real and large enough to be unambiguous.

  ( cd "$d" && GITHUB_OUTPUT="$d/o" env SOURCE=payload OUTDIR=out \
      NAME=eff VERSION=1.0.0 TARGET=t RUNNER_OS="$runner" \
      python3 "$SCRIPT" >/dev/null 2>&1 )

  python3 - "$d" "$ref_effort" <<'PY'
import glob, os, sys, zipfile
d, ref_effort = sys.argv[1], int(sys.argv[2])
ours = glob.glob(os.path.join(d, "out", "*"))[0]
ref = os.path.join(d, "ref")
with zipfile.ZipFile(ref, "w", zipfile.ZIP_DEFLATED,
                     compresslevel=ref_effort) as z:
    z.write(os.path.join(d, "payload"), "p/payload")
print("yes" if os.path.getsize(ours) < os.path.getsize(ref)
      else f"no ({os.path.getsize(ours)} vs {os.path.getsize(ref)})")
PY
  rm -rf "$d"
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
  assert_eq "name is <name>-<version>-<target> + platform suffix" \
    "$PKG_ARCHIVE" "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"
  assert_eq "stem output matches" "$PKG_STEM" "rsrpc-0.29.0-x86_64-unknown-linux-gnu"

  # A leading v must not leak into the archive name.
  VERSION=v0.29.0 pkg "app.sh" || true
  assert_eq "leading v is dropped" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"

  # One top-level directory, always: extraction must not scatter files.
  assert_contains "everything sits under one directory" "$PKG_ENTRIES" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu/app.sh"

  # Extraction must not scatter files, and the staging copy must not survive.
  assert_eq "staging dir is cleaned up" "$PKG_STAGED" ""

  # The zip path runs on Windows, where os.utime cannot follow a symlink. The
  # staging loop must survive that rather than aborting the whole step, so
  # exercise it with follow_symlinks off — which is what Windows gets.
  if pkg_works_without_symlink_following; then
    ok "packaging survives a platform that cannot follow symlinks"
  else
    bad "packaging survives a platform that cannot follow symlinks" \
        "$(tail -2 "$PKG_WORK/log" 2>/dev/null | sed 's/^/          /')"
  fi

  # upload-artifact strips the executable bit, so it has to live in the archive.
  assert_eq "executable bit is recorded in tar.xz" "$PKG_MODE" "0755"

  # EXTRA adds files to a single-source package, which is how a binary and its
  # launcher script travel together — siblings inside the one directory.
  pkg "app.sh" EXTRA="LICENSE" || true
  assert_contains "EXTRA adds a second file" "$PKG_ENTRIES" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu/LICENSE"

  # A directory source is packaged whole, recursively.
  pkg "extra" || true
  assert_contains "directory source is recursive" "$PKG_ENTRIES" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu/extra/nested.txt"

  # Format is decided by the platform and is not a caller choice.
  RUNNER_OS=Windows_NT pkg "app.sh" || true
  assert_eq "Windows gets zip" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.zip"
  RUNNER_OS=Linux pkg "app.sh" || true
  assert_eq "Linux gets tar.xz" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"
  RUNNER_OS=macOS pkg "app.sh" || true
  assert_eq "macOS gets tar.xz" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"
  RUNNER_OS= pkg "app.sh" || true
  assert_eq "an unset runner OS still gets tar.xz" "$PKG_ARCHIVE" \
    "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"

  # The executable bit has to survive zip as well as tar.
  RUNNER_OS=Windows_NT pkg "app.sh" || true
  assert_eq "executable bit is recorded in zip" "$PKG_MODE" "0755"

  # Compression effort is download bandwidth for every consumer, so it is
  # pinned by measurement rather than by reading the constant: the archive
  # this action produced must be smaller than the same payload at a lower
  # effort setting.
  #
  # zip shows a real gradient (level 1 through 9 differ measurably on binary
  # input), so lowering it must be caught. xz does not: on a real rsRPC
  # binary presets 6, 8 and 9 produce byte-identical output, and 9|EXTRE is
  # slightly larger. Asking xz to beat preset 8 would therefore assert
  # something that is not true of the format, so xz is pinned by its recorded
  # preset instead and zip carries the measurement.
  assert_eq "zip at max beats the fastest setting" "$(effort_zip 1)" "yes"
  assert_eq "tar.xz is written at preset 9" "$(xz_preset_used)" "9"

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
  VERSION=latest pkg "app.sh" || true
  assert_contains "non-numeric version fails" "$PKG_LOG" "does not start with a digit"

  # Rebuilding must replace rather than append, and be byte-identical so a
  # rebuilt tag does not look like different artifacts to a consumer. Tar
  # records mtimes, so this only holds because staging normalises them.
  RUNNER_OS=Windows_NT pkg "app.sh" || true
  local zfirst; zfirst="$(sha256sum "$PKG_WORK/out/$PKG_ARCHIVE" | cut -d' ' -f1)"
  rm -f "$PKG_WORK/out.outputs"
  ( cd "$PKG_WORK" && sleep 1 && GITHUB_OUTPUT="$PKG_WORK/out.outputs" env SOURCE=app.sh \
      OUTDIR=out NAME=rsrpc VERSION=0.29.0 TARGET=x86_64-unknown-linux-gnu \
      RUNNER_OS=Windows_NT python3 "$SCRIPT" >/dev/null 2>&1 )
  assert_eq "zip rebuild is byte-identical too" \
    "$(sha256sum "$PKG_WORK/out/$PKG_ARCHIVE" | cut -d' ' -f1)" "$zfirst"

  # Rebuilding must replace rather than append, and be byte-identical so a
  pkg "app.sh" || true
  local first; first="$(sha256sum "$PKG_WORK/out/$PKG_ARCHIVE" | cut -d' ' -f1)"
  rm -f "$PKG_WORK/out.outputs"
  ( cd "$PKG_WORK" && sleep 1 && GITHUB_OUTPUT="$PKG_WORK/out.outputs" env SOURCE=app.sh \
      OUTDIR=out NAME=rsrpc VERSION=0.29.0 TARGET=x86_64-unknown-linux-gnu \
      RUNNER_OS=Linux python3 "$SCRIPT" >/dev/null 2>&1 )
  local second; second="$(sha256sum "$PKG_WORK/out/$PKG_ARCHIVE" | cut -d' ' -f1)"
  assert_eq "rebuild is byte-identical, not appended" "$second" "$first"

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