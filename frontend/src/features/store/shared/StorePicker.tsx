import { Select } from '@/components/ui'
import { useStoreOptions, type StoreOption, type StoreType } from '@/api/store'

export interface StorePickerProps {
  value: number | null
  onChange: (id: number | null, store: StoreOption | null) => void
  /** Only the stores of this project. */
  projectId?: number
  /** Only stores of this type. */
  type?: StoreType
  /** Leave this one out (the other end of a transfer). */
  excludeId?: number
  placeholder?: string
  disabled?: boolean
  id?: string
  'aria-invalid'?: boolean
}

const TYPE: Record<StoreType, string> = { CENTRAL: 'central', SITE: 'site', YARD: 'yard' }

/** "CS01 - Central Store (central)": the store as the list shows it. */
export function storeLabel(s: Pick<StoreOption, 'code' | 'name' | 'type'>): string {
  return `${s.code} - ${s.name}${TYPE[s.type] ? ` (${TYPE[s.type]})` : ''}`
}

/** A drop-down of the stores this person may work in. */
export function StorePicker({ value, onChange, projectId = 0, type, excludeId, placeholder = 'Choose a store', disabled, id, ...rest }: StorePickerProps) {
  const q = useStoreOptions(projectId)
  const stores = (q.data ?? []).filter((s) => (!type || s.type === type) && s.id !== excludeId)
  const none = !q.isPending && !stores.length
  return (
    <Select
      id={id}
      aria-invalid={rest['aria-invalid']}
      disabled={disabled || q.isPending}
      placeholder={q.isPending ? 'Loading stores...' : none ? 'No store you work in' : placeholder}
      value={value ?? ''}
      options={stores.map((s) => ({ value: s.id, label: storeLabel(s) }))}
      onChange={(e) => {
        const chosen = e.target.value ? Number(e.target.value) : null
        onChange(chosen, stores.find((s) => s.id === chosen) ?? null)
      }}
    />
  )
}
