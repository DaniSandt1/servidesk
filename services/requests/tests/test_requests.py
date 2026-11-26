"""Pruebas unitarias de ms-requests."""

import json
import sys
import types
import unittest
import uuid


from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


# =====================================================
# CONFIGURACIÓN DEL ENTORNO DE PRUEBAS
# =====================================================

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# Simular dependencias del AWS Layer común
if "common" not in sys.modules:
    common = types.ModuleType("common")
    common.__path__ = []
    sys.modules["common"] = common

if "common.log" not in sys.modules:  # log real del layer (solo imprime, sin AWS)
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "common.log",
        Path(__file__).resolve().parents[3] / "infra" / "layers" / "common" / "python" / "common" / "log.py",
    )
    _log = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_log)
    sys.modules["common.log"] = _log



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

# Simular SNS sin conectarse a AWS
if "common.events" not in sys.modules:
    events = types.ModuleType("common.events")
    events.publish = MagicMock()
    sys.modules["common.events"] = events

from handlers import requests

from handlers import requests


# =====================================================
# RQ-01: GET /catalog
# =====================================================

class TestListCatalog(unittest.TestCase):
    """Pruebas de listado del catálogo de servicios."""

    def setUp(self):
        self.item_id = str(uuid.uuid4())
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

        self.catalog_item = {
            "id": uuid.UUID(self.item_id),
            "category_id": 1,
            "category_name": "Accesos",
            "name": "Acceso VPN",
            "description": "Acceso remoto corporativo",
            "form_schema": {
                "fields": [
                    {
                        "name": "motivo",
                        "label": "Motivo",
                        "type": "textarea",
                        "required": True,
                    }
                ]
            },
            "needs_approval": True,
            "sla_hours": 24,
            "active": True,
            "created_at": datetime(
                2026, 11, 20, 9, 0
            ),
        }

        self.mock_conn = MagicMock()

        self.mock_conn.columns = [
            {"name": name}
            for name in self.catalog_item
        ]

        self.mock_conn.run.return_value = [
            tuple(self.catalog_item.values())
        ]

        self.db_patch = patch.object(
            requests,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return requests.listCatalog(
            self.event, None
        )

    def consulta_sql(self):
        return self.mock_conn.run.call_args

    def cambiar_query(self, **params):
        self.event["queryStringParameters"] = params

    # TEST 1
    def test_listar_catalogo_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(
            body["data"][0]["name"],
            "Acceso VPN",
        )

    # TEST 2
    def test_admin_puede_consultar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "admin"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_agent_puede_consultar(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 4
    def test_customer_puede_consultar(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "customer"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 5
    def test_rol_no_permitido(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = "guest"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 7
    def test_filtrar_por_categoria(self):
        self.cambiar_query(category_id="1")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertIn(
            "ci.category_id = :category_id",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["category_id"],
            1,
        )

    # TEST 8
    def test_categoria_invalida(self):
        self.cambiar_query(category_id="abc")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 9
    def test_categoria_cero(self):
        self.cambiar_query(category_id="0")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 10
    def test_categoria_negativa(self):
        self.cambiar_query(category_id="-5")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 11
    def test_busqueda_por_nombre(self):
        self.cambiar_query(search="VPN")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertIn(
            "ci.name ILIKE :search",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["search"],
            "%VPN%",
        )

    # TEST 12
    def test_busqueda_muy_corta(self):
        self.cambiar_query(search="A")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_busqueda_muy_larga(self):
        self.cambiar_query(search="A" * 101)

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 14
    def test_categoria_y_busqueda_juntas(self):
        self.cambiar_query(
            category_id="1",
            search="VPN",
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertEqual(
            query.kwargs["category_id"],
            1,
        )

        self.assertEqual(
            query.kwargs["search"],
            "%VPN%",
        )

    # TEST 15
    def test_catalogo_vacio(self):
        self.mock_conn.run.return_value = []

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["data"], [])

    # TEST 16
    def test_incluir_nombre_categoria(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"][0]

        self.assertEqual(
            data["category_name"],
            "Accesos",
        )

        query = self.consulta_sql()

        self.assertIn(
            "INNER JOIN catalog_categories",
            query.args[0],
        )

    # TEST 17
    def test_solo_servicios_activos(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertIn(
            "ci.active = TRUE",
            query.args[0],
        )

    # TEST 18
    def test_ordenamiento_por_nombre(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertIn(
            "ORDER BY ci.name ASC",
            query.args[0],
        )

    # TEST 19
    def test_serializar_uuid(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"][0]

        self.assertEqual(
            data["id"],
            self.item_id,
        )

    # TEST 20
    def test_serializar_fecha(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"][0]

        self.assertEqual(
            data["created_at"],
            "2026-11-20T09:00:00Z",
        )

    # TEST 21
    def test_conservar_form_schema(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"][0]

        self.assertEqual(
            data["form_schema"]["fields"][0]["name"],
            "motivo",
        )

        self.assertTrue(
            data["form_schema"]["fields"][0]["required"]
        )

    # TEST 22
    def test_incluir_needs_approval_y_sla(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"][0]

        self.assertTrue(data["needs_approval"])
        self.assertEqual(data["sla_hours"], 24)

    # TEST 23
    def test_consulta_sin_paginacion(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertNotIn(
            "LIMIT",
            query.args[0].upper(),
        )

        self.assertNotIn(
            "OFFSET",
            query.args[0].upper(),
        )

        body = json.loads(response["body"])

        self.assertNotIn("meta", body)

    # TEST 24
    def test_no_modifica_la_base_de_datos(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consulta_sql()

        self.assertTrue(
            query.args[0].strip().upper().startswith("SELECT")
        )

# =====================================================
# RQ-02: GET /requests
# =====================================================

class TestListRequests(unittest.TestCase):
    """Pruebas unitarias de RQ-02."""

    def setUp(self):
        self.request_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.catalog_item_id = str(uuid.uuid4())
        self.assignee_id = str(uuid.uuid4())

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

        self.request_data = {
            "id": uuid.UUID(self.request_id),
            "key": "REQ-000001",
            "catalog_item_id": uuid.UUID(
                self.catalog_item_id
            ),
            "catalog_item_name": "Acceso VPN",
            "form_data": {
                "motivo": "Trabajo remoto"
            },
            "status": "submitted",
            "requester_id": uuid.UUID(self.user_id),
            "assignee_id": None,
            "created_at": datetime(
                2026, 11, 20, 9, 0
            ),
            "fulfilled_at": None,
        }

        self.total = 1
        self.empty_results = False

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            if "SELECT COUNT(*)" in sql:
                return [(self.total,)]

            if "FROM service_requests AS sr" in sql:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in self.request_data
                ]

                if self.empty_results:
                    return []

                return [
                    tuple(self.request_data.values())
                ]

            raise AssertionError(
                f"Consulta inesperada: {sql}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            requests,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return requests.listRequests(
            self.event, None
        )

    def cambiar_query(self, **params):
        self.event["queryStringParameters"] = params

    def cambiar_rol(self, role):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = role

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_listar_solicitudes_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(
            body["data"][0]["key"],
            "REQ-000001",
        )

    # TEST 2
    def test_admin_puede_listar(self):
        self.cambiar_rol("admin")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_agent_puede_listar(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 4
    def test_customer_puede_listar(self):
        self.cambiar_rol("customer")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        count_query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertEqual(
            count_query.kwargs["requester_id"],
            self.user_id,
        )

    # TEST 5
    def test_rol_no_autorizado(self):
        self.cambiar_rol("guest")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_customer_no_puede_ver_solicitudes_ajenas(self):
        self.cambiar_rol("customer")

        self.cambiar_query(
            requester_id=str(uuid.uuid4())
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_customer_puede_usar_me(self):
        self.cambiar_rol("customer")
        self.cambiar_query(requester_id="me")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertEqual(
            query.kwargs["requester_id"],
            self.user_id,
        )

    # TEST 8
    def test_paginacion_por_defecto(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        meta = json.loads(
            response["body"]
        )["meta"]

        self.assertEqual(meta["page"], 1)
        self.assertEqual(meta["limit"], 20)
        self.assertEqual(meta["total"], 1)
        self.assertEqual(meta["total_pages"], 1)

    # TEST 9
    def test_paginacion_personalizada(self):
        self.cambiar_query(
            page="3",
            limit="10",
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "INNER JOIN catalog_items"
        )[0]

        self.assertEqual(
            query.kwargs["limit"],
            10,
        )
        self.assertEqual(
            query.kwargs["offset"],
            20,
        )

    # TEST 10
    def test_pagina_cero_invalida(self):
        self.cambiar_query(page="0")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 11
    def test_pagina_no_numerica(self):
        self.cambiar_query(page="abc")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_limit_mayor_100(self):
        self.cambiar_query(limit="101")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_limit_cero(self):
        self.cambiar_query(limit="0")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 14
    def test_filtrar_por_estado(self):
        self.cambiar_query(
            status="submitted,approved"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertIn(
            "sr.status IN (:status_0, :status_1)",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["status_0"],
            "submitted",
        )

    # TEST 15
    def test_estado_invalido(self):
        self.cambiar_query(
            status="inventado"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_filtrar_por_catalog_item(self):
        self.cambiar_query(
            catalog_item_id=self.catalog_item_id
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertEqual(
            query.kwargs["catalog_item_id"],
            self.catalog_item_id,
        )

    # TEST 17
    def test_catalog_item_uuid_invalido(self):
        self.cambiar_query(
            catalog_item_id="CAT-001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_filtrar_requester_me(self):
        self.cambiar_query(
            requester_id="me"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertEqual(
            query.kwargs["requester_id"],
            self.user_id,
        )

    # TEST 19
    def test_requester_uuid_invalido(self):
        self.cambiar_query(
            requester_id="usuario123"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 20
    def test_filtrar_assignee_me(self):
        self.cambiar_query(
            assignee_id="me"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertEqual(
            query.kwargs["assignee_id"],
            self.user_id,
        )

    # TEST 21
    def test_filtrar_sin_responsable(self):
        self.cambiar_query(
            assignee_id="none"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertIn(
            "sr.assignee_id IS NULL",
            query.args[0],
        )

    # TEST 22
    def test_assignee_uuid_invalido(self):
        self.cambiar_query(
            assignee_id="AGENTE-001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 23
    def test_busqueda_por_clave(self):
        self.cambiar_query(
            search="REQ-000001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "SELECT COUNT(*)"
        )[0]

        self.assertIn(
            "sr.key ILIKE :search",
            query.args[0],
        )

        self.assertEqual(
            query.kwargs["search"],
            "%REQ-000001%",
        )

    # TEST 24
    def test_busqueda_muy_corta(self):
        self.cambiar_query(search="R")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 25
    def test_ordenamiento_personalizado(self):
        self.cambiar_query(
            sort_by="status",
            sort_order="asc",
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        query = self.consultas(
            "INNER JOIN catalog_items"
        )[0]

        self.assertIn(
            "sr.status ASC",
            query.args[0],
        )

    # TEST 26
    def test_sort_by_invalido(self):
        self.cambiar_query(
            sort_by="DROP TABLE"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 27
    def test_sort_order_invalido(self):
        self.cambiar_query(
            sort_order="random"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 28
    def test_sin_solicitudes(self):
        self.empty_results = True
        self.total = 0

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        body = json.loads(response["body"])

        self.assertEqual(body["data"], [])
        self.assertEqual(
            body["meta"]["total"],
            0,
        )
        self.assertEqual(
            body["meta"]["total_pages"],
            0,
        )

    # TEST 29
    def test_serializar_uuid_y_fecha(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(
            response["body"]
        )["data"][0]

        self.assertEqual(
            data["id"],
            self.request_id,
        )

        self.assertEqual(
            data["created_at"],
            "2026-11-20T09:00:00Z",
        )

    # TEST 30
    def test_incluir_nombre_del_servicio(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(
            response["body"]
        )["data"][0]

        self.assertEqual(
            data["catalog_item_name"],
            "Acceso VPN",
        )

    # TEST 31
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 32
    def test_total_pages_calculado(self):
        self.total = 45

        self.cambiar_query(limit="20")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        meta = json.loads(
            response["body"]
        )["meta"]

        self.assertEqual(meta["total"], 45)
        self.assertEqual(meta["total_pages"], 3)

# =====================================================
# RQ-03: POST /requests
# =====================================================

class TestCreateRequest(unittest.TestCase):
    """Pruebas unitarias de RQ-03."""

    def setUp(self):
        self.request_id = str(uuid.uuid4())
        self.catalog_item_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())

        self.form_schema = {
            "fields": [
                {
                    "name": "motivo",
                    "label": "Motivo",
                    "type": "textarea",
                    "required": True,
                },
                {
                    "name": "perfil",
                    "label": "Perfil",
                    "type": "select",
                    "required": True,
                    "options": [
                        "Básico",
                        "Administrador",
                    ],
                },
                {
                    "name": "fecha_fin",
                    "label": "Válido hasta",
                    "type": "date",
                    "required": False,
                },
            ]
        }

        self.form_data = {
            "motivo": "Trabajo remoto",
            "perfil": "Básico",
        }

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "customer",
                        "user_id": self.user_id,
                    }
                }
            },
            "body": json.dumps({
                "catalog_item_id": self.catalog_item_id,
                "form_data": self.form_data,
            }),
        }

        self.catalog_exists = True
        self.needs_approval = True
        self.fail_insert = False
        self.next_number = 1

        self.inserted_params = None

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if "FROM catalog_items" in query:
                if not self.catalog_exists:
                    return []

                return [(
                    "Acceso VPN",
                    self.form_schema,
                    self.needs_approval,
                )]

            if "pg_advisory_xact_lock" in query:
                return [(None,)]

            if "MAX(SUBSTRING" in query:
                return [(self.next_number - 1,)]

            if "INSERT INTO service_requests" in query:
                if self.fail_insert:
                    raise RuntimeError(
                        "Error simulado de PostgreSQL"
                    )

                self.inserted_params = params

                result = {
                    "id": uuid.UUID(self.request_id),
                    "key": params["key"],
                    "catalog_item_id": uuid.UUID(
                        params["catalog_item_id"]
                    ),
                    "form_data": json.loads(
                        params["form_data"]
                    ),
                    "status": params["status"],
                    "requester_id": uuid.UUID(
                        params["requester_id"]
                    ),
                    "assignee_id": None,
                    "created_at": datetime(
                        2026, 11, 20, 9, 0
                    ),
                    "fulfilled_at": None,
                }

                self.mock_conn.columns = [
                    {"name": name}
                    for name in result
                ]

                return [tuple(result.values())]

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            requests,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.publish_patch = patch.object(
            requests,
            "publish",
        )
        self.mock_publish = self.publish_patch.start()
        self.addCleanup(self.publish_patch.stop)

    def ejecutar(self):
        return requests.createRequest(
            self.event, None
        )

    def cambiar_body(self, **updates):
        body = json.loads(self.event["body"])
        body.update(updates)
        self.event["body"] = json.dumps(body)

    def cambiar_form(self, **updates):
        data = self.form_data.copy()
        data.update(updates)
        self.cambiar_body(form_data=data)

    def cambiar_rol(self, role):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = role

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_crear_solicitud_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        data = json.loads(response["body"])["data"]

        self.assertEqual(
            data["key"],
            "REQ-000001",
        )
        self.assertEqual(
            data["status"],
            "pending_approval",
        )
        self.assertEqual(
            data["catalog_item_name"],
            "Acceso VPN",
        )
        self.assertEqual(data["approvals"], [])

    # TEST 2
    def test_admin_puede_crear(self):
        self.cambiar_rol("admin")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 3
    def test_agent_puede_crear(self):
        self.cambiar_rol("agent")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 4
    def test_customer_puede_crear(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 5
    def test_rol_no_permitido(self):
        self.cambiar_rol("guest")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_catalog_item_uuid_invalido(self):
        self.cambiar_body(
            catalog_item_id="CAT-001"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_catalog_item_no_existe(self):
        self.catalog_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)
        self.mock_publish.assert_not_called()

    # TEST 8
    def test_form_data_obligatorio(self):
        self.cambiar_body(form_data={})

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(
            len(self.consultas("INSERT INTO service_requests")),
            0,
        )

    # TEST 9
    def test_form_data_debe_ser_objeto(self):
        self.cambiar_body(
            form_data=["motivo", "VPN"]
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 10
    def test_campo_obligatorio_faltante(self):
        self.cambiar_body(
            form_data={
                "perfil": "Básico",
            }
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 11
    def test_campo_extra_no_permitido(self):
        self.cambiar_form(
            campo_inventado="valor"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 12
    def test_select_opcion_invalida(self):
        self.cambiar_form(
            perfil="Superusuario"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 13
    def test_select_opcion_valida(self):
        self.cambiar_form(
            perfil="Administrador"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 14
    def test_tipo_texto_invalido(self):
        self.cambiar_form(
            motivo=123
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 15
    def test_fecha_invalida(self):
        self.cambiar_form(
            fecha_fin="2026-99-99"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 16
    def test_fecha_valida(self):
        self.cambiar_form(
            fecha_fin="2026-12-31"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 17
    def test_formulario_supera_8kb(self):
        self.cambiar_form(
            motivo="A" * 9000
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_campos_extra_en_body(self):
        self.cambiar_body(
            status="approved"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 19
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 20
    def test_solicitud_sin_aprobacion(self):
        self.needs_approval = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.assertEqual(
            self.inserted_params["status"],
            "submitted",
        )

    # TEST 21
    def test_requester_sale_del_token(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.assertEqual(
            self.inserted_params["requester_id"],
            self.user_id,
        )

    # TEST 22
    def test_clave_correlativa(self):
        self.next_number = 25

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.assertEqual(
            self.inserted_params["key"],
            "REQ-000025",
        )

    # TEST 23
    def test_se_guarda_form_data_json(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        stored = json.loads(
            self.inserted_params["form_data"]
        )

        self.assertEqual(
            stored["motivo"],
            "Trabajo remoto",
        )

        self.assertEqual(
            stored["perfil"],
            "Básico",
        )

    # TEST 24
    def test_publicar_request_submitted(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.mock_publish.assert_called_once()

        kwargs = self.mock_publish.call_args.kwargs

        self.assertEqual(
            kwargs["event_type"],
            "RequestSubmitted",
        )

        self.assertEqual(
            kwargs["tenant_id"],
            "andina",
        )

        self.assertEqual(
            kwargs["data"]["requestId"],
            self.request_id,
        )

    # TEST 25
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

    # TEST 26
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

    # TEST 27
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 28
    def test_validar_formulario_boolean(self):
        self.form_schema = {
            "fields": [
                {
                    "name": "acepta",
                    "type": "boolean",
                    "required": True,
                }
            ]
        }

        self.cambiar_body(
            form_data={"acepta": True}
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 29
    def test_rechazar_boolean_invalido(self):
        self.form_schema = {
            "fields": [
                {
                    "name": "acepta",
                    "type": "boolean",
                    "required": True,
                }
            ]
        }

        self.cambiar_body(
            form_data={"acepta": "sí"}
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 30
    def test_validar_campo_number(self):
        self.form_schema = {
            "fields": [
                {
                    "name": "cantidad",
                    "type": "number",
                    "required": True,
                }
            ]
        }

        self.cambiar_body(
            form_data={"cantidad": 3}
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 201)

    # TEST 31
    def test_rechazar_boolean_como_number(self):
        self.form_schema = {
            "fields": [
                {
                    "name": "cantidad",
                    "type": "number",
                    "required": True,
                }
            ]
        }

        self.cambiar_body(
            form_data={"cantidad": True}
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 32
    def test_form_schema_invalido(self):
        self.form_schema = {
            "fields": "incorrecto"
        }

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 500)

        self.assertEqual(
            len(self.consultas("INSERT INTO service_requests")),
            0,
        )

# =====================================================
# RQ-04: GET /requests/{id}
# =====================================================

class TestGetRequest(unittest.TestCase):
    """Pruebas unitarias de consulta de solicitudes."""

    def setUp(self):
        self.request_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.catalog_item_id = str(uuid.uuid4())
        self.approver_id = str(uuid.uuid4())
        self.approval_id = str(uuid.uuid4())

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
                "id": self.request_id,
            },
        }

        self.request_data = {
            "id": uuid.UUID(self.request_id),
            "key": "REQ-000001",
            "catalog_item_id": uuid.UUID(
                self.catalog_item_id
            ),
            "catalog_item_name": "Acceso VPN",
            "form_data": {
                "motivo": "Trabajo remoto"
            },
            "status": "approved",
            "requester_id": uuid.UUID(self.user_id),
            "assignee_id": None,
            "created_at": datetime(
                2026, 11, 20, 9, 0
            ),
            "fulfilled_at": None,
        }

        self.approval_data = {
            "id": uuid.UUID(self.approval_id),
            "request_id": uuid.UUID(self.request_id),
            "approver_id": uuid.UUID(self.approver_id),
            "decision": "approved",
            "decided_at": datetime(
                2026, 11, 20, 10, 0
            ),
        }

        self.request_exists = True
        self.has_approvals = True

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            if "FROM service_requests AS sr" in sql:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in self.request_data
                ]

                if not self.request_exists:
                    return []

                return [
                    tuple(self.request_data.values())
                ]

            if "FROM request_approvals" in sql:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in self.approval_data
                ]

                if not self.has_approvals:
                    return []

                return [
                    tuple(self.approval_data.values())
                ]

            raise AssertionError(
                f"Consulta inesperada: {sql}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            requests,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return requests.getRequest(
            self.event, None
        )

    def cambiar_rol(self, role):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = role

    def consultar_aprobaciones(self):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if "FROM request_approvals" in call.args[0]
        ]

    # TEST 1
    def test_consultar_solicitud_exitosamente(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["id"], self.request_id)
        self.assertEqual(data["key"], "REQ-000001")

    # TEST 2
    def test_admin_puede_consultar(self):
        self.cambiar_rol("admin")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_agent_puede_consultar(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 4
    def test_customer_puede_consultar_su_solicitud(self):
        self.cambiar_rol("customer")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 5
    def test_customer_no_puede_consultar_ajena(self):
        self.cambiar_rol("customer")

        self.request_data["requester_id"] = (
            uuid.uuid4()
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)

        # No debe consultar aprobaciones ajenas
        self.assertEqual(
            len(self.consultar_aprobaciones()),
            0,
        )

    # TEST 6
    def test_rol_no_autorizado(self):
        self.cambiar_rol("guest")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = "REQ-1"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 8
    def test_uuid_ausente(self):
        self.event["pathParameters"] = {}

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 9
    def test_path_parameters_ausente(self):
        self.event.pop("pathParameters")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 10
    def test_solicitud_no_existe(self):
        self.request_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)

        self.assertEqual(
            len(self.consultar_aprobaciones()),
            0,
        )

    # TEST 11
    def test_incluir_nombre_del_catalogo(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(
            data["catalog_item_name"],
            "Acceso VPN",
        )

    # TEST 12
    def test_incluir_aprobaciones(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(len(data["approvals"]), 1)

        self.assertEqual(
            data["approvals"][0]["decision"],
            "approved",
        )

        self.assertEqual(
            data["approvals"][0]["approver_id"],
            self.approver_id,
        )

    # TEST 13
    def test_solicitud_sin_aprobaciones(self):
        self.has_approvals = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["approvals"], [])

    # TEST 14
    def test_serializar_uuid(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["id"], self.request_id)

        self.assertEqual(
            data["approvals"][0]["id"],
            self.approval_id,
        )

    # TEST 15
    def test_serializar_fechas(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(
            data["created_at"],
            "2026-11-20T09:00:00Z",
        )

        self.assertEqual(
            data["approvals"][0]["decided_at"],
            "2026-11-20T10:00:00Z",
        )

    # TEST 16
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 17
    def test_consulta_sql_usa_parametros(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        first_call = (
            self.mock_conn.run.call_args_list[0]
        )

        self.assertIn(
            "WHERE sr.id = :request_id",
            first_call.args[0],
        )

        self.assertEqual(
            first_call.kwargs["request_id"],
            self.request_id,
        )

    # TEST 18
    def test_aprobaciones_ordenadas(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        approval_call = (
            self.consultar_aprobaciones()[0]
        )

        self.assertIn(
            "ORDER BY decided_at ASC",
            approval_call.args[0],
        )

    # TEST 19
    def test_no_modifica_base_de_datos(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        for call in self.mock_conn.run.call_args_list:
            sql = call.args[0].strip().upper()

            self.assertTrue(
                sql.startswith("SELECT")
            )

    # TEST 20
    def test_customer_uuid_token_invalido(self):
        self.cambiar_rol("customer")

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["user_id"] = "usuario-invalido"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 500)

        self.assertEqual(
            len(self.consultar_aprobaciones()),
            0,
        )

# =====================================================
# RQ-05: PATCH /requests/{id}
# =====================================================

class TestUpdateRequest(unittest.TestCase):
    """Pruebas unitarias de actualización de solicitudes."""

    def setUp(self):
        self.request_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.assignee_id = str(uuid.uuid4())
        self.catalog_item_id = str(uuid.uuid4())

        self.form_schema = {
            "fields": [
                {
                    "name": "motivo",
                    "type": "textarea",
                    "required": True,
                },
                {
                    "name": "perfil",
                    "type": "select",
                    "required": True,
                    "options": ["Básico", "Administrador"],
                },
            ]
        }

        self.form_data = {
            "motivo": "Trabajo remoto",
            "perfil": "Básico",
        }

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
                "id": self.request_id,
            },
            "body": json.dumps({
                "assignee_id": self.assignee_id,
            }),
        }

        self.request_exists = True
        self.requester_id = self.user_id
        self.status = "submitted"
        self.fail_update = False
        self.updated_assignee = None
        self.updated_form = self.form_data.copy()

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if "FOR UPDATE OF sr" in query:
                if not self.request_exists:
                    return []

                return [(
                    uuid.UUID(self.requester_id),
                    self.status,
                    self.form_schema,
                )]

            if query.startswith("UPDATE service_requests"):
                if self.fail_update:
                    raise RuntimeError("Error simulado de BD")

                if "assignee_id" in params:
                    self.updated_assignee = params["assignee_id"]

                if "form_data" in params:
                    self.updated_form = json.loads(
                        params["form_data"]
                    )

                return []

            if (
                "FROM service_requests AS sr" in query
                and "FOR UPDATE OF sr" not in query
            ):
                result = {
                    "id": uuid.UUID(self.request_id),
                    "key": "REQ-000001",
                    "catalog_item_id": uuid.UUID(
                        self.catalog_item_id
                    ),
                    "catalog_item_name": "Acceso VPN",
                    "form_data": self.updated_form,
                    "status": self.status,
                    "requester_id": uuid.UUID(
                        self.requester_id
                    ),
                    "assignee_id": (
                        uuid.UUID(self.updated_assignee)
                        if self.updated_assignee
                        else None
                    ),
                    "created_at": datetime(
                        2026, 11, 20, 9, 0
                    ),
                    "fulfilled_at": None,
                }

                self.mock_conn.columns = [
                    {"name": name}
                    for name in result
                ]

                return [tuple(result.values())]

            if "FROM request_approvals" in query:
                self.mock_conn.columns = [
                    {"name": name}
                    for name in (
                        "id",
                        "request_id",
                        "approver_id",
                        "decision",
                        "decided_at",
                    )
                ]
                return []

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            requests,
            "tenant_conn",
            return_value=self.mock_conn,
        )

        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def ejecutar(self):
        return requests.updateRequest(
            self.event, None
        )

    def cambiar_rol(self, role):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = role

    def cambiar_body(self, body):
        self.event["body"] = json.dumps(body)

    def usar_customer(self):
        self.cambiar_rol("customer")
        self.cambiar_body({
            "form_data": self.form_data.copy(),
        })

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_agent_asigna_responsable(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.updated_assignee,
            self.assignee_id,
        )

    # TEST 2
    def test_admin_asigna_responsable(self):
        self.cambiar_rol("admin")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 3
    def test_quitar_responsable(self):
        self.cambiar_body({"assignee_id": None})

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertIsNone(data["assignee_id"])

    # TEST 4
    def test_customer_actualiza_formulario(self):
        self.usar_customer()

        nuevo_form = {
            "motivo": "Nuevo motivo",
            "perfil": "Administrador",
        }
        self.cambiar_body({"form_data": nuevo_form})

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.updated_form, nuevo_form)

    # TEST 5
    def test_customer_puede_editar_pending_approval(self):
        self.usar_customer()
        self.status = "pending_approval"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 6
    def test_customer_no_edita_solicitud_ajena(self):
        self.usar_customer()
        self.requester_id = str(uuid.uuid4())

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(len(self.consultas("UPDATE service_requests")), 0)

    # TEST 7
    def test_customer_no_edita_approved(self):
        self.usar_customer()
        self.status = "approved"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(len(self.consultas("UPDATE service_requests")), 0)

    # TEST 8
    def test_customer_no_edita_fulfilled(self):
        self.usar_customer()
        self.status = "fulfilled"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 9
    def test_customer_no_puede_asignar(self):
        self.usar_customer()
        self.cambiar_body({
            "assignee_id": self.assignee_id,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 10
    def test_agent_no_modifica_form_data(self):
        self.cambiar_body({
            "form_data": self.form_data,
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 11
    def test_rol_no_autorizado(self):
        self.cambiar_rol("guest")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 12
    def test_uuid_solicitud_invalido(self):
        self.event["pathParameters"]["id"] = "REQ-001"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 13
    def test_solicitud_inexistente(self):
        self.request_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(len(self.consultas("UPDATE service_requests")), 0)

    # TEST 14
    def test_body_vacio(self):
        self.cambiar_body({})

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 15
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 16
    def test_assignee_uuid_invalido(self):
        self.cambiar_body({
            "assignee_id": "AGENTE-001"
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17
    def test_rechazar_campo_extra(self):
        self.cambiar_body({
            "assignee_id": self.assignee_id,
            "status": "approved",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_form_data_no_es_objeto(self):
        self.usar_customer()
        self.cambiar_body({
            "form_data": ["motivo"]
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 19
    def test_form_data_muy_grande(self):
        self.usar_customer()
        self.cambiar_body({
            "form_data": {
                "motivo": "X" * 9000,
                "perfil": "Básico",
            }
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 20
    def test_campo_obligatorio_faltante(self):
        self.usar_customer()
        self.cambiar_body({
            "form_data": {"perfil": "Básico"}
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(len(self.consultas("UPDATE service_requests")), 0)

    # TEST 21
    def test_select_invalido(self):
        self.usar_customer()
        self.cambiar_body({
            "form_data": {
                "motivo": "Acceso",
                "perfil": "Inexistente",
            }
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)

    # TEST 22
    def test_incluye_detalle_y_aprobaciones(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["key"], "REQ-000001")
        self.assertEqual(
            data["catalog_item_name"],
            "Acceso VPN",
        )
        self.assertEqual(data["approvals"], [])

    # TEST 23
    def test_rollback_si_falla_update(self):
        self.fail_update = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(len(self.consultas("ROLLBACK")), 1)
        self.assertEqual(len(self.consultas("COMMIT")), 0)

    # TEST 24
    def test_commit_si_actualiza(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(len(self.consultas("BEGIN")), 1)
        self.assertEqual(len(self.consultas("COMMIT")), 1)
        self.assertEqual(len(self.consultas("ROLLBACK")), 0)

    # TEST 25
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 26
    def test_customer_uuid_token_invalido(self):
        self.usar_customer()

        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["user_id"] = "usuario-invalido"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 500)
        self.mock_db.assert_not_called()

# =====================================================
# RQ-06: PUT /requests/{id}/status
# =====================================================

class TestChangeRequestStatus(unittest.TestCase):
    """Pruebas de cambios de estado y aprobaciones."""

    def setUp(self):
        self.request_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.catalog_id = str(uuid.uuid4())
        self.approval_id = str(uuid.uuid4())

        self.current_status = "pending_approval"
        self.new_status = "approved"
        self.request_exists = True
        self.fail_update = False
        self.fail_approval = False
        self.approvals = []
        self.fulfilled_at = None

        self.event = {
            "requestContext": {
                "authorizer": {
                    "lambda": {
                        "tenant_id": "andina",
                        "schema": "tenant_andina",
                        "role": "admin",
                        "user_id": self.user_id,
                    }
                }
            },
            "pathParameters": {
                "id": self.request_id,
            },
            "body": json.dumps({
                "status": self.new_status,
            }),
        }

        self.mock_conn = MagicMock()

        def fake_run(sql, **params):
            query = sql.strip()

            if query in ("BEGIN", "COMMIT", "ROLLBACK"):
                return []

            if (
                "FROM service_requests" in query
                and "FOR UPDATE" in query
            ):
                if not self.request_exists:
                    return []
                return [(self.current_status,)]

            if query.startswith("UPDATE service_requests"):
                if self.fail_update:
                    raise RuntimeError("Error SQL simulado")

                self.current_status = params["status"]

                if self.current_status == "fulfilled":
                    self.fulfilled_at = datetime(
                        2026, 11, 20, 12, 0
                    )
                return []

            if query.startswith("INSERT INTO request_approvals"):
                if self.fail_approval:
                    raise RuntimeError("Error de aprobación")

                self.approvals.append({
                    "id": uuid.UUID(self.approval_id),
                    "request_id": uuid.UUID(self.request_id),
                    "approver_id": uuid.UUID(
                        params["approver_id"]
                    ),
                    "decision": params["decision"],
                    "decided_at": datetime(
                        2026, 11, 20, 10, 0
                    ),
                })
                return []

            if "FROM service_requests AS sr" in query:
                result = {
                    "id": uuid.UUID(self.request_id),
                    "key": "REQ-000001",
                    "catalog_item_id": uuid.UUID(
                        self.catalog_id
                    ),
                    "catalog_item_name": "Acceso VPN",
                    "form_data": {"motivo": "Trabajo remoto"},
                    "status": self.current_status,
                    "requester_id": uuid.UUID(self.user_id),
                    "assignee_id": None,
                    "created_at": datetime(
                        2026, 11, 20, 9, 0
                    ),
                    "fulfilled_at": self.fulfilled_at,
                }

                self.mock_conn.columns = [
                    {"name": name}
                    for name in result
                ]
                return [tuple(result.values())]

            if "FROM request_approvals" in query:
                names = [
                    "id",
                    "request_id",
                    "approver_id",
                    "decision",
                    "decided_at",
                ]

                self.mock_conn.columns = [
                    {"name": name}
                    for name in names
                ]

                return [
                    tuple(item[name] for name in names)
                    for item in self.approvals
                ]

            raise AssertionError(
                f"SQL inesperado: {query}"
            )

        self.mock_conn.run.side_effect = fake_run

        self.db_patch = patch.object(
            requests,
            "tenant_conn",
            return_value=self.mock_conn,
        )
        self.mock_db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.publish_patch = patch.object(
            requests, "publish"
        )
        self.mock_publish = self.publish_patch.start()
        self.addCleanup(self.publish_patch.stop)

    def ejecutar(self):
        return requests.changeRequestStatus(
            self.event, None
        )

    def cambiar_rol(self, role):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["role"] = role

    def cambiar_estado(self, actual, nuevo):
        self.current_status = actual
        self.event["body"] = json.dumps({
            "status": nuevo
        })

    def consultas(self, fragment):
        return [
            call
            for call in self.mock_conn.run.call_args_list
            if fragment in call.args[0]
        ]

    # TEST 1
    def test_admin_aprueba_solicitud(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]
        self.assertEqual(data["status"], "approved")

    # TEST 2
    def test_admin_rechaza_solicitud(self):
        self.cambiar_estado(
            "pending_approval", "rejected"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.current_status, "rejected"
        )

    # TEST 3
    def test_agent_no_puede_aprobar(self):
        self.cambiar_rol("agent")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(
            len(self.consultas("UPDATE service_requests")),
            0,
        )

    # TEST 4
    def test_agent_no_puede_rechazar(self):
        self.cambiar_rol("agent")
        self.cambiar_estado(
            "pending_approval", "rejected"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)

    # TEST 5
    def test_customer_no_cambia_estados(self):
        self.cambiar_rol("customer")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 6
    def test_guest_no_autorizado(self):
        self.cambiar_rol("guest")

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 403)
        self.mock_db.assert_not_called()

    # TEST 7
    def test_agent_inicia_atencion_submitted(self):
        self.cambiar_rol("agent")
        self.cambiar_estado(
            "submitted", "in_fulfillment"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.current_status, "in_fulfillment"
        )

    # TEST 8
    def test_agent_inicia_atencion_approved(self):
        self.cambiar_rol("agent")
        self.cambiar_estado(
            "approved", "in_fulfillment"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 9
    def test_admin_inicia_atencion(self):
        self.cambiar_estado(
            "approved", "in_fulfillment"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

    # TEST 10
    def test_agent_completa_solicitud(self):
        self.cambiar_rol("agent")
        self.cambiar_estado(
            "in_fulfillment", "fulfilled"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(data["status"], "fulfilled")
        self.assertIsNotNone(data["fulfilled_at"])

    # TEST 11
    def test_no_aprobar_desde_submitted(self):
        self.cambiar_estado(
            "submitted", "approved"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 12
    def test_no_completar_sin_iniciar(self):
        self.cambiar_estado(
            "approved", "fulfilled"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 13
    def test_no_modificar_fulfilled(self):
        self.cambiar_estado(
            "fulfilled", "in_fulfillment"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 14
    def test_no_modificar_rejected(self):
        self.cambiar_estado(
            "rejected", "approved"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 15
    def test_no_repetir_mismo_estado(self):
        self.cambiar_estado(
            "approved", "approved"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 409)

    # TEST 16
    def test_estado_invalido(self):
        self.cambiar_estado(
            "submitted", "inventado"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 17
    def test_body_con_comment_rechazado(self):
        self.event["body"] = json.dumps({
            "status": "approved",
            "comment": "Conforme",
        })

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 18
    def test_uuid_invalido(self):
        self.event["pathParameters"]["id"] = "REQ-1"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 19
    def test_solicitud_no_existe(self):
        self.request_exists = False

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(
            len(self.consultas("UPDATE service_requests")),
            0,
        )
        self.mock_publish.assert_not_called()

    # TEST 20
    def test_registrar_aprobacion(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.assertEqual(len(self.approvals), 1)
        self.assertEqual(
            self.approvals[0]["approver_id"],
            uuid.UUID(self.user_id),
        )
        self.assertEqual(
            self.approvals[0]["decision"],
            "approved",
        )

    # TEST 21
    def test_registrar_rechazo(self):
        self.cambiar_estado(
            "pending_approval", "rejected"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.approvals[0]["decision"],
            "rejected",
        )

    # TEST 22
    def test_no_registrar_aprobacion_en_atencion(self):
        self.cambiar_estado(
            "submitted", "in_fulfillment"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.approvals, [])

    # TEST 23
    def test_publicar_request_approved(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        self.mock_publish.assert_called_once()

        kwargs = self.mock_publish.call_args.kwargs
        self.assertEqual(
            kwargs["event_type"], "RequestApproved"
        )
        self.assertEqual(
            kwargs["tenant_id"], "andina"
        )

    # TEST 24
    def test_publicar_request_rejected(self):
        self.cambiar_estado(
            "pending_approval", "rejected"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        kwargs = self.mock_publish.call_args.kwargs
        self.assertEqual(
            kwargs["event_type"], "RequestRejected"
        )

    # TEST 25
    def test_publicar_request_fulfilled(self):
        self.cambiar_estado(
            "in_fulfillment", "fulfilled"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        kwargs = self.mock_publish.call_args.kwargs
        self.assertEqual(
            kwargs["event_type"], "RequestFulfilled"
        )

    # TEST 26
    def test_no_publicar_en_in_fulfillment(self):
        self.cambiar_estado(
            "submitted", "in_fulfillment"
        )

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.mock_publish.assert_not_called()

    # TEST 27
    def test_detalle_incluye_aprobaciones(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)

        data = json.loads(response["body"])["data"]

        self.assertEqual(len(data["approvals"]), 1)
        self.assertEqual(
            data["approvals"][0]["decision"],
            "approved",
        )

    # TEST 28
    def test_rollback_si_falla_update(self):
        self.fail_update = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")), 1
        )
        self.assertEqual(
            len(self.consultas("COMMIT")), 0
        )
        self.mock_publish.assert_not_called()

    # TEST 29
    def test_rollback_si_falla_aprobacion(self):
        self.fail_approval = True

        with self.assertRaises(RuntimeError):
            self.ejecutar()

        self.assertEqual(
            len(self.consultas("ROLLBACK")), 1
        )
        self.assertEqual(
            len(self.consultas("COMMIT")), 0
        )
        self.mock_publish.assert_not_called()

    # TEST 30
    def test_commit_si_actualiza(self):
        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            len(self.consultas("BEGIN")), 1
        )
        self.assertEqual(
            len(self.consultas("COMMIT")), 1
        )
        self.assertEqual(
            len(self.consultas("ROLLBACK")), 0
        )

    # TEST 31
    def test_aislamiento_por_tenant(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["schema"] = "tenant_pacifico"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 200)
        self.mock_db.assert_called_once_with(
            "tenant_pacifico"
        )

    # TEST 32
    def test_uuid_usuario_invalido(self):
        self.event["requestContext"]["authorizer"][
            "lambda"
        ]["user_id"] = "usuario-invalido"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 500)
        self.mock_db.assert_not_called()

    # TEST 33
    def test_body_sin_status(self):
        self.event["body"] = "{}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()

    # TEST 34
    def test_json_invalido(self):
        self.event["body"] = "{incorrecto}"

        response = self.ejecutar()

        self.assertEqual(response["statusCode"], 400)
        self.mock_db.assert_not_called()




