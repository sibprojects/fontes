import { useEffect, useState, type FormEvent } from 'react'
import { addUrl, deleteDocument, listDocuments, uploadDocument } from '../api/client'
import type { DocumentOut } from '../api/types'
import { errorText, statusText } from '../format'

/** How often the list is re-fetched while a document is still being ingested. */
export const POLL_MS = 2000

function isBusy(doc: DocumentOut): boolean {
  return doc.status === 'queued' || doc.status === 'processing'
}

export function DocumentsPage() {
  // null until the first fetch answers, so the empty state does not flash.
  const [docs, setDocs] = useState<DocumentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  // Changing the key re-creates the file input, which is the simple way to clear it.
  const [fileInputKey, setFileInputKey] = useState(0)
  const [url, setUrl] = useState('')

  // Bumping this re-fetches the list.
  const [reload, setReload] = useState(0)

  useEffect(() => {
    // A slower, older answer must not overwrite a newer one.
    let current = true
    listDocuments().then(
      (fetched) => current && setDocs(fetched),
      (e: unknown) => current && setError(errorText(e)),
    )
    return () => {
      current = false
    }
  }, [reload])

  // While anything is queued or processing, fetch again after POLL_MS. Each fetch gives a
  // new `docs`, which re-runs this effect; once nothing is busy, no timer is set.
  useEffect(() => {
    if (!docs?.some(isBusy)) return
    const timer = setTimeout(() => setReload((n) => n + 1), POLL_MS)
    return () => clearTimeout(timer)
  }, [docs])

  // Runs one user action, shows its error if it fails, and re-fetches the list either way.
  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(errorText(e))
    }
    setReload((n) => n + 1)
  }

  async function onUpload(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    await run(() => uploadDocument(file))
    setFile(null)
    setFileInputKey((key) => key + 1)
  }

  async function onAddUrl(event: FormEvent) {
    event.preventDefault()
    if (!url.trim()) return
    await run(() => addUrl(url.trim()))
    setUrl('')
  }

  async function onDelete(doc: DocumentOut) {
    if (!window.confirm(`Delete ${doc.title}?`)) return
    await run(() => deleteDocument(doc.id))
  }

  return (
    <section>
      <div className="forms">
        <form onSubmit={onUpload}>
          <label>
            File
            <input
              key={fileInputKey}
              type="file"
              accept=".pdf,.md,.markdown,.html,.htm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={!file}>
            Upload
          </button>
        </form>
        <form onSubmit={onAddUrl}>
          <label>
            URL
            <input type="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <button type="submit" disabled={!url.trim()}>
            Add URL
          </button>
        </form>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {docs?.length === 0 && <p className="muted">No documents yet. Upload a PDF, Markdown or HTML file, or add a URL.</p>}

      {docs && docs.length > 0 && (
        <table className="documents">
          <thead>
            <tr>
              <th>Title</th>
              <th>Type</th>
              <th>Status</th>
              <th>Added</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.id}>
                <td>
                  {doc.url ? (
                    <a href={doc.url} target="_blank" rel="noreferrer">
                      {doc.title}
                    </a>
                  ) : (
                    doc.title
                  )}
                </td>
                <td>{doc.source_type}</td>
                <td>
                  <span className={`status status-${doc.status}`}>{statusText(doc)}</span>
                  {doc.status === 'failed' && doc.error && <div className="doc-error">{doc.error}</div>}
                </td>
                <td>{new Date(doc.created_at).toLocaleString()}</td>
                <td>
                  <button type="button" onClick={() => void onDelete(doc)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
