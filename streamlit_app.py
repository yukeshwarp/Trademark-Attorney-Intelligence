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
        capture = False
        for page in doc:
            text = page.get_text()
            if "USPTO Summary Page" in text:
                flag = True
            elif "ANALYST REVIEW −USPTO REPORT" in text:
                flag = False
                break
            if flag:
                extracted_text = extracted_text + text
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
            response = requests.post(url, headers=llm_headers, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                choices = result.get("choices", [])
                if choices:
                    extracted_data = choices[0].get("message", {}).get("content", "").strip()
                    if extracted_data:
                        try:
                            structured_output = json.loads(extracted_data)
                            st.subheader("Extracted Name and Page Ranges")
                            st.json(structured_output)
                        except json.JSONDecodeError:
                            st.error("Error parsing LLM response as JSON.")
                            st.text(extracted_data)
                    else:
                        st.warning("No names and page ranges extracted by the LLM.")
                else:
                    st.error("No choices returned from LLM response.")
            else:
                st.error(f"Error processing LLM response: {response.status_code}")
                st.json(response.json())
            # Optionally, send to Azure for further processing (if needed)
            proceed = st.button("Assess Conflict")
            if proceed:
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
        else:
            st.warning("No relevant section found in the document.")
