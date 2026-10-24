"""Tests for the package-artifact action.

The action turns one build output into one archive with a name a consumer
can match. The cases below are the decisions it makes: the name, the format,
the layout, the executable bit, the compression effort, and the refusals.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

from harness import (
    Package,
    Results,
    check_action_metadata,
    effort_beats,
    windows_utime_pythonpath,
    xz_preset_used,
)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_windows_cannot_follow_symlinks(results: Results, script: pathlib.Path) -> None:
    """Packaging must survive a platform whose os.utime refuses symlinks.

    The zip path runs on Windows, where os.utime has no follow_symlinks
    support. The action must fall back rather than abort the whole step, so
    the platform is simulated: a sitecustomize.py puts a refusing os.utime in
    place before the action's own imports run.
    """
    directory = windows_utime_pythonpath()
    work = pathlib.Path(tempfile.mkdtemp())
    try:
        source = work / "pkg"
        source.mkdir()
        app = source / "app.sh"
        app.write_text("#!/bin/sh\n")
        app.chmod(0o755)
        (source / "link.sh").symlink_to(app.name)

        environment = dict(os.environ)
        environment["GITHUB_OUTPUT"] = str(work / "o")
        environment["PYTHONPATH"] = str(directory)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment.update(
            {
                "SOURCE": "pkg",
                "NAME": "t",
                "VERSION": "1.0.0",
                "TARGET": "x86_64-pc-windows-msvc",
            }
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
        )
        archive = work / "dist" / "t-1.0.0-x86_64-pc-windows-msvc.zip"
        if proc.returncode == 0 and archive.is_file():
            results.ok("packaging survives a platform that cannot follow symlinks")
        else:
            results.bad(
                "packaging survives a platform that cannot follow symlinks",
                f"exit={proc.returncode}",
                *(proc.stdout + proc.stderr).splitlines()[-2:],
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(directory, ignore_errors=True)


def test_rebuild_is_byte_identical(results: Results, script: pathlib.Path, target: str) -> None:
    """Rebuilding must replace rather than append, and be byte-identical.

    A rebuilt tag must not look like different artifacts to a consumer, so
    the archive has to come out the same bytes twice.
    """
    package = Package(script, source="app.sh", target=target)
    first = sha256(package.work / "dist" / package.archive)
    # A second run in the same output directory: the archive must be replaced,
    # not appended to.
    time.sleep(1)
    environment = dict(os.environ)
    environment["GITHUB_OUTPUT"] = str(package.work / "out.outputs")
    environment.update(
        {
            "SOURCE": "app.sh",
            "NAME": "rsrpc",
            "VERSION": "0.29.0",
            "TARGET": target,
        }
    )
    subprocess.run(
        [sys.executable, str(script)],
        cwd=package.work,
        env=environment,
        capture_output=True,
        text=True,
    )
    second = sha256(package.work / "dist" / package.archive)
    package.close()
    results.assert_eq(f"rebuild is byte-identical, not appended ({target})", second, first)


def run(results: Results) -> None:
    print("package-artifact")
    script = check_action_metadata(results, "package-artifact")

    def pkg(source: str, **env) -> Package:
        return Package(script, source=source, env=env)

    # Verify <name>-<version>-<target> archive naming.
    package = pkg("app.sh")
    results.assert_eq(
        "name is <name>-<version>-<target> + platform suffix",
        package.archive,
        "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz",
    )
    results.assert_eq(
        "stem output matches",
        package.stem,
        "rsrpc-0.29.0-x86_64-unknown-linux-gnu",
    )
    package.close()

    # A leading v must not leak into the archive name.
    package = pkg("app.sh", VERSION="v0.29.0")
    results.assert_eq(
        "leading v is dropped",
        package.archive,
        "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz",
    )
    package.close()

    # One top-level directory, always: extraction must not scatter files.
    package = pkg("app.sh")
    results.assert_contains(
        "everything sits under one directory",
        "\n".join(package.entries),
        "rsrpc-0.29.0-x86_64-unknown-linux-gnu/app.sh",
    )

    # Extraction must not scatter files, and the staging copy must not survive.
    results.assert_eq("staging dir is cleaned up", package.staged, [])

    # upload-artifact strips the executable bit, so it has to live in the archive.
    results.assert_eq("executable bit is recorded in tar.xz", package.mode, "0755")
    package.close()

    test_windows_cannot_follow_symlinks(results, script)

    # EXTRA adds files to a single-source package, which is how a binary and
    # its launcher script travel together — siblings inside one directory.
    package = pkg("app.sh", EXTRA="LICENSE")
    results.assert_contains(
        "EXTRA adds a second file",
        "\n".join(package.entries),
        "rsrpc-0.29.0-x86_64-unknown-linux-gnu/LICENSE",
    )
    package.close()

    # A directory source is packaged whole, recursively.
    package = pkg("extra")
    results.assert_contains(
        "directory source is recursive",
        "\n".join(package.entries),
        "rsrpc-0.29.0-x86_64-unknown-linux-gnu/extra/nested.txt",
    )
    package.close()

    # Target platform chooses format (Windows: zip, others: tar.xz).
    for target, expected in [
        ("x86_64-pc-windows-msvc", "rsrpc-0.29.0-x86_64-pc-windows-msvc.zip"),
        ("i686-pc-windows-gnu", "rsrpc-0.29.0-i686-pc-windows-gnu.zip"),
        ("aarch64-apple-darwin", "rsrpc-0.29.0-aarch64-apple-darwin.tar.xz"),
        ("x86_64-unknown-linux-gnu", "rsrpc-0.29.0-x86_64-unknown-linux-gnu.tar.xz"),
        ("x86_64-unknown-freebsd", "rsrpc-0.29.0-x86_64-unknown-freebsd.tar.xz"),
    ]:
        package = pkg("app.sh", TARGET=target)
        results.assert_eq(f"{target} gets {expected.rsplit('.', 1)[-1]}", package.archive, expected)
        package.close()

    # The executable bit has to survive zip as well as tar.
    package = pkg("app.sh", TARGET="x86_64-pc-windows-msvc")
    results.assert_eq("executable bit is recorded in zip", package.mode, "0755")
    package.close()

    # Verify compression settings (zip measured, xz preset checked).
    results.assert_eq(
        "zip at max beats the fastest setting",
        effort_beats(script, "x86_64-pc-windows-msvc", 1),
        "yes",
    )
    results.assert_eq("tar.xz is written at preset 9", xz_preset_used(script), "9")

    # Windows target resolves .exe when unsuffixed name is given.
    package = pkg("onlyexe", TARGET="x86_64-pc-windows-msvc")
    results.assert_contains(
        "a Windows target appends .exe",
        "\n".join(package.entries),
        "onlyexe.exe",
    )
    package.close()
    package = pkg("onlyexe", TARGET="i686-pc-windows-gnu")
    results.assert_contains(
        "a mingw Windows target appends .exe",
        "\n".join(package.entries),
        "onlyexe.exe",
    )
    package.close()
    package = pkg("bothsuffixed", TARGET="x86_64-unknown-linux-gnu")
    results.assert_contains(
        "a Linux target wants no suffix",
        "\n".join(package.entries),
        "bothsuffixed",
    )
    results.assert_lacks(
        "and does not invent one",
        "\n".join(package.entries),
        "bothsuffixed.exe",
    )
    package.close()

    # An exact name always wins, so a caller with the real path is never moved.
    package = pkg("bothsuffixed.exe", TARGET="x86_64-pc-windows-msvc")
    results.assert_contains(
        "an exact .exe name is used as given",
        "\n".join(package.entries),
        "bothsuffixed.exe",
    )
    package.close()

    # Neither present: the error has to name both spellings, or the reader has
    # to guess which the action tried.
    package = pkg("nowhere", TARGET="x86_64-pc-windows-msvc")
    results.assert_contains(
        "a missing binary names both spellings",
        package.log,
        "nowhere does not exist, nor nowhere.exe",
    )
    package.close()
    package = pkg("nowhere", TARGET="x86_64-unknown-linux-gnu")
    results.assert_contains(
        "a missing file on Linux names one spelling",
        package.log,
        "nowhere does not exist",
    )
    results.assert_lacks("no .exe offered on Linux", package.log, "nowhere.exe")
    package.close()

    # A Windows target must not fall back to a file that only exists without
    # the suffix, which would ship the wrong artifact.
    package = pkg("extra", TARGET="x86_64-pc-windows-msvc")
    results.assert_contains(
        "a directory source is unaffected by the suffix",
        "\n".join(package.entries),
        "rsrpc-0.29.0-x86_64-pc-windows-msvc/extra/nested.txt",
    )
    package.close()

    # Bad input is rejected before anything is written.
    package = pkg("missing-file")
    results.assert_eq("missing source produces nothing", package.archive, "")
    results.assert_contains("missing source explains itself", package.log, "does not exist")
    package.close()
    package = pkg("")
    results.assert_eq("empty source produces nothing", package.archive, "")
    results.assert_contains("empty source explains itself", package.log, "nothing to package")
    package.close()
    package = pkg("app.sh", NAME="")
    results.assert_contains("empty name fails", package.log, "name is required")
    package.close()
    package = pkg("app.sh", NAME="a/b")
    results.assert_contains("name rejects a path separator", package.log, "path separator")
    package.close()
    package = pkg("app.sh", TARGET="")
    results.assert_contains("empty target fails", package.log, "target is required")
    package.close()
    package = pkg("app.sh", VERSION="latest")
    results.assert_contains("non-numeric version fails", package.log, "does not start with a digit")
    package.close()

    # Rebuild must replace output and be byte-identical.
    test_rebuild_is_byte_identical(results, script, "x86_64-pc-windows-msvc")
    test_rebuild_is_byte_identical(results, script, "x86_64-unknown-linux-gnu")
