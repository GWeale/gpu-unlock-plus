# SPDX-License-Identifier: GPL-2.0-only
"""Versioned, correctness-checked GEMM captures with conservative comparison."""

from dataclasses import asdict, dataclass, fields
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import tempfile

from . import __version__
from .system import MAX_READ, SOURCE_ROOT, System, bdf

SCHEMA = "gpu-unlock-plus.benchmark/v1"
FLAGS = ("allow_fp16_reduced_precision_reduction", "allow_bf16_reduced_precision_reduction",
         "allow_fp16_accumulation", "allow_tf32")
ATOL, RTOL = 0.002, 0.002
SMI_FIELDS = ("pci.bus_id", "uuid", "name", "driver_version", "power.limit", "temperature.gpu",
              "clocks.current.sm", "clocks.current.memory", "pstate")


@dataclass(frozen=True)
class BenchmarkConfig:
    m: int = 2048
    n: int = 2048
    k: int = 2048
    dtype: str = "float16"
    warmup: int = 5
    repeats: int = 10
    seed: int = 1729
    memory_mib: int = 256

    def validate(self):
        if any(type(x) is not int or not 16 <= x <= 4096 for x in (self.m, self.n, self.k)):
            raise ValueError("Each shape dimension must be between 16 and 4096.")
        if self.dtype not in ("float16", "bfloat16"):
            raise ValueError("Only float16 and bfloat16 inputs are supported.")
        if type(self.warmup) is not int or type(self.repeats) is not int or not 1 <= self.warmup <= 20 or not 5 <= self.repeats <= 50:
            raise ValueError("Use 1..20 warmups and 5..50 repeats.")
        if type(self.seed) is not int or type(self.memory_mib) is not int or not 0 <= self.seed <= 2**32 - 1 or not 64 <= self.memory_mib <= 2048:
            raise ValueError("Seed must be uint32; memory budget must be 64..2048 MiB.")
        if 2 * self.m * self.n * self.k * (self.warmup + self.repeats) > 4_000_000_000_000:
            raise ValueError("Total GEMM work exceeds the bounded run budget; reduce shape or repeats.")
        if self.estimated_bytes > self.memory_mib * 1024**2:
            raise ValueError("Estimated tensors plus 64 MiB workspace reserve exceed --memory-mib.")

    @property
    def estimated_bytes(self):
        return 2 * (self.m * self.k + self.k * self.n) + 5 * self.m * self.n + 64 * 1024**2


def number(value, label, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"Invalid finite number: {label}.")
    return value


def smi(system, address):
    observation = system.run(["nvidia-smi", "-i", address, "--query-gpu=" + ",".join(SMI_FIELDS),
                              "--format=csv,noheader,nounits"])
    if observation.error:
        raise ValueError("nvidia-smi identity/power evidence unavailable: " + observation.error)
    rows = list(csv.reader((observation.value or "").splitlines()))
    if len(rows) != 1 or len(rows[0]) != len(SMI_FIELDS):
        raise ValueError("Expected exactly one physical GPU in nvidia-smi evidence.")
    row = dict(zip(SMI_FIELDS, (item.strip() for item in rows[0])))
    domain, rest = row["pci.bus_id"].lower().split(":", 1)
    if bdf(f"{int(domain, 16):04x}:{rest}") != address:
        raise ValueError("nvidia-smi PCI identity does not match --target.")
    if not row["uuid"].startswith("GPU-") or not row["driver_version"]:
        raise ValueError("Physical GPU UUID/driver version unavailable; MIG is unsupported.")
    conditions = {}
    for key, name in (("power.limit", "power_limit_w"), ("temperature.gpu", "temperature_c"),
                      ("clocks.current.sm", "sm_clock_mhz"), ("clocks.current.memory", "memory_clock_mhz")):
        try:
            conditions[name] = number(float(row[key]), name, positive=True)
        except ValueError:
            raise ValueError(f"Required nvidia-smi evidence unavailable: {key}.") from None
    if row["pstate"] not in ("P0", "P1", "P2"):
        raise ValueError("GPU is not in an observed compute performance state (P0/P1/P2). Warm the GPU and retry.")
    conditions["pstate"] = row["pstate"]
    return row, conditions


def no_other_compute(system, address):
    result = system.run(["nvidia-smi", "-i", address, "--query-compute-apps=pid", "--format=csv,noheader,nounits"])
    if result.error:
        raise ValueError("Cannot check competing compute processes; no benchmark recorded.")
    try:
        pids = [int(line.strip()) for line in (result.value or "").splitlines()]
    except ValueError:
        raise ValueError("Competing compute process evidence is unknown.") from None
    if any(pid != os.getpid() for pid in pids):
        raise ValueError("Other compute processes are present on the selected GPU. Retry in an idle session.")


def normalized_uuid(value):
    return str(value).lower().removeprefix("gpu-").replace("-", "")


@contextmanager
def precision_contract(torch):
    matmul, saved = torch.backends.cuda.matmul, {}
    old_library = None
    try:
        for flag in FLAGS:
            saved[flag] = getattr(matmul, flag)
            setattr(matmul, flag, False)
            if getattr(matmul, flag) is not False:
                raise ValueError(f"Cannot verify {flag}=False. FP32 accumulation is unverified; no benchmark recorded.")
        old_library = torch.backends.cuda.preferred_blas_library()
        torch.backends.cuda.preferred_blas_library("cublas")
        if str(torch.backends.cuda.preferred_blas_library()).rsplit(".", 1)[-1].lower() != "cublas":
            raise ValueError("Cannot verify cuBLAS backend preference.")
        yield
    except (AttributeError, TypeError) as error:
        raise ValueError("Installed torch lacks the required FP32 output/precision API; accumulation is unverified, no benchmark recorded.") from error
    finally:
        if old_library is not None:
            torch.backends.cuda.preferred_blas_library(old_library)
        for flag, value in saved.items():
            setattr(matmul, flag, value)


def check_sample(actual, reference):
    if len(actual) != 256 or len(reference) != 256:
        raise ValueError("Correctness sample must contain 256 values.")
    errors = [abs(a - r) / (ATOL + RTOL * abs(r)) for a, r in zip(actual, reference)]
    if any(not math.isfinite(value) or value > 1 for value in errors):
        raise ValueError("GEMM correctness failed; no benchmark recorded.")
    return max(errors)


def capture(address, config, output):
    address = bdf(address)
    config.validate()
    output = Path(output).absolute()
    if not output.resolve().is_relative_to((SOURCE_ROOT / ".local").resolve()) or output.suffix != ".json":
        raise ValueError("Save private benchmark identity only under the ignored repository .local/ directory as .json.")
    if output.exists() or output.is_symlink():
        raise ValueError("Output exists; choose a new filename so the baseline is preserved.")
    try:
        import torch
    except ImportError:
        raise ValueError("Optional PyTorch is not installed. Use an existing CUDA-enabled torch environment; no dependencies were installed.") from None
    if not torch.cuda.is_available() or torch.version.hip:
        raise ValueError("A CUDA-enabled PyTorch environment and NVIDIA GPU are required. No benchmark recorded.")
    system = System()
    # The first identity query permits idle P-states. Warm-state checks happen below.
    identity = system.run(["nvidia-smi", "-i", address, "--query-gpu=uuid", "--format=csv,noheader,nounits"])
    if identity.error or not (identity.value or "").startswith("GPU-"):
        raise ValueError("Cannot resolve the selected PCI address to a physical GPU UUID.")
    matches = [index for index in range(torch.cuda.device_count())
               if normalized_uuid(getattr(torch.cuda.get_device_properties(index), "uuid", "")) == normalized_uuid(identity.value)]
    if len(matches) != 1:
        raise ValueError("Cannot match CUDA device UUID to PCI target. Use a torch version exposing physical device UUIDs; MIG is unsupported.")
    device = matches[0]
    torch.cuda.set_device(device)
    props = torch.cuda.get_device_properties(device)
    free, _ = torch.cuda.mem_get_info(device)
    if config.estimated_bytes > free // 2:
        raise ValueError("Run would use more than half the currently free VRAM; reduce --shape.")
    if config.dtype == "bfloat16" and not torch.cuda.is_bf16_supported():
        raise ValueError("This CUDA device does not support BF16.")
    with precision_contract(torch):
        try:
            with torch.inference_mode():
                dtype = getattr(torch, config.dtype)
                generator = torch.Generator(device=f"cuda:{device}").manual_seed(config.seed)
                a = torch.randn((config.m, config.k), dtype=dtype, device=f"cuda:{device}", generator=generator)
                b = torch.randn((config.k, config.n), dtype=dtype, device=f"cuda:{device}", generator=generator)
                out = torch.empty((config.m, config.n), dtype=torch.float32, device=f"cuda:{device}")
                rows = [i * (config.m - 1) // 15 for i in range(16)]
                cols = [i * (config.n - 1) // 15 for i in range(16)]
                reference = a[rows, :].cpu().double() @ b[:, cols].cpu().double()
                reference_values = reference.flatten().tolist()

                def gemm():
                    torch.mm(a, b, out_dtype=torch.float32, out=out)

                def check():
                    actual = out[rows, :][:, cols].cpu().double().flatten().tolist()
                    scaled = check_sample(actual, reference_values)
                    if not torch.isfinite(out).all().item():
                        raise ValueError("GEMM correctness failed; no benchmark recorded.")
                    return scaled

                for _ in range(config.warmup):
                    gemm()
                torch.cuda.synchronize(device)
                max_error = check()
                no_other_compute(system, address)
                row, warm = smi(system, address)
                samples = []
                start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                for _ in range(config.repeats):
                    torch.cuda.synchronize(device)
                    start.record()
                    gemm()
                    end.record()
                    end.synchronize()
                    samples.append(number(float(start.elapsed_time(end)), "elapsed_ms", positive=True))
                    max_error = max(max_error, check())
                end_row, finish = smi(system, address)
                no_other_compute(system, address)
                if row["uuid"] != end_row["uuid"] or row["driver_version"] != end_row["driver_version"]:
                    raise ValueError("GPU identity changed during capture.")
        except (AttributeError, TypeError) as error:
            raise ValueError("Installed torch lacks the required FP32 output API; accumulation is unverified, no benchmark recorded.") from error
    pci = f"/sys/bus/pci/devices/{address}"
    result = {"schema": SCHEMA, "synthetic": False,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "tool_version": __version__, "config": asdict(config),
              "gpu": {"bdf": address, "uuid": row["uuid"], "name": row["name"],
                      "vendor_id": system.read(pci + "/vendor").value,
                      "device_id": system.read(pci + "/device").value,
                      "memory_bytes": props.total_memory, "capability": [props.major, props.minor]},
              "environment": {"kernel": platform.release(), "machine": platform.machine(),
                              "torch": str(torch.__version__), "cuda": torch.version.cuda,
                              "driver": row["driver_version"],
                              "cuda_env_sha256": hashlib.sha256(json.dumps({key: value for key, value in os.environ.items()
                                  if key.startswith(("CUDA_", "CUBLAS_", "NVIDIA_", "PYTORCH_", "TORCH_"))}, sort_keys=True).encode()).hexdigest()},
              "math": {"input": config.dtype, "output": "float32", "accumulation": "fp32_backend_contract",
                       "backend": "cublas", "flags": {flag: False for flag in FLAGS},
                       "kernel_instruction_proof": False},
              "correctness": {"passed": True, "reference": "quantized_inputs_cpu_float64",
                              "sample_shape": [16, 16], "checked_outputs": config.repeats + 1,
                              "atol": ATOL, "rtol": RTOL, "max_scaled_error": max_error, "full_output_finite": True},
              "conditions": {"warm": warm, "finish": finish, "no_other_compute_observed": True,
                             "graphics_and_external_load": "unobserved"},
              "timing": {"method": "cuda_events_synchronized", "samples_ms": samples},
              "unlock_state": "not_determined_by_benchmark"}
    validate_result(result)
    write_result(output, result)
    return {"command": "bench", "output": str(output), "correctness": "passed",
            "samples": len(samples), "next_action": "Capture a second controlled run with the same options; compare locally. No unlock state was inferred."}


def write_result(path, result):
    path = Path(path)
    if path.suffix != ".json":
        raise ValueError("Benchmark output must be a .json file in an ignored local directory.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".capture-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and refuses to overwrite any existing result/symlink.
        os.link(temporary, path)
    except FileExistsError:
        raise ValueError("Output exists; choose a new filename so the baseline is preserved.") from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def validate_result(result):
    try:
        if result["schema"] != SCHEMA or type(result["synthetic"]) is not bool:
            raise ValueError("Unsupported benchmark schema or synthetic marker.")
        if not isinstance(result["config"], dict) or set(result["config"]) != {field.name for field in fields(BenchmarkConfig)}:
            raise ValueError("Incomplete or unrecognized benchmark configuration.")
        config = BenchmarkConfig(**result["config"])
        config.validate()
        if not isinstance(result["tool_version"], str) or not result["tool_version"]:
            raise ValueError("Missing benchmark tool version.")
        gpu, env, math_mode = result["gpu"], result["environment"], result["math"]
        bdf(gpu["bdf"])
        for field in ("bdf", "uuid", "name", "vendor_id", "device_id"):
            if not isinstance(gpu[field], str) or not gpu[field].strip():
                raise ValueError("Incomplete GPU identity.")
        if not re.fullmatch(r"GPU-[0-9a-fA-F-]{36}", gpu["uuid"]) or gpu["vendor_id"] != "0x10de" or not re.fullmatch(r"0x[0-9a-fA-F]{4}", gpu["device_id"]):
            raise ValueError("Malformed physical GPU identity.")
        number(gpu["memory_bytes"], "GPU memory", positive=True)
        if (not isinstance(gpu["capability"], list) or len(gpu["capability"]) != 2 or
                any(type(value) is not int or not 0 <= value <= 99 for value in gpu["capability"])):
            raise ValueError("Missing compute capability.")
        for field in ("kernel", "machine", "torch", "cuda", "driver", "cuda_env_sha256"):
            if not isinstance(env[field], str) or not env[field].strip():
                raise ValueError("Incomplete environment evidence.")
        if (math_mode["accumulation"] != "fp32_backend_contract" or math_mode["input"] != config.dtype or
                math_mode["output"] != "float32" or math_mode["backend"] != "cublas" or
                any(math_mode["flags"].get(flag) is not False for flag in FLAGS)):
            raise ValueError("FP32 accumulation backend contract is unverified.")
        correctness = result["correctness"]
        if (correctness["passed"] is not True or correctness["full_output_finite"] is not True or
                correctness["reference"] != "quantized_inputs_cpu_float64" or correctness["sample_shape"] != [16, 16] or
                correctness["checked_outputs"] != config.repeats + 1 or
                correctness["atol"] != ATOL or correctness["rtol"] != RTOL or
                not 0 <= number(correctness["max_scaled_error"], "correctness error") <= 1):
            raise ValueError("Correctness evidence failed or is incomplete.")
        timing = result["timing"]
        if timing["method"] != "cuda_events_synchronized" or not isinstance(timing["samples_ms"], list) or len(timing["samples_ms"]) != config.repeats:
            raise ValueError("Missing synchronized timing repeats.")
        for value in timing["samples_ms"]:
            number(value, "timing sample", positive=True)
            if not 0.000001 <= value <= 60000:
                raise ValueError("Timing sample outside the supported 1 ns..60 s interval.")
        conditions = result["conditions"]
        if conditions["no_other_compute_observed"] is not True:
            raise ValueError("Competing compute load was not checked.")
        for stage in ("warm", "finish"):
            for field in ("power_limit_w", "temperature_c", "sm_clock_mhz", "memory_clock_mhz"):
                number(conditions[stage][field], field, positive=True)
            if conditions[stage]["pstate"] not in ("P0", "P1", "P2"):
                raise ValueError("Unknown compute performance state.")
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed or incomplete benchmark result.") from error
    return result


def read_result(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_READ + 1)
    if len(data) > MAX_READ:
        raise ValueError("Benchmark input exceeds 4 MiB.")
    return validate_result(json.loads(data))


def compare(before, after):
    before, after = validate_result(before), validate_result(after)
    reasons = []
    for field in ("synthetic", "tool_version", "config", "gpu", "environment", "math"):
        if before[field] != after[field]:
            reasons.append(field + " differs")
    snapshots = [run["conditions"][stage] for run in (before, after) for stage in ("warm", "finish")]
    for field, tolerance in (("power_limit_w", 0.5), ("temperature_c", 5.0)):
        values = [snapshot[field] for snapshot in snapshots]
        if max(values) - min(values) > tolerance:
            reasons.append(field + " conditions differ/drift")
    for field in ("sm_clock_mhz", "memory_clock_mhz"):
        values = [snapshot[field] for snapshot in snapshots]
        if max(values) / min(values) > 1.05:
            reasons.append(field + " conditions differ/drift")
    if len({snapshot["pstate"] for snapshot in snapshots}) != 1:
        reasons.append("pstate conditions differ/drift")
    result = {"command": "compare", "compatible": not reasons, "reasons": reasons,
              "synthetic": before["synthetic"] or after["synthetic"],
              "limitations": "A matched GEMM timing ratio is not proof of unlock or end-to-end workload improvement. Graphics/external load and between-snapshot power drift remain unobserved.",
              "next_action": "Recapture with matching identity, configuration, environment and stable power/clock/temperature conditions."}
    if reasons:
        return result
    a, b = before["timing"]["samples_ms"], after["timing"]["samples_ms"]
    result["before_ms"] = {"median": statistics.median(a), "min": min(a), "max": max(a)}
    result["after_ms"] = {"median": statistics.median(b), "min": min(b), "max": max(b)}
    result["timing_ratio"] = statistics.median(a) / statistics.median(b)
    result["verdict"] = "inconclusive_overlap" if max(min(a), min(b)) <= min(max(a), max(b)) else "candidate_faster" if result["timing_ratio"] > 1 else "candidate_slower"
    result["next_action"] = "Repeat controlled captures across boots and validate your real workload before attributing a timing change to unlock."
    if result["synthetic"]:
        result["verdict"] = "synthetic_fixture_only"
        result["next_action"] = "Fixture demonstration only. These values are not hardware measurements."
    return result
