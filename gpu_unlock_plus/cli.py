# SPDX-License-Identifier: GPL-2.0-only
import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .benchmark import BenchmarkConfig, capture, compare, read_result
from .inventory import doctor, recipes
from .plans import plan
from .status import status
from .system import System, bdf


def human(report):
    print(f"gpu-unlock-plus {__version__} | {report['command']}")
    if report.get("synthetic"):
        print("SYNTHETIC FIXTURE ONLY. No hardware measurement.")
    for card in report.get("cards", []):
        support = card["support"]
        description = f"{support['chip']} {support['generation']} ({support['maturity']})" if support else "unsupported exact ID"
        print(f"{card['bdf']} 10de:{card['device_id'] or 'unknown'} | {description}")
        print(f"  driver={card['driver']} power={card['runtime_power']} state={card.get('state', 'not_checked')}")
        if "state" in card:
            print("  Current hardware selectors: unknown. State above describes observed engine/configuration evidence.")
        print("  Next: " + card["next_action"])
    for issue in report.get("inventory_issues", []):
        print("Observation: " + issue)
    if "host" in report:
        host = report["host"]
        print(f"Kernel: {host['kernel'] or 'unknown'} | headers={host['headers_present']}")
        print("Unavailable tools (requirements depend on packaging route): " + (", ".join(key for key, value in host["tools"].items() if value is False) or "none observed (fixture tools unknown)"))
        print(f"Firmware files missing: {len(host['firmware_missing'])} (presence only)")
        print("Secure Boot: " + host["boot"]["secure_boot"] + " | active loader: " + host["boot"]["active_loader"])
        print("Kernel lockdown: " + host["kernel_lockdown"])
        for limitation in report["limitations"]:
            print("Limit: " + limitation)
    if "journal" in report:
        print("Journal: " + (report["journal"]["error"] or report["journal"]["source"]))
        print(report["evidence_scope"])
    if report["command"] == "plan":
        print("PLAN ONLY. No commands executed or files changed.")
        print("Boot evidence: " + json.dumps(report["boot"]))
        print("Argument: " + report["kernel_argument"])
        for step in report["review_steps"]:
            print("  " + step)
        print("Conceptual diff (confirm the actual source first):")
        for line in report["conceptual_diff"]:
            print("  " + line)
        print("Recovery:")
        for step in report["recovery"]:
            print("  " + step)
    if report["command"] == "compare":
        if not report["compatible"]:
            print("Comparison refused: " + "; ".join(report["reasons"]))
        else:
            print(f"{report['verdict']}: timing ratio={report['timing_ratio']:.3f}x")
            print("Milliseconds (median/min/max): " + json.dumps({key: report[key] for key in ("before_ms", "after_ms")}))
        print(report["limitations"])
    if report["command"] == "bench":
        print(f"Correctness passed. Saved {report['samples']} samples to {report['output']}.")
    if report["command"] == "support":
        for row in report["recipes"]:
            print(f"10de:{row['device_id']} {row['chip']} {row['generation']} {row['maturity']}")
    print("Next: " + report["next_action"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only preflight, observed status, setup plans and controlled GEMM capture for the upstream gpu_unlock engine.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "status", "plan", "support", "bench", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true", help="Machine-readable output; diagnostics can contain private PCI identity.")
        if name in ("doctor", "status", "plan"):
            command.add_argument("--root", type=Path, default=Path("/"), help="Read-only fixture filesystem root; external commands are disabled for non-/ roots.")
        if name == "status":
            command.add_argument("--journal", type=Path, help="Local journalctl -k -b -o json export; boot/BDF checks still apply. Supplied logs are not authenticated.")
        if name == "plan":
            command.add_argument("--target", action="append", required=True, help="Explicit full PCI BDF; repeat for multiple cards. 'all' is refused.")
            command.add_argument("--loader", choices=("grub", "systemd-boot", "uki"))
        if name == "bench":
            command.add_argument("--target", required=True, help="Full PCI BDF. Resolved to CUDA by physical UUID, never enumeration order.")
            command.add_argument("--shape", nargs=3, type=int, default=(2048, 2048, 2048), metavar=("M", "N", "K"))
            command.add_argument("--dtype", choices=("float16", "bfloat16"), default="float16")
            command.add_argument("--warmup", type=int, default=5)
            command.add_argument("--repeats", type=int, default=10)
            command.add_argument("--seed", type=int, default=1729)
            command.add_argument("--memory-mib", type=int, default=256, help="Tensor estimate + 64 MiB reserve; not a hard CUDA allocator limit.")
            command.add_argument("--output", type=Path, required=True, help="New private .json file under ignored .local/ (never overwrite a baseline).")
        if name == "compare":
            command.add_argument("before", type=Path)
            command.add_argument("after", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = doctor(System(args.root))
        elif args.command == "status":
            report = status(System(args.root), args.journal)
        elif args.command == "plan":
            report = plan(System(args.root), args.target, args.loader)
        elif args.command == "support":
            from dataclasses import asdict
            report = {"command": "support", "recipes": [asdict(row) for row in recipes().values()],
                      "next_action": "Match exact PCI device IDs with doctor. Recipe inclusion is not hardware validation."}
        elif args.command == "bench":
            report = capture(bdf(args.target), BenchmarkConfig(*args.shape, args.dtype, args.warmup, args.repeats, args.seed, args.memory_mib), args.output)
        else:
            report = compare(read_result(args.before), read_result(args.after))
        if args.json:
            print(json.dumps(report, indent=2, allow_nan=False))
        else:
            human(report)
        return 1 if report.get("compatible") is False else 0
    except (ValueError, OSError, RuntimeError) as error:
        message = str(error) if isinstance(error, ValueError) else "Operation unavailable or file access failed; inspect local prerequisites."
        if args.json:
            print(json.dumps({"command": args.command, "error": message, "next_action": "Review inputs/prerequisites and retry. No host configuration was changed."}))
        else:
            print("gpu-unlock-plus: " + message, file=sys.stderr)
        return 2
