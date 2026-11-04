// SPDX-License-Identifier: GPL-2.0-only
/* Exercises production recipe selection, payload construction and transaction
 * execution. The fake launch decodes slots; it does NOT emulate signed code. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "engine.h"
#include "registers.h"

uint64_t gu_test_time;
struct reg { u32 addr, value; };
struct fake {
	struct reg regs[32];
	size_t n;
	const struct gu_card *card;
	struct gu_engine_plan plan;
	struct gu_engine_entry entry;
	u8 *image;
	unsigned launches, restores, stock, handoffs, host_writes, secure_writes;
	int launch_error, handoff_error, stock_error, restore_error;
	u32 fault, fault_after, corrupt_addr;
	bool drop_write, corrupt_mask, reset_mask, reset_selectors, bad_wpr, clear_fault;
};
static u32 get32(const u8 *p)
{ return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static u32 *reg(struct fake *f, u32 addr)
{
	for (size_t i = 0; i < f->n; i++) if (f->regs[i].addr == addr) return &f->regs[i].value;
	assert(f->n < 32);
	f->regs[f->n].addr = addr;
	return &f->regs[f->n++].value;
}
static int rd(void *ctx, u32 addr, u32 *v)
{
	struct fake *f = ctx;
	*v = addr == f->fault || (f->launches && addr == f->fault_after) ? 0xbadf0000 : *reg(f, addr);
	return 0;
}
static void wr(void *ctx, u32 addr, u32 v)
{
	struct fake *f = ctx;
	/* Any host write to a PLM or WPR2 fails this fixture. */
	assert(addr == f->card->family->feat_ss0 || addr == f->card->family->feat_ss1);
	assert(!f->plan.direct && f->stock == 1);
	f->host_writes++;
	*reg(f, addr) = v;
}
static struct gu_falcon_io io(struct fake *f)
{ return (struct gu_falcon_io){ .context = f, .read = rd, .write = wr }; }
static int launch(void *ctx, size_t index, unsigned int attempt, const struct gu_reg_write *first)
{
	struct fake *f = ctx;
	const struct gu_payload *p = f->card->family->booter->payload;
	(void)index; (void)attempt; (void)first;
	assert(!f->stock && !f->handoffs);
	f->launches++;
	if (!f->plan.frts_restorable) assert(f->launches == 1);
	if (f->clear_fault) f->fault = 0;
	if (f->launch_error) return f->launch_error;
	for (size_t i = 0; i < p->writes; i++) {
		u32 addr = get32(f->image + p->slots[i].address_off);
		u32 value = get32(f->image + p->slots[i].value_off);
		if (f->plan.direct) {
			assert(addr == f->card->family->feat_ss0 || addr == f->card->family->feat_ss1);
		}
		f->secure_writes++;
		if (!f->drop_write && addr != f->corrupt_addr) *reg(f, addr) = value;
	}
	if (f->corrupt_mask) *reg(f, GU_WPR_CFG_PLM_OFFSET) ^= 0x10;
	return 0;
}
static int restore(void *ctx)
{
	struct fake *f = ctx;
	assert(f->plan.frts_restorable && f->launches);
	f->restores++;
	return f->restore_error;
}
static int stock(void *ctx)
{
	struct fake *f = ctx;
	assert(f->launches && !f->stock++);
	return f->stock_error;
}
static int handoff(void *ctx)
{
	struct fake *f = ctx;
	assert(f->stock == 1);
	f->handoffs++;
	*reg(f, GU_WPR2_ADDR_HI_OFFSET) = f->bad_wpr ? 0x100 : 0;
	if (f->reset_mask) *reg(f, GU_WPR_CFG_PLM_OFFSET) ^= 0x10;
	if (f->reset_selectors) *reg(f, f->card->family->feat_ss1) = 0;
	if (f->handoff_error) return f->handoff_error;
	return 0;
}
static void init(struct fake *f, u16 id, enum gu_selector_mode mode)
{
	memset(f, 0, sizeof(*f));
	f->card = gu_card_find(id); assert(f->card);
	assert(!gu_engine_plan(f->card, mode, &f->plan));
	*reg(f, f->card->family->feat_plm) = 0xffffff8f;
	*reg(f, GU_WPR_CFG_PLM_OFFSET) = 0x4cb8f;
	f->image = malloc(f->card->family->booter->payload->size + 8); assert(f->image);
	memset(f->image, 0xa5, f->card->family->booter->payload->size + 8);
	struct gu_falcon_io mmio = io(f);
	assert(!gu_engine_entry(&mmio, &f->plan, &f->entry));
}
static int run(struct fake *f)
{
	struct gu_falcon_io mmio = io(f);
	struct gu_engine_ops ops = { f, launch, restore, stock, handoff };
	int ret = gu_engine_run(&mmio, &f->plan, &f->entry, f->image, &ops);
	for (size_t i = 0; i < 8; i++) assert(f->image[f->card->family->booter->payload->size + i] == 0xa5);
	return ret;
}
static void direct_cases(void)
{
	struct fake f;
	init(&f, 0x220a, GU_SELECT_AUTO); assert(f.plan.direct);
	assert(!run(&f));
	assert(f.launches == 1 && !f.host_writes && !f.restores && f.stock == 1 && f.handoffs == 1);
	assert(*reg(&f, GU_FEAT_PLM_OFFSET) == f.entry.feat_plm);
	assert(*reg(&f, GU_WPR_CFG_PLM_OFFSET) == f.entry.wpr_cfg_plm); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.drop_write = true;
	assert(run(&f) == -EIO && f.launches == 1 && !f.handoffs && !f.host_writes); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.corrupt_mask = true;
	assert(run(&f) == -EIO && f.launches == 1 && !f.handoffs); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.launch_error = -ETIMEDOUT;
	assert(run(&f) == -ETIMEDOUT && f.launches == 1 && !f.stock); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.fault_after = GU_FEAT_SS1_OFFSET;
	assert(run(&f) == -ENODEV && f.launches == 1 && !f.handoffs); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.reset_selectors = true;
	assert(run(&f) == -EIO && f.handoffs == 1 && f.launches == 1); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.reset_mask = true;
	assert(run(&f) == -EIO && f.handoffs == 1 && f.launches == 1); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.bad_wpr = true;
	assert(run(&f) == -EBUSY && f.handoffs == 1); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.handoff_error = -ETIMEDOUT;
	assert(run(&f) == -ETIMEDOUT && f.launches == 1); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.stock_error = -EIO;
	assert(run(&f) == -EIO && !f.handoffs && !f.host_writes); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT);
	f.plan.secure = f.card->family->privileged;
	assert(run(&f) == -EINVAL && !f.launches); free(f.image);
	init(&f, 0x220a, GU_SELECT_DIRECT); f.plan.secure.count = 7;
	assert(run(&f) == -E2BIG && !f.launches); free(f.image);
	puts("direct transaction: single launch, no host/PLM writes or retry, masks/selectors, reset and readback failures passed");
}
static void family_cases(void)
{
	struct fake f;
	const u16 ids[] = { 0x220a, 0x2414, 0x2486, 0x2504, 0x1e07, 0x1e84, 0x1f08, 0x2684 };
	for (size_t i = 0; i < sizeof(ids)/sizeof(ids[0]); i++) {
		init(&f, ids[i], GU_SELECT_AUTO);
		assert(f.plan.direct == (ids[i] == 0x220a));
		assert(!gu_payload_check(f.card->family->booter->payload));
		if (f.card->family->turing_layout) {
			assert(!f.plan.frts_restorable && f.plan.secure.count == 2);
			assert(f.card->family->booter->payload->writes == 2);
			f.fault = f.card->family->feat_plm; /* protected pre-read is allowed */
			f.clear_fault = true;
		}
		assert(!run(&f));
		assert(f.host_writes == (f.plan.direct ? 0u : 2u)); free(f.image);
	}
	/* Explicit fallback remains available before the first launch. */
	init(&f, 0x220a, GU_SELECT_PLM); assert(!f.plan.direct); assert(!run(&f));
	assert(f.launches == 1 && f.host_writes == 2 && f.restores == 1); free(f.image);
	init(&f, 0x2486, GU_SELECT_DIRECT); assert(f.plan.direct); assert(!run(&f)); free(f.image);
	/* Legacy readback retry remains bounded and only follows successful completion. */
	init(&f, 0x220a, GU_SELECT_PLM); f.drop_write = true;
	assert(run(&f) == -EIO && f.launches == 2 && f.restores == 1 && !f.handoffs); free(f.image);
	init(&f, 0x1e07, GU_SELECT_AUTO); f.drop_write = true;
	assert(run(&f) == -EIO && f.launches == 1 && !f.restores && !f.handoffs); free(f.image);
	puts("mixed families: GA102 auto, other GA10x opt-in, Turing/Ada legacy gates and bounded legacy retry passed");
}
static void entry_cases(void)
{
	struct fake f;
	init(&f, 0x220a, GU_SELECT_AUTO);
	struct gu_falcon_io mmio = io(&f);
	*reg(&f, GU_FEAT_SS0_OFFSET) = GU_SS0_UNLOCK;
	*reg(&f, GU_FEAT_SS1_OFFSET) = GU_SS1_UNLOCK;
	assert(gu_engine_entry(&mmio, &f.plan, &f.entry) == -EALREADY);
	assert(!f.launches && !f.host_writes);
	*reg(&f, GU_WPR2_ADDR_HI_OFFSET) = 0x100;
	assert(gu_engine_entry(&mmio, &f.plan, &f.entry) == -EALREADY);
	*reg(&f, GU_FEAT_SS1_OFFSET) = 0;
	assert(gu_engine_entry(&mmio, &f.plan, &f.entry) == -EBUSY);
	*reg(&f, GU_WPR2_ADDR_HI_OFFSET) = 0;
	*reg(&f, GU_FEAT_PLM_OFFSET) = ~0u;
	assert(gu_engine_entry(&mmio, &f.plan, &f.entry) == -EBUSY);
	*reg(&f, GU_FEAT_PLM_OFFSET) = 0xffffff8f; f.fault = GU_WPR_CFG_PLM_OFFSET;
	assert(gu_engine_entry(&mmio, &f.plan, &f.entry) == -ENODEV);
	free(f.image);
	puts("kept-power entry: protected PLMs recognized by selectors without writes; open PLM alone refused");
}
static void quiescence_cases(void)
{
	struct fake f;
	init(&f, 0x1e07, GU_SELECT_AUTO);
	struct gu_falcon_io mmio = io(&f);
	*reg(&f, GU_GSP_BASE + GU_FALCON_CPUCTL_OFFSET) = 16;
	*reg(&f, GU_SEC2_BASE + GU_FALCON_CPUCTL_OFFSET) = 16;
	assert(!gu_engine_turing_quiesce(&mmio));
	*reg(&f, GU_SEC2_BASE + GU_FALCON_DMATRFCMD_OFFSET) = 1;
	assert(gu_engine_turing_quiesce(&mmio) == -ETIMEDOUT);
	*reg(&f, GU_SEC2_BASE + GU_FALCON_DMATRFCMD_OFFSET) = 0;
	*reg(&f, GU_GSP_BASE + GU_FALCON_CPUCTL_OFFSET) = 0;
	assert(gu_engine_turing_quiesce(&mmio) == -ETIMEDOUT);
	f.fault = GU_GSP_BASE + GU_FALCON_CPUCTL_OFFSET;
	assert(gu_engine_turing_quiesce(&mmio) == -EIO);
	assert(!f.launches && !f.host_writes); free(f.image);
	puts("Turing handoff: both halts and idle DMA required; busy/inaccessible engines refused");
}
static void payload_cases(void)
{
	const struct gu_payload *orig = gu_card_find(0x1e07)->family->booter->payload;
	struct gu_payload p = *orig;
	struct gu_payload_slot slot = { p.size - 2, 4 };
	p.slots = &slot; p.writes = 1;
	u8 *buf = malloc(p.size); assert(buf);
	memset(buf, 0xa5, p.size);
	assert(gu_payload_build(&p, buf, NULL, 0) == -EINVAL && buf[0] == 0xa5);
	p = *orig;
	struct gu_payload_word word = { p.size, 0 };
	p.words = &word; p.word_count = 1;
	assert(gu_payload_build(&p, buf, NULL, 0) == -EINVAL && buf[0] == 0xa5);
	assert(gu_payload_build(orig, buf, NULL, 1) == -EINVAL);
	free(buf);
	puts("payload: production bounds rejection occurs before image writes; both chain layouts exercised");
}
int main(int argc, char **argv)
{
	if (argc == 2) {
		struct fake f; init(&f, 0x1e07, GU_SELECT_AUTO);
		assert(!gu_payload_build(f.card->family->booter->payload, f.image,
			f.plan.secure.entries, f.plan.secure.count));
		FILE *out = fopen(argv[1], "wb"); assert(out);
		assert(fwrite(f.image, 1, 0xfa00, out) == 0xfa00); assert(!fclose(out)); free(f.image);
		return 0;
	}
	direct_cases(); family_cases(); entry_cases(); quiescence_cases(); payload_cases(); return 0;
}
