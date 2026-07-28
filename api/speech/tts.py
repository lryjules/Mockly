"""
Text-to-speech : synthétise les questions de l'IA en voix française
via gTTS (gratuit, aucune clé requise).
"""

import io

from gtts import gTTS


def synthesize(text: str, lang: str = "fr") -> bytes:
    """Synthétise du texte en audio MP3. Renvoie les octets du fichier MP3."""
    buffer = io.BytesIO()
    gTTS(text=text, lang=lang).write_to_fp(buffer)
    return buffer.getvalue()
