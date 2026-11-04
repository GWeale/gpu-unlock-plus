/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GPU_UNLOCK_UNLOCK_610_H
#define GPU_UNLOCK_UNLOCK_610_H

#include "firmware_610.h"
#include "engine.h"
#include "session.h"

/* Read-only assessment in the pre-driver/pre-NVIDIA-resume window. The caller
 * holds pci_dev_lock. No firmware, allocation of DMA, PCI config or BAR writes.
 * With decoding disabled, cold assessment defers to the mutating transaction;
 * resume assessment refuses it. EALREADY requires both observed selectors. */
int gpu_unlock_610_assess(const struct gu_device *device, bool resume,
			  enum gu_selector_mode mode);

/* The caller holds pci_dev_lock and rechecks driver ownership. Uncertain DMA
 * or failed ownership restoration pins the module until recovery by power off.
 * Both operation and cleanup errors survive in the result. */
struct gu_attempt gpu_unlock_610_unlock(const struct gu_device *device,
		const struct gpu_unlock_610_shared *shared, bool resume, enum gu_selector_mode mode);

#endif
