import { describe, expect, it } from 'vitest'
import type { DocumentOut } from './api/types'
import { errorText, statusText } from './format'

function doc(overrides: Partial<DocumentOut>): DocumentOut {
  return {
    id: 'd1',
    title: 'a.md',
    source_type: 'markdown',
    status: 'ready',
    url: null,
    error: null,
    attempts: 0,
    max_attempts: 3,
    created_at: '2026-11-13T10:00:00Z',
    ...overrides,
  }
}

describe('statusText', () => {
  it('ready', () => expect(statusText(doc({ status: 'ready', attempts: 1 }))).toBe('ready'))
  it('processing', () => expect(statusText(doc({ status: 'processing', attempts: 1 }))).toBe('processing…'))
  it('queued before any attempt', () => expect(statusText(doc({ status: 'queued' }))).toBe('queued'))
  it('queued for a retry', () => expect(statusText(doc({ status: 'queued', attempts: 2 }))).toBe('retry 2/3'))
  it('failed', () => expect(statusText(doc({ status: 'failed', error: 'boom' }))).toBe('failed'))
})

describe('errorText', () => {
  it('uses the message of an Error', () => expect(errorText(new Error('boom'))).toBe('boom'))
  it('stringifies anything else', () => expect(errorText('boom')).toBe('boom'))
})
