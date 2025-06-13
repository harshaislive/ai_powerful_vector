import ffmpeg
import os
import tempfile
import logging
from typing import List, Optional, Tuple
from PIL import Image
import asyncio
import math

from config import config

logger = logging.getLogger(__name__)

class VideoService:
    def __init__(self):
        self.temp_dir = os.path.join(os.getcwd(), "temp_files")
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info("Video service initialized successfully")
    
    def get_video_info(self, video_path: str) -> Optional[dict]:
        """Get video metadata using ffprobe"""
        try:
            probe = ffmpeg.probe(video_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                duration = float(video_stream.get('duration', 0))
                width = int(video_stream.get('width', 0))
                height = int(video_stream.get('height', 0))
                fps = eval(video_stream.get('r_frame_rate', '0/1'))  # Convert fraction to float
                
                return {
                    'duration': duration,
                    'width': width,
                    'height': height,
                    'fps': fps,
                    'format': video_stream.get('codec_name', 'unknown')
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting video info for {video_path}: {e}")
            return None
    
    def extract_frames(self, video_path: str, video_id: str) -> List[str]:
        """
        Extract key frames from video for analysis
        
        Args:
            video_path: Path to the video file
            video_id: Unique identifier for the video
            
        Returns:
            List of paths to extracted frame images
        """
        try:
            if not config.VIDEO_ANALYSIS_ENABLED:
                logger.info("Video analysis disabled, skipping frame extraction")
                return []
            
            # Get video info
            video_info = self.get_video_info(video_path)
            if not video_info:
                logger.error(f"Could not get video info for {video_path}")
                return []
            
            duration = video_info['duration']
            if duration <= 0:
                logger.error(f"Invalid video duration: {duration}")
                return []
            
            # Calculate frame extraction times
            frame_times = self._calculate_frame_times(duration)
            
            extracted_frames = []
            
            for i, time_seconds in enumerate(frame_times):
                try:
                    frame_filename = f"{video_id}_frame_{i}_{int(time_seconds)}s.jpg"
                    frame_path = os.path.join(self.temp_dir, frame_filename)
                    
                    # Extract frame at specific time
                    (
                        ffmpeg
                        .input(video_path, ss=time_seconds)
                        .output(frame_path, vframes=1, format='image2', vcodec='mjpeg')
                        .overwrite_output()
                        .run(capture_stdout=True, capture_stderr=True, quiet=True)
                    )
                    
                    # Verify frame was created and is valid
                    if os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
                        # Verify it's a valid image
                        try:
                            with Image.open(frame_path) as img:
                                img.verify()
                            extracted_frames.append(frame_path)
                            logger.info(f"Extracted frame at {time_seconds}s: {frame_filename}")
                        except Exception as img_error:
                            logger.warning(f"Invalid image frame {frame_path}: {img_error}")
                            if os.path.exists(frame_path):
                                os.remove(frame_path)
                    else:
                        logger.warning(f"Frame extraction failed for time {time_seconds}s")
                        
                except Exception as frame_error:
                    logger.error(f"Error extracting frame at {time_seconds}s: {frame_error}")
                    continue
            
            logger.info(f"Successfully extracted {len(extracted_frames)} frames from video")
            return extracted_frames
            
        except Exception as e:
            logger.error(f"Error extracting frames from {video_path}: {e}")
            return []
    
    def _calculate_frame_times(self, duration: float) -> List[float]:
        """Calculate optimal times to extract frames from video"""
        frame_times = []
        
        # Always extract first frame (but not at 0 to avoid black frames)
        frame_times.append(min(2.0, duration * 0.1))
        
        if duration <= 10:
            # Short video: extract beginning, middle, end
            if duration > 5:
                frame_times.append(duration * 0.5)  # Middle
            frame_times.append(duration * 0.9)  # Near end
        else:
            # Longer video: use interval-based extraction
            interval = config.VIDEO_FRAME_INTERVAL
            max_frames = config.MAX_FRAMES_PER_VIDEO - 1  # -1 for the first frame we already added
            
            # Calculate how many frames we can extract with the given interval
            possible_frames = int(duration / interval)
            
            if possible_frames <= max_frames:
                # Use interval-based extraction
                current_time = interval
                while current_time < duration - 2 and len(frame_times) < config.MAX_FRAMES_PER_VIDEO:
                    frame_times.append(current_time)
                    current_time += interval
            else:
                # Too many possible frames, distribute evenly
                for i in range(1, max_frames + 1):
                    time_point = (duration * i) / (max_frames + 1)
                    frame_times.append(time_point)
        
        # Ensure we don't exceed max frames and times are within video duration
        frame_times = [t for t in frame_times if t < duration - 1][:config.MAX_FRAMES_PER_VIDEO]
        
        return sorted(frame_times)
    
    def extract_thumbnail(self, video_path: str, video_id: str) -> Optional[str]:
        """Extract a thumbnail from the video (first meaningful frame)"""
        try:
            if not config.EXTRACT_VIDEO_THUMBNAIL:
                return None
            
            thumbnail_filename = f"{video_id}_thumbnail.jpg"
            thumbnail_path = os.path.join(self.temp_dir, thumbnail_filename)
            
            # Extract thumbnail at 10% of video duration (to avoid black frames)
            video_info = self.get_video_info(video_path)
            if video_info and video_info['duration'] > 0:
                thumbnail_time = min(3.0, video_info['duration'] * 0.1)
            else:
                thumbnail_time = 3.0
            
            (
                ffmpeg
                .input(video_path, ss=thumbnail_time)
                .output(thumbnail_path, vframes=1, format='image2', vcodec='mjpeg', 
                       **{'vf': 'scale=640:360:force_original_aspect_ratio=decrease'})
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            
            if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                logger.info(f"Created video thumbnail: {thumbnail_filename}")
                return thumbnail_path
            else:
                logger.warning(f"Failed to create thumbnail for {video_path}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating thumbnail for {video_path}: {e}")
            return None
    
    def cleanup_frames(self, frame_paths: List[str]):
        """Clean up extracted frame files"""
        for frame_path in frame_paths:
            try:
                if os.path.exists(frame_path):
                    os.remove(frame_path)
                    logger.debug(f"Cleaned up frame: {frame_path}")
            except Exception as e:
                logger.warning(f"Error cleaning up frame {frame_path}: {e}")
    
    async def extract_frames_async(self, video_path: str, video_id: str) -> List[str]:
        """Async version of frame extraction"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.extract_frames,
                video_path,
                video_id
            )
            return result
        except Exception as e:
            logger.error(f"Error in async frame extraction: {e}")
            return []
    
    async def extract_thumbnail_async(self, video_path: str, video_id: str) -> Optional[str]:
        """Async version of thumbnail extraction"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.extract_thumbnail,
                video_path,
                video_id
            )
            return result
        except Exception as e:
            logger.error(f"Error in async thumbnail extraction: {e}")
            return None 