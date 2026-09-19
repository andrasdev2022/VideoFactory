import tempfile
import unittest

from pathlib import Path

from local_ltx_provider import (
    LocalLTXConfig,
    build_command,
    calculate_num_frames,
    calculate_seed,
    validate_config,
)


class LocalLTXProviderTests(
    unittest.TestCase
):

    def make_config(
        self,
        *,
        width=512,
        height=896,
    ) -> LocalLTXConfig:

        current_file = Path(
            __file__
        )

        return LocalLTXConfig(
            python_exe=current_file,
            worker_file=current_file,
            model_id="Lightricks/LTX-Video",
            width=width,
            height=height,
            fps=24,
            inference_steps=20,
            guidance_scale=3.0,
            seed_base=171198,
            timeout_sec=7200,
            offload_mode="sequential",
        )


    def test_frame_count_is_ltx_compatible_and_covers_duration(
        self,
    ):

        for duration in (
            2.75,
            4.05,
            6.75,
        ):

            frames = calculate_num_frames(
                duration,
                24,
            )

            self.assertEqual(
                (
                    frames
                    - 1
                )
                % 8,
                0,
            )

            self.assertGreaterEqual(
                frames
                / 24.0,
                duration,
            )


    def test_short_scene_rounds_to_next_valid_frame_group(
        self,
    ):

        self.assertEqual(
            calculate_num_frames(
                2.75,
                24,
            ),
            73,
        )


    def test_retry_seed_increments_previous_local_seed(
        self,
    ):

        config = self.make_config()

        first = calculate_seed(
            config=config,
            scene_id=5,
        )

        retry = calculate_seed(
            config=config,
            scene_id=5,
            previous_seed=first,
        )

        self.assertEqual(
            first,
            171203,
        )

        self.assertEqual(
            retry,
            171204,
        )


    def test_config_requires_dimensions_divisible_by_32(
        self,
    ):

        config = self.make_config(
            width=500,
            height=896,
        )

        errors = validate_config(
            config
        )

        self.assertTrue(
            any(
                "divisible by 32"
                in error
                for error
                in errors
            )
        )


    def test_build_command_contains_low_vram_controls(
        self,
    ):

        config = self.make_config()

        with tempfile.TemporaryDirectory() as directory:

            root = Path(
                directory
            )

            command = build_command(
                config=config,
                input_image=
                    root
                    / "scene.png",
                output_file=
                    root
                    / "scene.mp4",
                prompt="Small controlled motion.",
                num_frames=73,
                seed=171199,
            )

        joined = " ".join(
            command
        )

        self.assertIn(
            "--offload sequential",
            joined,
        )

        self.assertIn(
            "--num-frames 73",
            joined,
        )

        self.assertIn(
            "--width 512",
            joined,
        )

        self.assertIn(
            "--height 896",
            joined,
        )

    def test_worker_binds_image_to_video_pipeline_name(
        self,
    ):

        worker_file = (
            Path(__file__)
            .with_name(
                "local_ltx_worker.py"
            )
        )

        source = worker_file.read_text(
            encoding="utf-8",
        )

        self.assertIn(
            "LTXImageToVideoPipeline,",
            source,
        )

        self.assertIn(
            "pipeline = (\n"
            "            LTXImageToVideoPipeline\n"
            "            .from_pretrained(",
            source,
        )

        self.assertNotIn(
            "            DiffusionPipeline,\n"
            "            export_to_video,",
            source,
        )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
