import { describe, expect, it } from 'vitest'
import { foreignContent } from './stack-check.mjs'

const samples = ['lumen-kettle.md', 'sad-pravila.md']

describe('foreignContent', () => {
  it('accepts a stack holding only the samples and no questions', () => {
    expect(foreignContent([{ title: 'lumen-kettle.md' }, { title: 'sad-pravila.md' }], [], samples)).toEqual([])
  })

  it('names documents that are not samples', () => {
    expect(foreignContent([{ title: 'lumen-kettle.md' }, { title: 'tax-2025.pdf' }], [], samples)).toEqual([
      'document "tax-2025.pdf"',
    ])
  })

  it('counts questions already in the history', () => {
    expect(foreignContent([], [{ question: 'a' }, { question: 'b' }], samples)).toEqual([
      '2 question(s) in the history',
    ])
  })
})
