// SPDX-License-Identifier: AGPL-3.0-or-later
import { useLanguage } from '../../context/LanguageContext'
import { LEVEL_NAMES } from '../../lib/meta'

// Niveau de droit sur un module : aucun, lecture, écriture, gestion
export default function LevelBadge({ level, inherited = false }) {
  const { t } = useLanguage()
  const cls = ['outline', 'info', 'good', 'accent'][level] || 'outline'
  return <span className={`badge ${cls} ${inherited ? 'inherited' : ''}`}>{t(`level.${LEVEL_NAMES[level] || 'none'}`)}</span>
}
