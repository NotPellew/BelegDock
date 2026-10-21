import importlib.resources
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from belegdock import desktop, desktop_setup

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
ICON_DIR = PACKAGING / "icon"
ICON_SIZES = {16, 20, 24, 32, 40, 48, 64, 128, 256}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def load_build_module():
    path = PACKAGING / "build_windows.py"
    spec = importlib.util.spec_from_file_location("belegdock_build_windows_icon", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ico_sizes(data: bytes) -> set[int]:
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    sizes = set()
    for index in range(count):
        width = data[6 + 16 * index]
        sizes.add(width or 256)
    return sizes


def png_dimensions(data: bytes) -> tuple[int, int]:
    assert data[:8] == PNG_SIGNATURE
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


class IconAssetTests(unittest.TestCase):
    def test_ico_contains_every_required_size(self):
        data = (ICON_DIR / "belegdock.ico").read_bytes()

        self.assertEqual(ico_sizes(data), ICON_SIZES)

    def test_runtime_png_is_packaged_and_256_pixels(self):
        resource = importlib.resources.files("belegdock").joinpath("assets/belegdock.png")

        self.assertTrue(resource.is_file())
        self.assertEqual(png_dimensions(resource.read_bytes()), (256, 256))

    def test_build_backend_ships_the_png_as_package_data(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("assets/*.png", pyproject)

    def test_generator_output_matches_committed_assets(self):
        try:
            from PIL import Image
        except ModuleNotFoundError:
            self.skipTest("Pillow is not installed in the test environment")
        spec = importlib.util.spec_from_file_location("belegdock_make_icon", ICON_DIR / "make_icon.py")
        assert spec is not None and spec.loader is not None
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(generator.main(["make_icon.py", temporary]), 0)
            for name in ("belegdock.ico", "belegdock.png"):
                self.assertEqual(
                    sorted(Path(temporary).glob(name)), [Path(temporary) / name]
                )
            with Image.open(ICON_DIR / "belegdock.ico") as committed_ico:
                self.assertEqual(committed_ico.info["sizes"], {(n, n) for n in ICON_SIZES})
                for size in ICON_SIZES:
                    frame = committed_ico.ico.getimage((size, size)).convert("RGBA")
                    expected = generator.render(size)
                    self.assertEqual(frame.tobytes(), expected.tobytes(), f"{size}px frame")
            with Image.open(ROOT / "src" / "belegdock" / "assets" / "belegdock.png") as png:
                self.assertEqual(png.convert("RGBA").tobytes(), generator.render(256).tobytes())


class PackagingReferenceTests(unittest.TestCase):
    def test_spec_embeds_the_icon_in_both_executables(self):
        spec = (PACKAGING / "belegdock.spec").read_text(encoding="utf-8")

        chunks = spec.split("EXE(")[1:]
        self.assertEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertRegex(chunk.split(")\n", 1)[0], r"icon\s*=\s*ICON")
        self.assertIn("belegdock.ico", spec)

    def test_spec_bundles_the_runtime_png(self):
        spec = (PACKAGING / "belegdock.spec").read_text(encoding="utf-8")

        self.assertIn("belegdock.png", spec)
        self.assertIn("belegdock/assets", spec)

    def test_installer_uses_the_icon_everywhere(self):
        iss = (PACKAGING / "belegdock.iss").read_text(encoding="utf-8")

        self.assertRegex(iss, r"(?m)^SetupIconFile=.*belegdock\.ico$")
        self.assertIn("UninstallDisplayIcon={app}\\BelegDock-Desktop.exe", iss)
        shortcut = [line for line in iss.splitlines() if line.startswith('Name: "{userprograms}')]
        self.assertEqual(len(shortcut), 1)
        self.assertIn("BelegDock-Desktop.exe", shortcut[0])

    def test_artifact_check_requires_the_png_asset(self):
        module = load_build_module()

        normalized = {str(entry).replace("\\", "/") for entry in module.REQUIRED_BUNDLE_FILES}
        self.assertIn("belegdock/assets/belegdock.png", normalized)

    def test_smoke_requires_an_applied_window_icon(self):
        module = load_build_module()

        self.assertEqual(module.DESKTOP_SMOKE_REQUIRED_STATES[0], "icon")
        self.assertEqual(module.window_icon_mismatches([{"state": "icon", "applied": True}]), [])
        self.assertTrue(module.window_icon_mismatches([{"state": "icon", "applied": False}]))
        self.assertTrue(module.window_icon_mismatches([{"state": "labels"}]))

    def test_desktop_smoke_records_the_icon_state(self):
        smoke = (ROOT / "src" / "belegdock" / "desktop_smoke.py").read_text(encoding="utf-8")

        self.assertIn('"icon"', smoke)
        self.assertIn("window_icon_applied", smoke)


class WindowIconHelperTests(unittest.TestCase):
    def make_tk(self, image=None, error=None):
        tk = MagicMock()
        tk.TclError = RuntimeError
        tk.PhotoImage = MagicMock(return_value=image or object())
        if error is not None:
            tk.PhotoImage.side_effect = error
        return tk

    def test_helper_applies_the_png_as_default_window_icon(self):
        tk = self.make_tk()
        root = MagicMock()

        self.assertTrue(desktop.apply_window_icon(root, tk))

        tk.PhotoImage.assert_called_once()
        root.iconphoto.assert_called_once()
        self.assertIs(root.iconphoto.call_args.args[0], True)

    def test_helper_swallows_a_missing_asset_or_tk_error(self):
        for error in (FileNotFoundError("gone"), RuntimeError("bad image data")):
            root = MagicMock()
            self.assertFalse(desktop.apply_window_icon(root, self.make_tk(error=error)))
            root.iconphoto.assert_not_called()

        root = MagicMock()
        root.iconphoto.side_effect = RuntimeError("no window manager")
        self.assertFalse(desktop.apply_window_icon(root, self.make_tk()))

    def test_main_window_applies_the_icon(self):
        application = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        application.root = MagicMock()
        application.tk = self.make_tk()

        application._apply_window_icon()

        application.root.iconphoto.assert_called_once()
        self.assertTrue(application.window_icon_applied)

    def test_constructor_applies_the_icon_before_building(self):
        events = []

        class Root(MagicMock):
            def iconphoto(self, *args):
                events.append("icon")

        original_build = desktop.DesktopApplication._build
        desktop.DesktopApplication._build = lambda self: events.append("build")
        original_labels = desktop.DesktopApplication._load_labels
        desktop.DesktopApplication._load_labels = lambda self: None
        original_reload = desktop.DesktopApplication._reload_documents
        desktop.DesktopApplication._reload_documents = lambda self: None
        try:
            desktop.DesktopApplication(MagicMock(), self.make_tk(), MagicMock(), MagicMock(), root=Root())
        finally:
            desktop.DesktopApplication._build = original_build
            desktop.DesktopApplication._load_labels = original_labels
            desktop.DesktopApplication._reload_documents = original_reload

        self.assertEqual(events, ["icon", "build"])

    def test_setup_root_applies_the_icon(self):
        root = MagicMock()
        root.winfo_screenheight.return_value = 1000
        tk = self.make_tk()
        tk.Tk = MagicMock(return_value=root)
        view = MagicMock()
        view.preferred_height.return_value = 500
        original_view = desktop_setup.SetupView
        original_theme = desktop_setup.configure_theme
        original_dispatcher = desktop_setup._TkWorkerDispatcher
        desktop_setup.SetupView = MagicMock(return_value=view)
        desktop_setup.configure_theme = MagicMock()
        desktop_setup._TkWorkerDispatcher = MagicMock()
        try:
            state = SimpleNamespace(gmail="missing", lexware="missing")
            desktop_setup.run_setup(tk, MagicMock(), MagicMock(), state, services=MagicMock())
        finally:
            desktop_setup.SetupView = original_view
            desktop_setup.configure_theme = original_theme
            desktop_setup._TkWorkerDispatcher = original_dispatcher

        root.iconphoto.assert_called_once()


if __name__ == "__main__":
    unittest.main()
