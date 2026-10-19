"""Shared machinery for the action test suites.

The actions' logic lives in plain Python scripts, so they are driven directly:
a throwaway git repository stands in for the workspace, environment variables
stand in for the action inputs, and outputs are read from ``$GITHUB_OUTPUT``
exactly as the runner would read them.

Nothing here is an action under test — the suites import this and drive the
real scripts as subprocesses, so the scripts' own entry point is what gets
tested.
"""

from __future__ import annotations

import ast
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

# A `just` stand-in implementing the enforced `version` recipe contract:
# `just version get` prints X.Y.Z, `just version bump X` rewrites manifests.
JUST_STUB = """#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "version" ] || { echo "stub just: unsupported (want 'version ...')" >&2; exit 1; }
case "${2:-}" in
  get) sed -n -E 's/^version = "(.*)"/\\1/p' Cargo.toml 2>/dev/null | head -1 || true ;;
  bump) [ -n "${3:-}" ] || { echo "stub just: version bump needs a version" >&2; exit 1; }
        sed -i -E "s/^version = \\".*\\"/version = \\"$3\\"/" Cargo.toml ;;
  *) echo "stub just: unsupported version subcommand" >&2; exit 1 ;;
esac
"""

# A `just` with no `version` recipe at all: the action must fail fast on it.
JUST_BROKEN_STUB = """#!/usr/bin/env bash
echo "stub just: no version recipe" >&2; exit 1
"""

# Stands in for a platform that cannot stamp a symlink without following it,
# and says so rather than quietly following it. Imported automatically by
# `site` at interpreter startup, so it is in place before the action's own
# imports run — no rewriting of the action's source needed.
#
# Two things make it a platform rather than a bug:
#   * os.utime is not listed among the calls that support follow_symlinks, so
#     shutil skips it instead of passing the keyword — which is what a real
#     Windows runner does.
#   * os.utime refuses follow_symlinks=False with NotSupportedError, which is
#     the refusal the action's own fallback exists for.
WINDOWS_UTIME_SITECUSTOMIZE = '''"""Stand in for a platform that cannot stamp a symlink without following it."""
import errno
import os

_real_utime = os.utime
_NotSupportedError = getattr(errno, "NotSupportedError", OSError)


def _win_utime(path, times=(), *, ns=None, dir_fd=None, follow_symlinks=True):
    if follow_symlinks is False:
        raise _NotSupportedError("utime: cannot stamp a link without following it")
    if ns is not None:
        return _real_utime(path, ns=ns)
    return _real_utime(path, times)


# A platform that does not support the keyword does not list the call as
# supporting it, and shutil reads that list before passing the keyword.
os.supports_follow_symlinks.discard(os.utime)
os.utime = _win_utime
'''


def oneline(text: str) -> str:
    """A blob of text on one line, for a failure message."""
    return " ".join(text.split())


class Results:
    """Counts outcomes and prints them in the order the cases ran."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def ok(self, name: str) -> None:
        self.passed += 1
        print(f"  {GREEN}ok  {RESET} {name}")

    def bad(self, name: str, *details: str) -> None:
        self.failed += 1
        print(f"  {RED}FAIL{RESET} {name}")
        for detail in details:
            print(f"         {detail}")

    def assert_eq(self, what: str, got, want) -> None:
        if got == want:
            self.ok(what)
        else:
            self.bad(what, f"got:  {got}", f"want: {want}")

    def assert_contains(self, what: str, haystack: str, needle: str) -> None:
        if needle in haystack:
            self.ok(what)
        else:
            self.bad(what, f"missing: {needle}", f"in: {oneline(haystack)}")

    def assert_lacks(self, what: str, haystack: str, needle: str) -> None:
        if needle in haystack:
            self.bad(what, f"unexpectedly present: {needle}")
        else:
            self.ok(what)

    def fatal(self, message: str) -> None:
        """A broken test setup: report it and stop, rather than pass silently."""
        print(f"{RED}error{RESET} {message}", file=sys.stderr)
        raise SystemExit(2)


def check_action_metadata(results: Results, action_dir: str) -> pathlib.Path:
    """The action's own files must exist, parse, and be wired together.

    actionlint cannot lint an action.yml on its own — it parses one as a
    workflow — so this is what the action metadata gets.
    """
    action = REPO_ROOT / action_dir / "action.yml"
    script = REPO_ROOT / action_dir / f"{action_dir}.py"
    if not action.is_file():
        results.fatal(f"missing {action}")
    if not script.is_file():
        results.fatal(f"missing {script}")
    try:
        ast.parse(script.read_text())
    except SyntaxError as error:
        results.fatal(f"{script} does not parse: {error}")
    if script.name not in action.read_text():
        results.fatal(f"{action} does not invoke {script.name}")
    return script


class GitRepo:
    """A throwaway git repository with a bare origin, for the push paths.

    The origin is a real bare repository, so "the tag landed" is asserted
    against what was actually pushed rather than against a mock.
    """

    def __init__(
        self,
        manifest_version: str = "1.2.3",
        tag: str = "v1.2.3",
        just_stub: str = JUST_STUB,
    ) -> None:
        self.work = pathlib.Path(tempfile.mkdtemp())
        self.origin = self.work / "origin.git"
        self.repo = self.work / "repo"
        self.bin = self.work / "bin"
        self.bin.mkdir(parents=True)
        self.outputs_file = self.work / "out"
        self._write_just(just_stub)
        self._init_repo(manifest_version, tag)

    def _write_just(self, stub: str) -> None:
        stub_path = self.bin / "just"
        stub_path.write_text(stub)
        stub_path.chmod(0o755)

    def _init_repo(self, manifest_version: str, tag: str) -> None:
        self._git("init", "-q", "--bare", str(self.origin), cwd=self.work)
        self._git("init", "-q", str(self.repo), cwd=self.work)
        self._git("config", "user.email", "t@t", cwd=self.repo)
        self._git("config", "user.name", "t", cwd=self.repo)
        self._git("remote", "add", "origin", str(self.origin), cwd=self.repo)
        if manifest_version == "TAG-ONLY":
            (self.repo / "README.md").write_text("tag-only fixture, no manifest\n")
        else:
            (self.repo / "Cargo.toml").write_text(
                f'name = "x"\nversion = "{manifest_version}"\n'
            )
        self._git("add", "-A", cwd=self.repo)
        self._git("commit", "-qm", "init", cwd=self.repo)
        self._git("branch", "-M", "main", cwd=self.repo)
        self._git("push", "-q", "-u", "origin", "main", cwd=self.repo)
        if tag:
            self._git("tag", "-a", tag, "-m", "r", cwd=self.repo)
            self._git("push", "-q", "origin", f"refs/tags/{tag}", cwd=self.repo)

    def _git(self, *args: str, cwd: pathlib.Path) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def env(self, **overrides: str) -> dict:
        """The environment the action runs with: the stub `just` first on PATH."""
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["GITHUB_OUTPUT"] = str(self.outputs_file)
        env.update(overrides)
        return env

    def run(self, script: pathlib.Path, **overrides: str) -> tuple[int, str]:
        """Run an action script in the repo, with the given action inputs."""
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=self.repo,
            env=self.env(**overrides),
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def outputs(self) -> dict:
        """The action's step outputs, as the runner would read them."""
        if not self.outputs_file.is_file():
            return {}
        values = {}
        for line in self.outputs_file.read_text().splitlines():
            key, _, value = line.partition("=")
            values[key] = value
        return values

    def remote_tags(self) -> list:
        out = subprocess.run(
            ["git", "tag", "-l"],
            cwd=self.origin,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.split()

    def close(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def __enter__(self) -> "GitRepo":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def archive_entries(path: pathlib.Path) -> list:
    """(mode, name) for every member of an archive, whichever container it is."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return [
                ((info.external_attr >> 16) & 0o7777, info.filename)
                for info in archive.infolist()
            ]
    with tarfile.open(path) as archive:
        return [(member.mode, member.name) for member in archive.getmembers()]


class Package:
    """One package-artifact run, with what came out described."""

    def __init__(
        self,
        script: pathlib.Path,
        source: str,
        env: dict | None = None,
        name: str = "rsrpc",
        version: str = "0.29.0",
        target: str = "x86_64-unknown-linux-gnu",
        outdir: str = "out",
    ) -> None:
        self.work = pathlib.Path(tempfile.mkdtemp())
        self.outdir = outdir
        (self.work / outdir).mkdir()
        self.outputs_file = self.work / "out.outputs"
        self._make_fixtures()

        environment = dict(os.environ)
        environment["GITHUB_OUTPUT"] = str(self.outputs_file)
        environment.update(
            {
                "SOURCE": source,
                "OUTDIR": outdir,
                "NAME": name,
                "VERSION": version,
                "TARGET": target,
            }
        )
        environment.update(env or {})

        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=self.work,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.returncode = proc.returncode
        self.log = "\n".join((proc.stdout + proc.stderr).splitlines()[-3:])

        self.archive = ""
        self.stem = ""
        self.entries: list = []
        self.mode = "none"
        self.staged: list = []
        if self.returncode == 0 and self.outputs_file.is_file():
            outputs = {}
            for line in self.outputs_file.read_text().splitlines():
                key, _, value = line.partition("=")
                outputs[key] = value
            self.archive = outputs.get("archive", "")
            self.stem = outputs.get("stem", "")
            archive_path = self.work / self.outdir / self.archive
            if archive_path.is_file():
                listing = archive_entries(archive_path)
                self.entries = [name for _, name in listing]
                for mode, member in listing:
                    if member.endswith("app.sh"):
                        self.mode = f"{mode:04o}"
                        break
            out_dir = self.work / self.outdir
            self.staged = [
                entry.name
                for entry in out_dir.iterdir()
                if entry.name != self.archive
            ]

    def _make_fixtures(self) -> None:
        """A fixture tree: an executable, a plain file, a directory of each.

        The `onlyexe` / `bothsuffixed` pair covers the Windows suffix rules:
        one exists only with the suffix, one exists both ways so the exact
        name can win.
        """
        app = self.work / "app.sh"
        app.write_text("#!/bin/sh\necho hi\n")
        app.chmod(0o755)
        (self.work / "app").write_text("x\n")
        (self.work / "LICENSE").write_text("licence\n")
        extra = self.work / "extra"
        extra.mkdir()
        (extra / "nested.txt").write_text("x\n")
        onlyexe = self.work / "onlyexe.exe"
        onlyexe.write_text("#!/bin/sh\n")
        onlyexe.chmod(0o755)
        (self.work / "bothsuffixed").write_text("x\n")
        (self.work / "bothsuffixed.exe").write_text("x\n")

    def close(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


def windows_utime_pythonpath() -> pathlib.Path:
    """A directory whose sitecustomize.py makes os.utime refuse symlinks."""
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / "sitecustomize.py").write_text(WINDOWS_UTIME_SITECUSTOMIZE)
    return directory


def xz_preset_used(script: pathlib.Path) -> str:
    """The preset the action actually passes to tarfile, read off its constant.

    Read back from the source rather than from a copy of the number, so a
    silent change to it is visible.
    """
    tree = ast.parse(script.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "COMPRESSION" for target in node.targets
        ):
            return str(ast.literal_eval(node.value)["tar.xz"])
    return ""


def effort_beats(script: pathlib.Path, target: str, reference_effort: int) -> str:
    """Whether the archive the action produced beats the same payload packed
    at a lower effort setting.

    The action's own output is what gets measured, so lowering its constant
    is what makes this fail. The comparison is between the *compressed size of
    the member*, not between the archive files: the action's archive has a
    top-level directory and a longer member name than the reference, and
    comparing whole files would let that difference stand in for a
    difference in effort.
    """
    with tempfile.TemporaryDirectory() as directory:
        work = pathlib.Path(directory)
        payload = work / "payload"
        # Binary-like, and tuned so deflate's effort settings diverge the way
        # they do on a real compiled binary (on rsRPC's own binary, level 1 is
        # ~9% larger than level 9). Too little redundancy and every level
        # above 1 ties, which would make the assertion pass without meaning
        # anything.
        rnd = random.Random(20261018)
        with payload.open("wb") as handle:
            for _ in range(4000):
                handle.write(rnd.randbytes(48) * 64)   # long repeats: cheap for any level
                handle.write(rnd.randbytes(32) * 8)
                handle.write(rnd.randbytes(256))
                handle.write(rnd.randbytes(1024) * 3)

        environment = dict(os.environ)
        environment["GITHUB_OUTPUT"] = str(work / "o")
        environment.update(
            {
                "SOURCE": "payload",
                "OUTDIR": "out",
                "NAME": "eff",
                "VERSION": "1.0.0",
                "TARGET": target,
            }
        )
        subprocess.run(
            [sys.executable, str(script)],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
        )

        ours = next((work / "out").iterdir())
        with zipfile.ZipFile(ours) as archive:
            member = max(archive.infolist(), key=lambda info: info.file_size)
            ours_size = member.compress_size

        reference = work / "ref"
        with zipfile.ZipFile(
            reference, "w", zipfile.ZIP_DEFLATED, compresslevel=reference_effort
        ) as archive:
            archive.write(payload, "p/payload")
        with zipfile.ZipFile(reference) as archive:
            reference_size = archive.getinfo("p/payload").compress_size

        if ours_size < reference_size:
            return "yes"
        return f"no ({ours_size} vs {reference_size})"
