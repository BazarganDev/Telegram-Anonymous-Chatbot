"""
Anonymous Telegram Chat Bot (one-to-one random chat)
----------------------------------------------------


Features:
- Full anonymity: messages are relayed with copy_message (no username/ID shown).
- Matchmaking: /find pairs users; /stop ends; /next finds a new partner.
- Supports most message types: text, photos, videos, voice, and audio.
- Simple anti-spam throttle per user.
- Abuse reporting: /report logs a report to SQLite; optional ADMIN_CHAT_ID notified.
- Crash-safe: user states kept in SQLite; on restart, sessions are cleared to avoid ghost links.
- Clean, typed, and structured with python-telegram-bot v21+ (async API).

Security Note:
- Never log user content or IDs unless you must. This bot stores minimal metadata.

Link to the Github:
https://github.com/BazarganDev/Telegram-Anonymous-Chatbot
"""

# Import necessary modules.
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.error import Forbidden, BadRequest, NetworkError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    AIORateLimiter,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# Load environment variables from `.env` file (token, admin ID, db path)
load_dotenv()

# Configuration & Logging
# Configuration for the bot toke, admin notifications, and SQLite database path.
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Please set TELEGRAM_TOKEN in the environment.")

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
DB_PATH = Path(os.environ.get("DATABASE_PATH", "./anonchat.db")).resolve()

# Logging is configured at 'INFO' level for runtime diagnostics.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("anon-bot")


# Database
# A SQLite helper encapsulates user states and reports.
class DB:
    """
    Lightweight SQLite database wrapper for user matchmaking state and abuse reports.
    """
    def __init__(self, path: Path):
        self.path = path
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        # Table for users and matchmaking states
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                in_queue INTEGER NOT NULL DEFAULT 0,
                partner_id INTEGER,
                updated_at REAL NOT NULL
            );
            """
        )
        # Table for abuse reports
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                partner_id INTEGER,
                reason TEXT,
                created_at REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def set_queue(self, user_id: int, in_queue: bool):
        """
        Mark user as searching for a partner or not.
        """
        self._conn.execute(
            "INSERT INTO users(user_id, in_queue, partner_id, updated_at) VALUES(?,?,NULL,?)\n"
            "ON CONFLICT(user_id) DO UPDATE SET in_queue=excluded.in_queue, partner_id=NULL, updated_at=excluded.updated_at",
            (user_id, int(in_queue), time.time()),
        )
        self._conn.commit()

    def set_partner(self, a: int, b: Optional[int]):
        """
        Set two users as partners (or clear if b=None).
        """
        now = time.time()
        pairs = [(a, b)]
        if b is not None:
            pairs.append((b, a))
        for u, p in pairs:
            self._conn.execute(
                "INSERT INTO users(user_id,in_queue,partner_id,updated_at) VALUES(?,0,?,?)\n"
                "ON CONFLICT(user_id) DO UPDATE SET in_queue=0, partner_id=excluded.partner_id, updated_at=excluded.updated_at",
                (u, p, now),
            )
        self._conn.commit()

    def clear_all_sessions(self):
        """
        Clear all active sessions (called on startup for crash safety).
        """
        self._conn.execute(
            "UPDATE users SET partner_id=NULL, in_queue=0, updated_at=?", (time.time(),)
        )
        self._conn.commit()

    def get_partner(self, user_id: int) -> Optional[int]:
        """
        Return partner ID if user is in a session, else None.
        """
        cur = self._conn.execute(
            "SELECT partner_id FROM users WHERE user_id=?", (user_id,)
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def is_in_queue(self, user_id: int) -> bool:
        """
        Return True if user is currently waiting for a match.
        """
        cur = self._conn.execute(
            "SELECT in_queue FROM users WHERE user_id=?", (user_id,)
        )
        row = cur.fetchone()
        return bool(row and row[0])

    def pick_waiting_peer(self, exclude: int) -> Optional[int]:
        """
        Pick the oldest user in queue, excluding the given user.
        """
        cur = self._conn.execute(
            "SELECT user_id FROM users WHERE in_queue=1 AND user_id<>? ORDER BY updated_at ASC LIMIT 1",
            (exclude,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None

    def enqueue_if_missing(self, user_id: int):
        """
        Ensure user exists in DB, creating entry if missing.
        """
        cur = self._conn.execute(
            "SELECT user_id FROM users WHERE user_id=?", (user_id,)
        )
        if not cur.fetchone():
            self._conn.execute(
                "INSERT INTO users(user_id,in_queue,partner_id,updated_at) VALUES(?,?,NULL,?)",
                (user_id, 0, time.time()),
            )
            self._conn.commit()

    def create_report(self, reporter_id: int, partner_id: Optional[int], reason: str):
        """
        Store an abuse report in DB.
        """
        self._conn.execute(
            "INSERT INTO reports(reporter_id,partner_id,reason,created_at) VALUES(?,?,?,?)",
            (reporter_id, partner_id, reason[:1000], time.time()),
        )
        self._conn.commit()


DBI = DB(DB_PATH)


# Message‐Throttling State
# To prevent spam or floods, each user must wait a minimum interval between messages.
@dataclass
class Throttle:
    last_sent_at: float = 0.0


class State:
    """
    Tracks per-user message timestamps for flood prevention.
    """
    def __init__(self):
        self.throttle: dict[int, Throttle] = {}

    def may_send(self, user_id: int, min_interval: float = 0.7) -> bool:
        """
        Return True if user may send a message (enforces min interval).
        """
        t = self.throttle.setdefault(user_id, Throttle())
        now = time.time()
        if now - t.last_sent_at >= min_interval:
            t.last_sent_at = now
            return True
        return False


STATE = State()


# Helper Functions
async def send_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """
    Send a message safely, ignoring Forbidden errors if user blocked bot.
    """
    try:
        await context.bot.send_message(
            chat_id,
            text,
            parse_mode=constants.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Forbidden:
        # Bot is blocked by user
        pass


async def end_session(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, notify_other: bool = True
):
    """
    End a chat session for a user (and notify partner if applicable).
    """
    partner = DBI.get_partner(user_id)
    if partner:
        # Clear both sides of the pairing
        DBI.set_partner(user_id, None)
        DBI.set_partner(partner, None)
        if notify_other:
            await send_safe(context, partner, "<i>Your partner left the chat.</i>")
    else:
        # No partner, just clear this user
        DBI.set_partner(user_id, None)


# Handlers
WELCOME = (
    "<b>Anonymous Chat</b>\n\n"
    "Commands:\n"
    "- /find: find a partner\n"
    "- /stop: end current chat\n"
    "- /next: end current chat and find a new partner\n"
    "- /report [reason]: report partner to admin\n"
    "- /help: show this message\n\n"
    "YOUR IDENTITY IS HIDDEN BECAUSE THIS BOT USES `copy_message`. BE KIND. NO SPAM, HATE, OR ILLEGAL CONTENT IS ALLOWED!"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /start command.

    Ensures the user exists in the database and sends a welcome message
    listing available commands and safety reminders.
    """
    user_id = update.effective_user.id
    DBI.enqueue_if_missing(user_id)
    await update.effective_message.reply_html(WELCOME, disable_web_page_preview=True)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /help command.

    Repeats the welcome message to remind the user of all commands
    and how to use the bot safely.
    """
    await update.effective_message.reply_html(WELCOME, disable_web_page_preview=True)


async def find_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /find command.

    1. Ensures the user exists in DB.
    2. Checks if the user is already in a session.
       - If yes, prompts them to /stop or /next first.
    3. If not in session, attempts to find a waiting partner.
       - If a partner is found, immediately pairs them and notifies both.
       - If no partner is available, sets the user in queue and informs them.
    """
    user_id = update.effective_user.id
    DBI.enqueue_if_missing(user_id)
    if DBI.get_partner(user_id):
        await update.effective_message.reply_html(
            "You're already connected. Use /stop or /next."
        )
        return
    # Try to match
    peer = DBI.pick_waiting_peer(exclude=user_id)
    if peer is not None:
        DBI.set_partner(user_id, peer)
        await send_safe(context, peer, "<i>Matched! You're now connected. Say hi.</i>")
        await update.effective_message.reply_html(
            "Matched! You're now connected. Say hi."
        )
    else:
        DBI.set_queue(user_id, True)
        await update.effective_message.reply_html(
            "Searching for a partner… you'll be matched automatically."
        )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /stop command.

    Ends the current chat session for the user:
    1. If the user is not in a chat, informs them to use /find.
    2. Otherwise, clears the session for both user and partner.
    3. Updates the user's queue state to not searching.
    """
    user_id = update.effective_user.id
    if not DBI.get_partner(user_id) and not DBI.is_in_queue(user_id):
        await update.effective_message.reply_html(
            "You are not in a chat. Use /find to start."
        )
        return
    # Tear down the session for both sides
    await end_session(context, user_id)
    # Update queue state after clearing pairing
    DBI.set_queue(user_id, False)
    await update.effective_message.reply_html(
        "Chat ended. Use /find to meet someone new."
    )


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /next command.

    Ends the current session and immediately attempts to find a new partner:
    1. Clears existing session and queue state.
    2. Attempts to match user with a waiting partner.
       - If matched, notifies both users.
       - If no partner is available, puts the user back in queue.
    """
    user_id = update.effective_user.id
    # Ensure user is not queued during session teardown
    DBI.set_queue(user_id, False)
    await end_session(context, user_id)
    # Immediately find a new partner
    peer = DBI.pick_waiting_peer(exclude=user_id)
    if peer is not None:
        DBI.set_partner(user_id, peer)
        await send_safe(context, peer, "<i>Matched! You're now connected. Say hi.</i>")
        await update.effective_message.reply_html(
            "Matched! You're now connected. Say hi."
        )
    else:
        DBI.set_queue(user_id, True)
        await update.effective_message.reply_html(
            "Searching for a partner… you'll be matched automatically."
        )


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for /report command.

    1. Records a report in the database.
    2. Notifies the user that their report was submitted.
    3. Optionally notifies the admin chat with details.
    """
    user_id = update.effective_user.id
    partner = DBI.get_partner(user_id)
    reason = " ".join(context.args) if context.args else "[no reason given]"
    DBI.create_report(user_id, partner, reason)
    await update.effective_message.reply_html("Report submitted. Thank you.")
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                int(ADMIN_CHAT_ID),
                f"\u26a0\ufe0f Report\nReporter: <code>{user_id}</code>\nPartner: <code>{partner}</code>\nReason: {reason}",
                parse_mode=constants.ParseMode.HTML,
            )
        except Exception:
            logger.exception("Failed to notify admin about report")


# Generic relay for almost all content types
SUPPORTED = filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.AUDIO


async def relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generic relay handler for almost all supported message types.

    1. Checks if the user is in a chat session.
       - If not, prompts them to use /find.
    2. Checks throttling to prevent spam.
    3. Copies the message to the partner while preserving anonymity.
    4. Handles errors gracefully:
       - Forbidden: partner blocked bot -> ends session.
       - BadRequest / NetworkError: logs warnings without crashing.
    """
    user_id = update.effective_user.id
    partner = DBI.get_partner(user_id)
    if not partner:
        await update.effective_message.reply_html(
            "You're not connected. Use /find to get a partner."
        )
        return
    if not STATE.may_send(user_id):
        return  # Soft throttle
    try:
        # copy_message preserves content without attribution; truly anonymous.
        await context.bot.copy_message(
            chat_id=partner,
            from_chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
    except Forbidden:
        # Partner blocked or stopped the bot — end session gracefully
        await end_session(context, user_id)
        await update.effective_message.reply_html(
            "Your partner is unavailable. Use /find to match again."
        )
    except BadRequest as e:
        logger.warning("BadRequest while copying message: %s", e)
    except NetworkError:
        logger.warning("Network issue while relaying message")


# App Lifecycle
async def post_init(app: Application):
    """
    Post-initialization hook.

    Clears all active sessions on startup to avoid ghost links
    caused by crashes or redeploys.
    """
    DBI.clear_all_sessions()
    logger.info("Database ready at %s", DB_PATH)


def _build_app() -> Application:
    """
    Build the Telegram bot application instance.

    Configures:
    - Token
    - Rate limiter
    - Post-init cleanup
    """
    return (
        ApplicationBuilder()
        .token(TOKEN)
        .rate_limiter(AIORateLimiter(max_retries=2))
        .post_init(post_init)
        .build()
    )


async def main():
    """
    Main entry point of the bot.

    1. Builds the application.
    2. Registers all command and message handlers.
    3. Runs polling indefinitely.
    """
    app = _build_app()
    # Register command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("find", find_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    # Register relay handler for supported types
    app.add_handler(MessageHandler(SUPPORTED, relay))

    await app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
