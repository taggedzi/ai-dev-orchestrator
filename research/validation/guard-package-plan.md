# Offline guard packet-filter inputs

November 21, 2026: four official Ubuntu archives were downloaded and checked against signed Noble metadata for the developer-selected [guard VM](guard-preparation-plan.md). This is preparation, not installation approval. No package, service, firewall rule or VM setting changed. The stopped target's 480-row package-status file drove resolution; WSL's installed packages did not substitute for it.

## Measured package set

| New package | Exact version | Archive bytes |
| --- | --- | --- |
| libjansson4 | 2.14-2build2 | 32,830 |
| libnftnl11 | 1.2.6-2build1 | 65,986 |
| libnftables1 | 1.0.9-1ubuntu0.1 | 358,574 |
| nftables | 1.0.9-1ubuntu0.1 | 69,842 |

Total: 527,232 bytes. The [catalog](guard-package-inputs.json) retains archive paths, SHA-256 hashes, dependency declarations and already-installed direct dependency versions. It binds source VDI `2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09` and its package-status bytes. This candidate set is not an installed inventory. Re-resolve against the changed status after an OS update.

Existing Ubuntu 24.04 WSL tools ran as UID 1000: APT 2.8.3, gpgv 2.4.4 and the installed dpkg-deb. `APT_CONFIG` selected private state/cache/log/config directories, only Noble/Updates/Security `main`, amd64, no recommends/suggests, and normal signature/date/HTTPS checks. The retained effective configuration has no inherited installation hooks. Metadata refresh succeeded; all three InRelease files also passed independent gpgv verification with the copied installed Ubuntu archive keyring, fingerprint `F6ECB3762474EDA9D21B7022871920D1991BC93C`.

The target simulation selected four additions, zero upgrades/removals. Only `apt-get download` retrieved exact versions. Every archive's size, SHA-256 and control identity match authenticated metadata. No downloaded script or binary ran. WSL's package-status hash was unchanged. See [evidence](guard-package-evidence.json); signed metadata, indexes, command logs and archives remain under `.local/validation/guard-packages-01`.

## Service and patch findings

Reading the signed archive's text confirms an example configuration with empty chains and no drop policy. Its stock service loads that file and flushes the ruleset on stop. Its post-install script can reload the service manager and try restarting an already installed service. These are package-text observations, not guest runtime measurements.

The guard needs a reviewed default-drop configuration and different stop behavior before NIC activation. Use a trusted fence or retain enforcing kernel rules; prevent a permissive gap on stop/reload/failure. Install while disconnected and qualify startup ordering and failure/restart/stop cases independently. Canonical's [nftables documentation](https://documentation.ubuntu.com/security/security-features/network/firewall/nftables/) also identifies the default-disabled service and non-filtering example. Package installation or stock-unit enablement cannot qualify enforcement.

An offline simulation on a separate metadata copy found **97 upgrades and five new kernel packages**, zero removals. It proposes GA kernel `6.8.0-151.151`, compared with installed `6.8.0-139.139`. Those update archives were neither downloaded nor installed. This is an update count, not a vulnerability count or complete security assessment.

[Ubuntu's CVE-2026-99285 record](https://ubuntu.com/security/CVE-2026-99285), published November 10 and updated November 20, names `6.8.0-151.151` as the Noble fix and assigns negligible priority. It describes compatibility between kernel byte-order validation and older nft userspace. Exact kernel/userspace/rules testing therefore matters; no affected planned rule or exploit was observed. The downloaded Noble nftables is still 1.0.9, so a kernel version alone cannot establish compatibility.

Prepare a separately pinned OS-update/hardening plan for both guests before freezing final profiles. Resolve package additions coherently with those updates, review service effects, approve installation, then measure the resulting kernel/inventory. Qualify readiness, filtering, stop/reap and SDK behavior on the final profiles. Earlier boot observations retain their older-image scope.

## Reproduction and limits

[guard_packages.py](guard_packages.py) defaults to a no-action preview:

```powershell
python -B -m research.validation.guard_packages
```

Collection needs existing Linux tools and an explicit retrieval reference. It creates a new directory, checks target-status provenance, retains signed metadata, rejects upgrades/removals or unsupported resolver output for this narrow set, bounds downloads, verifies identities and holds on errors. It has no installation operation. Preserve occupied output directories and original receipts.

The [APT configuration manual](https://manpages.ubuntu.com/manpages/noble/man5/apt.conf.5.html) documents early `APT_CONFIG` loading and directory overrides; the [command manual](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html) documents simulation, explicit versions and downloads. These manuals are provided by APT 2.8.4ubuntu0.1; execution used 2.8.3, with effective settings/results retained separately.

VM creation approval remains pending separately. Installation, hardening, concrete packet rules, deadman/stream fencing, deployment approval and M1-12/M1-13 qualification remain open. No provider/model call, paid experiment, repository upload or product implementation occurred.
