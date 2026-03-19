# Changelog

Basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/) · [Semantic Versioning](https://semver.org/)

## [Unreleased]

### Planned
- GitHub Actions CI/CD para deploy automático de Lambdas
- Terraform para reproducir infraestructura completa
- Soporte multi-región

---

## [1.1.0] — 2026-03-19

### Added
- Historial persistente de conversaciones en DynamoDB (máx. 200 mensajes por usuario)
- Acciones `get_history` y `clear_history` en Lambda chat
- Banner de historial con resumen al cargar la sesión
- Modal de historial con paginación, búsqueda y botón "Repetir consulta"
- Selector de fechas con calendario interactivo en el modal de reporte
- Shortcuts de período: esta semana, 1–15 mar, 16–31 mar, todo marzo, todo disponible
- Campo "Mensaje personalizado" en el reporte por email
- Timer de sesión visible en la UI con aviso 5 min antes de expirar
- Pantalla de sesión expirada con redirección automática al login
- Auto-refresh de token Cognito vía RefreshToken
- Soporte de fechas exactas `start_date` / `end_date` en ambas Lambdas

### Changed
- Reporte Excel ampliado de 3 a 4 hojas (se agrega hoja de Alertas)
- Sistema de alertas rediseñado en 2 casos distintos (acumulado vs incremento)
- Limpieza de Markdown en el body del email (elimina `**`, `##` del contexto del agente)

### Fixed
- Sesiones Bedrock con clave dual para persistir contexto correctamente
- Ajuste automático de `start_date` al mínimo de datos disponibles en CUR (`2026-03-01`)

---

## [1.0.0] — 2026-03-17

### Added
- Chatbot serverless con Bedrock Agent (Claude Sonnet) para consultas en lenguaje natural
- Consulta de costos AWS desglosada por cuenta via Athena sobre datos CUR
- Reporte Excel (`.xlsx`) con 3 hojas enviado por SES con adjunto
- Autenticación con Amazon Cognito (JWT, flujo `USER_PASSWORD_AUTH`)
- Challenge `NEW_PASSWORD_REQUIRED` para primer login
- Persistencia básica de sesiones en DynamoDB
- Frontend SPA desplegado en S3 + CloudFront (`chat.protecso.io`)
- Soporte multi-cuenta via AWS Organizations API (`list_accounts`)
- 2 Lambdas de Action Group: `get_costs_by_period` y `get_cost_alerts`
- Alertas de consumo: cuentas con acumulado > $500 USD
- Tendencia mensual de últimos 6 meses en reporte Excel
- CORS habilitado en API Gateway para todos los orígenes

[Unreleased]: https://github.com/protecso/aws-cost-chatbot/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/protecso/aws-cost-chatbot/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/protecso/aws-cost-chatbot/releases/tag/v1.0.0
