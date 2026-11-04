# SPDX-License-Identifier: GPL-2.0-only
"""Reduce current-boot kernel evidence without probing GPU registers."""

import json
import re

from .inventory import inventory
from .system import BDF

SUCCESS = {"unlocked", "still unlocked after resume", "unlocked again after resume"}
FAILURE = re.compile(r"(?:unlock(?: after resume)?|firmware load) failed \(-?\d+\)$")


def targets(value):
    if value == "all":
        return "all", []
    entries = value.split(",") if value else []
    if any(not BDF.fullmatch(item) for item in entries):
        return [], ["Invalid targets configuration observed; the engine can ignore unmatched entries."]
    return [item.lower() for item in entries], []


def status(system, journal_file=None):
    cards, issues = inventory(system)
    boot = system.read("/proc/sys/kernel/random/boot_id").value
    boot = boot.replace("-", "").lower() if boot else None
    param = system.read("/sys/module/gpu_unlock/parameters/targets")
    cmdline = system.read("/proc/cmdline")
    configured = param.value
    if configured is None:
        values = re.findall(r"(?:^|\s)gpu_unlock\.targets=([^\s]*)", cmdline.value or "")
        configured = values[-1] if len(values) == 1 else ""
        if len(values) > 1:
            issues.append("Repeated targets on cmdline; effective configuration unknown.")
    selected, errors = targets(configured or "")
    issues.extend(errors)
    by_bdf = {}
    for card in cards:
        card["configured"] = bool(card["support"] and (selected == "all" or card["bdf"] in selected))
        card["state"] = "configured" if card["configured"] else "supported" if card["support"] else "unsupported"
        card["current_hardware_state"] = "unknown"
        card["evidence"] = []
        by_bdf[card["bdf"]] = card
    if journal_file:
        from .system import System
        log = System(journal_file.parent).read(journal_file.name)
        provenance = "supplied_journal_untrusted"
    else:
        log = system.run(["journalctl", "-k", "-b", "0", "-o", "json", "--no-pager", "-n", "20000"])
        provenance = "current_kernel_journal"
    ignored, records = 0, []
    for line in (log.value or "").splitlines():
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                ignored += 1
                continue
            timestamp = row["__MONOTONIC_TIMESTAMP"]
            if (not boot or row.get("_BOOT_ID") != boot or row.get("_TRANSPORT") != "kernel"
                    or not isinstance(row.get("MESSAGE"), str) or
                    not isinstance(timestamp, str) or not timestamp.isdigit()):
                ignored += 1
                continue
            records.append((int(timestamp), row["MESSAGE"]))
        except (ValueError, KeyError, TypeError):
            ignored += 1
    for timestamp, message in sorted(records, key=lambda row: row[0]):
        if re.search(r"PM: (?:suspend entry|hibernation)", message):
            for card in cards:
                if card["state"] in ("unlocked", "attempted"):
                    card["state"] = "unknown"
                    card["evidence"] = [{"monotonic_us": timestamp, "event": "power_transition_invalidates_prior_report"}]
        prefix, marker, event = message.partition("gpu_unlock: ")
        addresses = re.findall(r"(?<![\w:])(" + BDF.pattern + r")(?=:\s|\s|$)", prefix, re.I)
        if not marker or len(addresses) != 1 or addresses[0].lower() not in by_bdf:
            continue
        card = by_bdf[addresses[0].lower()]
        if not card["support"]:
            continue
        if event in SUCCESS:
            card["state"] = "unlocked"
        elif FAILURE.fullmatch(event):
            card["state"] = "failed"
        elif event == "not bound to nvidia, left as is after resume":
            card["state"] = "unknown"
        elif event.startswith("stage="):
            card["state"] = "attempted"
        else:
            continue
        # Keep only recognized, sanitized events, never arbitrary private kernel logs.
        safe_event = event.split()[0] if event.startswith("stage=") else event
        card["evidence"] = [{"monotonic_us": timestamp, "event": safe_event}]
    for card in cards:
        if card["runtime_power"] == "suspended" and card["state"] == "unlocked":
            card["state"] = "unknown"
            card["evidence"].append({"event": "runtime_suspended_invalidates_prior_report"})
        card["next_action"] = {
            "unlocked": "Engine reported success in this boot. Validate your workload; current selectors are not re-read.",
            "failed": "Inspect local current-boot kernel logs and the recovery plan; do not reload against a bound driver.",
            "attempted": "No terminal engine result observed. Inspect current-boot logs; success is unknown.",
            "configured": "Targets configured, no terminal result observed. Review boot ordering and journal access.",
            "supported": "Review an explicit-BDF setup plan before any installation.",
            "unsupported": "No exact engine recipe. Do not target this card.",
            "unknown": "Prior report is no longer sufficient. Inspect resume/power events and recovery plan."
        }[card["state"]]
    return {"schema_version": 1, "command": "status", "read_only": True, "cards": cards,
            "inventory_issues": issues, "journal": {"source": provenance, "error": log.error,
                "ignored_records": ignored, "accepted_records": len(records), "limit": 20000, "boot_id_available": bool(boot)},
            "evidence_scope": "Historical engine reports from this boot, not continuous hardware attestation.",
            "next_action": "Review per-card evidence. Missing/inaccessible logs leave success unknown."
            if cards else "No NVIDIA display/3D GPU observed; no unlock can be verified here."}
