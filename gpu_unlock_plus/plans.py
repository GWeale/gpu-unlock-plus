# SPDX-License-Identifier: GPL-2.0-only
"""Inspectable setup and recovery instructions. This module never applies them."""

from .inventory import doctor
from .system import bdf


def plan(system, requested, loader=None):
    report = doctor(system)
    requested = list(dict.fromkeys(bdf(item) for item in requested))
    cards = {card["bdf"]: card for card in report["cards"]}
    for address in requested:
        if address not in cards or not cards[address]["support"]:
            raise ValueError(f"{address}: no observed GPU with an exact supported engine recipe.")
    boot = report["host"]["boot"]
    argument = "gpu_unlock.targets=" + ",".join(requested)
    distro = system.read("/etc/os-release").value or ""
    installer = "make install-deb" if 'ID=ubuntu' in distro or 'ID=debian' in distro else None
    if not installer:
        installer = "make install (reviews /etc/os-release to choose the upstream installer)"
    boot_steps = {
        "grub": ["Back up /etc/default/grub. Append the argument inside GRUB_CMDLINE_LINUX_DEFAULT, preserving other options.",
                 "Debian/Ubuntu: sudo update-grub", "Arch: sudo grub-mkconfig -o /boot/grub/grub.cfg",
                 "Fedora/RHEL with grubby: sudo grubby --update-kernel=ALL --args=" + argument],
        "systemd-boot": ["Run bootctl status --no-pager to identify the active text entry and ESP.",
                         "Back up that entry. Append the argument to its options line, preserving other options.",
                         "For generated BLS entries or UKIs, use their generator instead of editing a generated entry."],
        "uki": ["Back up /etc/kernel/cmdline. Append the argument, preserving other options.",
                "Confirm the installed UKI generator and signing policy. Regenerate with that generator's documented command.",
                "There is no universal UKI regeneration command; do not guess from installed tools."],
    }
    recovery = ["For one boot, delete every gpu_unlock.targets= argument in the bootloader editor before booting.",
                "For a UKI with an embedded signed command line, external edits may be ignored. Select a known-good image without the target argument.",
                "Permanent opt-out: remove gpu_unlock.targets= from its original source and regenerate the same entries/images.",
                "Optional resume opt-out: append gpu_unlock.resume=0 through the same boot mechanism.",
                "Package removal on Debian/Ubuntu: sudo apt-get purge gpu-unlock-dkms gpu-unlock-firmware",
                "Package removal on Arch: sudo pacman -Rns gpu-unlock-dkms gpu-unlock-firmware",
                "Package removal on Fedora/RHEL: sudo dnf remove gpu-unlock-dkms gpu-unlock-firmware",
                "Verify package hooks remove the initramfs drop-ins and rebuild all affected images. Retain a known-good boot entry.",
                "If the engine reports firmware/DMA buffers retained, power off before retrying; do not force-remove the module."]
    return {"schema_version": 1, "command": "plan", "applied": False, "targets": requested,
            "cards": [cards[address] for address in requested], "host": report["host"],
            "limitations": report["limitations"],
            "boot": boot, "selected_loader": loader or "unconfirmed", "kernel_argument": argument,
            "review_steps": ["Review doctor, exact PCI IDs and experimental status for each selected card.",
                             "Review firmware/NOTICE.md and UPSTREAM.md before using upstream packaging.",
                             "The following installer may download inputs, install build dependencies, use sudo and rebuild boot images: " + installer,
                             "No installer has been run by this tool. Confirm headers, signing, initramfs ordering and recovery access first."] +
                            boot_steps.get(loader, ["Confirm the active boot mechanism. Rerun plan with --loader grub, systemd-boot or uki for its edit instructions."]),
            "conceptual_diff": ["+ " + argument + "  # append to the confirmed kernel command-line source"],
            "recovery": recovery,
            "next_action": "Review the commands and recovery route. Installation and boot edits are separate manual actions."}
