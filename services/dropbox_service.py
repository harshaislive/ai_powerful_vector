import dropbox
import requests
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
from urllib.parse import urlparse
import logging

from config import config
from models import DropboxFile

logger = logging.getLogger(__name__)

class DropboxService:
    def __init__(self):
        self.client_id = config.DROPBOX_CLIENT_ID
        self.client_secret = config.DROPBOX_CLIENT_SECRET
        self.refresh_token = config.DROPBOX_REFRESH_TOKEN
        self.access_token = None
        self.dbx = None
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
    
    def list_files(self, folder_path: str = "", recursive: bool = True) -> List[DropboxFile]:
        """List all files in Dropbox folder"""
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
            thumbnail_response = self.dbx.files_get_thumbnail(
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
                thumbnail_response = self.dbx.files_get_thumbnail(
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
    
    def get_files_modified_after(self, after_date: datetime) -> List[DropboxFile]:
        """Get files modified after a specific date"""
        all_files = self.list_files()
        return [f for f in all_files if f.modified > after_date] 