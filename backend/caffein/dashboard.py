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
import threading
import time
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
        "description": "chiffre d'affaires HT facturé et encaissé, mois par mois (period : last_6_months, last_12_months, quarter ou year)",
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

# Module de chaque source et de chaque chiffre clé : une carte ne s'affiche que si l'utilisateur
# peut consulter ce module (et qu'il est actif). Voir docs/modules.md.
SOURCE_MODULES = {
    "revenue_by_month": "sales", "revenue_by_client": "sales", "unpaid_invoices": "sales", "pending_quotes": "sales",
    "expenses_by_category": "accounting", "vat_by_month": "accounting", "deadlines": "accounting",
}
METRIC_MODULES = {
    "to_collect": "sales", "overdue_total": "sales", "paid_month": "sales", "revenue_year": "sales",
    "quotes_pending": "sales", "vat_balance": "accounting", "time_saved": "home",
}


# Chiffres clés des modules (Kpi), proposés comme cartes « kpi » : metric = « module.clé ».
# Ceux qui existent déjà ci-dessus sous un nom historique ne sont pas proposés deux fois.
LEGACY_KPIS = {"home.time_saved", "sales.to_collect", "sales.overdue", "sales.paid_month", "sales.quotes_pending",
               "accounting.vat_balance"}


def module_metrics(levels: dict[str, int] | None = None) -> dict:
    """{« stock.to_reorder »: (module, kpi)} pour les modules que l'utilisateur peut consulter (`levels`)."""
    from .core import modules as registry

    out = {}
    for module in registry.ordered():
        if levels is not None and levels.get(module.key, 0) < 1:
            continue
        for kpi in module.kpis:
            key = f"{module.key}.{kpi.key}"
            if key not in LEGACY_KPIS:
                out[key] = (module, kpi)
    return out


def widget_module(widget: dict) -> str:
    if widget["source"] == "kpi":
        metric = widget["params"]["metric"]
        return metric.split(".")[0] if "." in metric else METRIC_MODULES[metric]
    return SOURCE_MODULES[widget["source"]]


def allowed(widget: dict, levels: dict[str, int] | None) -> bool:
    """`levels` : niveaux de l'utilisateur par module (None : pas de filtre, usage interne et tests)."""
    return levels is None or levels.get(widget_module(widget), 0) >= 1


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
        metric = raw.get("metric")
        params["metric"] = metric if isinstance(metric, str) and (metric in METRICS or metric in module_metrics()) else "to_collect"
    if "period" in allowed:
        default = "year" if source in ("revenue_by_client", "expenses_by_category") else "last_12_months"
        params["period"] = raw.get("period") if raw.get("period") in PERIODS else default
    if "limit" in allowed:
        value = raw.get("limit")
        try:
            limit = 0 if isinstance(value, bool) else int(value or 0)
        except (TypeError, ValueError, OverflowError):  # « Infinity », 1e999…
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
    # Les cartes au-delà de 8 sont ignorées ; on n'en examine pas plus de 64 (doublons compris)
    for raw in raw_widgets[: MAX_WIDGETS * 8]:
        source = raw.get("source") if isinstance(raw, dict) else None
        if not isinstance(source, str) or source not in CATALOG:
            continue
        entry = CATALOG[source]
        visual = raw.get("visual") if raw.get("visual") in entry["visuals"] else entry["default_visual"]
        params = _clean_params(source, raw.get("params"))
        key = (source, visual, tuple(sorted(params.items())))
        if key in seen:
            continue
        seen.add(key)
        title = raw.get("title") if isinstance(raw.get("title"), str) else ""
        widgets.append({"source": source, "visual": visual, "title": _clean_text(title), "params": params})
        if len(widgets) == MAX_WIDGETS:
            break
    return {"title": _clean_text(spec.get("title") if isinstance(spec.get("title"), str) else ""), "widgets": widgets}


# ═════════════════════════════════════════════════════════════════════════
# Calcul des données (lecture seule)
# ═════════════════════════════════════════════════════════════════════════
def _range(period: str, ref: date) -> tuple[date, date]:
    if period == "month":
        p = fiscal.tva_period("month", ref)
        return p.start, p.end
    if period == "quarter":  # trimestre civil en cours (janvier-mars, avril-juin…)
        start = date(ref.year, 3 * ((ref.month - 1) // 3) + 1, 1)
        return start, month_end(add_months(start, 2))
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


def _module_kpi(metric: str) -> dict:
    """Chiffre clé d'un module, calculé par le module lui-même (mêmes valeurs que sur l'accueil)."""
    module, kpi = module_metrics()[metric]
    data = kpi.compute() or {}
    return {"metric": metric, "value": data.get("value"), "count": data.get("count"), "unit": kpi.unit, "label": kpi.label,
            "foot": kpi.foot, "icon": kpi.icon, "path": kpi.path, "alert": bool(kpi.alert and kpi.alert(data))}


def _kpi(params: dict, ref: date) -> dict:
    metric = params["metric"]
    if "." in metric:
        return _module_kpi(metric)
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
        return {"metric": metric, "value": round(collected - deductible, 2), "count": None, "unit": "money",
                "vat_exempt": bool(services.get_profile()["vat_exempt"])}
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
    totals: dict[object, list] = {}  # client (id, ou nom à défaut) → [nom, total]
    for inv in _issued_invoices():
        if _in_range(inv["issued_at"], start, end):
            key = inv.get("client_id") or inv.get("client_name") or "—"
            entry = totals.setdefault(key, [inv.get("client_name") or "—", 0.0])
            entry[1] += inv["subtotal"]
    rows, seen = [], {}
    for name, total in sorted(totals.values(), key=lambda x: -x[1]):
        # deux clients du même nom restent deux lignes (les libellés servent de clés au graphique)
        seen[name] = seen.get(name, 0) + 1
        rows.append({"label": name if seen[name] == 1 else f"{name} ({seen[name]})", "amount": round(total, 2)})
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
    return {"x": "label", "series": ["collected", "deductible"], "rows": rows,
            "vat_exempt": bool(services.get_profile()["vat_exempt"])}


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


def render(spec: object, levels: dict[str, int] | None = None) -> dict:
    """Description → description validée + données de chaque carte. Les cartes d'un module que
    l'utilisateur ne peut pas consulter sont retirées (`hidden` en donne le nombre)."""
    clean = validate_spec(spec)
    ref = today()
    kept = [w for w in clean["widgets"] if allowed(w, levels)]
    widgets = [{**w, "data": _RESOLVERS[w["source"]](w["params"], ref)} for w in kept]
    return {"title": clean["title"], "widgets": widgets, "hidden": len(clean["widgets"]) - len(kept)}


# ═════════════════════════════════════════════════════════════════════════
# Analyse locale (sans IA) : mots-clés → cartes
# ═════════════════════════════════════════════════════════════════════════
def _fold(text: str) -> str:
    """minuscules, sans accents ni apostrophes typographiques"""
    # « ça » n'est pas « CA » (chiffre d'affaires) une fois les accents retirés
    text = re.sub(r"\bça\b", "cela", text.lower().replace("’", "'"))
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


# « CA » = chiffre d'affaires s'il est écrit en majuscules, ou précédé d'un déterminant, ou suivi d'un
# qualificatif. Sinon « ca » est souvent « ça » tapé sans cédille (« comment ca va »).
_CA_UPPER = re.compile(r"\bCA\b")
_CA_FOLDED = re.compile(r"\b(?:mon|le|du|de|notre|son|ton|votre|leur)\s+ca\b|\bca\s+(?:par|ht|ttc|encaiss|factur|mensuel|annuel|sur|du|de|des)\b")
_REVENUE_WORDS = r"chiffre d'affaires|\brevenus?\b|\bventes\b|turnover|revenue|\bsales\b"

# Ordre important : les chiffres clés avant les graphiques, le plus précis d'abord
_KEYWORDS: list[tuple[str, dict]] = [
    (r"(?:total|combien|montant)\b[^.?!]{0,20}\ba encaisser|(?:how much|amount)(?: is)?(?: left)? to collect|left to collect|owed to me",
     {"source": "kpi", "params": {"metric": "to_collect"}}),
    (r"(?:total|combien|montant)\b[^.?!]{0,25}(?:en retard|overdue)", {"source": "kpi", "params": {"metric": "overdue_total"}}),
    (r"(?:total|combien|montant)\b[^.?!]{0,25}\bdevis|(?:total|value) of (?:my )?(?:pending )?quotes",
     {"source": "kpi", "params": {"metric": "quotes_pending"}}),
    (r"solde de (?:la )?tva|tva a (?:payer|reverser)|vat balance|vat (?:due|to pay)", {"source": "kpi", "params": {"metric": "vat_balance"}}),
    (r"\bca (?:encaisse )?(?:de l'annee|annuel)|chiffre d'affaires (?:encaisse )?(?:de l'annee|annuel)|revenue (?:this|for the) year|annual revenue",
     {"source": "kpi", "params": {"metric": "revenue_year"}}),
    (r"encaiss\w*\b[^.?!]{0,20}\bce mois|encaissements? du mois|(?:paid|collected) this month", {"source": "kpi", "params": {"metric": "paid_month"}}),
    (r"temps gagne|time saved|gagne du temps", {"source": "kpi", "params": {"metric": "time_saved"}}),
    (r"\btva\b|\bvat\b", {"source": "vat_by_month"}),
    (r"echeance|deadline|urssaf|declaration", {"source": "deadlines"}),
    (r"devis|quotes?\b", {"source": "pending_quotes"}),
    (r"depense|\bcharges?\b|\bachats?\b|\bfrais\b|expense|\bcosts?\b", {"source": "expenses_by_category"}),
    (r"\b(?:par|top|meilleurs?|principaux|gros|by|best|biggest)\b(?:\s+\S+){0,3}\s+(?:clients?|customers?)\b"
     r"|(?:clients?|customers?)\s+(?:qui|les plus)|clientele", {"source": "revenue_by_client"}),
    (r"en retard|\bretards?\b|overdue|\blate\b", {"source": "unpaid_invoices", "params": {"only_overdue": True}}),
    (r"impaye|non paye|unpaid|attente de paiement|a encaisser", {"source": "unpaid_invoices"}),
    (_REVENUE_WORDS + r"|factur", {"source": "revenue_by_month"}),
]
_MONTHLY = re.compile(r"par mois|mensuel|mois par mois|evolution|graphique|courbe|by month|monthly|chart|trend")
_DETAIL = re.compile(r"\b(?:liste|tableau|detail|lesquel|lesquelles|quels|quelles|lister|list|table|which)\b|\bfactures\b")

# Cette page ne fait qu'afficher : une demande qui touche aux données est refusée, pas interprétée.
# Un numéro de pièce (« facture 12 », « facture CAFFEIN-2026-00004 ») désigne une donnée ;
# « mes factures 2026 » désigne une année.
_RECORD = re.compile(r"\b(?:facture|devis|client|document|invoice|quote)s?\s+(?:n°|no\.?|numero|#)?\s*"
                     r"(?!(?:19|20)\d{2}\b(?!-))[a-z]*-?\d[\w-]*")
_SINGLE_RECORD = re.compile(r"\b(?:la|cette|une) facture\b|\b(?:le|ce|un) (?:devis|client|document)\b|\bthis (?:invoice|quote|client)\b")
_VIEW_OBJECT = r"\b(?:vue|view|graphique|graph|chart|tableau|table|carte|cartes|card|affichage|page)\b"
_MODIFY = re.compile(r"^\s*(?:change|modifie|corrige|mets? a jour|renomme|cree|paye|marque|valide|annule|duplique|convertis|"
                     r"update|edit|create|cancel|mark|rename|pay)\b(?![^.?!]{0,40}" + _VIEW_OBJECT + ")")
_ACTION = re.compile(r"^\s*(?:envoie|relance|send|remind|email)\b")
_CLEAR = re.compile(r"^\s*(?:efface|vide|reinitialise|recommence|repars de zero|clear|reset|start over)\b"
                    r"|^\s*(?:enleve|retire|supprime|remove|delete)\s+(?:tout|toutes les cartes|all|everything)\b")
_REMOVE = re.compile(r"^\s*(?:enleve|retire|supprime|cache|masque|vire|efface|vide|remove|hide|delete)\b")
_ADD = re.compile(r"^\s*(?:ajoute|rajoute|mets aussi|affiche aussi|montre aussi|et aussi|add|also show)\b|\baussi\b|\ben plus\b")
_TABLE = re.compile(r"\b(?:tableau|liste|table|list|detail)\b")
_SWITCH = re.compile(r"\b(?:en|as an?|as)\s+(tableau|table|liste|list|graphique|barres|bar chart|chart|graph)\b")
_TOP = re.compile(r"\b(?:top|les|mes|my)\s+(\d{1,2})\b(?!\s+(?:derni\w+\s+|prochain\w*\s+|last\s+|next\s+)?"
                  r"(?:mois|jours?|semaines?|ans?|annees?|months?|days?|weeks?|years?)\b)")
# Le catalogue ne connaît que les périodes en cours : « l'an dernier » n'est pas « cette année »
_PREVIOUS = re.compile(r"\b(?:annee|an|mois|trimestre|semestre)\s+(?:dernier|derniere|precedent|precedente|passee?)\b"
                       r"|\b(?:last|previous|past)\s+(?:year|month|quarter)\b")
_PERIOD = [
    (re.compile(r"6 (?:derniers )?mois|six (?:derniers )?mois|semestre|6 months|six months"), "last_6_months"),
    (re.compile(r"12 (?:derniers )?mois|douze mois|12 months|twelve months|un an glissant"), "last_12_months"),
    (re.compile(r"trimestre|quarter"), "quarter"),
    (re.compile(r"\bce mois\b|\bdu mois\b|\bmensuel|this month"), "month"),
    (re.compile(r"\bannee\b|\bannuel|\b(?:un|cet|par)\s+an\b|\bl'an\b|\byear\b|depuis janvier"), "year"),
]


def _metric_patterns(levels: dict[str, int] | None) -> list[tuple[str, str]]:
    """(motif, chiffre clé) : le libellé français ou anglais du chiffre clé, sans accents, cité dans la demande."""
    out = []
    for key, (_module, kpi) in module_metrics(levels).items():
        for label in kpi.label:
            folded = _fold(label).strip()
            if len(folded) >= 6:
                out.append((r"\b" + re.escape(folded) + r"\b", key))
    return out


def _matches(folded: str, original: str = "", levels: dict[str, int] | None = None) -> list[dict]:
    """Cartes demandées, dans l'ordre où la demande les cite."""
    found = []
    for pattern, metric in _metric_patterns(levels):
        match = re.search(pattern, folded)
        if match and not any(w["params"].get("metric") == metric for w in found):
            found.append({"source": "kpi", "params": {"metric": metric}, "at": match.start()})
    for pattern, widget in _KEYWORDS:
        match = re.search(pattern, folded)
        if match:
            found.append({"source": widget["source"], "params": dict(widget.get("params", {})), "at": match.start()})
    ca = _CA_UPPER.search(original) or _CA_FOLDED.search(folded)
    revenue_named = bool(re.search(_REVENUE_WORDS, folded) or ca)
    if ca and not any(w["source"] == "revenue_by_month" for w in found):
        found.append({"source": "revenue_by_month", "params": {}, "at": ca.start()})

    def drop(source: str) -> None:
        nonlocal found
        found = [w for w in found if w["source"] != source]

    sources = {w["source"] for w in found}
    metrics = {w["params"].get("metric") for w in found if w["source"] == "kpi"}
    monthly = bool(_MONTHLY.search(folded))
    detail = bool(_DETAIL.search(folded))
    # Un chiffre clé demandé : pas aussi le graphique ou le tableau du même sujet, sauf si la demande le dit
    if "revenue_year" in metrics and not monthly:
        drop("revenue_by_month")
    if "vat_balance" in metrics and not monthly:
        drop("vat_by_month")
    if "quotes_pending" in metrics and not detail:
        drop("pending_quotes")
    if metrics & {"to_collect", "overdue_total"} and not re.search(r"impaye|non paye|unpaid|" + _DETAIL.pattern, folded):
        drop("unpaid_invoices")
    if "paid_month" in metrics and not (re.search(_REVENUE_WORDS, folded) or ca):
        drop("revenue_by_month")
    # « factures impayées » : pas aussi un graphique de chiffre d'affaires
    if "unpaid_invoices" in sources and not revenue_named:
        drop("revenue_by_month")
    # « CA par client » : pas aussi le CA mois par mois, sauf si la demande le dit
    if "revenue_by_client" in sources and not re.search(r"par mois|mensuel|mois par mois|by month|monthly", folded):
        drop("revenue_by_month")
    # « en retard » et « impayées » ensemble : une seule carte, celle des retards
    unpaid = [w for w in found if w["source"] == "unpaid_invoices"]
    if len(unpaid) > 1:
        found = [w for w in found if w["source"] != "unpaid_invoices"] + [unpaid[0]]
    return [{"source": w["source"], "params": w["params"]} for w in sorted(found, key=lambda w: w["at"])]


def _refused(message: str, current: dict) -> dict:
    return {"spec": current, "message": message, "understood": False}


def compose_offline(text: str, current: dict, levels: dict[str, int] | None = None) -> dict:
    """Demande + vue actuelle → nouvelle vue et message d'explication. Sans IA."""
    folded = _fold(text)
    current = validate_spec(current)

    if _ACTION.search(folded) or _MODIFY.search(folded) or _RECORD.search(folded):
        return _refused("read_only", current)
    if _PREVIOUS.search(folded):
        return _refused("period_unsupported", current)

    found = _matches(folded, text, levels)
    if _CLEAR.search(folded) and (not found or re.search(r"\b(?:tout|all|everything)\b", folded)):
        return {"spec": {**current, "widgets": []}, "message": "cleared", "understood": True}

    if _REMOVE.search(folded):
        if _SINGLE_RECORD.search(folded):
            return _refused("read_only", current)
        targets = {w["source"] for w in found}
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
            return _refused("remove_unknown", current)
        kept = [w for w in current["widgets"] if w["source"] not in targets and w["visual"] not in visuals]
        removed = len(current["widgets"]) - len(kept)
        return {"spec": {**current, "widgets": kept}, "message": "removed" if removed else "remove_none",
                "understood": bool(removed)}

    # « modifie le graphique en tableau », « passe les impayés en graphique » : on change l'affichage
    switch = _SWITCH.search(folded)
    if switch and current["widgets"]:
        named = {w["source"] for w in found}
        shown = {w["source"] for w in current["widgets"]}
        if named <= shown:
            visual = "table" if switch.group(1) in ("tableau", "table", "liste", "list") else "bar"
            widgets, changed = [], 0
            for w in current["widgets"]:
                if (not named or w["source"] in named) and visual in CATALOG[w["source"]]["visuals"] and w["visual"] != visual:
                    w = {**w, "visual": visual}
                    changed += 1
                widgets.append(w)
            if changed:
                return {"spec": validate_spec({**current, "widgets": widgets}), "message": "changed", "understood": True}

    if not found:
        return _refused("not_understood", current)
    period = next((p for pattern, p in _PERIOD if pattern.search(folded)), None)
    top = _TOP.search(folded)
    wants_table = bool(_TABLE.search(folded))
    widgets = []
    for w in found:
        entry = CATALOG[w["source"]]
        visual = "table" if wants_table and "table" in entry["visuals"] else entry["default_visual"]
        params = dict(w["params"])
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
    values = _view_values(data)
    now = db.now_iso()
    # Compter et insérer dans la même transaction : deux créations simultanées ne dépassent pas la limite
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT COUNT(*) AS n FROM dashboard_views WHERE user_id = ?", (user_id,)).fetchone()["n"]
        if count >= MAX_VIEWS:
            raise services.Conflict(f"{MAX_VIEWS} vues au plus : supprimez-en une avant d'en créer une autre.")
        view_id = conn.execute(
            "INSERT INTO dashboard_views (user_id, name, spec, prompt, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, values["name"], values["spec"], values["prompt"], now, now)).lastrowid
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


# ── Limite des appels à l'IA ─────────────────────────────────────────────
# Au-delà, la demande passe par l'analyse locale : la page reste utilisable, sans coût ni attente.
AI_CALLS_PER_MINUTE = 20
_ai_calls: dict[str, list[float]] = {}
_ai_lock = threading.Lock()
_ai_slots = threading.BoundedSemaphore(4)  # appels simultanés au plus (chacun occupe un worker)


def ai_allowed(key: str) -> bool:
    """Enregistre un appel pour `key` (utilisateur, et adresse IP en démo) s'il reste du quota."""
    cutoff = time.monotonic() - 60
    with _ai_lock:
        recent = [t for t in _ai_calls.get(key, []) if t > cutoff]
        if len(recent) >= AI_CALLS_PER_MINUTE:
            _ai_calls[key] = recent
            return False
        _ai_calls[key] = [*recent, time.monotonic()]
        return True


def catalog(levels: dict[str, int] | None = None) -> list[dict]:
    """Catalogue décrit pour l'IA (et l'API) : sources, visuels et paramètres possibles.
    Avec `levels`, seulement les sources des modules que l'utilisateur peut consulter."""
    out = [{"source": s, "visuals": list(e["visuals"]), "params": list(e["params"]), "description": e["description"]}
           for s, e in CATALOG.items() if s == "kpi" or levels is None or levels.get(SOURCE_MODULES[s], 0) >= 1]
    extra = module_metrics(levels)
    if extra:
        out[0] = {**out[0], "description": out[0]["description"] + " ; et les chiffres clés des modules : "
                  + ", ".join(f"{key} ({kpi.label[0]})" for key, (_m, kpi) in extra.items())}
    return out


def ai_enabled() -> bool:
    return config.AI_ENABLED
