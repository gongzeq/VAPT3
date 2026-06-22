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
from secbot.threat_intel.feeds.cpe_match import check_supply_chain, seed_industry_cpes
from secbot.threat_intel.feeds.exploit_db import pull_exploit_db
from secbot.threat_intel.feeds.feodo import pull_feodo
from secbot.threat_intel.feeds.malwarebazaar import pull_malwarebazaar
from secbot.threat_intel.feeds.maritime import pull_maritime
from secbot.threat_intel.feeds.mitre_groups import import_mitre_groups
from secbot.threat_intel.feeds.nvd import pull_nvd
from secbot.threat_intel.feeds.otx import pull_otx
from secbot.threat_intel.feeds.threatfox import pull_threatfox

__all__ = [
    "check_supply_chain",
    "import_mitre_groups",
    "pull_cisa_kev",
    "pull_exploit_db",
    "pull_feodo",
    "pull_malwarebazaar",
    "pull_maritime",
    "pull_nvd",
    "pull_otx",
    "pull_threatfox",
    "seed_apt_aliases",
    "seed_industry_cpes",
]
