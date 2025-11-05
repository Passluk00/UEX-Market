import os
import re
import json
import asyncio
import logging
from datetime import datetime

import aiohttp
import aiosqlite
from aiohttp import web

import discord
from discord import app_commands, ui
from discord.ext import commands

from dotenv import load_dotenv
import directory  # contiene ALL_API_URL


# ---------- Config ----------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TUNNEL_URL = os.getenv("TUNNEL_URL")
DB_PATH = os.getenv("DB_PATH")
LOG_PATH = os.getenv("LOG_PATH")

# ---------- Logging ----------
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    filemode='a',
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ---------- DB globale ----------
db_conn: aiosqlite.Connection = None
db_lock = asyncio.Lock()

# ---------- Sessione HTTP globale ----------
aiohttp_session = None

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Inizializzazione DB ----------
async def init_db():
    global db_conn
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db_conn = await aiosqlite.connect(DB_PATH)
    await db_conn.execute("PRAGMA journal_mode=WAL;")
    await db_conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id TEXT PRIMARY KEY,
            uex_username TEXT NOT NULL,
            session_data TEXT NOT NULL,
            last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db_conn.commit()
    logging.info("📦 Database SQLite inizializzato in WAL mode")

async def init_negotiation_links_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS negotiation_links (
                negotiation_hash TEXT PRIMARY KEY,
                buyer_id TEXT NOT NULL,
                seller_id TEXT NOT NULL
            )
        """)
        await db.commit()



# ---------- Funzioni DB ----------
async def get_user_session(user_id: str) -> dict | None:
    async with db_lock:
        async with db_conn.execute("SELECT session_data FROM sessions WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

async def save_user_session(user_id: str, session: dict):
    async with db_lock:
        data_json = json.dumps(session)
        uex_username = session.get("uex_username", "")  # valore di default vuoto
        await db_conn.execute(
            "INSERT OR REPLACE INTO sessions (user_id, uex_username, session_data, last_update) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        (user_id,uex_username, data_json))
        await db_conn.commit()
        logging.info(f"💾 Sessione salvata per utente {user_id}")

async def remove_user_session(user_id: str):
    async with db_lock:
        await db_conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        await db_conn.commit()
        logging.info(f"🗑️ Sessione rimossa per utente {user_id}")

async def get_user_thread_id(user_id: str) -> str | None:
    session = await get_user_session(user_id)
    if session:
        return session.get("thread_id")
    return None

async def fetch_and_store_uex_username(user_id, secret_key, bearer_token, username_to_test):
    try:
        timeout = aiohttp.ClientTimeout(total=15)  # ⏱️ aumenta timeout a 15s
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

        # Se abbiamo una secret key, usiamola come header
        if secret_key:
            headers["secret-key"] = secret_key
            url = directory.API_GET_USER  # Non serve parametro username
        else:
            # Fallback: usiamo il parametro ?username=
            url = f"{directory.API_GET_USER}?username={username_to_test}"

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logging.warning(f"⚠️ Errore fetch UEX user {user_id}: status={resp.status} text={text}")
                    return None

                data = await resp.json()
                username = data.get("data", {}).get("username") or data.get("username")

                # ✅ Aggiorna nel DB
                session_data = await get_user_session(str(user_id))
                if session_data:
                    session_data["username"] = username
                    await save_user_session(str(user_id), session_data)
                    logging.info(f"💾 Username UEX salvato per {user_id}: {username}")

                return username

    except asyncio.TimeoutError:
        logging.error(f"⏱️ Timeout UEX API per utente {user_id}")
        return None
    except Exception as e:
        logging.exception(f"💥 Errore fetch_and_store_uex_username per {user_id}: {e}")
        return None


    """
    Restituisce il thread_id associato all'username UEX, se esiste.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, session_data
            FROM sessions
            WHERE uex_username = ?
        """, (uex_username,)) as cursor:
            row = await cursor.fetchone()

            if not row:
                logging.warning(f"⚠️ Nessuna sessione trovata per uex_username={uex_username}")
                return None

            user_id, session_json = row

            try:
                session = json.loads(session_json)
            except Exception as e:
                logging.error(f"💥 Errore nel parsing JSON di session_data per user_id={user_id}: {e}")
                return None

            thread_id = session.get("thread_id")
            if thread_id:
                logging.info(f"🧩 thread_id={thread_id} trovato per uex_username={uex_username} (user_id={user_id})")
                return thread_id
            else:
                logging.warning(f"⚠️ Nessun thread_id nella sessione di {uex_username}")
                return None




async def save_negotiation_link(negotiation_hash: str, buyer_id: str, seller_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO negotiation_links (negotiation_hash, buyer_id, seller_id)        
            VALUES (?, ?, ?)
        """, (negotiation_hash, buyer_id, seller_id))
        await db.commit()
        logging.info(f"🔗 Link salvato: {negotiation_hash} → buyer={buyer_id}, seller={seller_id}")

async def get_negotiation_link(negotiation_hash: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT buyer_id, seller_id FROM negotiation_links WHERE negotiation_hash = ?
        """, (negotiation_hash,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"buyer_id": row[0], "seller_id": row[1]}
    return None

async def delete_negotiation_link(negotiation_hash: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM negotiation_links WHERE negotiation_hash = ?", (negotiation_hash,))
        await db.commit()
        logging.info(f"❌ Link eliminato: {negotiation_hash}")

async def find_session_by_username(username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, session_data FROM sessions
        """) as cursor:
            async for row in cursor:
                uid, session_json = row
                session = json.loads(session_json)
                if session.get("username") == username:
                    return {"user_id": uid, **session}
    return None


async def handle_webhook_unificato(request, event_type: str, user_id: str):
    try:
        body = await request.text()
        data = json.loads(body) if body else {}
        logging.info(f"📨 Webhook ricevuto: event='{event_type}' → user_id={user_id} → body: {data}")
    
        
        if event_type == "negotiation_started":
            
            seller = data.get("listing_owner_username")
            buyer = data.get("client_username")
            hash = data.get("negotiation_hash")
            
            logging.info(f"🚀 Nuova negoziazione: hash: {hash} da {buyer}")

            await save_negotiation_link(
                    negotiation_hash=hash,
                    buyer_id=buyer,
                    seller_id=seller
                )
            
            # Recupera sessione utente
            thread_id = await get_user_thread_id(str(user_id))
            if not thread_id:
                logging.warning(f"⚠️ Nessun Thread_id Trovato per Seller: {seller}")
                return {"status": 404, "text": "Seller_thread_id not found"}
            
            # Recupera Thread Seller
            thread = bot.get_channel( thread_id )
            if not thread:
                logging.warning(f"⚠️ Thread non trovato per Seller: {seller}")
                return {"status": 404, "text": "thread not found"}
            
            # Avviso al Venditore di una Nuova Trattativa
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_footer(
                text=f"Made with love by Passluk"
            )
            embed.title = "📢 Nuova negoziazione iniziata"
            embed.description = (
                f"👤 **{data.get('client_username', 'Anonimo')}**\n"
                f"📦 **{data.get('listing_title', 'Sconosciuto')}**\n"
                f"🔗 [Apri su UEX](https://uexcorp.space/marketplace/negotiate/hash/{data.get('negotiation_hash', '')})"
            )
            embed.color = discord.Color.green()
            await thread.send(embed=embed)
            logging.info(f"✅ Link creato tra buyer: {buyer} e seller: {seller}")
            
            
        # === Caso 2: messaggio di reply ===
        elif event_type == "user_reply":
            
            seller = data.get("listing_owner_username")
            user = data.get("client_username")
            hash = data.get("negotiation_hash")
            
            logging.info(f"💬 Webhook reply ricevuto → hash: {hash}, da user_id={user}")

            link = await get_negotiation_link(hash)
            if not link:
                logging.warning(f"⚠️ Nessun collegamento trovato per negoziazione {hash}")
                return {"status": 404, "text": "negotiation link not found"}
            
            if user == None:
                logging.warning(f"Invalid Username")
                return {"status": 404, "text": "Invalid Username"}
            
            

            if user == seller:
                # manda il mex al buyer
                
                buyer_username = link.get("buyer_id")
                
                
                session_buyer = await find_session_by_username(buyer_username)
                if not session_buyer:
                    logging.warning(f"⚠️ Buyer_Session not found")
                    return {"status": 404, "text": "Buyer_Sessions not found"}
                
                
                buyer_thread_id = session_buyer.get("thread_id")
                if not buyer_thread_id: 
                    logging.warning(f"⚠️ Buyer_Thread_Id not found")
                    return {"status": 404, "text": "Buyer_thread_id not found"}
                
                
                # Recupera Thread Buyer
                thread = bot.get_channel( buyer_thread_id )
                if not thread:
                    logging.warning(f"⚠️ Thread non trovato per Seller: {seller}")
                    return {"status": 404, "text": "thread not found"}
                
                
                
                # Avviso al Buyer di una nuova Notifica
                embed = discord.Embed(color=discord.Color.blue())
                embed.set_footer(
                    text=f"Made with love by Passluk"
                )
                embed.title = "💬 Nuovo messaggio"
                embed.description = (
                    f"👤 **{seller}** ha scritto:\n"
                    f"> {data.get('message', '')}\n\n"
                    f"📦 **{data.get('listing_title', 'Sconosciuto')}**\n"
                    f"🔗 [Apri su UEX](https://uexcorp.space/marketplace/negotiate/hash/{hash})"
                )
                embed.color = discord.Color.gold()
                await thread.send(embed=embed)

            
            
            elif user != seller:
                # manda un mex al seller
                
                
                
                # Recupera sessione utente
                thread_id = await get_user_thread_id(str(user_id))
                if not thread_id:
                    logging.warning(f"⚠️ Nessun Thread_id Trovato per Seller: {seller}")
                    return {"status": 404, "text": "Seller_thread_id not found"}
                
                # Recupera Thread Seller
                thread = bot.get_channel( thread_id )
                if not thread:
                    logging.warning(f"⚠️ Thread non trovato per Seller: {seller}")
                    return {"status": 404, "text": "thread not found"}
                
                # Avviso al Venditore di una Nuova Notifica
                embed = discord.Embed(color=discord.Color.blue())
                embed.set_footer(
                    text=f"Made with love by Passluk"
                )
                embed.title = "💬 Nuovo messaggio"
                embed.description = (
                    f"👤 **{user}** ha scritto:\n"
                    f"> {data.get('message', '')}\n\n"
                    f"📦 **{data.get('listing_title', 'Sconosciuto')}**\n"
                    f"🔗 [Apri su UEX](https://uexcorp.space/marketplace/negotiate/hash/{hash})"
                )
                embed.color = discord.Color.gold()
                await thread.send(embed=embed)
                
            else:
                logging.warning(f"⚠️ Username '{user}' non corrisponde né al buyer né al seller per hash={hash}")
                return {"status": 400, "text": "Unknown message source"}
            
            
            
        # === Caso 3: negoziazione terminata ===
        elif event_type in ("negotiation_completed_client", "negotiation_completed_advertiser"):

            hash = data.get("negotiation_hash")
            logging.info(f"🏁 Fine negoziazione → eliminazione link hash: {hash}")
            
            # Recupera sessione utente
            thread_id = await get_user_thread_id(str(user_id))
            if not thread_id:
                logging.warning(f"⚠️ Nessun Thread_id Trovato per Seller: {seller}")
                return {"status": 404, "text": "Seller_thread_id not found"}
            
            # Recupera Thread Seller
            thread = bot.get_channel( thread_id )
            if not thread:
                logging.warning(f"⚠️ Thread non trovato per Seller: {seller}")
                return {"status": 404, "text": "thread not found"}
        

            # Avviso al Venditore di una Nuova Trattativa
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_footer(
                text=f"Made with love by Passluk"
            )
            embed.title = f"✅ Negoziazione completata da {data.get('client_username', 'Anonimo')}"
            embed.description = (
                f"📦 **{data.get('listing_title', 'Sconosciuto')}**\n"
                f"⭐ Valutazione: {data.get('rating_stars', 0)}\n"
                f"💬 Commento: {data.get('rating_comments', 'Nessuno')}\n"
                f"🔗 [Apri su UEX](https://uexcorp.space/marketplace/negotiate/hash/{hash})"
            )
            embed.color = discord.Color.red()
            await delete_negotiation_link(hash)
            await thread.send(embed=embed)
            
        
        
        else:
            
            # Recupera sessione utente
            thread_id = await get_user_thread_id(str(user_id))
            if not thread_id:
                logging.warning(f"⚠️ Nessun Thread_id Trovato per Seller: {seller}")
                return {"status": 404, "text": "Seller_thread_id not found"}
            
            # Recupera Thread Seller
            thread = bot.get_channel( thread_id )
            if not thread:
                logging.warning(f"⚠️ Thread non trovato per Seller: {seller}")
                return {"status": 404, "text": "thread not found"}
            
            # Avviso al Seller errore
            embed = discord.Embed(color=discord.Color.blue())
            embed.set_footer(
                text=f"Made with love by Passluk"
            )
            embed.title = f"ℹ️ Evento: {event_type}"
            embed.description = json.dumps(data, indent=2)
            await thread.send(embed=embed)

        logging.info(f"✅ Webhook elaborato con successo per event='{event_type}' → user_id={user_id}")
        return {"status": 200, "text": "Webhook elaborato"}

    except Exception as e:
        logging.exception(f"💥 Errore in handle_webhook_unificato: {e}")
        return {"status": 500, "text": f"internal error: {e}"}
        

# ---------- HTTP/Aiohttp webhook ----------
async def handle_webhook(request):
    try:
        
        event_type = request.match_info["event_type"]
        user_id = request.match_info["user_id"]
        result = await handle_webhook_unificato(request, event_type, user_id)
        logging.info(f"arrivata una richiesta utente: {user_id}")
        return web.Response(status=result["status"], text=result["text"])
    except Exception as e:
        logging.exception(f"💥 Errore handler aiohttp: {e}")
        return web.Response(status=500, text=f"Error: {e}")

async def handle_health(response):
	return web.Response(status=200, text=f"online")


async def start_aiohttp_server():
    app = web.Application()
    app.router.add_post("/webhook/{event_type}/{user_id}", handle_webhook)
    app.router.add_get("/health",handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 20187)
    await site.start()
    logging.info("🚀 Server HTTP/1.1 (aiohttp) avviato su porta 20187")

# ---------- Bottone per aprire thread ----------
class OpenThreadButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Apri la tua chat", style=discord.ButtonStyle.primary, custom_id="open_thread_button")
    async def open_thread(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        channel = interaction.channel

        try:
            thread_id = await get_user_thread_id(user_id)
            if thread_id:
                try:
                    existing_thread = await interaction.client.fetch_channel(int(thread_id))
                    if existing_thread and not existing_thread.archived:
                        await interaction.response.send_message(
                            "⚠️ Hai già una chat attiva! Controlla i tuoi thread privati.",
                            ephemeral=True
                        )
                        return
                except discord.NotFound:
                    await remove_user_session(user_id)

            thread = await channel.create_thread(
                name=f"Chat {interaction.user.name.capitalize()}",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            await thread.add_user(interaction.user)
            session = {"thread_id": thread.id, "notifications": []}
            await save_user_session(user_id, session)

            invisible = "\u200B"
            

            await thread.send(
                f"""👋 Ciao {interaction.user.name}!
                
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

                👉 Ottenere UEX Username
                1- Clicca sul tuo profilo in alto a destra.
                2- Clicca in alto a destra il bottone MY PUBLIC PROFILE
                3- Copia il tuo username che si trova nella barra url senza la @


                👉 Inserire le chiavi nel bot
                Nel tuo thread privato su Discord, incolla le due chiavi e l'username con questo formato:
                bearer:TUO_BEARER_TOKEN secret:TUA_SECRET_KEY username<TUO_USERNAME_UEX>               
                {invisible}
                """)
            
            await thread.send(
                f"""👉 Aggiungere i Webhook personalizzati
                
                Dopo aver configurato la tua app UEX, segui questi passaggi:

                1- In alto a destra clicca sul pulsante **Account**.
                2- Dal menu a tendina, seleziona **Apps**.
                3- Si aprirà la pagina con le tue applicazioni. In alto a destra clicca sul pulsante verde **Webhooks**.
                4- Si aprirà la pagina per la gestione dei webhook: troverai 4 campi diversi.
                5- Inserisci i seguenti URL nei rispettivi campi:

                Negotiation Completed (Advertiser)  
                ➜ `{TUNNEL_URL}/webhook/negotiation_completed_advertiser/{user_id}`

                Negotiation Completed (Client)  
                ➜ `{TUNNEL_URL}/webhook/negotiation_completed_client/{user_id}`

                Negotiation Started  
                ➜ `{TUNNEL_URL}/webhook/negotiation_started/{user_id}`

                User Reply
                ➜ `{TUNNEL_URL}/webhook/user_reply/{user_id}`

                6- Dopo averli inseriti tutti, clicca in basso al centro sul pulsante verde **Salva**.

                ⚠️ Nota Importante:
                Non condividere queste chiavi con nessuno.
                Il bot le userà solo per accedere alle tue notifiche personali su UEX.
                """
            )
            await interaction.response.send_message("✅ Thread creato! Controlla il tuo thread privato.", ephemeral=True)

        except Exception as e:
            logging.error(f"❌ Errore in open_thread: {e}")
            await interaction.response.send_message("❌ Si è verificato un errore durante la creazione del thread.", ephemeral=True)

# ---------- Evento on_ready ----------
@bot.event
async def on_ready():
    
    show_logo()
    
    global aiohttp_session
    logging.info("🗂️ Avvio Database")
    await init_db()
    await init_negotiation_links_table()
    logging.info("✅ Database Avviato")

    if aiohttp_session is None:
        aiohttp_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        logging.info("🌐 Sessione aiohttp inizializzata")

    logging.info(f"✅ Bot online come {bot.user}")
    logging.info(f"📡 URL base webhook: {TUNNEL_URL}")
    logging.info("🌐 Avvio server webhook...")
    bot.loop.create_task(start_aiohttp_server())

    await bot.tree.sync()
    logging.info("✅ Commands synchronized.")
    bot.add_view(OpenThreadButton())

# ---------- Evento on_message ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not isinstance(message.channel, discord.Thread):
        return

    uid = str(message.author.id)
    content = message.content.strip()
    session = await get_user_session(uid)

    if session is None:
        return
    
    # ✅ Rimuove l’indicatore verde se l’utente scrive nel thread
    try:
        thread = message.channel
        if isinstance(thread, discord.Thread) and "🟩" in thread.name:
            new_name = thread.name.replace(" 🟩", "")
            await thread.edit(name=new_name)
            logging.info(f"🟩 Indicatore rimosso per utente {uid}")
    except Exception as e:
        logging.warning(f"⚠️ Impossibile aggiornare nome thread: {e}")

    # ---------- Inserimento chiavi Bearer/Secret/Username ----------
    if not session.get("bearer_token") or not session.get("secret_key") or not session.get("username"):
        if all(x in content for x in ("bearer:", "secret:", "username:")):
            try:
                # Usa una regex robusta per estrarre i 3 campi
                match = re.search(
                    r"bearer:\s*([^\s]+)\s+secret:\s*([^\s]+)\s+username:\s*([^\s]+)",
                    content,
                    re.IGNORECASE
                )
                if not match:
                    await message.channel.send("❌ Formato non corretto. Usa: `bearer:<token> secret:<secret_key> username:<nick>`")
                    return

                bearer = match.group(1).strip().replace("<", "").replace(">", "")
                secret = match.group(2).strip().replace("<", "").replace(">", "")
                username_to_test = match.group(3).strip().replace("<", "").replace(">", "")

                logging.info(f"Bearer Token: {bearer}")
                logging.info(f"SECRET KEY: {secret}")
                logging.info(f"Username: {username_to_test}")

                # Salva nel DB
                session["bearer_token"] = bearer
                session["secret_key"] = secret
                session["username"] = username_to_test
                await save_user_session(uid, session)

                # 🔍 Recupera e verifica username UEX
                try:
                    username = await fetch_and_store_uex_username(uid, secret, bearer, username_to_test)
                    if username:
                        await message.channel.send(f"✅ Credenziali salvate! Username UEX rilevato: **{username}**")
                    else:
                        await message.channel.send("✅ Credenziali salvate! (Username UEX non rilevato)")
                except Exception as e:
                    logging.warning(f"⚠️ Errore fetch username UEX per {uid}: {e}")
                    await message.channel.send("✅ Credenziali salvate! (Errore nel recupero username)")

            except Exception as e:
                logging.exception(f"❌ Errore parsing credenziali utente {uid}: {e}")
                await message.channel.send("❌ Formato non corretto. Usa: `bearer:<token> secret:<secret_key> username:<nick>`")
        else:
            await message.channel.send("❌ Formato non corretto. Usa: `bearer:<token> secret:<secret_key> username:<nick>`")        
            

    # ---------- Se l'utente sta rispondendo a una notifica ----------
    if message.reference and message.reference.resolved:
        replied_msg = message.reference.resolved

        # Trova l'hash della notifica dall'embed
        embed = replied_msg.embeds[0] if replied_msg.embeds else None
        notif_hash = None

        if embed and embed.description:
            match = re.search(r"/hash/([a-f0-9-]+)", embed.description)
            if match:
                notif_hash = match.group(1)

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

        logging.info(f"hash: {notif_hash}. Message: {content}")

        try:
            async with aiohttp_session.post(directory.API_POST_MESSAGE, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    # ✅ Embed più curato per mostrare il messaggio inviato
                    embed = discord.Embed(
                        title="💬 Messaggio inviato a UEX",
                        description=f"**Hai risposto:**\n> {content}",
                        color=discord.Color.green()
                    )

                    embed.add_field(name="📦 Negoziazione", value=f"🔗 [Apri su UEX](https://uexcorp.space/marketplace/negotiate/hash/{notif_hash})", inline=False)
                    embed.set_footer(
                        text=f"Made with love by Passluk"
                    )

                    await message.channel.send(embed=embed)
                    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✉️ Utente {uid} ha risposto alla notifica {notif_hash}")
                else:
                    text = await resp.text()
                    await message.channel.send(f"⚠️ Errore nell’invio ({resp.status}): {text[:200]}")
                    logging.warning(f"Errore UEX reply {resp.status} per utente {uid}: {text}")

        except Exception as e:
            await message.channel.send(f"💥 Errore di connessione: {e}")
            logging.exception(f"💥 Errore durante l'invio reply utente {uid}: {e}")


    await bot.process_commands(message)


# ---------- Gestione thread eliminati ----------
@bot.event
async def on_thread_delete(thread: discord.Thread):
    """
    Quando un thread viene eliminato, rimuove tutte le sessioni associate
    nel DB per gli utenti collegati a quel thread.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db_conn:
            # Recupera tutti gli utenti associati a quel thread (se hai salvato thread_id nel DB)
            cursor = await db_conn.execute(
                "SELECT user_id FROM sessions WHERE session_data LIKE ?",
                (f'%{thread.id}%',)
            )
            users_to_delete = await cursor.fetchall()

            # Elimina tutte le sessioni trovate
            if users_to_delete:
                for (user_id,) in users_to_delete:
                    await db_conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                await db_conn.commit()
                logging.info(f"🗑️ Thread eliminato → rimosse sessioni per {len(users_to_delete)} utenti (thread_id={thread.id})")
            else:
                logging.debug(f"ℹ️ Nessuna sessione trovata per il thread eliminato {thread.id}")

    except Exception as e:
        logging.exception(f"💥 Errore in on_thread_delete: {e}")


# ---------- Gestione utente che lascia il thread ----------
@bot.event
async def on_thread_member_remove(thread: discord.Thread, member: discord.Member):
    """
    Quando un utente lascia un thread, rimuove la sua sessione dal DB
    se era associata a quel thread.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db_conn:
            # Rimuove la sessione di quell’utente
            await db_conn.execute(
                "DELETE FROM sessions WHERE user_id = ?",
                (str(member.id),)
            )
            await db_conn.commit()

        logging.info(f"🚪 Utente {member.id} ha lasciato il thread {thread.id} → sessione rimossa dal DB")

    except Exception as e:
        logging.exception(f"💥 Errore in on_thread_member_remove: {e}")






# ---------- Comando /stats ----------
@bot.tree.command(name="stats", description="Mostra statistiche del bot")
@app_commands.checks.has_permissions(manage_guild=True)
async def stats(interaction: discord.Interaction):
    try:
        async with db_lock:
            async with db_conn.execute("SELECT COUNT(*) FROM sessions") as cursor:
                row = await cursor.fetchone()
                users_count = row[0] if row else 0

            async with db_conn.execute("SELECT session_data FROM sessions") as cursor:
                threads_active = 0
                async for row in cursor:
                    session = json.loads(row[0])
                    if session.get("thread_id"):
                        threads_active += 1

        embed = discord.Embed(
            title="📊 Statistiche Bot",
            color=discord.Color.green()
        )
        embed.add_field(name="👥 Utenti registrati", value=str(users_count), inline=True)
        embed.add_field(name="💬 Threads attivi", value=str(threads_active), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logging.info(f"Eseguito Comando Stats. Current User: {users_count}. Active Threads: {threads_active}")
    except Exception as e:
        logging.exception(f"❌ Errore nel comando /stats: {e}")
        await interaction.response.send_message("❌ Errore nel recupero delle statistiche.", ephemeral=True)


# ---------- Comando /add ----------
@bot.tree.command(name="add", description="Aggiunge il bottone per creare le chat private in un canale")
@app_commands.describe(canale="Il canale dove inviare il messaggio con il bottone")
@app_commands.checks.has_permissions(manage_guild=True)
async def add_button(interaction: discord.Interaction, canale: discord.TextChannel):
    """Comando slash per aggiungere il bottone in un canale specifico."""
    try:
        view = OpenThreadButton()

        embed = discord.Embed(
            title="💬 Connettiti al Marketplace UEX",
            description=(
                "Crea la tua **chat privata** per ricevere notifiche, messaggi e aggiornamenti "
                "sulle tue **negoziazioni UEX** direttamente su Discord!\n\n"
                "👉 Premi il pulsante qui sotto per avviare la configurazione e collegare il tuo account."
                "🌐 **[Verifica lo stato del bot](https://passluk.ddns.net)**"
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="Made with ❤️ by Passluk | UEX Bot"
        )

        embed.set_thumbnail(url="https://uexcorp.space/favicon.ico")

        await canale.send(embed=embed, view=view)
        await interaction.response.send_message(
            f"✅ Bottone con embed aggiunto in {canale.mention}", ephemeral=True
        )

        logging.info(f"🔘 Bottone (embed) aggiunto manualmente da {interaction.user} in {canale.name}")

    except Exception as e:
        logging.exception("💥 Errore nell'aggiunta del bottone con /add")
        await interaction.response.send_message(
            "❌ Si è verificato un errore durante l'aggiunta del bottone.", ephemeral=True
        )



def show_logo():
    
    logo = r"""     
    
            @(((((((((((@            @(((((((@(((((((((((((((((((((((#@#((((((((((((@/        &%(((((((((((&#           
            @(((((((((((@@@@@.       @(((((((@(((((((((((((((((((((((((%@((((((((((((%@@@   ,@(((((((((((%@@@@@@@&      
            @(((((((((((@(((@.       @(((((((@(((((((((((((((((((((((((((&&((((((((((((@%@,@%(((((((((((@#((((%@        
            @(((((((((((@(((@.       @(((((((@((((((((((#@@@@@@@@@@@@@@@@@@@#(((((((((((%@@(((((((((((@%((((#@*        
            @(((((((((((@(((@.       @(((((((@((((((((((#@((((((((((((((((((#@((((((((((((((((((((((%@(((((@#     
            @(((((((((((@(((@.       @(((((((@((((((((((#@@@@@&&&&&&&&&&&&& *@&&((((((((((((((((((#@#((((%@       
            @(((((((((((@(((@.       @(((((((@((((((((((((((((((((((((((((@   .(@%(((((((((((((((@%((((#@.              
            @(((((((((((@(((@.       @(((((((@((((((((((((((((((((((((((((@###@,&%(((((((((((((((@#(((@/                
            @(((((((((((@(((@.       @(((((((@((((((((((((((((((((((((((((@(((@@((((((((((((((((((#@%&                  
            @#((((((((((@#((@.       @(((((((@((((((((((#@((((((((((((((((((#@((((((((((((((((((((((&@@*                
            #%(((((((((((@#(@.     *@((((((((@((((((((((#@(((@@@@@@@@@@@@@@@#((((((((((%@@((((((((((((@&@               
             &#((((((((((((%@@@@@@%((((((((((@((((((((((#&&&&&&&&&&&&&&&&@&(((((((((((@%((@#(((((((((((#@&&             
              #@(((((((((((((((((((((((((((((@(((((((((((((((((((((((((#@(((((((((((%@(((((@@((((((((((((&@@/           
                /@#((((((((((((((((((((((((#@@((((((((((((((((((((((((@#(((((((((((@%((((&@#@@#((((((((((((@&@.         
                   /@@@%#((((((((((((#%@@&#((@((((((((((((((((((((((@@(((((((((((%@((((#@@(%@@@@((((((((((((#@&&        
                      #@%#(((((((((((((((((((#@@,@#((((((((((((((((((((((&&(((((((((((%&#@(&&     @#((((((((((((@(      
                           ,#@@@@@@@@@@@@&/.     %%%%%%%%%%%%%%%%%%%%%%&@@@@@@@@@@&%%%*            (%%%%%%%%%%%%&@&@#   
                           
"""

    logging.info(logo)





# ---------- Run Bot ----------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
