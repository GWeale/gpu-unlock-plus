# SPDX-License-Identifier: GPL-2.0-only
"""Exercise upstream staging contracts under DESTDIR, with no installation."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from gpu_unlock_plus.system import SOURCE_ROOT


class PackagingTests(unittest.TestCase):
    def test_default_make_still_uses_upstream_noop_target(self):
        result = subprocess.run(["make", "-n"], cwd=SOURCE_ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("unittest", result.stdout)
        self.assertNotIn("sudo", result.stdout)

    def test_upstream_module_boot_hooks_and_licenses_stage_under_fake_root(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(["make", "install-dkms", "install-mkinitcpio", "install-initramfs-tools",
                                     "install-dracut", "install-licenses", "DESTDIR=" + temp],
                                    cwd=SOURCE_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            root = Path(temp)
            self.assertEqual((root / "usr/src/gpu-unlock-2.0.0/main.c").read_bytes(),
                             (SOURCE_ROOT / "kernel/gpu_unlock/main.c").read_bytes())
            for file in ("etc/mkinitcpio.conf.d/zz-gpu-unlock.conf",
                         "usr/share/initramfs-tools/scripts/init-top/gpu-unlock",
                         "usr/lib/dracut/dracut.conf.d/gpu-unlock.conf",
                         "usr/share/licenses/gpu-unlock/GPL-2.0.txt"):
                self.assertTrue((root / file).is_file(), file)
