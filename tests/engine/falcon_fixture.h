/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GU_FALCON_FIXTURE_H
#define GU_FALCON_FIXTURE_H
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "falcon.h"
#include "registers.h"

uint64_t gu_test_time;
struct fake {
	u32 regs[0x2000 / 4];
	u32 fault;
	unsigned writes, starts, transfers;
	bool stuck, require_physical, reset_stuck;
};
static const struct gu_falcon_engine eng = { 0x1000, 0x1600, 0x2000 };
static int rd(void *ctx, u32 reg, u32 *v)
{
	struct fake *f = ctx;
	if (reg == f->fault) { *v = 0xbadf0000; return 0; }
	if (!reg) { *v = 0x162000a1; return 0; }
	assert(reg >= eng.base && reg < eng.base + sizeof(f->regs));
	*v = f->regs[(reg - eng.base) / 4];
	return 0;
}
static void wr(void *ctx, u32 reg, u32 v)
{
	struct fake *f = ctx;
	assert(reg >= eng.base && reg < eng.base + sizeof(f->regs));
	f->writes++;
	f->regs[(reg - eng.base) / 4] =
		f->reset_stuck && reg == eng.base + GU_FALCON_ENGINE_OFFSET ? 0 : v;
	if (reg == eng.base + GU_FALCON_DMATRFCMD_OFFSET) {
		f->transfers++;
		f->regs[GU_FALCON_DMATRFCMD_OFFSET / 4] = 2;
	}
	if ((reg == eng.base + GU_FALCON_CPUCTL_OFFSET ||
	     reg == eng.base + GU_FALCON_CPUCTL_ALIAS_OFFSET) && v == 2) {
		f->starts++;
		bool physical = (f->regs[(eng.fbif - eng.base + GU_FBIF_CTL_OFFSET) / 4] & 128) &&
			!f->regs[GU_FALCON_DMACTL_OFFSET / 4];
		f->regs[GU_FALCON_CPUCTL_OFFSET / 4] =
			!f->stuck && (!f->require_physical || physical) ? 16 : 0;
	}
}
static struct gu_falcon_io init(struct fake *f, bool halted)
{
	memset(f, 0, sizeof(*f));
	gu_test_time = 0;
	f->fault = ~0u;
	f->regs[GU_FALCON_HWCFG2_OFFSET / 4] = 1u << 31;
	f->regs[GU_FALCON_HWCFG_OFFSET / 4] = 64;
	f->regs[GU_FALCON_CPUCTL_OFFSET / 4] = halted ? 16 : 0;
	f->regs[GU_FALCON_DMACTL_OFFSET / 4] = 0xff;
	return (struct gu_falcon_io){ .context = f, .read = rd, .write = wr };
}
#endif
