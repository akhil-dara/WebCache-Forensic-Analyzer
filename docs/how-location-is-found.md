# Location in WebCacheV01.dat

WebCacheV01.dat has no location table. The positions the **Location** view
shows were sent by applications inside request URLs, and the cache kept
those requests.

## The artifact: the MSN feed behind Widgets

The Windows taskbar's news and weather feed (Widgets, the Microsoft Start
Experiences app) refreshes its content from `assets.msn.com` throughout the
day, whether or not the panel is opened. Each refresh is a request, and
WebCacheV01.dat records it: the URL, its cache times, the response headers
and the file the response was saved to in the app's own cache.

When the device's location is available to the app, the request URL
carries it:

| Parameter | What it holds |
|---|---|
| `clientLocation` | latitude and longitude, joined by `\|` |
| `clientLocationAccuracy` | the accuracy radius the device claimed, in metres |
| `clientLocationProvider` | how the device got the position, e.g. `WiFi` |
| `clientLocationTimestamp` | when the device took the fix (UTC) |

These requests are short-lived. The cache replaces feed records within
hours, and the response files rotate with them. The positions survive in
the database's free pages and transaction logs long after the live records
are gone.

## How this tool helps

- **Reads every request URL, live and recovered**, for a position:
  `clientLocation` and the other common names (`lat`/`lon`, `latlng`,
  `ll`, `coords`, ...; see `webcache/engine/geolocation.py`), with its
  accuracy, provider and fix time.
- **Shows which app made a request.** The Containers view lists every
  container with its cache directory and partition, so the Start
  Experiences app's own container (its `Packages\...\AC\INetCache\` folder)
  is named, and each record belongs to one.
- **Recovers deleted feed requests** from unallocated pages and the
  transaction logs, labelled with the file and offset they came from. For
  this artifact that is usually where all the positions are.
- **Refuses what is not a position**: integer pairs, out-of-range values
  and 0,0.
- **States what each fix supports.** The accuracy band reads as a satellite
  fix (about 30 m or better), WiFi or cell (up to about 200 m: a building,
  not a room) or a neighbourhood at best. A fix is what the device told a
  server, not proof that a particular person was there.
- **Groups fixes into places** at a scale the examiner chooses: identical
  stored coordinates, or by distance within 11 m, 110 m (the default,
  matching the typical WiFi accuracy) or 1.1 km. A place is the position
  reported most often in its area plus every fix within that distance of
  it, so a building is never split by a rounding boundary. Each place is
  labelled by a position that was actually reported, states its range of
  accuracies, never an average, and every note says which grouping is in
  force.
- **Keeps the raw strings** of every value beside the parsed numbers, and
  every response-header blob byte for byte, so each finding can be checked
  against the stored URL.

Nothing is looked up and no network request is made. The map links on each
row are text.

## Example: one Windows 11 machine, three points in time

The same machine's WebCacheV01.dat at two shadow copies a day apart and
live, with the Start Experiences app's cache folder alongside:

| Copy examined | Feed requests in live records | Feed response files on disk | Feed requests recovered | Positions in live records | Positions recovered |
|---|--:|--:|--:|--:|--:|
| Shadow copy, day 1 | 23 | 23 | 145 | 0 | 135 |
| Shadow copy, day 2 | 0 | 0 | 172 | 0 | 135 |
| Live system, day 2 | 5 | 5 | 167 | 0 | 135 |

- The live records match the response files one for one, and both vanish
  when the cache rotates.
- Not one position was in a live record at any point. All 135 were
  recovered, from requests made over more than a year.
- Recovery found 145 to 172 feed requests the live tables no longer held.
- Grouped at the default ~110 m, the 135 fixes form 5 places: two hold 68
  and 62 fixes, the other three hold 2 or fewer. At ~11 m the same fixes
  split into 27 places by ordinary WiFi jitter; grouped by rounding instead
  of distance, a grid line cut each of the two large places in two.

Opened without recovery, this machine's Location view would be empty.

## What a feed record is, and is not

- **It shows a request was made.** The feed refreshes in the background,
  so it does not show that anyone opened the panel or read it.
- **The response is not in the database.** It is a separate file in the
  app's cache, which the record names. A place the server put in that
  response was chosen by the server, not reported by the device.
- **The database stores no request or response bodies**, only URLs, times,
  file references and headers.

## Further reading: how Windows gets the position

A `clientLocationProvider` of `WiFi` means Windows positioned itself from
the WiFi access points it could hear, by asking Microsoft's location
service. [WiFi Geolocation Forensics](https://github.com/akhil-dara/wifi-geolocation-forensics)
shows how that backend works: it resolves an access point through
Microsoft's and Apple's services, documents both wire formats
(`wifigeo/msft.py`, `wifigeo/apple.py`), cross-validates the two, and keeps
every request and response as hashed evidence. Its README also covers what
such a position can and cannot establish, including Microsoft answering from
the network connection when it holds no record for the access points heard.
