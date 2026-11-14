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

/** Past questions, newest first (the API's order). */
export function HistorySidebar({ refreshKey, selectedId, onSelect }: Props) {
  const [questions, setQuestions] = useState<QuestionSummaryOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    listQuestions().then(
      (fetched) => {
        if (!current) return
        setQuestions(fetched)
        setError(null)
      },
      (e: unknown) => current && setError(errorText(e)),
    )
    return () => {
      current = false
    }
  }, [refreshKey])

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
