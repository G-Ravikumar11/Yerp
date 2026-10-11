import { useRef } from 'react'
import { Button, Label } from '@/components/ui'
import { toast } from '@/stores/toast'

/** A picture chosen from the device, shrunk to fit, as a PNG data URL. White can be made see-through (a signature). */
export function readPicture(file: File, maxW: number, maxH: number, clearWhite: boolean): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!/^image\/(png|jpe?g|gif|webp|bmp)$/i.test(file.type)) return reject(new Error('Choose a picture - PNG or JPEG'))
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('That picture could not be read'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('That picture could not be read'))
      img.onload = () => {
        const scale = Math.min(1, maxW / img.width, maxH / img.height)
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(img.width * scale))
        canvas.height = Math.max(1, Math.round(img.height * scale))
        const ctx = canvas.getContext('2d')
        if (!ctx) return reject(new Error('That picture could not be read'))
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
        if (clearWhite) {
          const data = ctx.getImageData(0, 0, canvas.width, canvas.height)
          const d = data.data
          for (let i = 0; i < d.length; i += 4) if (d[i] > 225 && d[i + 1] > 225 && d[i + 2] > 225) d[i + 3] = 0
          ctx.putImageData(data, 0, 0)
        }
        resolve(canvas.toDataURL('image/png'))
      }
      img.src = String(reader.result)
    }
    reader.readAsDataURL(file)
  })
}

/** Show a logo, signature or seal, choose another, or take it off. */
export function PictureField({
  label,
  value,
  onChange,
  hint,
  maxW = 600,
  maxH = 240,
  clearWhite = false,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  hint?: string
  maxW?: number
  maxH?: number
  clearWhite?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const choose = async (file?: File) => {
    if (!file) return
    try {
      onChange(await readPicture(file, maxW, maxH, clearWhite))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'That picture could not be read')
    }
    if (input.current) input.current.value = ''
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <div className="flex flex-wrap items-center gap-3">
        <div className="grid h-[72px] w-44 place-items-center overflow-hidden rounded-lg border border-dashed border-input bg-white">
          {value ? <img src={value} alt={label} className="max-h-full max-w-full" /> : <span className="text-xs text-neutral-500">None</span>}
        </div>
        <input ref={input} type="file" accept="image/*" className="hidden" aria-label={`Choose ${label.toLowerCase()}`} onChange={(e) => void choose(e.target.files?.[0])} />
        <Button type="button" size="sm" variant="outline" onClick={() => input.current?.click()}>Choose picture</Button>
        {value && <Button type="button" size="sm" variant="ghost" onClick={() => onChange('')}>Remove</Button>}
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}
