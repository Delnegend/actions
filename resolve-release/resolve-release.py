#!/usr/bin/env python3
"""Resolve what a release run should do, then do it.

Runs in the caller's `prepare` job, after checkout and after the semver step,
and reports `ref`, `version`, `publish` and `skip` for the build job.

One function per dispatch path, chosen by `ref`:

    empty        ship a new version: bump, commit, tag, push
    commit SHA   test-build that commit, publish nothing
    vX.Y.Z       rebuild and publish an existing tag

Environment, set by the `resolve-release` action wrapper:

    INPUT_REF    dispatch ref: empty, 7-64 hex, or vX.Y.Z
    DRY_RUN      "true" to preview without mutating anything
    GATE_SHA     commit the CI gate approved; shipping refuses if HEAD moved
    MANIFEST_PATH  file holding the source-of-truth version; empty disables
                   recovery
    BUMP_COMMAND   command that rewrites the version files, given the new
                   version as its first argument; empty means manifest-less
    BUMP, CURRENT, NEXT, NEXT_STRICT    outputs of ietf-tools/semver-action

Results are appended to $GITHUB_OUTPUT.
"""

import os
import re
import shlex
import subprocess
import sys

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "actions@users.noreply.github.com"

SHA_RE = re.compile(r"[0-9a-f]{7,64}")
TAG_RE = re.compile(r"v\d+\.\d+\.\d+")
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def env(name, default=""):
    return os.environ.get(name, default)


def emit(**pairs):
    """Append step outputs the way the runner expects them."""
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        for key, value in pairs.items():
            f.write(f"{key}={value}\n")


def emit_skip(message):
    print(message)
    emit(ref="", version="", publish="false", skip="true")


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def git(*args):
    """Run git, capturing stdout for parsing and letting stderr reach the log."""
    return subprocess.run(["git", *args], check=True, text=True, stdout=subprocess.PIPE)


def git_ok(*args):
    """True when git exits zero. Used for existence checks."""
    return subprocess.run(["git", *args], capture_output=True).returncode == 0


def parse_version(version):
    """(1, 2, 3) from '1.2.3' or 'v1.2.3'; None when it is not a plain version."""
    match = VERSION_RE.fullmatch(version.lstrip("v"))
    return tuple(int(part) for part in match.groups()) if match else None


def latest_tag():
    out = git("tag", "-l", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname").stdout
    return out.splitlines()[0] if out.splitlines() else ""


def manifest_version(path):
    """The version in the manifest's first `version = "…"` line, or ''."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                match = re.match(r'^version\s*=\s*"([^"]+)"', line)
                if match:
                    return match.group(1)
    except OSError:
        return ""
    return ""


def classify_ref(ref):
    """'sha', 'tag' or 'ship'; anything else is a typo worth failing on."""
    if not ref:
        return "ship"
    if SHA_RE.fullmatch(ref):
        return "sha"
    if TAG_RE.fullmatch(ref):
        return "tag"
    fail(f"ref must be empty, a commit SHA (7-64 hex), or a version tag (vX.Y.Z); got '{ref}'.")


def preview(kind):
    """Print what the run would do. Mutates nothing, so it exits immediately."""
    messages = {
        "sha": f"[dry-run] would test-build commit {env('INPUT_REF')} (no publish)",
        "tag": f"[dry-run] would rebuild tag {env('INPUT_REF')} and publish it",
        "ship": f"[dry-run] would bump to {env('NEXT_STRICT')}, tag {env('NEXT')}, "
                "push, build, and publish",
    }
    emit_skip(messages[kind])


def test_build(ref):
    print(f"Test build against commit {ref} (will not publish).")
    emit(ref=ref, version=ref, publish="false", skip="false")


def rebuild(ref):
    if not git_ok("rev-parse", "-q", "--verify", f"refs/tags/{ref}"):
        fail(f"tag {ref} does not exist.")
    print(f"Rebuilding existing tag {ref}.")
    emit(ref=ref, version=ref.removeprefix("v"), publish="true", skip="false")


def recover_stranded_bump(latest):
    """Tag the commit a previous run bumped but died before tagging.

    Such a commit is not conventional, so the next run reads as having nothing
    to release — but the manifest is ahead of the latest tag, so the tag is
    what is missing.
    """
    path = env("MANIFEST_PATH")
    if not path or not latest:
        return False
    version = manifest_version(path)
    parsed = parse_version(version)
    if not parsed or parsed <= parse_version(latest):
        return False

    print(f"Manifest ({version}) is ahead of latest tag ({latest}); "
          "tagging the stranded commit.")
    tag = f"v{version}"
    git("config", "user.name", BOT_NAME)
    git("config", "user.email", BOT_EMAIL)
    git("tag", "-a", tag, "-m", f"Release {tag}")
    git("push", "origin", f"refs/tags/{tag}")
    emit(ref=tag, version=version, publish="true", skip="false")
    return True


def ship():
    latest = latest_tag()

    if recover_stranded_bump(latest):
        return

    next_tag, next_strict = env("NEXT"), env("NEXT_STRICT")
    current = env("CURRENT") or "none"

    # NEXT is the signal, not BUMP: when there are no new commits at all the
    # semver action returns before setting `bump`, so BUMP is empty.
    if not next_tag or env("BUMP") == "none":
        emit_skip(f"No version bump needed (current: {current}).")
        return

    # Refuse to publish a version that is not strictly ahead of the latest tag.
    if latest and parse_version(next_tag) <= parse_version(latest):
        fail(f"Calculated {next_tag} is not ahead of latest tag {latest}; "
             "nothing new to ship.")

    git("config", "user.name", BOT_NAME)
    git("config", "user.email", BOT_EMAIL)

    bump_command = env("BUMP_COMMAND")
    if not bump_command:
        # Manifest-less project: the tag is the version, so HEAD is tagged
        # directly and nothing is committed.
        print(f"No bump command; tagging HEAD as {next_tag}.")
        git("tag", "-a", next_tag, "-m", f"Release {next_tag}")
        git("push", "origin", f"refs/tags/{next_tag}")
    else:
        subprocess.run([*shlex.split(bump_command), next_strict], check=True)
        git("add", "-u")
        if git_ok("diff", "--staged", "--quiet"):
            fail("bump produced no change in package files")
        git("commit", "-m", f"chore(release): {next_tag}")
        # Commit first: a failed tag push is recoverable from the manifest,
        # a lost commit is not.
        git("push", "origin", "HEAD:main")
        if git_ok("rev-parse", "-q", "--verify", f"refs/tags/{next_tag}"):
            fail(f"tag {next_tag} already exists")
        git("tag", "-a", next_tag, "-m", f"Release {next_tag}")
        git("push", "origin", f"refs/tags/{next_tag}")

    emit(ref=next_tag, version=next_strict, publish="true", skip="false")


def main():
    kind = classify_ref(env("INPUT_REF"))

    if env("DRY_RUN") == "true":
        preview(kind)
        return

    # Ref dispatch pins its own commit, so the gate check does not apply.
    if kind == "ship" and env("GATE_SHA"):
        head = git("rev-parse", "HEAD").stdout.strip()
        if head != env("GATE_SHA"):
            fail(f"main moved during the gate ({env('GATE_SHA')} -> {head}); "
                 "re-run to gate the new HEAD.")

    if kind == "sha":
        test_build(env("INPUT_REF"))
    elif kind == "tag":
        rebuild(env("INPUT_REF"))
    else:
        ship()


if __name__ == "__main__":
    main()