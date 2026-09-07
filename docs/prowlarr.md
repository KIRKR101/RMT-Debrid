# Prowlarr integration

Prowlarr is an optional scraper that adds releases from its configured
indexers to the Discover page.

## Configuration

Add the Prowlarr URL to `.env`. Add the API key when Prowlarr authentication is
enabled:

```env
PROWLARR_URL=http://localhost:9696
PROWLARR_API_KEY=your-prowlarr-api-key
PROWLARR_RESULT_LIMIT=20
```

When configured, the API key is sent server-side using Prowlarr's `X-Api-Key`
header and is never returned to the browser. Leave it blank if the local
Prowlarr instance does not require authentication.

## Combined results

Torrentio and Prowlarr searches run together when both are configured. Results
are deduplicated by torrent info hash, while retaining every scraper that
returned the release. The Discover page can filter the combined results by
`Torrentio` or `Prowlarr`.

If one scraper is unavailable, results from the other scraper are still
returned. Prowlarr can be left unconfigured to use Torrentio alone.

`PROWLARR_RESULT_LIMIT` controls how many matching Prowlarr releases are
resolved during a normal search. The Discover page also provides a Load More
option that requests a larger result set when needed.
