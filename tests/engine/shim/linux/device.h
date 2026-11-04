/* SPDX-License-Identifier: GPL-2.0-only */
struct device { int unused; };
#define dev_dbg(dev, ...) do { (void)(dev); if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define dev_err(dev, ...) do { (void)(dev); if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#include <stdio.h>
