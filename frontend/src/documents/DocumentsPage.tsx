import { useEffect, useRef, useState, type FormEvent } from 'react'
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
  // A failed list fetch and a failed action are kept apart: the next good fetch clears the
  // first, the next action the second.
  const [listError, setListError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const error = actionError ?? listError
  const [file, setFile] = useState<File | null>(null)
  // Changing the key re-creates the file input, which is the simple way to clear it.
  const [fileInputKey, setFileInputKey] = useState(0)
  const [url, setUrl] = useState('')
  // True while an upload, URL or delete is being sent.
  const [busy, setBusy] = useState(false)
  const running = useRef(false)

  // Bumping this re-fetches the list.
  const [reload, setReload] = useState(0)
  // Bumped when a fetch settles, either way, so the poll below re-arms even after a failure.
  const [settled, setSettled] = useState(0)

  useEffect(() => {
    // A slower, older answer must not overwrite a newer one.
    let current = true
    listDocuments()
      .then(
        (fetched) => {
          if (!current) return
          setDocs(fetched)
          setListError(null)
        },
        (e: unknown) => current && setListError(errorText(e)),
      )
      .finally(() => current && setSettled((n) => n + 1))
    return () => {
      current = false
    }
  }, [reload])

  // While anything is queued or processing, or the last fetch failed (say, the api is
  // restarting), fetch again after POLL_MS. Every settled fetch re-runs this effect; once
  // nothing is busy and the fetch worked, no timer is set.
  useEffect(() => {
    if (!listError && !docs?.some(isBusy)) return
    const timer = setTimeout(() => setReload((n) => n + 1), POLL_MS)
    return () => clearTimeout(timer)
  }, [settled, docs, listError])

  // Runs one user action, shows its error if it fails, and re-fetches the list either way.
  // One at a time: the buttons are disabled while it runs, and the ref also stops a second
  // click that lands before React has re-rendered them. Returns whether the action worked.
  async function run(action: () => Promise<unknown>): Promise<boolean> {
    if (running.current) return false
    running.current = true
    setBusy(true)
    setActionError(null)
    let ok = true
    try {
      await action()
    } catch (e) {
      ok = false
      setActionError(errorText(e))
    } finally {
      running.current = false
      setBusy(false)
    }
    setReload((n) => n + 1)
    return ok
  }

  // On a failure the file and the URL stay, so they can be sent again.
  async function onUpload(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    if (!(await run(() => uploadDocument(file)))) return
    setFile(null)
    setFileInputKey((key) => key + 1)
  }

  async function onAddUrl(event: FormEvent) {
    event.preventDefault()
    if (!url.trim()) return
    if (await run(() => addUrl(url.trim()))) setUrl('')
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
          <button type="submit" disabled={busy || !file}>
            Upload
          </button>
        </form>
        <form onSubmit={onAddUrl}>
          <label>
            URL
            <input type="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <button type="submit" disabled={busy || !url.trim()}>
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
                  <button type="button" disabled={busy} onClick={() => void onDelete(doc)}>
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
