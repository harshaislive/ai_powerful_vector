import dropbox
import requests
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
from urllib.parse import urlparse
import logging
import tempfile
import hashlib
import json

from config import config
from models import DropboxFile
from services.local_cache_service import LocalCacheService

logger = logging.getLogger(__name__)

class DropboxService:
    def __init__(self):
        self.client_id = config.DROPBOX_CLIENT_ID
        self.client_secret = config.DROPBOX_CLIENT_SECRET
        self.refresh_token = config.DROPBOX_REFRESH_TOKEN
        self.access_token = None
        self.dbx = None
        self.cursor_file = "dropbox_cursor.json"
        
        # Initialize local cache
        self.cache = LocalCacheService()
        
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Dropbox client with access token"""
        try:
            self.access_token = self._get_access_token()
            self.dbx = dropbox.Dropbox(self.access_token)
            logger.info("Dropbox client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Dropbox client: {e}")
            raise
    
    def _get_access_token(self) -> str:
        """Get access token using refresh token"""
        url = "https://api.dropboxapi.com/oauth2/token"
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        return token_data['access_token']
    
    def _save_cursor(self, cursor: str, last_sync: datetime = None):
        """Save cursor state for incremental sync"""
        try:
            cursor_data = {
                "cursor": cursor,
                "last_sync": last_sync.isoformat() if last_sync else datetime.now().isoformat(),
                "created_at": datetime.now().isoformat()
            }
            with open(self.cursor_file, 'w') as f:
                json.dump(cursor_data, f)
            logger.info(f"Saved cursor state: {cursor[:20]}...")
        except Exception as e:
            logger.error(f"Error saving cursor: {e}")
    
    def _load_cursor(self) -> Optional[Dict]:
        """Load cursor state for incremental sync"""
        try:
            if os.path.exists(self.cursor_file):
                with open(self.cursor_file, 'r') as f:
                    cursor_data = json.load(f)
                logger.info(f"Loaded cursor state from {cursor_data.get('last_sync', 'unknown')}")
                return cursor_data
        except Exception as e:
            logger.error(f"Error loading cursor: {e}")
        return None
    
    def get_incremental_changes(self) -> tuple[List[DropboxFile], str]:
        """
        Get only changed files since last sync using Dropbox delta/continue API
        Updates local cache with changes
        Returns: (changed_files, new_cursor)
        """
        try:
            cursor_data = self._load_cursor()
            
            # Check if cache is empty - if so, do full sync first
            if self.cache.is_cache_empty():
                logger.info("Cache is empty, performing initial full sync")
                return self._do_full_resync()
            
            if cursor_data and cursor_data.get("cursor"):
                # Use existing cursor for incremental update
                cursor = cursor_data["cursor"]
                logger.info(f"Getting incremental changes since {cursor_data.get('last_sync', 'unknown')}")
                
                try:
                    result = self.dbx.files_list_folder_continue(cursor)
                except dropbox.exceptions.ApiError as e:
                    if "reset" in str(e).lower():
                        logger.warning("Cursor expired, doing full resync")
                        return self._do_full_resync()
                    raise
            else:
                # First time or cursor lost - do initial sync
                logger.info("No cursor found, doing initial sync")
                return self._do_full_resync()
            
            # Process incremental changes
            changed_files = []
            while True:
                for entry in result.entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        file_extension = os.path.splitext(entry.name)[1].lower()
                        
                        # Filter for supported file types
                        if (file_extension in config.SUPPORTED_IMAGE_TYPES or 
                            file_extension in config.SUPPORTED_VIDEO_TYPES):
                            
                            file_type = "image" if file_extension in config.SUPPORTED_IMAGE_TYPES else "video"
                            
                            dropbox_file = DropboxFile(
                                id=entry.id,
                                name=entry.name,
                                path_lower=entry.path_lower,
                                path_display=entry.path_display,
                                size=entry.size,
                                modified=entry.client_modified,
                                content_hash=entry.content_hash,
                                file_type=file_type,
                                extension=file_extension
                            )
                            changed_files.append(dropbox_file)
                    elif isinstance(entry, dropbox.files.DeletedMetadata):
                        # Handle deletions - remove from cache
                        self.cache.remove_file(entry.path_display)
                        logger.info(f"File deleted from cache: {entry.path_display}")
                
                if not result.has_more:
                    new_cursor = result.cursor
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)
            
            # Store changed files in cache
            if changed_files:
                self.cache.store_files(changed_files, is_full_sync=False)
            
            # Save new cursor
            self._save_cursor(new_cursor)
            
            logger.info(f"Found {len(changed_files)} changed files since last sync")
            return changed_files, new_cursor
            
        except Exception as e:
            logger.error(f"Error getting incremental changes: {e}")
            # Fallback to full sync on error
            return self._do_full_resync()
    
    def _do_full_resync(self) -> tuple[List[DropboxFile], str]:
        """Do a full resync when cursor is invalid or missing"""
        logger.info("Performing full resync...")
        
        files = []
        result = self.dbx.files_list_folder("", recursive=True)
        
        while True:
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    file_extension = os.path.splitext(entry.name)[1].lower()
                    
                    # Filter for supported file types
                    if (file_extension in config.SUPPORTED_IMAGE_TYPES or 
                        file_extension in config.SUPPORTED_VIDEO_TYPES):
                        
                        file_type = "image" if file_extension in config.SUPPORTED_IMAGE_TYPES else "video"
                        
                        dropbox_file = DropboxFile(
                            id=entry.id,
                            name=entry.name,
                            path_lower=entry.path_lower,
                            path_display=entry.path_display,
                            size=entry.size,
                            modified=entry.client_modified,
                            content_hash=entry.content_hash,
                            file_type=file_type,
                            extension=file_extension
                        )
                        files.append(dropbox_file)
            
            if not result.has_more:
                cursor = result.cursor
                break
            result = self.dbx.files_list_folder_continue(result.cursor)
        
        # Store all files in cache (full sync)
        if files:
            self.cache.store_files(files, is_full_sync=True)
        
        # Save cursor for future incremental syncs
        self._save_cursor(cursor)
        
        logger.info(f"Full resync completed: {len(files)} files")
        return files, cursor
    
    def list_files(self, folder_path: str = "", recursive: bool = True, use_cache: bool = True) -> List[DropboxFile]:
        """
        List files - now cache-first with fallback to Dropbox API
        
        Args:
            folder_path: Folder to list (not fully implemented for cache yet)
            recursive: Include subfolders (not relevant for cache implementation)
            use_cache: Whether to use cache first (default: True)
        """
        if use_cache and not self.cache.is_cache_empty():
            # Try cache first
            logger.info("Getting files from local cache (instant)")
            cached_files = self.cache.get_files(folder_path)
            if cached_files:
                logger.info(f"Retrieved {len(cached_files)} files from cache")
                return cached_files
            else:
                logger.info("Cache empty or no files found, falling back to Dropbox API")
        
        # Fallback to original API method
        logger.warning("Using Dropbox API for file listing (slow) - consider syncing cache first")
        try:
            files = []
            
            if recursive:
                result = self.dbx.files_list_folder(folder_path, recursive=True)
            else:
                result = self.dbx.files_list_folder(folder_path)
            
            while True:
                for entry in result.entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        file_extension = os.path.splitext(entry.name)[1].lower()
                        
                        # Filter for supported file types
                        if (file_extension in config.SUPPORTED_IMAGE_TYPES or 
                            file_extension in config.SUPPORTED_VIDEO_TYPES):
                            
                            file_type = "image" if file_extension in config.SUPPORTED_IMAGE_TYPES else "video"
                            
                            dropbox_file = DropboxFile(
                                id=entry.id,
                                name=entry.name,
                                path_lower=entry.path_lower,
                                path_display=entry.path_display,
                                size=entry.size,
                                modified=entry.client_modified,
                                content_hash=entry.content_hash,
                                file_type=file_type,
                                extension=file_extension
                            )
                            files.append(dropbox_file)
                
                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)
            
            logger.info(f"Found {len(files)} supported files in Dropbox")
            return files
            
        except Exception as e:
            logger.error(f"Error listing Dropbox files: {e}")
            raise
    
    def get_file_info(self, path: str) -> Optional[DropboxFile]:
        """Get detailed information about a specific file"""
        try:
            metadata = self.dbx.files_get_metadata(path)
            if isinstance(metadata, dropbox.files.FileMetadata):
                file_extension = os.path.splitext(metadata.name)[1].lower()
                file_type = "image" if file_extension in config.SUPPORTED_IMAGE_TYPES else "video"
                
                return DropboxFile(
                    id=metadata.id,
                    name=metadata.name,
                    path_lower=metadata.path_lower,
                    path_display=metadata.path_display,
                    size=metadata.size,
                    modified=metadata.client_modified,
                    content_hash=metadata.content_hash,
                    file_type=file_type,
                    extension=file_extension
                )
        except Exception as e:
            logger.error(f"Error getting file info for {path}: {e}")
            return None
    
    def create_shared_link(self, path: str) -> Optional[str]:
        """Create a public shared link for a file"""
        try:
            # Check if shared link already exists
            existing_links = self.dbx.sharing_list_shared_links(path=path)
            if existing_links.links:
                link = existing_links.links[0].url
                # Convert to direct download link
                return link.replace('?dl=0', '?dl=1')
            
            # Create new shared link
            shared_link = self.dbx.sharing_create_shared_link_with_settings(path)
            link = shared_link.url
            # Convert to direct download link
            return link.replace('?dl=0', '?dl=1')
            
        except dropbox.exceptions.ApiError as e:
            if 'shared_link_already_exists' in str(e):
                # Get existing link
                existing_links = self.dbx.sharing_list_shared_links(path=path)
                if existing_links.links:
                    link = existing_links.links[0].url
                    return link.replace('?dl=0', '?dl=1')
            logger.error(f"Error creating shared link for {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating shared link for {path}: {e}")
            return None
    
    def get_thumbnail_link(self, path: str, size: str = "medium") -> Optional[str]:
        """Get thumbnail URL for an image file"""
        try:
            if not path.lower().endswith(tuple(config.SUPPORTED_IMAGE_TYPES)):
                return None
            
            # Map size parameter to Dropbox thumbnail sizes
            size_mapping = {
                "small": dropbox.files.ThumbnailSize.w128h128,
                "medium": dropbox.files.ThumbnailSize.w640h480,
                "large": dropbox.files.ThumbnailSize.w1024h768
            }
            
            thumbnail_size = size_mapping.get(size, dropbox.files.ThumbnailSize.w640h480)
            
            # Get thumbnail data
            metadata, thumbnail_content = self.dbx.files_get_thumbnail(
                path, 
                format=dropbox.files.ThumbnailFormat.jpeg, 
                size=thumbnail_size
            )
            
            # Create a temporary shared link for the thumbnail
            # Note: This is a simplified approach. In production, you might want to
            # store thumbnails in a CDN or object storage for better performance
            shared_link = self.create_shared_link(path)
            
            # For now, we'll return the shared link with a size parameter
            # In a full implementation, you'd upload the thumbnail_response.content 
            # to a storage service and return that URL
            if shared_link:
                return f"{shared_link}&thumbnail=1&size={size}"
            
            return shared_link
            
        except Exception as e:
            logger.error(f"Error getting thumbnail for {path}: {e}")
            return self.create_shared_link(path)  # Fallback to full image
    
    def get_video_preview_link(self, path: str) -> Optional[str]:
        """Get a preview/thumbnail for a video file"""
        try:
            if not path.lower().endswith(tuple(config.SUPPORTED_VIDEO_TYPES)):
                return None
            
            # Try to get video thumbnail
            try:
                metadata, thumbnail_content = self.dbx.files_get_thumbnail(
                    path,
                    format=dropbox.files.ThumbnailFormat.jpeg,
                    size=dropbox.files.ThumbnailSize.w640h480
                )
                
                # Create shared link for the video thumbnail
                shared_link = self.create_shared_link(path)
                if shared_link:
                    return f"{shared_link}&preview=1&type=video"
                    
            except dropbox.exceptions.ApiError:
                # If thumbnail fails, return regular shared link
                logger.info(f"No thumbnail available for video {path}, using regular link")
                return self.create_shared_link(path)
            
            return self.create_shared_link(path)
            
        except Exception as e:
            logger.error(f"Error getting video preview for {path}: {e}")
            return self.create_shared_link(path)  # Fallback to full video
    
    def download_file(self, path: str, local_path: str) -> bool:
        """Download a file from Dropbox"""
        try:
            self.dbx.files_download_to_file(local_path, path)
            return True
        except Exception as e:
            logger.error(f"Error downloading file {path}: {e}")
            return False
    
    def get_files_modified_after(self, after_date: datetime, use_cache: bool = True) -> List[DropboxFile]:
        """Get files modified after a specific date - cache-first approach"""
        if use_cache and not self.cache.is_cache_empty():
            logger.info("Getting modified files from local cache")
            return self.cache.get_files_modified_after(after_date)
        
        # Fallback to old method (inefficient)
        logger.warning("Using inefficient method - fetching all files then filtering")
        all_files = self.list_files(use_cache=False)
        return [f for f in all_files if f.modified > after_date]

    def download_file_to_temp(self, path: str) -> Optional[str]:
        """Download a file to temporary directory and return local path"""
        try:
            # Create a safe filename based on the path hash
            path_hash = hashlib.md5(path.encode()).hexdigest()
            file_extension = os.path.splitext(path)[1]
            temp_filename = f"{path_hash}{file_extension}"
            
            # Create temp directory if it doesn't exist
            temp_dir = os.path.join(os.getcwd(), "temp_files")
            os.makedirs(temp_dir, exist_ok=True)
            
            local_path = os.path.join(temp_dir, temp_filename)
            
            # Check if file already exists and is recent
            if os.path.exists(local_path):
                # File exists, check if it's still fresh (less than 1 hour old)
                file_age = datetime.now().timestamp() - os.path.getmtime(local_path)
                if file_age < 3600:  # 1 hour
                    logger.info(f"Using cached file: {local_path}")
                    return local_path
            
            # Download the file
            self.dbx.files_download_to_file(local_path, path)
            logger.info(f"Downloaded {path} to {local_path}")
            return local_path
            
        except Exception as e:
            logger.error(f"Error downloading file {path} to temp: {e}")
            return None

    def get_local_file_url(self, path: str, base_url: str = None) -> Optional[str]:
        """Download file and return a local server URL"""
        try:
            local_path = self.download_file_to_temp(path)
            if not local_path:
                return None
                
            # Use config server URL if base_url not provided
            if base_url is None:
                base_url = config.SERVER_URL
                
            # Convert absolute path to relative path for URL
            temp_dir = os.path.join(os.getcwd(), "temp_files")
            relative_path = os.path.relpath(local_path, os.getcwd())
            
            # Return URL that our FastAPI server can serve
            file_url = f"{base_url}/files/{os.path.basename(local_path)}"
            return file_url
            
        except Exception as e:
            logger.error(f"Error creating local file URL for {path}: {e}")
            return None

    def get_local_file_path(self, path: str) -> Optional[str]:
        """Download file and return the local file system path for direct file access"""
        try:
            local_path = self.download_file_to_temp(path)
            if local_path and os.path.exists(local_path):
                logger.info(f"Local file path for {path}: {local_path}")
                return local_path
            return None
        except Exception as e:
            logger.error(f"Error getting local file path for {path}: {e}")
            return None

    def get_local_thumbnail(self, path: str, size: str = "medium", base_url: str = None) -> Optional[str]:
        """Get local thumbnail for an image file"""
        try:
            if not path.lower().endswith(tuple(config.SUPPORTED_IMAGE_TYPES)):
                return None
            
            # Use config server URL if base_url not provided
            if base_url is None:
                base_url = config.SERVER_URL
            
            # Map size parameter to Dropbox thumbnail sizes
            size_mapping = {
                "small": dropbox.files.ThumbnailSize.w128h128,
                "medium": dropbox.files.ThumbnailSize.w640h480,
                "large": dropbox.files.ThumbnailSize.w1024h768
            }
            
            thumbnail_size = size_mapping.get(size, dropbox.files.ThumbnailSize.w640h480)
            
            # Create thumbnail filename
            path_hash = hashlib.md5(path.encode()).hexdigest()
            thumb_filename = f"{path_hash}_thumb_{size}.jpg"
            
            temp_dir = os.path.join(os.getcwd(), "temp_files")
            os.makedirs(temp_dir, exist_ok=True)
            thumb_path = os.path.join(temp_dir, thumb_filename)
            
            # Check if thumbnail already exists
            if os.path.exists(thumb_path):
                file_age = datetime.now().timestamp() - os.path.getmtime(thumb_path)
                if file_age < 3600:  # 1 hour cache
                    return f"{base_url}/files/{thumb_filename}"
            
            # Get thumbnail from Dropbox
            try:
                metadata, response = self.dbx.files_get_thumbnail(
                    path, 
                    format=dropbox.files.ThumbnailFormat.jpeg, 
                    size=thumbnail_size
                )
                
                # Handle the response properly - it should be bytes
                if hasattr(response, 'content'):
                    thumbnail_content = response.content
                elif isinstance(response, bytes):
                    thumbnail_content = response
                else:
                    # If response is not bytes, try to get content
                    thumbnail_content = response
                
                # Save thumbnail to local file
                with open(thumb_path, 'wb') as f:
                    f.write(thumbnail_content)
                
                logger.info(f"Created thumbnail for {path} at {thumb_path}")
                return f"{base_url}/files/{thumb_filename}"
                
            except Exception as thumb_error:
                logger.warning(f"Could not create thumbnail for {path}: {thumb_error}")
                # Fallback to full image
                return self.get_local_file_url(path, base_url)
            
        except Exception as e:
            logger.error(f"Error creating local thumbnail for {path}: {e}")
            # Fallback to full image
            return self.get_local_file_url(path, base_url)

    def cleanup_temp_files(self, max_age_hours: int = 24):
        """Clean up old temporary files"""
        try:
            temp_dir = os.path.join(os.getcwd(), "temp_files")
            if not os.path.exists(temp_dir):
                return
                
            current_time = datetime.now().timestamp()
            cleaned_count = 0
            
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > (max_age_hours * 3600):
                        os.remove(file_path)
                        cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old temporary files")
                
        except Exception as e:
            logger.error(f"Error cleaning up temp files: {e}")

    def get_file_by_path_cached(self, path: str) -> Optional[DropboxFile]:
        """Get file by path from cache (instant lookup)"""
        return self.cache.get_file_by_path(path) 