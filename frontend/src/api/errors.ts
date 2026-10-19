// src/api/errors.ts —— 结构化 API 错误：/files 422 detail 为 {code,message} 时携带 code
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string = '') {
    super(message)
    this.name = 'ApiError'
  }
}
