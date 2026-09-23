import os
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot en ligne !"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import asyncio
from dotenv import load_dotenv

load_dotenv()

from config import (
    EXEMPT_ROLES, COLOR_MAIN, COLOR_OK, COLOR_ERR, COLOR_INFO, COLOR_MUSIC,
    MUSIC_MAX_QUEUE, MUSIC_DEFAULT_VOLUME
)
import music


TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN or TOKEN == "COLLE_TON_TOKEN_ICI":
    print("❌ DISCORD_TOKEN manquant")
    exit(1)


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

SAVE_FILE = "mute_data.json"
muted_channels = {}
muted_users = {}


def load_data():
    global muted_channels, muted_users
    try:
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                muted_channels = {int(k): v for k, v in data.get("channels", {}).items()}
                muted_users = {int(k): set(v) for k, v in data.get("users", {}).items()}
    except: pass


def save_data():
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "channels": {str(k): v for k, v in muted_channels.items()},
                "users": {str(k): list(v) for k, v in muted_users.items()},
            }, f)
    except: pass


def is_exempt(member):
    if member.bot: return True
    return any(r.name in EXEMPT_ROLES for r in member.roles)


def get_muted_set(guild_id):
    if guild_id not in muted_users:
        muted_users[guild_id] = set()
    return muted_users[guild_id]


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if is_exempt(member): return

    guild_id = member.guild.id
    muted_channel_id = muted_channels.get(guild_id)
    muted_set = get_muted_set(guild_id)

    if not muted_channel_id:
        if member.id in muted_set and after.channel is not None:
            try:
                if member.voice and member.voice.mute:
                    await member.edit(mute=False)
                muted_set.discard(member.id)
                save_data()
            except: pass
        return

    if after.channel and after.channel.id == muted_channel_id:
        if before.channel != after.channel:
            try:
                if not member.voice.mute:
                    await member.edit(mute=True)
                    muted_set.add(member.id)
                    save_data()
            except: pass
        return

    if before.channel and before.channel.id == muted_channel_id:
        if after.channel != before.channel:
            try:
                if member.voice and member.voice.mute:
                    await member.edit(mute=False)
                save_data()
            except: pass
        return


# ============================================
# COMMANDES MUTE
# ============================================
@bot.tree.command(name="set-mute", description="🔇 Mute tout le monde dans ton vocal")
@commands.has_permissions(administrator=True)
async def set_mute(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.response.send_message("❌ Tu dois être dans un vocal !", ephemeral=True)

    channel = interaction.user.voice.channel
    guild_id = interaction.guild.id
    muted_channels[guild_id] = channel.id
    muted_set = get_muted_set(guild_id)

    await interaction.response.defer()
    muted = 0
    for m in channel.members:
        if is_exempt(m): continue
        try:
            if not m.voice.mute:
                await m.edit(mute=True)
                muted_set.add(m.id)
                muted += 1
        except: pass

    save_data()
    await interaction.followup.send(f"🔇 **{muted}** membre(s) muté(s)")


@bot.tree.command(name="unset-mute", description="🔊 Désactive le mode mute")
@commands.has_permissions(administrator=True)
async def unset_mute(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in muted_channels:
        return await interaction.response.send_message("❌ Aucun salon mute.", ephemeral=True)
    await interaction.response.defer()
    channel_id = muted_channels.pop(guild_id)
    channel = interaction.guild.get_channel(channel_id)
    unmuted = 0
    if channel:
        for m in channel.members:
            if m.bot: continue
            try:
                if m.voice and m.voice.mute:
                    await m.edit(mute=False)
                    unmuted += 1
                    get_muted_set(guild_id).discard(m.id)
            except: pass
    save_data()
    await interaction.followup.send(f"🔊 **{unmuted}** démute(s)")


@bot.tree.command(name="unmute-all", description="🔊 Force le démute")
@commands.has_permissions(administrator=True)
async def unmute_all(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    await interaction.response.defer()
    muted_set = get_muted_set(guild_id)
    unmuted = 0
    for uid in list(muted_set):
        try:
            member = interaction.guild.get_member(uid)
            if not member:
                muted_set.discard(uid)
                continue
            if member.voice and member.voice.mute:
                await member.edit(mute=False)
                unmuted += 1
            muted_set.discard(uid)
        except: pass
    save_data()
    await interaction.followup.send(f"🔊 **{unmuted}** démute(s)")


# ============================================
# PLAY (gère artiste, album, playlist, track)
# ============================================
@bot.tree.command(name="play", description="🎵 Joue une musique / album / artiste / playlist")
@app_commands.describe(query="Nom, lien YouTube ou lien Spotify")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    vc = await music.ensure_voice(interaction)
    if not vc:
        return

    try:
        # ARTISTE Spotify
        if "spotify.com" in query and "/artist/" in query:
            await interaction.followup.send("🎵 Récupération de l'artiste...")
            artist_id = query.split("/artist/")[1].split("?")[0]
            tracks = music.extract_spotify_artist_tracks(artist_id)
            if not tracks:
                return await interaction.followup.send("❌ Artiste introuvable.")
            queue = music.get_queue(interaction.guild.id)
            added = 0
            for t in tracks:
                if len(queue) >= MUSIC_MAX_QUEUE: break
                try:
                    info = await music.search_youtube(t)
                    info['requester'] = interaction.user.display_name
                    queue.append(info)
                    added += 1
                except Exception as e:
                    print(f"⚠️ Ignorée : {e}")
            if not vc.is_playing() and not vc.is_paused():
                await music.play_next(interaction, interaction.guild.id)
            await interaction.followup.send(f"✅ Artiste : **{added}** morceau(x) ajouté(s)")
            return

        # ALBUM Spotify
        if "spotify.com" in query and "/album/" in query:
            await interaction.followup.send("🎵 Récupération de l'album...")
            album_id = query.split("/album/")[1].split("?")[0]
            tracks = music.extract_spotify_album_tracks(album_id)
            if not tracks:
                return await interaction.followup.send("❌ Album introuvable.")
                          # ⚡ RECHERCHE PARALLÈLE
            results = await music.search_multiple(tracks, max_concurrent=6)

            queue = music.get_queue(interaction.guild.id)
            added = 0
            for info in results:
                if len(queue) >= MUSIC_MAX_QUEUE: break
                info['requester'] = interaction.user.display_name
                queue.append(info)
                added += 1

            if not vc.is_playing() and not vc.is_paused():
                await music.play_next(interaction, interaction.guild.id)
            await interaction.followup.send(f"✅ Album : **{added}** piste(s)")
            return

        # PLAYLIST Spotify
        if "spotify.com" in query and "/playlist/" in query:
            await interaction.followup.send("🎵 Récupération de la playlist...")
            playlist_id = query.split("/playlist/")[1].split("?")[0]
            tracks = music.extract_spotify_playlist_tracks(playlist_id)
            if not tracks:
                return await interaction.followup.send("❌ Playlist introuvable.")
            queue = music.get_queue(interaction.guild.id)
            added = 0
            for t in tracks:
                if len(queue) >= MUSIC_MAX_QUEUE: break
                try:
                    info = await music.search_youtube(t)
                    info['requester'] = interaction.user.display_name
                    queue.append(info)
                    added += 1
                except: pass
            if not vc.is_playing() and not vc.is_paused():
                await music.play_next(interaction, interaction.guild.id)
            await interaction.followup.send(f"✅ Playlist : **{added}** piste(s)")
            return

        # TRACK Spotify
        if "spotify.com" in query and "/track/" in query:
            track_id = query.split("/track/")[1].split("?")[0]
            name = music.extract_spotify_track_info(track_id)
            if name:
                query = name

        # Simple
        track = await music.search_youtube(query)
        queue = music.get_queue(interaction.guild.id)
        if len(queue) >= MUSIC_MAX_QUEUE:
            return await interaction.followup.send("❌ File pleine.")
        track['requester'] = interaction.user.display_name
        queue.append(track)
        if not vc.is_playing() and not vc.is_paused():
            await music.play_next(interaction, interaction.guild.id)
        else:
            await interaction.followup.send(f"✅ Ajouté : **{track['title']}**")

    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {e}")


@bot.tree.command(name="skip", description="⏭️ Suivante")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        return await interaction.response.send_message("❌ Aucune musique", ephemeral=True)
    vc.stop()
    await interaction.response.send_message("⏭️ Passée")


@bot.tree.command(name="pause", description="⏸️ Pause")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        return await interaction.response.send_message("❌ Aucune musique", ephemeral=True)
    vc.pause()
    await interaction.response.send_message("⏸️ Pause")


@bot.tree.command(name="resume", description="▶️ Reprendre")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_paused():
        return await interaction.response.send_message("❌ Aucune musique", ephemeral=True)
    vc.resume()
    await interaction.response.send_message("▶️ Reprise")


@bot.tree.command(name="queue", description="📋 File")
async def queue_cmd(interaction: discord.Interaction):
    queue = music.get_queue(interaction.guild.id)
    current = music.now_playing.get(interaction.guild.id)
    if not queue and not current:
        return await interaction.response.send_message("📭 File vide", ephemeral=True)
    embed = discord.Embed(title="📋 File d'attente", color=COLOR_MUSIC)
    if current:
        embed.add_field(name="🎵 En cours", value=f"**{current['title'][:60]}**", inline=False)
    if queue:
        text = ""
        for i, t in enumerate(queue[:10]):
            text += f"`{i+1}.` {t['title'][:50]}\n"
        embed.add_field(name=f"📜 À suivre ({len(queue)})", value=text, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stop", description="⏹️ Arrêter")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        return await interaction.response.send_message("❌ Pas connecté", ephemeral=True)
    music.queues[interaction.guild.id] = []
    music.now_playing.pop(interaction.guild.id, None)
    if vc.is_playing(): vc.stop()
    await vc.disconnect()
    await interaction.response.send_message("⏹️ Déconnecté")


@bot.tree.command(name="volume", description="🔊 Volume (0-100)")
@app_commands.describe(niveau="0 à 100")
async def volume_cmd(interaction: discord.Interaction, niveau: int):
    vc = interaction.guild.voice_client
    if not vc or not vc.source:
        return await interaction.response.send_message("❌ Aucune musique", ephemeral=True)
    if not 0 <= niveau <= 100:
        return await interaction.response.send_message("❌ Entre 0 et 100", ephemeral=True)
    vc.source.volume = niveau / 100
    await interaction.response.send_message(f"🔊 Volume : **{niveau}%**")


@bot.tree.command(name="clear", description="🗑️ Vider la file")
async def clear_cmd(interaction: discord.Interaction):
    music.queues[interaction.guild.id] = []
    await interaction.response.send_message("🗑️ File vidée")


@bot.tree.command(name="aide", description="📖 Aide")
async def aide(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Aide", color=COLOR_MAIN)
    embed.add_field(
        name="🎵 Musique",
        value="`/play [nom ou lien]` • `/skip` • `/pause` • `/resume` • `/queue` • `/volume` • `/clear` • `/stop`",
        inline=False
    )
    embed.add_field(
        name="🔇 Mute",
        value="`/set-mute` • `/unset-mute` • `/unmute-all`",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    load_data()
    print("=" * 60)
    print(f"✅ Bot connecté : {bot.user}")
    print("=" * 60)
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées")
    except Exception as e:
        print(f"❌ Erreur : {e}")


   if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(os.getenv('DISCORD_TOKEN'))
