import { Link } from 'react-router-dom'
import { Card } from '@/components/ui'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { OldStoreCard } from './OldStore'
import { SLICES, StoreShell } from './StoreShell'

/** The Store front page: a card for each part this person may open. */
export default function StorePage() {
  const { can } = useSession()
  return (
    <StoreShell slice={null}>
      <OldStoreCard />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SLICES.filter((s) => can(storePerm(s.slice))).map((s) => (
          <Link key={s.slice} to={`/store/hub/${s.slice}`}>
            <Card className="h-full p-5 transition-colors hover:bg-accent">
              <h2 className="text-lg font-semibold">{s.label}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{s.blurb}</p>
            </Card>
          </Link>
        ))}
      </div>
    </StoreShell>
  )
}
