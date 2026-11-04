/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GPU_UNLOCK_ENGINE_H
#define GPU_UNLOCK_ENGINE_H
#include "falcon.h"
#include "recipes.h"

/* Auto enables direct selectors only on externally exercised GA102. */
enum gu_selector_mode { GU_SELECT_AUTO = -1, GU_SELECT_PLM, GU_SELECT_DIRECT };
struct gu_engine_plan {
	const struct gu_family *family;
	struct gu_write_table secure, host;
	bool direct, frts_restorable;
};
struct gu_engine_entry { u32 feat_plm, wpr_cfg_plm; };

/* launch returns success only after transport AND payload completion checks.
 * All memory remains caller-owned through handoff, including on failure. */
struct gu_engine_ops {
	void *context;
	int (*launch)(void *context, size_t index, unsigned int attempt,
		      const struct gu_reg_write *first);
	int (*restore_frts)(void *context);
	int (*restore_stock)(void *context);
	int (*handoff)(void *context);
};
int gu_engine_plan(const struct gu_card *card, enum gu_selector_mode mode,
		   struct gu_engine_plan *plan);
/* Read only, before firmware or hardware writes. EALREADY requires both selectors. */
int gu_engine_entry(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
		    struct gu_engine_entry *entry);
int gu_engine_verify(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
		     const struct gu_engine_entry *entry);
int gu_engine_turing_quiesce(const struct gu_falcon_io *io);
int gu_engine_run(const struct gu_falcon_io *io, const struct gu_engine_plan *plan,
		  const struct gu_engine_entry *entry, u8 *image,
		  const struct gu_engine_ops *ops);
#endif
