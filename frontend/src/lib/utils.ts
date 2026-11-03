import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

/** Rupees the way the site reads them: lakhs and crores, two decimals. */
export function formatINR(value: number | null | undefined) {
  return inr.format(value ?? 0)
}

/** ₹1.2 Cr / ₹34.5 L - for tiles, where the full figure is noise. */
export function compactINR(value: number | null | undefined) {
  const v = value ?? 0
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(1)} K`
  return `${sign}₹${abs.toFixed(0)}`
}

/** A list already on screen, saved as a spreadsheet can open: no round trip to the server, so it is only ever what the
 * screen itself shows, already filtered. For a formatted document (an invoice, a bill), the server's own export is used instead. */
export function downloadCsv(filename: string, headers: string[], rows: (string | number)[][]) {
  const cell = (v: string | number) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csv = [headers, ...rows].map((r) => r.map(cell).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
