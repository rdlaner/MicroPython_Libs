"""mptest

Very rough attempt to emulate pytest functionality.

TODO: Figure out how to do a fixture (if it's even possible on micropython)
"""


class raises:  # pylint: disable=invalid-name
    """Asserts that the specified exception is thrown while in this context."""
    def __init__(self, exc) -> None:
        self.exc = exc

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"{self.exc.__name__} was not raised")
        if exc_type is not self.exc:
            raise AssertionError(f"{exc_type.__name__} was raised instead of {self.exc.__name__}")
        return True


def _get_test_functions(fxns: dict) -> dict:
    return {name: func for name, func in fxns.items() if callable(func) and name.startswith("test_")}


def parametrize(arg_names, arg_values):
    """Parametrization decorator"""
    if isinstance(arg_names, str):
        arg_names = [name.strip() for name in arg_names.split(",")]

    def decorator(func):
        def wrapper(*args):
            # Loop through all sets of argument values
            for value in arg_values:
                # Ensure `value` is a tuple
                if not isinstance(value, tuple):
                    value = (value,)

                # Check if the length of `value` matches `arg_names`
                if len(value) != len(arg_names):
                    raise ValueError(
                        f"Value length {len(value)} does not match argument names length {len(arg_names)}"
                    )

                # Create keyword arguments from argument names and values
                params = dict(zip(arg_names, value))

                # Call the decorated function with the parameters
                func(*args, **params)
        return wrapper
    return decorator


def run(global_fxns: dict) -> None:
    """Runs all discovered tests.

    Identifies all "test_" functions from the provided `global_fxns` dict.
    Typical usage is to pass global functions via globals().

    Args:
        global_fxns (dict): Collection of functions containing tests.
    """
    test_functions = _get_test_functions(global_fxns)
    failures = []

    print(f"Running {len(test_functions)} tests")
    for name, func in test_functions.items():
        # Run any setup function
        if "setup" in global_fxns and callable(global_fxns["setup"]):
            global_fxns["setup"]()

        try:
            func()
        except AssertionError as exc:
            print("F", end="")
            failures.append(f"FAILED - {name}: {exc}")
        else:
            print(".", end="")

        # Run any teardown function
        if "teardown" in global_fxns and callable(global_fxns["teardown"]):
            global_fxns["teardown"]()

    print(f"{'*' * 50} Results {'*' * 50}")
    if failures:
        for failed in failures:
            print(failed)
    else:
        print("SUCCESS")
