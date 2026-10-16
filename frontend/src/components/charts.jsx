// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Table2, BarChart3 } from 'lucide-react'
import { useLanguage } from '../context/LanguageContext'
import { compactMoney, money } from '../lib/format'

// Spécifications : barres ≤ 24 px, extrémité arrondie 4 px (carrée à la base), 2 px d'écart,
// grille fine et discrète, info-bulle au survol, légende dès 2 séries, vue tableau.
const axisTick = { fill: 'var(--muted)', fontSize: 12 }

function ChartTooltip({ active, payload, label, series, language }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div style={{ fontWeight: 650, marginBottom: 6 }}>{label}</div>
      {series.map((s) => {
        const item = payload.find((p) => p.dataKey === s.key)
        return (
          <div className="row" key={s.key}>
            <span className="row" style={{ gap: 7 }}><span className="key" style={{ background: s.color }} />{s.label}</span>
            <span className="mono">{money(item?.value, language)}</span>
          </div>
        )
      })}
    </div>
  )
}

export function BarsChart({ data, xKey, series, height = 260, title, xLabel }) {
  const { t, language } = useLanguage()
  const [table, setTable] = useState(false)
  return (
    <div>
      <div className="row between wrap" style={{ marginBottom: 14 }}>
        {series.length > 1 ? (
          <div className="legend">
            {series.map((s) => <span key={s.key}><span className="key" style={{ background: s.color }} />{s.label}</span>)}
          </div>
        ) : <span />}
        <button className="btn sm ghost" onClick={() => setTable((v) => !v)} aria-pressed={table}>
          {table ? <BarChart3 size={15} /> : <Table2 size={15} />}
          {table ? t('chart.show_chart') : t('chart.show_table')}
        </button>
      </div>
      {table ? (
        <div className="table-wrap">
          <table className="table" aria-label={title}>
            <thead><tr><th>{xLabel || t('chart.period')}</th>{series.map((s) => <th key={s.key} className="right">{s.label}</th>)}</tr></thead>
            <tbody>
              {data.map((row) => (
                <tr key={row[xKey]}>
                  <td>{row[xKey]}</td>
                  {series.map((s) => <td key={s.key} className="right mono">{money(row[s.key], language)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ width: '100%', height }} role="img" aria-label={title}>
          <ResponsiveContainer>
            <BarChart data={data} barGap={2} barCategoryGap="22%" margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
              <XAxis dataKey={xKey} tick={axisTick} tickLine={false} axisLine={{ stroke: 'var(--border)' }} interval="preserveStartEnd" />
              <YAxis tick={axisTick} tickLine={false} axisLine={false} width={56} tickFormatter={(v) => compactMoney(v, language)} />
              <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<ChartTooltip series={series} language={language} />} />
              {series.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
