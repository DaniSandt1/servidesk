"""Arquitectura de solución v2: RDS privada + credenciales en AWS Secrets Manager.

    python docs/diagramas/build_arquitectura_v2.py

Genera docs/diagramas/servidesk_arquitectura_v2.drawio (editable en draw.io / app.diagrams.net).
Columnas de izquierda a derecha: usuarios → entrada (Amplify, API Gateway, authorizer) → VPC con
subredes privadas (microservicios, RDS, seedLoader, VPC endpoints) → servicios administrados.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "servidesk_arquitectura_v2.drawio"
W, H = 1600, 1085
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
                  f"strokeWidth=1.5;verticalAlign={valign};align={align};spacingLeft=10;spacingRight=10;spacingTop=4;"
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
aws_group(150, 20, 1430, 1045, "AWS Cloud", "group_aws_cloud_alt", INK)
aws_group(175, 55, 1385, 880, "Región us-east-1", "group_region", "#147EBA", dashed=True)
aws_group(450, 95, 760, 790, "VPC", "group_vpc2", PURPLE)
aws_group(465, 135, 730, 735, "Subredes privadas us-east-1a / us-east-1b (sin acceso a Internet)", "group_private_subnet", TEAL,
          fill="#E6F6F7", font="#147EBA")

# ------------------------------------------------------------------ actores
users = icon(45, 150, "users", INK, "Usuarios", ["admins, agentes", "y clientes"], size=56, shape="users")
dev = icon(45, 815, "user", INK, "Equipo dev", size=50, shape="user")

# ------------------------------------------------------------------ entrada (región, fuera de la VPC)
amplify = icon(250, 120, "amplify", RED, "Amplify", ["frontend React"])
apigw = icon(250, 330, "api_gateway", PINK, "API Gateway", ["6 HTTP API"])
authz = icon(250, 520, "lambda", ORANGE, "Authorizer", ["fuera de la VPC"])
cw = icon(250, 690, "cloudwatch_2", PINK, "CloudWatch Logs", ["logs de las Lambdas"])
cfn = icon(250, 820, "cloudformation", PINK, "CloudFormation", ["7 stacks"])

# ------------------------------------------------------------------ dentro de la VPC
micro = box(485, 175, 470, 400, "Microservicios · Lambda Python 3.12", ORANGE, fill="#FFF8F1")
for i, name in enumerate(["ms-identity", "ms-cmdb", "ms-incidents", "ms-problems", "ms-changes", "ms-requests"]):
    icon(530 + (i % 3) * 150, 230 + (i // 3) * 170, "lambda", ORANGE, name, size=56)
text(495, 530, 450, 40, "Rutas HTTP · consumidores SQS · migrate<br>Una base de datos por microservicio", 11, INK)

box(485, 625, 300, 225, "SG: puerto 5432 solo desde las Lambdas", SG_RED, size=11, valign="bottom")
rds = icon(560, 665, "rds", BLUE, "RDS PostgreSQL 16", ["sin acceso público", "6 bases · 1 schema por tenant"])
seed = icon(850, 690, "lambda", ORANGE, "seedLoader", ["carga los datos", "ficticios"], size=56)

box(1000, 175, 180, 675, "VPC endpoints", PURPLE, size=12)
ep_sns = icon(1065, 225, "endpoints", PURPLE, "SNS", ["interface"], size=50)
ep_sm = icon(1065, 470, "endpoints", PURPLE, "Secrets Manager", ["interface"], size=50)
ep_s3 = icon(1065, 712, "endpoints", PURPLE, "S3", ["gateway"], size=50)

# ------------------------------------------------------------------ servicios administrados
sns = icon(1290, 220, "sns", PINK, "Amazon SNS", ["1 tópico de eventos", "de dominio"], side="right")
sqs = icon(1290, 340, "sqs", PINK, "Amazon SQS", ["7 colas, cada una", "con su DLQ"], side="right")
sm = icon(1290, 460, "secrets_manager", RED, "Secrets Manager", ["DbSecret: credenciales de RDS", "JwtSecret: clave de los JWT"], side="right")
s3 = icon(1290, 707, "s3", GREEN, "Amazon S3", ["CSV de datos ficticios"], side="right")

# ------------------------------------------------------------------ flujos
edge(users, amplify, "HTTPS", exit=(1, 0.3), entry=(0, 0.5))
edge(users, apigw, "HTTPS + JWT", exit=(1, 0.8), entry=(0, 0.5), points=[(170, 195), (170, 360)])
edge(apigw, micro, "invoca", exit=(1, 0.5), entry=(0, 0.4625))
edge(apigw, authz, "valida\nJWT", color=PURPLE, dashed=True, start="block", exit=(1, 0.85), entry=(1, 0.25),
     points=[(345, 381), (345, 535)])
edge(authz, sm, "lee JwtSecret (endpoint público de Secrets Manager)", color=RED, dashed=True, exit=(1, 0.75), entry=(0, 0.75),
     points=[(420, 565), (420, 915), (1250, 915), (1250, 505)])
edge(micro, ep_sns, "publica", color=PINK, exit=(1, 0.1875), entry=(0, 0.5))
edge(ep_sns, sns, "", color=PINK, exit=(1, 0.5), entry=(0, 0.5))
edge(sns, sqs, "filtro por tipo\nde evento", color=PINK, exit=(0.5, 1), entry=(0.5, 0))
edge(sqs, micro, "consume", color=PINK, dashed=True, exit=(0, 0.5), entry=(1, 0.4875))
edge(micro, ep_sm, "lee secretos", color=RED, exit=(1, 0.8), entry=(0, 0.5))
edge(ep_sm, sm, "", color=RED, exit=(1, 0.5), entry=(0, 0.25))
edge(micro, rds, "SQL + SSL", color=BLUE, exit=(0.2234, 1), entry=(0.5, 0))
edge(seed, rds, "COPY", color=GREEN, exit=(0, 0.5), entry=(1, 0.5))
edge(seed, ep_s3, "lee CSV", color=GREEN, exit=(1, 0.5), entry=(0, 0.5))
edge(ep_s3, s3, "", color=GREEN, exit=(1, 0.5), entry=(0, 0.5))
edge(dev, cfn, "npm run deploy", color="#7D8998", dashed=True, exit=(1, 0.5), entry=(0, 0.5))

# ------------------------------------------------------------------ leyenda (una fila)
legend_items = [(INK, False, "Usuarios"), (PURPLE, True, "Autorización JWT"), (BLUE, False, "SQL a RDS"),
                (PINK, False, "Eventos SNS → SQS"), (RED, False, "Lectura de secretos"),
                (GREEN, False, "Carga de datos"), ("#7D8998", True, "Despliegue")]
box(175, 960, 1385, 70, "", "#7D8998", fill="#FFFFFF", dashed=False)
text(190, 985, 80, 20, "<b>Leyenda</b>", 12, INK, align="left")
for i, (col, dash, name) in enumerate(legend_items):
    lx, ly = 275 + i * 180, 995
    a = vertex(lx, ly, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    b = vertex(lx + 40, ly, 1, 1, "", "text;strokeColor=none;fillColor=none;")
    cells.append(f'<mxCell id="{nid()}" style="endArrow=block;endFill=1;html=1;strokeColor={col};strokeWidth=1.6;'
                 f'dashed={1 if dash else 0};dashPattern=6 4;" edge="1" parent="1" source="{a}" target="{b}">'
                 f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    text(lx + 47, ly - 9, 150, 20, name, 11, INK, align="left")

OUT.write_text(
    '<mxfile host="drawio" agent="servidesk/build_arquitectura_v2.py"><diagram name="Arquitectura v2" '
    f'id="arquitectura-v2"><mxGraphModel dx="1600" dy="900" grid="0" gridSize="10" guides="1" tooltips="1" '
    f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{W}" pageHeight="{H}" '
    f'background="#FFFFFF" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>", encoding="utf-8")
print(OUT)
