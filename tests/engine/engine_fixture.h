/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GU_ENGINE_FIXTURE_H
#define GU_ENGINE_FIXTURE_H
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
#endif
