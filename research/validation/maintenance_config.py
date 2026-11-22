"""Render and inspect proposed guest APT configuration; no installation path."""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from .guard_packages import WORKSPACE, sha
from .offline_repo import description, file_digest, inventory, new_root, write_json

PROPOSAL = WORKSPACE / "research/validation/maintenance-procedure.json"
PROPOSAL_SHA256 = "42b91618b6f35639aee882e9654a7e8df20ef530b6cc5de23663f2400141d232"
PRIVATE_ETC = "/run/mcli1-maintenance/apt"
MIRROR_SHA256 = "007c21f71b69a3741fffe3edbc24b7757d55805755163ffe04a19083d0e52570"


def proposal(raw):
    if sha(raw) != PROPOSAL_SHA256:
        raise ValueError("maintenance proposal differs from its external review pin")
    value = json.loads(raw)
    if (
        value["status"] != "proposed-maintenance-procedure-not-approved-not-applied"
        or any(v is not None for v in value["authority"].values())
        or value["runtime_or_security_qualified"] is not False
        or value["frozen_mirror_manifest"]["sha256"] != MIRROR_SHA256
    ):
        raise ValueError("proposal is outside configuration preparation")
    return value


def settings(value):
    result = dict(value["apt_configuration_proposal"])
    required = {
        "Dir": "/",
        "Dir::Etc": PRIVATE_ETC,
        "Dir::State::status": "/var/lib/dpkg/status",
        "Dir::Bin::dpkg": "/usr/bin/dpkg",
        "APT::Get::AllowUnauthenticated": "false",
        "Acquire::AllowInsecureRepositories": "false",
        "Acquire::AllowDowngradeToInsecureRepositories": "false",
        "Acquire::Check-Date": "true",
        "Acquire::Check-Valid-Until": "true",
    }
    if any(result.get(k) != v for k, v in required.items()):
        raise ValueError("guest configuration lost its real root or signature boundary")
    # Make the proposal's private-cache requirement explicit for binary caches too.
    result.update(
        {
            "Dir::Cache": "/var/cache/mcli1-maintenance",
            "Dir::Cache::pkgcache": "",
            "Dir::Cache::srcpkgcache": "",
            "Dir::Log": "/var/log/mcli1-maintenance",
            "Debug::NoLocking": "false",
        }
    )
    for key, item in result.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9:._/-]*", key) or any(
            c in item for c in ('"', "\\", "\n", "\r")
        ):
            raise ValueError("unsupported APT configuration token")
    return result


def render(value):
    values = settings(value)
    hooks = [
        "DPkg::Pre-Invoke",
        "DPkg::Post-Invoke",
        "DPkg::Pre-Install-Pkgs",
        "APT::Update::Pre-Invoke",
        "APT::Update::Post-Invoke",
        "APT::Update::Post-Invoke-Success",
        "Binary::apt::AptCli::Hooks",
    ]
    return (
        "// Preparation preview. Applying requires a separately bound runner/target.\n"
        + "\n".join(f'{k} "{v}";' for k, v in values.items())
        + '\n#clear APT::Architectures;\nAPT::Architectures { "amd64"; };\n'
        + "".join(f"#clear {key};\n" for key in hooks)
    )


def sources():
    return "".join(
        "deb [arch=amd64 signed-by=/media/mcli1-maintenance/keys/ubuntu-archive-keyring.gpg] "
        f"file:///media/mcli1-maintenance/repo {suite} main universe\n"
        for suite in ("noble", "noble-updates", "noble-security")
    )


def validate_dump(raw, expected):
    rows = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'([A-Za-z0-9:._/+~-]+) "(.*)";', line)
        if not match:
            raise ValueError("unsupported native APT dump framing")
        key, value = match.groups()
        rows.setdefault(key.casefold(), []).append(value)
        lowered = key.casefold()
        if value and any(t in lowered for t in ("hook", "invoke", "pre-install-pkgs")):
            raise ValueError("native configuration contains a command hook")
        if lowered.startswith("dpkg::options") and value != "--force-confold" and value:
            raise ValueError("native configuration contains unreviewed dpkg options")
    if any(
        rows.get(k.casefold()) != [v]
        for k, v in expected.items()
        if k.casefold() != "acquire::languages"
    ):
        raise ValueError("native configuration changed an effective critical option")
    # APT normalizes scalar Languages=none into the equivalent one-element list.
    if (
        expected.get("Acquire::Languages") != "none"
        or rows.get("acquire::languages") != [""]
        or rows.get("acquire::languages::") != ["none"]
    ):
        raise ValueError("native translation language list is not exactly disabled")
    if rows.get("apt::architectures::") != ["amd64"]:
        raise ValueError("native architecture list differs from the one reviewed")
    return dict(expected)


def prepare(output):
    raw = PROPOSAL.read_bytes()
    value = proposal(raw)
    root = new_root(output)
    (root / "apt.config").write_bytes(render(value).encode())
    (root / "sources.list").write_bytes(sources().encode())
    (root / "maintenance-procedure.json").write_bytes(raw)
    (root / "maintenance_config.py").write_bytes(Path(__file__).read_bytes())
    profile = {
        "format": "mcli1-maintenance-config-preview-v1",
        "status": "prepared-not-applied",
        "proposal_sha256": PROPOSAL_SHA256,
        "mirror_manifest_sha256": MIRROR_SHA256,
        "settings": settings(value),
        "guest_paths_created": False,
        "installation_authority": None,
        "files": inventory(root),
    }
    write_json(root / "profile.json", profile)
    return description(root / "profile.json")


def checked_profile(root, expected):
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected)
        or file_digest(root / "profile.json") != expected
    ):
        raise ValueError("candidate profile differs from its external review digest")
    value = json.loads((root / "profile.json").read_bytes())
    desired = proposal((root / "maintenance-procedure.json").read_bytes())
    if (
        value["format"] != "mcli1-maintenance-config-preview-v1"
        or value["status"] != "prepared-not-applied"
        or value["installation_authority"] is not None
        or value["settings"] != settings(desired)
        or value["proposal_sha256"] != PROPOSAL_SHA256
        or value["mirror_manifest_sha256"] != MIRROR_SHA256
        or (root / "apt.config").read_bytes() != render(desired).encode()
        or (root / "sources.list").read_bytes() != sources().encode()
        or inventory(root, exclude=("profile.json",)) != value["files"]
    ):
        raise ValueError("candidate profile changed its exact bytes or authority")
    return value


def check_native(candidate, expected, output):
    if sys.platform != "linux" or os.getuid() != 1000:
        raise ValueError("native inspection requires the reviewed UID-1000 Linux tools")
    candidate = Path(candidate).absolute()
    profile = checked_profile(candidate, expected)
    if Path(PRIVATE_ETC).exists():
        raise ValueError(
            "refuse to read existing guest-named configuration on the tool host"
        )
    root = new_root(output)
    (root / "commands").mkdir()
    (root / "cases").mkdir()
    source = Path(__file__).read_bytes()
    (root / "maintenance_config.py").write_bytes(source)
    before = file_digest(Path("/var/lib/dpkg/status"))
    receipt = {
        "format": "mcli1-maintenance-config-check-v1",
        "status": "checking",
        "profile_sha256": expected,
        "checker_source_sha256": sha(source),
        "scope": "apt-config version/dump only; no apt-get, installation, hook execution or guest path creation",
        "host_status_sha256_before": before,
        "commands": [],
        "negative_cases": [],
    }

    def save():
        write_json(root / "receipt.json", receipt)

    def run(label, config, *, version=False):
        args = ["/usr/bin/apt-config", "--version" if version else "dump"]
        process = subprocess.Popen(
            args,
            env={
                "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                "LC_ALL": "C",
                "LANG": "C",
                "APT_CONFIG": str(config),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        record = {
            "label": label,
            "args": args,
            "config": str(config),
            "pid": process.pid,
            "process_group": process.pid,
            "timed_out": False,
        }
        receipt["commands"].append(record)
        save()
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            record["timed_out"] = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        record["exit"] = process.returncode
        for suffix, data in (("stdout", stdout), ("stderr", stderr)):
            (root / "commands" / f"{label}.{suffix}").write_bytes(data)
        save()
        if (
            process.returncode
            or record["timed_out"]
            or (
                stderr
                and not (
                    label == "guest-profile"
                    and stderr.decode()
                    == f"W: Unable to read {PRIVATE_ETC}/apt.conf.d/ - DirectoryExists (2: No such file or directory)\n"
                )
            )
            or max(len(stdout), len(stderr)) > 2 * 1024**2
        ):
            raise ValueError("native configuration parser failed or exceeded its scope")
        return stdout.decode()

    save()
    try:
        receipt["apt_version"] = run(
            "apt-version", candidate / "apt.config", version=True
        ).strip()
        receipt["effective_settings"] = validate_dump(
            run("guest-profile", candidate / "apt.config"), profile["settings"]
        )
        receipt["guest_directory_warning"] = (
            "Expected absent guest-named parts directory on the WSL tool host; no guest paths created"
        )
        private = root / "private-etc"
        for name in ("apt.conf.d", "sources.list.d", "preferences.d", "trusted.gpg.d"):
            (private / name).mkdir(parents=True)
        for name in ("apt.conf", "preferences"):
            (private / name).write_bytes(b"")
        shadow = root / "shadow.config"
        shadow.write_bytes(
            (candidate / "apt.config").read_bytes()
            + f'Dir::Etc "{private.as_posix()}";\n'.encode()
        )
        shadow_settings = {**profile["settings"], "Dir::Etc": private.as_posix()}
        receipt["staged_effective_settings"] = validate_dump(
            run("workspace-private-profile", shadow), shadow_settings
        )
        cases = {
            "copied-status": 'Dir::State::status "/run/mcli1-maintenance/target-status";',
            "alternate-root": 'Dir "/run/mcli1-maintenance/planning-root";',
            "command-hook": 'DPkg::Post-Invoke { "/usr/bin/false"; };',
            "unsigned": 'APT::Get::AllowUnauthenticated "true";',
            "locking-disabled": 'Debug::NoLocking "true";',
            "wrong-dpkg": 'Dir::Bin::dpkg "/usr/bin/true";',
        }
        for name, addition in cases.items():
            path = root / "cases" / f"{name}.config"
            path.write_bytes(shadow.read_bytes() + (addition + "\n").encode())
            dumped = run(name, path)
            try:
                validate_dump(dumped, shadow_settings)
            except ValueError as exc:
                receipt["negative_cases"].append({"case": name, "rejected": str(exc)})
            else:
                raise ValueError("unsafe native configuration escaped a refusal check")
        # A parts file loads after APT_CONFIG: prove a reintroduced hook is caught.
        (private / "apt.conf.d/70-sentinel.conf").write_bytes(
            b'DPkg::Post-Invoke { "/usr/bin/false"; };\n'
        )
        late_dump = run("late-parts-hook", shadow)
        try:
            validate_dump(late_dump, shadow_settings)
        except ValueError as exc:
            receipt["negative_cases"].append(
                {"case": "late-parts-hook", "rejected": str(exc)}
            )
        else:
            raise ValueError("a late configuration hook escaped admission")
        checked_profile(candidate, expected)
        receipt["status"] = "native-parser-verified-not-applied"
    except Exception as exc:
        receipt["status"], receipt["error"] = "held", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["host_status_sha256_after"] = file_digest(Path("/var/lib/dpkg/status"))
        if (
            receipt["host_status_sha256_after"] != before
            or Path(__file__).read_bytes() != source
        ):
            receipt["status"] = "held-host-or-source-changed"
        receipt["files"] = inventory(root, exclude=("receipt.json",))
        save()
    if receipt["status"] != "native-parser-verified-not-applied":
        raise ValueError("native parser check held")
    return description(root / "receipt.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--check-native", action="store_true")
    parser.add_argument(
        "--candidate", default=".local/validation/maintenance-config-01"
    )
    parser.add_argument("--profile-sha256")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.prepare:
        result = prepare(args.output or args.candidate)
    elif args.check_native:
        if not args.profile_sha256 or not args.output:
            parser.error("native checking needs an external profile SHA and new output")
        result = check_native(args.candidate, args.profile_sha256, args.output)
    else:
        desired = proposal(PROPOSAL.read_bytes())
        result = {
            "status": "preview-only",
            "proposal_sha256": PROPOSAL_SHA256,
            "settings": settings(desired),
            "sources": sources().splitlines(),
            "apply_available": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
