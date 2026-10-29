import { Select } from '@/components/ui'
import { scanCode, scanWhat, useScanning, useStoreOptions, type StoreOption, type StoreType } from '@/api/store'
import { ApiError } from '@/lib/api'
import { toast } from '@/stores/toast'
import { ScanButton } from './Scanner'

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
  /** Offer a scan of a rack or yard-bay tag, which chooses its store (and tells onBin which bin it was). */
  scan?: boolean
  onBin?: (bin: { id: number; code: string }) => void
}

/** A drop-down of the stores this person may work in; scanning a rack or yard-bay tag chooses the store it is in. */
export function StorePicker({ value, onChange, projectId = 0, type, excludeId, placeholder = 'Choose a store', disabled, id, scan = true, onBin, ...rest }: StorePickerProps) {
  const q = useStoreOptions(projectId)
  const scanning = useScanning()
  const stores = (q.data ?? []).filter((s) => (!type || s.type === type) && s.id !== excludeId)
  const fromTag = async (code: string) => {
    try {
      const found = await scanCode(code)
      if (found.kind !== 'bin') return toast.error(`That is ${scanWhat(found)}, not a rack or yard-bay tag.`)
      const store = stores.find((s) => s.id === found.store.id)
      if (!store) return toast.error(`Bin ${found.bin.code} is in store ${found.store.code}, which cannot be chosen here.`)
      onChange(store.id, store)
      onBin?.(found.bin)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'The code could not be looked up.')
    }
  }
  const select = (
    <Select
      id={id}
      aria-invalid={rest['aria-invalid']}
      disabled={disabled || q.isPending}
      placeholder={placeholder}
      value={value ?? ''}
      options={stores.map((s) => ({ value: s.id, label: `${s.code} - ${s.name}` }))}
      onChange={(e) => {
        const chosen = e.target.value ? Number(e.target.value) : null
        onChange(chosen, stores.find((s) => s.id === chosen) ?? null)
      }}
    />
  )
  if (!scan || !scanning || disabled) return select
  return (
    <div className="flex gap-2">
      <div className="min-w-0 flex-1">{select}</div>
      <ScanButton title="Scan a rack or yard-bay tag" hint="The QR on the bin's tag chooses the store it is in." onCode={(c) => void fromTag(c)} />
    </div>
  )
}
