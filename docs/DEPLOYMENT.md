# 🚀 Guía de Despliegue — AWS Cost Chatbot

## Requisitos Previos

- AWS CLI configurado (`aws configure`) con perfil `AdministratorAccess`
- Cuenta gestionada por AWS Organizations
- Python 3.12 instalado localmente
- Bucket S3 de datos CUR ya configurado (`athena-cost-by-account-results`)
- SES verificado para `daniel.cordero@protecso.com.pe`

---

## 1. Lambda — `protecso-cur-chat`

Sin dependencias externas (solo `boto3`, incluido en el runtime base).

```bash
cd src/chat

# Empaquetar
zip function.zip lambda_function.py

# Desplegar
aws lambda update-function-code \
  --function-name protecso-cur-chat \
  --zip-file fileb://function.zip \
  --region us-east-1

# Verificar
aws lambda get-function-configuration \
  --function-name protecso-cur-chat \
  --region us-east-1 | grep LastModified
```

**Variables de entorno requeridas:**
```
AGENT_ID      = LDJKO1JVKY
AGENT_ALIAS   = QJONGN6CNC
HISTORY_TABLE = cur-chat-history
```

---

## 2. Lambda — `protecso-cur-report-email`

Requiere `openpyxl`. Se gestiona como **Lambda Layer** (ya existente: `openpyxl-python312:1`).

```bash
cd src/report

# Solo empaquetar el código (openpyxl viene del Layer)
zip function.zip lambda_function.py

# Desplegar
aws lambda update-function-code \
  --function-name protecso-cur-report-email \
  --zip-file fileb://function.zip \
  --region us-east-1
```

**Variables de entorno requeridas:**
```
ATHENA_DATABASE = aws_costs
ATHENA_TABLE    = data
ATHENA_OUTPUT   = s3://athena-cost-by-account-results/athena-results/
SES_FROM_EMAIL  = daniel.cordero@protecso.com.pe
```

**Layer adjunto:**
```
arn:aws:lambda:us-east-1:989663408506:layer:openpyxl-python312:1
```

---

## 3. Lambda — `protecso-cur-athena-action`

Sin dependencias externas.

```bash
cd src/athena_action

zip function.zip lambda_function.py

aws lambda update-function-code \
  --function-name protecso-cur-athena-action \
  --zip-file fileb://function.zip \
  --region us-east-1
```

**Variables de entorno opcionales (con defaults):**
```
ATHENA_DATABASE = aws_costs          # default en código
ATHENA_TABLE    = data               # default en código
ATHENA_OUTPUT   = s3://athena-cost-by-account-results/athena-results/
```

---

## 4. Frontend — S3 + CloudFront

```bash
# Subir SPA al bucket frontend
aws s3 cp frontend/index.html s3://<BUCKET_FRONTEND_NAME>/ \
  --content-type "text/html" \
  --cache-control "no-cache, no-store, must-revalidate"

# Invalidar caché de CloudFront
aws cloudfront create-invalidation \
  --distribution-id <CLOUDFRONT_DISTRIBUTION_ID> \
  --paths "/*"
```

> Reemplazar `<BUCKET_FRONTEND_NAME>` y `<CLOUDFRONT_DISTRIBUTION_ID>` con los valores reales de tu entorno.

---

## 5. API Gateway — Verificar Rutas

Las rutas deben estar configuradas en `protecso-cur-chat-api`:

| Método | Ruta | Lambda | Auth |
|---|---|---|---|
| POST | `/chat` | `protecso-cur-chat` | Cognito JWT |
| POST | `/send-report` | `protecso-cur-report-email` | Cognito JWT |
| OPTIONS | `/*` | (CORS) | Ninguna |

```bash
# Verificar estado del API
aws apigatewayv2 get-apis --region us-east-1
```

---

## 6. DynamoDB — Crear Tabla (si no existe)

```bash
aws dynamodb create-table \
  --table-name cur-chat-history \
  --attribute-definitions AttributeName=session_id,AttributeType=S \
  --key-schema AttributeName=session_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

---

## 7. Verificación Post-Deploy

```bash
# 1. Probar endpoint /chat
curl -X POST https://h1vw2u75ce.execute-api.us-east-1.amazonaws.com/prod/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"action":"chat","message":"hola","session_id":"test-01"}'

# 2. Verificar logs Lambda
aws logs tail /aws/lambda/protecso-cur-chat --follow --region us-east-1

# 3. Verificar DynamoDB tiene registros
aws dynamodb scan \
  --table-name cur-chat-history \
  --select COUNT \
  --region us-east-1
```

---

## Checklist de Deploy

- [ ] Lambda `protecso-cur-chat` actualizada y con variables de entorno
- [ ] Lambda `protecso-cur-report-email` actualizada con Layer `openpyxl-python312:1`
- [ ] Lambda `protecso-cur-athena-action` actualizada
- [ ] `index.html` subido a S3 frontend
- [ ] CloudFront invalidado
- [ ] Athena puede consultar `aws_costs.data`
- [ ] SES puede enviar desde `daniel.cordero@protecso.com.pe`
- [ ] Prueba end-to-end: login → chat → reporte por email
