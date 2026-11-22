# Executor container-engine input preparation

The [OS-update catalog](os-update-plan.md) explicitly excludes a container engine. The installed executor base has no Docker/containerd/runc. This stage prepares metadata for that missing input while guard creation and the phase-boundary decision remain separately pending. It does not approve installation or task execution.

## Metadata cohort and concrete retrieval

Use the already verified Noble/Updates/Security release cohort from `.local/validation/os-update-resolution-02`, receipt SHA-256 `408bf86c502100b284273aa5ec1c6a43c4c7b8949e414cc2079d329ebfaca3a9`, and OS catalog SHA-256 `4e3d6910cd66b8bcd4f70fc13aba59f98a141fed9e8bc96392bcdeb33634e57a`. The prior native gpgv results verify fingerprint `F6ECB3762474EDA9D21B7022871920D1991BC93C`; the collector rechecks the exact receipt and complete retained inventory. This reuses a recorded signature verification, rather than claiming a new gpgv run.

The signed main indexes contain containerd/runc but no Docker binary package. Retrieve the three missing `universe/binary-amd64/Packages.xz` indexes from the SHA-256 by-hash paths listed in those same signed release payloads. This preserves the OS cohort instead of resolving an engine against newly refreshed unrelated package versions. Proposed compressed retrieval is **17,984,768 bytes**; expanded indexes total **91,793,207 bytes**. No `.deb` archive is downloaded in this stage.

[engine_metadata.py](engine_metadata.py) defaults to a no-network preview. Collection requires an explicit retrieval reference, a new directory beneath workspace `.local/validation`, and no linked output paths. It uses only fixed official HTTPS archive/security origins, refuses redirects, checks both compressed and expanded signed sizes/hashes, bounds XZ memory/output and elapsed work, and preserves failed partial data/receipts without replay. It reads package paragraphs as data and never executes downloaded content, invokes APT, installs tools or changes a VM. The exact collector source is retained with the result.

The corrected decoder supports concatenated XZ streams and valid stream padding while enforcing the signed aggregate expanded size/hash. A separate new attempt may reuse an existing compressed index only after checking its exact signed size/hash, then copies it into the new evidence directory. The first attempt remains held with its source/receipt intact: it rejected a valid empty second stream in Noble's base index. This format behavior is specified in the [XZ format, section 2](https://tukaani.org/xz/xz-file-format.txt).

```powershell
python -B -m research.validation.engine_metadata
```

The mutable releases were published November 21, 2026; the Noble base release dates from April 25, 2024. None has `Valid-Until`. These authenticated indexes are a frozen planning cohort, not a claim of latest package/security status. Refresh/currentness and version/backport review remain required before an installation plan is approved.

## Resolution and security checks still required

Resolve a coherent engine transaction against the **proposed post-update executor inventory of 485 rows**, not WSL's installed state and not the older 480-row guest. A reconstructed status for planning must be labeled hypothetical until actual offline installation succeeds. Pin all additions/upgrades, authenticated archive/control identities, dependency closure and an exact-version replay; reject removals and unintended OS-version changes. Record engine/containerd/runc versions separately from source-package names and verify the final installed binaries later.

Canonical's [container update announcement](https://discourse.ubuntu.com/t/heads-up-upcoming-container-stack-updates/79268) explains source-package names such as docker.io-app/containerd-app/runc-app and the Docker 29 containerd-image-store change. It is context, not a version pin or compatibility measurement. Guest image loading, storage quotas, default AppArmor enforcement, daemon/service/network behavior and protected runtime sockets still need review and final-target tests.

The retained main metadata offers containerd `2.2.1-0ubuntu1~24.04.4` and runc `1.3.4-0ubuntu1~24.04.1` in updates. These are observed repository records, not a selected stack or proof of missing/present distro backports. Upstream's [CVE-2026-119101 advisory](https://github.com/opencontainers/runc/security/advisories/GHSA-g2c3-j8g3-7gpw) scopes its issue to checkpoint **and restore** of untrusted containers. Its [CVE-2026-41579 advisory](https://github.com/opencontainers/runc/security/advisories/GHSA-xjvp-4fhw-gc47) describes a rootfs issue and a Docker-specific mitigating behavior. Do not infer exploitability, patch status, or qualification from the upstream version number. Check the actual Ubuntu source/changelog/backports and enforce the chosen feature restrictions; conversation continuation is not container checkpoint/restore. Fetching Canonical's newer CVE page timed out in this review, so its distro disposition remains unknown.

After metadata retrieval, prepare the exact engine resolution and security/feature review. Package download, offline guest installation, hardening, image loading, deployment approval and M1-12/M1-13/#11 qualification remain later stages. No provider/model or product implementation work is authorized by this metadata collection.

## Measured metadata result

The corrected collection completed with all three compressed and expanded identities matching the frozen signed release entries. Compressed total is 17,984,768 bytes; expanded total is 91,793,207 bytes. The first attempt downloaded Updates and Noble, then held because the decoder rejected Noble's valid empty second stream. Both files' recorded hashes already matched the release. The second attempt reverified and copied those compressed files, retrieved Security and validated all expanded data. Both receipts and exact sources remain retained; the first was not replayed or overwritten.

| Repository record | Version observed | Scope |
| --- | --- | --- |
| Docker in Universe Updates/Security | `29.1.3-0ubuntu3~24.04.2` | Same 35,558,504-byte archive identity in both indexes; archive not retrieved. |
| Docker in Universe base | `24.0.7-0ubuntu4` | Historical base candidate; not selected. |
| containerd in Main Updates | `2.2.1-0ubuntu1~24.04.4` | Retained authenticated Main record; dependencies unresolved for this engine set. |
| runc in Main Updates | `1.3.4-0ubuntu1~24.04.1` | Retained authenticated Main record; backport/feature review open. |

The newer Docker record depends on `libnftables1`, in addition to containerd, iptables and installed system libraries. Resolve the whole closure against the proposed 485-row executor baseline; do not reuse the guard's older four-package addition result as an executor engine transaction. Source package `docker.io-app` produces binary package `docker.io`; these names are not interchangeable installation requests. See [engine metadata evidence](engine-metadata-evidence.json).
