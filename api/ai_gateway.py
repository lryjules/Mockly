"""
Passerelle unique vers l'API Gemini : un seul client, une seule clé,
réutilisé par app.py et par tous les modules de api/ (speech, interviewengine,
profileprocessing) pour éviter de dupliquer la configuration du SDK.

Pas de fallback silencieux : toute erreur (clé manquante, appel Gemini en
échec, réponse non-JSON) lève AIError, à charge des routes de la remonter
telle quelle au client plutôt que de servir des données factices sans que
personne ne s'en aperçoive.
"""

import os
import re
import json
import time
import traceback

from google import genai
from google.genai import types as genai_types

from api import ai_logging

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-flash-latest"

# Le SDK retente par défaut jusqu'à 5 fois (backoff exponentiel 1s/2s/4s/8s...,
# y compris sur 429) avant de lever. On limite les tentatives pour échouer
# raisonnablement vite sur une erreur persistante (ex. crédits Gemini épuisés).
#
# Le timeout par tentative doit rester généreux : un prompt volumineux
# (ex. cv_parse, ~8000 caractères de CV, réponse JSON structurée détaillée)
# peut légitimement prendre 10-20s chez Gemini Flash — un timeout de 10s
# faisait échouer ces appels valides avec un faux 504 DEADLINE_EXCEEDED.
# La vraie contrainte à respecter est le timeout du worker gunicorn (voir
# Procfile, --timeout 120), pas un timeout de proxy plus court : on reste
# large ici (~25s/tentative) et c'est gunicorn qui borne le pire cas.
_HTTP_OPTIONS = genai_types.HttpOptions(
    timeout=25_000,  # ms, par tentative
    retry_options=genai_types.HttpRetryOptions(attempts=2, initial_delay=0.5, max_delay=2.0),
)

if GEMINI_API_KEY:
    _client = genai.Client(api_key=GEMINI_API_KEY, http_options=_HTTP_OPTIONS)
else:
    _client = None
    print("⚠️  GEMINI_API_KEY not set – les fonctionnalités IA échoueront.")


class AIError(RuntimeError):
    """Levée pour tout échec d'appel IA (clé manquante, erreur Gemini, réponse
    non exploitable) — jamais avalée en silence."""


def get_client():
    """Renvoie le client google-genai partagé, ou None si aucune clé n'est configurée."""
    return _client


def ai_call(prompt: str, context: str = "other",
            interview_id: str | None = None, session_id: str | None = None,
            user_id: str | None = None) -> dict:
    """Appelle Gemini et parse une réponse JSON. Lève AIError en cas d'échec.

    `context` étiquette l'appel (ex: 'cv_parse', 'interview_question', 'chat')
    pour les métriques du tableau de bord admin (coût, tokens, latence par
    fonctionnalité, répartition par modèle).
    """
    if not _client:
        raise AIError("GEMINI_API_KEY manquant côté serveur — fonctionnalités IA indisponibles.")

    start = time.monotonic()
    try:
        print(f"[AI] Calling {GEMINI_MODEL} ...")
        response = _client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
            )
        )
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        ai_logging.log_call(
            context, GEMINI_MODEL, None, None, latency_ms, False, str(e),
            interview_id=interview_id, session_id=session_id, user_id=user_id
        )
        print(f"[AI] Exception: {e}")
        traceback.print_exc()
        raise AIError(f"Appel Gemini en échec ({context}) : {e}") from e

    latency_ms = int((time.monotonic() - start) * 1000)
    usage = response.usage_metadata
    ai_logging.log_call(
        context, GEMINI_MODEL,
        getattr(usage, "prompt_token_count", None) if usage else None,
        getattr(usage, "candidates_token_count", None) if usage else None,
        latency_ms, True, interview_id=interview_id, session_id=session_id,
        user_id=user_id
    )

    text = response.text.strip()
    print(f"[AI] Raw response ({len(text)} chars): {text[:200]}...")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if text.startswith("```"):
        stripped = text.split("\n", 1)[1]
        stripped = stripped.rsplit("```", 1)[0]
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise AIError(f"Réponse Gemini non-JSON pour '{context}' : {text[:300]}")
