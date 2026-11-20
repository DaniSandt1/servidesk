# ms-changes — ServiDesk

## Descripción

Microservicio encargado de gestionar las **solicitudes de cambio (RFC), evaluación de riesgo, aprobación CAB, planificación e implementación de cambios** dentro de ServiDesk.

Utiliza PostgreSQL con aislamiento multi-tenant mediante esquemas (`schemas`) y publica eventos mediante SNS para integrarse con otros microservicios.

## Estado de implementación

**Estado actual:** lógica Python de los 7 endpoints implementada y **182 pruebas unitarias aprobadas**.

| Funcionalidad | Estado |
|---|---|
| CH-01 · `GET /changes` | Implementado y probado |
| CH-02 · `POST /changes` | Implementado y probado |
| CH-03 · `GET /changes/{id}` | Implementado y probado |
| CH-04 · `PATCH /changes/{id}` | Implementado y probado |
| CH-05 · `PUT /changes/{id}/status` | Implementado y probado |
| CH-06 · `POST /changes/{id}/approve` | Implementado y probado |
| CH-07 · `POST /changes/{id}/reject` | Implementado y probado |
| Publicación de eventos SNS | Implementada y probada con mocks |
| Migración SQL | `001_init.sql` preparada |
| Validación en PostgreSQL real | Pendiente |
| Configuración y despliegue AWS | Pendiente de integración |

Los siete endpoints tienen lógica Python implementada. Esto no implica que todas las rutas HTTP estén configuradas o desplegadas en AWS.

## 1. Endpoints implementados

### CH-01 — Listar solicitudes de cambio

**`GET /changes`**

Permite consultar solicitudes de cambio con paginación, filtros y ordenamiento.

Funcionalidades:

- Paginación mediante `page` y `limit`.
- Límite predeterminado de 20 registros y máximo de 100.
- Filtros por `status`, `type` y `risk`, incluyendo múltiples valores separados por comas.
- Filtro por `requester_id`, incluyendo el valor `me`.
- Búsqueda por clave o título.
- Ordenamiento por fecha de creación, inicio planificado, riesgo, estado o clave.
- Filtros `planned_from` y `planned_to` para consultar el calendario de cambios.
- Aislamiento por tenant.

**Permisos:** `admin` y `agent`.

**Respuesta exitosa:** `200 OK`, con `data` y `meta`.

Ejemplo de consulta:

```http
GET /changes?status=approved,scheduled&sort_by=planned_start&sort_order=asc&limit=100
```

### CH-02 — Crear solicitud de cambio

**`POST /changes`**

Permite registrar una nueva solicitud de cambio.

Validaciones:

- `title`: obligatorio, entre 3 y 200 caracteres.
- `description`: máximo 5000 caracteres.
- `type`: `standard`, `normal` o `emergency`.
- `risk`: `low`, `medium` o `high`.
- `rollback_plan`: máximo 5000 caracteres.
- `planned_start` y `planned_end`: fechas ISO 8601.
- Si se proporcionan ambas fechas, `planned_end` debe ser posterior a `planned_start`.
- `problem_id`: UUID opcional.
- `cis`: máximo 50 elementos, sin identificadores repetidos.
- `new_version`: máximo 50 caracteres.
- Se rechazan campos no permitidos.

El backend establece automáticamente:

- Identificador UUID.
- Clave correlativa, por ejemplo `CHG-000001`.
- Estado inicial `draft`.
- Solicitante obtenido del contexto autenticado.
- Fecha de creación.

La operación utiliza una transacción PostgreSQL para registrar el cambio y sus CI relacionados.

**Permisos:** `admin` y `agent`.

**Respuesta exitosa:** `201 Created`, con `ChangeDetail`.

### CH-03 — Consultar solicitud de cambio

**`GET /changes/{id}`**

Permite obtener el detalle de una solicitud de cambio mediante su UUID.

Incluye:

- Información principal del cambio.
- Tipo, riesgo y estado.
- Plan de reversión.
- Fechas de planificación.
- Solicitante y problema relacionado.
- Lista de CI afectados.
- Historial de decisiones CAB.

Validaciones:

- UUID válido.
- Existencia de la solicitud.
- Permisos del usuario.
- Aislamiento por tenant.

**Permisos:** `admin` y `agent`.

**Respuesta exitosa:** `200 OK`.

**Errores principales:** `400`, `403` y `404`.

### CH-04 — Actualizar solicitud de cambio

**`PATCH /changes/{id}`**

Permite actualizar parcialmente una solicitud de cambio.

Campos editables:

- `title`
- `description`
- `type`
- `risk`
- `rollback_plan`
- `planned_start`
- `planned_end`
- `problem_id`
- `cis`

Reglas:

- Solo se permiten cambios en estado `draft`.
- Se rechazan campos desconocidos.
- Se validan textos, UUID, fechas y valores enumerados.
- Si se envía `cis`, se reemplaza la lista completa de CI afectados.
- Si no se envía `cis`, se conservan las relaciones existentes.
- La operación utiliza una transacción PostgreSQL con bloqueo de fila.
- Ante errores de base de datos se ejecuta `ROLLBACK`.

**Permisos:** `admin` y `agent`.

**Respuesta exitosa:** `200 OK`.

**Errores principales:** `400`, `403`, `404` y `409`.

### CH-05 — Cambiar estado de una solicitud

**`PUT /changes/{id}/status`**

Administra el ciclo de vida de las solicitudes de cambio.

Estados disponibles:

- `draft`
- `submitted`
- `approved`
- `rejected`
- `scheduled`
- `implemented`
- `failed`

Transiciones permitidas mediante este endpoint:

| Estado actual | Estado solicitado | Resultado |
|---|---|---|
| `draft` | `submitted` | Envío a aprobación |
| `draft` de tipo `standard` | `submitted` | Aprobación automática |
| `rejected` | `draft` | Permite corregir la solicitud |
| `approved` | `scheduled` | Programación del cambio |
| `scheduled` | `implemented` | Implementación exitosa |
| `scheduled` | `failed` | Implementación fallida |

Reglas:

- Para enviar un cambio se requieren fechas de inicio y fin válidas.
- Los cambios no estándar necesitan un plan de reversión.
- Los cambios `standard` se aprueban automáticamente al enviarlos.
- Los estados `approved` y `rejected` no pueden establecerse directamente mediante este endpoint.
- Las transiciones inválidas devuelven `409 Conflict`.
- Se utiliza una transacción PostgreSQL con bloqueo de fila.

Eventos publicados:

- `ChangeSubmitted`: al enviar una solicitud.
- `ChangeImplemented`: al finalizar satisfactoriamente la implementación.

**Permisos:** `admin` y `agent`.

**Respuesta exitosa:** `200 OK`.

### CH-06 — Aprobar solicitud de cambio

**`POST /changes/{id}/approve`**

Permite que un administrador registre una decisión de aprobación CAB.

Reglas:

- Solo los usuarios `admin` pueden aprobar.
- La solicitud debe estar en estado `submitted`.
- El solicitante no puede aprobar su propio cambio.
- El comentario es opcional y admite un máximo de 2000 caracteres.
- La aprobación se registra en `change_approvals`.
- El estado de la solicitud cambia a `approved`.
- Ambas operaciones se realizan dentro de una transacción PostgreSQL.

Evento publicado:

- `ChangeApproved`

**Permisos:** únicamente `admin`.

**Respuesta exitosa:** `200 OK`.

**Errores principales:** `400`, `403`, `404` y `409`.

### CH-07 — Rechazar solicitud de cambio

**`POST /changes/{id}/reject`**

Permite que un administrador rechace una solicitud de cambio y registre la justificación.

Reglas:

- Solo los usuarios `admin` pueden rechazar.
- La solicitud debe estar en estado `submitted`.
- El solicitante no puede rechazar su propio cambio.
- El campo `comment` es obligatorio.
- El comentario debe tener entre 3 y 2000 caracteres.
- La decisión se registra en `change_approvals`.
- El estado cambia a `rejected`.
- Las operaciones utilizan una transacción PostgreSQL.

Evento publicado:

- `ChangeRejected`

**Permisos:** únicamente `admin`.

**Respuesta exitosa:** `200 OK`.

**Errores principales:** `400`, `403`, `404` y `409`.

## 2. Estados y aprobación CAB

El microservicio implementa el ciclo de vida de las solicitudes de cambio.

Flujo habitual:

```text
draft
  |
  v
submitted
  |
  +-------> approved
  |            |
  |            v
  |         scheduled
  |            |
  |      +-----+-----+
  |      |           |
  |      v           v
  | implemented    failed
  |
  +-------> rejected
                |
                v
              draft
```

Los cambios de tipo `standard` pasan directamente a `approved` cuando se envían desde `draft`.

Los cambios `normal` y `emergency` requieren una decisión administrativa mediante los endpoints de aprobación o rechazo.

## 3. Integración mediante eventos SNS

El microservicio publica los siguientes eventos:

| Evento | Descripción |
|---|---|
| `ChangeSubmitted` | Una solicitud se envía a aprobación |
| `ChangeApproved` | Un administrador aprueba la solicitud |
| `ChangeRejected` | Un administrador rechaza la solicitud |
| `ChangeImplemented` | El cambio se implementa satisfactoriamente |

La publicación utiliza el helper compartido `common.events.publish`.

Los eventos contienen información como:

- `changeId`
- `key`
- `type`
- `risk`
- `status`
- `actorId`

Los eventos de aprobación y rechazo también incluyen información del administrador y su comentario.

**Estado:** la publicación de eventos está implementada y probada mediante mocks. La integración real con SNS y sus consumidores requiere validación en AWS.

## 4. Base de datos y migraciones

**Base de datos:** `db_changes`.

El aislamiento multi-tenant utiliza esquemas PostgreSQL, por ejemplo:

- `tenant_andina`
- `tenant_pacifico`
- `tenant_unitec`

### Tablas

| Tabla | Responsabilidad |
|---|---|
| `changes` | Almacenar las solicitudes de cambio |
| `change_approvals` | Registrar decisiones CAB |
| `change_cis` | Relacionar cambios con CI afectados |
| `change_tasks` | Registrar tareas asociadas a cambios |

### `changes`

Contiene información como:

- `id`
- `key`
- `title`
- `description`
- `type`
- `risk`
- `status`
- `rollback_plan`
- `planned_start`
- `planned_end`
- `requester_id`
- `problem_id`
- `created_at`

### `change_approvals`

Registra las decisiones de aprobación o rechazo:

- `id`
- `change_id`
- `approver_id`
- `decision`
- `comment`
- `decided_at`

### `change_cis`

Almacena los CI afectados por cada solicitud:

- `change_id`
- `ci_id`
- `new_version`

La combinación de `change_id` y `ci_id` es única.

### `change_tasks`

Contiene las tareas asociadas a los cambios, incluyendo su descripción, estado y responsable.

### Migraciones

El archivo `migrations/001_init.sql` contiene la definición inicial de las tablas y sus índices.

El handler `handlers/migrate.py` lee esa migración y la ejecuta dentro de los esquemas de tenant configurados.

**Pendiente:** validar la migración contra una instancia real de PostgreSQL, revisar su correspondencia final con el diagrama ER y agregar pruebas específicas para `migrate.py`.

## 5. Pruebas unitarias

Las pruebas utilizan:

- Python.
- `unittest`.
- `unittest.mock`.
- `MagicMock`.
- `pytest` como ejecutor.

Las dependencias de PostgreSQL y AWS se simulan mediante mocks, por lo que las pruebas unitarias no necesitan conexión a servicios reales.

### Resultado actual

**182 pruebas unitarias aprobadas**, confirmadas mediante ejecución local.

| Endpoint | Pruebas |
|---|---:|
| CH-01 · Listar cambios | 24 |
| CH-02 · Crear cambio | 24 |
| CH-03 · Consultar cambio | 16 |
| CH-04 · Actualizar cambio | 30 |
| CH-05 · Cambiar estado | 30 |
| CH-06 · Aprobar cambio | 27 |
| CH-07 · Rechazar cambio | 31 |
| **Total** | **182** |

Las pruebas cubren:

- Autorización por roles.
- Validación de parámetros.
- Paginación, filtros y búsqueda.
- Creación y actualización de solicitudes.
- Relación con CI afectados.
- Consulta de decisiones CAB.
- Transiciones permitidas y prohibidas.
- Aprobación automática de cambios estándar.
- Prevención de autoaprobación y autorrechazo.
- Transacciones y `ROLLBACK` ante errores.
- Publicación de eventos mediante mocks.
- Aislamiento por tenant.

### Ejecutar todas las pruebas

Desde la raíz del repositorio:

```powershell
python -m pytest services/changes/tests/ -v
```

Resultado confirmado:

```text
182 passed
```

### Ejecutar CH-05

```powershell
python -m pytest services/changes/tests/test_changes.py::TestChangeChangeStatus -v
```

### Ejecutar CH-06

```powershell
python -m pytest services/changes/tests/test_changes.py::TestApproveChange -v
```

### Ejecutar CH-07

```powershell
python -m pytest services/changes/tests/test_changes.py::TestRejectChange -v
```

## 6. Estructura del microservicio

```text
services/changes/
├── handlers/
│   ├── changes.py
│   └── migrate.py
├── migrations/
│   └── 001_init.sql
├── tests/
│   └── test_changes.py
├── serverless.yml
└── README.md
```

- `changes.py`: lógica HTTP de los siete endpoints.
- `migrate.py`: ejecución de la migración SQL por tenant.
- `001_init.sql`: definición de las tablas e índices.
- `test_changes.py`: pruebas unitarias de los siete endpoints.
- `serverless.yml`: configuración de infraestructura, gestionada por el responsable correspondiente.

## 7. Contrato de API

La implementación sigue las especificaciones de:

`docs/API_CONTRACTS.md`

Sección **8.5 — ms-changes**.

Los valores enumerados y las transiciones están documentados en las secciones 6 y 7 del mismo archivo.

## 8. Pendientes de integración

- Configurar las rutas HTTP restantes en API Gateway y Serverless.
- Validar la migración SQL con PostgreSQL real.
- Confirmar la compatibilidad de las tablas con el diagrama ER.
- Agregar pruebas unitarias específicas de migración.
- Verificar la publicación real de eventos SNS.
- Realizar pruebas de integración HTTP y base de datos.
- Revisar el manejo de fallos de publicación de eventos después del `COMMIT`.

## 9. Conclusión

El microservicio **`ms-changes`** dispone de la lógica Python correspondiente a los siete endpoints CH-01 a CH-07, con **182 pruebas unitarias aprobadas**.

La implementación cubre la creación, consulta, actualización, planificación, aprobación, rechazo e implementación de solicitudes de cambio.

Quedan pendientes las pruebas de integración con PostgreSQL y AWS, así como la configuración de las rutas correspondientes para su despliegue.