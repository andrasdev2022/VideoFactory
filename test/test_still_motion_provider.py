import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import image_to_video_generator as generator
import pipeline_orchestrator as master
import still_motion_provider as provider
from local_ltx_motion_policy import system_prompt
from scene_orchestrator import choose_next_action, ACTION_STOP_VIDEO
from test_scene_orchestrator import make_state
from test_video_semantic_qc_policy import make_result
from video_semantic_qc import build_context, evaluate_result


class StillMotionTests(unittest.TestCase):
    def test_config_and_frame_rounding(self):
        with patch.dict(os.environ, {"STILL_MOTION_MODE": "zoom", "STILL_MOTION_MAX_ZOOM": "1.05"}):
            config = provider.load_config()
        self.assertEqual(provider.frame_count(5.05, config), 122)
        self.assertEqual(provider.frame_count(5.0, config), 120)
        for duration in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                provider.frame_count(duration, config)
        for mode, zoom in (("pan", "1.05"), ("zoom", "nan"), ("zoom", "1.5")):
            with patch.dict(os.environ, {"STILL_MOTION_MODE": mode, "STILL_MOTION_MAX_ZOOM": zoom}):
                with self.assertRaises(ValueError):
                    provider.load_config()

    def test_hold_command_no_zoom(self):
        command = provider.build_command(Path("image with spaces.png"), Path("out.mp4"), 5.05, provider.Config(mode="hold"))
        self.assertIn("z='1'", command[command.index("-vf") + 1])
        self.assertEqual(command[command.index("-frames:v") + 1], "122")

    def test_preflight_needs_neither_runway_key_nor_ltx(self):
        with (
            patch.dict(os.environ, {"VIDEO_PROVIDER": "still_motion", "OPENAI_API_KEY": "test",
                "ELEVENLABS_API_KEY": "test", "SERVICE_PREFLIGHT_ENABLED": "0"}, clear=True),
            patch.object(master.shutil, "which", return_value="tool"),
            patch.object(master.subprocess, "Popen") as popen,
        ):
            master.preflight()
            self.assertIsNone(master.start_local_ltx_service())
            popen.assert_not_called()

    def test_semantic_failure_does_not_retry_deterministic_render(self):
        state = make_state(image_status="generated", image_file="image.png", image_qc="passed",
            image_semantic_qc="passed", video_status="generated", video_file="video.mp4",
            video_provider="still_motion", video_qc="passed", video_semantic_qc="failed")
        self.assertEqual(choose_next_action(state, 1, 1, 2, 4), ACTION_STOP_VIDEO)

    def test_zoom_qc_does_not_waive_motion_or_anatomy_failure(self):
        scene = {"semantic_qc_policy": {"motion_mode": "camera_only"}}
        self.assertFalse(evaluate_result(scene, make_result(motion=False))[0])
        result = make_result()
        result.anatomy_ok = False
        self.assertFalse(evaluate_result(scene, result)[0])
        self.assertIn("STILL-MOTION OVERRIDE", system_prompt("base", "still_motion"))
        self.assertEqual(system_prompt("base", "runway"), "base")

    def test_failed_render_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image, output = root / "image.png", root / "out.mp4"
            image.write_bytes(b"image")
            output.write_bytes(b"old")
            with patch.object(provider.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaises(RuntimeError):
                    provider.generate(input_image=image, output_file=output, duration_sec=1, config=provider.Config())
            self.assertEqual(output.read_bytes(), b"old")
            self.assertTrue(output.with_suffix(".still-motion.log").exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_real_render_through_shared_generator_and_cache(self):
        from PIL import Image
        for mode in ("zoom", "hold"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                Image.new("RGB", (256, 448), "orange").save(root / "image.png")
                scene = {"scene_id": 1, "motion_prompt": "A character waves.",
                    "image": {"file": "image.png", "qc": {"status": "passed"},
                              "semantic_qc": {"status": "passed"}}}
                job = {"job_id": "test", "script": {"scenes": [{"scene_id": 1,
                    "timing": {"status": "passed", "render_duration_sec": 2.05}}]}}
                with (
                    patch.dict(os.environ, {"STILL_MOTION_MODE": mode, "STILL_MOTION_MAX_ZOOM": "1.05"}),
                    patch.object(generator, "PROJECT_ROOT", root),
                    patch.object(generator, "VIDEO_PROVIDER", "still_motion"),
                    patch.object(generator, "generate_local_ltx") as ltx,
                ):
                    self.assertTrue(generator.generate_scene_video(None, job, scene, False, False))
                    self.assertFalse(generator.generate_scene_video(None, job, scene, False, False))
                    ltx.assert_not_called()
                    self.assertEqual(scene["video"]["provider"], "still_motion")
                    self.assertEqual(scene["video"]["qc"]["status"], "pending")
                    self.assertNotIn("waves", json.loads(build_context(job, scene, []))["motion_prompt"])
                    output = root / scene["video"]["file"]
                    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_frames,r_frame_rate", "-of", "json", str(output)], text=True))
                    self.assertEqual(probe["streams"][0]["nb_frames"], "50")
                    self.assertEqual(probe["streams"][0]["width"], 720)
                    self.assertEqual(probe["streams"][0]["height"], 1280)
                    scene["video"]["still_motion_config"]["max_zoom"] = 1.08
                    self.assertFalse(generator.video_metadata_matches_current_request(
                        scene, output, 2.05, 50 / 24, "image.png", "still_motion"))


if __name__ == "__main__":
    unittest.main()
