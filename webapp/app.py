import streamlit as st
import pandas as pd

from publication_engine import build_workbook, run_search

st.set_page_config(
    page_title="Faculty Publication Finder",
    layout="wide"
)

st.title("Faculty Publication Finder")

test_mode = st.checkbox(
    "Test Mode (first 10 faculty only)",
    value=True
)

uploaded_file = st.file_uploader(
    "Upload Faculty Roster (.xlsx)",
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
        "PubMed Initials",
    ]

    missing = [
        c for c in required_columns
        if c not in roster.columns
    ]

    if missing:
        st.error(
            "Missing columns: "
            + ", ".join(missing)
        )
        st.stop()

    st.success(
        f"Roster validated: {len(roster)} faculty loaded"
    )

if st.button("Run Search"):

    if uploaded_file is None:
        st.error("Please upload a roster file.")
        st.stop()

    start_string = start_date.strftime(
        "%Y/%m/%d"
    )

    end_string = end_date.strftime(
        "%Y/%m/%d"
    )

    progress_bar = st.progress(0)

    status = st.empty()

    def update_progress(
        current,
        total,
        faculty_name
    ):
        progress_bar.progress(
            current / total
        )

        status.info(
            f"Searching {current}/{total}: "
            f"{faculty_name}"
        )

    results, unique, summary = run_search(
        roster,
        start_string,
        end_string,
        progress_callback=update_progress
    )

    status.success(
        "Search complete"
    )

    st.success(
        "Search complete"
    )

    st.write(
        f"Matches found: {len(results)}"
    )

    st.write(
        f"Unique publications: {len(unique)}"
    )

    st.subheader(
        "Faculty Matches"
    )

    st.dataframe(
        results,
        use_container_width=True
    )

    st.subheader(
        "Unique Publications"
    )

    st.dataframe(
        unique,
        use_container_width=True
    )

    st.subheader(
        "Review Summary"
    )

    st.dataframe(
        summary,
        use_container_width=True
    )


    workbook_data = build_workbook(
        results,
        unique,
        summary
    )

    output_filename = (
        "Penn_State_EM_EDAT_Results_"
        f"{start_string.replace('/', '')}_to_"
        f"{end_string.replace('/', '')}.xlsx"
    )

    st.download_button(
        label="Download Excel Workbook",
        data=workbook_data,
        file_name=output_filename,
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )
