// SPDX-License-Identifier: AGPL-3.0-or-later
// Mise en page commune des pages Paramètres
export default function SettingsPage({ title, lead, actions, children, wide = false }) {
  return (
    <div className={`page settings-page ${wide ? 'wide' : ''}`}>
      <div className="page-header">
        <div>
          <h1 className="page-title">{title}</h1>
          {lead ? <p className="page-sub">{lead}</p> : null}
        </div>
        {actions ? <div className="row wrap">{actions}</div> : null}
      </div>
      {children}
    </div>
  )
}

export function Field({ label, hint, children, full = false, htmlFor }) {
  return (
    <div className={`field ${full ? 'full' : ''}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}
