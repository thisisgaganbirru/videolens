import os
import tempfile
import unittest
from unittest import mock

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

    def _on(self, windows: bool):
        return mock.patch(
            "app.infrastructure.media.uploads._host_is_windows", return_value=windows
        )

    def test_rejects_a_windows_path(self) -> None:
        # The literal value that broke the dev deployment, on a Linux host.
        settings = Settings(temp_dir="C:/Users/birru/AppData/Local/Temp/videolens")

        with self._on(windows=False), mock.patch("os.makedirs") as makedirs:
            with self.assertRaises(RuntimeError) as ctx:
                validate_temp_dir(settings)

        self.assertIn("absolute POSIX path", str(ctx.exception))
        self.assertIn("TEMP_DIR", str(ctx.exception))
        makedirs.assert_not_called()

    def test_rejects_a_backslash_windows_path_on_linux(self) -> None:
        with self._on(windows=False), mock.patch("os.makedirs") as makedirs:
            with self.assertRaises(RuntimeError):
                validate_temp_dir(Settings(temp_dir=r"C:\Users\me\Temp\videolens"))
        makedirs.assert_not_called()

    def test_accepts_a_posix_path_on_linux(self) -> None:
        with self._on(windows=False), mock.patch("os.makedirs") as makedirs, mock.patch(
            "os.access", return_value=True
        ):
            validate_temp_dir(Settings(temp_dir="/tmp/videolens"))
        makedirs.assert_called_once_with("/tmp/videolens", exist_ok=True)

    def test_accepts_a_drive_path_on_windows(self) -> None:
        """A local native-Windows run: a drive path is absolute there."""
        for path in ("C:/Users/me/AppData/Local/Temp/videolens", r"C:\Temp\videolens", r"\\host\share\vl"):
            with self.subTest(path=path), self._on(windows=True), mock.patch(
                "os.makedirs"
            ) as makedirs, mock.patch("os.access", return_value=True):
                validate_temp_dir(Settings(temp_dir=path))
                makedirs.assert_called_once_with(path, exist_ok=True)

    def test_rejects_a_driveless_path_on_windows_with_a_windows_message(self) -> None:
        """`/tmp/videolens` (the .env.example default) has no drive on
        Windows, so it is refused there, with advice for that OS rather than
        a message about POSIX paths."""
        with self._on(windows=True), mock.patch("os.makedirs") as makedirs:
            with self.assertRaises(RuntimeError) as ctx:
                validate_temp_dir(Settings(temp_dir="/tmp/videolens"))

        message = str(ctx.exception)
        self.assertIn("absolute Windows path", message)
        self.assertIn("/tmp/videolens", message)
        self.assertNotIn("POSIX", message)
        makedirs.assert_not_called()

    def test_rejects_a_relative_path_on_either_host(self) -> None:
        for windows in (False, True):
            with self.subTest(windows=windows), self._on(windows), mock.patch("os.makedirs") as makedirs:
                with self.assertRaises(RuntimeError):
                    validate_temp_dir(Settings(temp_dir="tmp/videolens"))
                makedirs.assert_not_called()

    def test_does_not_create_a_directory_for_a_rejected_path(self) -> None:
        """The bug was `os.makedirs` running before any validation, which is
        what silently created `./C:/Users/...`. Rejection must come first."""
        with tempfile.TemporaryDirectory() as cwd:
            previous = os.getcwd()
            os.chdir(cwd)
            try:
                with self._on(windows=False), self.assertRaises(RuntimeError):
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
