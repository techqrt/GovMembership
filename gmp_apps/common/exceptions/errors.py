class ValidationErrors(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(', '.join(errors))
        self.errors = errors


class TokenErrors(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(', '.join(errors))
        self.errors = errors


class ForbiddenError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ServiceUnavailableError(Exception):
    """A third-party service we depend on (e.g. the AI provider) cannot be used right now."""


class TooManyRequestsError(Exception):
    pass
