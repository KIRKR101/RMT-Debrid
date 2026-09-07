# Torrentio integration

The Discover page uses Torrentio to search movie and series releases. It
supports whole-show, season, and episode searches, and sends selected releases
to either Real-Debrid directly or the local download queue.

## Configuration

Torrentio is enabled by default with the public endpoint:

```env
TORRENTIO_URL=https://torrentio.strem.fun
TORRENTIO_FILTER=
```

If `TORRENTIO_URL` is omitted, the same public endpoint is used. Set it to a
different Torrentio-compatible endpoint to use a self-hosted or alternate
instance.

`TORRENTIO_FILTER` is optional. It may contain a configured Torrentio filter,
including an RD key, for example:

```env
TORRENTIO_FILTER=sort=qualitysize|qualityfilter=threed,other,scr,cam,unknown|realdebrid=YOUR_RD_KEY
```

The filter is appended to server-side requests and is never sent to the
browser.

If `TORRENTIO_URL` is explicitly set to an empty or invalid value, title
search continues to work but release searches return an error. Leaving it
unset is the recommended zero-configuration setup.
