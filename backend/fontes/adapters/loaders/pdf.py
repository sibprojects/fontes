import io
import logging

from pypdf import PdfReader

from fontes.application.ports.ingestion import PermanentIngestionError
from fontes.domain.chunks import Segment

# pypdf logs every malformed object it recovers from; that is noise, not an error.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def parse_pdf(data: bytes) -> list[Segment]:
    """One segment per page that has text, numbered from 1."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PermanentIngestionError("The PDF is password-protected")
        pages = [page.extract_text() for page in reader.pages]
    except PermanentIngestionError:
        raise
    except Exception as exc:
        # The file is the only input here, so whatever pypdf raises will happen on every
        # retry too: a permanent failure, not a transient one.
        raise PermanentIngestionError(f"Could not read the PDF: {exc}") from exc
    return [Segment(text, page=i) for i, text in enumerate(pages, start=1) if text.strip()]
