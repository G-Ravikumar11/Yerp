import { StoreShell } from '../StoreShell'

/** Store > Outward. Owned by P3: replace the body, keep the shell. Routes under /store/hub/outward/* land here, so
 * add your own sub-routes with <Routes> inside this component rather than in src/routes.tsx. */
export default function OutwardIndex() {
  // TODO(P3)
  return (
    <StoreShell slice="outward">
      <p className="text-sm text-muted-foreground">Nothing here yet.</p>
    </StoreShell>
  )
}
