import streamlit as st
import requests
import json
from io import BytesIO
import os

DI_ENDPOINT = os.getenv("COGNITIVE_SERVICES_DI_ENDPOINT")
DI_API_KEY = os.getenv("COGNITIVE_SERVICES_DI_API_KEY")
DI_MODEL_ID = os.getenv("DOCUMENT_INTELLIGENCE_MODEL")

headers = {
    "Ocp-Apim-Subscription-Key": DI_API_KEY,
    "Content-Type": "application/pdf"
}

# Initialize session state if not already set
if 'documents' not in st.session_state:
    st.session_state.documents = {}
if 'removed_documents' not in st.session_state:
    st.session_state.removed_documents = []

# Streamlit App
st.title("PDF to Azure Document Intelligence")

uploaded_files = st.file_uploader(
    "Upload files less than 400 pages",
    type=["pdf", "docx", "xlsx", "pptx"],
    accept_multiple_files=True,
    help="If your question is not answered properly or there's an error, consider uploading smaller documents or splitting larger ones.",
    label_visibility="collapsed",
)

if uploaded_files:
    new_files = []
    for uploaded_file in uploaded_files:
        # Skip files that are removed or already uploaded
        if (
            uploaded_file.name
            not in [
                st.session_state.documents[doc_id]["name"]
                for doc_id in st.session_state.documents
            ]
            and uploaded_file.name not in st.session_state.removed_documents
        ):
            new_files.append(uploaded_file)

    for new_file in new_files:
        st.success(f"File Selected: {new_file.name}")
        pdf_bytes = new_file.read()

        with st.spinner("Sending to Azure..."):
            response = requests.post(
                f"{DI_ENDPOINT}/formrecognizer/documentModels/{DI_MODEL_ID}:analyze?api-version=2023-07-31",
                headers=headers,
                data=pdf_bytes
            )

            if response.status_code == 202:
                operation_location = response.headers["Operation-Location"]
                st.write("Processing... Please wait.")

                # Poll for result
                while True:
                    poll_response = requests.get(operation_location, headers={"Ocp-Apim-Subscription-Key": DI_API_KEY})
                    result = poll_response.json()

                    if result.get("status") == "succeeded":
                        extracted_data = result["analyzeResult"]
                        st.success("Document processed successfully!")
                        break
                    elif result.get("status") == "failed":
                        st.error("Failed to process document.")
                        st.json(result)
                        break
            else:
                st.error("Error sending document to Azure.")
                st.json(response.json())

        # Display Extracted Data
        if extracted_data:
            st.subheader("Extracted Data")
            fields_to_display = ["Trademark", "Owner", "Class", "Status", "Goods/Service", "Design Phrase"]
            extracted_fields = {}

            documents = extracted_data.get("documents", [])
            for doc in documents:
                fields = doc.get("fields", {})
                for field_name, field_value in fields.items():
                    if field_name in fields_to_display:
                        extracted_fields[field_name] = field_value.get("valueString", "N/A")
            
            st.json(extracted_fields)
