# Maintenance media and APT configuration preview

The [maintenance procedure](maintenance-procedure.md) now has a byte-verified **data ISO** and a native-checked APT configuration preview. This stage creates local artifacts and runs configuration parsers only. It supplies no installer/apply command, target binding, VM creation/boot/attachment authority or runtime qualification.

## Exact artifacts

| Artifact | Measured identity |
| --- | --- |
| `.local/validation/maintenance-media-01/maintenance.iso` | 599,830,528 bytes; SHA-256 `e09f95fb365b3b87be9f6e7b8f7d1529ee596f09c4ea2fee1cf36ea239dd48d4` |
| ISO's `media-manifest.json` | 27,362 bytes; SHA-256 `de9916a00044717b9b5d588cf71bd5d88f565fc675a668a6b9351394dec943b6` |
| Configuration preview `profile.json` | SHA-256 `fef1a95fd7f80e5e4bf89aed1b29135508d7ce0035daa4c5df6a76171efbbf92` |
| Successful native configuration receipt | SHA-256 `728872d44394b6659814b89dd961458b299c80027fcc1892e77cf705975296eb` |
| ISO build/readback receipt | SHA-256 `777739d6acbfac1464a1d0e339f78687c8529ea8998e145747748e19aebbe0ff` |

See [machine-readable evidence](maintenance-media-evidence.json). Neither ISO nor media was mounted on the host or attached to a VM. No tool/dependency installation, provider/model call or repository upload occurred.

## Configuration preparation and native evidence

[maintenance_config.py](maintenance_config.py) pins proposal SHA-256 `42b91618b6f35639aee882e9654a7e8df20ef530b6cc5de23663f2400141d232`. Its default command previews; `--prepare` creates a new workspace artifact. Its only native operations are fixed `/usr/bin/apt-config --version` and `dump` calls as UID 1000. There is no apt-get/apply path.

```powershell
python -B -m research.validation.maintenance_config
```

The candidate keeps `Dir=/`, actual guest `/var/lib/dpkg/status`, actual `/usr/bin/dpkg`, signed file-only sources and an amd64-only architecture list. It makes private binary-cache/log paths explicit, disables persistent binary caches, retains locking and clears command-hook trees. Private main/parts/preferences/sourceparts/trustedparts are required. These are templates for the future guest, not directories created on this workstation. Foreign architectures, hooks, altered roots/status, disabled signatures/locking and token injection are rejected.

Existing WSL APT **2.8.3** parsed the exact guest-path configuration. Its missing `/run/mcli1-maintenance/apt/apt.conf.d` warning is retained and allowed only as that exact expected warning: the checker refuses an already-existing guest-named configuration directory on the tool host. It also parsed an equivalent workspace configuration with real empty private directories, changing only `Dir::Etc`. That staged positive check had no warnings. The real guest directories and final installed APT binary remain unqualified.

Seven native negative cases passed: copied status, alternate root, added command hook, unauthenticated mode, disabled locking, wrong dpkg binary and a hook reintroduced by a parts file loaded after APT_CONFIG. The sentinel command was never executed; apt-config only printed its value. All ten native commands exited zero without timeout; admission rejected the seven unsafe dumps. WSL's actual dpkg-status SHA-256 remained `0eb4221dd0a5e22685398c9efd9e7f0868351ea67279d01dd41f54d4a8f2a12b`.

The checker accounts for APT's observed canonicalization of scalar `Acquire::Languages=none` into an empty parent with a one-element `none` list. It requires exactly that list; extra languages hold. Attempt 01 held on the absent-directory warning; attempt 02 held on scalar-versus-list comparison. Their exact sources/receipts remain separate. The rendered guest configuration/source bytes never changed; the original builder snapshot and corrected checker snapshot are both retained.

## ISO construction and byte verification

The installed `C:\Windows\System32\tar.exe` reports bsdtar/libarchive **3.8.9**, binary SHA-256 `a3ac62fd4cdf619a7c53f71ca3fe5fb42f72020975670ff29afe3603f6416a8e`. Its small format probe preserved long names and deep by-hash paths. A later flag probe rejected unsupported `--mode` before creating media; the corrected probe and final build omit it. All attempts remain local. Upstream documents [ISO output and Rock Ridge options](https://github.com/libarchive/libarchive/wiki/FormatISO9660); that documentation is supporting context, while these native measurements establish installed-tool behavior.

The one-use `.local/validation/maintenance-media-01/run.py` builds ISO9660 level 3 with Rock Ridge, Joliet disabled, volume ID `MCLI1_MAINT_01`, root ownership and no ACL/xattr/fflag import. It rechecks the installed binary hash, frozen mirror/profile and all copied bytes. Working temporary storage stays inside its new artifact directory; a 180-second command deadline and 768 MiB image ceiling hold on failure. The writer's temporary directory was empty after completion. This is one retained image, not a claim that independent rebuilds are byte-identical.

The ISO contains **142 files / 599,085,636 payload bytes**: the original mirror's 135 files unchanged, six declared review additions and the new media index. Review additions are the proposal and its then-current Markdown, APT config/sources, external profile provenance and native-check receipt. The original directory/manifest and included older installation contract stay unchanged. The new media index covers this entire augmented tree; the original strict directory verifier intentionally does not authorize those extra review files.

An installed-libarchive readback converted the ISO into an **unextracted ustar stream**, which Python read incrementally. Every file name, length and SHA-256 matched the complete staged index; directories, root ownership and read/no-write bits were checked. No links or special files appeared. The system area is zero and descriptors are only primary/terminator (`1,255`), with no boot descriptor. All three final native commands exited zero. Writer/readback use the same library implementation; this is byte verification through that reader, not an independent Linux ISO9660 mount test. Mode checks do not create a no-exec mount: a later approved guest mount must use `ro,nosuid,nodev,noexec` and verify the complete tree before package use.

## Remaining before installation

Prepare the bound maintenance runner/host preview and refusal checks: actual-target status/root checks, create-only controls, exclusive ownership, persistent mask/helper-state checks, the proposed 600/210-second lease limits, independent evidence and no repair/replay. The exact ISO identity is now available for a later external approval packet; it has not been substituted into the frozen proposal's null authority fields. Guard creation and the phase-boundary choice remain separate pending decisions.

Then, only under the applicable approvals, verify DVD attachment/mount behavior and every mounted member on the chosen VM, measure free space/readiness, bind actual guard/executor identities and validate the real installed configuration. Package installation, new-kernel boot, mask survival, console behavior through reexec and final isolation/routing/recovery remain unmeasured.
