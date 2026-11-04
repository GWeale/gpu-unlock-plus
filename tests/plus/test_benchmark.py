# SPDX-License-Identifier: GPL-2.0-only
import copy
from dataclasses import replace
import json
import math
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gpu_unlock_plus.benchmark import (BenchmarkConfig, FLAGS, capture, check_sample, compare,
                                       no_other_compute, precision_contract, read_result, smi, write_result)
from gpu_unlock_plus.system import Observation, SOURCE_ROOT, System

FIXTURE = SOURCE_ROOT / "tests/fixtures/baseline.json"


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.baseline = read_result(FIXTURE)
        self.candidate = copy.deepcopy(self.baseline)
        self.candidate["timing"]["samples_ms"] = [1.0, 1.1, 0.9, 1.0, 1.05]

    def test_synthetic_cli_compare_runs_without_torch(self):
        result = subprocess.run([sys.executable, "-m", "gpu_unlock_plus", "compare", str(FIXTURE), str(FIXTURE), "--json"],
                                cwd=SOURCE_ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["verdict"], "synthetic_fixture_only")
        self.assertEqual(report["timing_ratio"], 1)

    def test_matching_comparison_uses_medians_and_ranges(self):
        result = compare(self.baseline, self.candidate)
        self.assertTrue(result["compatible"])
        self.assertEqual(result["timing_ratio"], 2)
        self.assertEqual(result["after_ms"], {"median": 1, "min": 0.9, "max": 1.1})
        self.assertEqual(result["verdict"], "synthetic_fixture_only")

    def test_comparison_refuses_each_identity_config_and_environment_difference(self):
        for field, nested, value in (("gpu", "uuid", "GPU-11111111-1111-1111-1111-111111111111"),
                                     ("gpu", "bdf", "0000:02:00.0"), ("config", "m", 32),
                                     ("config", "seed", 0), ("environment", "driver", "different"),
                                     ("environment", "cuda_env_sha256", "different")):
            with self.subTest(field=field, nested=nested):
                candidate = copy.deepcopy(self.candidate)
                candidate[field][nested] = value
                result = compare(self.baseline, candidate)
                self.assertFalse(result["compatible"])
                self.assertNotIn("timing_ratio", result)

    def test_conditions_and_within_run_drift_refuse_ratio(self):
        for field, value in (("temperature_c", 70), ("power_limit_w", 320), ("sm_clock_mhz", 2000),
                             ("memory_clock_mhz", 10000), ("pstate", "P0")):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.candidate)
                candidate["conditions"]["finish"][field] = value
                result = compare(self.baseline, candidate)
                self.assertFalse(result["compatible"])
                self.assertNotIn("timing_ratio", result)

    def test_bad_correctness_and_unverified_precision_rejected(self):
        for field, value in (("passed", False), ("max_scaled_error", 1.1), ("max_scaled_error", float("nan")),
                             ("full_output_finite", False), ("reference", "self"), ("atol", 100), ("checked_outputs", 0)):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.candidate)
                candidate["correctness"][field] = value
                with self.assertRaises(ValueError):
                    compare(self.baseline, candidate)
        self.candidate["math"]["flags"]["allow_fp16_accumulation"] = True
        with self.assertRaisesRegex(ValueError, "unverified"):
            compare(self.baseline, self.candidate)

    def test_malformed_schema_and_nonfinite_timings_rejected(self):
        for value in (None, [], {}, {"schema": "v2", "synthetic": False}):
            with self.assertRaises(ValueError):
                compare(value, self.candidate)
        for value in (0, -1, 1e308, 1e-308, float("inf"), float("nan"), True, "2"):
            candidate = copy.deepcopy(self.candidate)
            candidate["timing"]["samples_ms"][0] = value
            with self.assertRaises(ValueError):
                compare(self.baseline, candidate)
        candidate = copy.deepcopy(self.candidate)
        candidate.pop("tool_version")
        with self.assertRaises(ValueError):
            compare(self.baseline, candidate)

    def test_shape_and_work_memory_budgets_validate_before_gpu_import(self):
        config = BenchmarkConfig()
        config.validate()
        for kwargs in ({"m": -1}, {"m": 4097}, {"repeats": 50000}, {"warmup": 0},
                       {"m": 4096, "n": 4096, "k": 4096, "repeats": 50},
                       {"memory_mib": 64}, {"seed": -1}, {"m": True}, {"repeats": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(config, **kwargs).validate()

    def test_correctness_checks_quantized_input_reference_and_nonfinite(self):
        self.assertEqual(check_sample([1.0] * 256, [1.0] * 256), 0)
        for value in (1.1, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "correctness failed"):
                check_sample([1.0] * 255 + [value], [1.0] * 256)
        with self.assertRaises(ValueError):
            check_sample([1.0], [1.0])

    def test_atomic_capture_output_preserves_baseline_and_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "private/result.json"
            write_result(path, self.baseline)
            before = path.read_bytes()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            with self.assertRaisesRegex(ValueError, "exists"):
                write_result(path, self.candidate)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_capture_refuses_tracked_output_and_cpu_only(self):
        with self.assertRaisesRegex(ValueError, "ignored"):
            capture("0000:01:00.0", BenchmarkConfig(), SOURCE_ROOT / "capture.json")
        fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            with self.assertRaisesRegex(ValueError, "CUDA-enabled"):
                capture("0000:01:00.0", BenchmarkConfig(), SOURCE_ROOT / ".local/test-no-gpu.json")
        self.assertFalse((SOURCE_ROOT / ".local/test-no-gpu.json").exists())

    def test_missing_or_unsupported_precision_api_fails_closed_and_restores_flags(self):
        matmul = SimpleNamespace(**{flag: True for flag in FLAGS})
        library = ["default"]
        def preferred(value=None):
            if value is not None:
                library[0] = value
            return library[0]
        torch = SimpleNamespace(backends=SimpleNamespace(cuda=SimpleNamespace(matmul=matmul, preferred_blas_library=preferred)))
        with precision_contract(torch):
            self.assertTrue(all(getattr(matmul, flag) is False for flag in FLAGS))
            self.assertEqual(library[0], "cublas")
        self.assertTrue(all(getattr(matmul, flag) is True for flag in FLAGS))
        self.assertEqual(library[0], "default")
        delattr(matmul, "allow_fp16_accumulation")
        with self.assertRaisesRegex(ValueError, "unverified"), precision_contract(torch):
            self.fail("Cannot enter benchmark with missing precision API")
        self.assertTrue(matmul.allow_fp16_reduced_precision_reduction)
        self.assertTrue(matmul.allow_bf16_reduced_precision_reduction)

    def test_blas_library_readback_must_be_exact(self):
        matmul = SimpleNamespace(**{flag: True for flag in FLAGS})
        torch = SimpleNamespace(backends=SimpleNamespace(cuda=SimpleNamespace(matmul=matmul,
            preferred_blas_library=lambda *args: "_BlasBackend.Cublaslt")))
        with self.assertRaisesRegex(ValueError, "backend preference"), precision_contract(torch):
            self.fail("cuBLASLt is not the recorded cuBLAS contract")

    def test_nvidia_smi_identity_and_power_evidence_fail_closed(self):
        row = "00000000:01:00.0, GPU-00000000-0000-0000-0000-000000000000, Fixture, 1, 300, 60, 1700, 9500, P2"
        with patch.object(System, "run", return_value=Observation(row)):
            identity, conditions = smi(System(), "0000:01:00.0")
            self.assertEqual(conditions["power_limit_w"], 300)
        for value in (row.replace("300", "N/A"), row.replace("01:00.0", "02:00.0"), row + "\n" + row):
            with patch.object(System, "run", return_value=Observation(value)), self.assertRaises(ValueError):
                smi(System(), "0000:01:00.0")
        with patch.object(System, "run", return_value=Observation(None, "command_missing")), self.assertRaises(ValueError):
            no_other_compute(System(), "0000:01:00.0")
        with patch.object(System, "run", return_value=Observation("99999999")), self.assertRaisesRegex(ValueError, "Other compute"):
            no_other_compute(System(), "0000:01:00.0")

    def test_large_or_invalid_json_is_reported_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for value in ("not json", "x" * (4 * 1024 * 1024 + 1)):
                path.write_text(value)
                result = subprocess.run([sys.executable, "-m", "gpu_unlock_plus", "compare", str(path), str(FIXTURE), "--json"],
                                        cwd=SOURCE_ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error", json.loads(result.stdout))
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
