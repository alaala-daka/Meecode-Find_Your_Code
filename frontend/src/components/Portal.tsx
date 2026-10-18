// src/components/Portal.tsx —— 浮层统一挂到 body（FeedbackModal/LoginModal/Toast/StarSyncModal 共用）
// 为什么必须 portal：.topbar 的 backdrop-filter（TopBar.css:7）会让顶栏成为 fixed 定位的包含块，
// 浮层若渲染在顶栏子树里，position:fixed 的 inset:0 只铺满顶栏条（遮罩只盖住顶栏、弹窗被顶出屏幕截断）。
// 挂到 body 后 fixed 恒相对视口定位，且不再被祖先层叠上下文（.topbar z-index:20）压住。
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

export function Portal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body)
}

export default Portal
