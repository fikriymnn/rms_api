class AppError(Exception):
    """Error domain: service melempar ini, main.py mengubahnya menjadi respons HTTP."""

    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class BadRequest(AppError):
    status_code = 400


class Forbidden(AppError):
    status_code = 403


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class Unprocessable(AppError):
    status_code = 422
