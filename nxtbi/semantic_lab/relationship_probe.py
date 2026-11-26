# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Compare composite inclusion with FK evidence on synthetic, non-null keys.

Run from this directory on a supported platform:
    uv run --no-project --with desbordante==2.5.0 python -B relationship_probe.py
"""

from __future__ import annotations

import csv
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

Key = tuple[str, str]


def check_relationship(
    directory: Path, child: tuple[Key, ...], parent: tuple[Key, ...]
) -> tuple[bool, int, int]:
    """Return inclusion, duplicate parent key count, and orphan child row count."""
    from desbordante import aind_verification

    paths = [directory / "child.csv", directory / "parent.csv"]
    for path, rows in zip(paths, (child, parent), strict=True):
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("site", "product"))
            writer.writerows(rows)

    verifier = aind_verification.algorithms.Default()
    verifier.load_data(tables=[(str(path), ",", True) for path in paths])
    verifier.execute(lhs_indices=[0, 1], rhs_indices=[0, 1])

    parent_counts = Counter(parent)
    duplicate_keys = sum(count > 1 for count in parent_counts.values())
    orphan_rows = sum(key not in parent_counts for key in child)
    return verifier.get_error() == 0, duplicate_keys, orphan_rows


def main() -> None:
    """Verify the expected gates on a minimal composite-key fixture."""
    parent = (("North", "A"), ("South", "A"), ("South", "B"))
    child = (("North", "A"), ("South", "B"), ("South", "B"))
    cases = (
        ("valid_composite", child, parent, (True, 0, 0)),
        ("duplicated_parent", child, (*parent, parent[0]), (True, 1, 0)),
        ("orphan_pair", (*child, ("North", "B")), parent, (False, 0, 1)),
    )
    print(f"Desbordante {version('desbordante')}")
    with TemporaryDirectory() as temp_dir:
        for name, child_rows, parent_rows, expected in cases:
            result = check_relationship(Path(temp_dir), child_rows, parent_rows)
            exact, duplicates, orphans = result
            accepted = exact and duplicates == 0 and orphans == 0
            print(
                f"{name} exact_inclusion={exact} duplicate_parent_keys={duplicates} "
                f"orphan_child_rows={orphans} fk_eligible={accepted}"
            )
            if result != expected:
                raise RuntimeError(f"{name}: expected {expected}, got {result}")


if __name__ == "__main__":
    main()
