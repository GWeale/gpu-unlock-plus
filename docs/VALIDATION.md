# Engine validation and source credits

Observed on Hatter, 2026-11-04 UTC. The writable owner checkout is
`/home/hatter/Developer/gpu-unlock-plus`. No GPU was accessed by this work.
The source base is upstream `7eb51bccae0a0b7e599e084d971170e9a1e82d0c`;
the prior tooling delivery ended at `4c59aa554216a5d723ac9ee509450b6d46c8a561`.
Earlier validation remains in that revision's history.

## Observed engine results

`BASELINE=1 tests/engine/run.sh` compiles the original `falcon.c` from the base
and the amended production C against the same synthetic MMIO interface:

- The original loader returns `-ENODEV` with HALTED left set after reset,
  without starting the loader. The Turing-scoped path completes.
- With HALTED initially clear, the original loader starts but times out when
  physical requests without a context are denied. The amended Turing path sets
  FBIF's physical-no-context bit, clears DMACTL, and completes the fake launch.
- Turing-only allowance of the direct-loader HALTED timeout leaves GA100's
  behavior strict. PRI errors, reset failures, real launch timeouts, invalid
  buffers, and invalid geometry remain failures.
- A 257-byte DMA transfer emits two 256-byte transfers. This already worked
  in the base. No stale DMEM-alignment patch was ported.

The selector transaction moved into `engine.c` so the host checks execute the
same implementation used by the module. The tests call real recipe lookup,
payload construction, entry assessment, transaction execution, and readback
verification. They cover single-launch direct operation, rejected PLM tables,
no host writes in direct mode, no retry after failure, protection mutations,
selector loss after reset, WPR2 remaining enabled, unreadable results, failed
handoff, and stock-signature restoration failure. Legacy retry remains bounded
and requires a successful prior launch. Mixed-family tests exercise Turing,
GA102, other listed GA10x dies, and Ada. GA100's absent PCI gate stays absent.

Turing handoff tests require both engines halted and DMA idle. Busy or
inaccessible engines fail. Invalid payload slots and words fail before image
writes; allocation sentinels remain intact for valid recipe construction.
The complete Turing signature equals nlzy's pinned SHA-256:
`b0ec90294d1de3c67e024631c0a11000f281470d76eed806fc24c66b7fd1ef41`.

The fake launch decodes payload slots and applies synthetic register effects.
It does **not** execute or emulate NVIDIA firmware or the Falcon gadgets.
The hash proves layout equivalence, not mutex release on a physical GPU.
Kernel PCI claim/reset APIs, actual DMA coherency, real firmware acceptance,
full ROM/firmware transactions, display handoff, and allocation retention under
physical device failure are not exercised by the host fixtures. The kernel
retains its conservative ownership rule: uncertain firmware execution retains
DMA buffers and BAR ownership until power off.

## Independent review correction

A fresh-context native review on Desktop examined revision
`6574d192f3b794696fef236385909cf2ed38aa21` and found one material defect.
The new Turing no-FLR handoff checked that the DMA queue was not full instead
of checking that DMA was idle. NVIDIA's pinned
[TU102 definitions](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/610.43.03/src/common/inc/swref/published/turing/tu102/dev_falcon_v4.h#L77)
assign FULL to bit 0 and IDLE to bit 1. The handoff now requires IDLE=1 for
both GSP and SEC2 before releasing buffers.

The lead reproduced the defect against the reviewed production C: halted
engines with FULL=0 and IDLE=0 incorrectly passed. The amended production C
passes the expanded fixture under normal compilation and AddressSanitizer
plus UndefinedBehaviorSanitizer. Each engine is checked with not-full/busy,
full/busy, and idle states. No hardware operations were used for this check.
The independent reviewer found no other material issue in that bounded pass;
this does not certify physical firmware or suspend behavior.

## Checks

| Check | Result |
| --- | --- |
| `BASELINE=1 tests/engine/run.sh` | Passed old failure reproduction, new behavior and Turing reference hash |
| `SANITIZE=1 tests/engine/run.sh` | Passed AddressSanitizer and UndefinedBehaviorSanitizer on the C fixtures |
| `make check` | Passed production C checks, 32 Python CLI/benchmark/packaging tests, Python compilation and whitespace checks |
| `make -C kernel/gpu_unlock KCFLAGS=-Werror -j2` | Passed against installed `7.0.0-42-generic` headers |
| `make dist` | Passed; archive contains the modified engine, C fixtures and pilot |
| Private package staging | Passed in the existing fake-root packaging check; includes `engine.c` and `engine.h` through the existing module source glob |
| Physical improved-module tests | Not run |
| Container distribution matrix, firmware generation and real package installation | Not run |
| Hidden independent review | Completed on Desktop against `6574d19`; one DMA-idle defect corrected and regression-tested |

The module build reports the GCC executable-name difference, matching GCC
15.2.0 versions, unavailable `pahole`, and skipped BTF because `vmlinux` is absent.
The module is produced. These build-environment messages do not establish GPU
behavior.

The parent separately captured an RTX 3080 12 GB stock/existing-driver baseline
on Desktop using cuBLAS and CUDA from a user cache. That result is not a test of
this module. Raw identity, timings, and logs remain private on Desktop. The
improved-module trial, suspend/resume, retained unlock, performance comparison,
and every other board remain untested here. No speedup is claimed.

## Source credits

These are reviewed source inputs, not merged upstream changes or original
hardware discoveries by this fork. Original upstream history, Petri Krohn's
GA102 chain comments, and licensing remain intact. The proposal commits also
credit Claude Opus 5.5 for their development and testing.

| Source | Exact revision | Used here |
| --- | --- | --- |
| [RakkiPoni #294](https://github.com/Zagitta/gpu-unlock/pull/294) | `9422be4c7920ceb71841c4219ef1d352ef8c2344` | Physical-no-context loader setup, empirical reset wait, Turing two-write payload and handoff |
| [#294 prerequisite branch](https://github.com/Zagitta/gpu-unlock/commit/5247c22299d460546a9801e34401a204c5655878) | `5247c22299d460546a9801e34401a204c5655878` | Post-reset GSP HALTED allowance, absent from #294's PR-only diff against its non-main base |
| [nlzy/turing-unlock generator](https://github.com/nlzy/turing-unlock/blob/417f333263ff169e8f449c931b70db9dfd7b8ef4/firmware/generate_v67.py) | `417f333263ff169e8f449c931b70db9dfd7b8ef4` | GPL two-write ACR mutex release chain and independent whole-image digest |
| [Lukium #252](https://github.com/Zagitta/gpu-unlock/pull/252) | `62105cf46bd905d67c055c77bab0c2e3b7b3bc80` | Signed Booter writes selectors directly, protected PLMs, single-launch limit |
| [Cognizaunce #212](https://github.com/Zagitta/gpu-unlock/pull/212), [regression #270](https://github.com/Zagitta/gpu-unlock/issues/270) | `a278a53ba0a9b412bcb7d851c289b1a5ed927461` | Restore GA106M `2520` and `2560` lost in recipe refactoring |
| [Stradivario #217](https://github.com/Zagitta/gpu-unlock/pull/217) | `93e751fb813716e5d6ab00f8d9beb7fe28da8848` | Add reported GA103M `2420` |
| [qwecvw #231](https://github.com/Zagitta/gpu-unlock/pull/231) | `f8bc9936e1842b6052c07c21becc7086b5747c7d` | Add only the reported GA107 `25a2`, not all 27 proposed IDs |

Changes from those proposals: the Turing HALTED allowances and reset delay are
scoped to the known Turing family; other paths stay strict. Turing cannot retry
or refill FRTS and must prove halted engines, idle DMA, cleared WPR2, and no
pending PCIe transactions before releasing memory. Direct mode defaults only
on GA102, where the proposal reports physical tests, rather than all GA10x.
Both entry protection masks must still match after the launch and after FLR.
A read error or mismatch fails the transaction. Open PLMs without matching
selectors return busy rather than falsely reporting an existing unlock.

The FWSEC source audit found `falcon_dma_valid()` already rounds to 256 bytes.
The v3 ROM parser already checks the rounded data span against `image_size`.
For v2, the parser bounds DMEM in an aligned image, and the loader rejects
unaligned `data_off`; together those bounds contain the rounded tail. No
additional buffer rewrite or old alignment-rejection fix was needed.

## Delivery boundary

Only code, synthetic host checks, local builds, documentation, private commits,
private push, and scoped backup are part of this delivery. No module was
installed or loaded, no boot source was changed, and no host was rebooted.
No public PR, upstream comment, release, or merge was created. The RTX 3080
pilot is prepared separately and has not been applied.
