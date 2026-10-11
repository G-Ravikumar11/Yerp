import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { api, clickText, fill, launch, open, setValue, signIn, toastsGone, waitForToast } from './lib.mjs'

// Settings: the owner's company, paper, rules, access and alerts.
const { page, check, done } = await launch({ allow: [/^400 (POST|PUT) .api.(settings|approval-rules)/] })
await signIn(page)
const stamp = Date.now().toString().slice(-6)
const main = () => page.$eval('main', (e) => e.textContent.replace(/\s+/g, ' ').trim())
const tab = async (label) => { await clickText(page, '[role=tab]', label); await new Promise((r) => setTimeout(r, 400)) }
const save = async (button, toast) => { await clickText(page, 'main button', button); await waitForToast(page, toast); await toastsGone(page) }

await open(page, '/settings')
await page.waitForSelector('#co-name')

// --- Company ---------------------------------------------------------------------------------------
await fill(page, '#co-web', `https://example${stamp}.in`)
await fill(page, '#co-phone', `98480${stamp}`)
await save('Save company details', 'Company details saved')
const got = (await api(page, 'GET', '/api/settings')).data
check('the website and phone are saved', got.company_website === `https://example${stamp}.in` && got.company_phone === `98480${stamp}`, JSON.stringify(got).slice(0, 120))
await fill(page, '[aria-label="Bank 1 name"]', 'State Bank')
await fill(page, '[aria-label="Bank 1 account number"]', `5500${stamp}`)
await save('Save company details', 'Company details saved')
check('a bank account is saved', JSON.parse((await api(page, 'GET', '/api/settings')).data.bank_details)[0].account_number === `5500${stamp}`)
await fill(page, '#co-gstin', 'NOT-A-GSTIN')
await clickText(page, 'main button', 'Save company details')
await waitForToast(page, 'GSTIN')
check('a bad GSTIN is refused with the reason', true)
await toastsGone(page)

// A logo chosen from the device
const png = join(tmpdir(), `logo${stamp}.png`)
writeFileSync(png, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9Qz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC', 'base64'))
const input = await page.$('input[aria-label="Choose logo"]')
await input.uploadFile(png)
await page.waitForSelector('img[alt=Logo]')
await save('Save logo', 'Logo saved')
check('the logo is kept', (await api(page, 'GET', '/api/client/logo')).data.logo_url.startsWith('data:image/png'))

// Tax rates
await page.waitForSelector('[aria-label="Tax rate 1 name"]')
const before = (await api(page, 'GET', '/api/tax-rates')).data.length
await clickText(page, 'main button', 'Add a rate')
await fill(page, `[aria-label="Tax rate ${before + 1} name"]`, `Cess${stamp}`)
await fill(page, `[aria-label="Tax rate ${before + 1} percent"]`, '2.5')
await save('Save tax rates', 'Tax rates saved')
check('a new tax rate is saved', (await api(page, 'GET', '/api/tax-rates')).data.some((t) => t.name === `Cess${stamp}` && t.percent === 2.5))

// --- Documents ------------------------------------------------------------------------------------------
await tab('Documents')
await page.waitForSelector('[aria-label^="Edit letterhead"]')
await page.click('[aria-label^="Edit letterhead"]')
await page.waitForSelector('#lh-addr')
const firstUnit = (await api(page, 'GET', '/api/wo/business-units')).data.business_units[0]
if (firstUnit.gstin) await fill(page, '#lh-pan', firstUnit.gstin.slice(2, 12))
await fill(page, '#lh-addr', `Plot ${stamp}, Hyderabad`)
await clickText(page, '[role=dialog] button', 'Save letterhead')
await waitForToast(page, 'saved')
await toastsGone(page)
check('a letterhead edit is kept', (await api(page, 'GET', '/api/wo/business-units')).data.business_units.some((u) => u.address === `Plot ${stamp}, Hyderabad`))
await clickText(page, 'main button', 'Add a letterhead')
await page.waitForSelector('#lh-name')
await fill(page, '#lh-name', `Unit ${stamp}`)
await clickText(page, '[role=dialog] button', 'Save letterhead')
await waitForToast(page, 'added')
await toastsGone(page)
check('a new letterhead is added', (await api(page, 'GET', '/api/wo/business-units')).data.business_units.some((u) => u.name === `Unit ${stamp}`))
await page.waitForSelector('#sig-prepared-name')
await fill(page, '#sig-prepared-name', `Qs ${stamp}`)
await save('Save signatures', 'Saved')
check('a signatory name is kept', (await api(page, 'GET', '/api/documents/signatories')).data.signatories.prepared.name === `Qs ${stamp}`)
await page.waitForSelector('[aria-label="Condition 1 text"]')
await fill(page, '[aria-label="Condition 1 text"]', `Payment within ${stamp} days.`)
await save('Save conditions', 'conditions saved')
check('own conditions are saved and marked as such', (await api(page, 'GET', '/api/wo/terms/library')).data.custom === true && (await main()).includes('Your own'))
await clickText(page, 'main button', 'Go back to the standard conditions')
await waitForToast(page, 'standard')
await toastsGone(page)
check('they can go back to the standard ones', (await api(page, 'GET', '/api/wo/terms/library')).data.custom === false)

// --- Approvals -------------------------------------------------------------------------------------------
await tab('Approvals')
await page.waitForSelector('#ar-below')
await fill(page, '#ar-below', '1500')
await fill(page, '#ar-above', '900000')
await save('Save approval rules', 'Approval rules saved')
const rules = (await api(page, 'GET', '/api/approval-rules')).data
check('the two limits are saved', rules.auto_below === 1500 && rules.finance_above === 900000, JSON.stringify(rules))
await fill(page, '#ar-above', '1000')
await clickText(page, 'main button', 'Save approval rules')
await waitForToast(page, 'finance limit')
check('a finance limit under the sign-off limit is refused', true)
await toastsGone(page)
check('who approves what is spelled out', (await main()).includes('Leave') && (await main()).includes('Master, last'))
const domainBefore = (await api(page, 'GET', '/api/hr/org-domain')).data.domain
await fill(page, '#org-domain', `qa${stamp}.example.in`)
await save('Save domain', 'domain saved')
check('the staff domain is saved', (await api(page, 'GET', '/api/hr/org-domain')).data.domain === `qa${stamp}.example.in`)
await api(page, 'PUT', '/api/hr/org-domain', { domain: domainBefore })

// --- People and access --------------------------------------------------------------------------------------
await tab('People & access')
await page.waitForSelector('table[aria-label=Team]')
await clickText(page, 'main button', 'Add a colleague')
await page.waitForSelector('#tm-email')
await fill(page, '#tm-name', 'Accounts Helper')
await fill(page, '#tm-email', `helper${stamp}@example.in`)
await clickText(page, '[role=dialog] button', 'Send invite')
await waitForToast(page, 'emailed')
await toastsGone(page)
const helperMail = `helper${stamp}@example.in`
const helper = (await api(page, 'GET', '/api/team')).data.members.find((m) => m.email === helperMail)
check('a colleague is invited', !!helper && helper.role === 'admin')
const teamRow = (e) => page.evaluate((mail, e) => [...document.querySelectorAll('table[aria-label=Team] tbody tr')].find((r) => r.textContent.includes(mail)).querySelectorAll('button')[e].click(), helperMail, e)
await page.waitForFunction((e) => document.querySelector('table[aria-label=Team]')?.textContent.includes(e), {}, helperMail)
await setValue(page, `[aria-label="Role of ${helperMail}"]`, 'viewer')
await waitForToast(page, 'Role changed')
await toastsGone(page)
check('their role is changed', (await api(page, 'GET', '/api/team')).data.members.find((m) => m.id === helper.id).role === 'viewer')
await teamRow(0)
await waitForToast(page, 'suspended')
await toastsGone(page)
check('they can be suspended', (await api(page, 'GET', '/api/team')).data.members.find((m) => m.id === helper.id).is_active === false)
await teamRow(1)
await clickText(page, '[role=alertdialog] button, [role=dialog] button', 'Remove')
await waitForToast(page, 'Removed')
await toastsGone(page)
check('and removed', !(await api(page, 'GET', '/api/team')).data.members.some((m) => m.id === helper.id))

// A subcontractor gets a portal login
const con = await api(page, 'POST', '/api/wo/contractors', { company_name: `Gang ${stamp}`, contact_person: 'Raju', email: `gang${stamp}@example.in`, phone_number: '9000000000', pan: '', gst_number: '' })
check('a gang exists to invite', con.status === 200, JSON.stringify(con.data).slice(0, 100))
await open(page, '/settings')
await tab('People & access')
await page.waitForSelector('table[aria-label="Partner logins"]')
await clickText(page, 'main button', 'Invite a partner')
await page.waitForSelector('#pa-party')
await page.waitForFunction((n) => [...document.querySelectorAll('#pa-party option')].some((o) => o.textContent === n), {}, `Gang ${stamp}`)
await setValue(page, '#pa-party', String(con.data.id))
await page.waitForFunction((e) => document.querySelector('#pa-email').value === e, {}, `gang${stamp}@example.in`)
check('choosing the gang fills in its contact', true)
await clickText(page, '[role=dialog] button', 'Send invite')
await waitForToast(page, 'invited')
await toastsGone(page)
await page.waitForSelector('input[aria-label="Invite link"]')
const pu = (await api(page, 'GET', '/api/portal-access')).data.users.find((u) => u.email === `gang${stamp}@example.in`)
check('the login exists and its link is shown to pass on', !!pu && pu.is_active)
await page.evaluate((e) => [...document.querySelectorAll('table[aria-label="Partner logins"] tbody tr')].find((r) => r.textContent.includes(e)).querySelectorAll('button')[1].click(), `gang${stamp}@example.in`)
await waitForToast(page, 'no longer')
await toastsGone(page)
check('it can be turned off', (await api(page, 'GET', '/api/portal-access')).data.users.find((u) => u.id === pu.id).is_active === false)

// --- Alerts and data ---------------------------------------------------------------------------------------------
await tab('Alerts & data')
await page.waitForSelector('#al-emails')
await fill(page, '#al-emails', `boss${stamp}@example.in`)
const wasOn = (await api(page, 'GET', '/api/alerts/settings')).data.channels.money_in?.includes('email') ?? false
await page.click('input[aria-label="Money received by email"]')
await save('Save alerts', 'Alert settings saved')
const al = (await api(page, 'GET', '/api/alerts/settings')).data
check('alert addresses and channels are saved', al.emails.includes(`boss${stamp}@example.in`) && (al.channels.money_in?.includes('email') ?? false) === !wasOn, JSON.stringify(al.channels))
await clickText(page, 'main button', 'Send a test')
await waitForToast(page, '')
await toastsGone(page)
check('the activity log lists what was just done', await page.waitForFunction(() => document.querySelector('table[aria-label="Activity log"]')?.textContent.includes('team'), { timeout: 8000 }).then(() => true, () => false))
check('the backup shows what it holds and offers both downloads', (await main()).includes('Records and files') && (await main()).includes('records in'))
await done()
