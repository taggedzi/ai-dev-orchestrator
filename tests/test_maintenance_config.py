import copy
import unittest

from research.validation.maintenance_config import (
    PROPOSAL,
    proposal,
    render,
    settings,
    sources,
    validate_dump,
)


class MaintenanceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.proposal = proposal(PROPOSAL.read_bytes())
        self.settings = settings(self.proposal)
        self.dump = (
            "\n".join(
                f'{k} "{v}";'
                for k, v in self.settings.items()
                if k != "Acquire::Languages"
            )
            + '\nAcquire::Languages "";\nAcquire::Languages:: "none";\nAPT::Architectures:: "amd64";'
        )

    def test_copied_root_status_or_missing_signatures_cannot_render(self):
        for key, value in {
            "Dir": "/planning",
            "Dir::State::status": "/tmp/copied-status",
            "Dir::Bin::dpkg": "/usr/bin/true",
            "Acquire::Check-Date": "false",
            "APT::Get::AllowUnauthenticated": "true",
        }.items():
            changed = copy.deepcopy(self.proposal)
            changed["apt_configuration_proposal"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                render(changed)

    def test_changed_external_proposal_bytes_and_config_injection_hold(self):
        with self.assertRaises(ValueError):
            proposal(PROPOSAL.read_bytes() + b" ")
        changed = copy.deepcopy(self.proposal)
        changed["apt_configuration_proposal"]["Dir::Etc::main"] = '"; malicious "'
        with self.assertRaises(ValueError):
            render(changed)

    def test_post_parse_hooks_root_overrides_and_foreign_architecture_hold(self):
        validate_dump(self.dump, self.settings)
        for addition in [
            'DPkg::Post-Invoke:: "/usr/bin/false";',
            'Dir::State::status "/tmp/copied-status";',
            'DPkg::Options:: "--root=/tmp/elsewhere";',
            'APT::Architectures:: "i386";',
            'Debug::NoLocking "true";',
            'Acquire::Languages:: "en";',
        ]:
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                validate_dump(self.dump + "\n" + addition, self.settings)

    def test_sources_and_config_keep_guest_paths_and_no_installation_command(self):
        configuration = render(self.proposal)
        self.assertIn('Dir::State::status "/var/lib/dpkg/status";', configuration)
        self.assertNotIn("target-status", configuration)
        self.assertIn("#clear DPkg::Post-Invoke;", configuration)
        self.assertEqual(len(sources().splitlines()), 3)
        self.assertNotIn("https:", sources())
        self.assertNotIn("trusted=yes", sources())
        self.assertNotIn("apt-get", configuration)
