# Security policy

## Report a vulnerability privately

Use [GitHub's private vulnerability report form](https://github.com/GWeale/latchloom/security/advisories/new).
Include the affected commit, a minimal reproduction, the expected impact, and
any proposed fix. Do not open a public issue containing an exploit or a secret.
Do not attach full journals, firmware dumps, signing keys, GPU UUIDs, or unrelated
host information. Share only the evidence needed to reproduce the problem.

## Supported source

Security fixes target the current `main` branch. There are no maintained release
branches or support guarantees. Review the latest source and its validation
record before using the module.

## Hardware and privilege boundary

The engine runs in the kernel and interacts with signed GPU firmware before the
NVIDIA driver binds the selected card. A defect can affect the display, device,
or host. Synthetic checks do not validate physical firmware, DMA, power, or
suspend behavior. A matching PCI ID is not board certification.

The diagnostic CLI reads system state. Its planner prints proposed steps and
does not apply them. Installation and hardware experiments are separate manual
actions. Keep a known-good boot path and follow the recovery instructions for
the selected experiment.

NVIDIA firmware has separate redistribution terms. See
[firmware/NOTICE.md](firmware/NOTICE.md) and [licenses/](licenses/).
