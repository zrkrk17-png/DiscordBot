import discord
from discord.ext import commands
import yt_dlp
import asyncio
import time
import os
import subprocess
import requests
import re
import json
from config import COLOR_MUSIC, MUSIC_MAX_QUEUE, MUSIC_DEFAULT_VOLUME


FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

queues = {}
now_playing = {}
loop_mode = {}
playback_start = {}
panel_messages = {}


def get_queue(gid):
    if gid not in queues:
        queues[gid] = []
    return queues[gid]


def fmt_duration(seconds):
    if not seconds:
        return "0:00"
    try:
        s = int(float(seconds))
    except:
        return "0:00"
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def get_elapsed(gid):
    if gid not in playback_start:
        return 0
    return int(time.time() - playback_start[gid])


def make_bar(elapsed, total, length=18):
    if total <= 0:
        return "▬" * length
    elapsed = max(0, min(elapsed, total))
    filled = int((elapsed / total) * length)
    filled = max(0, min(filled, length - 1))
    return "▬" * filled + "🔘" + "▬" * (length - filled - 1)


# ============================================
# SPOTIFY SCRAPING (via page embed)
# ============================================
def extract_spotify_artist_tracks(artist_id):
    """Récupère les top tracks d'un artiste via la page embed Spotify"""
    try:
        url = f"https://open.spotify.com/embed/artist/{artist_id}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ Page artiste : HTTP {r.status_code}")
            return []

        html = r.text

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if not match:
            print("⚠️ __NEXT_DATA__ introuvable")
            return []

        data = json.loads(match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})

        artist_name = entity.get("name", "")
        print(f"🎵 Artiste : {artist_name}")

        track_list = entity.get("trackList", [])

        tracks = []
        for t in track_list[:10]:
            title = t.get("title") or t.get("name", "")
            subtitle = t.get("subtitle", "")
            if title:
                query = f"{subtitle} {title}".strip() if subtitle else title
                tracks.append(query)

        if tracks:
            print(f"🎵 Artiste → {len(tracks)} top tracks")
        else:
            tracks = [artist_name] if artist_name else []

        return tracks
    except Exception as e:
        print(f"⚠️ Erreur artiste : {e}")
        return []


def extract_spotify_album_tracks(album_id):
    """Récupère les pistes d'un album via la page embed"""
    try:
        url = f"https://open.spotify.com/embed/album/{album_id}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return []

        html = r.text
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if not match:
            return []

        data = json.loads(match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        track_list = entity.get("trackList", [])

        tracks = []
        for t in track_list:
            title = t.get("title") or t.get("name", "")
            subtitle = t.get("subtitle", "")
            if title:
                tracks.append(f"{subtitle} {title}".strip() if subtitle else title)

        print(f"🎵 Album → {len(tracks)} piste(s)")
        return tracks
    except:
        return []


def extract_spotify_playlist_tracks(playlist_id):
    """Récupère les pistes d'une playlist via la page embed"""
    try:
        url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return []

        html = r.text
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if not match:
            return []

        data = json.loads(match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        track_list = entity.get("trackList", [])

        tracks = []
        for t in track_list:
            title = t.get("title") or t.get("name", "")
            subtitle = t.get("subtitle", "")
            if title:
                tracks.append(f"{subtitle} {title}".strip() if subtitle else title)

        print(f"🎵 Playlist → {len(tracks)} piste(s)")
        return tracks
    except:
        return []


def extract_spotify_track_info(track_id):
    """Récupère le titre d'une piste"""
    try:
        url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            title = data.get("title", "")
            artist = data.get("author_name", "")
            return f"{artist} {title}".strip()
    except:
        pass
    return None


# ============================================
# RECHERCHE YOUTUBE + SOUNDCLOUD
# ============================================
async def search_youtube(query):
    """Recherche ULTRA RAPIDE (1 seul appel yt-dlp par source)"""
    if not query.startswith("http"):
        yt_query = f"ytsearch1:{query}"
        sc_query = f"scsearch1:{query}"
    else:
        yt_query = query
        sc_query = query

    loop = asyncio.get_event_loop()

    # === YOUTUBE (1 seul appel, format+URL en même temps) ===
    try:
        def yt_fast():
            cmd = [
                "python", "-m", "yt_dlp",
                "--js-runtimes", "deno",
                "--extractor-args", "youtube:player_client=mweb",
                "--print", "%(title)s|%(webpage_url)s|%(duration)s|%(thumbnail)s|%(url)s",
                "--no-warnings", "--skip-download",
                "--no-playlist",
                yt_query,
            ]
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=15, encoding="utf-8", errors="ignore")

        meta = await loop.run_in_executor(None, yt_fast)

        if meta.returncode == 0 and meta.stdout.strip():
            meta_line = meta.stdout.strip().split("\n")[0]
            parts = meta_line.split("|")
            if len(parts) >= 5 and parts[4].startswith("http"):
                print(f"✅ YT : {parts[0][:45]}")
                return {
                    'title': parts[0],
                    'url': parts[4],
                    'webpage_url': parts[1],
                    'thumbnail': parts[3] if parts[3] != "NA" else "",
                    'duration': int(float(parts[2])) if parts[2] not in ("NA", "") else 0,
                }
    except Exception as e:
        print(f"⚠️ YT : {str(e)[:50]}")

    # === SOUNDCLOUD (1 seul appel) ===
    try:
        def sc_fast():
            cmd = [
                "python", "-m", "yt_dlp",
                "--print", "%(title)s|%(webpage_url)s|%(duration)s|%(thumbnail)s|%(url)s",
                "--no-warnings", "--skip-download",
                "--no-playlist",
                "-f", "bestaudio",
                sc_query,
            ]
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=15, encoding="utf-8", errors="ignore")

        meta = await loop.run_in_executor(None, sc_fast)

        if meta.returncode == 0 and meta.stdout.strip():
            meta_line = meta.stdout.strip().split("\n")[0]
            parts = meta_line.split("|")
            if len(parts) >= 5 and parts[4].startswith("http"):
                print(f"✅ SC : {parts[0][:45]}")
                return {
                    'title': parts[0],
                    'url': parts[4],
                    'webpage_url': parts[1],
                    'thumbnail': parts[3] if parts[3] != "NA" else "",
                    'duration': int(float(parts[2])) if parts[2] not in ("NA", "") else 0,
                }
    except Exception as e:
        print(f"⚠️ SC : {str(e)[:50]}")

    raise Exception(f"Échec : {query[:40]}")


# ============================================
# PANEL NOW PLAYING
# ============================================
class NowPlayingView(discord.ui.LayoutView):
    def __init__(self, guild_id, paused=False):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self._build(paused)

    def _build(self, paused):
        track = now_playing.get(self.guild_id)
        if not track:
            container = discord.ui.Container(accent_color=0x8B5CF6)
            container.add_item(discord.ui.TextDisplay(content="# 🎵 Aucune musique"))
            self.add_item(container)
            return

        duration = track.get('duration', 0)
        elapsed = get_elapsed(self.guild_id)
        queue = get_queue(self.guild_id)
        queue_len = len(queue)
        requester = track.get('requester', 'Inconnu')
        title = track['title']
        if len(title) > 55:
            title = title[:52] + "..."

        container = discord.ui.Container(accent_color=0x8B5CF6)
        status = "⏸️ En pause" if paused else "▶️ En lecture"
        header_text = (
            f"# 🎵 Now Playing\n"
            f"### {title}\n"
            f"👤 **{requester}**\n"
            f"`♪ {fmt_duration(duration)}`  •  `📄 {queue_len} en file`\n"
            f"{status}"
        )

        if track.get('thumbnail'):
            section = discord.ui.Section(
                header_text,
                accessory=discord.ui.Thumbnail(media=track['thumbnail'])
            )
        else:
            section = discord.ui.Section(header_text)
        container.add_item(section)

        if duration > 0:
            bar = make_bar(elapsed, duration)
            container.add_item(discord.ui.TextDisplay(
                content=f"`{fmt_duration(elapsed)}` {bar} `{fmt_duration(duration)}`"
            ))

        if queue:
            container.add_item(discord.ui.Separator())
            queue_text = "**📜 À suivre :**\n"
            for i, t in enumerate(queue[:3]):
                queue_text += f"`{i+1}.` {t['title'][:50]} `[{fmt_duration(t.get('duration'))}]`\n"
            if queue_len > 3:
                queue_text += f"*... et {queue_len - 3} autres*"
            container.add_item(discord.ui.TextDisplay(content=queue_text))

        container.add_item(discord.ui.Separator())

        row1 = discord.ui.ActionRow()
        btn_prev = discord.ui.Button(label="Précédent", emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="mu_prev")
        btn_prev.callback = self.on_prev
        row1.add_item(btn_prev)

        if paused:
            btn_pp = discord.ui.Button(label="Reprendre", emoji="▶️", style=discord.ButtonStyle.primary, custom_id="mu_pp")
        else:
            btn_pp = discord.ui.Button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.success, custom_id="mu_pp")
        btn_pp.callback = self.on_pause
        row1.add_item(btn_pp)

        btn_next = discord.ui.Button(label="Suivant", emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="mu_next")
        btn_next.callback = self.on_next
        row1.add_item(btn_next)
        container.add_item(row1)

        row2 = discord.ui.ActionRow()
        btn_stop = discord.ui.Button(label="Arrêter", emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="mu_stop")
        btn_stop.callback = self.on_stop
        row2.add_item(btn_stop)

        btn_queue = discord.ui.Button(label="File", emoji="📋", style=discord.ButtonStyle.primary, custom_id="mu_queue")
        btn_queue.callback = self.on_queue
        row2.add_item(btn_queue)

        btn_pl = discord.ui.Button(label="Playlist", emoji="🎵", style=discord.ButtonStyle.secondary, custom_id="mu_pl")
        btn_pl.callback = self.on_playlist
        row2.add_item(btn_pl)
        container.add_item(row2)

        row3 = discord.ui.ActionRow()
        btn_search = discord.ui.Button(label="Rechercher", emoji="🔍", style=discord.ButtonStyle.secondary, custom_id="mu_search")
        btn_search.callback = self.on_search
        row3.add_item(btn_search)

        btn_more = discord.ui.Button(label="Plus", emoji="➕", style=discord.ButtonStyle.success, custom_id="mu_more")
        btn_more.callback = self.on_more
        row3.add_item(btn_more)

        btn_fav = discord.ui.Button(label="Favoris", emoji="💖", style=discord.ButtonStyle.secondary, custom_id="mu_fav")
        btn_fav.callback = self.on_fav
        row3.add_item(btn_fav)
        container.add_item(row3)

        row4 = discord.ui.ActionRow()
        btn_vu = discord.ui.Button(label="Volume +", emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="mu_vu")
        btn_vu.callback = self.on_vol_up
        row4.add_item(btn_vu)

        btn_vd = discord.ui.Button(label="Volume -", emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="mu_vd")
        btn_vd.callback = self.on_vol_down
        row4.add_item(btn_vd)

        loop_status = loop_mode.get(self.guild_id, 'off')
        if loop_status != 'off':
            btn_loop = discord.ui.Button(label="Répéter", emoji="🔁", style=discord.ButtonStyle.success, custom_id="mu_loop")
        else:
            btn_loop = discord.ui.Button(label="Répéter", emoji="🔁", style=discord.ButtonStyle.primary, custom_id="mu_loop")
        btn_loop.callback = self.on_loop
        row4.add_item(btn_loop)
        container.add_item(row4)

        self.add_item(container)

    async def on_prev(self, i):
        try: await i.response.send_message("⏮️ Pas d'historique", ephemeral=True)
        except: pass

    async def on_pause(self, i):
        try:
            vc = i.guild.voice_client
            if not vc or (not vc.is_playing() and not vc.is_paused()):
                return await i.response.send_message("❌ Aucune musique", ephemeral=True)
            if vc.is_playing():
                vc.pause(); paused = True
            else:
                vc.resume(); paused = False
            await i.response.edit_message(view=NowPlayingView(self.guild_id, paused=paused))
        except Exception as e:
            print(f"❌ Pause : {e}")

    async def on_next(self, i):
        try:
            vc = i.guild.voice_client
            if vc and (vc.is_playing() or vc.is_paused()):
                vc.stop()
                await i.response.send_message("⏭️ Passée", ephemeral=True)
        except: pass

    async def on_stop(self, i):
        try:
            vc = i.guild.voice_client
            if vc:
                queues[self.guild_id] = []
                now_playing.pop(self.guild_id, None)
                playback_start.pop(self.guild_id, None)
                if vc.is_playing(): vc.stop()
                await vc.disconnect()
            await i.response.send_message("⏹️ Arrêté", ephemeral=True)
        except: pass

    async def on_queue(self, i):
        try:
            queue = get_queue(self.guild_id)
            current = now_playing.get(self.guild_id)
            embed = discord.Embed(title="📋 File d'attente", color=COLOR_MUSIC)
            if current:
                embed.add_field(name="🎵 En cours", value=f"**{current['title'][:60]}**", inline=False)
            if queue:
                text = ""
                for idx, t in enumerate(queue[:10]):
                    text += f"`{idx+1}.` {t['title'][:45]} `[{fmt_duration(t.get('duration'))}]`\n"
                embed.add_field(name=f"📜 À suivre ({len(queue)})", value=text, inline=False)
            else:
                embed.add_field(name="📜 À suivre", value="*File vide*", inline=False)
            await i.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"❌ Queue : {e}")

    async def on_playlist(self, i):
        try: await i.response.send_message("🎵 Playlists bientôt !", ephemeral=True)
        except: pass

    async def on_search(self, i):
        try: await i.response.send_message("🔍 Tape `/play [musique]` !", ephemeral=True)
        except: pass

    async def on_more(self, i):
        try: await i.response.send_message("➕ Tape `/play [musique]` !", ephemeral=True)
        except: pass

    async def on_fav(self, i):
        try:
            track = now_playing.get(self.guild_id)
            if track:
                await i.response.send_message(f"💖 **{track['title'][:50]}** ajouté !", ephemeral=True)
        except: pass

    async def on_vol_up(self, i):
        try:
            vc = i.guild.voice_client
            if not vc or not vc.source: return
            cur = getattr(vc.source, 'volume', 0.5)
            new = min(2.0, cur + 0.1)
            vc.source.volume = new
            await i.response.send_message(f"🔊 {int(new*100)}%", ephemeral=True)
        except: pass

    async def on_vol_down(self, i):
        try:
            vc = i.guild.voice_client
            if not vc or not vc.source: return
            cur = getattr(vc.source, 'volume', 0.5)
            new = max(0.0, cur - 0.1)
            vc.source.volume = new
            await i.response.send_message(f"🔉 {int(new*100)}%", ephemeral=True)
        except: pass

    async def on_loop(self, i):
        try:
            cur = loop_mode.get(self.guild_id, 'off')
            new = {'off': 'track', 'track': 'queue', 'queue': 'off'}[cur]
            loop_mode[self.guild_id] = new
            labels = {'off': 'Désactivé', 'track': 'Musique', 'queue': 'File'}
            await i.response.send_message(f"🔁 {labels[new]}", ephemeral=True)
        except: pass


# ============================================
# LECTURE
# ============================================
async def play_next(ctx, guild_id):
    queue = get_queue(guild_id)
    if not queue:
        now_playing.pop(guild_id, None)
        playback_start.pop(guild_id, None)
        return

    track = queue.pop(0)
    now_playing[guild_id] = track
    playback_start[guild_id] = time.time()

    guild = ctx.guild if hasattr(ctx, 'guild') else None
    channel = ctx.channel if hasattr(ctx, 'channel') else None
    vc = guild.voice_client if guild else None
    if not vc: return

    try:
        source = discord.FFmpegPCMAudio(track['url'], **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=MUSIC_DEFAULT_VOLUME)

        def after_playing(error):
            if error: print(f"❌ {error}")
            mode = loop_mode.get(guild_id, 'off')
            if mode == 'track':
                queue.insert(0, track)
            elif mode == 'queue':
                queue.append(track)
            fut = asyncio.run_coroutine_threadsafe(play_next(ctx, guild_id), vc.client.loop)
            try: fut.result()
            except: pass

        vc.play(source, after=after_playing)
        msg = await channel.send(view=NowPlayingView(guild_id, paused=False))
        panel_messages[guild_id] = msg
        asyncio.create_task(update_panel_loop(guild_id, msg))
    except Exception as e:
        print(f"❌ Erreur play : {e}")


async def update_panel_loop(guild_id, msg):
    try:
        while True:
            await asyncio.sleep(5)
            if not msg.guild: break
            vc = msg.guild.voice_client
            if not vc or (not vc.is_playing() and not vc.is_paused()): break
            if not now_playing.get(guild_id): break
            try:
                await msg.edit(view=NowPlayingView(guild_id, paused=vc.is_paused()))
            except: break
    except asyncio.CancelledError: pass
    except Exception as e: print(f"⚠️ Update : {e}")


async def ensure_voice(interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("❌ Rejoins un salon vocal d'abord !", ephemeral=True)
        return None
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client is None:
        try: await channel.connect()
        except Exception as e:
            await interaction.followup.send(f"❌ Impossible : {e}", ephemeral=True)
            return None
    elif interaction.guild.voice_client.channel != channel:
        try: await interaction.guild.voice_client.move_to(channel)
        except: pass
    return interaction.guild.voice_client



# ============================================
# RECHERCHE PARALLÈLE (5x plus rapide)
# ============================================
async def search_multiple(tracks_list, max_concurrent=6):
    """Recherche plusieurs pistes en parallèle"""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def search_one(query):
        async with semaphore:
            try:
                return await search_youtube(query)
            except Exception as e:
                print(f"❌ {query[:30]} : {str(e)[:50]}")
                return None

    tasks = [search_one(q) for q in tracks_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = []
    for r in results:
        if r and not isinstance(r, Exception):
            valid.append(r)

    return valid
