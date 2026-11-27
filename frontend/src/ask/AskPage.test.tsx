import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getQuestion } from '../api/client'
import { ask } from '../api/sse'
import type { AnswerOut, AskEvent, Verdict } from '../api/types'
import { AskPage } from './AskPage'

vi.mock('../api/sse', () => ({ ask: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  getQuestion: vi.fn(),
}))

const stored: AnswerOut = {
  id: 'q9',
  question: 'What did I ask before?',
  answer: 'An old claim.',
  label: 'unsupported',
  paragraphs: [{ text: 'An old claim.', supported: false, citations: [] }],
  citations: [],
  provider: 'ollama',
  model: 'qwen2.5:7b',
  duration_ms: 1200,
  follow_up_of: null,
  created_at: '2026-11-13T10:00:00Z',
}

const verdict: Verdict = {
  question_id: 'q1',
  label: 'supported',
  paragraphs: [{ text: 'Run it [1].', supported: true, citations: [1] }],
  citations: [
    { n: 1, document_id: 'd1', document_title: 'guide.md', location: 'Install', url: null, excerpt: 'Run it.' },
  ],
}

function events(...items: AskEvent[]) {
  return async function* () {
    yield* items
  }
}

async function askQuestion(text = 'How do I run it?') {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Question'), text)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
  return user
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('AskPage', () => {
  it('streams tokens under verifying, then shows the verdict', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    vi.mocked(ask).mockImplementation(async function* () {
      yield { type: 'token', text: 'Run ' }
      yield { type: 'token', text: 'it [1].' }
      await gate
      yield { type: 'verdict', verdict }
    })
    const onAnswered = vi.fn()
    render(<AskPage onAnswered={onAnswered} />)
    await askQuestion()
    expect(ask).toHaveBeenCalledWith('How do I run it?', expect.any(AbortSignal))
    expect(await screen.findByText('verifying…')).toBeInTheDocument()
    expect(screen.getByText('Run it [1].')).toBeInTheDocument()

    release()
    expect(await screen.findByText('Supported by sources')).toBeInTheDocument()
    expect(screen.queryByText('verifying…')).not.toBeInTheDocument()
    expect(screen.getByText('[1] guide.md — Install')).toBeInTheDocument()
    expect(onAnswered).toHaveBeenCalledWith('q1')
  })

  it('the answer region announces itself', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    vi.mocked(ask).mockImplementation(async function* () {
      yield { type: 'token', text: 'Run ' }
      await gate
      yield { type: 'verdict', verdict }
    })
    const { container } = render(<AskPage />)
    const region = container.querySelector('section.ask [aria-live="polite"]')
    expect(region).not.toBeNull()
    expect(region).toHaveAttribute('aria-busy', 'false')
    await askQuestion()
    await screen.findByText('verifying…')
    expect(region).toHaveAttribute('aria-busy', 'true')
    expect(region).toContainElement(screen.getByText('verifying…'))
    release()
    await screen.findByText('Supported by sources')
    expect(region).toHaveAttribute('aria-busy', 'false')
  })

  it('shows the detail of a rejected question', async () => {
    vi.mocked(ask).mockImplementation(async function* () {
      yield* []
      throw new ApiError(422, 'The question is too long')
    })
    render(<AskPage />)
    await askQuestion()
    expect(await screen.findByRole('alert')).toHaveTextContent('The question is too long')
  })

  it('shows an error event and no provisional text', async () => {
    vi.mocked(ask).mockImplementation(
      events({ type: 'token', text: 'Partial answer' }, { type: 'error', detail: 'Cannot reach Ollama' }),
    )
    render(<AskPage />)
    await askQuestion()
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach Ollama')
    expect(screen.queryByText('Partial answer')).not.toBeInTheDocument()
    expect(screen.queryByText('verifying…')).not.toBeInTheDocument()
  })

  it('the button is disabled for a blank question and while streaming', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    vi.mocked(ask).mockImplementation(async function* () {
      yield { type: 'token', text: 'Run' }
      await gate
      yield { type: 'verdict', verdict }
    })
    render(<AskPage />)
    const button = screen.getByRole('button', { name: 'Ask' })
    expect(button).toBeDisabled()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Question'), '   ')
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText('Question'), 'How?')
    expect(button).toBeEnabled()
    await user.click(button)
    expect(await screen.findByText('verifying…')).toBeInTheDocument()
    expect(button).toBeDisabled()
    release()
    await screen.findByText('Supported by sources')
    expect(button).toBeEnabled()
  })

  it('Ctrl+Enter asks', async () => {
    vi.mocked(ask).mockImplementation(events({ type: 'verdict', verdict }))
    render(<AskPage />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Question'), 'How?')
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(ask).toHaveBeenCalledWith('How?', expect.any(AbortSignal))
  })

  it('aborts the stream on unmount', async () => {
    let signal: AbortSignal | undefined
    vi.mocked(ask).mockImplementation(async function* (_q: string, s?: AbortSignal) {
      signal = s
      yield { type: 'token', text: 'Run' }
      await new Promise(() => {})
    })
    const { unmount } = render(<AskPage />)
    await askQuestion()
    await screen.findByText('verifying…')
    unmount()
    expect(signal?.aborted).toBe(true)
  })

  it('shows a stored answer for historyId', async () => {
    vi.mocked(getQuestion).mockResolvedValue(stored)
    render(<AskPage historyId="q9" />)
    expect(await screen.findByText('What did I ask before?')).toBeInTheDocument()
    expect(getQuestion).toHaveBeenCalledWith('q9')
    expect(screen.getByText('Not supported by sources')).toBeInTheDocument()
    expect(screen.getByText(/no source/)).toBeInTheDocument()
  })

  it('shows why a stored answer could not be loaded', async () => {
    vi.mocked(getQuestion).mockRejectedValue(new ApiError(404, 'Question not found'))
    render(<AskPage historyId="q9" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Question not found')
  })

  it('asking calls onAsk so the history selection is cleared', async () => {
    vi.mocked(ask).mockImplementation(events({ type: 'verdict', verdict }))
    const onAsk = vi.fn()
    render(<AskPage onAsk={onAsk} />)
    await askQuestion()
    expect(onAsk).toHaveBeenCalledTimes(1)
  })
})
