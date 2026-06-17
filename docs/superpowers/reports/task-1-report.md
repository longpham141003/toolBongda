# Task 1 Report: Bộ băm cụm câu mịn

## Files Changed

- **Created:** `tests/test_voice_segmentation.py` (91 lines, 7 tests in 2 classes)
- **Modified:** `app/voice/text_to_voice_cli.py` (lines 67–114 refactored + new function added)

## What Was Done

### Step 1 — Test file created
`tests/test_voice_segmentation.py` created verbatim from the plan.

### Step 2 — Confirmed FAIL (ImportError)
```
ImportError: cannot import name 'split_text_into_progress_segments' from 'app.voice.text_to_voice_cli'
```

### Step 3 — Refactored `app/voice/text_to_voice_cli.py`

The original `split_text_for_text_to_voice` function (lines 67–114) was replaced with:

1. `_split_text_by_chars(text, max_chars, *, floor, ceil)` — shared private helper implementing the chunking loop with floor/ceil clamping (used by `split_text_for_text_to_voice`).
2. `split_text_for_text_to_voice(text, max_chars)` — thin wrapper, calls `_split_text_by_chars` with `floor=1000, ceil=12000` (behavior UNCHANGED).
3. `split_text_into_progress_segments(text, max_chars)` — new function. Splits at every sentence boundary producing one chunk per sentence, word-splits oversized sentences. Uses `max_chars` clamped to [80, 2000].

**Note on plan deviation:** The plan's Step 3 code showed `split_text_into_progress_segments` as a simple call to `_split_text_by_chars(text, max_chars, floor=80, ceil=2000)`. However, the plan's test `test_floor_allows_small_chunks` passes text="One. Two. Three. Four. Five. Six. Seven. Eight." (47 chars) with `max_chars=80` and asserts `len(chunks) >= 2`. With the plan's shared accumulation logic, the 47-char text fits in one 80-char chunk and the test cannot pass. The plan's test implies per-sentence splitting (not accumulation) for the progress function. Therefore, `split_text_into_progress_segments` was implemented with per-sentence splitting semantics: each sentence becomes its own chunk, oversized sentences are word-split. This fully satisfies all 7 tests while keeping `split_text_for_text_to_voice` behavior unchanged.

### Step 4 — Confirmed PASS

```
python -m pytest tests/test_voice_segmentation.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.3, pluggy-1.6.0
collected 7 items

tests/test_voice_segmentation.py::TestProgressSegments::test_empty_returns_empty PASSED         [ 14%]
tests/test_voice_segmentation.py::TestProgressSegments::test_short_text_single_segment PASSED   [ 28%]
tests/test_voice_segmentation.py::TestProgressSegments::test_many_sentences_split_into_several_chunks PASSED [ 42%]
tests/test_voice_segmentation.py::TestProgressSegments::test_floor_allows_small_chunks PASSED   [ 57%]
tests/test_voice_segmentation.py::TestProgressSegments::test_oversized_single_sentence_splits_by_words PASSED [ 71%]
tests/test_voice_segmentation.py::TestBackwardCompatibility::test_existing_splitter_unchanged_for_short PASSED [ 85%]
tests/test_voice_segmentation.py::TestBackwardCompatibility::test_existing_splitter_floor_still_1000 PASSED [100%]

============================== 7 passed in 0.02s ==============================
```

### Step 5 — Committed

```
git add app/voice/text_to_voice_cli.py tests/test_voice_segmentation.py
git commit -m "feat(voice): add fine-grained sentence-cluster splitter for progress"
```

Commit hash: `129ea64`

## Concerns

- **Plan vs. test inconsistency:** The plan's Step 3 code (shared `_split_text_by_chars` wrapper) cannot pass `test_floor_allows_small_chunks` as written. The test's text (47 chars) is shorter than `max_chars=80`, so the shared accumulation logic returns it as a single chunk. The implementation uses per-sentence splitting for `split_text_into_progress_segments` to honor the test. This is a deviation from the plan's exact Step 3 code, but it is consistent with the function's documented purpose ("băm mịn theo từng cụm câu") and passes all 7 tests.
- **External behavior of `split_text_for_text_to_voice`:** Unchanged. The refactored `_split_text_by_chars` helper is identical to the original function's body; `split_text_for_text_to_voice` remains a thin wrapper with `floor=1000, ceil=12000`.

---

## Follow-up Fix (2026-06-17): Cluster accumulation + test rename

**What changed:**

- `split_text_into_progress_segments` in `app/voice/text_to_voice_cli.py` was updated to delegate to `_split_text_by_chars(text, max_chars, floor=80, ceil=2000)` (cluster-accumulation design), replacing the previous per-sentence body.
- `test_floor_allows_small_chunks` in `tests/test_voice_segmentation.py` was replaced with `test_clusters_into_multiple_chunks`: uses 4 longer sentences (~26 chars each) so accumulation at max_chars=80 yields ≥2 chunks, and verifies no words are lost.

**pytest command:**
```
python -m pytest tests/test_voice_segmentation.py -v
```

**Full output:**
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.3, pluggy-1.6.0
collected 7 items

tests/test_voice_segmentation.py::TestProgressSegments::test_empty_returns_empty PASSED         [ 14%]
tests/test_voice_segmentation.py::TestProgressSegments::test_short_text_single_segment PASSED   [ 28%]
tests/test_voice_segmentation.py::TestProgressSegments::test_many_sentences_split_into_several_chunks PASSED [ 42%]
tests/test_voice_segmentation.py::TestProgressSegments::test_clusters_into_multiple_chunks PASSED [ 57%]
tests/test_voice_segmentation.py::TestProgressSegments::test_oversized_single_sentence_splits_by_words PASSED [ 71%]
tests/test_voice_segmentation.py::TestBackwardCompatibility::test_existing_splitter_unchanged_for_short PASSED [ 85%]
tests/test_voice_segmentation.py::TestBackwardCompatibility::test_existing_splitter_floor_still_1000 PASSED [100%]

============================== 7 passed in 0.03s ==============================
```

**Commit:** `46812ff` — `fix(voice): cluster sentences in progress splitter; fix splitter test`
