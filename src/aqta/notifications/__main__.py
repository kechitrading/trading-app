"""``python -m aqta.notifications``: the bot now runs inside the API process.

Approvals must share the API's order gateway, paper broker and kill switch, so the Telegram bot is
polled by the API (``uvicorn aqta.api:create_app --factory``). This entry point only explains that.
"""

from __future__ import annotations

if __name__ == "__main__":
    print(  # noqa: T201
        "The Telegram bot runs inside the API process. Start the API "
        "(uvicorn aqta.api:create_app --factory) with TELEGRAM_POLLING=true."
    )
