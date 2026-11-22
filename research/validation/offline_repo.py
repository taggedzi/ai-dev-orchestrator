"""Prepare a signed local Ubuntu mirror; check it with private, simulated APT.

No installation, package-script execution, network retrieval or VM operations.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .fetch_os_updates import checked_catalog, file_digest
from .guard_packages import WORKSPACE, configuration, paragraphs, sha
from .os_update_plan import NAME, VERSION, actions, release_dates, verify_files

LOCAL = WORKSPACE / ".local/validation"
SUITES = ("noble", "noble-updates", "noble-security")
COMPONENTS = ("main", "universe")
FINGERPRINT = "F6ECB3762474EDA9D21B7022871920D1991BC93C"
CATALOGS = {
    "os-update": "4e3d6910cd66b8bcd4f70fc13aba59f98a141fed9e8bc96392bcdeb33634e57a",
    "engine": "d4cb0db896a0b45e1e98a1ef26afd876a65f7f5f1fa85edcf33577ce2028f396",
}
RECEIPTS = {
    "os-update-resolution-02": "408bf86c502100b284273aa5ec1c6a43c4c7b8949e414cc2079d329ebfaca3a9",
    "engine-resolution-02": "b6727d3878cf7c3144a471352e23db04152411c2ad36072d293a4596c0f32dbd",
    "os-update-artifacts-01": "f50b00bdec22d3ea949ff26627c78cc2fa84de8046bd9331fb477b430c6b719b",
    "engine-artifacts-01": "2e7192702f316856147b0a0c68d0e4359f2757c2ba547e4040ff0d307a3c7515",
}
IDENTITY = ("name", "version", "architecture", "bytes", "sha256", "archive_path")


def relative_name(name):
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or not name
        or path.is_absolute()
        or path.as_posix() != name
        or any(p in (".", "..") for p in path.parts)
        or any(c in name for c in ("\\", ":", "\n", "\r", '"'))
    ):
        raise ValueError("unsafe relative payload path")
    return path


def no_links(path):
    if any(
        p.is_symlink() or getattr(p, "is_junction", lambda: False)()
        for p in (path, *path.parents)
    ):
        raise ValueError("linked paths are forbidden")


def new_root(value):
    root = Path(value).absolute()
    no_links(root)
    if root.resolve().parent != LOCAL.resolve():
        raise ValueError("output must be a new direct child of .local/validation")
    root.mkdir(parents=True, exist_ok=False)
    return root


def description(path):
    no_links(path)
    return {"bytes": path.stat().st_size, "sha256": file_digest(path)}


def inventory(root, *, exclude=()):
    result = {}
    for path in root.rglob("*"):
        no_links(path)
        if path.is_file():
            name = path.relative_to(root).as_posix()
            relative_name(name)
            if name not in exclude:
                result[name] = description(path)
    if sum(row["bytes"] for row in result.values()) > 1024**3:
        raise ValueError("bundle exceeds its one-GiB preparation scope")
    return result


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def package_union(catalogs):
    result, paths = {}, {}
    for catalog in catalogs:
        for row in catalog["archives"]:
            name, archive = row["name"], row["archive_path"]
            relative_name(archive)
            if not re.fullmatch(
                r"pool/(main|universe)/[A-Za-z0-9/_.+~%-]+\.deb", archive
            ):
                raise ValueError("unsupported publisher archive path")
            previous = result.get(name)
            if previous and any(previous[k] != row[k] for k in IDENTITY):
                raise ValueError("conflicting package identities across roles")
            if archive in paths and paths[archive] != name:
                raise ValueError("publisher archive path collision")
            result[name], paths[archive] = row, name
    return result


def prepare_inputs():
    catalogs = {}
    for kind, digest in CATALOGS.items():
        path = WORKSPACE / "research/validation" / f"{kind}-inputs.json"
        catalogs[kind] = checked_catalog(path.read_bytes(), digest, kind=kind)
    receipts = {}
    for name, digest in RECEIPTS.items():
        root = LOCAL / name
        no_links(root)
        raw = (root / "receipt.json").read_bytes()
        if sha(raw) != digest:
            raise ValueError("source receipt changed")
        receipts[name] = json.loads(raw)
        verify_files(root, receipts[name]["files"])
    archive_sources = {}
    for kind, catalog_digest in CATALOGS.items():
        receipt = receipts[f"{kind}-artifacts-01"]
        if (
            receipt["status"] != "retrieved-not-installed"
            or receipt["catalog_sha256"] != catalog_digest
        ):
            raise ValueError("archive collection is incomplete or from another catalog")
        expected = {r["name"]: r for r in catalogs[kind]["archives"]}
        if len(receipt["archives"]) != len(expected):
            raise ValueError("archive receipt has an incomplete inventory")
        seen = set()
        for row in receipt["archives"]:
            record = expected[row["name"]]
            if (
                row["name"] in seen
                or row["control_identity"] != "pass"
                or any(row[k] != record[k] for k in IDENTITY if k != "archive_path")
            ):
                raise ValueError(
                    "archive receipt differs from selected package identity"
                )
            seen.add(row["name"])
            relative_name(row["filename"])
            source = LOCAL / f"{kind}-artifacts-01" / "archives" / row["filename"]
            if description(source) != {k: row[k] for k in ("bytes", "sha256")}:
                raise ValueError("archive source changed")
            archive_sources[row["sha256"]] = source
    os_resolution = receipts["os-update-resolution-02"]
    engine_resolution = receipts["engine-resolution-02"]
    raw_status = (LOCAL / "os-update-resolution-02/target-status").read_bytes()
    if sha(raw_status) != catalogs["os-update"]["source_status_sha256"]:
        raise ValueError("original target status changed")
    installed = {
        r["Package"]: r["Version"]
        for r in paragraphs(raw_status.decode())
        if r.get("Status") == "install ok installed"
    }
    if len(installed) != 480:
        raise ValueError("unexpected original inventory")
    packages = package_union(catalogs.values())
    roles = {}
    for role in ("executor", "guard"):
        selected = list(os_resolution["profiles"][role]["actions"])
        if role == "executor":
            selected += engine_resolution["actions"]
        if len({r["name"] for r in selected}) != len(selected):
            raise ValueError("overlapping actions in combined role transaction")
        for row in selected:
            if (
                row["old_version"] != installed.get(row["name"])
                or row["version"] != packages[row["name"]]["version"]
            ):
                raise ValueError("role transaction changed its baseline or package pin")
        added = sum(r["old_version"] is None for r in selected)
        roles[role] = {
            "actions": sorted(selected, key=lambda r: r["name"]),
            "counts": {
                "upgrades": len(selected) - added,
                "additions": added,
                "removals": 0,
                "held_back": 0,
            },
            "expected_installed_rows": len(installed) + added,
        }
    return packages, archive_sources, roles, receipts


def build(output):
    packages, sources, roles, receipts = prepare_inputs()
    root = new_root(output)
    manifest = {
        "format": "mcli1-offline-repository-v1",
        "status": "building",
        "installation_approval": None,
        "vm_creation_approval": None,
        "qualifies_runtime": False,
        "source_receipts": RECEIPTS,
        "catalog_sha256": CATALOGS,
        "roles": roles,
        "archives": list(packages.values()),
        "archive_bytes": sum(r["bytes"] for r in packages.values()),
        "signed_releases": [],
        "builder_sha256": sha(Path(__file__).read_bytes()),
    }
    try:

        def copy(source, target, expected):
            destination = root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if description(source) != expected or description(destination) != expected:
                raise ValueError("payload copy changed bytes")

        native = LOCAL / "engine-resolution-02"
        for suite in SUITES:
            host = (
                "security.ubuntu.com"
                if suite == "noble-security"
                else "archive.ubuntu.com"
            )
            prefix = f"{host}_ubuntu_dists_{suite}"
            copy(
                native / f"state/lists/{prefix}_InRelease",
                f"repo/dists/{suite}/InRelease",
                receipts["engine-resolution-02"]["files"][
                    f"state/lists/{prefix}_InRelease"
                ],
            )
            for component in COMPONENTS:
                row = receipts["engine-resolution-02"]["verified_private_indexes"][
                    suite
                ][component]
                source = (
                    native / f"state/lists/{prefix}_{component}_binary-amd64_Packages"
                )
                if description(source) != row:
                    raise ValueError("index differs from the verified signed cohort")
                base = f"repo/dists/{suite}/{component}/binary-amd64"
                copy(source, f"{base}/Packages", row)
                copy(source, f"{base}/by-hash/SHA256/{row['sha256']}", row)
        copy(
            native / "etc/ubuntu-archive-keyring.gpg",
            "keys/ubuntu-archive-keyring.gpg",
            receipts["engine-resolution-02"]["files"]["etc/ubuntu-archive-keyring.gpg"],
        )
        copy(
            LOCAL / "os-update-resolution-02/target-status",
            "baseline/status",
            receipts["os-update-resolution-02"]["files"]["target-status"],
        )
        for kind, catalog_digest in CATALOGS.items():
            source = WORKSPACE / f"research/validation/{kind}-inputs.json"
            copy(
                source,
                f"catalogs/{kind}-inputs.json",
                {"bytes": source.stat().st_size, "sha256": catalog_digest},
            )
        for row in packages.values():
            copy(
                sources[row["sha256"]],
                f"repo/{row['archive_path']}",
                {k: row[k] for k in ("bytes", "sha256")},
            )
        plan = WORKSPACE / "research/validation/offline-install-plan.json"
        copy(
            plan,
            "offline-install-plan.json",
            description(plan),
        )
        for name, digest in RECEIPTS.items():
            if file_digest(LOCAL / name / "receipt.json") != digest:
                raise ValueError("source receipt changed during construction")
        manifest["signed_releases"] = receipts["engine-resolution-02"][
            "signed_releases"
        ]
        manifest["files"] = inventory(root)
        manifest["status"] = "prepared-not-installed"
    except Exception as exc:
        manifest["status"], manifest["error"] = "held", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        write_json(root / "manifest.json", manifest)
    return description(root / "manifest.json")


def checked_bundle(root, expected):
    no_links(root)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected)
        or file_digest(root / "manifest.json") != expected
    ):
        raise ValueError("bundle differs from its external review digest")
    value = json.loads((root / "manifest.json").read_bytes())
    if (
        value["format"] != "mcli1-offline-repository-v1"
        or value["status"] != "prepared-not-installed"
        or value["installation_approval"] is not None
        or value["qualifies_runtime"] is not False
    ):
        raise ValueError("unsupported or incomplete offline preparation")
    if inventory(root, exclude=("manifest.json",)) != value["files"]:
        raise ValueError("offline payload inventory changed")
    return value


def sources_list(bundle):
    uri = (bundle / "repo").resolve().as_uri()
    key = (bundle / "keys/ubuntu-archive-keyring.gpg").resolve().as_posix()
    if not uri.startswith("file:///") or any(c in key for c in (" ", "\n", "\r", "]")):
        raise ValueError("unsupported local mirror path")
    return "".join(
        f"deb [arch=amd64 signed-by={key}] {uri} {suite} main universe\n"
        for suite in SUITES
    )


def check_command(args):
    if args in (
        ["apt-get", "--version"],
        ["gpgv", "--version"],
        ["apt-get", "update", "--error-on=any"],
    ):
        return
    prefix = [
        "apt-get",
        "--simulate",
        "--no-install-recommends",
        "--no-remove",
        "install",
    ]
    if (
        args[:5] != prefix
        or len(args) <= 5
        or any(not re.fullmatch(rf"{NAME}={VERSION}", p) for p in args[5:])
    ):
        raise ValueError(
            "only local metadata refresh and exact-version simulations are allowed"
        )


def materialize_cache(path, source):
    """Replace only APT's exact local-mirror link with a verified private copy."""
    no_links(path.parent)
    expected = description(source)
    linked_target = None
    if path.is_symlink():
        linked_target = path.readlink().as_posix()
        permitted = {source.resolve(strict=True)}
        if source.name == "Packages":
            by_hash = source.parent / "by-hash/SHA256" / expected["sha256"]
            if description(by_hash) != expected:
                raise ValueError("by-hash mirror member differs from the signed index")
            permitted.add(by_hash.resolve(strict=True))
        if path.resolve(strict=True) not in permitted:
            raise ValueError("APT cache link points outside its exact mirror member")
        temporary = path.with_name(path.name + ".verified-copy")
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if description(temporary) != expected:
            raise ValueError("private cache copy changed bytes")
        os.replace(temporary, path)
    if description(path) != expected:
        raise ValueError("private APT cache differs from signed mirror member")
    return {
        "bytes": expected["bytes"],
        "sha256": expected["sha256"],
        "previous_link_target": linked_target,
    }


def check_offline(bundle, expected, output):
    if sys.platform != "linux" or os.getuid() != 1000:
        raise ValueError("offline checking requires the reviewed UID-1000 Linux tools")
    bundle = Path(bundle).absolute()
    manifest = checked_bundle(bundle, expected)
    candidate = Path(output).absolute()
    if candidate.resolve().is_relative_to(bundle.resolve()):
        raise ValueError("checker output must be outside the frozen bundle")
    root = new_root(candidate)
    for folder in (
        "state/lists/partial",
        "cache/archives/partial",
        "log",
        "etc/sources.list.d",
        "etc/apt.conf.d",
        "etc/preferences.d",
        "etc/trusted.gpg.d",
        "gnupg",
        "commands",
        "releases",
        "source",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle / "baseline/status", root / "target-status")
    (root / "etc/sources.list").write_text(sources_list(bundle), encoding="utf-8")
    (root / "apt.config").write_text(
        configuration(root)
        + 'APT::Get::Always-Include-Phased-Updates "true";\nAcquire::IndexTargets::deb::Packages::CompressionTypes "uncompressed";\nAcquire::GzipIndexes "false";\n',
        encoding="utf-8",
    )
    source_paths = [
        Path(__file__),
        *[
            Path(__file__).with_name(n)
            for n in ("fetch_os_updates.py", "guard_packages.py", "os_update_plan.py")
        ],
    ]
    for path in source_paths:
        shutil.copyfile(path, root / "source" / path.name)
    host_status = Path("/var/lib/dpkg/status")
    receipt = {
        "format": "mcli1-offline-repository-check-v1",
        "status": "checking",
        "bundle_manifest_sha256": expected,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "host_status_sha256_before": file_digest(host_status),
        "commands": [],
        "roles": {},
        "source_sha256": {p.name: file_digest(p) for p in source_paths},
    }

    def save():
        write_json(root / "receipt.json", receipt)

    def run(label, args, *, signature=False):
        if not signature:
            check_command(args)
        process = subprocess.Popen(
            args,
            cwd=root,
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "LANG": "C",
                "APT_CONFIG": str(root / "apt.config"),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        row = {
            "label": label,
            "args": args,
            "pid": process.pid,
            "process_group": process.pid,
            "timed_out": False,
        }
        receipt["commands"].append(row)
        save()
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            row["timed_out"] = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        row["exit"] = process.returncode
        for suffix, data in (("stdout", stdout), ("stderr", stderr)):
            (root / "commands" / f"{label}.{suffix}").write_bytes(data)
        save()
        if (
            process.returncode
            or row["timed_out"]
            or max(len(stdout), len(stderr)) > 8 * 1024**2
        ):
            raise ValueError(f"{label} failed or exceeded its capture/deadline scope")
        if not signature and any(
            line.startswith(("W:", "E:"))
            for line in (stdout + stderr).decode().splitlines()
        ):
            raise ValueError(f"{label} reported a metadata warning/error")
        return stdout.decode()

    save()
    try:
        receipt["apt_version"] = run(
            "apt-version", ["apt-get", "--version"]
        ).splitlines()[0]
        receipt["gpgv_version"] = run(
            "gpgv-version", ["gpgv", "--version"]
        ).splitlines()[0]
        releases = []
        for suite in SUITES:
            output_release = root / "releases" / f"{suite}.txt"
            text = run(
                f"signature-{suite}",
                [
                    "gpgv",
                    "--homedir",
                    str(root / "gnupg"),
                    "--keyring",
                    str(bundle / "keys/ubuntu-archive-keyring.gpg"),
                    "--output",
                    str(output_release),
                    "--status-fd",
                    "1",
                    str(bundle / f"repo/dists/{suite}/InRelease"),
                ],
                signature=True,
            )
            if f"[GNUPG:] VALIDSIG {FINGERPRINT} " not in text:
                raise ValueError("unexpected Ubuntu signing key")
            raw = output_release.read_text()
            release = paragraphs(raw)[0]
            dated = release_dates(raw, datetime.now(timezone.utc))
            if dated["suite"] != suite:
                raise ValueError("signed suite does not match mirror layout")
            releases.append(dated)
            indexes = {
                name: {"bytes": int(size), "sha256": digest}
                for digest, size, name in (
                    line.split()
                    for line in release["SHA256"].splitlines()
                    if line.strip()
                )
            }
            for component in COMPONENTS:
                name = f"{component}/binary-amd64/Packages"
                if description(bundle / f"repo/dists/{suite}/{name}") != indexes[name]:
                    raise ValueError("local mirror index differs from signed release")
        if sorted(releases, key=lambda r: r["suite"]) != sorted(
            manifest["signed_releases"], key=lambda r: r["suite"]
        ):
            raise ValueError("signed release cohort changed")
        run("local-metadata-update", ["apt-get", "update", "--error-on=any"])
        receipt["verified_private_indexes"] = {}
        receipt["private_cache_materialization"] = {}
        for suite in SUITES:
            release_matches = list((root / "state/lists").glob(f"*_{suite}_InRelease"))
            if len(release_matches) != 1:
                raise ValueError("private APT cache lacks the signed release")
            receipt["private_cache_materialization"][f"{suite}/InRelease"] = (
                materialize_cache(
                    release_matches[0], bundle / f"repo/dists/{suite}/InRelease"
                )
            )
            for component in COMPONENTS:
                matches = list(
                    (root / "state/lists").glob(
                        f"*_{suite}_{component}_binary-amd64_Packages"
                    )
                )
                wanted = description(
                    bundle / f"repo/dists/{suite}/{component}/binary-amd64/Packages"
                )
                if len(matches) != 1:
                    raise ValueError("private APT cache lacks an exact signed index")
                receipt["private_cache_materialization"][f"{suite}/{component}"] = (
                    materialize_cache(
                        matches[0],
                        bundle
                        / f"repo/dists/{suite}/{component}/binary-amd64/Packages",
                    )
                )
                receipt["verified_private_indexes"][f"{suite}/{component}"] = wanted
        baseline = {
            r["Package"]: r["Version"]
            for r in paragraphs((root / "target-status").read_text())
            if r.get("Status") == "install ok installed"
        }
        for role, proposal in manifest["roles"].items():
            pins = [f"{r['name']}={r['version']}" for r in proposal["actions"]]
            raw = run(
                f"simulate-{role}",
                [
                    "apt-get",
                    "--simulate",
                    "--no-install-recommends",
                    "--no-remove",
                    "install",
                    *pins,
                ],
            )
            selected, counts = actions(raw, baseline, require_nftables=role == "guard")
            if (
                sorted(selected, key=lambda r: r["name"]) != proposal["actions"]
                or counts != proposal["counts"]
                or len(baseline) + counts["additions"]
                != proposal["expected_installed_rows"]
            ):
                raise ValueError(
                    "offline role transaction differs from its frozen pins"
                )
            receipt["roles"][role] = {
                "counts": counts,
                "expected_installed_rows": proposal["expected_installed_rows"],
                "actions": selected,
            }
        checked_bundle(bundle, expected)
        if (root / "target-status").read_bytes() != (
            bundle / "baseline/status"
        ).read_bytes():
            raise ValueError("private target status changed")
        receipt["status"] = "verified-offline-not-installed"
    except Exception as exc:
        receipt["status"], receipt["error"] = "held", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["host_status_sha256_after"] = file_digest(host_status)
        if receipt["host_status_sha256_after"] != receipt[
            "host_status_sha256_before"
        ] or receipt["source_sha256"] != {p.name: file_digest(p) for p in source_paths}:
            receipt["status"] = "held-input-or-host-changed"
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        try:
            receipt["files"] = inventory(root, exclude=("receipt.json",))
        except (OSError, ValueError) as exc:
            receipt["status"] = "held-inventory-unsealed"
            receipt["inventory_error"] = f"{type(exc).__name__}: {exc}"
        save()
    if receipt["status"] != "verified-offline-not-installed":
        raise ValueError("offline check held; preserve its receipt")
    return description(root / "receipt.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--check-offline", action="store_true")
    parser.add_argument("--bundle", default=str(LOCAL / "offline-repository-01"))
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.build:
        result = build(args.output or args.bundle)
    elif args.check_offline:
        if not args.manifest_sha256 or not args.output:
            parser.error("offline checking needs --manifest-sha256 and new --output")
        result = check_offline(args.bundle, args.manifest_sha256, args.output)
    else:
        packages, _, roles, _ = prepare_inputs()
        result = {
            "status": "preview-only",
            "unique_archives": len(packages),
            "archive_bytes": sum(r["bytes"] for r in packages.values()),
            "roles": {
                name: {k: v for k, v in row.items() if k != "actions"}
                for name, row in roles.items()
            },
            "installation_approval": None,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
