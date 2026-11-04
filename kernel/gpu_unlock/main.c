// SPDX-License-Identifier: GPL-2.0-only
#include <linux/async.h>
#include <linux/init.h>
#include <linux/list.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/suspend.h>

#include "unlock_610.h"
#include "recipes.h"

static char *targets;
module_param(targets, charp, 0444);
MODULE_PARM_DESC(targets, "\"all\" or comma-separated PCI addresses of supported cards to unlock");

static int direct = GU_SELECT_AUTO;
module_param(direct, int, 0444);
MODULE_PARM_DESC(direct, "-1: direct on GA102 (default); 0: legacy PLMs; 1: direct on capable GA10x (other dies experimental). No in-boot fallback");

static bool resume = true;
module_param(resume, bool, 0644);
MODULE_PARM_DESC(resume, "Unlock the cards again after resume from suspend, which powers them off (default: on)");

/* A target card. Those unlocked at boot stay listed, with a reference, to be
 * unlocked again after each resume. */
struct card {
	struct list_head node;
	struct gu_device device;
	struct gu_session session;
	bool resuming;
};

static LIST_HEAD(cards);
static ASYNC_DOMAIN_EXCLUSIVE(unlock_domain);
static struct gpu_unlock_610_shared shared;

/* The next supported NVIDIA card after from, like pci_get_device(). */
static struct pci_dev *next_supported(struct pci_dev *from, const struct gu_card **recipe)
{
	struct pci_dev *pdev = from;

	while ((pdev = pci_get_device(PCI_VENDOR_ID_NVIDIA, PCI_ANY_ID, pdev)))
		if ((*recipe = gu_card_find(pdev->device)))
			return pdev;
	return NULL;
}

static bool owned_window(const struct card *card)
{
	const struct pci_driver *driver = card->device.pdev->driver;
	return card->resuming ? driver && !strcmp(driver->name, "nvidia") : !driver;
}

static int assess_card(void *context)
{
	struct card *card = context;
	struct pci_dev *pdev = card->device.pdev;
	int ret;
	pci_dev_lock(pdev);
	ret = owned_window(card) ?
		gpu_unlock_610_assess(&card->device, card->resuming, direct) : -EBUSY;
	pci_dev_unlock(pdev);
	return ret;
}
static int prepare_card(void *context)
{
	struct card *card = context;
	struct pci_dev *pdev = card->device.pdev;
	int ret;
	pci_dev_lock(pdev);
	ret = owned_window(card) ? gpu_unlock_610_load_shared(&card->device, &shared) : -EBUSY;
	pci_dev_unlock(pdev);
	return ret;
}
static struct gu_attempt execute_card(void *context)
{
	struct card *card = context;
	struct pci_dev *pdev = card->device.pdev;
	struct gu_attempt result = { .operation_error = -EBUSY };
	pci_dev_lock(pdev);
	if (owned_window(card))
		result = gpu_unlock_610_unlock(&card->device, &shared, card->resuming, direct);
	pci_dev_unlock(pdev);
	return result;
}
static struct gu_session_ops card_ops(struct card *card)
{
	return (struct gu_session_ops){ card, assess_card, prepare_card, execute_card };
}
static void report_card(struct card *card, int ret)
{
	struct pci_dev *pdev = card->device.pdev;
	const struct gu_session *s = &card->session;
	pci_info(pdev, "gpu_unlock: stage=session round=%llu phase=%u state=%u operation=%d cleanup=%d retained=%u result=%d\n",
		 (unsigned long long)s->round, s->stage, s->state,
		 s->last.operation_error, s->last.cleanup_error, s->last.retained, ret);
	if (s->state == GU_SESSION_POWER_OFF_REQUIRED)
		pci_err(pdev, "gpu_unlock: power off required; further attempts refused\n");
	if (ret == -EALREADY)
		pci_info(pdev, "gpu_unlock: %s\n", card->resuming ?
			 "still unlocked after resume" : "already unlocked; left unchanged");
	else if (ret)
		pci_err(pdev, "gpu_unlock: %s failed (%d)\n",
			 s->stage == GU_SESSION_FIRMWARE ? "firmware load" :
			 card->resuming ? "unlock after resume" : "unlock", ret);
	else
		pci_info(pdev, "gpu_unlock: %s\n", card->resuming ? "unlocked again after resume" : "unlocked");
}
static void execute_one(void *data, async_cookie_t cookie)
{
	struct card *card = data;
	struct gu_session_ops ops = card_ops(card);
	report_card(card, gu_session_execute(&card->session, &ops));
}

/* Assess before preparing firmware; only cold cards need a firmware bundle.
 * Publish all shared assets before any concurrent mutating transaction. */
static void unlock_cards(bool resuming)
{
	struct card *card;
	list_for_each_entry(card, &cards, node) {
		struct gu_session_ops ops = card_ops(card);
		int ret;
		card->resuming = resuming;
		ret = gu_session_prepare(&card->session, &ops);
		if (ret)
			report_card(card, ret);
	}
	list_for_each_entry(card, &cards, node)
		if (card->session.state == GU_SESSION_PREPARED)
			async_schedule_domain(execute_one, card, &unlock_domain);
	async_synchronize_full_domain(&unlock_domain);
	gpu_unlock_610_release_shared(&shared);
}

static void drop_card(struct card *card)
{
	list_del(&card->node);
	pci_dev_put(card->device.pdev);
	kfree(card);
}

/* nvidia resumes its cards from its own notifier, at the default priority 0,
 * once this returns: every card must be finished by then. */
static int gpu_unlock_pm_notify(struct notifier_block *nb, unsigned long event, void *unused)
{
	if (event == PM_POST_SUSPEND && resume)
		unlock_cards(true);
	return NOTIFY_DONE;
}

static struct notifier_block pm_nb = {
	.notifier_call = gpu_unlock_pm_notify,
	.priority = 1,
};

/* True when the comma-separated targets list names this PCI device. */
static bool listed(const char *name)
{
	const char *entry, *end;

	for (entry = targets; *entry; entry = *end ? end + 1 : end) {
		end = strchrnul(entry, ',');
		if (strlen(name) == end - entry && !strncasecmp(name, entry, end - entry))
			return true;
	}
	return false;
}

static void report_unmatched(void)
{
	const char *entry, *end;
	struct card *card;
	bool matched;

	for (entry = targets; *entry; entry = *end ? end + 1 : end) {
		end = strchrnul(entry, ',');
		matched = false;
		list_for_each_entry(card, &cards, node) {
			const char *name = pci_name(card->device.pdev);

			if (strlen(name) == end - entry && !strncasecmp(name, entry, end - entry)) {
				matched = true;
				break;
			}
		}
		if (!matched)
			pr_err("gpu_unlock: no supported card at \"%.*s\"\n",
			       (int)(end - entry), entry);
	}
}

static int __init gpu_unlock_init(void)
{
	struct pci_dev *pdev = NULL;
	struct card *card, *next;
	const struct gu_card *recipe;
	bool all, enumerated = true;

	/* Loaded ahead of nvidia on every boot; the command line is the opt-in. */
	if (!targets || !*targets)
		return 0;
	if (direct < GU_SELECT_AUTO || direct > GU_SELECT_DIRECT)
		return -EINVAL;
	all = !strcmp(targets, "all");
	while ((pdev = next_supported(pdev, &recipe))) {
		if (!all && !listed(pci_name(pdev)))
			continue;
		card = kzalloc(sizeof(*card), GFP_KERNEL);
		if (!card) {
			pci_err(pdev, "gpu_unlock: card allocation failed\n");
			enumerated = false;
			pci_dev_put(pdev);
			break;
		}
		card->device.pdev = pci_dev_get(pdev);
		card->device.recipe = recipe;
		list_add_tail(&card->node, &cards);
	}
	if (!all && enumerated)
		report_unmatched();
	/* nvidia loads once this returns: every card must be finished by then. */
	unlock_cards(false);
	list_for_each_entry_safe(card, next, &cards, node)
		if (card->session.state != GU_SESSION_READY &&
		    card->session.state != GU_SESSION_POWER_OFF_REQUIRED)
			drop_card(card);
	if (!list_empty(&cards))
		register_pm_notifier(&pm_nb);
	return 0;
}

static void __exit gpu_unlock_exit(void)
{
	struct card *card, *next;

	if (!list_empty(&cards))
		unregister_pm_notifier(&pm_nb);
	list_for_each_entry_safe(card, next, &cards, node)
		drop_card(card);
}

module_init(gpu_unlock_init);
module_exit(gpu_unlock_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("RTX pre-driver hardware unlock");
MODULE_VERSION("2.0.0");
