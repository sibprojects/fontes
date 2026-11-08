from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """A run of loaded text and where in the document it came from."""

    text: str
    page: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class Chunk:
    """A stored piece of a document; its location is what a citation points at."""

    ordinal: int
    text: str
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None

    def location_label(self, total: int) -> str:
        if self.page_start is not None:
            if self.page_end is None or self.page_end == self.page_start:
                return f"p. {self.page_start}"
            return f"pp. {self.page_start}–{self.page_end}"
        if self.section:
            return self.section
        return f"part {self.ordinal + 1} of {total}"
