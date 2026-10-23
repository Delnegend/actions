"""Tests for the resolve-release action.

The action decides what a release run should do and then does it, so the
cases below are the decisions: nothing to ship, a dry run, a malformed
dispatch, an ungated commit, a version that does not move forward, and the
happy path that bumps, commits, tags and pushes.
"""

from __future__ import annotations

import pathlib

from harness import (
    JUST_BROKEN_STUB,
    GitRepo,
    Results,
    check_action_metadata,
)

# The action inputs, as the workflow passes them. The semver-action outputs
# are empty unless a case says otherwise: NEXT empty is the reliable
# "nothing to ship" signal, because semver-action returns before setting
# `bump` when there are no new commits.
BASE = {
    "INPUT_REF": "",
    "DRY_RUN": "false",
    "GATE_SHA": "",
    "BUMP": "",
    "CURRENT": "v1.2.3",
    "NEXT": "",
    "NEXT_STRICT": "",
}


def run_case(
    results: Results,
    name: str,
    expect: str,
    expect_skip: int,
    expect_publish: int,
    env: dict | None = None,
    manifest: str = "1.2.3",
    tag: str = "v1.2.3",
    remote_tag: str = "",
) -> None:
    """Run the action over a throwaway repo and assert what it decided.

    `expect` is "ok" or "fail"; the skip and publish counts are what the
    build job reads, so a case that decided the wrong thing fails here even
    when the process exited cleanly.
    """
    with GitRepo(manifest_version=manifest, tag=tag) as repo:
        returncode, output = repo.run(
            pathlib.Path(__file__).parent / ".." / "resolve-release" / "resolve-release.py",
            **{**BASE, **(env or {})},
        )

        outputs = repo.outputs()
        skip = 1 if outputs.get("skip") == "true" else 0
        publish = 1 if outputs.get("publish") == "true" else 0

        problems = []
        if expect == "ok" and returncode != 0:
            problems.append(f"exit={returncode} want=0")
        if expect == "fail" and returncode == 0:
            problems.append("exit=0 want=non-zero")
        if skip != expect_skip:
            problems.append(f"skip={skip} want={expect_skip}")
        if publish != expect_publish:
            problems.append(f"publish={publish} want={expect_publish}")
        if remote_tag and remote_tag not in repo.remote_tags():
            problems.append(f"tag {remote_tag} not pushed")

        if problems:
            results.bad(name, *problems, *output.splitlines()[-2:])
        else:
            results.ok(name)


def test_build_version_packages(results: Results, script: pathlib.Path) -> None:
    """A test-build's version must be one package-artifact accepts.

    The version lands in an archive filename downstream, so a bare SHA would
    not do. Asserted against that action rather than against a rule restated
    here, so the two cannot drift apart.
    """
    from harness import Package

    with GitRepo() as repo:
        _, _ = repo.run(
            script,
            INPUT_REF="abc1234def5678",
            DRY_RUN="false",
            GATE_SHA="",
            BUMP="",
            CURRENT="",
            NEXT="",
            NEXT_STRICT="",
        )
        version = repo.outputs().get("version", "")

    package_script = script.parent.parent / "package-artifact" / "package-artifact.py"
    package = Package(
        package_script,
        source="app",
        name="app",
        version=version,
        target="x86_64-unknown-linux-gnu",
    )
    expected = f"app-{version}-x86_64-unknown-linux-gnu.tar.xz"
    if version == "0.0.0-test.abc1234" and (package.work / "dist" / expected).is_file():
        results.ok(f"test-build version packages as {version}")
    else:
        results.bad(
            "test-build version packages",
            f"version={version} is not 0.0.0-test.<sha>",
            f"expected archive {expected}",
        )
    package.close()


def test_missing_version_recipe(results: Results, script: pathlib.Path) -> None:
    """A repo without the `version` recipe must fail fast, not ship blind."""
    with GitRepo(just_stub=JUST_BROKEN_STUB) as repo:
        returncode, output = repo.run(
            script,
            **{
                **BASE,
                "BUMP": "patch",
                "CURRENT": "v1.2.3",
                "NEXT": "v1.2.4",
                "NEXT_STRICT": "1.2.4",
            },
        )
    if returncode != 0 and "just version get" in output:
        results.ok("missing version recipe -> fail fast")
    else:
        results.bad(
            "missing version recipe -> fail fast",
            f"exit={returncode}",
            *output.splitlines()[-2:],
        )


def run(results: Results) -> None:
    print("resolve-release")
    script = check_action_metadata(results, "resolve-release")

    # Nothing releasable.
    run_case(results, "no new commits -> skip", "ok", 1, 0)
    run_case(results, "bump=none -> skip", "ok", 1, 0, {"BUMP": "none"})
    run_case(results, "bump=none leaves no tag", "ok", 1, 0, {"BUMP": "none"})

    # A dry run must never mutate, on any path.
    run_case(
        results,
        "dry-run ship -> skip",
        "ok",
        1,
        0,
        {
            "DRY_RUN": "true",
            "BUMP": "patch",
            "CURRENT": "v1.2.3",
            "NEXT": "v1.2.4",
            "NEXT_STRICT": "1.2.4",
        },
    )
    run_case(
        results,
        "dry-run sha -> skip",
        "ok",
        1,
        0,
        {"INPUT_REF": "abc1234", "DRY_RUN": "true"},
    )
    run_case(
        results,
        "dry-run tag -> skip",
        "ok",
        1,
        0,
        {"INPUT_REF": "v1.2.3", "DRY_RUN": "true"},
    )

    # A malformed ref is rejected before anything mutates, dry-run included.
    run_case(
        results,
        "malformed ref -> fail",
        "fail",
        0,
        0,
        {"INPUT_REF": "v1.2", "CURRENT": "", "NEXT": "", "NEXT_STRICT": ""},
    )
    run_case(
        results,
        "bad ref on dry-run -> fail",
        "fail",
        0,
        0,
        {"INPUT_REF": "main", "DRY_RUN": "true"},
    )

    # Commit test-builds never publish.
    run_case(results, "sha -> no publish", "ok", 0, 0, {"INPUT_REF": "abc1234"})

    test_build_version_packages(results, script)

    # Tag rebuild.
    run_case(results, "tag rebuild -> publish", "ok", 0, 1, {"INPUT_REF": "v1.2.3"})
    run_case(results, "missing tag -> fail", "fail", 0, 0, {"INPUT_REF": "v9.9.9"})

    # Nothing ungated may ship.
    run_case(
        results,
        "gate sha mismatch -> fail",
        "fail",
        0,
        0,
        {
            "GATE_SHA": "deadbeef",
            "BUMP": "patch",
            "CURRENT": "v1.2.3",
            "NEXT": "v1.2.4",
            "NEXT_STRICT": "1.2.4",
        },
    )

    # Never republish or go backwards.
    run_case(
        results,
        "next == latest -> fail",
        "fail",
        0,
        0,
        {
            "BUMP": "patch",
            "CURRENT": "v1.2.3",
            "NEXT": "v1.2.3",
            "NEXT_STRICT": "1.2.3",
        },
    )
    run_case(
        results,
        "next < latest -> fail",
        "fail",
        0,
        0,
        {
            "BUMP": "patch",
            "CURRENT": "v1.2.3",
            "NEXT": "v1.0.0",
            "NEXT_STRICT": "1.0.0",
        },
    )

    # The happy path: bump, commit, tag, push — with a real remote to push to.
    run_case(
        results,
        "ship -> bump, tag, push",
        "ok",
        0,
        1,
        {
            "BUMP": "patch",
            "CURRENT": "v1.2.3",
            "NEXT": "v1.2.4",
            "NEXT_STRICT": "1.2.4",
        },
        remote_tag="v1.2.4",
    )

    # Empty version output fails loud: every repo must version a file.
    run_case(
        results,
        "empty version get -> fail",
        "fail",
        0,
        0,
        {
            "BUMP": "patch",
            "CURRENT": "v1.2.3",
            "NEXT": "v1.2.4",
            "NEXT_STRICT": "1.2.4",
        },
        manifest="TAG-ONLY",
    )

    # A stranded bump commit gets its tag rather than being skipped.
    run_case(
        results,
        "manifest ahead -> tag stranded commit",
        "ok",
        0,
        1,
        manifest="9.9.9",
        remote_tag="v9.9.9",
    )

    # A manifest that is not ahead must not trigger recovery.
    run_case(
        results,
        "manifest level -> no recovery",
        "ok",
        1,
        0,
    )

    test_missing_version_recipe(results, script)
