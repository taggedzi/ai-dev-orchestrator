"""Exercise provisioning refusal paths without a hypervisor or real VM disks."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PWSH = shutil.which("pwsh")
SOURCE = Path(__file__).resolve().parents[1] / "research" / "validation"


@unittest.skipUnless(PWSH, "PowerShell 7 is unavailable")
class GuardProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "research" / "validation"
        self.folder.mkdir(parents=True)
        self.script = self.folder / "New-GuardVm.ps1"
        shutil.copyfile(SOURCE / self.script.name, self.script)
        self.plan = json.loads((SOURCE / "guard-provisioning-plan.json").read_bytes())
        self.plan_file = self.folder / "guard-provisioning-plan.json"
        self.write_plan()

    def write_plan(self):
        self.plan_file.write_bytes(json.dumps(self.plan).encode())
        self.digest = hashlib.sha256(self.plan_file.read_bytes()).hexdigest()

    def run_script(self, *args):
        return subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-File", str(self.script), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )

    def apply(self, digest=None):
        return self.run_script(
            "-Apply",
            "-ApprovalReference",
            "synthetic refusal check only",
            "-PlanSha256",
            digest or self.digest,
            "-VBoxManage",
            str(self.root / "deliberately-absent-vbox.exe"),
        )

    def test_preview_needs_no_hypervisor_and_creates_no_state(self):
        result = self.run_script("-VBoxManage", "deliberately-absent-vbox.exe")
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview["mode"], "plan-only")
        self.assertEqual(preview["plan_sha256"], self.digest)
        self.assertFalse((self.root / ".local").exists())
        mutations = preview["operations"]
        self.assertEqual(
            [op[0] for op in mutations],
            ["createvm", "modifyvm", "clonemedium", "storagectl", "storageattach"],
        )
        self.assertNotIn("--existing", mutations[2])
        self.assertNotIn("--diffparent", mutations[2])
        self.assertIn("--variant", mutations[2])
        self.assertEqual(mutations[2][-1], "Standard")
        for operation in (mutations[1], mutations[3], mutations[4]):
            self.assertEqual(operation[1], self.plan["vm_uuid"])
            self.assertNotEqual(operation[1], self.plan["source_vm_uuid"])

    def test_apply_requires_separate_approval_and_exact_plan_digest(self):
        missing = self.run_script("-Apply")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("-ApprovalReference is required", missing.stderr)
        changed = self.apply("0" * 64)
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("exact reviewed -PlanSha256", changed.stderr)
        self.assertFalse((self.root / ".local").exists())

    def test_existing_vm_or_intent_prevents_replay_before_native_access(self):
        vm = self.root / self.plan["output_root"] / self.plan["vm_name"]
        vm.mkdir(parents=True)
        marker = vm / "preserve-me"
        marker.write_bytes(b"existing VM data")
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Guard VM directory exists", result.stderr)
        self.assertEqual(marker.read_bytes(), b"existing VM data")
        marker.unlink()
        vm.rmdir()
        receipt = self.root / self.plan["receipt_root"]
        receipt.mkdir(parents=True)
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Provisioning receipt directory exists", result.stderr)

    def test_escaped_path_or_expanded_scope_is_rejected_in_preview(self):
        self.plan["output_root"] = "../outside-workspace"
        self.write_plan()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Path escapes workspace", result.stderr)
        self.plan["output_root"] = ".local/validation/vms"
        for field in (
            "start_vm",
            "install_packages",
            "host_network_changes",
            "modify_source_vm",
        ):
            with self.subTest(field=field):
                self.plan[field] = True
                self.write_plan()
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unexpected guard provisioning scope", result.stderr)
                self.plan[field] = False

    def test_source_and_target_identity_cannot_alias(self):
        self.plan["vm_uuid"] = self.plan["source_vm_uuid"]
        self.write_plan()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected guard provisioning scope", result.stderr)


if __name__ == "__main__":
    unittest.main()
