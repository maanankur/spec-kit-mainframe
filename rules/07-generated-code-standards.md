# Rule 7 - Generated code standards

- Java 21, Spring Boot 3.x, Maven, constructor injection, no field injection.
- Package by bounded context, not by layer. ArchUnit enforces module boundaries; no
  cross-module database access.
- No `GOTO`-shaped control flow, no 500-line methods, no paragraph-named classes
  (`ProcessTransactionParagraph` is a JOBOL smell).
- Every public method that implements a business rule links to it in Javadoc via the rule id.
- Validation generated from copybook PIC clauses and legacy edit rules - legacy field
  constraints become explicit Bean Validation, not lost knowledge.
- No secrets in configuration. No `System.out`. Structured logging with correlation ids.
- Transactions are Spring declarative `@Transactional` (chunk transactions in Spring Batch); no
  hand-rolled transaction managers unless an ADR names the cross-resource-manager case.
- Configuration and credentials come from environment variables through Spring profiles. A
  committed `dev` profile carries default local credentials and seed data so verification can
  start the system unattended; `qa` and `prod` read from the environment only.
- Every wave ships a `Dockerfile` and `docker-compose.yml`; the system under test is started
  under compose, never as an in-process JVM in the agent sandbox.
- Module skeleton first: it compiles and passes ArchUnit before the first rule is implemented.
- Every business rule has a unit test; every use case has an integration test; suites create and
  destroy their own data, pass in any order, and run in parallel by default.
