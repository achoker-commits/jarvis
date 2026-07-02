"""Tests hystérésis bloc NexaTel — pytest tests/test_nexatel_hysteresis.py

Scénario cible : NexaTel mentionné au tour 1 → bloc présent aux tours 2-9 inclus
même sans mot-clé NexaTel dans les requêtes suivantes. Désactivé au tour 10.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import LLMEngine, _is_nexatel_relevant


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fresh() -> LLMEngine:
    llm = LLMEngine()
    llm._nexatel_turns_remaining = 0
    return llm


# ── Tests module-level _is_nexatel_relevant ───────────────────────────────────

def test_nexatel_keyword_in_query():
    assert _is_nexatel_relevant("j'ai un client Orange pour NexaTel")

def test_nexatel_keyword_proximus():
    assert _is_nexatel_relevant("offre Proximus moins chère ?")

def test_nexatel_keyword_prix_abonnement():
    assert _is_nexatel_relevant("quel est le prix de l'abonnement ?")

def test_nexatel_no_keyword_banal():
    assert not _is_nexatel_relevant("c'est quoi le machine learning")

def test_nexatel_keyword_in_history():
    history = [
        {"role": "user", "content": "compare Orange et NexaTel"},
        {"role": "assistant", "content": "NexaTel est 30% moins cher."},
    ]
    assert _is_nexatel_relevant("merci", history)

def test_nexatel_old_history_not_checked():
    """Histoire ancienne (> 3 derniers tours) ne doit pas déclencher."""
    history = [
        {"role": "user", "content": "client Proximus au tour 1"},
        {"role": "assistant", "content": "réponse NexaTel tour 1"},
        {"role": "user", "content": "sujet banal tour 2"},
        {"role": "assistant", "content": "réponse banale"},
        {"role": "user", "content": "sujet banal tour 3"},
        {"role": "assistant", "content": "réponse banale"},
        {"role": "user", "content": "sujet banal tour 4"},
        {"role": "assistant", "content": "réponse banale"},
    ]
    # Les 3 derniers tours (indices -6:-1) ne mentionnent pas NexaTel
    assert not _is_nexatel_relevant("météo", history)


# ── Tests hystérésis sur LLMEngine ───────────────────────────────────────────

def test_counter_initialized_at_zero():
    """Compteur à 0 à l'initialisation."""
    assert _fresh()._nexatel_turns_remaining == 0


def test_counter_set_after_nexatel_query():
    """Premier appel NexaTel → compteur = 8 après le décrément du tour courant."""
    llm = _fresh()
    llm.build_system_prompt([], query="client Orange pour NexaTel")
    assert llm._nexatel_turns_remaining == 8  # 9 injectés, 1 décrémenté


def test_hysteresis_active_turns_2_to_5():
    """NexaTel mentionné au tour 1 → bloc actif aux tours 2 à 5 sans mot-clé."""
    llm = _fresh()

    # Tour 1 : déclenchement
    llm.build_system_prompt([], query="j'ai un client Orange pour NexaTel")
    assert llm._nexatel_turns_remaining == 8

    # Tours 2-5 : sans mot-clé NexaTel
    for turn in range(2, 6):
        remaining_avant = llm._nexatel_turns_remaining
        assert remaining_avant > 0, f"Tour {turn} : NexaTel devrait encore être actif"
        llm.build_system_prompt([], query="c'est quoi le machine learning")

    # Après le tour 5, il doit rester 4 tours (8 - 4 = 4)
    assert llm._nexatel_turns_remaining == 4


def test_hysteresis_deactivates_after_8_additional_turns():
    """Après 8 tours sans mot-clé NexaTel, le compteur tombe à 0."""
    llm = _fresh()

    # Tour 0 : déclenchement
    llm.build_system_prompt([], query="question sur Proximus")

    # 8 tours sans mot-clé
    for i in range(8):
        llm.build_system_prompt([], query="quelle heure est-il")

    assert llm._nexatel_turns_remaining == 0, (
        f"Compteur doit être épuisé après 8 tours, obtenu {llm._nexatel_turns_remaining}"
    )


def test_hysteresis_resets_on_new_keyword():
    """Nouveau mot-clé NexaTel en cours de conversation réinitialise le compteur."""
    llm = _fresh()

    # Déclenchement initial
    llm.build_system_prompt([], query="client Orange NexaTel")

    # 4 tours sans mot-clé (compteur descend à 4)
    for _ in range(4):
        llm.build_system_prompt([], query="météo à Charleroi")

    assert llm._nexatel_turns_remaining == 4  # vérifie l'état intermédiaire

    # Nouveau mot-clé → reset + décrement → 8
    llm.build_system_prompt([], query="quel est le prix de l'abonnement Proximus")
    assert llm._nexatel_turns_remaining == 8, (
        f"Reset attendu à 8, obtenu {llm._nexatel_turns_remaining}"
    )


def test_counter_never_goes_negative():
    """Le compteur ne passe pas sous 0 même après beaucoup d'appels sans mot-clé."""
    llm = _fresh()
    for _ in range(20):
        llm.build_system_prompt([], query="bonjour")
    assert llm._nexatel_turns_remaining == 0
