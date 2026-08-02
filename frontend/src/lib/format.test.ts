import { describe, expect, it } from 'vitest'
import { formatBytes, formatRuntime } from './format'

describe('formatters', () => {
  it('formats bytes', () => expect(formatBytes(1073741824)).toBe('1.0 GB'))
  it('formats runtime', () => expect(formatRuntime(7380)).toBe('2h 3m'))
})
