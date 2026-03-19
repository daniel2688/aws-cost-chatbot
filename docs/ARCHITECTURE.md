# 🏗️ Arquitectura — AWS Cost Chatbot

## Diagrama General

![Arquitectura AWS Cost Chatbot](architecture.png)

> Fuente editable: [`aws-cost-chatbot-protecso-v2.drawio`](aws-cost-chatbot-protecso-v2.drawio) — abrir en [diagrams.net](https://app.diagrams.net)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           USUARIOS / NAVEGADOR                               │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ HTTPS
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  CloudFront CDN  (protecso-cur-chat-cdn)                                     │
│  Dominio: chat.protecso.io                                                   │
│  Origin: S3 bucket (SPA index.html)                                          │
└────────────────┬─────────────────────────────────────────────────────────────┘
                 │ Sirve SPA estática
                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  S3 Bucket (Frontend)                                                        │
│  └── index.html  ← SPA completa (Cognito + chat + modal reporte)             │
└──────────────────────────────────────────────────────────────────────────────┘

  Browser ejecuta JS → autenticación Cognito → llamadas a API Gateway

┌──────────────────────────────────────────────────────────────────────────────┐
│  Amazon Cognito User Pool                                                    │
│  Pool:      us-east-1_koWyGhMTX                                             │
│  Client:    protecso-cur-chat (9bk0lu8ablftqsbojch52qfhv)                    │
│  Flujo:     USER_PASSWORD_AUTH → IdToken JWT (60 min)                        │
│  Challenge: NEW_PASSWORD_REQUIRED para primer login                          │
└──────────────────────┬───────────────────────────────────────────────────────┘
                       │ JWT Bearer Token
                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  API Gateway HTTP API  (protecso-cur-chat-api)                               │
│  Base URL: https://h1vw2u75ce.execute-api.us-east-1.amazonaws.com/prod       │
│                                                                              │
│  ┌─────────────────────────┐   ┌──────────────────────────────────────────┐ │
│  │  POST /chat             │   │  POST /send-report                       │ │
│  │  Auth: Cognito JWT      │   │  Auth: Cognito JWT                       │ │
│  │  Integration: Lambda    │   │  Integration: Lambda                     │ │
│  │  protecso-cur-chat      │   │  protecso-cur-report-email               │ │
│  └─────────────┬───────────┘   └─────────────────┬────────────────────────┘ │
└────────────────┼────────────────────────────────┼──────────────────────────┘
                 │                                │
    ┌────────────▼──────────┐       ┌─────────────▼──────────────────────────┐
    │ Lambda                │       │ Lambda                                  │
    │ protecso-cur-chat     │       │ protecso-cur-report-email               │
    │ Python 3.12           │       │ Python 3.12                             │
    │                       │       │ Layer: openpyxl-python312:1             │
    │  1. Lee claims JWT    │       │                                         │
    │  2. DynamoDB get/save │       │  1. Athena Query 1 (top servicios)      │
    │     sesión Bedrock    │       │  2. Athena Query 2 (por cuenta)         │
    │  3. Invoke Agent      │       │  3. Athena Query 3 (tendencia 6m)       │
    │  4. Stream response   │       │  4. Athena Query 4 (diario/alertas)     │
    │  5. Persiste mensajes │       │  5. Organizations list_accounts()       │
    │     en DynamoDB       │       │  6. openpyxl → .xlsx (4 hojas)         │
    └──────────┬────────────┘       │  7. SES send_raw_email con adjunto      │
               │                    └────────────────────────────────────────┘
    ┌──────────▼────────────┐
    │ DynamoDB              │
    │ cur-chat-history      │
    │                       │
    │  PK: session_id       │
    │  Attrs:               │
    │  · bedrock_session    │
    │  · user (email)       │
    │  · messages (max 200) │
    │  · updated_at         │
    └──────────┬────────────┘
               │ (también escribe sesión)
    ┌──────────▼────────────┐
    │ Bedrock Agent         │
    │ ID:    LDJKO1JVKY     │
    │ Alias: QJONGN6CNC     │
    │ Model: Claude Sonnet  │
    │                       │
    │  Recibe pregunta →    │
    │  Razona → decide qué  │
    │  función invocar →    │
    │  genera respuesta NL  │
    └──────────┬────────────┘
               │ Action Group invocation
    ┌──────────▼────────────┐
    │ Lambda                │
    │ cur-athena-action     │
    │ Python 3.12           │
    │                       │
    │  get_costs_by_period  │
    │  get_cost_alerts      │
    └──────────┬────────────┘
               │
    ┌──────────▼──────────────────────────────────────────────────────────────┐
    │ Amazon Athena                                                            │
    │ WorkGroup: primary                                                       │
    │ Database:  aws_costs                                                     │
    │ Table:     data   ← datos CUR (Cost and Usage Report)                   │
    │                                                                          │
    │ Output: s3://athena-cost-by-account-results/athena-results/             │
    └──────────┬──────────────────────────────────────────────────────────────┘
               │ lee datos CUR
    ┌──────────▼──────────────────────────────────────────────────────────────┐
    │ S3 Bucket: athena-cost-by-account-results                                │
    │ ├── /athena-results/    ← resultados de queries                          │
    │ └── /cur/               ← datos CUR sincronizados desde AWS Billing      │
    └─────────────────────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────────────────────┐
    │ AWS Organizations                                                        │
    │ API: list_accounts → mapeo AccountId → AccountName                      │
    │ Usado por: Lambda report + Lambda athena-action                          │
    └─────────────────────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────────────────────┐
    │ Amazon SES (us-east-1)                                                   │
    │ From: daniel.cordero@protecso.com.pe                                     │
    │ Payload: MIMEMultipart con adjunto .xlsx                                 │
    └─────────────────────────────────────────────────────────────────────────┘
```

---

## Flujo 1 — Chat (consulta en lenguaje natural)

```
1. Usuario escribe pregunta en el browser
2. JS obtiene IdToken de Cognito (localStorage)
3. POST /chat → API Gateway valida JWT
4. Lambda cur-chat:
   a. Extrae email de claims JWT
   b. DynamoDB: obtiene bedrock_session (o crea nueva UUID)
   c. bedrock_agent_runtime.invoke_agent() con sessionId
   d. Itera chunks del stream → concatena respuesta
   e. DynamoDB: guarda sesión + append mensajes (max 200)
5. Respuesta en lenguaje natural → renderizada en el chat
```

---

## Flujo 2 — Reporte Excel por Email

```
1. Usuario abre modal → elige período (calendario) + email
2. POST /send-report → API Gateway valida JWT
3. Lambda cur-report-email:
   a. Ajusta start_date al mínimo CUR (2026-03-01)
   b. Ejecuta 4 queries Athena en secuencia (polling cada 2s)
   c. Organizations.list_accounts() → nombres reales
   d. openpyxl → Workbook con 4 hojas + estilos corporativos
   e. io.BytesIO → bytes del .xlsx
   f. SES: MIMEMultipart (HTML body + adjunto .xlsx)
4. Respuesta 200 con total, período, servicios, cuentas
```

---

## Estructura DynamoDB — `cur-chat-history`

| Atributo | Tipo | Descripción |
|---|---|---|
| `session_id` (PK) | String | Clave dual: `email#session_frontend` o `user#email` |
| `bedrock_session` | String | UUID de sesión activa en Bedrock Agent |
| `user` | String | Email del usuario autenticado |
| `messages` | List | Historial de mensajes `{role, content, ts}` (máx. 200) |
| `updated_at` | String | ISO timestamp de última actualización |

**Nota:** Se usan 2 PKs por usuario:
- `email#sessionId` → sesión Bedrock activa (para continuidad de contexto)
- `user#email` → historial persistente de todos los mensajes

---

## Queries Athena Reales

### Query 1 — Top 20 servicios por costo
```sql
SELECT line_item_product_code,
       SUM(line_item_unblended_cost) AS total_cost
FROM data
WHERE line_item_line_item_type = 'Usage'
  AND date(line_item_usage_start_date)
      BETWEEN DATE('start') AND DATE('end')
GROUP BY line_item_product_code
ORDER BY total_cost DESC
LIMIT 20
```

### Query 2 — Costos por cuenta y servicio
```sql
SELECT line_item_usage_account_id,
       line_item_product_code,
       SUM(line_item_unblended_cost) AS total_cost
FROM data
WHERE line_item_line_item_type = 'Usage'
  AND date(line_item_usage_start_date) BETWEEN ...
GROUP BY line_item_usage_account_id, line_item_product_code
ORDER BY total_cost DESC
```

### Query 3 — Tendencia mensual (6 meses)
```sql
SELECT DATE_FORMAT(date_trunc('month', date(...)), '%Y-%m') AS mes,
       line_item_product_code,
       SUM(line_item_unblended_cost) AS total_cost
FROM data
WHERE line_item_line_item_type = 'Usage'
  AND date(...) >= DATE_ADD('month', -6, CURRENT_DATE)
GROUP BY 1, 2
ORDER BY 1, 3 DESC
```

### Query 4 — Costos diarios por cuenta (alertas)
```sql
SELECT line_item_usage_account_id,
       date(line_item_usage_start_date) AS dia,
       SUM(line_item_unblended_cost) AS costo_dia
FROM data
WHERE line_item_line_item_type = 'Usage'
  AND date(...) BETWEEN DATE('start') AND DATE('end')
GROUP BY line_item_usage_account_id, date(line_item_usage_start_date)
ORDER BY line_item_usage_account_id, dia
```

---

## Configuración Bedrock Agent

| Parámetro | Valor |
|---|---|
| Agent ID | `LDJKO1JVKY` |
| Alias producción | `QJONGN6CNC` |
| Modelo base | Claude Sonnet (Bedrock) |
| Action Group | Lambda `protecso-cur-athena-action` |
| Funciones expuestas | `get_costs_by_period`, `get_cost_alerts` |
| Región | `us-east-1` |

> Ver guía completa de configuración en [`bedrock-agent-setup.md`](bedrock-agent-setup.md)

---

## Permisos IAM por Lambda

### `protecso-cur-chat`
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeAgent",
    "dynamodb:GetItem",
    "dynamodb:PutItem"
  ],
  "Resource": [
    "arn:aws:bedrock:us-east-1::agent/LDJKO1JVKY",
    "arn:aws:dynamodb:us-east-1:*:table/cur-chat-history"
  ]
}
```

### `protecso-cur-report-email`
```json
{
  "Effect": "Allow",
  "Action": [
    "athena:StartQueryExecution",
    "athena:GetQueryExecution",
    "athena:GetQueryResults",
    "s3:GetObject",
    "s3:PutObject",
    "ses:SendRawEmail",
    "organizations:ListAccounts"
  ]
}
```

### `protecso-cur-athena-action`
```json
{
  "Effect": "Allow",
  "Action": [
    "athena:StartQueryExecution",
    "athena:GetQueryExecution",
    "athena:GetQueryResults",
    "s3:GetObject",
    "s3:PutObject",
    "organizations:ListAccounts"
  ]
}
```

> Ver policy completo en [`../iam/lambda-policy.json`](../iam/lambda-policy.json)
