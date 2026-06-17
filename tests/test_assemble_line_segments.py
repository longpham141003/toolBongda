from app.pipeline.subtitle_store import assemble_line_segments


def test_cumulative_timing_with_pause():
    lines = [{"text": "A", "edited": False}, {"text": "B", "edited": True}, {"text": "C"}]
    segs = assemble_line_segments(lines, [1.0, 2.0, 0.5], pause=0.25)
    assert [s["index"] for s in segs] == [1, 2, 3]
    assert (segs[0]["start"], segs[0]["end"]) == (0.0, 1.0)
    assert (segs[1]["start"], segs[1]["end"]) == (1.25, 3.25)   # 1.0 + 0.25 pause
    assert (segs[2]["start"], segs[2]["end"]) == (3.5, 4.0)     # 3.25 + 0.25 pause
    assert segs[1]["edited"] is True
    assert all(s["timing_source"] == "measured" for s in segs)
    assert segs[0]["text"] == "A"


def test_zero_duration_gets_min_span():
    segs = assemble_line_segments([{"text": "A"}], [0.0])
    assert segs[0]["end"] > segs[0]["start"]


def test_missing_duration_treated_as_zero():
    segs = assemble_line_segments([{"text": "A"}, {"text": "B"}], [1.0])  # 2nd dur missing
    assert segs[1]["end"] > segs[1]["start"]
    assert segs[1]["start"] == 1.25
