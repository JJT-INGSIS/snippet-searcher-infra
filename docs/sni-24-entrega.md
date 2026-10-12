# SNI-24 — Entrega, commit y descripción de PR

## Cambios para revisar

Rama `feat/sni-24-swarm-bootstrap`, directorio `/Users/thiagoserebrinsky/facultad/projects/ingsis/sni-24-infra`. No se ejecutaron commits, push, PR ni merges de este ticket; tampoco se publicó evidencia en Linear.

- Stack de cinco servicios por digest, volumen de contenido y secretos independientes por Swarm.
- Bootstrap/preflight dev/prod; prod exige evidencia de dev con los mismos digests.
- Registro vigente, bloqueo por ambiente y escritura atómica; actualización de una aplicación y reaplicación sin restaurar referencias anteriores.
- SQL, HTTP interno, persistencia, healthchecks y CI local.
- Operación, límites y resultados reales en `sni-24-bootstrap.md` y `sni-24-evidencia.md`.

## Comandos de commit para ejecutar manualmente

```sh
cd /Users/thiagoserebrinsky/facultad/projects/ingsis/sni-24-infra

git add .gitignore .github/workflows/ci.yml README.md \
  docs/sni-24-bootstrap.md docs/sni-24-evidencia.md docs/sni-24-entrega.md docs/prs-infra-diseno.md \
  swarm/stack.yaml swarm/dev-release.json swarm/prod-release.json \
  scripts/bootstrap_swarm.py scripts/stack_release.py scripts/prepare_swarm_vm.sh \
  scripts/wait_for_stack.py scripts/verify_stack.py scripts/internal_http.py \
  scripts/verify_persistence.py scripts/verify_independent_update.py \
  scripts/validate_stack.py scripts/test_stack_release.py

git commit \
  -m "feat(infra): bootstrap independent Swarm deployments (SNI-24)" \
  -m "Pin verified public images, separate runtime secrets and persistent volumes, preserve current release references on reapply, and verify SQL, internal HTTP and independent updates."
```

La descripción explica la capacidad final de la implementación. Revisar el diff antes de ejecutar el commit. Publicación e integración corresponden al usuario; la base de la PR es `dev`.

## Título de PR

`SNI-24: preparar stack Swarm y bootstrap independiente de dev/prod`

## Descripción de PR

La descripción completa con decisiones, alternativas descartadas, motivos y límites está en [Infra — Descripciones de PR y contexto de diseño](./prs-infra-diseno.md#sni-24--stack-y-bootstrap-manual-devprod). Copiar el bloque de SNI-24; los bloques anteriores corresponden a SNI-20 y SNI-21.
