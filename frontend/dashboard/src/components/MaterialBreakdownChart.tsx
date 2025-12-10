import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { MaterialBreakdown } from '../lib/api'

interface Props {
  data: MaterialBreakdown[]
}

const formatCurrency = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export default function MaterialBreakdownChart({ data }: Props) {
  const top = [...data].sort((a, b) => b.total_revenue - a.total_revenue)

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={top} margin={{ left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="material" tick={{ fontSize: 12 }} interval={0} angle={-30} textAnchor="end" height={80} />
          <YAxis tickFormatter={formatCurrency} tick={{ fontSize: 12 }} width={90} />
          <Tooltip formatter={(value: any) => formatCurrency(value as number)} />
          <Bar dataKey="total_revenue" fill="#22c55e" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
