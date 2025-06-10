import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Dropbox Configuration
    DROPBOX_CLIENT_ID = os.getenv("DROPBOX_CLIENT_ID")
    DROPBOX_CLIENT_SECRET = os.getenv("DROPBOX_CLIENT_SECRET")
    DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
    
    # Replicate Configuration
    REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
    
    # CLIP Service Configuration
    CLIP_SERVICE_URL = os.getenv("CLIP_SERVICE_URL", "https://your-clip-service.railway.app")
    
    # Weaviate Configuration
    WEAVIATE_URL = os.getenv("WEAVIATE_URL", "https://weaviate-wdke-production.up.railway.app/")
    WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY", "")  # Optional - leave empty if no auth required
    
    # Note: To enable API key authentication on your Railway Weaviate instance, 
    # set these environment variables in Railway:
    # AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false
    # AUTHENTICATION_APIKEY_ENABLED=true  
    # AUTHENTICATION_APIKEY_ALLOWED_KEYS=your-secret-key-1,another-key-2
    # AUTHENTICATION_APIKEY_USERS=admin-user,read-user
    # AUTHORIZATION_RBAC_ENABLED=true (optional, for role-based access)
    # AUTHORIZATION_RBAC_ROOT_USERS=admin-user (optional, defines admin users)
    
    # Application Configuration
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    # Railway automatically assigns PORT environment variable
    APP_PORT = int(os.getenv("PORT") or os.getenv("APP_PORT", 8000))
    
    # Processing Configuration
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 10))
    
    # Optimization Configuration
    USE_THUMBNAILS = os.getenv("USE_THUMBNAILS", "true").lower() == "true"
    THUMBNAIL_SIZE = os.getenv("THUMBNAIL_SIZE", "medium")  # small, medium, large
    USE_VIDEO_PREVIEWS = os.getenv("USE_VIDEO_PREVIEWS", "true").lower() == "true"
    SKIP_DUPLICATE_FILES = os.getenv("SKIP_DUPLICATE_FILES", "true").lower() == "true"
    TRACK_CONTENT_HASH = os.getenv("TRACK_CONTENT_HASH", "true").lower() == "true"
    
    # Supported file types
    SUPPORTED_IMAGE_TYPES = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    SUPPORTED_VIDEO_TYPES = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv'}
    
    # Cron job settings
    CRON_HOUR = int(os.getenv("CRON_HOUR", 22))  # 10 PM
    CRON_MINUTE = int(os.getenv("CRON_MINUTE", 0))

config = Config() 