import { PageHeader } from '@/components/layout/PageHeader'
import WebsiteTab from '@/features/settings/WebsiteTab'

/** The company website's own page in the staff app: the Master, and whoever has been given "Manage website". */
export default function WebsitePage() {
  return (
    <>
      <PageHeader eyebrow="Website" title="Company website" description="Its words, pictures, projects and openings - drafted here, checked in the preview, then published." />
      <WebsiteTab />
    </>
  )
}
