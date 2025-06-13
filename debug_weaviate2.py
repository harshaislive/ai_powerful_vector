import sys
sys.path.append('.')
from services.weaviate_service import WeaviateService
from config import config
import json

# Initialize Weaviate service
weaviate_service = WeaviateService()

# Test direct UUID access
test_uuid = "0002752b-7be7-4133-a271-c4553cb19c10"

try:
    # Try to get object directly by UUID
    result = weaviate_service.client.data_object.get_by_id(test_uuid, class_name="DropboxFile")
    print("Direct UUID access result:")
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f"Direct UUID access failed: {e}")

# Alternative: Try to get by UUID using get query
try:
    result = weaviate_service.client.data_object.get(test_uuid, class_name="DropboxFile")
    print("\nAlternative UUID access result:")
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f"Alternative UUID access failed: {e}") 