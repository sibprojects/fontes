import { useState } from 'react'
import { AskPage } from './ask/AskPage'
import { HistorySidebar } from './ask/HistorySidebar'
import { DocumentsPage } from './documents/DocumentsPage'

type Tab = 'documents' | 'ask'

export default function App() {
  const [tab, setTab] = useState<Tab>('documents')
  // The history entry being shown, if any, and a counter that makes the history re-fetch.
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [historyKey, setHistoryKey] = useState(0)

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
        <div hidden={tab !== 'ask'} className="ask-layout">
          <HistorySidebar refreshKey={historyKey} selectedId={selectedId} onSelect={setSelectedId} />
          <div className="ask-main">
            <AskPage
              historyId={selectedId}
              onAsk={() => setSelectedId(null)}
              onAnswered={() => setHistoryKey((k) => k + 1)}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
