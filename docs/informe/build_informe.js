// Genera docs/informe/Informe_ServiDesk.docx (estructura del informe del proyecto 1).
// Uso: node docs/informe/build_informe.js
// Los cuadros amarillos indican qué captura o imagen va en ese lugar; se reemplazan a mano en Word.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType, ShadingType,
  BorderStyle, AlignmentType, HeadingLevel, LevelFormat, PageBreak, TableOfContents, Footer, Header,
  PageNumber, PageOrientation, ExternalHyperlink, VerticalAlign,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const FIG = path.join(ROOT, "docs", "diagramas");
const REPO = "https://github.com/al3xi3w/servidesk";
const APP = "https://main.d177kzi9o3gsmi.amplifyapp.com";

const FONT = "Times New Roman";
const NAVY = "182B4C"; // encabezado de tablas del informe del proyecto 1
const CODE = "772002"; // rutas, archivos y comandos (Times, rojo oscuro)
const A4 = { width: 11906, height: 16838 };
const MARGIN = 1440; // 2,54 cm, como el informe del proyecto 1
const CW = A4.width - 2 * MARGIN; // 9026 DXA de ancho útil (vertical)
const CW_L = A4.height - 2 * MARGIN; // 14570 DXA (horizontal)

// ------------------------------------------------------------------ texto con **negrita** y `código`
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, ...base }));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, font: FONT, ...base }));
    else out.push(new TextRun({ text: tok.slice(1, -1), font: FONT, color: CODE, size: base.size, bold: base.bold }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, ...base }));
  return out;
}

const P = (text, opts = {}) =>
  new Paragraph({ children: runs(text, opts.run), alignment: opts.align ?? AlignmentType.JUSTIFIED,
    spacing: { after: 120, line: 276 }, indent: opts.indent ? { firstLine: 720 } : undefined });
const H1 = (t, newPage = true) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: newPage,
  children: [new TextRun({ text: t, font: FONT })] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT })] });
const bullet = (t, level = 0) => new Paragraph({ numbering: { reference: "bullets", level }, children: runs(t),
  spacing: { after: 60, line: 276 }, alignment: AlignmentType.JUSTIFIED });
const numbered = (t, ref = "steps") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t),
  spacing: { after: 60, line: 276 }, alignment: AlignmentType.JUSTIFIED });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });
const quoted = (parts) => new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 720 },
  spacing: { before: 120, after: 160, line: 276 },
  children: ["“", ...parts, "”"].map((x) => (typeof x === "string" ? new TextRun({ text: x, font: FONT }) : x)) });
const link = (text, url) => new ExternalHyperlink({ link: url,
  children: [new TextRun({ text, style: "Hyperlink", font: FONT })] });

// ------------------------------------------------------------------ tablas
const BORDER = { style: BorderStyle.SINGLE, size: 3, color: "B2B8C1" };
const BORDERS = { top: BORDER, bottom: BORDER, left: BORDER, right: BORDER };

function table(headers, rows, widths, opts = {}) {
  const total = opts.total ?? CW;
  const scale = total / widths.reduce((a, b) => a + b, 0);
  const w = widths.map((x) => Math.round(x * scale));
  w[w.length - 1] += total - w.reduce((a, b) => a + b, 0);
  const cell = (text, i, head, shade) => new TableCell({
    width: { size: w[i], type: WidthType.DXA },
    borders: BORDERS,
    shading: head ? { fill: NAVY, type: ShadingType.CLEAR, color: "auto" }
      : shade ? { fill: "F1F4F6", type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    verticalAlign: VerticalAlign.CENTER,
    children: String(text).split("\n").map((line) => new Paragraph({
      children: runs(line, head ? { bold: true, color: "FFFFFF", size: 21 } : { size: 21 }),
      spacing: { after: 0 },
    })),
  });
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: w,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r, ri) => new TableRow({ children: r.map((c, i) => cell(c, i, false, ri % 2 === 1)) })),
    ],
  });
}
const gap = () => new Paragraph({ children: [], spacing: { after: 80 } });

// ------------------------------------------------------------------ cuadro amarillo de captura
function shot(n, title, lines, opts = {}) {
  // Cuadro amarillo + pie de figura en una misma tabla de 2 filas que no se separa entre páginas.
  const total = opts.total ?? CW;
  const YB = { style: BorderStyle.DASHED, size: 12, color: "C9A400" };
  const NONE = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const keep = (para) => para; // las filas usan cantSplit y los párrafos keepNext
  return [new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: [total],
    rows: [
      new TableRow({ cantSplit: true, children: [new TableCell({
        width: { size: total, type: WidthType.DXA },
        borders: { top: YB, bottom: YB, left: YB, right: YB },
        shading: { fill: "FFF2CC", type: ShadingType.CLEAR, color: "auto" },
        margins: { top: 140, bottom: 140, left: 180, right: 180 },
        children: [
          new Paragraph({ spacing: { after: 80 }, keepNext: true, children: [
            new TextRun({ text: `CAPTURA ${n} · `, bold: true, font: FONT, color: "7F6000", size: 21 }),
            new TextRun({ text: title, bold: true, font: FONT, color: "3D3000", size: 21 }),
          ] }),
          ...lines.map((l) => new Paragraph({ spacing: { after: 40 }, keepNext: true,
            children: runs(l, { size: 19, color: "3D3000" }) })),
          new Paragraph({ spacing: { before: 60, after: 0 }, keepNext: true, children: [new TextRun({
            text: "Reemplazar el contenido de este cuadro por la captura; el pie de figura de abajo se mantiene.",
            italics: true, font: FONT, size: 17, color: "8C7A2E" })] }),
        ],
      })] }),
      new TableRow({ cantSplit: true, children: [new TableCell({
        width: { size: total, type: WidthType.DXA },
        borders: { top: NONE, bottom: NONE, left: NONE, right: NONE },
        margins: { top: 0, bottom: 0, left: 0, right: 0 },
        children: [keep(caption(opts.caption ?? title))],
      })] }),
    ],
  }), new Paragraph({ children: [], spacing: { after: 120 } })];
}

let figN = 0;
function caption(text) {
  figN += 1;
  return new Paragraph({ alignment: AlignmentType.LEFT, spacing: { before: 80, after: 240 },
    children: [new TextRun({ text: `Figura ${figN}. ${text}`, italics: true, underline: {}, font: FONT, size: 22 })] });
}

function figure(file, widthPx, text) {
  const buf = fs.readFileSync(path.join(FIG, file));
  const w = buf.readUInt32BE(16);
  const h = buf.readUInt32BE(20);
  return [new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, keepNext: true,
    children: [new ImageRun({ type: "png", data: buf, transformation: { width: widthPx, height: Math.round(widthPx * h / w) },
      altText: { title: text, description: text, name: file } })] }), caption(text)];
}

// ------------------------------------------------------------------ contenido
const ENDPOINT_W = [10, 36, 54];

const coverLine = (text, opts = {}) => new Paragraph({ alignment: AlignmentType.CENTER,
  spacing: { before: opts.before ?? 0, after: opts.after ?? 0, line: 276 },
  children: [new TextRun({ text, font: FONT, size: opts.size ?? 28, bold: opts.bold ?? false })] });

const portada = [
  coverLine("UNIVERSIDAD DE INGENIERÍA Y TECNOLOGÍA", { bold: true, before: 400, after: 1000 }),
  coverLine("Curso:", { bold: true }),
  coverLine("Cloud Computing (CS2032)", { after: 1000 }),
  coverLine("Proyecto: ServiDesk - Plataforma SaaS de gestión de servicios TI (ITSM)", { bold: true, size: 34 }),
  coverLine("multi-tenant, serverless y basada en eventos en AWS", { bold: true, size: 34, after: 1000 }),
  coverLine("Integrantes Grupo:", { after: 120 }),
  ...["Daniel Guillermo Sandoval Toro (202310533)", "Jose Ernesto Guerrero Cueva (202210566)",
    "Ian Jesus Rodríguez Santayana (202310184)", "Vannia Fatima Curay Mauricio (201910133)",
    "Mia Wood De la fuente chavez (202410085)"].map((n) => coverLine(n, { after: 120 })),
  coverLine("Profesor:", { bold: true, before: 900 }),
  coverLine("Lezama, Aldo"),
  pageBreak(),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
    children: [new TextRun({ text: "ÍNDICE", bold: true, font: FONT, size: 28 })] }),
  new TableOfContents("Índice", { hyperlink: true, headingStyleRange: "1-2" }),
];

const intro = [
  H1("1. INTRODUCCIÓN"),
  P("ServiDesk es una plataforma **SaaS de gestión de servicios TI (ITSM)**, en la línea de ServiceNow, Jira Service Management o Freshservice: permite a varias organizaciones (tenants) gestionar sus incidentes, problemas, cambios, solicitudes de servicio y su CMDB desde una misma aplicación, con los datos de cada una aislados. Se construyó como proyecto final del curso sobre una arquitectura **multi-tenant, 100 % serverless y basada en eventos** en AWS Academy Learner Lab.", { indent: true }),
  P("El backend está formado por 6 microservicios en AWS Lambda detrás de API Gateway, protegidos con un Lambda Authorizer JWT. Cada microservicio tiene su propia base de datos en una única instancia de Amazon RDS PostgreSQL, con un schema por tenant. Los microservicios se comunican por eventos de dominio publicados en Amazon SNS y entregados a colas Amazon SQS. El frontend, en React, se publica en AWS Amplify.", { indent: true }),
  H2("1.1 Objetivos"),
  bullet("Implementar una solución SaaS de tipo ITSM (Grupo 6) con **multi-tenancy** real: el tenant se resuelve en el login y viaja firmado en el JWT; ningún dato de un tenant es visible para otro."),
  bullet("Construir **6 microservicios serverless** (API Gateway + Lambda) protegidos, cada uno con su propia base de datos en una instancia única de RDS con el patrón **Single Database, Multiple Schemas**."),
  bullet("Diseñar una arquitectura **basada en eventos (EDA)** con SNS y SQS: incidentes automáticos cuando un CI cae, detección de problemas recurrentes, publicación de errores conocidos y cierre de problemas al implementar un cambio."),
  bullet("Cargar **30 000 registros ficticios por microservicio** divididos en 3 tenants, usando S3 como origen de la carga."),
  bullet("**Automatizar todo el despliegue** con Serverless Framework y publicar el frontend en **AWS Amplify**; demostrar la solución con 2 tenants."),
  H2("1.2 Correspondencia con la rúbrica"),
  table(["Ítem", "Pts.", "Dónde se documenta"], [
    ["Diagrama de Arquitectura de Solución", "2", "Sección 2, Figura 1"],
    ["Backend", "8", "Sección 3 (microservicios, modelo de datos, datos ficticios y pruebas) y Sección 5 (despliegue)"],
    ["Frontend", "6", "Sección 4"],
    ["Exposición presencial", "1", "Presentación (archivo aparte) y demo con 2 tenants"],
    ["Exposición virtual con ACL (avance 30 %)", "3", "Fuera de este informe"],
  ], [40, 8, 52]),
  gap(),
  H2("1.3 Cumplimiento de los requerimientos"),
  table(["Requerimiento del enunciado", "Cómo se cumple", "Evidencia"], [
    ["SaaS del tipo asignado (ITSM)", "Incidentes, problemas (KEDB), cambios (CAB), catálogo y solicitudes, CMDB", "Secciones 3 y 4"],
    ["Multi-tenancy", "JWT con tenant y schema; un schema por tenant; 404 para datos de otro tenant", "2.4 y Figuras 9 y 25"],
    ["Serverless", "API Gateway (6 HTTP API) + 59 funciones Lambda, sin servidores", "Figuras 1, 16 y 17"],
    ["Basada en eventos (EDA)", "1 tópico SNS, 7 colas SQS con DLQ y 8 consumidores", "2.3 y Figuras 13, 19, 20 y 23"],
    ["≥ 5 microservicios protegidos, cada uno con su BD", "6 microservicios con Lambda Authorizer JWT, una base por microservicio", "3.1"],
    ["RDS único, patrón 2 (Single Database, Multiple Schemas)", "Instancia servidesk-db-dev; 6 bases db_*, cada una con 3 schemas tenant_*", "3.8 y Figura 18"],
    ["RDS privada y credenciales seguras", "RDS en subredes privadas sin acceso público; usuario/contraseña de la BD y clave JWT en AWS Secrets Manager", "2.1, 2.4 y Figuras 1, 18 y 26"],
    ["Diagrama E/R por microservicio", "6 diagramas E/R (todas las bases son PostgreSQL)", "Figuras 2 a 7"],
    ["30 000 registros por microservicio en 3 tenants", "10 000 por tenant en la tabla principal de cada servicio", "3.9 y Figura 8"],
    ["Usar S3, SNS y SQS", "S3 (carga de datos, adjuntos, exportes), SNS (eventos) y SQS (colas por consumidor)", "Figuras 19 a 21"],
    ["Despliegue automatizado con Serverless Framework", "serverless-compose: 7 stacks de CloudFormation con un solo comando", "Sección 5 y Figura 15"],
    ["Frontend en Amplify", "React + Vite publicado en Amplify Hosting", "Sección 4 y Figura 22"],
    ["Demo con 2 tenants", "andina y pacifico en dos pestañas", "Figura 25"],
  ], [30, 46, 24]),
  gap(),
  quoted([
    "El código completo, los contratos de API y la guía de despliegue están en el repositorio público de GitHub: ",
    link(REPO, REPO),
    " (README.md, docs/DEPLOY.md, docs/API_CONTRACTS.md y el README de cada microservicio). Aplicación publicada: ",
    link(APP, APP), "."]),
];

const arquitectura = [
  H1("2. ARQUITECTURA DE SOLUCIÓN"),
  P("La Figura 1 muestra todos los servicios de AWS utilizados en el frontend, el backend, la mensajería, los datos y el despliegue, con un color de flecha por tipo de flujo (tráfico de usuarios, autorización, SQL, publicación de eventos, entrega por SQS, carga de datos y despliegue). La base de datos RDS está en **subredes privadas** de la VPC, sin acceso desde Internet, y las Lambdas que la usan obtienen sus credenciales de **AWS Secrets Manager**.", { indent: true }),
  P("El diagrama editable está en `docs/diagramas/servidesk_arquitectura_v2.drawio` y la figura en alta resolución en `docs/diagramas/1b_diagrama_arquitectura_v2.png`.", { align: AlignmentType.LEFT }),
];

const arqFigure = [...figure("1b_diagrama_arquitectura_v2.png", 690, "Diagrama de Arquitectura de Solución de ServiDesk")];

const arquitectura2 = [
  H2("2.1 Componentes y servicios AWS"),
  table(["Capa", "Servicio / recurso", "Función"], [
    ["Frontend", "AWS Amplify Hosting\n(app servidesk, rama main)", "Hospeda la SPA React 19 + Vite. Las URLs de las 6 APIs se inyectan con variables `VITE_API_*_URL` al compilar."],
    ["Entrada", "Amazon API Gateway\n(6 HTTP API)", "Una API por microservicio, HTTPS y CORS. 44 rutas: 43 con authorizer JWT y `POST /auth/login` pública."],
    ["Seguridad", "Lambda Authorizer", "Valida firma HS256 (clave JwtSecret leída de Secrets Manager), expiración y claims del JWT y entrega a cada Lambda el contexto `tenant_id`, `schema`, `role`, `user_id` (caché de 300 s)."],
    ["Cómputo", "AWS Lambda (Python 3.12)", "57 funciones en los 6 microservicios (rutas HTTP, consumidores SQS y migrate) + authorizer y seedLoader en el stack infra. Capa común con pg8000, PyJWT y utilidades. Las Lambdas que acceden a la BD se ejecutan dentro de la VPC."],
    ["Red", "Amazon VPC\n(2 subredes privadas)", "Subredes privadas sin ruta a Internet para RDS y las Lambdas. Security groups: RDS solo acepta 5432 desde el SG de las Lambdas. VPC endpoints: Secrets Manager y SNS (interface) y S3 (gateway); no se usa NAT."],
    ["Secretos", "AWS Secrets Manager\n(DbSecret, JwtSecret)", "DbSecret: usuario, contraseña, host y puerto de RDS (contraseña generada por CloudFormation). JwtSecret: clave HS256 de los tokens. Las Lambdas los leen al iniciar y los guardan en caché."],
    ["Datos", "Amazon RDS PostgreSQL 16\n(servidesk-db-dev, db.t3.micro)", "Instancia única, privada (PubliclyAccessible = false) y con SSL obligatorio. Una base por microservicio (db_identity … db_requests) y un schema por tenant en cada una."],
    ["Eventos", "Amazon SNS\n(servidesk-itsm-events-dev)", "Tópico único de eventos de dominio; cada suscripción filtra por `eventType` (FilterPolicy)."],
    ["Colas", "Amazon SQS (7 colas + 7 DLQ)", "Una cola por consumidor con su cola de mensajes fallidos (maxReceiveCount 3) y ReportBatchItemFailures."],
    ["Almacenamiento", "Amazon S3 (3 buckets)", "seed: CSV comprimidos de la carga de datos; attachments y exports: provisionados para adjuntos y exportes."],
    ["Observabilidad", "Amazon CloudWatch Logs", "Un grupo de logs por función, con la duración de cada invocación y los mensajes de los consumidores."],
    ["Despliegue", "AWS CloudFormation +\nServerless Framework v3", "7 stacks (infra + 6 servicios) desplegados con `npm run deploy` (serverless-compose)."],
    ["Identidad", "IAM LabRole", "Rol de ejecución de todas las Lambdas (AWS Academy no permite crear roles)."],
  ], [14, 26, 60]),
  gap(),
  H2("2.2 Recorrido de una petición"),
  numbered("El usuario abre la aplicación servida por Amplify e inicia sesión con el **código de su organización**, su email y su contraseña."),
  numbered("ms-identity busca el código en `public.tenants`, valida la contraseña (PBKDF2) en el schema del tenant y firma un JWT de 1 hora con `tenant_id`, `schema` y `role` usando la clave JwtSecret de Secrets Manager."),
  numbered("Cada llamada del navegador va por HTTPS a la HTTP API del microservicio con `Authorization: Bearer <token>`."),
  numbered("API Gateway invoca al Lambda Authorizer, que valida el token y entrega el contexto del tenant."),
  numbered("La Lambda del endpoint, dentro de la subred privada, lee las credenciales de DbSecret en Secrets Manager (por el VPC endpoint), abre la conexión SSL a su base, fija `SET search_path` al schema del tenant del token y ejecuta la consulta."),
  numbered("Si la operación cambia el estado del dominio, después del COMMIT publica un evento en SNS; las colas SQS suscritas lo entregan a las Lambdas consumidoras de otros microservicios."),
  H2("2.3 Arquitectura basada en eventos"),
  P("Los microservicios no se llaman entre sí: se coordinan con eventos. Cada evento lleva un sobre común (`eventId`, `eventType`, `tenantId`, `occurredAt`, `source`, `data`) y cada consumidor es idempotente gracias a la tabla `processed_events`.", { indent: true }),
  table(["Evento", "Publica", "Cola → consumidor", "Efecto"], [
    ["CIStatusChanged", "ms-cmdb", "incidents-ci-q → ms-incidents", "Si el CI pasa a down, crea un incidente P2 automático (canal auto)."],
    ["IncidentCreated", "ms-incidents", "problems-incidents-q → ms-problems", "Con 3 o más incidentes del mismo CI en 24 h crea un problema y los vincula."],
    ["ProblemIncidentsLinked", "ms-problems", "incidents-problem-q → ms-incidents", "Fija problem_id en los incidentes vinculados."],
    ["KnownErrorPublished", "ms-problems", "incidents-kedb-q → ms-incidents", "Comenta la solución temporal en los incidentes del problema."],
    ["ChangeImplemented", "ms-changes", "cmdb-changes-q → ms-cmdb\nproblems-changes-q → ms-problems", "Aplica la versión nueva a los CIs del cambio y cierra el problema que corrige."],
    ["12 tipos de evento*", "todos", "identity-notify-q → ms-identity", "Crea las notificaciones de la campana para los usuarios afectados."],
  ], [20, 13, 30, 37]),
  P("* IncidentCreated, IncidentUpdated, IncidentResolved, ProblemCreated, KnownErrorPublished, ChangeSubmitted, ChangeApproved, ChangeRejected, RequestSubmitted, RequestApproved, RequestRejected y RequestFulfilled.", { run: { size: 18, color: "595959" } }),
  H2("2.4 Multi-tenancy y seguridad"),
  bullet("**El cliente no elige el tenant**: solo envía el código en el login. Después, el tenant y el schema viajan dentro de un JWT firmado; el backend rechaza `tenant_id` o `schema` en el body (400)."),
  bullet("**Una sola fuente de verdad**: cada Lambda toma el schema del contexto del authorizer y la capa común lo valida con una expresión regular antes del `SET search_path`."),
  bullet("**Los IDs de otro tenant no existen**: pedir un recurso de otro tenant responde 404 (no 403), así no se revela que existe."),
  bullet("Dentro del tenant, los clientes (customer) solo ven sus propios incidentes y solicitudes; la aprobación CAB y de solicitudes es solo de administradores."),
  bullet("Contraseñas con **PBKDF2-SHA256 (310 000 iteraciones)**; conexión a RDS con SSL desde la VPC; **RDS privada** (sin IP pública, su security group solo acepta a las Lambdas); credenciales de la BD y clave JWT en **AWS Secrets Manager**, nunca en el código ni en variables de entorno."),
];

const ms = (id, title, desc, rows, extra = []) => [
  H2(`${id} ${title}`), P(desc), table(["Método", "Ruta", "Descripción"], rows, ENDPOINT_W), ...extra, gap()];

const backend = [
  H1("3. BACKEND: MICROSERVICIOS"),
  P("Cada microservicio es un servicio de Serverless Framework con su propia HTTP API, sus funciones Lambda, su base de datos y, si consume eventos, sus colas SQS. Todos siguen los mismos contratos (`docs/API_CONTRACTS.md` y `docs/openapi.yaml`): respuestas `{data}` / `{data, meta}`, errores `{error: {code, message, details, request_id}}`, paginación, filtros y validación estricta del body.", { indent: true }),
  quoted(["Código fuente de los 6 microservicios: ", link(`${REPO}/tree/main/services`, `${REPO}/tree/main/services`)]),
  H2("3.1 Resumen"),
  table(["Microservicio", "Responsabilidad", "Base de datos", "Endpoints", "Publica / consume"], [
    ["ms-identity", "Login JWT, usuarios, equipos, notificaciones", "db_identity", "9", "Publica UserCreated · consume identity-notify-q"],
    ["ms-cmdb", "Elementos de configuración, relaciones, historial", "db_cmdb", "8", "Publica CIStatusChanged · consume cmdb-changes-q"],
    ["ms-incidents", "Incidentes, SLA, comentarios", "db_incidents", "7", "Publica Incident* · consume 3 colas"],
    ["ms-problems", "Problemas y errores conocidos (KEDB)", "db_problems", "7", "Publica Problem*, KnownErrorPublished · consume 2 colas"],
    ["ms-changes", "Cambios (RFC), aprobación CAB, calendario", "db_changes", "7", "Publica Change*"],
    ["ms-requests", "Catálogo de servicios y solicitudes", "db_requests", "6", "Publica Request*"],
  ], [15, 30, 14, 10, 31]),
  P("Todos usan Python 3.12 en AWS Lambda con pg8000 (capa común). Roles: **admin** (todo, incluida la aprobación), **agent** (operación) y **customer** (autoservicio sobre lo propio)."),
  ...ms("3.2", "ms-identity", "Resuelve el tenant en el login, emite el JWT y administra usuarios y equipos. Su consumidor identity-notify-q convierte 12 tipos de evento en notificaciones.", [
    ["POST", "/auth/login", "Valida código de organización, email y contraseña; devuelve el JWT (1 h) y el usuario (pública)"],
    ["GET", "/auth/me", "Usuario autenticado (restaura la sesión al recargar)"],
    ["GET", "/users", "Lista paginada con filtros role, active, ids y búsqueda por nombre o email"],
    ["GET / POST", "/users/{id} · /users", "Consulta un usuario · crea un usuario (admin; publica UserCreated)"],
    ["PATCH", "/users/{id}", "Actualiza nombre, rol, estado o contraseña (admin; no puede quitarse el rol a sí mismo)"],
    ["GET", "/teams", "Equipos de soporte"],
    ["GET / POST", "/notifications · /notifications/read", "Bandeja de la campana y marcar como leídas"],
  ]),
  ...ms("3.3", "ms-cmdb", "Registra los elementos de configuración (servidores, bases de datos, aplicaciones…), sus relaciones y el historial de cada cambio de campo.", [
    ["GET / POST", "/cis", "Lista con filtros status, environment, type_id, owner_team_id · registra un CI"],
    ["GET / PATCH", "/cis/{id}", "Consulta · actualiza (cada campo cambiado queda en ci_history)"],
    ["PUT", "/cis/{id}/status", "Cambia el estado y publica CIStatusChanged (down → incidente automático)"],
    ["DELETE", "/cis/{id}", "Baja lógica a retired (idempotente)"],
    ["GET", "/cis/{id}/relations · /ci-types", "Relaciones entrantes y salientes · tipos de CI"],
  ]),
  ...ms("3.4", "ms-incidents", "Gestiona los incidentes con prioridad calculada (impacto × urgencia), SLA por prioridad, comentarios internos y públicos, e incidentes automáticos creados por eventos.", [
    ["GET / POST", "/incidents", "Lista con colas (míos, sin asignar, SLA vencido), filtros y búsqueda · crea un incidente"],
    ["GET / PATCH", "/incidents/{id}", "Consulta · actualiza asignado, equipo, CI, impacto o urgencia"],
    ["PUT", "/incidents/{id}/status", "Transición de estado (resolver exige nota; publica IncidentResolved)"],
    ["GET / POST", "/incidents/{id}/comments", "Comentarios (los internos no los ve el cliente)"],
  ]),
  ...ms("3.5", "ms-problems", "Busca la causa raíz de incidentes recurrentes y publica errores conocidos con su solución temporal.", [
    ["GET / POST", "/problems", "Lista con filtros · crea un problema (puede vincular incidentes)"],
    ["GET / PATCH", "/problems/{id}", "Detalle con incidentes vinculados y error conocido · actualiza causa raíz"],
    ["PUT", "/problems/{id}/status", "Transición de estado"],
    ["POST", "/problems/{id}/known-error", "Publica el error conocido (KnownErrorPublished)"],
    ["POST", "/problems/{id}/incidents", "Vincula incidentes (ProblemIncidentsLinked)"],
  ]),
  ...ms("3.6", "ms-changes", "Gestiona las solicitudes de cambio con su plan de reversión, la aprobación del comité (CAB) y el calendario.", [
    ["GET / POST", "/changes", "Lista con filtros y rango de fechas (calendario) · crea un cambio en draft"],
    ["GET / PATCH", "/changes/{id}", "Detalle con CIs afectados y decisiones CAB · edición en draft"],
    ["PUT", "/changes/{id}/status", "submitted → scheduled → implemented/failed (los standard se aprueban solos)"],
    ["POST", "/changes/{id}/approve · /reject", "Decisión CAB (admin distinto del solicitante)"],
  ]),
  ...ms("3.7", "ms-requests", "Publica el catálogo de servicios con formularios dinámicos (form_schema) y gestiona las solicitudes y su aprobación.", [
    ["GET", "/catalog", "Catálogo activo con el formulario de cada servicio"],
    ["GET / POST", "/requests", "Lista (el cliente ve solo las suyas) · crea una solicitud validando form_data"],
    ["GET / PATCH", "/requests/{id}", "Detalle con aprobaciones · asigna responsable o edita el formulario"],
    ["PUT", "/requests/{id}/status", "Aprobar, rechazar, atender y completar"],
  ]),
  H2("3.8 Modelo de datos"),
  P("Las 6 bases son **PostgreSQL** (relacionales) y viven en la instancia única y privada servidesk-db-dev. Cada microservicio es dueño de su base (`db_<servicio>`) y dentro de ella existe un **schema por tenant** (`tenant_andina`, `tenant_pacifico`, `tenant_unitec`) con las mismas tablas: es el patrón 2 de multi-tenancy (Single Database, Multiple Schemas) aplicado a cada microservicio. La tabla global `public.tenants` de db_identity relaciona cada código de organización con su schema.", { indent: true }),
  P("Las Figuras 2 a 7 muestran el diagrama E/R de cada base. Solo se dibujan como entidades las tablas reales con sus claves foráneas. Las referencias a otro microservicio (por ejemplo `incidents.ci_id`) van punteadas hacia cajas grises porque **no hay FK entre bases**: la consistencia la dan la API y los eventos. Las columnas JSONB (`attributes`, `form_schema`, `form_data`) se documentan con un ejemplo de su estructura JSON, y las tablas técnicas sin relaciones (idempotencia de SQS) van en una nota.", { indent: true }),
];

const erFigs = [
  ["2_er_identity.png", "Diagrama E/R de db_identity (ms-identity)."],
  ["3_er_cmdb.png", "Diagrama E/R de db_cmdb (ms-cmdb)."],
  ["4_er_incidents.png", "Diagrama E/R de db_incidents (ms-incidents)."],
  ["5_er_problems.png", "Diagrama E/R de db_problems (ms-problems)."],
  ["6_er_changes.png", "Diagrama E/R de db_changes (ms-changes)."],
  ["7_er_requests.png", "Diagrama E/R de db_requests (ms-requests)."],
].flatMap(([f, t]) => figure(f, 600, t));

const backend2 = [
  H2("3.9 Datos ficticios"),
  P("`seed/generate.py` genera con Faker (es_ES) **10 000 registros por tenant en la tabla principal de cada microservicio**, más sus tablas relacionadas, como CSV comprimidos. Los UUID son deterministas (uuid5), así que un `reporter_id` o un `ci_id` apuntan a registros que existen en el otro microservicio. Se respetan las reglas del negocio: prioridad = impacto × urgencia, SLA vencido, errores conocidos solo en problemas resueltos, aprobaciones CAB solo en cambios no estándar y formularios válidos contra el catálogo.", { indent: true }),
  P("`seed/load.py` sube los archivos al bucket **S3** `servidesk-seed-dev-<cuenta>` e invoca la Lambda **seedLoader**, que se ejecuta dentro de la VPC y los transmite de S3 (por el gateway endpoint) a RDS con `COPY … FROM STDIN` por SSL, por servicio y tenant, en una transacción (la carga se puede repetir sin duplicar)."),
  table(["Microservicio", "Tabla principal", "andina", "pacifico", "unitec", "Total"], [
    ["ms-identity", "users", "10 000", "10 000", "10 000", "30 000"],
    ["ms-cmdb", "configuration_items", "10 000", "10 000", "10 000", "30 000"],
    ["ms-requests", "service_requests", "10 000", "10 000", "10 000", "30 000"],
    ["ms-incidents", "incidents", "10 000", "10 000", "10 000", "30 000"],
    ["ms-problems", "problems", "10 000", "10 000", "10 000", "30 000"],
    ["ms-changes", "changes", "10 000", "10 000", "10 000", "30 000"],
  ], [18, 26, 13, 13, 13, 17]),
  P("Además se cargan unos 190 000 registros en tablas relacionadas (comentarios, errores conocidos, CIs afectados, aprobaciones, relaciones entre CIs, historial y miembros de equipos).", { run: { size: 20 } }),
  ...shot(1, "Conteo de registros en RDS", [
    "Ejecutar en la terminal, con las credenciales del Learner Lab: `python seed/load.py count`.",
    "Capturar la tabla completa: tabla principal por tenant (andina, pacifico, unitec), total de 30 000 por microservicio, tablas relacionadas y la línea final \"RESULTADO: OK\".",
  ], { caption: "Conteo de registros por microservicio y tenant en RDS (seed/load.py count)." }),
  H2("3.10 Pruebas y documentación de las API"),
  bullet("**678 pruebas unitarias** (pytest) en los 6 microservicios, el authorizer y los consumidores, con la base simulada."),
  bullet("**Pruebas de integración contra PostgreSQL 16 real con SSL** (`scripts/integration/`), incluida una simulación end-to-end que recorre el flujo de eventos entre los 6 servicios con las suscripciones de los serverless.yml."),
  bullet("**Prueba de humo en AWS** (`python scripts/aws_check.py smoke`): login en 2 tenants, CRUD, eventos reales por SNS → SQS y aislamiento entre tenants."),
  bullet("**Contrato frontend ↔ backend** (`python scripts/frontend_contract.py`): las mismas llamadas que hacen las páginas, validadas contra los tipos de TypeScript."),
  bullet("Contratos documentados en `docs/API_CONTRACTS.md`, `docs/EVENT_CONTRACTS.md` y `docs/openapi.yaml` (OpenAPI 3.1)."),
  ...shot(2, "Prueba de humo contra AWS", [
    "Ejecutar `python scripts/aws_check.py smoke` y capturar la salida completa.",
    "Deben verse las secciones 1 a 7 en OK: autenticación (401/403), lecturas de los 6 servicios, \"incidente automático creado por el evento\", cambios aprobados por admin, notificación recibida y aislamiento entre tenants (404), con \"RESULTADO: TODO OK\".",
  ], { caption: "Prueba de humo en AWS: endpoints, eventos SNS → SQS y aislamiento entre tenants." }),
];

const frontend = [
  H1("4. FRONTEND"),
  P("El frontend es una SPA en **React 19 + TypeScript + Vite**, publicada en **AWS Amplify Hosting**. Está pensada para las empresas cliente y sus trabajadores, con lenguaje simple (Fallas, Problemas recurrentes, Actualizaciones, Pedidos, Equipos y sistemas), tema y logo por tenant, y vistas según el rol.", { indent: true }),
  quoted(["Aplicación publicada: ", link(APP, APP), ". Código del frontend: ",
    link(`${REPO}/tree/main/frontend`, `${REPO}/tree/main/frontend`)]),
  table(["Ruta", "Quién", "Qué muestra"], [
    ["/login", "público", "Login por código de organización, con accesos a las cuentas demo"],
    ["/app", "todos", "Tablero (admin/agent) o portal de autoservicio (customer)"],
    ["/app/incidents", "todos", "Fallas con SLA, matriz impacto × urgencia, comentarios e internos"],
    ["/app/problems", "admin, agent", "Causa raíz, errores conocidos e incidentes vinculados"],
    ["/app/changes, /app/changes/calendar", "admin, agent", "Solicitudes de cambio, aprobación CAB y calendario"],
    ["/app/catalog, /app/requests", "todos", "Catálogo con formularios dinámicos y solicitudes con aprobación"],
    ["/app/cmdb", "admin, agent", "Equipos y sistemas; marcar uno como caído genera un incidente automático"],
    ["/app/users", "admin, agent", "Usuarios y equipos (alta y edición solo admin)"],
    ["/demo/plataforma", "admin, agent", "Vista para la exposición: registros por microservicio y botones para disparar los eventos"],
  ], [27, 15, 58]),
  gap(),
  bullet("Un cliente HTTP por microservicio (`src/api`), con el token en el header Authorization; el tenant nunca se envía: lo pone el backend desde el JWT."),
  bullet("Con el backend real, las vistas se refrescan cada 15 s para mostrar lo que producen los eventos (incidentes automáticos, problemas por recurrencia) y la campana consulta las notificaciones cada 20 s."),
  bullet("`sessionStorage` por pestaña: permite tener andina y pacifico abiertos a la vez durante la demo."),
  ...shot(3, "Login con cuentas demo", [
    `Abrir ${APP}/login.`,
    "Mostrar la pantalla con los botones de organización (Andina Retail, Clínica Pacífico, UniTec Campus) y de rol (Administrador, Agente, Cliente).",
  ], { caption: "Pantalla de login por organización." }),
  ...shot(4, "Tablero del agente (tenant andina)", [
    "Ingresar con andina / lucia.paredes@andina.pe / Andina#2026.",
    "Capturar el tablero con los indicadores (fallas abiertas, P1, SLA vencido, actualizaciones por aprobar) cargados desde AWS.",
  ], { caption: "Tablero del agente con datos de AWS (tenant andina)." }),
  ...shot(5, "Lista de fallas (incidentes)", [
    "Menú Fallas: mostrar la lista con prioridad, estado, plazo (SLA) y las colas (míos, sin asignar, SLA vencido). Se ve el total de 10 000 del tenant.",
    "Opcional: abrir el detalle de una falla con sus comentarios.",
  ], { caption: "Lista de incidentes con SLA y colas del agente." }),
  ...shot(6, "Incidente automático por evento", [
    "Ir a /demo/plataforma y pulsar \"Simular CI caído\" (o en Equipos y sistemas marcar un CI como Caído).",
    "Esperar unos 15 s y capturar la lista de fallas con el nuevo incidente \"[Automático] … dejó de responder\" (canal auto, P2) y la campana de notificaciones.",
  ], { caption: "Incidente creado automáticamente por el evento CIStatusChanged (SNS → SQS)." }),
  ...shot(7, "Catálogo de servicios y solicitud", [
    "Ingresar como cliente (jorge.huaman@andina.pe) y abrir el Catálogo: mostrar las tarjetas y el formulario dinámico de un servicio (por ejemplo \"Laptop nueva\").",
  ], { caption: "Catálogo de servicios con formulario dinámico (portal del cliente)." }),
];

const despliegue = [
  H1("5. DESPLIEGUE EN AWS"),
  P("Todo el backend se despliega en AWS Academy Learner Lab con **Serverless Framework v3 + serverless-compose**: un solo comando crea los 7 stacks de CloudFormation, primero el stack compartido y luego los 6 microservicios en paralelo. La guía completa, para desplegarlo en cualquier cuenta, está en `docs/DEPLOY.md`.", { indent: true }),
  table(["Stack", "Recursos principales"], [
    ["servidesk-infra-dev", "VPC: 2 subredes privadas, security groups y VPC endpoints (Secrets Manager, SNS, S3); secretos DbSecret y JwtSecret; RDS PostgreSQL 16 privada, tópico SNS, 3 buckets S3, capa común (pg8000, PyJWT), Lambda Authorizer y Lambda seedLoader"],
    ["servidesk-identity-dev", "HTTP API (9 rutas), 11 Lambdas, cola identity-notify-q + DLQ"],
    ["servidesk-cmdb-dev", "HTTP API (8 rutas), 10 Lambdas, cola cmdb-changes-q + DLQ"],
    ["servidesk-incidents-dev", "HTTP API (7 rutas), 11 Lambdas, colas incidents-ci-q, incidents-problem-q, incidents-kedb-q + DLQ"],
    ["servidesk-problems-dev", "HTTP API (7 rutas), 10 Lambdas, colas problems-incidents-q, problems-changes-q + DLQ"],
    ["servidesk-changes-dev", "HTTP API (7 rutas), 8 Lambdas"],
    ["servidesk-requests-dev", "HTTP API (6 rutas), 7 Lambdas"],
  ], [28, 72]),
  gap(),
  new Paragraph({ children: [new TextRun({ text: "Pasos principales", bold: true, font: FONT })], spacing: { after: 80 } }),
  numbered("Copiar las credenciales del Learner Lab a `~/.aws/credentials` (no hace falta `.env`: CloudFormation genera la contraseña de la BD y la clave JWT en Secrets Manager).", "deploy"),
  numbered("`npm run deploy`: instala la capa común para Lambda (Linux, Python 3.12) y despliega infra y los 6 servicios (unos 15–20 min, la mayor parte es la creación de RDS).", "deploy"),
  numbered("`python scripts/aws_check.py all`: obtiene las URLs de las 6 APIs, ejecuta las migraciones (identity primero) y la prueba de humo.", "deploy"),
  numbered("`python seed/generate.py` y `python seed/load.py all`: generan los datos, los suben a S3 y los cargan con seedLoader.", "deploy"),
  numbered("`python scripts/deploy_frontend.py`: compila el frontend con las URLs de las APIs y lo publica en Amplify.", "deploy"),
  gap(),
  ...shot(8, "CloudFormation", [
    "Consola de AWS → CloudFormation → Stacks (región us-east-1).",
    "Mostrar los 7 stacks servidesk-*-dev en estado CREATE_COMPLETE o UPDATE_COMPLETE.",
  ], { caption: "Stacks de CloudFormation creados por Serverless Framework." }),
  ...shot(9, "Funciones Lambda", [
    "Consola → Lambda → Functions, filtrar por \"servidesk\".",
    "Mostrar la lista de funciones (runtime Python 3.12). Si cabe, abrir servidesk-incidents-dev-onCiStatusChanged → Configuration → Triggers y mostrar el trigger SQS incidents-ci-q.",
  ], { caption: "Funciones Lambda de los microservicios y sus consumidores." }),
  ...shot(10, "API Gateway", [
    "Consola → API Gateway → APIs: mostrar las 6 HTTP API dev-servidesk-*.",
    "Abrir dev-servidesk-incidents → Routes y mostrar las rutas con el authorizer jwtAuthorizer.",
  ], { caption: "HTTP APIs de API Gateway y rutas protegidas con el Lambda Authorizer." }),
  ...shot(11, "Amazon RDS", [
    "Consola → RDS → Databases → servidesk-db-dev.",
    "Mostrar motor PostgreSQL 16, clase db.t3.micro y estado Available; en la pestaña Connectivity & security, \"Publicly accessible: No\" y las subredes privadas servidesk-private-a/b-dev.",
  ], { caption: "Instancia única de RDS PostgreSQL, privada." }),
  ...shot(12, "Amazon SNS", [
    "Consola → SNS → Topics → servidesk-itsm-events-dev → pestaña Subscriptions.",
    "Mostrar las 7 suscripciones de tipo SQS (si cabe, abrir una y mostrar su filter policy por eventType).",
  ], { caption: "Tópico SNS con las suscripciones de las colas SQS." }),
  ...shot(13, "Amazon SQS", [
    "Consola → SQS → Queues, filtrar por \"servidesk\".",
    "Mostrar las 14 colas: 7 colas -q-dev y sus 7 colas de mensajes fallidos -dlq-dev.",
  ], { caption: "Colas SQS por consumidor con sus DLQ." }),
  ...shot(14, "Amazon S3", [
    "Consola → S3 → Buckets: mostrar los 3 buckets servidesk-seed/attachments/exports-dev-<cuenta>.",
    "Abrir servidesk-seed-dev-<cuenta> → seed/incidents/andina/ y mostrar los .csv.gz y el manifest.json.",
  ], { caption: "Buckets S3 y archivos de la carga de datos." }),
  ...shot(15, "AWS Amplify", [
    "Consola → Amplify → app servidesk: mostrar la rama main desplegada, su estado y la URL pública.",
  ], { caption: "Frontend publicado en AWS Amplify Hosting." }),
  ...shot(16, "CloudWatch Logs del consumidor de eventos", [
    "Consola → CloudWatch → Log groups → /aws/lambda/servidesk-incidents-dev-onCiStatusChanged.",
    "Abrir el log stream más reciente y mostrar la línea \"Incidente automático creado: INC-…\" (aparece después de la Captura 6 o de la prueba de humo).",
  ], { caption: "Log del consumidor SQS creando el incidente automático." }),
  ...shot(17, "Login real contra la API", [
    "Opcional: en Postman o PowerShell, `POST /auth/login` a la URL de identity con andina / lucia.paredes@andina.pe y mostrar la respuesta 200 con access_token.",
  ], { caption: "Login contra API Gateway y token JWT emitido por ms-identity." }),
  ...shot(18, "Demo con 2 tenants", [
    "Abrir dos pestañas del frontend: una con andina (Andina Retail) y otra con pacifico (Clínica Pacífico).",
    "Capturar ambas lado a lado: cada una con su logo, colores y sus propios datos (lista de fallas o tablero).",
  ], { caption: "Demo con dos tenants: cada organización ve solo su información." }),
  ...shot(19, "AWS Secrets Manager", [
    "Consola → Secrets Manager → Secrets: mostrar los secretos de la base de datos (DbSecret) y de la clave JWT (JwtSecret) del stack servidesk-infra-dev.",
    "Opcional: Consola → VPC → Endpoints, mostrar los endpoints de Secrets Manager, SNS y S3 en estado Available.",
  ], { caption: "Credenciales de la BD y clave JWT en AWS Secrets Manager." }),
];

const limitaciones = [
  H1("6. LIMITACIONES Y TRABAJO FUTURO"),
  bullet("**Red y RDS**: la instancia de RDS ya es privada y las credenciales están en Secrets Manager, pero es una sola instancia (Single-AZ) y cada Lambda abre su propia conexión. En producción se usaría Multi-AZ, RDS Proxy para reutilizar conexiones y la rotación automática de secretos (AWS Academy no permite crear el rol que necesita)."),
  bullet("**Publicación de eventos**: los eventos se publican después del COMMIT; si SNS fallara en ese instante, el evento se perdería. Se propone el patrón transactional outbox."),
  bullet("**Alcance funcional**: las tablas de tareas (problem_tasks, change_tasks, fulfillment_tasks) aún no tienen endpoints; los buckets de adjuntos y exportes están provisionados pero no se usan; falta una Lambda programada que marque el SLA vencido y publique IncidentSlaBreached."),
  bullet("**Autenticación**: JWT HS256 con una clave compartida (guardada en Secrets Manager) y sin refresh token (la sesión dura 1 hora). Se propone Amazon Cognito o tokens RS256 con rotación de claves."),
  bullet("**Despliegue**: el frontend se publica en Amplify con un script de despliegue manual; se propone conectar Amplify al repositorio para CI/CD. Serverless Framework v3 ya no recibe nuevas versiones; se evaluaría migrar a v4 o a AWS SAM/CDK."),
  bullet("**CORS** abierto (`*`) en las APIs; en producción se limitaría al dominio de Amplify."),
  H1("7. CONCLUSIONES", false),
  bullet("ServiDesk cumple los requerimientos del proyecto final: es un SaaS de tipo ITSM **multi-tenant, serverless y basado en eventos**, con 6 microservicios protegidos, una base por microservicio en un RDS único con el patrón Single Database, Multiple Schemas, y 30 000 registros por microservicio en 3 tenants."),
  bullet("El **aislamiento por tenant** se apoya en un único punto de verdad (el JWT firmado y el schema que fija la capa común), y se verificó en AWS: los datos de otro tenant responden 404."),
  bullet("La **arquitectura basada en eventos** desacopla los microservicios: un CI caído genera un incidente, la recurrencia crea un problema, el error conocido llega a los incidentes y el cambio implementado actualiza la CMDB y cierra el problema, sin llamadas directas entre servicios."),
  bullet("Las **pruebas contra PostgreSQL real** encontraron errores que los mocks no detectaban (tipos de parámetros, SSL de RDS, empaquetado de la capa) antes de llegar a la nube, y la prueba de humo valida el sistema completo en AWS con un solo comando."),
  bullet("Todo el despliegue es **reproducible**: cualquier integrante puede levantar la solución completa en su cuenta siguiendo `docs/DEPLOY.md`."),
];

// ------------------------------------------------------------------ documento
const portrait = { page: { size: A4, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } };
const landscape = { page: { size: { ...A4, orientation: PageOrientation.LANDSCAPE },
  margin: { top: 900, right: MARGIN, bottom: 900, left: MARGIN } } };

const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
  new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 20 })] })] });

const doc = new Document({
  creator: "Grupo 6 · CS2032",
  title: "Proyecto Final: ServiDesk",
  // El índice lo actualiza Word al exportar (ver README); sin aviso de "actualizar campos" al abrir.
  styles: {
    default: { document: { run: { font: FONT, size: 22 }, paragraph: { spacing: { line: 276 } } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true, color: "000000" },
        paragraph: { spacing: { before: 240, after: 240 }, keepNext: true, keepLines: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 22, color: "000000", underline: {} },
        paragraph: { spacing: { before: 240, after: 200 }, keepNext: true, keepLines: true, outlineLevel: 1 } },
      // Índice como el del proyecto 1: nivel 1 en negrita, nivel 2 con sangría
      { id: "TOC1", name: "toc 1", basedOn: "Normal", next: "Normal",
        run: { font: FONT, size: 22, bold: true }, paragraph: { spacing: { before: 60, after: 0 } } },
      { id: "TOC2", name: "toc 2", basedOn: "Normal", next: "Normal",
        run: { font: FONT, size: 22 }, paragraph: { spacing: { before: 60, after: 0 }, indent: { left: 360 } } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "●", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { size: 16 } } },
      { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 1134, hanging: 283 } } } }] },
    { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: "deploy", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ] },
  sections: [
    { properties: portrait, children: portada },
    { properties: portrait, footers: { default: footer }, children: intro },
    { properties: landscape, footers: { default: footer }, children: [...arquitectura, ...arqFigure] },
    { properties: portrait, footers: { default: footer },
      children: [...arquitectura2, ...backend, ...erFigs, ...backend2, ...frontend, ...despliegue, ...limitaciones] },
  ],
});

const out = path.join(__dirname, "Informe_ServiDesk.docx");
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log("OK", out, `${(buf.length / 1e6).toFixed(1)} MB`); });
