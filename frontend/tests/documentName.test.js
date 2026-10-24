import assert from 'node:assert/strict'
import test from 'node:test'
import { getDistinctFilename, getDocumentTitle } from '../src/utils/documentName.js'

test('document filename is not repeated when it is already the title', () => {
  const document = { title: 'Travel Policy.pdf', original_filename: 'Travel Policy.pdf' }
  assert.equal(getDocumentTitle(document), 'Travel Policy.pdf')
  assert.equal(getDistinctFilename(document), '')
})

test('document title and distinct source filename are both preserved', () => {
  const document = { title: 'Travel policy', original_filename: 'travel-policy-final.pdf' }
  assert.equal(getDocumentTitle(document), 'Travel policy')
  assert.equal(getDistinctFilename(document), 'travel-policy-final.pdf')
})

test('document names handle missing or empty API values', () => {
  assert.equal(getDocumentTitle({ title: '', original_filename: 'guide.txt' }), 'guide.txt')
  assert.equal(getDocumentTitle(null), 'Untitled document')
  assert.equal(getDistinctFilename({}), '')
})
