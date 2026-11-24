import csv
import sys
from pathlib import Path


def numero(texto):
    texto = str(texto).strip().replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def leer(ruta):
    ruta = Path(ruta)
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        hoja = openpyxl.load_workbook(ruta, read_only=True, data_only=True).active
        filas = list(hoja.iter_rows(values_only=True))
        cabecera = [str(c) for c in filas[0]]
        return [dict(zip(cabecera, f)) for f in filas[1:]]
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        muestra = f.read(4096)
        f.seek(0)
        separador = ";" if muestra.count(";") > muestra.count(",") else ","
        return list(csv.DictReader(f, delimiter=separador))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    filas = leer(sys.argv[1])
    columna = sys.argv[2] if len(sys.argv) > 2 else list(filas[0])[-1]
    valores = [numero(f[columna]) for f in filas if f.get(columna) not in (None, "")]
    print(f"Filas: {len(filas)}  Columna: {columna}  Total: {sum(valores):.2f}  "
          f"Media: {sum(valores) / len(valores):.2f}" if valores else f"Filas: {len(filas)}, sin valores en {columna}")


if __name__ == "__main__":
    main()
