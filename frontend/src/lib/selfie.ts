/**
 * A picture from the camera made small enough to go with a clock-in: a JPEG no wider than `max` pixels, as a data URL.
 * A selfie is optional, so any failure (a browser with no canvas, a file that is not a picture) gives null and the
 * clock-in goes without it.
 */
export async function selfieDataUrl(file: File, max = 640, quality = 0.7): Promise<string | null> {
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close?.()
    const url = canvas.toDataURL('image/jpeg', quality)
    return url.startsWith('data:image/jpeg') ? url : null
  } catch {
    return null
  }
}
