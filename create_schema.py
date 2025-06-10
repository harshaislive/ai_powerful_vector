#!/usr/bin/env python3
"""
Standalone script to create or reset Weaviate schema
"""
import os
import sys
from dotenv import load_dotenv
import weaviate

load_dotenv()

def create_weaviate_schema():
    """Create the Weaviate schema for DropboxFile class"""
    
    # Initialize Weaviate client
    weaviate_url = os.getenv("WEAVIATE_URL")
    weaviate_api_key = os.getenv("WEAVIATE_API_KEY")
    
    if not weaviate_url:
        print("Error: WEAVIATE_URL not found in environment variables")
        return False
    
    print(f"Connecting to Weaviate at: {weaviate_url}")
    
    try:
        if weaviate_api_key:
            auth_config = weaviate.AuthApiKey(api_key=weaviate_api_key)
            client = weaviate.Client(
                url=weaviate_url,
                auth_client_secret=auth_config
            )
            print("✅ Connected with API key authentication")
        else:
            client = weaviate.Client(url=weaviate_url)
            print("✅ Connected without authentication")
        
        # Check if schema already exists
        existing_schema = client.schema.get()
        existing_classes = [cls["class"] for cls in existing_schema.get("classes", [])]
        
        if "DropboxFile" in existing_classes:
            print("⚠️ DropboxFile class already exists. Deleting it first...")
            client.schema.delete_class("DropboxFile")
            print("✅ Deleted existing DropboxFile class")
        
        # Create the schema
        class_schema = {
            "class": "DropboxFile",
            "description": "A file from Dropbox with AI-generated embeddings and metadata",
            "vectorizer": "none",  # We'll provide our own vectors
            "properties": [
                {
                    "name": "dropbox_id",
                    "dataType": ["string"],
                    "description": "Unique identifier from Dropbox"
                },
                {
                    "name": "dropbox_path",
                    "dataType": ["string"],
                    "description": "Full path in Dropbox"
                },
                {
                    "name": "file_name",
                    "dataType": ["string"],
                    "description": "Name of the file"
                },
                {
                    "name": "file_type",
                    "dataType": ["string"],
                    "description": "Type of file (image/video)"
                },
                {
                    "name": "file_extension",
                    "dataType": ["string"],
                    "description": "File extension"
                },
                {
                    "name": "file_size",
                    "dataType": ["int"],
                    "description": "File size in bytes"
                },
                {
                    "name": "modified_date",
                    "dataType": ["date"],
                    "description": "Last modified date"
                },
                {
                    "name": "processed_date",
                    "dataType": ["date"],
                    "description": "Date when file was processed"
                },
                {
                    "name": "caption",
                    "dataType": ["text"],
                    "description": "AI-generated caption"
                },
                {
                    "name": "tags",
                    "dataType": ["string[]"],
                    "description": "Extracted tags"
                },
                {
                    "name": "public_url",
                    "dataType": ["string"],
                    "description": "Public URL for the file"
                },
                {
                    "name": "thumbnail_url",
                    "dataType": ["string"],
                    "description": "Thumbnail URL"
                },
                {
                    "name": "content_hash",
                    "dataType": ["string"],
                    "description": "Dropbox content hash"
                },
                {
                    "name": "metadata",
                    "dataType": ["object"],
                    "description": "Additional metadata",
                    "nestedProperties": [
                        {
                            "name": "content_hash",
                            "dataType": ["text"],
                            "description": "Dropbox content hash for duplicate detection"
                        },
                        {
                            "name": "revision",
                            "dataType": ["text"],
                            "description": "Dropbox file revision"
                        },
                        {
                            "name": "server_modified",
                            "dataType": ["text"],
                            "description": "Server modification timestamp"
                        },
                        {
                            "name": "client_modified",
                            "dataType": ["text"],
                            "description": "Client modification timestamp"
                        }
                    ]
                }
            ]
        }
        
        client.schema.create_class(class_schema)
        print("✅ Created DropboxFile schema successfully!")
        
        # Verify the schema
        schema = client.schema.get("DropboxFile")
        print(f"✅ Schema verification successful. Class has {len(schema['properties'])} properties.")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main function"""
    print("🚀 Creating Weaviate Schema for Dropbox Vector Search")
    print("=" * 50)
    
    success = create_weaviate_schema()
    
    if success:
        print("\n🎉 Schema creation completed successfully!")
        print("You can now run your main application.")
    else:
        print("\n💥 Schema creation failed!")
        print("Please check your environment variables and Weaviate connection.")
        sys.exit(1)

if __name__ == "__main__":
    main() 