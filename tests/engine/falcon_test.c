// SPDX-License-Identifier: GPL-2.0-only
/* Synthetic MMIO only: no firmware files, PCI access or GPU are used. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "falcon.h"
#include "registers.h"

#include "falcon_fixture.h"

static void loader_cases(void)
{
	u32 words[192] = { 0 };
	struct gu_falcon_loader_image image = {
		.loader = words, .loader_size = sizeof(words), .dma = 0x10000,
		.data_off = 0x100, .imem_ns_size = 0x100, .dmem_size = 0x100,
	};
	struct gu_falcon_evidence ev;
	struct fake f;
	struct gu_falcon_io io = init(&f, true);
#ifdef GU_BASELINE
	assert(gu_falcon_loader(&io, &eng, &image, &ev) == -ENODEV);
	assert(!f.starts);
	io = init(&f, false); f.require_physical = true;
	assert(gu_falcon_loader(&io, &eng, &image, &ev) == -ETIMEDOUT);
	assert(f.starts == 1 && !ev.halted);
	puts("baseline reproduced: stale HALTED rejected; missing physical-no-context setup times out");
#else
	image.turing = true;
	f.require_physical = true;
	assert(!gu_falcon_loader(&io, &eng, &image, &ev));
	assert(f.starts == 1 && ev.started && ev.halted && ev.reloaded);
	assert(gu_test_time >= 10000);
	io = init(&f, true); image.turing = false;
	assert(gu_falcon_loader(&io, &eng, &image, &ev) == -ENODEV && !f.starts);
	io = init(&f, true); image.turing = true; f.stuck = true;
	assert(gu_falcon_loader(&io, &eng, &image, &ev) == -ETIMEDOUT && !ev.halted);
	io = init(&f, true); f.fault = eng.base + GU_FALCON_CPUCTL_OFFSET;
	assert(gu_falcon_loader(&io, &eng, &image, &ev) == -ENODEV && !f.starts);
	io = init(&f, false); image.loader_size--;
	assert(gu_falcon_loader(&io, &eng, &image, &ev) == -EINVAL && !f.writes && !ev.started);
	puts("Turing loader: scoped stale HALTED, physical DMA, wait, timeout, inaccessible and invalid-input checks passed");
#endif
}
#ifndef GU_BASELINE
static void direct_and_dma_cases(void)
{
	struct fake f;
	u32 words[192] = { 0 };
	struct gu_falcon_direct_image image = {
		.words = words, .image_size = sizeof(words), .os_code_size = 256,
		.app_code_off = 256, .app_code_size = 256, .os_data_off = 512,
		.os_data_size = 256, .turing = true,
	};
	struct gu_falcon_evidence ev;
	struct gu_falcon_io io = init(&f, true);
	assert(!gu_falcon_direct(&io, &eng, &image, &ev) && f.starts == 1);
	io = init(&f, true); image.turing = false;
	assert(gu_falcon_direct(&io, &eng, &image, &ev) == -ETIMEDOUT && !f.starts);
	io = init(&f, true); image.turing = true; f.fault = eng.base + GU_FALCON_CPUCTL_OFFSET;
	assert(gu_falcon_direct(&io, &eng, &image, &ev) == -EIO && !f.starts);
	io = init(&f, false); image.image_size--;
	assert(gu_falcon_direct(&io, &eng, &image, &ev) == -EINVAL && !f.writes);
	image.image_size++; image.words = NULL;
	assert(gu_falcon_direct(&io, &eng, &image, &ev) == -EINVAL && !f.writes);
	image.words = words;
	io = init(&f, false); f.reset_stuck = true;
	assert(gu_falcon_direct(&io, &eng, &image, &ev) == -ETIMEDOUT && !f.starts);
	io = init(&f, false); f.regs[GU_FALCON_HWCFG2_OFFSET / 4] = 0;
	assert(!gu_falcon_direct(&io, &eng, &image, &ev)); /* documented pre-reset timeout */
	io = init(&f, false);
	assert(!gu_falcon_dma(&io, eng.base, 0, 0, 0x10000, 257, 0));
	assert(f.transfers == 2); /* non-256-aligned DMEM is already supported */
	io = init(&f, false);
	assert(gu_falcon_dma(&io, eng.base, 0xffff00, 0, 0x10000, 257, 0) == -EINVAL);
	assert(!f.writes);
	puts("direct loader/DMA: Turing-only timeout allowance, invalid input, reset failure, 257-byte rounding and overflow checks passed");
}
#endif
int main(void)
{
	loader_cases();
#ifndef GU_BASELINE
	direct_and_dma_cases();
#endif
	return 0;
}
