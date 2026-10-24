export function getDocumentTitle(document) {
  const title = typeof document?.title === 'string' ? document.title.trim() : ''
  const filename = typeof document?.original_filename === 'string'
    ? document.original_filename.trim()
    : ''
  return title || filename || 'Untitled document'
}

export function getDistinctFilename(document) {
  const title = getDocumentTitle(document)
  const filename = typeof document?.original_filename === 'string'
    ? document.original_filename.trim()
    : ''
  return filename && filename.toLocaleLowerCase() !== title.toLocaleLowerCase()
    ? filename
    : ''
}
