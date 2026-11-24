import logging
import traceback
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
logging.basicConfig(filename=CARPETA / "__ARCHIVO__.log", level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")


def trabajo():
    logging.info("Hecho: %d archivos en la carpeta", sum(1 for _ in CARPETA.iterdir()))


if __name__ == "__main__":
    try:
        trabajo()
    except Exception:
        logging.error(traceback.format_exc())
        raise
