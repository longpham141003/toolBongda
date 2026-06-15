/**
 * routing.js — pure-logic utilities for converting between filesystem paths
 * and URL slugs for series ("dự án") and videos.
 *
 * No React, no side effects — all functions are pure.
 */

// ---------------------------------------------------------------------------
// slugify
// ---------------------------------------------------------------------------

/**
 * Convert an arbitrary display name to a URL-safe slug.
 *
 * Algorithm (matches the inline expression in App.jsx):
 *   1. Lowercase
 *   2. NFD-normalise so combining diacritics become separate code points
 *   3. Strip combining diacritical marks (U+0300–U+036F)
 *   4. Replace runs of non-[a-z0-9] with a single dash
 *   5. Trim leading/trailing dashes
 *   6. Fall back to "muc" if the result is empty
 *
 * @param {string} name
 * @returns {string}
 */
export function slugify(name) {
  if (typeof name !== 'string') return 'muc'
  // Pre-replace Đ/đ (U+0110/U+0111): these characters have no NFD decomposition
  // into a base letter + combining mark, so they must be mapped explicitly.
  const result = name
    .replace(/[Đđ]/g, 'd')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
  return result || 'muc'
}

// ---------------------------------------------------------------------------
// Internal collision-safe slug builder
// ---------------------------------------------------------------------------

/**
 * Build forward (slugToPath) and reverse (pathToSlug) lookup objects from an
 * array of items, given a function that derives the raw (pre-collision) slug
 * for each item.
 *
 * Collision resolution: if two items yield the same slug the second one gets
 * suffix "-2", the third gets "-3", and so on — determined purely by array
 * order (stable / deterministic).
 *
 * @param {Array<{path: string}>} items
 * @param {(item: object) => string} getSlug
 * @returns {{ slugToPath: object, pathToSlug: object }}
 */
function buildSlugMap(items, getSlug) {
  const slugToPath = {}
  const pathToSlug = {}
  // Track how many times each base slug has been used so far
  const baseCount = {}

  for (const item of items) {
    const base = getSlug(item)
    if (!(base in baseCount)) {
      baseCount[base] = 0
    }
    baseCount[base] += 1
    const count = baseCount[base]
    const slug = count === 1 ? base : `${base}-${count}`

    slugToPath[slug] = item.path
    pathToSlug[item.path] = slug
  }

  return { slugToPath, pathToSlug }
}

// ---------------------------------------------------------------------------
// buildSeriesSlugMap
// ---------------------------------------------------------------------------

/**
 * Build slug↔path maps for a series array.
 *
 * A virtual series (is_virtual === true) always receives the fixed slug
 * "chua-phan-nhom" regardless of its title.
 *
 * @param {Array<{path: string, title: string, is_virtual?: boolean}>} series
 * @returns {{ slugToPath: object, pathToSlug: object }}
 */
export function buildSeriesSlugMap(series) {
  return buildSlugMap(series, (s) =>
    s.is_virtual === true ? 'chua-phan-nhom' : slugify(s.title)
  )
}

// ---------------------------------------------------------------------------
// buildVideoSlugMap
// ---------------------------------------------------------------------------

/**
 * Build slug↔path maps for a projects (video) array.
 * Slug is derived from project.name.
 *
 * @param {Array<{path: string, name: string}>} projects
 * @returns {{ slugToPath: object, pathToSlug: object }}
 */
export function buildVideoSlugMap(projects) {
  return buildSlugMap(projects, (p) => slugify(p.name))
}

// ---------------------------------------------------------------------------
// Lookup helpers — series
// ---------------------------------------------------------------------------

/**
 * Resolve a slug to the matching series path, or null if not found.
 * Builds the slug map internally on each call; callers with hot paths
 * should use buildSeriesSlugMap directly and cache the result.
 *
 * @param {string} slug
 * @param {Array<{path: string, title: string, is_virtual?: boolean}>} series
 * @returns {string|null}
 */
export function seriesSlugToPath(slug, series) {
  const { slugToPath } = buildSeriesSlugMap(series)
  return slugToPath[slug] ?? null
}

/**
 * Resolve a filesystem path to its series slug, or null if not found.
 *
 * @param {string} path
 * @param {Array<{path: string, title: string, is_virtual?: boolean}>} series
 * @returns {string|null}
 */
export function pathToSeriesSlug(path, series) {
  const { pathToSlug } = buildSeriesSlugMap(series)
  return pathToSlug[path] ?? null
}

// ---------------------------------------------------------------------------
// Lookup helpers — videos
// ---------------------------------------------------------------------------

/**
 * Resolve a slug to the matching project path, or null if not found.
 * Builds the slug map internally on each call; callers with hot paths
 * should use buildVideoSlugMap directly and cache the result.
 *
 * @param {string} slug
 * @param {Array<{path: string, name: string}>} projects
 * @returns {string|null}
 */
export function videoSlugToPath(slug, projects) {
  const { slugToPath } = buildVideoSlugMap(projects)
  return slugToPath[slug] ?? null
}

/**
 * Resolve a filesystem path to its video slug, or null if not found.
 *
 * @param {string} path
 * @param {Array<{path: string, name: string}>} projects
 * @returns {string|null}
 */
export function pathToVideoSlug(path, projects) {
  const { pathToSlug } = buildVideoSlugMap(projects)
  return pathToSlug[path] ?? null
}

// ---------------------------------------------------------------------------
// Workflow step ↔ URL segment constants
// ---------------------------------------------------------------------------

/**
 * Maps internal workflow step IDs to their URL segment equivalents.
 * @type {Record<string, string>}
 */
export const STEP_TO_SEGMENT = {
  step1:  'noi-dung',
  step2:  'giong-doc',
  step3a: 'phan-canh',
  step3b: 'duyet-anh',
  step4:  'xuat',
}

/**
 * Inverse of STEP_TO_SEGMENT — maps URL segments back to step IDs.
 * @type {Record<string, string>}
 */
export const SEGMENT_TO_STEP = Object.fromEntries(
  Object.entries(STEP_TO_SEGMENT).map(([step, seg]) => [seg, step])
)
