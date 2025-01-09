import streamlit as st
import requests
import json
from io import BytesIO
import logging
import os
import fitz
import re
import uuid
import redis
from openai import AzureOpenAI
import asyncio
from concurrent.futures import ThreadPoolExecutor
import tiktoken
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Union

llm_api_key = ""
azure_llm_endpoint = ""
llm_model = ""
llm_api_version = ""

llm_headers = {"Content-Type": "application/json", "api-key": llm_api_key}

def preprocess_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\u2013\u2014]', '-', text)
    text = re.sub(r'[\u2013\u2014]', '-', text)
    return text

def count_tokens(text):
    encoding = tiktoken.encoding_for_model(llm_model)
    return len(encoding.encode(text))

if "documents" not in st.session_state:
    st.session_state.documents = {}
if "removed_documents" not in st.session_state:
    st.session_state.removed_documents = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

st.title("Page range extractor")

uploaded_files = st.file_uploader(
    "Upload files less than 400 pages",
    type=["pdf", "docx", "xlsx", "pptx"],
    accept_multiple_files=True,
    help="If your question is not answered properly or there's an error, consider uploading smaller documents or splitting larger ones.",
    label_visibility="collapsed",
)

class TrademarkDetails(BaseModel):
    trademark_name: str = Field(description="The name of the Trademark", example="DISCOVER")
    status: str = Field(description="The Status of the Trademark", example="Registered")
    serial_number: str = Field(description="The Serial Number of the trademark from Chronology section", example="87−693,628")
    international_class_number: List[int] = Field(description="The International class number or Nice Classes number of the trademark from Goods/Services section or Nice Classes section", example=[18])
    owner: str = Field(description="The owner of the trademark", example="WALMART STORES INC")
    goods_services: str = Field(description="The goods/services from the document", example="LUGGAGE AND CARRYING BAGS; SUITCASES, TRUNKS, TRAVELLING BAGS, SLING BAGS FOR CARRYING INFANTS, SCHOOL BAGS; PURSES; WALLETS; RETAIL AND ONLINE RETAIL SERVICES")
    page_number: int = Field(description="The page number where the trademark details are found in the document", example=3)
    registration_number: Union[str, None] = Field(description="The Registration number of the trademark from Chronology section", example="5,809,957")
    design_phrase: str = Field(description="The design phrase of the trademark", example="THE MARK CONSISTS OF THE STYLIZED WORD 'MINI' FOLLOWED BY 'BY MOTHERHOOD.'", default="")


if uploaded_files:
    new_files = []
    for uploaded_file in uploaded_files:
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
            page = doc[0]
            rect = page.rect
            height = 50
            clip = fitz.Rect(0, height, rect.width, rect.height-height)
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            extracted_pages = []
            page_numbers = []
            extracted_pages2 = []
            flag = False
            
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text(clip=clip)
                extracted_pages2.append(text)

            for page_num, page in enumerate(doc, start=1):
                text = page.get_text()
                if "USPTO Summary Page" in text:
                    flag = True
                elif "ANALYST REVIEW −USPTO REPORT" in text:
                    flag = False
                    break
                if flag:
                    extracted_pages.append(text) 
                    page_numbers.append(page_num)
                    
            if extracted_pages:
                extracted_text = "\n".join(extracted_pages)
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
                    73-716,876
                    15
                    2. ARRID EXTRA EXTRA DRY
                    Registered
                    3
                    CHURCH & DWIGHT CO., INC.
                    78-446,679
                    18
                    3. EXTRA RICH FOR DRY, THIRSTY HAIR
                    Cancelled
                    3
                    NAMASTE LABORATORIES, L.L.C.
                    77-847,568
                    21
                    '''
                    Example: It means that contents related to ARRID EXTRA DRY are from page 15 to 17 and ARRID EXTRA EXTRA DRY from page 18 to 20, similarly for the following any number of entries.
                    So the end page is one page before the start page of the next trademark.

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

                url = f"{azure_llm_endpoint}/openai/deployments/{llm_model}/chat/completions?api-version={llm_api_version}"
                llm_response = requests.post(
                    url, headers=llm_headers, json=data, timeout=60
                )
                response = (
                    llm_response.json()
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                st_response = str(response)[7:-3]
                record = json.loads(st_response)

                async def extract_trademark_details_code1(document_chunk: str):
                    try:
                        client = AzureOpenAI(
                            azure_endpoint=azure_llm_endpoint,
                            api_key=llm_api_key,
                            api_version="2024-10-01-preview",
                        )

                        messages = [
                            {"role": "system", "content": "You are a data extraction specialist proficient in parsing trademark documents."},
                            {"role": "user", "content": f"""  
                                # Extract the following details from the provided trademark document with high accuracy and completeness. Ensure no relevant information is missed, even if it spans multiple pages or sections. Present the extracted details in the exact format specified below:  

                                # **Details to Extract:**  
                                # - Trademark Name (extract fully, including any special characters or formatting)  
                                # - Status (ensure to capture the most recent status)  
                                # - Serial Number (record as-is, including any leading zeros)  
                                # - International Class Number (provide as a list of integers, capturing all relevant class numbers)  
                                # - Owner (include full legal entity name and any additional information)  
                                # - Filed Date (format strictly as: MMM DD, YYYY, e.g., Jun 14, 2024)  
                                # - Registration Number (if available, extract in full)  
                                # - Goods & Services (capture the full description, ensuring each international class is followed by its corresponding goods and services; do not omit details even if they span multiple pages)  

                                # **Instructions:**  
                                # - Return results in the following format, replacing the example data with the extracted information:  
                                # - Ensure the output matches this format exactly, without any additional text, explanations, or modifications.  
                                # - Process all trademarks in the provided document chunk individually and thoroughly, even if multiple trademarks are present.  
                                # - If a section of the document is unclear or incomplete, extract the most relevant and accurate information available without assumptions.  
                                # - Capture every relevant section, ensuring no detail is overlooked, including footnotes, annexes, or supplemental documents.  

                                # **Document chunk to extract from:**  
                                # {document_chunk}  
                                # """  
                            }
                        ]

                        loop = asyncio.get_event_loop()
                        response = await loop.run_in_executor(
                            None,
                            lambda: client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=messages,
                                temperature=0
                            )
                        )
                        extracted_text = response.choices[0].message.content

                        trademark_list = []
                        for i, data in enumerate(trademark_list, start=1):
                            try:
                                trademark_name = data.get("trademark_name", "").split(',')[0].strip()
                                if "Global Filings" in trademark_name:
                                    trademark_name = trademark_name.split("Global Filings")[0].strip()
                                owner = data.get("owner", "").split(',')[0].strip()
                                status = data.get("status", "").split(',')[0].strip()
                                serial_number = data.get("serial_number", "")
                                international_class_number = data.get("international_class_numbers", [])
                                goods_services = data.get("goods_services", "")
                                page_number = data.get("page_number", "")
                                registration_number = data.get("registration_number", "No registration number presented in document")
                                design_phrase = data.get("design_phrase", "No Design phrase presented in document")

                                if not trademark_name or not owner or not status or not international_class_number:
                                    preprocessed_chunk = preprocess_text(data.get("raw_text", ""))
                                    extracted_data = extract_trademark_details_code1(preprocessed_chunk)
                                    trademark_name = extracted_data.get("trademark_name", trademark_name).split(',')[0].strip()
                                    if "Global Filings" in trademark_name:
                                        trademark_name = trademark_name.split("Global Filings")[0].strip()
                                    owner = extracted_data.get("owner", owner).split(',')[0].strip()
                                    status = extracted_data.get("status", status).split(',')[0].strip()
                                    registration_number = extracted_data.get("registration_number", registration_number).split(',')[0].strip()

                                trademark_details = TrademarkDetails(
                                    trademark_name=trademark_name,
                                    owner=owner,
                                    status=status,
                                    serial_number=serial_number,
                                    international_class_number=international_class_number,
                                    goods_services=goods_services,
                                    page_number=page_number,
                                    registration_number=registration_number,
                                    design_phrase=design_phrase
                                )                        
                                trademark_info = {
                                    "trademark_name": trademark_details.trademark_name,
                                    "owner": trademark_details.owner,
                                    "status": trademark_details.status,
                                    "serial_number": trademark_details.serial_number,
                                    "international_class_number": trademark_details.international_class_number,
                                    "goods_services": trademark_details.goods_services,
                                    "page_number": trademark_details.page_number,
                                    "registration_number":trademark_details.registration_number,
                                    "design_phrase": trademark_details.design_phrase
                                }
                                st.write(trademark_info)
                                print(trademark_info)
                                print("_____________________________________________________________________________________________________________________________")
                                trademark_list.append(trademark_info)
                            except ValidationError as e:
                                print(f"Validation error for trademark {i}: {e}")
                        
                        details = {}
                        for line in extracted_text.split("\n"):
                            if ":" in line:
                                key, value = line.split(":", 1)
                                details[key.strip().lower().replace(" ", "_")] = value.strip()
                        st.write(details)
                        return details

                    except Exception as e:
                        logging.error(f"Error extracting trademark details: {e}")
                        return {"error": f"Error extracting trademark details: {str(e)}"}
                    
                #Batch parallel execution    
                async def parallel_extraction():
                    tasks = []
                    document_chunk = ""
                    for i in range(len(record) - 1):
                        start_page = int(record[i]["page-start"])-1
                        end_page = int(record[i + 1]["page-start"])
                        document_chunk = document_chunk + "\n".join(extracted_pages2[start_page: end_page])
                        if count_tokens(document_chunk)>1000:
                            tasks.append(extract_trademark_details_code1(document_chunk))
                            document_chunk = ""
                    await asyncio.gather(*tasks)

                asyncio.run(parallel_extraction())
