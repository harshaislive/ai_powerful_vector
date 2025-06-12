# Railway Deployment Setup Guide

## 🚀 Setting Up Persistent Cache on Railway

### 1. Configure Volume for Cache Persistence

In your Railway project dashboard:

1. Go to **Settings** → **Volumes**
2. Click **"Add Volume"**
3. Configure:
   - **Mount Path**: `/app/data`
   - **Size**: 1GB (should be enough for cache database)
   - **Name**: `cache-storage`

### 2. Set Environment Variables

In your Railway project, add these environment variables:

```bash
# Cache Configuration
CACHE_DATA_DIR=/app/data

# Your existing environment variables
DROPBOX_CLIENT_ID=your_client_id
DROPBOX_CLIENT_SECRET=your_client_secret
DROPBOX_REFRESH_TOKEN=your_refresh_token
WEAVIATE_URL=your_weaviate_url
WEAVIATE_API_KEY=your_weaviate_api_key
REPLICATE_API_TOKEN=your_replicate_token
CLIP_SERVER_URL=your_clip_server_url
```

### 3. Deployment Workflow

After setting up the volume and environment variables:

1. **Deploy your application** to Railway
2. **Initialize the cache** using the new API endpoint:
   - Go to your deployed app dashboard
   - Click **"Initialize Cache"** (new button)
   - Wait for cache population to complete
3. **Process files** using:
   - **"Smart Process"** for incremental processing
   - **"Full Sync (Slow)"** for processing all cached files

### 4. New API Endpoints Available

- `POST /api/cache/init` - Initialize cache with full Dropbox sync
- `GET /api/cache/progress` - Get live cache and processing progress
- `POST /api/cache/sync` - Sync cache with latest Dropbox changes
- `GET /api/cache/stats` - Get cache statistics

### 5. Recommended Workflow

1. **First deployment**: Use "Initialize Cache" to populate the cache
2. **Regular processing**: Use "Smart Process" to handle only changed files
3. **Periodic sync**: Use "Sync Cache" to update file listings
4. **Full reprocessing**: Use "Full Sync (Slow)" only when needed

### 6. Benefits After Setup

- ✅ **90%+ reduction** in Dropbox API calls
- ✅ **Instant file listings** from local cache
- ✅ **Incremental processing** only handles changed files
- ✅ **Persistent cache** survives deployments and restarts
- ✅ **Live progress tracking** for all operations

### 7. Troubleshooting

If you see "Using Dropbox API for file listing (slow)" in logs:
- Check that `CACHE_DATA_DIR` environment variable is set
- Verify the volume is mounted correctly
- Ensure the cache has been initialized with "Initialize Cache"

### 8. File Structure in Volume

```
/app/data/
├── dropbox_cache.db          # Main cache database (SQLite)
└── (other persistent files)
```

The cache database will contain metadata for all your Dropbox files, enabling instant queries without API calls. 