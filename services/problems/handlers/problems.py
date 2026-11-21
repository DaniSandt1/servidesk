"""Handlers HTTP de ms-problems."""

import uuid
import json
from datetime import date, datetime
from common.events import publish

from common.http import ok, error, tenant_ctx
from common.db import tenant_conn


def listProblems(event, context):
    """PR-01: GET /problems."""

    # 1. Obtener usuario y tenant desde el token
    ctx = tenant_ctx(event)

    role = ctx["role"]
    user_id = ctx["user_id"]

    # Solo admin y agent pueden consultar problemas
    if role not in ("admin", "agent"):
        return error(
            "No tienes permiso para consultar problemas",
            403,
        )

    # 2. Leer parámetros de la URL
    query = event.get("queryStringParameters") or {}

    # 3. Validar paginación
    try:
        page = int(query.get("page", "1"))
        limit = int(query.get("limit", "20"))
    except (ValueError, TypeError):
        return error(
            "page y limit deben ser números enteros",
            400,
        )

    if page < 1 or not 1 <= limit <= 100:
        return error(
            "page debe ser >= 1 y limit entre 1 y 100",
            400,
        )

    # 4. Validar ordenamiento
    allowed_sort = {
        "created_at",
        "priority",
        "status",
        "key",
    }

    sort_by = query.get("sort_by", "created_at")
    sort_order = query.get("sort_order", "desc")

    if sort_by not in allowed_sort:
        return error(
            "Campo de ordenamiento inválido",
            400,
        )

    if sort_order not in ("asc", "desc"):
        return error(
            "sort_order debe ser asc o desc",
            400,
        )

    # 5. Construir filtros
    conditions = []
    params = {}

    # Filtrar por estado y prioridad
    enum_filters = {
        "status": {
            "new",
            "investigating",
            "known_error",
            "resolved",
            "closed",
        },
        "priority": {
            "P1", "P2", "P3", "P4",
        },
    }

    for field, allowed_values in enum_filters.items():
        value = query.get(field)

        if value is None:
            continue

        values = value.split(",")

        if any(v not in allowed_values for v in values):
            return error(
                f"Filtro inválido: {field}",
                400,
            )

        placeholders = []

        for index, item in enumerate(values):
            name = f"{field}_{index}"
            placeholders.append(f":{name}")
            params[name] = item

        conditions.append(
            f"{field} IN ({', '.join(placeholders)})"
        )

    # 6. Filtrar por CI
    ci_id = query.get("ci_id")

    if ci_id is not None:
        try:
            params["ci_id"] = str(uuid.UUID(ci_id))
        except (ValueError, TypeError, AttributeError):
            return error(
                "ci_id debe ser un UUID válido",
                400,
            )

        conditions.append("ci_id = :ci_id")

    # 7. Filtrar por responsable
    owner_id = query.get("owner_id")

    if owner_id == "me":
        params["owner_id"] = str(
            uuid.UUID(str(user_id))
        ) if user_id else None

        if params["owner_id"] is None:
            return error(
                "No se encontró el usuario autenticado",
                403,
            )

        conditions.append("owner_id = :owner_id")

    elif owner_id is not None:
        try:
            params["owner_id"] = str(uuid.UUID(owner_id))
        except (ValueError, TypeError, AttributeError):
            return error(
                "owner_id debe ser un UUID válido o me",
                400,
            )

        conditions.append("owner_id = :owner_id")

    # 8. Buscar por clave o título
    search = query.get("search")

    if search is not None:
        if not 2 <= len(search) <= 100:
            return error(
                "search debe tener entre 2 y 100 caracteres",
                400,
            )

        conditions.append(
            "(key ILIKE :search OR title ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    # 9. Construir WHERE
    where_sql = ""

    if conditions:
        where_sql = " WHERE " + " AND ".join(conditions)

    # 10. Conectar al schema del tenant
    conn = tenant_conn(ctx["schema"])

    # 11. Contar problemas
    total_rows = conn.run(
        "SELECT COUNT(*) FROM problems" + where_sql,
        **params,
    )

    total = total_rows[0][0]

    # 12. Obtener página solicitada
    offset = (page - 1) * limit

    sql = (
        "SELECT * FROM problems"
        + where_sql
        + f" ORDER BY {sort_by} {sort_order.upper()}, id ASC"
        + " LIMIT :limit OFFSET :offset"
    )

    rows = conn.run(
        sql,
        **params,
        limit=limit,
        offset=offset,
    )

    cols = [column["name"] for column in conn.columns]

    problems_list = [
        dict(zip(cols, row))
        for row in rows
    ]

    # 13. Respuesta según el contrato
    return ok({
        "data": problems_list,
        "meta": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (
                (total + limit - 1) // limit
            ),
        },
    })

def createProblem(event, context):
    """PR-02: POST /problems."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return error(
            "No tienes permiso para crear problemas",
            403,
        )

    # 2. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return error("JSON inválido", 400)

    if not isinstance(body, dict):
        return error(
            "El body debe ser un objeto JSON",
            400,
        )

    # 3. Validar campos permitidos
    allowed_fields = {
        "title",
        "description",
        "priority",
        "ci_id",
        "owner_id",
        "incident_ids",
    }

    unknown = set(body) - allowed_fields

    if unknown:
        return error(
            "Campos no permitidos: "
            + ", ".join(sorted(unknown)),
            400,
        )

    # 4. Validar título
    title = body.get("title")

    if (
        not isinstance(title, str)
        or not 3 <= len(title.strip()) <= 200
    ):
        return error(
            "title debe tener entre 3 y 200 caracteres",
            400,
        )

    title = title.strip()

    # 5. Validar descripción
    description = body.get("description")

    if description is not None:
        if (
            not isinstance(description, str)
            or len(description) > 5000
        ):
            return error(
                "description debe tener máximo 5000 caracteres",
                400,
            )

    # 6. Validar prioridad
    priority = body.get("priority")

    if priority not in ("P1", "P2", "P3", "P4"):
        return error(
            "priority debe ser P1, P2, P3 o P4",
            400,
        )

    # 7. Validar CI
    ci_id = body.get("ci_id")

    if ci_id is not None:
        try:
            ci_id = str(uuid.UUID(ci_id))
        except (ValueError, TypeError, AttributeError):
            return error(
                "ci_id debe ser un UUID válido",
                400,
            )

    # 8. Responsable: por defecto usuario autenticado
    owner_id = body.get("owner_id")

    if owner_id is None:
        owner_id = ctx["user_id"]

    try:
        owner_id = str(uuid.UUID(str(owner_id)))
    except (ValueError, TypeError, AttributeError):
        return error(
            "owner_id debe ser un UUID válido",
            400,
        )

    # 9. Validar incident_ids
    incident_ids = body.get("incident_ids", [])

    if not isinstance(incident_ids, list):
        return error(
            "incident_ids debe ser una lista",
            400,
        )

    if len(incident_ids) > 50:
        return error(
            "incident_ids permite máximo 50 incidentes",
            400,
        )

    validated_ids = []

    for incident_id in incident_ids:
        try:
            validated_ids.append(
                str(uuid.UUID(incident_id))
            )
        except (ValueError, TypeError, AttributeError):
            return error(
                "incident_ids contiene un UUID inválido",
                400,
            )

    # Evitar incidentes repetidos
    validated_ids = list(dict.fromkeys(validated_ids))

    # 10. Conectar al schema del tenant
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 11. Bloquear generación de claves del tenant
        conn.run(
            """
            SELECT pg_advisory_xact_lock(
                hashtext(current_schema() || ':problem_key')
            )
            """
        )

        # 12. Obtener siguiente correlativo
        rows = conn.run(
            """
            SELECT COALESCE(
                MAX(SUBSTRING(key FROM 5)::integer),
                0
            )
            FROM problems
            WHERE key ~ '^PRB-[0-9]{6}$'
            """
        )

        next_number = rows[0][0] + 1

        if next_number > 999999:
            raise RuntimeError(
                "Se agotó el rango de claves de problemas"
            )

        problem_key = f"PRB-{next_number:06d}"

        # 13. Crear problema
        rows = conn.run(
            """
            INSERT INTO problems (
                key,
                title,
                description,
                status,
                priority,
                ci_id,
                owner_id,
                created_at
            )
            VALUES (
                :key,
                :title,
                :description,
                'new',
                :priority,
                :ci_id,
                :owner_id,
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            )
            RETURNING *
            """,
            key=problem_key,
            title=title,
            description=description,
            priority=priority,
            ci_id=ci_id,
            owner_id=owner_id,
        )

        columns = [
            column["name"]
            for column in conn.columns
        ]

        problem = dict(zip(columns, rows[0]))
        problem_id = str(problem["id"])

        # 14. Vincular incidentes
        for incident_id in validated_ids:
            conn.run(
                """
                INSERT INTO problem_incidents (
                    problem_id,
                    incident_id
                )
                VALUES (
                    :problem_id,
                    :incident_id
                )
                ON CONFLICT (
                    problem_id,
                    incident_id
                ) DO NOTHING
                """,
                problem_id=problem_id,
                incident_id=incident_id,
            )

        # 15. Confirmar la transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 16. Construir ProblemDetail
    def serialize(value):
        if isinstance(value, uuid.UUID):
            return str(value)

        if isinstance(value, (datetime, date)):
            return value.isoformat().replace("+00:00", "Z")

        return value

    problem_detail = {
        field: serialize(value)
        for field, value in problem.items()
    }

    problem_detail["incident_ids"] = validated_ids
    problem_detail["known_error"] = None

    # 17. Publicar ProblemCreated después del COMMIT
    publish(
        event_type="ProblemCreated",
        tenant_id=ctx["tenant_id"],
        data={
            "problemId": problem_id,
            "key": problem_key,
            "title": title,
            "priority": priority,
            "ciId": ci_id,
            "ownerId": owner_id,
            "actorId": ctx["user_id"],
        },
        source="ms-problems",
    )

    # 18. Publicar vínculo si hay incidentes
    if validated_ids:
        publish(
            event_type="ProblemIncidentsLinked",
            tenant_id=ctx["tenant_id"],
            data={
                "problemId": problem_id,
                "incidentIds": validated_ids,
                "actorId": ctx["user_id"],
            },
            source="ms-problems",
        )

    # 19. Respuesta oficial PR-02
    return ok({
        "data": problem_detail
    }, 201)

def getProblem(event, context):
    """PR-03: GET /problems/{id}."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return error(
            "No tienes permiso para consultar problemas",
            403,
        )

    # 2. Obtener y validar ID
    path_params = event.get("pathParameters") or {}

    try:
        problem_id = str(
            uuid.UUID(path_params.get("id"))
        )
    except (ValueError, TypeError, AttributeError):
        return error(
            "El ID del problema debe ser un UUID válido",
            400,
        )

    # 3. Conectar al schema del tenant
    conn = tenant_conn(ctx["schema"])

    # 4. Buscar problema
    rows = conn.run(
        """
        SELECT *
        FROM problems
        WHERE id = :problem_id
        """,
        problem_id=problem_id,
    )

    if not rows:
        return error(
            "Problema no encontrado",
            404,
        )

    columns = [
        column["name"]
        for column in conn.columns
    ]

    problem = dict(zip(columns, rows[0]))

    # 5. Consultar incidentes vinculados
    incident_rows = conn.run(
        """
        SELECT incident_id
        FROM problem_incidents
        WHERE problem_id = :problem_id
        ORDER BY incident_id
        """,
        problem_id=problem_id,
    )

    incident_ids = [
        str(row[0])
        for row in incident_rows
    ]

    # 6. Buscar error conocido
    known_error_rows = conn.run(
        """
        SELECT *
        FROM known_errors
        WHERE problem_id = :problem_id
        LIMIT 1
        """,
        problem_id=problem_id,
    )

    known_error = None

    if known_error_rows:
        columns = [
            column["name"]
            for column in conn.columns
        ]

        known_error = dict(
            zip(columns, known_error_rows[0])
        )

    # 7. Serializar UUID y fechas
    def serialize(value):
        if isinstance(value, uuid.UUID):
            return str(value)

        if isinstance(value, datetime):
            if value.tzinfo is None:
                # Las columnas TIMESTAMP de PostgreSQL
                # se almacenan como UTC en este servicio.
                return value.isoformat() + "Z"

            return value.isoformat().replace(
                "+00:00", "Z"
            )

        if isinstance(value, date):
            return value.isoformat()

        return value

    problem_detail = {
        field: serialize(value)
        for field, value in problem.items()
    }

    problem_detail["incident_ids"] = incident_ids

    if known_error is not None:
        problem_detail["known_error"] = {
            field: serialize(value)
            for field, value in known_error.items()
        }
        # El frontend (KnownError.published_at) usa la fecha de publicación
        problem_detail["known_error"]["published_at"] = (
            problem_detail["known_error"].get("created_at")
        )
    else:
        problem_detail["known_error"] = None

    # 8. Responder con ProblemDetail
    return ok({
        "data": problem_detail
    })

def updateProblem(event, context):
    """PR-04: PATCH /problems/{id}."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return error(
            "No tienes permiso para actualizar problemas",
            403,
        )

    # 2. Validar ID
    path_params = event.get("pathParameters") or {}

    try:
        problem_id = str(
            uuid.UUID(path_params.get("id"))
        )
    except (ValueError, TypeError, AttributeError):
        return error(
            "El ID del problema debe ser un UUID válido",
            400,
        )

    # 3. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return error("JSON inválido", 400)

    if not isinstance(body, dict):
        return error(
            "El body debe ser un objeto JSON",
            400,
        )

    # 4. Validar campos permitidos
    allowed_fields = {
        "title",
        "description",
        "priority",
        "root_cause",
        "ci_id",
        "owner_id",
        "fix_change_id",
    }

    unknown = set(body) - allowed_fields

    if unknown:
        return error(
            "Campos no permitidos: "
            + ", ".join(sorted(unknown)),
            400,
        )

    if not body:
        return error(
            "Debes enviar al menos un campo",
            400,
        )

    # 5. Validar título
    if "title" in body:
        title = body["title"]

        if (
            not isinstance(title, str)
            or not 3 <= len(title.strip()) <= 200
        ):
            return error(
                "title debe tener entre 3 y 200 caracteres",
                400,
            )

        body["title"] = title.strip()

    # 6. Validar descripción y causa raíz
    for field in ("description", "root_cause"):
        if field in body:
            value = body[field]

            if value is not None and (
                not isinstance(value, str)
                or len(value) > 5000
            ):
                return error(
                    f"{field} debe tener máximo 5000 caracteres",
                    400,
                )

    # 7. Validar prioridad
    if "priority" in body:
        if body["priority"] not in (
            "P1", "P2", "P3", "P4"
        ):
            return error(
                "priority debe ser P1, P2, P3 o P4",
                400,
            )

    # 8. Validar UUID opcionales
    for field in (
        "ci_id",
        "owner_id",
        "fix_change_id",
    ):
        if field in body and body[field] is not None:
            try:
                body[field] = str(
                    uuid.UUID(body[field])
                )
            except (ValueError, TypeError, AttributeError):
                return error(
                    f"{field} debe ser un UUID válido o null",
                    400,
                )

    # 9. Conectar al esquema del tenant
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # Bloquear el registro durante la actualización
        rows = conn.run(
            """
            SELECT status
            FROM problems
            WHERE id = :problem_id
            FOR UPDATE
            """,
            problem_id=problem_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "Problema no encontrado",
                404,
            )

        # No modificar problemas cerrados
        if rows[0][0] == "closed":
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "No se puede editar un problema cerrado",
                409,
            )

        # Construir UPDATE únicamente con campos permitidos
        assignments = [
            f"{field} = :{field}"
            for field in body
        ]

        sql = (
            "UPDATE problems SET "
            + ", ".join(assignments)
            + " WHERE id = :problem_id"
        )

        conn.run(
            sql,
            problem_id=problem_id,
            **body,
        )

        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 10. Reutilizar PR-03 para devolver ProblemDetail
    return getProblem(event, context)

def changeProblemStatus(event, context):
    """PR-05: PUT /problems/{id}/status."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return error(
            "No tienes permiso para cambiar el estado",
            403,
        )

    # 2. Validar el ID del problema
    path_params = event.get("pathParameters") or {}

    try:
        problem_id = str(uuid.UUID(path_params.get("id")))
    except (ValueError, TypeError, AttributeError):
        return error(
            "El ID del problema debe ser un UUID válido",
            400,
        )

    # 3. Leer el body JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return error("JSON inválido", 400)

    if not isinstance(body, dict):
        return error(
            "El body debe ser un objeto JSON",
            400,
        )

    # 4. Solo se permite enviar el campo status
    if set(body) != {"status"}:
        return error(
            "Debes enviar únicamente el campo status",
            400,
        )

    new_status = body["status"]

    # 5. Estados solicitables mediante PR-05
    allowed_statuses = {
        "investigating",
        "resolved",
        "closed",
    }

    if new_status not in allowed_statuses:
        return error(
            "Estado inválido. Usa investigating, resolved o closed",
            400,
        )

    # 6. Flujo de transiciones aprobado
    allowed_transitions = {
        "new": {"investigating"},
        "investigating": {"resolved"},
        "known_error": {"resolved"},
        "resolved": {"closed"},
        "closed": set(),
    }

    # 7. Conectar al schema del tenant autenticado
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 8. Bloquear el problema para evitar cambios simultáneos
        rows = conn.run(
            """
            SELECT status, root_cause
            FROM problems
            WHERE id = :problem_id
            FOR UPDATE
            """,
            problem_id=problem_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "Problema no encontrado",
                404,
            )

        current_status, root_cause = rows[0]

        # 9. Comprobar que la transición sea válida
        valid_next_statuses = allowed_transitions.get(
            current_status, set()
        )

        if new_status not in valid_next_statuses:
            conn.run("ROLLBACK")
            transaction_started = False

            return error(
                "INVALID_STATUS_TRANSITION: "
                f"No se permite pasar de {current_status} "
                f"a {new_status}",
                409,
            )

        # 10. Para resolver, la causa raíz es obligatoria
        if new_status == "resolved":
            if (
                not isinstance(root_cause, str)
                or not root_cause.strip()
            ):
                conn.run("ROLLBACK")
                transaction_started = False

                return error(
                    "No se puede resolver el problema "
                    "sin registrar root_cause",
                    409,
                )

        # 11. Actualizar el estado
        conn.run(
            """
            UPDATE problems
            SET status = :new_status
            WHERE id = :problem_id
            """,
            new_status=new_status,
            problem_id=problem_id,
        )

        # 12. Confirmar la transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 13. Reutilizar PR-03 para obtener ProblemDetail
    return getProblem(event, context)

def publishKnownError(event, context):
    """PR-06: POST /problems/{id}/known-error."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return error(
            "No tienes permiso para publicar errores conocidos",
            403,
        )

    # 2. Validar ID del problema
    path_params = event.get("pathParameters") or {}

    try:
        problem_id = str(uuid.UUID(path_params.get("id")))
    except (ValueError, TypeError, AttributeError):
        return error(
            "El ID del problema debe ser un UUID válido",
            400,
        )

    # 3. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return error("JSON inválido", 400)

    if not isinstance(body, dict):
        return error(
            "El body debe ser un objeto JSON",
            400,
        )

    # 4. Validar campos permitidos
    allowed_fields = {"symptom", "workaround"}

    unknown = set(body) - allowed_fields

    if unknown:
        return error(
            "Campos no permitidos: "
            + ", ".join(sorted(unknown)),
            400,
        )

    # 5. Validar campos obligatorios
    for field in ("symptom", "workaround"):
        value = body.get(field)

        if (
            not isinstance(value, str)
            or not 3 <= len(value.strip()) <= 5000
        ):
            return error(
                f"{field} debe tener entre 3 y 5000 caracteres",
                400,
            )

        body[field] = value.strip()

    # 6. Conectar al esquema del tenant
    conn = tenant_conn(ctx["schema"])
    transaction_started = False

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 7. Bloquear el problema
        rows = conn.run(
            """
            SELECT status
            FROM problems
            WHERE id = :problem_id
            FOR UPDATE
            """,
            problem_id=problem_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "Problema no encontrado",
                404,
            )

        current_status = rows[0][0]

        # 8. Solo investigar -> error conocido
        if current_status != "investigating":
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "Solo se puede publicar un error conocido "
                "cuando el problema está investigating",
                409,
            )

        # 9. Comprobar que no exista un error conocido
        existing = conn.run(
            """
            SELECT id
            FROM known_errors
            WHERE problem_id = :problem_id
            """,
            problem_id=problem_id,
        )

        if existing:
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "El problema ya tiene un error conocido",
                409,
            )

        # 10. Crear el error conocido
        rows = conn.run(
            """
            INSERT INTO known_errors (
                problem_id,
                symptom,
                workaround
            )
            VALUES (
                :problem_id,
                :symptom,
                :workaround
            )
            RETURNING id
            """,
            problem_id=problem_id,
            symptom=body["symptom"],
            workaround=body["workaround"],
        )

        known_error_id = str(rows[0][0])

        # 11. Cambiar el estado del problema
        conn.run(
            """
            UPDATE problems
            SET status = 'known_error'
            WHERE id = :problem_id
            """,
            problem_id=problem_id,
        )

        # 12. Confirmar la transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 13. Publicar evento después del COMMIT
    publish(
        event_type="KnownErrorPublished",
        tenant_id=ctx["tenant_id"],
        data={
            "problemId": problem_id,
            "knownErrorId": known_error_id,
            "symptom": body["symptom"],
            "workaround": body["workaround"],
            "actorId": ctx["user_id"],
        },
        source="ms-problems",
    )

    # 14. Reutilizar PR-03 para construir ProblemDetail
    detail_response = getProblem(event, context)

    # PR-06 debe responder 201 Created
    detail_response["statusCode"] = 201

    return detail_response

def linkProblemIncidents(event, context):
    """PR-07: POST /problems/{id}/incidents."""

    ctx = tenant_ctx(event)

    # 1. Validar permisos
    if ctx["role"] not in ("admin", "agent"):
        return error(
            "No tienes permiso para vincular incidentes",
            403,
        )

    # 2. Validar ID del problema
    path_params = event.get("pathParameters") or {}

    try:
        problem_id = str(uuid.UUID(path_params.get("id")))
    except (ValueError, TypeError, AttributeError):
        return error(
            "El ID del problema debe ser un UUID válido",
            400,
        )

    # 3. Leer JSON
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return error("JSON inválido", 400)

    if not isinstance(body, dict):
        return error(
            "El body debe ser un objeto JSON",
            400,
        )

    # 4. Solo se permite incident_ids
    if set(body) != {"incident_ids"}:
        return error(
            "Debes enviar únicamente incident_ids",
            400,
        )

    incident_ids = body["incident_ids"]

    # 5. Validar lista de incidentes
    if not isinstance(incident_ids, list):
        return error(
            "incident_ids debe ser una lista",
            400,
        )

    if not 1 <= len(incident_ids) <= 50:
        return error(
            "incident_ids debe contener entre 1 y 50 IDs",
            400,
        )

    # 6. Validar UUID y eliminar duplicados
    validated_ids = []

    for incident_id in incident_ids:
        try:
            normalized_id = str(uuid.UUID(incident_id))
        except (ValueError, TypeError, AttributeError):
            return error(
                "incident_ids contiene un UUID inválido",
                400,
            )

        if normalized_id not in validated_ids:
            validated_ids.append(normalized_id)

    # 7. Conectar al schema del tenant
    conn = tenant_conn(ctx["schema"])
    transaction_started = False
    inserted_ids = []

    try:
        conn.run("BEGIN")
        transaction_started = True

        # 8. Comprobar que el problema exista
        rows = conn.run(
            """
            SELECT id
            FROM problems
            WHERE id = :problem_id
            FOR UPDATE
            """,
            problem_id=problem_id,
        )

        if not rows:
            conn.run("ROLLBACK")
            transaction_started = False
            return error(
                "Problema no encontrado",
                404,
            )

        # 9. Vincular solo los incidentes nuevos
        for incident_id in validated_ids:
            rows = conn.run(
                """
                INSERT INTO problem_incidents (
                    problem_id,
                    incident_id
                )
                VALUES (
                    :problem_id,
                    :incident_id
                )
                ON CONFLICT (
                    problem_id,
                    incident_id
                ) DO NOTHING
                RETURNING incident_id
                """,
                problem_id=problem_id,
                incident_id=incident_id,
            )

            if rows:
                inserted_ids.append(str(rows[0][0]))

        # 10. Confirmar la transacción
        conn.run("COMMIT")
        transaction_started = False

    except Exception:
        if transaction_started:
            conn.run("ROLLBACK")
        raise

    # 11. Publicar evento solo por vínculos nuevos
    if inserted_ids:
        publish(
            event_type="ProblemIncidentsLinked",
            tenant_id=ctx["tenant_id"],
            data={
                "problemId": problem_id,
                "incidentIds": inserted_ids,
                "actorId": ctx["user_id"],
            },
            source="ms-problems",
        )

    # 12. Devolver ProblemDetail actualizado
    return getProblem(event, context)

