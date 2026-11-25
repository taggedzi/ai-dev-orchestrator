# Offline OS installation stage

Prepared and executed November 21, 2026 for the existing new VM only, after command approval under [AGENTS.md](../../AGENTS.md). The target is `mcli1-validation-01` (`74129e9c-5a65-44fa-9d35-79d458dc4704`), installation VDI `e832fc9c-23cc-40a8-8e66-fa0c624b8bd9`. No existing development VM or host disk was an installation target.

## Measured result

The approved offline installation completed in 298.515 seconds and powered off. Exactly one matching serial receipt and zero failure markers were recorded. The installed target reports Ubuntu 24.04.5 LTS, amd64, kernel file `vmlinuz-6.8.0-139-generic`, 480 package rows, and `fixture` UID 1000. The target package audit passed. All eight NICs stayed disabled in the installation monitor. The final VDI SHA-256 is `8461a61de7a1c53c125d47397ae3c52fd792a24fad3f7f794dfe29b9ff826feb`.

See [the measured evidence](os-install-evidence.json). Receipt and serial/audit files remain under `.local/validation/os-install-01`. This describes an installed target inspected from the installer, not a successful boot of that target. First boot, running kernel, runtime hardening, control transport and executor behavior remain unqualified. The source changes passed 40 tests with one Windows symlink test skipped; lint and rendered-template checks passed.

## Detection finding

The standalone detect command returned `E_NOTIMPL`, but the installed VirtualBox 7.2.22 unattended-install dry run returned exit 0 and selected `ubuntu_autoinstall_user_data`, detected Ubuntu Server 24.04.5, and supplied the NoCloud boot parameters. A custom offline-template dry run also passed. This qualifies preparation, not installation success.

The [upstream detector source](https://github.com/VirtualBox/virtualbox/blob/main/src/VBox/Main/src-server/UnattendedImpl.cpp) maps an incomplete Linux detection return to `E_NOTIMPL`. Source reviewed November 21: GitHub file blob `3c1262a9119f9ade0da379e3143b8fcc473e1ca7`; this is supporting source evidence, not a verified match to the installed binary's build source. The measured native dry run establishes the usable preparation path on this workstation.

Despite its documented dry-run intent, the first native dry run changed `GUI/FirstRun` to `0` and normalized `localhost-reachable="true"` under the disabled adapter's NAT configuration. No NIC was enabled and no VM was booted. Preserve this observation rather than describing the dry run as byte-for-byte inert.

## Exact installation scope

Use the already checksum-verified Ubuntu Server 24.04.5 ISO and its `ubuntu-server-minimal` source, confirmed by reading `casper/install-sources.yaml` with the installed Windows tar utility. The original image and installation-disk identity are rechecked before boot. Refuse an already allocated/populated installation disk, extra HDDs, shared folders, a running VM, changed resource settings, or any enabled NIC.

The original 32 GiB virtual disk will be partitioned and formatted as the OS installation disk. Use direct storage layout matching `/dev/sda`, no swap, a new disposable `fixture` operator credential, US locale/keyboard, and UTC. All eight NICs remain disabled. Disable installer refresh, third-party driver discovery, SSH server installation, Guest Additions and the test-execution service. Only packages from the local Ubuntu installation image are allowed; there are no model calls, repository uploads or online dependency installs.

The generated password is a new VM-only credential saved under the ignored `.local/validation/os-install-*/operator-password.txt`; it is not a host credential. Native command output is sanitized before retention. Generated auxiliary media can contain its password hash and stay in ignored local preparation storage. Credentials and installer media must be removed or replaced during later image hardening before any untrusted executor runs.

`image_receipt.py` runs in the installer against `/target`. It checks installed OS/architecture, runs the target's package audit, records package-inventory SHA-256 and installed kernel filenames, and confirms the operator UID is nonzero. It writes a token-bound JSON record inside the guest and emits it on a file-backed serial port. Successful installation must both emit exactly one matching receipt and power off. A 20-minute installation deadline is separate from the future ten-minute AI runtime lease. On failure or timeout, request poweroff for this target, retain diagnostics and stop. No automatic restart or reformatting occurs.

This stage does not verify the installed OS's first boot, qualify the security boundary, install OpenHands/GSD/Node/Git, establish runtime storage limits, or authorize an executor experiment. Those later stages need their own measured inputs and scope.

## Reviewable commands

The default command displays the plan and makes no native calls:

```powershell
python -m research.validation.os_install
```

The completed installation command had this form:

```powershell
python -m research.validation.os_install --apply --approval "<approval reference>" --output .local/validation/os-install-01
```

The output directory must be new, and the script now refuses the populated installation disk. Do not rerun it against the installed image. Native dry-run evidence is in `.local/validation/os-install-preflight-02/result.json`; the earlier preflight correctly held before installation when `showmediuminfo` rejected `--machinereadable`. The corrected implementation parses the installed CLI's actual colon-delimited medium output. YAML validation used the already installed PyYAML; the runner itself uses Python's standard library.

Configuration choices follow [Canonical's autoinstall reference](https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html): source selection, offline fallback and poweroff are explicit. Installed-package inventory is hashed in the receipt and stored inside the image. Running-system behavior remains a later measurement.
