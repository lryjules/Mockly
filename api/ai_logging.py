"""
Journalisation des appels Gemini (coût, tokens, latence, erreurs) pour le
tableau de bord admin. Les tarifs ci-dessous sont des estimations (à ajuster
selon les prix réels du modèle utilisé) — ils permettent d'obtenir un ordre
de grandeur du coût plutôt qu'une facturation exacte.
"""

import time
from contextlib import contextmanager

from api.db import get_db

# USD pour 1 million de tokens. Approximatif (tarif "Flash" générique) :
# à ajuster si le modèle réellement utilisé (cf. ai_gateway.GEMINI_MODEL)
# a une grille tarifaire différente.
PRICE_PER_MILLION_TOKENS = {
    "input": 0.075,
    "output": 0.30,
}


def estimate_cost(input_tokens: int | None, output_tokens: int | None) -> float:
    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    return (
        input_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS["input"]
        + output_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS["output"]
    )


def log_call(context: str, model: str | None, input_tokens: int | None,
             output_tokens: int | None, latency_ms: int, success: bool,
             error_message: str | None = None, interview_id: str | None = None,
             session_id: str | None = None) -> None:
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO ai_call_log
                   (context, model, input_tokens, output_tokens, latency_ms,
                    success, error_message, interview_id, session_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (context, model, input_tokens, output_tokens, latency_ms,
                 int(success), error_message, interview_id, session_id)
            )
    except Exception as e:
        # La journalisation ne doit jamais faire échouer l'appel IA lui-même.
        print(f"[ai_logging] Impossible d'enregistrer l'appel : {e}")


@contextmanager
def timed_call(context: str, model: str | None, interview_id: str | None = None,
               session_id: str | None = None):
    """Chronomètre un appel Gemini et le journalise automatiquement.

    Usage :
        with timed_call("interview_question", model) as record:
            response = client.models.generate_content(...)
            record(response.usage_metadata)
    En cas d'exception, l'appel est journalisé comme échec avant d'être
    re-levée.
    """
    start = time.monotonic()
    usage_holder = {}

    def record(usage_metadata=None):
        usage_holder["usage_metadata"] = usage_metadata

    try:
        yield record
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        log_call(context, model, None, None, latency_ms, False, str(e),
                  interview_id, session_id)
        raise
    else:
        latency_ms = int((time.monotonic() - start) * 1000)
        usage = usage_holder.get("usage_metadata")
        input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        output_tokens = getattr(usage, "candidates_token_count", None) if usage else None
        log_call(context, model, input_tokens, output_tokens, latency_ms, True,
                  None, interview_id, session_id)
