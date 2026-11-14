import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CitationOut, ParagraphOut } from '../api/types'
import { AnswerView } from './AnswerView'

const citation: CitationOut = {
  n: 1,
  document_id: 'd1',
  document_title: 'guide.md',
  location: 'Install',
  url: null,
  excerpt: 'Run make install to set it up.',
}

const paragraphs: ParagraphOut[] = [
  { text: 'Run `make install` [1].', supported: true, citations: [1] },
  { text: 'It is very fast.', supported: false, citations: [] },
]

describe('AnswerView', () => {
  it('marks unsupported paragraphs', () => {
    render(<AnswerView question="How?" paragraphs={paragraphs} citations={[citation]} label="partially_supported" />)
    const unsupported = screen.getByText(/It is very fast\./).closest('p')!
    expect(unsupported).toHaveClass('unsupported')
    expect(unsupported).toHaveTextContent('(no source)')
    expect(screen.getByText(/Run `make install`/).closest('p')).not.toHaveClass('unsupported')
  })

  it('shows the question and the label text', () => {
    render(<AnswerView question="How?" paragraphs={paragraphs} citations={[citation]} label="partially_supported" />)
    expect(screen.getByText('How?')).toBeInTheDocument()
    expect(screen.getByText('Partly supported')).toHaveClass('label-partially_supported')
  })

  it('lists citations with location and excerpt', () => {
    render(<AnswerView question="How?" paragraphs={paragraphs} citations={[citation]} label="supported" />)
    expect(screen.getByText('[1] guide.md — Install')).toBeInTheDocument()
    expect(screen.getByText('Run make install to set it up.')).toBeInTheDocument()
  })

  it('links URL citations', () => {
    const web = { ...citation, url: 'https://example.com/guide' }
    render(<AnswerView question="How?" paragraphs={paragraphs} citations={[web]} label="supported" />)
    expect(screen.getByRole('link', { name: 'https://example.com/guide' })).toHaveAttribute(
      'href',
      'https://example.com/guide',
    )
  })

  it('has no sources heading when nothing was cited', () => {
    render(
      <AnswerView
        question="Peru?"
        paragraphs={[{ text: 'I could not find anything.', supported: false, citations: [] }]}
        citations={[]}
        label="not_found"
      />,
    )
    expect(screen.queryByText('Sources')).not.toBeInTheDocument()
    expect(screen.getByText('Nothing found in your documents')).toBeInTheDocument()
    // "Nothing found" is not a claim, so it is not flagged as one without a source.
    expect(screen.queryByText(/no source/)).not.toBeInTheDocument()
  })
})
