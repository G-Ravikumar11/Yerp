import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui'

/** The owner's delete, as a quiet icon at the end of a row. It does not open the row. */
export function DeleteButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <span onClick={(e) => e.stopPropagation()}>
      <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" aria-label={`Delete ${label}`} onClick={onClick}>
        <Trash2 />
      </Button>
    </span>
  )
}
