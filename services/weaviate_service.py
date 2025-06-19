import weaviate
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from config import config
from models import ProcessedFile, SearchRequest, SearchResult, SearchResponse

logger = logging.getLogger(__name__)

class WeaviateService:
    def __init__(self):
        try:
            # Initialize Weaviate client
            if config.WEAVIATE_API_KEY and config.WEAVIATE_API_KEY.strip():
                auth_config = weaviate.AuthApiKey(api_key=config.WEAVIATE_API_KEY)
                self.client = weaviate.Client(
                    url=config.WEAVIATE_URL,
                    auth_client_secret=auth_config
                )
                logger.info("Weaviate client initialized with API key authentication")
            else:
                self.client = weaviate.Client(url=config.WEAVIATE_URL)
                logger.info("Weaviate client initialized without authentication")
            
            # Test connection
            if not self.client.is_ready():
                raise ConnectionError("Weaviate is not ready")
            
            # Create schema if it doesn't exist
            self._create_schema()
            
            logger.info("Weaviate service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Weaviate service: {e}")
            raise
    
    def _create_schema(self):
        """Create the schema for storing file embeddings"""
        try:
            # Check if class already exists
            schema = self.client.schema.get()
            class_names = [cls["class"] for cls in schema.get("classes", [])]
            
            if "DropboxFile" not in class_names:
                class_schema = {
                    "class": "DropboxFile",
                    "description": "A file from Dropbox with embeddings and metadata",
                    "vectorizer": "none",  # We'll provide our own vectors
                    "vectorIndexType": "hnsw",  # CRITICAL: Enable vector index
                    "vectorIndexConfig": {
                        "skip": False,
                        "cleanupIntervalSeconds": 300,
                        "pq": {
                            "enabled": False,
                            "bitCompression": False,
                            "segments": 0,
                            "centroids": 256,
                            "encoder": {
                                "type": "kmeans",
                                "distribution": "log-normal"
                            }
                        },
                        "vectorCacheMaxObjects": 1000000,
                        "maxConnections": 64,
                        "efConstruction": 128,
                        "ef": -1,
                        "dynamicEfMin": 100,
                        "dynamicEfMax": 500,
                        "dynamicEfFactor": 8,
                        "distance": "cosine"  # CRITICAL: Set distance metric
                    },
                    "properties": [
                        {
                            "name": "dropbox_id",
                            "dataType": ["string"],
                            "description": "Dropbox file ID"
                        },
                        {
                            "name": "dropbox_path",
                            "dataType": ["string"],
                            "description": "Full path in Dropbox"
                        },
                        {
                            "name": "file_name",
                            "dataType": ["string"],
                            "description": "File name"
                        },
                        {
                            "name": "file_type",
                            "dataType": ["string"],
                            "description": "File type (image/video)"
                        },
                        {
                            "name": "file_extension",
                            "dataType": ["string"],
                            "description": "File extension"
                        },
                        {
                            "name": "file_size",
                            "dataType": ["int"],
                            "description": "File size in bytes"
                        },
                        {
                            "name": "modified_date",
                            "dataType": ["date"],
                            "description": "Last modified date"
                        },
                        {
                            "name": "processed_date",
                            "dataType": ["date"],
                            "description": "Date when processed"
                        },
                        {
                            "name": "caption",
                            "dataType": ["string"],
                            "description": "Generated caption"
                        },
                        {
                            "name": "tags",
                            "dataType": ["string[]"],
                            "description": "Extracted tags"
                        },
                        {
                            "name": "public_url",
                            "dataType": ["string"],
                            "description": "Public URL for the file"
                        },
                        {
                            "name": "thumbnail_url",
                            "dataType": ["string"],
                            "description": "Thumbnail URL"
                        },
                        {
                            "name": "content_hash",
                            "dataType": ["string"],
                            "description": "Dropbox content hash"
                        },
                        {
                            "name": "metadata",
                            "dataType": ["object"],
                            "description": "Additional metadata",
                            "nestedProperties": [
                                {
                                    "name": "content_hash",
                                    "dataType": ["text"],
                                    "description": "Dropbox content hash for duplicate detection"
                                },
                                {
                                    "name": "revision",
                                    "dataType": ["text"],
                                    "description": "Dropbox file revision"
                                },
                                {
                                    "name": "server_modified",
                                    "dataType": ["text"],
                                    "description": "Server modification timestamp"
                                },
                                {
                                    "name": "client_modified",
                                    "dataType": ["text"],
                                    "description": "Client modification timestamp"
                                }
                            ]
                        }
                    ]
                }
                
                self.client.schema.create_class(class_schema)
                logger.info("Created DropboxFile schema in Weaviate with vector index support")
            else:
                logger.info("DropboxFile schema already exists")
                
        except Exception as e:
            logger.error(f"Error creating schema: {e}")
            raise
    
    def validate_vector_setup(self) -> Dict[str, Any]:
        """
        Validate that Weaviate is properly configured for vector search
        
        Returns:
            Dictionary with validation results
        """
        try:
            # Check if schema exists
            schema = self.client.schema.get()
            classes = schema.get("classes", [])
            
            dropbox_class = None
            for cls in classes:
                if cls["class"] == "DropboxFile":
                    dropbox_class = cls
                    break
            
            if not dropbox_class:
                return {
                    "valid": False,
                    "error": "DropboxFile class not found in schema",
                    "recommendations": ["Run schema creation first"]
                }
            
            # Check vector configuration
            vector_config = dropbox_class.get("vectorIndexConfig", {})
            vector_index_type = dropbox_class.get("vectorIndexType")
            
            issues = []
            if vector_index_type != "hnsw":
                issues.append(f"Vector index type is '{vector_index_type}', should be 'hnsw'")
            
            if vector_config.get("skip", True):
                issues.append("Vector indexing is disabled (skip=True)")
            
            if vector_config.get("distance") != "cosine":
                issues.append(f"Distance metric is '{vector_config.get('distance')}', should be 'cosine'")
            
            # Check if we have any data with vectors
            sample_query = (
                self.client.query
                .get("DropboxFile", ["file_name"])
                .with_additional(["vector"])
                .with_limit(1)
                .do()
            )
            
            files = sample_query.get("data", {}).get("Get", {}).get("DropboxFile", [])
            has_vectors = False
            if files:
                vector_data = files[0].get("_additional", {}).get("vector")
                has_vectors = bool(vector_data and len(vector_data) > 0)
            
            return {
                "valid": len(issues) == 0,
                "schema_exists": True,
                "vector_index_type": vector_index_type,
                "vector_config": vector_config,
                "issues": issues,
                "has_sample_vectors": has_vectors,
                "sample_vector_dimensions": len(files[0].get("_additional", {}).get("vector", [])) if files and has_vectors else 0,
                "recommendations": [
                    "Delete and recreate schema if vector config is wrong",
                    "Process some files to generate vectors",
                    "Test vector search functionality"
                ] if issues else ["Vector setup looks good!"]
            }
            
        except Exception as e:
            return {
                "valid": False,
                "error": f"Error validating vector setup: {str(e)}",
                "recommendations": ["Check Weaviate connection", "Verify schema creation"]
            }
    
    def store_file(self, processed_file: ProcessedFile) -> bool:
        """
        Store a processed file in Weaviate
        
        Args:
            processed_file: ProcessedFile object with all metadata and embeddings
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # CRITICAL: Validate embedding exists and has correct dimensions
            if not processed_file.embedding:
                logger.error(f"No embedding provided for file: {processed_file.file_name}")
                return False
            
            if not isinstance(processed_file.embedding, list) or len(processed_file.embedding) == 0:
                logger.error(f"Invalid embedding format for file: {processed_file.file_name}")
                return False
            
            # Log embedding info for debugging
            logger.info(f"Storing file with {len(processed_file.embedding)}-dimensional embedding: {processed_file.file_name}")
            
            # Prepare data object
            data_object = {
                "dropbox_id": processed_file.id,
                "dropbox_path": processed_file.dropbox_path,
                "file_name": processed_file.file_name,
                "file_type": processed_file.file_type,
                "file_extension": processed_file.file_extension,
                "file_size": processed_file.file_size,
                "modified_date": processed_file.modified_date.replace(microsecond=0).isoformat() + "Z",
                "processed_date": processed_file.processed_date.replace(microsecond=0).isoformat() + "Z",
                "caption": processed_file.caption,
                "tags": processed_file.tags,
                "public_url": processed_file.public_url,
                "thumbnail_url": processed_file.thumbnail_url,
                "content_hash": processed_file.metadata.get("content_hash", processed_file.id),  # Store actual content hash
                "metadata": processed_file.metadata
            }
            
            # Check if file already exists by path
            existing = self.get_file_by_path(processed_file.dropbox_path)
            
            if existing:
                # Update existing file WITH VECTOR
                logger.info(f"Updating existing file with vector: {processed_file.file_name}")
                self.client.data_object.update(
                    data_object=data_object,
                    class_name="DropboxFile",
                    uuid=existing["id"],
                    vector=processed_file.embedding  # CRITICAL: Include vector
                )
                logger.info(f"Updated existing file with {len(processed_file.embedding)}-dim vector: {processed_file.file_name}")
            else:
                # Create new file WITH VECTOR
                logger.info(f"Creating new file with vector: {processed_file.file_name}")
                result = self.client.data_object.create(
                    data_object=data_object,
                    class_name="DropboxFile",
                    vector=processed_file.embedding  # CRITICAL: Include vector
                )
                logger.info(f"Created new file with {len(processed_file.embedding)}-dim vector: {processed_file.file_name}")
                logger.debug(f"Weaviate response: {result}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing file {processed_file.file_name}: {e}")
            logger.error(f"Embedding info - Type: {type(processed_file.embedding)}, Length: {len(processed_file.embedding) if processed_file.embedding else 'None'}")
            return False
    
    def get_file_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """Get file by Dropbox path"""
        try:
            result = (
                self.client.query
                .get("DropboxFile", ["dropbox_path", "file_name", "file_type", "caption", "tags", "metadata", "public_url", "thumbnail_url", "content_hash", "processed_date", "file_size", "modified_date"])
                .with_where({
                    "path": ["dropbox_path"],
                    "operator": "Equal",
                    "valueText": path
                })
                .with_additional(["id"])
                .with_limit(1)
                .do()
            )
            
            files = result.get("data", {}).get("Get", {}).get("DropboxFile", [])
            if files:
                file_data = files[0]
                # Add the UUID to the main data
                file_data["id"] = file_data.get("_additional", {}).get("id", "")
                return file_data
            return None
            
        except Exception as e:
            logger.error(f"Error getting file by path {path}: {e}")
            return None

    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file by ID using direct UUID access"""
        try:
            result = self.client.data_object.get(file_id, class_name="DropboxFile")
            
            if result and "properties" in result:
                # Convert the result to match our expected format
                properties = result["properties"]
                file_data = {
                    "id": result.get("id", ""),
                    "dropbox_path": properties.get("dropbox_path", ""),
                    "file_name": properties.get("file_name", ""),
                    "file_type": properties.get("file_type", ""),
                    "caption": properties.get("caption", ""),
                    "tags": properties.get("tags", []),
                    "metadata": properties.get("metadata", {}),
                    "public_url": properties.get("public_url", ""),
                    "thumbnail_url": properties.get("thumbnail_url", "")
                }
                return file_data
            return None
            
        except Exception as e:
            logger.error(f"Error getting file by ID {file_id}: {e}")
            return None
    
    def search_similar(self, query_embedding: List[float], limit: int = 10, 
                      file_types: Optional[List[str]] = None) -> List[SearchResult]:
        """
        Search for similar files using vector similarity
        
        Args:
            query_embedding: Query vector
            limit: Maximum number of results
            file_types: Optional list of file types to filter by
            
        Returns:
            List of SearchResult objects
        """
        try:
            # CRITICAL: Validate query embedding
            if not query_embedding or not isinstance(query_embedding, list):
                logger.error("Invalid query embedding provided for vector search")
                return []
            
            logger.info(f"Performing vector search with {len(query_embedding)}-dimensional embedding")
            
            query_builder = (
                self.client.query
                .get("DropboxFile", [
                    "dropbox_path", "file_name", "file_type", "file_extension",
                    "caption", "tags", "modified_date", "public_url", "thumbnail_url"
                ])
                .with_near_vector({
                    "vector": query_embedding,
                    "distance": 1.5  # Maximum distance threshold (more permissive for real searches)
                })
                .with_limit(limit)
                .with_additional(["distance", "id"])
            )
            
            # Add file type filter if specified
            if file_types:
                where_filter = {
                    "path": ["file_type"],
                    "operator": "Equal",
                    "valueText": file_types[0]
                }
                
                if len(file_types) > 1:
                    # Multiple file types - use OR condition
                    or_conditions = []
                    for file_type in file_types:
                        or_conditions.append({
                            "path": ["file_type"],
                            "operator": "Equal",
                            "valueText": file_type
                        })
                    where_filter = {
                        "operator": "Or",
                        "operands": or_conditions
                    }
                
                query_builder = query_builder.with_where(where_filter)
            
            result = query_builder.do()
            
            files = result.get("data", {}).get("Get", {}).get("DropboxFile", [])
            search_results = []
            
            logger.info(f"Weaviate returned {len(files)} vector search results")
            
            for file_data in files:
                additional = file_data.get("_additional", {})
                distance = float(additional.get("distance", 1.0))  # Default to max distance
                similarity_score = max(0.0, 1.0 - distance)  # Convert distance to similarity, ensure non-negative
                
                # Log similarity for debugging
                logger.debug(f"File: {file_data.get('file_name', 'unknown')} - Distance: {distance:.3f}, Similarity: {similarity_score:.3f}")
                
                search_result = SearchResult(
                    id=additional.get("id", ""),
                    dropbox_path=file_data.get("dropbox_path", ""),
                    file_name=file_data.get("file_name", ""),
                    file_type=file_data.get("file_type", ""),
                    similarity_score=similarity_score,
                    caption=file_data.get("caption"),
                    tags=file_data.get("tags", []),
                    modified_date=datetime.fromisoformat(file_data.get("modified_date", "").replace("Z", "+00:00")),
                    public_url=file_data.get("public_url"),
                    thumbnail_url=file_data.get("thumbnail_url")
                )
                search_results.append(search_result)
            
            logger.info(f"Found {len(search_results)} similar files via vector search")
            return search_results
            
        except Exception as e:
            logger.error(f"Error searching similar files: {e}")
            logger.error(f"Query embedding info - Type: {type(query_embedding)}, Length: {len(query_embedding) if query_embedding else 'None'}")
            return []
    
    def search_by_text(self, query_text: str, limit: int = 10) -> List[SearchResult]:
        """
        Search files by text in captions and tags
        
        Args:
            query_text: Text to search for
            limit: Maximum number of results
            
        Returns:
            List of SearchResult objects
        """
        try:
            result = (
                self.client.query
                .get("DropboxFile", [
                    "dropbox_path", "file_name", "file_type", "file_extension",
                    "caption", "tags", "modified_date", "public_url", "thumbnail_url"
                ])
                .with_where({
                    "operator": "Or",
                    "operands": [
                        {
                            "path": ["caption"],
                            "operator": "Like",
                            "valueText": f"*{query_text}*"
                        },
                        {
                            "path": ["tags"],
                            "operator": "Like",
                            "valueText": f"*{query_text}*"
                        }
                    ]
                })
                .with_limit(limit)
                .with_additional(["id"])
                .do()
            )
            
            files = result.get("data", {}).get("Get", {}).get("DropboxFile", [])
            search_results = []
            
            for file_data in files:
                additional = file_data.get("_additional", {})
                
                search_result = SearchResult(
                    id=additional.get("id", ""),
                    dropbox_path=file_data.get("dropbox_path", ""),
                    file_name=file_data.get("file_name", ""),
                    file_type=file_data.get("file_type", ""),
                    similarity_score=1.0,  # Text search doesn't have similarity score
                    caption=file_data.get("caption"),
                    tags=file_data.get("tags", []),
                    modified_date=datetime.fromisoformat(file_data.get("modified_date", "").replace("Z", "+00:00")),
                    public_url=file_data.get("public_url"),
                    thumbnail_url=file_data.get("thumbnail_url")
                )
                search_results.append(search_result)
            
            logger.info(f"Found {len(search_results)} files matching text query")
            return search_results
            
        except Exception as e:
            logger.error(f"Error searching by text: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored files (simplified for compatibility)"""
        try:
            # Get total count using simple aggregation
            total_result = (
                self.client.query
                .aggregate("DropboxFile")
                .with_meta_count()
                .do()
            )
            
            total_count = total_result.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
            
            # For file type counts, use simple queries since group_by is not available
            image_result = (
                self.client.query
                .aggregate("DropboxFile")
                .with_where({
                    "path": ["file_type"],
                    "operator": "Equal",
                    "valueText": "image"
                })
                .with_meta_count()
                .do()
            )
            
            video_result = (
                self.client.query
                .aggregate("DropboxFile")
                .with_where({
                    "path": ["file_type"],
                    "operator": "Equal",
                    "valueText": "video"
                })
                .with_meta_count()
                .do()
            )
            
            image_count = image_result.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
            video_count = video_result.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
            
            return {
                "total_files": total_count,
                "by_type": {
                    "image": image_count,
                    "video": video_count
                },
                "last_updated": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "total_files": 0,
                "by_type": {
                    "image": 0,
                    "video": 0
                },
                "error": str(e)
            }
    
    def delete_file(self, file_id: str) -> bool:
        """Delete a file from Weaviate"""
        try:
            self.client.data_object.delete(uuid=file_id, class_name="DropboxFile")
            logger.info(f"Deleted file with ID: {file_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file {file_id}: {e}")
            return False 