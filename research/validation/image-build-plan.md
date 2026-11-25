# Offline Agent Server image build

Status: the explicitly approved offline image build and corrected startup smoke completed November 21, 2026. The image archive is retained locally; Docker Desktop has been stopped again. This is the runtime-input continuation of [the minimal image plan](runtime-image-plan.md), for the existing M1-12 fixture. Product implementation remains gated on the feasibility decision.

## Exact inputs and differences

The [build input manifest](image-build-inputs.json), SHA-256 `11f525e2b09560fc977ad3b45530b014279b31348c18c768c79899eb55319c00`, records Docker Hub's public Linux/amd64 manifest/config/layer digests, observed November 21. Tags are informational; builds bind these manifests:

| Role | Python 3.13.17 image manifest |
| --- | --- |
| Builder, trixie | `sha256:bf756c962c5d29f6fe30dbf70c692b1e978c272619e8f1096e1d697934c662bf` |
| Runtime, slim-trixie | `sha256:d879ed88565a7a3c614b980b369d4a5025a9d057b71f93d09fc6d0b2ca823a18` |

The two images total 456,689,133 compressed layer bytes before sharing/caching. Index bytes, platform manifest and configuration were independently SHA-256 checked; no layer was downloaded during registry metadata review. The later approved pull/build and smoke results are recorded below. Input identity does not establish patch or signature qualification. Docker's [registry authentication documentation](https://docs.docker.com/reference/api/registry/auth/) describes the public pull-token mechanism; no user credential or repository data was supplied to these metadata requests.

OpenHands source archive at commit `504a88cab0fb48ee5226238ad7b8f1d865fa84a8` is 5,730,059 bytes, SHA-256 `1c91cd7f97074706d0bfb2fde0608c104b69de6bdbe58d44f6c7275d0b9ea1d7`. Its lockfile and four reviewed project manifests match their previously recorded Git blob IDs. Source intake selects only the SDK, tools, Agent Server and upstream LICENSE: 553 regular files, 5,530,752 bytes. It rejects selected links, traversal, aliases, duplicates and size overruns. Other project files, native credentials and this project's Git metadata never enter the Docker context.

Four build-only wheels are pinned separately: pip 26.2.2, setuptools 83.0.0, wheel 0.46.3 and packaging 26.2. Each exact public wheel URL, size and hash is in the manifest. Their ordinary Python dependency metadata closes over this set. Optional test/doc extras are excluded. These tools build the three OpenHands packages and `func-timeout` 4.3.5 without build isolation or index access. Runtime installation uses the 185 previously retained wheel candidates plus those four newly built wheels; all are hash-bound before installation, and `pip check` must pass. Build backends and sdist setup code run only inside the separately approved offline builder.

The seven new archives total 42,112,004 bytes: four build wheels, Node 22.16.0, Git 2.51.0 and tini 0.19.0. Node/Git checksums come from the official lists recorded in the earlier plan. The tini checksum comes from the pinned upstream OpenHands Dockerfile. No npm packages or ACP provider are installed. The [pinned TerminalTool definition](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-tools/openhands/tools/terminal/definition.py#L287-L310) supports an explicit `terminal_type="subprocess"`; this candidate records that choice rather than relying on tmux autodetection. It is a deployment-profile input that needs tool/start/stop measurement, not proof of equivalent recovery behavior.

The [recipe](MinimalAgentServer.Dockerfile) uses the existing minimal source layout with a separate final image. It does not run the upstream full-image sudo/capability stages. Git is built for local fixture operations, omitting curl/SSL/expat/Perl/Tcl/Python integrations; this variant and effective binary hashes must remain in the cohort identity. Required browser-use, MCP and Docker Python packages remain installed while their callable features remain disabled in the launch policy. The final image is non-root UID/GID 10001, has an explicit tiny init process, records copied C++ libraries separately from its base dpkg inventory, and contains no build environment or source archive. Image configuration alone does not prove isolation or disable dynamic API requests.

## Preparation action

`python -m research.validation.image_context` prints a plan with no native/network calls. The following separately approved action downloads exactly the seven archives, verifies the retained runtime archives and source, and writes a new context; it does not install or execute packages or start Docker:

```powershell
python -m research.validation.image_context --apply --approval "<approval reference>" --output .local/validation/image-context-01
```

Retain the printed context manifest digest outside that directory. Verify its complete file inventory and digest before passing it to Docker. Incomplete or existing contexts are held; never overwrite or retry them silently. The context is synthetic preparation material and public upstream source only.

## Separately approved build action

Read-only inventory found Docker client 29.9.3 and a `desktop-linux` context, with no reachable Desktop engine. A sandbox-denied status query and its terminal outcome were retained separately from the approved read-only query, which also reported Desktop unavailable. Do not infer a running daemon from CLI presence. Starting installed Docker Desktop requires the following explicit preparation approval; do not change its settings, global context, other WSL distributions, host firewall or the validation VM.

The proposed action starts installed Docker Desktop, records the actual Linux engine/build versions and available resources, and pulls only the two digest-pinned base images. Use an isolated Docker configuration and the literal Desktop Linux named-pipe endpoint so ambient account credentials, registry config and context selection do not enter the operation. Build only this frozen context under a new tag `mcli1-agent-server:prep-504a88c-01`, refusing an existing tag. Every Dockerfile RUN has `--network=none`; no host paths, sockets, SSH forwards or secrets are mounted. The built-in Dockerfile frontend is used, without a floating external syntax image. Build logs, inspection, image ID, image archive and hashes remain local.

After build, run only an offline preparation smoke check with no published ports, network `none`, read-only root, UID/GID 10001, dropped capabilities, no-new-privileges, bounded tmpfs, 1 CPU, 2 GiB memory/no extra swap and 128 PIDs. Check imports and exact tool versions, then server startup under a dummy-only configuration. Record stop/removal and retain uncertain results as holds. This is a preparation check on Docker Desktop, not the final VirtualBox target or an M1-12 isolation result. Dependency installation, build and smoke execution must be explicitly authorized together before starting them.

Restore Desktop to its observed stopped state after this preparation when no unrelated containers need it; preserve image artifacts. Before using an image in the validation VM, complete that VM's readiness/hardening, freeze its runtime package/LSM/cgroup/storage profile and external network boundary, qualify observer/supervisor/extractor controls, and obtain final deployment/run approval. No executor task or provider call is part of this build action.

## Measured build and startup result

The seven archives were retrieved and verified. The first 751-file context was retained without execution; source review corrected an unrecognized telemetry consent value to `denied`/`override` and `DO_NOT_TRACK=1`. The executed context is `.local/validation/image-context-02`, manifest SHA-256 `90eecd3d458076e9ad95becba7f14e07a2355f459992ba59c0694f3979346375`. Its exact amendment and original digest are retained. All source/context bytes remained unchanged by Docker.

The approved action started Docker Desktop 4.99.0 with Linux Engine 29.9.3, containerd 2.4.2, runc 1.5.2 and WSL kernel `6.18.58.1-microsoft-standard-WSL2`. Inventory reported 20 CPUs and 16,693,161,984 memory bytes; no Docker settings were changed. No unrelated running containers were listed. An isolated Docker client configuration contained no account credentials, and the literal Linux engine endpoint was used without switching the global context.

The network-disabled build passed installation integrity, `pip check`, required SDK/terminal/editor imports and version checks. It produced image ID `sha256:f242d7a2b69742fde04385231647c54c57396b251ddfd7a5f34095073970e868`, under the new tag. The 999,058,944-byte Docker archive is `.local/validation/image-build-01/agent-server-image.tar`, SHA-256 `4859acc886856d990bef0215be182999bf6a7021db54ba06db30888ca01caf66`. Its saved configuration hashes to that exact image ID. Four built wheel hashes and copied binary/library hashes are retained separately. The exact toolchain inventory digest is `89da4f442adfd5cc89517c05efdf946cd8c637f77dc4cb7abe4e02a3a71366dc`.

The first smoke probe was invalid because of a host-side newline-escaping error, before it tested readiness. Its container configuration and stopped/removed outcome remain recorded. Startup logs also exposed LiteLLM's default remote cost-map fetch; `network=none` prevented DNS/connect and the library used its backup. The second check first syntax-validated the corrected probe and explicitly set `LITELLM_LOCAL_MODEL_COST_MAP=True`, which the pinned wheel implements. This environment setting is now a mandatory launch-profile input; it is not baked into this image. The second log contained no remote cost-map fetch attempt. This is not a general syscall/network trace.

The corrected non-root/read-only check observed Python 3.13.17, Node 22.16.0, Git 2.51.0, the three OpenHands distributions at 1.62.0 and LiteLLM 1.105.1. All 186 external installed versions match the input catalog; total runtime distributions are 189, with 87 base dpkg rows. `/alive`, `/health`, `/ready` and `/server_info` returned HTTP 200 under the dummy session key, with readiness reporting `ready`. Kernel status reported empty effective capabilities and no-new-privileges; writing image root returned EROFS. Independent Docker inspection matched network none, no ports/binds, a read-only root, UID/GID 10001, 1 CPU, 2 GiB/no extra swap and 128 PIDs. This is a preparation observation on Desktop, not the final target's denial qualification.

The server advertised 17 usable tools including delegation/workflow tools. A fixed conversation definition and external control-route allowlist still need to prove that only terminal and file editor are granted. No conversation or task was created. `workspace_version` is `unknown` because the separate Docker workspace distribution is absent from this local-runtime image. The Desktop AppArmor label was empty, and the base inventory includes apt 3.0.3; final-target LSM and patch/security qualification remain open. Do not promote this preparation result to an isolation Go.

Both smoke containers were observed stopped (exit 143 after SIGTERM) and removed; no other running containers were listed. Docker Desktop stop returned zero, and a subsequent literal named-pipe API query confirmed the engine unavailable. The image and source evidence were retained. No VirtualBox VM, host firewall or security setting was changed. See [image-build-evidence.json](image-build-evidence.json) for artifact hashes, execution sources, raw operation receipts and the precise limits of the result.
