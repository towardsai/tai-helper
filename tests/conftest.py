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

# Pin the model configuration too. These default from the environment, so a
# developer pointing their .env at a different gateway or model would otherwise
# fail assertions that have nothing to do with their change.
os.environ["HELPER_PRIMARY_BASE_URL"] = "https://openrouter.ai/api/v1"
os.environ["HELPER_PRIMARY_MODEL"] = "deepseek/deepseek-v4-flash"
os.environ["HELPER_PRIMARY_REASONING"] = "false"
os.environ["HELPER_FALLBACK_MODEL"] = "gemini-3.7-flash"
os.environ["HELPER_GEMINI_THINKING_BUDGET"] = "0"
os.environ["HELPER_MAX_OUTPUT_TOKENS"] = "420"
