import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { OrderStatus } from '../lib/api'

interface Props {
  data: OrderStatus[]
}

export default function OrderStatusChart({ data }: Props) {
  const sorted = [...data].sort((a, b) => b.order_count - a.order_count)

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={sorted} layout="vertical" margin={{ left: 80 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis type="number" hide />
          <YAxis dataKey="status" type="category" tick={{ fontSize: 12 }} width={140} />
          <Tooltip />
          <Bar dataKey="order_count" fill="#6366f1" radius={[4, 4, 4, 4]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
