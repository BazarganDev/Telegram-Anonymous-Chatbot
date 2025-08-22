# Telegram-Anonymous-Chatbot

<h1 align="center">⚠️ STILL UNDER DEVELOPMENT ⚠️</h1>

## Overview
The Anonymous Telegram Chat Bot is designed for one-to-one random chats while ensuring user anonymity. It allows users to connect with others without revealing their identities, making it a safe space for open conversations.

## Features
- Full Anonymity: Messages are relayed using copy_message, ensuring no usernames or IDs are shown.
- Supports various message types such as text, photos, videos, voice messages and audio.
- Anti-Spam Mechanism: Simple throttle per user to prevent spam.
- Abuse Reporting: You can log a report to SQLite and it will notify the admin about the report.
- Crash-Safe: User states are stored in SQLite; sessions are cleared on restart to avoid ghost links.

## Security Note
The bot does not log user content or IDs unless absolutely necessary. It stores minimal metadata to maintain user privacy.

## Installation
1. Clone the repository:
```bash
~ git clone https://github.com/BazarganDev/Telegram-Anonymous-Chatbot/
~ cd Telegram-Anonymous-Chatbot
```
2. Set up environment variables
Edit `TELEGRAM_TOKEN`, `ADMIN_CHAT_ID` in the `.env` file with your bot token and your Telegram user ID:
```env
TELEGRAM_TOKEN=your-telegram-bot-token
ADMIN_CHAT_ID=your-telegram-userID
DATABASE_PATH=anonchat.db
```
3. Install Dependencies
```
pip install -r requirements.txt
```
4. Run the bot
```
python app.py
```

## Contribution
Contributions are welcome! Please fork the repository and submit a pull request for any enhancements or bug fixes.
