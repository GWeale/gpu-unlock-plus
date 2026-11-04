# Pilot the modified engine on the RTX 3080

**Prepared, not applied.** The parent owns the decision and any hardware work.
Do not execute this procedure as part of the implementation handoff.
The first trial targets only `0000:01:00.0`, uses direct selectors, and disables
resume re-unlock. It requires an attended cold boot and a recovery console.

The intended Desktop card is the EVGA RTX 3080 12 GB, GA102, `10de:220a`,
subsystem `3842:4865`. The parent observed NVIDIA `595.99.02`, kernel
`7.0.0-42-generic`, and a 350 W default limit. Recheck these observations when
the pilot is authorized. Keep power limits, clocks, driver, display workload,
and benchmark dependencies unchanged.

The parent's private cuBLAS stock baseline is separate from this source tree.
It covers FP16 and BF16 inputs with FP32 compute/output, TF32, and a pedantic
FP32 control at shapes 2048 and 4096. The improved-module trial is pending.
Repeat that same instrument and settings after the trial. Do not substitute
the optional PyTorch CLI capture and compare unlike measurement contracts.

Before installation, capture the stock phase with the final reusable private
instrument on Desktop:

```sh
python3 "$HOME/.cache/gpu-unlock-plus/stock_baseline.py" --phase stock
```

## Build reviewed packages on Hatter

Use the existing owner checkout. Do not create another writable project checkout
on Desktop. Record the final reviewed Git revision from the handoff. The inherited
package version is `2.0.0`, so version alone does not identify these changes.

```sh
cd /home/hatter/Developer/gpu-unlock-plus
git status --short
git rev-parse HEAD
make check
make -C kernel/gpu_unlock KCFLAGS=-Werror -j2
dpkg-checkbuilddeps
make deb
sha256sum build/deb/gpu-unlock-dkms_2.0.0_all.deb \
  build/deb/gpu-unlock-firmware_2.0.0_all.deb
dpkg-deb --info build/deb/gpu-unlock-dkms_2.0.0_all.deb
dpkg-deb --info build/deb/gpu-unlock-firmware_2.0.0_all.deb
```

Require a clean tree and the reviewed revision before `make deb`. Stop if build
dependencies are missing; dependency installation is a separate system change.
`make deb` downloads the pinned NVIDIA inputs into the user cache and generates
firmware locally. It does not run NVIDIA's installer or replace the installed
driver. Read `firmware/NOTICE.md` first. Firmware/package generation and real
package installation were **not run** in the implementation task.

The parent can transfer those two exact packages and their hash receipt to a
private Desktop cache through the authorized fleet route. The destination used
below is `~/.cache/gpu-unlock-plus/pilot/`. Verify hashes there before installation.

## Qualify Desktop and preserve recovery

These commands are for Desktop after separate approval, not Hatter:

```sh
uname -r
cat /sys/bus/pci/devices/0000:01:00.0/vendor
cat /sys/bus/pci/devices/0000:01:00.0/device
cat /sys/bus/pci/devices/0000:01:00.0/subsystem_vendor
cat /sys/bus/pci/devices/0000:01:00.0/subsystem_device
lspci -Dnnk -s 0000:01:00.0
nvidia-smi -i 00000000:01:00.0
mokutil --sb-state
bootctl status --no-pager
cat /proc/cmdline
command -v update-initramfs
```

Require the exact identity above, installed headers for `7.0.0-42-generic`, and
an identified active boot entry. The following boot steps assume GRUB with
initramfs-tools. If Desktop uses a UKI, enforced signatures, or a different
loader, stop and prepare its exact boot/signing procedure first. Do not disable
Secure Boot as an improvised workaround.

Keep a working console or SSH route independent of the GPU's display. The FLR
can blank that display until NVIDIA takes over. Preserve the original initrd
before package hooks regenerate it:

```sh
sudo cp --no-clobber /boot/initrd.img-7.0.0-42-generic \
  /boot/initrd.img-7.0.0-42-generic.gpu-unlock-before
```

Record the original GRUB `linux` and `initrd` lines privately. Confirm that you
can select the same kernel and the saved initrd from GRUB's edit screen.
Do not proceed if recovery access or the original image is uncertain.

## Install without unlocking the active card

```sh
cd "$HOME/.cache/gpu-unlock-plus/pilot"
sha256sum gpu-unlock-dkms_2.0.0_all.deb gpu-unlock-firmware_2.0.0_all.deb
sudo apt-get install ./gpu-unlock-firmware_2.0.0_all.deb \
  ./gpu-unlock-dkms_2.0.0_all.deb
dkms status
modinfo -k 7.0.0-42-generic gpu_unlock
lsinitramfs /boot/initrd.img-7.0.0-42-generic | \
  rg 'gpu_unlock|gpu-unlock/610.43.03|scripts/init-top/gpu-unlock'
```

Match the hashes to Hatter's receipt. Check DKMS built the intended module and
that the initrd contains the module, its firmware, and the early init-top hook.
The source for that hook loads the module before udev/NVIDIA coldplug.
The module stays inert without `gpu_unlock.targets=`. Do not unload the active
NVIDIA driver or manually load the unlock module to run it on this active card.

## Make one attended cold-boot trial

Save work and shut down through the parent's approved hardware procedure.
An ordinary warm restart can preserve the previous GPU state. Require a true
power-off interval before the trial.

At GRUB, select the intended `7.0.0-42-generic` entry and press `e`. On its
`linux` line, remove any previous `gpu_unlock.*` options and append exactly:

```text
gpu_unlock.targets=0000:01:00.0 gpu_unlock.direct=1 gpu_unlock.resume=0
```

Keep all unrelated arguments intact. Boot once with Ctrl-X or F10. This edit is
not saved to `/etc/default/grub`. Do not use `targets=all`. Do not enable suspend
re-unlock during this first trial.

## Capture evidence before a benchmark

Create a private directory outside the repository, then collect:

```sh
umask 077
pilot_evidence="$HOME/.local/state/gpu-unlock-plus/3080-pilot/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$pilot_evidence"
cat /proc/cmdline > "$pilot_evidence/cmdline.txt"
journalctl -k -b --no-pager > "$pilot_evidence/kernel.txt"
lspci -Dnnk -s 0000:01:00.0 > "$pilot_evidence/pci.txt"
nvidia-smi -i 00000000:01:00.0 -q > "$pilot_evidence/nvidia-smi.txt"
cat /sys/module/gpu_unlock/parameters/targets
cat /sys/module/gpu_unlock/parameters/direct
cat /sys/module/gpu_unlock/parameters/resume
```

Require all of the following for the explicit BDF:

- `stage=engine mode=direct`, followed by exactly one successful Booter
  invocation. With normal loglevel, the single launch is enforced by the C
  policy; dynamic-debug invocation detail is optional diagnostic evidence.
- `stage=plm mode=direct protections_verified=1`. This line is emitted only
  after checked mask equality and selector readbacks. Entry values are in
  `stage=gfw`; optional dynamic-debug output records each comparison.
- `stage=flr` with SS0 `0x88888888`, SS1 `0x8`, WPR2 HI `0`, no pending PCIe
  transaction, and bus mastering disabled during handoff.
- `stage=handoff ret=0 state=4 retained=0 ... cleanup=0` and `gpu_unlock: unlocked`.
- NVIDIA binds the same card normally. No new Xid, firmware, PCIe, or NVRM
  error accompanies the trial. A success line alone does not establish
  correctness, retained state, or performance.

`already unlocked; left unchanged` is a read-only kept-power observation,
not a successful new trial. A missing direct-mode verification line, failed
handoff, or retained DMA allocation fails the pilot. Capture the logs and
recover. Do not reload, switch to PLM mode, or launch Booter again in that boot.

Only after the engine evidence passes, run the pilot phase of that same
instrument:

```sh
python3 "$HOME/.cache/gpu-unlock-plus/stock_baseline.py" --phase pilot
```

Use the same script digest in both records. The phase guard checks module
presence only; it does not replace the engine-evidence requirements above.
Preserve its math controls, shapes, input construction, windows, repeat count,
correctness checks, and observed desktop graphics load. Compare the stock and
pilot correctness, timing dispersion, power, clocks, and temperature. Label
any result as this local desktop experiment. It cannot prove application
speedup or universal board compatibility.

## Recover or remove the experiment

For the next boot, omit all three `gpu_unlock.*` arguments. The GRUB one-off
edit normally disappears on its own. If the trial failed after a launch or
retained DMA buffers, use a full power-off before another attempt.

If the system fails to reach a usable session, select the known-good kernel
in GRUB and remove `gpu_unlock.targets=` from its `linux` line. If necessary,
change the `initrd` line to the saved
`/boot/initrd.img-7.0.0-42-generic.gpu-unlock-before` image. Boot without the
unlock target, capture private logs, and stop the experiment.

Once back in a normal session, removal is:

```sh
sudo apt-get remove gpu-unlock-dkms gpu-unlock-firmware
sudo update-initramfs -u -k 7.0.0-42-generic
dkms status
```

The saved initrd remains available until the parent decides to delete it.
A legacy-mode comparison, persistent boot configuration, suspend/resume test,
or another board is a later decision. No part of this document authorizes
those actions or records them as performed.
