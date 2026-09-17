# PROMPT — SENTINELPAY RISK ENGINE

## Hardening final, pruebas adversariales y preparación para evaluación

### Contexto

Ya existe una implementación completa de:

* Fase 1;
* Fase 2;
* Fase 3;
* Fase 4;
* interfaz Streamlit;
* motor de scoring;
* velocity detection;
* blocklist;
* circuit breaker;
* explicabilidad.

Ahora debes realizar la etapa final de **hardening, testing, documentación y preparación para evaluación**.

### OBJETIVO PRINCIPAL

En esta etapa debes implementar **exclusivamente el Bono D — Pruebas adversariales**.

El objetivo es crear una **suite automatizada de pruebas adversariales realista y reproducible** que demuestre que SentinelPay puede detectar y responder correctamente ante diferentes patrones de ataque.

No reescribas el sistema si ya funciona.

Primero comprende la arquitectura existente y reutiliza las interfaces, servicios, modelos y reglas actuales.

---

# 1. Auditoría inicial

Antes de modificar código:

1. Inspecciona la estructura completa del repositorio.
2. Identifica cómo se evalúa actualmente una transacción.
3. Identifica dónde se implementan:

   * reglas;
   * scoring;
   * velocity detection;
   * blocklist;
   * circuit breaker;
   * explicabilidad;
   * persistencia del estado;
   * configuración.
5. Identifica errores o comportamientos inconsistentes.
6. Revisa dependencias y configuración.

Corrige primero cualquier problema del **core existente** que impida construir o ejecutar correctamente las pruebas.

No hagas una reestructuración innecesaria del proyecto.

---

# 2. Bono D — Pruebas adversariales

Implementa una suite de tests automatizados enfocada específicamente en ataques contra el motor de riesgo.

Las pruebas deben utilizar el sistema real de evaluación y no simplemente probar funciones aisladas sin pasar por el flujo principal.

Organiza las pruebas, preferiblemente, en una estructura clara como:

```text
tests/
├── test_adversarial.py
├── adversarial/
│   ├── test_card_testing.py
│   ├── test_ip_spoofing.py
│   ├── test_device_recycling.py
│   └── test_combined_attacks.py
```

Adapta esta estructura a la arquitectura existente si ya existe una organización de tests diferente.

---

# 3. Ataque 1 — Card Testing

Implementa pruebas automatizadas que simulen un ataque de **card testing**.

El escenario debe representar múltiples transacciones pequeñas realizadas rápidamente con la misma tarjeta.

Ejemplo conceptual:

```text
card_001
    ↓
$0.50
$0.70
$0.80
$0.40
$0.90
$0.60
```

Genera una secuencia temporal realista dentro de la ventana configurada por el sistema.

Verifica que:

* las primeras transacciones sean procesadas normalmente según las reglas existentes;
* el límite de velocidad se active cuando corresponda;
* la transacción que supera el límite produzca la respuesta esperada;
* la razón de rechazo sea explicable;
* el bloqueo temporal se aplique cuando corresponda;
* las transacciones posteriores durante el bloqueo sean rechazadas con la razón correspondiente.

La prueba debe comprobar valores reales de la respuesta, no simplemente verificar que "no ocurrió una excepción".

Debe validar, como mínimo:

```text
decision
score
activated rules / reasons
velocity detection
blocklist status
```

Utiliza los límites configurados realmente por el sistema.

No dupliques la lógica del motor dentro del test para forzar artificialmente el resultado.

---

# 4. Ataque 2 — IP Spoofing / Cambios rápidos de IP

Implementa pruebas que simulen cambios rápidos de:

```text
ip
ip_country
```

durante una secuencia de transacciones.

Ejemplo:

```text
transaction_1 → country=CO → ip_country=CO
transaction_2 → country=CO → ip_country=RU
transaction_3 → country=CO → ip_country=CN
transaction_4 → country=CO → ip_country=US
```

El objetivo es verificar que el motor detecte correctamente las señales de inconsistencia geográfica cuando correspondan.

Verifica:

* activación de `country_mismatch`;
* incremento correspondiente del score;
* decisión resultante;
* explicación de la señal;
* comportamiento cuando las señales se combinan con otras reglas.

No inventes una regla de IP spoofing que no exista en el sistema.

Si el sistema actual detecta el comportamiento mediante `country_mismatch`, las pruebas deben validar esa implementación existente.

---

# 5. Ataque 3 — Device Recycling

Implementa pruebas para simular múltiples tarjetas utilizando el mismo dispositivo.

Ejemplo:

```text
device_A

card_001
card_002
card_003
card_004
card_005
```

Las transacciones deben ocurrir dentro de la ventana temporal configurada.

Verifica específicamente el comportamiento definido para:

```text
same device + multiple different cards
```

Comprueba que:

* el contador de tarjetas distintas sea correcto;
* el límite configurado se respete;
* la regla de velocity correspondiente se active;
* el score cambie correctamente;
* la decisión sea la esperada;
* la explicación indique claramente la señal activada.

También agrega pruebas de frontera:

```text
exactamente en el límite
justo por debajo del límite
justo por encima del límite
```

---

# 6. Ataques combinados

Implementa escenarios donde varias señales adversariales ocurran simultáneamente.

Por ejemplo:

```text
card testing
+
country mismatch
+
unusual hour
+
device recycling
```

Verifica que el motor:

* active correctamente las múltiples reglas;
* no pierda señales;
* acumule correctamente los pesos;
* respete el límite máximo del score;
* produzca una decisión coherente con los umbrales configurados;
* explique cada señal activada.

No asumas manualmente cuál debe ser el score final sin revisar primero cómo funciona el scoring actual.

Las expectativas de los tests deben derivarse de la implementación y configuración reales.

---

# 7. Pruebas de frontera de los ataques

Agrega pruebas para comprobar que el sistema no genere falsos positivos simplemente por estar cerca de un límite.

Incluye:

### Velocity

```text
5 transacciones → comportamiento permitido
6 transacciones → activar límite
```

según la configuración actual del proyecto.

### Device recycling

```text
2 tarjetas → debajo del límite
3 tarjetas → límite configurado
4 tarjetas → superar límite
```

Ajusta estos valores si la configuración actual del proyecto utiliza otros límites.

### Ventanas temporales

Prueba:

```text
dentro de la ventana
exactamente en el límite temporal
justo fuera de la ventana
```

El objetivo es comprobar el comportamiento real del sliding window.

---

# 8. Casos borde

Agrega o completa pruebas para:

* `amount = 0`;
* amount negativo;
* amount extremadamente grande;
* timestamp futuro;
* timestamp muy antiguo;
* timestamps iguales;
* transacciones exactamente en el límite;
* transacciones justo fuera del límite;
* múltiples reglas simultáneas;
* score potencialmente superior a 100;
* circuit breaker abierto;
* expiración de blocklist;
* device con muchas tarjetas.

Estas pruebas deben integrarse con la suite existente sin duplicar tests que ya cubran exactamente el mismo comportamiento.

---

# 9. Calidad de las pruebas

Las pruebas adversariales deben ser:

* deterministas;
* reproducibles;
* independientes;
* fáciles de entender;
* automatizadas;
* ejecutables mediante `pytest`.

Evita pruebas que dependan de:

* tiempos reales de espera innecesarios;
* comportamiento aleatorio no controlado;
* servicios externos reales;
* llamadas de red;
* credenciales;
* intervención manual.

Si el sistema utiliza elementos aleatorios, como `mock_bank_auth()`, utiliza mecanismos de inyección, mocks o configuración determinista para que los tests sean reproducibles.

No cambies la lógica de producción únicamente para hacer que los tests pasen.

---

# 10. No implementar otros bonos

En esta etapa está explícitamente prohibido implementar:

### Bono A

No implementar:

```text
grafo de colusión
fraud ring graph
visualización de nodos/conexiones
```

### Bono B

No implementar una solución adicional específicamente para obtener el bono de concurrencia.

### Bono C

No implementar un nuevo sistema de exportación de auditoría JSON como bono.

### Bono D

**Este es el único bono que debe implementarse.**

La entrega debe poder demostrar claramente que el **Bono D — Pruebas adversariales** está implementado mediante tests automatizados.

---

# 11. Seguridad

Realiza una revisión básica del repositorio:

Busca posibles valores sensibles como:

```text
API_KEY
SECRET
TOKEN
PASSWORD
```

Verifica:

* `.env.example`;
* `.gitignore`;
* configuración;
* logs;
* documentación.

No agregues credenciales reales.

No incluyas secretos en los tests.

---

# 12. README final

Actualiza `README.md`.

Debe explicar claramente:

## Arquitectura

Explica brevemente los componentes principales.

## Instalación

Incluye los pasos exactos para instalar el proyecto.

Ejemplo:

```bash
pip install -r requirements.txt
```

Utiliza únicamente comandos que correspondan con la implementación real.

## Configuración

Explica:

* variables de entorno;
* configuración necesaria;
* valores opcionales;
* configuración relevante para ejecutar las pruebas.

## Ejecución

Indica exactamente cómo ejecutar la aplicación.

Si utiliza Streamlit, incluye el comando real:

```bash
streamlit run <archivo_principal>.py
```

## Testing

Incluye:

```bash
pytest
```

y explica cómo ejecutar específicamente las pruebas adversariales.

Por ejemplo, si corresponde a la estructura real:

```bash
pytest tests/test_adversarial.py
```

No inventes rutas.

## Demo

Explica cómo demostrar:

1. transacción normal;
2. country mismatch;
3. unusual hour;
4. card testing;
5. device recycling;
6. combinación de señales;
7. circuit breaker.

## Bono D

Agrega una sección específica:

```text
Bono D — Pruebas adversariales
```

Explica:

* qué ataques se simulan;
* qué comportamiento se valida;
* dónde están los tests;
* cómo ejecutarlos.

No menciones los Bonos A, B o C como implementados.

---

# 13. Bitácora de IA

Crea o actualiza:

```text
docs/sesion_ia.md
```

Documenta la evolución de los prompts utilizados durante el desarrollo.

Incluye:

* Prompt 1;
* Prompt 2;
* Prompt 3;
* Prompt 4;
* Prompt 5;
* resultado obtenido de cada uno;
* problemas encontrados;
* correcciones realizadas;
* decisiones técnicas relevantes.

Para esta etapa final, documenta específicamente cómo se utilizó IA para diseñar o mejorar las pruebas adversariales.

No incluyas secretos ni credenciales.

---

# 14. Requirements

Verifica:

```text
requirements.txt
```

Debe contener únicamente las dependencias realmente necesarias.

No agregues una librería solamente por una prueba si puede resolverse correctamente con las herramientas existentes.

Si agregas una dependencia, justifica su necesidad y verifica que la instalación funcione.

---

# 15. Ejecución completa de tests

Ejecuta:

```bash
pytest
```

Después ejecuta específicamente la suite adversarial.

Verifica:

```text
tests existentes
+
tests adversariales
```

Corrige cualquier fallo real encontrado.

No elimines tests existentes simplemente para obtener un resultado verde.

No reduzcas las expectativas de los tests para ocultar errores del sistema.

---

# 16. Verificación del Bono D

Antes de finalizar, verifica explícitamente que existen pruebas automatizadas para:

### Card Testing

```text
microtransacciones
ráfaga rápida
velocity detection
blocklist
```

### IP Spoofing

```text
cambios rápidos de IP / país
country mismatch
```

### Device Recycling

```text
múltiples tarjetas
mismo device
ventana temporal
velocity detection
```

### Combinaciones

```text
múltiples señales simultáneas
scoring combinado
explicabilidad
```

El resultado debe ser demostrable ejecutando `pytest`.

---

# 17. Prueba final de demostración

Ejecuta y verifica como mínimo:

### Caso A — Transacción normal

Debe procesarse correctamente según las reglas existentes.

### Caso B — Country mismatch + unusual hour

Para el escenario definido por el reto:

```text
country = CO
ip_country = RU
hora = 04:58
```

Debe producir:

```text
score = 40
decision = REVIEW
```

si la configuración base permanece sin cambios.

### Caso C — Card testing

Realiza la secuencia configurada para superar el límite de velocity.

Debe activarse:

```text
velocity_limit_exceeded
```

y producir la decisión correspondiente.

### Caso D — Blocklist

Realiza una transacción posterior mientras la tarjeta permanece bloqueada.

Debe producir:

```text
card_temporarily_blocked
```

### Caso E — Ataque combinado

Ejecuta una transacción que active múltiples señales simultáneamente.

Verifica:

```text
score
decision
activated rules
reasons
```

### Caso F — Circuit breaker

Provoca el número de fallos configurado en `mock_bank_auth()`.

Verifica la transición:

```text
CLOSED
→ OPEN
→ degraded REVIEW
```

y posteriormente, cuando corresponda:

```text
OPEN
→ HALF_OPEN
→ CLOSED
```

---

# 18. Corrección final

No te limites a detectar problemas.

**Corrige los problemas encontrados.**

Después vuelve a ejecutar:

```bash
pytest
```

y las pruebas adversariales.

Si una prueba falla:

1. determina si el problema está en el test o en el sistema;
2. corrige la causa real;
3. vuelve a ejecutar la prueba;
4. verifica que no hayas roto otras funcionalidades.

No declares éxito basándote únicamente en una inspección estática.

---

# 19. Resultado final

El repositorio debe quedar:

* funcional;
* modular;
* testeado;
* documentado;
* demostrable;
* seguro;
* preparado para evaluación;
* con el **Bono D implementado y demostrable**.

Al finalizar proporciona:

1. resumen de los cambios realizados;
2. archivos creados/modificados;
3. tests ejecutados;
4. resultado de los tests;
5. pruebas adversariales implementadas;
6. escenarios de ataque cubiertos;
7. instrucciones para ejecutar la suite adversarial;
8. flujo de demostración;
9. limitaciones reales restantes.

### Restricción final

**No afirmes que una prueba fue ejecutada si realmente no la ejecutaste.**

**No afirmes que el Bono D funciona si los tests correspondientes no fueron ejecutados correctamente.**

**No implementes los Bonos A, B ni C.**

La prioridad es mantener intactas las funcionalidades core de SentinelPay y añadir una **suite de pruebas adversariales sólida, automatizada y demostrable para el Bono D**.
