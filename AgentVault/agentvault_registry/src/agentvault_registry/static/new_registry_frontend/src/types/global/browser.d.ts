// Global type declarations for browser APIs
declare global {
  interface Window {
    localStorage: Storage
    sessionStorage: Storage
  }
  
  const localStorage: Storage
  const sessionStorage: Storage
}

export {}
