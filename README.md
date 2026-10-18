<div align="center">

# actions

**Shared composite actions for Delnegend's release pipeline, pinned by SHA across ten projects so a release fix lands once instead of in ten copies.**

[![Release](https://img.shields.io/github/v/release/Delnegend/actions?style=flat-square)](https://github.com/Delnegend/actions/releases)
[![License](https://img.shields.io/github/license/Delnegend/actions?style=flat-square)](LICENSE)

</div>

---

## Quick Start

Reference the action by commit SHA, and forward the step outputs your build
job reads:

```yaml
- name: Bump, tag, and push
  id: resolve
  uses: Delnegend/actions/resolve-release@1299339be1f82a70f2580c26c82f5a6925b99dc4 # v1
  with:
    ref: ${{ inputs.ref }}
    dry-run: ${{ inputs.dry-run }}
    gate-sha: ${{ github.sha }}
    semver-bump: ${{ steps.semver.outputs.bump }}
    semver-current: ${{ steps.semver.outputs.current }}
    semver-next: ${{ steps.semver.outputs.next }}
    semver-next-strict: ${{ steps.semver.outputs.nextStrict }}
```

Pin a full commit SHA, never a tag — the same discipline the rest of the
pipeline uses. Resolve `v1` to its commit with `git rev-parse 'v1^{commit}'`.

## What's Inside

| Action | Purpose |
|---|---|
| [`resolve-release`](resolve-release/action.yml) | Decides what a release run does, then does it. |

## Highlights

- **Four dispatch modes, one step** — ship a new version, test-build a commit, rebuild an existing tag, or preview — selected by the `ref` input.
- **Never ships ungated code** — if the branch moves while CI runs, the release refuses rather than publishing a commit nothing checked.
- **A preview never mutates** — dry-run exits before any tag, commit, or push, on every path.
- **Recovers a lost tag** — a run that pushed its bump then died before tagging is completed, not silently skipped.

## Dispatch Modes

`ref` selects the behaviour. An unrecognised value fails the run rather than
quietly doing nothing.

| `ref` | Behaviour | `publish` |
|---|---|---|
| empty | bump, tag, push, build, publish | `true` |
| commit SHA (7–64 hex) | test-build that commit, no release | `false` |
| `vX.Y.Z` | rebuild and publish an existing tag | `true` |
| `dry-run: true` | print what would happen, mutate nothing | `false` |

## Configuration

Every input, output, and the manifest-less project variant:
**[`docs/configuration.md`](docs/configuration.md)**.

## Documentation

- **[Configuration](docs/configuration.md)** — full input and output reference.
- **[Development](docs/development.md)** — adding an action, testing it, versioning and pinning.

## License

[MIT](LICENSE)