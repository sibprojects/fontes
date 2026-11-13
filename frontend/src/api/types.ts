// Hand-written mirrors of backend/fontes/api/schemas.py. Datetimes arrive as ISO strings.

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed'
export type SourceType = 'pdf' | 'markdown' | 'html' | 'url'
export type Label = 'supported' | 'partially_supported' | 'unsupported' | 'not_found'

export type DocumentOut = {
  id: string
  title: string
  source_type: SourceType
  status: DocumentStatus
  url: string | null
  error: string | null
  attempts: number
  max_attempts: number
  created_at: string
}

export type ChunkOut = {
  ordinal: number
  location: string
  text: string
}

export type ParagraphOut = {
  text: string
  supported: boolean
  citations: number[]
}

export type CitationOut = {
  n: number
  document_id: string
  document_title: string
  location: string
  url: string | null
  excerpt: string
}

export type AnswerOut = {
  id: string
  question: string
  answer: string
  label: Label
  paragraphs: ParagraphOut[]
  citations: CitationOut[]
  provider: string | null
  model: string | null
  duration_ms: number
  created_at: string
}

export type QuestionSummaryOut = {
  id: string
  question: string
  label: Label
  created_at: string
}

/** The data of the `verdict` event of POST /ask. */
export type Verdict = {
  question_id: string
  label: Label
  paragraphs: ParagraphOut[]
  citations: CitationOut[]
}

/** One event of the answer stream, already decoded. */
export type AskEvent =
  | { type: 'token'; text: string }
  | { type: 'verdict'; verdict: Verdict }
  | { type: 'error'; detail: string }
