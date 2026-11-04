from fontes.config import get_settings
from fontes.container import build_app

app = build_app(get_settings())
