import streamlit as st
import fitz  # PyMuPDF for PDF processing
from typing import List, Dict, Union
import re
from fileinput import filename
import time
import os
import streamlit as st 
import pandas as pd
import fitz  # PyMuPDF
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Union
import base64
from docx import Document  
from docx.shared import Pt
from io import BytesIO
import re, ast
from dotenv import load_dotenv
load_dotenv()  

def is_correct_format_code1(page_text: str) -> bool:
    required_fields = ["Status:", "Goods/Services:"] # , "Last Reported Owner:"
    return all(field in page_text for field in required_fields)

def is_correct_format_code2(page_text: str) -> bool:
    required_fields = ["Register", "Nice Classes", "Goods & Services"]
    return all(field in page_text for field in required_fields)

def preprocess_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\u2013\u2014]', '-', text)
    return text

def parse_international_class_numbers(class_numbers: str) -> List[int]:
    numbers = class_numbers.split(',')
    return [int(num.strip()) for num in numbers if num.strip().isdigit()]

def extract_trademark_details_code1(document_chunk: str) -> Dict[str, Union[str, List[int]]]:
    try:
        from openai import AzureOpenAI
        azure_endpoint = os.getenv("AZURE_ENDPOINT")  
        api_key = os.getenv("AZURE_API_KEY")  
          
        client = AzureOpenAI(  
            azure_endpoint=azure_endpoint,  
            api_key=api_key,   
            api_version="2024-10-01-preview",
        )  
        
        messages=[  
                    {"role": "system", "content": "You are a data extraction specialist proficient in parsing trademark documents."},  
                    {"role": "user", "content": f"""  
                        Extract the following details from the provided trademark document and present them in the exact format specified:  

                        - Trademark Name  
                        - Status  
                        - Serial Number  
                        - International Class Number (as a list of integers)  
                        - Owner  
                        - Goods & Services  
                        - Filed Date (format: MMM DD, YYYY, e.g., Jun 14, 2024)  
                        - Registration Number  

                        **Instructions:**  
                        - Return the results in the following format, replacing the example data with the extracted information:
                        - Ensure the output matches this format precisely.  
                        - Do not include any additional text or explanations.  

                        **Document to extract from:**  
                        {document_chunk}  
                        """}  
                        ]  
        
        response = client.chat.completions.create(  
                model="gpt-4o-mini",  
                messages=messages,  
                temperature=0,  
                max_tokens=4000,  
        )  
        extracted_text = response.choices[0].message.content
      
        details = {}
        for line in extracted_text.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                details[key.strip().lower().replace(" ", "_")] = value.strip()
        return details
    
    except Exception as e:
        print(f"An error occurred: {e}")

def extract_trademark_details_code2(page_text: str) -> Dict[str, Union[str, List[int]]]:
    details = {}

    trademark_name_match = re.search(r"\d+\s*/\s*\d+\s*\n\s*\n\s*([A-Za-z0-9'&!,\-. ]+)\s*\n", page_text)
    if trademark_name_match:
        details["trademark_name"] = trademark_name_match.group(1).strip()
    else:
        trademark_name_match = re.search(r"(?<=\n)([A-Za-z0-9'&!,\-. ]+)(?=\n)", page_text)
        details["trademark_name"] = trademark_name_match.group(1).strip() if trademark_name_match else ""

    status_match = re.search(r'Status\s*(?:\n|:\s*)([A-Za-z]+)', page_text, re.IGNORECASE)
    details["status"] = status_match.group(1).strip() if status_match else ""

    owner_match = re.search(r'Holder\s*(?:\n|:\s*)(.*)', page_text, re.IGNORECASE)
    if owner_match:
        details["owner"] = owner_match.group(1).strip()
    else:
        owner_match = re.search(r'Owner\s*(?:\n|:\s*)(.*)', page_text, re.IGNORECASE)
        details["owner"] = owner_match.group(1).strip() if owner_match else ""
        
        

    nice_classes_match = re.search(r'Nice Classes\s*[\s:]*\n((?:\d+(?:,\s*\d+)*)\b)', page_text, re.IGNORECASE)
    if nice_classes_match:
        nice_classes_text = nice_classes_match.group(1)
        nice_classes = [int(cls.strip()) for cls in nice_classes_text.split(",")]
        details["international_class_number"] = nice_classes
    else:
        details["international_class_number"] = []
        


    serial_number_match = re.search(r'Application#\s*(.*)', page_text, re.IGNORECASE)
    details["serial_number"] = serial_number_match.group(1).strip() if serial_number_match else ""

    goods_services_match = re.search(r'Goods & Services\s*(.*?)(?=\s*G&S translation|$)', page_text, re.IGNORECASE | re.DOTALL)
    details["goods_services"] = goods_services_match.group(1).strip() if goods_services_match else ""
    
    registration_number_match = re.search(r'Registration#\s*(.*)', page_text, re.IGNORECASE)
    details["registration_number"] = registration_number_match.group(1).strip() if registration_number_match else ""
    
    # Description
    design_phrase = re.search(r'Description\s*(.*?)(?=\s*Applicant|Owner|Holder|$)', page_text, re.IGNORECASE | re.DOTALL)
    details["design_phrase"] = design_phrase.group(1).strip() if design_phrase else "No Design phrase presented in document"
    

    return details

def extract_international_class_numbers_and_goods_services(document: str, start_page: int, pdf_document: fitz.Document) -> Dict[str, Union[List[int], str]]:
    """ Extract the International Class Numbers and Goods/Services from the document over a range of pages """
    class_numbers = []
    goods_services = []
    combined_text = ""

    for i in range(start_page, min(start_page + 6, pdf_document.page_count)):
        page = pdf_document.load_page(i)
        page_text = page.get_text()
        combined_text += page_text
        if "Last Reported Owner:" in page_text:
            break

    pattern = r'International Class (\d+): (.*?)(?=\nInternational Class \d+:|\n[A-Z][a-z]+:|\nLast Reported Owner:|Disclaimers:|\Z)'
    matches = re.findall(pattern, combined_text, re.DOTALL)
    for match in matches:
        class_number = int(match[0])
        class_numbers.append(class_number)
        goods_services.append(f"Class {class_number}: {match[1].strip()}")

    if "sexual" in goods_services or "sex" in goods_services:
        goods_services = replace_disallowed_words(goods_services)

    return {
        "international_class_numbers": class_numbers,
        "goods_services": "\n".join(goods_services)
    }

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
    

def extract_registration_number(document: str) -> str:
    """ Extract the registration number from the Chronology section """
    match = re.search(r'Chronology:.*?Registration Number:\s*([\d,]+)', document, re.DOTALL)
    if match:
        return match.group(1).strip()
    return "No registration number presented in document"

def extract_design_phrase(document: str, start_page: int, pdf_document: fitz.Document) -> Dict[str, Union[List[int], str]]:
    """ Extract the design phrase from the document """
    combined_texts = ""
    for i in range(start_page, min(start_page + 8, pdf_document.page_count)):
        page = pdf_document.load_page(i)
        page_text = page.get_text()
        combined_texts += page_text
        if "Filing Correspondent:" in page_text:
            break

def parse_trademark_details(document_path: str) -> List[Dict[str, Union[str, List[int]]]]:
    with fitz.open(document_path) as pdf_document:
        trademark_list = []
        for page_num in range(pdf_document.page_count):
            page = pdf_document.load_page(page_num)
            page_text = page.get_text()
            
            if is_correct_format_code1(page_text):
                preprocessed_chunk = preprocess_text(page_text)
                extracted_data = extract_trademark_details_code1(preprocessed_chunk)
                additional_data = extract_international_class_numbers_and_goods_services(page_text, page_num, pdf_document)
                registration_number = extract_registration_number(page_text)
                design_phrase = extract_design_phrase(page_text, page_num, pdf_document)
                
                if extracted_data:
                    extracted_data["page_number"] = page_num + 1
                    extracted_data.update(additional_data)
                    extracted_data["design_phrase"] = design_phrase
                    trademark_list.append(extracted_data)
                    extracted_data["registration_number"] = registration_number
                    
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

                        # If crucial fields are missing, attempt to re-extract the values
                        if not trademark_name or not owner or not status or not international_class_number:
                            preprocessed_chunk = preprocess_text(data.get("raw_text", ""))
                            extracted_data = extract_trademark_details_code1(preprocessed_chunk)
                            trademark_name = extracted_data.get("trademark_name", trademark_name).split(',')[0].strip()
                            if "Global Filings" in trademark_name:
                                trademark_name = trademark_name.split("Global Filings")[0].strip()
                            owner = extracted_data.get("owner", owner).split(',')[0].strip()
                            status = extracted_data.get("status", status).split(',')[0].strip()
                            international_class_number = parse_international_class_numbers(extracted_data.get("international_class_number", "")) or international_class_number
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
                        print(trademark_info)
                        print("_____________________________________________________________________________________________________________________________")
                        trademark_list.append(trademark_info)
                    except ValidationError as e:
                        print(f"Validation error for trademark {i}: {e}")
                                    
            else :
                if not is_correct_format_code2(page_text):
                    continue

                extracted_data = extract_trademark_details_code2(page_text)
                if extracted_data:
                    extracted_data["page_number"] = page_num + 1
                    trademark_list.append(extracted_data)

                trademark_list = []
                for i, data in enumerate(trademark_list, start=1):
                    try:
                        trademark_details = TrademarkDetails(
                            trademark_name=data.get("trademark_name", ""),
                            owner=data.get("owner", ""),
                            status=data.get("status", ""),
                            serial_number=data.get("serial_number", ""),
                            international_class_number=data.get("international_class_number", []),
                            goods_services=data.get("goods_services", ""),
                            page_number=data.get("page_number", 0),
                            registration_number=data.get("registration_number", ""),
                            design_phrase=data.get("design_phrase", "")
                        )
                        if (trademark_details.trademark_name != "" and trademark_details.owner != "" and trademark_details.status != "" and trademark_details.goods_services != ""):
                                trademark_info = {
                                    "trademark_name": trademark_details.trademark_name,
                                    "owner": trademark_details.owner,
                                    "status": trademark_details.status,
                                    "serial_number": trademark_details.serial_number,
                                    "international_class_number": trademark_details.international_class_number,
                                    "goods_services": trademark_details.goods_services,
                                    "page_number": trademark_details.page_number,
                                    "registration_number":trademark_details.registration_number,
                                    "design_phrase":trademark_details.design_phrase,
                                }
                                
                                trademark_list.append(trademark_info)
                    except ValidationError as e:
                        print(f"Validation error for trademark {i}: {e}")

        return trademark_list


def parse_trademark_details_from_stream(pdf_document) -> List[Dict[str, Union[str, List[int]]]]:
    trademark_list = []
    return "Hello"
    for page_num in range(pdf_document.page_count):
        st.write("hi")
        page = pdf_document.load_page(page_num)
        page_text = page.get_text()
        st.write(page_text)
        
    #     if is_correct_format_code1(page_text):
    #         preprocessed_chunk = preprocess_text(page_text)
    #         extracted_data = extract_trademark_details_code1(preprocessed_chunk)
    #         additional_data = extract_international_class_numbers_and_goods_services(page_text, page_num, pdf_document)
    #         registration_number = extract_registration_number(page_text)
    #         design_phrase = extract_design_phrase(page_text, page_num, pdf_document)
            
    #         if extracted_data:
    #             extracted_data["page_number"] = page_num + 1
    #             extracted_data.update(additional_data)
    #             extracted_data["design_phrase"] = design_phrase
    #             trademark_list.append(extracted_data)
    #             extracted_data["registration_number"] = registration_number
                
    #         trademark_list = []
    #         for i, data in enumerate(trademark_list, start=1):
    #             try:
    #                 trademark_name = data.get("trademark_name", "").split(',')[0].strip()
    #                 if "Global Filings" in trademark_name:
    #                     trademark_name = trademark_name.split("Global Filings")[0].strip()
    #                 owner = data.get("owner", "").split(',')[0].strip()
    #                 status = data.get("status", "").split(',')[0].strip()
    #                 serial_number = data.get("serial_number", "")
    #                 international_class_number = data.get("international_class_numbers", [])
    #                 goods_services = data.get("goods_services", "")
    #                 page_number = data.get("page_number", "")
    #                 registration_number = data.get("registration_number", "No registration number presented in document")
    #                 design_phrase = data.get("design_phrase", "No Design phrase presented in document")

    #                 # If crucial fields are missing, attempt to re-extract the values
    #                 if not trademark_name or not owner or not status or not international_class_number:
    #                     preprocessed_chunk = preprocess_text(data.get("raw_text", ""))
    #                     extracted_data = extract_trademark_details_code1(preprocessed_chunk)
    #                     trademark_name = extracted_data.get("trademark_name", trademark_name).split(',')[0].strip()
    #                     if "Global Filings" in trademark_name:
    #                         trademark_name = trademark_name.split("Global Filings")[0].strip()
    #                     owner = extracted_data.get("owner", owner).split(',')[0].strip()
    #                     status = extracted_data.get("status", status).split(',')[0].strip()
    #                     international_class_number = parse_international_class_numbers(extracted_data.get("international_class_number", "")) or international_class_number
    #                     registration_number = extracted_data.get("registration_number", registration_number).split(',')[0].strip()

    #                 trademark_details = TrademarkDetails(
    #                     trademark_name=trademark_name,
    #                     owner=owner,
    #                     status=status,
    #                     serial_number=serial_number,
    #                     international_class_number=international_class_number,
    #                     goods_services=goods_services,
    #                     page_number=page_number,
    #                     registration_number=registration_number,
    #                     design_phrase=design_phrase
    #                 )                        
    #                 trademark_info = {
    #                     "trademark_name": trademark_details.trademark_name,
    #                     "owner": trademark_details.owner,
    #                     "status": trademark_details.status,
    #                     "serial_number": trademark_details.serial_number,
    #                     "international_class_number": trademark_details.international_class_number,
    #                     "goods_services": trademark_details.goods_services,
    #                     "page_number": trademark_details.page_number,
    #                     "registration_number":trademark_details.registration_number,
    #                     "design_phrase": trademark_details.design_phrase
    #                 }
    #                 st.write(trademark_info)
    #                 st.markdown("---")
    #                 trademark_list.append(trademark_info)
    #             except ValidationError as e:
    #                 print(f"Validation error for trademark {i}: {e}")
        
    # return trademark_list

# Streamlit app
st.title("Trademark Details Extractor")

if 'document' not in st.session_state:
    st.session_state['document'] = None

uploaded_file = st.file_uploader("Upload Trademark PDF", type=["pdf"])

if uploaded_file:
    st.session_state['document'] = uploaded_file

if st.session_state['document']:
    # Read PDF directly from stream
    document_bytes = st.session_state['document'].getvalue()
    pdf_document = fitz.open(stream=document_bytes, filetype="pdf")
    
    # Extract text from the PDF
    document_text = "".join([page.get_text() for page in pdf_document])
    
    # Process and extract trademark details
    extracted_data = parse_trademark_details_from_stream(pdf_document)
    st.write(extracted_data)
    # # Display extracted data
    # if extracted_data:
    #     st.write("## Extracted Trademark Details")
    #     for data in extracted_data:
    #         st.write("### Trademark Information")
    #         st.write(f"**Trademark Name:** {data.get('trademark_name', 'N/A')}")
    #         st.write(f"**Owner:** {data.get('owner', 'N/A')}")
    #         st.write(f"**Status:** {data.get('status', 'N/A')}")
    #         st.write(f"**Serial Number:** {data.get('serial_number', 'N/A')}")
    #         st.write(f"**International Class Numbers:** {', '.join(map(str, data.get('international_class_number', [])))}")
    #         st.write(f"**Goods & Services:** {data.get('goods_services', 'N/A')}")
    #         st.write(f"**Page Number:** {data.get('page_number', 'N/A')}")
    #         st.write(f"**Registration Number:** {data.get('registration_number', 'N/A')}")
    #         st.write(f"**Design Phrase:** {data.get('design_phrase', 'N/A')}")
    #         st.write("---")
    # else:
    #     st.error("No trademark details could be extracted from the document.")
