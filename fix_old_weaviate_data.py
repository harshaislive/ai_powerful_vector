#!/usr/bin/env python3
"""
Script to handle old Weaviate data without vectors
This script provides options to clean up or migrate old data
"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.weaviate_service import WeaviateService
from services.processing_service import ProcessingService
from services.dropbox_service import DropboxService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WeaviateDataFixer:
    def __init__(self):
        self.weaviate_service = None
        self.processing_service = None
        self.dropbox_service = None
        
    async def initialize_services(self):
        """Initialize all required services"""
        try:
            logger.info("🚀 Initializing services...")
            
            self.weaviate_service = WeaviateService()
            self.processing_service = ProcessingService()
            self.dropbox_service = DropboxService()
            
            logger.info("✅ All services initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize services: {e}")
            return False
    
    def analyze_data_state(self):
        """Analyze the current state of data in Weaviate"""
        try:
            logger.info("🔍 Analyzing Weaviate data state...")
            
            # Query all files to check their vector status
            query = (
                self.weaviate_service.client.query
                .get("DropboxFile", ["file_name", "file_type", "dropbox_path", "caption", "tags"])
                .with_additional(["vector", "id"])
                .with_limit(1000)  # Adjust if you have more than 1000 files
                .do()
            )
            
            files = query.get("data", {}).get("Get", {}).get("DropboxFile", [])
            
            files_with_vectors = []
            files_without_vectors = []
            corrupted_files = []
            
            for file_data in files:
                try:
                    file_name = file_data.get('file_name', 'unknown')
                    additional = file_data.get("_additional", {})
                    vector_data = additional.get("vector", [])
                    
                    if vector_data and len(vector_data) > 0:
                        # Check if vector contains valid numbers
                        if all(isinstance(x, (int, float)) for x in vector_data[:10]):
                            files_with_vectors.append({
                                'name': file_name,
                                'path': file_data.get('dropbox_path', ''),
                                'type': file_data.get('file_type', ''),
                                'vector_dim': len(vector_data),
                                'id': additional.get('id', '')
                            })
                        else:
                            corrupted_files.append({
                                'name': file_name,
                                'path': file_data.get('dropbox_path', ''),
                                'type': file_data.get('file_type', ''),
                                'issue': 'Invalid vector data',
                                'id': additional.get('id', '')
                            })
                    else:
                        files_without_vectors.append({
                            'name': file_name,
                            'path': file_data.get('dropbox_path', ''),
                            'type': file_data.get('file_type', ''),
                            'caption': file_data.get('caption', ''),
                            'tags': file_data.get('tags', []),
                            'id': additional.get('id', '')
                        })
                        
                except Exception as e:
                    corrupted_files.append({
                        'name': file_data.get('file_name', 'unknown'),
                        'path': file_data.get('dropbox_path', ''),
                        'issue': f'Error processing: {e}',
                        'id': additional.get('id', '') if 'additional' in locals() else ''
                    })
            
            # Display analysis results
            print("\n" + "=" * 60)
            print("📊 WEAVIATE DATA ANALYSIS")
            print("=" * 60)
            print(f"✅ Files with vectors: {len(files_with_vectors)}")
            print(f"❌ Files without vectors: {len(files_without_vectors)}")
            print(f"🔧 Corrupted files: {len(corrupted_files)}")
            print(f"📋 Total files: {len(files)}")
            
            if files_with_vectors:
                print(f"\n🎯 Files with vectors (sample):")
                for i, file in enumerate(files_with_vectors[:5], 1):
                    print(f"  {i}. {file['name']} ({file['vector_dim']} dimensions)")
            
            if files_without_vectors:
                print(f"\n⚠️ Files without vectors (sample):")
                for i, file in enumerate(files_without_vectors[:5], 1):
                    print(f"  {i}. {file['name']} ({file['type']})")
                    if file['caption']:
                        print(f"      Caption: {file['caption'][:60]}...")
            
            if corrupted_files:
                print(f"\n🔧 Corrupted files:")
                for i, file in enumerate(corrupted_files[:5], 1):
                    print(f"  {i}. {file['name']} - {file['issue']}")
            
            return {
                'files_with_vectors': files_with_vectors,
                'files_without_vectors': files_without_vectors,
                'corrupted_files': corrupted_files,
                'total_files': len(files)
            }
            
        except Exception as e:
            logger.error(f"❌ Error analyzing data state: {e}")
            return None
    
    def delete_files_without_vectors(self, files_without_vectors: List[Dict]):
        """Delete files that don't have vectors"""
        try:
            logger.info(f"🗑️ Deleting {len(files_without_vectors)} files without vectors...")
            
            deleted_count = 0
            failed_count = 0
            
            for file in files_without_vectors:
                try:
                    # Delete by ID if available
                    if file.get('id'):
                        self.weaviate_service.client.data_object.delete(file['id'])
                        deleted_count += 1
                        logger.info(f"✅ Deleted: {file['name']}")
                    else:
                        logger.warning(f"⚠️ No ID for file: {file['name']}")
                        failed_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ Failed to delete {file['name']}: {e}")
            
            logger.info(f"📊 Deletion Summary:")
            logger.info(f"  Successfully deleted: {deleted_count}")
            logger.info(f"  Failed to delete: {failed_count}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Error deleting files without vectors: {e}")
            return 0
    
    async def regenerate_vectors_for_old_files(self, files_without_vectors: List[Dict]):
        """Regenerate vectors for files that don't have them"""
        try:
            logger.info(f"🔄 Regenerating vectors for {len(files_without_vectors)} files...")
            
            processed_count = 0
            failed_count = 0
            
            for file in files_without_vectors:
                try:
                    logger.info(f"🔄 Processing: {file['name']}")
                    
                    # Get file info from Dropbox
                    file_info = self.dropbox_service.get_file_info(file['path'])
                    if not file_info:
                        logger.error(f"❌ Could not get file info for: {file['path']}")
                        failed_count += 1
                        continue
                    
                    # Process the file to generate vectors
                    success = await self.processing_service.process_file(file_info)
                    
                    if success:
                        processed_count += 1
                        logger.info(f"✅ Successfully processed: {file['name']}")
                        
                        # Delete the old entry without vectors
                        if file.get('id'):
                            try:
                                self.weaviate_service.client.data_object.delete(file['id'])
                                logger.info(f"🗑️ Deleted old entry for: {file['name']}")
                            except Exception as e:
                                logger.warning(f"⚠️ Could not delete old entry for {file['name']}: {e}")
                    else:
                        failed_count += 1
                        logger.error(f"❌ Failed to process: {file['name']}")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ Error processing {file['name']}: {e}")
            
            logger.info(f"📊 Vector Regeneration Summary:")
            logger.info(f"  Successfully processed: {processed_count}")
            logger.info(f"  Failed to process: {failed_count}")
            
            return processed_count
            
        except Exception as e:
            logger.error(f"❌ Error regenerating vectors: {e}")
            return 0
    
    def clean_corrupted_files(self, corrupted_files: List[Dict]):
        """Clean up corrupted file entries"""
        try:
            logger.info(f"🔧 Cleaning {len(corrupted_files)} corrupted files...")
            
            cleaned_count = 0
            failed_count = 0
            
            for file in corrupted_files:
                try:
                    if file.get('id'):
                        self.weaviate_service.client.data_object.delete(file['id'])
                        cleaned_count += 1
                        logger.info(f"✅ Cleaned: {file['name']}")
                    else:
                        logger.warning(f"⚠️ No ID for corrupted file: {file['name']}")
                        failed_count += 1
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ Failed to clean {file['name']}: {e}")
            
            logger.info(f"📊 Cleanup Summary:")
            logger.info(f"  Successfully cleaned: {cleaned_count}")
            logger.info(f"  Failed to clean: {failed_count}")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"❌ Error cleaning corrupted files: {e}")
            return 0
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.processing_service:
                await self.processing_service.cleanup()
            logger.info("✅ Cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

async def main():
    """Main function to fix Weaviate data issues"""
    fixer = WeaviateDataFixer()
    
    try:
        logger.info("🔧 Starting Weaviate Data Fixer")
        logger.info("=" * 60)
        
        # Initialize services
        if not await fixer.initialize_services():
            logger.error("❌ Failed to initialize services. Exiting.")
            return
        
        # Analyze current data state
        analysis = fixer.analyze_data_state()
        if not analysis:
            logger.error("❌ Could not analyze data state. Exiting.")
            return
        
        files_with_vectors = analysis['files_with_vectors']
        files_without_vectors = analysis['files_without_vectors']
        corrupted_files = analysis['corrupted_files']
        
        # If no issues, exit
        if not files_without_vectors and not corrupted_files:
            print("\n🎉 All your data looks good! No fixes needed.")
            return
        
        # Show options
        print("\n" + "=" * 60)
        print("🛠️ REPAIR OPTIONS:")
        print("=" * 60)
        print("1. Delete files without vectors (clean slate)")
        print("2. Regenerate vectors for files without vectors (keep old data)")
        print("3. Clean up corrupted files only")
        print("4. Full cleanup (delete all problematic files)")
        print("5. Show analysis only (no changes)")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        print("\n" + "=" * 60)
        
        if choice == "1":
            # Delete files without vectors
            if files_without_vectors:
                confirm = input(f"⚠️ This will delete {len(files_without_vectors)} files without vectors. Continue? (y/N): ")
                if confirm.lower() == 'y':
                    deleted = fixer.delete_files_without_vectors(files_without_vectors)
                    logger.info(f"🎉 Deleted {deleted} files without vectors")
                else:
                    logger.info("❌ Operation cancelled")
            else:
                logger.info("✅ No files without vectors to delete")
                
        elif choice == "2":
            # Regenerate vectors for files without vectors
            if files_without_vectors:
                confirm = input(f"🔄 This will regenerate vectors for {len(files_without_vectors)} files. Continue? (y/N): ")
                if confirm.lower() == 'y':
                    processed = await fixer.regenerate_vectors_for_old_files(files_without_vectors)
                    logger.info(f"🎉 Regenerated vectors for {processed} files")
                else:
                    logger.info("❌ Operation cancelled")
            else:
                logger.info("✅ No files without vectors to process")
                
        elif choice == "3":
            # Clean corrupted files only
            if corrupted_files:
                confirm = input(f"🔧 This will delete {len(corrupted_files)} corrupted files. Continue? (y/N): ")
                if confirm.lower() == 'y':
                    cleaned = fixer.clean_corrupted_files(corrupted_files)
                    logger.info(f"🎉 Cleaned {cleaned} corrupted files")
                else:
                    logger.info("❌ Operation cancelled")
            else:
                logger.info("✅ No corrupted files to clean")
                
        elif choice == "4":
            # Full cleanup
            total_problematic = len(files_without_vectors) + len(corrupted_files)
            if total_problematic > 0:
                confirm = input(f"⚠️ This will delete {total_problematic} problematic files. Continue? (y/N): ")
                if confirm.lower() == 'y':
                    deleted = 0
                    if files_without_vectors:
                        deleted += fixer.delete_files_without_vectors(files_without_vectors)
                    if corrupted_files:
                        deleted += fixer.clean_corrupted_files(corrupted_files)
                    logger.info(f"🎉 Cleaned up {deleted} problematic files")
                else:
                    logger.info("❌ Operation cancelled")
            else:
                logger.info("✅ No problematic files to clean")
                
        elif choice == "5":
            # Show analysis only
            logger.info("📊 Analysis complete. No changes made.")
            
        else:
            logger.error("❌ Invalid choice")
        
        # Final analysis
        print("\n" + "=" * 60)
        logger.info("🔍 Running final analysis...")
        final_analysis = fixer.analyze_data_state()
        
        if final_analysis:
            print("\n🎯 FINAL STATE:")
            print(f"✅ Files with vectors: {len(final_analysis['files_with_vectors'])}")
            print(f"❌ Files without vectors: {len(final_analysis['files_without_vectors'])}")
            print(f"🔧 Corrupted files: {len(final_analysis['corrupted_files'])}")
            
            if len(final_analysis['files_without_vectors']) == 0 and len(final_analysis['corrupted_files']) == 0:
                print("\n🎉 All data is now clean and ready for vector search!")
            else:
                print("\n⚠️ Some issues remain. You may want to run this script again.")
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Operation interrupted by user")
        
    except Exception as e:
        logger.error(f"❌ Data fixing failed with error: {e}")
        
    finally:
        await fixer.cleanup()

if __name__ == "__main__":
    asyncio.run(main()) 