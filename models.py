from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class DropboxFile(BaseModel):
    id: str
    name: str
    path_lower: str
    path_display: str
    size: int
    modified: datetime
    content_hash: Optional[str] = None
    is_downloadable: bool = True
    file_type: str
    extension: str

class EmbeddingRequest(BaseModel):
    text: Optional[str] = None
    image_url: Optional[str] = None

class EmbeddingResponse(BaseModel):
    embedding: List[float]
    dimensions: int

class CaptionRequest(BaseModel):
    image_url: str

class CaptionResponse(BaseModel):
    caption: str

class ProcessedFile(BaseModel):
    id: str
    dropbox_path: str
    file_name: str
    file_type: str
    file_extension: str
    file_size: int
    modified_date: datetime
    processed_date: datetime
    embedding: List[float]
    caption: Optional[str] = None
    tags: List[str] = []
    metadata: Dict[str, Any] = {}
    public_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    file_types: Optional[List[str]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

class SearchResult(BaseModel):
    id: str
    dropbox_path: str
    file_name: str
    file_type: str
    similarity_score: float
    caption: Optional[str] = None
    tags: List[str] = []
    modified_date: datetime
    public_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

class SearchResponse(BaseModel):
    results: List[SearchResult]
    total_count: int
    query: str
    processing_time: float

class ProcessingStatus(BaseModel):
    status: str  # "running", "completed", "failed", "idle"
    files_processed: int
    files_total: int
    current_file: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    errors: List[str] = [] 