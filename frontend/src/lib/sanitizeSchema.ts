// src/lib/sanitizeSchema.ts —— README 与评论共用的 rehype-sanitize 白名单（spec 决策 6：单点审计）
import { defaultSchema } from 'rehype-sanitize'

/* 安全基线（决策 #9）：内嵌 HTML 经 rehype-raw 解析后必须过白名单消毒
   （script/iframe/事件属性等全部剔除）再渲染。README 与评论共用同一 schema。 */
export const sanitizeSchema: typeof defaultSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), 'video'],
  attributes: {
    ...defaultSchema.attributes,
    video: ['src', 'controls', 'width', 'height', 'poster', 'autoPlay', 'loop', 'muted', 'preload', 'playsInline'],
    source: ['src', 'type', 'media', 'srcSet'],
  },
}
