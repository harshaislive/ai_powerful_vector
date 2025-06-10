import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import time

from models import DropboxFile, ProcessedFile, ProcessingStatus
from services.dropbox_service import DropboxService
from services.replicate_service import ReplicateService
from services.clip_service import ClipService
from services.weaviate_service import WeaviateService
from config import config

logger = logging.getLogger(__name__)

class ProcessingService:
    def __init__(self):
        self.dropbox_service = DropboxService()
        self.replicate_service = ReplicateService()
        self.clip_service = ClipService()
        self.weaviate_service = WeaviateService()
        
        # Processing state
        self.current_status = ProcessingStatus(
            status="idle",
            files_processed=0,
            files_total=0
        )
        self.processing_lock = asyncio.Lock()
        
        logger.info("Processing service initialized")
    
    async def process_all_files(self) -> ProcessingStatus:
        """Process all files in Dropbox"""
        async with self.processing_lock:
            try:
                self.current_status = ProcessingStatus(
                    status="running",
                    files_processed=0,
                    files_total=0,
                    start_time=datetime.now(),
                    errors=[]
                )
                
                logger.info("Starting full file processing...")
                
                # Get all files from Dropbox
                dropbox_files = self.dropbox_service.list_files()
                self.current_status.files_total = len(dropbox_files)
                
                logger.info(f"Found {len(dropbox_files)} files to process")
                
                # Process files in batches
                batch_size = config.BATCH_SIZE
                for i in range(0, len(dropbox_files), batch_size):
                    batch = dropbox_files[i:i + batch_size]
                    await self._process_batch(batch)
                
                self.current_status.status = "completed"
                self.current_status.end_time = datetime.now()
                
                logger.info(f"Processing completed. Processed {self.current_status.files_processed}/{self.current_status.files_total} files")
                
                return self.current_status
                
            except Exception as e:
                logger.error(f"Error in process_all_files: {e}")
                self.current_status.status = "failed"
                self.current_status.end_time = datetime.now()
                self.current_status.errors.append(str(e))
                return self.current_status
    
    async def process_new_files(self, after_date: datetime) -> ProcessingStatus:
        """Process files modified after a specific date"""
        async with self.processing_lock:
            try:
                self.current_status = ProcessingStatus(
                    status="running",
                    files_processed=0,
                    files_total=0,
                    start_time=datetime.now(),
                    errors=[]
                )
                
                logger.info(f"Processing files modified after {after_date}")
                
                # Get files modified after the specified date
                dropbox_files = self.dropbox_service.get_files_modified_after(after_date)
                self.current_status.files_total = len(dropbox_files)
                
                logger.info(f"Found {len(dropbox_files)} new/modified files to process")
                
                # Process files in batches
                batch_size = config.BATCH_SIZE
                for i in range(0, len(dropbox_files), batch_size):
                    batch = dropbox_files[i:i + batch_size]
                    await self._process_batch(batch)
                
                self.current_status.status = "completed"
                self.current_status.end_time = datetime.now()
                
                logger.info(f"New file processing completed. Processed {self.current_status.files_processed}/{self.current_status.files_total} files")
                
                return self.current_status
                
            except Exception as e:
                logger.error(f"Error in process_new_files: {e}")
                self.current_status.status = "failed"
                self.current_status.end_time = datetime.now()
                self.current_status.errors.append(str(e))
                return self.current_status
    
    async def _process_batch(self, files: List[DropboxFile]):
        """Process a batch of files"""
        tasks = [self._process_single_file(file) for file in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_msg = f"Error processing {files[i].name}: {result}"
                logger.error(error_msg)
                self.current_status.errors.append(error_msg)
            else:
                self.current_status.files_processed += 1
                
        logger.info(f"Batch completed. Progress: {self.current_status.files_processed}/{self.current_status.files_total}")
    
    async def _process_single_file(self, dropbox_file: DropboxFile) -> Optional[ProcessedFile]:
        """Process a single file"""
        try:
            self.current_status.current_file = dropbox_file.name
            logger.info(f"Processing file: {dropbox_file.name}")
            

            
            # Check if file already exists and hasn't changed
            existing_file = self.weaviate_service.get_file_by_path(dropbox_file.path_display)
            if existing_file and config.SKIP_DUPLICATE_FILES:
                # Check if content hash is the same (file hasn't changed)
                stored_hash = existing_file.get("content_hash")
                if config.TRACK_CONTENT_HASH and stored_hash == dropbox_file.content_hash:
                    logger.info(f"Skipping {dropbox_file.name} - already processed and unchanged")
                    return None
                else:
                    logger.info(f"File {dropbox_file.name} has changed, reprocessing...")
            
            # Create public URL for the file
            public_url = self.dropbox_service.create_shared_link(dropbox_file.path_display)
            if not public_url:
                logger.error(f"Could not create public URL for {dropbox_file.name}")
                return None
            
            # Get optimized URLs based on file type and configuration
            thumbnail_url = None
            processing_url = public_url  # Default to full size
            
            if dropbox_file.file_type == "image" and config.USE_THUMBNAILS:
                # Use configured thumbnail size for processing to reduce bandwidth
                thumbnail_url = self.dropbox_service.get_thumbnail_link(
                    dropbox_file.path_display, 
                    config.THUMBNAIL_SIZE
                )
                # Use thumbnail for processing instead of full image
                processing_url = thumbnail_url or public_url
                logger.info(f"Using {config.THUMBNAIL_SIZE} thumbnail for processing: {dropbox_file.name}")
            elif dropbox_file.file_type == "video" and config.USE_VIDEO_PREVIEWS:
                # Get video preview/thumbnail
                thumbnail_url = self.dropbox_service.get_video_preview_link(dropbox_file.path_display)
                # For videos, still use full URL for now, but we have the preview
                processing_url = public_url
                logger.info(f"Processing video with preview: {dropbox_file.name}")
            else:
                # Use full-size files if optimization is disabled
                processing_url = public_url
                if dropbox_file.file_type == "image":
                    thumbnail_url = public_url  # Use full image as thumbnail
                logger.info(f"Using full-size file for processing: {dropbox_file.name}")
            
            # Generate caption
            caption = None
            tags = []
            
            if dropbox_file.file_type == "image":
                # Generate caption using Replicate with optimized image
                caption = await self.replicate_service.generate_caption_async(processing_url)
                if caption:
                    # Extract tags from caption
                    tags = self.replicate_service.extract_tags_from_caption(caption)
            elif dropbox_file.file_type == "video":
                # For videos, use basic caption for now
                caption = self.replicate_service.generate_video_caption(processing_url)
                tags = ["video"]
            
            # Generate embedding
            embedding = None
            if dropbox_file.file_type == "image":
                # Get image embedding using CLIP with optimized image
                embedding = await self.clip_service.get_image_embedding(processing_url)
            elif caption:
                # Get text embedding from caption
                embedding = await self.clip_service.get_text_embedding(caption)
            
            if not embedding:
                logger.warning(f"Could not generate embedding for {dropbox_file.name}")
                # Use a default embedding or skip
                return None
            
            # Create processed file object
            processed_file = ProcessedFile(
                id=dropbox_file.id,
                dropbox_path=dropbox_file.path_display,
                file_name=dropbox_file.name,
                file_type=dropbox_file.file_type,
                file_extension=dropbox_file.extension,
                file_size=dropbox_file.size,
                modified_date=dropbox_file.modified,
                processed_date=datetime.now(),
                embedding=embedding,
                caption=caption,
                tags=tags,
                metadata={
                    "content_hash": dropbox_file.content_hash,
                    "path_lower": dropbox_file.path_lower,
                    "processing_url": processing_url,  # Track what URL was used for processing
                    "optimized": dropbox_file.file_type == "image"  # Track if we used optimization
                },
                public_url=public_url,
                thumbnail_url=thumbnail_url
            )
            
            # Store in Weaviate
            success = self.weaviate_service.store_file(processed_file)
            
            if success:
                logger.info(f"Successfully processed and stored: {dropbox_file.name}")
                return processed_file
            else:
                logger.error(f"Failed to store processed file: {dropbox_file.name}")
                return None
                
        except Exception as e:
            logger.error(f"Error processing file {dropbox_file.name}: {e}")
            return None
    
    async def search_files(self, query: str, limit: int = 10, file_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Search files using both vector similarity and text search"""
        try:
            results = []
            
            # Try vector search first (if query can be embedded)
            query_embedding = await self.clip_service.get_text_embedding(query)
            if query_embedding:
                vector_results = self.weaviate_service.search_similar(
                    query_embedding, 
                    limit=limit, 
                    file_types=file_types
                )
                results.extend([{
                    "source": "vector",
                    "result": result
                } for result in vector_results])
            
            # Also try text search
            text_results = self.weaviate_service.search_by_text(query, limit=limit)
            results.extend([{
                "source": "text",
                "result": result
            } for result in text_results])
            
            # Remove duplicates and sort by similarity score
            seen_paths = set()
            unique_results = []
            
            for item in results:
                result = item["result"]
                if result.dropbox_path not in seen_paths:
                    seen_paths.add(result.dropbox_path)
                    unique_results.append(item)
            
            # Sort by similarity score (higher first)
            unique_results.sort(key=lambda x: x["result"].similarity_score, reverse=True)
            
            return unique_results[:limit]
            
        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return []
    
    def get_processing_status(self) -> ProcessingStatus:
        """Get current processing status"""
        return self.current_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics (optimized - doesn't scan entire Dropbox)"""
        try:
            weaviate_stats = self.weaviate_service.get_stats()
            
            # Use Weaviate data instead of scanning Dropbox every time
            processed_count = weaviate_stats.get("total_files", 0)
            weaviate_by_type = weaviate_stats.get("by_type", {"image": 0, "video": 0})
            
            stats = {
                "dropbox_files": {
                    "total": "Scan needed",  # Only show actual count after manual scan
                    "images": "Scan needed",
                    "videos": "Scan needed"
                },
                "processed_files": {
                    "total": processed_count,
                    "images": weaviate_by_type.get("image", 0),
                    "videos": weaviate_by_type.get("video", 0)
                },
                "weaviate": weaviate_stats,
                "config": {
                    "batch_size": config.BATCH_SIZE,
                    "supported_image_types": list(config.SUPPORTED_IMAGE_TYPES),
                    "supported_video_types": list(config.SUPPORTED_VIDEO_TYPES),
                    "use_thumbnails": config.USE_THUMBNAILS,
                    "thumbnail_size": config.THUMBNAIL_SIZE
                },
                "optimization": {
                    "thumbnail_processing": config.USE_THUMBNAILS,
                    "video_preview": config.USE_VIDEO_PREVIEWS,
                    "duplicate_detection": config.SKIP_DUPLICATE_FILES,
                    "content_hash_tracking": config.TRACK_CONTENT_HASH
                },
                "last_processing": {
                    "status": self.current_status.status,
                    "files_processed": self.current_status.files_processed,
                    "files_total": self.current_status.files_total,
                    "start_time": self.current_status.start_time.isoformat() if self.current_status.start_time else None,
                    "end_time": self.current_status.end_time.isoformat() if self.current_status.end_time else None,
                    "errors": len(self.current_status.errors),
                    "current_file": self.current_status.current_file
                }
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "error": str(e),
                "dropbox_files": {"total": "Error", "images": "Error", "videos": "Error"},
                "processed_files": {"total": 0, "images": 0, "videos": 0},
                "weaviate": {"total_files": 0, "by_type": {"image": 0, "video": 0}},
                "config": {"batch_size": config.BATCH_SIZE},
                "optimization": {
                    "thumbnail_processing": config.USE_THUMBNAILS,
                    "video_preview": config.USE_VIDEO_PREVIEWS,
                    "duplicate_detection": config.SKIP_DUPLICATE_FILES,
                    "content_hash_tracking": config.TRACK_CONTENT_HASH
                },
                "last_processing": {"status": "error", "files_processed": 0, "files_total": 0}
            }
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            await self.clip_service.close()
            logger.info("Processing service cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}") 