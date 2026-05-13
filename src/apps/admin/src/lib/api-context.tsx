'use client'

import { createContext, useContext, useMemo, useState } from 'react'
import type { ApiConnectionStatus } from './types'

interface ApiContextValue {
  userId: string
  connectionStatus: ApiConnectionStatus
  setConnected: () => void
  setFallback: () => void
  resetConnection: () => void
}

const ApiContext = createContext<ApiContextValue | null>(null)

export function ApiProvider({ children }: { children: React.ReactNode }) {
  const [connectionStatus, setConnectionStatus] = useState<ApiConnectionStatus>('unknown')

  const value = useMemo<ApiContextValue>(
    () => ({
      userId: 'demo',
      connectionStatus,
      setConnected: () => setConnectionStatus('connected'),
      setFallback: () => setConnectionStatus('fallback'),
      resetConnection: () => setConnectionStatus('unknown'),
    }),
    [connectionStatus]
  )

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApiContext() {
  const context = useContext(ApiContext)
  if (!context) {
    throw new Error('useApiContext must be used within ApiProvider')
  }
  return context
}
