"""Tests des cas limites streaming Groq → TTS — pytest tests/test_streaming.py"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import LLMEngine


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mk_text(text: str):
    """Faux chunk Groq portant du texte."""
    chunk = MagicMock()
    chunk.choices[0].delta.content = text
    chunk.choices[0].delta.tool_calls = None
    return chunk


def _mk_tool(name: str = "", args: str = "", tc_id: str = "tc_0"):
    """Faux chunk Groq portant un tool call."""
    chunk = MagicMock()
    chunk.choices[0].delta.content = None
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args
    chunk.choices[0].delta.tool_calls = [tc]
    return chunk


def _new_llm():
    llm = LLMEngine()   # pas de clé API, tests purement locaux
    llm._last_response = ""
    return llm


# ── Cas 1 : buffer résiduel sans ponctuation finale ───────────────────────────

def test_cas1_last_response_no_terminal_punctuation():
    """Texte sans '.' final : _last_response doit contenir TOUT le texte."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text("Bonjour"), _mk_text(" je suis"), _mk_text(" JARVIS")]),
        tc,
    )
    result = "".join(gen)
    assert result == "Bonjour je suis JARVIS"
    assert llm._last_response == "Bonjour je suis JARVIS"
    assert not tc["is_tool"]


def test_cas1_last_response_with_punctuation():
    """Texte avec ponctuation : _last_response complet et identique."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text("Il fait beau"), _mk_text(". Bonne journée"), _mk_text(" !")]),
        tc,
    )
    "".join(gen)
    assert llm._last_response == "Il fait beau. Bonne journée !"


def test_cas1_empty_stream():
    """Stream vide : _last_response reste vide, rien ne plante."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(iter([]), tc)
    assert list(gen) == []
    assert llm._last_response == ""


# ── Cas 2 : détection tool call pure ─────────────────────────────────────────

def test_cas2_pure_tool_call_no_yield():
    """Stream pur tool call : rien n'est yielded, tc_state rempli."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([
            _mk_tool("meteo", '{"ville": "Charleroi"}', "tc_abc"),
            _mk_tool("", '"}', ""),  # chunk de continuation : pas d'ID (falsy → pas écrasé)
        ]),
        tc,
    )
    yielded = list(gen)
    assert yielded == []
    assert tc["is_tool"]
    assert tc["name"] == "meteo"
    assert tc["id"] == "tc_abc"
    assert llm._last_response == ""


def test_cas2_tool_call_args_concatenated():
    """Les arguments d'un tool call arrivent en plusieurs chunks → concaténés."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([
            _mk_tool("meteo", '{"ville":', "tc_1"),
            _mk_tool("", ' "Paris"}'),
        ]),
        tc,
    )
    list(gen)
    import json
    args = json.loads(tc["args"])
    assert args == {"ville": "Paris"}


def test_cas2_hybrid_pre_tool_text_passed_to_execute():
    """
    Stream hybride texte+tool : _make_stream_gen yield le texte pré-tool
    ET remplit tc_state avec le tool call.
    Vérifie que les deux sont disponibles pour _execute_and_respond_stream.
    """
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([
            _mk_text("Je cherche la météo..."),   # texte pré-tool, yielded
            _mk_tool("meteo", '{"ville":"Charleroi"}', "tc_h"),  # tool call
        ]),
        tc,
    )
    yielded = list(gen)

    # Le texte pré-tool a bien été yielded (et accumulé dans _last_response)
    assert yielded == ["Je cherche la météo..."]
    assert llm._last_response == "Je cherche la météo..."

    # Le tool call a bien été détecté
    assert tc["is_tool"]
    assert tc["name"] == "meteo"
    assert tc["id"] == "tc_h"

    # _execute_and_respond_stream reçoit pre_tool_text non vide
    # (on vérifie juste que la signature accepte le paramètre)
    import inspect
    sig = inspect.signature(llm._execute_and_respond_stream)
    assert "pre_tool_text" in sig.parameters


# ── Cas 4 : historique complet après consommation partielle ───────────────────

def test_cas4_drain_after_partial_consumption():
    """Drain du générateur après arrêt précoce → _last_response complet."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text("Un "), _mk_text("deux "), _mk_text("trois")]),
        tc,
    )
    # Simuler TTS qui consomme seulement le 1er chunk
    first = next(gen)
    assert first == "Un "
    assert llm._last_response == "Un "

    # Drain explicite (ce que chat_with_tools fait après speak_streaming)
    for _ in gen:
        pass

    assert llm._last_response == "Un deux trois"


def test_cas4_full_consumption_idempotent():
    """Drain après consommation complète = no-op, _last_response inchangé."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text("Alpha"), _mk_text(" Beta")]),
        tc,
    )
    # Consommation complète
    "".join(gen)
    snapshot = llm._last_response

    # Drain supplémentaire : ne doit rien changer
    for _ in gen:
        pass

    assert llm._last_response == snapshot == "Alpha Beta"


def test_cas4_last_response_equals_concatenation():
    """_last_response == concat de tous les chunks yielded, dans l'ordre."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    texts = ["Bonjour ", "voici ", "votre ", "réponse."]
    gen = llm._make_stream_gen(iter([_mk_text(t) for t in texts]), tc)
    yielded = list(gen)
    assert "".join(yielded) == "".join(texts)
    assert llm._last_response == "".join(texts)
