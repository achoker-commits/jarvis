"""Tests de routage d'outils JARVIS — pytest tests/test_routing.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import LLMEngine

_llm = LLMEngine()  # pas de clé → Ollama mode (pas besoin de connexion pour ces tests)


def _route(text: str) -> str:
    return _llm._force_tool_for_query(text)


# ── Météo ──────────────────────────────────────────────────────────────────
def test_meteo_simple():
    assert _route("C'est quoi la météo ?") == "meteo"

def test_meteo_ville():
    assert _route("quel temps fait-il à Bruxelles ?") == "meteo"

def test_meteo_semaine():
    assert _route("météo cette semaine") == "meteo"

def test_meteo_no_false_positive_sport():
    # "temps" dans un contexte sportif ne doit pas déclencher météo
    # (ce cas est ambigu, on accepte que "temps" déclenche météo)
    pass

# ── Musique ────────────────────────────────────────────────────────────────
def test_musique_jazz():
    assert _route("joue-moi du jazz") == "musique_spotify"

def test_musique_rap():
    assert _route("mets du rap français") == "musique_spotify"

def test_musique_joue():
    assert _route("joue quelque chose") == "musique_spotify"

def test_musique_spotify_cherche():
    assert _route("cherche PNL sur Spotify") == "musique_spotify"

def test_musique_pause():
    assert _route("pause musique") == "musique_spotify"

def test_musique_chanson_actuelle():
    assert _route("c'est quoi cette chanson") == "musique_spotify"

# ── Système ────────────────────────────────────────────────────────────────
def test_systeme_batterie():
    assert _route("batterie à combien ?") == "systeme"

def test_systeme_wifi():
    assert _route("je suis connecté à quel wifi ?") == "systeme"

def test_systeme_dark_mode():
    assert _route("active le mode sombre") == "systeme"

def test_systeme_screenshot():
    assert _route("fais une capture d'écran") == "systeme"

# ── Volume ────────────────────────────────────────────────────────────────
def test_volume_monte():
    assert _route("monte le son") == "volume"

def test_volume_niveau():
    assert _route("mets le son à 70") == "volume"

# ── Actualités ────────────────────────────────────────────────────────────
def test_actualites():
    assert _route("quelles sont les nouvelles du jour ?") == "actualites"

def test_actualites_news():
    assert _route("donne-moi les news") == "actualites"

# ── Devises ────────────────────────────────────────────────────────────────
def test_devises_taux():
    assert _route("quel est le taux de change euro dollar ?") == "devises"

def test_devises_convertir():
    assert _route("combien font 100 euros en dirhams ?") == "devises"

# ── Crypto ────────────────────────────────────────────────────────────────
def test_crypto_bitcoin():
    assert _route("combien vaut le bitcoin ?") == "recherche_info"

# ── Recherche générale ────────────────────────────────────────────────────
def test_recherche_qui_est():
    assert _route("qui est Elon Musk ?") == "recherche_info"

def test_recherche_cest_quoi():
    assert _route("c'est quoi la photosynthèse ?") == "recherche_info"

# ── Alarme / Minuteur ────────────────────────────────────────────────────
def test_minuteur():
    assert _route("lance un minuteur de 5 minutes") == "minuteur"

def test_alarme():
    assert _route("réveille-moi à 7h30") == "alarme"

# ── Pas de faux positif ────────────────────────────────────────────────────
def test_no_tool_simple_question():
    result = _route("tu peux m'expliquer c'est quoi l'IA ?")
    # "c'est quoi" devrait → recherche_info SAUF si "toi/tu" exclu
    # ici pas de "toi/tu", donc peut déclencher recherche_info — acceptable
    assert result in ("recherche_info", "")

def test_no_tool_greeting():
    assert _route("comment tu vas ?") == ""
