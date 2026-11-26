# Diagramas

| Archivo | Contenido |
| --- | --- |
| `1b_diagrama_arquitectura_v2.png` | Arquitectura de solución vigente: RDS en subredes privadas y credenciales en Secrets Manager |
| `1_diagrama_arquitectura.png` | Arquitectura anterior (RDS pública), se conserva como referencia |
| `2_er_identity.png` … `7_er_requests.png` | Diagrama E/R de la base de cada microservicio |
| `servidesk_arquitectura_v2.drawio` | Fuente editable de la arquitectura vigente (se genera con `python docs/diagramas/build_arquitectura_v2.py`) |
| `servidesk_arquitectura.drawio` | Fuente editable de la arquitectura anterior |
| `servidesk_er.drawio` | Fuente editable de los 6 E/R (una página por microservicio) |

Los `.drawio` se abren con [draw.io](https://app.diagrams.net) o draw.io Desktop. Se generan con
`python docs/diagramas/build_diagrams.py` (y exporta los PNG si draw.io Desktop está instalado), así
que los cambios conviene hacerlos en el script para que estilo y datos sigan alineados con el código.

Criterios de los E/R: todas las bases son PostgreSQL (relacionales), así que solo se dibujan como
entidades las tablas reales con sus FK. Las columnas JSONB se documentan con un ejemplo de su estructura
JSON (no como tablas), las referencias a otro microservicio van punteadas hacia cajas grises (no hay FK
entre bases) y las tablas técnicas sin relaciones (idempotencia de SQS) van en una nota.
