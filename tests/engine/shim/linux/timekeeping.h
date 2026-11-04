/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdint.h>
typedef uint64_t ktime_t;
extern uint64_t gu_test_time;
static inline ktime_t ktime_get(void) { return gu_test_time++; }
static inline ktime_t ktime_add_us(ktime_t t, unsigned int us) { return t + us; }
static inline int ktime_compare(ktime_t a, ktime_t b) { return (a > b) - (a < b); }
