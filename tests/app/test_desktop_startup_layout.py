import unittest

from belegdock import desktop


class Root:
    def __init__(self, width):
        self.width = width
        self.geometry_value = None
        self.minimum_size = None

    def geometry(self, value):
        self.geometry_value = value

    def minsize(self, width, height):
        self.minimum_size = (width, height)

    def winfo_width(self):
        return self.width


class Section:
    def __init__(self):
        self.grid_calls = []

    def grid(self, **kwargs):
        self.grid_calls.append(kwargs)


class DesktopStartupLayoutTests(unittest.TestCase):
    def test_initial_geometry_is_explicit_and_starts_wide(self):
        self.assertTrue(hasattr(desktop, "INITIAL_WINDOW_GEOMETRY"))
        self.assertTrue(hasattr(desktop, "MIN_WINDOW_SIZE"))
        self.assertTrue(hasattr(desktop.DesktopApplication, "_configure_window"))
        if not all(
            (
                hasattr(desktop, "INITIAL_WINDOW_GEOMETRY"),
                hasattr(desktop, "MIN_WINDOW_SIZE"),
                hasattr(desktop.DesktopApplication, "_configure_window"),
            )
        ):
            return

        app = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        app.root = Root(width=1200)
        app._configure_window()
        self.assertEqual(app.root.geometry_value, desktop.INITIAL_WINDOW_GEOMETRY)
        self.assertEqual(app.root.minimum_size, desktop.MIN_WINDOW_SIZE)

        app.sections = Section()
        app.choose_section = Section()
        app.review_section = Section()
        app._section_layout = None
        app._layout_sections()

        self.assertEqual(app._section_layout, "wide")
        self.assertEqual(app.choose_section.grid_calls[-1]["column"], 0)
        self.assertEqual(app.review_section.grid_calls[-1]["column"], 1)


if __name__ == "__main__":
    unittest.main()
