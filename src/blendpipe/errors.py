"""The one error the pipeline raises for anything a model or project gets wrong."""


class BuildError(Exception):
    """A model, spec or project breaks a rule; the message says which and how."""
