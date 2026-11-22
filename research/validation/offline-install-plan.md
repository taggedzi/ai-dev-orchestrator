# Offline installation input preparation

The developer selected the separate guard VM topology for preparation. Powered-off guard creation, boot/installation and final deployment tests remain separate decisions. This stage builds and checks a public-package mirror, without applying an installation or activating services.

## Prepared input

[offline_repo.py](offline_repo.py) joins the verified [OS](os-update-inputs.json) and [engine](engine-inputs.json) catalogs: **114 unique archives / 370,837,818 bytes**, deduplicating three shared nftables libraries. Archive lookup uses retrieval-receipt SHA-256 and actual cached filenames: APT filenames can encode an epoch even when publisher pool filenames do not. Conflicting identities or publisher paths hold construction.

`.local/validation/offline-repository-01` contains three original Ubuntu InRelease files, six full Main/Universe indexes and their SHA-256 by-hash copies, the Ubuntu keyring, original 480-row status, both frozen catalogs, archives under publisher pool paths and the [proposed installation contract](offline-install-plan.json). It has 134 indexed payload files / 598,872,399 bytes. Its separate 126,956-byte manifest SHA-256 is `007c21f71b69a3741fffe3edbc24b7757d55805755163ffe04a19083d0e52570`. Prior review bundles and input receipts remain unchanged.

Default invocation previews without starting APT. `--build` writes a new direct child of workspace `.local/validation`, refuses existing output and linked paths, compares copied bytes against frozen identities and retains a held manifest on failure. The bundle has no apply script or installation authority. It is a selected archive subset backed by full signed indexes, not a general Ubuntu mirror: other transactions can request absent archives.

```powershell
python -B -m research.validation.offline_repo
```

## Measured offline check

The successful checker is `.local/validation/offline-repository-check-04`, receipt SHA-256 `fe3aa5b2c740c361ea1ce811d2cedc0d0ef91ef208c2de409911260ebf422d84`. It used existing Ubuntu-24.04 WSL tools as UID 1000: APT 2.8.3 and gpgv 2.4.4. Each attempt retains its exact checker/helpers and commands. See [machine-readable evidence](offline-install-evidence.json).

It independently verified all three InRelease signatures against fingerprint `F6ECB3762474EDA9D21B7022871920D1991BC93C`, suite/date fields and six expanded index identities. APT refreshed only private metadata from three constructed **file://** sources with explicit signature/keyring checks. No HTTP source, insecure override or installation was supplied. Every private index matched the signed bytes before exact pinned simulations ran.

| Role, starting at the original 480 installed rows | Upgrades | Additions | Proposed final rows |
| --- | ---: | ---: | ---: |
| Executor: OS plus engine | 97 | 16 | 496 |
| Guard: OS plus nftables | 97 | 9 | 489 |

Both simulations reproduced every old/new version, with zero removals or held-back packages. WSL's actual dpkg-status SHA-256 stayed `0eb4221dd0a5e22685398c9efd9e7f0868351ea67279d01dd41f54d4a8f2a12b`; private target status, mirror payload/manifest and checker sources stayed unchanged. All eight native commands exited zero without timeout. These are dependency-planning results, not installed inventory, completed package scripts, booted kernel or security/runtime qualification.

Three earlier attempts remain separate, without replay or overwrite:

1. Attempt 01 passed signatures but APT selected absent compressed indexes and exited 100. The general uncompressed preference did not achieve the required selection. The checker now sets `Acquire::IndexTargets::deb::Packages::CompressionTypes "uncompressed"`. Ubuntu documents the [general compression preference](https://manpages.ubuntu.com/manpages/noble/man5/apt.conf.5.html); APT's [additional-index documentation](https://github.com/Debian/apt/blob/main/doc/acquire-additional-files.md) describes per-target selection. The latter is archived upstream documentation, not a source pin for installed APT 2.8.3; compatibility is measured here.
2. Attempt 02 completed metadata refresh but rejected generated index symlinks. Its inventory exception also interrupted final receipt saving. The last receipt still says `checking`; successful command captures/source remain, but no sealed final inventory or after-status result exists for that attempt.
3. Attempt 03 allowed only canonical Packages paths and held when APT used by-hash counterparts. Its receipt records the held/unsealed inventory and unchanged host status. Read-only inspection identified all six exact targets. Revision 04 permits only the canonical member or its same signed SHA-256 path, checks both identities, then replaces only that generated private cache link with a verified regular copy. The three private InRelease files were already regular. Frozen bundle link rejection stays unchanged.

Owned commands have a PID/process group and 180-second deadline; timeout kills only that group and holds. Captured output is checked against 8 MiB after collection. This is trusted signed-package preparation, not general containment for untrusted payloads. Full regression: 152 tests, 151 passed and one existing Windows symlink-capability skip; lint/format checks passed.

## Installation and hardening proposal

The [JSON contract](offline-install-plan.json) binds original executor/proposed guard identities, original status, transactions and prerequisites. Actual guard disk identity, installation approval and maintenance authority are null. Preserve the original source for the separately reviewed guard clone before executor updates. Revalidate actual stopped disks/status and independently restorable baseline copies before installation.

Propose a create-only `/usr/sbin/policy-rc.d` returning 101 during maintenance, plus persistent administrator masks for Docker service/socket/containerd on executor and stock nftables on guard. Review existing policy rather than overwriting it. Debian documents [policy denial](https://manpages.debian.org/bookworm/init-system-helpers/invoke-rc.d.8.en.html) and [deb-systemd-invoke's policy consultation](https://manpages.debian.org/bookworm/init-system-helpers/deb-systemd-invoke.1p.en.html). This does not universally block enable/unmask, direct systemctl, package helpers or all OS service restarts. Actual mask survival/helper behavior still need qualification; no blanket suppression result is claimed.

Keep all eight NICs disabled during maintenance, with no experiment tasks. Exact maintenance authority, storage/time bounds, stop and recovery need review; the experiment's ten-minute lease is unchanged. Review remaining OS scripts, needrestart/conffile/debconf behavior, automatic-update units and credential/machine-identity cleanup before an apply procedure. Guard rules must replace the stock permissive example and flush-on-stop lifecycle. Docker socket/group, network/storage/quota/LSM policy, checkpoint/restore exclusion and image import remain open.

The frozen releases have no Valid-Until; signature success does not establish current security status. Freshness and unresolved distro backports remain installation gates. After approved installation, collect actual configure/audit/status/binary and effective unit/socket/mask state, then measure running kernel and repeated readiness. Final isolation, external fencing/stop and routes remain later gates. Pending guard-creation and phase-boundary decisions are unchanged.

Next: inspect remaining OS maintainer scripts and automatic service paths, then prepare a concrete maintenance procedure for review. No guest installation, VM creation/boot/network change, service activation, model/provider call or product implementation ran in this stage.
