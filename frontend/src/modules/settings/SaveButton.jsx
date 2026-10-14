// SPDX-License-Identifier: AGPL-3.0-or-later
import { Save } from 'lucide-react'
import { Spinner } from '../../components/ui'
import { useLanguage } from '../../context/LanguageContext'

export default function SaveButton({ onClick, disabled, saving }) {
  const { t } = useLanguage()
  return (
    <button type="button" className="btn primary" onClick={onClick} disabled={disabled || saving}>
      {saving ? <Spinner /> : <Save size={16} />} {t('common.save')}
    </button>
  )
}
