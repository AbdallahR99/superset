# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Package the compiled NxtBI chat extension in Superset's SUPX layout."""

# Packaging runs without installing the Superset Python application.
import json  # noqa: TID251
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent


def main() -> None:
    """Write an installable SUPX and unpacked local extension."""
    package = json.loads((ROOT / "extension.json").read_text(encoding="utf-8"))
    frontend_dist = ROOT / "frontend" / "dist"
    entries = sorted(frontend_dist.glob("remoteEntry.*.js"))
    if len(entries) != 1:
        raise SystemExit("Run npm run build in the extension frontend first.")

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    assets = dist / "frontend" / "dist"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(frontend_dist, assets)

    publisher, name = package["publisher"], package["name"]
    manifest = {
        key: package[key]
        for key in ("publisher", "name", "displayName", "version", "permissions")
    }
    manifest["frontend"] = {
        "remoteEntry": entries[0].name,
        "moduleFederationName": "nxtbi_aiCopilot",
    }
    (dist / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    bundle = ROOT / f"{publisher}.{name}-{package['version']}.supx"
    with ZipFile(bundle, "w", ZIP_DEFLATED) as archive:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(dist))
    print(f"Created {bundle}")


if __name__ == "__main__":
    main()
