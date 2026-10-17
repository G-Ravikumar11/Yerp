import { StoreShell } from '../StoreShell'

/** Store > Reports. Owned by P5: replace the body, keep the shell. Routes under /store/hub/reports/* land here, so
 * add your own sub-routes with <Routes> inside this component rather than in src/routes.tsx. */
export default function ReportsIndex() {
  // TODO(P5)
  return (
    <StoreShell slice="reports">
      <p className="text-sm text-muted-foreground">Nothing here yet.</p>
    </StoreShell>
  )
}
