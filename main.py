import os
import json
import aiohttp
import asyncio
import logging
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime
import time
import directory  # contiene ALL_API_URL


# ---------- FILE DI SALVATAGGIO ----------
SESSIONS_FILE = "user_sessions.json"
SAVE_INTERVAL = 600  # secondi


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
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 6))  # secondi

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Sessioni utente
user_sessions = {}
last_poll_time = 0.0



# ---------- Funzioni per gestione JSON ----------

save_lock = asyncio.Lock()

async def save_sessions():
    """Salva le sessioni utente su file JSON in modo asincrono."""
    try:
        temp_file = SESSIONS_FILE + ".tmp"
        async with save_lock:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in user_sessions.items()}, f, ensure_ascii=False, indent=4)
            os.replace(temp_file, SESSIONS_FILE)
        logging.info("💾 Sessioni utente salvate su file JSON")
    except Exception as e:
        logging.exception(f"💥 Errore durante il salvataggio delle sessioni: {e}")

def load_sessions():
    """Carica le sessioni utente da file JSON se esiste."""
    global user_sessions
    if os.path.isfile(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                user_sessions = {str(k): v for k, v in json.load(f).items()}
            logging.info(f"📂 Caricate {len(user_sessions)} sessioni utente da JSON")
        except Exception as e:
            logging.exception(f"💥 Errore durante il caricamento delle sessioni: {e}")
            user_sessions = {}
    else:
        user_sessions = {}

async def add_user_session(user_id, thread_id, bearer_token=None, secret_key=None):
    uid = str(user_id)
    user_sessions[uid] = {
        "thread_id": thread_id,
        "notifications": [],
        "bearer_token": bearer_token,
        "secret_key": secret_key
    }
    await save_sessions()

async def remove_user_session(user_id):
    uid = str(user_id)
    if uid in user_sessions:
        user_sessions.pop(uid)
        await save_sessions()



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

        await add_user_session(user_id, thread.id)

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

      # Avvia salvataggio periodico
    if not auto_save_sessions.is_running():
        auto_save_sessions.start()


    if not poll_all_users.is_running():
        poll_all_users.start()


# ---------- Task periodico salvataggio ----------
@tasks.loop(seconds=SAVE_INTERVAL)
async def auto_save_sessions():
    await save_sessions()

async def close_aiohttp():
    global aiohttp_session
    if aiohttp_session:
        await aiohttp_session.close()
        aiohttp_session = None
        logging.info("🌐 Sessione aiohttp chiusa")

@bot.event
async def on_disconnect():
    await close_aiohttp()

@bot.event
async def on_shutdown():
    await close_aiohttp()


# ---------- Gestione thread eliminati ----------

@bot.event
async def on_thread_delete(thread: discord.Thread):
    to_remove = None
    for uid, session in user_sessions.items():
        if int(session.get("thread_id", 0)) == int(thread.id):
            to_remove = uid
            break
    if to_remove:
        await remove_user_session(to_remove)
        logging.info(f"🗑️ Thread eliminato, rimossa sessione per utente {to_remove}")


# ---------- Funzione per rispondere a un messaggio UEX ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    uid = str(message.author.id)
    content = message.content.strip()

    # Gestione iniziale credenziali
    if uid in user_sessions:
        session = user_sessions[uid]

        # Se non ha ancora inserito le chiavi
        if not session.get("bearer_token") or not session.get("secret_key"):
            if content.startswith("bearer:") and "secret:" in content:
                try:
                    bearer = content.split("bearer:")[1].split("secret:")[0].strip()
                    secret = content.split("secret:")[1].strip()

                    bearer = bearer.replace("<", "").replace(">", "")
                    secret = secret.replace("<", "").replace(">", "")

                    session["bearer_token"] = bearer
                    session["secret_key"] = secret
                    
                    await save_sessions()  # <- aggiungi questa riga!
                    await message.channel.send("✅ Credenziali salvate! Inizio a controllare le notifiche...")
                
                    asyncio.create_task(fetch_notifications(uid, session))
                
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
                                
                await bot.process_commands(message)

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
                        logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✉️ Utente {uid} ha risposto alla notifica {notif_hash}")
                    else:
                        text = await resp.text()
                        await message.channel.send(f"⚠️ Errore nell’invio ({resp.status}): {text[:200]}")
                        logging.warning(f"Errore UEX reply {resp.status} per utente {uid}: {text}")
            except Exception as e:
                await message.channel.send(f"💥 Errore di connessione: {e}")
                logging.exception(f"💥 Errore durante l'invio reply utente {uid}: {e}")

    await bot.process_commands(message)


# ---------- FUNZIONE POLLING PER SINGOLO UTENTE (con logging dettagliato e parsing migliorato) ----------
async def fetch_notifications(user_id, session):
    global aiohttp_session

    if not session.get("bearer_token") or not session.get("secret_key"):
        logging.info(f"⏸️ Utente {user_id} senza credenziali, skip fetch.")
        return


    async with semaphore:
        thread = bot.get_channel(int(session.get("thread_id", 0)))
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

                        raw_message = notif.get("message", "").strip()
                        redir = notif.get("redir", "")
                        notif_hash = None

                        if "hash/" in redir:
                            notif_hash = redir.split("hash/")[-1]

                        # --- 🔧 Parsing migliorato ---
                        if ":" in raw_message:
                            sender, text = raw_message.split(":", 1)
                            sender = sender.strip()
                            text = text.strip()
                        else:
                            # Gestisce casi tipo "captmonsters ended negotiation"
                            parts = raw_message.split(" ", 1)
                            if len(parts) == 2 and parts[0].isalnum():
                                sender, text = parts[0].strip(), parts[1].strip()
                            else:
                                sender, text = "Sconosciuto", raw_message.strip()

                        # Salva la notifica
                        session.setdefault("notifications", []).append({
                            "id": notif_id,
                            "hash": notif_hash,
                            "message": raw_message
                        })
                        
                        await save_sessions()

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

    tasks_list = []
    for uid, sess in list(user_sessions.items()):
        # ✅ Avvia il polling solo se l'utente ha entrambe le chiavi
        if not sess.get("bearer_token") or not sess.get("secret_key"):
            logging.info(f"⏸️ Utente {uid} senza credenziali, salto polling.")
            continue
        tasks_list.append(asyncio.create_task(fetch_notifications(uid, sess)))

    if not tasks_list:
        logging.info("⏸️ Nessun utente con credenziali valide, salto polling.")
        return

    await asyncio.gather(*tasks_list, return_exceptions=True)

    elapsed = time.perf_counter() - start
    last_poll_time = elapsed
    logging.info(f"✅ Polling completato in {elapsed:.2f}s per {len(tasks_list)} utenti")


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


# ---------- Carica sessioni all'avvio ----------
load_sessions()


# ---------- Run Bot ----------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
