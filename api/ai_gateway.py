"""
Passerelle unique vers l'API Gemini : un seul client, une seule clé,
réutilisé par app.py et par tous les modules de api/ (speech, interviewengine,
profileprocessing) pour éviter de dupliquer la configuration du SDK.
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

if GEMINI_API_KEY:
    _client = genai.Client(api_key=GEMINI_API_KEY)
else:
    _client = None
    print("⚠️  GEMINI_API_KEY not set – AI features will return mock data.")


def get_client():
    """Renvoie le client google-genai partagé, ou None si aucune clé n'est configurée."""
    return _client


def ai_call(prompt: str, fallback: dict, context: str = "other",
            interview_id: str | None = None, session_id: str | None = None,
            user_id: str | None = None) -> dict:
    """Appelle Gemini et parse une réponse JSON. Renvoie fallback en cas d'erreur.

    `context` étiquette l'appel (ex: 'cv_parse', 'interview_question', 'chat')
    pour les métriques du tableau de bord admin (coût, tokens, latence par
    fonctionnalité, répartition par modèle).
    """
    if not _client:
        print("[AI] No client – returning fallback")
        return fallback

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
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())

        print(f"[AI] Could not parse JSON from response – using fallback")
        return fallback

    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        ai_logging.log_call(
            context, GEMINI_MODEL, None, None, latency_ms, False, str(e),
            interview_id=interview_id, session_id=session_id, user_id=user_id
        )
        print(f"[AI] Exception: {e}")
        traceback.print_exc()
        return fallback
