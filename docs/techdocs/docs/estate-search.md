# Estate search

One search box over every repo's docs on this domain — each site keeps its own
Pagefind index; this page merges them in your browser
([multisite](https://pagefind.app/docs/multisite/); same-domain, no server).

<link href="/pagefind/pagefind-ui.css" rel="stylesheet">
<script src="/pagefind/pagefind-ui.js"></script>
<div id="estate-search"></div>
<script>
window.addEventListener('DOMContentLoaded', () => {
  new PagefindUI({
    element: "#estate-search",
    showSubResults: true,
    mergeIndex: [
      { bundlePath: "/infrastructure/pagefind", mergeFilter: { repo: "infrastructure" } },
      { bundlePath: "/workflows/pagefind", mergeFilter: { repo: "workflows" } },
      { bundlePath: "/telemetry-service/pagefind", mergeFilter: { repo: "telemetry-service" } },
      { bundlePath: "/ledgerflow/pagefind", mergeFilter: { repo: "ledgerflow" } },
      { bundlePath: "/monitoring-platform/pagefind", mergeFilter: { repo: "monitoring-platform" } },
      { bundlePath: "/searxng-application/pagefind", mergeFilter: { repo: "searxng-application" } },
      { bundlePath: "/freshrss-application/pagefind", mergeFilter: { repo: "freshrss-application" } },
      { bundlePath: "/invoiceninja-application/pagefind", mergeFilter: { repo: "invoiceninja-application" } },
      { bundlePath: "/action-typescript-template/pagefind", mergeFilter: { repo: "action-typescript-template" } },
      { bundlePath: "/application-template/pagefind", mergeFilter: { repo: "application-template" } },
      { bundlePath: "/backstage-application/pagefind", mergeFilter: { repo: "backstage-application" } },
    ],
  });
});
</script>

!!! note
    A repo appears here after its next docs publish (the Pagefind pass shipped
    2026-08-11); missing bundles are skipped gracefully.
