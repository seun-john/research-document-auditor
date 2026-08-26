from __future__ import annotations

import json
import hashlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..citations import ReferenceEntry
from ..models import Finding, Location, ReferenceVerification

USER_AGENT = "research-document-auditor/0.3 (NovaPoint Consulting; open metadata verification)"
CACHE_VERSION = 2
SUCCESS_TTL_SECONDS = 180 * 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 30 * 24 * 60 * 60


def _get_json(url: str, bearer: str | None = None) -> tuple[int | None, dict | None, str | None]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace")), None
    except urllib.error.HTTPError as exc:
        return exc.code, None, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, None, str(exc)


def _cited_title(raw: str) -> str:
    after_year = re.split(r"\(?(?:19|20)\d{2}[a-z]?\)?\.?", raw, maxsplit=1, flags=re.I)
    if len(after_year) < 2:
        return ""
    title = after_year[1].strip(" .,:;-")
    return title.split(". ", 1)[0].strip()


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _title_similarity(left: str, right: str) -> float:
    a, b = _normal(left), _normal(right)
    if not a or not b:
        return 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    at, bt = set(a.split()), set(b.split())
    jaccard = len(at & bt) / max(1, len(at | bt))
    return max(sequence, jaccard)


def _doi_title_similarity(left: str, right: str) -> float:
    """Title score for an already-resolved DOI.

    Registry records for books and chapters often omit a cited subtitle. An
    exact normalized prefix is therefore strong evidence only after the DOI has
    resolved; applying this rule to broad title search would be too permissive.
    """
    score = _title_similarity(left, right)
    a, b = _normal(left), _normal(right)
    if a and b and (a.startswith(b + " ") or b.startswith(a + " ") or a == b):
        score = max(score, 0.95)
    return score


def _year(metadata: dict) -> int | None:
    parts = metadata.get("issued", {}).get("date-parts", [[None]])
    value = parts[0][0] if parts and parts[0] else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _authors(metadata: dict) -> list[str]:
    output = []
    for author in metadata.get("author", []) or []:
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part) or author.get("name", "")
        if name:
            output.append(name)
    return output


def _author_matches(entry: ReferenceEntry, authors: list[str]) -> bool:
    if not entry.key or not authors:
        return False
    expected = _normal(entry.key.author).replace(" ", "")
    return any(expected and expected in _normal(author).replace(" ", "") for author in authors)


class JsonRequestCache:
    def __init__(self, filename: str | Path | None) -> None:
        self.path = Path(filename).expanduser().resolve() if filename else None
        self.data: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._dirty = 0
        if self.path and self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                entries = loaded.get("entries", {}) if loaded.get("version") == CACHE_VERSION else loaded
                now = time.time()
                for key, item in entries.items():
                    if not isinstance(item, dict) or item.get("status") not in {200, 404}:
                        continue
                    timestamp = float(item.get("timestamp", now))
                    ttl = NEGATIVE_TTL_SECONDS if item.get("status") == 404 else SUCCESS_TTL_SECONDS
                    if now - timestamp > ttl:
                        continue
                    legacy_url = None if re.fullmatch(r"[0-9a-f]{64}", key) else key
                    cache_key = key if legacy_url is None else self._key(key)
                    self.data[cache_key] = {
                        "status": item.get("status"),
                        "body": self._trim_body(legacy_url, item.get("body")) if legacy_url else item.get("body"),
                        "timestamp": timestamp,
                    }
            except (OSError, json.JSONDecodeError):
                self.data = {}

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, url: str) -> tuple[int | None, dict | None, str | None] | None:
        key = self._key(url)
        with self._lock:
            item = self.data.get(key)
            if not item:
                return None
            status = item.get("status")
            ttl = NEGATIVE_TTL_SECONDS if status == 404 else SUCCESS_TTL_SECONDS
            if status not in {200, 404} or time.time() - float(item.get("timestamp", 0)) > ttl:
                self.data.pop(key, None)
                self._dirty += 1
                return None
            return status, item.get("body"), None

    @staticmethod
    def _trim_body(url: str, body: dict | None) -> dict | None:
        if body is None:
            return None
        host = urllib.parse.urlsplit(url).hostname or ""
        if host == "api.openalex.org":
            return {key: body.get(key) for key in ("id", "title", "is_retracted")}
        if host == "api.datacite.org":
            data = body.get("data", {})
            attrs = data.get("attributes", {})
            return {"data": {"attributes": {key: attrs.get(key) for key in (
                "titles", "publicationYear", "creators", "url",
            )}}}
        if host == "api.crossref.org":
            message = body.get("message", {})
            fields = ("DOI", "title", "author", "issued", "container-title", "URL", "type")
            if "items" in message:
                return {"message": {"items": [
                    {key: item.get(key) for key in fields if key in item}
                    for item in message.get("items", [])[:5]
                ]}}
            return {"message": {key: message.get(key) for key in fields if key in message}}
        return body

    def put(self, url: str, status: int | None, body: dict | None, error: str | None) -> None:
        if not self.path or error or status not in {200, 404}:
            return
        with self._lock:
            self.data[self._key(url)] = {
                "status": status,
                "body": self._trim_body(url, body),
                "timestamp": time.time(),
            }
            self._dirty += 1
            checkpoint = self._dirty >= 10
        if checkpoint:
            self.save()

    def save(self) -> None:
        if not self.path:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps({"version": CACHE_VERSION, "entries": self.data}, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(self.path)
            self._dirty = 0


class DoiRegistryEngine:
    """Verify references using Crossref, DataCite, and DOI-linked OpenAlex records."""

    name = "open-metadata"

    def __init__(
        self,
        email: str | None = None,
        cache_path: str | Path | None = None,
        delay: float = 0.1,
        openalex_api_key: str | None = None,
        workers: int = 1,
        progress=None,
    ) -> None:
        self.email = email
        self.cache = JsonRequestCache(cache_path)
        self.delay = max(0.0, delay)
        self.openalex_api_key = openalex_api_key
        self.workers = max(1, min(int(workers), 16))
        self.progress = progress
        self._openalex_disabled = False
        self._state_lock = threading.Lock()

    def _request(self, url: str, bearer: str | None = None) -> tuple[int | None, dict | None, str | None]:
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        status: int | None = None
        body: dict | None = None
        error: str | None = None
        for attempt in range(3):
            if bearer:
                status, body, error = _get_json(url, bearer)
            else:
                status, body, error = _get_json(url)
            if error or status == 429 or (status is not None and status >= 500):
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
            break
        self.cache.put(url, status, body, error)
        if self.delay:
            time.sleep(self.delay)
        return status, body, error

    def audit(self, references: list[ReferenceEntry]) -> list[Finding]:
        findings, _ = self.audit_with_results(references)
        return findings

    def audit_with_results(
        self, references: list[ReferenceEntry]
    ) -> tuple[list[Finding], list[ReferenceVerification]]:
        findings: list[Finding] = []
        verifications: list[ReferenceVerification] = []
        try:
            def audit_one(entry):
                if entry.doi:
                    return self._audit_doi(entry)
                return self._audit_bibliographic(entry)

            def collect(completed):
                for index, (item_findings, verification) in enumerate(completed, 1):
                    findings.extend(item_findings)
                    verifications.append(verification)
                    if self.progress:
                        self.progress(index, len(references), references[index - 1])

            if self.workers == 1:
                collect(map(audit_one, references))
            else:
                with ThreadPoolExecutor(
                    max_workers=self.workers, thread_name_prefix="reference-audit"
                ) as executor:
                    collect(executor.map(audit_one, references))
        finally:
            self.cache.save()
        return findings, verifications

    def _crossref_query(self, entry: ReferenceEntry) -> tuple[int | None, dict | None, str | None]:
        parameters = {
            "query.bibliographic": entry.raw[:1500],
            "rows": "5",
            "select": "DOI,title,author,issued,container-title,URL,type",
        }
        if self.email:
            parameters["mailto"] = self.email
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(parameters)
        return self._request(url)

    def _audit_bibliographic(self, entry: ReferenceEntry) -> tuple[list[Finding], ReferenceVerification]:
        cited_title = _cited_title(entry.raw)
        status, body, error = self._crossref_query(entry)
        if error or status != 200 or not body:
            verification = ReferenceVerification(
                entry.paragraph, entry.raw, "SERVICE_ERROR", "high", "Crossref",
                evidence=[error or f"HTTP {status}"],
            )
            return [
                Finding(
                    "REF004", "info", "Reference service could not be checked",
                    "Crossref could not be reached for this bibliography entry.",
                    Location(entry.paragraph, "References"), [error or f"HTTP {status}"],
                    "Retry the online audit; a service failure is not evidence that a reference is false.",
                )
            ], verification

        items = body.get("message", {}).get("items", [])
        candidates = []
        for item in items:
            actual_title = (item.get("title") or [""])[0]
            similarity = _title_similarity(cited_title, actual_title)
            authors = _authors(item)
            author_match = _author_matches(entry, authors)
            actual_year = _year(item)
            expected_year = int(entry.key.year[:4]) if entry.key and entry.key.year[:4].isdigit() else None
            year_match = expected_year is None or actual_year is None or abs(expected_year - actual_year) <= 1
            score = similarity * 0.78 + (0.14 if author_match else 0.0) + (0.08 if year_match else 0.0)
            candidates.append((score, similarity, author_match, year_match, item, authors, actual_year))

        if not candidates:
            return self._unverified(entry, cited_title, "Crossref returned no candidates")

        score, similarity, author_match, year_match, item, authors, actual_year = max(candidates, key=lambda value: value[0])
        actual_title = (item.get("title") or [""])[0]
        doi = item.get("DOI")
        url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)
        evidence = [
            f"Title similarity: {similarity:.2f}",
            f"Author match: {'yes' if author_match else 'no'}",
            f"Year match: {'yes' if year_match else 'no'}",
        ]

        if similarity >= 0.82 and (author_match or not authors) and year_match:
            retraction_findings, retraction_status = self._retraction_check(entry, doi, actual_title)
            verification = ReferenceVerification(
                entry.paragraph, entry.raw, "VERIFIED", "high", "Crossref", actual_title, authors,
                actual_year, doi, url, evidence, retraction_status,
            )
            if retraction_findings:
                verification.status = "RETRACTED"
            return retraction_findings, verification

        if similarity >= 0.96 and year_match:
            # Exact title and compatible year can verify a work even when a
            # registry has incomplete or organisational author metadata.
            retraction_findings, retraction_status = self._retraction_check(entry, doi, actual_title)
            verification = ReferenceVerification(
                entry.paragraph, entry.raw, "VERIFIED", "medium", "Crossref", actual_title,
                authors, actual_year, doi, url, evidence, retraction_status,
            )
            if retraction_findings:
                verification.status = "RETRACTED"
            return retraction_findings, verification

        if similarity >= 0.82:
            retraction_findings, retraction_status = self._retraction_check(entry, doi, actual_title)
            verification = ReferenceVerification(
                entry.paragraph, entry.raw, "REAL_BUT_MIS_CITED", "medium", "Crossref", actual_title,
                authors, actual_year, doi, url, evidence, retraction_status,
            )
            finding = Finding(
                "REF006", "medium", "Reference appears real but metadata differs",
                "Crossref found a strong title match, but the author or year does not agree.",
                Location(entry.paragraph, "References"),
                [f"Supplied: {entry.raw}", f"Matched: {actual_title}", *evidence],
                "Compare the supplied citation with the linked metadata and correct the differing fields.", "medium",
            )
            return [finding, *retraction_findings], verification

        if similarity >= 0.62 and score >= 0.62:
            verification = ReferenceVerification(
                entry.paragraph, entry.raw, "POSSIBLE_MATCH", "low", "Crossref", actual_title, authors,
                actual_year, doi, url, evidence,
            )
            return [
                Finding(
                    "REF007", "low", "Possible metadata match needs review",
                    "Crossref returned a plausible but inconclusive match.",
                    Location(entry.paragraph, "References"),
                    [f"Supplied: {entry.raw}", f"Candidate: {actual_title}", *evidence],
                    "Review the linked candidate manually; do not treat this result as verification.", "low",
                )
            ], verification
        return self._unverified(entry, cited_title, f"Best title similarity: {similarity:.2f}")

    def _unverified(
        self, entry: ReferenceEntry, cited_title: str, reason: str
    ) -> tuple[list[Finding], ReferenceVerification]:
        verification = ReferenceVerification(
            entry.paragraph, entry.raw, "UNVERIFIED", "medium", "Crossref",
            evidence=[reason, f"Parsed title: {cited_title or '[unavailable]'}"],
        )
        finding = Finding(
            "REF008", "low", "Reference was not verified in Crossref",
            "No sufficiently strong Crossref metadata match was found.",
            Location(entry.paragraph, "References"), [entry.raw, reason],
            "Search another appropriate index, publisher site, library catalogue, or author profile before drawing a conclusion.",
            "medium",
        )
        return [finding], verification

    def _audit_doi(self, entry: ReferenceEntry) -> tuple[list[Finding], ReferenceVerification]:
        doi = entry.doi or ""
        encoded = urllib.parse.quote(doi, safe="")
        query = f"?mailto={urllib.parse.quote(self.email)}" if self.email else ""
        status, body, error = self._request(f"https://api.crossref.org/works/{encoded}{query}")
        registrant = "Crossref"
        metadata = body.get("message", {}) if status == 200 and body else None

        if status == 404:
            ds_status, ds_body, ds_error = self._request(f"https://api.datacite.org/dois/{encoded}")
            error = error or ds_error
            if ds_status == 200 and ds_body:
                registrant = "DataCite"
                attrs = ds_body.get("data", {}).get("attributes", {})
                metadata = {
                    "title": [(attrs.get("titles") or [{}])[0].get("title", "")],
                    "issued": {"date-parts": [[attrs.get("publicationYear")]]},
                    "author": [{"name": creator.get("name", "")} for creator in attrs.get("creators", [])],
                    "URL": attrs.get("url"), "DOI": doi,
                }
                status = 200
            elif ds_status == 404:
                finding = Finding(
                    "REF001", "high", "DOI is not registered",
                    f"DOI {doi} returned 404 from both Crossref and DataCite.",
                    Location(entry.paragraph, "References"), [entry.raw],
                    "Check the publisher and search the title independently before treating the reference as fabricated.",
                )
                return [finding], ReferenceVerification(
                    entry.paragraph, entry.raw, "UNREGISTERED_DOI", "high", "Crossref + DataCite", doi=doi,
                    evidence=["Both registries returned HTTP 404"],
                )

        if error or status != 200 or not metadata:
            finding = Finding(
                "REF004", "info", "Reference registry could not be checked",
                f"DOI {doi} could not be verified because the registry returned {error or 'HTTP ' + str(status)}.",
                Location(entry.paragraph, "References"), suggestion="Retry; a service failure is not evidence of a false reference.",
            )
            return [finding], ReferenceVerification(
                entry.paragraph, entry.raw, "SERVICE_ERROR", "high", registrant, doi=doi,
                evidence=[error or f"HTTP {status}"],
            )

        actual_title = (metadata.get("title") or [""])[0]
        cited_title = _cited_title(entry.raw)
        authors = _authors(metadata)
        actual_year = _year(metadata)
        url = metadata.get("URL") or f"https://doi.org/{doi}"
        similarity = _doi_title_similarity(cited_title, actual_title)
        findings: list[Finding] = []
        verification_status = "VERIFIED"
        if cited_title and actual_title and similarity < 0.55:
            findings.append(
                Finding(
                    "REF002", "high", "DOI appears to resolve to a different work",
                    f"DOI {doi} resolves in {registrant}, but the registered title does not closely match.",
                    Location(entry.paragraph, "References"),
                    [f"Cited: {cited_title}", f"Registered: {actual_title}"],
                    "Correct the DOI or replace the bibliography metadata with the registered work.", "medium",
                )
            )
            verification_status = "REAL_BUT_MIS_CITED"

        if entry.key and actual_year and str(actual_year) != entry.key.year[:4]:
            findings.append(
                Finding(
                    "REF003", "medium", "Reference year differs from registry",
                    f"The citation says {entry.key.year[:4]}, while {registrant} reports {actual_year} for DOI {doi}.",
                    Location(entry.paragraph, "References"),
                    suggestion="Check for an online-first versus issue-date difference, then correct or annotate it.",
                    confidence="medium",
                )
            )
            verification_status = "REAL_BUT_MIS_CITED"

        retraction_findings, retraction_status = self._retraction_check(entry, doi, actual_title)
        findings.extend(retraction_findings)
        if retraction_findings:
            verification_status = "RETRACTED"
        verification = ReferenceVerification(
            entry.paragraph, entry.raw, verification_status, "high", registrant, actual_title, authors,
            actual_year, doi, url, [f"DOI registered in {registrant}", f"Title similarity: {similarity:.2f}"],
            retraction_status,
        )
        return findings, verification

    def _retraction_check(
        self, entry: ReferenceEntry, doi: str | None, title: str
    ) -> tuple[list[Finding], str]:
        if not doi:
            return [], "NOT_CHECKED_NO_DOI"
        if re.match(r"^\s*retracted\s*:", title, re.I):
            return [
                Finding(
                    "REF005", "high", "Cited work is marked as retracted",
                    f"The registered metadata title marks DOI {doi} as retracted.",
                    Location(entry.paragraph, "References"), [title],
                    "Review the retraction notice and replace or explicitly contextualise the citation.",
                )
            ], "RETRACTED"
        encoded = urllib.parse.quote(doi, safe="/")
        url = f"https://api.openalex.org/works/doi:{encoded}"
        cached = self.cache.get(url)
        if cached is not None:
            status, body, _ = cached
        else:
            with self._state_lock:
                disabled = self._openalex_disabled
            if disabled:
                return [], "UNAVAILABLE"
            status, body, error = self._request(url, bearer=self.openalex_api_key)
            if error or status == 429 or (status is not None and status >= 500):
                with self._state_lock:
                    self._openalex_disabled = True
        if status == 200 and body and body.get("is_retracted"):
            return [
                Finding(
                    "REF005", "high", "Cited work is marked as retracted",
                    f"OpenAlex marks DOI {doi} as retracted.", Location(entry.paragraph, "References"),
                    [title], "Review the retraction notice and replace or explicitly contextualise the citation.",
                )
            ], "RETRACTED"
        if status == 200 and body:
            return [], "NOT_RETRACTED"
        return [], "UNAVAILABLE"
