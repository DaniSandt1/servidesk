# ms-requests — ServiDesk

## 1. Descripción

Microservicio encargado de gestionar el **catálogo de servicios, las solicitudes de los usuarios, las aprobaciones y el cumplimiento de solicitudes** dentro de ServiDesk.

Permite consultar servicios disponibles, registrar solicitudes, asignar responsables, actualizar formularios y gestionar el flujo de aprobación y atención.

Utiliza PostgreSQL con aislamiento multi-tenant mediante schemas y publica eventos utilizando el sistema de mensajería SNS de AWS.

**Estado del desarrollo (noviembre de 2026):** los seis endpoints RQ-01 a RQ-06 están implementados y cuentan con **168 pruebas unitarias aprobadas**. La integración con PostgreSQL real, AWS Lambda, API Gateway y SNS todavía está pendiente de validación.

## 2. Referencia y alcance

Referencia funcional: `docs/API_CONTRACTS.md`, sección **8.6 — ms-requests**.

- **Base de datos:** PostgreSQL, `db_requests`.
- **Multi-tenancy:** separación de información mediante schemas, por ejemplo `tenant_andina`, `tenant_pacifico` y `tenant_unitec`.
- **Autenticación:** contexto obtenido del token mediante `tenant_ctx`.
- **Roles:** `admin`, `agent` y `customer`, con permisos según cada operación.
- **Formato de respuesta:** objetos JSON con `data`, y `meta` cuando corresponde.
- **Eventos:** publicación mediante el helper compartido `common.events.publish`.

Las tareas de configuración de Serverless, API Gateway, Authorizer y despliegue corresponden al equipo de integración.

## 3. Endpoints implementados

| ID | Método | Ruta | Handler | Estado |
|---|---|---|---|---|
| RQ-01 | GET | `/catalog` | `listCatalog` | Implementado y probado |
| RQ-02 | GET | `/requests` | `listRequests` | Implementado y probado |
| RQ-03 | POST | `/requests` | `createRequest` | Implementado y probado |
| RQ-04 | GET | `/requests/{id}` | `getRequest` | Implementado y probado |
| RQ-05 | PATCH | `/requests/{id}` | `updateRequest` | Implementado y probado |
| RQ-06 | PUT | `/requests/{id}/status` | `changeRequestStatus` | Implementado y probado |

Todos los endpoints cuentan con pruebas unitarias que utilizan mocks de las dependencias externas.

## 4. Funcionalidades implementadas

### RQ-01 — Consultar catálogo de servicios

**Endpoint:** `GET /catalog`

Permite listar los elementos activos del catálogo de servicios.

Funcionalidades:

- Consulta de servicios disponibles por tenant.
- Filtro por `category_id`.
- Búsqueda por nombre mediante `search`.
- Inclusión del nombre de la categoría.
- Ordenamiento por nombre.
- Acceso para `admin`, `agent` y `customer`.
- Consultas SQL parametrizadas.

**Respuesta exitosa:** `200 OK`.

```json
{
  "data": [
    {
      "id": "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b",
      "category_id": 1,
      "category_name": "Accesos",
      "name": "Acceso VPN",
      "description": "Solicitud de acceso remoto",
      "form_schema": {
        "fields": []
      },
      "needs_approval": true,
      "sla_hours": 24,
      "active": true,
      "created_at": "2026-11-20T09:00:00Z"
    }
  ]
}
```

El catálogo no utiliza paginación, de acuerdo con el contrato de API.

### RQ-02 — Listar solicitudes

**Endpoint:** `GET /requests`

Permite consultar las solicitudes registradas en el tenant autenticado.

Funcionalidades:

- Paginación mediante `page` y `limit`.
- Límite predeterminado de 20 registros y máximo de 100.
- Filtros por estado, elemento del catálogo, solicitante y responsable.
- Búsqueda por clave de solicitud.
- Ordenamiento por fecha, estado o clave.
- Inclusión de metadatos de paginación.
- Restricción de visibilidad para clientes.

**Regla de seguridad:** los usuarios con rol `customer` solamente pueden consultar sus propias solicitudes.

**Respuesta exitosa:** `200 OK`.

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 0,
    "total_pages": 0
  }
}
```

### RQ-03 — Crear solicitud

**Endpoint:** `POST /requests`

Permite registrar una nueva solicitud seleccionando un servicio del catálogo.

Ejemplo de petición:

```json
{
  "catalog_item_id": "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b",
  "form_data": {
    "motivo": "Trabajo remoto",
    "perfil": "Básico"
  }
}
```

Validaciones:

- El servicio debe existir y estar activo.
- `catalog_item_id` debe ser un UUID válido.
- `form_data` debe cumplir el `form_schema` del catálogo.
- Se comprueban los campos obligatorios.
- Se validan los tipos de datos y las opciones de selección.
- No se aceptan campos adicionales.
- `form_data` no puede superar los 8 KB.

El backend establece automáticamente:

- Clave correlativa, por ejemplo `REQ-000001`.
- Identificador del solicitante desde el token.
- Fecha de creación.
- Estado inicial `pending_approval` cuando el servicio requiere aprobación.
- Estado inicial `submitted` cuando no requiere aprobación.

La operación utiliza una transacción PostgreSQL y bloqueo para generar claves correlativas.

**Evento publicado:** `RequestSubmitted`.

**Respuesta exitosa:** `201 Created`.

### RQ-04 — Consultar detalle de solicitud

**Endpoint:** `GET /requests/{id}`

Permite consultar una solicitud específica mediante su UUID.

Incluye:

- Identificador y clave de la solicitud.
- Servicio solicitado.
- Datos del formulario.
- Estado actual.
- Solicitante y responsable.
- Fechas de creación y cumplimiento.
- Historial de aprobaciones.

Reglas:

- `admin` y `agent` pueden consultar solicitudes dentro del tenant.
- `customer` solamente puede consultar solicitudes propias.
- Un UUID inválido devuelve HTTP `400`.
- Una solicitud inexistente devuelve HTTP `404`.
- Un acceso no autorizado devuelve HTTP `403`.

**Respuesta exitosa:** `200 OK` con `ServiceRequestDetail`.

### RQ-05 — Actualizar solicitud

**Endpoint:** `PATCH /requests/{id}`

Permite modificar una solicitud según el rol del usuario.

**Administradores y agentes:**

- Pueden asignar un responsable mediante `assignee_id`.
- Pueden retirar al responsable enviando `null`.

Ejemplo:

```json
{
  "assignee_id": "e4c3b2a1-1234-4567-89ab-0123456789ab"
}
```

**Clientes:**

- Pueden actualizar `form_data`.
- Solo pueden modificar solicitudes propias.
- Únicamente pueden editar solicitudes en estado `submitted` o `pending_approval`.
- El formulario actualizado debe cumplir el esquema definido para el servicio.

La operación utiliza una transacción PostgreSQL y bloqueo de fila mediante `SELECT ... FOR UPDATE`.

Respuestas principales:

- `200`: actualización correcta.
- `400`: datos inválidos o campos no permitidos.
- `403`: operación sin permiso.
- `404`: solicitud inexistente.
- `409`: solicitud que ya no puede editarse.

### RQ-06 — Cambiar estado de solicitud

**Endpoint:** `PUT /requests/{id}/status`

Permite administrar el flujo de aprobación y cumplimiento.

Ejemplo:

```json
{
  "status": "approved"
}
```

Estados admitidos como destino:

- `approved`
- `rejected`
- `in_fulfillment`
- `fulfilled`

Transiciones implementadas:

| Estado actual | Estado siguiente |
|---|---|
| `pending_approval` | `approved`, `rejected` |
| `submitted` | `in_fulfillment` |
| `approved` | `in_fulfillment` |
| `in_fulfillment` | `fulfilled` |

Reglas:

- Solo `admin` puede aprobar o rechazar solicitudes pendientes de aprobación.
- `admin` y `agent` pueden iniciar y completar la atención.
- No se permiten transiciones inválidas ni repetir un estado.
- Al aprobar o rechazar se registra una entrada en `request_approvals`.
- Al completar una solicitud se establece `fulfilled_at`.
- La actualización se realiza dentro de una transacción PostgreSQL.

Eventos publicados:

| Operación | Evento |
|---|---|
| Aprobar solicitud | `RequestApproved` |
| Rechazar solicitud | `RequestRejected` |
| Completar solicitud | `RequestFulfilled` |

El cambio a `in_fulfillment` no publica un evento específico en esta implementación.

**Respuesta exitosa:** `200 OK`.

**Nota:** las transiciones representan la implementación actual y requieren validación final del equipo antes del despliegue.

## 5. Base de datos y migraciones

**Base de datos:** `db_requests`.

**Archivo de migración:** `migrations/001_init.sql`.

Tablas contempladas:

| Tabla | Responsabilidad |
|---|---|
| `catalog_categories` | Categorías del catálogo |
| `catalog_items` | Servicios disponibles y formularios |
| `service_requests` | Solicitudes registradas |
| `request_approvals` | Historial de aprobaciones y rechazos |
| `fulfillment_tasks` | Tareas de cumplimiento |

El archivo `handlers/migrate.py` está preparado para ejecutar la migración en los schemas configurados:

- `tenant_andina`
- `tenant_pacifico`
- `tenant_unitec`

**Estado:** migración SQL preparada, pendiente de ejecución y validación contra PostgreSQL real.

## 6. Seguridad y multi-tenancy

El microservicio aplica las siguientes medidas:

- Obtiene el schema del contexto autenticado.
- No permite seleccionar libremente el tenant mediante el body o los parámetros de consulta.
- Valida los roles permitidos para cada endpoint.
- Restringe las consultas y actualizaciones de clientes a sus propias solicitudes.
- Valida los UUID y los datos recibidos.
- Utiliza consultas SQL parametrizadas.
- Controla los campos que pueden modificarse.
- Usa transacciones y bloqueos para operaciones sensibles.

Los controles de autenticación y autorización también dependen de la integración correcta del Lambda Authorizer.

## 7. Eventos e integración

El microservicio publica eventos mediante `common.events.publish`.

| Evento | Origen |
|---|---|
| `RequestSubmitted` | RQ-03 |
| `RequestApproved` | RQ-06 |
| `RequestRejected` | RQ-06 |
| `RequestFulfilled` | RQ-06 |

Las pruebas unitarias utilizan mocks para comprobar las llamadas de publicación.

**Pendiente:** verificar la publicación y recepción real de eventos mediante AWS SNS/SQS.

La publicación ocurre después del `COMMIT` de la transacción. Para mayor robustez en producción, debe evaluarse un mecanismo de recuperación de eventos fallidos, como el patrón *transactional outbox*.

## 8. Pruebas unitarias

Se ejecutaron **168 pruebas unitarias exitosas** utilizando `pytest` y mocks.

| Endpoint | Pruebas aprobadas |
|---|---:|
| RQ-01 — Consultar catálogo | 24 |
| RQ-02 — Listar solicitudes | 32 |
| RQ-03 — Crear solicitud | 32 |
| RQ-04 — Consultar solicitud | 20 |
| RQ-05 — Actualizar solicitud | 26 |
| RQ-06 — Cambiar estado | 34 |
| **Total** | **168** |

Las pruebas verifican escenarios exitosos, validaciones, permisos, aislamiento por tenant, manejo de errores, transacciones y publicación de eventos simulados.

### Ejecutar todas las pruebas

Desde la raíz del repositorio:

```bash
python -m pytest services/requests/tests/ -v
```

### Ejecutar las pruebas de un endpoint

Ejemplo para RQ-06:

```bash
python -m pytest services/requests/tests/test_requests.py::TestChangeRequestStatus -v
```

Las pruebas no necesitan conexión real a PostgreSQL ni servicios AWS.

**Limitación:** los resultados unitarios no garantizan que las consultas SQL, las migraciones o las integraciones externas funcionen correctamente en el entorno desplegado.

## 9. Estructura del microservicio

```text
services/
└── requests/
    ├── handlers/
    │   ├── requests.py
    │   └── migrate.py
    ├── migrations/
    │   └── 001_init.sql
    ├── tests/
    │   └── test_requests.py
    ├── serverless.yml
    └── README.md
```

### Archivos principales

- `handlers/requests.py`: implementación de los seis endpoints.
- `handlers/migrate.py`: ejecución de la migración por tenant.
- `migrations/001_init.sql`: estructura inicial de la base de datos.
- `tests/test_requests.py`: pruebas unitarias de los seis endpoints.
- `serverless.yml`: configuración de funciones Lambda y rutas HTTP, responsabilidad del equipo de integración.

## 10. Pendientes para la integración

Aunque los seis endpoints cuentan con pruebas unitarias aprobadas, todavía falta:

1. **Validar PostgreSQL:** ejecutar `001_init.sql`, comprobar tablas, restricciones, consultas, claves y transacciones.
2. **Configurar API Gateway:** registrar los endpoints pendientes en `serverless.yml` y asociarlos con sus handlers.
3. **Validar autenticación:** comprobar el contexto recibido del Lambda Authorizer y el aislamiento efectivo entre tenants.
4. **Probar eventos reales:** verificar SNS y el comportamiento ante errores de publicación.
5. **Confirmar reglas de negocio:** revisar con el equipo el flujo definitivo de estados y aprobaciones.
6. **Realizar pruebas de integración:** comprobar los seis endpoints mediante solicitudes HTTP reales.
7. **Revisar la estructura SQL:** contrastar la migración con el diagrama entidad-relación definitivo.
8. **Completar el despliegue:** integrar los componentes AWS con el resto de ServiDesk.

Las operaciones HTTP sobre `fulfillment_tasks` quedan fuera del alcance de esta versión, según el contrato de API.

## 11. Estado final

**Implementación local: completada para RQ-01 a RQ-06.**

- Seis handlers implementados.
- Validaciones y restricciones por rol incorporadas.
- Consultas multi-tenant preparadas.
- Migración inicial SQL preparada.
- Eventos de solicitudes incorporados.
- **168 pruebas unitarias aprobadas.**

**Estado de integración:** pendiente de validación en PostgreSQL y AWS.

**Referencia:** contratos propuestos de ServiDesk, `docs/API_CONTRACTS.md`.

El microservicio está preparado para revisión mediante Pull Request e integración posterior con el sistema.
