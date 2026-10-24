#!/usr/bin/env python3
"""Stage, archive, and upload build artifacts with consistent naming and layout.

Environment:
  SOURCE  Path to file or directory to package
  EXTRA   Optional space-separated additional paths to include
  NAME    Artifact base name (e.g. rsrpc)
  TARGET  Target triple (OS component selects format)
"""

import errno
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

# Fallback for runners without errno.NotSupportedError.
NotSupportedError = getattr(errno, "NotSupportedError", OSError)

# Target OS selects archive format: Windows gets zip; all others get tar.xz (-9 preset).
# Target triple field is matched by name because Windows triples include vendor fields.
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
    """.exe for Windows targets; empty otherwise."""
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
    """Copy sources into stem directory with normalised timestamps for reproducibility."""
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

    # Clamp to earliest zip timestamp (1980-01-01).
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or "0")
    epoch = max(epoch, ZIP_EPOCH)
    for path in sorted(stage_dir.rglob("*")) + [stage_dir]:
        try:
            # Stamp symlink itself; fall back when follow_symlinks is unsupported.
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
    """Write staged tree into archive preserving file modes."""
    if fmt == "zip":
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=COMPRESSION[fmt]) as zf:
            for path, arcname in members(root, entries, prefix):
                # from_file sets external_attr for permissions; compress_type must be explicit.
                info = zipfile.ZipInfo.from_file(path, arcname)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, b"" if path.is_dir() else path.read_bytes())
        return

    # Strip 'tar.' prefix for tarfile mode.
    kwargs = {"preset": COMPRESSION[fmt]}
    with tarfile.open(archive, f"w:{TAR_MODE[fmt]}", **kwargs) as tar:
        if root is not None:
            # Recursive add captures subdirectories.
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