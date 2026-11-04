/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdint.h>
extern uint64_t gu_test_time;
static inline void usleep_range(unsigned long lo, unsigned long hi)
{ (void)hi; gu_test_time += lo; }
static inline void msleep(unsigned int ms) { gu_test_time += ms * 1000; }
