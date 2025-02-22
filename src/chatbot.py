import os
import time
import google.generativeai as genai
from dotenv import load_dotenv
import pandas as pd
import utils
import data_loader
import re

load_dotenv()

def upload_and_index_file(path, mime_type=None):
    """Uploads a file to Gemini and returns its URI and name."""
    file = genai.upload_file(path, mime_type=mime_type)
    print(f"Uploaded file '{file.display_name}' as: {file.uri}")
    return {"uri": file.uri, "name": file.name, "display_name": file.display_name}

def wait_for_files_active(files):
    """Waits for files to be processed."""
    print("Waiting for file processing...")
    for file_data in files:
        file = genai.get_file(file_data['name'])
        while file.state.name == "PROCESSING":
            print(".", end="", flush=True)
            time.sleep(10)
            file = genai.get_file(file.name)
        if file.state.name != "ACTIVE":
            raise Exception(f"File {file.name} failed to process")
    print("...all files ready")
    print()

def clear_chat_history(model):
    """Clears chat history by starting a new chat session."""
    try:
        new_chat_session = model.start_chat()
        return new_chat_session
    except Exception as e:
        print(f"An error occurred while starting a new chat session: {e}")
        return None

def analyze_query_type(query):
    """
    Analyze if the query is asking for code or explanation.
    Returns:
    - 'code': If the query is asking for specific code/transformation
    - 'explanation': If the query is asking for conceptual understanding
    """
    code_indicators = [
        'create', 'generate', 'write', 'code', 'query', 'sql', 'dbt', 
        'transform', 'model', 'script', 'implementation', 'mapping'
    ]
    
    explanation_indicators = [
        'explain', 'what', 'why', 'how', 'describe', 'help me understand',
        'tell me about', 'difference between', 'compare', 'analysis'
    ]
    
    query = query.lower()
    code_score = sum(1 for word in code_indicators if word in query)
    explanation_score = sum(1 for word in explanation_indicators if word in query)
    
    # If it contains SQL-like keywords or specific technical terms, lean towards code
    if any(term in query for term in ['select', 'from', 'where', 'join', 'group by']):
        return 'code'
        
    return 'code' if code_score > explanation_score else 'explanation'

def find_relevant_edc_view(query, edc_metadata):
    """
    Find the most relevant EDC view based on the query context.
    """
    if not isinstance(edc_metadata, pd.DataFrame):
        return None
        
    # Extract unique viewnames
    viewnames = edc_metadata['viewname'].unique()
    
    # Common SDTM domain patterns
    domain_patterns = {
        'DM': ['demographic', 'subject', 'patient'],
        'AE': ['adverse event', 'ae ', 'safety'],
        'CM': ['medication', 'treatment', 'drug'],
        'VS': ['vital', 'signs'],
        'LB': ['lab', 'laboratory'],
        'TU': ['tumor', 'lesion', 'cancer'],
        'RS': ['response', 'recist'],
        'EX': ['exposure', 'administration', 'dose']
    }
    
    # Find matching domain from query
    matched_domain = None
    query_lower = query.lower()
    
    for domain, patterns in domain_patterns.items():
        if any(pattern in query_lower for pattern in patterns):
            matched_domain = domain
            break
    
    if matched_domain:
        # Look for views containing the matched domain
        domain_views = [v for v in viewnames if matched_domain.lower() in v.lower()]
        if domain_views:
            return domain_views[0]
    
    # Default return the first view if no match found
    return viewnames[0] if len(viewnames) > 0 else None

def get_relevant_variables(viewname, edc_metadata):
    """
    Get relevant variables and their metadata for a specific view.
    """
    if not isinstance(edc_metadata, pd.DataFrame):
        return []
        
    view_vars = edc_metadata[edc_metadata['viewname'] == viewname]
    return view_vars.to_dict('records')

def main():
    model_name = "gemini-2.0-flash"

    try:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    except KeyError:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    generation_config = {
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 30,
        "max_output_tokens": 2048,  # Increased for more detailed dbt responses
    }

    system_instruction = """You are a specialized data transformation expert focused on Phase 1 oncology clinical trials. 
    Your expertise includes:
    - Converting EDC metadata into dbt models for BigQuery
    - CDISC SDTM mappings specific to oncology domains (particularly TU, RS, EX, etc.)
    - Best practices for modeling clinical data in BigQuery
    - Implementing RECIST criteria and tumor response calculations
    - Handling common Phase 1 oncology concepts like DLT periods, cohorts, and dose escalation
    
    Your primary goal is to help create dbt transformations that:
    1. Map EDC data to SDTM standards
    2. Implement oncology-specific derived calculations
    3. Follow BigQuery best practices
    4. Create reusable macros for common oncology data patterns
    """

    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config=generation_config,
        system_instruction=system_instruction,
    )

    data_directory = "data/"
    edc_metadata_files = utils.find_files(data_directory, "edc*.csv")
    sdtm_metadata_files = utils.find_files(data_directory, "sdtm*.xml")

    # Combine all data files for processing
    all_data_files = edc_metadata_files + sdtm_metadata_files

    try:
        files = []
        for file in edc_metadata_files:
            files.append(upload_and_index_file(file, mime_type="text/csv"))
        for file in sdtm_metadata_files:
            files.append(upload_and_index_file(file, mime_type="text/xml"))

    except Exception as e:
        print(f"Error during file upload: {e}")
        return

    try:
        wait_for_files_active(files)
    except Exception as e:
        print(f"Error waiting for file processing: {e}")
        return

    chat = model.start_chat()

    while True:
        query = input("Ask about dbt transformations or SDTM mappings for your oncology trial (or type 'exit', or 'clear'): ")

        if "exit" in query.lower():
            break

        if "clear" in query.lower():
            chat = clear_chat_history(model)
            if chat:
                print("Chat history cleared. Starting a new session.")
            else:
                print("An error occurred. Please check the logs.")
            continue
        
        try:
            # Load the EDC metadata
            edc_metadata = pd.read_csv(next(f for f in all_data_files if f.endswith('.csv')))
            
            # Analyze query type
            query_type = analyze_query_type(query)
            
            # Find relevant EDC view and variables
            relevant_view = find_relevant_edc_view(query, edc_metadata)
            relevant_vars = get_relevant_variables(relevant_view, edc_metadata) if relevant_view else []
            
            print(f"Query type detected: {'Code Generation' if query_type == 'code' else 'Explanation'}")
            if relevant_view:
                print(f"Using EDC view: {relevant_view}")
            
            # Construct appropriate prompt based on query type
            if query_type == 'code':
                prompt_parts = [
                    f"{query}. Create a dbt transformation in SQL that implements this for BigQuery, following CDISC SDTM standards for oncology trials.",
                    "Available EDC view structure:",
                    f"View: {relevant_view}",
                    f"Variables: {json.dumps(relevant_vars, indent=2)}",
                    "Please generate SQL that specifically uses these source variables for the transformation."
                ]
            else:
                prompt_parts = [
                    f"{query}",
                    "Please provide a clear explanation based on:",
                    f"EDC Structure: {relevant_view}",
                    "Focus on clinical data standards and oncology-specific considerations."
                ]

            print("\nGenerating response...")
            response = chat.send_message(prompt_parts)
            
            # Format the response based on query type
            if query_type == 'code':
                print("\n=== DBT Transformation ===")
                print(response.text)
                print("\nNote: This transformation is based on your specific EDC structure and SDTM requirements.")
            else:
                print("\n=== Explanation ===")
                print(response.text)

        except Exception as e:
            print(f"An error occurred while generating the response: {e}")
            print(f"Error details: {str(e)}")

if __name__ == "__main__":
    main()