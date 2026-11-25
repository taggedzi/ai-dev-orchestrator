"""Prepare pinned GSD and measure read-only exports of synthetic planning input."""

import argparse
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import unicodedata
import urllib.request
from pathlib import Path

from .bundle import Objects, digest, inventory, load_json, safe_path, verify, write
from .fixture import canonical
from .os_install import WORKSPACE, rooted
from .store import Hold

VERSION = "1.21.0"
COMMIT = "357508df233ccca0dcf4332b385d6bee9b113da9"
METADATA_URL = "https://registry.npmjs.org/@opengsd%2fgsd-core/1.21.0"
TARBALL_URL = "https://registry.npmjs.org/@opengsd/gsd-core/-/gsd-core-1.21.0.tgz"
INTEGRITY = "sha512-qccKXCfMny+UMYO7rDZWz83oy6JWd1D3QR/2WUbcjd7N0WZBhr9/+hsXQ5nVaf423W/GSspMjSqT+ZsQNeCLUQ=="
MAX_FILES = 3000
MAX_FILE = 8 * 1024**2
MAX_UNPACKED = 64 * 1024**2
CLI = "package/gsd-core/bin/gsd-tools.cjs"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch(url, limit):
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(url, timeout=30) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise Hold("upstream response exceeds preparation bound")
    return raw


def check_metadata(raw):
    data = load_json(raw)
    if (
        data.get("name") != "@opengsd/gsd-core"
        or data.get("version") != VERSION
        or data.get("gitHead") != COMMIT
        or data.get("dist", {}).get("tarball") != TARBALL_URL
        or data["dist"].get("integrity") != INTEGRITY
        or data.get("engines", {}).get("node") != ">=24.0.0"
    ):
        raise Hold("npm metadata differs from the reviewed GSD pin")
    return data


def unpack(archive, destination=None):
    names, aliases, total = set(), {}, 0
    files = {}
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        prefix + str(number) for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            name = member.name.rstrip("/") if member.isdir() else member.name
            path = safe_path(name)
            if path.parts[0] != "package" or any(
                part.endswith((".", " "))
                or part.split(".")[0].upper() in reserved
                or any(ord(c) < 32 for c in part)
                for part in path.parts
            ):
                raise Hold("unsafe package archive path")
            for end in range(1, len(path.parts) + 1):
                prefix = "/".join(path.parts[:end])
                key = unicodedata.normalize("NFC", prefix).casefold()
                if aliases.setdefault(key, prefix) != prefix:
                    raise Hold("package archive path alias")
            if member.isdir():
                continue
            if not member.isfile() or name in names:
                raise Hold("package archive link, special file, or duplicate")
            names.add(name)
            total += member.size
            if (
                len(names) > MAX_FILES
                or not 0 <= member.size <= MAX_FILE
                or total > MAX_UNPACKED
            ):
                raise Hold("package archive exceeds preparation bounds")
            data = source.extractfile(member).read(MAX_FILE + 1)
            if len(data) != member.size:
                raise Hold("truncated package member")
            files[str(path.relative_to("package"))] = {
                "bytes": len(data),
                "sha256": digest(data),
                "mode": "100644",
            }
            if destination is not None:
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(data)
    return {"files": len(names), "bytes": total, "inventory": files}


def verify_archive(raw):
    expected = base64.b64decode(INTEGRITY.removeprefix("sha512-"), validate=True)
    if len(raw) > 16 * 1024**2 or hashlib.sha512(raw).digest() != expected:
        raise Hold("published GSD package integrity mismatch")


def prepare(output, approval):
    if not approval:
        raise Hold("GSD package preparation approval required")
    output = rooted(output)
    output.mkdir(parents=True, exist_ok=False)
    raw = fetch(METADATA_URL, 1024**2)
    metadata = check_metadata(raw)
    write(output, "registry-metadata.json", raw)
    archive = fetch(TARBALL_URL, 16 * 1024**2)
    verify_archive(archive)
    write(output, "package.tgz", archive)
    extracted = unpack(output / "package.tgz", output)
    package_files = extracted.pop("inventory")
    if extracted != {
        "files": metadata["dist"]["fileCount"],
        "bytes": metadata["dist"]["unpackedSize"],
    }:
        raise Hold("package member inventory differs from npm metadata")
    if not (output / "package/gsd-core/bin/lib/cli-exit.cjs").is_file():
        raise Hold("published compiled runtime missing; never bootstrap a compiler")
    if inventory(output / "package") != package_files:
        raise Hold("extracted package bytes do not match the verified archive")
    result = {
        "schema_version": 1,
        "classification": "downloaded package, no install scripts or CLI executed",
        "approval": approval,
        "version": VERSION,
        "git_head": COMMIT,
        "metadata_sha256": digest(raw),
        "tarball_sha256": digest(archive),
        "tarball_integrity": INTEGRITY,
        "registry_signatures_verified": False,
        "files": inventory(output / "package"),
        "extracted": extracted,
    }
    write(output, "preparation-receipt.json", canonical(result) + b"\n")
    return result


def environment(home):
    keep = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH"}
    result = {key: value for key, value in os.environ.items() if key.upper() in keep}
    for name in ("HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR"):
        result[name] = str(home)
    result.update(
        NODE_DISABLE_COMPILE_CACHE="1",
        NO_COLOR="1",
        CI="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_COUNT="0",
    )
    return result


def export(package, bundle, manifest_hash, output, approval):
    if not approval:
        raise Hold("read-only GSD query approval required")
    package, output = rooted(package), rooted(output)
    source_paths = [
        Path(__file__),
        Path(__file__).with_name("bundle.py"),
        Path(__file__).with_name("fixture.py"),
    ]
    source_pins = {path.name: digest(path.read_bytes()) for path in source_paths}
    receipt = load_json((package / "preparation-receipt.json").read_bytes())
    if receipt.get("version") != VERSION or receipt.get("git_head") != COMMIT:
        raise Hold("wrong prepared GSD version")
    # Authenticate the execution tree against the fixed archive integrity, not
    # merely a colocated receipt which could have been changed alongside it.
    verify_archive((package / "package.tgz").read_bytes())
    if inventory(package / "package") != unpack(package / "package.tgz")[
        "inventory"
    ] or inventory(package / "package") != receipt.get("files"):
        raise Hold("prepared GSD package changed")
    manifest = verify(bundle, expected_digest=manifest_hash)
    node = shutil.which("node")
    if not node:
        raise Hold("installed Node required; do not install automatically")
    output.mkdir(parents=True, exist_ok=False)
    home = output / "isolated-home"
    home.mkdir()
    env = environment(home)
    version = (
        subprocess.run(
            [node, "--version"], capture_output=True, check=True, timeout=10, env=env
        )
        .stdout.decode()
        .strip()
    )
    if (
        not re.fullmatch(r"v\d+\.\d+\.\d+", version)
        or int(version[1:].split(".")[0]) < 24
    ):
        raise Hold(
            "GSD planning runtime requires Node >=24; fixture Node pin is separate"
        )
    project = output / "planning-input"
    project.mkdir()
    files = {}
    for name in manifest["files"]:
        if name.startswith("planning/.planning/"):
            relative = name.removeprefix("planning/")
            raw = Path(bundle, name).read_bytes()
            files[relative] = raw.decode("utf-8")
            write(project, relative, raw)
    if not files:
        raise Hold("frozen raw planning files missing")
    objects = Objects(project / ".git")
    commit = objects.commit(files, [], 0, "Frozen M-CLI1 planning input")
    write(project, ".git/HEAD", "ref: refs/heads/planning\n")
    write(project, ".git/refs/heads/planning", commit["oid"] + "\n")
    write(
        project,
        ".git/config",
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tautocrlf = false\n\thooksPath = /dev/null\n",
    )
    git = shutil.which("git")
    if not git:
        raise Hold("installed Git required for the isolated planning fixture")
    subprocess.run(
        [git, "-C", str(project), "read-tree", "HEAD"],
        env=env,
        capture_output=True,
        timeout=10,
        check=True,
    )
    status = subprocess.run(
        [git, "-C", str(project), "status", "--porcelain=v1", "--untracked-files=all"],
        env=env,
        capture_output=True,
        timeout=10,
        check=True,
    )
    if status.stdout:
        raise Hold("planning fixture does not match its committed baseline")
    write(output, "git-status-before.stdout", status.stdout)
    git_version = (
        subprocess.run(
            [git, "--version"], env=env, capture_output=True, timeout=10, check=True
        )
        .stdout.decode()
        .strip()
    )
    before = inventory(project)
    write(output, "planning-before.json", canonical(before) + b"\n")
    commands = [
        ("identity", ["runtime-identity", "--raw"]),
        ("context", ["query", "project-context"]),
        ("inspect", ["query", "planning", "inspect"]),
        ("index", ["query", "phase-plan-index", "1"]),
        ("inspect-repeat", ["query", "planning", "inspect"]),
    ]
    observations = []
    try:
        for name, arguments in commands:
            result = subprocess.run(
                [node, str(package / CLI), *arguments],
                cwd=project,
                env=env,
                capture_output=True,
                timeout=30,
                check=False,
            )
            if len(result.stdout) + len(result.stderr) > 2 * 1024**2:
                raise Hold("GSD query capture bound exceeded")
            write(output, name + ".stdout", result.stdout)
            write(output, name + ".stderr", result.stderr)
            observations.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "exit": result.returncode,
                    "stdout_sha256": digest(result.stdout),
                    "stderr_sha256": digest(result.stderr),
                }
            )
            print(canonical(observations[-1]).decode(), flush=True)
            if result.returncode:
                raise Hold("pinned GSD query failed; inspect retained evidence")
        snapshot = load_json((output / "inspect.stdout").read_bytes())
        if snapshot.get("schema_version") != 1:
            raise Hold("unsupported GSD export schema")
        if (output / "inspect.stdout").read_bytes() != (
            output / "inspect-repeat.stdout"
        ).read_bytes():
            raise Hold("repeated GSD snapshots differ")
    finally:
        after = inventory(project)
        write(output, "planning-after.json", canonical(after) + b"\n")
        write(output, "query-observations.json", canonical(observations) + b"\n")
    status = subprocess.run(
        [git, "-C", str(project), "status", "--porcelain=v1", "--untracked-files=all"],
        env=env,
        capture_output=True,
        timeout=10,
        check=True,
    )
    write(output, "git-status-after.stdout", status.stdout)
    if status.stdout:
        raise Hold("query changed Git working state")
    after = inventory(project)
    write(output, "planning-after.json", canonical(after) + b"\n")
    if source_pins != {path.name: digest(path.read_bytes()) for path in source_paths}:
        raise Hold("query preparation sources changed during execution")
    if after != before or inventory(package / "package") != receipt["files"]:
        raise Hold("read-only query changed planning/Git input or tool package")
    result = {
        "schema_version": 1,
        "classification": "measured pinned GSD schema-1 export; import fidelity not yet qualified",
        "approval": approval,
        "gsd_version": VERSION,
        "gsd_commit": COMMIT,
        "planning_node": version,
        "node_path": node,
        "node_sha256": digest(Path(node).read_bytes()),
        "planning_git": git_version,
        "source_sha256": source_pins,
        "package_receipt_sha256": digest(
            (package / "preparation-receipt.json").read_bytes()
        ),
        "bundle_sha256": manifest_hash,
        "planning_commit": commit,
        "planning_files_unchanged": True,
        "git_metadata_unchanged": True,
        "tool_package_unchanged": True,
        "snapshot_sha256": digest((output / "inspect.stdout").read_bytes()),
        "snapshot_schema": 1,
        "repeat_bytes_equal": True,
        "queries": observations,
    }
    write(output, "result.json", canonical(result) + b"\n")
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=["plan", "prepare", "export"], nargs="?", default="plan"
    )
    parser.add_argument("--approval")
    parser.add_argument(
        "--package", type=Path, default=WORKSPACE / ".local/validation/gsd-package-01"
    )
    parser.add_argument(
        "--bundle", type=Path, default=WORKSPACE / ".local/validation/review-bundle"
    )
    parser.add_argument(
        "--manifest-sha256",
        default="08cbd45c6f48c930300f5132bbc5af24d63cf0f55d3c24210095607ede57a405",
    )
    parser.add_argument(
        "--output", type=Path, default=WORKSPACE / ".local/validation/gsd-export-01"
    )
    args = parser.parse_args()
    if args.mode == "plan":
        result = {
            "mode": "plan-only",
            "gsd_version": VERSION,
            "gsd_commit": COMMIT,
            "source": TARBALL_URL,
            "integrity": INTEGRITY,
            "planning_node": ">=24 (installed workstation Node)",
            "global_install": False,
            "npm_hooks": False,
            "provider_calls": False,
            "input": "synthetic planning files from the original frozen bundle",
        }
    elif args.mode == "prepare":
        result = prepare(args.package, args.approval)
        result = {k: v for k, v in result.items() if k != "files"}
    else:
        result = export(
            args.package, args.bundle, args.manifest_sha256, args.output, args.approval
        )
    print(canonical(result).decode())


if __name__ == "__main__":
    main()
