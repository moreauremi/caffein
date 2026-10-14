// SPDX-License-Identifier: AGPL-3.0-or-later
import { createElement } from 'react'
import { iconFor } from '../lib/icons'

// Icône désignée par son nom (envoyé par le serveur : modules, pages, chiffres clés, actions)
export default function NamedIcon({ name, size = 16, ...props }) {
  return createElement(iconFor(name), { size, 'aria-hidden': true, ...props })
}
