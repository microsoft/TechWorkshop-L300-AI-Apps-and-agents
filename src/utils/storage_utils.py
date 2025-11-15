"""
Azure Storage utilities for AI Foundry integration
Provides helper functions for accessing Azure Blob Storage using Managed Identity
"""

import os
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ClientAuthenticationError
from dotenv import load_dotenv
from typing import Optional, BinaryIO
import logging

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

class StorageManager:
    """
    Manages Azure Blob Storage access with Managed Identity authentication
    """
    
    def __init__(self, storage_account_name: str = None, container_name: str = None):
        """
        Initialize StorageManager with authentication
        
        Args:
            storage_account_name: Azure Storage Account name
            container_name: Blob container name
        """
        self.storage_account_name = storage_account_name or os.getenv("storage_account_name", "")
        self.container_name = container_name or os.getenv("storage_container_name", "zava")
        self.blob_service_client = self._create_blob_service_client()
    
    def _create_blob_service_client(self) -> BlobServiceClient:
        """
        Create BlobServiceClient with appropriate authentication method
        
        Returns:
            Configured BlobServiceClient instance
        """
        if not self.storage_account_name:
            raise ValueError("storage_account_name is required")
        
        account_url = f"https://{self.storage_account_name}.blob.core.windows.net"
        
        try:
            # Try Managed Identity first (works in AI Foundry, App Service, etc.)
            logger.info("Attempting authentication with DefaultAzureCredential (Managed Identity)")
            credential = DefaultAzureCredential()
            return BlobServiceClient(account_url=account_url, credential=credential)
            
        except ClientAuthenticationError as e:
            logger.warning(f"Managed Identity authentication failed: {e}")
            
            # Fallback to connection string for local development
            blob_connection_string = os.getenv("blob_connection_string", "")
            if blob_connection_string:
                logger.info("Falling back to connection string authentication")
                return BlobServiceClient.from_connection_string(blob_connection_string)
            else:
                logger.error("No valid authentication method available")
                raise Exception("No valid authentication method available for Azure Blob Storage")
    
    def upload_blob(self, blob_name: str, data: BinaryIO, content_type: str = None, overwrite: bool = True) -> str:
        """
        Upload a blob to the container
        
        Args:
            blob_name: Name for the blob
            data: Binary data to upload
            content_type: MIME type of the content
            overwrite: Whether to overwrite existing blob
            
        Returns:
            URL of the uploaded blob
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            
            # Set content settings if content_type is provided
            content_settings = None
            if content_type:
                content_settings = ContentSettings(content_type=content_type)
            
            # Upload the blob
            container_client.upload_blob(
                name=blob_name,
                data=data,
                overwrite=overwrite,
                content_settings=content_settings
            )
            
            # Return the blob URL
            blob_url = f"https://{self.storage_account_name}.blob.core.windows.net/{self.container_name}/{blob_name}"
            logger.info(f"Successfully uploaded blob: {blob_url}")
            return blob_url
            
        except Exception as e:
            logger.error(f"Error uploading blob '{blob_name}': {e}")
            raise
    
    def download_blob(self, blob_name: str) -> bytes:
        """
        Download a blob from the container
        
        Args:
            blob_name: Name of the blob to download
            
        Returns:
            Blob content as bytes
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blob_client = container_client.get_blob_client(blob_name)
            
            blob_data = blob_client.download_blob().readall()
            logger.info(f"Successfully downloaded blob: {blob_name}")
            return blob_data
            
        except Exception as e:
            logger.error(f"Error downloading blob '{blob_name}': {e}")
            raise
    
    def list_blobs(self, name_starts_with: str = None) -> list:
        """
        List blobs in the container
        
        Args:
            name_starts_with: Optional prefix filter
            
        Returns:
            List of blob names
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blob_list = container_client.list_blobs(name_starts_with=name_starts_with)
            
            blob_names = [blob.name for blob in blob_list]
            logger.info(f"Found {len(blob_names)} blobs in container '{self.container_name}'")
            return blob_names
            
        except Exception as e:
            logger.error(f"Error listing blobs: {e}")
            raise
    
    def delete_blob(self, blob_name: str) -> bool:
        """
        Delete a blob from the container
        
        Args:
            blob_name: Name of the blob to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blob_client = container_client.get_blob_client(blob_name)
            
            blob_client.delete_blob()
            logger.info(f"Successfully deleted blob: {blob_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting blob '{blob_name}': {e}")
            raise

def get_storage_manager() -> StorageManager:
    """
    Get a configured StorageManager instance
    
    Returns:
        StorageManager instance ready for use
    """
    return StorageManager()

# Convenience function for quick access
def upload_file_to_blob(file_path: str, blob_name: str = None, content_type: str = None) -> str:
    """
    Upload a local file to blob storage
    
    Args:
        file_path: Path to the local file
        blob_name: Name for the blob (defaults to filename)
        content_type: MIME type (auto-detected if None)
        
    Returns:
        URL of the uploaded blob
    """
    import mimetypes
    from pathlib import Path
    
    if not blob_name:
        blob_name = Path(file_path).name
    
    if not content_type:
        content_type, _ = mimetypes.guess_type(file_path)
    
    storage_manager = get_storage_manager()
    
    with open(file_path, 'rb') as file_data:
        return storage_manager.upload_blob(blob_name, file_data, content_type)

# Example usage for AI Foundry
if __name__ == "__main__":
    # Example: List all blobs
    storage_manager = get_storage_manager()
    blobs = storage_manager.list_blobs()
    print(f"Blobs in container: {blobs}")
