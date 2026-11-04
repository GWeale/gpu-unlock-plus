# Contributing to Tensor Reclaim

Changes should improve the engine, its evidence, or the tools that help people
use it. Keep each pull request focused and preserve upstream attribution.

## Run the checks

Use Linux with Python 3.10 or later, a C compiler, make, Git, and `sha256sum`.
The default checks use the Python standard library and synthetic devices.
They do not need a GPU, CUDA, root, firmware downloads, or installed packages.

```sh
make check
SANITIZE=1 tests/engine/run.sh
```

To reproduce the original loader failures, use a checkout containing the upstream
base commit, then run `BASELINE=1 tests/engine/run.sh`.

With kernel headers already installed, you can also build the module without
installing or loading it:

```sh
make -C kernel/gpu_unlock KCFLAGS=-Werror -j2
```

The distribution/package matrix is a separate manual workflow. It downloads
build inputs and tests package installation inside containers.

## Prepare a pull request

`main` requires a pull request and both CPU CI checks, including for
administrators. Branches must be up to date, and review conversations must be
resolved before merge. Direct pushes, force pushes, and branch deletion are
blocked. Use a feature branch and squash or rebase when merging.

- Explain the observable problem, the change, and how you checked it.
- Add a focused regression for changed behavior. Exercise production code or
  a public CLI rather than duplicating the implementation in a test.
- Keep PCI recipe additions tied to exact IDs and linked source evidence.
- Separate synthetic tests, reported third-party results, and your own physical
  hardware observations. A successful build is not an unlock or a speedup.
- Keep raw journals, GPU UUIDs, serial numbers, credentials, firmware binaries,
  and machine-specific diagnostics outside Git. Redact attachments before posting.
- Preserve the notices in `licenses/` and `firmware/NOTICE.md`, and credit code
  or firmware research taken from another project.

Kernel changes need an explicit account of failure handling, buffer ownership,
reset behavior, and recovery. Do not run a hardware experiment as part of an
ordinary test suite. The [RTX 3080 pilot](docs/RTX3080-PILOT.md) is a separate,
manual procedure.

## Report a problem

Search [existing fork issues](https://github.com/GWeale/tensor-reclaim/issues)
first. Include the fork commit and reproduction steps. Use the unlock-failure
form when a card fails to unlock, gains no speed, or loses the unlock later.
For CLI problems, include the command and a small redacted input when relevant.

Successful upstream hardware reports belong in
[the upstream success discussion](https://github.com/Zagitta/gpu-unlock/discussions/238),
not in an issue. Identify this fork and its exact commit if you tested it.
For general upstream questions, use
[upstream Q&A](https://github.com/Zagitta/gpu-unlock/discussions/categories/q-a).
Report security problems through the [security policy](SECURITY.md).

Keep discussions technical and respectful. Explain disagreements with evidence,
and do not publish another person's private logs or identifiers.
