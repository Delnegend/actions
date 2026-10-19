#!/usr/bin/env python3
"""Run the action test suites.

    ./test/run.py                # every suite
    ./test/run.py resolve-release # one suite

Exits non-zero if any case fails.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from harness import Results  # noqa: E402
import test_package_artifact  # noqa: E402
import test_resolve_release  # noqa: E402

SUITES = {
    "resolve-release": test_resolve_release.run,
    "package-artifact": test_package_artifact.run,
}


def main(argv: list) -> int:
    names = argv[1:] or list(SUITES)
    unknown = [name for name in names if name not in SUITES]
    if unknown:
        print(f"unknown action: {unknown[0]}", file=sys.stderr)
        return 2

    results = Results()
    for name in names:
        SUITES[name](results)
        print()

    print(f"passed={results.passed} failed={results.failed}")
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
