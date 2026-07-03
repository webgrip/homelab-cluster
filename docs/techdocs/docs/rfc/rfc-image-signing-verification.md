# RFC: Image signing & verification — record the Transit anchor, own the enforce path

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** The cluster's image-signing trust anchor quietly became **OpenBao Transit** — the
> cosign private key lives in `transit/keys/cosign-webgrip` and never leaves the vault; CI signs
> via the transit API; a CronJob mirrors trusted public-key versions into a ConfigMap that three
> Kyverno verify policies consume. That's a genuinely strong design that **no record describes** —
> the [security-hardening RFC](rfc-security-hardening.md) still narrates a "GitHub-OIDC →
> Authentik re-anchor" that reality bypassed. Meanwhile all three verify policies sit in Audit
> with no owned promotion path, and two SBOM platforms (Dependency-Track *and* GUAC) ingest the
> same weekly SBOMs without a recorded reason for running both.

## Why

The pipeline as built (verified in-tree 2026-07-02):

- **Signing**: `openbao/bootstrap/init.sh` creates Transit key `cosign-webgrip` (ECDSA-P256);
  CI signs via `transit/sign` under the `cosign-signer` policy — the private key is never
  exportable. Rotation has a [runbook](../runbooks/cosign-transit-key-rotation.md).
- **Trust distribution**: the `cosign-pubkey-publish` CronJob (30 min, fail-soft) reads every
  still-trusted key version and writes them to the `cosign-webgrip-pub` ConfigMap.
- **Verification** (all **Audit**, `failurePolicy: Ignore`): `image-verify-harbor-audit`
  (signature + CycloneDX attestation on `harbor.${SECRET_DOMAIN}/webgrip/*`),
  `image-verify-audit` (ghcr `webgrip/*` by key; `kyverno/*` keyless), and
  `image-attestations-audit` (SBOM attestations).
- **SBOM analysis, twice**: `trivy-sbom-uploader` (weekly) scans running images → CycloneDX →
  Dependency-Track *and* drops the same SBOMs in Garage where the `guac-s3-collector` (weekly,
  +3h) ingests them into GUAC (ent/Postgres/NATS + its own collectors and certifiers).

Three gaps:

1. **The anchor decision is unrecorded and the existing docs contradict it.** Choosing
   vault-held Transit signing over keyless (Fulcio/Rekor with Authentik OIDC) or a static cosign
   keypair was the most consequential supply-chain call since Harbor — it trades transparency-log
   ecosystem-fit for sovereignty and non-exportability (`rekor.ignoreTlog: true` follows from
   it). It exists only as `init.sh` + policy YAML, while rfc-security-hardening still points at
   the superseded Authentik-keyless plan.
2. **Enforce has no owner.** ADR-0032 built the promotion machinery and ADR-0033 decided the
   *registries* rule stays Audit — but nobody owns promoting the *verify* policies. The wave
   exists in principle; scoping it (start: `harbor webgrip/*` signatures — narrow, all first-party,
   no Harbor-SPOF concern beyond what ADR-0033 already analyzed) is this RFC's job. Note the
   circularity to resolve: verification must not block the components that produce/serve
   verification (harbor itself, openbao, kyverno).
3. **DT + GUAC duplication is undecided.** Two platforms, two databases (one un-barman'd — see
   the [Postgres RFC](rfc-postgres-data-layer.md)), two weekly pipelines, one SBOM source. GUAC
   adds graph analysis (dependency blast-radius queries) over DT's VEX/policy/alerting — but
   whether that justifies double the footprint on this hardware has never been weighed. The
   [supply-chain docs](../general/supply-chain-overview.md) describe both without choosing.

## Proposal

1. **Backfill the anchor ADR** (retroactive): OpenBao Transit as the signing anchor — context,
   the keyless/static alternatives, the `ignoreTlog` consequence, key-rotation model (multi-version
   trust via the ConfigMap), and the accepted coupling: **OpenBao availability gates CI signing**.
   Update rfc-security-hardening's stale re-anchor language to point here.
2. **Scope the verify-enforce wave** (new ADR, executes via ADR-0032 machinery):
   `image-verify-harbor` signatures → Enforce first (first-party images only, small blast
   radius), attestations next, ghcr third; each wave gated on a clean PolicyReport per ADR-0032,
   with the verification-infrastructure namespaces carved out to break the circularity.
3. **Decide the SBOM-platform question** (new ADR): keep both with recorded roles (DT =
   operational CVE triage/alerting, GUAC = graph forensics), or consolidate to DT and shelve GUAC
   until a graph question actually arises. Leaning: consolidate — the
   [supply-chain-cve-triage flow](../general/supply-chain-cve-triage.md) runs entirely on DT
   today, and GUAC's marginal value is speculative while its footprint (Postgres + NATS + 5
   workloads) is concrete.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | OpenBao Transit as the image-signing trust anchor (retroactive) |
| candidate | — | Verify-policy enforce waves, first-party first (new) |
| candidate | — | SBOM platform: consolidate on DT vs dual-run with recorded roles (new) |

## Out of scope

- `require-approved-registries` — decided, stays Audit ([ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md)).
- The promotion *mechanism* — [ADR-0032](../adr/adr-0032-kyverno-enforce-promotion-policy.md).
- CI build isolation (rootless BuildKit) — [ADR-0026](../adr/adr-0026-rootless-ci-image-builds.md).

## References

- [supply-chain-overview](../general/supply-chain-overview.md) ·
  [supply-chain-pipeline](../general/supply-chain-pipeline.md) ·
  [cosign-transit-key-rotation runbook](../runbooks/cosign-transit-key-rotation.md)
- [RFC: security hardening](rfc-security-hardening.md) — the stale re-anchor narrative this supersedes
