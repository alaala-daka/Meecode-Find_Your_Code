// src/lib/isImageFile.ts —— 图片后缀白名单：文件预览分流依据（spec 2026-10-19 §3.1）
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif'])

/** 只认最后一段后缀：'archive.png.bak' 不算；点开头（隐藏文件）与无后缀不算 */
export function isImageFile(path: string): boolean {
  const name = path.split('/').pop() ?? path
  const dot = name.lastIndexOf('.')
  if (dot <= 0) return false
  return IMAGE_EXTS.has(name.slice(dot + 1).toLowerCase())
}
