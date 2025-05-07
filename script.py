import os
import requests
import time
import sys
import yaml

# --- Script-level Defaults ---
DEFAULT_CHECK_INTERVAL_SECONDS = 300
DEFAULT_PUBLIC_IP_SERVICE_URL = "https://api.ipify.org?format=json"
DNS_CONFIG_FILE_PATH = '/app/config/dns_config.yml'
DEFAULT_CONFIG_TEMPLATE_PATH = '/app/dns_config.default.yml'

# --- Global Variables for Configuration ---
MIJNHOST_API_KEY = None
CHECK_INTERVAL_SECONDS = DEFAULT_CHECK_INTERVAL_SECONDS
PUBLIC_IP_SERVICE_URL = DEFAULT_PUBLIC_IP_SERVICE_URL
parsed_config_data = {} # To hold the entire loaded YAML for later writing

# --- Helper Functions ---
def log_message(message):
    """Prints a message to stdout, suitable for Docker logs."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}", flush=True)

def load_and_validate_config():
    """Loads configuration from YAML, validates it, and sets global config variables."""
    global parsed_config_data, CHECK_INTERVAL_SECONDS, PUBLIC_IP_SERVICE_URL, MIJNHOST_API_KEY

    MIJNHOST_API_KEY = os.environ.get('MIJNHOST_API_KEY')
    if not MIJNHOST_API_KEY:
        log_message("CRITICAL: MIJNHOST_API_KEY environment variable is required.")
        return None, None # Indicate fatal error

    _last_known_ip_yaml = None
    _domain_configs_yaml = []

    try:
        with open(DNS_CONFIG_FILE_PATH, 'r') as f:
            parsed_config_data = yaml.safe_load(f)
        
        if not parsed_config_data: # Handle empty file after it's found
            parsed_config_data = {'global_settings': {}, 'domains': []}
            log_message(f"INFO: Main config file '{DNS_CONFIG_FILE_PATH}' was found but empty or invalid. Initializing with default structure.")

    except FileNotFoundError:
        log_message(f"INFO: Main DNS configuration file '{DNS_CONFIG_FILE_PATH}' not found.")
        try:
            log_message(f"Attempting to create it from default template '{DEFAULT_CONFIG_TEMPLATE_PATH}'...")
            with open(DEFAULT_CONFIG_TEMPLATE_PATH, 'r') as f_default:
                default_content = f_default.read()
            
            # Ensure the target directory /app/config exists.
            # This is important because the volume mount might just be a file if ./config is a file on host.
            # However, docker-compose `volumes: - ./config:/app/config` should create /app/config if ./config is a dir.
            # For safety, especially if script is run outside Docker with similar paths, ensure dir.
            os.makedirs(os.path.dirname(DNS_CONFIG_FILE_PATH), exist_ok=True)

            with open(DNS_CONFIG_FILE_PATH, 'w') as f_target: # This creates/overwrites
                f_target.write(default_content)
            log_message(f"Default configuration successfully copied to '{DNS_CONFIG_FILE_PATH}'.")

            # Now that the file is created, load it for the current run
            with open(DNS_CONFIG_FILE_PATH, 'r') as f_newly_copied:
                parsed_config_data = yaml.safe_load(f_newly_copied)
            
            if not parsed_config_data: # If default template was empty or invalid YAML
                log_message(f"WARNING: Content copied from default to '{DNS_CONFIG_FILE_PATH}' was empty or invalid YAML. Initializing with empty structure.")
                parsed_config_data = {'global_settings': {}, 'domains': []}

        except FileNotFoundError:
            log_message(f"CRITICAL: Default configuration template '{DEFAULT_CONFIG_TEMPLATE_PATH}' also not found. Cannot create initial config. Initializing with empty structure.")
            parsed_config_data = {'global_settings': {}, 'domains': []}
        except IOError as e_io:
            log_message(f"CRITICAL: IO error while creating config from default template: {e_io}. Path: {DNS_CONFIG_FILE_PATH}. Initializing with empty structure.")
            parsed_config_data = {'global_settings': {}, 'domains': []}
        except yaml.YAMLError as e_yaml: # If the default content, once written and re-read, is bad
            log_message(f"CRITICAL: Error parsing YAML from newly copied default config '{DNS_CONFIG_FILE_PATH}': {e_yaml}. Initializing with empty structure.")
            parsed_config_data = {'global_settings': {}, 'domains': []}
        except Exception as e_fallback: # Catch-all for other unexpected errors
            log_message(f"CRITICAL: Unexpected error creating config from default template: {e_fallback}. Initializing with empty structure.")
            parsed_config_data = {'global_settings': {}, 'domains': []}
            
    except yaml.YAMLError as e: # This catches YAML errors from the initial attempt to read DNS_CONFIG_FILE_PATH
        log_message(f"CRITICAL: Error parsing YAML from '{DNS_CONFIG_FILE_PATH}': {e}")
        return None, None # Indicate fatal error
    except Exception as e:
        log_message(f"CRITICAL: Unexpected error loading config '{DNS_CONFIG_FILE_PATH}': {e}")
        return None, None


    # Ensure global_settings exists
    if 'global_settings' not in parsed_config_data or not isinstance(parsed_config_data.get('global_settings'), dict):
        parsed_config_data['global_settings'] = {}
        log_message(f"INFO: 'global_settings' section missing or invalid in '{DNS_CONFIG_FILE_PATH}'. Initializing.")

    gs = parsed_config_data['global_settings']
    _last_known_ip_yaml = gs.get('last_known_ip')
    _check_interval_yaml = gs.get('check_interval_seconds')
    _public_ip_url_yaml = gs.get('public_ip_service_url')

    # Determine final global settings (YAML > Default)
    try:
        CHECK_INTERVAL_SECONDS = int(_check_interval_yaml if _check_interval_yaml is not None else DEFAULT_CHECK_INTERVAL_SECONDS)
        if CHECK_INTERVAL_SECONDS <= 0:
            log_message(f"WARNING: check_interval_seconds ('{_check_interval_yaml}') must be positive. Using default: {DEFAULT_CHECK_INTERVAL_SECONDS}.")
            CHECK_INTERVAL_SECONDS = DEFAULT_CHECK_INTERVAL_SECONDS
    except (ValueError, TypeError):
        log_message(f"WARNING: Invalid check_interval_seconds ('{_check_interval_yaml}'). Using default: {DEFAULT_CHECK_INTERVAL_SECONDS}.")
        CHECK_INTERVAL_SECONDS = DEFAULT_CHECK_INTERVAL_SECONDS

    PUBLIC_IP_SERVICE_URL = str(_public_ip_url_yaml if _public_ip_url_yaml is not None else DEFAULT_PUBLIC_IP_SERVICE_URL)
    if not PUBLIC_IP_SERVICE_URL.startswith(('http://', 'https://')):
        log_message(f"WARNING: Invalid public_ip_service_url ('{_public_ip_url_yaml}'). Using default: {DEFAULT_PUBLIC_IP_SERVICE_URL}.")
        PUBLIC_IP_SERVICE_URL = DEFAULT_PUBLIC_IP_SERVICE_URL
    
    # Ensure domains list exists
    if 'domains' not in parsed_config_data or not isinstance(parsed_config_data.get('domains'), list):
        parsed_config_data['domains'] = []
        log_message(f"INFO: 'domains' list missing or invalid in '{DNS_CONFIG_FILE_PATH}'. Initializing.")
    
    _domain_configs_yaml = parsed_config_data['domains']
    
    valid_domain_configs = []
    for i, domain_entry in enumerate(_domain_configs_yaml):
        if not isinstance(domain_entry, dict) or not all(k in domain_entry for k in ("domain_name", "records")):
            log_message(f"WARNING: Domain entry at index {i} in '{DNS_CONFIG_FILE_PATH}' is invalid or missing 'domain_name'/'records'. Skipping.")
            continue
        if not isinstance(domain_entry.get('records'), list) or not domain_entry.get('records'):
            log_message(f"WARNING: 'records' for domain '{domain_entry.get('domain_name')}' must be a non-empty list. Skipping domain.")
            continue
        
        current_domain_name = str(domain_entry.get("domain_name","")).strip()
        if not current_domain_name:
            log_message(f"WARNING: Domain entry at index {i} has empty or missing 'domain_name'. Skipping.")
            continue

        valid_records_for_domain = []
        for j, record_item in enumerate(domain_entry['records']):
            if not isinstance(record_item, dict) or not all(k in record_item for k in ("name", "type", "ttl")):
                log_message(f"WARNING: Record (index {j}) for domain '{current_domain_name}' is invalid or missing keys (name, type, ttl). Skipping record.")
                continue
            
            record_name = str(record_item.get("name","")).strip()
            record_type = str(record_item.get("type","")).upper().strip()
            record_ttl_str = str(record_item.get("ttl","")).strip()

            if not record_name:
                 log_message(f"WARNING: Record (index {j}) for domain '{current_domain_name}' has empty or missing 'name'. Skipping record.")
                 continue
            if record_type not in ["A", "AAAA"]:
                log_message(f"WARNING: Record '{record_name}' for domain '{current_domain_name}' has invalid type '{record_type}'. Skipping record.")
                continue
            try:
                record_ttl = int(record_ttl_str)
                if record_ttl <= 0:
                    log_message(f"WARNING: Record '{record_name}' for domain '{current_domain_name}' TTL '{record_ttl}' must be positive. Skipping record.")
                    continue
            except ValueError:
                log_message(f"WARNING: Record '{record_name}' for domain '{current_domain_name}' TTL '{record_ttl_str}' is not a valid integer. Skipping record.")
                continue
            
            valid_records_for_domain.append({"name": record_name, "type": record_type, "ttl": record_ttl})
        
        if valid_records_for_domain:
            valid_domain_configs.append({"domain_name": current_domain_name, "records": valid_records_for_domain})
        else:
            log_message(f"INFO: No valid records found for domain '{current_domain_name}'.")

    if not valid_domain_configs:
        log_message("WARNING: No valid domains or records configured to manage after validation.")

    return _last_known_ip_yaml, valid_domain_configs

def cache_ip_in_yaml(ip_address):
    """Saves the current IP and effective global settings back to the YAML config file."""
    global parsed_config_data, CHECK_INTERVAL_SECONDS, PUBLIC_IP_SERVICE_URL
    if not parsed_config_data: # Should have been initialized by load_and_validate_config
        log_message("ERROR: Cannot cache IP. Configuration data structure not initialized.")
        # Attempt to re-initialize to prevent crash on write, though this indicates a logic flaw if reached.
        parsed_config_data = {'global_settings': {}, 'domains': []}


    # Ensure global_settings dictionary exists
    if 'global_settings' not in parsed_config_data or not isinstance(parsed_config_data['global_settings'], dict):
        parsed_config_data['global_settings'] = {}
        
    gs = parsed_config_data['global_settings']
    gs['last_known_ip'] = ip_address
    gs['check_interval_seconds'] = CHECK_INTERVAL_SECONDS
    gs['public_ip_service_url'] = PUBLIC_IP_SERVICE_URL
    
    try:
        # Ensure domains list is preserved even if it was empty or became empty after validation
        if 'domains' not in parsed_config_data or not isinstance(parsed_config_data.get('domains'),list):
             parsed_config_data['domains'] = []


        with open(DNS_CONFIG_FILE_PATH, 'w') as f:
            yaml.dump(parsed_config_data, f, sort_keys=False, default_flow_style=False, indent=2)
        log_message(f"IP address {ip_address} and current settings cached to {DNS_CONFIG_FILE_PATH}")
    except IOError as e:
        log_message(f"ERROR: Could not write to config file {DNS_CONFIG_FILE_PATH}: {e}")
    except yaml.YAMLError as e:
        log_message(f"ERROR: Could not format data for YAML storage: {e}")
    except Exception as e:
        log_message(f"ERROR: Unexpected error writing to YAML: {e}")


def get_public_ip():
    log_message(f"Fetching public IP from {PUBLIC_IP_SERVICE_URL}...")
    try:
        response = requests.get(PUBLIC_IP_SERVICE_URL, timeout=10)
        response.raise_for_status()
        # Assuming the service returns JSON with an 'ip' key
        ip_address = response.json().get('ip')
        if not ip_address:
            log_message(f"ERROR: 'ip' key not found or empty in response from {PUBLIC_IP_SERVICE_URL}. Response: {response.text}")
            return None
        log_message(f"Current public IP: {ip_address}")
        return ip_address
    except requests.exceptions.RequestException as e:
        log_message(f"ERROR: Could not fetch public IP from {PUBLIC_IP_SERVICE_URL}: {e}")
    except requests.exceptions.JSONDecodeError:
        log_message(f"ERROR: Response from {PUBLIC_IP_SERVICE_URL} was not valid JSON: {response.text}")
    except Exception as e:
        log_message(f"ERROR: Unexpected error fetching public IP: {e}")
    return None

def update_dns_record(ip_address, domain_name_param, record_name, record_type, record_ttl):
    api_url = f"https://mijn.host/api/v2/domains/{domain_name_param}/dns"
    
    if record_name == "@" or not record_name: # Allow empty name to default to "@"
        fqdn_record_name = f"{domain_name_param}."
        display_name = "@"
    else:
        fqdn_record_name = f"{record_name}.{domain_name_param}."
        display_name = record_name

    headers = {
        'API-Key': MIJNHOST_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'DockerDDNSClient-MijnHost/2.0.0' # Version bump
    }
    payload = {
        "record": {
            "type": record_type,
            "name": fqdn_record_name, # API expects FQDN with trailing dot
            "value": ip_address,
            "ttl": record_ttl
        }
    }
    
    log_message(f"Attempting to update DNS record {display_name}.{domain_name_param} to {ip_address} (Type: {record_type}, TTL: {record_ttl})")
    
    try:
        # Using PATCH as per mijn.host API v2 for creating/updating
        response = requests.patch(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status() 
        # Log more useful info from response if available
        try:
            response_json = response.json()
            log_message(f"DNS update successful for {display_name}.{domain_name_param}. Response: {response_json}")
        except requests.exceptions.JSONDecodeError:
            log_message(f"DNS update successful for {display_name}.{domain_name_param}. Status: {response.status_code}")
        return True
    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP error during DNS update for {display_name}.{domain_name_param}: {http_err}"
        try:
            # Attempt to get more detailed error from API response
            error_details = http_err.response.json()
            error_message += f" - Details: {error_details}"
        except (requests.exceptions.JSONDecodeError, AttributeError):
            if hasattr(http_err.response, 'text'):
                 error_message += f" - Response content: {http_err.response.text}"
        log_message(error_message)
    except requests.exceptions.RequestException as e:
        log_message(f"Network/Request error during DNS update for {display_name}.{domain_name_param}: {e}")
    except Exception as e:
        log_message(f"Unexpected error during DNS update for {display_name}.{domain_name_param}: {e}")
    return False

# --- Main Execution Logic ---
if __name__ == "__main__":
    log_message("DDNS Client for mijn.host started (YAML configuration with mtime check).")

    # --- Initial Configuration Load ---
    # These variables will hold the state from the config file
    cached_ip_from_config, domain_configurations = load_and_validate_config() # This updates globals like MIJNHOST_API_KEY

    if MIJNHOST_API_KEY is None:
        log_message("CRITICAL: MIJNHOST_API_KEY environment variable is not set on startup. Exiting.")
        sys.exit(1)
    
    # Store initial modification time
    try:
        dns_config_last_modified_time = os.path.getmtime(DNS_CONFIG_FILE_PATH)
    except OSError:
        log_message(f"INFO: DNS configuration file '{DNS_CONFIG_FILE_PATH}' not found on startup or error accessing it. Will attempt to load if created.")
        dns_config_last_modified_time = 0 # Treat as if it's very old or non-existent

    log_message(f"Initial effective check interval: {CHECK_INTERVAL_SECONDS} seconds.")
    log_message(f"Initial effective public IP service URL: {PUBLIC_IP_SERVICE_URL}.")
    log_message(f"DNS configuration file: {DNS_CONFIG_FILE_PATH}")

    if cached_ip_from_config:
        log_message(f"Initial last known IP from config: {cached_ip_from_config}")
    else:
        log_message("No last known IP in config initially or config not found; will fetch and update if needed.")

    if not domain_configurations:
        log_message("WARNING: No domains configured initially. Script will run and can cache IP, but won't update DNS records until domains are added to config.")

    while True:
        # --- Check if config file has been modified ---
        current_mtime = None
        try:
            current_mtime = os.path.getmtime(DNS_CONFIG_FILE_PATH)
        except OSError: # File might have been deleted or is inaccessible
            if dns_config_last_modified_time is not None and dns_config_last_modified_time != 0 : # It existed before
                log_message(f"WARNING: DNS configuration file '{DNS_CONFIG_FILE_PATH}' is no longer accessible or has been deleted. Using last known configuration or defaults.")
            # If file never existed or was marked as 0, no new message needed here.
            dns_config_last_modified_time = 0 # Mark as needing load if it reappears or becomes accessible

        if current_mtime is not None and current_mtime != dns_config_last_modified_time:
            log_message(f"Change detected in '{DNS_CONFIG_FILE_PATH}'. Reloading configuration.")
            # Reload config and update globals
            cached_ip_from_config, domain_configurations = load_and_validate_config()
            dns_config_last_modified_time = current_mtime # Update mtime after successful load

            if MIJNHOST_API_KEY is None: # Check if API key became unset after reload
                log_message("CRITICAL: MIJNHOST_API_KEY is no longer set after config reload. Waiting before retry.")
                time.sleep(DEFAULT_CHECK_INTERVAL_SECONDS) # Use a default safe interval
                continue # Restart loop to try reloading

            if domain_configurations is None: # Critical YAML/file error during reload
                log_message("CRITICAL: Failed to load or validate configuration after detected change. Retrying after interval.")
                # Use CHECK_INTERVAL_SECONDS which would be the last valid one, or default if never valid.
                time.sleep(CHECK_INTERVAL_SECONDS if CHECK_INTERVAL_SECONDS > 0 else DEFAULT_CHECK_INTERVAL_SECONDS)
                continue # Restart loop
            
            log_message(f"Config reloaded. Current check interval: {CHECK_INTERVAL_SECONDS}s. IP Service: {PUBLIC_IP_SERVICE_URL}")
            if not domain_configurations:
                log_message("WARNING: No domains configured to manage after reload.")
        
        # --- Get current public IP ---
        current_public_ip = get_public_ip()
        
        if current_public_ip:
            if current_public_ip != cached_ip_from_config:
                log_message(f"Public IP ('{current_public_ip}') differs from IP in config ('{cached_ip_from_config if cached_ip_from_config else 'N/A'}'). Update required.")
                
                if not domain_configurations:
                    log_message("IP changed, but no domains configured. Caching new IP.")
                    cache_ip_in_yaml(current_public_ip)
                    cached_ip_from_config = current_public_ip # Update in-memory cache
                else:
                    all_updates_successful_for_new_ip = True
                    for domain_config in domain_configurations:
                        domain_name = domain_config['domain_name']
                        log_message(f"Processing updates for domain: {domain_name}")
                        for record in domain_config['records']:
                            if not update_dns_record(current_public_ip, domain_name, record['name'], record['type'], record['ttl']):
                                all_updates_successful_for_new_ip = False
                                # Continue trying other records/domains even if one fails
                    
                    if all_updates_successful_for_new_ip:
                        log_message(f"All DNS updates successful for new IP {current_public_ip}. Caching IP.")
                        cache_ip_in_yaml(current_public_ip)
                        cached_ip_from_config = current_public_ip # Update in-memory cache
                    else:
                        log_message(f"One or more DNS updates failed for new IP {current_public_ip}. IP will not be cached. Will retry next cycle.")
            else:
                log_message(f"Public IP ({current_public_ip}) matches IP in config. No DNS update needed.")
        else:
            log_message("Could not determine public IP. Skipping DNS update check for this cycle.")
            
        # CHECK_INTERVAL_SECONDS would have been updated if config was reloaded
        log_message(f"Waiting for {CHECK_INTERVAL_SECONDS} seconds before next check...")
        time.sleep(CHECK_INTERVAL_SECONDS)
