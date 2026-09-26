"""Safe, contract-shaped failures for HTTP callers."""


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
