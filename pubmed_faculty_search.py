from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from Bio import Entrez


START_DATE = "2026/07/01"
END_DATE = "2026/07/31"
INPUT_FILE = "Penn_State_EM_Faculty.xlsx"
OUTPUT_FILE = "Penn_State_EM_PubMed_Results.xlsx"

# NCBI asks E-utilities users to provide an email address.
Entrez.email = "jeffrey.s.lubin@gmail.com"


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def canonical_faculty_name(row: pd.Series) -> str:
    """Build the display name from the corrected component columns."""
    last = clean_text(row.get("Last Name"))
    first = clean_text(row.get("First Name / Initial"))
    return f"{last}, {first}" if first else last


def build_query(row: pd.Series) -> str:
    last = clean_text(row.get("Last Name"))
    first = clean_text(row.get("First Name / Initial"))
    initials = clean_text(row.get("PubMed Initials"))

    if not last or not initials:
        raise ValueError(
            f"Missing Last Name or PubMed Initials for {canonical_faculty_name(row)}"
        )

    date_part = f'("{START_DATE}"[Date - Publication] : "{END_DATE}"[Date - Publication])'
    terms: list[str] = []

    # Full Author Name is precise when PubMed has the complete name.
    if len(first) > 1:
        terms.append(f'"{first} {last}"[Full Author Name]')

    # Author surname + initials is broader and catches records without full names.
    terms.append(f'"{last} {initials}"[Author]')

    return f'({" OR ".join(terms)}) AND {date_part}'


def search_pmids(query: str) -> list[str]:
    with Entrez.esearch(
        db="pubmed",
        term=query,
        retmax=10000,
        sort="pub date",
    ) as handle:
        result = Entrez.read(handle)
    return list(result.get("IdList", []))


def fetch_records(pmids: list[str]) -> list[dict]:
    records: list[dict] = []
    for start in range(0, len(pmids), 200):
        batch = pmids[start:start + 200]
        with Entrez.efetch(
            db="pubmed",
            id=",".join(batch),
            rettype="medline",
            retmode="xml",
        ) as handle:
            data = Entrez.read(handle)
        records.extend(data.get("PubmedArticle", []))
        time.sleep(0.4)
    return records


def article_date(record: dict) -> str:
    issue = (
        record.get("MedlineCitation", {})
        .get("Article", {})
        .get("Journal", {})
        .get("JournalIssue", {})
    )
    pub_date = issue.get("PubDate", {})

    year = clean_text(pub_date.get("Year"))
    month = clean_text(pub_date.get("Month"))
    day = clean_text(pub_date.get("Day"))
    medline_date = clean_text(pub_date.get("MedlineDate"))

    if year:
        return "-".join(part for part in [year, month, day] if part)
    return medline_date


def parse_article(record: dict) -> dict[str, Any]:
    citation = record.get("MedlineCitation", {})
    article = citation.get("Article", {})
    journal = article.get("Journal", {})

    authors: list[str] = []
    author_details: list[dict[str, str]] = []
    affiliations: list[str] = []

    for author in article.get("AuthorList", []):
        collective = clean_text(author.get("CollectiveName"))
        if collective:
            authors.append(collective)
            author_details.append(
                {"last": collective, "fore": "", "initials": "", "display": collective}
            )
            continue

        last = clean_text(author.get("LastName"))
        fore = clean_text(author.get("ForeName"))
        initials = clean_text(author.get("Initials"))
        display = ", ".join(part for part in [last, fore] if part)

        authors.append(display)
        author_details.append(
            {"last": last, "fore": fore, "initials": initials, "display": display}
        )

        for affiliation_info in author.get("AffiliationInfo", []):
            affiliation = clean_text(affiliation_info.get("Affiliation"))
            if affiliation:
                affiliations.append(affiliation)

    doi = ""
    for article_id in record.get("PubmedData", {}).get("ArticleIdList", []):
        attributes = getattr(article_id, "attributes", {})
        if attributes.get("IdType") == "doi":
            doi = clean_text(article_id)
            break

    publication_types = [
        clean_text(item)
        for item in article.get("PublicationTypeList", [])
        if clean_text(item)
    ]

    return {
        "PMID": clean_text(citation.get("PMID")),
        "Title": clean_text(article.get("ArticleTitle")),
        "Journal": clean_text(journal.get("Title")),
        "Publication Date": article_date(record),
        "Authors": "; ".join(authors),
        "Affiliations": " | ".join(dict.fromkeys(affiliations)),
        "DOI": doi,
        "Publication Types": "; ".join(publication_types),
        "_author_details": author_details,
    }


def matching_affiliation(row: pd.Series, affiliation_text: str) -> str:
    affiliation_lower = affiliation_text.lower()

    if any(
        phrase in affiliation_lower
        for phrase in ["penn state", "pennsylvania state", "hershey"]
    ):
        return "Penn State/Hershey affiliation present"

    secondary = clean_text(row.get("Secondary Institution(s)"))
    for part in re.split(r"[;,|]", secondary):
        part = part.strip().lower()
        if part and part in affiliation_lower:
            return "Secondary affiliation present"

    return ""


def confidence_for_match(
    row: pd.Series, article: dict[str, Any]
) -> tuple[str, str]:
    last = clean_text(row.get("Last Name")).lower()
    first = clean_text(row.get("First Name / Initial")).lower()
    initials = clean_text(row.get("PubMed Initials")).lower()

    surname_matches = [
        author
        for author in article["_author_details"]
        if author["last"].lower() == last
    ]

    if not surname_matches:
        return "Unlikely", "No exact surname match in the parsed author list"

    affiliation_reason = matching_affiliation(row, article["Affiliations"])

    if len(first) > 1:
        for author in surname_matches:
            fore = author["fore"].lower()
            if fore == first or fore.startswith(first + " ") or first.startswith(fore + " "):
                reason = "Exact given-name and surname match"
                if affiliation_reason:
                    reason += f"; {affiliation_reason}"
                return "Likely", reason

        for author in surname_matches:
            if author["initials"].lower().startswith(initials):
                reason = "Surname and initials match; full given name unavailable or different"
                if affiliation_reason:
                    return "Likely", f"{reason}; {affiliation_reason}"
                return "Needs Review", reason

        return "Needs Review", "Surname matches, but given name or initials do not clearly match"

    for author in surname_matches:
        if author["initials"].lower().startswith(initials):
            if affiliation_reason:
                return "Likely", f"Initial and surname match; {affiliation_reason}"
            return "Needs Review", "Roster contains only an initial; identity requires review"

    return "Needs Review", "Surname matches, but initials do not clearly match"


def format_sheet(writer: pd.ExcelWriter, sheet_name: str, dataframe: pd.DataFrame) -> None:
    worksheet = writer.book[sheet_name]
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    for column_number, column_name in enumerate(dataframe.columns, start=1):
        values = [clean_text(column_name)]
        values.extend(clean_text(value) for value in dataframe[column_name].head(300))
        width = min(max(len(value) for value in values) + 2, 60)
        letter = worksheet.cell(1, column_number).column_letter
        worksheet.column_dimensions[letter].width = width

    for cell in worksheet[1]:
        cell.font = cell.font.copy(bold=True)
        cell.alignment = cell.alignment.copy(wrap_text=True)

    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = cell.alignment.copy(vertical="top", wrap_text=True)


def main() -> None:
    folder = Path(__file__).resolve().parent
    input_path = folder / INPUT_FILE
    output_path = folder / OUTPUT_FILE

    if not input_path.exists():
        raise FileNotFoundError(
            f"Could not find {INPUT_FILE} in {folder}. "
            "Place the workbook and this script in the same folder."
        )

    roster = pd.read_excel(input_path, sheet_name="Faculty Roster")
    required_columns = {"Last Name", "First Name / Initial", "PubMed Initials"}
    missing_columns = required_columns - set(roster.columns)
    if missing_columns:
        raise ValueError(
            "The Faculty Roster sheet is missing: "
            + ", ".join(sorted(missing_columns))
        )

    roster = roster.dropna(subset=["Last Name", "PubMed Initials"]).copy()

    all_matches: list[dict[str, Any]] = []
    article_cache: dict[str, dict[str, Any]] = {}

    print(f"Searching {len(roster)} faculty members...")
    print(f"Publication date range: {START_DATE} through {END_DATE}\n")

    for number, (_, faculty) in enumerate(roster.iterrows(), start=1):
        faculty_name = canonical_faculty_name(faculty)
        query = build_query(faculty)

        print(f"[{number}/{len(roster)}] {faculty_name}")
        pmids = search_pmids(query)
        print(f"    PubMed results found: {len(pmids)}")

        missing_pmids = [pmid for pmid in pmids if pmid not in article_cache]
        if missing_pmids:
            for raw_record in fetch_records(missing_pmids):
                parsed = parse_article(raw_record)
                if parsed["PMID"]:
                    article_cache[parsed["PMID"]] = parsed

        for pmid in pmids:
            article = article_cache.get(pmid)
            if not article:
                continue

            confidence, reason = confidence_for_match(faculty, article)
            all_matches.append(
                {
                    "Faculty Name": faculty_name,
                    "Confidence": confidence,
                    "Reason": reason,
                    "PMID": article["PMID"],
                    "Title": article["Title"],
                    "Journal": article["Journal"],
                    "Publication Date": article["Publication Date"],
                    "Authors": article["Authors"],
                    "Affiliations": article["Affiliations"],
                    "DOI": article["DOI"],
                    "Publication Types": article["Publication Types"],
                    "Search Query": query,
                }
            )

        time.sleep(0.4)

    result_columns = [
        "Faculty Name", "Confidence", "Reason", "PMID", "Title", "Journal",
        "Publication Date", "Authors", "Affiliations", "DOI",
        "Publication Types", "Search Query"
    ]
    results = pd.DataFrame(all_matches, columns=result_columns)

    if not results.empty:
        order = pd.CategoricalDtype(
            ["Likely", "Needs Review", "Unlikely"], ordered=True
        )
        results["Confidence"] = results["Confidence"].astype(order)
        results = results.sort_values(
            ["Confidence", "Faculty Name", "Publication Date", "PMID"],
            ascending=[True, True, False, True],
        )
        results["Confidence"] = results["Confidence"].astype(str)

    unique_map: dict[str, dict[str, Any]] = {}
    matched_faculty: defaultdict[str, list[str]] = defaultdict(list)
    confidence_by_pmid: defaultdict[str, list[str]] = defaultdict(list)

    for _, row in results.iterrows():
        pmid = clean_text(row["PMID"])
        matched_faculty[pmid].append(clean_text(row["Faculty Name"]))
        confidence_by_pmid[pmid].append(clean_text(row["Confidence"]))

        unique_map.setdefault(
            pmid,
            {
                "PMID": pmid,
                "Title": row["Title"],
                "Journal": row["Journal"],
                "Publication Date": row["Publication Date"],
                "Authors": row["Authors"],
                "Affiliations": row["Affiliations"],
                "DOI": row["DOI"],
                "Publication Types": row["Publication Types"],
            },
        )

    unique_rows: list[dict[str, Any]] = []
    for pmid, article in unique_map.items():
        confidence_values = confidence_by_pmid[pmid]
        overall_confidence = (
            "Likely"
            if "Likely" in confidence_values
            else "Needs Review"
            if "Needs Review" in confidence_values
            else "Unlikely"
        )

        unique_rows.append(
            {
                "Overall Confidence": overall_confidence,
                "Matched Faculty": "; ".join(dict.fromkeys(matched_faculty[pmid])),
                **article,
            }
        )

    unique = pd.DataFrame(unique_rows)
    if not unique.empty:
        unique = unique.sort_values(
            ["Overall Confidence", "Publication Date", "PMID"],
            ascending=[True, False, True],
        )

    if results.empty:
        summary = pd.DataFrame(
            columns=[
                "Faculty Name", "Likely", "Needs Review",
                "Unlikely", "Total Retrieved"
            ]
        )
    else:
        summary = (
            results.groupby(["Faculty Name", "Confidence"], dropna=False)
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )
        for column in ["Likely", "Needs Review", "Unlikely"]:
            if column not in summary.columns:
                summary[column] = 0
        summary["Total Retrieved"] = (
            summary["Likely"]
            + summary["Needs Review"]
            + summary["Unlikely"]
        )
        summary = summary[
            ["Faculty Name", "Likely", "Needs Review", "Unlikely", "Total Retrieved"]
        ]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        unique.to_excel(writer, sheet_name="Unique Publications", index=False)
        results.to_excel(writer, sheet_name="Faculty Matches", index=False)
        summary.to_excel(writer, sheet_name="Review Summary", index=False)

        format_sheet(writer, "Unique Publications", unique)
        format_sheet(writer, "Faculty Matches", results)
        format_sheet(writer, "Review Summary", summary)

    print("\nFinished.")
    print(f"Results saved to:\n{output_path}")


if __name__ == "__main__":
    main()
