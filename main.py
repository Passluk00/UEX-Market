import os
import asyncio
import requests
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime


# ---------- Config ----------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
UEX_BEARER_TOKEN = os.getenv("UEX_BEARER_TOKEN")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 6))  # secondi
UEX_SECRET_KEY = "todo"                                                         # TODO da cambiare

API_NOTIFICATIONS = "https://api.uexcorp.uk/2.0/user_notifications/"


# ---------- Discord Bot ----------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix non serve più, ma resta per compatibilità

# simuliamo una struttura chat in memoria
chat_sessions = {}

@bot.event
async def on_ready():
    await bot.tree.sync()  # registra i comandi slash con Discord
    print(f"✅ Bot connesso come {bot.user}")
    poll_uex_notifications.start()  # avvia il polling

# --- Slash Commands ---
@bot.tree.command(name="lista", description="Mostra tutte le chat attive")
async def lista(interaction: discord.Interaction):
    if not chat_sessions:
        await interaction.response.send_message("📭 Nessuna chat disponibile.")
        return

    msg = "**📋 Chat attive:**\n"
    for person, info in chat_sessions.items():
        msg += f"- **{person}** | Oggetto: {info['oggetto']} | Messaggi: {info['messaggi']} | Non letti: {info['non_letti']}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="rispondi", description="Apri una chat con una persona")
async def rispondi(interaction: discord.Interaction, persona: str):
    if persona not in chat_sessions:
        await interaction.response.send_message(f"⚠️ Nessuna chat trovata con {persona}")
        return
    await interaction.response.send_message(f"✉️ Chat con {persona} aperta. Scrivi il messaggio da inviare.")

@bot.tree.command(name="termina", description="Chiudi la chat con una persona")
async def termina(interaction: discord.Interaction, persona: str):
    if persona in chat_sessions:
        del chat_sessions[persona]
        await interaction.response.send_message(f"✅ Chat con {persona} terminata.")
    else:
        await interaction.response.send_message(f"⚠️ Nessuna chat trovata con {persona}")

@bot.tree.command(name="edit", description="Modifica un oggetto in vendita")
async def edit(interaction: discord.Interaction, id_oggetto: str, prezzo: float):
    # qui potrai collegarti alle API UEX
    await interaction.response.send_message(f"🛠️ Oggetto {id_oggetto} aggiornato con prezzo {prezzo} (mock).")

# ---------- Polling UEX ----------
@tasks.loop(seconds=POLL_INTERVAL)
async def poll_uex_notifications():
    headers = {
    "Authorization": f"Bearer {UEX_BEARER_TOKEN}",
    "secret-key": UEX_SECRET_KEY
}

    try:
        response = requests.get(API_NOTIFICATIONS, headers=headers)
        response.raise_for_status()
        data = response.json()
        notifications = data.get("data", [])

        if notifications:
            channel = bot.get_channel(CHANNEL_ID)
            for notif in notifications:
                sender = notif.get("sender", "Sconosciuto")
                message = notif.get("message", "")
                redir = notif.get("redir", "")
                obj = notif.get("object", None)

                # aggiorna chat_sessions
                if sender not in chat_sessions:
                    chat_sessions[sender] = {"oggetto": obj, "messaggi": 0, "non_letti": 0}
                chat_sessions[sender]["messaggi"] += 1
                chat_sessions[sender]["non_letti"] += 1

                # invia su Discord
                if channel:
                    await channel.send(f"📩 Nuova notifica da **{sender}**: {message}\n↪️ [Dettagli]({redir})")

    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now()}] Errore nel polling UEX: {e}")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)




## 
# 
#   TODO 
#   !- Trovare Secret-Key dal sito UEX CORP.
#   1- Implementare lista di oggetti in vendita
#   2- Rifattorizzare il codice in modo che sia in linea con le direttive
#   3- Segliere Un Logo 
#   4- Capire meglio funzionamento di webhook
#   5- Capire meglio API UEX 
#   6- Implementare nuovi comandi riguardanti chat e gestione inventario
#   
# 
# 
# 
# ##