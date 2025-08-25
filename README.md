# Telegram-Anonymous-Chatbot

<h1 align="center">⚠️ STILL UNDER DEVELOPMENT ⚠️</h1>

## Overview
The Anonymous Telegram Chat Bot is designed for one-to-one random chats while ensuring user anonymity. It allows users to connect with others without revealing their identities, making it a safe space for open conversations.

## Features
- Full anonymity: messages are relayed with copy_message (no username/ID shown).
- Matchmaking: /find pairs users; /stop ends; /next finds a new partner.
- Supports most message types: text, photos, videos, voice, documents, stickers, locations, etc.
- Simple anti-spam throttle per user.
- Abuse reporting: /report logs a report to SQLite; optional ADMIN_CHAT_ID notified.
- Crash-safe: user states kept in SQLite; on restart, sessions are cleared to avoid ghost links.
- Clean, typed, and structured with python-telegram-bot v21+ (async API).

## Security Note
Never log user content or IDs unless you must. This bot stores minimal metadata.

## Installation
1. Clone the repository:
   ```bash
   ~ git clone https://github.com/BazarganDev/Telegram-Anonymous-Chatbot/
   ~ cd Telegram-Anonymous-Chatbot
   ```
2. Set up environment variables:<br>
   Edit `TELEGRAM_TOKEN`, `ADMIN_CHAT_ID` in the `.env` file with your bot token and your Telegram user ID:
   ```env
   TELEGRAM_TOKEN=your-telegram-bot-token (Get your own bot token with @BotFather in Telegram)
   ADMIN_CHAT_ID=your-telegram-userID
   DATABASE_PATH=anonchat.db
   ```
3. Install Dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run the bot:
   ```
   python app.py
   ```

## Contribution
Contributions are welcome! Please fork the repository and submit a pull request for any enhancements or bug fixes.
