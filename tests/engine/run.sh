#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
cd "$(dirname "$0")/../.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cc=${CC:-cc}
# Recipe tables use partial static initializers; GA100 is deliberately not an
# enabled PCI recipe. Match the kernel's warning policy for those two cases.
flags='-std=c11 -Wall -Wextra -Werror -Wno-missing-field-initializers -Wno-unused-const-variable'
includes='-Itests/engine/shim -Ikernel/gpu_unlock'
# Optional sanitizer mode; ordinary make check remains portable to host cc.
if [ "${SANITIZE:-0}" = 1 ]; then
    flags="$flags -fsanitize=address,undefined -fno-omit-frame-pointer -g"
fi
$cc $flags $includes tests/engine/falcon_test.c kernel/gpu_unlock/falcon.c \
    kernel/gpu_unlock/prep_610.c -o "$work/falcon"
"$work/falcon"
$cc $flags $includes tests/engine/hs_preflight_test.c kernel/gpu_unlock/falcon.c \
    kernel/gpu_unlock/prep_610.c -o "$work/hs-preflight"
"$work/hs-preflight"
$cc $flags $includes tests/engine/engine_test.c kernel/gpu_unlock/engine.c \
    kernel/gpu_unlock/recipes.c kernel/gpu_unlock/payload.c \
    kernel/gpu_unlock/falcon.c kernel/gpu_unlock/prep_610.c -o "$work/engine"
"$work/engine"
"$work/engine" "$work/turing.bin"
# nlzy/turing-unlock's two-write signature, also pinned in RakkiPoni #294.
# Whole-image check detects misplaced frames/slots; not a Falcon emulator.
printf '%s  %s\n' b0ec90294d1de3c67e024631c0a11000f281470d76eed806fc24c66b7fd1ef41 "$work/turing.bin" | sha256sum -c -
# Rebuild the same reproducer with the unchanged engine from our fork base.
# This exercises the old C, rather than recreating its reject in a fixture.
if [ "${BASELINE:-0}" = 1 ]; then
    git show 7eb51bccae0a0b7e599e084d971170e9a1e82d0c:kernel/gpu_unlock/falcon.c > "$work/falcon-old.c"
    $cc $flags $includes -DGU_BASELINE tests/engine/falcon_test.c "$work/falcon-old.c" \
        kernel/gpu_unlock/prep_610.c -o "$work/baseline"
    "$work/baseline"
    git show 981a9f434f3244a5c9880b99036d7b5b6a1c8116:kernel/gpu_unlock/falcon.c > "$work/falcon-prior.c"
    $cc $flags $includes -DGU_OLD_HS tests/engine/hs_preflight_test.c "$work/falcon-prior.c" \
        kernel/gpu_unlock/prep_610.c -o "$work/hs-baseline"
    "$work/hs-baseline"
fi
