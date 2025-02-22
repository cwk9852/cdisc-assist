# Script to extract sample datasets from R packages
# Required packages
library(admiral)
library(tools)

# Create output directory if it doesn't exist
output_dir <- "extracted_datasets"
dir.create(output_dir, showWarnings = FALSE)

# Function to extract and save datasets from a package
extract_package_datasets <- function(package_name) {
  # Get all datasets in the package
  datasets <- data(package = package_name)$results[, "Item"]
  
  if(length(datasets) > 0) {
    # Create package-specific subdirectory
    pkg_dir <- file.path(output_dir, package_name)
    dir.create(pkg_dir, showWarnings = FALSE)
    
    # Extract and save each dataset
    for(dataset in datasets) {
      # Load the dataset into environment
      data(list = dataset, package = package_name, envir = environment())
      
      # Get the actual dataset object
      dataset_obj <- get(dataset)
      
      if(is.data.frame(dataset_obj)) {
        # Create output filename
        output_file <- file.path(pkg_dir, paste0(dataset, ".csv"))
        
        # Write to CSV
        write.csv(dataset_obj, output_file, row.names = FALSE)
        cat(sprintf("Saved %s from package %s\n", dataset, package_name))
      }
    }
  } else {
    cat(sprintf("No datasets found in package %s\n", package_name))
  }
}

# List of packages to process
packages <- c("admiral", "pharmaverseadam", "pharmaversesdtm")

# Process each package
for(pkg in packages) {
  tryCatch({
    if(requireNamespace(pkg, quietly = TRUE)) {
      cat(sprintf("\nProcessing package: %s\n", pkg))
      extract_package_datasets(pkg)
    } else {
      cat(sprintf("\nPackage %s is not installed\n", pkg))
    }
  }, error = function(e) {
    cat(sprintf("\nError processing package %s: %s\n", pkg, e$message))
  })
}

cat("\nDataset extraction complete. Files saved in:", normalizePath(output_dir), "\n")