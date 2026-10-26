# v60 — Primeiro ciclo comercial: captar pedidos de demonstração

## O que passa a existir

- Página comercial em português em `/offer`.
- Formulário de pedido de demonstração ligado a `POST /api/v1/public/demo-requests`.
- Persistência SQLite durável, chave de idempotência, honeypot, consentimento explícito e limite de cinco pedidos por email por hora.
- Fila interna para consultar pedidos e atualizar o estado comercial (`NEW`, `CONTACTED`, `QUALIFIED`, `WON`, `LOST`).

## Executar localmente

```bash
python -m pip install -r requirements-runtime.txt
export DASHBOARD_API_TOKEN='token-local-dashboard-com-mais-de-16-caracteres'
export PUBLIC_INTAKE_ADMIN_TOKEN='cria-um-token-aleatorio-com-pelo-menos-24-caracteres'
export PUBLIC_INTAKE_DATABASE_PATH='data/public_demo_requests.sqlite3'
uvicorn app.dashboard.api:app --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000/offer`. Os pedidos ficam guardados em `data/public_demo_requests.sqlite3`.

## Operar a fila interna

```bash
curl -H "Authorization: Bearer $PUBLIC_INTAKE_ADMIN_TOKEN" \
  'http://127.0.0.1:8000/api/v1/admin/demo-requests?status=NEW'
```

Atualizar o estado:

```bash
curl -X PATCH \
  -H "Authorization: Bearer $PUBLIC_INTAKE_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"status":"CONTACTED"}' \
  'http://127.0.0.1:8000/api/v1/admin/demo-requests/REQUEST_ID'
```

## Limitações e passos obrigatórios antes de lançar

- SQLite é adequado para desenvolvimento/piloto numa única instância; para múltiplas instâncias, mover a fila para PostgreSQL/Supabase.
- A rota administrativa usa um token dedicado e não é um sistema completo de utilizadores/roles. Guardar o token num gestor de segredos e usar HTTPS.
- Antes de publicar: substituir o nome comercial genérico pelos dados reais da entidade, acrescentar política de privacidade e contactos legais, validar base jurídica/consentimento RGPD e política de retenção.
- Não existe ainda email automático, calendário, checkout, faturação ou aquisição outbound. O formulário confirma receção, mas o contacto comercial ainda é manual.
- Os preços na página são hipóteses comerciais indicativas e não uma proposta contratual.
- Não enviar dados pessoais de leads imobiliários neste formulário; é apenas para captar potenciais agências clientes.

## Testes

`tests/test_v60_commercial_intake.py` cobre página e submissão, idempotência, fila protegida, atualização de estado, validação, persistência e limite por email.
