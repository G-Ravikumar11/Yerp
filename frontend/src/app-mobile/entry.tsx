import { lazy, type ElementType } from 'react'
import { AppShell as WebShell } from '@/components/layout/AppShell'
import WebHome from '@/features/dashboard/HomePage'
import { SCREENS as WEB_SCREENS, type Screen } from '@/routes'
import { appUi } from './gate'

/**
 * The one place the website's frame, front page and screen list are swapped for the phone app's.
 *
 * App.tsx takes `AppShell`, `HomePage` and `SCREENS` from here instead of from their own files. In the website's build
 * `__MOBILE_UI__` is false, so each is simply the website's own, and the lazy imports below are removed from the
 * bundle, which then has none of the phone layout. In the installed app they are the phone's. Everything that is
 * different about the phone app is therefore in this folder, and App.tsx never needs to change for it.
 */
const phone = __MOBILE_UI__ && appUi()

const MobileShell = __MOBILE_UI__ ? lazy(() => import('./MobileShell')) : null
const TodayPage = __MOBILE_UI__ ? lazy(() => import('./TodayPage')) : null
const ProjectsCards = __MOBILE_UI__ ? lazy(() => import('./ProjectsCards')) : null
const MorePage = __MOBILE_UI__ ? lazy(() => import('./MorePage')) : null
const ApprovalsCards = __MOBILE_UI__ ? lazy(() => import('./ApprovalsCards')) : null

export const AppShell: ElementType = phone && MobileShell ? MobileShell : WebShell
export const HomePage: ElementType = phone && TodayPage ? TodayPage : WebHome

/** The website's screens; in the phone app the project list and the approvals are cards, and /more is added. */
export const SCREENS: Screen[] =
  phone && ProjectsCards && ApprovalsCards && MorePage
    ? [
        ...WEB_SCREENS.filter((s) => s.path !== '/projects' && s.path !== '/approvals'),
        { path: '/projects', Component: ProjectsCards },
        { path: '/approvals', Component: ApprovalsCards },
        { path: '/more', Component: MorePage },
      ]
    : WEB_SCREENS
