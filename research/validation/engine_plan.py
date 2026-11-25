"""Resolve engine additions against a hypothetical post-OS status; never install."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .engine_metadata import RESOLUTION, plan
from .guard_packages import WORKSPACE, configuration, package_record, paragraphs, sha
from .os_update_plan import actions, check_apt_command, release_dates, verify_files

ENGINE_METADATA = WORKSPACE / ".local/validation/engine-metadata-02"
ENGINE_RECEIPT_SHA256 = (
    "8b16c9a5a5a9fc59e00f59f6ab98737583b8ce47787b96cdcfbdb0e6a60c7cab"
)
STATUS_FIELDS = (
    "Package",
    "Status",
    "Priority",
    "Section",
    "Installed-Size",
    "Maintainer",
    "Architecture",
    "Multi-Arch",
    "Source",
    "Version",
    "Essential",
    "Protected",
    "Pre-Depends",
    "Depends",
    "Recommends",
    "Suggests",
    "Conflicts",
    "Breaks",
    "Replaces",
    "Provides",
    "Enhances",
    "Description",
    "Homepage",
)


def project_status(raw_status, updates, metadata):
    """Construct dependency-planning data, with no claim that packages installed."""
    installed = {}
    for row in paragraphs(raw_status.decode()):
        if row.get("Status") == "install ok installed":
            if row["Package"] in installed:
                raise ValueError("duplicate installed package")
            installed[row["Package"]] = row["Version"]
    desired = installed.copy()
    changed = set()
    for row in updates:
        name = row["name"]
        if (
            name in changed
            or installed.get(name) != row["old_version"]
            or row["version"] == row["old_version"]
        ):
            raise ValueError("OS action differs from the inspected starting version")
        changed.add(name)
        desired[name] = row["version"]
    index = {}
    for row in metadata:
        if row.get("Architecture") in ("amd64", "all"):
            index.setdefault((row["Package"], row["Version"]), []).append(row)
    result = []
    for name, version in sorted(desired.items()):
        matches = index.get((name, version), [])
        if not matches:
            raise ValueError("missing exact package metadata for projected status")
        variants = [
            {k: v for k, v in r.items() if k in STATUS_FIELDS and k != "Status"}
            for r in matches
        ]
        if any(r != variants[0] for r in variants[1:]):
            raise ValueError("conflicting exact-version package control metadata")
        row = {**variants[0], "Status": "install ok installed"}
        if not {
            "Package",
            "Version",
            "Architecture",
            "Maintainer",
            "Description",
        } <= set(row):
            raise ValueError("incomplete projected package control fields")
        result.append(
            "\n".join(f"{key}: {row[key]}" for key in STATUS_FIELDS if key in row)
        )
    return ("\n\n".join(result) + "\n\n").encode(), desired


def inputs():
    indexes = plan()  # Rechecks the OS receipt, inventory and prior signatures.
    raw = (ENGINE_METADATA / "receipt.json").read_bytes()
    if sha(raw) != ENGINE_RECEIPT_SHA256:
        raise ValueError("engine metadata differs from its external receipt pin")
    receipt = json.loads(raw)
    if (
        receipt["status"] != "collected-not-resolved-not-installed"
        or receipt["indexes"] != indexes
    ):
        raise ValueError("engine metadata is incomplete or from another OS cohort")
    verify_files(ENGINE_METADATA, receipt["files"])
    os_receipt = json.loads((RESOLUTION / "receipt.json").read_bytes())
    profile = os_receipt["profiles"]["executor"]
    status, desired = project_status(
        (RESOLUTION / "target-status").read_bytes(),
        profile["actions"],
        paragraphs(
            (RESOLUTION / "commands/exact-package-metadata.stdout").read_text(
                encoding="utf-8"
            )
        ),
    )
    if (
        len(desired) != profile["expected_installed_rows"]
        or len(desired) != 485
        or any(name in desired for name in ("docker.io", "containerd", "runc"))
    ):
        raise ValueError("unexpected proposed executor inventory")
    return status, desired, indexes


def check_engine_command(args):
    check_apt_command(args)
    if args == ["apt-get", "--version"]:
        return
    if (
        "upgrade" in args
        or "install" not in args
        or not all(
            re.fullmatch(r"[a-z0-9][a-z0-9+.-]*=[A-Za-z0-9:.+~_-]+", item)
            for item in args[args.index("install") + 1 :]
        )
        or not args[args.index("install") + 1 :]
    ):
        raise ValueError("engine resolver requires only pinned simulated additions")


def candidate_version(raw, package):
    current, found = None, []
    for line in raw.splitlines():
        if line and not line[0].isspace():
            current = line.removesuffix(":")
        elif current == package and line.startswith("  Candidate: "):
            found.append(line.removeprefix("  Candidate: "))
    if len(found) != 1 or not re.fullmatch(r"[A-Za-z0-9:.+~_-]+", found[0]):
        raise ValueError("missing or ambiguous native package candidate")
    return found[0]


def verify_signed_indexes(root, release):
    records = {}
    for line in release["SHA256"].splitlines():
        if line.strip():
            digest, size, name = line.split()
            if name in records:
                raise ValueError("duplicate signed index path")
            records[name] = {"bytes": int(size), "sha256": digest}
    host = (
        "security.ubuntu.com"
        if release["Suite"] == "noble-security"
        else "archive.ubuntu.com"
    )
    result = {}
    for component in ("main", "universe"):
        expected = records[f"{component}/binary-amd64/Packages"]
        path = (
            root
            / "state/lists"
            / f"{host}_ubuntu_dists_{release['Suite']}_{component}_binary-amd64_Packages"
        )
        if (
            path.stat().st_size != expected["bytes"]
            or sha(path.read_bytes()) != expected["sha256"]
        ):
            raise ValueError("private APT index differs from signed release")
        result[component] = expected
    return result


def resolve(output):
    if sys.platform != "linux":
        raise ValueError("native resolution needs the existing Linux APT tools")
    status, desired, indexes = inputs()
    candidate = Path(output).absolute()
    if any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("linked output paths are forbidden")
    root = candidate.resolve()
    root.relative_to((WORKSPACE / ".local/validation").resolve())
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(RESOLUTION / "state/lists", root / "state/lists")
    shutil.copytree(RESOLUTION / "etc", root / "etc")
    for folder in (
        "cache/archives/partial",
        "log",
        "gnupg",
        "commands",
        "releases",
        "projected-dpkg",
        "source",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for row in indexes:
        host = (
            "security.ubuntu.com"
            if row["suite"] == "noble-security"
            else "archive.ubuntu.com"
        )
        name = f"{host}_ubuntu_dists_{row['suite']}_universe_binary-amd64_Packages"
        shutil.copyfile(
            ENGINE_METADATA / (row["suite"] + "-Packages"), root / "state/lists" / name
        )
    (root / "target-status").write_bytes(status)
    (root / "projected-dpkg/status").write_bytes(status)
    sources = root / "etc/sources.list"
    sources.write_text(
        sources.read_text()
        .replace(str(RESOLUTION), str(root))
        .replace(" main\n", " main universe\n")
    )
    (root / "apt.config").write_text(
        configuration(root) + 'APT::Get::Always-Include-Phased-Updates "true";\n'
    )
    source_paths = [
        Path(__file__),
        *[
            Path(__file__).with_name(n)
            for n in ("engine_metadata.py", "guard_packages.py", "os_update_plan.py")
        ],
    ]
    source_hashes = {p.name: sha(p.read_bytes()) for p in source_paths}
    for path in source_paths:
        (root / "source" / path.name).write_bytes(path.read_bytes())
    host_status = Path("/var/lib/dpkg/status")
    before = sha(host_status.read_bytes())
    receipt = {
        "format": "mcli1-engine-resolution-v1",
        "status": "resolving",
        "scope": "Offline APT simulation on reconstructed status only; no downloads, installs or VM changes",
        "baseline_classification": "Hypothetical 485-row post-OS planning inventory, not installed guest observation",
        "projected_status_sha256": sha(status),
        "baseline_versions": desired,
        "source_sha256": source_hashes,
        "engine_metadata_receipt_sha256": ENGINE_RECEIPT_SHA256,
        "host_status_sha256_before": before,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "commands": [],
    }

    def save():
        (root / "receipt.json").write_bytes(
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
        )

    def run(label, args):
        if args[0] == "apt-get":
            check_engine_command(args)
        result = subprocess.run(
            args,
            cwd=root,
            env={
                **os.environ,
                "APT_CONFIG": str(root / "apt.config"),
                "LC_ALL": "C",
                "LANG": "C",
            },
            capture_output=True,
            timeout=120,
            check=False,
        )
        for suffix, data in (("stdout", result.stdout), ("stderr", result.stderr)):
            (root / "commands" / (label + "." + suffix)).write_bytes(data)
        receipt["commands"].append(
            {"label": label, "args": args, "exit": result.returncode}
        )
        save()
        if result.returncode:
            raise ValueError(f"{label} failed; preserve evidence and hold")
        return result.stdout.decode()

    save()
    try:
        if run("user-id", ["id", "-u"]).strip() != "1000":
            raise ValueError(
                "resolver must use the previously reviewed unprivileged WSL user"
            )
        for tool in ("apt-get", "apt-cache", "gpgv", "dpkg-query"):
            run(tool + "-version", [tool, "--version"])
        run("effective-config", ["apt-config", "dump"])
        shown = run(
            "projected-dpkg-query",
            [
                "dpkg-query",
                f"--admindir={root / 'projected-dpkg'}",
                "-W",
                "-f=${Package}\t${Version}\t${Status}\n",
            ],
        )
        observed = {}
        for line in shown.splitlines():
            name, version, state = line.split("\t")
            if state != "install ok installed" or name in observed:
                raise ValueError("projected status has unexpected dpkg state")
            observed[name] = version
        if observed != desired:
            raise ValueError("dpkg-query differs from the projected inventory")
        signed, verified_indexes = [], {}
        for number, path in enumerate(
            sorted((root / "state/lists").glob("*_InRelease"))
        ):
            payload = root / "releases" / f"{number}.txt"
            signature = run(
                f"signature-{number}",
                [
                    "gpgv",
                    "--homedir",
                    str(root / "gnupg"),
                    "--keyring",
                    str(root / "etc/ubuntu-archive-keyring.gpg"),
                    "--output",
                    str(payload),
                    "--status-fd",
                    "1",
                    str(path),
                ],
            )
            if (
                "[GNUPG:] VALIDSIG F6ECB3762474EDA9D21B7022871920D1991BC93C "
                not in signature
            ):
                raise ValueError("unexpected archive signing identity")
            signed.append(
                release_dates(payload.read_text(), datetime.now(timezone.utc))
            )
            release = paragraphs(payload.read_text())[0]
            verified_indexes[release["Suite"]] = verify_signed_indexes(root, release)
        if {r["suite"] for r in signed} != {r["suite"] for r in indexes}:
            raise ValueError("incomplete signed release cohort")
        policy = run(
            "engine-candidates",
            ["apt-cache", "policy", "docker.io", "containerd", "runc"],
        )
        docker_candidate = candidate_version(policy, "docker.io")
        base_command = [
            "apt-get",
            "--simulate",
            "--no-install-recommends",
            "--no-remove",
            "install",
        ]
        text = run("simulate-engine", [*base_command, "docker.io=" + docker_candidate])
        selected, counts = actions(text, desired, require_nftables=False)
        if counts["upgrades"] or not {"docker.io", "containerd", "runc"} <= {
            r["name"] for r in selected
        }:
            raise ValueError(
                "engine transaction changes the OS baseline or lacks required runtimes"
            )
        repeated, repeated_counts = actions(
            run(
                "pinned-simulate-engine",
                [*base_command, *[r["name"] + "=" + r["version"] for r in selected]],
            ),
            desired,
            require_nftables=False,
        )
        if counts != repeated_counts or sorted(
            selected, key=lambda r: r["name"]
        ) != sorted(repeated, key=lambda r: r["name"]):
            raise ValueError("pinned replay changes the selected package effects")
        metadata = run(
            "selected-package-metadata",
            ["apt-cache", "show", *[r["name"] + "=" + r["version"] for r in selected]],
        )
        records = [
            package_record(
                metadata,
                r["name"],
                r["version"],
                max_bytes=1024**3,
                components=("main", "universe"),
            )
            for r in selected
        ]
        if sum(r["bytes"] for r in records) > 1024**3:
            raise ValueError("engine archive set exceeds its planning bound")
        receipt.update(
            {
                "status": "prepared-not-approved",
                "signed_releases": signed,
                "verified_private_indexes": verified_indexes,
                "actions": selected,
                "counts": counts,
                "packages": records,
                "archive_bytes": sum(r["bytes"] for r in records),
                "expected_installed_rows": len(desired) + counts["additions"],
            }
        )
    except Exception as exc:  # noqa: BLE001 -- persist terminal diagnostics rather than infer a successful plan
        receipt.update({"status": "hold", "error": f"{type(exc).__name__}: {exc}"})
    receipt["host_status_sha256_after"] = sha(host_status.read_bytes())
    receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        inputs()
        if (
            before != receipt["host_status_sha256_after"]
            or (root / "target-status").read_bytes() != status
            or (root / "projected-dpkg/status").read_bytes() != status
            or any(sha(p.read_bytes()) != source_hashes[p.name] for p in source_paths)
        ):
            raise ValueError("host status, projected status or planner source changed")
    except (OSError, ValueError) as exc:
        receipt.update({"status": "hold", "integrity_error": str(exc)})
    receipt["files"] = {
        p.relative_to(root).as_posix(): {
            "bytes": p.stat().st_size,
            "sha256": sha(p.read_bytes()),
        }
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "receipt.json"
    }
    save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument(
        "--output", default=str(WORKSPACE / ".local/validation/engine-resolution-01")
    )
    args = parser.parse_args()
    if not args.resolve:
        status, desired, _ = inputs()
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "baseline": "hypothetical post-update executor, not installed",
                    "installed_rows_for_planning": len(desired),
                    "projected_status_sha256": sha(status),
                    "archive_download_or_installation": False,
                },
                indent=2,
            )
        )
        return
    receipt = resolve(args.output)
    print(
        json.dumps(
            {
                k: receipt.get(k)
                for k in (
                    "status",
                    "error",
                    "integrity_error",
                    "counts",
                    "archive_bytes",
                    "expected_installed_rows",
                )
            },
            indent=2,
        )
    )
    if receipt["status"] != "prepared-not-approved":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
