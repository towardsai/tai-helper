from __future__ import annotations

import os

os.environ["HELPER_ALLOWED_ORIGINS"] = (
    "https://towardsai.com,https://www.towardsai.com,"
    "https://academy.towardsai.net,https://towardsai.net,"
    "https://www.towardsai.net"
)
os.environ["HELPER_ALLOWED_HOSTS"] = (
    "towardsai.com,www.towardsai.com,academy.towardsai.net,"
    "towardsai.net,www.towardsai.net"
)
os.environ["HELPER_SITE_WIDE_HOSTS"] = "towardsai.com,www.towardsai.com"
