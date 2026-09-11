# Rule 5 - Data handling and PII

Production datasets are masked or synthesized *before* any agent can read them. The masking
is format-preserving so copybook offsets stay valid.

- `dataset_pii_guard.py` blocks reads of unmasked dataset paths.
- Field-level PII classification is recorded in the graph during discovery.
- No production data value ever appears in an artifact, a graph node, or a prompt.
- Golden masters use masked or synthetic data with preserved statistical and boundary
  properties.
