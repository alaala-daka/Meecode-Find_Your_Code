// src/lib/githubRaw.ts —— GitHub 外链拼装：路径分段编码，中文/空格安全
const RAW_BASE = 'https://raw.githubusercontent.com'

// 分段先解码再编码：markdown 链接的 href 已被 remark 预编码，
// 直接 encodeURIComponent 会二次转义（% → %25）；解码后重编码保持幂等。
// 非法转义序列（字面量 % 等）解码会抛错，此时按原样编码。
function encodeSegment(seg: string): string {
  let decoded = seg
  try {
    decoded = decodeURIComponent(seg)
  } catch {
    // 保留原样
  }
  return encodeURIComponent(decoded)
}

/** 路径分段 encodeURIComponent（幂等）：'assets/演示 截图.png' → 'assets/%E6%BC%94%E7%A4%BA%20%E6%88%AA%E5%9B%BE.png' */
export function encodePath(p: string): string {
  return p.split('/').map(encodeSegment).join('/')
}

/** raw 直链（README 内嵌资源与图片预览共用）：fullName='owner/repo'，ref 为分支名 */
export function rawUrlFor(fullName: string, ref: string, path: string): string {
  return `${RAW_BASE}/${fullName}/${ref}/${encodePath(path)}`
}

/** GitHub 浏览深链：repoWebUrl 形如 'https://github.com/owner/repo'（容忍尾斜杠） */
export function blobUrl(repoWebUrl: string, ref: string, path: string): string {
  return `${repoWebUrl.replace(/\/$/, '')}/blob/${ref}/${encodePath(path)}`
}
