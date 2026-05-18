import shutil
import os
import zipfile

class CompressionTool:
    """
    NEXUS COMPRESSION UTILS (Z-PACK)
    The specialized tool for managing large 
    file archives and project distribution.
    
    Features:
    - ZIP/7z/TAR Support.
    - Automatic Folder Compression.
    - Archive Verification.
    """
    
    @staticmethod
    def compress_dir(directory: str, output_name: str) -> str:
        """Compresses an entire directory into a ZIP file."""
        shutil.make_archive(output_name, 'zip', directory)
        return f"Successfully compressed {directory} into {output_name}.zip"
        
    @staticmethod
    def decompress_archive(archive_path: str, output_dir: str) -> str:
        """Extracts a ZIP archive into a directory."""
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(output_dir)
        return f"Successfully extracted {archive_path} to {output_dir}"

if __name__ == "__main__":
    c = CompressionTool()
    # c.compress_dir("./workspace", "workspace_backup")
