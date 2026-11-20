"""Pruebas unitarias de ms-changes: CH-01."""

import json
import sys
import types
import unittest
import uuid

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch



# Preparar ruta del microservicio
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# Simular el Layer común de AWS
if "common" not in sys.modules:
    common = types.ModuleType("common")
    common.__path__ = []
    sys.modules["common"] = common

if "common.db" not in sys.modules:
    db = types.ModuleType("common.db")
    db.tenant_conn = MagicMock()
    sys.modules["common.db"] = db

if "common.http" not in sys.modules:
    http = types.ModuleType("common.http")

    def tenant_ctx(event):
        return event["requestContext"]["authorizer"]["lambda"]

    def ok(body, status=200):
        return {
            "statusCode": status,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(body, default=str),
        }

    http.tenant_ctx = tenant_ctx
    http.ok = ok
    sys.modules["common.http"] = http

if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import changes

class TestListChanges(unittest.TestCase):
    """Pruebas CH-01: GET /changes."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.user_id,
                    }
                }
            },
            "queryStringParameters": None,
        }

        self.change = {
            "id": self.change_id,
            "key": "CHG-000001",
            "title": "Actualizar servidor",
            "description": "Actualización de firmware",
            "type": "normal",
            "risk": "medium",
            "status": "draft",
            "rollback_plan": "Restaurar respaldo",
            "planned_start": datetime(
                2026, 11, 25, 10, 0
            ),
            "planned_end": datetime(
                2026, 11, 25, 12, 0
            ),
            "requester_id": self.user_id,
            "problem_id": None,
            "created_at": datetime(
                2026, 11, 20, 9, 0
            ),
        }

        self.mock_conn = MagicMock()
        self.mock_conn.columns = [
            {"name": name}
            for name in self.change
        ]

        def fake_run(sql, **params):
            if "SELECT COUNT(*) FROM changes" in sql:
                return [(1,)]

            if "SELECT * FROM changes" in sql:
                return [tuple(self.change.values())]

            raise AssertionError(
                f"SQL inesperado: {sql}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return changes.listChanges(
            self.event, None
        )

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_listar_cambios_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(
            body["data"][0]["key"],
            "CHG-000001",
        )
        self.assertEqual(body["meta"]["total"], 1)
        self.assertEqual(body["meta"]["page"], 1)
        self.assertEqual(body["meta"]["limit"], 20)

    # TEST 2
    def test_admin_puede_listar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_customer_no_autorizado(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 4
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 5
    def test_paginacion_personalizada(self):
        self.event["queryStringParameters"] = {
            "page": "2",
            "limit": "10",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT * FROM changes"
        )[0]

        self.assertEqual(sql_call.kwargs["limit"], 10)
        self.assertEqual(sql_call.kwargs["offset"], 10)

    # TEST 6
    def test_pagina_invalida(self):
        self.event["queryStringParameters"] = {
            "page": "0",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_limit_mayor_a_100(self):
        self.event["queryStringParameters"] = {
            "limit": "101",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 8
    def test_filtro_estado(self):
        self.event["queryStringParameters"] = {
            "status": "draft,submitted",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT COUNT(*) FROM changes"
        )[0]

        self.assertIn(
            "status IN (:status_0, :status_1)",
            sql_call.args[0],
        )

        self.assertEqual(
            sql_call.kwargs["status_0"],
            "draft",
        )

    # TEST 9
    def test_filtro_tipo(self):
        self.event["queryStringParameters"] = {
            "type": "normal,emergency",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT COUNT(*) FROM changes"
        )[0]

        self.assertIn(
            "type IN (:type_0, :type_1)",
            sql_call.args[0],
        )

    # TEST 10
    def test_filtro_riesgo(self):
        self.event["queryStringParameters"] = {
            "risk": "high",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT COUNT(*) FROM changes"
        )[0]

        self.assertIn(
            "risk IN (:risk_0)",
            sql_call.args[0],
        )

    # TEST 11
    def test_filtro_estado_invalido(self):
        self.event["queryStringParameters"] = {
            "status": "inventado",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_requester_me(self):
        self.event["queryStringParameters"] = {
            "requester_id": "me",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT COUNT(*) FROM changes"
        )[0]

        self.assertEqual(
            sql_call.kwargs["requester_id"],
            self.user_id,
        )

    # TEST 13
    def test_requester_uuid_invalido(self):
        self.event["queryStringParameters"] = {
            "requester_id": "usuario123",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 14
    def test_busqueda_por_titulo_o_clave(self):
        self.event["queryStringParameters"] = {
            "search": "servidor",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT COUNT(*) FROM changes"
        )[0]

        self.assertIn(
            "key ILIKE :search",
            sql_call.args[0],
        )

        self.assertIn(
            "title ILIKE :search",
            sql_call.args[0],
        )

        self.assertEqual(
            sql_call.kwargs["search"],
            "%servidor%",
        )

    # TEST 15
    def test_busqueda_muy_corta(self):
        self.event["queryStringParameters"] = {
            "search": "a",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_ordenamiento_personalizado(self):
        self.event["queryStringParameters"] = {
            "sort_by": "planned_start",
            "sort_order": "asc",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT * FROM changes"
        )[0]

        self.assertIn(
            "ORDER BY planned_start ASC",
            sql_call.args[0],
        )

    # TEST 17
    def test_sort_by_invalido(self):
        self.event["queryStringParameters"] = {
            "sort_by": "DROP TABLE changes",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_sort_order_invalido(self):
        self.event["queryStringParameters"] = {
            "sort_order": "random",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 19
    def test_filtro_calendario(self):
        self.event["queryStringParameters"] = {
            "planned_from": "2026-11-25T00:00:00Z",
            "planned_to": "2026-11-26T00:00:00Z",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        sql_call = self.consultas(
            "SELECT COUNT(*) FROM changes"
        )[0]

        self.assertIn(
            "planned_end >= :planned_from",
            sql_call.args[0],
        )

        self.assertIn(
            "planned_start <= :planned_to",
            sql_call.args[0],
        )

    # TEST 20
    def test_fecha_calendario_invalida(self):
        self.event["queryStringParameters"] = {
            "planned_from": "fecha-invalida",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 21
    def test_rango_fechas_invertido(self):
        self.event["queryStringParameters"] = {
            "planned_from": "2026-11-26T00:00:00Z",
            "planned_to": "2026-11-25T00:00:00Z",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 22
    def test_serializacion_fechas(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(
            response["body"]
        )["data"][0]

        self.assertEqual(
            data["planned_start"],
            "2026-11-25T10:00:00Z",
        )

        self.assertEqual(
            data["created_at"],
            "2026-11-20T09:00:00Z",
        )

    # TEST 23
    def test_sin_cambios(self):
        def fake_empty_run(sql, **params):
            if "COUNT(*)" in sql:
                return [(0,)]
            return []

        self.mock_conn.run.side_effect = fake_empty_run

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["data"], [])
        self.assertEqual(body["meta"]["total"], 0)
        self.assertEqual(body["meta"]["total_pages"], 0)

    # TEST 24
    def test_limite_invalido_no_numerico(self):
        self.event["queryStringParameters"] = {
            "limit": "abc",
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

class TestCreateChange(unittest.TestCase):
    """Pruebas CH-02: POST /changes."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.ci_id = str(uuid.uuid4())
        self.problem_id = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.user_id,
                    }
                }
            },
            "body": json.dumps({
                "title": "Actualizar firmware",
                "description": "Actualizar servidor principal",
                "type": "normal",
                "risk": "medium",
                "rollback_plan": "Restaurar respaldo",
                "planned_start": "2026-11-25T10:00:00Z",
                "planned_end": "2026-11-25T12:00:00Z",
                "problem_id": self.problem_id,
                "cis": [
                    {
                        "ci_id": self.ci_id,
                        "new_version": "15.1.8",
                    }
                ],
            }),
        }

        self.mock_conn = MagicMock()
        self.fail_ci_insert = False

        self.change = {
            "id": self.change_id,
            "key": "CHG-000001",
            "title": "Actualizar firmware",
            "description": "Actualizar servidor principal",
            "type": "normal",
            "risk": "medium",
            "status": "draft",
            "rollback_plan": "Restaurar respaldo",
            "planned_start": datetime(
                2026, 11, 25, 10, 0
            ),
            "planned_end": datetime(
                2026, 11, 25, 12, 0
            ),
            "requester_id": self.user_id,
            "problem_id": self.problem_id,
            "created_at": datetime(
                2026, 11, 20, 9, 0
            ),
        }

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if "pg_advisory_xact_lock" in query:
                return [(None,)]

            if "MAX(SUBSTRING" in query:
                return [(0,)]

            if "INSERT INTO changes" in query:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in self.change
                ]

                self.change["key"] = params["key"]
                self.change["title"] = params["title"]
                self.change["description"] = params["description"]
                self.change["type"] = params["type"]
                self.change["risk"] = params["risk"]
                self.change["rollback_plan"] = (
                    params["rollback_plan"]
                )
                self.change["planned_start"] = (
                    params["planned_start"]
                )
                self.change["planned_end"] = (
                    params["planned_end"]
                )
                self.change["requester_id"] = (
                    params["requester_id"]
                )
                self.change["problem_id"] = (
                    params["problem_id"]
                )

                return [tuple(self.change.values())]

            if "INSERT INTO change_cis" in query:
                if self.fail_ci_insert:
                    raise RuntimeError(
                        "Error simulado al vincular CI"
                    )
                return []

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return changes.createChange(
            self.event, None
        )

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    def cambiar_body(self, **updates):
        body = json.loads(self.event["body"])
        body.update(updates)
        self.event["body"] = json.dumps(body)

    # TEST 1
    def test_crear_cambio_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["key"], "CHG-000001")
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["title"], "Actualizar firmware")
        self.assertEqual(len(data["cis"]), 1)
        self.assertEqual(data["approvals"], [])

    # TEST 2
    def test_admin_puede_crear(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 3
    def test_customer_no_puede_crear(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 4
    def test_aislamiento_por_tenant(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)
        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 5
    def test_titulo_obligatorio(self):
        self.cambiar_body(title="")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_descripcion_mayor_a_5000(self):
        self.cambiar_body(description="A" * 5001)

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_tipo_invalido(self):
        self.cambiar_body(type="urgente")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 8
    def test_riesgo_invalido(self):
        self.cambiar_body(risk="critical")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 9
    def test_rollback_plan_mayor_a_5000(self):
        self.cambiar_body(
            rollback_plan="R" * 5001
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 10
    def test_fechas_invertidas(self):
        self.cambiar_body(
            planned_start="2026-11-26T10:00:00Z",
            planned_end="2026-11-25T10:00:00Z",
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 11
    def test_fecha_invalida(self):
        self.cambiar_body(
            planned_start="fecha-invalida"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_problem_id_invalido(self):
        self.cambiar_body(
            problem_id="PRB-000001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_cis_duplicados(self):
        self.cambiar_body(
            cis=[
                {"ci_id": self.ci_id},
                {"ci_id": self.ci_id},
            ]
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 14
    def test_maximo_50_cis(self):
        self.cambiar_body(
            cis=[
                {"ci_id": str(uuid.uuid4())}
                for _ in range(51)
            ]
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 15
    def test_new_version_maximo_50(self):
        self.cambiar_body(
            cis=[{
                "ci_id": self.ci_id,
                "new_version": "V" * 51,
            }]
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_campos_no_permitidos(self):
        self.cambiar_body(status="approved")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_crear_sin_cis(self):
        self.cambiar_body(cis=[])

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["cis"], [])
        self.assertEqual(
            len(self.consultas("INSERT INTO change_cis")),
            0,
        )

    # TEST 19
    def test_requester_se_obtiene_del_token(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        insert = self.consultas(
            "INSERT INTO changes"
        )[0]

        self.assertEqual(
            insert.kwargs["requester_id"],
            self.user_id,
        )

    # TEST 20
    def test_generacion_de_clave(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.assertEqual(
            len(self.consultas("pg_advisory_xact_lock")),
            1,
        )

        insert = self.consultas(
            "INSERT INTO changes"
        )[0]

        self.assertEqual(
            insert.kwargs["key"],
            "CHG-000001",
        )

    # TEST 21
    def test_transaccion_commit(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.assertEqual(
            len(self.consultas("BEGIN")),
            1,
        )

        self.assertEqual(
            len(self.consultas("COMMIT")),
            1,
        )

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            0,
        )

    # TEST 22
    def test_rollback_si_falla_insert_ci(self):
        self.fail_ci_insert = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("BEGIN")),
            1,
        )

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )

        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )

    # TEST 23
    def test_cambio_standard(self):
        self.cambiar_body(
            type="standard",
            risk="low",
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["type"], "standard")
        self.assertEqual(data["risk"], "low")
        self.assertEqual(data["status"], "draft")

    # TEST 24
    def test_fechas_se_guardan_en_utc(self):
        self.cambiar_body(
            planned_start="2026-11-25T05:00:00-05:00",
            planned_end="2026-11-25T07:00:00-05:00",
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        insert = self.consultas(
            "INSERT INTO changes"
        )[0]

        self.assertEqual(
            insert.kwargs["planned_start"],
            datetime(2026, 11, 25, 10, 0),
        )

        self.assertEqual(
            insert.kwargs["planned_end"],
            datetime(2026, 11, 25, 12, 0),
        )

class TestGetChange(unittest.TestCase):
    """Pruebas CH-03: GET /changes/{id}."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.ci_id = str(uuid.uuid4())
        self.approval_id = str(uuid.uuid4())
        self.approver_id = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.user_id,
                    }
                }
            },
            "pathParameters": {
                "id": self.change_id,
            },
        }

        self.change_exists = True

        self.change = {
            "id": uuid.UUID(self.change_id),
            "key": "CHG-000001",
            "title": "Actualizar firmware",
            "description": "Actualizar servidor principal",
            "type": "normal",
            "risk": "medium",
            "status": "draft",
            "rollback_plan": "Restaurar respaldo",
            "planned_start": datetime(
                2026, 11, 25, 10, 0
            ),
            "planned_end": datetime(
                2026, 11, 25, 12, 0
            ),
            "requester_id": uuid.UUID(self.user_id),
            "problem_id": None,
            "created_at": datetime(
                2026, 11, 20, 9, 0
            ),
        }

        self.cis = [
            {
                "ci_id": uuid.UUID(self.ci_id),
                "new_version": "15.1.8",
            }
        ]

        self.approvals = [
            {
                "id": uuid.UUID(self.approval_id),
                "change_id": uuid.UUID(self.change_id),
                "approver_id": uuid.UUID(self.approver_id),
                "decision": "approved",
                "comment": "Aprobado por CAB",
                "decided_at": datetime(
                    2026, 11, 21, 10, 0
                ),
            }
        ]

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            # Consultar cambio principal
            if "FROM changes" in query:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in self.change
                ]

                if not self.change_exists:
                    return []

                return [tuple(self.change.values())]

            # Consultar CI afectados
            if "FROM change_cis" in query:
                self.mock_conn.columns = [
                    {"name": "ci_id"},
                    {"name": "new_version"},
                ]

                return [
                    (
                        item["ci_id"],
                        item["new_version"],
                    )
                    for item in self.cis
                ]

            # Consultar aprobaciones
            if "FROM change_approvals" in query:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in (
                        "id",
                        "change_id",
                        "approver_id",
                        "decision",
                        "comment",
                        "decided_at",
                    )
                ]

                return [
                    tuple(item.values())
                    for item in self.approvals
                ]

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return changes.getChange(
            self.event, None
        )

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_consultar_cambio_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(
            data["id"],
            self.change_id,
        )

        self.assertEqual(
            data["key"],
            "CHG-000001",
        )

        self.assertEqual(
            data["status"],
            "draft",
        )

    # TEST 2
    def test_admin_puede_consultar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_customer_no_puede_consultar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 4
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = (
            "CHG-000001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 5
    def test_uuid_ausente(self):
        self.event["pathParameters"] = None

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_cambio_no_existe(self):
        self.change_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)

        self.assertEqual(
            len(self.consultas("FROM change_cis")),
            0,
        )

        self.assertEqual(
            len(self.consultas("FROM change_approvals")),
            0,
        )

    # TEST 7
    def test_consultar_cis_afectados(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(len(data["cis"]), 1)

        self.assertEqual(
            data["cis"][0]["ci_id"],
            self.ci_id,
        )

        self.assertEqual(
            data["cis"][0]["new_version"],
            "15.1.8",
        )

    # TEST 8
    def test_consultar_aprobaciones(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(
            len(data["approvals"]),
            1,
        )

        approval = data["approvals"][0]

        self.assertEqual(
            approval["id"],
            self.approval_id,
        )

        self.assertEqual(
            approval["approver_id"],
            self.approver_id,
        )

        self.assertEqual(
            approval["decision"],
            "approved",
        )

    # TEST 9
    def test_cambio_sin_cis(self):
        self.cis = []

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["cis"], [])
        self.assertEqual(len(data["approvals"]), 1)

    # TEST 10
    def test_cambio_sin_aprobaciones(self):
        self.approvals = []

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["approvals"], [])

    # TEST 11
    def test_cambio_sin_relaciones(self):
        self.cis = []
        self.approvals = []

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["cis"], [])
        self.assertEqual(data["approvals"], [])

    # TEST 12
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 13
    def test_consultas_usan_id_correcto(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        for fragment in (
            "FROM changes",
            "FROM change_cis",
            "FROM change_approvals",
        ):
            query = self.consultas(fragment)[0]

            self.assertEqual(
                query.kwargs["change_id"],
                self.change_id,
            )

    # TEST 14
    def test_serializacion_fechas(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(
            data["planned_start"],
            "2026-11-25T10:00:00Z",
        )

        self.assertEqual(
            data["created_at"],
            "2026-11-20T09:00:00Z",
        )

        self.assertEqual(
            data["approvals"][0]["decided_at"],
            "2026-11-21T10:00:00Z",
        )

    # TEST 15
    def test_no_modifica_la_base_de_datos(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        for call in self.mock_conn.run.call_args_list:
            sql = call.args[0].strip().upper()

            self.assertTrue(
                sql.startswith("SELECT")
            )

    # TEST 16
    def test_consultas_ordenadas(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        ci_query = self.consultas(
            "FROM change_cis"
        )[0]

        approval_query = self.consultas(
            "FROM change_approvals"
        )[0]

        self.assertIn(
            "ORDER BY ci_id ASC",
            ci_query.args[0],
        )

        self.assertIn(
            "ORDER BY decided_at ASC, id ASC",
            approval_query.args[0],
        )

class TestUpdateChange(unittest.TestCase):
    """Pruebas CH-04: PATCH /changes/{id}."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.ci_id_1 = str(uuid.uuid4())
        self.ci_id_2 = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.user_id,
                    }
                }
            },
            "pathParameters": {
                "id": self.change_id,
            },
            "body": json.dumps({
                "title": "Actualizar firmware versión 2",
            }),
        }

        self.change_exists = True
        self.current_status = "draft"

        self.current_start = datetime(
            2026, 11, 25, 10, 0
        )
        self.current_end = datetime(
            2026, 11, 25, 12, 0
        )

        self.fail_update = False
        self.fail_ci_insert = False

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if (
                "FROM changes" in query
                and "FOR UPDATE" in query
            ):
                if not self.change_exists:
                    return []

                return [(
                    self.current_status,
                    self.current_start,
                    self.current_end,
                )]

            if query.startswith("UPDATE changes"):
                if self.fail_update:
                    raise RuntimeError(
                        "Error simulado al actualizar cambio"
                    )
                return []

            if query.startswith("DELETE FROM change_cis"):
                return []

            if query.startswith("INSERT INTO change_cis"):
                if self.fail_ci_insert:
                    raise RuntimeError(
                        "Error simulado insertando CI"
                    )
                return []

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.detail_response = {
            "statusCode": 200,
            "body": json.dumps({
                "data": {
                    "id": self.change_id,
                    "status": "draft",
                    "title": "Actualizar firmware versión 2",
                    "cis": [],
                    "approvals": [],
                }
            }),
        }

        self.detail_patch = patch.object(
            changes,
            "getChange",
            return_value=self.detail_response,
        )
        self.mock_detail = self.detail_patch.start()
        self.addCleanup(self.detail_patch.stop)

    def ejecutar(self):
        return changes.updateChange(
            self.event, None
        )

    def cambiar_body(self, **updates):
        body = json.loads(self.event["body"])
        body.update(updates)
        self.event["body"] = json.dumps(body)

    def reemplazar_body(self, body):
        self.event["body"] = json.dumps(body)

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_actualizar_cambio_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            1,
        )

        self.assertEqual(
            len(self.consultas("COMMIT")),
            1,
        )

        self.mock_detail.assert_called_once_with(
            self.event, None
        )

    # TEST 2
    def test_admin_puede_actualizar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_customer_no_puede_actualizar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()
        self.mock_detail.assert_not_called()

    # TEST 4
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = (
            "CHG-000001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 5
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_body_vacio(self):
        self.reemplazar_body({})

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_campos_no_permitidos(self):
        self.reemplazar_body({
            "status": "approved",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 8
    def test_titulo_invalido(self):
        self.reemplazar_body({
            "title": "A",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 9
    def test_descripcion_mayor_a_5000(self):
        self.reemplazar_body({
            "description": "A" * 5001,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 10
    def test_tipo_invalido(self):
        self.reemplazar_body({
            "type": "urgent",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 11
    def test_riesgo_invalido(self):
        self.reemplazar_body({
            "risk": "critical",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_problem_id_invalido(self):
        self.reemplazar_body({
            "problem_id": "PRB-000001",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_cambio_no_existe(self):
        self.change_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )

        self.mock_detail.assert_not_called()

    # TEST 14
    def test_no_editar_cambio_submitted(self):
        self.current_status = "submitted"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

        self.mock_detail.assert_not_called()

    # TEST 15
    def test_no_editar_cambio_approved(self):
        self.current_status = "approved"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 16
    def test_no_editar_cambio_implemented(self):
        self.current_status = "implemented"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 17
    def test_actualizar_varios_campos(self):
        self.reemplazar_body({
            "title": "Actualizar balanceador",
            "risk": "high",
            "type": "emergency",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "UPDATE changes"
        )[0]

        self.assertIn("title = :title", query.args[0])
        self.assertIn("risk = :risk", query.args[0])
        self.assertIn("type = :type", query.args[0])

        self.assertEqual(
            query.kwargs["risk"],
            "high",
        )

    # TEST 18
    def test_actualizar_fechas_validas(self):
        self.reemplazar_body({
            "planned_start": "2026-11-26T10:00:00Z",
            "planned_end": "2026-11-26T12:00:00Z",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "UPDATE changes"
        )[0]

        self.assertEqual(
            query.kwargs["planned_start"],
            datetime(2026, 11, 26, 10, 0),
        )

    # TEST 19
    def test_fechas_invertidas(self):
        self.reemplazar_body({
            "planned_start": "2026-11-26T10:00:00Z",
            "planned_end": "2026-11-25T10:00:00Z",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )

        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 20
    def test_validar_fechas_parciales(self):
        # Modificar solo inicio, dejando el fin anterior
        self.reemplazar_body({
            "planned_start": "2026-11-26T10:00:00Z",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 21
    def test_reemplazar_cis(self):
        self.reemplazar_body({
            "cis": [
                {
                    "ci_id": self.ci_id_1,
                    "new_version": "16.0",
                },
                {
                    "ci_id": self.ci_id_2,
                    "new_version": "17.0",
                },
            ],
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("DELETE FROM change_cis")),
            1,
        )

        self.assertEqual(
            len(self.consultas("INSERT INTO change_cis")),
            2,
        )

        # Cambiar únicamente CIS no ejecuta UPDATE changes
        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 22
    def test_vaciar_lista_cis(self):
        self.reemplazar_body({
            "cis": [],
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("DELETE FROM change_cis")),
            1,
        )

        self.assertEqual(
            len(self.consultas("INSERT INTO change_cis")),
            0,
        )

    # TEST 23
    def test_no_modificar_cis_si_no_se_envian(self):
        self.reemplazar_body({
            "risk": "high",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("DELETE FROM change_cis")),
            0,
        )

    # TEST 24
    def test_cis_duplicados(self):
        self.reemplazar_body({
            "cis": [
                {"ci_id": self.ci_id_1},
                {"ci_id": self.ci_id_1},
            ],
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 25
    def test_maximo_50_cis(self):
        self.reemplazar_body({
            "cis": [
                {"ci_id": str(uuid.uuid4())}
                for _ in range(51)
            ],
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 26
    def test_new_version_muy_larga(self):
        self.reemplazar_body({
            "cis": [{
                "ci_id": self.ci_id_1,
                "new_version": "V" * 51,
            }],
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 27
    def test_rollback_si_falla_update(self):
        self.fail_update = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )

        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )

        self.mock_detail.assert_not_called()

    # TEST 28
    def test_rollback_si_falla_insert_ci(self):
        self.reemplazar_body({
            "cis": [{
                "ci_id": self.ci_id_1,
                "new_version": "16.0",
            }],
        })

        self.fail_ci_insert = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )

        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )

        self.mock_detail.assert_not_called()

    # TEST 29
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 30
    def test_transaccion_y_respuesta_detalle(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        consultas = [
            call.args[0].strip()
            for call in self.mock_conn.run.call_args_list
        ]

        self.assertEqual(consultas[0], "BEGIN")
        self.assertEqual(consultas[-1], "COMMIT")

        self.assertIn(
            "FOR UPDATE",
            consultas[1],
        )

        self.mock_detail.assert_called_once_with(
            self.event, None
        )

class TestChangeChangeStatus(unittest.TestCase):
    """Pruebas CH-05: PUT /changes/{id}/status."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "agent",
                        "user_id": self.user_id,
                    }
                }
            },
            "pathParameters": {
                "id": self.change_id,
            },
            "body": json.dumps({
                "status": "submitted"
            }),
        }

        self.current_status = "draft"
        self.change_type = "normal"
        self.rollback_plan = "Restaurar respaldo"
        self.planned_start = datetime(
            2026, 11, 25, 10, 0
        )
        self.planned_end = datetime(
            2026, 11, 25, 12, 0
        )
        self.change_exists = True
        self.fail_update = False
        self.updated_status = None

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if (
                "FROM changes" in query
                and "FOR UPDATE" in query
            ):
                if not self.change_exists:
                    return []

                return [(
                    self.current_status,
                    self.change_type,
                    self.rollback_plan,
                    self.planned_start,
                    self.planned_end,
                    "CHG-000001",
                    "medium",
                )]

            if query.startswith("UPDATE changes"):
                if self.fail_update:
                    raise RuntimeError(
                        "Error simulado de PostgreSQL"
                    )

                self.updated_status = params["new_status"]
                return []

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.publish_patch = patch.object(
            changes,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()
        self.addCleanup(self.publish_patch.stop)

        self.detail_response = {
            "statusCode": 200,
            "body": json.dumps({
                "data": {
                    "id": self.change_id,
                    "status": "submitted",
                    "cis": [],
                    "approvals": [],
                }
            }),
        }

        self.detail_patch = patch.object(
            changes,
            "getChange",
            return_value=self.detail_response,
        )
        self.mock_detail = self.detail_patch.start()
        self.addCleanup(self.detail_patch.stop)

    def ejecutar(self):
        return changes.changeChangeStatus(
            self.event, None
        )

    def cambiar_estado(self, status):
        self.event["body"] = json.dumps({
            "status": status,
        })

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_draft_a_submitted(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.updated_status,
            "submitted",
        )
        self.mock_detail.assert_called_once()

    # TEST 2
    def test_standard_se_aprueba_automaticamente(self):
        self.change_type = "standard"
        self.rollback_plan = None

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.updated_status,
            "approved",
        )

    # TEST 3
    def test_emergency_a_submitted(self):
        self.change_type = "emergency"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.updated_status,
            "submitted",
        )

    # TEST 4
    def test_publicar_change_submitted(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_publish.assert_called_once()

        kwargs = self.mock_publish.call_args.kwargs

        self.assertEqual(
            kwargs["event_type"],
            "ChangeSubmitted",
        )
        self.assertEqual(
            kwargs["tenant_id"],
            "andina",
        )
        self.assertEqual(
            kwargs["data"]["changeId"],
            self.change_id,
        )
        self.assertEqual(
            kwargs["data"]["actorId"],
            self.user_id,
        )
        self.assertEqual(
            kwargs["source"],
            "ms-changes",
        )

    # TEST 5
    def test_evento_standard_contiene_estado_approved(self):
        self.change_type = "standard"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        kwargs = self.mock_publish.call_args.kwargs

        self.assertEqual(
            kwargs["event_type"],
            "ChangeSubmitted",
        )
        self.assertEqual(
            kwargs["data"]["status"],
            "approved",
        )

    # TEST 6
    def test_rejected_a_draft(self):
        self.current_status = "rejected"
        self.cambiar_estado("draft")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.updated_status, "draft")
        self.mock_publish.assert_not_called()

    # TEST 7
    def test_approved_a_scheduled(self):
        self.current_status = "approved"
        self.cambiar_estado("scheduled")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.updated_status,
            "scheduled",
        )
        self.mock_publish.assert_not_called()

    # TEST 8
    def test_scheduled_a_implemented(self):
        self.current_status = "scheduled"
        self.cambiar_estado("implemented")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.updated_status,
            "implemented",
        )

        self.assertEqual(
            self.mock_publish.call_args.kwargs["event_type"],
            "ChangeImplemented",
        )

    # TEST 9
    def test_scheduled_a_failed(self):
        self.current_status = "scheduled"
        self.cambiar_estado("failed")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.updated_status, "failed")
        self.mock_publish.assert_not_called()

    # TEST 10
    def test_no_saltar_draft_a_scheduled(self):
        self.cambiar_estado("scheduled")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 11
    def test_no_repetir_estado(self):
        self.current_status = "submitted"
        self.cambiar_estado("submitted")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)
        self.mock_publish.assert_not_called()

    # TEST 12
    def test_submitted_no_pasa_directo_a_scheduled(self):
        self.current_status = "submitted"
        self.cambiar_estado("scheduled")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 13
    def test_implemented_es_final(self):
        self.current_status = "implemented"
        self.cambiar_estado("draft")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 14
    def test_failed_es_final(self):
        self.current_status = "failed"
        self.cambiar_estado("draft")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 15
    def test_approved_directo_prohibido(self):
        self.cambiar_estado("approved")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_rejected_directo_prohibido(self):
        self.cambiar_estado("rejected")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17
    def test_fechas_obligatorias_para_enviar(self):
        self.planned_start = None

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.mock_publish.assert_not_called()

    # TEST 18
    def test_fechas_invertidas_no_permitidas(self):
        self.planned_end = datetime(
            2026, 11, 24, 12, 0
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            0,
        )

    # TEST 19
    def test_rollback_obligatorio_para_normal(self):
        self.rollback_plan = None

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_publish.assert_not_called()

    # TEST 20
    def test_rollback_vacio_no_permitido(self):
        self.rollback_plan = "   "

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 21
    def test_customer_no_autorizado(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 22
    def test_admin_autorizado(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 23
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = "CHG-001"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 24
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 25
    def test_campos_extra_no_permitidos(self):
        self.event["body"] = json.dumps({
            "status": "submitted",
            "risk": "high",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 26
    def test_cambio_inexistente(self):
        self.change_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.mock_publish.assert_not_called()

    # TEST 27
    def test_rollback_si_falla_postgresql(self):
        self.fail_update = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 28
    def test_aislamiento_por_tenant(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_andina"
        )

    # TEST 29
    def test_evento_se_publica_despues_commit(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("COMMIT")),
            1,
        )
        self.mock_publish.assert_called_once()

        sql_queries = [
            call.args[0].strip()
            for call in self.mock_conn.run.call_args_list
        ]

        self.assertEqual(sql_queries[-1], "COMMIT")

    # TEST 30
    def test_devolver_detalle_actualizado(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_detail.assert_called_once_with(
            self.event, None
        )

        self.assertEqual(
            response,
            self.detail_response,
        )

class TestApproveChange(unittest.TestCase):
    """Pruebas CH-06: POST /changes/{id}/approve."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.approver_id = str(uuid.uuid4())
        self.requester_id = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "admin",
                        "user_id": self.approver_id,
                    }
                }
            },
            "pathParameters": {
                "id": self.change_id,
            },
            "body": json.dumps({
                "comment": "Aprobado por el comité CAB",
            }),
        }

        self.change_exists = True
        self.current_status = "submitted"
        self.fail_insert = False
        self.fail_update = False

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if (
                "FROM changes" in query
                and "FOR UPDATE" in query
            ):
                if not self.change_exists:
                    return []

                return [(
                    self.current_status,
                    self.requester_id,
                    "CHG-000001",
                    "normal",
                    "medium",
                )]

            if "INSERT INTO change_approvals" in query:
                if self.fail_insert:
                    raise RuntimeError(
                        "Error insertando aprobación CAB"
                    )
                return []

            if query.startswith("UPDATE changes"):
                if self.fail_update:
                    raise RuntimeError(
                        "Error actualizando el cambio"
                    )
                return []

            raise AssertionError(
                f"Consulta SQL inesperada: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.publish_patch = patch.object(
            changes,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()
        self.addCleanup(self.publish_patch.stop)

        self.detail_response = {
            "statusCode": 200,
            "body": json.dumps({
                "data": {
                    "id": self.change_id,
                    "status": "approved",
                    "cis": [],
                    "approvals": [
                        {
                            "decision": "approved",
                            "approver_id": self.approver_id,
                        }
                    ],
                }
            }),
        }

        self.detail_patch = patch.object(
            changes,
            "getChange",
            return_value=self.detail_response,
        )
        self.mock_detail = self.detail_patch.start()
        self.addCleanup(self.detail_patch.stop)

    def ejecutar(self):
        return changes.approveChange(
            self.event, None
        )

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_aprobar_cambio_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("INSERT INTO change_approvals")),
            1,
        )
        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            1,
        )

        self.mock_detail.assert_called_once()

    # TEST 2
    def test_solo_admin_puede_aprobar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "agent"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()
        self.mock_publish.assert_not_called()

    # TEST 3
    def test_customer_no_puede_aprobar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 4
    def test_solicitante_no_puede_autoaprobarse(self):
        self.requester_id = self.approver_id

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("INSERT INTO change_approvals")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 5
    def test_solo_estado_submitted(self):
        self.current_status = "draft"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)
        self.mock_publish.assert_not_called()

    # TEST 6
    def test_no_aprobar_cambio_approved(self):
        self.current_status = "approved"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

        self.assertEqual(
            len(self.consultas("INSERT INTO change_approvals")),
            0,
        )

    # TEST 7
    def test_no_aprobar_cambio_rejected(self):
        self.current_status = "rejected"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 8
    def test_no_aprobar_cambio_implemented(self):
        self.current_status = "implemented"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 9
    def test_cambio_no_existe(self):
        self.change_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.mock_publish.assert_not_called()

    # TEST 10
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = (
            "CHG-000001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 11
    def test_uuid_ausente(self):
        self.event["pathParameters"] = None

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_comentario_opcional(self):
        self.event["body"] = "{}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        insert = self.consultas(
            "INSERT INTO change_approvals"
        )[0]

        self.assertIsNone(
            insert.kwargs["comment"]
        )

    # TEST 14
    def test_comentario_mayor_a_2000(self):
        self.event["body"] = json.dumps({
            "comment": "A" * 2001,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 15
    def test_comentario_no_es_texto(self):
        self.event["body"] = json.dumps({
            "comment": 123,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_campos_no_permitidos(self):
        self.event["body"] = json.dumps({
            "comment": "Aprobado",
            "status": "approved",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17
    def test_aprobador_sale_del_token(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        insert = self.consultas(
            "INSERT INTO change_approvals"
        )[0]

        self.assertEqual(
            insert.kwargs["approver_id"],
            self.approver_id,
        )

    # TEST 18
    def test_decision_approved_en_sql(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        insert = self.consultas(
            "INSERT INTO change_approvals"
        )[0]

        self.assertIn(
            "'approved'",
            insert.args[0],
        )

    # TEST 19
    def test_actualizar_estado_a_approved(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        update = self.consultas(
            "UPDATE changes"
        )[0]

        self.assertIn(
            "status = 'approved'",
            update.args[0],
        )

    # TEST 20
    def test_publicar_change_approved(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_publish.assert_called_once()

        kwargs = self.mock_publish.call_args.kwargs

        self.assertEqual(
            kwargs["event_type"],
            "ChangeApproved",
        )
        self.assertEqual(
            kwargs["tenant_id"],
            "andina",
        )
        self.assertEqual(
            kwargs["source"],
            "ms-changes",
        )

    # TEST 21
    def test_evento_incluye_datos_correctos(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = self.mock_publish.call_args.kwargs["data"]

        self.assertEqual(
            data["changeId"],
            self.change_id,
        )
        self.assertEqual(
            data["status"],
            "approved",
        )
        self.assertEqual(
            data["approverId"],
            self.approver_id,
        )
        self.assertEqual(
            data["actorId"],
            self.approver_id,
        )

    # TEST 22
    def test_rollback_si_falla_insert(self):
        self.fail_insert = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 23
    def test_rollback_si_falla_update(self):
        self.fail_update = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 24
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 25
    def test_bloqueo_de_fila(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        select = self.consultas(
            "FROM changes"
        )[0]

        self.assertIn(
            "FOR UPDATE",
            select.args[0],
        )

    # TEST 26
    def test_evento_despues_del_commit(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        queries = [
            call.args[0].strip()
            for call in self.mock_conn.run.call_args_list
        ]

        self.assertEqual(queries[-1], "COMMIT")
        self.mock_publish.assert_called_once()

    # TEST 27
    def test_devolver_detalle_actualizado(self):
        response = self.ejecutar()

        self.assertEqual(
            response,
            self.detail_response,
        )

        self.mock_detail.assert_called_once_with(
            self.event,
            None,
        )

class TestRejectChange(unittest.TestCase):
    """Pruebas CH-07: POST /changes/{id}/reject."""

    def setUp(self):
        self.change_id = str(uuid.uuid4())
        self.approver_id = str(uuid.uuid4())
        self.requester_id = str(uuid.uuid4())

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "admin",
                        "user_id": self.approver_id,
                    }
                }
            },
            "pathParameters": {
                "id": self.change_id,
            },
            "body": json.dumps({
                "comment": "Falta el plan de pruebas",
            }),
        }

        self.change_exists = True
        self.current_status = "submitted"
        self.fail_insert = False
        self.fail_update = False

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if (
                "FROM changes" in query
                and "FOR UPDATE" in query
            ):
                if not self.change_exists:
                    return []

                return [(
                    self.current_status,
                    self.requester_id,
                    "CHG-000001",
                    "normal",
                    "medium",
                )]

            if "INSERT INTO change_approvals" in query:
                if self.fail_insert:
                    raise RuntimeError(
                        "Error insertando rechazo CAB"
                    )
                return []

            if query.startswith("UPDATE changes"):
                if self.fail_update:
                    raise RuntimeError(
                        "Error actualizando cambio"
                    )
                return []

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            changes,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.publish_patch = patch.object(
            changes,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()
        self.addCleanup(self.publish_patch.stop)

        self.detail_response = {
            "statusCode": 200,
            "body": json.dumps({
                "data": {
                    "id": self.change_id,
                    "status": "rejected",
                    "cis": [],
                    "approvals": [
                        {
                            "decision": "rejected",
                            "approver_id": self.approver_id,
                        }
                    ],
                }
            }),
        }

        self.detail_patch = patch.object(
            changes,
            "getChange",
            return_value=self.detail_response,
        )
        self.mock_detail = self.detail_patch.start()
        self.addCleanup(self.detail_patch.stop)

    def ejecutar(self):
        return changes.rejectChange(
            self.event, None
        )

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_rechazar_cambio_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(
            len(self.consultas("INSERT INTO change_approvals")),
            1,
        )
        self.assertEqual(
            len(self.consultas("UPDATE changes")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            1,
        )

        self.mock_detail.assert_called_once()

    # TEST 2
    def test_agent_no_puede_rechazar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "agent"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()
        self.mock_publish.assert_not_called()

    # TEST 3
    def test_customer_no_puede_rechazar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 4
    def test_no_rechazar_cambio_propio(self):
        self.requester_id = self.approver_id

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("INSERT INTO change_approvals")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 5
    def test_solo_rechazar_submitted(self):
        self.current_status = "draft"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)
        self.mock_publish.assert_not_called()

    # TEST 6
    def test_no_rechazar_approved(self):
        self.current_status = "approved"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 7
    def test_no_rechazar_rejected(self):
        self.current_status = "rejected"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 8
    def test_no_rechazar_scheduled(self):
        self.current_status = "scheduled"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 9
    def test_no_rechazar_implemented(self):
        self.current_status = "implemented"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 10
    def test_cambio_no_existe(self):
        self.change_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.mock_publish.assert_not_called()

    # TEST 11
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = (
            "CHG-000001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_uuid_ausente(self):
        self.event["pathParameters"] = None

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 14
    def test_comentario_obligatorio(self):
        self.event["body"] = "{}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 15
    def test_comentario_vacio(self):
        self.event["body"] = json.dumps({
            "comment": "   ",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_comentario_muy_corto(self):
        self.event["body"] = json.dumps({
            "comment": "No",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17
    def test_comentario_mayor_a_2000(self):
        self.event["body"] = json.dumps({
            "comment": "A" * 2001,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_comentario_no_es_texto(self):
        self.event["body"] = json.dumps({
            "comment": 123,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 19
    def test_campos_no_permitidos(self):
        self.event["body"] = json.dumps({
            "comment": "Rechazado",
            "status": "rejected",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 20
    def test_guardar_comentario_sin_espacios(self):
        self.event["body"] = json.dumps({
            "comment": "  Falta documentación  ",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        insert = self.consultas(
            "INSERT INTO change_approvals"
        )[0]

        self.assertEqual(
            insert.kwargs["comment"],
            "Falta documentación",
        )

    # TEST 21
    def test_rechazo_registra_aprobador_del_token(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        insert = self.consultas(
            "INSERT INTO change_approvals"
        )[0]

        self.assertEqual(
            insert.kwargs["approver_id"],
            self.approver_id,
        )

    # TEST 22
    def test_decision_rejected_en_sql(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        insert = self.consultas(
            "INSERT INTO change_approvals"
        )[0]

        self.assertIn(
            "'rejected'",
            insert.args[0],
        )

    # TEST 23
    def test_actualizar_estado_rejected(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        update = self.consultas(
            "UPDATE changes"
        )[0]

        self.assertIn(
            "status = 'rejected'",
            update.args[0],
        )

    # TEST 24
    def test_publicar_change_rejected(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.mock_publish.assert_called_once()

        kwargs = self.mock_publish.call_args.kwargs

        self.assertEqual(
            kwargs["event_type"],
            "ChangeRejected",
        )
        self.assertEqual(
            kwargs["tenant_id"],
            "andina",
        )
        self.assertEqual(
            kwargs["source"],
            "ms-changes",
        )

    # TEST 25
    def test_evento_incluye_datos_correctos(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = self.mock_publish.call_args.kwargs["data"]

        self.assertEqual(
            data["changeId"],
            self.change_id,
        )
        self.assertEqual(
            data["status"],
            "rejected",
        )
        self.assertEqual(
            data["approverId"],
            self.approver_id,
        )
        self.assertEqual(
            data["actorId"],
            self.approver_id,
        )
        self.assertEqual(
            data["comment"],
            "Falta el plan de pruebas",
        )

    # TEST 26
    def test_rollback_si_falla_insert(self):
        self.fail_insert = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 27
    def test_rollback_si_falla_update(self):
        self.fail_update = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")),
            1,
        )
        self.assertEqual(
            len(self.consultas("COMMIT")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 28
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 29
    def test_bloqueo_de_fila(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        select = self.consultas("FROM changes")[0]

        self.assertIn(
            "FOR UPDATE",
            select.args[0],
        )

    # TEST 30
    def test_evento_despues_del_commit(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        queries = [
            call.args[0].strip()
            for call in self.mock_conn.run.call_args_list
        ]

        self.assertEqual(queries[-1], "COMMIT")
        self.mock_publish.assert_called_once()

    # TEST 31
    def test_devolver_detalle_actualizado(self):
        response = self.ejecutar()

        self.assertEqual(
            response,
            self.detail_response,
        )

        self.mock_detail.assert_called_once_with(
            self.event,
            None,
        )





