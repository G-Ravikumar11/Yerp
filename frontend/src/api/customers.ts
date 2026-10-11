import { useQuery } from '@tanstack/react-query'
import { get, post, put } from '@/lib/api'

export interface Customer {
  id: number
  code: string
  name: string
  contact_person: string
  email: string
  phone_number: string
  gstin: string
  pan: string
  address: string
  city: string
  state: string
  pincode: string
  notes: string
  projects?: number
}

export type CustomerInput = Omit<Customer, 'id' | 'code' | 'projects'>

export const customerKeys = { all: ['customers'] as const, list: (q: string) => ['customers', 'list', q] as const }

export const useCustomers = (q: string) =>
  useQuery({ queryKey: customerKeys.list(q), queryFn: async () => (await get<{ customers: Customer[] }>(`/api/customers?q=${encodeURIComponent(q)}`)).customers ?? [], placeholderData: (prev) => prev })

export const createCustomer = (c: CustomerInput) => post<{ message: string }>('/api/customers', c)
export const updateCustomer = (id: number, c: CustomerInput) => put<{ message: string }>(`/api/customers/${id}`, c)
