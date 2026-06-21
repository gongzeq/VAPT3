"""Threat Intel feed pullers.

Each feed puller:
1. Fetches data from a public source
2. Maps it to the Threat Intel data model
3. Upserts via :mod:`secbot.threat_intel.repo`
4. Records a ``FeedPullRun`` with counts and status

Feed pullers are called by Workflow cron jobs and the manual trigger API.
"""

from secbot.threat_intel.feeds.apt_aliases_seed import seed_apt_aliases
from secbot.threat_intel.feeds.cisa_kev import pull_cisa_kev
from secbot.threat_intel.feeds.mitre_groups import import_mitre_groups
from secbot.threat_intel.feeds.threatfox import pull_threatfox

__all__ = [
    "import_mitre_groups",
    "pull_cisa_kev",
    "pull_threatfox",
    "seed_apt_aliases",
]
