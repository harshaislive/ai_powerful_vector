#!/usr/bin/env python3
"""
Railway Startup Script for Dropbox Vector Search Engine
Handles cache database initialization and provides deployment-specific optimizations
"""

import os
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - RAILWAY - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_cache_status():
    """Check if cache database exists and provide status"""
    cache_file = Path("dropbox_cache.db")
    
    if cache_file.exists():
        size_mb = cache_file.stat().st_size / (1024 * 1024)
        logger.info(f"🎉 Cache database found! Size: {size_mb:.1f} MB")
        logger.info("✅ This will skip initial cache population and save API calls!")
        return True
    else:
        logger.warning("⚠️ No cache database found - will need to initialize from Dropbox API")
        logger.info("💡 Consider uploading dropbox_cache.db to skip this step")
        return False

def check_environment():
    """Check Railway environment and required variables"""
    logger.info("🔍 Checking Railway environment...")
    
    # Check if running on Railway
    railway_env = os.getenv("RAILWAY_ENVIRONMENT")
    if railway_env:
        logger.info(f"🚂 Running on Railway environment: {railway_env}")
    else:
        logger.info("🏠 Running locally")
    
    # Check critical environment variables
    required_vars = [
        "REPLICATE_API_TOKEN",
        "DROPBOX_CLIENT_ID", 
        "DROPBOX_CLIENT_SECRET",
        "DROPBOX_REFRESH_TOKEN"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        return False
    else:
        logger.info("✅ All required environment variables are set")
        return True

def optimize_for_railway():
    """Apply Railway-specific optimizations"""
    logger.info("⚙️ Applying Railway optimizations...")
    
    # Set optimal batch size for Railway
    os.environ.setdefault("BATCH_SIZE", "5")  # Smaller batches for Railway
    
    # Ensure temp directory exists
    temp_dir = Path("temp_files")
    temp_dir.mkdir(exist_ok=True)
    logger.info(f"📁 Temp directory ready: {temp_dir}")
    
    # Log memory and disk info if available
    try:
        import psutil
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('.')
        logger.info(f"💾 Memory: {memory.available / (1024**3):.1f}GB available")
        logger.info(f"💿 Disk: {disk.free / (1024**3):.1f}GB available")
    except ImportError:
        logger.info("📊 System monitoring not available (psutil not installed)")

def main():
    """Main startup function"""
    logger.info("🚀 Starting Dropbox Vector Search Engine on Railway...")
    
    # Check environment
    if not check_environment():
        logger.error("💥 Environment check failed - some features may not work")
    
    # Check cache status
    cache_exists = check_cache_status()
    
    # Apply optimizations
    optimize_for_railway()
    
    # Provide startup summary
    logger.info("📋 Startup Summary:")
    logger.info(f"   • Cache Database: {'✅ Available' if cache_exists else '❌ Missing'}")
    logger.info(f"   • Environment: {'✅ Complete' if check_environment() else '⚠️ Incomplete'}")
    logger.info(f"   • Batch Size: {os.getenv('BATCH_SIZE', '10')}")
    
    if cache_exists:
        logger.info("🎯 Recommended: Use 'Smart Process' for efficient processing")
    else:
        logger.info("🎯 Recommended: Initialize cache first, then use 'Smart Process'")
    
    logger.info("🌟 Ready to start FastAPI application!")

if __name__ == "__main__":
    main() 