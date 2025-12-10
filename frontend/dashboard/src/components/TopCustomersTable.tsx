import { TopCustomer } from '../lib/api'

interface Props {
  data: TopCustomer[]
}

const formatCurrency = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export default function TopCustomersTable({ data }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm text-left">
        <thead>
          <tr className="text-gray-500 border-b">
            <th className="py-2 pr-4">Customer</th>
            <th className="py-2 pr-4 text-right">Revenue</th>
            <th className="py-2 pr-4 text-right">Orders</th>
            <th className="py-2 text-right">Line Items</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.purchaser} className="border-b last:border-0">
              <td className="py-2 pr-4 font-medium text-gray-900">{row.purchaser}</td>
              <td className="py-2 pr-4 text-right text-gray-900">{formatCurrency(row.total_revenue)}</td>
              <td className="py-2 pr-4 text-right text-gray-700">{row.order_count}</td>
              <td className="py-2 text-right text-gray-700">{row.line_item_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
