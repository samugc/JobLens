"""Error contract for CV export."""

from __future__ import annotations


class CvExportError(Exception):
    """Base class for all CV export errors."""


class InvalidDraftError(CvExportError, ValueError):
    """Raised when a CvDraft is missing required fields or malformed."""


class UnsupportedSchemaError(InvalidDraftError):
    """Raised when cv_draft_version is not supported."""


class ApprovalError(InvalidDraftError):
    """Raised when one or more factual items are not finally approved."""


class EvidenceContractError(InvalidDraftError):
    """Raised when a provided evidence-support contract is invalid or inconsistent."""


class ContactError(InvalidDraftError):
    """Raised when required candidate contact details are missing."""


class RenderingError(CvExportError, RuntimeError):
    """Raised when a backend fails to produce a valid document."""


class DestinationError(CvExportError, ValueError):
    """Raised when a destination cannot be used."""