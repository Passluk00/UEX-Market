import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import uvicorn

# ---------- Config ----------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))

# ---------- Discord Bot ----------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix non serve più, ma resta per compatibilità

# simuliamo una struttura chat in memoria
chat_sessions = {}

@bot.event
async def on_ready():
    await bot.tree.sync()  # registra i comandi slash con Discord
    print(f"✅ Bot connesso come {bot.user}")

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

# ---------- FastAPI Webhook ----------
app = FastAPI()

@app.post("/webhook")
async def webhook_listener(request: Request):
    data = await request.json()
    print("📩 Ricevuto webhook:", data)

    # esempio: salvo notifiche in chat_sessions
    persona = data.get("sender", "sconosciuto")
    oggetto = data.get("item", "N/A")
    if persona not in chat_sessions:
        chat_sessions[persona] = {"oggetto": oggetto, "messaggi": 0, "non_letti": 0}
    chat_sessions[persona]["messaggi"] += 1
    chat_sessions[persona]["non_letti"] += 1

    # invio su Discord
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(f"📩 Nuovo messaggio da **{persona}** sull'oggetto **{oggetto}**")
    return {"status": "ok"}

# ---------- Avvio Discord + Webhook ----------
async def start_bot_and_webhook():
    config = uvicorn.Config(app, host="0.0.0.0", port=WEBHOOK_PORT, log_level="info")
    server = uvicorn.Server(config)

    loop = asyncio.get_event_loop()
    bot_task = loop.create_task(bot.start(DISCORD_TOKEN))
    server_task = loop.create_task(server.serve())

    await asyncio.wait([bot_task, server_task])

if __name__ == "__main__":
    asyncio.run(start_bot_and_webhook())




## 
# 
#   TODO 
# 
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