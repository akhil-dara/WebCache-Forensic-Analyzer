"""
Additional offline analysis.

Three capabilities that add evidentiary value without contacting anything
external — everything is computed from the database alone:

  redirect_chains()   Reconstructs navigation/redirect chains, so a landing
                      page can be traced back to what sent the user there.

  homograph_findings() Reports IDN/punycode hostnames, separating the two
                      cases that get confused: a label mixing scripts or
                      using ASCII-confusable characters, which is the shape
                      of a name built to imitate another, and a hostname
                      simply written in a non-Latin script, which is how
                      most of the world writes domains. Pure stdlib.

  hsts_visit_evidence() Reports HSTS pins and what corroborates them. A pin
                      is set by an HTTPS response, but includeSubDomains
                      coverage or a browser preload entry can account for one
                      without that exact host being reached, so the finding
                      states its limits rather than asserting a visit.
"""

import unicodedata
from collections import defaultdict
from urllib.parse import urljoin, urlparse

# ── Redirect chains ──────────────────────────────────────────────────


def _norm(url):
    """Normalise a URL for chain matching: scheme+host+path, no fragment."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
        if not p.netloc:
            return url.strip().lower()
        path = p.path or "/"
        q = f"?{p.query}" if p.query else ""
        return f"{p.scheme.lower()}://{p.netloc.lower()}{path}{q}"
    except ValueError:
        return url.strip().lower()


def redirect_chains(entries, max_depth=12):
    """Build redirect chains from the RedirectUrl column and from HTTP 3xx
    Location headers.

    Returns a list of chains, longest first:
      {"hops": [{url, source, entry}], "length": n, "start", "end", "resolved"}

    `resolved` counts how many hops landed on a record that actually exists in
    the database — an unresolved final hop still tells you where the browser
    was being sent, which is itself evidence.
    """
    by_url = {}
    for e in entries:
        key = _norm(e.get("CleanUrl") or e.get("Url", ""))
        if key and key not in by_url:
            by_url[key] = e

    # source url -> list of (normalised target, target as recorded, basis).
    # A list: the same URL can carry more than one recorded redirect, and
    # every one is kept.
    edges = defaultdict(list)
    for e in entries:
        raw_src = e.get("CleanUrl") or e.get("Url", "")
        src = _norm(raw_src)
        if not src:
            continue
        target = (e.get("RedirectUrl") or "").strip()
        source_kind = "RedirectUrl column"
        if not target:
            resp = e.get("ResponseHeaders")
            if isinstance(resp, dict) and resp:
                status = str(resp.get("_status_line", ""))
                bits = status.split(" ", 2)
                code = bits[1] if len(bits) >= 2 else ""
                # Only 3xx is a redirect. A Location on a 200 describes
                # something else, and on a 201 it names a resource that was
                # just created — neither sent the browser anywhere.
                is_3xx = code[:1] == "3" and code[1:].isdigit()
                is_known_status = code[:1].isdigit()
                for k, v in resp.items():
                    if k.lower() != "location" or not str(v).strip():
                        continue
                    if is_3xx:
                        target = str(v).strip()
                        source_kind = f"HTTP {code} Location"
                    elif not is_known_status:
                        # No readable status line. A Location here usually is
                        # a redirect, but that is an inference and is labelled
                        # as one rather than stated as a 3xx.
                        target = str(v).strip()
                        source_kind = ("Location header (no readable status "
                                       "line — redirect inferred)")
                    break
        if target:
            # "Location: /next" is relative to the URL that carried it.
            # Left unresolved it became a hop to the literal string "/next".
            resolved = target
            if raw_src and not urlparse(target).netloc:
                try:
                    resolved = urljoin(raw_src, target)
                except ValueError:
                    resolved = target
            pair = (_norm(resolved), resolved, source_kind)
            if pair not in edges[src]:
                edges[src].append(pair)

    # Nodes that are never a redirect target are chain starts.
    targets = {t for pairs in edges.values() for t, _, _ in pairs}
    starts = [s for s in edges if s not in targets]

    # A cycle has no such node (every URL in it is some URL's target), so
    # one node is seeded per component no start can reach; a redirect loop
    # is then reported and described rather than dropped.
    reachable = set()
    for node in starts:
        cur = node
        while cur in edges and cur not in reachable:
            reachable.add(cur)
            cur = edges[cur][0][0]
    for node in edges:
        if node in reachable:
            continue
        cur = node
        while cur in edges and cur not in reachable:
            reachable.add(cur)
            cur = edges[cur][0][0]
        starts.append(node)

    chains = []
    # A URL with several recorded targets yields a chain per target, so no
    # recorded redirect goes unreported.
    pending = [(s, i) for s in starts for i in range(len(edges[s]))]
    for start, branch in pending:
        hops = [{"url": start, "source": "start",
                 "entry": by_url.get(start), "in_db": start in by_url}]
        seen = {start}
        cur = start
        choice = branch
        forked = False
        while cur in edges and len(hops) < max_depth:
            options = edges[cur]
            if len(options) > 1:
                forked = True
            nxt_norm, nxt_raw, kind = options[min(choice, len(options) - 1)]
            choice = 0          # only the first step follows the branch index
            if nxt_norm in seen:
                hops.append({"url": nxt_raw, "source": kind + " (loop)",
                             "entry": None, "in_db": nxt_norm in by_url})
                break
            seen.add(nxt_norm)
            hops.append({"url": nxt_raw, "source": kind,
                         "entry": by_url.get(nxt_norm), "in_db": nxt_norm in by_url})
            cur = nxt_norm
        if len(hops) > 1:
            chains.append({
                "hops": hops,
                "length": len(hops),
                "start": hops[0]["url"],
                "end": hops[-1]["url"],
                "resolved": sum(1 for h in hops if h["in_db"]),
                "crosses_domain": len({urlparse(h["url"]).netloc.lower()
                                       for h in hops
                                       if urlparse(h["url"]).netloc}) > 1,
                # True when some URL on this chain had more than one recorded
                # target, so the path shown is one of several the records
                # support.
                "has_alternatives": forked,
            })
    # Identical chains can arise from repeated records; report each once.
    unique = []
    seen_chains = set()
    for chain in chains:
        signature = tuple(h["url"] for h in chain["hops"])
        if signature in seen_chains:
            continue
        seen_chains.add(signature)
        unique.append(chain)
    unique.sort(key=lambda c: c["length"], reverse=True)
    return unique


# ── IDN homograph / punycode ─────────────────────────────────────────

# Scripts whose characters are routinely mixed with Latin to build look-alikes.
#: The tool's own assessment of a flagged hostname, one per kind (the
#: grid states each once, in a header tooltip).
HOST_ASSESSMENT_LOOKALIKE = (
    "Contains indicators associated with names built to imitate "
    "another. Compare against the domain it resembles before drawing "
    "any conclusion.")
HOST_ASSESSMENT_NON_LATIN = (
    "Not written in Latin script. Nothing here indicates imitation; "
    "this is how domains are ordinarily written in that language.")

_SCRIPT_HINTS =("CYRILLIC", "GREEK", "ARMENIAN", "HEBREW", "ARABIC",
                 "CHEROKEE", "FULLWIDTH")

# Characters that look like ASCII but are not.
CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "у": "y", "х": "x", "і": "i", "ј": "j", "һ": "h",
    "ο": "o", "α": "a", "ρ": "p", "ν": "v", "ɡ": "g",
    "ẞ": "S", "ａ": "a", "ｅ": "e", "ı": "i", "ǀ": "l",
}


def _char_name(ch):
    """Unicode name for a character, or a placeholder when it has none."""
    try:
        return unicodedata.name(ch)
    except ValueError:
        return "unnamed"


def _script_of(ch):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "UNKNOWN"
    for hint in _SCRIPT_HINTS:
        if name.startswith(hint):
            return hint
    if "LATIN" in name:
        return "LATIN"
    if "DIGIT" in name or ch in "-._":
        return "COMMON"
    return name.split()[0] if name else "UNKNOWN"


def analyze_hostname(host):
    """Inspect one hostname for deceptive-name indicators.

    Returns None when nothing notable, else a findings dict.
    """
    if not host:
        return None
    # Inspect what was stored before normalising it. Case folding maps
    # U+212A KELVIN SIGN onto a plain ASCII "k" (the only BMP character that
    # does this), so lowercasing first would hide it.
    as_stored = host.strip()
    host = as_stored.lower()
    findings = []
    # Findings that indicate a name may be imitating another. A hostname in a
    # non-Latin script is not one of these: it is simply a hostname in another
    # language, and the great majority of them are ordinary sites.
    lookalike_findings = []
    decoded = host

    # 1. Punycode labels
    if "xn--" in host:
        parts = []
        for label in host.split("."):
            if label.startswith("xn--"):
                try:
                    parts.append(label.encode("ascii").decode("idna"))
                except (UnicodeError, UnicodeDecodeError):
                    parts.append(label)
            else:
                parts.append(label)
        decoded = ".".join(parts)
        findings.append(f"Punycode hostname decodes to “{decoded}”")

    # 2. Non-ASCII characters
    non_ascii = [c for c in decoded if ord(c) > 127]
    if non_ascii:
        scripts = sorted({_script_of(c) for c in decoded
                          if _script_of(c) not in ("COMMON", "UNKNOWN")})
        findings.append("Contains non-ASCII characters: " +
                        ", ".join(sorted({f'{c!r} ({_script_of(c)})'
                                          for c in non_ascii})))
        # 3. Mixed script within a single label — the classic homograph shape
        for label in decoded.split("."):
            label_scripts = {_script_of(c) for c in label
                             if _script_of(c) not in ("COMMON", "UNKNOWN")}
            if len(label_scripts) > 1:
                mixed = (f"Label “{label}” mixes scripts: "
                         f"{', '.join(sorted(label_scripts))} — mixing scripts "
                         "inside one label is the classic shape of a name "
                         "built to imitate another")
                findings.append(mixed)
                lookalike_findings.append(mixed)
        if scripts and "LATIN" not in scripts and len(scripts) == 1:
            # A hostname written wholly in one non-Latin script is a hostname
            # in another language. Saying it looks like a Latin name would put
            # a finding against national ccTLDs such as 中国 and مصر.
            findings.append(
                f"Hostname is written in {scripts[0]} script rather than "
                "Latin. This is how domains are ordinarily written in that "
                "language and is not by itself an indication of imitation.")

    # 4. Characters that case-folding turns into plain ASCII. These are not
    # lookalike domains — IDNA maps them to the ASCII letter, so the name
    # resolves to the legitimate host — but the stored URL did contain a
    # character that is not the letter it appears to be, and saying nothing
    # would let that disappear entirely.
    folded_away = sorted({c for c in as_stored
                          if ord(c) > 127 and c.lower().isascii()})
    if folded_away:
        described = ", ".join(
            f"{c!r} (U+{ord(c):04X} {_char_name(c)}) reads as {c.lower()!r}"
            for c in folded_away)
        findings.append(
            f"Stored hostname contains {described}. Case folding turns these "
            "into ordinary ASCII, so the name resolves to the legitimate "
            "host — but the URL as stored was not written in plain ASCII.")

    # 5. Confusable characters that skeletonise to an ASCII lookalike
    skeleton = "".join(CONFUSABLES.get(c, c) for c in decoded)
    if skeleton != decoded:
        confusable = (f"Confusable characters present; skeleton is “{skeleton}” "
                      "— these characters render like ASCII letters, which is "
                      "what a lookalike name relies on")
        findings.append(confusable)
        lookalike_findings.append(confusable)

    if not findings:
        return None
    return {
        "host": host,
        "decoded": decoded,
        "skeleton": skeleton,
        "findings": findings,
        # Whether anything here actually indicates imitation, as opposed to
        # the hostname simply not being written in Latin script.
        "lookalike_indicators": lookalike_findings,
        "is_lookalike_candidate": bool(lookalike_findings),
        "assessment": (HOST_ASSESSMENT_LOOKALIKE if lookalike_findings
                       else HOST_ASSESSMENT_NON_LATIN),
        "is_punycode": "xn--" in host,
        "has_non_ascii": bool(non_ascii),
    }


def homograph_findings(entries):
    """Scan every URL for deceptive hostnames. Returns one row per hostname."""
    seen = {}
    for e in entries:
        url = e.get("CleanUrl") or e.get("Url", "")
        if not url:
            continue
        try:
            host = urlparse(url).netloc.lower()
        except ValueError:
            continue
        if not host or host in seen:
            continue
        result = analyze_hostname(host)
        if result:
            result["example_url"] = url
            result["records"] = 0
            seen[host] = result
    # count records per flagged host
    if seen:
        for e in entries:
            url = e.get("CleanUrl") or e.get("Url", "")
            try:
                host = urlparse(url).netloc.lower()
            except ValueError:
                continue
            if host in seen:
                seen[host]["records"] += 1
    return sorted(seen.values(), key=lambda r: -r["records"])


# ── HSTS pins as visit evidence ──────────────────────────────────────

#: The tool's own sentences about a pin, one per kind. They are the same
#: text for every pin of a kind, so the grid states each ONCE, in a header
#: tooltip (views/cookies.py), while every row still carries its own.
HSTS_SIGNIFICANCE_CORROBORATED = (
    "Host also appears in history/cache records, which corroborates "
    "the pin.")
HSTS_SIGNIFICANCE_UNCORROBORATED = (
    "No other record for this host survives. A pin is set by an "
    "HTTPS response, but includeSubDomains coverage or a browser "
    "preload entry can account for one without this exact host "
    "being contacted — weigh LastTimeUsed, which requires a "
    "request to have been made.")
HSTS_ATTRIBUTION_SUBDOMAINS = (
    "Pin covers subdomains — contact with a covered host or "
    "the parent could account for it")
HSTS_ATTRIBUTION_HOST_ONLY = "Pin is host-specific (no includeSubDomains)"

def hsts_visit_evidence(hsts_entries, entries):
    """HSTS pins held for each host, and whether anything else corroborates them.

    A dynamically-set pin is created by an HTTPS response carrying a
    Strict-Transport-Security header, so it is real evidence that a TLS
    exchange happened. It does not establish that this exact host answered:

      * a pin carrying includeSubDomains covers subdomains, so contact with a
        covered host — or with the parent — can account for it;
      * browsers ship an HSTS preload list, and a preloaded pin was never set
        by any response.

    LastTimeUsed is the stronger signal and is reported per pin: it records
    when the pin was actually applied, which needs a request to have been made.

    Returns one row per pin. Corroborated is "NO" where the host appears
    nowhere else in the database; those rows are listed first because they
    carry information no other record does — not because they are the
    strongest evidence.
    """
    hosts_in_db = set()
    for e in entries:
        url = e.get("CleanUrl") or e.get("Url", "")
        try:
            netloc = urlparse(url).netloc.lower()
        except ValueError:
            netloc = ""
        if netloc:
            hosts_in_db.add(netloc)
            if netloc.startswith("www."):
                hosts_in_db.add(netloc[4:])

    rows = []
    for h in hsts_entries or []:
        domain = (h.get("Domain") or "").lower()
        if not domain or domain.startswith(":"):
            continue
        corroborated = domain in hosts_in_db or any(
            host == domain or host.endswith("." + domain) for host in hosts_in_db)
        rows.append({
            "Domain": h.get("Domain", ""),
            "LastTimeUsed": h.get("LastTimeUsed", ""),
            "LastTimeUsed_raw": h.get("LastTimeUsed_raw", 0),
            "Expires": h.get("Expires", ""),
            "IncludeSubdomains": "yes" if h.get("IncludeSubdomains") else "no",
            "Corroborated": "yes" if corroborated else "NO",
            "Significance": (HSTS_SIGNIFICANCE_CORROBORATED if corroborated
                             else HSTS_SIGNIFICANCE_UNCORROBORATED),
            # Whether the pin's own coverage flag weakens the host attribution.
            "HostAttribution": (HSTS_ATTRIBUTION_SUBDOMAINS
                                if h.get("IncludeSubdomains")
                                else HSTS_ATTRIBUTION_HOST_ONLY),
            "Table": h.get("Table", ""),
            "PartitionId": h.get("PartitionId", ""),
            # The pin's raw expiry FILETIME, carried through unmodified --
            # including the 0x7FFFFFFFFFFFFFFF "never" sentinel, which is
            # a recorded fact about the pin rather than a missing value
            # (see ese_parser._parse_hsts_table). Without this the shell
            # has only the formatted string, and views/cookies.py already
            # declares Expires kind="time".
            "Expires_raw": h.get("Expires_raw", 0),
            # The pin itself, by reference, so every field of the
            # hsts_entries record stays reachable and cannot disagree with
            # the row.
            "SourceEntry": h,
        })
    # Uncorroborated pins first: they point at hosts nothing else records,
    # which is where an examiner should look, not where the evidence is
    # strongest.
    rows.sort(key=lambda r: (r["Corroborated"] == "yes",
                             -(r.get("LastTimeUsed_raw") or 0)))
    return rows
