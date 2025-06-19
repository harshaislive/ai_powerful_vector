#!/usr/bin/env python3
"""
Batch processing script for vectorizing all images in Dropbox
This script processes all images using the enhanced local processing pipeline
"""

import asyncio
import os
import sys
import logging
from datetime import datetime

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.processing_service import ProcessingService
from services.dropbox_service import DropboxService
from services.weaviate_service import WeaviateService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BatchProcessor:
    def __init__(self):
        self.processing_service = None
        self.dropbox_service = None
        self.weaviate_service = None
        
    async def initialize_services(self):
        """Initialize all required services"""
        try:
            logger.info("🚀 Initializing services for batch processing...")
            
            self.processing_service = ProcessingService()
            self.dropbox_service = DropboxService()
            self.weaviate_service = WeaviateService()
            
            logger.info("✅ All services initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize services: {e}")
            return False
    
    async def get_processing_stats(self):
        """Get current processing statistics"""
        try:
            # Get total files from Dropbox
            cached_files = self.dropbox_service.cache.get_files()
            total_files = len(cached_files)
            image_files = len([f for f in cached_files if f.file_type == "image"])
            video_files = len([f for f in cached_files if f.file_type == "video"])
            
            # Get processed files from Weaviate
            processed_count = self.weaviate_service.get_file_count()
            
            logger.info(f"📊 Processing Statistics:")
            logger.info(f"  Total files in Dropbox: {total_files}")
            logger.info(f"  Image files: {image_files}")
            logger.info(f"  Video files: {video_files}")
            logger.info(f"  Already processed: {processed_count}")
            logger.info(f"  Remaining to process: {image_files + video_files - processed_count}")
            
            return {
                "total_files": total_files,
                "image_files": image_files,
                "video_files": video_files,
                "processed_count": processed_count,
                "remaining": image_files + video_files - processed_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting processing stats: {e}")
            return None
    
    async def process_all_files(self, batch_size=5):
        """Process all files in batches"""
        try:
            logger.info("🎯 Starting batch processing of all files...")
            
            # Get initial stats
            stats = await self.get_processing_stats()
            if not stats:
                logger.error("❌ Could not get processing statistics")
                return False
            
            if stats["remaining"] == 0:
                logger.info("🎉 All files are already processed!")
                return True
            
            logger.info(f"📋 Processing {stats['remaining']} remaining files...")
            
            # Process files using the processing service
            result = await self.processing_service.process_all_files()
            
            if result:
                logger.info("🎉 Batch processing completed successfully!")
                
                # Get final stats
                final_stats = await self.get_processing_stats()
                if final_stats:
                    logger.info(f"📊 Final Statistics:")
                    logger.info(f"  Total processed: {final_stats['processed_count']}")
                    logger.info(f"  Remaining: {final_stats['remaining']}")
                
                return True
            else:
                logger.error("❌ Batch processing failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in batch processing: {e}")
            return False
    
    async def process_specific_types(self, file_types=["image"]):
        """Process only specific file types"""
        try:
            logger.info(f"🎯 Processing files of types: {file_types}")
            
            # Get files of specified types
            cached_files = self.dropbox_service.cache.get_files()
            target_files = [f for f in cached_files if f.file_type in file_types]
            
            logger.info(f"📋 Found {len(target_files)} files to process")
            
            processed_count = 0
            failed_count = 0
            
            for file in target_files:
                try:
                    logger.info(f"🔄 Processing: {file.name}")
                    
                    # Check if already processed
                    existing = self.weaviate_service.get_file_by_path(file.path_display)
                    if existing:
                        logger.info(f"⏭️ Skipping already processed file: {file.name}")
                        continue
                    
                    # Process the file
                    success = await self.processing_service.process_file(file)
                    
                    if success:
                        processed_count += 1
                        logger.info(f"✅ Successfully processed: {file.name}")
                    else:
                        failed_count += 1
                        logger.error(f"❌ Failed to process: {file.name}")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ Error processing {file.name}: {e}")
            
            logger.info(f"📊 Processing Summary:")
            logger.info(f"  Successfully processed: {processed_count}")
            logger.info(f"  Failed: {failed_count}")
            logger.info(f"  Total attempted: {processed_count + failed_count}")
            
            return processed_count > 0
            
        except Exception as e:
            logger.error(f"❌ Error in specific type processing: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.processing_service:
                await self.processing_service.cleanup()
            logger.info("✅ Cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

async def main():
    """Main batch processing function"""
    processor = BatchProcessor()
    
    try:
        logger.info("🚀 Starting Batch Vector Processing")
        logger.info("=" * 60)
        
        # Initialize services
        if not await processor.initialize_services():
            logger.error("❌ Failed to initialize services. Exiting.")
            return
        
        # Get current stats
        logger.info("\n" + "=" * 60)
        stats = await processor.get_processing_stats()
        
        if not stats:
            logger.error("❌ Could not get processing statistics. Exiting.")
            return
        
        # Ask user what to do
        print("\n" + "=" * 60)
        print("🎯 Batch Processing Options:")
        print("1. Process all remaining files (images + videos)")
        print("2. Process only images")
        print("3. Process only videos")
        print("4. Show statistics only")
        
        choice = input("\nEnter your choice (1-4): ").strip()
        
        print("\n" + "=" * 60)
        
        if choice == "1":
            # Process all files
            success = await processor.process_all_files()
            if success:
                logger.info("🎉 All files processed successfully!")
            else:
                logger.error("❌ Batch processing failed")
                
        elif choice == "2":
            # Process only images
            success = await processor.process_specific_types(["image"])
            if success:
                logger.info("🎉 All images processed successfully!")
            else:
                logger.error("❌ Image processing failed")
                
        elif choice == "3":
            # Process only videos
            success = await processor.process_specific_types(["video"])
            if success:
                logger.info("🎉 All videos processed successfully!")
            else:
                logger.error("❌ Video processing failed")
                
        elif choice == "4":
            # Show statistics only
            logger.info("📊 Current statistics displayed above")
            
        else:
            logger.error("❌ Invalid choice. Exiting.")
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Processing interrupted by user")
        
    except Exception as e:
        logger.error(f"❌ Batch processing failed with error: {e}")
        
    finally:
        await processor.cleanup()

if __name__ == "__main__":
    # Run the batch processor
    asyncio.run(main()) 