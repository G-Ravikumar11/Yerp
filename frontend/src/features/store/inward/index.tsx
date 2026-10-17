import { StoreShell } from '../StoreShell'

/** Store > Inward. Owned by P2: replace the body, keep the shell. Routes under /store/hub/inward/* land here, so
 * add your own sub-routes with <Routes> inside this component rather than in src/routes.tsx. */
export default function InwardIndex() {
  // TODO(P2)
  return (
    <StoreShell slice="inward">
      <p className="text-sm text-muted-foreground">Nothing here yet.</p>
    </StoreShell>
  )
}
