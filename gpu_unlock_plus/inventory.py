# SPDX-License-Identifier: GPL-2.0-only
"""Per-card support comes from the engine's exact PCI recipe table."""

from dataclasses import asdict, dataclass
import platform
import re
import shutil

from .system import BDF, SOURCE_ROOT

GENERATIONS = {"GA": ("Ampere", "upstream-established"),
               "AD": ("Ada", "experimental"), "TU": ("Turing", "experimental")}


@dataclass(frozen=True)
class Support:
    device_id: str
    chip: str
    generation: str
    maturity: str


def recipes():
    text = (SOURCE_ROOT / "kernel/gpu_unlock/recipes.c").read_text()
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    match = re.search(r"static const struct gu_card cards\[\]\s*=\s*\{(.*?)\};", text, re.S)
    if not match:
        raise ValueError("Cannot read engine PCI recipe table; support is unknown.")
    result = {}
    remaining = match[1]
    for entry in re.finditer(r"((?:GA|AD|TU)\d{3})\(0x([0-9a-fA-F]{4})\)", match[1]):
        chip, device = entry.groups()
        generation, maturity = GENERATIONS[chip[:2]]
        key = device.lower()
        if key in result:
            raise ValueError("Duplicate engine PCI recipe; review support parser.")
        result[key] = Support(key, chip, generation, maturity)
        remaining = remaining.replace(entry[0], "", 1)
    if not result or remaining.replace(",", "").strip():
        raise ValueError("Unrecognized engine PCI recipe syntax; support is unknown.")
    return result


def inventory(system):
    table = recipes()
    cards, issues = [], []
    try:
        devices = sorted(system.path("/sys/bus/pci/devices").iterdir())
    except OSError:
        return [], ["PCI sysfs is unavailable or permission denied; inventory unknown."]
    for device in devices:
        if not BDF.fullmatch(device.name):
            continue
        base = f"/sys/bus/pci/devices/{device.name}"
        vendor, pci_class = system.read(base + "/vendor"), system.read(base + "/class")
        if vendor.error or pci_class.error:
            issues.append(f"{device.name}: vendor/class unreadable; inventory incomplete.")
            continue
        if vendor.value.lower() != "0x10de" or not pci_class.value.lower().startswith("0x03"):
            continue
        device_id = system.read(base + "/device").value
        device_id = device_id.lower().removeprefix("0x") if device_id else None
        support = table.get(device_id)
        try:
            driver = (device / "driver").resolve(strict=True).name
        except FileNotFoundError:
            driver = "unbound" if not (device / "driver").is_symlink() else "unknown"
        except OSError:
            driver = "unknown"
        cards.append({"bdf": device.name.lower(), "vendor_id": "10de", "device_id": device_id,
                      "support": asdict(support) if support else None,
                      "driver": driver,
                      "runtime_power": system.read(base + "/power/runtime_status").value or "unknown",
                      "power_control": system.read(base + "/power/control").value or "unknown"})
    return cards, issues


def boot_environment(system):
    efi = system.path("/sys/firmware/efi").is_dir()
    secure_boot = "unknown"
    try:
        variables = list(system.path("/sys/firmware/efi/efivars").glob("SecureBoot-*"))
        if len(variables) == 1:
            data = variables[0].read_bytes()
            if len(data) == 5 and data[4] in (0, 1):
                secure_boot = "enabled" if data[4] else "disabled"
    except OSError:
        pass
    candidates = []
    for name, path in (("grub", "/etc/default/grub"), ("kernel-cmdline/UKI", "/etc/kernel/cmdline"),
                       ("systemd-boot/BLS", "/boot/loader/entries"),
                       ("systemd-boot/BLS", "/efi/loader/entries")):
        if system.path(path).exists():
            candidates.append({"mechanism": name, "path": path})
    active = system.run(["bootctl", "status", "--no-pager"])
    return {"firmware": "UEFI" if efi else "legacy_or_efi_unavailable",
            "secure_boot": secure_boot, "candidates": candidates,
            "active_loader": "systemd-boot" if active.value and
            re.search(r"Product:\s+systemd-boot", active.value) else "unknown",
            "limitation": "Files show candidates only. Confirm the active entry and image generator before editing."}


def doctor(system):
    cards, issues = inventory(system)
    kernel = system.read("/proc/sys/kernel/osrelease").value
    tools = {name: bool(shutil.which(name)) if str(system.root) == "/" else None
             for name in ("make", "cc", "dkms", "git", "python3", "zstd", "tar", "xz", "openssl", "journalctl", "nvidia-smi",
                          "dpkg-buildpackage", "rpmbuild", "makepkg", "update-initramfs", "dracut", "mkinitcpio")}
    headers = bool(kernel and system.path(f"/lib/modules/{kernel}/build/Makefile").is_file())
    fw = system.path("/usr/lib/firmware/gpu-unlock/610.43.03")
    required = re.search(r"FIRMWARE_FILES\s*:=\s*(.*?)\nLICENSES", (SOURCE_ROOT / "Makefile").read_text(), re.S)
    names = required[1].replace("\\\n", " ").split() if required else []
    missing = [name for name in names if not (fw / name).is_file()]
    for card in cards:
        if not card["support"]:
            card["next_action"] = "No engine recipe for this exact PCI ID. Do not target this card."
        elif card["driver"] != "unbound":
            card["next_action"] = "Review plan for a future pre-driver boot; do not unload the active driver."
        elif card["runtime_power"] != "active":
            card["next_action"] = "Power/readiness is unknown or suspended; review platform power behavior before a future boot."
        else:
            card["next_action"] = f"Review: ./gpu-unlock-plus plan --target {card['bdf']}"
    return {"schema_version": 1, "command": "doctor", "read_only": True,
            "cards": cards, "inventory_issues": issues,
            "host": {"kernel": kernel, "architecture": platform.machine() if str(system.root) == "/" else "fixture",
                     "headers_present": headers, "tools": tools,
                     "kernel_lockdown": system.read("/sys/kernel/security/lockdown").value or "unknown",
                     "firmware_missing": missing, "firmware_presence_only": True,
                     "engine_module_loaded": system.path("/sys/module/gpu_unlock").is_dir(),
                     "boot": boot_environment(system)},
            "limitations": ["Recipe support is not proof of board compatibility or unlock.",
                            "Headers/tool/file presence is not a completed build or firmware integrity check.",
                            "Secure Boot unknown/enabled requires review of module signing and lockdown policy.",
                            "Power loss, runtime D3, suspend and hibernation can invalidate an unlock.",
                            "No BAR, PCI config, ROM or GPU register access is performed."],
            "next_action": "Review per-card actions and host prerequisites, then request an explicit-BDF setup plan."
            if cards else "No NVIDIA display/3D GPU observed. Use a supported Linux GPU host; do not install here."}
