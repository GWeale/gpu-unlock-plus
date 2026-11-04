# First working release validation

Worker `hatter-small`, checkout `/home/hatter/Developer/gpu-unlock-plus`.
Checked 2026-11-03 Pacific (2026-11-04 UTC).
Base upstream revision `7eb51bccae0a0b7e599e084d971170e9a1e82d0c`.
All files under `kernel/`, `firmware/`, `licenses/`, and the native engine package
recipes remain unchanged from that base. `VERSION` remains the engine's 2.0.0.

Final owner synchronization fast-forwarded the clean private `main` checkout from
`247ad059004c36002cc58dafba47ccb737ed5f69` to
`eb83380fb13837eefbad6f4b2518b6ed0cbd0846`. The incoming diff contained exactly
three files: benchmark validation, its regression tests, and this receipt.
The sync reran `make check`, CLI help/version, doctor/status/support, synthetic
comparisons, and CPU-only benchmark input refusal on that actual owner checkout.
Earlier toolchain, source archive and module build results below were retained;
the unchanged kernel build and upstream container matrix were not rerun.

## Observed checks

| Command/check | Result |
| --- | --- |
| `dev-doctor --smoke --auth` | Passed local toolchain, temporary build, existing login and backup-job checks |
| `dev-doctor` | Final owner sync passed local inventory |
| `fleet-capabilities --json` | Qualified Hatter for bounded local work; two build jobs used |
| `make check` | Final owner sync passed all 31 behavioral tests, including all eight missing-config-field subcases, upstream fake-root staging, Python compilation and whitespace checks |
| `make -C kernel/gpu_unlock KCFLAGS=-Werror -j2` | Passed against installed `7.0.0-42-generic` headers; no installation or loading |
| `make dist` | Passed source archive generation; enhanced CLI, recipes, tests and documentation included |
| `./gpu-unlock-plus --help`, `--version` and subcommand help | Final owner sync passed |
| `./gpu-unlock-plus doctor` and `doctor --json` | Passed without sudo; zero NVIDIA display/3D GPUs, no PCI inventory errors, installed running-kernel headers observed |
| `./gpu-unlock-plus status` and `status --json` | Passed without sudo; zero NVIDIA cards, no success assertion |
| `./gpu-unlock-plus support` and `support --json` | Passed; engine recipe table available |
| `./gpu-unlock-plus bench --target 0000:01:00.0 --output .local/unavailable.json --json` | Expected exit 2, optional torch absent; no output result created |
| `./gpu-unlock-plus bench --target 0000:01:00.0 --shape 0 16 16 --output .local/owner-sync-invalid.json --json` | Final owner sync observed expected exit 2 before GPU dependencies; no result created |
| `./gpu-unlock-plus compare tests/fixtures/baseline.json tests/fixtures/baseline.json` (also with `--json`) | Final owner sync passed complete CPU-only synthetic fixture; text visibly marked as fixture |
| `./gpu-unlock-plus compare tests/fixtures/baseline.json <private-incomplete-fixture.json> --json` | Final owner sync rejected each of the eight missing config fields with exit 2 |
| Current tracked files, outgoing diff/history filename and credential-pattern screen | Screened before private backup; no credential material intentionally added |

The module build printed a compiler-name difference (same GCC 15.2.0 version),
a missing/different `pahole` warning, and skipped BTF generation because `vmlinux`
was unavailable. The `.ko` was produced. Compilation is not evidence of a working
unlock. Generated objects/module files are ignored local build artifacts.

The new test suite includes multi-GPU partial success, unsupported exact IDs,
missing tools and denied reads, malformed and stale/other-boot/other-BDF logs,
power-transition invalidation, plan-only recovery paths, shape/work/memory bounds,
bad correctness and precision evidence, schema/identity/condition mismatches,
and atomic private output refusal/preservation. Existing module/boot/license
staging is exercised under temporary `DESTDIR`, without root or firmware assets.

A real doctor run exposed `ENOMEM` when a single proc/sys read requested 4 MiB.
The read boundary now uses small bounded chunks. A live proc/sys regression check
verifies the kernel release against `platform.release()`. A per-BDF log delimiter
regression found during focused checking was also corrected before completion.

## Unavailable or deliberately unrun

- No NVIDIA hardware or CUDA-enabled torch environment was available on Hatter.
  GPU capture success, actual precision/instruction selection, unlock retention,
  resume behavior, power behavior and performance were not validated.
- The initial Hatter runtime had no permitted hidden native review route.
  The lead later obtained a fresh-context, read-only native review from Desktop
  of revision `247ad059004c36002cc58dafba47ccb737ed5f69`.
  It found that incomplete benchmark configurations could receive defaults and
  pass comparison. The lead reproduced the defect, required the exact field set,
  and added a regression case for every configuration field.
  The focused regression passed in memory against the amended source; the final
  Hatter owner sync also passed `make check` with 31 tests and CLI rejection of
  all eight incomplete configurations at the synchronized revision above.
  This review did not validate successful CUDA capture or GPU behavior.
- The upstream container matrix (`make test-module`, `make test-packages`) was
  not run. It downloads dependencies and package inputs. Available host headers
  were used directly instead; packaging staging was tested in fake roots.
- Firmware generation/download, actual package installation/removal, driver
  unload/module load, boot changes, reboot, public release, PR, deployment and
  upstream messages were not performed.

## Ownership and delivery

The original `origin` was renamed to `upstream`, with a disabled push URL.
Private backup destination is `GWeale/gpu-unlock-plus`; authenticated ownership
and private visibility were verified again during final owner synchronization.
The registered T3 project still points to this checkout with check, read-only
doctor/status, and build-only module scripts. The final remote
SHA and enrollment/backup receipt are reported at delivery, rather than embedded
in a self-referential commit. Runtime observations and raw logs stay outside Git
under `~/.local/state/gpu-unlock-plus/`.

Inherited CI is manual-only. The release-producing Unraid discovery job is also
guarded to the original upstream repository. Private backup does not authorize
public release or installation. The independent review finding is corrected.
Separately authorized NVIDIA hardware testing remains unrun.
