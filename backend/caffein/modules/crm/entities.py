# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités du CRM : prospects, opportunités et actions commerciales.

Un prospect (« Nouveau », « Contacté », « Qualifié ») devient client des Ventes par la conversion, ou se perd.
Une opportunité avance d'étape en étape (découverte, qualification, proposition, négociation) avec une probabilité
de signature, puis se gagne ou se perd ; son montant pondéré (montant HT × probabilité), calculé ici, nourrit le
pipeline de l'accueil. Une action commerciale (appel, email, rendez-vous, tâche) a une échéance et passe en retard
une fois celle-ci dépassée.

Le client (`sales.clients`) et le devis (table `invoices`) appartiennent aux Ventes : le CRM ne les lit que si les
Ventes sont actives, et ne les crée que pour un utilisateur qui peut y écrire.
"""

from __future__ import annotations

from ... import db, services
from ...core import modules as registry
from ...core.entities import Action, Entity, Field
from ...core.errors import Conflict, Forbidden
from ...core.modules import WRITE
from ...core.permissions import level_for
from ...utils import cents, parse_date, today

MIGRATIONS = [
    (1, """
-- Prospects. client_id : client des Ventes créé ou retrouvé par la conversion (pas de clé étrangère vers un
-- autre module)
CREATE TABLE IF NOT EXISTS crm_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'other'
        CHECK (source IN ('website', 'referral', 'event', 'social', 'cold', 'other')),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'qualified', 'converted', 'lost')),
    client_id INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_leads_status ON crm_leads(status);
CREATE INDEX IF NOT EXISTS idx_crm_leads_client ON crm_leads(client_id);

-- Opportunités. client_id : client des Ventes ; quote_id : devis créé dans les Ventes (table invoices).
-- La probabilité est toujours remplie (celle de l'étape par défaut) ; le montant pondéré se calcule.
CREATE TABLE IF NOT EXISTS crm_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    lead_id INTEGER REFERENCES crm_leads(id) ON DELETE RESTRICT,
    client_id INTEGER,
    amount REAL,
    stage TEXT NOT NULL DEFAULT 'prospecting'
        CHECK (stage IN ('prospecting', 'qualification', 'proposal', 'negotiation', 'won', 'lost')),
    probability REAL,
    expected_close TEXT,
    lost_reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    quote_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_opportunities_code ON crm_opportunities(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_crm_opportunities_stage ON crm_opportunities(stage);
CREATE INDEX IF NOT EXISTS idx_crm_opportunities_lead ON crm_opportunities(lead_id);
CREATE INDEX IF NOT EXISTS idx_crm_opportunities_client ON crm_opportunities(client_id);

-- Actions commerciales : appels, emails, rendez-vous et tâches, avec leur échéance
CREATE TABLE IF NOT EXISTS crm_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'call' CHECK (kind IN ('call', 'email', 'meeting', 'task')),
    subject TEXT NOT NULL DEFAULT '',
    due_date TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    done_on TEXT,
    lead_id INTEGER REFERENCES crm_leads(id) ON DELETE RESTRICT,
    opportunity_id INTEGER REFERENCES crm_opportunities(id) ON DELETE RESTRICT,
    client_id INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_activities_due ON crm_activities(done, due_date);
CREATE INDEX IF NOT EXISTS idx_crm_activities_lead ON crm_activities(lead_id);
CREATE INDEX IF NOT EXISTS idx_crm_activities_opportunity ON crm_activities(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_crm_activities_client ON crm_activities(client_id);
"""),
]

LEAD_STATUSES = (
    ("new", ("Nouveau", "New"), "info"), ("contacted", ("Contacté", "Contacted")),
    ("qualified", ("Qualifié", "Qualified"), "accent"), ("converted", ("Converti", "Converted"), "good"),
    ("lost", ("Perdu", "Lost"), "outline"),
)
OPEN_LEAD_STATUSES = ("new", "contacted", "qualified")
SOURCES = (
    ("website", ("Site web", "Website")), ("referral", ("Recommandation", "Referral")),
    ("event", ("Salon ou événement", "Trade show or event")), ("social", ("Réseaux sociaux", "Social media")),
    ("cold", ("Prospection directe", "Cold outreach")), ("other", ("Autre", "Other")),
)
STAGES = (
    ("prospecting", ("Découverte", "Prospecting")), ("qualification", ("Qualification", "Qualification")),
    ("proposal", ("Proposition", "Proposal"), "info"), ("negotiation", ("Négociation", "Negotiation"), "accent"),
    ("won", ("Gagnée", "Won"), "good"), ("lost", ("Perdue", "Lost"), "outline"),
)
OPEN_STAGES = ("prospecting", "qualification", "proposal", "negotiation")
CLOSED_STAGES = ("won", "lost")
STAGE_ORDER = {choice[0]: position for position, choice in enumerate(STAGES)}
# Probabilité de signature habituelle de chaque étape (%), reprise quand l'utilisateur n'en donne pas
STAGE_PROBABILITY = {"prospecting": 10, "qualification": 25, "proposal": 50, "negotiation": 75, "won": 100, "lost": 0}
ACTIVITY_KINDS = (
    ("call", ("Appel", "Call")), ("email", ("Email", "Email")), ("meeting", ("Rendez-vous", "Meeting"), "accent"),
    ("task", ("Tâche", "Task")),
)
CHANGED = "La fiche vient d'être modifiée par ailleurs : rechargez-la."


def _today() -> str:
    return today().isoformat()


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


def _move(table: str, row_id: int, column: str, value: str, origins: tuple[str, ...], **extra) -> None:
    """Change un statut (ou une étape), seulement depuis l'une des valeurs `origins` : deux actions simultanées
    sur la même fiche (double clic, deux personnes) ne passent pas toutes les deux."""
    values = {column: value, "updated_at": db.now_iso(), **extra}
    sets = ", ".join(f"{name} = ?" for name in values)
    with db.connect() as conn:
        cur = conn.execute(f"UPDATE {table} SET {sets} WHERE id = ? AND {column} IN ({_marks(origins)})",
                           (*values.values(), row_id, *origins))
        if cur.rowcount == 0:
            raise Conflict(CHANGED)


def _check_sales(user: dict, disabled: str, forbidden: str) -> None:
    """Le CRM crée un client ou un devis dans les Ventes : elles doivent être actives, et l'utilisateur doit pouvoir
    y écrire. Un appel interne (données de démonstration, script : sans utilisateur) n'a pas de droits à vérifier."""
    if not registry.is_enabled("sales"):
        raise ValueError(disabled)
    if user.get("id") is not None and level_for(user, "sales") < WRITE:
        raise Forbidden(forbidden)


def _client(client_id: int | None) -> int | None:
    """L'identifiant, si ce client des Ventes existe encore (les Ventes doivent être actives)."""
    if client_id and db.fetch_one("SELECT 1 FROM clients WHERE id = ?", (client_id,)):
        return client_id
    return None


def _lead_client(lead_id: int | None) -> int | None:
    """Client des Ventes d'un prospect converti, s'il existe encore (les Ventes doivent être actives)."""
    if not lead_id:
        return None
    row = db.fetch_one("SELECT client_id FROM crm_leads WHERE id = ?", (lead_id,))
    return _client(row["client_id"]) if row else None


def _current(values: dict, existing: dict | None, name: str):
    """Valeur d'un champ après l'enregistrement : celle envoyée, sinon celle de la fiche."""
    return values[name] if name in values else (existing or {}).get(name)


# ═════════════════════════════════════════════════════════════════════════
# Prospects
# ═════════════════════════════════════════════════════════════════════════
LEAD_LOCKS = {
    "converted": "Prospect converti en client : il ne se modifie plus. Ses coordonnées sont désormais dans la fiche du "
                 "client (Ventes).",
    "lost": "Prospect perdu : il ne se modifie plus.",
}


def _lead_locked(row: dict) -> str | None:
    return LEAD_LOCKS.get(row.get("status"))


def _lead_before_delete(row: dict) -> None:
    """Un prospect se supprime quel que soit son statut : ses coordonnées sont des données personnelles (droit à
    l'effacement). Le moteur refuse toujours la suppression d'un prospect désigné par une opportunité ou une action
    commerciale."""
    return None


def _client_named(name: str) -> dict | None:
    """Client des Ventes qui porte ce nom, sans tenir compte des majuscules ni des espaces autour (le plus ancien)."""
    wanted = name.strip().casefold()
    return next((c for c in db.fetch_all("SELECT id, name FROM clients ORDER BY id")
                 if (c["name"] or "").strip().casefold() == wanted), None)


def _contacted(row: dict, payload: dict, user: dict) -> str:
    _move("crm_leads", row["id"], "status", "contacted", ("new",))
    return f"{row['company']} : prospect contacté."


def _qualify(row: dict, payload: dict, user: dict) -> str:
    _move("crm_leads", row["id"], "status", "qualified", ("new", "contacted"))
    return f"{row['company']} : prospect qualifié."


def _convert(row: dict, payload: dict, user: dict) -> str:
    """Le prospect devient client des Ventes : le client du même nom s'il existe, sinon un nouveau client avec les
    coordonnées du prospect. Ses opportunités et ses actions commerciales sans client sont rattachées à ce client."""
    _check_sales(user, "Activez le module Ventes pour convertir un prospect en client.",
                 "Droits insuffisants : la conversion crée un client dans les Ventes, ce qui demande le droit "
                 "d'écriture sur ce module.")
    client = _client_named(row["company"])
    created = None
    if client is None:
        created = client = services.create_client({
            "name": row["company"], "contact_name": row.get("contact_name") or "", "email": row.get("email") or "",
            "phone": row.get("phone") or "", "city": row.get("city") or "", "notes": row.get("notes") or "",
        })
    now = db.now_iso()
    try:
        with db.connect() as conn:  # le prospect et ses fiches liées dans la même transaction
            cur = conn.execute(
                f"UPDATE crm_leads SET status = 'converted', client_id = ?, updated_at = ? "
                f"WHERE id = ? AND status IN ({_marks(OPEN_LEAD_STATUSES)})",
                (client["id"], now, row["id"], *OPEN_LEAD_STATUSES))
            if cur.rowcount == 0:
                raise Conflict(CHANGED)
            for table in ("crm_opportunities", "crm_activities"):
                conn.execute(f"UPDATE {table} SET client_id = ?, updated_at = ? WHERE lead_id = ? AND client_id IS NULL",
                             (client["id"], now, row["id"]))
    except Exception:
        if created is not None:  # conversion faite ailleurs entre-temps, ou échec : pas de client en double
            services.delete_client(created["id"])
        raise
    return f"Client créé : {client['name']}" if created else f"Rattaché au client existant : {client['name']}"


def _lose_lead(row: dict, payload: dict, user: dict) -> str:
    _move("crm_leads", row["id"], "status", "lost", OPEN_LEAD_STATUSES)
    return f"{row['company']} : prospect perdu."


LEADS = Entity(
    module="crm", name="leads", table="crm_leads", label=("Prospect", "Lead"), plural=("Prospects", "Leads"),
    title="company", subtitle="city", order_by="id DESC", icon="Contact", board="status",
    description=("Les entreprises à démarcher : contact, origine et suivi jusqu'à leur conversion en clients des Ventes.",
                 "Companies to win over: contact, source and follow-up until they become customers in Sales."),
    fields=[
        Field("company", ("Entreprise", "Company"), required=True, list=True, search=True, maxlength=120),
        Field("contact_name", ("Contact", "Contact"), list=True, search=True, maxlength=120),
        Field("email", ("Email", "Email"), type="email"),
        Field("phone", ("Téléphone", "Phone"), type="phone"),
        Field("city", ("Ville", "City"), list=True, maxlength=120),
        Field("source", ("Origine", "Source"), type="enum", choices=SOURCES, default="other", required=True, list=True,
              filter=True),
        Field("status", ("Statut", "Status"), type="enum", choices=LEAD_STATUSES, default="new", readonly=True, list=True,
              filter=True),
        Field("client_id", ("Client", "Customer"), type="ref", ref="sales.clients", readonly=True,
              help=("Rempli par la conversion du prospect en client.", "Filled in when the lead is converted into a customer.")),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    actions=[
        Action("contacted", ("Marquer comme contacté", "Mark as contacted"), _contacted,
               when=lambda r: r.get("status") == "new", icon="PhoneCall"),
        Action("qualify", ("Qualifier", "Qualify"), _qualify, when=lambda r: r.get("status") in ("new", "contacted"),
               icon="BadgeCheck"),
        Action("convert", ("Convertir en client", "Convert to customer"), _convert,
               when=lambda r: r.get("status") in OPEN_LEAD_STATUSES, style="primary", icon="UserCheck",
               confirm=("Convertir ce prospect en client ? Un client du même nom dans les Ventes est repris ; sinon, "
                        "il est créé.",
                        "Convert this lead into a customer? A customer with the same name in Sales is reused; "
                        "otherwise, one is created.")),
        Action("lost", ("Marquer comme perdu", "Mark as lost"), _lose_lead,
               when=lambda r: r.get("status") in OPEN_LEAD_STATUSES, style="danger", icon="X",
               confirm=("Marquer ce prospect comme perdu ? Il ne sera plus modifiable.",
                        "Mark this lead as lost? It can no longer be edited.")),
    ],
    locked=_lead_locked, before_delete=_lead_before_delete,
)


# ═════════════════════════════════════════════════════════════════════════
# Opportunités
# ═════════════════════════════════════════════════════════════════════════
def probability(stage: str | None, value: float | None, stored: dict | None = None) -> float:
    """Probabilité de signature retenue (%) : celle saisie ; vide, ou étape changée sans nouvelle probabilité, celle
    habituelle de l'étape. `stored` : l'opportunité enregistrée (étape et probabilité), None à la création. Une seule
    règle pour l'enregistrement (prepare), les montants pondérés et l'aperçu de saisie : le formulaire renvoie
    l'ancienne probabilité quand seule l'étape change."""
    stage = stage or "prospecting"
    stage_changed = stored is not None and stage != stored.get("stage") and value == stored.get("probability")
    if value is None or stage_changed:
        return float(STAGE_PROBABILITY.get(stage, 0))
    return float(value)


def weighted_amount(amount: float | None, percent: float) -> float | None:
    """Montant pondéré : montant HT × probabilité, au centime (vide tant que le montant n'est pas connu)."""
    return None if amount is None else cents(float(amount) * percent / 100)


def open_pipeline() -> dict:
    """Pipeline : somme des montants pondérés des opportunités en cours (ni gagnées ni perdues), et leur nombre."""
    rows = db.fetch_all(f"SELECT amount, probability, stage FROM crm_opportunities WHERE stage IN ({_marks(OPEN_STAGES)})",
                        OPEN_STAGES)
    total = sum(weighted_amount(r["amount"], probability(r["stage"], r["probability"])) or 0 for r in rows)
    return {"value": cents(total), "count": len(rows)}


def _opportunity_figures(rows: list[dict]) -> None:
    """Montant pondéré, et numéro du devis créé dans les Ventes : « brouillon » tant qu'il n'est pas émis, vide s'il
    a été supprimé ou si les Ventes sont désactivées. Une requête groupée pour toute la liste. Pendant la saisie
    (aperçu), l'étape et la probabilité enregistrées décident, comme à l'enregistrement, de la probabilité retenue."""
    ids = sorted({r["id"] for r in rows if r.get("id")})
    stored = {}
    if ids:
        stored = {r["id"]: r for r in db.fetch_all(
            f"SELECT id, stage, probability FROM crm_opportunities WHERE id IN ({_marks(ids)})", tuple(ids))}
    quotes = sorted({r["quote_id"] for r in rows if r.get("quote_id")})
    numbers: dict[int, str] = {}
    if quotes and registry.is_enabled("sales"):
        numbers = {q["id"]: q["number"] or "brouillon" for q in db.fetch_all(
            f"SELECT id, number FROM invoices WHERE kind = 'quote' AND id IN ({_marks(quotes)})", tuple(quotes))}
    for row in rows:
        percent = probability(row.get("stage"), row.get("probability"), stored.get(row.get("id")))
        row["weighted_amount"] = weighted_amount(row.get("amount"), percent)
        row["quote_number"] = numbers.get(row.get("quote_id"), "")


def _opportunity_prepare(values: dict, existing: dict | None) -> None:
    """Probabilité retenue (voir `probability`). Opportunité d'un prospect converti, sans client : le client du
    prospect."""
    values["probability"] = probability(_current(values, existing, "stage"), _current(values, existing, "probability"),
                                        existing)
    if registry.is_enabled("sales") and not _current(values, existing, "client_id"):
        client = _lead_client(_current(values, existing, "lead_id"))
        if client:
            values["client_id"] = client


def _opportunity_validate(values: dict, existing: dict | None) -> None:
    stage = values.get("stage")
    if stage in CLOSED_STAGES and (existing is None or existing.get("stage") != stage):
        raise ValueError("Étape : utilisez « Marquer comme gagnée » ou « Marquer comme perdue » pour clore l'opportunité.")
    client = values.get("client_id")
    if client is None and existing is not None and "client_id" not in existing:
        # Ventes désactivées : le champ Client est masqué, mais le client enregistré compte toujours
        stored = db.fetch_one("SELECT client_id FROM crm_opportunities WHERE id = ?", (existing["id"],))
        client = stored["client_id"] if stored else None
    if not values.get("lead_id") and not client:
        if registry.is_enabled("sales"):
            raise ValueError("Prospect : choisissez un prospect ou un client.")
        raise ValueError("Prospect : choisissez un prospect (pour choisir un client, activez le module Ventes).")


OPPORTUNITY_LOCKS = {
    "won": "Opportunité gagnée : elle ne se modifie plus.",
    "lost": "Opportunité perdue : elle ne se modifie plus.",
}


def _opportunity_locked(row: dict) -> str | None:
    return OPPORTUNITY_LOCKS.get(row.get("stage"))


def _opportunity_before_delete(row: dict) -> None:
    """Une opportunité gagnée reste dans l'historique ; en cours ou perdue, elle se supprime (si aucune action
    commerciale ne la désigne)."""
    if row.get("stage") == "won":
        raise Conflict("Une opportunité gagnée ne se supprime pas : elle fait partie de l'historique des ventes.")


def _win(row: dict, payload: dict, user: dict) -> str:
    _move("crm_opportunities", row["id"], "stage", "won", OPEN_STAGES, probability=STAGE_PROBABILITY["won"])
    return f"Opportunité {row['code']} gagnée."


def _lose_opportunity(row: dict, payload: dict, user: dict) -> str:
    _move("crm_opportunities", row["id"], "stage", "lost", OPEN_STAGES, probability=STAGE_PROBABILITY["lost"])
    return f"Opportunité {row['code']} perdue."


def _create_quote(row: dict, payload: dict, user: dict) -> str:
    """Devis brouillon dans les Ventes, d'une ligne (l'intitulé et le montant HT de l'opportunité) ; une opportunité
    pas encore à l'étape « Proposition » y passe."""
    _check_sales(user, "Activez le module Ventes pour créer un devis.",
                 "Droits insuffisants : créer un devis demande le droit d'écriture sur les Ventes.")
    client = _client(row.get("client_id"))  # un client supprimé entre-temps ne compte pas
    if not client:
        raise ValueError("Client : choisissez un client avant de créer le devis.")
    quote = services.create_invoice({
        "kind": "quote", "client_id": client, "title": row["title"],
        "items": [{"description": row["title"], "quantity": 1, "unit_price": row.get("amount") or 0}],
    })
    values = {"quote_id": quote["id"], "updated_at": db.now_iso()}
    if STAGE_ORDER[row["stage"]] < STAGE_ORDER["proposal"]:
        values.update(stage="proposal", probability=STAGE_PROBABILITY["proposal"])
    sets = ", ".join(f"{name} = ?" for name in values)
    try:
        with db.connect() as conn:  # seulement si personne n'a changé l'étape ni créé de devis entre-temps (double clic)
            updated = conn.execute(f"UPDATE crm_opportunities SET {sets} WHERE id = ? AND stage = ? AND quote_id IS ?",
                                   (*values.values(), row["id"], row["stage"], row.get("quote_id"))).rowcount
        if not updated:
            raise Conflict(CHANGED)
    except Exception:
        services.delete_invoice(quote["id"])  # pas de devis orphelin dans les Ventes
        raise
    return "Devis brouillon créé dans Ventes → Factures et devis."


OPPORTUNITIES = Entity(
    module="crm", name="opportunities", table="crm_opportunities", label=("Opportunité", "Opportunity"),
    plural=("Opportunités", "Opportunities"), title="title", subtitle="code", order_by="id DESC", icon="Target",
    board="stage",
    description=("Les affaires en cours, de la découverte à la signature : montant, probabilité, montant pondéré et devis "
                 "en un clic.",
                 "Deals in progress, from prospecting to signature: amount, probability, weighted amount and "
                 "one-click quote."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="OPP", readonly=True, list=True, search=True),
        Field("title", ("Intitulé", "Title"), required=True, list=True, search=True, maxlength=120),
        Field("lead_id", ("Prospect", "Lead"), type="ref", ref="crm.leads", filter=True),
        Field("client_id", ("Client", "Customer"), type="ref", ref="sales.clients", list=True, filter=True),
        Field("amount", ("Montant HT", "Amount excl. VAT"), type="money", min=0, max=1_000_000_000, list=True),
        Field("stage", ("Étape", "Stage"), type="enum", choices=STAGES, default="prospecting", required=True, list=True,
              filter=True, action_choices=CLOSED_STAGES, help=("Gagnée ou perdue : utilisez les boutons de la fiche.", "Won or lost: use the record's buttons.")),
        Field("probability", ("Probabilité", "Probability"), type="percent", min=0, max=100,
              help=("Vide, ou étape changée sans nouvelle probabilité : celle de l'étape (découverte 10 %, "
                    "qualification 25 %, proposition 50 %, négociation 75 %).",
                    "Empty, or stage changed without a new probability: the stage's usual one (prospecting 10%, "
                    "qualification 25%, proposal 50%, negotiation 75%).")),
        Field("weighted_amount", ("Montant pondéré", "Weighted amount"), type="money", computed=True, list=True,
              help=("Montant HT × probabilité.", "Amount excl. VAT × probability.")),
        Field("expected_close", ("Clôture prévue", "Expected close date"), type="date", list=True),
        Field("quote_number", ("Devis", "Quote"), computed=True,
              help=("Créé par « Créer le devis » ; « brouillon » tant qu'il n'est pas émis dans les Ventes.",
                    "Created with “Create quote”; “brouillon” (draft) until it is issued in Sales.")),
        Field("lost_reason", ("Motif de perte", "Reason for loss"), maxlength=200,
              help=("À renseigner avant de marquer l'opportunité comme perdue.", "Fill in before marking the deal as lost.")),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
        Field("quote_id", ("Devis", "Quote"), type="int", readonly=True, hidden=True),
    ],
    actions=[
        Action("create_quote", ("Créer le devis", "Create quote"), _create_quote,
               when=lambda r: bool(r.get("client_id")) and not r.get("quote_number") and r.get("stage") != "lost",
               icon="FileSignature"),
        Action("won", ("Marquer comme gagnée", "Mark as won"), _win, when=lambda r: r.get("stage") in OPEN_STAGES,
               style="primary", icon="CheckCircle2",
               confirm=("Marquer l'opportunité comme gagnée ? Elle ne sera plus modifiable.",
                        "Mark the deal as won? It can no longer be edited.")),
        Action("lost", ("Marquer comme perdue", "Mark as lost"), _lose_opportunity,
               when=lambda r: r.get("stage") in OPEN_STAGES, style="danger", icon="Ban",
               confirm=("Marquer l'opportunité comme perdue ? Elle ne sera plus modifiable.",
                        "Mark the deal as lost? It can no longer be edited.")),
    ],
    compute=_opportunity_figures, prepare=_opportunity_prepare, validate=_opportunity_validate,
    locked=_opportunity_locked, before_delete=_opportunity_before_delete,
)


# ═════════════════════════════════════════════════════════════════════════
# Actions commerciales
# ═════════════════════════════════════════════════════════════════════════
def _activity_figures(rows: list[dict]) -> None:
    """En retard : pas encore faite, et son échéance est passée (aujourd'hui n'est pas en retard)."""
    day = today()
    for row in rows:
        due = parse_date(row.get("due_date"))
        row["overdue"] = bool(not row.get("done") and due is not None and due < day)


def _activity_prepare(values: dict, existing: dict | None) -> None:
    """Faite : date du jour quand la case est cochée, effacée quand elle est décochée. Opportunité choisie : son
    prospect et son client, s'ils sont vides ; prospect converti : son client."""
    before = existing or {}
    if "done" in values:
        if values["done"] and not before.get("done"):
            values["done_on"] = _today()
        elif not values["done"]:
            values["done_on"] = None
    opportunity = values.get("opportunity_id")
    source = None
    if opportunity and opportunity != before.get("opportunity_id"):
        source = db.fetch_one("SELECT lead_id, client_id FROM crm_opportunities WHERE id = ?", (opportunity,))
    if source and source["lead_id"] and not _current(values, existing, "lead_id"):
        values["lead_id"] = source["lead_id"]
    if registry.is_enabled("sales") and not _current(values, existing, "client_id"):
        client = _client(source["client_id"]) if source else None
        client = client or _lead_client(_current(values, existing, "lead_id"))
        if client:
            values["client_id"] = client


def _done(row: dict, payload: dict, user: dict) -> str:
    with db.connect() as conn:
        cur = conn.execute("UPDATE crm_activities SET done = 1, done_on = ?, updated_at = ? WHERE id = ? AND done = 0",
                           (_today(), db.now_iso(), row["id"]))
        if cur.rowcount == 0:
            raise Conflict(CHANGED)
    return f"Action « {row['subject']} » marquée comme faite."


ACTIVITIES = Entity(
    module="crm", name="activities", table="crm_activities", label=("Action commerciale", "Sales activity"),
    plural=("Actions commerciales", "Sales activities"), title="subject", order_by="done, due_date, id DESC",
    icon="ListTodo",
    description=("Appels, emails, rendez-vous et tâches, avec leur échéance : les actions à faire d'abord, les plus "
                 "anciennes en tête.",
                 "Calls, emails, meetings and tasks with their due date: pending ones first, oldest at the top."),
    fields=[
        Field("kind", ("Type", "Type"), type="enum", choices=ACTIVITY_KINDS, default="call", required=True, list=True,
              filter=True),
        Field("subject", ("Objet", "Subject"), required=True, list=True, search=True, maxlength=160),
        Field("due_date", ("Échéance", "Due date"), type="date", default=_today, list=True),
        Field("done", ("Faite", "Done"), type="bool", default=False, list=True, filter=True),
        Field("done_on", ("Faite le", "Done on"), type="date", readonly=True),
        Field("overdue", ("En retard", "Overdue"), type="bool", computed=True, list=True),
        Field("lead_id", ("Prospect", "Lead"), type="ref", ref="crm.leads", list=True),
        Field("opportunity_id", ("Opportunité", "Opportunity"), type="ref", ref="crm.opportunities",
              help=("Le prospect et le client de l'opportunité sont repris s'ils sont vides.",
                    "The deal's lead and customer are used when empty.")),
        Field("client_id", ("Client", "Customer"), type="ref", ref="sales.clients"),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    actions=[
        Action("done", ("Marquer comme faite", "Mark as done"), _done, when=lambda r: not r.get("done"), style="primary",
               icon="CircleCheck"),
    ],
    compute=_activity_figures, prepare=_activity_prepare,
)

ENTITIES = [OPPORTUNITIES, LEADS, ACTIVITIES]
