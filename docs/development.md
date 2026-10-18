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

## Testing

Composite action scripts are plain bash, so they can be exercised outside
Actions: write the `run:` block to a file and drive it with environment
variables against a throwaway git repository.

```bash
d="$(mktemp -d)"; git -C "$d" init -q
git -C "$d" config user.email t@t; git -C "$d" config user.name t
printf 'name = "x"\nversion = "1.2.3"\n' > "$d/Cargo.toml"
git -C "$d" add -A; git -C "$d" commit -qm init
git -C "$d" tag -a v1.2.3 -m r

(cd "$d" && GITHUB_OUTPUT="$d/out" \
  INPUT_REF= DRY_RUN=false GATE_SHA= MANIFEST_PATH=Cargo.toml \
  BUMP_COMMAND="just bump" BUMP= CURRENT=v1.2.3 NEXT= NEXT_STRICT= \
  bash resolve.sh)

cat "$d/out"   # ref / version / publish / skip
```

Assert on the four outputs and the exit status. Cover every dispatch mode, the
skip path, the recovery path, and each rejection case — the failure paths are
where release logic goes wrong.

Two traps worth knowing:

- `grep -c` exits non-zero when it finds nothing, so `n=$(grep -c x f || echo 0)`
  yields `"0\n0"`. Check the exit status instead.
- The fixtures must match what the action actually reads. A `Cargo.toml`
  written as JSON on one line will not match `grep -m1 '^version = '`.

## Linting

Actions are not covered by `just check`, so validate them explicitly:

```bash
actionlint resolve-release/action.yml
```

Every consuming project runs this in CI as the `Workflow lint (actionlint)`
job, which covers that project's workflows — not this repository's own files.

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