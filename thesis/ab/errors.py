class BuildError(RuntimeError):
    """The checkout did not produce a runnable binary."""


class Incompatible(BuildError):
    """The checkout runs, but it cannot take the shared model path."""
