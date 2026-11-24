import tkinter as tk
from tkinter import messagebox


def accion():
    texto = entrada.get().strip()
    if not texto:
        messagebox.showwarning("__NOMBRE__", "Escribe algo primero.")
        return
    resultado.set(f"Has escrito: {texto}")


ventana = tk.Tk()
ventana.title("__NOMBRE__")
ventana.minsize(320, 160)
marco = tk.Frame(ventana, padx=16, pady=16)
marco.pack(fill="both", expand=True)
tk.Label(marco, text="Texto:").grid(row=0, column=0, sticky="w")
entrada = tk.Entry(marco, width=30)
entrada.grid(row=0, column=1, sticky="ew", padx=(8, 0))
tk.Button(marco, text="Aceptar", command=accion).grid(row=1, column=0, columnspan=2, pady=12)
resultado = tk.StringVar()
tk.Label(marco, textvariable=resultado).grid(row=2, column=0, columnspan=2)
marco.columnconfigure(1, weight=1)
ventana.mainloop()
