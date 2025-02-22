"""
CDISC data collector for DM domain knowledge 
Collects and caches data locally to avoid repeated API calls
"""
import logging
import os
from pathlib import Path
import json
import requests
from datetime import datetime
from typing import Dict, Optional, List, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CDISCDataCollector:
    def __init__(self, cache_dir: str = "data/cdisc"):
        self.api_base_url = "https://library.cdisc.org/api"
        self.api_key = os.environ["CDISC_API_KEY"]
        self.formats = {
            "json": "application/json",
            "xml": "application/xml", 
            "csv": "text/csv",
            "excel": "application/vnd.ms-excel"
        }
        # Create absolute path for cache directory
        self.cache_dir = Path(cache_dir).resolve()
        self.models_dir = self.cache_dir / "models"
        self.igs_dir = self.cache_dir / "implementation_guides" 
        self.terminology_dir = self.cache_dir / "terminology"
        
        # Create all directory structures
        for dir in [self.cache_dir, self.models_dir, self.igs_dir, self.terminology_dir]:
            dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created/verified directory: {dir}")
            
        self.products_data = None
        self.max_workers = 5

    def _make_api_request(self, endpoint: str, accept_format: str = "application/json") -> Dict:
        """Make request to CDISC Library API with error handling"""
        try:
            url = endpoint if endpoint.startswith("http") else f"{self.api_base_url}{endpoint}"
            headers = {
                "api-key": self.api_key,
                "Accept": accept_format
            }
            logger.info(f"Making API request to: {url}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            if accept_format == "application/json":
                return response.json()
            return response.content
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.error(f"Resource not found: {endpoint}")
            elif e.response.status_code == 401:
                logger.error("Authentication failed. Check CDISC API key")
            elif e.response.status_code == 403:
                logger.error("Not authorized to access this resource") 
            else:
                logger.error(f"HTTP error occurred: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making API request: {e}")
            raise

    def _get_cache_path(self, category: str, data_type: str, version: str, fmt: str = "json") -> Path:
        """
        Get path for cached data with explicit organization
        
        Args:
            category: Top level category (models, implementation_guides, terminology)
            data_type: Type of data (sdtm, adam, etc)
            version: Version string
            fmt: File format extension
        """
        timestamp = datetime.now().strftime("%Y%m%d")
        
        # Select appropriate base directory
        if category == "models":
            base_dir = self.models_dir
        elif category == "implementation_guides":
            base_dir = self.igs_dir
        elif category == "terminology":
            base_dir = self.terminology_dir
        else:
            base_dir = self.cache_dir
            
        # Create type-specific subdirectory
        type_dir = base_dir / data_type
        type_dir.mkdir(exist_ok=True)
            
        # For IGs, append _ig to avoid name collisions with model files
        if category == "implementation_guides":
            return type_dir / f"{data_type}_ig_v{version}_{timestamp}.{fmt}"
        
        return type_dir / f"{data_type}_v{version}_{timestamp}.{fmt}"

    def _save_to_cache(self, data: Dict, category: str, data_type: str, version: str, fmt: str = "json") -> Path:
        """
        Save data to cache with explicit organization and return saved path
        """
        cache_path = self._get_cache_path(category, data_type, version, fmt)
        mode = "wb" if isinstance(data, bytes) else "w"
        
        try:
            with open(cache_path, mode) as f:
                if isinstance(data, (dict, list)) and fmt == "json":
                    json.dump(data, f, indent=2)
                else:
                    f.write(data)
            logger.info(f"Successfully saved {data_type} v{version} data as {fmt} to: {cache_path}")
            return cache_path
        except Exception as e:
            logger.error(f"Failed to save {data_type} v{version} data: {e}")
            raise

    def _get_products_data(self, force_refresh: bool = False) -> Dict:
        """Get products data from CDISC Library API"""
        if not self.products_data or force_refresh:
            try:
                self.products_data = self._make_api_request("/mdr/products")
                products_path = self._save_to_cache(
                    self.products_data, 
                    "products", 
                    "products", 
                    "latest"
                )
                logger.info(f"Successfully retrieved and cached products data to: {products_path}")
            except Exception as e:
                logger.error(f"Failed to retrieve products data: {e}")
                raise
        return self.products_data

    def collect_model_data(self, model_type: str = "sdtm", version: str = "1-2", 
                          format: str = "json", force_refresh: bool = False) -> Dict:
        """
        Collect model data for specified version
        Args:
            model_type: Type of model ("sdtm", "adam", etc)
            version: Version string (e.g. "1-2" for 1.2)
            format: Output format ("json", "xml", "csv", "excel")
            force_refresh: Force refresh of products data from API
        """
        try:
            # Get products data from API
            products = self._get_products_data(force_refresh)
            
            # Navigate to appropriate section based on model type
            if model_type == "sdtm":
                tab_section = products.get("_links", {}).get("data-tabulation", {})
                model_links = tab_section.get("_links", {}).get("sdtm", [])
                ig_links = tab_section.get("_links", {}).get("sdtmig", [])
            elif model_type == "adam":
                analysis_section = products.get("_links", {}).get("data-analysis", {})
                model_links = analysis_section.get("_links", {}).get("adam", [])
                ig_links = analysis_section.get("_links", {}).get("adamig", [])
            else:
                raise ValueError(f"Unsupported model type: {model_type}")

            # Find requested version in models
            model_href = None
            model_data = None
            for link in model_links:
                if version in link.get("href", ""):
                    model_href = link["href"]
                    model_data = link
                    break

            if not model_href:
                raise Exception(f"Version {version} not found for {model_type}")

            # Get the model content in requested format
            accept_format = self.formats.get(format, self.formats["json"])
            model_content = self._make_api_request(model_href, accept_format)

            # Find matching IGs
            matching_igs = []
            for ig in ig_links:
                # Look for IGs that are associated with this version
                if version in ig.get("title", "").lower():
                    matching_igs.append(ig)
            
            collected_data = {
                "model": model_content,
                "model_metadata": model_data,
                "implementation_guides": matching_igs,
                "metadata": {
                    "collection_date": datetime.now().isoformat(),
                    "model_type": model_type,
                    "version": version,
                    "format": format
                }
            }
            
            # Cache results
            self._save_to_cache(collected_data, f"{model_type}_v{version}", format)
            logger.info(f"Successfully collected {model_type} v{version} model data")
            
            return collected_data
            
        except Exception as e:
            logger.error(f"Failed to collect {model_type} model data: {e}")
            raise

    def _get_model_links(self, products: Dict, model_type: str) -> tuple[List, List]:
        """Get model and IG links from products data based on model type"""
        if model_type == "sdtm":
            # SDTM models are under data-tabulation
            tab_section = products.get("_links", {}).get("data-tabulation", {})
            models = tab_section.get("_links", {}).get("sdtm", [])
            igs = tab_section.get("_links", {}).get("sdtmig", [])
            
        elif model_type == "adam":
            # ADaM models are under data-analysis
            analysis_section = products.get("_links", {}).get("data-analysis", {})
            models = analysis_section.get("_links", {}).get("adam", [])
            igs = analysis_section.get("_links", {}).get("adamig", [])
            
        elif model_type == "cdash":
            # CDASH models are under data-collection
            collection_section = products.get("_links", {}).get("data-collection", {})
            models = collection_section.get("_links", {}).get("cdash", [])
            igs = collection_section.get("_links", {}).get("cdashig", [])
            
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
            
        return models or [], igs or []

    def _get_version_from_title(self, title: str) -> str:
        """Extract version from title string"""
        if not title:
            return ""
        # Handle various version formats:
        # "Study Data Tabulation Model Version 1.2"
        # "ADaM Implementation Guide Version 1.1"
        # "SDTM Implementation Guide: Human Clinical Trials Version 3.1.2 (Final)"
        try:
            if "Version" in title:
                version = title.split("Version")[-1].strip()
                # Remove any "(Final)" or other suffixes
                version = version.split("(")[0].strip()
                # Convert format like "1.2" to "1-2"
                return version.replace(".", "-")
        except Exception as e:
            logger.warning(f"Failed to extract version from title '{title}': {e}")
        return ""

    def _process_resource(self, resource_type: str, resource: Dict, formats: List[str], category: str) -> tuple:
        """Process a single resource and return success status, data, and saved paths"""
        version = self._get_version_from_title(resource.get("title"))
        href = resource.get("href")
        if not href or not version:
            return False, None, []

        resource_data = {}
        paths = []
        success = False
        for fmt in formats:
            try:
                accept_format = self.formats.get(fmt)
                content = self._make_api_request(href, accept_format)
                resource_data[fmt] = content

                # Save each format separately
                saved_path = self._save_to_cache(
                    content,
                    category,
                    resource_type,
                    version,
                    fmt
                )
                paths.append(str(saved_path))
                success = True

            except Exception as e:
                logger.error(f"Failed to collect {resource_type.upper()} v{version} in {fmt}: {e}")

        return success, resource_data, paths

    def _process_resource_batch(self, resources: List[Dict], resource_type: str, category: str, formats: List[str]) -> List[tuple]:
        """Process a batch of resources in parallel"""
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for resource in resources:
                future = executor.submit(
                    self._process_resource,
                    resource_type=resource_type,
                    resource=resource,
                    formats=formats,
                    category=category
                )
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    success, data, paths = future.result()
                    if success:
                        results.append((data, paths))
                except Exception as e:
                    logger.error(f"Error processing resource: {e}")
                    
        return results

    def collect_all_resources(self, formats: List[str] = ["json"]) -> Dict[str, Any]:
        """
        Collect all available CDISC Library resources including models, IGs and terminology
        Uses parallel processing to speed up collection
        
        Args:
            formats: List of formats to collect in (e.g. ["json", "xml", "csv"])
        """
        try:
            # Get products data from API 
            products = self._get_products_data(force_refresh=True)
            
            collected = {
                "models": {},
                "implementation_guides": {},
                "terminology": {},
                "metadata": {
                    "collection_date": datetime.now().isoformat(),
                    "formats": formats,
                    "output_directories": {
                        "base": str(self.cache_dir),
                        "models": str(self.models_dir),
                        "implementation_guides": str(self.igs_dir),
                        "terminology": str(self.terminology_dir)
                    }
                }
            }

            saved_files = {
                "models": {},
                "implementation_guides": {},
                "terminology": {}
            }

            # Process model types in parallel batches
            model_batches = []
            for model_type in ["sdtm", "adam", "cdash"]:
                logger.info(f"\nProcessing {model_type.upper()} resources...")
                model_links, ig_links = self._get_model_links(products, model_type)
                
                saved_files["models"][model_type] = []
                saved_files["implementation_guides"][model_type] = []
                collected["models"][model_type] = {}
                collected["implementation_guides"][model_type] = {}

                if model_links:
                    model_batches.append((model_links, model_type, "models"))
                if ig_links:
                    model_batches.append((ig_links, model_type, "implementation_guides"))

            # Process all model batches in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                batch_futures = []
                for resources, resource_type, category in model_batches:
                    future = executor.submit(
                        self._process_resource_batch,
                        resources,
                        resource_type,
                        category,
                        formats
                    )
                    batch_futures.append((future, resource_type, category))

                # Collect results as they complete
                for future, resource_type, category in batch_futures:
                    try:
                        results = future.result()
                        for data, paths in results:
                            if category == "models":
                                collected["models"][resource_type].update(data)
                                saved_files["models"][resource_type].extend(paths)
                            else:
                                collected["implementation_guides"][resource_type].update(data)
                                saved_files["implementation_guides"][resource_type].extend(paths)
                    except Exception as e:
                        logger.error(f"Error processing batch {resource_type} {category}: {e}")

            # Process terminology packages in parallel
            term_section = products.get("_links", {}).get("terminology", {})
            if term_section:
                term_packages = term_section.get("_links", {}).get("packages", [])
                saved_files["terminology"] = {}

                # Group terminology packages by type
                term_batches = {}
                for package in term_packages:
                    title = package.get("title", "")
                    if not title or len(title.split()) < 4:
                        continue
                        
                    pkg_type = title.split()[0].lower()
                    if pkg_type not in term_batches:
                        term_batches[pkg_type] = []
                        saved_files["terminology"][pkg_type] = []
                        collected["terminology"][pkg_type] = {}
                    term_batches[pkg_type].append(package)

                # Process terminology batches in parallel
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    term_futures = []
                    for pkg_type, packages in term_batches.items():
                        future = executor.submit(
                            self._process_resource_batch,
                            packages,
                            pkg_type,
                            "terminology",
                            formats
                        )
                        term_futures.append((future, pkg_type))

                    # Collect terminology results
                    for future, pkg_type in term_futures:
                        try:
                            results = future.result()
                            for data, paths in results:
                                collected["terminology"][pkg_type].update(data)
                                saved_files["terminology"][pkg_type].extend(paths)
                        except Exception as e:
                            logger.error(f"Error processing terminology batch {pkg_type}: {e}")

            # Save collection manifest
            manifest = {
                "collection_date": datetime.now().isoformat(),
                "saved_files": saved_files,
                "metadata": collected["metadata"]
            }
            
            manifest_path = self._save_to_cache(
                manifest,
                "collection_manifest",
                "manifest",
                datetime.now().strftime("%Y%m%d"),
                "json"
            )
            
            logger.info(f"\nCollection complete. Manifest saved to: {manifest_path}")
            logger.info("\nFiles were saved to:")
            for category, type_dict in saved_files.items():
                if type_dict:
                    logger.info(f"\n{category.upper()}:")
                    for data_type, files in type_dict.items():
                        if files:
                            logger.info(f"  {data_type}: {len(files)} files")
                            logger.info(f"    Directory: {self.cache_dir / category / data_type}")
            
            return collected

        except Exception as e:
            logger.error(f"Failed to collect all resources: {e}")
            raise

def main():
    """Collect all CDISC Library resources"""
    # Create collector with explicit cache directory
    cache_dir = Path(__file__).parent.parent / "data" / "cdisc"
    collector = CDISCDataCollector(str(cache_dir))
    
    try:
        logger.info(f"Starting collection with cache directory: {cache_dir}")
        data = collector.collect_all_resources(formats=["json", "xml", "csv"])
        
        # Summary already logged in collect_all_resources
        
    except Exception as e:
        logger.error(f"Collection failed: {e}")

if __name__ == "__main__":
    main()