from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.voice.text_to_voice_cli import (
    split_text_for_text_to_voice,
    split_text_into_progress_segments,
)


class TestProgressSegments:
    def test_empty_returns_empty(self):
        assert split_text_into_progress_segments("", 350) == []

    def test_short_text_single_segment(self):
        assert split_text_into_progress_segments("Hello world.", 350) == ["Hello world."]

    def test_many_sentences_split_into_several_chunks(self):
        text = " ".join(f"Sentence number {i} here." for i in range(40))
        chunks = split_text_into_progress_segments(text, 120)
        # ~24 ký tự/câu, 120 ký tự/đoạn => nhiều đoạn, không phải 1
        assert len(chunks) > 5
        # ghép lại không mất từ
        joined = " ".join(chunks).split()
        assert joined == text.split()

    def test_clusters_into_multiple_chunks(self):
        # 4 câu ~26 ký tự mỗi câu; max_chars=80 => gom 2 câu/đoạn => >=2 đoạn.
        text = (
            "Alpha bravo charlie delta. Echo foxtrot golf hotel. "
            "India juliet kilo lima. Mike november oscar papa."
        )
        chunks = split_text_into_progress_segments(text, 80)
        assert len(chunks) >= 2
        # ghép lại không mất từ
        assert " ".join(chunks).split() == text.split()

    def test_oversized_single_sentence_splits_by_words(self):
        sentence = "word " * 200  # 1 câu ~1000 ký tự, không dấu kết thúc
        chunks = split_text_into_progress_segments(sentence.strip(), 100)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)


class TestBackwardCompatibility:
    def test_existing_splitter_unchanged_for_short(self):
        assert split_text_for_text_to_voice("Hi there.", 10000) == ["Hi there."]

    def test_existing_splitter_floor_still_1000(self):
        # truyền max_chars nhỏ (200) vẫn bị nâng lên sàn 1000 như cũ:
        # nếu sàn thực sự là 200 thì 1200 ký tự sẽ ra ~6 đoạn nhỏ <=200;
        # với sàn 1000 chỉ ra 1-2 đoạn và có đoạn lớn hơn 200.
        text = "A. " * 400  # 1200 ký tự
        chunks = split_text_for_text_to_voice(text, 200)
        assert max(len(c) for c in chunks) > 200  # 200 đã bị ghi đè lên sàn 1000
        assert len(chunks) <= 2
