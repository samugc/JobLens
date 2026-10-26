"""JobLens CV export component."""

from .adapter import adapt_draft, validate_export
from .api import (
    export_cv_docx,
    export_cv_docx_bytes,
    export_cv_pdf,
    export_cv_pdf_bytes,
)
from .errors import (
    ApprovalError,
    ContactError,
    CvExportError,
    DestinationError,
    EvidenceContractError,
    InvalidDraftError,
    RenderingError,
    UnsupportedSchemaError,
)
from .models import CanonicalDraft
from .utils import safe_filename

__all__ = [
    "ApprovalError",
    "CanonicalDraft",
    "ContactError",
    "CvExportError",
    "DestinationError",
    "EvidenceContractError",
    "InvalidDraftError",
    "RenderingError",
    "UnsupportedSchemaError",
    "adapt_draft",
    "export_cv_docx",
    "export_cv_docx_bytes",
    "export_cv_pdf",
    "export_cv_pdf_bytes",
    "safe_filename",
    "validate_export",
]

__version__ = "0.1.0"