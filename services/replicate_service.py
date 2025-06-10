import replicate
import logging
from typing import Optional
import asyncio
import time
import os

from config import config
from models import CaptionRequest, CaptionResponse

logger = logging.getLogger(__name__)

class ReplicateService:
    def __init__(self):
        if not config.REPLICATE_API_TOKEN:
            raise ValueError("REPLICATE_API_TOKEN is required")
        
        # Set the API token using environment variable (modern replicate library)
        os.environ["REPLICATE_API_TOKEN"] = config.REPLICATE_API_TOKEN
        
        # BLIP model for image captioning
        self.blip_model = "salesforce/blip:2e1dddc8621f72155f24cf2e0adbde548458d3cab9f00c0139eea840d0ac4746"
        
        logger.info("Replicate service initialized successfully")
    
    def generate_caption(self, image_url: str, task: str = "caption") -> Optional[str]:
        """
        Generate caption for an image using BLIP model
        
        Args:
            image_url: Public URL of the image
            task: Task type - "caption" for image captioning
        
        Returns:
            Generated caption or None if failed
        """
        try:
            logger.info(f"Generating caption for image: {image_url}")
            
            input_data = {
                "image": image_url,
                "task": task
            }
            
            # Run the model
            output = replicate.run(self.blip_model, input=input_data)
            
            if output and isinstance(output, str):
                caption = output.strip()
                logger.info(f"Generated caption: {caption}")
                return caption
            else:
                logger.warning(f"Unexpected output format from BLIP model: {output}")
                return None
                
        except Exception as e:
            logger.error(f"Error generating caption for {image_url}: {e}")
            return None
    
    async def generate_caption_async(self, image_url: str, task: str = "caption") -> Optional[str]:
        """
        Async version of generate_caption
        """
        try:
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.generate_caption,
                image_url,
                task
            )
            return result
        except Exception as e:
            logger.error(f"Error in async caption generation: {e}")
            return None
    
    def generate_video_caption(self, video_url: str) -> Optional[str]:
        """
        Generate caption for video (placeholder - you might want to extract frames first)
        For now, we'll return a basic description
        """
        try:
            # For videos, we could:
            # 1. Extract key frames
            # 2. Generate captions for frames
            # 3. Combine into video description
            # For now, return a placeholder
            
            logger.info(f"Processing video: {video_url}")
            return "Video file - automatic captioning not yet implemented"
            
        except Exception as e:
            logger.error(f"Error processing video {video_url}: {e}")
            return None
    
    def generate_enhanced_caption(self, image_url: str) -> Optional[dict]:
        """
        Generate multiple types of descriptions for richer metadata
        """
        try:
            captions = {}
            
            # Basic caption
            basic_caption = self.generate_caption(image_url, "caption")
            if basic_caption:
                captions["caption"] = basic_caption
            
            # Try question answering for more details
            try:
                # What is in this image?
                detailed = replicate.run(self.blip_model, input={
                    "image": image_url,
                    "task": "question_answering",
                    "question": "What objects, people, and activities are in this image?"
                })
                if detailed:
                    captions["detailed"] = detailed.strip()
            except:
                pass
            
            return captions if captions else None
            
        except Exception as e:
            logger.error(f"Error generating enhanced caption: {e}")
            return None
    
    def extract_tags_from_caption(self, caption: str) -> list:
        """
        Extract relevant tags from caption text
        """
        if not caption:
            return []
        
        # Simple keyword extraction - you could use more sophisticated NLP here
        common_objects = [
            "person", "people", "man", "woman", "child", "baby",
            "car", "bike", "bicycle", "motorcycle", "truck", "bus",
            "dog", "cat", "bird", "horse", "animal",
            "tree", "flower", "grass", "sky", "cloud", "mountain", "beach", "ocean",
            "house", "building", "street", "road", "bridge",
            "food", "cake", "pizza", "burger", "drink",
            "phone", "computer", "laptop", "camera",
            "happy", "smile", "laughing", "sad", "excited"
        ]
        
        caption_lower = caption.lower()
        found_tags = []
        
        for obj in common_objects:
            if obj in caption_lower:
                found_tags.append(obj)
        
        return list(set(found_tags))  # Remove duplicates 