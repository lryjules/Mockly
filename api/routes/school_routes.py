"""Routes du tableau de bord "profil école" : /api/school/dashboard,
/api/school/students/<id>/token-bonus, /api/school/token-bonus/bulk.

Sécurité : l'identité vient d'un token de session Clerk vérifié (@require_auth,
voir api/clerk_auth.py). Chaque action est en plus scopée au school_id du
compte "profil école" qui appelle — un compte école ne peut jamais lire ni
modifier un élève d'une autre école.

Le bonus quotidien accordé à un élève (au-delà du quota gratuit défini par
api.token_budget.DEFAULT_DAILY_TOKEN_LIMIT) n'est jamais garanti au moment où
il est réglé ici : il n'est réellement actif que tant que le pool mensuel de
l'école (schools.monthly_bonus_token_pool) n'est pas épuisé — voir
api/token_budget.py::get_effective_daily_limit.
"""

import csv
import io
import re
from pathlib import Path

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import school_metrics
from api import token_budget
from api import organizations
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, get_or_create_local_user

school_bp = Blueprint("school", __name__)

MAX_BONUS_DAILY_TOKENS = token_budget.MAX_DAILY_TOKEN_LIMIT - token_budget.DEFAULT_DAILY_TOKEN_LIMIT

MAX_EMAIL_LEN = 254
MAX_NAME_LEN = 100
MAX_CSV_SIZE = 2 * 1024 * 1024  # 2 Mo
# Chaque ligne déclenche un appel réseau réel à l'API Clerk (pas de file
# d'attente/traitement en arrière-plan dans cette app) — au-delà, le risque
# de dépasser le timeout gunicorn (120s) devient réel. Limite MVP assumée.
MAX_CSV_ROWS = 300
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def _get_school_admin(clerk_user_id: str | None):
    """Renvoie le profil local si cet utilisateur Clerk est un compte "profil école" valide, sinon None."""
    if not clerk_user_id:
        return None
    row = get_or_create_local_user(clerk_user_id)
    if not row or not row["is_school_admin"] or not row["school_id"]:
        return None
    return row


@school_bp.route("/api/school/dashboard", methods=["GET"])
@require_auth
def get_dashboard():
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    dashboard = school_metrics.get_school_dashboard(admin["school_id"])
    return jsonify(dashboard)


@school_bp.route("/api/school/students/<student_id>/token-bonus", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def update_student_token_bonus(student_id):
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403
    data = request.get_json(force=True)

    if "bonus_daily_token_limit" not in data:
        return jsonify({"error": "bonus_daily_token_limit requis"}), 400
    try:
        bonus = max(0, min(MAX_BONUS_DAILY_TOKENS, int(data["bonus_daily_token_limit"])))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_daily_token_limit doit être un entier"}), 400

    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id=%s AND school_id=%s", (student_id, admin["school_id"])
        ).fetchone()
        if not student:
            return jsonify({"error": "Élève introuvable dans ton école"}), 404

        conn.execute("UPDATE users SET bonus_daily_token_limit=%s WHERE id=%s", (bonus, student_id))

    return jsonify({
        "bonus_daily_token_limit": bonus,
        "daily_token_limit": token_budget.DEFAULT_DAILY_TOKEN_LIMIT + bonus,
    })


@school_bp.route("/api/school/token-bonus/bulk", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def bulk_update_token_bonus():
    """Ajoute (ou retire, avec un delta négatif) un bonus quotidien à tout le pool d'élèves de l'école."""
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403
    data = request.get_json(force=True)

    if "bonus_daily_token_limit_delta" not in data:
        return jsonify({"error": "bonus_daily_token_limit_delta requis"}), 400
    try:
        delta = max(-MAX_BONUS_DAILY_TOKENS, min(MAX_BONUS_DAILY_TOKENS, int(data["bonus_daily_token_limit_delta"])))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_daily_token_limit_delta doit être un entier"}), 400

    with get_db() as conn:
        conn.execute(
            f"UPDATE users SET bonus_daily_token_limit = LEAST({MAX_BONUS_DAILY_TOKENS}, GREATEST(0, bonus_daily_token_limit + %s)) "
            "WHERE school_id=%s AND is_admin=0 AND is_school_admin=0",
            (delta, admin["school_id"])
        )
        nb_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=%s AND is_admin=0 AND is_school_admin=0",
            (admin["school_id"],)
        ).fetchone()[0]

    return jsonify({"message": "Bonus de tokens mis à jour", "nb_students": nb_students})


@school_bp.route("/api/school/students", methods=["GET"])
@require_auth
def list_school_students():
    """Roster combiné : élèves actifs + invitations en attente, plus l'état
    des sièges. Route additive — ne remplace pas /api/school/dashboard."""
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    with get_db() as conn:
        active = conn.execute(
            """SELECT id, email, created_at FROM users
               WHERE school_id=%s AND is_admin=0 AND is_school_admin=0
               ORDER BY created_at DESC""",
            (admin["school_id"],)
        ).fetchall()
        invited = conn.execute(
            """SELECT email, first_name, last_name, created_at FROM pending_org_invites
               WHERE organization_id=%s AND role='STUDENT'
               ORDER BY created_at DESC""",
            (admin["school_id"],)
        ).fetchall()
        seats = organizations.get_seat_usage(admin["school_id"], conn=conn)

    return jsonify({
        "active": [{"id": r["id"], "email": r["email"], "created_at": r["created_at"]} for r in active],
        "invited": [
            {"email": r["email"], "first_name": r["first_name"], "last_name": r["last_name"], "created_at": r["created_at"]}
            for r in invited
        ],
        "seats": seats,
    })


@school_bp.route("/api/school/students/invite", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def invite_student():
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip() or None
    last_name = (data.get("last_name") or "").strip() or None

    if not email:
        return jsonify({"error": "Email requis"}), 400
    if err := validate_length(email, "email", MAX_EMAIL_LEN):
        return err
    if not _valid_email(email):
        return jsonify({"error": "Adresse email invalide"}), 400
    for label, value in (("Prénom", first_name), ("Nom", last_name)):
        if value and (err := validate_length(value, label, MAX_NAME_LEN)):
            return err

    if not organizations.has_available_seats(admin["school_id"]):
        usage = organizations.get_seat_usage(admin["school_id"])
        return jsonify({
            "error": f"Plus de siège disponible ({usage['used']}/{usage['limit']} utilisés)",
            "seats": usage,
        }), 409

    result = organizations.send_org_invite(
        email, admin["school_id"], "STUDENT", invited_by=admin["id"],
        first_name=first_name, last_name=last_name,
    )
    status_code = {
        "applied": 200, "pending": 200,
        "already_member": 409, "conflict": 409, "failed": 502,
    }[result["status"]]
    return jsonify(result), status_code


@school_bp.route("/api/school/students/import-csv", methods=["POST"])
@require_auth
@limiter.limit("10 per hour")
def import_students_csv():
    """CSV attendu : colonnes first_name,last_name,email (en-tête insensible
    à la casse). Rejet atomique si les sièges disponibles ne suffisent pas
    pour toutes les nouvelles lignes — jamais d'import partiel silencieux."""
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Nom de fichier vide"}), 400
    if Path(file.filename).suffix.lower() != ".csv":
        return jsonify({"error": "Format non supporté. Utilise un fichier .csv"}), 400

    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_CSV_SIZE:
        return jsonify({"error": "Fichier trop volumineux (max 2 Mo)"}), 413
    if size == 0:
        return jsonify({"error": "Fichier vide"}), 400

    try:
        raw = file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"error": "Fichier illisible : encodage attendu UTF-8"}), 400

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return jsonify({"error": "En-têtes CSV manquants"}), 400
    headers = {h.strip().lower(): h for h in reader.fieldnames}
    required = ("first_name", "last_name", "email")
    missing = [h for h in required if h not in headers]
    if missing:
        return jsonify({"error": f"Colonnes manquantes : {', '.join(missing)}"}), 400

    rows = list(reader)
    if not rows:
        return jsonify({"error": "Le fichier ne contient aucune ligne"}), 400
    if len(rows) > MAX_CSV_ROWS:
        return jsonify({"error": f"Trop de lignes ({len(rows)}), maximum {MAX_CSV_ROWS} par import. Divise le fichier."}), 400

    seen_emails = set()
    parsed = []
    skipped = []
    for i, row in enumerate(rows, start=2):  # ligne 1 = en-têtes
        email = (row.get(headers["email"]) or "").strip().lower()
        first_name = (row.get(headers["first_name"]) or "").strip()
        last_name = (row.get(headers["last_name"]) or "").strip()
        if not email or not _valid_email(email):
            skipped.append({"row": i, "email": email, "reason": "Email invalide ou manquant"})
            continue
        if email in seen_emails:
            skipped.append({"row": i, "email": email, "reason": "Doublon dans le fichier"})
            continue
        seen_emails.add(email)
        parsed.append({"email": email, "first_name": first_name or None, "last_name": last_name or None})

    if not parsed:
        return jsonify({
            "created": [], "skipped": skipped, "failed": [],
            "seats": organizations.get_seat_usage(admin["school_id"]),
        })

    if not organizations.has_available_seats(admin["school_id"], additional=len(parsed)):
        usage = organizations.get_seat_usage(admin["school_id"])
        available = (usage["limit"] - usage["used"]) if usage["limit"] is not None else None
        return jsonify({
            "error": (
                f"Sièges insuffisants : {available if available is not None else '?'} disponible(s) "
                f"pour {len(parsed)} nouvelle(s) invitation(s) demandée(s)."
            ),
            "seats": usage,
        }), 409

    created, failed = [], []
    for entry in parsed:
        result = organizations.send_org_invite(
            entry["email"], admin["school_id"], "STUDENT", invited_by=admin["id"],
            first_name=entry["first_name"], last_name=entry["last_name"],
        )
        if result["status"] in ("applied", "pending"):
            created.append({"email": entry["email"], "status": result["status"]})
        elif result["status"] in ("already_member", "conflict"):
            skipped.append({"email": entry["email"], "reason": result.get("reason") or result["status"]})
        else:
            failed.append({"email": entry["email"], "reason": result.get("reason") or "Échec inconnu"})

    return jsonify({
        "created": created, "skipped": skipped, "failed": failed,
        "seats": organizations.get_seat_usage(admin["school_id"]),
    })
