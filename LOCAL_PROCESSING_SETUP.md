# Local Image Processing with Azure Vision Setup

## Overview

This setup enables local image processing using Azure Computer Vision API with binary uploads instead of URL-based processing. This approach is more reliable and faster for vector generation.

## What's New

### 1. **Enhanced Azure Vision Service** (`services/azure_vision_service.py`)

Added new methods for local file processing:

- `generate_caption_from_local_file(image_path)` - Process local image files with binary upload
- `analyze_local_image_full(image_path)` - Full analysis with tags and categories  
- `generate_caption_with_tags_from_local(image_path)` - Caption + tags in one call

### 2. **Enhanced Processing Service** (`services/processing_service.py`)

- Modified to use local file processing first, URL processing as fallback
- Better logging for debugging vector generation
- Enhanced error handling

### 3. **Enhanced Dropbox Service** (`services/dropbox_service.py`)

- Added `get_local_file_path(path)` method for direct file system access
- Maintains file caching for efficiency

### 4. **Fixed Weaviate Vector Configuration** (`services/weaviate_service.py`)

- Added proper HNSW vector index configuration
- Enhanced vector validation and logging
- Added diagnostic methods

## Testing the Setup

### Step 1: Check Weaviate Vector Configuration

```bash
python check_weaviate_vectors.py
```

This script will:
- ✅ Validate vector schema configuration
- ✅ Check for existing vectors
- ✅ Test vector search functionality
- ✅ Show sample data

Expected output if working:
```
🎉 Weaviate is properly configured for vector search!
✅ Schema is valid
✅ Vector indexing is enabled
✅ Sample vectors are stored (if files processed)
✅ Vector search is functional
```

### Step 2: Run Complete Pipeline Test

```bash
python test_local_vector_processing.py
```

This comprehensive test will:

1. **🚀 Initialize Services**
   - Dropbox, Azure Vision, CLIP, Weaviate

2. **🔧 Validate Vector Setup**
   - Check Weaviate schema and configuration

3. **📸 Find Test Image**
   - Locate image in Dropbox for testing

4. **⬇️ Download Locally**
   - Download image to local temp directory

5. **🤖 Process with Azure Vision**
   - Send binary data to Azure API
   - Generate caption and tags

6. **🔮 Generate CLIP Embeddings**
   - Convert caption to 512-dimensional vector

7. **💾 Store in Weaviate**
   - Save with proper vector indexing

8. **🔍 Verify Storage**
   - Confirm file is retrievable from Weaviate

9. **🎯 Test Vector Search**
   - Perform semantic search and check results

## Expected Test Output

### Successful Run:
```
🧪 Starting Local Vector Processing Test
============================================================

🚀 Initializing services...
✅ Dropbox service initialized
✅ Azure Computer Vision service initialized  
✅ CLIP service initialized
✅ Weaviate service initialized

============================================================
🔧 Validating vector setup...
Schema exists: True
Vector index type: hnsw
Has sample vectors: True
Sample vector dimensions: 512
✅ Vector setup looks good!

============================================================
🔍 Looking for test images in Dropbox...
📸 Found test image: photo.jpg (/photos/photo.jpg)

============================================================
🧪 Testing local processing for: /photos/photo.jpg

⬇️ Step 1: Downloading image locally...
✅ Downloaded 2048576 bytes to: /temp_files/abc123.jpg

🤖 Step 2: Processing with Azure Computer Vision...
✅ Caption: A group of people standing on a beach
✅ Tags: ['people', 'beach', 'outdoor', 'water', 'sand']

🔮 Step 3: Generating CLIP embedding...
✅ Generated 512-dimensional embedding
✅ Embedding sample: [0.123, -0.456, 0.789, ...]

📦 Step 4: Creating ProcessedFile object...
✅ Created ProcessedFile object

💾 Step 5: Storing in Weaviate...
✅ Successfully stored in Weaviate

🔍 Step 6: Verifying storage...
✅ File successfully retrieved from Weaviate
✅ Stored caption: A group of people standing on a beach
✅ Stored tags: ['people', 'beach', 'outdoor', 'water', 'sand']

============================================================
🔍 Testing vector search with query: 'test image'
✅ Generated query embedding (512 dimensions)
✅ Found 1 search results:
  1. photo.jpg (similarity: 0.742)
     Caption: A group of people standing on a beach
     Tags: ['people', 'beach', 'outdoor', 'water', 'sand']

============================================================
🎉 ALL TESTS PASSED!
✅ Local image processing with Azure Vision works correctly
✅ CLIP embeddings are generated successfully  
✅ Vectors are stored and searchable in Weaviate
✅ Vector search returns relevant results
```

## Benefits of Local Processing

### 1. **Reliability**
- No URL accessibility issues
- No shared link permissions problems
- Direct binary upload to Azure

### 2. **Performance**
- Faster processing with local files
- Better error handling
- Reduced network dependency

### 3. **Quality**
- Full resolution image analysis
- More accurate captions and tags
- Better vector generation

### 4. **Debugging**
- Clear logging at each step
- Easy to identify issues
- Comprehensive error messages

## Configuration Requirements

### Environment Variables:
```env
# Azure Computer Vision
AZURE_VISION_API_KEY=your_azure_key
AZURE_VISION_ENDPOINT=https://your-endpoint.cognitiveservices.azure.com

# CLIP Service
CLIP_SERVICE_URL=https://your-clip-service.com

# Weaviate
WEAVIATE_URL=https://your-weaviate-cluster.com
WEAVIATE_API_KEY=your_weaviate_key

# Dropbox
DROPBOX_CLIENT_ID=your_client_id
DROPBOX_CLIENT_SECRET=your_client_secret
DROPBOX_REFRESH_TOKEN=your_refresh_token
```

## Troubleshooting

### If Vector Validation Fails:

1. **Schema Issues**: 
   - Delete Weaviate data and restart app
   - Schema will be recreated with proper vector config

2. **No Sample Vectors**:
   - Run processing to generate vectors
   - Use Smart Process for efficiency

3. **Vector Search Fails**:
   - Check CLIP service connectivity
   - Verify embedding dimensions match

### If Azure Vision Fails:

1. **API Key Issues**:
   - Verify `AZURE_VISION_API_KEY` is correct
   - Check endpoint URL format

2. **File Access Issues**:
   - Ensure temp directory exists and is writable
   - Check file download permissions

### If Processing Fails:

1. **Service Initialization**:
   - Check all environment variables
   - Verify service connectivity

2. **File Processing**:
   - Ensure you have images in Dropbox
   - Check supported file types in config

## Next Steps

1. **Run the tests** to verify everything works
2. **Process your images** using the app's Smart Process feature
3. **Test search functionality** with semantic queries
4. **Monitor logs** for any issues during processing

The local processing approach will make your vector search much more reliable and accurate! 🎉 