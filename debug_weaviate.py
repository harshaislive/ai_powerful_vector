import sys
sys.path.append('.')
from services.weaviate_service import WeaviateService
from config import config
import json

# Initialize Weaviate service
weaviate_service = WeaviateService()

# Get a few sample records to see the structure
result = weaviate_service.client.query.get('DropboxFile', ['dropbox_path', 'file_name', 'file_type']).with_additional(['id']).with_limit(3).do()

print('Sample records from Weaviate:')
print(json.dumps(result, indent=2))

# Test the get_file_by_id method
files = result.get("data", {}).get("Get", {}).get("DropboxFile", [])
if files:
    first_file = files[0]
    file_id = first_file.get("_additional", {}).get("id", "")
    print(f"\nTesting get_file_by_id with ID: {file_id}")
    
    file_data = weaviate_service.get_file_by_id(file_id)
    print(f"Result: {json.dumps(file_data, indent=2)}") 