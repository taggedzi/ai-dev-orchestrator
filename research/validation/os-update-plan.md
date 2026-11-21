# Proposed offline guest OS updates

Status: resolved against retained signed Ubuntu metadata; **installation is not approved**. This prepares the next hardening inputs while the separate [disconnected guard creation decision](guard-preparation-plan.md) remains pending. Neither VM was booted, modified or updated.

## Exact transactions

Both roles start from the inspected 480-package base, source VDI SHA-256 `2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`. The [frozen input catalog](os-update-inputs.json) records every proposed version, authenticated archive hash and role membership.

| Role | Upgrades | Additions | Removals / held back | Expected installed rows |
| --- | --- | --- | --- | --- |
| Executor OS | 97 | 5 kernel packages | 0 / 0 | 485 |
| Guard OS plus nftables | 97 | 9, including the kernel and four packet-filter packages | 0 / 0 | 489 |

The unique archive union is **106 files, 297,065,488 bytes** (about 283 MiB). Four archives, 527,232 bytes, were already verified in the [packet-filter stage](guard-package-plan.md); 296,538,256 additional bytes are needed at resolution time. The catalog's installation approval is null. Container-engine installation is outside this OS-update set and remains a separate missing executor input.

The proposed GA kernel is `6.8.0-151.151`, replacing the default boot candidate `6.8.0-139.139` after a successful update and boot. Old kernel packages remain installed: no removal or automatic cleanup is proposed. A package transaction alone does not prove which kernel booted. Previous readiness observations retain their exact older-image scope.

## Measured resolver checks

[os_update_plan.py](os_update_plan.py) uses the already retained Noble/Updates/Security `main` indexes and installed Ubuntu 24.04 WSL tools. It verifies the original collection's external receipt digest and full file inventory, then copies indexes and keyring into new private APT state. No metadata refresh, archive download or installation occurs during resolution.

It independently verifies all three archive signatures and dates. The retained mutable indexes were published November 21, 2026. None of these Ubuntu release files contains `Valid-Until`; signature validity therefore does not establish that this is still the latest snapshot. Refresh/currentness review is required before installation approval. The receipt preserves exact publication dates and raw index bytes.

The resolver explicitly includes phased updates so WSL's machine ID does not affect selection. This is a proposed deterministic update policy, subject to installation review. [APT's preference manual](https://manpages.ubuntu.com/manpages/noble/man5/apt_preferences.5.html) documents the machine-ID dependency and the include-phased option.

Both native simulations completed with zero removals and no held-back packages. All 97 old-to-new version comparisons passed installed `dpkg --compare-versions`. Metadata for all **489 final package versions**, including unchanged packages, is available in the authenticated snapshot. Replaying each role with explicit `name=version` arguments produced the same package-effect set. WSL's package-status bytes and the original collection stayed unchanged. These are resolver measurements, not a successful installation, security audit or boot qualification.

The first attempt stopped because `--no-download` required cached archives even with simulation enabled. Its failed receipt and exact executed sources are preserved under `.local/validation/os-update-resolution-01*`. Revision 02 uses APT's documented `--simulate` operation and rejects real install/download commands at its command boundary. It does not use missing-archive recovery to omit planned changes. See [resolution evidence](os-update-evidence.json).

## Archive retrieval review

[fetch_os_updates.py](fetch_os_updates.py) has a separate download-only entry point. It requires an explicit retrieval reference and the catalog SHA-256, creates a new private output directory, reuses only hash-matching cached archives, and requests exact versions from the three fixed official Ubuntu sources. It verifies every archive's size, SHA-256 and control identity using installed tools; it never executes downloaded scripts/binaries. Its APT command boundary permits only `apt-get download` with exact versions. On timeout it terminates its own download process group, preserves partial data and holds. No automatic replay occurs.

The default commands preview scope without invoking APT or changing state:

```powershell
python -B -m research.validation.os_update_plan
python -B -m research.validation.fetch_os_updates
```

Actual retrieval uses the installed WSL tools and the externally reviewed catalog digest; it is not package installation approval. The [APT command manual](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html) distinguishes simulation, version selection and archive download.

## Installation and qualification prerequisites

Before a guest update, approve a concrete offline bootstrap/installation plan bound to that guest's actual disk UUID/hash, package status, payload/media and shutdown authority. Guard creation approval does not authorize attaching media, booting, installing or connecting a NIC. Keep both guests disconnected during updates and review maintainer scripts, service restarts, kernel/initramfs/bootloader changes, conffile handling and background package-management services.

Then rotate inherited credentials/identity, remove installation artifacts, address the offline network wait, install the reviewed guard services and replace the stock nftables policy/flush-on-stop behavior. Record the installed inventory and running kernel before freezing final readiness policies. Qualify the final guard/executor profiles, independent stop supervisor, filtering/stream fencing, observers and disposable extractor before M1-12/M1-13 or executor task dispatch. The architecture feasibility decision and product implementation remain open.
