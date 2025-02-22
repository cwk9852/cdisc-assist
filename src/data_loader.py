import pandas as pd
import xml.etree.ElementTree as ET
import json
import utils

ONCOLOGY_DOMAINS = {
    'TU': 'Tumor Identification',
    'TR': 'Tumor Results',
    'RS': 'Disease Response',
    'EX': 'Exposure',
    'DD': 'Death Details',
    'DS': 'Disposition',
    'AE': 'Adverse Events',
    'CM': 'Concomitant Medications'
}

def load_edc_metadata(csv_file):
    """Loads EDC metadata from a CSV file into a pandas DataFrame with oncology focus."""
    try:
        df = pd.read_csv(csv_file)
        # Add oncology domain classification if possible
        if 'form_name' in df.columns:
            df['domain_guess'] = df['form_name'].apply(lambda x: next(
                (domain for domain, desc in ONCOLOGY_DOMAINS.items()
                 if any(keyword in x.lower()
                        for keyword in [domain.lower(), desc.lower()])), None))
        print(f"Successfully loaded EDC metadata from {csv_file}")
        return df
    except FileNotFoundError:
        print(f"Error: EDC metadata file not found at {csv_file}")
        return None
    except Exception as e:
        print(f"Error loading EDC metadata: {e}")
        return None

def extract_sdtm_variable_info(xml_file):
    """Extracts SDTM variable information focusing on oncology domains."""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        variable_info = []

        # Focus on oncology-relevant domains
        for domain in ONCOLOGY_DOMAINS.keys():
            domain_vars = root.findall(f".//datasetVariable[./domain='{domain}']")
            for item in domain_vars:
                variable = {
                    'domain': domain.strip(),
                    'name': item.find("name").text.strip() if item.find("name") is not None else None,
                    'label': item.find("label").text.strip() if item.find("label") is not None else None,
                    'definition': item.find("definition").text.strip() if item.find("definition") is not None else None,
                    'core': item.find("core").text.strip() if item.find("core") is not None else None,
                    'datatype': item.find("datatype").text.strip() if item.find("datatype") is not None else None
                }
                variable_info.append(variable)

        print(f"Successfully extracted oncology SDTM metadata from {xml_file}")
        return variable_info
    except FileNotFoundError:
        return "Error: File not found."
    except Exception as e:
        return f"An error occurred: {e}"

def load_sdtm_terminology(json_file):
    """Loads SDTM controlled terminology from a JSON file."""
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        print(f"Successfully loaded SDTM terminology from {json_file}")
        return data
    except FileNotFoundError:
        print(f"Error: SDTM terminology file not found at {json_file}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {json_file}")
        return None

def extract_column_information(edc_df_xml):
    for path in edc_df_xml:
        type = utils.get_file_type(path)

        if "csv" in type: #loading csv
            print (f"The file is  the type {type} of data")
            edc_df = pd.read_csv(path)
            list_of_columns = edc_df.columns
            return list_of_columns
        elif "xml" in type: #xml
            print ("It is an xml I'm not quite sure what we can do with that yet")
        elif "json" in type: # json
            print ("Json type doesn't exist")

        else:
            return None

def load_data(files):
    file_text = []
    edc_metadata = {}
    sdtm_info = {}

    for path in files:
        type = utils.get_file_type(path)

        if type == "csv":
            print(f"Loading CSV file: {path}")
            try:
                edc_df = pd.read_csv(path)
                edc_metadata = {
                    'columns': list(edc_df.columns),
                    'forms': edc_df['form_name'].unique().tolist() if 'form_name' in edc_df.columns else [],
                    'fields': edc_df['field_name'].unique().tolist() if 'field_name' in edc_df.columns else []
                }
                file_text.append(f"EDC Structure: {json.dumps(edc_metadata, indent=2)}")
            except Exception as e:
                print(f"Error loading CSV file {path}: {e}")
                continue

        elif type == "xml":
            print(f"Loading XML file: {path}")
            data = extract_sdtm_variable_info(path)

            if isinstance(data, list):
                try:
                    # Group SDTM variables by domain
                    domain_variables = {}
                    for var in data:
                        domain = var.get('domain', 'UNKNOWN')
                        if domain not in domain_variables:
                            domain_variables[domain] = []
                        domain_variables[domain].append({
                            'name': var.get('name'),
                            'label': var.get('label'),
                            'core': var.get('core')
                        })

                    sdtm_info = domain_variables
                    file_text.append(f"SDTM Structure: {json.dumps(domain_variables, indent=2)}")
                except Exception as e:
                    print(f"Error processing XML data from {path}: {e}")
                    continue
            else:
                print(f"Failed to extract data from XML file {path}: {data}")

        elif type == "json":
            print(f"JSON file type processing not implemented: {path}")
        else:
            print(f"Unsupported file type for {path}")

    return file_text if file_text else None

def extract_table_metadata(metadata_snapshot_file):
    """
    Extracts table names, descriptions, and column definitions from an EDC metadata file.
    """
    table_metadata = []
    try:
        df = pd.read_csv(metadata_snapshot_file)
        df.fillna('', inplace=True)  # Replace NaN with empty string for easier processing
    except Exception as e:
        print(f"Failed to load EDC metadata: {e}")
        return None

    # Iterate through each unique viewname (table) in the dataframe
    for table in df['viewname'].unique():
        table_df = df[df['viewname'] == table]
        table_description = table_df['varlabel'].iloc[0]  # Get the label from the description
        columns = []
        # For every column in the view
        for index, row in table_df.iterrows():
            # Check if the column appears to define demographics information
            column_name = row['varname']
            column_description = row['varlabel']
            column_type = row['vartype']
            columns.append({
                'column_name': column_name,
                'description': column_description,
                'data_type': column_type,
            })

        table_metadata.append({
            'table_name': table,
            'table_description': table_description,
            'columns': columns
        })
    return table_metadata