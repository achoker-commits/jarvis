"""
jarvis_tools.py — Définition des outils disponibles pour JARVIS via Groq tool calling.
Le LLM comprend l'intention et choisit lui-même quelle fonction appeler.
"""

import json
import logging
import time
from typing import Any

from mac_control import (
    app_open, app_quit, app_switch, app_list_running,
    browser_open_url, browser_search, browser_go_back, browser_reload,
    browser_get_page_title, browser_open_youtube, browser_new_tab,
    file_open, file_open_folder, file_create_note, file_list_desktop,
    file_take_screenshot, finder_search,
    email_get_unread_count, email_get_latest, email_compose,
    calendar_get_today, calendar_add_event,
    system_set_volume, system_mute, system_unmute, system_sleep,
    system_lock_screen, system_empty_trash, system_wifi_status, system_set_brightness,
    system_dark_mode, system_do_not_disturb, system_show_desktop,
    spotify_play_pause, spotify_next, spotify_previous,
    spotify_current_track, spotify_search_play, spotify_play_artist_radio,
    dictate_text, clipboard_set, clipboard_get, notification_send,
)

logger = logging.getLogger(__name__)

# Cache météo : {clé_ville: (timestamp, résultat)} — TTL 30 min
_WEATHER_CACHE: dict = {}
_WEATHER_TTL = 1800  # 30 minutes

# Cache devises : {clé_devise: (timestamp, résultat)} — TTL 20 min
_DEVISE_CACHE: dict = {}
_DEVISE_TTL = 1200  # 20 minutes

# ─────────────────────────────────────────────────────────────────────────────
# Définition des outils (format Groq/OpenAI function calling)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ouvrir_application",
            "description": "Ouvre, lance ou bascule vers une application sur le Mac. Utiliser quand l'utilisateur veut ouvrir, lancer, démarrer, ou passer à une app (Spotify, Chrome, Mail, Notes, Terminal, Word, Finder, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Nom de l'application à ouvrir ou vers laquelle basculer"},
                    "action": {"type": "string", "description": "ouvrir (défaut), basculer (passer à une app déjà ouverte), lister (lister les apps ouvertes)", "enum": ["ouvrir", "basculer", "lister"]},
                },
                "required": ["nom"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fermer_application",
            "description": "Quitte ou ferme une application",
            "parameters": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Nom de l'application à fermer"},
                },
                "required": ["nom"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ouvrir_site_web",
            "description": "Ouvre un site web ou une URL dans le navigateur",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL ou nom du site (ex: youtube.com, google.com)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rechercher_sur_internet",
            "description": "Effectue une recherche sur Google ou YouTube. Utiliser quand l'utilisateur veut chercher quelque chose en ligne, trouver une vidéo, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {"type": "string", "description": "Ce qu'il faut rechercher"},
                    "moteur": {"type": "string", "description": "google ou youtube", "enum": ["google", "youtube", "duckduckgo"]},
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "musique_spotify",
            "description": "Contrôle Spotify : jouer/pause, chanson suivante, précédente, chercher un artiste ou une chanson",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "L'action à effectuer",
                        "enum": ["play_pause", "suivant", "precedent", "chanson_actuelle", "chercher", "radio_artiste"],
                    },
                    "recherche": {"type": "string", "description": "Artiste, chanson ou genre à chercher (pour action=chercher ou radio_artiste)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emails",
            "description": "Gère les emails : lire les non lus, voir les derniers emails, écrire un nouvel email",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "L'action",
                        "enum": ["compter_non_lus", "lire_derniers", "ecrire"],
                    },
                    "destinataire": {"type": "string", "description": "Adresse email du destinataire (pour écrire)"},
                    "sujet": {"type": "string", "description": "Sujet de l'email (pour écrire)"},
                    "corps": {"type": "string", "description": "Contenu de l'email (pour écrire)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendrier",
            "description": "Consulte ou ajoute des événements au calendrier",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "lire (voir les événements du jour) ou ajouter",
                        "enum": ["lire", "ajouter"],
                    },
                    "titre": {"type": "string", "description": "Titre de l'événement (pour ajouter)"},
                    "date": {"type": "string", "description": "Date de l'événement (pour ajouter)"},
                    "heure": {"type": "string", "description": "Heure de l'événement (pour ajouter)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fichiers",
            "description": "Gère les fichiers et dossiers : ouvrir un fichier, ouvrir un dossier, créer une note, lister le bureau, prendre une capture d'écran, décrire l'écran",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "L'action à effectuer",
                        "enum": ["ouvrir_fichier", "ouvrir_dossier", "creer_note", "lister_bureau", "screenshot", "rechercher", "decrire_ecran"],
                    },
                    "nom": {"type": "string", "description": "Nom du fichier, dossier ou terme de recherche"},
                    "contenu": {"type": "string", "description": "Contenu de la note (pour creer_note)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume",
            "description": "Contrôle le volume sonore du Mac. TOUJOURS utiliser cet outil pour changer le volume — ne jamais simuler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "monter (+20%), baisser (-20%), couper (mute), remettre (unmute), definir (niveau précis)",
                        "enum": ["monter", "baisser", "couper", "remettre", "definir"],
                    },
                    "niveau": {"type": "integer", "description": "Niveau entre 0 et 100 (obligatoire pour action=definir)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "systeme",
            "description": "Actions système et infos temps réel. TOUJOURS utiliser pour batterie/WiFi/CPU/RAM — données dynamiques, ne jamais inventer. Aussi : veille, verrouillage, corbeille, presse-papier, luminosité.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "L'action système à effectuer",
                        "enum": ["veille", "verrouiller", "vider_corbeille", "wifi", "batterie", "cpu_ram",
                                 "presse_papier_lire", "presse_papier_ecrire", "luminosite", "screenshot",
                                 "mode_sombre", "mode_clair", "ne_pas_deranger", "reactiver_notifs",
                                 "montre_bureau"],
                    },
                    "texte": {"type": "string", "description": "Texte à copier (pour presse_papier_ecrire)"},
                    "niveau": {"type": "integer", "description": "Niveau 0-100 pour la luminosité"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "meteo",
            "description": "Donne la météo actuelle et les prévisions. Si l'utilisateur demande 'météo pour la semaine', 'prévisions', '5 jours', passer jours=5. Sinon jours=2 (aujourd'hui + demain).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ville": {"type": "string", "description": "Ville (défaut: Charleroi)"},
                    "jours": {"type": "integer", "description": "Nombre de jours de prévision (1=aujourd'hui seulement, 2=demain inclus, 5=semaine). Défaut: 2"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "minuteur",
            "description": "Lance un minuteur après un délai relatif (ex: 'dans 10 minutes', 'dans 1 heure'). Pour une heure précise ('à 8h30', 'à 14h'), utilise l'outil alarme.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duree_secondes": {"type": "integer", "description": "Durée en secondes"},
                    "message": {"type": "string", "description": "Message à annoncer quand le minuteur se termine"},
                },
                "required": ["duree_secondes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alarme",
            "description": "Programme une alarme à une heure précise de la journée (ex: 'à 8h30', 'à 14h', 'à 7h du matin'). Utiliser quand l'utilisateur mentionne une heure fixe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "heure": {"type": "integer", "description": "Heure (0-23)"},
                    "minute": {"type": "integer", "description": "Minute (0-59), défaut 0"},
                    "message": {"type": "string", "description": "Message à annoncer (ex: 'Réveil, monsieur.')"},
                },
                "required": ["heure"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memoriser",
            "description": "Mémorise une information importante de façon permanente pour les prochaines sessions",
            "parameters": {
                "type": "object",
                "properties": {
                    "information": {"type": "string", "description": "L'information à mémoriser"},
                },
                "required": ["information"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualites",
            "description": "Récupère les dernières actualités / nouvelles du jour. Peut cibler les news télécom (Proximus, Orange, VOO, IBPT) si le sujet le concerne.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sujet": {
                        "type": "string",
                        "description": "Sujet optionnel pour orienter la source (ex: 'proximus', 'télécom', 'belgique', 'sport')",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recherche_info",
            "description": "Recherche une information en temps réel sur internet et retourne la réponse directement (sans ouvrir de navigateur). Utiliser pour TOUTE question factuelle ou d'actualité : prix, personnes, événements, sport, news, définitions, statistiques, météo passée, résultats, faits récents. Ex: 'prix du bitcoin', 'résultats PSG hier', 'qui est le président américain', 'population Paris', 'actualité Belgique'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {"type": "string", "description": "Question ou terme à rechercher"},
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obsidian",
            "description": "Interagit avec le vault Obsidian personnel de l'utilisateur. Chercher des notes ('qui est ce contact', 'mes clients', 'mon agenda'), créer une note rapide, ou voir les tâches du jour.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "chercher (recherche), lire_note (lit le contenu complet d'une note), note_rapide (créer une note), agenda (tâches du jour)",
                        "enum": ["chercher", "lire_note", "note_rapide", "agenda"],
                    },
                    "requete": {"type": "string", "description": "Terme de recherche ou contenu de la note"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "devises",
            "description": "Donne le taux de change en temps réel entre des devises. Utiliser quand l'utilisateur demande le taux EUR/USD, combien font X euros en dollars, ou toute conversion de monnaie.",
            "parameters": {
                "type": "object",
                "properties": {
                    "montant": {"type": "number", "description": "Montant à convertir (défaut: 1)"},
                    "de": {"type": "string", "description": "Devise source (ex: EUR, USD, MAD, GBP)"},
                    "vers": {"type": "string", "description": "Devises cibles séparées par virgule (ex: USD,MAD,GBP)"},
                },
                "required": ["de"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notification",
            "description": "Envoie une notification système macOS. Utiliser pour envoyer une alerte visible, confirmer une action importante, ou informer qu'une tâche est terminée.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titre": {"type": "string", "description": "Titre de la notification (ex: 'JARVIS', 'Rappel NexaTel')"},
                    "message": {"type": "string", "description": "Corps de la notification"},
                },
                "required": ["titre", "message"],
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Vision : screenshot + description Groq
# ─────────────────────────────────────────────────────────────────────────────

def _describe_screen_groq() -> str:
    """Prend une capture d'écran et la décrit via Groq Vision (llava gratuit)."""
    import os, base64, tempfile, subprocess, requests as _req
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        subprocess.run(["screencapture", "-x", "-t", "png", tmp_path], check=True, capture_output=True)

        with open(tmp_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            return "Clé Groq non configurée — impossible d'analyser l'écran."

        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Décris ce qui est affiché à l'écran en 2-3 phrases courtes. Sois précis sur les applications ouvertes, le texte visible, et ce que l'utilisateur est en train de faire. Réponds en français."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            "max_tokens": 200,
        }
        resp = _req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"decrire_ecran erreur : {e}")
        return "Impossible d'analyser l'écran."


# ─────────────────────────────────────────────────────────────────────────────
# Exécution des outils
# ─────────────────────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict, persistent_memory=None, tts=None) -> str:
    """Exécute un outil et retourne le résultat textuel."""
    try:
        if name == "ouvrir_application":
            action = args.get("action", "ouvrir")
            nom = args.get("nom", "")
            if action == "basculer":
                return app_switch(nom)
            if action == "lister":
                return app_list_running()
            return app_open(nom)

        elif name == "fermer_application":
            return app_quit(args.get("nom", ""))

        elif name == "ouvrir_site_web":
            return browser_open_url(args.get("url", ""))

        elif name == "rechercher_sur_internet":
            return browser_search(args.get("requete", ""), args.get("moteur", "google"))

        elif name == "musique_spotify":
            action = args.get("action", "")
            recherche = args.get("recherche", "")
            if action == "play_pause":
                return spotify_play_pause()
            elif action == "suivant":
                return spotify_next()
            elif action == "precedent":
                return spotify_previous()
            elif action == "chanson_actuelle":
                return spotify_current_track()
            elif action == "chercher":
                return spotify_search_play(recherche)
            elif action == "radio_artiste":
                return spotify_play_artist_radio(recherche) if recherche else spotify_search_play("mix du moment")
            return "Action Spotify inconnue."

        elif name == "emails":
            action = args.get("action", "")
            if action == "compter_non_lus":
                return email_get_unread_count()
            elif action == "lire_derniers":
                return email_get_latest(3)
            elif action == "ecrire":
                return email_compose(
                    to=args.get("destinataire", ""),
                    subject=args.get("sujet", ""),
                    body=args.get("corps", ""),
                )
            return "Action email inconnue."

        elif name == "calendrier":
            action = args.get("action", "")
            if action == "lire":
                return calendar_get_today()
            elif action == "ajouter":
                return calendar_add_event(
                    title=args.get("titre", "Événement"),
                    date_str=args.get("date", ""),
                    time_str=args.get("heure", ""),
                )
            return "Action calendrier inconnue."

        elif name == "fichiers":
            action = args.get("action", "")
            nom = args.get("nom", "")
            if action == "ouvrir_fichier":
                return file_open(nom)
            elif action == "ouvrir_dossier":
                return file_open_folder(nom or "Desktop")
            elif action == "creer_note":
                return file_create_note(nom or "Note", args.get("contenu", ""))
            elif action == "lister_bureau":
                return file_list_desktop()
            elif action == "screenshot":
                return file_take_screenshot()
            elif action == "decrire_ecran":
                return _describe_screen_groq()
            elif action == "rechercher":
                return finder_search(nom)
            return "Action fichier inconnue."

        elif name == "volume":
            action = args.get("action", "")
            niveau = args.get("niveau", 50)
            if action == "couper":
                return system_mute()
            elif action == "remettre":
                return system_unmute()
            elif action == "monter":
                import subprocess
                subprocess.run(["osascript", "-e",
                    "set volume output volume (output volume of (get volume settings) + 20)"],
                    capture_output=True)
                return "Volume augmenté."
            elif action == "baisser":
                import subprocess
                subprocess.run(["osascript", "-e",
                    "set volume output volume (output volume of (get volume settings) - 20)"],
                    capture_output=True)
                return "Volume réduit."
            elif action == "definir":
                return system_set_volume(niveau)
            return "Action volume inconnue."

        elif name == "systeme":
            action = args.get("action", "")
            if action == "veille":
                return system_sleep()
            elif action == "verrouiller":
                return system_lock_screen()
            elif action == "vider_corbeille":
                return system_empty_trash()
            elif action == "wifi":
                return system_wifi_status()
            elif action == "mode_sombre":
                return system_dark_mode(True)
            elif action == "mode_clair":
                return system_dark_mode(False)
            elif action == "ne_pas_deranger":
                return system_do_not_disturb(True)
            elif action == "reactiver_notifs":
                return system_do_not_disturb(False)
            elif action == "montre_bureau":
                return system_show_desktop()
            elif action == "batterie":
                # macOS : pmset est toujours fiable (psutil peut échouer sur Apple Silicon)
                import subprocess as _sp, re as _re
                try:
                    out = _sp.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=4).stdout
                    pct_match = _re.search(r'(\d+)%', out)
                    charged = "charging" in out or "charged" in out
                    ac = "AC Power" in out
                    status = "en charge" if (charged or ac) else "sur batterie"
                    if pct_match:
                        pct = int(pct_match.group(1))
                        # Estimer le temps restant
                        time_match = _re.search(r'(\d+:\d+) remaining', out)
                        time_str = f", environ {time_match.group(1)} restant" if time_match and time_match.group(1) != "0:00" else ""
                        return f"Batterie à {pct}%, {status}{time_str}."
                except Exception:
                    pass
                # Fallback psutil
                try:
                    import psutil
                    batt = psutil.sensors_battery()
                    if batt:
                        status = "en charge" if batt.power_plugged else "sur batterie"
                        return f"Batterie à {int(batt.percent)}%, {status}."
                except Exception:
                    pass
                return "Impossible de lire l'état de la batterie."
            elif action == "cpu_ram":
                try:
                    import psutil
                    cpu = psutil.cpu_percent(interval=0.5)
                    ram = psutil.virtual_memory()
                    ram_used = ram.used / (1024**3)
                    ram_total = ram.total / (1024**3)
                    disk = psutil.disk_usage("/")
                    disk_free = disk.free / (1024**3)
                    disk_total = disk.total / (1024**3)
                    batt = psutil.sensors_battery()
                    batt_str = f"Batterie {int(batt.percent)}% ({'en charge' if batt.power_plugged else 'sur batterie'}). " if batt else ""
                    return (f"CPU : {cpu:.0f}%, RAM : {ram_used:.1f}/{ram_total:.0f} Go ({ram.percent:.0f}%). "
                            f"Disque : {disk_free:.0f} Go libres sur {disk_total:.0f} Go. {batt_str}")
                except Exception:
                    return "Impossible de lire les infos système."
            elif action == "presse_papier_lire":
                return clipboard_get()
            elif action == "presse_papier_ecrire":
                return clipboard_set(args.get("texte", ""))
            elif action == "luminosite":
                niveau = int(args.get("niveau", 50))
                return system_set_brightness(niveau)
            elif action == "screenshot":
                return file_take_screenshot()
            return "Action système inconnue."

        elif name == "meteo":
            import requests
            try:
                ville = args.get("ville", "Charleroi").strip()
                nb_jours = min(int(args.get("jours", 2)), 7)
                # Cache 30 min pour éviter des appels répétés (clé inclut nb_jours)
                _cache_key = f"{ville.lower()}_{nb_jours}"
                _cached = _WEATHER_CACHE.get(_cache_key)
                if _cached and (time.time() - _cached[0]) < _WEATHER_TTL:
                    logger.debug(f"Météo cache hit : {ville}")
                    return _cached[1]
                # Coordonnées connues pour éviter un appel de géocodage
                COORDS = {
                    "charleroi": (50.41, 4.44),
                    "bruxelles": (50.85, 4.35),
                    "brussels":  (50.85, 4.35),
                    "liège":     (50.63, 5.57),
                    "liege":     (50.63, 5.57),
                    "namur":     (50.46, 4.87),
                    "mons":      (50.45, 3.95),
                    "paris":     (48.85, 2.35),
                    "lille":     (50.63, 3.07),
                    "london":    (51.51, -0.13),
                    "londres":   (51.51, -0.13),
                }
                key = ville.lower()
                if key in COORDS:
                    lat, lon = COORDS[key]
                else:
                    # Géocodage via Open-Meteo geocoding API
                    geo = requests.get(
                        f"https://geocoding-api.open-meteo.com/v1/search?name={ville}&count=1&language=fr",
                        timeout=5
                    ).json()
                    results = geo.get("results", [])
                    if results:
                        lat, lon = results[0]["latitude"], results[0]["longitude"]
                        ville = results[0].get("name", ville)
                    else:
                        lat, lon = 50.41, 4.44
                        ville = "Charleroi"

                resp = requests.get(
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={lat}&longitude={lon}"
                    f"&current=temperature_2m,weathercode,windspeed_10m,relative_humidity_2m"
                    f"&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max,windspeed_10m_max"
                    f"&forecast_days={max(nb_jours, 2)}&timezone=auto", timeout=5
                )
                rjson = resp.json()
                data = rjson["current"]
                codes = {
                    0: "ciel dégagé", 1: "principalement dégagé", 2: "partiellement nuageux",
                    3: "couvert", 45: "brouillard", 48: "brouillard givrant",
                    51: "bruine légère", 53: "bruine modérée", 61: "pluie légère",
                    63: "pluie modérée", 65: "forte pluie", 80: "averses légères",
                    81: "averses modérées", 82: "fortes averses", 95: "orage",
                    96: "orage avec grêle", 99: "violent orage avec grêle",
                }
                _JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                wcode = data.get("weathercode", 0)
                desc = codes.get(wcode, "conditions variables")
                temp = data['temperature_2m']
                result = (f"À {ville} : {temp}°C, {desc}. "
                          f"Vent {data['windspeed_10m']} km/h, humidité {data['relative_humidity_2m']}%.")
                # Suggestion proactive selon les conditions actuelles
                _RAIN_CODES = {51, 53, 61, 63, 65, 80, 81, 82, 95, 96, 99}
                _STORM_CODES = {95, 96, 99}
                if wcode in _STORM_CODES:
                    result += " Évitez de sortir si possible — orage prévu."
                elif wcode in _RAIN_CODES:
                    result += " Prenez un parapluie."
                elif temp >= 30:
                    result += " Forte chaleur — pensez à vous hydrater."
                elif temp <= 2:
                    result += " Il fait très froid — couvrez-vous bien."
                # Prévisions journalières
                try:
                    daily = rjson.get("daily", {})
                    daily_len = len(daily.get("temperature_2m_max", []))
                    from datetime import datetime as _dt2
                    today_wd = _dt2.now().weekday()
                    if nb_jours <= 2 and daily_len >= 2:
                        # Mode court — demain seulement
                        t_max = daily["temperature_2m_max"][1]
                        t_min = daily["temperature_2m_min"][1]
                        desc_tmr = codes.get(daily["weathercode"][1], "conditions variables")
                        rain_pct = daily.get("precipitation_probability_max", [0, 0])[1]
                        result += f" Demain : {t_min}–{t_max}°C, {desc_tmr}"
                        if rain_pct >= 30:
                            result += f", {rain_pct}% de risque de pluie"
                        result += "."
                    elif nb_jours >= 3 and daily_len >= nb_jours:
                        # Mode semaine — prévisions par jour
                        result += " Prévisions :"
                        for i in range(1, min(nb_jours, daily_len)):
                            wd = (today_wd + i) % 7
                            jour = _JOURS_FR[wd]
                            t_max = daily["temperature_2m_max"][i]
                            t_min = daily["temperature_2m_min"][i]
                            desc_d = codes.get(daily["weathercode"][i], "variable")
                            rain_p = daily.get("precipitation_probability_max", [0]*8)[i] if i < len(daily.get("precipitation_probability_max", [])) else 0
                            result += f" {jour.capitalize()} {t_min}–{t_max}°C {desc_d}"
                            if rain_p >= 40:
                                result += f" ({rain_p}% pluie)"
                            result += "."
                except Exception:
                    pass
                _WEATHER_CACHE[_cache_key] = (time.time(), result)
                return result
            except Exception as e:
                logger.error(f"Météo erreur : {e}")
                return "Météo indisponible."

        elif name == "minuteur":
            import threading, time as _time
            secondes = int(args.get("duree_secondes", 60))
            message = args.get("message", "Minuteur terminé.")
            def _run():
                _time.sleep(secondes)
                if tts:
                    tts.speak(message)
                notification_send("JARVIS", message)
            threading.Thread(target=_run, daemon=True).start()
            mins = secondes // 60
            secs = secondes % 60
            if mins and secs:
                dur = f"{mins} min {secs} sec"
            elif mins:
                dur = f"{mins} minute{'s' if mins > 1 else ''}"
            else:
                dur = f"{secondes} seconde{'s' if secondes > 1 else ''}"
            return f"Minuteur lancé pour {dur}."

        elif name == "alarme":
            import threading, time as _time
            from datetime import datetime as _dt, timedelta as _td
            heure = int(args.get("heure", 7))
            minute = int(args.get("minute", 0))
            message = args.get("message", f"Alarme de {heure:02d}h{minute:02d}.")

            now = _dt.now()
            target = now.replace(hour=heure, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += _td(days=1)  # Si l'heure est déjà passée → demain

            secondes_attente = (target - now).total_seconds()

            def _alarm_run():
                _time.sleep(secondes_attente)
                if tts:
                    tts.speak(message)
                notification_send("JARVIS Alarme", message)

            threading.Thread(target=_alarm_run, daemon=True).start()

            delta_mins = int(secondes_attente // 60)
            if delta_mins >= 60:
                delta_str = f"{delta_mins // 60}h{delta_mins % 60:02d}"
            else:
                delta_str = f"{delta_mins} minute{'s' if delta_mins > 1 else ''}"
            return f"Alarme programmée pour {heure:02d}h{minute:02d} (dans {delta_str})."

        elif name == "memoriser":
            info = args.get("information", "")
            if persistent_memory and info:
                import re as _re_mem
                # Rejeter les faits transitoires : états techniques, problèmes en cours, tests
                _TRANSIENT = _re_mem.compile(
                    r"(?:problème|bug|erreur|grésil|souci|en cours|transitoire"
                    r"|audio|micro|son|voix|feedback|bruit|test|essai"
                    r"|ne marche pas|ne fonctionne pas|ça ne|ça n'|régler"
                    r"|corriger|résoudre|à corriger|à régler)",
                    _re_mem.IGNORECASE,
                )
                if not _TRANSIENT.search(info):
                    persistent_memory.save_fact(info)
            return ""  # silencieux — JARVIS ne dit jamais "Mémorisé : ..."

        elif name == "actualites":
            import requests, xml.etree.ElementTree as ET
            sujet = args.get("sujet", "").lower() if args else ""

            # Sources télécom / tech — priorité si la requête concerne Proximus, VOO, Orange, NexaTel…
            TELECOM_KEYWORDS = ["proximus", "voo", "orange", "telenet", "scarlet", "télécom",
                                 "internet", "fibre", "5g", "gsm", "mobile", "ibpt", "opérateur"]
            is_telecom = any(kw in sujet for kw in TELECOM_KEYWORDS)

            TELECOM_SOURCES = [
                ("IBPT Belgique", "https://www.ibpt.be/rss/fr/news.xml"),
                ("RTBF Tech", "https://www.rtbf.be/rss/section/tech.xml"),
                ("Numerama Belgique", "https://www.numerama.com/feed/"),
                ("01net Telecom", "https://www.01net.com/rss/actualites/telecom/"),
                ("Le Soir Eco", "https://www.lesoir.be/arc/outboundfeeds/rss/economy/?outputType=xml"),
            ]

            GENERAL_SOURCES = [
                ("RTBF Info", "https://www.rtbf.be/rss/info.xml"),
                ("RTL Info Belgique", "https://www.rtl.be/rss/rubriques/info.xml"),
                ("La DH Belgique", "https://www.dhnet.be/arc/outboundfeeds/rss/?outputType=xml"),
                ("La Libre Belgique", "https://www.lalibre.be/arc/outboundfeeds/rss/?outputType=xml"),
                ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
                ("20 Minutes", "https://www.20minutes.fr/feeds/rss/une.xml"),
            ]

            sources_to_try = (TELECOM_SOURCES if is_telecom else []) + GENERAL_SOURCES

            for source_name, url in sources_to_try:
                try:
                    resp = requests.get(url, timeout=5, headers={"User-Agent": "JARVIS/3.0"})
                    if resp.status_code != 200:
                        continue
                    root = ET.fromstring(resp.content)
                    items = root.findall(".//item")[:3]
                    headlines = [i.find("title").text.strip() for i in items if i.find("title") is not None]
                    if headlines:
                        return f"Actualités ({source_name}) : " + ". ".join(f"{i+1}: {h}" for i, h in enumerate(headlines)) + "."
                except Exception:
                    continue
            return "Actualités indisponibles."

        elif name == "recherche_info":
            import requests, urllib.parse
            requete = args.get("requete", "").strip()
            if not requete:
                return "Que voulez-vous chercher ?"

            requete_lower = requete.lower()

            # 1. Crypto prices — CoinGecko (gratuit, sans clé)
            CRYPTO_IDS = {
                "bitcoin": "bitcoin", "btc": "bitcoin",
                "ethereum": "ethereum", "eth": "ethereum",
                "bnb": "binancecoin", "binance": "binancecoin",
                "solana": "solana", "sol": "solana",
                "xrp": "ripple", "ripple": "ripple",
                "cardano": "cardano", "ada": "cardano",
                "dogecoin": "dogecoin", "doge": "dogecoin",
            }
            crypto_id = None
            for kw, cid in CRYPTO_IDS.items():
                if kw in requete_lower:
                    crypto_id = cid
                    break
            if crypto_id:
                try:
                    resp = requests.get(
                        f"https://api.coingecko.com/api/v3/simple/price"
                        f"?ids={crypto_id}&vs_currencies=eur,usd&include_24hr_change=true",
                        timeout=6, headers={"User-Agent": "JARVIS/3.0"}
                    )
                    d = resp.json().get(crypto_id, {})
                    eur = d.get("eur", 0)
                    usd = d.get("usd", 0)
                    chg = d.get("eur_24h_change", 0)
                    chg_str = f", {chg:+.1f}% sur 24h" if chg else ""
                    return f"{crypto_id.capitalize()} : {eur:,.0f} € / {usd:,.0f} $ {chg_str}."
                except Exception:
                    pass

            # 2. Actions boursières — yfinance (gère les cookies Yahoo automatiquement)
            STOCK_KEYWORDS = {
                "apple": "AAPL", "tesla": "TSLA", "microsoft": "MSFT",
                "google": "GOOGL", "alphabet": "GOOGL", "amazon": "AMZN",
                "nvidia": "NVDA", "meta": "META", "netflix": "NFLX",
                "bnp": "BNP.PA", "totalenergies": "TTE.PA", "total": "TTE.PA",
                "air france": "AIRF.PA", "lvmh": "MC.PA", "airbus": "AIR.PA",
                "microsoft": "MSFT", "samsung": "005930.KS",
            }
            stock_ticker = None
            for kw, ticker in STOCK_KEYWORDS.items():
                if kw in requete_lower:
                    stock_ticker = ticker
                    break
            # Détecter un ticker direct (ex: "cours de AAPL", "action NVDA")
            if not stock_ticker:
                import re as _re
                m = _re.search(r'\b([A-Z]{2,5}(?:\.[A-Z]{2})?)\b', requete)
                if m and any(w in requete_lower for w in ["action", "bourse", "cours", "ticker"]):
                    stock_ticker = m.group(1)
            if stock_ticker:
                try:
                    import yfinance as yf
                    t = yf.Ticker(stock_ticker)
                    hist = t.history(period="2d")
                    if not hist.empty:
                        price = hist["Close"].iloc[-1]
                        prev = hist["Close"].iloc[-2] if len(hist) >= 2 else price
                        chg_pct = ((price - prev) / prev * 100) if prev else 0
                        nom = requete.replace("cours de ", "").replace("action ", "").replace("prix de ", "").strip().title()
                        return (
                            f"{nom} ({stock_ticker}) : {price:.2f} €"
                            if stock_ticker.endswith(".PA") else
                            f"{nom} ({stock_ticker}) : {price:.2f} $"
                        ) + f", {chg_pct:+.2f}% aujourd'hui."
                except Exception:
                    pass

            # 3. Wikipedia (résumé court) — meilleure source pour faits généraux
            # Essayer plusieurs formulations de la requête
            _wiki_queries = [requete]
            # Simplification pour questions "population/capitale/superficie de X"
            import re as _re
            _m = _re.search(r'(?:population|capitale|superficie|président|premier ministre)\s+(?:de\s+|d\'|du\s+)?(.+)', requete_lower)
            if _m:
                _wiki_queries.append(_m.group(1).strip().title())
            for _wq in _wiki_queries:
                try:
                    wiki_url = (
                        "https://fr.wikipedia.org/api/rest_v1/page/summary/"
                        + urllib.parse.quote(_wq.replace(" ", "_"))
                    )
                    resp = requests.get(wiki_url, timeout=5, headers={"User-Agent": "JARVIS/3.0"})
                    if resp.status_code == 200:
                        data = resp.json()
                        extract = data.get("extract", "").strip()
                        if extract and len(extract) > 30:
                            return extract[:350]
                except Exception:
                    pass

            # 4. DuckDuckGo Instant Answer (réponse directe si disponible)
            try:
                ddg_url = (
                    "https://api.duckduckgo.com/"
                    f"?q={urllib.parse.quote(requete)}&format=json&no_html=1&skip_disambig=1"
                )
                resp = requests.get(ddg_url, timeout=5, headers={"User-Agent": "JARVIS/3.0"})
                data = resp.json()
                abstract = data.get("AbstractText", "").strip()
                if abstract and len(abstract) > 30:
                    return abstract[:300]
                answer = data.get("Answer", "").strip()
                if answer and len(answer) > 5:
                    return answer[:200]
            except Exception:
                pass

            # 5. DuckDuckGo HTML scraping — résultats réels, marche pour n'importe quelle question
            try:
                import re as _re2, html as _html
                ddg_html_url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(requete)
                resp = requests.get(
                    ddg_html_url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                    timeout=8
                )
                snippets = _re2.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, _re2.DOTALL)
                cleaned = []
                for s in snippets[:4]:
                    clean = _re2.sub(r'<[^>]+>', '', s).strip()
                    clean = _html.unescape(clean)
                    clean = _re2.sub(r'\s+', ' ', clean).strip()
                    if clean and len(clean) > 25:
                        cleaned.append(clean)
                if cleaned:
                    return " ".join(cleaned[:2])[:400]
            except Exception:
                pass

            return f"Aucune donnée trouvée pour '{requete}'. Voulez-vous que j'ouvre une recherche web ?"

        elif name == "obsidian":
            action = args.get("action", "chercher")
            requete = args.get("requete", "").strip()

            # Accéder au cache vault déjà chargé (évite de recréer MemorySystem)
            try:
                from pathlib import Path as _Path
                import json as _json
                _cache = _Path.home() / ".jarvis_vault_cache.json"
                if not _cache.exists():
                    return "Vault Obsidian non disponible. Lancez JARVIS depuis un terminal pour initialiser le cache."

                with open(_cache, encoding="utf-8") as _f:
                    _data = _json.load(_f)
                vault_path = _data.get("vault", "")
                notes = _data.get("notes", [])

                # Wrapper léger (pas de MemorySystem complet)
                _OBS_STOP = frozenset({
                    "le","la","les","un","une","des","du","de","en","et","ou",
                    "est","sont","a","au","aux","pas","ne","se","sa","son","ses",
                    "ma","mon","mes","ta","ton","tes","je","tu","il","elle","nous",
                    "vous","ils","elles","me","te","lui","y","ce","qui","que","qu",
                    "sur","dans","pour","par","avec","sans","si","mais","car",
                    "plus","bien","tout","aussi","cette","cet","ces","quel","quelle",
                    "quoi","comment","quand","on","ca","c","j","d","l","n","s",
                })
                class _Mem:
                    def __init__(self, idx, vp):
                        self._index = idx
                        self.vault_path = _Path(vp) if vp else None
                    def search_relevant_notes(self, q, top_k=3):
                        import re as _re2, unicodedata as _ud
                        def _norm(s):
                            s = s.lower()
                            s = _ud.normalize("NFD", s)
                            s = "".join(c for c in s if _ud.category(c) != "Mn")
                            s = _re2.sub(r"[^\w\s]", " ", s)
                            return s
                        all_qw = set(_norm(q).split())
                        qw = all_qw - _OBS_STOP or all_qw
                        scored = []
                        for n in self._index:
                            main = _norm(n["title"]+" "+n["preview"]+" "+" ".join(str(t) for t in n.get("tags", [])))
                            mw = set(main.split())
                            score = len(qw & mw)
                            score += len(qw & set(_norm(n["title"]).split())) * 3
                            fc = _norm(n.get("full_content","")[:3000])
                            fc_words = set(fc.split()) - _OBS_STOP
                            fc_hits = len(qw & fc_words)
                            score += fc_hits * (1.0 if score == 0 else 0.3)
                            if score > 0:
                                scored.append({**n, "score": score})
                        return sorted(scored, key=lambda x: x["score"], reverse=True)[:top_k]
                    def save_quick_note(self, content):
                        from memory import MemorySystem as _MS
                        import os as _os
                        m = _MS(_os.getenv("OBSIDIAN_VAULT_PATH", vault_path))
                        return m.save_quick_note(content)

                mem = _Mem(notes, vault_path)

                if action == "chercher":
                    if not requete:
                        return "Que voulez-vous chercher dans vos notes ?"
                    results = mem.search_relevant_notes(requete, top_k=3)
                    if not results:
                        return f"Aucune note trouvée pour '{requete}'."
                    parts = []
                    for note in results:
                        preview = note["preview"][:200].strip()
                        parts.append(f"{note['title']} : {preview}")
                    return " | ".join(parts)

                elif action == "lire_note":
                    if not requete:
                        return "Quelle note voulez-vous lire ?"
                    results = mem.search_relevant_notes(requete, top_k=1)
                    if not results:
                        return f"Aucune note trouvée pour '{requete}'."
                    note = results[0]
                    content = note.get("full_content", note.get("preview", ""))
                    if not content:
                        return f"Note '{note['title']}' vide ou inaccessible."
                    # Retourner le contenu complet (le LLM le reformulera)
                    return f"Note '{note['title']}' :\n{content[:800]}"

                elif action == "note_rapide":
                    if not requete:
                        return "Que voulez-vous noter ?"
                    path = mem.save_quick_note(requete)
                    return f"Note '{requete[:40]}' sauvegardée dans Obsidian." if path else "Impossible de créer la note."

                elif action == "agenda":
                    from datetime import datetime as _dt
                    today = _dt.now()
                    today_str = today.strftime("%Y-%m-%d")
                    slash_str = today.strftime("%d/%m")
                    results = []
                    for note in mem._index:
                        c = note.get("full_content", "").lower()
                        if "jarvis-log" in note.get("tags", []):
                            continue
                        if today_str in c or slash_str in c:
                            results.append(note)
                    if not results:
                        return f"Aucun événement trouvé pour aujourd'hui ({today.strftime('%d/%m/%Y')})."
                    tasks = []
                    for note in results[:3]:
                        for line in note["full_content"].splitlines():
                            if ("- [ ]" in line or "- [x]" in line) and len(line.strip()) > 5:
                                tasks.append(line.replace("- [ ]", "☐").replace("- [x]", "☑").strip())
                    if not tasks:
                        return f"Notes d'agenda trouvées : {', '.join(n['title'] for n in results[:3])}."
                    return "Agenda du jour : " + ". ".join(tasks[:5]) + "."

            except Exception as e:
                logger.error(f"Obsidian erreur : {e}")
                return "Impossible d'accéder au vault Obsidian."

        elif name == "devises":
            import requests
            try:
                montant = float(args.get("montant", 1))
                devise_de = args.get("de", "EUR").upper().strip()
                vers_raw = args.get("vers", "USD,MAD,GBP").upper().strip()
                vers_list = [v.strip() for v in vers_raw.split(",") if v.strip() and v.strip() != devise_de]
                if not vers_list:
                    vers_list = ["USD", "MAD", "GBP"]

                # Cache — ExchangeRate-API renvoyant les taux de base (indépendant du montant)
                _devise_cache_key = f"{devise_de}_{','.join(sorted(vers_list))}"
                _cached_devise = _DEVISE_CACHE.get(_devise_cache_key)
                if _cached_devise and (time.time() - _cached_devise[0]) < _DEVISE_TTL:
                    # Recalculer pour le montant demandé si différent du cache
                    _cached_rates, _cached_base_montant = _cached_devise[1], _cached_devise[2]
                    if _cached_base_montant == 1.0:
                        # Les taux sont stockés pour 1 unité, recalculer
                        all_rates = _cached_rates
                        rates = {v: all_rates[v] * montant for v in vers_list if v in all_rates}
                        montant_str = f"{montant:g}"
                        _DEVISE_NAMES = {
                            "USD": "dollars américains", "EUR": "euros",
                            "GBP": "livres sterling", "MAD": "dirhams marocains",
                            "CHF": "francs suisses", "JPY": "yens japonais",
                            "DZD": "dinars algériens", "TND": "dinars tunisiens",
                            "CAD": "dollars canadiens", "AUD": "dollars australiens",
                            "CNY": "yuans chinois", "KRW": "wons coréens",
                        }
                        parts = []
                        for v, rate in sorted(rates.items()):
                            name_d = _DEVISE_NAMES.get(v, v)
                            if rate >= 100:
                                parts.append(f"{rate:,.0f} {name_d}")
                            elif rate >= 1:
                                parts.append(f"{rate:.2f} {name_d}")
                            else:
                                parts.append(f"{rate:.4f} {name_d}")
                        from_name = _DEVISE_NAMES.get(devise_de, devise_de)
                        return f"{montant_str} {from_name} = " + ", ".join(parts) + "."

                # ExchangeRate-API (gratuit, sans clé, supporte MAD et 150+ devises)
                resp = requests.get(
                    f"https://open.er-api.com/v6/latest/{devise_de}",
                    timeout=5
                )
                data = resp.json()
                if data.get("result") != "success":
                    return f"Taux non disponibles pour {devise_de}."

                all_rates = data.get("rates", {})
                rates = {v: all_rates[v] * montant for v in vers_list if v in all_rates}

                if not rates:
                    return f"Devises non reconnues : {', '.join(vers_list)}."

                # Mettre en cache les taux bruts (pour montant=1) — TTL 20 min
                _DEVISE_CACHE[_devise_cache_key] = (time.time(), all_rates, 1.0)

                montant_str = f"{montant:g}"
                # Noms lisibles des devises pour la synthèse vocale
                _DEVISE_NAMES = {
                    "USD": "dollars américains", "EUR": "euros",
                    "GBP": "livres sterling", "MAD": "dirhams marocains",
                    "CHF": "francs suisses", "JPY": "yens japonais",
                    "DZD": "dinars algériens", "TND": "dinars tunisiens",
                    "CAD": "dollars canadiens", "AUD": "dollars australiens",
                    "CNY": "yuans chinois", "KRW": "wons coréens",
                }
                # Formater les taux selon la magnitude
                parts = []
                for v, rate in sorted(rates.items()):
                    name_d = _DEVISE_NAMES.get(v, v)
                    if rate >= 100:
                        parts.append(f"{rate:,.0f} {name_d}")
                    elif rate >= 1:
                        parts.append(f"{rate:.2f} {name_d}")
                    else:
                        parts.append(f"{rate:.4f} {name_d}")
                from_name = _DEVISE_NAMES.get(devise_de, devise_de)
                return f"{montant_str} {from_name} = " + ", ".join(parts) + "."
            except Exception as e:
                logger.error(f"devises erreur : {e}")
                return "Taux de change indisponibles."

        elif name == "notification":
            titre = args.get("titre", "JARVIS")
            message = args.get("message", "")
            if not message:
                return "Message vide."
            notification_send(titre, message)
            return f"Notification envoyée : {message[:60]}"

        else:
            return f"Outil inconnu : {name}"

    except Exception as e:
        logger.error(f"Erreur outil {name} : {e}")
        return f"Erreur lors de l'exécution de {name}."
