from flask import Flask, render_template_string, request

app = Flask(__name__)
PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>__NOMBRE__</title></head>
<body style="font-family: sans-serif; max-width: 600px; margin: 40px auto">
  <h1>__NOMBRE__</h1>
  <form method="post"><input name="texto" required> <button>Enviar</button></form>
  {% if texto %}<p>Has enviado: {{ texto }}</p>{% endif %}
</body></html>"""


@app.route("/", methods=["GET", "POST"])
def inicio():
    return render_template_string(PAGINA, texto=request.form.get("texto"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
