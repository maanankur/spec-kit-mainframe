# Runbook — <project> target (<environment>)

| Task | Command |
|---|---|
| Start | `cd target && docker compose up -d --build && ops/wait-for-healthy.sh` |
| Health | `curl http://localhost:8080/actuator/health` |
| UI | http://localhost:3000 |
| API docs | http://localhost:8080/swagger |
| Run a batch job | `curl -X POST http://localhost:8080/api/batch/<JOB>/run` |
| Export legacy-format images | `curl -X POST "http://localhost:8080/api/batch/export?suffix=<tag>"` → `target/ops/out/java/` |
| Golden-master comparison | `python <plugin>/scripts/golden_master.py --workspace .` |
| Re-run the legacy chain | `python <plugin>/scripts/legacy_harness.py --workspace .` |
| Use-case coverage | `python <plugin>/scripts/use_case_coverage.py --workspace .` |
| Reset | `docker compose down -v` |
| Logs | `docker compose logs app --tail 200` |

## Rollback
<how to remove the target without touching the legacy; how to flip the gateway route back>

## Alerts that matter
- <job exit codes that mean rejects / abends, with the rule that defines them>
- Any golden-master unexplained difference during dual-run: stop the cutover.
