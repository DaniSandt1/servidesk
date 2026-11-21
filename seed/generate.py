"""Generador de datos ficticios de ServiDesk (F5).

Genera, para cada tenant (andina, pacifico, unitec), 10 000 registros en la tabla principal de
cada microservicio (30 000 por servicio) más sus tablas hijas, como CSV comprimidos:

    seed/out/<servicio>/<tenant>/<tabla>.csv.gz
    seed/out/<servicio>/<tenant>/manifest.json   (orden de carga, columnas, filas, SQL posterior)

Los UUID son deterministas (uuid5), así que los IDs coinciden entre servicios sin consultarse:
usuarios y equipos (ms-identity) se reutilizan en requester_id / reporter_id / assignee_id /
owner_team_id; los CI (ms-cmdb) en incidents.ci_id, problems.ci_id y change_cis.ci_id; los
incidentes, problemas y cambios se enlazan entre sí (problem_id, fix_change_id, incident_ids).

Las 3 cuentas demo por tenant (frontend/src/mocks/db.ts) se incluyen con su contraseña en PBKDF2.
El resto de usuarios comparte la contraseña del tenant (p. ej. Andina#2026) para poder probar
cualquier cuenta.

Uso:  python seed/generate.py [--per-tenant 10000] [--out seed/out]
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import random
import sys
import time
import unicodedata
import uuid
from pathlib import Path

from faker import Faker

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services" / "identity"), str(ROOT / "infra" / "layers" / "common" / "python")]

from handlers.identity_common import hash_password  # noqa: E402
from handlers.tenant_data import NAMESPACE, TEAMS, TENANTS, demo_users, team_id, user_id  # noqa: E402

# ------------------------------------------------------------------ vocabulario (igual que el modo demo)

FLAVOR = {"andina": "retail", "pacifico": "salud", "unitec": "campus"}
APPS = {
    "retail": ["pos-tienda", "erp-sap", "ecommerce-web", "inventario-api", "pagos-gateway", "crm-clientes", "almacen-wms"],
    "salud": ["his-clinico", "citas-web", "laboratorio-lis", "farmacia-api", "pacs-imagenes", "historia-ehr", "facturacion"],
    "campus": ["campus-virtual", "matricula-api", "biblioteca", "notas-sis", "wifi-campus", "correo-edu", "pagos-pension"],
}
CI_TYPES = ["Servidor", "Base de datos", "Aplicación", "Red", "Estación de trabajo", "Servicio cloud"]  # ids 1..6
CI_PREFIX = {1: "srv", 2: "db", 3: "app", 4: "net", 5: "pc", 6: "cloud"}
SEDES = ["Central", "Norte", "Sur", "Este", "Oeste", "Data center Lima", "Data center Arequipa"]
INCIDENT_TITLES = [
    "No puedo acceder a {app}", "{app} responde muy lento", "Error 500 al guardar en {app}",
    "Impresora del piso {n} no imprime", "VPN se desconecta cada pocos minutos", "Correo no sincroniza en el móvil",
    "Contraseña bloqueada tras varios intentos", "Pantalla azul en laptop asignada",
    "Caída intermitente de red en sede {n}", "Certificado SSL vencido en {app}", "No llegan notificaciones de {app}",
    "Disco lleno en servidor de {app}", "Teléfono IP sin tono", "Reporte mensual de {app} no se genera",
    "Wi-Fi sin conexión en sala {n}", "Lentitud general al iniciar sesión", "Fallo en sincronización de {app} con ERP",
    "Usuario sin permisos en carpeta compartida",
]
INCIDENT_DESCRIPTIONS = [
    "El problema empezó esta mañana y afecta al equipo de {area}.",
    "Se reproduce cada vez que intento ingresar desde la sede {sede}.",
    "Varios compañeros reportan lo mismo desde ayer.",
    "Aparece un mensaje de error y no puedo continuar con mi trabajo.",
    "Ocurre de forma intermitente, sobre todo en horario punta.",
]
PROBLEM_TITLES = [
    "Fugas de memoria recurrentes en {app}", "Saturación del pool de conexiones de {app}",
    "Cortes de red en horario punta", "Fallas repetidas de autenticación SSO",
    "Errores de replicación en base de datos de {app}", "Degradación del rendimiento tras actualizaciones",
    "Caídas del servicio de colas en {app}", "Tiempo de respuesta alto en {app} los lunes",
]
ROOT_CAUSES = [
    "Configuración incorrecta del pool de conexiones tras la última versión.",
    "Controlador de red desactualizado en los equipos afectados.",
    "Tarea programada que bloquea tablas durante el horario laboral.",
    "Memoria insuficiente asignada a la máquina virtual.",
    "Certificado intermedio no renovado en el balanceador.",
    "Índice faltante en la consulta principal del módulo.",
]
WORKAROUNDS = [
    "Reiniciar el servicio de la aplicación desde la consola de administración.",
    "Reiniciar el pool de conexiones desde la consola del balanceador (5 minutos).",
    "Cerrar sesión, borrar la caché del navegador y volver a ingresar.",
    "Conectarse por la red cableada mientras se corrige el Wi-Fi.",
    "Ejecutar el reporte fuera del horario punta.",
]
CHANGE_TITLES = [
    "Actualizar {app} a la versión {v}", "Aplicar parches de seguridad mensuales en servidores",
    "Migrar base de datos de {app} a nueva instancia", "Ampliar almacenamiento del clúster de {app}",
    "Renovar certificados SSL de {app}", "Reemplazar switch del piso {n}", "Habilitar MFA para acceso remoto",
    "Ajustar reglas del firewall perimetral", "Escalar horizontalmente {app}",
    "Desplegar nueva versión del portal de {app}",
]
COMMENTS = [
    "Se revisaron los registros del servicio; se observa un pico de errores a las {h}:00.",
    "Contacté al usuario, confirma que el problema persiste.", "Se reinició el servicio y se está monitoreando.",
    "Escalado al equipo de infraestructura para revisión.",
    "Pendiente de ventana de mantenimiento para aplicar la corrección.", "El usuario adjunta captura del error.",
    "Se aplicó la solución temporal publicada en el error conocido.", "Gracias, quedo atento a la actualización.",
]
AREAS = ["Ventas", "Finanzas", "Logística", "Recursos Humanos", "Marketing", "Operaciones", "Atención al cliente"]
SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}
PRIORITY = {("high", "high"): "P1", ("high", "medium"): "P2", ("high", "low"): "P3",
            ("medium", "high"): "P2", ("medium", "medium"): "P3", ("medium", "low"): "P4",
            ("low", "high"): "P3", ("low", "medium"): "P4", ("low", "low"): "P4"}

H = dt.timedelta(hours=1)
D = dt.timedelta(days=1)


def uid(tenant, kind, n):
    return str(uuid.uuid5(NAMESPACE, f"{tenant}:{kind}:{n}"))


def ts(value):
    return None if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def ascii_slug(text):
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().lower().replace(" ", "")


def weighted(rng, pairs):
    values, weights = zip(*pairs)
    return rng.choices(values, weights=weights, k=1)[0]


def fill(rng, template, apps):
    return (template.replace("{app}", rng.choice(apps)).replace("{n}", str(rng.randint(1, 9)))
            .replace("{v}", f"{rng.randint(2, 9)}.{rng.randint(0, 12)}").replace("{h}", f"{rng.randint(8, 20):02d}"))


def recent_time(rng, now, max_days, bias=1.6):
    """Fecha en los últimos max_days días, con más densidad cerca de hoy."""
    return now - dt.timedelta(seconds=int((rng.random() ** bias) * max_days * 86400))


# ------------------------------------------------------------------ escritura


class Writer:
    """Acumula tablas por servicio/tenant y escribe CSV.gz + manifest.json."""

    def __init__(self, out_dir):
        self.out = out_dir
        self.totals = {}

    def write(self, service, tenant, tables, post_sql=()):
        folder = self.out / service / tenant
        folder.mkdir(parents=True, exist_ok=True)
        manifest = {"service": service, "tenant": tenant, "tables": [], "post_sql": list(post_sql)}
        for table, columns, rows in tables:
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(columns)
            for row in rows:
                w.writerow(["" if v is None else ("t" if v is True else "f" if v is False else v) for v in row])
            data = gzip.compress(buf.getvalue().encode("utf-8"), mtime=0)
            (folder / f"{table}.csv.gz").write_bytes(data)
            manifest["tables"].append({"table": table, "columns": list(columns), "rows": len(rows),
                                       "file": f"{table}.csv.gz"})
            self.totals.setdefault(service, {}).setdefault(table, 0)
            self.totals[service][table] += len(rows)
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ generación por tenant


def generate_tenant(tenant, n, now, writer):
    code = tenant["code"]
    flavor = FLAVOR[code]
    apps = APPS[flavor]
    fake = Faker("es_ES")
    fake.seed_instance(f"servidesk:{code}")

    # ---------------------------------------------------------------- identity
    rng = random.Random(f"{code}:identity")
    teams = [(team_id(code, name), name, desc) for name, desc in TEAMS]
    team_ids = [t[0] for t in teams]
    bulk_hash = hash_password(tenant["password"])

    users = []  # (id, email, full_name, role, password_hash, active, created_at)
    emails = set()
    for demo in demo_users(tenant):
        users.append([demo["id"], demo["email"], demo["full_name"], demo["role"], hash_password(demo["password"]),
                      True, ts(now - 700 * D)])
        emails.add(demo["email"])
    i = 0
    while len(users) < n:
        i += 1
        role = "admin" if i <= 17 else "agent" if i <= 1000 else "customer"
        first, last1, last2 = fake.first_name(), fake.last_name(), fake.last_name()
        email = f"{ascii_slug(first)}.{ascii_slug(last1)}{i}@{tenant['domain']}"
        if email in emails:
            continue
        emails.add(email)
        users.append([user_id(code, email), email, f"{first} {last1} {last2}", role, bulk_hash,
                      rng.random() > 0.03, ts(now - rng.randint(1, 730) * D - rng.randint(0, 86399) * dt.timedelta(seconds=1))])

    admins = [u[0] for u in users if u[3] == "admin"]
    agents = [u[0] for u in users if u[3] == "agent"]
    staff = admins + agents
    customers = [u[0] for u in users if u[3] == "customer"]
    demo_admin, demo_agent, demo_customer = (u["id"] for u in demo_users(tenant))

    members = set()
    member_rows = []
    for k, user in enumerate(u for u in users if u[3] != "customer"):
        chosen = team_ids[:2] if user[0] in (demo_admin, demo_agent) else rng.sample(team_ids, rng.choice([1, 1, 2]))
        for t in chosen:
            if (t, user[0]) not in members:
                members.add((t, user[0]))
                member_rows.append([t, user[0], False])
    for t in team_ids:  # un líder por equipo
        for row in member_rows:
            if row[0] == t:
                row[2] = True
                break
    team_members_of = {}
    for t, u, _ in member_rows:
        team_members_of.setdefault(t, []).append(u)

    writer.write("identity", code, [
        ("teams", ("id", "name", "description", "created_at"), [[t, nm, ds, ts(now - 800 * D)] for t, nm, ds in teams]),
        ("users", ("id", "email", "full_name", "role", "password_hash", "active", "created_at"), users),
        ("team_members", ("team_id", "user_id", "is_lead"), member_rows),
    ])

    # ---------------------------------------------------------------- cmdb
    rng = random.Random(f"{code}:cmdb")
    cis = []  # [id, type_id, name, status, environment, version, owner_team_id, attributes, created_at, updated_at]
    for k in range(1, n + 1):
        type_id = weighted(rng, [(1, 25), (2, 10), (3, 25), (4, 12), (5, 20), (6, 8)])
        env = weighted(rng, [("prod", 5), ("qa", 2), ("dev", 2)])
        status = weighted(rng, [("operational", 85), ("degraded", 7), ("down", 2), ("retired", 6)])
        created = now - rng.randint(30, 1100) * D
        updated = min(now, created + rng.randint(0, 900) * D)
        base = rng.choice(apps) if type_id in (2, 3, 6) else rng.choice(SEDES).lower().replace(" ", "-")
        name = f"{CI_PREFIX[type_id]}-{ascii_slug(base)}-{env}-{k:05d}"
        attrs = {"sede": rng.choice(SEDES)}
        if type_id in (1, 2, 4, 5):
            attrs["ip"] = f"10.{rng.randint(10, 60)}.{rng.randint(0, 255)}.{rng.randint(2, 254)}"
        if type_id in (1, 5):
            attrs["os"] = rng.choice(["Ubuntu 22.04", "Windows Server 2022", "Windows 11", "Red Hat 9"])
        if type_id == 2:
            attrs["motor"] = rng.choice(["PostgreSQL 16", "MySQL 8", "SQL Server 2022", "Oracle 19c"])
        if type_id == 6:
            attrs["proveedor"] = rng.choice(["AWS", "Azure", "GCP"])
        cis.append([uid(code, "ci", k), type_id, name, status, env,
                    f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}",
                    rng.choice(team_ids), json.dumps(attrs, ensure_ascii=False), ts(created), ts(updated)])
    active_cis = [c for c in cis if c[3] != "retired"]
    ci_name = {c[0]: c[2] for c in cis}

    rel_rows, rel_seen = [], set()
    while len(rel_rows) < n // 3:
        a, b = rng.sample(cis, 2)
        rel = weighted(rng, [("depends_on", 5), ("runs_on", 3), ("connects_to", 2)])
        if (a[0], b[0], rel) in rel_seen:
            continue
        rel_seen.add((a[0], b[0], rel))
        rel_rows.append([uid(code, "rel", len(rel_rows)), a[0], b[0], rel, a[8]])
    history = [[uid(code, "cihist", k), c[0], "created", None, c[2], rng.choice(staff), "api", None, c[8]]
               for k, c in enumerate(cis)]

    writer.write("cmdb", code, [
        ("configuration_items", ("id", "type_id", "name", "status", "environment", "version", "owner_team_id",
                                 "attributes", "created_at", "updated_at"), cis),
        ("ci_relations", ("id", "source_ci_id", "target_ci_id", "relation", "created_at"), rel_rows),
        ("ci_history", ("id", "ci_id", "field", "old_value", "new_value", "actor_id", "source", "change_id",
                        "changed_at"), history),
    ])

    # ---------------------------------------------------------------- requests (catálogo + solicitudes)
    rng = random.Random(f"{code}:requests")
    just = {"name": "justificacion", "label": "Justificación", "type": "textarea", "required": True}
    categories = [(1, "Hardware", "Equipos y periféricos"), (2, "Software", "Licencias e instalaciones"),
                  (3, "Accesos", "Cuentas, permisos y VPN"), (4, "Colaboración", "Correo y videoconferencia"),
                  (5, "Personas", "Altas y bajas de colaboradores")]
    catalog_def = [
        (1, "Laptop nueva", [{"name": "modelo", "label": "Modelo", "type": "select", "required": True,
                              "options": ['Estándar 14"', 'Desarrollo 16"', 'Ultraligera 13"']},
                             {"name": "fecha_entrega", "label": "Fecha deseada", "type": "date", "required": False},
                             just], True, 72),
        (1, "Monitor adicional", [{"name": "tamano", "label": "Tamaño", "type": "select", "required": True,
                                   "options": ['24"', '27"', '32"']}, just], True, 48),
        (1, "Periféricos (mouse, teclado, headset)", [
            {"name": "item", "label": "Artículo", "type": "select", "required": True,
             "options": ["Mouse", "Teclado", "Headset", "Webcam"]},
            {"name": "cantidad", "label": "Cantidad", "type": "number", "required": True}], False, 24),
        (2, "Licencia de software", [{"name": "producto", "label": "Producto", "type": "select", "required": True,
                                      "options": ["Microsoft 365 E3", "Adobe Acrobat Pro", "JetBrains All Products",
                                                  "Tableau Creator"]}, just], True, 48),
        (2, "Instalación de aplicación", [{"name": "aplicacion", "label": "Aplicación", "type": "text", "required": True},
                                          {"name": "equipo", "label": "Nombre del equipo", "type": "text",
                                           "required": True}], False, 24),
        (3, "Acceso a sistema", [{"name": "sistema", "label": "Sistema", "type": "select", "required": True,
                                  "options": apps},
                                 {"name": "perfil", "label": "Perfil", "type": "select", "required": True,
                                  "options": ["Lectura", "Operador", "Administrador"]}, just], True, 24),
        (3, "Restablecer contraseña", [{"name": "cuenta", "label": "Cuenta", "type": "text", "required": True}],
         False, 4),
        (3, "Acceso VPN", [{"name": "temporal", "label": "Acceso temporal", "type": "boolean", "required": False},
                           {"name": "hasta", "label": "Vigente hasta", "type": "date", "required": False}, just],
         True, 24),
        (4, "Buzón o lista de correo compartida", [
            {"name": "nombre", "label": "Nombre del buzón", "type": "text", "required": True},
            {"name": "miembros", "label": "Miembros (correos)", "type": "textarea", "required": True}], False, 24),
        (4, "Sala de videoconferencia", [{"name": "sede", "label": "Sede", "type": "select", "required": True,
                                          "options": ["Central", "Norte", "Sur"]},
                                         {"name": "fecha", "label": "Fecha", "type": "date", "required": True}],
         False, 8),
        (5, "Alta de nuevo colaborador", [{"name": "nombre", "label": "Nombre completo", "type": "text", "required": True},
                                          {"name": "area", "label": "Área", "type": "text", "required": True},
                                          {"name": "inicio", "label": "Fecha de ingreso", "type": "date",
                                           "required": True},
                                          {"name": "laptop", "label": "Requiere laptop", "type": "boolean",
                                           "required": False}], True, 72),
        (5, "Baja de colaborador", [{"name": "nombre", "label": "Nombre completo", "type": "text", "required": True},
                                    {"name": "ultimo_dia", "label": "Último día", "type": "date", "required": True}],
         True, 24),
    ]
    catalog_rows = [[uid(code, "catalog", k), cat, name, f"Solicita: {name.lower()}.",
                     json.dumps({"fields": fields}, ensure_ascii=False), needs, sla, True, ts(now - 600 * D)]
                    for k, (cat, name, fields, needs, sla) in enumerate(catalog_def)]

    req_rows, approvals = [], []
    created_list = sorted(recent_time(rng, now, 365) for _ in range(n))
    for k, created in enumerate(created_list, start=1):
        item_idx = rng.randrange(len(catalog_def))
        _, _, fields, needs, sla = catalog_def[item_idx]
        recent = now - created < 5 * D
        if needs:
            status = weighted(rng, [("pending_approval", 4), ("approved", 2), ("in_fulfillment", 2), ("rejected", 1)]) \
                if recent else weighted(rng, [("fulfilled", 12), ("rejected", 2), ("in_fulfillment", 1)])
        else:
            status = weighted(rng, [("submitted", 4), ("in_fulfillment", 3), ("fulfilled", 2)]) \
                if recent else weighted(rng, [("fulfilled", 14), ("rejected", 1)])
        form = {}
        for f in fields:
            t = f["type"]
            form[f["name"]] = (rng.choice(f["options"]) if t == "select" else rng.randint(1, 3) if t == "number"
                               else rng.random() < 0.5 if t == "boolean"
                               else (created + rng.randint(2, 15) * D).strftime("%Y-%m-%d") if t == "date"
                               else "Necesario para cumplir con las tareas del puesto." if t == "textarea"
                               else fake.name())
        req_id = uid(code, "request", k)
        requester = demo_customer if k % 17 == 0 else rng.choice(customers)
        assignee = rng.choice(agents) if status in ("in_fulfillment", "fulfilled") else None
        fulfilled = created + rng.randint(2, 70) * H if status == "fulfilled" else None
        req_rows.append([req_id, f"REQ-{k:06d}", catalog_rows[item_idx][0], json.dumps(form, ensure_ascii=False),
                         status, requester, assignee, ts(created), ts(min(fulfilled, now) if fulfilled else None)])
        if needs and status != "pending_approval":
            approvals.append([uid(code, "reqappr", k), req_id, demo_admin if rng.random() < 0.3 else rng.choice(admins),
                              "rejected" if status == "rejected" else "approved",
                              ts(min(now, created + rng.randint(1, 30) * H))])

    writer.write("requests", code, [
        ("catalog_categories", ("id", "name", "description", "created_at"),
         [[cid, name, desc, ts(now - 600 * D)] for cid, name, desc in categories]),
        ("catalog_items", ("id", "category_id", "name", "description", "form_schema", "needs_approval", "sla_hours",
                           "active", "created_at"), catalog_rows),
        ("service_requests", ("id", "key", "catalog_item_id", "form_data", "status", "requester_id", "assignee_id",
                              "created_at", "fulfilled_at"), req_rows),
        ("request_approvals", ("id", "request_id", "approver_id", "decision", "decided_at"), approvals),
    ], post_sql=["SELECT setval(pg_get_serial_sequence('catalog_categories', 'id'), "
                 "(SELECT MAX(id) FROM catalog_categories))"])

    # ---------------------------------------------------------------- incidents
    rng = random.Random(f"{code}:incidents")
    incidents = []
    created_list = sorted(recent_time(rng, now, 365) for _ in range(n))
    for k, created in enumerate(created_list, start=1):
        channel = weighted(rng, [("portal", 80), ("email", 15), ("auto", 5)])
        if channel == "auto":  # igual que incidents-ci-q: P2 (alto x media)
            impact, urgency = "high", "medium"
        else:
            impact = weighted(rng, [("high", 2), ("medium", 5), ("low", 3)])
            urgency = weighted(rng, [("high", 3), ("medium", 5), ("low", 2)])
        priority = PRIORITY[(impact, urgency)]
        age = now - created
        if age < 2 * D:
            status = weighted(rng, [("new", 5), ("in_progress", 4), ("on_hold", 1), ("resolved", 2)])
        elif age < 10 * D:
            status = weighted(rng, [("in_progress", 3), ("on_hold", 1), ("resolved", 4), ("closed", 3)])
        else:
            status = weighted(rng, [("resolved", 2), ("closed", 12), ("in_progress", 1)])
        due = created + SLA_HOURS[priority] * H
        resolved = None
        if status in ("resolved", "closed"):
            resolved = min(now, created + dt.timedelta(minutes=rng.randint(20, int(SLA_HOURS[priority] * 60 * 1.6))))
        breached = (resolved > due) if resolved else (now > due)
        team = rng.choice(team_ids)
        assignee = None if status == "new" and rng.random() < 0.6 else (
            demo_agent if rng.random() < 0.05 else rng.choice(team_members_of.get(team) or agents))
        # en los automáticos reporta quien marcó el CI como caído (personal de TI)
        reporter = rng.choice(staff) if channel == "auto" else (demo_customer if k % 23 == 0 else rng.choice(customers))
        ci = rng.choice(active_cis)[0] if (channel == "auto" or rng.random() < 0.7) else None
        title = (f"[Automático] {ci_name[ci]} dejó de responder" if channel == "auto"
                 else fill(rng, rng.choice(INCIDENT_TITLES), apps))
        desc = rng.choice(INCIDENT_DESCRIPTIONS).replace("{area}", rng.choice(AREAS)).replace("{sede}", rng.choice(SEDES))
        incidents.append({"id": uid(code, "incident", k), "key": f"INC-{k:06d}", "title": title[:200],
                          "description": desc, "status": status, "impact": impact, "urgency": urgency,
                          "priority": priority, "sla_due_at": due, "sla_breached": breached, "reporter_id": reporter,
                          "assignee_id": assignee, "team_id": team, "ci_id": ci, "problem_id": None,
                          "channel": channel, "created_at": created, "resolved_at": resolved})

    comments = []
    for inc in incidents:
        for c in range(rng.choice([0, 1, 1, 1, 2])):
            internal = inc["assignee_id"] is not None and rng.random() < 0.25
            author = inc["assignee_id"] if (internal or not inc["reporter_id"] or rng.random() < 0.6) else inc["reporter_id"]
            comments.append([uid(code, "comment", f"{inc['key']}:{c}"), inc["id"], author or demo_admin,
                             fill(rng, rng.choice(COMMENTS), apps), internal,
                             ts(min(now, inc["created_at"] + rng.randint(5, 600) * dt.timedelta(minutes=1)))])

    # ---------------------------------------------------------------- problems (enlazan incidentes)
    rng = random.Random(f"{code}:problems")
    problems, links, known = [], [], []
    linkable = [inc for inc in incidents if inc["ci_id"]]
    rng.shuffle(linkable)
    created_list = sorted(recent_time(rng, now, 540, bias=1.2) for _ in range(n))
    for k, created in enumerate(created_list, start=1):
        status = weighted(rng, [("new", 10), ("investigating", 25), ("known_error", 15), ("resolved", 25),
                                ("closed", 25)])
        prob = {"id": uid(code, "problem", k), "key": f"PRB-{k:06d}",
                "title": fill(rng, rng.choice(PROBLEM_TITLES), apps)[:200],
                "description": "Análisis de causa raíz de incidentes recurrentes.", "status": status,
                "priority": weighted(rng, [("P1", 1), ("P2", 3), ("P3", 4), ("P4", 2)]),
                "root_cause": rng.choice(ROOT_CAUSES) if status in ("known_error", "resolved", "closed") else None,
                "ci_id": rng.choice(active_cis)[0], "owner_id": demo_agent if k % 29 == 0 else rng.choice(agents),
                "fix_change_id": None, "created_at": created}
        if rng.random() < 0.3 and linkable:
            group = [linkable.pop() for _ in range(min(len(linkable), rng.choice([1, 2, 3])))]
            if group:
                prob["ci_id"] = group[0]["ci_id"]
                for inc in group:
                    inc["problem_id"] = prob["id"]
                    links.append([prob["id"], inc["id"], ts(max(created, inc["created_at"]))])
        if status in ("known_error", "resolved", "closed"):
            known.append([uid(code, "kedb", k), prob["id"],
                          f"Los usuarios reportan: {prob['title'].lower()}.", rng.choice(WORKAROUNDS),
                          ts(min(now, created + rng.randint(1, 20) * D))])
        problems.append(prob)

    # ---------------------------------------------------------------- changes (corrigen problemas, tocan CIs)
    rng = random.Random(f"{code}:changes")
    changes, change_cis, change_approvals = [], [], []
    fixable = [p for p in problems if p["status"] in ("resolved", "closed")]
    rng.shuffle(fixable)
    created_list = sorted(recent_time(rng, now, 365, bias=1.1) for _ in range(n))
    for k, created in enumerate(created_list, start=1):
        ctype = weighted(rng, [("standard", 4), ("normal", 5), ("emergency", 1)])
        risk = "low" if ctype == "standard" else weighted(rng, [("low", 3), ("medium", 5), ("high", 2)])
        start = created + rng.randint(1, 20) * D + rng.randint(0, 23) * H
        if ctype == "emergency":
            start = created + rng.randint(1, 12) * H
        end = start + rng.randint(1, 6) * H
        if start > now:
            status = weighted(rng, [("draft", 2), ("submitted", 3), ("approved", 3), ("scheduled", 4), ("rejected", 1)])
        else:
            status = weighted(rng, [("implemented", 15), ("failed", 1), ("rejected", 2)])
        if ctype == "standard" and status == "submitted":
            status = "approved"  # D14: los standard se aprueban solos
        change_id = uid(code, "change", k)
        problem = fixable.pop() if (status == "implemented" and fixable and rng.random() < 0.35) else None
        if problem:
            problem["fix_change_id"] = change_id
        changes.append([change_id, f"CHG-{k:06d}", fill(rng, rng.choice(CHANGE_TITLES), apps)[:200],
                        "Cambio planificado para mejorar la estabilidad y seguridad del servicio.", ctype, risk, status,
                        None if (ctype == "standard" and rng.random() < 0.5)
                        else "Restaurar la instantánea previa y revertir la configuración desde el repositorio.",
                        ts(start), ts(end), demo_agent if k % 31 == 0 else rng.choice(agents),
                        problem["id"] if problem else None, ts(created)])
        for ci in rng.sample(active_cis, rng.choice([1, 1, 2])):
            change_cis.append([change_id, ci[0],
                               f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}" if rng.random() < 0.6
                               else None])
        if ctype != "standard" and status in ("approved", "scheduled", "implemented", "failed", "rejected"):
            decision = "rejected" if status == "rejected" else "approved"
            change_approvals.append([uid(code, "chgappr", k), change_id,
                                     demo_admin if rng.random() < 0.3 else rng.choice(admins), decision,
                                     "Aprobado en CAB." if decision == "approved" else "Riesgo no justificado; replanificar.",
                                     ts(min(now, created + rng.randint(2, 48) * H))])

    # ---------------------------------------------------------------- escritura incidents / problems / changes
    writer.write("incidents", code, [
        ("incidents", ("id", "key", "title", "description", "status", "impact", "urgency", "priority",
                       "sla_policy_id", "sla_due_at", "sla_breached", "reporter_id", "assignee_id", "team_id",
                       "ci_id", "problem_id", "channel", "created_at", "resolved_at"),
         [[i["id"], i["key"], i["title"], i["description"], i["status"], i["impact"], i["urgency"], i["priority"],
           None, ts(i["sla_due_at"]), i["sla_breached"], i["reporter_id"], i["assignee_id"], i["team_id"],
           i["ci_id"], i["problem_id"], i["channel"], ts(i["created_at"]), ts(i["resolved_at"])] for i in incidents]),
        ("incident_comments", ("id", "incident_id", "author_id", "body", "internal", "created_at"), comments),
    ], post_sql=[
        # sla_policy_id se resuelve por prioridad contra las políticas que creó la migración 003
        "UPDATE incidents i SET sla_policy_id = s.id FROM sla_policies s WHERE s.priority = i.priority",
    ])
    writer.write("problems", code, [
        ("problems", ("id", "key", "title", "description", "status", "priority", "root_cause", "ci_id", "owner_id",
                      "fix_change_id", "created_at"),
         [[p["id"], p["key"], p["title"], p["description"], p["status"], p["priority"], p["root_cause"], p["ci_id"],
           p["owner_id"], p["fix_change_id"], ts(p["created_at"])] for p in problems]),
        ("problem_incidents", ("problem_id", "incident_id", "created_at"), links),
        ("known_errors", ("id", "problem_id", "symptom", "workaround", "created_at"), known),
    ])
    writer.write("changes", code, [
        ("changes", ("id", "key", "title", "description", "type", "risk", "status", "rollback_plan", "planned_start",
                     "planned_end", "requester_id", "problem_id", "created_at"), changes),
        ("change_cis", ("change_id", "ci_id", "new_version"), change_cis),
        ("change_approvals", ("id", "change_id", "approver_id", "decision", "comment", "decided_at"),
         change_approvals),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-tenant", type=int, default=10_000)
    parser.add_argument("--out", type=Path, default=ROOT / "seed" / "out")
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    writer = Writer(args.out)
    started = time.time()
    for tenant in TENANTS:
        t0 = time.time()
        generate_tenant(tenant, args.per_tenant, now, writer)
        print(f"  {tenant['code']:9} generado en {time.time() - t0:5.1f} s")

    print(f"\nTotales (3 tenants) en {args.out}:")
    for service, tables in writer.totals.items():
        print(f"  {service:10} " + ", ".join(f"{t}={c:,}" for t, c in tables.items()))
    size = sum(f.stat().st_size for f in args.out.rglob("*.csv.gz"))
    print(f"\n{size / 1e6:.1f} MB comprimidos · {time.time() - started:.1f} s")


if __name__ == "__main__":
    main()
