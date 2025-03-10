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
    FROM source_tu tu
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

# Create model with specific configuration for clinical data
try:
    model = genai.GenerativeModel(
        'gemini-2.0-flash',  # Try more reliable model
        generation_config={
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 30,
            "max_output_tokens": 2048,  # Shorter responses for faster generation
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
            'gemini-2.0-pro-exp-02-05',  # Fallback model
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
    Enhanced function to find the most relevant EDC view based on keyword matching.
    Supports both SDTM and ADaM domains with improved pattern matching.
    Fixed to properly match domain-specific views rather than defaulting to ADDCYCLE.
    """
    if not isinstance(edc_metadata, pd.DataFrame) or edc_metadata is None:
        print("WARNING: edc_metadata not available")
        return None
        
    # Extract unique viewnames
    viewnames = edc_metadata['viewname'].unique()
    print(f"INFO: Available unique viewnames: {len(viewnames)}")
    
    # Log first few viewnames for debugging
    sample_views = [v for v in viewnames if isinstance(v, str)][:5]
    print(f"INFO: Sample viewnames: {sample_views}")
    
    # Direct mappings from CDISC domains to EDC view name patterns
    # This provides a more reliable connection between domains and actual view names
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
    
    # Clean string viewnames
    string_views = [v for v in viewnames if isinstance(v, str)]
    if not string_views:
        print("ERROR: No valid string viewnames found in metadata")
        return None
    
    # Preprocessing for better matching
    query_lower = query.lower().strip()
    query_words = query_lower.split()
    
    print(f"INFO: Processing query: '{query_lower}'")
    
    # STEP 1: Direct domain match in query (exact matches like "DM" or "ADSL" as standalone words)
    for domain in domain_to_view_patterns.keys():
        if domain.lower() in query_words or domain in query_words:
            print(f"INFO: Found exact domain match: {domain}")
            # Look for view names that contain this domain
            view_patterns = domain_to_view_patterns[domain]
            
            for pattern in view_patterns:
                # Try exact match first
                pattern_views = [v for v in string_views if pattern.lower() in v.lower()]
                if pattern_views:
                    # Sort so that shorter names come first (more specific matches)
                    pattern_views.sort(key=len)
                    best_view = pattern_views[0]
                    print(f"SUCCESS: Matched domain {domain} to view {best_view} using pattern {pattern}")
                    return best_view
            
            # If no pattern match, try any view with the domain code in it
            domain_views = [v for v in string_views if domain.lower() in v.lower()]
            if domain_views:
                best_view = domain_views[0]
                print(f"SUCCESS: Matched domain {domain} to view {best_view} directly")
                return best_view
    
    # STEP 2: Keyword matching from query to domains
    domain_scores = {}
    
    for domain, patterns in query_domain_patterns.items():
        score = 0
        for pattern in patterns:
            if pattern in query_lower:
                score += 1
                # Extra weight for exact word matches
                if pattern in query_words:
                    score += 2
        
        # Add weight for domain code appearing in query
        if domain.lower() in query_lower:
            score += 3
            
        if score > 0:
            domain_scores[domain] = score
    
    # Sort domains by score
    if domain_scores:
        # Find best matching domain
        best_domain = max(domain_scores.items(), key=lambda x: x[1])[0]
        best_score = domain_scores[best_domain]
        print(f"INFO: Best domain match: {best_domain} (score: {best_score})")
        
        # Try to find a view matching this domain
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
                print(f"SUCCESS: Matched domain {best_domain} to view {best_view} through keyword matching")
                return best_view
                
    # STEP 3: Direct view name search in available views
    for word in query_words:
        if len(word) > 2:  # Ignore short words
            word_views = [v for v in string_views if word.lower() in v.lower()]
            if word_views:
                # Prefer non-RAW views
                non_raw_views = [v for v in word_views if not v.upper().endswith('_RAW')]
                if non_raw_views:
                    best_view = non_raw_views[0]
                    print(f"SUCCESS: Matched query word '{word}' directly to view {best_view}")
                    return best_view
                else:
                    best_view = word_views[0]
                    print(f"SUCCESS: Matched query word '{word}' directly to view {best_view}")
                    return best_view
    
    # STEP 4: Context-based matching for general queries
    query_contexts = {
        'demographics': ['demographic', 'patient', 'subject', 'enrollment'],
        'safety': ['safety', 'adverse', 'toxicity', 'side effect'],
        'efficacy': ['efficacy', 'response', 'outcome', 'effectiveness'],
        'labs': ['laboratory', 'lab', 'test', 'blood', 'urine'],
        'treatment': ['treatment', 'medication', 'drug', 'dose', 'exposure']
    }
    
    context_scores = {}
    for context, keywords in query_contexts.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            context_scores[context] = score
    
    if context_scores:
        best_context = max(context_scores.items(), key=lambda x: x[1])[0]
        print(f"INFO: Best context match: {best_context}")
        
        # Map contexts to view patterns
        context_to_view = {
            'demographics': ['DM', 'DEMO', 'SUBJECT', 'ENROLL'],
            'safety': ['AE', 'ADVERSE'], 
            'efficacy': ['RESPONSE', 'EFFICACY', 'TUMOR', 'RS'],
            'labs': ['LAB', 'BLOOD', 'URINE'],
            'treatment': ['EX', 'CM', 'MEDICATION', 'TREATMENT']
        }
        
        view_patterns = context_to_view.get(best_context, [])
        for pattern in view_patterns:
            matching_views = [v for v in string_views if pattern.lower() in v.lower()]
            if matching_views:
                # Prefer non-RAW views
                non_raw_views = [v for v in matching_views if not v.upper().endswith('_RAW')]
                if non_raw_views:
                    best_view = non_raw_views[0]
                    print(f"SUCCESS: Context {best_context} matched to view {best_view}")
                    return best_view
                else:
                    best_view = matching_views[0]
                    print(f"SUCCESS: Context {best_context} matched to view {best_view}")
                    return best_view
    
    # STEP 5: Domain-specific mapping as fallback
    # Explicitly map common domains to expected views
    domain_view_priority = {
        'DM': 'V_MEDIFLEX_DM',
        'AE': 'V_MEDIFLEX_AE',
        'LB': 'V_MEDIFLEX_Lab',  # Notice capitalization matches the actual view
        'VS': 'V_MEDIFLEX_VS',
        'EX': 'V_MEDIFLEX_EX',
        'CM': 'V_MEDIFLEX_CM',
        'MH': 'V_MEDIFLEX_MH',
        'TU': 'V_MEDIFLEX_TUMOR'
    }
    
    # Look for these exact views first
    for domain, view in domain_view_priority.items():
        if view in string_views:
            if domain.lower() in query_lower or any(kw in query_lower for kw in query_domain_patterns.get(domain, [])):
                print(f"SUCCESS: Using domain priority mapping {domain} -> {view}")
                return view
    
    # STEP 6: Last resort fallback to specific domain-related views rather than ADDCYCLE
    # Prioritize important clinical data views over cycle/visit views
    domain_view_fallbacks = [
        'V_MEDIFLEX_Lab', 'V_MEDIFLEX_AE', 'V_MEDIFLEX_DM',
        'V_MEDIFLEX_VS', 'V_MEDIFLEX_EX', 'V_MEDIFLEX_CM',
        'V_MEDIFLEX_MH', 'V_MEDIFLEX_TUMOR', 'V_MEDIFLEX_BLOOD'
    ]
    
    for view in domain_view_fallbacks:
        if view in string_views:
            print(f"FALLBACK: Using general-purpose clinical view {view}")
            return view
            
    # Absolute last resort: use first non-ADDCYCLE view
    for view in string_views:
        if 'ADDCYCLE' not in view.upper():
            print(f"LAST RESORT: Using first non-ADDCYCLE view: {view}")
            return view
            
    # If all else fails, use first string view but log a warning
    default_view = string_views[0]
    print(f"WARNING: No domain-specific match found. Defaulting to first view: {default_view}")
    return default_view

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
    global chat_session, chat_history, next_message, next_image
    try:
        print("INFO: Clearing chat history and starting new session")
        
        # Reset the Gemini chat session
        try:
            chat_session = model.start_chat(history=[])
            print("INFO: Successfully created new Gemini chat session")
        except Exception as model_error:
            print(f"ERROR: Failed to create new Gemini chat session: {model_error}")
            traceback.print_exc()
            # Even if Gemini fails, continue clearing other state
        
        # Clear all conversation state
        chat_history = []
        next_message = ""
        next_image = ""
        
        # Log success
        print("INFO: Successfully cleared chat history and reset state")
        return jsonify(success=True, message="Chat history cleared")
    except Exception as e:
        error_message = f"Error clearing chat: {str(e)}"
        print(f"ERROR: {error_message}")
        traceback.print_exc()
        return jsonify(success=False, message=error_message)

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
            
            # Determine the query type and prepare an appropriate prompt
            query_type = analyze_query_type(message)
            print(f"INFO: Query type detected as: {query_type}")
            
            # Enhanced user prompt with context
            if query_type == 'code' and relevant_view and relevant_vars:
                try:
                    # Safely build the variable string with error handling
                    var_strings = []
                    for var in relevant_vars[:10]:  # Limit to 10 vars
                        try:
                            if isinstance(var, dict) and 'fieldname' in var and 'label' in var:
                                var_strings.append(f"{var['fieldname']} ({var['label']})")
                            elif isinstance(var, dict) and 'fieldname' in var:
                                var_strings.append(f"{var['fieldname']}")
                            else:
                                print(f"WARNING: Unexpected variable format: {var}")
                        except Exception as var_error:
                            print(f"ERROR processing variable: {var_error}")
                            continue
                    
                    relevant_vars_str = ", ".join(var_strings)
                    if len(relevant_vars) > 10:
                        relevant_vars_str += f" and {len(relevant_vars) - 10} more variables"
                    
                    enhanced_prompt = code_prompt_template.format(
                        query=message,
                        relevant_view=relevant_view,
                        relevant_vars=relevant_vars_str
                    )
                    print(f"INFO: Enhanced code prompt with view context: {relevant_view}")
                except Exception as prompt_error:
                    print(f"ERROR building enhanced code prompt: {prompt_error}")
                    traceback.print_exc()
                    enhanced_prompt = message  # Fallback to original message
            elif query_type == 'explanation' and relevant_view:
                try:
                    enhanced_prompt = explanation_prompt_template.format(
                        query=message,
                        relevant_view=relevant_view
                    )
                    print(f"INFO: Enhanced explanation prompt with view context: {relevant_view}")
                except Exception as prompt_error:
                    print(f"ERROR building enhanced explanation prompt: {prompt_error}")
                    traceback.print_exc()
                    enhanced_prompt = message  # Fallback to original message
            else:
                enhanced_prompt = message
                print("INFO: Using original prompt (no enhancement)")
            
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
            
            # Store the response in history
            chat_history[-1]["bot"] = response_text
            
            # Log information about the response
            response_preview = response_text[:100] + "..." if len(response_text) > 100 else response_text
            print(f"INFO: Generated response: '{response_preview}'")
            print(f"INFO: Response length: {len(response_text)} characters")
            print(f"INFO: Contains code blocks: {'```' in response_text}")
            
            # Return the full text response with debug info
            print("INFO: Returning successful response")
            return jsonify(
                success=True, 
                response=response_text,
                metadata={
                    "query_type": query_type,
                    "response_length": len(response_text),
                    "has_code_blocks": "```" in response_text,
                    "relevant_view": relevant_view if relevant_view else None
                }
            )
                
        except Exception as model_error:
            error_msg = f"Unable to generate response: {str(model_error)}"
            print(f"ERROR: Model error: {model_error}")
            traceback.print_exc()
            chat_history[-1]["bot"] = error_msg
            
            # Try to provide a more helpful error message
            if "quota" in str(model_error).lower() or "rate" in str(model_error).lower():
                error_msg = "API quota exceeded. Please try again in a moment."
            elif "internal" in str(model_error).lower():
                error_msg = "The service is experiencing technical difficulties. Please try again later."
            
            return jsonify(success=False, response=error_msg)
            
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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)