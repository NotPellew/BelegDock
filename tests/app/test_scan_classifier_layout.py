import unittest

from belegdock import desktop


class Widget:
    def __init__(self, *_args, **_kwargs):
        pass

    def grid(self, **_kwargs):
        pass

    def columnconfigure(self, *_args, **_kwargs):
        pass

    def rowconfigure(self, *_args, **_kwargs):
        pass

    def set(self, _value):
        pass


class Treeview:
    def __init__(self, *_args, **_kwargs):
        self.columns = {}

    def heading(self, *_args, **_kwargs):
        pass

    def column(self, name, **options):
        self.columns[name] = options

    def grid(self, **_kwargs):
        pass

    def configure(self, **_kwargs):
        pass

    def yview(self):
        return (0.0, 1.0)

    def set(self, _value):
        pass


class Ttk:
    Frame = Widget
    Scrollbar = Widget
    Treeview = Treeview


class ScanClassifierLayoutTests(unittest.TestCase):
    def test_candidate_columns_fit_the_existing_wide_side_panel(self):
        app = desktop.DesktopApplication.__new__(desktop.DesktopApplication)
        app.ttk = Ttk()
        view = app._build_tree(
            Widget(),
            row=3,
            columns=("filename", "document_type", "recommendation", "size"),
            headings={
                "filename": "Dateiname",
                "document_type": "Dokumenttyp",
                "recommendation": "Empfehlung",
                "size": "Größe",
            },
            selectmode="extended",
        )

        widths = {
            name: options["width"]
            for name, options in view.columns.items()
            if name in {"filename", "document_type", "recommendation", "size"}
        }
        self.assertLessEqual(sum(widths.values()), 500)
        self.assertTrue(widths["filename"] >= 180)
        self.assertTrue(widths["document_type"] >= 80)
        self.assertTrue(widths["recommendation"] >= 90)
        self.assertTrue(widths["size"] >= 70)


if __name__ == "__main__":
    unittest.main()
