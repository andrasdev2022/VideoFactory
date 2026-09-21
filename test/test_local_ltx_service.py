import unittest

from local_ltx_service import (
    validate_request,
)


class LocalLTXServiceTests(
    unittest.TestCase
):

    def make_request(
        self,
    ) -> dict:

        return {
            "image":
                "scene.png",

            "output":
                "scene.mp4",

            "prompt":
                "Small controlled motion.",

            "width":
                512,

            "height":
                896,

            "fps":
                24,

            "num_frames":
                49,

            "steps":
                12,

            "guidance_scale":
                3.0,

            "seed":
                171199,
        }


    def test_valid_request_passes(
        self,
    ):

        validate_request(
            self.make_request()
        )


    def test_request_requires_ltx_frame_shape(
        self,
    ):

        request = self.make_request()

        request[
            "num_frames"
        ] = 48

        with self.assertRaises(
            RuntimeError
        ):

            validate_request(
                request
            )


    def test_request_requires_dimensions_divisible_by_32(
        self,
    ):

        request = self.make_request()

        request[
            "width"
        ] = 500

        with self.assertRaises(
            RuntimeError
        ):

            validate_request(
                request
            )


if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )
