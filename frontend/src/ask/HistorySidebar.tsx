import { useEffect, useState } from 'react'
import { listQuestions } from '../api/client'
import type { QuestionSummaryOut } from '../api/types'
import { errorText, labelText } from '../format'

type Props = {
  /** Bumped by the parent after a new answer, to fetch the list again. */
  refreshKey: number
  selectedId: string | null
  onSelect: (id: string) => void
}

/** After a failed fetch (say, the api is restarting), the list is fetched again this often. */
export const HISTORY_RETRY_MS = 2000

/** Past questions, newest first (the API's order). */
export function HistorySidebar({ refreshKey, selectedId, onSelect }: Props) {
  const [questions, setQuestions] = useState<QuestionSummaryOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Bumped by the retry timer; a new fetch also re-arms the timer if it fails again.
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let current = true
    let timer: ReturnType<typeof setTimeout> | undefined
    listQuestions().then(
      (fetched) => {
        if (!current) return
        setQuestions(fetched)
        setError(null)
      },
      (e: unknown) => {
        if (!current) return
        setError(errorText(e))
        timer = setTimeout(() => setRetry((n) => n + 1), HISTORY_RETRY_MS)
      },
    )
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [refreshKey, retry])

  return (
    <nav className="history" aria-label="History">
      <h2>History</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {questions?.length === 0 && <p className="muted">No questions yet.</p>}
      <ul>
        {questions?.map((q) => (
          <li key={q.id}>
            <button
              type="button"
              aria-current={q.id === selectedId ? 'true' : undefined}
              onClick={() => onSelect(q.id)}
            >
              <span className="history-question">{q.question}</span>
              <span className="history-meta">
                <span className={`label label-${q.label}`}>{labelText(q.label)}</span>{' '}
                {new Date(q.created_at).toLocaleString()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
