/**
 * 后端 API（接口）的基础地址。
 * Vite 只会把 VITE_ 前缀的变量暴露给浏览器代码。
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
