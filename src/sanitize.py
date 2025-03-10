def sanitize_text(text):
    """Simple function to sanitize text with [object Object] issues"""
    if not text:
        return ""
    
    # Replace [object Object] with a more reasonable string
    return text.replace('[object Object]', '')
