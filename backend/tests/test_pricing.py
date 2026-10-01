from app import pricing


def test_video_skus_per_second_by_resolution():
    skus = {"duration_seconds_480p": "0.05", "duration_seconds_720p": "0.10", "duration_seconds_1080p": "0.15"}
    cost, note = pricing.video_skus_cost(skus, resolution="720p", duration=5)
    assert round(cost, 4) == 0.5 and note == ""


def test_video_skus_audio_and_cents():
    cost, _ = pricing.video_skus_cost({"duration_seconds_with_audio": "0.40", "duration_seconds_without_audio": "0.20"},
                                      resolution="720p", duration=8)
    assert round(cost, 4) == 1.6
    cost, _ = pricing.video_skus_cost({"cents_per_second_output_720p": "6", "cents_per_second_output_1080p": "12"},
                                      resolution="1080p", duration=5)
    assert round(cost, 4) == 0.6


def test_video_skus_tokens_and_minimum():
    cost, note = pricing.video_skus_cost({"video_tokens": "0.0000012", "minimum_cents_per_generation": "50"},
                                         resolution="480p", duration=5)
    assert cost >= 0.5 and "tokens" in note
    assert pricing.video_skus_cost({"weird": "x"}, resolution="720p", duration=5)[0] is None


def test_duration_and_resolution_fit():
    model = {"supported_durations": [4, 6, 8], "supported_resolutions": ["720p", "1080p"]}
    assert pricing.video_duration_for(model, 5.1) == 6
    assert pricing.video_duration_for(model, 12) == 8
    assert pricing.video_resolution_for(model, "480p") == "720p"


def test_image_and_llm_prices_from_catalog(fake, client):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        c = pricing.image_cost(db, "google/gemini-3-pro-image-preview", "4K")
        assert c.value == 0.24 and c.source == "live"
        c = pricing.image_cost(db, "google/gemini-2.5-flash-image", "1K")
        assert c.value == 0.039
        llm = pricing.llm_cost("anthropic/claude-sonnet-4.5", 1_000_000, 100_000)
        assert round(llm.value, 4) == 4.5
        tts = pricing.tts_cost(db, "mistralai/voxtral-mini-tts-2603", 10_000, 600)
        assert round(tts.value, 4) == 0.16 and tts.source == "live"
    finally:
        db.close()
