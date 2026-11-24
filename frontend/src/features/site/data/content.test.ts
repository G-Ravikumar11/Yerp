import { describe, expect, it } from 'vitest'
import { COMPANY, SITE } from './content'

// The backend's copy, from which each company's website sections are first filled in (services/website_content.py).
// Read from disk: it lives outside the frontend, where the app's own imports may not reach.
// The tests run from frontend/.
const SEED = '../backend/app/constants/website_content.json'

describe('the website content the database starts from', () => {
  it('is exactly the text the site carries, so the site looks the same before and after it arrives', async () => {
    const fsModule = 'node:fs'
    const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as { readFileSync: (p: string, enc: 'utf8') => string }
    // After changing content.ts, refresh the backend copy so a new company starts from the same words.
    expect(JSON.parse(readFileSync(SEED, 'utf8'))).toEqual(JSON.parse(JSON.stringify({ company: COMPANY, ...SITE })))
  })
})
