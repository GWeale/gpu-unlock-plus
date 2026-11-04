// SPDX-License-Identifier: GPL-2.0-only
#ifdef __KERNEL__
#include <linux/errno.h>
#else
#include <errno.h>
#endif
#include "session.h"

int gu_attempt_errno(const struct gu_attempt *result)
{
	if (result->operation_error && result->operation_error != -EALREADY)
		return result->operation_error;
	if (result->cleanup_error)
		return result->cleanup_error;
	if (result->retained)
		return -EBUSY;
	return result->operation_error;
}
int gu_session_prepare(struct gu_session *session, const struct gu_session_ops *ops)
{
	int ret;
	if (session->state == GU_SESSION_POWER_OFF_REQUIRED)
		return -EOWNERDEAD;
	if (session->state == GU_SESSION_PREPARED)
		return -EBUSY;
	session->state = GU_SESSION_NEW;
	session->stage = GU_SESSION_ASSESS;
	session->round++;
	ret = ops->assess(ops->context);
	session->last = (struct gu_attempt){ .operation_error = ret };
	if (ret == -EALREADY)
		session->state = GU_SESSION_READY;
	if (ret)
		return ret;
	session->stage = GU_SESSION_FIRMWARE;
	ret = ops->prepare(ops->context);
	session->last.operation_error = ret;
	if (!ret)
		session->state = GU_SESSION_PREPARED;
	return ret;
}
int gu_session_execute(struct gu_session *session, const struct gu_session_ops *ops)
{
	int ret;
	if (session->state == GU_SESSION_POWER_OFF_REQUIRED)
		return -EOWNERDEAD;
	if (session->state != GU_SESSION_PREPARED)
		return -EPROTO;
	session->stage = GU_SESSION_TRANSACTION;
	session->last = ops->execute(ops->context);
	ret = gu_attempt_errno(&session->last);
	if (session->last.retained || session->last.cleanup_error)
		session->state = GU_SESSION_POWER_OFF_REQUIRED;
	else
		session->state = !ret || ret == -EALREADY ? GU_SESSION_READY : GU_SESSION_NEW;
	return ret;
}
