import streamlit as st
import pandas as pd
from publication_engine import run_search
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

st.write("publication_engine imported successfully")

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

if st.button("Run Search"):

    if uploaded_file is None:
        st.error("Please upload a roster file.")
        st.stop()

    roster = pd.read_excel(
        uploaded_file,
        sheet_name="Faculty Roster"
    )

    start_string = start_date.strftime("%Y/%m/%d")
    end_string = end_date.strftime("%Y/%m/%d")

    progress_bar = st.progress(0)
    status = st.empty()

    def update_progress(current, total, faculty_name):

        progress_bar.progress(current / total)

        status.info(
            f"Searching {current}/{total}: {faculty_name}"
    )

    results = run_search(
        roster,
        start_string,
        end_string,
        progress_callback=update_progress
    )

    st.success("Search complete")

    st.write(f"Matches found: {len(results)}")

    st.dataframe(
        results,
        use_container_width=True
    )