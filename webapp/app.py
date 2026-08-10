import streamlit as st

st.title("Faculty Publication Finder")

uploaded_file = st.file_uploader(
"Upload Faculty Roster",
type=["xlsx"]
)

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

if uploaded_file is not None:
    import pandas as pd

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
else:
    st.success(
    f"Roster validated: {len(roster)} faculty loaded"
)

    st.session_state["roster"] = roster

# st.success(f"Roster uploaded: {len(roster)} rows")

if st.button("Run Search"):
    st.write(f"Start: {start_date}")
    st.write(f"End: {end_date}")

    if uploaded_file is None:
        st.error("Please upload a roster file.")
    else:
        st.success("Ready to run search")