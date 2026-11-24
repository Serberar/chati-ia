"""Filtro de imagen y video: no se genera contenido sexual ni desnudos, se pida como se pida.

Se aplica en el ultimo paso, justo antes de mandar la descripcion al generador, para que valga igual en el chat,
la cola nocturna, las peliculas por escenas y la API.
"""
import re
import unicodedata

MESSAGE = "No genero desnudos ni contenido sexual. Si quieres, pídemelo de otra forma."

# Sin acentos y en minusculas. Raices en español e ingles.
_BLOCKED = re.compile(
    r"\b(?:"
    r"desnud\w*|en (?:pelotas|bolas|cueros)|sin (?:nada de )?(?:ropa|bragas|sujetador|camiseta puesta)|desvest\w*|desvist\w*|"
    r"quit\w* (?:la|toda la|el|los|las) (?:ropa|bikini|bragas|sujetador|vestido|pantalon\w*|camiseta)|"
    r"top ?less|porn\w*|erot\w*|sexo|sexual\w*|sexy|hentai|fetich\w*|orgasm\w*|masturb\w*|"
    r"pezon\w*|genital\w*|vulva\w*|vagin\w*|pene|penes|pubis|pubic\w*|follar\w*|follando|coito|"
    r"nud(?:e|es|ity)|naked|nsfw|undress\w*|unclothed|no clothes|without clothes|bare (?:breasts?|chest)|"
    r"sex|explicit content|nipples?|penis|intercourse|lingerie|lenceria|striptease"
    r")\b")


class BlockedContent(ValueError):
    def __init__(self):
        super().__init__(MESSAGE)


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[\s_\-.]+", " ", text)


def is_blocked(text: str) -> bool:
    return bool(_BLOCKED.search(_plain(text)))


def check(*texts: str) -> None:
    if any(is_blocked(t) for t in texts):
        raise BlockedContent
