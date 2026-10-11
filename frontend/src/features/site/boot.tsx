import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import SitePage from './SitePage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SitePage />
  </StrictMode>,
)
