from main_optimized import _requires_render_output


def test_batch_replay_skips_rendering_when_every_output_is_disabled():
    config = {
        "pipeline": {"save_video": False, "show_in_web": False},
        "video_saver_node": {"save_conflict_clips": False},
        "show_node": {"imshow": False},
    }
    assert _requires_render_output(config) is False


def test_any_visual_output_keeps_rendering_enabled():
    config = {
        "pipeline": {"save_video": False, "show_in_web": True},
        "video_saver_node": {"save_conflict_clips": False},
        "show_node": {"imshow": False},
    }
    assert _requires_render_output(config) is True
