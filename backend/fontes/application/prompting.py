"""The prompt that asks a model to answer only from numbered sources, citing them as [n]."""

from collections.abc import Sequence
from dataclasses import dataclass

from fontes.application.ports.chunks import SearchHit

SYSTEM = """You answer questions using only the numbered sources you are given.

Rules:
- Use only facts stated in the sources. Do not use outside knowledge.
- Cite the source of each statement with its number in square brackets, like [1] or [2][3].
- Put at least one [n] marker in every paragraph and in every list item.
- Use only the numbers of the sources listed below.
- If the sources do not answer the question, say so plainly instead of guessing.
- Answer in the language of the question.
- Write plain paragraphs or lists. Do not use headings."""


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str


def build_prompt(question: str, hits: Sequence[SearchHit]) -> Prompt:
    sources = "\n\n".join(_source(n, hit) for n, hit in enumerate(hits, start=1))
    user = f"Sources:\n\n{sources}\n\nQuestion: {question}"
    return Prompt(SYSTEM, user)


def _source(n: int, hit: SearchHit) -> str:
    header = f"[{n}] {hit.document_title} — {hit.chunk.location_label(hit.total_chunks)}"
    if hit.document_url:
        header += f" ({hit.document_url})"
    return f"{header}\n{hit.chunk.text}"
