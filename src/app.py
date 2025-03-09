from flask import (
    Flask,
    render_template,
    request,
    Response,
    stream_with_context,
    jsonify,
)
from werkzeug.utils import secure_filename
from PIL import Image
import io
from dotenv import load_dotenv
import os
import google.generativeai as genai
import pandas as pd
import glob
import json
import time
import traceback
import re
# Removed heavy NLP dependencies for better performance
from xml.etree import ElementTree
import utils

# Load environment variables from .env file
load_dotenv()

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "csv", "xml", "xpt", "sas7bdat"}
UPLOAD_FOLDER = "uploads"

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# WARNING: Do not share code with you API key hard coded in it.
# Get your Gemini API key from: https://aistudio.google.com/app/apikey
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

# Load CDISC Thesaurus from JSON file
try:
    with open('cdisc_thesaurus.json', 'r') as f:
        cdisc_thesaurus = json.load(f)
    code_indicators = cdisc_thesaurus.get("code_indicators", [])
    explanation_indicators = cdisc_thesaurus.get("explanation_indicators", [])
    system_instruction = cdisc_thesaurus.get("system_instruction", "")
    code_example = cdisc_thesaurus.get("code_example", "")
    code_prompt_template = cdisc_thesaurus.get("code_prompt_template", "")
    explanation_prompt_template = cdisc_thesaurus.get("explanation_prompt_template", "")
except FileNotFoundError:
    # Fallback if thesaurus file isn't found
    code_indicators = [
        'create', 'generate', 'write', 'code', 'query', 'sql', 'dbt', 
        'transform', 'model', 'script', 'implementation', 'mapping'
    ]
    explanation_indicators = [
        'explain', 'what', 'why', 'how', 'describe', 'help me understand',
        'tell me about', 'difference between', 'compare', 'analysis'
    ]
    system_instruction = """You are a specialized clinical data standards expert for oncology clinical trials.
    
    Your expertise includes both CDISC SDTM and ADaM standards, with focus on these domains:
    - DM/ADSL: Demographics and subject-level analysis data
    - AE/ADAE: Adverse events data
    - LB/ADLB: Laboratory test results
    - EX/ADEX: Exposure and dosing data
    - CM/ADCM: Concomitant medications 
    - MH/ADMH: Medical history information
    - DH/ADDH: Disease history details
    - RS/ADRS: Response assessment data
    - TU/ADTU: Tumor findings and measurements
    - VS/ADVS: Vital signs measurements
    
    You also excel at ADaM-specific datasets:
    - ADTTE: Time-to-event analysis
    - ADTR: Tumor response analysis
    
    Your primary goal is to help create data transformations that:
    1. Map source data to SDTM and ADaM standards
    2. Implement oncology-specific derived calculations (esp. RECIST)
    3. Follow database best practices (BigQuery, Snowflake, etc.)
    4. Create reusable transformation patterns for clinical data
    """
    code_example = ""
    code_prompt_template = "{query}. Create a dbt transformation in SQL that implements this for BigQuery, following CDISC SDTM standards for oncology trials.\nAvailable EDC view structure:\nView: {relevant_view}.\nVariables: {relevant_vars}.\nPlease generate SQL that specifically uses these source variables for the transformation."
    explanation_prompt_template = "{query}. Please provide a clear explanation based on:\nEDC Structure: {relevant_view}.\nFocus on clinical data standards and oncology-specific considerations."

# Add code example to system instruction if available
if code_example:
    system_instruction += f"""
    Here is an example of what a good dbt model query looks like:
        {code_example}
    Please use that as a guide.
    """

# Create model with specific configuration for clinical data
try:
    model = genai.GenerativeModel(
        'gemini-1.5-flash',  # Try more reliable model
        generation_config={
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 30,
            "max_output_tokens": 1024,  # Shorter responses for faster generation
        },
        system_instruction=system_instruction
    )
    print("Successfully created Gemini model")
except Exception as e:
    print(f"ERROR creating model: {e}")
    traceback.print_exc()
    # Fallback to a different model if the specified one isn't available
    try:
        model = genai.GenerativeModel(
            'gemini-pro',  # Fallback model
            generation_config={
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 30,
                "max_output_tokens": 1024,
            },
            system_instruction=system_instruction
        )
        print("Using fallback model gemini-pro")
    except Exception as e2:
        print(f"ERROR creating fallback model: {e2}")
        traceback.print_exc()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

chat_session = model.start_chat(history=[])
next_message = ""
next_image = ""
uploaded_files = []
edc_metadata = None
sdtm_metadata = {}
chat_history = []

# Don't load heavy NLP models for better performance
nlp_models_loaded = False
print("Using lightweight keyword matching for better performance")

def allowed_file(filename):
    """Returns if a filename is supported via its extension"""
    _, ext = os.path.splitext(filename)
    return ext.lstrip('.').lower() in ALLOWED_EXTENSIONS

def upload_and_index_file(file_path, mime_type=None):
    """Uploads a file to Gemini and returns its URI and name."""
    try:
        file = genai.upload_file(file_path, mime_type=mime_type)
        print(f"Uploaded file '{file.display_name}' as: {file.uri}")
        return {"uri": file.uri, "name": file.name, "display_name": file.display_name}
    except Exception as e:
        print(f"Error uploading file: {e}")
        traceback.print_exc()
        return None

def wait_for_files_active(files):
    """Waits for files to be processed."""
    print("Waiting for file processing...")
    for file_data in files:
        file = genai.get_file(file_data['name'])
        while file.state.name == "PROCESSING":
            print(".", end="", flush=True)
            time.sleep(2)
            file = genai.get_file(file.name)
        if file.state.name != "ACTIVE":
            raise Exception(f"File {file.name} failed to process: State is {file.state.name}")
    print("All files processed successfully")

def analyze_query_type(query):
    """
    Simplified query type analysis using keyword matching for better performance.
    """
    query = query.lower()
    
    # SQL-specific patterns strongly suggest code
    if any(term in query for term in ['select', 'from', 'where', 'join', 'group by']):
        return 'code'
    
    # Check for code indicators
    code_score = sum(1 for word in code_indicators if word in query.split())
    explanation_score = sum(1 for word in explanation_indicators if word in query.split())
    
    # Some extra heuristics for better accuracy
    if any(phrase in query for phrase in ['create a', 'generate a', 'write a', 'build a']):
        code_score += 2
    
    if any(phrase in query for phrase in ['what is', 'how does', 'explain', 'why is']):
        explanation_score += 2
    
    return 'code' if code_score >= explanation_score else 'explanation'

def find_relevant_edc_view(query, edc_metadata):
    """
    Simplified function to find the most relevant EDC view based on keyword matching.
    """
    if not isinstance(edc_metadata, pd.DataFrame) or edc_metadata is None:
        return None
        
    # Extract unique viewnames
    viewnames = edc_metadata['viewname'].unique()
    
    # Common SDTM domain patterns
    domain_patterns = {
        'DM': ['demographic', 'subject', 'patient', 'dm'],
        'AE': ['adverse event', 'ae', 'safety', 'adverse'],
        'CM': ['medication', 'treatment', 'drug', 'cm', 'concomitant'],
        'VS': ['vital', 'signs', 'vs'],
        'LB': ['lab', 'laboratory', 'lb'],
        'TU': ['tumor', 'lesion', 'cancer', 'tu'],
        'RS': ['response', 'recist', 'rs'],
        'EX': ['exposure', 'administration', 'dose', 'ex', 'drug']
    }
    
    # Updated domain patterns with focus domains and ADaM
    domain_patterns = {
        'DM': ['demographic', 'subject', 'patient', 'dm', 'adsl'],
        'AE': ['adverse event', 'ae', 'safety', 'adverse', 'adae'],
        'LB': ['lab', 'laboratory', 'lb', 'adlb'],
        'EX': ['exposure', 'administration', 'dose', 'ex', 'adex'],
        'CM': ['medication', 'treatment', 'drug', 'cm', 'concomitant', 'adcm'],
        'MH': ['medical history', 'mh', 'admh'],
        'DH': ['disease history', 'dh', 'addh'],
        'RS': ['response', 'recist', 'rs', 'adrs'],
        'TU': ['tumor', 'lesion', 'cancer', 'tu', 'adtu'],
        'VS': ['vital', 'signs', 'vs', 'advs'],
        'ADSL': ['subject level', 'adsl', 'baseline'],
        'ADTTE': ['time to event', 'adtte', 'survival'],
        'ADTR': ['tumor response', 'adtr', 'best response'],
    }
    
    # Find matching domain from query
    matched_domain = None
    match_strength = 0
    query_words = query.lower().split()
    
    # First check exact matches to prioritize them
    for domain, patterns in domain_patterns.items():
        if domain.lower() in query.lower():
            return domain  # Immediate return for exact domain match
    
    # Then do pattern matching
    for domain, patterns in domain_patterns.items():
        # Count how many patterns match in the query
        current_strength = sum(1 for pattern in patterns if pattern in query.lower())
        # Check for exact words
        current_strength += sum(3 for pattern in patterns if pattern in query_words)
        
        if current_strength > match_strength:
            match_strength = current_strength
            matched_domain = domain
    
    if matched_domain and match_strength > 0:
        # Look for views containing the matched domain
        domain_views = [v for v in viewnames if matched_domain.lower() in v.lower()]
        if domain_views:
            print(f"Matched domain {matched_domain} to view {domain_views[0]}")
            return domain_views[0]
    
    # Default return the first view if no match found
    return viewnames[0] if len(viewnames) > 0 else None

def get_relevant_variables(viewname, edc_metadata):
    """
    Get relevant variables and their metadata for a specific view.
    """
    if not isinstance(edc_metadata, pd.DataFrame) or edc_metadata is None:
        return []
        
    view_vars = edc_metadata[edc_metadata['viewname'] == viewname]
    return view_vars.to_dict('records')

def parse_sdtm_xml(xml_path):
    """Parses the SDTM XML file and organizes data for access."""
    try:
        tree = ElementTree.parse(xml_path)
        root = tree.getroot()
        sdtm_metadata = {}

        for cls in root.findall('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}class'):
            class_name = cls.find('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}name').text
            sdtm_metadata[class_name] = {}
            for var in cls.findall('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}classVariable'):
                var_name = var.find('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}name').text
                var_label = var.find('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}label').text
                var_def = var.find('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}definition').text if var.find(
                    './/{http://www.cdisc.org/ns/mdr/sdtm/v2.1}definition') is not None else ""
                var_role = var.find('.//{http://www.cdisc.org/ns/mdr/sdtm/v2.1}role').text if var.find(
                    './/{http://www.cdisc.org/ns/mdr/sdtm/v2.1}role') is not None else ""
                sdtm_metadata[class_name][var_name] = {
                    'label': var_label,
                    'definition': var_def,
                    'role': var_role
                }

        return sdtm_metadata
    except Exception as e:
        print(f"Error parsing XML file {xml_path}: {e}")
        traceback.print_exc()
        return {}

def get_sdtm_metadata(sdtm_metadata, query):
    """Retrieves relevant SDTM metadata based on user query."""
    relevant_metadata = ""

    query = query.lower()

    for class_name, variables in sdtm_metadata.items():
        for var_name, metadata in variables.items():
            if var_name.lower() in query or metadata['label'].lower() in query or metadata['definition'].lower() in query:
                relevant_metadata += f"\n   Variable: {var_name}\n       Label: {metadata['label']}\n       Definition: {metadata['definition']}\n       Role: {metadata['role']}\n"
    return relevant_metadata

def initialize_data_files():
    """Load initial EDC and SDTM data files"""
    global edc_metadata, uploaded_files, sdtm_metadata
    
    data_directory = "data/"
    os.makedirs(data_directory, exist_ok=True)
    
    edc_metadata_files = glob.glob(os.path.join(data_directory, "edc*.csv"))
    sdtm_metadata_files = glob.glob(os.path.join(data_directory, "sdtm*.xml"))
    
    if edc_metadata_files:
        try:
            edc_metadata = pd.read_csv(edc_metadata_files[0])
            print(f"Loaded EDC metadata from {edc_metadata_files[0]}")
        except Exception as e:
            print(f"Error loading EDC metadata: {e}")
            traceback.print_exc()
    
    # Load SDTM metadata from XML if available
    if sdtm_metadata_files:
        try:
            sdtm_metadata = parse_sdtm_xml(sdtm_metadata_files[0])
            print(f"Loaded SDTM metadata from {sdtm_metadata_files[0]}")
        except Exception as e:
            print(f"Error loading SDTM metadata: {e}")
            traceback.print_exc()
    
    # Upload files to Gemini
    files = []
    try:
        for file in edc_metadata_files:
            file_obj = upload_and_index_file(file, mime_type="text/csv")
            if file_obj:
                files.append(file_obj)
                uploaded_files.append({"name": os.path.basename(file), "type": "EDC Metadata"})
                
        for file in sdtm_metadata_files:
            file_obj = upload_and_index_file(file, mime_type="text/xml")
            if file_obj:
                files.append(file_obj)
                uploaded_files.append({"name": os.path.basename(file), "type": "SDTM Metadata"})
                
        if files:
            wait_for_files_active(files)
            print(f"Successfully initialized {len(files)} data files")
    except Exception as e:
        print(f"Error initializing data files: {e}")
        traceback.print_exc()

# Initialize data files on startup
initialize_data_files()

@app.route("/upload", methods=["POST"])
def upload_file():
    """Takes in a file, checks if it is valid, and saves it"""
    global next_image
    global edc_metadata
    global uploaded_files
    global sdtm_metadata

    if "file" not in request.files:
        return jsonify(success=False, message="No file part")

    file = request.files["file"]

    if file.filename == "":
        return jsonify(success=False, message="No selected file")
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Handle different file types
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext in ['.jpg', '.jpeg', '.png']:
            # Image handling for multimodal input
            file_stream = io.BytesIO(open(file_path, 'rb').read())
            file_stream.seek(0)
            next_image = Image.open(file_stream)
            file_type = "Image"
        elif file_ext == '.csv':
            # Load CSV as EDC metadata
            try:
                edc_metadata = pd.read_csv(file_path)
                file_obj = upload_and_index_file(file_path, mime_type="text/csv")
                file_type = "EDC Metadata"
            except Exception as e:
                return jsonify(success=False, message=f"Error loading CSV file: {str(e)}")
        elif file_ext == '.xml':
            # Handle XML files - parse if it's SDTM metadata
            try:
                if "sdtm" in filename.lower():
                    sdtm_metadata = parse_sdtm_xml(file_path)
                file_obj = upload_and_index_file(file_path, mime_type="text/xml")
                file_type = "SDTM Metadata" if "sdtm" in filename.lower() else "XML Document"
            except Exception as e:
                return jsonify(success=False, message=f"Error processing XML file: {str(e)}")
        elif file_ext in ['.xpt', '.sas7bdat']:
            # Handle other clinical data files
            file_obj = upload_and_index_file(file_path)
            file_type = "Clinical Data"
        else:
            file_obj = upload_and_index_file(file_path)
            file_type = "Document"
            
        uploaded_files.append({"name": filename, "type": file_type})
        
        return jsonify(
            success=True,
            message=f"{file_type} uploaded successfully and added to the conversation",
            filename=filename,
        )
    return jsonify(success=False, message="File type not allowed")

@app.route("/get_files", methods=["GET"])
def get_files():
    """Returns the list of uploaded files"""
    return jsonify(success=True, assistant_files=uploaded_files)

@app.route("/clear_chat", methods=["POST"])
def clear_chat():
    """Clears the chat history and starts a new session"""
    global chat_session, chat_history
    try:
        chat_session = model.start_chat(history=[])
        chat_history = []
        return jsonify(success=True, message="Chat history cleared")
    except Exception as e:
        return jsonify(success=False, message=f"Error clearing chat: {str(e)}")

@app.route("/", methods=["GET"])
def index():
    """Renders the main homepage for the app"""
    return render_template(
        "index.html", 
        chat_history=chat_session.history,
        files=uploaded_files
    )

@app.route("/chat", methods=["POST"])
def chat():
    """
    Super simplified chat endpoint that just returns static responses
    """
    try:
        print("DEBUG: Chat endpoint called")
        print("DEBUG: Request data:", request.data)
        print("DEBUG: Request headers:", dict(request.headers))
        
        if not request.is_json:
            print("DEBUG: Request is not JSON")
            return jsonify(success=False, response="Invalid request format - not JSON")
        
        message = request.json.get("message", "")
        print(f"DEBUG: Received message: '{message}'")
        
        if not message:
            return jsonify(success=False, response="Empty message")
            
        # Add to chat history for tracking
        chat_history.append({"user": message, "bot": ""})
        
        # For debugging, first try a static response to verify UI display
        if "test" in message.lower():
            test_response = "This is a test response to verify the UI is working properly."
            chat_history[-1]["bot"] = test_response
            print("DEBUG: Returning test response")
            return jsonify(success=True, response=test_response)
            
        # Normal processing with the model
        try:
            print("DEBUG: Calling model with message...")
            response = chat_session.send_message(message)
            response_text = response.text
            
            # Store in history
            chat_history[-1]["bot"] = response_text
            
            print(f"DEBUG: Generated response: '{response_text[:50]}...'")
            print(f"DEBUG: Response length: {len(response_text)} characters")
            
            # Return the full text response with debug info
            print("DEBUG: Returning successful response")
            return jsonify(
                success=True, 
                response=response_text,
                debug_info={
                    "response_length": len(response_text),
                    "has_code_blocks": "```" in response_text
                }
            )
                
        except Exception as inner_e:
            error_msg = f"Model error: {str(inner_e)}"
            print(f"DEBUG: {error_msg}")
            traceback.print_exc()
            chat_history[-1]["bot"] = error_msg
            return jsonify(success=False, response=error_msg)
            
    except Exception as e:
        error_message = f"Server error: {str(e)}"
        print(f"DEBUG: Overall endpoint error: {error_message}")
        traceback.print_exc()
        return jsonify(success=False, response=error_message)

@app.route("/stream", methods=["GET"])
def stream():
    """
    Alternate approach: non-streaming direct response
    """
    global next_message
    global next_image
    global chat_history
    
    # Debug output
    print(f"DEBUG: Stream request received for message: '{next_message}'")
    
    # Add message to history if not empty
    if next_message:
        chat_history.append({"user": next_message, "bot": ""})
    
    # Direct approach without streaming
    def generate():
        # Send header to establish connection
        yield f"data: Connecting...\n\n"
        
        # Skip empty messages
        if not next_message:
            yield f"data: Empty message received\n\n"
            yield f"data: [DONE]\n\n"
            return
            
        try:
            # Call the model directly
            print(f"DEBUG: Calling model with: '{next_message}'")
            response = chat_session.send_message(next_message)
            print(f"DEBUG: Response received, length: {len(response.text)}")
            
            # Get text
            response_text = response.text
            
            # Check for code blocks
            has_code = "```" in response_text
            
            if has_code:
                print(f"DEBUG: Response contains code blocks")
                print(f"FULL RESPONSE WITH CODE:\n{response_text}")
                simplified_response = "Your code example is ready. Code has been logged to the server console."
                chat_history[-1]["bot"] = response_text
                yield f"data: {simplified_response}\n\n"
            else:
                # Normal text response
                chat_history[-1]["bot"] = response_text
                yield f"data: {response_text}\n\n"
                
            # Clear message after processing
            next_message = ""
            
        except Exception as e:
            error_message = f"Error generating response: {str(e)}"
            print(f"ERROR: {error_message}")
            traceback.print_exc()
            yield f"data: {error_message}\n\n"
            if len(chat_history) > 0:
                chat_history[-1]["bot"] = error_message
        
        # Always send done signal
        yield f"data: [DONE]\n\n"
    
    # Set appropriate headers for SSE
    response = Response(stream_with_context(generate()), 
                       mimetype="text/event-stream")
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@app.route("/query_type", methods=["POST"])
def get_query_type():
    """Returns the predicted query type (code or explanation)"""
    query = request.json.get("query", "")
    if not query:
        return jsonify(success=False, message="No query provided")
    
    query_type = analyze_query_type(query)
    return jsonify(success=True, query_type=query_type)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
