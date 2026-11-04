# Per-card recovery engine

This fork adds a session policy for RTX 20/30 unlocks: an uncertain operation
cannot silently become the next resume attempt. It also recognizes an eligible
kept-power unlock before requiring any firmware files, and validates Falcon
transfers before reset.

These changes address software paths reproduced with production C on a CPU.
They have no physical module, suspend/resume, performance, or application-speed
validation yet. They do not increase the hardware's unlocked tensor rate.

## Recovery belongs to the card's session

Previously, a failed resume could retain firmware-visible DMA buffers and BAR
ownership, while the coordinator kept only its old boot-success flag. A later
resume remained eligible for a new operation, or could recognize the selector
values from an incomplete operation as an existing unlock. There was no durable
caller-owned record of the unresolved ownership.

Each card now has its own session. The transaction returns its original operation
error, cleanup error, and whether it retained DMA. Either retained ownership or
failed cleanup establishes `POWER_OFF_REQUIRED`. Later rounds reject that card
before any assessment, firmware preparation, or transaction callback. Other
cards continue independently. A failed restoration also pins the module, even
when buffers were freed, so unloading and reloading cannot erase the barrier.

| State | Next round |
| --- | --- |
| `NEW` | Perform a fresh read-only assessment, then prepare firmware if necessary |
| `PREPARED` | Execute once using immutable shared firmware; another preparation is refused |
| `READY` | Assess again; previous success is not current hardware evidence |
| `POWER_OFF_REQUIRED` | Refuse every backend callback and retain the original terminal errors |

There is no force-clear or retry control. A suspend/resume does not clear the
hold. Recovery requires the documented power-off procedure. The in-memory record
lasts for this module/kernel session; it is not a persistent hardware latch and
cannot prove that a later warm reboot physically reset a passed-through card.

The kernel emits a cached terminal record through the normal per-BDF log:

```text
gpu_unlock: stage=session round=1 phase=2 state=3 operation=-110 cleanup=-16 retained=1 result=-110
```

`phase` is assessment `0`, firmware preparation `1`, or transaction `2`.
`state` is new `0`, prepared `1`, ready `2`, or power-off required `3`.
The example is synthetic. A denied later admission reports its denial separately
and preserves the original operation and cleanup errors in the record.
No DMA addresses or raw firmware contents are added to this record.

## Working selectors do not need firmware preparation

Assessment runs under the PCI device lock, only in the existing pre-driver or
pre-NVIDIA-resume window. It maps BAR0 for observation and always unmaps it.
It does not claim a PCI region, change PCI configuration or DMA masks, allocate
DMA buffers, or write registers. Both unlocked selectors are required.

A retained result completes that assessment without firmware preparation. A
cold card still requires the complete validated firmware bundle. Shared assets
are prepared for every card needing a transaction before workers begin. Driver
ownership and entry state are rechecked in the mutating transaction, so a sample
from the preparation phase never authorizes a later write by itself.

With memory decoding disabled, cold assessment defers to the existing transaction
that enables decoding. Resume assessment refuses that state. These observations
are not continuous monitoring of an active NVIDIA-owned GPU. There is no new
runtime-PM callback hook or live sysfs register interface.

## Invalid transport geometry fails before ownership changes

The HS transport previously validated core code and data before reset, but
validated its optional OS stub only when submitting that later DMA transfer.
The same malformed OS-offset fixture now fails before any MMIO write. Pure
validators are shared by the transports and FWSEC preparation. FWSEC runs its
validator before enabling bus mastering or committing conservative DMA retention.

This distinction is deliberate: untouched geometry rejection can unwind normally.
A reset, transfer, or completion failure after possible firmware access still
uses conservative retention. `started=false` alone never proves that hardware
was untouched. Existing support for non-256-aligned DMEM sizes is preserved.

## Evidence and limits

Run the complete host suite with:

```sh
make check
SANITIZE=1 tests/engine/run.sh
BASELINE=1 tests/engine/run.sh
make -C kernel/gpu_unlock KCFLAGS=-Werror -j2
```

The baseline mode rebuilds historical production Falcon C. It reproduces both
the earlier Turing loader failures and the pre-reset OS-transfer validation gap.
Session fixtures drive the production session API and selector transaction
through synthetic MMIO. They cover repeated quarantine denial, firmware absence
with retained selectors, cleanup-only failure, preservation of both errors,
fresh reassessment, safe retry, and independent cards.

The fixtures do not execute NVIDIA firmware or exercise real PCI mapping,
resource restoration, module pinning, display handoff, or suspend ordering.
Those kernel-adapter paths receive source review and a warnings-as-errors build;
physical validation remains a separate attended pilot. Existing pilot packages
identify source `981a9f4` and do not contain this session feature.

[The validation record](VALIDATION.md) separates earlier package results from
this change. [Upstream #184](https://github.com/Zagitta/gpu-unlock/issues/184)
documents an older invalid-DMEM retention failure; that size-rounding defect was
already fixed, while the OS-transfer case was reproduced here.
[Upstream #255](https://github.com/Zagitta/gpu-unlock/issues/255) documents
selector persistence across a passthrough guest reboot. It motivates careful
kept-power handling; it does not validate this new session engine.
