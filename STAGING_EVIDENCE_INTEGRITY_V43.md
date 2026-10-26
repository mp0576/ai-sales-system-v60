# v43 — Verificação da integridade das evidências de staging

## O que muda

O verificador de manifesto já não se limita a verificar a forma do JSON quando é executado pela CLI: exige `--evidence-root`, abre cada artefacto referenciado, rejeita caminhos absolutos, traversal (`..`), symlinks, ficheiros inexistentes, conteúdo vazio e hashes SHA-256 divergentes. Qualquer erro mantém a decisão em `NO-GO`.

## Utilização

Para um manifesto criado pelo runner v40, em que as referências são relativas à pasta de saída:

```bash
python scripts/verify_staging_rehearsal.py \
  staging-rehearsal-output/rehearsal-manifest.json \
  --evidence-root staging-rehearsal-output \
  --report staging-rehearsal-output/verification-report.json
```

A raiz de evidências deve conter os ficheiros efetivamente recolhidos. Não apontar para uma pasta diferente para contornar referências em falta. O verificador não executa comandos nem liga à rede; apenas verifica artefactos locais.

## Limitações

Hashes válidos demonstram que o conteúdo corresponde ao digest declarado, não provam que um teste foi executado honestamente ou que o ambiente remoto é seguro. A decisão positiva é apenas `GO_FOR_MANUAL_REVIEW`; nunca autorização de lançamento. As provas de concorrência PostgreSQL e idempotência do fornecedor continuam a exigir staging real e sandbox.
