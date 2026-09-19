# Bono A — Optimización global por lotes: por qué el lote supera al greedy

Este documento desarrolla, con números concretos, el requisito del Bono A: *"Expliquen por qué la
asignación por lotes supera a la codiciosa (ej. un caso donde el greedy deja un pedido lejano varado
y el lote lo resuelve mejor)"*.

## 1. El algoritmo

`app/batch_optimizer.py::solve_batch_assignment` agrupa los pedidos de una ventana corta y resuelve
la asignación conjunta pedido↔repartidor de **costo total mínimo**, usando el algoritmo húngaro
(`scipy.optimize.linear_sum_assignment`) sobre una matriz de costos `orders × slots_de_repartidor`.
Cada repartidor se expande en tantas "ranuras" como capacidad libre tenga, para poder recibir más de
un pedido del mismo lote sin violar `max_capacity` (cubierto por
`tests/test_bono_a_batch.py::test_batch_respects_capacity_as_multiple_slots`).

La asignación **greedy** (la que usan las Fases 1-3 pedido a pedido) decide con la información de un
solo pedido a la vez: para cada pedido que llega, elige el mejor repartidor *disponible en ese
instante*. Nunca puede "deshacer" una decisión anterior para acomodar un pedido que llega después.

## 2. Ejemplo numérico (la prueba que corre en la suite)

`tests/test_bono_a_batch.py::test_batch_beats_greedy_when_greedy_strands_a_far_order` usa esta matriz
de costos (simplificada para que el ejemplo sea nítido y sin empates):

| pedido \ repartidor | cour_near | cour_far |
| --- | --- | --- |
| order_close | **1** | 4 |
| order_far | 2 | **50** |

`order_close` y `order_far` llegan casi al mismo tiempo, cada repartidor tiene capacidad para 1.

- **Greedy** procesa `order_close` primero (llegó primero). Mirando solo ese pedido, `cour_near` es
  el más barato disponible (1 < 4) — una decisión localmente razonable. Eso deja a `order_far` varado
  con el único repartidor que queda, `cour_far`, al costo más alto de toda la matriz.
  **Costo total: 1 + 50 = 51.**
- **El lote** ve ambos pedidos a la vez. El algoritmo húngaro evalúa las combinaciones posibles y
  descubre que intercambiar las asignaciones (`order_close → cour_far`, `order_far → cour_near`) da
  un costo total mucho menor. **Costo total: 4 + 2 = 6.**

El lote nunca deja "varado" a un pedido con el peor repartidor disponible si existe una redistribución
global más barata — exactamente el caso que pide el enunciado.

## 3. Por qué el ejemplo usa una matriz ilustrativa (y no directamente `compute_base_cost`)

El motor de producción (`app/rules_engine.py::compute_base_cost`) usa una fórmula deliberadamente
simple para que coincida con el ejemplo documentado en la Fase 1/3 del reto (tarifa base + distancia
del pedido + un recargo **fijo** si el repartidor está en otra zona). Con esa fórmula, el costo de
un pedido **no depende del repartidor**, salvo por ese recargo fijo de cruce de zona — así que el
costo total de cualquier asignación completa se reduce a: *(suma fija de costos por distancia) +
recargo × (número de emparejamientos fuera de zona)*. Minimizar el costo total con esa fórmula
equivale a **maximizar la cantidad de emparejamientos en la misma zona**, y el greedy (que siempre
intenta usar un repartidor de la misma zona cuando hay uno disponible) casi siempre llega también a
ese óptimo con esta fórmula en particular — no porque el greedy sea igual de bueno en general, sino
porque el modelo de costo de producción es demasiado simple para exponer la diferencia.

Por eso el ejemplo de esta sección usa una matriz de costos explícita: aísla la propiedad general del
optimizador (`solve_batch_assignment` es agnóstico al `cost_fn` que se le pase — ver su firma en
`batch_optimizer.py`) de las particularidades de la fórmula de tarifa actual. Es la misma ventaja que
aparecería de inmediato si el modelo de costo se enriquece con datos reales de posición de cada
repartidor (GPS, tiempo estimado de recogida variable por repartidor, etc., en vez de un recargo fijo
por zona): en ese escenario más realista, el greedy sí dejaría sistemáticamente pedidos varados con el
repartidor más caro disponible, y el lote seguiría encontrando el óptimo global sin cambiar una línea
de `batch_optimizer.py`.

## 4. Conclusión

- El lote (algoritmo húngaro) siempre encuentra el óptimo global para la matriz de costos que se le da.
- El greedy es un heurístico miope: con arribos secuenciales, puede "gastar" el mejor repartidor
  disponible en un pedido para el que la diferencia era pequeña, dejando a un pedido posterior con la
  peor opción restante.
- La brecha entre ambos crece con la riqueza del modelo de costo; con el modelo actual (simple, para
  calzar el ejemplo del enunciado) la brecha es pequeña o nula en la mayoría de casos, pero el
  optimizador ya está listo para capturarla si el equipo de producto decide enriquecer el costo más
  adelante.
