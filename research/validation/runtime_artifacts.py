"""Plan or collect exact public dependency archives; never install or execute them."""

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .bundle import digest, load_json
from .fixture import canonical
from .gsd_export import NoRedirect
from .os_install import WORKSPACE, rooted
from .store import Hold

CATALOG = Path(__file__).with_name("runtime-inputs.json")
CATALOG_SHA256 = "9d564fe32a459224da2b8d9e51c89964e5a7fd80d91c8e564aa0ea1a8f6a9881"
TOTAL_BYTES = 142502826


def catalog():
    raw = CATALOG.read_bytes()
    if digest(raw) != CATALOG_SHA256:
        raise Hold("runtime catalog differs from its reviewed digest")
    value = load_json(raw)
    rows = value["artifacts"]
    if len(rows) != 186 or sum(row["bytes"] for row in rows) != TOTAL_BYTES:
        raise Hold("runtime catalog bounds changed")
    names = set()
    for row in rows:
        name, url = row["filename"], urlsplit(row["url"])
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", name)
            or name.casefold() in names
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            or type(row["bytes"]) is not int
            or not 0 < row["bytes"] <= 64 * 1024**2
            or url.scheme != "https"
            or url.netloc != "files.pythonhosted.org"
            or not url.path.startswith("/packages/")
            or unquote(url.path.rsplit("/", 1)[-1]) != name
            or url.query
            or url.fragment
        ):
            raise Hold("unsafe or unexpected runtime artifact")
        names.add(name.casefold())
    return value


def collect_one(root, row):
    # Disallow redirects and ambient proxies. Send no credentials or project data.
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    with opener.open(row["url"], timeout=30) as response:
        raw = response.read(row["bytes"] + 1)
    if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
        raise Hold("artifact size/hash differs: " + row["filename"])
    target = root / "archives" / row["filename"]
    with target.open("xb") as output:
        output.write(raw)
    if digest(target.read_bytes()) != row["sha256"]:
        raise Hold("retained artifact changed: " + row["filename"])
    return {"filename": row["filename"], "bytes": len(raw), "sha256": digest(raw)}


def collect(output, approval):
    if not approval or not approval.strip():
        raise Hold("explicit artifact retrieval approval required")
    value = catalog()
    root = rooted(output).resolve()
    root.relative_to((WORKSPACE / ".local/validation").resolve())
    root.mkdir(parents=True, exist_ok=False)
    (root / "archives").mkdir()
    (root / "catalog.json").write_bytes(CATALOG.read_bytes())
    receipt = {
        "schema_version": 1,
        "status": "collecting",
        "approval": approval,
        "catalog_sha256": CATALOG_SHA256,
        "source_sha256": digest(Path(__file__).read_bytes()),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "download only; no install, extraction, package execution or VM changes",
        "observations": [],
        "errors": [],
    }

    def save():
        temporary = root / "receipt.next"
        temporary.write_bytes(canonical(receipt) + b"\n")
        temporary.replace(root / "receipt.json")

    save()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(collect_one, root, row): row for row in value["artifacts"]
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                receipt["observations"].append(future.result())
            except (OSError, ValueError) as exc:
                receipt["errors"].append(
                    {"filename": row["filename"], "error": str(exc)}
                )
            save()
    receipt["observations"].sort(key=lambda row: row["filename"])
    receipt["errors"].sort(key=lambda row: row["filename"])
    receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["status"] = "hold" if receipt["errors"] else "collected-not-installed"
    if digest(Path(__file__).read_bytes()) != receipt["source_sha256"]:
        receipt["errors"].append({"error": "collector source changed during retrieval"})
        receipt["status"] = "hold"
    if digest(CATALOG.read_bytes()) != CATALOG_SHA256:
        receipt["errors"].append({"error": "catalog changed during retrieval"})
        receipt["status"] = "hold"
    save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval")
    parser.add_argument(
        "--output", type=Path, default=Path(".local/validation/runtime-artifacts-01")
    )
    args = parser.parse_args()
    value = catalog()
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "plan-only",
                    "catalog_sha256": CATALOG_SHA256,
                    "files": len(value["artifacts"]),
                    "bytes": TOTAL_BYTES,
                    "output": str(args.output),
                    "scope": value["scope"],
                }
            )
        )
        return 0
    receipt = collect(args.output, args.approval)
    print(
        json.dumps({"status": receipt["status"], "files": len(receipt["observations"])})
    )
    return 1 if receipt["errors"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
