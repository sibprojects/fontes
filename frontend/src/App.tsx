import { useState } from 'react'
import { AskPage } from './ask/AskPage'
import { HistorySidebar } from './ask/HistorySidebar'
import { DocumentsPage } from './documents/DocumentsPage'

type Tab = 'documents' | 'ask'

/** A click on a history entry. `n` is new on every click, so clicking the same entry again
 * (say, after it failed to load) loads it again. */
type Selection = { id: string; n: number }

export default function App() {
  const [tab, setTab] = useState<Tab>('documents')
  // The history entry being shown, if any, and a counter that makes the history re-fetch.
  const [selected, setSelected] = useState<Selection | null>(null)
  // The answer just given on this page; it is the current history entry until the next ask.
  const [answeredId, setAnsweredId] = useState<string | null>(null)
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
          <HistorySidebar
            refreshKey={historyKey}
            selectedId={selected?.id ?? answeredId}
            onSelect={(id) => setSelected((s) => ({ id, n: (s?.n ?? 0) + 1 }))}
          />
          <div className="ask-main">
            <AskPage
              historyId={selected?.id ?? null}
              historyLoad={selected?.n ?? 0}
              onAsk={() => {
                setSelected(null)
                setAnsweredId(null)
              }}
              onAnswered={(id) => {
                setAnsweredId(id)
                setHistoryKey((k) => k + 1)
              }}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
