from flask import (
    Flask,
    render_template,
    request,
    Response,
    stream_with_context,
    jsonify,
    session
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
from sanitize import sanitize_text
import uuid
import pickle

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
        'transform', 'model', 'script', 'implementation', 'mapping', 'derivation'
    ]
    explanation_indicators = [
        'explain', 'what', 'why', 'how', 'describe', 'help me understand',
        'tell me about', 'difference between', 'compare', 'analysis'
    ]
    system_instruction = """You are a specialized CDISC standards expert for oncology clinical trials with deep knowledge of BOTH SDTM and ADaM implementations. Your expertise is HIGHLY TECHNICAL and focused on DATA TRANSFORMATIONS, especially in SQL and dbt models for BigQuery.

Core Expertise:
- CDISC standards implementation (SDTM and ADaM) with precise attention to controlled terminology
- Converting source data into SDTM/ADaM models with optimized SQL transformations
- Implementing complex derivations like RECIST criteria and BOR calculations
- Creating efficient, well-structured dbt models that follow best practices
- Designing data pipelines for clinical data standardization

You specialize in these domains and their technical implementations:
- DM/ADSL: Demographics and baseline characteristics with subject-level analysis
- AE/ADAE: Adverse event analysis with SMQs and toxicity grading
- LB/ADLB: Lab test normalization, grading, and shift analyses
- EX/ADEX: Exposure calculations including dose intensity and interruptions
- TU/ADTU: Tumor measurements with complex target/non-target lesion handling
- RS/ADRS: Response assessments using RECIST 1.1 criteria
- ADTTE: Time-to-event analysis with censoring rules
- ADTR: Tumor response analysis with BOR and confirmation logic

Response Guidelines:
- Provide TECHNICALLY PRECISE, SPECIFIC answers with CDISC compliant terminology
- For code requests: Generate COMPLETE, PRODUCTION-QUALITY SQL that includes ALL required fields
- For explanations: Focus on technical implementation details and variable relationships
- Include important derivation logic and handle edge cases in your code
- When mapping data, ensure all required SDTM/ADaM variables are included with correct attributes
- If a topic is outside your expertise, respond only with: 'I can only assist with CDISC standards implementation for clinical trials.'
- PRIORITIZE CODE QUALITY AND TECHNICAL ACCURACY above all else
"""
    code_example = """-- Example dbt model for ADRS (ADaM Response) dataset from SDTM TU and RS
{{ config(
    materialized = 'table',
    schema = 'adam',
    tags = ['oncology', 'response']
) }}

WITH source_tu AS (
    -- Source Target Lesion measurements
    SELECT
        STUDYID,
        USUBJID,
        VISIT,
        VISITNUM,
        TUDTC,
        TULNKID,
        TUTESTCD,
        TUTEST,
        TUORRES,
        TUSTRESC,
        TUMETHOD,
        TULOC,
        TUEVAL,
        TUEVALID
    FROM {{ source('sdtm', 'tu') }}
    WHERE TUTESTCD IN ('DIAMETER', 'SUMDIAM') -- Include only target lesion measurements
      AND TUEVAL = 'INVESTIGATOR'             -- Use investigator assessments
),

source_rs AS (
    -- Source Response data
    SELECT
        STUDYID,
        USUBJID,
        VISIT,
        VISITNUM,
        RSDTC,
        RSTESTCD,
        RSTEST,
        RSCAT,
        RSEVAL,
        RSEVALID,
        RSSTRESC,
        RSNDTC
    FROM {{ source('sdtm', 'rs') }}
    WHERE RSCAT = 'OVERALL RESPONSE'          -- Focus on overall response assessments
      AND RSEVAL = 'INVESTIGATOR'             -- Use investigator assessments
),

-- Join with ADSL for standard subject-level variables
adsl AS (
    SELECT
        STUDYID,
        USUBJID,
        SUBJID,
        SITEID,
        TRTSDT,
        TRTEDT,
        SAFFL,
        TRT01A,
        TRT01P,
        ITTFL,
        AGE,
        SEX,
        RACE
    FROM {{ ref('adsl') }}
    WHERE ITTFL = 'Y'                         -- Include only ITT population
),

-- Calculate baseline sum of diameters
baseline_sod AS (
    SELECT
        USUBJID,
        SUM(CAST(TUSTRESC AS FLOAT64)) AS BASELSUM
    FROM source_tu
    WHERE TUTESTCD = 'DIAMETER'
      AND VISIT = 'SCREENING'                 -- Define baseline as screening visit
    GROUP BY USUBJID
),

-- Target lesion response evaluations by visit
target_response AS (
    SELECT
        tu.USUBJID,
        tu.VISIT,
        tu.VISITNUM,
        tu.TUDTC,
        SUM(CAST(tu.TUSTRESC AS FLOAT64)) AS SUMDIAM,
        bs.BASELSUM,
        -- Calculate percent change from baseline
        CASE 
            WHEN bs.BASELSUM > 0 THEN 
                ROUND(100 * (SUM(CAST(tu.TUSTRESC AS FLOAT64)) - bs.BASELSUM) / bs.BASELSUM, 1)
            ELSE NULL
        END AS PCHG,
        -- Derive target response per RECIST 1.1
        CASE
            WHEN SUM(CAST(tu.TUSTRESC AS FLOAT64)) = 0 THEN 'CR'
            WHEN ROUND(100 * (SUM(CAST(tu.TUSTRESC AS FLOAT64)) - bs.BASELSUM) / bs.BASELSUM, 1) <= -30 THEN 'PR'
            WHEN ROUND(100 * (SUM(CAST(tu.TUSTRESC AS FLOAT64)) - bs.BASELSUM) / bs.BASELSUM, 1) >= 20 THEN 'PD'
            ELSE 'SD'
        END AS TRSP
    FROM source_tu
    LEFT JOIN baseline_sod bs ON tu.USUBJID = bs.USUBJID
    WHERE tu.TUTESTCD = 'DIAMETER'
    GROUP BY tu.USUBJID, tu.VISIT, tu.VISITNUM, tu.TUDTC, bs.BASELSUM
),

-- Combine target and non-target response with overall response
overall_response AS (
    SELECT
        tr.USUBJID,
        tr.VISIT,
        tr.VISITNUM,
        tr.TUDTC AS ADT,
        tr.SUMDIAM,
        tr.BASELSUM,
        tr.PCHG,
        tr.TRSP AS TRLRES,
        rs.RSSTRESC AS OVRLRES,
        -- Derive ADY (analysis day)
        DATE_DIFF(CAST(tr.TUDTC AS DATE), CAST(adsl.TRTSDT AS DATE), DAY) + 1 AS ADY,
        -- Analysis visit derived from visit number
        CASE
            WHEN tr.VISITNUM = 1 THEN 'BASELINE'
            WHEN tr.VISITNUM BETWEEN 2 AND 3 THEN 'CYCLE 1'
            WHEN tr.VISITNUM BETWEEN 4 AND 5 THEN 'CYCLE 2'
            WHEN tr.VISITNUM BETWEEN 6 AND 7 THEN 'CYCLE 3'
            ELSE 'CYCLE ' || CAST(CEIL(tr.VISITNUM / 2) AS STRING)
        END AS AVISIT,
        DENSE_RANK() OVER (PARTITION BY tr.USUBJID ORDER BY tr.VISITNUM) AS AVISITN
    FROM target_response tr
    LEFT JOIN source_rs rs ON tr.USUBJID = rs.USUBJID AND tr.VISIT = rs.VISIT
    LEFT JOIN adsl ON tr.USUBJID = adsl.USUBJID
),

-- Best Overall Response determination
bor_candidates AS (
    SELECT
        USUBJID,
        OVRLRES,
        -- Apply confirmation rule - response must be maintained for ≥4 weeks
        CASE
            WHEN OVRLRES IN ('CR', 'PR') AND 
                 LEAD(OVRLRES, 1) OVER (PARTITION BY USUBJID ORDER BY VISITNUM) IN ('CR', 'PR') AND
                 DATE_DIFF(CAST(LEAD(ADT, 1) OVER (PARTITION BY USUBJID ORDER BY VISITNUM) AS DATE),
                           CAST(ADT AS DATE), DAY) >= 28
            THEN OVRLRES
            WHEN OVRLRES = 'SD' AND ADY >= 42  -- SD requires minimum 6 weeks duration
            THEN 'SD'
            WHEN OVRLRES = 'PD'
            THEN 'PD'
            ELSE NULL
        END AS CONF_RESP
    FROM overall_response
),

best_response AS (
    SELECT
        USUBJID,
        -- Apply response hierarchy (CR > PR > SD > PD > NE)
        CASE
            WHEN COUNT(CASE WHEN CONF_RESP = 'CR' THEN 1 END) > 0 THEN 'CR'
            WHEN COUNT(CASE WHEN CONF_RESP = 'PR' THEN 1 END) > 0 THEN 'PR'
            WHEN COUNT(CASE WHEN CONF_RESP = 'SD' THEN 1 END) > 0 THEN 'SD'
            WHEN COUNT(CASE WHEN CONF_RESP = 'PD' THEN 1 END) > 0 THEN 'PD'
            ELSE 'NE'
        END AS BOR
    FROM bor_candidates
    GROUP BY USUBJID
)

-- Final ADRS dataset
SELECT
    -- ADSL variables (subject-level)
    adsl.STUDYID,
    adsl.USUBJID,
    adsl.SUBJID,
    adsl.SITEID,
    adsl.AGE,
    adsl.SEX,
    adsl.RACE,
    adsl.TRTSDT,
    adsl.TRTEDT,
    adsl.TRT01A,
    adsl.TRT01P,
    
    -- Response assessment data
    or1.ADT,
    or1.ADY,
    or1.AVISIT,
    or1.AVISITN,
    
    -- Analysis parameters in vertical structure
    paramcd.PARAMCD,
    paramcd.PARAM,
    
    -- Analysis values
    CASE 
        WHEN paramcd.PARAMCD = 'OVRLRESP' THEN or1.OVRLRES
        WHEN paramcd.PARAMCD = 'TRLRESP' THEN or1.TRLRES
        WHEN paramcd.PARAMCD = 'BOR' THEN br.BOR
        WHEN paramcd.PARAMCD = 'SUMDIAM' THEN CAST(or1.SUMDIAM AS STRING)
        WHEN paramcd.PARAMCD = 'PCHGBSL' THEN CAST(or1.PCHG AS STRING)
        ELSE NULL
    END AS AVALC,
    
    -- Numeric analysis value when applicable
    CASE 
        WHEN paramcd.PARAMCD = 'SUMDIAM' THEN or1.SUMDIAM
        WHEN paramcd.PARAMCD = 'PCHGBSL' THEN or1.PCHG
        ELSE NULL
    END AS AVAL,
    
    -- Analysis value unit
    CASE 
        WHEN paramcd.PARAMCD = 'SUMDIAM' THEN 'mm'
        WHEN paramcd.PARAMCD = 'PCHGBSL' THEN '%'
        ELSE ''
    END AS AVALU,
    
    -- Baseline values
    CASE 
        WHEN paramcd.PARAMCD = 'SUMDIAM' THEN or1.BASELSUM
        ELSE NULL
    END AS BASE
    
FROM adsl
CROSS JOIN (
    -- Parameters for vertical structure
    SELECT 'OVRLRESP' AS PARAMCD, 'Overall Response' AS PARAM UNION ALL
    SELECT 'TRLRESP' AS PARAMCD, 'Target Lesion Response' AS PARAM UNION ALL
    SELECT 'BOR' AS PARAMCD, 'Best Overall Response' AS PARAM UNION ALL
    SELECT 'SUMDIAM' AS PARAMCD, 'Sum of Diameters' AS PARAM UNION ALL
    SELECT 'PCHGBSL' AS PARAMCD, 'Percent Change from Baseline' AS PARAM
) paramcd
LEFT JOIN overall_response or1 ON adsl.USUBJID = or1.USUBJID
LEFT JOIN best_response br ON adsl.USUBJID = br.USUBJID

-- Only include records that have actual values
WHERE
    (paramcd.PARAMCD IN ('OVRLRESP', 'TRLRESP', 'SUMDIAM', 'PCHGBSL') AND or1.USUBJID IS NOT NULL)
    OR (paramcd.PARAMCD = 'BOR' AND br.USUBJID IS NOT NULL)

ORDER BY
    USUBJID,
    PARAMCD,
    AVISITN
"""
    code_prompt_template = "{query}. Create a dbt transformation in SQL that implements this for BigQuery, following CDISC standards (SDTM or ADaM as appropriate) for oncology trials.\nAvailable source structure:\nView: {relevant_view}.\nVariables: {relevant_vars}.\nGenerate SQL that uses these source variables for the transformation, with no extra text."
    explanation_prompt_template = "{query}. Provide a brief, direct explanation based on:\nSource Structure: {relevant_view}.\nFocus on CDISC standards (SDTM and ADaM) for oncology trials.\nRespond without additional text."

# Add code example to system instruction if available
if code_example:
    system_instruction += f"""
    Here is an example of what a good dbt model query looks like:
        {code_example}
    Please use that as a guide.
    """

# Initialize cached domain lookups for performance
domain_view_cache = {}
domain_processed = set()

# Create model with specific configuration for clinical data
try:
    model = genai.GenerativeModel(
        'gemini-2.0-flash',  # Try more reliable model
        generation_config={
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 25,
            "max_output_tokens": 3068,  # Shorter responses for faster generation
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
            'gemini-2.0-flash-lite',  # Fallback model
            generation_config={
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 30,
                "max_output_tokens": 2048,
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
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'cdisc-standards-assistant-key')

# Session data storage
SESSION_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session_data')
os.makedirs(SESSION_DATA_DIR, exist_ok=True)

# These will be specific to each session
chat_sessions = {}  # Maps session_id to chat_session object
next_message = ""
next_image = ""
uploaded_files = {}  # Maps session_id to uploaded_files list
edc_metadata = None  # Global metadata shared across sessions
sdtm_metadata = {}   # Global metadata shared across sessions
chat_histories = {}  # Maps session_id to chat_history list

# Don't load heavy NLP models for better performance
nlp_models_loaded = False
print("Using lightweight keyword matching for better performance")

def get_or_create_session_id():
    """Get or create a unique session ID for the current user"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        print(f"Created new session: {session['session_id']}")
    return session['session_id']

def get_chat_session(session_id):
    """Get or create a chat session for the given session ID"""
    if session_id not in chat_sessions:
        # Create a new session
        chat_sessions[session_id] = model.start_chat(history=[])
        chat_histories[session_id] = []
        uploaded_files[session_id] = []
        print(f"Created new chat session for {session_id}")
    return chat_sessions[session_id]

def get_chat_history(session_id):
    """Get the chat history for the given session ID"""
    if session_id not in chat_histories:
        chat_histories[session_id] = []
    return chat_histories[session_id]

def save_session_data(session_id):
    """Save session data to a file"""
    try:
        if session_id in chat_histories:
            # Save chat history
            session_file = os.path.join(SESSION_DATA_DIR, f"{session_id}_history.pkl")
            with open(session_file, 'wb') as f:
                pickle.dump(chat_histories[session_id], f)
            
            # Save uploaded files (just their metadata, not the actual files)
            if session_id in uploaded_files:
                files_file = os.path.join(SESSION_DATA_DIR, f"{session_id}_files.pkl")
                with open(files_file, 'wb') as f:
                    pickle.dump(uploaded_files[session_id], f)
            
            print(f"Session data saved for {session_id}")
            return True
    except Exception as e:
        print(f"Error saving session data: {e}")
        traceback.print_exc()
    return False

def load_session_data(session_id):
    """Load session data from a file"""
    try:
        # Load chat history
        history_file = os.path.join(SESSION_DATA_DIR, f"{session_id}_history.pkl")
        if os.path.exists(history_file):
            with open(history_file, 'rb') as f:
                chat_histories[session_id] = pickle.load(f)
            
            # Recreate session with loaded history for the LLM
            history_for_llm = []
            for msg in chat_histories[session_id]:
                if 'user' in msg and 'bot' in msg:
                    history_for_llm.append({
                        'role': 'user',
                        'parts': [msg['user']]
                    })
                    if msg['bot']:  # Only add bot messages if they're not empty
                        history_for_llm.append({
                            'role': 'model',
                            'parts': [msg['bot']]
                        })
            
            # Create a new chat session with the loaded history
            chat_sessions[session_id] = model.start_chat(history=history_for_llm)
            
            # Load uploaded files
            files_file = os.path.join(SESSION_DATA_DIR, f"{session_id}_files.pkl")
            if os.path.exists(files_file):
                with open(files_file, 'rb') as f:
                    uploaded_files[session_id] = pickle.load(f)
            
            print(f"Session data loaded for {session_id}")
            return True
    except Exception as e:
        print(f"Error loading session data: {e}")
        traceback.print_exc()
        # Start with a fresh session if loading fails
        chat_histories[session_id] = []
        chat_sessions[session_id] = model.start_chat(history=[])
        uploaded_files[session_id] = []
    return False

def process_markdown_to_html(markdown_text):
    """
    Simple markdown to HTML converter
    """
    if not markdown_text:
        return ""
    
    # Function to escape HTML
    def escape_html(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    html = []
    lines = markdown_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Code blocks
        if (line.startswith('```')):
            language = line[3:].strip() or "plaintext"
            code_lines = []
            i += 1  # Skip the opening ```
            
            # Collect all lines until closing ```
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i])
                i += 1
                
            # Skip the closing ```
            if i < len(lines):
                i += 1
                
            # Generate code block HTML
            code = escape_html('\n'.join(code_lines))
            html.append(f'''
            <div style="margin:10px 0; border:1px solid #ddd; border-radius:4px; overflow:hidden;">
                <div style="background:#f5f5f5; padding:5px 10px; display:flex; justify-content:space-between; border-bottom:1px solid #ddd;">
                    <span style="font-weight:bold">{language.upper()}</span>
                    <button class="copy-btn" style="border:none; background:none; cursor:pointer; color:blue;">Copy</button>
                </div>
                <pre style="margin:0; padding:10px; overflow:auto;"><code class="{language}">{code}</code></pre>
            </div>
            ''')
            continue
        
        # Headers
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if header_match:
            level = len(header_match.group(1))
            text = header_match.group(2)
            html.append(f'<h{level} style="margin:0.4em 0">{text}</h{level}>')
            i += 1
            continue
        
        # Lists
        list_match = re.match(r'^[-*+]\s+(.+)$', line)
        if list_match:
            text = list_match.group(1)
            html.append(f'<ul style="margin:0.2em 0; padding-left:1.5em"><li>{text}</li></ul>')
            i += 1
            continue
        
        # Paragraphs
        if line.strip():
            html.append(f'<p style="margin:0.3em 0">{line}</p>')
        else:
            html.append('<br>')
        
        i += 1
    
    return '\n'.join(html)

def sanitize_markdown(text):
    """Basic function to sanitize problematic markdown content"""
    if not text:
        return ""
    
    # Replace [object Object] with empty string
    text = text.replace("[object Object]", "")
    
    # If we end up with empty headers like "# ", fix them
    text = re.sub(r'^(#{1,6})\s*$', r'\1 Section', text, flags=re.MULTILINE)
    
    # Use html module's escape function to handle HTML entities
    text = html.escape(text)
    
    # Unescape code blocks and reformat them 
    # This is a simple approach that works in many cases but isn't perfect
    code_block_pattern = r'```(.*?)\n(.*?)```'
    
    def format_code_block(match):
        language = match.group(1).strip() or "plaintext"
        code = match.group(2)
        return f'''```{language}
{code}```'''
    
    text = re.sub(code_block_pattern, format_code_block, text, flags=re.DOTALL)
    
    return text

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
    Optimized query type analysis using cached patterns for better performance.
    """
    # Cache for common SQL patterns - avoids multiple string checks
    SQL_PATTERNS = ['select', 'from', 'where', 'join', 'group by', 'order by', 'having', 'union']
    CODE_PHRASES = ['create a', 'generate a', 'write a', 'build a', 'implement', 'code for']
    EXPLANATION_PHRASES = ['what is', 'how does', 'explain', 'why is', 'tell me about', 'describe']
    
    query = query.lower()
    
    # Fast path for obvious SQL
    for pattern in SQL_PATTERNS:
        if pattern in query:
            return 'code'
    
    # Check for specific code phrases (faster than iterating all indicators)
    for phrase in CODE_PHRASES:
        if phrase in query:
            return 'code'
            
    # Check for specific explanation phrases
    for phrase in EXPLANATION_PHRASES:
        if phrase in query:
            return 'explanation'
    
    # Only do the more expensive analysis if we haven't determined yet
    code_score = sum(1 for word in code_indicators if word in query.split())
    explanation_score = sum(1 for word in explanation_indicators if word in query.split())
    
    return 'code' if code_score >= explanation_score else 'explanation'

def find_relevant_edc_view(query, edc_metadata):
    """
    Performance-optimized function to find the most relevant EDC view based on keyword matching.
    Uses a cache to avoid repeated expensive matching operations.
    """
    global domain_view_cache, domain_processed
    
    if not isinstance(edc_metadata, pd.DataFrame) or edc_metadata is None:
        print("WARNING: edc_metadata not available")
        return None
    
    # Start timing the function
    start_time = time.time()
    
    # Check if we have processed views before
    if not domain_processed:
        # Cache setup - only done once per server session
        try:
            # Extract unique viewnames just once
            viewnames = edc_metadata['viewname'].unique()
            string_views = [v for v in viewnames if isinstance(v, str)]
            
            # Pre-populate the cache with common domains
            common_domains = ['DM', 'AE', 'LB', 'VS', 'CM', 'EX', 'TU', 'RS', 'ADSL', 'ADAE', 'ADLB']
            
            # Direct mappings from CDISC domains to EDC view name patterns
            domain_to_view_patterns = {
                # Core SDTM domains with explicit mapping to view patterns
                'DM': ['DM', 'DEMO', 'SUBJECT'],
                'AE': ['AE', 'ADVERSE'],
                'LB': ['LAB', 'BLOOD', 'SPECIMEN', 'URINE'],
                'EX': ['EX', 'EXPOSURE', 'DRUG', 'MEDICATION', 'TREATMENT'],
                'CM': ['CM', 'CONMED', 'MEDICATION'],
                'MH': ['MH', 'HISTORY', 'MEDICAL'],
                'VS': ['VS', 'VITAL', 'BP'],
                'TU': ['TU', 'TUMOR', 'LESION'],
                'RS': ['RS', 'RESPONSE', 'RECIST', 'EFFICACY'],
                'EG': ['EG', 'ECG', 'ELECTRO'],
                
                # ADaM domains
                'ADSL': ['ADSL', 'SUBJECT', 'DEMO'],
                'ADAE': ['ADAE', 'AE'],
                'ADLB': ['ADLB', 'LAB'],
                'ADEX': ['ADEX', 'EX', 'EXPOSURE'],
                'ADCM': ['ADCM', 'CM', 'MEDICATION'],
                'ADRS': ['ADRS', 'RESPONSE'],
                'ADTU': ['ADTU', 'TUMOR'],
                'ADVS': ['ADVS', 'VS', 'VITAL'],
            }
            
            # Pre-populate cache with direct domain matches (most common case)
            for domain, patterns in domain_to_view_patterns.items():
                for pattern in patterns:
                    pattern_views = [v for v in string_views if pattern.lower() in v.lower()]
                    if pattern_views:
                        # Sort by length for more specific matches
                        pattern_views.sort(key=len)
                        domain_view_cache[domain.lower()] = pattern_views[0]
                        print(f"CACHE: Pre-populated domain {domain} with view {pattern_views[0]}")
                        break
            
            # Also add explicit mappings for common views
            domain_view_priority = {
                'DM': 'V_MEDIFLEX_DM',
                'AE': 'V_MEDIFLEX_AE',
                'LB': 'V_MEDIFLEX_Lab',
                'VS': 'V_MEDIFLEX_VS',
                'EX': 'V_MEDIFLEX_EX',
                'CM': 'V_MEDIFLEX_CM',
                'MH': 'V_MEDIFLEX_MH',
                'TU': 'V_MEDIFLEX_TUMOR'
            }
            
            # Add priority mappings to cache if they exist
            for domain, view in domain_view_priority.items():
                if view in string_views:
                    domain_view_cache[domain.lower()] = view
                    print(f"CACHE: Added priority mapping {domain} -> {view}")
            
            # Mark domains as processed so we don't do this again
            domain_processed = True
            print(f"INFO: Domain view cache initialized with {len(domain_view_cache)} entries")
            
        except Exception as e:
            print(f"ERROR initializing domain cache: {e}")
            # Continue without cache
    
    # Quick processing of query
    query_lower = query.lower().strip()
    query_words = query_lower.split()
    
    # FAST PATH 1: Direct cache lookup for exact domain matches
    for word in query_words:
        if word in domain_view_cache:
            view = domain_view_cache[word]
            print(f"CACHE HIT: Using cached view {view} for domain {word}")
            return view
    
    # FAST PATH 2: Look for domain code in query with word boundaries
    for domain in domain_view_cache.keys():
        # Check for domain with word boundaries (e.g. "DM " or " DM" but not "ADMH")
        pattern = r'\b' + re.escape(domain) + r'\b'
        if re.search(pattern, query_lower):
            view = domain_view_cache[domain]
            print(f"CACHE HIT: Found domain {domain} in query with word boundary")
            return view
    
    # If we get here, we need to do the full analysis
    
    # Extract unique viewnames
    viewnames = edc_metadata['viewname'].unique()
    string_views = [v for v in viewnames if isinstance(v, str)]
    
    if not string_views:
        print("ERROR: No valid string viewnames found in metadata")
        return None
        
    # Standard CDISC domain patterns for identifying domains in user queries
    query_domain_patterns = {
        # Core domains
        'DM': ['demographic', 'subject', 'patient', 'dm', 'subject characteristic'],
        'AE': ['adverse event', 'ae', 'safety', 'adverse', 'side effect', 'reaction'],
        'LB': ['lab', 'laboratory', 'lb', 'test', 'result', 'specimen'],
        'EX': ['exposure', 'administration', 'dose', 'ex', 'drug', 'medication taken', 'treatment'],
        'CM': ['concomitant', 'medication', 'treatment', 'drug', 'cm', 'conmed'],
        'MH': ['medical history', 'mh', 'prior condition', 'previous condition'],
        'DH': ['disease history', 'dh', 'diagnosis', 'cancer history'],
        'RS': ['response', 'recist', 'rs', 'assessment', 'evaluation'],
        'TU': ['tumor', 'lesion', 'cancer', 'tu', 'mass', 'nodule'],
        'VS': ['vital', 'signs', 'vs', 'blood pressure', 'temperature', 'pulse'],
        
        # ADaM domains
        'ADSL': ['subject level', 'adsl', 'baseline', 'population', 'disposition'],
        'ADAE': ['adverse event analysis', 'adae', 'safety analysis'],
        'ADLB': ['laboratory analysis', 'adlb', 'lab test analysis'],
        'ADEX': ['exposure analysis', 'adex', 'dosing analysis', 'treatment analysis'],
        'ADCM': ['concomitant medication analysis', 'adcm'],
        'ADMH': ['medical history analysis', 'admh'],
        'ADRS': ['response analysis', 'adrs', 'efficacy analysis'],
        'ADTU': ['tumor analysis', 'adtu', 'lesion analysis'],
        'ADVS': ['vital signs analysis', 'advs'],
        'ADTTE': ['time to event', 'adtte', 'survival', 'duration', 'ttx', 'tte'],
        'ADTR': ['tumor response', 'adtr', 'best response', 'bor', 'overall response'],
    }
    
    # Keyword matching from query to domains - using scoring
    domain_scores = {}
    
    for domain, patterns in query_domain_patterns.items():
        score = sum(1 for pattern in patterns if pattern in query_lower)
        
        # Extra weight for domain code in query
        if domain.lower() in query_lower:
            score += 3
            
        if score > 0:
            domain_scores[domain] = score
    
    # Find best matching domain if any
    if domain_scores:
        best_domain = max(domain_scores.items(), key=lambda x: x[1])[0]
        
        # Check cache for this domain
        if best_domain.lower() in domain_view_cache:
            view = domain_view_cache[best_domain.lower()]
            print(f"CACHE HIT: Using cached view {view} for best domain match {best_domain}")
            return view
            
        # If not in cache, look for matching view using domain patterns
        domain_to_view_patterns = {
            'DM': ['DM', 'DEMO', 'SUBJECT'],
            'AE': ['AE', 'ADVERSE'],
            'LB': ['LAB', 'BLOOD', 'SPECIMEN', 'URINE'],
            'EX': ['EX', 'EXPOSURE', 'DRUG', 'MEDICATION', 'TREATMENT'],
            'CM': ['CM', 'CONMED', 'MEDICATION'],
            'MH': ['MH', 'HISTORY', 'MEDICAL'],
            'VS': ['VS', 'VITAL', 'BP'],
            'TU': ['TU', 'TUMOR', 'LESION'],
            'RS': ['RS', 'RESPONSE', 'RECIST', 'EFFICACY'],
            'EG': ['EG', 'ECG', 'ELECTRO'],
            'ADSL': ['ADSL', 'SUBJECT', 'DEMO'],
            'ADAE': ['ADAE', 'AE'],
            'ADLB': ['ADLB', 'LAB'],
            'ADEX': ['ADEX', 'EX', 'EXPOSURE'],
            'ADCM': ['ADCM', 'CM', 'MEDICATION'],
            'ADRS': ['ADRS', 'RESPONSE'],
            'ADTU': ['ADTU', 'TUMOR'],
            'ADVS': ['ADVS', 'VS', 'VITAL'],
        }
        
        view_patterns = domain_to_view_patterns.get(best_domain, [best_domain])
        for pattern in view_patterns:
            matching_views = [v for v in string_views if pattern.lower() in v.lower()]
            if matching_views:
                # Look for RAW vs non-RAW versions
                non_raw_views = [v for v in matching_views if not v.upper().endswith('_RAW')]
                if non_raw_views:
                    best_view = non_raw_views[0]
                else:
                    best_view = matching_views[0]
                
                # Cache this result for future use
                domain_view_cache[best_domain.lower()] = best_view
                print(f"SUCCESS: Domain {best_domain} matched to view {best_view} (added to cache)")
                return best_view
    
    # Fallback: direct match to known priority views
    domain_view_priority = {
        'DM': 'V_MEDIFLEX_DM',
        'AE': 'V_MEDIFLEX_AE',
        'LB': 'V_MEDIFLEX_Lab',
        'VS': 'V_MEDIFLEX_VS',
        'EX': 'V_MEDIFLEX_EX',
        'CM': 'V_MEDIFLEX_CM',
        'MH': 'V_MEDIFLEX_MH',
        'TU': 'V_MEDIFLEX_TUMOR'
    }
    
    # Last resort: general-purpose fallbacks
    fallback_views = [v for v in string_views if 'ADDCYCLE' not in v.upper()]
    if fallback_views:
        default_view = fallback_views[0]
        print(f"FALLBACK: Using general view: {default_view}")
        return default_view
    
    # If no string views available at all
    print("ERROR: No usable views found")
    return None

def get_relevant_variables(viewname, edc_metadata):
    """
    Get relevant variables and their metadata for a specific view.
    Contains safeguards for missing fields and data validation.
    Enhanced to provide more context for CDISC mapping.
    """
    if not isinstance(edc_metadata, pd.DataFrame) or edc_metadata is None:
        print("WARNING: edc_metadata is not available or not a DataFrame")
        return []
        
    # Check if viewname column exists
    if 'viewname' not in edc_metadata.columns:
        print(f"WARNING: 'viewname' column missing from edc_metadata. Available columns: {edc_metadata.columns.tolist()}")
        return []
    
    # Make sure viewname is a string
    if not isinstance(viewname, str):
        print(f"WARNING: viewname is not a string: {type(viewname)}")
        return []
    
    try:
        # Filter the dataframe for the specific view
        view_vars = edc_metadata[edc_metadata['viewname'] == viewname]
        
        # Check if we have results
        if view_vars.empty:
            print(f"WARNING: No variables found for viewname '{viewname}'")
            return []
            
        # Handle column mapping for different EDC systems
        column_mapping = {
            'fieldname': ['fieldname', 'field', 'name', 'varname'],
            'label': ['label', 'description', 'varlabel'],
            'type': ['type', 'datatype', 'vartype'],
            'length': ['length', 'size', 'varlength'],
            'format': ['format', 'varformat'],
            'codelist': ['codelist', 'coded_values', 'terminology']
        }
        
        # Map columns to standardized names
        for target_col, source_options in column_mapping.items():
            if target_col not in view_vars.columns:
                for source_col in source_options:
                    if source_col in view_vars.columns:
                        view_vars[target_col] = view_vars[source_col]
                        print(f"INFO: Mapped '{source_col}' to '{target_col}'")
                        break
                else:
                    # If no match found, create placeholder
                    if target_col == 'fieldname':
                        view_vars[target_col] = view_vars.index.astype(str)
                    elif target_col == 'label':
                        view_vars[target_col] = 'No description available'
                    else:
                        view_vars[target_col] = None
        
        # Identify potential CDISC mapping candidates (variables with _STD suffix or matching SDTM naming)
        sdtm_pattern = re.compile(r'^[A-Z]{2,4}$')  # Basic pattern for SDTM var names
        
        def identify_cdisc_mapping(row):
            # Check for _STD suffix which often indicates a coded value
            std_field = f"{row['fieldname']}_STD" if 'fieldname' in row else None
            if std_field and std_field in view_vars.columns.tolist():
                return f"Coded value in {std_field}"
            
            # Check if the field name matches SDTM pattern
            if sdtm_pattern.match(str(row.get('fieldname', ''))):
                return f"Potential SDTM variable"
            
            # Check for common SDTM variable names in the field
            common_sdtm_vars = ['DTC', 'STDT', 'ENDT', 'TERM', 'TESTCD', 'ORRES', 'STRESC']
            for sdtm_var in common_sdtm_vars:
                if sdtm_var in str(row.get('fieldname', '')):
                    return f"Contains SDTM component: {sdtm_var}"
            
            return None
        
        # Add CDISC mapping hints to records
        records = []
        for _, row in view_vars.iterrows():
            record = row.to_dict()
            mapping_hint = identify_cdisc_mapping(record)
            if mapping_hint:
                record['cdisc_hint'] = mapping_hint
            records.append(record)
            
        print(f"INFO: Found {len(records)} variables for viewname '{viewname}'")
        return records
        
    except Exception as e:
        print(f"ERROR in get_relevant_variables: {e}")
        traceback.print_exc()
        return []

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

# Test function to validate the EDC view selection fix
def test_edc_view_selection():
    """
    Tests the find_relevant_edc_view function with various domain-specific queries
    to ensure correct table selection.
    """
    global edc_metadata
    
    if not isinstance(edc_metadata, pd.DataFrame) or edc_metadata is None:
        print("ERROR: Cannot run tests - EDC metadata not loaded")
        return
        
    test_queries = [
        # Format: (query, expected_domain)
        ("Tell me about the LB domain", "LB"),
        ("Convert laboratory data to SDTM", "LB"),
        ("Create a mapping for adverse events", "AE"),
        ("Generate SQL for demographics", "DM"),
        ("Map vital signs from source to SDTM", "VS"),
        ("How do I transform tumor measurements?", "TU"),
        ("What is the best approach to handle concomitant medications?", "CM"),
        ("Generate RECIST criteria evaluation code", "RS"),
    ]
    
    print("\n===== TESTING EDC VIEW SELECTION =====")
    print(f"Available EDC metadata with {len(edc_metadata)} rows")
    
    for query, expected_domain in test_queries:
        print(f"\nTEST QUERY: '{query}'")
        print(f"EXPECTED DOMAIN: {expected_domain}")
        
        selected_view = find_relevant_edc_view(query, edc_metadata)
        
        if selected_view:
            # Check if view name contains expected domain (allowing for variations in casing)
            domain_match = expected_domain.lower() in selected_view.lower()
            alternative_match = False
            
            # Special case handling for domains with alternative views
            if expected_domain == "LB" and ("LAB" in selected_view.upper() or "BLOOD" in selected_view.upper() or "URINE" in selected_view.upper()):
                domain_match = True
                alternative_match = True
            elif expected_domain == "TU" and "TUMOR" in selected_view.upper():
                domain_match = True
                alternative_match = True
                
            if domain_match:
                if alternative_match:
                    print(f"✅ SUCCESS: Selected appropriate alternative view: {selected_view}")
                else:
                    print(f"✅ SUCCESS: Selected view contains domain: {selected_view}")
            else:
                # The selected view does not contain the expected domain
                print(f"❌ FAILURE: Selected view '{selected_view}' does not match expected domain '{expected_domain}'")
                # Print the first few records for this view to understand why it was selected
                try:
                    view_vars = edc_metadata[edc_metadata['viewname'] == selected_view]
                    print(f"Selected view has {len(view_vars)} variables")
                    if not view_vars.empty:
                        print("First few variable names:")
                        if 'varname' in view_vars.columns:
                            print(view_vars['varname'].head(3).tolist())
                        elif 'fieldname' in view_vars.columns:
                            print(view_vars['fieldname'].head(3).tolist())
                except Exception as e:
                    print(f"Error examining view: {e}")
        else:
            print("❌ FAILURE: No view selected")
            
    print("\n===== END OF EDC VIEW SELECTION TESTS =====\n")

# Initialize data files ONLY at startup (will be performed once)
# Tests only run in development mode
if os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_DEBUG') == '1':
    # Initialize files and then run tests in debug mode
    initialize_data_files()
    test_edc_view_selection()
else:
    # Just initialize files in production mode, no tests
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
    """
    Clears the chat history and starts a new session with the LLM.
    Properly resets all conversation state for a fresh start.
    """
    try:
        # Get the session ID
        session_id = get_or_create_session_id()
        
        print(f"INFO: Clearing chat history for session {session_id}")
        
        # Reset the Gemini chat session
        try:
            chat_sessions[session_id] = model.start_chat(history=[])
            print(f"INFO: Successfully created new Gemini chat session for {session_id}")
        except Exception as model_error:
            print(f"ERROR: Failed to create new Gemini chat session: {model_error}")
            traceback.print_exc()
        
        # Clear conversation state for this session
        chat_histories[session_id] = []
        
        # Keep uploaded_files metadata but clear session-specific data
        if session_id in uploaded_files:
            files_backup = uploaded_files[session_id]
        else:
            files_backup = []
        
        # Delete all session files
        try:
            session_pattern = os.path.join(SESSION_DATA_DIR, f"{session_id}_*")
            for session_file in glob.glob(session_pattern):
                try:
                    os.remove(session_file)
                    print(f"INFO: Removed session file: {session_file}")
                except Exception as remove_error:
                    print(f"WARNING: Failed to remove session file {session_file}: {remove_error}")
        except Exception as file_error:
            print(f"ERROR: Failed to clean session files: {file_error}")
        
        # Restore uploaded files metadata
        uploaded_files[session_id] = files_backup
        
        # Load welcome template
        try:
            welcome_template_path = os.path.join('templates', 'welcome_template.html')
            if os.path.exists(welcome_template_path):
                with open(welcome_template_path, 'r') as f:
                    welcome_html = f.read()
                    print("INFO: Successfully loaded welcome template")
            else:
                welcome_html = """
                <div class="welcome-message">
                  <h3>Welcome to the CDISC Standards Assistant</h3>
                  <p>I can help you with:</p>
                  <ul>
                    <li>Converting source data into SDTM/ADaM standards</li>
                    <li>Creating dbt models and SQL transformations for clinical data</li>
                    <li>Implementing RECIST criteria and oncology-specific analyses</li>
                    <li>Designing ADaM datasets for efficacy and safety analysis</li>
                  </ul>
                  <p>Try asking:</p>
                  <div class="example-queries">
                    <div class="example-query" id="ex-1">"Tell me about the DM domain structure and purpose"</div>
                    <div class="example-query" id="ex-2">"Explain the key variables in the ADSL domain"</div>
                    <div class="example-query" id="ex-3">"Generate code to map lab data to SDTM LB domain with explanation"</div>
                  </div>
                  <p class="prompt-tip">For best results, ask for explanations about domains before requesting code.</p>
                </div>
                """
                print("INFO: Using inline welcome message (template not found)")
        except Exception as template_error:
            print(f"ERROR: Failed to load welcome template: {template_error}")
            welcome_html = "<div class='welcome-message'><h3>Chat history cleared</h3><p>You can start a new conversation.</p></div>"
        
        # Save the clean session state
        save_session_data(session_id)
        
        # Log success and return
        print(f"INFO: Successfully cleared chat history for session {session_id}")
        return jsonify(success=True, message="Chat history cleared", welcome_html=welcome_html)
    except Exception as e:
        error_message = f"Error clearing chat: {str(e)}"
        print(f"ERROR: {error_message}")
        traceback.print_exc()
        return jsonify(success=False, message=error_message)

@app.route("/", methods=["GET"])
def index():
    """Renders the main homepage for the app with persistent sessions"""
    session_id = get_or_create_session_id()
    
    # Try to load existing session data
    if session_id in chat_sessions:
        # Session already initialized
        print(f"Using existing session: {session_id}")
    else:
        # Try to load from disk
        load_result = load_session_data(session_id)
        if load_result:
            print(f"Loaded session data from disk for {session_id}")
        else:
            print(f"No saved data found for {session_id}")
    
    # Ensure we have a chat session
    chat_session = get_chat_session(session_id)
    chat_history = get_chat_history(session_id)
    
    # Convert our chat history format to the one expected by the template
    messages = []
    for idx, msg in enumerate(chat_history):
        if 'user' in msg:
            messages.append({
                'role': 'user',
                'content': msg['user'],
                'id': idx + 1
            })
        if 'bot' in msg and msg['bot']:
            messages.append({
                'role': 'assistant',
                'content': msg['bot'],
                'id': idx + 1
            })
    
    # Get files for this session
    session_files = uploaded_files.get(session_id, [])
    
    # Use welcome_template.html content if it exists
    welcome_html = None
    try:
        welcome_template_path = 'templates/welcome_template.html'
        if os.path.exists(welcome_template_path):
            with open(welcome_template_path, 'r') as f:
                welcome_html = f.read()
    except Exception as e:
        print(f"Error loading welcome template: {e}")
    
    return render_template(
        "index.html", 
        messages=messages,
        files=session_files,
        welcome_html=welcome_html
    )

@app.route("/chat", methods=["POST"])
def chat():
    """
    Chat endpoint handling both synchronous and streaming responses.
    Contains robust error handling and logs detailed information for debugging.
    """
    try:
        print("\n\n==== CHAT ENDPOINT CALLED ====")
        print(f"TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"METHOD: {request.method}")
        print(f"ROUTE: {request.path}")
        
        # Check for valid JSON and log the raw request data
        print(f"DEBUG: Request headers: {dict(request.headers)}")
        print(f"DEBUG: Request content type: {request.content_type}")
        print(f"DEBUG: Raw request data: {request.data}")
        
        if not request.is_json:
            print(f"ERROR: Request is not JSON. Raw data: {request.data}")
            return jsonify(success=False, response="Invalid request format. Please send a JSON object with a 'message' field.")
        
        try:
            # Extract message from request
            print(f"DEBUG: Request JSON: {request.json}")
            message = request.json.get("message", "").strip()
            print(f"INFO: Received message: '{message[:50]}...' ({len(message)} chars)")
        except Exception as e:
            print(f"ERROR parsing JSON: {e}")
            print(f"Raw request data: {request.data}")
            return jsonify(success=False, response="Error parsing request data. Please check your request format.")
        
        # Validate message content
        if not message:
            print("ERROR: Empty message received")
            return jsonify(success=False, response="Please enter a message to continue.")
        
        # Check message length
        if len(message) > 2000:  # Set a reasonable limit
            print(f"ERROR: Message too long ({len(message)} chars)")
            return jsonify(success=False, response="Your message is too long. Please limit your query to 2000 characters.")
            
        # Get the session ID
        session_id = get_or_create_session_id()
        chat_session = get_chat_session(session_id)
        chat_history = get_chat_history(session_id)
        
        # Add to chat history for tracking (use neutral keys that work with or without Gemini)
        chat_history.append({"user": message, "bot": ""})
        
        # For debugging/testing, provide a static response
        if message.lower() == "test":
            test_response = "This is a test response to verify the UI is working properly."
            chat_history[-1]["bot"] = test_response
            print("DEBUG: Returning test response")
            return jsonify(success=True, response=test_response)
        
        # Add domain-specific test cases
        if message.lower() == "test adam":
            test_response = "ADaM (Analysis Data Model) is a CDISC standard for representing clinical trial analysis datasets. Key ADaM datasets include ADSL (Subject Level), ADAE (Adverse Events), ADLB (Lab Tests), and ADTTE (Time-to-Event)."
            chat_history[-1]["bot"] = test_response
            print("DEBUG: Returning ADaM test response")
            return jsonify(success=True, response=test_response)
            
        if message.lower() == "test sdtm":
            test_response = "SDTM (Study Data Tabulation Model) is a CDISC standard that organizes clinical trial data into standardized domains such as DM (Demographics), AE (Adverse Events), LB (Laboratory Tests), and VS (Vital Signs)."
            chat_history[-1]["bot"] = test_response
            print("DEBUG: Returning SDTM test response")
            return jsonify(success=True, response=test_response)
            
        if message.lower() == "test code formatting":
            test_response = """-- This is a test of SQL code formatting with comments
-- dbt model for DM (Demographics) dataset
-- This model transforms source data into the CDISC SDTM DM domain

WITH source_data AS (
    -- Select and transform columns from the source view
    -- Apply data cleaning functions to ensure proper formatting
    SELECT
        CAST(TRIM(REGEXP_REPLACE(subject_id, r'[^\\x00-\\x7F]+', '')) AS STRING) AS STUDYID,  -- Study Identifier
        CAST(TRIM(REGEXP_REPLACE(patient_id, r'[^\\x00-\\x7F]+', '')) AS STRING) AS USUBJID,  -- Unique Subject Identifier
        CAST(TRIM(REGEXP_REPLACE(site_id, r'[^\\x00-\\x7F]+', '')) AS STRING) AS SITEID,      -- Study Site Identifier
        CAST(TRIM(REGEXP_REPLACE(gender, r'[^\\x00-\\x7F]+', '')) AS STRING) AS SEX,          -- Sex
        SAFE_CAST(TRIM(REGEXP_REPLACE(age, r'[^\\x00-\\x7F]+', '')) AS INT64) AS AGE,         -- Age
        CAST(TRIM(REGEXP_REPLACE(race, r'[^\\x00-\\x7F]+', '')) AS STRING) AS RACE,           -- Race
        CAST(TRIM(REGEXP_REPLACE(ethnicity, r'[^\\x00-\\x7F]+', '')) AS STRING) AS ETHNIC     -- Ethnicity
    FROM {{ source('raw', 'v_patient_demographics') }}
)

-- Final DM domain output with CDISC-compliant variables
SELECT
    STUDYID,    -- Study Identifier
    USUBJID,    -- Unique Subject Identifier
    SUBJID,     -- Subject Identifier for the Study
    SITEID,     -- Study Site Identifier
    
    -- Apply controlled terminology mapping for sex
    CASE 
        WHEN UPPER(SEX) = 'M' OR UPPER(SEX) = 'MALE' THEN 'M'
        WHEN UPPER(SEX) = 'F' OR UPPER(SEX) = 'FEMALE' THEN 'F'
        WHEN UPPER(SEX) = 'U' OR UPPER(SEX) = 'UNKNOWN' THEN 'U'
        ELSE 'U'  -- Default to Unknown if not provided
    END AS SEX,
    
    -- Age handling with validation
    CASE
        WHEN AGE IS NULL THEN NULL
        WHEN AGE < 0 THEN NULL  -- Handle invalid ages
        WHEN AGE > 89 THEN 89   -- Age cap per privacy requirements
        ELSE AGE
    END AS AGE,
    
    -- Map Race to CDISC controlled terminology
    CASE
        WHEN UPPER(RACE) LIKE '%WHITE%' THEN 'WHITE'
        WHEN UPPER(RACE) LIKE '%BLACK%' OR UPPER(RACE) LIKE '%AFRICAN%' THEN 'BLACK OR AFRICAN AMERICAN'
        WHEN UPPER(RACE) LIKE '%ASIAN%' THEN 'ASIAN'
        WHEN UPPER(RACE) LIKE '%HAWAIIAN%' OR UPPER(RACE) LIKE '%PACIFIC%' THEN 'NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER'
        WHEN UPPER(RACE) LIKE '%AMERICAN INDIAN%' OR UPPER(RACE) LIKE '%ALASKA%' THEN 'AMERICAN INDIAN OR ALASKA NATIVE'
        ELSE 'OTHER'
    END AS RACE,
    
    -- Map Ethnicity to CDISC controlled terminology
    CASE
        WHEN UPPER(ETHNIC) LIKE '%HISPANIC%' OR UPPER(ETHNIC) LIKE '%LATINO%' THEN 'HISPANIC OR LATINO'
        WHEN UPPER(ETHNIC) LIKE '%NOT HISPANIC%' OR UPPER(ETHNIC) LIKE '%NOT LATINO%' THEN 'NOT HISPANIC OR LATINO'
        ELSE 'UNKNOWN'
    END AS ETHNIC
    
FROM source_data
WHERE USUBJID IS NOT NULL  -- Only include records with valid subject IDs

ORDER BY
    USUBJID  -- Ensure consistent ordering
"""
            chat_history[-1]["bot"] = test_response
            print("DEBUG: Returning code formatting test response")
            return jsonify(success=True, response=test_response)
            
        # Normal processing with the model
        try:
            # Check if we can find a relevant view for context enhancement
            relevant_view = None
            relevant_vars = []
            
            if isinstance(edc_metadata, pd.DataFrame) and not edc_metadata.empty:
                relevant_view = find_relevant_edc_view(message, edc_metadata)
                if relevant_view:
                    relevant_vars = get_relevant_variables(relevant_view, edc_metadata)
                    print(f"INFO: Found relevant view: {relevant_view} with {len(relevant_vars)} variables")
            
            # Start measuring prompt preparation time
            prompt_start_time = time.time()
            
            # Determine the query type using optimized analysis
            query_type = analyze_query_type(message)
            print(f"INFO: Query type detected as: {query_type}")
            
            # Enhanced user prompt with context - more efficient implementation
            if query_type == 'code' and relevant_view and relevant_vars:
                try:
                    # Fast implementation for variable string building - limit to 10 vars
                    # Use list comprehension instead of loop for better performance
                    var_strings = [
                        f"{var.get('fieldname', 'Unknown')} ({var.get('label', 'No label')})" 
                        for var in relevant_vars[:10] 
                        if isinstance(var, dict) and 'fieldname' in var
                    ]
                    
                    # Fast string joining
                    relevant_vars_str = ", ".join(var_strings)
                    if len(relevant_vars) > 10:
                        relevant_view=relevant_view,
                        relevant_vars=relevant_vars_str
                    
                    print(f"INFO: Enhanced code prompt with view context: {relevant_view}")
                except Exception as prompt_error:
                    print(f"ERROR building enhanced code prompt: {prompt_error}")
                    enhanced_prompt = message  # Fallback to original message
            elif query_type == 'explanation' and relevant_view:
                try:
                    # Simple template formatting for explanation prompt
                    enhanced_prompt = explanation_prompt_template.format(
                        query=message,
                        relevant_view=relevant_view
                    )
                    print(f"INFO: Enhanced explanation prompt with view context: {relevant_view}")
                except Exception as prompt_error:
                    print(f"ERROR building enhanced explanation prompt: {prompt_error}")
                    enhanced_prompt = message  # Fallback to original message
            else:
                enhanced_prompt = message
                print("INFO: Using original prompt (no enhancement)")
                
            # Log prompt preparation time
            prompt_prep_time = time.time() - prompt_start_time
            print(f"INFO: Prompt preparation took {prompt_prep_time:.3f} seconds")
            
            # Add SDTM metadata if relevant
            if sdtm_metadata and ('sdtm' in message.lower() or 'domain' in message.lower()):
                relevant_sdtm_info = get_sdtm_metadata(sdtm_metadata, message)
                if relevant_sdtm_info:
                    enhanced_prompt += f"\n\nRelevant SDTM Metadata:\n{relevant_sdtm_info}"
                    print("INFO: Added SDTM metadata to prompt")
            
            print(f"DEBUG: Calling model with enhanced message...")
            # Log a preview of the prompt (not the full thing to keep logs manageable)
            prompt_preview = enhanced_prompt[:100] + "..." if len(enhanced_prompt) > 100 else enhanced_prompt
            print(f"DEBUG: Prompt preview: '{prompt_preview}'")
            
            # Call the model with the enhanced prompt
            response = chat_session.send_message(enhanced_prompt)
            response_text = response.text
            
            # Process the response
            if not response_text or response_text.strip() == "":
                error_msg = "No response was generated. Please try again with a different query."
                print(f"ERROR: Empty response from model")
                chat_history[-1]["bot"] = error_msg
                return jsonify(success=False, response=error_msg)
            
            # Store the response directly but clean out any object references
            chat_history[-1]["bot"] = sanitize_text(response_text)
            
            # Save the updated session data
            save_session_data(session_id)
            
            # Log information about the response
            response_preview = response_text[:100] + "..." if len(response_text) > 100 else response_text
            print(f"INFO: Generated response: '{response_preview}'")
            print(f"INFO: Response length: {len(response_text)} characters")
            print(f"INFO: Contains code blocks: {'```' in response_text}")
            print(f"INFO: Session {session_id} updated and saved")
            
            # Return the full text response with debug info
            print("INFO: Returning successful response")
            # Return sanitized response
            sanitized_response = sanitize_text(response_text)
            return jsonify(
                success=True, 
                response=sanitized_response,
                metadata={
                    "query_type": query_type,
                    "response_length": len(sanitized_response),
                    "has_code_blocks": "```" in sanitized_response,
                    "relevant_view": relevant_view if relevant_view else None,
                    "session_id": session_id
                }
            )
                
        except Exception as model_error:
            error_msg = f"Unable to generate response: {str(model_error)}"
            print(f"ERROR: Model error: {model_error}")
            traceback.print_exc()
            chat_history[-1]["bot"] = error_msg
            
            # Still save the error in history
            save_session_data(session_id)
            
            # Try to provide a more helpful error message
            if "quota" in str(model_error).lower() or "rate" in str(model_error).lower():
                error_msg = "API quota exceeded. Please try again in a moment."
            elif "internal" in str(model_error).lower():
                error_msg = "The service is experiencing technical difficulties. Please try again later."
            
            return jsonify(success=False, response=error_msg, session_id=session_id)
            
    except Exception as server_error:
        error_message = f"Server error occurred. Please try again later."
        print(f"ERROR: Overall endpoint error: {server_error}")
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
            
            if (has_code):
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

@app.route("/ping", methods=["GET", "POST"])
def ping():
    """Simple diagnostic endpoint to test connectivity"""
    print(f"\n==== PING ENDPOINT CALLED ====")
    print(f"TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"METHOD: {request.method}")
    
    # Return request info for diagnostic purposes
    response_data = {
        "success": True,
        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "method": request.method,
        "headers": dict(request.headers),
        "is_json": request.is_json,
        "data": request.get_data(as_text=True) if request.data else None
    }
    
    print("Ping responding with success")
    return jsonify(response_data)

@app.route("/test_chat", methods=["GET", "POST"])
def test_chat():
    """Special test endpoint that mimics the chat endpoint but without LLM processing"""
    print(f"\n==== TEST CHAT ENDPOINT CALLED ====")
    print(f"TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"METHOD: {request.method}")
    
    # Log all request details
    print(f"DEBUG: Request headers: {dict(request.headers)}")
    print(f"DEBUG: Request content type: {request.content_type}")
    print(f"DEBUG: Request data: {request.get_data(as_text=True)}")
    
    if request.is_json:
        try:
            message = request.json.get("message", "")
            print(f"DEBUG: Received message: '{message}'")
            
            # Return immediate success with echo
            return jsonify({
                "success": True,
                "response": f"Echo: {message}",
                "metadata": {
                    "time": time.strftime('%Y-%m-%d %H:%M:%S'),
                    "is_test": True
                }
            })
        except Exception as e:
            print(f"ERROR parsing JSON: {e}")
            return jsonify(success=False, response=f"Error parsing JSON: {str(e)}")
    else:
        # Handle non-JSON request
        print("DEBUG: Received non-JSON request")
        return jsonify({
            "success": False,
            "response": "This endpoint expects a JSON request with a 'message' field",
            "received_data": request.get_data(as_text=True)
        })

@app.after_request
def add_header(response):
    """Add headers to prevent browser caching"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)