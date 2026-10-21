import importlib


def require_module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        raise AssertionError(f"missing module {name}") from None


def require(module, name):
    value = getattr(module, name, None)
    if value is None:
        raise AssertionError(f"{module.__name__}.{name} is missing")
    return value
