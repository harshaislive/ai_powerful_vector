import httpx
import logging
from typing import Optional, List, Dict, Any
import asyncio
import os

from config import config

logger = logging.getLogger(__name__)

class AzureVisionService:
    def __init__(self):
        if not config.AZURE_VISION_API_KEY:
            raise ValueError("AZURE_VISION_API_KEY is required")
        
        self.endpoint = config.AZURE_VISION_ENDPOINT.rstrip('/')
        self.api_key = config.AZURE_VISION_API_KEY
        self.client = httpx.AsyncClient(timeout=60.0)
        
        logger.info("Azure Computer Vision service initialized successfully")
    
    async def generate_caption_async(self, image_url: str) -> Optional[str]:
        """
        Generate caption for an image using Azure Computer Vision API
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            Generated caption or None if failed
        """
        try:
            logger.info(f"Generating caption for image: {image_url}")
            
            # Azure Computer Vision API endpoint
            url = f"{self.endpoint}/vision/v3.2/analyze"
            
            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/json"
            }
            
            params = {
                "visualFeatures": "Description"
            }
            
            payload = {
                "url": image_url
            }
            
            response = await self.client.post(url, headers=headers, params=params, json=payload)
            response.raise_for_status()
            
            result = response.json()
            
            # Extract the best caption
            description = result.get("description", {})
            captions = description.get("captions", [])
            
            if captions:
                # Get the caption with highest confidence
                best_caption = max(captions, key=lambda x: x.get("confidence", 0))
                caption = best_caption.get("text", "")
                confidence = best_caption.get("confidence", 0)
                
                logger.info(f"Generated caption: {caption} (confidence: {confidence:.2f})")
                return caption
            else:
                logger.warning("No captions returned from Azure Computer Vision")
                return None
                
        except Exception as e:
            logger.error(f"Error generating caption for {image_url}: {e}")
            return None
    
    async def analyze_image_full(self, image_url: str) -> Optional[Dict[str, Any]]:
        """
        Get full analysis including captions, tags, and metadata
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            Full analysis data or None if failed
        """
        try:
            logger.info(f"Analyzing image: {image_url}")
            
            url = f"{self.endpoint}/vision/v3.2/analyze"
            
            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/json"
            }
            
            params = {
                "visualFeatures": "Description"
            }
            
            payload = {
                "url": image_url
            }
            
            response = await self.client.post(url, headers=headers, params=params, json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Full analysis completed for image")
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing image {image_url}: {e}")
            return None
    
    def extract_tags_from_caption(self, caption: str) -> List[str]:
        """
        Extract tags from caption text - keeping same interface as Replicate service
        
        Args:
            caption: Generated caption
            
        Returns:
            List of extracted tags
        """
        if not caption:
            return []
        
        # Basic tag extraction from caption
        # This mimics the existing Replicate service behavior
        import re
        
        # Common words to extract as tags
        words = re.findall(r'\b\w+\b', caption.lower())
        
        # Filter out common words and keep meaningful ones
        stop_words = {'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 
                     'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 
                     'to', 'was', 'were', 'will', 'with', 'the', 'this', 'but', 'they', 
                     'have', 'had', 'what', 'said', 'each', 'which', 'their', 'time', 
                     'up', 'use', 'your', 'how', 'man', 'new', 'now', 'old', 'see', 
                     'two', 'way', 'who', 'boy', 'did', 'number', 'no', 'part', 'like', 
                     'over', 'such', 'her', 'would', 'make', 'than', 'first', 'been', 
                     'call', 'his', 'into', 'him', 'has', 'more'}
        
        tags = [word for word in words if word not in stop_words and len(word) > 2]
        
        # Remove duplicates and limit to reasonable number
        tags = list(dict.fromkeys(tags))[:10]
        
        logger.info(f"Extracted tags from caption: {tags}")
        return tags
    
    async def extract_tags_from_azure_data(self, image_url: str) -> List[str]:
        """
        Extract tags directly from Azure Computer Vision API response
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            List of tags from Azure API
        """
        try:
            analysis = await self.analyze_image_full(image_url)
            if analysis:
                description = analysis.get("description", {})
                azure_tags = description.get("tags", [])
                
                logger.info(f"Azure tags: {azure_tags}")
                return azure_tags
            
            return []
            
        except Exception as e:
            logger.error(f"Error extracting Azure tags: {e}")
            return []
    
    async def generate_caption_with_tags(self, image_url: str) -> tuple[Optional[str], List[str]]:
        """
        Generate both caption and tags in one call for efficiency
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            Tuple of (caption, tags)
        """
        try:
            analysis = await self.analyze_image_full(image_url)
            if not analysis:
                return None, []
            
            # Extract caption
            description = analysis.get("description", {})
            captions = description.get("captions", [])
            
            caption = None
            if captions:
                best_caption = max(captions, key=lambda x: x.get("confidence", 0))
                caption = best_caption.get("text", "")
            
            # Extract tags (Azure provides them in description.tags)
            azure_tags = description.get("tags", [])
            
            # Also extract tags from caption for comprehensive tagging
            caption_tags = self.extract_tags_from_caption(caption) if caption else []
            
            # Combine and deduplicate tags
            all_tags = list(dict.fromkeys(azure_tags + caption_tags))
            
            logger.info(f"Generated caption with tags: {caption}, tags: {all_tags}")
            return caption, all_tags
            
        except Exception as e:
            logger.error(f"Error generating caption with tags: {e}")
            return None, []
    
    # Video processing methods to maintain interface compatibility
    async def analyze_video_frames(self, frame_paths: List[str]) -> Optional[str]:
        """
        Analyze extracted video frames and generate a comprehensive video description
        Uses Azure Computer Vision for each frame
        
        Args:
            frame_paths: List of paths to extracted frame images
            
        Returns:
            Combined video description or None if failed
        """
        try:
            if not frame_paths:
                logger.warning("No frames provided for video analysis")
                return "Video file - no frames extracted for analysis"
            
            logger.info(f"Analyzing {len(frame_paths)} video frames with Azure Computer Vision")
            
            frame_captions = []
            
            # Analyze each frame using Azure Computer Vision
            for i, frame_path in enumerate(frame_paths):
                try:
                    # Convert local path to URL for Azure API
                    frame_filename = os.path.basename(frame_path)
                    frame_url = f"{config.SERVER_URL}/files/{frame_filename}"
                    
                    # Generate caption for this frame
                    caption = await self.generate_caption_async(frame_url)
                    
                    if caption:
                        frame_captions.append(caption)
                        logger.info(f"Frame {i+1} caption: {caption}")
                    else:
                        logger.warning(f"Failed to generate caption for frame {i+1}")
                        
                except Exception as frame_error:
                    logger.error(f"Error analyzing frame {i+1}: {frame_error}")
                    continue
            
            if not frame_captions:
                logger.error("No frame captions generated")
                return "Video file - frame analysis failed"
            
            # Combine frame captions into video description
            video_description = self._combine_frame_captions(frame_captions)
            
            logger.info(f"Generated video description: {video_description}")
            return video_description
            
        except Exception as e:
            logger.error(f"Error analyzing video frames: {e}")
            return "Video file - analysis error"
    
    def _combine_frame_captions(self, frame_captions: List[str]) -> str:
        """
        Intelligently combine frame captions into a coherent video description
        
        Args:
            frame_captions: List of captions for each frame
            
        Returns:
            Combined video description
        """
        try:
            if not frame_captions:
                return "Video content"
            
            if len(frame_captions) == 1:
                return f"Video showing {frame_captions[0].lower()}"
            
            # Remove duplicates while preserving order
            unique_captions = []
            seen = set()
            for caption in frame_captions:
                caption_lower = caption.lower().strip()
                if caption_lower not in seen:
                    unique_captions.append(caption)
                    seen.add(caption_lower)
            
            if len(unique_captions) == 1:
                return f"Video showing {unique_captions[0].lower()}"
            
            # Create a narrative flow
            if len(unique_captions) == 2:
                return f"Video showing {unique_captions[0].lower()}, then {unique_captions[1].lower()}"
            elif len(unique_captions) == 3:
                return f"Video beginning with {unique_captions[0].lower()}, showing {unique_captions[1].lower()}, and ending with {unique_captions[2].lower()}"
            else:
                # For longer videos, create a more structured description
                beginning = unique_captions[0].lower()
                middle_parts = unique_captions[1:-1]
                ending = unique_captions[-1].lower()
                
                if middle_parts:
                    middle_text = ", ".join([part.lower() for part in middle_parts])
                    return f"Video beginning with {beginning}, showing {middle_text}, and ending with {ending}"
                else:
                    return f"Video beginning with {beginning} and ending with {ending}"
            
        except Exception as e:
            logger.error(f"Error combining frame captions: {e}")
            return "Video content"
    
    def extract_video_tags(self, video_description: str, frame_captions: List[str] = None) -> List[str]:
        """
        Extract tags from video description and frame captions
        
        Args:
            video_description: Combined video description
            frame_captions: Optional list of individual frame captions
            
        Returns:
            List of extracted tags
        """
        try:
            tags = set()
            
            # Extract tags from video description
            if video_description:
                desc_tags = self.extract_tags_from_caption(video_description)
                tags.update(desc_tags)
            
            # Extract tags from individual frame captions
            if frame_captions:
                for caption in frame_captions:
                    frame_tags = self.extract_tags_from_caption(caption)
                    tags.update(frame_tags)
            
            # Always include video tag
            tags.add("video")
            
            # Convert to sorted list
            result = sorted(list(tags))
            logger.info(f"Extracted video tags: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error extracting video tags: {e}")
            return ["video"]
    
    async def generate_caption_from_local_file(self, image_path: str) -> Optional[str]:
        """
        Generate caption for a local image file using Azure Computer Vision API
        
        Args:
            image_path: Path to the local image file
            
        Returns:
            Generated caption or None if failed
        """
        try:
            if not os.path.exists(image_path):
                logger.error(f"Image file not found: {image_path}")
                return None
            
            logger.info(f"Generating caption for local image: {image_path}")
            
            # Azure Computer Vision API endpoint
            url = f"{self.endpoint}/vision/v3.2/analyze"
            
            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/octet-stream"  # Binary data
            }
            
            params = {
                "visualFeatures": "Description"
            }
            
            # Read image file as binary data
            with open(image_path, 'rb') as image_file:
                image_data = image_file.read()
            
            logger.info(f"Sending {len(image_data)} bytes to Azure Vision API")
            
            response = await self.client.post(url, headers=headers, params=params, content=image_data)
            response.raise_for_status()
            
            result = response.json()
            
            # Extract the best caption
            description = result.get("description", {})
            captions = description.get("captions", [])
            
            if captions:
                # Get the caption with highest confidence
                best_caption = max(captions, key=lambda x: x.get("confidence", 0))
                caption = best_caption.get("text", "")
                confidence = best_caption.get("confidence", 0)
                
                logger.info(f"Generated caption from local file: {caption} (confidence: {confidence:.2f})")
                return caption
            else:
                logger.warning("No captions returned from Azure Computer Vision for local file")
                return None
                
        except Exception as e:
            logger.error(f"Error generating caption for local file {image_path}: {e}")
            return None
    
    async def analyze_local_image_full(self, image_path: str) -> Optional[Dict[str, Any]]:
        """
        Get full analysis of local image including captions, tags, and metadata
        
        Args:
            image_path: Path to the local image file
            
        Returns:
            Full analysis data or None if failed
        """
        try:
            if not os.path.exists(image_path):
                logger.error(f"Image file not found: {image_path}")
                return None
            
            logger.info(f"Analyzing local image: {image_path}")
            
            url = f"{self.endpoint}/vision/v3.2/analyze"
            
            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/octet-stream"
            }
            
            params = {
                "visualFeatures": "Description,Tags,Categories"  # Get more features for local analysis
            }
            
            # Read image file as binary data
            with open(image_path, 'rb') as image_file:
                image_data = image_file.read()
            
            response = await self.client.post(url, headers=headers, params=params, content=image_data)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Full analysis completed for local image")
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing local image {image_path}: {e}")
            return None
    
    async def generate_caption_with_tags_from_local(self, image_path: str) -> tuple[Optional[str], List[str]]:
        """
        Generate both caption and tags from local image in one call for efficiency
        
        Args:
            image_path: Path to the local image file
            
        Returns:
            Tuple of (caption, tags)
        """
        try:
            analysis = await self.analyze_local_image_full(image_path)
            if not analysis:
                return None, []
            
            # Extract caption
            description = analysis.get("description", {})
            captions = description.get("captions", [])
            
            caption = None
            if captions:
                best_caption = max(captions, key=lambda x: x.get("confidence", 0))
                caption = best_caption.get("text", "")
            
            # Extract tags from Azure API
            azure_tags = analysis.get("tags", [])
            # Azure tags come as objects with "name" and "confidence"
            tags = [tag.get("name", "") for tag in azure_tags if tag.get("confidence", 0) > 0.5]
            
            # Also get description tags (these are usually more general)
            description_tags = description.get("tags", [])
            tags.extend(description_tags)
            
            # Remove duplicates and limit
            tags = list(dict.fromkeys(tags))[:15]
            
            logger.info(f"Generated caption and tags from local file: {caption}, tags: {tags}")
            return caption, tags
            
        except Exception as e:
            logger.error(f"Error generating caption and tags from local file {image_path}: {e}")
            return None, []
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            asyncio.create_task(self.close())
        except Exception:
            pass 