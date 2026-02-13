"""
Telegram notification service for Gilbert's Yoga Helper.

Sends notifications about new matches after crawl completion.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.
"""
import os
from typing import List, Optional
from urllib.parse import quote

import httpx

from backend.utils.logging import get_logger

logger = get_logger(__name__)

# Telegram configuration from environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Telegram API base URL
TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def is_telegram_configured() -> bool:
    """Check if Telegram bot is configured."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


async def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a message via Telegram bot.

    Args:
        text: Message text (supports HTML formatting)
        parse_mode: "HTML" or "Markdown"

    Returns:
        True if message was sent successfully
    """
    if not is_telegram_configured():
        logger.warning("Telegram not configured - skipping notification")
        return False

    url = f"{TELEGRAM_API_BASE}{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)

            if response.status_code == 200:
                logger.info("Telegram notification sent successfully")
                return True
            else:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                return False

    except httpx.TimeoutException:
        logger.error("Telegram API timeout")
        return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


async def notify_new_matches(
    new_matches: List[dict],
    total_new: int,
    crawl_duration: Optional[int] = None
) -> bool:
    """
    Send notification about new matches found during crawl.

    Args:
        new_matches: List of new match dicts with title, price, url, source
        total_new: Total number of new matches
        crawl_duration: Crawl duration in seconds (optional)

    Returns:
        True if notification was sent
    """
    if not is_telegram_configured():
        return False

    if total_new == 0:
        # Optionally notify even if no new matches
        # For now, skip notification if no new matches
        logger.info("No new matches - skipping Telegram notification")
        return True

    # Build message
    lines = []

    # Header
    if total_new == 1:
        lines.append(f"<b>1 neuer Treffer gefunden!</b>")
    else:
        lines.append(f"<b>{total_new} neue Treffer gefunden!</b>")

    if crawl_duration:
        minutes = crawl_duration // 60
        seconds = crawl_duration % 60
        if minutes > 0:
            lines.append(f"<i>Crawl-Dauer: {minutes}m {seconds}s</i>")
        else:
            lines.append(f"<i>Crawl-Dauer: {seconds}s</i>")

    lines.append("")

    # Show all matches
    for match in new_matches:
        title = match.get("title", "Unbekannt")
        price = match.get("price", "")
        url = match.get("url", "")
        source = match.get("source", "")

        # Truncate long titles
        if len(title) > 50:
            title = title[:47] + "..."

        # Escape HTML special chars
        title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        price_str = f" - {price}" if price else ""
        source_str = f" [{source}]" if source else ""

        lines.append(f"• <a href=\"{url}\">{title}</a>{price_str}{source_str}")

    message = "\n".join(lines)

    # Telegram has a 4096 character limit per message — split if needed
    if len(message) <= 4096:
        return await send_telegram_message(message)

    # Split into multiple messages at line boundaries
    chunks = []
    current_chunk = ""
    for line in lines:
        if current_chunk and len(current_chunk) + len(line) + 1 > 4096:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
    if current_chunk:
        chunks.append(current_chunk)

    success = True
    for chunk in chunks:
        if not await send_telegram_message(chunk):
            success = False
    return success


async def send_test_notification() -> bool:
    """Send a test notification to verify configuration."""
    return await send_telegram_message(
        "<b>Test-Nachricht</b>\n\n"
        "Telegram-Benachrichtigungen funktionieren!"
    )
