"""
Limites de sécurité partagées : rate limiting (protection brute-force /
abus de coût IA) et validation de longueur des champs texte libres avant
qu'ils ne partent vers Gemini ou la base.

`limiter` est créé ici sans app liée (pattern factory de Flask-Limiter) pour
pouvoir être importé et décorer les routes dans chaque blueprint sans import
circulaire ; il est rattaché à l'app via `limiter.init_app(app)` dans app.py.

Stockage en mémoire : suffisant pour un seul dyno (ex. Render free/starter).
Si l'app tourne un jour sur plusieurs instances, il faudra passer à un
backend partagé (Redis) via storage_uri, sinon chaque instance a ses propres
compteurs et la limite réelle devient (limite × nombre d'instances).
"""

from flask import jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per hour", "60 per minute"],
    storage_uri="memory://",
)


def validate_length(value: str, field: str, max_len: int, min_len: int = 0):
    """Renvoie une réponse JSON d'erreur (à `return`r par l'appelant) si la
    longueur de `value` est hors bornes, sinon None."""
    length = len(value or "")
    if length < min_len:
        return jsonify({"error": f"{field} doit contenir au moins {min_len} caractères"}), 400
    if length > max_len:
        return jsonify({"error": f"{field} ne doit pas dépasser {max_len} caractères"}), 400
    return None
