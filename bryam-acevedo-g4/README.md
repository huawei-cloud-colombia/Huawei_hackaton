# SentinelPay Risk Engine — Reto 4

**Autor:** Bryam Camilo Acevedo Orjuela — Grupo 4

Motor de scoring de riesgo en tiempo real (API + UI) para detectar fraude tipo "card testing" en transacciones de pago, resolviendo el Reto 4 del hackathon.

## Instalación

```bash
cd codigo
python -m venv .venv

# Windows
./.venv/Scripts/activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

## Ejecutar el proyecto

```bash
# (con el venv activado, dentro de codigo/)
uvicorn app.main:app --reload --port 8000
```

Abrir **http://127.0.0.1:8000** en el navegador. Ahí se encuentra la interfaz gráfica (Fase 4): formulario para ingresar una transacción, resultado con score/decisión/razones a color, y un botón **"Simular ráfaga (6x)"** para ver en vivo cómo el sistema detecta y bloquea el "card testing".

## Ejecutar las pruebas

```bash
# (con el venv activado, dentro de codigo/)
pytest -v
```

18 pruebas cubriendo las 3 fases del motor, concurrencia (Bono B), colusión por grafo (Bono A) y patrones adversariales (Bono D).

## Contenido de esta entrega

```
bryam-acevedo-g4/
├── README.md              # este archivo
├── requerimientos.txt     # dependencias (fastapi, uvicorn, pydantic, pytest, httpx)
├── prompt_usado.txt       # bitácora de prompts e iteraciones con la IA
└── codigo/                # código fuente completo (ver codigo/README.md para arquitectura y decisiones de diseño)
```

Para el detalle de arquitectura, decisiones de diseño y qué bonos se implementaron (A, B, C y D), ver **[`codigo/README.md`](codigo/README.md)**.
