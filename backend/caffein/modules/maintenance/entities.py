# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités de la Maintenance : équipements et interventions préventives ou correctives.

Un équipement a une périodicité de maintenance préventive : sa prochaine maintenance (dernière maintenance préventive
terminée, à défaut date d'achat, plus la périodicité) et son échéance (à jour, bientôt, en retard) sont calculées ici,
jamais stockées. « Planifier la maintenance » crée l'intervention préventive à cette date.

Une intervention est « Planifiée », « En cours », puis « Terminée » (ou « Annulée »). Démarrer une intervention
corrective met l'équipement « En panne » ; terminer une intervention le remet « En service », sauf si une autre
réparation est encore en cours. Un équipement réformé ne change plus de statut et ne reçoit plus d'intervention.

Le poste de charge (Données techniques), le fournisseur (Achats) et le technicien (RH) sont des références
facultatives : sans ces modules, les champs disparaissent et la Maintenance fonctionne quand même.
"""

from __future__ import annotations

from datetime import date, timedelta

from ... import db
from ...core import entities
from ...core.entities import Action, Entity, Field
from ...core.errors import Conflict
from ...core.modules import WRITE
from ...utils import fmt_date, parse_date, today

MIGRATIONS = [
    (1, """
-- workcenter_id : poste de charge des Données techniques ; supplier_id : fournisseur des Achats (pas de clé étrangère
-- vers un autre module)
CREATE TABLE IF NOT EXISTS maintenance_equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    workcenter_id INTEGER,
    location TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    purchase_date TEXT,
    supplier_id INTEGER,
    interval_days INTEGER,
    status TEXT NOT NULL DEFAULT 'operational' CHECK (status IN ('operational', 'degraded', 'down', 'retired')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_maintenance_equipment_code ON maintenance_equipment(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_maintenance_equipment_status ON maintenance_equipment(status);
CREATE INDEX IF NOT EXISTS idx_maintenance_equipment_workcenter ON maintenance_equipment(workcenter_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_equipment_supplier ON maintenance_equipment(supplier_id);

-- Interventions sur un équipement. technician_id : salarié des RH (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS maintenance_interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    equipment_id INTEGER REFERENCES maintenance_equipment(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL DEFAULT 'corrective' CHECK (kind IN ('preventive', 'corrective')),
    title TEXT NOT NULL DEFAULT '',
    planned_date TEXT,
    done_on TEXT,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'in_progress', 'done', 'cancelled')),
    technician_id INTEGER,
    duration_hours REAL,
    cost REAL,
    report TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_maintenance_interventions_code ON maintenance_interventions(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_maintenance_interventions_equipment ON maintenance_interventions(equipment_id, kind, status);
CREATE INDEX IF NOT EXISTS idx_maintenance_interventions_status ON maintenance_interventions(status, planned_date);
CREATE INDEX IF NOT EXISTS idx_maintenance_interventions_done ON maintenance_interventions(done_on);
CREATE INDEX IF NOT EXISTS idx_maintenance_interventions_technician ON maintenance_interventions(technician_id);
"""),
]

EQUIPMENT_STATUSES = (
    ("operational", ("En service", "Operational"), "good"), ("degraded", ("Dégradé", "Degraded"), "warn"),
    ("down", ("En panne", "Down"), "bad"), ("retired", ("Réformé", "Retired"), "outline"),
)
DUE_STATUSES = (
    ("ok", ("À jour", "Up to date"), "good"), ("soon", ("Bientôt", "Due soon"), "warn"),
    ("overdue", ("En retard", "Overdue"), "bad"),
)
KINDS = (("preventive", ("Préventive", "Preventive"), "info"), ("corrective", ("Corrective", "Corrective"), "warn"))
STATUSES = (
    ("planned", ("Planifiée", "Planned")), ("in_progress", ("En cours", "In progress"), "info"),
    ("done", ("Terminée", "Completed"), "good"), ("cancelled", ("Annulée", "Cancelled"), "outline"),
)
OPEN = ("planned", "in_progress")
SOON_DAYS = 7  # « Bientôt » : la prochaine maintenance tombe dans les 7 jours
CHANGED = "L'intervention vient d'être modifiée par ailleurs : rechargez-la."
LOCKS = {
    "done": "Intervention terminée : elle ne se modifie plus.",
    "cancelled": "Intervention annulée : elle ne se modifie plus.",
}


def _today() -> str:
    return today().isoformat()


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


# ═════════════════════════════════════════════════════════════════════════
# Calculs : prochaine maintenance et échéance (une seule règle pour les fiches, les listes et l'accueil)
# ═════════════════════════════════════════════════════════════════════════
def intervention_stats(ids: list) -> dict[int, dict]:
    """Par équipement, en une requête groupée : date de la dernière maintenance préventive terminée, date de la
    maintenance préventive planifiée (ou en cours) et nombre d'interventions ouvertes (planifiées ou en cours)."""
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {r["equipment_id"]: r for r in db.fetch_all(f"""
        SELECT equipment_id,
               MAX(CASE WHEN kind = 'preventive' AND status = 'done' THEN done_on END) AS last_maintenance,
               MIN(CASE WHEN kind = 'preventive' AND status IN ('planned', 'in_progress') THEN planned_date END)
                   AS planned_maintenance,
               COALESCE(SUM(status IN ('planned', 'in_progress')), 0) AS open_interventions
        FROM maintenance_interventions WHERE equipment_id IN ({_marks(ids)}) GROUP BY equipment_id""", tuple(ids))}


def next_maintenance(last: object, purchase: object, interval: object, status: object = None) -> date | None:
    """Dernière maintenance préventive (à défaut, date d'achat) plus la périodicité ; rien sans périodicité, sans date
    de départ, ou pour un équipement réformé."""
    if not interval or status == "retired":
        return None
    start = parse_date(last) or parse_date(purchase)
    if start is None:
        return None
    try:
        return start + timedelta(days=int(interval))
    except (OverflowError, ValueError, TypeError):
        return None


def due_status(due: date | None, day: date | None = None) -> str | None:
    """En retard : date passée ; bientôt : dans les 7 jours (aujourd'hui compris) ; à jour au-delà."""
    if due is None:
        return None
    day = day or today()
    if due < day:
        return "overdue"
    if due <= day + timedelta(days=SOON_DAYS):
        return "soon"
    return "ok"


def _equipment_figures(rows: list[dict]) -> None:
    stats = intervention_stats([r.get("id") for r in rows])
    day = today()
    for row in rows:
        s = stats.get(row.get("id")) or {}
        due = next_maintenance(s.get("last_maintenance"), row.get("purchase_date"), row.get("interval_days"),
                               row.get("status"))
        row["last_maintenance"] = s.get("last_maintenance")
        row["next_maintenance"] = due.isoformat() if due else None
        row["due_status"] = due_status(due, day)
        row["planned_maintenance"] = s.get("planned_maintenance")
        row["open_interventions"] = s.get("open_interventions") or 0


def due_equipment() -> dict:
    """Équipements (non réformés) dont la maintenance préventive tombe dans les 7 jours ou est dépassée."""
    rows = db.fetch_all("SELECT id, purchase_date, interval_days, status FROM maintenance_equipment "
                        "WHERE status != 'retired' AND interval_days > 0")
    stats = intervention_stats([r["id"] for r in rows])
    day = today()
    states = [due_status(next_maintenance((stats.get(r["id"]) or {}).get("last_maintenance"), r["purchase_date"],
                                          r["interval_days"], r["status"]), day) for r in rows]
    return {"value": sum(1 for s in states if s in ("soon", "overdue")), "count": states.count("overdue")}


# ═════════════════════════════════════════════════════════════════════════
# Équipements
# ═════════════════════════════════════════════════════════════════════════
def _open_interventions(equipment_id: int) -> int:
    return db.fetch_one(f"SELECT COUNT(*) AS n FROM maintenance_interventions WHERE equipment_id = ? "
                        f"AND status IN ({_marks(OPEN)})", (equipment_id, *OPEN))["n"]


def _equipment_validate(values: dict, existing: dict | None) -> None:
    bought = parse_date(values.get("purchase_date"))
    if bought and bought > today():
        raise ValueError("Date d'achat : la date ne peut pas être dans le futur.")
    retiring = values.get("status") == "retired" and (existing or {}).get("status") != "retired"
    if retiring and existing is not None and _open_interventions(existing["id"]):
        raise ValueError("Statut : terminez ou annulez d'abord les interventions ouvertes de cet équipement avant de le "
                         "réformer.")


def _can_schedule(row: dict) -> bool:
    return bool(row.get("interval_days")) and row.get("status") != "retired" and not row.get("planned_maintenance")


def _schedule(row: dict, payload: dict, user: dict) -> str:
    """Crée l'intervention préventive à la date de la prochaine maintenance (aujourd'hui si elle est dépassée ou pas
    encore calculable)."""
    due = parse_date(row.get("next_maintenance"))
    day = max(due, today()) if due else today()
    new_id = entities.save_row(INTERVENTIONS, {
        "equipment_id": row["id"], "kind": "preventive", "title": f"Maintenance préventive : {row['name']}",
        "planned_date": day.isoformat(),
    }, WRITE)
    # Double clic, deux personnes : seule la première maintenance planifiée est gardée
    earlier = db.fetch_one(f"SELECT COUNT(*) AS n FROM maintenance_interventions WHERE equipment_id = ? "
                           f"AND kind = 'preventive' AND status IN ({_marks(OPEN)}) AND id < ?", (row["id"], *OPEN, new_id))
    if earlier["n"]:
        db.execute("DELETE FROM maintenance_interventions WHERE id = ?", (new_id,))
        raise Conflict("Une maintenance préventive vient d'être planifiée pour cet équipement : rechargez-le.")
    code = db.fetch_one("SELECT code FROM maintenance_interventions WHERE id = ?", (new_id,))["code"]
    return f"Maintenance préventive {code} planifiée le {fmt_date(day)}."


EQUIPMENT = Entity(
    module="maintenance", name="equipment", table="maintenance_equipment", label=("Équipement", "Equipment"),
    plural=("Équipements", "Equipment"), title="name", subtitle="code", order_by="name COLLATE NOCASE", icon="Gauge",
    board="status",
    description=("Vos machines et leur maintenance préventive : prochaine échéance calculée, interventions planifiées "
                 "en un clic.",
                 "Your machines and their preventive maintenance: next due date calculated, maintenance planned in one "
                 "click."),
    fields=[
        Field("code", ("Code", "Code"), type="code", prefix="EQ", yearly=False, readonly=True, list=True, search=True),
        Field("name", ("Nom", "Name"), required=True, list=True, search=True, maxlength=120),
        Field("workcenter_id", ("Poste de charge", "Work centre"), type="ref", ref="technical.workcenters", list=True,
              filter=True),
        Field("status", ("Statut", "Status"), type="enum", choices=EQUIPMENT_STATUSES, default="operational",
              required=True, list=True, filter=True,
              help=("Mis à jour par les interventions : « En panne » au démarrage d'une réparation, « En service » à la "
                    "fin d'une intervention.",
                    "Updated by maintenance jobs: “Down” when a repair starts, “Operational” when a job is completed.")),
        Field("interval_days", ("Périodicité de maintenance (jours)", "Maintenance interval (days)"), type="int", min=0,
              max=3650, help=("Vide ou 0 : pas de maintenance préventive périodique.",
                              "Empty or 0: no periodic preventive maintenance.")),
        Field("last_maintenance", ("Dernière maintenance préventive", "Last preventive maintenance"), type="date",
              computed=True),
        Field("next_maintenance", ("Prochaine maintenance", "Next maintenance"), type="date", computed=True, list=True,
              help=("Dernière maintenance préventive terminée (à défaut, date d'achat) plus la périodicité.",
                    "Last completed preventive maintenance (or purchase date) plus the interval.")),
        Field("due_status", ("Échéance de maintenance", "Maintenance due"), type="enum", choices=DUE_STATUSES,
              computed=True, list=True, help=("« Bientôt » : dans les 7 jours.", "“Due soon”: within 7 days.")),
        Field("planned_maintenance", ("Maintenance planifiée le", "Maintenance planned on"), type="date", computed=True),
        Field("open_interventions", ("Interventions ouvertes", "Open maintenance jobs"), type="int", computed=True,
              help=("Planifiées ou en cours.", "Planned or in progress.")),
        Field("location", ("Emplacement", "Location"), maxlength=120),
        Field("manufacturer", ("Fabricant", "Manufacturer"), maxlength=120),
        Field("model", ("Modèle", "Model"), maxlength=120),
        Field("serial_number", ("Numéro de série", "Serial number"), search=True, maxlength=80),
        Field("purchase_date", ("Date d'achat", "Purchase date"), type="date"),
        Field("supplier_id", ("Fournisseur", "Supplier"), type="ref", ref="purchases.suppliers", filter=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    actions=[
        Action("schedule", ("Planifier la maintenance", "Schedule maintenance"), _schedule, when=_can_schedule,
               style="primary", icon="CalendarClock"),
    ],
    compute=_equipment_figures, validate=_equipment_validate,
)


# ═════════════════════════════════════════════════════════════════════════
# Interventions
# ═════════════════════════════════════════════════════════════════════════
def _intervention_figures(rows: list[dict]) -> None:
    """En retard : planifiée et sa date prévue est passée (aujourd'hui n'est pas en retard)."""
    day = today()
    for row in rows:
        planned = parse_date(row.get("planned_date"))
        row["overdue"] = bool(row.get("status") == "planned" and planned is not None and planned < day)


def _intervention_validate(values: dict, existing: dict | None) -> None:
    equipment_id = values.get("equipment_id")
    if existing is not None and existing.get("status") == "in_progress":
        if equipment_id != existing.get("equipment_id"):
            raise ValueError("Équipement : l'intervention a commencé, il ne change plus.")
        if values.get("kind") != existing.get("kind"):
            raise ValueError("Type : l'intervention a commencé, il ne change plus.")
    if equipment_id and (existing is None or equipment_id != existing.get("equipment_id")):
        equipment = db.fetch_one("SELECT status FROM maintenance_equipment WHERE id = ?", (equipment_id,))
        if equipment is not None and equipment["status"] == "retired":
            raise ValueError("Équipement : il est réformé, on n'y prévoit plus d'intervention.")


def _intervention_locked(row: dict) -> str | None:
    return LOCKS.get(row.get("status"))


def _intervention_before_delete(row: dict) -> None:
    if row.get("status") not in ("planned", "cancelled"):
        raise Conflict("Seule une intervention planifiée ou annulée peut être supprimée.")


def _equipment_status(equipment_id: int | None) -> str | None:
    row = db.fetch_one("SELECT status FROM maintenance_equipment WHERE id = ?", (equipment_id,)) if equipment_id else None
    return row["status"] if row else None


def _move(row: dict, status: str, origins: tuple[str, ...], equipment: str | None = None, **extra) -> bool:
    """Change le statut de l'intervention, seulement depuis l'un des statuts `origins` (deux actions simultanées ne
    passent pas toutes les deux), et, dans la même transaction, celui de son équipement (`equipment`) s'il n'est pas
    réformé. L'équipement ne revient « En service » que si aucune autre réparation n'y est en cours. Renvoie True si le
    statut de l'équipement a changé."""
    now = db.now_iso()
    values = {"status": status, "updated_at": now, **extra}
    sets = ", ".join(f"{name} = ?" for name in values)
    with db.connect() as conn:
        cur = conn.execute(f"UPDATE maintenance_interventions SET {sets} WHERE id = ? AND status IN ({_marks(origins)})",
                           (*values.values(), row["id"], *origins))
        if cur.rowcount == 0:
            raise Conflict(CHANGED)
        if equipment is None or not row.get("equipment_id"):
            return False
        sql = "UPDATE maintenance_equipment SET status = ?, updated_at = ? WHERE id = ? AND status NOT IN ('retired', ?)"
        params: tuple = (equipment, now, row["equipment_id"], equipment)
        if equipment == "operational":
            sql += (" AND NOT EXISTS (SELECT 1 FROM maintenance_interventions WHERE equipment_id = ? "
                    "AND kind = 'corrective' AND status = 'in_progress' AND id != ?)")
            params += (row["equipment_id"], row["id"])
        return conn.execute(sql, params).rowcount > 0


def _completion_date(payload: dict) -> str:
    """Date de fin : celle du jour, ou celle indiquée (intervention saisie après coup), pas dans le futur."""
    value = payload.get("date")
    if value in (None, ""):
        return _today()
    day = parse_date(value) if isinstance(value, str) else None
    if day is None:
        raise ValueError("Terminée le : date invalide.")
    if day > today():
        raise ValueError("Terminée le : la date ne peut pas être dans le futur.")
    return day.isoformat()


def _start(row: dict, payload: dict, user: dict) -> str:
    down = _move(row, "in_progress", ("planned",), equipment="down" if row.get("kind") == "corrective" else None)
    message = f"Intervention {row['code']} démarrée."
    return f"{message} L'équipement passe « En panne »." if down else message


def _finish(row: dict, payload: dict, user: dict) -> str:
    day = _completion_date(payload)
    back = _move(row, "done", OPEN, equipment="operational", done_on=day)
    message = f"Intervention {row['code']} terminée."
    return f"{message} L'équipement est de nouveau « En service »." if back else message


def _cancel(row: dict, payload: dict, user: dict) -> str:
    _move(row, "cancelled", OPEN)
    message = f"Intervention {row['code']} annulée."
    if row.get("kind") == "corrective" and row.get("status") == "in_progress" \
            and _equipment_status(row.get("equipment_id")) == "down":
        message += " L'équipement reste « En panne » : modifiez son statut dans sa fiche s'il fonctionne."
    return message


INTERVENTIONS = Entity(
    module="maintenance", name="interventions", table="maintenance_interventions", label=("Intervention", "Maintenance job"),
    plural=("Interventions", "Maintenance jobs"), title="title", subtitle="code", order_by="planned_date DESC, id DESC",
    icon="Wrench", board="status",
    description=("Maintenances préventives et réparations : démarrer une réparation met l'équipement en panne, terminer "
                 "une intervention le remet en service.",
                 "Preventive maintenance and repairs: starting a repair marks the equipment as down, completing a job "
                 "puts it back into service."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="INT", readonly=True, list=True, search=True),
        Field("equipment_id", ("Équipement", "Equipment"), type="ref", ref="maintenance.equipment", required=True,
              list=True, filter=True),
        Field("kind", ("Type", "Type"), type="enum", choices=KINDS, default="corrective", required=True, list=True,
              filter=True),
        Field("title", ("Intitulé", "Title"), required=True, list=True, search=True, maxlength=160),
        Field("planned_date", ("Date prévue", "Planned date"), type="date", default=_today, required=True, list=True),
        Field("done_on", ("Terminée le", "Completed on"), type="date", readonly=True, list=True),
        Field("status", ("Statut", "Status"), type="enum", choices=STATUSES, default="planned", readonly=True, list=True,
              filter=True),
        Field("overdue", ("En retard", "Overdue"), type="bool", computed=True, list=True,
              help=("Planifiée et date prévue dépassée.", "Planned and past its planned date.")),
        Field("technician_id", ("Technicien", "Technician"), type="ref", ref="hr.employees", filter=True),
        Field("duration_hours", ("Durée (heures)", "Duration (hours)"), type="decimal", min=0, max=10_000),
        Field("cost", ("Coût", "Cost"), type="money", min=0, max=1_000_000_000, list=True,
              help=("Pièces, main-d'œuvre et déplacement, HT.", "Parts, labour and travel, excl. VAT.")),
        Field("report", ("Compte rendu", "Report"), type="longtext", width="full"),
    ],
    actions=[
        Action("start", ("Démarrer", "Start"), _start, when=lambda r: r.get("status") == "planned", icon="Play"),
        Action("done", ("Terminer", "Complete"), _finish, when=lambda r: r.get("status") in OPEN, style="primary",
               icon="CircleCheck"),
        Action("cancel", ("Annuler", "Cancel"), _cancel, when=lambda r: r.get("status") in OPEN, style="danger",
               icon="Ban", confirm=("Annuler cette intervention ?", "Cancel this maintenance job?")),
    ],
    compute=_intervention_figures, validate=_intervention_validate, locked=_intervention_locked,
    before_delete=_intervention_before_delete,
)

ENTITIES = [INTERVENTIONS, EQUIPMENT]
