#!/usr/bin/env python3
"""Stage, archive and upload one build artifact under a consistent name.

Every project that ships compiled binaries has to answer the same three
questions — what the archive is called, what is inside it, and who owns the
executable bit. Answering them per-repository is how `<name>-<target>.zip` and
`<name>-<target>.tar.gz` end up sitting next to `<name>-<version>-<target>.zip`
in the same tap, with the two that carry no version unable to be tracked at all.

This script settles them in one place:

  name    the archive is always `<name>-<version>-<target>.<ext>`
  content by default everything sits under a single top-level directory named
          after the archive, so extraction never scatters files
  mode    the executable bit is recorded inside the archive

The mode point matters more than it looks. `actions/download-artifact` strips
it, so a workflow that restores permissions after downloading has already lost
them. Recording the mode in the archive is what actually survives the round
trip: zip keeps it in the entry's `external_attr`, tar in the header.

A leading `v` on the version is dropped, so a caller holding `v0.29.0` and one
holding `0.29.0` produce the same archive.

Environment, set by the action wrapper:

  SOURCE      path to a file or directory to package
  EXTRA       optional space-separated additional paths to include
  NAME        artifact base name, e.g. rsrpc
  VERSION     version being released, with or without a leading v
  TARGET      platform slug, e.g. x86_64-unknown-linux-gnu
  FORMAT      zip | tar.gz | tar.xz | 7z, or empty to pick per runner OS
  LAYOUT      dir | flat, or empty for dir
  OUTDIR      directory to write the archive into
  RUNNER_OS   the runner's OS, used to pick a default format

Results are appended to $GITHUB_OUTPUT.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

FORMATS = {
    "zip": ".zip",
    "tar.gz": ".tar.gz",
    "tgz": ".tar.gz",
    "tar.xz": ".tar.xz",
    "txz": ".tar.xz",
    "7z": ".7z",
}
DEFAULT_FORMAT = {"Windows_NT": "zip"}


def env(name, default=""):
    return os.environ.get(name, default).strip()


def emit(**pairs):
    """Append step outputs the way the runner expects them."""
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        for key, value in pairs.items():
            f.write(f"{key}={value}\n")


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def note(message):
    print(f"package-artifact: {message}")


def normalise_version(version):
    """Drop a leading v so callers holding either form agree on the name."""
    if not version:
        fail("version is required")
    stripped = version[1:] if version.startswith("v") else version
    if not stripped[0].isdigit():
        fail(f"version {version!r} does not start with a digit after any v prefix")
    return stripped


def check_component(value, label):
    """A component lands in a filename, so keep it boring."""
    if not value:
        fail(f"{label} is required")
    if set(value) & set("/\\ \t\n"):
        fail(f"{label} {value!r} must not contain a path separator or whitespace")
    return value


def resolve_format(runner):
    requested = env("FORMAT").lower() or DEFAULT_FORMAT.get(runner, "tar.gz")
    if requested not in FORMATS:
        fail(f"format {requested!r} is not one of: {', '.join(sorted(FORMATS))}")
    return requested


def collect():
    """Expand every requested path, keeping order and dropping empties."""
    found = []
    for raw in [env("SOURCE"), *env("EXTRA").split()]:
        if not raw:
            continue
        path = Path(raw)
        if not path.exists():
            fail(f"{raw} does not exist")
        if path not in found:
            found.append(path)
    if not found:
        fail("nothing to package: set SOURCE, or EXTRA alongside it")
    return found


def stage(sources, outdir, stem):
    """Copy every source into one directory named after the archive."""
    stage_dir = outdir / stem
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    for path in sources:
        dest = stage_dir / path.name
        if path.is_dir():
            shutil.copytree(path, dest, symlinks=True)
        else:
            shutil.copy2(path, dest)
    return stage_dir


def flat_entries(sources):
    """(path, arcname) pairs landing at the archive root, for layout=flat."""
    entries = []
    for source in sources:
        if source.is_dir():
            entries += [(child, str(child.relative_to(source)))
                        for child in sorted(source.rglob("*"))]
        else:
            entries.append((source, source.name))
    return entries


def reject_collisions(entries):
    """Two entries sharing an arcname means one silently overwrites the other."""
    seen = {}
    for _, arcname in entries:
        seen[arcname] = seen.get(arcname, 0) + 1
    clashes = sorted(name for name, count in seen.items() if count > 1)
    if clashes:
        fail(f"these entries collide at the archive root: {', '.join(clashes)}")


def write_zip(archive, entries, prefix=""):
    """ZipInfo.from_file carries st_mode into external_attr, which is the only
    place a zip can keep the executable bit."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arcname in entries:
            info = zipfile.ZipInfo.from_file(path, f"{prefix}{arcname}")
            if path.is_dir():
                zf.writestr(info, b"")
            else:
                zf.writestr(info, path.read_bytes())


def write_tar(archive, entries, prefix="", compression="gz"):
    # recursive so that adding a staged directory brings its contents with it;
    # tarfile stores a bare directory entry and nothing below it otherwise.
    with tarfile.open(archive, f"w:{compression}") as tar:
        for path, arcname in entries:
            tar.add(path, arcname=f"{prefix}{arcname}", recursive=True)


def write_7z(archive, sources):
    if not shutil.which("7z"):
        fail("format 7z needs p7zip on PATH: apt-get install -y p7zip-full")
    result = subprocess.run(
        ["7z", "a", "-t7z", str(archive), *[str(p) for p in sources]],
        capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"7z failed: {result.stderr.strip() or result.stdout.strip()}")


def main():
    name = check_component(env("NAME"), "name")
    target = check_component(env("TARGET"), "target")
    version = normalise_version(env("VERSION"))

    runner = env("RUNNER_OS")
    fmt = resolve_format(runner)
    layout = env("LAYOUT").lower() or "dir"
    if layout not in {"dir", "flat"}:
        fail(f"layout {layout!r} is not one of: dir, flat")

    sources = collect()

    stem = f"{name}-{version}-{target}"
    outdir = Path(env("OUTDIR") or "dist")
    outdir.mkdir(parents=True, exist_ok=True)
    archive = outdir / f"{stem}{FORMATS[fmt]}"

    note(f"{archive} ({fmt}, layout={layout}, {len(sources)} source(s))")

    # No unlink first: zipfile and tarfile both open "w", which truncates.
    staged = None
    if fmt == "7z":
        # 7z keeps its own directory layout; stage first so the single
        # top-level directory is the same one the other formats produce.
        staged = stage(sources, outdir, stem) if layout == "dir" else None
        write_7z(archive, [staged] if staged else sources)
    elif layout == "dir":
        staged = stage(sources, outdir, stem)
        entries = [(child, str(child.relative_to(staged)))
                   for child in sorted(staged.rglob("*")) if child.is_file()]
        if fmt == "zip":
            write_zip(archive, entries, prefix=f"{stem}/")
        else:
            write_tar(archive, [(staged, stem)],
                      compression="xz" if fmt == "tar.xz" else "gz")
    else:
        entries = flat_entries(sources)
        reject_collisions(entries)
        if fmt == "zip":
            write_zip(archive, entries)
        else:
            write_tar(archive, entries,
                      compression="xz" if fmt == "tar.xz" else "gz")

    if staged and staged.exists():
        shutil.rmtree(staged)

    if not archive.exists() or archive.stat().st_size == 0:
        fail(f"{archive} was not produced")

    note(f"{archive.stat().st_size} bytes")
    emit(archive=archive.name, path=str(archive), stem=stem, version=version)


if __name__ == "__main__":
    main()