# Tensor Reclaim changelog

This file records changes in the fork. The CLI is version 0.1.0; the inherited
kernel/package version is 2.0.0. Use the Git commit to identify an engine build.
No packaged fork release has been published.

## Unreleased

### Engine

- Correct the Turing loader setup and use the credited two-write payload.
  Require halted engines, idle DMA, cleared WPR2, and no pending PCIe
  transactions for the handoff that preserves selectors without FLR.
- Add a single-launch direct-selector path, enabled by default on GA102.
  Verify both selectors and unchanged protection masks before success.
  Other listed GA10x direct paths require explicit opt-in.
- Restore reported GA106M IDs `2520` and `2560`. Add reported GA103M `2420`
  and GA107 `25a2` without extending support to unreported IDs.
- Exercise production Falcon, payload, recipe, and transaction code with
  CPU-only synthetic MMIO checks and optional sanitizers.

### Tools

- Add read-only preflight and per-card observed status, exact-target setup and
  recovery plans, and a support table derived from the engine recipes.
- Add bounded, correctness-checked GEMM capture and conservative comparison.
  Reject incomplete configuration records and incompatible evidence.
- Preserve private capture outputs and label synthetic benchmark fixtures.

### Project

- Rename the project to Tensor Reclaim and add new banner artwork. Preserve
  existing CLI, kernel module, and package interfaces.
- Protect `main` with mandatory pull requests, both current CPU CI checks,
  resolved conversations, linear history, and administrator enforcement.

- Add automatic CPU-only checks, contribution and security guidance, fork
  branding, and a root GPL license copy.

### Validation limits

Physical improved-module trials remain pending. There is no measured speedup
claim for this fork. See [the validation record and source credits](docs/VALIDATION.md)
for observed checks, upstream proposal revisions, and known limits.
