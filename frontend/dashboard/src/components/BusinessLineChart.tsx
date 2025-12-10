import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from 'recharts'
import { MonthlyRevenueByBusinessLine } from '../lib/api'

interface Props {
  data: MonthlyRevenueByBusinessLine[]
}

const formatCurrency = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export default function BusinessLineChart({ data }: Props) {
  const lines = ['Signage', 'Printing', 'Engraving']
  const colors: Record<string, string> = {
    Signage: '#6366f1',
    Printing: '#22c55e',
    Engraving: '#f97316',
  }

  const aggregated = Object.values(
    data.reduce<Record<string, any>>((acc, curr) => {
      const key = curr.year_month
      if (!acc[key]) acc[key] = { year_month: key }
      acc[key][curr.business_line] = curr.revenue
      return acc
    }, {})
  ).sort((a, b) => (a.year_month < b.year_month ? -1 : 1))

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={aggregated} margin={{ left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="year_month" tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={formatCurrency} tick={{ fontSize: 12 }} width={90} />
          <Tooltip formatter={(value: any) => formatCurrency(value as number)} labelFormatter={(label) => `Month: ${label}`} />
          <Legend />
          {lines.map((line) => (
            <Area
              key={line}
              type="monotone"
              dataKey={line}
              stroke={colors[line]}
              fill={colors[line]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
