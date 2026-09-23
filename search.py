import yt_dlp
import subprocess
import asyncio


async def search_audio(query):
    """Cherche l'audio : YouTube d'abord, SoundCloud en secours"""

    # === 1. ESSAI YOUTUBE ===
    try:
        result = await try_youtube(query)
        if result:
            print(f"✅ YouTube : {result['title']}")
            return result
    except Exception as e:
        print(f"⚠️ YouTube échoué : {str(e)[:100]}")

    # === 2. FALLBACK SOUNDCLOUD ===
    try:
        result = await try_soundcloud(query)
        if result:
            print(f"✅ SoundCloud : {result['title']}")
            return result
    except Exception as e:
        print(f"⚠️ SoundCloud échoué : {str(e)[:100]}")

    raise Exception("Impossible de trouver l'audio")


async def try_youtube(query):
    """Recherche sur YouTube via yt-dlp"""
    if not query.startswith("http"):
        search_query = f"ytsearch1:{query}"
    else:
        search_query = query

    loop = asyncio.get_event_loop()

    def run():
        cmd = [
            "python", "-m", "yt_dlp",
            "--js-runtimes", "deno",
            "--extractor-args", "youtube:player_client=android_vr",
            "--print", "%(title)s|%(webpage_url)s|%(duration)s|%(thumbnail)s",
            "--no-warnings", "--skip-download",
            search_query,
        ]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30, encoding="utf-8", errors="ignore")

    result = await loop.run_in_executor(None, run)
    if result.returncode != 0:
        raise Exception(result.stderr[:200])

    line = result.stdout.strip().split("\n")[0]
    parts = line.split("|")
    if len(parts) < 4:
        raise Exception("Format invalide")

    # Récupère l'URL audio
    def run_url():
        cmd = [
            "python", "-m", "yt_dlp",
            "--js-runtimes", "deno",
            "--extractor-args", "youtube:player_client=android_vr",
            "--get-url", "-f", "bestaudio",
            "--no-warnings", search_query,
        ]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30, encoding="utf-8", errors="ignore")

    url_result = await loop.run_in_executor(None, run_url)
    if url_result.returncode != 0:
        raise Exception(url_result.stderr[:200])

    audio_url = url_result.stdout.strip().split("\n")[0]
    if not audio_url.startswith("http"):
        raise Exception("URL invalide")

    return {
        'title': parts[0],
        'url': audio_url,
        'webpage_url': parts[1],
        'thumbnail': parts[3] if parts[3] != "NA" else "",
        'duration': int(parts[2]) if parts[2] not in ("NA", "") else 0,
        'source': 'YouTube',
    }


async def try_soundcloud(query):
    """Recherche sur SoundCloud via yt-dlp"""
    search_query = f"scsearch1:{query}"

    loop = asyncio.get_event_loop()

    def run_meta():
        cmd = [
            "python", "-m", "yt_dlp",
            "--print", "%(title)s|%(webpage_url)s|%(duration)s|%(thumbnail)s",
            "--no-warnings", "--skip-download",
            search_query,
        ]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30, encoding="utf-8", errors="ignore")

    result = await loop.run_in_executor(None, run_meta)
    if result.returncode != 0:
        raise Exception(result.stderr[:200])

    line = result.stdout.strip().split("\n")[0]
    parts = line.split("|")
    if len(parts) < 4:
        raise Exception("Format SoundCloud invalide")

    # URL audio SoundCloud
    def run_url():
        cmd = [
            "python", "-m", "yt_dlp",
            "--get-url", "-f", "bestaudio",
            "--no-warnings", search_query,
        ]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30, encoding="utf-8", errors="ignore")

    url_result = await loop.run_in_executor(None, run_url)
    if url_result.returncode != 0:
        raise Exception(url_result.stderr[:200])

    audio_url = url_result.stdout.strip().split("\n")[0]
    if not audio_url.startswith("http"):
        raise Exception("URL SoundCloud invalide")

    return {
        'title': parts[0],
        'url': audio_url,
        'webpage_url': parts[1],
        'thumbnail': parts[3] if parts[3] != "NA" else "",
        'duration': int(parts[2]) if parts[2] not in ("NA", "") else 0,
        'source': 'SoundCloud',
    }