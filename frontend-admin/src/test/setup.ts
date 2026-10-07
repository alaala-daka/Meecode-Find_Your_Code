// src/test/setup.ts
import '@testing-library/jest-dom'

// jsdom 缺 IntersectionObserver：装默认空实现兜底
if (!('IntersectionObserver' in globalThis)) {
  class NoopObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  ;(globalThis as Record<string, unknown>).IntersectionObserver = NoopObserver
}

// jsdom 缺 ResizeObserver（Radix Select/Portal 布局依赖）
if (!('ResizeObserver' in globalThis)) {
  class NoopResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  ;(globalThis as Record<string, unknown>).ResizeObserver = NoopResizeObserver
}

// jsdom 缺 pointer capture / scrollIntoView（Radix Select 交互依赖）
if (typeof Element !== 'undefined') {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {}
  }
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false
  }
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = () => {}
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = () => {}
  }
}
