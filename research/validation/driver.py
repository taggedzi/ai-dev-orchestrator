"""Prepared executor client. No VM startup or automatic mutation recovery."""

import hashlib
import subprocess
import time
from pathlib import Path
from uuid import UUID

from .bundle import digest, load_json, verify
from .fixture import canonical
from .http_tools import request
from .store import Hold


def deployment_template(bundle_hash, gsd_export_hash=None):
    return {
        "schema_version": 1,
        "status": "not-approved",
        "bundle_sha256": bundle_hash,
        "approval": None,
        "target_vm_uuid": None,
        "image_sha256": None,
        "toolchain_sha256": None,
        "network_policy_sha256": None,
        "tool_schema_sha256": None,
        "gsd_export_sha256": gsd_export_hash,
        "chat_transcript_sha256": None,
        "gate_evidence": {
            "isolation": None,
            "stop_reap": None,
            "route_and_metering": None,
        },
        "runtime_url": "http://127.0.0.1:8000",
        "proxy_url": "http://127.0.0.1:8001",
        "lease_expires_utc_ns": None,
        "vboxmanage": None,
    }


def qualified_profile(bundle_root, profile):
    verify(bundle_root, expected_digest=profile.get("bundle_sha256"))
    raw = Path(bundle_root, "manifest.json").read_bytes()
    if (
        profile.get("schema_version") != 1
        or profile.get("status") != "approved"
        or not profile.get("approval")
    ):
        raise Hold("no frozen deployment/run approval")
    if profile.get("bundle_sha256") != digest(raw):
        raise Hold("profile bound to a different bundle")
    for name in (
        "image_sha256",
        "toolchain_sha256",
        "network_policy_sha256",
        "tool_schema_sha256",
        "gsd_export_sha256",
        "chat_transcript_sha256",
    ):
        value = profile.get(name)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise Hold(f"unfrozen deployment field: {name}")
    if set(profile.get("gate_evidence", {})) != {
        "isolation",
        "stop_reap",
        "route_and_metering",
    } or not all(profile["gate_evidence"].values()):
        raise Hold("missing target qualification evidence")
    UUID(profile["target_vm_uuid"])
    if (
        type(profile.get("lease_expires_utc_ns")) is not int
        or time.time_ns() >= profile["lease_expires_utc_ns"]
    ):
        raise Hold("missing or expired runtime lease")
    return profile


class Driver:
    def __init__(self, store, proxy_url):
        self.store = store
        self.proxy_url = proxy_url

    def mutation(self, operation, path, payload):
        raw = canonical(payload)
        binding = hashlib.sha256(canonical(["POST", path, digest(raw)])).hexdigest()
        self.store.begin(operation, binding)
        # A disconnect leaves possible-send durable. No exception handler retries it.
        status, response, _ = request(
            self.proxy_url,
            "POST",
            path,
            raw,
            {"Content-Type": "application/json", "X-Fixture-Operation": operation},
        )
        self.store.receipt(operation, status, response)
        return status, load_json(response)

    def lookup(self, conversation):
        conversation = str(UUID(str(conversation)))
        return request(self.proxy_url, "GET", f"/api/conversations/{conversation}")

    def history(self, conversation):
        """Keep raw pages. Unknown native page shapes hold rather than guess."""
        conversation = str(UUID(str(conversation)))
        pages, seen = [], set()
        page_id = None
        for _ in range(128):
            from urllib.parse import urlencode

            path = f"/api/conversations/{conversation}/events/search"
            if page_id is not None:
                path += "?" + urlencode({"page_id": page_id})
            status, raw, _ = request(self.proxy_url, "GET", path)
            if status != 200:
                raise Hold("history lookup failed")
            page = load_json(raw)
            if not isinstance(page, dict) or "next_page_id" not in page:
                raise Hold("unqualified native history schema")
            pages.append(page)
            page_id = page["next_page_id"]
            if page_id is None:
                return pages
            if not isinstance(page_id, str) or page_id in seen:
                raise Hold("history cursor repeated or invalid")
            seen.add(page_id)
        raise Hold("history page limit")


def stop_vm(store, profile):
    """Prepared emergency stop for one explicitly named VirtualBox target."""
    identity = str(UUID(profile["target_vm_uuid"]))
    executable = Path(profile["vboxmanage"])
    if (
        executable.name.lower() not in ("vboxmanage.exe", "vboxmanage")
        or not executable.is_absolute()
    ):
        raise Hold("explicit VBoxManage executable required")
    store.fence("VM stop requested")
    started = time.monotonic_ns()
    # Only this target; no shell interpolation, enumeration or VM creation.
    result = subprocess.run(
        [str(executable), "controlvm", identity, "poweroff"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
        shell=False,
        check=False,
    )
    store.event(
        "supervisor-stop-command",
        {
            "target": identity,
            "exit": result.returncode,
            "elapsed_ns": time.monotonic_ns() - started,
            "stdout_sha256": digest(result.stdout),
            "stderr_sha256": digest(result.stderr),
            "classification": "command receipt; independent stop/reap confirmation still required",
        },
    )
    if result.returncode:
        raise Hold("VM poweroff command failed; runtime stop unproven")


def report(store):
    snapshot = store.snapshot()
    audit = store.audit()
    return {
        "schema_version": 1,
        "classification": "local harness evidence; simulated billing",
        "executor_cases": "Inconclusive until approved target experiments are measured",
        "accepted_tasks": None,
        "accepted_tasks_reason": "harness does not infer acceptance from native status",
        "snapshot": snapshot,
        "audit_records": len(audit),
        "audit_head": audit[-1]["digest"] if audit else None,
        "cost_per_accepted_task": None,
        "cost_reason": "no verified task acceptance count",
    }
