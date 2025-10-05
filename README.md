# Discord UEX Notification Bot

[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)  
[![discord.py](https://img.shields.io/badge/discord.py-v2.5+-blue?logo=discord&logoColor=white)](https://pypi.org/project/discord.py/)  
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---


## ✨ Description

This Discord bot allows users to receive **real-time notifications** from UEX directly in private threads on Discord.  
Users can create a personal thread, add their UEX API credentials, and receive notifications about messages, negotiations, and updates.

Additionally, users can **reply to notifications directly from Discord**. Replies are sent back to UEX via the API, enabling two-way communication without leaving Discord.

---


## 🛠 Features

- 🧵 **Private Threads per User:** Each user gets a dedicated thread for notifications.  
- 🔑 **API Credential Management:** Users input their Bearer Token and Secret Key securely.  
- ⏱ **Real-Time Notification Polling:** Fetch new messages asynchronously from UEX API.  
- 💬 **Reply to Notifications:** Users reply directly in Discord; bot sends the reply via UEX API.  
- 📋 **Error Handling & Logging:** Logs include polling, notifications, replies, and API errors.  
- 📊 **Bot Stats Command:** `/stats` shows active users, threads, and last polling duration.
- 💾 **Automatically save and persist** user sessions in `user_sessions.json`.
- 🔁 **Automatically restore** sessions when the bot starts.
---


## 📦 Requirements

- Python 3.11+
- discord.py
- aiohttp
- python-dotenv
- Discord bot with `message_content` intent enabled
- Discord channel ID for the “Open Thread” button
- Access to UEX API with valid Bearer Token and Secret Key

Optional: `logging` module for debug/log files.

---


## ⚙️ Installation

1. Clone this repository:

```bash
git clone <repository_url>
cd <repository>
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a .env file in the root directory with the following:
  
```bash
DISCORD_TOKEN=your_discord_bot_token
POLL_INTERVAL=6         #polling interval
```
4. Run the Bot

```bash
python bot.py
```

---


## **🚀 Usage**

1. Create a thread:

    Click the “Open Thread” button in the configured Discord channel.

2. Add credentials:
    
    Send your API credentials in your private thread:

```bash
bearer:<TOKEN> secret:<SECRET>
```

3. Receive notifications:
    
    New notifications from UEX appear in your thread as Discord embeds.

4. Reply to notifications:

   - Use Discord’s “Reply” feature on a notification embed.
   - Type your message.
   - The bot sends it to UEX automatically and confirms success.

5. Check bot stats:

    Use `/stats` to see active users, active threads, and last polling duration.

---


## **📄 Logging**

The bot logs the following to bot.log and console:

- Polling start and completion per user
- Notifications received
- Replies sent
- API errors and timeouts

---


## **⏱ Expected Behavior**

- Notifications appear almost instantly in Discord after being available in UEX.
- Replies sent from Discord appear immediately in UEX.
- Errors or delays are logged for troubleshooting.

---


## **⚠️ Disclaimer**

⚠️ If notifications do not appear instantly in Discord, this is due to delays in the UEX API.
The bot fetches notifications as soon as they are available from UEX, but the API may take several minutes to propagate new messages.