# Real-Debrid API Reference

> Comprehensive Markdown transcription and reorganisation of the public Real-Debrid API documentation at `https://api.real-debrid.com/`, checked 5 September 2026.
>
> This document preserves the technical content of the reference — endpoints, parameters, response fields, status codes, authentication workflows, limits, and embedded schema fragments — while reorganising and rewording the explanatory prose for easier use.

## Contents

- [General implementation details](#general-implementation-details)
- [REST API](#rest-api)
  - [Root methods](#root-methods)
  - [User](#user)
  - [Unrestrict](#unrestrict)
  - [Traffic](#traffic)
  - [Streaming](#streaming)
  - [Downloads](#downloads)
  - [Torrents](#torrents)
  - [Hosts](#hosts)
  - [Settings](#settings)
  - [Support](#support)
- [Response schemas](#response-schemas)
- [Example REST call](#example-rest-call)
- [Authentication](#authentication)
- [OAuth2 authentication for applications](#oauth2-authentication-for-applications)
  - [Open-source applications](#open-source-applications)
  - [Website / client application workflow](#website--client-application-workflow)
  - [Mobile-device workflow](#mobile-device-workflow)
  - [Open-source application workflow](#open-source-application-workflow)
  - [Legacy application workflow](#legacy-application-workflow)
  - [Two-factor authentication](#two-factor-authentication)
  - [Refreshing an access token](#refreshing-an-access-token)
- [Numeric API error codes](#numeric-api-error-codes)
- [Embedded schema fragments without a public method heading](#embedded-schema-fragments-without-a-public-method-heading)

---

## General implementation details

REST base URL:

```text
https://api.real-debrid.com/rest/1.0/
```

OAuth2 base URL:

```text
https://api.real-debrid.com/oauth/v2/
```

The API is divided into namespaces such as `user`, `unrestrict`, `torrents`, and `settings`.

Supported HTTP methods are:

- `GET`
- `POST`
- `PUT`
- `DELETE`

A client that cannot issue one of these verbs can override the request method through the `X-HTTP-Verb` HTTP header.

Unless an endpoint explicitly says otherwise, a successful request returns HTTP `200` and a JSON object.

Errors use HTTP `4xx` or `5xx` responses and return a JSON object containing:

```json
{
  "error": "human-readable error message",
  "error_code": 0
}
```

`error_code` is optional. Applications should use the numeric error code when available rather than parsing the human-readable string.

All strings sent to or returned by the API must use UTF-8. For maximum compatibility, Real-Debrid recommends Unicode Normalisation Form C (NFC) before UTF-8 encoding.

The API:

- emits `ETag` response headers;
- supports the `If-None-Match` request header;
- represents dates in the format produced by JavaScript's `Date.prototype.toJSON()`;
- requires authentication by default unless an endpoint is explicitly documented as public.

### Rate limit

The documented global limit is:

```text
250 requests per minute
```

Rejected requests still count towards the limit. Requests exceeding the limit receive HTTP `429`. The documentation warns that brute-forcing can lead to a block for an unspecified period.

---

# REST API

## Root methods

### `GET /disable_access_token`

Disables the access token currently used for the request.

Authentication: required.

Success:

```text
HTTP 204
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |

---

### `GET /time`

Returns the Real-Debrid server time as raw text.

Authentication: not required.

Response format:

```text
Y-m-d H:i:s
```

---

### `GET /time/iso`

Returns the Real-Debrid server time as raw text using an ISO-style representation.

Authentication: not required.

Response format:

```text
Y-m-dTH:i:sO
```

---

## User

### `GET /user`

Returns information about the authenticated user.

Authentication: required.

Response: [User schema](#user-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

## Unrestrict

### `POST /unrestrict/check`

Tests whether a file at a hoster link can be downloaded.

Authentication: not required.

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `link` | yes | string | Original hoster URL |
| POST body | `password` | no | string | Password required by the hoster, if any |

Response: [Link-check schema](#link-check-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 503 | File unavailable |

---

### `POST /unrestrict/link`

Takes an original hoster URL and generates an unrestricted download URL.

Authentication: required.

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `link` | yes | string | Original hoster URL |
| POST body | `password` | no | string | Hoster-side password |
| POST body | `remote` | no | int | `0` or `1`; uses Remote traffic, with dedicated-server and account-sharing protections lifted |

A request can produce either:

- one generated link: [Unique unrestricted-link schema](#unique-unrestricted-link-schema); or
- multiple generated choices, such as for YouTube: [Multi-option unrestricted-link schema](#multi-option-unrestricted-link-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `POST /unrestrict/folder`

Expands a supported hoster folder URL into its individual links.

Authentication: required.

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `link` | yes | string | Hoster folder URL |

If no links are found, the API returns an empty array.

Response shape: array of URL strings.

```json
[
  "string",
  "string",
  "string"
]
```

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `PUT /unrestrict/containerFile`

Decrypts an uploaded download-container file.

Supported container formats listed by the documentation:

- RSDF
- CCF
- CCF3
- DLC

Authentication: required.

The endpoint accepts the container file as the request payload; the current documentation does not publish a named parameter table for it.

Response shape: array of URL strings.

```json
[
  "string",
  "string",
  "string"
]
```

Errors:

| HTTP | Meaning |
|---:|---|
| 400 | Bad request; inspect the API error message |
| 401 | Token is invalid or expired |
| 403 | Permission denied; account locked or not Premium |
| 503 | Service unavailable; inspect the API error message |

---

### `POST /unrestrict/containerLink`

Downloads and decrypts a container file from an HTTP URL.

Authentication: required.

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `link` | yes | string | HTTP URL of the container file |

Response shape: array of URL strings.

```json
[
  "string",
  "string",
  "string"
]
```

Errors:

| HTTP | Meaning |
|---:|---|
| 400 | Bad request; inspect the API error message |
| 401 | Token is invalid or expired |
| 403 | Permission denied; account locked or not Premium |
| 503 | Service unavailable; inspect the API error message |

---

## Traffic

### `GET /traffic`

Returns traffic limits and usage information for hosters whose traffic is limited, including current consumption and extra traffic packages.

Authentication: required.

Response: [Traffic schema](#traffic-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `GET /traffic/details`

Returns per-hoster traffic usage over a date range.

Authentication: required.

Query parameters:

| Name | Required | Type | Default | Meaning |
|---|:---:|---|---|---|
| `start` | no | `YYYY-MM-DD` date | one week ago | First day of the period |
| `end` | no | `YYYY-MM-DD` date | today | Last day of the period |

The requested period may not exceed 31 days.

Response: [Traffic-details schema](#traffic-details-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

## Streaming

### `GET /streaming/transcode/{id}`

Returns transcoding/streaming links for a file.

`{id}` is a file identifier obtained from `/downloads` or `/unrestrict/link`.

Authentication: required.

Response: [Transcoding schema](#transcoding-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `GET /streaming/mediaInfos/{id}`

Returns detailed media metadata for a file.

`{id}` is obtained from `/downloads` or `/unrestrict/link`.

Authentication: required.

Response: [Media-information schema](#media-information-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |
| 503 | Service unavailable because media metadata could not be found |

---

## Downloads

### `GET /downloads`

Returns the authenticated user's generated-download history/list.

Authentication: required.

Query parameters:

| Name | Required | Type | Meaning |
|---|:---:|---|---|
| `offset` | no | int | Starting offset; must be between zero and the value of the `X-Total-Count` response header |
| `page` | no | int | Page-based pagination |
| `limit` | no | int | Entries per response; range zero to 5000; default `100` |

Do not use `offset` and `page` together. If both are present, `page` takes precedence.

Response: [Downloads-list schema](#downloads-list-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `DELETE /downloads/delete/{id}`

Removes a generated link from the user's downloads list.

Authentication: required.

Success:

```text
HTTP 204
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |
| 404 | Unknown resource |

---

## Torrents

### `GET /torrents`

Returns the user's torrent list.

Authentication: required.

Query parameters:

| Name | Required | Type | Meaning |
|---|:---:|---|---|
| `offset` | no | int | Starting offset; must be between zero and `X-Total-Count` |
| `page` | no | int | Page-based pagination |
| `limit` | no | int | Entries per request; zero to 5000; default `100` |
| `filter` | no | string | Set to `"active"` to return only active torrents |

Do not use `offset` and `page` together. If both are supplied, `page` takes precedence.

Response: [Torrent-list schema](#torrent-list-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `GET /torrents/info/{id}`

Returns detailed information for a torrent.

Authentication: required.

Response: [Torrent-information schema](#torrent-information-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `GET /torrents/activeCount`

Returns the current number of active torrents and the account's maximum active-torrent allowance.

Authentication: required.

Response:

```json
{
  "nb": 0,
  "limit": 0
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `nb` | int | Current number of active torrents |
| `limit` | int | Maximum number of active torrents permitted |

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `GET /torrents/availableHosts`

Returns hosters to which a torrent can be uploaded.

Authentication: required.

Response:

```json
[
  {
    "host": "string",
    "max_file_size": 0
  }
]
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `host` | string | Hoster's main domain |
| `max_file_size` | int | Maximum supported split size |

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `PUT /torrents/addTorrent`

Uploads a `.torrent` file and creates a torrent resource.

Authentication: required.

Success:

```text
HTTP 201
```

Query parameter:

| Name | Required | Type | Meaning |
|---|:---:|---|---|
| `host` | no | string | Hoster domain obtained from `/torrents/availableHosts` |

The torrent file itself is uploaded as the request body; the current parameter table labels only `host`.

Response:

```json
{
  "id": "string",
  "uri": "string"
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | ID of the created torrent |
| `uri` | string | URL of the created resource |

Errors:

| HTTP | Meaning |
|---:|---|
| 400 | Bad request; inspect the API error |
| 401 | Token is invalid or expired |
| 403 | Permission denied; account locked or not Premium |
| 503 | Service unavailable; inspect the API error |

---

### `POST /torrents/addMagnet`

Creates a torrent from a magnet URI.

Authentication: required.

Success:

```text
HTTP 201
```

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `magnet` | yes | string | Magnet URI |
| POST body | `host` | no | string | Hoster domain obtained from `/torrents/availableHosts` |

Response:

```json
{
  "id": "string",
  "uri": "string"
}
```

Errors:

| HTTP | Meaning |
|---:|---|
| 400 | Bad request; inspect the API error |
| 401 | Token is invalid or expired |
| 403 | Permission denied; account locked or not Premium |
| 503 | Service unavailable; inspect the API error |

---

### `POST /torrents/selectFiles/{id}`

Selects which files of a torrent should be downloaded and starts the torrent.

Authentication: required.

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `files` | yes | string | Comma-separated file IDs, or the literal string `"all"` |

Retrieve valid file IDs first with:

```text
GET /torrents/info/{id}
```

Normal success:

```text
HTTP 204
```

Response body: none.

Errors and alternate statuses:

| HTTP | Meaning |
|---:|---|
| 202 | The requested action has already been performed |
| 400 | Bad request; inspect the API error |
| 401 | Token is invalid or expired |
| 403 | Permission denied; account locked or not Premium |
| 404 | Invalid file ID(s), or invalid/unknown torrent ID |

---

### `DELETE /torrents/delete/{id}`

Deletes a torrent from the user's torrent list.

Authentication: required.

Success:

```text
HTTP 204
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |
| 404 | Unknown resource |

---

## Hosts

### `GET /hosts`

Returns supported hosters.

Authentication: not required.

Response: [Hosts schema](#hosts-schema).

---

### `GET /hosts/status`

Returns the status of hosters, including whether Real-Debrid supports them and status information reported for competitors.

Authentication: required by the documentation's default rule; this method is not explicitly marked public.

Response: [Host-status schema](#host-status-schema).

---

### `GET /hosts/regex`

Returns regular expressions matching supported file links. Intended for discovering supported URLs inside arbitrary documents.

Authentication: not required.

Response shape: array of regular-expression strings.

```json
[
  "string",
  "string",
  "string"
]
```

---

### `GET /hosts/regexFolder`

Returns regular expressions matching supported hoster-folder links. Intended for discovering folder URLs inside arbitrary documents.

Authentication: not required.

Response shape: array of regular-expression strings.

```json
[
  "string",
  "string",
  "string"
]
```

---

### `GET /hosts/domains`

Returns all supported hoster domains.

Authentication: not required.

Response:

```json
[
  "string",
  "string",
  "string"
]
```

Each element is a domain name.

---

## Settings

### `GET /settings`

Returns the authenticated user's current settings together with the available values for configurable settings.

Authentication: required.

Response: [Settings schema](#settings-schema).

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `POST /settings/update`

Updates one user setting.

Authentication: required.

Success:

```text
HTTP 204
```

Parameters:

| Location | Name | Required | Type | Meaning |
|---|---|:---:|---|---|
| POST body | `setting_name` | yes | string | Name of the setting |
| POST body | `setting_value` | yes | string | New value; valid values are returned by `GET /settings` |

Accepted documented `setting_name` values:

```text
download_port
locale
streaming_language_preference
streaming_quality
mobile_streaming_quality
streaming_cast_audio_preference
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 400 | Invalid setting name or value |
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `POST /settings/convertPoints`

Converts fidelity points.

Authentication: required.

Success:

```text
HTTP 204
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |
| 503 | Insufficient fidelity points |

---

### `POST /settings/changePassword`

Requests the verification email used to change the account password.

Authentication: required.

Success:

```text
HTTP 204
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `PUT /settings/avatarFile`

Uploads a replacement user-avatar image.

Authentication: required.

Success:

```text
HTTP 204
```

The current documentation does not publish a named parameter table for the uploaded image payload.

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 400 | Bad request; inspect the API error |
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

### `DELETE /settings/avatarDelete`

Resets the user's avatar to the default image.

Authentication: required.

Success:

```text
HTTP 204
```

Response body: none.

Errors:

| HTTP | Meaning |
|---:|---|
| 401 | Token is invalid or expired |
| 403 | Permission denied because the account is locked |

---

## Support

The current public documentation contains a `/support` namespace heading but no public support method headings beneath it. The page does, however, embed support/forum-related response schemas. Those are preserved in [Embedded schema fragments without a public method heading](#embedded-schema-fragments-without-a-public-method-heading).

---

# Response schemas

The schemas below preserve all fields and conditions documented on the current reference page. They are schema examples rather than guaranteed literal values.

## User schema

```js
{
  "id": int,
  "username": "string",
  "email": "string",
  "points": int,       // Fidelity points
  "locale": "string",  // User language
  "avatar": "string",  // URL
  "type": "string",    // "premium" or "free"
  "premium": int,      // seconds remaining as a Premium user
  "expiration": "string" // jsonDate
}
```

---

## Link-check schema

Used by `POST /unrestrict/check`.

```js
{
  "host": "string",      // hoster's main domain
  "link": "string",
  "filename": "string",
  "filesize": int,
  "supported": int
}
```

---

## Unique unrestricted-link schema

Used when `POST /unrestrict/link` generates one link.

```js
{
  "id": "string",
  "filename": "string",
  "mimeType": "string", // MIME type guessed from the file extension
  "filesize": int,      // bytes; 0 when unknown
  "link": "string",     // original link
  "host": "string",     // hoster's main domain
  "chunks": int,        // maximum chunks allowed
  "crc": int,           // CRC checking disabled/enabled
  "download": "string", // generated unrestricted URL
  "streamable": int     // whether it can be streamed on the website
}
```

---

## Multi-option unrestricted-link schema

The documentation gives this variant for a generated link that has quality/type alternatives.

```js
{
  "id": "string",
  "filename": "string",
  "filesize": int,      // bytes; 0 when unknown
  "link": "string",     // original link
  "host": "string",     // hoster's main domain
  "chunks": int,        // maximum chunks allowed
  "crc": int,           // CRC checking disabled/enabled
  "download": "string", // generated unrestricted URL
  "streamable": int,
  "type": "string",     // generally the file/quality type
  "alternative": [
    {
      "id": "string",
      "filename": "string",
      "download": "string",
      "type": "string"
    },
    {
      "id": "string",
      "filename": "string",
      "download": "string",
      "type": "string"
    }
  ]
}
```

The page also embeds an array-shaped generated-link schema:

```js
[
  {
    "id": "string",
    "filename": "string",
    "mimeType": "string",
    "filesize": int,
    "link": "string",
    "host": "string",
    "chunks": int,
    "download": "string",
    "generated": "string" // jsonDate
  },
  {
    "id": "string",
    "filename": "string",
    "mimeType": "string",
    "filesize": int,
    "link": "string",
    "host": "string",
    "chunks": int,
    "download": "string",
    "generated": "string",
    "type": "string" // generally the file/quality type
  }
]
```

---

## Downloads-list schema

The generated-download list uses objects containing:

```js
[
  {
    "id": "string",
    "filename": "string",
    "mimeType": "string", // guessed from extension
    "filesize": int,      // bytes; 0 when unknown
    "link": "string",     // original URL
    "host": "string",     // hoster's main domain
    "chunks": int,
    "download": "string", // generated URL
    "generated": "string" // jsonDate
  }
]
```

A `type` string may also be present, describing the file type or, commonly, its quality.

---

## Traffic schema

Top-level keys are hoster main domains.

```js
{
  "example.com": {
    "left": int,
    "bytes": int,
    "links": int,
    "limit": int,
    "type": "string",
    "extra": int,
    "reset": "string"
  }
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `left` | int | Remaining bytes or links |
| `bytes` | int | Bytes downloaded |
| `links` | int | Number of unrestricted links used |
| `limit` | int | Traffic/link limit |
| `type` | string | `"links"`, `"gigabytes"`, or `"bytes"` |
| `extra` | int | Additional traffic or links purchased by the user |
| `reset` | string | `"daily"`, `"weekly"`, or `"monthly"` |

---

## Traffic-details schema

Top-level keys are calendar dates.

```js
{
  "YYYY-MM-DD": {
    "host": {
      "host.example": int
    },
    "bytes": int
  }
}
```

For each day:

- `host` maps hoster domains to the number of bytes downloaded from that hoster;
- `bytes` is the total number of bytes downloaded that day.

---

## Transcoding schema

```js
{
  "apple": {
    "quality": "string"
  },
  "dash": {
    "quality": "string"
  },
  "liveMP4": {
    "quality": "string"
  },
  "h264WebM": {
    "quality": "string"
  }
}
```

Documented format groups:

| Key | Format |
|---|---|
| `apple` | M3U8 live-streaming format |
| `dash` | MPD live-streaming format |
| `liveMP4` | Live MP4 |
| `h264WebM` | Live H.264 WebM |

The schema uses quality names as keys/entries whose values are URLs represented as strings.

---

## Media-information schema

```js
{
  "filename": "string",
  "hoster": "string",
  "link": "string",
  "type": "string",
  "season": "string",
  "episode": "string",
  "year": "string",
  "duration": float,
  "bitrate": int,
  "size": int,
  "details": {
    "video": {
      "und1": {
        "stream": "string",
        "lang": "string",
        "lang_iso": "string",
        "codec": "string",
        "colorspace": "string",
        "width": int,
        "height": int
      }
    },
    "audio": {
      "und1": {
        "stream": "string",
        "lang": "string",
        "lang_iso": "string",
        "codec": "string",
        "sampling": int,
        "channels": float
      }
    },
    "subtitles": {
      "und1": {
        "stream": "string",
        "lang": "string",
        "lang_iso": "string",
        "type": "string"
      }
    }
  },
  "poster_path": "string",
  "audio_image": "string",
  "backdrop_path": "string"
}
```

Top-level fields:

| Field | Type | Meaning |
|---|---|---|
| `filename` | string | Cleaned filename |
| `hoster` | string | Hoster containing the file |
| `link` | string | Original content URL |
| `type` | string | `"movie"`, `"show"`, or `"audio"` |
| `season` | string or null | Detected season, if available |
| `episode` | string or null | Detected episode, if available |
| `year` | string or null | Detected year, if available |
| `duration` | float | Duration in seconds |
| `bitrate` | int | Media bitrate |
| `size` | int | Original file size in bytes |
| `poster_path` | string | Poster-image URL, when available |
| `audio_image` | string | HD music-image URL, when available |
| `backdrop_path` | string | Backdrop-image URL, when available |

Stream keys such as `und1` represent the language's ISO-639 code followed by a numeric stream ID when available.

Video stream fields:

| Field | Type | Meaning |
|---|---|---|
| `stream` | string | Stream identifier |
| `lang` | string | Human-readable language, e.g. `English` |
| `lang_iso` | string | ISO-639 language code, e.g. `eng` or `fre` |
| `codec` | string | Video codec, e.g. `h264` or `divx` |
| `colorspace` | string | Video colour space, e.g. `yuv420p` |
| `width` | int | Width in pixels |
| `height` | int | Height in pixels |

Audio stream fields:

| Field | Type | Meaning |
|---|---|---|
| `stream` | string | Stream identifier |
| `lang` | string | Human-readable language |
| `lang_iso` | string | ISO-639 language code |
| `codec` | string | Audio codec, e.g. `aac` or `mp3` |
| `sampling` | int | Audio sampling rate |
| `channels` | float | Channel count, e.g. `2`, `5.1`, or `7.1` |

Subtitle stream fields:

| Field | Type | Meaning |
|---|---|---|
| `stream` | string | Stream identifier |
| `lang` | string | Human-readable language |
| `lang_iso` | string | ISO-639 language code |
| `type` | string | Subtitle format, e.g. `ASS` or `SRT` |

---

## Torrent-list schema

```js
[
  {
    "id": "string",
    "filename": "string",
    "hash": "string",
    "bytes": int,
    "host": "string",
    "split": int,
    "progress": int,
    "status": "downloaded",
    "added": "string",
    "links": [
      "string"
    ],
    "ended": "string",
    "speed": int,
    "seeders": int
  }
]
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Torrent ID |
| `filename` | string | Torrent/display filename |
| `hash` | string | SHA-1 torrent hash |
| `bytes` | int | Size of selected files only |
| `host` | string | Hoster's main domain |
| `split` | int | Link split size |
| `progress` | int | Completion from `0` to `100` |
| `status` | string | Current torrent state |
| `added` | string | `jsonDate` |
| `links` | string[] | Generated host URLs |
| `ended` | string | Present only when finished; `jsonDate` |
| `speed` | int | Present only in `downloading`, `compressing`, or `uploading` |
| `seeders` | int | Present only in `downloading` or `magnet_conversion` |

Documented torrent-status values:

```text
magnet_error
magnet_conversion
waiting_files_selection
queued
downloading
downloaded
error
virus
compressing
uploading
dead
```

---

## Torrent-information schema

The current reference page renders the detailed torrent schema as an array containing a detailed torrent object:

```js
[
  {
    "id": "string",
    "filename": "string",
    "original_filename": "string",
    "hash": "string",
    "bytes": int,
    "original_bytes": int,
    "host": "string",
    "split": int,
    "progress": int,
    "status": "downloaded",
    "added": "string",
    "files": [
      {
        "id": int,
        "path": "string",
        "bytes": int,
        "selected": int
      }
    ],
    "links": [
      "string"
    ],
    "ended": "string",
    "speed": int,
    "seeders": int
  }
]
```

Fields not already covered by the list schema:

| Field | Type | Meaning |
|---|---|---|
| `original_filename` | string | Original torrent name |
| `original_bytes` | int | Total size of the entire torrent |
| `files` | array | Files contained in the torrent |

Each item in `files` contains:

| Field | Type | Meaning |
|---|---|---|
| `id` | int | File ID used by `/torrents/selectFiles/{id}` |
| `path` | string | Path within the torrent, beginning with `/` |
| `bytes` | int | File size |
| `selected` | int | `0` or `1` |

The same conditional rules for `ended`, `speed`, and `seeders` apply as in the torrent-list schema.

---

## Hosts schema

Top-level keys are hoster main domains.

```js
{
  "example.com": {
    "id": "string",
    "name": "string",
    "image": "string"
  }
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Hoster identifier |
| `name` | string | Human-readable hoster name |
| `image` | string | Image URL |

---

## Host-status schema

```js
{
  "example.com": {
    "id": "string",
    "name": "string",
    "image": "string",
    "supported": int,
    "status": "string",
    "check_time": "string",
    "competitors_status": {
      "competitor.example": {
        "status": "string",
        "check_time": "string"
      }
    }
  }
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Hoster identifier |
| `name` | string | Hoster name |
| `image` | string | Image URL |
| `supported` | int | `0` or `1` |
| `status` | string | `"up"`, `"down"`, or `"unsupported"` |
| `check_time` | string | `jsonDate` |
| `competitors_status` | object | Status keyed by competitor domain |

Each competitor object contains:

- `status`: `"up"`, `"down"`, or `"unsupported"`;
- `check_time`: `jsonDate`.

---

## Settings schema

```js
{
  "download_ports": [
    "string",
    "string"
  ],
  "download_port": "string",
  "locales": {
    "string": "string"
  },
  "locale": "string",
  "streaming_qualities": [
    "string",
    "string",
    "string",
    "string"
  ],
  "streaming_quality": "string",
  "mobile_streaming_quality": "string",
  "streaming_languages": {
    "string": "string"
  },
  "streaming_language_preference": "string",
  "streaming_cast_audio": [
    "string",
    "string"
  ],
  "streaming_cast_audio_preference": "string"
}
```

Meaning:

| Field | Meaning |
|---|---|
| `download_ports` | Allowed values for `download_port` |
| `download_port` | Current download port |
| `locales` | Allowed locale values |
| `locale` | Current locale |
| `streaming_qualities` | Allowed values for `streaming_quality` |
| `streaming_quality` | Current normal streaming quality |
| `mobile_streaming_quality` | Current streaming quality on mobile devices |
| `streaming_languages` | Allowed values for `streaming_language_preference` |
| `streaming_language_preference` | Current preferred streaming language |
| `streaming_cast_audio` | Allowed values for `streaming_cast_audio_preference` |
| `streaming_cast_audio_preference` | Current audio preference for Google Cast devices |

---

# Example REST call

The documentation demonstrates retrieving the authenticated user with cURL:

```bash
curl -X GET \
  -H "Authorization: Bearer your_api_token" \
  "https://api.real-debrid.com/rest/1.0/user"
```

Its example response uses:

```http
HTTP/1.1 200 OK
Content-Type: application/json
etag: fd6e5a758cf66fe4e92bc2bc7061d9f32dc542af
date: Fri, 12 Jul 2013 12:12:12 GMT
```

and an example body equivalent to:

```json
{
  "id": 42,
  "username": "administrator",
  "email": "support@real-debrid.com",
  "points": 12347428,
  "avatar": "https://s.real-debrid.com/images/avatars/42424242424.png",
  "type": "premium",
  "premium": 666666,
  "expiration": "2032-06-06T04:42:42.000Z"
}
```

---

# Authentication

Authenticated REST requests normally carry a Bearer token:

```http
Authorization: Bearer your_api_token
```

If a client cannot send an `Authorization` header, the token may instead be supplied in the REST URL as the `auth_token` query parameter:

```text
/rest/1.0/method?auth_token=your_api_token
```

The token may be either:

- the user's private API token; or
- an access token obtained through OAuth2.

The documentation explicitly warns against embedding or using a private API token in public applications because it grants access to all API methods.

---

# OAuth2 authentication for applications

Before using application OAuth, an application is normally created in the Real-Debrid control panel. This yields:

```text
client_id
client_secret
```

OAuth2 base URL:

```text
https://api.real-debrid.com/oauth/v2/
```

The documentation recommends:

| Application type | Authentication flow |
|---|---|
| Website | Three-legged OAuth2 |
| Mobile application | Device OAuth2 |
| Open-source application or script | Open-source/device-style OAuth2 |

---

## Open-source applications

Real-Debrid publishes this client ID for open-source applications that do not need a custom application name or custom scopes:

```text
X245A4XAIBGVM
```

Allowed scopes for that client ID:

```text
unrestrict
torrents
downloads
user
```

The documentation notes that this shared client ID may be subject to limits stricter than the service-wide limits because badly designed applications also use it.

---

## Website / client application workflow

This flow uses three-legged OAuth2.

Endpoints:

```text
GET/redirect /auth
POST         /token
```

A non-browser-native application may need to present the authorisation page in a web view.

### Step 1: send the user to `/auth`

Query parameters:

| Parameter | Value |
|---|---|
| `client_id` | Application client ID |
| `redirect_uri` | One registered redirect URL, URL-encoded |
| `response_type` | `code` |
| `state` | Arbitrary application-generated value used to defend against CSRF |

Example:

```text
https://api.real-debrid.com/oauth/v2/auth?client_id=ABCDEFGHIJKLM&redirect_uri=https%3A%2F%2Fexample.com&response_type=code&state=iloverd
```

### Step 2: user authorises the application

The user approves access on Real-Debrid.

### Step 3: receive the redirect

Real-Debrid redirects to the supplied `redirect_uri` with:

| Parameter | Meaning |
|---|---|
| `code` | Authorisation code used to obtain tokens |
| `state` | The same state value sent at the beginning |

The application should verify `state`.

### Step 4: exchange the code at `/token`

This is a direct server-to-server `POST`, not a request made in the user's browser.

Parameters:

| Parameter | Value |
|---|---|
| `client_id` | Application client ID |
| `client_secret` | Application client secret |
| `code` | Authorisation code from the redirect |
| `redirect_uri` | One registered redirect URL |
| `grant_type` | `authorization_code` |

Example:

```bash
curl -X POST "https://api.real-debrid.com/oauth/v2/token" \
  -d "client_id=ABCDEFGHIJKLM&client_secret=abcdefghsecret0123456789&code=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&redirect_uri=https://your-app.tld/realdebrid_api&grant_type=authorization_code"
```

### Step 5: token response

The successful JSON response contains:

```js
{
  "access_token": "string",
  "expires_in": int,
  "token_type": "Bearer",
  "refresh_token": "string"
}
```

`expires_in` is the access-token validity in seconds.

The refresh token remains valid until the user revokes the application's rights.

### Step 6: store tokens

The application stores the access token for API requests and must also retain the refresh token so it can obtain replacement access tokens after expiration.

---

## Mobile-device workflow

This is Real-Debrid's device-oriented OAuth2 variant.

Endpoints:

```text
/device/code
/token
```

The application may present some steps in a WebView if it wants to keep the process inside the mobile app.

### Step 1: obtain device authentication data

Request:

```text
https://api.real-debrid.com/oauth/v2/device/code?client_id=ABCDEFGHIJKLM
```

The response contains:

```json
{
  "device_code": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
  "user_code": "ABCDEF0123456",
  "interval": 5,
  "expires_in": 1800,
  "verification_url": "https://real-debrid.com/device"
}
```

Fields:

| Field | Meaning |
|---|---|
| `device_code` | Code the application uses while polling |
| `user_code` | Code displayed to the user |
| `interval` | Poll interval in seconds |
| `expires_in` | Lifetime of the device authorisation request |
| `verification_url` | Page the user opens to authorise |

### Step 2: ask the user to verify

The user opens `verification_url` and enters `user_code`.

### Step 3: poll `/token`

Using `device_code`, the application starts sending direct token requests every five seconds.

Parameters:

| Parameter | Value |
|---|---|
| `client_id` | Application client ID |
| `client_secret` | Application client secret |
| `code` | `device_code` |
| `grant_type` | `http://oauth.net/grant_type/device/1.0` |

Example:

```bash
curl -X POST "https://api.real-debrid.com/oauth/v2/token" \
  -d "client_id=ABCDEFGHIJKLM&client_secret=abcdefghsecret0123456789&code=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&grant_type=http://oauth.net/grant_type/device/1.0"
```

Until the user finishes authorisation, the application receives an error response.

### Steps 4–5: user login and approval

The user enters the code, signs in if necessary, and approves the application. The browser window can then be closed.

### Step 6: token response

After authorisation, `/token` returns:

```js
{
  "access_token": "string",
  "expires_in": int,
  "token_type": "Bearer",
  "refresh_token": "string"
}
```

### Step 7: store tokens

Store both access and refresh tokens. The refresh token is used after the access token expires.

---

## Open-source application workflow

An open-source application cannot safely ship a fixed `client_secret`, because source distribution would expose it. Real-Debrid therefore provides a process that first creates a user-bound `client_id` and `client_secret`.

Those generated credentials can subsequently be reused with the mobile/device OAuth flow.

Do not redistribute the generated credentials. The documentation warns that using a user's generated credentials with another account exposes the original user's UID in the displayed application identity. Its example is that an application name would gain a suffix like:

```text
(UID: 000)
```

Endpoints:

```text
/device/code
/device/credentials
/token
```

### Step 1: request a device code with new credentials enabled

Request:

```text
https://api.real-debrid.com/oauth/v2/device/code?client_id=ABCDEFGHIJKLM&new_credentials=yes
```

Required query values:

| Parameter | Value |
|---|---|
| `client_id` | Existing/shared client ID |
| `new_credentials` | `yes` |

Example response:

```json
{
  "device_code": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
  "user_code": "ABCDEF0123456",
  "interval": 5,
  "expires_in": 1800,
  "verification_url": "https://real-debrid.com/device"
}
```

### Step 2: user verification

Ask the user to open `verification_url` and enter `user_code`.

### Step 3: poll `/device/credentials`

Every five seconds, make a direct request using:

| Query parameter | Value |
|---|---|
| `client_id` | Existing/shared client ID |
| `code` | `device_code` |

The endpoint returns errors until the user authorises the application.

### Steps 4–5: user login and approval

The user enters the code, logs in if required, and authorises the application.

### Step 6: receive user-bound credentials

`/device/credentials` then returns:

```js
{
  "client_id": "string",
  "client_secret": "string"
}
```

The new `client_id` is bound to the authorising user.

Store both values.

### Step 7: exchange the device code for tokens

POST to `/token` with:

| Parameter | Value |
|---|---|
| `client_id` | New user-bound client ID |
| `client_secret` | New user-bound client secret |
| `code` | Original `device_code` |
| `grant_type` | `http://oauth.net/grant_type/device/1.0` |

The response contains:

```js
{
  "access_token": "string",
  "expires_in": int,
  "token_type": "Bearer",
  "refresh_token": "string"
}
```

Example:

```bash
curl -X POST "https://api.real-debrid.com/oauth/v2/token" \
  -d "client_id=ABCDEFGHIJKLM&client_secret=abcdefghsecret0123456789&code=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&grant_type=http://oauth.net/grant_type/device/1.0"
```

### Step 8: store tokens

Store the access token and refresh token. The refresh token is needed to renew the access token later.

---

## Legacy application workflow

This flow is marked as requiring special authorisation on the application's `client_id` from the Real-Debrid webmaster.

Endpoint:

```text
/token
```

The application sends a direct `POST` with:

| Parameter | Value |
|---|---|
| `client_id` | Specially authorised client ID |
| `username` | User login |
| `password` | User password |
| `grant_type` | `password` |

Example:

```bash
curl -X POST "https://api.real-debrid.com/oauth/v2/token" \
  -d "client_id=ABCDEFGHIJKLM&username=abcdefghsecret0123456789&password=abcdefghsecret0123456789&grant_type=password"
```

On success:

```js
{
  "access_token": "string",
  "expires_in": int,
  "token_type": "Bearer",
  "refresh_token": "string"
}
```

The documentation explicitly says applications must **not** save the user's login credentials. Only the `refresh_token` should be retained as the effective long-term credential.

---

## Two-factor authentication

The documentation includes a two-factor process in the legacy authentication section.

### Testing the flow

For testing only, add:

```text
force_twofactor=true
```

This forces the server to return a two-factor error containing:

```js
{
  "verification_url": "string",
  "twofactor_code": "string",
  "error": "twofactor_auth_needed",
  "error_code": 11
}
```

`verification_url` is where the user should be redirected.

### WebView / popup flow

Open `verification_url` for the user.

Then, using `twofactor_code`, send a direct `POST` to `/token` with:

| Parameter | Value |
|---|---|
| `client_id` | Application client ID |
| `code` | Two-factor code returned earlier |
| `grant_type` | `twofactor` |

Example:

```bash
curl -X POST "https://api.real-debrid.com/oauth/v2/token" \
  -d "client_id=ABCDEFGHIJKLM&code=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&grant_type=twofactor"
```

Until the user enters the correct security code at `verification_url`, the request returns HTTP `403`.

### Handling the security code inside the application

The SMS or email is not sent until the application requests it.

To send the code, POST to `/token` with:

| Parameter | Value |
|---|---|
| `client_id` | Application client ID |
| `code` | Previously returned two-factor code |
| `grant_type` | `twofactor` |
| `send` | `true` |

On success:

```text
HTTP 204
```

If the sending limit has been reached:

```text
HTTP 403
```

To validate the security code entered by the user, POST to `/token` with:

| Parameter | Value |
|---|---|
| `client_id` | Application client ID |
| `code` | Previously returned two-factor code |
| `grant_type` | `twofactor` |
| `response` | Security code entered by the user |

An incorrect code returns HTTP `400`. Exhausting the allowed number of attempts returns HTTP `403`.

---

## Refreshing an access token

Endpoint:

```text
/token
```

Use the saved `refresh_token` in a direct `POST`.

Parameters:

| Parameter | Value |
|---|---|
| `client_id` | Client ID |
| `client_secret` | Client secret |
| `code` | Saved refresh token |
| `grant_type` | `http://oauth.net/grant_type/device/1.0` |

Response:

```js
{
  "access_token": "string",
  "expires_in": int,
  "token_type": "Bearer",
  "refresh_token": "string"
}
```

Example:

```bash
curl -X POST "https://api.real-debrid.com/oauth/v2/token" \
  -d "client_id=ABCDEFGHIJKLM&client_secret=abcdefghsecret0123456789&code=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&grant_type=http://oauth.net/grant_type/device/1.0"
```

---

# Numeric API error codes

API errors can include both a human-readable `error` string and an integer `error_code`. Applications are expected to branch on the numeric code.

| Code | Meaning |
|---:|---|
| -1 | Internal error |
| 1 | Missing parameter |
| 2 | Bad parameter value |
| 3 | Unknown method |
| 4 | Method not allowed |
| 5 | Slow down |
| 6 | Resource unreachable |
| 7 | Resource not found |
| 8 | Bad token |
| 9 | Permission denied |
| 10 | Two-factor authentication needed |
| 11 | Two-factor authentication pending |
| 12 | Invalid login |
| 13 | Invalid password |
| 14 | Account locked |
| 15 | Account not activated |
| 16 | Unsupported hoster |
| 17 | Hoster in maintenance |
| 18 | Hoster limit reached |
| 19 | Hoster temporarily unavailable |
| 20 | Hoster unavailable to free users |
| 21 | Too many active downloads |
| 22 | IP address not allowed |
| 23 | Traffic exhausted |
| 24 | File unavailable |
| 25 | Service unavailable |
| 26 | Upload too big |
| 27 | Upload error |
| 28 | File not allowed |
| 29 | Torrent too big |
| 30 | Invalid torrent file |
| 31 | Action already done |
| 32 | Image resolution error |
| 33 | Torrent already active |
| 34 | Too many requests |
| 35 | Infringing file |
| 36 | Fair Usage Limit |
| 37 | Disabled endpoint |

---

# Embedded schema fragments without a public method heading

The current documentation page includes several schema blocks after the `/support` heading that are not paired with a visible public method heading. They are retained here so the Markdown document does not lose information present on the source page.

## Instant-availability-style torrent schema

The page embeds the following structure, keyed first by torrent hash and then by hoster (for example, `"rd"`). Each hoster contains one or more variants; each variant maps file IDs to filename/filesize objects.

```js
{
  "first_hash": {
    "rd": [
      {
        "1": {
          "filename": "string",
          "filesize": int
        },
        "2": {
          "filename": "string",
          "filesize": int
        }
      },
      {
        "3": {
          "filename": "string",
          "filesize": int
        }
      }
    ]
  },
  "second_hash": {
    "rd": [
      {
        "1": {
          "filename": "string",
          "filesize": int
        },
        "2": {
          "filename": "string",
          "filesize": int
        }
      }
    ]
  }
}
```

The schema annotation states that, to obtain instant downloading for one variant, all file IDs in the chosen variant array/object should be supplied to `/selectFiles`.

The current rendered method list on `api.real-debrid.com` does **not** expose a corresponding method heading, even though this schema remains embedded in the page.

---

## Support/forum category schema

The page embeds a support/forum-category structure keyed by category name:

```js
{
  "category": [
    {
      "id": int,
      "name": "string",
      "description": "string",
      "topics": int,
      "posts": int,
      "unread_content": int,
      "last_post": {
        "id": int,
        "topic_id": int,
        "user_id": int,
        "user_name": "string",
        "user_level": "string",
        "date": "string"
      }
    }
  ]
}
```

Forum fields:

| Field | Meaning |
|---|---|
| `id` | Forum ID |
| `name` | Forum name |
| `description` | Forum description |
| `topics` | Number of topics in the forum |
| `posts` | Number of posts in the forum |
| `unread_content` | `0` or `1` |
| `last_post` | Metadata for the latest post |

`last_post.user_level` may be:

```text
user
banned
moderator
administrator
```

`last_post.date` is a `jsonDate`.

---

## Support/forum topics schema

The page also embeds a forum-detail structure:

```js
{
  "meta": {
    "id": int,
    "name": "string",
    "description": "string",
    "topics": int,
    "autorisation_topic": int,
    "autorisation_post": int,
    "autorisation_stick": int,
    "autorisation_moderation": int
  },
  "topics": {
    "normal": [
      {
        "id": int,
        "title": "string",
        "author": {
          "user_id": int,
          "username": "string",
          "level": "string"
        },
        "posts": int,
        "views": int,
        "unread_content": int,
        "last_post": {
          "id": int,
          "user_id": int,
          "user_name": "string",
          "user_level": "string",
          "date": "string"
        }
      }
    ],
    "sticky": []
  }
}
```

The documentation notes that the keys inside `topics` are `"normal"` or `"sticky"`.

`meta` fields:

| Field | Meaning |
|---|---|
| `id` | Forum ID |
| `name` | Forum name |
| `description` | Forum description |
| `topics` | Topic count |
| `autorisation_topic` | `0` or `1`; user may create a topic |
| `autorisation_post` | `0` or `1`; user may post in a topic |
| `autorisation_stick` | `0` or `1`; user may make a topic sticky |
| `autorisation_moderation` | `0` or `1`; user may use moderation tools |

The embedded example shows two slightly different topic-author representations: one uses a nested `author` object (`user_id`, `username`, `level`), while another sample uses flat fields named `author_user_id` and `author_user_name`. Both forms are preserved by the source material.

---

# Source

Real-Debrid public API documentation:

```text
https://api.real-debrid.com/
```

Reference checked: 5 September 2026.
