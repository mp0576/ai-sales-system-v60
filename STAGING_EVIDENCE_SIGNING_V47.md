# v47 — Integridade criptográfica dos relatórios de staging

` scripts/sign_staging_evidence.py` assina um relatório JSON com HMAC-SHA256 e permite verificar posteriormente se o envelope foi alterado.

## Uso

```bash
export STAGING_EVIDENCE_HMAC_KEY='use-a-random-secret-of-at-least-32-bytes'
python scripts/sign_staging_evidence.py staging-security-acceptance.json --output staging-security-acceptance.signed.json
python scripts/sign_staging_evidence.py staging-security-acceptance.signed.json --verify
```

Use uma chave aleatória e exclusiva, entregue por gestor de segredos. Não a inclua no repositório, ZIP, relatório, logs ou tickets. Se a chave for comprometida, rode-a e volte a assinar as evidências. Proteja o acesso ao ficheiro assinado e registe quem recolheu e quem verificou os resultados.

## Limites importantes

- HMAC comprova integridade em relação à chave partilhada, não a identidade individual do autor nem a verdade dos resultados.
- Qualquer pessoa com a chave pode criar uma assinatura válida; a chave não deve estar disponível ao processo de recolha se o verificador tiver de atuar como fronteira de confiança separada.
- O verificador não executa testes, não contacta Supabase e não valida o fornecedor. Um envelope assinado com `NO_GO` continua a ser `NO_GO`.
- O sucesso da assinatura não equivale a autorização de lançamento. A aceitação remota e revisão humana continuam obrigatórias.

The key must be **at least 32 bytes** long. This utility **does not execute tests**. A valid signature is **not a launch authorization**.
