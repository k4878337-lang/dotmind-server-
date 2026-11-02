import io
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def extract_pdf_text(base64_data: str, max_pages: int = 30) -> str:
    """Extracts text content from a base64-encoded PDF using pypdf with fallback."""
    try:
        pdf_bytes = base64.b64decode(base64_data)
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        num_pages = min(len(reader.pages), max_pages)
        pages_text = []
        for i in range(num_pages):
            page_text = reader.pages[i].extract_text()
            if page_text:
                pages_text.append(f"[Page {i + 1}]\n{page_text.strip()}")

        extracted = "\n\n".join(pages_text)
        if len(reader.pages) > max_pages:
            extracted += f"\n\n[Truncated: PDF contains {len(reader.pages)} pages, first {max_pages} pages extracted]"
        return extracted if extracted.strip() else "[PDF contains no extractable text layer / scanned image]"
    except Exception as e:
        logger.warning(f"pypdf extraction failed: {e}")
        # Basic stream fallback
        try:
            pdf_bytes = base64.b64decode(base64_data)
            raw_str = pdf_bytes.decode("latin1", errors="ignore")
            import re
            streams = re.findall(r"stream[\r\n]+(.*?)[\r\n]+endstream", raw_str, re.DOTALL)
            text_chunks = [s for s in streams if len(s) > 10 and any(c.isalpha() for c in s)]
            if text_chunks:
                return f"[Fallback text extraction]\n" + "\n".join(text_chunks[:5])
        except Exception:
            pass
        return f"[Failed to extract PDF text: {str(e)}]"

def extract_document_text(filename: str, mime_type: str, base64_data: str) -> Optional[str]:
    """Extracts readable text from various document formats."""
    if not base64_data:
        return None

    fname_lower = filename.lower()
    if mime_type == "application/pdf" or fname_lower.endswith(".pdf"):
        return extract_pdf_text(base64_data)

    if (
        mime_type.startswith("text/")
        or any(fname_lower.endswith(ext) for ext in [".py", ".kt", ".json", ".txt", ".md", ".csv", ".xml", ".gradle", ".kts", ".sh", ".yaml", ".yml", ".html", ".js", ".ts"])
    ):
        try:
            decoded = base64.b64decode(base64_data).decode("utf-8", errors="ignore")
            return decoded
        except Exception as e:
            return f"[Error decoding text file {filename}: {str(e)}]"

    return None
