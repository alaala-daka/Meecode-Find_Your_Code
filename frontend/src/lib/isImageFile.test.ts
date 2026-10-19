// src/lib/isImageFile.test.ts
import { describe, expect, it } from 'vitest'
import { isImageFile } from './isImageFile'

describe('isImageFile', () => {
  it('识别 9 种图片后缀（含 SVG、大小写混合）', () => {
    for (const p of ['a.png', 'b.jpg', 'c.jpeg', 'd.gif', 'e.webp', 'f.svg', 'g.bmp', 'h.ico', 'i.avif',
      'J.PNG', 'photo.JpEg', 'assets/dir/x.SVG']) {
      expect(isImageFile(p), p).toBe(true)
    }
  })

  it('非图片与伪后缀不识别', () => {
    for (const p of ['README.md', 'main.py', 'archive.png.bak', 'Makefile', 'a.', '.png', 'src/.hidden']) {
      expect(isImageFile(p), p).toBe(false)
    }
  })
})
