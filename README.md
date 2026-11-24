# Chati IA

[![CI](https://github.com/Serberar/chati-ia/actions/workflows/ci.yml/badge.svg)](https://github.com/Serberar/chati-ia/actions/workflows/ci.yml)

Asistente de IA **local** para Windows: chat, imágenes, vídeo, voz y un agente de código. Los modelos se ejecutan en el propio equipo con Ollama y ComfyUI.

![Conversación en Chati](docs/chat.png)

## Qué incluye

- **Chat** con modelos locales de Ollama, memoria, documentos (RAG), búsqueda web y búsqueda profunda.
- **Imágenes** a partir de texto y ampliación.
- **Vídeo** corto a partir de texto, y películas por escenas.
- **Voz:** transcripción con faster-whisper y lectura con Piper.
- **Agente de código** sobre OpenCode, con revisión, puntos de control y rutinas.
- **Cuentas** de usuario, datos cifrados en reposo y avisos push.
- **App de escritorio** (bandeja de Windows) y web instalable en el móvil.

## Lo interesante por dentro

- **Modelos en local:** el chat, los documentos, las imágenes y la voz se procesan en el propio ordenador. Solo salen a internet las búsquedas web y los avisos push, si se usan.
- **Cifrado en reposo:** cada usuario tiene su clave de datos, cifrada con otra que sale de su contraseña.
- **Respuestas verificadas:** un verificador revisa las respuestas para que no inventen datos.
- **Agente de código con frenos:** puntos de control para deshacer, revisión, reglas por proyecto y bloqueo de órdenes peligrosas.
- **Gestión de la GPU:** carga y descarga modelos de texto, imagen y vídeo para que quepan en una sola tarjeta.
- **Filtro de contenido** en el último paso antes del generador ([content_guard.py](orchestrator/media/content_guard.py)): no se generan desnudos ni contenido sexual, se pida como se pida.

Los modelos se configuran en `orchestrator/config.yaml`.

## Servicios locales

| Servicio | Dirección |
|---|---|
| Chati (FastAPI) | `http://127.0.0.1:8899` |
| Ollama | `http://127.0.0.1:11434` |
| ComfyUI | `http://127.0.0.1:8188` |
| OpenCode | `http://127.0.0.1:8901` |

## Instalación

Desde el código:

```powershell
powershell -ExecutionPolicy Bypass -File setup/install.ps1
```

El script instala lo que falte (Python 3.12, Ollama, Git, ComfyUI y demás) y prepara los entornos. Los modelos ocupan decenas de GB y no están en el repositorio.

Los datos y modelos van a `%LOCALAPPDATA%/ChatiIA`; se cambia con `-DataRoot` o con la variable `CHATI_DATA_ROOT`.

## Arrancar y parar

```powershell
powershell -ExecutionPolicy Bypass -File setup/start_all.ps1
powershell -ExecutionPolicy Bypass -File setup/stop_chati.ps1
```

Después abre `http://localhost:8899`.

## Pruebas

```powershell
cd orchestrator
python -m pytest -m "not live and not slow"
```

`live` necesita Ollama y `slow` genera imagen o vídeo real con ComfyUI.

## Estructura

| Ruta | Qué es |
|---|---|
| `orchestrator/main.py` | Servidor FastAPI |
| `orchestrator/api/` | Rutas HTTP |
| `orchestrator/chat/` | Conversación, memoria, RAG y búsquedas |
| `orchestrator/coding/` | Agente de código |
| `orchestrator/agents/` | Clientes de Ollama y ComfyUI, e imagen, vídeo y voz |
| `orchestrator/media/` | Vídeo, archivos generados y filtro de contenido |
| `orchestrator/models/` | Catálogo, elección y memoria de los modelos |
| `orchestrator/accounts/` | Usuarios, sesiones, dispositivos y avisos |
| `orchestrator/infra/` | Rutas de datos, cifrado, métricas y registro |
| `orchestrator/static/` | Interfaz web |
| `orchestrator/workflows/` | Flujos de ComfyUI |
| `orchestrator/tests/` | Pruebas |
| `setup/` | Instalación, arranque, copias de seguridad y compilación |

## Copias de seguridad

```powershell
powershell -ExecutionPolicy Bypass -File setup/backup.ps1
powershell -ExecutionPolicy Bypass -File setup/restore.ps1
```

Por defecto las copias van a una carpeta de OneDrive y se conservan las 14 últimas; se cambia con `-Destino` y `-Mantener`.

## Publicar una versión

1. Sube `VERSION` en `orchestrator/version.py`.
2. Ejecuta `setup/build_release.ps1`. Compila el lanzador y, con Inno Setup 6, deja el instalador en `setup/Output`.

## Licencia

[MIT](LICENSE)

## Autor

Sergio Bernabé
