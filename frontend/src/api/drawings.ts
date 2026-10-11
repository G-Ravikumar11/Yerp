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
export const setDrawingStatus = (id: number, status: string) => post<{ drawing: { number: string } }>(`/api/drawings/${id}/status`, { status })
export function addRevision(id: number, file: File, b: { revision: string; status: string; received_on: string; received_from: string; remarks: string }) {
  const fd = new FormData()
  fd.append('file', file, file.name)
  for (const [k, v] of Object.entries(b)) fd.append(k, v)
  return api<{ message: string }>(`/api/drawings/${id}/revisions`, { method: 'POST', body: fd })
}
