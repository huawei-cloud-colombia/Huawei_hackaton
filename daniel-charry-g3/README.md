# 🎟️ NEXUS LIVE // T-80 — Solución del Equipo

## 🧑‍💻 Equipo

| Integrante | Rol |
|---|---|
| Daniel Charry | Líder de desarrollo |

**Rama:** `daniel-charry-g3`
**Reto:** [RETO 3 — NEXUS LIVE](../Retos/RETO_3_NEXUS_LIVE.md)

---

## 📖 Descripción

Este repositorio contiene la solución al **Reto 3: NEXUS LIVE**, cuyo objetivo es reconstruir un **motor de reservas de alta concurrencia** capaz de garantizar que un asiento nunca sea vendido a dos compradores diferentes.

El sistema debe soportar:

- Consulta de asientos disponibles.
- Creación de reservas temporales (`HOLD`).
- Expiración automática de reservas.
- Confirmación de compras (`SOLD`).
- Reintentos seguros (idempotencia).
- Concurrencia segura bajo alta carga.
- Integración con un proveedor de pagos inestable.
- Trazabilidad de transiciones de estado.
- Interfaz visual para simulación.

---

## 🏗️ Arquitectura

> _Se definirá durante el desarrollo._

**Stack tentativo:**

- **Lenguaje:** _por definir_
- **Framework:** _por definir_
- **Almacenamiento:** _por definir_
- **Interfaz:** _por definir_

---

## 📂 Estructura del proyecto

```text
daniel-charry-g3/
├── README.md
├── (por definir)
```

---

## 🚀 Instalación y ejecución

```bash
# Por definir
```

---

## 🧪 Pruebas

```bash
# Por definir
```

---

## 📋 Fases del reto

| Fase | Descripción | Estado |
|---|---|---|
| **Fase 1** | SeatLock: reservas temporales y estados | ⬜ Pendiente |
| **Fase 2** | Idempotencia y concurrencia segura | ⬜ Pendiente |
| **Fase 3** | Confirmación, pagos y resiliencia | ⬜ Pendiente |
| **Fase 4** | Interfaz visual y simulación | ⬜ Pendiente |

---

## 🤖 Bitácora de uso de GLM 5.2

> Registro de interacciones con el agente de desarrollo GLM 5.2 durante el hackathon.

- _Se actualizará conforme avanza el desarrollo._

---

## 📝 Notas

- Tiempo total disponible: **80 minutos**
- Apertura de venta: **10:00:00**
- Usuarios en sala de espera: **180.000**
- Asientos disponibles: **42.000**
