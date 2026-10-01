from app.pipeline import text
from app.pipeline.scenes import normalize_plan
from app.pipeline.schemas import PlannedScene


def test_sentence_split_multilingual():
    segs = text.segment_script(
        "Dr. Smith arrived at 10 p.m. in the U.S. capital. Nobody knew why!\n\n"
        "W 1939 r. Niemcy zaatakowały Polskę, np. Gdańsk. Wojna trwała długo.\n"
        "Am 3. Mai kam er an, z.B. mit dem Zug. Es war 1943. Dann ging alles schnell."
    )
    assert [s.text for s in segs] == [
        "Dr. Smith arrived at 10 p.m. in the U.S. capital.",
        "Nobody knew why!",
        "W 1939 r. Niemcy zaatakowały Polskę, np. Gdańsk.",
        "Wojna trwała długo.",
        "Am 3. Mai kam er an, z.B. mit dem Zug.",
        "Es war 1943.",
        "Dann ging alles schnell.",
    ]


def test_metrics_and_repetition():
    script = ("The vault was sealed for centuries. " * 3) + "Nobody opened it again until the war ended in silence."
    m = text.script_metrics(script, 150, 15, 25)
    assert m["words"] == text.word_count(script)
    assert m["repeated_sentences"][0]["count"] == 3
    assert m["within_target"] is False


def test_chunking_keeps_order():
    segs = text.segment_script(" ".join(f"Sentence number {i} is here." for i in range(300)))
    chunks = text.chunk_segments(segs, 200)
    flat = [s.index for c in chunks for s in c]
    assert flat == list(range(300))
    assert all(sum(s.words for s in c) <= 260 for c in chunks)


def test_srt_and_timecodes():
    srt = text.build_srt([(0.0, 4.0, "Hello world. This is a test."), (4.0, 2.5, "Second scene.")])
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "00:00:06,500" in srt
    assert text.timecode(3725) == "1:02:05"
    assert text.timecode(65) == "1:05"


def _ps(start, end):
    return PlannedScene(start=start, end=end, visual_description="d", prompt="p", asset_type="image+motion",
                        asset_type_reason="r", motion="zoom-in")


def test_normalize_plan_fills_gaps_and_overlaps():
    segs = {i: text.Segment(i, f"S{i}.", 0, 1) for i in range(10, 21)}
    out = normalize_plan([_ps(10, 12), _ps(12, 14), _ps(17, 18)], 10, 20, segs, "style")
    covered = [i for s in out for i in range(s["start"], s["end"] + 1)]
    assert covered == list(range(10, 21))  # sobreposição cortada, buraco 15-16 e final 19-20 absorvidos
    assert [(s["start"], s["end"]) for s in out] == [(10, 12), (13, 16), (17, 20)]
    assert out[0]["asset_type"] == "IMAGE_MOTION" and out[0]["motion"] == "zoom_in"
    out = normalize_plan([_ps(10, 12), _ps(13, 14)], 10, 20, segs, "style")
    assert [(s["start"], s["end"]) for s in out][-1] == (15, 20)
    assert out[-1]["visual_description"].startswith("Cena gerada automaticamente")


def test_split_for_tts_respects_limit_without_losing_text():
    from app.pipeline.narration import split_for_tts

    script = " ".join(f"This is sentence number {i}." for i in range(400))
    parts = split_for_tts(script, 500)
    assert len(parts) > 1 and all(len(p) <= 500 for p in parts)
    assert " ".join(parts) == script
