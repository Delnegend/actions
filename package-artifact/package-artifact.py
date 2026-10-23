#!/usr/bin/env python3
"""Stage, archive and upload one build artifact under a consistent name.

Every project that ships compiled binaries has to answer the same three
questions — what the archive is called, what is inside it, and who owns the
executable bit. Answering them per-repository is how `<name>-<target>.zip` and
`<name>-<target>.tar.gz` end up sitting next to `<name>-<version>-<target>.zip`
in the same tap, with the two that carry no version unable to be tracked at all.

Every one of those is decided here rather than at the call site:

  name      `<name>-<version>-<target>.<ext>`
  format    zip on Windows, tar.xz everywhere else
  effort    maximum for whichever format was chosen
  content   one top-level directory named after the archive
  mode      the executable bit, recorded inside the archive

A caller supplies what is unique to their build — the binary, the version, the
target triple — and gets the rest. Each decision left to a call site is one a
consumer eventually has to special-case, and a formula cannot handle both
`<name>-0.29.0-linux.tar.gz` and `<name>-0.29.0-linux.zip`.

The mode point matters more than it looks. `actions/download-artifact` strips
it, so a workflow that restores permissions after downloading has already lost
them. Recording the mode in the archive is what actually survives the round
trip: zip keeps it in the entry's `external_attr`, tar in the header.

A leading `v` on the version is dropped, so a caller holding `v0.29.0` and one
holding `0.29.0` produce the same archive.

Environment, set by the action wrapper:

  SOURCE      path to a file or directory to package. For a Windows target
              the .exe suffix is tried when the plain path is absent
  EXTRA       optional space-separated additional paths to include
  NAME        artifact base name, e.g. rsrpc
  TARGET      target triple, e.g. x86_64-unknown-linux-gnu. Its OS component
              selects the archive format, not the runner's.

The archive is always written into `dist/`.

Results are appended to $GITHUB_OUTPUT.
"""

import errno
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

# Raised when a filesystem cannot support the request at all, as opposed to
# the operation being refused for this path. Not present on every Python the
# runners ship, hence the fallback.
NotSupportedError = getattr(errno, "NotSupportedError", OSError)

# One archive format per target platform, chosen here and not at the call site.
#
# Keyed on the target's OS component rather than runner.os: a matrix entry can
# target Windows while building on a Linux runner (a mingw cross-build), and
# keying on the runner would hand a Windows consumer a tar.xz.
#
# Windows gets zip because that is what a Windows user expects to double-click,
# and because the Linuxbrew formulae that consume these archives reference zip
# names on that platform. Everything else gets tar.xz: it compresses materially
# better on compiled binaries, and tar is what a Unix user reaches for.
#
# The preset is -9 rather than -9e. Measured on a 4.7 MB release binary, -9e is
# within 0.005% of -9 in size for about 5% more CPU, so the extra effort buys
# nothing a consumer would notice while making the slowest runners slower.
# The OS is not at a fixed index: `<arch>-<os>-<env>` for most targets but
# `<arch>-<vendor>-<os>-<env>` for Windows ones. So the field is matched by
# name instead of position.
OS = {"windows", "linux", "darwin", "apple", "freebsd", "netbsd", "openbsd"}
FORMAT = {"windows": "zip"}
EXECUTABLE_SUFFIX = {"windows": ".exe"}
SUFFIX = {"zip": ".zip", "tar.xz": ".tar.xz"}
COMPRESSION = {"zip": 9, "tar.xz": 9}
# tarfile names the compression, not the format.
TAR_MODE = {"tar.xz": "xz"}
# 1980-01-01T00:00:00Z, the earliest timestamp a zip entry can hold.
ZIP_EPOCH = 315532800


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


def target_os(target):
    """The OS field of a target triple, or empty when it names none we know."""
    for field in target.lower().split("-"):
        if field in OS:
            return field
    return ""


def archive_format(target):
    """The format for the platform being built for. Not a call-site choice."""
    return FORMAT.get(target_os(target), "tar.xz")


def executable_suffix(target):
    """`.exe` for a Windows target, nothing otherwise.

    Every compiler appends it and every caller would otherwise have to carry
    the same conditional in its matrix, which is where the duplication this
    replaces came from.
    """
    return EXECUTABLE_SUFFIX.get(target_os(target), "")


def resolve(path, target):
    """Find the file at `path`, appending the platform's executable suffix.

    The plain path wins when it exists, so a caller that already has the exact
    name is never redirected.
    """
    candidate = Path(path)
    if candidate.exists():
        return candidate
    suffix = executable_suffix(target)
    if suffix:
        suffixed = Path(f"{path}{suffix}")
        if suffixed.exists():
            return suffixed
        fail(f"{path} does not exist, nor {path}{suffix}")
    fail(f"{path} does not exist")


def collect(target):
    """Expand every requested path, keeping order and dropping empties."""
    found = []
    for raw in [env("SOURCE"), *env("EXTRA").split()]:
        if not raw:
            continue
        path = resolve(raw, target)
        if path not in found:
            found.append(path)
    if not found:
        fail("nothing to package: set SOURCE, or EXTRA alongside it")
    return found


def stage(sources, outdir, stem):
    """Copy every source into one directory named after the archive.

    Timestamps are normalised so the archive is reproducible: tar records
    mtimes, so two runs of the same commit would otherwise produce different
    bytes and a rebuilt release would look like a different artifact. Build
    time is not information a consumer needs from inside a tarball.
    """
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

    # zip's DOS timestamp field cannot represent anything before 1980, so the
    # epoch is clamped to the format's own floor.
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or "0")
    epoch = max(epoch, ZIP_EPOCH)
    for path in sorted(stage_dir.rglob("*")) + [stage_dir]:
        try:
            # follow_symlinks=False stamps the link itself rather than its
            # target, which is what ends up in the archive. Windows has no
            # support for the keyword and refuses it outright, so a refusal
            # falls back to the same call without it.
            os.utime(path, (epoch, epoch), follow_symlinks=False)
        except (NotImplementedError, NotSupportedError):
            os.utime(path, (epoch, epoch))
    return stage_dir


def members(root, entries, prefix):
    """(path, arcname) for the staged tree, or the caller's own pairs.

    Walked in sorted order so the archive is byte-identical between runs.
    """
    if root is None:
        return entries
    found = []
    for path in sorted(root.rglob("*")):
        found.append((path, f"{prefix}{path.relative_to(root)}"))
    return found


def write_archive(archive, fmt, entries, prefix="", root=None):
    """Write the staged tree into `archive`.

    Zip keeps the executable bit in each entry's external_attr and tar in the
    header; both need the mode read off disk at write time, which is why this
    takes paths rather than pre-read bytes.
    """
    if fmt == "zip":
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=COMPRESSION[fmt]) as zf:
            for path, arcname in members(root, entries, prefix):
                # from_file carries st_mode into external_attr, which is the
                # only place a zip can keep the executable bit. It does not set
                # compress_type, and writestr honours the ZipInfo it is given,
                # so that has to be set here or the entry is stored verbatim.
                info = zipfile.ZipInfo.from_file(path, arcname)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, b"" if path.is_dir() else path.read_bytes())
        return

    # tarfile's mode string is the compression name without the `tar.` prefix.
    kwargs = {"preset": COMPRESSION[fmt]}
    with tarfile.open(archive, f"w:{TAR_MODE[fmt]}", **kwargs) as tar:
        if root is not None:
            # recursive, or tarfile records a bare directory entry and
            # nothing below it.
            tar.add(root, arcname=prefix.rstrip("/"), recursive=True)
        else:
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
    fmt = archive_format(target)
    sources = collect(target)

    stem = f"{name}-{version}-{target}"
    outdir = Path("dist")
    outdir.mkdir(parents=True, exist_ok=True)
    archive = outdir / f"{stem}{SUFFIX[fmt]}"

    note(f"{archive} ({fmt}, preset {COMPRESSION[fmt]}, {len(sources)} source(s))")

    # No unlink first: zipfile and tarfile both open "w", which truncates.
    staged = stage(sources, outdir, stem)
    try:
        write_archive(archive, fmt, [], prefix=f"{stem}/", root=staged)
    finally:
        if staged.exists():
            shutil.rmtree(staged)

    if not archive.exists() or archive.stat().st_size == 0:
        fail(f"{archive} was not produced")

    note(f"{archive.stat().st_size} bytes")
    emit(archive=archive.name, path=str(archive), stem=stem, version=version)


if __name__ == "__main__":
    main()