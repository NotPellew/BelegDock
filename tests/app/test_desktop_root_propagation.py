import unittest

from belegdock import desktop


class PropagatingRoot:
    def __init__(self):
        self.calls = []

    def geometry(self, value):
        self.calls.append(("geometry", value))

    def minsize(self, width, height):
        self.calls.append(("minsize", width, height))

    def grid_propagate(self, value):
        self.calls.append(("grid_propagate", value))


class DesktopRootPropagationTests(unittest.TestCase):
    def test_window_propagation_is_disabled_after_initial_sizing(self):
        app = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        app.root = PropagatingRoot()

        app._configure_window()

        self.assertEqual(
            app.root.calls,
            [
                ("geometry", desktop.INITIAL_WINDOW_GEOMETRY),
                ("minsize", *desktop.MIN_WINDOW_SIZE),
                ("grid_propagate", False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
