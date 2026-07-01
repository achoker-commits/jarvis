"""
mac_control.py — Contrôle complet du Mac par JARVIS via AppleScript + subprocess
Navigateur, fichiers, emails, calendrier, système, apps, dictée.
"""

import logging
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires AppleScript
# ─────────────────────────────────────────────────────────────────────────────

def _run_applescript(script: str, timeout: int = 10) -> str:
    """Exécute un script AppleScript et retourne la sortie."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"AppleScript timeout : {script[:60]}")
        return ""
    except Exception as e:
        logger.error(f"AppleScript erreur : {e}")
        return ""


def _run_shell(cmd: list, timeout: int = 10) -> str:
    """Exécute une commande shell et retourne la sortie."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Shell erreur {cmd} : {e}")
        return ""


def _as_str(text: str) -> str:
    """Échappe une chaîne pour insertion sûre dans un literal AppleScript.
    AppleScript ne supporte pas \\\" — on remplace les guillemets par des apostrophes.
    """
    return str(text).replace('"', "'").replace("\\", "/").replace("\n", " ")


# ─────────────────────────────────────────────────────────────────────────────
# Contrôle navigateur (Safari / Chrome)
# ─────────────────────────────────────────────────────────────────────────────

def browser_open_url(url: str, browser: str = "Safari") -> str:
    """Ouvre une URL dans le navigateur par défaut."""
    if not url.startswith("http"):
        url = "https://" + url
    subprocess.Popen(["open", url])
    return f"J'ouvre {url}."


def browser_search(query: str, engine: str = "google") -> str:
    """Lance une recherche web."""
    engines = {
        "google": "https://www.google.com/search?q=",
        "duckduckgo": "https://duckduckgo.com/?q=",
        "youtube": "https://www.youtube.com/results?search_query=",
    }
    base = engines.get(engine, engines["google"])
    url = base + urllib.parse.quote(query)
    subprocess.Popen(["open", url])
    return f"Je recherche '{query}' sur {engine.capitalize()}."


def browser_go_back() -> str:
    script = '''
    tell application "Safari"
        activate
        tell front document to go back
    end tell
    '''
    _run_applescript(script)
    return "Page précédente."


def browser_reload() -> str:
    script = 'tell application "Safari" to activate\ntell application "System Events" to key code 15 using command down'
    _run_applescript(script)
    return "Page rechargée."


def browser_get_current_url() -> str:
    script = 'tell application "Safari" to return URL of front document'
    return _run_applescript(script) or "Impossible de lire l'URL."


def browser_get_page_title() -> str:
    script = 'tell application "Safari" to return name of front document'
    title = _run_applescript(script)
    return f"Page actuelle : {title}." if title else "Safari n'est pas ouvert."


def browser_open_youtube(query: str = "") -> str:
    if query:
        return browser_search(query, "youtube")
    subprocess.Popen(["open", "https://www.youtube.com"])
    return "J'ouvre YouTube."


def browser_new_tab(url: str = "") -> str:
    if url and not url.startswith("http"):
        url = "https://" + url
    script = f'''
    tell application "Safari"
        activate
        make new document with properties {{URL:"{url}"}}
    end tell
    '''
    _run_applescript(script)
    return f"Nouvel onglet ouvert{' sur ' + url if url else ''}."


# ─────────────────────────────────────────────────────────────────────────────
# Gestion fichiers & dossiers
# ─────────────────────────────────────────────────────────────────────────────

def file_open(path: str) -> str:
    """Ouvre un fichier ou dossier avec l'app par défaut."""
    expanded = os.path.expanduser(path)
    if os.path.exists(expanded):
        subprocess.Popen(["open", expanded])
        return f"J'ouvre {path}."
    # Chercher dans les emplacements courants
    for base in [Path.home(), Path.home() / "Documents", Path.home() / "Desktop"]:
        candidate = base / path
        if candidate.exists():
            subprocess.Popen(["open", str(candidate)])
            return f"J'ouvre {candidate.name}."
    return f"Je n'ai pas trouvé '{path}'."


def file_open_folder(folder: str = "Desktop") -> str:
    """Ouvre un dossier dans Finder."""
    folders = {
        "bureau": str(Path.home() / "Desktop"),
        "desktop": str(Path.home() / "Desktop"),
        "documents": str(Path.home() / "Documents"),
        "téléchargements": str(Path.home() / "Downloads"),
        "downloads": str(Path.home() / "Downloads"),
        "projets": str(Path.home() / "projets"),
        "images": str(Path.home() / "Pictures"),
        "musique": str(Path.home() / "Music"),
        "home": str(Path.home()),
    }
    path = folders.get(folder.lower().strip(), os.path.expanduser(folder))
    subprocess.Popen(["open", path])
    return f"J'ouvre le dossier {folder}."


def file_create_note(name: str, content: str = "") -> str:
    """Crée un fichier texte sur le bureau."""
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)
    if not safe_name.endswith(".txt"):
        safe_name += ".txt"
    path = Path.home() / "Desktop" / safe_name
    path.write_text(content or f"Note créée par JARVIS le {datetime.now().strftime('%d/%m/%Y %H:%M')}\n",
                    encoding="utf-8")
    return f"Fichier '{safe_name}' créé sur votre bureau."


def file_list_desktop() -> str:
    """Liste les fichiers sur le bureau."""
    desktop = Path.home() / "Desktop"
    items = [f.name for f in desktop.iterdir() if not f.name.startswith(".")]
    if not items:
        return "Votre bureau est vide."
    return f"Sur votre bureau : {', '.join(items[:8])}{'...' if len(items) > 8 else ''}."


def file_take_screenshot() -> str:
    """Prend une capture d'écran et la sauvegarde sur le bureau."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(Path.home() / "Desktop" / f"JARVIS_screenshot_{timestamp}.png")
    _run_shell(["screencapture", "-x", path])
    return f"Capture d'écran sauvegardée sur le bureau."


def finder_search(query: str) -> str:
    """Ouvre une recherche Spotlight."""
    script = f'''
    tell application "System Events"
        key code 49 using command down
    end tell
    delay 0.5
    tell application "System Events"
        keystroke "{_as_str(query)}"
    end tell
    '''
    _run_applescript(script)
    return f"Je cherche '{query}' avec Spotlight."


# ─────────────────────────────────────────────────────────────────────────────
# Email (Mail.app)
# ─────────────────────────────────────────────────────────────────────────────

def email_get_unread_count() -> str:
    """Retourne le nombre d'emails non lus."""
    script = '''
    tell application "Mail"
        set unread_count to unread count of inbox
        return unread_count as string
    end tell
    '''
    count = _run_applescript(script)
    if count and count.isdigit():
        n = int(count)
        if n == 0:
            return "Aucun email non lu."
        return f"Vous avez {n} email{'s' if n > 1 else ''} non lu{'s' if n > 1 else ''}."
    return "Je ne peux pas accéder à Mail pour l'instant."


def email_get_latest(n: int = 3) -> str:
    """Lit les derniers emails."""
    script = f'''
    tell application "Mail"
        set msgs to messages of inbox
        set result_str to ""
        repeat with i from 1 to {n}
            if i ≤ (count of msgs) then
                set msg to item i of msgs
                set result_str to result_str & (sender of msg) & ": " & (subject of msg) & "\\n"
            end if
        end repeat
        return result_str
    end tell
    '''
    result = _run_applescript(script, timeout=15)
    if result:
        lines = [l.strip() for l in result.split("\n") if l.strip()]
        if lines:
            return "Derniers emails : " + ". ".join(lines[:n]) + "."
    return "Impossible de lire vos emails. Vérifiez que Mail est configuré."


def email_compose(to: str = "", subject: str = "", body: str = "") -> str:
    """Ouvre un nouvel email dans Mail.app."""
    to_s, subj_s, body_s = _as_str(to), _as_str(subject), _as_str(body)
    script = f'''
    tell application "Mail"
        activate
        set new_msg to make new outgoing message with properties {{subject:"{subj_s}", content:"{body_s}", visible:true}}
        if "{to_s}" is not "" then
            tell new_msg
                make new to recipient with properties {{address:"{to_s}"}}
            end tell
        end if
    end tell
    '''
    _run_applescript(script)
    to_str = f" à {to}" if to else ""
    return f"Email ouvert{to_str} avec le sujet '{subject}'."


# ─────────────────────────────────────────────────────────────────────────────
# Calendrier (Calendar.app)
# ─────────────────────────────────────────────────────────────────────────────

def calendar_get_today() -> str:
    """Lit les événements d'aujourd'hui."""
    today = datetime.now().strftime("%B %d, %Y")
    script = f'''
    tell application "Calendar"
        set today_start to current date
        set hours of today_start to 0
        set minutes of today_start to 0
        set seconds of today_start to 0
        set today_end to today_start + (24 * 60 * 60)

        set event_list to ""
        repeat with cal in calendars
            repeat with ev in (events of cal whose start date ≥ today_start and start date < today_end)
                set event_list to event_list & (summary of ev) & " à " & (time string of start date of ev) & "\\n"
            end repeat
        end repeat
        return event_list
    end tell
    '''
    result = _run_applescript(script, timeout=15)
    if result and result.strip():
        events = [e.strip() for e in result.split("\n") if e.strip()]
        return f"Aujourd'hui : {', '.join(events[:5])}."
    return "Aucun événement aujourd'hui."


def calendar_add_event(title: str, date_str: str = "", time_str: str = "") -> str:
    """Ajoute un événement au calendrier."""
    if not date_str:
        date_str = datetime.now().strftime("%d/%m/%Y")
    if not time_str:
        time_str = "09:00"

    title_s = _as_str(title)
    script = f'''
    tell application "Calendar"
        activate
        tell calendar "Calendrier"
            set new_event to make new event with properties {{summary:"{title_s}"}}
        end tell
    end tell
    '''
    _run_applescript(script)
    return f"Événement '{title}' ajouté. Vérifiez votre calendrier pour régler l'heure exacte."


# ─────────────────────────────────────────────────────────────────────────────
# Contrôle système
# ─────────────────────────────────────────────────────────────────────────────

def system_set_volume(level: int) -> str:
    level = max(0, min(100, level))
    _run_shell(["osascript", "-e", f"set volume output volume {level}"])
    return f"Volume à {level}%."


def system_mute() -> str:
    _run_shell(["osascript", "-e", "set volume output muted true"])
    return "Son coupé."


def system_unmute() -> str:
    _run_shell(["osascript", "-e", "set volume output muted false"])
    return "Son rétabli."


def system_set_brightness(level: int) -> str:
    """Règle la luminosité (0-100)."""
    level = max(0, min(100, level))
    fraction = level / 100.0
    script = f'tell application "System Events" to set brightness to {fraction}'
    result = _run_shell(["osascript", "-e", script])
    return f"Luminosité à {level}%."


def system_sleep() -> str:
    """Met le Mac en veille."""
    _run_shell(["osascript", "-e", 'tell application "System Events" to sleep'])
    return "Mise en veille."


def system_lock_screen() -> str:
    """Verrouille l'écran."""
    _run_shell(["osascript", "-e",
                'tell application "System Events" to keystroke "q" using {command down, control down}'])
    return "Écran verrouillé."


def system_empty_trash() -> str:
    """Vide la corbeille."""
    script = 'tell application "Finder" to empty trash'
    _run_applescript(script)
    return "Corbeille vidée."


def system_show_desktop() -> str:
    """Affiche le bureau (Mission Control)."""
    _run_shell(["osascript", "-e",
                'tell application "System Events" to key code 103 using {command down}'])
    return "Bureau affiché."


def system_wifi_status() -> str:
    """Retourne le statut WiFi."""
    out = _run_shell(["networksetup", "-getairportnetwork", "en0"])
    if "Current Wi-Fi Network" in out:
        network = out.split(": ", 1)[-1]
        return f"Connecté au réseau WiFi : {network}."
    return "WiFi non connecté ou indisponible."


def app_open(name: str) -> str:
    """Ouvre une application par nom ou un site web si c'est un service en ligne."""
    # Sites web (ouverts dans le navigateur par défaut)
    web_map = {
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "linkedin": "https://www.linkedin.com",
        "twitter": "https://www.x.com",
        "x.com": "https://www.x.com",
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "google drive": "https://drive.google.com",
        "google docs": "https://docs.google.com",
        "google sheets": "https://sheets.google.com",
        "google calendar": "https://calendar.google.com",
        "google maps": "https://maps.google.com",
        "chatgpt": "https://chat.openai.com",
        "nexatel": "https://nexatel-choker.netlify.app",
        "mon site": "https://nexatel-choker.netlify.app",
        "netlify": "https://app.netlify.com",
        "groq": "https://console.groq.com",
        "github": "https://github.com",
        "tiktok": "https://www.tiktok.com",
        "reddit": "https://www.reddit.com",
        "proximus": "https://www.proximus.be",
        "my proximus": "https://www.proximus.be/fr/id_cr_myprodpack/particuliers/produits-et-offres/mon-proximus.html",
        "google my business": "https://business.google.com",
        "gmb": "https://business.google.com",
        "ma fiche google": "https://business.google.com",
        "canva": "https://www.canva.com",
        "selectra": "https://selectra.be",
        "trello": "https://trello.com",
        "whatsapp web": "https://web.whatsapp.com",
        "claude.ai": "https://claude.ai",
    }
    # Applications natives Mac
    app_map = {
        "spotify": "Spotify", "safari": "Safari",
        "chrome": "Google Chrome", "firefox": "Firefox", "brave": "Brave Browser", "arc": "Arc",
        "messages": "Messages", "mail": "Mail",
        "notes": "Notes", "calendrier": "Calendar", "calendar": "Calendar",
        "terminal": "Terminal", "iterm": "iTerm2", "finder": "Finder",
        "musique": "Music", "music": "Music", "photos": "Photos",
        "vscode": "Visual Studio Code", "vs code": "Visual Studio Code", "code": "Visual Studio Code",
        "cursor": "Cursor", "claude": "Claude",
        "obsidian": "Obsidian",
        "whatsapp": "WhatsApp", "teams": "Microsoft Teams",
        "word": "Microsoft Word", "excel": "Microsoft Excel",
        "powerpoint": "Microsoft PowerPoint", "keynote": "Keynote",
        "numbers": "Numbers", "pages": "Pages",
        "notion": "Notion", "slack": "Slack", "discord": "Discord",
        "telegram": "Telegram", "signal": "Signal",
        "zoom": "zoom.us", "facetime": "FaceTime",
        "réglages": "System Settings", "préférences": "System Settings",
        "calculatrice": "Calculator", "horloge": "Clock",
        "activity monitor": "Activity Monitor", "activité": "Activity Monitor",
        "moniteur": "Activity Monitor",
        "xcode": "Xcode", "imovie": "iMovie", "garageband": "GarageBand",
        "1password": "1Password", "raycast": "Raycast",
        "bear": "Bear", "ulysses": "Ulysses",
        "vlc": "VLC", "iina": "IINA",
        "figma": "Figma", "sketch": "Sketch",
        "postman": "Postman", "tableplus": "TablePlus",
    }

    app_name = name.lower().strip()

    # Vérifier les sites web en premier
    for key, url in web_map.items():
        if key in app_name:
            subprocess.Popen(["open", url])
            return f"J'ouvre {key.capitalize()} dans votre navigateur."

    # Puis les apps natives
    real_name = None
    for key, val in app_map.items():
        if key in app_name:
            real_name = val
            break
    if not real_name:
        real_name = name.strip().title()
    try:
        result = subprocess.run(
            ["open", "-a", real_name],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0:
            return f"{real_name} est ouvert."
        # Essayer avec le nom original (cas sensibles)
        result2 = subprocess.run(
            ["open", "-a", name.strip()],
            capture_output=True, text=True, timeout=8
        )
        if result2.returncode == 0:
            return f"{name.strip()} est ouvert."
        return f"Je n'arrive pas à ouvrir '{name}'. Vérifiez que l'application est installée."
    except Exception as e:
        logger.warning(f"app_open {name!r} erreur : {e}")
        return f"Impossible d'ouvrir '{name}'."


def app_quit(name: str) -> str:
    """Quitte une application."""
    script = f'tell application "{name}" to quit'
    _run_applescript(script)
    return f"{name} fermé."


def app_list_running() -> str:
    """Liste les applications actuellement ouvertes."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of every application process whose background only is false'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            apps = [a.strip() for a in result.stdout.strip().split(",") if a.strip()]
            # Filtrer les apps système non pertinentes
            ignore = {"Dock", "SystemUIServer", "Finder", "loginwindow", "AXVisualSupportAgent"}
            apps = [a for a in apps if a not in ignore]
            if apps:
                return "Applications ouvertes : " + ", ".join(apps[:12]) + "."
    except Exception:
        pass
    return "Impossible de lister les applications ouvertes."


def app_switch(name: str) -> str:
    """Bascule vers une application ouverte."""
    script = f'tell application "{name}" to activate'
    _run_applescript(script)
    return f"Passage à {name}."


def dictate_text(text: str) -> str:
    """Tape du texte dans l'application active."""
    script = f'tell application "System Events" to keystroke "{_as_str(text)}"'
    _run_applescript(script)
    return f"Texte saisi : {text[:40]}."


def clipboard_set(text: str) -> str:
    """Copie du texte dans le presse-papier."""
    subprocess.run(["pbcopy"], input=text.encode(), check=True)
    return "Texte copié dans le presse-papier."


def clipboard_get() -> str:
    """Lit le contenu du presse-papier."""
    result = _run_shell(["pbpaste"])
    if result:
        return f"Presse-papier : {result[:100]}."
    return "Presse-papier vide."


def notification_send(title: str, message: str) -> None:
    """Envoie une notification macOS."""
    script = f'display notification "{_as_str(message)}" with title "{_as_str(title)}"'
    _run_applescript(script)


# ─────────────────────────────────────────────────────────────────────────────
# Spotify control via AppleScript
# ─────────────────────────────────────────────────────────────────────────────

def spotify_play_pause() -> str:
    script = 'tell application "Spotify" to playpause'
    _run_applescript(script)
    return "Lecture/pause."


def spotify_next() -> str:
    script = 'tell application "Spotify" to next track'
    _run_applescript(script)
    return "Piste suivante."


def spotify_previous() -> str:
    script = 'tell application "Spotify" to previous track'
    _run_applescript(script)
    return "Piste précédente."


def spotify_current_track() -> str:
    # Vérifier d'abord si Spotify est ouvert
    check = _run_applescript('tell application "System Events" to (name of processes) contains "Spotify"')
    if check != "true":
        return "Spotify n'est pas ouvert."
    script = '''
    tell application "Spotify"
        if player state is playing then
            set track_name to name of current track
            set artist_name to artist of current track
            return artist_name & " - " & track_name
        else
            return "en pause"
        end if
    end tell
    '''
    result = _run_applescript(script)
    if not result:
        return "Impossible de lire Spotify."
    if result == "en pause":
        return "Spotify est en pause."
    return f"En cours : {result}."


def system_dark_mode(enable: bool = True) -> str:
    """Active ou désactive le mode sombre macOS."""
    state = "true" if enable else "false"
    script = f'tell application "System Events" to tell appearance preferences to set dark mode to {state}'
    _run_applescript(script)
    return f"Mode {'sombre' if enable else 'clair'} activé."


def system_do_not_disturb(enable: bool = True) -> str:
    """Active ou désactive Ne pas déranger (Focus mode macOS 12+)."""
    # Sur macOS Ventura+, utiliser le raccourci Focus
    # Fallback : notification de statut
    try:
        # Méthode Shortcuts si disponible
        action = "on" if enable else "off"
        subprocess.run(
            ["shortcuts", "run", f"Do Not Disturb {action}"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass
    return f"Mode {'Ne pas déranger activé' if enable else 'Notifications rétablies'}."


def spotify_search_play(query: str) -> str:
    """Lance une recherche sur Spotify et commence la lecture."""
    url = f"spotify:search:{urllib.parse.quote(query)}"
    subprocess.Popen(["open", url])
    time.sleep(1.5)  # Réduit de 2.5s → 1.5s
    script = '''
    tell application "Spotify" to activate
    delay 0.8
    tell application "System Events"
        tell process "Spotify"
            key code 36
        end tell
    end tell
    '''
    _run_applescript(script)
    return f"Je lance '{query}' sur Spotify."


def spotify_play_artist_radio(artist: str) -> str:
    """Joue une radio d'artiste sur Spotify."""
    url = f"spotify:search:{urllib.parse.quote(artist)}"
    subprocess.Popen(["open", url])
    return f"Recherche de musique de {artist} sur Spotify."
