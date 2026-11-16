"""Structure-aware document chunking for Chinese knowledge bases."""

from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter


splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    chunk_size=450,
    chunk_overlap=110,
)

_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_CHINESE_HEADING = re.compile(r"^(?:[一二三四五六七八九十百]+、|\d+[.、])\s*(.+?)\s*$")


def _section_title(line: str) -> str | None:
    """Return a section title for Markdown and common Chinese document headings."""
    stripped = line.strip()
    match = _MARKDOWN_HEADING.match(stripped) or _CHINESE_HEADING.match(stripped)
    return match.group(1).strip() if match else None


def _sections(text: str) -> list[tuple[str, str]]:
    """Split a document into titled sections while retaining untitled preamble."""
    sections: list[tuple[str, str]] = []
    title = "文档摘要"
    buffer: list[str] = []

    for line in text.splitlines():
        next_title = _section_title(line)
        if next_title:
            if "\n".join(buffer).strip():
                sections.append((title, "\n".join(buffer).strip()))
            title = next_title
            # Store the normalized title once as a prefix on every resulting
            # chunk instead of relying on a heading that only the first chunk
            # would contain.
            buffer = []
        else:
            buffer.append(line)

    if "\n".join(buffer).strip():
        sections.append((title, "\n".join(buffer).strip()))
    return sections or [("文档摘要", text.strip())]


def split_text(documents: list[dict]) -> list[dict]:
    """Create chunks with stable section and position metadata.

    Repeating a section title in every chunk gives the embedding model context
    that would otherwise be lost when a long policy or manual is split.
    """
    chunks: list[dict] = []

    for doc in documents:
        chunk_index = 0
        for section_title, section_text in _sections(doc["text"]):
            for text in splitter.split_text(section_text):
                content = text.strip()
                if not content:
                    continue
                content = f"【{section_title}】\n{content}"
                chunks.append(
                    {
                        "text": content,
                        "filename": doc["filename"],
                        "stored_filename": doc["stored_filename"],
                        "user_id": doc["user_id"],
                        "section_title": section_title,
                        "chunk_index": chunk_index,
                    }
                )
                chunk_index += 1

    return chunks
