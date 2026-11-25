"""Retrieve Universe indexes pinned by the already verified OS snapshot only."""

import argparse
import hashlib
import json
import lzma
import re
import time
import urllib.request
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path

from .guard_packages import WORKSPACE, paragraphs, sha
from .os_update_plan import release_dates, verify_files

RESOLUTION = WORKSPACE / ".local/validation/os-update-resolution-02"
RECEIPT_SHA256 = "408bf86c502100b284273aa5ec1c6a43c4c7b8949e414cc2079d329ebfaca3a9"
CATALOG_SHA256 = "4e3d6910cd66b8bcd4f70fc13aba59f98a141fed9e8bc96392bcdeb33634e57a"
FINGERPRINT = "F6ECB3762474EDA9D21B7022871920D1991BC93C"
SUITES = {"noble", "noble-updates", "noble-security"}


def index_record(release):
    if (
        release.get("Origin") != "Ubuntu"
        or release.get("Codename") != "noble"
        or release.get("Suite") not in SUITES
    ):
        raise ValueError("unexpected Ubuntu release")
    rows = {}
    for line in release["SHA256"].splitlines():
        if not line.strip():
            continue
        digest, size, name = line.split()
        if name in rows or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("invalid or repeated signed index entry")
        rows[name] = {"sha256": digest, "bytes": int(size)}
    prefix = "universe/binary-amd64/Packages"
    compressed, expanded = rows[prefix + ".xz"], rows[prefix]
    if (
        not 0 < compressed["bytes"] <= 64 * 1024**2
        or not 0 < expanded["bytes"] <= 256 * 1024**2
    ):
        raise ValueError("signed metadata exceeds collection bounds")
    suite = release["Suite"]
    host = "security.ubuntu.com" if suite == "noble-security" else "archive.ubuntu.com"
    return {
        "suite": suite,
        "compressed": compressed,
        "expanded": expanded,
        "url": f"https://{host}/ubuntu/dists/{suite}/universe/binary-amd64/by-hash/SHA256/{compressed['sha256']}",
    }


def plan():
    raw = (RESOLUTION / "receipt.json").read_bytes()
    if (
        sha(raw) != RECEIPT_SHA256
        or sha((WORKSPACE / "research/validation/os-update-inputs.json").read_bytes())
        != CATALOG_SHA256
    ):
        raise ValueError("OS snapshot differs from its external pins")
    receipt = json.loads(raw)
    if receipt["status"] != "prepared-not-approved":
        raise ValueError("OS metadata resolution did not complete")
    verify_files(RESOLUTION, receipt["files"])
    result = []
    for number in range(3):
        label = f"signature-{number}"
        if (
            next(c for c in receipt["commands"] if c["label"] == label)["exit"] != 0
            or f"[GNUPG:] VALIDSIG {FINGERPRINT} "
            not in (RESOLUTION / f"commands/{label}.stdout").read_text()
        ):
            raise ValueError("missing prior native signature verification")
        payload = (RESOLUTION / f"releases/{number}.txt").read_text(encoding="utf-8")
        dates = release_dates(payload, datetime.now(timezone.utc))
        row = index_record(paragraphs(payload)[0])
        result.append({**row, "signed_release": dates})
    if {r["suite"] for r in result} != SUITES:
        raise ValueError("incomplete release cohort")
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("metadata redirects are not approved")


def fetch_index(row, root, opener):
    deadline = time.monotonic() + 180
    compressed = root / (row["suite"] + "-Packages.xz")
    partial = compressed.with_suffix(".xz.partial")
    with opener.open(row["url"], timeout=30) as response, partial.open("xb") as output:
        if response.status != 200 or response.geturl() != row["url"]:
            raise ValueError("unexpected metadata response")
        total, digest = 0, hashlib.sha256()
        while data := response.read(
            min(1024**2, row["compressed"]["bytes"] - total + 1)
        ):
            if time.monotonic() > deadline:
                raise TimeoutError("metadata transfer exceeded its wall-time bound")
            total += len(data)
            if total > row["compressed"]["bytes"]:
                raise ValueError("compressed metadata exceeds its signed size")
            output.write(data)
            digest.update(data)
    if (
        total != row["compressed"]["bytes"]
        or digest.hexdigest() != row["compressed"]["sha256"]
    ):
        raise ValueError("compressed metadata differs from signed release")
    partial.rename(compressed)
    return expand_index(row, compressed, root, deadline)


def expand_index(row, compressed, root, deadline):
    expanded = root / (row["suite"] + "-Packages")
    remaining = compressed.read_bytes()
    total, streams, digest = 0, 0, hashlib.sha256()
    with expanded.open("xb") as output:
        while remaining:
            trimmed = remaining.lstrip(b"\0")
            padding = len(remaining) - len(trimmed)
            if padding % 4 or (not streams and padding):
                raise ValueError("invalid XZ stream padding")
            remaining = trimmed
            if not remaining:
                break
            streams += 1
            if streams > 1024:
                raise ValueError("excessive XZ stream count")
            decoder = lzma.LZMADecompressor(memlimit=256 * 1024**2)
            while not decoder.eof:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "metadata expansion exceeded its wall-time bound"
                    )
                data = decoder.decompress(
                    remaining,
                    max_length=min(1024**2, row["expanded"]["bytes"] - total + 1),
                )
                remaining = b""
                total += len(data)
                if total > row["expanded"]["bytes"]:
                    raise ValueError("expanded metadata exceeds its signed size")
                output.write(data)
                digest.update(data)
                if decoder.needs_input and not decoder.eof:
                    raise ValueError("truncated compressed index")
            remaining = decoder.unused_data
    if (
        total != row["expanded"]["bytes"]
        or digest.hexdigest() != row["expanded"]["sha256"]
    ):
        raise ValueError("expanded index differs from signed release")
    return expanded


def engine_rows(path):
    selected, block, block_bytes = [], [], 0
    with path.open(encoding="utf-8") as source:
        for line in chain(source, ["\n"]):
            if line.strip():
                block_bytes += len(line.encode())
                if block_bytes > 1024**2:
                    raise ValueError("oversized package metadata paragraph")
                block.append(line)
                continue
            if block:
                row = paragraphs("".join(block))[0]
                if row.get("Package") in ("docker.io", "containerd", "runc"):
                    selected.append(
                        {
                            k: row.get(k, "")
                            for k in (
                                "Package",
                                "Version",
                                "Source",
                                "Architecture",
                                "Section",
                                "Filename",
                                "Size",
                                "SHA256",
                                "Depends",
                                "Pre-Depends",
                                "Recommends",
                            )
                        }
                    )
                block, block_bytes = [], 0
    return selected


def collect(output, approval, reuse_verified_indexes=None):
    indexes = plan()
    candidate = Path(output).absolute()
    for path in (candidate, *candidate.parents):
        if path.exists() and (
            path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("linked output paths are forbidden")
    root = candidate.resolve()
    root.relative_to((WORKSPACE / ".local/validation").resolve())
    cache = Path(reuse_verified_indexes).resolve() if reuse_verified_indexes else None
    if cache is not None:
        cache.relative_to((WORKSPACE / ".local/validation").resolve())
        if not cache.is_dir():
            raise ValueError("reuse directory is absent")
    root.mkdir(parents=True, exist_ok=False)
    source_bytes = Path(__file__).read_bytes()
    (root / "executed-source.py").write_bytes(source_bytes)
    receipt = {
        "format": "mcli1-engine-metadata-v1",
        "status": "collecting",
        "approval": approval,
        "scope": "Signed-index data retrieval only; no package archives, installed tooling, APT resolution, VM operations or downloaded code execution",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "indexes": indexes,
        "source_sha256": sha(source_bytes),
        "prior_signature_receipt_sha256": RECEIPT_SHA256,
        "os_update_catalog_sha256": CATALOG_SHA256,
        "packages": [],
        "reused_index_files": [],
    }
    target = root / "receipt.json"
    target.write_bytes((json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    try:
        opener = urllib.request.build_opener(NoRedirect())
        for row in indexes:
            cached = cache / (row["suite"] + "-Packages.xz") if cache else None
            if cached is not None and cached.exists():
                if (
                    cached.is_symlink()
                    or getattr(cached.lstat(), "st_file_attributes", 0) & 0x400
                    or cached.stat().st_size != row["compressed"]["bytes"]
                ):
                    raise ValueError("cached index has unexpected type or size")
                data = cached.read_bytes()
                if sha(data) != row["compressed"]["sha256"]:
                    raise ValueError("cached index differs from signed release")
                copy = root / cached.name
                with copy.open("xb") as destination:
                    destination.write(data)
                path = expand_index(row, copy, root, time.monotonic() + 180)
                receipt["reused_index_files"].append(
                    {"path": str(cached), **row["compressed"]}
                )
            else:
                path = fetch_index(row, root, opener)
            receipt["packages"].extend(
                {"suite": row["suite"], **record} for record in engine_rows(path)
            )
        if not any(p["Package"] == "docker.io" for p in receipt["packages"]):
            raise ValueError("no Docker package in the signed Universe indexes")
        if plan() != indexes or Path(__file__).read_bytes() != source_bytes:
            raise ValueError("metadata inputs or collector source changed")
        receipt["status"] = "collected-not-resolved-not-installed"
    except Exception as exc:  # noqa: BLE001 -- preserve a terminal receipt for network/decoder failures
        receipt.update({"status": "hold", "error": f"{type(exc).__name__}: {exc}"})
    receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["files"] = {
        p.name: {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
        for p in sorted(root.iterdir())
        if p.is_file() and p != target
    }
    target.write_bytes((json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", default=str(WORKSPACE / ".local/validation/engine-metadata-01")
    )
    parser.add_argument("--collect-approval")
    parser.add_argument("--reuse-verified-indexes")
    args = parser.parse_args()
    if not args.collect_approval:
        rows = plan()
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "indexes": rows,
                    "download_bytes": sum(r["compressed"]["bytes"] for r in rows),
                    "package_download_or_installation": False,
                },
                indent=2,
            )
        )
        return
    receipt = collect(args.output, args.collect_approval, args.reuse_verified_indexes)
    print(json.dumps({k: receipt[k] for k in ("status", "packages")}, indent=2))
    if receipt["status"] != "collected-not-resolved-not-installed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
