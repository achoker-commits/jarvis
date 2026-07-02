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


# ── Cas 5 : tool call inline malformé (llama-3.3 bug) ────────────────────────

def test_cas5_malformed_inline_tool_call_filtered():
    """
    llama-3.3 émet <function=systeme{"action":"batterie"}</function> dans le
    content au lieu d'utiliser tool_calls → le fragment ne doit PAS être yielded
    vers le TTS, et tc_state doit être rempli correctement.
    """
    import json
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text('<function=systeme{"action": "batterie"}</function>')]),
        tc,
    )
    yielded = list(gen)
    all_text = "".join(yielded)
    assert "<function=" not in all_text, f"Fragment malformé transmis au TTS : {all_text!r}"
    assert tc["is_tool"]
    assert tc["name"] == "systeme"
    args = json.loads(tc["args"])
    assert args.get("action") == "batterie"


def test_cas5_malformed_with_pre_text():
    """Texte légitme avant le tool call inline → texte yielded, outil détecté."""
    import json
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([
            _mk_text("Je vérifie la batterie..."),
            _mk_text('<function=systeme{"action": "batterie"}</function>'),
        ]),
        tc,
    )
    yielded = list(gen)
    all_text = "".join(yielded)
    assert "<function=" not in all_text
    assert "Je vérifie la batterie..." in all_text
    assert tc["is_tool"]
    assert tc["name"] == "systeme"
    args = json.loads(tc["args"])
    assert args.get("action") == "batterie"


def test_cas5_malformed_split_across_chunks():
    """Tool call malformé arrivant en plusieurs chunks — tous filtrés."""
    import json
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([
            _mk_text("<function="),
            _mk_text('meteo{"ville":'),
            _mk_text(' "Charleroi"}</function>'),
        ]),
        tc,
    )
    yielded = list(gen)
    all_text = "".join(yielded)
    assert "<function=" not in all_text
    assert tc["is_tool"]
    assert tc["name"] == "meteo"
    args = json.loads(tc["args"])
    assert args.get("ville") == "Charleroi"


def test_cas5_no_false_positive_function_word():
    """Le mot 'function' normal dans le texte ne doit PAS déclencher le filtre."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    text = "La fonction principale de cet outil est simple."
    gen = llm._make_stream_gen(iter([_mk_text(text)]), tc)
    yielded = list(gen)
    assert "".join(yielded) == text
    assert not tc["is_tool"]


# ── Cas 6 : variantes du format inline (régression 2026-07-02) ───────────────

def test_cas6_closing_bracket_gt_variant():
    """`<function=NAME{...}></function>` — '}>' avant '</function>' (régression réelle)."""
    import json
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text('<function=recherche_info{"requete": "test"}></function>')]),
        tc,
    )
    yielded = list(gen)
    assert "<function=" not in "".join(yielded)
    assert tc["is_tool"]
    assert tc["name"] == "recherche_info"
    assert json.loads(tc["args"]) == {"requete": "test"}


def test_cas6_html_style_tag():
    """`<function=NAME>{"k":"v"}</function>` — '>' après le nom, JSON en corps."""
    import json
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text('<function=meteo>{"ville": "Paris"}</function>')]),
        tc,
    )
    yielded = list(gen)
    assert "<function=" not in "".join(yielded)
    assert tc["is_tool"]
    assert tc["name"] == "meteo"
    assert json.loads(tc["args"]) == {"ville": "Paris"}


def test_cas6_no_closing_tag_stream_truncated():
    """Stream tronqué : `<function=NAME{...}>` sans `</function>` → pas yielded, outil récupéré."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text('<function=volume{"action": "monter"}>')]),
        tc,
    )
    yielded = list(gen)
    # Le fragment malformé ne doit PAS être transmis au TTS
    assert "<function=" not in "".join(yielded)
    # L'outil doit être détecté
    assert tc["is_tool"]
    assert tc["name"] == "volume"


def test_cas6_orphan_tag_only():
    """`<function=NAME>` seul sans JSON ni fermeture → silencieux, outil détecté."""
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([_mk_text("<function=systeme>")]),
        tc,
    )
    yielded = list(gen)
    assert "<function=" not in "".join(yielded)
    assert tc["is_tool"]
    assert tc["name"] == "systeme"


def test_cas6_pre_text_then_closing_gt():
    """Texte légitime + `<function=NAME{...}></function>` → texte yielded, outil détecté."""
    import json
    llm = _new_llm()
    tc = {"is_tool": False, "id": "", "name": "", "args": ""}
    gen = llm._make_stream_gen(
        iter([
            _mk_text("Je cherche ça pour vous."),
            _mk_text('<function=recherche_info{"requete": "belgique"}></function>'),
        ]),
        tc,
    )
    yielded = list(gen)
    all_text = "".join(yielded)
    assert "<function=" not in all_text
    assert "Je cherche ça pour vous." in all_text
    assert tc["is_tool"]
    assert json.loads(tc["args"]) == {"requete": "belgique"}
