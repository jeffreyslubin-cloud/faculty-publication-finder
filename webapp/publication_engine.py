from collections import defaultdict
from io import BytesIO
import time
from urllib.error import HTTPError, URLError

import pandas as pd

from pubmed_faculty_edat_strict import (
    canonical_faculty_name,
    build_query,
    search_pmids,
    fetch_records,
    parse_article,
    classify_match,
    keep_candidate,
    format_sheet,
)


RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6
BASE_RETRY_SECONDS = 2.0
MAX_RETRY_SECONDS = 30.0
REQUEST_SPACING_SECONDS = 0.5


class PubMedRequestError(RuntimeError):
    pass


def _retry_pubmed_call(operation, faculty_name, function, *args):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            time.sleep(REQUEST_SPACING_SECONDS)
            return function(*args)
        except HTTPError as error:
            retryable = error.code in RETRYABLE_HTTP_CODES
            if not retryable or attempt == MAX_ATTEMPTS:
                raise PubMedRequestError(
                    f"PubMed {operation} failed for {faculty_name} "
                    f"with HTTP {error.code}: {error.reason}"
                ) from error

            retry_after = error.headers.get("Retry-After") if error.headers else None
            try:
                retry_seconds = float(retry_after) if retry_after else None
            except (TypeError, ValueError):
                retry_seconds = None

            if retry_seconds is None:
                retry_seconds = min(
                    BASE_RETRY_SECONDS * (2 ** (attempt - 1)),
                    MAX_RETRY_SECONDS,
                )
            time.sleep(retry_seconds)

        except URLError as error:
            if attempt == MAX_ATTEMPTS:
                raise PubMedRequestError(
                    f"PubMed {operation} failed for {faculty_name}: {error.reason}"
                ) from error

            retry_seconds = min(
                BASE_RETRY_SECONDS * (2 ** (attempt - 1)),
                MAX_RETRY_SECONDS,
            )
            time.sleep(retry_seconds)


def _search_pmids_with_retry(query, faculty_name):
    return _retry_pubmed_call(
        "search",
        faculty_name,
        search_pmids,
        query,
    )


def _fetch_records_with_retry(pmids, faculty_name):
    return _retry_pubmed_call(
        "record fetch",
        faculty_name,
        fetch_records,
        pmids,
    )


def run_search(
    roster,
    start_date,
    end_date,
    progress_callback=None
):

    roster = roster.dropna(
        subset=["Last Name", "PubMed Initials"]
    ).copy()

    kept_matches = []
    article_cache = {}
    excluded_counts = defaultdict(int)

    total = len(roster)

    for number, (_, faculty) in enumerate(
        roster.iterrows(),
        start=1
    ):

        if progress_callback:
            progress_callback(
                number,
                total,
                canonical_faculty_name(faculty)
            )

        faculty_name = canonical_faculty_name(
            faculty
        )

        query = build_query(
            faculty,
            start_date,
            end_date
        )

        pmids = _search_pmids_with_retry(
            query,
            faculty_name
        )

        missing_pmids = [
            pmid
            for pmid in pmids
            if pmid not in article_cache
        ]

        if missing_pmids:

            fetched_records = _fetch_records_with_retry(
                missing_pmids,
                faculty_name
            )

            for raw_record in fetched_records:

                parsed = parse_article(
                    raw_record
                )

                if parsed["PMID"]:

                    article_cache[
                        parsed["PMID"]
                    ] = parsed

        for pmid in pmids:

            article = article_cache.get(
                pmid
            )

            if not article:
                continue

            confidence, reason, institution_match, em_match = (
                classify_match(
                    faculty,
                    article
                )
            )

            if not keep_candidate(
                confidence,
                institution_match,
                em_match
            ):

                excluded_counts[
                    confidence
                ] += 1

                continue

            kept_matches.append({
                "Faculty Name": faculty_name,
                "Confidence": confidence,
                "Reason": reason,
                "PMID": article["PMID"],
                "PubMed Entry Date":
                    article["PubMed Entry Date"],
                "Publication Date":
                    article["Publication Date"],
                "Title": article["Title"],
                "Journal": article["Journal"],
                "Authors": article["Authors"],
                "Affiliations":
                    article["Affiliations"],
                "Penn State/Hershey Affiliation":
                    "Yes"
                    if institution_match
                    else "No",
                "Emergency Medicine Affiliation":
                    "Yes"
                    if em_match
                    else "No",
                "DOI": article["DOI"],
                "Publication Types":
                    article["Publication Types"],
                "Search Query": query,
            })

    results = pd.DataFrame(
        kept_matches
    )

    if not results.empty:

        rank = {
            "Likely": 0,
            "Needs Review": 1
        }

        results["_rank"] = (
            results["Confidence"]
            .map(rank)
            .fillna(9)
        )

        results = (
            results
            .sort_values(
                [
                    "_rank",
                    "Faculty Name",
                    "PubMed Entry Date",
                    "PMID",
                ],
                ascending=[
                    True,
                    True,
                    False,
                    True,
                ],
            )
            .drop(columns=["_rank"])
            .drop_duplicates(
                subset=[
                    "Faculty Name",
                    "PMID",
                ]
            )
        )

    unique_columns = [
        "PMID",
        "PubMed Entry Date",
        "Publication Date",
        "Title",
        "Journal",
        "Authors",
        "Affiliations",
        "DOI",
        "Publication Types",
        "Matched Faculty",
    ]

    if results.empty:
        unique = pd.DataFrame(columns=unique_columns)
        summary = pd.DataFrame(
            columns=[
                "Faculty Name",
                "Likely",
                "Needs Review",
                "Total Retained",
            ]
        )
    else:
        unique = (
            results.groupby("PMID", as_index=False)
            .agg({
                "PubMed Entry Date": "first",
                "Publication Date": "first",
                "Title": "first",
                "Journal": "first",
                "Authors": "first",
                "Affiliations": "first",
                "DOI": "first",
                "Publication Types": "first",
                "Faculty Name": lambda values: "; ".join(dict.fromkeys(values)),
            })
            .rename(columns={"Faculty Name": "Matched Faculty"})
        )

        summary = (
            results.groupby(
                ["Faculty Name", "Confidence"],
                dropna=False
            )
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )

        for column in ["Likely", "Needs Review"]:
            if column not in summary.columns:
                summary[column] = 0

        summary["Total Retained"] = (
            summary["Likely"]
            + summary["Needs Review"]
        )

        summary = summary[
            [
                "Faculty Name",
                "Likely",
                "Needs Review",
                "Total Retained",
            ]
        ]

    return results, unique, summary


def build_workbook(
    results,
    unique,
    summary
):
    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:
        unique.to_excel(
            writer,
            sheet_name="Unique Publications",
            index=False
        )
        results.to_excel(
            writer,
            sheet_name="Faculty Matches",
            index=False
        )
        summary.to_excel(
            writer,
            sheet_name="Review Summary",
            index=False
        )

        format_sheet(
            writer,
            "Unique Publications",
            unique
        )
        format_sheet(
            writer,
            "Faculty Matches",
            results
        )
        format_sheet(
            writer,
            "Review Summary",
            summary
        )

    output.seek(0)
    return output.getvalue()
