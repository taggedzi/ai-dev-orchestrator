"""Prepare signed Ubuntu package inputs for the guard; never install packages.

Collection runs on the existing Ubuntu 24.04 WSL tooling with private APT state
and the stopped target's package status. Default invocation is a preview only.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
STATUS = ".local/validation/guard-preparation-02/dpkg-status.stdout"
EVIDENCE = "research/validation/guard-preparation-evidence.json"
SOURCES = (
    "deb [arch=amd64 signed-by={keyring}] https://archive.ubuntu.com/ubuntu noble main",
    "deb [arch=amd64 signed-by={keyring}] https://archive.ubuntu.com/ubuntu noble-updates main",
    "deb [arch=amd64 signed-by={keyring}] https://security.ubuntu.com/ubuntu noble-security main",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def paragraphs(raw):
    """Read deb822 fields without interpreting their content as commands."""
    rows, row, previous = [], {}, None
    for line in raw.splitlines() + [""]:
        if not line:
            if row:
                rows.append(row)
            row, previous = {}, None
        elif line[0].isspace():
            if previous is None:
                raise ValueError("orphan deb822 continuation")
            row[previous] += "\n" + line
        else:
            key, separator, value = line.partition(":")
            if not separator or key in row:
                raise ValueError("invalid or duplicate deb822 field")
            row[key], previous = value.lstrip(), key
    return rows


def additions(simulation):
    result = []
    for line in simulation.splitlines():
        if line.startswith(("Remv ", "Purg ")):
            raise ValueError("package removal is outside this preparation")
        if not line.startswith("Inst "):
            continue
        match = re.fullmatch(r"Inst ([a-z0-9][a-z0-9+.-]*) \(([^ ]+) [^\r\n]+\)", line)
        if not match:
            raise ValueError("upgrade or unsupported APT simulation row")
        name, version = match.groups()
        if not re.fullmatch(r"[A-Za-z0-9:.+~_-]+", version):
            raise ValueError("unsupported package version")
        if name in {item["name"] for item in result}:
            raise ValueError("duplicate APT action")
        result.append({"name": name, "version": version})
    if not result or len(result) > 20 or "nftables" not in {r["name"] for r in result}:
        raise ValueError("unexpected guard package set")
    return result


def package_record(raw, name, version, *, max_bytes=8 * 1024**2):
    matches = [
        row
        for row in paragraphs(raw)
        if row.get("Package") == name and row.get("Version") == version
    ]
    if not matches or any(row != matches[0] for row in matches):
        raise ValueError("ambiguous/missing exact package metadata")
    row = matches[0]
    filename, digest, size = (
        row.get("Filename", ""),
        row.get("SHA256", ""),
        row.get("Size", ""),
    )
    if (
        row.get("Architecture") not in ("amd64", "all")
        or not re.fullmatch(r"pool/main/[A-Za-z0-9/_.+~%:-]+\.deb", filename)
        or ".." in filename.split("/")
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not size.isdecimal()
        or not 0 < int(size) <= max_bytes
    ):
        raise ValueError("invalid package location, architecture, size or digest")
    return {
        "name": name,
        "version": version,
        "architecture": row["Architecture"],
        "archive_path": filename,
        "filename": filename.rsplit("/", 1)[1],
        "bytes": int(size),
        "sha256": digest,
        "depends": row.get("Depends", ""),
        "pre_depends": row.get("Pre-Depends", ""),
    }


def configuration(root):
    path = root.as_posix()
    if any(c in path for c in ('"', "\\", "\n", "\r")):
        raise ValueError("unsupported APT configuration path")
    settings = {
        "Dir": path,
        "Dir::State": "state",
        "Dir::State::status": f"{path}/target-status",
        "Dir::State::lists": "lists",
        "Dir::Cache": "cache",
        "Dir::Cache::archives": "archives",
        "Dir::Log": "log",
        "Dir::Etc": "etc",
        "Dir::Etc::sourcelist": "sources.list",
        "Dir::Etc::sourceparts": "sources.list.d",
        "Dir::Etc::main": "apt.conf",
        "Dir::Etc::parts": "apt.conf.d",
        "Dir::Etc::preferences": "preferences",
        "Dir::Etc::preferencesparts": "preferences.d",
        "Dir::Etc::trusted": "ubuntu-archive-keyring.gpg",
        "Dir::Etc::trustedparts": "trusted.gpg.d",
        "APT::Architecture": "amd64",
        "APT::Install-Recommends": "false",
        "APT::Install-Suggests": "false",
        "APT::Get::AllowUnauthenticated": "false",
        "Acquire::AllowInsecureRepositories": "false",
        "Acquire::AllowDowngradeToInsecureRepositories": "false",
        "Acquire::Check-Valid-Until": "true",
        "Acquire::Check-Date": "true",
        "Acquire::Languages": "none",
        "Acquire::Retries": "0",
        "Acquire::http::Timeout": "20",
        "Acquire::https::Timeout": "20",
        "Acquire::https::Verify-Peer": "true",
        "Acquire::https::Verify-Host": "true",
        "Acquire::PDiffs": "false",
        "Acquire::IndexTargets::deb::DEP-11::DefaultEnabled": "false",
        "Acquire::IndexTargets::deb::CNF::DefaultEnabled": "false",
    }
    return (
        "\n".join(f'{key} "{value}";' for key, value in settings.items())
        + '\nAPT::Architectures { "amd64"; };\n'
    )


def collect(output, approval):
    if sys.platform != "linux" or not approval.strip():
        raise ValueError(
            "collection requires reviewed Linux tooling and a retrieval approval reference"
        )
    candidate = Path(output).absolute()
    if any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("linked output paths are forbidden")
    root = candidate.resolve()
    root.relative_to((WORKSPACE / ".local/validation").resolve())
    evidence_raw = (WORKSPACE / EVIDENCE).read_bytes()
    expected = json.loads(evidence_raw)["raw_evidence_files"]["dpkg-status.stdout"][
        "sha256"
    ]
    status = (WORKSPACE / STATUS).read_bytes()
    if sha(status) != expected:
        raise ValueError("target package status differs from stopped-image evidence")
    rows = paragraphs(status.decode())
    if len([r for r in rows if r.get("Status") == "install ok installed"]) != 480:
        raise ValueError("unexpected target status inventory")
    root.mkdir(parents=True, exist_ok=False)
    for folder in (
        "etc/apt.conf.d",
        "etc/sources.list.d",
        "etc/preferences.d",
        "etc/trusted.gpg.d",
        "state/lists/partial",
        "cache/archives/partial",
        "log",
        "gnupg",
        "archives",
        "commands",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "target-status").write_bytes(status)
    (root / "apt.config").write_text(configuration(root))
    keyring = root / "etc/ubuntu-archive-keyring.gpg"
    keyring.write_bytes(
        Path("/usr/share/keyrings/ubuntu-archive-keyring.gpg").read_bytes()
    )
    (root / "etc/sources.list").write_text(
        "\n".join(s.format(keyring=keyring) for s in SOURCES) + "\n"
    )
    environment = {
        **os.environ,
        "APT_CONFIG": str(root / "apt.config"),
        "LC_ALL": "C",
        "LANG": "C",
    }
    host_status = Path("/var/lib/dpkg/status")
    source_hash = sha(Path(__file__).read_bytes())
    before = sha(host_status.read_bytes())
    receipt = {
        "schema_version": 1,
        "status": "collecting",
        "approval": approval,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "signed metadata, simulated target resolution and archive download only; no installation, VM or network changes",
        "source_sha256": source_hash,
        "target_status_sha256": expected,
        "preparation_evidence_sha256": sha(evidence_raw),
        "keyring_sha256": sha(keyring.read_bytes()),
        "host_status_sha256_before": before,
        "commands": [],
    }

    def save():
        temporary = root / "receipt.next"
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temporary.replace(root / "receipt.json")

    def run(label, args, cwd=None):
        result = subprocess.run(
            args,
            env=environment,
            cwd=cwd or root,
            capture_output=True,
            timeout=240,
            check=False,
        )
        (root / "commands" / (label + ".stdout")).write_bytes(result.stdout)
        (root / "commands" / (label + ".stderr")).write_bytes(result.stderr)
        receipt["commands"].append(
            {"label": label, "args": args, "exit": result.returncode}
        )
        save()
        if result.returncode:
            raise ValueError(f"{label} failed; retain evidence and do not install")
        return result.stdout.decode()

    save()
    try:
        for binary in ("apt-get", "apt-cache", "gpgv", "dpkg-deb"):
            run(binary + "-version", [binary, "--version"])
        run("effective-config", ["apt-config", "dump"])
        run("update", ["apt-get", "--error-on=any", "update"])
        signatures = []
        releases = sorted((root / "state/lists").glob("*_InRelease"))
        if len(releases) != 3:
            raise ValueError("missing signed suite metadata")
        for number, release in enumerate(releases):
            output = run(
                f"signature-{number}",
                [
                    "gpgv",
                    "--homedir",
                    str(root / "gnupg"),
                    "--keyring",
                    str(keyring),
                    "--status-fd",
                    "1",
                    str(release),
                ],
            )
            fingerprints = re.findall(
                r"^\[GNUPG:\] VALIDSIG ([0-9A-F]+) ", output, re.MULTILINE
            )
            if not fingerprints:
                raise ValueError("no valid archive signature")
            signatures.append(
                {
                    "file": release.name,
                    "sha256": sha(release.read_bytes()),
                    "signing_fingerprints": fingerprints,
                }
            )
        selected = additions(
            run(
                "simulate",
                [
                    "apt-get",
                    "--simulate",
                    "--no-install-recommends",
                    "--no-remove",
                    "install",
                    "nftables",
                ],
            )
        )
        records = [
            package_record(
                run(
                    "metadata-" + r["name"],
                    ["apt-cache", "show", r["name"] + "=" + r["version"]],
                ),
                r["name"],
                r["version"],
            )
            for r in selected
        ]
        if sum(r["bytes"] for r in records) > 16 * 1024**2:
            raise ValueError("package set exceeds preparation size bound")
        run(
            "download",
            [
                "apt-get",
                "download",
                *(r["name"] + "=" + r["version"] for r in selected),
            ],
            root / "archives",
        )
        archives = sorted((root / "archives").glob("*.deb"))
        if len(archives) != len(records):
            raise ValueError("unexpected archive inventory")
        for record in records:
            matches = [
                p
                for p in archives
                if sha(p.read_bytes()) == record["sha256"]
                and p.stat().st_size == record["bytes"]
            ]
            if len(matches) != 1:
                raise ValueError("archive differs from signed package metadata")
            p = matches[0]
            fields = run(
                "archive-" + record["name"],
                ["dpkg-deb", "--field", str(p), "Package", "Version", "Architecture"],
            )
            parsed = paragraphs(fields)[0]
            if (
                parsed.get("Package"),
                parsed.get("Version"),
                parsed.get("Architecture"),
            ) != (record["name"], record["version"], record["architecture"]):
                raise ValueError("archive control metadata differs")
            record["local_filename"] = p.name
        receipt.update(
            {
                "status": "collected-not-installed",
                "signatures": signatures,
                "packages": records,
            }
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        receipt.update({"status": "hold", "error": str(exc)})
    receipt["host_status_sha256_after"] = sha(host_status.read_bytes())
    receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    if (
        before != receipt["host_status_sha256_after"]
        or source_hash != sha(Path(__file__).read_bytes())
        or status != (root / "target-status").read_bytes()
    ):
        receipt.update(
            {
                "status": "hold",
                "error": "source, host status or target status changed during collection",
            }
        )
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
    parser.add_argument("--output", default=".local/validation/guard-packages-01")
    parser.add_argument("--collect-approval")
    args = parser.parse_args()
    if not args.collect_approval:
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "package": "nftables",
                    "target_status": STATUS,
                    "suites": ["noble", "noble-updates", "noble-security"],
                    "component": "main",
                    "architecture": "amd64",
                    "install": False,
                }
            )
        )
        return
    result = collect(WORKSPACE / args.output, args.collect_approval)
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in (
                    "status",
                    "packages",
                    "error",
                    "host_status_sha256_before",
                    "host_status_sha256_after",
                )
            }
        )
    )
    if result["status"] != "collected-not-installed":
        sys.exit(1)


if __name__ == "__main__":
    main()
