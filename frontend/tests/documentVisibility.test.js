import assert from 'node:assert/strict'
import test from 'node:test'
import { documentVisibilityLabel } from '../src/utils/documentVisibility.js'

test('visibility label reflects the API is_shared value', () => {
  assert.equal(documentVisibilityLabel(true), 'SHARED')
  assert.equal(documentVisibilityLabel(false), 'PRIVATE')
  assert.equal(documentVisibilityLabel(undefined), 'PRIVATE')
})
