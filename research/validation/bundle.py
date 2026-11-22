"""Reproduce Git objects directly, index all inputs, and detect changed bundles."""

import difflib
import hashlib
import json
import os
import stat
import zlib
from pathlib import Path, PurePosixPath

from .fixture import (
    PINS,
    POLICY,
    PROMPTS,
    SEED,
    T1,
    T2,
    TASKS,
    canonical,
    planning_files,
    sources,
)

ROOT = Path(__file__).resolve().parents[2]
SEED_OID = "187a824c8735c958b32b7d3c1f957d621d07226e"
SEED_TREE = "57be177b66a8ecf7bd6616b72ef0ebf08ddb9f50"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        data,
        object_pairs_hook=pairs,
        parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)),
    )


def safe_path(name):
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or any(p in ("", ".", "..") for p in name.split("/"))
    ):
        raise ValueError(f"unsafe path: {name}")
    return path


def write(root, name, data):
    path = root.joinpath(*safe_path(name).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


class Objects:
    def __init__(self, root):
        self.root = root

    def put(self, kind, data):
        raw = f"{kind} {len(data)}\0".encode() + data
        oid = hashlib.sha1(raw).hexdigest()
        write(self.root, f"objects/{oid[:2]}/{oid[2:]}", zlib.compress(raw))
        return oid

    def tree(self, files):
        nested = {}
        for name, value in files.items():
            parts = safe_path(name).parts
            node = nested
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

        def emit(node):
            entries = []
            for name, value in node.items():
                directory = isinstance(value, dict)
                oid = emit(value) if directory else self.put("blob", value.encode())
                entries.append(
                    (
                        name + ("/" if directory else ""),
                        ("40000" if directory else "100644").encode()
                        + b" "
                        + name.encode()
                        + b"\0"
                        + bytes.fromhex(oid),
                    )
                )
            return self.put("tree", b"".join(data for _, data in sorted(entries)))

        return emit(nested)

    def commit(self, files, parents, second, message):
        tree = self.tree(files)
        identity = f"Fixture <fixture@example.invalid> {1767225600 + second} +0000"
        raw = f"tree {tree}\n" + "".join(f"parent {parent}\n" for parent in parents)
        raw += f"author {identity}\ncommitter {identity}\n\n{message}\n"
        return {
            "oid": self.put("commit", raw.encode()),
            "tree": tree,
            "parents": parents,
            "timestamp": 1767225600 + second,
            "message": message,
        }


def inventory(root, exclude_manifest=False):
    result = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"link/reparse point: {path}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"nonregular input: {path}")
        name = path.relative_to(root).as_posix()
        safe_path(name)
        if exclude_manifest and name == "manifest.json":
            continue
        if metadata.st_size > 1024**2:
            raise ValueError(f"oversized input: {name}")
        result[name] = {
            "bytes": metadata.st_size,
            "sha256": digest(path.read_bytes()),
            "mode": "100755"
            if os.name != "nt" and metadata.st_mode & 0o111
            else "100644",
        }
    return result


def attach_planning_export(root, export_root, expected_snapshot_hash):
    from .gsd_import import normalize

    export_root = Path(export_root)
    snapshot = (export_root / "inspect.stdout").read_bytes()
    if digest(snapshot) != expected_snapshot_hash:
        raise ValueError("GSD snapshot differs from its external freeze digest")
    receipt = load_json((export_root / "result.json").read_bytes())
    if (
        receipt.get("gsd_version") != PINS["gsd"]["version"]
        or receipt.get("gsd_commit") != PINS["gsd"]["commit"]
        or receipt.get("snapshot_sha256") != expected_snapshot_hash
        or not all(
            receipt.get(key) is True
            for key in [
                "planning_files_unchanged",
                "git_metadata_unchanged",
                "tool_package_unchanged",
                "repeat_bytes_equal",
            ]
        )
    ):
        raise ValueError("GSD export lacks the required read-only provenance")
    project = export_root / "planning-input"
    before = load_json((export_root / "planning-before.json").read_bytes())
    if before != load_json(
        (export_root / "planning-after.json").read_bytes()
    ) or before != inventory(project):
        raise ValueError("GSD source planning/Git state changed")
    raw = {}
    for name in planning_files():
        raw[name] = (project / name).read_bytes()
        if raw[name] != (root / "planning" / name).read_bytes():
            raise ValueError("GSD export refers to different raw planning inputs")
    if {name for name in before if name.startswith(".planning/")} != set(raw):
        raise ValueError("GSD source has unexpected planning inputs")
    expected_queries = ["identity", "context", "inspect", "index", "inspect-repeat"]
    if [row["name"] for row in receipt["queries"]] != expected_queries:
        raise ValueError("GSD query provenance incomplete")
    for row in receipt["queries"]:
        if row["exit"] != 0:
            raise ValueError("GSD query failed")
        for suffix in ("stdout", "stderr"):
            if (
                digest((export_root / (row["name"] + "." + suffix)).read_bytes())
                != row[suffix + "_sha256"]
            ):
                raise ValueError("GSD query evidence bytes changed")
    if snapshot != (export_root / "inspect-repeat.stdout").read_bytes():
        raise ValueError("GSD repeat evidence differs")
    normalized = canonical(normalize(snapshot, raw)) + b"\n"
    write(root, "planning/native-snapshot.json", snapshot)
    write(
        root,
        "planning/native-export-receipt.json",
        (export_root / "result.json").read_bytes(),
    )
    write(root, "planning/import-probe.json", normalized)
    return {
        "snapshot_sha256": expected_snapshot_hash,
        "schema_version": 1,
        "source_bundle_sha256": receipt["bundle_sha256"],
        "source_planning_commit": receipt["planning_commit"]["oid"],
        "import_probe_sha256": digest(normalized),
        "classification": "measured GSD export plus fixture-only import probe; product integration remains open",
    }


def build(destination, gsd_export=None, gsd_snapshot_hash=None):
    if bool(gsd_export) != bool(gsd_snapshot_hash):
        raise ValueError(
            "GSD attachment requires both export root and external snapshot digest"
        )
    root = Path(destination).absolute()
    # Exclusive creation also prevents accidental replacement of a prior freeze.
    root.mkdir(parents=True, exist_ok=False)
    trees = sources()
    objects = Objects(root / "git")
    records = {}
    recipes = [
        ("S0", [], 0, "Seed M-CLI1"),
        ("C1", ["S0"], 1, "Implement T-01"),
        ("C2", ["C1"], 2, "Implement T-02"),
        ("B1-rejected", ["S0"], 1, "Rejected T-01 mixed blank"),
        ("C-D", ["S0"], 1, "Implement T-01 stateful variant"),
        ("H-D", ["S0"], 3, "Maintain name policy"),
        ("I-D", ["H-D", "C-D"], 4, "Integrate stateful variant"),
        ("I-D-corrected", ["H-D"], 5, "Correct T-01 after integration regression"),
    ]
    for name, parents, second, message in recipes:
        files = trees[name]
        records[name] = objects.commit(
            files, [records[parent]["oid"] for parent in parents], second, message
        )
        for path, content in files.items():
            write(root, f"sources/{name}/{path}", content)
        write(root, f"git/refs/fixture/{name}", records[name]["oid"] + "\n")
    for name, base in (
        ("C1", "S0"),
        ("C2", "C1"),
        ("B1-rejected", "S0"),
        ("C-D", "S0"),
        ("H-D", "S0"),
        ("I-D-corrected", "H-D"),
    ):
        patch = ""
        for path in sorted(set(trees[name]) | set(trees[base])):
            old, new = trees[base].get(path, ""), trees[name].get(path, "")
            if old != new:
                patch += "".join(
                    difflib.unified_diff(
                        old.splitlines(True),
                        new.splitlines(True),
                        fromfile="a/" + path if path in trees[base] else "/dev/null",
                        tofile="b/" + path,
                    )
                )
        write(root, f"patches/{name}.patch", patch)
    if records["S0"]["oid"] != SEED_OID or records["S0"]["tree"] != SEED_TREE:
        raise ValueError("seed differs from M1-10")
    write(root, "git/HEAD", "ref: refs/heads/milestone\n")
    write(root, "git/refs/heads/milestone", SEED_OID + "\n")
    write(
        root,
        "git/config",
        "[core]\n\trepositoryformatversion = 0\n\tbare = true\n\tlogallrefupdates = false\n",
    )
    for path, content in planning_files().items():
        write(root, "planning/" + path, content)
    plan = {
        "format": "fixture-normalized-plan-v1",
        "milestone": "M-CLI1",
        "revision": "PR-01",
        "baseline": SEED_OID,
        "tasks": TASKS,
        "provenance": "coordinator-authored fixture expectation; not a GSD CLI export",
    }
    write(root, "planning/expected-plan.json", canonical(plan) + b"\n")
    for name, prompt in PROMPTS.items():
        write(root, f"prompts/{name}.txt", prompt)
    for name, content in {"policy": POLICY, "pins": PINS}.items():
        write(root, name + ".json", canonical(content) + b"\n")
    # A Linux payload with no Git or network operations. The tool schema remains a deployment gate.
    for task, additions in (("T-01", T1), ("T-02", T2)):
        payload = "from pathlib import Path\n"
        for path, text in additions.items():
            payload += f"p = Path({path!r})\np.parent.mkdir(parents=True, exist_ok=True)\np.write_bytes({text.encode()!r})\n"
        payload += "import subprocess, sys\n"
        payload += f"result = subprocess.run(['node', '--test', 'test/{'validate' if task == 'T-01' else 'cli'}.test.js'], check=False, timeout=30)\nsys.exit(result.returncode)\n"
        write(root, f"payloads/{task}.py", payload)
    probe = ROOT / "research/fixtures/executor-recovery-probe.py"
    write(root, "probes/executor-recovery-probe.py", probe.read_bytes())
    # Copy harness source into the bundle so its version is part of the freeze.
    for path in sorted(Path(__file__).parent.iterdir()):
        if path.suffix in (".py", ".md", ".ps1") or path.name in (
            "provisioning-plan.json",
            "preparation-evidence.json",
            "provisioning-evidence.json",
            "os-install-evidence.json",
            "first-boot-evidence.json",
            "offline-inspection-evidence.json",
            "boot-diagnostic-evidence.json",
            "gsd-export-evidence.json",
            "runtime-inputs.json",
            "runtime-image-evidence.json",
            "image-build-inputs.json",
            "image-build-evidence.json",
            "control-schema-evidence.json",
            "control-request-example.json",
            "guard-provisioning-plan.json",
            "guard-network-inputs.json",
            "guard-preparation-evidence.json",
            "guard-package-inputs.json",
            "guard-package-evidence.json",
            "os-update-inputs.json",
            "os-update-evidence.json",
            "os-update-artifact-evidence.json",
            "resolved-tool-evidence.json",
            "token-fit-evidence.json",
            "wire-input-evidence.json",
            "phase-policy-evidence.json",
            "phase-handoff-review-evidence.json",
            "engine-metadata-evidence.json",
            "engine-inputs.json",
            "engine-resolution-evidence.json",
            "engine-artifact-evidence.json",
            "MinimalAgentServer.Dockerfile",
        ):
            write(root, "harness/research/validation/" + path.name, path.read_bytes())
    write(
        root, "harness/research/fixtures/executor-recovery-probe.py", probe.read_bytes()
    )
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        write(root, "harness/tests/" + path.name, path.read_bytes())
    for path in sorted((ROOT / "tests/fixtures").glob("*.json")):
        write(root, "harness/tests/fixtures/" + path.name, path.read_bytes())
    for path in sorted((ROOT / "docs/decisions").glob("*.md")):
        write(root, "harness/docs/decisions/" + path.name, path.read_bytes())
    for directory in ("docs", "research"):
        for path in sorted((ROOT / directory).glob("*.md")):
            write(
                root, "harness/" + path.relative_to(ROOT).as_posix(), path.read_bytes()
            )
    for name in ("README.md", "AGENTS.md"):
        write(root, "harness/" + name, (ROOT / name).read_bytes())
    corpus = reviewer_corpus(trees)
    for label, files in corpus.items():
        for path, content in files["files"].items():
            write(root, f"review-corpus/{label}/{path}", content)
        base = "S0" if files["task"] == "T-01" else "C1"
        files["subject"] = objects.commit(
            files["files"], [records[base]["oid"]], 10, "Review candidate"
        )
        write(root, f"git/refs/fixture/{label}", files["subject"]["oid"] + "\n")
    write(
        root,
        "review-corpus/adjudication.json",
        canonical(
            {
                name: {k: v for k, v in row.items() if k != "files"}
                for name, row in corpus.items()
            }
        )
        + b"\n",
    )
    write(root, "objects.json", canonical(records) + b"\n")
    write(
        root,
        "scripts/expected-turns.json",
        canonical(
            {
                "status": "tool-neutral expectations; freeze native envelopes after schema qualification",
                "model": "fixture/model-v1",
                "baseline_submissions": [
                    {
                        "ordinal": n,
                        "task": task,
                        "role": role,
                        "simulated_settlement": amount,
                        "response_expectation": (
                            f"terminal: python3 -I /fixture/payloads/{task}.py in /workspace/project"
                            if role == "edit"
                            else "native finish: approved paths and observed test exit"
                            if role == "finish"
                            else "separate scripted review receipt bound to independent criterion observations"
                        ),
                    }
                    for n, (task, role, amount) in enumerate(
                        [
                            (task, role, amount)
                            for task in ("T-01", "T-02")
                            for role, amount in (
                                ("edit", 120000),
                                ("finish", 20000),
                                ("review", 40000),
                            )
                        ],
                        1,
                    )
                ],
            }
        )
        + b"\n",
    )
    write(
        root,
        "review-rubric.json",
        canonical(
            {
                "id": "m1-08-rubric-v1",
                "criteria": [
                    "correctness",
                    "maintainability",
                    "tests",
                    "scope",
                    "architectural-fit",
                ],
                "blocking": ["critical", "major"],
                "pass_requires": "all criteria satisfied with independent evidence; zero open blocking findings",
                "missing_evidence": "inconclusive",
                "finding_fields": [
                    "criterion",
                    "severity",
                    "subject_oid",
                    "location",
                    "reproducer",
                    "expected",
                    "actual",
                    "impact",
                ],
                "special_probes": {
                    "T-01": "mixed ECMAScript whitespace",
                    "T-02": "validator substitution plus CLI exit and streams",
                },
            }
        )
        + b"\n",
    )
    planning_export = (
        attach_planning_export(root, gsd_export, gsd_snapshot_hash)
        if gsd_export
        else None
    )
    manifest = {
        "schema_version": 1,
        "fixture": "M-CLI1",
        "status": "prepared-not-approved",
        "serialization": "UTF-8; sorted compact JSON keys; stable arrays; integer money; LF",
        "files": inventory(root, exclude_manifest=True),
        "objects": records,
        "open_gates": [
            "product ingestion/acceptance integration for the measured GSD fixture export"
            if planning_export
            else "actual pinned GSD schema-1 export and import comparison",
            "Linux target/image/toolchain digests and isolation measurements",
            "deployed OpenHands prompts/tool schemas and exact Chat transcripts",
            "independent host observer and hypervisor stop/reap qualification",
            "frozen deployment approval and scenario run approval",
            "blinded reviewer adjudication and measured executor/gateway cases",
        ],
    }
    if planning_export:
        manifest["planning_export"] = planning_export
    write(root, "manifest.json", canonical(manifest) + b"\n")
    return manifest


def blind_packets(bundle, destination, seed):
    """Split reviewer inputs from the trusted labels; freeze seed before review."""
    import random

    bundle = Path(bundle)
    verify(bundle)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    labels = load_json((bundle / "review-corpus/adjudication.json").read_bytes())
    order = list(labels)
    random.Random(seed).shuffle(order)
    mapping = {}
    for number, label in enumerate(order, 1):
        packet = f"R{number:02d}"
        source = bundle / "review-corpus" / label
        for name in inventory(source):
            write(root, f"packets/{packet}/source/{name}", (source / name).read_bytes())
        write(
            root,
            f"packets/{packet}/packet.json",
            canonical(
                {
                    "task": labels[label]["task"],
                    "subject": labels[label]["subject"],
                    "rubric": load_json((bundle / "review-rubric.json").read_bytes()),
                }
            )
            + b"\n",
        )
        mapping[packet] = labels[label] | {"original_packet": label}
    write(
        root,
        "trusted-index.json",
        canonical({"seed": seed, "mapping": mapping, "files": inventory(root)}) + b"\n",
    )
    return {
        "packets": 8,
        "reviewer_root": str(root / "packets"),
        "trusted_index": str(root / "trusted-index.json"),
    }


def verify(root, expected_digest=None):
    root = Path(root)
    if root.is_symlink() or root.joinpath("manifest.json").is_symlink():
        raise ValueError("bundle root/manifest must not be a link")
    if root.joinpath("manifest.json").stat().st_size > 2 * 1024**2:
        raise ValueError("oversized manifest")
    raw = root.joinpath("manifest.json").read_bytes()
    if expected_digest is not None and digest(raw) != expected_digest:
        raise ValueError("manifest differs from the external freeze digest")
    manifest = load_json(raw)
    if manifest.get("schema_version") != 1 or manifest.get("fixture") != "M-CLI1":
        raise ValueError("unsupported bundle")
    if inventory(root, exclude_manifest=True) != manifest["files"]:
        raise ValueError("bundle bytes, types or file inventory changed")
    if manifest["objects"]["S0"]["oid"] != SEED_OID:
        raise ValueError("wrong baseline")
    return manifest


def reviewer_corpus(trees):
    """Adjudication is trusted-side only; blind packets must omit this index."""
    bypass = trees["C2"] | {"src/cli.js": T2_BYPASS}
    wrong = trees["C2"] | {
        "src/cli.js": trees["C2"]["src/cli.js"].replace(
            "process.exitCode = 2", "process.exitCode = 1"
        )
    }
    alternate1 = trees["C1"] | {
        "src/validate.js": "export function validateName(input) {\n  if (!/\\S/u.test(input)) throw new TypeError('Name must not be blank');\n  return input;\n}\n"
    }
    alternate2 = trees["C2"] | {
        "src/cli.js": trees["C2"]["src/cli.js"].replace(
            "process.argv[2] ?? ''", "process.argv.slice(2)[0] ?? ''"
        )
    }
    rows = [
        (
            "P01",
            trees["B1-rejected"],
            "T-01",
            "reject",
            "mixed blank accepts space-tab-space",
        ),
        ("P02", bypass, "T-02", "reject", "validator substitution is ignored"),
        ("P03", wrong, "T-02", "reject", "blank CLI exits 1 rather than 2"),
        (
            "P04",
            trees["C1"] | {"package.json": SEED["package.json"] + "\n"},
            "T-01",
            "reject",
            "unrelated existing path changed",
        ),
        ("P05", trees["C1"], "T-01", "pass", "gold validator"),
        ("P06", alternate1, "T-01", "pass", "equivalent non-whitespace validator"),
        ("P07", trees["C2"], "T-02", "pass", "gold CLI"),
        ("P08", alternate2, "T-02", "pass", "equivalent first-argument access"),
    ]
    return {
        name: {
            "files": files,
            "task": task,
            "expected": verdict,
            "reproduction": reason,
        }
        for name, files, task, verdict, reason in rows
    }


T2_BYPASS = """try {
  const name = process.argv[2] ?? '';
  if (/^\\s*$/u.test(name)) throw new TypeError('Name must not be blank');
  process.stdout.write(`Hello, ${name}!\\n`);
} catch (error) {
  process.stderr.write(`${error.message}\\n`);
  process.exitCode = 2;
}
"""
