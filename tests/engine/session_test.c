// SPDX-License-Identifier: GPL-2.0-only
/* Session admission drives the same production selector transaction as the
 * existing engine fixture. Only PCI/resource ownership results are synthetic. */
#include "engine_fixture.h"
#include "session.h"
struct round_fixture {
	struct fake gpu;
	unsigned assessments, preparations, executions;
	int assess_error, prepare_error, execution_error, cleanup_error;
	bool retained;
};
static int assess(void *context)
{
	struct round_fixture *f = context;
	f->assessments++;
	if (f->assess_error)
		return f->assess_error;
	struct gu_falcon_io mmio = io(&f->gpu);
	return gu_engine_entry(&mmio, &f->gpu.plan, &f->gpu.entry);
}
static int prepare(void *context)
{
	struct round_fixture *f = context;
	f->preparations++;
	return f->prepare_error;
}
static struct gu_attempt execute(void *context)
{
	struct round_fixture *f = context;
	f->executions++;
	return (struct gu_attempt){ f->execution_error ? f->execution_error : run(&f->gpu),
		f->cleanup_error, f->retained };
}
static struct gu_session_ops setup(struct round_fixture *f)
{
	memset(f, 0, sizeof(*f));
	init(&f->gpu, 0x220a, GU_SELECT_AUTO);
	return (struct gu_session_ops){ f, assess, prepare, execute };
}
static void retained_is_firmware_independent(void)
{
	struct round_fixture f;
	struct gu_session s = { 0 };
	struct gu_session_ops ops = setup(&f);
	*reg(&f.gpu, GU_FEAT_SS0_OFFSET) = GU_SS0_UNLOCK;
	*reg(&f.gpu, GU_FEAT_SS1_OFFSET) = GU_SS1_UNLOCK;
	f.prepare_error = -ENOENT;
	assert(gu_session_prepare(&s, &ops) == -EALREADY);
	assert(s.state == GU_SESSION_READY && !f.preparations && !f.executions);
	assert(!f.gpu.launches && !f.gpu.host_writes);
	assert(gu_session_execute(&s, &ops) == -EPROTO && !f.executions);
	/* READY is a previous observation; a new round cannot reuse it. */
	f.assess_error = -ENODEV;
	assert(gu_session_prepare(&s, &ops) == -ENODEV && s.state == GU_SESSION_NEW);
	assert(f.assessments == 2 && !f.preparations);
	free(f.gpu.image);
}
static void uncertain_failure_is_sticky(void)
{
	struct round_fixture f;
	struct gu_session s = { 0 };
	struct gu_session_ops ops = setup(&f);
	assert(!gu_session_prepare(&s, &ops));
	assert(gu_session_prepare(&s, &ops) == -EBUSY && f.assessments == 1);
	f.gpu.launch_error = -ETIMEDOUT; f.retained = true; f.cleanup_error = -EBUSY;
	assert(gu_session_execute(&s, &ops) == -ETIMEDOUT);
	assert(s.last.operation_error == -ETIMEDOUT && s.last.cleanup_error == -EBUSY && s.last.retained);
	assert(s.state == GU_SESSION_POWER_OFF_REQUIRED && f.gpu.launches == 1);
	/* Neither apparent success nor apparent power loss may erase quarantine. */
	for (unsigned int round = 0; round < 4; round++) {
		*reg(&f.gpu, GU_FEAT_SS0_OFFSET) = round & 1 ? 0 : GU_SS0_UNLOCK;
		*reg(&f.gpu, GU_FEAT_SS1_OFFSET) = round & 1 ? 0 : GU_SS1_UNLOCK;
		assert(gu_session_prepare(&s, &ops) == -EOWNERDEAD);
		assert(gu_session_execute(&s, &ops) == -EOWNERDEAD);
	}
	assert(f.assessments == 1 && f.preparations == 1 && f.executions == 1);
	assert(s.last.operation_error == -ETIMEDOUT && f.gpu.launches == 1);
	/* Another card has independent admission and still completes normally. */
	struct round_fixture other;
	struct gu_session healthy = { 0 };
	struct gu_session_ops other_ops = setup(&other);
	assert(!gu_session_prepare(&healthy, &other_ops));
	assert(!gu_session_execute(&healthy, &other_ops) && healthy.state == GU_SESSION_READY);
	assert(other.gpu.launches == 1);
	free(f.gpu.image); free(other.gpu.image);
}
static struct gu_attempt outcome(void *context) { return *(struct gu_attempt *)context; }
static void cleanup_and_result_normalization(void)
{
	const struct gu_attempt cases[] = {
		{ 0, 0, true }, { -EALREADY, -EIO, false }, { 0, -EIO, false },
		{ -ETIMEDOUT, -EIO, false }, { -EIO, 0, false }, { -EALREADY, 0, false },
	};
	const int errors[] = { -EBUSY, -EIO, -EIO, -ETIMEDOUT, -EIO, -EALREADY };
	for (size_t i = 0; i < sizeof(cases)/sizeof(cases[0]); i++) {
		struct gu_attempt result = cases[i];
		struct gu_session s = { .state = GU_SESSION_PREPARED };
		struct gu_session_ops ops = { .context = &result, .execute = outcome };
		assert(gu_session_execute(&s, &ops) == errors[i]);
		bool blocked = cases[i].retained || cases[i].cleanup_error;
		assert((s.state == GU_SESSION_POWER_OFF_REQUIRED) == blocked);
		assert(s.last.operation_error == cases[i].operation_error);
		assert(s.last.cleanup_error == cases[i].cleanup_error);
		assert(gu_session_execute(&s, &ops) == (blocked ? -EOWNERDEAD : -EPROTO));
	}
}
static void safe_failure_can_reassess(void)
{
	struct round_fixture f;
	struct gu_session s = { 0 };
	struct gu_session_ops ops = setup(&f);
	f.prepare_error = -ENOENT;
	assert(gu_session_prepare(&s, &ops) == -ENOENT && !f.executions);
	f.prepare_error = 0;
	assert(!gu_session_prepare(&s, &ops) && s.round == 2);
	f.execution_error = -EINVAL;
	assert(gu_session_execute(&s, &ops) == -EINVAL && s.state == GU_SESSION_NEW);
	assert(gu_session_execute(&s, &ops) == -EPROTO && f.executions == 1);
	assert(!gu_session_prepare(&s, &ops) && f.assessments == 3);
	assert(!f.gpu.launches);
	f.execution_error = 0;
	assert(!gu_session_execute(&s, &ops) && f.gpu.launches == 1);
	free(f.gpu.image);
}
int main(void)
{
	retained_is_firmware_independent(); uncertain_failure_is_sticky();
	cleanup_and_result_normalization(); safe_failure_can_reassess();
	puts("session engine: no firmware for retained unlocks; quarantine blocks all later effects; cleanup errors preserved; fresh reassessment and per-card isolation passed");
	return 0;
}
