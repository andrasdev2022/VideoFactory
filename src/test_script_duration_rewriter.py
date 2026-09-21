import unittest

import script_duration_rewriter

from script_duration_rewriter import (
    DurationRewriteOutput,
    DurationRewriteScene,
    allocate_render_targets,
    apply_rewrite,
    build_rewrite_plan,
    validate_rewrite,
)


def make_job(
    total_mode="long",
):

    if total_mode == "long":

        render_durations = [
            3.0,
            9.0,
            8.0,
            8.0,
            7.4,
        ]

    else:

        render_durations = [
            3.0,
            5.0,
            5.0,
            5.0,
            6.0,
        ]

    texts = [
        "My cat fired me today.",
        (
            "I entered the office and found my cat "
            "sitting proudly in the CEO chair."
        ),
        (
            "He reviewed my work, knocked over my coffee, "
            "and promoted himself without hesitation."
        ),
        (
            "Everyone nodded through his ridiculous slideshow "
            "while I begged for one more chance."
        ),
        (
            "He fired me, then sent a LinkedIn request "
            "before I reached the elevator."
        ),
    ]

    scenes = []

    for index, (
        render_duration,
        text,
    ) in enumerate(
        zip(
            render_durations,
            texts,
        ),
        start=1,
    ):

        headroom = 0.3

        scenes.append(
            {
                "scene_id":
                    index,

                "type":
                    (
                        "hook"
                        if index == 1
                        else "setup"
                    ),

                "voiceover":
                    text,

                "voice": {
                    "status":
                        "generated",
                },

                "timing": {
                    "status":
                        "passed",

                    "voice_duration_sec":
                        render_duration
                        - headroom,

                    "render_duration_sec":
                        render_duration,

                    "headroom_sec":
                        headroom,

                    "min_video_duration_sec":
                        2.0,

                    "max_video_duration_sec":
                        10.0,
                },
            }
        )

    total = sum(
        render_durations
    )

    return {
        "script": {
            "voiceover":
                " ".join(
                    texts
                ),

            "scenes":
                scenes,
        },

        "visuals": {
            "scenes": [
                {
                    "scene_id":
                        index,

                    "image": {
                        "status":
                            "generated",
                    },

                    "video": {
                        "status":
                            "generated",
                    },
                }
                for index in range(
                    1,
                    6,
                )
            ],
        },

        "timing_summary": {
            "status":
                "complete",

            "total_render_duration_sec":
                total,

            "target_duration_sec":
                30.0,

            "script_revision_recommended":
                True,
        },
    }


class ScriptDurationRewriterTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):

        self.old_hook = (
            script_duration_rewriter
            .PROTECT_HOOK_MAX_SEC
        )

        script_duration_rewriter.PROTECT_HOOK_MAX_SEC = (
            3.5
        )


    def tearDown(
        self,
    ):

        script_duration_rewriter.PROTECT_HOOK_MAX_SEC = (
            self.old_hook
        )


    def test_allocation_hits_exact_target(
        self,
    ):

        metrics = [
            {
                "scene_id": 1,
                "protected": True,
                "current_render_duration_sec": 3.0,
                "min_render_duration_sec": 2.0,
                "max_render_duration_sec": 10.0,
            },
            {
                "scene_id": 2,
                "protected": False,
                "current_render_duration_sec": 9.0,
                "min_render_duration_sec": 2.0,
                "max_render_duration_sec": 10.0,
            },
            {
                "scene_id": 3,
                "protected": False,
                "current_render_duration_sec": 8.0,
                "min_render_duration_sec": 2.0,
                "max_render_duration_sec": 10.0,
            },
            {
                "scene_id": 4,
                "protected": False,
                "current_render_duration_sec": 8.0,
                "min_render_duration_sec": 2.0,
                "max_render_duration_sec": 10.0,
            },
            {
                "scene_id": 5,
                "protected": False,
                "current_render_duration_sec": 7.4,
                "min_render_duration_sec": 2.0,
                "max_render_duration_sec": 10.0,
            },
        ]

        targets = allocate_render_targets(
            metrics,
            30.0,
        )

        self.assertAlmostEqual(
            sum(
                targets.values()
            ),
            30.0,
            places=3,
        )

        self.assertEqual(
            targets[1],
            3.0,
        )


    def test_long_job_creates_shorten_plan(
        self,
    ):

        job = make_job(
            "long"
        )

        spec = {
            "video": {
                "target_duration_sec":
                    30,
            },
        }

        plan = build_rewrite_plan(
            job,
            spec,
        )

        self.assertEqual(
            plan[
                "mode"
            ],
            "shorten",
        )

        self.assertNotIn(
            1,
            plan[
                "rewrite_scene_ids"
            ],
        )

        self.assertEqual(
            set(
                plan[
                    "rewrite_scene_ids"
                ]
            ),
            {
                2,
                3,
                4,
                5,
            },
        )

        self.assertAlmostEqual(
            sum(
                budget[
                    "target_render_duration_sec"
                ]
                for budget in plan[
                    "budgets"
                ]
            ),
            35.0,
            places=3,
        )


    def test_short_job_creates_expand_plan(
        self,
    ):

        job = make_job(
            "short"
        )

        spec = {
            "video": {
                "target_duration_sec":
                    30,
            },
        }

        plan = build_rewrite_plan(
            job,
            spec,
        )

        self.assertEqual(
            plan[
                "mode"
            ],
            "expand",
        )

        self.assertAlmostEqual(
            sum(
                budget[
                    "target_render_duration_sec"
                ]
                for budget in plan[
                    "budgets"
                ]
            ),
            25.0,
            places=3,
        )


    def test_validation_rejects_wrong_scene_set(
        self,
    ):

        plan = {
            "mode":
                "shorten",

            "rewrite_scene_ids":
                [
                    2,
                    3,
                ],

            "budgets": [
                {
                    "scene_id": 2,
                    "text": "one two three four five six",
                    "current_words": 6,
                    "min_words": 1,
                    "max_words": 5,
                    "max_chars": 100,
                },
                {
                    "scene_id": 3,
                    "text": "one two three four five six",
                    "current_words": 6,
                    "min_words": 1,
                    "max_words": 5,
                    "max_chars": 100,
                },
            ],
        }

        output = DurationRewriteOutput(
            mode="shorten",
            scenes=[
                DurationRewriteScene(
                    scene_id=2,
                    voiceover="one two three",
                ),
            ],
        )

        errors = validate_rewrite(
            plan,
            output,
        )

        self.assertTrue(
            errors
        )


    def test_apply_invalidates_changed_artifacts_and_rebuilds_script(
        self,
    ):

        job = make_job(
            "long"
        )

        spec = {
            "video": {
                "target_duration_sec":
                    30,
            },
        }

        plan = build_rewrite_plan(
            job,
            spec,
        )

        output = DurationRewriteOutput(
            mode="shorten",
            scenes=[
                DurationRewriteScene(
                    scene_id=2,
                    voiceover=(
                        "I found my cat "
                        "in the CEO chair."
                    ),
                ),
                DurationRewriteScene(
                    scene_id=3,
                    voiceover=(
                        "He reviewed my work "
                        "and promoted himself."
                    ),
                ),
                DurationRewriteScene(
                    scene_id=4,
                    voiceover=(
                        "Everyone nodded while "
                        "I begged again."
                    ),
                ),
                DurationRewriteScene(
                    scene_id=5,
                    voiceover=(
                        "He fired me, then "
                        "sent a LinkedIn request."
                    ),
                ),
            ],
        )

        changed = apply_rewrite(
            job,
            plan,
            output,
        )

        self.assertEqual(
            changed,
            [
                2,
                3,
                4,
                5,
            ],
        )

        self.assertNotIn(
            "timing_summary",
            job,
        )

        self.assertEqual(
            job[
                "script"
            ][
                "duration_normalization"
            ][
                "status"
            ],
            "pending_remeasure",
        )

        self.assertTrue(
            job[
                "script"
            ][
                "voiceover"
            ]
            .startswith(
                "My cat fired me today."
            )
        )

        for scene_id in changed:

            scene = (
                job[
                    "script"
                ][
                    "scenes"
                ][
                    scene_id - 1
                ]
            )

            self.assertNotIn(
                "voice",
                scene,
            )

            self.assertNotIn(
                "timing",
                scene,
            )

            visual = (
                job[
                    "visuals"
                ][
                    "scenes"
                ][
                    scene_id - 1
                ]
            )

            self.assertNotIn(
                "video",
                visual,
            )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
