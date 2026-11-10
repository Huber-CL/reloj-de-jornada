---
description: Ejecuta las pruebas del parser Workera (correos Tipo A y B) y del resolver Entrada/Salida, incluidos los casos de borde
---

Ejecuta la suite del motor Workera y resume el resultado.

1. Desde la raíz del proyecto ejecuta (usa el intérprete del venv según el sistema):
   - Windows: `.venv/Scripts/python -m pytest tests/test_workera_and_resolver.py -v`
   - macOS/Linux: `.venv/bin/python -m pytest tests/test_workera_and_resolver.py -v`
2. La suite usa HTML simulado de ambos correos (fixtures en `tests/fixtures/`) y debe cubrir:
   - Correo A normal (09/11/2026 05:52:47 Entrada, hash E7B8C5E7) y RUT que no coincide.
   - Correo B (06/11/2026, Horario 07:00 a 16:00, sobretiempo de 103 minutos → salida 17:43:00).
   - Doble Entrada (07:00:10 + 17:43:15) → la segunda se asigna como salida inferida.
   - Doble Salida → la primera se asigna como ingreso inferido.
   - Rebote: marca a pocos minutos de otra (< 10 min y también < 15 min, el umbral configurado) se ignora.
   - Reconstrucción por correo de Alerta: marca faltante sugerida desde turno + minutos.
   - Una sola marca 'Entrada' después de las 15:00 → pregunta "¿Es tu Salida…?" y la alerta la resuelve.
3. Si falta alguno de estos casos en la suite, agrégalo antes de reportar.
4. Muestra al usuario: total de tests, pasados/fallidos y, para cada fallo, la aserción y la causa probable.
   No modifiques el código de producción para hacer pasar un test sin explicar por qué el test estaba mal.

$ARGUMENTS
