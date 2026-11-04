// SPDX-License-Identifier: GPL-2.0-only
#include "falcon_fixture.h"

static struct gu_falcon_hs_image valid_image(void)
{
	return (struct gu_falcon_hs_image) {
		.dma = 0x10000, .code_off = 256, .code_size = 256,
		.code_va = 256, .data_off = 512, .data_size = 257,
		.os_code_size = 256,
	};
}
int main(void)
{
	struct fake f;
	struct gu_falcon_evidence ev;
	struct gu_falcon_hs_image image = valid_image();
	struct gu_falcon_io io = init(&f, false);
	image.os_code_off = 1;
	int ret = gu_falcon_hs(&io, &eng, &image, &ev);
#ifdef GU_OLD_HS
	assert(ret == -EINVAL && f.writes == 6 && ev.reset_asserted && !ev.started);
	puts("HS baseline reproduced: malformed OS transfer rejected only after six reset/setup writes");
#else
	assert(ret == -EINVAL && !f.writes && !ev.reset_asserted && !ev.started);
	assert(gu_falcon_hs_validate(NULL) == -EINVAL);
	/* Every malformed transfer is rejected before any reset or DMA write. */
	for (unsigned int i = 0; i < 9; i++) {
		image = valid_image(); io = init(&f, false);
		switch (i) {
		case 0: image.code_pa = 1; break;
		case 1: image.code_va = 1; break;
		case 2: image.data_pa = 1; break;
		case 3: image.data_off = 1; break;
		case 4: image.os_code_off = 1; break;
		case 5: image.code_size = 0; break;
		case 6: image.dma = ~0ull - 255; image.os_code_off = 256; break;
		case 7: image.code_pa = 0xffff00; image.code_size = 257; break;
		case 8: image.dma = 1ull << 49; break;
		}
		assert(gu_falcon_hs_validate(&image) < 0);
		assert(gu_falcon_hs(&io, &eng, &image, &ev) < 0);
		assert(!f.writes && !f.starts && !ev.reset_asserted);
	}
	image = valid_image(); io = init(&f, false);
	assert(!gu_falcon_hs_validate(&image) && !f.writes);
	assert(!gu_falcon_hs(&io, &eng, &image, &ev));
	assert(f.starts == 1 && f.transfers == 4 && ev.halted);
	/* A reset failure remains an uncertain hardware operation, not preflight. */
	io = init(&f, false); f.reset_stuck = true;
	assert(gu_falcon_hs(&io, &eng, &image, &ev) == -ETIMEDOUT);
	assert(f.writes && !f.starts);
	puts("HS preflight: code/data/OS validation is pure; all invalid transfers write nothing; valid rounded DMA and reset failure passed");
#endif
	return 0;
}
