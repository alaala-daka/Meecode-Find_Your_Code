// src/lib/githubRaw.ts —— GitHub 外链拼装：路径分段编码，中文/空格安全
const RAW_BASE = 'https://raw.githubusercontent.com'

/** 路径分段 encodeURIComponent：'assets/演示 截图.png' → 'assets/%E6%BC%94%E7%A4%BA%20%E6%88%AA%E5%9B%BE.png' */
export function encodePath(p: string): string {
  return p.split('/').map(encodeURIComponent).join('/')
}

/**
 * 路径分段解码（预编码归一）：'docs/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md' → 'docs/使用说明.md'。
 * markdown/HTML 的 href/src 由 ReadmeSection.resolveUrl 在边界统一经本函数归一
 * （含 rehype-raw 注入的 raw HTML src）；API/文件树等字面路径不要经过本函数，直接交给 encodePath。
 * 已知边角：raw HTML 引用的字面 `%XX` 文件名会被归一误解（markdown 里写 `%2520` 可正确表达）。
 * 非法转义序列（如字面量 '%'）解码抛错时回退原段。
 */
export function decodePath(p: string): string {
  return p.split('/').map((seg) => {
    try {
      return decodeURIComponent(seg)
    } catch {
      return seg
    }
  }).join('/')
}

/** raw 直链（README 内嵌资源与图片预览共用）：fullName='owner/repo'，ref 为分支名 */
export function rawUrlFor(fullName: string, ref: string, path: string): string {
  return `${RAW_BASE}/${fullName}/${ref}/${encodePath(path)}`
}

/** GitHub 浏览深链：repoWebUrl 形如 'https://github.com/owner/repo'（容忍尾斜杠） */
export function blobUrl(repoWebUrl: string, ref: string, path: string): string {
  return `${repoWebUrl.replace(/\/$/, '')}/blob/${ref}/${encodePath(path)}`
}
