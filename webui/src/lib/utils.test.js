import { describe, it, expect } from 'vitest'
import { cn, formatTime, mediaUrl } from './utils'

describe('formatTime', () => {
  it('formats 0 seconds as 0:00', () => {
    expect(formatTime(0)).toBe('0:00')
  })

  it('formats seconds under a minute', () => {
    expect(formatTime(5)).toBe('0:05')
    expect(formatTime(59)).toBe('0:59')
  })

  it('formats exactly one minute', () => {
    expect(formatTime(60)).toBe('1:00')
  })

  it('formats minutes and seconds', () => {
    expect(formatTime(65)).toBe('1:05')
    expect(formatTime(125)).toBe('2:05')
  })

  it('formats large values (over one hour)', () => {
    // formatTime does not add hours – minutes continue to grow
    expect(formatTime(3600)).toBe('60:00')
    expect(formatTime(3661)).toBe('61:01')
  })

  it('handles null/undefined by defaulting to 0', () => {
    expect(formatTime(null)).toBe('0:00')
    expect(formatTime(undefined)).toBe('0:00')
    expect(formatTime('')).toBe('0:00')
  })

  it('handles string numbers', () => {
    expect(formatTime('90')).toBe('1:30')
  })

  it('truncates fractional seconds', () => {
    expect(formatTime(61.9)).toBe('1:01')
  })
})

describe('mediaUrl', () => {
  it('returns empty string for falsy path', () => {
    expect(mediaUrl('')).toBe('')
    expect(mediaUrl(null)).toBe('')
    expect(mediaUrl(undefined)).toBe('')
  })

  it('builds a /api/media URL with encoded path', () => {
    expect(mediaUrl('C:/Projects/foo.jpg')).toBe(
      '/api/media?path=C%3A%2FProjects%2Ffoo.jpg'
    )
  })

  it('includes version param when provided', () => {
    const url = mediaUrl('assets/img.png', '2')
    expect(url).toBe('/api/media?path=assets%2Fimg.png&v=2')
  })

  it('omits version param when version is empty string', () => {
    const url = mediaUrl('assets/img.png', '')
    expect(url).toBe('/api/media?path=assets%2Fimg.png')
  })

  it('encodes special characters in the path', () => {
    expect(mediaUrl('path with spaces/file.jpg')).toBe(
      '/api/media?path=path%20with%20spaces%2Ffile.jpg'
    )
  })
})

describe('cn', () => {
  it('returns a single class string unchanged', () => {
    expect(cn('foo')).toBe('foo')
  })

  it('merges multiple class strings', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('ignores falsy values', () => {
    expect(cn('foo', false, null, undefined, 'bar')).toBe('foo bar')
  })

  it('handles conditional objects', () => {
    expect(cn({ foo: true, bar: false })).toBe('foo')
  })

  it('deduplicates conflicting Tailwind classes (last wins)', () => {
    // tailwind-merge keeps the last conflicting utility
    expect(cn('p-4', 'p-2')).toBe('p-2')
    expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500')
  })

  it('returns empty string when no classes given', () => {
    expect(cn()).toBe('')
  })
})
