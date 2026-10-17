import { StoreShell } from '../StoreShell'

/** Store > Masters. Owned by P1: replace the body, keep the shell. Routes under /store/hub/masters/* land here, so
 * add your own sub-routes with <Routes> inside this component rather than in src/routes.tsx. */
export default function MastersIndex() {
  // TODO(P1)
  return (
    <StoreShell slice="masters">
      <p className="text-sm text-muted-foreground">Nothing here yet.</p>
    </StoreShell>
  )
}
