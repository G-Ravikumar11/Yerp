import { useMemo, useState } from 'react'
import { Button, Modal } from '@/components/ui'
import { DataGrid, type Column } from '@/components/grid'
import { createItems, itemKeys, type ItemInput, type ItemKind, type ItemVocabulary } from '@/api/items'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'

interface NewItem {
  kind: ItemKind
  item_code: string
  item_name: string
  item_type: string
  units_of_measure: string
  hsn_code: string
  item_tax_type: string
}

const blank = (): NewItem => ({ kind: 'RM', item_code: '', item_name: '', item_type: 'Purchased', units_of_measure: 'Nos', hsn_code: '', item_tax_type: '18%' })

/** The code alphabet leaves out I, L, O and U; a code is exactly six of the rest. */
const CODE = /^[0-9A-HJKMNP-TV-Z]{6}$/i

/**
 * Many items typed at once, the way they are on a sheet. The code is issued
 * when it is left blank, so nobody invents one; the pickers only hold what
 * exists, so a unit that is not a unit cannot be entered.
 */
export function AddItemsModal({ open, onOpenChange, vocab }: { open: boolean; onOpenChange: (o: boolean) => void; vocab: ItemVocabulary | undefined }) {
  const [rows, setRows] = useState<NewItem[]>([])

  const columns = useMemo<Column<NewItem>[]>(
    () => [
      { id: 'kind', header: 'Kind', type: 'select', width: 150, options: [{ value: 'RM', label: 'Raw material' }, { value: 'FG', label: 'Finished good' }] },
      {
        id: 'item_code',
        header: 'Code',
        hint: 'Blank: issued for you',
        width: 130,
        mono: true,
        placeholder: 'Auto',
        validate: (v) => (CODE.test(String(v)) ? null : 'A code is exactly six characters, and never I, L, O or U'),
      },
      { id: 'item_name', header: 'Name', hint: 'What is it?', width: 300, required: true, placeholder: 'Cement OPC 53, 50 kg bag' },
      { id: 'item_type', header: 'Type', type: 'select', width: 130, options: vocab?.item_types ?? ['Purchased', 'Service'] },
      { id: 'units_of_measure', header: 'Unit', type: 'select', width: 110, options: vocab?.units ?? ['Nos'] },
      { id: 'hsn_code', header: 'HSN / SAC', width: 120, mono: true },
      { id: 'item_tax_type', header: 'Tax', type: 'select', width: 100, options: vocab?.tax_rates ?? ['18%'] },
    ],
    [vocab],
  )

  const save = useAction(
    (items: ItemInput[]) => createItems(items),
    {
      invalidate: [itemKeys.all],
      onSuccess: () => {
        setRows([])
        onOpenChange(false)
      },
    },
  )

  const ready = rows.filter((r) => r.item_name.trim())

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Add items"
      description="Type, or paste a block from Excel. Codes are issued for you - change one only to match a scheme you already use."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            onClick={() => {
              if (!ready.length) return toast.error('Give at least one item a name.')
              save.mutate(ready.map((r) => ({ ...r, item_code: r.item_code.trim().toUpperCase() })))
            }}
          >
            Save {ready.length || ''} item{ready.length === 1 ? '' : 's'}
          </Button>
        </>
      }
    >
      <DataGrid aria-label="New items" columns={columns} rows={rows} onRowsChange={(next) => setRows(next)} newRow={blank} minRows={6} maxHeight={340} />
    </Modal>
  )
}
