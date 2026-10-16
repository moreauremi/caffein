# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités de la Qualité : non-conformités, leurs actions correctives et préventives, et le plan d'actions.

Une non-conformité (réclamation client, défaut fournisseur, défaut interne, constat d'audit) est déclarée
« Ouverte », passe « En analyse », puis « Actions en cours » une fois sa cause racine trouvée et ses actions
décidées ; elle se clôture (niveau gestion) quand toutes ses actions sont faites, et se rouvre si besoin. Ses actions
sont des lignes de la fiche ; le plan d'actions (vue SQL) les rassemble toutes, avec leur échéance et leur retard.
Les chiffres (actions restant à faire, ancienneté, retard) sont calculés ici, jamais stockés.

L'article (Données techniques), le fournisseur (Achats), le client (Ventes) et le responsable d'une action (RH)
sont des références facultatives : sans ces modules, les champs disparaissent et la Qualité fonctionne quand même.
"""

from __future__ import annotations

from ... import db
from ...core.entities import Action, Child, Entity, Field
from ...core.errors import Conflict
from ...core.modules import MANAGE
from ...utils import parse_date, today

MIGRATIONS = [
    (1, """
-- article_id : article des Données techniques ; supplier_id : fournisseur des Achats ; client_id : client des Ventes
-- (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS quality_nonconformities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    detected_on TEXT,
    origin TEXT NOT NULL DEFAULT 'internal' CHECK (origin IN ('customer', 'supplier', 'internal', 'audit')),
    severity TEXT NOT NULL DEFAULT 'minor' CHECK (severity IN ('minor', 'major', 'critical')),
    article_id INTEGER,
    supplier_id INTEGER,
    client_id INTEGER,
    quantity_affected REAL,
    description TEXT NOT NULL DEFAULT '',
    root_cause TEXT NOT NULL DEFAULT '',
    cost REAL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'analysis', 'action', 'closed')),
    closed_on TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_quality_nonconformities_code ON quality_nonconformities(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_quality_nonconformities_status ON quality_nonconformities(status, severity);
CREATE INDEX IF NOT EXISTS idx_quality_nonconformities_detected ON quality_nonconformities(detected_on);
CREATE INDEX IF NOT EXISTS idx_quality_nonconformities_article ON quality_nonconformities(article_id);
CREATE INDEX IF NOT EXISTS idx_quality_nonconformities_supplier ON quality_nonconformities(supplier_id);
CREATE INDEX IF NOT EXISTS idx_quality_nonconformities_client ON quality_nonconformities(client_id);

-- Actions correctives et préventives d'une non-conformité. owner_id : salarié des RH (pas de clé étrangère vers un
-- autre module)
CREATE TABLE IF NOT EXISTS quality_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nonconformity_id INTEGER NOT NULL REFERENCES quality_nonconformities(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'corrective' CHECK (kind IN ('corrective', 'preventive')),
    description TEXT NOT NULL DEFAULT '',
    owner_id INTEGER,
    due_date TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    done_on TEXT
);
CREATE INDEX IF NOT EXISTS idx_quality_actions_nonconformity ON quality_actions(nonconformity_id, position);
CREATE INDEX IF NOT EXISTS idx_quality_actions_due ON quality_actions(done, due_date);
CREATE INDEX IF NOT EXISTS idx_quality_actions_owner ON quality_actions(owner_id);

-- Plan d'actions : chaque action avec sa non-conformité (consultation)
CREATE VIEW IF NOT EXISTS quality_action_plan AS
    SELECT a.id AS id, a.description AS description, n.id AS nonconformity_id, n.code AS nonconformity_code,
           n.title AS nonconformity_title, n.status AS nonconformity_status, a.kind AS kind, a.owner_id AS owner_id,
           a.due_date AS due_date, a.done AS done, a.done_on AS done_on
    FROM quality_actions a JOIN quality_nonconformities n ON n.id = a.nonconformity_id;
"""),
]

ORIGINS = (
    ("customer", ("Réclamation client", "Customer complaint")), ("supplier", ("Fournisseur", "Supplier")),
    ("internal", ("Interne", "Internal")), ("audit", ("Audit", "Audit")),
)
SEVERITIES = (
    ("minor", ("Mineure", "Minor"), "outline"), ("major", ("Majeure", "Major"), "warn"),
    ("critical", ("Critique", "Critical"), "bad"),
)
STATUSES = (
    ("open", ("Ouverte", "Open"), "bad"), ("analysis", ("En analyse", "Under analysis"), "warn"),
    ("action", ("Actions en cours", "Actions in progress"), "info"), ("closed", ("Clôturée", "Closed"), "good"),
)
ACTION_KINDS = (("corrective", ("Corrective", "Corrective")), ("preventive", ("Préventive", "Preventive"), "info"))
CHANGED = "La non-conformité vient d'être modifiée par ailleurs : rechargez-la."
CLOSED = "Non-conformité clôturée : elle ne se modifie plus. Rouvrez-la pour la compléter."


def _today() -> str:
    return today().isoformat()


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


def is_overdue(done: object, due_date: object, day=None) -> bool:
    """Action en retard : pas encore faite et son échéance est passée (aujourd'hui n'est pas en retard).
    Une seule règle pour le plan d'actions et le chiffre clé de l'accueil."""
    due = parse_date(due_date)
    return bool(not done and due is not None and due < (day or today()))


# ═════════════════════════════════════════════════════════════════════════
# Non-conformités
# ═════════════════════════════════════════════════════════════════════════
def _nc_figures(rows: list[dict]) -> None:
    """Actions restant à faire : depuis les lignes de la fiche (fiche, saisie en cours), sinon par une requête groupée
    (liste). Ancienneté : jours écoulés depuis la détection, jusqu'à la clôture ou jusqu'à aujourd'hui."""
    missing = [r["id"] for r in rows if "actions" not in r and r.get("id")]
    pending: dict[int, int] = {}
    if missing:
        pending = {r["nonconformity_id"]: r["n"] for r in db.fetch_all(
            f"SELECT nonconformity_id, COUNT(*) AS n FROM quality_actions WHERE done = 0 "
            f"AND nonconformity_id IN ({_marks(missing)}) GROUP BY nonconformity_id", tuple(missing))}
    day = today()
    for row in rows:
        if "actions" in row:
            row["actions_open"] = sum(1 for line in row["actions"] or [] if not line.get("done"))
        else:
            row["actions_open"] = pending.get(row.get("id"), 0)
        detected = parse_date(row.get("detected_on"))
        end = parse_date(row.get("closed_on")) or day
        row["age_days"] = (end - detected).days if detected else None


def _nc_validate(values: dict, existing: dict | None) -> None:
    detected = parse_date(values.get("detected_on"))
    if detected and detected > today():
        raise ValueError("Détectée le : la date ne peut pas être dans le futur.")
    lines = values.get("actions") or []
    for i, line in enumerate(lines, start=1):
        done_on = parse_date(line.get("done_on"))
        if done_on and done_on > today():
            raise ValueError(f"Actions, ligne {i} — Faite le : la date ne peut pas être dans le futur.")
    if values.get("status") == "action":  # actions engagées : leur cause et au moins une action restent
        if not (values.get("root_cause") or "").strip():
            raise ValueError("Cause racine : elle reste obligatoire tant que les actions sont en cours.")
        if not lines:
            raise ValueError("Actions : gardez au moins une action tant que les actions sont en cours.")


def _nc_after_save(row_id: int, created: bool) -> None:
    """Faite le : la date du jour pour une action cochée sans date ; effacée pour une action décochée."""
    with db.connect() as conn:
        conn.execute("UPDATE quality_actions SET done_on = ? WHERE nonconformity_id = ? AND done = 1 AND done_on IS NULL",
                     (_today(), row_id))
        conn.execute("UPDATE quality_actions SET done_on = NULL WHERE nonconformity_id = ? AND done = 0 "
                     "AND done_on IS NOT NULL", (row_id,))


def _nc_locked(row: dict) -> str | None:
    return CLOSED if row.get("status") == "closed" else None


def _nc_before_delete(row: dict) -> None:
    if row.get("status") == "closed":
        raise Conflict("Une non-conformité clôturée ne se supprime pas : elle fait partie de l'historique qualité.")


def _move(row: dict, status: str, origins: tuple[str, ...], **extra) -> None:
    """Change le statut, seulement depuis l'un des statuts `origins` : deux actions simultanées sur la même fiche
    (double clic, deux personnes) ne passent pas toutes les deux."""
    values = {"status": status, "updated_at": db.now_iso(), **extra}
    sets = ", ".join(f"{name} = ?" for name in values)
    with db.connect() as conn:
        cur = conn.execute(f"UPDATE quality_nonconformities SET {sets} WHERE id = ? AND status IN ({_marks(origins)})",
                           (*values.values(), row["id"], *origins))
        if cur.rowcount == 0:
            raise Conflict(CHANGED)


def _closing_date(payload: dict, row: dict) -> str:
    """Date de clôture : celle du jour, ou celle indiquée (clôture saisie après coup), ni dans le futur, ni avant la
    détection."""
    value = payload.get("date")
    if value in (None, ""):
        return _today()
    day = parse_date(value) if isinstance(value, str) else None
    if day is None:
        raise ValueError("Clôturée le : date invalide.")
    if day > today():
        raise ValueError("Clôturée le : la date ne peut pas être dans le futur.")
    if row.get("detected_on") and day.isoformat() < row["detected_on"]:
        raise ValueError("Clôturée le : elle ne peut pas précéder la date de détection.")
    return day.isoformat()


def _analyse(row: dict, payload: dict, user: dict) -> str:
    _move(row, "analysis", ("open",))
    return f"Non-conformité {row['code']} en analyse."


def _plan(row: dict, payload: dict, user: dict) -> str:
    if not (row.get("root_cause") or "").strip():
        raise ValueError("Cause racine : renseignez-la avant d'engager les actions.")
    if not row.get("actions"):
        raise ValueError("Actions : ajoutez au moins une action corrective ou préventive avant de les engager.")
    _move(row, "action", ("open", "analysis"))
    return f"Non-conformité {row['code']} : actions engagées."


def _close(row: dict, payload: dict, user: dict) -> str:
    pending = [line for line in row.get("actions") or [] if not line.get("done")]
    if pending:
        raise ValueError(f"Actions : {len(pending)} action(s) pas encore faite(s) ; la non-conformité se clôture une "
                         "fois toutes ses actions faites.")
    day = _closing_date(payload, row)
    _move(row, "closed", ("action",), closed_on=day)
    return f"Non-conformité {row['code']} clôturée."


def _reopen(row: dict, payload: dict, user: dict) -> str:
    _move(row, "action", ("closed",), closed_on=None)
    return f"Non-conformité {row['code']} rouverte : ses actions sont de nouveau en cours."


ACTION_FIELDS = [
    Field("kind", ("Type", "Type"), type="enum", choices=ACTION_KINDS, default="corrective", required=True),
    Field("description", ("Action", "Action"), required=True, maxlength=300, width="full"),
    Field("owner_id", ("Responsable", "Owner"), type="ref", ref="hr.employees"),
    Field("due_date", ("Échéance", "Due date"), type="date"),
    Field("done", ("Faite", "Done"), type="bool", default=False),
    Field("done_on", ("Faite le", "Done on"), type="date",
          help=("La date du jour si l'action est cochée sans date.", "Today's date when the action is ticked without one.")),
]

NONCONFORMITIES = Entity(
    module="quality", name="nonconformities", table="quality_nonconformities", label=("Non-conformité", "Non-conformity"),
    plural=("Non-conformités", "Non-conformities"), title="title", subtitle="code", order_by="detected_on DESC, id DESC",
    icon="FileWarning", board="status",
    description=("Réclamations clients, défauts fournisseurs ou internes, constats d'audit : analysez la cause, menez les "
                 "actions correctives et préventives, puis clôturez.",
                 "Customer complaints, supplier or internal defects, audit findings: analyse the root cause, carry out "
                 "corrective and preventive actions, then close."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="NC", readonly=True, list=True, search=True),
        Field("title", ("Intitulé", "Title"), required=True, list=True, search=True, maxlength=160),
        Field("detected_on", ("Détectée le", "Detected on"), type="date", default=_today, required=True, list=True),
        Field("origin", ("Origine", "Origin"), type="enum", choices=ORIGINS, default="internal", required=True, list=True,
              filter=True),
        Field("severity", ("Gravité", "Severity"), type="enum", choices=SEVERITIES, default="minor", required=True,
              list=True, filter=True),
        Field("status", ("Statut", "Status"), type="enum", choices=STATUSES, default="open", readonly=True, list=True,
              filter=True),
        Field("article_id", ("Article", "Item"), type="ref", ref="technical.articles", filter=True),
        Field("supplier_id", ("Fournisseur", "Supplier"), type="ref", ref="purchases.suppliers", filter=True),
        Field("client_id", ("Client", "Customer"), type="ref", ref="sales.clients", filter=True),
        Field("quantity_affected", ("Quantité concernée", "Quantity affected"), type="decimal", min=0, max=1_000_000_000),
        Field("cost", ("Coût de la non-qualité", "Cost of poor quality"), type="money", min=0, max=1_000_000_000,
              list=True, help=("Rebuts, reprises, remplacements, avoirs, transports…",
                               "Scrap, rework, replacements, credit notes, shipping…")),
        Field("actions_open", ("Actions à faire", "Open actions"), type="int", computed=True, list=True),
        Field("age_days", ("Ancienneté (jours)", "Age (days)"), type="int", computed=True, list=True,
              help=("Jours écoulés depuis la détection, jusqu'à la clôture.", "Days since detection, until closure.")),
        Field("closed_on", ("Clôturée le", "Closed on"), type="date", readonly=True),
        Field("description", ("Description", "Description"), type="longtext", width="full"),
        Field("root_cause", ("Cause racine", "Root cause"), type="longtext", width="full",
              help=("Obligatoire pour engager les actions.", "Required to start the actions.")),
    ],
    children=[Child("actions", ("Actions", "Actions"), "quality_actions", "nonconformity_id", ACTION_FIELDS)],
    actions=[
        Action("analyse", ("Lancer l'analyse", "Start analysis"), _analyse, when=lambda r: r.get("status") == "open",
               icon="Microscope"),
        Action("plan", ("Engager les actions", "Start actions"), _plan,
               when=lambda r: r.get("status") in ("open", "analysis"), style="primary", icon="ListChecks"),
        Action("close", ("Clôturer", "Close"), _close, when=lambda r: r.get("status") == "action", level=MANAGE,
               style="primary", icon="BadgeCheck",
               confirm=("Clôturer la non-conformité ? Elle ne sera plus modifiable.",
                        "Close the non-conformity? It can no longer be edited.")),
        Action("reopen", ("Rouvrir", "Reopen"), _reopen, when=lambda r: r.get("status") == "closed", level=MANAGE,
               icon="CircleDashed",
               confirm=("Rouvrir la non-conformité ? Ses actions repassent en cours.",
                        "Reopen the non-conformity? Its actions are in progress again.")),
    ],
    compute=_nc_figures, validate=_nc_validate, after_save=_nc_after_save, locked=_nc_locked,
    before_delete=_nc_before_delete,
)


# ═════════════════════════════════════════════════════════════════════════
# Plan d'actions (vue SQL, consultation)
# ═════════════════════════════════════════════════════════════════════════
def _plan_figures(rows: list[dict]) -> None:
    day = today()
    for row in rows:
        row["overdue"] = is_overdue(row.get("done"), row.get("due_date"), day)


ACTION_PLAN = Entity(
    module="quality", name="action_plan", table="quality_action_plan", label=("Action qualité", "Quality action"),
    plural=("Plan d'actions", "Action plan"), title="description", subtitle="nonconformity_code",
    order_by="done, due_date IS NULL, due_date, id DESC", icon="ListChecks", readonly=True,
    description=("Toutes les actions correctives et préventives, à faire d'abord, les échéances les plus proches en tête. "
                 "Elles se modifient dans la fiche de leur non-conformité.",
                 "Every corrective and preventive action, pending ones first, nearest due date at the top. They are "
                 "edited in their non-conformity record."),
    fields=[
        Field("description", ("Action", "Action"), list=True, search=True),
        Field("nonconformity_code", ("Non-conformité", "Non-conformity"), list=True, search=True),
        Field("nonconformity_title", ("Intitulé de la non-conformité", "Non-conformity title"), list=True, search=True),
        Field("nonconformity_id", ("Fiche de la non-conformité", "Non-conformity record"), type="ref",
              ref="quality.nonconformities", filter=True),
        Field("nonconformity_status", ("Statut de la non-conformité", "Non-conformity status"), type="enum",
              choices=STATUSES, filter=True),
        Field("kind", ("Type", "Type"), type="enum", choices=ACTION_KINDS, list=True, filter=True),
        Field("owner_id", ("Responsable", "Owner"), type="ref", ref="hr.employees", list=True, filter=True),
        Field("due_date", ("Échéance", "Due date"), type="date", list=True),
        Field("done", ("Faite", "Done"), type="bool", list=True, filter=True),
        Field("done_on", ("Faite le", "Done on"), type="date"),
        Field("overdue", ("En retard", "Overdue"), type="bool", computed=True, list=True,
              help=("Pas encore faite et échéance dépassée.", "Not done yet and past its due date.")),
    ],
    compute=_plan_figures,
)

ENTITIES = [NONCONFORMITIES, ACTION_PLAN]
