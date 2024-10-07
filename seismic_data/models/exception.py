class NotFoundError(Exception):
    """Exception raised when a specific entity is not found."""

    def __init__(self, message="Record Not found!"):
        self.message = message
        super().__init__(self.message)