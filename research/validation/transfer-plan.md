# Identity-gated transfer controller preparation

The newer [host-adapter checkpoint](host-adapter-plan.md) supplies prepared
collectors and a bounded Job Object accounting fix in the serial transport.
Its revision 03 grants supersede this checkpoint's revision 02 transport binding
for future activation. The measured evidence and snapshots below remain historical
and unchanged; no old or new grant has been activated.

The [serial primitive](maintenance-serial-plan.md) and
[guest controls](guest-control-plan.md) now have a controller, bounded command
compiler and standalone guest entry. Four role/purpose review packets remain
unarmed. No actual guest transfer, root apply, service command or VM action ran.
Product implementation and final native qualification remain open.

## Review packets and source revisions

| Role / purpose | Local directory | Raw grant SHA-256 |
| --- | --- | --- |
| Guard / inspect | `.local/validation/transfer-guard-inspect-02` | `9076c9c12a92ed63e0204718aa4a607c7a42b3a73ad0a92a89025c9791e7b3e7` |
| Guard / controls | `.local/validation/transfer-guard-controls-02` | `40b2f6b8d01930e7c667b32657b697a77095e722ae396299a363387fda8d9097` |
| Executor / inspect | `.local/validation/transfer-executor-inspect-02` | `7ecedafed520ac29fb8b10f5a39a55499c3f197a4ed924e5c506d1f72b1921eb` |
| Executor / controls | `.local/validation/transfer-executor-controls-02` | `0b2faf328e0b8252ffae8de0264913a22d71cb147cde0608c71f02d167befde4` |

All refuse with `transfer approval is unbound`. They contain source/input hashes
and proposed payloads, with actual identity, backup, approval, original lease and
clock fields empty. No observation was fabricated for the controls purpose.
These snapshots are provenance/review inputs, not complete deployable host
packages or activatable commands. [Evidence](transfer-evidence.json) records
exact inventories, source hashes, receipts and remaining gates. Revision 01
packets remain intact as earlier source snapshots; revision 02 binds the final
byte-freezing changes and was this checkpoint's review cohort. Use the newer host
review's revision 03 grants for the corrected transport source binding.

Integration exposed an ordering bug in the earlier probe: JSON sorting changed
unit/configuration map iteration and therefore the action-list hash. The planner
now follows the frozen mask list and sorts configuration destinations. A pure
replay of the retained old source reproduces the mismatch; the new source keeps
the same plan across a JSON round-trip. This was a refusal bug, not evidence of
an unsafe native apply; no root apply had run.

The current probe SHA-256 is
`598837d6ef704d54716b9982660d6b0377bae690a3a26a9570f55a4586969c99`;
the rebound control SHA-256 is
`6b01cd7ca8e27ae56ed55d1817e336c2a2d5cdab4a667916557bd8347dc70391`.
The serial worker adds an explicit nonce/step rejection frame and is pinned to
`0e7e3344d13ce4fc448e0943debb76bade221672cfef9f195f61cca0785e7502`.
Earlier local snapshots and historical measured evidence remain intact. Their
old source pins must not be mixed into this controller's activation cohort.

## Controller sequence

[maintenance_transfer.py](maintenance_transfer.py) checks a raw grant digest,
source/payload cohort, exact role/target/disk, independent backup, preboot/source
preservation receipts, scoped approvals and an already armed outside-VM lease.
Caller payload bytes are frozen before validation. Source hashes must match the
grant, the process-start source epoch and current files before dispatch. The
compiler extracts identity code and stages helper bytes from that verified source;
it refuses a changed helper instead of rereading unreviewed bytes.

It cannot create or renew that lease. A phase is at most 90 seconds and must
retain ten seconds before the original lease expiry for stop handling.

The controller records one durable attempt before starting collectors/I/O.
Reopening the journal cannot resume or replay that attempt. Separate sampler and
watchdog threads validate generation/fencing, immutable original deadlines,
supervisor owner, fresh host/storage/UART/disconnection facts and evidence refs.
A collector that stops returning cannot refresh its old sample. Native live-state
collection and approval authentication are still injected contracts, not
implemented or qualified adapters.

The first serial exchange is read-only. It requires isolated, nonoptimized Linux
Python as root, PID 1 systemd, loopback only, exact DMI/root UUID/boot identity,
ext4 root inode and the initial mount namespace. The controller validates the
framed reply before compiling any guest write. Wrong identity or a stale response
prevents upload and fences the admitted attempt.

The guest sample supplies its own clock values. The guest window adds no more
than the remaining host phase budget after receipt, capped at 60 seconds. It
does not copy host monotonic timestamps or reset the original host phase deadline.
This numeric mapping accounts conservatively for return latency; it does not
qualify VM clock drift, pause or suspend behavior. Host deadlines and independent
VM stop remain authoritative.

## Exact generated commands

[transfer_commands.py](transfer_commands.py) creates only fixed-purpose lines for
identity, stage creation, chunk writes, member finalization and invocation.
The host never executes a shell. Guest lines use absolute `/usr/bin/python3`
with `-I -B`; generated source is compressed/encoded as one quoted argument and
bounded before dispatch. Python documents
[isolated invocation](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I)
and [POSIX shell quoting](https://docs.python.org/3.12/library/shlex.html#shlex.quote).
The quoting applies to the trusted guest shell, not Windows command syntax.

The batch retains the serial limits: 128 steps, 256 KiB request and at most 2,047
printable characters per typed line. Payload members are capped at 1 MiB. Large
or poorly compressible data that cannot fit holds before stage creation; no
automatic split, deadline extension or transport fallback exists.

Each write rechecks root, boot/DMI, root device/inode, namespace and the guest
window, then opens the private stage through directory descriptors. Stages are
created exclusively under `/run/mcli1-observe-<nonce>` or
`/run/mcli1-control-<nonce>`. Partial members use exclusive creation, exact append
offsets, owner/mode/link checks and fsync. Finalization checks the compressed
hash, performs a bounded decode, checks the original hash/length and creates the
final member exclusively. Partial files are retained; there is no removal or
repair command. Python's [zlib documentation](https://docs.python.org/3.12/library/zlib.html)
describes bounded decompression state and remaining-data checks.

[guest_transfer_entry.py](guest_transfer_entry.py) rechecks identity, capsule and
every final member. It invokes only the pinned read-only probe or the separately
bound controls-only packet. It frames at most 512 KiB of report data. Any step
error emits a nonce-bound rejection rather than echoing private exception/config
bytes. The serial worker holds immediately on that frame; command echo cannot
acknowledge or reject a step.

## Stop ownership and uncertainty

The read-only identity operation receives a journal receipt only after its full
binding checks. The upload/invocation stays `possible-send` until report binding
and independent stop are both verified. Interrupted delivery, changed authority,
wrong results or missing stop evidence fence the attempt and retain uncertainty.
An acknowledged exchange alone is never installation or task acceptance.

After an admitted attempt, the controller fences before requesting stop. Its
injected stop adapter must signal the **original supervisor owner**, whose
one-shot ledger must report `stop-command-returned` with unchanged target and
deadlines. A separate nonce-bound observation must confirm poweroff, storage,
disabled NICs/no shares, freshness and the proposed ten-second bound. A poweroff
claim without that owner ledger cannot complete the transfer. No second native
stop implementation or automatic stop retry is introduced here.

Missing/late stop evidence leaves the durable state held for reconciliation.
Only both a bound result and stop proof produce
`transfer-and-stop-reported-not-accepted`, with authority still fenced. The
collector/stop callbacks and their truth are trusted boundaries; native owner
liveness, peer identity, approval authentication and actual stop/reap still need
qualification. Pre-grant/lease refusal performs no native action; an existing
outside-VM supervisor must continue enforcing its original authority.

## Measured checks and limits

Windows regression: **247 tests, 234 passed, 13 platform skips**. The selected
Linux suite passed **59 checks** as UID 1000 / Python 3.10.12. It includes the
probe/control fixtures and all 25 new transfer checks. Twelve selected cases use
real POSIX scratch files or synthetic children; controller/owner/observer states
are synthetic. No actual root staging, root apply or real service command ran.

Checks cover both purposes/roles, line/byte/step bounds, sorted JSON plan stability,
immutable phase timing, guest clock separation, changed hardware/identity,
lost acknowledgements, stale/blocked collectors, revocation, one-shot original
stop ownership, missing/cross-attempt stop evidence and payload/helper
substitution after admission. Native transfer-body
fixtures measure byte round-trip, duplicate offsets, compressed-data tampering,
bounded expansion, existing final files, isolated rejection and failure on this
non-guest tool host. These are not positive target-root or VirtualBox measurements.

The WSL package-status hash remained
`82f7835e29b4c8d3aab46e79e5d4719a53e03c9841f3aaa7eb02755740064501`
across all three selected runs. Historical VDI/VM observations were not refreshed.
No VM, package/tool installation, media mount, model/provider call or repository
upload occurred. Root/namespace checks do not establish a boundary against
hostile guest root or bind-mount manipulation. Kernel stalls, clock behavior,
physical-power-loss/database-loss recovery and complete deployment/runtime
behavior remain unqualified.

## Next check

Prepare and qualify the bounded live-state/original-supervisor stop adapters and
their evidence format. Prepare the same-boot inspection/approval handoff as well:
controls require a genuine observation from the current boot, but a completed
inspection attempt always stops its VM. Its old boot-bound observation cannot
authorize a later control boot; this handoff is still unresolved.

Native VM creation, boot/UART activation, root-session
establishment, transfer and control changes require their applicable explicit
approvals. Disconnected guard creation and the phase-boundary selection remain
pending. Installation, repeated readiness, final isolation/routing/recovery and
the feasibility decision remain open.
