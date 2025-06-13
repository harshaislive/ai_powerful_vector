import replicate
import logging
from typing import Optional, List
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
    
    def generate_caption(self, image_url: str, task: str = "image_captioning") -> Optional[str]:
        """
        Generate caption for an image using BLIP model
        
        Args:
            image_url: Public URL of the image
            task: Task type - "image_captioning" for image captioning
        
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
    
    async def generate_caption_async(self, image_url: str, task: str = "image_captioning") -> Optional[str]:
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
    
    async def analyze_video_frames(self, frame_paths: List[str]) -> Optional[str]:
        """
        Analyze extracted video frames and generate a comprehensive video description
        
        Args:
            frame_paths: List of paths to extracted frame images
            
        Returns:
            Combined video description or None if failed
        """
        try:
            if not frame_paths:
                logger.warning("No frames provided for video analysis")
                return "Video file - no frames extracted for analysis"
            
            logger.info(f"Analyzing {len(frame_paths)} video frames")
            
            frame_captions = []
            frame_details = []
            
            # Analyze each frame
            for i, frame_path in enumerate(frame_paths):
                try:
                    # Convert local path to URL for Replicate API
                    # Note: This assumes frames are served via the /files endpoint
                    frame_filename = os.path.basename(frame_path)
                    frame_url = f"{config.SERVER_URL}/files/{frame_filename}"
                    
                    # Generate caption for this frame
                    caption = await self.generate_caption_async(frame_url, "image_captioning")
                    
                    if caption:
                        frame_captions.append(caption)
                        
                        # Try to get more detailed description
                        try:
                            detailed = await self.generate_caption_async(frame_url, "visual_question_answering")
                            if detailed and detailed != caption:
                                frame_details.append(detailed)
                        except:
                            pass
                        
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
            video_description = self._combine_frame_captions(frame_captions, frame_details)
            
            logger.info(f"Generated video description: {video_description}")
            return video_description
            
        except Exception as e:
            logger.error(f"Error analyzing video frames: {e}")
            return "Video file - analysis error"
    
    def _combine_frame_captions(self, frame_captions: List[str], frame_details: List[str] = None) -> str:
        """
        Intelligently combine frame captions into a coherent video description
        
        Args:
            frame_captions: List of captions for each frame
            frame_details: Optional detailed descriptions
            
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
                return f"Video showing {unique_captions[0].lower()}, followed by {unique_captions[1].lower()}, and ending with {unique_captions[2].lower()}"
            else:
                # For longer videos, create a more structured description
                beginning = unique_captions[0].lower()
                middle_parts = unique_captions[1:-1]
                ending = unique_captions[-1].lower()
                
                if middle_parts:
                    middle_text = ", ".join([cap.lower() for cap in middle_parts])
                    return f"Video beginning with {beginning}, showing {middle_text}, and ending with {ending}"
                else:
                    return f"Video beginning with {beginning} and ending with {ending}"
                    
        except Exception as e:
            logger.error(f"Error combining frame captions: {e}")
            return "Video with multiple scenes"
    
    def extract_video_tags(self, video_description: str, frame_captions: List[str] = None) -> List[str]:
        """
        Extract tags from video description and frame captions
        
        Args:
            video_description: Combined video description
            frame_captions: Individual frame captions
            
        Returns:
            List of relevant tags
        """
        try:
            tags = set(["video"])  # Always include 'video' tag
            
            # Extract tags from main description
            if video_description:
                description_tags = self.extract_tags_from_caption(video_description)
                tags.update(description_tags)
            
            # Extract tags from individual frame captions
            if frame_captions:
                for caption in frame_captions:
                    frame_tags = self.extract_tags_from_caption(caption)
                    tags.update(frame_tags)
            
            # Add video-specific tags
            video_keywords = [
                "motion", "movement", "action", "sequence", "scene", "clip",
                "footage", "recording", "film", "movie", "animation"
            ]
            
            description_lower = video_description.lower() if video_description else ""
            for keyword in video_keywords:
                if keyword in description_lower:
                    tags.add(keyword)
            
            return list(tags)
            
        except Exception as e:
            logger.error(f"Error extracting video tags: {e}")
            return ["video"]
    
    def generate_enhanced_caption(self, image_url: str) -> Optional[dict]:
        """
        Generate multiple types of descriptions for richer metadata
        """
        try:
            captions = {}
            
            # Basic caption
            basic_caption = self.generate_caption(image_url, "image_captioning")
            if basic_caption:
                captions["caption"] = basic_caption
            
            # Try question answering for more details
            try:
                # What is in this image?
                detailed = replicate.run(self.blip_model, input={
                    "image": image_url,
                    "task": "visual_question_answering",
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