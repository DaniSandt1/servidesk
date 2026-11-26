"""Arquitectura de solución v2: RDS privada + credenciales en AWS Secrets Manager.

    python docs/diagramas/build_arquitectura_v2.py

Genera docs/diagramas/servidesk_arquitectura_v2.drawio (editable en draw.io / app.diagrams.net).
Cambios respecto a la v1:
  * RDS en 2 subredes privadas propias (sin ruta a internet), PubliclyAccessible = false y
    SG :5432 solo desde el SG de las Lambdas (antes: subred pública y 0.0.0.0/0).
  * Las Lambdas que usan la BD (6 microservicios + seedLoader) corren dentro de la VPC.
  * Las credenciales de la BD salen de AWS Secrets Manager (DB_SECRET_ARN), no de variables de entorno.
  * Sin NAT: Secrets Manager y SNS por endpoints de VPC interface, S3 por endpoint gateway.
  * La clave HS256 de los JWT también está en Secrets Manager (JwtSecret).
  * Leyenda de flujos, logs a CloudWatch, servicios regionales dentro de la región e IAM como global.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "servidesk_arquitectura_v2.drawio"
W, H = 1900, 1400
INK, MUTED = "#232F3E", "#5F6B7A"
ORANGE, PINK, RED, GREEN, BLUE, PURPLE = "#ED7100", "#E7157B", "#DD344C", "#7AA116", "#3B48CC", "#8C4FFF"
TEAL, BADGE, SG_RED = "#00A4A6", "#5A6ACF", "#D13212"

cells = []
_n = [0]


def nid():
    _n[0] += 1
    return f"v{_n[0]}"


def vertex(x, y, w, h, value, style):
    cid = nid()
    cells.append(f'<mxCell id="{cid}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" '
                 f'parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def edge(src, dst, label="", color=INK, dashed=False, exit=None, entry=None, points=None, start="none",
         font_color=None):
    cid = nid()
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=11;fontColor={font_color or color};"
             f"strokeColor={color};strokeWidth=1.6;endArrow=block;endFill=1;startArrow={start};startFill=1;"
             f"dashed={1 if dashed else 0};dashPattern=6 4;labelBackgroundColor=#FFFFFF;")
    if exit:
        style += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry:
        style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    pts = ""
    if points:
        pts = '<Array as="points">' + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + "</Array>"
    cells.append(f'<mxCell id="{cid}" value="{escape(label.replace(chr(10), "<br>"), {chr(34): "&quot;"})}" '
                 f'style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
                 f'<mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>')
    return cid


def label_html(title, lines, color=MUTED, size=11):
    out = f"<b>{escape(title)}</b>"
    if lines:
        out += f'<br><span style="font-size:{size}px;color:{color}">' + "<br>".join(lines) + "</span>"
    return out


def icon(x, y, res, color, title, lines=(), size=60, side="bottom", shape="resourceIcon"):
    """Ícono AWS con su texto debajo (side='bottom') o a la derecha (side='right')."""
    if side == "bottom":
        pos = "verticalLabelPosition=bottom;verticalAlign=top;align=center;labelPosition=center;"
    else:
        pos = "verticalLabelPosition=middle;verticalAlign=middle;align=left;labelPosition=right;spacingLeft=6;"
    shape_style = (f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};" if shape == "resourceIcon"
                   else f"shape=mxgraph.aws4.{res};")
    return vertex(x, y, size, size, label_html(title, lines),
                  f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={color};"
                  f"strokeColor=#ffffff;dashed=0;html=1;fontSize=12;aspect=fixed;{pos}{shape_style}")


def badge(x, y, n):
    vertex(x, y, 22, 22, f"<b>{n}</b>",
           f"rounded=1;arcSize=12;html=1;fillColor={BADGE};strokeColor=none;fontColor=#FFFFFF;fontSize=11;")


def aws_group(x, y, w, h, title, gr_icon, stroke, fill="none", font=None, dashed=False):
    return vertex(x, y, w, h, title,
                  f"points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;"
                  f"container=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;"
                  f"grIcon=mxgraph.aws4.{gr_icon};strokeColor={stroke};fillColor={fill};verticalAlign=top;"
                  f"align=left;spacingLeft=30;fontColor={font or stroke};dashed={1 if dashed else 0};")


def box(x, y, w, h, title, stroke, fill="none", dashed=True, font=None, size=13, bold=True, valign="top",
        align="left"):
    return vertex(x, y, w, h, title,
                  f"rounded=0;html=1;whiteSpace=wrap;fontSize={size};fontStyle={1 if bold else 0};"
                  f"strokeColor={stroke};fillColor={fill};dashed={1 if dashed else 0};dashPattern=8 4;"
                  f"strokeWidth=1.5;verticalAlign={valign};align={align};spacingLeft=10;spacingTop=4;"
                  f"fontColor={font or stroke};")


def text(x, y, w, h, value, size=11, color=MUTED, align="center", italic=False):
    return vertex(x, y, w, h, value,
                  f"text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;fontSize={size};"
                  f"fontColor={color};align={align};verticalAlign=top;fontStyle={2 if italic else 0};")


def endpoint(x, y, kind, service, detail):
    cid = vertex(x, y, 230, 110,
                 f'<b style="color:{INK}">VPC endpoint · {kind}</b><br>'
                 f'<span style="font-size:12px;color:{INK}">{service}</span><br>'
                 f'<span style="font-size:10px;color:{MUTED}">{detail}</span>',
                 f"rounded=1;arcSize=6;html=1;whiteSpace=wrap;fontSize=12;strokeColor={PURPLE};fillColor=#FFFFFF;"
                 f"strokeWidth=1.5;align=left;verticalAlign=middle;spacingLeft=62;")
    icon(x + 10, y + 32, "endpoints", PURPLE, "", size=44)
    return cid


# ------------------------------------------------------------------ contenedores
aws_group(150, 20, 1730, 1365, "AWS Cloud", "group_aws_cloud_alt", INK)
aws_group(185, 60, 1680, 1195, "Region – us-east-1 (N. Virginia)", "group_region", "#147EBA", dashed=True)
aws_group(565, 95, 880, 1125, "Default VPC · 172.31.0.0/16", "group_vpc2", PURPLE)
aws_group(580, 135, 850, 1070,
          "Subredes privadas (sin ruta a internet) · 172.31.200.0/24 us-east-1a · 172.31.201.0/24 us-east-1b",
          "group_private_subnet", TEAL, fill="#E6F6F7", font="#147EBA")

# ------------------------------------------------------------------ actores
users = icon(45, 150, "users", INK, "Usuarios", ["(agentes y", "admins de", "cada tenant)"], 56, shape="users")
dev = icon(45, 560, "user", INK, "Equipo dev",
           ["npm run deploy", "invoke migrate ×6", "seed/load.py →", "S3 seed + seedLoader"], 50, shape="user")

# ------------------------------------------------------------------ columna izquierda (fuera de la región)
amplify = icon(212, 120, "amplify", RED, "Amplify Hosting", ["SPA React + Vite", "(despliegue manual)"])
badge(276, 112, 1)
cfn = icon(212, 560, "cloudformation", PINK, "CloudFormation", ["Serverless Framework v3", "compose · 7 stacks"])
badge(276, 552, 11)
cw = icon(212, 770, "cloudwatch_2", PINK, "CloudWatch Logs", ["logs de cada Lambda"])
badge(276, 762, 12)
text(185, 1268, 300, 20, "<b>Servicios globales</b>", 12, INK, align="left")
iam = icon(212, 1295, "role", RED, "IAM · LabRole",
           ["rol de ejecución único de todas las Lambdas (AWS Academy)", "permite leer DbSecret y JwtSecret"],
           side="right")
badge(186, 1287, 13)

# ------------------------------------------------------------------ región, fuera de la VPC (izquierda)
apigw = icon(415, 300, "api_gateway", PINK, "API Gateway", ["HTTP API ×6 · CORS"])
badge(479, 292, 2)
authz = icon(415, 520, "lambda", ORANGE, "Lambda Authorizer",
             ["JWT HS256 · caché 300 s", "fuera de la VPC (no usa la BD)", "clave: JwtSecret"])
badge(479, 512, 3)
layer = vertex(415, 730, 60, 60, label_html("Lambda Layer", ["pg8000 · PyJWT", "db → Secrets Manager",
                                                          "events → endpoint SNS"]),
           f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={ORANGE};strokeColor=#ffffff;"
           f"html=1;fontSize=12;aspect=fixed;verticalLabelPosition=bottom;verticalAlign=top;"
           f"align=center;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.layers;")
badge(479, 722, 5)
box(365, 960, 190, 250,
    "<b>Seguridad de la BD</b><br><span style=\"font-weight:normal;font-size:11px;color:#232F3E\">"
    "• RDS sin IP pública (PubliclyAccessible = false)<br>"
    "• Subredes privadas: sin Internet Gateway ni NAT<br>"
    "• SG :5432 solo desde el SG de las Lambdas<br>"
    "• Contraseña de RDS y clave JWT generadas por CloudFormation en Secrets Manager; ninguna Lambda las recibe en variables de entorno"
    "</span>", RED, fill="#FFFFFF", dashed=False, size=12, bold=False)

# ------------------------------------------------------------------ microservicios (dentro de la VPC)
micro = box(600, 180, 540, 570, "Microservicios Lambda · Python 3.12", ORANGE, fill="#FFF8F1")
badge(1108, 186, 4)
services = [
    ("ms-identity", ["login · usuarios", "equipos · notificaciones"]),
    ("ms-cmdb", ["CIs · relaciones", "tipos · historial"]),
    ("ms-incidents", ["incidentes · SLA", "comentarios"]),
    ("ms-problems", ["problemas · KEDB"]),
    ("ms-changes", ["RFC · aprobación CAB"]),
    ("ms-requests", ["catálogo · solicitudes"]),
]
for i, (name, lines) in enumerate(services):
    col, row = i % 2, i // 2
    icon(700 + col * 250, 225 + row * 150, "lambda", ORANGE, name, lines)
text(610, 670, 520, 75,
     "<i>Handlers HTTP · consumidores SQS · migrate<br>"
     "<b>Lambdas DENTRO de la VPC</b> (2 subredes privadas) · SG sg-lambdas<br>"
     "Secretos: Secrets Manager (DB_SECRET_ARN · JWT_SECRET_ARN), caché por contenedor</i>", 11, INK)

# ------------------------------------------------------------------ RDS y seedLoader
box(600, 790, 390, 330, "SG :5432 solo desde SG de las Lambdas · RDS privada", SG_RED, size=11)
rds = icon(625, 900, "rds", BLUE, "RDS PostgreSQL 16",
           ["servidesk-db-dev · db.t3.micro · 20 GB", "PubliclyAccessible = false · Single-AZ",
            "DB subnet group: subredes privadas", "", "6 bases db_*: identity · cmdb · incidents",
            "problems · changes · requests", "<b>1 schema por tenant (tenant_andina…)</b>",
            "public.tenants en db_identity (login)", "", "contraseña maestra = secreto DbSecret"],
           64, side="right")
badge(603, 892, 8)
seed = icon(1035, 880, "lambda", ORANGE, "seedLoader", ["15 min · 1 GB", "en la VPC", "lee el secreto"])
badge(1099, 872, 10)
text(590, 1135, 830, 40,
     "Tabla de rutas servidesk-private-rt: solo la ruta local de la VPC + prefijo de S3 (endpoint gateway) · "
     "sin Internet Gateway ni NAT", 11, "#147EBA")

# ------------------------------------------------------------------ endpoints de VPC
box(1170, 150, 250, 970, "SG endpoints · :443 solo desde SG de las Lambdas", SG_RED, size=11)
ep_sns = endpoint(1180, 200, "Interface", "Amazon SNS", "sin DNS privado · SNS_ENDPOINT_URL")
ep_sm = endpoint(1180, 640, "Interface", "Secrets Manager", "sin DNS privado · SECRETS_ENDPOINT_URL")
ep_s3 = endpoint(1180, 880, "Gateway", "Amazon S3", "ruta en la tabla privada")

# ------------------------------------------------------------------ columna derecha (servicios regionales)
sns = icon(1500, 170, "sns", PINK, "Amazon SNS", ["servidesk-itsm-events-dev", "attrs: eventType · tenantId"],
           side="right")
badge(1474, 162, 6)
box(1470, 290, 380, 320, "Amazon SQS · una cola + DLQ por suscripción", "#7D8998", font=INK, size=12)
sqs = icon(1500, 340, "sqs", PINK, "Colas SQS ×7", ["FilterPolicy · RawMessageDelivery"], side="right")
badge(1474, 332, 7)
dlq = icon(1500, 450, "sqs", PINK, "DLQ ×7", ["1 por cola (*-dlq-dev)", "retención 14 días"], side="right")
text(1480, 530, 365, 75,
     "identity-notify-q · cmdb-changes-q<br>incidents-ci-q · incidents-problem-q<br>"
     "incidents-kedb-q · problems-incidents-q<br>problems-changes-q", 10, MUTED, align="left")
sm = icon(1500, 665, "secrets_manager", RED, "AWS Secrets Manager",
          ["<b>DbSecret</b>: username · password · host · port", "(contraseña maestra de RDS)",
           "<b>JwtSecret</b>: clave HS256 de los JWT", "ambos generados por CloudFormation"], side="right")
badge(1474, 657, 14)
s3 = icon(1500, 905, "s3", GREEN, "Amazon S3", ["seed: datos ficticios (CSV.gz + manifest)",
                                                 '<span style="color:#9AA4B2">attachments · exports (7 d):</span>',
                                                 '<span style="color:#9AA4B2">provisionados, aún sin uso</span>'],
          side="right")
badge(1474, 897, 9)

# ------------------------------------------------------------------ flujos
edge(users, amplify, "HTTPS", exit=(1, 0.3), entry=(0, 0.5))
edge(users, apigw, "REST/JSON + Bearer JWT (axios)", exit=(1, 0.8), entry=(0, 0.5), points=[(168, 195), (168, 330)])
edge(apigw, micro, "proxy\npayload 2.0", exit=(1, 0.5), entry=(0, 0.263))
edge(apigw, authz, "valida JWT →\ntenant_id, schema,\nrole, user_id", color=PURPLE, dashed=True, start="block",
     exit=(1, 0.9), entry=(1, 0.5), points=[(530, 354), (530, 550)])
edge(layer, micro, "", color=ORANGE, dashed=True, exit=(1, 0.5), entry=(0, 0.95))
edge(micro, ep_sns, "publish()\nlos 6 servicios", color=ORANGE, exit=(1, 0.09), entry=(0, 0.3))
edge(ep_sns, sns, "", color=PINK, exit=(1, 0.5), entry=(0, 0.5))
edge(sns, sqs, "suscripción por cola", color=PINK, exit=(0.5, 1), entry=(0.5, 0))
edge(sqs, dlq, "tras 3 intentos", color=PINK, exit=(0.5, 1), entry=(0.5, 0))
edge(sqs, micro, "consumidores: identity · cmdb · incidents · problems\n(event source mapping, batch 10)",
     color=PINK, dashed=True, exit=(0, 0.5), entry=(1, 0.33))
edge(micro, ep_sm, "GetSecretValue\nDbSecret · JwtSecret", color=RED, exit=(1, 0.86), entry=(0, 0.4))
edge(ep_sm, sm, "", color=RED, exit=(1, 0.5), entry=(0, 0.5))
edge(micro, rds, "pg8000 + SSL :5432\nendpoint privado", color=BLUE, exit=(0.07, 1), entry=(0.5, 0))
edge(seed, rds, "COPY", color=GREEN, exit=(0, 0.5), entry=(0.5, 1), points=[(1000, 910), (1000, 1060), (657, 1060)])
edge(seed, ep_s3, "manifest.json\n+ CSV.gz", color=GREEN, exit=(1, 0.5), entry=(0, 0.5))
edge(ep_s3, s3, "", color=GREEN, exit=(1, 0.5), entry=(0, 0.5))
edge(seed, ep_sm, "", color=RED, dashed=True, exit=(0.5, 0), entry=(0.3, 1))
edge(micro, cw, "logs (todas las Lambdas)", color="#7D8998", dashed=True, exit=(0, 0.91), entry=(1, 0.5),
     points=[(300, 699), (300, 800)], font_color=MUTED)
edge(dev, cfn, "crea", color="#7D8998", dashed=True, exit=(1, 0.5), entry=(0, 0.5))
edge(authz, sm, "GetSecretValue (JwtSecret) · endpoint público: el authorizer está fuera de la VPC", color=RED,
     dashed=True, exit=(0, 0.5), entry=(0, 0.85), points=[(345, 550), (345, 1236), (1460, 1236), (1460, 716)])

legend_items = [(INK, False, "Tráfico de usuarios"), (PURPLE, True, "Autorización JWT"),
                (BLUE, False, "SQL a RDS (SSL)"), (ORANGE, False, "Publicar evento"),
                (PINK, False, "SNS → SQS → DLQ"), (PINK, True, "SQS → consumidora"),
                (RED, False, "Lectura de secretos"), (GREEN, False, "Carga de datos (seed)"),
                ("#7D8998", True, "Despliegue / logs")]
box(1490, 1000, 360, 225, "Leyenda", "#7D8998", fill="#FFFFFF", dashed=False, font=INK, size=12)
for i, (col, dash, name) in enumerate(legend_items):
    lx, ly = 1505 + (i // 5) * 175, 1040 + (i % 5) * 36
    a = vertex(lx, ly, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    b = vertex(lx + 45, ly, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    cells.append(f'<mxCell id="{nid()}" style="endArrow=block;endFill=1;html=1;strokeColor={col};strokeWidth=1.6;'
                 f'dashed={1 if dash else 0};dashPattern=6 4;" edge="1" parent="1" source="{a}" target="{b}">'
                 f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    text(lx + 52, ly - 9, 120, 20, name, 11, INK, align="left")

text(1500, 1385, 370, 18, "<i>ServiDesk · arquitectura de solución v2 (RDS privada + Secrets Manager)</i>",
     10, MUTED, align="right")

OUT.write_text(
    '<mxfile host="drawio" agent="servidesk/build_arquitectura_v2.py"><diagram name="Arquitectura v2" '
    f'id="arquitectura-v2"><mxGraphModel dx="1600" dy="900" grid="0" gridSize="10" guides="1" tooltips="1" '
    f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{W}" pageHeight="{H}" '
    f'background="#FFFFFF" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>", encoding="utf-8")
print(OUT)
