# Minimal OpenHands runtime preparation

Status: input review, offline dependency export, approved archive retrieval and static metadata audit completed November 21, 2026. The later [offline image build and startup smoke](image-build-plan.md#measured-build-and-startup-result) now provide a retained image archive and measured versions. No executor task has run. This is preparation for M1-12 under the [existing experiment order](../two-task-validation-fixture.md#execution-order-and-prerequisite-gates), not product implementation or architecture adoption.

## Inputs established by source review

Retain OpenHands SDK/Agent Server 1.62.0 at `504a88cab0fb48ee5226238ad7b8f1d865fa84a8`, LiteLLM 1.105.1, executor Node 22.16.0 and Git 2.51.0. Propose CPython 3.13.17 for the container; the guest's Python 3.12.3 remains a separate tool. Python selection is a proposal until the image profile is approved.

The [pinned upstream Dockerfile](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-agent-server/openhands/agent_server/docker/Dockerfile) provides `source-minimal` and `binary-minimal`. Its full `source`/`binary` targets inherit a passwordless sudo grant even if optional capabilities are empty. Use the minimal source layout as the preparation reference, with explicit `INSTALL_ACP_PROVIDERS=""`, `ENABLE_VSCODE=false` and no optional capability stage. The default runtime has Node 24.22.2; it cannot stand in for the fixture Node pin. The builder also uses a floating Python 3.13 request and a sync command without `--no-dev`; it is not an exact minimal dependency build.

The [server metadata](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-agent-server/pyproject.toml) requires both SDK and tools. The [tools package](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-tools/pyproject.toml) requires `browser-use`. Disabling the browser tool does not remove that Python package. Preserve the upstream dependency graph rather than silently deleting required packages. Browser, MCP, ACP and Docker execution remain disabled in the launch policy and must be tested on the deployed server. Python distribution presence and enabled runtime capability are distinct observations.

The root [lockfile](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/uv.lock) is 1,072,916 bytes, SHA-256 `7756b36b335f98d6f58220a6d0c84c4ff94c69c7540fb08a07847e829a2c793c`, Git blob `9f261cf7c9abd3ccb6f999b4371225ff6369ffe4`. The GitHub connector omitted its large content; a direct public raw download matched that Git blob. Source review found 415 package rows, including development and platform variants. The lockfile's `setuptools` row is 80.9.0, while workspace build-system requirements demand >=83.0.0. Runtime locking alone does not freeze build isolation dependencies.

## Measured offline selection

Installed planning-host uv 0.13.9 exported the pinned metadata with `export --frozen --offline --no-dev --package openhands-agent-server --no-emit-workspace --no-header --no-annotate --format requirements.txt`. No interpreter, package or source build was installed or executed. All six metadata files remained byte-identical. The universal requirements output is 256,977 bytes, SHA-256 `e16b99d9ba9ef36ec673dc38a03fee11cfb29d0d3a04669481e6fce21cecf32e`, with 352 pinned requirement rows. uv documents that development dependencies are included by default and `--no-dev` excludes them; `--frozen` prevents automatic relocking. [uv sync documentation](https://docs.astral.sh/uv/concepts/projects/sync/)

An explicit Linux x86-64 CPython 3.13.17 marker environment excludes 166 rows. Selection uses installed pip's vendored packaging 26.2 and conservative wheel tags with a glibc floor no newer than 2.28. It selects 186 third-party artifacts totaling 142,502,826 bytes (about 136 MiB), with no missing artifact. Of these, 185 are compatible-tag wheel candidates and one is the pinned `func-timeout` 4.3.5 sdist. The tags do not prove imports or installed compatibility. Neither pyright nor its Node 24.19.0 wheel is in this selected server set. `browser-use`, `posthog`, the Docker Python client and MCP libraries remain dependencies. Platform selection did not use the Windows host's marker values.

The [reviewed input catalog](runtime-inputs.json) binds every exact URL, filename, byte count and SHA-256. Its digest is `9d564fe32a459224da2b8d9e51c89964e5a7fd80d91c8e564aa0ea1a8f6a9881`. Raw source, universal export, target selection and query receipt stay under ignored `.local/validation/runtime-review-01/`. These are metadata results, not an installed runtime or isolation evidence. See [source evidence](runtime-image-evidence.json).

## Concrete retrieval action

The collector defaults to plan-only and performs no network or filesystem mutation in that mode:

```powershell
python -m research.validation.runtime_artifacts
```

After explicit retrieval approval:

```powershell
python -m research.validation.runtime_artifacts --apply --approval "<approval reference>" --output .local/validation/runtime-artifacts-01
```

This action downloads only the 186 cataloged archives from `files.pythonhosted.org` into a new ignored directory. Four bounded workers check exact byte counts and hashes before retaining each file; HTTPS redirects and ambient proxies are disabled. A failed file produces a retained hold. It never extracts or executes archives, installs packages, invokes a compiler/container daemon, starts a VM, enables networking or calls a model. It refuses an existing destination and paths outside this workspace's `.local/validation/`. Do not interpret retrieval approval as build or experiment approval.

The approved invocation completed with all 186 files, exact catalog byte counts and SHA-256 values, and no retrieval errors. Retained archives occupy 142,502,826 bytes under `.local/validation/runtime-artifacts-01/archives/`. A subsequent static audit rehashed every archive and read only bounded wheel METADATA or the sdist's top-level PKG-INFO. Starting with the three workspace manifests, it traversed all 189 distributions including activated extras under the explicit Linux/Python target. Published version constraints and Requires-Python fields had no detected conflicts or missing dependencies; all 186 selected external distributions were reached. This checks static metadata only: the sdist can generate additional build requirements, and imports, native libraries and server behavior remain untested. No package was extracted or executed.

## Image build still to freeze

Before an install/build action, pin the Linux builder and final base image manifests, build tools and Debian package artifacts. Freeze the build backend dependencies for the three workspace packages and the `func-timeout` sdist separately. Build only in an approved disposable environment without project credentials; a build script is executable code. Preserve raw source from the exact commit and the patch replacing floating Python/dev/default-toolchain behavior. Keep the source, terminal/editor, dummy broker configuration and narrow tool inventory traceable to this pin.

Use the official Node 22.16.0 Linux x64 tarball SHA-256 `f4cb75bb036f0d0eddf6b79d9596df1aaab9ddccd6a20bf489be5abe9467e84e` and Git 2.51.0 source tarball SHA-256 `60a7c2251cc2e588d5cd87bae567260617c6de0c22dca9cdbfc4c7d2b8990b62`. These values came from the [Node checksum list](https://nodejs.org/dist/v22.16.0/SHASUMS256.txt) and [kernel.org Git checksum list](https://www.kernel.org/pub/software/scm/git/sha256sums.asc); signatures have not been verified and neither archive has been downloaded in this stage. Git compilation inputs and resulting binary hash remain open.

Use a non-root UID/GID 10001, immutable runtime files, a read-only root, private bounded writable mounts, no sudo/socket/device inheritance, dropped capabilities, no-new-privileges, seccomp and an enforcing LSM profile. Freeze the effective container runtime version, cgroup controls and storage budgets. Smoke-test imports, effective versions, local server startup, terminal/file-editor schema and disabled features with network disconnected before qualifying a task run. Export the built image/package inventory and SHA-256, then import it offline into the approved guest. A marker filter or successful export cannot substitute for these measurements.

## Network and next check

The executor VM remains disconnected. VirtualBox internal networking excludes host applications, while host-only networking includes the host. Both need a concrete broker/control transport; internal networking alone has no destination filter between participating VMs. [Oracle networking documentation](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/networkingdetails.html)

Prepare a separate decision proposal for external enforcement before attaching any NIC: identify the enforcing host/switch or trusted appliance, literal broker/control flows, anti-spoofing, IPv4/IPv6 drops and counters, independent stop/fence authority, and positive controls for forbidden destinations. Do not substitute guest firewall rules for enforcement outside a potentially compromised guest. Keep the existing host-only adapter, host firewall, other VMs and security settings unchanged until a concrete deployment is approved.

The [subsequent build stage](image-build-plan.md) has now pinned builder/base manifests, build backends, source and recipe, then measured a successful offline build/startup. Its image ID, archive and software inventory are preparation evidence. Next, freeze and qualify the narrow conversation/API policy, external network boundary and guest runtime/hardening profile. Guest readiness, supervisor/observer/extractor qualification and final deployment approval remain prerequisites to M1-12. The [250-file GSD review packet](gsd-freeze-evidence.json) remains unchanged; the final deployment needs a new approved packet.
