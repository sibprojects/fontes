from fontes.domain.chunks import Chunk


def test_label_single_page() -> None:
    assert Chunk(0, "t", 4, 4).location_label(9) == "p. 4"


def test_label_page_range() -> None:
    assert Chunk(0, "t", 4, 5).location_label(9) == "pp. 4–5"


def test_label_section() -> None:
    assert Chunk(0, "t", section="Install").location_label(9) == "Install"


def test_label_position() -> None:
    assert Chunk(2, "t").location_label(12) == "part 3 of 12"
