"""
Speech-to-text : transcrit l'audio enregistré par le candidat en texte,
en envoyant les octets audio directement à Gemini (compréhension multimodale).
"""

from google.genai import types as genai_types

from api import ai_gateway
from api import ai_logging

TRANSCRIBE_PROMPT = (
    "Transcris fidèlement, en français, la réponse orale ci-jointe donnée par un "
    "candidat lors d'un entretien d'embauche. Ne renvoie que le texte transcrit, "
    "sans commentaire, sans guillemets, sans préfixe."
)


def transcribe(audio_bytes: bytes, mime_type: str = "audio/webm",
                interview_id: str | None = None) -> str:
    """Transcrit un extrait audio en texte. Renvoie une chaîne vide si aucune clé n'est configurée."""
    client = ai_gateway.get_client()
    if not client:
        print("[STT] No client – returning empty transcript")
        return ""

    try:
        with ai_logging.timed_call("stt", ai_gateway.GEMINI_MODEL, interview_id=interview_id) as record:
            audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            response = client.models.generate_content(
                model=ai_gateway.GEMINI_MODEL,
                contents=[TRANSCRIBE_PROMPT, audio_part],
            )
            record(response.usage_metadata)
        return (response.text or "").strip()
    except Exception as e:
        print(f"[STT] Exception: {e}")
        return ""
