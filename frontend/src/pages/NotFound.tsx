import { ErrorPage } from '@/components/errors/ErrorPage'

/** An address the app does not have: the 404 page. */
export default function NotFound() {
  return <ErrorPage kind="notFound" code="YE-DATA-01" />
}
