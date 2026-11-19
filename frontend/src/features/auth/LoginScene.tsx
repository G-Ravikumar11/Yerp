import type { CSSProperties, ReactNode } from 'react'
import './login-scene.css'

const asset = (path: string) => `${import.meta.env.BASE_URL}${path}`

/**
 * The sign-in page's frame: warm paper, the building under construction with its crane and clouds on the left, the
 * company's logo at the top left, and the form on the right. Only the login page uses it; the other sign-in style
 * screens keep AuthLayout.
 */
export function LoginScene({ logo, logoAlt, title, subtitle, children }: { logo: string; logoAlt: string; title: string; subtitle: string; children: ReactNode }) {
  return (
    <main className="login-scene" style={{ '--login-grain': `url(${asset('site/img/grain.png')})` } as CSSProperties}>
      <img src={asset('brand/yalavarti-logo.png')} alt="Yalavarti Infra Projects" className="ls-brand" />
      <div className="ls-art" aria-hidden>
        <img src={asset('brand/login-architecture.jpg')} alt="" />
      </div>
      <img src={asset('brand/login-clouds.webp')} alt="" aria-hidden className="ls-cloud ls-cloud-c" />
      <img src={asset('brand/login-clouds.webp')} alt="" aria-hidden className="ls-cloud ls-cloud-b" />
      <img src={asset('brand/login-clouds.webp')} alt="" aria-hidden className="ls-cloud ls-cloud-a" />
      <div className="ls-panel">
        <div className="ls-form">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-5 grid size-24 place-items-center overflow-hidden rounded-2xl bg-white shadow-[0_8px_24px_-12px_rgb(31_42_61/0.35)] ring-1 ring-black/5">
              <img src={logo} alt={logoAlt} className="size-full object-contain p-2" />
            </div>
            <h1 className="text-[2rem] font-bold leading-tight text-foreground">{title}</h1>
            <p className="mt-1.5 text-lg text-muted-foreground">{subtitle}</p>
          </div>
          {children}
        </div>
      </div>
    </main>
  )
}
