# SPDX-License-Identifier: AGPL-3.0-or-later
"""Description de l'espace d'un utilisateur pour l'interface : modules visibles, pages, entités et droits.
L'interface construit sa navigation et ses écrans génériques à partir de cette description."""

from __future__ import annotations

from . import entities
from . import modules as registry
from .modules import LEVEL_NAMES, NONE
from .permissions import levels_for


def build(user: dict) -> dict:
    levels = levels_for(user)
    is_admin = user.get("role") == "admin"
    modules, entity_meta = [], {}
    for module in registry.ordered():
        level = levels.get(module.key, NONE)
        if level == NONE:
            continue
        pages = []
        for page in module.pages:
            if (page.admin_only and not is_admin) or level < page.min_level:
                continue
            if page.entity:
                entity = entities.ENTITIES.get(page.entity)
                if entity is None or not registry.is_enabled(entity.module) or levels.get(entity.module, NONE) == NONE:
                    continue
            pages.append({"slug": page.slug, "label": page.label, "entity": page.entity, "component": page.component,
                          "path": page.path, "icon": page.icon})
        if not pages:
            continue
        modules.append({"key": module.key, "slug": module.slug, "label": module.label, "description": module.description,
                        "icon": module.icon, "core": module.core, "level": level, "level_name": LEVEL_NAMES[level],
                        "pages": pages})
        for entity in module.entities:
            entity_meta[entity.key] = entities.meta(entity, level)
    return {"modules": modules, "entities": entity_meta, "levels": levels, "is_admin": is_admin}
