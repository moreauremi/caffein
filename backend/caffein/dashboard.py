# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tableau de bord à la demande (« Mes vues »).

L'utilisateur écrit ce qu'il veut voir ; l'IA (ou, hors-ligne, une analyse par mots-clés)
choisit des briques dans un catalogue fermé et renvoie une *description* de la vue :

    {"title": "…", "widgets": [{"source": "revenue_by_month", "visual": "bar", "title": "…", "params": {…}}]}

L'IA ne produit ni code, ni SQL, ni HTML, et ne voit jamais les données de l'entreprise :
seulement la demande, le catalogue et la vue en cours. Toute description passe par
`validate_spec()` ; les données sont ensuite calculées ici, par des fonctions fixes qui
s'appuient sur la logique métier de `services.py`. Voir docs/tableau-de-bord-ia.md.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from . import config, db, fiscal, services
from .utils import add_months, month_end, parse_date, today

MAX_WIDGETS = 8
MAX_PROMPT = 500
MAX_TITLE = 80
MAX_VIEWS = 30

PERIODS = ("month", "quarter", "year", "last_6_months", "last_12_months")
METRICS = ("to_collect", "overdue_total", "paid_month", "revenue_year", "quotes_pending", "vat_balance", "time_saved")
VISUALS = ("stat", "bar", "table", "list")

# Catalogue : source → visuels possibles, visuel et titre par défaut, paramètres acceptés.
# L'IA reçoit `description` ; l'interface traduit le titre par défaut si l'IA n'en donne pas.
CATALOG: dict[str, dict] = {
    "kpi": {
        "visuals": ("stat",), "default_visual": "stat", "params": ("metric",),
        "description": "un chiffre clé (metric) : to_collect (à encaisser), overdue_total (factures en retard), "
                       "paid_month (encaissé ce mois), revenue_year (CA encaissé de l'année), quotes_pending (devis en attente), "
                       "vat_balance (solde de TVA du mois), time_saved (temps gagné grâce à Caffein)",
    },
    "revenue_by_month": {
        "visuals": ("bar", "table"), "default_visual": "bar", "params": ("period",),
        "description": "chiffre d'affaires HT facturé et encaissé, mois par mois (period : last_6_months, last_12_months ou year)",
    },
    "revenue_by_client": {
        "visuals": ("bar", "table"), "default_visual": "bar", "params": ("period", "limit"),
        "description": "chiffre d'affaires HT facturé par client, du plus important au plus petit (period, limit)",
    },
    "unpaid_invoices": {
        "visuals": ("table",), "default_visual": "table", "params": ("only_overdue", "limit"),
        "description": "factures à encaisser, les plus en retard d'abord (only_overdue : seulement celles en retard)",
    },
    "expenses_by_category": {
        "visuals": ("bar", "table"), "default_visual": "bar", "params": ("period",),
        "description": "dépenses HT par catégorie, d'après les justificatifs classés (period)",
    },
    "vat_by_month": {
        "visuals": ("bar", "table"), "default_visual": "bar", "params": ("period",),
        "description": "TVA collectée et déductible, mois par mois (period : last_6_months, last_12_months ou year)",
    },
    "pending_quotes": {
        "visuals": ("table",), "default_visual": "table", "params": ("limit",),
        "description": "devis envoyés en attente de réponse",
    },
    "deadlines": {
        "visuals": ("list",), "default_visual": "list", "params": (),
        "description": "prochaines échéances TVA et URSSAF, avec le montant estimé",
    },
}
SOURCES = tuple(CATALOG)


# ═════════════════════════════════════════════════════════════════════════
# Validation d'une description (quelle qu'en soit l'origine : IA, analyse locale, navigateur)
# ═════════════════════════════════════════════════════════════════════════
def _clean_text(value: object, limit: int = MAX_TITLE) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _clean_params(source: str, raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    allowed = CATALOG[source]["params"]
    params: dict = {}
    if "metric" in allowed:
        params["metric"] = raw.get("metric") if raw.get("metric") in METRICS else "to_collect"
    if "period" in allowed:
        default = "year" if source in ("revenue_by_client", "expenses_by_category") else "last_12_months"
        params["period"] = raw.get("period") if raw.get("period") in PERIODS else default
    if "limit" in allowed:
        try:
            limit = int(raw.get("limit") or 0)
        except (TypeError, ValueError):
            limit = 0
        params["limit"] = min(max(limit, 1), 20) if limit else 8
    if "only_overdue" in allowed:
        params["only_overdue"] = raw.get("only_overdue") is True
    return params


def validate_spec(spec: object) -> dict:
    """Description reçue → description sûre. Les cartes inconnues ou mal formées sont écartées,
    jamais devinées ; les doublons exacts sont fusionnés ; 8 cartes au plus."""
    spec = spec if isinstance(spec, dict) else {}
    widgets, seen = [], set()
    raw_widgets = spec.get("widgets") if isinstance(spec.get("widgets"), list) else []
    for raw in raw_widgets:
        if not isinstance(raw, dict) or raw.get("source") not in CATALOG:
            continue
        source = raw["source"]
        entry = CATALOG[source]
        visual = raw.get("visual") if raw.get("visual") in entry["visuals"] else entry["default_visual"]
        params = _clean_params(source, raw.get("params"))
        key = (source, visual, tuple(sorted(params.items())))
        if key in seen:
            continue
        seen.add(key)
        widgets.append({"source": source, "visual": visual, "title": _clean_text(raw.get("title")), "params": params})
        if len(widgets) == MAX_WIDGETS:
            break
    return {"title": _clean_text(spec.get("title")), "widgets": widgets}


# ═════════════════════════════════════════════════════════════════════════
# Calcul des données (lecture seule)
# ═════════════════════════════════════════════════════════════════════════
def _range(period: str, ref: date) -> tuple[date, date]:
    if period == "month":
        p = fiscal.tva_period("month", ref)
        return p.start, p.end
    if period == "quarter":
        p = fiscal.tva_period("quarter", ref)
        return p.start, p.end
    if period == "year":
        return date(ref.year, 1, 1), date(ref.year, 12, 31)
    months = 6 if period == "last_6_months" else 12
    return add_months(ref.replace(day=1), -(months - 1)), month_end(ref)


def _months(period: str, ref: date) -> list[date]:
    start, end = _range(period, ref)
    months, cursor = [], start.replace(day=1)
    while cursor <= end:
        months.append(cursor)
        cursor = add_months(cursor, 1)
    return months


def _issued_invoices() -> list[dict]:
    """Factures émises (ni brouillon ni annulée)."""
    return [i for i in services.list_invoices("invoice") if i["status"] in ("pending", "paid")]


def _in_range(value: object, start: date, end: date) -> bool:
    d = parse_date(value)
    return bool(d and start <= d <= end)


def _kpi(params: dict, ref: date) -> dict:
    metric = params["metric"]
    summary = services.invoice_summary()
    if metric in ("to_collect", "overdue_total", "paid_month", "quotes_pending"):
        count_key = {"to_collect": "to_collect_count", "overdue_total": "overdue_count", "paid_month": "paid_month_count",
                     "quotes_pending": "quotes_pending_count"}[metric]
        return {"metric": metric, "value": summary[metric], "count": summary[count_key], "unit": "money"}
    if metric == "revenue_year":
        paid = [i for i in _issued_invoices()
                if i["status"] == "paid" and _in_range(i["paid_at"], date(ref.year, 1, 1), date(ref.year, 12, 31))]
        return {"metric": metric, "value": round(sum(i["subtotal"] for i in paid), 2), "count": len(paid), "unit": "money"}
    if metric == "vat_balance":
        period = fiscal.tva_period("month", ref)
        collected = deductible = 0.0
        for d in services.list_documents(period.start, period.end):
            if d["tva_type"] == "collected":
                collected += d["tva"] or 0
            else:
                deductible += d["tva"] or 0
        return {"metric": metric, "value": round(collected - deductible, 2), "count": None, "unit": "money"}
    return {"metric": metric, "value": services.time_saved_minutes(), "count": None, "unit": "minutes"}


def _revenue_by_month(params: dict, ref: date) -> dict:
    months = _months(params["period"], ref)
    invoices = _issued_invoices()
    rows = []
    for m in months:
        start, end = m, month_end(m)
        invoiced = sum(i["subtotal"] for i in invoices if _in_range(i["issued_at"], start, end))
        paid = sum(i["subtotal"] for i in invoices if i["status"] == "paid" and _in_range(i["paid_at"], start, end))
        rows.append({"label": fiscal.month_label_short(m), "invoiced": round(invoiced, 2), "paid": round(paid, 2)})
    return {"x": "label", "series": ["invoiced", "paid"], "rows": rows}


def _revenue_by_client(params: dict, ref: date) -> dict:
    start, end = _range(params["period"], ref)
    totals: dict[str, float] = {}
    for inv in _issued_invoices():
        if _in_range(inv["issued_at"], start, end):
            name = inv.get("client_name") or "—"
            totals[name] = totals.get(name, 0) + inv["subtotal"]
    rows = [{"label": name, "amount": round(total, 2)} for name, total in sorted(totals.items(), key=lambda x: -x[1])]
    return {"x": "label", "series": ["amount"], "rows": rows[: params["limit"]]}


def _unpaid_invoices(params: dict, ref: date) -> dict:
    statuses = ("overdue",) if params["only_overdue"] else ("pending", "overdue")
    rows = [
        {"id": i["id"], "number": i["number"], "client": i.get("client_name") or "", "title": i["title"],
         "total": i["total"], "due_date": i["due_date"], "days_overdue": i["days_overdue"], "status": i["display_status"]}
        for i in services.list_invoices("invoice") if i["display_status"] in statuses
    ]
    rows.sort(key=lambda r: (-r["days_overdue"], r["due_date"] or ""))
    return {"rows": rows[: params["limit"]], "total": round(sum(r["total"] for r in rows), 2), "count": len(rows)}


def _expenses_by_category(params: dict, ref: date) -> dict:
    start, end = _range(params["period"], ref)
    totals: dict[str, float] = {}
    for d in services.list_documents(start, end):
        if d["tva_type"] == "deductible":
            category = d["categorie"] or "Autres"
            totals[category] = totals.get(category, 0) + (d["ht"] or 0)
    rows = [{"label": c, "amount": round(v, 2)} for c, v in sorted(totals.items(), key=lambda x: -x[1])]
    return {"x": "label", "series": ["amount"], "rows": rows}


def _vat_by_month(params: dict, ref: date) -> dict:
    months = _months(params["period"], ref)
    docs = services.list_documents(months[0], month_end(months[-1]))
    rows = []
    for m in months:
        bucket = [d for d in docs if d["date"] and d["date"][:7] == m.isoformat()[:7]]
        rows.append({
            "label": fiscal.month_label_short(m),
            "collected": round(sum(d["tva"] or 0 for d in bucket if d["tva_type"] == "collected"), 2),
            "deductible": round(sum(d["tva"] or 0 for d in bucket if d["tva_type"] == "deductible"), 2),
        })
    return {"x": "label", "series": ["collected", "deductible"], "rows": rows}


def _pending_quotes(params: dict, ref: date) -> dict:
    rows = [
        {"id": q["id"], "number": q["number"], "client": q.get("client_name") or "", "title": q["title"], "total": q["total"],
         "issued_at": q["issued_at"]}
        for q in services.list_invoices("quote") if q["status"] == "pending"
    ]
    return {"rows": rows[: params["limit"]], "total": round(sum(r["total"] for r in rows), 2), "count": len(rows)}


def _deadlines(params: dict, ref: date) -> dict:
    return {"rows": services.upcoming_deadlines(ref)}


_RESOLVERS = {
    "kpi": _kpi, "revenue_by_month": _revenue_by_month, "revenue_by_client": _revenue_by_client,
    "unpaid_invoices": _unpaid_invoices, "expenses_by_category": _expenses_by_category, "vat_by_month": _vat_by_month,
    "pending_quotes": _pending_quotes, "deadlines": _deadlines,
}


def render(spec: object) -> dict:
    """Description → description validée + données de chaque carte."""
    clean = validate_spec(spec)
    ref = today()
    widgets = [{**w, "data": _RESOLVERS[w["source"]](w["params"], ref)} for w in clean["widgets"]]
    return {"title": clean["title"], "widgets": widgets}


# ═════════════════════════════════════════════════════════════════════════
# Analyse locale (sans IA) : mots-clés → cartes
# ═════════════════════════════════════════════════════════════════════════
def _fold(text: str) -> str:
    """minuscules, sans accents ni apostrophes typographiques"""
    # « ça » n'est pas « CA » (chiffre d'affaires) une fois les accents retirés
    text = re.sub(r"\bça\b", "cela", text.lower().replace("’", "'"))
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


# Ordre important : le plus précis d'abord (« TVA » avant « mois », « par client » avant « chiffre d'affaires »)
_KEYWORDS: list[tuple[str, dict]] = [
    (r"\btva\b|\bvat\b", {"source": "vat_by_month"}),
    (r"echeance|deadline|urssaf|declaration", {"source": "deadlines"}),
    (r"devis|quote", {"source": "pending_quotes"}),
    (r"depense|charge|achat|frais|expense|cost", {"source": "expenses_by_category"}),
    (r"\b(par|top|meilleurs?|principaux|gros|by|best|biggest)\b(\s+\S+){0,3}\s+clients?\b|clients?\s+(qui|les plus)",
     {"source": "revenue_by_client"}),
    (r"en retard|retards?\b|overdue|late", {"source": "unpaid_invoices", "params": {"only_overdue": True}}),
    (r"impaye|(?<!total )(?<!combien )(?<!montant )a encaisser|non paye|unpaid|attente de paiement", {"source": "unpaid_invoices"}),
    (r"(total|combien|montant)\b[^.?!]{0,20}\ba encaisser|how much (is )?(left )?to collect",
     {"source": "kpi", "params": {"metric": "to_collect"}}),
    (r"temps gagne|time saved|gagne du temps", {"source": "kpi", "params": {"metric": "time_saved"}}),
    (r"encaisse ce mois|paid this month|ce mois-ci", {"source": "kpi", "params": {"metric": "paid_month"}}),
    (r"chiffre d'affaires|\bca\b|revenus?|ventes|turnover|revenue|sales|factur", {"source": "revenue_by_month"}),
]
# Cette page ne fait qu'afficher : une demande de modification est refusée, pas interprétée
_MODIFY = re.compile(r"^\s*(change|modifie|corrige|mets? a jour|renomme|cree|envoie|relance|annule|paye|marque|valide|"
                     r"duplique|convertis|update|edit|create|send|cancel|mark|rename)\b")
_RECORD = re.compile(r"\b(facture|devis|client|document|invoice|quote)s?\s+(n°|no|numero|#)?\s*\d+")
_CLEAR = re.compile(r"^\s*(efface|vide|reinitialise|recommence|repars de zero|clear|reset|start over)\b")
_REMOVE = re.compile(r"^\s*(enleve|retire|supprime|cache|masque|vire|remove|hide|delete)\b")
_ADD = re.compile(r"^\s*(ajoute|rajoute|mets aussi|affiche aussi|montre aussi|et aussi|add|also show)\b|\baussi\b|\ben plus\b")
_TABLE = re.compile(r"\b(tableau|liste|table|list|detail)\b")
_PERIOD = [
    (re.compile(r"6 (derniers )?mois|six (derniers )?mois|semestre|6 months|six months"), "last_6_months"),
    (re.compile(r"12 (derniers )?mois|douze mois|12 months|twelve months|un an glissant"), "last_12_months"),
    (re.compile(r"trimestre|quarter"), "quarter"),
    (re.compile(r"\bce mois\b|\bdu mois\b|\bmensuel|this month"), "month"),
    (re.compile(r"\bannee\b|\ban\b|\bannuel|\byear\b|depuis janvier"), "year"),
]


def _matches(folded: str) -> list[dict]:
    """Cartes demandées, dans l'ordre où la demande les cite."""
    found = []
    for pattern, widget in _KEYWORDS:
        match = re.search(pattern, folded)
        if match:
            found.append({"source": widget["source"], "params": dict(widget.get("params", {})), "at": match.start()})
    sources = {w["source"] for w in found}
    revenue_named = re.search(r"chiffre d'affaires|\bca\b|revenu|ventes|revenue|sales", folded)
    # « factures impayées » : pas aussi un graphique de chiffre d'affaires
    if "unpaid_invoices" in sources and not revenue_named:
        found = [w for w in found if w["source"] != "revenue_by_month"]
    # « CA par client » : pas aussi le CA mois par mois, sauf si la demande le dit
    if "revenue_by_client" in sources and not re.search(r"par mois|mensuel|mois par mois|by month|monthly", folded):
        found = [w for w in found if w["source"] != "revenue_by_month"]
    # « en retard » et « impayées » ensemble : une seule carte, celle des retards
    unpaid = [w for w in found if w["source"] == "unpaid_invoices"]
    if len(unpaid) > 1:
        found = [w for w in found if w["source"] != "unpaid_invoices"] + [unpaid[0]]
    return [{"source": w["source"], "params": w["params"]} for w in sorted(found, key=lambda w: w["at"])]


def compose_offline(text: str, current: dict) -> dict:
    """Demande + vue actuelle → nouvelle vue et message d'explication. Sans IA."""
    folded = _fold(text)
    current = validate_spec(current)
    period = next((p for pattern, p in _PERIOD if pattern.search(folded)), None)

    if _MODIFY.search(folded) or _RECORD.search(folded):
        return {"spec": current, "message": "read_only", "understood": False}

    if _CLEAR.search(folded):
        return {"spec": {**current, "widgets": []}, "message": "cleared", "understood": True}

    if _REMOVE.search(folded):
        targets = {w["source"] for w in _matches(folded)}
        # « enlève le graphique » / « enlève le tableau » : par type de carte
        visuals = set()
        if not targets:
            if re.search(r"graphique|graph|chart|barres", folded):
                visuals.add("bar")
            if re.search(r"tableau|table", folded):
                visuals.add("table")
            if re.search(r"chiffre cle|carte chiffre|kpi", folded):
                visuals.add("stat")
        if not targets and not visuals:
            return {"spec": current, "message": "remove_unknown", "understood": False}
        kept = [w for w in current["widgets"] if w["source"] not in targets and w["visual"] not in visuals]
        removed = len(current["widgets"]) - len(kept)
        return {"spec": {**current, "widgets": kept}, "message": "removed" if removed else "remove_none",
                "understood": bool(removed)}

    found = _matches(folded)
    if not found:
        return {"spec": current, "message": "not_understood", "understood": False}
    wants_table = bool(_TABLE.search(folded))
    widgets = []
    for w in found:
        entry = CATALOG[w["source"]]
        visual = "table" if wants_table and "table" in entry["visuals"] else entry["default_visual"]
        params = dict(w["params"])
        top = re.search(r"\b(?:top|les|mes)\s+(\d{1,2})\b", folded)
        if top and "limit" in entry["params"]:
            params["limit"] = int(top.group(1))
        if period and "period" in entry["params"]:
            # un graphique mensuel sur « ce mois » n'aurait qu'une barre : on garde l'année
            params["period"] = "year" if period == "month" and w["source"] in ("revenue_by_month", "vat_by_month") else period
        widgets.append({"source": w["source"], "visual": visual, "params": params})

    adding = bool(_ADD.search(folded)) and bool(current["widgets"])
    spec = validate_spec({"title": current["title"], "widgets": (current["widgets"] if adding else []) + widgets})
    return {"spec": spec, "message": "added" if adding else "composed", "understood": True}


# ═════════════════════════════════════════════════════════════════════════
# Vues enregistrées (propres à chaque utilisateur)
# ═════════════════════════════════════════════════════════════════════════
def _view(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "spec": validate_spec(db.loads(row["spec"], {})), "prompt": row["prompt"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_views(user_id: int) -> list[dict]:
    rows = db.fetch_all("SELECT * FROM dashboard_views WHERE user_id = ? ORDER BY created_at, id", (user_id,))
    return [_view(r) for r in rows]


def get_view(user_id: int, view_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM dashboard_views WHERE id = ? AND user_id = ?", (view_id, user_id))
    if not row:
        raise services.NotFound("Vue introuvable")
    return _view(row)


def _view_values(data: dict) -> dict:
    name = _clean_text(data.get("name"))
    if not name:
        raise ValueError("Donnez un nom à la vue.")
    spec = validate_spec(data.get("spec"))
    if not spec["widgets"]:
        raise ValueError("La vue est vide : ajoutez au moins une carte.")
    return {"name": name, "spec": db.dumps(spec), "prompt": _clean_text(data.get("prompt"), MAX_PROMPT)}


def create_view(user_id: int, data: dict) -> dict:
    count = db.fetch_one("SELECT COUNT(*) AS n FROM dashboard_views WHERE user_id = ?", (user_id,))["n"]
    if count >= MAX_VIEWS:
        raise services.Conflict(f"{MAX_VIEWS} vues au plus : supprimez-en une avant d'en créer une autre.")
    now = db.now_iso()
    view_id = db.insert("dashboard_views", {**_view_values(data), "user_id": user_id, "created_at": now, "updated_at": now})
    return get_view(user_id, view_id)


def update_view(user_id: int, view_id: int, data: dict) -> dict:
    current = get_view(user_id, view_id)
    values = _view_values({"name": data.get("name", current["name"]), "spec": data.get("spec", current["spec"]),
                           "prompt": data.get("prompt", current["prompt"])})
    db.update("dashboard_views", view_id, {**values, "updated_at": db.now_iso()})
    return get_view(user_id, view_id)


def delete_view(user_id: int, view_id: int) -> None:
    get_view(user_id, view_id)
    db.execute("DELETE FROM dashboard_views WHERE id = ? AND user_id = ?", (view_id, user_id))


def catalog() -> list[dict]:
    """Catalogue décrit pour l'IA (et l'API) : sources, visuels et paramètres possibles."""
    return [{"source": s, "visuals": list(e["visuals"]), "params": list(e["params"]), "description": e["description"]}
            for s, e in CATALOG.items()]


def ai_enabled() -> bool:
    return config.AI_ENABLED
