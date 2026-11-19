// The screenshots are committed to a public repository, so the stack they are taken from
// must hold nothing but the fictional samples: no other documents, no earlier questions.

/** Returns what would show up in the screenshots besides the samples; empty means clean. */
export function foreignContent(documents, questions, sampleNames) {
  const samples = new Set(sampleNames)
  const found = documents.filter((d) => !samples.has(d.title)).map((d) => `document "${d.title}"`)
  if (questions.length > 0) found.push(`${questions.length} question(s) in the history`)
  return found
}
