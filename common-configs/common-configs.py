#!/usr/bin/env python3
"""Check the declared configuration of tracked Rust and Bun projects."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

# Deny these Clippy groups at priority -1 or lower.
CLIPPY_DENIED_GROUPS = (
    'pedantic',
    'nursery',
)

# Deny or forbid these individual checks at a higher priority than both groups.
CLIPPY_DENIED_LINTS = (
    'unwrap_used',
    'expect_used',
    'indexing_slicing',
    'arithmetic_side_effects',
    'unreachable',
    'unimplemented',
    'unchecked_time_subtraction',
    'todo',
    'string_slice',
    'panic_in_result_fn',
    'panic',
    'exit',
    'as_conversions',
)

# Bun uses seconds for its package release age: 14 days.
BUN_MINIMUM_RELEASE_AGE = 1209600
REQUIREMENTS = {
    'clippy.toml': {
        ('allow-unwrap-in-tests',): True,
        ('allow-expect-in-tests',): True,
        ('allow-panic-in-tests',): True,
        ('allow-indexing-slicing-in-tests',): True,
    },
    '.cargo/config.toml': {
        ('registry', 'global-min-publish-age'): '14 days',
        ('resolver', 'incompatible-publish-age'): 'deny',
    },
}
MISSING = object()


def escape(value, property_value=False):
    text = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    if property_value:
        text = text.replace(':', '%3A').replace(',', '%2C')
    return text


class Scanner:
    def __init__(self, root):
        self.root = root.resolve()
        self.errors = 0
        self.manifests = {}

    def error(self, path, message):
        self.errors += 1
        try:
            name = path.relative_to(self.root).as_posix()
        except ValueError:
            name = str(path)
        print(f'::error file={escape(name, True)}::{escape(message)}')

    def tracked(self):
        result = subprocess.run(['git', '-C', str(self.root), 'ls-files', '--stage', '-z'],
                                check=True, stdout=subprocess.PIPE)
        manifests = set()
        sources = False
        files = set()
        for entry in result.stdout.split(b'\0'):
            if not entry:
                continue
            info, filename = entry.split(b'\t', 1)
            mode, _, stage = info.split(b' ')
            if mode == b'160000':
                continue
            path = self.root / os.fsdecode(filename)
            files.add(path)
            if path.name == 'Cargo.toml':
                manifests.add(path)
                if mode == b'120000' or path.is_symlink():
                    self.error(path, 'Cargo.toml: symlink manifests are not allowed')
            elif path.suffix == '.rs':
                sources = True
        return manifests, sources, files

    def scan(self):
        tracked, sources, files = self.tracked()
        self.check_bun(files)
        if not tracked:
            if sources:
                self.error(self.root, 'Cargo.toml: Rust source is tracked but no manifest is tracked')
            else:
                print('::notice::No tracked Rust manifests or source files; skipping Rust configuration scan')
            return
        for name, entries in REQUIREMENTS.items():
            path = self.root / name
            if path not in files or not path.is_file():
                self.error(path, f'{name}: expected a tracked file')
                continue
            try:
                with path.open('rb') as file:
                    config = tomllib.load(file)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                self.error(path, f'{name}: cannot read or parse configuration: {exc}')
                continue
            for keys, expected in entries.items():
                actual = config
                for key in keys:
                    actual = actual.get(key, MISSING) if isinstance(actual, dict) else MISSING
                if type(actual) is not type(expected) or actual != expected:
                    display = '<missing>' if actual is MISSING else repr(actual)
                    self.error(path, f'{".".join(keys)}: actual {display}; expected {expected!r}')
        for path in sorted(tracked):
            if path.is_symlink():
                continue
            try:
                with path.open('rb') as file:
                    self.manifests[path] = tomllib.load(file)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                self.error(path, f'Cargo.toml: cannot read or parse manifest: {exc}')

        covered = set()
        with tempfile.TemporaryDirectory(prefix='common-configs-cargo-') as home:
            env = os.environ.copy()
            env.update(CARGO_HOME=home, CARGO_NET_OFFLINE='true', RUSTUP_TOOLCHAIN='stable')
            for path in sorted(self.manifests):
                if path in covered:
                    continue
                result = subprocess.run(
                    ['cargo', 'metadata', '--offline', '--no-deps', '--format-version', '1',
                     '--manifest-path', str(path)],
                    cwd=Path(__file__).resolve().parent, env=env, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode:
                    self.error(path, f'cargo metadata failed: {result.stderr.strip()}')
                    continue
                try:
                    metadata = json.loads(result.stdout)
                    root = Path(metadata['workspace_root']).resolve() / 'Cargo.toml'
                    ids = set(metadata['workspace_members'])
                    members = [Path(p['manifest_path']).resolve() for p in metadata['packages'] if p['id'] in ids]
                    if len(members) != len(ids):
                        raise ValueError('metadata omitted workspace member packages')
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    self.error(path, f'cargo metadata returned invalid workspace data: {exc}')
                    continue
                valid = True
                for member in [root, *members]:
                    if not member.is_relative_to(self.root):
                        self.error(path, f'workspace manifest outside checkout: {member}')
                        valid = False
                    elif member not in tracked:
                        self.error(member, 'Cargo.toml: workspace root or member is not tracked')
                        valid = False
                    elif member not in self.manifests:
                        valid = False
                covered.update([root, *members])
                if valid:
                    self.check_workspace(root, members)

    def check_bun(self, files):
        lockfiles = sorted(path for path in files if path.name in ('bun.lock', 'bun.lockb'))
        for lockfile in lockfiles:
            path = lockfile.parent / 'bunfig.toml'
            if path not in files or not path.is_file():
                self.error(path, 'install.minimumReleaseAge: expected a tracked bunfig.toml beside the Bun lockfile')
                continue
            try:
                with path.open('rb') as file:
                    config = tomllib.load(file)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                self.error(path, f'bunfig.toml: cannot read or parse configuration: {exc}')
                continue
            install = config.get('install', {})
            age = install.get('minimumReleaseAge', MISSING) if isinstance(install, dict) else MISSING
            if type(age) is not int or age < BUN_MINIMUM_RELEASE_AGE:
                actual = '<missing>' if age is MISSING else repr(age)
                self.error(path, f'install.minimumReleaseAge: actual {actual}; expected integer >= {BUN_MINIMUM_RELEASE_AGE} seconds')
            exclusions = install.get('minimumReleaseAgeExcludes', []) if isinstance(install, dict) else []
            if exclusions:
                print(f'::notice file={escape(path.relative_to(self.root).as_posix(), True)}::'
                      f'{escape(f"install.minimumReleaseAgeExcludes: {exclusions!r}")}')

    def check_workspace(self, root, members):
        manifest = self.manifests[root]
        profile = manifest.get('profile', {}).get('release', {})
        for key, allowed in (('opt-level', (3,)), ('lto', ('thin',)),
                             ('codegen-units', (1,)), ('strip', (True, 'symbols'))):
            value = profile.get(key, MISSING)
            if key == 'opt-level' and value is MISSING:
                continue
            if not any(type(value) is type(expected) and value == expected for expected in allowed):
                actual = '<missing>' if value is MISSING else repr(value)
                self.error(root, f'profile.release.{key}: actual {actual}; expected {allowed!r}')

        for member in members:
            data = self.manifests[member]
            lints = data.get('lints', {})
            if lints.get('workspace') is True:
                lint_path = root
                prefix = 'workspace.lints.clippy'
                clippy = manifest.get('workspace', {}).get('lints', {}).get('clippy', {})
                if len(lints) != 1:
                    self.error(member, 'lints.workspace: inherited lints conflict with local lint entries')
            else:
                lint_path = member
                prefix = 'lints.clippy'
                clippy = lints.get('clippy', {})
            priorities = {}
            for key in (*CLIPPY_DENIED_GROUPS, *CLIPPY_DENIED_LINTS):
                value = clippy.get(key, MISSING)
                level = value if isinstance(value, str) else value.get('level') if isinstance(value, dict) else None
                priority = value.get('priority', 0) if isinstance(value, dict) else 0
                valid_form = isinstance(value, str) or (isinstance(value, dict) and set(value) <= {'level', 'priority'})
                allowed_levels = ('deny',) if key in CLIPPY_DENIED_GROUPS else ('deny', 'forbid')
                valid_priority = type(priority) is int
                if not valid_form or level not in allowed_levels or not valid_priority or (key in CLIPPY_DENIED_GROUPS and priority > -1):
                    actual = '<missing>' if value is MISSING else repr(value)
                    expected = 'deny with integer priority <= -1' if key in CLIPPY_DENIED_GROUPS else 'deny or forbid with integer priority higher than both groups'
                    self.error(lint_path, f'{prefix}.{key}: actual {actual}; expected {expected}')
                else:
                    priorities[key] = priority
            for key in CLIPPY_DENIED_LINTS:
                if key in priorities and any(group in priorities and priorities[key] <= priorities[group] for group in CLIPPY_DENIED_GROUPS):
                    self.error(lint_path, f'{prefix}.{key}.priority: actual {priorities[key]}; expected higher than both group priorities')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    scanner = Scanner(Path(args.root))
    try:
        scanner.scan()
    except (OSError, subprocess.CalledProcessError) as exc:
        scanner.error(scanner.root, f'configuration scan failed: {exc}')
    return int(scanner.errors != 0)


if __name__ == '__main__':
    sys.exit(main())
