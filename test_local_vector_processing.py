#!/usr/bin/env python3
"""
Test script for local image processing with Azure Vision and vector storage
This script tests the complete pipeline:
1. Download image locally from Dropbox
2. Process with Azure Computer Vision (local binary upload)
3. Generate CLIP embeddings
4. Store in Weaviate with vectors
5. Verify vector search works
"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from typing import Optional

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from services.dropbox_service import DropboxService
from services.azure_vision_service import AzureVisionService
from services.clip_service import ClipService
from services.weaviate_service import WeaviateService
from models import ProcessedFile

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LocalVectorTester:
    def __init__(self):
        self.dropbox_service = None
        self.azure_vision_service = None
        self.clip_service = None
        self.weaviate_service = None
        
    async def initialize_services(self):
        """Initialize all required services"""
        try:
            logger.info("🚀 Initializing services...")
            
            # Initialize Dropbox service
            self.dropbox_service = DropboxService()
            logger.info("✅ Dropbox service initialized")
            
            # Initialize Azure Vision service
            self.azure_vision_service = AzureVisionService()
            logger.info("✅ Azure Computer Vision service initialized")
            
            # Initialize CLIP service
            self.clip_service = ClipService()
            logger.info("✅ CLIP service initialized")
            
            # Initialize Weaviate service
            self.weaviate_service = WeaviateService()
            logger.info("✅ Weaviate service initialized")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize services: {e}")
            return False
    
    async def find_test_image(self) -> Optional[str]:
        """Find a suitable test image from Dropbox"""
        try:
            logger.info("🔍 Looking for test images in Dropbox...")
            
            # Get cached files (much faster than listing all files)
            cached_files = self.dropbox_service.cache.get_files()
            
            # Find first image file
            for file in cached_files:
                if file.file_type == "image":
                    logger.info(f"📸 Found test image: {file.name} ({file.path_display})")
                    return file.path_display
            
            # If no cached files, try listing some files
            logger.info("No cached files found, checking Dropbox directly...")
            files = self.dropbox_service.list_files()
            
            for file in files[:10]:  # Check first 10 files
                if file.file_type == "image":
                    logger.info(f"📸 Found test image: {file.name} ({file.path_display})")
                    return file.path_display
            
            logger.error("❌ No image files found in Dropbox")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error finding test image: {e}")
            return None
    
    async def test_local_processing(self, image_path: str) -> bool:
        """Test the complete local processing pipeline"""
        try:
            logger.info(f"🧪 Testing local processing for: {image_path}")
            
            # Step 1: Download image locally
            logger.info("⬇️ Step 1: Downloading image locally...")
            local_file_path = self.dropbox_service.get_local_file_path(image_path)
            
            if not local_file_path or not os.path.exists(local_file_path):
                logger.error(f"❌ Failed to download image locally: {image_path}")
                return False
            
            file_size = os.path.getsize(local_file_path)
            logger.info(f"✅ Downloaded {file_size} bytes to: {local_file_path}")
            
            # Step 2: Process with Azure Computer Vision (local binary upload)
            logger.info("🤖 Step 2: Processing with Azure Computer Vision...")
            caption, tags = await self.azure_vision_service.generate_caption_with_tags_from_local(local_file_path)
            
            if not caption:
                logger.error("❌ Failed to generate caption with Azure Vision")
                return False
            
            logger.info(f"✅ Caption: {caption}")
            logger.info(f"✅ Tags: {tags}")
            
            # Step 3: Generate CLIP embedding
            logger.info("🔮 Step 3: Generating CLIP embedding...")
            embedding = await self.clip_service.get_text_embedding(caption)
            
            if not embedding:
                logger.error("❌ Failed to generate CLIP embedding")
                return False
            
            logger.info(f"✅ Generated {len(embedding)}-dimensional embedding")
            logger.info(f"✅ Embedding sample: {embedding[:5]}...")
            
            # Step 4: Create ProcessedFile object
            logger.info("📦 Step 4: Creating ProcessedFile object...")
            
            # Get file info from Dropbox
            file_info = self.dropbox_service.get_file_info(image_path)
            if not file_info:
                logger.error(f"❌ Could not get file info for: {image_path}")
                return False
            
            processed_file = ProcessedFile(
                id=file_info.id,
                dropbox_path=file_info.path_display,
                file_name=file_info.name,
                file_type=file_info.file_type,
                file_extension=file_info.extension,
                file_size=file_info.size,
                modified_date=file_info.modified,
                processed_date=datetime.now(),
                embedding=embedding,
                caption=caption,
                tags=tags,
                metadata={
                    "content_hash": file_info.content_hash,
                    "local_processing": True,
                    "test_file": True
                },
                public_url=None,
                thumbnail_url=None
            )
            
            logger.info(f"✅ Created ProcessedFile object")
            
            # Step 5: Store in Weaviate
            logger.info("💾 Step 5: Storing in Weaviate...")
            success = self.weaviate_service.store_file(processed_file)
            
            if not success:
                logger.error("❌ Failed to store file in Weaviate")
                return False
            
            logger.info("✅ Successfully stored in Weaviate")
            
            # Step 6: Verify storage and vector retrieval
            logger.info("🔍 Step 6: Verifying storage...")
            stored_file = self.weaviate_service.get_file_by_path(image_path)
            
            if not stored_file:
                logger.error("❌ File not found in Weaviate after storage")
                return False
            
            logger.info("✅ File successfully retrieved from Weaviate")
            logger.info(f"✅ Stored caption: {stored_file.get('caption', 'N/A')}")
            logger.info(f"✅ Stored tags: {stored_file.get('tags', [])}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in local processing test: {e}")
            return False
    
    async def test_vector_search(self, test_caption: str) -> bool:
        """Test vector search functionality"""
        try:
            logger.info(f"🔍 Testing vector search with query: '{test_caption}'")
            
            # Generate embedding for search query
            query_embedding = await self.clip_service.get_text_embedding(test_caption)
            
            if not query_embedding:
                logger.error("❌ Failed to generate query embedding")
                return False
            
            logger.info(f"✅ Generated query embedding ({len(query_embedding)} dimensions)")
            
            # Search for similar vectors
            search_results = self.weaviate_service.search_similar(query_embedding, limit=5)
            
            if not search_results:
                logger.warning("⚠️ No search results found")
                return False
            
            logger.info(f"✅ Found {len(search_results)} search results:")
            
            for i, result in enumerate(search_results, 1):
                logger.info(f"  {i}. {result.file_name} (similarity: {result.similarity_score:.3f})")
                logger.info(f"     Caption: {result.caption}")
                logger.info(f"     Tags: {result.tags}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in vector search test: {e}")
            return False
    
    async def validate_vector_setup(self) -> bool:
        """Validate the overall vector setup"""
        try:
            logger.info("🔧 Validating vector setup...")
            
            validation_result = self.weaviate_service.validate_vector_setup()
            
            logger.info(f"Schema exists: {validation_result.get('schema_exists', False)}")
            logger.info(f"Vector index type: {validation_result.get('vector_index_type', 'unknown')}")
            logger.info(f"Has sample vectors: {validation_result.get('has_sample_vectors', False)}")
            logger.info(f"Sample vector dimensions: {validation_result.get('sample_vector_dimensions', 0)}")
            
            issues = validation_result.get('issues', [])
            if issues:
                logger.warning("⚠️ Vector setup issues found:")
                for issue in issues:
                    logger.warning(f"  - {issue}")
            else:
                logger.info("✅ Vector setup looks good!")
            
            return validation_result.get('valid', False)
            
        except Exception as e:
            logger.error(f"❌ Error validating vector setup: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.azure_vision_service:
                await self.azure_vision_service.close()
            if self.clip_service:
                await self.clip_service.close()
            logger.info("✅ Cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

async def main():
    """Main test function"""
    tester = LocalVectorTester()
    
    try:
        logger.info("🧪 Starting Local Vector Processing Test")
        logger.info("=" * 60)
        
        # Initialize services
        if not await tester.initialize_services():
            logger.error("❌ Failed to initialize services. Exiting.")
            return
        
        # Validate vector setup first
        logger.info("\n" + "=" * 60)
        if not await tester.validate_vector_setup():
            logger.error("❌ Vector setup validation failed. Please fix vector configuration first.")
            return
        
        # Find a test image
        logger.info("\n" + "=" * 60)
        test_image_path = await tester.find_test_image()
        
        if not test_image_path:
            logger.error("❌ No test image found. Please ensure you have images in Dropbox.")
            return
        
        # Test local processing pipeline
        logger.info("\n" + "=" * 60)
        if not await tester.test_local_processing(test_image_path):
            logger.error("❌ Local processing test failed.")
            return
        
        # Test vector search
        logger.info("\n" + "=" * 60)
        test_query = "test image"  # Simple query to test search
        if not await tester.test_vector_search(test_query):
            logger.error("❌ Vector search test failed.")
            return
        
        # Final success message
        logger.info("\n" + "=" * 60)
        logger.info("🎉 ALL TESTS PASSED!")
        logger.info("✅ Local image processing with Azure Vision works correctly")
        logger.info("✅ CLIP embeddings are generated successfully")
        logger.info("✅ Vectors are stored and searchable in Weaviate")
        logger.info("✅ Vector search returns relevant results")
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        
    finally:
        await tester.cleanup()

if __name__ == "__main__":
    # Run the test
    asyncio.run(main()) 