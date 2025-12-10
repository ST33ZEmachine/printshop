import { useEffect, useState } from 'react'
import { api, MonthlyRevenueByBusinessLine, TopCustomer, RevenueTrend, OrderStatus, MaterialBreakdown } from './lib/api'
import RevenueTrendsChart from './components/RevenueTrendsChart'
import BusinessLineChart from './components/BusinessLineChart'
import TopCustomersTable from './components/TopCustomersTable'
import OrderStatusChart from './components/OrderStatusChart'
import MaterialBreakdownChart from './components/MaterialBreakdownChart'

function App() {
  const [monthlyBusinessLine, setMonthlyBusinessLine] = useState<MonthlyRevenueByBusinessLine[]>([])
  const [topCustomers, setTopCustomers] = useState<TopCustomer[]>([])
  const [revenueTrends, setRevenueTrends] = useState<RevenueTrend[]>([])
  const [orderStatus, setOrderStatus] = useState<OrderStatus[]>([])
  const [materialBreakdown, setMaterialBreakdown] = useState<MaterialBreakdown[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const [mbl, tc, rt, os, mb] = await Promise.all([
          api.getMonthlyRevenueByBusinessLine(),
          api.getTopCustomers(10),
          api.getRevenueTrends(),
          api.getOrderStatus(),
          api.getMaterialBreakdown(10),
        ])
        setMonthlyBusinessLine(mbl)
        setTopCustomers(tc)
        setRevenueTrends(rt)
        setOrderStatus(os)
        setMaterialBreakdown(mb)
      } catch (err: any) {
        console.error(err)
        setError(err?.message || 'Failed to load dashboard data')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <p className="text-sm uppercase tracking-wide opacity-80">Bourquin Insights</p>
            <h1 className="text-2xl font-semibold">Operations Dashboard</h1>
          </div>
          <div className="flex items-center gap-3">
            <a
              className="text-sm font-medium hover:underline"
              href="/"
            >
              Chat
            </a>
            <span className="text-white/60">|</span>
            <span className="text-sm font-medium">Dashboard</span>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="grid gap-6 md:grid-cols-2">
            {[...Array(6)].map((_, idx) => (
              <div key={idx} className="h-48 rounded-xl bg-white shadow-sm animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-8">
            <section className="grid gap-6 md:grid-cols-2">
              <div className="rounded-xl bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">Revenue Trends</h2>
                  <p className="text-sm text-gray-500">Monthly performance</p>
                </div>
                <RevenueTrendsChart data={revenueTrends} />
              </div>

              <div className="rounded-xl bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">Business Lines</h2>
                  <p className="text-sm text-gray-500">Monthly split</p>
                </div>
                <BusinessLineChart data={monthlyBusinessLine} />
              </div>
            </section>

            <section className="grid gap-6 lg:grid-cols-3">
              <div className="rounded-xl bg-white p-5 shadow-sm lg:col-span-2">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">Top Customers</h2>
                  <p className="text-sm text-gray-500">By total revenue</p>
                </div>
                <TopCustomersTable data={topCustomers} />
              </div>

              <div className="rounded-xl bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">Order Status</h2>
                  <p className="text-sm text-gray-500">Counts by stage</p>
                </div>
                <OrderStatusChart data={orderStatus} />
              </div>
            </section>

            <section className="rounded-xl bg-white p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900">Material Breakdown</h2>
                <p className="text-sm text-gray-500">Top materials by revenue</p>
              </div>
              <MaterialBreakdownChart data={materialBreakdown} />
            </section>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
