import streamlit as st

st.title("Penn State Emergency Medicine Publication Finder")

st.write("This is the first test of the web app.")

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

if st.button("Run Search"):
    st.success("Button works!")
    st.write("Start:", start_date)
    st.write("End:", end_date)