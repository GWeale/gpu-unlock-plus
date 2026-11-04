# SPDX-License-Identifier: GPL-2.0-only
"""Behavior checks use synthetic PCI devices and journal exports, never GPU writes."""

from contextlib import redirect_stdout
import io
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gpu_unlock_plus.cli import main
from gpu_unlock_plus.inventory import recipes
from gpu_unlock_plus.status import status
from gpu_unlock_plus.system import Observation, SOURCE_ROOT, System

BOOT = "0" * 32


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put("/proc/sys/kernel/random/boot_id", BOOT)
        self.put("/proc/sys/kernel/osrelease", "fixture-kernel")
        (self.root / "sys/bus/pci/devices").mkdir(parents=True)

    def put(self, path, data):
        target = self.root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
        return target

    def card(self, address="0000:01:00.0", device="0x2206", vendor="0x10de", power="active", driver=None):
        base = "/sys/bus/pci/devices/" + address
        for field, value in (("vendor", vendor), ("device", device), ("class", "0x030000"),
                             ("power/runtime_status", power), ("power/control", "auto")):
            self.put(base + "/" + field, value)
        if driver:
            target = self.root / "sys/bus/pci/drivers" / driver
            target.mkdir(parents=True, exist_ok=True)
            (self.root / base.lstrip("/") / "driver").symlink_to(target)

    def invoke(self, *args):
        result = subprocess.run([sys.executable, "-m", "gpu_unlock_plus", *args], cwd=SOURCE_ROOT,
                                capture_output=True, text=True, timeout=20)
        return result.returncode, result.stdout, result.stderr

    def report(self, command, *args):
        code, out, err = self.invoke(command, "--root", str(self.root), "--json", *args)
        self.assertEqual(code, 0, err + out)
        return json.loads(out)

    def journal(self, *events):
        rows = []
        for index, event in enumerate(events):
            row = {"_BOOT_ID": BOOT, "_TRANSPORT": "kernel", "__MONOTONIC_TIMESTAMP": str(index + 1),
                   "MESSAGE": "pci 0000:01:00.0: gpu_unlock: " + event}
            rows.append(row)
        return rows

    def log(self, rows):
        return self.put("journal.jsonl", "\n".join(json.dumps(row) for row in rows))

    def test_help_and_module_entrypoints(self):
        for command in ([], ["--help"], ["bench", "--help"], ["plan", "--help"]):
            code, out, err = self.invoke(*command)
            self.assertEqual(code, 2 if not command else 0)
            self.assertIn("usage:", out + err)
        result = subprocess.run([str(SOURCE_ROOT / "gpu-unlock-plus"), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("0.1.0", result.stdout)

    def test_doctor_without_nvidia_or_tools(self):
        report = self.report("doctor")
        self.assertEqual(report["cards"], [])
        self.assertIn("No NVIDIA", report["next_action"])
        with patch.dict(os.environ, {"PATH": ""}):
            self.assertEqual(System().run(["missing_gpu_unlock_plus_command"]).error, "command_missing")

    @unittest.skipUnless(Path("/proc/sys/kernel/osrelease").is_file(), "Linux procfs required")
    def test_live_proc_sys_kernel_read_does_not_use_oversized_reads(self):
        observation = System().read("/proc/sys/kernel/osrelease")
        self.assertIsNone(observation.error)
        self.assertEqual(observation.value, platform.release())

    def test_exact_ids_multi_gpu_and_non_gpu_functions(self):
        self.card(driver="nvidia")
        self.card("0000:02:00.0", "0x2684")
        self.card("0000:03:00.0", "0xdead")
        self.card("0000:04:00.0", "0x2684", vendor="0x8086")
        self.card("0000:02:00.1", "0x2684")
        self.put("/sys/bus/pci/devices/0000:02:00.1/class", "0x040300")
        cards = self.report("doctor")["cards"]
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]["support"]["generation"], "Ampere")
        self.assertEqual(cards[0]["driver"], "nvidia")
        self.assertEqual(cards[1]["support"]["maturity"], "experimental")
        self.assertIsNone(cards[2]["support"])
        self.assertIn("Do not target", cards[2]["next_action"])

    def test_recipe_source_coverage_fails_closed(self):
        table = recipes()
        self.assertIn("2206", table)
        self.assertIn("1e04", table)
        self.assertNotIn("dead", table)
        original = (SOURCE_ROOT / "kernel/gpu_unlock/recipes.c").read_text()
        with patch.object(Path, "read_text", return_value=original.replace("GA102(0x2200)", "UNKNOWN(0x2200)")):
            with self.assertRaisesRegex(ValueError, "Unrecognized"):
                recipes()

    def test_secure_boot_candidate_is_not_active_loader(self):
        self.put("/etc/default/grub", "GRUB_CMDLINE_LINUX_DEFAULT=quiet")
        variable = self.root / "sys/firmware/efi/efivars/SecureBoot-fixture"
        variable.parent.mkdir(parents=True)
        variable.write_bytes(b"\x07\x00\x00\x00\x01")
        boot = self.report("doctor")["host"]["boot"]
        self.assertEqual(boot["secure_boot"], "enabled")
        self.assertEqual(boot["active_loader"], "unknown")
        self.assertEqual(boot["candidates"][0]["mechanism"], "grub")

    def test_unreadable_inventory_stays_unknown(self):
        self.card()
        read = System.read
        def denied(system, name):
            return Observation(None, "permission_denied") if name.endswith("/vendor") else read(system, name)
        with patch.object(System, "read", denied):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["doctor", "--root", str(self.root), "--json"]), 0)
            report = json.loads(output.getvalue())
            self.assertFalse(report["cards"])
            self.assertIn("incomplete", report["inventory_issues"][0])

    def test_configuration_and_module_do_not_prove_unlock(self):
        self.card()
        self.put("/sys/module/gpu_unlock/parameters/targets", "all")
        report = self.report("status")
        self.assertEqual(report["cards"][0]["state"], "configured")
        self.assertEqual(report["cards"][0]["current_hardware_state"], "unknown")
        self.assertIsNotNone(report["journal"]["error"])

    def test_journal_partial_success_and_attempted(self):
        self.card()
        self.card("0000:02:00.0")
        self.card("0000:03:00.0")
        rows = self.journal("stage=claim device=0x2206", "unlocked")
        failure = self.journal("unlock failed (-16)")[0]
        failure["MESSAGE"] = failure["MESSAGE"].replace("01:00.0", "02:00.0")
        rows.append(failure)
        attempted = self.journal("stage=handoff ret=0 state=1")[0]
        attempted["MESSAGE"] = attempted["MESSAGE"].replace("01:00.0", "03:00.0")
        rows.append(attempted)
        report = self.report("status", "--journal", str(self.log(rows)))
        self.assertEqual([card["state"] for card in report["cards"]], ["unlocked", "failed", "attempted"])
        self.assertEqual(report["cards"][2]["evidence"][0]["event"], "stage=handoff")

    def test_stale_other_bdf_userspace_malformed_logs_ignored(self):
        self.card()
        rows = self.journal("unlocked") * 3
        rows = [dict(row) for row in rows]
        rows[0]["_BOOT_ID"] = "1" * 32
        rows[1]["MESSAGE"] = "pci 0000:09:00.0: gpu_unlock: unlocked"
        rows[2]["_TRANSPORT"] = "stdout"
        malformed_bdf = self.journal("unlocked")[0]
        malformed_bdf["MESSAGE"] = "pci 10000:01:00.0: gpu_unlock: unlocked"
        rows.extend([None, {}, {"MESSAGE": []}, malformed_bdf])
        log = self.log(rows)
        with log.open("a") as stream:
            stream.write("\nnot json")
        report = self.report("status", "--journal", str(log))
        self.assertEqual(report["cards"][0]["state"], "supported")
        self.assertGreaterEqual(report["journal"]["ignored_records"], 6)

    def test_latest_failure_and_power_loss_invalidate_success(self):
        self.card()
        rows = self.journal("unlocked", "unlock after resume failed (-5)")
        report = self.report("status", "--journal", str(self.log(rows)))
        self.assertEqual(report["cards"][0]["state"], "failed")
        rows[1]["MESSAGE"] = "PM: suspend entry (deep)"
        report = self.report("status", "--journal", str(self.log(rows)))
        self.assertEqual(report["cards"][0]["state"], "unknown")
        rows.extend(self.journal("unlocked again after resume"))
        rows[-1]["__MONOTONIC_TIMESTAMP"] = "3"
        self.assertEqual(self.report("status", "--journal", str(self.log(rows)))["cards"][0]["state"], "unlocked")
        self.put("/sys/bus/pci/devices/0000:01:00.0/power/runtime_status", "suspended")
        self.assertEqual(self.report("status", "--journal", str(self.log(rows)))["cards"][0]["state"], "unknown")

    def test_permission_denied_journal_and_missing_boot_id(self):
        self.card()
        with patch.object(System, "run", return_value=Observation(None, "permission_denied")):
            report = status(System(self.root))
            self.assertEqual(report["journal"]["error"], "permission_denied")
            self.assertEqual(report["cards"][0]["state"], "supported")
        (self.root / "proc/sys/kernel/random/boot_id").unlink()
        report = self.report("status", "--journal", str(self.log(self.journal("unlocked"))))
        self.assertEqual(report["cards"][0]["state"], "supported")

    def test_invalid_targets_never_expand_to_all(self):
        self.card()
        self.put("/sys/module/gpu_unlock/parameters/targets", "all,0000:01:00.0")
        report = self.report("status")
        self.assertFalse(report["cards"][0]["configured"])
        self.assertTrue(report["inventory_issues"])

    def test_plan_is_inspectable_and_never_mutates_fixture(self):
        self.card()
        grub = self.put("/etc/default/grub", 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
        before = grub.read_bytes()
        report = self.report("plan", "--target", "0000:01:00.0", "--target", "0000:01:00.0", "--loader", "grub")
        self.assertEqual(report["targets"], ["0000:01:00.0"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["kernel_argument"], "gpu_unlock.targets=0000:01:00.0")
        self.assertTrue(any("one boot" in step for step in report["recovery"]))
        self.assertTrue(any("sudo update-grub" in step for step in report["review_steps"]))
        self.assertEqual(grub.read_bytes(), before)
        for target in ("all", "01:00.0", "0000:01:20.0", "0000:01:00.8", "0000:ff:00.0"):
            code, out, _ = self.invoke("plan", "--root", str(self.root), "--target", target, "--json")
            self.assertEqual(code, 2)
            self.assertIn("error", json.loads(out))


if __name__ == "__main__":
    unittest.main()
