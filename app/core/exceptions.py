class ServiceError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: dict | None = None
    ):
        self.code, self.message, self.status_code, self.details = (
            code,
            message,
            status_code,
            details or {},
        )
        super().__init__(message)
