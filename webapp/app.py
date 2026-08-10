import streamlit as st
import pandas as pd

from pubmed_faculty_edat_strict import build_query
from pubmed_faculty_edat_strict import search_pmids

st.set_page_config(page_title="Faculty Publication Finder")

st.title("Faculty Publication Finder")

uploaded_file = st.file_uploader(
    "Upload Faculty Roster",
    type=["xlsx"]
)

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

roster = None

if uploaded_file is not None:

    roster = pd.read_excel(
        uploaded_file,
        sheet_name="Faculty Roster"
    )

    required_columns = [
        "Last Name",
        "First Name / Initial",
        "PubMed Initials"
    ]

    missing_columns = [
        col for col in required_columns
        if col not in roster.columns
    ]

    if missing_columns:
        st.error(
            "Missing columns: " + ", ".join(missing_columns)
        )
        st.stop()

    st.success(
        f"Roster validated: {len(roster)} faculty loaded"
    )

if st.button("Run Search"):

    if roster is None:
        st.error("Please upload a roster file.")
        st.stop()

    faculty = roster.iloc[0]

    start_string = start_date.strftime("%Y/%m/%d")
    end_string = end_date.strftime("%Y/%m/%d")

    query = build_query(
        faculty,
        start_string,
        end_string
    )

    st.subheader("Test Search")

    st.write("Faculty:")
    st.write(faculty["Faculty Name"])

    st.write("Query:")
    st.code(query)

    with st.spinner("Searching PubMed..."):
        pmids = search_pmids(query)

    st.success("Search complete")

    st.write(
        f"PMIDs Found: {len(pmids)}"
    )

    if pmids:
        st.write(pmids[:20])
