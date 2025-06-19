# Search Logic Documentation - Dropbox Vector Search Engine

## Overview

This document provides a comprehensive explanation of how the search functionality works in the Dropbox Vector Search Engine application. The system uses AI-powered vector search combined with traditional text search to find relevant images and videos from Dropbox.

## Architecture Overview

The search system consists of several key components:

1. **Frontend Search Interface** (`templates/search.html`)
2. **API Endpoints** (`main.py`)
3. **Processing Service** (`services/processing_service.py`)
4. **Vector Database** (`services/weaviate_service.py`)
5. **CLIP Embedding Service** (`services/clip_service.py`)
6. **Video Processing** (`services/video_service.py`)

## Complete Search Flow

### 1. User Initiates Search

**Frontend (`templates/search.html`)**
```javascript
// User types query and submits form
function performSearch(event) {
    const query = document.getElementById('searchInput').value.trim();
    const fileType = document.getElementById('fileTypeFilter').value;
    const limit = document.getElementById('limitFilter').value;
    
    const searchData = {
        query: query,
        limit: parseInt(limit),
        file_types: fileType ? [fileType] : null
    };
    
    // POST to /api/search
    fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(searchData)
    })
}
```

### 2. API Endpoint Processing

**Main API Handler (`main.py:796-827`)**
```python
@app.post("/api/search")
async def search_files(search_request: SearchRequest):
    """Search files using vector similarity and text search"""
    start_time = datetime.now()
    
    # Call processing service to perform search
    results = await processing_service.search_files(
        query=search_request.query,
        limit=search_request.limit,
        file_types=search_request.file_types
    )
    
    processing_time = (datetime.now() - start_time).total_seconds()
    
    # Return structured response
    return SearchResponse(
        results=search_results,
        total_count=len(search_results),
        query=search_request.query,
        processing_time=processing_time
    )
```

### 3. Processing Service - Dual Search Strategy

**Processing Service (`services/processing_service.py:558-601`)**

The system uses a **dual search approach**:

```python
async def search_files(self, query: str, limit: int = 10, file_types: Optional[List[str]] = None):
    """Search files using both vector similarity and text search"""
    results = []
    
    # 1. VECTOR SEARCH - Convert query to embedding and find similar vectors
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
    
    # 2. TEXT SEARCH - Search in captions and tags
    text_results = self.weaviate_service.search_by_text(query, limit=limit)
    results.extend([{
        "source": "text",
        "result": result
    } for result in text_results])
    
    # 3. DEDUPLICATION & RANKING
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
```

## Vector Creation Process

### How Vectors Are Generated

Vectors are created during the file processing pipeline, not during search. Here's how:

#### 1. File Processing Trigger

Files are processed through several methods:
- **Smart Processing**: Only processes changed files (`smart_process()`)
- **Initial Processing**: Processes all cached files (`process_all_files()`)
- **Scheduled Processing**: Daily processing of new files

#### 2. Single File Processing

**Processing Service (`services/processing_service.py:343-557`)**

```python
async def _process_single_file(self, dropbox_file: DropboxFile) -> Optional[ProcessedFile]:
    """Process a single file to generate embeddings and metadata"""
    
    # 1. GENERATE CAPTION
    if dropbox_file.file_type == "image":
        # Use Azure Vision or Replicate BLIP for image captions
        if self.use_azure_vision:
            caption = await self.azure_vision_service.get_image_caption(public_url)
        else:
            caption = await self.replicate_service.generate_caption(public_url)
    
    elif dropbox_file.file_type == "video":
        # Extract frames and generate caption from key frames
        frames = await self.video_service.extract_frames_async(temp_path, dropbox_file.id)
        if frames:
            frame_captions = []
            for frame_path in frames:
                frame_caption = await self.replicate_service.generate_caption(frame_url)
                frame_captions.append(frame_caption)
            # Combine frame captions
            caption = f"Video showing: {', '.join(frame_captions)}"
    
    # 2. GENERATE EMBEDDING FROM CAPTION
    embedding = await self.clip_service.get_text_embedding(caption)
    
    # 3. EXTRACT TAGS (from caption analysis)
    tags = self._extract_tags_from_caption(caption)
    
    # 4. CREATE PROCESSED FILE OBJECT
    processed_file = ProcessedFile(
        id=dropbox_file.id,
        dropbox_path=dropbox_file.path_display,
        file_name=dropbox_file.name,
        file_type=dropbox_file.file_type,
        embedding=embedding,  # This is the vector!
        caption=caption,
        tags=tags,
        # ... other metadata
    )
    
    # 5. STORE IN WEAVIATE
    success = self.weaviate_service.store_file(processed_file)
    
    return processed_file if success else None
```

#### 3. CLIP Service - Text to Vector Conversion

**CLIP Service (`services/clip_service.py:64-89`)**

```python
async def get_text_embedding(self, text: str) -> Optional[List[float]]:
    """Get embedding for text using the CLIP service"""
    
    # Send text to external CLIP service
    response = await self.client.post(
        f"{self.base_url}/embed/text",
        params={"text": text}
    )
    
    result = response.json()
    embedding = result.get("embedding")  # Returns 512-dimensional vector
    
    return embedding
```

#### 4. Video Processing - Frame Extraction

**Video Service (`services/video_service.py:61-147`)**

For videos, the system:

1. **Extracts Key Frames** using FFmpeg at strategic intervals
2. **Generates Captions** for each frame using BLIP
3. **Combines Frame Captions** into a comprehensive video description
4. **Creates Video Embedding** from the combined caption

```python
def extract_frames(self, video_path: str, video_id: str) -> List[str]:
    """Extract key frames from video for analysis"""
    
    # Calculate optimal frame extraction times
    frame_times = self._calculate_frame_times(duration)
    
    for time_seconds in frame_times:
        # Extract frame using FFmpeg
        ffmpeg.input(video_path, ss=time_seconds).output(frame_path, vframes=1).run()
    
    return extracted_frames
```

## Vector Storage in Weaviate

### Schema Structure

**Weaviate Service (`services/weaviate_service.py:40-130`)**

Files are stored in Weaviate with this schema:

```python
class_schema = {
    "class": "DropboxFile",
    "vectorizer": "none",  # We provide our own vectors
    "properties": [
        {"name": "dropbox_id", "dataType": ["string"]},
        {"name": "dropbox_path", "dataType": ["string"]},
        {"name": "file_name", "dataType": ["string"]},
        {"name": "file_type", "dataType": ["string"]},
        {"name": "caption", "dataType": ["string"]},
        {"name": "tags", "dataType": ["string[]"]},
        {"name": "embedding", "dataType": ["number[]"]},  # The vector!
        # ... other properties
    ]
}
```

### Vector Storage

```python
def store_file(self, processed_file: ProcessedFile) -> bool:
    """Store a processed file with its vector in Weaviate"""
    
    data_object = {
        "dropbox_id": processed_file.id,
        "caption": processed_file.caption,
        "tags": processed_file.tags,
        # ... other properties
    }
    
    # Store with vector
    self.client.data_object.create(
        data_object=data_object,
        class_name="DropboxFile",
        vector=processed_file.embedding  # 512-dimensional vector
    )
```

## Search & Scoring Logic

### 1. Vector Similarity Search

**Weaviate Service (`services/weaviate_service.py:267-347`)**

```python
def search_similar(self, query_embedding: List[float], limit: int = 10, file_types: Optional[List[str]] = None):
    """Search for similar files using vector similarity"""
    
    query_builder = (
        self.client.query
        .get("DropboxFile", [
            "dropbox_path", "file_name", "file_type", 
            "caption", "tags", "public_url", "thumbnail_url"
        ])
        .with_near_vector({
            "vector": query_embedding,
            "distance": 0.8  # Maximum distance threshold
        })
        .with_limit(limit)
        .with_additional(["distance", "id"])
    )
    
    # Add file type filters if specified
    if file_types:
        where_filter = {
            "path": ["file_type"],
            "operator": "Equal",
            "valueText": file_types[0]
        }
        query_builder = query_builder.with_where(where_filter)
    
    result = query_builder.do()
    
    # Convert distance to similarity score
    for file_data in files:
        additional = file_data.get("_additional", {})
        distance = float(additional.get("distance", 0))
        similarity_score = 1.0 - distance  # Higher score = more similar
```

### 2. Text Search

**Weaviate Service (`services/weaviate_service.py:349-413`)**

```python
def search_by_text(self, query_text: str, limit: int = 10):
    """Search files by text in captions and tags"""
    
    result = (
        self.client.query
        .get("DropboxFile", [...])
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
        .do()
    )
```

## Scoring System

The app uses a **dual scoring approach**:

### 1. Vector Similarity Scoring

- **Distance Calculation**: Weaviate calculates cosine distance between query vector and stored vectors
- **Similarity Conversion**: `similarity_score = 1.0 - distance`
- **Range**: 0.0 (no similarity) to 1.0 (identical)
- **Threshold**: Maximum distance of 0.8 (minimum similarity of 0.2)

### 2. Text Search Scoring

- **Text Matches**: Get similarity score of 1.0 (perfect match indicator)
- **Combines**: Results from both caption and tag matches

### 3. Result Ranking

```python
# Combine results and remove duplicates
unique_results = []
seen_paths = set()

for item in results:
    result = item["result"]
    if result.dropbox_path not in seen_paths:
        seen_paths.add(result.dropbox_path)
        unique_results.append(item)

# Sort by similarity score (descending)
unique_results.sort(key=lambda x: x["result"].similarity_score, reverse=True)
```

## Frontend Result Display

### Result Processing

**Frontend (`templates/search.html:537-591`)**

```javascript
function displayResults(data) {
    currentResults = data.results || [];
    
    // Show search metadata
    document.getElementById('resultsInfo').innerHTML = `
        <h4>Found ${data.total_count} results for "${data.query}"</h4>
        <p class="text-muted">Search completed in ${data.processing_time.toFixed(2)} seconds</p>
    `;
    
    // Display in grid or list view
    if (currentView === 'grid') {
        displayGridResults();
    } else {
        displayListResults();
    }
}
```

### Grid Item Creation

```javascript
function createGridItem(result, index) {
    // Show similarity score as percentage
    const similarityPercentage = (result.similarity_score * 100).toFixed(1);
    
    item.innerHTML = `
        <div class="result-image-container">
            <img src="${thumbnailUrl}" alt="${result.file_name}">
            <div class="result-overlay">
                <div class="result-meta">
                    <span class="file-type-badge">${result.file_type.toUpperCase()}</span>
                    <span class="similarity-score">${similarityPercentage}%</span>
                </div>
            </div>
        </div>
        <div class="result-caption">${truncatedCaption}</div>
    `;
}
```

## Performance Optimizations

### 1. Thumbnails
- **Image Optimization**: Uses thumbnail URLs for faster loading
- **Fallback Strategy**: Falls back to full images if thumbnails fail
- **Video Thumbnails**: Extracts video frames as thumbnails

### 2. Caching
- **Local Cache**: Uses SQLite cache for Dropbox file metadata
- **Smart Processing**: Only processes changed files
- **Duplicate Detection**: Uses content hashes to avoid reprocessing

### 3. Batch Processing
- **Configurable Batch Size**: Processes files in batches (config.BATCH_SIZE)
- **Background Processing**: Uses FastAPI background tasks
- **Progress Tracking**: Real-time processing status updates

## Search Query Examples

### Vector Search Examples
- **"people smiling"** → Finds images with people showing happy expressions
- **"sunset beach"** → Finds beach scenes during sunset
- **"birthday party"** → Finds celebration/party scenes
- **"dogs playing"** → Finds images/videos of dogs in playful activities

### Text Search Examples
- **"wedding"** → Matches files with "wedding" in captions or tags
- **"vacation"** → Matches travel-related content
- **"Christmas"** → Matches holiday-themed content

## Error Handling

### 1. Search Failures
```python
try:
    results = await processing_service.search_files(...)
except Exception as e:
    logger.error(f"Error in search: {e}")
    raise HTTPException(status_code=500, detail=str(e))
```

### 2. Missing Embeddings
- Falls back to text-only search if vector generation fails
- Graceful degradation when CLIP service is unavailable

### 3. Frontend Error Handling
```javascript
.catch(error => {
    console.error('Search error:', error);
    hideLoading();
    showError('Search failed. Please try again.');
});
```

## Configuration

Key configuration options affecting search:

```python
# config.py
CLIP_SERVICE_URL = "https://clip-service.example.com"
WEAVIATE_URL = "https://weaviate-cluster.example.com"
BATCH_SIZE = 10
USE_THUMBNAILS = True
VIDEO_ANALYSIS_ENABLED = True
MAX_FRAMES_PER_VIDEO = 5
VIDEO_FRAME_INTERVAL = 30  # seconds
```

## Summary

The search system provides a sophisticated AI-powered search experience by:

1. **Processing Files**: Converting images/videos to vectors via CLIP embeddings
2. **Dual Search**: Combining vector similarity and text matching
3. **Smart Scoring**: Using cosine similarity for ranking
4. **Fast Results**: Optimized with thumbnails and caching
5. **Rich Display**: Showing similarity scores and metadata

The result is a search engine that understands the semantic content of images and videos, allowing users to find files using natural language descriptions. 