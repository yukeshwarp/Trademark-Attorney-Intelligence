import streamlit as st
import requests
import json
from io import BytesIO
import os
import fitz  # PyMuPDF
import re

# Set up API keys and endpoints
DI_ENDPOINT = os.getenv("COGNITIVE_SERVICES_DI_ENDPOINT")
DI_API_KEY = os.getenv("COGNITIVE_SERVICES_DI_API_KEY")
DI_MODEL_ID = os.getenv("DOCUMENT_INTELLIGENCE_MODEL")
llm_api_key = os.getenv("LLM_API_KEY")  # Assuming you have an LLM API key like OpenAI
azure_llm_endpoint = os.getenv("LLM_ENDPOINT")  # Endpoint for your LLM
llm_model = os.getenv("LLM_MODEL")
llm_api_version = os.getenv("LLM_API_VERSION")

headers = {
    "Ocp-Apim-Subscription-Key": DI_API_KEY,
    "Content-Type": "application/pdf"
}

llm_headers = {"Content-Type": "application/json", "api-key": llm_api_key}

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

def split_pdf_by_page_range(pdf_bytes, start_page, end_page):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    new_doc = fitz.open()

    # Append pages in the range to a new PDF
    for page_num in range(start_page - 1, end_page):  # 0-based index in PyMuPDF
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

    # Save the new document to a bytes buffer
    pdf_buffer = BytesIO()
    new_doc.save(pdf_buffer)
    pdf_buffer.seek(0)
    return pdf_buffer

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
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        flag = False
        extracted_text = ""
        page_numbers = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            if "USPTO Summary Page" in text:
                flag = True
            elif "ANALYST REVIEW −USPTO REPORT" in text:
                flag = False
                break
            if flag:
                extracted_text += text
                page_numbers.append(page_num)

        st.text(extracted_text)
        if extracted_text:  # If extracted text exists
            # Create a prompt for LLM to extract name and page ranges in the specified JSON format
            prompt = f"""
            The following text is extracted from a document. The task is to extract the name and associated page ranges in a structured JSON array format with each entry containing:
            - "name": The name of the entity (string).
            - "page-start": The first page number where the entity appears (string).
            - "page-end": The last page number where the entity appears (string).

            Example:
            The data will be as below
            '''
            1. ARRID EXTRA DRY
            Registered
            3
            CHURCH & DWIGHT CO., INC.
            73−716,876
            15
            2. ARRID EXTRA EXTRA DRY
            Registered
            3
            CHURCH & DWIGHT CO., INC.
            78−446,679
            18
            3. EXTRA RICH FOR DRY, THIRSTY HAIR
            Cancelled
            3
            NAMASTE LABORATORIES, L.L.C.
            77−847,568
            21
            '''
            It means that contents related to ARRID EXTRA DRY are from page 15 to 17 and ARRID EXTRA EXTRA DRY from page 18 to 20, similarly for the following any number of entries.

            Now process the following extracted text and return the output as a structured JSON array with fields "name", "start page" and "end page":

            {extracted_text}
            """

            data = {
                "model": llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts details.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0.0,
            }

            # Send the prompt to LLM for processing
            url = f"{azure_llm_endpoint}/openai/deployments/{llm_model}/chat/completions?api-version={llm_api_version}"
            llm_response = requests.post(url, headers=llm_headers, json=data, timeout=30)
            response = llm_response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if llm_response.status_code == 200:
                st.markdown(response)

                extracted_ranges = json.loads(response)
                for entry in extracted_ranges:
                    start_page = int(entry["page-start"])
                    end_page = int(entry["page-end"])
                    name = entry["name"]

                    split_pdf = split_pdf_by_page_range(pdf_bytes, start_page, end_page)

                    with st.spinner(f"Sending {name} pages {start_page}-{end_page} to Azure..."):
                        response = requests.post(
                            f"{DI_ENDPOINT}/formrecognizer/documentModels/{DI_MODEL_ID}:analyze?api-version=2023-07-31",
                            headers=headers,
                            data=split_pdf.read()
                        )

                        if response.status_code == 202:
                            operation_location = response.headers.get("Operation-Location")

                            while True:
                                poll_response = requests.get(operation_location, headers=headers)
                                result = poll_response.json()

                                if result.get("status") == "succeeded":
                                    extracted_data = result["analyzeResult"]
                                    st.success(f"{name} processed successfully!")
                                    st.json(extracted_data)
                                    break
                                elif result.get("status") == "failed":
                                    st.error(f"Failed to process {name}.")
                                    break
                        else:
                            st.error("Failed to send document to Azure.")
            else:
                st.error("Failed to get response from LLM.")
