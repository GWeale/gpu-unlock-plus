// SPDX-License-Identifier: GPL-2.0-only
/* Selector transaction policy. Based on Lukium #252 (62105cf) and
 * RakkiPoni #294 (9422be4); readbacks are gates, never just diagnostics. */
#include "diagnostic.h"
#ifdef __KERNEL__
#include <linux/errno.h>
#else
#include <errno.h>
#endif
#include "engine.h"
#include "registers.h"

static bool inaccessible(u32 v)
{
	return v == ~0u || (v & 0xffff0000u) == 0xbadf0000u;
}
static int read_reg(const struct gu_falcon_io *io, u32 reg, u32 *value)
{
	if (io->read(io->context, reg, value) || inaccessible(*value))
		return -ENODEV;
	return 0;
}
/* PLMs may legitimately be all ones on the legacy route. */
static int read_plm(const struct gu_falcon_io *io, u32 reg, u32 *value)
{
	if (io->read(io->context, reg, value) || (*value & 0xffff0000u) == 0xbadf0000u)
		return -ENODEV;
	return 0;
}
int gu_engine_plan(const struct gu_card *card, enum gu_selector_mode mode,
		   struct gu_engine_plan *plan)
{
	const struct gu_family *f;
	if (!card || !card->family || !plan || mode < GU_SELECT_AUTO || mode > GU_SELECT_DIRECT)
		return -EINVAL;
	f = card->family;
	*plan = (struct gu_engine_plan){ .family = f };
	plan->direct = f->direct_selectors &&
		(mode == GU_SELECT_DIRECT || (mode == GU_SELECT_AUTO && card->chip == 0x172));
	plan->secure = plan->direct ? f->host : f->privileged;
	if (!plan->direct)
		plan->host = f->host;
	/* Turing clears WPR2 in the payload and cannot refill it from host. */
	plan->frts_restorable = !plan->direct && !f->turing_layout;
	return 0;
}
int gu_engine_entry(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
		    struct gu_engine_entry *entry)
{
	const struct gu_family *f = plan->family;
	u32 ss0, ss1, hi;
	int ret;
	if (read_reg(io, f->feat_ss0, &ss0) || read_reg(io, f->feat_ss1, &ss1) ||
	    read_reg(io, GU_WPR2_ADDR_HI_OFFSET, &hi))
		return -ENODEV;
	if (ss0 == GU_SS0_UNLOCK && ss1 == GU_SS1_UNLOCK)
		return -EALREADY;
	if (hi >> 4)
		return -EBUSY;
	if (io->read(io->context, f->feat_plm, &entry->feat_plm))
		return -ENODEV;
	ret = (entry->feat_plm & 0xffff0000u) == 0xbadf0000u ? -ENODEV : 0;
	/* Turing's PLM can be protected until Booter has run. Its pre-read is
	 * diagnostic; the mandatory post-write readback is not relaxed. */
	if (ret && !f->turing_layout)
		return ret;
	if (!ret && entry->feat_plm == ~0u)
		return -EBUSY; /* Open PLM alone does not prove unlocked selectors. */
	if (plan->direct) {
		ret = read_plm(io, GU_WPR_CFG_PLM_OFFSET, &entry->wpr_cfg_plm);
		if (ret)
			return ret;
		if (entry->wpr_cfg_plm == ~0u || entry->wpr_cfg_plm == 0xfffff0ff)
			return -EBUSY;
	}
	return 0;
}
static int verify_masks(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
			const struct gu_engine_entry *entry)
{
	u32 feat, wpr;
	if (!plan->direct)
		return 0;
	if (read_plm(io, plan->family->feat_plm, &feat) ||
	    read_plm(io, GU_WPR_CFG_PLM_OFFSET, &wpr))
		return -ENODEV;
	GU_NOTE("direct protections: feat=%#x/%#x wpr_cfg=%#x/%#x\n",
		feat, entry->feat_plm, wpr, entry->wpr_cfg_plm);
	if (feat != entry->feat_plm || wpr != entry->wpr_cfg_plm)
		return -EIO;
	return 0;
}
int gu_engine_verify(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
		     const struct gu_engine_entry *entry)
{
	u32 ss0, ss1, hi;
	if (read_reg(io, plan->family->feat_ss0, &ss0) ||
	    read_reg(io, plan->family->feat_ss1, &ss1) ||
	    read_reg(io, GU_WPR2_ADDR_HI_OFFSET, &hi))
		return -ENODEV;
	if (ss0 != GU_SS0_UNLOCK || ss1 != GU_SS1_UNLOCK)
		return -EIO;
	if (hi >> 4)
		return -EBUSY;
	return verify_masks(io, plan, entry);
}
int gu_engine_turing_quiesce(const struct gu_falcon_io *io)
{
	const u32 bases[] = { GU_GSP_BASE, GU_SEC2_BASE };
	size_t i;
	int ret;
	for (i = 0; i < sizeof(bases) / sizeof(bases[0]); i++) {
		ret = gu_falcon_poll(io, bases[i] + GU_FALCON_CPUCTL_OFFSET,
				     16, 16, 1000000, true, NULL);
		/* FULL=0 only permits another queued command; IDLE is bit 1. */
		if (!ret)
			ret = gu_falcon_poll(io, bases[i] + GU_FALCON_DMATRFCMD_OFFSET,
					     2, 2, 1000000, true, NULL);
		if (ret)
			return ret;
	}
	return 0;
}
int gu_engine_run(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
		  const struct gu_engine_entry *entry, u8 *image,
		  const struct gu_engine_ops *ops)
{
	const struct gu_payload *payload = plan->family->booter->payload;
	const struct gu_write_table *table = &plan->secure;
	struct gu_reg_write batch[GU_PAYLOAD_MAX_WRITES];
	size_t i, j, count;
	unsigned int attempt;
	int ret;
	bool matched = false;
	if (!image || !ops || !ops->launch || !ops->restore_frts ||
	    !ops->restore_stock || !ops->handoff || gu_payload_check(payload) ||
	    !table->entries || !table->count)
		return -EINVAL;
	/* A protected WPR_CFG cannot refill FRTS. Refuse a second launch even
	 * if a future recipe accidentally grows beyond one payload. */
	if (!plan->frts_restorable && table->count > payload->writes)
		return -E2BIG;
	if (plan->direct) {
		if (plan->host.count || table->count != 2 ||
		    table->entries[0].addr != plan->family->feat_ss0 ||
		    table->entries[0].value != GU_SS0_UNLOCK ||
		    table->entries[1].addr != plan->family->feat_ss1 ||
		    table->entries[1].value != GU_SS1_UNLOCK)
			return -EINVAL;
		ret = verify_masks(io, plan, entry);
		if (ret)
			return ret;
	}
	for (i = 0; i < table->count; i += payload->writes) {
		count = table->count - i;
		if (count > payload->writes)
			count = payload->writes;
		for (j = 0; j < payload->writes; j++)
			batch[j] = table->entries[i + (j < count ? j : count - 1)];
		for (attempt = 1; attempt <= (plan->frts_restorable ? 2u : 1u); attempt++) {
			u32 before;
			if (i || attempt > 1) {
				ret = ops->restore_frts(ops->context);
				if (ret)
					return ret;
			}
			if (io->read(io->context, batch[0].addr, &before) ||
			    (!plan->family->turing_layout && (before & 0xffff0000u) == 0xbadf0000u))
				return -ENODEV;
			ret = gu_payload_build(payload, image, batch, payload->writes);
			if (ret)
				return ret;
			ret = ops->launch(ops->context, i, attempt, &batch[0]);
			if (ret)
				return ret; /* Never replay an uncertain side effect. */
			ret = verify_masks(io, plan, entry);
			if (ret)
				return ret;
			matched = true;
			for (j = 0; j < count; j++) {
				const struct gu_reg_write *w = &table->entries[i + j];
				u32 observed, expected = w->expect ? w->expect : w->value;
				if (read_plm(io, w->addr, &observed))
					return -ENODEV;
				GU_NOTE("pass=%zu/%zu attempt=%u target=%#x expected=%#x observed=%#x\n",
					i + j + 1, table->count, attempt, w->addr, expected, observed);
				if (observed != expected && !w->optional)
					matched = false;
			}
			if (matched)
				break;
		}
		if (!matched)
			return -EIO;
	}
	if (plan->frts_restorable) {
		ret = ops->restore_frts(ops->context);
		if (ret)
			return ret;
	}
	ret = ops->restore_stock(ops->context);
	if (ret)
		return ret;
	for (i = 0; i < plan->host.count; i++) {
		const struct gu_reg_write *w = &plan->host.entries[i];
		u32 observed;
		if (read_reg(io, w->addr, &observed))
			return -ENODEV;
		io->write(io->context, w->addr, w->value);
		if (read_reg(io, w->addr, &observed))
			return -ENODEV;
		if (observed != w->value)
			return -EIO;
	}
	ret = ops->handoff(ops->context);
	return ret ? ret : gu_engine_verify(io, plan, entry);
}
