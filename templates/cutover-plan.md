# Cutover plan — <project>, <wave>

**What is deployed:** <database, application, UI — the compose services and the profile they run on>. <Where the seed/migrated data came from.>

**What this is not:** <state plainly if this is a development deployment: no qa/prod profile, no secrets manager, no TLS, no OIDC, no pipeline>.

## Coexistence position (ADR on coexistence)
<Which side is the system of record for each context. What the target writes. Whether the gateway/strangler routing is deployed.>

## Cutover sequence for a real wave (after its G6)
1. Freeze the wave's legacy stores; take the final unload; run `5-data/migration/decode_all.sh` → `load.sql` → `reconcile.sql`; sums to the cent or stop.
2. Point the gateway route for the wave's transactions at the target; keep the legacy route as the kill switch.
3. Dual-run the wave's batch jobs for one full cycle; `golden_master.py`; zero unexplained or roll back.
4. Retire the legacy copy of the store only after the reconciliation job has run clean for the agreed period.

## Rollback
<Exact commands. What was changed on the legacy side (should be nothing). How writes captured during dual-run are replayed.>
