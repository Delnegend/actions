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
  uses: Delnegend/actions/resolve-release@95ab222e3127d13ebbe6cf220f57254ce17beffe # v1
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

**Composite actions** run inside the caller's job and workspace.

| Action | Purpose |
|---|---|
| [`resolve-release`](resolve-release/action.yml) | Decides what a release run does, then does it. |
| [`package-artifact`](package-artifact/action.yml) | Stages, archives and uploads one build artifact under a consistent name. |
| [`publish-release`](publish-release/action.yml) | Downloads the build artifacts and publishes the GitHub release. |
| [`cargo-cooldown`](cargo-cooldown/action.yml) | Checks that the installed Cargo enforces the 14-day publish quarantine. |
| [`docker-build-push`](docker-build-push/action.yml) | Builds a container image with Buildx and pushes it, or loads it locally. |

**Reusable workflows** are called as a job, and each of their runs is a
separate set of status checks.

| Workflow | Purpose |
|---|---|
| [`reusable-auto-merge`](.github/workflows/reusable-auto-merge.yml) | Auto-merges dependency PRs, and optionally `release/` branches. |
| [`reusable-deps-update`](.github/workflows/reusable-deps-update.yml) | Opens weekly dependency-upgrade PRs behind the publish quarantine. |
| [`scan`](.github/workflows/scan.yml) | Runs the security scans (gitleaks, actionlint, semgrep, trivy, osv). |

## Highlights

- **Four dispatch modes, one step** — ship a new version, test-build a commit, rebuild an existing tag, or preview — selected by the `ref` input.
- **Never ships ungated code** — if the branch moves while CI runs, the release refuses rather than publishing a commit nothing checked.
- **A preview never mutates** — dry-run exits before any tag, commit, or push, on every path.
- **Recovers a lost tag** — a run that pushed its bump then died before tagging is completed, not silently skipped.
- **One archive name across every project** — `<name>-<version>-<target>.<ext>`, version-stamped so a formula or script can match it without hardcoding a target triple.
- **Format and layout are not call-site inputs** — zip for a Windows target, tar.xz otherwise, both at maximum effort, one directory, decided once in one place.
- **The executable bit survives the round trip** — `download-artifact` strips it, so it is recorded inside the archive rather than restored afterwards.
- **Reproducible** — timestamps are normalised, so rebuilding a tag produces byte-identical archives.
- **One scan bundle, opted out not in** — every repo runs gitleaks, actionlint, semgrep, trivy and osv; opting out names the exception instead of restating the rule.
- **One build-and-push shape** — two tags, zstd layers, gha or registry cache, decided once in `docker-build-push` instead of in four release workflows.

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

Every input, output, and the `just version` recipe contract:
**[`docs/configuration.md`](docs/configuration.md)**.

## Documentation

- **[Configuration](docs/configuration.md)** — full input and output reference.
- **[Development](docs/development.md)** — adding an action, testing it, versioning and pinning.

## License

[MIT](LICENSE)