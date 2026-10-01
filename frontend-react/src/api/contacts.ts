import { useQuery } from '@tanstack/react-query'
import { del, get, post, put } from '@/lib/api'

export const contactKeys = { all: ['contacts'] as const }

export interface Contact {
  id: number
  name: string
  email: string
  phone_number: string
  contact_person: string
  gstin: string
  address: string
  city: string
  state: string
  pincode: string
}
export type ContactInput = Omit<Contact, 'id'>

export const useContacts = () => useQuery({ queryKey: contactKeys.all, queryFn: () => get<Contact[]>('/api/contacts') })
export const createContact = (b: ContactInput) => post<{ message?: string }>('/api/contacts', b)
export const updateContact = (id: number, b: ContactInput) => put<{ message?: string }>(`/api/contacts/${id}`, b)
export const deleteContact = (id: number) => del<{ message?: string }>(`/api/contacts/${id}`)
