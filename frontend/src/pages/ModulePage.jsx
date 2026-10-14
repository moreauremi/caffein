// SPDX-License-Identifier: AGPL-3.0-or-later
import { Navigate, useParams } from 'react-router-dom'
import { Lock } from 'lucide-react'
import EntityPage from '../components/entity/EntityPage'
import { EmptyState } from '../components/ui'
import { useLanguage } from '../context/LanguageContext'
import { useMeta } from '../context/MetaContext'
import { pagePath } from '../lib/meta'
import { COMPONENTS } from '../modules'

function NoAccess() {
  const { t } = useLanguage()
  return <div className="page"><EmptyState icon={Lock} title={t('nav.no_access')} /></div>
}

// Contenu d'une page de module : écran sur mesure du registre, ou écran généré pour une entité
export function PageContent({ module, page }) {
  if (page.component) {
    const Component = COMPONENTS[page.component]
    return Component ? <Component module={module} page={page} /> : <NoAccess />
  }
  if (page.entity) return <EntityPage key={page.entity} entityKey={page.entity} />
  return <NoAccess />
}

// /:module/:page — le module et la page doivent figurer dans la description de l'espace de l'utilisateur
export default function ModulePage() {
  const { moduleSlug, pageSlug } = useParams()
  const { moduleBySlug } = useMeta()
  const module = moduleBySlug(moduleSlug)
  if (!module) return <NoAccess />
  if (!pageSlug) return <Navigate to={pagePath(module, module.pages[0])} replace />
  const page = module.pages.find((p) => p.slug === pageSlug && !p.path)
  if (!page) return <NoAccess />
  return <PageContent module={module} page={page} />
}

// « / » : la page d'accueil (tableau de bord), sinon la première page accessible
export function HomeIndex() {
  const { modules } = useMeta()
  for (const module of modules) {
    const page = module.pages.find((p) => p.path === '/')
    if (page) return <PageContent module={module} page={page} />
  }
  const first = modules[0]
  return first ? <Navigate to={pagePath(first, first.pages[0])} replace /> : <NoAccess />
}
