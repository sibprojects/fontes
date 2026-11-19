"""The prompt that asks a model to answer only from numbered sources, citing them as [n]."""

import re
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
- If the question has no clear language (only names, numbers or codes), answer in the language of the sources.
- Write plain paragraphs or lists. Do not use headings."""  # noqa: E501 (one rule per line)

# qwen2.5 sometimes answers a short English question in Chinese. When neither the question
# nor the sources contain any Han characters, nothing asked for them, so rule them out.
NO_CHINESE = "\n- Do not write Chinese characters."
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str


def build_prompt(question: str, hits: Sequence[SearchHit]) -> Prompt:
    sources = "\n\n".join(_source(n, hit) for n, hit in enumerate(hits, start=1))
    user = f"Sources:\n\n{sources}\n\nQuestion: {question}"
    has_han = _HAN.search(question) or any(_HAN.search(hit.chunk.text) for hit in hits)
    return Prompt(SYSTEM if has_han else SYSTEM + NO_CHINESE, user)


def _source(n: int, hit: SearchHit) -> str:
    header = f"[{n}] {hit.document_title} — {hit.chunk.location_label(hit.total_chunks)}"
    if hit.document_url:
        header += f" ({hit.document_url})"
    return f"{header}\n{hit.chunk.text}"
