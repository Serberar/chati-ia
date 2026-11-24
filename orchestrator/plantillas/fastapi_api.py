from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="__NOMBRE__")
elementos: dict[int, dict] = {}


class Elemento(BaseModel):
    nombre: str
    precio: float = 0


@app.get("/elementos")
def listar():
    return [{"id": i, **e} for i, e in elementos.items()]


@app.post("/elementos")
def crear(elemento: Elemento):
    nuevo = max(elementos, default=0) + 1
    elementos[nuevo] = elemento.model_dump()
    return {"id": nuevo, **elementos[nuevo]}


@app.get("/elementos/{id}")
def ver(id: int):
    if id not in elementos:
        raise HTTPException(404, "No existe")
    return {"id": id, **elementos[id]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
