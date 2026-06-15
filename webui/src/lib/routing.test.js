import { describe, it, expect } from 'vitest'
import {
  slugify,
  buildSeriesSlugMap,
  buildVideoSlugMap,
  seriesSlugToPath,
  videoSlugToPath,
  pathToSeriesSlug,
  pathToVideoSlug,
  STEP_TO_SEGMENT,
  SEGMENT_TO_STEP,
} from './routing'

// ---------------------------------------------------------------------------
// slugify
// ---------------------------------------------------------------------------
describe('slugify', () => {
  it('lowercases ASCII text', () => {
    expect(slugify('Hello World')).toBe('hello-world')
  })

  it('strips Vietnamese diacritics — Bóng Đá → bong-da', () => {
    expect(slugify('Bóng Đá')).toBe('bong-da')
  })

  it('strips Vietnamese diacritics — Khoa học vũ trụ! → khoa-hoc-vu-tru', () => {
    expect(slugify('Khoa học vũ trụ!')).toBe('khoa-hoc-vu-tru')
  })

  it('handles more Vietnamese characters', () => {
    expect(slugify('Trận chung kết')).toBe('tran-chung-ket')
    expect(slugify('Chuỗi dự án')).toBe('chuoi-du-an')
  })

  it('collapses runs of non-alphanumeric chars into a single dash', () => {
    expect(slugify('a  --  b')).toBe('a-b')
    expect(slugify('hello!!! world')).toBe('hello-world')
  })

  it('trims leading and trailing dashes', () => {
    expect(slugify('  hello  ')).toBe('hello')
    expect(slugify('!hello!')).toBe('hello')
  })

  it('returns "muc" for empty / all-special input', () => {
    expect(slugify('')).toBe('muc')
    expect(slugify('!!!')).toBe('muc')
    expect(slugify('   ')).toBe('muc')
  })

  it('preserves digits', () => {
    expect(slugify('Video 42')).toBe('video-42')
  })
})

// ---------------------------------------------------------------------------
// buildSeriesSlugMap
// ---------------------------------------------------------------------------
describe('buildSeriesSlugMap', () => {
  const series = [
    { path: 'C:/Projects/BongDa', title: 'Bóng Đá', is_virtual: false },
    { path: 'C:/Projects/KhoaHoc', title: 'Khoa học', is_virtual: false },
    { path: 'C:/Projects/Ungrouped', title: 'Chưa phân nhóm', is_virtual: true },
  ]

  it('builds slugToPath and pathToSlug maps', () => {
    const { slugToPath, pathToSlug } = buildSeriesSlugMap(series)
    expect(slugToPath['bong-da']).toBe('C:/Projects/BongDa')
    expect(slugToPath['khoa-hoc']).toBe('C:/Projects/KhoaHoc')
    expect(pathToSlug['C:/Projects/BongDa']).toBe('bong-da')
    expect(pathToSlug['C:/Projects/KhoaHoc']).toBe('khoa-hoc')
  })

  it('virtual series always gets slug "chua-phan-nhom" regardless of title', () => {
    const { slugToPath, pathToSlug } = buildSeriesSlugMap(series)
    expect(slugToPath['chua-phan-nhom']).toBe('C:/Projects/Ungrouped')
    expect(pathToSlug['C:/Projects/Ungrouped']).toBe('chua-phan-nhom')
  })

  it('handles collision with deterministic suffix -2, -3 by array order', () => {
    const colliding = [
      { path: 'C:/A', title: 'Bóng Đá', is_virtual: false },
      { path: 'C:/B', title: 'Bong Da', is_virtual: false },   // same slug bong-da
      { path: 'C:/C', title: 'BONG DA', is_virtual: false },   // same slug again
    ]
    const { slugToPath, pathToSlug } = buildSeriesSlugMap(colliding)
    // first keeps the base slug
    expect(slugToPath['bong-da']).toBe('C:/A')
    // second gets -2
    expect(slugToPath['bong-da-2']).toBe('C:/B')
    // third gets -3
    expect(slugToPath['bong-da-3']).toBe('C:/C')
    // reverse
    expect(pathToSlug['C:/A']).toBe('bong-da')
    expect(pathToSlug['C:/B']).toBe('bong-da-2')
    expect(pathToSlug['C:/C']).toBe('bong-da-3')
  })

  it('returns plain objects (not Maps)', () => {
    const { slugToPath, pathToSlug } = buildSeriesSlugMap(series)
    expect(typeof slugToPath).toBe('object')
    expect(typeof pathToSlug).toBe('object')
  })
})

// ---------------------------------------------------------------------------
// buildVideoSlugMap
// ---------------------------------------------------------------------------
describe('buildVideoSlugMap', () => {
  const projects = [
    { path: 'C:/Projects/BongDa/final', name: 'Trận chung kết', category: 'Bóng Đá' },
    { path: 'C:/Projects/BongDa/semi',  name: 'Bán kết',        category: 'Bóng Đá' },
    { path: 'C:/Projects/BongDa/q1',    name: 'Trận chung kết', category: 'Bóng Đá' }, // collision
  ]

  it('builds slugToPath and pathToSlug maps from project.name', () => {
    const { slugToPath, pathToSlug } = buildVideoSlugMap(projects)
    expect(slugToPath['tran-chung-ket']).toBe('C:/Projects/BongDa/final')
    expect(slugToPath['ban-ket']).toBe('C:/Projects/BongDa/semi')
    expect(pathToSlug['C:/Projects/BongDa/semi']).toBe('ban-ket')
  })

  it('handles collisions with -2 suffix for duplicate names', () => {
    const { slugToPath, pathToSlug } = buildVideoSlugMap(projects)
    expect(slugToPath['tran-chung-ket-2']).toBe('C:/Projects/BongDa/q1')
    expect(pathToSlug['C:/Projects/BongDa/q1']).toBe('tran-chung-ket-2')
  })
})

// ---------------------------------------------------------------------------
// seriesSlugToPath / pathToSeriesSlug round-trip
// ---------------------------------------------------------------------------
describe('seriesSlugToPath and pathToSeriesSlug', () => {
  const series = [
    { path: 'C:/Projects/BongDa', title: 'Bóng Đá', is_virtual: false },
    { path: 'C:/Projects/KhoaHoc', title: 'Khoa học vũ trụ', is_virtual: false },
    { path: 'C:/Projects/Ungrouped', title: 'whatever', is_virtual: true },
  ]

  it('resolves slug → path', () => {
    expect(seriesSlugToPath('bong-da', series)).toBe('C:/Projects/BongDa')
    expect(seriesSlugToPath('khoa-hoc-vu-tru', series)).toBe('C:/Projects/KhoaHoc')
    expect(seriesSlugToPath('chua-phan-nhom', series)).toBe('C:/Projects/Ungrouped')
  })

  it('returns null for unknown slug', () => {
    expect(seriesSlugToPath('does-not-exist', series)).toBeNull()
  })

  it('round-trip: pathToSeriesSlug then seriesSlugToPath returns original path', () => {
    for (const s of series) {
      const slug = pathToSeriesSlug(s.path, series)
      expect(slug).not.toBeNull()
      expect(seriesSlugToPath(slug, series)).toBe(s.path)
    }
  })

  it('returns null for unknown path in pathToSeriesSlug', () => {
    expect(pathToSeriesSlug('C:/NoSuchPath', series)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// videoSlugToPath / pathToVideoSlug round-trip
// ---------------------------------------------------------------------------
describe('videoSlugToPath and pathToVideoSlug', () => {
  const projects = [
    { path: 'C:/Projects/BongDa/final', name: 'Trận chung kết' },
    { path: 'C:/Projects/BongDa/semi',  name: 'Bán kết' },
  ]

  it('resolves slug → path', () => {
    expect(videoSlugToPath('tran-chung-ket', projects)).toBe('C:/Projects/BongDa/final')
    expect(videoSlugToPath('ban-ket', projects)).toBe('C:/Projects/BongDa/semi')
  })

  it('returns null for unknown slug', () => {
    expect(videoSlugToPath('ghost', projects)).toBeNull()
  })

  it('round-trip: pathToVideoSlug then videoSlugToPath returns original path', () => {
    for (const p of projects) {
      const slug = pathToVideoSlug(p.path, projects)
      expect(slug).not.toBeNull()
      expect(videoSlugToPath(slug, projects)).toBe(p.path)
    }
  })

  it('returns null for unknown path in pathToVideoSlug', () => {
    expect(pathToVideoSlug('C:/NoSuchPath', projects)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// STEP_TO_SEGMENT / SEGMENT_TO_STEP
// ---------------------------------------------------------------------------
describe('STEP_TO_SEGMENT and SEGMENT_TO_STEP', () => {
  const expectedPairs = [
    ['step1',  'noi-dung'],
    ['step2',  'giong-doc'],
    ['step3a', 'phan-canh'],
    ['step3b', 'duyet-anh'],
    ['step4',  'xuat'],
  ]

  it('STEP_TO_SEGMENT has exactly the required entries', () => {
    expect(Object.keys(STEP_TO_SEGMENT)).toHaveLength(expectedPairs.length)
    for (const [step, seg] of expectedPairs) {
      expect(STEP_TO_SEGMENT[step]).toBe(seg)
    }
  })

  it('SEGMENT_TO_STEP has exactly the required entries', () => {
    expect(Object.keys(SEGMENT_TO_STEP)).toHaveLength(expectedPairs.length)
    for (const [step, seg] of expectedPairs) {
      expect(SEGMENT_TO_STEP[seg]).toBe(step)
    }
  })

  it('STEP_TO_SEGMENT and SEGMENT_TO_STEP are exact inverses', () => {
    for (const [step, seg] of expectedPairs) {
      expect(SEGMENT_TO_STEP[STEP_TO_SEGMENT[step]]).toBe(step)
      expect(STEP_TO_SEGMENT[SEGMENT_TO_STEP[seg]]).toBe(seg)
    }
  })
})
