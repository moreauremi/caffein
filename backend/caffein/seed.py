# SPDX-License-Identifier: AGPL-3.0-or-later
"""Initialisation d'une instance et données de démonstration.

- `init_instance()` : instance vierge (assistant d'installation sans démo).
- `seed()` : jeu de démonstration daté relativement au jour du lancement.

    python -m caffein seed --demo           # ajoute la démo si la base est vide
    python -m caffein seed --demo --reset   # efface les données métier puis recrée la démo

Les comptes utilisateurs ne sont jamais supprimés par ces fonctions.
"""

from __future__ import annotations

import shutil
from datetime import datetime, time, timedelta

from . import config, db, services
from .ai import reminder_template
from .core import modules as registry
from .email_templates import TONE_LABELS, invoice_email, onboarding_email, reminder_email, reminder_subject, sender_name
from .pdf_invoice import render_invoice_pdf, render_supplier_invoice_pdf
from .utils import add_months, fmt_date_long, fmt_money, slugify_name, today

PROFILE = {
    "full_name": "Alex Durand", "company": "Studio Durand", "email": "alex@studio-durand.example",
    "phone": "06 12 34 56 78", "address": "18 rue des Lilas", "zip_code": "69003", "city": "Lyon",
    "siret": "123 456 789 00010", "naf_code": "74.10Z", "iban": "FR76 3000 6000 0112 3456 7890 189",
    "bic": "AGRIFRPP882", "activity": "bnc", "declaration_frequency": "monthly", "vat_exempt": 0,
    "vat_number": "FR12 123456789", "default_vat_rate": 0.20, "payment_terms_days": 30, "invoice_prefix": "CAFFEIN",
}

CLIENTS = [
    {"name": "Atelier Nova", "contact_name": "Jean Martin", "email": "jean.martin@atelier-nova.example",
     "address": "12 quai Saint-Antoine", "zip_code": "69002", "city": "Lyon", "siren": "512 345 678"},
    {"name": "Kairos Conseil", "contact_name": "Sophie Bernard", "email": "compta@kairos-conseil.example",
     "address": "4 rue de la Paix", "zip_code": "75002", "city": "Paris", "siren": "498 765 432"},
    {"name": "Maison Verde", "contact_name": "Lucas Petit", "email": "lucas@maison-verde.example",
     "address": "27 cours Julien", "zip_code": "13006", "city": "Marseille"},
    {"name": "Pixel & Co", "contact_name": "Inès Robert", "email": "ines@pixelandco.example",
     "address": "9 rue Sainte-Catherine", "zip_code": "33000", "city": "Bordeaux", "siren": "823 456 001"},
    {"name": "Boulangerie Lemoine", "contact_name": "Claire Lemoine", "email": "contact@boulangerie-lemoine.example",
     "address": "3 place du Marché", "zip_code": "69005", "city": "Lyon"},
]

# (client, titre, lignes [(desc, qté, PU)], émise J-x, payée J-x | None, relances, dernière relance J-x)
INVOICES = [
    ("Atelier Nova", "Identité visuelle", [("Création de l'identité visuelle (logo, palette, typographies)", 1, 2400)], 250, 230, 0, None),
    ("Kairos Conseil", "Refonte du site vitrine", [("Design et intégration du site vitrine", 6, 450)], 220, 200, 0, None),
    ("Pixel & Co", "Maquettes application mobile", [("Maquettes UI de l'application (12 écrans)", 4, 500)], 190, 175, 0, None),
    ("Maison Verde", "Charte graphique", [("Charte graphique et déclinaisons", 1, 1800)], 160, 140, 0, None),
    ("Atelier Nova", "Supports print salon", [("Kakémono 85×200", 1, 450), ("Flyers A5 recto-verso", 1, 500)], 130, 118, 0, None),
    ("Kairos Conseil", "Maintenance site — T2", [("Maintenance et mises à jour (forfait mensuel)", 3, 350)], 100, 90, 0, None),
    ("Boulangerie Lemoine", "Logo et menu", [("Logo", 1, 450), ("Mise en page du menu", 1, 200)], 75, 60, 0, None),
    ("Pixel & Co", "Design system", [("Conception du design system (jours)", 8, 480)], 55, 38, 0, None),
    ("Maison Verde", "Shooting & retouches", [("Shooting produits (demi-journée)", 1, 600), ("Retouches photo", 20, 30)], 40, 20, 0, None),
    ("Boulangerie Lemoine", "Site vitrine", [("Site vitrine 5 pages", 1, 1900)], 60, None, 1, 12),
    ("Atelier Nova", "Brochure commerciale", [("Brochure 12 pages — conception et mise en page", 1, 1500)], 34, None, 0, None),
    ("Kairos Conseil", "Atelier UX", [("Atelier UX avec les équipes (jours)", 2, 600)], 20, None, 0, None),
    ("Maison Verde", "Bannières réseaux sociaux", [("Pack de 10 visuels réseaux sociaux", 1, 420)], 5, 1, 0, None),
    ("Pixel & Co", "Icônes sur mesure", [("Icônes sur mesure", 24, 35)], 8, None, 0, None),
]

QUOTES = [
    ("Kairos Conseil", "Refonte de l'espace client", [("Refonte UX/UI de l'espace client (jours)", 12, 500)], 15, "pending"),
    ("Boulangerie Lemoine", "Shooting produits", [("Shooting produits en boutique", 1, 900)], 10, "accepted"),
    ("Pixel & Co", "Design system", [("Conception du design system (jours)", 8, 480)], 70, "invoiced"),
]

# (fournisseur, adresse, résumé, HT, taux TVA, catégorie, jours avant aujourd'hui)
SUPPLIERS = {
    "Adobe Systems France": ("4-6 cours de l'Île Seguin, 92100 Boulogne-Billancourt", "Logiciels/SaaS"),
    "OVHcloud": ("2 rue Kellermann, 59100 Roubaix", "Logiciels/SaaS"),
    "SNCF Voyageurs": ("9 rue Jean-Philippe Rameau, 93200 Saint-Denis", "Transport"),
    "LDLC": ("2 rue des Érables, 69760 Limonest", "Matériel"),
    "La Ruche Coworking": ("41 rue de la Charité, 69002 Lyon", "Frais fixes"),
    "Figma France": ("10 rue de Penthièvre, 75008 Paris", "Logiciels/SaaS"),
    "Imprimerie du Rhône": ("55 avenue Jean Jaurès, 69007 Lyon", "Marketing"),
}

NOTIFICATIONS = [
    ("Relances intelligentes", "Caffein rédige désormais vos relances avec l'IA, en trois tons progressifs, et vous prévient à chaque envoi.", "📮 Nouveauté", 2),
    ("Classement plus fiable", "L'extraction des factures fournisseurs gère mieux les PDF scannés et les photos de tickets.", "⚡ Amélioration", 9),
    ("Factur-X & export comptable", "Prochaine étape : factures au format Factur-X et export FEC pour votre expert-comptable.", "🗺️ Roadmap", 20),
    ("Facturation électronique", "Depuis le 1er septembre 2026, vous devez pouvoir recevoir des factures électroniques. L'émission suivra en 2027.", "⚠️ Information", 35),
]

TAG_COLORS = {"📮 Nouveauté": ("#E3F2FD", "#1565C0"), "⚡ Amélioration": ("#F3E5F5", "#6A1B9A"),
              "🗺️ Roadmap": ("#E8F5E9", "#2E7D32"), "⚠️ Information": ("#FFF3E0", "#E65100")}


def _stamp(days_ago: int, hour: int = 10, minute: int = 0) -> str:
    d = today() - timedelta(days=days_ago)
    return datetime.combine(d, time(hour, minute), tzinfo=config.TIMEZONE).isoformat()


def _day(days_ago: int) -> str:
    return (today() - timedelta(days=days_ago)).isoformat()


WELCOME_NOTIFICATIONS = [
    ("Bienvenue dans Caffein", "Votre instance est prête. Créez une facture en une phrase ou déposez vos premiers justificatifs.", "📮 Nouveauté"),
    ("Configurez l'envoi des emails", "Sans serveur SMTP, les emails restent dans la boîte d'envoi. Renseignez CAFFEIN_SMTP_* dans la configuration.", "⚠️ Information"),
    ("Activez l'IA (optionnel)", "Avec une clé ANTHROPIC_API_KEY, Claude lit vos factures, rédige les devis et les relances.", "⚡ Amélioration"),
    ("Pensez aux sauvegardes", "La commande « caffein backup » archive la base, les documents et la clé de chiffrement.", "⚠️ Information"),
]

# Tables métier du socle, dans un ordre compatible avec les clés étrangères
BUSINESS_TABLES = ("emails", "job_runs", "documents", "invoice_lines", "invoices", "clients", "notifications", "declarations",
                   "alerts_sent", "profile")


def business_tables() -> list[str]:
    """Tables vidées par une réinitialisation : celles des modules (les plus dépendants d'abord), puis celles du socle.
    Les comptes, les rôles, les droits et l'activation des modules sont conservés."""
    tables: list[str] = []
    for module in reversed(registry.dependency_order()):
        tables += [t for t in module.reset_tables if t not in tables]
    return tables + [t for t in BUSINESS_TABLES if t not in tables]


# Instance de démonstration : une équipe aux rôles différents, pour montrer les droits par module.
# Mots de passe aléatoires et jamais affichés : on ne peut pas se connecter avec ces comptes.
DEMO_TEAM = [
    ("camille.roux@studio-durand.example", "Camille Roux", "sales", {}),
    ("hugo.martin@studio-durand.example", "Hugo Martin", "production", {}),
    ("lea.bernard@studio-durand.example", "Léa Bernard", "accountant", {"hr": 1}),
    ("nina.lefevre@studio-durand.example", "Nina Lefèvre", "readonly", {"accounting": 0}),
]


def seed_demo_team() -> None:
    """Membres de démonstration (mode démo seulement) ; ceux qui existent déjà sont laissés tels quels."""
    import secrets

    from . import auth
    from .core import permissions

    for email, name, role_key, overrides in DEMO_TEAM:
        if auth.get_user_by_email(email):
            continue
        role = db.fetch_one("SELECT id FROM roles WHERE key = ?", (role_key,))
        user = auth.create_user(email, secrets.token_urlsafe(24), name, "member", role_id=role["id"] if role else None)
        if overrides:
            permissions.set_user_overrides(user["id"], overrides)


def is_empty() -> bool:
    return db.fetch_one("SELECT COUNT(*) AS n FROM clients")["n"] == 0


def _clear_tables() -> None:
    tables = business_tables()
    with db.connect() as conn:
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({', '.join('?' for _ in tables)})", tables)


def wipe() -> None:
    """Efface toutes les données métier et les fichiers classés. Les comptes sont conservés."""
    db.init_db()
    _clear_tables()
    for folder in (config.DRIVE_DIR, config.OUTBOX_DIR):
        if folder.exists():
            shutil.rmtree(folder)
    config.ensure_dirs()


def _notify(title: str, desc: str, tag: str, created_at: str | None = None) -> None:
    color, tag_color = TAG_COLORS[tag]
    db.insert("notifications", {"title": title, "description": desc, "tag": tag, "color": color, "tag_color": tag_color,
                                "created_at": created_at or db.now_iso()})


def init_instance(organization: dict | None = None, reset: bool = False) -> None:
    """Instance vierge : profil de l'entreprise, arborescence, actualités de bienvenue."""
    if reset:
        wipe()
    db.init_db()
    config.ensure_dirs()
    if not db.fetch_one("SELECT id FROM profile WHERE id = 1"):
        db.insert("profile", {"id": 1, "created_at": db.now_iso()})
    if organization:
        services.update_profile(organization)
    if not db.fetch_one("SELECT COUNT(*) AS n FROM notifications")["n"]:
        for title, desc, tag in reversed(WELCOME_NOTIFICATIONS):  # la plus récente s'affiche en premier
            _notify(title, desc, tag)


def _supplier_documents() -> list[tuple]:
    ref = today()
    docs = []
    for m in range(1, ref.month + 1):  # abonnement mensuel Adobe, le 5 du mois
        d = ref.replace(month=m, day=5)
        if d <= ref:
            docs.append(("Adobe Systems France", "Abonnement Creative Cloud", 69.99, 0.20, (ref - d).days))
    start = add_months(ref.replace(day=1), -3)
    for i in range(4):  # coworking sur 4 mois
        d = add_months(start, i).replace(day=2)
        if d <= ref:
            docs.append(("La Ruche Coworking", "Abonnement coworking (poste fixe)", 180.00, 0.20, (ref - d).days))
    docs += [
        ("Figma France", "Licence Figma Professional (annuelle)", 135.00, 0.20, 270),
        ("OVHcloud", "Hébergement web et nom de domaine", 95.88, 0.20, 235),
        ("SNCF Voyageurs", "Billet Lyon–Paris, rendez-vous client", 72.73, 0.10, 205),
        ("LDLC", "Écran 27 pouces", 349.17, 0.20, 168),
        ("Imprimerie du Rhône", "Impression flyers salon", 240.00, 0.20, 128),
        ("SNCF Voyageurs", "Billet Lyon–Paris, atelier client", 72.73, 0.10, 22),
    ]
    return docs


def seed(reset: bool = False) -> bool:
    """Crée le jeu de démonstration. Sans `reset`, ne fait rien si des clients existent déjà."""
    db.init_db()
    if reset:
        wipe()
    elif not is_empty():
        return False
    config.ensure_dirs()
    ref = today()

    _clear_tables()
    db.insert("profile", {"id": 1, **PROFILE, "created_at": _stamp(2, 9, 12)})
    profile = services.get_profile()

    clients = {}
    for c in CLIENTS:
        row = services.create_client(c)
        db.update("clients", row["id"], {"created_at": _stamp(260)})
        clients[c["name"]] = services.get_client(row["id"])

    # ── Factures émises (numérotation chronologique, par année) ──
    seq: dict[int, int] = {}
    numbers: dict[str, str] = {}
    emails = []
    for client_name, title, lines, issued_ago, paid_ago, reminders, last_reminder_ago in sorted(INVOICES, key=lambda x: -x[3]):
        inv = services.create_invoice({
            "kind": "invoice", "client_id": clients[client_name]["id"], "title": title,
            "items": [{"description": d, "quantity": q, "unit_price": u} for d, q, u in lines],
        })
        issued = ref - timedelta(days=issued_ago)
        seq[issued.year] = seq.get(issued.year, 0) + 1
        number = f"CAFFEIN-{issued.year}-{seq[issued.year]:05d}"
        numbers[title] = number
        db.update("invoices", inv["id"], {
            "number": number, "status": "pending", "issued_at": issued.isoformat(),
            "due_date": (issued + timedelta(days=30)).isoformat(), "emailed_at": _stamp(issued_ago, 11),
            "emailed_to": clients[client_name]["email"], "created_at": _stamp(issued_ago, 10), "updated_at": _stamp(issued_ago, 11),
        })
        inv = services.get_invoice(inv["id"])
        target = services.invoice_pdf_target(inv)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render_invoice_pdf(inv, inv["client"], profile))
        db.update("invoices", inv["id"], {"pdf_path": str(target)})
        inv = services.get_invoice(inv["id"])
        subject, html = invoice_email(inv, inv["client"], profile, inv["portal_url"])
        emails.append({"kind": "invoice", "to_email": inv["client"]["email"], "subject": subject, "html": html,
                       "attachment_name": target.name, "invoice_id": inv["id"], "created_at": _stamp(issued_ago, 11)})
        if paid_ago is not None:
            services.mark_paid(inv["id"], _day(paid_ago))
            db.execute("UPDATE documents SET created_at = ? WHERE invoice_id = ?", (_stamp(paid_ago, 15), inv["id"]))
        if reminders:
            db.update("invoices", inv["id"], {"reminder_count": reminders, "last_reminder_at": _stamp(last_reminder_ago, 9),
                                              "last_reminder_tone": "gentle"})
            days_overdue = (ref - timedelta(days=last_reminder_ago) - (issued + timedelta(days=30))).days
            ctx = {"tone": "gentle", "tone_label": TONE_LABELS["gentle"], "sender_name": sender_name(profile),
                   "invoice_number": number, "amount_formatted": fmt_money(inv["total"]),
                   "due_date_formatted": fmt_date_long(inv["due_date"]), "days_overdue": days_overdue,
                   "client_name": inv["client"]["contact_name"], "recipient_email": inv["client"]["email"],
                   "portal_url": inv["portal_url"]}
            emails.append({"kind": "reminder", "to_email": inv["client"]["email"],
                           "subject": reminder_subject("gentle", number, days_overdue),
                           "html": reminder_email(ctx, reminder_template(ctx)), "invoice_id": inv["id"],
                           "created_at": _stamp(last_reminder_ago, 9), "meta": db.dumps({"tone": "gentle", "written_by": "modèle"})})

    # Un brouillon créé en langage naturel
    delivery = ref.replace(day=15) if ref.day < 15 else add_months(ref.replace(day=15), 1)
    services.create_invoice({
        "kind": "invoice", "client_id": clients["Atelier Nova"]["id"], "title": "Animation du logo",
        "items": [{"description": "Animation du logo (motion design, 3 formats)", "quantity": 1, "unit_price": 800}],
        "source_text": "Animation logo pour Jean Martin, 800 €, livraison le 15",
        "delivery_date": delivery.isoformat(),
    })

    # ── Devis ──
    quote_seq: dict[int, int] = {}
    for client_name, title, lines, issued_ago, status in sorted(QUOTES, key=lambda x: -x[3]):
        q = services.create_invoice({"kind": "quote", "client_id": clients[client_name]["id"], "title": title,
                                     "items": [{"description": d, "quantity": qt, "unit_price": u} for d, qt, u in lines]})
        issued = ref - timedelta(days=issued_ago)
        quote_seq[issued.year] = quote_seq.get(issued.year, 0) + 1
        db.update("invoices", q["id"], {"number": f"DEVIS-{issued.year}-{quote_seq[issued.year]:05d}", "status": status,
                                        "issued_at": issued.isoformat(), "due_date": (issued + timedelta(days=30)).isoformat(),
                                        "created_at": _stamp(issued_ago, 9)})
        q = services.get_invoice(q["id"])
        target = services.invoice_pdf_target(q)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render_invoice_pdf(q, q["client"], profile))
        db.update("invoices", q["id"], {"pdf_path": str(target)})

    # ── Documents fournisseurs (TVA déductible) avec leurs PDF ──
    me = {"name": profile["company"], "contact_name": profile["full_name"], "address": profile["address"],
          "zip_code": profile["zip_code"], "city": profile["city"], "email": profile["email"]}
    for i, (supplier, resume, ht, rate, days_ago) in enumerate(_supplier_documents()):
        address, categorie = SUPPLIERS[supplier]
        d = ref - timedelta(days=days_ago)
        folder = config.FOLDERS["recues"] / slugify_name(supplier)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{slugify_name(supplier)}-{d.isoformat()}.pdf"
        street, city = address.split(", ", 1)
        pdf = render_supplier_invoice_pdf(
            {"company": supplier, "address": street, "city": city, "legal_mention": "SAS", "siret": f"4{i:02d} 222 333 0001{i % 10}"},
            me, f"F{d:%Y%m}-{1000 + i}", d.isoformat(), (d + timedelta(days=30)).isoformat(), [(resume, 1, ht)], rate)
        path.write_bytes(pdf)
        tva = round(ht * rate, 2)
        services.add_document({
            "date": d.isoformat(), "fournisseur": supplier.upper(), "ht": ht, "tva": tva, "ttc": round(ht + tva, 2),
            "categorie": categorie, "resume": resume[:50], "tva_type": "deductible", "echeance": (d + timedelta(days=30)).isoformat(),
            "file_path": path, "original_name": f"facture-{slugify_name(supplier).lower().replace(' ', '-')}.pdf",
            "source": "inbox", "extracted_by": "heuristique", "created_at": _stamp(days_ago, 14),
        })

    # ── Deux factures fournisseurs fraîchement déposées, traitées au démarrage ──
    inbox_docs = [
        ("Free Pro", "8 rue de la Ville l'Évêque", "75008 Paris", "facture-free-pro.pdf", "Forfait Freebox Pro", 33.25, 0.20, 3),
        ("Canva Pty Ltd", "110 Kippax Street", "Sydney NSW 2010", "Canva_invoice.pdf", "Abonnement Canva Pro", 11.00, 0.20, 1),
    ]
    for supplier, street, city, filename, desc, ht, rate, days_ago in inbox_docs:
        d = ref - timedelta(days=days_ago)
        pdf = render_supplier_invoice_pdf({"company": supplier, "address": street, "city": city, "siret": "999 888 777 00011"},
                                          me, f"INV-{d:%y%m%d}", d.isoformat(), (d + timedelta(days=15)).isoformat(), [(desc, 1, ht)], rate)
        (config.INBOX_DIR / filename).write_bytes(pdf)

    # ── Actualités, emails, historique ──
    for title, desc, tag, days_ago in NOTIFICATIONS:
        _notify(title, desc, tag, _stamp(days_ago, 8))
    for e in emails:
        db.insert("emails", {"from_email": f"{sender_name(profile)} <{config.EMAIL_FROM_ADDRESS}>", "status": "simulated",
                             "meta": "{}", **e})
    welcome_subject, welcome_html = onboarding_email("welcome", profile["full_name"])
    db.insert("emails", {"kind": "onboarding", "to_email": profile["email"], "from_email": f"Caffein <{config.EMAIL_FROM_ADDRESS}>",
                         "subject": welcome_subject, "status": "simulated", "meta": "{}", "html": welcome_html,
                         "created_at": _stamp(2, 9, 13)})
    db.update("profile", 1, {"onboarding_step": 1})

    runs = [
        ("setup_drive", "event", "Arborescence vérifiée", 2, 9, False),
        ("auto_reminders", "schedule", "1 relance envoyée", 12, 9, True),
        ("send_invoice", "manual", f"Facture {numbers['Icônes sur mesure']} envoyée à ines@pixelandco.example (simulé)", 8, 11, True),
        ("process_inbox", "schedule", "1 document classé (ADOBE SYSTEMS FRANCE)", 5, 14, True),
        ("generate_pdf", "event", f"Facture {numbers['Bannières réseaux sociaux']} émise — PDF archivé", 5, 10, True),
        ("onboarding_emails", "event", f"Email d'onboarding envoyé : « {welcome_subject} »", 2, 9, True),
    ]
    for job_name, trigger, summary, days_ago, hour, notable in runs:
        db.insert("job_runs", {"job": job_name, "trigger": trigger, "status": "success", "summary": summary,
                               "details": db.dumps({"notable": notable, "seed": True}), "started_at": _stamp(days_ago, hour),
                               "finished_at": _stamp(days_ago, hour)})

    # Déclarations URSSAF passées déjà faites (sauf la dernière échue)
    for m in range(1, ref.month - 1):
        declared = datetime(ref.year, m + 1, 25, 18, 0, tzinfo=config.TIMEZONE)
        db.execute("INSERT OR REPLACE INTO declarations (period_key, declared_at) VALUES (?, ?)",
                   (f"{ref.year}-{m:02d}", declared.isoformat()))

    # ── Modules : la démonstration les active tous, chacun apporte ses données ──
    registry.enable_all()
    for module in registry.dependency_order():
        if module.seed_demo:
            module.seed_demo()
    return True
