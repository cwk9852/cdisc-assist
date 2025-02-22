import os
import fnmatch
import re

def find_files(directory, pattern):
    """Lists files in a directory (and its subdirectories) that match a given pattern."""
    matches = []
    for root, dirnames, filenames in os.walk(directory):
        for filename in fnmatch.filter(filenames, pattern):
            matches.append(os.path.join(root, filename))
    return matches

def get_file_version(filename):
    """Extracts a version number (e.g., '2-1') from a filename using regex."""
    match = re.search(r'v(\d+-\d+)', filename, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def get_file_type(filename):
  """Returns the filetype based on the suffix"""
  match = re.search(r'.(csv|xml|json)$', filename, re.IGNORECASE)
  if match:
        return match.group(1)
  return None

def sort_files_by_version(files):
    """Sorts files based on their version and returns the sorted list and list of XML files."""
    # Helper function to convert version string to a tuple of integers
    def version_to_tuple(version):
        try:
            parts = version.split('-')
            return tuple(map(int, parts))
        except:
            return None

    # Extract filename and version and put in a list
    file_list = []
    for filename in files:
        version = get_file_version(filename)
        if version:
          file_list.append([filename, version_to_tuple(version)])
    # Remove elements that didn't match the correct values

    file_list = [item for item in file_list if item[1] != None]
    #Sort
    file_list = sorted(file_list, key=lambda x: x[1])
    sorted_files = [item[0] for item in file_list]

    # Finally, get the last
    xml_files = [item for item in sorted_files if item.endswith(".xml")]
    return xml_files, sorted_files