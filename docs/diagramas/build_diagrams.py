"""Genera los diagramas de ServiDesk en draw.io (editables) y los exporta a PNG.

    python docs/diagramas/build_diagrams.py            # .drawio + PNG (necesita draw.io Desktop)
    python docs/diagramas/build_diagrams.py --no-png   # solo los .drawio

Salida (docs/diagramas/):
    servidesk_er.drawio (6 páginas) -> 2_er_identity.png ... 7_er_requests.png

La arquitectura de solución se genera con build_arquitectura_v2.py.

Estilo tomado de los diagramas del proyecto 1 (CloudCommerce): contenedor AWS Cloud, cajas con
tinte y borde por categoría de AWS, flechas ortogonales con etiqueta y color por tipo de flujo,
leyenda y notas; E/R con un contenedor punteado por base, tablas con encabezado de color,
PK/FK/UQ, pata de gallo sólida para FK reales y punteada gris para referencias a otro servicio.

Solo se dibujan como entidades las tablas relacionales reales de cada base (todas PostgreSQL).
Las columnas JSONB se muestran con un ejemplo de su estructura JSON (no como entidades) y las
tablas técnicas sin relaciones (idempotencia de SQS) van en una nota.
"""

import argparse
import html
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent
DRAWIO = Path(r"C:\Program Files\draw.io\draw.io.exe")
FONT = "Helvetica"

# Colores de categoría AWS (aws4) y tintes de fondo, como en el proyecto 1
C = {
    "front": ("#DD344C", "#FDECEF"),     # Amplify
    "appint": ("#E7157B", "#FDEAF3"),    # API Gateway, SNS, SQS
    "compute": ("#ED7100", "#FFF4EA"),   # Lambda
    "db": ("#3B48CC", "#EEF0FC"),        # RDS (borde azul como las BD del proyecto 1)
    "storage": ("#7AA116", "#F3F8E8"),   # S3
    "mgmt": ("#E7157B", "#FDEAF3"),      # CloudWatch, CloudFormation
    "security": ("#DD344C", "#FDECEF"),  # IAM
    "net": ("#8C4FFF", "#F4EEFF"),       # VPC / authorizer
    "neutral": ("#232F3E", "#FFFFFF"),
}
INK = "#232F3E"
MUTED = "#5F6B7A"


class Page:
    def __init__(self, name, width, height):
        self.name = name
        self.width = width
        self.height = height
        self.cells = []
        self.geom = {}
        self.n = 0

    def _id(self):
        self.n += 1
        return f"c{self.n}"

    def vertex(self, x, y, w, h, value="", style="", parent="1"):
        cid = self._id()
        self.geom[cid] = (x, y, w, h)
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" '
            f'parent="{parent}"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def edge(self, src, dst, value="", style="", points=None):
        cid = self._id()
        value = value.replace("\n", "<br>")  # html=1: los saltos de línea van como <br>
        pts = ""
        if points:
            pts = "<Array as=\"points\">" + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + "</Array>"
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" edge="1" parent="1" '
            f'source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>')
        return cid

    def xml(self):
        body = "".join(self.cells)
        return (f'<diagram name="{escape(self.name)}" id="{self.name}"><mxGraphModel dx="1600" dy="900" grid="0" '
                f'gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
                f'pageWidth="{self.width}" pageHeight="{self.height}" background="#FFFFFF" math="0" shadow="0">'
                f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram>')


def save(pages, path):
    path.write_text('<mxfile host="drawio" agent="servidesk/build_diagrams.py">' +
                    "".join(p.xml() for p in pages) + "</mxfile>", encoding="utf-8")


# ------------------------------------------------------------------ primitivas de estilo


def text(p, x, y, w, h, value, size=12, bold=False, color=INK, align="left", valign="top", italic=False):
    fs = (1 if bold else 0) + (2 if italic else 0)
    return p.vertex(x, y, w, h, value,
                    f"text;html=1;whiteSpace=wrap;fontFamily={FONT};fontSize={size};fontStyle={fs};"
                    f"fontColor={color};align={align};verticalAlign={valign};strokeColor=none;fillColor=none;")


def group(p, x, y, w, h, title, subtitle="", color="#232F3E", fill="#FFFFFF", dashed=False, rounded=True,
          title_size=13, width=2, res=None):
    """Contenedor con título arriba a la izquierda; con res, el ícono del servicio va antes del título
    (como los grupos "VPC" y "EC2 · …" del proyecto 1)."""
    label = f'<b style="font-size:{title_size}px">{html.escape(title)}</b>'
    if subtitle:
        label += f'<br><span style="font-size:11px;color:{MUTED}">{html.escape(subtitle)}</span>'
    cid = p.vertex(x, y, w, h, label,
                   f"rounded={1 if rounded else 0};arcSize=3;absoluteArcSize=1;html=1;whiteSpace=wrap;"
                   f"fontFamily={FONT};fontColor={color};strokeColor={color};fillColor={fill};"
                   f"strokeWidth={width};dashed={1 if dashed else 0};dashPattern=8 6;align=left;verticalAlign=top;"
                   f"spacingLeft={48 if res else 14};spacingTop=8;container=0;")
    if res:
        icon(p, x + 12, y + 11, res, color, 26)
    return cid


def component(p, x, y, w, h, title, lines, color, fill="#FFFFFF", title_size=14, line_size=11):
    """Componente dentro de un grupo: blanco con borde de color, sin ícono (como 'ms-productos :8001')."""
    body = f'<b style="font-size:{title_size}px;color:{INK}">{html.escape(title)}</b>'
    if lines:
        body += f'<br><span style="font-size:{line_size}px;color:{MUTED}">' + \
                "<br>".join(html.escape(line) for line in lines) + "</span>"
    return p.vertex(x, y, w, h, body,
                    f"rounded=1;arcSize=6;html=1;whiteSpace=wrap;fontFamily={FONT};strokeColor={color};"
                    f"fillColor={fill};strokeWidth=2;align=center;verticalAlign=middle;spacingLeft=8;"
                    f"spacingRight=8;")


def icon(p, x, y, res, color, size=30):
    return p.vertex(x, y, size, size, "",
                    f"sketch=0;outlineConnect=0;fontColor={INK};fillColor={color};strokeColor=#ffffff;dashed=0;"
                    f"html=1;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};")


def service(p, x, y, w, h, title, lines, cat, res=None, title_size=14, line_size=11, align="center"):
    """Caja de servicio AWS: borde y tinte de la categoría, ícono arriba, título y detalle."""
    stroke, fill = C[cat]
    body = f'<b style="font-size:{title_size}px;color:{INK}">{html.escape(title)}</b>'
    if lines:
        body += f'<br><span style="font-size:{line_size}px;color:{MUTED}">' + \
                "<br>".join(html.escape(line) for line in lines) + "</span>"
    top = 44 if res else 10
    cid = p.vertex(x, y, w, h, body,
                   f"rounded=1;arcSize=6;html=1;whiteSpace=wrap;fontFamily={FONT};strokeColor={stroke};"
                   f"fillColor={fill};strokeWidth=2;align={align};verticalAlign=top;spacingTop={top};"
                   f"spacingLeft=8;spacingRight=8;")
    if res:
        icon(p, x + (w - 30) / 2 if align == "center" else x + 12, y + 8, res, stroke)
    return cid


def arrow(p, src, dst, label="", color=INK, dashed=False, width=2, exit=None, entry=None, points=None,
          end="block", start="none", font_color=None):
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontFamily={FONT};fontSize=11;"
             f"fontColor={font_color or INK};strokeColor={color};strokeWidth={width};endArrow={end};endFill=1;"
             f"startArrow={start};startFill=1;dashed={1 if dashed else 0};dashPattern=6 4;"
             f"labelBackgroundColor=#FFFFFF;jumpStyle=arc;")
    if exit:
        style += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry:
        style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    return p.edge(src, dst, label, style, points)


# ------------------------------------------------------------------ 1. arquitectura


def architecture():
    p = Page("Arquitectura", 2400, 1600)
    text(p, 40, 18, 1400, 36, "ServiDesk — Diagrama de Arquitectura de Solución (AWS)", 24, True)
    text(p, 40, 52, 1700, 22, "SaaS de gestión de servicios TI (ITSM) · multi-tenant (un schema por tenant) · "
                              "100 % serverless · basado en eventos (SNS → SQS)", 13, color=MUTED)

    # ---------------------------------------------------------------- actores externos
    user = service(p, 30, 170, 190, 100, "Usuario", ["Navegador web", "andina · pacifico · unitec"], "neutral",
                   "user")
    dev = service(p, 30, 640, 190, 126, "Equipo / desarrollador", ["Repo GitHub al3xi3w/servidesk",
                                                                   "npm run deploy", "scripts/*.py · seed/*.py"],
                  "neutral", "git_repository")

    group(p, 250, 90, 2120, 1480, "AWS Cloud — región us-east-1", "AWS Academy Learner Lab · rol LabRole",
          color="#232F3E", width=2)

    # ---------------------------------------------------------------- entrada
    amplify = service(p, 300, 160, 250, 116, "AWS Amplify Hosting",
                      ["Frontend React 19 + Vite (SPA)", "app servidesk · rama main", "publicado con deploy_frontend.py"],
                      "front", "amplify")
    apigw = service(p, 300, 360, 250, 420, "Amazon API Gateway",
                    ["6 HTTP API · HTTPS · CORS", "una por microservicio", "",
                     "identity  /auth/login · /auth/me", "/users · /teams · /notifications",
                     "cmdb  /cis · /ci-types", "incidents  /incidents/{id}/…", "problems  /problems/{id}/…",
                     "changes  /changes/{id}/approve…", "requests  /catalog · /requests", "",
                     "43 rutas con authorizer JWT", "+ POST /auth/login pública"], "appint", "api_gateway")
    authz = service(p, 300, 830, 250, 140, "Lambda Authorizer",
                    ["JWT HS256 · respuesta simple", "valida firma, exp y claims", "contexto: tenant_id · schema ·",
                     "role · user_id (caché 300 s)"], "compute", "lambda")
    sec = group(p, 300, 1010, 250, 230, "Seguridad y multi-tenancy", color="#7D8998")
    text(p, 310, 1040, 236, 196,
         "• El tenant y el schema salen solo del JWT firmado; el backend rechaza tenant_id en el body.<br>"
         "• Datos de otro tenant responden 404.<br>"
         "• Contraseñas PBKDF2-SHA256 (310 000 iteraciones).<br>"
         "• RDS con SSL; secretos solo en variables de entorno.", 11)

    # ---------------------------------------------------------------- microservicios
    lam = group(p, 600, 150, 710, 790, "Microservicios — AWS Lambda (Python 3.12)",
                "6 servicios · 57 funciones (rutas HTTP, consumidores SQS y migrate) · cada uno con su propia base",
                color=C["compute"][0], fill=C["compute"][1], dashed=True, res="lambda")
    specs = [
        ("ms-identity", ["login JWT (PBKDF2) · usuarios · equipos", "bandeja de notificaciones",
                         "consume identity-notify-q"]),
        ("ms-cmdb", ["CIs · relaciones · historial", "publica CIStatusChanged", "consume cmdb-changes-q"]),
        ("ms-incidents", ["incidentes · SLA · comentarios", "consume incidents-ci-q,",
                          "incidents-problem-q, incidents-kedb-q"]),
        ("ms-problems", ["problemas · errores conocidos (KEDB)", "consume problems-incidents-q,",
                         "problems-changes-q"]),
        ("ms-changes", ["RFC · aprobación CAB · calendario", "publica ChangeSubmitted / Approved /",
                        "Rejected / Implemented"]),
        ("ms-requests", ["catálogo con form_schema", "solicitudes y aprobaciones", "publica Request*"]),
    ]
    for i, (title, lines) in enumerate(specs):
        col, row = i % 2, i // 2
        component(p, 625 + col * 345, 230 + row * 185, 320, 150, title, lines, C["compute"][0])
    component(p, 625, 805, 665, 105, "Lambda Layer common",
              ["pg8000 1.31 · scramp 1.4.5 · PyJWT", "common.db: conexión SSL + SET search_path = schema del tenant",
               "common.events: publish(eventType, tenantId, data)"], C["compute"][0])

    # ---------------------------------------------------------------- RDS
    rds = group(p, 1370, 150, 540, 600, "Amazon RDS · PostgreSQL 16",
                "instancia única servidesk-dev · db.t3.micro · SSL obligatorio", color=C["db"][0], fill="#F8F9FE",
                res="rds")
    for i, key in enumerate(["identity", "cmdb", "incidents", "problems", "changes", "requests"]):
        p.vertex(1395, 222 + i * 78, 490, 66,
                 f'<b style="font-size:13px;color:{INK}">db_{key}</b>'
                 f'<span style="font-size:11px;color:{MUTED}">  ·  dueño: ms-{key}</span><br>'
                 f'<span style="font-size:11px;color:#3B48CC">tenant_andina │ tenant_pacifico │ tenant_unitec</span>'
                 + ('<span style="font-size:11px;color:#3B48CC"> │ public.tenants</span>' if key == "identity" else ""),
                 f"rounded=1;arcSize=8;html=1;whiteSpace=wrap;fontFamily={FONT};strokeColor=#3B48CC;"
                 f"fillColor=#EEF0FC;strokeWidth=2;align=left;verticalAlign=middle;spacingLeft=12;")
    text(p, 1395, 692, 500, 50, "Patrón 2 de multi-tenancy: una base por microservicio y un schema por tenant · "
                                "30 000 registros por microservicio (10 000 por tenant)", 11, color="#3B48CC")

    # ---------------------------------------------------------------- columna derecha
    s3seed = service(p, 1960, 160, 380, 120, "Amazon S3 · seed",
                     ["servidesk-seed-dev-<cuenta>", "seed/<servicio>/<tenant>/*.csv.gz + manifest"],
                     "storage", "s3")
    seedl = service(p, 1960, 330, 380, 120, "Lambda seedLoader (stack infra)",
                    ["S3 → gzip → COPY FROM STDIN (SSL)", "carga idempotente por servicio y tenant"],
                    "compute", "lambda")
    s3other = service(p, 1960, 500, 380, 108, "Amazon S3 · attachments / exports",
                      ["servidesk-attachments-dev-<cuenta> (CORS)", "servidesk-exports-dev-<cuenta> (7 días)"],
                      "storage", "s3")
    cw = service(p, 1960, 650, 380, 108, "Amazon CloudWatch Logs",
                 ["/aws/lambda/servidesk-* · una línea REPORT", "por invocación · logs de los consumidores"],
                 "mgmt", "cloudwatch")
    cfn = service(p, 1960, 1040, 380, 150, "AWS CloudFormation",
                  ["7 stacks: servidesk-infra-dev +", "identity · cmdb · incidents ·", "problems · changes · requests",
                   "Serverless Framework v3 + compose"], "mgmt", "cloudformation")
    iam = service(p, 1960, 1230, 380, 108, "AWS IAM · LabRole",
                  ["rol de ejecución de todas las Lambdas", "(AWS Academy no permite crear roles)"], "security",
                  "role")

    # ---------------------------------------------------------------- mensajería
    eda = group(p, 600, 1030, 1310, 480, "Mensajería basada en eventos (EDA)",
                "Amazon SNS (fan-out con FilterPolicy por eventType) → Amazon SQS: una cola por consumidor con su DLQ "
                "(maxReceiveCount 3) · ReportBatchItemFailures · idempotencia con processed_events",
                color=C["appint"][0], fill="#FFF8FB", dashed=True, res="sqs")
    sns = service(p, 625, 1120, 290, 160, "Amazon SNS",
                  ["tópico servidesk-itsm-events-dev", "sobre: eventId · eventType ·", "tenantId · source · data",
                   "suscripciones con FilterPolicy"], "appint", "sns")
    queues = [
        ("identity-notify-q", "12 tipos de evento → notificaciones"),
        ("cmdb-changes-q", "ChangeImplemented → versión del CI"),
        ("incidents-ci-q", "CIStatusChanged (down) → incidente P2"),
        ("incidents-problem-q", "ProblemIncidentsLinked → problem_id"),
        ("incidents-kedb-q", "KnownErrorPublished → workaround"),
        ("problems-incidents-q", "IncidentCreated → 3 en 24 h = problema"),
        ("problems-changes-q", "ChangeImplemented → cierra el problema"),
    ]
    first_q = None
    for i, (qname, what) in enumerate(queues):
        col, row = i % 2, i // 2
        qx, qy = 975 + col * 465, 1115 + row * 92
        q = p.vertex(qx, qy, 440, 78,
                     f'<b style="font-size:12px;color:{INK}">{qname}</b>'
                     f'<span style="font-size:11px;color:{MUTED}">  + DLQ</span><br>'
                     f'<span style="font-size:11px;color:{MUTED}">{html.escape(what)}</span>',
                     f"rounded=1;arcSize=8;html=1;whiteSpace=wrap;fontFamily={FONT};strokeColor={C['appint'][0]};"
                     f"fillColor=#FFFFFF;strokeWidth=2;align=left;verticalAlign=middle;spacingLeft=50;")
        icon(p, qx + 10, qy + 23, "sqs", C["appint"][0], 30)
        first_q = first_q or q
    text(p, 1440, 1400, 450, 60, "<b>7 colas + 7 DLQ = 14 colas SQS</b><br>"
                                 "servidesk-&lt;servicio&gt;-&lt;nombre&gt;-q-dev / -dlq-dev", 11, color=C["appint"][0])

    # ---------------------------------------------------------------- flujos
    # tráfico de usuario (negro)
    arrow(p, user, amplify, "HTTPS", exit=(1, 0.5), entry=(0, 0.5))
    arrow(p, amplify, apigw, "llamadas REST (HTTPS)\nAuthorization: Bearer JWT", exit=(0.5, 1), entry=(0.5, 0))
    arrow(p, apigw, lam, "invoca", exit=(1, 0.35), entry=(0, 0.3))
    # autorización (morado punteado)
    arrow(p, apigw, authz, "valida el token", color=C["net"][0], dashed=True, exit=(0.5, 1), entry=(0.5, 0),
          font_color=C["net"][0])
    # SQL (azul)
    arrow(p, lam, rds, "", color=C["db"][0], exit=(1, 0.3), entry=(0, 0.4), font_color=C["db"][0])
    # eventos: publicar (naranja) y consumir (rosado punteado)
    arrow(p, lam, sns, "publish", color=C["compute"][0], exit=(0, 0.97), entry=(0, 0.5),
          font_color=C["compute"][0], points=[(578, 916), (578, 1200)])
    arrow(p, sns, first_q, "fan-out", color=C["appint"][0], exit=(1, 0.2), entry=(0, 0.5),
          font_color=C["appint"][0])
    arrow(p, eda, lam, "event source mapping → consumidores (lotes de 10)", color=C["appint"][0], dashed=True,
          exit=(0.62, 0), entry=(0.83, 1), font_color=C["appint"][0])
    # seed (verde)
    arrow(p, dev, s3seed, "seed/load.py upload (boto3)", color=C["storage"][0], dashed=True, exit=(1, 0.5),
          entry=(0.5, 0), font_color=C["storage"][0], points=[(264, 703), (264, 138), (2150, 138)])
    arrow(p, s3seed, seedl, "get_object (stream)", color=C["storage"][0], exit=(0.5, 1), entry=(0.5, 0),
          font_color=C["storage"][0])
    arrow(p, seedl, rds, "COPY FROM STDIN", color=C["storage"][0], exit=(0, 0.5), entry=(1, 0.33),
          font_color=C["storage"][0])
    # observabilidad
    arrow(p, lam, cw, "logs", color="#7D8998", dashed=True, exit=(1, 0.95), entry=(0, 0.5), font_color=MUTED,
          points=[(1340, 900), (1340, 785), (1935, 785), (1935, 704)])
    # despliegue (gris punteado)
    arrow(p, dev, amplify, "", color="#7D8998", dashed=True, exit=(1, 0.2),
          entry=(0, 0.82), font_color=MUTED, points=[(236, 665), (236, 255)])
    arrow(p, dev, cfn, "npm run deploy → serverless compose → CloudFormation", color="#7D8998", dashed=True,
          exit=(1, 0.85), entry=(0, 0.5), font_color=MUTED,
          points=[(278, 747), (278, 1545), (1935, 1545), (1935, 1115)])

    # ---------------------------------------------------------------- leyenda
    group(p, 30, 1100, 205, 330, "Leyenda", color="#7D8998")
    items = [(INK, False, "Tráfico de usuarios"), (C["net"][0], True, "Autorización JWT"),
             (C["db"][0], False, "SQL a RDS (SSL)"), (C["compute"][0], False, "Publicar evento en SNS"),
             (C["appint"][0], True, "SQS → Lambda consumidora"), (C["storage"][0], False, "Carga de datos (seed)"),
             ("#7D8998", True, "Despliegue / logs")]
    for i, (col, dash, label) in enumerate(items):
        y = 1148 + i * 38
        a = p.vertex(45, y, 1, 1, "", "text;strokeColor=none;fillColor=none;")
        b = p.vertex(95, y, 1, 1, "", "text;strokeColor=none;fillColor=none;")
        p.edge(a, b, "", f"endArrow=block;endFill=1;html=1;strokeColor={col};strokeWidth=2;"
                         f"dashed={1 if dash else 0};dashPattern=6 4;")
        text(p, 103, y - 10, 130, 22, label, 11)
    return p


# ------------------------------------------------------------------ 2. E/R por microservicio

ROW_H = 30
HEAD_H = 52


def table(p, x, y, name, subtitle, cols, color, width=400):
    """Tabla E/R. cols = [(nombre, tipo, clave)]; devuelve (id, alto, índice por columna)."""
    h = HEAD_H + ROW_H * len(cols) + 4
    rows = []
    for i, (cname, ctype, key) in enumerate(cols):
        bg = "#F5F7FA" if i % 2 == 0 else "#FFFFFF"
        weight = "bold" if key.startswith("PK") else "normal"
        rows.append(
            f'<tr style="background:{bg};height:{ROW_H}px">'
            f'<td style="padding-left:14px;width:40%;text-align:left;font-weight:{weight}">{html.escape(cname)}</td>'
            f'<td style="color:{MUTED};width:38%;text-align:left">{html.escape(ctype)}</td>'
            f'<td style="text-align:right;padding-right:14px;color:{color};font-weight:bold">{html.escape(key)}</td>'
            f'</tr>')
    label = (f'<div style="background:{color};color:#FFFFFF;height:{HEAD_H}px;text-align:center;'
             f'border-radius:8px 8px 0 0;box-sizing:border-box;padding-top:7px">'
             f'<b style="font-size:16px">{html.escape(name)}</b><br><span style="font-size:11px">'
             f'{html.escape(subtitle)}</span></div>'
             f'<table style="width:100%;border-collapse:collapse;font-size:12px;color:{INK}">{"".join(rows)}</table>')
    cid = p.vertex(x, y, width, h, label,
                   f"rounded=1;arcSize=8;absoluteArcSize=1;html=1;whiteSpace=wrap;overflow=fill;spacing=0;"
                   f"fontFamily={FONT};strokeColor={color};fillColor=#FFFFFF;strokeWidth=1.5;align=left;"
                   f"verticalAlign=top;")
    idx = {c[0]: i for i, c in enumerate(cols)}
    return cid, h, idx


def row_y(h, i):
    return round((HEAD_H + ROW_H * i + ROW_H / 2) / h, 4)


def row_abs(p, cid, i):
    x, y, w, h = p.geom[cid]
    return y + HEAD_H + ROW_H * i + ROW_H / 2


def fk(p, child, child_h, child_row, parent, parent_h, parent_row, color, side=("right", "left"),
       many="ERmany", one="ERmandOne", points=None):
    """FK real dentro de la misma base: pata de gallo en el hijo, raya en el padre (fila de la PK)."""
    ex = 1 if side[0] == "right" else 0
    en = 0 if side[1] == "left" else 1
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;fontFamily={FONT};fontSize=11;strokeColor={color};"
             f"strokeWidth=1.8;startArrow={many};startFill=0;endArrow={one};endFill=0;"
             f"exitX={ex};exitY={row_y(child_h, child_row)};exitDx=0;exitDy=0;"
             f"entryX={en};entryY={row_y(parent_h, parent_row)};entryDx=0;entryDy=0;startSize=12;endSize=12;")
    return p.edge(child, parent, "", style, points)


def ext_ref(p, x, y, title, owner, fields, width=300):
    """Tabla de otro microservicio (no existe en esta base): caja gris punteada."""
    return p.vertex(x, y, width, 54,
                    f'<b style="font-size:13px;color:#4A5563">{html.escape(title)}</b>'
                    f'<span style="font-size:11px;color:{MUTED}"> · {html.escape(owner)}</span><br>'
                    f'<span style="font-size:11px;color:{MUTED}">id ← {html.escape(fields)}</span>',
                    f"rounded=1;arcSize=10;html=1;whiteSpace=wrap;fontFamily={FONT};strokeColor=#9AA4B2;"
                    f"fillColor=#F7F8FA;strokeWidth=1.5;dashed=1;dashPattern=6 4;align=left;spacingLeft=12;"
                    f"verticalAlign=middle;")


def logical(p, src, row, ext, xv, side="right"):
    """Referencia lógica a otro servicio: sale de la fila de la columna y entra por la izquierda de la caja
    externa, con su propia vertical en xv (así ninguna línea comparte tramo con otra)."""
    sx, sy, sw, sh = p.geom[src]
    ex, ey, ew, eh = p.geom[ext]
    ry = row_abs(p, src, row)
    cy = ey + eh / 2
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#8A94A3;strokeWidth=1.5;dashed=1;"
             f"dashPattern=6 4;startArrow=ERzeroToMany;startFill=0;endArrow=ERmandOne;endFill=0;startSize=12;"
             f"endSize=12;exitX={1 if side == 'right' else 0};exitY={row_y(sh, row)};exitDx=0;exitDy=0;"
             f"entryX=0;entryY=0.5;entryDx=0;entryDy=0;")
    return p.edge(src, ext, "", style, [(xv, ry), (xv, cy)])


def code_box(p, x, y, w, h, title, code):
    lines = html.escape(code).replace("\n", "<br>").replace("  ", "&nbsp;&nbsp;")
    return p.vertex(x, y, w, h,
                    f'<div style="font-family:Courier New;font-size:12px;color:#3D4752;text-align:left">'
                    f'<span style="color:#8A94A3">// {html.escape(title)}</span><br>{lines}</div>',
                    f"rounded=1;arcSize=4;absoluteArcSize=1;html=1;whiteSpace=wrap;strokeColor=#C9CED6;"
                    f"fillColor=#FFFFFF;strokeWidth=1.2;align=left;verticalAlign=top;spacing=14;")


def note(p, x, y, w, h, value, color="#9C8A2E", fill="#FFF8E1"):
    return p.vertex(x, y, w, h, value,
                    f"rounded=1;arcSize=6;html=1;whiteSpace=wrap;fontFamily={FONT};fontSize=11;fontColor={INK};"
                    f"strokeColor={color};fillColor={fill};strokeWidth=1.5;align=left;verticalAlign=top;spacing=12;")


def tech_note(p, x, y, w, h, body):
    return note(p, x, y, w, h, "<b>Tablas técnicas (no se dibujan como entidades)</b><br>" + body)


def legend(p, y, width, relations):
    group(p, 40, y, width - 80, 150, "Cómo leerlo", color="#9AA4B2")
    a = p.vertex(70, y + 62, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    b = p.vertex(190, y + 62, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    p.edge(a, b, "", "endArrow=ERmandOne;startArrow=ERmany;html=1;strokeColor=#232F3E;strokeWidth=1.8;"
                     "startSize=12;endSize=12;endFill=0;startFill=0;")
    text(p, 210, y + 50, 620, 30, "FK real dentro de la misma base: <b>muchos</b> (pata de gallo) a <b>uno</b> (raya)",
         12)
    a = p.vertex(70, y + 108, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    b = p.vertex(190, y + 108, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    p.edge(a, b, "", "endArrow=ERmandOne;startArrow=ERzeroToMany;html=1;strokeColor=#8A94A3;strokeWidth=1.5;"
                     "dashed=1;dashPattern=6 4;startSize=12;endSize=12;endFill=0;startFill=0;")
    text(p, 210, y + 90, 640, 46, "Referencia lógica a otro microservicio (caja gris): guarda el UUID, <b>no hay "
                                  "FK</b> entre bases; la consistencia la dan la API y los eventos", 12)
    text(p, 880, y + 48, width - 960, 96,
         "<b>PK</b> clave primaria · <b>FK</b> clave foránea · <b>UQ</b> valor único · <b>ref</b> referencia "
         "lógica · <b>enum</b> valores fijos (CHECK) · <b>json</b> columna JSONB: se muestra su estructura, no es "
         "una tabla<br>" + relations, 12)


def er_page(name, n_title, db, owner, color, tint, box_h, build, width=1960, below=0):
    """Página E/R: título, contenedor punteado de la base (alto box_h) y leyenda debajo."""
    p = Page(name, width, 100 + box_h + below + 200)
    text(p, 40, 22, 1500, 34, f"ServiDesk — Diagrama E/R · {n_title}", 24, True)
    text(p, 40, 58, 1800, 22, "Mismas tablas en cada schema de tenant (tenant_andina · tenant_pacifico · "
                              "tenant_unitec): patrón 2 de multi-tenancy en la instancia única de RDS.", 13,
         color=MUTED)
    group(p, 30, 100, 1340, box_h, f"PostgreSQL 16 · {db}", f"dueño: {owner}", color=color, fill=tint,
          dashed=True, title_size=17)
    relations = build(p)
    legend(p, 100 + box_h + below + 30, width, relations)
    return p


OWNER = "(Python 3.12 · AWS Lambda · pg8000)"


def er_identity():
    color, tint = "#33658A", "#F1F5F9"

    def build(p):
        users, uh, ui = table(p, 70, 190, "users", "tabla", [
            ("id", "UUID", "PK"), ("email", "VARCHAR(254)", "UQ"), ("full_name", "VARCHAR(150)", ""),
            ("role", "VARCHAR(20)", "enum"), ("password_hash", "VARCHAR(255)", ""), ("active", "BOOLEAN", ""),
            ("created_at", "TIMESTAMP", "")], color)
        members, mh, mi = table(p, 560, 190, "team_members", "tabla (N:M users ↔ teams)", [
            ("team_id", "UUID", "PK·FK"), ("user_id", "UUID", "PK·FK"), ("is_lead", "BOOLEAN", "")], color, 360)
        teams, th, ti = table(p, 960, 190, "teams", "tabla", [
            ("id", "UUID", "PK"), ("name", "VARCHAR(100)", "UQ"), ("description", "VARCHAR(255)", ""),
            ("created_at", "TIMESTAMP", "")], color, 380)
        notif, nh, ni = table(p, 70, 520, "notifications", "tabla (la llena el consumidor identity-notify-q)", [
            ("id", "UUID", "PK"), ("user_id", "UUID", "FK"), ("event_type", "VARCHAR(60)", ""),
            ("title", "VARCHAR(200)", ""), ("body", "TEXT", ""), ("resource_type", "VARCHAR(20)", "enum"),
            ("resource_id", "UUID", "ref"), ("read", "BOOLEAN", ""), ("created_at", "TIMESTAMP", "")], color)
        tenants, _, _ = table(p, 960, 520, "public.tenants", "tabla global (schema public de db_identity)", [
            ("code", "VARCHAR(30)", "PK"), ("schema_name", "VARCHAR(63)", "UQ"), ("name", "VARCHAR(150)", ""),
            ("active", "BOOLEAN", ""), ("created_at", "TIMESTAMP", "")], "#4A6A86", 380)
        fk(p, members, mh, mi["user_id"], users, uh, ui["id"], color, side=("left", "right"))
        fk(p, members, mh, mi["team_id"], teams, th, ti["id"], color, side=("right", "left"))
        fk(p, notif, nh, ni["user_id"], users, uh, ui["id"], color, side=("left", "left"),
           points=[(48, row_abs(p, notif, ni["user_id"])), (48, row_abs(p, users, ui["id"]))])
        ext = ext_ref(p, 1440, row_abs(p, notif, ni["resource_id"]) - 27, "recurso de otro servicio",
                      "incidents · problems · changes · requests · CI", "resource_type + resource_id", 430)
        logical(p, notif, ni["resource_id"], ext, 1400)
        tech_note(p, 1440, 190, 430, 74, "<b>processed_events</b>(event_id PK, event_type, processed_at): "
                                         "idempotencia del consumidor SQS; no se relaciona con ninguna tabla.")
        note(p, 1440, 285, 430, 92,
             "<b>role</b>: admin · agent · customer<br><b>password_hash</b>: pbkdf2_sha256$310000$salt$hash "
             "(nunca lo devuelve la API)<br><b>email</b> se guarda en minúsculas (CHECK).", color, "#EEF3F8")
        note(p, 1440, 520, 430, 110,
             "<b>public.tenants</b> resuelve el login: tenant_code → schema_name (tenant_andina…). No tiene FK: "
             "cada fila corresponde a un <b>schema</b> completo con users, teams, team_members y notifications.",
             "#4A6A86", "#EEF3F8")
        return ("Relaciones: 1 user → 0..N notifications · users N:M teams mediante team_members · "
                "1 tenant → 1 schema")

    return er_page("E-R identity", "ms-identity (db_identity)", "db_identity", f"ms-identity {OWNER}",
                   color, tint, 790, build)


def er_cmdb():
    color, tint = "#0F7C8C", "#EEF7F8"

    def build(p):
        types, th, ti = table(p, 70, 200, "ci_types", "tabla (6 tipos base)", [
            ("id", "SERIAL", "PK"), ("name", "VARCHAR(60)", "UQ")], color, 330)
        ci, ch, cii = table(p, 520, 200, "configuration_items", "tabla", [
            ("id", "UUID", "PK"), ("type_id", "INT", "FK"), ("name", "VARCHAR(150)", ""),
            ("status", "VARCHAR(20)", "enum"), ("environment", "VARCHAR(10)", "enum"),
            ("version", "VARCHAR(50)", ""), ("owner_team_id", "UUID", "ref"), ("attributes", "JSONB", "json"),
            ("created_at", "TIMESTAMP", ""), ("updated_at", "TIMESTAMP", "")], color, 400)
        rel, rh, ri = table(p, 70, 620, "ci_relations", "tabla (grafo de dependencias entre CIs)", [
            ("id", "UUID", "PK"), ("source_ci_id", "UUID", "FK"), ("target_ci_id", "UUID", "FK"),
            ("relation", "VARCHAR(20)", "enum"), ("created_at", "TIMESTAMP", "")], color, 380)
        hist, hh, hi = table(p, 960, 620, "ci_history", "tabla (auditoría por campo)", [
            ("id", "UUID", "PK"), ("ci_id", "UUID", "FK"), ("field", "VARCHAR(50)", ""),
            ("old_value", "TEXT", ""), ("new_value", "TEXT", ""), ("actor_id", "UUID", "ref"),
            ("source", "VARCHAR(30)", ""), ("change_id", "UUID", "ref"), ("changed_at", "TIMESTAMP", "")],
            color, 380)
        ci_id_y = row_abs(p, ci, cii["id"])
        fk(p, ci, ch, cii["type_id"], types, th, ti["id"], color, side=("left", "right"))
        fk(p, rel, rh, ri["source_ci_id"], ci, ch, cii["id"], color, side=("right", "left"),
           points=[(470, row_abs(p, rel, ri["source_ci_id"])), (470, ci_id_y)])
        fk(p, rel, rh, ri["target_ci_id"], ci, ch, cii["id"], color, side=("right", "left"),
           points=[(490, row_abs(p, rel, ri["target_ci_id"])), (490, ci_id_y)])
        fk(p, hist, hh, hi["ci_id"], ci, ch, cii["id"], color, side=("left", "right"),
           points=[(940, row_abs(p, hist, hi["ci_id"])), (940, ci_id_y)])
        code_box(p, 1440, 190, 430, 200, "attributes · JSONB (estructura libre por tipo de CI)",
                 '{\n  "sede": "Data center Lima",\n  "ip": "10.20.1.15",\n  "os": "Ubuntu 22.04",\n'
                 '  "motor": "PostgreSQL 16"\n}\n// status: operational | degraded | down | retired\n'
                 '// environment: prod | qa | dev')
        e_team = ext_ref(p, 1440, row_abs(p, ci, cii["owner_team_id"]) - 27, "identity.teams", "ms-identity",
                         "owner_team_id")
        e_user = ext_ref(p, 1440, row_abs(p, hist, hi["actor_id"]) - 27, "identity.users", "ms-identity",
                         "actor_id")
        e_chg = ext_ref(p, 1440, row_abs(p, hist, hi["change_id"]) - 27, "changes.changes", "ms-changes",
                        "change_id (ChangeImplemented)")
        logical(p, ci, cii["owner_team_id"], e_team, 1400)
        logical(p, hist, hi["actor_id"], e_user, 1400)
        logical(p, hist, hi["change_id"], e_chg, 1400)
        tech_note(p, 1440, 525, 430, 92, "<b>processed_events</b>: idempotencia de cmdb-changes-q.<br>"
                                         "<b>Baja lógica</b>: DELETE /cis/{id} pone status = retired (otros "
                                         "servicios guardan ci_id y no hay FK entre bases).")
        return ("Relaciones: 1 ci_type → N CIs · 1 CI → N relaciones como origen y N como destino "
                "(depends_on · runs_on · connects_to) · 1 CI → N cambios en ci_history")

    return er_page("E-R cmdb", "ms-cmdb (db_cmdb)", "db_cmdb", f"ms-cmdb {OWNER}", color, tint, 880, build)


def er_incidents():
    color, tint = "#B4532A", "#FBF1EC"

    def build(p):
        sla, sh, si = table(p, 70, 200, "sla_policies", "tabla (P1 4 h · P2 8 h · P3 24 h · P4 72 h)", [
            ("id", "SERIAL", "PK"), ("priority", "VARCHAR(2)", "enum"), ("response_minutes", "INT", ""),
            ("resolution_minutes", "INT", "")], color, 380)
        inc, ih, ii = table(p, 520, 200, "incidents", "tabla", [
            ("id", "UUID", "PK"), ("key", "VARCHAR(20)", "UQ"), ("title", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("status", "VARCHAR(20)", "enum"), ("impact", "VARCHAR(10)", "enum"),
            ("urgency", "VARCHAR(10)", "enum"), ("priority", "VARCHAR(2)", "enum"), ("sla_policy_id", "INT", "FK"),
            ("sla_due_at", "TIMESTAMP", ""), ("sla_breached", "BOOLEAN", ""), ("reporter_id", "UUID", "ref"),
            ("assignee_id", "UUID", "ref"), ("team_id", "UUID", "ref"), ("ci_id", "UUID", "ref"),
            ("problem_id", "UUID", "ref"), ("channel", "VARCHAR(10)", "enum"), ("created_at", "TIMESTAMP", ""),
            ("resolved_at", "TIMESTAMP", "")], color, 400)
        com, coh, coi = table(p, 70, 620, "incident_comments", "tabla", [
            ("id", "UUID", "PK"), ("incident_id", "UUID", "FK"), ("author_id", "UUID", "ref"),
            ("body", "TEXT", ""), ("internal", "BOOLEAN", ""), ("created_at", "TIMESTAMP", "")], color, 380)
        evs, eh, ei = table(p, 960, 790, "incident_events", "tabla (historial de estados)", [
            ("id", "UUID", "PK"), ("incident_id", "UUID", "FK"), ("actor_id", "UUID", "ref"),
            ("old_status", "VARCHAR(20)", ""), ("new_status", "VARCHAR(20)", ""), ("created_at", "TIMESTAMP", "")],
            color, 380)
        inc_id_y = row_abs(p, inc, ii["id"])
        fk(p, inc, ih, ii["sla_policy_id"], sla, sh, si["id"], color, side=("left", "right"),
           points=[(480, row_abs(p, inc, ii["sla_policy_id"])), (480, row_abs(p, sla, si["id"]))])
        fk(p, com, coh, coi["incident_id"], inc, ih, ii["id"], color, side=("right", "left"),
           points=[(500, row_abs(p, com, coi["incident_id"])), (500, inc_id_y)])
        fk(p, evs, eh, ei["incident_id"], inc, ih, ii["id"], color, side=("left", "right"),
           points=[(940, row_abs(p, evs, ei["incident_id"])), (940, inc_id_y)])
        e_user = ext_ref(p, 1440, 440, "identity.users", "ms-identity", "reporter_id · assignee_id · author_id")
        e_team = ext_ref(p, 1440, 530, "identity.teams", "ms-identity", "team_id")
        e_ci = ext_ref(p, 1440, 620, "cmdb.configuration_items", "ms-cmdb", "ci_id")
        e_prb = ext_ref(p, 1440, 710, "problems.problems", "ms-problems", "problem_id (incidents-problem-q)")
        logical(p, inc, ii["reporter_id"], e_user, 1385)
        logical(p, inc, ii["team_id"], e_team, 1400)
        logical(p, inc, ii["ci_id"], e_ci, 1415)
        logical(p, inc, ii["problem_id"], e_prb, 1390)
        note(p, 1440, 200, 430, 130,
             "<b>Reglas</b><br>priority = impacto × urgencia (high · medium · low → P1…P4)<br>"
             "sla_due_at = created_at + resolución de la política<br>status: new · in_progress · on_hold · "
             "resolved · closed<br>channel: portal · email · auto (creado por CIStatusChanged)<br>"
             "key: INC-000001… correlativa por tenant", color, tint)
        tech_note(p, 1440, 800, 430, 74, "<b>processed_events</b>: idempotencia de incidents-ci-q, "
                                         "incidents-problem-q e incidents-kedb-q.")
        return ("Relaciones: 1 sla_policy → N incidentes · 1 incidente → 0..N comentarios · 1 incidente → 0..N "
                "cambios de estado · reportante, asignado y autor son usuarios de ms-identity")

    return er_page("E-R incidents", "ms-incidents (db_incidents)", "db_incidents", f"ms-incidents {OWNER}",
                   color, tint, 960, build)


def er_problems():
    color, tint = "#6E4BAA", "#F4F0FA"

    def build(p):
        pinc, pih, pii = table(p, 70, 200, "problem_incidents", "tabla (incidentes vinculados)", [
            ("problem_id", "UUID", "PK·FK"), ("incident_id", "UUID", "PK·ref"), ("created_at", "TIMESTAMP", "")],
            color, 380)
        prb, ph, pi = table(p, 520, 200, "problems", "tabla", [
            ("id", "UUID", "PK"), ("key", "VARCHAR(20)", "UQ"), ("title", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("status", "VARCHAR(20)", "enum"), ("priority", "VARCHAR(2)", "enum"),
            ("root_cause", "TEXT", ""), ("ci_id", "UUID", "ref"), ("owner_id", "UUID", "ref"),
            ("fix_change_id", "UUID", "ref"), ("created_at", "TIMESTAMP", "")], color, 400)
        ke, kh, ki = table(p, 70, 470, "known_errors", "tabla (KEDB · 0..1 por problema)", [
            ("id", "UUID", "PK"), ("problem_id", "UUID", "FK·UQ"), ("symptom", "TEXT", ""),
            ("workaround", "TEXT", ""), ("created_at", "TIMESTAMP", "")], color, 380)
        tasks, tah, tai = table(p, 960, 620, "problem_tasks", "tabla", [
            ("id", "UUID", "PK"), ("problem_id", "UUID", "FK"), ("title", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("status", "VARCHAR(20)", "enum"), ("assignee_id", "UUID", "ref"),
            ("created_at", "TIMESTAMP", "")], color, 380)
        prb_id_y = row_abs(p, prb, pi["id"])
        fk(p, pinc, pih, pii["problem_id"], prb, ph, pi["id"], color, side=("right", "left"))
        fk(p, ke, kh, ki["problem_id"], prb, ph, pi["id"], color, side=("right", "left"), many="ERzeroToOne",
           points=[(490, row_abs(p, ke, ki["problem_id"])), (490, prb_id_y)])
        fk(p, tasks, tah, tai["problem_id"], prb, ph, pi["id"], color, side=("left", "right"),
           points=[(940, row_abs(p, tasks, tai["problem_id"])), (940, prb_id_y)])
        e_ci = ext_ref(p, 1440, 420, "cmdb.configuration_items", "ms-cmdb", "ci_id")
        e_user = ext_ref(p, 1440, 500, "identity.users", "ms-identity", "owner_id · assignee_id")
        e_chg = ext_ref(p, 1440, 580, "changes.changes", "ms-changes", "fix_change_id (problems-changes-q)")
        e_inc = ext_ref(p, 70, 990, "incidents.incidents", "ms-incidents", "problem_incidents.incident_id")
        logical(p, prb, pi["ci_id"], e_ci, 1390)
        logical(p, prb, pi["owner_id"], e_user, 1405)
        logical(p, prb, pi["fix_change_id"], e_chg, 1420)
        logical(p, pinc, pii["incident_id"], e_inc, 48, side="left")
        note(p, 1440, 200, 430, 110,
             "<b>Reglas</b><br>status: new · investigating · known_error · resolved · closed<br>"
             "Publicar el error conocido crea la fila en known_errors y pasa el problema a known_error.<br>"
             "3+ incidentes del mismo CI en 24 h crean un problema automático.", color, tint)
        tech_note(p, 1440, 670, 430, 110, "<b>processed_events</b>: idempotencia SQS.<br><b>ci_incident_log</b>"
                                          "(incident_id, ci_id, priority, title, occurred_at): copia local de "
                                          "IncidentCreated para contar la recurrencia; sin FK.")
        return ("Relaciones: 1 problema → 0..N incidentes vinculados · 1 problema → 0..1 error conocido · "
                "1 problema → 0..N tareas · se cierra al implementarse el cambio que lo corrige")

    return er_page("E-R problems", "ms-problems (db_problems)", "db_problems", f"ms-problems {OWNER}",
                   color, tint, 870, build, below=80)


def er_changes():
    color, tint = "#2E7D32", "#F1F8F1"

    def build(p):
        appr, ah, ai = table(p, 70, 200, "change_approvals", "tabla (decisiones CAB)", [
            ("id", "UUID", "PK"), ("change_id", "UUID", "FK"), ("approver_id", "UUID", "ref"),
            ("decision", "VARCHAR(10)", "enum"), ("comment", "VARCHAR(2000)", ""), ("decided_at", "TIMESTAMP", "")],
            color, 380)
        chg, chh, chi = table(p, 520, 200, "changes", "tabla (RFC)", [
            ("id", "UUID", "PK"), ("key", "VARCHAR(20)", "UQ"), ("title", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("type", "VARCHAR(20)", "enum"), ("risk", "VARCHAR(10)", "enum"),
            ("status", "VARCHAR(20)", "enum"), ("rollback_plan", "TEXT", ""), ("planned_start", "TIMESTAMP", ""),
            ("planned_end", "TIMESTAMP", ""), ("requester_id", "UUID", "ref"), ("problem_id", "UUID", "ref"),
            ("created_at", "TIMESTAMP", "")], color, 400)
        cis, cih, cii = table(p, 70, 560, "change_cis", "tabla (CIs afectados)", [
            ("change_id", "UUID", "PK·FK"), ("ci_id", "UUID", "PK·ref"), ("new_version", "VARCHAR(50)", "")],
            color, 380)
        tasks, th, ti = table(p, 960, 660, "change_tasks", "tabla", [
            ("id", "UUID", "PK"), ("change_id", "UUID", "FK"), ("title", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("status", "VARCHAR(20)", ""), ("assignee_id", "UUID", "ref"),
            ("created_at", "TIMESTAMP", "")], color, 380)
        chg_id_y = row_abs(p, chg, chi["id"])
        fk(p, appr, ah, ai["change_id"], chg, chh, chi["id"], color, side=("right", "left"))
        fk(p, cis, cih, cii["change_id"], chg, chh, chi["id"], color, side=("right", "left"),
           points=[(490, row_abs(p, cis, cii["change_id"])), (490, chg_id_y)])
        fk(p, tasks, th, ti["change_id"], chg, chh, chi["id"], color, side=("left", "right"),
           points=[(940, row_abs(p, tasks, ti["change_id"])), (940, chg_id_y)])
        e_user = ext_ref(p, 1440, 500, "identity.users", "ms-identity", "requester_id · approver_id · assignee_id",
                         360)
        e_prb = ext_ref(p, 1440, 580, "problems.problems", "ms-problems", "problem_id")
        e_ci = ext_ref(p, 70, 980, "cmdb.configuration_items", "ms-cmdb", "change_cis.ci_id (+ new_version)", 340)
        logical(p, chg, chi["requester_id"], e_user, 1390)
        logical(p, chg, chi["problem_id"], e_prb, 1405)
        logical(p, cis, cii["ci_id"], e_ci, 48, side="left")
        note(p, 1440, 200, 430, 110,
             "<b>Reglas</b><br>type: standard · normal · emergency (standard se aprueba solo)<br>status: draft → "
             "submitted → approved/rejected → scheduled → implemented/failed<br>planned_end > planned_start "
             "(CHECK) · aprueba un admin distinto del solicitante", color, tint)
        return ("Relaciones: 1 cambio → 0..N decisiones CAB · 1 cambio → 1..N CIs afectados (con su versión nueva) "
                "· 1 cambio → 0..N tareas · al implementarse publica ChangeImplemented")

    return er_page("E-R changes", "ms-changes (db_changes)", "db_changes", f"ms-changes {OWNER}", color, tint,
                   860, build, below=80)


def er_requests():
    color, tint = "#9A5B13", "#FBF4EA"

    def build(p):
        cat, cah, cai = table(p, 70, 200, "catalog_categories", "tabla", [
            ("id", "INT IDENTITY", "PK"), ("name", "VARCHAR(150)", "UQ"), ("description", "TEXT", ""),
            ("created_at", "TIMESTAMP", "")], color, 360)
        item, ih, ii = table(p, 500, 200, "catalog_items", "tabla (servicios del catálogo)", [
            ("id", "UUID", "PK"), ("category_id", "INT", "FK"), ("name", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("form_schema", "JSONB", "json"), ("needs_approval", "BOOLEAN", ""),
            ("sla_hours", "INT", ""), ("active", "BOOLEAN", ""), ("created_at", "TIMESTAMP", "")], color, 380)
        req, rh, ri = table(p, 940, 200, "service_requests", "tabla", [
            ("id", "UUID", "PK"), ("key", "VARCHAR(20)", "UQ"), ("catalog_item_id", "UUID", "FK"),
            ("form_data", "JSONB", "json"), ("status", "VARCHAR(30)", "enum"), ("requester_id", "UUID", "ref"),
            ("assignee_id", "UUID", "ref"), ("created_at", "TIMESTAMP", ""), ("fulfilled_at", "TIMESTAMP", "")],
            color, 400)
        appr, ah, ai = table(p, 500, 600, "request_approvals", "tabla", [
            ("id", "UUID", "PK"), ("request_id", "UUID", "FK"), ("approver_id", "UUID", "ref"),
            ("decision", "VARCHAR(10)", "enum"), ("decided_at", "TIMESTAMP", "")], color, 380)
        tasks, th, ti = table(p, 940, 600, "fulfillment_tasks", "tabla", [
            ("id", "UUID", "PK"), ("request_id", "UUID", "FK"), ("title", "VARCHAR(200)", ""),
            ("description", "TEXT", ""), ("status", "VARCHAR(20)", "enum"), ("assignee_id", "UUID", "ref"),
            ("created_at", "TIMESTAMP", "")], color, 400)
        req_id_y = row_abs(p, req, ri["id"])
        fk(p, item, ih, ii["category_id"], cat, cah, cai["id"], color, side=("left", "right"))
        fk(p, req, rh, ri["catalog_item_id"], item, ih, ii["id"], color, side=("left", "right"))
        fk(p, appr, ah, ai["request_id"], req, rh, ri["id"], color, side=("right", "left"),
           points=[(905, row_abs(p, appr, ai["request_id"])), (905, req_id_y)])
        fk(p, tasks, th, ti["request_id"], req, rh, ri["id"], color, side=("right", "right"),
           points=[(1362, row_abs(p, tasks, ti["request_id"])), (1362, req_id_y)])
        code_box(p, 1440, 200, 430, 320, "form_schema · JSONB (catalog_items)",
                 '{\n  "fields": [\n    { "name": "modelo",\n      "label": "Modelo",\n      "type": "select",\n'
                 '      "required": true,\n      "options": ["Estándar 14\\"", ...] },\n'
                 '    { "name": "justificacion",\n      "type": "textarea",\n      "required": true }\n  ]\n}\n'
                 '// type: text | textarea | number | date | select | boolean')
        code_box(p, 1440, 540, 430, 180, "form_data · JSONB (service_requests)",
                 '{\n  "modelo": "Desarrollo 16\\"",\n  "fecha_entrega": "2026-11-28",\n'
                 '  "justificacion": "..."\n}\n// se valida contra el form_schema del ítem (máx. 8 KB)')
        e_user = ext_ref(p, 1440, 760, "identity.users", "ms-identity", "requester_id · assignee_id · approver_id",
                         430)
        logical(p, req, ri["requester_id"], e_user, 1400)
        note(p, 70, 600, 380, 120,
             "<b>Reglas</b><br>Al crear: pending_approval si needs_approval, si no submitted.<br>"
             "status: submitted · pending_approval · approved · rejected · in_fulfillment · fulfilled<br>"
             "key: REQ-000001… por tenant", color, tint)
        return ("Relaciones: 1 categoría → N ítems · 1 ítem → N solicitudes · 1 solicitud → 0..N aprobaciones y "
                "0..N tareas · form_schema y form_data son JSON dentro de la fila, no tablas aparte")

    return er_page("E-R requests", "ms-requests (db_requests)", "db_requests", f"ms-requests {OWNER}",
                   color, tint, 840, build)


# ------------------------------------------------------------------ exportación


def export(drawio_file, png, page_index):
    cmd = [str(DRAWIO), "-x", "-f", "png", "-s", "2", "-b", "24", "-p", str(page_index), "-o", str(png),
           str(drawio_file)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    print(f"  {png.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-png", action="store_true")
    args = parser.parse_args()

    # La arquitectura vigente (RDS privada) se genera con build_arquitectura_v2.py;
    # architecture() es la versión anterior (RDS pública) y ya no se exporta.
    er = OUT / "servidesk_er.drawio"
    er_pages = [er_identity(), er_cmdb(), er_incidents(), er_problems(), er_changes(), er_requests()]
    save(er_pages, er)
    print(f"  {er.name} ({len(er_pages)} páginas)")

    if args.no_png:
        return
    if not DRAWIO.exists():
        sys.exit("No se encontró draw.io Desktop; usa --no-png y exporta desde la app.")
    for i, name in enumerate(["identity", "cmdb", "incidents", "problems", "changes", "requests"]):
        export(er, OUT / f"{i + 2}_er_{name}.png", i)


if __name__ == "__main__":
    main()
