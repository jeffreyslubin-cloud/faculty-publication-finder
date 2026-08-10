import streamlit as st
import pandas as pd
from datetime import datetime
from pubmed_faculty_edat_strict import (
    build_query,
    search_pmids,
    fetch_records,
    parse_article,
    classify_match,
    keep_candidate,
    canonical_faculty_name,
)

st.set_page_config(page_title="Faculty Publication Finder", layout="wide")

st.title("Faculty Publication Finder")

uploaded_file = st.file_uploader(
    "Upload Faculty Roster (.xlsx)",
    type=["xlsx"]
)

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

roster = None

if uploaded_file is not None:
    roster = pd.read_excel(uploaded_file, sheet_name="Faculty Roster")

    required_columns = [
        "Last Name",
        "First Name / Initial",
        "PubMed Initials",
    ]

    missing = [c for c in required_columns if c not in roster.columns]

    if missing:
        st.error("Missing columns: " + ", ".join(missing))
        st.stop()

    st.success(f"Roster validated: {len(roster)} faculty loaded")

if st.button("Run Search", type="primary"):

    if roster is None:
        st.error("Please upload a roster file.")
        st.stop()

    start_string = start_date.strftime("%Y/%m/%d")
    end_string = end_date.strftime("%Y/%m/%d")

    progress = st.progress(0)
    status = st.empty()

    kept_matches = []
    article_cache = {}

    total_faculty = len(roster)

    for idx, (_, faculty) in enumerate(roster.iterrows(), start=1):

        faculty_name = canonical_faculty_name(faculty)
        status.write(f"Processing {idx}/{total_faculty}: {faculty_name}")

        query = build_query(faculty, start_string, end_string)
        pmids = search_pmids(query)

        missing_pmids = [p for p in pmids if p not in article_cache]

        if missing_pmids:
            for record in fetch_records(missing_pmids):
                parsed = parse_article(record)
                if parsed["PMID"]:
                    article_cache[parsed["PMID"]] = parsed

        for pmid in pmids:
            article = article_cache.get(pmid)

            if not article:
                continue

            confidence, reason, institution_match, em_match = classify_match(
                faculty,
                article,
            )

            if not keep_candidate(confidence, institution_match, em_match):
                continue

            kept_matches.append({
                "Faculty Name": faculty_name,
                "Confidence": confidence,
                "Reason": reason,
                "PMID": article["PMID"],
                "PubMed Entry Date": article["PubMed Entry Date"],
                "Publication Date": article["Publication Date"],
                "Title": article["Title"],
                "Journal": article["Journal"],
                "DOI": article["DOI"],
            })

        progress.progress(idx / total_faculty)

    results = pd.DataFrame(kept_matches)

    status.success("Search complete")

    st.metric("Faculty", total_faculty)
    st.metric("Matches", len(results))

    if results.empty:
        st.warning("No matches found.")
    else:
        st.dataframe(results, use_container_width=True)

        csv = results.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Download Results CSV",
            data=csv,
            file_name="faculty_publications.csv",
            mime="text/csv",
        )
