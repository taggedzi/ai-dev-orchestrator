# Guard VM preparation and first provisioning review

The developer selected the [guard topology](../../docs/decisions/0001-validation-network-boundary.md) for preparation on November 21, 2026. The first native action proposed here creates a new **powered-off, disconnected VM** from a full disk clone. It does not boot either VM, install packages, create a network or run an executor. Those later stages remain separate reviews under [AGENTS.md](../../AGENTS.md).

## Concrete first-stage inputs

[guard-provisioning-plan.json](guard-provisioning-plan.json) fixes `mcli1-guard-01`, UUID `0eceb37e-f216-45ed-817c-7cf2fca3a32a`, one CPU, 1024 MiB, EFI, ordinary APIC on and x2APIC off. All eight NICs, UARTs, clipboard, drag-and-drop, USB, audio and remote display stay disabled. A new SATA disk is a full independent dynamic VDI, with 32 GiB logical capacity. No installer, source NVRAM, source VM configuration or source disk is attached to the new VM. This capacity is guard preparation storage, not the executor's later writable-space limit.

The source is the already installed executor preparation disk, UUID `e832fc9c-23cc-40a8-8e66-fa0c624b8bd9`, SHA-256 `2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`. It must remain stopped, disconnected and unchanged across cloning. `clonemedium` gets a new target path with no `--existing` or differencing option. A new VM is created rather than cloning its device/settings profile. The new disk UUID and hash are measurements to retain after provisioning, not invented approval inputs. [Oracle's 7.2 CLI reference](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html) documents the clone and VM commands; the installed version is `7.2.22r175245`.

The guard inherits the OS's package state, bootstrap account, machine identity and installation artifacts. It is an **unhardened offline preparation copy**. Rotate the disposable bootstrap credential, replace machine identity, remove installer state and disable inappropriate network/automatic services before any network connection. Guard readiness on one CPU must be measured separately; the executor's one promising two-CPU boot does not qualify it. The guard's fresh EFI NVRAM and boot discovery also need measurement. Do not replay the formatting installer against either disk.

## Measured read-only preflight

Native inventory confirmed the selected source VM powered off with eight NICs disabled and no running VMs. It is still a normal base VDI, 32768 MiB, with no parent. A new sparse partition copy was exported with source SHA-256 checked before and after. The copy is an unreplayed filesystem view; it was never mounted. Existing WSL `debugfs` read its package metadata only, executing no guest binary. See [guard-preparation-evidence.json](guard-preparation-evidence.json) and retained receipts under `.local/validation/guard-preparation-02`.

There are 480 installed package rows. Python is `3.12.3-0ubuntu2.1`, iproute2 `6.1.0-1ubuntu6.4`, systemd `255.4-1ubuntu8.17`, and the installed kernel package `6.8.0-139.139`. **nftables, libnftables1, iptables, tcpdump, Docker, containerd and openssh-server are absent.** The local installer ISO has no nftables archive in its directory inventory. Prepare a separately pinned offline package set before installation; no general network access is needed for the first clone stage. This observation is package metadata, not a runtime binary/version test.

An exclusive bind to host `127.0.0.1:18181` succeeded and was immediately released. This is a point-in-time availability check, not a reserved port or forwarding rule. Actual NAT source identity and guard interface names remain measurements for the later trusted qualification stage.

The first inspection stopped before disk export when `clonemedium --help` was rejected as an unknown option. Installed `VBoxManage help clonemedium` displays the documentation (with exit 1); that is separate from a failed clone operation. The corrected read-only inspection completed. Original attempt files were preserved. No VM or network setting changed in either attempt. WSL needed command approval after sandbox access was denied.

## Reviewable operation

[New-GuardVm.ps1](New-GuardVm.ps1) defaults to a JSON preview and makes no native calls:

```powershell
pwsh -NoProfile -File research/validation/New-GuardVm.ps1
```

After separate approval, the apply form requires both its reference and the exact SHA-256 printed by the preview:

```powershell
pwsh -NoProfile -File research/validation/New-GuardVm.ps1 -Apply -ApprovalReference "<native creation approval>" -PlanSha256 "<reviewed plan digest>"
```

Before changes, it rejects path escapes/reparse points, existing target identities/directories, an existing one-use receipt directory, a changed hypervisor, a running/reconfigured source, a non-base disk, changed source bytes and insufficient free space. It records an intent before mutation. On failure it retains partial state and does not clean up, retry, boot or continue automatically. Success requires the new VM stopped/disconnected, an independent base-disk identity, and unchanged source configuration and bytes. A failed postcondition is a hold even if the new VM exists. Refusal-path tests use temporary files and a deliberately absent hypervisor executable; native application remains unmeasured.

## Network inputs for the later stage

[guard-network-inputs.json](guard-network-inputs.json) freezes the chosen address/flow contract and explicit missing measurements. It is **not an installed or syntax-qualified nftables ruleset** and supplies no deployment network-policy digest. The internal switch is `mcli1-validation-net-01`, guard `192.0.2.1/30`, executor `192.0.2.2/30`. The guard alone may later get a second ordinary-NAT adapter for loopback host ingress `18181` to guard `8081`; its static management address candidate is `10.0.3.15/24`. Neither guest gets default routing or DNS.

Freeze actual interface/MAC identities, permanent neighbors, the forwarded management source address and effective rules before activation. The guard is an endpoint/proxy with forwarding disabled. Default-drop ingress/input/output/forward policies must reject spoofing, IPv6, fragments, VLANs and other destinations. Live attempt authority precedes broker established-flow permission; fencing must terminate active streams as well as deny new admissions. The current control gate is loopback conformance code and still needs fixed-target guard transport and required wire observation. Kernel filtering alone does not implement request grants or stream cancellation.

Qualify guard boot, hardening, package/tool versions, policy startup, broker/control/deadman services and trusted positive/negative probes **before connecting the executor**. Then qualify the exact executor profile, Windows stop supervisor and independent observer/extractor. This plan does not close M1-12, M1-13 or the later executor-recovery/feasibility gates.
