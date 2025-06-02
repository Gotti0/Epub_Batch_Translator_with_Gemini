# ebtg/ebtg_exceptions.py

class EbtgBaseException(Exception):
    """Base exception for EBTG project."""
    pass

class EbtgProcessingError(EbtgBaseException):
    """General error during EBTG processing."""
    pass

class XhtmlExtractionError(EbtgProcessingError):
    """Error during XHTML content extraction."""
    pass

class ApiXhtmlGenerationError(EbtgProcessingError):
    """Error when the API (via BTG) fails to generate XHTML."""
    pass