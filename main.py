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



# ---------- SESSIONE HTTP GLOBALE ----------
aiohttp_session = None
semaphore = asyncio.Semaphore(5)  # max 5 utenti in parallelo



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
    
    global aiohttp_session
    if aiohttp_session is None:
        aiohttp_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        logging.info("🌐 Sessione aiohttp inizializzata")

    
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

# ---------- Funzione per rispondere a un messaggio UEX ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    user_id = message.author.id
    content = message.content.strip()

    # Gestione iniziale credenziali
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

        # ---------- Se l'utente sta rispondendo a una notifica ----------
        if message.reference and message.reference.resolved:
            replied_msg = message.reference.resolved

            # Trova l'hash nel messaggio originale (presente nel link embed)
            embed = replied_msg.embeds[0] if replied_msg.embeds else None
            if embed and embed.description and "https://uexcorp.space/" in embed.description:
                try:
                    redir_part = embed.description.split("https://uexcorp.space/")[1]
                    if "hash/" in redir_part:
                        notif_hash = redir_part.split("hash/")[1].split(")")[0]
                    else:
                        notif_hash = None
                except Exception:
                    notif_hash = None
            else:
                notif_hash = None

            if not notif_hash:
                await message.channel.send("❌ Impossibile trovare l'hash della notifica da questo messaggio.")
                return

            # Prepara la richiesta API
            headers = {
                "Authorization": f"Bearer {session['bearer_token']}",
                "secret-key": session["secret_key"],
                "Content-Type": "application/json"
            }

            payload = {
                "is_production": 1,
                "hash": notif_hash,
                "message": content
            }

            try:
                async with aiohttp_session.post(directory.API_POST_MESSAGE, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        await message.channel.send("✅ Risposta inviata correttamente a UEX!")
                        print(f"❌payload: hash: {notif_hash}, message: {content}")
                        logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✉️ Utente {user_id} ha risposto alla notifica {notif_hash}")
                    else:
                        text = await resp.text()
                        await message.channel.send(f"⚠️ Errore nell’invio ({resp.status}): {text[:200]}")
                        logging.warning(f"Errore UEX reply {resp.status} per utente {user_id}: {text}")
            except Exception as e:
                await message.channel.send(f"💥 Errore di connessione: {e}")
                logging.exception(f"💥 Errore durante l'invio reply utente {user_id}: {e}")

    await bot.process_commands(message)






# ---------- FUNZIONE POLLING PER SINGOLO UTENTE (con logging dettagliato) ----------
async def fetch_notifications(user_id, session):
    global aiohttp_session

    async with semaphore:
        thread = bot.get_channel(session.get("thread_id"))
        if not thread:
            logging.warning(f"❌ Thread mancante per utente {user_id}, elimino la sessione.")
            user_sessions.pop(user_id, None)
            return

        headers = {
            "Authorization": f"Bearer {session['bearer_token']}",
            "secret-key": session["secret_key"]
        }

        retries = 3
        for attempt in range(retries):
            start_time = time.perf_counter()
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Inizio polling utente {user_id} (tentativo {attempt+1})")

            try:
                async with aiohttp_session.get(directory.API_NOTIFICATIONS, headers=headers) as resp:
                    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🌐 Richiesta API inviata (status={resp.status}) per utente {user_id}")

                    if resp.status != 200:
                        text = await resp.text()
                        logging.warning(f"⚠️ Errore API UEX {resp.status} per utente {user_id}: {text[:200]}")
                        return

                    data = await resp.json()
                    notifications = data.get("data", [])
                    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] 📦 Ricevute {len(notifications)} notifiche per utente {user_id}")

                    for notif in notifications:
                        notif_id = notif.get("id")

                        # Evita duplicati
                        if any(n.get("id") == notif_id for n in session.get("notifications", [])):
                            continue

                        raw_message = notif.get("message", "")
                        redir = notif.get("redir", "")
                        notif_hash = None

                        if "hash/" in redir:
                            notif_hash = redir.split("hash/")[-1]

                        # Parsing messaggio
                        if ":" in raw_message:
                            sender, text = raw_message.split(":", 1)
                            sender = sender.strip()
                            text = text.strip()
                        else:
                            sender = "Sconosciuto"
                            text = raw_message

                        # Salva la notifica
                        session.setdefault("notifications", []).append({
                            "id": notif_id,
                            "hash": notif_hash,
                            "message": raw_message
                        })

                        print(f"id: {notif_id}")
                        print(f"hash: {notif_hash}")
                        print(f"Message: {raw_message}")
                        
                        # LOG PRIMA DELL'INVIO SU DISCORD
                        logging.info(
                            f"[{datetime.now().strftime('%H:%M:%S')}] 📨 Nuova notifica utente {user_id} - Mittente: {sender}, Messaggio: {text[:60]}..."
                        )

                        # Invia nel thread Discord
                        embed = discord.Embed(
                            title="📩 Nuova notifica",
                            description=f"👤 Mittente: **{sender}**\n💬 {text}\n🔗 [Apri su UEX](https://uexcorp.space/{redir})",
                            color=discord.Color.blue()
                        )
                        await thread.send(embed=embed)

                        # LOG DOPO L'INVIO
                        logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Messaggio inviato su Discord per utente {user_id}")

                    elapsed = time.perf_counter() - start_time
                    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] ⏱️ Polling utente {user_id} completato in {elapsed:.2f}s")
                    return  # success

            except asyncio.TimeoutError:
                logging.warning(f"[{datetime.now().strftime('%H:%M:%S')}] ⏳ Timeout API UEX per utente {user_id} (tentativo {attempt+1}/{retries})")
                await asyncio.sleep(1)
            except Exception as e:
                logging.exception(f"[{datetime.now().strftime('%H:%M:%S')}] 💥 Errore polling utente {user_id}: {e}")
                await asyncio.sleep(1)
        else:
            logging.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Polling fallito per utente {user_id} dopo {retries} tentativi.")



# ---------- POLLING GLOBALE ----------
@tasks.loop(seconds=POLL_INTERVAL)
async def poll_all_users():
    global last_poll_time
    start = time.perf_counter()

    users_count = len(user_sessions)
    if users_count == 0:
        logging.info("🔄 Nessun utente attivo, salto polling.")
        return

    logging.info(f"🔄 Inizio polling per {users_count} utenti")

    tasks_list = [asyncio.create_task(fetch_notifications(uid, sess)) for uid, sess in list(user_sessions.items())]
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


# ---------- Comando /add ----------
@bot.tree.command(name="add", description="Aggiunge il bottone per creare le chat private in un canale")
@app_commands.describe(canale="Il canale dove inviare il messaggio con il bottone")
@app_commands.checks.has_permissions(manage_guild=True)
async def add_button(interaction: discord.Interaction, canale: discord.TextChannel):
    """Comando slash per aggiungere il bottone in un canale specifico."""
    try:
        view = OpenThreadButton()
        await canale.send(
            "Crea la tua chat privata con UEX!\n"
            "Clicca il pulsante qui sotto per avviare una conversazione personale e ricevere le tue notifiche UEX",
            view=view
        )
        await interaction.response.send_message(f"✅ Bottone aggiunto in {canale.mention}", ephemeral=True)
        logging.info(f"🔘 Bottone aggiunto manualmente da {interaction.user} in {canale.name}")
    except Exception as e:
        logging.exception("💥 Errore nell'aggiunta del bottone con /add")
        await interaction.response.send_message("❌ Errore durante l'aggiunta del bottone.", ephemeral=True)




# ---------- Run Bot ----------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
