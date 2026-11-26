import { PageHeader } from '@/components/layout/PageHeader'
import { StoreMore } from './StoreSteps'

/** The store's screens that are not one of the numbered steps: kept off the menu so it stays short, one click away here. */
export default function StoreMorePage() {
  return (
    <div>
      <PageHeader eyebrow="Store" title="More" description="Other store work, used less often. Click one to open it." />
      <StoreMore bare />
    </div>
  )
}
