# Benchmark contract, version 1

`gpu-unlock-plus.benchmark/v1` describes controlled eager PyTorch GEMM captures.
It does not describe tensor issue rate, engine success, or application throughput.
The committed fixture is synthetic. It is never a hardware result.

## Capture controls

The target is a full PCI BDF. `nvidia-smi` resolves it to a physical UUID, which
must match exactly one CUDA device's reported UUID. CUDA ordinals and NVIDIA
enumeration indices are never assumed interchangeable. MIG is unsupported.

Inputs are seeded normal FP16 or BF16 matrices. The output is preallocated FP32.
The harness requests eager cuBLAS and verifies these controls are false:

- `allow_fp16_reduced_precision_reduction`
- `allow_bf16_reduced_precision_reduction`
- `allow_fp16_accumulation`
- `allow_tf32`

Missing or unverifiable controls, unsupported FP32-output APIs, absent CUDA,
missing power data, or competing compute processes abort capture. Controls and
the previous BLAS preference are restored after success or failure. A backend
contract is recorded, not instruction-level verification. PyTorch or driver bugs
remain possible. No `torch.compile` or custom kernels are involved.

Every timed GEMM uses CUDA start/end events, a prior device synchronization, and
an end-event synchronization. Allocation, reference computation, validation and
`nvidia-smi` queries are outside the event interval. Every output is checked for
finite values. A grid of 16 by 16 evenly spaced output elements is checked against
a CPU FP64 product of the actual quantized input rows/columns across the full K
dimension. This is sampled numerical validation, not exhaustive output equality.
It runs after warmup and after each timed result.

The sample passes when each absolute error is at most
`0.002 + 0.002 * abs(reference)`. The maximum scaled error must be finite and no
greater than 1. The same fixed tolerances are required when reading results.
An incorrect, nonfinite or incomplete result cannot enter comparison.

Dimensions are 16..4096, warmups 1..20, repeats 5..50, and seed is uint32.
Total requested work is at most 4 trillion multiply/add operations. The estimated
VRAM use is two-byte inputs, four-byte output, a one-byte validation mask, and
64 MiB of workspace reserve. It must fit the user budget (64..2048 MiB) and half
the currently free VRAM. This estimate is not a hard allocator cap; CUDA libraries
can reserve additional memory and allocation can still fail. There is no GPU-hang
watchdog. Reduce shapes for small cards.

## Result fields

The writer publishes a complete new JSON file atomically with mode 0600. It
refuses existing files and symlinks. CLI output contains only a capture summary;
UUID/identity live in the private file under ignored `.local/`.

| Field | Evidence |
| --- | --- |
| `schema`, `synthetic`, `tool_version`, `created_at` | Format, fixture marker, producer and UTC capture time |
| `config` | M/N/K, input dtype, warmups, repeats, seed and memory budget |
| `gpu` | BDF, physical UUID, reported name, PCI vendor/device ID, memory and capability |
| `environment` | Kernel, architecture, torch, CUDA runtime and NVIDIA driver versions |
| `environment.cuda_env_sha256` | Hash of CUDA/CUBLAS/NVIDIA/PYTORCH/TORCH-prefixed environment variables; values are not stored |
| `math` | Input/output types, requested cuBLAS contract and verified flags; instruction proof remains false |
| `correctness` | Fixed tolerances, reference method, sample shape, checks performed, finiteness and maximum scaled error |
| `conditions` | Warm and finish power limit, temperature, SM/memory clocks, P-state and competing-compute checks |
| `timing` | Synchronized CUDA-event method and every repeat in milliseconds |
| `unlock_state` | Always `not_determined_by_benchmark` |

## Comparison refusals

Both records must validate before comparison. GPU identity (including UUID/BDF),
configuration, tool version, environment and math metadata must match exactly.
Synthetic and measured records cannot be mixed. Unknown precision/correctness,
missing process checks, malformed schemas and invalid timings are errors.

Across all four warm/finish snapshots, power-limit spread must be at most 0.5 W,
temperature spread at most 5 degrees C, SM/memory clock spread at most 5 percent,
and P-state identical. Unknown power/clock data cannot pass. The harness observes
other compute processes before and after timing. It cannot exclude graphics
load, brief competing processes, thermal changes between snapshots, or system
and environment differences not recorded in the schema.

The comparison returns median, minimum, maximum, and baseline/candidate timing
ratio only when these checks pass. Overlapping repeat ranges are inconclusive.
Non-overlap yields a candidate timing change, not an unlock claim. Repeat
controlled captures across multiple boots and validate a real workload before
attributing a difference to the engine. Any causal performance assessment still
requires hardware evidence and an identified workload limiter.

The CLI returns 0 for a completed report (including synthetic/overlapping results),
1 for an incompatible comparison, and 2 for invalid inputs or unavailable capture.
Doctor/status exit 0 means observations were collected, not that installation is
safe or an unlock succeeded. Automation must inspect the report fields.

## Primary API references

Checked 2026-11-03. Installed APIs are checked at runtime; these links are not a
substitute for observing the installed backend.

- [PyTorch `torch.mm` FP32 output contract](https://docs.pytorch.org/docs/2.15/generated/torch.mm.html).
- [PyTorch CUDA precision controls and synchronized timing](https://docs.pytorch.org/docs/2.15/notes/cuda.html).
- [NVIDIA `nvidia-smi` identity, query and power documentation](https://docs.nvidia.com/deploy/nvidia-smi/).
