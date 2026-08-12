from collections import defaultdict
import time

import pandas as pd

from pubmed_faculty_edat_strict import (
    canonical_faculty_name,
    build_query,
    search_pmids,
    fetch_records,
    parse_article,
    classify_match,
    keep_candidate,
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

        pmids = search_pmids(query)

        time.sleep(0.5)

        missing_pmids = [
            pmid
            for pmid in pmids
            if pmid not in article_cache
        ]

        if missing_pmids:

            for raw_record in fetch_records(
                missing_pmids
            ):

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

    return results, unique
