// SPDX-License-Identifier: AGPL-3.0-or-later
// Formulaires génériques : valeurs initiales et données envoyées au serveur, d'après la description de l'entité.

export function editableFields(fields) {
  return fields.filter((f) => !f.readonly)
}

// Valeurs initiales d'une ligne : celles déclarées par le serveur
export function blankLine(child) {
  const line = {}
  for (const field of editableFields(child.fields)) line[field.name] = field.default ?? (field.type === 'bool' ? false : null)
  return line
}

// Formulaire d'une fiche : valeurs enregistrées, ou valeurs par défaut (+ préremplissage depuis l'adresse)
export function initialForm(entity, row, prefill = {}) {
  const form = {}
  for (const field of editableFields(entity.fields)) {
    if (row) {
      form[field.name] = row[field.name] ?? null
      if (field.type === 'ref') form[`${field.name}__label`] = row[`${field.name}__label`] ?? null
    } else {
      const preset = prefill[field.name]
      form[field.name] = preset !== undefined ? preset : (field.default ?? (field.type === 'bool' ? false : null))
    }
  }
  return form
}

export function initialChildren(entity, row) {
  const out = {}
  for (const child of entity.children) {
    out[child.key] = row ? (row[child.key] || []).map((line) => {
      const clean = {}
      for (const field of editableFields(child.fields)) {
        clean[field.name] = line[field.name] ?? null
        if (field.type === 'ref') clean[`${field.name}__label`] = line[`${field.name}__label`] ?? null
      }
      return clean
    }) : []
  }
  return out
}

// Données envoyées : seulement les champs saisissables (le serveur ignore le reste et calcule les autres)
export function buildPayload(entity, form, children) {
  const payload = {}
  for (const field of editableFields(entity.fields)) payload[field.name] = form[field.name] ?? null
  for (const child of entity.children) {
    const fields = editableFields(child.fields)
    payload[child.key] = (children[child.key] || []).map((line) => Object.fromEntries(fields.map((f) => [f.name, line[f.name] ?? null])))
  }
  return payload
}
