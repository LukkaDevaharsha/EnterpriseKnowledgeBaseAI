"""Split extracted text into bounded chunks with source character offsets."""


def split_text(text, chunk_size=1000, overlap=150):
    """Return chunk dictionaries with indices and offsets into *text*.

    Chunk contents exclude surrounding whitespace; offsets identify the exact
    content substring in the original input. Adjacent chunks overlap where
    possible, and no chunk exceeds ``chunk_size`` characters.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0:
        raise ValueError("overlap must be a non-negative integer")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    text_length = len(text)
    start = 0

    while start < text_length:
        while start < text_length and text[start].isspace():
            start += 1
        if start >= text_length:
            break

        limit = min(start + chunk_size, text_length)
        end = limit
        if limit < text_length:
            boundary = max(text.rfind(" ", start + 1, limit + 1),
                           text.rfind("\n", start + 1, limit + 1),
                           text.rfind("\t", start + 1, limit + 1))
            if boundary > start and boundary >= start + chunk_size // 2:
                end = boundary

        # Trim only the stored chunk edges and retain source-aligned offsets.
        content_start = start
        content_end = end
        while content_start < content_end and text[content_start].isspace():
            content_start += 1
        while content_end > content_start and text[content_end - 1].isspace():
            content_end -= 1
        if content_end > content_start:
            chunks.append({
                "chunk_index": len(chunks),
                "content": text[content_start:content_end],
                "start_char": content_start,
                "end_char": content_end,
            })

        if end >= text_length:
            break
        next_start = max(start + 1, end - overlap)
        # Move to a word boundary when possible without risking a stalled loop.
        whitespace = next((i for i in range(next_start, end)
                           if text[i].isspace()), None)
        if whitespace is not None and whitespace > start:
            next_start = whitespace + 1
        start = next_start

    return chunks
