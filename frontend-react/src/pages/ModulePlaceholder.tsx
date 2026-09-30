import { motion } from 'framer-motion'
import { Construction, ExternalLink } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, SkeletonRows } from '@/components/ui'

/** Stands in for a module until it is ported, and says where to work meanwhile. */
export default function ModulePlaceholder({ title, group }: { title: string; group?: string }) {
  return (
    <>
      <PageHeader
        eyebrow={group}
        title={title}
        description="This screen is still on the current app. It moves across module by module, keeping every rule it has now."
        actions={
          <Button asChild>
            <a href="/app.html?old=1">
              Open in current app <ExternalLink />
            </a>
          </Button>
        }
      />
      <Card className="overflow-hidden">
        <div className="flex items-center gap-3 border-b border-border px-5 py-4">
          <span className="grid size-9 place-items-center rounded-lg bg-warning-soft text-warning">
            <Construction className="size-[18px]" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">Waiting to be ported</p>
            <p className="text-[13px] text-muted-foreground">The data grid and this module's API hooks land here.</p>
          </div>
          <Badge tone="neutral">Planned</Badge>
        </div>
        <motion.div initial={{ opacity: 0.4 }} animate={{ opacity: 1 }} transition={{ duration: 0.6 }}>
          <SkeletonRows rows={5} cols={5} />
        </motion.div>
      </Card>
    </>
  )
}
