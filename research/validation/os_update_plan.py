"""Resolve pinned guest OS update proposals from retained signed metadata only.

No downloads, installation, guest execution or VM changes. Linux tooling is
needed only for --resolve; the default invocation prints a scope preview.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .guard_packages import WORKSPACE, configuration, package_record, paragraphs, sha

COLLECTION = WORKSPACE / ".local/validation/guard-packages-01"
CATALOG = WORKSPACE / "research/validation/guard-package-inputs.json"
NAME = r"[a-z0-9][a-z0-9+.-]*"
VERSION = r"[A-Za-z0-9:.+~_-]+"
INST = re.compile(
    rf"Inst ({NAME})(?: \[({VERSION})\])? \(({VERSION}) [^\r\n)]+\)(?: \[[^\]\r\n]*\])*"
)
CONF = re.compile(rf"Conf ({NAME}) \(({VERSION}) [^\r\n)]+\)(?: \[[^\]\r\n]*\])*")
SUMMARY = re.compile(
    r"(\d+) upgraded, (\d+) newly installed, (\d+) to remove and (\d+) not upgraded\."
)


def check_apt_command(args):
    if args == ["apt-get", "--version"]:
        return
    allowed = {
        "--simulate",
        "--with-new-pkgs",
        "--no-install-recommends",
        "--no-remove",
    }
    flags = []
    index = 1
    while index < len(args) and args[index].startswith("-"):
        if args[index] not in allowed:
            raise ValueError("unsupported APT simulation option")
        flags.append(args[index])
        index += 1
    if (
        args[0] != "apt-get"
        or "--simulate" not in flags
        or "--no-remove" not in flags
        or index == len(args)
        or args[index] not in ("upgrade", "install")
    ):
        raise ValueError("only simulated APT update transactions are allowed")
    if any(
        not re.fullmatch(rf"{NAME}(?:={VERSION})?", item) for item in args[index + 1 :]
    ):
        raise ValueError("unsupported APT package argument")


def actions(raw, installed, *, require_nftables):
    selected, configured, counts = {}, {}, []
    for line in raw.splitlines():
        if line.startswith(("Remv ", "Purg ")):
            raise ValueError("removals are outside this OS update proposal")
        if match := SUMMARY.fullmatch(line):
            counts.append(tuple(map(int, match.groups())))
        elif line.startswith("Inst "):
            match = INST.fullmatch(line)
            if not match:
                raise ValueError("unsupported APT installation action")
            name, old, new = match.groups()
            if name in selected or old != installed.get(name):
                raise ValueError("duplicate action or changed starting package version")
            if old == new:
                raise ValueError("unexpected reinstall")
            selected[name] = {"name": name, "old_version": old, "version": new}
        elif line.startswith("Conf "):
            match = CONF.fullmatch(line)
            if not match or match[1] in configured:
                raise ValueError("unsupported/duplicate APT configuration action")
            configured[match[1]] = match[2]
        elif re.match(r"^(Inst|Conf|Remv|Purg)\b", line):
            raise ValueError("unsupported APT action framing")
    updates = sum(row["old_version"] is not None for row in selected.values())
    additions = len(selected) - updates
    if counts != [(updates, additions, 0, 0)] or not 1 <= len(selected) <= 200:
        raise ValueError("incomplete, held-back or unsupported update summary")
    if configured != {name: row["version"] for name, row in selected.items()}:
        raise ValueError("APT configuration actions differ from selected packages")
    if ("nftables" in selected) != require_nftables:
        raise ValueError("packet-filter addition does not match the guest role")
    return list(selected.values()), {
        "upgrades": updates,
        "additions": additions,
        "removals": 0,
        "held_back": 0,
    }


def verify_files(root, expected):
    entries = list(root.rglob("*"))
    if root.is_symlink() or any(p.is_symlink() for p in entries):
        raise ValueError("linked metadata inputs are forbidden")
    actual = {
        p.relative_to(root).as_posix()
        for p in entries
        if p.is_file() and p.name != "receipt.json"
    }
    if actual != set(expected):
        raise ValueError("collection inventory changed")
    for name, row in expected.items():
        p = root / name
        if p.stat().st_size != row["bytes"] or sha(p.read_bytes()) != row["sha256"]:
            raise ValueError("retained metadata bytes changed")


def release_dates(raw, now):
    rows = paragraphs(raw)
    if len(rows) != 1 or rows[0].get("Origin") != "Ubuntu":
        raise ValueError("unexpected signed release payload")
    row = rows[0]
    created = parsedate_to_datetime(row["Date"])
    expiry = parsedate_to_datetime(row["Valid-Until"]) if "Valid-Until" in row else None
    if created.tzinfo is None or (expiry is not None and expiry.tzinfo is None):
        raise ValueError("release dates lack a timezone")
    if created > now + timedelta(seconds=10) or (expiry is not None and expiry <= now):
        raise ValueError("signed metadata is future-dated or expired")
    return {
        "suite": row["Suite"],
        "codename": row["Codename"],
        "date": created.isoformat(),
        "valid_until": expiry.isoformat() if expiry else None,
    }


def resolve(output):
    if sys.platform != "linux":
        raise ValueError("resolution uses the reviewed installed Linux APT tooling")
    candidate = Path(output).absolute()
    if any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("linked output paths are forbidden")
    root = candidate.resolve()
    root.relative_to((WORKSPACE / ".local/validation").resolve())
    frozen = json.loads(CATALOG.read_bytes())
    raw_receipt = (COLLECTION / "receipt.json").read_bytes()
    if sha(raw_receipt) != frozen["raw_collection_receipt"]["sha256"]:
        raise ValueError("collection differs from its recorded external digest")
    collection = json.loads(raw_receipt)
    if collection["status"] != "collected-not-installed":
        raise ValueError("collection did not complete")
    verify_files(COLLECTION, collection["files"])
    status = (COLLECTION / "target-status").read_bytes()
    if sha(status) != frozen["target_status_sha256"]:
        raise ValueError("starting target status changed")
    installed = {
        r["Package"]: r["Version"]
        for r in paragraphs(status.decode())
        if r.get("Status") == "install ok installed"
    }
    if len(installed) != 480:
        raise ValueError("unexpected starting package inventory")
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(COLLECTION / "state/lists", root / "state/lists")
    shutil.copytree(COLLECTION / "etc", root / "etc")
    for folder in ("cache/archives/partial", "log", "gnupg", "commands", "releases"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "target-status").write_bytes(status)
    (root / "apt.config").write_text(
        configuration(root) + 'APT::Get::Always-Include-Phased-Updates "true";\n'
    )
    sources = root / "etc/sources.list"
    sources.write_text(sources.read_text().replace(str(COLLECTION), str(root)))
    env = {
        **os.environ,
        "APT_CONFIG": str(root / "apt.config"),
        "LC_ALL": "C",
        "LANG": "C",
    }
    host_status = Path("/var/lib/dpkg/status")
    before = sha(host_status.read_bytes())
    receipt = {
        "schema_version": 1,
        "status": "resolving",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "offline signed-metadata resolution only; no archive downloads, installs, guest execution or VM changes",
        "source_sha256": {
            p.name: sha(p.read_bytes())
            for p in (Path(__file__), Path(__file__).with_name("guard_packages.py"))
        },
        "collection_receipt_sha256": sha(raw_receipt),
        "target_status_sha256": sha(status),
        "host_status_sha256_before": before,
        "include_phased_updates": True,
        "commands": [],
    }

    def save():
        temporary = root / "receipt.next"
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temporary.replace(root / "receipt.json")

    def run(label, args):
        if args[0] == "apt-get":
            check_apt_command(args)
        result = subprocess.run(
            args, env=env, cwd=root, capture_output=True, timeout=120, check=False
        )
        (root / "commands" / (label + ".stdout")).write_bytes(result.stdout)
        (root / "commands" / (label + ".stderr")).write_bytes(result.stderr)
        receipt["commands"].append(
            {"label": label, "args": args, "exit": result.returncode}
        )
        save()
        if result.returncode:
            raise ValueError(f"{label} failed; preserve metadata and hold")
        return result.stdout.decode()

    save()
    try:
        for binary in ("apt-get", "apt-cache", "gpgv", "dpkg"):
            run(binary + "-version", [binary, "--version"])
        run("effective-config", ["apt-config", "dump"])
        signed = []
        for number, release in enumerate(
            sorted((root / "state/lists").glob("*_InRelease"))
        ):
            payload = root / "releases" / (str(number) + ".txt")
            result = run(
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
                    str(release),
                ],
            )
            if (
                "[GNUPG:] VALIDSIG F6ECB3762474EDA9D21B7022871920D1991BC93C "
                not in result
            ):
                raise ValueError("unexpected release signing identity")
            signed.append(
                release_dates(payload.read_text(), datetime.now(timezone.utc))
            )
        if {r["suite"] for r in signed} != {"noble", "noble-updates", "noble-security"}:
            raise ValueError("missing or unexpected signed suite")
        profiles, unique = {}, {}
        for role, extra in (("executor", []), ("guard", ["nftables"])):
            simulated = run(
                "simulate-" + role,
                [
                    "apt-get",
                    "--simulate",
                    "--with-new-pkgs",
                    "--no-install-recommends",
                    "--no-remove",
                    "upgrade",
                    *extra,
                ],
            )
            selected, counts = actions(
                simulated, installed, require_nftables=role == "guard"
            )
            profiles[role] = {
                "counts": counts,
                "actions": selected,
                "expected_installed_rows": 480 + counts["additions"],
            }
            for row in selected:
                if row["name"] in unique and unique[row["name"]] != row:
                    raise ValueError("roles resolve conflicting versions")
                unique[row["name"]] = row
        comparisons = []
        for row in unique.values():
            if row["old_version"] is not None:
                args = [
                    "dpkg",
                    "--compare-versions",
                    row["old_version"],
                    "lt",
                    row["version"],
                ]
                result = subprocess.run(
                    args, env=env, capture_output=True, timeout=10, check=False
                )
                comparisons.append(
                    {"name": row["name"], "args": args, "exit": result.returncode}
                )
        (root / "version-comparisons.json").write_text(
            json.dumps(comparisons, indent=2) + "\n"
        )
        if any(r["exit"] for r in comparisons):
            raise ValueError("a proposed change is not a version upgrade")
        final_versions = {
            **installed,
            **{r["name"]: r["version"] for r in unique.values()},
        }
        metadata = run(
            "exact-package-metadata",
            [
                "apt-cache",
                "show",
                *(name + "=" + version for name, version in final_versions.items()),
            ],
        )
        metadata_index = {}
        for row in paragraphs(metadata):
            metadata_index.setdefault(
                (row.get("Package"), row.get("Version")), []
            ).append(row)
        published = {}
        for name, version in final_versions.items():
            narrowed = "\n\n".join(
                "\n".join(f"{key}: {value}" for key, value in row.items())
                for row in metadata_index.get((name, version), [])
            )
            published[name] = package_record(narrowed, name, version, max_bytes=1024**3)
        (root / "published-final-packages.json").write_text(
            json.dumps(published, indent=2, sort_keys=True) + "\n"
        )
        records = []
        for row in unique.values():
            record = dict(published[row["name"]])
            record["old_version"] = row["old_version"]
            record["locally_verified_archive"] = next(
                (
                    str(COLLECTION / "archives" / p["local_filename"])
                    for p in collection["packages"]
                    if p["sha256"] == record["sha256"] and p["bytes"] == record["bytes"]
                ),
                None,
            )
            records.append(record)
        if sum(r["bytes"] for r in records) > 2 * 1024**3:
            raise ValueError("update archive union exceeds proposal size bound")
        for role, profile in profiles.items():
            pinned = run(
                "pinned-simulate-" + role,
                [
                    "apt-get",
                    "--simulate",
                    "--no-install-recommends",
                    "--no-remove",
                    "install",
                    *(r["name"] + "=" + r["version"] for r in profile["actions"]),
                ],
            )
            repeated, repeated_counts = actions(
                pinned, installed, require_nftables=role == "guard"
            )
            if {json.dumps(r, sort_keys=True) for r in repeated} != {
                json.dumps(r, sort_keys=True) for r in profile["actions"]
            } or repeated_counts != profile["counts"]:
                raise ValueError("pinned replay changes the proposed transaction")
        receipt.update(
            {
                "status": "prepared-not-approved",
                "signed_releases": signed,
                "profiles": profiles,
                "packages": records,
                "published_final_package_versions": len(published),
                "archive_bytes": sum(r["bytes"] for r in records),
                "additional_download_bytes": sum(
                    r["bytes"] for r in records if r["locally_verified_archive"] is None
                ),
            }
        )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        receipt.update({"status": "hold", "error": str(exc)})
    receipt["host_status_sha256_after"] = sha(host_status.read_bytes())
    receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    if (
        before != receipt["host_status_sha256_after"]
        or (root / "target-status").read_bytes() != status
    ):
        receipt.update(
            {"status": "hold", "error": "host or target package status changed"}
        )
    try:
        verify_files(COLLECTION, collection["files"])
    except (OSError, ValueError) as exc:
        receipt.update({"status": "hold", "error": str(exc)})
    if any(
        sha(Path(__file__).with_name(name).read_bytes()) != digest
        for name, digest in receipt["source_sha256"].items()
    ):
        receipt.update({"status": "hold", "error": "planner source changed"})
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
    parser.add_argument("--output", default=".local/validation/os-update-resolution-01")
    args = parser.parse_args()
    if not args.resolve:
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "profiles": [
                        "executor OS updates",
                        "guard OS updates plus nftables",
                    ],
                    "metadata": "retained signed Noble snapshot",
                    "include_phased_updates": True,
                    "downloads": False,
                    "install": False,
                }
            )
        )
        return
    result = resolve(WORKSPACE / args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "profiles": {
                    k: v["counts"] for k, v in result.get("profiles", {}).items()
                },
                "archives": len(result.get("packages", [])),
                "archive_bytes": result.get("archive_bytes"),
                "additional_download_bytes": result.get("additional_download_bytes"),
                "error": result.get("error"),
            }
        )
    )
    if result["status"] != "prepared-not-approved":
        sys.exit(1)


if __name__ == "__main__":
    main()
