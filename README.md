# Discord UEX Notification Bot

[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)  
[![discord.py](https://img.shields.io/badge/discord.py-v2.5+-blue?logo=discord&logoColor=white)](https://pypi.org/project/discord.py/)  
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---


## ✨ Description

The Discord UEX Notification Bot connects your UEX account directly with Discord, allowing users to receive real-time negotiation updates and exchange messages seamlessly.

Each user has a private thread where the bot delivers negotiation messages, listings updates, and system notifications.
Users can also reply directly from Discord, and the bot automatically sends their message back to UEX via webhook.

This version includes a database system, real-time webhook handling, negotiation linking between users.

---


## 🛠 Features

- 🧵 **Private Threads per User:** Each user gets a dedicated thread for notifications.  
- 🔑 **API Credential Management:** Users input their Bearer Token and Secret Key securely.  
- 🔗 **Webhook-Driven Communication:** Receives and processes UEX webhooks instantly — no polling delays.
- 🧠 **Negotiation Link Mapping:** Automatically links buyers and sellers using the negotiation hash to enable two-way messaging.
- 💬 **Two-Way Messaging:** Messages from either side of a negotiation are routed to the other user in real-time.
- 🧾 **Persistent SQLite Database:** Stores user sessions, negotiation links, and webhook data in a local SQLite database.
- ⚙️ **Automatic Session Recovery:** On restart, the bot restores active user sessions and linked negotiations.
- 📊 **Logging & Debugging:** Detailed logs for every webhook event, negotiation start/end, and message transfer.
- 🧠 **Smart Negotiation Routing:** Automatically determines the correct recipient (buyer/seller) for each reply based on stored negotiation data. 
- 📋 **Error Handling:** Logs include polling, notifications, replies, and API errors.  
- 📊 **Bot Stats Command:** `/stats` shows active users, threads, and last polling duration.

---


## 🧰 Tech Stack


| Component                  | Technology                         |
| -------------------------- | ---------------------------------- |
| **Language**               | Python 3.11+                       |
| **Discord SDK**            | discord.py v2.5+                   |
| **Async HTTP**             | aiohttp                            |
| **Database**               | aiosqlite (SQLite)                 |
| **Environment Management** | python-dotenv                      |
| **Hosting / Gateway**      | Nginx + FastAPI (Webhook Endpoint) |


---


## ⚙️ Installation

1. Clone this repository:

  ```bash
  git clone https://github.com/Passluk00/UEX-Market.git/ 
  cd UEX-Market 
  ```

2. Install dependencies:

  ```bash
  pip install -r requirements.txt
  ```

3. Create a .env file in the root directory with the following:
  
  ```bash
  DISCORD_TOKEN=your_discord_bot_token
  DB_PATH=your_database_path
  LOG_PATH=your_log_path
  TUNNEL_URL=             #public ip or url
  POLL_INTERVAL=6         #polling interval
  ```

4. Run the Bot

  ```bash
  python bot.py
  ```

---


## **🚀 Usage**

0. Add the Button to a Channel

   Type this command to add a button to a specific channel

   ```bash
   /add channel_name  
   ```


2. Create a thread:

    Click the “Open Thread” button in the configured Discord channel.

3. Add credentials:
    
    Send your API credentials in your private thread:

    ```bash
    bearer:<TOKEN> secret:<SECRET> username:<uex_username>
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
The bot get notifications as soon as they are available from UEX, but the API may take several minutes to propagate new messages.
