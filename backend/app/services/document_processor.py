"""Extract searchable text from stored documents."""

import pymupdf


def extract_document_text(file_path, file_type):
    """Extract readable text from a PDF or UTF-8 TXT file."""

    if file_type == "TXT":
        try:
            with open(file_path, "r", encoding="utf-8-sig") as file:
                text = file.read()
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                "The TXT file could not be read as UTF-8."
            ) from exc

    elif file_type == "PDF":
        try:
            # Read and close the disk file before opening the PDF.
            with open(file_path, "rb") as file:
                pdf_bytes = file.read()

            # Parse from memory to avoid Windows file-locking issues.
            with pymupdf.open(
                stream=pdf_bytes,
                filetype="pdf",
            ) as pdf:
                text = "\n".join(
                    page.get_text("text")
                    for page in pdf
                )

        except (
            pymupdf.FileDataError,
            pymupdf.EmptyFileError,
            OSError,
        ) as exc:
            raise ValueError(
                "The PDF file could not be parsed."
            ) from exc

    else:
        raise ValueError("Unsupported document type.")

    text = text.strip()

    if not text:
        raise ValueError(
            "The document contains no extractable text."
        )

    return text


def extract_document_pages(file_path, file_type):
    """Return page-level extracted text for metadata-preserving indexing."""
    if file_type == "TXT":
        text = extract_document_text(file_path, file_type)
        return [(None, text)]
    if file_type != "PDF":
        raise ValueError("Unsupported document type.")
    try:
        with open(file_path, "rb") as file:
            pdf_bytes = file.read()
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            pages = [
                (index + 1, page.get_text("text").strip())
                for index, page in enumerate(pdf)
            ]
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, OSError) as exc:
        raise ValueError("The PDF file could not be parsed.") from exc
    if not any(text for _, text in pages):
        raise ValueError("The document contains no extractable text.")
    return pages


def extract_pdf_outline(file_path):
    """Return real PDF bookmarks as page destinations, or an empty list."""
    try:
        with open(file_path, "rb") as file:
            pdf_bytes = file.read()
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            return [
                {"level": level, "title": title, "page_number": page_number}
                for level, title, page_number, *_ in pdf.get_toc()
                if isinstance(level, int) and isinstance(title, str)
                and isinstance(page_number, int) and page_number > 0
            ]
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, OSError) as exc:
        raise ValueError("The PDF outline could not be read.") from exc
