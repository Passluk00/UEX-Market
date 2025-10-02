import os
import requests
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime
import directory  # contiene API_NOTIFICATIONS

# ---------- Config ----------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 6))  # secondi

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Salva sessioni utente {user_id: {bearer_token, secret_key, thread_id, notifications}}
user_sessions = {}


# ---------- View Bottone ----------
class OpenThreadButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # <-- View persistente

    @ui.button(label="Apri la tua chat", style=discord.ButtonStyle.primary, custom_id="open_thread_button")
    async def open_thread(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        channel = interaction.channel

        # Controlla se thread già esiste
        if user_id in user_sessions:
            await interaction.response.send_message("Hai già un thread attivo!", ephemeral=True)
            return

        # Crea thread privato
        thread = await channel.create_thread(
            name=f"Chat {interaction.user.name}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )
        await thread.add_user(interaction.user)

        # Salva sessione utente
        user_sessions[user_id] = {
            "thread_id": thread.id,
            "notifications": []
        }

        await thread.send(
            f"👋 Ciao {interaction.user.name}! Inserisci il tuo **Bearer Token** e **Secret Key** "
            f"nel formato: `bearer:<token> secret:<secret_key>`"
        )
        await interaction.response.send_message("✅ Thread creato! Controlla il tuo thread privato.", ephemeral=True)


# ---------- Eventi Bot ----------
@bot.event
async def on_ready():
    print(f"✅ Bot connesso come {bot.user}")

    bot.add_view(OpenThreadButton())

    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.components:
                print("🔘 Pulsante già presente, riassociato.")
                break
        else:
            view = OpenThreadButton()
            await channel.send("Clicca il bottone per creare la tua chat personale:", view=view)
            print("🔘 Pulsante creato.")

    # <<<<<<<<<<<<< QUI MANCA
    if not poll_all_users.is_running():
        poll_all_users.start()

@bot.event
async def on_thread_delete(thread: discord.Thread):
    """Se un utente elimina il proprio thread, eliminiamo anche la sessione associata"""
    to_remove = None
    for user_id, session in user_sessions.items():
        if session.get("thread_id") == thread.id:
            to_remove = user_id
            break

    if to_remove:
        del user_sessions[to_remove]
        print(f"🗑️ Thread eliminato, rimossa sessione per utente {to_remove}")



@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    content = message.content.strip()

    # Controlla se è nel formato bearer/secret
    if user_id in user_sessions and "bearer_token" not in user_sessions[user_id]:
        if content.startswith("bearer:") and "secret:" in content:
            try:
                bearer = content.split("bearer:")[1].split("secret:")[0].strip()
                secret = content.split("secret:")[1].strip()

                # Rimuove eventuali <>
                bearer = bearer.replace("<", "").replace(">", "")
                secret = secret.replace("<", "").replace(">", "")

                user_sessions[user_id]["bearer_token"] = bearer
                user_sessions[user_id]["secret_key"] = secret
                await message.channel.send("✅ Credenziali salvate! Inizio a controllare le notifiche...")
            except Exception as e:
                await message.channel.send("❌ Formato non corretto. Usa: `bearer:<token> secret:<secret_key>`")
        return

    await bot.process_commands(message)


# ---------- Polling globale utenti ----------
@tasks.loop(seconds=POLL_INTERVAL)
async def poll_all_users():
    for user_id in list(user_sessions.keys()):  # usa copia delle chiavi
        session = user_sessions[user_id]

        if "bearer_token" not in session or "secret_key" not in session:
            continue  # utente non ha inserito credenziali

        headers = {
            "Authorization": f"Bearer {session['bearer_token']}",
            "secret-key": session["secret_key"]
        }

        try:
            response = requests.get(directory.API_NOTIFICATIONS, headers=headers)
            response.raise_for_status()
            data = response.json()
            notifications = data.get("data", [])

            thread = bot.get_channel(session["thread_id"])
            if notifications and thread:
                for notif in notifications:
                    notif_id = notif.get("id")
                    if notif_id in session["notifications"]:
                        continue  # già inviato

                    raw_message = notif.get("message", "")
                    redir = notif.get("redir", "")

                    # Split sender/testo
                    if ":" in raw_message:
                        sender, text = raw_message.split(":", 1)
                        sender = sender.strip()
                        text = text.strip()
                    else:
                        sender = "Sconosciuto"
                        text = raw_message

                    # Salva ID notifica per evitare duplicati
                    session["notifications"].append(notif_id)

                    # Invia messaggio completo
                ##    await thread.send(
                #        f"📩 Nuova notifica\n"
                #        f"👤 Mittente: {sender}\n"
                #        f"💬 Messaggio: {text}\n"
                #        f"🔗 Link alla chat: https://uexcorp.space/{redir}\n"
                #        
                ##    )
                    
                    embed = discord.Embed(
                        title="📩 Nuova notifica",
                        description=f"👤 Mittente: **{sender}**\n💬 {text}\n🔗 [Vai alla chat]( https://uexcorp.space/{redir}\n )",
                        color=discord.Color.blue()
                        )
                    
                    await thread.send(embed=embed)

        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now()}] Errore nel polling UEX per {user_id}: {e}")


# ---------- Comando /lista ----------






# ---------- Run Bot ----------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)





### Notifiche funzionanti + avvio funzionante
    