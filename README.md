# Dropbox Vector Search Engine

A powerful AI-driven search engine for your Dropbox images and videos using CLIP embeddings, BLIP captions, and Weaviate vector database.

## Features

- 🔍 **AI-Powered Search**: Search through images and videos using natural language
- 🖼️ **Image Analysis**: Advanced caption generation using Azure Computer Vision (with BLIP fallback)
- 🧠 **Vector Embeddings**: CLIP embeddings for semantic similarity search
- 📊 **Rich Metadata**: Extract tags, file information, and metadata with confidence scores
- ⏰ **Automated Processing**: Daily cron jobs to process new files
- 🌐 **Web Interface**: Beautiful dashboard and search interface
- 🚀 **Scalable**: Designed for deployment on Railway/Docker

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Dropbox API   │    │  Replicate API  │    │  CLIP Service   │
│                 │    │   (BLIP Model)  │    │   (Railway)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   FastAPI App   │
                    │                 │
                    └─────────────────┘
                                 │
                    ┌─────────────────┐
                    │    Weaviate     │
                    │ Vector Database │
                    │   (Railway)     │
                    └─────────────────┘
```

## Setup Instructions

### Prerequisites

1. **Dropbox App**: Create a Dropbox app and get:
   - Client ID
   - Client Secret
   - Refresh Token

2. **Azure Computer Vision API**: Get your API key from [Azure Portal](https://portal.azure.com) (Primary)

3. **Replicate API**: Get your API token from [Replicate](https://replicate.com) (Fallback)

4. **CLIP Service**: Deploy your CLIP service on Railway (or use existing one)

5. **Weaviate**: Deploy Weaviate on Railway (or use existing instance)

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd ai_vector_powerful
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment**
```bash
cp env.example .env
# Edit .env with your actual credentials
```

4. **Run the application**
```bash
python main.py
```

The application will be available at `http://localhost:8000`

### Environment Variables

Copy `env.example` to `.env` and configure:

```bash
# Dropbox Configuration
DROPBOX_CLIENT_ID=your_dropbox_client_id
DROPBOX_CLIENT_SECRET=your_dropbox_client_secret
DROPBOX_REFRESH_TOKEN=your_dropbox_refresh_token

# Azure Computer Vision Configuration (Primary)
AZURE_VISION_ENDPOINT=https://imagevisionharsha.cognitiveservices.azure.com
AZURE_VISION_API_KEY=your_azure_vision_api_key

# Replicate Configuration (Fallback)
REPLICATE_API_TOKEN=r8_your_replicate_api_token

# CLIP Service Configuration
CLIP_SERVICE_URL=https://your-clip-service.railway.app

# Weaviate Configuration
WEAVIATE_URL=https://weaviate-wdke-production.up.railway.app/
# WEAVIATE_API_KEY=  # Optional - only needed if your Weaviate requires authentication

# Application Configuration
APP_HOST=0.0.0.0
APP_PORT=8000

# Server URL for external access (for Railway, leave blank - auto-detected)
SERVER_URL=

# Processing Configuration
BATCH_SIZE=10

# Optimization Configuration (New Features)
USE_THUMBNAILS=true                    # Process images using thumbnails instead of full size
THUMBNAIL_SIZE=medium                  # Thumbnail size: small, medium, large
USE_VIDEO_PREVIEWS=true               # Generate video previews/thumbnails
SKIP_DUPLICATE_FILES=true             # Skip files that haven't changed
TRACK_CONTENT_HASH=true               # Track file content hash for duplicate detection

# Cron Job Configuration
CRON_HOUR=22
CRON_MINUTE=0
```

## Enabling Weaviate Authentication (Optional)

If you want to secure your Railway Weaviate instance with API key authentication, set these environment variables in your **Railway Weaviate service** (not in this application):

```bash
AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false
AUTHENTICATION_APIKEY_ENABLED=true
AUTHENTICATION_APIKEY_ALLOWED_KEYS=your-secret-key-1,another-key-2
AUTHENTICATION_APIKEY_USERS=admin-user,read-user
AUTHORIZATION_RBAC_ENABLED=true          # Optional: Enable role-based access control
AUTHORIZATION_RBAC_ROOT_USERS=admin-user # Optional: Define admin users
```

**Steps to enable authentication:**
1. Go to your Railway project dashboard
2. Select your Weaviate service
3. Go to the "Variables" tab
4. Add the above environment variables
5. Set `WEAVIATE_API_KEY` in this application to one of your allowed keys

**Important notes:**
- The number of keys in `AUTHENTICATION_APIKEY_ALLOWED_KEYS` must match the number of users in `AUTHENTICATION_APIKEY_USERS`
- Each key corresponds to the user in the same position in the lists
- After enabling authentication, anonymous access will be disabled

## Usage

### 1. Dashboard
Visit `http://localhost:8000` to access the dashboard where you can:
- View system statistics
- Monitor processing status
- Start manual processing
- Quick search functionality

### 2. Processing Files
- **Process All Files**: Processes all images and videos in your Dropbox
- **Process New Files**: Processes files modified in the last 24 hours
- **Automated Processing**: Runs daily at 10 PM (configurable)

### 3. Searching
Visit `http://localhost:8000/search` to search your files:
- Natural language queries: "people smiling", "sunset beach", "birthday party"
- Filter by file type (images/videos)
- Adjust result limits
- View similarity scores

### 4. API Endpoints

#### GET `/api/health`
Health check endpoint

#### GET `/api/stats`
Get system statistics

#### GET `/api/status`
Get current processing status

#### POST `/api/process/all`
Start processing all files

#### POST `/api/process/new`
Start processing new files

#### POST `/api/search`
Search files (JSON body with SearchRequest)

#### GET `/api/search?q=query`
Search files (URL parameters)

## Docker Deployment

### Build and run locally:
```bash
docker build -t dropbox-vector-search .
docker run -p 8000:8000 --env-file .env dropbox-vector-search
```

### Deploy to Railway:
1. Connect your GitHub repository to Railway
2. Set environment variables in Railway dashboard
3. Deploy automatically on push

## File Processing Flow

1. **Discovery**: Scan Dropbox for supported files (images/videos)
2. **URL Generation**: Create public shared links for each file
3. **Caption Generation**: Use Replicate BLIP model for image captions
4. **Embedding Generation**: Generate CLIP embeddings for images and text
5. **Tag Extraction**: Extract relevant tags from captions
6. **Storage**: Store all data and vectors in Weaviate
7. **Indexing**: Enable fast similarity search

## Supported File Types

**Images**: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`
**Videos**: `.mp4`, `.avi`, `.mov`, `.mkv`, `.wmv`, `.flv`

## Performance Considerations

- **Batch Processing**: Files are processed in configurable batches
- **Rate Limiting**: Respects API rate limits
- **Error Handling**: Robust error handling with retry logic
- **Caching**: Efficient caching of embeddings and metadata
- **Async Processing**: Non-blocking processing for better performance

## Monitoring

### Logs
The application provides comprehensive logging for:
- File processing status
- API calls and responses
- Error tracking
- Performance metrics

### Health Checks
- `/api/health` endpoint for monitoring
- Docker health checks included
- Service dependency checks

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Troubleshooting

### Common Issues

1. **Dropbox Authentication**: Ensure refresh token is valid
2. **CLIP Service**: Verify CLIP service URL is accessible
3. **Weaviate Connection**: Check Weaviate instance status
4. **File Processing Errors**: Check format support

### Debug Mode
Set log level to DEBUG in `main.py` for detailed logging.

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review logs for error details
3. Create an issue on GitHub 

## New Optimization Features ✨

### 1. **Thumbnail Processing for Images**
- **Enabled**: Images are processed using medium-sized thumbnails (640x480) instead of full resolution
- **Benefits**: Faster processing, reduced bandwidth usage, lower costs
- **Configuration**: Set `USE_THUMBNAILS=true` and choose size with `THUMBNAIL_SIZE` (small/medium/large)

### 2. **Video Preview Generation**
- **Enabled**: Video thumbnails and previews are generated when possible
- **Benefits**: Visual previews for videos, faster loading in search results
- **Configuration**: Set `USE_VIDEO_PREVIEWS=true`

### 3. **Smart Duplicate Detection**
- **Enabled**: Files are tracked by content hash to avoid reprocessing unchanged files
- **Benefits**: Dramatically faster processing on subsequent runs
- **Features**:
  - Content hash tracking for change detection
  - Skip processing if file hasn't changed
  - Automatic reprocessing if file is modified
- **Configuration**: Set `SKIP_DUPLICATE_FILES=true` and `TRACK_CONTENT_HASH=true`

### Performance Impact
- **First Run**: Same speed (all files need processing)
- **Subsequent Runs**: 80-90% faster (only new/changed files processed)
- **Bandwidth**: 60-70% reduction for image processing
- **Storage**: Smaller thumbnails for faster loading 