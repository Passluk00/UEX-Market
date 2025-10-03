import os
import aiohttp
import asyncio
import logging
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime
import time
import directory  # contiene API_NOTIFICATIONS

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ---------- Config ----------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 6))  # secondi

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Sessioni utente
user_sessions = {}
last_poll_time = 0.0


# ---------- View Bottone ----------
class OpenThreadButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Apri la tua chat", style=discord.ButtonStyle.primary, custom_id="open_thread_button")
    async def open_thread(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        channel = interaction.channel

        if user_id in user_sessions:
            await interaction.response.send_message("Hai già un thread attivo!", ephemeral=True)
            return

        thread = await channel.create_thread(
            name=f"Chat {interaction.user.name}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(interaction.user)

        user_sessions[user_id] = {
            "thread_id": thread.id,
            "notifications": []
        }

        await thread.send(
            f"""👋 Ciao {interaction.user.name}!🔑 Ecco come ottenere Bearer Token e Secret Key su UEX

👉 Ottenere il Bearer Token
1- Accedi al sito UEX con il tuo account.
2- Scorri fino in fondo alla pagina e clicca sul link API.
3- Si aprirà la documentazione delle API: clicca al centro sul link MY APPS.
4- Premi il pulsante Get Started Now.
5- Accetta i Termini e Condizioni.
6- Crea una nuova app (il nome è a piacimento, ad esempio "Discord Bot").
7- Una volta creata, scorri in fondo alla pagina: troverai il tuo Bearer Token. Copialo.

👉 Ottenere la Secret Key
1- Clicca sul tuo profilo in alto a destra.
2- Nella scheda che si apre troverai la tua Secret Key. Copiala.

👉 Inserire le chiavi nel bot
Nel tuo thread privato su Discord, incolla le due chiavi con questo formato:
bearer:TUO_BEARER_TOKEN secret:TUA_SECRET_KEY

⚠️ Nota Importante:
Non condividere queste chiavi con nessuno.
Il bot le userà solo per accedere alle tue notifiche personali su UEX.
"""
        )
        await interaction.response.send_message("✅ Thread creato! Controlla il tuo thread privato.", ephemeral=True)


# ---------- Eventi Bot ----------
@bot.event
async def on_ready():
    logging.info(f"✅ Bot connesso come {bot.user}")
    await bot.tree.sync()
    logging.info("✅ Commands synchronized.")

    bot.add_view(OpenThreadButton())

    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.components:
                logging.info("🔘 Pulsante già presente, riassociato.")
                break
        else:
            view = OpenThreadButton()
            await channel.send(
                "Crea la tua chat privata con UEX!\nClicca il pulsante qui sotto per avviare una conversazione personale e ricevere le tue notifiche UEX",
                view=view
            )
            logging.info("🔘 Pulsante creato.")

    if not poll_all_users.is_running():
        poll_all_users.start()


@bot.event
async def on_thread_delete(thread: discord.Thread):
    to_remove = None
    for user_id, session in user_sessions.items():
        if session.get("thread_id") == thread.id:
            to_remove = user_id
            break
    if to_remove:
        del user_sessions[to_remove]
        logging.info(f"🗑️ Thread eliminato, rimossa sessione per utente {to_remove}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    content = message.content.strip()

    if user_id in user_sessions:
        session = user_sessions[user_id]

        # Se non ha ancora inserito le chiavi
        if "bearer_token" not in session or "secret_key" not in session:
            if content.startswith("bearer:") and "secret:" in content:
                try:
                    bearer = content.split("bearer:")[1].split("secret:")[0].strip()
                    secret = content.split("secret:")[1].strip()

                    bearer = bearer.replace("<", "").replace(">", "")
                    secret = secret.replace("<", "").replace(">", "")

                    user_sessions[user_id]["bearer_token"] = bearer
                    user_sessions[user_id]["secret_key"] = secret
                    await message.channel.send("✅ Credenziali salvate! Inizio a controllare le notifiche...")
                except Exception:
                    await message.channel.send("❌ Formato non corretto. Usa: `bearer:<token> secret:<secret_key>`")
            else:
                await message.channel.send("❌ Formato non corretto. Usa: `bearer:<token> secret:<secret_key>`")
            return

    await bot.process_commands(message)


# ---------- Funzione polling per singolo utente ----------
async def fetch_notifications(user_id, session):
    thread = bot.get_channel(session["thread_id"])
    if not thread:
        logging.warning(f"❌ Thread mancante per utente {user_id}, elimino la sessione.")
        user_sessions.pop(user_id, None)
        return

    headers = {
        "Authorization": f"Bearer {session['bearer_token']}",
        "secret-key": session["secret_key"]
    }

    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(directory.API_NOTIFICATIONS, headers=headers) as resp:
                if resp.status != 200:
                    logging.error(f"⚠️ Errore {resp.status} per utente {user_id}")
                    return

                data = await resp.json()
                notifications = data.get("data", [])

                for notif in notifications:
                    notif_id = notif.get("id")
                    if notif_id in session["notifications"]:
                        continue

                    raw_message = notif.get("message", "")
                    redir = notif.get("redir", "")

                    if ":" in raw_message:
                        sender, text = raw_message.split(":", 1)
                        sender = sender.strip()
                        text = text.strip()
                    else:
                        sender = "Sconosciuto"
                        text = raw_message

                    session["notifications"].append(notif_id)

                    embed = discord.Embed(
                        title="📩 Nuova notifica",
                        description=f"👤 Mittente: **{sender}**\n💬 {text}\n🔗 [Vai alla chat](https://uexcorp.space/{redir})",
                        color=discord.Color.blue()
                    )
                    await thread.send(embed=embed)

    except Exception as e:
        logging.exception(f"💥 Errore polling utente {user_id}: {e}")


# ---------- Polling globale ----------
@tasks.loop(seconds=POLL_INTERVAL)
async def poll_all_users():
    global last_poll_time
    start = time.perf_counter()

    users_count = len(user_sessions)
    logging.info(f"🔄 Inizio polling per {users_count} utenti")

    tasks_list = [fetch_notifications(user_id, session) for user_id, session in list(user_sessions.items())]
    await asyncio.gather(*tasks_list, return_exceptions=True)

    elapsed = time.perf_counter() - start
    last_poll_time = elapsed
    logging.info(f"✅ Polling completato in {elapsed:.2f}s per {users_count} utenti")


# ---------- Comando /stats ----------
@bot.tree.command(name="stats", description="Mostra statistiche del bot")
@app_commands.checks.has_permissions(manage_guild=True)
async def stats(interaction: discord.Interaction):
    users_count = len(user_sessions)
    threads_active = sum(1 for u in user_sessions.values() if "thread_id" in u)

    embed = discord.Embed(
        title="📊 Statistiche Bot",
        color=discord.Color.green()
    )
    embed.add_field(name="👥 Utenti attivi", value=str(users_count), inline=True)
    embed.add_field(name="💬 Threads attivi", value=str(threads_active), inline=True)
    embed.add_field(name="⏱️ Ultimo polling", value=f"{last_poll_time:.2f} sec", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------- Run Bot ----------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
