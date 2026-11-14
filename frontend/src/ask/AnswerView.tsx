import type { CitationOut, Label, ParagraphOut } from '../api/types'
import { labelText } from '../format'

type Props = {
  question: string
  paragraphs: ParagraphOut[]
  citations: CitationOut[]
  label: Label
}

/** A verified answer: the label, each paragraph (unsupported ones highlighted), then the sources. */
export function AnswerView({ question, paragraphs, citations, label }: Props) {
  return (
    <article className="answer">
      <h2 className="question">{question}</h2>
      <span className={`label label-${label}`}>{labelText(label)}</span>
      {paragraphs.map((paragraph, i) => {
        // "Nothing found" is the app talking, not a claim, so it is never flagged.
        const flagged = !paragraph.supported && label !== 'not_found'
        return (
          <p key={i} className={flagged ? 'paragraph unsupported' : 'paragraph'}>
            {paragraph.text}
            {flagged && <span className="no-source"> (no source)</span>}
          </p>
        )
      })}
      {citations.length > 0 && (
        <>
          <h3>Sources</h3>
          <ul className="sources">
            {citations.map((citation) => (
              <li key={citation.n}>
                {/* <details> opens on click with no state: the excerpt is the chunk the model saw. */}
                <details>
                  <summary>
                    [{citation.n}] {citation.document_title} — {citation.location}
                  </summary>
                  {citation.url && (
                    <a href={citation.url} target="_blank" rel="noreferrer">
                      {citation.url}
                    </a>
                  )}
                  <blockquote className="excerpt">{citation.excerpt}</blockquote>
                </details>
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  )
}
