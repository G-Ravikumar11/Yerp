import { useQuery } from '@tanstack/react-query'
import { get, post, api } from '@/lib/api'
import { fileQuery, type FileFilter, type FileItem, type FileSummary } from './files'

export const drwKeys = { all: ['drawings'] as const }

export interface Drawing { id: number; number: string; title: string; discipline: string; current_revision: string; revisions: number; status: string; received_on: string; current_file_id: number | null }
export interface DrawingRegister { drawings: Drawing[]; disciplines: string[]; statuses: string[]; summary: { drawings: number; gfc: number; awaiting: number } }
export interface Revision { revision: string; status: string; received_on: string; received_from: string; remarks: string; file_id: number | null; current: boolean }
export interface DrawingHistory { id: number; number: string; title: string; current_revision: string; history: Revision[] }

export const useDrawings = (job: number) => useQuery({ queryKey: ['drawings', 'register', job], enabled: job > 0, queryFn: () => get<DrawingRegister>(`/api/jobs/${job}/drawings`) })
export const useDrawing = (id: number | null) => useQuery({ queryKey: ['drawings', 'one', id], enabled: !!id, queryFn: async () => (await get<{ drawing: DrawingHistory }>(`/api/drawings/${id}`)).drawing })
export const useJobPhotos = (job: number, kind: string, f: FileFilter, source: string) =>
  useQuery({ queryKey: ['drawings', 'photos', job, kind, f, source], enabled: job > 0, queryFn: () => get<{ photos: FileItem[]; summary: FileSummary }>(`/api/jobs/${job}/photos?kind=${encodeURIComponent(kind || 'photo,drawing,document')}${fileQuery({ ...f, kind: '' })}${source ? `&source=${encodeURIComponent(source)}` : ''}`) })

export const addDrawing = (job: number, b: { number: string; title: string; discipline: string }) => post<{ drawing: { id: number; number: string } }>(`/api/jobs/${job}/drawings`, b)
export const deleteDrawing = (id: number) => api<{ message: string }>(`/api/drawings/${id}`, { method: 'DELETE' })
export const setDrawingStatus = (id: number, status: string) => post<{ drawing: { number: string } }>(`/api/drawings/${id}/status`, { status })
/** A large photo of a sheet, made smaller in the browser before it goes up (the server keeps at most 2400 px anyway),
 *  so a 6 MB phone picture uploads as a few hundred KB. Anything else, or anything that does not shrink, goes as it is. */
async function shrink(file: File): Promise<File> {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < 800_000) return file
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const k = Math.min(1, 2400 / Math.max(bmp.width, bmp.height))
    const c = document.createElement('canvas')
    c.width = Math.round(bmp.width * k)
    c.height = Math.round(bmp.height * k)
    const g = c.getContext('2d')
    if (!g) return file
    g.fillStyle = '#fff'
    g.fillRect(0, 0, c.width, c.height)
    g.drawImage(bmp, 0, 0, c.width, c.height)
    bmp.close()
    const blob = await new Promise<Blob | null>((ok) => c.toBlob(ok, 'image/jpeg', 0.82))
    if (!blob || blob.size >= file.size) return file
    return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' })
  } catch {
    return file
  }
}

export async function addRevision(id: number, picked: File, b: { revision: string; status: string; received_on: string; received_from: string; remarks: string }) {
  const file = await shrink(picked)
  const fd = new FormData()
  fd.append('file', file, file.name)
  for (const [k, v] of Object.entries(b)) fd.append(k, v)
  return api<{ message: string }>(`/api/drawings/${id}/revisions`, { method: 'POST', body: fd })
}

export interface Plan3D {
  available: boolean
  message?: string
  reason?: string
  walls?: { x1: number; y1: number; x2: number; y2: number }[]
  rooms?: { name: string; x: number; y: number; w: number; h: number }[]
  openings?: { type: 'door' | 'window'; x: number; y: number }[]
  width_m?: number | null
  storeys?: number
  revision?: string
  low_confidence?: boolean
}
/** Trace the current sheet's floor plan into walls and rooms. Nothing is saved. */
export const planTo3d = (id: number) => post<Plan3D>(`/api/ai/drawings/${id}/to-3d`, {})
