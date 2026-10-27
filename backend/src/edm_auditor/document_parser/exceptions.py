"""Exceptions exposed by the document parser."""


class DocumentParserError(Exception):
    """Base class for expected document parser failures."""


class UnsupportedDocumentFormat(DocumentParserError):
    """The input extension or format is not supported."""


class DocumentNotFound(DocumentParserError):
    """The input path does not exist."""


class DocumentAccessError(DocumentParserError):
    """The input cannot be read."""


class InvalidDocument(DocumentParserError):
    """The input is damaged or does not match its format."""


class TextLayerRequired(DocumentParserError):
    """The PDF does not contain extractable text."""


class DocumentTooLarge(DocumentParserError):
    """The input exceeds the configured size limit."""
