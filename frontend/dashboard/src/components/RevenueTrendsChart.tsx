import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { RevenueTrend } from '../lib/api'

interface Props {
  data: RevenueTrend[]
}

const formatCurrency = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export default function RevenueTrendsChart({ data }: Props) {
  const sorted = [...data].sort((a, b) => (a.year_month < b.year_month ? -1 : 1))

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={sorted} margin={{ left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="year_month" tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={formatCurrency} tick={{ fontSize: 12 }} width={90} />
          <Tooltip formatter={(value: any) => formatCurrency(value as number)} labelFormatter={(label) => `Month: ${label}`} />
          <Area type="monotone" dataKey="total_revenue" stroke="#6366f1" fill="#6366f1" fillOpacity={0.2} strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
