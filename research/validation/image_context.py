"""Prepare a frozen offline image context without installing or executing inputs."""

import argparse
import re
import shutil
import sys
import tarfile
import unicodedata
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .bundle import digest, load_json, safe_path
from .fixture import canonical
from .os_install import WORKSPACE, rooted
from .runtime_artifacts import catalog as runtime_catalog
from .store import Hold

INPUTS = Path(__file__).with_name("image-build-inputs.json")
INPUTS_SHA256 = "11f525e2b09560fc977ad3b45530b014279b31348c18c768c79899eb55319c00"
PREFIX = "software-agent-sdk-504a88cab0fb48ee5226238ad7b8f1d865fa84a8"


def inputs():
    raw = INPUTS.read_bytes()
    if digest(raw) != INPUTS_SHA256:
        raise Hold("image inputs differ from the reviewed digest")
    return load_json(raw)


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if (
            url.scheme != "https"
            or url.netloc != "release-assets.githubusercontent.com"
            or urlsplit(req.full_url).netloc != "github.com"
        ):
            raise Hold("unapproved build artifact redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_asset(row):
    url = urlsplit(row["url"])
    if url.scheme != "https" or url.netloc not in {
        "nodejs.org",
        "www.kernel.org",
        "github.com",
        "files.pythonhosted.org",
    }:
        raise Hold("unexpected image asset source")
    opener = urllib.request.build_opener(
        ArtifactRedirect, urllib.request.ProxyHandler({})
    )
    with opener.open(row["url"], timeout=30) as response:
        raw = response.read(row["bytes"] + 1)
    if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
        raise Hold("image asset bytes changed: " + row["filename"])
    return raw


def source_files(archive_path):
    result, aliases = {}, set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            name = member.name
            safe_path(name)
            if name == PREFIX and member.isdir():
                continue
            if not name.startswith(PREFIX + "/"):
                raise Hold("unexpected upstream archive root")
            name = name.removeprefix(PREFIX + "/")
            selected = name == "LICENSE" or name.split("/")[0] in {
                "openhands-sdk",
                "openhands-tools",
                "openhands-agent-server",
            }
            if not selected or member.isdir():
                continue
            key = unicodedata.normalize("NFC", name).casefold()
            if key in aliases or not member.isfile() or member.size > 1024**2:
                raise Hold("unsafe, duplicate or oversized source member")
            if any(
                part.endswith((".", " ")) or ":" in part
                for part in safe_path(name).parts
            ):
                raise Hold("source path alias")
            aliases.add(key)
            result[name] = archive.extractfile(member).read(member.size + 1)
            if len(result) > 1000 or sum(map(len, result.values())) > 16 * 1024**2:
                raise Hold("source package bounds exceeded")
    if "LICENSE" not in result:
        raise Hold("upstream license missing")
    return result


def prepare(destination, approval):
    if not approval or not approval.strip():
        raise Hold("explicit image-input preparation approval required")
    value, runtime = inputs(), runtime_catalog()
    root = rooted(destination).resolve()
    root.relative_to((WORKSPACE / ".local/validation").resolve())
    archive = (
        WORKSPACE / ".local/validation/image-input-review-02/openhands-504a88c.tar.gz"
    )
    if digest(archive.read_bytes()) != value["source_archive"]["sha256"]:
        raise Hold("upstream source archive changed")
    source = source_files(archive)
    runtime_root = WORKSPACE / ".local/validation/runtime-artifacts-01/archives"
    for row in runtime["artifacts"]:
        if digest((runtime_root / row["filename"]).read_bytes()) != row["sha256"]:
            raise Hold("runtime archive changed: " + row["filename"])
    root.mkdir(parents=True, exist_ok=False)
    (root / "assets").mkdir()
    (root / "archives").mkdir()
    # On a failure preserve the incomplete exclusive context; never silently retry.
    for row in value["assets"]:
        filename = row["filename"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", filename):
            raise Hold("unsafe asset filename")
        (root / "assets" / filename).write_bytes(fetch_asset(row))
    for name, raw in source.items():
        target = root / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for row in runtime["artifacts"]:
        shutil.copyfile(
            runtime_root / row["filename"], root / "archives" / row["filename"]
        )
    for source_name, name in [
        ("MinimalAgentServer.Dockerfile", "Dockerfile"),
        ("image_build_inside.py", "build_inside.py"),
    ]:
        shutil.copyfile(INPUTS.with_name(source_name), root / name)
    build_requirements = "".join(
        "/inputs/assets/" + row["filename"] + " --hash=sha256:" + row["sha256"] + "\n"
        for row in value["assets"]
        if row["filename"].endswith(".whl")
    )
    (root / "build-requirements.txt").write_text(
        build_requirements, encoding="utf-8", newline="\n"
    )
    runtime_requirements = "".join(
        "/inputs/archives/" + row["filename"] + " --hash=sha256:" + row["sha256"] + "\n"
        for row in runtime["artifacts"]
        if row["kind"] == "wheel"
    )
    (root / "runtime-requirements.txt").write_text(
        runtime_requirements, encoding="utf-8", newline="\n"
    )
    (root / ".dockerignore").write_bytes(b"context-receipt.json\n")
    manifest = {
        "schema_version": 1,
        "status": "prepared-not-built",
        "approval": approval,
        "image_inputs_sha256": INPUTS_SHA256,
        "runtime_catalog_sha256": value["runtime_catalog_sha256"],
        "preparer_sha256": digest(Path(__file__).read_bytes()),
        "files": {
            p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted(root.rglob("*"))
            if p.is_file()
        },
    }
    raw = canonical(manifest) + b"\n"
    (root / "context-manifest.json").write_bytes(raw)
    return {
        "context": str(root),
        "files": len(manifest["files"]),
        "manifest_sha256": digest(raw),
        "status": manifest["status"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval")
    parser.add_argument(
        "--output", type=Path, default=Path(".local/validation/image-context-01")
    )
    args = parser.parse_args()
    value = inputs()
    result = (
        prepare(args.output, args.approval)
        if args.apply
        else {
            "mode": "plan-only",
            "asset_files": len(value["assets"]),
            "asset_bytes": sum(r["bytes"] for r in value["assets"]),
            "base_images": [
                {"role": image["role"], "manifest_sha256": image["manifest_sha256"]}
                for image in value["base_images"]
            ],
            "scope": "Collect archives and prepare context only; no package execution, Docker start or image build",
        }
    )
    print(canonical(result).decode())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
