"""Prepare and inspect M-CLI1 using installed Python, Node and Git only."""

import argparse
import sys
from pathlib import Path

from .bundle import blind_packets, build, digest, load_json, verify
from .checks import grade, scope
from .driver import deployment_template, qualified_profile, report
from .fixture import canonical
from .http_tools import broker, fault_proxy
from .store import Store
from .supervisor import LeaseSupervisor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify", "check", "profile"):
        child = sub.add_parser(name)
        child.add_argument("bundle", type=Path)
        if name == "verify":
            child.add_argument("--manifest-sha256")
        if name == "build":
            child.add_argument("--gsd-export", type=Path)
            child.add_argument("--gsd-snapshot-sha256")
    child = sub.add_parser("blind")
    child.add_argument("bundle", type=Path)
    child.add_argument("destination", type=Path)
    child.add_argument("--seed", type=int, required=True)
    child = sub.add_parser("supervise")
    child.add_argument("bundle", type=Path)
    child.add_argument("profile", type=Path)
    child.add_argument("database", type=Path)
    child = sub.add_parser("report")
    child.add_argument("database", type=Path)
    child = sub.add_parser("reserve")
    child.add_argument("database", type=Path)
    child.add_argument("body", type=Path)
    child.add_argument("--permit", required=True)
    child.add_argument("--task", required=True, choices=("T-01", "T-02"))
    child.add_argument("--attempt", required=True)
    child.add_argument(
        "--role", required=True, choices=("edit", "correction", "finish", "review")
    )
    child.add_argument("--bound", type=int, required=True)
    for name in ("broker", "proxy"):
        child = sub.add_parser(name)
        child.add_argument("database", type=Path)
        child.add_argument("script", type=Path)
        child.add_argument("--port", type=int, default=0)
        if name == "proxy":
            child.add_argument("--upstream", required=True)
    args = parser.parse_args()
    if args.command == "build":
        manifest = build(args.bundle, args.gsd_export, args.gsd_snapshot_sha256)
        output = {
            "bundle": str(args.bundle),
            "files": len(manifest["files"]),
            "manifest_sha256": digest((args.bundle / "manifest.json").read_bytes()),
            "status": manifest["status"],
            "objects": manifest["objects"],
            "open_gates": manifest["open_gates"],
        }
    elif args.command == "verify":
        manifest = verify(args.bundle, expected_digest=args.manifest_sha256)
        output = {
            "verified_files": len(manifest["files"]),
            "manifest_sha256": digest((args.bundle / "manifest.json").read_bytes()),
            "status": manifest["status"],
        }
    elif args.command == "profile":
        manifest = verify(args.bundle)
        output = deployment_template(
            digest((args.bundle / "manifest.json").read_bytes()),
            (manifest.get("planning_export") or {}).get("snapshot_sha256"),
        )
    elif args.command == "blind":
        output = blind_packets(args.bundle, args.destination, args.seed)
    elif args.command == "check":
        verify(args.bundle)
        rows = []
        for task, base, name in (("T-01", "S0", "C1"), ("T-02", "C1", "C2")):
            row = grade(
                args.bundle / "sources" / name, task, integrated=True, review=True
            )
            row["scope_pass"] = scope(
                args.bundle / "sources" / base, args.bundle / "sources" / name, task
            )
            rows.append(row)
        output = {
            "classification": "local gold checks; runtime tool versions are not the deployment pins",
            "results": rows,
            "pass": all(row["pass"] and row["scope_pass"] for row in rows),
        }
        print(canonical(output).decode())
        return 0 if output["pass"] else 1
    else:
        store = Store(args.database)
        try:
            if args.command == "report":
                output = report(store)
            elif args.command == "reserve":
                store.reserve(
                    args.permit,
                    args.task,
                    args.attempt,
                    args.role,
                    digest(args.body.read_bytes()),
                    args.bound,
                )
                output = store.snapshot()
            elif args.command == "supervise":
                profile = qualified_profile(
                    args.bundle, load_json(args.profile.read_bytes())
                )
                LeaseSupervisor(store, profile).watch()
                output = report(store)
            else:
                script = load_json(args.script.read_bytes())
                server = (
                    broker(store, script, ("127.0.0.1", args.port))
                    if args.command == "broker"
                    else fault_proxy(
                        store, args.upstream, script, ("127.0.0.1", args.port)
                    )
                )
                print(
                    canonical(
                        {
                            "listening": f"http://127.0.0.1:{server.server_port}",
                            "classification": "local synthetic service",
                        }
                    ).decode(),
                    flush=True,
                )
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.server_close()
                return 0
        finally:
            store.close()
    print(canonical(output).decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
