import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { Button } from '@/components/ui'

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center py-24 text-center">
      <span className="grid size-16 place-items-center rounded-2xl bg-muted text-muted-foreground">
        <Compass className="size-7" />
      </span>
      <h1 className="mt-6 text-2xl font-semibold">That page is not here</h1>
      <p className="mt-2 text-[15px] text-muted-foreground">The address may have changed, or the module has not been ported yet.</p>
      <Button asChild className="mt-6">
        <Link to="/">Back to the Command Center</Link>
      </Button>
    </div>
  )
}
