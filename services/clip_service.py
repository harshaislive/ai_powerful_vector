import httpx
import logging
from typing import List, Optional
import asyncio

from config import config
from models import EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)

class ClipService:
    def __init__(self):
        self.base_url = config.CLIP_SERVICE_URL.rstrip('/')
        self.client = httpx.AsyncClient(timeout=60.0)
        
        logger.info(f"CLIP service initialized with URL: {self.base_url}")
    
    async def get_image_embedding(self, image_url: str) -> Optional[List[float]]:
        """
        Get embedding for an image using the CLIP service
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            List of embedding values or None if failed
        """
        try:
            logger.info(f"Getting image embedding for: {image_url}")
            
            # Download the image first
            image_response = await self.client.get(image_url)
            image_response.raise_for_status()
            
            # Send to CLIP service
            files = {
                "file": ("image", image_response.content, "image/jpeg")
            }
            
            response = await self.client.post(
                f"{self.base_url}/embed/image",
                files=files
            )
            response.raise_for_status()
            
            result = response.json()
            embedding = result.get("embedding")
            
            if embedding:
                logger.info(f"Successfully generated embedding with {len(embedding)} dimensions")
                return embedding
            else:
                logger.error("No embedding returned from CLIP service")
                return None
                
        except Exception as e:
            logger.error(f"Error getting image embedding: {e}")
            return None
    
    async def get_text_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get embedding for text using the CLIP service
        
        Args:
            text: Text to embed
            
        Returns:
            List of embedding values or None if failed
        """
        try:
            logger.info(f"Getting text embedding for: {text[:50]}...")
            
            response = await self.client.post(
                f"{self.base_url}/embed/text",
                params={"text": text}
            )
            response.raise_for_status()
            
            result = response.json()
            embedding = result.get("embedding")
            
            if embedding:
                logger.info(f"Successfully generated text embedding with {len(embedding)} dimensions")
                return embedding
            else:
                logger.error("No embedding returned from CLIP service")
                return None
                
        except Exception as e:
            logger.error(f"Error getting text embedding: {e}")
            return None
    
    async def calculate_similarity(self, query_embedding: List[float], target_embeddings: List[List[float]]) -> Optional[List[float]]:
        """
        Calculate similarity scores between query embedding and target embeddings
        
        Args:
            query_embedding: Query embedding vector
            target_embeddings: List of target embedding vectors
            
        Returns:
            List of similarity scores or None if failed
        """
        try:
            payload = {
                "query_embedding": query_embedding,
                "target_embeddings": target_embeddings
            }
            
            response = await self.client.post(
                f"{self.base_url}/similarity/search",
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            scores = result.get("similarity_scores")
            
            if scores:
                logger.info(f"Calculated similarity for {len(scores)} targets")
                return scores
            else:
                logger.error("No similarity scores returned")
                return None
                
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return None
    
    async def get_embedding_for_file(self, file_path: str, file_type: str, caption: Optional[str] = None) -> Optional[List[float]]:
        """
        Get embedding for a file, combining image and text embeddings if available
        
        Args:
            file_path: Path to the file (used to get public URL)
            file_type: Type of file ('image' or 'video')
            caption: Optional caption text
            
        Returns:
            Combined embedding or None if failed
        """
        try:
            embeddings = []
            
            # For images, get image embedding
            if file_type == "image":
                # This would need the public URL - we'll get it from the calling function
                pass
            
            # If we have a caption, get text embedding
            if caption:
                text_embedding = await self.get_text_embedding(caption)
                if text_embedding:
                    embeddings.append(text_embedding)
            
            # For now, return the text embedding if available
            # In a more sophisticated setup, you might combine image and text embeddings
            if embeddings:
                return embeddings[0]  # Return first available embedding
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting embedding for file {file_path}: {e}")
            return None
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            asyncio.create_task(self.close())
        except Exception:
            pass 