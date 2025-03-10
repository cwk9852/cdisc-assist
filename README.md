# CDISC Standards Assistant

An interactive AI-powered assistant for working with CDISC standards, specifically focused on SDTM and ADaM implementations for clinical trials data.

## Features

- **Interactive Chat Interface**: Get real-time assistance with CDISC standards implementation
- **SDTM & ADaM Domain Guide**: Quick reference for domain structures and variables
- **Code Generation**: Generate SQL/dbt code for data transformations
- **Context-Aware Responses**: Upload EDC metadata and SDTM specifications for enhanced assistance
- **File Management**: Upload and manage clinical data files for context
- **Domain Documentation**: Built-in documentation for SDTM and ADaM domains

## Supported Domains

### SDTM Domains
- Demographics (DM)
- Adverse Events (AE)
- Laboratory Tests (LB)
- Vital Signs (VS)
- Concomitant Medications (CM)
- Exposure (EX)
- Medical History (MH)
- Tumor/Lesion Measurements (TU)
- Response/Disease Status (RS)

### ADaM Domains
- Subject-Level (ADSL)
- Adverse Events Analysis (ADAE)
- Laboratory Analysis (ADLB)
- Vital Signs Analysis (ADVS)
- Exposure Analysis (ADEX)
- Response Analysis (ADRS)
- Time-to-Event Analysis (ADTTE)
- Tumor Response Analysis (ADTR)

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd CSC525/Week8
```

2. Set up a Python virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
# Create a .env file with:
GOOGLE_API_KEY=your_gemini_api_key
SECRET_KEY=your_flask_secret_key
```

5. Run the application:
```bash
cd src
flask run --host=0.0.0.0 --port=8080
```

## Usage

1. **Upload Context Files**:
   - Upload EDC metadata (.csv)
   - Upload SDTM specification files (.xml)
   - Upload sample datasets (.csv, .xpt, .sas7bdat)

2. **Ask Questions**:
   - Request explanations about CDISC standards
   - Generate SQL code for data transformations
   - Get domain-specific guidance

3. **Use Domain Guide**:
   - Switch between SDTM and ADaM tabs
   - Click on domains for quick info
   - Use domain information in queries

## Features in Detail

### Context-Aware Assistance
The assistant uses uploaded files to provide more accurate and context-specific responses:
- EDC metadata for source-to-SDTM mappings
- SDTM specifications for compliance checking
- Sample data for realistic examples

### Code Generation
Generates production-ready code for:
- SDTM/ADaM transformations
- dbt models with proper configuration
- Complex derivations (e.g., RECIST criteria)
- Standard CDISC variable mappings

### Domain Guide
Interactive reference featuring:
- Core variables by domain
- Standard implementations
- Common mappings and derivations
- CDISC controlled terminology

## Project Structure

```
src/
├── app.py              # Main Flask application
├── cdisc_thesaurus.json # CDISC terminology and templates
├── sanitize.py         # Text sanitization utilities
├── utils.py           # Helper functions
├── static/            # Static assets
│   ├── chat.js       # Chat interface logic
│   ├── main.css      # Styling
│   └── images/       # UI images
├── templates/         # HTML templates
│   ├── index.html    # Main chat interface
│   └── welcome_template.html
└── data/             # Sample data and specs
    ├── terminology/  # CDISC controlled terminology
    └── sample_datasets/ # Example clinical data
```

## Development

### Adding New Features
1. Fork the repository
2. Create a feature branch
3. Implement changes
4. Submit a pull request

### Code Style
- Follow PEP 8 for Python code
- Use consistent formatting for JavaScript/CSS
- Document all functions and complex logic

## Security

- API keys are managed via environment variables
- User sessions are secure and isolated
- File uploads are validated and sanitized
- No PHI/PII should be uploaded

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with Google's Gemini API
- Uses CDISC standard specifications
- Incorporates Pharmaverse example datasets
- Built on Flask framework

## Support

For issues and feature requests, please use the GitHub issue tracker.