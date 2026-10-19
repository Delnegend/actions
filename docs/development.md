# Development Guide

## Adding an Action

One directory per action, containing an `action.yml` with
`runs.using: composite`. Composite actions run in the caller's job and
workspace, so they can read the checkout and push with its credentials — but
they cannot declare jobs, matrix strategies, or outputs of their own beyond
what individual steps write.

```yaml
name: my-action
description: What it does, in one sentence.

inputs:
  thing:
    description: What it controls.
    required: false
    default: ""

outputs:
  result:
    description: What it produces.
    value: ${{ steps.run.outputs.result }}

runs:
  using: composite
  steps:
    - id: run
      shell: bash
      env:
        THING: ${{ inputs.thing }}
      run: |
        set -euo pipefail
        echo "result=$THING" >> "$GITHUB_OUTPUT"
```

Whole jobs that every repo repeats (auto-merge, weekly upgrades) go in
`.github/workflows/reusable-*.yml` instead: one `workflow_call` workflow with
typed inputs, called as a job via `uses:`. Same pinning discipline — full SHA
with a `# vN` comment.

## Testing

`./test/run.py` drives each action's script against throwaway git
repositories with environment variables standing in for the action inputs.
Outputs are read from `$GITHUB_OUTPUT` exactly as the runner would. `CI` runs
it on every push and pull request.

```bash
./test/run.py                 # every suite
./test/run.py resolve-release # one suite
```

The suites are one file per action, over a shared harness:

```
test/
  run.py                  # entry point: run the suites, count the outcomes
  harness.py              # fixtures, subprocess driving, assertions
  test_resolve_release.py
  test_package_artifact.py
```

Run it locally before pushing — it needs python3 and git, and takes about a
minute. Each case sets up a repo with a bare `origin` and a stub `just`, so
the push paths are exercised for real rather than mocked: a case can assert
the tag actually landed on the remote.

Two things worth knowing, both hit while writing these tests:

- The fixtures must match what the action actually reads. A `Cargo.toml`
  written as JSON on one line will not match the version the action reads.
- A platform that behaves differently is simulated with a `sitecustomize.py`
  on `PYTHONPATH`, not by rewriting the action's source. Rewriting the source
  couples the test to the action's exact text, and the action then has to be
  edited to keep the test meaningful.

Mutate the action before trusting a green run — change the skip guard and
confirm the suite goes red. A test that cannot fail proves nothing. The
suites were checked against a broken skip guard, a broken archive name, a
dropped executable bit and a removed platform fallback, and each of those
turns the suite red.

## Linting

`just check` does not exist here — there is no toolchain. Two jobs cover it:

- **Workflow lint** runs `actionlint` over `.github/workflows/`, the same
  command the consuming projects run.
- **Tests** runs `./test/run.sh`, which is what actually verifies the actions.

actionlint cannot lint an `action.yml` on its own: it parses one as a
*workflow* and reports `"jobs" section is missing`. Its action-metadata checks
only fire when a workflow references the action through `uses:`. So it is
deliberately not pointed at `resolve-release/action.yml` — passing it would be
a guaranteed false failure.

## Versioning

Tag releases `v1`, `v2`, … Consumers pin a full commit SHA with the tag in a
trailing comment:

```yaml
uses: Delnegend/actions/resolve-release@<sha> # v1
```

A tag is a label, not a lock — resolve it with `git rev-parse 'v1^{commit}'`.
Pin by SHA so a moved tag cannot change what a release pipeline runs, and so
consumers opt in to upgrades deliberately.

After tagging:

```bash
gh release create v1 --title "v1" --notes "What landed."
```

## Rolling Out a Change

1. Commit and tag in this repository.
2. Resolve the tag to its commit SHA.
3. Update each consumer's workflow to the new SHA, one repo at a time.
4. Confirm with a `dry-run` dispatch per repo — it mutates nothing and prints
   the version it would release:

   ```bash
   gh workflow run release.yml -R Delnegend/<repo> -f dry-run=true
   ```

5. Then promote to a real release when ready.

A behavioural change and a repin do not have to ship together: land the fix on
`v1`, repin consumers when convenient, and cut `v2` only for a breaking input
or output change.