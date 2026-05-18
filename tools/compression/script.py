import shutil

class CompressionTool:
    """NEXUS COMPRESSION DRIVER 1.0"""
    @staticmethod
    def compress_dir(directory: str, output_name: str) -> str:
        shutil.make_archive(output_name, 'zip', directory)
        return f"Successfully compressed {directory}"
