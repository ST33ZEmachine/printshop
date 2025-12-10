const API_URL = import.meta.env.VITE_API_URL || 'https://trello-orders-api-kspii3btya-uc.a.run.app';

export interface MonthlyRevenueByBusinessLine {
  year_month: string;
  business_line: string;
  revenue: number;
  order_count: number;
}

export interface TopCustomer {
  purchaser: string;
  total_revenue: number;
  order_count: number;
  line_item_count: number;
}

export interface RevenueTrend {
  year_month: string;
  total_revenue: number;
  order_count: number;
  line_item_count: number;
}

export interface OrderStatus {
  status: string;
  order_count: number;
}

export interface MaterialBreakdown {
  material: string;
  total_revenue: number;
  order_count: number;
  line_item_count: number;
}

async function fetchData<T>(endpoint: string): Promise<T[]> {
  const response = await fetch(`${API_URL}${endpoint}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${endpoint}: ${response.statusText}`);
  }
  const data = await response.json();
  return data.data || [];
}

export const api = {
  getMonthlyRevenueByBusinessLine: () =>
    fetchData<MonthlyRevenueByBusinessLine>('/api/dashboard/monthly-revenue-by-business-line'),
  
  getTopCustomers: (limit: number = 20) =>
    fetchData<TopCustomer>(`/api/dashboard/top-customers?limit=${limit}`),
  
  getRevenueTrends: () =>
    fetchData<RevenueTrend>('/api/dashboard/revenue-trends'),
  
  getOrderStatus: () =>
    fetchData<OrderStatus>('/api/dashboard/order-status'),
  
  getMaterialBreakdown: (limit: number = 20) =>
    fetchData<MaterialBreakdown>(`/api/dashboard/material-breakdown?limit=${limit}`),
};
