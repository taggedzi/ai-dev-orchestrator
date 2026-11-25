"""Retrieve exact archives from a frozen OS update or explicit engine proposal.

Uses installed WSL APT/dpkg-deb tools, private metadata/cache/configuration and
public Ubuntu mirrors. There is no installation or VM operation.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .guard_packages import SOURCES, WORKSPACE, configuration, paragraphs, sha
from .os_update_plan import COLLECTION, NAME, VERSION, release_dates, verify_files

CATALOG = WORKSPACE / "research/validation/os-update-inputs.json"
ENGINE_CATALOG = WORKSPACE / "research/validation/engine-inputs.json"


def check_download_command(args):
    if (
        len(args) < 3
        or args[:2] != ["apt-get", "download"]
        or any(not re.fullmatch(rf"{NAME}={VERSION}", value) for value in args[2:])
    ):
        raise ValueError("only exact-version archive download commands are allowed")


def checked_catalog(raw, expected, *, kind="os-update"):
    if kind not in ("os-update", "engine"):
        raise ValueError("unsupported archive proposal kind")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha(raw) != expected:
        raise ValueError("catalog differs from the external review digest")
    value = json.loads(raw)
    packages = value["archives"]
    names = {r["name"] for r in packages}
    if (
        value["schema_version"] != 1
        or value["installation_approval"] is not None
        or not 1 <= len(packages) <= 200
        or len(names) != len(packages)
        or value["unique_archives"] != len(packages)
    ):
        raise ValueError("unsupported archive proposal")
    if kind == "os-update" and (
        set(value.get("profiles", {})) != {"executor", "guard"}
        or set().union(*(set(r["package_names"]) for r in value["profiles"].values()))
        != names
    ):
        raise ValueError("proposal guest profiles do not match archive inventory")
    if kind == "engine" and (
        value.get("status") != "resolved-not-downloaded-not-installed"
        or value.get("role") != "executor container engine candidate"
        or not {"docker.io", "containerd", "runc"} <= names
        or value.get("counts")
        != {"upgrades": 0, "additions": len(packages), "removals": 0, "held_back": 0}
        or value.get("planning_baseline", {}).get("package_rows") != 485
        or value.get("proposed_final_package_rows") != 485 + len(packages)
        or value.get("security_and_runtime_qualified") is not False
    ):
        raise ValueError(
            "engine proposal does not preserve its unresolved installation scope"
        )
    for row in packages:
        if (
            not re.fullmatch(NAME, row["name"])
            or not re.fullmatch(VERSION, row["version"])
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            or row.get("architecture") not in ("amd64", "all")
            or type(row["bytes"]) is not int
            or not 0 < row["bytes"] <= 1024**3
        ):
            raise ValueError("unsupported package identity, digest or size")
        if kind == "engine" and (
            not re.fullmatch(
                r"pool/(?:main|universe)/[A-Za-z0-9/_.+~%:-]+\.deb",
                row.get("archive_path", ""),
            )
            or ".." in row["archive_path"].split("/")
            or row.get("filename") != row["archive_path"].rsplit("/", 1)[-1]
        ):
            raise ValueError("engine archive is outside the reviewed components")
    if (
        sum(r["bytes"] for r in packages) != value["archive_bytes"]
        or value["archive_bytes"] > 2 * 1024**3
    ):
        raise ValueError("archive size union differs or exceeds scope")
    return value


def check_resolution_binding(catalog, metadata, kind):
    if kind == "os-update":
        return catalog["source_status_sha256"]
    keys = ("name", "version", "architecture", "bytes", "sha256", "archive_path")
    expected = {r["name"]: tuple(r[k] for k in keys) for r in catalog["archives"]}
    observed = {r["name"]: tuple(r[k] for k in keys) for r in metadata["packages"]}
    status_hash = catalog["planning_baseline"]["projected_status_sha256"]
    if (
        len(observed) != len(metadata["packages"])
        or expected != observed
        or metadata.get("counts") != catalog["counts"]
        or len(metadata.get("baseline_versions", {})) != 485
        or metadata.get("projected_status_sha256") != status_hash
        or not re.fullmatch(r"[0-9a-f]{64}", status_hash)
    ):
        raise ValueError("engine catalog differs from the frozen native resolution")
    return status_hash


def source_lines(keyring, kind):
    if kind not in ("os-update", "engine"):
        raise ValueError("unsupported source component mode")
    return [
        s.format(keyring=keyring) + (" universe" if kind == "engine" else "")
        for s in SOURCES
    ]


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fetch(output, expected_catalog, approval, *, kind="os-update"):
    if sys.platform != "linux" or not approval.strip():
        raise ValueError(
            "retrieval requires existing Linux tools and an explicit approval reference"
        )
    catalog_path = CATALOG if kind == "os-update" else ENGINE_CATALOG
    raw_catalog = catalog_path.read_bytes()
    catalog = checked_catalog(raw_catalog, expected_catalog, kind=kind)
    if kind == "engine" and os.getuid() != 1000:
        raise ValueError("engine retrieval requires the reviewed unprivileged WSL user")
    local_root = (WORKSPACE / ".local/validation").resolve()
    candidate = Path(output).absolute()
    if any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("linked output paths are forbidden")
    root = candidate.resolve()
    root.relative_to(local_root)
    reference = catalog[
        "metadata_receipt" if kind == "os-update" else "native_resolution_receipt"
    ]
    metadata_file = (WORKSPACE / reference["path"]).resolve()
    metadata_file.relative_to(local_root)
    raw_metadata = metadata_file.read_bytes()
    if sha(raw_metadata) != reference["sha256"]:
        raise ValueError("metadata receipt differs from the frozen proposal")
    source = metadata_file.parent
    metadata = json.loads(raw_metadata)
    if metadata["status"] != "prepared-not-approved":
        raise ValueError("archive proposal resolution did not pass")
    verify_files(source, metadata["files"])
    expected_status = check_resolution_binding(catalog, metadata, kind)
    for release in (source / "releases").glob("*.txt"):
        release_dates(release.read_text(), datetime.now(timezone.utc))
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / "state/lists", root / "state/lists")
    for folder in (
        "etc/apt.conf.d",
        "etc/sources.list.d",
        "etc/preferences.d",
        "etc/trusted.gpg.d",
        "cache/archives/partial",
        "log",
        "archives",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)
    keyring = root / "etc/ubuntu-archive-keyring.gpg"
    keyring.write_bytes((source / "etc/ubuntu-archive-keyring.gpg").read_bytes())
    (root / "etc/sources.list").write_text(
        "\n".join(source_lines(keyring, kind)) + "\n"
    )
    (root / "target-status").write_bytes((source / "target-status").read_bytes())
    if sha((root / "target-status").read_bytes()) != expected_status:
        raise ValueError("starting target status differs")
    (root / "apt.config").write_text(configuration(root))
    (root / "catalog.json").write_bytes(raw_catalog)
    (root / "executed-collector.py").write_bytes(Path(__file__).read_bytes())
    env = {
        **os.environ,
        "APT_CONFIG": str(root / "apt.config"),
        "LC_ALL": "C",
        "LANG": "C",
    }
    host_status = Path("/var/lib/dpkg/status")
    before = file_digest(host_status)
    receipt = {
        "schema_version": 1,
        "catalog_kind": kind,
        "status": "retrieving",
        "approval": approval,
        "catalog_sha256": expected_catalog,
        "metadata_receipt_sha256": sha(raw_metadata),
        "source_sha256": {
            p.name: sha(p.read_bytes())
            for p in (
                Path(__file__),
                Path(__file__).with_name("os_update_plan.py"),
                Path(__file__).with_name("guard_packages.py"),
            )
        },
        "scope": "exact archives and control metadata only; no downloaded code execution, installation or VM changes",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "host_status_sha256_before": before,
    }

    def save():
        temporary = root / "receipt.next"
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temporary.replace(root / "receipt.json")

    save()
    try:
        reused = []
        reused_sources = []
        available = {}
        for p in (COLLECTION / "archives").glob("*.deb"):
            if p.is_symlink():
                raise ValueError("linked cache archive")
            available[file_digest(p)] = p
        pending = []
        for row in catalog["archives"]:
            cached = available.get(row["sha256"])
            if cached is None:
                pending.append(row)
                continue
            if cached.stat().st_size != row["bytes"]:
                raise ValueError("cache archive size mismatch")
            shutil.copyfile(cached, root / "archives" / cached.name)
            reused.append(row["name"])
            reused_sources.append(
                {"name": row["name"], "path": str(cached), "sha256": row["sha256"]}
            )
        args = [
            "apt-get",
            "download",
            *(r["name"] + "=" + r["version"] for r in pending),
        ]
        if pending:
            check_download_command(args)
            receipt["download_args"] = args
            receipt["reused_packages"] = reused
            receipt["reused_archive_sources"] = reused_sources
            save()
            with subprocess.Popen(
                args,
                env=env,
                cwd=root / "archives",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            ) as operation:
                receipt["download_pid"] = operation.pid
                receipt["download_process_group"] = operation.pid
                receipt["download_state"] = "running"
                save()
                timed_out = False
                try:
                    stdout, stderr = operation.communicate(timeout=900)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(operation.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout, stderr = operation.communicate()
                download_exit = operation.returncode
            (root / "download.stdout").write_bytes(stdout)
            (root / "download.stderr").write_bytes(stderr)
            receipt["download_exit"] = download_exit
            receipt["download_state"] = "terminal"
            receipt["download_timed_out"] = timed_out
            save()
            if download_exit or timed_out:
                raise ValueError(
                    "APT archive retrieval failed; preserve partial downloads"
                )
        files = list((root / "archives").iterdir())
        if len(files) != len(catalog["archives"]) or any(
            not p.is_file() or p.is_symlink() or p.suffix != ".deb" for p in files
        ):
            raise ValueError("unexpected archive inventory")
        by_hash = {}
        for p in files:
            by_hash.setdefault(file_digest(p), []).append(p)
        observations = []
        for row in catalog["archives"]:
            matches = by_hash.get(row["sha256"], [])
            if len(matches) != 1 or matches[0].stat().st_size != row["bytes"]:
                raise ValueError("archive differs from authenticated catalog")
            p = matches[0]
            result = subprocess.run(
                ["dpkg-deb", "--field", str(p), "Package", "Version", "Architecture"],
                env=env,
                capture_output=True,
                timeout=20,
                check=False,
            )
            fields = paragraphs(result.stdout.decode())
            if (
                result.returncode
                or len(fields) != 1
                or (
                    fields[0].get("Package"),
                    fields[0].get("Version"),
                    fields[0].get("Architecture"),
                )
                != (row["name"], row["version"], row["architecture"])
            ):
                raise ValueError("archive control identity differs")
            observations.append(
                {
                    "name": row["name"],
                    "version": row["version"],
                    "architecture": row["architecture"],
                    "filename": p.name,
                    "bytes": row["bytes"],
                    "sha256": row["sha256"],
                    "control_identity": "pass",
                }
            )
        receipt.update(
            {
                "status": "retrieved-not-installed",
                "archives": observations,
                "archive_bytes": sum(r["bytes"] for r in observations),
                "retrieved_packages": len(pending),
                "reused_packages": reused,
                "reused_archive_sources": reused_sources,
            }
        )
        verify_files(source, metadata["files"])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        receipt.update({"status": "hold", "error": str(exc)})
    receipt["host_status_sha256_after"] = file_digest(host_status)
    receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    if (
        before != receipt["host_status_sha256_after"]
        or catalog_path.read_bytes() != raw_catalog
        or metadata_file.read_bytes() != raw_metadata
        or file_digest(root / "target-status") != expected_status
        or any(
            sha(Path(__file__).with_name(name).read_bytes()) != digest
            for name, digest in receipt["source_sha256"].items()
        )
    ):
        receipt.update(
            {
                "status": "hold",
                "error": "host status, catalog or collector source changed",
            }
        )
    receipt["files"] = {
        p.relative_to(root).as_posix(): {
            "bytes": p.stat().st_size,
            "sha256": file_digest(p),
        }
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "receipt.json"
    }
    save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    parser.add_argument("--kind", choices=("os-update", "engine"), default="os-update")
    parser.add_argument("--catalog-sha256")
    parser.add_argument("--retrieve-approval")
    args = parser.parse_args()
    catalog_path = CATALOG if args.kind == "os-update" else ENGINE_CATALOG
    if not args.retrieve_approval:
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "catalog_sha256": sha(catalog_path.read_bytes()),
                    "catalog_kind": args.kind,
                    "scope": "download exact public Ubuntu archives only",
                    "install": False,
                    "vm_changes": False,
                }
            )
        )
        return
    result = fetch(
        WORKSPACE
        / (
            args.output
            or (
                ".local/validation/engine-artifacts-01"
                if args.kind == "engine"
                else ".local/validation/os-update-artifacts-01"
            )
        ),
        args.catalog_sha256 or "",
        args.retrieve_approval,
        kind=args.kind,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "verified_archives": len(result.get("archives", [])),
                "bytes": result.get("archive_bytes"),
                "retrieved_packages": result.get("retrieved_packages"),
                "reused_packages": len(result.get("reused_packages", [])),
                "error": result.get("error"),
            }
        )
    )
    if result["status"] != "retrieved-not-installed":
        sys.exit(1)


if __name__ == "__main__":
    main()
