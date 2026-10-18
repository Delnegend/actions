# actions

Shared composite actions for the release pipeline used across
[Delnegend](https://github.com/Delnegend)'s projects.

One implementation of the release decision logic, pinned by SHA in every
consumer, so a fix lands once instead of in ten copies.

## Actions

### `resolve-release`

Decides what a release run should do, then does it. Runs inside the caller's
`prepare` job, against the checkout the caller already made, and reports what
the build job should do.

```yaml
- name: Bump, tag, and push
  id: resolve
  uses: Delnegend/actions/resolve-release@<sha> # v1
  with:
    ref: ${{ inputs.ref }}
    dry-run: ${{ inputs.dry-run }}
    gate-sha: ${{ github.sha }}
    semver-bump: ${{ steps.semver.outputs.bump }}
    semver-current: ${{ steps.semver.outputs.current }}
    semver-next: ${{ steps.semver.outputs.next }}
    semver-next-strict: ${{ steps.semver.outputs.nextStrict }}
```

The job then forwards the outputs:

```yaml
outputs:
  ref: ${{ steps.resolve.outputs.ref }}
  version: ${{ steps.resolve.outputs.version }}
  publish: ${{ steps.resolve.outputs.publish }}
  skip: ${{ steps.resolve.outputs.skip }}
```

#### Dispatch modes

`ref` selects one of four behaviours. An unrecognised value fails the run
rather than quietly doing nothing.

| `ref` | Behaviour | `publish` |
|---|---|---|
| empty | bump, tag, push, build, publish | `true` |
| commit SHA (7–64 hex) | test-build that commit, no release | `false` |
| `vX.Y.Z` | rebuild and publish an existing tag | `true` |
| `dry-run: true` | print what would happen, mutate nothing | `false` |

#### Outputs

| Output | Meaning |
|---|---|
| `ref` | what the build job checks out — a tag, or a SHA for a test-build |
| `version` | version being released, no `v` prefix |
| `publish` | `true` when this run should create a release |
| `skip` | `true` when there is nothing to build |

#### What it guarantees

- **Nothing ungated is released.** Shipping refuses if `HEAD` no longer matches
  `gate-sha`, so a commit that landed while the gate ran is caught instead of
  being published unreviewed.
- **A dry run never mutates**, on any dispatch path.
- **Nothing is published twice.** The calculated version must sort strictly
  after the latest tag.
- **A lost tag is recoverable.** If an earlier run pushed its bump commit and
  died before tagging, that commit is not conventional and reads as "nothing to
  release" — but the manifest is ahead of the latest tag, so the tag is what's
  missing. The action tags the stranded commit instead of skipping it.

#### Inputs

| Input | Default | Purpose |
|---|---|---|
| `ref` | `""` | dispatch ref — empty, SHA, or tag |
| `dry-run` | `false` | preview without mutating |
| `gate-sha` | `""` | commit the CI gate approved |
| `manifest-path` | `Cargo.toml` | source of truth for recovery; empty disables it |
| `bump-command` | `just bump` | rewrites version files, new version as `$1`; empty means manifest-less |
| `semver-bump` | `""` | bump type from `semver-action` |
| `semver-current` | `""` | current version |
| `semver-next` | `""` | next version, with `v` |
| `semver-next-strict` | `""` | next version, without `v` |

#### Manifest-less projects

Where the version lives in the git tag alone, set `bump-command: ''` and
`manifest-path: ''`. The action then tags `HEAD` directly and commits nothing:

```yaml
  with:
    bump-command: ''
    manifest-path: ''
```

#### Requirements

The caller must have checked out with `fetch-depth: 0` and
`persist-credentials: true` — the action reads the full tag history and pushes
the commit and tag using the checkout's credentials. It needs `contents: write`.

## Versioning

Tag releases `v1`, `v2`, … Consumers pin a full commit SHA with the tag in a
trailing comment, matching the pinning used for every other action:

```yaml
uses: Delnegend/actions/resolve-release@e5d31409a69d06622f1647914a5c85bc755f6b3 # v1
```

## License

MIT — see [LICENSE](LICENSE).