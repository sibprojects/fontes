import { useState } from 'react'
import { DocumentsPage } from './documents/DocumentsPage'

type Tab = 'documents' | 'ask'

export default function App() {
  const [tab, setTab] = useState<Tab>('documents')

  // Both pages stay mounted and are only hidden, so switching tabs keeps their state.
  return (
    <div className="app">
      <header>
        <h1>Fontes</h1>
        <nav className="tabs">
          <button type="button" aria-pressed={tab === 'documents'} onClick={() => setTab('documents')}>
            Documents
          </button>
          <button type="button" aria-pressed={tab === 'ask'} onClick={() => setTab('ask')}>
            Ask
          </button>
        </nav>
      </header>
      <main>
        <div hidden={tab !== 'documents'}>
          <DocumentsPage />
        </div>
        <div hidden={tab !== 'ask'}>
          <p className="muted">Asking comes next.</p>
        </div>
      </main>
    </div>
  )
}
