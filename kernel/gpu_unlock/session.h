/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GPU_UNLOCK_SESSION_H
#define GPU_UNLOCK_SESSION_H
#include "prep_610.h"

enum gu_session_state {
	GU_SESSION_NEW, GU_SESSION_PREPARED, GU_SESSION_READY,
	GU_SESSION_POWER_OFF_REQUIRED,
};
enum gu_session_stage { GU_SESSION_ASSESS, GU_SESSION_FIRMWARE, GU_SESSION_TRANSACTION };
struct gu_attempt {
	int operation_error, cleanup_error;
	bool retained;
};
struct gu_session {
	enum gu_session_state state;
	enum gu_session_stage stage;
	u64 round;
	struct gu_attempt last;
};
struct gu_session_ops {
	void *context;
	/* Read only. EALREADY is a fresh observation, not cached success. */
	int (*assess)(void *context);
	int (*prepare)(void *context);
	struct gu_attempt (*execute)(void *context);
};
int gu_attempt_errno(const struct gu_attempt *result);
/* Prepare every card before executing any: shared firmware is immutable while
 * workers run. Only PREPARED may execute. Every new round reassesses READY.
 * Ownership/cleanup uncertainty blocks all callbacks for this kernel session;
 * the kernel adapter must pin the module so unloading cannot erase the hold. */
int gu_session_prepare(struct gu_session *session, const struct gu_session_ops *ops);
int gu_session_execute(struct gu_session *session, const struct gu_session_ops *ops);
#endif
