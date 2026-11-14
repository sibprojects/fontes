import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ask } from '../api/sse'
import type { Verdict } from '../api/types'
import { errorText } from '../format'
import { AnswerView } from './AnswerView'

/** Matches QUESTION_MAX_CHARS on the backend; the API rejects longer ones anyway. */
const MAX_CHARS = 2000

// One union instead of several flags, so that, say, "streaming" with a verdict cannot exist.
type View =
  | { kind: 'idle' }
  | { kind: 'streaming'; question: string; text: string }
  | { kind: 'answered'; question: string; verdict: Verdict }
  | { kind: 'failed'; question: string; detail: string }

type Props = {
  onAnswered?: (questionId: string) => void
}

export function AskPage({ onAnswered }: Props) {
  const [question, setQuestion] = useState('')
  const [view, setView] = useState<View>({ kind: 'idle' })
  const controller = useRef<AbortController | null>(null)

  // Leaving the page stops the answer; the API then stores nothing.
  useEffect(() => () => controller.current?.abort(), [])

  const streaming = view.kind === 'streaming'

  async function submit() {
    const asked = question.trim()
    if (!asked || streaming) return
    const current = new AbortController()
    controller.current = current
    setView({ kind: 'streaming', question: asked, text: '' })
    try {
      for await (const event of ask(asked, current.signal)) {
        if (event.type === 'token') {
          setView((v) => (v.kind === 'streaming' ? { ...v, text: v.text + event.text } : v))
        } else if (event.type === 'verdict') {
          setView({ kind: 'answered', question: asked, verdict: event.verdict })
          onAnswered?.(event.verdict.question_id)
        } else {
          setView({ kind: 'failed', question: asked, detail: event.detail })
        }
      }
    } catch (e) {
      if (!current.signal.aborted) setView({ kind: 'failed', question: asked, detail: errorText(e) })
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void submit()
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <section className="ask">
      <form onSubmit={onSubmit} className="ask-form">
        <label htmlFor="question">Question</label>
        <textarea
          id="question"
          rows={3}
          maxLength={MAX_CHARS}
          placeholder="Ask about your documents (Ctrl+Enter to send)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" disabled={streaming || !question.trim()}>
          Ask
        </button>
      </form>

      {view.kind === 'streaming' && (
        <article className="answer provisional">
          <h2 className="question">{view.question}</h2>
          <span className="label label-verifying">verifying…</span>
          <p className="paragraph">{view.text}</p>
        </article>
      )}

      {view.kind === 'answered' && (
        <AnswerView
          question={view.question}
          paragraphs={view.verdict.paragraphs}
          citations={view.verdict.citations}
          label={view.verdict.label}
        />
      )}

      {view.kind === 'failed' && (
        <article className="answer">
          <h2 className="question">{view.question}</h2>
          <p role="alert" className="error">
            {view.detail}
          </p>
        </article>
      )}
    </section>
  )
}
