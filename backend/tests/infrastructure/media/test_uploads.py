import os
import tempfile
import unittest

from app.infrastructure.config import Settings
from app.infrastructure.media.uploads import validate_temp_dir


class ValidateTempDirTests(unittest.TestCase):
    """`TEMP_DIR` reached production as a Windows path and nothing noticed:
    `C:` is a legal directory name on Linux, so `os.makedirs` succeeded and the
    service booted healthy while writing into a junk *relative* directory. The
    failure surfaced much later, as FFmpeg's `Protocol not found` at the
    normalize step, because FFmpeg reads everything before the first colon of
    an output path as a protocol scheme. These assert the startup check that
    now rejects it outright."""

    def test_rejects_a_windows_path(self) -> None:
        # The literal value that broke the dev deployment.
        settings = Settings(temp_dir="C:/Users/birru/AppData/Local/Temp/videolens")

        with self.assertRaises(RuntimeError) as ctx:
            validate_temp_dir(settings)

        self.assertIn("absolute", str(ctx.exception))
        self.assertIn("TEMP_DIR", str(ctx.exception))

    def test_rejects_a_relative_path(self) -> None:
        settings = Settings(temp_dir="tmp/videolens")

        with self.assertRaises(RuntimeError):
            validate_temp_dir(settings)

    def test_does_not_create_a_directory_for_a_rejected_path(self) -> None:
        """The bug was `os.makedirs` running before any validation, which is
        what silently created `./C:/Users/...`. Rejection must come first."""
        with tempfile.TemporaryDirectory() as cwd:
            previous = os.getcwd()
            os.chdir(cwd)
            try:
                with self.assertRaises(RuntimeError):
                    validate_temp_dir(Settings(temp_dir="C:/Users/birru/AppData/Local/Temp/videolens"))
                self.assertEqual(os.listdir(cwd), [])
            finally:
                os.chdir(previous)

    def test_accepts_and_creates_an_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            target = os.path.join(parent, "videolens")
            settings = Settings(temp_dir=target)

            validate_temp_dir(settings)

            self.assertTrue(os.path.isdir(target))

    def test_is_idempotent_when_the_directory_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as target:
            settings = Settings(temp_dir=target)

            validate_temp_dir(settings)
            validate_temp_dir(settings)

            self.assertTrue(os.path.isdir(target))


if __name__ == "__main__":
    unittest.main()
