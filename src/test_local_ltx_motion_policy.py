import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import image_to_video_generator as generator
import visual_prompt_generator as visual
from local_ltx_motion_policy import build_motion_plan, previous_seed
from scene_orchestrator import apply_safe_motion_fallback
from video_semantic_qc import build_context, evaluate_result
from test_video_semantic_qc_policy import make_result


def make_job():
    scene = {
        "scene_id": 2, "characters": ["pip", "miso"],
        "motion_prompt": "Pip pushes the cart, presents a cup and turns while the camera pans.",
        "continuity_notes": "Steam drifts across the frame. Keep both characters visible.",
        "image_prompt": "Pip and Miso in a spa.",
        "image": {"file": "image.png", "status": "generated"},
        "video": {"provider": "local_ltx", "seed": 171201,
                  "semantic_qc": {"status": "failed", "motion_matches_prompt": False}},
    }
    return {"job_id": "test", "characters": [
        {"character_id": "pip", "name": "Pip"},
        {"character_id": "miso", "name": "Miso"},
    ], "script": {"scenes": [{"scene_id": 2, "timing": {
        "status": "passed", "render_duration_sec": 5.05}}]},
        "visuals": {"scenes": [scene]}}


class LocalLTXMotionPolicyTests(unittest.TestCase):
    def test_retry_simplifies_action_without_mutating_authored_scene(self):
        job = make_job()
        scene = job["visuals"]["scenes"][0]
        original = copy.deepcopy(scene)
        plan = build_motion_plan(job, scene, retry=True)
        self.assertEqual(plan["stage"], "single_motion")
        self.assertIn("Pip makes one small, slow head tilt", plan["prompt"])
        self.assertNotIn("cart", plan["prompt"])
        self.assertNotIn("Steam", plan["prompt"])
        self.assertEqual(scene, original)

    def test_identity_failure_uses_smaller_motion_from_structured_qc(self):
        for failure in (
            {"morphing_or_shape_drift": True}, {"anatomy_ok": False},
            {"unexpected_scene_cut": True}, {"source_frame_continuity_ok": False},
            {"characters": [{"present_throughout": False}]},
            {"characters": [{"identity_stable": False}]},
        ):
            with self.subTest(failure=failure):
                job = make_job()
                scene = job["visuals"]["scenes"][0]
                scene["video"]["semantic_qc"].update(failure)
                scene["video"]["semantic_qc"]["overall_notes"] = "verbose mist " * 300
                plan = build_motion_plan(job, scene, retry=True)
                self.assertEqual(plan["stage"], "identity_recovery")
                self.assertIn("breathes gently", plan["prompt"])
                self.assertNotIn("verbose", plan["prompt"])

    def test_safe_fallback_preserves_seed_and_uses_compact_motion(self):
        job = make_job()
        scene = job["visuals"]["scenes"][0]
        apply_safe_motion_fallback(job, 2)
        self.assertNotIn("video", scene)
        self.assertEqual(previous_seed(scene), 171201)
        plan = build_motion_plan(job, scene)
        self.assertEqual(plan["stage"], "minimal_motion")
        self.assertLess(len(plan["prompt"].split()), 80)
        self.assertNotIn("static_hold", scene["semantic_qc_policy"].values())

    def test_runway_keeps_authored_motion_and_qc_correction(self):
        job = make_job()
        with patch.object(generator, "VIDEO_PROVIDER", "runway"):
            prompt = generator.build_video_prompt(job, job["visuals"]["scenes"][0], True)
        self.assertIn("pushes the cart", prompt)
        self.assertIn("Follow the requested motion exactly.", prompt)

    def test_generated_video_records_effective_plan_for_qc_and_next_seed(self):
        job = make_job()
        scene = job["visuals"]["scenes"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.png").write_bytes(b"image")

            def generate(**kwargs):
                self.assertEqual(kwargs["previous_seed"], 171201)
                kwargs["output_file"].parent.mkdir(parents=True, exist_ok=True)
                kwargs["output_file"].write_bytes(b"video")
                return SimpleNamespace(duration_sec=5.375, model_id="LTX", width=512,
                    height=896, fps=24, num_frames=129, inference_steps=12,
                    guidance_scale=3.0, seed=171202, offload_mode="sequential")

            with (
                patch.object(generator, "PROJECT_ROOT", root),
                patch.object(generator, "VIDEO_PROVIDER", "local_ltx"),
                patch.object(generator, "validate_scene_preconditions", return_value=[]),
                patch.object(generator, "validate_local_ltx_config", return_value=[]),
                patch.object(generator, "generate_local_ltx", side_effect=generate),
            ):
                self.assertTrue(generator.generate_scene_video(None, job, scene, True, True))
        self.assertEqual(scene["video"]["motion_policy_stage"], "single_motion")
        self.assertEqual(scene["video"]["semantic_qc"]["status"], "pending")
        self.assertEqual(previous_seed(scene), 171202)
        self.assertIn("pushes the cart", scene["motion_prompt"])
        context = json.loads(build_context(job, scene, []))
        self.assertIn("head tilt", context["motion_prompt"])
        self.assertNotIn("pushes the cart", context["motion_prompt"])

    def test_motion_replan_clears_static_waiver_preserves_image_and_seed(self):
        job = make_job()
        scene = job["visuals"]["scenes"][0]
        scene["motion_strategy"] = "still_image_fallback_v1"
        scene["semantic_qc_policy"] = {"motion_mode": "static_hold"}
        image = copy.deepcopy(scene["image"])
        visual.apply_motion_only_output(job, visual.MotionPromptOutput(scenes=[
            visual.MotionPromptScene(scene_id=2, motion_prompt="Pip tilts his head.")]))
        self.assertEqual(scene["image"], image)
        self.assertNotIn("video", scene)
        self.assertNotIn("semantic_qc_policy", scene)
        self.assertNotIn("motion_strategy", scene)
        self.assertEqual(previous_seed(scene), 171201)

    def test_local_generation_and_motion_only_receive_provider_rules(self):
        spec = {"video": {"aspect_ratio": "9:16", "resolution": "512x896", "fps": 24}, "visual": {}}
        job = make_job()
        client = Mock()
        client.responses.parse.return_value.output_parsed = object()
        for provider in ("local_ltx", "runway"):
            with self.subTest(provider=provider), patch.dict(os.environ, {"VIDEO_PROVIDER": provider}):
                visual.generate_visual_prompts(client, spec, job, job["script"]["scenes"])
                full = client.responses.parse.call_args.kwargs["input"][0]["content"]
                visual.generate_motion_prompt(client, spec, job, job["script"]["scenes"][0], job["visuals"]["scenes"][0])
                motion = client.responses.parse.call_args.kwargs["input"][0]["content"]
                for content in (full, motion):
                    self.assertEqual("LOCAL LTX OVERRIDE" in content, provider == "local_ltx")

    def test_local_motion_policy_does_not_waive_motion_or_identity_failures(self):
        scene = {"video": {"provider": "local_ltx", "motion_policy_stage": "identity_recovery"}}
        result = make_result(motion=False)
        passed, errors, _ = evaluate_result(scene, result)
        self.assertFalse(passed)
        self.assertTrue(any("motion" in error for error in errors))
        result = make_result()
        result.morphing_or_shape_drift = True
        passed, _, _ = evaluate_result(scene, result)
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
