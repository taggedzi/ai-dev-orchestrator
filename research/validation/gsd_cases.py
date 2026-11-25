"""Run bounded synthetic negative controls through the already-prepared GSD CLI."""

import argparse
import re
import shutil
import sys
from pathlib import Path

from .bundle import digest, inventory, load_json, verify, write
from .fixture import canonical
from .gsd_export import export
from .gsd_import import eligible_tasks, load_raw, normalize
from .os_install import rooted
from .store import Hold

PLAN1 = "planning/.planning/phases/01-validate-cli/01-01-PLAN.md"
PLAN2 = "planning/.planning/phases/01-validate-cli/01-02-PLAN.md"


def mutate(name, destination):
    if name == "cycle":
        path = destination / PLAN1
        text = path.read_text(encoding="utf-8").replace(
            "depends_on: []", 'depends_on: ["01-02"]', 1
        )
    else:
        path = destination / PLAN2
        text = path.read_text(encoding="utf-8")
        if name == "missing-target":
            text = text.replace('depends_on: ["01-01"]', 'depends_on: ["99-99"]', 1)
        elif name == "dropped-edge":
            text = text.replace('depends_on: ["01-01"]', "depends_on: []", 1)
        elif name == "malformed-plan":
            text = text.replace("</task>", "", 1)
        else:
            raise Hold("unknown negative control")
    path.write_bytes(text.encode())


def run(package, bundle, manifest_hash, output, approval):
    if not approval:
        raise Hold("read-only negative-control approval required")
    package, bundle, output = rooted(package), rooted(bundle), rooted(output)
    source_paths = [
        Path(__file__),
        Path(__file__).with_name("gsd_import.py"),
        Path(__file__).with_name("gsd_export.py"),
    ]
    source_pins = {path.name: digest(path.read_bytes()) for path in source_paths}
    manifest = verify(bundle, expected_digest=manifest_hash)
    output.mkdir(parents=True, exist_ok=False)
    positive_root = output / "positive"
    positive_query = export(package, bundle, manifest_hash, positive_root, approval)
    positive = normalize(
        (positive_root / "inspect.stdout").read_bytes(),
        load_raw(positive_root / "planning-input"),
    )
    if eligible_tasks(positive, []) != ["T-01"] or eligible_tasks(
        positive, ["T-01"]
    ) != ["T-02"]:
        raise Hold("positive import/readiness control failed")
    write(positive_root, "normalized-plan.json", canonical(positive) + b"\n")
    rows = []
    for name in ("missing-target", "cycle", "dropped-edge", "malformed-plan"):
        case = output / name
        changed = case / "bundle"
        shutil.copytree(bundle, changed, symlinks=False)
        mutate(name, changed)
        variant = dict(manifest)
        variant["files"] = inventory(changed, exclude_manifest=True)
        changed_paths = sorted(
            path
            for path in manifest["files"]
            if manifest["files"][path] != variant["files"].get(path)
        )
        if changed_paths != [PLAN1 if name == "cycle" else PLAN2] or set(
            variant["files"]
        ) != set(manifest["files"]):
            raise Hold("negative case changed more than its one intended PLAN")
        variant["variant"] = {"kind": name, "baseline_manifest_sha256": manifest_hash}
        write(changed, "manifest.json", canonical(variant) + b"\n")
        freeze = digest((changed / "manifest.json").read_bytes())
        root = case / "query"
        try:
            query = export(package, changed, freeze, root, approval)
        except Hold as error:
            observation = {
                "case": name,
                "classification": "inconclusive producer hold",
                "error": str(error),
                "bundle_sha256": freeze,
            }
            if name == "cycle" and (root / "index.stderr").is_file():
                native_error = (root / "index.stderr").read_text(encoding="utf-8")
                events = load_json((root / "query-observations.json").read_bytes())
                before = load_json((root / "planning-before.json").read_bytes())
                after = load_json((root / "planning-after.json").read_bytes())
                if (
                    events[-1]["name"] == "index"
                    and events[-1]["exit"] == 1
                    and all(row["exit"] == 0 for row in events[:-1])
                    and before == after
                    and re.search(
                        r"depends_on cycle detected.*01-01.*01-02", native_error
                    )
                ):
                    try:
                        normalize(
                            (root / "inspect.stdout").read_bytes(),
                            load_raw(root / "planning-input"),
                        )
                    except Hold as importer_error:
                        if str(importer_error) == "dependency cycle":
                            observation.update(
                                classification="measured native index refusal; importer refused",
                                native_error=native_error.strip(),
                                importer_error=str(importer_error),
                                planning_unchanged=True,
                                eligible=[],
                                snapshot_sha256=digest(
                                    (root / "inspect.stdout").read_bytes()
                                ),
                            )
            rows.append(observation)
            continue
        raw = load_raw(root / "planning-input")
        try:
            normalized = normalize((root / "inspect.stdout").read_bytes(), raw)
        except Hold as error:
            rows.append(
                {
                    "case": name,
                    "classification": "measured native export; importer refused",
                    "error": str(error),
                    "bundle_sha256": freeze,
                    "snapshot_sha256": query["snapshot_sha256"],
                    "planning_unchanged": query["planning_files_unchanged"],
                    "eligible": [],
                }
            )
        else:
            rows.append(
                {
                    "case": name,
                    "classification": "failure: unsafe fixture import accepted",
                    "eligible": eligible_tasks(normalized, []),
                    "bundle_sha256": freeze,
                }
            )
    unsupported = load_json((positive_root / "inspect.stdout").read_bytes())
    unsupported["schema_version"] = 2
    unsupported_raw = canonical(unsupported) + b"\n"
    write(output, "unsupported-schema.json", unsupported_raw)
    try:
        normalize(unsupported_raw, load_raw(positive_root / "planning-input"))
    except Hold as error:
        rows.append(
            {
                "case": "unsupported-schema",
                "classification": "consumer-only schema mutation refused",
                "error": str(error),
                "snapshot_sha256": digest(unsupported_raw),
                "eligible": [],
            }
        )
    else:
        rows.append(
            {
                "case": "unsupported-schema",
                "classification": "failure: unsupported schema accepted",
            }
        )
    if source_pins != {path.name: digest(path.read_bytes()) for path in source_paths}:
        raise Hold("case-control sources changed during execution")
    result = {
        "schema_version": 1,
        "classification": "local planning import controls; no task execution or product scheduler qualification",
        "baseline_manifest_sha256": manifest_hash,
        "positive_snapshot_sha256": positive_query["snapshot_sha256"],
        "source_sha256": source_pins,
        "positive_readiness": {
            "initial": eligible_tasks(positive, []),
            "after_T01_acceptance": eligible_tasks(positive, ["T-01"]),
        },
        "cases": rows,
        "pass": all(
            row["classification"]
            in {
                "measured native export; importer refused",
                "measured native index refusal; importer refused",
                "consumer-only schema mutation refused",
            }
            for row in rows
        ),
    }
    write(output, "result.json", canonical(result) + b"\n")
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    result = run(
        args.package, args.bundle, args.manifest_sha256, args.output, args.approval
    )
    print(canonical(result).decode())
    if not result["pass"]:
        raise Hold("negative controls contain failure or inconclusive evidence")


if __name__ == "__main__":
    main()
