import json
from pathlib import Path

ARCHIVO = Path(__file__).with_name("datos.json")


def cargar():
    return json.loads(ARCHIVO.read_text(encoding="utf-8")) if ARCHIVO.exists() else []


def guardar(datos):
    ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    datos = cargar()
    while True:
        print("\n1. Ver  2. Añadir  3. Borrar  4. Salir")
        opcion = input("Opcion: ").strip()
        if opcion == "1":
            for i, d in enumerate(datos, 1):
                print(i, d)
        elif opcion == "2":
            datos.append(input("Texto: "))
            guardar(datos)
        elif opcion == "3":
            numero = input("Numero: ").strip()
            if numero.isdigit() and 1 <= int(numero) <= len(datos):
                datos.pop(int(numero) - 1)
                guardar(datos)
            else:
                print("Numero no valido.")
        elif opcion == "4":
            break


if __name__ == "__main__":
    main()
