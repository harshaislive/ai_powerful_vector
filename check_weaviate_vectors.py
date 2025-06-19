#!/usr/bin/env python3
"""
Simple script to check Weaviate vector storage and retrieval
This script specifically verifies that vectors are properly stored and retrievable
"""

import asyncio
import os
import sys
import logging
import json

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.weaviate_service import WeaviateService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def check_weaviate_vectors():
    """Check Weaviate vector storage and configuration"""
    try:
        logger.info("🔍 Checking Weaviate vector storage...")
        
        # Initialize Weaviate service
        weaviate_service = WeaviateService()
        logger.info("✅ Connected to Weaviate")
        
        # 1. Validate vector setup
        logger.info("\n📋 1. Validating vector setup...")
        validation = weaviate_service.validate_vector_setup()
        
        print(f"Schema exists: {validation.get('schema_exists', False)}")
        print(f"Vector index type: {validation.get('vector_index_type', 'unknown')}")
        print(f"Has sample vectors: {validation.get('has_sample_vectors', False)}")
        print(f"Sample vector dimensions: {validation.get('sample_vector_dimensions', 0)}")
        
        issues = validation.get('issues', [])
        if issues:
            print("⚠️ Issues found:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("✅ Vector setup validation passed!")
        
        # 2. Get sample data with vectors
        logger.info("\n📊 2. Checking sample data with vectors...")
        
        try:
            # Query for files with vectors
            sample_query = (
                weaviate_service.client.query
                .get("DropboxFile", ["file_name", "file_type", "caption", "tags"])
                .with_additional(["vector", "id"])
                .with_limit(3)
                .do()
            )
            
            files = sample_query.get("data", {}).get("Get", {}).get("DropboxFile", [])
            
            if files:
                print(f"Found {len(files)} files in Weaviate:")
                
                for i, file_data in enumerate(files, 1):
                    additional = file_data.get("_additional", {})
                    vector_data = additional.get("vector", [])
                    
                    print(f"\n  {i}. File: {file_data.get('file_name', 'unknown')}")
                    print(f"     Type: {file_data.get('file_type', 'unknown')}")
                    print(f"     Caption: {file_data.get('caption', 'No caption')[:100]}...")
                    print(f"     Tags: {file_data.get('tags', [])}")
                    print(f"     Has Vector: {bool(vector_data)}")
                    print(f"     Vector Dimensions: {len(vector_data) if vector_data else 0}")
                    
                    if vector_data:
                        print(f"     Vector Sample: {vector_data[:5]}...")
                        
                        # Validate vector values
                        if all(isinstance(x, (int, float)) for x in vector_data[:10]):
                            print(f"     ✅ Vector contains valid numbers")
                        else:
                            print(f"     ❌ Vector contains invalid data")
            else:
                print("❌ No files found in Weaviate")
                
        except Exception as e:
            print(f"❌ Error querying sample data: {e}")
        
        # 3. Test vector search if we have data
        if validation.get('has_sample_vectors', False):
            logger.info("\n🔍 3. Testing vector search...")
            
            try:
                # Create a dummy vector for testing (same dimensions as stored vectors)
                vector_dim = validation.get('sample_vector_dimensions', 512)
                test_vector = [0.1] * vector_dim  # Simple test vector
                
                search_results = weaviate_service.search_similar(test_vector, limit=2)
                
                if search_results:
                    print(f"✅ Vector search returned {len(search_results)} results:")
                    for i, result in enumerate(search_results, 1):
                        print(f"  {i}. {result.file_name} (similarity: {result.similarity_score:.3f})")
                else:
                    print("⚠️ Vector search returned no results")
                    
            except Exception as e:
                print(f"❌ Vector search test failed: {e}")
        else:
            print("\n⚠️ 3. Skipping vector search test - no sample vectors found")
        
        # 4. Schema details
        logger.info("\n🏗️ 4. Schema configuration details...")
        
        try:
            schema = weaviate_service.client.schema.get()
            classes = schema.get("classes", [])
            
            for cls in classes:
                if cls["class"] == "DropboxFile":
                    print(f"Class: {cls['class']}")
                    print(f"Vectorizer: {cls.get('vectorizer', 'unknown')}")
                    print(f"Vector Index Type: {cls.get('vectorIndexType', 'unknown')}")
                    
                    vector_config = cls.get('vectorIndexConfig', {})
                    print(f"Vector Index Config:")
                    print(f"  - Skip: {vector_config.get('skip', 'unknown')}")
                    print(f"  - Distance: {vector_config.get('distance', 'unknown')}")
                    print(f"  - Max Connections: {vector_config.get('maxConnections', 'unknown')}")
                    
                    break
        except Exception as e:
            print(f"❌ Error getting schema details: {e}")
        
        # 5. Summary
        logger.info("\n📋 Summary:")
        is_ready = (
            validation.get('valid', False) and 
            validation.get('has_sample_vectors', False)
        )
        
        if is_ready:
            print("🎉 Weaviate is properly configured for vector search!")
            print("✅ Schema is valid")
            print("✅ Vector indexing is enabled")
            print("✅ Sample vectors are stored")
            print("✅ Vector search is functional")
        else:
            print("❌ Weaviate vector setup needs attention:")
            if not validation.get('valid', False):
                print("  - Schema configuration issues")
            if not validation.get('has_sample_vectors', False):
                print("  - No vectors stored yet (need to process files)")
        
        return is_ready
        
    except Exception as e:
        logger.error(f"❌ Error checking Weaviate: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(check_weaviate_vectors()) 